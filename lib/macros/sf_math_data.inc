; =============================================================================
; sf_math_data.inc — math routines + LUTs (macro library, link partner)
; =============================================================================
; The emitted half of sf_math.inc: the LUT-based trig/sqrt/arctangent
; subroutine bodies (transcribed from the engine's proven implementations)
; plus the generated lookup tables. Unlike the macro files, this file EMITS
; bytes — include it ONCE at the BOTTOM of main.asm, inside the CODE segment,
; next to the engine .asm includes:
;
;   .include "sf_math_data.inc"
;
; (If you forget it, the link fails naming _sf_sin / math_sin_lut — that's
; your cue.) Requires engine_state.inc (the ES_ATAN2_* scratch block) and
; engine_api.inc (API_BLOCK_BASE / ENGINE_A0 — sf_math.inc includes it).
;
; Calling convention (all bodies): A16/I16 on entry (the macros assert it),
; DP=$0000, DB=$00. Args pre-marshalled into the API block by the macro.
; Result: 16-bit in A AND mirrored at ENGINE_A0 ($20-$23, high word zero).
; Scratch: DP $B0-$BC (the ES_ATAN2_* transient block — shared with other
; main-thread transients by mutual exclusion, never live across calls) and
; the hardware multiplier/divider ($4202-$4216). Game DP $32-$5F untouched.
; WRAM $053E-$053F = the random-number state (claimed scratch slot — see
; lib/macros/README.md).
; =============================================================================

.ifndef SF_MATH_DATA_INC
SF_MATH_DATA_INC = 1

; -----------------------------------------------------------------------------
; _sf_sin — sine of an angle. In: API+0 = angle (low byte used; 0..255 = one
; full turn). Out: A = 8.8 signed, negated-sine convention: _sf_sin(64) =
; $FF00 (-1.0), _sf_sin(192) = $0100 (+1.0). Clobbers A, X.
; WIDTH-RISK: A16/I16 throughout (no toggles).
; -----------------------------------------------------------------------------
_sf_sin:
    .a16
    .i16
    lda API_BLOCK_BASE + $00        ; angle
    and #$00FF                      ; low byte = LUT index
    asl a                           ; x2 for word indexing
    tax
    lda f:math_sin_lut, x           ; 8.8 result
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

; -----------------------------------------------------------------------------
; _sf_cos — cosine of an angle. In: API+0 = angle (low byte). Out: A = 8.8
; signed: _sf_cos(0) = $0100 (+1.0), _sf_cos(128) = $FF00 (-1.0). The shared
; LUT stores the negated sine, so cos(x) = -lut[(x + 64) & 255]. Clobbers A, X.
; WIDTH-RISK: A16/I16 throughout (no toggles).
; -----------------------------------------------------------------------------
_sf_cos:
    .a16
    .i16
    lda API_BLOCK_BASE + $00        ; angle
    clc
    adc #$0040                      ; + quarter turn
    and #$00FF                      ; wrap to LUT index
    asl a
    tax
    lda f:math_sin_lut, x           ; -sin(x + 1/4 turn)
    eor #$FFFF                      ; negate -> cos(x)
    inc a
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

; -----------------------------------------------------------------------------
; _sf_sqrt — square root with linear interpolation. In: API+0 = x (8.8;
; negative returns 0). Out: A = sqrt(x) in 8.8 ($0400 -> $0200). LUT holds
; sqrt(n) for the integer part; the fraction interpolates toward sqrt(n+1)
; via the hardware 8x8 multiplier. Clobbers A, X; scratch ES_ATAN2_DX.
; WIDTH-RISK: toggles A8 for the hardware-multiply writes; both exits A16.
; -----------------------------------------------------------------------------
_sf_sqrt:
    .a16
    .i16
    lda API_BLOCK_BASE + $00
    bmi @sqrt_neg                   ; negative -> 0

    pha                             ; keep the full 8.8 value for the fraction
    xba                             ; integer part -> low byte
    and #$00FF
    cmp #$00FF                      ; cap at 254 so n+1 lookup stays in range
    bcc @sqrt_idx_ok
    lda #$00FE
@sqrt_idx_ok:
    .a16
    asl a
    tax
    lda f:math_sqrt_lut, x          ; sqrt(n)
    sta ENGINE_A0
    lda f:math_sqrt_lut + 2, x      ; sqrt(n+1)
    sec
    sbc ENGINE_A0                   ; delta
    sta ES_ATAN2_DX                 ; transient scratch (delta, < $0100)

    pla                             ; the 8.8 input again
    and #$00FF                      ; fraction byte

    sep #$20
    .a8
    sta $4202                       ; multiplicand = fraction
    lda ES_ATAN2_DX
    sta $4203                       ; multiplier = delta low byte
    nop                             ; 8 machine cycles before reading RDMPY
    nop
    nop
    nop
    rep #$20
    .a16
    lda $4216                       ; fraction * delta
    xba                             ; / 256
    and #$00FF
    clc
    adc ENGINE_A0                   ; sqrt(n) + interpolated step
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

@sqrt_neg:
    .a16
    lda #$0000
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

; -----------------------------------------------------------------------------
; _sf_atan2 — full-circle arctangent by octant decomposition. In: API+0 = dx
; (8.8 signed), API+4 = dy (8.8 signed). Out: A = angle 0..255 (= 0..1 turn):
; atan2(+1, 0) = 0, atan2(0, +1) = $40, atan2(-1, 0) = $80, atan2(0, -1) =
; $C0 — the convention pair of the negated-sine LUT. (0, 0) returns 0.
; Mechanism: classify the octant from the signs + |dy|>|dx|, compute
; ratio = min/max * 64 via the hardware divider, look up the base angle
; (0..32) in math_atan_lut, then mirror into the octant. Clobbers A, X;
; scratch ES_ATAN2_* ($B0-$BC).
; WIDTH-RISK: toggles A8 around the octant-flag bytes, the hardware-divider
; write, and the byte-wide LUT read; every multi-path label annotated; all
; exits A16.
; -----------------------------------------------------------------------------
_sf_atan2:
    .a16
    .i16
    lda API_BLOCK_BASE + $00        ; dx
    sta ES_ATAN2_DX
    lda API_BLOCK_BASE + $04        ; dy
    sta ES_ATAN2_DY

    lda ES_ATAN2_DX                 ; (0,0) -> 0
    ora ES_ATAN2_DY
    bne @atan2_nonzero
    jmp @atan2_zero
@atan2_nonzero:
    .a16

    ; |dx|, |dy|
    lda ES_ATAN2_DX
    bpl @atan2_dx_pos
    eor #$FFFF
    inc a
@atan2_dx_pos:
    .a16
    sta ES_ATAN2_ABS_DX

    lda ES_ATAN2_DY
    bpl @atan2_dy_pos
    eor #$FFFF
    inc a
@atan2_dy_pos:
    .a16
    sta ES_ATAN2_ABS_DY

    ; Octant flags: bit0 = dy < 0, bit1 = dx < 0, bit2 = |dy| > |dx| (steep)
    stz ES_ATAN2_OCTANT

    lda ES_ATAN2_DY
    bpl @atan2_dy_sign_ok
    sep #$20
    .a8
    inc ES_ATAN2_OCTANT
    rep #$20
    .a16
@atan2_dy_sign_ok:
    .a16
    lda ES_ATAN2_DX
    bpl @atan2_dx_sign_ok
    lda ES_ATAN2_OCTANT
    ora #$0002
    sta ES_ATAN2_OCTANT
@atan2_dx_sign_ok:
    .a16
    lda ES_ATAN2_ABS_DY
    cmp ES_ATAN2_ABS_DX
    bcc @atan2_not_steep
    beq @atan2_not_steep
    lda ES_ATAN2_OCTANT
    ora #$0004
    sta ES_ATAN2_OCTANT
@atan2_not_steep:
    .a16

    ; ratio = min(|dx|,|dy|) * 64 / max(|dx|,|dy|) -> LUT index 0..64
    lda ES_ATAN2_OCTANT
    and #$0004
    beq @atan2_use_dy_over_dx
    lda ES_ATAN2_ABS_DX             ; steep: numerator = |dx|
    bra @atan2_do_ratio
@atan2_use_dy_over_dx:
    .a16
    lda ES_ATAN2_ABS_DY             ; shallow: numerator = |dy|
@atan2_do_ratio:
    .a16
    asl a                           ; * 64
    asl a
    asl a
    asl a
    asl a
    asl a
    sta ES_ATAN2_BASE

    lda ES_ATAN2_OCTANT
    and #$0004
    beq @atan2_div_by_dx
    lda ES_ATAN2_ABS_DY             ; steep: divisor = |dy|
    bra @atan2_do_div
@atan2_div_by_dx:
    .a16
    lda ES_ATAN2_ABS_DX
@atan2_do_div:
    .a16
    bne @atan2_div_nonzero
    jmp @atan2_zero
@atan2_div_nonzero:
    .a16
    sta ES_ATAN2_DIVISOR

    lda ES_ATAN2_BASE               ; dividend
    sta $4204                       ; WRDIVL/H
    sep #$20
    .a8
    lda ES_ATAN2_DIVISOR            ; divisor low byte (8-bit hw divide)
    bne @atan2_hw_div_ok
    lda #$01
@atan2_hw_div_ok:
    .a8
    sta $4206                       ; WRDIVB — 16 machine cycles to settle
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    rep #$20
    .a16
    lda $4214                       ; quotient

    cmp #$0041                      ; clamp to 0..64
    bcc @atan2_idx_ok
    lda #$0040
@atan2_idx_ok:
    .a16
    tax
    sep #$20
    .a8
    lda f:math_atan_lut, x          ; base angle, 0..32 (256ths of a turn)
    rep #$20
    .a16
    and #$00FF
    sta ES_ATAN2_BASE

    ; Mirror the base angle into the octant (flags: steep|dx_neg|dy_neg)
    lda ES_ATAN2_OCTANT
    and #$0007
    asl a
    tax
    jmp (@atan2_octant_tbl, x)

@atan2_octant_tbl:
    .word @atan2_oct0               ; 000: dx>0, dy>=0, shallow ->       base
    .word @atan2_oct1               ; 001: dx>0, dy<0,  shallow -> 256 - base
    .word @atan2_oct2               ; 010: dx<0, dy>=0, shallow -> 128 - base
    .word @atan2_oct3               ; 011: dx<0, dy<0,  shallow -> 128 + base
    .word @atan2_oct4               ; 100: dx>0, dy>=0, steep   ->  64 - base
    .word @atan2_oct5               ; 101: dx>0, dy<0,  steep   -> 192 + base
    .word @atan2_oct6               ; 110: dx<0, dy>=0, steep   ->  64 + base
    .word @atan2_oct7               ; 111: dx<0, dy<0,  steep   -> 192 - base

@atan2_oct0:
    .a16
    lda ES_ATAN2_BASE
    bra @atan2_store
@atan2_oct1:
    .a16
    lda #$0100
    sec
    sbc ES_ATAN2_BASE
    bra @atan2_store
@atan2_oct2:
    .a16
    lda #$0080
    sec
    sbc ES_ATAN2_BASE
    bra @atan2_store
@atan2_oct3:
    .a16
    lda #$0080
    clc
    adc ES_ATAN2_BASE
    bra @atan2_store
@atan2_oct4:
    .a16
    lda #$0040
    sec
    sbc ES_ATAN2_BASE
    bra @atan2_store
@atan2_oct5:
    .a16
    lda #$00C0
    clc
    adc ES_ATAN2_BASE
    bra @atan2_store
@atan2_oct6:
    .a16
    lda #$0040
    clc
    adc ES_ATAN2_BASE
    bra @atan2_store
@atan2_oct7:
    .a16
    lda #$00C0
    sec
    sbc ES_ATAN2_BASE
@atan2_store:
    .a16
    and #$00FF                      ; wrap to 0..255
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

@atan2_zero:
    .a16
    lda #$0000
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

; -----------------------------------------------------------------------------
; Random numbers — 16-bit Galois feedback shift register.
; -----------------------------------------------------------------------------
; State at WRAM $053E-$053F (SF_RND_STATE, claimed macro-scratch slot).
; Step: shift right; when a 1 falls out, fold the tap mask $B400 back in
; (taps 16,14,13,11 — full 65535-step period). State must never be zero:
; _sf_srand substitutes a fixed nonzero seed for 0.

SF_RND_STATE = $053E            ; 2 bytes, between sf_physics scratch ($053D)
                                ; and the engine DMA staging ($0540)

; _sf_srand — seed the generator. In: API+0 = seed (0 -> $ACE1). Clobbers A.
; WIDTH-RISK: A16/I16 throughout (no toggles).
_sf_srand:
    .a16
    .i16
    lda API_BLOCK_BASE + $00
    bne @srand_store
    lda #$ACE1                      ; zero is the shift register's fixed point
@srand_store:
    .a16
    sta a:SF_RND_STATE
    rts

; _sf_rnd — uniform draw. In: API+0 = max (1..256; a low byte of 0 means
; 256). Out: A = 0..max-1. Mechanism: step the shift register, take its high
; byte r (0..255), result = (r * max) >> 8 via the hardware multiplier —
; constant time, no divide. Distribution note: exactly uniform when max
; divides 256; otherwise buckets differ by at most one part in 256 (the
; multiply-shift spreads the remainder; fine for gameplay, not for dice-roll
; fairness audits). Clobbers A.
; WIDTH-RISK: toggles A8 for the multiplier writes; both exits A16; every
; multi-path label annotated.
_sf_rnd:
    .a16
    .i16
    ; step the shift register
    lda a:SF_RND_STATE
    lsr a
    bcc @rnd_no_tap
    eor #$B400                      ; fold the tap mask back in
@rnd_no_tap:
    .a16
    sta a:SF_RND_STATE

    sep #$20
    .a8
    lda a:SF_RND_STATE + 1          ; r = high byte (0..255)
    sta $4202
    lda API_BLOCK_BASE + $00        ; max low byte
    beq @rnd_max256                 ; low byte 0 = 256 -> return r directly
    sta $4203                       ; start 8x8 multiply
    nop                             ; 8 machine cycles before reading RDMPY
    nop
    nop
    nop
    rep #$20
    .a16
    lda $4216                       ; r * max
    xba                             ; >> 8 -> 0..max-1
    and #$00FF
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

@rnd_max256:
    .a8
    lda a:SF_RND_STATE + 1
    rep #$20
    .a16
    and #$00FF
    sta ENGINE_A0
    stz ENGINE_A0 + 2
    rts

; --- the generated tables (regen: PYTHONPATH=. python3 tools/gen_math_luts.py) ---
.include "sf_math_luts.inc"

.endif ; SF_MATH_DATA_INC
