; =============================================================================
; mode7_diz_math.asm — Dizworld Math Routines (ported from dizworld.s)
; =============================================================================
; Ported from: https://github.com/bbbradsmith/SNES_stuff/blob/main/dizworld/dizworld.s
; Author: Brad Smith (rainwarrior)
;
; THIRD-PARTY CONTENT — MODIFIED TRANSLITERATION, CC BY 4.0.
; ATTRIBUTION REQUIRED.
;   Author:  (c) Brad Smith (rainwarrior) — https://rainwarrior.ca
;   Licence: Creative Commons Attribution 4.0 International (CC BY 4.0)
;            https://creativecommons.org/licenses/by/4.0/
; The six routines below are modified transliterations of Brad's math
; section (DP scratch remapped; `sincos` reads the 512-entry sine LUT
; instead of Brad's 256-entry table). A ROM that links this file must credit
; Brad Smith. See NOTICE and docs/92_provenance_audit.md §4.
;
; Routines:
;   umul16     — 16x16 unsigned → 32-bit product (HW multiply)
;   smul16     — 16x16 signed multiply
;   smul16_u8  — 16x8 signed × unsigned multiply
;   udiv32     — 32÷16 unsigned → quotient + remainder (software long division)
;   sign       — sign-extension helper
;   sincos     — angle lookup using SuperForge's mode7_sin_lut
;
; IMPORTANT: umul16, smul16, smul16_u8, udiv32 expect 8-bit index registers (.i8).
; The caller must sep #$10 / .i8 before calling and rep #$10 / .i16 after.
; sincos and sign expect .a16 .i16.
;
; ZP allocation: $B0-$CF (engine cache area)
;
; Cross-ref:
;   engine/mode7_sin_lut.inc (512-entry sine LUT, 1.7.8 signed)
; the specification
; =============================================================================

; Must NOT have .p816/.smart — this file is .include'd into a parent

; === Zero Page Variables ($B0-$CF) ===
math_a   = $B0   ; 4 bytes ($B0-$B3)
math_b   = $B4   ; 4 bytes ($B4-$B7)
math_p   = $B8   ; 8 bytes ($B8-$BF) — product/quotient result
math_r   = $C0   ; 8 bytes ($C0-$C7) — remainder
cosa     = $C8   ; 2 bytes ($C8-$C9)
sina     = $CA   ; 2 bytes ($CA-$CB)
diz_temp = $CC   ; 2 bytes ($CC-$CD)

; =============================================================================
; umul16 — 16x16 unsigned multiply → 32-bit product
; =============================================================================
; Input:  math_a (16-bit), math_b (16-bit) — zero page
; Output: math_p (32-bit) — zero page
; Clobbers: A, X, Y
; Mode: .a16 .i8, DB=0
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
; Input:  math_a (16-bit signed), math_b (16-bit signed) — zero page
; Output: math_p (32-bit signed) — zero page
; Clobbers: A, X, Y
; Mode: .a16 .i8, DB=0
;
; Algorithm: unsigned multiply + sign correction.
; If A's high byte >= $80 (negative), subtract B from upper product.
; If B's high byte >= $80 (negative), subtract A from upper product.
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
; smul16_u8 — 16-bit signed × 8-bit unsigned multiply → 24-bit result
; =============================================================================
; Input:  math_a (16-bit signed), math_b (8-bit unsigned) — zero page
; Output: math_p (24-bit signed, bytes 0-2) — zero page
; Clobbers: A, X, Y
; Mode: .a16 .i8, DB=0
;
; If math_a is negative (high byte >= $80), a correction term is applied
; by multiplying the sign extension byte ($FF) by math_b and adding.
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
    bcc @smul16_u8_done ; if sign bit clear, no correction needed
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
; udiv32 — 32÷16 unsigned division → quotient + remainder
; =============================================================================
; Input:  math_a (32-bit dividend, bytes 0-3), math_b (16-bit divisor, bytes 0-1)
; Output: math_p (32-bit quotient, bytes 0-3), math_r (16-bit remainder, bytes 0-1)
; Clobbers: A, X
; Mode: .a16 .i8
;
; Uses software long division (32 iterations).
; math_b+2 must be zero for 32÷16 division.
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
@loop:
    rol
    rol z:math_r+2
    cmp z:math_b+0
    pha
    lda z:math_r+2
    sbc z:math_b+2
    bcc @no_sub
        sta z:math_r+2
        pla
        sbc z:math_b+0
        sec
        bra @cont
@no_sub:
        pla
@cont:
    rol z:math_p+0
    rol z:math_p+2
    dex
    bne @loop
    sta z:math_r+0
    rts


; =============================================================================
; sign — Sign extension helper
; =============================================================================
; Input:  A (16-bit value)
; Output: A = $0000 if positive, $FFFF if negative
; Preserves: flags (via PHP/PLP)
; Mode: .a16
; =============================================================================
sign:
    .a16
    php
    cmp #$8000
    bcs @negative
        lda #0
        plp
        rts
@negative:
        lda #$FFFF
        plp
        rts


; =============================================================================
; sincos — Angle → cos/sin lookup using SuperForge's mode7_sin_lut
; =============================================================================
; Input:  A = angle (0-255, Dizworld 256-step convention), .a16 .i16 mode
; Output: cosa (ZP), sina (ZP) — 1.7.8 signed fixed-point
; Clobbers: A, X, diz_temp
;
; Conversion from Dizworld 256-step angles to SuperForge 512-entry LUT:
;   1. Mask to byte range: and #$00FF
;   2. First ASL: doubles angle to 512-step entry index (0-510, even)
;   3. Cosine offset: +128 entries (quarter period in 512-step space)
;   4. Second ASL: converts entry index to byte offset (x2 for 16-bit entries)
;
; Without the second ASL, angle=64 would index entry 64 ($00B5 ≈ sin 45°)
; instead of entry 128 ($0100 = sin 90°).
;
; Cross-ref: engine/mode7_sin_lut.inc, plan.md an earlier stage compatibility note
; =============================================================================
sincos:
    .a16
    .i16
    and #$00FF          ; mask to byte
    asl                 ; double: 256-step → 512-step entry index
    sta diz_temp        ; save sin entry index
    clc
    adc #128            ; cos = sin + quarter period (128 entries)
    and #$01FE          ; wrap to valid range (must be even for word alignment)
    asl                 ; entry index → byte offset (x2 for 16-bit entries)
    tax
    lda f:mode7_sin_lut, x
    sta cosa
    lda diz_temp        ; recover sin entry index
    asl                 ; entry index → byte offset (x2)
    tax
    lda f:mode7_sin_lut, x
    sta sina
    rts
