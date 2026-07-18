#!/usr/bin/env python3
"""make_floor.py — first-party receding-ground-plane Mode 7 floor for the
split_h_demo (the horizontal raster-band split template).

CLEAN-ROOM: ORIGINAL placeholder art authored from scratch. Reproduces NO
commercial-game content — only the Mode 7 floor TECHNIQUE (a receding textured
ground plane) is exercised, never any game's art.

Authors a 1024x1024 PNG on the 128x128 Mode 7 tile grid: a bold TRACK-LIKE
checker ground plane — a two-tone checkerboard tarmac with a bright straight
lane running down the middle and regular cross-stripes. The strong regular
pattern makes the perspective recede unambiguously (so a rendered frame reads
clearly as a receding ground plane, not a flat fill), and gives the seam test a
non-uniform floor band to check against the tile HUD band above it.

  - CGRAM index 0 reserved as the dark tarmac backdrop (Mode 7 out-of-map fill).

Outputs (committed):
    floor.png            authored source image (1024x1024) — reference only
    floor_map.bin        32768-byte interleaved Mode 7 VRAM blob (BANK1)
    floor_palette.inc    ca65 CGRAM data (floor_pal + FLOOR_PAL_COUNT)

Regenerate (from the materialized kit root, PYTHONPATH=.):
    PYTHONPATH=. python3 templates/split_h_demo/assets/make_floor.py
"""
from __future__ import annotations

import sys
import struct
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# --- colours (RGB) — an original cool tarmac + warm lane palette ---
TARMAC_A = (30, 32, 40)     # checker dark  -> reserved to CGRAM index 0
TARMAC_B = (60, 64, 78)     # checker light
STRIPE   = (200, 200, 210)  # cross-stripe (bright, high contrast)
LANE     = (210, 170, 60)   # centre lane (warm gold — the strong recede cue)
LANE_EDGE = (250, 230, 150)  # lane edge highlight

CHECK = 4                   # checker block size in TILES (32 world px)
STRIPE_PITCH = 16           # a full-width cross-stripe every N tiles
LANE_HALF = 3               # centre-lane half-width in TILES (col 64 +/- this)


def tile_color(tx: int, ty: int):
    # centre lane: a straight bright band down the middle (cols ~61..67),
    # edged with a highlight — the dominant perspective recede cue.
    dc = tx - 64
    if abs(dc) <= LANE_HALF:
        return LANE_EDGE if abs(dc) == LANE_HALF else LANE
    # full-width cross-stripes at a regular pitch (the depth ticks).
    if ty % STRIPE_PITCH == 0 or ty % STRIPE_PITCH == 1:
        return STRIPE
    # two-tone checker tarmac everywhere else.
    bx, by = tx // CHECK, ty // CHECK
    return TARMAC_B if (bx ^ by) & 1 else TARMAC_A


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


def reserve_backdrop(tile_data: bytes, palette: bytes):
    """Force CGRAM index 0 to TARMAC_A (the Mode 7 backdrop slot), remapping any
    tile pixel that landed on index 0 to a freshly appended duplicate colour."""
    from toolchain.mode7_assets import rgb_to_bgr555
    want = rgb_to_bgr555(*TARMAC_A)
    idx0 = struct.unpack_from("<H", palette, 0)[0]
    if idx0 == want:
        return tile_data, palette
    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    free = used
    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:
            td[i] = free
    pal = bytearray(palette)
    struct.pack_into("<H", pal, free * 2, idx0)
    struct.pack_into("<H", pal, 0, want)
    return bytes(td), bytes(pal)


def main() -> None:
    try:
        from toolchain.mode7_map_converter import convert_map_png
        from toolchain.mode7_assets import interleave_mode7_data
    except ImportError:
        sys.exit("toolchain/ not importable — run from kit root with PYTHONPATH=.")

    png = HERE / "floor.png"
    build_png(png)

    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "floor_map.bin").write_bytes(blob)
    print(f"wrote floor_map.bin ({len(blob)} bytes)")

    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; floor_palette.inc — GENERATED (make_floor.py). CGRAM idx0 = tarmac backdrop.",
        "floor_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; colour {i}")
    lines += ["", f"FLOOR_PAL_COUNT = {used}", ""]
    (HERE / "floor_palette.inc").write_text("\n".join(lines))
    print(f"wrote floor_palette.inc ({used} colours)")


if __name__ == "__main__":
    main()
