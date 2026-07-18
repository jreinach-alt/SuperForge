; =============================================================================
; mode7_chamber_cycles_test — measure the chamber's per-frame Mode 7 CPU cost
; =============================================================================
; Kit rule #1: measure on the emulator, never estimate. Frame-budget method (as
; bend_cycles_test): a minimal NMI counts frames; the main loop runs the
; chamber's per-frame engine work (sf_mode7_cam + sf_mode7_tick) back-to-back,
; counting iterations. The pytest computes:
;     master_clocks_per_tick = frames * 357368 / ticks   (NTSC frame = 1364*262)
;
; With a CONSTANT angle (MEASURE_REBUILD = 0) the tick takes the cheap ORIGIN
; path (mode7_set_origin only — NO pv_rebuild): the chamber's real steady-state
; per-frame cost. Set MEASURE_REBUILD = 1 to force a changing angle each iter
; (the pv_rebuild path) — what a per-frame rotating matrix would cost, for
; contrast. posy is advanced every iter either way so set_origin has real work.
;
; HDMA is disabled in the measured window so the per-scanline transfers do NOT
; steal cycles — we time the CPU table BUILD, not the HDMA transfer (hardware).
;
;   $7E:E000 = "SFDB"
;   $7E:E030 = tick count  (32-bit, little-endian)
;   $7E:E034 = frame count (32-bit, from the NMI)
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init
.include "sf_mode7.inc"         ; the Mode 7 macro group
.include "engine_state.inc"

MEASURE_REBUILD = 0             ; 0 = origin path (real chamber cost); 1 = rebuild

TICKS  = $7E0000 + $E030        ; 32-bit per-frame-work iteration counter
FRAMES = $7E0000 + $E034        ; 32-bit frame counter (NMI-incremented)

; the chamber's perspective (matches templates/mode7_chamber/main.asm)
PV_L0 = 32
PV_L1 = 224
PV_S0 = 320
PV_S1 = 64
PV_SH = 1440
PV_IN = 1
PV_WR = 1
FOCUS = 128

M7T_POSX  = $32
M7T_POSY  = $34
M7T_ANGLE = $36

.segment "CODE"

NMI:
    ; minimal NMI: bump the 32-bit frame counter, ack, return. The stock engine
    ; NMI is NOT run — this ROM measures main-loop CPU time, not the commit.
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

    sf_mode7_on
    sf_mode7_perspective #PV_L0, #PV_L1, #PV_S0, #PV_S1, #PV_SH, #PV_IN, #PV_WR
    sf_mode7_focus #FOCUS
    sf_mode7_flags #$00

    lda #512
    sta M7T_POSX
    sta M7T_POSY
    stz M7T_ANGLE
    sf_mode7_cam M7T_POSX, M7T_POSY, M7T_ANGLE
    sf_mode7_tick               ; build once (clears M7_DIRTY_REBUILD)

    rep #$30
    .a16
    .i16
    lda #$0000
    sta f:TICKS
    sta f:TICKS + 2
    sta f:FRAMES
    sta f:FRAMES + 2

    sf_debug_magic

    sep #$20
    .a8
    stz $420C                   ; HDMAEN = 0 (no HDMA contention in the window)
    lda #$80
    sta $4200                   ; NMI on (frame counter only)
    rep #$30
    .a16
    .i16

measure_loop:
    .a16
    .i16
    inc M7T_POSY                ; advance posy (gives mode7_set_origin real work)
.if MEASURE_REBUILD
    sep #$20
    .a8
    inc M7T_ANGLE              ; vary the angle -> force the pv_rebuild path
    rep #$20
    .a16
.endif
    sf_mode7_cam M7T_POSX, M7T_POSY, M7T_ANGLE
    sf_mode7_tick              ; the per-frame work under test

    rep #$30
    .a16
    .i16
    lda f:TICKS
    inc a
    sta f:TICKS
    bne measure_loop
    lda f:TICKS + 2
    inc a
    sta f:TICKS + 2
    bra measure_loop

; =============================================================================
; Engine includes — the documented sf_mode7.inc link-partner order
; =============================================================================
mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"
