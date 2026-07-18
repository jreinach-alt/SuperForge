; =============================================================================
; bend_test — run-gate for sf_bend / sf_tunnel (per-scanline BGnHOFS curve)
; =============================================================================
; BG1 carries wide vertical stripes (4 tiles on / 4 tiles off → 64px period, so
; a per-scanline horizontal shift is unambiguous up to 63px). sf_tunnel arms an
; ANIMATED sine bend (the marquee tunnel): every scanline gets a horizontal
; offset = sine[(scanline + phase) & $FF] * amp / 128, and sf_bend_tick rolls
; the phase every frame so the displacement pattern advances downward.
;
; A flat BG would show each stripe at the SAME x on every row; the bend must
; measurably VARY a stripe's x per scanline (PRIMARY a), and the per-scanline
; pattern must ADVANCE between two screenshots N frames apart (PRIMARY b — the
; roll, what proves "tunnel" over "static bend").
;
; Done-condition (emulator-verifiable, read from RENDERED PIXELS):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = allocated HDMA channel (3..7)
;   - $7E:E010 = frame heartbeat (advances)
;   - a vertical stripe's x-position varies per scanline following the sine
;   - the per-scanline displacement pattern advances between frames (roll)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_bg.inc"            ; gfxmode, scroll, mset, sf_load_bg_tile, sf_bg_color
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin
.include "sf_fx.inc"            ; sf_bend / sf_tunnel / sf_bend_tick
.include "engine_state.inc"

BG_GREEN  = $03E0               ; 15-bit BGR green stripe colour
BG_MX     = $46                 ; tilemap fill loop scratch (DP, game area)
BG_MY     = $48
BG_TILE   = $4A

BEND_AMP   = 14                 ; peak displacement (px); amp 14 ≈ 13-14px
BEND_SPEED = 2                  ; phase roll per frame (the tunnel advance)

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; clears WRAM/CGRAM/VRAM
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; uploads under the coldstart forced blank (before screen-on)
    sf_load_bg_tile 1, bg_tile  ; BG1 CHR: tile 1 = solid colour index 1
    sf_bg_color 0, 1, BG_GREEN  ; BG palette 0, slot 1 = green

    jsr init_ppu                ; engine PPU defaults (screen on)
    gfxmode #1                  ; enable BG1 (zeros the shadow tilemap)

    ; --- wide vertical stripes: tile = (mx >> 2) & 1 → 64px period.
    ;     24 rows (192 px), not the full 28: the engine's one-shot initial
    ;     tilemap DMA is never retried (dirty bit clears after ONE transfer),
    ;     and a full 28-row 2KB transfer can overrun a truncated first VBlank
    ;     write window (PPU drops the tail rows). 24 rows fits the window and
    ;     the bend samples well inside 192 px anyway. (Same pattern as
    ;     parallax_test.asm — the established kit stripe-fill recipe.) ---
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
    mset #1, BG_MX, BG_MY, BG_TILE
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

    ; --- BG1 at world-zero scroll; the bend is the only horizontal motion ---
    scroll #1, #0, #0

    ; --- arm the ANIMATED sine tunnel on BG1 (the marquee effect) ---
    sf_tunnel #SF_CURVE_SINE, #BEND_AMP, #BEND_SPEED
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; record the allocated channel for the test

    sf_debug_magic

    ; enable NMI + auto-joypad at a defined point in the frame (ack a pending
    ; NMI, wait for active display, then enable — so the first NMI lands on a
    ; VBlank leading edge with the full tilemap DMA window; same as parallax).
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

    ; --- frame heartbeat for the test ---
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x
    jmp game_loop

; one solid 8x8 4bpp tile (all colour index 1) — same as parallax_test
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
