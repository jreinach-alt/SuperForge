; =============================================================================
; overworld_palette.inc — overworld (Mode 7) CGRAM data (GENERATED — do not edit)
; =============================================================================
; mode7_flight ground palette: a kit-native copy of the RPG overworld palette so
; the airship flies over a continent/coastline instead of the racer track.
; Regenerate: PYTHONPATH=. python3 templates/rpg/assets/make_rpg_assets.py
; (companion blob: ground_map.bin == templates/rpg/assets/ovw_map.bin)
; CGRAM index 0 = SKY backdrop (revealed above the horizon by the
; per-scanline sky-split where BG1 is off; floor grass is relocated).
; =============================================================================

ovw_pal:
    .word $726C    ; color 0
    .word $1E06    ; color 1
    .word $3256    ; color 2
    .word $21B0    ; color 3
    .word $4232    ; color 4
    .word $254C    ; color 5
    .word $5D65    ; color 6
    .word $44E3    ; color 7
    .word $1D3A    ; color 8
    .word $619A    ; color 9
    .word $4B1C    ; color 10
    .word $1563    ; color 11

OVW_PAL_COUNT = 12
