; =============================================================================
; pool_test — run-gate for the sf_pool macros
; =============================================================================
; Drives a 4-slot pool through its full state cycle — empty, filling, kill,
; slot REUSE, full/overflow — and records every result in the debug region.
; Per the discipline, the cycle covers all transitions, not just spawn-once:
;
;   $7E:E00A  count after init                 -> expect 0
;   $7E:E00C  1st spawn offset                 -> expect 0
;   $7E:E00E  2nd spawn offset                 -> expect 2
;   $7E:E010  3rd spawn offset                 -> expect 4
;   $7E:E012  count (3 live)                   -> expect 3
;   $7E:E014  spawn after killing slot 1       -> expect 2  (reuses the hole)
;   $7E:E016  4th spawn offset                 -> expect 6
;   $7E:E018  spawn when full                  -> expect $FFFF
;   $7E:E01A  count (all live)                 -> expect 4
;   $7E:E01C  count after kill_x slot 0        -> expect 3
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_pool.inc"
.include "engine_state.inc"

POOL   = $1800                  ; alive[4] in the game-array region (see sf_pool.inc)
POOL_N = 4

.segment "CODE"

NMI:
NMI_STUB:
    rti

RESET:
    sf_coldstart

    sf_pool_init POOL, POOL_N

    sf_pool_count POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E00A, x    ; expect 0

    sf_pool_spawn POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E00C, x    ; expect 0

    sf_pool_spawn POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E00E, x    ; expect 2

    sf_pool_spawn POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E010, x    ; expect 4

    sf_pool_count POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E012, x    ; expect 3

    ; kill the middle slot (offset 2), then spawn must reuse the hole
    ldx #$0002
    sf_pool_kill_x POOL
    sf_pool_spawn POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E014, x    ; expect 2

    sf_pool_spawn POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E016, x    ; expect 6

    sf_pool_spawn POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E018, x    ; expect $FFFF (full)

    sf_pool_count POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E01A, x    ; expect 4

    ldx #$0000
    sf_pool_kill_x POOL
    sf_pool_count POOL, POOL_N
    ldx #$0000
    sta f:$7E0000 + $E01C, x    ; expect 3

    sf_debug_magic
    sf_debug_complete
    stp
