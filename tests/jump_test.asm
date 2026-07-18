; =============================================================================
; jump_test — run-gate for the jump-physics macros (sf_physics.inc)
; =============================================================================
; Scripted physics, no input: builds a ground row + a ceiling block, then runs
; three traces of sf_physics_step, recording the pixel y after EVERY step so
; the pytest can verify the whole state cycle (take-off, ascent, apex, bump,
; descent, landing snap, rest stability) — not just snapshots.
;
; Map: ground row 26 (px 208..215, all cols); ceiling row 21, cols 12..15
;      (px 96..127 x 168..175). Rest y on the ground = 200.
;
; Traces (64 steps each, 1 byte pixel-y per step):
;   $E040..$E07F  T1 clean jump at px=40 (no ceiling): settle, sf_jump, 64
;                 steps. Expect apex ~162 (~38px above 200) near step 18,
;                 landing back at exactly 200, then flat 200 (rest stability).
;   $E080..$E0BF  T2 head bump at px=100 (under the ceiling): expect min y
;                 EXACTLY 176 (snap below the tile, never inside it), early
;                 descent, settle at 200.
;   $E0C0..$E0FF  T3 fall from y=40 in open air: per-step delta <= 4
;                 (SF_MAX_FALL clamp = the no-tunnel bound), land at 200, flat.
;
; Scalars:
;   +$10  GROUNDED after T1 (expect 1)
;   +$12  VY after T1       (expect 0)
;   +$14  pixel y after T1  (expect 200)
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_bg.inc"            ; gfxmode, mset
.include "sf_map.inc"           ; sf_tile_flags (+ sf_solid_box for physics)
.include "sf_physics.inc"       ; sf_jump, sf_physics_step
.include "engine_state.inc"

PX       = $32                  ; player x (pixels)
PYF      = $34                  ; player y, 8.8 fixed
VY       = $36                  ; vertical velocity, signed 8.8
NEWY     = $38                  ; physics scratch
GROUNDED = $3A                  ; 1 = standing
TRACEPTR = $3C                  ; debug-region store pointer (bank $7E offset)
MJ_I     = $46                  ; map-fill loop counter

.segment "CODE"

NMI:
NMI_STUB:
    rti

RESET:
    sf_coldstart

    jsr init_ppu
    gfxmode #1                  ; zeros shadow tilemaps + sets 32x32 dims

    ; --- world: solid tile 2; ground row 26; ceiling row 21 cols 12..15 ---
    sf_tile_flags 2, SF_FLAG_SOLID
    rep #$30
    .a16
    .i16
    stz MJ_I
@ground:
    mset #1, MJ_I, #26, #2
    lda MJ_I
    inc a
    sta MJ_I
    cmp #32
    bne @ground
    lda #12
    sta MJ_I
@ceiling:
    mset #1, MJ_I, #21, #2
    lda MJ_I
    inc a
    sta MJ_I
    cmp #16
    bne @ceiling

    ; =========================================================================
    ; T1 — clean jump at px=40
    ; =========================================================================
    lda #40
    sta PX
    lda #200 * 256              ; y = 200.0 (rest on the ground row)
    sta PYF
    stz VY
    stz GROUNDED
    jsr settle                  ; two steps -> grounded latches
    sf_jump VY, GROUNDED
    lda #$E040
    sta TRACEPTR
    jsr run_trace               ; 64 recorded steps

    rep #$30
    .a16
    ldx #$0000
    lda GROUNDED
    sta f:$7E0000 + $E010, x
    lda VY
    sta f:$7E0000 + $E012, x
    lda PYF
    xba
    and #$00FF
    sta f:$7E0000 + $E014, x

    ; =========================================================================
    ; T2 — head bump at px=100 (box 100..107 sits under ceiling 96..127)
    ; =========================================================================
    lda #100
    sta PX
    lda #200 * 256
    sta PYF
    stz VY
    stz GROUNDED
    jsr settle
    sf_jump VY, GROUNDED
    lda #$E080
    sta TRACEPTR
    jsr run_trace

    ; =========================================================================
    ; T3 — fall from y=40 in open air at px=40 (terminal-velocity clamp)
    ; =========================================================================
    lda #40
    sta PX
    lda #40 * 256
    sta PYF
    stz VY
    stz GROUNDED
    lda #$E0C0
    sta TRACEPTR
    jsr run_trace

    sf_debug_magic
    sf_debug_complete
    stp

; -----------------------------------------------------------------------------
; settle — two physics steps so the ground probe latches grounded=1.
; WIDTH-RISK: asserts A16/I16; exits A16/I16.
settle:
    rep #$30
    .a16
    .i16
    sf_physics_step PYF, VY, PX, NEWY, GROUNDED
    sf_physics_step PYF, VY, PX, NEWY, GROUNDED
    rts

; -----------------------------------------------------------------------------
; run_trace — 64 physics steps, storing the pixel y (1 byte) per step at
; bank-$7E offset [TRACEPTR++]. Y saved around the step (engine clobbers it).
; WIDTH-RISK: asserts A16/I16; exits A16/I16.
run_trace:
    rep #$30
    .a16
    .i16
    ldy #64
rt_loop:
    phy
    sf_physics_step PYF, VY, PX, NEWY, GROUNDED
    rep #$30
    .a16
    .i16
    lda PYF
    xba
    and #$00FF
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
