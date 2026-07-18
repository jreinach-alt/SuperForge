; =============================================================================
; mode7_math.asm -- Mode 7 Math Routines
; =============================================================================
; Fast multiply / divide / sincos routines for Mode 7 affine transforms.
;
; Two groups:
;
; (1) Phase 8A routines using the SNES hardware multiplier at $4202-$4217.
;     DP scratch: $90-$96. Original SuperForge code (no third-party derivation).
;       lut_multiply_8bit   -- 8x8 unsigned multiply
;       lut_multiply_16bit  -- 16x16 signed multiply (returns bits 23:8)
;
; (2) Phase 16-0a Brad-port helpers. DP scratch: $B0-$CD.
;     Used by engine/mode7_hdma.asm's pv_rebuild / pv_set_origin.
;       umul16     -- 16x16 unsigned multiply -> 32-bit product
;       smul16     -- 16x16 signed multiply   -> 32-bit signed product
;       smul16_u8  -- 16-bit signed x 8-bit unsigned -> 24-bit signed
;       udiv32     -- 32/16 unsigned division -> 32-bit quotient + 16-bit remainder
;       sign       -- sign-extend A (returns $0000 or $FFFF)
;       sincos     -- angle (u8) -> cosa + sina via engine/mode7_sin_lut.inc
;
;     Brad-port helpers expect .i8 (umul16/smul16/smul16_u8/udiv32) or
;     .i16 (sincos/sign). See per-routine mode headers.
;
;     Third-party derivation — group (2) only:
;       Source:   https://github.com/bbbradsmith/SNES_stuff/blob/main/dizworld/dizworld.s
;       Author:   Brad Smith (rainwarrior) — https://rainwarrior.ca
;       License:  Creative Commons Attribution 4.0 International (CC BY 4.0)
;                 https://creativecommons.org/licenses/by/4.0/
;       Notice:   Modified transliteration via tests/phase8/mode7_diz_math.asm
;                 (an earlier Phase 8 port of the same routines). Algorithm is
;                 unchanged; DP scratch slot assignment, comment headers, and
;                 engine-integration glue are SuperForge additions.
;       See docs/THIRDPARTY.md for consolidated attribution.
;
; Cross-ref:
;   engine/mode7_sin_lut.inc (sine LUT, 512 entries, 1.7.8 signed)
;   engine/mode7_perspective_lut.inc (legacy perspective LUT — pre-16-0a)
;   tests/phase8/mode7_diz_math.asm (intermediate transliteration of group 2)
;   docs/superforge_cycle_budget_v0.1.md (cycle budget)
; =============================================================================

; Must NOT have .p816/.smart -- this file is .include'd into a parent that
; sets them.  The parent must have .p816 and .smart active.

; === SNES Hardware Multiply Registers ===
; IMPORTANT: These routines use long addressing (f:$00xxxx) to access hardware
; registers, making them safe to call from any Data Bank (including DB=$7E
; during Mode 7 HDMA table generation).
WRMPYA  = $4202     ; Multiplicand (8-bit, write)
WRMPYB  = $4203     ; Multiplier (8-bit, write -- starts multiply)
RDMPYL  = $4216     ; Product low byte (16-bit result, read)
RDMPYH  = $4217     ; Product high byte (16-bit result, read)


; =============================================================================
; lut_multiply_8bit -- Fast 8x8 unsigned multiply using hardware registers
; =============================================================================
; Performs: result = A * X  (8-bit unsigned x 8-bit unsigned)
;
; Input:
;   A = multiplicand (8-bit, low byte used in 8-bit mode)
;   X = multiplier (8-bit, low byte used)
;
; Output:
;   A = 16-bit unsigned product (in 16-bit accumulator mode)
;   Carry: undefined
;   X, Y: preserved
;
; Timing: ~20 cycles (write + 2 NOP + read)
;
; Precondition: Caller must be in 16-bit index mode (.i16).
;               Accumulator mode is managed internally.
; =============================================================================
lut_multiply_8bit:
    sep #$20            ; 8-bit A
    .a8
    sta f:WRMPYA        ; write multiplicand (long addr: DB-independent)
    txa                 ; get multiplier from X
    sta f:WRMPYB        ; write multiplier (starts multiply)
    ; --- 8 master cycle delay required before reading result ---
    nop                 ; 2 cycles (FastROM)
    nop                 ; 2 cycles (FastROM)
    ; Additional NOPs for safety margin on real hardware timing
    nop                 ; 2 cycles
    nop                 ; 2 cycles
    rep #$20            ; 16-bit A
    .a16
    lda f:RDMPYL        ; read 16-bit result (low at $4216, high at $4217)
    rts


; =============================================================================
; lut_multiply_16bit -- 16x16 signed multiply, return bits 23:8
; =============================================================================
; Performs a full 16x16 signed multiply using three 8x8 hardware multiplies
; and returns bits 23:8 of the 32-bit product (effectively a fixed-point
; multiply where both inputs are 8.8 and the result is 8.8).
;
; Algorithm:
;   Given A = Ah:Al (16-bit), X = Xh:Xl (16-bit, signed)
;   Product = Al*Xl + (Al*Xh)<<8 + (Ah*Xl)<<8 + (Ah*Xh)<<16
;   We need bits 23:8 = high byte of (Al*Xl) + low byte of (Al*Xh + Ah*Xl)
;                      + (Ah*Xh)<<8 + carries
;
;   Simplified for fixed-point 8.8 result:
;     result = (Al*Xl >> 8) + Al*Xh + Ah*Xl + (Ah*Xh << 8)
;
;   But since we want bits 23:8, we compute:
;     partial1 = Al * Xl   -> take high byte (bits 15:8)
;     partial2 = Al * Xh   -> take full 16 bits (contributes to bits 23:8)
;     partial3 = Ah * Xl   -> take full 16 bits (contributes to bits 23:8)
;     partial4 = Ah * Xh   -> shift left 8, add (contributes to bits 31:16)
;     result = (partial1 >> 8) + partial2 + partial3 + (partial4 << 8)
;
;   For signed multiply: if X is negative, negate X before multiply,
;   then negate the result.
;
; Input:
;   A = scale value (16-bit unsigned, typically from perspective LUT)
;   X = sin/cos value (16-bit signed, from sine LUT)
;
; Output:
;   A = bits 23:8 of 32-bit product (16-bit, signed)
;   X, Y: clobbered
;
; Uses scratch: $00-$09 (direct page scratch area)
;   $00: A low byte (Al)
;   $01: A high byte (Ah)
;   $02: X low byte (Xl) -- after possible negation
;   $03: X high byte (Xh) -- after possible negation
;   $04-$05: accumulator for partial sums (16-bit)
;   $06: sign flag (0 = positive, 1 = negative)
;
; Timing: ~80-100 cycles (3 HW multiplies + bookkeeping)
;
; Precondition: .a16 .i16 mode
; =============================================================================

; Direct page scratch offsets (use low DP area $90-$9F for engine scratch)
M7_SCRATCH_AL    = $90
M7_SCRATCH_AH    = $91
M7_SCRATCH_XL    = $92
M7_SCRATCH_XH    = $93
M7_SCRATCH_SUM   = $94   ; 2 bytes
M7_SCRATCH_SIGN  = $96

lut_multiply_16bit:
    .a16
    .i16
    ; --- Save inputs and determine sign ---
    sta M7_SCRATCH_SUM      ; temporarily store A (scale)
    stz M7_SCRATCH_SIGN     ; assume positive

    ; Extract A bytes
    sep #$20
    .a8
    lda M7_SCRATCH_SUM      ; Al (low byte of scale)
    sta M7_SCRATCH_AL
    lda M7_SCRATCH_SUM + 1  ; Ah (high byte of scale)
    sta M7_SCRATCH_AH

    ; Check if X is negative
    rep #$20
    .a16
    txa
    bpl @x_positive
    ; X is negative -- negate it and set sign flag
    eor #$FFFF
    inc a
    tax
    lda #$0001
    sta M7_SCRATCH_SIGN
@x_positive:
    ; Extract X bytes (now guaranteed positive)
    ; Must do TXA in 16-bit mode so both bytes transfer correctly
    txa                     ; A = full 16-bit X (still in .a16)
    sep #$20
    .a8
    sta M7_SCRATCH_XL       ; Xl = low byte
    xba                     ; swap: A = high byte (was loaded by 16-bit TXA)
    sta M7_SCRATCH_XH       ; Xh = high byte

    ; === Partial product 1: Al * Xl (take high byte = bits 15:8) ===
    lda M7_SCRATCH_AL
    sta f:WRMPYA
    lda M7_SCRATCH_XL
    sta f:WRMPYB
    nop
    nop
    nop
    nop
    ; Read high byte of Al*Xl
    lda f:RDMPYH            ; bits 15:8 of Al*Xl
    rep #$20
    .a16
    and #$00FF
    sta M7_SCRATCH_SUM      ; running sum = high byte of Al*Xl

    ; === Partial product 2: Al * Xh (full 16-bit, add to sum) ===
    sep #$20
    .a8
    lda M7_SCRATCH_AL
    sta f:WRMPYA
    lda M7_SCRATCH_XH
    sta f:WRMPYB
    nop
    nop
    nop
    nop
    rep #$20
    .a16
    lda f:RDMPYL            ; full 16-bit result of Al*Xh
    clc
    adc M7_SCRATCH_SUM
    sta M7_SCRATCH_SUM

    ; === Partial product 3: Ah * Xl (full 16-bit, add to sum) ===
    sep #$20
    .a8
    lda M7_SCRATCH_AH
    sta f:WRMPYA
    lda M7_SCRATCH_XL
    sta f:WRMPYB
    nop
    nop
    nop
    nop
    rep #$20
    .a16
    lda f:RDMPYL            ; full 16-bit result of Ah*Xl
    clc
    adc M7_SCRATCH_SUM
    sta M7_SCRATCH_SUM

    ; === Partial product 4: Ah * Xh (shift left 8, add to sum) ===
    sep #$20
    .a8
    lda M7_SCRATCH_AH
    sta f:WRMPYA
    lda M7_SCRATCH_XH
    sta f:WRMPYB
    nop
    nop
    nop
    nop
    rep #$20
    .a16
    lda f:RDMPYL            ; full 16-bit result of Ah*Xh
    ; Shift left 8: we only need the low byte shifted into the high byte
    ; of our 16-bit sum.  Equivalent to: (result & $FF) << 8
    ; But also the high byte contributes to bits 31:24 which we discard.
    xba                     ; swap bytes: effectively << 8 for low byte
    and #$FF00              ; mask off the swapped low byte (was high byte)
    clc
    adc M7_SCRATCH_SUM
    ; A now holds bits 23:8 of the 32-bit product

    ; --- Apply sign ---
    ldx M7_SCRATCH_SIGN
    beq @done               ; if sign=0, result is positive, we're done
    ; Negate the result
    eor #$FFFF
    inc a
@done:
    rts


; =============================================================================
; =============================================================================
; Phase 16-0a Brad-port math helpers
; =============================================================================
; Transliterated from tests/phase8/mode7_diz_math.asm (which is itself a
; clean port of dizworld.s support routines by Brad Smith / rainwarrior).
;
; DP scratch allocation ($B0-$CD):
;   math_a   $B0  4 bytes — operand A (variable width)
;   math_b   $B4  4 bytes — operand B
;   math_p   $B8  8 bytes — product / quotient (up to 64-bit for udiv32)
;   math_r   $C0  8 bytes — remainder (udiv32)
;   cosa     $C8  2 bytes — current-frame cos(angle), signed 8.8
;   sina     $CA  2 bytes — current-frame sin(angle)
;   diz_temp $CC  2 bytes — scratch used by sincos
;
; These DP locations are used only during pv_rebuild execution (BUILD
; phase), when the game register file and API block are quiescent.
; No collision with lut_multiply_16bit's $90-$96 scratch.
; =============================================================================

; === Brad-port ZP aliases (local to this file's helpers) ===
; Using equates matching dizworld.s exactly so the helper bodies are
; character-by-character transcriptions of Brad's source.
math_a   = $B0   ; 4 bytes
math_b   = $B4   ; 4 bytes
math_p   = $B8   ; 8 bytes
math_r   = $C0   ; 8 bytes
cosa     = $C8   ; 2 bytes
sina     = $CA   ; 2 bytes
diz_temp = $CC   ; 2 bytes


; =============================================================================
; umul16 — 16x16 unsigned multiply → 32-bit product
; =============================================================================
; Correspondence: dizworld.s ~umul16 (Brad's support routines).
; Input:  math_a (u16), math_b (u16)
; Output: math_p (u32)
; Clobbers: A, X, Y
; Mode: .a16 .i8, DB=0 (hardware multiply registers accessed via a: which
;                       are bank-0 regardless of DB, but caller conventions
;                       expect DB=0 for surrounding code).
; =============================================================================
umul16:
    .a16
    .i8
    ldx z:math_a+0
    stx a:$4202
    ldy z:math_b+0
    sty a:$4203        ; a0 x b0 (A)
    ldx z:math_b+1
    stz z:math_p+2
    lda a:$4216
    stx a:$4203        ; a0 x b1 (B)
    sta z:math_p+0     ; 00AA
    ldx z:math_a+1
    lda a:$4216
    stx a:$4202
    sty a:$4203        ; a1 x b0 (C)
    clc
    adc z:math_p+1     ; 00AA + 0BB0
    ldy z:math_b+1
    adc a:$4216
    sty a:$4203        ; a1 x b1 (D)
    sta z:math_p+1     ; 00AA + 0BB0 + 0CC0
    lda z:math_p+2
    bcc :+
    adc #$00FF
:
    adc a:$4216
    sta z:math_p+2
    rts


; =============================================================================
; smul16 — 16x16 signed multiply → 32-bit signed product
; =============================================================================
; Correspondence: dizworld.s ~smul16.
; Algorithm: umul16 + sign correction for each negative operand.
; Input:  math_a (s16), math_b (s16)
; Output: math_p (s32)
; Clobbers: A, X, Y
; Mode: .a16 .i8, DB=0
; =============================================================================
smul16:
    .a16
    .i8
    jsr umul16
    cpx #$80
    bcc :+
        sbc z:math_b
    :
    cpy #$80
    bcc :+
        sbc z:math_a
    :
    sta z:math_p+2
    rts


; =============================================================================
; smul16_u8 — 16-bit signed × 8-bit unsigned → 24-bit signed product
; =============================================================================
; Correspondence: dizworld.s ~smul16_u8.
; Input:  math_a (s16), math_b (u8 in math_b+0, math_b+1..+3 ignored)
; Output: math_p bytes 0-2 (s24)
; Clobbers: A, X, Y
; Mode: .a16 .i8, DB=0
; =============================================================================
smul16_u8:
    .a16
    .i8
    ldx z:math_b
    stx a:$4202
    ldy z:math_a+0
    sty a:$4203        ; b x a0 (A)
    ldx z:math_a+1
    stz z:math_p+2
    lda a:$4216
    stx a:$4203        ; b x a1 (B)
    sta z:math_p+0     ; 0AA
    lda z:math_p+1
    clc
    adc a:$4216        ; 0AA + BB0
    sta z:math_p+1
    cpx #$80
    bcc @smul16_u8_done
        ldx #$FF
        stx a:$4203    ; b x $FF (sign extension correction)
        clc
        lda z:math_p+2
        adc a:$4216    ; 0AA + BB0 + C00
        sta z:math_p+2
        lda z:math_p+1
@smul16_u8_done:
    rts


; =============================================================================
; udiv32 — 32/16 unsigned division → 32-bit quotient + 16-bit remainder
; =============================================================================
; Correspondence: dizworld.s ~udiv32.
; Input:  math_a (u32 dividend, bytes 0-3), math_b (u16 divisor in bytes 0-1;
;         math_b+2 must be zero for valid 32/16 behavior)
; Output: math_p (u32 quotient), math_r (u16 remainder in bytes 0-1)
; Clobbers: A, X
; Mode: .a16 .i8
;
; Software long division via 32 iterations. Used by pv_rebuild to compute
; ZR0 = (1<<21) / pv_s0 and ZR1 = (1<<21) / pv_s1 with full precision.
; =============================================================================
udiv32:
    .a16
    .i8
    lda z:math_a+0
    asl
    sta z:math_p+0
    lda z:math_a+2
    rol
    sta z:math_p+2
    stz z:math_r+2
    lda #0
    ldx #32
@udiv32_loop:
    rol
    rol z:math_r+2
    cmp z:math_b+0
    pha
    lda z:math_r+2
    sbc z:math_b+2
    bcc @udiv32_no_sub
        sta z:math_r+2
        pla
        sbc z:math_b+0
        sec
        bra @udiv32_cont
@udiv32_no_sub:
        pla
@udiv32_cont:
    rol z:math_p+0
    rol z:math_p+2
    dex
    bne @udiv32_loop
    sta z:math_r+0
    rts


; =============================================================================
; sign — Sign-extension helper
; =============================================================================
; Correspondence: dizworld.s ~sign.
; Input:  A (16-bit value)
; Output: A = $0000 if positive (A < $8000), $FFFF if negative (A >= $8000)
; Preserves: flags via PHP/PLP (so caller's carry etc. are intact)
; Mode: .a16
; =============================================================================
sign:
    .a16
    php
    cmp #$8000
    bcs @sign_negative
        lda #0
        plp
        rts
@sign_negative:
        lda #$FFFF
        plp
        rts


; =============================================================================
; sincos — Angle (u8) → cos/sin pair
; =============================================================================
; Correspondence: dizworld.s ~sincos (adapted for SuperForge's 512-entry
; sine LUT — Brad used a 256-entry LUT; we double the index).
; Input:  A (8-bit angle in low byte, 0-255 = 0-360 degrees — Brad's
;         256-step convention)
; Output: cosa, sina (ZP $C8, $CA) — signed 1.7.8 fixed-point
; Clobbers: A, X, diz_temp
; Mode: .a16 .i16
;
; Index mapping (SuperForge LUT is 512 entries × 2 bytes):
;   1. Mask input to byte: and #$00FF
;   2. ASL: 256-step angle → 512-entry index (LUT is 2x wider than Brad's)
;   3. Cosine = sin offset by 128 entries (quarter period)
;   4. ASL: entry index → byte offset (2 bytes per entry)
; =============================================================================
sincos:
    .a16
    .i16
    and #$00FF          ; mask to byte
    asl                 ; double: 256-step → 512-entry index
    sta diz_temp        ; save sin entry index
    clc
    adc #128            ; cos = sin + quarter period (128 entries)
    and #$01FE          ; wrap to valid range (must be even for word alignment)
    asl                 ; entry index → byte offset (x2)
    tax
    lda f:sin_lut, x
    sta cosa
    lda diz_temp        ; recover sin entry index
    asl                 ; entry index → byte offset (x2)
    tax
    lda f:sin_lut, x
    sta sina
    rts
