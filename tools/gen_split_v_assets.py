#!/usr/bin/env python3
"""gen_split_v_assets — the split_v_fight rail's art, as .bin blobs.

Emits into $(BUILD)/assets:

    sv_stage_chr.bin    9 tiles x 32 B, 4bpp   BG1/BG2 stage (shared by both cameras)
    sv_stage_pal.bin    16 words              BG palette 0
    sv_stage_map.bin    32x32 tilemap         the flat grass-topped dirt floor
    sv_bevel_chr.bin    2 tiles x 32 B, 4bpp  the divider bar (BG3)
    sv_bevel_pal.bin    16 words              BG palette 2 (CGRAM 8..11)
    sv_knight_chr.bin   8192 B, 4bpp          the fighter's TWELVE 32x32 frames
                                              plus the blade's FOUR, OBJ-grid
                                              laid out: one whole name table
    sv_knight_pal_r.bin 16 words              OBJ palette 0 — red team
    sv_knight_pal_b.bin 16 words              OBJ palette 1 — blue team
    sv_blade_pal.bin    16 words              OBJ palette 2 — the blade's own
    sv_hud_chr.bin      2048 B, 4bpp          the second name table: 2 life
                                              segments + the count's glyphs,
                                              16x16
    sv_anim.bin         24 B                  6 anim tables x 4 frames
    sv_anim_meta.bin    12 B                  ...and each one's (len, rate)

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

  * "camelot [version 1.0]" (analogStudios_) — the FIGHTER and the BLADE, and
    these ARE pixel traces: twelve 32x32 cells of arthurPendragon_.png and four
    of excalibur_.png. Both PNGs are the pack's own unmodified files, vendored
    under vendor/art/camelot (docs/92 §5.1), so this path needs no zip and has
    no fallback. The pack's character sheets carry no attack pose by design —
    the weapon sheet carries the swing — which is why an attack here is a body
    pose plus a blade sprite.

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

# The knight's drawn content bottom inside its 32x32 cell: the author frames
# every camelot cell with four transparent rows under the feet. It is what the
# fighters' feet anchor to, and it is CHECKED against the pixels rather than
# restated — see action_sheet.
SV_CONTENT_BOTTOM = 28

# --- the HUD / countdown glyph sheet ----------------------------------------
# BG3 IS THE DIVIDER on this rail, so bg_text (which claims BG3SC/BG34NBA)
# cannot compose and there is no text layer to put a HUD on. Life bars and the
# round-start count are therefore SPRITES, on their own OBJ name table, at the
# 16x16 half of the OBSEL size pair the fighters' 32x32 half comes from.
HUD_BOX = 16
HUD_PER_ROW = 8         # 16x16 frames per pair of grid rows (16 tiles wide)

# The face is the tree's own vendored one — the same .hex the BG font is cut
# from — doubled to 16x16 so a glyph reads at arcade scale. Nothing new is
# imported to draw four digits and five letters.
FONT_HEX = REPO / "vendor" / "fonts" / "unscii-8.hex"
HUD_GLYPHS = "321FIGHT"

# Palette indices, in the fighter's own OBJ palette — so a life bar drawn on
# palette 0 is red and the same tile on palette 1 is blue, with no second copy
# of the art. Index 1 is the knight's outline, which the team recolours carry
# as the TEAM colour; index 8 is the brightest ramp entry (a warm near-white on
# red, cool on blue); index 2 is the darkest body tone.
HUD_TEAM, HUD_DARK, HUD_BODY, HUD_BRIGHT = 1, 2, 4, 8


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

    Returns None when no source art is configured. Kept as the SINGLE-FRAME
    conversion the vendored `sv_knight_chr.bin` was cut from, so the zip path
    still reproduces exactly what is committed under vendor/art/split_v — it is
    the oracle `action_sheet` is checked against, not the shipping path.
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
# the ACTION SHEET — the fighter's frame set, traced from the in-tree pack PNG
# ---------------------------------------------------------------------------
# THE PNG IS IN THE TREE, so this path needs no zip and no fallback: the pack's
# own unmodified `arthurPendragon_.png` is vendored under vendor/art/camelot
# (sha256-matched against its zip member, docs/92 §5.1) because `brawler` reads
# it. Tracing it directly is strictly better provenance than a derived blob —
# the PNG is independent of everything this repo emits, which is what makes the
# rendered-frame comparison in tests/test_split_v_fight.py mean something.
#
# THE CHARACTER SHEETS HAVE NO ATTACK POSE, AND THAT IS THE PACK'S DESIGN, not
# a gap. Its own READ ME maps arthurPendragon_'s rows — idle / run / jump-idle
# / jump-run / turn / hit / death — with no swing among them, because the
# WEAPON carries the attack: `excalibur_.png` ships swing-left, swing-right and
# stab as its own 32x32 frames, meant to be composited over the character. So
# an attack here is a body pose (a braced wind-up and a hard forward lean, out
# of the turn and jump-run rows) plus a BLADE sprite that sweeps, and the
# impact is sold by the defender playing the character sheet's real `hit` row.
#
# ONE SWING ROW, H-FLIPPED for the other side, exactly as the character is.
# The pack draws both directions by hand and they are not quite mirrors —
# measured, 4 to 10 pixels of 1024 per frame — so flipping is a real choice and
# not an assumption: it costs four pixels of asymmetry and buys the four CHR
# frames that let the whole set fit one OBJ name table. The row taken is the
# one whose arc travels the way the right-facing character columns face.
CAMELOT = REPO / "vendor" / "art" / "camelot"
ARTHUR_PNG = CAMELOT / "arthurPendragon_.png"
EXCALIBUR_PNG = CAMELOT / "excalibur_.png"

# (row, col) on the 8x8 grid of 32x32 cells. Columns 0-3 face RIGHT; the
# left-facing quarter (cols 4-7) is not taken, because a fighter facing the
# other way is an OAM H-flip (split_v_obj's facing idiom, half the CHR).
#
# ONE SLOT PER LINE, and the slot index is the position in this list: it is
# what the anim tables below index and what the ASM's SV_F_* names mirror.
ACTION_CELLS = [
    (0, 0),          # 0  idle A          row 0 = idle
    (0, 2),          # 1  idle B
    (1, 0),          # 2  walk 0          row 1 = run
    (1, 1),          # 3  walk 1
    (1, 2),          # 4  walk 2
    (1, 3),          # 5  walk 3
    (3, 1),          # 6  jump            row 3 = jump-idle, legs tucked
    (5, 1),          # 7  lunge wind-up   row 5 = turn; arms out, braced
    (4, 1),          # 8  lunge strike    row 4 = jump-run; the hard forward lean
    (6, 2),          # 9  hit flash       row 6 = hit; the full-body red frame
    (6, 1),          # 10 hit recoil
    (7, 3),          # 11 KO              row 7 = death; the frame lying down
]
FRAME_BOX = 32
FRAMES_PER_GROUP = 4        # 4 frames of 32x32 fill one 64-tile grid group

# The blade, from excalibur_.png's swing row, in the order the SWING plays it:
# the sheet draws the arc left-to-right as a recovery to vertical, so reading
# the columns backwards gives raise -> lean -> arc -> full smear, which is a
# strike. Its own 32x32 box is the CHARACTER's box, so the blade composites at
# the fighter's own screen position with no offset to tune.
# ROW 2, NOT ROW 1, and the difference is visible: the sheet's two swing rows
# sweep opposite ways, and only row 2's arc travels the way the RIGHT-facing
# character columns face. Row 1 built and ran and put the arc behind a fighter
# looking the other way — a perfectly valid sprite, swinging backwards.
WEAPON_CELLS = [(2, 3), (2, 2), (2, 1), (2, 0)]

# ...on its OWN OBJ palette. The knight's 8 colours and the blade's 5 would fit
# one 15-entry palette together, and merging them would re-index every knight
# pixel — the exact drift the vendored oracle exists to catch. A second palette
# costs 16 CGRAM words and keeps the blade's steel and gold as the pack drew
# them, on both teams.
WEAPON_PAL_SLOT = 2         # OBJ palette 2 = CGRAM 160..175

# The anim tables, by state. `rate` is game frames per step; a 1-step table
# holds a pose. The tuple order IS the state index the ASM stores.
ANIM_TABLES = [
    ("idle", [0, 1], 24),
    ("walk", [2, 3, 4, 5], 6),
    ("jump", [6], 60),
    ("attack", [7, 8], 6),
    ("hit", [9, 10], 6),
    ("ko", [11], 60),
]
ANIM_STRIDE = 4             # frames per table in sv_anim.bin
META_STRIDE = 2             # (len, rate) per table in sv_anim_meta.bin


def slot_base_tile(slot):
    """Frame slot -> its top-left tile on the 16-wide OBJ name table.

    A 32x32 sprite reads {N..N+3, N+16..N+19, N+32..N+35, N+48..N+51} —
    hardware-fixed row stride of 16 — so four frames fill one group of four
    grid rows and frame N starts at (N//4)*64 + (N%4)*4.
    """
    return (slot // FRAMES_PER_GROUP) * 64 + (slot % FRAMES_PER_GROUP) * 4


def action_sheet():
    """The fighter's frame set -> (chr blob, palette words, content bottom).

    ONE PALETTE OVER THE WHOLE SET, built from the union of every chosen
    cell's opaque colours. That union is the same 8 colours frame 0 alone
    uses, in the same luminance order, so frame 0's bytes are unchanged by the
    expansion — which is what lets the vendored single-frame blob stand as an
    oracle for this conversion (checked in main).
    """
    sheet = Image.open(ARTHUR_PNG).convert("RGBA")
    cells = []
    for row, col in ACTION_CELLS:
        cell = sheet.crop((col * FRAME_BOX, row * FRAME_BOX,
                           (col + 1) * FRAME_BOX, (row + 1) * FRAME_BOX))
        # png2snes passes an already-boxed frame through untouched ("keep
        # author's framing"), and every camelot cell is exactly the OBJ box —
        # so `box_frame` is a no-op here and is called anyway, through the
        # branch that says so rather than around it.
        cells.append(box_frame(cell, FRAME_BOX, "bottom"))

    allc = set()
    for c in cells:
        allc |= opaque_colors(c)
    words, c2i = build_palette(allc)

    # Sized for the BLADE's four slots too: they follow the body's twelve on
    # the same name table, and the whole sheet is uploaded as one blob.
    total = len(cells) + len(WEAPON_CELLS)
    groups = (total + FRAMES_PER_GROUP - 1) // FRAMES_PER_GROUP
    blob = bytearray(groups * 64 * 32)
    for slot, cell in enumerate(cells):
        rows = index_frame(cell, c2i)
        base = slot_base_tile(slot)
        for ty in range(FRAME_BOX // 8):
            for tx in range(FRAME_BOX // 8):
                tile = [r[tx * 8:(tx + 1) * 8]
                        for r in rows[ty * 8:(ty + 1) * 8]]
                ti = base + ty * 16 + tx
                blob[ti * 32:(ti + 1) * 32] = encode_tile_4bpp(tile)

    # The feet anchor. Every chosen cell must end its drawn pixels on the same
    # row or the fighter's soles would jump between animations; measured here,
    # where the pixels are, and re-asserted in split_v_obj.asm.
    bottoms = {content_bottom(c) for c in cells}
    if bottoms != {SV_CONTENT_BOTTOM}:
        raise SystemExit(
            f"gen_split_v_assets: the action frames' drawn content bottoms are "
            f"{sorted(bottoms)}, not {{{SV_CONTENT_BOTTOM}}} — the feet anchor "
            f"in engine/features/split_v_obj/split_v_obj.asm is derived from "
            f"{SV_CONTENT_BOTTOM}")
    return blob, words, SV_CONTENT_BOTTOM


def weapon_frames(blob, first_slot):
    """Trace the blade's swing into `blob`, from `first_slot` onward.

    Its own palette, built from its own cells — see WEAPON_PAL_SLOT. Returns
    the palette words.
    """
    sheet = Image.open(EXCALIBUR_PNG).convert("RGBA")
    cells = []
    for row, col in WEAPON_CELLS:
        cell = sheet.crop((col * FRAME_BOX, row * FRAME_BOX,
                           (col + 1) * FRAME_BOX, (row + 1) * FRAME_BOX))
        if cell.size != (FRAME_BOX, FRAME_BOX):
            raise SystemExit(f"gen_split_v_assets: excalibur cell {cell.size} "
                             f"is not the {FRAME_BOX}x{FRAME_BOX} OBJ box")
        cells.append(cell)

    allc = set()
    for c in cells:
        allc |= opaque_colors(c)
    words, c2i = build_palette(allc)

    for i, cell in enumerate(cells):
        rows = index_frame(cell, c2i)
        base = slot_base_tile(first_slot + i)
        if base + 3 * 16 + 3 > 255:
            raise SystemExit(f"gen_split_v_assets: blade slot {first_slot + i} "
                             f"runs past the 256-tile OBJ name table")
        for ty in range(FRAME_BOX // 8):
            for tx in range(FRAME_BOX // 8):
                tile = [r[tx * 8:(tx + 1) * 8]
                        for r in rows[ty * 8:(ty + 1) * 8]]
                ti = base + ty * 16 + tx
                blob[ti * 32:(ti + 1) * 32] = encode_tile_4bpp(tile)
    return words


def anim_blobs():
    """The six state tables on a fixed stride, plus their (len, rate) meta.

    Naming a table per state at ASSEMBLE time forces a branch chain in the
    clock AND a second one in the draw. One stride index does both — brawler's
    shape, one rail over. Short tables are padded with their OWN step 0, so
    every byte is a defined tile and the padding is never indexed (the LENGTH
    that bounds the wrap ships beside it).
    """
    frames, meta = bytearray(), bytearray()
    for name, slots, rate in ANIM_TABLES:
        if len(slots) > ANIM_STRIDE:
            raise SystemExit(f"{name}: {len(slots)} steps over the "
                             f"{ANIM_STRIDE}-frame stride")
        row = [slot_base_tile(s) for s in slots]
        row += [row[0]] * (ANIM_STRIDE - len(row))
        if max(row) > 255:
            raise SystemExit(f"{name}: tile {max(row)} past the 8-bit OAM tile "
                             f"byte")
        frames += bytes(row)
        meta += bytes((len(slots), rate))
    return bytes(frames), bytes(meta)


# ---------------------------------------------------------------------------
# the HUD sheet — 16x16 frames on the second OBJ name table
# ---------------------------------------------------------------------------

def hud_slot_base_tile(slot):
    """HUD frame slot -> its top-left tile, RELATIVE to the second name table.

    A 16x16 sprite reads {N, N+1, N+16, N+17}, so two grid rows hold eight
    frames and slot N starts at (N//8)*32 + (N%8)*2.
    """
    return (slot // HUD_PER_ROW) * 32 + (slot % HUD_PER_ROW) * 2


def font_glyphs():
    """The doubled 8x8 face -> {char: 16 rows of 16 booleans}."""
    rows_by_cp = {}
    for ln in FONT_HEX.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        code, _, data = ln.partition(":")
        rows_by_cp[int(code, 16)] = [int(data[i:i + 2], 16)
                                     for i in range(0, 16, 2)]
    out = {}
    for ch in HUD_GLYPHS:
        src = rows_by_cp.get(ord(ch))
        if src is None:
            raise SystemExit(f"gen_split_v_assets: '{ch}' is not in "
                             f"{FONT_HEX.name}")
        doubled = []
        for byte in src:
            row = [bool(byte & (1 << (7 - x))) for x in range(8)]
            wide = [v for v in row for _ in range(2)]
            doubled += [wide, list(wide)]
        out[ch] = doubled
    return out


def glyph_frame(mask):
    """A doubled glyph -> a 16x16 index frame: bright body, team-colour outline.

    The outline is derived from the mask rather than authored, so every glyph
    gets the same treatment and none can be missed. It matters at this size:
    a bare bright glyph over the pale sky is nearly invisible, and the count is
    the one thing on screen a player must read in a third of a second.
    """
    out = [[0] * HUD_BOX for _ in range(HUD_BOX)]
    for y in range(HUD_BOX):
        for x in range(HUD_BOX):
            if mask[y][x]:
                out[y][x] = HUD_BRIGHT
                continue
            near = any(mask[y + dy][x + dx]
                       for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                       if 0 <= y + dy < HUD_BOX and 0 <= x + dx < HUD_BOX)
            if near:
                out[y][x] = HUD_TEAM
    return out


def life_frame(full):
    """One life-bar segment, 16x16: a filled pip or an empty socket.

    Both carry the same team-colour border, so a spent segment still marks its
    place — a bar that simply loses cells reads as a shorter bar, not as
    damage.
    """
    out = [[0] * HUD_BOX for _ in range(HUD_BOX)]
    for y in range(3, 13):
        for x in range(1, 15):
            edge = y in (3, 12) or x in (1, 14)
            if edge:
                out[y][x] = HUD_TEAM
            elif not full:
                out[y][x] = HUD_DARK
            else:
                out[y][x] = HUD_BRIGHT if y == 4 else HUD_BODY
    return out


def hud_sheet():
    """The 16x16 glyph frames, laid out on their own name table.

    Slot order is the vocabulary the ASM's SV_H_* names mirror. Unused slots
    are BLANK rather than absent — the claim is a whole grid group either way,
    and a defined blank tile is what rule 5 asks for over whatever the linker
    left.
    """
    glyphs = font_glyphs()
    frames = [life_frame(True), life_frame(False)]
    frames += [glyph_frame(glyphs[ch]) for ch in HUD_GLYPHS]
    if len(frames) > HUD_PER_ROW * 2:
        raise SystemExit(f"gen_split_v_assets: {len(frames)} HUD frames over "
                         f"the {HUD_PER_ROW * 2}-frame sheet")
    blob = bytearray(64 * 32)               # 4 grid rows = 16 frames
    for slot, pix in enumerate(frames):
        base = hud_slot_base_tile(slot)
        for ty in range(HUD_BOX // 8):
            for tx in range(HUD_BOX // 8):
                tile = [r[tx * 8:(tx + 1) * 8]
                        for r in pix[ty * 8:(ty + 1) * 8]]
                ti = base + ty * 16 + tx
                blob[ti * 32:(ti + 1) * 32] = encode_tile_4bpp(tile)
    return bytes(blob), len(frames)


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

    # --- the fighter's frame set, from the in-tree pack PNG ------------------
    # No fallback and none needed: vendor/art/camelot/arthurPendragon_.png is
    # the pack's own unmodified file, committed here (docs/92 §5.1), so a bare
    # checkout has the source rather than a derivative of it.
    chr_blob, _pack_words, bottom = action_sheet()
    notes.append(f"knight CHR: {len(ACTION_CELLS)} frames traced from "
                 f"{ARTHUR_PNG.name}, content_bottom = {bottom} "
                 f"(feet anchor: y = surface_top - {bottom})")
    blade_pal = weapon_frames(chr_blob, len(ACTION_CELLS))
    notes.append(f"blade CHR: {len(WEAPON_CELLS)} frames traced from "
                 f"{EXCALIBUR_PNG.name} into slots "
                 f"{len(ACTION_CELLS)}..{len(ACTION_CELLS)+len(WEAPON_CELLS)-1}"
                 f", {sum(1 for w in blade_pal if w)} palette entries")

    # THE VENDORED SINGLE-FRAME BLOB IS THE ORACLE for that trace. It was cut
    # from the same PNG by the zip path above, before the frame set existed,
    # and slot 0 still sits at grid origin — so the expanded sheet must carry
    # byte-identical pixels in the sixteen TILES that frame occupies. It is the
    # cheapest possible guard on the one thing a multi-frame conversion can
    # silently change: the palette's luminance ORDER, which would re-index
    # every pixel while leaving the byte count, the colour count and the
    # picture's shape all correct.
    #
    # THE SIXTEEN TILES, NOT THE FIRST 2048 BYTES. Slot 0's tiles are
    # {0..3, 16..19, 32..35, 48..51} and slots 1-3 fill the gaps between them
    # in the same 64-tile group, so a prefix compare reads three other frames'
    # pixels as drift. It fired exactly that way when this was first written —
    # which is the gate doing its job on the check rather than on the art.
    oracle = vendored("sv_knight_chr.bin")
    if oracle is not None:
        for ty in range(FRAME_BOX // 8):
            for tx in range(FRAME_BOX // 8):
                ti = ty * 16 + tx
                if chr_blob[ti * 32:(ti + 1) * 32] != oracle[ti * 32:(ti + 1) * 32]:
                    raise SystemExit(
                        f"gen_split_v_assets: the frame set's slot 0 no longer "
                        f"reproduces the vendored single-frame trace of the "
                        f"same PNG (tile {ti}) — the palette order or the grid "
                        f"layout moved. Re-vendor deliberately; do not let "
                        f"this drift silently.")
    notes.append("knight CHR: slot 0 byte-matches the vendored single-frame trace")

    # The zip path stays reachable, and re-derives that same oracle from the
    # ORIGINAL archive when one is configured — so `SF_SOURCE_ART_DIR` still
    # checks the vendored copy against the pack rather than against us.
    traced = knight_chr_from_pack()
    if traced is None and args.require_source_art:
        raise SystemExit("gen_split_v_assets: --require-source-art, but the "
                         f"pack holding {KNIGHT_ZIP} is not under SF_SOURCE_ART_DIR")
    if traced is not None:
        if oracle is not None and traced[0] != oracle:
            raise SystemExit(
                "gen_split_v_assets: the vendored knight CHR disagrees with a "
                "fresh trace of the pack zip — one of them is stale. Re-vendor "
                "deliberately; do not let this drift silently.")
        notes.append("knight CHR: the vendored oracle re-derived from the pack zip")

    write(out / "sv_knight_chr.bin", bytes(chr_blob), made)
    write(out / "sv_knight_pal_r.bin", pal16(KNIGHT_PAL_RED), made)
    write(out / "sv_knight_pal_b.bin", pal16(KNIGHT_PAL_BLUE), made)
    write(out / "sv_blade_pal.bin", pal16(blade_pal), made)

    # --- the anim tables and the HUD sheet -----------------------------------
    anim, anim_meta = anim_blobs()
    write(out / "sv_anim.bin", anim, made)
    write(out / "sv_anim_meta.bin", anim_meta, made)
    hud, n_hud = hud_sheet()
    write(out / "sv_hud_chr.bin", hud, made)
    notes.append(f"HUD sheet: {n_hud} 16x16 frames (2 life segments + "
                 f"{len(HUD_GLYPHS)} glyphs from {FONT_HEX.name})")

    print("gen_split_v_assets: " + ", ".join(made))
    for n in notes:
        print("  " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
