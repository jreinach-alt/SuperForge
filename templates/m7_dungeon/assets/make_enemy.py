#!/usr/bin/env python3
"""make_enemy.py — the m7_dungeon enemy OBJ, PROCEDURALLY generated (no pack).

Gallery-polish: the dungeon camera is a PLAN VIEW — straight DOWN, ZERO tilt — so
the enemy SLIME must read as a blob seen FROM DIRECTLY OVERHEAD. From straight
above a slime is a CONCENTRIC BLOB: a dark outline rim, a warm body, and an inner
glossy highlight crescent. That is ALL you can see looking down at a puddle of goo
— NO eyes (eyes are a face, a face means a tilted camera) and NO "front"/puddle
base (a directional base means the camera is angled). The slime is near-radially
symmetric on purpose: OBJ sprites do NOT rotate with the Mode 7 floor, so a blob
with any strong orientation would visibly contradict the world the instant the
floor spins under it. The only break is the glossy highlight — a specular from the
overhead light, i.e. a wobble of life, not a facing.

Authored from scratch as a 16x16 index grid, built PROCEDURALLY from concentric
distance bands (guaranteeing the radial symmetry) plus the glossy crescent.
stdlib-only; deterministic; no third-party source, so the provenance regen is just
this script.

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

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

# OBJ palette 1 — warm slime. index: 0 transparent, 1 outline/rim, 2 mid-orange
# shade (interior only — lands in the rendered-wall band), 3 bright body (the
# enemy-warm anchor), 4 glossy highlight.
PAL = [
    (0, 0, 0),          # 0 transparent
    (49, 24, 24),       # 1 dark outline / rim
    (173, 74, 49),      # 2 mid-orange shade (kept INTERIOR: radial rim darkening)
    (231, 107, 74),     # 3 bright body — the enemy-warm band anchor
    (255, 222, 181),    # 4 glossy highlight (warm cream)
]

# --- plan-view geometry (a 16x16 grid, centre at (7.5,7.5)). The slime is built
#     from CONCENTRIC distance bands so it is radially symmetric BY CONSTRUCTION.
#     The mid-orange shade (index 2, a rendered-WALL-band tone) is kept strictly
#     INTERIOR (radius < the ~7px ring the enemy-on-floor test samples); the
#     OUTERMOST ring is the neutral dark outline. ---
_N = 16
_CX = _CY = 7.5
_R_BODY = 5.5        # bright warm body (index 3) — dominates the blob
_R_SHADE = 6.1       # radial rim darkening (index 2, interior only)
_R_EDGE = 6.9        # dark outline rim (index 1) — the outermost ring


def _plan_slime_grid():
    """Build the 16x16 index grid: a concentric warm blob (outline rim -> body ->
    interior shade) + one glossy highlight crescent. Returns 16 hex strings."""
    g = [[0] * _N for _ in range(_N)]
    # concentric blob: bright body -> shaded rim -> dark outline
    for y in range(_N):
        for x in range(_N):
            d = math.hypot(x - _CX, y - _CY)
            if d <= _R_BODY:
                g[y][x] = 3          # bright warm body (enemy anchor)
            elif d <= _R_SHADE:
                g[y][x] = 2          # interior shade (radial rim, stays off the
                                     # floor-ring sampler — never the outer edge)
            elif d <= _R_EDGE:
                g[y][x] = 1          # dark outline rim (the outermost pixels)

    # GLOSSY HIGHLIGHT — one small specular cap in the upper body (the overhead
    # light on a wet dome), offset up. A SINGLE connected shape (never two dots,
    # which would read as eyes) — the slime's only break in radial symmetry (life).
    for (ry, x0, x1) in ((3, 7, 8), (4, 6, 9), (5, 7, 8)):
        for x in range(x0, x1 + 1):
            if g[ry][x] == 3:        # only paint over body (keep it inner/glossy)
                g[ry][x] = 4

    return ["".join(format(v, "x") for v in row) for row in g]


# 16x16 plan-view slime: concentric warm blob + a glossy highlight crescent. No
# eyes, no puddle "front" — a blob seen straight down.
ENEMY_ROWS = _plan_slime_grid()


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
        "; Procedural PLAN-VIEW slime (straight-down): concentric warm blob —",
        "; outline rim, bright body, glossy highlight crescent. No eyes/front (zero tilt).",
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
    print("wrote enemy.inc (procedural plan-view slime)")


if __name__ == "__main__":
    main()
