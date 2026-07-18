; =============================================================================
; track_palette.inc — racer track CGRAM data (GENERATED — do not edit)
; =============================================================================
; Regenerate: PYTHONPATH=. python3 templates/racer/assets/make_track.py
; (companion blob: track_map.bin, the interleaved Mode 7 VRAM image)
; =============================================================================

track_pal:
    .word $7EAC    ; color 0
    .word $1E27    ; color 1
    .word $77BD    ; color 2
    .word $14BA    ; color 3
    .word $39AD    ; color 4
    .word $316B    ; color 5
    .word $0C42    ; color 6
    .word $15C5    ; color 7

TRACK_PAL_COUNT = 8
