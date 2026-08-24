; =============================================================================
; m7_project.asm — world point -> screen point on the static-affine Mode 7
; plane
; =============================================================================
; One entry point:
;
;  m7p_project X = world x, Y = world y
;  -> carry SET = pre-culled (off-screen at EVERY heading)
;  carry CLEAR = ES_M7P+M7P_SX / +M7P_SY hold signed screen px
;
; THE TRANSPOSE IS THE WHOLE CORRECTNESS QUESTION. The PPU's matrix maps SCREEN
; -> TEXEL; a sprite needs WORLD -> SCREEN, which is its inverse. At the fixed
; scale m7_affine ships, [[A,B],[C,D]] is a pure rotation, so the inverse is
; the transpose [[A,C],[B,D]] — the same four words, read in the other order:
;
;  sx = ((dx*A + dy*C) >> 8) + 128
;  sy = ((dx*B + dy*D) >> 8) + 112
;
; `A,C` for sx and `B,D` for sy. Feed the FORWARD pairing (A,B / C,D) and the
; sprites counter-rotate — they still move and still stay on screen, so it
; passes a casual look while every sprite slides off the world tile it stands
; on. m7_persp_project keeps exactly that as a negative-control build flag for
; the same reason.
;
; NO HARDWARE MULTIPLIER (feature.toml carries the argument). The two products
; per axis are software shift-adds sized to the OPERANDS: the multiplier is the
; world delta, which the pre-cull has already bounded to +-192, so the loop
; runs at most eight iterations and exits the moment the remaining bits are
; zero. A word-width 16-iteration multiply would do twice the work for the same
; answer.

; --- m7_affine's DP shadow, named ------------------------------------------
; The sixteen-byte layout is m7_affine's declared contract (its feature.toml
; lists it in commit order). Naming the offsets here rather than writing the
; raw numbers at four use sites is what makes a future re-order of that shadow
; a one-line change instead of a hunt.
M7P_AFF_A = 0                   ; signed 1.7.8 —  cos(t)
M7P_AFF_B = 2                   ;                 sin(t)
M7P_AFF_C = 4                   ;                -sin(t)
M7P_AFF_D = 6                   ;                 cos(t)
M7P_AFF_X = 8                   ; the affine pivot, world px
M7P_AFF_Y = 10

; --- this feature's own scratch (the m7p dp claim) -------------------------
M7P_DX  = 0                     ; 2 — world delta, signed
M7P_DY  = 2                     ; 2
M7P_SX  = 4                     ; 2 — the answer, signed screen px
M7P_SY  = 6                     ; 2
M7P_MA  = 8                     ; 4 — multiplicand, shifted LEFT through 32 bits
M7P_MB  = 12                    ; 2 — multiplier, shifted RIGHT until zero
M7P_ACC = 14                    ; 4 — signed 32-bit dot-product accumulator

; --- the screen the pivot is centred on ------------------------------------
; m7a_set_center puts the pivot at (128,112) — half of the 256x224 NTSC active
; area — and holds it there at every heading. So the projection's origin is not
; a choice made here; it is that routine's contract, restated.
M7P_SCREEN_CX = 128
M7P_SCREEN_CY = 112

; A 16x16 sprite whose CENTRE is a little outside the raster is still partly
; visible, so the cull window is the raster grown by the sprite's half-size.
M7P_MARGIN = 16
M7P_HX = M7P_SCREEN_CX + M7P_MARGIN     ; 144 — half-width of the padded view
M7P_HY = M7P_SCREEN_CY + M7P_MARGIN     ; 128 — half-height

; THE PRE-CULL RADIUS. Rotation about the pivot preserves distance, so a world
; point farther from the pivot than the padded view's CIRCUMRADIUS cannot land
; inside that view at any heading — the answer is the same for all 256 matrices
; and needs no multiply to reach. This is the smallest integer with that
; property, and both halves of "smallest" and "with that property" are asserted
; below rather than trusted: the value is ceil(hypot(144,128)) = 193, and a
; square-root is not something ca65 can evaluate, so the CHECK is written as
; the squared inequality it is equivalent to.
M7P_R = 193
.assert M7P_R * M7P_R >= M7P_HX * M7P_HX + M7P_HY * M7P_HY, error,  "m7_project: M7P_R is too small — a visible point would be pre-culled"
.assert (M7P_R - 1) * (M7P_R - 1) < M7P_HX * M7P_HX + M7P_HY * M7P_HY, error,  "m7_project: M7P_R is loose — it is not ceil(hypot(M7P_HX, M7P_HY))"

; --- M7P_MAC_LOOP: the shift-add inner loop, add and subtract arms ----------
; Instantiated TWICE by m7p_mac, once per product sign, so the sign is decided
; ONCE per multiply instead of being re-tested on every iteration. The two arms
; are otherwise identical.
;
; acc += ma, then ma <<= 1, for each set bit of mb, low bit first — the
; ordinary long-multiplication of binary, with the partial products accumulated
; in place. The loop tests mb for zero at the TOP, so it costs one iteration
; per significant bit of the multiplier and not one per bit of the word.
;
; No sep/rep here: every arm is A16/I16 throughout, which is why the
; annotations below are bare assertions of the arriving width rather than
; narrowings.
.macro M7P_MAC_LOOP m7p_op
    .local m7p_loop, m7p_skip, m7p_done
m7p_loop:
    .a16
    .i16
    lda z:ES_M7P + M7P_MB
    beq m7p_done                    ; no bits left — the product is complete
    lsr a
    sta z:ES_M7P + M7P_MB
    bcc m7p_skip                    ; this bit is clear: no partial product
.if .xmatch({m7p_op}, {add})
    clc
    lda z:ES_M7P + M7P_ACC + 0
    adc z:ES_M7P + M7P_MA + 0
    sta z:ES_M7P + M7P_ACC + 0
    lda z:ES_M7P + M7P_ACC + 2
    adc z:ES_M7P + M7P_MA + 2
    sta z:ES_M7P + M7P_ACC + 2
.else
    sec
    lda z:ES_M7P + M7P_ACC + 0
    sbc z:ES_M7P + M7P_MA + 0
    sta z:ES_M7P + M7P_ACC + 0
    lda z:ES_M7P + M7P_ACC + 2
    sbc z:ES_M7P + M7P_MA + 2
    sta z:ES_M7P + M7P_ACC + 2
.endif
m7p_skip:
    .a16
    .i16
    asl z:ES_M7P + M7P_MA + 0
    rol z:ES_M7P + M7P_MA + 2       ; ma <<= 1, across all 32 bits
    bra m7p_loop
m7p_done:
    .a16
    .i16
.endmacro

; --- m7p_mac: acc += a * b, signed 16x16 -> signed 32 ----------------------
; In: A16/I16, DB=0. A = a (the multiplicand — a matrix coefficient),
;  Y = b (the multiplier — a world delta).
; Out: A16/I16. ES_M7P+M7P_ACC accumulated. Clobbers A, X, Y.
;
; MAGNITUDES FIRST, SIGN ONCE. Both operands are taken to absolute value and
; the product's sign becomes the choice of loop arm. That is what lets the loop
; exit on the multiplier's significant bits: -3 as a raw 16-bit multiplier has
; fourteen set bits, |−3| has two.
;
; The operand roles are not interchangeable. |b| is bounded by the pre-cull at
; 192, so it is the MULTIPLIER (eight iterations at worst). |a| reaches 256 —
; one bit wider — so it is the multiplicand, and it is held in 32 bits because
; 256 shifted left eight times is $10000 and would vanish from a word.
;
; WIDTH-RISK: A16/I16 on entry and exit, and throughout — there is no sep/rep
; anywhere in this routine or in the loop macro it expands. X is used as a
; two's-complement PARITY counter (0/1/2), not as an index.
m7p_mac:
    .a16
    .i16
    ldx #0
    cmp #0                          ; N = bit 15 of the coefficient
    bpl @a_pos
    eor #$FFFF
    inc a                           ; a = |a|
    inx
@a_pos:
    .a16
    .i16
    sta z:ES_M7P + M7P_MA + 0
    stz z:ES_M7P + M7P_MA + 2       ; |a| <= 256: the high half starts clear
    tya
    cmp #0
    bpl @b_pos
    eor #$FFFF
    inc a                           ; b = |b|
    inx
@b_pos:
    .a16
    .i16
    sta z:ES_M7P + M7P_MB
    txa
    lsr a                           ; X odd = exactly one operand was negative
    bcs m7p_mac_neg
    M7P_MAC_LOOP add
    rts
; Reached only by that `bcs`. A FULL label rather than a cheap `@` one: the
; macro above emits labels of its own, and a real label resets ca65's cheap-
; local scope — a `@negative` here would be a different symbol from the one the
; branch named, and the assembler says so.
m7p_mac_neg:
    .a16
    .i16
    M7P_MAC_LOOP sub
    rts

; --- m7p_mul: acc = a * b, one signed 16x16 -> signed 32 product -----------
; CONTRACT m7p_mul
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = a (the multiplicand), Y = b (the multiplier)
;   out:      the accumulator holds the signed 32-bit product — +0 its low
;             word, +2 its high word. `a` is the wider operand because it
;             is held in 32 bits and shifted LEFT; `b` is shifted RIGHT
;             until zero, so the loop costs one iteration per significant
;             bit of it and the smaller, often-zero operand belongs there
;   clobbers: A, X, Y, N, Z
;   assumes:  no sep/rep here or in m7p_mac, so the width survives the
;             tail call
;   tail:     jmp m7p_mac — a tail call: m7p_mac's rts returns to this
;             routine's caller
;
; A16/I16. ES_M7P+M7P_ACC holds the 32-bit product, little-endian:
;
; m7p_mac ACCUMULATES; this is the same multiply with the accumulator cleared
; first, which is what a caller wanting ONE product needs. It exists because
; the rail's tank step is exactly that shape: a matrix coefficient (signed
; 1.7.8) times the hero's speed (signed 8.8) is a 16.16 displacement, and its
; two halves are the product's two words with no shifting at all.
;
; THE OPERAND ROLES ARE NOT INTERCHANGEABLE — see m7p_mac's header. `a` is held
; in 32 bits and shifted LEFT, so it is the wider operand (a coefficient, |a|
; <= 256); `b` is shifted RIGHT until zero, so the loop costs one iteration per
; significant bit of it and the SMALLER, more often near-zero operand belongs
; there (a speed that is 0 at rest costs a single test).
;
; WIDTH-RISK: A16/I16 on entry and exit. No sep/rep here or in m7p_mac.
m7p_mul:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "m7p_mul"
    stz z:ES_M7P + M7P_ACC + 0
    stz z:ES_M7P + M7P_ACC + 2
    jmp m7p_mac                     ; tail call: m7p_mac's rts returns to ours

; --- M7P_DOT: acc = dx*ca + dy*cb, then A = acc >> 8 -----------------------
; ca/cb are ASSEMBLE-TIME offsets into m7_affine's shadow, which is why this is
; a macro and not a routine taking two pointers: the pairing IS the transpose,
; so it belongs at the call site where a reader can see A,C against B,D.
;
; The >>8 is a LOAD, not a shift. The accumulator is little-endian, so the word
; straddling its bytes 1 and 2 is already the arithmetic shift — sign included,
; because byte 3's low bit is byte 2's high bit. It fits a signed word by
; construction: |dx|,|dy| <= 192 and |coeff| <= 256 give |acc| <= 98,304, and
; 98,304 >> 8 = 384.
.macro M7P_DOT m7p_ca, m7p_cb
    stz z:ES_M7P + M7P_ACC + 0
    stz z:ES_M7P + M7P_ACC + 2
    lda z:ES_M7AFF + m7p_ca
    ldy z:ES_M7P + M7P_DX
    jsr m7p_mac
    lda z:ES_M7AFF + m7p_cb
    ldy z:ES_M7P + M7P_DY
    jsr m7p_mac
    lda z:ES_M7P + M7P_ACC + 1      ; the s32 sum >> 8, as a signed word
.endmacro

; --- m7p_project: the world point -> the screen point ----------------------
; CONTRACT m7p_project
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = world x, Y = world y, both unsigned world pixels
;   out:      the screen point, with the CARRY as the visibility answer
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  every callee (m7p_mac through M7P_DOT) is A16/I16-preserving
;             and contains no sep/rep, which is what lets the carry-flag
;             return convention survive the calls — the `clc`/`sec` are
;             the LAST flag writes on each path
;   tail:     rts
;
; A16/I16. Carry SET = pre-culled, nothing written to SX/SY.
;  Carry CLEAR = ES_M7P+M7P_SX / +M7P_SY hold the signed screen position.
;
; The pivot subtraction is deliberately NOT reduced modulo the 1024 px world
; torus. The plane wraps, so a point can be reached the short way round — but
; the only points this rail projects are within a screen of the pivot, where
; the raw difference IS the short way, and a modulo would cost more than the
; pre-cull it feeds. A rail whose actors can be a half-world away must reduce
; here first; this one cannot produce that case.
;
; WIDTH-RISK: A16/I16 throughout. Every callee (m7p_mac via M7P_DOT) is
; A16/I16-preserving and contains no sep/rep, so the carry-flag return
; convention below survives the calls — the `clc`/`sec` are the LAST flag
; writes on each path.
m7p_project:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "m7p_project"
    txa
    sec
    sbc z:ES_M7AFF + M7P_AFF_X      ; dx = wx - pivot x
    sta z:ES_M7P + M7P_DX
    jsr m7p_abs
    cmp #M7P_R
    bcs @cull                       ; |dx| >= R: outside the circumradius
    tya
    sec
    sbc z:ES_M7AFF + M7P_AFF_Y      ; dy = wy - pivot y
    sta z:ES_M7P + M7P_DY
    jsr m7p_abs
    cmp #M7P_R
    bcs @cull                       ; |dy| >= R: same, on the other axis
    ; ---- the transpose. A,C for x; B,D for y. ---------------------------
    M7P_DOT M7P_AFF_A, M7P_AFF_C
    clc
    adc #M7P_SCREEN_CX
    sta z:ES_M7P + M7P_SX
    M7P_DOT M7P_AFF_B, M7P_AFF_D
    clc
    adc #M7P_SCREEN_CY
    sta z:ES_M7P + M7P_SY
    clc                             ; carry clear = projected
    rts
@cull:
    .a16
    .i16
    sec                             ; carry set = off-screen at every heading
    rts

; --- m7p_abs: A = |A|, signed 16-bit ---------------------------------------
; In/out: A16/I16, DB=0. Clobbers A only — the caller's X and Y survive, which
; is what lets m7p_project keep the world y in Y across the x-axis test.
m7p_abs:
    .a16
    .i16
    cmp #0
    bpl @done
    eor #$FFFF
    inc a
@done:
    .a16
    .i16
    rts
