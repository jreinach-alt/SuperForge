#!/usr/bin/env python3
"""gen_lakeside_assets.py — deterministic art for the `lakeside` rail.

Emits (byte-identical on re-run, pure integer math, no seed):

  lk_chr.bin    26 x 4bpp BG1 tiles, 32 B each = 832 B   the shore and the bed
  lk_map.bin    32x32 tilemap words = 2048 B             the world
  lk_pal.bin    16 BGR555 words = 32 B                   BG palette group 0
                (CGRAM 0..15; word 0 IS the backdrop slot)
  wat_chr.bin   34 x 4bpp BG2 tiles = 1088 B            the surface, the
                                                         highlight's phases and
                                                         the swash band's slots
  wat_map.bin   32x32 tilemap words = 2048 B             the surface
  wat_pal.bin   16 BGR555 words = 32 B                   BG palette group 2
                (CGRAM 32..47)
  surf_chr.bin  32 phases x 16 slots x 32 B = 16384 B   the surf, resident
  lk_art.inc    the LAYOUT constants water.asm pins      (format version 2)

WHAT THE PICTURE IS. A shore read from the side: sky, a ridge of hills, a sand
and rock beach whose WATERLINE MEANDERS across three tile rows, then a clear
shallow strip, then the lake in two zones — a textured shallow shelf with silt,
pebble and sandbar clusters, and open deep water with rock and weed. The
surface on BG2 covers the water from tile row 12 down, and its TOP EDGE is a
SURF that runs up the shore and draws back: tilemap rows 12..15 are display
slots whose 32 bytes are rewritten from a resident phase blob once per armed
VBlank, so the waterline sweeps 26 px of beach on an asymmetric schedule — the
swash fast, the backwash a little under half as fast, then a lull. The edge is
transparent above a meandering line at every phase, so the blend's own boundary
is irregular AND it moves; the sand it crosses is (sand + water) >> 1 while it
is covered and its own colour again when the water leaves. Sparse opaque
highlights twinkle on the deep water through a four-phase loop.

WHY THE COLOURS ARE WHAT THEY ARE. The rail's subject is a half-add, and its
tests assert the composited pixel as an EQUALITY rather than a tolerance: for
each 5-bit channel the PPU computes min((main + sub) >> 1, 31) (Mesen2
SnesPpu.cpp:1372-1377 — the shift is applied before the clamp, so with two
operands of at most 31 the clamp never bites). Flat bands made that easy;
tile art does not, because a picture with seven submerged main colours and five
surface colours puts THIRTY-FIVE distinct composited values on screen. So the
palette is chosen against the whole cross product, and
`assert_blend_colours_are_distinguishable` proves four separate properties over
it at author time rather than leaving any of them to a reader:

  P1  the submerged main colours are pairwise distinct;
  P2  no half-add equals any raw main colour — dry or submerged — which is what
      lets a test say "this pixel cannot be an unblended world pixel";
  P3  every half-add is distinct from every other, so a spot check names one
      (main, sub) pair and not a class;
  P4  no FULL add (the halve bit clear) equals any legal value, which is what
      makes "the full-add colour appears nowhere" a real assertion.

A collision would not fail the generator's own output — it would make a passing
test unable to tell a blended pixel from an unblended one, which is the
indirect-evidence trap one layer down.

READABLE THROUGH THE BLEND. A half-add halves CONTRAST as well as brightness:
two bed colours 12 apart in a channel are 6 apart once composited. So the
submerged palette is spread deliberately wide — the cluster colours sit 8 to 17
apart from the beds they sit on — and the surface is built from strong opaque
clusters rather than dither, because a dithered pattern loses its identity
entirely at half weight.

THE HORIZONTAL PERIOD IS 32 PX, AND IT IS LOAD-BEARING. BG2 scrolls and BG1
does not, so the picture repeats when the surface has moved one pattern period.
The surface map is authored as a 4-cell pattern repeated eight times and the
highlight's phase advances once per 8 px, so both return together every 32 px
and `tests/test_lakeside.py::test_the_surface_is_continuous_across_both_wraps`
can assert a BIT-IDENTICAL picture across the pattern period and across the
256 px map wrap. Rows 25..27 carry no highlight and sit over a horizontally
UNIFORM bed, which is what makes the drift there a pure translation the tests
can recover from the pixels.

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): `encode_4bpp` asserts every
pixel index is 0..15 and `encode_pal` asserts every entry is a 15-bit BGR
value. An out-of-range author error stops the generator naming the offending
pixel; it never quietly becomes a different colour.
"""
import sys
from pathlib import Path

# --- BGR555 helper ---------------------------------------------------------
# The SNES word is B<<10 | G<<5 | R, five bits per channel. Written as a
# function of the three channels rather than as hex literals so the blend
# arithmetic below can be read against the same numbers the tests use.


def bgr(r, g, b):
    assert all(0 <= c <= 31 for c in (r, g, b)), f"channel out of range: {r},{g},{b}"
    return (b << 10) | (g << 5) | r


# --- BG1: the world, palette group 0 (CGRAM words 0..15) -------------------
# Word 0 is the 4bpp transparent slot AND the hardware backdrop at once,
# which is why lake_bg claims it rather than composing `backdrop`.
#
# The first seven are DRY — they live above the surface's coverage and are
# never an operand of the blend. The last seven are SUBMERGED, and every one
# of them is a main-screen operand the half-add has to stay honest about.
BACKDROP = (2, 3, 8)          # deep night blue — the main screen's floor
SKY = (18, 24, 30)            # pale daylight blue
HILL = (4, 14, 6)             # dark green ridge
HILL_LIT = (7, 19, 9)         # its sunlit face
SAND = (26, 22, 12)           # warm dry sand
ROCK = (14, 12, 10)           # the shoreline rocks
ROCK_LIT = (21, 18, 16)       # their lit faces. ONE STEP OFF SUBROCK_LIT
                              #   ON PURPOSE: the two used to differ by 1 in
                              #   r and b, and >>1 threw that away — their
                              #   half-adds were the SAME colour. Harmless
                              #   while the beach could never be wet; a P3
                              #   collision the moment the surf covers rock.

SHELF = (18, 23, 17)          # the shallow bed: pale green silt over sand
SHELF_DK = (11, 16, 13)       # ...and the darker silt that drifts over it
SANDBAR = (27, 26, 19)        # a bright bar just under the surface
SUBROCK = (11, 12, 11)        # submerged rock
SUBROCK_LIT = (19, 18, 15)    # its lit face
DEEP = (4, 10, 14)            # open water's bed
DEEP_DK = (1, 3, 6)           # weed and the deepest silt

LK_PAL = [bgr(*BACKDROP), bgr(*SKY), bgr(*HILL), bgr(*HILL_LIT), bgr(*SAND),
          bgr(*ROCK), bgr(*ROCK_LIT), bgr(*SHELF), bgr(*SHELF_DK),
          bgr(*SANDBAR), bgr(*SUBROCK), bgr(*SUBROCK_LIT), bgr(*DEEP),
          bgr(*DEEP_DK), 0, 0]

# --- BG2: the surface, palette group 2 (CGRAM words 32..47) ---------------
# Two zones, because a lake is not one flat sheet: the shallow water near the
# shore catches a greener light than the open water does, and the pair of
# crest/trough tones per zone is what makes the depth split a thing the eye
# reads rather than a thing the map knows.
SH_CREST = (11, 23, 25)       # shallow: the lit face of a ripple
SH_TROUGH = (5, 14, 20)       # shallow: its shaded face
DP_CREST = (7, 17, 27)        # deep: the lit face
DP_TROUGH = (2, 9, 17)        # deep: its shaded face
GLINT = (27, 30, 31)          # the sparse opaque highlight

WAT_PAL = [0, bgr(*SH_CREST), bgr(*SH_TROUGH), bgr(*DP_CREST),
           bgr(*DP_TROUGH), bgr(*GLINT)] + [0] * 10

# =============================================================================
# tile art
# =============================================================================
# Palette INDICES inside a tile, not colours. Index 0 is transparent in a 4bpp
# BG, which is what draws the water's edge and the gaps in the ripple.
#
# Tiles are written either as an 8-line PICTURE (one character per pixel, read
# through the legend below) or as a PROFILE — a per-column boundary height,
# which is the shape an irregular edge actually wants. Both are hand-authored:
# the byte output is a property of this file and not of a seed.

LK_LEGEND = {".": 0, "s": 1, "h": 2, "H": 3, "n": 4, "r": 5, "R": 6,
             "f": 7, "g": 8, "b": 9, "k": 10, "K": 11, "d": 12, "D": 13}

WAT_LEGEND = {".": 0, "c": 1, "t": 2, "C": 3, "T": 4, "*": 5}

# The surface map's horizontal pattern: four 8 px cells, repeated eight
# times across the 32-cell map. EVERY periodic number in this file is a
# multiple or a divisor of it — the highlight's loop, the surf's cycle, the
# edge profiles — because a picture asked to repeat across a 32 px
# displacement can only do so if they all are.
WAVE_PATTERN_PX = 4 * 8

WAT_I_SH_CREST, WAT_I_SH_TROUGH = 1, 2
WAT_I_DP_CREST, WAT_I_DP_TROUGH = 3, 4


def pic(legend, *rows):
    """Eight 8-character lines -> an 8x8 grid of palette indices."""
    assert len(rows) == 8, f"a tile is 8 rows, got {len(rows)}"
    out = []
    for y, row in enumerate(rows):
        assert len(row) == 8, f"row {y} is {len(row)} px, expected 8"
        out.append([legend[c] for c in row])
    return out


def flat(index):
    return [[index] * 8 for _ in range(8)]


def profile(top_index, bottom_index, heights):
    """`top_index` above a per-column boundary, `bottom_index` from it down.

    `heights[x]` is how many rows of `top_index` column x carries. This is the
    shape every irregular edge in this file is built from — a coastline, a
    shelf drop-off, the jagged top of the surface — because a boundary the eye
    reads as terrain is one that moves within the tile, not one that lands on
    a tile row.
    """
    assert len(heights) == 8, f"a profile is 8 columns, got {len(heights)}"
    assert all(0 <= h <= 8 for h in heights), f"height out of range: {heights}"
    return [[top_index if y < heights[x] else bottom_index for x in range(8)]
            for y in range(8)]


# ---- BG1 tiles, in the order they are packed into lk_chr.bin --------------
LK_T = {}                       # name -> tile id, filled by `lk_tile`
LK_TILES = []


def lk_tile(name, rows):
    LK_T[name] = len(LK_TILES)
    LK_TILES.append(rows)


lk_tile("empty", flat(0))                       # written, never referenced
lk_tile("sky", flat(LK_LEGEND["s"]))
lk_tile("horizon_a", profile(1, 2, [4, 4, 3, 3, 2, 3, 3, 4]))
lk_tile("horizon_b", profile(1, 2, [5, 4, 4, 5, 5, 4, 3, 3]))
lk_tile("hill", flat(LK_LEGEND["h"]))
lk_tile("hill_lit", pic(LK_LEGEND,
                        "hhHhhhhh",
                        "hhHHhhHh",
                        "hhhHhhHH",
                        "hHhhhhhh",
                        "hHHhhhhh",
                        "hhhhhHhh",
                        "hhhhhHHh",
                        "hhhhhhhh"))
lk_tile("hill_sand", profile(2, 4, [4, 5, 5, 4, 3, 3, 4, 5]))
lk_tile("sand", pic(LK_LEGEND,
                    "nnnnnnnn",
                    "nnnrnnnn",
                    "nnnnnnnn",
                    "nnnnnnrn",
                    "nnnnnnnn",
                    "nrnnnnnn",
                    "nnnnnnnn",
                    "nnnnrnnn"))
lk_tile("sand_rock", pic(LK_LEGEND,
                         "nnnnnnnn",
                         "nnRnnnnn",
                         "nrrnnnRn",
                         "nrrnnrrn",
                         "rrrrnrrr",
                         "rrrRrrrr",
                         "rrrrrrRr",
                         "rrrrrrrr"))
lk_tile("rock", pic(LK_LEGEND,
                    "rRrrrrrr",
                    "rRRrrrrR",
                    "rrRrrrrR",
                    "rrrrRRrr",
                    "rrrrRrrr",
                    "RrrrrrRr",
                    "rrrrrRRr",
                    "rrrrrrrr"))
# The six coast tiles. Each carries land above a meandering line and the CLEAR
# shallow water below it — no surface covers these rows, so what the waterline
# separates here is two UNBLENDED populations, which is why the shallow bed's
# colour has to read as water on its own rather than borrowing the blend.
# Four are sand and two are rock, so the beach is sand with outcrops in it
# rather than a rock band.
lk_tile("coast_a", profile(4, 7, [6, 6, 5, 5, 6, 7, 7, 6]))
lk_tile("coast_b", profile(4, 7, [3, 4, 4, 3, 2, 2, 3, 3]))
lk_tile("coast_c", profile(4, 7, [6, 5, 4, 3, 2, 2, 1, 1]))
lk_tile("coast_d", profile(4, 7, [1, 1, 2, 3, 4, 5, 5, 6]))
lk_tile("coast_r", profile(5, 7, [5, 4, 4, 3, 3, 4, 5, 5]))
lk_tile("coast_s", profile(5, 7, [2, 3, 4, 4, 3, 2, 2, 3]))
lk_tile("shelf", flat(LK_LEGEND["f"]))
lk_tile("shelf_silt", pic(LK_LEGEND,
                          "ffgggfff",
                          "fggggggf",
                          "fggfggff",
                          "ffgfffff",
                          "fffffggf",
                          "ffffgggg",
                          "fffffggf",
                          "ffffffff"))
lk_tile("shelf_rock", pic(LK_LEGEND,
                          "ffffffff",
                          "ffKKffff",
                          "fkkkkfff",
                          "fkkkkKKf",
                          "kkkkkkkf",
                          "fkkkkkkf",
                          "ffkkkkff",
                          "ffffkfff"))
lk_tile("sandbar", pic(LK_LEGEND,
                       "ffbbbfff",
                       "fbbbbbbf",
                       "bbbbbbbb",
                       "bbbbbbbb",
                       "fbbbbbbb",
                       "ffbbbbbf",
                       "fffbbfff",
                       "ffffffff"))
lk_tile("shelf_deep_a", profile(7, 12, [5, 6, 6, 5, 4, 4, 3, 3]))
lk_tile("shelf_deep_b", profile(7, 12, [3, 2, 2, 3, 4, 5, 5, 6]))
lk_tile("deep", flat(LK_LEGEND["d"]))
lk_tile("deep_silt", pic(LK_LEGEND,
                         "dddDDddd",
                         "ddDDDDdd",
                         "dDDdDDdd",
                         "ddDddddd",
                         "ddddDDdd",
                         "dddDDDDd",
                         "ddddDDdd",
                         "dddddddd"))
lk_tile("deep_rock", pic(LK_LEGEND,
                         "dddddddd",
                         "dddKKddd",
                         "ddkkkkdd",
                         "dkkkkKKd",
                         "dkkkkkkd",
                         "kkkkkkkd",
                         "dkkkkkdd",
                         "ddkkdddd"))
lk_tile("deep_weed", pic(LK_LEGEND,
                         "dDdddDdd",
                         "dDddDDdd",
                         "dDDdDddd",
                         "ddDdDddD",
                         "ddDDDddD",
                         "dddDDdDD",
                         "dddDDDDd",
                         "ddddDDdd"))

# ---- BG2 tiles ------------------------------------------------------------
WAT_T = {}
WAT_TILES = []


def wat_tile(name, rows):
    WAT_T[name] = len(WAT_TILES)
    WAT_TILES.append(rows)


wat_tile("empty", flat(0))
wat_tile("sh_crest", flat(WAT_I_SH_CREST))
wat_tile("sh_trough", flat(WAT_I_SH_TROUGH))
# The ripple. Roughly a quarter of each wave tile is TRANSPARENT, which is what
# lets the bed through unblended in patches — the empty-sub fallback happening
# inside the water rather than only at its edge.
wat_tile("sh_wave_a", pic(WAT_LEGEND,
                          "tttttttt",
                          "tcccccct",
                          "tttttttt",
                          "tttttttt",
                          "tt....tt",
                          "t......t",
                          "tttttttt",
                          "tttttttt"))
wat_tile("sh_wave_b", pic(WAT_LEGEND,
                          "tttttttt",
                          "tt....tt",
                          "t......t",
                          "tttttttt",
                          "tttttttt",
                          "ttcccccc",
                          "tttttttt",
                          "tttttttt"))
# The surface's top edge USED TO BE four static tiles on tilemap row 14. It is
# now the swash band's business (see "the surf" below) and the shape those
# tiles drew survives as SURF_JAG, one of the edge profiles the band composes.
# Nothing points at a jag tile any more, so none is emitted: an unreferenced
# tile is a claim nobody reads.
wat_tile("dp_crest", flat(WAT_I_DP_CREST))
wat_tile("dp_trough", flat(WAT_I_DP_TROUGH))
# Where the two zones meet. The depth itself is a property of the BED and its
# drop-off is drawn on BG1, which does not scroll; this is the SURFACE changing
# character over it, so its boundary is allowed to meander and to drift — a
# wind line on open water does exactly that. Both indices are already in the
# palette, so the zone edge adds no colour and no blend pair.
wat_tile("zone_a", profile(WAT_I_SH_TROUGH, WAT_I_DP_TROUGH, [5, 4, 4, 3, 3, 2, 2, 3]))
wat_tile("zone_b", profile(WAT_I_SH_TROUGH, WAT_I_DP_TROUGH, [4, 5, 6, 6, 5, 4, 4, 5]))
wat_tile("zone_c", profile(WAT_I_SH_TROUGH, WAT_I_DP_TROUGH, [5, 4, 3, 3, 4, 5, 6, 6]))
wat_tile("zone_d", profile(WAT_I_SH_TROUGH, WAT_I_DP_TROUGH, [6, 5, 4, 4, 5, 5, 6, 5]))
wat_tile("dp_wave_a", pic(WAT_LEGEND,
                          "TTTTTTTT",
                          "TTCCCCCT",
                          "TTTTTTTT",
                          "TTTTTTTT",
                          "TTT...TT",
                          "TT.....T",
                          "TTTTTTTT",
                          "TTTTTTTT"))
wat_tile("dp_wave_b", pic(WAT_LEGEND,
                          "TTTTTTTT",
                          "TT...TTT",
                          "T.....TT",
                          "TTTTTTTT",
                          "TTTTTTTT",
                          "TCCCCCTT",
                          "TTTTTTTT",
                          "TTTTTTTT"))
# THE HIGHLIGHT'S DISPLAY SLOT. The map points every twinkle cell here; the
# VBlank writer copies one of the four phases below into it every armed frame
# (engine/features/water/water.asm, `wat_nmi_glint`). Its bytes in this blob
# are phase 0, so a machine caught at phase 0 matches the blob exactly.
GLINT_PHASES = [
    pic(WAT_LEGEND,                             # 0 — a bare point
        "TTTTTTTT",
        "TTTTTTTT",
        "TTTTTTTT",
        "TTT**TTT",
        "TTT**TTT",
        "TTTTTTTT",
        "TTTTTTTT",
        "TTTTTTTT"),
    pic(WAT_LEGEND,                             # 1 — opening
        "TTTTTTTT",
        "TTTTTTTT",
        "TTT**TTT",
        "TT****TT",
        "TT****TT",
        "TTT**TTT",
        "TTTTTTTT",
        "TTTTTTTT"),
    pic(WAT_LEGEND,                             # 2 — the peak
        "TTTTTTTT",
        "TTT**TTT",
        "TTT**TTT",
        "T******T",
        "T******T",
        "TTT**TTT",
        "TTT**TTT",
        "TTTTTTTT"),
    pic(WAT_LEGEND,                             # 3 — scattering
        "TTTTTTTT",
        "TTTTTTTT",
        "TT*TT*TT",
        "TTTTTTTT",
        "TTTTTTTT",
        "TT*TT*TT",
        "TTTTTTTT",
        "TTTTTTTT"),
]
wat_tile("glint_slot", GLINT_PHASES[0])
for _i, _rows in enumerate(GLINT_PHASES):
    wat_tile(f"glint_p{_i}", _rows)

# How far the surface drifts before the highlight steps to its next phase, and
# how many phases there are. The consumer PINS both out of lk_art.inc rather
# than re-narrating them, so the loop cannot drift from the tiles it indexes.
#
# THE PRODUCT IS 32 — one whole pattern period — and that is not a coincidence
# to tidy away. The picture is asked to repeat exactly across a 32 px
# displacement of the surface; a highlight loop whose length did not divide
# that would break the repeat, so the two numbers are chosen together.
#
# THE LOOP IS INDEXED BY POSITION, NOT BY A COUNT OF FRAMES. What selects a
# phase is where the surface has got to, which is an accumulator the rail
# advances through TS_STEP — so the twinkle is region-correct for free, it
# holds still exactly when the drift is stilled, and there is no second clock
# to keep in step with the first.
GLINT_STEP_SHIFT = 3
GLINT_STEP_PX = 1 << GLINT_STEP_SHIFT
GLINT_PHASE_COUNT = len(GLINT_PHASES)
GLINT_TILE_SHIFT = 5
GLINT_TILE_BYTES = 1 << GLINT_TILE_SHIFT
assert GLINT_PHASE_COUNT & (GLINT_PHASE_COUNT - 1) == 0, (
    f"the highlight's phase count is {GLINT_PHASE_COUNT} — the consumer masks "
    f"with count-1, so it must be a power of two")

# =============================================================================
# the surf — a wave that runs up the shore and draws back
# =============================================================================
# WHAT IT IS, AND WHY IT BELONGS IN A COLOUR-MATH RAIL. BG2 is the SUB screen
# and the blend is a half-add, so the surface's own top edge IS the blend
# boundary. Where the surface has a pixel the world renders as
# (world + water) >> 1; where it has none the world arrives whole. Move that
# edge up the beach and the sand it crosses becomes darker and cooler — WET
# SAND — and move it back and the sand is dry again. The animation and the
# colour math are one event: the PPU does the wet/dry shading, and nothing
# repaints a "wet" palette.
#
# THE BAND is tilemap rows 12..15, 32 px of shore. Rows 12 and 13 are beach in
# the world below — sand, its rock speckles, the meandering coast tiles — and
# rows 14 and 15 are the shallow bed, so one edge sweeping the band crosses
# both populations. Rows 0..11 are never covered, which is what keeps
# `test_above_the_waterline_the_world_is_at_full_intensity` a claim about a
# region that is dry BY CONSTRUCTION rather than by timing.
#
# THE MECHANISM IS RESIDENT PHASES, the pattern the highlight already proves
# one tile at a time. Every cell of the band points at a DISPLAY SLOT; the
# whole block of slots is rewritten from a ROM blob once per armed VBlank, so
# what changes is which resident bytes the map's cells are showing and not how
# much art is in flight. 16 slots x 32 B = one 512 B transfer against a
# measured 5952 B/frame VBlank budget — declared in water/feature.toml and
# proved by the allocator, not estimated here.
#
# THE PHASE IS INDEXED BY POSITION, exactly like the highlight: the surface's
# accumulated scroll is the rail's one region-correct quantity (the drift runs
# through TS_STEP), so a phase selected from it inherits that correctness with
# no clock of its own, freezes the instant B stills the drift, and closes on a
# whole number of pattern periods.
SURF_TOP_ROW = 12                       # the band's first tilemap row
SURF_ROWS = 4                           # ...and its height, in rows
SURF_CELLS = 4                          # the map's 4-cell horizontal pattern
SURF_SLOTS = SURF_ROWS * SURF_CELLS     # 16 display slots
SURF_BAND_PX = SURF_ROWS * 8            # 32 px of shore
SURF_BAND_TOP_PX = SURF_TOP_ROW * 8     # picture row 96
SURF_BAND_BOT_PX = SURF_BAND_TOP_PX + SURF_BAND_PX      # ...and 128
SURF_PHASES = 32
SURF_STEP_SHIFT = 2                     # one phase per 4 px of drift
SURF_STEP_PX = 1 << SURF_STEP_SHIFT
SURF_PERIOD_PX = SURF_PHASES * SURF_STEP_PX             # 128 px — the cycle
SURF_LIP_PX = 2                         # the crest lip at the water's edge

# THE CYCLE IS 128 px AND THAT IS A MULTIPLE OF 32, which is the whole reason
# the picture still repeats: the surface map's pattern is 4 cells = 32 px, the
# highlight's loop is 4 phases x 8 px = 32 px, and the map wraps at 256. A surf
# period that did not divide 256 and was not divided BY 32 would leave the
# gallery clip with a visible seam and the wrap case with nothing true to say.
assert SURF_PERIOD_PX % WAVE_PATTERN_PX == 0, (
    f"the surf cycle is {SURF_PERIOD_PX} px, which is not a whole number of "
    f"{WAVE_PATTERN_PX} px pattern periods — the picture would not repeat")
assert (32 * 8) % SURF_PERIOD_PX == 0, (
    f"the surf cycle is {SURF_PERIOD_PX} px, which does not divide the map's "
    f"256 px wrap — the surface would show a seam at the wrap")

# --- the schedule: SWASH FAST, BACKWASH SLOW, THEN A LULL --------------------
# `SURF_H[p]` is how far the water has advanced INTO the band, in pixels, at
# phase p. The base waterline sits at picture row SURF_BAND_BOT_PX - h, and the
# per-column edge profile pushes it back down from there.
#
# SURF IS NOT A SINE AND THE ASYMMETRY IS THE POINT. A wave's swash runs up the
# shore in a rush and decelerates as it climbs; the backwash draws down under
# gravity over several times as long; and between waves the shore drains and
# nothing much happens. A symmetric oscillation reads as a pulsing band rather
# than as water, which is exactly what this table exists not to be:
#
#   phases 0..5    the swash — 6 -> 32 px in five steps (20 frames), and the
#                  steps SHRINK: 7, 7, 6, 4, 2. The run-up decelerating.
#   phases 5..19   the backwash — 32 -> 8 px over fourteen steps (56 frames),
#                  a little under half the swash's rate.
#   phases 19..31  the lull — the shore drained, the edge idling at its low
#                  mark while the next wave gathers.
#
# It closes: SURF_H[31] is one step from SURF_H[0], so the cycle returns to its
# own starting profile and the gallery clip's join stays invisible.
SURF_H = [
    6, 13, 20, 26, 30, 32,                                       # the swash
    31, 29, 27, 25, 23, 21, 19, 17, 16, 14, 12, 11, 9, 8,        # the backwash
    8, 7, 7, 6, 6, 6, 7, 7, 6, 6, 6, 6,                          # the lull
]
assert len(SURF_H) == SURF_PHASES, (
    f"the schedule has {len(SURF_H)} entries and the loop has {SURF_PHASES}")

# The phase whose edge reproduces the surface's ORIGINAL static top: the water
# at h = 16 (base line on picture row 112, the top of tilemap row 14) wearing
# the jag profile the four removed tiles used to draw. Named because the tests
# that are about the rail's OTHER claims — the vofs geometry, the per-pixel
# edge — hold their picture still at it, so their assertions did not have to be
# rewritten around a moving edge.
SURF_REF_PHASE = 14
assert SURF_H[SURF_REF_PHASE] == 16, (
    f"the reference phase is h = {SURF_H[SURF_REF_PHASE]}, not the 16 that puts "
    f"the base waterline on the top of tilemap row 14")

# --- the edge profiles ------------------------------------------------------
# A per-column push-down, in pixels, over the pattern's 32 px period. Larger
# means the water reaches LESS far up that column, so the shape is read as a
# coastline seen from above rather than as a wave seen from the side.
#
# One shape per leg of the cycle, because a wave front and a draining backwash
# do not have the same edge: the front is rounded and shallow, the drain is
# ragged with deep notches where the water has already run off, and the lull is
# nearly calm. SURF_JAG is the shape the surface's four static top tiles used to
# draw, kept because the reference phase wears it.
SURF_JAG = [0, 1, 2, 3, 3, 2, 1, 2, 3, 4, 5, 5, 4, 3, 2, 2,
            3, 2, 2, 1, 1, 2, 3, 4, 4, 3, 3, 2, 1, 1, 0, 0]
SURF_FRONT = [0, 0, 1, 1, 2, 2, 2, 1, 1, 0, 0, 1, 2, 3, 3, 2,
              1, 1, 0, 0, 1, 1, 2, 2, 3, 2, 1, 1, 0, 0, 1, 2]
SURF_DRAIN = [1, 2, 4, 5, 5, 3, 1, 0, 1, 3, 5, 5, 4, 2, 1, 2,
              4, 5, 4, 2, 1, 1, 3, 5, 5, 3, 2, 1, 0, 1, 3, 4]
SURF_CALM = [1, 1, 2, 2, 1, 1, 0, 0, 1, 2, 2, 1, 1, 0, 0, 1,
             2, 2, 1, 1, 0, 1, 1, 2, 2, 1, 1, 0, 0, 1, 1, 2]
for _n, _p in (("jag", SURF_JAG), ("front", SURF_FRONT),
               ("drain", SURF_DRAIN), ("calm", SURF_CALM)):
    assert len(_p) == WAVE_PATTERN_PX, f"{_n} profile is {len(_p)} px"
    assert all(0 <= v <= 5 for v in _p), f"{_n} profile leaves 0..5"

# The lowest the water is ever allowed to sit is one pixel above the band's
# bottom line, or its edge would fall into tilemap row 16 — which the band does
# not own and cannot draw.
SURF_MAX_PUSH = max(max(SURF_JAG), max(SURF_FRONT),
                    max(SURF_DRAIN), max(SURF_CALM))
assert min(SURF_H) > SURF_MAX_PUSH, (
    f"h reaches {min(SURF_H)} but the edge pushes down {SURF_MAX_PUSH} px — the "
    f"waterline would leave the band's bottom")
assert max(SURF_H) <= SURF_BAND_PX, (
    f"h reaches {max(SURF_H)}, past the band's {SURF_BAND_PX} px")


def surf_profile(phase):
    """The per-column PICTURE ROW of the topmost water pixel, over 32 px.

    The shape is ROTATED by the phase so no two phases of the lull can hold the
    same bytes — the display slots are how a test recovers which phase is on
    screen, and two identical blocks would make that ambiguous. The rotation is
    zero at the reference phase, which is what keeps its edge byte-for-byte the
    jag the static tiles used to draw.
    """
    shape = (SURF_FRONT if phase <= 5 else
             SURF_DRAIN if phase <= 19 else SURF_CALM)
    if phase == SURF_REF_PHASE:
        shape = SURF_JAG
    rot = (phase - SURF_REF_PHASE) % WAVE_PATTERN_PX
    base = SURF_BAND_BOT_PX - SURF_H[phase]
    return [base + shape[(x + rot) % WAVE_PATTERN_PX]
            for x in range(WAVE_PATTERN_PX)]


# --- what the water looks like BELOW its edge -------------------------------
# The band's own fill, per row of the band and per cell of the pattern. Rows 12
# and 13 are FULLY OPAQUE by construction and that is load-bearing rather than
# decorative: the swash zone is where the wet/dry equality is asserted, so a
# transparent pixel there would be a bare main-screen colour in the middle of a
# region the test calls covered. A thin sheet of swash running up a beach is
# opaque; the gaps belong further out, where the ripple already has them.
SURF_STREAK_A = pic(WAT_LEGEND,
                    "tttttttt",
                    "tccctttt",
                    "tttttttt",
                    "ttttcccc",
                    "tttttttt",
                    "tttttttt",
                    "ttcccttt",
                    "tttttttt")
SURF_STREAK_B = pic(WAT_LEGEND,
                    "tttttttt",
                    "tttttccc",
                    "tttttttt",
                    "ttcccttt",
                    "tttttttt",
                    "tttttttt",
                    "cccttttt",
                    "tttttttt")
SURF_FILL = {
    0: (SURF_STREAK_A, flat(WAT_I_SH_TROUGH),
        SURF_STREAK_B, flat(WAT_I_SH_TROUGH)),
    1: (flat(WAT_I_SH_TROUGH), SURF_STREAK_B,
        flat(WAT_I_SH_TROUGH), SURF_STREAK_A),
    2: tuple(flat(WAT_I_SH_TROUGH) for _ in range(SURF_CELLS)),
    3: (WAT_TILES[WAT_T["sh_wave_a"]], WAT_TILES[WAT_T["sh_trough"]],
        WAT_TILES[WAT_T["sh_wave_b"]], WAT_TILES[WAT_T["sh_trough"]]),
}
for _r in range(SURF_ROWS - 1):
    for _c, _t in enumerate(SURF_FILL[_r]):
        assert all(v != 0 for row in _t for v in row), (
            f"the band's fill at row {_r} cell {_c} has a transparent pixel — "
            f"the swash zone's wet/dry equality would have a hole in it")


def surf_slot_tile(row, cell, top_px):
    """One display slot: transparent above the edge, water below it.

    The first SURF_LIP_PX rows of water in every column are the CREST colour —
    the lit lip a wave carries at its leading edge — and everything under that
    is the band row's own fill. The lip travels with the edge, which is what
    makes the advancing front read as a wave rather than as a rectangle
    growing.
    """
    y0 = SURF_BAND_TOP_PX + row * 8
    fill = SURF_FILL[row][cell]
    out = []
    for ty in range(8):
        y = y0 + ty
        line = []
        for u in range(8):
            top = top_px[cell * 8 + u]
            if y < top:
                line.append(0)
            elif y < top + SURF_LIP_PX:
                line.append(WAT_I_SH_CREST)
            else:
                line.append(fill[ty][u])
        out.append(line)
    return out


def surf_block(phase):
    """One phase's 16 slot tiles, in the order the map's cells read them."""
    top = surf_profile(phase)
    return [surf_slot_tile(r, c, top)
            for r in range(SURF_ROWS) for c in range(SURF_CELLS)]


# The slots themselves, resident in the surface's own CHR page. Their bytes in
# the blob are the REFERENCE phase, so a machine caught before its first armed
# VBlank shows the surface's original top edge rather than whatever the VRAM
# powered on holding.
SURF_SLOT0 = len(WAT_TILES)
for _i, _t in enumerate(surf_block(SURF_REF_PHASE)):
    wat_tile(f"surf_slot{_i:02d}", _t)
assert len(WAT_TILES) - SURF_SLOT0 == SURF_SLOTS

# =============================================================================
# the maps
# =============================================================================
MAP_DIM = 32

# --- BG1: the world --------------------------------------------------------
# THE WATERLINE, column by column. `LK_COAST_ROW[c]` is the tile row that
# carries the land/water boundary in column c; everything above it in rows
# 9..13 is beach and everything below is clear shallow water. The boundary
# therefore wanders over three tile rows — 24 px — and the coast tile in each
# column adds the sub-tile jag, so the eye reads terrain rather than a stripe.
LK_COAST_ROW = [12, 12, 13, 13, 12, 11, 11, 12, 13, 13, 13, 12, 12, 11, 12, 13,
                13, 12, 11, 11, 12, 12, 13, 13, 12, 12, 11, 12, 13, 13, 12, 12]
LK_COAST_TILE = ["coast_a", "coast_b", "coast_c", "coast_d", "coast_b",
                 "coast_r", "coast_a", "coast_c", "coast_b", "coast_d",
                 "coast_a", "coast_c", "coast_s", "coast_b", "coast_a",
                 "coast_d", "coast_c", "coast_b", "coast_r", "coast_a",
                 "coast_d", "coast_c", "coast_b", "coast_a", "coast_s",
                 "coast_c", "coast_d", "coast_b", "coast_a", "coast_c",
                 "coast_b", "coast_d"]

# The shelf's drop-off into open water, on the same scheme: the row that
# carries the break, and which of the two drop-off profiles draws it.
LK_DROP_ROW = [19, 19, 18, 18, 19, 20, 20, 19, 18, 18, 19, 20, 20, 19, 18, 18,
               19, 19, 20, 20, 19, 18, 18, 19, 20, 19, 18, 18, 19, 20, 19, 19]
LK_DROP_TILE = ["shelf_deep_a", "shelf_deep_b"]

# The clusters — silt, pebbles, sandbars, weed. Written as (row, col) so a
# reader can find any of them on screen, and placed off the pattern grid so
# they do not line up with the surface above them. Rows 25..27 carry none:
# that band is the horizontally UNIFORM bed the drift measurement needs.
LK_CLUSTERS = {
    (14, 3): "shelf_silt", (14, 11): "shelf_rock", (14, 21): "shelf_silt",
    (14, 27): "sandbar",
    (15, 6): "sandbar", (15, 7): "sandbar", (15, 14): "shelf_silt",
    (15, 24): "shelf_rock", (15, 30): "shelf_silt",
    (16, 1): "shelf_rock", (16, 9): "shelf_silt", (16, 17): "sandbar",
    (16, 18): "sandbar", (16, 26): "shelf_silt",
    (17, 4): "shelf_silt", (17, 12): "shelf_rock", (17, 22): "shelf_silt",
    (18, 8): "shelf_silt", (18, 28): "shelf_rock",
    (20, 2): "deep_silt", (20, 15): "deep_weed", (20, 25): "deep_silt",
    (21, 10): "deep_silt", (21, 19): "deep_rock", (21, 29): "deep_weed",
    (22, 5): "deep_rock", (22, 13): "deep_silt", (22, 23): "deep_weed",
    (23, 0): "deep_silt", (23, 8): "deep_weed", (23, 16): "deep_silt",
    (23, 27): "deep_rock",
    (24, 4): "deep_weed", (24, 12): "deep_silt", (24, 20): "deep_rock",
    (24, 31): "deep_silt",
}

# The hill ridge: which of the two horizon profiles each column carries.
LK_RIDGE = "abbaabbbaababbaabbaaabbabaabbaba"


def lk_cell(row, col):
    """The BG1 tile at one map cell. One function, so the world has one shape."""
    if row <= 5:
        return LK_T["sky"]
    if row == 6:
        return LK_T["horizon_a" if LK_RIDGE[col] == "a" else "horizon_b"]
    if row in (7, 8):
        return LK_T["hill_lit"] if (col * 5 + row * 3) % 7 < 3 else LK_T["hill"]
    if row == 9:
        return LK_T["hill_sand"]
    if row == 10:
        return LK_T["sand_rock"] if (col * 3) % 11 == 0 else LK_T["sand"]
    coast = LK_COAST_ROW[col]
    if row < 14:
        if row < coast:
            return LK_T["rock"] if (col * 7 + row) % 9 < 2 else LK_T["sand"]
        if row == coast:
            return LK_T[LK_COAST_TILE[col]]
        return LK_T["shelf"]
    cluster = LK_CLUSTERS.get((row, col))
    if cluster is not None:
        return LK_T[cluster]
    drop = LK_DROP_ROW[col]
    if row < drop:
        return LK_T["shelf"]
    if row == drop:
        return LK_T[LK_DROP_TILE[col & 1]]
    return LK_T["deep"]


# --- BG2: the surface ------------------------------------------------------
# EVERY ROW IS A 4-CELL PATTERN, REPEATED EIGHT TIMES, and that is the whole
# reason a 32 px displacement reproduces the picture exactly (see the module
# docstring). Rows 0..13 are empty: above the surface's coverage the sub screen
# has no pixel at all, which is the edge the tests read, and it is also what
# keeps the meandering waterline in rows 11..13 a boundary between two
# UNBLENDED populations. Row 14 is the jagged top. Row 21 is FULLY OPAQUE — the
# text line sits there, so every glyph pixel has a sub-screen pixel under it and
# would blend if BG3 were gated into the math. Rows 25..27 carry no highlight
# and sit over a uniform bed, so the drift there is a pure translation.
#
# ROWS 19 AND 21 ARE ONE TILE ACROSS THE WHOLE PATTERN, deliberately: the last
# shallow row and the calm strip the text sits on. A row whose surface is the
# same tile in every cell carries the SAME sub colour at every x WHATEVER the
# scroll is, which is what lets a test name a coordinate, name both
# contributors, and assert one composited value without first recovering where
# the surface has drifted to. Everywhere else the tests measure the layers as
# they actually are.
WAT_ROWS = {
    16: ("sh_trough", "sh_wave_b", "sh_trough", "sh_wave_a"),
    17: ("sh_wave_b", "sh_trough", "sh_wave_a", "sh_crest"),
    18: ("sh_trough", "sh_wave_a", "sh_trough", "sh_wave_b"),
    19: ("sh_trough", "sh_trough", "sh_trough", "sh_trough"),
    20: ("zone_a", "zone_b", "zone_c", "zone_d"),
    21: ("dp_trough", "dp_trough", "dp_trough", "dp_trough"),
    22: ("dp_trough", "glint_slot", "dp_wave_a", "dp_trough"),
    23: ("dp_wave_b", "dp_trough", "dp_wave_a", "dp_trough"),
    24: ("dp_trough", "dp_wave_b", "dp_trough", "glint_slot"),
    25: ("dp_wave_a", "dp_trough", "dp_wave_b", "dp_trough"),
    26: ("dp_trough", "dp_wave_a", "dp_trough", "dp_wave_b"),
    27: ("dp_wave_b", "dp_trough", "dp_wave_a", "dp_trough"),
}
# THE SWASH BAND, rows 12..15: every cell points at a DISPLAY SLOT and none of
# them ever changes. What changes is the 32 bytes behind each slot, rewritten
# from the phase blob once per armed VBlank — so the map is static, the phases
# are resident, and the wave is a question of which resident bytes the cells are
# showing. Rows 15's slots carry the ripple that used to be authored here
# directly; rows 12 and 13 did not exist as surface at all before the surf, and
# rows 0..11 still do not.
for _r in range(SURF_ROWS):
    WAT_ROWS[SURF_TOP_ROW + _r] = tuple(
        f"surf_slot{_r * SURF_CELLS + _c:02d}" for _c in range(SURF_CELLS))

# Rows 28..31 are off the bottom of a 224-line picture and repeat the last
# visible pattern rather than being left unwritten (power-on VRAM is random —
# rule 5).
for _r in range(28, MAP_DIM):
    WAT_ROWS[_r] = WAT_ROWS[27]

# The attribute halves of a tilemap word: BG1 authors palette group 0 and
# priority 0, so its word IS its tile id; BG2 authors palette group 2.
LK_ATTR = 0
WAT_ATTR = 2 << 10


def lk_map_words():
    return [lk_cell(row, col) | LK_ATTR
            for row in range(MAP_DIM) for col in range(MAP_DIM)]


def wat_map_words():
    out = []
    for row in range(MAP_DIM):
        pattern = WAT_ROWS.get(row)
        for col in range(MAP_DIM):
            tile = 0 if pattern is None else WAT_T[pattern[col & 3]]
            out.append(tile | WAT_ATTR)
    return out


# --- encoders --------------------------------------------------------------
def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3).

    Asserts rather than masks: an index outside 0..15 names its own pixel.
    """
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    for y, row in enumerate(rows):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} px, expected 8"
        for x, v in enumerate(row):
            assert 0 <= v <= 15, (
                f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
    out = bytearray()
    for pair in (0, 2):                      # planes 0/1, then planes 2/3
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                lo = (lo << 1) | ((v >> pair) & 1)
                hi = (hi << 1) | ((v >> (pair + 1)) & 1)
            out += bytes((lo, hi))
    assert len(out) == 32, f"{label}: encoded {len(out)} B, expected 32"
    return bytes(out)


def encode_words(words, label, count):
    assert len(words) == count, f"{label}: {len(words)} words, expected {count}"
    out = bytearray()
    for i, w in enumerate(words):
        assert 0 <= w <= 0xFFFF, f"{label}: entry {i} value {w:#06x} is not 16-bit"
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def encode_pal(words, label):
    for i, w in enumerate(words):
        assert 0 <= w <= 0x7FFF, (
            f"{label}: entry {i} value {w:#06x} is not a 15-bit BGR555 word")
    return encode_words(words, label, 16)


# --- the emitted layout ----------------------------------------------------
# A generated include whose SHAPE is load-bearing carries a format version and
# its consumer pins it (AGENTS.md, "A generated include carries a FORMAT
# VERSION"). What water.asm would otherwise have to re-narrate is exactly the
# four numbers below: which tile the map's twinkle cells point at, where the
# phases live, how many there are, and how far the surface drifts between
# them. Re-authoring the tiles moves these; the .assert stops a build that
# would have indexed the wrong bytes.
ART_FORMAT = 2                  # 2: the surf's layout joined the highlight's


def art_inc():
    return "".join(f"{line}\n" for line in [
        "; lk_art.inc — GENERATED by tools/gen_lakeside_assets.py. Do not edit.",
        ";",
        "; The surface's highlight tile: where its display slot is, where its",
        "; phases live, how many there are, and how far the surface drifts",
        "; between two of them. water.asm pins LK_ART_FORMAT and reads the rest",
        "; rather than narrating them a second time — a re-authored tile order",
        "; moves these numbers, and a consumer that had copied them would index",
        "; the wrong bytes with every gate still green.",
        ";",
        "; The two _SHIFT constants are the same numbers as their _PX / _BYTES",
        "; siblings: the consumer shifts by a build-time count and asserts the",
        "; pair agrees, so neither can be edited alone.",
        f"LK_ART_FORMAT       = {ART_FORMAT}",
        f"LK_GLINT_SLOT       = {WAT_T['glint_slot']}",
        f"LK_GLINT_SRC        = {WAT_T['glint_p0']}",
        f"LK_GLINT_PHASES     = {GLINT_PHASE_COUNT}",
        f"LK_GLINT_STEP_PX    = {GLINT_STEP_PX}",
        f"LK_GLINT_STEP_SHIFT = {GLINT_STEP_SHIFT}",
        f"LK_GLINT_TILE_BYTES = {GLINT_TILE_BYTES}",
        f"LK_GLINT_TILE_SHIFT = {GLINT_TILE_SHIFT}",
        f"LK_GLINT_TILE_WORDS = {GLINT_TILE_BYTES // 2}",
        ";",
        "; The surf: where the swash band's display slots are, how big one",
        "; phase's block of them is, how many phases there are and how far the",
        "; surface drifts between two of them. Same contract as the highlight's",
        "; — the consumer shifts by a build-time count and asserts the shift",
        "; agrees with its _PX / _BYTES sibling.",
        f"LK_SURF_SLOT        = {SURF_SLOT0}",
        f"LK_SURF_SLOT_WORDS  = {SURF_SLOT0 * (GLINT_TILE_BYTES // 2)}",
        f"LK_SURF_SLOTS       = {SURF_SLOTS}",
        f"LK_SURF_PHASES      = {SURF_PHASES}",
        f"LK_SURF_STEP_PX     = {SURF_STEP_PX}",
        f"LK_SURF_STEP_SHIFT  = {SURF_STEP_SHIFT}",
        f"LK_SURF_BLOCK_BYTES = {SURF_SLOTS * GLINT_TILE_BYTES}",
        f"LK_SURF_BLOCK_SHIFT = {(SURF_SLOTS * GLINT_TILE_BYTES).bit_length() - 1}",
        f"LK_SURF_PERIOD_PX   = {SURF_PERIOD_PX}",
        f"LK_SURF_TOP_ROW     = {SURF_TOP_ROW}",
        f"LK_SURF_ROWS        = {SURF_ROWS}",
        f"LK_SURF_REF_PHASE   = {SURF_REF_PHASE}",
    ])


# --- the property the tests depend on --------------------------------------
def half_add(main, sub):
    """The PPU's half-add, per 5-bit channel: min((main + sub) >> 1, 31).

    Mesen2 SnesPpu.cpp:1372-1377. Written here so the generator can prove the
    palette keeps the results distinguishable; the tests derive their own
    expectations from CGRAM rather than importing this.
    """
    return tuple(min((a + b) >> 1, 31) for a, b in zip(main, sub))


def full_add(main, sub):
    """The same pixel with CGADSUB's halve bit clear — what a defect looks like."""
    return tuple(min(a + b, 31) for a, b in zip(main, sub))


SUBMERGED = {"shelf": SHELF, "shelf_dk": SHELF_DK, "sandbar": SANDBAR,
             "subrock": SUBROCK, "subrock_lit": SUBROCK_LIT,
             "deep": DEEP, "deep_dk": DEEP_DK}
DRY = {"backdrop": BACKDROP, "sky": SKY, "hill": HILL, "hill_lit": HILL_LIT,
       "sand": SAND, "rock": ROCK, "rock_lit": ROCK_LIT}

# THE BEACH IS NOW A MAIN OPERAND TOO, and that is what the surf changed about
# this file. Before it, the surface's map was empty above tilemap row 14 and
# the only main-screen colours the blender ever saw were submerged ones; the
# beach was dry by construction. The swash band covers tilemap rows 12 and 13,
# whose world is sand, its rock speckles and the meandering coast tiles — so
# sand, rock and its lit face are wettable, and every property below has to
# hold over them as well. It did not, at first: ROCK_LIT and SUBROCK_LIT
# differed by one step in two channels, >>1 threw the difference away, and
# their half-adds were the same colour (a P3 collision). ROCK_LIT moved one
# step. That is the palette paying for the feature, priced at author time
# rather than discovered as an untestable pixel.
WETTABLE = dict(SUBMERGED)
WETTABLE.update({"sand": SAND, "rock": ROCK, "rock_lit": ROCK_LIT})
SURFACE = {"sh_crest": SH_CREST, "sh_trough": SH_TROUGH,
           "dp_crest": DP_CREST, "dp_trough": DP_TROUGH, "glint": GLINT}


def assert_blend_colours_are_distinguishable():
    """Four properties over the WHOLE cross product, proved at author time.

    The flat-band version of this rail had four composited colours and one
    property to check. Tile art has thirty-five, and the properties the tests
    spend are no longer the same one:

      P1  the raw main colours are pairwise distinct — otherwise two beds are
          one bed and half the picture's assertions are about nothing;
      P2  no half-add equals ANY raw colour, dry or submerged. This is the one
          the region-wide case rests on: it is what makes "this pixel is not
          explicable as an unblended world pixel" a decidable question;
      P3  every half-add is distinct from every other, so a spot check names
          one (main, sub) pair rather than a class of them;
      P4  no FULL add lands on a legal value, which is what lets
          `test_the_half_add_is_not_a_full_add` assert an ABSENCE.

    Returns the map of names to colours, half-adds included, so the caller can
    print what it proved.
    """
    named = dict(WETTABLE)
    named.update(DRY)
    blends = {}
    for m, mc in WETTABLE.items():
        for s, sc in SURFACE.items():
            blends[f"{m}+{s}"] = half_add(mc, sc)

    # P1 — the raw colours (dry and submerged) are pairwise distinct.
    seen = {}
    for name, colour in named.items():
        clash = seen.get(colour)
        assert clash is None, (
            f"P1 palette collision: '{name}' and '{clash}' are both {colour} — "
            f"two world colours a test could not tell apart")
        seen[colour] = name

    # P2 — no half-add equals a raw colour.
    for name, colour in blends.items():
        clash = seen.get(colour)
        assert clash is None, (
            f"P2 palette collision: the blend '{name}' is {colour}, which is "
            f"also the raw colour '{clash}' — a test could not tell a blended "
            f"pixel from an unblended one")

    # P3 — the half-adds are pairwise distinct.
    seen_blend = {}
    for name, colour in blends.items():
        clash = seen_blend.get(colour)
        assert clash is None, (
            f"P3 palette collision: the blends '{name}' and '{clash}' are both "
            f"{colour} — a spot check there would name a class, not a pair")
        seen_blend[colour] = name

    # P4 — no full add lands on a legal value.
    legal = set(blends.values()) | set(named.values())
    for m, mc in WETTABLE.items():
        for s, sc in SURFACE.items():
            fa = full_add(mc, sc)
            assert fa not in legal, (
                f"P4 palette collision: the FULL add of '{m}' and '{s}' is "
                f"{fa}, which is a legal composited value — "
                f"`test_the_half_add_is_not_a_full_add` would be vacuous")

    named.update(blends)
    return named


def main(outdir):
    blend = assert_blend_colours_are_distinguishable()
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "lk_chr.bin": b"".join(encode_4bpp(t, f"lk tile {i}")
                               for i, t in enumerate(LK_TILES)),
        "lk_map.bin": encode_words(lk_map_words(), "lk map", MAP_DIM * MAP_DIM),
        "lk_pal.bin": encode_pal(LK_PAL, "lk palette"),
        "wat_chr.bin": b"".join(encode_4bpp(t, f"wat tile {i}")
                                for i, t in enumerate(WAT_TILES)),
        "wat_map.bin": encode_words(wat_map_words(), "wat map",
                                    MAP_DIM * MAP_DIM),
        "wat_pal.bin": encode_pal(WAT_PAL, "wat palette"),
        # THE SURF'S PHASES, resident in ROM and DMA'd into the band's display
        # slots one block per armed VBlank. Emitted in phase order so the
        # consumer's source address is `blob + phase * BLOCK`, which is one
        # shift and one add of a quantity the rail already keeps.
        "surf_chr.bin": b"".join(
            b"".join(encode_4bpp(t, f"surf phase {ph} slot {i}")
                     for i, t in enumerate(surf_block(ph)))
            for ph in range(SURF_PHASES)),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")
    # EVERY PHASE'S BLOCK IS DISTINCT, and that is a property the tests spend
    # rather than a tidiness check: the display slots are how a case recovers
    # which phase is on screen without consulting an engine word, and two
    # identical blocks would make that recovery ambiguous exactly where the
    # lull holds the schedule still. The edge profile's per-phase rotation is
    # what buys it.
    blocks = {}
    for ph in range(SURF_PHASES):
        raw = b"".join(encode_4bpp(t, f"surf phase {ph}")
                       for t in surf_block(ph))
        clash = blocks.get(raw)
        assert clash is None, (
            f"surf phases {ph} and {clash} hold identical bytes — a test could "
            f"not tell which one is on screen")
        blocks[raw] = ph

    (out / "lk_art.inc").write_text(art_inc())
    print(f"  lk_art.inc: format {ART_FORMAT}, "
          f"glint slot {WAT_T['glint_slot']} <- {GLINT_PHASE_COUNT} phase(s) "
          f"at {WAT_T['glint_p0']}, one every {GLINT_STEP_PX} px")
    print(f"  {len(LK_TILES)} BG1 tile(s), {len(WAT_TILES)} BG2 tile(s)")
    heights = [surf_profile(ph) for ph in range(SURF_PHASES)]
    lo = min(min(h) for h in heights)
    hi = max(max(h) for h in heights)
    print(f"  surf: {SURF_PHASES} phase(s) x {SURF_SLOTS} slot(s) at tile "
          f"{SURF_SLOT0}, one every {SURF_STEP_PX} px, cycle "
          f"{SURF_PERIOD_PX} px; the waterline sweeps picture rows {lo}..{hi}")
    print(f"  distinguishable: {len(WETTABLE)} wettable main colour(s) x "
          f"{len(SURFACE)} surface colour(s) = "
          f"{len(WETTABLE) * len(SURFACE)} composited value(s), P1-P4 hold")
    for name in ("shelf+sh_crest", "deep+dp_trough", "subrock+dp_crest",
                 "deep+glint"):
        print(f"  half-add {name} = {blend[name]}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
