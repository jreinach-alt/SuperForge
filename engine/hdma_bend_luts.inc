; =============================================================================
; hdma_bend_luts.inc — curve LUTs for the HDMA bend / tunnel builder
; =============================================================================
; GENERATED FILE — do not hand-edit. Regenerate with:
;   PYTHONPATH=. python3 tools/gen_bend_luts.py
; (values from toolchain/math_lut.py; this file only freezes the bytes)
;
; Signed bytes, -127..+127, stored as raw two's-complement ($80..$FF =
; negative). hdma_build_hofs_curve reads one per scanline index and its bit-7
; test recovers magnitude + sign before scaling by amplitude / 128.
;   _hdma_curve_sine     one full sine period (DERIVED from the kit 8.8 sine
;                        SoT generate_sin_lut): [0]=0 [64]=+127 [128]=0
;                        [192]=-127. Rolls with phase -> tunnel.
;   _hdma_curve_parabola curved horizon symmetric about scanline 112: 0 at
;                        the centre, +127 at the top & bottom edges; indices
;                        past 224 clamp to the edge so a phase roll stays bounded.
;   _hdma_curve_horizon  v1.2-R V-axis (BGnVOFS) RECIPROCAL / 1-over-z
;                        perspective (SIGNED, -127..+127). Maps each ground
;                        scanline to a BOUNDED source row src = horizon +
;                        span*d/(d+tau), d = scanline - horizon; offset = src -
;                        scanline. Steepest AT the horizon (top) so rows bunch
;                        DRAMATICALLY there (>=4x vs foreground), saturating
;                        toward the bottom — a barrel / perspective horizon.
;                        src stays < 256 so the field never wraps into the sky
;                        (clean render). Replaces the old quadratic ramp (~1.3x).
;                        Compressed end at the TOP (correct direction).
; =============================================================================

_hdma_curve_sine:
    .byte $00, $03, $06, $09, $0C, $0F, $13, $16
    .byte $19, $1C, $1F, $22, $25, $28, $2B, $2E
    .byte $31, $34, $36, $39, $3C, $3F, $41, $44
    .byte $46, $49, $4B, $4E, $50, $53, $55, $58
    .byte $5A, $5C, $5E, $60, $62, $64, $66, $68
    .byte $6A, $6B, $6D, $6F, $70, $72, $73, $74
    .byte $76, $77, $78, $79, $7A, $7B, $7B, $7C
    .byte $7D, $7D, $7E, $7E, $7F, $7F, $7F, $7F
    .byte $7F, $7F, $7F, $7F, $7F, $7E, $7E, $7D
    .byte $7D, $7C, $7B, $7B, $7A, $79, $78, $77
    .byte $76, $74, $73, $72, $70, $6F, $6D, $6B
    .byte $6A, $68, $66, $64, $62, $60, $5E, $5C
    .byte $5A, $58, $55, $53, $50, $4E, $4B, $49
    .byte $46, $44, $41, $3F, $3C, $39, $36, $34
    .byte $31, $2E, $2B, $28, $25, $22, $1F, $1C
    .byte $19, $16, $13, $0F, $0C, $09, $06, $03
    .byte $00, $FD, $FA, $F7, $F4, $F1, $ED, $EA
    .byte $E7, $E4, $E1, $DE, $DB, $D8, $D5, $D2
    .byte $CF, $CC, $CA, $C7, $C4, $C1, $BF, $BC
    .byte $BA, $B7, $B5, $B2, $B0, $AD, $AB, $A8
    .byte $A6, $A4, $A2, $A0, $9E, $9C, $9A, $98
    .byte $96, $95, $93, $91, $90, $8E, $8D, $8C
    .byte $8A, $89, $88, $87, $86, $85, $85, $84
    .byte $83, $83, $82, $82, $81, $81, $81, $81
    .byte $81, $81, $81, $81, $81, $82, $82, $83
    .byte $83, $84, $85, $85, $86, $87, $88, $89
    .byte $8A, $8C, $8D, $8E, $90, $91, $93, $95
    .byte $96, $98, $9A, $9C, $9E, $A0, $A2, $A4
    .byte $A6, $A8, $AB, $AD, $B0, $B2, $B5, $B7
    .byte $BA, $BC, $BF, $C1, $C4, $C7, $CA, $CC
    .byte $CF, $D2, $D5, $D8, $DB, $DE, $E1, $E4
    .byte $E7, $EA, $ED, $F1, $F4, $F7, $FA, $FD

_hdma_curve_parabola:
    .byte $7F, $7D, $7B, $78, $76, $74, $72, $70
    .byte $6E, $6B, $69, $67, $65, $63, $61, $5F
    .byte $5D, $5B, $59, $58, $56, $54, $52, $50
    .byte $4E, $4D, $4B, $49, $47, $46, $44, $42
    .byte $41, $3F, $3E, $3C, $3A, $39, $37, $36
    .byte $34, $33, $32, $30, $2F, $2D, $2C, $2B
    .byte $29, $28, $27, $26, $24, $23, $22, $21
    .byte $20, $1F, $1E, $1C, $1B, $1A, $19, $18
    .byte $17, $16, $15, $15, $14, $13, $12, $11
    .byte $10, $0F, $0F, $0E, $0D, $0C, $0C, $0B
    .byte $0A, $0A, $09, $09, $08, $07, $07, $06
    .byte $06, $05, $05, $04, $04, $04, $03, $03
    .byte $03, $02, $02, $02, $01, $01, $01, $01
    .byte $01, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $01, $01, $01, $01, $01, $02, $02, $02
    .byte $03, $03, $03, $04, $04, $04, $05, $05
    .byte $06, $06, $07, $07, $08, $09, $09, $0A
    .byte $0A, $0B, $0C, $0C, $0D, $0E, $0F, $0F
    .byte $10, $11, $12, $13, $14, $15, $15, $16
    .byte $17, $18, $19, $1A, $1B, $1C, $1E, $1F
    .byte $20, $21, $22, $23, $24, $26, $27, $28
    .byte $29, $2B, $2C, $2D, $2F, $30, $32, $33
    .byte $34, $36, $37, $39, $3A, $3C, $3E, $3F
    .byte $41, $42, $44, $46, $47, $49, $4B, $4D
    .byte $4E, $50, $52, $54, $56, $58, $59, $5B
    .byte $5D, $5F, $61, $63, $65, $67, $69, $6B
    .byte $6E, $70, $72, $74, $76, $78, $7B, $7D
    .byte $7F, $7F, $7F, $7F, $7F, $7F, $7F, $7F
    .byte $7F, $7F, $7F, $7F, $7F, $7F, $7F, $7F
    .byte $7F, $7F, $7F, $7F, $7F, $7F, $7F, $7F
    .byte $7F, $7F, $7F, $7F, $7F, $7F, $7F, $7F

_hdma_curve_horizon:
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $0B, $14, $1D, $24, $2A, $30, $35
    .byte $39, $3D, $41, $44, $47, $4A, $4C, $4E
    .byte $50, $52, $53, $55, $56, $57, $58, $59
    .byte $5A, $5A, $5B, $5C, $5C, $5C, $5D, $5D
    .byte $5D, $5D, $5E, $5E, $5E, $5E, $5E, $5D
    .byte $5D, $5D, $5D, $5D, $5D, $5C, $5C, $5C
    .byte $5B, $5B, $5B, $5A, $5A, $59, $59, $58
    .byte $58, $58, $57, $56, $56, $55, $55, $54
    .byte $54, $53, $52, $52, $51, $51, $50, $4F
    .byte $4F, $4E, $4D, $4D, $4C, $4B, $4B, $4A
    .byte $49, $48, $48, $47, $46, $46, $45, $44
    .byte $43, $43, $42, $41, $40, $3F, $3F, $3E
    .byte $3D, $3C, $3C, $3B, $3A, $39, $38, $37
    .byte $37, $36, $35, $34, $33, $33, $32, $31
    .byte $30, $2F, $2E, $2D, $2D, $2C, $2B, $2A
    .byte $29, $28, $27, $27, $26, $25, $24, $23
    .byte $22, $21, $20, $20, $1F, $1E, $1D, $1C
    .byte $1B, $1A, $19, $19, $18, $17, $16, $15
    .byte $14, $13, $12, $11, $10, $10, $0F, $0E
    .byte $0D, $0C, $0B, $0A, $09, $08, $07, $06
    .byte $06, $05, $04, $03, $02, $01, $00, $FF
    .byte $FE, $FD, $FC, $FB, $FA, $FA, $F9, $F8
    .byte $F7, $F6, $F5, $F4, $F3, $F2, $F1, $F0
    .byte $EF, $EE, $ED, $EC, $EC, $EB, $EA, $E9
    .byte $E8, $E7, $E6, $E5, $E4, $E3, $E2, $E1
    .byte $E0, $DF, $DE, $DD, $DC, $DB, $DB, $DA
