; =============================================================================
; buttons — btnp edge-detection probe
; =============================================================================
; Demonstrates the difference between btn (held) and btnp (newly-pressed this
; frame). Each PRESS of the A button steps the sprite +16 px to the right; an
; A button that is merely held does NOT keep moving it. This exercises the
; per-frame input latch (sf_frame_begin) that btnp reads.
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB")
;   - holding A for many frames advances the sprite exactly ONE 16px step
;     (proving edge-detect, not continuous motion)
;   - releasing and pressing A again advances it one more step
;   (verified via hardware OAM slot-0 X)
;
; Build:  make buttons      (-> build/buttons.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"

.include "sf_core.inc"
.include "sf_video.inc"
.include "sf_sprite.inc"
.include "sf_input.inc"         ; btnp (+ buttons.inc)
.include "sf_frame.inc"

.include "engine_state.inc"

OBJ_CYAN  = $7FE0               ; 15-bit BGR: cyan (G+B)
PLAYER_X  = $32
STEP      = 16

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    sf_obj_color 0, 1, OBJ_CYAN
    sf_load_obj_tile 1, sprite_tile
    jsr init_ppu

    rep #$30
    .a16
    .i16
    lda #40
    sta PLAYER_X

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

    ; btnp: fires only on the frame A transitions to pressed (rising edge).
    btnp #BTN_A
    beq @no_press
    rep #$20
    .a16
    lda PLAYER_X
    clc
    adc #STEP
    sta PLAYER_X
@no_press:

    spr_clear
    spr #1, PLAYER_X, #100, #$00, #2
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
