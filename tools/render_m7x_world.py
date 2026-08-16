#!/usr/bin/env python3
"""render_m7x_world.py — look at the mode7_explore world data as a PICTURE.

There is no ROM for this rail yet, so nothing can be rendered on the emulator.
What CAN be checked is that the data itself makes a believable world, and the
only way to check that is to look at it. This script renders two PNGs, both
built from the SHIPPED BYTES on disk rather than by re-running the generator's
geography — so what you see is what m7x_rom would place in ROM.

    m7x_world.png    the 512x512 world, one pixel per tile, as TWO panels:
                     left  = terrain CLASS (the collision view — what blocks
                             you), with the 128x128 boot window outlined and
                             the enterable house marked
                     right = the world's OWN palette colours (the art view —
                             coastline, forests, roads and towns as coloured)

    m7x_seed.png     the boot window at FULL 8bpp resolution, 1024x1024 px:
                     every tile id in m7x_seed.bin's even bytes drawn through
                     the 8x8 CHR in its ODD bytes, through m7x_pal.bin. This
                     is the texture proof — if the tiles were flat colour
                     blocks or a position-id pattern, this image would say so
                     immediately.

The seed panel reads the seed's tile ids back through the WRAPPED placement
((wy & 127)*128 + (wx & 127)), so the window appears in world order rather
than in VRAM order. That is a second, visual check on the property the
generator asserts numerically: if the placement were sequential, this image
would be torn into four offset quadrants.

Run:
    python3 tools/gen_mode7_explore_assets.py /tmp/m7x_assets/gen
    python3 tools/render_m7x_world.py /tmp/m7x_assets/gen /tmp/m7x_assets
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

WORLD_T = 512
VRAM_WIN = 128
SPAWN_TX, SPAWN_TY = 258, 258
DEMO_TX, DEMO_TY = 254, 254

# The terrain-class palette for the collision panel. Deliberately NOT the
# world's own colours: this panel answers "what blocks you", so blocked classes
# are the saturated ones and everything walkable is muted.
TERR_COLOR = {
    0: (74, 122, 66),      # GRASS      walkable
    1: (196, 170, 116),    # PATH       walkable
    2: (28, 54, 120),      # WATER      BLOCKED
    3: (110, 100, 96),     # MOUNTAIN   BLOCKED
    4: (208, 72, 56),      # TOWN       walkable, decorative
    5: (255, 0, 220),      # TOWN_ENTER walkable, ENTERS the town
}


def bgr555_to_rgb(w: int):
    """Undo the hardware's 5-bit-per-channel packing, back to 8-bit for the
    screen. The <<3 loses the low bits the PPU never had."""
    return (((w >> 0) & 31) << 3, ((w >> 5) & 31) << 3, ((w >> 10) & 31) << 3)


def load_pal(p: Path):
    b = p.read_bytes()
    return [bgr555_to_rgb(b[i] | (b[i + 1] << 8)) for i in range(0, len(b), 2)]


def render_world(world: bytes, terr: bytes, pal, out: Path) -> None:
    """Two 512x512 panels side by side: terrain class, then the world's own
    colours. One pixel per tile."""
    gap = 12
    img = Image.new("RGB", (WORLD_T * 2 + gap, WORLD_T), (16, 16, 20))
    px = img.load()

    # A per-tile-id colour for the art panel: the average of the tile's texture
    # would blur the checkers, so use the tile's DOMINANT palette entry — the
    # colour a viewer reads the tile as from a distance.
    tile_rgb = {
        0: pal[0], 1: pal[1], 2: pal[2], 3: pal[3], 4: pal[4],
        5: pal[5], 6: pal[6], 7: pal[7], 8: pal[8], 9: pal[9],
        10: pal[7],                       # the enterable house reads as roof
    }

    for ty in range(WORLD_T):
        row = ty * WORLD_T
        for tx in range(WORLD_T):
            tid = world[row + tx]
            px[tx, ty] = TERR_COLOR[terr[tid]]
            px[WORLD_T + gap + tx, ty] = tile_rgb.get(tid, (255, 0, 255))

    # Annotate the COLLISION panel only; the art panel stays pure data.
    # The 128x128 boot window, so the scale of "several windows" is visible.
    x0, y0 = SPAWN_TX - VRAM_WIN // 2, SPAWN_TY - VRAM_WIN // 2
    for i in range(VRAM_WIN):
        for (x, y) in ((x0 + i, y0), (x0 + i, y0 + VRAM_WIN - 1),
                       (x0, y0 + i), (x0 + VRAM_WIN - 1, y0 + i)):
            px[x, y] = (255, 255, 255)
    # The enterable house — one tile in 262,144, so it needs a crosshair.
    for d in range(-6, 7):
        if abs(d) > 1:
            px[DEMO_TX + d, DEMO_TY] = (255, 255, 255)
            px[DEMO_TX, DEMO_TY + d] = (255, 255, 255)

    img.save(out)
    print(f"  {out}  ({img.width}x{img.height}) "
          f"left = terrain class + boot window + house crosshair, "
          f"right = the world's own palette")


def render_seed(seed: bytes, pal, out: Path) -> None:
    """The boot window at full 8bpp: 128x128 tiles x 8x8 px = 1024x1024.

    Both halves of the seed are used — tile ids from the EVEN bytes, the CHR
    those ids index from the ODD bytes — so this picture is made of nothing
    but shipped bytes."""
    chr_data = bytes(seed[1::2])                  # 16,384 B, tile-major
    img = Image.new("RGB", (VRAM_WIN * 8, VRAM_WIN * 8))
    px = img.load()
    win_x0 = (SPAWN_TX - VRAM_WIN // 2) % WORLD_T
    win_y0 = (SPAWN_TY - VRAM_WIN // 2) % WORLD_T
    for dy in range(VRAM_WIN):
        wy = (win_y0 + dy) % WORLD_T
        for dx in range(VRAM_WIN):
            wx = (win_x0 + dx) % WORLD_T
            # read back through the WRAPPED placement, not sequentially
            word = (wy & (VRAM_WIN - 1)) * VRAM_WIN + (wx & (VRAM_WIN - 1))
            tid = seed[word * 2]
            base = tid * 64
            for y in range(8):
                for x in range(8):
                    px[dx * 8 + x, dy * 8 + y] = pal[chr_data[base + y * 8 + x]]
    img.save(out)
    print(f"  {out}  ({img.width}x{img.height}) the boot window, every tile "
          f"drawn through the seed's own CHR at 8bpp")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("assets", help="the directory gen_mode7_explore_assets wrote")
    ap.add_argument("outdir", help="where to write the PNGs")
    args = ap.parse_args(argv)
    a, out = Path(args.assets), Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    world = (a / "m7x_map.bin").read_bytes()
    terr = (a / "m7x_terr.bin").read_bytes()
    seed = (a / "m7x_seed.bin").read_bytes()
    pal = load_pal(a / "m7x_pal.bin")
    assert len(world) == WORLD_T * WORLD_T and len(seed) == 0x8000

    print("render_m7x_world:")
    render_world(world, terr, pal, out / "m7x_world.png")
    render_seed(seed, pal, out / "m7x_seed.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
