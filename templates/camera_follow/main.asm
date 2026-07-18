; =============================================================================
; camera_follow — move a player through a large world; the camera tracks it
; =============================================================================
; A red player you move with the d-pad through a 512x448 world over a tiled
; background. The camera centres the player and scrolls the BG to follow, but
; clamps at the world edges so the view never runs off the world — there, the
; player walks toward the screen edge instead. Demonstrates the camera-follow
; primitive (sf_camera_follow) composing sprites + scrolling. Adapt it: change
; the world size, clamp the player to the world, add a real level.
;
; State (DP): player world pos $32/$34, camera $36/$38, sprite screen $3A/$3C.
;
; Done-condition (emulator-verifiable):
;   - boots; BG + red sprite visible
;   - mid-world: as the player moves, the camera tracks (BG scrolls) and the
;     sprite stays centred on screen (~128)
;   - at the world edge: the camera clamps (stops scrolling) and the sprite
;     moves toward the screen edge
;
; Build:  make camera_follow      (-> build/camera_follow.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, mset, sf_load_bg_tile, sf_bg_color
.include "sf_camera.inc"        ; sf_camera_follow (+ scroll)
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

OBJ_RED  = $001F
BG_GREEN = $03E0
WORLD_W  = 512
WORLD_H  = 448
PWX      = $32                  ; player world position
PWY      = $34
CAM_X    = $36                  ; camera (clamped)
CAM_Y    = $38
SCRX     = $3A                  ; sprite screen position
SCRY     = $3C
BG_MX    = $46                  ; tilemap fill scratch
BG_MY    = $48
BG_TILE  = $4A
SPEED    = 2

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    sf_load_bg_tile 1, bg_tile
    sf_bg_color 0, 1, BG_GREEN
    sf_load_obj_tile 1, sprite_tile
    sf_obj_color 0, 1, OBJ_RED

    jsr init_ppu
    gfxmode #1

    ; checkerboard BG (repeats every 256 px as the world scrolls)
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda BG_MX
    eor BG_MY
    and #$0001
    sta BG_TILE
    mset #1, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #32
    bne @row

    ; player starts at the world centre
    lda #256
    sta PWX
    lda #224
    sta PWY

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    ; --- move the player through the world ---
    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda PWX
    clc
    adc #SPEED
    sta PWX
@no_right:
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda PWX
    sec
    sbc #SPEED
    sta PWX
@no_left:
    btn #BTN_DOWN
    beq @no_down
    rep #$20
    .a16
    lda PWY
    clc
    adc #SPEED
    sta PWY
@no_down:
    btn #BTN_UP
    beq @no_up
    rep #$20
    .a16
    lda PWY
    sec
    sbc #SPEED
    sta PWY
@no_up:

    ; --- keep the player inside the world (8px sprite) ---
    sf_clamp0 PWX, (WORLD_W - 8)
    sf_clamp0 PWY, (WORLD_H - 8)

    ; --- camera tracks the player (clamped) and scrolls BG1 ---
    sf_camera_follow PWX, PWY, WORLD_W, WORLD_H, CAM_X, CAM_Y

    ; --- sprite screen position = world - camera ---
    rep #$20
    .a16
    lda PWX
    sec
    sbc CAM_X
    sta SCRX
    lda PWY
    sec
    sbc CAM_Y
    sta SCRY

    spr_clear
    spr #1, SCRX, SCRY, #$00, #2
    sf_frame_end
    jmp game_loop

bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
sprite_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
