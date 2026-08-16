; =============================================================================
; scenes/world.asm — the whole game: move the player, follow + clamp, subtract
; =============================================================================
; The whole game loop: four button tests moving the PLAYER through the world,
; a world clamp, the follow camera, and the subtraction that turns a world
; position into a screen position.
;
; TWO SPACES, THREE OWNERS — the rail's lesson made structural:
;   - the PLAYER lives in WORLD coordinates (US_PWX/US_PWY, this scene's
;     state), bounded by the world clamp;
;   - the CAMERA is cf_bg's `cf_cam` dp claim, recomputed HERE every tick as
;     clamp(player - half-screen, 0, world - screen) and committed to the PPU
;     by that feature's NMI hook (the scroller_bg/pfs_bg division: the scene
;     writes, the owning feature's VBlank commit reads);
;   - the SPRITE is drawn at SCREEN coordinates (US_SCRX/US_SCRY), derived
;     here as world - camera and consumed by cf_obj_place, which never sees a
;     world coordinate.
;
; The clamp interplay is what the rail exists to show: mid-world the camera
; tracks and the subtraction is CONSTANT (the sprite holds screen-centre while
; the BG slides); at a world edge the camera pins and the subtraction WALKS
; (the BG holds while the sprite moves to the screen edge). Both regimes fall
; out of the same three steps below — there is no branch that "decides" which
; one is on screen.

.scope world

; --- enter ----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr cf_arm                      ; CHR, palette, the built map, cam zeroed
    jsr cf_obj_arm                  ; OBJ CHR, palette, OBSEL, tile + attr
    ; ---- the player boots at the world centre ----------------------------
    lda #CF_BOOT_X
    sta z:US_PWX
    lda #CF_BOOT_Y
    sta z:US_PWY
    stz z:US_FRAMES
    ; ---- run the follow + subtraction ONCE, then stage the sprite, so the
    ; first committed frame is the real picture: camera (128, 112), sprite at
    ; screen (128, 112) — not cf_arm's zeroed camera and a parked sprite.
    ; scene_mgr holds NMI masked across enter, so the first VBlank that can
    ; publish any of this is the first one after these lines ran.
    jsr follow_camera
    jsr derive_screen
    jsr cf_obj_place
    ; ---- the scene's base display ----------------------------------------
    ; BGMODE, TM, BG1SC and BG12NBA are the `scene_writes` this scene owns on
    ; cf_bg's behalf (see that feature.toml's attribution note). Every value
    ; comes from the allocator's emitted encoding; none is narrated from a
    ; VRAM address here.
    sep #$20
    .a8
    lda #1                          ; BGMODE 1: BG1/BG2 4bpp, BG3 2bpp
    sta a:$2105
    lda #ES_V_CF_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_CF_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 chr page in the low nibble
    lda #((1 << 4) | 1)             ; TM: OBJ + BG1 on the main screen
    sta a:$212C
    rep #$20
    .a16
    rts

; --- tick -----------------------------------------------------------------
; In/out: A16/I16, DB=0. Called once per frame by sm_tick. Clobbers A.
;
; The order is fixed: move, clamp, follow, subtract, draw.
tick:
    .a16
    .i16
    inc z:US_FRAMES
    jsr move_player
    jsr clamp_player
    jsr follow_camera
    jsr derive_screen
    jsr cf_obj_place                ; re-staged every frame — see cf_obj.asm
    rts

; --- move_player: the d-pad moves the player through the WORLD --------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; LEVEL-TRIGGERED, not edge: the pad is held to walk, so this reads
; ES_INP_CUR and never ES_INP_PRESS. Opposite directions are both applied
; rather than being made exclusive — holding Left+Right nets to zero because
; the two deltas cancel, not because a branch
; picked one. (Identical shape to scroller's scroll_from_pad; the ONE
; difference is what the words mean: this moves the PLAYER, and the camera is
; derived from it afterwards, where scroller's pad moved the camera itself.)
move_player:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:US_PWX
    clc
    adc #CF_SPEED
    sta z:US_PWX
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:US_PWX
    sec
    sbc #CF_SPEED
    sta z:US_PWX
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_DOWN
    beq @no_down
    lda z:US_PWY
    clc
    adc #CF_SPEED
    sta z:US_PWY
@no_down:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @no_up
    lda z:US_PWY
    sec
    sbc #CF_SPEED
    sta z:US_PWY
@no_up:
    .a16
    .i16
    rts

; --- clamp_player: keep the player inside the WORLD -------------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; Per axis: SIGNED-AWARE low bound — a value that moved below 0 wrapped to a
; high u16 (bit 15 set), so `bpl` distinguishes "went negative" from "large",
; and the clamp-to-0 arm catches the wrap rather than letting it read as a
; huge coordinate. High bound is world - 8: the 8x8 player's top-left may not
; pass the world's last sprite-sized cell.
clamp_player:
    .a16
    .i16
    lda z:US_PWX
    bpl @x_chk_hi                   ; bit15 clear -> non-negative, check high
    lda #0                          ; wrapped below 0 -> clamp to 0
    bra @x_done
@x_chk_hi:
    .a16
    .i16
    cmp #CF_PLAYER_MAX_X + 1
    bcc @x_done                     ; <= max -> keep
    lda #CF_PLAYER_MAX_X            ; > max -> clamp to max
@x_done:
    .a16
    .i16
    sta z:US_PWX
    lda z:US_PWY
    bpl @y_chk_hi
    lda #0
    bra @y_done
@y_chk_hi:
    .a16
    .i16
    cmp #CF_PLAYER_MAX_Y + 1
    bcc @y_done
    lda #CF_PLAYER_MAX_Y
@y_done:
    .a16
    .i16
    sta z:US_PWY
    rts

; --- follow_camera: cam = clamp(player - half-screen, 0, world - screen) ----
; In/out: A16/I16, DB=0. Clobbers A.
;
; The camera CENTRES the player
; (player - half-screen), clamped to [0, world - screen] so the view never
; runs off the world. The subtraction can go negative (player near the world's
; top-left) — as u16 that sets bit 15, so `bpl` catches it exactly as in
; clamp_player. THE CAMERA IS A PURE FUNCTION OF THE PLAYER: no camera state
; survives a tick, which is why walking back from a clamped edge re-tracks
; without any unclamp logic.
follow_camera:
    .a16
    .i16
    lda z:US_PWX
    sec
    sbc #CF_HALF_W
    bpl @x_chk_hi                   ; >= 0 -> check the high clamp
    lda #0                          ; player left of centre-range -> pin at 0
    bra @x_done
@x_chk_hi:
    .a16
    .i16
    cmp #CF_CAM_MAX_X + 1
    bcc @x_done                     ; <= max -> keep (TRACKING regime)
    lda #CF_CAM_MAX_X               ; > max -> pin at the far edge (CLAMPED)
@x_done:
    .a16
    .i16
    sta z:ES_CF_CAM + 0
    lda z:US_PWY
    sec
    sbc #CF_HALF_H
    bpl @y_chk_hi
    lda #0
    bra @y_done
@y_chk_hi:
    .a16
    .i16
    cmp #CF_CAM_MAX_Y + 1
    bcc @y_done
    lda #CF_CAM_MAX_Y
@y_done:
    .a16
    .i16
    sta z:ES_CF_CAM + 2
    rts

; --- derive_screen: sprite screen position = world - camera -----------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; The whole trick behind a scrolling actor, and deliberately TWO bare
; subtractions with no clamp of their own: once
; clamp_player and follow_camera have run, scrx is in [0, 248] and scry in
; [0, 216] by construction — mid-world the camera cancels the player's motion
; (constant 128/112), at an edge the pinned camera lets the difference walk.
derive_screen:
    .a16
    .i16
    lda z:US_PWX
    sec
    sbc z:ES_CF_CAM + 0
    sta z:US_SCRX
    lda z:US_PWY
    sec
    sbc z:ES_CF_CAM + 2
    sta z:US_SCRY
    rts

; --- exit -----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. There is nowhere to go —
; this rail has one scene and no edges — so the handler exists to satisfy
; scene_mgr's table and re-parks what this scene armed, which is the exit
; contract every rail's scene owes whether or not it is ever reached.
exit:
    .a16
    .i16
    jsr oam_park_all
    rts

.endscope
