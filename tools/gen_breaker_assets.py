#!/usr/bin/env python3
"""gen_breaker_assets.py — deterministic art + palettes for the `breaker` rail.

Emits (byte-identical on re-run, pure integer math):

  brk_bg_chr.bin    6 x 4bpp BG tiles, 32 B each = 192 B
                    tile 0 empty · 1 wall · 2..5 the four brick colours
  brk_bg_pal.bin    16 BGR555 words = 32 B  (BG palette 2, CGRAM 32..47)
  brk_sky_chr.bin   1 x 4bpp tile, solid colour 1 = 32 B   (the BG2 wash bed)
  brk_sky_pal.bin   16 BGR555 words = 32 B  (BG palette 3, CGRAM 48..63)
  brk_obj_chr.bin   2 x 4bpp OBJ tiles = 64 B   tile 0 paddle · tile 1 ball
  brk_obj_pal.bin   16 BGR555 words = 32 B  (OBJ palette 0, CGRAM 128..143)
  brk_grad.bin      3 x 224 COLDATA bytes = 672 B  (rgb_gradient's grad_tabs)

The brick faces are 7x7 with the 8th column and 8th row left TRANSPARENT --
that gap is the mortar line, and it is why a wall of bricks reads as a wall of
bricks rather than a flat colour field. Each face is bevelled: top row + left
column take the row colour's highlight index, bottom row + right column its
shadow index, the interior its base. The bevel is GENERATED from that rule
rather than written out as byte tables, so the source states it once instead
of carrying 128 bytes nobody can check by eye.

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): `encode_4bpp` asserts every
pixel index is 0..15 and every palette entry is a 15-bit BGR value. An
out-of-range author error stops the generator naming the offending pixel; it
never quietly becomes a different colour.
"""
import sys
from pathlib import Path

# --- BG palette 2: the arena ------------------------------------------------
# index 0 is the 4bpp transparent slot and is never rendered; it is written
# anyway so the whole claim is defined at enter (CLAUDE.md rule 5).
BG_PAL = [
    0x0000,   # 0  transparent
    0x39CE,   # 1  wall grey
    0x001F,   # 2  brick red      base
    0x01BF,   # 3  brick orange   base
    0x03FF,   # 4  brick yellow   base
    0x03E0,   # 5  brick green    base
    0x295F,   # 6  red    highlight
    0x000D,   # 7  red    shadow
    0x2AFF,   # 8  orange highlight
    0x00AD,   # 9  orange shadow
    0x2BFF,   # 10 yellow highlight
    0x01AD,   # 11 yellow shadow
    0x2BEA,   # 12 green  highlight
    0x01A0,   # 13 green  shadow
    0x0000,   # 14 unused
    0x0000,   # 15 unused
]

# (base, highlight, shadow) per brick row colour — tiles 2..5 in order.
BRICKS = [(2, 6, 7), (3, 8, 9), (4, 10, 11), (5, 12, 13)]

# --- BG palette 3: the night bed BG2 fills the screen with -------------------
# Colour math ADDs rgb_gradient's per-scanline COLDATA ramp on top of this, so
# it is deliberately almost black: the ramp is the picture, this is the paper.
SKY_PAL = [0x0000, 0x1020] + [0x0000] * 14   # B=4 G=1 R=0: a cold dark blue

# --- OBJ palette 0: paddle + ball -------------------------------------------
# ONE palette for both sprites: the paddle tile draws in index 1, the ball in
# index 2. Two OBJ palettes would cost a second CGRAM claim to say the same
# thing: the two sprites differ by index, not by palette, so one CGRAM claim
# covers both and the register has one fewer thing to prove.
OBJ_PAL = [
    0x0000,   # 0  transparent
    0x7FE0,   # 1  paddle cyan
    0x7FFF,   # 2  ball white
] + [0x0000] * 13

# --- the backdrop ramp (rgb_gradient grad_tabs layout) ----------------------
TOTAL_LINES = 224                       # rgb_gradient.asm GRAD_LINES
SKY_TOP = (4, 6, 14)                    # dark slate-blue at the top of the field
SKY_BOT = (1, 1, 6)                     # near-black deep blue down in the pit
PLANE = (0x20, 0x40, 0x80)              # COLDATA plane-select bits (R, G, B)


def encode_4bpp(px: list[list[int]], label: str) -> bytes:
    """One 8x8 index grid -> 32 B SNES 4bpp planar.

    Layout: rows 0..7 of bitplanes 0/1 interleaved (2 B per row), then rows
    0..7 of bitplanes 2/3. Raises on any index outside 0..15 -- never masks.
    """
    assert len(px) == 8, f"{label}: need 8 rows, got {len(px)}"
    for y, row in enumerate(px):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} pixels, need 8"
        for x, v in enumerate(row):
            if not 0 <= v <= 15:
                raise ValueError(
                    f"{label}: pixel ({x},{y}) index {v} is outside 0..15 -- "
                    "a 4bpp tile cannot express it. Fix the art, do not mask."
                )
    out = bytearray()
    for planes in ((0, 1), (2, 3)):
        for y in range(8):
            for bit in planes:
                b = 0
                for x in range(8):
                    if px[y][x] >> bit & 1:
                        b |= 0x80 >> x
                out.append(b)
    return bytes(out)


def pal_bytes(words: list[int], label: str) -> bytes:
    assert len(words) == 16, f"{label}: need 16 words, got {len(words)}"
    out = bytearray()
    for i, w in enumerate(words):
        if not 0 <= w <= 0x7FFF:
            raise ValueError(f"{label}: entry {i} = ${w:04X} is not 15-bit BGR555")
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


def brick_tile(base: int, hl: int, sh: int) -> list[list[int]]:
    """7x7 bevelled face + a transparent mortar column and row."""
    px = [[0] * 8 for _ in range(8)]
    for y in range(7):
        for x in range(7):
            if y == 0 or x == 0:
                px[y][x] = hl
            elif y == 6 or x == 6:
                px[y][x] = sh
            else:
                px[y][x] = base
    return px


def bg_chr() -> bytes:
    tiles = [[[0] * 8 for _ in range(8)]]                    # 0: empty
    tiles.append([[1] * 8 for _ in range(8)])                # 1: wall, solid
    for base, hl, sh in BRICKS:                              # 2..5: bricks
        tiles.append(brick_tile(base, hl, sh))
    return b"".join(encode_4bpp(t, f"bg tile {i}") for i, t in enumerate(tiles))


def obj_chr() -> bytes:
    # tile 0 — the paddle segment: a 6 px bar, one pixel of air top and bottom
    paddle = [[0] * 8 if y in (0, 7) else [1] * 8 for y in range(8)]
    # tile 1 — the ball: an 8x8 disc, written as one row mask per row
    # ($3C/$7E/$FF...) so the shape is readable as a shape.
    disc = (0x3C, 0x7E, 0xFF, 0xFF, 0xFF, 0xFF, 0x7E, 0x3C)
    ball = [[2 if m >> (7 - x) & 1 else 0 for x in range(8)] for m in disc]
    return encode_4bpp(paddle, "obj paddle") + encode_4bpp(ball, "obj ball")


def _lerp(a: int, b: int, i: int, n: int) -> int:
    return a + (b - a) * i // max(1, n - 1)


def grad_tabs() -> bytes:
    """One COLDATA byte per scanline per plane: R table, then G, then B."""
    out = bytearray()
    for p in range(3):
        for line in range(TOTAL_LINES):
            v = _lerp(SKY_TOP[p], SKY_BOT[p], line, TOTAL_LINES)
            assert 0 <= v <= 31, f"plane {p} line {line}: intensity {v} > 31"
            out.append(PLANE[p] | v)
    return bytes(out)


def main(outdir: str) -> None:
    d = Path(outdir)
    d.mkdir(parents=True, exist_ok=True)
    art = {
        "brk_bg_chr.bin": bg_chr(),
        "brk_bg_pal.bin": pal_bytes(BG_PAL, "bg pal"),
        "brk_sky_chr.bin": encode_4bpp([[1] * 8 for _ in range(8)], "sky tile"),
        "brk_sky_pal.bin": pal_bytes(SKY_PAL, "sky pal"),
        "brk_obj_chr.bin": obj_chr(),
        "brk_obj_pal.bin": pal_bytes(OBJ_PAL, "obj pal"),
        "brk_grad.bin": grad_tabs(),
    }
    for name, blob in art.items():
        (d / name).write_bytes(blob)
        print(f"{name}: {len(blob)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
