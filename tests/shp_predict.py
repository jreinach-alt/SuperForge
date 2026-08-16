"""The Mode 7 PER-SCANLINE predictor `tests/test_split_h_persp_demo.py` asserts on.

It holds NO rail-specific numbers — no band count, no seam, no pose set, no
origin — only the transform and the frame geometry, so the rail's geometry
stays in the rail's own module where a reader can compare it to the
header it models.

WHY A PREDICTOR AT ALL, when the rail's headline signal is an on-screen checker
period. Because on a PERSPECTIVE band the period is a different number on every
scanline and an integer on almost none of them: the world square is 32 px and
the scale ramps from `s_far` to `s_near`, so the on-screen square walks
32*256/S(k) continuously — 25.6 px at the top of camera A's band, 85.3 px at
the bottom. A run-length assertion cannot describe any of those rows exactly,
so it could only be taken at the two ends and only approximately. Predicting
the pixels makes EVERY row assertable, and it carries claims a period cannot
state at all: that both bands read ONE map (a second copy, a wrong tilemap row,
a wrong CHR byte or a wrong palette index would each fail it), and that the
seam falls on exactly the declared scanline.

THE TRANSFORM IS MESEN2'S, READ FROM ITS SOURCE, not from a hardware doc's
prose (AGENTS.md's "re-derive register encodings from Mesen2" rule, applied to
a transform rather than an encoding). `SnesPpu.cpp::RenderTilemapMode7`:

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

The `& ~63` terms are faithful two's-complement AND and DO fire here — unlike
on a flat-matrix rail, this one's per-scanline A/B/C/D and its off-centre
origins put real bits in the low six — which is the reason to take the
transform from the source rather than to simplify it.

`realY` IS MESEN'S `_scanline`, WHICH IS NOT THE PICTURE ROW. Rendering is
guarded by `_scanline > 0`, so the first rendered line is `_scanline == 1` and
it lands on PNG row `PICTURE_TOP` of the 256x239 frame Mesen hands back. Both
constants live in `tests/frame_geometry.py` since 2026-08-07 and are
re-exported here. They are still MEASURED rather than inherited:
`test_the_frame_geometry_is_the_one_this _predictor_assumes` in the rail's
module re-solves the offset by predicting the boot frame at six candidates and
requiring exactly one to mismatch zero rows.

WHAT IS **NOT** HERE, and belongs to the caller: which pose a row streams. On a
per-scanline rail that is the whole mechanism, and it differs per band (a
band-local index, restarted at the seam), so the module passes this file a
`matrix_of_row` callable and an `origin_of_row` callable and keeps its own
band list. A predictor that knew about bands would be asserting the rail's
design against itself.
"""
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent

# The frame geometry is a fact about MESEN, not about this rail, and lives in
# one place now. Re-exported under the same
# names so no call site changes. The module's own
# `test_the_frame_geometry_is_the_one_this_predictor_assumes` still RE-SOLVES
# the offset from the picture, which is the half sharing cannot do.
from frame_geometry import (FRAME_H, FRAME_W, PICTURE_LINES,  # noqa: F401,E402
                            PICTURE_TOP, REAL_Y_BIAS, png_row)

MAP_T = 128                     # world side, in tiles
TILE_PX = 8
WORLD_PX = MAP_T * TILE_PX      # 1024


def bgr555_to_rgb(word: int) -> tuple:
    """Mesen's full-brightness expansion: 5 bits -> (v << 3) | (v >> 2)."""
    return tuple(((c << 3) | (c >> 2))
                 for c in (word & 31, (word >> 5) & 31, (word >> 10) & 31))


def load_palette(pal_bytes: bytes) -> list:
    return [bgr555_to_rgb(pal_bytes[i] | (pal_bytes[i + 1] << 8))
            for i in range(0, len(pal_bytes), 2)]


def _clip(v: int) -> int:
    return (v | ~0x3FF) if (v & 0x2000) else (v & 0x3FF)


def predict_row(blob: bytes, cgram: list, picture_row: int,
                a: int, b: int, c: int, d: int,
                centre_x: int, centre_y: int, hofs: int, vofs: int,
                real_y_bias: int = REAL_Y_BIAS) -> list:
    """The 256 RGB pixels one matrix + one origin render on one picture row.

    `blob` is the INTERLEAVED Mode 7 image (tilemap even, 8bpp CHR odd) — the
    same bytes the ROM DMAs into VRAM.
    """
    real_y = picture_row + real_y_bias
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


def predict_frame(blob: bytes, cgram: list, matrix_of_row, origin_of_row,
                  real_y_bias: int = REAL_Y_BIAS) -> list:
    """All 224 rows. `matrix_of_row(r) -> (A,B,C,D)`; `origin_of_row(r) ->
    (centre_x, centre_y, hofs, vofs)`. Both are the CALLER's — see the module
    docstring for why the band model does not live here."""
    return [predict_row(blob, cgram, r, *matrix_of_row(r), *origin_of_row(r),
                        real_y_bias=real_y_bias)
            for r in range(PICTURE_LINES)]


def actual_row(image, picture_row: int) -> list:
    r = png_row(picture_row)
    return [image.getpixel((x, r)) for x in range(FRAME_W)]


def actual_frame(image) -> list:
    return [actual_row(image, r) for r in range(PICTURE_LINES)]


def first_run(image, picture_row: int) -> int:
    """The length of a row's first colour run — the on-screen checker period at
    the (rare) scales that divide the world square into whole screen pixels."""
    row = actual_row(image, picture_row)
    n = 1
    while n < FRAME_W and row[n] == row[0]:
        n += 1
    return n


def transitions(image, picture_row: int) -> int:
    """How many colour changes a row carries — the period signal, robust at a
    scale whose run-lengths alternate rather than repeat."""
    row = actual_row(image, picture_row)
    return sum(1 for x in range(1, FRAME_W) if row[x] != row[x - 1])


def mean_red(image, r0: int, r1: int, step: int = 4) -> float:
    """Mean red channel over picture rows [r0, r1) — the rail's per-band WORLD
    POSITION signal. The cool checker pair carries red 0 by construction and
    the warm pair carries red > 0 (the generator asserts the separation), so a
    band's mean red says WHICH STRIPE its camera is looking at, independently
    of what its matrix is doing."""
    tot = n = 0
    for r in range(r0, r1):
        row = actual_row(image, r)
        for x in range(0, FRAME_W, step):
            tot += row[x][0]
            n += 1
    return tot / n


def read_poses(path: Path) -> list:
    """A pose set as [pose][row] -> (lo_word, hi_word), signed."""
    raw = Path(path).read_bytes()

    def s16(off):
        v = raw[off] | (raw[off + 1] << 8)
        return v - 0x10000 if v & 0x8000 else v

    stride = PICTURE_LINES // 2 * 4                 # 448 B: a band-local pose
    return [[(s16(p * stride + r * 4), s16(p * stride + r * 4 + 2))
             for r in range(stride // 4)]
            for p in range(len(raw) // stride)]
