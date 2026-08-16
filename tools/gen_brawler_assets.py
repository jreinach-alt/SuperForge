#!/usr/bin/env python3
"""gen_brawler_assets.py — the `brawler` rail's art, from the ORIGINAL pack PNGs.

Emits into `build/assets` (byte-identical on re-run — every step below is
integer math over vendored bytes, and nothing consults a dict iteration order,
a float, a clock or a PRNG):

  br_art_chr.bin    8192 B  Arthur: 16 frames @ 32x32 on the 16-wide OBJ VRAM
                            grid = 256 tiles x 32 B 4bpp. EXACTLY one OBJ name
                            table
  br_art_pal.bin      32 B  16 BGR555 words -- OBJ palette 0 (CGRAM 128..143)
  br_mor_chr.bin    6144 B  Mordred: 12 frames = 192 tiles
  br_mor_pal.bin      32 B  16 words -- OBJ palette 1 (CGRAM 144..159)
  br_bg_chr.bin     1568 B  49 unique 4bpp BG tiles (blank #0 reserved first)
  br_bg_pal.bin       32 B  16 words -- BG palette group 0 (word 0 = backdrop)
  br_bg_map.bin       96 B  the 8x6 = 48-word terrain PATCH the floor tiles
  br_anim.bin         40 B  5 animation tables x 8-byte stride
  br_anim_meta.bin    10 B  the same 5 tables x (len, rate)

SOURCE = THE PACK'S OWN PNGs, NOT DERIVED .inc BLOBS. That is the
whole reason this generator looks the way it does. CLAUDE.md's asset-import
rule says a converter that byte-traces a *derived* asset must be ground-truthed
against a render it did not produce, because checking it against your own
re-rendering of your own output is a tautology — and that tautology has shipped
visibly broken art on this project. Reading `vendor/art/camelot/*.png` and
`vendor/art/four_seasons_tileset/*.png` removes the trap at its root: the PNG is
independent of everything this repo produces, so `tests/test_brawler.py` can
compare the RENDERED SNES FRAME back to it and the comparison means something.

MATCHING THE COMMITTED REFERENCE CONVERSION. Every step below reproduces a
specific branch of a `png2snes.py` conversion, and the result is byte-identical
to the three vendored `ref_*.inc` fixtures — `tests/test_brawler.py` asserts
exactly that. The reproductions worth naming, because each is a place a
from-scratch converter would land somewhere else:

  * THE PALETTE ORDER is luminance-then-RGB with index 0 reserved transparent
    (`build_palette`). Not "sorted by first appearance", which
    is what a from-scratch converter reaches for and which would move every
    pixel's index.
  * RE-CENTRING IS SKIPPED for a frame that already measures exactly the OBJ
    box ("already exact; keep author's framing"). The camelot
    cells are 32x32 and the box is 32x32, so the author's framing survives —
    including the FOUR TRANSPARENT ROWS UNDER THE FEET that put the drawn
    content bottom at row 28. That number anchors the rail's lane band; a
    converter that "helpfully" re-centred would report 24 and the knights would
    float 4 px above the floor.
  * A "COLLECTED" FRAME IS A NON-EMPTY CELL. Empty cells are
    skipped before the --anims ranges are applied, so a collected index is NOT
    `row*8 + col` on a sheet with gaps. Mordred's sheet has them; his ranges
    only line up if the skip happens first.
  * THE OBJ VRAM GRID IS 16 TILES WIDE and a 32x32 frame is a 4x4 block whose
    rows sit +16 tile numbers apart — hardware, not a choice (the PPU fetches
    tile `(row+dy)&15 << 4 | (col+dx)&15`; Mesen2 SnesPpu.cpp:739). Frames pack
    four per grid row-group, so frame N's top-left tile is
    `(N//4)*64 + (N%4)*4` — the $00/$04/$08/$0C, $40.., $80.., $C0.. ladder in
    the anim tables.
  * THE BG PATH dedupes 8x8 cells against a cache seeded with a RESERVED BLANK
    at index 0 and bakes the palette group into the map word.
    The converted 64x48 region needs ONE palette (12 colours), so
    a best-fit-decreasing `group_palettes` provably collapses to a
    single group whose colour set is the union — asserted below rather than
    reimplemented.

THE ANIMATION TABLES ARE A BLOB, ON A FIXED STRIDE. A per-animation table of
base-relative tile offsets named at ASSEMBLE time
(`sf_anim_tile arthur_anim_run, AFRAME`) forces a
three-way branch dispatch in the draw and a second one in the clock. SuperForge has
no such macro and the tables are ROM like everything else, so they go out as
one blob on an 8-byte stride indexed by the anim-state word: state 0/1/2 are
Arthur's idle/run/hit, 3/4 are Mordred's idle/run. Same bytes, same visible
cycle, no dispatch. Short tables are padded with their own frame 0 — explicit,
never left uninitialised (rule 5) — and the padding is never indexed because
the LENGTH that bounds the wrap ships beside it in br_anim_meta.

Usage:  python3 tools/gen_brawler_assets.py [outdir]      (default build/assets)
"""

import sys
from pathlib import Path

from PIL import Image

ART = Path(__file__).resolve().parent.parent / "vendor" / "art"
CAMELOT = ART / "camelot"
TILESET = ART / "four_seasons_tileset"

# --- the two sprite conversions, and their arguments ------------------------
# sprite <png> --frame 32x32 --size 32 --anims <spec> --name <n>
SPRITE_BOX = 32
ARTHUR_ANIMS = "idle:0-3,run:8-11+16-19,hit:48-51"
MORDRED_ANIMS = "idle:8-11,run:16-19+24-27"

# --- the BG conversion (bg <png> --region 0,0,64,48) ------------------------
BG_REGION = (0, 0, 64, 48)

# --- animation clock metadata ----------------------------------------------
# (table key, rate) in stride order. The RATE is game frames per animation
# step; the LEN comes from the table itself.
#   arthur idle/run/hit  -> rates 8, 6, 4
#   mordred (one clock)  -> rate 8, len forced to 4
# Mordred keeps ONE clock length for both tables — his run table is 8 steps but
# the clock steps it at len 4: run uses steps 0-3 of 8, and one clock length
# avoids a reset on every stun flicker.
ANIM_ORDER = [
    ("arthur", "idle", 8, None),
    ("arthur", "run", 6, None),
    ("arthur", "hit", 4, None),
    ("mordred", "idle", 8, None),
    ("mordred", "run", 8, 4),
]
ANIM_STRIDE = 8


# ---------------------------------------------------------------------------
# png2snes primitives, reproduced
# ---------------------------------------------------------------------------

def _rgba(img):
    """RGBA image -> flat list of (r,g,b,a) tuples."""
    raw = img.tobytes()
    return [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]


def _opaque_colors(img):
    """Distinct opaque (alpha>=128) RGB colours."""
    return {p[:3] for p in _rgba(img) if p[3] >= 128}


def _bgr15(rgb):
    r, g, b = rgb
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def build_palette(colors, label):
    """Index 0 transparent, 1..15 sorted by luminance then RGB.

    png2snes.py:157. The luminance key is integer (299/587/114 weights), so the
    order is exact and reproducible; the RGB tuple breaks ties.
    """
    if len(colors) > 15:
        raise SystemExit(f"{label}: {len(colors)} opaque colours; an SNES "
                         f"palette holds 15 + transparent")
    ordered = sorted(colors, key=lambda c: (c[0] * 299 + c[1] * 587 + c[2] * 114, c))
    words = [_bgr15((0, 0, 0))] + [_bgr15(c) for c in ordered]
    words += [0] * (16 - len(words))
    return words, {c: i + 1 for i, c in enumerate(ordered)}


def encode_tile_4bpp(pix, label):
    """8x8 rows of palette indices -> 32 B SNES 4bpp planar.

    NEVER masks: an index outside 0..15 is a converter bug and is raised, not
    silently quantised (the parent repo's `& 0x03` scar).
    """
    out = bytearray(32)
    for y in range(8):
        b0 = b1 = b2 = b3 = 0
        for x in range(8):
            v = pix[y][x]
            if not 0 <= v <= 15:
                raise SystemExit(f"{label}: palette index {v} out of 4bpp range")
            bit = 7 - x
            b0 |= ((v >> 0) & 1) << bit
            b1 |= ((v >> 1) & 1) << bit
            b2 |= ((v >> 2) & 1) << bit
            b3 |= ((v >> 3) & 1) << bit
        out[y * 2] = b0
        out[y * 2 + 1] = b1
        out[16 + y * 2] = b2
        out[16 + y * 2 + 1] = b3
    return bytes(out)


def index_image(img, c2i):
    """RGBA image -> rows of palette indices (transparent -> 0)."""
    w, h = img.size
    d = _rgba(img)
    return [[c2i[d[y * w + x][:3]] if d[y * w + x][3] >= 128 else 0
             for x in range(w)] for y in range(h)]


def encode_pal(words):
    out = bytearray()
    for w in words:
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def encode_words(words):
    return encode_pal(words)


# ---------------------------------------------------------------------------
# sprite conversion
# ---------------------------------------------------------------------------

def collect_frames(png, box):
    """Cut a sheet into `box`x`box` cells row-major, SKIPPING EMPTY ones.

    png2snes.py:198. The skip is what makes a "collected frame index" differ
    from `row*cols + col` on a sheet with gaps, and Mordred's has gaps.
    """
    img = Image.open(png).convert("RGBA")
    w, h = img.size
    if w % box or h % box:
        raise SystemExit(f"{png.name}: {w}x{h} does not divide into {box}x{box}")
    out = []
    for fy in range(h // box):
        for fx in range(w // box):
            cell = img.crop((fx * box, fy * box, (fx + 1) * box, (fy + 1) * box))
            if cell.getchannel("A").getbbox():
                out.append(cell)
    return out


def parse_anims(spec):
    """--anims "idle:0-3,run:8-11+16-19" -> {name: [collected indices]}."""
    out = {}
    for part in spec.split(","):
        name, ranges = part.split(":")
        idxs = []
        for rng in ranges.split("+"):
            a, b = (int(v) for v in rng.split("-"))
            idxs.extend(range(a, b + 1))
        out[name] = idxs
    return out


def grid_layout(n_frames, box):
    """Frame -> top-left tile offset on the 16-wide OBJ VRAM grid."""
    t = box // 8
    per_row = 16 // t
    return [(f // per_row) * t * 16 + (f % per_row) * t for f in range(n_frames)]


def convert_sprite(png, anims_spec, label):
    """-> (chr blob, palette words, per-frame tile offsets, {anim: [offsets]}).

    Returns the DRAWN CONTENT BOTTOM too: the lowest opaque row + 1 over all
    frames. It is the number the lane band is anchored to, so it is computed
    here from the pixels rather than restated in the ASM.
    """
    frames = collect_frames(png, SPRITE_BOX)
    anims = parse_anims(anims_spec)
    keep = []
    for idxs in anims.values():
        for i in idxs:
            if i >= len(frames):
                raise SystemExit(f"{label}: frame {i} past the {len(frames)} "
                                 f"non-empty cells collected")
            if i not in keep:
                keep.append(i)
    remap = {old: new for new, old in enumerate(keep)}
    kept = [frames[i] for i in keep]
    anims = {a: [remap[i] for i in idxs] for a, idxs in anims.items()}

    allc = set()
    for f in kept:
        allc |= _opaque_colors(f)
    words, c2i = build_palette(allc, label)

    # png2snes.py:381 — a frame already exactly the box size keeps the author's
    # framing; only an oversized/undersized one is re-centred. Every camelot
    # cell is exactly 32x32, so nothing moves. Asserted, not assumed: a pack
    # revision that changed the cell size would otherwise silently shift the
    # feet baseline out from under the lane band.
    for f in kept:
        if f.size != (SPRITE_BOX, SPRITE_BOX):
            raise SystemExit(f"{label}: cell {f.size} is not the {SPRITE_BOX}"
                             f"x{SPRITE_BOX} OBJ box — re-derive the lane band")

    placements = grid_layout(len(kept), SPRITE_BOX)
    if placements and max(placements) > 255:
        raise SystemExit(f"{label}: last frame at tile offset {max(placements)}"
                         " — OAM tile numbers are 8-bit")
    t = SPRITE_BOX // 8
    rows_used = ((len(kept) + (16 // t) - 1) // (16 // t)) * t
    blob = bytearray(rows_used * 16 * 32)
    for f, img in enumerate(kept):
        rows = index_image(img, c2i)
        base = placements[f]
        for ty in range(t):
            for tx in range(t):
                ti = base + ty * 16 + tx
                pix = [rows[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
                blob[ti * 32:(ti + 1) * 32] = encode_tile_4bpp(
                    pix, f"{label} frame {f} tile {ti}")

    bottom = 0
    for img in kept:
        bb = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0).getbbox()
        if bb:
            bottom = max(bottom, bb[3])

    tables = {a: [placements[i] for i in idxs] for a, idxs in anims.items()}
    return bytes(blob), words, placements, tables, bottom


# ---------------------------------------------------------------------------
# BG conversion
# ---------------------------------------------------------------------------

def convert_bg(png, region, label):
    """-> (chr blob, palette words, map words).

    png2snes.py:708. Dedupes 8x8 cells against a cache seeded with a reserved
    blank at index 0; an empty cell maps to that blank.
    """
    x, y, w, h = region
    img = Image.open(png).convert("RGBA").crop((x, y, x + w, y + h))
    mw, mh = w // 8, h // 8
    cells = {}
    union = set()
    for ty in range(mh):
        for tx in range(mw):
            cell = img.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8))
            cols = frozenset(_opaque_colors(cell))
            if len(cols) > 15:
                raise SystemExit(f"{label}: cell ({tx},{ty}) has {len(cols)} colours")
            cells[(tx, ty)] = (cell, cols)
            union |= cols
    # png2snes groups per-tile colour sets into <=8 palettes (best-fit-
    # decreasing + a pairwise merge pass). When the UNION fits one palette that
    # algorithm provably collapses to exactly one group whose colour set is the
    # union — the merge pass merges every pair whose union is <=15. So the
    # single-group case is computed directly here, and the precondition is
    # checked rather than assumed. If a future region needed two groups this
    # raises instead of silently disagreeing with png2snes's grouping.
    if len(union) > 15:
        raise SystemExit(f"{label}: {len(union)} colours over the region needs "
                         f"more than one BG palette group — the single-group "
                         f"shortcut in this converter no longer applies")
    words, c2i = build_palette(union, label)

    blobs = [bytes(32)]
    cache = {bytes(32): 0}
    map_words = []
    for ty in range(mh):
        for tx in range(mw):
            cell, cols = cells[(tx, ty)]
            if not cols:
                map_words.append(0)          # the reserved blank, palette 0
                continue
            enc = encode_tile_4bpp(index_image(cell, c2i), f"{label} ({tx},{ty})")
            if enc not in cache:
                cache[enc] = len(blobs)
                blobs.append(enc)
            map_words.append(cache[enc] & 0x3FF)   # palette group 0: no attr bits
    return b"".join(blobs), words, map_words, (mw, mh)


# ---------------------------------------------------------------------------

def build_anim_blobs(tables, lengths):
    """The 5-table stride blob + its (len, rate) companion.

    `tables` maps (character, anim) -> list of tile offsets; `lengths` overrides
    the clock length where a table is stepped shorter than it is long.
    """
    frames = bytearray()
    meta = bytearray()
    for char, anim, rate, forced_len in ANIM_ORDER:
        tbl = tables[(char, anim)]
        if len(tbl) > ANIM_STRIDE:
            raise SystemExit(f"{char} {anim}: {len(tbl)} steps over the "
                             f"{ANIM_STRIDE}-byte stride")
        # pad with the table's OWN frame 0 — a defined tile, never a stray byte
        row = list(tbl) + [tbl[0]] * (ANIM_STRIDE - len(tbl))
        frames += bytes(row)
        n = forced_len if forced_len is not None else len(tbl)
        meta += bytes((n, rate))
    del lengths
    return bytes(frames), bytes(meta)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    art_chr, art_pal, art_pl, art_tabs, art_bottom = convert_sprite(
        CAMELOT / "arthurPendragon_.png", ARTHUR_ANIMS, "arthur")
    mor_chr, mor_pal, mor_pl, mor_tabs, mor_bottom = convert_sprite(
        CAMELOT / "mordred_.png", MORDRED_ANIMS, "mordred")

    # The lane band's anchor. Both knights must agree, and both must be 28.
    # Checked here because this is where the pixels are; the ASM re-asserts the
    # same equality against BR_CONTENT_BOTTOM.
    if art_bottom != mor_bottom:
        raise SystemExit(f"content bottoms disagree: arthur {art_bottom}, "
                         f"mordred {mor_bottom} — re-derive the lane band")
    if art_bottom != 28:
        raise SystemExit(f"content bottom is {art_bottom}, not 28 — the lane "
                         f"band in game/brawler/brawler.inc is derived from 28")

    bg_chr, bg_pal, bg_map, bg_grid = convert_bg(
        TILESET / "four-seasons-tileset.png", BG_REGION, "terrain")

    anim, anim_meta = build_anim_blobs(
        {("arthur", k): v for k, v in art_tabs.items()}
        | {("mordred", k): v for k, v in mor_tabs.items()}, None)

    files = {
        "br_art_chr.bin": art_chr,
        "br_art_pal.bin": encode_pal(art_pal),
        "br_mor_chr.bin": mor_chr,
        "br_mor_pal.bin": encode_pal(mor_pal),
        "br_bg_chr.bin": bg_chr,
        "br_bg_pal.bin": encode_pal(bg_pal),
        "br_bg_map.bin": encode_words(bg_map),
        "br_anim.bin": anim,
        "br_anim_meta.bin": anim_meta,
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")
    print(f"  arthur: {len(art_pl)} frames, drawn content bottom {art_bottom}")
    print(f"  mordred: {len(mor_pl)} frames, drawn content bottom {mor_bottom}")
    print(f"  terrain: {bg_grid[0]}x{bg_grid[1]} cells, "
          f"{len(bg_chr)//32} unique tiles")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
