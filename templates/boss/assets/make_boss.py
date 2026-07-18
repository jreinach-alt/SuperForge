#!/usr/bin/env python3
"""make_boss.py — first-party animated Mode 7 boss arena (boss template).

Authors a 1024x1024 boss-arena PNG on the 128x128-tile grid (every 8x8 tile is
one solid color, so the kit converter dedups the whole map to a couple dozen
unique tiles and colors — far under the Mode 7 limits of 256 tiles / 256
colors), then converts it through the kit's Mode 7 pipeline:

    toolchain/mode7_map_converter.py::convert_map_png   (tiles+map+palette)
    toolchain/mode7_assets.py::interleave_mode7_data    (native VRAM layout)

The boss — an ORIGINAL design, the "Cragmaw Sentinel": a hulking horned stone
golem head carved into the floor of a dark arena. Two curved stone horns sweep
up from a blocky brow; deep-set molten eyes glow under the brow ridge; a heavy
fanged jaw clamps the lower face; cracked-basalt cheeks frame a glowing rune
set into the forehead. It fills roughly the middle 48x48 tiles so it reads BIG
when the camera centers on the arena middle (the template spawns the camera at
posx=512, posy=512 looking down at the floor).

CGRAM index 0 is reserved as the dark arena backdrop (same discipline as the
racer's reserve_sky_backdrop): in Mode 7 index 0 is the transparent/backdrop
slot, revealed wherever BG1 is off — so we force it to the arena's dark stone
color and relocate whatever the converter happened to put there to an opaque
slot. Off-boss area is then a clean dark color.

Outputs (committed; regenerate only when changing the boss):
    boss.png           the authored source image (1024x1024)
    boss_map.bin       32,768 bytes interleaved Mode 7 VRAM blob — even bytes
                       = 128x128 tilemap, odd bytes = 8bpp tile pixels; the
                       exact layout sf_mode7_load_map boss_map, #$8000 DMAs to
                       VRAM word $0000
    boss_palette.inc   ca65 CGRAM data: boss_pal (BGR555 words) + BOSS_PAL_COUNT

Regenerate (from a kit root that has toolchain/ — the materialized kit tree;
in the parent monorepo run from the parent root, the import path is the same):
    PYTHONPATH=. python3 templates/boss/assets/make_boss.py
Deterministic output: same script, same bytes.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# --- arena geometry (tile units on the 128x128 grid) ---
CENTER = 63.5               # arena center (tiles)
BOSS_HALF = 24              # the boss reads across the middle ~48x48 tiles

# --- palette (RGB; the converter assigns CGRAM indices in scan order, then
#     reserve_arena_backdrop() forces index 0 to ARENA_DARK) ---
ARENA_DARK = (12, 10, 18)        # arena floor / backdrop (-> CGRAM index 0)
ARENA_TILE = (26, 22, 34)        # subtle floor checker (motion cue under Mode 7)
STONE_DK = (64, 58, 70)          # golem stone, shadow
STONE_MD = (104, 96, 110)        # golem stone, midtone
STONE_LT = (150, 140, 156)       # golem stone, lit edge
HORN_DK = (88, 70, 52)           # horn, shadow
HORN_LT = (170, 138, 96)         # horn, lit
EYE_GLOW = (255, 96, 32)         # molten eye core
EYE_DIM = (150, 40, 16)          # molten eye shadow
JAW_DK = (40, 36, 48)            # jaw cavity / mouth shadow
FANG = (224, 220, 208)           # fangs
RUNE = (96, 220, 255)            # forehead rune glow
RUNE_DIM = (40, 110, 140)        # rune halo


def _ellipse(tx, ty, cx, cy, rx, ry):
    """True if tile (tx,ty) is inside the axis-aligned ellipse centered
    (cx,cy) with radii (rx,ry)."""
    dx = (tx - cx) / rx
    dy = (ty - cy) / ry
    return dx * dx + dy * dy <= 1.0


def boss_color(tx: int, ty: int):
    """Solid color for a tile inside the boss bounding box, or None if this
    tile is arena floor (not part of the creature). All geometry is in tile
    units relative to the 128x128 grid; the head is built feature-by-feature
    from coarse ellipses + rectangles so every 8x8 tile is one flat color and
    the converter dedups aggressively.

    The head occupies roughly tx,ty in [40..88] (the middle ~48 tiles)."""
    cx, cy = CENTER, CENTER

    # ---- horns: two curved stone horns sweeping up-and-out from the brow ----
    # left horn (a chain of shrinking circles arcing up-left)
    for i, (hx, hy, hr) in enumerate((
            (50, 44, 4.5), (47, 39, 4.0), (45, 34, 3.4),
            (44, 29, 2.7), (44, 25, 2.0))):
        if _ellipse(tx, ty, hx, hy, hr, hr):
            return HORN_LT if (i + tx) & 1 else HORN_DK
    # right horn (mirror)
    for i, (hx, hy, hr) in enumerate((
            (77, 44, 4.5), (80, 39, 4.0), (82, 34, 3.4),
            (83, 29, 2.7), (83, 25, 2.0))):
        if _ellipse(tx, ty, hx, hy, hr, hr):
            return HORN_LT if (i + tx) & 1 else HORN_DK

    # ---- main skull mass: a broad rounded block, brow heavier than jaw ----
    head = _ellipse(tx, ty, cx, cy + 2, 21, 23)
    if not head:
        return None

    # forehead rune: a small diamond glyph set high-center
    if 60 <= tx <= 67 and 46 <= ty <= 52:
        if abs(tx - 63.5) + abs(ty - 49) <= 3.5:
            return RUNE
        if abs(tx - 63.5) + abs(ty - 49) <= 5.0:
            return RUNE_DIM

    # brow ridge: a heavy dark bar across the upper face above the eyes
    if 46 <= tx <= 81 and 53 <= ty <= 57:
        return STONE_DK

    # eyes: deep-set molten sockets under the brow
    if _ellipse(tx, ty, 54, 61, 5.0, 4.0):
        if _ellipse(tx, ty, 54, 61, 2.6, 2.2):
            return EYE_GLOW
        return EYE_DIM
    if _ellipse(tx, ty, 73, 61, 5.0, 4.0):
        if _ellipse(tx, ty, 73, 61, 2.6, 2.2):
            return EYE_GLOW
        return EYE_DIM

    # nose/muzzle bridge: a narrow lit ridge down the center
    if 62 <= tx <= 65 and 58 <= ty <= 70:
        return STONE_LT

    # jaw + mouth: a wide dark maw across the lower face with fangs
    if 50 <= tx <= 77 and 72 <= ty <= 80:
        # fangs: alternating upper/lower teeth at the mouth edges
        if ty in (72, 73) and (tx % 4) in (0, 1):
            return FANG
        if ty in (79, 80) and (tx % 4) in (2, 3):
            return FANG
        return JAW_DK

    # cheeks / cracked-basalt cheekbones: midtone with a lit checker so the
    # camera tilt shows surface relief
    if ty < cy:
        return STONE_MD if ((tx >> 1) ^ (ty >> 1)) & 1 else STONE_DK
    return STONE_LT if ((tx >> 1) ^ (ty >> 1)) & 1 else STONE_MD


def tile_color(tx: int, ty: int):
    """Solid color for tile (tx, ty) — boss in the middle, arena floor around."""
    if CENTER - BOSS_HALF - 2 <= tx <= CENTER + BOSS_HALF + 2 and \
       CENTER - BOSS_HALF - 2 <= ty <= CENTER + BOSS_HALF + 2:
        c = boss_color(tx, ty)
        if c is not None:
            return c
    # arena floor: a subtle two-tone checker for a Mode 7 motion cue
    return ARENA_TILE if ((tx >> 2) ^ (ty >> 2)) & 1 else ARENA_DARK


def build_png(path: Path) -> None:
    img = Image.new("RGB", (1024, 1024))
    px = img.load()
    for ty in range(128):
        for tx in range(128):
            c = tile_color(tx, ty)
            for py in range(8):
                for pxi in range(8):
                    px[tx * 8 + pxi, ty * 8 + py] = c
    img.save(path)
    print(f"wrote {path}")


def reserve_arena_backdrop(tile_data: bytes, palette: bytes):
    """Make CGRAM index 0 the ARENA_DARK backdrop (shown wherever BG1 is off).

    The converter assigned index 0 to the first pixel it scanned — tile (0,0),
    which is arena floor. In Mode 7 index 0 is the transparent/backdrop slot,
    so we want it to BE the arena's dark color. If the first-scanned color is
    already ARENA_DARK we are done; otherwise relocate that color to the first
    free opaque slot and write ARENA_DARK into index 0. Only index 0 changes
    meaning; every other index is untouched, so any hard-coded CGRAM reference
    in the template stays valid.

    Returns ``(tile_data, palette)`` with the swap applied.
    """
    import struct
    from toolchain.mode7_assets import rgb_to_bgr555

    arena_word = rgb_to_bgr555(*ARENA_DARK)
    idx0_word = struct.unpack_from("<H", palette, 0)[0]
    if idx0_word == arena_word:
        return tile_data, palette          # already correct, nothing to do

    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    free_slot = used                       # first unused opaque index
    if free_slot >= 256:
        raise ValueError("no free CGRAM slot to relocate the index-0 color")

    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:                         # index 0 was the first-scanned color
            td[i] = free_slot
    pal = bytearray(palette)
    struct.pack_into("<H", pal, free_slot * 2, idx0_word)   # old color -> opaque
    struct.pack_into("<H", pal, 0, arena_word)              # arena dark -> idx 0
    return bytes(td), bytes(pal)


def main() -> None:
    try:
        from toolchain.mode7_map_converter import convert_map_png
        from toolchain.mode7_assets import interleave_mode7_data
    except ImportError:
        sys.exit("toolchain/ not importable — run from the kit root with "
                 "PYTHONPATH=. (see the header)")

    png = HERE / "boss.png"
    build_png(png)

    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_arena_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "boss_map.bin").write_bytes(blob)
    print(f"wrote {HERE / 'boss_map.bin'} ({len(blob)} bytes)")

    # palette .inc — only the used head of the 256-color table
    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; =============================================================================",
        "; boss_palette.inc — boss-arena CGRAM data (GENERATED — do not edit)",
        "; =============================================================================",
        "; Regenerate: PYTHONPATH=. python3 templates/boss/assets/make_boss.py",
        "; (companion blob: boss_map.bin, the interleaved Mode 7 VRAM image)",
        "; CGRAM index 0 = ARENA_DARK backdrop (shown where BG1 is off).",
        "; =============================================================================",
        "",
        "boss_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; color {i}")
    lines += ["", f"BOSS_PAL_COUNT = {used}", ""]
    (HERE / "boss_palette.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'boss_palette.inc'} ({used} colors)")


if __name__ == "__main__":
    main()
