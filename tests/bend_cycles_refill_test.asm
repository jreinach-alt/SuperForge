; =============================================================================
; bend_cycles_refill_test — measure the OPTIMIZED REFILL per-frame cost (E-PERF)
; =============================================================================
; Companion to bend_cycles_test.asm. That ROM arms a PURE ROLL (base scroll 0)
; so the tick takes the E-SLIDE pointer-slide fast-path; THIS ROM sets a NONZERO
; base scroll (scroll #1, #100, #0) before arming, so every sf_bend_tick takes
; the composed-base optimized REFILL path (the S1/S3 224-line word rebuild +
; one adc base per line). Same frame-budget method:
;     master_clocks_per_rebuild = frames * 357368 / rebuilds.
;
;   $7E:E000 = "SFDB"
;   $7E:E030 = rebuild count (32-bit, little-endian)
;   $7E:E034 = frame count   (32-bit, from the NMI)
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
    lda $4210
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

    ; NONZERO base scroll → forces the optimized refill path every tick.
    scroll #1, #100, #0

    sf_tunnel #SF_CURVE_SINE, #14, #2

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
    stz $420C                   ; HDMAEN = 0 (no HDMA contention during timing)
    lda #$80
    sta $4200
    rep #$30
    .a16
    .i16

measure_loop:
    sf_bend_tick                ; refill path (base scroll = 100), back-to-back

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
