"""The Mode 7 flat-matrix predictor the matrix-band PAIR's modules assert on.

Both `tests/test_split_h_matrix_demo.py` (two bands) and
`tests/test_split_h_persp3_demo.py` (three) read their picture through this
file. It holds NO rail-specific numbers — no band count, no seam, no scale —
only the transform, so a rail's geometry stays in the rail's own module where
a reader can compare it to the header it models.

WHY A PREDICTOR AT ALL, when the rails' headline signal is an on-screen
checker PERIOD. Because the period is only an integer at the three scales the
shipping bands use. The moment a test drives the live band's zoom — which is
the whole of the pair's fourth teaching, the live HDMA-table patch — the scale
passes through values like $0044, whose period is 8 * 256 / 68 = 30.1 px and
whose run-lengths alternate 30/30/31. A run-length assertion cannot describe
that frame at all, so it would have to stop at the endpoints and skip the
cycle. Predicting the pixels makes every intermediate scale assertable and
makes the endpoints stronger at the same time: the comparison is over all 256
pixels of a row rather than over the length of its first run.

THE TRANSFORM IS MESEN2'S, READ FROM ITS SOURCE, not from a hardware doc's
prose (AGENTS.md's "re-derive register encodings from Mesen2" rule, applied to
a transform rather than an encoding). `SnesPpu.cpp::RenderTilemapMode7`, lines
1135-1224 of the tree at /tmp/Mesen2:

    clip(v)   = (v & 0x2000) ? (v | ~0x3ff) : (v & 0x3ff)
    xValue    = ((A * clip(hScroll - centerX)) & ~63)
              + ((B * realY)                  & ~63)
              + ((B * clip(vScroll - centerY))& ~63)
              + (centerX << 8)
    yValue    = same with C, D and centerY
    per pixel:  xOffset = xValue >> 8 ; yOffset = yValue >> 8
                xValue += A           ; yValue += C
    tile      = vram_word[((yOffset & ~7) << 4) | (xOffset >> 3)]  -> LOW byte
    colour    = vram_word[(tile << 6) + ((yOffset & 7) << 3)
                          + (xOffset & 7)]                         -> HIGH byte

The `& ~63` terms are faithful two's-complement AND, and are a no-op at every
scale these rails use — kept because dropping a term that happens not to fire
is how a predictor stops being the machine's.

`realY` IS MESEN'S `_scanline`, WHICH IS NOT THE PICTURE ROW. Rendering is
guarded by `_scanline > 0`, so the first rendered line is `_scanline == 1` and
it lands on PNG row 7 of the 256x239 frame Mesen hands back. MEASURED rather
than argued: predicting every row of `split_h_matrix_demo`'s boot frame at
seven candidate offsets mismatched 69/52/35/18/**0**/18/36 rows, so `realY =
picture_row + 1` is the only offset that describes the machine, and it agrees
with the `_scanline > 0` guard. Both constants live in
`tests/frame_geometry.py` since 2026-08-07 and are re-exported here under the
same names; the modules still re-assert them from the picture, which is the
half sharing cannot do.
"""
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
ASSETS = SUPERFORGE / "build" / "assets"

# The frame geometry is a fact about MESEN, not about these rails, and lives in
# one place now. Re-exported under the same
# names so no call site changes and `P.PICTURE_LINES` keeps working.
from frame_geometry import (FRAME_H, FRAME_W, PICTURE_LINES,  # noqa: F401,E402
                            PICTURE_TOP, REAL_Y_BIAS, png_row)

MAP_T = 128                     # world side, in tiles
TILE_PX = 8
WORLD_PX = MAP_T * TILE_PX      # 1024
CENTRE = WORLD_PX // 2          # the rails' M7X/M7Y


def bgr555_to_rgb(word: int) -> tuple:
    """Mesen's full-brightness expansion: 5 bits -> (v << 3) | (v >> 2)."""
    return tuple(((c << 3) | (c >> 2))
                 for c in (word & 31, (word >> 5) & 31, (word >> 10) & 31))


def load_palette(pal_bytes: bytes) -> list:
    return [bgr555_to_rgb(pal_bytes[i] | (pal_bytes[i + 1] << 8))
            for i in range(0, len(pal_bytes), 2)]


def _clip(v: int) -> int:
    return (v | ~0x3FF) if (v & 0x2000) else (v & 0x3FF)


def predict_row(blob: bytes, cgram: list, scale: int, picture_row: int,
                a=None, b=0, c=0, d=None,
                centre_x=CENTRE, centre_y=CENTRE, hofs=0, vofs=0) -> list:
    """The 256 RGB pixels a flat matrix renders on one picture row.

    `scale` fills M7A and M7D; `a`/`d` override it for a test that wants an
    asymmetric matrix. `blob` is the INTERLEAVED Mode 7 image (tilemap even,
    8bpp CHR odd) — the same bytes the ROM DMAs into VRAM.
    """
    a = scale if a is None else a
    d = scale if d is None else d
    real_y = picture_row + REAL_Y_BIAS
    xv = (((a * _clip(hofs - centre_x)) & ~63) + ((b * real_y) & ~63)
          + ((b * _clip(vofs - centre_y)) & ~63) + (centre_x << 8))
    yv = (((c * _clip(hofs - centre_x)) & ~63) + ((d * real_y) & ~63)
          + ((d * _clip(vofs - centre_y)) & ~63) + (centre_y << 8))
    out = []
    for _ in range(FRAME_W):
        xo = (xv >> 8) & 0x3FF          # M7SEL = 0: the plane wraps at 1024
        yo = (yv >> 8) & 0x3FF
        xv += a
        yv += c
        tile = blob[2 * (((yo & ~7) << 4) | (xo >> 3))]
        idx = blob[2 * ((tile << 6) + ((yo & 7) << 3) + (xo & 7)) + 1]
        out.append(cgram[idx])
    return out


def actual_row(image, picture_row: int) -> list:
    r = png_row(picture_row)
    return [image.getpixel((x, r)) for x in range(FRAME_W)]


def first_run(image, picture_row: int) -> int:
    """The length of a row's first colour run — the on-screen checker PERIOD
    at any scale that divides 8 px into a whole number of screen pixels."""
    row = actual_row(image, picture_row)
    n = 1
    while n < FRAME_W and row[n] == row[0]:
        n += 1
    return n


def run_profile(image) -> list:
    """(first_run) per picture row — the shape a seam shows up in."""
    return [first_run(image, r) for r in range(PICTURE_LINES)]


def derive_checker_blob() -> bytes:
    """The reference's world, RE-DERIVED here from its generator's prose.

    `templates/split_h_matrix_demo/assets/gen_map.py`: tile (row, col) is
    `(row ^ col) & 1`; CHR is two solid 8bpp tiles of palette index 1 and 2;
    the two halves are byte-interleaved. NO shared code with
    tools/gen_split_h_matrix_assets.py — which is the point: a generator bug
    and a test bug cannot agree with each other, and the vendored reference
    oracle is a third independent derivation of the same bytes.
    """
    tilemap = bytearray(MAP_T * MAP_T)
    for row in range(MAP_T):
        for col in range(MAP_T):
            tilemap[row * MAP_T + col] = (row ^ col) & 1
    chr_bytes = bytearray(MAP_T * MAP_T)
    chr_bytes[0:64] = bytes([1]) * 64
    chr_bytes[64:128] = bytes([2]) * 64
    out = bytearray(2 * MAP_T * MAP_T)
    out[0::2] = tilemap
    out[1::2] = chr_bytes
    return bytes(out)


def band_entry(lines: int, scale: int) -> tuple:
    """One AB-table entry and its CD partner, as the ROM must have built them.

    A = D = scale, B = C = 0 — a flat top-down camera at angle 0 — and the
    count byte's bit 7 CLEAR, which is the NON-REPEAT reading.
    """
    lo, hi = scale & 0xFF, (scale >> 8) & 0xFF
    return (bytes((lines, lo, hi, 0, 0)), bytes((lines, 0, 0, lo, hi)))
