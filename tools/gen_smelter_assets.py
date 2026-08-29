#!/usr/bin/env python3
"""Assets for the `smelter` rail — a foundry floor where every 8-pixel column
scrolls on its own, out of BG3's tilemap and not out of an HDMA channel.

THREE KINDS OF OUTPUT, and the third is the point of the rail.

  the PLATES   BG1 4bpp tile art: steel plates, and nothing else. BG1 is
               TRANSPARENT everywhere a plate is not, which is what lets a
               per-column vertical offset move one plate without moving the
               world behind it.

  the MELT     BG2 4bpp tile art: a cavern wall with no horizontal feature in
               it at all -- IN THE TILE **AND** IN THE MAP, which took two
               goes: see melt_map -- a bright crust line, and the melt below. The wall's
               vertical uniformity is deliberate and load-bearing: displacing
               a column of it shows nothing, so the ONLY thing a viewer (or a
               test) can see move is the crust — which is exactly the edge the
               per-column equality is asserted on.

  the TABLE    `smt_col.bin` — SMT_PHASES complete 32-word BG3 offset rows,
               plus a flat control, at a 64 B stride. Each word is one
               column's vertical scroll for one layer, with the enable bit
               that says WHICH layer (bit 13 = BG1, bit 14 = BG2).

OFFSET-PER-TILE, AND WHY IT IS NOT AN HDMA EFFECT. In modes 2, 4 and 6 the
PPU stops reading BG3's tilemap as tiles: for every 8-pixel column it fetches
a word out of it and uses it as that column's scroll (Mesen2
Core/SNES/SnesPpu.cpp, GetHorizontalOffsetByte / GetVerticalOffsetByte at
:257-276, applied in GetTilemapData at :153-169). The whole mechanism runs out
of the ordinary tilemap fetch a layer already pays for, so it costs ZERO HDMA
channels and zero per-scanline CPU. What it costs is the VBlank upload of the
row — 64 B a frame here — and that is the entire per-frame price of every
column on screen moving independently.

ONE VALUE A COLUMN, TWO GATES. A column's word carries ONE offset and two
enable bits, so BG1 and BG2 can each be gated in or out of it but they cannot
be displaced by DIFFERENT amounts in the same column. That is not a limitation
this file works around, it is the shape it is designed to: the plate columns
drive BG1 and the gap columns drive BG2, so the melt is calm under the plates
and erupts in the gaps the player has to jump.

THE OFFSET REPLACES THE SCROLL, it does not add to it (vScroll = word & $3FF,
SnesPpu.cpp:167), so every number in this table is an ABSOLUTE position, and a
column whose enable bit is clear falls back to its layer's own BGnVOFS.
"""
import math
import pathlib
import sys

from PIL import Image

# --------------------------------------------------------------------------
# geometry — every number here is emitted into smt_art.inc, never restated
# --------------------------------------------------------------------------
COLS = 32                    # 256 px / 8: one offset word each, on SCREEN

# --------------------------------------------------------------------------
# THE WORLD, AND WHY IT COSTS NOTHING TO SCROLL
# --------------------------------------------------------------------------
# THE LEVEL IS THE OFFSET TABLE. The table is already one word per column per
# frame; making it WORLD-space rather than screen-space is the whole of the
# scrolling design. The DMA still moves 32 words into BG3's V row every VBlank
# — the camera only moves where it READS FROM. Same 64 B, same one transfer,
# same zero cycles during active display, and no tilemap streaming anywhere.
#
# BG1 AND BG2'S MAPS STAY 32 COLUMNS AND REPEAT EVERY 256 PX. The melt repeats
# invisibly because it is uniform; the plates' ART repeats too, so a plate slot
# exists at the same four column groups in every screen — and what varies
# across the world is the WORD each column gets, which is where every plate's
# height, period and phase live. A level designed in the table needs no new
# claim, no new blob shape and no streaming engine.
SCREENS = 4                  # ...so the world is 1,024 px wide
WORLD_COLS = COLS * SCREENS  # 128 offset words a row

# THE LEAD COSTS ONE COLUMN OF WORLD, and this is where it is paid. The DMA
# reads WORLD columns cam+1 .. cam+32 (the one-column lead, below), so the
# camera can reach cam = WORLD_COLS - COLS - 1 and no further without running
# off the row's end. The last world column is therefore never displaced, and
# the world is 8 px shorter than the arithmetic above suggests. Stated rather
# than padded: a 129-word row would double the stride to keep it a power of two
# and waste 16 KB to buy one column nobody stands on.
CAM_COL_MAX = WORLD_COLS - COLS - 1
WORLD_W = (CAM_COL_MAX + COLS) * 8

PHASES = 64                  # the animation loop
PHASE_SHIFT = 8              # stride 256 B -> a phase is (index << 8)
STRIDE = 1 << PHASE_SHIFT
assert STRIDE == WORLD_COLS * 2, "the phase stride must be one whole world row"

# BG1 — the plates. A 32x64 map (512 px tall) so no scroll value in range ever
# wraps; the plate band is two rows, and its TOP is the edge everything is
# measured against.
PLAT_MAP_ROW = 40
PLAT_TOP_PX = PLAT_MAP_ROW * 8          # 320
PLAT_BASE = 240                          # screen y = 320 - 240 = 80
PLAT_AMP = 40                            # ...so y travels 40..120

# Four plates, each four columns (32 px) wide: (first column, width).
# The GAPS between them are where the melt erupts, which is the same fact as
# "a column drives one layer or the other" seen from the picture's side.
PLATES = ((3, 4), (11, 4), (19, 4), (27, 4))

# --------------------------------------------------------------------------
# THE COURSE — sixteen plate slots, and the level design lives here
# --------------------------------------------------------------------------
# BG1's map repeats every 32 columns, so the four groups above are plate ART in
# every screen: sixteen slots across the world. Which of them a player can
# actually use, and when, is entirely these three tuples — a level expressed as
# per-slot motion rather than as geometry.
#
# THE JUMP IS THE DESIGN CONSTRAINT AND IT IS MEASURED, NOT GUESSED. Apex is
# v^2/2g = 50 px over ~40 frames of flight, which at 2 px a frame carries 80 px
# horizontally; slots are 64 px apart, so a NEIGHBOURING slot is always
# reachable and the difficulty is never distance. It is HEIGHT: the slots span
# 80 px of travel, more than a jump's apex, so a plate that is high when you
# arrive has to be waited for. That is the mechanic the moving plates buy, and
# the course is written to use it — screen 0 is gentle and in step, and the
# amplitudes widen and the periods diverge as the world goes right.
#
# Slot 0 is the spawn and is deliberately the calmest thing in the level.
SLOT_FREQ = (1, 2, 1, 3,      # screen 0 — the picture the rail always had
             2, 1, 3, 2,      # screen 1 — periods start to diverge
             3, 1, 2, 3,      # screen 2 — and the amplitudes open up
             1, 3, 2, 1)      # screen 3
# THE AMPLITUDES ARE THE DIFFICULTY CURVE, and they were measured against a
# player rather than guessed. A jump's apex is 50 px; a slot that travels more
# than that can be HIGH when you arrive, and then the only way across is to
# wait for it — the mechanic the moving plates exist for. Screens 0-2 stay
# inside the reach so a run can be crossed on rhythm alone; screen 3 opens up
# past it, so the far side is where timing starts to matter and where a player
# who is only jumping loses the knight. Measured by driving it: a
# a run that waits for the target plate crosses 2.5 screens and dies on
# screen 3. The bound on screens 0-2 is the APEX: two neighbours at amplitude a
# can differ by up to 2a, and a jump only climbs 32 px, so a > 26 makes a
# crossing depend on catching the pair in phase rather than on timing one jump.
# Measured by driving it, not chosen: at 28-34 a waiting run died at x=434.
SLOT_AMP = (22, 24, 22, 26,      # screen 0 — the picture the rail always had
            24, 22, 26, 24,      # screen 1
            26, 24, 22, 26,      # screen 2
            52, 46, 58, 40)      # screen 3 — past the apex; wait or fall
SLOT_OFF = (0.00, 0.25, 0.50, 0.10,
            0.60, 0.35, 0.85, 0.15,
            0.45, 0.70, 0.05, 0.55,
            0.30, 0.80, 0.20, 0.65)
assert len(SLOT_FREQ) == len(SLOT_AMP) == len(SLOT_OFF) == SCREENS * len(PLATES)

# BG2 — the melt. Same map shape. Rows 0..31 are wall, row 32 is the crust,
# 33..63 the body: the crust's top pixel is the measurable edge.
CRUST_MAP_ROW = 32
CRUST_TOP_PX = CRUST_MAP_ROW * 8        # 256
MELT_BASE = 126                          # screen y = 256 - 126 = 130
MELT_AMP = 40                            # a jet lifts the crust to y = 90
MELT_RIPPLE = 4                          # ...and nothing is ever perfectly
                                         #    still, which is what keeps a
                                         #    gallery clip from reading as a
                                         #    frozen frame
# The jets, one per gap between plates (and the two screen edges), each with
# its own frequency and phase. RECTIFIED: a jet rises out of the surface and
# falls back to it rather than dipping below, because a jet that went down
# would read as a hole.
#
# THE GAPS ARE DELIBERATELY UNEQUAL — 3, 4, 4, 4 and 1 columns wide — and the
# odd ones are the sharpest thing in the picture. A jet's amplitude is an arch
# across its run (0 at the edges, 1 in the middle), so a 4-wide gap lifts two
# columns together, a 3-wide gap lifts EXACTLY ONE while both its neighbours
# hold still, and the 1-wide gap at the right edge is a single 8-pixel column
# of melt standing alone. That is the whole claim of the mechanism made
# visible: the granularity is one column, not one layer and not one band.
JET_FREQ = (1, 2, 1, 2, 3)
JET_OFF = (0.00, 0.35, 0.62, 0.18, 0.80)

# The enable bits, from the hardware. They are ALSO emitted by the allocator
# as ES_OPT_WORKS_BG1 / _BG2 and the ASM builds nothing from these — this file
# needs them because it is the thing that writes the words.
BIT_BG1 = 0x2000
BIT_BG2 = 0x4000

# --------------------------------------------------------------------------
# palettes (BGR555)
# --------------------------------------------------------------------------
def rgb(r, g, b):
    return (b << 10) | (g << 5) | r


# Group 0 — BG1's plates. Word 0 is the 4bpp transparent slot AND the hardware
# backdrop at once, which is why this group is claimed with `at = 0`: one word,
# two meanings, one owner. Nothing ever sees it here (BG2 is opaque across the
# whole picture), and it is claimed anyway because the hardware does not care
# what we expect to see.
PAL_PLATE = [
    rgb(2, 2, 4),        # 0 backdrop / transparent
    rgb(7, 8, 10),       # 1 plate shadow
    rgb(13, 14, 16),     # 2 plate body
    rgb(20, 21, 23),     # 3 plate highlight
    rgb(26, 27, 28),     # 4 plate top edge
    rgb(9, 6, 4),        # 5 rust
    rgb(4, 4, 6),        # 6 plate underside
    rgb(16, 12, 6),      # 7 rivet
] + [0] * 8

# --------------------------------------------------------------------------
# THE WALL'S OWN INDEX RANGE — what makes a colour rotation move a PATTERN
# --------------------------------------------------------------------------
# The wall used to be two indices, dark and light, with the streaks drawn into
# the TILE. Two indices cannot flow: rotating two colours is a flicker, not a
# direction. So the wall now spends EIGHT indices, one per pixel column of its
# tile, and carries no pattern in its pixels at all — the pattern lives in the
# PALETTE, and rotating the eight colours walks it across the screen.
#
# That is the classic trick and it is the only one available here, because the
# wall is the one surface that cannot be CHR-animated: it has to be invariant
# under vertical displacement (see `melt_map`), and every animation frame would
# have to be vertically uniform. A PALETTE cycle does not touch a pixel, so the
# invariance is untouched by construction rather than by care.
#
# 8..15 IS FREE SPACE IN THIS GROUP and that is why the range is private: the
# melt's own indices 3..7 are what every per-column measurement in
# tests/test_smelter.py resolves the crust by, and a cycle that reached them
# would be moving the instrument rather than the picture. The wall cycling in
# 8..15 cannot touch 3..7 by construction. `wall_ramp` asserts the two families
# stay far apart in RGB as well, so a wall pixel can never be nearest-matched to
# the crust's index.
WALL_IX0 = 8                 # the wall's first palette index
WALL_SHADES = 8              # ...and this many of them, spread over
WALL_PX_PER_SHADE = 4        # ...this many pixels each, so the travelling
                             #   band's spatial period is 32 px. It was 1
                             #   px a shade — an 8-px period — and at ~11
                             #   px/s that read as shimmer, not as flow
WALL_PERIOD = WALL_SHADES * WALL_PX_PER_SHADE
WALL_TILES = WALL_PERIOD // 8   # ...so the run is this many tiles long
WALL_DARK = (3, 2, 5)        # the ramp's ends, in 5-bit BGR555 components
WALL_LIGHT = (6, 5, 10)      # ...and the span is DELIBERATELY narrow: the
                             #   first pass ran to (9, 8, 14) and the wall
                             #   read as a bold barber-pole competing with
                             #   the plates. A background that announces
                             #   itself is not a background — the flow has
                             #   to be legible when looked at and ignorable
                             #   when not


def wall_ramp(k):
    """The eight colours entries 8..15 hold at cycle step k.

    A raised cosine between the two ends, ROTATED by k, so what travels is a
    smooth band of lightness rather than a hard edge — and rotation is what
    makes the cycle close exactly at WALL_SHADES with nothing to hide.
    """
    out = []
    for i in range(WALL_SHADES):
        t = (1 - math.cos(2 * math.pi * ((i - k) % WALL_SHADES) / WALL_SHADES)) / 2
        out.append(rgb(*(int(round(a + (b - a) * t))
                         for a, b in zip(WALL_DARK, WALL_LIGHT))))
    return out


# Group 1 — BG2's cavern and melt.
PAL_MELT = [
    rgb(0, 0, 0),        # 0 unused (BG2 is opaque everywhere)
    rgb(0, 0, 0),        # 1 unused — the wall left for 8..15
    rgb(0, 0, 0),        # 2 unused — as above
    rgb(31, 30, 14),     # 3 crust white-hot
    rgb(31, 20, 2),      # 4 crust orange
    rgb(28, 9, 0),       # 5 melt bright
    rgb(20, 4, 0),       # 6 melt mid
    rgb(12, 1, 0),       # 7 melt dark
] + wall_ramp(0)


# --------------------------------------------------------------------------
# tiles — 8x8 index grids
# --------------------------------------------------------------------------
def solid(v):
    return [[v] * 8 for _ in range(8)]


def wall_tile(k):
    """Tile `k` of the cavern wall's WALL_TILES-long run: every row identical,
    every FOUR pixel columns one palette index. It carries no pattern — the
    pattern is in the palette, and `wall_ramp` walks it sideways.

    EVERY ROW IDENTICAL IS THE LOAD-BEARING PART, and it is why the wall gets
    its motion from a colour rotation rather than from a CHR swap: one offset
    word displaces a whole column of BG2, so a wall with any horizontal
    feature slides that feature past the screen as the melt rises. The rail
    shipped exactly that once — a uniform tile whose MAP alternated two streak
    phases per row, which is a horizontal seam every 8 pixels — and a human
    caught it in the gallery clip. Alternating on the COLUMN, as this run does,
    is the safe axis: a column of identical rows stays identical however far it
    is displaced.

    FOUR TILES AND FOUR PIXELS A SHADE, WHICH IS THE POINT OF THIS SHAPE. The
    first version put all eight shades across ONE tile — one pixel each — so
    the travelling band had a spatial period of 8 px, and at the cycle's rate
    that is a bright column every 8 pixels crawling about 11 px a second. It
    read as shimmer rather than as flow: there was nothing big enough for the
    eye to track. Spreading the same eight shades over 32 px gives the band a
    period four times longer and a shape you can follow, for three more tiles
    of CHR, no new palette entries, no new claim and no change to the
    mechanism.
    """
    row = [WALL_IX0 + ((k * 8 + x) // WALL_PX_PER_SHADE) % WALL_SHADES
           for x in range(8)]
    return [list(row) for _ in range(8)]


def crust_tile(seed):
    """The melt's surface: two white-hot rows over orange over the body. The
    TOP row is the edge every measurement lands on, so it is the brightest
    thing in the palette and it is unbroken across the tile."""
    rows = [[3] * 8, [3 if (x + seed) % 3 else 4 for x in range(8)],
            [4] * 8, [4 if (x + seed) % 4 else 5 for x in range(8)],
            [5] * 8, [5 if (x * 3 + seed) % 5 else 6 for x in range(8)],
            [6] * 8, [6 if (x + seed) % 3 else 5 for x in range(8)]]
    return rows


# THE BUBBLE FIELD. Two per body tile, born at different steps, each rising one
# row a step and living five of the eight — so at any moment a tile holds nought,
# one or two of them at different sizes and the lava reads as boiling rather than
# as a texture sliding.
#
# THE CYCLE IS THE CONSTRAINT, not the look. Everything in this rail's animation
# closes exactly at MELT_ANIM_FRAMES so the gallery clip's seam stays shut and
# frame 0 of the swap IS the static CHR the boot upload writes. Ages are taken
# modulo 8 and the rise is modulo 8, so step 8 is step 0 by construction — the
# same property the rotations had, kept when they were replaced.
#
# (x, y at birth, the step it is born on) — per body seed, so the two body tiles
# bubble out of phase and a wall of them does not pulse in unison.
# Declared here rather than read off MELT_ANIM_FRAMES because that constant is
# defined with the animation, further down. The two are asserted equal at the
# point the second one exists, so they cannot drift apart in silence.
MELT_BUBBLE_CYCLE = 8
MELT_BUBBLES = {
    0: ((2, 7, 0),),
    5: ((5, 7, 3),),
}
MELT_BUBBLE_LIFE = 5            # ...of MELT_ANIM_FRAMES steps
# radius by age: a bead rising, swelling for two steps, then gone. Kept SMALL
# on purpose — the body tile repeats across the whole lava, so a bubble is not
# one bubble, it is one every eight pixels. A 3x3 blob at that density stops
# reading as lava and starts reading as a honeycomb; measured by looking.
MELT_BUBBLE_R = (0, 0, 1, 1, 0)


def melt_tile(seed, k=0):
    """The lava body at animation step `k`.

    The texture is the same dither it always was; what moves is the bubbles.
    They are drawn AFTER it in indices the body already uses (7 for the film,
    5 for the rim), so no new colour enters the tile and `crust_y` — which
    finds the melt's surface by nearest match to the crust's index 3 — has
    nothing new to find. The assertion in `melt_anim` checks that, per frame.
    """
    rows = []
    for y in range(8):
        rows.append([5 if ((x * 5 + y * 3 + seed) % 11 == 0) else
                     (7 if ((x + y * 2 + seed) % 9 == 0) else 6)
                     for x in range(8)])
    for bx, by, born in MELT_BUBBLES[seed]:
        age = (k - born) % MELT_BUBBLE_CYCLE
        if age >= MELT_BUBBLE_LIFE:
            continue                    # not in the world this step
        cy = (by - age) % 8
        r = MELT_BUBBLE_R[age]
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy > r * r:
                    continue            # a plus, not a square block
                x, y = (bx + dx) % 8, (cy + dy) % 8
                # bright film in the middle, darker rim around it — which is
                # what makes a 3x3 blob read as a bubble and not as a blot
                core = (dx == 0 and dy == 0)
                rows[y][x] = 7 if (core or r == 0) else 5
    return rows


def plate_top(kind):
    """kind: 0 left end, 1 middle, 2 right end. Row 0 is the plate's TOP EDGE
    and it is a single bright line across the tile — the same reason the crust
    is: this is the edge the per-column assertion reads."""
    rows = [[4] * 8, [3] * 8,
            [2, 2, 3, 2, 2, 2, 3, 2],
            [2] * 8,
            [2, 7, 2, 2, 2, 2, 7, 2],
            [1] * 8, [1] * 8, [1, 1, 1, 5, 5, 1, 1, 1]]
    if kind == 0:
        for y in range(8):
            rows[y][0] = 0 if y >= 6 else 4
    if kind == 2:
        for y in range(8):
            rows[y][7] = 0 if y >= 6 else 4
    return rows


def plate_under(kind):
    rows = [[6 if (x + y) % 5 else 1 for x in range(8)] for y in range(8)]
    for y in range(8):
        if y >= 5:
            rows[y] = [0] * 8
    if kind == 0:
        for y in range(5):
            rows[y][0] = 0
    if kind == 2:
        for y in range(5):
            rows[y][7] = 0
    return rows


# BG1's tiles: 0 must be fully transparent — every column that is not a plate
# shows it at every row, which is what makes BG1 a layer carrying four movable
# objects rather than a picture.
PLATE_TILES = [
    ("clear", solid(0)),
    ("top_l", plate_top(0)), ("top_m", plate_top(1)), ("top_r", plate_top(2)),
    ("und_l", plate_under(0)), ("und_m", plate_under(1)),
    ("und_r", plate_under(2)),
]
# THE WALL RUN COMES FIRST so the four ANIMATED tiles stay contiguous and last
# — `smt_nmi_melt` moves them as ONE transfer, and MELT_ANIM_FIRST below is
# derived from this order rather than typed beside it.
MELT_TILES = [(f"wall_{k}", wall_tile(k)) for k in range(WALL_TILES)] + [
    ("crust_a", crust_tile(0)), ("crust_b", crust_tile(2)),
    ("melt_a", melt_tile(0, 0)), ("melt_b", melt_tile(5, 0)),
]

# --------------------------------------------------------------------------
# THE MELT'S CHR ANIMATION — the same tilemap, different pixels
# --------------------------------------------------------------------------
# The classic BG animation: the map never changes, and a VBlank transfer swaps
# the CHR under it. Four tiles, eight frames, 128 B a frame — the lava churns
# with no extra tilemap traffic and no second layer.
#
# WHICH FOUR, AND WHY NOT THE WALL. The animated block is the crust pair and
# the body pair, which sit CONTIGUOUSLY in the shared CHR claim (slots 9..12),
# so the whole swap is ONE transfer. The wall is deliberately left out and it
# is the one surface here that could not have joined: it has to be invariant
# under vertical displacement (see `melt_map`), which forces every one of its
# frames to be vertically uniform, and it would also make
# `test_the_wall_does_not_move_when_its_column_does` unable to tell "the wall
# moved" from "the wall animated" without pinning both frames to one animation
# bucket. The lava is under no such constraint: it is SUPPOSED to move with its
# column, so a texture that changes as it moves reads as molten rather than as
# a defect. Motion belongs where the constraint is not.
#
# BOTH MOTIONS CLOSE EXACTLY AT FRAME 8, which is what keeps the gallery clip's
# loop seam at zero. The crust's rows rotate HORIZONTALLY and the body's rotate
# VERTICALLY: a rotation by 8 of an 8-wide, 8-tall tile is the identity, so
# frame 8 IS frame 0 with no discontinuity to hide. A seed-drift animation
# (varying `crust_tile`'s dither seed) was the obvious first idea and does not
# close — its periods are 3, 4 and 5, so eight frames land mid-cycle and the
# wrap is a visible jump.
#
# AND THE CRUST'S ROW 0 SURVIVES BY CONSTRUCTION, not by care. It is the single
# bright unbroken line every per-column measurement in tests/test_smelter.py
# lands on (`CRUST_IX`), so an animation that disturbed it would take the whole
# module down. A HORIZONTAL rotation of a uniform row is that row, so the
# invariant needs no special case -- and it is asserted below anyway, because
# "it happens to be safe" is not a thing to leave unstated in the one place a
# future frame set gets added.
# TICK: ok -- an ANIMATION frame count, indexed by the already-scaled PHASE and
#   never by a hardware frame. `smt_nmi_melt` computes (phase >> SHIFT) & 7 and
#   counts nothing, so a change of tick rate leaves this table correct.
MELT_ANIM_FRAMES = 8            # ...and 8 is also the rotation's own period
assert MELT_BUBBLE_CYCLE == MELT_ANIM_FRAMES, \
    "the bubbles' period is not the animation's — step 8 would not be step 0"
MELT_ANIM_SHIFT = 1             # frame = (phase >> 1) & 7 -- 16 phases a
                                #   cycle, which DIVIDES the 64-phase loop, so
                                #   the picture stays a pure function of the
                                #   phase and the clip still closes on itself


def rot_h(rows, k):
    """Every row rotated left by k. A uniform row is unchanged by this."""
    return [r[k % 8:] + r[:k % 8] for r in rows]


def rot_v(rows, k):
    """The tile's rows cycled, so its content drifts UPWARD by k."""
    return [rows[(y + k) % 8] for y in range(8)]


# TICK: ok -- a colour-rotation STEP count the already-scaled phase indexes,
#   never a hardware frame. `smt_nmi_row` computes (phase >> SHIFT) & 7 and
#   counts nothing.
WALL_PAL_FRAMES = WALL_SHADES   # a full rotation, so step 8 IS step 0
WALL_PAL_SHIFT = 1             # frame = (phase >> 1) & 7 -- 16 phases for the
                               #   band to travel one tile, which DIVIDES the
                               #   64-phase loop and keeps the clip's seam shut


def _far(a, b):
    """RGB distance between two BGR555 words, in 5-bit units."""
    return sum((((a >> s) & 31) - ((b >> s) & 31)) ** 2 for s in (0, 5, 10))


def wall_pal():
    """-> the cycle's blob: WALL_PAL_FRAMES x WALL_SHADES BGR555 words.

    Step 0 is what `PAL_MELT` already holds, so the enter upload and the cycle
    are the same colours rather than two that happen to agree — the same rule
    the CHR animation's frame 0 follows.

    AND NO SHADE MAY IMPERSONATE A MEASURED EDGE, at any step. The test module
    finds the crust and the plate by NEAREST CGRAM COLOUR against a palette it
    read ONCE, so while the cycle runs a wall pixel's colour may not be in that
    snapshot at all — it is matched to whatever is closest. The requirement is
    therefore not "far from everything" but the sharp version: every wall shade
    must be closer to some OTHER WALL SHADE than to either measured edge. The
    ramp's own span bounds the first, so comparing that span to the distance to
    each edge settles it for every snapshot at once.

    Without this a wall shade could drift into nearest-match range of the
    crust's white-hot line and `crust_y` would report an edge a hundred rows
    above the metal — a failure that would read as the offset table being
    wrong.
    """
    ramps = [wall_ramp(k) for k in range(WALL_PAL_FRAMES)]
    assert ramps[0] == PAL_MELT[WALL_IX0:WALL_IX0 + WALL_SHADES], \
        "step 0 is not the palette the enter upload writes"
    shades = {w for r in ramps for w in r}
    span = max(_far(a, b) for a in shades for b in shades)
    for name, edge in (("the crust's white-hot line", PAL_MELT[3]),
                       ("the plate's top edge", PAL_PLATE[4])):
        worst = min(_far(w, edge) for w in shades)
        assert worst > span, (
            f"a wall shade is within {worst} of {name} while the ramp's own "
            f"span is {span} — a stale palette snapshot could nearest-match a "
            f"wall pixel to that edge and the column scans would find the wall")
    blob = bytearray()
    for r in ramps:
        for w in r:
            blob += bytes((w & 0xFF, w >> 8))
    return bytes(blob)


def melt_anim():
    """-> (blob, [tile names]) — MELT_ANIM_FRAMES x 4 tiles of 4bpp CHR.

    Frame 0 is byte-identical to the four tiles in the static CHR blob, so the
    boot upload and the animation agree and the title's restore is a real
    restore rather than a fifth picture.
    """
    # TAKEN FROM `MELT_TILES` RATHER THAN REBUILT FROM THE SAME SEEDS, so
    # "frame 0 is the static tile" is true by construction. Re-calling
    # `crust_tile(0)` here would be a second copy of the seeds, and a seed
    # changed in one place and not the other gives a rail whose lava snaps on
    # the first frame of every cycle.
    # The crust rotates; the body is REBUILT at each step, because bubbles are
    # not a rotation of anything. Both close at MELT_ANIM_FRAMES: a rotation by
    # 8 of an 8-tall tile is the identity, and every bubble's age and rise are
    # taken modulo 8.
    base = [(MELT_TILES[WALL_TILES + 0], lambda r, k: rot_h(r, k)),
            (MELT_TILES[WALL_TILES + 1], lambda r, k: rot_h(r, k)),
            (MELT_TILES[WALL_TILES + 2], lambda _r, k: melt_tile(0, k)),
            (MELT_TILES[WALL_TILES + 3], lambda _r, k: melt_tile(5, k))]
    assert [n for (n, _), _ in base] == ["crust_a", "crust_b",
                                         "melt_a", "melt_b"], MELT_TILES
    blob = bytearray()
    for k in range(MELT_ANIM_FRAMES):
        for (name, rows), rot in base:
            f = rot(rows, k)
            if k == 0:
                assert f == rows, (
                    f"{name} frame 0 is not the tile the boot upload writes — "
                    f"the static CHR and the animation would disagree on the "
                    f"first frame of every cycle")
            if name.startswith("crust"):
                assert f[0] == rows[0] == [3] * 8, (
                    f"{name} frame {k}: the crust's top row is not the "
                    f"unbroken bright line every per-column measurement reads")
            else:
                assert all(3 not in r for r in f), (
                    f"{name} frame {k}: a body pixel is the CRUST's index, "
                    f"which would give `crust_y` a second edge to find")
            blob += encode_4bpp(f, f"{name}@{k}")
    return bytes(blob), [n for (n, _), _ in base]


T_CLEAR, T_TOP_L, T_TOP_M, T_TOP_R, T_UND_L, T_UND_M, T_UND_R = range(7)
# BG2's tiles sit after BG1's in one shared CHR claim, so their ids are offset.
MELT_BASE_TILE = len(PLATE_TILES)
T_WALL = tuple(MELT_BASE_TILE + k for k in range(WALL_TILES))
T_CRUST_A, T_CRUST_B, T_MELT_A, T_MELT_B = \
    (MELT_BASE_TILE + WALL_TILES + i for i in range(4))

# The animated block starts at the crust and runs to the end of the melt: four
# CONTIGUOUS slots, which is what makes the swap one transfer rather than two.
MELT_ANIM_FIRST = MELT_BASE_TILE + WALL_TILES   # ...past the wall run
MELT_ANIM_TILES = 4
# A POWER OF TWO, because the ASM turns the frame index into a blob offset with
# a shift — ca65 has no multiply available in a `.repeat` count. Asserted here
# so a fifth animated tile stops the GENERATOR rather than silently emitting a
# stride the walker cannot express.
assert (WALL_SHADES * 2) & (WALL_SHADES * 2 - 1) == 0, \
    "the wall cycle's per-step stride must be a power of two — a shift scales it"
assert WALL_PAL_FRAMES & (WALL_PAL_FRAMES - 1) == 0, \
    "the wall cycle's step count must be a power of two — the index is a mask"
assert PHASES % (WALL_PAL_FRAMES << WALL_PAL_SHIFT) == 0, \
    ("the wall cycle must DIVIDE the phase loop, or the picture stops being a "
     "pure function of the phase and the gallery clip's seam opens")
assert (MELT_ANIM_TILES * 32) & (MELT_ANIM_TILES * 32 - 1) == 0, \
    "the animation's per-frame stride must be a power of two"
assert MELT_ANIM_FRAMES & (MELT_ANIM_FRAMES - 1) == 0, \
    "the frame count must be a power of two — the index is a mask"
assert (MELT_ANIM_FRAMES << MELT_ANIM_SHIFT) <= PHASES and \
    PHASES % (MELT_ANIM_FRAMES << MELT_ANIM_SHIFT) == 0, \
    ("the animation's cycle must DIVIDE the phase loop, or the picture stops "
     "being a pure function of the phase and the gallery clip's seam opens")

ATTR_G0 = 0 << 10            # palette group 0 — the plates
ATTR_G1 = 2 << 10            # palette group 2 — the cavern and the melt. Not
                             # group 1: bg_text pins CGRAM words 28..31 for
                             # its 2bpp palette 7, which lands inside group
                             # 1, and the title scene composes both.


# --------------------------------------------------------------------------
# tilemaps — 32 x 64 words each (a 512 px tall map, so no scroll in range
# wraps and every screen row is the row this file drew)
# --------------------------------------------------------------------------
MAP_ROWS = 64


def plate_map():
    m = [[T_CLEAR | ATTR_G0] * COLS for _ in range(MAP_ROWS)]
    for first, width in PLATES:
        for i in range(width):
            c = first + i
            kind = 0 if i == 0 else (2 if i == width - 1 else 1)
            m[PLAT_MAP_ROW][c] = (T_TOP_L + kind) | ATTR_G0
            m[PLAT_MAP_ROW + 1][c] = (T_UND_L + kind) | ATTR_G0
    return [w for row in m for w in row]


def melt_map():
    m = []
    for r in range(MAP_ROWS):
        if r < CRUST_MAP_ROW:
            # ONE TILE EVERYWHERE, WHICH IS THE STRONGEST FORM OF THE
            # PROPERTY. `wall_tile` makes all eight of its rows identical so
            # that displacing a column of wall is invisible — and this map
            # once alternated two streak phases on `(c + r) % 2`, which threw
            # that away: swapping the tile every 8 map rows IS a horizontal
            # seam every 8 pixels, and a displaced column slid it past the
            # screen. A human caught it in the gallery clip. Alternating on
            # `c` fixed it; moving the wall's pattern into the PALETTE removed
            # the alternation altogether, so there is no longer a second tile
            # to get wrong. Measured either way: tests/test_smelter.py
            # ::test_the_wall_does_not_move_when_its_column_does.
            # ALTERNATING ON THE COLUMN, which is the safe axis — and the
            # map's width is a multiple of WALL_TILES, so the run lines up
            # with itself across the wrap and across the whole world.
            row = [T_WALL[c % WALL_TILES] | ATTR_G1 for c in range(COLS)]
        elif r == CRUST_MAP_ROW:
            row = [(T_CRUST_A if c % 2 == 0 else T_CRUST_B) | ATTR_G1
                   for c in range(COLS)]
        else:
            row = [(T_MELT_A if (c + r) % 3 else T_MELT_B) | ATTR_G1
                   for c in range(COLS)]
        m.append(row)
    return [w for row in m for w in row]


# --------------------------------------------------------------------------
# the offset table — the rail's subject
# --------------------------------------------------------------------------
def plate_of(wcol):
    """Which of the world's sixteen plate SLOTS owns this world column, or None.

    BG1's map is 32 columns wide and repeats every 256 px, so the four groups
    in `PLATES` are plate art in every screen; the slot index is which screen
    plus which group. A column belongs to at most one, which is what makes "a
    plate's columns share one value" a fact about the table rather than an
    accident of how it was built.
    """
    local, screen = wcol % COLS, wcol // COLS
    for i, (first, width) in enumerate(PLATES):
        if first <= local < first + width:
            return screen * len(PLATES) + i
    return None


def gaps():
    """The runs of world columns that belong to no plate, left to right. These
    are the melt's — one jet each, and the runs at a screen boundary MERGE,
    which is what keeps a jet from having a seam in it where two screens meet."""
    out, run = [], []
    for c in range(WORLD_COLS):
        if plate_of(c) is None:
            run.append(c)
        elif run:
            out.append(run)
            run = []
    if run:
        out.append(run)
    return out


GAPS = gaps()


def plate_word(slot, phase):
    f, off, amp = SLOT_FREQ[slot], SLOT_OFF[slot], SLOT_AMP[slot]
    v = PLAT_BASE + amp * math.sin(2 * math.pi * (f * phase / PHASES + off))
    return BIT_BG1 | (int(round(v)) & 0x3FF)


def melt_word(col, phase):
    # Which jet this column sits in, and where across it: 0 at the edges, 1 in
    # the middle. A jet is an ARCH rather than a step, so the crust leaves the
    # plates' level smoothly and the eye reads a column of melt rising rather
    # than a rectangle appearing.
    g = next(i for i, run in enumerate(GAPS) if col in run)
    run = GAPS[g]
    if len(run) == 1:
        shape = 1.0
    else:
        t = (col - run[0]) / (len(run) - 1)
        shape = math.sin(math.pi * t)
    # THE JET TABLES ARE INDEXED MODULO THEIR OWN LENGTH, so a world four
    # screens wide needs no more of them than one screen did — and because the
    # gap runs are not all the same width, the same five parameters land on
    # different arches each time and no two screens of melt look alike.
    drive = math.sin(2 * math.pi * (JET_FREQ[g % len(JET_FREQ)] * phase / PHASES
                                    + JET_OFF[g % len(JET_OFF)]))
    jet = MELT_AMP * shape * max(0.0, drive)
    # ...and a small travelling ripple under all of it, so no column is ever
    # exactly still. A clip that holds a frozen frame reads as the effect
    # breaking, which is the seam lesson the last two rails paid for.
    ripple = MELT_RIPPLE * math.sin(2 * math.pi * (phase / PHASES + col / 11.0))
    return BIT_BG2 | (int(round(MELT_BASE + jet + ripple)) & 0x3FF)


def column_word(col, phase):
    p = plate_of(col)
    return plate_word(p, phase) if p is not None else melt_word(col, phase)


def flat_word(col):
    """The control. THE ENABLE BIT STAYS SET and only the VALUE goes to its
    base, so exactly one variable moves between "running" and "flat" — the
    heathaze rule: a control that also disarms the mechanism cannot tell a
    broken table from a broken transfer."""
    p = plate_of(col)
    return (BIT_BG1 | PLAT_BASE) if p is not None else (BIT_BG2 | MELT_BASE)


# THE ONE-COLUMN LEAD, and it is MEASURED, not assumed.
#
# The PPU fetches a column's tilemap data BEFORE it fetches that column's
# offset words: in mode 2 the eight-cycle group for column g runs
# GetTilemapData for BG2 and BG1 (cases 0 and 1) and only THEN
# GetHorizontalOffsetByte / GetVerticalOffsetByte (cases 2 and 3), so the
# words fetched with column index g are latched in time for column g + 1
# (Mesen2 Core/SNES/SnesPpu.cpp FetchTileData, :316-330). The latches are also
# cleared at the start of each scanline's fetch (:284-287), so SCREEN COLUMN 0
# CANNOT BE DISPLACED AT ALL — it always shows its layer's own BGnVOFS.
#
# Confirmed on the shipped binary before this shift existed: the plate whose
# words sat in table columns 3..6 rendered at screen columns 4..6 with column
# 3 at the fallback — three columns wide instead of four, with an invisible
# ghost beside it. tests/test_smelter.py asserts both halves of the rule
# against the rendered picture.
#
# So the ROW IS WRITTEN ONE COLUMN TO THE LEFT of the columns it displaces.
# Everything above this line is expressed in SCREEN columns, which is the only
# frame of reference the art, the collision and the tests share; the shift
# lives here, once, at the boundary where a screen column becomes a table
# index.
def col_table():
    """The world's rows. Index k of a row is WORLD COLUMN k, with no shift
    baked in — the one-column lead is applied by the DMA, which reads from
    `cam + 1` (smt_opt.asm). That is a CHANGE from the screen-space table,
    where the shift was baked here, and it is what makes the row usable for two
    things at once: the 32 words the transfer moves, and the ONE word the
    fallback registers need for the column the hardware cannot displace.
    """
    out = bytearray()
    for phase in range(PHASES):
        for col in range(WORLD_COLS):
            w = column_word(col, phase)
            out += bytes((w & 0xFF, w >> 8))
    for col in range(WORLD_COLS):
        w = flat_word(col)
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


def h_row():
    """The H row — row 0 of BG3's map, which the PPU reads as the HORIZONTAL
    offset word for every column. All zero: with neither enable bit set no
    horizontal displacement is applied, which is how a V-only table is
    expressed. It is uploaded ONCE, at scene enter; only the V row is rewritten
    per frame."""
    return bytes(COLS * 2)




# ===========================================================================
# THE KNIGHT — traced from the vendored camelot pack's own PNG
# ===========================================================================
# `vendor/art/camelot/arthurPendragon_.png`, CC0 (analogStudios_ / Kevin's
# Mom's House, the `legends_` series). The PNG is the pack's ORIGINAL file,
# sha256-matched against its zip member in docs/92 §5.1, and reading it
# directly rather than a converted blob is what the asset-import rule asks
# for: a converter validated against your own re-rendering of your own output
# is a tautology, and the PNG is independent of everything this repo emits.
#
# WHY A KNIGHT ON A FOUNDRY FLOOR, AND WHY THIS ONE. The rail needed a sprite
# whose FEET ARE A SHARP HORIZONTAL EDGE, because the whole claim it makes is
# that the collision reads the same word the picture is drawn from: the knight
# stands on a plate whose height is a table entry, and rides it. The pack
# frames every 32x32 cell with FOUR TRANSPARENT ROWS UNDER THE FEET, so the
# drawn content ends at row 28 of 32 — a number this rail depends on and the
# pack's README already measured, which is exactly the kind of thing you want
# to inherit rather than re-derive.
#
# RIGHT-FACING ONLY (columns 0-3). The pack draws both directions by hand,
# and walking left here is an OAM H-flip — half the CHR, and the same idiom
# `split_v_obj` uses.
#
# THE HELPERS BELOW ARE COPIED, NOT IMPORTED, and this is the fourth copy of
# `encode_tile_4bpp` in tools/. Not promoted, deliberately: the other three
# have three DIFFERENT signatures (`gen_brawler_assets` takes a label,
# `gen_m7_dungeon_assets` takes a grid and an origin), so a shared module
# would be a signature negotiation across three byte-pinned rails rather than
# a move. Two committed oracles would prove such a move pure —
# `vendor/art/camelot/ref_arthur.inc` and `vendor/art/split_v/sv_knight_chr.bin`
# — which is what makes it a good follow-up and a bad thing to do inside a
# sprint about offset-per-tile. Filed in docs/dx_paper_cuts.md.
CAMELOT = pathlib.Path(__file__).resolve().parent.parent / "vendor" / "art" / "camelot"
ARTHUR_PNG = CAMELOT / "arthurPendragon_.png"

# TICK: ok -- these index the ART, not the clock. A `frame` here is one of
#   the pack's 32x32 animation cells, and NOTHING ON THIS RAIL COUNTS
#   HARDWARE FRAMES to choose between them: the walk is indexed by the
#   knight's own screen X and the idle by the rail's phase, both of which
#   TS_STEP has already scaled. There is no table here indexed by a frame
#   number, so a change of tick rate leaves every one of these correct.
FRAME_BOX = 32              # the pack's cell, in PIXELS
FRAMES_PER_GROUP = 4        # four 32x32 cells fill one 64-tile grid group
                            # TICK: ok -- a VRAM packing ratio, as above.

# (row, col) on the 8x8 grid of 32x32 cells. The pack's own READ ME maps
# arthurPendragon_'s rows: idle [0], run [1,2], jump-idle [3], jump-run [4],
# turn [5], hit [6], death [7]. ONE SLOT PER LINE, and the slot index IS the
# position in this list — it is what the anim tables index and what the ASM's
# SMT_F_* names mirror.
KNIGHT_CELLS = [
    (0, 0), (0, 1), (0, 2), (0, 3),          # 0-3   idle
    (1, 0), (1, 1), (1, 2), (1, 3),          # 4-7   run, first half
    (2, 0), (2, 1), (2, 2), (2, 3),          # 8-11  run, second half
    (3, 1),                                  # 12    jump-idle, legs tucked
]
KNIGHT_SLOTS = 16           # 13 cells, padded to four whole grid groups
                            # TICK: ok -- a VRAM slot count, as above.

# The anim tables, by state. The tuple order IS the state index the ASM
# stores, and the second number is a SHIFT rather than a frame count —
# because NOTHING ON THIS RAIL COUNTS FRAMES.
#
# The walk is indexed by the knight's own screen X, one step every 8 px, so the
# legs move with the ground and the cadence is region-correct for free: X is
# advanced by TS_STEP's output, so the animation inherits the scaler with no
# clock of its own. The idle is indexed by the rail's phase, one step every 16
# of them, which is the same argument on the quantity that already carries it.
# Neither needs an accumulator, a countdown or a `TICK: ok` stamp, because
# neither is a frame count.
#
# EVERY LENGTH IS A POWER OF TWO, asserted below: the index is a shift and a
# MASK, so a length that was not would need a compare-and-wrap in the draw.
KNIGHT_ANIM = [
    ("idle", [0, 1, 2, 3], 4),               # phase >> 4, & 3
    ("walk", [4, 5, 6, 7, 8, 9, 10, 11], 3),  # x >> 3, & 7
    ("jump", [12], 0),                        # one pose; the shift is inert
]
ANIM_STRIDE = 8             # frame slots per state in smt_anim.bin
META_STRIDE = 2             # (index mask, shift) per state


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
    assert len(pal) <= 16, f"{len(pal)} colours will not fit a 4bpp palette"
    return [rgb_to_bgr15(c) for c in pal] + [0] * (16 - len(pal)), c2i


def index_frame(img, c2i):
    w, h = img.size
    data = rgba_pixels(img)
    return [[c2i[data[y * w + x][:3]] if data[y * w + x][3] >= 128 else 0
             for x in range(w)] for y in range(h)]


def slot_base_tile(slot):
    """Frame slot -> its top-left tile on the 16-wide OBJ name table.

    A 32x32 sprite reads {N..N+3, N+16..N+19, N+32..N+35, N+48..N+51} — the
    row stride of 16 is hardware-fixed — so four frames fill one group of four
    grid rows and frame N starts at (N//4)*64 + (N%4)*4.
    """
    return (slot // FRAMES_PER_GROUP) * 64 + (slot % FRAMES_PER_GROUP) * 4


def content_bottom(rows):
    """The last row of a frame with any opaque pixel in it.

    MEASURED per build rather than taken from the pack's README, because it is
    the number the collision is expressed through: the knight's feet must land
    ON the plate's top edge, and a frame whose content ended somewhere else
    would put them in the air or in the metal. The README says 28 of 32; this
    asserts it against the pixels.
    """
    for y in range(len(rows) - 1, -1, -1):
        if any(rows[y]):
            return y + 1
    raise AssertionError("an entirely transparent knight frame")


def content_top(rows):
    """The FIRST row of a frame with any opaque pixel in it.

    The sibling of `content_bottom`, and measured for the same reason: the
    melt now hides him when he is FULLY SUBMERGED, which is a statement about
    his highest drawn pixel and not about the top of his 32 px cell. Arthur's
    frames carry transparent rows above the helmet, so taking the cell's edge
    would despawn him several rows late — visibly late, because the frame he
    is still drawn in is the one under the lava.
    """
    for y in range(len(rows)):
        if any(rows[y]):
            return y
    raise AssertionError("an entirely transparent knight frame")


def knight_sheet():
    """The knight's frames -> (CHR blob, 16 palette words, content top/bottom).

    ONE PALETTE OVER THE WHOLE SET, built from the union of every chosen
    cell's opaque colours — the pack's README measures Arthur at 8, so this is
    a lossless conversion and not a quantisation.
    """
    sheet = Image.open(ARTHUR_PNG).convert("RGBA")
    cells = []
    for row, col in KNIGHT_CELLS:
        # The pack's cell IS the OBJ box, so there is no crop and no
        # re-centring here — `png2snes.py`'s `recenter` is skipped for a frame
        # that already measures exactly the box ("already exact; keep author's
        # framing"), and re-centring anyway would push the art 4 px down and
        # move the feet off the number the collision is written against.
        cells.append(sheet.crop((col * FRAME_BOX, row * FRAME_BOX,
                                 (col + 1) * FRAME_BOX, (row + 1) * FRAME_BOX)))
        assert cells[-1].size == (FRAME_BOX, FRAME_BOX)

    allc = set()
    for c in cells:
        allc |= opaque_colors(c)
    words, c2i = build_palette(allc)

    groups = (KNIGHT_SLOTS + FRAMES_PER_GROUP - 1) // FRAMES_PER_GROUP
    blob = bytearray(groups * 64 * 32)
    bottom, top = 0, FRAME_BOX
    for slot, cell in enumerate(cells):
        rows = index_frame(cell, c2i)
        bottom = max(bottom, content_bottom(rows))
        # the SMALLEST top over the set, for the same reason bottom is the
        # largest: whichever frame is on screen, no drawn pixel is outside
        # [top, bottom)
        top = min(top, content_top(rows))
        base = slot_base_tile(slot)
        for ty in range(FRAME_BOX // 8):
            for tx in range(FRAME_BOX // 8):
                tile = [r[tx * 8:(tx + 1) * 8]
                        for r in rows[ty * 8:(ty + 1) * 8]]
                ti = base + ty * 16 + tx
                blob[ti * 32:(ti + 1) * 32] = encode_4bpp(tile, f"knight{slot}")
    return bytes(blob), words, top, bottom, len(allc)


def anim_tables():
    """(frames, meta) — the anim tables as one flat pair of blobs.

    `frames` is ANIM_STRIDE TILE NUMBERS per state (the slot's base tile, not
    its slot index: the draw writes an OAM tile field and should not have to
    know the grid arithmetic), `meta` is (index mask, shift) per state.
    Emitted rather than written into the ASM for the reason every table in
    this rail is: the walker and the table cannot disagree about a number
    neither of them holds twice.
    """
    frames = bytearray(len(KNIGHT_ANIM) * ANIM_STRIDE)
    meta = bytearray(len(KNIGHT_ANIM) * META_STRIDE)
    for i, (name, slots, shift) in enumerate(KNIGHT_ANIM):
        assert len(slots) <= ANIM_STRIDE, f"{name}: {len(slots)} > stride"
        assert len(slots) & (len(slots) - 1) == 0, (
            f"{name}: {len(slots)} frames is not a power of two, and the draw "
            f"indexes with a mask")
        for j, s in enumerate(slots):
            frames[i * ANIM_STRIDE + j] = slot_base_tile(s)
        meta[i * META_STRIDE + 0] = len(slots) - 1      # the index mask
        meta[i * META_STRIDE + 1] = shift
    return bytes(frames), bytes(meta)


# --------------------------------------------------------------------------
def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3)."""
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    for y, row in enumerate(rows):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} px"
        for x, v in enumerate(row):
            assert 0 <= v <= 15, (
                f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
    out = bytearray()
    for pair in (0, 2):
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
        assert 0 <= w <= 0xFFFF, f"{label}: entry {i} {w:#06x} is not 16-bit"
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


ART_INC = """; smt_art.inc — GENERATED by tools/gen_smelter_assets.py. Do not edit.
;
; The SHAPE of the offset table and the geometry the plates and the melt were
; drawn at. Emitted rather than restated so the table, the walker that uploads
; it, the collision that reads it and the tests that assert on it cannot
; disagree about a single number.
SMT_COLS          = {cols}     ; offset words the TRANSFER moves (256 px / 8)

; --- the world -------------------------------------------------------------
; The table is WORLD-space: a row is one word per world column, and the camera
; moves the DMA's read head rather than anything being rebuilt. So scrolling
; costs the same 64 B and the same one transfer a static screen did.
SMT_SCREENS       = {screens}      ; ...of 256 px
SMT_WORLD_COLS    = {wcols}    ; words in a row
SMT_WORLD_W       = {worldw}   ; the reachable world, in pixels
SMT_CAM_COL_MAX   = {cammax}     ; the rightmost camera column: the DMA reads
                             ;   cam+1 .. cam+32 (the one-column lead), so the
                             ;   world's last column is never displaced and the
                             ;   camera stops one short of it
SMT_PHASES        = {phases}     ; the loop closes here
SMT_FLAT_INDEX    = {flat}     ; the control row: same shape, base values
SMT_ROW_COUNT     = {rows}     ; phases + the control
SMT_PHASE_SHIFT   = {shift}      ; stride {stride} B -> a row is (index << {shift})
SMT_ROW_BYTES     = {stride}
SMT_TILE_COUNT    = {tiles}
SMT_PAL_MELT_OFF  = 32     ; the melt group's byte offset in smt_pal.bin

; --- the knight (vendor/art/camelot, CC0) ----------------------------------
SMT_KN_BOX        = {kbox}     ; the pack's cell AND the OBJ box: no crop, no
                             ;   re-centre -- see the generator
SMT_KN_TOP        = {ktop}      ; MEASURED: the FIRST row of any frame with an
                             ;   opaque pixel. What "fully submerged" means:
                             ;   the melt hides him when THIS row is under the
                             ;   crust line, not when his cell's edge is
SMT_KN_BOTTOM     = {kbot}     ; MEASURED: the last row of a frame with any
                             ;   opaque pixel in it. The pack frames every cell
                             ;   with four transparent rows under the feet, and
                             ;   this is the number the collision is written
                             ;   against
SMT_KN_SLOTS      = {kslots}     ; frames, padded to whole 64-tile grid groups
SMT_KN_STATES     = {kstates}      ; idle, walk, jump -- the state index the ASM
                             ;   stores IS the row of the anim table
SMT_KN_ST_IDLE    = 0
SMT_KN_ST_WALK    = 1
SMT_KN_ST_JUMP    = 2
SMT_KN_ANIM_STRIDE = {kstride}     ; frame slots per state in smt_anim.bin
SMT_ANIM_META_OFF = {kmetaoff}     ; ...and where the (index mask, shift) pairs start

; --- BG1: the plates -------------------------------------------------------
SMT_PLAT_MAP_ROW  = {prow}     ; the plate band's first tilemap row
SMT_PLAT_TOP_PX   = {ptop}    ; ...in map pixels: the edge measurements use
SMT_PLAT_BASE     = {pbase}    ; the flat control's value for a plate column
SMT_PLAT_AMP      = {pamp}
SMT_PLAT_COUNT    = {pcount}
SMT_PLAT_WIDTH    = {pwidth}      ; columns, and every plate is the same: a
                             ;   32 px slab, which is also the knight's box
SMT_VOFS_BG1      = {vbg1}      ; the fallback for a column with bit 13 clear
{platcols}

; --- BG2: the melt ---------------------------------------------------------
SMT_CRUST_MAP_ROW = {crow}     ; the crust line's tilemap row
SMT_CRUST_TOP_PX  = {ctop}    ; ...in map pixels
SMT_MELT_BASE     = {mbase}    ; the flat control's value for a gap column
SMT_MELT_AMP      = {mamp}
SMT_VOFS_BG2      = {vbg2}    ; the fallback for a column with bit 14 clear —
                             ;   the plates' columns, where the melt is calm

; --- BG2's CHR animation: the same map, different pixels -------------------
; The classic BG swap. {manimf} frames of {manimt} CONTIGUOUS tiles, moved into
; the same CHR slots every VBlank, so the lava churns for no tilemap traffic
; and no second layer. The frame is a function of the PHASE — nothing here
; counts hardware frames — and {manimf} frames every {manimshift} phase(s) is a
; cycle that DIVIDES the {phases}-phase loop, so the picture stays a pure
; function of one number and the gallery clip still closes on itself.
; TICK: ok -- an ANIMATION frame count the PHASE indexes, not a frame counter.
SMT_MELT_ANIM_FRAMES = {manimf}
SMT_MELT_ANIM_TILES  = {manimt}
SMT_MELT_ANIM_FIRST  = {manimfirst}     ; the first animated CHR slot
SMT_MELT_ANIM_SHIFT  = {manimshift}     ; frame = (phase >> SHIFT) & (FRAMES-1)
SMT_MELT_ANIM_BYTES  = {manimbytes}   ; one frame, and one transfer
SMT_MELT_ANIM_LOG2_BYTES = {manimlog2}  ; ...as a shift, because the frame
                             ;   index is scaled to a blob offset with `asl`
                             ;   and ca65 has no multiply in a .repeat count

; --- BG2's WALL: a colour rotation, and the pattern that flows on it -------
; The wall carries no pattern in its pixels — one tile, every row identical,
; and EVERY COLUMN ITS OWN PALETTE INDEX. The pattern is the eight colours
; those indices hold, and rotating them walks a band of lightness across the
; screen for {wpalbytes} bytes of CGRAM a frame.
;
; IT IS A PALETTE CYCLE AND NOT A CHR SWAP FOR A REASON. The wall is the one
; surface that must be invariant under vertical displacement, so every frame of
; a CHR animation would have to be vertically uniform — and the case that
; checks the invariance could no longer tell "the wall moved" from "the wall
; animated". A colour rotation does not touch a pixel, so the invariance holds
; by construction, and the test tells the two apart by comparing frames one
; whole cycle apart.
;
SMT_WALL_IX0        = {wix0}      ; the wall's first palette index
SMT_WALL_SHADES     = {wshades}      ; ...this many of them, spread over
SMT_WALL_PX_PER_SHADE = {wpxper}      ; ...this many pixels each, so the
SMT_WALL_PERIOD     = {wperiod}     ; travelling band's period is this wide
SMT_WALL_TILES      = {wtiles}      ; ...and the run is this many tiles long
; TICK: ok -- a colour-rotation STEP the phase indexes, not a frame counter.
SMT_WALL_PAL_FRAMES = {wpalf}      ; a full rotation: step 8 IS step 0
SMT_WALL_PAL_SHIFT  = {wpalshift}      ; frame = (phase >> SHIFT) & (FRAMES-1)
SMT_WALL_PAL_BYTES  = {wpalbytes}     ; one step, written straight to CGDATA
SMT_WALL_PAL_LOG2_BYTES = {wpallog2}  ; ...as a shift, for the same reason
                             ;   SMT_MELT_ANIM_LOG2_BYTES is one
"""


assert len({p[1] for p in PLATES}) == 1, (
    "the plates are not all the same width, and SMT_PLAT_WIDTH is emitted as "
    "one number the collision indexes every plate with")


def main(argv):
    out = pathlib.Path(argv[1] if len(argv) > 1 else "build/assets")
    out.mkdir(parents=True, exist_ok=True)

    tiles = PLATE_TILES + MELT_TILES
    chr_blob = b"".join(encode_4bpp(rows, name) for name, rows in tiles)
    (out / "smt_chr.bin").write_bytes(chr_blob)
    (out / "smt_pmap.bin").write_bytes(
        encode_words(plate_map(), "smt_pmap", COLS * MAP_ROWS))
    (out / "smt_mmap.bin").write_bytes(
        encode_words(melt_map(), "smt_mmap", COLS * MAP_ROWS))
    # ONE PALETTE BLOB, TWO CGRAM GROUPS. The two 16-word halves go to CGRAM
    # 0 and 32, which are not contiguous — but the BLOB is, and that is what
    # the uploader needs: a single base symbol plus a small positive byte
    # offset. Two separate blobs would leave the loader adding the difference
    # between two linker-placed symbols, and the allocator is free to order
    # them either way (it put the melt's first), so that difference can be
    # NEGATIVE and absolute-long indexed addressing would carry it into the
    # wrong bank.
    (out / "smt_pal.bin").write_bytes(
        encode_words(PAL_PLATE + PAL_MELT, "smt_pal", 32))
    (out / "smt_hrow.bin").write_bytes(h_row())

    kchr, kpal, ktop, kbottom, kcolours = knight_sheet()
    (out / "smt_obj.bin").write_bytes(kchr)
    (out / "smt_obj_pal.bin").write_bytes(
        encode_words(kpal, "smt_obj_pal", 16))
    kframes, kmeta = anim_tables()
    (out / "smt_anim.bin").write_bytes(kframes + kmeta)

    manim, mnames = melt_anim()
    (out / "smt_melt_anim.bin").write_bytes(manim)
    wpal = wall_pal()
    (out / "smt_wall_pal.bin").write_bytes(wpal)

    col = col_table()
    assert len(col) == (PHASES + 1) * STRIDE, len(col)
    (out / "smt_col.bin").write_bytes(col)

    (out / "smt_art.inc").write_text(ART_INC.format(
        cols=COLS, phases=PHASES, flat=PHASES, rows=PHASES + 1,
        screens=SCREENS, wcols=WORLD_COLS, worldw=WORLD_W, cammax=CAM_COL_MAX,
        shift=PHASE_SHIFT, stride=STRIDE, tiles=len(tiles),
        prow=PLAT_MAP_ROW, ptop=PLAT_TOP_PX, pbase=PLAT_BASE, pamp=PLAT_AMP,
        pcount=len(SLOT_FREQ), pwidth=PLATES[0][1], vbg1=0,
        platcols="\n".join(
            f"SMT_PLAT_{i}_COL     = {(i // len(PLATES)) * COLS + PLATES[i % len(PLATES)][0]}"
            f"{' ' * max(1, 5 - len(str((i // len(PLATES)) * COLS + PLATES[i % len(PLATES)][0])))}"
            f"; slot {i}: screen {i // len(PLATES)}, group {i % len(PLATES)}"
            for i in range(len(SLOT_FREQ))),
        crow=CRUST_MAP_ROW, ctop=CRUST_TOP_PX, mbase=MELT_BASE, mamp=MELT_AMP,
        vbg2=MELT_BASE,
        kbox=FRAME_BOX, ktop=ktop, kbot=kbottom, kslots=KNIGHT_SLOTS,
        kstates=len(KNIGHT_ANIM), kstride=ANIM_STRIDE,
        kmetaoff=len(kframes),
        manimf=MELT_ANIM_FRAMES, manimt=MELT_ANIM_TILES,
        wpxper=WALL_PX_PER_SHADE, wperiod=WALL_PERIOD, wtiles=WALL_TILES,
        manimfirst=MELT_ANIM_FIRST, manimshift=MELT_ANIM_SHIFT,
        manimbytes=MELT_ANIM_TILES * 32,
        manimlog2=(MELT_ANIM_TILES * 32).bit_length() - 1,
        wix0=WALL_IX0, wshades=WALL_SHADES, wpalf=WALL_PAL_FRAMES,
        wpalshift=WALL_PAL_SHIFT, wpalbytes=WALL_SHADES * 2,
        wpallog2=(WALL_SHADES * 2).bit_length() - 1))

    print(f"smt_chr.bin  {len(chr_blob):6d} B  ({len(tiles)} tiles)")
    print(f"smt_pmap.bin   4096 B  (32x64 words, {len(PLATES)} plates)")
    print(f"smt_mmap.bin   4096 B  (32x64 words, crust at map row "
          f"{CRUST_MAP_ROW})")
    print(f"smt_pal.bin      64 B  (two 16-word groups: 0 and 2)")
    print(f"smt_hrow.bin  {COLS * 2:6d} B  (the H row: all zero, V-only table)")
    print(f"smt_col.bin  {len(col):6d} B  ({PHASES} phases + 1 flat control "
          f"x {STRIDE} B; {len(GAPS)} jets, {len(PLATES)} plates)")
    print(f"smt_obj.bin  {len(kchr):6d} B  ({len(KNIGHT_CELLS)} knight frames "
          f"in {KNIGHT_SLOTS} slots, {kcolours} opaque colours, content "
          f"bottom {kbottom}/{FRAME_BOX})")
    print(f"smt_wall_pal.bin  {len(wpal):5d} B  ({WALL_PAL_FRAMES} steps x "
          f"{WALL_SHADES} words — the wall's colours, rotated)")
    print(f"smt_melt_anim.bin {len(manim):5d} B  ({MELT_ANIM_FRAMES} frames x "
          f"{len(mnames)} tiles: {', '.join(mnames)})")
    print(f"smt_obj_pal.bin  32 B  /  smt_anim.bin  "
          f"{len(kframes) + len(kmeta)} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
