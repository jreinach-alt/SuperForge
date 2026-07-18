; =============================================================================
; sf_math_luts.inc — generated lookup tables for the sf_math group
; =============================================================================
; GENERATED FILE — do not hand-edit. Regenerate with:
;   PYTHONPATH=. python3 tools/gen_math_luts.py
; (values from toolchain/math_lut.py; this file only freezes the bytes)
;
; Angle convention everywhere in the kit: 0..255 = one full turn.
; math_sin_lut stores the NEGATED sine in 8.8 signed, so:
;   math_sin_lut[0]   = $0000          math_sin_lut[64]  = $FF00 (-1.0)
;   math_sin_lut[128] = $0000          math_sin_lut[192] = $0100 (+1.0)
; cosine = -math_sin_lut[(i + 64) & 255]  (the runtime does the negate).
; math_sqrt_lut[n] = sqrt(n) in 8.8 (n = integer part of the 8.8 input).
; math_atan_lut[r] = atan(r/64) in 256ths of a turn (0..32), for the
; octant-decomposition arctangent.
; =============================================================================

math_sin_lut:
    .word $0000, $FFFA, $FFF3, $FFED, $FFE7, $FFE1, $FFDA, $FFD4
    .word $FFCE, $FFC8, $FFC2, $FFBC, $FFB6, $FFB0, $FFAA, $FFA4
    .word $FF9E, $FF98, $FF93, $FF8D, $FF87, $FF82, $FF7C, $FF77
    .word $FF72, $FF6D, $FF68, $FF63, $FF5E, $FF59, $FF54, $FF4F
    .word $FF4B, $FF47, $FF42, $FF3E, $FF3A, $FF36, $FF32, $FF2F
    .word $FF2B, $FF28, $FF24, $FF21, $FF1E, $FF1B, $FF19, $FF16
    .word $FF13, $FF11, $FF0F, $FF0D, $FF0B, $FF09, $FF08, $FF06
    .word $FF05, $FF04, $FF03, $FF02, $FF01, $FF01, $FF00, $FF00
    .word $FF00, $FF00, $FF00, $FF01, $FF01, $FF02, $FF03, $FF04
    .word $FF05, $FF06, $FF08, $FF09, $FF0B, $FF0D, $FF0F, $FF11
    .word $FF13, $FF16, $FF19, $FF1B, $FF1E, $FF21, $FF24, $FF28
    .word $FF2B, $FF2F, $FF32, $FF36, $FF3A, $FF3E, $FF42, $FF47
    .word $FF4B, $FF4F, $FF54, $FF59, $FF5E, $FF63, $FF68, $FF6D
    .word $FF72, $FF77, $FF7C, $FF82, $FF87, $FF8D, $FF93, $FF98
    .word $FF9E, $FFA4, $FFAA, $FFB0, $FFB6, $FFBC, $FFC2, $FFC8
    .word $FFCE, $FFD4, $FFDA, $FFE1, $FFE7, $FFED, $FFF3, $FFFA
    .word $0000, $0006, $000D, $0013, $0019, $001F, $0026, $002C
    .word $0032, $0038, $003E, $0044, $004A, $0050, $0056, $005C
    .word $0062, $0068, $006D, $0073, $0079, $007E, $0084, $0089
    .word $008E, $0093, $0098, $009D, $00A2, $00A7, $00AC, $00B1
    .word $00B5, $00B9, $00BE, $00C2, $00C6, $00CA, $00CE, $00D1
    .word $00D5, $00D8, $00DC, $00DF, $00E2, $00E5, $00E7, $00EA
    .word $00ED, $00EF, $00F1, $00F3, $00F5, $00F7, $00F8, $00FA
    .word $00FB, $00FC, $00FD, $00FE, $00FF, $00FF, $0100, $0100
    .word $0100, $0100, $0100, $00FF, $00FF, $00FE, $00FD, $00FC
    .word $00FB, $00FA, $00F8, $00F7, $00F5, $00F3, $00F1, $00EF
    .word $00ED, $00EA, $00E7, $00E5, $00E2, $00DF, $00DC, $00D8
    .word $00D5, $00D1, $00CE, $00CA, $00C6, $00C2, $00BE, $00B9
    .word $00B5, $00B1, $00AC, $00A7, $00A2, $009D, $0098, $0093
    .word $008E, $0089, $0084, $007E, $0079, $0073, $006D, $0068
    .word $0062, $005C, $0056, $0050, $004A, $0044, $003E, $0038
    .word $0032, $002C, $0026, $001F, $0019, $0013, $000D, $0006

math_sqrt_lut:
    .word $0000, $0100, $016A, $01BB, $0200, $023C, $0273, $02A5
    .word $02D4, $0300, $032A, $0351, $0377, $039B, $03BE, $03DF
    .word $0400, $0420, $043E, $045C, $0479, $0495, $04B1, $04CC
    .word $04E6, $0500, $0519, $0532, $054B, $0563, $057A, $0591
    .word $05A8, $05BF, $05D5, $05EB, $0600, $0615, $062A, $063F
    .word $0653, $0667, $067B, $068F, $06A2, $06B5, $06C8, $06DB
    .word $06EE, $0700, $0712, $0724, $0736, $0748, $0759, $076B
    .word $077C, $078D, $079E, $07AE, $07BF, $07CF, $07E0, $07F0
    .word $0800, $0810, $0820, $082F, $083F, $084E, $085E, $086D
    .word $087C, $088B, $089A, $08A9, $08B8, $08C6, $08D5, $08E3
    .word $08F2, $0900, $090E, $091C, $092A, $0938, $0946, $0954
    .word $0961, $096F, $097D, $098A, $0997, $09A5, $09B2, $09BF
    .word $09CC, $09D9, $09E6, $09F3, $0A00, $0A0D, $0A19, $0A26
    .word $0A33, $0A3F, $0A4C, $0A58, $0A64, $0A71, $0A7D, $0A89
    .word $0A95, $0AA1, $0AAD, $0AB9, $0AC5, $0AD1, $0ADD, $0AE9
    .word $0AF4, $0B00, $0B0C, $0B17, $0B23, $0B2E, $0B3A, $0B45
    .word $0B50, $0B5C, $0B67, $0B72, $0B7D, $0B88, $0B93, $0B9E
    .word $0BA9, $0BB4, $0BBF, $0BCA, $0BD5, $0BE0, $0BEB, $0BF5
    .word $0C00, $0C0B, $0C15, $0C20, $0C2A, $0C35, $0C3F, $0C4A
    .word $0C54, $0C5F, $0C69, $0C73, $0C7D, $0C88, $0C92, $0C9C
    .word $0CA6, $0CB0, $0CBA, $0CC4, $0CCE, $0CD8, $0CE2, $0CEC
    .word $0CF6, $0D00, $0D0A, $0D14, $0D1D, $0D27, $0D31, $0D3B
    .word $0D44, $0D4E, $0D57, $0D61, $0D6B, $0D74, $0D7E, $0D87
    .word $0D91, $0D9A, $0DA3, $0DAD, $0DB6, $0DBF, $0DC9, $0DD2
    .word $0DDB, $0DE4, $0DEE, $0DF7, $0E00, $0E09, $0E12, $0E1B
    .word $0E24, $0E2D, $0E36, $0E3F, $0E48, $0E51, $0E5A, $0E63
    .word $0E6C, $0E75, $0E7E, $0E87, $0E8F, $0E98, $0EA1, $0EAA
    .word $0EB2, $0EBB, $0EC4, $0ECC, $0ED5, $0EDE, $0EE6, $0EEF
    .word $0EF7, $0F00, $0F09, $0F11, $0F1A, $0F22, $0F2A, $0F33
    .word $0F3B, $0F44, $0F4C, $0F54, $0F5D, $0F65, $0F6D, $0F76
    .word $0F7E, $0F86, $0F8E, $0F97, $0F9F, $0FA7, $0FAF, $0FB7
    .word $0FBF, $0FC8, $0FD0, $0FD8, $0FE0, $0FE8, $0FF0, $0FF8

math_atan_lut:
    .byte $00, $01, $01, $02, $03, $03, $04, $04, $05, $06, $06, $07, $08, $08, $09, $09
    .byte $0A, $0B, $0B, $0C, $0C, $0D, $0D, $0E, $0F, $0F, $10, $10, $11, $11, $12, $12
    .byte $13, $13, $14, $14, $15, $15, $16, $16, $17, $17, $18, $18, $19, $19, $19, $1A
    .byte $1A, $1B, $1B, $1B, $1C, $1C, $1D, $1D, $1D, $1E, $1E, $1E, $1F, $1F, $1F, $20
    .byte $20
