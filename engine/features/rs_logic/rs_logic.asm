; =============================================================================
; rs_logic.asm — the rail driver: the S-curve, the field it bends around, the
;  aim, the shot, the damage and the failure
; =============================================================================
; THE REDESIGN. Three things make this rail what it is now, and all three are
; here:
;
;  * THE SHIP FLIES ITSELF, around a repeating S-curve. `rs_path_step` reads a
;  baked table with the frame odometer and writes the result into the CAMERA
;  ORIGIN — a TRANSLATION. It never touches the heading. The pose table has
;  64 entries, so the smallest turn the plane can make is 5.6 degrees, and
;  steering with it is exactly what made the shipped rail read as binary.
;
;  * THE PLAYER AIMS AND NOTHING ELSE. The d-pad moves a point on the GROUND
;  PLANE in WORLD coordinates; the ship ignores the pad entirely. Because the
;  aim point is world-anchored and projected through the same pinhole as the
;  hazards, the ship's swing DRAGS it across the screen — the compensation is
;  the skill demand, and it is emergent rather than faked.
;
;  * ONE ODOMETER DRIVES EVERYTHING. `US_DIST` is +1 per frame. The path index,
;  the spawn schedules and each actor's arrival phase all come off it, so the
;  curve and the obstacles it bends around are phase-locked BY CONSTRUCTION.
;  `dist * RS_OBS_STEP + z` is invariant across an actor's whole flight, so
;  `rs_path[dist + RS_LEAD]` is literally where the camera WILL BE when that
;  actor arrives.

; --- the kernel's transient scratch (the rs_hot claim), named ---------------
RSL_OFF     = ES_RS_HOT + 0         ; the actor cursor, an absolute byte offset
RSL_BUL_OFF = ES_RS_HOT + 2         ; the tracer cursor
RSL_T0      = ES_RS_HOT + 4         ; a value held across one nested scan
RSL_T1      = ES_RS_HOT + 6         ; likewise
RSL_BEST    = ES_RS_HOT + 8         ; the hitscan's best hazard, a cache offset
RSL_BESTZ   = ES_RS_HOT + 10        ; ...and its depth, so "nearest wins"
RSL_ABASE   = ES_RS_HOT + 12        ; the pool base the generic loops run over
RSL_AEND    = ES_RS_HOT + 14        ; ...and its base + 2*slots

; =============================================================================
; rs_logic_arm — the rail's whole starting state (scene enter, and the restart)
; =============================================================================
; In/out: A16/I16, DB=0. At scene enter this runs under forced blank with NMI
; masked (scene_mgr contract); it is ALSO the self-restart the fail state calls
; on a running frame, which is safe because it touches no PPU port.
;
; Every declared byte this rail owns is written here, before any tick reads it.
; That is what lets both WRAM claims stay OUT of `[init] zero` under a random
; power-on (CLAUDE.md rule 5): a defect that stopped this running would show as
; garbage rather than as a plausible zero.
;
; WIDTH-RISK: A16/I16 entry AND exit, and the routine now contains NO `sep`/
; `rep` at all — the redesign deleted the heading words, so the two one-byte
; heading stores this marker used to describe are gone. A width contract that
; names writes which no longer exist is worse than none: rule 6 makes these
; markers load-bearing for the cross-file case precisely because the linter
; cannot see callers. `pool_init` holds the same A16/I16 contract on both sides
; (cross-file, so it is stated here too).
rs_logic_arm:
    .a16
    .i16
    ; ---- the odometer and the camera it drives ----------------------------
    lda #0
    sta f:US_DIST_LONG
    sta f:US_ADV_FRAC_LONG
    sta f:US_LEAN_LONG
    sta f:US_LANE_LONG
    sta f:US_SPAWN_T_LONG
    sta f:US_BURST_T_LONG
    sta f:US_BURST_SX_LONG
    sta f:US_BURST_SY_LONG
    sta f:US_BURST_F_LONG
    sta f:US_SCORE_LONG
    sta f:US_FAIL_T_LONG
    sta f:US_SHOTS_LIVE_LONG
    sta f:US_HAZARDS_LIVE_LONG
    lda #RS_CENTRE
    sta z:US_CAM_X                  ; path[0] is 0, so the S starts centred
    sta f:US_CAM_Y_LONG
    sta f:US_RET_X_LONG             ; the aim starts down the rail's own lane
    lda #RS_RET_Z_INIT
    sta f:US_RET_Z_LONG
    lda #RS_LIVES_N
    sta f:US_LIVES_LONG
    ; NOTHING SETS A HEADING HERE, because there is no heading state left to
    ; set: `persp_set_pose` runs once from the scene's enter with 0 and this
    ; ROM has no other caller. See the note in main.asm's NMI hook.
    ; ---- all three pools, through the mechanism ---------------------------
    ; Empty, not seeded: the field is SCHEDULED now, so `rs_spawn` fills it one
    ; actor at a time and the pool's allocate path runs from the first frame.
    POOL_BIND ES_RS_ACTORS_LONG + RS_OBS_ALIVE
    ldx #RS_OBS_N
    jsr pool_init
    POOL_BIND ES_RS_ACTORS_LONG + RS_PYL_ALIVE
    ldx #RS_PYL_N
    jsr pool_init
    POOL_BIND ES_RS_ACTORS_LONG + RS_BUL_ALIVE
    ldx #RS_BUL_N
    jsr pool_init
    rts

; =============================================================================
; rs_path_at — A = the S-curve's lateral offset at odometer value A (signed)
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X. The whole curve is this one read.
; `rs_path_bin` is 256 signed words baked by tools/gen_railshooter_assets.py;
; the caller passes an odometer value and gets the offset at that phase, which
; is what makes "where will the camera be in RS_LEAD frames" a table lookup
; rather than a simulation.
;
; THE TABLE IS SAMPLED ONCE PER FRAME (RS_PATH_SHIFT = 0), so the
; `.repeat` below is ZERO-TRIP and this routine is now three instructions and a
; long read. It is kept rather than deleted because the shift is the ONE knob
; that decides the curve's temporal resolution: a future change that raises it
; must see the divide it is reintroducing, and is what a held entry costs
; (three still frames then a 21-px lurch of the whole plane).
; `::` is LOAD-BEARING on the `.repeat`: a repeat count must be a constant
; expression and ca65 2.18 DEFERS an unqualified parent-scope lookup inside a
; `.scope` (the same measurement race.asm's binding block records). WIDTH-RISK:
; A16/I16 entry AND exit; no sep/rep.
rs_path_at:
    .a16
    .i16
    .repeat ::RS_PATH_SHIFT
    lsr a
    .endrepeat
    and #RS_PATH_MASK
    asl a                           ; a word table
    tax
    lda f:rs_path_bin, x
    rts

; =============================================================================
; rs_path_step — the odometer, the camera's lateral position, and the bank
; =============================================================================
; In/out: A16/I16, DB=0.
;
; THE CAMERA ORIGIN IS THE ONLY THING THIS WRITES. `US_CAM_X` lands in the M7X
; shadow in `rs_advance`, and M7X is a free per-frame CPU-written VBlank shadow
; over a wrapping 16-bit world position (mode7_persp/feature.toml:36,50). No
; heading is touched anywhere in this file.
;
; THE BANK LEADS THE SWING, with no extra state: the derivative of a sine is
; the same table read a quarter period along, so the ship's lean comes from
; `rs_path[dist + QUARTER]` and tips into the turn rather than out of it.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. Every label annotated;
; rs_path_at and rs_abs16 hold the same contract.
rs_path_step:
    .a16
    .i16
    lda f:US_DIST_LONG
    inc a
    sta f:US_DIST_LONG
    ; ---- cam_x = centre + path[dist] --------------------------------------
    jsr rs_path_at
    clc
    adc #RS_CENTRE
    and #RS_WORLD_MASK
    sta z:US_CAM_X
    ; ---- the bank, from the path's own slope ------------------------------
    lda #RS_LEAN_NONE
    sta f:US_LEAN_LONG
    lda f:US_DIST_LONG
    clc
    adc #(RS_PATH_QUARTER << RS_PATH_SHIFT)
    jsr rs_path_at
    sta RSL_T0                      ; the signed slope
    jsr rs_abs16
    cmp #RS_BANK_DEAD
    bcc @done                       ; near an extreme: flying straight
    lda RSL_T0
    bmi @left
    lda #RS_LEAN_RIGHT
    sta f:US_LEAN_LONG
    rts
@left:
    .a16
    .i16
    lda #RS_LEAN_LEFT
    sta f:US_LEAN_LONG
@done:
    .a16
    .i16
    rts

; =============================================================================
; rs_advance — the rail walks forward, always, at 1.5 world px/frame
; =============================================================================
; In/out: A16/I16, DB=0.
;
; The forward axis is DECOUPLED from the hazards' depth axis: this drives the
; Mode 7 floor's texture scroll (the speed cue) and nothing else, while each
; actor carries its own z scalar. That decoupling is the rail's headline —
; anchoring hazards to the matrix instead gives only ~14 world px of forward
; depth, far too shallow for a multi-frame approach.
;
; 1.5 px/frame is a 75% cut on the obvious 6, held in 8.8 because an integer
; 1 or 2 reads as steppy at this scale. `xba` lifts the accumulator's
; whole-pixel part out; the fraction is masked back down.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep anywhere.
rs_advance:
    .a16
    .i16
    lda f:US_ADV_FRAC_LONG
    clc
    adc #RS_RAIL_SPEED_88
    pha
    and #RS_ADV_FRAC_MASK
    sta f:US_ADV_FRAC_LONG          ; the fraction carries to next frame
    pla
    xba                             ; the whole pixels were the high byte
    and #RS_ADV_FRAC_MASK
    sta RSL_T0
    lda f:US_CAM_Y_LONG
    sec
    sbc RSL_T0
    and #RS_WORLD_MASK
    sta f:US_CAM_Y_LONG
    ; the Mode 7 origin shadows the NMI hook commits every armed frame
    lda z:US_CAM_X
    sta z:ES_M7ORG + 0              ; M7X — the S-curve lands HERE
    lda f:US_CAM_Y_LONG
    sta z:ES_M7ORG + 2              ; M7Y
    lda z:US_CAM_X
    sec
    sbc #RS_SCREEN_HALF
    sta z:ES_M7ORG + 4              ; HOFS: the screen's centre column
    lda f:US_CAM_Y_LONG
    sec
    sbc #RS_SKY_LINES
    sta z:ES_M7ORG + 6              ; VOFS: the pivot sits on the horizon seam
    rts

; =============================================================================
; rs_reticle_move — the d-pad, and the ONLY thing the player controls
; =============================================================================
; In/out: A16/I16, DB=0.
;
; A point on the ground plane in WORLD coordinates. LEFT/RIGHT slide it along
; the world's lateral axis (wrapping with the plane); UP/DOWN push it further
; down the rail or pull it back, clamped, because a one-axis reticle could only
; ever reach hazards at one depth.
;
; Nothing here touches the camera. The reticle's SCREEN position is computed by
; the projection, from (ret_x - cam_x), which is exactly why the ship's swing
; drags it: the world point is standing still and the camera is not.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. Every label annotated.
rs_reticle_move:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #RS_JOY_LEFT
    beq @no_left
    lda f:US_RET_X_LONG
    sec
    sbc #RS_RET_SPEED
    and #RS_WORLD_MASK
    sta f:US_RET_X_LONG
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #RS_JOY_RIGHT
    beq @no_right
    lda f:US_RET_X_LONG
    clc
    adc #RS_RET_SPEED
    and #RS_WORLD_MASK
    sta f:US_RET_X_LONG
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #RS_JOY_UP
    beq @no_up
    lda f:US_RET_Z_LONG
    clc
    adc #RS_RET_Z_STEP              ; UP pushes the aim further down the rail
    cmp #(RS_RET_Z_MAX + 1)
    bcc :+
    lda #RS_RET_Z_MAX
:   .a16
    .i16
    sta f:US_RET_Z_LONG
@no_up:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #RS_JOY_DOWN
    beq @no_down
    lda f:US_RET_Z_LONG
    sec
    sbc #RS_RET_Z_STEP
    cmp #RS_RET_Z_MIN
    bcs :+
    lda #RS_RET_Z_MIN
:   .a16
    .i16
    sta f:US_RET_Z_LONG
@no_down:
    .a16
    .i16
    rts

; =============================================================================
; rs_next_lane — A = the next lateral lane OFFSET; the cursor advances
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; SIGNED OFFSETS FROM THE PATH, not absolute world columns, and that is the
; redesign's change. A hazard is placed at `path(arrival) + offset`, so the
; offset is literally how far off the ship's nose it will pass: two of the four
; are inside RS_SHIP_HIT_X and will hurt, two are outside and will not. That is
; what makes every hazard a decision rather than scenery.
;
; The cursor moves through A and the table is read with X, because the 65816
; has `lda long,x` and NO `lda long,y` and no long form of `ldy` at all — the
; same asymmetry that forces `pool`'s caller-side cursor into X. WIDTH-RISK:
; A16/I16 entry AND exit; no sep/rep.
rs_next_lane:
    .a16
    .i16
    lda f:US_LANE_LONG
    tax
    clc
    adc #2
    and #((RS_LANES * 2) - 1)       ; cycle 0,2,4,6 (a power-of-two lane count)
    sta f:US_LANE_LONG
    lda f:rs_lane_tab, x
    rts

rs_lane_tab:
    .word (1 << 16) - 56, (1 << 16) - 20, 20, 56
.assert (RS_LANES & (RS_LANES - 1)) = 0, error, "the lane cursor's mask needs a power-of-two lane count"

; =============================================================================
; rs_spawn — the scheduled field: a hazard every RS_OBS_GAP, a pylon per bend
; =============================================================================
; In/out: A16/I16, DB=0.
;
; BOTH SPAWNS PLACE THEIR ACTOR AGAINST THE CAMERA'S FUTURE, not its present.
; `rs_path_at(dist + RS_LEAD)` is where the camera will be when the actor
; arrives, because `dist` rises at exactly the rate `z` falls. A hazard lands
; near that column (so it is a threat); a pylon lands on the OPPOSITE side at
; twice the amplitude (so the path visibly bends around it).
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. POOL_BIND and pool_spawn both
; require and leave A16/I16; rs_path_at and rs_next_lane hold the same
; contract.
rs_spawn:
    .a16
    .i16
    ; ---- hazards ----------------------------------------------------------
    lda f:US_SPAWN_T_LONG
    inc a
    cmp #RS_OBS_GAP
    bcc @haz_wait
    lda #0
    sta f:US_SPAWN_T_LONG
    jsr rs_spawn_hazard
    bra @pylon
@haz_wait:
    .a16
    .i16
    sta f:US_SPAWN_T_LONG
@pylon:
    .a16
    .i16
    ; THE PYLON BEAT IS A PHASE, NOT A COUNTER, and that is what makes the
    ; slalom a property instead of a coincidence. The column stands on the
    ; rail's centre, so the distance the ship passes it at is |path| at the
    ; frame it ARRIVES — and with a free-running RS_PYL_GAP counter that phase
    ; is whatever the boot happened to line up. MEASURED after the ground lock
    ; moved RS_LEAD: arrivals landed near a zero crossing and the ship flew
    ; STRAIGHT THROUGH the column on 39 frames of a period.
    ;
    ; Testing the arrival phase directly fires on exactly the same beat —
    ; RS_PATH_HALF frames, one per bend, alternating sides — but always at a
    ; bend EXTREME, so the pass distance is the path's full amplitude every
    ; time and no boot phase can put the pylon on the ship's nose.
    lda f:US_DIST_LONG
    clc
    adc #RS_LEAD                    ; the phase the camera will be at on arrival
    and #(RS_PATH_HALF - 1)
    cmp #RS_PATH_QUARTER
    bne @pyl_wait
    jsr rs_spawn_pylon
@pyl_wait:
    .a16
    .i16
    rts

; --- rs_spawn_hazard: one hazard at the far edge, in the next lane ----------
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. X holds the claimed slot's
; RELATIVE byte offset across the placement, so every field store indexes the
; pool's own base.
rs_spawn_hazard:
    .a16
    .i16
    POOL_BIND ES_RS_ACTORS_LONG + RS_OBS_ALIVE
    ldx #RS_OBS_N
    jsr pool_spawn
    bmi @full                       ; the field is full: skip this beat
    lda #RS_Z_FAR
    sta f:ES_RS_ACTORS_LONG + RS_OBS_Z, x
    lda #RS_TIER_FAR
    sta f:ES_RS_ACTORS_LONG + RS_OBS_TIER, x
    phx
    lda f:US_DIST_LONG
    clc
    adc #RS_LEAD                    ; where the camera will be on arrival
    jsr rs_path_at
    clc
    adc #RS_CENTRE
    sta RSL_T0
    jsr rs_next_lane                ; how far off the nose it will pass
    clc
    adc RSL_T0
    and #RS_WORLD_MASK
    plx
    sta f:ES_RS_ACTORS_LONG + RS_OBS_WX, x
@full:
    .a16
    .i16
    rts

; --- rs_spawn_pylon: the obstacle the bend is bending around ---------------
; ON THE RAIL'S CENTRE COLUMN, and the ship's own swing is what carries it
; past. That is the whole placement: a pylon every RS_PYL_GAP frames — exactly
; one bend — standing on the line the rail would fly if it flew straight, so
; the S-curve alternately takes the ship down the LEFT of one and the RIGHT of
; the next. A pilot reads a slalom, so the player SEES why the ship is
; swinging.
;
; MEASURED, because the first attempt was over-built. Placing it at `centre -
; 2*path(arrival)` — the opposite side at twice the swing — put the column
; entirely off the left edge at closest approach, and the emulator showed an
; empty rail with a pylon in OAM at x = -77. On the centre column the pass
; distance is |path(arrival)|, so the column sweeps from the vanishing point
; out to one side of the ship and off the edge, alternating sides every bend.
;
; The spawn PHASE is what makes that alternation exact rather than lucky, and
; since the ground lock it is tested directly rather than counted to (see
; `rs_spawn`): the beat fires when the ARRIVAL phase is a bend extreme, so
; |path(arrival)| is the full amplitude — 64 world px, 90 screen px at the top
; of the near tier and 214 at the bottom — every single time. Consecutive
; arrivals are half a period apart, so they alternate sides. WIDTH-RISK:
; A16/I16 entry AND exit; no sep/rep.
rs_spawn_pylon:
    .a16
    .i16
    POOL_BIND ES_RS_ACTORS_LONG + RS_PYL_ALIVE
    ldx #RS_PYL_N
    jsr pool_spawn
    bmi @full
    lda #RS_Z_FAR
    sta f:ES_RS_ACTORS_LONG + RS_PYL_Z, x
    lda #RS_TIER_FAR
    sta f:ES_RS_ACTORS_LONG + RS_PYL_TIER, x
    lda #RS_CENTRE
    sta f:ES_RS_ACTORS_LONG + RS_PYL_WX, x
@full:
    .a16
    .i16
    rts

; =============================================================================
; rs_actors_step — one generic depth pass over the pool named in RSL_ABASE
; =============================================================================
; In/out: A16/I16, DB=0. In: RSL_ABASE = the pool's byte offset inside the
; rs_actors claim, RSL_AEND = RSL_ABASE + 2*slots, RSL_T1 = 0 for the hazard
; pool (arrival can hurt) or non-zero for the pylons (it cannot).
;
; ONE LOOP SERVES BOTH POOLS because every pool lays its four fields out at the
; same offsets from its own base — so the cursor carries the base and the field
; constants never change. That is also why the free path has to subtract the
; base again: `pool_kill` wants the offset RELATIVE to the alive[] array it was
; bound to.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. Every label annotated;
; rs_abs16, rs_hurt and rs_actor_free hold the same contract.
rs_actors_step:
    .a16
    .i16
    lda RSL_ABASE
    sta RSL_OFF
@lp:
    .a16
    .i16
    ldx RSL_OFF
    lda f:ES_RS_ACTORS_LONG + RS_F_ALIVE, x
    beq @next
    lda f:ES_RS_ACTORS_LONG + RS_F_Z, x
    sec
    sbc #RS_OBS_STEP
    bcc @arrive                     ; underflowed past 0 — it is at the camera
    cmp #RS_OBS_HIT_Z
    bcc @arrive
    sta f:ES_RS_ACTORS_LONG + RS_F_Z, x
    bra @next
@arrive:
    .a16
    .i16
    lda RSL_T1
    bne @free                       ; a pylon: the rail flew around it
    ; ---- did it reach the SHIP? the ship sits at the camera's own column ---
    ldx RSL_OFF
    lda f:ES_RS_ACTORS_LONG + RS_F_WX, x
    sec
    sbc z:US_CAM_X
    and #RS_WORLD_MASK              ; fold onto the plane's period, so a hazard
    cmp #(RS_WORLD_PX / 2)          ;   across the world seam is not 1,000 px
    bcc :+                          ;   away
    sec
    sbc #RS_WORLD_PX
:   .a16
    .i16
    jsr rs_abs16
    cmp #RS_SHIP_HIT_X
    bcs @free                       ; it passed wide — no harm
    jsr rs_hurt
@free:
    .a16
    .i16
    ldx RSL_OFF
    jsr rs_actor_free
@next:
    .a16
    .i16
    lda RSL_OFF
    clc
    adc #2
    sta RSL_OFF
    cmp RSL_AEND
    bcc @lp
    rts

; --- rs_actor_free: release the slot at absolute byte offset X -------------
; RSL_T1 selects the pool, the same flag the arrival path uses, so there is one
; place that knows which alive[] to bind. WIDTH-RISK: A16/I16 entry AND exit;
; POOL_BIND and pool_kill hold the same.
rs_actor_free:
    .a16
    .i16
    txa
    sec
    sbc RSL_ABASE                   ; pool_kill wants a RELATIVE offset
    tax
    lda RSL_T1
    bne @pyl
    POOL_BIND ES_RS_ACTORS_LONG + RS_OBS_ALIVE
    bra @kill
@pyl:
    .a16
    .i16
    POOL_BIND ES_RS_ACTORS_LONG + RS_PYL_ALIVE
@kill:
    .a16
    .i16
    jsr pool_kill
    rts

; =============================================================================
; rs_hurt — a hazard reached the ship: exactly ONE life segment
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X. At zero the rail freezes for
; RS_FAIL_FRAMES and CLEARS the field, so the fail state is a still, empty rail
; with an empty bar rather than a frozen mess — and then `rs_fail_step`
; re-arms, so the demo loops for a pilot without a game-over flow. WIDTH-RISK:
; A16/I16 entry AND exit; no sep/rep. Every label annotated.
rs_hurt:
    .a16
    .i16
    lda f:US_LIVES_LONG
    beq @done                       ; already out; nothing left to take
    dec a
    sta f:US_LIVES_LONG
    bne @done
    lda #RS_FAIL_FRAMES
    sta f:US_FAIL_T_LONG
    POOL_BIND ES_RS_ACTORS_LONG + RS_OBS_ALIVE
    ldx #RS_OBS_N
    jsr pool_init                   ; clear the field, through the mechanism
    POOL_BIND ES_RS_ACTORS_LONG + RS_PYL_ALIVE
    ldx #RS_PYL_N
    jsr pool_init
    POOL_BIND ES_RS_ACTORS_LONG + RS_BUL_ALIVE
    ldx #RS_BUL_N
    jsr pool_init
@done:
    .a16
    .i16
    rts

; =============================================================================
; rs_fail_step — count the fail state down, then restart the rail
; =============================================================================
; In/out: A16/I16, DB=0. Returns with Z SET while the rail is playable and Z
; CLEAR while it is failing, so the caller's gate is one `beq`. WIDTH-RISK:
; A16/I16 entry AND exit; no sep/rep. Every label annotated.
rs_fail_step:
    .a16
    .i16
    lda f:US_FAIL_T_LONG
    beq @done                       ; playing: Z set
    dec a
    sta f:US_FAIL_T_LONG
    bne @done                       ; still failing: Z clear
    jsr rs_logic_arm                ; the self-restart
    lda #0                          ; ...and it is playable again this frame
@done:
    .a16
    .i16
    rts

; =============================================================================
; rs_bul_move — every tracer recedes toward the horizon; freed at the far edge
; =============================================================================
; In/out: A16/I16, DB=0. A tracer's z INCREASES, faster than the rail closes
; hazards, so it climbs the screen toward the horizon. Reaching the far edge
; frees the slot — the pool's free path, and the one a reuse test drives.
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. POOL_BIND and pool_kill both
; require and leave A16/I16.
rs_bul_move:
    .a16
    .i16
    lda #0
    sta RSL_BUL_OFF
@lp:
    .a16
    .i16
    ldx RSL_BUL_OFF
    lda f:ES_RS_ACTORS_LONG + RS_BUL_ALIVE, x
    beq @next
    lda f:ES_RS_ACTORS_LONG + RS_BUL_Z, x
    clc
    adc #RS_BUL_SPEED
    sta f:ES_RS_ACTORS_LONG + RS_BUL_Z, x
    cmp #(RS_BUL_MAX + 1)
    bcc @next
    POOL_BIND ES_RS_ACTORS_LONG + RS_BUL_ALIVE
    jsr pool_kill                   ; X preserved
@next:
    .a16
    .i16
    lda RSL_BUL_OFF
    clc
    adc #2
    sta RSL_BUL_OFF
    cmp #(2 * RS_BUL_N)
    bcc @lp
    rts

; --- rs_abs16: A = |A|, 16-bit signed. Clobbers A only ----------------------
;
; THE SIGN TEST IS A `cmp`, NOT A `bpl`, AND THAT IS LOAD-BEARING. A `bpl` here
; reads N as the LAST INSTRUCTION left it — which is not necessarily a load of
; A. This routine shipped with `bpl` and the arrival damage test called it
; straight after `cmp #(RS_WORLD_PX / 2)`: on the POSITIVE path that compare is
; the last flag-setter, and for a small positive dx it leaves N set (32 - 512
; is negative), so |32| came back as -32 and every hazard passing to the RIGHT
; of the ship was harmless. Hazards passing to the LEFT hurt correctly, because
; their path ends in `sbc` and N was honest. Measured: dx = +32 arrived,
; predict HIT, actual miss — an asymmetry between the -20 and +20 lanes that no
; amount of reading the arrival code would have explained, because the
; arithmetic there IS right and the flag belonged to somebody else.
;
; This is the same defect family as an `ldx #0` / `bpl` pair that tests the
; wrong register's sign, at a different site. The `cmp #(1 << 15)` form tests A
; and nothing else: carry set == the sign bit is set.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep.
rs_abs16:
    .a16
    .i16
    cmp #(1 << 15)
    bcc @done
    eor #((1 << 16) - 1)
    inc a
@done:
    .a16
    .i16
    rts

; =============================================================================
; rs_tier_step — grow-only size-tier hysteresis over the pool in RSL_ABASE
; =============================================================================
; In/out: A16/I16, DB=0. Same generic cursor contract as rs_actors_step.
;
; An actor's z is monotone DECREASING through its whole approach, so its tier
; only ever GROWS (3 -> 0) and only ever by one step at a time. A tier advances
; when z falls RS_TIER_HYST BELOW the threshold for the bigger frame — the
; margin is what stops an actor sitting on a boundary from flickering between
; two pre-drawn sizes every frame, which is the visible failure the SNES's lack
; of sprite scaling makes possible.
;
; "Grow only" is safe because z never rises for a live actor: the redesign
; FREES an arrived actor and spawns a fresh one at the far edge with its tier
; back at RS_TIER_FAR, so there is no recycle for the hysteresis to chase.
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. Every label annotated.
rs_tier_step:
    .a16
    .i16
    lda RSL_ABASE
    sta RSL_OFF
@lp:
    .a16
    .i16
    ldx RSL_OFF
    lda f:ES_RS_ACTORS_LONG + RS_F_ALIVE, x
    beq @next
    lda f:ES_RS_ACTORS_LONG + RS_F_TIER, x
    beq @next                       ; already the biggest frame
    cmp #3
    beq @from3
    cmp #2
    beq @from2
    ; ---- from tier 1: grow to 0 once z < (T0 - hysteresis) ----------------
    lda f:ES_RS_ACTORS_LONG + RS_F_Z, x
    cmp #(RS_TIER_T0 - RS_TIER_HYST)
    bcs @next
    lda #0
    bra @store
@from2:
    .a16
    .i16
    lda f:ES_RS_ACTORS_LONG + RS_F_Z, x
    cmp #(RS_TIER_T1 - RS_TIER_HYST)
    bcs @next
    lda #1
    bra @store
@from3:
    .a16
    .i16
    lda f:ES_RS_ACTORS_LONG + RS_F_Z, x
    cmp #(RS_TIER_T2 - RS_TIER_HYST)
    bcs @next
    lda #2
@store:
    .a16
    .i16
    sta f:ES_RS_ACTORS_LONG + RS_F_TIER, x
@next:
    .a16
    .i16
    lda RSL_OFF
    clc
    adc #2
    sta RSL_OFF
    cmp RSL_AEND
    bcc @lp
    rts

; =============================================================================
; rs_step_pools — run the depth pass and the hysteresis over BOTH actor pools
; =============================================================================
; In/out: A16/I16, DB=0. The one place that names the two pools, so the generic
; loops above never have to. WIDTH-RISK: A16/I16 entry AND exit; no sep/rep.
rs_step_pools:
    .a16
    .i16
    lda #RS_OBS_BASE
    sta RSL_ABASE
    lda #(RS_OBS_BASE + 2 * RS_OBS_N)
    sta RSL_AEND
    lda #0
    sta RSL_T1                      ; hazards: arriving HURTS
    jsr rs_actors_step
    jsr rs_tier_step
    lda #RS_PYL_BASE
    sta RSL_ABASE
    lda #(RS_PYL_BASE + 2 * RS_PYL_N)
    sta RSL_AEND
    lda #1
    sta RSL_T1                      ; pylons: the rail goes around them
    jsr rs_actors_step
    jsr rs_tier_step
    rts

; =============================================================================
; rs_fire — A (rising edge): a SCREEN-SPACE hitscan, then a tracer for feel
; =============================================================================
; In/out: A16/I16, DB=0. Runs AFTER `rs_cache_build`, because the cache it
; tests against is the same projection the OAM emit is about to draw from.
;
; WHY SCREEN-SPACE AND NOT WORLD-SPACE, and it is the redesign's core fix. A
; fixed world tolerance cannot match a sprite's footprint across depth: 32
; screen px is 44 world px at z=60 and 221 at z=300. Testing the aim point
; against the hazard's own PROJECTED BOX matches what the pilot actually sees
; at every depth, which is what makes hits achievable at all — and the numbers
; tested are the ones about to be written into OAM, so "the crosshair was on
; it" and "it died" cannot disagree.
;
; NEAREST WINS. Two overlapping hazards resolve to the one with the lower z,
; which is the one drawn in front.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. Every label annotated;
; POOL_BIND, pool_spawn and pool_kill hold the same contract.
rs_fire:
    .a16
    .i16
    lda z:ES_INP_PRESS
    bit #RS_JOY_A
    bne :+
    rts
:   .a16
    .i16
    lda #RS_NO_HIT
    sta RSL_BEST
    sta RSL_BESTZ
    lda #0
    sta RSL_OFF                     ; the cache cursor, entry * RSC_STRIDE
@lp:
    .a16
    .i16
    ldx RSL_OFF
    lda f:ES_RS_CACHE_LONG + RSC_VIS, x
    beq @next                       ; culled or dead: nothing on screen to hit
    ; ---- the target's box: 32 px at the two near tiers, 16 at the far two --
    lda f:ES_RS_CACHE_LONG + RSC_TIER, x
    cmp #2
    bcs @small
    lda #(32 + 2 * RS_RET_TOL)
    bra @have_box
@small:
    .a16
    .i16
    lda #(16 + 2 * RS_RET_TOL)
@have_box:
    .a16
    .i16
    sta RSL_T0
    ; ---- is the aim point inside it? unsigned, so a negative delta wraps ---
    lda RSD_RSX
    clc
    adc #RS_RET_TOL
    sec
    sbc f:ES_RS_CACHE_LONG + RSC_SX, x
    cmp RSL_T0
    bcs @next
    lda RSD_RSY
    clc
    adc #RS_RET_TOL
    sec
    sbc f:ES_RS_CACHE_LONG + RSC_SY, x
    cmp RSL_T0
    bcs @next
    ; ---- a hit. keep it only if it is NEARER than the best so far ---------
    lda RSL_OFF
    lsr a
    lsr a                           ; cache offset -> the pool's byte cursor
    tax
    lda f:ES_RS_ACTORS_LONG + RS_OBS_Z, x
    cmp RSL_BESTZ
    bcs @next
    sta RSL_BESTZ
    lda RSL_OFF
    sta RSL_BEST
@next:
    .a16
    .i16
    lda RSL_OFF
    clc
    adc #RSC_STRIDE
    sta RSL_OFF
    cmp #(RSC_STRIDE * RS_OBS_N)    ; hazards only — a pylon is not a target
    bcc @lp
    lda RSL_BEST
    cmp #RS_NO_HIT
    beq @tracer
    jsr rs_kill
@tracer:
    .a16
    .i16
    ; A tracer flies on every press, hit or miss — it is the feel, and it is
    ; what keeps the pool's allocate -> free -> REUSE cycle running.
    POOL_BIND ES_RS_ACTORS_LONG + RS_BUL_ALIVE
    ldx #RS_BUL_N
    jsr pool_spawn
    bmi @done                       ; full: the press is swallowed
    lda f:US_RET_X_LONG             ; up the AIM's lane, not the ship's
    sta f:ES_RS_ACTORS_LONG + RS_BUL_WX, x
    lda #RS_BUL_SPAWN
    sta f:ES_RS_ACTORS_LONG + RS_BUL_Z, x
@done:
    .a16
    .i16
    rts

; =============================================================================
; rs_kill — the hazard in RSL_BEST dies: a flash where it was, and a point
; =============================================================================
; In/out: A16/I16, DB=0.
;
; THE FLASH IS THE WHOLE POINT. The shipped rail's hit test worked and was
; invisible, because a killed hazard was recycled to the horizon and that looks
; exactly like one that flew past. Here the hazard is FREED and a burst is
; pinned at its last projected position for RS_BURST_FRAMES — an event a hazard
; that merely passes never produces. WIDTH-RISK: A16/I16 entry AND exit; no
; sep/rep. Every label annotated.
rs_kill:
    .a16
    .i16
    ldx RSL_BEST
    lda f:ES_RS_CACHE_LONG + RSC_SX, x
    sta f:US_BURST_SX_LONG
    lda f:ES_RS_CACHE_LONG + RSC_SY, x
    sta f:US_BURST_SY_LONG
    ; a 16x16 target needs the 32x32 flash pulled back half a frame to centre
    lda f:ES_RS_CACHE_LONG + RSC_TIER, x
    cmp #2
    bcc @centred
    lda f:US_BURST_SX_LONG
    sec
    sbc #RS_BURST_OFF
    sta f:US_BURST_SX_LONG
    lda f:US_BURST_SY_LONG
    sec
    sbc #RS_BURST_OFF
    sta f:US_BURST_SY_LONG
@centred:
    .a16
    .i16
    lda #RS_BURST_FRAMES
    sta f:US_BURST_T_LONG
    ; ---- the score ---------------------------------------------------------
    lda f:US_SCORE_LONG
    cmp #RS_SCORE_MAX
    bcs @scored
    inc a
    sta f:US_SCORE_LONG
@scored:
    .a16
    .i16
    ; ---- free the slot, through the mechanism -----------------------------
    lda RSL_BEST
    lsr a
    lsr a
    tax
    POOL_BIND ES_RS_ACTORS_LONG + RS_OBS_ALIVE
    jsr pool_kill
    rts

; --- rs_burst_step: the flash counts itself down ---------------------------
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. Every label annotated.
rs_burst_step:
    .a16
    .i16
    lda f:US_BURST_T_LONG
    beq @done
    dec a
    sta f:US_BURST_T_LONG
    cmp #RS_BURST_SWAP
    lda #0
    bcs @store                      ; the first half: frame A
    lda #1
@store:
    .a16
    .i16
    sta f:US_BURST_F_LONG
@done:
    .a16
    .i16
    rts

; =============================================================================
; rs_pool_census — publish every pool's live count for this frame
; =============================================================================
; In/out: A16/I16, DB=0.
;
; TWO COUNTS PER FRAME, PUBLISHED: the live bullet count and the live obstacle
; count. Those are the two observables the pool mechanism actually has — one
; for "fire, travel, hit", one for "spawn, arrive, recycle" — and a test that
; can read both can tell a working pool from a pool that never frees. They
; land in the rail's own declared state (game/railshooter/state.toml).
;
; THE HAZARD COUNT NOW CYCLES. On the shipped rail the field never emptied, so
; that count was always RS_OBS_N and only the tracers exercised the pool's free
; path. The redesign spawns on a schedule and frees on arrival or on a kill, so
; BOTH counts move and both are worth asserting on.
;
; PUBLISH ONLY. Nothing in this rail branches on either word, so the census
; cannot change what is drawn — which is what makes the counts safe to assert
; on: a test reading them is reading the pool's answer, not a variable the game
; steers by.
;
; WHERE IT SITS IN THE FRAME: after `rs_fire`, before `rs_draw`. Both matter.
; After the kills, so a hazard that died this frame is already gone from the
; count; before the draw, so the count and the OAM window a test compares it
; against describe the SAME frame's pool state.
;
; WIDTH-RISK: A16/I16 entry AND exit; no sep/rep. POOL_BIND requires A16 and
; leaves it; `pool_count` holds the same contract on both sides.
rs_pool_census:
    .a16
    .i16
    POOL_BIND ES_RS_ACTORS_LONG + RS_BUL_ALIVE
    ldx #RS_BUL_N
    jsr pool_count
    sta f:US_SHOTS_LIVE_LONG
    POOL_BIND ES_RS_ACTORS_LONG + RS_OBS_ALIVE
    ldx #RS_OBS_N
    jsr pool_count
    sta f:US_HAZARDS_LIVE_LONG
    rts
