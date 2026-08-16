#!/usr/bin/env python3
"""gen_scroller_assets.py — deterministic art + palettes for the `scroller` rail.

Emits (byte-identical on re-run, pure integer math):

  scr_bg_chr.bin    2 x 4bpp BG tiles, 32 B each = 64 B
                    tile 0 EMPTY (all indices 0) · tile 1 SOLID index 1
  scr_bg_pal.bin    16 BGR555 words = 32 B  (BG palette group 0, CGRAM 0..15;
                    word 0 IS the backdrop slot — see scroller_bg/feature.toml)
  scr_obj_chr.bin   1 x 4bpp OBJ tile = 32 B   solid index 1
  scr_obj_pal.bin   16 BGR555 words = 32 B  (OBJ palette 0, CGRAM 128..143)

THE TILE ART. Only one tile carries ink. It is the 32-byte pattern eight
`$FF,$00` rows (bitplanes 0 and 1) followed by sixteen `$00` bytes (bitplanes
2 and 3) — i.e. a 4bpp tile whose every pixel is colour index 1. The
checkerboard's other cell is tile 0, all zeros: index 0, which a 4bpp BG
renders as the backdrop.

So the picture is *green squares on the backdrop*, and the two "colours" of the
checkerboard are one palette entry and one transparency. Tile 0 is written
EXPLICITLY rather than inherited from a cleared VRAM (rule 5 — every byte the
feature reads is a byte the feature wrote).

Colours:
  BG_GREEN = $03E0   checkerboard green
  OBJ_RED  = $001F   sprite red

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): `encode_4bpp` asserts every
pixel index is 0..15 and every palette entry is a 15-bit BGR value. An
out-of-range author error stops the generator naming the offending pixel; it
never quietly becomes a different colour.
"""
import sys
from pathlib import Path

BG_GREEN = 0x03E0        # BGR555 pure green — the checkerboard
OBJ_RED = 0x001F         # BGR555 pure red — the sprite

# --- BG palette group 0: CGRAM words 0..15 ----------------------------------
# Word 0 is the 4bpp transparent slot AND the hardware backdrop at once, which
# is why scroller_bg claims it rather than composing `backdrop`. It is BLACK,
# and it is written HERE rather than left to `sf_coldstart`'s CGRAM clear — the
# backdrop the picture shows is a byte this feature wrote.
BG_PAL = [0x0000, BG_GREEN] + [0x0000] * 14

# --- OBJ palette 0: CGRAM words 128..143 ------------------------------------
OBJ_PAL = [0x0000, OBJ_RED] + [0x0000] * 14

EMPTY_TILE = [[0] * 8 for _ in range(8)]
SOLID_TILE = [[1] * 8 for _ in range(8)]


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
    files = {
        "scr_bg_chr.bin": encode_4bpp(EMPTY_TILE, "bg tile 0 (empty)")
                          + encode_4bpp(SOLID_TILE, "bg tile 1 (solid)"),
        "scr_bg_pal.bin": encode_pal(BG_PAL, "bg palette"),
        "scr_obj_chr.bin": encode_4bpp(SOLID_TILE, "obj tile 0 (solid)"),
        "scr_obj_pal.bin": encode_pal(OBJ_PAL, "obj palette"),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
