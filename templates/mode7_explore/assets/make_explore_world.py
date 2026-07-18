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
# Position-identifiability for tests is a HIDDEN/debug surface only: a TOWN tile
# sits at every (tx,ty) on a 32-tile lattice (legitimate authored content —
# towns — placed on a regular grid) so the proof test has ground-truth "at world
# (32k,32m) you see a TOWN tile".  Everything between is believable geography.
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

# --- HIDDEN debug landmark grid: a TOWN tile at every (tx,ty) where tx%32==0
#     and ty%32==0 (authored towns on a 32-tile lattice) -> position-identifiable
#     ground truth for the proof test without a synthetic visible pattern. ------
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
    # spawn clearing: forced walkable grass so boot is never boxed in (checked
    # before geography, after the landmark lattice below would normally win —
    # but the clearing is offset off the lattice so they don't overlap)
    if _in_spawn_clearing(tx, ty):
        return TERR_GRASS
    # hidden debug landmark lattice (authored town tiles) — so a landmark is
    # never overwritten by surrounding geography
    if tx % LANDMARK_STEP == 0 and ty % LANDMARK_STEP == 0:
        return TERR_TOWN
    # EXPLORER ROAD corridors along the two spawn axes: forced walkable PATH so
    # the avatar traverses the full clamp box (>= 3 windows) each axis. These
    # override water/mountain (an authored road/causeway). Checked before the
    # height geography so a mountain range never severs the corridor.
    if _on_explorer_corridor(tx, ty):
        return TERR_PATH
    h = _height(tx, ty)
    if h < 0.30:
        return TERR_WATER            # ocean / lakes (BLOCKED)
    if _is_ridge(tx, ty, h):
        return TERR_MOUNTAIN         # mountain range (BLOCKED)
    # roads connect the towns (laid only over land)
    if _on_road(tx, ty):
        return TERR_PATH
    return TERR_GRASS                # grass (coast/forest are visual variants)


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
    # town roof: bright red (7) tiled roof with darker (5) ridge lines
    TILE_TOWN: _tex([
        "77777777", "75777757", "77777777", "77577577",
        "77777777", "75777757", "77777777", "77577577",
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
    L.append(f"WORLD_LANDMARK_STEP = {LANDMARK_STEP}  ; TOWN tile lattice spacing (hidden debug)")
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
# AVATAR OBJ asset (self-contained — no cross-template dependency).  A 16x16
# hero sprite (the explorer) as four 8x8 4bpp tiles laid out for the SNES PPU
# 16x16 quad {N, N+1, N+16, N+17}.  Tile base 16 (VRAM-row aligned, a multiple
# of 16) -> quad {16,17,32,33}.  OBJ palette 0: skin / tunic / cape / outline.
# =============================================================================
AVATAR_BASE_TILE = 16              # OBJ tile base (16x16 reads {16,17,32,33})

OBJ_PAL = [
    (0, 0, 0),           # 0 transparent
    (240, 220, 180),     # 1 skin
    (40, 80, 210),       # 2 tunic blue
    (190, 50, 50),       # 3 cape red
    (28, 28, 38),        # 4 outline / boots
    (110, 70, 40),       # 5 hair brown
    (248, 248, 232),     # 6 highlight
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
]

# 16x16 explorer drawn as palette indices.  Rows of 16; split into the PPU quad.
AVATAR16 = [
    "0000044444400000",
    "0000455555540000",
    "0004555555554000",
    "0004511111154000",
    "0004151111514000",
    "0004111111114000",
    "0000041111400000",
    "0003322222233000",
    "0033222222223300",
    "0332222222222330",
    "0042222222222400",
    "0004222222224000",
    "0000411111140000",
    "0000041001400000",
    "0000044004400000",
    "0000440000440000",
]


def _avatar_quad():
    """Split the 16x16 grid into four 8x8 index grids (TL, TR, BL, BR)."""
    g = [[int(c, 16) for c in row] for row in AVATAR16]
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
    """Emit explore_obj.inc: a 34-tile 4bpp OBJ CHR blob whose tiles 16,17,32,33
    form the 16x16 avatar (the PPU quad for OBJ base tile 16), an OBJ palette,
    and the AVATAR_TILE / EXPLORE_OBJ_BYTES equates."""
    EMPTY = [[0] * 8 for _ in range(8)]
    tl, tr, bl, br = _avatar_quad()
    tiles = [EMPTY] * 34
    tiles[16] = tl
    tiles[17] = tr
    tiles[32] = bl
    tiles[33] = br
    chr_bytes = b"".join(encode_4bpp(t) for t in tiles)
    pal_words = [rgb_to_bgr555(*c) for c in OBJ_PAL]
    L = []
    L.append("; ===========================================================================")
    L.append("; explore_obj.inc — avatar OBJ CHR + palette (GENERATED)")
    L.append("; ===========================================================================")
    L.append("; Regenerate: python3 templates/mode7_explore/assets/make_explore_world.py")
    L.append("; 16x16 explorer avatar: OBJ base tile 16 -> PPU quad {16,17,32,33}.")
    L.append("; ===========================================================================")
    L.append("")
    L.append(f"AVATAR_TILE       = {AVATAR_BASE_TILE}")
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
    print(f"  obj        : explore_obj.inc ({len(chr_bytes)} CHR bytes, avatar base tile {AVATAR_BASE_TILE})")


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
    lm = [(tx, ty) for ty in range(0, WORLD_T, LANDMARK_STEP)
          for tx in range(0, WORLD_T, LANDMARK_STEP)]
    print(f"  landmarks  : {len(lm)} TOWN tiles on a {LANDMARK_STEP}-tile lattice")

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
