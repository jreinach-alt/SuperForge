#!/usr/bin/env python3
"""gen_lakeside_assets.py — deterministic art for the `lakeside` rail.

Emits (byte-identical on re-run, pure integer math):

  lk_chr.bin    9 x 4bpp BG1 tiles, 32 B each = 288 B   the world's bands
  lk_map.bin    32x32 tilemap words = 2048 B            the banded world
  lk_pal.bin    16 BGR555 words = 32 B                  BG palette group 0
                (CGRAM 0..15; word 0 IS the backdrop slot)
  wat_chr.bin   3 x 4bpp BG2 tiles = 96 B               0 empty, 1 crest,
                                                        2 trough
  wat_map.bin   32x32 tilemap words = 2048 B            the surface
  wat_pal.bin   16 BGR555 words = 32 B                  BG palette group 2
                (CGRAM 32..47)

WHY THE COLOURS ARE WHAT THEY ARE. The rail's subject is a half-add, and its
tests assert the composited pixel as an EQUALITY rather than a tolerance:
for each 5-bit channel the PPU computes min((main + sub) >> 1, 31)
(Mesen2 SnesPpu.cpp:1372-1377 — the shift is applied before the clamp, so
with two operands of at most 31 the clamp never bites for a half-add). That
only works if every pair of colours that can meet on screen produces a
distinct answer, so the palettes below are chosen to keep all of

    bed_near, bed_far, crest, trough,
    (bed_near+crest)>>1, (bed_near+trough)>>1,
    (bed_far+crest)>>1,  (bed_far+trough)>>1

pairwise different, and `assert_blend_colours_are_distinguishable` proves it
here rather than leaving it to a reader. A collision would not fail the
generator's own output — it would make a passing test unable to tell a
blended pixel from an unblended one, which is the indirect-evidence trap one
layer down.

THE TWO UNIFORM BANDS. The surface map is not one pattern. Map rows 14..16
are ALL crest and rows 20..22 are ALL trough, so those two horizontal bands
are opaque on the sub screen at EVERY horizontal scroll — which makes the
equality assertions hold at every x and every frame, independent of the
drift. The wave rows between and below them carry gaps, so the same picture
also exercises the empty-sub fallback inside the water band, and the gaps
move with the scroll.

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): `encode_4bpp` asserts
every pixel index is 0..15 and `encode_pal` asserts every entry is a 15-bit
BGR value. An out-of-range author error stops the generator naming the
offending pixel; it never quietly becomes a different colour.
"""
import sys
from pathlib import Path

# --- BGR555 helper ---------------------------------------------------------
# The SNES word is B<<10 | G<<5 | R, five bits per channel. Written as a
# function of the three channels rather than as hex literals so the blend
# arithmetic below can be read against the same numbers the tests use.


def bgr(r, g, b):
    assert all(0 <= c <= 31 for c in (r, g, b)), f"channel out of range: {r},{g},{b}"
    return (b << 10) | (g << 5) | r


# --- BG1: the world, palette group 0 (CGRAM words 0..15) -------------------
# Word 0 is the 4bpp transparent slot AND the hardware backdrop at once,
# which is why lake_bg claims it rather than composing `backdrop`.
BACKDROP = (2, 3, 8)          # deep night blue — the main screen's floor
SKY = (18, 24, 30)            # pale daylight blue
HILL = (4, 14, 6)             # dark green horizon
SAND = (26, 22, 12)           # warm sand
ROCK = (14, 12, 10)           # the shoreline rocks
ROCK_LIT = (20, 18, 16)       # their lit faces
BED_NEAR = (2, 10, 12)        # lake bed, the near shelf
BED_FAR = (1, 6, 9)           # lake bed, the deep water

LK_PAL = [bgr(*BACKDROP), bgr(*SKY), bgr(*HILL), bgr(*SAND), bgr(*ROCK),
          bgr(*BED_NEAR), bgr(*BED_FAR), bgr(*ROCK_LIT)] + [0] * 8

# --- BG2: the surface, palette group 2 (CGRAM words 32..47) ---------------
CREST = (8, 20, 22)           # the lit face of a ripple
TROUGH = (4, 10, 18)          # its shaded face

WAT_PAL = [0, bgr(*CREST), bgr(*TROUGH)] + [0] * 13

# --- tile art --------------------------------------------------------------
# Palette indices inside a tile, not colours. Index 0 is transparent in a
# 4bpp BG, which is what draws the water's edge.
LK_I_SKY, LK_I_HILL, LK_I_SAND = 1, 2, 3
LK_I_ROCK, LK_I_BED_N, LK_I_BED_F, LK_I_ROCK_LIT = 4, 5, 6, 7


def flat(index):
    return [[index] * 8 for _ in range(8)]


def split(top_index, bottom_index, at_row):
    """A seam tile: `top_index` above row `at_row`, `bottom_index` from it."""
    return [[top_index if y < at_row else bottom_index] * 8 for y in range(8)]


def rock_tile():
    """The shoreline band: rock with lit faces on a fixed 8x8 pattern.

    Hand-authored rather than generated from noise so the byte output is a
    property of this file and not of a seed. The pattern is deliberately
    asymmetric left-to-right, which is what makes the band read as rubble
    rather than as a grid.
    """
    lit = {(0, 1), (1, 1), (1, 2), (4, 0), (5, 0), (2, 4), (3, 4), (3, 5),
           (6, 3), (7, 3), (5, 6), (6, 6), (0, 6), (7, 5)}
    return [[LK_I_ROCK_LIT if (x, y) in lit else LK_I_ROCK
             for x in range(8)] for y in range(8)]


# BG1 tile ids, in the order they are packed into lk_chr.bin.
LK_T_EMPTY, LK_T_SKY, LK_T_HILL, LK_T_HORIZON = 0, 1, 2, 3
LK_T_SAND, LK_T_SHORE, LK_T_ROCK, LK_T_BED_N, LK_T_BED_F = 4, 5, 6, 7, 8

LK_TILES = [
    flat(0),                                   # 0 empty — written, not assumed
    flat(LK_I_SKY),                            # 1 sky
    flat(LK_I_HILL),                           # 2 hill
    split(LK_I_SKY, LK_I_HILL, 4),             # 3 the horizon seam
    flat(LK_I_SAND),                           # 4 sand
    split(LK_I_HILL, LK_I_SAND, 5),            # 5 the hill/sand seam
    rock_tile(),                               # 6 the rock shoreline
    flat(LK_I_BED_N),                          # 7 lake bed, near shelf
    flat(LK_I_BED_F),                          # 8 lake bed, deep
]

WAT_T_EMPTY, WAT_T_CREST, WAT_T_TROUGH = 0, 1, 2
WAT_TILES = [flat(0), flat(1), flat(2)]

# --- the maps --------------------------------------------------------------
MAP_DIM = 32

# The world, band by band: the tile every cell of a row carries. Rows 28..31
# are off the bottom of a 224-line picture and repeat the deep water rather
# than being left unwritten (power-on VRAM is random — rule 5).
LK_ROWS = ([LK_T_SKY] * 6 + [LK_T_HORIZON] + [LK_T_HILL] * 3
           + [LK_T_SHORE] + [LK_T_SAND] * 2 + [LK_T_ROCK]
           + [LK_T_BED_N] * 6 + [LK_T_BED_F] * 12)
assert len(LK_ROWS) == MAP_DIM

# The surface. Rows 0..13 are empty: above the shoreline the sub screen has
# no pixel at all, which is the edge the tests read. Rows 14..16 and 20..22
# are UNIFORM (see the module docstring); the rest carry the ripple.
WAT_UNIFORM = {r: WAT_T_CREST for r in (14, 15, 16)}
WAT_UNIFORM.update({r: WAT_T_TROUGH for r in (20, 21, 22)})
WAT_WAVE_ROWS = set(range(17, 20)) | set(range(23, 28))

# The ripple, as a 4-cell cycle: 8 px crest, 8 px trough, 16 px of nothing.
# The phase steps by one cell per row, so the bands run diagonally and read
# as moving water rather than as columns.
WAT_CYCLE = [WAT_T_CREST, WAT_T_TROUGH, WAT_T_EMPTY, WAT_T_EMPTY]

# The attribute halves of a tilemap word: BG1 authors palette group 0 and
# priority 0, so its word IS its tile id; BG2 authors palette group 2.
LK_ATTR = 0
WAT_ATTR = 2 << 10


def lk_map_words():
    return [LK_ROWS[row] | LK_ATTR
            for row in range(MAP_DIM) for _ in range(MAP_DIM)]


def wat_map_words():
    out = []
    for row in range(MAP_DIM):
        for col in range(MAP_DIM):
            if row in WAT_UNIFORM:
                tile = WAT_UNIFORM[row]
            elif row in WAT_WAVE_ROWS:
                tile = WAT_CYCLE[(col + row) & 3]
            else:
                tile = WAT_T_EMPTY
            out.append(tile | WAT_ATTR)
    return out


# --- encoders --------------------------------------------------------------
def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3).

    Asserts rather than masks: an index outside 0..15 names its own pixel.
    """
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    for y, row in enumerate(rows):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} px, expected 8"
        for x, v in enumerate(row):
            assert 0 <= v <= 15, (
                f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
    out = bytearray()
    for pair in (0, 2):                      # planes 0/1, then planes 2/3
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                lo = (lo << 1) | ((v >> pair) & 1)
                hi = (hi << 1) | ((v >> (pair + 1)) & 1)
            out += bytes((lo, hi))
    assert len(out) == 32, f"{label}: encoded {len(out)} B, expected 32"
    return bytes(out)


def encode_words(words, label, count):
    assert len(words) == count, f"{label}: {len(words)} words, expected {count}"
    out = bytearray()
    for i, w in enumerate(words):
        assert 0 <= w <= 0xFFFF, f"{label}: entry {i} value {w:#06x} is not 16-bit"
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def encode_pal(words, label):
    for i, w in enumerate(words):
        assert 0 <= w <= 0x7FFF, (
            f"{label}: entry {i} value {w:#06x} is not a 15-bit BGR555 word")
    return encode_words(words, label, 16)


# --- the property the tests depend on --------------------------------------
def half_add(main, sub):
    """The PPU's half-add, per 5-bit channel: min((main + sub) >> 1, 31).

    Mesen2 SnesPpu.cpp:1372-1377. Written here so the generator can prove the
    palette keeps the results distinguishable; the tests derive their own
    expectations from CGRAM rather than importing this.
    """
    return tuple(min((a + b) >> 1, 31) for a, b in zip(main, sub))


def assert_blend_colours_are_distinguishable():
    named = {"bed_near": BED_NEAR, "bed_far": BED_FAR,
             "crest": CREST, "trough": TROUGH,
             "rock": ROCK, "sand": SAND, "sky": SKY, "hill": HILL}
    for main in ("bed_near", "bed_far"):
        for sub in ("crest", "trough"):
            named[f"{main}+{sub}"] = half_add(named[main], named[sub])
    seen = {}
    for name, colour in named.items():
        clash = seen.get(colour)
        assert clash is None, (
            f"palette collision: '{name}' and '{clash}' are both {colour} — a "
            f"test could not tell a blended pixel from an unblended one")
        seen[colour] = name
    return named


def main(outdir):
    blend = assert_blend_colours_are_distinguishable()
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "lk_chr.bin": b"".join(encode_4bpp(t, f"lk tile {i}")
                               for i, t in enumerate(LK_TILES)),
        "lk_map.bin": encode_words(lk_map_words(), "lk map", MAP_DIM * MAP_DIM),
        "lk_pal.bin": encode_pal(LK_PAL, "lk palette"),
        "wat_chr.bin": b"".join(encode_4bpp(t, f"wat tile {i}")
                                for i, t in enumerate(WAT_TILES)),
        "wat_map.bin": encode_words(wat_map_words(), "wat map",
                                    MAP_DIM * MAP_DIM),
        "wat_pal.bin": encode_pal(WAT_PAL, "wat palette"),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")
    for name in ("bed_near+crest", "bed_near+trough",
                 "bed_far+crest", "bed_far+trough"):
        print(f"  half-add {name} = {blend[name]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
