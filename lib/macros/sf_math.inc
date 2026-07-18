; =============================================================================
; sf_math.inc — LUT math macros: trig, square root, arctangent, random
; =============================================================================
; Fixed-point math for gameplay: 8.8 signed values (high byte = signed
; integer part, low byte = fraction; $0100 = 1.0) and the kit's angle
; convention (0..255 = one full turn). The macros marshal into the API block
; and JSR the subroutine bodies in sf_math_data.inc — include THAT file once
; at the bottom of main.asm (CODE segment); this file is macros-only and is
; included at the top with the other sf_*.inc.
;
; Sine convention (matches the Mode 7 renderer's LUT): the table stores the
; NEGATED sine — sf_sin 64 returns -$0100, sf_sin 192 returns +$0100, and
; sf_cos 0 returns +$0100. The arctangent is the convention's inverse pair:
; sf_atan2 of (dx=+1.0, dy=0) = 0, (0, +1.0) = $40, (-1.0, 0) = $80,
; (0, -1.0) = $C0.
;
; Result convention: 16-bit result in A (and mirrored at ENGINE_A0). All
; macros assert A16/I16 entry, exit A16/I16, and expect DP=$0000 / DB=$00
; (the kit main-thread baseline).
; Scratch: DP $B0-$BC transient (never live across calls) + the hardware
; multiplier/divider; the random state persists at WRAM $053E-$053F.
; =============================================================================

.ifndef SF_MATH_INC
SF_MATH_INC = 1

.include "engine_api.inc"

; -----------------------------------------------------------------------------
; sf_sin angle -> A — negated sine, 8.8. angle verbatim 16-bit (low byte
; used). sf_sin #64 -> $FF00 (-1.0); sf_sin #192 -> $0100 (+1.0).
; Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); body stays A16.
.macro sf_sin sf_angle
    rep #$30
    .a16
    .i16
    lda sf_angle
    sta API_BLOCK_BASE + $00
    jsr _sf_sin
.endmacro

; -----------------------------------------------------------------------------
; sf_cos angle -> A — cosine, 8.8. sf_cos #0 -> $0100; sf_cos #128 -> $FF00.
; Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry; body stays A16.
.macro sf_cos sf_angle
    rep #$30
    .a16
    .i16
    lda sf_angle
    sta API_BLOCK_BASE + $00
    jsr _sf_cos
.endmacro

; -----------------------------------------------------------------------------
; sf_sqrt x -> A — square root of an 8.8 value (negative -> 0), interpolated:
; sf_sqrt #$0400 (4.0) -> $0200 (2.0). Clobbers A, X.
; WIDTH-RISK: asserts A16/I16 entry; the body toggles A8 internally and
; exits A16.
.macro sf_sqrt sf_x
    rep #$30
    .a16
    .i16
    lda sf_x
    sta API_BLOCK_BASE + $00
    jsr _sf_sqrt
.endmacro

; -----------------------------------------------------------------------------
; sf_atan2 dx, dy -> A — angle (0..255) of the vector (dx, dy), both 8.8
; signed verbatim operands. The inverse of the sf_sin/sf_cos convention.
; Clobbers A, X (+ DP $B0-$BC transient).
; WIDTH-RISK: asserts A16/I16 entry; the body toggles A8 internally and
; exits A16.
.macro sf_atan2 sf_dx, sf_dy
    rep #$30
    .a16
    .i16
    lda sf_dx
    sta API_BLOCK_BASE + $00
    lda sf_dy
    sta API_BLOCK_BASE + $04
    jsr _sf_atan2
.endmacro

; -----------------------------------------------------------------------------
; sf_srand seed — seed the random generator (16-bit verbatim; 0 substitutes
; a fixed nonzero seed — the shift register must never be all-zero). The
; same seed always replays the same sequence. Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; body stays A16.
.macro sf_srand sf_seed
    rep #$30
    .a16
    .i16
    lda sf_seed
    sta API_BLOCK_BASE + $00
    jsr _sf_srand
.endmacro

; -----------------------------------------------------------------------------
; sf_rnd max -> A — uniform draw 0..max-1. max verbatim 16-bit, range 1..256
; (the body reads the low byte; 0 means 256). Constant-time multiply-shift;
; when max doesn't divide 256 the buckets differ by at most 1/256 (fine for
; gameplay). Clobbers A.
; WIDTH-RISK: asserts A16/I16 entry; the body toggles A8 internally and
; exits A16.
.macro sf_rnd sf_max
    rep #$30
    .a16
    .i16
    lda sf_max
    sta API_BLOCK_BASE + $00
    jsr _sf_rnd
.endmacro

.endif ; SF_MATH_INC
