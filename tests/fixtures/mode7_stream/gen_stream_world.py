#!/usr/bin/env python3
# =============================================================================
# gen_stream_world.py — large authored Mode 7 overworld for the streaming proof.
# =============================================================================
# Streaming-rail v2 / Sprint S1.  Authors a 256x256-tile (= 2048x2048 px) Mode 7
# overworld — "several windows" wide AND tall vs the 128x128 (1024x1024 px) Mode
# 7 VRAM window — and emits it in the SPLIT streaming format the proven overhead-racing substrate
# consumes:
#
#   world_flat_bankN.bin   FLAT tilemap, 1 byte/tile (low-byte tile id), packed
#                          256 bytes/row, 128 rows/bank.  256 rows -> 2 banks
#                          (16 KB each).  This is what STREAMS into VRAM low
#                          bytes as the camera walks.  Bank/offset addressing:
#                          bank = (row >> 7) + base, offset = $8000+(row&127)*256.
#   world_seed.bin         32 KB INTERLEAVED Mode 7 VRAM seed = the INITIAL
#                          128x128 window: low byte = initial tilemap id,
#                          high byte = the fixed N-tile 8bpp CHR set (tile T's
#                          64 bytes live at the high bytes of words T*64..+63).
#                          Uploaded ONCE under forced blank.  The CHR never
#                          streams; only the low-byte tile ids do.
#   world_collision.bin    WORLD-SPACE collision, 1 byte/tile, 256x256 = 64 KB,
#                          row-major  collision[ty*256+tx] = terrain id.  16-bit
#                          indexed (NOT the 14-bit (ty<<7)|tx the 128 RPG uses).
#   world_stream.inc       ca65 constants: world dims, spawn, bank base, the
#                          TERR_*/tile-id vocabulary, palette word table.
#
# The VISIBLE world reuses the kit RPG overworld's authored tile art
# (grass/path/water/mountain/town) + its palette colours — a bigger TILEMAP over
# the SAME tiles, NOT a synthetic position-id pattern (owner decision: reuse the
# kit's authored tile art; a position-id visible world is BANNED).  A separate
# HIDDEN debug landmark band (a diagonal of TOWN tiles every 32 tiles) gives the
# proof test position-identifiable ground truth WITHOUT making the visible world
# a synthetic pattern — the landmarks are authored content (towns), just placed
# on a regular grid so a test can assert "at world (tx,ty) you must see tile id
# T".  Geography (continents/water/mountains/roads) is generated believably.
#
# Deterministic: same script, same bytes (fixed seed, no PRNG state leak).
#
# Regenerate (from a kit root that has PIL):
#   python3 tests/fixtures/mode7_stream/gen_stream_world.py
# =============================================================================
from __future__ import annotations

import math
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- world geometry ----------------------------------------------------------
WORLD_T = 256                       # world is WORLD_T x WORLD_T tiles
WORLD_PX = WORLD_T * 8              # 2048 px
ROWS_PER_BANK = 128                # 128 rows * 256 bytes/row = 32768 = 1 bank
COLS = WORLD_T                      # 256 bytes/row
BANK_BASE = 2                      # flat tilemap starts at ROM bank 2 (BANK2 seg)
VRAM_WIN = 128                     # Mode 7 VRAM tilemap is 128x128

# --- terrain ids (parallel collision table; mirror the kit RPG vocabulary) ---
TERR_GRASS = 0      # walkable
TERR_PATH = 1       # walkable
TERR_WATER = 2      # BLOCKED
TERR_MOUNTAIN = 3   # BLOCKED
TERR_TOWN = 4       # walkable landmark
BLOCKED = {TERR_WATER, TERR_MOUNTAIN}
TERR_BLOCKED_MIN = TERR_WATER
TERR_BLOCKED_MAX = TERR_MOUNTAIN

# --- tile ids (low-byte tilemap entry == CHR tile index).  Each terrain gets
#     TWO checker tiles for a visible motion cue (matches the RPG meadow checker)
#     except path/town which use a flat tile.  Tile id 0 must stay walkable
#     grass (CGRAM-0 is the Mode 7 backdrop convention; we DON'T reserve a sky
#     slot here — this proof is a flat top-down view, no perspective horizon, so
#     index 0 can be opaque grass). -----------------------------------------
TILE_GRASS_DK = 0
TILE_GRASS_LT = 1
TILE_PATH = 2
TILE_WATER_DK = 3
TILE_WATER_LT = 4
TILE_MTN_DK = 5
TILE_MTN_LT = 6
TILE_TOWN = 7
N_TILES = 8

# tile id -> terrain id (for the collision table; SSoT with the rendered tile)
TILE_TERRAIN = {
    TILE_GRASS_DK: TERR_GRASS, TILE_GRASS_LT: TERR_GRASS,
    TILE_PATH: TERR_PATH,
    TILE_WATER_DK: TERR_WATER, TILE_WATER_LT: TERR_WATER,
    TILE_MTN_DK: TERR_MOUNTAIN, TILE_MTN_LT: TERR_MOUNTAIN,
    TILE_TOWN: TERR_TOWN,
}

# --- authored colours (BGR-as-RGB triples, reuse the kit RPG palette flavour) -
#     these mirror make_rpg_assets.py's GRASS/PATH/WATER/MTN/TOWN colours so the
#     visible world looks like the RPG overworld, just larger.
RGB = {
    TILE_GRASS_DK: (30, 92, 40),
    TILE_GRASS_LT: (52, 130, 58),
    TILE_PATH: (176, 150, 96),
    TILE_WATER_DK: (24, 58, 140),
    TILE_WATER_LT: (44, 92, 184),
    TILE_MTN_DK: (96, 84, 78),
    TILE_MTN_LT: (150, 138, 128),
    TILE_TOWN: (208, 72, 56),
}

# --- spawn: centre of the world so the proof can walk +X, +Y, -X, -Y freely ---
SPAWN_TX = 128
SPAWN_TY = 128

# --- HIDDEN debug landmark grid: a TOWN tile at every (tx,ty) where tx%32==0
#     and ty%32==0.  These are authored town tiles (legitimate content), placed
#     on a 32-tile lattice so the proof test has position-identifiable ground
#     truth: "world tile (32k, 32m) is a TOWN tile (id 7)".  Everything between
#     is believable geography. ----------------------------------------------
LANDMARK_STEP = 32


def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


# -----------------------------------------------------------------------------
# Geography — believable large overworld.  Adapted from rpg_world_map_gen.py's
# approach (continent mask + feature discs + ridge segments + a road grid), but
# emits TILE IDS directly (not a PNG) at 256x256.
# -----------------------------------------------------------------------------
def _continent_height(tx: int, ty: int) -> float:
    """Smooth pseudo-elevation field in [0,1] from summed sinusoids (seeded,
    deterministic) — high = inland, low = ocean.  No PRNG, fully reproducible."""
    nx = tx / WORLD_T
    ny = ty / WORLD_T
    # radial falloff from centre keeps a central landmass, oceans at the rim
    dx, dy = nx - 0.5, ny - 0.5
    radial = 1.0 - min(1.0, math.sqrt(dx * dx + dy * dy) / 0.62)
    # layered sinusoidal noise (fixed frequencies/phases = deterministic)
    n = 0.0
    for k, (fx, fy, ph, amp) in enumerate([
        (2.0, 2.0, 0.0, 0.50), (3.7, 1.3, 1.1, 0.28),
        (1.3, 4.1, 2.3, 0.22), (6.0, 5.0, 0.7, 0.13),
        (8.3, 3.1, 3.3, 0.09),
    ]):
        n += amp * math.sin(fx * nx * math.pi * 2 + ph) * math.cos(fy * ny * math.pi * 2 + ph)
    n = (n + 1.0) * 0.5  # -> [0,1]-ish
    return max(0.0, min(1.0, 0.55 * radial + 0.55 * n))


def _ridge(tx: int, ty: int) -> bool:
    """Mountain ridge field: high-elevation bands form ranges."""
    h = _continent_height(tx, ty)
    # ridges where the elevation crosses a high band with a thin ripple
    ripple = math.sin(tx * 0.5) * math.cos(ty * 0.4)
    return h > 0.74 and ripple > 0.25


def terrain_at(tx: int, ty: int) -> int:
    """SINGLE SOURCE OF TRUTH: terrain id for world tile (tx,ty).  Used by BOTH
    the rendered tile id and the collision table."""
    # hidden debug landmark lattice (authored town tiles) — checked first so a
    # landmark is never overwritten by surrounding geography
    if tx % LANDMARK_STEP == 0 and ty % LANDMARK_STEP == 0:
        return TERR_TOWN
    h = _continent_height(tx, ty)
    if h < 0.30:
        return TERR_WATER            # ocean / lakes (BLOCKED)
    if _ridge(tx, ty):
        return TERR_MOUNTAIN         # mountain range (BLOCKED)
    # road grid: cardinal paths every 16 tiles (so the player always has a path
    # within a few steps of spawn in every direction)
    if (tx % 16) in (7, 8) or (ty % 16) in (7, 8):
        # don't pave over water/mountain
        return TERR_PATH
    return TERR_GRASS


def tile_at(tx: int, ty: int) -> int:
    """Tile id (CHR index / low-byte tilemap entry) for world tile (tx,ty).
    Derived from terrain_at so visuals and collision can never drift."""
    terr = terrain_at(tx, ty)
    if terr == TERR_TOWN:
        return TILE_TOWN
    if terr == TERR_PATH:
        return TILE_PATH
    if terr == TERR_WATER:
        return TILE_WATER_LT if (tx ^ ty) & 1 else TILE_WATER_DK
    if terr == TERR_MOUNTAIN:
        return TILE_MTN_LT if (tx ^ ty) & 1 else TILE_MTN_DK
    # meadow checker (2x2 block scale, like the RPG meadow motion cue)
    return TILE_GRASS_LT if ((tx >> 1) ^ (ty >> 1)) & 1 else TILE_GRASS_DK


# -----------------------------------------------------------------------------
# Emitters
# -----------------------------------------------------------------------------
def build_tilemap() -> bytes:
    """256x256 tile-id grid, row-major."""
    out = bytearray(WORLD_T * WORLD_T)
    for ty in range(WORLD_T):
        base = ty * WORLD_T
        for tx in range(WORLD_T):
            out[base + tx] = tile_at(tx, ty)
    return bytes(out)


def build_collision(tilemap: bytes) -> bytes:
    """256x256 terrain-id grid, row-major (world-space, 16-bit indexed)."""
    return bytes(TILE_TERRAIN[t] for t in tilemap)


def build_chr() -> bytes:
    """Fixed N_TILES-tile 8bpp Mode 7 CHR set, packed tile-major: tile T's 64
    bytes at offset T*64.  Each tile is a FLAT solid colour = palette index ==
    tile id (so CGRAM[tile_id] is the tile's colour).  Padded to 256 tiles
    (16384 bytes) — the Mode 7 char set always occupies all 256 slots."""
    out = bytearray(256 * 64)
    for t in range(N_TILES):
        # flat tile: every pixel = palette index t
        for i in range(64):
            out[t * 64 + i] = t
    return bytes(out)


def build_seed(tilemap: bytes, chr_data: bytes) -> bytes:
    """32 KB interleaved Mode 7 VRAM seed for the INITIAL 128x128 window covering
    world tiles [SPAWN-64 .. SPAWN+63] each axis.  CRITICAL: the seed must use
    the SAME VRAM-WRAPPED placement the streaming engine uses — a world tile
    (wx,wy) lands at VRAM word (wy & 127)*128 + (wx & 127), NOT at a sequential
    (vy*128+vx).  The engine's row/column DMA writes the leading edge at the
    wrapped position (coord & $7F); if the seed used a sequential layout the two
    mappings would differ by the window origin (off-by-64 corruption when a row
    or column that the seed placed is later re-streamed at its wrapped slot).
    low byte = tile id; high byte = chr_data (the fixed char set)."""
    out = bytearray(VRAM_WIN * VRAM_WIN * 2)
    win_x0 = (SPAWN_TX - 64) % WORLD_T
    win_y0 = (SPAWN_TY - 64) % WORLD_T
    for dy in range(VRAM_WIN):
        wy = (win_y0 + dy) % WORLD_T
        vy = wy & (VRAM_WIN - 1)            # wrapped VRAM row == engine mapping
        for dx in range(VRAM_WIN):
            wx = (win_x0 + dx) % WORLD_T
            vx = wx & (VRAM_WIN - 1)        # wrapped VRAM col
            word = vy * VRAM_WIN + vx
            out[word * 2] = tilemap[wy * WORLD_T + wx]      # low = tile id
            out[word * 2 + 1] = chr_data[word]              # high = CHR byte
    return bytes(out)


def build_flat_banks(tilemap: bytes) -> list[bytes]:
    """Flat tilemap split into ROM banks: ROWS_PER_BANK rows/bank, 256 B/row."""
    banks = []
    n_banks = WORLD_T // ROWS_PER_BANK
    for b in range(n_banks):
        data = bytearray()
        for row in range(b * ROWS_PER_BANK, (b + 1) * ROWS_PER_BANK):
            data.extend(tilemap[row * COLS: row * COLS + COLS])
        assert len(data) == ROWS_PER_BANK * COLS
        banks.append(bytes(data))
    return banks


def emit_inc(palette_words: list[int], n_banks: int) -> str:
    L = []
    L.append("; ===========================================================================")
    L.append("; world_stream.inc — large Mode 7 streaming overworld constants (GENERATED)")
    L.append("; ===========================================================================")
    L.append("; Regenerate: python3 tests/fixtures/mode7_stream/gen_stream_world.py")
    L.append(f"; World: {WORLD_T}x{WORLD_T} tiles ({WORLD_PX}x{WORLD_PX} px), "
             f"{N_TILES} authored tiles, flat tilemap across {n_banks} ROM banks.")
    L.append("; ===========================================================================")
    L.append("")
    L.append(f"WORLD_T_TILES   = {WORLD_T}")
    L.append(f"WORLD_PX        = {WORLD_PX}")
    L.append(f"WORLD_WRAP_MASK = {WORLD_T - 1}        ; (tile coord) & this wraps 0..{WORLD_T-1}")
    L.append(f"WORLD_ROWS_PER_BANK = {ROWS_PER_BANK}")
    L.append(f"WORLD_COLS_BYTES = {COLS}      ; bytes per flat row")
    L.append(f"WORLD_FLAT_BANK_BASE = {BANK_BASE}   ; first ROM bank of flat tilemap")
    L.append(f"WORLD_SPAWN_TX  = {SPAWN_TX}")
    L.append(f"WORLD_SPAWN_TY  = {SPAWN_TY}")
    L.append(f"WORLD_LANDMARK_STEP = {LANDMARK_STEP}  ; TOWN tile lattice spacing (hidden debug)")
    L.append("")
    L.append("; --- terrain ids (parallel collision table) ---")
    L.append(f"TERR_GRASS    = {TERR_GRASS}")
    L.append(f"TERR_PATH     = {TERR_PATH}")
    L.append(f"TERR_WATER    = {TERR_WATER}    ; BLOCKED")
    L.append(f"TERR_MOUNTAIN = {TERR_MOUNTAIN}    ; BLOCKED")
    L.append(f"TERR_TOWN     = {TERR_TOWN}    ; walkable landmark")
    L.append(f"TERR_BLOCKED_MIN = {TERR_BLOCKED_MIN}")
    L.append(f"TERR_BLOCKED_MAX = {TERR_BLOCKED_MAX}")
    L.append("")
    L.append("; --- tile ids (CHR index == low-byte tilemap entry) ---")
    L.append(f"TILE_GRASS_DK = {TILE_GRASS_DK}")
    L.append(f"TILE_GRASS_LT = {TILE_GRASS_LT}")
    L.append(f"TILE_PATH     = {TILE_PATH}")
    L.append(f"TILE_WATER_DK = {TILE_WATER_DK}")
    L.append(f"TILE_WATER_LT = {TILE_WATER_LT}")
    L.append(f"TILE_MTN_DK   = {TILE_MTN_DK}")
    L.append(f"TILE_MTN_LT   = {TILE_MTN_LT}")
    L.append(f"TILE_TOWN     = {TILE_TOWN}")
    L.append("")
    L.append("; --- CGRAM palette: index == tile id (flat tiles); BGR555 words ---")
    L.append("; Emitted into RODATA via pushseg/popseg so this .inc can be included")
    L.append("; in the equate region (before the ROM's first .segment CODE) without")
    L.append("; the .word data landing in whatever segment is active (e.g. VECTORS")
    L.append("; right after header.inc — see CLAUDE.md 'header.inc Leaves You in the")
    L.append("; VECTORS Segment').")
    L.append(f"WORLD_PAL_COUNT = {len(palette_words)}")
    L.append(".pushseg")
    L.append('.segment "RODATA"')
    L.append("world_palette:")
    for i, w in enumerate(palette_words):
        L.append(f"    .word ${w:04X}    ; color {i}")
    L.append(".popseg")
    L.append("")
    return "\n".join(L) + "\n"


def main() -> None:
    tilemap = build_tilemap()
    collision = build_collision(tilemap)
    chr_data = build_chr()
    seed = build_seed(tilemap, chr_data)
    banks = build_flat_banks(tilemap)

    # palette: 256 entries, index i = colour of tile id i (flat tiles).  Only the
    # first N_TILES are meaningful; rest zero.
    pal = [0] * 256
    for t in range(N_TILES):
        pal[t] = rgb_to_bgr555(*RGB[t])

    assert len(seed) == 0x8000, len(seed)
    assert len(collision) == WORLD_T * WORLD_T
    (HERE / "world_seed.bin").write_bytes(seed)
    # collision is 64KB; ca65 .incbin can't span banks, so split into 32KB
    # bank files (collision bank N = world rows [N*128 .. N*128+127]).
    n_coll_banks = (len(collision) + 0x7FFF) // 0x8000
    for cb in range(n_coll_banks):
        chunk = collision[cb * 0x8000: (cb + 1) * 0x8000]
        (HERE / f"world_collision_bank{cb}.bin").write_bytes(chunk)
    for b, data in enumerate(banks):
        (HERE / f"world_flat_bank{b}.bin").write_bytes(data)
    (HERE / "world_stream.inc").write_text(emit_inc(pal[:N_TILES], len(banks)))

    # census for the header / sanity
    census = {}
    for t in tilemap:
        census[t] = census.get(t, 0) + 1
    print(f"world: {WORLD_T}x{WORLD_T} tiles, {N_TILES} authored tiles")
    print(f"  seed       : world_seed.bin ({len(seed)} bytes, initial 128x128 window)")
    print(f"  collision  : {n_coll_banks} x world_collision_bankN.bin ({len(collision)} bytes total, world-space 16-bit indexed)")
    print(f"  flat banks : {len(banks)} x world_flat_bankN.bin ({len(banks[0])} bytes each)")
    print(f"  tile census: {census}")
    # ground-truth landmarks (for the proof test)
    lm = [(tx, ty) for ty in range(0, WORLD_T, LANDMARK_STEP)
          for tx in range(0, WORLD_T, LANDMARK_STEP)]
    print(f"  landmarks  : {len(lm)} TOWN tiles on a {LANDMARK_STEP}-tile lattice")


if __name__ == "__main__":
    main()
