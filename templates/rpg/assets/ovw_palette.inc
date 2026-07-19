; =============================================================================
; ovw_palette.inc — overworld (Mode 7) CGRAM data (GENERATED — do not edit)
; =============================================================================
; SOURCE ART: Four Seasons Platformer Tileset [16x16] — Rotting Pixels.
;   pack:  examples/itch_cc0/Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels.zip
;   grant: custom permissive (itch.io page, quoted 2026-07-18) — free +
;          commercial use, modification allowed, credit optional. NOT CC0;
;          see examples/itch_cc0/LICENSES.md.
;   The grass/dirt-path/water/rock terrain tiles are that pack's 16x16 art
;   downsampled 16->8 into this 8bpp Mode 7 tile set. The LAYOUT + collision
;   are first-party (ovw_terrain is the SSoT) — the art swap moves nothing.
; cmd: PYTHONPATH=. python3 templates/rpg/assets/make_rpg_assets.py
; (companion blob: ovw_map.bin, the interleaved Mode 7 VRAM image)
; CGRAM index 0 = SKY backdrop (revealed above the horizon by the
; per-scanline sky-split where BG1 is off; floor grass is relocated).
; =============================================================================

ovw_pal:
    .word $7EAF    ; color 0
    .word $1E03    ; color 1
    .word $1A22    ; color 2
    .word $1DE3    ; color 3
    .word $1682    ; color 4
    .word $1E25    ; color 5
    .word $26C4    ; color 6
    .word $26E3    ; color 7
    .word $2A84    ; color 8
    .word $1F43    ; color 9
    .word $14A6    ; color 10
    .word $25B1    ; color 11
    .word $36BD    ; color 12
    .word $2E5A    ; color 13
    .word $25F8    ; color 14
    .word $18EA    ; color 15
    .word $25B6    ; color 16
    .word $1D0E    ; color 17
    .word $1085    ; color 18
    .word $1D6F    ; color 19
    .word $2A38    ; color 20
    .word $18EB    ; color 21
    .word $14C9    ; color 22
    .word $1D73    ; color 23
    .word $192D    ; color 24
    .word $21B5    ; color 25
    .word $2908    ; color 26
    .word $5A51    ; color 27
    .word $3DCD    ; color 28
    .word $62B3    ; color 29
    .word $3169    ; color 30
    .word $6EF6    ; color 31
    .word $7B59    ; color 32
    .word $7FBC    ; color 33
    .word $1CC5    ; color 34
    .word $41CD    ; color 35
    .word $2D49    ; color 36
    .word $49EE    ; color 37
    .word $2507    ; color 38
    .word $5230    ; color 39
    .word $5A72    ; color 40
    .word $62B5    ; color 41
    .word $6165    ; color 42
    .word $4923    ; color 43
    .word $30C2    ; color 44
    .word $3CE3    ; color 45
    .word $5544    ; color 46
    .word $1D3A    ; color 47
    .word $619A    ; color 48
    .word $4B1C    ; color 49
    .word $1584    ; color 50

OVW_PAL_COUNT = 51
