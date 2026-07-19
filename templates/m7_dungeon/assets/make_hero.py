#!/usr/bin/env python3
"""make_hero.py — the m7_dungeon hero OBJ, PROCEDURALLY generated (no pack).

Gallery-polish: the dungeon camera is a PLAN VIEW — looking straight DOWN at the
floor, ZERO tilt. The hero is an OBJ pinned at screen centre while the Mode 7 floor
rotates + scrolls underneath (TANK CONTROLS). So the hero must read as the
character's FOOTPRINT FROM DIRECTLY OVERHEAD — NOT a side profile, NOT an
above-behind three-quarter view. From straight above you see only: the CROWN of the
helmet at centre, the SHOULDERS as a ring around it, and the HANDS at the sides of
the shoulder line. No face, no chest, no back, no legs — a face/brow/eyes or a
visible backplate/greaves would betray a tilted camera, and there is none here.

The ONE deliberate break in the hero's radial symmetry is a forward cue at the TOP
edge: a bright helm PLUME tip pointing screen-up. Tank controls mean the hero
permanently faces screen-up while the WORLD rotates beneath, so a single top-edge
marker is the only orientation the sprite may show. (OBJ sprites do NOT rotate with
the Mode 7 floor, so a near-radially-symmetric hero is the only design that stays
honest as the floor spins under it — the plume is the sole intentional asymmetry.)

This authors that hero from scratch as a 16x16 index grid, built PROCEDURALLY from
concentric distance bands (guaranteeing the radial symmetry) plus the plume + hands.
stdlib-only; deterministic; no third-party source, so the provenance regen is just
this script.

The palette is deliberately BRIGHT + DESATURATED steel/bone (max-min small) so it
stays distinct from the cool flagstone floor, the warm brick walls, the warm slime
enemy, and the gold goal — the Wave-D colour-band discrimination the rail's tests
rely on (the hero reads grey/steel, never warm). Rendered tones (SNES 5-bit
expansion): mid steel (156,148,148) + bone (239,231,222) are the body; a near-black
cool outline + a mid-dark shade give the head-over-shoulders depth.

Emits hero.inc in the shape main.asm consumes (HERO_TILE / hero_chr / HERO_CHR_BYTES
/ hero_pal / HERO_PAL_COUNT) — the 18-tile OBJ upload where a 16x16 sprite is the
PPU quad {0,1,16,17} and tiles 2..15 are zero-filled, so the ROM's CHR/pal load
path is unchanged.

Regenerate (from the materialized kit root):
    python3 templates/m7_dungeon/assets/make_hero.py
"""
from __future__ import annotations

import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

# OBJ palette 0 — steel knight, bright + desaturated (stays out of every warm/cool
# terrain band). index: 0 transparent, 1 outline, 2 steel body, 3 bone highlight,
# 4 plate shade.
PAL = [
    (0, 0, 0),          # 0 transparent
    (49, 49, 66),       # 1 dark cool outline / silhouette / neck seam
    (156, 148, 148),    # 2 mid steel — helmet dome + shoulder ring
    (239, 231, 222),    # 3 bone highlight — top-lit crown apex, plume, hands
    (99, 99, 123),      # 4 mid-dark cool shade — the recessed neck groove ring
]

# --- plan-view geometry (a 16x16 grid, centre at (7.5,7.5)). The hero is built
#     from CONCENTRIC distance bands so it is radially symmetric BY CONSTRUCTION —
#     the only thing that breaks the symmetry is the forward plume, added after. ---
_N = 16
_CX = _CY = 7.5
# radial bands, apex outward (distance from centre, in grid px):
_R_CROWN = 2.35      # bright helmet APEX — the crown of the head, top-lit (bone)
_R_DOME = 3.3        # steel helmet DOME around the apex
_R_GROOVE = 4.2      # recessed neck GROOVE ring (shade) — head sits above shoulders
_R_RING = 6.2        # steel SHOULDER ring (pauldrons) — widest armour
_R_EDGE = 7.0        # dark silhouette OUTLINE (the footprint rim)


def _plan_hero_grid():
    """Build the 16x16 index grid: concentric plan-view knight + the forward plume
    + hands at the shoulder sides. Returns 16 strings of 16 hex digits."""
    g = [[0] * _N for _ in range(_N)]
    # concentric footprint: crown apex -> dome -> neck groove -> shoulders -> rim
    for y in range(_N):
        for x in range(_N):
            d = math.hypot(x - _CX, y - _CY)
            if d <= _R_CROWN:
                g[y][x] = 3          # bone crown apex (the very top of the head)
            elif d <= _R_DOME:
                g[y][x] = 2          # steel helmet dome
            elif d <= _R_GROOVE:
                g[y][x] = 4          # recessed neck groove (depth, head-over-body)
            elif d <= _R_RING:
                g[y][x] = 2          # steel shoulder ring
            elif d <= _R_EDGE:
                g[y][x] = 1          # dark silhouette outline

    # FORWARD CUE — a helm PLUME tip at the top edge, pointing screen-up. Bone
    # (bright) so it reads as the crest, tapering to a tip at row 0. This is the
    # ONLY intentional break in the radial symmetry (tank controls: faces up).
    plume = {0: (7, 8), 1: (6, 9), 2: (6, 9)}   # row -> inclusive x-span
    for ry, (x0, x1) in plume.items():
        for x in range(x0, x1 + 1):
            g[ry][x] = 3
    # frame the plume base so the crest reads as a ridge, not a smear. (Nothing
    # bright is placed low on the head — two symmetric bright pips would read as
    # EYES, i.e. a face, i.e. a tilt; the plan view has none.)
    g[2][5] = 1
    g[2][10] = 1

    # HANDS — gauntlets at the SIDES of the shoulder line (3 & 9 o'clock), bright
    # bone so they read as hands gripping at the widest point of the shoulders.
    for (hx0, hx1) in ((1, 2), (13, 14)):
        for x in range(hx0, hx1 + 1):
            for y in (7, 8):
                g[y][x] = 3

    return ["".join(format(v, "x") for v in row) for row in g]


# 16x16 top-down (plan-view) knight: crown apex at centre, shoulder ring around it,
# hands at the sides, a single forward plume at the top edge. No face/back/legs.
HERO_ROWS = _plan_hero_grid()


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
    assert len(HERO_ROWS) == 16 and all(len(r) == 16 for r in HERO_ROWS)
    blob = build_chr(HERO_ROWS)
    lines = [
        "; hero.inc — GENERATED (make_hero.py); DO NOT EDIT BY HAND.",
        "; Procedural PLAN-VIEW knight (straight-down): crown apex, shoulder ring,",
        "; hands at the sides, one forward plume. No face/back/legs (zero tilt).",
        "; Bright desaturated steel/bone — stays out of the warm/cool terrain bands.",
        "; original kit art (no pack source); CC0.",
        "HERO_TILE = 0",
        "hero_chr:",
    ]
    for i in range(0, len(blob), 16):
        lines.append("    .byte " + ", ".join(f"${b:02X}" for b in blob[i:i + 16]))
    lines.append(f"HERO_CHR_BYTES = {len(blob)}")
    lines.append("")
    lines.append("hero_pal:")
    for rgb in PAL:
        lines.append(f"    .word ${bgr555(rgb):04X}")
    for _ in range(16 - len(PAL)):
        lines.append("    .word $0000")
    lines.append("HERO_PAL_COUNT = 16")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    (HERE / "hero.inc").write_text(build_inc())
    print("wrote hero.inc (procedural plan-view knight)")


if __name__ == "__main__":
    main()
