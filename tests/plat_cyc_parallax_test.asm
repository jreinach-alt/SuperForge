; =============================================================================
; plat_cyc_parallax_test — measure sf_parallax_tick (hdma_update_parallax_bands)
; =============================================================================
; Times the flagship's per-frame parallax rebuild by the frame-budget method
; (kit rule #1: measure, never estimate). NMI counts frames; the main loop runs
; sf_parallax_tick back-to-back and counts iterations. The pytest computes
; master-clocks-per-iteration and subtracts plat_cyc_base_test's loop overhead
; to isolate the tick (see test_platformer_cycles.py). Same 2-band arm as
; templates/platformer/main.asm (BG2, split 96, ratios 0x20/0x60), a nonzero
; world-X fed once so the table build is representative.
;
;   $7E:E000 = "SFDB"
;   $7E:E030 = iteration count (32-bit, little-endian)
;   $7E:E034 = frame count     (32-bit, from the NMI)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "sf_bg.inc"
.include "sf_frame.inc"
.include "sf_fx.inc"
.include "engine_state.inc"

REBUILDS = $7E0000 + $E030
FRAMES   = $7E0000 + $E034

.segment "CODE"

NMI:
    rep #$30
    .a16
    .i16
    pha
    phx
    lda f:FRAMES
    inc a
    sta f:FRAMES
    bne :+
    lda f:FRAMES + 2
    inc a
    sta f:FRAMES + 2
:
    sep #$20
    .a8
    lda $4210                   ; ack NMI (read-clear)
    rep #$30
    .a16
    .i16
    plx
    pla
    rti

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    jsr hdma_alloc_init

    sf_load_bg_tile 1, bg_tile
    sf_bg_color 0, 1, $03E0
    jsr init_ppu
    gfxmode #1

    ; arm the 2-band parallax on BG2, feed a representative nonzero world-X
    scroll #2, #120, #0             ; SHADOW_BG2HOFS = world-X 120 (mid-level)
    sf_parallax_bands #2, #96, #$20, #$60

    rep #$30
    .a16
    .i16
    lda #$0000
    sta f:REBUILDS
    sta f:REBUILDS + 2
    sta f:FRAMES
    sta f:FRAMES + 2

    sf_debug_magic

    ; NMI on, HDMA off — time the table BUILD (CPU), not the HDMA transfer.
    sep #$20
    .a8
    stz $420C                   ; HDMAEN = 0 (no HDMA contention in the window)
    lda #$80
    sta $4200                   ; NMITIMEN: enable VBlank NMI (the frame clock)
    rep #$30
    .a16
    .i16

measure_loop:
    sf_parallax_tick            ; the routine under test, back-to-back
    rep #$30
    .a16
    .i16
    lda f:REBUILDS
    inc a
    sta f:REBUILDS
    bne measure_loop
    lda f:REBUILDS + 2
    inc a
    sta f:REBUILDS + 2
    bra measure_loop

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
