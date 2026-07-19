#!/usr/bin/env python3
"""make_stage.py — SEAMLESS grass-topped-dirt stage tiles for split_v_fight.

Why this generator exists (the border fix)
-------------------------------------------
The Four Seasons Platformer Tileset authors every 16x16 cell as a FREE-STANDING
platform block: a dark outline + shaded corner pixels wrap all four edges (the
"?"/brick look). png2snes faithfully extracts those blocks, so a raw region
conversion tiles them into a GRID of bordered cells — a dark outline around
every terrain cell, and (because the arena floor repeats the dirt block's
bottom row) a hard horizontal line every 8 px through the dirt body. That is the
"terrain has a border around it" the owner reported.

Terrain wants the opposite: an outline only where an edge is REAL (the top of
the ground — the grass lip) and a SEAMLESS interior everywhere else. This
generator authors that directly, calibrated to the platformer rail's
hand-drawn ground (grass lip on top, plain speckled dirt fill below):

  * palette — DERIVED byte-for-byte from the pack region the rail always used
    (Four Seasons region 0,0,16,32), so the colours are the pack's own and the
    rail's hand-set band-safe CGRAM in main.asm (idx1 = the outline recoloured
    to off-neutral $0CA9, idx2..7 the grass/dirt ramp) stays correct unchanged.
  * CHR    — RE-AUTHORED seamless: a grass lip (idx1 top edge over idx3/5/7
    blades) melting into a torus-tiling speckled dirt body (idx4 base, idx2
    shadow + idx6 highlight specks). No interior outlines, no corner pixels, so
    the floor reads as continuous ground with a grass surface — no grid.

Only stage_chr changes; stage_pal and stage_map are re-emitted identical to the
pack conversion (main.asm reads stage_chr + its own hand-set palette, and builds
the flat floor procedurally, so the map is documentation here).

Band-safety (split_v_fight's sacred constraint): the palette is unchanged, so
none of the floor colours can read as the divider's white core or dark-neutral
shadow in the centre probe band — the property holds by construction. The grass
lip keeps idx1 pixels so the -DUNSAFE_STAGE non-vacuity proof (which recolours
idx1 to the pack's dark-neutral $14A6) still trips the shadow probe.

Regenerate (from a materialized kit root, or the parent monorepo root — same
import path; needs the registered CC0 pack zip under examples/itch_cc0/):
    PYTHONPATH=. python3 templates/split_v_fight/assets/make_stage.py
Deterministic output: same script + same pack, same bytes.
"""
from __future__ import annotations

import random
import sys
import zipfile
from pathlib import Path

from PIL import Image

# tools/png2snes.py helpers — the exact palette build + 4bpp encode + emit
# formatting the committed conversion used, so this file stays byte-format
# identical to a png2snes .inc.
from tools.png2snes import (
    build_palette,
    emit_bytes,
    emit_words,
    encode_tile_4bpp,
    opaque_colors,
    rgb_to_bgr15,
)

HERE = Path(__file__).resolve().parent
# kit root = .../templates/split_v_fight/assets -> up 3
ROOT = HERE.parent.parent.parent
ZIP_NAME = "Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels.zip"
REGION = (0, 0, 16, 32)   # the grass-block-over-dirt-block column the rail used
OUT = HERE / "stage.inc"


def find_zip():
    """The registered CC0 pack zip, in the materialized kit (examples/itch_cc0
    under the kit root) or the parent monorepo (one level up)."""
    for base in (ROOT, ROOT.parent):
        p = base / "examples" / "itch_cc0" / ZIP_NAME
        if p.exists():
            return p
    raise SystemExit(f"make_stage: pack zip not found (looked under "
                     f"{ROOT}/examples/itch_cc0 and {ROOT.parent}/examples/itch_cc0)")

# The rail's hand-set band-safe CGRAM order (main.asm) — the pack palette must
# land in exactly this index order or the re-authored CHR would mis-colour.
EXPECTED_PAL = [0x0000, 0x14A6, 0x1D0E, 0x1DE3, 0x21D7, 0x1B0B, 0x329B, 0x2373]

# palette-index roles (in the derived, luminance-sorted order)
OUTLINE = 1          # pack outline (recoloured off-neutral $0CA9 in-game): grass lip
DIRT_SHADOW = 2      # dark brown
GRASS_DARK = 3       # dark green
DIRT_MID = 4         # mid brown (dirt fill base)
GRASS_BRIGHT = 5     # bright green
DIRT_LIGHT = 6       # light brown (dirt highlight speck)
GRASS_LIGHT = 7      # light green


def load_region():
    with zipfile.ZipFile(find_zip()) as zf:
        name = next(n for n in zf.namelist()
                    if n.endswith("four-seasons-tileset.png"))
        with zf.open(name) as fh:
            img = Image.open(fh).convert("RGBA").copy()
    x, y, w, h = REGION
    return img.crop((x, y, x + w, y + h))


def derive_palette(region):
    """png2snes's exact BG palette build over the region -> (words, colour->idx).
    Asserts it matches the rail's hand-set order so the re-authored CHR is safe."""
    words, c2i = build_palette(opaque_colors(region))
    if words[:len(EXPECTED_PAL)] != EXPECTED_PAL:
        raise SystemExit(
            "make_stage: derived palette drifted from the rail's band-safe order\n"
            f"  derived : {[f'${w:04X}' for w in words[:8]]}\n"
            f"  expected: {[f'${w:04X}' for w in EXPECTED_PAL]}")
    return words, c2i


# ---- seamless tile authoring ------------------------------------------------

def dirt_tile(seed):
    """8x8 speckled dirt that tiles in BOTH directions (a filled idx4 field with
    scattered specks touches no edge structurally, so it wraps cleanly). Two
    seeds give the column-parity pair, breaking any repeat banding."""
    rng = random.Random(seed)
    t = [[DIRT_MID] * 8 for _ in range(8)]
    cells = [(x, y) for y in range(8) for x in range(8)]
    rng.shuffle(cells)
    for x, y in cells[:7]:            # shadow flecks
        t[y][x] = DIRT_SHADOW
    for x, y in cells[7:13]:          # light highlights
        t[y][x] = DIRT_LIGHT
    return t


def grass_tile(seed):
    """Grass surface: an idx1 lip on the very top (the REAL top-of-ground edge),
    three rows of blades, melting into the same speckled dirt below. Tiles
    horizontally (the floor is one grass row wide-repeated)."""
    rng = random.Random(seed)
    t = dirt_tile(seed ^ 0x5A5A)         # dirt body underneath
    t[0] = [OUTLINE] * 8                  # the outlined grass lip (top edge)
    blade = [GRASS_BRIGHT, GRASS_LIGHT, GRASS_LIGHT, GRASS_BRIGHT,
             GRASS_LIGHT, GRASS_BRIGHT, GRASS_LIGHT, GRASS_LIGHT]
    rng.shuffle(blade)
    t[1] = blade[:]
    t[2] = [GRASS_LIGHT if (x + seed) % 3 else GRASS_BRIGHT for x in range(8)]
    # row 3: grass roots darkening into the soil (dark-green tips over dirt)
    t[3] = [GRASS_DARK if (x * 2 + seed) % 3 == 0 else DIRT_MID for x in range(8)]
    return t


def subsoil_tile(seed):
    """Just below the grass surface: speckled dirt with a few dark-green roots
    still hanging from the grass above. Seamless (no borders)."""
    t = dirt_tile(seed)
    for x in range(8):
        if (x * 3 + seed) % 4 == 0:
            t[0][x] = GRASS_DARK          # a root reaching down from the grass row
    return t


def build_chr(c2i):
    """8 stage tiles in the pack's cell order (tile0 blank reserved by png2snes):
        1,2 grass surface   3,4 subsoil   5,6 dirt   7,8 dirt body
    main.asm places 1/2 at the grass row, 3/4 just below, 7/8 for the body; the
    parity pair (odd/even column) is two seeds of the same motif -> no banding."""
    tiles = [
        grass_tile(1), grass_tile(2),
        subsoil_tile(3), subsoil_tile(4),
        dirt_tile(5), dirt_tile(6),
        dirt_tile(7), dirt_tile(8),
    ]
    blob = bytearray(bytes(32))          # tile 0 = reserved blank
    for grid in tiles:
        blob += encode_tile_4bpp(grid)
    return bytes(blob), len(tiles) + 1


def main():
    region = load_region()
    pal_words, c2i = derive_palette(region)
    blob, n_tiles = build_chr(c2i)
    # stage_map: the pack's 2x4 cell order (documentation — main.asm builds the
    # flat floor procedurally and does not read this map).
    map_words = [0x0001, 0x0002, 0x0003, 0x0004,
                 0x0005, 0x0006, 0x0007, 0x0008]
    lines = [
        "; Generated by templates/split_v_fight/assets/make_stage.py — DO NOT EDIT BY HAND",
        "; Regenerate: PYTHONPATH=. python3 templates/split_v_fight/assets/make_stage.py",
        "; source-pack: Four Seasons Platformer Tileset [16x16][FREE] — Rotting Pixels",
        ";   (examples/itch_cc0/; grant: custom permissive — free + commercial use,",
        ";    modification, credit optional; see examples/itch_cc0/LICENSES.md). The",
        ";    PALETTE is derived byte-for-byte from pack region 0,0,16,32; the CHR is",
        ";    RE-AUTHORED seamless (grass lip on top, plain speckled dirt fill below)",
        ";    because the pack's cells are free-standing outlined blocks, not tileable",
        ";    terrain — a raw conversion borders every floor cell. See the generator",
        ";    docstring. main.asm recolours idx1 (pack outline) to off-neutral $0CA9",
        ";    at load for divider-band safety.",
        f"; {2}x{4} cells, {n_tiles} unique tiles (incl. reserved blank #0), 1 BG palette(s)",
        "; LOAD CONTRACT: sf_load_bg_chr 0, stage_chr, stage_chr_bytes",
        "; then sf_load_bg_pals 0, stage_pal, stage_pal_count — map words",
        "; already carry tile index (base 0 baked in) and palette bits;",
        "; pass them straight to mset. If you also use sf_text, keep",
        "; base + tiles <= 80 (the font owns BG1 tiles 80-127).",
        "",
        f"stage_chr_tiles = {n_tiles}",
        f"stage_chr_bytes = {len(blob)}",
        "stage_pal_count = 1",
        "stage_map_w = 2",
        "stage_map_h = 4",
        "",
        emit_words("stage_pal", pal_words),
        "",
        emit_words("stage_map", map_words),
        "",
        emit_bytes("stage_chr", blob),
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"make_stage: {n_tiles} tiles ({len(blob)} CHR bytes) -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
