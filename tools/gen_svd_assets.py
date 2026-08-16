#!/usr/bin/env python3
"""Generate split_v_demo's ROM blobs.

Six blobs, all derived from the numbers below:

  svd_stage_chr.bin  5 x 4bpp tiles.  Tile 0 EMPTY (the four solid tiles are
                     uploaded starting at tile 1, `$2010 = word $2000 +
                     tile 1*16`, so the tilemap carries ids 1..4 and id 0
                     stays the transparent one).  Tiles 1..4 = solid colour
                     indices 1..4.
  svd_stage_map.bin  the 32x32 landscape, built from the height map below
                     by the four-branch cell rule below.
  svd_stage_pal.bin  BG palette 0, 16 CGRAM words.  Word 0 is the BACKDROP
                     and it is WHITE: the seam bar is the backdrop showing
                     through window 2, so word 0 IS the bar's colour.
  svd_obj_chr.bin    1 x 4bpp tile, solid colour index 1 -- the `player_tile`
                     (8 rows of $FF,$00 then 8 of $00,$00 is a 4bpp tile whose
                     every pixel is index 1).
  svd_obj_pal.bin    OBJ palette 0, 16 CGRAM words; word 1 red.
  svd_diag_tab.bin   the DIAGONAL seam's HDMA table (see below).

THE DIAGONAL TABLE is this rail's one genuinely new artefact and it is a
ROM blob because the slant is STATIC -- the tables are built once and never
recomputed.  One channel, DMAP mode 4 = four registers written
once per line, so one 4-byte group drives WH0/WH1/WH2/WH3 -- window 1's
left edge, its right edge, and the divider band's two edges -- and the
seam slants because the group changes every scanline.

    seam(s) = DIAG_BASE + ((s * DIAG_SLOPE) >> 8)      s = 0..223

with DIAG_BASE = 72 and DIAG_SLOPE = $0080 (0.5 px/line), so
the seam runs 72 -> 183 and crosses screen centre at s = 112.  Table shape
is window_iris's, for the same reason (two repeat entries covering 224
lines, because 127 is the per-entry ceiling):

    [$FF] repeat 127  -> lines   0..126, 4 B each
    [$E1] repeat  97  -> lines 127..223, 4 B each
    [$00] terminator
    = 1 + 508 + 1 + 388 + 1 = 899 B

This module is also the tests' oracle: tests/test_split_v_demo.py imports
nothing from it but re-derives the same numbers from the description above, so
a generator bug and an ASM bug cannot agree with each other.
"""
import sys
from pathlib import Path

# --- the stage's constants
HMAP = (18, 18, 17, 16, 15, 13, 11, 9, 8, 8, 9, 11, 13, 15, 16, 17,
        17, 16, 15, 14, 14, 15, 16, 17, 17, 16, 15, 15, 16, 17, 18, 18)
GND_DIRT = 24            # rows >= this are dirt
MTN_LO, MTN_HI = 6, 13   # cols [6,13) above the dirt are mountain
DIAG_BASE = 72           # seam x at the top scanline
DIAG_SLOPE = 0x0080      # 8.8 px per scanline
BAND_HW = 6              # seam band half-width (bar = 2*HW px wide)
SCREEN_LINES = 224

TILE_SKY, TILE_GRASS, TILE_MTN, TILE_DIRT = 1, 2, 3, 4

# BGR15.  Word 0 white = the seam bar.
STAGE_COLOURS = (0x7FFF, 0x7F54, 0x02E0, 0x4A52, 0x1194)
MARKER_COLOUR = 0x001F   # red, OBJ palette 0 index 1


def solid_4bpp_tile(index: int) -> bytes:
    """A 4bpp 8x8 tile whose every pixel is `index`.

    ca65 order: rows 0..7 of planes 0,1 interleaved, then rows 0..7 of
    planes 2,3.  A plane is $FF when its bit is set in `index`.
    """
    out = bytearray()
    for planes in ((0, 1), (2, 3)):
        for _row in range(8):
            for p in planes:
                out.append(0xFF if (index >> p) & 1 else 0x00)
    return bytes(out)


def stage_chr() -> bytes:
    return b"\x00" * 32 + b"".join(solid_4bpp_tile(i) for i in (1, 2, 3, 4))


def cell(col: int, row: int) -> int:
    """The four-branch cell rule: sky, grass, mountain, dirt."""
    if row < HMAP[col]:
        return TILE_SKY
    if row >= GND_DIRT:
        return TILE_DIRT
    if MTN_LO <= col < MTN_HI:
        return TILE_MTN
    return TILE_GRASS


def stage_map() -> bytes:
    """32x32 tilemap words: bare tile ids (palette 0, no flip, no priority)."""
    out = bytearray()
    for row in range(32):
        for col in range(32):
            out += cell(col, row).to_bytes(2, "little")
    return bytes(out)


def palette(words) -> bytes:
    padded = tuple(words) + (0,) * (16 - len(words))
    return b"".join(w.to_bytes(2, "little") for w in padded)


def diag_seam_x(line: int) -> int:
    return DIAG_BASE + ((line * DIAG_SLOPE) >> 8)


def diag_table() -> bytes:
    """The per-scanline WH0/WH1/WH2/WH3 group for every one of 224 lines."""
    out = bytearray()
    line = 0
    for count in (127, 97):
        out.append(0x80 | count)                # repeat: `count` transfers
        for _ in range(count):
            seam = diag_seam_x(line)
            out += bytes((seam, 255, seam - BAND_HW, seam + BAND_HW))
            line += 1
    out.append(0x00)                            # terminator
    assert line == SCREEN_LINES, line
    return bytes(out)


BLOBS = {
    "svd_stage_chr.bin": stage_chr,
    "svd_stage_map.bin": stage_map,
    "svd_stage_pal.bin": lambda: palette(STAGE_COLOURS),
    "svd_obj_chr.bin": lambda: solid_4bpp_tile(1),
    "svd_obj_pal.bin": lambda: palette((0x0000, MARKER_COLOUR)),
    "svd_diag_tab.bin": diag_table,
}


def main(argv):
    out_dir = Path(argv[1] if len(argv) > 1 else "build/assets")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, make in BLOBS.items():
        data = make()
        (out_dir / name).write_bytes(data)
        print(f"{name}: {len(data)} B")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
