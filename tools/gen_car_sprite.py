#!/usr/bin/env python3
"""gen_car_sprite.py — deterministic microzero player-car OBJ assets.

Emits (byte-identical on re-run, pure integer math):
  car_chr.bin   1024 B — 32 tiles x 32 B 4bpp: a 16-tile-wide OBJ grid row
                pair with the 16x16 car in tiles 0, 1, 16, 17 (the PPU
                reads 16x16 sprites at N, N+1, N+16, N+17), rest empty
  car_pal.bin   32 B — 16 BGR555 words, OBJ palette 0 (index 0 transparent)

The car (rear view, arcade-style): red body, dark-red shading, grey wings,
white cockpit, yellow engine glow.
"""
import sys
from pathlib import Path

# palette indices
T, RED, DRED, GREY, DGREY, WHITE, YELLOW = 0, 1, 2, 3, 4, 5, 6

PALETTE = [
    0x0000,                        # 0 transparent
    0x001F,                        # 1 red (BGR555: R=31)
    0x000C,                        # 2 dark red
    0x4210,                        # 3 grey (16,16,16)
    0x18C6,                        # 4 dark grey (6,6,6)
    0x7FFF,                        # 5 white
    0x03FF,                        # 6 yellow (R=31, G=31)
] + [0x0000] * 9

R = "."          # shorthand map for the pixel art
ART = [
    "................",
    "................",
    "......5555......",
    ".....555555.....",
    "....11555511....",
    "...1111111111...",
    "..111111111111..",
    ".33111111111133.",
    "3331111111111333",
    "3311111111111133",
    "3311122222111133",
    "3111226666221113",
    "1111266666621111",
    ".11226666662211.",
    "..44.666666.44..",
    "...4..4444..4...",
]
CHARMAP = {".": T, "1": RED, "2": DRED, "3": GREY, "4": DGREY,
           "5": WHITE, "6": YELLOW}


def encode_tile_4bpp(pix):
    """pix: 8x8 palette indices (0..15) -> 32 B SNES 4bpp planes."""
    out = bytearray()
    for row in range(8):
        b0 = b1 = 0
        for x in range(8):
            p = pix[row][x]
            assert 0 <= p <= 15
            b0 = (b0 << 1) | (p & 1)
            b1 = (b1 << 1) | ((p >> 1) & 1)
        out += bytes((b0, b1))
    for row in range(8):
        b2 = b3 = 0
        for x in range(8):
            p = pix[row][x]
            b2 = (b2 << 1) | ((p >> 2) & 1)
            b3 = (b3 << 1) | ((p >> 3) & 1)
        out += bytes((b2, b3))
    return bytes(out)


def car_pixels():
    assert len(ART) == 16 and all(len(r) == 16 for r in ART)
    return [[CHARMAP[c] for c in row] for row in ART]


def tiles():
    """The 32-tile grid: car quadrants at 0, 1, 16, 17."""
    px = car_pixels()
    grid = {}
    for qy in range(2):
        for qx in range(2):
            tile = [[px[qy * 8 + y][qx * 8 + x] for x in range(8)]
                    for y in range(8)]
            grid[qy * 16 + qx] = encode_tile_4bpp(tile)
    empty = encode_tile_4bpp([[T] * 8 for _ in range(8)])
    return b"".join(grid.get(i, empty) for i in range(32))


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gen_car_sprite.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    chr_blob = tiles()
    assert len(chr_blob) == 1024
    (outdir / "car_chr.bin").write_bytes(chr_blob)
    pal = b"".join(c.to_bytes(2, "little") for c in PALETTE)
    assert len(pal) == 32
    (outdir / "car_pal.bin").write_bytes(pal)
    print(f"car_chr.bin: {len(chr_blob)} B, car_pal.bin: {len(pal)} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
