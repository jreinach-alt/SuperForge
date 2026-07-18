; =============================================================================
; town_assets.inc — Mode 1 town/battle CHR + palettes (GENERATED — do not edit)
; =============================================================================
; Regenerate: PYTHONPATH=. python3 templates/rpg/assets/make_rpg_assets.py
; 4bpp BG CHR (tiles 0..5): 0=empty 1=cobble 2=brick 3=water 4=torch 5=avatar
; town_bg_pal = 16-color BG palette 0; obj_pal = 16-color OBJ palette 0.
; =============================================================================

; --- BG/avatar CHR blob (6 tiles x 32 bytes = 192 bytes, 4bpp) ---
town_chr:
    ; tile 0
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    ; tile 1
    .byte $FD, $22, $BF, $48, $EF, $91, $FD, $02
    .byte $FF, $44, $7F, $90, $DF, $22, $F7, $08
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    ; tile 2
    .byte $11, $00, $11, $00, $FF, $00, $44, $00
    .byte $44, $00, $FF, $00, $11, $00, $11, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    .byte $FF, $00, $FF, $00, $FF, $00, $FF, $00
    ; tile 3
    .byte $00, $FF, $42, $FF, $10, $FF, $00, $FF
    .byte $24, $FF, $00, $FF, $41, $FF, $00, $FF
    .byte $FF, $00, $BD, $00, $EF, $00, $FF, $00
    .byte $DB, $00, $FF, $00, $BE, $00, $FF, $00
    ; tile 4
    .byte $18, $18, $3C, $3C, $3C, $3C, $18, $18
    .byte $18, $00, $18, $00, $18, $00, $18, $00
    .byte $18, $00, $3C, $00, $3C, $00, $18, $00
    .byte $18, $00, $18, $00, $18, $00, $18, $00
    ; tile 5
    .byte $00, $00, $38, $00, $38, $00, $44, $7C
    .byte $C6, $FE, $00, $38, $00, $00, $00, $00
    .byte $38, $00, $44, $00, $44, $00, $00, $00
    .byte $00, $00, $44, $00, $28, $00, $28, $00
    ; tile 6
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    ; tile 7
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    .byte $00, $00, $00, $00, $00, $00, $00, $00
    ; tile 8
    .byte $18, $00, $18, $00, $18, $00, $18, $00
    .byte $18, $00, $00, $00, $18, $00, $18, $00
    .byte $18, $00, $18, $00, $18, $00, $18, $00
    .byte $18, $00, $00, $00, $18, $00, $18, $00
    ; tile 9
    .byte $00, $66, $00, $66, $00, $66, $00, $7E
    .byte $00, $7E, $00, $66, $00, $66, $00, $66
    .byte $66, $00, $66, $00, $66, $00, $7E, $00
    .byte $7E, $00, $66, $00, $66, $00, $66, $00
    ; tile 10
    .byte $00, $7E, $00, $7E, $00, $60, $00, $7C
    .byte $00, $7C, $00, $60, $00, $7E, $00, $7E
    .byte $7E, $00, $7E, $00, $60, $00, $7C, $00
    .byte $7C, $00, $60, $00, $7E, $00, $7E, $00
    ; tile 11
    .byte $00, $60, $00, $60, $00, $60, $00, $60
    .byte $00, $60, $00, $60, $00, $7E, $00, $7E
    .byte $60, $00, $60, $00, $60, $00, $60, $00
    .byte $60, $00, $60, $00, $7E, $00, $7E, $00
    ; tile 12
    .byte $00, $3C, $00, $7E, $00, $66, $00, $66
    .byte $00, $66, $00, $66, $00, $7E, $00, $3C
    .byte $3C, $00, $7E, $00, $66, $00, $66, $00
    .byte $66, $00, $66, $00, $7E, $00, $3C, $00
TOWN_CHR_BYTES = 416

; tile-index constants (avatar is OBJ tile 5)
TOWN_TILE_EMPTY  = 0
TOWN_TILE_COBBLE = 1
TOWN_TILE_BRICK  = 2
TOWN_TILE_WATER  = 3
TOWN_TILE_TORCH  = 4
AVATAR_TILE      = 5
; --- Sprint 2 OBJ sprite-text glyphs (tiles 8..12; 6/7 reserved empty
;     for the avatar's 16x16 PPU quad). The prompt strip word is HELLO.
PROMPT_TILE_IND  = 8    ; '!' indicator (shown only when adjacent to NPC)
GLYPH_TILE_H     = 9
GLYPH_TILE_E     = 10
GLYPH_TILE_L     = 11
GLYPH_TILE_O     = 12

; --- BG palette 0 (16 colors, BGR15) ---
town_bg_pal:
    .word $0000
    .word $398C
    .word $2908
    .word $4E31
    .word $1912
    .word $10AC
    .word $5565
    .word $2B3F
    .word $0CA3
    .word $0000
    .word $0000
    .word $0000
    .word $0000
    .word $0000
    .word $0000
    .word $0000
TOWN_BG_PAL_COUNT = 1

; --- OBJ palette 0 (16 colors, BGR15) — avatar ---
obj_pal:
    .word $0000
    .word $5B7E
    .word $64E5
    .word $14B6
    .word $1463
    .word $33BF
    .word $77FF
    .word $0000
    .word $0000
    .word $0000
    .word $0000
    .word $0000
    .word $0000
    .word $0000
    .word $0000
    .word $0000

