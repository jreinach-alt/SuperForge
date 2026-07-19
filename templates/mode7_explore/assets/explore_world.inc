; ===========================================================================
; explore_world.inc — believable Mode 7 streaming overworld constants (GENERATED)
; ===========================================================================
; Regenerate: python3 templates/mode7_explore/assets/make_explore_world.py
; World: 512x512 tiles (4096x4096 px), 11 authored textured tiles, flat tilemap across 8 ROM banks.
; Collision derives from the FLAT tilemap byte via tile_terrain_lut (NO
; separate collision table — the tilemap is the single source of truth).
; ===========================================================================

WORLD_T_TILES   = 512
WORLD_PX        = 4096
WORLD_WRAP_MASK = 511        ; (tile coord) & this wraps 0..511
WORLD_ROWS_PER_BANK = 64
WORLD_COLS_BYTES = 512      ; bytes per flat row
WORLD_FLAT_BANK_BASE = 2   ; first ROM bank of flat tilemap
WORLD_FLAT_BANK_COUNT = 8   ; flat tilemap spans this many ROM banks
WORLD_SPAWN_TX  = 258
WORLD_SPAWN_TY  = 258
WORLD_LANDMARK_STEP = 32  ; TOWN (house) landmark lattice spacing, tiles

; --- DEMO town house: the enterable house a short walk NW of spawn. Stepping
;     onto (WORLD_DEMO_HOUSE_TX, WORLD_DEMO_HOUSE_TY) triggers the Mode 1
;     town-visit arc (mosaic-in -> interior -> mosaic-out). Off the tested spawn
;     axes so the streaming sweeps never step onto it. ---
WORLD_DEMO_HOUSE_TX = 254
WORLD_DEMO_HOUSE_TY = 254

; --- terrain ids (collision-class vocabulary; tile_terrain_lut maps to these) ---
TERR_GRASS    = 0
TERR_PATH     = 1
TERR_WATER    = 2    ; BLOCKED
TERR_MOUNTAIN = 3    ; BLOCKED
TERR_TOWN     = 4    ; walkable landmark (decorative lattice houses)
TERR_TOWN_ENTER = 5  ; walkable landmark that ENTERS the town (demo house)
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
TILE_COAST    = 8
TILE_FOREST   = 9
TILE_TOWN_DOOR = 10

; --- CGRAM palette + tile_terrain_lut: emitted into RODATA via pushseg/popseg
;     so this .inc can be included in the equate region (before the ROM's
;     first .segment CODE). ---
WORLD_PAL_COUNT = 12
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
    .word $471A    ; color 8
    .word $1523    ; color 9
    .word $19A5    ; color 10
    .word $21B0    ; color 11

; tile-id -> terrain-class LUT (256 bytes). collision[ (tx,ty) ] =
; tile_terrain_lut[ flat_tilemap[ty*WORLD_T + tx] ].  The tilemap is the SSoT.
tile_terrain_lut:
    .byte 0, 0, 1, 2, 2, 3, 3, 4, 0, 0, 5, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
    .byte 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
.popseg

