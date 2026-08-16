#!/usr/bin/env python3
"""gen_meteor_assets.py — the meteor_event rail's art.

Emits (deterministic; byte-identical on re-run):

    met_map.bin        32,768 B  interleaved Mode 7 VRAM image (tilemap | CHR)
    met_pal.bin            32 B  16 BGR555 words, index 0 = the night sky
    met_obj_chr.bin     3,072 B  96 OBJ tiles, 4bpp (six 16-tile VRAM rows)
    met_obj_pal.bin        32 B  16 BGR555 words (one OBJ palette, whole cast)
    met_bg_chr.bin        128 B  4 Mode-1 BG tiles, 4bpp
    met_bg_pal.bin         32 B  16 BGR555 words, index 0 = the night sky

AUTHORED, NOT IMPORTED, the same route `mo_rom` takes. The meteor and its cast
are drawn from shape predicates rather than traced from an image, so there is
no converter between a source asset and this output and therefore no converter
to ground-truth.

THE SCALE ARITHMETIC THIS ART IS SIZED AGAINST
----------------------------------------------
Mode 7 scale maps SCREEN to TEXEL: a larger matrix value samples a wider texel
span, so a larger value looks SMALLER. One screen pixel spans `scale / 256`
map pixels, so an object D map pixels across renders `D * 256 / scale` pixels
wide:

    crossover  scale $0E00 (14.0)   448 map px -> 32 screen px
    full       scale $0220 (2.125)  448 map px -> 211 screen px

Those two numbers are the tuned ones — $0E00 is about 32 px on screen, checked
on the emulator against the sprite it hands over from, and $0220 is the
full-size meteor nearly filling the screen height — so the meteor is drawn
448 map px across
(radius 28 tiles) and the hand-off from the 32x32 ROCKY sprite frame to the
Mode-7 plane happens at the same apparent size, which is the whole point of the
crossover.

CGRAM INDEX 0 IS THE BACKDROP (hardware): in Mode 7 an 8bpp pixel value is an
ABSOLUTE CGRAM index, and index 0 is also the backdrop slot. The predicate
paints world tile (0,0) with the night sky, so the row-major dedup lands that
tone at index 0 BY CONSTRUCTION — asserted below rather than fixed up
afterwards. That is also what makes the sprite phase's OFF-FIELD park read as
black: M7SEL bit 7 shows the BACKDROP outside the 1024-px field.

THE CAPTURE'S PIXEL-EXACTNESS IS AN ASSET DECISION, NOT ONLY A CODE ONE. The
Mode-1 platform tile is SOLID green and the captured OBJ block is the SAME
solid green at the SAME palette entry (BG palette word 1 and OBJ palette word 1
are one RGB constant, asserted below). So when ST_CAPTURE drops BG1 from TM,
the green pixel set of the frame is expected to be IDENTICAL — which is what
tests/test_meteor_event.py asserts, and it can only be asserted because the two
colours are one constant here.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

WORLD_T = 128                       # tiles per side (Mode 7 tilemap is 128x128)
TILE_PX = 8
MAP_BYTES = WORLD_T * WORLD_T       # 16,384 tilemap bytes / CHR bytes
BLOB_BYTES = 2 * MAP_BYTES          # 32,768 interleaved
PAL_WORDS = 16
OBJ_TILE_BYTES = 32                 # 4bpp
OBJ_TILES = 96                      # six 16-tile VRAM rows
BG_TILES = 4
CENTER = 63.5                       # map centre, tile units — the affine pivot
MET_R_T = 28.0                      # meteor radius in TILES (448 px across)

# --- the palette (RGB; the dedup assigns CGRAM indices in scan order) ------
NIGHT = (8, 6, 20)          # the sky — and the backdrop, index 0
STAR = (150, 150, 170)      # sparse star tiles
ROCK_DK = (48, 44, 52)      # meteor body, shadow side
ROCK_MD = (96, 90, 96)      # meteor body, midtone
ROCK_LT = (150, 144, 148)   # meteor body, lit side
CRATER = (30, 28, 34)       # crater floors
EMBER_RIM = (196, 40, 24)   # the burning leading rim
EMBER_MID = (240, 128, 24)  # the fissures' orange shell
EMBER_CORE = (255, 226, 96)  # the molten core seen through the cracks
CHAR = (18, 16, 20)         # charred edge between rock and rim

FLOOR_COLOURS = [NIGHT, ROCK_DK, ROCK_MD, ROCK_LT, CRATER,
                 EMBER_RIM, EMBER_MID, EMBER_CORE, CHAR, STAR]

# --- the Mode-1 level's two colours ---------------------------------------
# GREEN is ONE constant used by the BG palette AND the OBJ palette, which is
# what makes the capture pixel-exact rather than approximately-the-same-hue.
GREEN = (64, 168, 72)
PLAYER_LT = (236, 240, 248)
PLAYER_DK = (56, 72, 120)

# Crater centres (tile units, relative to the meteor centre) and radii. A
# fixed hand-picked set rather than a PRNG: the art is a design, and a seeded
# generator would make a recolour or a radius change silently reshuffle it.
CRATERS = [(-9.0, -11.0, 6.0), (8.0, -6.0, 4.5), (-4.0, 6.0, 5.5),
           (12.0, 8.0, 3.5), (-15.0, 3.0, 3.0), (2.0, 15.0, 4.0)]

# Fissure rays: (angle-ish slope, half-width) in tile space, drawn as radial
# cracks that show the molten core.
FISSURES = [(0.55, 1.6), (-1.9, 1.4), (2.6, 1.2), (-0.35, 1.5)]

# Star tiles, in absolute tile coordinates — far from the meteor so a scale
# ramp never sweeps one across the disc.
STARS = [(6, 9), (19, 4), (31, 17), (14, 30), (103, 11), (117, 26),
         (96, 40), (9, 96), (24, 113), (110, 101), (119, 118), (46, 6),
         (78, 4), (5, 55), (122, 62), (60, 122)]


def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


# =============================================================================
# The Mode 7 plane — the meteor itself
# =============================================================================
def tile_color(tx: int, ty: int) -> tuple[int, int, int]:
    dx = tx - CENTER
    dy = ty - CENTER
    r = (dx * dx + dy * dy) ** 0.5
    if r > MET_R_T:
        return STAR if (tx, ty) in _STAR_SET else NIGHT
    if r > MET_R_T - 1.5:
        return CHAR                             # the charred outer edge
    if r > MET_R_T - 4.0:
        return EMBER_RIM                        # the burning leading rim
    # --- fissures: radial cracks showing the core ---------------------------
    for slope, half in FISSURES:
        # distance from the line through the centre with this slope
        d = abs(dy - slope * dx) / (1.0 + slope * slope) ** 0.5
        if d <= half * 0.45:
            return EMBER_CORE
        if d <= half:
            return EMBER_MID
    # --- craters ------------------------------------------------------------
    for cx, cy, cr in CRATERS:
        cd = ((dx - cx) ** 2 + (dy - cy) ** 2) ** 0.5
        if cd <= cr * 0.7:
            return CRATER
        if cd <= cr:
            return ROCK_DK
    # --- body shading: lit from the upper left ------------------------------
    lam = (dx + dy) / (2.0 * MET_R_T)           # -0.5 (upper left) .. +0.5
    if lam < -0.16:
        return ROCK_LT
    if lam < 0.14:
        return ROCK_MD
    return ROCK_DK


_STAR_SET = set(STARS)


def convert_map() -> tuple[bytes, bytes, list[tuple[int, int, int]]]:
    """(tile_data padded to 256 tiles, tilemap, palette in scan order).

    Every 8x8 tile is one solid colour, so the dedup emits one CHR tile per
    colour and the tilemap is a colour index map — gen_boss_assets.py's shape.
    """
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
            if ci not in unique:                # solid tiles: one per colour
                unique[ci] = len(unique)
                tile_data.extend(bytes([ci]) * (TILE_PX * TILE_PX))
            tilemap.append(unique[ci])

    if len(palette_rgb) > PAL_WORDS:
        raise ValueError(f"{len(palette_rgb)} colours; the met_pal claim is "
                         f"{PAL_WORDS} words")
    assert palette_rgb[0] == NIGHT, (
        "index 0 must be the night sky: it is the Mode 7 backdrop slot, and "
        "the predicate puts it there by painting tile (0,0) with it — "
        "recolouring the sky moved it")
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
        rgb = palette_rgb[i] if i < len(palette_rgb) else NIGHT
        out += struct.pack("<H", rgb_to_bgr555(*rgb))
    return bytes(out)


# =============================================================================
# The cast (4bpp OBJ) — one sheet, one palette
# =============================================================================
# OBJ palette indices. 0 is transparent by hardware contract.
P_GREEN = 1         # the captured ground/platform block — BG palette word 1
P_PL_LT = 2         # player body
P_PL_DK = 3         # player visor
P_ROCK_DK = 4
P_ROCK_MD = 5
P_ROCK_LT = 6
P_CRATER = 7
P_RIM = 8
P_EMBER = 9
P_CORE = 10
P_CHAR = 11

OBJ_COLOURS = [
    (0, 0, 0),      # 0 transparent (never fetched; kept black)
    GREEN,          # 1
    PLAYER_LT,      # 2
    PLAYER_DK,      # 3
    ROCK_DK,        # 4
    ROCK_MD,        # 5
    ROCK_LT,        # 6
    CRATER,         # 7
    EMBER_RIM,      # 8
    EMBER_MID,      # 9
    EMBER_CORE,     # 10
    CHAR,           # 11
]


def encode_tile_4bpp(px, ox: int, oy: int) -> bytes:
    """8x8 at (ox,oy) of a 2-D index grid -> 32 B SNES 4bpp planar."""
    out = bytearray(OBJ_TILE_BYTES)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            v = px[oy + y][ox + x]
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def solid(n: int, idx: int):
    return [[idx] * n for _ in range(n)]


def player_art():
    """16x16: a pale figure with a dark visor band. Solid enough that the
    freeze test can find it by colour and small enough to sit on the ground
    band without touching it (y 176..191 against a ground top of 192)."""
    g = [[0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            dx, dy = x - 7.5, y - 7.5
            if abs(dx) <= 5.0 and abs(dy) <= 7.0:
                g[y][x] = P_PL_LT
    for y in range(4, 7):                       # the visor band
        for x in range(3, 13):
            if g[y][x]:
                g[y][x] = P_PL_DK
    for y in range(12, 16):                     # legs: split the skirt
        g[y][7] = g[y][8] = 0
    return g


def meteor_art(n: int, radius: float, fiery: bool):
    """An n x n meteor frame. `fiery` draws the far specks (all ember, no
    rock); otherwise the ROCKY crossover frames, which resemble the Mode 7
    plane's meteor so the hand-off at ~32 px reads as one object."""
    c = (n - 1) / 2.0
    g = [[0] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            dx, dy = x - c, y - c
            r = (dx * dx + dy * dy) ** 0.5
            if r > radius:
                continue
            if fiery:
                g[y][x] = (P_CORE if r <= radius * 0.45 else
                           P_EMBER if r <= radius * 0.78 else P_RIM)
                continue
            if r > radius - 1.0:
                g[y][x] = P_CHAR
            elif r > radius - 3.0:
                g[y][x] = P_RIM
            else:
                # the same lighting law and the same crack idea as the plane,
                # at sprite scale
                if abs(dy - 0.55 * dx) / 1.145 <= radius * 0.10:
                    g[y][x] = P_CORE
                elif abs(dy + 1.9 * dx) / 2.147 <= radius * 0.11:
                    g[y][x] = P_EMBER
                elif ((dx + radius * 0.35) ** 2
                      + (dy + radius * 0.40) ** 2) ** 0.5 <= radius * 0.28:
                    g[y][x] = P_CRATER
                else:
                    lam = (dx + dy) / (2.0 * radius)
                    g[y][x] = (P_ROCK_LT if lam < -0.16 else
                               P_ROCK_MD if lam < 0.14 else P_ROCK_DK)
    return g


def blit(tiles, base: int, art, side: int) -> None:
    """Place a side x side sprite whose PPU tile quad starts at `base` on the
    16-tile VRAM row grid: a 16x16 reads {N, N+1, N+16, N+17} and a 32x32 the
    4x4 block from N, so a row step is +16 tiles, not +2."""
    n = side // 8
    for ty in range(n):
        for tx in range(n):
            tiles[base + ty * 16 + tx] = encode_tile_4bpp(art, tx * 8, ty * 8)


def sprite_chr() -> bytes:
    """96 tiles, six 16-tile VRAM rows.

      rows 0-3   tiles 0 / 4 / 8    three 32x32 ROCKY frames (r 10, 13, 15.5)
      rows 4-5   tile 64            16x16 captured ground/platform block
                 tile 66            16x16 player
                 tiles 68 / 70 / 72 three 16x16 FIERY specks (r 3, 5, 7)

    The frame ladder, laid out on the OBJ tile grid.
    """
    tiles = [bytes(OBJ_TILE_BYTES)] * OBJ_TILES
    for base, radius in ((0, 10.0), (4, 13.0), (8, 15.5)):
        blit(tiles, base, meteor_art(32, radius, fiery=False), 32)
    blit(tiles, 64, solid(16, P_GREEN), 16)
    blit(tiles, 66, player_art(), 16)
    for base, radius in ((68, 3.0), (70, 5.0), (72, 7.0)):
        blit(tiles, base, meteor_art(16, radius, fiery=True), 16)
    return b"".join(tiles)


def sprite_pal() -> bytes:
    out = bytearray()
    for rgb in OBJ_COLOURS:
        out += struct.pack("<H", rgb_to_bgr555(*rgb))
    return bytes(out) + bytes(2 * (PAL_WORDS - len(OBJ_COLOURS)))


# =============================================================================
# The Mode-1 level's BG tiles and palette
# =============================================================================
def bg_chr() -> bytes:
    """Four 4bpp tiles: 0 blank (index 0 = transparent -> the backdrop shows),
    1 the solid green platform/ground block, 2-3 spare so the claim is a whole
    128 B."""
    tiles = [encode_tile_4bpp(solid(8, 0), 0, 0),
             encode_tile_4bpp(solid(8, 1), 0, 0),
             bytes(OBJ_TILE_BYTES), bytes(OBJ_TILE_BYTES)]
    assert len(tiles) == BG_TILES
    return b"".join(tiles)


def bg_pal() -> bytes:
    """BG palette 0. Word 0 is the backdrop AND BG colour 0 — one owner by
    hardware contract, so it carries the same night the Mode 7 plane
    puts at its own index 0 and the swap does not flash a different sky."""
    words = [NIGHT, GREEN] + [NIGHT] * (PAL_WORDS - 2)
    return b"".join(struct.pack("<H", rgb_to_bgr555(*c)) for c in words)


def _selftest(pal_bytes: bytes, obj_pal_bytes: bytes, bg_pal_bytes: bytes,
              obj_chr_bytes: bytes) -> None:
    # THE CAPTURE'S COLOUR IDENTITY: the BG platform tile and the captured OBJ
    # block must be the same colour, or "the captured ground lands on the same
    # pixels" is a claim about geometry only. One RGB constant, two palettes,
    # asserted here so a recolour cannot break the test's premise silently.
    assert bg_pal_bytes[2:4] == obj_pal_bytes[2:4], (
        "BG palette word 1 and OBJ palette word 1 must be the same colour — "
        "the capture's pixel-exactness rests on it")
    # The two palettes' word 0 agree, so the swap does not flash a new sky.
    assert bg_pal_bytes[0:2] == pal_bytes[0:2]
    # The ground block really is solid: all 64 pixels of each of its four
    # tiles are index P_GREEN. Checked through the encoder, not around it.
    want = encode_tile_4bpp(solid(8, P_GREEN), 0, 0)
    for t in (64, 65, 80, 81):
        got = obj_chr_bytes[t * OBJ_TILE_BYTES:(t + 1) * OBJ_TILE_BYTES]
        assert got == want, f"capture block tile {t} is not solid green"


def main(argv):
    if len(argv) != 2:
        print("usage: gen_meteor_assets.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    tile_data, tilemap, palette_rgb = convert_map()
    files = {
        "met_map.bin": interleave(tilemap, tile_data),
        "met_pal.bin": floor_pal(palette_rgb),
        "met_obj_chr.bin": sprite_chr(),
        "met_obj_pal.bin": sprite_pal(),
        "met_bg_chr.bin": bg_chr(),
        "met_bg_pal.bin": bg_pal(),
    }
    _selftest(files["met_pal.bin"], files["met_obj_pal.bin"],
              files["met_bg_pal.bin"], files["met_obj_chr.bin"])
    want = {"met_map.bin": BLOB_BYTES, "met_pal.bin": 32,
            "met_obj_chr.bin": OBJ_TILES * OBJ_TILE_BYTES,
            "met_obj_pal.bin": 32, "met_bg_chr.bin": BG_TILES * 32,
            "met_bg_pal.bin": 32}
    for name, data in files.items():
        assert len(data) == want[name], (name, len(data), want[name])
        (outdir / name).write_bytes(data)
        print(f"wrote {outdir / name} ({len(data)} B)")
    print(f"  Mode 7 plane: {len(palette_rgb)} colours, "
          f"meteor radius {MET_R_T} tiles = {MET_R_T * 2 * TILE_PX:.0f} map px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
