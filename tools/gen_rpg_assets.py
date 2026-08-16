#!/usr/bin/env python3
"""gen_rpg_assets.py — the `rpg` rail's world, town, actors and palettes.

Emits (byte-identical on re-run, pure integer math, no PIL, no source art):

  rpg_m7.bin      32768 B  the INTERLEAVED Mode 7 region: map byte at every
                           EVEN address, CHR byte at every ODD one — the layout
                           $2118/$2119 want, 128x128 tiles + 256 8bpp tiles
  rpg_col.bin     16384 B  the SAME world as a FLAT one-byte-per-tile map,
                           which is the only shape `col_map` can probe
  rpg_flags.bin     256 B  col_map's CM_FLAGS: tile id -> terrain flag byte
  rpg_m7_pal.bin     64 B  32 BGR555 words, CGRAM 0..31; word 0 IS THE SKY
  rpg_town_chr.bin 2048 B  64 x 4bpp town tiles
  rpg_town_map.bin 2048 B  the town's 32x32 tilemap words
  rpg_town_pal.bin   32 B  16 BGR555 words, CGRAM 0..15
  rpg_obj_chr.bin  2048 B  64 x 4bpp OBJ tiles (the 16-wide grid 16x16 needs)
  rpg_obj_pal.bin    32 B  16 BGR555 words, CGRAM 128..143

TWO REPRESENTATIONS OF ONE WORLD, AND WHY. Mode 7's region interleaves the
tilemap and the CHR at alternate bytes; `col_map`'s addressing is
`(ty & (rpc-1)) * W + tx`, one byte per tile. Neither can be read as the other.
Both are emitted here from the SAME `world_tiles()` grid, in one pass, so they
cannot drift — the drift is what a second generator would buy.

NO ART IMPORT, therefore no ground-truth obligation. CLAUDE.md's asset-import
rule ("ground-truth the converter against a render it did not produce, never a
re-rendering of your own output") binds a CONVERTER. There is no converter
here: the world is authored in this file as integer shapes, the way
`gen_cf_assets.py`, `gen_maze_assets.py` and `gen_room_assets.py` author
theirs. The only inputs are documented CONSTANTS — the world size, the spawn
tile, the panel colours in gen_dialog_assets.py — each stated where it is
declared rather than inferred from an image.

SKY = CGRAM WORD 0. A Mode 7 8bpp pixel value is an ABSOLUTE CGRAM index, and
this rail's sky is the backdrop showing through `split_band`'s top band. So no
floor pixel may be index 0, and `assert_no_index0` enforces it over every one
of the 256 tiles rather than trusting the art.

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): every encoder asserts its
index range and names the offending pixel.
"""
import sys
from pathlib import Path

W = H = 128                        # world, in tiles — a 1024-px torus, which is
                                   # what makes col_map's `and #(CM_W-1)` right
SPAWN_TX, SPAWN_TY = 64, 78        # the player's first tile (on the north road)

# --- terrain tile ids (also the Mode 7 tile ids: one tile per class) --------
T_GRASS, T_PATH, T_WATER, T_MOUNT, T_TOWN, T_TREE, T_SAND, T_NPC = range(8)

# --- col_map flag bits ------------------------------------------------------
F_BLOCK = 1 << 0
F_TOWN = 1 << 1
F_TALK = 1 << 2

FLAGS = {
    T_GRASS: 0,
    T_PATH: 0,
    T_WATER: F_BLOCK,
    T_MOUNT: F_BLOCK,
    T_TOWN: F_BLOCK | F_TOWN,      # blocked so the player STOPS at the gate
    T_TREE: F_BLOCK,
    T_SAND: 0,
    T_NPC: F_BLOCK,                # a wayside statue: a blocked landmark. NOT
                                   # F_TALK — Mode 7 has NO BG3, so the panel
                                   # debuts in the town, where BG3 exists
                                   # (the panel needs a layer to live on).
}

# --- CGRAM 0..31, the Mode 7 palette. Word 0 is the SKY. --------------------
SKY = 0x7E93                       # pale daylight blue (b=31 g=20 r=19)
M7_PAL = [
    SKY,                           #  0 sky / backdrop  (NO floor pixel uses it)
    0x1180, 0x1A61, 0x22C2,        #  1-3  grass dark -> light
    0x1EF7, 0x2B5B,                #  4-5  path, path light
    0x5800, 0x6C21,                #  6-7  water deep, water shallow
    0x14A5, 0x2128, 0x2DAD,        #  8-10 mountain dark/mid/snowline
    0x0C1F, 0x1CBF,                # 11-12 roof red, roof light
    0x35AD, 0x4A52,                # 13-14 wall stone, wall light
    0x0940, 0x1163,                # 15-16 tree dark, tree light
    0x3ADF, 0x2F7B,                # 17-18 sand, sand shade
    0x001F, 0x02BF,                # 19-20 npc cloth, npc trim
    0x2B5F,                        # 21    npc skin
] + [0x0000] * 10                  # 22-31 unused, written explicitly (rule 5)

TOWN_PAL = [
    0x1084,                        #  0 backdrop: the town's night stone
    0x2D6B, 0x39EF,                #  1-2 cobble, cobble light
    0x2114, 0x35AD,                #  3-4 brick, brick mortar
    0x0C1F, 0x1CBF,                #  5-6 roof red, roof light
    0x027F, 0x03FF,                #  7-8 torch flame, torch core
    0x4210,                        #  9  door timber
    0x5AD6,                        # 10  door light
    0x1A61, 0x22C2,                # 11-12 grass dark/light
    0x6C21, 0x5800,                # 13-14 water light/deep
    0x7FFF,                        # 15  highlight
]

OBJ_PAL = [
    0x0000,                        #  0 transparent (OBJ index 0 never drawn)
    0x001F, 0x02BF,                #  1-2 tunic red, tunic light
    0x2B5F, 0x3BFF,                #  3-4 skin, skin light
    0x0000, 0x14A5,                #  5-6 outline black, boot brown
    0x1180, 0x2D6B,                #  7-8 villager green, villager pale
    0x7FFF, 0x4210,                #  9-10 white, grey
] + [0x0000] * 5


# ---------------------------------------------------------------------------
# encoders — every one asserts its range and names the pixel
# ---------------------------------------------------------------------------
def encode_8bpp(rows, label):
    """8x8 indices -> 64 B Mode 7 CHR — LINEAR, one byte per pixel, row-major.

    NOT bitplanar. Mode 7 CHR is the one tile format on the SNES that is direct
    8-bit colour, and the first pass of this generator got it wrong (bitplanar,
    which rendered the floor as coloured stripes). Read off Mesen2
    Core/SNES/SnesPpu.cpp:1218-1223 rather than assumed:

        colorIndex = _vram[(tileIndex << 6) + ((yOffset & 7) << 3)
                           + (xOffset & 7)] >> 8

    i.e. word index = tile*64 + row*8 + col, and the CHR byte is the HIGH byte
    of that word — which is what the odd addresses of the interleaved region
    are. The tilemap is the same word's LOW byte, at index (ty*128 + tx)
    (SnesPpu.cpp:1202, `((yOffset & ~0x07) << 4) | (xOffset >> 3)`).
    """
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    out = bytearray()
    for y in range(8):
        assert len(rows[y]) == 8, f"{label}: row {y} is not 8 px"
        for x in range(8):
            v = rows[y][x]
            assert 0 <= v <= 255, (
                f"{label}: pixel ({x},{y}) index {v} is outside 8bpp 0..255")
            out.append(v)
    assert len(out) == 64, f"{label}: encoded {len(out)} B, expected 64"
    return bytes(out)


def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3)."""
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    out = bytearray()
    for pair in (0, 2):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                assert 0 <= v <= 15, (
                    f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
                lo = (lo << 1) | ((v >> pair) & 1)
                hi = (hi << 1) | ((v >> (pair + 1)) & 1)
            out += bytes((lo, hi))
    assert len(out) == 32, f"{label}: encoded {len(out)} B, expected 32"
    return bytes(out)


def encode_pal(words, label):
    out = bytearray()
    for i, w in enumerate(words):
        assert 0 <= w <= 0x7FFF, (
            f"{label}: entry {i} value {w:#06x} is not a 15-bit BGR555 word")
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def assert_no_index0(rows, label):
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            assert v != 0, (
                f"{label}: pixel ({x},{y}) is CGRAM index 0, which this rail's "
                f"split shows as SKY — a floor tile may not use it")


# ---------------------------------------------------------------------------
# the Mode 7 tileset — one 8x8 tile per terrain class
# ---------------------------------------------------------------------------
def _speckle(base, spot, seed):
    """A deterministic 2-colour dither: no RNG, so re-runs are byte-identical."""
    rows = []
    for y in range(8):
        row = []
        for x in range(8):
            row.append(spot if ((x * 5 + y * 3 + seed) % 7) == 0 else base)
        rows.append(row)
    return rows


def _banded(top, bottom, split):
    return [[top] * 8 if y < split else [bottom] * 8 for y in range(8)]


def m7_tileset():
    """256 tiles of 8x8 indices; ids 0..7 are the terrain, 8..255 are filler."""
    grass = _speckle(1, 3, 0)
    path = _speckle(4, 5, 2)
    water = _speckle(6, 7, 1)
    mount = _banded(10, 8, 3)
    for y in range(8):                    # a ridge line so peaks read as peaks
        mount[y][(y * 3) % 8] = 9
    town = _banded(11, 13, 4)
    town[0] = [12] * 8
    for y in range(4, 8):
        town[y][3] = 14
        town[y][4] = 14
    tree = _speckle(15, 16, 5)
    for y in range(6, 8):
        tree[y] = [1, 1, 1, 15, 15, 1, 1, 1]
    sand = _speckle(17, 18, 3)
    npc = _banded(21, 19, 3)
    npc[0] = [1] * 8                      # grass above the head
    for y in range(4, 8):
        npc[y][0] = 1
        npc[y][7] = 1
    npc[3] = [1, 20, 20, 20, 20, 20, 20, 1]

    tiles = [grass, path, water, mount, town, tree, sand, npc]
    labels = ["grass", "path", "water", "mountain", "town", "tree", "sand",
              "npc"]
    for rows, label in zip(tiles, labels):
        assert_no_index0(rows, f"m7 tile {label}")
    # every remaining tile is written EXPLICITLY (rule 5: never inherit a
    # cleared VRAM), as flat grass so a stray map byte reads as ground.
    tiles += [grass] * (256 - len(tiles))
    return tiles


# ---------------------------------------------------------------------------
# the world grid — authored as integer shapes
# ---------------------------------------------------------------------------
def _disc(grid, cx, cy, r, tid):
    for y in range(max(0, cy - r), min(H, cy + r + 1)):
        for x in range(max(0, cx - r), min(W, cx + r + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                grid[y][x] = tid


def _ring(grid, cx, cy, r, tid):
    for y in range(max(0, cy - r), min(H, cy + r + 1)):
        for x in range(max(0, cx - r), min(W, cx + r + 1)):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if r * r < d2 <= (r + 1) * (r + 1):
                grid[y][x] = tid


def _hline(grid, y, x0, x1, tid):
    for x in range(x0, x1 + 1):
        grid[y][x] = tid


def _vline(grid, x, y0, y1, tid):
    for y in range(y0, y1 + 1):
        grid[y][x] = tid


def world_tiles():
    """The 128x128 designed world. Returns grid[y][x] = terrain/tile id."""
    g = [[T_GRASS] * W for _ in range(H)]

    # a mountain range across the north, and a spur down the west edge
    for y in range(4, 16):
        for x in range(8, 120):
            if (x * 7 + y * 11) % 23 > 6 and y < 16 - abs(x - 64) // 12:
                g[y][x] = T_MOUNT
    for y in range(16, 60):
        for x in range(2, 8 - (y - 16) // 12):
            g[y][x] = T_MOUNT

    # the lake, with a sand shore
    _ring(g, 40, 46, 13, T_SAND)
    _disc(g, 40, 46, 13, T_WATER)

    # scattered woods (deterministic, not random)
    for y in range(20, 118):
        for x in range(20, 118):
            if g[y][x] == T_GRASS and (x * 13 + y * 29) % 97 == 0:
                g[y][x] = T_TREE

    # the roads: a north-south trunk through the spawn and an east-west branch
    _vline(g, 64, 20, 110, T_PATH)
    _hline(g, 88, 30, 100, T_PATH)
    _vline(g, 96, 60, 88, T_PATH)

    # THE TOWN GATE, four tiles north of spawn on the trunk road. Close on
    # purpose: it is the rail's first transition and a test that has to walk
    # sixty tiles to reach it is a test nobody runs. The road continues past it
    # as scenery — the gate BLOCKS, so you stop in front of it, which is also
    # what makes the last frame before the dissolve show you standing there.
    g[SPAWN_TY - 4][SPAWN_TX] = T_TOWN

    # the villager, standing beside the road two tiles south of spawn
    g[SPAWN_TY + 2][SPAWN_TX + 1] = T_NPC
    for x in (SPAWN_TX, SPAWN_TX + 1):
        for y in (SPAWN_TY + 1, SPAWN_TY + 2, SPAWN_TY + 3):
            if g[y][x] not in (T_NPC, T_PATH):
                g[y][x] = T_GRASS

    # The spawn tile and the road north and south of it walk; EAST and WEST of
    # it are a wayside tree and a pond, and they are there on purpose. A
    # collision test needs a blocked neighbour it can reach in one press —
    # without one the nearest wall is tens of tiles away and the test that
    # proves a press is REJECTED becomes a test nobody runs. Both directions,
    # so the rejection is not proven on one axis only.
    for dy in (-1, 0, 1):
        g[SPAWN_TY + dy][SPAWN_TX] = T_PATH
    g[SPAWN_TY][SPAWN_TX + 1] = T_TREE
    g[SPAWN_TY][SPAWN_TX - 1] = T_WATER
    assert FLAGS[g[SPAWN_TY][SPAWN_TX]] & F_BLOCK == 0, "spawn tile blocks"
    assert FLAGS[g[SPAWN_TY][SPAWN_TX + 1]] & F_BLOCK, "east of spawn must block"
    assert FLAGS[g[SPAWN_TY][SPAWN_TX - 1]] & F_BLOCK, "west of spawn must block"
    assert FLAGS[g[SPAWN_TY - 4][SPAWN_TX]] & F_TOWN, "the gate must be F_TOWN"
    return g


# ---------------------------------------------------------------------------
# the town — a 32x32 Mode 1 room
# ---------------------------------------------------------------------------
TT_VOID, TT_COBBLE, TT_COBBLE2, TT_BRICK, TT_ROOF, TT_TORCH, TT_DOOR, \
    TT_GRASS, TT_WATER, TT_BARREL, TT_TORCH_LIT = range(11)

# TT_TORCH_LIT: the SAVE torch's flare tile. Never placed in the map —
# town_flare_commit swaps it into the save-torch cell in VBlank for a few frames
# on save, then restores TT_TORCH, so the panel's "THE TORCH FLARES ONCE" is
# honest. It only needs to EXIST in the CHR at its id.

# TT_BARREL: a blocking plaza prop (owner pilot feedback, 2026-08-08). It
# replaces the two DECORATIVE torches at (8,9)/(24,9) so the SAVE torch (20,16)
# is the only torch a player can walk up to — the save point reads as unique.
# The runtime block set is the WALKABLE whitelist in rpg_town.asm rpgt_blocks
# (cobble/cobble2/grass/door walk; everything else blocks), so a barrel blocks
# by construction; TOWN_BLOCK here is the Python-side sanity twin (the spawn
# assert below reads it).
TOWN_BLOCK = {TT_VOID, TT_BRICK, TT_ROOF, TT_TORCH, TT_WATER, TT_BARREL}
TOWN_W = TOWN_H = 32
TOWN_SPAWN_TX, TOWN_SPAWN_TY = 16, 20      # just inside the south gate
TOWN_NPC_TX, TOWN_NPC_TY = 12, 10          # the villager's cell
TOWN_SAVE_TX, TOWN_SAVE_TY = 20, 16        # the save point's cell
TOWN_EXIT_TX, TOWN_EXIT_TY = 16, 24        # the gate back to the overworld


def town_tileset():
    """64 tiles of 8x8 4bpp indices. Ids 0..8 are the room; the rest are void."""
    void = [[0] * 8 for _ in range(8)]
    cobble = _speckle(1, 2, 0)
    cobble2 = _speckle(1, 2, 4)
    brick = [[3] * 8 for _ in range(8)]
    for y in (0, 4):
        brick[y] = [4] * 8
    for y in range(8):
        brick[y][(0 if y < 4 else 4)] = 4
    roof = _banded(6, 5, 3)
    torch = [[3] * 8 for _ in range(8)]
    torch[2] = [3, 3, 7, 7, 7, 7, 3, 3]
    torch[3] = [3, 7, 8, 8, 8, 8, 7, 3]
    torch[4] = [3, 3, 7, 8, 8, 7, 3, 3]
    door = [[9] * 8 for _ in range(8)]
    door[0] = [10] * 8
    for y in range(8):
        door[y][0] = 10
        door[y][7] = 10
    grass = _speckle(11, 12, 1)
    water = _speckle(13, 14, 2)
    # A wooden barrel: a light-timber frame (10) with white corners (15), a
    # timber body (9) and two grey metal HOOPS (4). ORIGINAL procedural art,
    # authored here as integer shapes like every other town tile — no reference
    # import, so no ground-truth obligation. Every index is a town-palette
    # entry and none is 0, so the tile is fully OPAQUE (index 0 = the backdrop
    # this scene shows outside the room; a placed tile must not use it — the
    # same discipline cobble/brick/torch already follow).
    _B, _W, _F, _H = 9, 10, 15, 4        # body, frame-light, white, hoop
    barrel = [
        [_W, _F, _F, _F, _F, _F, _F, _W],
        [_F, _B, _B, _B, _B, _B, _B, _F],
        [_F, _H, _H, _H, _H, _H, _H, _F],
        [_F, _B, _B, _B, _B, _B, _B, _F],
        [_F, _B, _B, _B, _B, _B, _B, _F],
        [_F, _H, _H, _H, _H, _H, _H, _F],
        [_F, _B, _B, _B, _B, _B, _B, _F],
        [_W, _F, _F, _F, _F, _F, _F, _W],
    ]
    # the save-torch FLARE tile: a bigger, WHITE-HOT flame — core (8)
    # and highlight white (15) — so the swap on save reads as a real flare
    # against the small orange torch (TT_TORCH). Brick-dark (3) ground, opaque.
    torch_lit = [[3] * 8 for _ in range(8)]
    torch_lit[1] = [3, 3, 7, 8, 8, 7, 3, 3]
    torch_lit[2] = [3, 7, 8, 15, 15, 8, 7, 3]
    torch_lit[3] = [7, 8, 15, 15, 15, 15, 8, 7]
    torch_lit[4] = [3, 7, 8, 15, 15, 8, 7, 3]
    torch_lit[5] = [3, 3, 7, 8, 8, 7, 3, 3]
    tiles = [void, cobble, cobble2, brick, roof, torch, door, grass, water,
             barrel, torch_lit]
    labels = ["void", "cobble", "cobble2", "brick", "roof", "torch", "door",
              "grass", "water", "barrel", "torch_lit"]
    for rows, label in zip(tiles, labels):
        for y in range(8):
            for x in range(8):
                assert 0 <= rows[y][x] <= 15, f"town {label} ({x},{y})"
    tiles += [void] * (64 - len(tiles))
    return tiles


def town_map():
    """32x32 tile ids. The tilemap WORDS are built from these by main()."""
    m = [[TT_VOID] * TOWN_W for _ in range(TOWN_H)]
    # the plaza floor: everything inside the wall ring
    for y in range(2, 26):
        for x in range(2, 30):
            m[y][x] = TT_COBBLE if (x + y) % 2 == 0 else TT_COBBLE2
    # the wall ring
    for x in range(2, 30):
        m[2][x] = TT_BRICK
        m[25][x] = TT_BRICK
    for y in range(2, 26):
        m[y][2] = TT_BRICK
        m[y][29] = TT_BRICK
    # two buildings in the upper plaza
    for y in range(4, 8):
        for x in range(5, 11):
            m[y][x] = TT_BRICK
        for x in range(21, 27):
            m[y][x] = TT_BRICK
    for x in range(5, 11):
        m[3][x] = TT_ROOF
    for x in range(21, 27):
        m[3][x] = TT_ROOF
    # a fountain
    for y in range(13, 16):
        for x in range(14, 18):
            m[y][x] = TT_WATER
    # the two plaza barrels, the save point and the villager's post. The
    # barrels at (8,9)/(24,9) were decorative torches (owner pilot feedback,
    # 2026-08-08): swapped so the SAVE torch is the plaza's ONLY torch and the
    # save point is visually unique. The NPC-post torch (12,10) stays — the
    # villager sprite sits on it, so it does not read as a loose torch.
    for x in (8, 24):
        m[9][x] = TT_BARREL
    m[TOWN_SAVE_TY][TOWN_SAVE_TX] = TT_TORCH
    m[TOWN_NPC_TY][TOWN_NPC_TX] = TT_TORCH
    # a lawn strip and the south gate
    for x in range(4, 28):
        m[23][x] = TT_GRASS
    m[TOWN_EXIT_TY][TOWN_EXIT_TX] = TT_DOOR
    m[25][TOWN_EXIT_TX] = TT_DOOR
    assert m[TOWN_SPAWN_TY][TOWN_SPAWN_TX] not in TOWN_BLOCK, "town spawn blocks"
    return m


# ---------------------------------------------------------------------------
# the actors — 16x16 OBJ in the 16-tile-wide grid the PPU demands
# ---------------------------------------------------------------------------
def _sprite16(body, trim, skin):
    """A 16x16 index grid: a small hooded figure, plain and readable."""
    g = [[0] * 16 for _ in range(16)]
    for y in range(2, 7):                       # head
        for x in range(5, 11):
            g[y][x] = skin
    for x in range(4, 12):                      # hood brim
        g[1][x] = trim
        g[2][x] = trim
    for y in range(7, 13):                      # tunic
        for x in range(4, 12):
            g[y][x] = body
    for y in range(7, 13):
        g[y][3] = skin                          # arms
        g[y][12] = skin
    for y in range(13, 16):                     # legs
        for x in (5, 6, 9, 10):
            g[y][x] = 6
    for y in range(1, 16):                      # outline
        for x in range(16):
            if g[y][x] == 0 and any(
                    0 <= y + dy < 16 and 0 <= x + dx < 16 and g[y + dy][x + dx]
                    not in (0, 5) for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))):
                g[y][x] = 5
    return g


def obj_tileset():
    """64 4bpp tiles laid out as a 16-WIDE grid.

    The PPU reads a 16x16 OBJ as tiles {N, N+1, N+16, N+17} — the second row is
    +16 tile slots, never +2 — so a 16x16 sprite cannot be four consecutive
    tiles. Slot N=0 is the avatar, N=2 the villager.
    """
    tiles = [[[0] * 8 for _ in range(8)] for _ in range(64)]
    for slot, sprite in ((0, _sprite16(1, 2, 3)), (2, _sprite16(7, 8, 3))):
        for qy in range(2):
            for qx in range(2):
                dst = tiles[slot + qx + qy * 16]
                for y in range(8):
                    for x in range(8):
                        dst[y][x] = sprite[qy * 8 + y][qx * 8 + x]
    return tiles


# ---------------------------------------------------------------------------
def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    # --- Mode 7: one grid, TWO representations, one pass -------------------
    grid = world_tiles()
    flat = bytearray(W * H)
    for y in range(H):
        for x in range(W):
            flat[y * W + x] = grid[y][x]
    chrbytes = bytearray()
    for i, rows in enumerate(m7_tileset()):
        chrbytes += encode_8bpp(rows, f"m7 tile {i}")
    assert len(chrbytes) == 16384, len(chrbytes)
    interleaved = bytearray(32768)
    for i in range(16384):
        interleaved[i * 2] = flat[i]
        interleaved[i * 2 + 1] = chrbytes[i]

    flags = bytearray(256)
    for tid, f in FLAGS.items():
        flags[tid] = f

    # --- the town ----------------------------------------------------------
    town_chr = bytearray()
    for i, rows in enumerate(town_tileset()):
        town_chr += encode_4bpp(rows, f"town tile {i}")
    tm = town_map()
    town_words = bytearray()
    for y in range(TOWN_H):
        for x in range(TOWN_W):
            town_words += bytes((tm[y][x] & 0xFF, 0x00))   # palette 0, prio 0

    obj_chr = bytearray()
    for i, rows in enumerate(obj_tileset()):
        obj_chr += encode_4bpp(rows, f"obj tile {i}")

    files = {
        "rpg_m7.bin": bytes(interleaved),
        "rpg_col.bin": bytes(flat),
        "rpg_flags.bin": bytes(flags),
        "rpg_m7_pal.bin": encode_pal(M7_PAL, "m7 palette"),
        "rpg_town_chr.bin": bytes(town_chr),
        "rpg_town_map.bin": bytes(town_words),
        "rpg_town_pal.bin": encode_pal(TOWN_PAL, "town palette"),
        "rpg_obj_chr.bin": bytes(obj_chr),
        "rpg_obj_pal.bin": encode_pal(OBJ_PAL, "obj palette"),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
