; ===========================================================================
; explore_town.inc — Mode 1 town-interior CHR + palette (GENERATED)
; ===========================================================================
; Regenerate: python3 templates/mode7_explore/assets/make_explore_world.py
; The mosaic town-visit interior: a plank floor, stone walls, a table, and
; an exit door. 4bpp BG1 CHR (uploaded to VRAM word $5000, above the
; preserved Mode 7 image) + a 16-colour palette (CGRAM 0..15; colour 0 is
; the floor base, also the backdrop so gaps read as floor).
; ===========================================================================

TOWN_TILE_FLOOR = 0
TOWN_TILE_WALL  = 1
TOWN_TILE_DOOR  = 2
TOWN_TILE_TABLE = 3
TOWN_CHR_BYTES  = 128
TOWN_PAL_COUNT  = 16

.pushseg
.segment "RODATA"
town_chr:
    .byte $FE, $01, $FE, $01, $FE, $01, $00, $FF, $FE, $01, $FE, $01, $FE, $01, $00, $FF
    .byte $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $FF, $FE, $FF, $FE, $FF, $00, $00, $00, $FF, $7F, $FF, $7F, $FF, $00
    .byte $FF, $00, $01, $00, $01, $00, $FF, $00, $FF, $00, $80, $00, $80, $00, $FF, $00
    .byte $00, $00, $54, $7E, $54, $7E, $54, $7E, $54, $7E, $54, $7E, $54, $7E, $00, $00
    .byte $00, $FF, $7E, $81, $7E, $81, $7F, $81, $7E, $81, $7E, $81, $7E, $81, $00, $FF
    .byte $00, $00, $00, $7E, $7E, $81, $7E, $81, $42, $42, $42, $42, $42, $42, $00, $00
    .byte $00, $00, $00, $7E, $00, $FF, $00, $FF, $00, $42, $00, $42, $00, $42, $00, $00

town_pal:
    .word $10C9    ; color 0
    .word $192D    ; color 1
    .word $0C86    ; color 2
    .word $398C    ; color 3
    .word $4E51    ; color 4
    .word $24E7    ; color 5
    .word $1592    ; color 6
    .word $2238    ; color 7
    .word $0865    ; color 8
    .word $154F    ; color 9
    .word $21F5    ; color 10
    .word $0464    ; color 11
    .word $471A    ; color 12
    .word $0000    ; color 13
    .word $0000    ; color 14
    .word $0000    ; color 15
.popseg

