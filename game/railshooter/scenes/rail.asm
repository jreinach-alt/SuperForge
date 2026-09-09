; =============================================================================
; rail — the railshooter's only scene
; =============================================================================
; The whole rail: a Mode-7 grid under a sky band, an auto-advancing camera, a
; fixed ship that banks with the curve, pooled hazards riding a pinhole 1/z
; projection through four pre-drawn size tiers, pooled bullets receding toward
; the horizon, and a lock-on reticle on the ground.
;
; FOUR OF THE EIGHT HDMA CHANNELS ARE ARMED HERE: split_band's BGMODE + TM and
; mode7_persp's two indirect matrix channels, with oam_sprites time-sharing one
; of those numbers in the VBlank phase. This rail is not a channel-pressure
; case — its pressure is game-side surface.
.scope rail

.include "engine_state_rail.inc"    ; GENERATED — this scene's map

; rail-only engine feature code — INSIDE the scope: its claims are scene-scoped
.include "mode7_persp.asm"
.include "rs_floor.asm"
.include "sky_band.asm"
.include "rs_obj.asm"
.include "rs_logic.asm"

; The camera's world wrap, from rs_floor's DERIVED plane period. Named here
; because it is the composition's statement about which world the driver moves
; in, and asserted against the LUT's far edge so a bigger Z_FAR than the world
; can hold is a build refusal rather than an obstacle spawning behind you.
.assert RS_Z_FAR < RS_WORLD_PX, error, "the projection reaches past the world"

; --- sky_band's blobs: SCENE-scoped claims, so their `.incbin` sites live
; --- inside this scope where the emitted ES_R_SKY_* symbols exist -----------
.segment "BANK1"
sky_map_bin:
    .incbin "sky_map.bin"
.assert ^sky_map_bin = ES_R_SKY_MAP_ROM_BANK, error, "sky_map bank drifted from allocator claim"
.assert .loword(sky_map_bin) = ES_R_SKY_MAP_ROM_ADDR, error, "sky_map addr drifted from allocator claim"
sky_chr_bin:
    .incbin "sky_chr.bin"
.assert ^sky_chr_bin = ES_R_SKY_CHR_ROM_BANK, error, "sky_chr bank drifted from allocator claim"
.assert .loword(sky_chr_bin) = ES_R_SKY_CHR_ROM_ADDR, error, "sky_chr addr drifted from allocator claim"
sky_pal_bin:
    .incbin "sky_pal.bin"
.assert ^sky_pal_bin = ES_R_SKY_PAL_ROM_BANK, error, "sky_pal bank drifted from allocator claim"
.assert .loword(sky_pal_bin) = ES_R_SKY_PAL_ROM_ADDR, error, "sky_pal addr drifted from allocator claim"
.segment "CODE"

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
enter:
    .a16
    .i16
    ; ---- the Mode 7 grid: one DMA, four CGRAM words, M7SEL ----------------
    jsr rs_floor_arm
    ; ---- the scene's seed display registers (split_band's scene_writes) ---
    sep #$20
    .a8
    lda #SB_MODE_BOT
    sta a:$2105                 ; BGMODE 7 (HDMA overrides per line)
    lda #SB_TM_BOT
    sta a:$212C                 ; TM (HDMA overrides per line)
    ; ---- arm the split-band HDMA channels in the scene_mgr shadow ---------
    rep #$10
    .i16
    ldx #(ES_H_BGM_CH * 16)
    lda #ES_H_BGM_DMAP
    sta f:ES_SM_HDMA_LONG+0, x  ; DMAP: direct, 1 byte
    lda #ES_H_BGM_BBAD
    sta f:ES_SM_HDMA_LONG+1, x  ; BBAD: $2105
    lda #^sb_bgmode_tab
    sta f:ES_SM_HDMA_LONG+4, x  ; A1B: table bank
    rep #$20
    .a16
    lda #.loword(sb_bgmode_tab)
    sta f:ES_SM_HDMA_LONG+2, x  ; A1T: table addr
    sep #$20
    .a8
    ldx #(ES_H_TMI_CH * 16)
    lda #ES_H_TMI_DMAP
    sta f:ES_SM_HDMA_LONG+0, x  ; DMAP: indirect, 1 byte
    lda #ES_H_TMI_BBAD
    sta f:ES_SM_HDMA_LONG+1, x  ; BBAD: $212C
    lda #^sb_tm_tab
    sta f:ES_SM_HDMA_LONG+4, x  ; A1B: index-table bank
    sta f:ES_SM_HDMA_LONG+7, x  ; DASB: data bank (same bank)
    rep #$20
    .a16
    lda #.loword(sb_tm_tab)
    sta f:ES_SM_HDMA_LONG+2, x
    ; ---- perspective: index tables + channel shadow + heading 0 -----------
    ; THE ONLY persp_set_pose CALL IN THIS ROM, and the `lda #0` is why "the
    ; plane never rotates" is structural rather than a promise: after this
    ; point no code path can retarget the pose.
    jsr persp_arm
    lda #0
    jsr persp_set_pose
    ; ---- the sky band: BG2 ramp CHR/map/palette + the BG2 register bases --
    jsr sky_arm
    ; ---- the OBJ sheet, the two OBJ palettes, OBSEL, the OAM slots --------
    jsr rs_obj_arm
    ; ---- the rail's own state: camera, odometer, ship, the two pools ------
    ; NOT "heading" — there is no heading state on this rail at all; the
    ; S-curve is a translation of the camera origin.
    stz z:US_TS_ACC             ; the timebase's carried fraction. HERE and not
                                ;   in rs_logic_arm: that routine re-runs on
                                ;   the fail-state self-restart, and this is
                                ;   the CONSOLE's clock rather than the run's
    jsr rs_logic_arm
    ; ---- HDMAEN shadow: four channels (the NMI applies it) ----------------
    sep #$20
    .a8
    lda #((1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH) | (1 << ES_H_M7AB_CH) | (1 << ES_H_M7CD_CH))
    sta z:ES_SM_NMI+2
    rep #$20
    .a16
    rts

exit:
    .a16
    .i16
    jsr rs_obj_disarm           ; re-park every claimed OAM slot
    rts

; --- tick: one frame of the rail --------------------------------------------
; In/out: A16/I16, DB=0.
;
; THE ORDER IS THE RAIL'S SHAPE, and three places in it are load-bearing:
;
;   * the S-curve writes US_CAM_X and every projection reads it, so the driver
;     lands before the cache;
;   * `rs_cache_build` runs BEFORE `rs_fire`, because the hitscan tests the aim
;     point against the SAME projected boxes the emit is about to draw — that
;     is what makes "the crosshair was on it" and "it died" one fact;
;   * the census sits after the kills and before the draw, so the published
;     counts and the OAM window a test compares them against describe the same
;     frame's pool state.
;
; The fail state is a gate at the top, not a mode elsewhere: while it runs the
; rail freezes and only the draw happens, so the empty life bar and the blinking
; ship are on screen for a pilot to read before it restarts itself.
; =============================================================================
; THE RAIL IN TWO REGIONS (engine/features/tick_scale)
; =============================================================================
; THE STATE STEP IS THE UNIT, and here that is not a preference — it is the
; only thing that keeps the GROUND LOCK intact.
;
; railshooter.inc states the lock twice. "ONE ODOMETER DRIVES EVERYTHING":
; US_DIST counts +1 per frame and the path index, every spawn schedule and
; every actor's arrival phase come off it. And "z falls RS_OBS_STEP per frame
; while `dist` rises 1 per frame, so `dist * RS_OBS_STEP + z` is INVARIANT for
; an actor across its whole flight" — which is what makes RS_LEAD a real
; "where will the camera be when this arrives" number. The forward scroll is
; the third expression of the same clock: RS_RAIL_SPEED_88 and RS_OBS_STEP are
; LOCKED to each other (5 z per frame IS 0.5 texture px per frame), and the
; file's own measured note says a 4-against-128 pair reads as an actor/surface
; rate ratio of 0.8 at every row.
;
; Three separate accumulators would let those three drift apart by their
; rounding, and drifting them apart is exactly the defect the lock exists to
; prevent. Stepping the STATE keeps them one clock by construction: the
; odometer, the depth and the scroll advance together or not at all.
;
; So the seven state routines run 1 or 2 times per frame — the count TS_STEP
; publishes for a base of one tick per frame — and the projection and the draw
; run ONCE. On NTSC the count is exactly 1 for ever, so the rail is unchanged
; to the cycle, which is what keeps `make rs-probe`'s calibration case reading
; the same surface and pylon rates it was landed against.
;
; WHAT THE DOUBLED STEP DOES NOT BREAK, checked rather than assumed: the spawn
; schedules fire on the ARRIVAL PHASE of `dist`, and each state step sees a
; DISTINCT dist, so a doubled frame evaluates two phases rather than one phase
; twice — no schedule can double-fire, and none can be skipped either. The
; bank ramp's rate limiter moves one pose per STEP, which is the rate it was
; always meant to be.
;
; NOT SCALED, and stated: rs_fail_step's RS_FAIL_FRAMES countdown. It is the
; dwell on a dead run before the self-restart, outside the play loop and
; outside anything the player is steering — `brawler`'s class B, left alone for
; `brawler`'s reason.
;
; TICK: ok — this block is the region compensator's derivation for this rail;
;   naming the NTSC frame beside the PAL one is its subject rather than a
;   coupling in it, exactly as in tick_scale.asm.
tick:
    .a16
    .i16
    jsr rs_fail_step            ; Z set while playable, clear while failing
    beq @play
    jsr rs_cache_build          ; the field is empty here; the draw still needs
    jsr rs_draw                 ;   a cache to walk, and the HUD still renders
    rts
@play:
    .a16
    .i16
    ; THIS FRAME'S STATE STEPS: 1, or 2. See "THE RAIL IN TWO REGIONS" above.
    ; The seven state routines are inside the loop and the PROJECTION and DRAW
    ; are outside it — the cache is one frame's answer and the screen is drawn
    ; once, whatever the state did to get there.
    TS_STEP z:US_TS_ACC, TS_ONE
    beq rail_project            ; unreachable on either machine, and the loop
                                ;   must not run 65,536 times if that ever
                                ;   stops being true
@again:
    .a16
    .i16
    pha
    jsr rs_path_step            ; the S-curve: the odometer -> the camera's x
    jsr rs_advance              ; the rail walks forward, always
    jsr rs_reticle_move         ; the d-pad -> the world-anchored aim point
    jsr rs_spawn                ; the scheduled hazard / pylon field
    jsr rs_step_pools           ; depth, arrival damage, and the tier hysteresis
    jsr rs_bul_move             ; every tracer recedes; freed at the horizon
    jsr rs_burst_step           ; the kill flash counts itself down
    pla
    dec a
    bne @again
rail_project:
    .a16
    .i16
    jsr rs_cache_build          ; PASS 1: project every actor and the aim point
    jsr rs_shot_cue             ; the SHOT, on the same edge rs_fire gates on
    jsr rs_fire                 ; A -> the screen-space hitscan, burst, score
    jsr rs_kill_cue             ; ...and the KILL, on the score it just moved
    jsr rs_pool_census          ; publish every pool's live count
    jsr rs_draw                 ; PASS 2: the whole foreground plus the HUD
    rts

; --- rs_sfx: queue the sound effect named in A ------------------------------
; In: A16 = the SFX:: id (low byte). In/out: A16/I16, DB=0. Clobbers A.
;
; WIDTH-RISK: sf_sfx_queue_c declares `entry: A8 I16 DB=0` and this rail calls
; it from A16 code, so the sep/rep pair is load-bearing and lives here rather
; than at each call site. X survives it, which is why this uses the centred
; entry point rather than loading a pan into X.
rs_sfx:
    .a16
    .i16
    sep #$20
    .a8
    jsr sf_sfx_queue_c
    rep #$20
    .a16
    rts

; --- rs_shot_cue: the trigger, and it needs no latch of its own -------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; ES_INP_PRESS IS ALREADY AN EDGE — the `input` feature publishes the rising
; edge, not the held state — so testing it here is one-shot by construction,
; the same way `jumper`'s take-off is. It is also the EXACT condition `rs_fire`
; bails on two instructions later, which is why this sits immediately above it:
; the cue and the shot read one word on one frame and cannot disagree about
; whether a trigger was pulled.
;
; THIS IS NOT A FEATURE EDIT, and it is not the platformer_stream boundary
; either. ES_INP_PRESS is `input`'s published output that every rail already
; reads for its own controls; nothing is being lifted out of `rs_logic`.
rs_shot_cue:
    .a16
    .i16
    lda z:ES_INP_PRESS
    bit #RS_JOY_A
    beq @none
    lda #SFX::laser
    jsr rs_sfx
@none:
    .a16
    .i16
    rts

; --- rs_kill_cue: the score's CHANGE, which is one kill ---------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; `score` is declared in this rail's own state.toml and `rs_logic` fills it —
; the feature owns the hitscan, the game owns the counter and what it sounds
; like — so, as on `microzero`'s lap, the cue costs the feature nothing.
;
; THE SCORE IS A LEVEL and the kill is its change. A cue on the value would
; sound on every frame from the first kill onward. One extra reason to latch
; rather than hook the hitscan: `rs_fire` resolves NEAREST WINS across the
; whole cache, so one trigger pull scores at most one kill and the counter's
; step is exactly the event. `rs_fail_step` re-arms the demo by resetting the
; score, and a DECREASE is not a kill, which is why this tests for equality
; and not for "moved".
rs_kill_cue:
    .a16
    .i16
    ; `score` is declared "u16" and not "u16@dp", so the allocator places it in
    ; WRAM rather than the direct page and the LONG form is the addressing this
    ; takes: `rs_logic` reaches the same word as `f:US_SCORE_LONG` and this
    ; must agree with it. A `z:` here is not a slower read, it is a read of a
    ; different byte -- ca65 refuses it outright, which is the gate working.
    lda f:US_SCORE_LONG
    cmp f:US_SCOREPREV_LONG
    beq @same                   ; nothing died this frame
    sta f:US_SCOREPREV_LONG
    bcc @same                   ; the re-arm reset it: a fall is not a kill
    lda #SFX::explosion         ; declared `both` -- which means it may take
    jsr rs_sfx                  ;   EITHER sfx channel, so it can OVERLAP the
                                ;   laser queued above rather than replace it
                                ;   (assets/audio/sound-effects.txt, "FLAGS").
                                ;   The ring still hands over one id per frame,
                                ;   so the second of the two arrives on the
                                ;   next frame and the pair reads as one event.
@same:
    .a16
    .i16
    rts

.endscope
