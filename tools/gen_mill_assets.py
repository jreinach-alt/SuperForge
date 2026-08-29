#!/usr/bin/env python3
"""mill — the machine hall's art, its offset row, and the geometry both agree on.

THE RAIL'S SUBJECT IS MODE 4'S AXIS BIT. Modes 2 and 6 fetch a word for EACH
axis, so a column is displaced on both and the axis is not a choice. Mode 4
fetches ONE word and bit 15 picks — so a single 32-word row pumps one station
vertically and runs the next one's conveyor sideways, which is the one thing
mode 4 does that mode 2 cannot (docs/100 §2, §5 O7).

=============================================================================
WHAT CONSTRAINS THE ART, AND — MORE IMPORTANTLY — WHAT DOES NOT
=============================================================================
A displaced column moves WHOLE, so each axis imposes an invariance on the art
it moves:

  a VERTICALLY displaced column shows its own pixels at another row, so
      everything in it that must not appear to move has to be identical row to
      row. Here that is the piston SHAFT and nothing else.
  a HORIZONTALLY displaced column shows the NEIGHBOURING TILE, because the
      layer keeps its own fine three bits and the word's are dropped (hScroll
      = (BGnHOFS & 7) | (word & $3F8), SnesPpu.cpp:157) — so on the layer a
      belt drives, EVERY map row must hold one tile across its whole width,
      and what moves has to be a repeating texture whose phase the shift
      changes.

*** ONLY THE COLUMNS THE TABLE DRIVES OWE ANY OF THAT. ***

That is the sentence the first cut of this rail did not have, and it is why it
looked like a test pattern: it drew EVERYTHING as though it were displaced.
Per station the table drives four SHAFT columns on BG1 and three BELT columns
on BG2 — and every other column is free. The leg, the floor, the molten
channel, the machine bases and the pier are ordinary 8bpp art with a 96-colour
ramp set and no invariance to keep, and they are most of the screen.

The layering does the rest of the work. In a BELT column BG1 is not driven, so
it falls back to BG1VOFS and is STATIC: the belt frame, the deck and the lava
under it are full-detail 8bpp sitting in front of a conveyor that runs. In a
SHAFT column BG2 is not driven, so the far wall behind the machine is static
while the machine strokes.

=============================================================================
THE PALETTE IS EXTRACTED, NOT INVENTED
=============================================================================
The four ramps below are read off the swatch panel of the project owner's
concept sheet for this rail ("THE FORGE LINE", supplied 2026-08-29), sampled
through a five-row median at the centre of each swatch and reduced to BGR555.
The sheet is drawn to a SIXTEEN-COLOUR budget per ramp; mode 4 renders bg1 at
8bpp, so each ramp is stretched to two or three times that here. That is the
whole argument for the mode in one number, and it is why the ramps are anchors
rather than a finished list.

THE SOURCE IMAGE IS NOT IN THIS TREE and nothing here reads it: these are the
measured values, transcribed. What could not be taken from the sheet is the
ART — it is a continuous-tone render in a pixel-art style, 214,869 unique
colours, 0.00% of its 8x8 blocks constant, and the strip it labels
"vertically invariant" has 340 distinct rows out of 340. There is no grid in
it to slice. The tiles below are authored to its DESIGN — its object
inventory, its silhouettes and its station layout — at this hardware's budget.

=============================================================================
8BPP BUYS DEPTH, NOT SIZE
=============================================================================
A tile is 64 bytes against 4bpp's 32, so the budget that bought smelter
fifteen tiles buys about sixty here. The hall is four stations with a
36-step steel ramp and a 32-step molten one in them, not sixty distinct
things — and the depth is the point, because 4bpp cannot hold either ramp at
any tile count.
"""
import pathlib
import sys

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
OUT.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# the palette, from the concept sheet's swatch panel
# --------------------------------------------------------------------------
def rgb(r, g, b):
    return (b << 10) | (g << 5) | r


def _lum(c):
    return 2 * c[0] + 5 * c[1] + c[2]


def _anchors(swatches):
    """The sheet's ramps are FOLDED — a swatch strip runs dark-to-light and
    back, or interleaves a warm and a cold family. Sorting by luminance and
    dropping duplicates recovers the monotone ramp the strip was drawn from,
    without anyone choosing which swatch goes where."""
    out = []
    for c in sorted(swatches, key=_lum):
        if not out or _lum(c) > _lum(out[-1]):
            out.append(c)
    return out


def _stretch(anchors, n):
    """n evenly-spaced steps along the anchor ramp, linear in each channel."""
    out = []
    for k in range(n):
        t = k * (len(anchors) - 1) / (n - 1)
        i = min(int(t), len(anchors) - 2)
        f = t - i
        a, b = anchors[i], anchors[i + 1]
        out.append(tuple(round(a[j] + (b[j] - a[j]) * f) for j in range(3)))
    return out


# --- the measured swatches, BGR555 -----------------------------------------
# STEEL / METAL carries TWO families and the sheet interleaves them: a warm
# grey for worked iron and a cold blue for machined steel. Split, because the
# rail uses them for different things — warm for the static frames, cold for
# the shafts, so a viewer can tell the moving part from the frame by hue and
# not only by motion.
SW_STEEL_COLD = [(4, 5, 6), (4, 5, 7), (6, 7, 9), (9, 10, 12),
                 (11, 13, 15), (15, 17, 20), (19, 21, 24), (23, 26, 28)]
SW_STEEL_WARM = [(6, 6, 7), (8, 7, 7), (9, 8, 8), (10, 10, 9),
                 (12, 11, 11), (17, 16, 15)]
SW_BRASS = [(2, 1, 0), (5, 2, 0), (7, 4, 1), (8, 4, 1), (9, 5, 2), (11, 6, 2),
            (12, 7, 3), (13, 7, 3), (15, 10, 5), (16, 9, 3), (18, 10, 3),
            (21, 13, 5), (22, 15, 7), (25, 15, 6)]
SW_MOLTEN = [(7, 1, 0), (11, 2, 0), (24, 4, 1), (26, 5, 1), (28, 8, 1),
             (28, 11, 2), (30, 15, 3), (30, 18, 4), (30, 20, 5), (31, 24, 9),
             (31, 27, 13), (31, 31, 29)]
SW_SHADOW = [(0, 0, 0), (0, 0, 2), (0, 1, 3), (0, 1, 4), (1, 2, 6), (1, 2, 7),
             (2, 2, 7), (2, 3, 7), (2, 3, 9), (3, 4, 11)]

# --- BG1's 96, at CGRAM 32..127 --------------------------------------------
# THE CEILING IS 127 AND NOT 255, and that is not this rail's choice. An 8bpp
# layer indexes CGRAM DIRECTLY with the pixel value (SnesPpu.cpp:1077) and OBJ
# reads CGRAM[128 + palette*16 + colour] (:960) — the same words. So the
# moment this hall wants a sprite in it, everything at or above 128 belongs to
# OBJ. The budget is drawn for that now rather than re-cut later.
BG1_IX0 = 32
N_COLD, N_WARM, N_MOLTEN, N_BRASS = 36, 16, 32, 12
IX_COLD = BG1_IX0                       # 32.. 67  machined steel: the shafts
IX_WARM = IX_COLD + N_COLD              # 68.. 83  worked iron: the frames
IX_MOLTEN = IX_WARM + N_WARM            # 84..115  the melt, the glow, hot metal
IX_BRASS = IX_MOLTEN + N_MOLTEN         # 116..127 fittings, bands, plaques

PAL_BG1 = [rgb(*c) for c in
           (_stretch(_anchors(SW_STEEL_COLD), N_COLD)
            + _stretch(_anchors(SW_STEEL_WARM), N_WARM)
            + _stretch(_anchors(SW_MOLTEN), N_MOLTEN)
            + _stretch(_anchors(SW_BRASS), N_BRASS))]
assert len(PAL_BG1) == N_COLD + N_WARM + N_MOLTEN + N_BRASS == 96

# --- BG2's two GROUPS, at CGRAM 0..7 ---------------------------------------
# EIGHT GROUPS OF FOUR, NOT ONE SET OF FOUR. A 2bpp tilemap entry carries a
# 3-bit palette field, so the layer has eight sub-palettes inside CGRAM 0..31
# (SnesPpu.cpp:1082) — the rail's first cut used one and drew a warm belt in
# the wall's own cold shades, which is a belt nobody can see move. Group 0 is
# the hall behind the machines; group 1 is the conveyor.
# THE SHEET'S SHADOW RAMP CANNOT SERVE ALONE, and measuring it is what said
# so: its ten swatches span (0,0,0) to (3,4,11) — the whole ramp is near-black,
# because on the sheet it is a SHADOW ramp for an 8bpp layer to sink into, not
# a palette for a layer of its own. Given four colours and asked to be a room,
# it produced a black rectangle. So group 0 takes the shadow ramp's top end and
# continues it up through the cold steel's dark end: still unmistakably behind
# everything, and with enough range to hold a course line.
PAL_BG2 = [rgb(1, 1, 4),                    # g0/0 backdrop — CGRAM word 0, and
                                            #      the hardware's border colour
           rgb(4, 6, 11),                   # g0/1 the far wall
           rgb(7, 10, 16),                  # g0/2 its courses
           rgb(12, 15, 21),                 # g0/3 ...and the lit edge of one
           rgb(0, 0, 0),                    # g1/0 transparent
           rgb(*SW_BRASS[3]),               # g1/1 belt body
           rgb(*SW_BRASS[10]),              # g1/2 belt plate
           rgb(*SW_MOLTEN[9])]              # g1/3 the cleat, catching the pour
BG2_G_WALL, BG2_G_BELT = 0, 1


# --------------------------------------------------------------------------
# geometry — and the column plan is the whole design
# --------------------------------------------------------------------------
COLS = 32                     # a 32-tile map row: the table's width and BG's
ROWS = 32                     # ...and its height. 256 px: a V displacement
                              #   WRAPS in it, which is what lets a shaft run
                              #   the full height with no seam to slide
PHASES = 128                  # the loop closes here
PHASE_SHIFT = 6               # a row is 32 words = 64 B -> index << 6
ROW_BYTES = COLS * 2

# THE ONE-COLUMN FETCH LEAD, AND THE PIER THAT PAYS FOR IT
# The offset words are fetched AFTER a column's tilemap data, so the word at
# BG3 map column j displaces SCREEN column j+1. Smelter measured this and pays
# it at the READ HEAD, because its table is world-space and scrolls; this table
# is screen-space and does not, so it is baked in here — one place, and LEAD is
# emitted so the ASM and the tests read the same number.
#
# AND SCREEN COLUMN 0 CANNOT BE DISPLACED AT ALL — the PPU clears the offset
# latches at the start of each scanline's fetch (SnesPpu.cpp:284-287). That is
# not a thing to pay off, it is a thing to DRAW: a machine that never moves is
# a defect, a WALL that never moves is the room.
LEAD = 1
PIER_COLS = 1                 # screen column 0: the hall's masonry buttress

# THE STATIONS. Four machines, left to right, over the 31 displaceable columns:
#   [upright][shaft][shaft][upright][belt...]
#
# A SHAFT COLUMN IS OPAQUE FOR ITS WHOLE HEIGHT AND CANNOT BE OTHERWISE.
# Bounding it top and bottom would put a horizontal edge in a column that
# slides, so the edge would slide. That is not a cost to minimise away, it is
# the fact to design around: give the station TWO UPRIGHTS and run the ram
# between them, the way the concept sheet's press does, and the frame supplies
# the top and bottom the shaft cannot have. Sixteen shaft columns read as a
# wall of pipes; EIGHT, each in a frame, read as four machines.
STATION_AT = (1, 9, 17, 25)
STATION_W = (8, 8, 8, 7)
SHAFT_COLS = 2                # ...between the uprights at 0 and 3
BELT_AT = 4                   # ...and the conveyor fills the rest

# THE STROKE, in pixels of vertical displacement. A head drawn at map row
# CAP_ROW appears at screen row CAP_ROW*8 - v.
CAP_ROW = 17                  # 136 px down the map
HEAD_ROWS = 2                 # ...and the head is two tiles tall
STROKE = (80, 64, 88, 56)     # per station — four machines, four throws
PERIOD = (1, 2, 1, 1)         # ...and the twin cycles twice a loop
STATION_PHASE = (0, 40, 74, 20)   # ...starting at different points

# THE BELT'S RATE, in units of the H field. It is 8-PIXEL granular — the layer
# keeps its own low three bits — so only multiples of 8 do anything.
BELT_STEP = 4
BELT_DIR = (1, -1, 1, -1)
GANTRY_ROW = 2                # the overhead girder, on BG2 so it can cross
BELT_ROW = 20                 # the conveyor's map row
BELT_PHASES = 8               # EIGHT, not four: at four the belt has only four
                              #   distinct appearances in a whole turn of the
                              #   table (measured), and that reads as a
                              #   flicker rather than as travel

DECK_ROW = 23                 # the floor deck: y 184..199
MELT_ROW = 25                 # ...and the channel under it, y 200..223 — the
                              #   last three rows the 224-line picture shows

# THE CHR PAGES ARE A FIXED SIZE, PADDED. A claim must be FILLED by its
# .incbin (docs/37), so a CHR blob that shrank with an art edit would move
# every claim the packer places after it and drift the .assert in main.asm —
# a build failure for a colour change. The page is the resource; how much of
# it the art currently uses is a number the generator prints.
CHR1_TILES = 192              # 12,288 B — bg1 at 8bpp, 64 B a tile
CHR2_TILES = 64               # 1,024 B — bg2 at 2bpp, 16 B a tile

BIT_BG1 = 0x2000              # this column's offset drives BG1
BIT_BG2 = 0x4000              # ...or BG2
BIT_VSEL = 0x8000             # mode 4 ONLY: this word is a V offset
V_MASK = 0x03FF
H_MASK = 0x03F8


def station_of(col):
    for i, (s, w) in enumerate(zip(STATION_AT, STATION_W)):
        if s <= col < s + w:
            return i
    return None


def kind(col):
    """SCREEN column -> what the art and the table both mean by it.

    ONE COORDINATE SYSTEM, and every consumer converts from it: the map, the
    painter and the word table all ask this function. Two systems is how the
    lead became an off-by-one nobody could see.
    """
    if col < PIER_COLS:
        return "pier"
    st = station_of(col)
    if st is None:
        return "pier"
    k = col - STATION_AT[st]
    if k == 0 or k == 1 + SHAFT_COLS:
        return "upright"
    if k <= SHAFT_COLS:
        return "shaft"
    return "belt"


# --------------------------------------------------------------------------
# BG1 — 8bpp, painted as a picture and THEN cut into tiles
# --------------------------------------------------------------------------
# Painting first and tiling second is how the art gets to look like something.
# The invariance the mechanism needs is enforced WHILE PAINTING — a shaft
# column is filled from a per-x profile, so it is uniform by construction —
# and then asserted again after the cut, so a future edit that breaks it stops
# the build instead of shipping a shaft that slides.
def C(k):  return IX_COLD + max(0, min(N_COLD - 1, int(k)))
def Wm(k): return IX_WARM + max(0, min(N_WARM - 1, int(k)))
def Ml(k): return IX_MOLTEN + max(0, min(N_MOLTEN - 1, int(k)))
def Br(k): return IX_BRASS + max(0, min(N_BRASS - 1, int(k)))

PX = COLS * 8                                   # 256 x 256, the whole map


def _cyl(w, lo, hi, centre=0.32):
    """A round shaded column w pixels wide: a bright specular line off centre,
    falling to dark at both edges. The staple of every machined surface here
    and the reason the cold ramp has 36 steps and not 16."""
    out = []
    for x in range(w):
        t = (x + 0.5) / w
        d = abs(t - centre) / max(centre, 1 - centre)
        out.append(lo + (hi - lo) * max(0.0, 1.0 - d * d * 1.15))
    return out


def shaft_profile(st):
    """The 32-pixel band of a station's four SHAFT columns, as one index per
    x. Every row of those columns is this, which is the vertical-invariance
    contract discharged by construction rather than by care."""
    w = SHAFT_COLS * 8
    if st == 0:                                  # drop hammer: one heavy guide
        p = _cyl(w, 6, 35)
        for x in (0, 1, w - 2, w - 1):
            p[x] = 1
        return [C(v) for v in p]
    if st == 1:                                  # twin pistons: two rods
        p = _cyl(w // 2, 7, 35) + _cyl(w // 2, 7, 35)
        return [C(v) for v in p]
    if st == 2:                                  # crucible: two guide rails,
        p = [None] * w                           #   open between them
        for x, v in zip(range(0, 5), _cyl(5, 9, 33)):
            p[x] = C(v)
        for x, v in zip(range(w - 5, w), _cyl(5, 9, 33)):
            p[x] = C(v)
        return [0 if v is None else v for v in p]
    p = [None] * w                               # press: two thick posts
    for x, v in zip(range(0, 6), _cyl(6, 8, 34)):
        p[x] = C(v)
    for x, v in zip(range(w - 6, w), _cyl(6, 8, 34)):
        p[x] = C(v)
    return [0 if v is None else v for v in p]


def shaft_groups(st):
    """(first column of the group, its width in columns, its phase offset).

    THE TWIN IS TWO GROUPS AND THAT IS THE PER-COLUMN CLAIM MADE VISIBLE: one
    rod one column wide and one two columns wide, half a turn apart, inside a
    single station. Nothing in the table knows they belong to one machine —
    they are simply three adjacent words, and two of them agree."""
    if st == 1:
        return ((0, 1, PHASES // 2), (1, 1, 0))
    return ((0, SHAFT_COLS, 0),)


def head_pixels(st, wcols):
    """The one thing in a shaft column that is NOT row-uniform, and therefore
    the one thing its displacement is seen to move."""
    w = wcols * 8
    buf = [[0] * w for _ in range(16)]
    # THE HEAD IS WARM AND THE SHAFT IS COLD, and that is a legibility rule
    # rather than a palette preference: the head is the only thing in its
    # column that moves, and on a cold cylinder a cold head is a shape nobody
    # can pick out of the shading it slides through. The sheet draws every
    # moving part in brass and hot metal for the same reason.
    body = _cyl(w, 2, N_BRASS - 1)
    for y in range(16):
        for x in range(w):
            buf[y][x] = Br(body[x] * (0.5 + 0.5 * (1 - abs(y - 6) / 12)))
    if st == 0:                                  # ram: a dark band + hot face
        for y in (0, 1, 6, 7):
            for x in range(w):
                buf[y][x] = Wm(3 + 4 * (1 - abs(x - w * 0.3) / w))
        for y in range(12, 16):
            for x in range(1, w - 1):
                buf[y][x] = Ml(12 + (y - 12) * 6)
    elif st == 1:                                # piston cap: collar + crown
        for y in (0, 1, 8, 9):
            for x in range(w):
                buf[y][x] = Wm(2 + 5 * (1 - abs(x - w * 0.3) / w))
        for y in range(13, 16):
            for x in range(1, w - 1):
                buf[y][x] = Ml(8 + (y - 13) * 5)
    elif st == 2:                                # crucible: a vessel of melt
        for y in range(16):
            for x in range(w):
                inside = 3 <= x < w - 3 and 3 <= y < 14
                if inside:
                    buf[y][x] = Ml(4 + 26 * (1 - (y - 3) / 11) ** 1.4)
                elif y in (2, 14) or x in (2, w - 3):
                    buf[y][x] = Br(4 + 6 * (1 - abs(x - w * 0.3) / w))
    else:                                        # platen: a slab, lit beneath
        for y in range(16):
            for x in range(w):
                if y < 3 or y > 12:
                    buf[y][x] = 0
                elif y in (3, 12):
                    buf[y][x] = Br(3 + 8 * (1 - abs(x - w * 0.35) / w))
                else:
                    buf[y][x] = C(body[x] * (0.6 + 0.4 * (1 - (y - 3) / 10)))
        for x in range(1, w - 1):
            buf[13][x] = Ml(24)
            buf[14][x] = Ml(16)
    return buf


# --- the static columns: the pier, the legs, the deck and the channel -------
# NONE OF THIS OWES THE MECHANISM ANYTHING. These columns are never displaced
# (a leg's word holds BG1 at rest; a belt's word drives BG2 and leaves BG1 at
# its fallback), so the art is free: horizontal courses, bolt rows, hazard
# bands, a lit deck edge — every shape the shafts are forbidden.
def paint_pier(buf):
    for y in range(PX):
        for x in range(8):
            course = (y % 24) < 2
            lit = x == 7
            v = 3 if course else 7 + ((x * 5 + (y // 24) * 3) % 5)
            buf[y][x] = Wm(13 if lit else v)
    for y in range(72, 104):                     # a furnace hatch in the wall
        for x in range(1, 7):
            edge = y in (72, 73, 102, 103) or x in (1, 6)
            buf[y][x] = Br(9) if edge else Ml(6 + 20 * (1 - (y - 74) / 28))


def paint_crown(buf, cx, w, st):
    """The head-frame across a station's two uprights, ABOVE the shaft.

    It is what gives the ram a top — the thing a vertically displaced column
    cannot have. Drawn once across the whole 32-pixel station: uprights and
    shafts alike, because at these rows the shaft columns are uniform and the
    crown replaces them... which it cannot. So it stops at the uprights and
    the beam BETWEEN them lives on the shaft columns' own uniform profile.
    That is the constraint refusing a shortcut, and it is why the beam here is
    only the two bracket ends."""
    top = GANTRY_ROW * 8 + 4
    for k, x0 in ((0, cx), (1, cx + w - 8)):
        for y in range(top, top + 20):
            for x in range(8):
                if y < top + 4:
                    v = Wm(15 if 1 <= x < 7 else 3)
                elif y < top + 7:
                    v = Br(9 - (y - top - 4))
                else:
                    v = Wm(2 if x in (0, 7) else 10 + ((x + st) % 3))
                buf[y][x0 + x] = v


def paint_upright(buf, cx, st, side):
    """A station's frame post: BOXY, and deliberately not another cylinder.

    Two columns of flat-shaded worked iron with hard vertical edges, a heavy
    capital, bolt courses every four rows, a maker's plaque and a splayed foot
    on the deck. Every one of those is a HORIZONTAL feature, which is the
    whole point: this column is held at rest by its word, so it may carry the
    shapes a shaft may not, and the contrast between box and cylinder is what
    tells a viewer which part of the machine moves."""
    # DARK, AND THAT IS THE SEPARATION. The uprights and the shafts were the
    # same mid-grey and the picture read as thirty-two bars: value, not hue, is
    # what tells two vertical things apart at this size. The frame is nearer
    # the viewer and in its own shadow, so it goes dark with bright bolt
    # courses; the shaft behind it is a lit cylinder. And the frame may take
    # the MELT'S UPLIGHT on its lower half, which the shaft may not — a
    # gradient is a horizontal feature and a displaced column cannot hold one.
    w = 8
    top, bot = GANTRY_ROW * 8 + 4, DECK_ROW * 8 + 4
    for y in range(top, bot):
        glow = max(0.0, (y - (MELT_ROW * 8 - 72)) / 72)
        for x in range(w):
            edge = x in (0, w - 1)
            inner = 2 <= x < w - 2
            v = 0 if edge else (6 if inner else 3)
            buf[y][cx + x] = Br(2 + 5 * glow) if (glow > 0.45 and not edge) \
                else Wm(v)
    for y in range(top, top + 12):                    # the capital
        for x in range(w):
            over = y < top + 3
            buf[y][cx + x] = Wm(0 if x in (0, w - 1) else (13 if over else 7))
    for gy in range(top + 20, bot - 12, 32):          # bolt courses
        for y in (gy, gy + 1, gy + 2):
            for x in range(1, w - 1):
                buf[y][cx + x] = Br(3 + (5 if y == gy + 1 else 0))
    if side == 0:                                     # one plaque a station
        py = top + 46 + st * 4
        for y in range(py, py + 10):
            for x in range(1, w - 1):
                rim = y in (py, py + 9) or x in (1, w - 2)
                buf[y][cx + x] = Br(10 if rim else 4 + ((x + y + st) % 3) * 2)
    for y in range(bot - 12, bot):                    # the splayed foot
        k = (y - (bot - 12)) // 4
        for x in range(w):
            buf[y][cx + x] = Wm(4 if x < k or x >= w - k else 8)


def paint_belt_front(buf, cx, w):
    """BG1 in a BELT column: STATIC, because that column's word drives BG2.
    So the conveyor's frame, its rollers and the deck under it are full-detail
    8bpp standing in front of a belt that runs. That is the layering doing the
    work, and it is why the picture is not four bays of empty air."""
    top = BELT_ROW * 8 - 3
    for x in range(cx, cx + w):
        for y in (top, top + 1):                 # the rail over the belt
            buf[y][x] = C(24 + ((x // 2) % 3) * 3)
        for y in (top + 21, top + 22, top + 23):  # ...and the trough under it
            buf[y][x] = Wm(3 + (y - top - 21) * 4)
    for x in range(cx + 4, cx + w, 32):          # roller housings, SPARSE:
        for y in range(top + 2, top + 21):       #   the belt behind them is
            for k in range(5):                   #   the thing that moves, and
                if x + k < cx + w:               #   a frame that covers it is
                    buf[y][x + k] = Wm(4 + (3 if 1 <= k <= 3 else 0))


def paint_deck_and_melt(buf, cx, w):
    """The floor the hall stands on and the channel running under it. Static
    art in every column that gets it, so it carries the horizontal courses,
    the hazard skirt and the lit lip that no displaced column could hold."""
    d0, m0 = DECK_ROW * 8, MELT_ROW * 8
    for x in range(cx, cx + w):
        for y in range(d0, m0):
            r = y - d0
            if r < 2:                            # the deck's lit top edge
                buf[y][x] = Wm(15 if (x % 32) < 16 else 12)
            elif r < 5:                          # a hazard skirt
                buf[y][x] = (Br(11) if ((x + r * 2) % 12) < 6 else Wm(2))
            elif r in (14, 15):
                buf[y][x] = Wm(3)
            else:
                buf[y][x] = Wm(5 + ((x // 4 + r) % 3))
        for y in range(m0 - 3, m0):              # the lip catching the glow
            buf[y][x] = Ml(24 + (y - m0 + 3) * 3)
        for y in range(m0, PX):                  # the channel, uplighting all
            d = min(1.0, (y - m0) / 40)
            n = ((x * 7 + (y // 2) * 5) % 13) / 13
            buf[y][x] = Ml(min(N_MOLTEN - 1, 9 + 20 * (1 - d) + 6 * n))


def paint_bg1():
    buf = [[0] * PX for _ in range(PX)]
    paint_pier(buf)
    for st, (s, w) in enumerate(zip(STATION_AT, STATION_W)):
        prof = shaft_profile(st)
        sx = (s + 1) * 8
        for x in range(len(prof)):               # THE SHAFTS: one index per x,
            for y in range(PX):                  #   every row identical
                buf[y][sx + x] = prof[x]
        for k0, wc, _ in shaft_groups(st):
            head = head_pixels(st, wc)
            for y in range(16):
                for x in range(wc * 8):
                    buf[CAP_ROW * 8 + y][sx + k0 * 8 + x] = head[y][x]
        paint_upright(buf, s * 8, st, 0)                  # the near upright
        paint_upright(buf, (s + 1 + SHAFT_COLS) * 8, st, 1)   # ...and the far
        paint_crown(buf, s * 8, (2 + SHAFT_COLS) * 8, st)
        bx = (s + BELT_AT) * 8
        bw = (w - BELT_AT) * 8
        paint_belt_front(buf, bx, bw)
        paint_deck_and_melt(buf, s * 8, 8)
        paint_deck_and_melt(buf, (s + 1 + SHAFT_COLS) * 8, 8)
        paint_deck_and_melt(buf, bx, bw)
    paint_deck_and_melt(buf, 0, 8)
    return buf


# --------------------------------------------------------------------------
# BG2 — 2bpp, and EVERY MAP ROW IS ONE TILE ACROSS ITS WHOLE WIDTH
# --------------------------------------------------------------------------
# That is not a stylistic choice, it is the horizontal-displacement contract:
# a shifted column shows the NEIGHBOURING tile, so anything that must not
# appear to move has to be the same tile everywhere in its row. The far wall
# therefore varies VERTICALLY only — courses, a gantry band, a datum line —
# and the one thing that varies along a row is the conveyor tread, whose
# PHASE is exactly what the shift is meant to change.
def wall_row(r):
    """One 8x8 tile, palette group 0 — the hall BEHIND, in four colours.

    ARCHITECTURE, NOT TEXTURE. Every map row of this layer is one tile across
    its whole width (the H-displacement contract), so nothing here may vary
    along a row except by 8-pixel repeat — and a diagonal hatch, which is what
    the first cut used, reads as noise rather than as a room. What a horizontal
    band CAN say is depth: a dark head-height, a lit mezzanine rail, brick
    courses that get closer together toward the floor, and a datum line where
    the far wall meets the deck. All of that is free, because these columns are
    displaced only by the BELTS, and a belt's shift cannot move a tile that is
    repeated everywhere."""
    rows = []
    for y in range(8):
        gy = r * 8 + y
        if gy < 16:                                     # the roof, receding
            rows.append([0 if (gy < 6 or (x % 8) < 5) else 1 for x in range(8)])
        elif gy in (72, 73):                            # the mezzanine rail
            rows.append([3] * 8)
        elif gy == 74:
            rows.append([2] * 8)
        elif 75 <= gy < 82:                             # ...and its balusters
            rows.append([2 if (x % 4) == 1 else 1 for x in range(8)])
        elif gy % 24 == 0:                              # a brick course
            rows.append([2] * 8)
        elif gy % 24 == 1:
            rows.append([3 if (x % 8) < 4 else 2 for x in range(8)])
        elif gy % 24 == 23:
            rows.append([0] * 8)
        elif gy >= 176:                                 # the wall's dark foot
            rows.append([0 if (x % 8) < 6 else 1 for x in range(8)])
        else:
            rows.append([1] * 8)          # FLAT. Any x-variation here reads as
                                          #   a vertical stripe once it is
                                          #   repeated down a whole wall, which
                                          #   is the one direction this layer
                                          #   must not appear to have structure
    return rows


def gantry_row(half):
    """The overhead crane girder, ON BG2 — which is the only layer it can be
    on. It has to cross the SHAFT columns, and a shaft column is displaced, so
    a girder drawn there on BG1 would ride up and down with the ram. Here it is
    one tile repeated across the whole row: the belts shift it and nothing
    changes, and the shafts do not touch it at all."""
    rows = []
    for y in range(8):
        if half == 0:                                    # the top flange
            rows.append([3 if y in (2, 3) else (2 if y > 3 else 0)
                         for _ in range(8)])
        else:                                            # ...the web and lugs
            rows.append([2 if y < 2 else (3 if y == 2 else
                        (1 if (x % 8) < 3 else 0)) for x in range(8)])
    return rows


def tread_tile(k):
    """One phase of the conveyor, palette group 1. A shift of j tiles shows
    phase (c + j) mod BELT_PHASES, so the pattern's PHASE is what travels —
    the only shape a horizontally displaced column can animate. The cleat is
    DIAGONAL: a vertical bar looks identical shifted by its own period and
    reads as a stutter."""
    rows = []
    for y in range(8):
        if y in (0, 7):
            rows.append([2] * 8)
        else:
            rows.append([3 if ((x + y + k * 3) % BELT_PHASES) < 3 else 1
                         for x in range(8)])
    return rows


# --------------------------------------------------------------------------
# encoders
# --------------------------------------------------------------------------
def encode_8bpp(rows, who):
    """One 8x8 tile, 64 bytes: four bitplane PAIRS, planes 0/1 then 2/3 then
    4/5 then 6/7, each pair interleaved by row the way 4bpp's first pair is."""
    out = bytearray()
    for pair in range(4):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                assert 0 <= v < 256, f"{who}: index {v} is not 8bpp"
                assert v < 128, (f"{who}: index {v} is at or above 128, where "
                                 f"OBJ's palettes live (SnesPpu.cpp:960)")
                lo |= ((v >> (pair * 2)) & 1) << (7 - x)
                hi |= ((v >> (pair * 2 + 1)) & 1) << (7 - x)
            out += bytes((lo, hi))
    return bytes(out)


def encode_2bpp(rows, who):
    out = bytearray()
    for y in range(8):
        lo = hi = 0
        for x in range(8):
            v = rows[y][x]
            assert 0 <= v < 4, f"{who}: index {v} is not 2bpp"
            lo |= (v & 1) << (7 - x)
            hi |= ((v >> 1) & 1) << (7 - x)
        out += bytes((lo, hi))
    return bytes(out)


def pal_bytes(words):
    out = bytearray()
    for w in words:
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


# --------------------------------------------------------------------------
# the cut: a painted picture -> unique tiles + a tilemap
# --------------------------------------------------------------------------
def cut(buf):
    tiles, index, tmap = [], {}, []
    for r in range(ROWS):
        row = []
        for c in range(COLS):
            key = tuple(tuple(buf[r * 8 + y][c * 8 + x] for x in range(8))
                        for y in range(8))
            if key not in index:
                index[key] = len(tiles)
                tiles.append([list(t) for t in key])
            row.append(index[key])
        tmap.append(row)
    return tiles, tmap


def assert_shaft_invariance(buf):
    """THE CONTRACT, RE-CHECKED AFTER PAINTING. A shaft column is displaced
    vertically, so every row of it outside the head band must be identical —
    the generator paints it that way, and this is what stops a future edit
    from quietly reintroducing the seam that slides."""
    head = range(CAP_ROW * 8, CAP_ROW * 8 + 16)
    for st, s in enumerate(STATION_AT):
        for x in range((s + 1) * 8, (s + 1 + SHAFT_COLS) * 8):
            seen = {buf[y][x] for y in range(PX) if y not in head}
            assert len(seen) == 1, (
                f"station {st} shaft x={x} has {len(seen)} distinct values "
                f"outside the head band — a V-displaced column must be "
                f"identical row to row")


# --------------------------------------------------------------------------
# the offset row — ONE word a column, and bit 15 picks its axis
# --------------------------------------------------------------------------
def piston_v(col, phase):
    """A stroke. The hammer FALLS fast and rises slow; the others are even.
    Per station, so the four machines read as four machines."""
    import math
    st = station_of(col)
    k = col - STATION_AT[st] - 1
    sub = next(o for k0, wc, o in shaft_groups(st) if k0 <= k < k0 + wc)
    t = ((phase * PERIOD[st] + STATION_PHASE[st] + sub) % PHASES) / PHASES
    if st == 0:                                  # the hammer: a fast drop
        u = (1 - math.cos(2 * math.pi * t)) / 2
        u = u ** 3 if t < 0.5 else u ** 0.6
    else:
        u = (1 - math.cos(2 * math.pi * t)) / 2
    return int(round(STROKE[st] * u))


def belt_h(col, phase):
    st = station_of(col)
    return (BELT_DIR[st % len(BELT_DIR)] * BELT_STEP * phase) & 0x3FF


def column_word(col, phase):
    """The word for SCREEN column `col`. Where it is STORED is row_table's
    business — that is the one place the lead is applied."""
    k = kind(col)
    if k == "pier":
        return 0                                 # unreachable, or at rest
    if k == "leg":
        return BIT_BG1 | BIT_VSEL | 0            # driven, and held AT REST:
    if k == "shaft":                             #   the frame does not move
        return BIT_BG1 | BIT_VSEL | (piston_v(col, phase) & V_MASK)
    return BIT_BG2 | (belt_h(col, phase) & H_MASK)


def flat_word(col):
    """The control row. THE ENABLE BITS AND THE AXIS BIT STAY SET and only the
    VALUE goes to rest — smelter's rule and heathaze's before it: a control
    that also disarms the mechanism cannot tell a broken table from a broken
    transfer, because both produce the same still picture."""
    k = kind(col)
    if k == "pier":
        return 0
    if k in ("leg", "shaft"):
        return BIT_BG1 | BIT_VSEL | 0
    return BIT_BG2 | 0


def row_table():
    """One row per phase, then the flat control — and THE LEAD IS APPLIED HERE
    AND ONLY HERE. Index j holds the word for SCREEN COLUMN j + LEAD, because
    that is the column the PPU will hand it to."""
    out = bytearray()
    for phase in range(PHASES):
        for j in range(COLS):
            w = column_word(j + LEAD, phase) if j + LEAD < COLS else 0
            out += bytes((w & 0xFF, w >> 8))
    for j in range(COLS):
        w = flat_word(j + LEAD) if j + LEAD < COLS else 0
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------
def main():
    buf = paint_bg1()
    assert_shaft_invariance(buf)
    tiles1, map1 = cut(buf)
    assert len(tiles1) <= CHR1_TILES, (
        f"BG1 needs {len(tiles1)} tiles, the page holds {CHR1_TILES}")
    chr1 = b"".join(encode_8bpp(t, f"bg1 tile {i}") for i, t in enumerate(tiles1))
    chr1 += bytes(64 * (CHR1_TILES - len(tiles1)))

    # BG2: one tile per MAP ROW (the H-invariance contract), plus the tread
    # phases, which are the one thing along a row that may differ.
    tiles2 = [wall_row(r) for r in range(ROWS)]
    gant = len(tiles2)
    tiles2 += [gantry_row(0), gantry_row(1)]
    tread0 = len(tiles2)
    tiles2 += [tread_tile(k) for k in range(BELT_PHASES)]
    assert len(tiles2) <= CHR2_TILES, (
        f"BG2 needs {len(tiles2)} tiles, the page holds {CHR2_TILES}")
    chr2 = b"".join(encode_2bpp(t, f"bg2 tile {i}") for i, t in enumerate(tiles2))
    chr2 += bytes(16 * (CHR2_TILES - len(tiles2)))

    def m1():
        out = bytearray()
        for r in range(ROWS):
            for c in range(COLS):
                t = map1[r][c]
                out += bytes((t & 0xFF, t >> 8))
        return bytes(out)

    def m2():
        out = bytearray()
        for r in range(ROWS):
            for c in range(COLS):
                if r in (GANTRY_ROW, GANTRY_ROW + 1):
                    t, g = gant + (r - GANTRY_ROW), BG2_G_WALL
                elif BELT_ROW <= r < BELT_ROW + 2:
                    t, g = tread0 + (c % BELT_PHASES), BG2_G_BELT
                else:
                    t, g = r, BG2_G_WALL
                w = t | (g << 10)
                out += bytes((w & 0xFF, w >> 8))
        return bytes(out)

    (OUT / "mil_chr1.bin").write_bytes(chr1)
    (OUT / "mil_chr2.bin").write_bytes(chr2)
    (OUT / "mil_map1.bin").write_bytes(m1())
    (OUT / "mil_map2.bin").write_bytes(m2())
    # ONE PALETTE BLOB, TWO GROUPS, and the offset is emitted beside it: two
    # claims are two blobs the packer orders by SIZE, and an uploader reaching
    # the second by a distance from the first reads a sign it does not choose.
    (OUT / "mil_pal.bin").write_bytes(pal_bytes(PAL_BG1) + pal_bytes(PAL_BG2))
    (OUT / "mil_row.bin").write_bytes(row_table())

    inc = f"""; mil_art.inc — GENERATED by tools/gen_mill_assets.py. Do not edit.
; The machine hall's geometry, so the ASM and the tests read ONE copy of it.
SMIL_COLS         = {COLS}
SMIL_ROWS         = {ROWS}
SMIL_PHASES       = {PHASES}    ; the loop closes here
SMIL_FLAT_INDEX   = {PHASES}    ; ...and the control row sits past it
SMIL_ROW_COUNT    = {PHASES + 1}
SMIL_PHASE_SHIFT  = {PHASE_SHIFT}      ; a row is {ROW_BYTES} B -> index << {PHASE_SHIFT}
SMIL_ROW_BYTES    = {ROW_BYTES}
SMIL_LEAD         = {LEAD}      ; the word at index j displaces SCREEN column
                           ;   j+LEAD -- the offset words are fetched AFTER a
                           ;   column's tilemap data. Baked into the blob
SMIL_PIER_COLS    = {PIER_COLS}      ; ...so screen column 0 gets no word at all
                           ;   and is drawn as the hall's wall, not as a
                           ;   machine that never moves
SMIL_STATIONS     = {len(STATION_AT)}
SMIL_BELT_AT      = {BELT_AT}
SMIL_SHAFT_COLS   = {SHAFT_COLS}
SMIL_CAP_ROW      = {CAP_ROW}     ; the head's map row
SMIL_BELT_ROW     = {BELT_ROW}
SMIL_BELT_PHASES  = {BELT_PHASES}
SMIL_TILES1       = {len(tiles1)}
SMIL_TILES2       = {len(tiles2)}
SMIL_BG1_IX0      = {BG1_IX0}     ; BG1 is 8bpp and indexes CGRAM directly, so
SMIL_BG1_COLOURS  = {len(PAL_BG1)}     ;   its art starts past BG2's groups...
SMIL_BG1_IX_MAX   = 127    ; ...and stops below OBJ's, which own 128..255
SMIL_PAL2_OFF     = {2 * len(PAL_BG1)}    ; BG2's two groups, inside the one blob
SMIL_PAL2_WORDS   = {len(PAL_BG2)}

; THE FALLBACK PORTS' REST VALUES. A column whose word does not carry a
; layer's enable bit shows that layer at its own BGnVOFS/BGnHOFS.
SMIL_BG1_REST     = 0
SMIL_BG2_REST     = 0
"""
    (OUT / "mil_art.inc").write_text(inc)
    print(f"  mill: chr1 {len(chr1)} B ({len(tiles1)}/{CHR1_TILES} x 8bpp), "
          f"chr2 {len(chr2)} B ({len(tiles2)}/{CHR2_TILES} x 2bpp), "
          f"pal {2 * (len(PAL_BG1) + len(PAL_BG2))} B "
          f"({len(PAL_BG1)} BG1 + {len(PAL_BG2)} BG2), "
          f"row table {PHASES}+1 x {ROW_BYTES} B")


if __name__ == "__main__":
    main()
