#!/usr/bin/env python3
"""make_hero.py — a 16x16 hero OBJ for the m7_dungeon rail.

The hero is an ARROW pointing UP (the tank-control "facing stays up" cue): the
rendered frame shows the hero pinned screen-centre, nose up, while the floor
rotates and scrolls under it. 4bpp planar CHR; 16x16 = 4 tiles at the hardware
16x16 OBJ layout (top row tiles 0/1, bottom row tiles 16/17).

Emits hero.inc (hero_chr + HERO_CHR_BYTES + hero_pal + HERO_PAL_COUNT + HERO_TILE).
Regenerate (from the materialized kit root):
    python3 templates/m7_dungeon/assets/make_hero.py
"""
from __future__ import annotations
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 16x16 arrow pointing up. '.' = transparent, '1' body, '2' outline, '3' nose.
HERO = [
    ".......33.......",
    "......3223......",
    ".....322223.....",
    "....32222223....",
    "...3222222223...",
    "..322222222223..",
    ".32221111122223.",
    "3222211111222223",
    "...2211111122...",
    "...2111111112...",
    "...2111111112...",
    "...2111111112...",
    "...2111111112...",
    "...2111111112...",
    "...2221111222...",
    "....22222222....",
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
    (90, 200, 255),     # 1 body (cyan)
    (20, 40, 90),       # 2 outline (dark blue)
    (255, 240, 120),    # 3 nose (yellow — points along facing)
]


def main():
    assert len(HERO) == 16 and all(len(r) == 16 for r in HERO)
    # 16x16 sprite VRAM layout: tile0=TL, tile1=TR, tile16=BL, tile17=BR.
    # sf_load_obj_chr uploads a contiguous blob; the 16x16 OBJ reads its lower
    # row 16 tiles later, so we upload 18 tiles (0..17) with tiles 2..15
    # zero-filled. That keeps tile17 (=BR) at the right VRAM offset.
    tiles = {
        0: encode_tile_4bpp(HERO, 0, 0),
        1: encode_tile_4bpp(HERO, 8, 0),
        16: encode_tile_4bpp(HERO, 0, 8),
        17: encode_tile_4bpp(HERO, 8, 8),
    }
    blob = bytearray()
    for t in range(18):
        blob.extend(tiles.get(t, bytes(32)))
    assert len(blob) == 18 * 32

    lines = [
        "; hero.inc — GENERATED (make_hero.py). 16x16 up-arrow hero OBJ.",
        "HERO_TILE = 0",
        "hero_chr:",
    ]
    for i in range(0, len(blob), 16):
        row = ", ".join(f"${b:02X}" for b in blob[i:i + 16])
        lines.append(f"    .byte {row}")
    lines.append(f"HERO_CHR_BYTES = {len(blob)}")
    lines.append("")
    lines.append("hero_pal:")
    for rgb in PAL:
        lines.append(f"    .word ${bgr555(rgb):04X}")
    # pad to 16 colours
    for _ in range(16 - len(PAL)):
        lines.append("    .word $0000")
    lines.append("HERO_PAL_COUNT = 16")
    lines.append("")
    (HERE / "hero.inc").write_text("\n".join(lines))
    print(f"wrote hero.inc ({len(blob)} CHR bytes)")


if __name__ == "__main__":
    main()
