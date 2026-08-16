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

RC_FLAG_DRIVABLE = 1                ; gen_col_flags.FLAG_DRIVABLE

; The speed bar is a rendered readout of a physics value, so how many lights a
; speed is worth is a game rule and lives here. The tick COUNT is DERIVED from
; rc_kart's OAM claim rather than narrated twice — both features are
; scene-scoped and the scene composes both, so the symbol is in scope.
RC_BAR_TICKS = ES_O_BAR_SPRITES
RC_BAR_STEP  = RC_SPEED_CAP / RC_BAR_TICKS

; --- rc_arm: the init contract + the kart at rest on the start line ---------
; In/out: A16/I16, DB=0, forced blank (scene_mgr enter contract).
rc_arm:
    .a16
    .i16
    lda #0
    ldx #(ES_RC_HOT_SIZE - 2)
:   sta z:ES_RC_HOT, x
    dex
    dex
    bpl :-
    stz z:US_SPEED
    stz z:US_SUB_PX + 0
    stz z:US_SUB_PX + 2
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

; --- rc_pause: START toggles the freeze. Out: A16, Z set while RACING -------
; The rising edge only (input's per-frame pressed latch is stable for exactly
; one frame), so holding START does not strobe. A frozen frame skips the whole
; per-frame body: the camera and the day-night clock both hold where they are —
; a true freeze-frame, which is what "pause" has to mean for a test that reads
; the picture.
rc_pause:
    .a16
    .i16
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
rc_steer:
    .a16
    .i16
    ldy #0                          ; lean: 0 straight
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    sep #$20
    .a8
    lda f:US_HEADING_LONG
    inc a
    and #(RC_POSES - 1)
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
    dec a
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
rc_throttle:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_B
    beq @coast
    lda z:US_SPEED
    clc
    adc #RC_ACCEL
    cmp #RC_SPEED_CAP
    bcc @store
    lda #RC_SPEED_CAP               ; clamp at top speed
    bra @store
@coast:
    .a16
    .i16
    lda z:US_SPEED
    sec
    sbc #RC_DECEL
    bcs @store
    lda #0                          ; floor at a full standstill
@store:
    .a16
    .i16
    sta z:US_SPEED
    rts

; --- rc_offroad: the map is collision ground truth --------------------------
; Query the tile under the camera; if it is not drivable, bleed speed toward
; RC_GRASS_CAP. THIS FEEDS THE PHYSICS — unlike microzero's read-only cm_tick,
; which deliberately feeds nothing to protect a pinned measurement. Grass
; slowing the kart to a crawl IS this rail (its README's first sentence), so
; the query has to reach velocity here.
rc_offroad:
    .a16
    .i16
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
    cmp #RC_GRASS_CAP
    bcc @done                       ; already at the crawl: no extra drag
    sec
    sbc #RC_OFFROAD_DRAG
    cmp #RC_GRASS_CAP
    bcs @store
    lda #RC_GRASS_CAP               ; floor the bleed at the crawl speed
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
rc_move:
    .a16
    .i16
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
    nop                             ; 8 CPU cycles before RDMPY is valid
    nop
    nop
    nop
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
    nop
    nop
    nop
    nop
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
; The bar is a rendered readout of a physics value, so the mapping is here
; rather than in rc_kart: how many lights a speed is worth is a game rule.
rc_bar_ticks:
    .a16
    .i16
    lda z:US_SPEED
    ldy #0
@count:
    .a16
    .i16
    cmp #RC_BAR_STEP
    bcc @done
    sec
    sbc #RC_BAR_STEP
    iny
    cpy #RC_BAR_TICKS
    bcc @count
@done:
    .a16
    .i16
    rts
