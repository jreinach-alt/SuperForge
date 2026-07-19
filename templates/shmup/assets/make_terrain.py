#!/usr/bin/env python3
"""make_terrain.py — the shmup's streamed PLANET field, from the CC0 AlcWilliam
"Spaceship Pack" (examples/itch_cc0/Spaceship Pack.zip).

Why this generator exists (the space reskin)
--------------------------------------------
The shmup streams a field of BG "obstacle chunks" down the night sky as its
scrolling terrain. Those chunks used to be grass-capped dirt ISLANDS — a
platformer leftover the owner flagged: green grass + brown dirt has no place in
a space shooter. This generator replaces the island ART with PLANETS from the
same pack the ships came from, so the whole rail reads as one space scene. The
chunk ROLE is unchanged (streamed BG blocks over the sky) — only the art is.

Each planet is a native 48x48 pack sprite BOX-downscaled to a 32x32 (4x4-tile)
BG block — edge-bled first so the smooth shading survives the reduction — then
the four planets are quantized to ONE shared 13-colour BG palette. The round
silhouettes keep transparent corners, so the night sky shows through and each
block reads as a discrete planet. The four 4x4 blocks are concatenated into a
strip map; main.asm's scatter loop stamps them at staggered origins, cycling
all four designs so the streamed field shows variety.

The palette reserves index 0 (transparent — sky) and index 8 (the HUD backing
bar, unchanged from the island build); the 13 planet colours take indices 1-7
and 9-14. The solid HUD-backing tile is appended after the planet tiles exactly
as before, so main.asm's BG2 HUD band needs no change.

Four planets, in strip order:
    planet_1  ringed gas giant     planet_2  orange banded gas giant
    planet_4  magenta cratered     planet_6  blue-green earth-like world

Regenerate (from a materialized kit root, or the parent monorepo root — same
import path; needs the registered CC0 pack zip under examples/itch_cc0/):
    PYTHONPATH=. python3 templates/shmup/assets/make_terrain.py
Deterministic output: same script + same pack, same bytes.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageEnhance

from tools.png2snes import (
    emit_bytes,
    emit_words,
    encode_tile_4bpp,
    rgb_to_bgr15,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
ZIP_NAME = "Spaceship Pack.zip"
OUT = HERE / "terrain.inc"

# the four planet designs, in strip order (main.asm cycles them across stamps)
PLANET_PNGS = ["planet_1.png", "planet_2.png", "planet_4.png", "planet_6.png"]
PLANET_DESC = "ringed / orange banded / magenta cratered / blue-green earth"

BOX = 32                      # planet block: 32x32 px = 4x4 BG tiles
TILES = BOX // 8              # 4 tiles per side (main.asm hard-codes 4)
N_COLORS = 13                 # shared planet palette (0=transp, 8=HUD reserved)

# CGRAM slots the planet colours may occupy: 0 is transparent (the sky shows
# through), 8 is the HUD backing bar (below) — planets take the other 13.
SLOTS = [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14]

# HUD backing: a dark slate bar tile (palette 0, colour index 8 — reserved; the
# planets use 1-7 + 9-14) placed on the fixed BG2 layer behind the BG3 HUD text
# so SCORE/LIVES stay legible when a bright planet scrolls under the top row.
# The colour is far darker than any planet tone and reads as a deliberate UI bar
# over the night sky. See main.asm (BG12NBA share + the mset #2 band).
HUD_BACK_IDX = 8
HUD_BACK_COLOR = 0x10A3       # BGR15 dark slate-blue (R24 G16 B64) — cool, low-luma


def find_zip():
    for base in (ROOT, ROOT.parent):
        p = base / "examples" / "itch_cc0" / ZIP_NAME
        if p.exists():
            return p
    raise SystemExit("make_terrain: pack zip not found under examples/itch_cc0/")


def load_pack():
    imgs = []
    with zipfile.ZipFile(find_zip()) as zf:
        for name in PLANET_PNGS:
            with zf.open(name) as fh:
                imgs.append(Image.open(fh).convert("RGBA").copy())
    return imgs


def bleed_rgb(img: Image.Image) -> Image.Image:
    """Fill transparent pixels with the mean of opaque neighbours (iterative
    dilation) so a smooth downscale does not pull black from (0,0,0,0). Same
    technique make_ships.py uses on the ships — the smooth planet shading needs
    it too, or the round rim darkens into the sky."""
    img = img.convert("RGBA").copy()
    px = img.load()
    w, h = img.size
    opaque = [[px[x, y][3] >= 128 for x in range(w)] for y in range(h)]
    for _ in range(max(w, h)):
        add = {}
        for y in range(h):
            for x in range(w):
                if opaque[y][x]:
                    continue
                acc = [0, 0, 0]
                n = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < w and 0 <= yy < h and opaque[yy][xx]:
                            r, g, b, _ = px[xx, yy]
                            acc[0] += r; acc[1] += g; acc[2] += b; n += 1
                if n:
                    add[(x, y)] = (acc[0] // n, acc[1] // n, acc[2] // n, 0)
        if not add:
            break
        for (x, y), c in add.items():
            px[x, y] = c
            opaque[y][x] = True
    return img


def downscale(img: Image.Image) -> Image.Image:
    """Crop to opaque content, edge-bleed, BOX-downscale to the 32x32 block,
    a gentle contrast+sharpen so the bands/craters survive the reduction. The
    alpha is downscaled and re-thresholded separately, keeping the round
    silhouette (transparent corners) crisp."""
    img = img.convert("RGBA")
    a = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    bb = a.getbbox()
    img = img.crop(bb)
    a = a.crop(bb)
    small = bleed_rgb(img).resize((BOX, BOX), Image.BOX)
    small = ImageEnhance.Contrast(small).enhance(1.12)
    small = ImageEnhance.Sharpness(small).enhance(1.2)
    small.putalpha(a.resize((BOX, BOX), Image.BOX).point(lambda v: 255 if v >= 110 else 0))
    return small


def shared_quantize(frames):
    """Reduce all four planets to ONE shared N_COLORS palette (median-cut, no
    dither — deterministic). Returns (per-frame index grids using the reserved
    CGRAM SLOTS, palette as a list of RGB tuples in SLOTS order)."""
    strip = Image.new("RGB", (sum(f.width for f in frames), BOX), (0, 0, 0))
    x = 0
    for f in frames:
        strip.paste(f.convert("RGB"), (x, 0))
        x += f.width
    pal_img = strip.quantize(colors=N_COLORS, dither=Image.Dither.NONE)
    flat = pal_img.getpalette()
    pal_rgb = [tuple(flat[i * 3:i * 3 + 3]) for i in range(N_COLORS)]
    grids = []
    for f in frames:
        q = f.convert("RGB").quantize(palette=pal_img, dither=Image.Dither.NONE)
        idx = list(q.getdata())
        alpha = list(f.getchannel("A").point(lambda v: 255 if v >= 128 else 0).getdata())
        w, h = f.size
        grid = [[0] * w for _ in range(h)]
        for yy in range(h):
            for xx in range(w):
                if alpha[yy * w + xx] >= 128:
                    grid[yy][xx] = SLOTS[idx[yy * w + xx]]
        grids.append(grid)
    return grids, pal_rgb


def build_palette(pal_rgb):
    """16-word BG palette: 0 transparent, 8 the HUD bar, the 13 planet colours
    mapped onto the reserved SLOTS, the rest 0."""
    words = [0x0000] * 16
    words[HUD_BACK_IDX] = HUD_BACK_COLOR
    for c, rgb in enumerate(pal_rgb):
        words[SLOTS[c]] = rgb_to_bgr15(rgb)
    return words


def slice_planets(grids):
    """Slice each 32x32 planet into 8x8 tiles, dedup across ALL planets (blank
    tile #0 reserved, like png2snes bg). Returns (CHR blob, per-planet 4x4 map
    word lists, tile count incl. blank)."""
    chr_blobs = [bytes(32)]                  # tile 0 reserved blank
    cache = {bytes(32): 0}
    maps = []
    for grid in grids:
        mw = []
        for ty in range(TILES):
            for tx in range(TILES):
                cell = [grid[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
                if not any(v for row in cell for v in row):
                    mw.append(0)             # blank cell, palette 0
                    continue
                enc = encode_tile_4bpp(cell)
                if enc not in cache:
                    cache[enc] = len(chr_blobs)
                    chr_blobs.append(enc)
                mw.append(cache[enc] & 0x3FF)   # palette 0
        maps.append(mw)
    return b"".join(chr_blobs), maps, len(chr_blobs)


def main():
    frames = [downscale(p) for p in load_pack()]
    grids, pal_rgb = shared_quantize(frames)
    pal_words = build_palette(pal_rgb)
    blob, maps, n_tiles = slice_planets(grids)
    map_words = [w for planet in maps for w in planet]   # strip: 4 planets stacked
    # append the solid HUD-backing tile (all pixels = HUD_BACK_IDX) after the
    # planet tiles; main.asm stamps it on the fixed BG2 layer behind the HUD.
    hud_tile = n_tiles
    blob = blob + encode_tile_4bpp([[HUD_BACK_IDX] * 8 for _ in range(8)])
    n_tiles += 1
    lines = [
        "; Generated by templates/shmup/assets/make_terrain.py — DO NOT EDIT BY HAND",
        "; Regenerate: PYTHONPATH=. python3 templates/shmup/assets/make_terrain.py",
        "; source-pack: Spaceship Pack (planet_1/2/4/6) — AlcWilliam",
        ";   (examples/itch_cc0/; grant: CC0 — see examples/itch_cc0/LICENSES.md).",
        ";   Four native 48x48 planet sprites BOX-DOWNSCALED to 32x32 (4x4-tile)",
        ";   BG blocks, edge-bled so the smooth shading survives, then quantized to",
        ";   ONE shared 13-colour BG palette. Round silhouettes keep transparent",
        ";   corners so the night sky reads through; main.asm stamps the four",
        ";   blocks across the streamed field. Pre-authored by this generator (the",
        ";   pack ships no tileable terrain — planets are the space-native chunks).",
        f"; planets: {PLANET_DESC}",
        f"; {TILES}x{TILES}-tile blocks x {len(frames)} planets, {n_tiles} unique "
        "tiles (incl. reserved blank #0 + HUD bar), 1 BG palette",
        "; LOAD CONTRACT: sf_load_bg_chr 0, terrain_chr, terrain_chr_bytes",
        "; then sf_load_bg_pals 0, terrain_pal, terrain_pal_count — map words",
        "; already carry tile index (base 0 baked in) and palette bits;",
        "; pass them straight to mset. If you also use sf_text, keep",
        "; base + tiles <= 80 (the font owns BG1 tiles 80-127).",
        "",
        f"terrain_chr_tiles = {n_tiles}",
        f"terrain_chr_bytes = {len(blob)}",
        "terrain_pal_count = 1",
        f"terrain_planet_count = {len(frames)}   ; distinct planet blocks in the strip",
        f"terrain_planet_tiles = {TILES}   ; tiles per planet side (main.asm stamps {TILES}x{TILES})",
        f"terrain_map_w = {TILES}",
        f"terrain_map_h = {TILES * len(frames)}   ; the {len(frames)} blocks stacked into a strip",
        f"terrain_hud_tile = {hud_tile}   ; solid dark bar tile (palette 0 idx "
        f"{HUD_BACK_IDX}); main.asm stamps it on the fixed BG2 HUD band",
        "",
        emit_words("terrain_pal", pal_words),
        "",
        "; strip map: planet p occupies words p*16 .. p*16+15 (4x4, row-major)",
        emit_words("terrain_map", map_words, per_line=TILES),
        "",
        emit_bytes("terrain_chr", blob),
        "",
    ]
    OUT.write_text("\n".join(lines))
    print(f"make_terrain: {len(frames)} planets, {n_tiles} tiles "
          f"({len(blob)} CHR bytes) -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
