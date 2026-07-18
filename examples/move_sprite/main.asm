; =============================================================================
; move_sprite — a visible sprite you drive with the d-pad
; =============================================================================
; The headline scenario: a red 8x8 sprite that moves with the controller, on
; screen, written entirely in macros. Combines the visible-sprite setup
; (sf_video) with the read-input/update/draw frame loop (btn + sf_frame_*).
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB")
;   - with no input, the red sprite holds position
;   - injecting Right moves the red blob right; Left left; Down down; Up up
;     (verified by the red-pixel centroid in successive screenshots, and by
;      hardware OAM slot-0 X/Y)
;
; Build:  make move_sprite      (-> build/move_sprite.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"

.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end

.include "engine_state.inc"

OBJ_RED      = $001F
PLAYER_X     = $32              ; DP game state (main-thread DP=$0000)
PLAYER_Y     = $34
PLAYER_SPEED = 2

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    sf_obj_color 0, 1, OBJ_RED
    sf_load_obj_tile 1, sprite_tile
    jsr init_ppu

    rep #$30
    .a16
    .i16
    lda #120
    sta PLAYER_X
    lda #100
    sta PLAYER_Y

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda PLAYER_X
    clc
    adc #PLAYER_SPEED
    sta PLAYER_X
@no_right:
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda PLAYER_X
    sec
    sbc #PLAYER_SPEED
    sta PLAYER_X
@no_left:
    btn #BTN_DOWN
    beq @no_down
    rep #$20
    .a16
    lda PLAYER_Y
    clc
    adc #PLAYER_SPEED
    sta PLAYER_Y
@no_down:
    btn #BTN_UP
    beq @no_up
    rep #$20
    .a16
    lda PLAYER_Y
    sec
    sbc #PLAYER_SPEED
    sta PLAYER_Y
@no_up:

    spr_clear
    spr #1, PLAYER_X, PLAYER_Y, #$00, #2
    sf_frame_end
    jmp game_loop

sprite_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
