; ===========================================================================
; world_stream.inc — large Mode 7 streaming overworld constants (GENERATED)
; ===========================================================================
; Regenerate: python3 tests/fixtures/mode7_stream/gen_stream_world.py
; World: 256x256 tiles (2048x2048 px), 8 authored tiles, flat tilemap across 2 ROM banks.
; ===========================================================================

WORLD_T_TILES   = 256
WORLD_PX        = 2048
WORLD_WRAP_MASK = 255        ; (tile coord) & this wraps 0..255
WORLD_ROWS_PER_BANK = 128
WORLD_COLS_BYTES = 256      ; bytes per flat row
WORLD_FLAT_BANK_BASE = 2   ; first ROM bank of flat tilemap
WORLD_SPAWN_TX  = 128
WORLD_SPAWN_TY  = 128
WORLD_LANDMARK_STEP = 32  ; TOWN tile lattice spacing (hidden debug)

; --- terrain ids (parallel collision table) ---
TERR_GRASS    = 0
TERR_PATH     = 1
TERR_WATER    = 2    ; BLOCKED
TERR_MOUNTAIN = 3    ; BLOCKED
TERR_TOWN     = 4    ; walkable landmark
TERR_BLOCKED_MIN = 2
TERR_BLOCKED_MAX = 3

; --- tile ids (CHR index == low-byte tilemap entry) ---
TILE_GRASS_DK = 0
TILE_GRASS_LT = 1
TILE_PATH     = 2
TILE_WATER_DK = 3
TILE_WATER_LT = 4
TILE_MTN_DK   = 5
TILE_MTN_LT   = 6
TILE_TOWN     = 7

; --- CGRAM palette: index == tile id (flat tiles); BGR555 words ---
; Emitted into RODATA via pushseg/popseg so this .inc can be included
; in the equate region (before the ROM's first .segment CODE) without
; the .word data landing in whatever segment is active (e.g. VECTORS
; right after header.inc — see CLAUDE.md 'header.inc Leaves You in the
; VECTORS Segment').
WORLD_PAL_COUNT = 8
.pushseg
.segment "RODATA"
world_palette:
    .word $1563    ; color 0
    .word $1E06    ; color 1
    .word $3256    ; color 2
    .word $44E3    ; color 3
    .word $5D65    ; color 4
    .word $254C    ; color 5
    .word $4232    ; color 6
    .word $1D3A    ; color 7
.popseg

