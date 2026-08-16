; =============================================================================
; scenes/world.asm — the whole game: read the d-pad, move the camera
; =============================================================================
; The whole of the gameplay is eleven instructions: four button tests, each
; adding or subtracting SCR_SPEED from one camera word, then a scroll and a
; sprite.
;
; THE CAMERA IS scroller_bg's DP CLAIM, not this scene's state, because the
; routine that READS it is that feature's VBlank commit (pfs_bg's division,
; unchanged). This scene WRITES it, which is the same shape split_v_fight's
; director has with `ES_SV_SPREAD` / `ES_SV_MID`.
;
; NO CLAMP, deliberately. The camera is bounded nowhere at all, and a 32x32 map
; on a 10-bit scroll latch wraps every 256 px on both axes — so scrolling
; forever is a torus, not a wall. That is a real property of the rail and the
; test drives past the wrap in both directions rather than stopping at the
; first screenful.

.scope world

; --- enter ----------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr scr_arm                     ; CHR, palette, the built map, the camera
    jsr scr_obj_arm                 ; OBJ CHR, palette, OBSEL, tile + attr
    jsr scr_obj_draw                ; stage the rider BEFORE the first NMI, so
                                    ; frame 0 commits a real entry rather than
                                    ; whatever oam_park_all left
    stz z:US_FRAMES
    ; ---- the scene's base display ----------------------------------------
    ; BGMODE, TM, BG1SC and BG12NBA are the `scene_writes` this scene owns on
    ; scroller_bg's behalf (see that feature.toml's attribution note). Every
    ; value comes from the allocator's emitted encoding; none is narrated from
    ; a VRAM address here.
    sep #$20
    .a8
    lda #1                          ; BGMODE 1: BG1/BG2 4bpp, BG3 2bpp
    sta a:$2105
    lda #ES_V_SCR_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_SCR_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 chr page in the low nibble
    lda #((1 << 4) | 1)             ; TM: OBJ + BG1 on the main screen
    sta a:$212C
    rep #$20
    .a16
    rts

; --- tick -----------------------------------------------------------------
; In/out: A16/I16, DB=0. Called once per frame by sm_tick. Clobbers A.
tick:
    .a16
    .i16
    inc z:US_FRAMES
    jsr scroll_from_pad
    jsr scr_obj_draw                ; re-staged every frame — see that routine
    rts

; --- scroll_from_pad: the d-pad moves the world ----------------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; LEVEL-TRIGGERED, not edge: the pad is held to scroll, so this reads
; ES_INP_CUR and never ES_INP_PRESS. Opposite directions are both applied
; rather than being made exclusive — holding Left+Right nets to zero because
; the two deltas cancel, not because a branch picked one.
scroll_from_pad:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_RIGHT
    beq @no_right
    lda z:ES_SCR_CAM + 0
    clc
    adc #SCR_SPEED
    sta z:ES_SCR_CAM + 0
@no_right:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_LEFT
    beq @no_left
    lda z:ES_SCR_CAM + 0
    sec
    sbc #SCR_SPEED
    sta z:ES_SCR_CAM + 0
@no_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_DOWN
    beq @no_down
    lda z:ES_SCR_CAM + 2
    clc
    adc #SCR_SPEED
    sta z:ES_SCR_CAM + 2
@no_down:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @no_up
    lda z:ES_SCR_CAM + 2
    sec
    sbc #SCR_SPEED
    sta z:ES_SCR_CAM + 2
@no_up:
    .a16
    .i16
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
