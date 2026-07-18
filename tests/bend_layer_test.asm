; =============================================================================
; bend_layer_test — run-gate for E-LAYER: sf_tunnel arms the bend on BG2
; =============================================================================
; Enhancement v1.1 (E-LAYER): the bend layer is selectable (BG1/2/3). This ROM
; puts the vertical-stripe reference feature on BG2 (CHR word $4000, tilemap
; word $5C00 per bg_engine.asm Mode-1 layout) and arms the ANIMATED sine tunnel
; on BG2 via the new layer arg:  sf_tunnel #SF_CURVE_SINE, #amp, #speed, #2.
; BG1 is left blank (tile 0), so any per-scanline horizontal displacement that
; the test reads from rendered pixels can ONLY come from the BG2 bend — proving
; the engine drives BG2HOFS ($210F), not BG1HOFS, when HDMA_BEND_LAYER = 2.
;
; Done-condition (read from RENDERED PIXELS):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = allocated HDMA channel (3..7)
;   - $7E:E010 = frame heartbeat (advances)
;   - BG2's vertical stripe edge x VARIES per scanline along the sine curve
;   - the pattern ADVANCES between frames (the roll) — same proof as bend_test,
;     but on BG2.
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, scroll, mset, sf_bg_color
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_fx.inc"            ; sf_tunnel / sf_bend_tick
.include "engine_state.inc"

BG_GREEN  = $03E0               ; 15-bit BGR green stripe colour
BG_MX     = $46                 ; tilemap fill loop scratch (DP, game area)
BG_MY     = $48
BG_TILE   = $4A

BEND_AMP   = 14                 ; peak displacement (px); amp 14 ≈ 13-14px
BEND_SPEED = 2                  ; phase roll per frame (the tunnel advance)
BEND_LAYER = 2                  ; the layer under test (BG2)

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; --- upload the stripe tile to BG2 CHR ($4000 word) under forced blank ---
    ; (sf_load_bg_tile only targets BG1 CHR $2000; BG2 CHR base is word $4000
    ;  in the engine's Mode-1 layout — see engine/bg_engine.asm BG12NBA=$42.)
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word, increment after high byte
    rep #$30
    .a16
    .i16
    lda #($4000 + 1*16)         ; BG2 CHR base + tile 1 * 16 words
    sta $2116                   ; VMADD
    ldx #$0000
@chr:
    lda f:bg_tile, x
    sta $2118
    inx
    inx
    cpx #$0020
    bne @chr

    sf_bg_color 0, 1, BG_GREEN  ; BG palette 0, slot 1 = green

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; Mode 1: BG1 + BG2 (zeros the shadow tilemaps)

    ; --- BG2 wide vertical stripes (BG1 left blank → tile 0) ---
    rep #$30
    .a16
    .i16
    stz BG_MY
@row:
    stz BG_MX
@col:
    lda BG_MX
    lsr
    lsr
    and #$0001                  ; 4 tiles on / 4 tiles off → 64px stripe period
    sta BG_TILE
    mset #BEND_LAYER, BG_MX, BG_MY, BG_TILE
    lda BG_MX
    inc a
    sta BG_MX
    cmp #32
    bne @col
    lda BG_MY
    inc a
    sta BG_MY
    cmp #24
    bne @row

    ; --- both layers at world-zero scroll; the bend is the only motion ---
    scroll #1, #0, #0
    scroll #BEND_LAYER, #0, #0

    ; --- arm the ANIMATED sine tunnel on BG2 (the layer-selectable arm) ---
    sf_tunnel #SF_CURVE_SINE, #BEND_AMP, #BEND_SPEED, #BEND_LAYER
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; record the allocated channel for the test

    sf_debug_magic

    sep #$20
    .a8
    lda $4210                   ; ack pending NMI (read-clear)
@wait_vblank_end:
    lda $4212                   ; HVBJOY
    bmi @wait_vblank_end        ; bit 7 = 1 → still in VBlank
    lda #$81
    sta $4200
    rep #$30
    .a16
    .i16

game_loop:
    sf_frame_begin              ; wait for NMI; latch input

    sf_bend_tick                ; roll the curve phase + rebuild the table

    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    jmp game_loop

; one solid 8x8 4bpp tile (all colour index 1) — same as bend_test
bg_tile:
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $FF,$00, $FF,$00, $FF,$00, $FF,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00
    .byte $00,$00, $00,$00, $00,$00, $00,$00

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
