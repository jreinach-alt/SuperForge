#!/usr/bin/env python3
"""gen_map.py — first-party Mode-7 checker world for the C-horiz matrix-band rail.

Emits the interleaved Mode-7 VRAM blob (even bytes = 128x128 tilemap, odd bytes =
8bpp tile pixels) for ONE flat top-down world shared by both camera bands. The
world is a 1x1-tile checkerboard of two solid tiles (tile0 = palette idx 1,
tile1 = palette idx 2) -> an 8x8-px checker period in WORLD space.

Under a flat top-down Mode-7 matrix at scale M7A=M7D=$0100 (1:1) one screen px is
one world px, so the on-screen checker period is 8 px; at scale $0040 (0.25) each
screen px steps 0.25 world px, so the period is 4x = 32 px. That 8-vs-32 period
difference is the measurable "two distinct cameras of ONE world" signal the test
reads from the framebuffer.

First-party, deterministic, mechanism-only (no game references).
"""
from pathlib import Path

MAP_W = 128
TILE_WORDS = 64


def build() -> bytes:
    tilemap = bytearray(MAP_W * MAP_W)
    for row in range(MAP_W):
        for col in range(MAP_W):
            # 1x1-tile checker -> 8x8 px world checker.
            tilemap[row * MAP_W + col] = (row ^ col) & 1
    chr_bytes = bytearray(MAP_W * MAP_W)
    # Tile 0 = solid palette index 1; tile 1 = solid palette index 2 (8bpp).
    chr_bytes[0:TILE_WORDS] = bytes([0x01]) * TILE_WORDS
    chr_bytes[TILE_WORDS:2 * TILE_WORDS] = bytes([0x02]) * TILE_WORDS
    out = bytearray(2 * MAP_W * MAP_W)
    out[0::2] = tilemap
    out[1::2] = chr_bytes
    return bytes(out)


if __name__ == "__main__":
    data = build()
    assert len(data) == 0x8000, len(data)
    target = Path(__file__).parent / "checker_map.bin"
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")
