#!/usr/bin/env python3
"""make_chamber.py — first-party placeholder STONE CHAMBER floor for the
mode7_chamber demo (the Mode 7 "barrel chamber" effect template).

CLEAN-ROOM: this is ORIGINAL placeholder art (an ashlar stone floor with an
asymmetric inlay), authored from scratch. It reproduces NO commercial-game
content — only the Mode 7 effect TECHNIQUE is recreated, never any game's art.

Authors a 1024x1024 PNG on the 128x128 Mode 7 tile grid:
  - An ASHLAR STONE FLOOR: a two-tone block checker with mortar-line relief.
  - Bold HORIZONTAL RIBS across the full width at a regular pitch — the motion
    cue: the ribs bow with the per-scanline barrel and ride up/down with the
    vertical undulation, so both reads are unambiguous in a rendered frame.
  - CGRAM index 0 reserved as a dark stone backdrop (the Mode 7 out-of-map fill).

Outputs (committed):
    chamber.png            authored source image (1024x1024) — reference only
    chamber_map.bin        32768-byte interleaved Mode 7 VRAM blob (BANK1)
    chamber_palette.inc    ca65 CGRAM data (chamber_pal + CHAMBER_PAL_COUNT)

Regenerate (from the materialized kit root, PYTHONPATH=.):
    PYTHONPATH=. python3 templates/mode7_chamber/assets/make_chamber.py
"""
from __future__ import annotations

import sys
import struct
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# --- colours (RGB) — an original cool-grey stone palette ---
STONE_A  = (44, 46, 54)    # ashlar block dark  -> reserved to CGRAM index 0
STONE_B  = (92, 96, 110)   # ashlar block light (the checker motion cue)
MORTAR   = (24, 25, 30)    # mortar line between blocks (relief)
RIB      = (170, 150, 90)  # horizontal accent rib body (warm brass — the motion cue)
RIB_HI   = (236, 214, 150) # rib top-edge highlight

BLOCK = 2                  # ashlar block size in TILES (16px blocks)
RIB_PITCH = 8              # a horizontal rib every RIB_PITCH tiles (64 world px)


def tile_color(tx: int, ty: int):
    # Horizontal ribs: a 2-tile-tall bright band across the FULL width every
    # RIB_PITCH tiles (highlight row + body row). These are the motion cue —
    # they bow with the per-scanline barrel and ride up/down with the vertical
    # undulation (they replace the old asymmetric bearing arrow).
    m = ty % RIB_PITCH
    if m == 0:
        return RIB_HI
    if m == 1:
        return RIB
    # ashlar stone: mortar lines on block boundaries, else the two-tone checker
    bx, by = tx // BLOCK, ty // BLOCK
    on_mortar = (tx % BLOCK == 0) or (ty % BLOCK == 0)
    if on_mortar:
        return MORTAR
    return STONE_B if (bx ^ by) & 1 else STONE_A


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
    """Force CGRAM index 0 to STONE_A (the Mode 7 backdrop slot), remapping any
    tile pixel that landed on index 0 to a freshly appended duplicate colour."""
    from toolchain.mode7_assets import rgb_to_bgr555
    want = rgb_to_bgr555(*STONE_A)
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

    png = HERE / "chamber.png"
    build_png(png)

    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "chamber_map.bin").write_bytes(blob)
    print(f"wrote chamber_map.bin ({len(blob)} bytes)")

    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; chamber_palette.inc — GENERATED (make_chamber.py). CGRAM idx0 = stone backdrop.",
        "chamber_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; colour {i}")
    lines += ["", f"CHAMBER_PAL_COUNT = {used}", ""]
    (HERE / "chamber_palette.inc").write_text("\n".join(lines))
    print(f"wrote chamber_palette.inc ({used} colours)")


if __name__ == "__main__":
    main()
