#!/usr/bin/env python3
"""make_enemy.py — the m7_dungeon enemy OBJ, PROCEDURALLY generated (no pack).

Gallery-polish: the enemy is a classic SLIME — a warm orange blob that patrols the
rotating floor and reads as "enemy" at Mode 7 scale. Authored from scratch as a
16x16 index grid: a rounded teardrop dome, a glossy cream highlight, two dark eyes,
a wavy puddle base. stdlib-only; deterministic; no third-party source, so the
provenance regen is just this script.

Colour strategy (Wave-D discrimination, MEASURED on the emulator): the bright body
renders (231,107,74) — WARM + BRIGHT, so it clears the enemy band (r>=205, brighter
than any brick wall tone) and separates from the cool floor, the grey knight hero,
and the gold goal. A near-black outline RINGS the silhouette so the mid-orange
shade (which, being a mid warm, lands in the rendered-WALL band) stays INTERIOR,
never on the floor-ring the enemy-on-floor test samples around the sprite. The
glossy highlight is a warm cream (neither the enemy band nor the grey-hero band).

Emits enemy.inc in the shape main.asm consumes (ENEMY_TILE / enemy_chr /
ENEMY_CHR_BYTES / enemy_pal / ENEMY_PAL_COUNT) — the 18-tile OBJ upload where a
16x16 sprite is the PPU quad {0,1,16,17} and tiles 2..15 are zero-filled, so the
ROM's CHR/pal load path is unchanged. Uses its OWN OBJ palette (palette 1).

Regenerate (from the materialized kit root):
    python3 templates/m7_dungeon/assets/make_enemy.py
"""
from __future__ import annotations
from pathlib import Path

HERE = Path(__file__).resolve().parent

# OBJ palette 1 — warm slime. index: 0 transparent, 1 outline/eyes, 2 mid-orange
# shade (interior only — lands in the rendered-wall band), 3 bright body (the
# enemy-warm anchor), 4 glossy highlight.
PAL = [
    (0, 0, 0),          # 0 transparent
    (49, 24, 24),       # 1 dark outline / eyes / base rim
    (173, 74, 49),      # 2 mid-orange shade (kept interior)
    (231, 107, 74),     # 3 bright body — the enemy-warm band anchor
    (255, 222, 181),    # 4 glossy highlight (warm cream)
]


def _row(off: int, pat: str) -> str:
    """A 16-wide index row: `pat` (hex digits) placed at column `off`, 0-padded."""
    s = "0" * off + pat
    s = s + "0" * (16 - len(s))
    assert len(s) == 16, (off, pat, len(s))
    return s


# 16x16 slime: rounded dome, glossy highlight upper-left, two eyes, wavy puddle
# base. The dark outline (idx1) rings it so the wall-band mid-orange (idx2) stays
# off the outer edge the enemy-on-floor ring sampler reads.
ENEMY_ROWS = [
    _row(0,  ""),                 # 0
    _row(0,  ""),                 # 1
    _row(6,  "1331"),             # 2  dome crown
    _row(5,  "133331"),           # 3  dome top
    _row(4,  "13443331"),         # 4  dome + glossy highlight (4) upper-left
    _row(4,  "13343331"),         # 5  highlight rounds off
    _row(3,  "1333333321"),       # 6  dome widens
    _row(3,  "1331331331"),       # 7  two dark eyes
    _row(3,  "1331331331"),       # 8  eyes lower
    _row(2,  "133333333321"),     # 9  belly widening
    _row(2,  "133323333331"),     # 10 belly, faint interior shade
    _row(2,  "133333333331"),     # 11 belly widest
    _row(2,  "132233223231"),     # 12 lower belly (soft interior shade)
    _row(1,  "1333333333331"),    # 13 puddle base (widest)
    _row(1,  "1311331331131"),    # 14 wavy base (little foot bumps)
    _row(2,  "1100000011"),       # 15 base edge droplets
]


def bgr555(rgb) -> int:
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def encode_tile_4bpp(rows, ox: int, oy: int) -> bytes:
    """8x8 sub-grid at (ox,oy) of `rows` -> 32 bytes SNES 4bpp planar."""
    out = bytearray(32)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            v = int(rows[oy + y][ox + x], 16)
            assert 0 <= v <= 15, v
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2 + 0] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2 + 0] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def build_chr(rows) -> bytes:
    """18-tile OBJ blob: TL/TR/BL/BR at PPU-quad indices 0/1/16/17, rest zero (the
    16x16 upload main.asm's sf_load_obj_chr expects)."""
    tiles = [bytes(32)] * 18
    tiles[0] = encode_tile_4bpp(rows, 0, 0)    # TL
    tiles[1] = encode_tile_4bpp(rows, 8, 0)    # TR
    tiles[16] = encode_tile_4bpp(rows, 0, 8)   # BL
    tiles[17] = encode_tile_4bpp(rows, 8, 8)   # BR
    return b"".join(tiles)


def build_inc() -> str:
    assert len(ENEMY_ROWS) == 16 and all(len(r) == 16 for r in ENEMY_ROWS)
    blob = build_chr(ENEMY_ROWS)
    lines = [
        "; enemy.inc — GENERATED (make_enemy.py); DO NOT EDIT BY HAND.",
        "; Procedural SLIME: warm orange dome, glossy highlight, two eyes, puddle base.",
        "; Bright warm body (231,107,74) — the Wave-D enemy-warm band anchor.",
        "; original kit art (no pack source); CC0.",
        "ENEMY_TILE = 0",
        "enemy_chr:",
    ]
    for i in range(0, len(blob), 16):
        lines.append("    .byte " + ", ".join(f"${b:02X}" for b in blob[i:i + 16]))
    lines.append(f"ENEMY_CHR_BYTES = {len(blob)}")
    lines.append("")
    lines.append("enemy_pal:")
    for rgb in PAL:
        lines.append(f"    .word ${bgr555(rgb):04X}")
    for _ in range(16 - len(PAL)):
        lines.append("    .word $0000")
    lines.append("ENEMY_PAL_COUNT = 16")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    (HERE / "enemy.inc").write_text(build_inc())
    print("wrote enemy.inc (procedural slime)")


if __name__ == "__main__":
    main()
