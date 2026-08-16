#!/usr/bin/env python3
"""gen_mode7_explore_assets.py — the mode7_explore rail's world, as .bin blobs.

Emits into $(BUILD)/assets (deterministic, byte-identical on re-run — pure
`math` over fixed sinusoid phases, no PRNG anywhere):

    m7x_seed.bin       32,768 B  the INTERLEAVED Mode 7 VRAM image for the
                                 initial 128x128 window: even byte = tilemap
                                 tile id, odd byte = the fixed 8bpp CHR set
    m7x_map.bin       262,144 B  the FLAT 512x512 tile-id world, 512 B/row,
                                 row-major. Bank-tiled by construction: 64
                                 rows = one 32 KB LoROM window, 8 chunks, so
                                 a DMA source never spans a bank
    m7x_pal.bin            24 B  12 BGR555 words, the world palette
    m7x_terr.bin          256 B  tile id -> terrain class (ONE BYTE PER TILE
                                 ID, not per world tile) — collision's LUT
    m7x_obj_chr.bin     1,216 B  38-tile 4bpp OBJ sheet: the avatar's three
                                 authored 16x16 facings at base tiles 16/18/20
    m7x_obj_pal.bin        32 B  16 BGR555 words, OBJ palette 0
    m7x_town_chr.bin      128 B  4 tiles x 32 B, the Mode 1 interior's 4bpp CHR
    m7x_town_pal.bin       32 B  16 BGR555 words, the interior palette
    m7x_world.inc                assembly-time equates ONLY (no data): world
                                 dims, spawn, demo house, the TERR_*/TILE_*
                                 vocabulary. Precedent: tools/gen_move_lut.py

Run:
    python3 tools/gen_mode7_explore_assets.py build/assets
    python3 tools/gen_mode7_explore_assets.py build/assets --verify   # re-emit
                                 and diff against what is already on disk

SELF-CONTAINED BY REQUIREMENT: this file imports nothing and names no path
outside the repo, so it runs identically on a bare checkout. Everything below
is authored here.

WORLD ART — the requirement this world is built to:

    The visible world uses an RPG overworld terrain vocabulary
    + palette flavour (grass / dirt-path / water / mountain / town), drawn as
    TEXTURED 8x8 tiles (a checker meadow, a dithered water ripple, a rocky
    mountain, a tiled road, a town-roof tile, a sand coast, a forest canopy) —
    NOT flat solid-colour blocks (that is what made the prior demo
    unconvincing) and NOT a synthetic position-id pattern (BANNED).

So every one of the eleven tiles below is an authored 8x8 pattern, and the
world under them is authored geography rather than a function of position.

=============================================================================
THE GEOGRAPHY ALGORITHM — what places what, in the order it is decided
=============================================================================

`terrain_at(tx, ty)` is the SINGLE SOURCE OF TRUTH. `tile_at()` derives the
rendered tile id from it, so what you SEE blocked is what collision rejects —
they cannot drift, because there is no second table. Collision at runtime is
then: read the flat tilemap byte in ROM, LUT it through m7x_terr.bin. That is
why there is no separate 256 KB collision map (two of them would not fit in a
512 KB ROM alongside the code).

The decision order is a PRIORITY CHAIN — each rule wins over everything below
it, and the order is load-bearing:

  1. SPAWN CLEARING — a 7x7 grass square centred on spawn (258,258). Forced
     first so the avatar can never boot boxed in by ocean or mountain.

  2. THE DEMO HOUSE at (254,254) and its APPROACH (tx 253..255, ty 254..257).
     The house is the ONE tile in the world carrying TERR_TOWN_ENTER; the
     approach is forced grass so the house is reachable from the clearing
     without depending on whatever geography the sinusoids put there. The
     house sits OFF both spawn axes deliberately: the axes are the road
     corridors a streaming sweep walks, and an on-axis enterable house would
     be stepped onto by a test that only meant to scroll.

  3. THE EXPLORER CORRIDORS — the spawn ROW and the spawn COLUMN, forced
     TERR_PATH across the whole camera-clamp box [64..447]. Checked BEFORE the
     height field so a mountain range can never sever them; over water they
     read as an authored causeway. This is what guarantees >= 3 windows of new
     content each axis without the avatar getting walled in.

  4. THE CLAMP RING — a 16-tile solid OCEAN band framing the clamp box, just
     OUTSIDE it on either axis. The camera is clamped to [64..447]; without
     this the avatar would stop on open ground against an invisible wall, so
     the band makes the stop diegetic: you reach a coastline.

  5. THE HEIGHT FIELD — everything else. `_height()` is a radial falloff
     (centre high, rim low, so the landmass is a continent ringed by ocean)
     plus five sinusoid octaves in NORMALISED [0,1] space with fixed phases.
     Then, in order:
       h < 0.30                  -> WATER    (ocean and inland lakes, BLOCKED)
       `_is_ridge`               -> MOUNTAIN (BLOCKED)
       `_on_road`                -> PATH
       otherwise                 -> GRASS

     `_is_ridge` = high ground (h > 0.70) AND a thin oriented ripple in
     sin((tx+ty)) / sin((tx-ty)), which is what makes ranges form connected
     DIAGONAL CHAINS instead of isolated dots.

     `_on_road` is the town road network: a vertical corridor near every
     32-tile town column and a horizontal one near every town row, each nudged
     +/-1 tile by a sinusoid of the other axis so the roads MEANDER and read as
     authored rather than as a rigid lattice. Roads are laid only over land
     because water/mountain are decided above them.

  6. THE TOWN LATTICE — last. A house at every (tx%32, ty%32) == (0,0) that
     landed on walkable land. Water and mountain lattice cells are SKIPPED, so
     no house ever floats in the ocean or buries itself in a peak. These carry
     TERR_TOWN (decorative, walkable, does NOT warp) — distinct from the demo
     house's TERR_TOWN_ENTER, which is the distinction that lets a streaming
     sweep cross a lattice house without entering the interior.

`tile_at()` then picks the VISUAL variant within a terrain class:
  - water and mountain alternate dark/light on (tx^ty)&1 — a fine dither that
    gives the surface motion under a moving camera
  - grass becomes COAST wherever a 4-neighbour is ocean (a sand beach band
    traced around every shoreline automatically)
  - grass becomes FOREST inside mid-elevation pockets (0.46 < h < 0.62) where
    a second ripple fires
  - otherwise a 2x2-block meadow checker, dark/light — the Mode 7 motion cue

=============================================================================
THE TWO PROPERTIES THAT ARE LOAD-BEARING
=============================================================================

**The seed uses the SAME VRAM-WRAPPED placement the streamer uses.** World
tile (wx,wy) lands at VRAM word `(wy & 127)*128 + (wx & 127)`, NOT at a
sequential `(vy*128 + vx)`. The Mode 7 tilemap is a 128x128 torus and the
streaming engine writes a leading-edge row/column into the slot the world
coordinate wraps to; if the seed used sequential placement the picture would
tear the first time a row was re-streamed. `verify_seed_placement()` below
proves the agreement rather than asserting it in prose.

**The Mode 7 CHR is baked into the seed's ODD bytes and never streams.** The
char set is 256 tiles x 64 B = 16,384 B, and the window is 128x128 = 16,384
words, so the CHR fills the high byte of every word exactly once. Only tilemap
LOW bytes stream. One DMA under forced blank in mode 1 drives VMDATAL/VMDATAH
alternately, and that alternation IS the interleave.
"""
from __future__ import annotations

import argparse
import functools
import math
import sys
from pathlib import Path

# --- world geometry ---------------------------------------------------------
WORLD_T = 512                       # world side, tiles
WORLD_PX = WORLD_T * 8              # 4096 px
ROWS_PER_BANK = 64                  # 64 rows * 512 B/row = 32768 = one window
COLS = WORLD_T                      # bytes per flat row
VRAM_WIN = 128                      # the Mode 7 VRAM tilemap is 128x128
CHR_TILES = 256                     # a Mode 7 char set is always all 256 slots
TILE_BYTES = 64                     # 8bpp 8x8

# --- terrain classes (what collision sees) ----------------------------------
TERR_GRASS = 0                      # walkable
TERR_PATH = 1                       # walkable (road)
TERR_WATER = 2                      # BLOCKED
TERR_MOUNTAIN = 3                   # BLOCKED
TERR_TOWN = 4                       # walkable landmark, DECORATIVE
TERR_TOWN_ENTER = 5                 # walkable landmark that ENTERS the town
BLOCKED = {TERR_WATER, TERR_MOUNTAIN}
# Blocking is a contiguous class RANGE test, which is why the two blocked
# classes are adjacent: the ROM compares against these two bounds, not a set.
TERR_BLOCKED_MIN = TERR_WATER
TERR_BLOCKED_MAX = TERR_MOUNTAIN

# --- tile ids (a tilemap low byte IS the CHR tile index) --------------------
TILE_GRASS_DK = 0                   # meadow checker base
TILE_GRASS_LT = 1                   # meadow checker highlight
TILE_PATH = 2                       # dirt road
TILE_WATER_DK = 3                   # water ripple (deep)
TILE_WATER_LT = 4                   # water ripple (shallow)
TILE_MTN_DK = 5                     # mountain rock (dark)
TILE_MTN_LT = 6                     # mountain rock (lit)
TILE_TOWN = 7                       # town roof — the decorative lattice house
TILE_COAST = 8                      # sand / coastline
TILE_FOREST = 9                     # forest canopy
TILE_TOWN_DOOR = 10                 # the ENTERABLE demo house (roof + door)
N_TILES = 11

# tile id -> terrain class. Emitted as the 256-byte LUT; ids outside the
# authored vocabulary fall back to GRASS so a stray byte can never read as a
# phantom wall.
TILE_TERRAIN = {
    TILE_GRASS_DK: TERR_GRASS, TILE_GRASS_LT: TERR_GRASS,
    TILE_PATH: TERR_PATH,
    TILE_WATER_DK: TERR_WATER, TILE_WATER_LT: TERR_WATER,
    TILE_MTN_DK: TERR_MOUNTAIN, TILE_MTN_LT: TERR_MOUNTAIN,
    TILE_TOWN: TERR_TOWN,
    TILE_COAST: TERR_GRASS,         # beach is walkable
    TILE_FOREST: TERR_GRASS,        # forest is walkable decoration
    TILE_TOWN_DOOR: TERR_TOWN_ENTER,
}

# --- the world palette: 12 BGR555 words, absolute CGRAM indices (Mode 7 is
#     8bpp and index 0 is also the backdrop slot, so tile 0 must be opaque
#     grass — this is a flat top-down view with no horizon showing through). -
PAL_RGB = {
    0:  (30, 92, 40),               # grass dark
    1:  (52, 130, 58),              # grass light
    2:  (176, 150, 96),             # dirt path
    3:  (24, 58, 140),              # water deep
    4:  (44, 92, 184),              # water shallow
    5:  (96, 84, 78),               # mountain dark
    6:  (150, 138, 128),            # mountain light
    7:  (208, 72, 56),              # town roof
    8:  (214, 198, 140),            # sand / coast
    9:  (26, 78, 42),               # forest dark
    10: (40, 104, 52),              # forest light
    11: (132, 110, 66),             # path edge (darker dirt)
}
N_COLORS = 12

# --- spawn, near the world centre so the proof can walk all four ways -------
SPAWN_TX = 258
SPAWN_TY = 258
SPAWN_CLEAR_R = 3                   # a (2R+1)^2 grass clearing around spawn

# --- the demo house: the ONE tile carrying TERR_TOWN_ENTER ------------------
DEMO_HOUSE_TX = 254
DEMO_HOUSE_TY = 254
DEMO_APPROACH_X0, DEMO_APPROACH_X1 = 253, 255
DEMO_APPROACH_Y0, DEMO_APPROACH_Y1 = 254, 257

# --- the camera-clamp box: the camera tile is clamped here so the 128 window
#     never crosses the world's toroidal seam. -----------------------------
CLAMP_MIN = 64                      # = the half-window
CLAMP_MAX = WORLD_T - 1 - 64        # = 447
CLAMP_RING_W = 16                   # the diegetic ocean band's width

LANDMARK_STEP = 32                  # the town lattice's spacing


def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    """A BGR555 word from 8-bit components — the hardware's colour layout."""
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


# =============================================================================
# Geography (see the priority chain in the module docstring)
# =============================================================================
@functools.lru_cache(maxsize=None)
def _height(tx: int, ty: int) -> float:
    """Smooth pseudo-elevation in [0,1] — high = inland, low = ocean.

    MEMOISED, and purely for speed: the coast rule samples four neighbours per
    tile, so a 512x512 world asks this ~1.3M times for 262,144 distinct
    answers. The cache changes no byte — same inputs, same float arithmetic.

    A radial falloff (a central continent, ocean at the rim) plus five
    sinusoid octaves at FIXED phases. Frequencies are in normalised [0,1]
    space so the geography's character is a property of the world, not of its
    tile count."""
    nx = tx / WORLD_T
    ny = ty / WORLD_T
    dx, dy = nx - 0.5, ny - 0.5
    radial = 1.0 - min(1.0, math.sqrt(dx * dx + dy * dy) / 0.60)
    n = 0.0
    for (fx, fy, ph, amp) in (
        (1.6, 1.6, 0.0, 0.50), (3.1, 1.7, 1.1, 0.26),
        (1.7, 3.3, 2.3, 0.20), (5.0, 4.0, 0.7, 0.12),
        (7.3, 5.7, 3.3, 0.08),
    ):
        n += amp * math.sin(fx * nx * math.pi * 2 + ph) * math.cos(fy * ny * math.pi * 2 + ph)
    n = (n + 1.0) * 0.5
    return max(0.0, min(1.0, 0.52 * radial + 0.58 * n))


def _is_ridge(tx: int, ty: int, h: float) -> bool:
    """A mountain RANGE: high ground plus a thin oriented ripple, so ranges
    form connected diagonal chains instead of isolated dots."""
    if h <= 0.70:
        return False
    ripple = math.sin((tx + ty) * 0.22) * 0.6 + math.sin((tx - ty) * 0.16) * 0.4
    return ripple > 0.05


def _is_forest(tx: int, ty: int, h: float) -> bool:
    """Forest pockets in the mid-elevation band (walkable decoration)."""
    if not (0.46 < h < 0.62):
        return False
    return math.sin(tx * 0.28 + 1.7) * math.cos(ty * 0.33 - 0.9) > 0.45


def _on_road(tx: int, ty: int) -> bool:
    """The town road network: a corridor near every town column and every town
    row, each nudged by a sinusoid of the OTHER axis so the roads meander."""
    if tx % LANDMARK_STEP == int(round(math.sin(ty * 0.13))) % LANDMARK_STEP:
        return True
    if ty % LANDMARK_STEP == int(round(math.sin(tx * 0.11))) % LANDMARK_STEP:
        return True
    return False


def _in_spawn_clearing(tx: int, ty: int) -> bool:
    return (abs(tx - SPAWN_TX) <= SPAWN_CLEAR_R
            and abs(ty - SPAWN_TY) <= SPAWN_CLEAR_R)


def _on_explorer_corridor(tx: int, ty: int) -> bool:
    """The spawn-row / spawn-column road, inside the camera-clamp box."""
    if ty == SPAWN_TY and CLAMP_MIN <= tx <= CLAMP_MAX:
        return True
    if tx == SPAWN_TX and CLAMP_MIN <= ty <= CLAMP_MAX:
        return True
    return False


def _in_clamp_ring(tx: int, ty: int) -> bool:
    """The ocean band framing the camera-clamp box — a CLAMP_RING_W strip just
    OUTSIDE [CLAMP_MIN..CLAMP_MAX] on either axis, so the clamp edge reads as
    a coastline rather than an invisible wall on open ground."""
    x_band = ((CLAMP_MIN - CLAMP_RING_W) <= tx < CLAMP_MIN
              or CLAMP_MAX < tx <= (CLAMP_MAX + CLAMP_RING_W))
    y_band = ((CLAMP_MIN - CLAMP_RING_W) <= ty < CLAMP_MIN
              or CLAMP_MAX < ty <= (CLAMP_MAX + CLAMP_RING_W))
    return x_band or y_band


def terrain_at(tx: int, ty: int) -> int:
    """THE SINGLE SOURCE OF TRUTH. The priority chain, in order."""
    if _in_spawn_clearing(tx, ty):
        return TERR_GRASS
    if tx == DEMO_HOUSE_TX and ty == DEMO_HOUSE_TY:
        return TERR_TOWN_ENTER
    if (DEMO_APPROACH_X0 <= tx <= DEMO_APPROACH_X1
            and DEMO_APPROACH_Y0 <= ty <= DEMO_APPROACH_Y1):
        return TERR_GRASS
    if _on_explorer_corridor(tx, ty):
        return TERR_PATH
    if _in_clamp_ring(tx, ty):
        return TERR_WATER
    h = _height(tx, ty)
    if h < 0.30:
        base = TERR_WATER
    elif _is_ridge(tx, ty, h):
        base = TERR_MOUNTAIN
    elif _on_road(tx, ty):
        base = TERR_PATH
    else:
        base = TERR_GRASS
    # the town lattice, last, and only where it landed on walkable land
    if tx % LANDMARK_STEP == 0 and ty % LANDMARK_STEP == 0 and base not in BLOCKED:
        return TERR_TOWN
    return base


def tile_at(tx: int, ty: int) -> int:
    """The rendered tile id, DERIVED from terrain_at so the two cannot drift."""
    terr = terrain_at(tx, ty)
    if terr == TERR_TOWN_ENTER:
        return TILE_TOWN_DOOR
    if terr == TERR_TOWN:
        return TILE_TOWN
    if terr == TERR_PATH:
        return TILE_PATH
    if terr == TERR_WATER:
        return TILE_WATER_LT if (tx ^ ty) & 1 else TILE_WATER_DK
    if terr == TERR_MOUNTAIN:
        return TILE_MTN_LT if (tx ^ ty) & 1 else TILE_MTN_DK
    # grass: pick the believable visual variant
    for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if _height((tx + dx) % WORLD_T, (ty + dy) % WORLD_T) < 0.30:
            return TILE_COAST           # a sand band wherever land meets ocean
    if _is_forest(tx, ty, _height(tx, ty)):
        return TILE_FOREST
    return TILE_GRASS_LT if ((tx >> 1) ^ (ty >> 1)) & 1 else TILE_GRASS_DK


# =============================================================================
# The authored 8x8 Mode 7 textures (8bpp — one PAL_RGB index per pixel)
# =============================================================================
# Hand-authored PATTERNS, not fills: a checker meadow, a dithered water ripple,
# a rocky face, a seamed dirt road, a pitched roof, a grainy beach, a clustered
# canopy. Every tile carries REAL TEXTURE over the terrain palette: a
# flat-colour or position-id world is explicitly banned, because a Mode 7
# plane of flat cells gives the eye nothing to track and the rail's whole
# subject is motion over ground.
def _tex(rows) -> bytes:
    """8 strings of 8 hex chars -> 64 palette-index bytes."""
    assert len(rows) == 8, rows
    out = bytearray(64)
    for y, r in enumerate(rows):
        assert len(r) == 8, r
        for x, c in enumerate(r):
            out[y * 8 + x] = int(c, 16)
    return bytes(out)


TEX = {
    # meadow: a fine 2-tone checker, dark base and light variant
    TILE_GRASS_DK: _tex([
        "00010001", "01000100", "00010001", "00000000",
        "00010001", "01000100", "00010001", "00000000",
    ]),
    TILE_GRASS_LT: _tex([
        "11011101", "10111011", "11011101", "11111111",
        "11011101", "10111011", "11011101", "11111111",
    ]),
    # dirt road: tan fill with a darker (B) seam grid -> reads as paved
    TILE_PATH: _tex([
        "2222222B", "22222222", "22222222", "2222222B",
        "2222222B", "22222222", "22222222", "BBBBBBBB",
    ]),
    # water: deep blue with shallow ripple diagonals, and the lit variant
    TILE_WATER_DK: _tex([
        "33334333", "33343333", "33433333", "34333334",
        "43333343", "33333433", "33334333", "33343333",
    ]),
    TILE_WATER_LT: _tex([
        "44443444", "44434444", "44344444", "43444443",
        "34444434", "44444344", "44443444", "44434444",
    ]),
    # mountain: a rocky face, base 5 with 6 highlight ridges, and the lit one
    TILE_MTN_DK: _tex([
        "55655655", "56555565", "55556555", "55655655",
        "65555556", "55655655", "56555565", "55556555",
    ]),
    TILE_MTN_LT: _tex([
        "66566566", "65666656", "66665666", "66566566",
        "56666665", "66566566", "65666656", "66665666",
    ]),
    # the decorative lattice house: a red pitched roof over sand-tan walls with
    # dark windows. The 0 corners fall back to grass-dark, so the house NESTS
    # in the meadow instead of reading as a flat red block.
    TILE_TOWN: _tex([
        "00077000", "00777700", "07777770", "77777777",
        "08888880", "08588580", "08855880", "08855880",
    ]),
    # THE ENTERABLE house: the same roof, but with a tall bright DOOR framed by
    # dark posts — so the avatar can SEE which house is the one that enters.
    TILE_TOWN_DOOR: _tex([
        "00077000", "00777700", "07777770", "77777777",
        "08888880", "08849880", "08849880", "08849880",
    ]),
    # sand: a tan beach with a few darker grains
    TILE_COAST: _tex([
        "88828888", "88888828", "82888888", "88888288",
        "88828888", "88888828", "82888888", "88888288",
    ]),
    # forest: dark/light green clustered foliage
    TILE_FOREST: _tex([
        "9A9AA9A9", "AA9A9AAA", "9A9AA9A9", "AAA9A9AA",
        "9A9AA9A9", "AA9A9AAA", "9A9AA9A9", "AAA9A9AA",
    ]),
}


def build_chr() -> bytes:
    """The fixed 256-tile 8bpp Mode 7 char set, tile-major: tile T's 64 bytes
    at offset T*64. Tiles 0..N_TILES-1 are the authored textures; the rest are
    zero. A Mode 7 char set always occupies all 256 slots = 16,384 B, which is
    exactly the 128x128 window's word count — so it fills the seed's odd bytes
    once, with nothing left over."""
    out = bytearray(CHR_TILES * TILE_BYTES)
    for t in range(N_TILES):
        out[t * TILE_BYTES:(t + 1) * TILE_BYTES] = TEX[t]
    assert len(out) == VRAM_WIN * VRAM_WIN, "CHR must fill exactly one window's odd bytes"
    return bytes(out)


def build_palette() -> bytes:
    """12 BGR555 words, little-endian."""
    out = bytearray()
    for i in range(N_COLORS):
        w = rgb_to_bgr555(*PAL_RGB[i])
        out.append(w & 0xFF)
        out.append(w >> 8)
    return bytes(out)


# =============================================================================
# The avatar OBJ sheet — three authored 16x16 facings
# =============================================================================
# A 16x16 OBJ is the PPU quad {N, N+1, N+16, N+17} — the lower half is +16 tile
# numbers away, not +2 — so the sheet is a 38-tile grid with content at the
# three quads and zero tiles between the rows. That padding is the hardware's
# alignment, not slack.
#
#   DOWN  base 16 -> {16,17,32,33}   front view, face + eyes
#   UP    base 18 -> {18,19,34,35}   back view, hair only, no face
#   SIDE  base 20 -> {20,21,36,37}   RIGHT profile; LEFT is this H-FLIPPED via
#                                    the free OAM attribute bit, so there is no
#                                    fourth sprite to author or to ship
AVATAR_BASE_TILE = 16
AVATAR_TILE_DOWN = 16
AVATAR_TILE_UP = 18
AVATAR_TILE_SIDE = 20
AVATAR_TILE_MAX = AVATAR_TILE_SIDE + 17     # 37 — the highest tile occupied

# OBJ palette 0. Three distinct PURPLE robe shades read against grass, road,
# water AND sand — none of the Mode 7 terrain tones are purple — so the avatar
# can never be mistaken for terrain by eye or by a classifier.
OBJ_PAL = [
    (0, 0, 0),                      # 0 transparent
    (242, 214, 176),                # 1 skin
    (126, 52, 166),                 # 2 robe purple (mid)
    (74, 26, 104),                  # 3 robe purple (dark)
    (26, 26, 36),                   # 4 outline / boots
    (72, 46, 34),                   # 5 hair
    (250, 250, 236),                # 6 highlight
    (176, 108, 210),                # 7 robe purple (light)
    (168, 120, 56),                 # 8 staff shaft
    (255, 202, 82),                 # 9 staff tip
    (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0),
]

# FRONT (walking down): hair frames the face, two eyes, a robe that FLARES at
# the hem, the staff held on the viewer-left with its gold tip up.
AVATAR_DOWN = [
    "0000055555500000", "0090555555550000", "0080551111550000",
    "0080511111150000", "0080514114150000", "0080511111150000",
    "0080551111550000", "0081322222231000", "0080272222272000",
    "0080222222222000", "0000322222223000", "0000322222223000",
    "0003222222222300", "0032222222222230", "0032722222272300",
    "0003300440330000",
]

# BACK (walking up): the same silhouette from behind — all hair, no face.
AVATAR_UP = [
    "0000055555500000", "0090555555550000", "0080555555550000",
    "0080555555550000", "0080555555550000", "0080555555550000",
    "0080555555550000", "0081322222231000", "0080272222272000",
    "0080222222222000", "0000322222223000", "0000322222223000",
    "0003222222222300", "0032222222222230", "0032722222272300",
    "0003300440330000",
]

# SIDE, facing RIGHT: hair swept back, one eye, the staff held FORWARD on the
# leading side, robe flaring behind the stride. LEFT is this H-flipped, which
# puts the staff on the leading side there too.
AVATAR_SIDE = [
    "0000555550000000", "0005555511009000", "0055555111008000",
    "0055551141108000", "0005551111108000", "0000551111108000",
    "0000322222218000", "0003222222281000", "0003272222280000",
    "0003222222200000", "0003222222230000", "0003222222230000",
    "0032222222223000", "0322222222223000", "0327222222232000",
    "0033004400330000",
]

AVATAR_FACINGS = (
    (AVATAR_DOWN, AVATAR_TILE_DOWN),
    (AVATAR_UP, AVATAR_TILE_UP),
    (AVATAR_SIDE, AVATAR_TILE_SIDE),
)


def _split_quad(grid16):
    """A 16x16 index grid -> the four 8x8 grids of the PPU quad (TL,TR,BL,BR)."""
    assert len(grid16) == 16, f"avatar grid must be 16 rows, got {len(grid16)}"
    for r in grid16:
        assert len(r) == 16, f"avatar row must be 16 cols: {r!r}"
    g = [[int(c, 16) for c in row] for row in grid16]
    return ([r[0:8] for r in g[0:8]], [r[8:16] for r in g[0:8]],
            [r[0:8] for r in g[8:16]], [r[8:16] for r in g[8:16]])


def encode_4bpp(tile) -> bytes:
    """An 8x8 index grid (0..15) -> SNES 4bpp planar, 32 B: bitplanes 0/1
    interleaved by row for eight rows, then bitplanes 2/3 the same way."""
    out = bytearray()
    for lo, hi in ((0, 1), (2, 3)):
        for row in tile:
            a = b = 0
            for x, idx in enumerate(row):
                assert 0 <= idx <= 15, idx
                bit = 7 - x
                a |= ((idx >> lo) & 1) << bit
                b |= ((idx >> hi) & 1) << bit
            out.append(a)
            out.append(b)
    return bytes(out)


def build_obj_chr() -> bytes:
    """The 38-tile 4bpp OBJ sheet, three facings on the PPU's 16-wide grid."""
    empty = [[0] * 8 for _ in range(8)]
    tiles = [empty] * (AVATAR_TILE_MAX + 1)
    for grid, base in AVATAR_FACINGS:
        tl, tr, bl, br = _split_quad(grid)
        tiles[base], tiles[base + 1] = tl, tr
        tiles[base + 16], tiles[base + 17] = bl, br
    return b"".join(encode_4bpp(t) for t in tiles)


def build_pal16(pal_rgb) -> bytes:
    """16 BGR555 words, little-endian. A 4bpp palette is 16 entries whether or
    not the art uses them all."""
    assert len(pal_rgb) == 16, len(pal_rgb)
    out = bytearray()
    for c in pal_rgb:
        w = rgb_to_bgr555(*c)
        out.append(w & 0xFF)
        out.append(w >> 8)
    return bytes(out)


# =============================================================================
# The Mode 1 town interior — a small single-screen room
# =============================================================================
# Stepping onto the demo house mosaic-swaps from the streaming Mode 7 overworld
# to this interior: a plank floor, stone walls, a table, and an exit door.
# Colour 0 is the floor base AND the backdrop, so gaps read as floor.
TOWN_TILE_FLOOR = 0
TOWN_TILE_WALL = 1
TOWN_TILE_DOOR = 2
TOWN_TILE_TABLE = 3
TOWN_N_TILES = 4

TOWN_PAL_RGB = [
    (72, 52, 34),                   # 0  floor base — ALSO the backdrop
    (104, 78, 50),                  # 1  floor light (plank face)
    (52, 36, 24),                   # 2  floor dark (plank seam)
    (96, 100, 112),                 # 3  wall base (cool stone)
    (140, 146, 158),                # 4  wall light (lit brick)
    (60, 62, 72),                   # 5  wall dark (mortar / shadow)
    (150, 96, 44),                  # 6  door wood
    (196, 140, 70),                 # 7  door light (planks)
    (40, 26, 16),                   # 8  door frame / dark
    (120, 82, 42),                  # 9  table wood
    (168, 120, 64),                 # 10 table top (lit)
    (36, 24, 14),                   # 11 table legs / shadow
    (214, 198, 140),                # 12 warm highlight (knob / sheen)
    (0, 0, 0), (0, 0, 0), (0, 0, 0),
]

TOWN_TEX = {
    # plank floor: a light face with darker seams
    TOWN_TILE_FLOOR: [
        "11111112", "11111112", "11111112", "22222222",
        "11111112", "11111112", "11111112", "22222222",
    ],
    # stone wall: brick courses with offset rows and a mortar seam
    TOWN_TILE_WALL: [
        "44444444", "33333335", "33333335", "55555555",
        "44444444", "53333333", "53333333", "55555555",
    ],
    # exit door: wood planks in a dark frame, with a bright knob
    TOWN_TILE_DOOR: [
        "88888888", "87676768", "87676768", "8767676C",
        "87676768", "87676768", "87676768", "88888888",
    ],
    # table: a lit top slab on dark legs, floor showing around it
    TOWN_TILE_TABLE: [
        "00000000", "0AAAAAA0", "A999999A", "A999999A",
        "0B0000B0", "0B0000B0", "0B0000B0", "00000000",
    ],
}


def build_town_chr() -> bytes:
    """4 tiles x 32 B of 4bpp BG1 CHR for the interior."""
    out = bytearray()
    for t in range(TOWN_N_TILES):
        rows = TOWN_TEX[t]
        assert len(rows) == 8, rows
        grid = []
        for r in rows:
            assert len(r) == 8, r
            grid.append([int(c, 16) for c in r])
        out += encode_4bpp(grid)
    return bytes(out)


# =============================================================================
# The world, and the seed
# =============================================================================
def build_tilemap() -> bytes:
    """The flat 512x512 tile-id grid, row-major, 512 B/row.

    BANK-TILED BY CONSTRUCTION rather than by a later split: 64 rows are
    exactly 32,768 B, so chunk k of the emitted blob is rows 64k..64k+63 and a
    DMA source inside it can never span a bank. The .incbin site slices this
    one file by offset, which is what `world_rom`'s claim site already does."""
    out = bytearray(WORLD_T * WORLD_T)
    for ty in range(WORLD_T):
        base = ty * WORLD_T
        for tx in range(WORLD_T):
            out[base + tx] = tile_at(tx, ty)
    assert WORLD_T * COLS // ROWS_PER_BANK  # silence nothing; shape below
    assert ROWS_PER_BANK * COLS == 32768, "a chunk must be exactly one window"
    return bytes(out)


def build_terrain_lut() -> bytes:
    """The 256-byte tile-id -> terrain-class LUT.

    ONE BYTE PER TILE ID, not per world tile — that is the whole point. A
    byte-per-world-tile collision map would be another 256 KB and the two
    together do not fit in a 512 KB ROM. Collision is instead
    `terr[ map[ty*512 + tx] ]`: a ROM read and a LUT.

    Ids outside the authored vocabulary map to GRASS, so a stray byte reads as
    walkable rather than as a phantom wall."""
    return bytes(TILE_TERRAIN.get(i, TERR_GRASS) for i in range(256))


def build_seed(tilemap: bytes, chr_data: bytes) -> bytes:
    """The 32 KB interleaved Mode 7 VRAM seed for the initial window.

    THE WRAPPED PLACEMENT IS THE POINT. World tile (wx,wy) lands at VRAM word
    `(wy & 127)*128 + (wx & 127)`, NOT at a sequential `(vy*128 + vx)`. The
    Mode 7 tilemap is a 128x128 torus; the streamer writes each leading-edge
    row/column into the slot its world coordinate wraps to, so a seed built
    sequentially would disagree with the streamer the first time a row was
    re-written — the picture tears at the first step.

    Even byte = tile id (streams). Odd byte = the fixed CHR (never streams).
    One DMA under forced blank in mode 1 drives VMDATAL/VMDATAH alternately,
    and that alternation IS this interleave."""
    out = bytearray(VRAM_WIN * VRAM_WIN * 2)
    win_x0 = (SPAWN_TX - VRAM_WIN // 2) % WORLD_T
    win_y0 = (SPAWN_TY - VRAM_WIN // 2) % WORLD_T
    for dy in range(VRAM_WIN):
        wy = (win_y0 + dy) % WORLD_T
        vy = wy & (VRAM_WIN - 1)
        for dx in range(VRAM_WIN):
            wx = (win_x0 + dx) % WORLD_T
            vx = wx & (VRAM_WIN - 1)
            word = vy * VRAM_WIN + vx
            out[word * 2] = tilemap[wy * WORLD_T + wx]
            out[word * 2 + 1] = chr_data[word]
    return bytes(out)


# =============================================================================
# Generation-time gates — the properties that must hold for the rail to work
# =============================================================================
def verify_seed_placement(seed: bytes, tilemap: bytes, samples) -> list:
    """Prove the seed's even bytes sit at the WRAPPED VRAM word, independently:
    the word index is recomputed here from (wx,wy) rather than read back out of
    build_seed's own loop, so this cannot agree by sharing the bug."""
    lines = []
    win_x0 = (SPAWN_TX - VRAM_WIN // 2) % WORLD_T
    win_y0 = (SPAWN_TY - VRAM_WIN // 2) % WORLD_T
    for (wx, wy) in samples:
        # The wrapped identity holds only for tiles the seed actually placed.
        # Outside the window, the same VRAM word legitimately belongs to a
        # DIFFERENT world tile 128 away — that is the torus working, not a bug.
        # Refuse an out-of-window sample by name: a checker that silently
        # compared the wrong tile would report a defect that is not there,
        # which is exactly what a bad sample did while this was being written.
        if not (0 <= (wx - win_x0) % WORLD_T < VRAM_WIN
                and 0 <= (wy - win_y0) % WORLD_T < VRAM_WIN):
            raise SystemExit(
                f"gen_mode7_explore_assets: sample ({wx},{wy}) is OUTSIDE the "
                f"seeded window x[{win_x0}..{win_x0 + VRAM_WIN - 1}] "
                f"y[{win_y0}..{win_y0 + VRAM_WIN - 1}] — its VRAM word belongs "
                f"to another tile. Pick a sample inside the window.")
        word = (wy & (VRAM_WIN - 1)) * VRAM_WIN + (wx & (VRAM_WIN - 1))
        got = seed[word * 2]
        want = tilemap[wy * WORLD_T + wx]
        if got != want:
            raise SystemExit(
                f"gen_mode7_explore_assets: seed placement is WRONG at world "
                f"({wx},{wy}): VRAM word {word} holds tile {got}, the flat "
                f"tilemap holds {want}")
        lines.append(f"world ({wx:3d},{wy:3d}) -> VRAM word {word:5d} "
                     f"= (wy&127)*128 + (wx&127) -> tile id {got} (matches map)")
    return lines


def verify_world(tilemap: bytes) -> list:
    """The gates the rail's playability depends on. Each RAISES rather than
    warns — a world that fails one of these is not shippable, and a generator
    that emits it anyway is the shape a later slice debugs on the emulator."""
    notes = []

    # 1 · exactly ONE enterable house in the whole world. If a decorative
    #     lattice house ever picked up TERR_TOWN_ENTER, a streaming sweep
    #     crossing it would warp into the interior mid-test.
    n_enter = sum(1 for b in tilemap if TILE_TERRAIN.get(b) == TERR_TOWN_ENTER)
    if n_enter != 1:
        raise SystemExit(f"gen_mode7_explore_assets: {n_enter} tiles carry "
                         f"TERR_TOWN_ENTER, must be exactly 1")
    if tilemap[DEMO_HOUSE_TY * WORLD_T + DEMO_HOUSE_TX] != TILE_TOWN_DOOR:
        raise SystemExit("gen_mode7_explore_assets: the demo house is not at "
                         f"({DEMO_HOUSE_TX},{DEMO_HOUSE_TY})")
    notes.append(f"exactly 1 TERR_TOWN_ENTER tile, at ({DEMO_HOUSE_TX},"
                 f"{DEMO_HOUSE_TY}); the lattice houses are all TERR_TOWN")

    # 2 · the demo house is OFF both spawn axes — those are the corridors a
    #     streaming sweep walks, and an on-axis enterable house gets stepped on.
    if DEMO_HOUSE_TX == SPAWN_TX or DEMO_HOUSE_TY == SPAWN_TY:
        raise SystemExit("gen_mode7_explore_assets: the demo house is on a "
                         "spawn axis — a streaming sweep would warp into town")
    notes.append("demo house is off both spawn axes")

    # 3 · the spawn is not boxed in: a 6-tile walkable run each cardinal way,
    #     so streaming actually fires from boot.
    run = 6
    for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for k in range(1, run + 1):
            tx, ty = (SPAWN_TX + dx * k) % WORLD_T, (SPAWN_TY + dy * k) % WORLD_T
            if terrain_at(tx, ty) in BLOCKED:
                raise SystemExit(
                    f"gen_mode7_explore_assets: spawn ({SPAWN_TX},{SPAWN_TY}) "
                    f"is boxed in — blocked at ({tx},{ty}), {k} tiles along "
                    f"({dx},{dy}). Streaming would not fire from boot.")
    notes.append(f"spawn ({SPAWN_TX},{SPAWN_TY}): {run}-tile open run each way")

    # 4 · the house is walkable-reachable from the spawn (BFS over walkable).
    seen = {(SPAWN_TX, SPAWN_TY)}
    frontier = [(SPAWN_TX, SPAWN_TY)]
    while frontier and (DEMO_HOUSE_TX, DEMO_HOUSE_TY) not in seen:
        cx, cy = frontier.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = ((cx + dx) % WORLD_T, (cy + dy) % WORLD_T)
            if nb not in seen and terrain_at(*nb) not in BLOCKED:
                seen.add(nb)
                frontier.append(nb)
    if (DEMO_HOUSE_TX, DEMO_HOUSE_TY) not in seen:
        raise SystemExit("gen_mode7_explore_assets: the demo house is not "
                         "walkable-reachable from spawn")
    notes.append("demo house is walkable-reachable from spawn")

    # 5 · the camera-clamp box gives >= 3 windows of DISTINCT content each
    #     axis. Camera travel is [64..447]; the window shows cam-64..cam+63, so
    #     the tiles ever seen span travel + 128.
    travel = CLAMP_MAX - CLAMP_MIN
    content_windows = (travel + VRAM_WIN) / float(VRAM_WIN)
    if content_windows < 3.0:
        raise SystemExit(f"gen_mode7_explore_assets: only "
                         f"{content_windows:.2f} windows of distinct content")
    notes.append(f"camera travel {travel} tiles/axis = "
                 f"{travel / float(VRAM_WIN):.2f} windows of camera motion, "
                 f"{content_windows:.2f} windows of distinct content")

    # 6 · the world is not a flat fill and not a position-id pattern: every
    #     authored tile must actually appear. A vocabulary entry that never
    #     occurs is art nobody will ever see, and the whole-world census below
    #     is what makes "believable geography" checkable rather than asserted.
    census = {}
    for b in tilemap:
        census[b] = census.get(b, 0) + 1
    missing = [t for t in range(N_TILES) if census.get(t, 0) == 0]
    if missing:
        raise SystemExit(f"gen_mode7_explore_assets: tile id(s) {missing} "
                         f"never appear in the world")
    notes.append("all 11 authored tile ids occur in the world")
    return notes, census


# =============================================================================
# Emitters
# =============================================================================
def emit_inc() -> str:
    """m7x_world.inc — assembly-time EQUATES ONLY, no data. Every byte of data
    ships as a .bin the allocator places; this file is just the vocabulary the
    rail's .asm and the game logic bind against. Precedent for a generated
    .inc alongside .bin blobs: tools/gen_move_lut.py."""
    L = [
        "; m7x_world.inc — mode7_explore world constants (GENERATED — do not edit)",
        "; Regenerate: python3 tools/gen_mode7_explore_assets.py $(BUILD)/assets",
        ";",
        "; EQUATES ONLY. The data lives in the m7x_* .bin blobs, placed by the",
        "; allocator through m7x_rom's claims. Nothing here is an address.",
        "",
        "; --- world geometry ---",
        f"M7X_WORLD_T      = {WORLD_T}      ; world side, tiles",
        f"M7X_WORLD_PX     = {WORLD_PX}     ; world side, px",
        f"M7X_WRAP_MASK    = {WORLD_T - 1}      ; (tile coord) & this wraps 0..{WORLD_T - 1}",
        f"M7X_COLS_BYTES   = {COLS}      ; bytes per flat tilemap row",
        f"M7X_ROWS_PER_BANK = {ROWS_PER_BANK}      ; rows per 32 KB chunk",
        f"M7X_VRAM_WIN     = {VRAM_WIN}      ; the Mode 7 tilemap is this square",
        "",
        "; --- spawn, and the camera clamp that keeps the window off the seam ---",
        f"M7X_SPAWN_TX     = {SPAWN_TX}",
        f"M7X_SPAWN_TY     = {SPAWN_TY}",
        f"M7X_CLAMP_MIN    = {CLAMP_MIN}",
        f"M7X_CLAMP_MAX    = {CLAMP_MAX}",
        "",
        "; --- the ONE enterable house. Stepping onto this tile triggers the",
        ";     Mode 1 interior; the decorative lattice houses do NOT. ---",
        f"M7X_DEMO_HOUSE_TX = {DEMO_HOUSE_TX}",
        f"M7X_DEMO_HOUSE_TY = {DEMO_HOUSE_TY}",
        f"M7X_LANDMARK_STEP = {LANDMARK_STEP}      ; the decorative town lattice",
        "",
        "; --- terrain classes. BLOCKED is a contiguous RANGE test against the",
        ";     two bounds, not a set membership. ---",
        f"M7X_TERR_GRASS      = {TERR_GRASS}",
        f"M7X_TERR_PATH       = {TERR_PATH}",
        f"M7X_TERR_WATER      = {TERR_WATER}      ; BLOCKED",
        f"M7X_TERR_MOUNTAIN   = {TERR_MOUNTAIN}      ; BLOCKED",
        f"M7X_TERR_TOWN       = {TERR_TOWN}      ; walkable, decorative",
        f"M7X_TERR_TOWN_ENTER = {TERR_TOWN_ENTER}      ; walkable, ENTERS the town",
        f"M7X_TERR_BLOCKED_MIN = {TERR_BLOCKED_MIN}",
        f"M7X_TERR_BLOCKED_MAX = {TERR_BLOCKED_MAX}",
        "",
        "; --- tile ids (a tilemap low byte IS the CHR tile index) ---",
        f"M7X_TILE_GRASS_DK  = {TILE_GRASS_DK}",
        f"M7X_TILE_GRASS_LT  = {TILE_GRASS_LT}",
        f"M7X_TILE_PATH      = {TILE_PATH}",
        f"M7X_TILE_WATER_DK  = {TILE_WATER_DK}",
        f"M7X_TILE_WATER_LT  = {TILE_WATER_LT}",
        f"M7X_TILE_MTN_DK    = {TILE_MTN_DK}",
        f"M7X_TILE_MTN_LT    = {TILE_MTN_LT}",
        f"M7X_TILE_TOWN      = {TILE_TOWN}",
        f"M7X_TILE_COAST     = {TILE_COAST}",
        f"M7X_TILE_FOREST    = {TILE_FOREST}",
        f"M7X_TILE_TOWN_DOOR = {TILE_TOWN_DOOR}",
        f"M7X_N_TILES        = {N_TILES}",
        "",
        "; --- the avatar's OBJ tile grid: 16x16 quads {N,N+1,N+16,N+17}.",
        ";     LEFT is SIDE H-flipped via the OAM attribute bit — no fourth",
        ";     sprite is authored or shipped. ---",
        f"M7X_AVATAR_TILE_DOWN = {AVATAR_TILE_DOWN}",
        f"M7X_AVATAR_TILE_UP   = {AVATAR_TILE_UP}",
        f"M7X_AVATAR_TILE_SIDE = {AVATAR_TILE_SIDE}",
        f"M7X_AVATAR_TILES     = {AVATAR_TILE_MAX + 1}      ; the sheet's tile count",
        "",
        "; --- the Mode 1 interior's tile ids ---",
        f"M7X_TOWN_TILE_FLOOR = {TOWN_TILE_FLOOR}",
        f"M7X_TOWN_TILE_WALL  = {TOWN_TILE_WALL}",
        f"M7X_TOWN_TILE_DOOR  = {TOWN_TILE_DOOR}",
        f"M7X_TOWN_TILE_TABLE = {TOWN_TILE_TABLE}",
        "",
    ]
    return "\n".join(L)


def write(path: Path, blob: bytes, made: list, verify: bool) -> None:
    """Write, or — under --verify — compare against what is already there and
    refuse on any difference. The verify arm is the determinism check: it is
    the same generator's second run judged against its first."""
    if verify:
        if not path.exists():
            raise SystemExit(f"--verify: {path} does not exist")
        old = path.read_bytes()
        if old != blob:
            raise SystemExit(f"--verify: {path} DIFFERS — {len(old)} B on disk "
                             f"vs {len(blob)} B regenerated (NOT deterministic)")
        made.append(f"{path.name} ({len(blob)} B, identical)")
        return
    path.write_bytes(blob)
    made.append(f"{path.name} ({len(blob)} B)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir", help="directory to write the .bin blobs into")
    ap.add_argument("--verify", action="store_true",
                    help="regenerate and compare against what is on disk "
                         "instead of writing — the determinism check")
    args = ap.parse_args(argv)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    tilemap = build_tilemap()
    chr_data = build_chr()
    seed = build_seed(tilemap, chr_data)
    terr = build_terrain_lut()

    assert len(tilemap) == 0x40000, len(tilemap)
    assert len(seed) == 0x8000, len(seed)
    assert len(terr) == 256, len(terr)

    made: list = []
    write(out / "m7x_map.bin", tilemap, made, args.verify)
    write(out / "m7x_seed.bin", seed, made, args.verify)
    write(out / "m7x_pal.bin", build_palette(), made, args.verify)
    write(out / "m7x_terr.bin", terr, made, args.verify)
    write(out / "m7x_obj_chr.bin", build_obj_chr(), made, args.verify)
    write(out / "m7x_obj_pal.bin", build_pal16(OBJ_PAL), made, args.verify)
    write(out / "m7x_town_chr.bin", build_town_chr(), made, args.verify)
    write(out / "m7x_town_pal.bin", build_pal16(TOWN_PAL_RGB), made, args.verify)
    write(out / "m7x_world.inc", emit_inc().encode(), made, args.verify)

    notes, census = verify_world(tilemap)
    # Three samples inside the seeded window x[194..321] y[194..321], chosen to
    # straddle the 256 boundary the wrap turns on: every one has a world
    # coordinate >= 128, so `wx & 127` is a REAL wrap in each case and a
    # sequential (vy*128+vx) seed would fail all three.
    notes += verify_seed_placement(seed, tilemap, (
        (SPAWN_TX, SPAWN_TY),                       # (258,258) — above 256
        (DEMO_HOUSE_TX, DEMO_HOUSE_TY),             # (254,254) — below 256
        (SPAWN_TX - VRAM_WIN // 2, SPAWN_TY + VRAM_WIN // 2 - 1),
    ))                                              # (194,321) — mixed sides
    # the CHR occupies the odd bytes and NOTHING else does
    if bytes(seed[1::2]) != chr_data:
        raise SystemExit("gen_mode7_explore_assets: the seed's odd bytes are "
                         "not the CHR set")
    notes.append("seed odd bytes == the 16,384 B CHR set, exactly")

    names = {TILE_GRASS_DK: "grass_dk", TILE_GRASS_LT: "grass_lt",
             TILE_PATH: "path", TILE_WATER_DK: "water_dk",
             TILE_WATER_LT: "water_lt", TILE_MTN_DK: "mtn_dk",
             TILE_MTN_LT: "mtn_lt", TILE_TOWN: "town", TILE_COAST: "coast",
             TILE_FOREST: "forest", TILE_TOWN_DOOR: "town_door"}
    total = float(len(tilemap))
    print("gen_mode7_explore_assets: " + ", ".join(made))
    for n in notes:
        print("  " + n)
    print("  world census (share of 512x512):")
    for t in range(N_TILES):
        print(f"    {t:2d} {names[t]:<10} {census.get(t, 0):7d}  "
              f"{100.0 * census.get(t, 0) / total:5.2f}%")
    lattice = (WORLD_T // LANDMARK_STEP) ** 2
    print(f"  {census.get(TILE_TOWN, 0)} decorative houses on the "
          f"{LANDMARK_STEP}-tile lattice ({lattice} points, "
          f"{lattice - census.get(TILE_TOWN, 0)} skipped over water/mountain)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
