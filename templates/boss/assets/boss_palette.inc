; =============================================================================
; boss_palette.inc — boss-arena CGRAM data (GENERATED — do not edit)
; =============================================================================
; Regenerate: PYTHONPATH=. python3 templates/boss/assets/make_boss.py
; (companion blob: boss_map.bin, the interleaved Mode 7 VRAM image)
; CGRAM index 0 = ARENA_DARK backdrop (shown where BG1 is off).
; =============================================================================

boss_pal:
    .word $0821    ; color 0
    .word $1043    ; color 1
    .word $3235    ; color 2
    .word $190B    ; color 3
    .word $358D    ; color 4
    .word $20E8    ; color 5
    .word $45A5    ; color 6
    .word $7F6C    ; color 7
    .word $08B2    ; color 8
    .word $4E32    ; color 9
    .word $119F    ; color 10
    .word $1885    ; color 11
    .word $6B7C    ; color 12

BOSS_PAL_COUNT = 13
