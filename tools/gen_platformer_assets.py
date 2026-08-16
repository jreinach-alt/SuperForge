#!/usr/bin/env python3
"""gen_platformer_assets.py — deterministic art for the `platformer` rail.

Emits, into the directory named on the command line:

  plf_bg_chr.bin    9 BG tiles, 4bpp planar   (blank, ground, ledge, platform,
                                               coin, dirt, cloud, hill body,
                                               hill crest) -- BG1 *and* BG2
  plf_bg_pal.bin    16 BGR555 words           one palette serving both layers
  plf_obj_chr.bin   64 OBJ tiles, 4bpp planar (the hero's 4 frames as tiles
                                               0-31, the ghost's as 32-63, laid
                                               out for the {N,N+1,N+16,N+17}
                                               16x16 quad rule)
  plf_hero_pal.bin  16 BGR555 words           OBJ palette 0
  plf_ghost_pal.bin 16 BGR555 words           OBJ palette 1
  plf_level.bin     32 rows x 64 tile ids     the world, one byte per cell
  plf_sky.bin       32 rows x 8 tile ids      BG2's column-periodic skyline
  plf_grad.bin      3 x 224 COLDATA bytes     the dusk ramp rgb_gradient streams

TWO KINDS OF ART, AND THE SPLIT IS DELIBERATE.

THE ACTORS ARE IMPORTED. The hero and the ghosts are read from the ORIGINAL
pack PNGs vendored at `vendor/art/dungeon_sprites/` -- analogStudios_'s
"dungeonSprites". They are this rail's identity, so they are read from the
artist's pixels rather than re-drawn: hand-authored stand-ins were tried first
and they are not the same characters.

Reading the PNG also removes CLAUDE.md's asset-import tautology at the root:
the PNG is independent of anything this repo produces, so a test that compares
this generator's output to it is asking a real question. `tests/test_platformer.py`
then closes the loop from the other end, checking the CHR and palette derived
here against the committed reference conversion -- two converters that share
no code.

THE SCENERY IS HAND-AUTHORED. The level tiles and the skyline are stated below
as ASCII PICTURES, because no pack ships them: they are this rail's geometry
rather than its characters, and the generator being their source makes it the
tests' oracle for free. `breaker` takes the same route: no assets dir, its
tiles are bitmaps in its own DATA section.

NO SILENT MASKING (CLAUDE.md's asset-encoder rule), on BOTH paths. Every grid
character must resolve to a declared palette index; every imported pixel must
resolve to a colour the frame set actually declared; every index must be 0..15.
All three are asserted with the offending coordinates, never `& 0x0F`-ed into
range.

Everything is integer and order-independent, so the output is byte-identical
on re-run -- which is what makes recording the ROM's md5 worth anything.
"""
import sys
from pathlib import Path

from PIL import Image

ART = Path(__file__).resolve().parent.parent / "vendor/art/dungeon_sprites"

# --- the shared BG palette -------------------------------------------------
# ONE 16-colour palette serves BG1 (the level) and BG2 (the sky), which is
# what "one feature owns all a rail's co-resident layers" buys when the layers
# are related -- the same fold shmup made for its CHR page. Two palettes would
# only be needed if the two layers' indices collided; laid out together, they
# do not.
BGR = {
    ".": 0x0000,   # 0 transparent -- the backdrop reads through it
    "d": 0x11B7,   # 1 dirt body
    "p": 0x03E0,   # 2 platform body
    "c": 0x03FF,   # 3 coin body
    "g": 0x1726,   # 4 grass / platform edge
    "k": 0x090F,   # 5 dirt speckle (dark)
    "h": 0x4BFF,   # 6 coin highlight
    "w": 0x525C,   # 7 cloud, dusk-lit cream
    "s": 0x2846,   # 8 skyline silhouette
}
BG_ORDER = ".dpcgkhws"                      # index == position in this string

# --- the two OBJ actors, IMPORTED from the vendored pack --------------------
# Right-facing frames only: the rail mirrors with an OBJ HFLIP bit, which is
# free, so the left-facing halves of the pack are dead weight in VRAM.
HERO_PNGS = [f"fHero_idle_rIdle_{i}.png" for i in range(4)]
GHOST_PNGS = [f"ghost_idleWalkRun_rIdleWalkRun_{i}.png" for i in range(4)]


def grid(text):
    """An ASCII picture -> a list of rows of characters. Blank lines dropped."""
    rows = [ln for ln in text.strip("\n").split("\n") if ln.strip()]
    w = len(rows[0])
    for r in rows:
        assert len(r) == w, f"ragged grid row {r!r} (expected {w} wide)"
    return rows


def to_indices(rows, order):
    """Characters -> palette indices, asserting every one is declared."""
    out = []
    for y, r in enumerate(rows):
        line = []
        for x, ch in enumerate(r):
            assert ch in order, f"undeclared pixel {ch!r} at ({x},{y})"
            i = order.index(ch)
            assert 0 <= i <= 15, f"index {i} out of 4bpp range at ({x},{y})"
            line.append(i)
        out.append(line)
    return out


def encode_4bpp(tile):
    """One 8x8 index tile -> 32 bytes planar: rows of (p0,p1) then (p2,p3)."""
    assert len(tile) == 8 and all(len(r) == 8 for r in tile)
    lo, hi = bytearray(), bytearray()
    for row in tile:
        b = [0, 0, 0, 0]
        for x, px in enumerate(row):
            assert 0 <= px <= 15, f"pixel index {px} is not 4bpp"
            bit = 7 - x
            for pl in range(4):
                if px >> pl & 1:
                    b[pl] |= 1 << bit
        lo += bytes((b[0], b[1]))
        hi += bytes((b[2], b[3]))
    return bytes(lo + hi)


def palette_bin(mapping, order):
    """16 BGR555 words, little-endian; undeclared slots are black."""
    out = bytearray()
    for i in range(16):
        v = mapping[order[i]] if i < len(order) else 0
        out += bytes((v & 0xFF, v >> 8))
    return bytes(out)


def words_bin(words):
    """16 BGR555 words, little-endian."""
    assert len(words) == 16
    return b"".join(bytes((w & 0xFF, w >> 8)) for w in words)


# =============================================================================
# BG tiles -- 8x8 each, in level-map id order so a map byte IS a tile number
# =============================================================================
BG_TILES = [
    # 0 blank: the sky. Tile 0 must be fully transparent, because the dusk
    #   gradient is a BACKDROP wash and reads through every empty cell.
    grid("""
........
........
........
........
........
........
........
........"""),
    # 1 ground: two rows of grass over speckled dirt. The level's surface.
    grid("""
gggggggg
gggggggg
ddddkddd
dddddkdd
dkdddddd
ddddddkd
dddkdddd
dddddddd"""),
    # 2 ledge: the same surface, kept a DISTINCT tile id so the level map
    #   reads the way `sf_load_bg_tile 2, ground_tile` asks it to.
    grid("""
gggggggg
gggggggg
ddddkddd
dddddkdd
dkdddddd
ddddddkd
dddkdddd
dddddddd"""),
    # 3 one-way platform: a mossy lip you can jump THROUGH from below.
    grid("""
gggggggg
pppppppp
pppppppp
........
........
........
........
........"""),
    # 4 coin: a gold roundel with a highlight on its upper left.
    grid("""
..cccc..
.chhcc..
cchccccc
cchccccc
cccccccc
cccccccc
.cccccc.
..cccc.."""),
    # 5 dirt: the ground's interior. Same SOLID collision, no grass.
    grid("""
dddkdddd
ddddddkd
dkdddddd
ddddddkd
dddddkdd
dkdddddd
ddddkddd
dddddddd"""),
    # 6 cloud: BG2's far band. Round, so the dusk backdrop shows around it.
    grid("""
........
...ww...
..wwww..
.wwwwww.
wwwwwwww
.wwwwww.
........
........"""),
    # 7 hill body: BG2's near band, solid silhouette.
    grid("""
ssssssss
ssssssss
ssssssss
ssssssss
ssssssss
ssssssss
ssssssss
ssssssss"""),
    # 8 hill crest: the jagged top edge of the same silhouette.
    grid("""
...ss...
..ssss..
..ssss..
.ssssss.
.ssssss.
ssssssss
ssssssss
ssssssss"""),
]

# =============================================================================
# OBJ sprites -- the IMPORTED actors, 16x16, in the {N,N+1,N+16,N+17} quad
# =============================================================================
# The pack's cell is 24x24 but every frame's opaque content fits inside 16x16,
# so the reduction is a CROP AND A CENTRE PASTE -- no scaling, no resampling,
# no colour loss. That is not a convenience: it is what makes this derivation
# byte-reproducible, and therefore what lets test_platformer.py check it
# against the committed reference conversion and get a real answer.


def load_frames(names):
    """Vendored PNGs -> 16x16 RGBA frames, alpha-bbox cropped and centred.

    This is `png2snes.py`'s `recenter`. Bottom-anchoring is
    NOT used (png2snes's own default is centre) -- the feet are anchored at
    draw time from `content_bottom` instead, which is the same number and
    keeps the art's own vertical centring intact.
    """
    out = []
    for n in names:
        im = Image.open(ART / n).convert("RGBA")
        a = im.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        bb = a.getbbox()
        assert bb, f"{n}: fully transparent"
        x0, y0, x1, y1 = bb
        cw, ch = x1 - x0, y1 - y0
        assert cw <= 16 and ch <= 16, \
            f"{n}: opaque content is {cw}x{ch}, too big for the 16x16 OBJ box"
        box = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        box.paste(im.crop(bb), ((16 - cw) // 2, (16 - ch) // 2))
        out.append((n, box))
    return out


def sprite_palette(frames):
    """The frame set's distinct 5-bit colours -> 16 BGR555 words + a lookup.

    Index 0 is transparent (the hardware ignores its value), 1.. are sorted
    dark -> light so the order is a property of the ART and not of dict
    iteration. This is png2snes.py's `build_palette`, which is why the words
    come out equal to the committed reference conversion's.

    A frame set richer than 15 colours is REJECTED, naming the count. It is
    never `& 0x0F`-ed into range (CLAUDE.md's asset-encoder rule) -- silent
    masking is how a palette index becomes the wrong colour with no error.
    """
    seen = set()
    for _, im in frames:
        for y in range(16):
            for x in range(16):
                r, g, b, a = im.getpixel((x, y))
                if a >= 128:
                    seen.add((r >> 3, g >> 3, b >> 3))
    ordered = sorted(seen, key=lambda c: (c[0] * 299 + c[1] * 587 + c[2] * 114, c))
    assert len(ordered) <= 15, \
        f"{len(ordered)} distinct colours; a 4bpp OBJ palette holds 15 + transparent"
    words = [0] + [(c[2] << 10) | (c[1] << 5) | c[0] for c in ordered]
    return words + [0] * (16 - len(words)), {c: i + 1 for i, c in enumerate(ordered)}


def to_sprite_indices(name, im, lut):
    """One 16x16 RGBA frame -> palette indices, asserting every pixel resolves."""
    px = [[0] * 16 for _ in range(16)]
    for y in range(16):
        for x in range(16):
            r, g, b, a = im.getpixel((x, y))
            if a < 128:
                continue
            key = (r >> 3, g >> 3, b >> 3)
            assert key in lut, f"{name}: undeclared colour {key} at ({x},{y})"
            i = lut[key]
            assert 0 <= i <= 15, f"{name}: index {i} out of 4bpp range at ({x},{y})"
            px[y][x] = i
    return px


def content_bottoms(frames):
    """PER FRAME, the drawn content's bottom edge in the 16-px box, exclusive.

    THE FEET ANCHOR, AND IT IS FOUR NUMBERS, NOT ONE. The `.inc` headers
    png2snes writes carry a single `content_bottom` documented as "lowest
    drawn row + 1 (MAX OVER FRAMES)", and one number cannot describe four
    frames that do not share a sole. The hero's do not: measured off the
    vendored PNGs and off the built CHR, its four idle frames come out
    [16, 15, 15, 15].

    WHY THEY DIFFER, WHICH IS AN IMPORT ARTEFACT AND NOT THE ART. In the
    source PNGs all four hero frames share the same BOTTOM (row 24 of the
    pack's 24x24 cell) and bob at the HEAD (tops 8, 9, 10, 9) -- an idle
    breath, feet planted. `load_frames` reproduces png2snes's `recenter`,
    which centres each alpha-bbox crop in the 16-box: that pins the TOPS at
    ~0 and pushes the variation onto the BOTTOMS, exactly inverting the
    relationship the artist drew. The CHR matches the committed reference
    conversion byte for byte because the centring does; so does the artefact.

    Anchoring every frame on the MAX floats three frames of four; anchoring
    on a single per-actor value sinks whichever frames are
    taller than it into the surface. Both are wrong in one direction each,
    which is why the draw code takes the whole list and subtracts each
    frame's own number.
    """
    out = []
    for _, im in frames:
        a = im.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        bb = a.getbbox()
        assert bb, "fully transparent frame has no feet"
        out.append(bb[3])
    return out


def source_bottoms(names):
    """The same edge in the PACK'S OWN cell, before any centring.

    Kept because it is the evidence that the per-frame spread above is ours
    (well, png2snes's) and not the artist's: the hero's four are all equal
    here and unequal after the crop-and-centre.
    """
    out = []
    for n in names:
        im = Image.open(ART / n).convert("RGBA")
        a = im.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        out.append(a.getbbox()[3])
    return out


def quad(px16):
    """A 16x16 index picture -> its four 8x8 tiles, in {TL, TR, BL, BR} order.

    The SNES reads a 16x16 OBJ as tiles {N, N+1, N+16, N+17} -- the OBJ name
    table is sixteen tiles wide, so "one row down" is +16, not +2. So the
    bottom half of every frame lands in the NEXT tile row, and this returns
    the four in the order the page layout below places them.
    """
    tl = [r[0:8] for r in px16[0:8]]
    tr = [r[8:16] for r in px16[0:8]]
    bl = [r[0:8] for r in px16[8:16]]
    br = [r[8:16] for r in px16[8:16]]
    return tl, tr, bl, br


def sprite_page(frames, lut):
    """Four 16x16 frames -> a 32-tile page: two 16-wide VRAM tile rows.

      row 0 (tiles  0..15): f0 [0,1]  f1 [2,3]  f2 [4,5]  f3 [6,7]
      row 1 (tiles 16..31): ...their bottom halves, each +16

    THE PAGE IS 32 TILES FOR 4 FRAMES, not 16, and the 8 blank tiles past
    frame 3 in each row are what the {N+16} rule costs. That is also why an
    actor's load base must be a MULTIPLE OF 16 and why two actors must sit 32
    apart: at 16 apart the second's top row lands on the first's bottom row.
    That bug has been shipped before, which is why the pack's LOAD CONTRACT
    note is quoted in vendor/art/dungeon_sprites/README.md.
    """
    blank = [[0] * 8 for _ in range(8)]
    row0 = [blank for _ in range(16)]
    row1 = [blank for _ in range(16)]
    for n, (name, im) in enumerate(frames):
        tl, tr, bl, br = quad(to_sprite_indices(name, im, lut))
        row0[n * 2 + 0], row0[n * 2 + 1] = tl, tr
        row1[n * 2 + 0], row1[n * 2 + 1] = bl, br
    return b"".join(encode_4bpp(t) for t in row0 + row1)


def obj_pages():
    """The 64-tile OBJ region: the hero's page then the ghost's.

    Tiles 0-31 = hero (PLF_HERO_TILE 0), 32-63 = ghost (PLF_GHOST_TILE 32).
    Both bases are multiples of 16, which is the load contract the pages are
    laid out for.
    """
    chunks, meta = [], {}
    for tag, names in (("hero", HERO_PNGS), ("ghost", GHOST_PNGS)):
        frames = load_frames(names)
        words, lut = sprite_palette(frames)
        chunks.append(sprite_page(frames, lut))
        meta[tag] = (words, content_bottoms(frames), source_bottoms(names))
    return b"".join(chunks), meta



# =============================================================================
# The level -- 32 rows x 64 columns of tile ids (512 x 256 px)
# =============================================================================
# The `level_map`, expressed as a picture rather than as .repeat runs so the
# geometry is readable and the tests can import THIS as their oracle.
#
#   .  sky        1 ground (grass surface)   2 ledge      3 one-way platform
#   4  coin       5 dirt interior
#
# Ground rows 24-27 with pits at cols 22-25 and 46-49; ghost 2's ledge (row
# 16, cols 26-38) crosses the world's page seam at col 32, which is the thing
# the seam patrol exists to exercise.
#
# 32 ROWS, NOT 28, AND THE FOUR SPARE ONES BUY TOTALITY. The screen
# is 224 px = 28 rows and rows 28-31 are pure sky that nothing can scroll into
# (BG1VOFS is pinned at 0). But a 32-row map makes the collision probe's row
# index `(y >> 3) & 31` -- a mask -- so EVERY u16 input names a real cell and
# there is no bounds check, no sentinel, and no branch to get wrong. That is
# col_map's discipline and breaker_bg's, and here it costs 256 bytes of ROM.
# It also makes the blob a 1:1 image of the 64x32 BG1 tilemap, so the build
# loop is a copy with an attribute OR rather than a transform.
LEVEL_W, LEVEL_H = 64, 32
_L = {".": 0, "G": 1, "L": 2, "P": 3, "C": 4, "D": 5}


def level_rows():
    r = [["."] * LEVEL_W for _ in range(LEVEL_H)]

    def put(row, c0, c1, ch):
        for c in range(c0, c1 + 1):
            r[row][c] = ch

    r[15][31] = "C"                    # the seam coin, at ledge-walking height
    put(16, 26, 38, "L")               # ghost 2's ledge -- crosses col 32
    put(18, 19, 21, "P")               # the step up to the ledge
    r[19][12] = "C"
    r[19][43] = "C"
    put(20, 10, 15, "P")               # one-way platforms
    put(20, 41, 46, "P")
    r[23][7] = "C"
    r[23][34] = "C"
    r[23][60] = "C"
    for col in range(LEVEL_W):         # rows 24-27: ground, minus two pits
        if 22 <= col <= 25 or 46 <= col <= 49:
            continue
        r[24][col] = "G"
        for row in (25, 26, 27):
            r[row][col] = "D"
    return ["".join(row) for row in r]


def level_bin():
    rows = level_rows()
    out = bytearray()
    for row in rows:
        for ch in row:
            assert ch in _L, f"undeclared level cell {ch!r}"
            out.append(_L[ch])
    assert len(out) == LEVEL_W * LEVEL_H
    return bytes(out)


# =============================================================================
# BG2's skyline -- 32 rows x 8 columns of tile ids, periodic across the map
# =============================================================================
# The 8-column period is 64 px, so a parallax shift is UNAMBIGUOUS in a
# screenshot up to 63 px: the same picture never repeats within one band's
# whole travel, and a test can name where a feature moved to. Residues 0-1 are
# always empty, which leaves a 16 px backdrop valley every 64 px where the dusk
# ramp reads pure.
#
# WHICH ROWS SIT IN WHICH BAND IS THE WHOLE DESIGN. BG2 does not scroll
# vertically, so row r covers scanlines 8r..8r+7, and the band split is at
# scanline 96 = row 12. Clouds live in rows 3-7 (fully above), hills in rows
# 12-16 (fully below) -- so the two bands each carry a feature that is
# ENTIRELY theirs, and a screenshot at a known camera x shows them at two
# different offsets with nothing straddling the seam to confuse the reading.
#
#   6 cloud    7 hill body    8 hill crest
SKY_W, SKY_H = 8, 32
SKY_ROWS = {
    3:  [0, 0, 0, 6, 6, 0, 0, 0],       # a small cloud top
    4:  [0, 0, 6, 6, 6, 6, 0, 0],       # ...its body
    7:  [0, 0, 0, 0, 0, 0, 6, 6],       # a second cloud, offset
    12: [0, 0, 0, 0, 8, 8, 0, 0],       # the hill's jagged peak
    13: [0, 0, 0, 8, 7, 7, 8, 0],       # shoulders
    14: [0, 0, 8, 7, 7, 7, 7, 8],       # base edges
    15: [0, 0, 7, 7, 7, 7, 7, 7],       # solid silhouette, valley at 0-1
    16: [0, 0, 7, 7, 7, 7, 7, 7],
}


def sky_bin():
    out = bytearray()
    for r in range(SKY_H):
        row = SKY_ROWS.get(r, [0] * SKY_W)
        assert len(row) == SKY_W
        for t in row:
            assert 0 <= t < len(BG_TILES), f"sky row {r} names tile {t}"
            out.append(t)
    assert len(out) == SKY_W * SKY_H
    return bytes(out)


# =============================================================================
# The dusk gradient -- 3 x 224 COLDATA bytes, the ramp rgb_gradient streams
# =============================================================================
# THE RAMP LANDS ON THE BACKDROP.
# `play` declares RG_MATH_LAYERS = PLF_MATH_BACKDROP (CGADSUB bit 5) — so the
# ramp IS the sky,
# showing through every transparent level cell and every gap between the hills,
# while BG1's terrain and BG2's skyline keep their authored colours. CGRAM word
# 0 under it is BLACK (PLF_PLAY_SKY), so these intensities render as themselves.
#
# AN EARLIER SHAPE OF THIS RAMP, and why it is gone: it used to be (18,5,8) ->
# (0,0,0) reshaped onto BG1+BG2, on the reasoning that re-targeting the shared
# `rgb_gradient` would move microzero's pinned md5. It rendered a dark teal
# sky. The premise was wrong twice over: a pin is not a licence to ship the
# wrong picture, AND re-targeting never needed to move it — WHICH layers the
# wash lands on is a per-scene declaration, so microzero and breaker keep
# emitting the byte they always emitted.
#
# WHERE THE COMMITTED REFERENCE RAMP DIVERGES, stated because it is a knowing
# gap rather than a drift. `tests/fixtures/ref_dusk_grad.bin` is a measured
# ramp whose 8.8 step was computed as
#     step = signed_div_225(xba(bot - top))
# where `xba` BYTE-SWAPS in place of a `<< 8` — correct for a positive delta,
# wrong for a negative one ($FFEA -> $EAFF = -5377, not -5632). Its R step is
# therefore -23 where the declared endpoints ask for -25, and it stops at
# (3,1,11) instead of (2,0,12). That is an arithmetic bug, not a look choice,
# and reproducing a byte-swap in a Python generator to inherit it would make
# DUSK_BOT below stop describing this file's own output — for a difference of
# at most 2 of 31 intensity steps. So the endpoints below are realised as
# DECLARED, and `test_the_dusk_ramp_matches_the_reference_ramp` bounds the gap
# against the measured fixture rather than leaving it unstated.
GRAD_LINES = 224
DUSK_TOP = (24, 8, 2)                  # warm orange at the top of the sky
DUSK_BOT = (2, 0, 12)                  # deep blue-purple at the horizon
PLANE = (0x20, 0x40, 0x80)             # COLDATA plane-select bits (R, G, B)


def grad_bin():
    out = bytearray()
    for pl in range(3):
        top, bot = DUSK_TOP[pl], DUSK_BOT[pl]
        for y in range(GRAD_LINES):
            # integer lerp, rounded to nearest -- no float, so re-runs match
            v = (top * (GRAD_LINES - 1 - y) + bot * y + (GRAD_LINES - 1) // 2) \
                // (GRAD_LINES - 1)
            assert 0 <= v <= 31, f"intensity {v} out of COLDATA range"
            out.append(PLANE[pl] | v)
    assert len(out) == 3 * GRAD_LINES
    return bytes(out)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
    out.mkdir(parents=True, exist_ok=True)

    bg_chr = b"".join(encode_4bpp(t) for t in
                      (to_indices(g, BG_ORDER) for g in BG_TILES))
    assert len(bg_chr) == len(BG_TILES) * 32
    (out / "plf_bg_chr.bin").write_bytes(bg_chr)
    (out / "plf_bg_pal.bin").write_bytes(palette_bin(BGR, BG_ORDER))
    obj_chr, meta = obj_pages()
    assert len(obj_chr) == 64 * 32
    (out / "plf_obj_chr.bin").write_bytes(obj_chr)
    (out / "plf_hero_pal.bin").write_bytes(words_bin(meta["hero"][0]))
    (out / "plf_ghost_pal.bin").write_bytes(words_bin(meta["ghost"][0]))
    (out / "plf_level.bin").write_bytes(level_bin())
    (out / "plf_sky.bin").write_bytes(sky_bin())
    (out / "plf_grad.bin").write_bytes(grad_bin())
    # The feet anchors are the FOUR numbers per actor the draw code subtracts;
    # printing them keeps what governs where the actors stand visible at build
    # time rather than buried in a header nobody re-reads. The source column is
    # the pack's own bottoms -- when they are all equal and ours are not, the
    # spread is the centring, not the art.
    print(f"gen_platformer_assets: {len(BG_TILES)} BG tiles, 64 OBJ tiles "
          f"(hero @0 + ghost @32, both 16-aligned), "
          f"{LEVEL_W}x{LEVEL_H} level, {SKY_W}x{SKY_H} skyline, "
          f"{GRAD_LINES}-line dusk ramp -> {out}")
    for tag in ("hero", "ghost"):
        print(f"  {tag:5s} content_bottom per frame {meta[tag][1]} "
              f"(pack's own bottoms {meta[tag][2]})")


if __name__ == "__main__":
    main()
