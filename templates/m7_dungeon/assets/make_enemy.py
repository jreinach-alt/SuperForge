#!/usr/bin/env python3
"""make_enemy.py — a 16x16 STATIC enemy OBJ for the m7_dungeon rail (S4).

A distinct RED diamond/blob, deliberately NOT the cyan up-arrow hero, so a
rendered frame plainly shows the enemy sitting ON the rotating floor at its
world tile (the S4 projection test). 4bpp planar CHR; 16x16 = 4 tiles at the
hardware 16x16 OBJ layout (top row tiles 0/1, bottom row tiles 16/17).

The enemy uses its OWN OBJ palette slot (palette 1) so it can't be confused
with the hero's palette 0; the ROM uploads enemy_chr to a separate VRAM tile
region and enemy_pal to CGRAM OBJ palette 1.

Emits enemy.inc (enemy_chr + ENEMY_CHR_BYTES + enemy_pal + ENEMY_PAL_COUNT +
ENEMY_TILE). Regenerate (from the materialized kit root):
    python3 templates/m7_dungeon/assets/make_enemy.py
"""
from __future__ import annotations
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 16x16 red diamond blob. '.' = transparent, '1' body (red), '2' outline (dark),
# '3' highlight (bright). A diamond reads clearly distinct from the hero arrow.
ENEMY = [
    ".......22.......",
    "......2112......",
    ".....211112.....",
    "....21133112....",
    "...2113333112...",
    "..211333331112..",
    ".21133333331112.",
    "2113333333333112",
    "2113333333333112",
    ".21133333331112.",
    "..211333331112..",
    "...2113333112...",
    "....21133112....",
    ".....211112.....",
    "......2112......",
    ".......22.......",
]


def encode_tile_4bpp(rows, ox, oy):
    out = bytearray(32)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            ch = rows[oy + y][ox + x]
            v = 0 if ch == "." else int(ch, 16)
            assert 0 <= v <= 15
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2 + 0] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2 + 0] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def bgr555(rgb):
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


PAL = [
    (0, 0, 0),          # 0 transparent
    (200, 30, 30),      # 1 body (red)
    (70, 0, 0),         # 2 outline (dark red)
    (255, 140, 100),    # 3 highlight (bright orange)
]


def main():
    assert len(ENEMY) == 16 and all(len(r) == 16 for r in ENEMY)
    # 16x16 sprite VRAM layout: tile0=TL, tile1=TR, tile16=BL, tile17=BR.
    # Upload 18 tiles (0..17) with 2..15 zero-filled so tile17 (=BR) lands at
    # the right VRAM offset (same packing as make_hero.py).
    tiles = {
        0: encode_tile_4bpp(ENEMY, 0, 0),
        1: encode_tile_4bpp(ENEMY, 8, 0),
        16: encode_tile_4bpp(ENEMY, 0, 8),
        17: encode_tile_4bpp(ENEMY, 8, 8),
    }
    blob = bytearray()
    for t in range(18):
        blob.extend(tiles.get(t, bytes(32)))
    assert len(blob) == 18 * 32

    lines = [
        "; enemy.inc — GENERATED (make_enemy.py). 16x16 red-diamond enemy OBJ (S4).",
        "ENEMY_TILE = 0",
        "enemy_chr:",
    ]
    for i in range(0, len(blob), 16):
        row = ", ".join(f"${b:02X}" for b in blob[i:i + 16])
        lines.append(f"    .byte {row}")
    lines.append(f"ENEMY_CHR_BYTES = {len(blob)}")
    lines.append("")
    lines.append("enemy_pal:")
    for rgb in PAL:
        lines.append(f"    .word ${bgr555(rgb):04X}")
    for _ in range(16 - len(PAL)):
        lines.append("    .word $0000")
    lines.append("ENEMY_PAL_COUNT = 16")
    lines.append("")
    (HERE / "enemy.inc").write_text("\n".join(lines))
    print(f"wrote enemy.inc ({len(blob)} CHR bytes)")


if __name__ == "__main__":
    main()
