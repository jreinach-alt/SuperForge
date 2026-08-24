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
RL_TSH_A  = ES_RL_HOT + 16          ; the timebase's two (fraction, step)
RL_TSH    = ES_RL_HOT + 18          ;   pairs: the steering and the coast
RL_TSF_A  = ES_RL_HOT + 20          ;   friction
RL_TSF    = ES_RL_HOT + 22
RL_VMAX   = ES_RL_HOT + 24          ; ...and the five region-picked constants
RL_VMIN   = ES_RL_HOT + 26
RL_VACC   = ES_RL_HOT + 28
RL_VBRK   = ES_RL_HOT + 30
RL_VREV   = ES_RL_HOT + 32
.assert RL_VREV + 2 - ES_RL_HOT = ES_RL_HOT_SIZE, error, "the rl_hot field layout does not fill its DP claim"

; =============================================================================
; THE REGION-CORRECT UNITS — a speed takes r, an ACCELERATION takes r^2
; =============================================================================
; A PAL frame must carry r = 1.2018039 of the distance an NTSC frame carries
; (engine/features/tick_scale carries that derivation and is the only place
; the ratio lives). This rail's motion is a first-order integration rather
; than a ballistic arc, but the two-constant rule is the same one and for the
; same reason: US_VEL is px per FRAME and scales by r, while MZ_ACCEL,
; MZ_BRAKE, MZ_REVERSE and MZ_FRICTION are px per frame SQUARED and scale by
; r^2. Together they leave the RAMP intact as well as the top speed —
; cap/accel frames becomes (cap*r)/(accel*r^2) = (cap/accel)/r frames, which
; at 50.007 fps is the same number of REAL SECONDS as it was at 60.099.
;
; TS_SCALED / TS_SCALE are tick_scale's build-time twin of TS_STEP's PAL arm,
; which is what lets a per-frame-SQUARED quantity be scaled TWICE (once here
; into the base, once by the macro). They are NOT a second copy of the ratio:
; TS_GAIN_NUM / TS_GAIN_DEN are tick_scale's and single-sourced, and the
; `+ DEN/2` rounding is the run-time arm's own, so the two cannot disagree by
; a count.

; --- the two caps: one r each, chosen once at arm --------------------------
; These are ASSIGNMENTS (a clamp writes one or the other), not accumulations,
; so they carry no fraction and there is no accumulator to declare. A console
; cannot change region, so the pair is picked once in rl_arm.
TS_SCALED MZ_VEL_MAX_R, MZ_VEL_MAX
MZ_VEL_MIN_MAG   = (1 << 16) - MZ_VEL_MIN   ; the reverse cap's MAGNITUDE: a
                                            ;   direction does not scale, so
TS_SCALED MZ_VEL_MIN_MAG_R, MZ_VEL_MIN_MAG
MZ_VEL_MIN_R     = (1 << 16) - MZ_VEL_MIN_MAG_R   ; the sign is re-applied

; --- the three big accelerations: r^2, as build-time INTEGERS --------------
; Two TS_SCALED steps rather than one nested call — ca65 will not parse a
; define-macro invocation inside another one's argument list.
;
; NO ACCUMULATOR FOR THESE THREE, and that is a stated rounding rather than an
; oversight. Their accumulator bases would be 65,536 / 98,304 / 32,768 counts
; against tick_scale's TS_BASE_MAX of 42,000 — the bound where the build-time
; scale wraps ca65's 32-bit expression arithmetic — and they do not earn the
; re-expression it would take to fit: at 256, 384 and 128 counts the nearest
; integer is 0.068%, 0.11% and 0.068% away. MZ_FRICTION is the one that DOES
; earn a carried fraction (64 counts, where the same rounding costs 0.61%),
; and it gets one below.
TS_SCALED MZ_ACCEL_R1,   MZ_ACCEL
TS_SCALED MZ_ACCEL_R,    MZ_ACCEL_R1
TS_SCALED MZ_BRAKE_R1,   MZ_BRAKE
TS_SCALED MZ_BRAKE_R,    MZ_BRAKE_R1
TS_SCALED MZ_REVERSE_R1, MZ_REVERSE
TS_SCALED MZ_REVERSE_R,  MZ_REVERSE_R1

; --- friction: the r^2 site that carries a fraction ------------------------
; TS_STEP applies exactly one r, so the other one rides the BASE — on the PAL
; arm only, which is why rl_ts_publish branches on ES_RGN_PAL BEFORE the macro
; instead of after it. Both arms share one accumulator: a console cannot
; change region, so only one of them is ever taken.
TS_FRIC_BASE   = MZ_FRICTION * TS_ONE
TS_SCALED TS_FRIC_BASE_R, TS_FRIC_BASE

; --- the steering: ONE r, and the pose SET is untouched --------------------
; One pose per frame is rl_steer's declared max turn, and it is docs/95 §5.1's
; hard class: a small integer with no correct x5/6. The accumulator answers it
; the way an animation divider is answered — the 64-pose set and the pose LUTs
; stay exactly as generated, and what is scaled is how far the HEADING
; advances, so a PAL frame turns 1 or 2 poses averaging 1.2018 and the world
; rotates under the player at the same rate per REAL second.
TS_STEER_BASE = 1 * TS_ONE

; THE STREAMING CLAMP IS SIZED AGAINST THIS CAP, so the bound is asserted here,
; where the scale is applied. mode7_stream stages at most 8 tiles per axis per
; frame and NEVER SNAPS, so a frame that needs a ninth leaves it for the next
; one and VRAM trails the camera. The worst crossing count is not step/8: a
; step lands on an arbitrary sub-tile phase, so it is
; floor((7 + wholepx) / 8), and the whole-pixel step itself is at most
; (255 + cap) >> 8 once the sub-pixel accumulator is full. At cap = 64 px that
; is floor((7 + 64) / 8) = 8 — exactly the clamp — and one 8.8 count more
; makes it 9. MZ_VEL_MAX_R is 57.69 px/frame, whose worst frame MEASURES 8
; staged and 0 deferred (game.toml carries the table).
.assert MZ_VEL_MAX_R <= 64 << 8, error, "the region-scaled top speed exceeds 64 px/frame — a frame's walk can now cross 9 tiles on one axis and mode7_stream's 8-per-axis clamp would defer the ninth"

; CAM0 sits on the start/finish spoke, east and south of the ring centre — the
; sector the lap machine starts in. Guarded, not narrated:
RL_SECTOR0 = 3
.assert CAM0_PX >= MZ_CENTER_PX, error, "CAM0 is not east of the ring centre"
.assert CAM0_PY >= MZ_CENTER_PX, error, "CAM0 is not south of the ring centre"

rl_ckpt_bit: .byte 1, 2, 4, 8       ; sector -> checkpoint mask bit

; --- rl_arm: init contract + race state at the start line -------------------
; CONTRACT rl_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the race state seeded — every word written here (rule 5)
;   clobbers: A, X, N, Z
;   assumes:  forced blank — the scene enter contract
;   tail:     rts
rl_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rl_arm"
    ldx #(ES_RL_HOT_SIZE - 2)
:   stz z:ES_RL_HOT, x
    dex
    dex
    bpl :-
    stz z:US_VEL
    stz z:US_SUB_PX + 0
    stz z:US_SUB_PX + 2
    ; ---- the region's five constants. The loop above has already zeroed the
    ; two accumulators and their published steps, which is their
    ; write-before-read contract. -----------------------------------------
    lda z:ES_RGN_PAL
    beq :+
    lda #MZ_VEL_MAX_R
    sta z:RL_VMAX
    lda #MZ_VEL_MIN_R
    sta z:RL_VMIN
    lda #MZ_ACCEL_R
    sta z:RL_VACC
    lda #MZ_BRAKE_R
    sta z:RL_VBRK
    lda #MZ_REVERSE_R
    sta z:RL_VREV
    bra :++
:   .a16
    .i16
    lda #MZ_VEL_MAX                 ; today's constants, to the bit
    sta z:RL_VMAX
    lda #MZ_VEL_MIN
    sta z:RL_VMIN
    lda #MZ_ACCEL
    sta z:RL_VACC
    lda #MZ_BRAKE
    sta z:RL_VBRK
    lda #MZ_REVERSE
    sta z:RL_VREV
:   .a16
    .i16
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

; --- rl_ts_publish: this frame's two region-correct steps, published once ---
; In/out: A16/I16, DB=0. Clobbers A. Called at the top of rl_tick, so every
; consumer reads a settled word.
;
; On NTSC each publishes the constant tools/gen_move_lut.py authored, to the
; unit, and the carried fraction stays 0 for ever — which is why the NTSC
; picture cannot move and why that generator's `Sim` is still the tests'
; bit-exact oracle. The FRICTION is an acceleration and takes the r^2 arm:
; TS_STEP applies exactly one r, so the other one rides the BASE and the arm
; is chosen BEFORE the macro.
; ANONYMOUS LABELS, not `@cheap` ones: TS_STEP's `.local` labels are plain
; symbols, so expanding it between a `@label` and its use RESETS the
; cheap-local scope and the branch target goes undefined.
rl_ts_publish:
    .a16
    .i16
    TS_STEP z:RL_TSH_A, TS_STEER_BASE   ; the steering: ONE r (poses/frame)
    sta z:RL_TSH
    lda z:ES_RGN_PAL
    beq :+
    TS_STEP z:RL_TSF_A, TS_FRIC_BASE_R
    sta z:RL_TSF
    rts
:   .a16
    .i16
    TS_STEP z:RL_TSF_A, TS_FRIC_BASE
    sta z:RL_TSF
    rts

; --- rl_tick: one frame of race logic (race::tick) --------------------------
; CONTRACT rl_tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one frame of race logic: steering, friction and the lap
;             machine
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  once per frame from the scene tick, during active display
;   tail:     rts
rl_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rl_tick"
    jsr rl_ts_publish           ; this frame's region-correct steps, once
    jsr rl_steer
    jsr rl_velocity
    jsr rl_move
    jsr rl_lap
    rts

; --- rl_steer: L/R turn one pose step per frame (the declared max) --
; RL_TSH is the region's answer to that "one": 1 on NTSC for ever, 1 or 2 on
; PAL averaging 1.2018, so the world turns at the same rate per REAL second.
; The A8 loads take the published word's LOW byte on purpose — the step is 1
; or 2 by construction and the heading is masked to 0..63 either way.
rl_steer:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #JOY_LEFT
    beq :+
    sep #$20
    .a8
    lda f:US_HEADING_LONG
    clc
    adc z:RL_TSH
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
    sec
    sbc z:RL_TSH
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
    sbc z:RL_TSF
    bpl @store                  ; still forward
    lda #0
    bra @store
@coast_neg:
    .a16
    clc
    adc z:RL_TSF
    bmi @store                  ; still reversing
    lda #0
    bra @store
@accel:
    .a16
    lda z:US_VEL
    clc
    adc z:RL_VACC
    bmi @store                  ; still below zero: nowhere near the cap
    ; `cmp cap / bcc / lda cap` where this used to read `cmp #(cap+1) / bcc /
    ; lda #cap`. The two differ only when vel EQUALS the cap, where the first
    ; stores the cap and the second stores a value that already IS the cap —
    ; the same word either way. What the rewrite buys is a cap that can live
    ; in a word instead of in two immediates.
    cmp z:RL_VMAX
    bcc @store
    lda z:RL_VMAX               ; clamp at top speed
    bra @store
@brake:
    .a16
    lda z:US_VEL
    beq @reverse
    bmi @reverse
    sec
    sbc z:RL_VBRK
    bpl @store                  ; braked, still rolling forward
    lda #0
    bra @store
@reverse:
    .a16
    lda z:US_VEL
    sec
    sbc z:RL_VREV
    cmp z:RL_VMIN               ; unsigned: both operands are $8000..$FFFF
    bcs @store
    lda z:RL_VMIN
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
    ; 8 CPU CYCLES BEFORE RDMPY IS VALID, counted per instruction rather than
    ; counted by the reader, and spent in 3 bytes instead of 4. The densest
    ; padding this CPU has is a stack pair — `phb`/`plb` is 7 cycles in 2 bytes
    ; — but 7 does not divide 8 and there is no one-cycle instruction to finish
    ; it, so the exact form is the `xba` pair (3 + 3, which puts A back) plus
    ; one `nop`. A and the flags are both dead here: the `lda a:$4216` below
    ; reloads A at the full width and nothing between reads a flag.
    xba                         ; 3
    xba                         ; 3   — A restored
    nop                         ; 2   = 8
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
    xba                         ; 3   — the same 8-cycle RDMPY window as above
    xba                         ; 3
    nop                         ; 2   = 8
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
