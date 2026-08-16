; =============================================================================
; race_logic.asm — velocity physics + lap detection (scene-scoped)
; =============================================================================
; Steering, velocity and position are integrated here; the pose retarget that
; follows a heading change still happens in VBlank (sm_nmi_hook) — this code
; only moves state.
;
; Physics (bit-exact against tools/gen_move_lut.py's Sim, which is the tests'
; oracle and the constants' single source of truth):
;  vel is SIGNED 8.8 px/frame. B accelerates toward MZ_VEL_MAX, Down brakes
;  to a stop and then reverses toward MZ_VEL_MIN, coasting decays toward 0.
;  The per-axis step is sign(u)*sign(vel) * ((|u| * |vel|) >> 8) — the
;  magnitude comes from the hardware multiplier (8x8, so the kernel
;  decomposes m*v = mh*v + ml*vh + (ml*vl >> 8), exact by construction) and
;  the sign is applied afterwards. Position carries an 8-bit sub-pixel
;  accumulator per axis: t = sub + step; sub = t & 255; pos += t >> 8
;  (FLOOR semantics — the high byte is sign-extended).
;
; Lap: the world is quartered around the ring centre (0 NE, 1 NW, 2 SW, 3 SE; y
; grows south). The start/finish spoke runs due east, so it IS the 3->0 sector
; edge. A lap counts only when all four sectors were visited since the last one
; — wiggling across the line cannot score, and the reverse circuit
; (0->3->2->1->0) never reaches the 3->0 edge at all.

; --- DP field aliases (ES_RL_HOT layout, feature.toml) ----------------------
RL_MAG    = ES_RL_HOT + 0           ; |u| (0..256)
RL_SGN    = ES_RL_HOT + 2           ; 1 = negate the product
RL_ACC    = ES_RL_HOT + 4           ; magnitude product accumulator
RL_VABS   = ES_RL_HOT + 6           ; |vel|
RL_VNEG   = ES_RL_HOT + 8           ; 1 = vel is negative
RL_STEP_X = ES_RL_HOT + 10          ; signed 8.8 step, this frame
RL_STEP_Y = ES_RL_HOT + 12
RL_T      = ES_RL_HOT + 14          ; sub-accumulator sum

; CAM0 sits on the start/finish spoke, east and south of the ring centre — the
; sector the lap machine starts in. Guarded, not narrated:
RL_SECTOR0 = 3
.assert CAM0_PX >= MZ_CENTER_PX, error, "CAM0 is not east of the ring centre"
.assert CAM0_PY >= MZ_CENTER_PX, error, "CAM0 is not south of the ring centre"

rl_ckpt_bit: .byte 1, 2, 4, 8       ; sector -> checkpoint mask bit

; --- rl_arm: init contract + race state at the start line -------------------
; In/out: A16/I16, DB=0, forced blank (scene enter contract).
rl_arm:
    .a16
    .i16
    ldx #(ES_RL_HOT_SIZE - 2)
:   stz z:ES_RL_HOT, x
    dex
    dex
    bpl :-
    stz z:US_VEL
    stz z:US_SUB_PX + 0
    stz z:US_SUB_PX + 2
    sep #$20
    .a8
    lda #0
    sta f:US_LAP_LONG
    lda #RL_SECTOR0
    sta f:US_SECTOR_LONG
    lda #(1 << RL_SECTOR0)
    sta f:US_CKPT_LONG
    rep #$20
    .a16
    rts

; --- rl_tick: one frame of race logic (race::tick) --------------------------
; In/out: A16/I16, DB=0.
rl_tick:
    .a16
    .i16
    jsr rl_steer
    jsr rl_velocity
    jsr rl_move
    jsr rl_lap
    rts

; --- rl_steer: L/R turn one pose step per frame (the declared max) --
rl_steer:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #JOY_LEFT
    beq :+
    sep #$20
    .a8
    lda f:US_HEADING_LONG
    inc
    and #63
    sta f:US_HEADING_LONG       ; left = +h (counterclockwise on the map)
    rep #$20
    .a16
:   .a16                        ; both paths here are A16 (beq source + rep)
    lda z:ES_INP_CUR
    bit #JOY_RIGHT
    beq :+
    sep #$20
    .a8
    lda f:US_HEADING_LONG
    dec
    and #63
    sta f:US_HEADING_LONG
    rep #$20
    .a16
:   .a16
    rts

; --- rl_velocity: accelerate / brake+reverse / coast ------------------------
; All clamps are unsigned compares guarded by a sign test first: the used value
; space is only $0000..MZ_VEL_MAX and MZ_VEL_MIN..$FFFF.
rl_velocity:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #JOY_B
    bne @accel
    lda z:ES_INP_CUR
    bit #JOY_DOWN
    bne @brake
    ; ---- coast: decay toward zero ----------------------------------------
    lda z:US_VEL
    beq @done
    bmi @coast_neg
    sec
    sbc #MZ_FRICTION
    bpl @store                  ; still forward
    lda #0
    bra @store
@coast_neg:
    .a16
    clc
    adc #MZ_FRICTION
    bmi @store                  ; still reversing
    lda #0
    bra @store
@accel:
    .a16
    lda z:US_VEL
    clc
    adc #MZ_ACCEL
    bmi @store                  ; still below zero: nowhere near the cap
    cmp #(MZ_VEL_MAX + 1)
    bcc @store
    lda #MZ_VEL_MAX
    bra @store
@brake:
    .a16
    lda z:US_VEL
    beq @reverse
    bmi @reverse
    sec
    sbc #MZ_BRAKE
    bpl @store                  ; braked, still rolling forward
    lda #0
    bra @store
@reverse:
    .a16
    lda z:US_VEL
    sec
    sbc #MZ_REVERSE
    cmp #MZ_VEL_MIN             ; unsigned: both operands are $8000..$FFFF
    bcs @store
    lda #MZ_VEL_MIN
@store:
    .a16
    sta z:US_VEL
@done:
    .a16
    rts

; --- rl_move: step the camera origin along the heading ----------------------
rl_move:
    .a16
    .i16
    lda z:US_VEL
    beq @none                   ; stopped: no step, the accumulators hold
    bpl @vpos
    eor #$FFFF
    inc a
    sta z:RL_VABS
    lda #1
    sta z:RL_VNEG
    bra @dirs
@vpos:
    .a16
    sta z:RL_VABS
    stz z:RL_VNEG
@dirs:
    .a16
    sep #$20
    .a8
    lda f:US_HEADING_LONG
    rep #$20
    .a16
    and #255                    ; the A8 load left the high byte stale
    asl
    asl
    tax                         ; LUT byte index = heading * 4
    lda a:move_lut + 0, x
    phx
    jsr rl_scale
    sta z:RL_STEP_X
    plx
    lda a:move_lut + 2, x
    jsr rl_scale
    sta z:RL_STEP_Y
    lda z:RL_STEP_X
    ldx #0
    jsr rl_integrate
    lda z:RL_STEP_Y
    ldx #2
    jsr rl_integrate
@none:
    .a16
    rts

; --- rl_scale: (|u| * |vel|) >> 8, signed by sign(u) xor sign(vel) ----------
; In: A16 = u (signed 8.8 unit component, -256..256); RL_VABS/RL_VNEG set. Out:
; A16 = signed 8.8 step. Clobbers X, RL_MAG/RL_SGN/RL_ACC.
rl_scale:
    .a16
    .i16
    ldx #0
    cmp #0
    bpl @mag
    ldx #1
    eor #$FFFF
    inc a
@mag:
    .a16
    sta z:RL_MAG
    txa
    eor z:RL_VNEG
    and #1
    sta z:RL_SGN
    ; ---- (ml * vl) >> 8 ---------------------------------------------------
    ; WIDTH-RISK: the multiplier ports are 8-bit; every A8 load below takes the
    ; LOW byte of a DP word on purpose. Exits A16 for the caller.
    sep #$20
    .a8
    lda z:RL_MAG                ; ml
    sta a:$4202
    lda z:RL_VABS               ; vl
    sta a:$4203
    nop                         ; 8 CPU cycles before RDMPY is valid
    nop
    nop
    nop
    rep #$20
    .a16
    lda a:$4216
    xba
    and #255
    sta z:RL_ACC
    ; ---- + ml * vh --------------------------------------------------------
    sep #$20
    .a8
    lda z:RL_MAG
    sta a:$4202
    lda z:RL_VABS + 1           ; vh
    sta a:$4203
    nop
    nop
    nop
    nop
    rep #$20
    .a16
    lda a:$4216
    clc
    adc z:RL_ACC
    sta z:RL_ACC
    ; ---- + mh * |vel| (mh is 0 or 1 — |u| never exceeds 256) -------------
    lda z:RL_MAG
    cmp #256
    bcc @sign
    lda z:RL_VABS
    clc
    adc z:RL_ACC
    sta z:RL_ACC
@sign:
    .a16
    lda z:RL_ACC
    ldx z:RL_SGN
    beq @out
    eor #$FFFF
    inc a
@out:
    .a16
    rts

; --- rl_integrate: add a signed 8.8 step to one world axis ------------------
; In: A16 = step; X = axis byte offset (0 = x, 2 = y) into the contiguous
;  US_SUB_PX pair and the M7ORG position pair.
rl_integrate:
    .a16
    .i16
    clc
    adc z:US_SUB_PX, x
    sta z:RL_T
    and #255
    sta z:US_SUB_PX, x
    lda z:RL_T
    xba                         ; whole-pixel part = the high byte...
    and #255
    cmp #128
    bcc :+
    ora #$FF00                  ; ...sign-extended (t >> 8 is a FLOOR shift)
:   .a16
    clc
    adc z:ES_M7ORG, x
    and #4095                   ; the 4096-px world wraps
    sta z:ES_M7ORG, x
    rts

; --- rl_lap: sector circuit closed by the due-east start/finish spoke -------
rl_lap:
    .a16
    .i16
    lda z:ES_M7ORG + 2
    sec
    sbc #MZ_CENTER_PX
    bmi @north
    lda z:ES_M7ORG + 0
    sec
    sbc #MZ_CENTER_PX
    bmi @sw
    ldx #3                      ; south + east = SE
    bra @have
@sw:
    .a16
    ldx #2
    bra @have
@north:
    .a16
    lda z:ES_M7ORG + 0
    sec
    sbc #MZ_CENTER_PX
    bmi @nw
    ldx #0                      ; north + east = NE
    bra @have
@nw:
    .a16
    ldx #1
@have:
    .a16
    sep #$20
    .a8
    lda f:US_SECTOR_LONG
    cmp #3                      ; came from SE...
    bne @mark
    cpx #0                      ; ...into NE: that IS the start/finish spoke
    bne @mark
    lda f:US_CKPT_LONG
    cmp #MZ_CKPT_ALL            ; a whole circuit, not a wiggle over the line
    bne @mark
    lda f:US_LAP_LONG
    inc
    sta f:US_LAP_LONG
    ; X still holds the sector @mark is about to consume, and rl_hud_lap loads
    ; it with the HUD cell address — save it across the call.
    phx
    jsr rl_hud_lap              ; stage the new digit for the next VBlank
    plx
    lda #0
    sta f:US_CKPT_LONG
@mark:
    .a8
    .i16
    lda f:US_CKPT_LONG
    ora a:rl_ckpt_bit, x
    sta f:US_CKPT_LONG
    ; WIDTH-RISK: txa in A8 takes only X's low byte — X is a sector id (0..3)
    ; by construction here, so the high byte is known zero.
    txa
    sta f:US_SECTOR_LONG
    rep #$20
    .a16
    rts

; --- rl_hud_lap: stage the lap digit into the bg_text VBlank cell queue -----
; In/out: A8/I16, DB=0 (called from rl_lap's A8 stretch). A running scene
; cannot write VRAM itself — the NMI hook commits the staged cell. CLOBBERS X
; (text_queue_cell takes the VRAM address there) — the one caller brackets the
; jsr with phx/plx because X is its live sector index.
rl_hud_lap:
    .a8
    .i16
    lda f:US_LAP_LONG
    rep #$20
    .a16
    and #15
    cmp #10
    bcc :+
    adc #6                      ; carry set: +7 total ('A' - '9' - 1)
:   .a16
    clc
    adc #('0' - ' ')            ; glyph index (space is tile 0)
    ora #RACE_TXT_ATTR
    ldx #RACE_LAP_CELL
    jsr text_queue_cell
    sep #$20
    .a8
    rts
