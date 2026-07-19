#!/usr/bin/env python3
"""make_terrain.py — a SEAMLESS grass-capped floating island for the shmup rail.

Why this generator exists (the border fix)
-------------------------------------------
The shmup scatters an 8x6 terrain patch as "islands" over the night sky. That
patch was a raw png2snes conversion of Four Seasons region 0,0,64,48 — but the
pack authors every 16x16 cell as a FREE-STANDING platform block (dark outline +
shaded corners on all four edges; the region even includes "?"/"!" item blocks).
Tiled into an island, each cell showed its own border, so every island read as a
GRID of bordered bricks, not a landmass. That is the "sprite edge problem" the
owner reported.

An island wants an outline only where an edge is REAL — its own silhouette
against the sky — and a SEAMLESS interior. This generator authors that: a
64x48 island image (rounded grass-capped dirt: a grass lip on top, a speckled
dirt body, a soft shaded underside, softened corners), then slices it into 8x8
BG tiles exactly like png2snes bg (blank tile #0 reserved, content-deduped,
mset-ready map words). The palette is DERIVED from the pack's own grass/dirt
column (region 0,0,16,32) so the island keeps the Four Seasons look.

The 8x6 map is what main.asm's island-scatter loop stamps at five staggered
origins; the transparent (tile 0) cells outside the island silhouette let the
night sky show through, so each stamp reads as a discrete floating island.

Regenerate (from a materialized kit root, or the parent monorepo root — same
import path; needs the registered CC0 pack zip under examples/itch_cc0/):
    PYTHONPATH=. python3 templates/shmup/assets/make_terrain.py
Deterministic output: same script + same pack, same bytes.
"""
from __future__ import annotations

import random
import sys
import zipfile
from pathlib import Path

from PIL import Image

from tools.png2snes import (
    build_palette,
    emit_bytes,
    emit_words,
    encode_tile_4bpp,
    opaque_colors,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
ZIP_NAME = "Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels.zip"
PAL_REGION = (0, 0, 16, 32)   # the pack's grass-block-over-dirt-block column
OUT = HERE / "terrain.inc"

MAP_W, MAP_H = 8, 6            # 8x6 cells -> 64x48 px (main.asm hard-codes 8 x 6)
W, H = MAP_W * 8, MAP_H * 8

# palette-index roles in the pack's luminance-sorted grass/dirt order (0 transp)
EDGE = 1             # pack outline / dark-neutral — the island's shaded rim + lip
DIRT_SHADOW = 2      # dark brown (underside + specks)
GRASS_DARK = 3       # dark green (grass tips / roots)
DIRT_MID = 4         # mid brown (dirt fill base)
GRASS_BRIGHT = 5     # bright green
DIRT_LIGHT = 6       # light brown (dirt highlight speck)
GRASS_LIGHT = 7      # light green

EXPECTED_PAL = [0x0000, 0x14A6, 0x1D0E, 0x1DE3, 0x21D7, 0x1B0B, 0x329B, 0x2373]

# HUD backing: a dark slate bar tile (palette 0, colour index 8 — free; the
# island uses 1..7) placed on the fixed BG2 layer behind the BG3 HUD text so
# SCORE/LIVES stay legible when a bright island scrolls under the top row. The
# colour is far darker than any terrain tone and reads as a deliberate UI bar
# over the night sky. See main.asm (BG12NBA share + the mset #2 band).
HUD_BACK_IDX = 8
HUD_BACK_COLOR = 0x10A3   # BGR15 dark slate-blue (R24 G16 B64) — cool, low-luma


def find_zip():
    for base in (ROOT, ROOT.parent):
        p = base / "examples" / "itch_cc0" / ZIP_NAME
        if p.exists():
            return p
    raise SystemExit("make_terrain: pack zip not found under examples/itch_cc0/")


def derive_palette():
    """png2snes's BG palette build over the pack's grass/dirt column -> the same
    band-friendly grass+dirt ramp split_v_fight uses (so the two rails match)."""
    with zipfile.ZipFile(find_zip()) as zf:
        name = next(n for n in zf.namelist()
                    if n.endswith("four-seasons-tileset.png"))
        with zf.open(name) as fh:
            img = Image.open(fh).convert("RGBA").copy()
    x, y, w, h = PAL_REGION
    words, _ = build_palette(opaque_colors(img.crop((x, y, x + w, y + h))))
    if words[:len(EXPECTED_PAL)] != EXPECTED_PAL:
        raise SystemExit("make_terrain: derived grass/dirt palette drifted:\n"
                         f"  {[f'${w:04X}' for w in words[:8]]}")
    words[HUD_BACK_IDX] = HUD_BACK_COLOR   # the fixed BG2 HUD-bar colour
    return words


# ---- author the island as a 64x48 index image ------------------------------

def in_island(x, y):
    """Rounded-rectangle silhouette (standard test): clamp the pixel to the
    rectangle inset by R and keep it if within R of that point — so the four
    corners round off to quarter-circles and a stamp reads as an island."""
    R = 6
    cx = min(max(x, R), W - 1 - R)
    cy = min(max(y, R), H - 1 - R)
    return (x - cx) ** 2 + (y - cy) ** 2 <= R * R


def _dirt_px(x, y):
    """Deterministic per-pixel dirt speckle (a filled field, so it tiles)."""
    v = random.Random((x * 73856 + y * 19349) & 0xFFFFFFFF).random()
    if v < 0.11:
        return DIRT_SHADOW
    if v < 0.26:
        return DIRT_LIGHT
    return DIRT_MID


def author_island():
    grid = [[0] * W for _ in range(H)]
    dirt = _dirt_px

    for y in range(H):
        for x in range(W):
            if not in_island(x, y):
                continue
            top_edge = not in_island(x, y - 1)
            bot_edge = not in_island(x, y + 1)
            if y <= 1:                       # grass cap
                if top_edge or y == 0:
                    grid[y][x] = GRASS_DARK  # the darker grass lip (real top edge)
                else:
                    grid[y][x] = GRASS_LIGHT if (x + y) % 2 else GRASS_BRIGHT
            elif y == 2:                     # grass roots melting into dirt
                grid[y][x] = GRASS_DARK if (x % 4 == 0) else dirt(x, y)
            else:                            # dirt body
                grid[y][x] = dirt(x, y)
            # soft shaded underside + side rim: 1 px of dirt-shadow on the real edge
            if y >= 2 and (bot_edge or not in_island(x - 1, y)
                           or not in_island(x + 1, y)):
                grid[y][x] = DIRT_SHADOW
    return grid


# ---- slice to tiles + dedup (png2snes bg semantics) ------------------------

def slice_tiles(grid):
    chr_blobs = [bytes(32)]                  # tile 0 reserved blank
    cache = {bytes(32): 0}
    map_words = []
    for ty in range(MAP_H):
        for tx in range(MAP_W):
            cell = [grid[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
            if not any(v for row in cell for v in row):
                map_words.append(0)          # blank cell, palette 0
                continue
            enc = encode_tile_4bpp(cell)
            if enc not in cache:
                cache[enc] = len(chr_blobs)
                chr_blobs.append(enc)
            map_words.append(cache[enc] & 0x3FF)   # palette 0
    return b"".join(chr_blobs), map_words, len(chr_blobs)


def main():
    pal_words = derive_palette()
    grid = author_island()
    blob, map_words, n_tiles = slice_tiles(grid)
    # append the solid HUD-backing tile (all pixels = HUD_BACK_IDX) after the
    # island tiles; main.asm stamps it on the fixed BG2 layer behind the HUD.
    hud_tile = n_tiles
    blob = blob + encode_tile_4bpp([[HUD_BACK_IDX] * 8 for _ in range(8)])
    n_tiles += 1
    lines = [
        "; Generated by templates/shmup/assets/make_terrain.py — DO NOT EDIT BY HAND",
        "; Regenerate: PYTHONPATH=. python3 templates/shmup/assets/make_terrain.py",
        "; source-pack: Four Seasons Platformer Tileset [16x16][FREE] — Rotting Pixels",
        ";   (examples/itch_cc0/; grant: custom permissive — free + commercial use,",
        ";    modification, credit optional; see examples/itch_cc0/LICENSES.md). The",
        ";    PALETTE is derived byte-for-byte from pack region 0,0,16,32 (its grass/",
        ";    dirt column); the island TILES + MAP are RE-AUTHORED seamless — a",
        ";    grass-capped rounded dirt island — because the pack's raw cells are",
        ";    free-standing outlined blocks, not tileable terrain (a raw conversion",
        ";    borders every island cell). See the generator docstring.",
        f"; {MAP_W}x{MAP_H} cells, {n_tiles} unique tiles (incl. reserved blank #0), "
        "1 BG palette(s)",
        "; LOAD CONTRACT: sf_load_bg_chr 0, terrain_chr, terrain_chr_bytes",
        "; then sf_load_bg_pals 0, terrain_pal, terrain_pal_count — map words",
        "; already carry tile index (base 0 baked in) and palette bits;",
        "; pass them straight to mset. If you also use sf_text, keep",
        "; base + tiles <= 80 (the font owns BG1 tiles 80-127).",
        "",
        f"terrain_chr_tiles = {n_tiles}",
        f"terrain_chr_bytes = {len(blob)}",
        "terrain_pal_count = 1",
        f"terrain_map_w = {MAP_W}",
        f"terrain_map_h = {MAP_H}",
        f"terrain_hud_tile = {hud_tile}   ; solid dark bar tile (palette 0 idx "
        f"{HUD_BACK_IDX}); main.asm stamps it on the fixed BG2 HUD band",
        "",
        emit_words("terrain_pal", pal_words),
        "",
        emit_words("terrain_map", map_words),
        "",
        emit_bytes("terrain_chr", blob),
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"make_terrain: {n_tiles} tiles ({len(blob)} CHR bytes) -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
