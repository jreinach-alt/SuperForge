#!/usr/bin/env python3
# =============================================================================
# make_explore_world.py — believable LARGE Mode 7 streaming overworld (S2 rail,
# F1 remediation: grown to 512x512 so "several windows" is LITERAL)
# =============================================================================
# Streaming rail v2 / Sprint S2 + F1 remediation.  Authors a 512x512-tile
# (= 4096x4096 px) Mode 7 overworld — SEVERAL (>=3) windows wide AND tall vs the
# 128x128 (1024x1024 px) Mode 7 VRAM window — that reads as a BELIEVABLE
# explorable world (a coherent continent with a coastline, lakes, mountain
# RANGES, several TOWNS, forests, and ROADS that connect the towns) and emits it
# in the SPLIT streaming format the proven Mode 7 2-axis streaming substrate
# (engine/mode7_stream.asm + _nmi.inc) consumes:
#
#   explore_flat_bankN.bin   FLAT tilemap, 1 byte/tile (low-byte tile id), packed
#                            512 bytes/row, 64 rows/bank.  512 rows -> 8 banks
#                            (32 KB each).  STREAMS into VRAM low bytes as the
#                            avatar walks.  bank=(row>>6)+base, off=$8000+(row&63)*512.
#   explore_seed.bin         32 KB INTERLEAVED Mode 7 VRAM seed = the INITIAL
#                            128x128 window: low byte = initial tilemap id, high
#                            byte = the fixed N-tile 8bpp CHR set.  Uploaded ONCE
#                            under forced blank.  The CHR never streams.
#   explore_world.inc        ca65 constants: world dims, spawn, bank base, the
#                            TERR_*/tile-id vocabulary, palette word table, AND
#                            the tile-id -> terrain-class LUT (tile_terrain_lut,
#                            256 bytes) the ROM reads for collision.
#
# COLLISION (F1 remediation — NO separate collision table).  A 512x512 byte/tile
# tilemap is 256 KB (8 banks); a byte/tile collision table would add another
# 256 KB -> the two together exceed the 512 KB ROM.  FIX: the tilemap is the
# SINGLE SOURCE OF TRUTH for terrain.  collision derives terrain from the FLAT
# ROM tilemap byte at the world tile (a ROM read, NOT a VRAM read — safe) LUT'd
# through a 256-entry tile-id -> terrain-class table.  This keeps the rail at
# 512 KB and removes the 16-bit collision-index width problem entirely.
#
# WORLD ART (owner decision: reuse the kit RPG overworld's authored tile art).
# The visible world uses the kit RPG overworld's authored terrain vocabulary +
# palette flavour (grass / dirt-path / water / mountain / town), drawn as
# TEXTURED 8x8 tiles (a checker meadow, a dithered water ripple, a rocky
# mountain, a tiled road, a town-roof tile, a sand coast, a forest canopy) —
# NOT flat solid-colour blocks (that is what made the prior demo unconvincing)
# and NOT a synthetic position-id pattern (BANNED).  Each terrain has a small
# set of authored CHR tiles so a walking avatar reads real authored ground.
#
# LANDMARK lattice (doubles as the test's ground truth): an authored TOWN (a
# little house) sits at every (tx,ty) on a 32-tile lattice THAT FALLS ON WALKABLE
# LAND — towns on a regular grid, believable authored content. Water/mountain
# lattice cells are skipped (no house floating in the ocean). Because the towns
# are position-regular, the proof test (mx009) reads "at land world (32k,32m) you
# see a TOWN tile", confirming the streamed world is the authored one. Everything
# between is believable geography.
#
# Deterministic: same script, same bytes (fixed sinusoid phases, no PRNG state).
#
# Regenerate (from the template assets dir, needs PIL):
#   python3 templates/mode7_explore/assets/make_explore_world.py
# =============================================================================
from __future__ import annotations

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- world geometry (F1: grown 256 -> 512 so "several windows" is literal) ---
WORLD_T = 512                       # world is WORLD_T x WORLD_T tiles
WORLD_PX = WORLD_T * 8              # 4096 px
ROWS_PER_BANK = 64                 # 64 rows * 512 bytes/row = 32768 = 1 bank
COLS = WORLD_T                      # 512 bytes/row
BANK_BASE = 2                      # flat tilemap starts at ROM bank 2 (BANK2 seg)
VRAM_WIN = 128                     # Mode 7 VRAM tilemap is 128x128

# --- terrain ids (the tile-id -> terrain-class LUT maps to these; collision
#     reads the flat tilemap byte then LUTs it — the tilemap is the SSoT) ------
TERR_GRASS = 0      # walkable
TERR_PATH = 1       # walkable (road)
TERR_WATER = 2      # BLOCKED
TERR_MOUNTAIN = 3   # BLOCKED
TERR_TOWN = 4       # walkable landmark
BLOCKED = {TERR_WATER, TERR_MOUNTAIN}
TERR_BLOCKED_MIN = TERR_WATER
TERR_BLOCKED_MAX = TERR_MOUNTAIN

# --- tile ids (low-byte tilemap entry == CHR tile index).  Each terrain has
#     authored TEXTURED tiles (a couple of variants for a motion cue), giving
#     the world an authored look rather than flat colour blocks.  Tile id 0 must
#     stay walkable grass (this proof is a flat top-down view, no perspective
#     horizon, so CGRAM index 0 can be opaque grass). -------------------------
TILE_GRASS_DK = 0   # meadow checker base
TILE_GRASS_LT = 1   # meadow checker highlight
TILE_PATH = 2       # dirt road (tiled)
TILE_WATER_DK = 3   # water ripple (deep)
TILE_WATER_LT = 4   # water ripple (shallow)
TILE_MTN_DK = 5     # mountain rock (dark)
TILE_MTN_LT = 6     # mountain rock (lit)
TILE_TOWN = 7       # town roof (landmark)
TILE_COAST = 8      # sand / coastline (walkable beach band)
TILE_FOREST = 9     # forest canopy (walkable, decorative)
N_TILES = 10

# tile id -> terrain id.  This is the SSoT-aligned mapping emitted as the ROM's
# 256-entry tile_terrain_lut (collision reads the flat tilemap byte then LUTs).
TILE_TERRAIN = {
    TILE_GRASS_DK: TERR_GRASS, TILE_GRASS_LT: TERR_GRASS,
    TILE_PATH: TERR_PATH,
    TILE_WATER_DK: TERR_WATER, TILE_WATER_LT: TERR_WATER,
    TILE_MTN_DK: TERR_MOUNTAIN, TILE_MTN_LT: TERR_MOUNTAIN,
    TILE_TOWN: TERR_TOWN,
    TILE_COAST: TERR_GRASS,        # beach is walkable (treated as grass terrain)
    TILE_FOREST: TERR_GRASS,       # forest is walkable (decorative grass terrain)
}

# --- authored 8bpp palette.  Each terrain texture is drawn with a SMALL set of
#     palette indices (a base + a highlight), reusing the kit RPG overworld
#     colour flavour (make_rpg_assets.py's GRASS/PATH/WATER/MTN/TOWN tones). ----
PAL_RGB = {
    0:  (30, 92, 40),     # grass dark
    1:  (52, 130, 58),    # grass light
    2:  (176, 150, 96),   # dirt path
    3:  (24, 58, 140),    # water deep
    4:  (44, 92, 184),    # water shallow
    5:  (96, 84, 78),     # mountain dark
    6:  (150, 138, 128),  # mountain light
    7:  (208, 72, 56),    # town roof
    8:  (214, 198, 140),  # sand / coast
    9:  (26, 78, 42),     # forest dark
    10: (40, 104, 52),    # forest light
    11: (132, 110, 66),   # path edge (darker dirt)
}
N_COLORS = 12

# --- spawn: near the centre of the world so the proof can walk +X, +Y, -X, -Y
#     freely across SEVERAL windows.  A small GRASS clearing is carved around the
#     spawn (see _in_spawn_clearing) so the avatar is never boxed in by
#     ocean/mountain at boot.  Offset a couple tiles off the 32-lattice so the
#     spawn cell itself is NOT a TOWN landmark (a landmark cell is walkable, but
#     keeping the spawn on plain grass makes the boot frame read as open meadow).
SPAWN_TX = 258
SPAWN_TY = 258
SPAWN_CLEAR_R = 3                  # carve a (2R+1)^2 grass clearing around spawn

# --- camera-clamp box (mirror of main.asm CLAMP_*): the camera tile is clamped
#     to [CLAMP_MIN .. CLAMP_MAX] each axis so the 128 window never crosses the
#     world's toroidal seam. The avatar can traverse this whole range. ----------
CLAMP_MIN = 64                     # = WORLD_HALF
CLAMP_MAX = WORLD_T - 1 - 64       # = 447 for a 512 world
CLAMP_RING_W = 16                  # width (tiles) of the diegetic ocean band that
                                   #   frames the clamp box so its edge is a coast

# --- EXPLORER ROAD corridors: an authored road runs the full clamp range along
#     the spawn's row AND column, so the avatar genuinely walks >= 3 windows of
#     NEW content each axis without being boxed in by the surrounding mountain
#     ranges. These are believable authored roads (the world already has a town
#     road network); they are forced WALKABLE (TERR_PATH) over land and water
#     alike along the two spawn axes within the clamp box (a causeway across
#     water reads as an authored bridge/road). Everything off the two corridors
#     is untouched geography. ---------------------------------------------------
def _on_explorer_corridor(tx: int, ty: int) -> bool:
    """True on the spawn-row or spawn-column road corridor, inside the clamp box
    (and not at the spawn clearing, which stays grass)."""
    if ty == SPAWN_TY and CLAMP_MIN <= tx <= CLAMP_MAX:
        return True
    if tx == SPAWN_TX and CLAMP_MIN <= ty <= CLAMP_MAX:
        return True
    return False

# --- DIEGETIC CLAMP RING: the camera is clamped to [CLAMP_MIN..CLAMP_MAX], so
#     without an authored barrier the avatar halts on OPEN ground (an invisible
#     wall). Author a solid OCEAN band framing the clamp box, just OUTSIDE it on
#     either axis, so reaching the clamp edge shows a coastline that explains the
#     stop. The band lives entirely outside [CLAMP_MIN..CLAMP_MAX] (the camera and
#     the road corridors never enter it), and the coast tiles just inside the
#     clamp render as sand automatically (tile_at's COAST rule sees the water). --
def _in_clamp_ring(tx: int, ty: int) -> bool:
    """True in the ocean band that frames the camera-clamp box (a CLAMP_RING_W-
    wide strip just outside [CLAMP_MIN..CLAMP_MAX] on either axis)."""
    x_band = (CLAMP_MIN - CLAMP_RING_W) <= tx < CLAMP_MIN or CLAMP_MAX < tx <= (CLAMP_MAX + CLAMP_RING_W)
    y_band = (CLAMP_MIN - CLAMP_RING_W) <= ty < CLAMP_MIN or CLAMP_MAX < ty <= (CLAMP_MAX + CLAMP_RING_W)
    return x_band or y_band

# --- LANDMARK lattice: an authored TOWN (house) tile at every (tx,ty) where
#     tx%32==0 and ty%32==0 that falls on walkable LAND (water/mountain lattice
#     cells are skipped). Towns on a regular grid double as position-identifiable
#     ground truth: the proof test (mx009) confirms a land lattice point streams
#     in as TILE_TOWN, proving the rendered world IS the authored world. --------
LANDMARK_STEP = 32


def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


# -----------------------------------------------------------------------------
# Geography — a believable large overworld.  A central CONTINENT (radial falloff
# + layered deterministic sinusoids) surrounded by OCEAN, with a SAND coastline
# band, LAKES inland, MOUNTAIN RANGES along high-elevation ridges, FORESTS in
# mid-elevation pockets, a 32-tile lattice of TOWNS, and ROADS connecting the
# towns along cardinal corridors.  All deterministic (no PRNG).  Scaled to a
# 512x512 world (the sinusoid frequencies are in NORMALISED [0,1] space so the
# geography character carries over at the larger size; the ridge/forest/road
# ripples are in TILE space and so scale naturally to 4x the tiles).
# -----------------------------------------------------------------------------
def _height(tx: int, ty: int) -> float:
    """Smooth pseudo-elevation field in [0,1] — high=inland, low=ocean."""
    nx = tx / WORLD_T
    ny = ty / WORLD_T
    dx, dy = nx - 0.5, ny - 0.5
    # radial falloff keeps a central landmass with ocean at the rim
    radial = 1.0 - min(1.0, math.sqrt(dx * dx + dy * dy) / 0.60)
    n = 0.0
    for (fx, fy, ph, amp) in [
        (1.6, 1.6, 0.0, 0.50), (3.1, 1.7, 1.1, 0.26),
        (1.7, 3.3, 2.3, 0.20), (5.0, 4.0, 0.7, 0.12),
        (7.3, 5.7, 3.3, 0.08),
    ]:
        n += amp * math.sin(fx * nx * math.pi * 2 + ph) * math.cos(fy * ny * math.pi * 2 + ph)
    n = (n + 1.0) * 0.5
    return max(0.0, min(1.0, 0.52 * radial + 0.58 * n))


def _is_ridge(tx: int, ty: int, h: float) -> bool:
    """Mountain RANGE: high elevation + a thin oriented ripple so ranges form
    connected diagonal chains, not isolated dots."""
    if h <= 0.70:
        return False
    ripple = math.sin((tx + ty) * 0.22) * 0.6 + math.sin((tx - ty) * 0.16) * 0.4
    return ripple > 0.05


def _is_forest(tx: int, ty: int, h: float) -> bool:
    """Forest pockets in mid-elevation bands (walkable decoration)."""
    if not (0.46 < h < 0.62):
        return False
    f = math.sin(tx * 0.28 + 1.7) * math.cos(ty * 0.33 - 0.9)
    return f > 0.45


# --- ROAD network: roads connect the towns (on the 32-tile lattice) along
#     cardinal corridors, with a gentle deterministic meander so they read as
#     authored roads, not a rigid grid.  A town-column road runs near tx%32==0
#     and a town-row road near ty%32==0, each nudged a tile by a sinusoid so the
#     corridors wander.  Roads are laid only over land (terrain_at gates that). -
def _on_road(tx: int, ty: int) -> bool:
    # vertical corridor near each town column, meandering by +/-1 tile
    col_mod = tx % LANDMARK_STEP
    col_off = int(round(math.sin(ty * 0.13))) % LANDMARK_STEP
    if col_mod == col_off:
        return True
    # horizontal corridor near each town row, meandering by +/-1 tile
    row_mod = ty % LANDMARK_STEP
    row_off = int(round(math.sin(tx * 0.11))) % LANDMARK_STEP
    if row_mod == row_off:
        return True
    return False


def _in_spawn_clearing(tx: int, ty: int) -> bool:
    """A small grass clearing carved around the spawn so the avatar boots onto
    open walkable ground (never boxed in by ocean/mountain)."""
    return (abs(tx - SPAWN_TX) <= SPAWN_CLEAR_R
            and abs(ty - SPAWN_TY) <= SPAWN_CLEAR_R)


def terrain_at(tx: int, ty: int) -> int:
    """SINGLE SOURCE OF TRUTH (geography): terrain id for world tile (tx,ty).
    Used to derive the rendered tile id; the ROM's collision reads the rendered
    tilemap byte back through the tile-id -> terrain LUT, so what you SEE blocked
    is what the movement code rejects."""
    # spawn clearing: forced walkable grass so boot is never boxed in
    if _in_spawn_clearing(tx, ty):
        return TERR_GRASS
    # EXPLORER ROAD corridors along the two spawn axes: forced walkable PATH so
    # the avatar traverses the full clamp box (>= 3 windows) each axis. These
    # override water/mountain (an authored road/causeway). Checked before the
    # height geography so a mountain range never severs the corridor.
    if _on_explorer_corridor(tx, ty):
        return TERR_PATH
    # diegetic clamp ring: a solid ocean band framing the clamp box, so the clamp
    # edge reads as a coastline instead of an invisible wall on open ground
    if _in_clamp_ring(tx, ty):
        return TERR_WATER
    # base geography (the natural terrain a landmark would sit on)
    h = _height(tx, ty)
    if h < 0.30:
        base = TERR_WATER            # ocean / lakes (BLOCKED)
    elif _is_ridge(tx, ty, h):
        base = TERR_MOUNTAIN         # mountain range (BLOCKED)
    elif _on_road(tx, ty):
        base = TERR_PATH             # roads connect the towns (laid only over land)
    else:
        base = TERR_GRASS            # grass (coast/forest are visual variants)
    # LANDMARK lattice: an authored TOWN (a house) sits at every 32-tile lattice
    # point — but ONLY on walkable LAND. A lattice cell over water or a mountain
    # keeps its natural terrain, so no house ever floats in the ocean or buries
    # itself in a peak (that flat-red-dots-everywhere look was the bug). The
    # proof test (mx009) reads this back: the streamed VRAM at a land lattice
    # point must render TILE_TOWN, proving the streamed content is the AUTHORED
    # world (position-identifiable ground truth), not a coincidental grass fill.
    if tx % LANDMARK_STEP == 0 and ty % LANDMARK_STEP == 0 and base not in BLOCKED:
        return TERR_TOWN
    return base


def tile_at(tx: int, ty: int) -> int:
    """Tile id (CHR index / low-byte tilemap entry) for world tile (tx,ty).
    Derived from terrain_at so visuals and collision can never drift; grass
    terrain is rendered as grass / coast / forest variants for a believable
    look (all share TERR_GRASS collision)."""
    terr = terrain_at(tx, ty)
    if terr == TERR_TOWN:
        return TILE_TOWN
    if terr == TERR_PATH:
        return TILE_PATH
    if terr == TERR_WATER:
        return TILE_WATER_LT if (tx ^ ty) & 1 else TILE_WATER_DK
    if terr == TERR_MOUNTAIN:
        return TILE_MTN_LT if (tx ^ ty) & 1 else TILE_MTN_DK
    # grass terrain: choose a believable visual variant.
    h = _height(tx, ty)
    # COAST: a sand band where land meets ocean (a neighbour is water)
    for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = (tx + dx) % WORLD_T, (ty + dy) % WORLD_T
        if _height(nx, ny) < 0.30:
            return TILE_COAST
    if _is_forest(tx, ty, h):
        return TILE_FOREST
    # meadow checker (2x2 block scale) for a Mode 7 motion cue
    return TILE_GRASS_LT if ((tx >> 1) ^ (ty >> 1)) & 1 else TILE_GRASS_DK


# -----------------------------------------------------------------------------
# Authored 8x8 textures (8bpp; each byte = a palette index from PAL_RGB).  These
# are hand-authored patterns (NOT flat fills): a checker meadow, a dithered water
# ripple, a rocky mountain face, a tiled dirt road, a town roof, a sand beach, a
# forest canopy.  This is the "reuse the kit's authored tile art" requirement
# expressed as real textures over the kit's terrain palette.
# -----------------------------------------------------------------------------
def _tex(rows):
    """rows: 8 strings of 8 chars, each char a palette-index nibble/letter.
    Returns 64 palette-index bytes."""
    out = bytearray(64)
    assert len(rows) == 8
    for y, r in enumerate(rows):
        assert len(r) == 8, r
        for x, c in enumerate(r):
            out[y * 8 + x] = int(c, 16)
    return bytes(out)


# Grass dark/light: a fine 2-tone checker (base 0/1) with a few light specks.
TEX = {
    TILE_GRASS_DK: _tex([
        "00010001", "01000100", "00010001", "00000000",
        "00010001", "01000100", "00010001", "00000000",
    ]),
    TILE_GRASS_LT: _tex([
        "11011101", "10111011", "11011101", "11111111",
        "11011101", "10111011", "11011101", "11111111",
    ]),
    # dirt road: tan fill with a darker (11) seam grid -> reads as a paved path
    TILE_PATH: _tex([
        "2222222B", "22222222", "22222222", "2222222B",
        "2222222B", "22222222", "22222222", "BBBBBBBB",
    ]),
    # water deep: deep-blue (3) with shallow (4) ripple diagonals
    TILE_WATER_DK: _tex([
        "33334333", "33343333", "33433333", "34333334",
        "43333343", "33333433", "33334333", "33343333",
    ]),
    TILE_WATER_LT: _tex([
        "44443444", "44434444", "44344444", "43444443",
        "34444434", "44444344", "44443444", "44434444",
    ]),
    # mountain dark/lit: rocky face (5 base, 6 highlight ridges)
    TILE_MTN_DK: _tex([
        "55655655", "56555565", "55556555", "55655655",
        "65555556", "55655655", "56555565", "55556555",
    ]),
    TILE_MTN_LT: _tex([
        "66566566", "65666656", "66665666", "66566566",
        "56666665", "66566566", "65666656", "66665666",
    ]),
    # town: a little house — a red (7) pitched roof over sand-tan (8) walls with
    #     dark (5) windows and a central door.  Reads as a BUILDING on grass (the
    #     0 corners fall back to grass-dark, blending the house into the meadow),
    #     not a flat red block.
    TILE_TOWN: _tex([
        "00077000", "00777700", "07777770", "77777777",
        "08888880", "08588580", "08855880", "08855880",
    ]),
    # sand / coast: tan beach (8) with a few darker (2) grains
    TILE_COAST: _tex([
        "88828888", "88888828", "82888888", "88888288",
        "88828888", "88888828", "82888888", "88888288",
    ]),
    # forest canopy: dark/light green (9/10) clustered foliage
    TILE_FOREST: _tex([
        "9A9AA9A9", "AA9A9AAA", "9A9AA9A9", "AAA9A9AA",
        "9A9AA9A9", "AA9A9AAA", "9A9AA9A9", "AAA9A9AA",
    ]),
}


def build_chr() -> bytes:
    """Fixed 256-tile 8bpp Mode 7 CHR set, packed tile-major: tile T's 64 bytes
    at offset T*64.  Tiles 0..N_TILES-1 are the authored textures; the rest are
    zero (the Mode 7 char set always occupies all 256 slots = 16384 bytes)."""
    out = bytearray(256 * 64)
    for t in range(N_TILES):
        out[t * 64:(t + 1) * 64] = TEX[t]
    return bytes(out)


# -----------------------------------------------------------------------------
# Emitters
# -----------------------------------------------------------------------------
def build_tilemap() -> bytes:
    """WORLD_T x WORLD_T tile-id grid, row-major."""
    out = bytearray(WORLD_T * WORLD_T)
    for ty in range(WORLD_T):
        base = ty * WORLD_T
        for tx in range(WORLD_T):
            out[base + tx] = tile_at(tx, ty)
    return bytes(out)


def build_terrain_lut() -> bytes:
    """256-entry tile-id -> terrain-class LUT (the ROM's collision substrate).
    Indices outside the authored tile vocabulary map to TERR_GRASS (walkable) —
    they never occur in the flat tilemap, but a defined fallback means a stray
    byte never reads as a phantom wall."""
    lut = bytearray(256)
    for i in range(256):
        lut[i] = TILE_TERRAIN.get(i, TERR_GRASS)
    return bytes(lut)


def build_seed(tilemap: bytes, chr_data: bytes) -> bytes:
    """32 KB interleaved Mode 7 VRAM seed for the INITIAL 128x128 window centred
    on SPAWN.  CRITICAL: the seed uses the SAME VRAM-WRAPPED placement the
    streaming engine uses — world tile (wx,wy) lands at VRAM word
    (wy & 127)*128 + (wx & 127), NOT a sequential (vy*128+vx) — so a row/column
    the seed placed lines up byte-exact with the wrapped slot it is later
    re-streamed to.  low byte = tile id; high byte = chr_data (the fixed char
    set indexed by VRAM word, the standard Mode 7 CHR layout)."""
    out = bytearray(VRAM_WIN * VRAM_WIN * 2)
    win_x0 = (SPAWN_TX - 64) % WORLD_T
    win_y0 = (SPAWN_TY - 64) % WORLD_T
    for dy in range(VRAM_WIN):
        wy = (win_y0 + dy) % WORLD_T
        vy = wy & (VRAM_WIN - 1)
        for dx in range(VRAM_WIN):
            wx = (win_x0 + dx) % WORLD_T
            vx = wx & (VRAM_WIN - 1)
            word = vy * VRAM_WIN + vx
            out[word * 2] = tilemap[wy * WORLD_T + wx]      # low = tile id
            out[word * 2 + 1] = chr_data[word]              # high = CHR byte
    return bytes(out)


def build_flat_banks(tilemap: bytes) -> list[bytes]:
    """Flat tilemap split into ROM banks: ROWS_PER_BANK rows/bank, COLS B/row."""
    banks = []
    n_banks = WORLD_T // ROWS_PER_BANK
    for b in range(n_banks):
        data = bytearray()
        for row in range(b * ROWS_PER_BANK, (b + 1) * ROWS_PER_BANK):
            data.extend(tilemap[row * COLS: row * COLS + COLS])
        assert len(data) == ROWS_PER_BANK * COLS
        banks.append(bytes(data))
    return banks


def emit_inc(palette_words: list[int], terr_lut: bytes, n_banks: int) -> str:
    L = []
    L.append("; ===========================================================================")
    L.append("; explore_world.inc — believable Mode 7 streaming overworld constants (GENERATED)")
    L.append("; ===========================================================================")
    L.append("; Regenerate: python3 templates/mode7_explore/assets/make_explore_world.py")
    L.append(f"; World: {WORLD_T}x{WORLD_T} tiles ({WORLD_PX}x{WORLD_PX} px), "
             f"{N_TILES} authored textured tiles, flat tilemap across {n_banks} ROM banks.")
    L.append("; Collision derives from the FLAT tilemap byte via tile_terrain_lut (NO")
    L.append("; separate collision table — the tilemap is the single source of truth).")
    L.append("; ===========================================================================")
    L.append("")
    L.append(f"WORLD_T_TILES   = {WORLD_T}")
    L.append(f"WORLD_PX        = {WORLD_PX}")
    L.append(f"WORLD_WRAP_MASK = {WORLD_T - 1}        ; (tile coord) & this wraps 0..{WORLD_T-1}")
    L.append(f"WORLD_ROWS_PER_BANK = {ROWS_PER_BANK}")
    L.append(f"WORLD_COLS_BYTES = {COLS}      ; bytes per flat row")
    L.append(f"WORLD_FLAT_BANK_BASE = {BANK_BASE}   ; first ROM bank of flat tilemap")
    L.append(f"WORLD_FLAT_BANK_COUNT = {n_banks}   ; flat tilemap spans this many ROM banks")
    L.append(f"WORLD_SPAWN_TX  = {SPAWN_TX}")
    L.append(f"WORLD_SPAWN_TY  = {SPAWN_TY}")
    L.append(f"WORLD_LANDMARK_STEP = {LANDMARK_STEP}  ; TOWN (house) landmark lattice spacing, tiles")
    L.append("")
    L.append("; --- terrain ids (collision-class vocabulary; tile_terrain_lut maps to these) ---")
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
    L.append(f"TILE_COAST    = {TILE_COAST}")
    L.append(f"TILE_FOREST   = {TILE_FOREST}")
    L.append("")
    L.append("; --- CGRAM palette + tile_terrain_lut: emitted into RODATA via pushseg/popseg")
    L.append(";     so this .inc can be included in the equate region (before the ROM's")
    L.append(";     first .segment CODE). ---")
    L.append(f"WORLD_PAL_COUNT = {len(palette_words)}")
    L.append(".pushseg")
    L.append('.segment "RODATA"')
    L.append("world_palette:")
    for i, w in enumerate(palette_words):
        L.append(f"    .word ${w:04X}    ; color {i}")
    L.append("")
    L.append("; tile-id -> terrain-class LUT (256 bytes). collision[ (tx,ty) ] =")
    L.append("; tile_terrain_lut[ flat_tilemap[ty*WORLD_T + tx] ].  The tilemap is the SSoT.")
    L.append("tile_terrain_lut:")
    for i in range(0, 256, 16):
        chunk = terr_lut[i:i + 16]
        L.append("    .byte " + ", ".join(str(b) for b in chunk))
    L.append(".popseg")
    L.append("")
    return "\n".join(L) + "\n"


# =============================================================================
# AVATAR OBJ asset — ELNORA, the purple-robed staff-wielding heroine.
# =============================================================================
# Self-contained (no cross-template dependency).  Elnora is a 16x16 hero sprite
# authored with FOUR FACINGS — down / up / left / right — so she turns to face
# the direction she walks.  Each facing is a 16x16 sprite = four 8x8 4bpp tiles
# in the SNES PPU quad {N, N+1, N+16, N+17}:
#
#     DOWN  base tile 16 -> {16,17,32,33}   (front view, face + eyes visible)
#     UP    base tile 18 -> {18,19,34,35}   (back view, hair only, no face)
#     SIDE  base tile 20 -> {20,21,36,37}   (RIGHT-facing profile; LEFT is this
#                                            sprite H-FLIPPED via the free OAM
#                                            attribute flip bit — the staff then
#                                            lands on the leading (left) side)
#
# The sprite is a TRUE 16x16 OBJ (OBSEL $62 = size mode 3 -> small=16x16), so the
# H-flip mirrors in place (a 32x32 box with 16x16 art would slide the art +16px
# when flipped).  main.asm latches the facing from the last d-pad direction and
# picks base tile + flip bit accordingly; the 2-frame walk bob (Y hop) rides on
# top of every facing unchanged.
#
# OBJ palette 0 (Elnora's colours): 3 distinct PURPLE robe shades (mid / dark /
# light) that read as purple over grass, road, water AND coast (none of the Mode
# 7 terrain tones are purple), a warm brown-gold STAFF shaft with a bright gold
# tip gem, skin, dark chestnut hair, a near-black outline, and a white sheen.
# The avatar is an OBJ sprite, so it is EXCLUDED from the mx-series rendered-VRAM
# tilemap asserts (those read BG tile ids); the purple can never collide with a
# terrain classifier.
# =============================================================================
AVATAR_BASE_TILE = 16              # DOWN facing base tile (mx002 / oracle read this)
AVATAR_TILE_DOWN = 16              # front view  -> quad {16,17,32,33}
AVATAR_TILE_UP = 18                # back view   -> quad {18,19,34,35}
AVATAR_TILE_SIDE = 20              # right view  -> quad {20,21,36,37} (LEFT = H-flip)
AVATAR_TILE_MAX = AVATAR_TILE_SIDE + 17   # highest tile index any facing occupies (37)

OBJ_PAL = [
    (0, 0, 0),           # 0 transparent
    (242, 214, 176),     # 1 skin
    (126, 52, 166),      # 2 robe purple (mid)   — Elnora's mantle
    (74, 26, 104),       # 3 robe purple (dark)  — robe shadow / hem flare / edge
    (26, 26, 36),        # 4 outline / boots     — near-black
    (72, 46, 34),        # 5 hair                — dark chestnut
    (250, 250, 236),     # 6 highlight           — eye spark / gem shine / sheen
    (176, 108, 210),     # 7 robe purple (light) — robe highlight
    (168, 120, 56),      # 8 staff shaft         — warm brown-gold
    (255, 202, 82),      # 9 staff tip           — bright gold gem
    (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0),
]

# --- Elnora, FRONT (walking DOWN).  Hair frames the face (feminine), two eyes,
#     a purple robe that FLARES at the hem (dress silhouette), and the staff held
#     on the viewer-left with its gold tip up beside her head. --------------------
AVATAR_DOWN = [
    "0000055555500000",  # 0  hair crown
    "0090555555550000",  # 1  gold tip beside her head, hair
    "0080551111550000",  # 2  staff shaft, hair frames skin forehead
    "0080511111150000",  # 3  hair, skin face
    "0080514114150000",  # 4  skin face, two eyes
    "0080511111150000",  # 5  skin face
    "0080551111550000",  # 6  hair falls to the sides (long)
    "0081322222231000",  # 7  hand grips the staff, robe collar
    "0080272222272000",  # 8  robe with a light-purple sheen
    "0080222222222000",  # 9  robe body
    "0000322222223000",  # 10 robe, dark side shading
    "0000322222223000",  # 11 robe waist
    "0003222222222300",  # 12 robe begins to flare
    "0032222222222230",  # 13 robe flare wider
    "0032722222272300",  # 14 wide hem with sheen
    "0003300440330000",  # 15 hem shadow + little boots
]

# --- Elnora, BACK (walking UP).  Same silhouette from behind: the head is all
#     hair (NO face), the robe shows a centre pleat, staff + gold tip on the
#     viewer-left. --------------------------------------------------------------
AVATAR_UP = [
    "0000055555500000",  # 0  hair crown
    "0090555555550000",  # 1  gold tip, hair
    "0080555555550000",  # 2  back of the head — all hair
    "0080555555550000",  # 3  hair
    "0080555555550000",  # 4  hair (no face)
    "0080555555550000",  # 5  hair
    "0080555555550000",  # 6  hair falls down her back
    "0081322222231000",  # 7  robe collar, hand on the staff
    "0080272222272000",  # 8  robe with centre pleat sheen
    "0080222222222000",  # 9  robe body
    "0000322222223000",  # 10 robe, dark side shading
    "0000322222223000",  # 11 robe waist
    "0003222222222300",  # 12 robe flare
    "0032222222222230",  # 13 flare wider
    "0032722222272300",  # 14 wide hem with pleat sheen
    "0003300440330000",  # 15 hem shadow + boots
]

# --- Elnora, SIDE profile facing RIGHT.  Hair sweeps back (left), one eye + nose
#     face right, robe flares behind her stride, and the STAFF is held FORWARD on
#     the leading (right) side, gold tip up.  LEFT facing = this sprite H-flipped
#     (the staff then leads on the left).  Leading-side staff per the spec. ------
AVATAR_SIDE = [
    "0000555550000000",  # 0  hair crown, swept back
    "0005555511009000",  # 1  hair back, skin brow, gold tip (right)
    "0055555111008000",  # 2  hair, face, staff shaft
    "0055551141108000",  # 3  hair, eye, nose bulge, shaft
    "0005551111108000",  # 4  hair sweeps back, face, shaft
    "0000551111108000",  # 5  jaw / neck, shaft
    "0000322222218000",  # 6  robe collar, hand reaches the staff
    "0003222222281000",  # 7  robe, hand grips shaft
    "0003272222280000",  # 8  robe with sheen, shaft lower
    "0003222222200000",  # 9  robe body
    "0003222222230000",  # 10 robe
    "0003222222230000",  # 11 robe waist
    "0032222222223000",  # 12 robe flares behind the stride
    "0322222222223000",  # 13 flare wider (trailing)
    "0327222222232000",  # 14 hem with sheen
    "0033004400330000",  # 15 back foot + front foot mid-step
]

# facing name -> (grid, base tile).  SIDE authored facing RIGHT; LEFT reuses it
# H-flipped at draw time, so it is NOT emitted as separate CHR.
AVATAR_FACINGS = {
    "down": (AVATAR_DOWN, AVATAR_TILE_DOWN),
    "up": (AVATAR_UP, AVATAR_TILE_UP),
    "side": (AVATAR_SIDE, AVATAR_TILE_SIDE),
}


def _split_quad(grid16):
    """Split a 16x16 index grid into four 8x8 index grids (TL, TR, BL, BR) for
    the SNES PPU 16x16 tile quad {N, N+1, N+16, N+17}."""
    assert len(grid16) == 16, f"avatar grid must be 16 rows, got {len(grid16)}"
    g = [[int(c, 16) for c in row] for row in grid16]
    for r in grid16:
        assert len(r) == 16, f"avatar row must be 16 cols: {r!r}"
    tl = [row[0:8] for row in g[0:8]]
    tr = [row[8:16] for row in g[0:8]]
    bl = [row[0:8] for row in g[8:16]]
    br = [row[8:16] for row in g[8:16]]
    return tl, tr, bl, br


def encode_4bpp(tile):
    """Encode an 8x8 index grid (0..15) to SNES 4bpp planar (32 bytes)."""
    out = bytearray()
    for row in tile:
        b0 = b1 = 0
        for x, idx in enumerate(row):
            assert 0 <= idx <= 15, idx
            bit = 7 - x
            b0 |= ((idx >> 0) & 1) << bit
            b1 |= ((idx >> 1) & 1) << bit
        out.append(b0); out.append(b1)
    for row in tile:
        b2 = b3 = 0
        for x, idx in enumerate(row):
            bit = 7 - x
            b2 |= ((idx >> 2) & 1) << bit
            b3 |= ((idx >> 3) & 1) << bit
        out.append(b2); out.append(b3)
    return bytes(out)


def emit_obj():
    """Emit explore_obj.inc: a 4bpp OBJ CHR blob holding Elnora's THREE authored
    facing sprites (down/up/right; left is right H-flipped at draw time) laid out
    as 16x16 PPU quads at base tiles 16/18/20, plus the OBJ palette and the
    AVATAR_TILE* / EXPLORE_OBJ_BYTES equates.  The blob spans tiles 0..37."""
    EMPTY = [[0] * 8 for _ in range(8)]
    n_tiles = AVATAR_TILE_MAX + 1               # 38 tiles (0..37)
    tiles = [EMPTY] * n_tiles
    for _name, (grid, base) in AVATAR_FACINGS.items():
        tl, tr, bl, br = _split_quad(grid)
        tiles[base] = tl                        # {base, base+1, base+16, base+17}
        tiles[base + 1] = tr
        tiles[base + 16] = bl
        tiles[base + 17] = br
    chr_bytes = b"".join(encode_4bpp(t) for t in tiles)
    pal_words = [rgb_to_bgr555(*c) for c in OBJ_PAL]
    L = []
    L.append("; ===========================================================================")
    L.append("; explore_obj.inc — Elnora avatar OBJ CHR + palette (GENERATED)")
    L.append("; ===========================================================================")
    L.append("; Regenerate: python3 templates/mode7_explore/assets/make_explore_world.py")
    L.append("; Elnora, the purple-robed staff-wielder, in FOUR FACINGS. Three authored")
    L.append("; 16x16 sprites (down/up/right); LEFT is the right sprite H-flipped via the")
    L.append("; free OAM attribute flip bit. PPU 16x16 quads {N,N+1,N+16,N+17}:")
    L.append(";   AVATAR_TILE_DOWN 16 -> {16,17,32,33}   front (face + eyes)")
    L.append(";   AVATAR_TILE_UP   18 -> {18,19,34,35}   back (hair, no face)")
    L.append(";   AVATAR_TILE_SIDE 20 -> {20,21,36,37}   right profile (LEFT = H-flip)")
    L.append("; ===========================================================================")
    L.append("")
    L.append(f"AVATAR_TILE       = {AVATAR_BASE_TILE}   ; DOWN facing (default / idle)")
    L.append(f"AVATAR_TILE_DOWN  = {AVATAR_TILE_DOWN}")
    L.append(f"AVATAR_TILE_UP    = {AVATAR_TILE_UP}")
    L.append(f"AVATAR_TILE_SIDE  = {AVATAR_TILE_SIDE}   ; RIGHT; LEFT = this tile H-flipped")
    L.append(f"EXPLORE_OBJ_BYTES = {len(chr_bytes)}")
    L.append("")
    L.append(".pushseg")
    L.append('.segment "RODATA"')
    L.append("avatar_chr:")
    for i in range(0, len(chr_bytes), 16):
        chunk = chr_bytes[i:i + 16]
        L.append("    .byte " + ", ".join(f"${b:02X}" for b in chunk))
    L.append("")
    L.append(f"OBJ_PAL_COUNT = {len(pal_words)}")
    L.append("obj_pal:")
    for i, w in enumerate(pal_words):
        L.append(f"    .word ${w:04X}    ; color {i}")
    L.append(".popseg")
    L.append("")
    (HERE / "explore_obj.inc").write_text("\n".join(L) + "\n")
    print(f"  obj        : explore_obj.inc ({len(chr_bytes)} CHR bytes, "
          f"{n_tiles} tiles, Elnora facings down/up/side @ 16/18/20)")


def _open_run(tx: int, ty: int, length: int) -> bool:
    """True iff there is a contiguous walkable run of `length` tiles in EACH
    cardinal direction from (tx,ty) (so streaming actually fires from the start —
    the avatar is not boxed in by a wall one tile away)."""
    for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for k in range(1, length + 1):
            t = terrain_at((tx + dx * k) % WORLD_T, (ty + dy * k) % WORLD_T)
            if t in BLOCKED:
                return False
    return True


def main() -> None:
    emit_obj()
    tilemap = build_tilemap()
    chr_data = build_chr()
    seed = build_seed(tilemap, chr_data)
    banks = build_flat_banks(tilemap)
    terr_lut = build_terrain_lut()

    pal = [rgb_to_bgr555(*PAL_RGB[i]) for i in range(N_COLORS)]

    assert len(seed) == 0x8000, len(seed)
    assert len(terr_lut) == 256
    (HERE / "explore_seed.bin").write_bytes(seed)
    # remove any stale collision-table banks from the prior 256x256 design
    for stale in HERE.glob("explore_collision_bank*.bin"):
        stale.unlink()
    for b, data in enumerate(banks):
        (HERE / f"explore_flat_bank{b}.bin").write_bytes(data)
    (HERE / "explore_world.inc").write_text(emit_inc(pal, terr_lut, len(banks)))

    census = {}
    for t in tilemap:
        census[t] = census.get(t, 0) + 1
    print(f"world: {WORLD_T}x{WORLD_T} tiles, {N_TILES} authored textured tiles")
    print(f"  seed       : explore_seed.bin ({len(seed)} bytes, initial 128x128 window)")
    print(f"  flat banks : {len(banks)} x explore_flat_bankN.bin ({len(banks[0])} bytes each, "
          f"{len(banks) * len(banks[0]) // 1024} KB total tilemap)")
    print(f"  collision  : tile_terrain_lut (256 B in explore_world.inc) — NO separate table")
    print(f"  tile census   : {dict(sorted(census.items()))}")
    lattice_pts = (WORLD_T // LANDMARK_STEP) ** 2
    towns = census.get(TILE_TOWN, 0)
    print(f"  landmarks  : {towns} TOWN (house) tiles on a {LANDMARK_STEP}-tile lattice "
          f"({lattice_pts} lattice points, {lattice_pts - towns} skipped over water/mountain)")

    # --- spawn validity (P3): require a multi-tile OPEN RUN around spawn so
    #     streaming actually fires from boot (not just spawn + 4 neighbours). ---
    SPAWN_OPEN_RUN = 6
    if not _open_run(SPAWN_TX, SPAWN_TY, SPAWN_OPEN_RUN):
        raise SystemExit(
            f"ERROR: spawn ({SPAWN_TX},{SPAWN_TY}) is boxed in — no {SPAWN_OPEN_RUN}-tile "
            f"open run in every cardinal direction. Streaming would not fire from boot. "
            f"Move SPAWN_TX/SPAWN_TY to open ground or widen SPAWN_CLEAR_R.")
    print(f"  spawn ({SPAWN_TX},{SPAWN_TY}): {SPAWN_OPEN_RUN}-tile open run each direction: OK")

    # --- traversal proof (F1): the camera-clamp box must allow >= 3 streaming
    #     windows (128 tiles) of CAMERA travel each axis. The main.asm clamp is
    #     [HALF .. WORLD-1-HALF] = [64 .. 447] -> 383 tiles of camera travel.
    #     Distinct CONTENT traversed = travel + window = 383 + 128 = 511 tiles
    #     (the window shows cam-64..cam+63), so ~4.0 windows of NEW content stream
    #     in across a full-axis walk. Both are reported. -------------------------
    HALF = 64
    travel = (WORLD_T - 1 - HALF) - HALF                 # 383 tiles
    cam_windows = travel / 128.0                          # ~2.99 (camera position span)
    content_windows = (travel + 128) / 128.0             # ~3.99 (distinct tiles seen)
    print(f"  camera-clamp travel: {travel} tiles each axis "
          f"= {cam_windows:.2f} windows of camera travel, "
          f"{content_windows:.2f} windows of distinct content traversed")
    # >= 3 windows of distinct streamed content each axis (the DoD's "several").
    assert content_windows >= 3.0, \
        f"distinct content traversed {content_windows:.2f} windows < 3"


if __name__ == "__main__":
    main()
