; =============================================================================
; patrol_test — run-gate for the enemy patrol macro (sf_enemy.inc)
; =============================================================================
; Scripted patrol, no input: two enemies stepped 200 frames each, recording
; the x position EVERY step, so the pytest can verify the whole bounce cycle
; (walk, wall turn, ledge turn, return) and the exact bounds.
;
; Map: ground row 26 (full width); walls cols 4 and 14, rows 20..25 (px
;      32..39 / 112..119); platform row 18, cols 18..24 (px 144..199).
;
; Traces (200 steps each, 1 byte x per step):
;   $E040..$E107  T1 wall-bounded patrol on the ground (ey=200, start x=80,
;                 dir right): bounce between EXACT bounds x=40 (left wall)
;                 and x=104 (right wall), multiple round trips.
;   $E110..$E1D7  T2 ledge-bounded patrol on the platform (ey=136, start
;                 x=170, dir right): bounce between EXACT bounds x=144
;                 (left edge) and x=192 (right edge) — the box never
;                 overhangs the platform (144..199).
;
; Scalars:
;   +$10  T1 final dir (0/1 — just sanity, trace is the contract)
;   +$12  T2 final dir
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_bg.inc"            ; gfxmode, mset
.include "sf_map.inc"           ; sf_tile_flags
.include "sf_enemy.inc"         ; sf_patrol_step
.include "engine_state.inc"

EX       = $32                  ; enemy x
EY       = $34                  ; enemy y
EDIR     = $36                  ; 0 = left, 1 = right
NEWX     = $38                  ; patrol scratch
LEADX    = $3A
FOOTY    = $3C
TRACEPTR = $3E                  ; debug-region store pointer
MP_I     = $46                  ; map-fill loop counter

.segment "CODE"

NMI:
NMI_STUB:
    rti

RESET:
    sf_coldstart

    jsr init_ppu
    gfxmode #1                  ; zeros shadow tilemaps + sets 32x32 dims

    ; --- terrain: tile 2 solid; ground, two walls, one platform ---
    sf_tile_flags 2, SF_FLAG_SOLID
    rep #$30
    .a16
    .i16
    stz MP_I
@ground:
    mset #1, MP_I, #26, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #32
    bne @ground
    lda #20
    sta MP_I
@walls:                         ; cols 4 + 14, rows 20..25
    mset #1, #4,  MP_I, #2
    mset #1, #14, MP_I, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #26
    bne @walls
    lda #18
    sta MP_I
@plat:                          ; row 18, cols 18..24
    mset #1, MP_I, #18, #2
    lda MP_I
    inc a
    sta MP_I
    cmp #25
    bne @plat

    ; --- T1: wall-bounded patrol on the ground ---
    lda #80
    sta EX
    lda #200
    sta EY
    lda #1
    sta EDIR
    lda #$E040
    sta TRACEPTR
    jsr run_trace

    ldx #$0000
    lda EDIR
    sta f:$7E0000 + $E010, x

    ; --- T2: ledge-bounded patrol on the platform ---
    lda #170
    sta EX
    lda #136
    sta EY
    lda #1
    sta EDIR
    lda #$E110
    sta TRACEPTR
    jsr run_trace

    ldx #$0000
    lda EDIR
    sta f:$7E0000 + $E012, x

    sf_debug_magic
    sf_debug_complete
    stp

; -----------------------------------------------------------------------------
; run_trace — 200 patrol steps, storing x (1 byte) per step at bank-$7E
; offset [TRACEPTR++]. Y saved around the step (engine clobbers it).
; WIDTH-RISK: asserts A16/I16; exits A16/I16.
run_trace:
    rep #$30
    .a16
    .i16
    ldy #200
rt_loop:
    phy
    sf_patrol_step EX, EY, EDIR, NEWX, LEADX, FOOTY
    rep #$30
    .a16
    .i16
    lda EX
    ldx TRACEPTR
    sep #$20
    .a8
    sta f:$7E0000, x
    rep #$20
    .a16
    inc TRACEPTR
    ply
    dey
    beq rt_done                 ; trampoline: the loop body is a >127-byte
    jmp rt_loop                 ; macro expansion (see lib/macros/README.md)
rt_done:
    rts

.include "ppu_init.inc"
.include "bg_engine.asm"
.include "collision_engine.asm"
