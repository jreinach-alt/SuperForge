; =============================================================================
; math_test — run-gate for the sf_math macros (trig / sqrt / atan2 / random)
; =============================================================================
; Exercises the LUT math against hand-computed cases and records the results
; in the debug region for MesenRunner to read back. All values 8.8 unless
; noted; angles 0..255 = one full turn (negated-sine convention).
;
;   $7E:E00A  sf_sin #0          -> $0000
;   $7E:E00C  sf_sin #64         -> $FF00 (-1.0; the LUT stores -sine)
;   $7E:E00E  sf_sin #192        -> $0100 (+1.0)
;   $7E:E010  sf_cos #0          -> $0100 (+1.0)
;   $7E:E012  sf_cos #128        -> $FF00 (-1.0)
;   $7E:E014  sf_sqrt #$0400     -> $0200 (sqrt 4.0 = 2.0)
;   $7E:E016  sf_sqrt #0         -> $0000
;   $7E:E018  sf_sqrt #$1900     -> $0500 (sqrt 25.0 = 5.0)
;   $7E:E01A  sf_atan2 +1, 0     -> $0000
;   $7E:E01C  sf_atan2 0, +1     -> $0040 (quarter turn)
;   $7E:E01E  sf_atan2 -1, 0     -> $0080 (half turn)
;   $7E:E020  sf_atan2 0, -1     -> $00C0 (three-quarter turn)
;   $7E:E030  32 words: sf_rnd #16 draws, seed $1234 (all < 16)
;   $7E:E070   8 words: sf_rnd #16 draws, seed $1234 again (same sequence)
;   $7E:E080   8 words: sf_rnd #16 draws, seed $BEEF (different sequence)
;
; Build: 32KB generic test-ROM rule (no engine .asm needed — the math
; bodies + LUTs come from sf_math_data.inc).
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_math.inc"          ; sf_sin/cos/sqrt/atan2/srand/rnd
.include "engine_state.inc"     ; ES_ATAN2_* scratch the bodies use

.segment "CODE"

NMI:
NMI_STUB:
    rti

RESET:
    sf_coldstart

    rep #$30
    .a16
    .i16

    ; (the trig/sqrt/atan2 bodies clobber X for LUT indexing — re-zero it
    ;  before every long-indexed debug store)

    ; --- sine / cosine ---
    sf_sin #0
    ldx #$0000
    sta f:$7E0000 + $E00A, x
    sf_sin #64
    ldx #$0000
    sta f:$7E0000 + $E00C, x
    sf_sin #192
    ldx #$0000
    sta f:$7E0000 + $E00E, x
    sf_cos #0
    ldx #$0000
    sta f:$7E0000 + $E010, x
    sf_cos #128
    ldx #$0000
    sta f:$7E0000 + $E012, x

    ; --- square root ---
    sf_sqrt #$0400
    ldx #$0000
    sta f:$7E0000 + $E014, x
    sf_sqrt #0
    ldx #$0000
    sta f:$7E0000 + $E016, x
    sf_sqrt #$1900
    ldx #$0000
    sta f:$7E0000 + $E018, x

    ; --- arctangent, the four cardinal directions ---
    sf_atan2 #$0100, #0
    ldx #$0000
    sta f:$7E0000 + $E01A, x
    sf_atan2 #0, #$0100
    ldx #$0000
    sta f:$7E0000 + $E01C, x
    sf_atan2 #$FF00, #0
    ldx #$0000
    sta f:$7E0000 + $E01E, x
    sf_atan2 #0, #$FF00
    ldx #$0000
    sta f:$7E0000 + $E020, x

    ; --- random: 32 draws below 16, seed $1234 ---
    sf_srand #$1234
    ldx #$0000
@rnd_loop_a:
    sf_rnd #16
    sta f:$7E0000 + $E030, x
    inx
    inx
    cpx #64
    bne @rnd_loop_a

    ; --- same seed -> same sequence (first 8 draws) ---
    sf_srand #$1234
    ldx #$0000
@rnd_loop_b:
    sf_rnd #16
    sta f:$7E0000 + $E070, x
    inx
    inx
    cpx #16
    bne @rnd_loop_b

    ; --- different seed -> different sequence ---
    sf_srand #$BEEF
    ldx #$0000
@rnd_loop_c:
    sf_rnd #16
    sta f:$7E0000 + $E080, x
    inx
    inx
    cpx #16
    bne @rnd_loop_c

    sf_debug_magic
    sf_debug_complete
    stp

.include "sf_math_data.inc"     ; the bodies + generated LUTs (emitted half)
