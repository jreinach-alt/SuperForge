; =============================================================================
; bend_cycles_test — measure sf_bend_tick (hdma_update_hofs_curve) cycle cost
; =============================================================================
; Times the per-frame bend rebuild on the emulator (kit rule #1: measure, never
; estimate) by the FRAME-BUDGET method — robust where in-ROM beam-counter
; latching is finicky. NMI is enabled and the NMI handler counts frames; the
; main loop runs hdma_update_hofs_curve in a tight back-to-back loop and counts
; rebuilds. The pytest reads (rebuilds, frames) after a fixed run and computes:
;     master_clocks_per_rebuild = frames * 357368 / rebuilds   (NTSC frame =
;     1364*262 master clocks); 1 CPU fast cycle = 6 master clocks (WRAM).
; A tight loop of pure rebuilds (no per-frame game work, no sf_frame_begin
; wait) keeps the CPU busy ~100% so frames*budget / rebuilds is the true cost.
;
; v1.1 NOTE: this ROM arms a PURE ROLL (base scroll = 0), so the tick takes the
; E-SLIDE pointer-slide fast-path (just A1Tn arithmetic, near-zero cost). The
; OPTIMIZED REFILL path (base scroll != 0) is measured by bend_cycles_refill_test
; — the two paths are mutually exclusive per frame, so each needs its own ROM.
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

REBUILDS = $7E0000 + $E030      ; 32-bit rebuild counter
FRAMES   = $7E0000 + $E034      ; 32-bit frame counter (NMI-incremented)

.segment "CODE"

NMI:
    ; minimal NMI: bump the 32-bit frame counter, ack, return. We do NOT run
    ; the stock engine NMI here — this ROM measures CPU time, not rendering.
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
    scroll #1, #0, #0

    ; arm the animated tunnel so hdma_update_hofs_curve has a channel + table
    sf_tunnel #SF_CURVE_SINE, #14, #2

    ; zero the 32-bit counters
    rep #$30
    .a16
    .i16
    lda #$0000
    sta f:REBUILDS
    sta f:REBUILDS + 2
    sta f:FRAMES
    sta f:FRAMES + 2

    sf_debug_magic

    ; enable NMI (vblank) — the only interrupt; it just counts frames.
    ; Disable HDMA ($420C=0) so the bend channel's per-scanline transfer does
    ; NOT steal cycles during the measured window — we are timing the table
    ; BUILD (CPU), not the HDMA transfer (free, hardware). NMI_HDMA_ENABLE is
    ; left set but the stock VBlank re-arm path is not linked in this ROM.
    sep #$20
    .a8
    stz $420C                   ; HDMAEN = 0 (no HDMA contention)
    lda #$80
    sta $4200
    rep #$30
    .a16
    .i16

measure_loop:
    sf_bend_tick                ; the routine under test, back-to-back

    ; rebuilds += 1 (32-bit)
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
