; dash_chr.inc — GENERATED (make_dash.py). BG3 2bpp instrument tiles.
dash_chr:
    .byte $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00    ; tile 0 BLANK
    .byte $FF, $00, $FF, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00    ; tile 1 FRAME_TOP
    .byte $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $00, $FF, $00, $FF, $00    ; tile 2 FRAME_BOT
    .byte $FF, $00, $81, $7E, $81, $7E, $81, $7E, $81, $7E, $81, $7E, $81, $7E, $FF, $00    ; tile 3 BAR_EMPTY
    .byte $FF, $00, $FF, $7E, $FF, $7E, $FF, $7E, $FF, $7E, $FF, $7E, $FF, $7E, $FF, $00    ; tile 4 BAR_FILL
    .byte $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF, $FF    ; tile 5 GAUGE_LIT
    .byte $00, $FF, $00, $FF, $00, $FF, $00, $FF, $00, $FF, $00, $FF, $00, $FF, $00, $FF    ; tile 6 GAUGE_DIM

DASH_CHR_BYTES = 112
DASH_TILE_BLANK = 0
DASH_TILE_FRAME_TOP = 1
DASH_TILE_FRAME_BOT = 2
DASH_TILE_BAR_EMPTY = 3
DASH_TILE_BAR_FILL = 4
DASH_TILE_GAUGE_LIT = 5
DASH_TILE_GAUGE_DIM = 6
