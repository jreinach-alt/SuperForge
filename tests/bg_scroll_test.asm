; =============================================================================
; bg_scroll_test — run-gate for the BG macros (render + scroll)
; =============================================================================
; Sets up a BG1 tilemap of vertical green stripes and scrolls it horizontally.
; Proves: gfxmode enables BG1, sf_load_bg_tile/sf_bg_color upload BG content,
; mset builds the tilemap, and scroll (committed by the NMI) moves it.
;
; Done-condition (emulator-verifiable):
;   - boots ($7E:E000 == "SFDB")
;   - VRAM tilemap @ word $5800 holds the stripe pattern (alt tile 0 / tile 1)
;   - the screen shows green stripes (non-zero green pixels)
;   - the stripes scroll: SCRL_X ($E010) advances and the screenshot shifts
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, scroll, mset, sf_load_bg_tile, sf_bg_color
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "engine_state.inc"

BG_GREEN = $03E0                ; 15-bit BGR green
BG_MX    = $46                  ; tilemap fill loop scratch (DP)
BG_MY    = $48
BG_TILE  = $4A
SCRL_X   = $4C

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears CGRAM/VRAM (no garbage)
    sf_engine_init

    ; uploads under the coldstart forced blank (before screen-on)
    sf_load_bg_tile 1, bg_tile  ; BG1 CHR: tile 1 = solid colour index 1
    sf_bg_color 0, 1, BG_GREEN  ; BG palette 0, slot 1 = green

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- build a vertical-stripe tilemap: odd columns = tile 1 (green) ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda BG_MX
    and #$0001                  ; tile = mx & 1  (0 or 1) -> stripes
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
    cmp #28
    bne @row

    sf_debug_magic

    ; enable NMI + auto-joypad
    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

    stz SCRL_X
game_loop:
    sf_frame_begin              ; wait for NMI (commits scroll, DMAs the tilemap)
    lda SCRL_X
    inc a
    sta SCRL_X
    scroll #1, SCRL_X, #0       ; advance BG1 horizontal scroll
    ldx #$0000
    lda SCRL_X
    sta f:$7E0000 + $E010, x    ; record scroll for the test
    jmp game_loop

; one solid 8x8 4bpp tile (all colour index 1)
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
