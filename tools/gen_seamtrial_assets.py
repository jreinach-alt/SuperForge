#!/usr/bin/env python3
"""gen_seamtrial_assets — the split_v_seamtrial rail's art, as .bin blobs.

Emits into $(BUILD)/assets:

    svs_stage_chr.bin   9 tiles x 32 B, 4bpp   the terrain (BG1 == BG2)
    svs_stage_map.bin   32x32 tilemap words    the skyline the source authors
    svs_stage_pal.bin   16 words               BG palette 0 (only 0..7 used)
    svs_bevel_chr.bin   2 tiles x 32 B, 4bpp   the divider bar (BG3, read 2bpp)
    svs_bevel_pal.bin   16 words               BG3 2bpp palette 2 (CGRAM 8..11)
    svs_pad2048.bin     2048 B of zero         see PADDING, below
    svs_pad32.bin       32 B of zero           see PADDING, below

PROVENANCE. Everything here is AUTHORED from the numbers stated in this file --
the terrain height map, the four terrain colours, and the tile-selection ladder
the `@row`/`@col` loop walks. No pack art, no trace, no
reference read -- so this generator runs identically on a bare runner and the rail
has no oracle-gated test.

THE BEVEL IS A TRANSCRIPTION AND IT IS EXACT, which is the one place this
needed arithmetic rather than copying. The source draws its bar as TWO tiles
(`bg3_bar_tiles` tile1 = `$FFFE` x8, tile2 = `$C03F` x8) parked at BG3 map
columns 15 and 16 with BG3HOFS pinned to 0, so screen x 120..127 reads tile1
and 128..135 reads tile2. SuperForge's `split_v_bg` instead fills the WHOLE BG3
map with ONE tile and lets window 2 cut the bar out of it, so the visible
column x samples tile column `x & 7`. Reproducing the source's picture is
therefore a re-indexing, not a redesign -- the band only ever spans
[128-hw, 128+hw] with hw = spread>>4 <= 3, i.e. x in 125..131, which reads
tile columns 5,6,7,0,1,2,3:

    source  x:   125 126 127 | 128 129 130 131
    source pix:   3   3   2  |  2   2   1   1     (tile1[5,6,7] | tile2[0,1,2,3])
    tile col:     5   6   7  |  0   1   2   3

so BEVEL_COLS below is that row, re-indexed. Column 4 is unreachable at every
hw the sweep produces and is set to 3 so the highlight run stays contiguous if
SPREAD_MAX is ever raised. Verified for hw = 1, 2 and 3: the rendered 3, 5 and
7 px bars are pixel-for-pixel the source's.

PADDING, and why a blob of zeroes is the honest thing here. `split_v_bg`
declares `depends = ["split_v_rom"]`, and `split_v_rom` carries the
`split_v_fight` FIGHTERS' three claims (`sv_knight_chr`, `sv_knight_pal_r`,
`sv_knight_pal_b`) alongside the five stage/bevel claims `split_v_bg` actually
resolves. The dependency is coarser than the use, so composing the seam
mechanism drags in 2112 B of fighter art this rail never uploads -- and
`make rom-unbacked` (docs/37) correctly refuses a rom claim with no `.incbin`.
Backing those three with ZEROES says "this rail does not use them" in the
artifact itself; backing them with the fighter blobs would hide the coupling
behind art that looks intentional.
"""
from __future__ import annotations

import argparse
from pathlib import Path

# --- the palette, as an sf_bg_color block ----------------------------------
# Colour 0 is the backdrop. A stage whose every tile is solid can leave it
# $7FFF (white) and never show it. Here it is the SKY,
# so a transparent pixel (tile 0, which the map never uses) reads as sky rather
# than as a white flash -- power-on fidelity applied to a colour rather than to
# a byte.
SKY      = 0x7F54
GRASS    = 0x02E0
MOUNTAIN = 0x4A52
DIRT     = 0x1194
# Dither partners. AUTHORED, not in the source: the source's stage is four flat
# colours, and a flat colour is invisible under a horizontal camera shift. The
# skyline carries the divergence on its own, but the flat interiors do not, so
# odd world columns use a 1px checker against a darker partner. That is what
# makes "the two halves are showing different columns" readable INSIDE the
# ground as well as along its silhouette.
GRASS_D    = 0x01C0
MOUNTAIN_D = 0x318C
DIRT_D     = 0x08CD

STAGE_PAL = [SKY, SKY, GRASS, MOUNTAIN, DIRT, GRASS_D, MOUNTAIN_D, DIRT_D]

# --- the bevel, from split_v_fight's measured tones -------------------------
# These are the PUBLISHED RENDER's tones -- (49,49,49) /
# (156,156,156) / (255,255,255) -- not the $0CA9 a comment elsewhere quotes
# about something else. Same values split_v_fight ships, deliberately: the trial and
# the rail it graduated into must draw the SAME bar or the isolation proof is
# proving a different mechanism.
BEVEL_PAL = [0x0000, 0x18C6, 0x4E73, 0x7FFF]
BEVEL_COLS = [2, 2, 1, 1, 3, 3, 3, 2]   # see the docstring's re-indexing

# --- the terrain height map, `hmap` -----------------------------------------
HMAP = [18, 18, 17, 16, 15, 13, 11, 9, 8, 8, 9, 11, 13, 15, 16, 17,
        17, 16, 15, 14, 14, 15, 16, 17, 17, 16, 15, 15, 16, 17, 18, 18]
GND_DIRT = 24          # source equate: rows >= 24 are dirt regardless
MTN_LO, MTN_HI = 6, 13  # source ladder: cols [6,13) above the dirt line are rock
MAP_W = MAP_H = 32

# Tile ids in the authored CHR page.
T_BLANK, T_SKY, T_GRASS, T_MTN, T_DIRT = 0, 1, 2, 3, 4
T_GRASS_X, T_MTN_X, T_DIRT_X, T_SURF = 5, 6, 7, 8


def solid(v):
    return [[v] * 8 for _ in range(8)]


def checker(a, b):
    return [[a if (x + y) & 1 == 0 else b for x in range(8)] for y in range(8)]


def surface():
    """The ground's top tile: two rows of grass over dirt. The source has no
    such tile (its terrain top is a flat grass block); it exists because the
    silhouette is what the seam is read from, and a hard grass/sky edge with a
    dirt body under it reads the height change far more sharply."""
    return [[2 if y < 2 else 4] * 8 for y in range(8)]


def stage_tiles():
    return [solid(0), solid(1), solid(2), solid(3), solid(4),
            checker(2, 5), checker(3, 6), checker(4, 7), surface()]


def terrain_tile(col, row):
    """The source's selection ladder, plus the two authored
    refinements: the top non-sky row of a non-rock column is the surface tile,
    and odd columns take the dithered variant."""
    h = HMAP[col & 31]
    if row < h:
        return T_SKY
    rock = MTN_LO <= (col & 31) < MTN_HI and row < GND_DIRT
    if rock:
        return T_MTN_X if col & 1 else T_MTN
    if row >= GND_DIRT:
        return T_DIRT_X if col & 1 else T_DIRT
    if row == h:
        return T_SURF
    return T_GRASS_X if col & 1 else T_GRASS


def stage_map():
    return [terrain_tile(c, r) for r in range(MAP_H) for c in range(MAP_W)]


def encode_tile_4bpp(tile):
    """SNES 4bpp: 8 words of planes 0/1 interleaved, then 8 words of 2/3.
    Values are 0..7 by construction here; nothing is masked -- a masked index
    is a different colour on screen and no error anywhere -- it is asserted."""
    out = bytearray()
    for plane_pair in (0, 2):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = tile[y][x]
                if not 0 <= v <= 15:
                    raise ValueError(f"pixel {v} out of 4bpp range at ({x},{y})")
                bit = 7 - x
                lo |= ((v >> plane_pair) & 1) << bit
                hi |= ((v >> (plane_pair + 1)) & 1) << bit
            out += bytes((lo, hi))
    return bytes(out)


def pal16(words):
    w = list(words) + [0] * (16 - len(words))
    return b"".join(bytes((v & 0xFF, (v >> 8) & 0xFF)) for v in w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    out = ap.parse_args().out
    out.mkdir(parents=True, exist_ok=True)

    chr_bytes = b"".join(encode_tile_4bpp(t) for t in stage_tiles())
    assert len(chr_bytes) == 9 * 32, len(chr_bytes)
    (out / "svs_stage_chr.bin").write_bytes(chr_bytes)

    words = stage_map()
    assert len(words) == 1024
    (out / "svs_stage_map.bin").write_bytes(
        b"".join(bytes((w & 0xFF, (w >> 8) & 0xFF)) for w in words))

    (out / "svs_stage_pal.bin").write_bytes(pal16(STAGE_PAL + BEVEL_PAL))
    bevel = [BEVEL_COLS[:] for _ in range(8)]
    (out / "svs_bevel_chr.bin").write_bytes(
        encode_tile_4bpp(bevel) * 2)
    (out / "svs_bevel_pal.bin").write_bytes(pal16(BEVEL_PAL))

    (out / "svs_pad2048.bin").write_bytes(bytes(2048))
    (out / "svs_pad32.bin").write_bytes(bytes(32))
    print(f"gen_seamtrial_assets: wrote 7 blobs into {out}")


if __name__ == "__main__":
    main()
