#!/usr/bin/env python3
"""make_ground.py — first-party Mode 7 grid terrain (railshooter template).

A rail shooter's ground is a streaming reference grid (retro wireframe read):
a dark surface with bright grid lines, so the auto-advancing rail gives a clear
sense of forward speed as the lines rush toward the camera. Authors a
1024x1024 PNG on the 128x128-tile grid (every 8x8 tile is one solid color, so
the converter dedups to a handful of tiles/colors), then runs it through the
kit's Mode 7 pipeline (same path as the racer's make_track.py).

Sky: Mode 7 has no second BG layer, so the band above the horizon shows the
CGRAM[0] backdrop (the railshooter template's arm_sky_split turns BG1 off
there). The converter assigns index 0 to the first-scanned pixel, so we reserve
index 0 for a deep-space sky and relocate the ground color to an opaque slot —
otherwise the ground (transparent index 0) and sky would share a color. Same
trick as make_track.py reserve_sky_backdrop.

Regenerate (from a kit root with toolchain/, PYTHONPATH=.):
    PYTHONPATH=. python3 templates/railshooter/assets/make_ground.py
Deterministic: same script, same bytes.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# --- colors (RGB) ---
SKY = (24, 16, 64)          # deep-space backdrop (index 0, reserved)
GROUND = (16, 24, 56)       # dark surface between grid lines
GRID = (64, 200, 232)       # bright cyan grid lines (the speed cue)
GRID_MAJOR = (232, 96, 200)  # magenta major lines every 16 tiles (lane refs)

GRID_STEP = 4               # a grid line every 4 tiles
MAJOR_STEP = 16             # a major (magenta) line every 16 tiles


def tile_color(tx: int, ty: int) -> tuple[int, int, int]:
    on_major = (tx % MAJOR_STEP == 0) or (ty % MAJOR_STEP == 0)
    on_grid = (tx % GRID_STEP == 0) or (ty % GRID_STEP == 0)
    if on_major:
        return GRID_MAJOR
    if on_grid:
        return GRID
    return GROUND


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
    """Reserve CGRAM index 0 for the sky backdrop; relocate the index-0 ground
    color to the first free opaque slot. See make_track.py for the rationale."""
    from toolchain.mode7_assets import rgb_to_bgr555
    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    slot = used
    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:
            td[i] = slot
    pal = bytearray(palette)
    struct.pack_into("<H", pal, slot * 2, struct.unpack_from("<H", pal, 0)[0])
    struct.pack_into("<H", pal, 0, rgb_to_bgr555(*SKY))
    return bytes(td), bytes(pal)


def main() -> None:
    try:
        from toolchain.mode7_map_converter import convert_map_png
        from toolchain.mode7_assets import interleave_mode7_data
    except ImportError:
        sys.exit("toolchain/ not importable — run from the kit root with PYTHONPATH=.")

    png = HERE / "ground.png"
    build_png(png)

    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_sky_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "ground_map.bin").write_bytes(blob)
    print(f"wrote {HERE / 'ground_map.bin'} ({len(blob)} bytes)")

    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; =============================================================================",
        "; ground_palette.inc — railshooter grid-terrain CGRAM data (GENERATED)",
        "; =============================================================================",
        "; Regenerate: PYTHONPATH=. python3 templates/railshooter/assets/make_ground.py",
        "; =============================================================================",
        "",
        "ground_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; color {i}")
    lines += ["", f"GROUND_PAL_COUNT = {used}", ""]
    (HERE / "ground_palette.inc").write_text("\n".join(lines))
    print(f"wrote {HERE / 'ground_palette.inc'} ({used} colors)")


if __name__ == "__main__":
    main()
