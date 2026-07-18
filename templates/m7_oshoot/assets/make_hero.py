#!/usr/bin/env python3
"""make_hero.py — a 16x16 hero OBJ for the m7_dungeon rail.

The hero is a ROUND cyan body with a small directional NOSE at the TOP (the
"facing stays up" cue): the rendered frame shows the hero pinned screen-centre,
nose up, while the floor rotates and scrolls under it. 4bpp planar CHR; 16x16 =
4 tiles at the hardware 16x16 OBJ layout (top row tiles 0/1, bottom row 16/17).

ART NOTE — why ROUND body: OBJ sprites are NOT rotated by the Mode 7 matrix, so
an oriented body would read as "should spin with the floor but doesn't." A
radially-symmetric circle is rotation-invariant. The hero is always upright, so
a small NOSE at the top (yellow, palette index 3) keeps the aim/facing legible
without making the whole body directional.

Emits hero.inc (hero_chr + HERO_CHR_BYTES + hero_pal + HERO_PAL_COUNT + HERO_TILE).
Regenerate (from the materialized kit root):
    python3 templates/m7_dungeon/assets/make_hero.py
"""
from __future__ import annotations
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 16x16 round cyan body with a directional nose at the TOP. Generated
# procedurally (distance-from-centre test, NOT hand-drawn) so the body is a true
# radially-symmetric circle — rotation-invariant on the spinning floor — while a
# small NOSE preserves the "up" aim cue. Palette indices UNCHANGED so the test
# colours match: '.' transparent, '1' body (cyan), '2' outline (dark blue),
# '3' nose (yellow, points along facing).
def _make_round_hero():
    """Filled cyan circle (centre (7.5,7.5), radius ~7) with a 1px dark outline
    ring, plus a small yellow nose poking up from the top edge."""
    W = H = 16
    cx = cy = 7.5
    R_OUT = 7.0
    RING = 1.0
    grid = []
    for y in range(H):
        row = []
        for x in range(W):
            dx, dy = x - cx, y - cy
            d = (dx * dx + dy * dy) ** 0.5
            if d > R_OUT:
                row.append(".")        # outside the disc -> transparent
            elif d > R_OUT - RING:
                row.append("2")        # 1px dark-blue outline ring
            else:
                row.append("1")        # cyan body fill
        grid.append(list(row))

    # Directional NOSE: a short yellow stub at the top centre (rows 0..2, the
    # two centre columns), overlaying the top of the body so "up" stays legible.
    for ny in range(0, 3):
        for nx in (7, 8):
            grid[ny][nx] = "3"
    return ["".join(r) for r in grid]


HERO = _make_round_hero()


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
        "; hero.inc — GENERATED (make_hero.py). 16x16 round hero OBJ (up-nose).",
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
