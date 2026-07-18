#!/usr/bin/env python3
"""gen_checker_map.py — generate the Mode 7 run-gate's test map (first-party).

Produces checker_map.bin: 32,768 bytes of interleaved Mode 7 VRAM data
(even bytes = the 128x128 tilemap, odd bytes = the 8bpp tile pixels), the
exact byte layout the VRAM port consumes with VMAIN=$80 word-increment
writes, and the layout engine/mode7_engine.asm's mode7_vram_upload DMAs
to VRAM word $0000 in one shot.

Map design (deliberately trivial — the run-gate proves the camera math,
not art): a checkerboard of 2x2-tile (16x16 px) squares over two solid
tiles. Tile 0 = every pixel palette index 1; tile 1 = every pixel palette
index 2. The test ROM sets CGRAM 1/2 to two distinguishable greens, so a
perspective screenshot shows squares that shrink toward the horizon and a
rotation is visible as the checker grid tilting.

Regenerate:  python3 tests/fixtures/mode7/gen_checker_map.py
(writes checker_map.bin next to this script; deterministic output)
"""
from pathlib import Path

MAP_W = 128                 # tilemap is 128x128 tiles
TILE_WORDS = 64             # 8x8 pixels, one byte per pixel (odd VRAM bytes)
CHECKER_SHIFT = 1           # 2x2-tile squares -> 16x16 px checkers


def build() -> bytes:
    # tilemap[i]: tile index for tile (row, col); checker over 2x2 blocks
    tilemap = bytearray(MAP_W * MAP_W)
    for row in range(MAP_W):
        for col in range(MAP_W):
            tilemap[row * MAP_W + col] = ((row >> CHECKER_SHIFT)
                                          ^ (col >> CHECKER_SHIFT)) & 1

    # chr: tile 0 = 64 bytes of $01, tile 1 = 64 bytes of $02; rest empty.
    chr_bytes = bytearray(MAP_W * MAP_W)
    chr_bytes[0:TILE_WORDS] = bytes([0x01]) * TILE_WORDS
    chr_bytes[TILE_WORDS:2 * TILE_WORDS] = bytes([0x02]) * TILE_WORDS

    out = bytearray(2 * MAP_W * MAP_W)
    out[0::2] = tilemap          # even byte of each VRAM word
    out[1::2] = chr_bytes        # odd byte of each VRAM word
    return bytes(out)


if __name__ == "__main__":
    data = build()
    assert len(data) == 0x8000, len(data)
    target = Path(__file__).parent / "checker_map.bin"
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes)")
