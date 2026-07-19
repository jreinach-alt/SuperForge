; =============================================================================
; plat_cyc_fade_test — measure sf_bright_fade_tick on its IDLE fast-exit path
; =============================================================================
; The flagship calls sf_bright_fade_tick every frame; when no fade is armed it
; must fast-exit cheaply (it is left in the loop permanently). This times that
; IDLE path by the frame-budget method (kit rule #1: measure, never estimate):
; NMI counts frames, the main loop runs sf_bright_fade_tick back-to-back with
; NO fade armed, and the pytest subtracts plat_cyc_base_test's loop overhead to
; isolate the tick (see test_platformer_cycles.py).
;
;   $7E:E000 = "SFDB"
;   $7E:E030 = iteration count (32-bit, little-endian)
;   $7E:E034 = frame count     (32-bit, from the NMI)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"
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
    ; NO sf_bright_fade arm — the tick under test must take its idle fast-exit.

    rep #$30
    .a16
    .i16
    lda #$0000
    sta f:REBUILDS
    sta f:REBUILDS + 2
    sta f:FRAMES
    sta f:FRAMES + 2

    sf_debug_magic

    sep #$20
    .a8
    lda #$80
    sta $4200                   ; NMITIMEN: enable VBlank NMI (the frame clock)
    rep #$30
    .a16
    .i16

measure_loop:
    sf_bright_fade_tick         ; the routine under test (idle), back-to-back
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

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "dma_scheduler.asm"
.include "bright_fade_engine.asm"
