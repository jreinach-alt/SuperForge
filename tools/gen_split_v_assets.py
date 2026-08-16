#!/usr/bin/env python3
"""gen_split_v_assets — the split_v_fight rail's art, as .bin blobs.

Emits into $(BUILD)/assets:

    sv_stage_chr.bin    9 tiles x 32 B, 4bpp   BG1/BG2 stage (shared by both cameras)
    sv_stage_pal.bin    16 words              BG palette 0
    sv_stage_map.bin    32x32 tilemap         the flat grass-topped dirt floor
    sv_bevel_chr.bin    2 tiles x 32 B, 4bpp  the divider bar (BG3)
    sv_bevel_pal.bin    16 words              BG palette 2 (CGRAM 8..11)
    sv_knight_chr.bin   2048 B, 4bpp          one 32x32 fighter, OBJ-grid laid out
    sv_knight_pal_r.bin 16 words              OBJ palette 0 — red team
    sv_knight_pal_b.bin 16 words              OBJ palette 1 — blue team

PROVENANCE, and why two of these are traced and one is not.

Two registered art packs feed this rail, and they are NOT under the same grant.
Per-pack grants are in this repo's NOTICE (camelot is CC0; the Four Seasons
tileset carries Rotting Pixels' own permissive grant, which is not CC0).

  * "Four Seasons Platformer Tileset [16x16][FREE]" (Rotting Pixels) — the
    STAGE, and only its PALETTE is taken from the pack. The 9 stage tiles are
    AUTHORED procedurally against that palette (seeded, deterministic). The
    pack's own pixels are never traced into stage CHR, so "ground-truth the
    converter against a hardware render" reduces here to "the palette matches
    and the authored tiles reproduce" — both checked in
    tests/test_split_v_fight.py.

  * "camelot [version 1.0]" (analogStudios_) — the FIGHTER, and this one IS a
    pixel trace of arthurPendragon_.png frame 0 at 32x32, anchor bottom.

The converter is ground-truthed against a hardware render, never against a
re-rendering of this script's own output; see tests/test_split_v_fight.py.

THE PACK ZIPS ARE NOT VENDORED, and the normal build does not need them. The
vendored palette + CHR under vendor/art/split_v/ are what this generator emits
by default, so a bare runner with nothing else on disk builds. Point
SF_SOURCE_ART_DIR at a directory holding the original pack zips to re-derive
them from source instead; when it is set,
the vendored blobs are byte-checked against the fresh conversion, so they
cannot drift silently.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import zipfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "vendor" / "art" / "split_v"

# Optional source-art directory, read-only and never a build dependency: the
# vendored blobs under vendor/art/split_v/ are the default and the shipping
# path. Set SF_SOURCE_ART_DIR to re-derive from the original pack zips.
SOURCE_ART_DIR = os.environ.get("SF_SOURCE_ART_DIR", "")
REFERENCE_CANDIDATES = [Path(SOURCE_ART_DIR)] if SOURCE_ART_DIR else []
STAGE_ZIP = "Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels.zip"
KNIGHT_ZIP = "camelot_ [version 1.0].zip"
STAGE_REGION = (0, 0, 16, 32)     # the grass-block-over-dirt-block column

# The rail's band-safe CGRAM order. The derived pack palette must land in
# exactly this order or the authored CHR mis-colours; asserted, not assumed.
EXPECTED_STAGE_PAL = [0x0000, 0x14A6, 0x1D0E, 0x1DE3, 0x21D7,
                      0x1B0B, 0x329B, 0x2373]

# CGRAM word 0 is the BACKDROP -- the colour the PPU shows where every layer is
# transparent, which on this stage is the whole sky. build_palette puts a
# nominal $0000 at index 0 because for a 4bpp LAYER index 0 means "transparent
# and the value is unused"; that is true of the layer and false of word 0, and
# leaving it black renders a night sky under a daylit floor. The equivalent
# runtime form is `sf_bg_color 0, 0` with this same value.
SKY_BGR15 = 0x6E64

# palette-index roles in the derived (luminance-sorted) order
OUTLINE, DIRT_SHADOW, GRASS_DARK, DIRT_MID = 1, 2, 3, 4
GRASS_BRIGHT, DIRT_LIGHT, GRASS_LIGHT = 5, 6, 7

# The two team palettes: hand-authored band-safe recolours of the pack's own
# knight ramp. Kept as literals because they are
# authored values, not derived ones — deriving them would invent a rule that
# was never applied.
KNIGHT_PAL_RED = [0x0000, 0x14B4, 0x14EC, 0x18D9, 0x211C,
                  0x1E9C, 0x331E, 0x4ADD, 0x675E]
KNIGHT_PAL_BLUE = [0x0000, 0x50A5, 0x30E5, 0x64C6, 0x7108,
                   0x1E9C, 0x331E, 0x4ADD, 0x7B59]

# The bevel divider: shadow / mid / highlight, matched to the RENDERED output
# rather than to a value quoted in a comment.
#
# This started as [$0000, $0CA9, $4E73, $7FFF]. $0CA9 is a real number from a
# comment about what the band-safety PROBE reads at the seam -- not the bevel's
# shadow. It is a warm brown, (74,41,24) on hardware, and the published capture
# renders the divider as (49,49,49) / (156,156,156) / (255,255,255): a NEUTRAL
# grey bevel. Measuring the artefact beat quoting the prose.
BEVEL_PAL = [0x0000, 0x18C6, 0x4E73, 0x7FFF]
BV_OUTLINE, BV_MID, BV_HILITE = 1, 2, 3

FLOOR_ROW = 22          # tilemap row of the grass surface (px 176)
MAP_W = MAP_H = 32


# ---------------------------------------------------------------------------
# png2snes's primitives, restated. The build must work with nothing but this
# tree on disk, so these are written out rather than imported; each is small
# and exactly specified.
# ---------------------------------------------------------------------------

def rgb_to_bgr15(rgb):
    r, g, b = rgb
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def rgba_pixels(img):
    raw = img.tobytes()
    return [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]


def opaque_colors(img):
    return {p[:3] for p in rgba_pixels(img) if p[3] >= 128}


def build_palette(colors):
    """Index 0 transparent; 1..15 sorted by luminance then RGB."""
    ordered = sorted(colors,
                     key=lambda c: (c[0] * 299 + c[1] * 587 + c[2] * 114, c))
    pal = [(0, 0, 0)] + ordered
    c2i = {c: i + 1 for i, c in enumerate(ordered)}
    words = [rgb_to_bgr15(c) for c in pal] + [0] * (16 - len(pal))
    return words, c2i


def encode_tile_4bpp(pix):
    """8x8 rows of indices 0..15 -> 32 B SNES 4bpp planar.

    NEVER masks. The parent repo's silent `& 0x03` quantisation is the
    canonical scar (SuperForge CLAUDE.md, "Silent Bitwise-AND Quantisation");
    an out-of-range index is an encoder bug and must say so.
    """
    out = bytearray(32)
    for y in range(8):
        b0 = b1 = b2 = b3 = 0
        for x in range(8):
            v = pix[y][x]
            assert 0 <= v <= 15, f"palette index {v} out of 4bpp range"
            bit = 7 - x
            b0 |= ((v >> 0) & 1) << bit
            b1 |= ((v >> 1) & 1) << bit
            b2 |= ((v >> 2) & 1) << bit
            b3 |= ((v >> 3) & 1) << bit
        out[y * 2], out[y * 2 + 1] = b0, b1
        out[16 + y * 2], out[16 + y * 2 + 1] = b2, b3
    return bytes(out)


def index_frame(img, c2i):
    w, h = img.size
    data = rgba_pixels(img)
    return [[c2i[data[y * w + x][:3]] if data[y * w + x][3] >= 128 else 0
             for x in range(w)] for y in range(h)]


def box_frame(img, size, anchor):
    """Fit the frame's opaque content into a size x size box.

    THE GUARD IS THE POINT (png2snes.py cmd_sprite:372-376): a frame that is
    ALREADY size x size is passed through untouched — "keep author's framing".
    Only an off-size frame is recentred, and only then does `anchor` do
    anything.

    This rail's knight is cut from a 256x256 sheet on a 32x32 grid, so every
    frame arrives exactly 32x32 and **`--anchor bottom` in the recorded
    conversion command is INERT**. Recentring it anyway pushes the art 4 px
    down and re-centres it horizontally — a silently different sprite that
    still has the right palette and the right byte count.

    That is the `recenter` trap wearing a new costume: there
    the anchor inverted what the artist drew, here the anchor is not applied
    at all and the command line says it is. The `.inc` header's `cmd:` line is
    SECONDARY evidence; the converter is primary (CLAUDE.md, "if you are about
    to state what a tool does, open the tool"). Caught by byte-diffing this
    conversion against the committed reference blob, which is why that diff is
    a test.
    """
    if img.size == (size, size):
        return img
    a = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    bbox = a.getbbox()
    if bbox is None:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x0, y0, x1, y1 = bbox
    cw, ch = x1 - x0, y1 - y0
    if cw > size or ch > size:
        raise SystemExit(f"gen_split_v_assets: frame content {cw}x{ch} "
                         f"exceeds the {size}x{size} box")
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img.crop(bbox),
              ((size - cw) // 2, (size - ch) if anchor == "bottom" else 0))
    return out


def content_bottom(img):
    """Lowest drawn row + 1, inside the box.

    The fighters' FEET anchor to this, not to the box height: the art does not
    fill its cell, and clamping to the box edge leaves the empty bottom rows
    as a visible gap under each fighter. 28 is this knight's number.
    """
    a = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    bb = a.getbbox()
    return bb[3] if bb else 0


# ---------------------------------------------------------------------------
# optional source art (SF_SOURCE_ART_DIR)
# ---------------------------------------------------------------------------

def reference_zip(name):
    """Locate a registered art pack, or None when no source art is configured."""
    for base in REFERENCE_CANDIDATES:
        p = base / "examples" / "itch_cc0" / name
        if p.exists():
            return p
    return None


def stage_palette_from_pack():
    """The 8-colour stage ramp, derived from the pack region png2snes read.

    Returns None when no source art is configured so the caller can fall back.
    """
    zp = reference_zip(STAGE_ZIP)
    if zp is None:
        return None
    with zipfile.ZipFile(zp) as zf:
        name = next(n for n in zf.namelist()
                    if n.endswith("four-seasons-tileset.png"))
        with zf.open(name) as fh:
            img = Image.open(fh).convert("RGBA").copy()
    x, y, w, h = STAGE_REGION
    words, _ = build_palette(opaque_colors(img.crop((x, y, x + w, y + h))))
    if words[:len(EXPECTED_STAGE_PAL)] != EXPECTED_STAGE_PAL:
        raise SystemExit(
            "gen_split_v_assets: the derived stage palette drifted from the "
            "rail's band-safe order\n"
            f"  derived : {[f'${w:04X}' for w in words[:8]]}\n"
            f"  expected: {[f'${w:04X}' for w in EXPECTED_STAGE_PAL]}")
    return words


def knight_chr_from_pack():
    """Trace arthurPendragon_.png frame 0 -> (2048 B CHR, 16 palette words).

    Returns None when no source art is configured.
    """
    zp = reference_zip(KNIGHT_ZIP)
    if zp is None:
        return None
    with zipfile.ZipFile(zp) as zf:
        name = next(n for n in zf.namelist()
                    if n.endswith("arthurPendragon_.png"))
        with zf.open(name) as fh:
            sheet = Image.open(fh).convert("RGBA").copy()
    # collect_frames cuts the sheet on the 32x32 grid, row-major, SKIPPING
    # empty cells; frame 0 is the first non-empty one (r0c0 for this sheet).
    frame = box_frame(sheet.crop((0, 0, 32, 32)), 32, "bottom")
    words, c2i = build_palette(opaque_colors(frame))
    rows = index_frame(frame, c2i)
    bottom = content_bottom(frame)

    # OBJ VRAM is a 16-tile-wide grid and a 32x32 sprite reads its lower tile
    # rows +16 tile numbers away (hardware-fixed). One frame at grid origin
    # therefore occupies tiles {0..3, 16..19, 32..35, 48..51} of a 64-tile
    # block -> 2048 B, most of it the padding that keeps the rows aligned.
    blob = bytearray(64 * 32)
    for ty in range(4):
        for tx in range(4):
            tile = [row[tx * 8:(tx + 1) * 8]
                    for row in rows[ty * 8:(ty + 1) * 8]]
            slot = ty * 16 + tx
            blob[slot * 32:(slot + 1) * 32] = encode_tile_4bpp(tile)
    return bytes(blob), words, bottom


# ---------------------------------------------------------------------------
# authored tiles — deterministic, seeded, no pack pixels involved
# ---------------------------------------------------------------------------

def dirt_tile(seed):
    """8x8 speckled dirt that tiles in BOTH directions: a filled idx4 field
    with scattered specks touches no edge structurally, so it wraps cleanly.
    Two seeds give the column-parity pair, breaking repeat banding."""
    rng = random.Random(seed)
    t = [[DIRT_MID] * 8 for _ in range(8)]
    cells = [(x, y) for y in range(8) for x in range(8)]
    rng.shuffle(cells)
    for x, y in cells[:7]:
        t[y][x] = DIRT_SHADOW
    for x, y in cells[7:13]:
        t[y][x] = DIRT_LIGHT
    return t


def grass_tile(seed):
    """The grass surface: an idx1 lip on the very top row (the real
    top-of-ground edge), blades below, melting into the dirt body."""
    rng = random.Random(seed)
    t = dirt_tile(seed ^ 0x5A5A)
    for x in range(8):
        t[0][x] = OUTLINE
    for y, tone in ((1, GRASS_LIGHT), (2, GRASS_BRIGHT), (3, GRASS_DARK)):
        for x in range(8):
            t[y][x] = tone if rng.random() < 0.8 else GRASS_BRIGHT
    return t


def bevel_tiles():
    """The divider bar: a 3-tone vertical bevel, 2 tiles tall so the band can
    repeat down the screen. Column 0 highlight, 1..6 mid, 7 shadow-outline —
    read left-to-right it reads as a lit edge, a body and a shadowed edge."""
    def col(x):
        return BV_HILITE if x == 0 else (BV_OUTLINE if x == 7 else BV_MID)
    tile = [[col(x) for x in range(8)] for _ in range(8)]
    return [tile, tile]


def stage_tiles():
    """9 tiles: 0 = transparent sky, 1-2 grass parity pair, 3-8 dirt body."""
    sky = [[0] * 8 for _ in range(8)]
    tiles = [sky, grass_tile(0xA11CE), grass_tile(0xB0B)]
    for i in range(6):
        tiles.append(dirt_tile(0xD1E7 + i))
    return tiles


def stage_map():
    """32x32 tilemap words: sky above FLOOR_ROW, one grass row, dirt below.
    Column parity picks the tile of each authored pair, so the floor does not
    visibly repeat at an 8px pitch."""
    words = []
    for row in range(MAP_H):
        for col in range(MAP_W):
            if row < FLOOR_ROW:
                t = 0
            elif row == FLOOR_ROW:
                t = 1 + (col & 1)
            else:
                t = 3 + ((col + row) % 6)
            words.append(t)
    return words


# ---------------------------------------------------------------------------

def w2b(words):
    out = bytearray()
    for w in words:
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def pal16(words):
    return w2b(list(words) + [0] * (16 - len(words)))


def write(path: Path, blob: bytes, made):
    path.write_bytes(blob)
    made.append(f"{path.name} ({len(blob)} B)")


def vendored(name):
    p = VENDOR / name
    return p.read_bytes() if p.exists() else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("outdir")
    ap.add_argument("--require-source-art", action="store_true",
                    help="fail instead of falling back to vendor/art/split_v")
    args = ap.parse_args(argv)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    made, notes = [], []

    # --- stage palette: derived from the pack, or the vendored copy ---------
    pack_pal = stage_palette_from_pack()
    if pack_pal is None:
        if args.require_source_art:
            raise SystemExit("gen_split_v_assets: --require-source-art, but the "
                             f"pack holding {STAGE_ZIP} is not under SF_SOURCE_ART_DIR")
        blob = vendored("sv_stage_pal.bin")
        if blob is None:
            raise SystemExit("gen_split_v_assets: no source art and no vendored "
                             "stage palette — cannot build")
        notes.append("stage palette: VENDORED (no source art)")
    else:
        pack_pal = list(pack_pal)
        pack_pal[0] = SKY_BGR15          # the backdrop; see SKY_BGR15
        blob = pal16(pack_pal)
        v = vendored("sv_stage_pal.bin")
        if v is not None and v != blob:
            raise SystemExit(
                "gen_split_v_assets: the vendored stage palette disagrees with "
                "a fresh conversion from the pack — one of them is stale. "
                "Re-vendor deliberately; do not let this drift silently.")
        notes.append("stage palette: derived from the pack")
    write(out / "sv_stage_pal.bin", blob, made)

    # --- authored stage CHR + map ------------------------------------------
    write(out / "sv_stage_chr.bin",
          b"".join(encode_tile_4bpp(t) for t in stage_tiles()), made)
    write(out / "sv_stage_map.bin", w2b(stage_map()), made)

    # --- the divider --------------------------------------------------------
    write(out / "sv_bevel_chr.bin",
          b"".join(encode_tile_4bpp(t) for t in bevel_tiles()), made)
    write(out / "sv_bevel_pal.bin", pal16(BEVEL_PAL), made)

    # --- the fighter --------------------------------------------------------
    traced = knight_chr_from_pack()
    if traced is None:
        if args.require_source_art:
            raise SystemExit("gen_split_v_assets: --require-source-art, but the "
                             f"pack holding {KNIGHT_ZIP} is not under SF_SOURCE_ART_DIR")
        chr_blob = vendored("sv_knight_chr.bin")
        if chr_blob is None:
            raise SystemExit("gen_split_v_assets: no source art and no vendored "
                             "knight CHR — cannot build")
        notes.append("knight CHR: VENDORED (no source art)")
    else:
        chr_blob, _pack_words, bottom = traced
        notes.append(f"knight content_bottom = {bottom} "
                     f"(feet anchor: y = surface_top - {bottom})")
        v = vendored("sv_knight_chr.bin")
        if v is not None and v != chr_blob:
            raise SystemExit(
                "gen_split_v_assets: the vendored knight CHR disagrees with a "
                "fresh trace of the pack PNG — one of them is stale. Re-vendor "
                "deliberately; do not let this drift silently.")
        notes.append("knight CHR: traced from the pack PNG")
    write(out / "sv_knight_chr.bin", chr_blob, made)
    write(out / "sv_knight_pal_r.bin", pal16(KNIGHT_PAL_RED), made)
    write(out / "sv_knight_pal_b.bin", pal16(KNIGHT_PAL_BLUE), made)

    print("gen_split_v_assets: " + ", ".join(made))
    for n in notes:
        print("  " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
