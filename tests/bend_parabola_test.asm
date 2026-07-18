; =============================================================================
; bend_parabola_test — run-gate for the STATIC sf_bend / SF_CURVE_PARABOLA arm
; =============================================================================
; Companion to bend_test.asm (which arms the ANIMATED sf_tunnel sine). This ROM
; arms the STATIC parabola bend — the curved-horizon half of D-CURVE that the
; shipped suite did not exercise (audit-1 Deviation #1). It is a SEPARATE ROM,
; not a -D variant: the generic tests/%.sfc Makefile rule does not forward -D.
;
; BG1 carries the same wide vertical stripes (4 tiles on / 4 tiles off → 64px
; period) so a per-scanline horizontal shift is unambiguous up to 63px.
; sf_bend SF_CURVE_PARABOLA arms a STATIC per-scanline offset =
;   parabola[scanline & $FF] * amp / 128
; with NO phase roll and NO tick — the parabola LUT is 0 at the centre scanline
; (~112) and rises to +peak at the top and bottom edges, SYMMETRIC about the
; centre. So a stripe's leftmost edge x is displaced LEAST at screen centre and
; MOST (same direction) at top and bottom: the curved-horizon bow.
;
; Done-condition (emulator-verifiable, read from RENDERED PIXELS):
;   - boots ($7E:E000 == "SFDB"); $7E:E012 = allocated HDMA channel (3..7)
;   - $7E:E010 = frame heartbeat (advances — the loop runs)
;   - a vertical stripe's x-position varies per scanline, SYMMETRIC about the
;     vertical centre (edge-x at y ≈ edge-x at the mirrored scanline)
;   - the rendered image is STATIC (no roll) frame-to-frame WHILE the heartbeat
;     keeps advancing — distinguishes static sf_bend from animated sf_tunnel
;
; The loop deliberately calls sf_bend_tick every frame (as a real game would
; leave it in) with speed 0: the table is rebuilt identically each frame, so the
; pixels MUST hold static while the heartbeat advances — proving "static" is a
; property of the curve/speed, not of a frozen main loop.
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
    ;     write window. 24 rows fits the window; the parabola centre (~112) and
    ;     both lobes sample well inside 192 px. (Same recipe as bend_test.asm.) ---
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

    ; --- arm the STATIC parabola bend on BG1 (the curved-horizon shape) ---
    sf_bend #SF_CURVE_PARABOLA, #BEND_AMP
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; record the allocated channel for the test

    sf_debug_magic

    ; enable NMI + auto-joypad at a defined point in the frame (ack a pending
    ; NMI, wait for active display, then enable — so the first NMI lands on a
    ; VBlank leading edge with the full tilemap DMA window; same as bend_test).
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

    sf_bend_tick                ; speed 0 → identical rebuild; pixels HOLD static

    ; --- frame heartbeat for the test (the loop runs; the bend holds) ---
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
