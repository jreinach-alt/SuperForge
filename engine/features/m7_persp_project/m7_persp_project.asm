; =============================================================================
; m7_persp_project.asm — a world point onto a PER-SCANLINE Mode 7 camera
; =============================================================================
; The inverse of what sh2_cam's matrix channels stream. The floor at band-local
; row k samples
;
;  texel = P + S(k)/256 * R(theta) * (sx - 128, k - 112)
;
; so a world point W sits at camera-frame (u, v) = R(-theta) * (W - P), and
;
;  d = -v forward distance, in world px
;  k = sp_vk[d] the row whose forward distance is d
;  sx = 128 +- (|u| * recip(k) >> 8)
;  sy = band_top + k
;
; R(-theta), NOT R(theta), and that is the whole correctness question. Feed the
; FORWARD pairing and the markers still move, still stay on screen and still
; look plausible — they slide off the world tile they are standing on, which is
; the failure that survives a casual look. `-D SH2_SP_FORWARD` negates sin here
; and is the rail's non-vacuity control for exactly that (m7_project's header
; records the identical trap for its own transpose).
;
; WHY THERE IS NO DIVIDE. S(k) changes every scanline, so "how far is one
; screen pixel in world units at row k" is a per-row quantity — the reciprocal
; table is that division taken ONCE, offline, and sp_vk is the depth->row
; inverse taken the same way. Both come out of the same scale_ramp the floor
; streams, so a ramp change moves the plane and its inverse together or the
; asset gate refuses both.
;
; THE CULL ORDER IS THE DESIGN. The naive four-multiply core measures 8,522 mc
; per sprite per visible band, and 6,965 mc even for CULLED sprites, because
; both dot products run before the v cull. The order here is:
;
;  1. wrap-subtract dx -> |dx| > 176 out; dy likewise. A Chebyshev pre-cull
;  with NO MULTIPLIES: rotation preserves distance, so a point farther than
;  the padded view's half-window on either world axis is off screen at every
;  heading and no product can change that answer.
;  2. the v dot (two 8x8 products) -> the v / d / k / seam culls.
;  3. only survivors pay for the u dot and the reciprocal.
;
; Reproducing the arithmetic without the order reproduces the cost. NO CYCLE
; FIGURE IS CLAIMED for the ordered version: it has not been measured on the
; emulator, and the first sprite rail whose headroom rule depends on the
; number is the one that owes it.
;
; THE 8x8 HARDWARE CORE, and why it is legal. After the pre-cull |dx|,|dy| <=
; 176, and the sincos LUT is magnitude-CLAMPED to 255 at build time, so every
; rotation product has two byte-wide operands and goes through $4202/$4203 in
; one 8-cycle multiply. Per term, sign and magnitude are split:
;
;  t = (|a| * |c| + 128) >> 8 rounded, 0..176
;  t' = (t ^ m) - m m = sign(a) ^ sign(c) ($0000 / $FFFF)
;
; Each term is at most 176, so a two-term dot fits s16 with no 32-bit
; accumulator. The sign-mask staging between the $4203 write and the $4216 read
; is COVER WORK, not decoration: it is longer than the multiplier's latency, so
; the product is ready when it is read and there is no wait loop.
;
; ALU OWNERSHIP. $4202-$4206 + $4214-$4217 is ONE resource under one name here
; (schemas.py "ALU"), claimed WHOLE by this feature's feature.toml. M7_project
; declined that claim for twelve products a frame and did the multiply in
; software; this core does four per surviving sprite per band inside a VBlank,
; so the trade goes the other way — and it is DECLARED, so the allocator
; refuses a second owner rather than leaving it to an unwritten assumption.

; --- the geometry, derived rather than narrated -----------------------------
; The world's wrap period and the screen's centre column. Written as shifts
; because `no_literals` reads a bare 1024 or 512 as a WRAM-claim address and
; cannot tell it from a hand-narrated one — and the shift form is the honest
; statement anyway (the plane wraps on a power of two because the PPU's Mode 7
; sampler does).
MPP_WORLD_LOG2 = 10
MPP_WORLD_PX   = 1 << MPP_WORLD_LOG2        ; 1024 — the plane's period
MPP_WRAP       = MPP_WORLD_PX - 1
MPP_SCREEN_CX  = 1 << 7                     ; 128 — the pivot's screen column
MPP_LINES      = MPP_SCREEN_CX - (1 << 4)   ; 112 scanlines per band

; The pre-cull's half-window, and the negative half of the wrapped residue it
; implies. A raw residue in [0, 176] is a positive delta, one in [848, 1023] is
; a negative one (|dx| = 1024 - raw), and anything between is farther than the
; window on that axis at every heading.
MPP_CHEB   = 176
MPP_NEG_LO = MPP_WORLD_PX - MPP_CHEB

; The inverse LUT's domain, and the screen-x window. Sp_vk is indexed by a
; single byte, so a forward distance of 256 or more has no row by construction;
; |u| >= 256 is off screen at any row before the reciprocal is even read; and a
; 32x32 token whose centre is more than MPP_XOFF_MAX from the pivot column has
; no pixel left on screen.
MPP_DMAX     = 1 << 8
MPP_XOFF_MAX = 160

; The per-band SEAM guard. Each band guards ONLY the edge that faces the seam
; and lets its true-SCREEN edge slide off: band 1's bottom IS the seam, so its
; deepest rows are culled; band 2's top is, so its shallowest are. The hardware
; clips an OAM box past the screen edge and the 9-bit X wraps, so a sprite
; leaving the picture's outer edge needs no help — a sprite crossing the seam
; would draw into the OTHER camera's half, which is not a clip but a lie. The
; cutoffs are the tier ladder's own box margins (16x16 at the top edge, 32x32
; at the bottom), and they are what `-D SH2_SP_CULLOFF` removes.
MPP_SEAM_LO = 9
MPP_SEAM_HI = 95

MPP_TIER_MID = 2                            ; the -D SH2_SP_TIEROFF constant

; --- the scratch block, inside the one 36-byte dp claim ---------------------
MPP_WX   = ES_MPP + 0
MPP_WY   = ES_MPP + 2
MPP_ADX  = ES_MPP + 4
MPP_ADY  = ES_MPP + 6
MPP_MDX  = ES_MPP + 8
MPP_MDY  = ES_MPP + 10
MPP_CMAG = ES_MPP + 12
MPP_SMAG = ES_MPP + 13
MPP_MC   = ES_MPP + 14
MPP_MS   = ES_MPP + 16
MPP_TMPM = ES_MPP + 18
MPP_ACC  = ES_MPP + 20
MPP_U    = ES_MPP + 22
MPP_PX   = ES_MPP + 24
MPP_PY   = ES_MPP + 26
MPP_TOP  = ES_MPP + 28
MPP_SX   = ES_MPP + 30
MPP_SY   = ES_MPP + 32
MPP_TIER = ES_MPP + 34

; The tables this feature reads, tied to the claims that hold them. The labels
; are the game's .incbin sites; these asserts are what make the indexing model
; — one heading is four bytes, one row is one byte, the domain is a byte — a
; property of the ALLOCATION rather than of a comment.
.assert ES_R_SH2_SP_SINCOS_SIZE = (1 << 8) * 4, error, "m7_persp_project: the sincos set is not 256 headings x (cos,sin)"
.assert ES_R_SH2_SP_VK_SIZE = MPP_DMAX, error, "m7_persp_project: sp_vk does not cover the whole byte domain the d cull assumes"
.assert ES_R_SH2_SP_RECIP_LO_SIZE = MPP_LINES, error, "m7_persp_project: the recip table is not one entry per band scanline"
.assert ES_R_SH2_SP_RECIP_HI_SIZE = MPP_LINES, error, "m7_persp_project: the recip high table is not one entry per band scanline"
.assert ES_R_SH2_SP_TIER_SIZE = MPP_LINES, error, "m7_persp_project: the tier ladder is not one entry per band scanline"
.assert MPP_SEAM_HI < MPP_LINES, error, "m7_persp_project: band 1's seam guard is past the last row"

; =============================================================================
; mpp_mul8 — a signed 8x8 product, through the ALU this feature owns
; =============================================================================
; In: A16 = a, X = b, both signed and both within [-128, 128]. Out: A16 = a *
; b, signed (|product| <= 16384, so it fits s16).
;  Clobbers A, X, Y, MPP_TMPM and MPP_ACC.
;
; WHY IT LIVES HERE AND NOT IN THE CALLER. `$4202-$4206` + `$4214-$4217` is ONE
; whole resource under the name `ALU` (schemas.py), claimed by this feature's
; feature.toml, and the allocator refuses a second owner — correctly, because
; the two entry points share one AluMulDiv state and destroy each other's
; result. The swarm's AI needs signed 8x8 products for its steering
; cross product, so the ALU's owner PUBLISHES the primitive rather than the AI
; declaring a claim that would be refused. That refusal is the allocator
; working, not an obstacle to route around.
;
; THE OPERAND BOUND IS THE CALLER'S TO MEET and it is not decoration: both
; halves go through $4202/$4203 as BYTES after the sign/magnitude split, so an
; operand outside [-128, 128] silently loses its top bits. Sh2_swarm's are
; arithmetic >>3 of a 10-bit residue and of an 8.8 velocity, so both are
; bounded by 64 by construction — see that file's own note.
;
; The sign-mask staging between the `$4203` write and the `$4216` read is COVER
; WORK, exactly as in mpp_project's dot core: 13 cycles against the
; multiplier's 8, so the product is ready when it is read and there is no wait
; loop.
;
; WIDTH-RISK: A16/I16 in and out. The ONE 8-bit window is the operand pair,
; inside a balanced sep/rep; X is 16-bit across it because it carries |b|.
mpp_mul8:
    .a16
    .i16
    ldy #0
    cmp #$8000
    bcc @apos
    eor #$FFFF
    inc a
    dey                             ; Y = $FFFF: a was negative
@apos:
    .a16
    .i16
    sta z:MPP_ACC                   ; |a|
    sty z:MPP_TMPM                  ; sign(a)
    txa
    ldy #0
    cmp #$8000
    bcc @bpos
    eor #$FFFF
    inc a
    dey
@bpos:
    .a16
    .i16
    tax                             ; X = |b|
    sep #$20
    .a8
    lda z:MPP_ACC
    sta a:$4202                     ; WRMPYA = |a|
    txa
    sta a:$4203                     ; WRMPYB = |b| — the product starts here
    rep #$20
    .a16
    tya
    eor z:MPP_TMPM                  ; the product's sign is the xor of the two
    sta z:MPP_TMPM                  ; COVER WORK: longer than the 8-cycle wait
    lda a:$4216                     ; RDMPY: |a| * |b|
    eor z:MPP_TMPM
    sec
    sbc z:MPP_TMPM                  ; (t ^ m) - m
    rts

; =============================================================================
; mpp_band_coeffs — A = heading (0..255) -> the band's split-sign coefficients
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; Called ONCE PER BAND, not per marker: the coefficients are the camera's, and
; every marker in the band is projected against the same pair. Magnitudes go to
; the byte halves MPP_CMAG/MPP_SMAG (the multiply operands) and the signs to
; MPP_MC/MPP_MS as $0000/$FFFF word masks, which is the form the per-term `(t ^
; m) - m` negate wants — a mask, not a branch.
;
; WIDTH-RISK: enters and exits A16/I16. The only 8-bit windows are the two
; magnitude byte stores, each inside a balanced sep/rep; the index registers
; are never narrowed, which matters because X carries the LUT offset across one
; of them.
mpp_band_coeffs:
    .a16
    .i16
    and #((1 << 8) - 1)
    asl a
    asl a                           ; heading * 4: a cos word and a sin word
    tax
    lda f:sh2_sp_sincos_bin, x      ; cos, s8.8, |cos| <= 255 by the clamp
    bpl @cpos
    eor #$FFFF
    inc a
    tay                             ; Y = |cos|
    lda #$FFFF
    bra @cst
@cpos:
    .a16
    .i16
    tay
    lda #0
@cst:
    .a16
    .i16
    sta z:MPP_MC
    tya
    sep #$20
    .a8
    sta z:MPP_CMAG
    rep #$20
    .a16
    lda f:sh2_sp_sincos_bin + 2, x  ; sin
.ifdef SH2_SP_FORWARD
    ; THE WRONG-MATH CONTROL. Negating sin turns R(-theta) into R(theta) — the
    ; FORWARD floor matrix — so the projection becomes the map the PPU applies
    ; rather than its inverse. Markers still move, still stay on screen and
    ; still look like a plausible crowd; they simply stop standing on their own
    ; texels. Without this build, "the sprites are in the right place" is a
    ; claim nothing can make false.
    eor #$FFFF
    inc a
.endif
    bpl @spos
    eor #$FFFF
    inc a
    tay
    lda #$FFFF
    bra @sst
@spos:
    .a16
    .i16
    tay
    lda #0
@sst:
    .a16
    .i16
    sta z:MPP_MS
    tya
    sep #$20
    .a8
    sta z:MPP_SMAG
    rep #$20
    .a16
    rts

; =============================================================================
; mpp_project — one world point against the staged band
; =============================================================================
; In: A16/I16, DB=0. The caller stages MPP_WX/MPP_WY (the world point) and,
;  once per band, MPP_PX/MPP_PY/MPP_TOP plus mpp_band_coeffs' output.
; Out: CARRY SET -> visible; MPP_SX / MPP_SY / MPP_TIER hold the answer.
;  CARRY CLEAR -> culled, and NOTHING was written to the caller's OAM slot.
;  Clobbers A, X, Y and the scratch block.
;
; The carry is the whole return protocol on purpose: a culled marker must cost
; the caller no store at all, which is what makes OAM slot COMPACTION possible
; (sh2_obj). A convention that returned an off-screen coordinate instead would
; force a park store per culled sprite, which is most of them.
;
; WIDTH-RISK: A16/I16 in and out. Every 8-bit window is a $4202/$4203 operand
; pair inside a balanced sep/rep, and the index registers are NEVER narrowed —
; X carries the band-local row k from the sp_vk lookup all the way through the
; u dot to the reciprocal and the tier read, across three of those windows.
mpp_project:
    .a16
    .i16
    ; ---- dx: the wrapped residue, split into magnitude and sign ------------
    ; The plane wraps, so `wx - px` is only meaningful modulo the period. The
    ; residue is read directly: [0, 176] is a positive delta, [848, 1023] a
    ; negative one, and everything between is outside the pre-cull window on
    ; this axis at EVERY heading. Two compares, no multiply, no sign extension.
    lda z:MPP_WX
    sec
    sbc z:MPP_PX
    and #MPP_WRAP
    ldy #0                          ; the sign mask, assumed positive
    cmp #(MPP_CHEB + 1)
    bcc @xok
    cmp #MPP_NEG_LO
    bcs @xneg
@cull:
    .a16
    .i16
    clc                             ; the ONE cull exit: carry clear
    rts
@xneg:
    .a16
    .i16
    eor #$FFFF
    clc
    adc #(MPP_WORLD_PX + 1)         ; |dx| = 1024 - raw
    dey                             ; ...and the mask becomes $FFFF
@xok:
    .a16
    .i16
    sta z:MPP_ADX
    sty z:MPP_MDX

    ; ---- dy, identically ---------------------------------------------------
    lda z:MPP_WY
    sec
    sbc z:MPP_PY
    and #MPP_WRAP
    ldy #0
    cmp #(MPP_CHEB + 1)
    bcc @yok
    cmp #MPP_NEG_LO
    bcs @yneg
    bra @cull
@yneg:
    .a16
    .i16
    eor #$FFFF
    clc
    adc #(MPP_WORLD_PX + 1)
    dey
@yok:
    .a16
    .i16
    sta z:MPP_ADY
    sty z:MPP_MDY

    ; ---- v = dx*sin + dy*cos ----------------------------------------------
    ; The FORWARD axis, and the only dot a culled marker ever pays for. Both
    ; terms are at most 176, so the sum fits s16 with no 32-bit accumulator.
    sep #$20
    .a8
    lda z:MPP_ADX
    sta a:$4202                     ; WRMPYA = |dx|  (a byte: |dx| <= 176)
    lda z:MPP_SMAG
    sta a:$4203                     ; WRMPYB = |sin| — the product starts here
    rep #$20
    .a16
    lda z:MPP_MDX
    eor z:MPP_MS                    ; ...the term's sign is the xor of the two
    sta z:MPP_TMPM                  ; COVER WORK: longer than the 8-cycle wait
    lda a:$4216                     ; RDMPY: |dx| * |sin|
    clc
    adc #$0080
    xba
    and #$00FF                      ; (product + 128) >> 8, rounded
    eor z:MPP_TMPM
    sec
    sbc z:MPP_TMPM                  ; t' = (t ^ m) - m
    sta z:MPP_ACC
    sep #$20
    .a8
    lda z:MPP_ADY
    sta a:$4202
    lda z:MPP_CMAG
    sta a:$4203
    rep #$20
    .a16
    lda z:MPP_MDY
    eor z:MPP_MC
    sta z:MPP_TMPM
    lda a:$4216
    clc
    adc #$0080
    xba
    and #$00FF
    eor z:MPP_TMPM
    sec
    sbc z:MPP_TMPM
    clc
    adc z:MPP_ACC                   ; A = v

    ; ---- the v / d / k culls, all before the u dot -------------------------
    ; The camera sees NEGATIVE v only: v >= 0 is at or behind the pivot row,
    ; where the floor has no scanline to draw the point on. @cullv is a second
    ; cull exit rather than a branch back to @cull: the two dot products
    ; between them are ~70 bytes and a relative branch cannot span that. Two
    ; `clc / rts` sites cost four bytes; a `jmp` trampoline per cull would cost
    ; more, on the path most markers take.
    bpl @cullv
    eor #$FFFF
    inc a                           ; d = -v, the forward distance
    cmp #MPP_DMAX
    bcs @cullv                      ; past the LUT's byte domain
    tax
    lda f:sh2_sp_vk_bin, x          ; the build-time inverse of the ramp
    and #$00FF                      ; (a word read; the high half is the next
                                    ;  entry and is discarded — the table is
                                    ;  ROM, so the extra byte is harmless)
    cmp #$00FF
    bne @haverow                    ; $FF = beyond the horizon / behind us
@cullv:
    .a16
    .i16
    clc
    rts
@haverow:
    .a16
    .i16
    tax                             ; X = band-local row k, KEPT from here on

.ifndef SH2_SP_CULLOFF
    ; ---- the per-band SEAM guard, before the u dot -------------------------
    ; Band 1's bottom edge is the seam and band 2's top edge is, so each culls
    ; only the rows whose OAM box would reach across it. `-D SH2_SP_CULLOFF`
    ; removes both, and then a band-1 marker's white token draws into band 2's
    ; half of the picture — which is the control that makes "the seam holds" a
    ; claim about pixels rather than a description of this branch.
    ldy z:MPP_TOP
    bne @seam2
    cpx #(MPP_SEAM_HI + 1)
    bcc @udot
    clc
    rts
@seam2:
    .a16
    .i16
    cpx #MPP_SEAM_LO
    bcs @udot
    clc
    rts
.endif
@udot:
    .a16
    .i16
    ; ---- u = dx*cos - dy*sin: only survivors pay -------------------------
    ; The same two-product core, with the sin term SUBTRACTED — which costs one
    ; `eor #$FFFF` on its sign mask rather than a second code path.
    sep #$20
    .a8
    lda z:MPP_ADX
    sta a:$4202
    lda z:MPP_CMAG
    sta a:$4203
    rep #$20
    .a16
    lda z:MPP_MDX
    eor z:MPP_MC
    sta z:MPP_TMPM
    lda a:$4216
    clc
    adc #$0080
    xba
    and #$00FF
    eor z:MPP_TMPM
    sec
    sbc z:MPP_TMPM
    sta z:MPP_ACC
    sep #$20
    .a8
    lda z:MPP_ADY
    sta a:$4202
    lda z:MPP_SMAG
    sta a:$4203
    rep #$20
    .a16
    lda z:MPP_MDY
    eor z:MPP_MS
    eor #$FFFF                      ; the u dot SUBTRACTS this term
    sta z:MPP_TMPM
    lda a:$4216
    clc
    adc #$0080
    xba
    and #$00FF
    eor z:MPP_TMPM
    sec
    sbc z:MPP_TMPM
    clc
    adc z:MPP_ACC                   ; A = u
    sta z:MPP_U
    ; |u| without touching X, which still holds k: cmp #$8000 carries the sign
    cmp #$8000
    bcc @aupos
    eor #$FFFF
    inc a
@aupos:
    .a16
    .i16
    cmp #MPP_DMAX
    bcs @cull2                      ; |u| >= 256 is off screen at any row
    sta z:MPP_ACC                   ; |u|

    ; ---- sxoff = |u| * recip(k) >> 8 --------------------------------------
    ; recip(k) is NINE bits (171..410), so this is one 8x8 multiply by its low
    ; byte plus a conditional `+ |u|` for the ninth — which is what replaces a
    ; 16-bit divide by the row's scale. The high-table read is the cover work
    ; for the product, and its `lsr` leaves the ninth bit in the carry, which
    ; survives the `rep` and the loads below.
    sep #$20
    .a8
    sta a:$4202                     ; WRMPYA = |u| (a byte: |u| < 256)
    lda f:sh2_sp_recip_lo_bin, x
    sta a:$4203
    lda f:sh2_sp_recip_hi_bin, x
    lsr a                           ; carry = recip's bit 8
    rep #$20
    .a16
    lda a:$4216
    xba
    and #$00FF                      ; >> 8
    bcc @nohi
    clc
    adc z:MPP_ACC                   ; + |u|, the ninth bit's contribution
@nohi:
    .a16
    .i16
    cmp #MPP_XOFF_MAX
    bcc @havex
@cull2:
    .a16
    .i16
    clc
    rts
@havex:
    .a16
    .i16
    ; ---- the answer --------------------------------------------------------
    ; Y is free (the vk lookup consumed it), so it carries u's sign into the
    ; branch without disturbing X.
    ldy z:MPP_U
    bpl @upos
    eor #$FFFF
    inc a
@upos:
    .a16
    .i16
    clc
    adc #MPP_SCREEN_CX
    sta z:MPP_SX
    txa                             ; X = k, still
    clc
    adc z:MPP_TOP
    sta z:MPP_SY
.ifdef SH2_SP_TIEROFF
    ; THE SIZE-LADDER CONTROL. Every marker gets the middle tier, so apparent
    ; size stops tracking depth. Without it, "far markers are drawn smaller" is
    ; a claim about a table nothing can contradict.
    lda #MPP_TIER_MID
.else
    lda f:sh2_sp_tier_bin, x        ; (word read, high half discarded as above)
    and #$00FF
.endif
    sta z:MPP_TIER
    sec
    rts
