#!/usr/bin/env python3
"""make_track.py — first-party closed-circuit Mode 7 track (racer template).

Authors a 1024x1024 track PNG on the 128x128-tile grid (every 8x8 tile is one
solid color, so the kit converter dedups the whole map to ~7 unique tiles and
7 palette entries — far under the Mode 7 limits of 256 tiles / 256 colors),
then converts it through the kit's Mode 7 pipeline:

    toolchain/mode7_map_converter.py::convert_map_png   (tiles+map+palette)
    toolchain/mode7_assets.py::interleave_mode7_data    (native VRAM layout)

Track design — a closed circular circuit, drivable out of the box:
    grass        2x2-tile two-green checker (motion cue off the road)
    road         ring, radius 38..52 tiles, two-gray 4x4 checker (motion cue)
    edge stripes 1-tile red/white rumble checkers at both road edges
    start line   black/white checker across the road on the east side
                 (the template spawns the camera on it: posx=872, posy=512)

Outputs (committed; regenerate only when changing the track):
    track.png          the authored source image
    track_map.bin      32,768 bytes interleaved Mode 7 VRAM blob — even bytes
                       = 128x128 tilemap, odd bytes = 8bpp tile pixels; the
                       exact layout sf_mode7_load_map DMAs to VRAM word $0000
    track_palette.inc  ca65 CGRAM data: track_pal (BGR555 words) +
                       TRACK_PAL_COUNT

Regenerate (from a kit root that has toolchain/ — the materialized kit tree;
in the parent monorepo run from the parent root, the import path is the same):
    PYTHONPATH=. python3 templates/racer/assets/make_track.py
Deterministic output: same script, same bytes.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# --- track geometry (tile units on the 128x128 grid) ---
CENTER = 63.5               # ring center (tiles)
ROAD_IN = 38.0              # inner road radius
ROAD_OUT = 52.0             # outer road radius
STRIPE_W = 1.0              # rumble-stripe width outside each road edge

# --- the palette (RGB; the converter assigns CGRAM indices in scan order) ---
GRASS_A = (40, 116, 40)
GRASS_B = (56, 140, 56)
ROAD_A = (88, 88, 96)
ROAD_B = (104, 104, 112)
STRIPE_R = (208, 44, 44)
WHITE = (236, 236, 236)
LINE_K = (20, 20, 24)

# --- the sky (shown above the horizon by the template's TM-split HDMA) ---
# Mode 7 BG1 has no second layer, so the sky is the CGRAM[0] backdrop, revealed
# above the horizon where the TM-split turns BG1 off. The converter assigns
# index 0 to the first pixel it scans — tile (0,0), which is grass — so a naive
# build leaves grass at the transparent index-0 slot, making grass and sky the
# SAME color (both = the backdrop). To get a sky that is DISTINCT from the green
# grass, reserve_sky_backdrop() (below) swaps a dedicated sky color into index 0
# and relocates grass to an opaque slot. SKY is a daylight blue; the template's
# day-night color-math subtract darkens it toward the horizon and at night.
SKY = (96, 168, 248)


def tile_color(tx: int, ty: int) -> tuple[int, int, int]:
    """Solid color for tile (tx, ty) — the whole map is solid 8x8 tiles."""
    dx = tx - CENTER
    dy = ty - CENTER
    d = math.hypot(dx, dy)

    # start/finish line: across the road on the east side (camera spawn)
    if ty in (63, 64) and ROAD_IN <= dx <= ROAD_OUT:
        return LINE_K if (tx + ty) & 1 else WHITE

    if ROAD_IN <= d <= ROAD_OUT:                       # road surface
        return ROAD_B if ((tx >> 2) ^ (ty >> 2)) & 1 else ROAD_A
    if ROAD_IN - STRIPE_W <= d < ROAD_IN or ROAD_OUT < d <= ROAD_OUT + STRIPE_W:
        return STRIPE_R if (tx + ty) & 1 else WHITE    # rumble stripes
    return GRASS_B if ((tx >> 1) ^ (ty >> 1)) & 1 else GRASS_A


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
    """Make CGRAM index 0 a dedicated SKY color (the backdrop above the horizon).

    The converter put grass at index 0 (first-scanned pixel), and in Mode 7
    index 0 is transparent — so grass renders as the backdrop and would share
    the sky's color. Relocate grass to the first free opaque slot and write SKY
    into index 0. Only index 0 changes meaning; every other index (the
    palette-cycle entries 2..4, road, stripes, line) is untouched, so the
    template's hard-coded CGRAM references stay valid.

    Returns ``(tile_data, palette)`` with the swap applied.
    """
    import struct
    from toolchain.mode7_assets import rgb_to_bgr555

    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    grass_slot = used                       # first unused opaque index
    if grass_slot >= 256:
        raise ValueError("no free CGRAM slot to relocate grass for the sky")

    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:                          # index 0 was grass-A exclusively
            td[i] = grass_slot
    pal = bytearray(palette)
    struct.pack_into("<H", pal, grass_slot * 2,
                     struct.unpack_from("<H", pal, 0)[0])   # grass -> opaque slot
    struct.pack_into("<H", pal, 0, rgb_to_bgr555(*SKY))     # sky -> backdrop
    return bytes(td), bytes(pal)


def main() -> None:
    try:
        from toolchain.mode7_map_converter import convert_map_png
        from toolchain.mode7_assets import interleave_mode7_data
    except ImportError:
        sys.exit("toolchain/ not importable — run from the kit root with "
                 "PYTHONPATH=. (see the header)")

    png = HERE / "track.png"
    build_png(png)

    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_sky_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "track_map.bin").write_bytes(blob)
    print(f"wrote {HERE / 'track_map.bin'} ({len(blob)} bytes)")

    # palette .inc — only the used head of the 256-color table
    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; =============================================================================",
        "; track_palette.inc — racer track CGRAM data (GENERATED — do not edit)",
        "; =============================================================================",
        "; Regenerate: PYTHONPATH=. python3 templates/racer/assets/make_track.py",
        "; (companion blob: track_map.bin, the interleaved Mode 7 VRAM image)",
        "; =============================================================================",
        "",
        "track_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; color {i}")
    lines += ["", f"TRACK_PAL_COUNT = {used}", ""]
    (HERE / "track_palette.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'track_palette.inc'} ({used} colors)")


if __name__ == "__main__":
    main()
