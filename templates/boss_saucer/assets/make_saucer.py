#!/usr/bin/env python3
"""make_saucer.py — first-party scaling Mode 7 boss arena (boss_saucer template).

Authors a 1024x1024 boss PNG on the 128x128-tile grid (every 8x8 tile is one
solid color, so the kit converter dedups the whole map to a few dozen unique
tiles and colors — far under the Mode 7 limits of 256 tiles / 256 colors),
then converts it through the kit's Mode 7 pipeline:

    toolchain/mode7_map_converter.py::convert_map_png   (tiles+map+palette)
    toolchain/mode7_assets.py::interleave_mode7_data    (native VRAM layout)

The boss — an ORIGINAL design, the "Disc Marauder": a classic domed flying
saucer hovering against a dark night sky. A wide metallic hull disc (lit upper
rim, shadowed lower rim) carries a glowing blue cockpit dome on top; a ring of
amber running lights studs the hull's equator; an underside emitter glows where
its descending beam originates. It fills roughly the middle ~40x40 tiles so it
reads BIG when the camera centers on the arena middle — and, crucially for this
template's signature, holds a STRONG silhouette + high-contrast hull / dome /
lights / emitter so it stays legible whether Mode 7 scales it tiny (far/high)
or zooms it to fill the screen on a lunge.

CGRAM index 0 is reserved as the dark night-sky backdrop (same discipline as
the boss template's reserve_arena_backdrop): in Mode 7 index 0 is the
transparent/backdrop slot, revealed wherever BG1 is off — so we force it to a
near-black sky color and relocate whatever the converter happened to put there
to an opaque slot. The off-boss area is then a clean dark sky with a
two-brightness static star scatter (a sparse bright field + a denser dim field)
for depth.

Outputs (committed; regenerate only when changing the boss):
    saucer.png         the authored source image (1024x1024)
    saucer_map.bin     32,768 bytes interleaved Mode 7 VRAM blob — even bytes
                       = 128x128 tilemap, odd bytes = 8bpp tile pixels; the
                       exact layout sf_mode7_load_map saucer_map, #$8000 DMAs
                       to VRAM word $0000
    saucer_palette.inc ca65 CGRAM data: saucer_pal (BGR555 words)
                       + SAUCER_PAL_COUNT

Regenerate (from a kit root that has toolchain/ — the materialized kit tree;
in the parent monorepo run from the parent root, the import path is the same):
    PYTHONPATH=. python3 templates/boss_saucer/assets/make_saucer.py
Deterministic output: same script, same bytes.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# --- arena geometry (tile units on the 128x128 grid) ---
CENTER = 63.5               # arena center (tiles)
BOSS_HALF = 22              # the saucer reads across the middle ~44x44 tiles

# --- palette (RGB; the converter assigns CGRAM indices in scan order, then
#     reserve_sky_backdrop() forces index 0 to SKY_DARK) ---
SKY_DARK = (6, 8, 18)            # night sky / backdrop (-> CGRAM index 0)
STAR = (150, 158, 190)           # bright static star (the original sparse field)
STAR_DIM = (56, 62, 84)          # dim star (a denser second field, for depth)
HULL_DK = (52, 58, 74)           # saucer hull, lower-rim shadow
HULL_MD = (110, 118, 138)        # saucer hull, midtone body
HULL_LT = (182, 190, 208)        # saucer hull, lit upper rim (metallic glint)
HULL_EDGE = (24, 26, 38)         # hull dark outline / hull-bottom seam
DOME_DK = (28, 96, 150)          # cockpit dome, shadow
DOME_MD = (64, 168, 232)         # cockpit dome, midtone
DOME_LT = (150, 226, 255)        # cockpit dome, glowing highlight
LIGHT_ON = (255, 196, 64)        # running light, lit core (amber)
LIGHT_DIM = (150, 96, 24)        # running light, dim halo
BEAM_DK = (60, 130, 70)          # underside emitter glow, outer
BEAM_LT = (170, 255, 190)        # underside emitter glow, hot core


def _ellipse(tx, ty, cx, cy, rx, ry):
    """True if tile (tx,ty) is inside the axis-aligned ellipse centered
    (cx,cy) with radii (rx,ry)."""
    dx = (tx - cx) / rx
    dy = (ty - cy) / ry
    return dx * dx + dy * dy <= 1.0


def saucer_color(tx: int, ty: int):
    """Solid color for a tile inside the saucer bounding box, or None if this
    tile is open sky (not part of the craft). All geometry is in tile units
    relative to the 128x128 grid; the craft is built feature-by-feature from
    coarse ellipses + bands so every 8x8 tile is one flat color and the
    converter dedups aggressively.

    The craft occupies roughly tx in [40..88], ty in [44..82] (the middle
    ~44 tiles). Vertical layering, top to bottom:
        dome (cockpit) -> hull disc (wide ellipse) -> running-light ring
        -> underside emitter glow + descending beam stub."""
    cx = CENTER

    # equator of the hull disc (where the widest hull ellipse is centered)
    hull_cy = CENTER + 1.0

    # ---- underside emitter glow + a short descending beam stub ----
    # a downward emitter cone directly under the hull center; reads as where
    # the boss's beam originates. Kept below the hull so it never hides hull.
    if ty > hull_cy + 4:
        # cone half-width shrinks slightly then the beam stub narrows
        spread = 7.0 - (ty - (hull_cy + 4)) * 0.25
        if spread > 1.5 and abs(tx - cx) <= spread:
            # hot core down the centerline, softer green on the flanks
            return BEAM_LT if abs(tx - cx) <= max(1.5, spread - 4) else BEAM_DK

    # ---- cockpit dome: a glowing hemisphere on top of the hull ----
    # dome sits above the hull equator; a half-ellipse (only its upper half).
    dome_cy = hull_cy - 6
    if ty <= dome_cy + 1 and _ellipse(tx, ty, cx, dome_cy, 9.0, 8.0):
        # vertical shade: lit crown, mid body, shadowed base
        if ty <= dome_cy - 3:
            return DOME_LT
        if ty <= dome_cy - 1:
            return DOME_MD
        return DOME_DK

    # ---- main hull disc: a wide flat ellipse (the saucer body) ----
    hull = _ellipse(tx, ty, cx, hull_cy, 22.0, 6.5)
    if not hull:
        return None

    # dark hull outline: the bottom-most rim row reads as the disc underside
    if not _ellipse(tx, ty, cx, hull_cy, 22.0, 5.5):
        if ty > hull_cy:
            return HULL_EDGE          # underside seam (dark)
        return HULL_LT                # top rim catches the light (metallic)

    # running-light ring: amber lights studded along the hull equator
    if abs(ty - hull_cy) <= 0.8:
        # lit pip every 5 tiles, a dim halo on the immediate neighbors
        rel = int(round(tx - cx))
        if rel % 5 == 0:
            return LIGHT_ON
        if rel % 5 in (1, 4):
            return LIGHT_DIM

    # hull body shading: lit above the equator, shadowed below — gives the
    # disc volume so it still reads as a 3D craft under Mode 7 scaling.
    if ty < hull_cy - 1:
        return HULL_LT if ((tx >> 1) ^ (ty >> 1)) & 1 else HULL_MD
    if ty > hull_cy + 1:
        return HULL_DK
    return HULL_MD


def star_color(tx: int, ty: int):
    """Deterministic two-brightness starfield (a hash on tile coords), fixed for
    reproducibility. The BRIGHT field is byte-for-byte the original 1-in-64
    scatter (the reveal + lunge lit-pixel tests are calibrated against it); a
    denser second field of DIM stars is layered on for depth. Returns the star
    color, or None for open sky."""
    # mix the coords so the field scatters instead of striping along a line
    h = (tx * 374761393 + ty * 668265263) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    h ^= h >> 16
    if (h & 0x3F) == 0:          # bright: ~1 in 64 (UNCHANGED from the original)
        return STAR
    if (h & 0x1F) == 0x0A:       # dim: ~1 in 32, disjoint from the bright set
        return STAR_DIM
    return None


def tile_color(tx: int, ty: int):
    """Solid color for tile (tx, ty) — saucer in the middle, night sky around."""
    if CENTER - BOSS_HALF - 4 <= tx <= CENTER + BOSS_HALF + 4 and \
       CENTER - BOSS_HALF - 4 <= ty <= CENTER + BOSS_HALF + 8:
        c = saucer_color(tx, ty)
        if c is not None:
            return c
    # open sky: near-black, with a two-brightness static star scatter for depth
    c = star_color(tx, ty)
    if c is not None:
        return c
    return SKY_DARK


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


def reserve_sky_backdrop(tile_data: bytes, palette: bytes):
    """Make CGRAM index 0 the SKY_DARK backdrop (shown wherever BG1 is off).

    The converter assigned index 0 to the first pixel it scanned — tile (0,0),
    which is open sky. In Mode 7 index 0 is the transparent/backdrop slot, so
    we want it to BE the night-sky color. If the first-scanned color is already
    SKY_DARK we are done; otherwise relocate that color to the first free
    opaque slot and write SKY_DARK into index 0. Only index 0 changes meaning;
    every other index is untouched, so any hard-coded CGRAM reference in the
    template stays valid.

    Returns ``(tile_data, palette)`` with the swap applied.
    """
    import struct
    from toolchain.mode7_assets import rgb_to_bgr555

    sky_word = rgb_to_bgr555(*SKY_DARK)
    idx0_word = struct.unpack_from("<H", palette, 0)[0]
    if idx0_word == sky_word:
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
    struct.pack_into("<H", pal, 0, sky_word)                # sky dark -> idx 0
    return bytes(td), bytes(pal)


def main() -> None:
    try:
        from toolchain.mode7_map_converter import convert_map_png
        from toolchain.mode7_assets import interleave_mode7_data
    except ImportError:
        sys.exit("toolchain/ not importable — run from the kit root with "
                 "PYTHONPATH=. (see the header)")

    png = HERE / "saucer.png"
    build_png(png)

    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_sky_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "saucer_map.bin").write_bytes(blob)
    print(f"wrote {HERE / 'saucer_map.bin'} ({len(blob)} bytes)")

    # palette .inc — only the used head of the 256-color table
    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; =============================================================================",
        "; saucer_palette.inc — boss_saucer Mode 7 CGRAM data (GENERATED — do not edit)",
        "; =============================================================================",
        "; Regenerate: PYTHONPATH=. python3 templates/boss_saucer/assets/make_saucer.py",
        "; (companion blob: saucer_map.bin, the interleaved Mode 7 VRAM image)",
        "; CGRAM index 0 = SKY_DARK night-sky backdrop (shown where BG1 is off).",
        "; =============================================================================",
        "",
        "saucer_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; color {i}")
    lines += ["", f"SAUCER_PAL_COUNT = {used}", ""]
    (HERE / "saucer_palette.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'saucer_palette.inc'} ({used} colors)")


if __name__ == "__main__":
    main()
