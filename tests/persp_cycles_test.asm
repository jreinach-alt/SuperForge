; =============================================================================
; persp_cycles_test — per-frame CPU cost of a Mode-7 pv_rebuild at the
; split_h_persp_demo's camera parameters, and at reduced line-count / interp
; (the candidate INCREMENTAL "live camera B" approaches). Kit rule #1: measure
; on the emulator, never estimate.
;
; WHY THIS EXISTS: the perspective rail ships camera A LIVE + camera B as
; PRECOMPUTED poses. This ROM is the authoritative measurement behind that
; decision — it proves a genuine SECOND live per-scanline solve for camera B
; cannot fit a 60 fps CPU frame. See docs/guides/split_h.md ("live-B budget").
;
; Method (identical to mode7_chamber_cycles_test / bend_cycles_test): a minimal
; NMI counts frames; the main loop runs a forced pv_rebuild back-to-back
; counting ticks; HDMA is off in the window so per-scanline transfers steal no
; cycles — this times the CPU table BUILD, not the HDMA transfer (hardware).
;     master_clocks_per_tick = frames * 357368 / ticks   (NTSC frame = 1364*262)
;
; Compile-time knobs (-D); defaults = camera A's shipping spec (a full solve):
;   CY_L0, CY_L1   perspective band [L0..L1)            (default 0..224)
;   CY_INTERP      1 / 2 / 4  (full / half / quarter res)(default 1)
;   CY_ANGLE       1 = vary angle each iter (pv_rebuild path); 0 = origin path (1)
;   CY_DOUBLE      1 = run TWO full solves per iter (the both-cameras-live worst
;                  case)                                 (default undefined)
;
;   $7E:E000 = "SFDB"   $7E:E030 = tick count (u32)   $7E:E034 = frame count (u32)
; =============================================================================
.p816
.smart

.include "header.inc"
.include "sf_core.inc"
.include "sf_frame.inc"
.include "sf_mode7.inc"
.include "engine_state.inc"

.ifndef CY_L0
CY_L0 = 0
.endif
.ifndef CY_L1
CY_L1 = 224
.endif
.ifndef CY_INTERP
CY_INTERP = 1
.endif
.ifndef CY_ANGLE
CY_ANGLE = 1
.endif

PV_S0 = 320
PV_S1 = 96
PV_SH = 512
PV_WR = 1
FOCUS = 168

TICKS  = $7E0000 + $E030
FRAMES = $7E0000 + $E034

M7T_POSX  = $32
M7T_POSY  = $34
M7T_ANGLE = $36

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

    sf_mode7_on
    sf_mode7_perspective #CY_L0, #CY_L1, #PV_S0, #PV_S1, #PV_SH, #CY_INTERP, #PV_WR
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
    inc M7T_POSY                ; advance posy (mode7_set_origin has real work)
.if CY_ANGLE
    sep #$20
    .a8
    inc M7T_ANGLE
    lda #$01
    sta M7_DIRTY_REBUILD        ; force the pv_rebuild path every iter
    rep #$20
    .a16
.endif
    sf_mode7_cam M7T_POSX, M7T_POSY, M7T_ANGLE
    sf_mode7_tick              ; the work under test
.ifdef CY_DOUBLE
    ; WORST CASE: a SECOND full per-scanline solve every iter (camera B live).
    sep #$20
    .a8
    lda #$01
    sta M7_DIRTY_REBUILD
    rep #$20
    .a16
    sf_mode7_tick
.endif

    rep #$30
    .a16
    .i16
    lda f:TICKS
    inc a
    sta f:TICKS
    bne :+
    lda f:TICKS + 2
    inc a
    sta f:TICKS + 2
:
    jmp measure_loop

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
