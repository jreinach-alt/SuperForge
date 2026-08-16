#!/usr/bin/env python3
"""gen_boss_assets.py — the boss rail's art: the arena golem plane + the cast.

Emits (deterministic; byte-identical on re-run):

    bs_map.bin         32,768 B  interleaved Mode 7 VRAM image (tilemap | CHR)
    bs_pal.bin             32 B  16 BGR555 words, index 0 = the arena dark
    bs_sprite_chr.bin   1,024 B  32 OBJ tiles, 4bpp (two 16-tile VRAM rows)
    bs_sprite_pal.bin      32 B  16 BGR555 words (one OBJ palette, whole cast)

AUTHORED, NOT IMPORTED (mo_rom's route). The reference rail's own art is
first-party procedural — make_boss.py draws its "Cragmaw Sentinel" golem head
from ellipse/box predicates over the 128x128 tile grid, every 8x8 tile one
solid colour so the converter dedups to a couple dozen tiles. This file is
the same kind of author with an ORIGINAL design, so there is no converter
between a source asset and this output and no converter to ground-truth
( step 1's carve-out; mode7_explore and m7_oshoot took the same
route).

THE DESIGN — the "Ashen Warden": a horned obsidian skull carved into the
arena floor, filling the middle ~48x48 tiles so it reads BIG when the pivot
sits at map centre (512,512). Two swept horns; ember eyes under a heavy brow;
a fanged jaw plate; a teal sigil burning in the forehead. The arena around it
is a two-tone dark checker — the motion cue that makes the Mode 7 rotation
and the reveal's scale ramp legible even where the skull is off-screen.

The interleave, the solid-tile dedup and the OBJ grid layout are
gen_m7_oshoot_assets.py's, function for function: Mode 7 VRAM words carry the
tilemap entry in the LOW byte and the CHR pixel in the HIGH byte, so build-
time interleaving makes the upload one DMA; a 16x16 sprite reads tiles
{N, N+1, N+16, N+17}, so the sheet is two 16-tile rows with the 8x8 cast in
row 0's tail.

CGRAM INDEX 0 IS THE BACKDROP (hardware): the predicate deliberately paints
world tile (0,0) with the arena dark, so the first colour the row-major dedup
scans lands the backdrop tone at index 0 BY CONSTRUCTION — asserted below
rather than fixed up after. A converter that lets some other tone reach index
0 first has to evict it afterwards; ordering the paint so the backdrop tone
gets there first removes the eviction pass entirely, and the assert is what
keeps that true when someone recolours the arena.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

WORLD_T = 128               # tiles per side (the Mode 7 tilemap is 128x128)
TILE_PX = 8
MAP_BYTES = WORLD_T * WORLD_T          # 16,384 tilemap bytes / CHR bytes
BLOB_BYTES = 2 * MAP_BYTES             # 32,768 interleaved
PAL_WORDS = 16                         # the bs_pal claim, exactly
OBJ_TILE_BYTES = 32
OBJ_TILES = 32                         # two 16-tile rows
CENTER = 63.5                          # arena centre, tile units

# --- the floor palette (RGB; dedup assigns CGRAM indices in scan order) ----
ARENA_DARK = (12, 10, 16)   # arena floor A — and the backdrop, index 0
ARENA_TILE = (24, 20, 32)   # arena floor B (the checker's motion cue)
OBSID_DK = (52, 48, 64)     # skull stone, shadow
OBSID_MD = (88, 82, 100)    # skull stone, midtone
OBSID_LT = (132, 124, 146)  # skull stone, lit edge
HORN_DK = (92, 64, 40)      # horn, shadow
HORN_LT = (176, 132, 84)    # horn, lit
EMBER = (255, 120, 24)      # eye core
EMBER_DIM = (140, 48, 12)   # eye socket rim
JAW_DK = (36, 32, 44)       # jaw cavity
FANG = (228, 224, 212)      # fangs
SIGIL = (80, 255, 180)      # forehead sigil core
SIGIL_DIM = (32, 130, 90)   # sigil halo
FLOOR_COLOURS = [ARENA_DARK, ARENA_TILE, OBSID_DK, OBSID_MD, OBSID_LT,
                 HORN_DK, HORN_LT, EMBER, EMBER_DIM, JAW_DK, FANG,
                 SIGIL, SIGIL_DIM]


def _ellipse(tx, ty, cx, cy, rx, ry):
    dx = (tx - cx) / rx
    dy = (ty - cy) / ry
    return dx * dx + dy * dy <= 1.0


def tile_color(tx: int, ty: int) -> tuple[int, int, int]:
    """One solid colour per 8x8 tile — the Warden, feature by feature, else
    the arena checker."""
    cx, cy = CENTER, CENTER

    # ---- horns: chains of shrinking circles sweeping up and out ----
    for i, (hx, hy, hr) in enumerate((
            (48, 46, 5.0), (44, 40, 4.2), (42, 34, 3.5),
            (41, 28, 2.8), (41, 23, 2.0))):
        if _ellipse(tx, ty, hx, hy, hr, hr):
            return HORN_LT if (i + tx) & 1 else HORN_DK
    for i, (hx, hy, hr) in enumerate((
            (79, 46, 5.0), (83, 40, 4.2), (85, 34, 3.5),
            (86, 28, 2.8), (86, 23, 2.0))):
        if _ellipse(tx, ty, hx, hy, hr, hr):
            return HORN_LT if (i + tx) & 1 else HORN_DK

    # ---- the skull mass: a broad rounded block, heavier above the jaw ----
    if not _ellipse(tx, ty, cx, cy + 2, 22, 24):
        # the arena: a two-tone checker in 4x4-tile blocks
        return ARENA_TILE if ((tx >> 2) + (ty >> 2)) & 1 else ARENA_DARK

    # forehead sigil: a burning diamond, high centre
    if abs(tx - cx) + abs(ty - 48) <= 3.5:
        return SIGIL
    if abs(tx - cx) + abs(ty - 48) <= 5.5:
        return SIGIL_DIM

    # brow ridge: a heavy dark bar over the eyes
    if 47 <= tx <= 80 and 54 <= ty <= 58:
        return OBSID_DK

    # eyes: ember cores in dim sockets, under the brow
    for ex in (54, 73):
        if _ellipse(tx, ty, ex, 63, 5.2, 4.2):
            if _ellipse(tx, ty, ex, 63, 2.6, 2.2):
                return EMBER
            return EMBER_DIM

    # nose slits: two short dark grooves
    if 61 <= tx <= 66 and 68 <= ty <= 71 and (tx in (62, 65)):
        return JAW_DK

    # jaw plate: a dark cavity band with four fangs hanging into it
    if 52 <= tx <= 75 and 74 <= ty <= 82:
        if ty <= 76 and tx in (55, 61, 67, 73):
            return FANG
        if ty >= 80 and tx in (58, 64, 70):
            return FANG
        return JAW_DK

    # cheek cracks: lit fissures down the stone
    if (tx + 2 * ty) % 19 == 0 and _ellipse(tx, ty, cx, cy + 2, 20, 22):
        return OBSID_LT

    # base stone: midtone, shadowed toward the rim
    if _ellipse(tx, ty, cx, cy + 2, 17, 19):
        return OBSID_MD
    return OBSID_DK


# =============================================================================
# The Mode 7 converter (gen_m7_oshoot_assets.py's, function for function)
# =============================================================================

def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def convert_map() -> tuple[bytes, bytes, list[tuple[int, int, int]]]:
    """(tile_data padded to 256 tiles, tilemap, palette in scan order)."""
    color_map: dict[tuple[int, int, int], int] = {}
    palette_rgb: list[tuple[int, int, int]] = []
    unique: dict[int, int] = {}
    tile_data = bytearray()
    tilemap = bytearray()

    for ty in range(WORLD_T):
        for tx in range(WORLD_T):
            color = tile_color(tx, ty)
            if color not in color_map:
                color_map[color] = len(palette_rgb)
                palette_rgb.append(color)
            ci = color_map[color]
            if ci not in unique:                 # solid tiles: one per colour
                unique[ci] = len(unique)
                tile_data.extend(bytes([ci]) * (TILE_PX * TILE_PX))
            tilemap.append(unique[ci])

    if len(palette_rgb) > PAL_WORDS:
        raise ValueError(f"{len(palette_rgb)} colours; the bs_pal claim is "
                         f"{PAL_WORDS} words")
    assert palette_rgb[0] == ARENA_DARK, (
        "index 0 must be the arena dark: it is the Mode 7 backdrop slot, and "
        "the predicate puts it there by painting tile (0,0) with it — "
        "recolouring the arena moved it")
    tile_data.extend(bytes(MAP_BYTES - len(tile_data)))     # pad to 256 tiles
    return bytes(tile_data), bytes(tilemap), palette_rgb


def interleave(tilemap: bytes, tile_data: bytes) -> bytes:
    out = bytearray(BLOB_BYTES)
    out[0::2] = tilemap
    out[1::2] = tile_data
    return bytes(out)


def floor_pal(palette_rgb) -> bytes:
    """Exactly 16 words; the unused tail repeats the backdrop tone so the
    claim, the file and the CGRAM upload agree byte for byte."""
    out = bytearray()
    for i in range(PAL_WORDS):
        rgb = palette_rgb[i] if i < len(palette_rgb) else ARENA_DARK
        out += struct.pack("<H", rgb_to_bgr555(*rgb))
    return bytes(out)


# =============================================================================
# The cast (4bpp OBJ) — one sheet, one palette
# =============================================================================
# Sprite palette indices ('.' = 0 = transparent):
#   1 hull lit (cyan)   2 hull mid    3 hull dark    4 canopy white
#   5 orb core          6 orb rim     7 bolt core    8 pip green
#   9 pip green dark    A pip dim     B pip dim dark C flash white
SPRITE_COLOURS = [
    (0, 0, 0),          # 0 transparent (never rendered)
    (96, 232, 255),     # 1 hull lit
    (40, 150, 210),     # 2 hull mid
    (16, 70, 120),      # 3 hull dark
    (235, 250, 255),    # 4 canopy
    (255, 150, 40),     # 5 orb core
    (170, 52, 16),      # 6 orb rim
    (190, 255, 250),    # 7 bolt core
    (80, 230, 90),      # 8 pip lit
    (24, 110, 40),      # 9 pip lit dark
    (90, 90, 104),      # A pip dim
    (44, 44, 56),       # B pip dim dark
    (255, 255, 255),    # C flash white
]

PLAYER_F0 = [                       # 16x16 arrowhead gunship, nose UP
    ".......11.......",
    "......1221......",
    "......1221......",
    ".....124421.....",
    ".....124421.....",
    "....12244221....",
    "....12222221....",
    "...1222222221...",
    "...1223223221...",
    "..122232232221..",
    "..122222222221..",
    ".12232222223221.",
    ".12321222212321.",
    "1223.122221.3221",
    "122..112211..221",
    "1....1....1....1",
]


def hit_frame(rows):
    """The iframe flash: every hull tone slammed to white, shape kept."""
    return ["".join("C" if ch in "123" else ch for ch in row) for row in rows]


ORB = [                             # 8x8 enemy attack orb
    "..6666..",
    ".665566.",
    "65555556",
    "65555556",
    "65555556",
    "65555556",
    ".665566.",
    "..6666..",
]

SHOT = [                            # 8x8 player bolt (travels up)
    "...77...",
    "...77...",
    "..7117..",
    "..7117..",
    "..7117..",
    "..7117..",
    "...77...",
    "...77...",
]

PIP_LIT = [                         # 8x8 HP segment, lit
    "99999999",
    "98888889",
    "98888889",
    "98888889",
    "98888889",
    "98888889",
    "98888889",
    "99999999",
]

PIP_DIM = [                         # 8x8 HP segment, depleted (hollow ring)
    "BBBBBBBB",
    "BAAAAAAB",
    "BA....AB",
    "BA....AB",
    "BA....AB",
    "BA....AB",
    "BAAAAAAB",
    "BBBBBBBB",
]


def _pix(ch: str) -> int:
    return 0 if ch == "." else int(ch, 16)


def encode_tile_4bpp(rows, ox: int, oy: int) -> bytes:
    """8x8 at (ox,oy) -> 32 B SNES 4bpp planar (planes 0/1 rows 0-15,
    planes 2/3 rows 16-31; bit 7 = leftmost)."""
    out = bytearray(OBJ_TILE_BYTES)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            v = _pix(rows[oy + y][ox + x])
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def sprite_chr() -> bytes:
    """32 tiles, two 16-tile VRAM rows. Player F0 quad {0,1,16,17}, F1 quad
    {2,3,18,19} (one tile-column over); the 8x8 cast at row-0 tiles 4..7."""
    f1 = hit_frame(PLAYER_F0)
    tiles = [bytes(OBJ_TILE_BYTES)] * OBJ_TILES
    for base, art in ((0, PLAYER_F0), (2, f1)):
        assert len(art) == 16 and all(len(r) == 16 for r in art)
        for ty in range(2):
            for tx in range(2):
                tiles[base + ty * 16 + tx] = encode_tile_4bpp(
                    art, tx * 8, ty * 8)
    for slot, art in ((4, ORB), (5, SHOT), (6, PIP_LIT), (7, PIP_DIM)):
        assert len(art) == 8 and all(len(r) == 8 for r in art)
        tiles[slot] = encode_tile_4bpp(art, 0, 0)
    return b"".join(tiles)


def sprite_pal() -> bytes:
    out = bytearray()
    for rgb in SPRITE_COLOURS:
        out += struct.pack("<H", rgb_to_bgr555(*rgb))
    return bytes(out) + bytes(2 * (16 - len(SPRITE_COLOURS)))


def main(argv):
    if len(argv) != 2:
        print("usage: gen_boss_assets.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    tile_data, tilemap, palette_rgb = convert_map()
    blobs = {
        "bs_map.bin": interleave(tilemap, tile_data),
        "bs_pal.bin": floor_pal(palette_rgb),
        "bs_sprite_chr.bin": sprite_chr(),
        "bs_sprite_pal.bin": sprite_pal(),
    }
    want = {"bs_map.bin": BLOB_BYTES, "bs_pal.bin": 32,
            "bs_sprite_chr.bin": 1024, "bs_sprite_pal.bin": 32}
    for name, data in blobs.items():
        assert len(data) == want[name], (name, len(data))   # == the rom claim
        (outdir / name).write_bytes(data)
        print(f"wrote {outdir / name} ({len(data)} B)")
    print(f"  {len(palette_rgb)} floor colours, "
          f"{len(set(tilemap))} unique tiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
