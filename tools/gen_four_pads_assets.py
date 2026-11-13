#!/usr/bin/env python3
"""gen_four_pads_assets.py — deterministic four_pads OBJ assets (docs/102).

Emits (byte-identical on re-run, pure integer math):
  fp_obj_chr.bin   96 B — THREE 8x8 4bpp tiles:
                   0 = the player token, 1 = a lamp RING (pad idle),
                   2 = a FILLED lamp (pad holding a button)
  fp_obj_pal.bin  128 B — four OBJ palettes of 16 BGR555 words, one per
                   player: index 1 = body colour, 2 = white highlight,
                   3 = dark outline

One token tile and one pair of lamp tiles serve all four players; who is who
is the OAM palette-select bits alone (palette n = player n+1). The pixel art
is written out below as strings and ENCODED here, so the tests can assert the
uploaded VRAM against bytes derived from the same picture.
"""
import sys
from pathlib import Path

T = 8
GLYPH = {".": 0, "X": 1, "o": 2, "#": 3}

# The player token: a round body with an outline and a highlight.
TOKEN = ["..####..",
         ".#XXXX#.",
         "#XoXXXX#",
         "#XXXXXX#",
         "#XXXXXX#",
         "#XXXXXX#",
         ".#XXXX#.",
         "..####.."]
# The lamp, idle: a ring with a dark centre showing through (transparent).
RING = ["..####..",
        ".#XXXX#.",
        "#XX..XX#",
        "#X....X#",
        "#X....X#",
        "#XX..XX#",
        ".#XXXX#.",
        "..####.."]
# The lamp, lit: filled, with a white core.
LIT = ["..####..",
       ".#XXXX#.",
       "#XXooXX#",
       "#XooooX#",
       "#XooooX#",
       "#XXooXX#",
       ".#XXXX#.",
       "..####.."]
TILES = [("token", TOKEN), ("ring", RING), ("lit", LIT)]

# Body colours, 15-bit BGR (%0bbbbbgggggrrrrr): P1 red, P2 blue, P3 green,
# P4 yellow — four hues a viewer can tell apart at a glance.
def bgr(r, g, b):
    return (b << 10) | (g << 5) | r

BODY = [bgr(31, 4, 4), bgr(6, 12, 31), bgr(4, 26, 6), bgr(31, 28, 2)]
WHITE = bgr(31, 31, 31)
OUTLINE = bgr(3, 3, 5)


def encode_4bpp(pixels, label: str) -> bytes:
    """64 palette indices (row-major) -> 32 B SNES 4bpp tile. No masking:
    an index outside 0..15 is a refusal (CLAUDE.md, silent quantisation)."""
    assert len(pixels) == T * T, f"{label}: {len(pixels)} pixels, want {T * T}"
    bad = sorted({p for p in pixels if not 0 <= p <= 15})
    assert not bad, f"{label}: palette indices {bad} do not fit 4bpp"
    lo, hi = bytearray(), bytearray()
    for y in range(T):
        row = pixels[y * T:(y + 1) * T]
        planes = [sum(((px >> bit) & 1) << (7 - x) for x, px in enumerate(row))
                  for bit in range(4)]
        lo += bytes((planes[0], planes[1]))
        hi += bytes((planes[2], planes[3]))
    return bytes(lo + hi)


def chr_bytes() -> bytes:
    out = b""
    for name, art in TILES:
        assert len(art) == T and all(len(r) == T for r in art), name
        out += encode_4bpp([GLYPH[c] for row in art for c in row], name)
    return out


def pal_bytes() -> bytes:
    out = b""
    for body in BODY:
        words = [0x0000] * 16
        words[1], words[2], words[3] = body, WHITE, OUTLINE
        out += b"".join(w.to_bytes(2, "little") for w in words)
    return out


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "fp_obj_chr.bin").write_bytes(chr_bytes())
    (out / "fp_obj_pal.bin").write_bytes(pal_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
