#!/usr/bin/env python3
"""make_obstacles.py — first-party rail-shooter OBJ art (obstacle/reticle/bullet).

Trademark-free pixel art for the railshooter template's gameplay sprites, all
encoded to SNES 4bpp planar CHR on the hardware's 16-tile VRAM rows (an NxN
sprite reads each lower tile row at +16 tile numbers). Sized for OBSEL size
pair 3 (16x16 small / 32x32 large), the same OBSEL the ship uses.

The SNES has only TWO OAM sizes live at once. To fake FOUR apparent obstacle
sizes (a near object grows tiny->small->medium->large as it approaches) we
pre-draw FOUR frames at different ART densities across the two OAM boxes:

    obs_t3  $00  16x16 box, tiny art centred (~half-size)  -> tier 3 (farthest)
    obs_t2  $02  16x16 box, full 16x16 hazard              -> tier 2
    obs_t1  $04  32x32 box, medium art centred (~16x16)    -> tier 1
    obs_t0  $08  32x32 box, full 32x32 hazard              -> tier 0 (nearest)

so the visible step is: tier 3 (small box, small art) -> tier 2 (small box, full
art) -> tier 1 (large box, medium art) -> tier 0 (large box, full art). main.asm
maps each PROJ_TIER to one (frame, OAM size bit, screen-centre offset).

Plus the gameplay sprites:
    obs_reticle  $0C  lock-on crosshair, 16x16            — the aim point (M4)
    obs_bullet   $0E  projectile, 8x8 in a 16x16 slot     — fired shot   (M4)

The 16x16 frames must each start on a 2-tile boundary so the PPU reads their
lower row at +16; the 32x32 frames occupy a 4x4 subtile block (their VRAM rows
at base + {0..3, 16..19, 32..35, 48..51}). All frames are laid out on a 96-tile
(6-row) blob with no overlap.

Output (committed): obstacles.inc — obstacles_chr blob, obstacles_pal (OBJ
palette, distinct from the ship's), and the frame/tile constants.

Regenerate:  python3 templates/railshooter/assets/make_obstacles.py
(stdlib only; deterministic output)
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

# palette index -> RGB (index 0 = transparent, never rendered)
PALETTE = {
    0: (0, 0, 0),
    1: (20, 16, 8),         # outline / shadow
    2: (240, 176, 32),      # hazard amber
    3: (255, 232, 120),     # hazard highlight
    4: (208, 64, 40),       # hazard warning red (chevrons)
    5: (255, 255, 255),     # reticle white
    6: (96, 255, 160),      # bullet green
    7: (200, 255, 220),     # bullet core
}

# 16x16 hazard block: an amber cube with red warning chevrons + an outline.
OBSTACLE16 = [
    "................",
    "..111111111111..",
    ".11222222222211.",
    ".12333333333321.",
    ".12344444444321.",
    ".12342222224321.",
    ".12342444424321.",
    ".12342444424321.",
    ".12342444424321.",
    ".12342444424321.",
    ".12342222224321.",
    ".12344444444321.",
    ".12333333333321.",
    ".11222222222211.",
    "..111111111111..",
    "................",
]

# 8x8 hazard core (the same motif, distilled for the tiniest tier).
OBSTACLE8 = [
    "..1111..",
    ".122221.",
    ".123321.",
    ".124421.",
    ".124421.",
    ".123321.",
    ".122221.",
    "..1111..",
]

# 16x16 lock-on reticle: a hollow crosshair (sparse, so it reads over the floor)
RETICLE16 = [
    "......5555......",
    "....55....55....",
    "...5........5...",
    "..5..........5..",
    ".5............5.",
    ".5............5.",
    "5......55......5",
    "5.....5..5.....5",
    "5.....5..5.....5",
    "5......55......5",
    ".5............5.",
    ".5............5.",
    "..5..........5..",
    "...5........5...",
    "....55....55....",
    "......5555......",
]

# 8x8 projectile (green tracer)
BULLET8 = [
    "...66...",
    "..6776..",
    ".677776.",
    ".677776.",
    ".677776.",
    ".677776.",
    "..6776..",
    "...66...",
]


def upscale2x(rows: list[str]) -> list[str]:
    out = []
    for r in rows:
        wide = "".join(ch * 2 for ch in r)
        out += [wide, wide]
    return out


def pad_center(art: list[str], size: int) -> list[str]:
    """Centre `art` (square) in a transparent `size`x`size` char grid."""
    n = len(art)
    assert all(len(r) == n for r in art), "art must be square"
    assert n <= size and (size - n) % 2 == 0
    pad = (size - n) // 2
    blank = "." * size
    out = [blank] * pad
    for r in art:
        out.append("." * pad + r + "." * pad)
    out += [blank] * pad
    assert len(out) == size and all(len(r) == size for r in out)
    return out


def encode_tile_4bpp(rows: list[str], ox: int, oy: int) -> bytes:
    """One 8x8 tile at (ox, oy) of a char grid -> 32 bytes SNES 4bpp planar."""
    out = bytearray(32)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            ch = rows[oy + y][ox + x]
            v = 0 if ch == "." else int(ch)
            assert 0 <= v <= 15
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2 + 0] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2 + 0] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def bgr555(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def place(tiles: list[bytes], base: int, art: list[str], w_subtiles: int, h_subtiles: int) -> None:
    """Place a w x h subtile sprite at OBJ tile `base`, on 16-tile VRAM rows."""
    for ty in range(h_subtiles):
        for tx in range(w_subtiles):
            tiles[base + ty * 16 + tx] = encode_tile_4bpp(art, tx * 8, ty * 8)


def main() -> None:
    assert len(OBSTACLE16) == 16 and all(len(r) == 16 for r in OBSTACLE16)
    assert len(OBSTACLE8) == 8 and all(len(r) == 8 for r in OBSTACLE8)
    assert len(RETICLE16) == 16 and all(len(r) == 16 for r in RETICLE16)
    assert len(BULLET8) == 8 and all(len(r) == 8 for r in BULLET8)

    obstacle32_full = upscale2x(OBSTACLE16)             # full 32x32 hazard
    obstacle32_med = pad_center(OBSTACLE16, 32)         # 16x16 hazard centred in 32x32
    obstacle16_tiny = pad_center(OBSTACLE8, 16)         # 8x8 core centred in 16x16

    tiles = [bytes(32)] * 96             # 6 VRAM rows x 16 tiles
    # 4 size tiers (two 32x32 boxes, two 16x16 boxes), no overlap:
    place(tiles, 0x00, obstacle16_tiny, 2, 2)   # tier3 16x16 box, tiny art (cols 0-1)
    place(tiles, 0x02, OBSTACLE16, 2, 2)        # tier2 16x16 box, full art (cols 2-3)
    place(tiles, 0x04, obstacle32_med, 4, 4)    # tier1 32x32 box, medium art (cols 4-7)
    place(tiles, 0x08, obstacle32_full, 4, 4)   # tier0 32x32 box, full art (cols 8-11)
    # gameplay sprites:
    place(tiles, 0x0C, RETICLE16, 2, 2)         # reticle 16x16 (cols 12-13)
    place(tiles, 0x0E, BULLET8, 1, 1)           # bullet 8x8 in 16x16 slot (col 14)
    blob = b"".join(tiles)
    assert len(blob) == 96 * 32

    lines = [
        "; =============================================================================",
        "; obstacles.inc — railshooter obstacle/reticle/bullet OBJ CHR (GENERATED)",
        "; =============================================================================",
        "; Regenerate: python3 templates/railshooter/assets/make_obstacles.py",
        "; 6 VRAM tile rows. OBSEL size pair 3 (16x16 small / 32x32 large).",
        "; FOUR pre-drawn size tiers across the two OAM boxes (no HW sprite scaling):",
        ";   tier3 = 16x16 box + tiny art,  tier2 = 16x16 box + full art,",
        ";   tier1 = 32x32 box + medium art, tier0 = 32x32 box + full art.",
        "; LOAD CONTRACT: upload obstacles_chr at a 16-aligned OBJ tile index; a",
        "; frame's OAM tile = base + obs_<frame> (lower rows read at +16).",
        "; =============================================================================",
        "",
        "obs_t3        = $00      ; tier 3: 16x16 box, tiny art  (OAM size = small)",
        "obs_t2        = $02      ; tier 2: 16x16 box, full art  (OAM size = small)",
        "obs_t1        = $04      ; tier 1: 32x32 box, med art   (OAM size = large)",
        "obs_t0        = $08      ; tier 0: 32x32 box, full art  (OAM size = large)",
        "obs_reticle   = $0C      ; lock-on crosshair 16x16",
        "obs_bullet    = $0E      ; projectile 8x8 (drawn in a 16x16 small slot)",
        f"obstacles_chr_bytes = {len(blob)}",
        "",
        "obstacles_chr:",
    ]
    for off in range(0, len(blob), 16):
        chunk = ", ".join(f"${b:02X}" for b in blob[off:off + 16])
        lines.append(f"    .byte {chunk}")
    lines += ["", "obstacles_pal:"]
    for i in range(16):
        word = bgr555(PALETTE[i]) if i in PALETTE else 0
        lines.append(f"    .word ${word:04X}    ; color {i}")
    lines.append("")
    (HERE / "obstacles.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'obstacles.inc'} ({len(blob)} bytes)")


if __name__ == "__main__":
    main()
