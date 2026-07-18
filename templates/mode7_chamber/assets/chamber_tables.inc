; chamber_tables.inc — GENERATED (make_chamber_tables.py).
; M7A barrel curve + COLDATA vignette (factual hardware register values).

; M7A barrel: 192 floor scanlines (l0=32..l1=224), symmetric
; raised-cosine bow 1.0 ($0100) -> 1.5 ($0180) -> 1.0
; (smooth peak — no mid-screen corner).
chamber_barrel:
    .word $0100, $0100, $0100, $0100, $0101, $0101, $0101, $0102
    .word $0102, $0103, $0103, $0104, $0105, $0106, $0107, $0108
    .word $0109, $010A, $010B, $010C, $010D, $010F, $0110, $0111
    .word $0113, $0114, $0116, $0117, $0119, $011B, $011C, $011E
    .word $0120, $0122, $0124, $0126, $0128, $0129, $012B, $012D
    .word $012F, $0131, $0134, $0136, $0138, $013A, $013C, $013E
    .word $0140, $0142, $0144, $0146, $0148, $014A, $014C, $014F
    .word $0151, $0153, $0155, $0157, $0158, $015A, $015C, $015E
    .word $0160, $0162, $0164, $0165, $0167, $0169, $016A, $016C
    .word $016D, $016F, $0170, $0171, $0173, $0174, $0175, $0176
    .word $0177, $0178, $0179, $017A, $017B, $017C, $017D, $017D
    .word $017E, $017E, $017F, $017F, $017F, $0180, $0180, $0180
    .word $0180, $0180, $0180, $0180, $017F, $017F, $017F, $017E
    .word $017E, $017D, $017D, $017C, $017B, $017A, $0179, $0178
    .word $0177, $0176, $0175, $0174, $0173, $0171, $0170, $016F
    .word $016D, $016C, $016A, $0169, $0167, $0165, $0164, $0162
    .word $0160, $015E, $015C, $015A, $0158, $0157, $0155, $0153
    .word $0151, $014F, $014C, $014A, $0148, $0146, $0144, $0142
    .word $0140, $013E, $013C, $013A, $0138, $0136, $0134, $0131
    .word $012F, $012D, $012B, $0129, $0128, $0126, $0124, $0122
    .word $0120, $011E, $011C, $011B, $0119, $0117, $0116, $0114
    .word $0113, $0111, $0110, $010F, $010D, $010C, $010B, $010A
    .word $0109, $0108, $0107, $0106, $0105, $0104, $0103, $0103
    .word $0102, $0102, $0101, $0101, $0101, $0100, $0100, $0100

; COLDATA vignette HDMA table: direct [count,value]... $00 ($2132).
; Intensity 0 -> 8 -> 0 ($E0..$E8..$E0), brightest middle 84 lines.
chamber_vignette:
    .byte $24, $E0
    .byte $08, $E2
    .byte $04, $E3
    .byte $08, $E4
    .byte $0A, $E5
    .byte $0C, $E6
    .byte $12, $E7
    .byte $54, $E8
    .byte $0A, $E7
    .byte $08, $E6
    .byte $06, $E5
    .byte $06, $E4
    .byte $06, $E3
    .byte $01, $E1
    .byte $00                ; terminator

CHAMBER_VIGNETTE_LEN = 29    ; bytes incl. terminator
; (vignette covers 217 active scanlines)
