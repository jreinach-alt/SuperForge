; =============================================================================
; col_box_test — run-gate for the col_box collision macro
; =============================================================================
; Exercises col_box's two outcomes against hand-computed cases and records the
; results in the debug region for MesenRunner to read back.
;
;   $7E:E00A  overlapping boxes    -> expect 1
;   $7E:E00C  disjoint boxes       -> expect 0
;   $7E:E00E  1px overlap          -> expect 1
;   $7E:E010  edge-touching (0px)  -> expect 0 (STRICT overlap: touching != overlap)
;
; Build:
;   ca65 --cpu 65816 -I infrastructure/rom_template -I asm_repo_staging/lib/macros \
;        -I engine asm_repo_staging/tests/col_box_test.asm -o cb.o
;   ld65 -C infrastructure/rom_template/lorom.cfg cb.o -o cb.sfc
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_collision.inc"     ; col_box (+ engine_api)
.include "engine_state.inc"

.segment "CODE"

NMI:
NMI_STUB:
    rti

RESET:
    sf_coldstart

    ; (1) overlapping: A(10,10,20,20) covers 10..30; B(20,20,20,20) covers 20..40 -> overlap
    col_box #10, #10, #20, #20,  #20, #20, #20, #20
    ldx #$0000
    sta f:$7E0000 + $E00A, x

    ; (2) disjoint: A(10,10,5,5) covers 10..15; B(100,100,5,5) far away -> no overlap
    col_box #10, #10, #5, #5,  #100, #100, #5, #5
    ldx #$0000
    sta f:$7E0000 + $E00C, x

    ; (3) 1px overlap: A covers x[10,20), B(19) covers x[19,29) -> share 1px -> overlap
    col_box #10, #10, #10, #10,  #19, #10, #10, #10
    ldx #$0000
    sta f:$7E0000 + $E00E, x

    ; (4) edge-touching: A right edge at x=20 (exclusive), B left edge at x=20 -> 0px -> no overlap
    col_box #10, #10, #10, #10,  #20, #10, #10, #10
    ldx #$0000
    sta f:$7E0000 + $E010, x

    sf_debug_magic
    sf_debug_complete
    stp

.include "collision_engine.asm"
