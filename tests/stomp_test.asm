; =============================================================================
; stomp_test — run-gate for the stomp macro (sf_stomp_check)
; =============================================================================
; Pure contact classification, no map and no physics loop: six hand-crafted
; player/enemy states exercise every branch of sf_stomp_check, recording the
; result code + the post-call ealive/vy so the pytest can verify both the
; classification AND the side effects (kill + bounce on stomp only).
;
; Enemy at (100, 200) for all cases (ey passed immediate). Player 8x8.
;
; Cases (result @ +$10 + 6*i, ealive @ +$12 + 6*i, vy @ +$14 + 6*i):
;   T0 stomp:    pyi=193 (bottom 201, 1px into the top), vy=+$0100 falling
;                -> 1, ealive 0, vy = -SF_BOUNCE_VEL ($FD00)
;   T1 side:     pyi=200 level, vy=0 standing          -> 2, alive, vy 0
;   T2 below:    pyi=204, vy=-$0200 rising             -> 2, alive, vy kept
;   T3 none:     px=150 (no overlap), falling          -> 0, alive, vy kept
;   T4 dead:     ealive=0, perfect stomp geometry      -> 0, stays dead,
;                vy UNCHANGED (dead enemies are transparent)
;   T5 deep:     pyi=199 (bottom 207, 7px deep), vy=+$0100 falling -> 2
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_enemy.inc"         ; sf_stomp_check (+ col_box via sf_collision)
.include "engine_state.inc"

PX     = $32
PYI    = $34
VY     = $36
EX     = $38
EALIVE = $3A
OUT    = $3C                    ; debug-region store pointer

.segment "CODE"

NMI:
NMI_STUB:
    rti

; -----------------------------------------------------------------------------
; record — store A (result), EALIVE, VY at [OUT], advance OUT by 6.
; WIDTH-RISK: asserts A16/I16 entry; exits A16/I16.
record:
    rep #$30
    .a16
    .i16
    ldx OUT
    sta f:$7E0000, x
    lda EALIVE
    sta f:$7E0002, x
    lda VY
    sta f:$7E0004, x
    txa
    clc
    adc #6
    sta OUT
    rts

RESET:
    sf_coldstart

    rep #$30
    .a16
    .i16
    lda #$E010
    sta OUT
    lda #100
    sta EX

    ; T0 — clean stomp
    lda #100
    sta PX
    lda #193
    sta PYI
    lda #$0100
    sta VY
    lda #1
    sta EALIVE
    sf_stomp_check PX, PYI, VY, EX, #200, EALIVE
    jsr record

    ; T1 — standing side contact
    lda #95
    sta PX
    lda #200
    sta PYI
    stz VY
    lda #1
    sta EALIVE
    sf_stomp_check PX, PYI, VY, EX, #200, EALIVE
    jsr record

    ; T2 — rising from below
    lda #100
    sta PX
    lda #204
    sta PYI
    lda #(($10000 - $0200) & $FFFF)
    sta VY
    lda #1
    sta EALIVE
    sf_stomp_check PX, PYI, VY, EX, #200, EALIVE
    jsr record

    ; T3 — no overlap
    lda #150
    sta PX
    lda #193
    sta PYI
    lda #$0100
    sta VY
    lda #1
    sta EALIVE
    sf_stomp_check PX, PYI, VY, EX, #200, EALIVE
    jsr record

    ; T4 — dead enemy is transparent (perfect stomp geometry, no effect)
    lda #100
    sta PX
    lda #193
    sta PYI
    lda #$0100
    sta VY
    stz EALIVE
    sf_stomp_check PX, PYI, VY, EX, #200, EALIVE
    jsr record

    ; T5 — falling but too deep (side contact mid-fall)
    lda #100
    sta PX
    lda #199
    sta PYI
    lda #$0100
    sta VY
    lda #1
    sta EALIVE
    sf_stomp_check PX, PYI, VY, EX, #200, EALIVE
    jsr record

    sf_debug_magic
    sf_debug_complete
    stp

.include "collision_engine.asm"
