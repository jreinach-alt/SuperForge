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
; In/out: A16/I16, DB=0. Clobbers A, X, Y. Called FIRST in the scene tick, so
; everything downstream (the join, the origin, the sprites) sees one frame's
; answer rather than a mixture of two.
m7f_tick_state:
    .a16
    .i16
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
    inc a
    and #M7F_HEAD_MASK
    sta z:M7F_HEAD
:
    .a16
    lda z:ES_INP_CUR
    bit #M7F_JOY_RIGHT
    beq :+
    lda z:M7F_HEAD
    dec a
    and #M7F_HEAD_MASK          ; -1 wraps to 255 under the mask
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
    sbc #M7F_DECEL
    bpl @store                  ; still positive
    lda #0
    bra @store
@coast_neg:
    .a16
    clc
    adc #M7F_DECEL
    bmi @store                  ; still negative
    lda #0
    bra @store
@fwd:
    .a16
    lda z:M7F_SPEED
    clc
    adc #M7F_ACCEL
    cmp #(M7F_SPEED_CAP + 1)
    bcc @store
    lda #M7F_SPEED_CAP
    bra @store
@rev:
    .a16
    lda z:M7F_SPEED
    sec
    sbc #M7F_ACCEL
    ; Clamp to SPEED_REV. Both are negative, so the signed test is a subtract
    ; and a sign check — `cmp` alone would be the unsigned one.
    pha
    sec
    sbc #M7F_SPEED_REV          ; (A - SPEED_REV); negative => A < SPEED_REV
    bpl @rev_ok
    pla
    lda #M7F_SPEED_REV
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
m7f_altitude:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #M7F_JOY_R
    beq :+
    lda z:M7F_ALTIDX
    cmp #M7F_ALT_MAXIDX
    bcs :+                      ; already at the ceiling
    inc a
    sta z:M7F_ALTIDX
:
    .a16
    lda z:ES_INP_CUR
    bit #M7F_JOY_L
    beq :+
    lda z:M7F_ALTIDX
    beq :+                      ; already on the floor
    dec a
    sta z:M7F_ALTIDX
:
    .a16
    rts
