#!/usr/bin/env python3
"""make_shadow.py — first-party ground-shadow OBJ for the mode7_flight rail.

Generates a dark ground-shadow sprite in two rendered sizes (the altitude
readout layered over the airship): a BIG 32x32 ellipse (airship LOW / close to
the ground) and a SMALL 16x16 ellipse (HIGH). The rail selects between them by
the OAM size bit + tile number as altitude changes; combined with a Y-offset
that drops toward the horizon as you climb, the shadow's rendered size/offset
tracks altitude. Generated art (not harvested).

The big 32x32 frame is emitted as 4 BLOCKS of 4 tiles (one tile-row each), the
small 16x16 as 2 blocks of 2 tiles — the same block layout as airship.inc, so
the rail uploads each block to VRAM tile-rows 16 apart (the hardware NxN OBJ
contract). 4bpp planar; OBJ palette 1, index 1 = shadow, rest transparent.

Output (committed): shadow.inc. Regenerate:
  python3 templates/mode7_flight/assets/make_shadow.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
PALETTE = {0: (0, 0, 0), 1: (16, 16, 40)}     # index 1 = dark shadow


def bgr555(rgb):
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def encode_tile_4bpp(grid, ox, oy):
    out = bytearray(32)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            v = grid[oy + y][ox + x]
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2 + 0] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2 + 0] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def ellipse(n):
    g = [[0] * n for _ in range(n)]
    cx = cy = (n - 1) / 2.0
    rx, ry = n * 0.46, n * 0.32                # flattened ground shadow
    for y in range(n):
        for x in range(n):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                g[y][x] = 1
    return g


def blocks(grid, ntiles):
    """Return ntiles blocks, each = one tile-row of ntiles contiguous tiles."""
    out = []
    for ty in range(ntiles):
        b = bytearray()
        for tx in range(ntiles):
            b += encode_tile_4bpp(grid, tx * 8, ty * 8)
        out.append(bytes(b))
    return out


def main():
    big = blocks(ellipse(32), 4)              # 4 blocks x 128 B
    small = blocks(ellipse(16), 2)            # 2 blocks x 64 B
    lines = [
        "; =============================================================================",
        "; shadow.inc — mode7_flight ground-shadow OBJ (GENERATED — do not edit)",
        "; =============================================================================",
        "; Regenerate: python3 templates/mode7_flight/assets/make_shadow.py",
        "; A dark flattened ellipse in two sizes. shadow_big = 4 blocks of 128 B (32x32,",
        "; airship LOW); shadow_small = 2 blocks of 64 B (16x16, HIGH). The rail uploads",
        "; each block to VRAM tile-rows 16 apart (hardware NxN OBJ contract) and flips",
        "; the OAM tile + size bit + Y-offset with altitude. OBJ palette 1, index 1.",
        "; =============================================================================",
        "",
        "shadow_big:",
    ]
    for blk in big:
        for off in range(0, len(blk), 16):
            lines.append("    .byte " + ", ".join(f"${b:02X}" for b in blk[off:off + 16]))
    lines += ["", "shadow_small:"]
    for blk in small:
        for off in range(0, len(blk), 16):
            lines.append("    .byte " + ", ".join(f"${b:02X}" for b in blk[off:off + 16]))
    lines += ["", "shadow_pal:"]
    for i in range(16):
        word = bgr555(PALETTE[i]) if i in PALETTE else 0
        lines.append(f"    .word ${word:04X}")
    lines.append("")
    (HERE / "shadow.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'shadow.inc'}  big=4x128B small=2x64B")


if __name__ == "__main__":
    main()
