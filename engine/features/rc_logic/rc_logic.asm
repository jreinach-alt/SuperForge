; =============================================================================
; rc_logic.asm — the racer's throttle / steer / integrate / off-road kernel
; =============================================================================
; race_logic's structure, a different physics model. B accelerates toward
; RC_SPEED_CAP; releasing it coasts to a FULL stop (there is no brake and no
; reverse); and while col_map says the tile under the kart is not drivable,
; speed bleeds by RC_OFFROAD_DRAG per frame down to RC_GRASS_CAP. Cutting the
; circuit costs time instead of a lap count — this rail has no laps.
;
; The magnitude-then-sign step kernel (rc_scale / rc_integrate) is the same
; math race_logic uses, for the same reason: the 65816's multiplier is 8x8, so
; a 16x16 magnitude product is decomposed and accumulated, and the sign is
; applied afterwards rather than by shifting a signed product.
;
; THE BINDING CONTRACT: the includer supplies the heading LUT label and the
; world's pixel wrap, because both belong to the rail's world and not to this
; kernel.
;
;  RCL_MOVE_LUT the 64-entry heading -> 8.8 unit forward vector table
;  RCL_WORLD_MASK the world's pixel wrap mask (4095 for a 4096 px torus)
.ifndef RCL_MOVE_LUT
    .error "rc_logic: the includer must define RCL_MOVE_LUT (the heading LUT label)"
.endif
.ifndef RCL_WORLD_MASK
    .error "rc_logic: the includer must define RCL_WORLD_MASK (the world's pixel wrap mask)"
.endif

; --- DP field aliases (ES_RC_HOT layout, feature.toml) ----------------------
RC_MAG  = ES_RC_HOT + 0             ; |u| (0..256)
RC_SGN  = ES_RC_HOT + 2             ; 1 = negate the product
RC_ACC  = ES_RC_HOT + 4             ; magnitude product accumulator
RC_UABS = ES_RC_HOT + 6             ; |speed| (speed is never negative here,
                                    ;  but the kernel keeps the shape so the
                                    ;  sign path stays exercised by |u|)
RC_STEPX = ES_RC_HOT + 8            ; signed 8.8 step, this frame
RC_STEPY = ES_RC_HOT + 10
RC_T    = ES_RC_HOT + 12            ; sub-accumulator sum
RC_TSA_A = ES_RC_HOT + 16           ; the timebase's three (fraction, step)
RC_TSA   = ES_RC_HOT + 18           ;   pairs: throttle accel, coast decel,
RC_TSD_A = ES_RC_HOT + 20           ;   and the steering
RC_TSD   = ES_RC_HOT + 22
RC_TSH_A = ES_RC_HOT + 24
RC_TSH   = ES_RC_HOT + 26
RC_VCAP  = ES_RC_HOT + 28           ; ...and the four region-picked constants
RC_VGRSS = ES_RC_HOT + 30
RC_VDRAG = ES_RC_HOT + 32
RC_VBAR  = ES_RC_HOT + 34
.assert RC_VBAR + 2 - ES_RC_HOT = ES_RC_HOT_SIZE, error, "the rc_hot field layout does not fill its DP claim"

; =============================================================================
; THE REGION-CORRECT UNITS — a speed takes r, an ACCELERATION takes r^2
; =============================================================================
; A PAL frame must carry r = 1.2018039 of the distance an NTSC frame carries
; (engine/features/tick_scale carries that derivation and is the only place
; the ratio lives). This rail's motion is a first-order integration rather
; than a ballistic arc, but the two-constant rule is the same one and for the
; same reason: US_SPEED is px per FRAME and scales by r, while RC_ACCEL,
; RC_DECEL and RC_OFFROAD_DRAG are px per frame SQUARED and scale by r^2.
; Together they leave the RAMP intact as well as the top speed —
; cap/accel frames becomes (cap*r)/(accel*r^2) = (cap/accel)/r frames, which
; at 50.007 fps is the same number of REAL SECONDS as it was at 60.099.
;
; TS_SCALED is tick_scale's build-time twin of TS_STEP's PAL arm, which is
; what lets a per-frame-SQUARED quantity be scaled TWICE (once here into the
; base, once by the macro). It is NOT a second copy of the ratio:
; TS_GAIN_NUM / TS_GAIN_DEN are tick_scale's and single-sourced.

TS_ACCEL_BASE   = RC_ACCEL * TS_ONE
TS_SCALED TS_ACCEL_BASE_R, TS_ACCEL_BASE
TS_DECEL_BASE   = RC_DECEL * TS_ONE
TS_SCALED TS_DECEL_BASE_R, TS_DECEL_BASE
; ONE POSE PER FRAME is `rc_steer`'s turn rate, and it is docs/95 §5.1's HARD
; class: a small integer with no correct x5/6. The accumulator answers it the
; way the animation dividers are answered elsewhere — the pose SET is
; untouched and what is scaled is how far the heading advances, so a PAL frame
; turns 1 or 2 poses averaging 1.2018 and the world rotates under the player
; at the same rate per REAL second.
TS_STEER_BASE   = 1 * TS_ONE

TS_SCALED RC_SPEED_CAP_R, RC_SPEED_CAP
TS_SCALED RC_GRASS_CAP_R, RC_GRASS_CAP
TS_SCALED RC_BAR_STEP_R,  RC_BAR_STEP
; THE OFF-ROAD BLEED IS SCALED AS AN INTEGER, not through an accumulator, and
; that is a stated rounding rather than an oversight. Its base would be
; 384 * TS_ONE = 98,304, past tick_scale's TS_BASE_MAX of 42,000 — the bound
; where `base * TS_GAIN_NUM` wraps ca65's 32-bit expression arithmetic — so an
; accumulator would need the quantity re-expressed in quarter units. It does
; not earn that: the constant is 384 counts, so r^2 lands on 554.6 and the
; nearest integer is 0.07% away. (The two constants that DO get accumulators
; are 64 and 48 counts, where the same rounding would cost 0.5%.)
; (two steps, not one nested call: ca65 will not parse a define-macro
;  invocation inside another one's argument list.)
TS_SCALED RC_OFFROAD_DRAG_1, RC_OFFROAD_DRAG
TS_SCALED RC_OFFROAD_DRAG_R, RC_OFFROAD_DRAG_1

; The bar reads FULL at the top speed on both machines, which is only true
; while the tick and the cap carry the same scale. Asserted rather than
; assumed: the bar is a rendered readout and a cap that outran its own step
; would light every tick and stay there.
.assert RC_BAR_STEP_R * RC_BAR_TICKS <= RC_SPEED_CAP_R, error, "the region-scaled speed bar cannot reach its last tick at the region-scaled cap"

RC_FLAG_DRIVABLE = 1                ; gen_col_flags.FLAG_DRIVABLE

; The speed bar is a rendered readout of a physics value, so how many lights a
; speed is worth is a game rule and lives here. The tick COUNT is DERIVED from
; rc_kart's OAM claim rather than narrated twice — both features are
; scene-scoped and the scene composes both, so the symbol is in scope.
RC_BAR_TICKS = ES_O_BAR_SPRITES
RC_BAR_STEP  = RC_SPEED_CAP / RC_BAR_TICKS

; --- rc_arm: the init contract + the kart at rest on the start line ---------
; CONTRACT rc_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the race state seeded — every word written here (rule 5)
;   clobbers: A, X, N, Z
;   assumes:  forced blank — the scene_mgr enter contract
;   tail:     rts
rc_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rc_arm"
    lda #0
    ldx #(ES_RC_HOT_SIZE - 2)
:   sta z:ES_RC_HOT, x
    dex
    dex
    bpl :-
    stz z:US_SPEED
    stz z:US_SUB_PX + 0
    stz z:US_SUB_PX + 2
    ; ---- the region's four constants. The loop above has already zeroed the
    ; three accumulators and their published steps, which is their
    ; write-before-read contract. ----------------------------------------
    lda z:ES_RGN_PAL
    beq :+
    lda #RC_SPEED_CAP_R
    sta z:RC_VCAP
    lda #RC_GRASS_CAP_R
    sta z:RC_VGRSS
    lda #RC_OFFROAD_DRAG_R
    sta z:RC_VDRAG
    lda #RC_BAR_STEP_R
    sta z:RC_VBAR
    bra :++
:   .a16
    .i16
    lda #RC_SPEED_CAP               ; today's constants, to the bit
    sta z:RC_VCAP
    lda #RC_GRASS_CAP
    sta z:RC_VGRSS
    lda #RC_OFFROAD_DRAG
    sta z:RC_VDRAG
    lda #RC_BAR_STEP
    sta z:RC_VBAR
:   .a16
    .i16
    sep #$20
    .a8
    lda #0                          ; (stz has no abs-long form)
    sta f:US_HEADING_LONG
    sta f:US_HEADING_AP_LONG
    sta f:US_LEAN_LONG
    sta f:US_PAUSED_LONG
    sta f:US_TOD_PH_LONG            ; phase 0 = the DAY hold
    sta f:US_GRAD_K_LONG            ; keyframe 0 = full day
    rep #$20
    .a16
    lda #RC_TOD_HOLD
    sta f:US_TOD_T_LONG
    rts

; --- rc_ts_publish: this frame's three region-correct steps, published once -
; CONTRACT rc_ts_publish
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      this frame's scaled steps published, one per rate
;   clobbers: A, N, Z
;   assumes:  the TOP of the scene tick, so everything below reads this
;             frame's steps. It runs unconditionally — TS_STEP carries a
;             fraction between frames, so a step computed only on the
;             frames a pad is held would carry a fraction sampled from the
;             player rather than from the clock
;   tail:     rts
;
; every consumer reads a settled word.
;
; On NTSC each publishes the constant this file authored, to the unit, and the
; carried fraction stays 0 for ever — which is why the NTSC picture cannot
; move. The two ACCELERATIONS take the r^2 arm: TS_STEP applies exactly one r,
; so the other one rides the BASE and the arm is chosen BEFORE the macro.
; ANONYMOUS LABELS, not `@cheap` ones: TS_STEP's `.local` labels are plain
; symbols, so expanding it between a `@label` and its use RESETS the
; cheap-local scope and the branch target goes undefined.
rc_ts_publish:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rc_ts_publish"
    TS_STEP z:RC_TSH_A, TS_STEER_BASE   ; the steering: ONE r (poses/frame)
    sta z:RC_TSH
    lda z:ES_RGN_PAL
    beq :+
    TS_STEP z:RC_TSA_A, TS_ACCEL_BASE_R
    sta z:RC_TSA
    TS_STEP z:RC_TSD_A, TS_DECEL_BASE_R
    sta z:RC_TSD
    rts
:   .a16
    .i16
    TS_STEP z:RC_TSA_A, TS_ACCEL_BASE
    sta z:RC_TSA
    TS_STEP z:RC_TSD_A, TS_DECEL_BASE
    sta z:RC_TSD
    rts

; --- rc_pause: START toggles the freeze. Out: A16, Z set while RACING -------
; CONTRACT rc_pause
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the freeze toggled by START. Z is SET while racing
;   clobbers: A, N, Z
;   assumes:  once per frame from the scene tick, during active display
;   tail:     rts
;
; The rising edge only (input's per-frame pressed latch is stable for exactly
; one frame), so holding START does not strobe. A frozen frame skips the whole
; per-frame body: the camera and the day-night clock both hold where they are —
; a true freeze-frame, which is what "pause" has to mean for a test that reads
; the picture.
rc_pause:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rc_pause"
    lda z:ES_INP_PRESS
    and #JOY_START
    beq @no_edge
    sep #$20
    .a8
    lda f:US_PAUSED_LONG
    eor #1
    sta f:US_PAUSED_LONG
    rep #$20
    .a16
@no_edge:
    .a16
    .i16
    sep #$20
    .a8
    lda f:US_PAUSED_LONG
    rep #$20
    .a16
    and #255                        ; the A8 load left the high byte stale
    rts

; --- rc_steer: LEFT/RIGHT turn one pose step per frame, and set the lean ----
; CONTRACT rc_steer
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the heading stepped by this frame's steer
;   clobbers: A, Y, N, Z, C, V
;   assumes:  the pads are already latched and rc_ts_publish has run
;   tail:     rts
rc_steer:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rc_steer"
    ldy #0                          ; lean: 0 straight
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    sep #$20
    .a8
    lda f:US_HEADING_LONG
    clc
    adc z:RC_TSH                    ; 1 pose on NTSC; 1 or 2 on PAL, averaging
    and #(RC_POSES - 1)             ;   1.2018 — the same turn per REAL second
    sta f:US_HEADING_LONG
    rep #$20
    .a16
    ldy #1                          ; lean left
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    sep #$20
    .a8
    lda f:US_HEADING_LONG
    sec
    sbc z:RC_TSH
    and #(RC_POSES - 1)
    sta f:US_HEADING_LONG
    rep #$20
    .a16
    ldy #2                          ; lean right (the left CHR, H-flipped)
@no_right:
    .a16
    .i16
    tya
    sep #$20
    .a8
    sta f:US_LEAN_LONG
    rep #$20
    .a16
    rts

; --- rc_throttle: B accelerates toward the cap, releasing coasts to a stop --
; CONTRACT rc_throttle
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the speed stepped by this frame's accelerate or decelerate
;   clobbers: A, N, Z, C, V
;   assumes:  the pads are already latched and rc_ts_publish has run
;   tail:     rts
rc_throttle:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rc_throttle"
    lda z:ES_INP_CUR
    and #JOY_B
    beq @coast
    lda z:US_SPEED
    clc
    adc z:RC_TSA
    cmp z:RC_VCAP
    bcc @store
    lda z:RC_VCAP                   ; clamp at top speed
    bra @store
@coast:
    .a16
    .i16
    lda z:US_SPEED
    sec
    sbc z:RC_TSD
    bcs @store
    lda #0                          ; floor at a full standstill
@store:
    .a16
    .i16
    sta z:US_SPEED
    rts

; --- rc_offroad: the map is collision ground truth --------------------------
; CONTRACT rc_offroad
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the off-road penalty applied to the speed
;   clobbers: A, N, Z, C, V
;   assumes:  the surface has been probed for this frame
;   tail:     rts
;
; Query the tile under the camera; if it is not drivable, bleed speed toward
; RC_GRASS_CAP. THIS FEEDS THE PHYSICS — unlike microzero's read-only cm_tick,
; which deliberately feeds nothing to protect a pinned measurement. Grass
; slowing the kart to a crawl IS this rail (its README's first sentence), so
; the query has to reach velocity here.
rc_offroad:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rc_offroad"
    lda z:ES_M7ORG + 0              ; the camera's world pixel x (wrapped by
    sta z:CM_PX                     ;   rc_move)
    lda z:ES_M7ORG + 2
    sta z:CM_PY
    jsr col_map_at                  ; leaves A8; CM_FLAG holds the result
    ; WIDTH-RISK: col_map_at EXITS A8 by contract, and it is a CROSS-FILE
    ; callee — the one thing `make width-check` structurally cannot see
    ; (CLAUDE.md rule 6's stated limit). Without this `.a8`, ca65 still tracks
    ; A16 from the `jsr` and assembles the `and` below as a THREE-byte 16-bit
    ; immediate; the CPU, actually in A8, eats two of those bytes and executes
    ; the stray $00 as BRK. That is not hypothetical here — it is the defect
    ; this rail shipped and then measured.
    .a8
    lda z:CM_FLAG
    and #RC_FLAG_DRIVABLE
    rep #$20
    .a16
    bne @on_track
    lda z:US_SPEED
    cmp z:RC_VGRSS
    bcc @done                       ; already at the crawl: no extra drag
    sec
    sbc z:RC_VDRAG
    cmp z:RC_VGRSS
    bcs @store
    lda z:RC_VGRSS                  ; floor the bleed at the crawl speed
@store:
    .a16
    .i16
    sta z:US_SPEED
    bra @done
@on_track:
    .a16
    .i16
@done:
    .a16
    .i16
    rts

; --- rc_move: step the camera origin along the heading ----------------------
; CONTRACT rc_move
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the position stepped along the heading at the current speed
;   clobbers: A, X, N, Z, C
;   assumes:  rc_steer and rc_throttle have already run
;   tail:     rts
rc_move:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rc_move"
    lda z:US_SPEED
    beq @none                       ; stopped: no step, the accumulators hold
    sta z:RC_UABS
    sep #$20
    .a8
    lda f:US_HEADING_LONG
    rep #$20
    .a16
    and #255                        ; the A8 load left the high byte stale
    asl
    asl
    tax                             ; LUT byte index = heading * 4
    lda a:RCL_MOVE_LUT + 0, x
    phx
    jsr rc_scale
    sta z:RC_STEPX
    plx
    lda a:RCL_MOVE_LUT + 2, x
    jsr rc_scale
    sta z:RC_STEPY
    lda z:RC_STEPX
    ldx #0
    jsr rc_integrate
    lda z:RC_STEPY
    ldx #2
    jsr rc_integrate
@none:
    .a16
    .i16
    rts

; --- rc_scale: (|u| * speed) >> 8, signed by sign(u) ------------------------
; In: A16 = u (signed 8.8 unit component, -256..256); RC_UABS set. Out: A16 =
; signed 8.8 step. Clobbers X, RC_MAG/RC_SGN/RC_ACC.
rc_scale:
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
    .i16
    sta z:RC_MAG
    txa
    and #1
    sta z:RC_SGN
    ; ---- (ml * vl) >> 8 ---------------------------------------------------
    ; WIDTH-RISK: the multiplier ports are 8-bit; every A8 load below takes the
    ; LOW byte of a DP word on purpose. Exits A16 for the caller.
    sep #$20
    .a8
    lda z:RC_MAG                    ; ml
    sta a:$4202
    lda z:RC_UABS                   ; vl
    sta a:$4203
    ; 8 CPU CYCLES BEFORE RDMPY IS VALID, counted per instruction rather than
    ; counted by the reader, and spent in 3 bytes instead of 4. The densest
    ; padding this CPU has is a stack pair — `phb`/`plb` is 7 cycles in 2 bytes
    ; — but 7 does not divide 8 and there is no one-cycle instruction to finish
    ; it, so the exact form is the `xba` pair (3 + 3, which puts A back) plus
    ; one `nop`. A and the flags are both dead here: the `lda a:$4216` below
    ; reloads A at the full width and nothing between reads a flag.
    xba                             ; 3
    xba                             ; 3   — A restored
    nop                             ; 2   = 8
    rep #$20
    .a16
    lda a:$4216
    xba
    and #255
    sta z:RC_ACC
    ; ---- + ml * vh --------------------------------------------------------
    sep #$20
    .a8
    lda z:RC_MAG
    sta a:$4202
    lda z:RC_UABS + 1               ; vh
    sta a:$4203
    xba                             ; 3   — the same 8-cycle RDMPY window as above
    xba                             ; 3
    nop                             ; 2   = 8
    rep #$20
    .a16
    lda a:$4216
    clc
    adc z:RC_ACC
    sta z:RC_ACC
    ; ---- + mh * speed (mh is 0 or 1 — |u| never exceeds 256) -------------
    lda z:RC_MAG
    cmp #256
    bcc @sign
    lda z:RC_UABS
    clc
    adc z:RC_ACC
    sta z:RC_ACC
@sign:
    .a16
    .i16
    lda z:RC_ACC
    ldx z:RC_SGN
    beq @out
    eor #$FFFF
    inc a
@out:
    .a16
    .i16
    rts

; --- rc_integrate: add a signed 8.8 step to one world axis ------------------
; In: A16 = step; X = axis byte offset (0 = x, 2 = y) into the contiguous
;  US_SUB_PX pair and the M7ORG position pair.
rc_integrate:
    .a16
    .i16
    clc
    adc z:US_SUB_PX, x
    sta z:RC_T
    and #255
    sta z:US_SUB_PX, x
    lda z:RC_T
    xba                             ; whole-pixel part = the high byte...
    and #255
    cmp #128
    bcc :+
    ora #$FF00                      ; ...sign-extended (t >> 8 is a FLOOR shift)
:   .a16
    .i16
    clc
    adc z:ES_M7ORG, x
    and #(RCL_WORLD_MASK)           ; the world torus wraps
    sta z:ES_M7ORG, x
    rts

; --- rc_bar_ticks: speed -> lit tick count. Out: Y = 0..RC_BAR_TICKS --------
; CONTRACT rc_bar_ticks
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      Y = the lit tick count, 0..RC_BAR_TICKS, derived from the
;             speed
;   clobbers: A, Y, N, Z, C, V
;   assumes:  nothing — it is a pure function of the speed word
;   tail:     rts
;
; The bar is a rendered readout of a physics value, so the mapping is here
; rather than in rc_kart: how many lights a speed is worth is a game rule.
rc_bar_ticks:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "rc_bar_ticks"
    lda z:US_SPEED
    ldy #0
@count:
    .a16
    .i16
    cmp z:RC_VBAR
    bcc @done
    sec
    sbc z:RC_VBAR
    iny
    cpy #RC_BAR_TICKS
    bcc @count
@done:
    .a16
    .i16
    rts
