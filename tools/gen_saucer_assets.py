#!/usr/bin/env python3
"""gen_saucer_assets.py — boss_saucer's art: the saucer plane + the cast.

Emits (deterministic; byte-identical on re-run):

    sau_map.bin         32,768 B  interleaved Mode 7 VRAM image (tilemap | CHR)
    sau_pal.bin             32 B  16 BGR555 words, index 0 = the night sky
    sau_sprite_chr.bin   1,536 B  48 OBJ tiles, 4bpp (three 16-tile VRAM rows)
    sau_sprite_pal.bin      64 B  TWO OBJ palettes: 0 = the cast, 1 = the stars

AUTHORED, NOT IMPORTED, the same route `mo_rom` takes.
The reference rail's own art is first-party procedural — make_saucer.py draws its
"Disc Marauder" from ellipse predicates over the 128x128 tile grid, every 8x8
tile one solid colour, so the converter dedups to a few dozen tiles. This file
is the same kind of author with an ORIGINAL design, so there is no converter
between a source asset and this output and no converter to ground-truth


THE DESIGN — the "Sable Halo": a dark ringed disc, drawn as CONCENTRIC bands
so it is almost radially symmetric, with a twelve-lamp amber running ring at
the hull's equator and a glowing teal canopy over a white-hot ventral emitter
at the pivot. The near-symmetry is a DESIGN DECISION, not a style whim. The
fight snaps the heading to 0 on its first frame (`stz b_angle` — rotation is
OFF once the fight starts) after the HOLD phase has spun it to 105, and that
snap is choreography: it has to read as the saucer settling, not as the art
jumping. Twelve lamps put one full lamp pitch at 256/12 = 21.33 headings, so a
105-heading snap lands 4.92 pitches on — 1.7 headings, about 2.4 degrees, off
a perfect lamp-to-lamp alignment. The spin still READS (the lamp ring sweeps);
the snap does not.

The interleave, the solid-tile dedup and the OBJ grid layout are
gen_boss_assets.py's, function for function: Mode 7 VRAM words carry the
tilemap entry in the LOW byte and the CHR pixel in the HIGH byte, so
build-time interleaving makes the upload one DMA; a 16x16 sprite reads tiles
{N, N+1, N+16, N+17}, so the sheet is 16-tile rows with the 8x8 cast in row
0's tail and the glyph set in rows 1-2.

CGRAM INDEX 0 IS THE BACKDROP (hardware): the plane's off-disc region is the
night sky and world tile (0,0) is off the disc, so the row-major dedup lands
the backdrop tone at index 0 BY CONSTRUCTION — asserted below rather than
fixed up after. It is also what lets the STARS sit UNDER the plane: a Mode 7
pixel of value 0 is transparent (Mesen2 `SnesPpu::RenderTilemapMode7`:
`if(colorIndex > 0)`), so the whole sky is a hole the backdrop shows through,
and an OBJ sprite drawn below BG1 shows there and is covered by the hull.

THE STAR FIELD IS NOT IN THE PLANE. It used to be — a two-density scatter
baked into the world tile grid — and that put it on the one layer the fight
RAMPS: four scale ramps zoom the plane, so the stars grew and shrank in
lockstep with a near object, which is backwards for a field at infinity and
is most of why the old field read as dense noise. The stars are now OBJ
sprites (sau_obj's `stars` band), on their own OBJ palette so a test can
count star pixels without them being confusable with any cast or hull tone,
and drawn at OAM priority 0 — the one OBJ priority Mode 7 puts BELOW BG1
(Mesen2 `SnesPpu::RenderMode7`: sprite priorities {2,4,6,7} against BG1's 3),
so the saucer occludes them instead of them freckling its hull.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

WORLD_T = 128               # tiles per side (the Mode 7 tilemap is 128x128)
TILE_PX = 8
MAP_BYTES = WORLD_T * WORLD_T          # 16,384 tilemap bytes / CHR bytes
BLOB_BYTES = 2 * MAP_BYTES             # 32,768 interleaved
PAL_WORDS = 16                         # the sau_pal claim, exactly
OBJ_TILE_BYTES = 32
OBJ_TILES = 48                         # three 16-tile rows
CENTER = 63.5                          # arena centre, tile units
LAMPS = 12                             # running lights (see the header)
LAMP_R = 16.5                          # lamp ring radius, tiles

# --- the floor palette (RGB; dedup assigns CGRAM indices in scan order) ----
# THE TWO STAR TONES ARE GONE, NOT REHOMED. They were plane colours because the
# star field was plane texture; the field is OBJ now and its tones live in the
# star OBJ palette below, so the floor palette has two fewer AUTHORED colours
# and `floor_pal` pads the tail with the sky tone exactly as before — the claim,
# the file and the CGRAM upload are still 16 words. Repurposing the freed
# indices would have meant inventing a plane colour to justify them.
SKY_DARK = (6, 8, 18)        # night sky — AND the backdrop, index 0
HULL_EDGE = (14, 16, 26)     # hull outline / dome seam
HULL_DK = (44, 50, 66)       # hull, shadowed band
HULL_MD = (86, 94, 116)      # hull, midtone band
HULL_LT = (146, 156, 180)    # hull, lit band
RIM_LT = (198, 206, 226)     # the outer rim's metallic glint
LAMP_ON = (255, 190, 60)     # running lamp, lit core
LAMP_DIM = (146, 92, 22)     # running lamp, halo
DOME_DK = (16, 74, 106)      # canopy, shadow
DOME_MD = (46, 156, 204)     # canopy, midtone
DOME_LT = (140, 226, 250)    # canopy, glowing highlight
EMIT_DK = (58, 148, 104)     # ventral emitter, outer glow
EMIT_LT = (206, 255, 224)    # ventral emitter, hot core
FLOOR_COLOURS = [SKY_DARK, HULL_EDGE, HULL_DK, HULL_MD, HULL_LT, RIM_LT,
                 LAMP_ON, LAMP_DIM, DOME_DK, DOME_MD, DOME_LT, EMIT_DK,
                 EMIT_LT]


def tile_color(tx: int, ty: int) -> tuple[int, int, int]:
    """One solid colour per 8x8 tile — the Sable Halo, band by band, else the
    night sky."""
    dx, dy = tx - CENTER, ty - CENTER
    r = math.hypot(dx, dy)

    # ---- off the disc: flat night sky ------------------------------------
    # ONE tone, and that is the point: value 0 is transparent in Mode 7, so
    # this whole region is a hole the backdrop fills — which is the layer the
    # OBJ star field now sits in, under the hull. World tile (0,0) is out here
    # (r = 89.8), so the row-major dedup still meets the sky first.
    if r > 22.0:
        return SKY_DARK

    # ---- the hull outline ------------------------------------------------
    if r > 21.0:
        return HULL_EDGE
    if r > 19.4:
        return RIM_LT

    # ---- the twelve running lamps, on the hull's equator -----------------
    for k in range(LAMPS):
        a = 2.0 * math.pi * k / LAMPS
        lx, ly = LAMP_R * math.cos(a), LAMP_R * math.sin(a)
        d = math.hypot(dx - lx, dy - ly)
        if d <= 1.05:
            return LAMP_ON
        if d <= 1.95:
            return LAMP_DIM

    # ---- the canopy and the ventral emitter at the pivot -----------------
    if r <= 2.3:
        return EMIT_LT
    if r <= 3.4:
        return EMIT_DK
    if r <= 5.2:
        return DOME_LT
    if r <= 7.1:
        return DOME_MD
    if r <= 8.6:
        return DOME_DK
    if r <= 9.6:
        return HULL_EDGE

    # ---- the hull: concentric bands, so a spin reads as ring motion ------
    band = int((r - 9.6) / 1.6)
    return (HULL_LT, HULL_MD, HULL_DK)[band % 3]


# =============================================================================
# The Mode 7 converter (gen_boss_assets.py's, function for function)
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
        raise ValueError(f"{len(palette_rgb)} colours; the sau_pal claim is "
                         f"{PAL_WORDS} words")
    assert palette_rgb[0] == SKY_DARK, (
        "index 0 must be the night sky: it is the Mode 7 backdrop slot, and "
        "the scan meets the sky first because world tile (0,0) is off the "
        "disc — recolouring the sky, or growing the disc past the corner, "
        "moved it")
    tile_data.extend(bytes(MAP_BYTES - len(tile_data)))     # pad to 256 tiles
    return bytes(tile_data), bytes(tilemap), palette_rgb


def interleave(tilemap: bytes, tile_data: bytes) -> bytes:
    out = bytearray(BLOB_BYTES)
    out[0::2] = tilemap
    out[1::2] = tile_data
    return bytes(out)


def floor_pal(palette_rgb) -> bytes:
    """Exactly 16 words; the unused tail repeats the sky tone so the claim,
    the file and the CGRAM upload agree byte for byte."""
    out = bytearray()
    for i in range(PAL_WORDS):
        rgb = palette_rgb[i] if i < len(palette_rgb) else SKY_DARK
        out += struct.pack("<H", rgb_to_bgr555(*rgb))
    return bytes(out)


# =============================================================================
# The cast (4bpp OBJ) — one sheet, one palette
# =============================================================================
# Sprite palette indices ('.' = 0 = transparent):
#   1 hull lit    2 hull mid   3 hull dark   4 canopy      5 beam core
#   6 beam edge   7 bolt core  8 pip lit     9 pip lit dk  A pip dim
#   B pip dim dk (ALSO the card banner)      C flash white
#   D exhaust hot E exhaust cool             F glyph white
SPRITE_COLOURS = [
    (0, 0, 0),          # 0 transparent (never rendered)
    (150, 230, 255),    # 1 hull lit
    (58, 140, 200),     # 2 hull mid
    (22, 62, 104),      # 3 hull dark
    (240, 252, 255),    # 4 canopy
    (255, 255, 240),    # 5 beam core (white-hot)
    (96, 226, 255),     # 6 beam edge (cyan)
    (170, 255, 236),    # 7 bolt core
    (96, 236, 108),     # 8 pip lit
    (26, 116, 44),      # 9 pip lit dark
    (96, 96, 110),      # A pip dim
    (40, 40, 54),       # B pip dim dark / the card banner
    (255, 255, 255),    # C flash white
    (255, 226, 96),     # D exhaust hot
    (232, 104, 28),     # E exhaust cool
    (236, 244, 255),    # F glyph white
]

PLAYER_F0 = [                       # 16x16 wide-winged gunship, nose UP
    ".......11.......",
    "......1441......",
    "......1441......",
    "......1441......",
    ".....124421.....",
    ".....122221.....",
    "..1..122221..1..",
    ".111.122221.111.",
    "1122112222112211",
    "1223212222123231",
    "1223212222123231",
    "1223122222223221",
    ".132122222221231",
    "..1.122332211.1.",
    "....12.33.21....",
    "....1..EE..1....",
]


def hit_frame(rows):
    """The iframe flash: every hull tone slammed to white, shape kept."""
    return ["".join("C" if ch in "123" else ch for ch in row) for row in rows]


SHOT = [                            # 8x8 player bolt (travels up)
    "...77...",
    "..7117..",
    "..7117..",
    "..7117..",
    "..7117..",
    "..7117..",
    "..7117..",
    "...77...",
]

PIP_LIT = [                         # 8x8 HP segment, lit
    ".999999.",
    "98888889",
    "98888889",
    "98888889",
    "98888889",
    "98888889",
    "98888889",
    ".999999.",
]

PIP_DIM = [                         # 8x8 HP segment, depleted (hollow)
    ".BBBBBB.",
    "BAAAAAAB",
    "BA....AB",
    "BA....AB",
    "BA....AB",
    "BA....AB",
    "BAAAAAAB",
    ".BBBBBB.",
]

# THE BEAM, three cells. The lance walks a straight line from the saucer's
# emitter to the latched column, so the body cell is FULL WIDTH and every row
# is identical: consecutive placements step at most 7.4 px across and 5 px down
# (saucer.inc's SAU_BEAM_PITCH / SAU_BEAM_MUL), and an 8 px cell touches its
# neighbour at either extreme. The debut's 4 px core was authored for a
# strictly vertical column and leaves 2 px gaps the moment the walk slopes.
BEAM = ["66555566"] * 8
# The telegraph's sight cell: a 4 px core with the cyan edge, drawn on the EVEN
# segments only, so the charge reads as a dotted line already aimed at where the
# beam will land. MEASURED at 2 px first: 128 lit pixels across the whole sight
# line, and more than half of them fall on the saucer's own pale hull, where a
# white-only core has almost no contrast. The cyan edge is what makes the dashes
# read there — this is the debut's beam cell, kept as the THIN half of a
# thin/solid pair rather than as the beam itself.
BEAM_TELE = ["..6556.."] * 8
# The burst: the emitter's muzzle flash, and the same cell again at the far end
# where the lance lands.
BEAM_FLARE = [
    "..6..6..",
    ".6.55.6.",
    "..5555..",
    "66555566",
    "66555566",
    "..5555..",
    ".6.55.6.",
    "..6..6..",
]

EXH_LO = [                          # thruster flame, short phase
    "........",
    "........",
    "........",
    "........",
    "..DDDD..",
    "..DEED..",
    "...EE...",
    "........",
]

EXH_HI = [                          # thruster flame, tall phase
    "........",
    "..DDDD..",
    ".DDDDDD.",
    ".DDEEDD.",
    "..EEEE..",
    "..EEEE..",
    "...EE...",
    "....E...",
]

CARDBG = ["BBBBBBBB"] * 8           # the result banner's 8x8 cell

BLANK8 = ["........"] * 8

# --- the glyph set: 5x7 faces, left-aligned in an 8x8 cell (GTEXT_ADV = 6
#     advances the pen 5 px of face + 1 px of gap). Only
#     the eighteen cells the four strings actually spell are authored.
def _g(*rows):
    assert len(rows) == 7, rows
    out = ["".join("F" if c == "#" else "." for c in r).ljust(8, ".")
           for r in rows]
    assert all(len(r) == 8 for r in out), out
    return out + ["........"]


GLYPHS = {
    "A": _g(".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "C": _g(".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    "D": _g("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": _g("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": _g("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "I": _g("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "M": _g("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": _g("#...#", "##..#", "#.#.#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": _g(".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "R": _g("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": _g(".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": _g("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": _g("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": _g("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": _g("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "Y": _g("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "<": _g("..#..", ".##..", "###..", ".##..", "..#..", ".....", "....."),
    ">": _g("..#..", "..##.", "..###", "..##.", "..#..", ".....", "....."),
}

# =============================================================================
# The star field (OBJ palette 1) — two faces, two depths
# =============================================================================
# WHY A SECOND PALETTE for three tones. Every one of palette 0's sixteen
# entries has an owner, and the rail's tests count POPULATIONS by rendered
# colour (`test_the_colour_predicates_are_disjoint` is the precondition that
# makes those counts attributable). Borrowing, say, the glyph white would make
# "star pixels" and "card pixels" the same population and quietly disarm both
# counts. A second palette is 16 free CGRAM words — the rail uses 32 of 256 —
# and it buys an EXACT star population: a star pixel cannot be anything else.
#
# Indices 1..3 only; 4..15 are never referenced by a star tile and are padded
# black. ('.' = 0 = transparent, as everywhere on the sheet.)
STAR_CORE = (216, 232, 255)     # 1 near-star core
STAR_HALO = (120, 148, 200)     # 2 near-star arms
STAR_FAINT = (84, 100, 148)     # 3 the far layer, one tone
STAR_COLOURS = [(0, 0, 0), STAR_CORE, STAR_HALO, STAR_FAINT] + [(0, 0, 0)] * 12

# A FOUR-POINT TWINKLE, not a dot. A single lit pixel is indistinguishable
# from sensor noise once the gallery GIF has quantised to <=128 colours; a
# 5x5 cross with dimmer arm tips reads as a star at 1:1 and survives the
# quantiser. Nine lit pixels, centred at (3,3) so the 8x8 cell's own
# top-left is what OAM places.
STAR_NEAR = [
    "........",
    "...2....",
    "...1....",
    ".21112..",
    "...1....",
    "...2....",
    "........",
    "........",
]

# The far layer: the same centre, one tone, five pixels — smaller and dimmer,
# which is the DEPTH cue the old two-density plane scatter used to carry. Here
# it is carried by the drift rate as well (the far band scrolls at half the
# near band's rate), so the two layers separate in motion, not only in tone.
STAR_FAR = [
    "........",
    "........",
    "...3....",
    "..333...",
    "...3....",
    "........",
    "........",
    "........",
]

# The sheet's tile numbers. 5/6/7/8 are the REFERENCE's own values for shot / pip
# lit / pip dim / beam (its assets/README.md load table), kept so a reader
# cross-checking both sources meets one numbering; tile 4 is its
# SPR_PROJECTILE slot, which the saucer template already ships present-but-
# unused ("the saucer attacks with the beam, not orbs") and which stays blank
# here for the same reason — a shifted-down cast would give tile 8 two
# different meanings across the two trees, which is worse than 32 blank bytes.
T_PLAYER0, T_PLAYER1 = 0, 2
T_SHOT, T_PIP_LIT, T_PIP_DIM, T_BEAM = 5, 6, 7, 8
T_EXH_LO, T_EXH_HI, T_CARDBG = 9, 10, 11
T_BEAM_TELE, T_BEAM_FLARE = 12, 13      # row 0's remaining free cells
T_STAR_FAR, T_STAR_NEAR = 14, 15        # ...and its last two
GLYPH_BASE = 20                     # row 1's tail, past the player's quads
GLYPH_ORDER = "ACDEFIMNORSTUVWY<>"  # the union the four strings spell
GLYPH_TILE = {ch: GLYPH_BASE + i for i, ch in enumerate(GLYPH_ORDER)}


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
    """48 tiles, three 16-tile VRAM rows. Player F0 quad {0,1,16,17}, F1 quad
    {2,3,18,19} (one tile-column over); the 8x8 cast in row 0's tail; the
    eighteen glyphs from tile 20."""
    f1 = hit_frame(PLAYER_F0)
    tiles = [bytes(OBJ_TILE_BYTES)] * OBJ_TILES
    for base, art in ((T_PLAYER0, PLAYER_F0), (T_PLAYER1, f1)):
        assert len(art) == 16 and all(len(r) == 16 for r in art), art
        for ty in range(2):
            for tx in range(2):
                tiles[base + ty * 16 + tx] = encode_tile_4bpp(
                    art, tx * 8, ty * 8)
    for slot, art in ((T_SHOT, SHOT), (T_PIP_LIT, PIP_LIT),
                      (T_PIP_DIM, PIP_DIM), (T_BEAM, BEAM),
                      (T_EXH_LO, EXH_LO), (T_EXH_HI, EXH_HI),
                      (T_CARDBG, CARDBG), (T_BEAM_TELE, BEAM_TELE),
                      (T_BEAM_FLARE, BEAM_FLARE), (T_STAR_FAR, STAR_FAR),
                      (T_STAR_NEAR, STAR_NEAR)):
        assert len(art) == 8 and all(len(r) == 8 for r in art), art
        tiles[slot] = encode_tile_4bpp(art, 0, 0)
    for ch, slot in GLYPH_TILE.items():
        assert slot < OBJ_TILES and tiles[slot] == bytes(OBJ_TILE_BYTES), \
            f"glyph {ch} would overwrite tile {slot}"
        tiles[slot] = encode_tile_4bpp(GLYPHS[ch], 0, 0)
    return b"".join(tiles)


def sprite_pal() -> bytes:
    """Both OBJ palettes, back to back — palette 0 (the cast) then palette 1
    (the stars). They are contiguous CGRAM words 128..159 by claim, which is
    what lets ONE upload loop carry both; sau_obj.asm asserts that adjacency
    at build time rather than trusting this comment."""
    assert len(SPRITE_COLOURS) == 16, len(SPRITE_COLOURS)
    assert len(STAR_COLOURS) == 16, len(STAR_COLOURS)
    out = bytearray()
    for rgb in SPRITE_COLOURS + STAR_COLOURS:
        out += struct.pack("<H", rgb_to_bgr555(*rgb))
    return bytes(out)


def main(argv):
    if len(argv) != 2:
        print("usage: gen_saucer_assets.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    tile_data, tilemap, palette_rgb = convert_map()
    blobs = {
        "sau_map.bin": interleave(tilemap, tile_data),
        "sau_pal.bin": floor_pal(palette_rgb),
        "sau_sprite_chr.bin": sprite_chr(),
        "sau_sprite_pal.bin": sprite_pal(),
    }
    want = {"sau_map.bin": BLOB_BYTES, "sau_pal.bin": 32,
            "sau_sprite_chr.bin": OBJ_TILES * OBJ_TILE_BYTES,
            "sau_sprite_pal.bin": 64}
    for name, data in blobs.items():
        assert len(data) == want[name], (name, len(data))   # == the rom claim
        (outdir / name).write_bytes(data)
        print(f"wrote {outdir / name} ({len(data)} B)")
    print(f"  {len(palette_rgb)} floor colours, "
          f"{len(set(tilemap))} unique tiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
