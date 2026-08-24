; =============================================================================
; m7f_logic.asm — four axes, one frame: turn, throttle, altitude, integrate
; =============================================================================
; The control model, one routine per axis:
;
;  D-pad LEFT / RIGHT heading +/- 1 of 256 per frame HELD
;  B throttle forward, up to SPEED_CAP
;  Y reverse thrust, down to SPEED_REV
;  neither coast toward 0 — hover, not a stop
;  R climb (altitude up, ground recedes)
;  L descend (altitude down, ground approaches)
;
; ALL SIX ARE HELD-STATE, not edges: this is a flight model, and a tap should
; nudge rather than latch. The altitude is stored as an INDEX 0..80 rather
; than as an altitude 0..240 in steps of 3, because the profile blob is
; indexed and a divide by 3 every frame to reach it would be a cost for
; nothing. Alt = idx * 3, the clamps are the same two ends, and the step is
; one index per held frame either way, so the FEEL is identical.
;

; --- the throttle model -----------------------------------------------------
; Written as SHIFTS of the 8.8 point rather than as hex, and not for style:
; `no_literals` refuses a bare $0300 — it lands inside an emitted WRAM claim
; and nothing in the token distinguishes a speed from an address — and the
; shift form says "three pixels per frame", which the hex does not.
M7F_FP        = 8                       ; the 8.8 fixed point's fraction bits
M7F_ACCEL     = 1 << (M7F_FP - 4)       ; $0010: +1/16 px/frame per frame of B
M7F_DECEL     = 1 << (M7F_FP - 5)       ; $0008: the coast bleed toward hover
M7F_SPEED_CAP = 3 << M7F_FP             ; $0300: 3 px/frame forward
M7F_SPEED_REV = (0 - (2 << M7F_FP)) & $FFFF   ; $FE00: -2 px/frame reverse

; =============================================================================
; THE FLIGHT MODEL IN TWO REGIONS (engine/features/tick_scale)
; =============================================================================
; A PAL frame lasts r = 1 + TS_GAIN_NUM/TS_GAIN_DEN = 1.2018039 NTSC frames.
; Four numbers here and each takes the exponent its DIMENSION asks for:
;
;   a CAP is px per frame           -> r    768 -> 923, 512 -> 615
;   an ACCELERATION is px per frame
;     PER frame                     -> r^2  16 -> 23, 8 -> 12
;
; All four are 8.8, which is docs/95 §5.2's cheap class — the fixed point
; absorbs the ratio, so the conversion is a build-time constant chosen once at
; scene enter and there is nothing per-frame to carry. The REVERSE cap is
; negated from its own magnitude on both machines rather than twinned, so
; "$FE00 is minus $0200" cannot become false on one of them.
;
; The two INTEGER rates in this file — the heading and the altitude index, both
; one unit per held frame — are NOT twinned. An integer step of 1 has no
; correct x1.2018 (round-to-nearest is 1 and changes nothing; round-up is 2 and
; overshoots by 66%), so they read US_TS_TICK, which sky.asm publishes once per
; frame through TS_STEP with the fraction carried.
;
; STATED RESIDUAL: the accelerations round to whole 8.8 LSBs — ACCEL 16 -> 23
; against a true 23.11 (-0.4%) and DECEL 8 -> 12 against 11.55 (+3.9%). Both
; are transients against a throttle that reaches its cap in twenty frames and
; then sits there.
;
; TICK: ok — this block is the region compensator's derivation for this rail;
;   naming the NTSC frame beside the PAL one is its subject rather than a
;   coupling in it, exactly as in tick_scale.asm.
.define M7F_RGAIN(v)  ((((v) * (TS_GAIN_DEN + TS_GAIN_NUM)) + TS_GAIN_DEN / 2) / TS_GAIN_DEN)
; The reverse cap's MAGNITUDE, derived from the cap rather than declared beside
; it: a second constant up there would sit inside three lines of ACCEL and
; SPEED_CAP, and the override this block carries would then silence THOSE too —
; which is hiding a finding rather than answering one.
M7F_SPEED_MAG     = (0 - M7F_SPEED_REV) & $FFFF
M7F_ACCEL_PAL     = M7F_RGAIN(M7F_RGAIN(M7F_ACCEL))
M7F_DECEL_PAL     = M7F_RGAIN(M7F_RGAIN(M7F_DECEL))
M7F_SPEED_CAP_PAL = M7F_RGAIN(M7F_SPEED_CAP)
M7F_SPEED_MAG_PAL = M7F_RGAIN(M7F_SPEED_MAG)

; --- m7f_region_rates: the four numbers, in the running console's units -----
; CONTRACT m7f_region_rates
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_RGN_PAL — the region flag, latched once at boot
;   out:      the scene's per-frame rates published in the running
;             console's units, on BOTH arms of the branch (the
;             write-before-read establishment for them)
;   clobbers: A, N, Z, C, V
;   assumes:  ONCE, from the scene's `enter`, which runs with the NMI
;             masked — so the words are written before the first armed
;             VBlank reads them (rule 5)
;   tail:     rts
;
; before the first armed VBlank and before anything reads one.
;
; WIDTH-RISK: A16/I16 in and out; no sep/rep. `@pal` is reached A16 by branch,
; `@ntsc` A16 by fall-through, `@rev` A16 from both.
m7f_region_rates:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "m7f_region_rates"
    lda z:ES_RGN_PAL
    bne @pal
    lda #M7F_ACCEL                  ; NTSC: today's constants, to the LSB
    sta z:US_R_ACCEL
    lda #M7F_DECEL
    sta z:US_R_DECEL
    lda #M7F_SPEED_CAP
    sta z:US_R_CAP
    lda #M7F_SPEED_MAG
    bra @rev
@pal:
    .a16
    .i16
    lda #M7F_ACCEL_PAL              ; r^2 — an acceleration
    sta z:US_R_ACCEL
    lda #M7F_DECEL_PAL              ; r^2
    sta z:US_R_DECEL
    lda #M7F_SPEED_CAP_PAL          ; r   — a velocity
    sta z:US_R_CAP
    lda #M7F_SPEED_MAG_PAL
@rev:
    .a16
    .i16
    ; A holds the reverse cap's MAGNITUDE; the stored word is its negative, so
    ; the symmetry is arithmetic on both machines rather than two constants
    ; that have to agree.
    sta z:US_R_REV
    lda #0
    sec
    sbc z:US_R_REV
    sta z:US_R_REV
    rts

; --- which bit of the latched JOY word is which -----------------------------
; $4218 delivers one 16-bit word: B Y Select Start Up Down Left Right in the
; HIGH byte, A X L R in the low. Written as SHIFTS rather than as $0200 and
; friends because `no_literals` cannot tell a bare $0200 from a hand-narrated
; WRAM address — it collides with a real claim — and the shift says which bit
; position is meant, which the hex does not.
M7F_JOY_R     = 1 << 4
M7F_JOY_L     = 1 << 5
M7F_JOY_RIGHT = 1 << 8
M7F_JOY_LEFT  = 1 << 9
M7F_JOY_Y     = 1 << 14
M7F_JOY_B     = 1 << 15

; --- m7f_tick_state: the whole frame's state step ---------------------------
; CONTRACT m7f_tick_state
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the flight state advanced one frame
;   clobbers: A, X, Y, N, Z
;   assumes:  FIRST in the scene tick, so everything downstream projects
;             this frame's state rather than last frame's
;   tail:     rts
;
; everything downstream (the join, the origin, the sprites) sees one frame's
; answer rather than a mixture of two.
m7f_tick_state:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "m7f_tick_state"
    jsr m7f_turn
    jsr m7f_throttle
    jsr m7f_altitude
    jsr m7f_move                ; m7f_cam's — it owns the multiplier
    rts

; --- m7f_turn: LEFT/RIGHT step the heading one of 256 per held frame --------
; In/out: A16/I16, DB=0. Clobbers A.
;
; LEFT increments and RIGHT decrements, which is the sense that reads
; correctly on screen: the world turns the other way from the camera. Holding
; both is a deliberate no-op (+1 then -1) — the hardware can report both on a
; worn pad, and cancelling is the honest answer.
m7f_turn:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #M7F_JOY_LEFT
    beq :+
    lda z:M7F_HEAD
    clc
    adc z:US_TS_TICK                ; one heading unit per TICK, not per frame
    and #M7F_HEAD_MASK
    sta z:M7F_HEAD
:
    .a16
    lda z:ES_INP_CUR
    bit #M7F_JOY_RIGHT
    beq :+
    lda z:M7F_HEAD
    sec
    sbc z:US_TS_TICK            ; ...and back the other way; the mask wraps it
    and #M7F_HEAD_MASK
    sta z:M7F_HEAD
:
    .a16
    rts

; --- m7f_throttle: B forward, Y reverse, release coasts to hover ------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; `speed` is SIGNED 8.8, and that single fact is what makes forward, reverse
; and hover one mechanism rather than three: `m7f_move` multiplies the
; heading's sin/cos by it and subtracts, so a negative speed reverses along the
; same heading for free and a zero speed is a hover with the camera still
; pointed where the player left it. B takes priority over Y when both are
; held — forward wins, so a fumbled reverse does not stall the ship.
m7f_throttle:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #M7F_JOY_B
    bne @fwd
    lda z:ES_INP_CUR
    bit #M7F_JOY_Y
    bne @rev
    ; ---- no throttle: bleed toward 0 --------------------------------------
    lda z:M7F_SPEED
    beq @done
    bmi @coast_neg
    sec
    sbc z:US_R_DECEL
    bpl @store                  ; still positive
    lda #0
    bra @store
@coast_neg:
    .a16
    clc
    adc z:US_R_DECEL
    bmi @store                  ; still negative
    lda #0
    bra @store
@fwd:
    .a16
    lda z:M7F_SPEED
    clc
    adc z:US_R_ACCEL
    cmp z:US_R_CAP                  ; the bound is a word now, so the `+ 1` the
    beq @store                      ;   immediate carried is this `beq`
    bcc @store
    lda z:US_R_CAP
    bra @store
@rev:
    .a16
    lda z:M7F_SPEED
    sec
    sbc z:US_R_ACCEL
    ; Clamp to SPEED_REV. Both are negative, so the signed test is a subtract
    ; and a sign check — `cmp` alone would be the unsigned one.
    pha
    sec
    sbc z:US_R_REV              ; (A - SPEED_REV); negative => A < SPEED_REV
    bpl @rev_ok
    pla
    lda z:US_R_REV
    bra @store
@rev_ok:
    .a16
    pla
@store:
    .a16
    sta z:M7F_SPEED
@done:
    .a16
    rts

; --- m7f_altitude: R climbs, L descends, both ends clamp (no crash) ---------
; In/out: A16/I16, DB=0. Clobbers A.
;
; ONE INDEX PER HELD FRAME — a step of 3 on the underlying 0..240 scale: 81
; levels traversed end-to-end in 80 held frames (1.33 s), smooth by
; construction. Both ends CLAMP rather than wrap: no crash into the ground and
; no break through the ceiling, so the rail has no fail state.
; NAMED LOCAL LABELS, NOT ANONYMOUS ONES, and this was a live bug rather than
; a style note. Each arm now needs a label of its OWN for the clamp, and an
; anonymous one lands between the arm's guard `beq :+` and the label that guard
; meant — so with R released the routine fell straight into `sta M7F_ALTIDX`
; with the JOYPAD WORD still in A. The altitude index became $0000 or $0010,
; the band length derived from it became nonsense, and m7f_compose_timed then
; overran the frame so badly that the main loop ran at one iteration per thirty
; VBlanks. The oracle read it as the whole rail stopping; nothing went red and
; width-check was clean, because every annotation was true. sh2_cam.asm's
; SH2_CAM_PAD carries the same warning for the same reason.
m7f_altitude:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #M7F_JOY_R
    beq @no_climb
    ; CLAMPED RATHER THAN GUARDED, because the step can be 2 on PAL and a
    ; "one below the ceiling" test would let it land one above.
    lda z:M7F_ALTIDX
    clc
    adc z:US_TS_TICK
    cmp #(M7F_ALT_MAXIDX + 1)
    bcc @climb_store
    lda #M7F_ALT_MAXIDX
@climb_store:
    .a16
    .i16
    sta z:M7F_ALTIDX
@no_climb:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #M7F_JOY_L
    beq @no_dive
    lda z:M7F_ALTIDX
    sec
    sbc z:US_TS_TICK
    bcs @dive_store             ; no borrow — still above the floor
    lda #0                      ; ...or it just crossed it: stop there
@dive_store:
    .a16
    .i16
    sta z:M7F_ALTIDX
@no_dive:
    .a16
    .i16
    rts
