; =============================================================================
; hud_game — a sprite you move with a live text HUD (score counter)
; =============================================================================
; A red player you move with the d-pad, with a white "SCORE 00000" HUD line on
; the BG3 text layer. Pressing A bumps the score; the counter reprints only
; when the value changes (the cheap HUD pattern — 5 tiles + one tilemap DMA,
; not a per-frame reprint). Demonstrates the text surface (sf_text.inc)
; composed with sprites + input. Adapt it: print lives/level labels, bump the
; score from a collision (col_box) instead of a button.
;
; State (DP): player screen pos $32/$34, score $36.
; Debug: SCORE mirrored to $7E:E010 whenever it changes.
;
; Done-condition (emulator-verifiable):
;   - boots; red sprite + white "SCORE 00000" visible
;   - d-pad moves the sprite (OAM + pixels move; HUD text stays put)
;   - pressing A: SCORE increments once per press (debug $E010), the printed
;     counter updates (VRAM BG3 tilemap digit tiles change)
;
; Build:  make hud_game      (-> build/hud_game.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode
.include "sf_text.inc"          ; sf_text_init, print, sf_print_u16
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn, btnp (+ buttons.inc)
.include "sf_camera.inc"        ; sf_clamp0
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

OBJ_RED = $001F
PX      = $32                   ; player screen position
PY      = $34
SCORE   = $36
SPEED   = 2

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init

    ; uploads under the coldstart forced blank (before screen-on)
    sf_load_obj_tile 1, sprite_tile
    sf_obj_color 0, 1, OBJ_RED
    sf_text_init                ; font + white text colour

    jsr init_ppu
    gfxmode #1                  ; (zeros the shadow tilemaps)

    ; --- HUD: label once, counter at its start value (after gfxmode) ---
    rep #$30
    .a16
    .i16
    stz SCORE
    print str_score, #8, #8     ; "SCORE" at tiles (1..5, 1)
    sf_print_u16 SCORE, #56, #8 ; "00000" at tiles (7..11, 1)

    ; player starts at screen centre
    lda #124
    sta PX
    lda #108
    sta PY

    spr_clear
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMI + auto-joypad on
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin

    ; --- move the player (screen space) ---
    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda PX
    clc
    adc #SPEED
    sta PX
@no_right:
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda PX
    sec
    sbc #SPEED
    sta PX
@no_left:
    btn #BTN_DOWN
    beq @no_down
    rep #$20
    .a16
    lda PY
    clc
    adc #SPEED
    sta PY
@no_down:
    btn #BTN_UP
    beq @no_up
    rep #$20
    .a16
    lda PY
    sec
    sbc #SPEED
    sta PY
@no_up:

    ; keep the 8px sprite on screen
    sf_clamp0 PX, (256 - 8)
    sf_clamp0 PY, (224 - 8)

    ; --- A press: bump the score, reprint the counter (only on change) ---
    btnp #BTN_A
    beq @no_score
    rep #$20
    .a16
    lda SCORE
    inc a
    sta SCORE
    ldx #$0000
    sta f:$7E0000 + $E010, x    ; mirror for the test
    sf_print_u16 SCORE, #56, #8 ; reprint the 5 digits (NMI commits next frame)
@no_score:

    spr_clear
    spr #1, PX, PY, #$00, #2
    sf_frame_end
    jmp game_loop

str_score:
    .byte "SCORE", 0

; one solid 8x8 4bpp tile (all colour index 1)
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
.include "text_engine.asm"
.include "sf_text_data.inc"
