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
.segment "BANK6"
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
    jsr rs_path_step            ; the S-curve: the odometer -> the camera's x
    jsr rs_advance              ; the rail walks forward, always
    jsr rs_reticle_move         ; the d-pad -> the world-anchored aim point
    jsr rs_spawn                ; the scheduled hazard / pylon field
    jsr rs_step_pools           ; depth, arrival damage, and the tier hysteresis
    jsr rs_bul_move             ; every tracer recedes; freed at the horizon
    jsr rs_cache_build          ; PASS 1: project every actor and the aim point
    jsr rs_fire                 ; A -> the screen-space hitscan, burst, score
    jsr rs_burst_step           ; the kill flash counts itself down
    jsr rs_pool_census          ; publish every pool's live count
    jsr rs_draw                 ; PASS 2: the whole foreground plus the HUD
    rts

.endscope
