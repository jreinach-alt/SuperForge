; =============================================================================
; plat_cyc_base_test — the empty measure-loop baseline (frame-budget method)
; =============================================================================
; The differential partner for plat_cyc_parallax_test / plat_cyc_fade_test:
; the SAME back-to-back counter loop with NO routine under test, so its
; master-clocks-per-iteration is the pure loop overhead. Subtracting it from a
; sibling ROM's per-iteration cost isolates the routine (kit rule #1: measure,
; never estimate; see test_platformer_cycles.py). The measure_loop body below
; is byte-identical to the sibling ROMs' — only the routine call differs.
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
    ; (baseline: no routine under test) — the counter code below is identical
    ; in every plat_cyc_* ROM so the differential cancels the loop overhead.
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
