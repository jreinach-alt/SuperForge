#!/usr/bin/env python3
"""gen_dialog_assets.py — the `dialog` feature's nine-patch CHR + panel palette.

Emits (byte-identical on re-run, pure integer math):

  dlg_chr.bin   9 x 2bpp tiles, 16 B each = 144 B   the nine-patch
  dlg_pal.bin   4 BGR555 words = 8 B                the panel sub-palette

THE OPACITY CONTRACT, which is the whole reason this file exists. A BG
palette's index 0 is TRANSPARENT by hardware, so a "box" drawn out of font
glyphs shows the scene through every pixel that is not a stroke — the box
reads as floating characters, not as a panel. That is the defect this file
exists to make impossible: do NOT hand-roll a box out of text glyphs, an
opaque box needs opaque CHR. So EVERY pixel of all nine tiles here is index
>= 1, and the generator ASSERTS it
rather than trusting the art: `assert_opaque` fails naming the offending pixel.

Nine-patch order (the order `_dlg_tile_for` picks from):
    0 TL   1 TOP   2 TR
    3 LEFT 4 FILL  5 RIGHT
    6 BL   7 BOT   8 BR

Colours are a documented 4-word table, not an inferred format:
    word 0  $0000  transparent slot — never used INSIDE the panel
    word 1  $2862  dark blue body
    word 2  $7BDE  pale border
    word 3  $7FFF  white (spare; glyphs print in the scene's own text palette)

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): `encode_2bpp` asserts every
index is 0..3 and `encode_pal` asserts every word is 15-bit. An out-of-range
author error stops the generator naming the pixel; it never becomes a different
colour.
"""
import sys
from pathlib import Path

BODY = 1                 # panel interior
EDGE = 2                 # frame line
PAL = [0x0000, 0x2862, 0x7BDE, 0x7FFF]


def tile(top=False, bottom=False, left=False, right=False):
    """An 8x8 body-fill tile with a 1-px frame line on the named sides."""
    rows = [[BODY] * 8 for _ in range(8)]
    if top:
        rows[0] = [EDGE] * 8
    if bottom:
        rows[7] = [EDGE] * 8
    for y in range(8):
        if left:
            rows[y][0] = EDGE
        if right:
            rows[y][7] = EDGE
    return rows


NINE_PATCH = [
    ("TL", tile(top=True, left=True)),
    ("TOP", tile(top=True)),
    ("TR", tile(top=True, right=True)),
    ("LEFT", tile(left=True)),
    ("FILL", tile()),
    ("RIGHT", tile(right=True)),
    ("BL", tile(bottom=True, left=True)),
    ("BOT", tile(bottom=True)),
    ("BR", tile(bottom=True, right=True)),
]


def assert_opaque(rows, label):
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            assert v >= 1, (
                f"{label}: pixel ({x},{y}) is index 0 — a panel cell may not be "
                f"transparent (the opacity contract)")


def encode_2bpp(rows, label):
    """8x8 indices -> 16 B SNES 2bpp (row-interleaved bitplanes 0 and 1)."""
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    out = bytearray()
    for y in range(8):
        assert len(rows[y]) == 8, f"{label}: row {y} is not 8 px"
        lo = hi = 0
        for x in range(8):
            v = rows[y][x]
            assert 0 <= v <= 3, (
                f"{label}: pixel ({x},{y}) index {v} is outside 2bpp 0..3")
            lo = (lo << 1) | (v & 1)
            hi = (hi << 1) | ((v >> 1) & 1)
        out += bytes((lo, hi))
    assert len(out) == 16, f"{label}: encoded {len(out)} B, expected 16"
    return bytes(out)


def encode_pal(words, label):
    out = bytearray()
    for i, w in enumerate(words):
        assert 0 <= w <= 0x7FFF, (
            f"{label}: entry {i} value {w:#06x} is not a 15-bit BGR555 word")
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    chr_bytes = bytearray()
    for name, rows in NINE_PATCH:
        assert_opaque(rows, name)
        chr_bytes += encode_2bpp(rows, name)
    assert len(chr_bytes) == 144, len(chr_bytes)
    (out / "dlg_chr.bin").write_bytes(bytes(chr_bytes))
    (out / "dlg_pal.bin").write_bytes(encode_pal(PAL, "panel palette"))
    print(f"  dlg_chr.bin: {len(chr_bytes)} B (9 tiles, all pixels opaque)")
    print("  dlg_pal.bin: 8 B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
