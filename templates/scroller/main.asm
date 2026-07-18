; =============================================================================
; scroller — a scrolling tilemap background with a sprite on top
; =============================================================================
; A green checkerboard BG1 you scroll with the d-pad (the world moves under a
; fixed red sprite). Demonstrates the BG pipeline (gfxmode + mset + scroll) and
; sprite-over-BG compositing from the macro library. Adapt it: change the
; tilemap, make the sprite move and the camera follow, add a second layer.
;
; State (DP): cam $32/$34 (BG scroll). The sprite is fixed at screen centre.
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB")
;   - the BG renders a green checkerboard AND a red sprite is visible on top
;   - each d-pad direction scrolls the BG the right way (SHADOW_BG1HOFS/VOFS
;     and the on-screen pattern), while the sprite holds its screen position
;
; Build:  make scroller      (-> build/scroller.sfc)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, scroll, mset, sf_load_bg_tile, sf_bg_color
.include "sf_video.inc"         ; sf_obj_color, sf_load_obj_tile
.include "sf_sprite.inc"        ; spr, spr_clear
.include "sf_input.inc"         ; btn (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin, sf_frame_end
.include "engine_state.inc"

OBJ_RED  = $001F
BG_GREEN = $03E0
CAM_X    = $32
CAM_Y    = $34
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
    sf_coldstart                ; forced blank; clears CGRAM/VRAM
    sf_engine_init

    ; uploads under the forced blank (before init_ppu/gfxmode turn the screen on)
    sf_load_bg_tile 1, bg_tile      ; BG1 CHR tile 1 = solid colour index 1
    sf_bg_color 0, 1, BG_GREEN      ; BG palette 0, slot 1 = green
    sf_load_obj_tile 1, sprite_tile ; OBJ tile 1
    sf_obj_color 0, 1, OBJ_RED      ; OBJ palette 0, slot 1 = red

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- build a checkerboard tilemap: tile = (mx ^ my) & 1 ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda BG_MX
    eor BG_MY
    and #$0001                  ; checkerboard 0/1
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

    stz CAM_X
    stz CAM_Y
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

    ; --- scroll the world with the d-pad ---
    btn #BTN_RIGHT
    beq @no_right
    rep #$20
    .a16
    lda CAM_X
    clc
    adc #SPEED
    sta CAM_X
@no_right:
    btn #BTN_LEFT
    beq @no_left
    rep #$20
    .a16
    lda CAM_X
    sec
    sbc #SPEED
    sta CAM_X
@no_left:
    btn #BTN_DOWN
    beq @no_down
    rep #$20
    .a16
    lda CAM_Y
    clc
    adc #SPEED
    sta CAM_Y
@no_down:
    btn #BTN_UP
    beq @no_up
    rep #$20
    .a16
    lda CAM_Y
    sec
    sbc #SPEED
    sta CAM_Y
@no_up:

    scroll #1, CAM_X, CAM_Y     ; apply the camera to BG1

    ; --- draw the fixed sprite on top of the scrolling world ---
    spr_clear
    spr #1, #120, #100, #$00, #2
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
