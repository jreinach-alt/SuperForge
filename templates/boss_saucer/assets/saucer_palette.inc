; =============================================================================
; saucer_palette.inc — boss_saucer Mode 7 CGRAM data (GENERATED — do not edit)
; =============================================================================
; Regenerate: PYTHONPATH=. python3 templates/boss_saucer/assets/make_saucer.py
; (companion blob: saucer_map.bin, the interleaved Mode 7 VRAM image)
; CGRAM index 0 = SKY_DARK night-sky backdrop (shown where BG1 is off).
; =============================================================================

saucer_pal:
    .word $0820    ; color 0
    .word $0820    ; color 1
    .word $7F92    ; color 2
    .word $76A8    ; color 3
    .word $4983    ; color 4
    .word $6AF6    ; color 5
    .word $45CD    ; color 6
    .word $231F    ; color 7
    .word $0D92    ; color 8
    .word $24E6    ; color 9
    .word $1063    ; color 10
    .word $2207    ; color 11
    .word $5FF5    ; color 12
    .word $5E72    ; color 13

SAUCER_PAL_COUNT = 14
