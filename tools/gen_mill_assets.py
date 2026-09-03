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

ROOT = pathlib.Path(__file__).resolve().parent.parent
KIT = ROOT / "vendor" / "art" / "forge_line"

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

# THE PALETTE IS FITTED TO THE PICTURE, NOT A CURVE THROUGH THE ART.
#
# The four ramps above are the sheet's own swatches, and the first cut built
# the palette by INTERPOLATING them -- `_stretch(_anchors(SW_*), n)` -- then
# quantised the kit art onto the result by nearest entry. That places the
# entries along a 1-D CURVE while the art is a 3-D CLOUD around it, and the
# tree that shipped it measured the cost: only 76 of 96 claimed CGRAM entries
# were ever drawn, and the cold ramp used 19 of its 36.
#
# An 8bpp layer indexes CGRAM DIRECTLY with no palette field, so the palette
# can be chosen FROM the art instead. The second cut fitted the SHEETS --
# per-family k-means over every kit pixel at source resolution -- which
# weighted a rail strip the rail paints as one 32-pixel row the same as the
# lobby wall that covers a whole scene, and never saw the delivered art at
# all. This cut fits WHAT IS ON SCREEN: `tools/fit_mill_palette.py` runs the
# painters below with SOURCE set (see `kit`), takes every BG1 pixel of every
# room the rail shows, and fits each family to its share of that cloud. It
# also CHOOSES THE SPLIT -- the four ramp lengths were 36/16/32/12 by hand;
# now each family's error is measured at every length and the split with the
# least total on-screen error is taken. The painters address tones as
# FRACTIONS of a ramp (`Wm(t)`, below) so a split can move without any of
# them being retouched; every ramp stays MONOTONE by luminance so a fraction
# keeps meaning "that far from dark to light".
#
# GENERATED, and committed rather than computed at build time for the reason
# KIT_BOX carries: a build must not depend on a clustering pass agreeing with
# itself run to run. A family with fewer DISTINCT entries than its length
# keeps the duplicates -- every fraction must land on a real step, and a ramp
# that cannot fill itself is saying the art has no more steps to give.
# Regenerate with `python3 tools/fit_mill_palette.py --write` -- and do so
# whenever a room is added or its art changes, because the cloud is the
# picture.
# --- GENERATED by tools/fit_mill_palette.py: begin ---
# Do not hand-edit. Fitted to the PICTURE -- every BG1 pixel of the hall's
# two screens, the melt's one and the lobby's, each counted once -- and the split chosen
# to minimise the total on-screen error (floor 8 a ramp; the warm ramp
# floors at its 16 hand-dithered tones). 100890 source px in the
# cloud, 28714 drawn by hand on the ramps, 188 rejected as key
# fringe. Error is the eye-weighted squared distance per on-screen source
# pixel, against the ramps and split this run replaced:
#   cold    69379 px (68.8%)  24 -> 24 entries (23 distinct)  error   10.9 ->   10.9  (hand-drawn area 0 px, 0 tones)
#   warm    10015 px ( 9.9%)  24 -> 24 entries (24 distinct)  error    1.2 ->    1.2  (hand-drawn area 26882 px, 16 tones)
#   molten  11198 px (11.1%)   8 -> 12 entries (12 distinct)  error  630.2 ->   10.3  (hand-drawn area 688 px, 31 tones)
#   brass   10298 px (10.2%)  40 -> 36 entries (35 distinct)  error    4.4 ->    4.6  (hand-drawn area 1144 px, 34 tones)
#   total                          error  646.7 ->   27.0 (-96%)
N_COLD, N_WARM, N_MOLTEN, N_BRASS = 24, 24, 12, 36
FIT_STEEL_COLD = [(2,3,5), (3,3,4), (2,3,6), (2,3,6), (3,3,7), (3,4,5), (3,4,8), (5,4,4), (3,4,9), (6,4,5), (4,5,6), (5,5,5), (4,5,9), (5,6,10), (5,7,10), (6,7,9), (7,8,11), (8,9,12), (10,10,13), (14,14,14), (18,19,20), (22,22,22), (27,25,23), (28,29,29)]
FIT_STEEL_WARM = [(7,5,6), (5,6,7), (6,6,5), (7,6,5), (6,6,9), (7,7,6), (9,6,8), (9,7,6), (8,8,7), (9,8,8), (8,8,11), (11,9,6), (12,8,9), (11,10,9), (12,11,11), (11,11,13), (13,12,10), (14,13,12), (18,12,12), (16,15,14), (17,16,15), (20,17,14), (19,18,16), (20,19,17)]
FIT_MOLTEN = [(8,2,2), (12,1,2), (17,3,1), (25,5,1), (30,9,1), (31,18,4), (28,22,10), (31,22,7), (31,25,10), (31,27,14), (31,30,20), (31,30,27)]
FIT_BRASS = [(1,0,0), (1,0,1), (1,1,1), (1,1,3), (2,1,1), (2,1,3), (2,1,4), (4,0,4), (1,2,4), (3,1,4), (3,1,5), (3,2,2), (2,2,5), (2,2,5), (3,2,5), (3,3,2), (4,3,2), (5,3,1), (4,3,4), (7,3,4), (6,4,3), (7,4,2), (8,5,4), (9,5,2), (10,7,3), (13,5,6), (13,7,3), (12,8,4), (14,11,6), (17,10,4), (18,13,7), (22,13,5), (26,14,0), (23,18,10), (23,19,13), (25,20,10)]
# --- GENERATED by tools/fit_mill_palette.py: end ---
IX_COLD = BG1_IX0                       # machined steel: the shafts, and the
                                        #   lobby's wall
IX_WARM = IX_COLD + N_COLD              # worked iron: the machine housings
                                        #   and the lift frames.
                                        # TICK: ok -- a CGRAM index. `frames`
                                        #   here is ironwork, not animation
IX_MOLTEN = IX_WARM + N_WARM            # the melt, the glow, hot metal
IX_BRASS = IX_MOLTEN + N_MOLTEN         # fittings, bands, plaques

PAL_BG1 = [rgb(*c) for c in
           (FIT_STEEL_COLD + FIT_STEEL_WARM + FIT_MOLTEN + FIT_BRASS)]
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
           rgb(*SW_BRASS[9]),               # g1/2 belt plate
           rgb(*SW_BRASS[13])]              # g1/3 the cleat's lit edge — BRASS
                                            #      and not molten: the belt is
                                            #      the second-loudest thing on
                                            #      screen and the channel is the
                                            #      first, so a hot cleat put two
                                            #      light sources in one picture
                                            #      and the eye went to the wrong
                                            #      one
BG2_G_WALL, BG2_G_BELT = 0, 1


# --------------------------------------------------------------------------
# geometry — and the column plan is the whole design
# --------------------------------------------------------------------------
COLS = 32                     # a 32-tile map row: the table's width and BG's
ROWS = 64                     # ...and its height. 512 px, a 32x64 tilemap:
                              #   the world is TWO SCREENS TALL and the camera
                              #   climbs it. A V displacement wraps in the map,
                              #   which is what lets a shaft run the full
                              #   height with no seam to slide
WORLD_H = ROWS * 8            # ...of which this much is drawn: ALL of it now.
                              #   The camera bottoms out at the map's last
                              #   screen, because that is where the molten
                              #   channel is and the channel is the floor both
                              #   rooms share (SMIL_FLOOR_Y below)
                              #   screens. The 64 rows past it are the shaft
                              #   columns' wrap and are never shown undisplaced
CAM_MAX = WORLD_H - 224       # the camera's travel, in pixels
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
#   [upright][shaft x4][upright][belt x6]  -- TWO stations, not four.
#
# THE SCALE COMES FROM THE ART. The concept sheet's own placement manifest puts
# a machine across about eleven columns; four of those do not fit on a 32-column
# screen and the four-station version was four copies of one small machine. Two
# stations at the sheet's scale is a hall with two DIFFERENT machines in it, and
# the ram is then four columns wide -- exactly the 32 px the kit's ram art is
# drawn at, so the art arrives at its own size instead of being squeezed.
#
# A SHAFT COLUMN IS OPAQUE FOR ITS WHOLE HEIGHT AND CANNOT BE OTHERWISE.
# Bounding it top and bottom would put a horizontal edge in a column that
# slides, so the edge would slide. That is not a cost to minimise away, it is
# the fact to design around: give the station TWO UPRIGHTS and run the ram
# between them, the way the concept sheet's press does, and the frame supplies
# the top and bottom the shaft cannot have. Sixteen shaft columns read as a
# wall of pipes; EIGHT, each in a frame, read as four machines.
STATION_AT = (1, 13)
STATION_W = (12, 12)
SHAFT_COLS = 4                # ...between the uprights at 0 and 5
BELT_AT = 6                   # ...and the conveyor fills the rest
TAIL_AT = 25                  # ...then a conveyor run out to the right edge

# THE STROKE, in pixels of vertical displacement. A head drawn at map row
# CAP_ROW appears at screen row CAP_ROW*8 - v.
FLOOR = 28                    # the forge floor's first map row: the lower
                              #   screen is rows 28..55, the shaft house above
# TWO HEADS, TWO ROWS, and they were one constant until the deck became a place
# to stand. A ram and a lift car are the same SHAPE — a head 48 px tall on a
# displaced column — so sharing the row read as economy. What separates them is
# what each has to reach:
#
#   the CAR has to land ON the deck, because a lift you cannot walk into is a
#   lift nobody boards. Its bottom is the deck's top.
#   the RAM has nothing to meet, and that is not an oversight — THERE IS NO
#   FLOOR UNDER IT. A shaft column is displaced vertically, so it must be
#   identical row to row, and a deck is a horizontal course; the four columns a
#   station's shaft occupies therefore cannot have one. The hammer falls past
#   the deck line into the melt, which is what the picture already showed and
#   what DECK_COLS below records. Its row stays where the art wants it.
#
# (An earlier cut of this split moved the ram DOWN so it would bite into a
# figure standing under it. Measured afterwards: nobody can stand under it.)
HEAD_ROWS = 6                 # the kit's ram is 48 px, six tiles tall
CAP_ROW = FLOOR + 13          # the ram's top map row
STROKE = (72, 0)              # station 0 is the drop hammer; station 1 is the
PERIOD = (1, 1)               #   ELEVATOR and its column is not driven by the
STATION_PHASE = (0, 0)        #   phase at all — the scene drives it

ELEVATOR = 1                  # ...which station's shaft carries the car
CAR_H = HEAD_ROWS * 8         # ...and its height
# THE PORT HAS TO BE SMALLER THAN THE MAN, or the occlusion it exists for
# never happens. The first cut was 22x30 in a 32x48 car and the rider's ink is
# 11x17 — eight pixels of clearance on every side — so the shell had nothing to
# cut and priority 0 was doing no observable work at all. That is not a defect
# a look would find, because the picture is right either way; it was found by
# tools/plants/mill.py::the-rider-outranks-the-car coming back TEST-BLIND, i.e.
# by the harness reporting that the mechanism could be REMOVED without the
# screen changing. A viewing port down to about the knees cuts his legs, which
# is both what the plant needs and what a lift door actually looks like.
WINDOW = (7, 26, 18, 18)      # x0, y0, w, h of the glass, inside the car.
                              #   LOW IN THE DOOR, because a man standing on
                              #   the car's floor has his head there. The car
                              #   is 48 px and he is 32, so his box starts 16
                              #   down it and his drawn content 11 further —
                              #   a port at the top of the door shows the space
                              #   above his helmet. Placed here, ONE formula
                              #   puts him in the car whether it is parked on
                              #   the deck or halfway up the shaft.
                              #   THE HOLE IS THE EFFECT: BG1 is transparent
                              #   here and opaque everywhere else on the car,
                              #   and an OBJ at priority 0 loses to BG1's
                              #   normal priority (SnesPpu.cpp:958 —
                              #   `_mainScreenFlags[x] & 0x0F` must be LESS
                              #   than the sprite's, and mode 4 gives BG1
                              #   3 against OBJ0's 2). So the rider is drawn
                              #   only where this rectangle is, with no mask
                              #   register and no per-scanline work

# THE BELT'S RATE, in units of the H field. It is 8-PIXEL granular — the layer
# keeps its own low three bits — so only multiples of 8 do anything.
BELT_STEP = 4
BELT_DIR = (1, -1, 1, -1)
GANTRY_ROW = FLOOR + 10               # the overhead girder, on BG2 so it can cross
                                      #   -- and it is TEN rows down, not two,
                                      #   because the camera now rests at the
                                      #   map's bottom to put the channel on
                                      #   screen and a girder at FLOOR+2 sat
                                      #   sixteen pixels above the picture.
                                      #   The uprights hang from it, so moving
                                      #   it moves them, which is why there is
                                      #   one number here and not three
BELT_ROW = FLOOR + 20                 # the conveyor's map row
BELT_PHASES = 8               # EIGHT, not four: at four the belt has only four
                              #   distinct appearances in a whole turn of the
                              #   table (measured), and that reads as a
                              #   flicker rather than as travel

# THE FLOOR IS THE SAME LINE IN BOTH ROOMS, AND THE CHANNEL UNDER IT IS THE
# SAME ART AT THE SAME HEIGHT. The lobby is the ground floor at the bottom of
# the shaft and the hall is what the lift opens onto, so a molten channel that
# jumped between them would be two channels. These two rows and LOBBY_FLOOR
# below are the one statement of that, asserted rather than commented: the
# deck lands at SMIL_FLOOR_Y on screen in each room and the channel runs from
# there to the bottom of the picture.
DECK_ROW = FLOOR + 27                 # the floor deck...
MELT_ROW = FLOOR + 29                 # ...and the channel under it, running to
                              #   the map's last row: 56 lines of the picture,
                              #   where the hall used to show three
FLOOR_Y = DECK_ROW * 8 - (ROWS * 8 - 224)   # the deck's SCREEN row at rest, in
                                            #   both rooms (see LOBBY_FLOOR)
CHANNEL_Y = MELT_ROW * 8 - (ROWS * 8 - 224)  # ...and the channel's

# ...and now the two heads can be derived from it, which is the whole reason
# they were split. STAND_Y is where a figure's feet go; RAM_BITE is how far
# into him the hammer comes at the bottom of its stroke, so the hazard is a
# stated number rather than an accident of two rows.
STAND_Y = DECK_ROW * 8                # the deck's top: a standing figure's feet
CAR_ROW = (STAND_Y - CAR_H) // 8      # the car LANDS on it
RAM_BITE = STAND_Y - 32 - (CAP_ROW * 8 + HEAD_ROWS * 8)
assert CAR_ROW * 8 + CAR_H == STAND_Y, "the car must land on the deck"


def head_row(st):
    """Which map row this station's head is pasted at, and staged against.

    ONE FUNCTION, so the painter, the invariance check and the emitted
    constants cannot disagree about it — which they did for one build, with the
    car's art at the ram's row and the rider staged at the car's.
    """
    return CAR_ROW if st == ELEVATOR else CAP_ROW

# THE CHR PAGES ARE A FIXED SIZE, PADDED. A claim must be FILLED by its
# .incbin (docs/37), so a CHR blob that shrank with an art edit would move
# every claim the packer places after it and drift the .assert in main.asm —
# a build failure for a colour change. The page is the resource; how much of
# it the art currently uses is a number the generator prints.
CHR1_TILES = 384              # 24,576 B — bg1 at 8bpp, 64 B a tile. RAISED
                              #   AGAIN from 320 when the palette stopped being
                              #   an interpolated curve and started being fitted
                              #   to the art (see FIT_* above): a richer palette
                              #   DEDUPES LESS, because fewer 8x8 blocks come
                              #   out byte-identical once the shading between
                              #   them survives quantisation. 328 tiles needed
                              #   against a 320 page — the overflow is the
                              #   measurement that the fit is carrying more.
                              #   Originally RAISED
                              #   from 192 when the kit's art arrived: converted
                              #   assets dedupe far less than procedural ones,
                              #   because every pixel of authored shading is a
                              #   little different from its neighbour
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
        return "belt" if col >= TAIL_AT else "pier"
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
# --------------------------------------------------------------------------
# the kit — the concept sheets, resampled into this palette
# --------------------------------------------------------------------------
# vendor/art/forge_line/README.md is the whole argument for why this is a
# CONVERSION and not an extraction; the short version is that the sheets carry
# no pixel grid (0.00% of aligned 8x8 blocks constant, and no integer upscale
# underneath) but every asset is isolated on a chroma key, so each one can be
# resampled to the footprint its layer gives it.
#
# BOXES ARE THE SEGMENTER'S, NOT EYEBALLED: tools/kit_import.py finds them by
# row band then column run. They are written out here because a build must not
# depend on a segmentation pass agreeing with itself run to run.
KIT_BOX = {
    "rail_a": ("frames_sheet", (82, 58, 242, 836)),
    "rail_b": ("frames_sheet", (268, 58, 400, 836)),
    "rail_c": ("frames_sheet", (557, 58, 678, 836)),
    "rail_d": ("frames_sheet", (745, 58, 860, 836)),
    "ram": ("ram_fx_sheet", (226, 82, 370, 332)),
    "post": ("conveyor_sheet", (759, 481, 845, 682)),
    "footing": ("frames_sheet", (85, 852, 1028, 946)),
    "roller": ("conveyor_sheet", (130, 481, 497, 682)),
    "billet": ("frames_sheet", (761, 996, 986, 1038)),
    "panel_flue": ("conveyor_sheet", (130, 808, 246, 926)),
    "panel_brace": ("conveyor_sheet", (342, 808, 458, 926)),
    "panel_valve": ("conveyor_sheet", (555, 808, 670, 926)),
    "panel_hatch": ("conveyor_sheet", (767, 808, 883, 926)),
    "panel_rivet": ("conveyor_sheet", (980, 808, 1096, 926)),
    "panel_duct": ("conveyor_sheet", (1197, 808, 1313, 926)),
}
_KIT_CACHE = {}

# PROVENANCE, FOR THE FITTER. `tools/fit_mill_palette.py` fits the palette to
# what is ON SCREEN, and the only honest way to know what is on screen is to
# run the painters. So when SOURCE is a dict, the two quantisers below stop
# quantising: every opaque source pixel gets a SOURCE ID (256 and up, so it
# can never be mistaken for a CGRAM index) whose RGB888 is recorded in SOURCE,
# and the painters paint those ids exactly where they would have painted the
# nearest entry. A pixel the painters draw by hand -- `Wm(t)`, a tone rather
# than a colour -- stays an ordinary index, and the fitter counts it but does
# not fit it: it will be whatever the ramp has at that fraction.
#
# Nothing in a normal build sets SOURCE, and the build does not read it.
SOURCE = None
_SOURCE_IX = {}


def _source_id(rgb):
    if rgb not in _SOURCE_IX:
        _SOURCE_IX[rgb] = 256 + len(SOURCE)
        SOURCE[_SOURCE_IX[rgb]] = rgb
    return _SOURCE_IX[rgb]


def rgb888(v):
    """A painted value -> its RGB888: a CGRAM index through the palette, or a
    source id through SOURCE."""
    if v >= 256:
        return SOURCE[v]
    w = PAL_BG1[v - BG1_IX0]
    return ((w & 31) << 3 | (w & 31) >> 2,
            ((w >> 5) & 31) << 3 | ((w >> 5) & 31) >> 2,
            ((w >> 10) & 31) << 3 | ((w >> 10) & 31) >> 2)


def rgb555(v):
    """...and the same in the palette's own 5-bit units."""
    if v >= 256:
        return tuple(c >> 3 for c in SOURCE[v])
    w = PAL_BG1[v - BG1_IX0]
    return (w & 31, (w >> 5) & 31, (w >> 10) & 31)


def kit(name, size):
    """One converted asset as an index buffer, cached. Imported lazily because
    kit_import reads THIS module's palette — importing it at module scope is a
    cycle."""
    key = (name, size)
    if key not in _KIT_CACHE:
        import kit_import
        sheet, box = KIT_BOX[name]
        if SOURCE is None:
            _KIT_CACHE[key] = kit_import.convert(str(KIT / f"{sheet}.png"),
                                                 box, size)
        else:
            from PIL import Image
            im = kit_import.resample(kit_import.key_to_alpha(
                Image.open(KIT / f"{sheet}.png").crop(box)), size)
            px = im.load()
            _KIT_CACHE[key] = [[_source_id(px[x, y][:3]) if px[x, y][3] else 0
                                for x in range(size[0])]
                               for y in range(size[1])]
    return _KIT_CACHE[key]


# A TONE IS A FRACTION OF ITS RAMP, 0 dark to 1 light -- NOT A STEP COUNT.
# The painters used to say `Wm(9)`, nine steps up a sixteen-step ramp, and
# that number meant something only while the ramp was sixteen long. The
# ramp lengths are now the FITTER'S to choose (N_* above are generated), so
# a step count would silently point at a different tone every time the
# split moved. The literal denominators in the painters (`Wm(9 / 15)`) are
# the step counts each tone was picked on, frozen as fractions; they are not
# the ramp's length and do not track it.
TONES = None                    # the fitter: {family ix0: {t, ...}} drawn by hand


def _tone(ix0, n, t):
    if TONES is not None:
        TONES.setdefault(ix0, set()).add(round(t, 4))
    return ix0 + max(0, min(n - 1, round(t * (n - 1))))


def C(t):  return _tone(IX_COLD, N_COLD, t)
def Wm(t): return _tone(IX_WARM, N_WARM, t)
def Ml(t): return _tone(IX_MOLTEN, N_MOLTEN, t)
def Br(t): return _tone(IX_BRASS, N_BRASS, t)

SCREEN_H = 224                                  # the picture, in lines
DECK_PLATE = 16                                 # the footing plate's height:
                                                #   the deck band, in both rooms
PX = COLS * 8                                   # 256 px wide
PXH = ROWS * 8                                  # ...and 512 tall, the whole map


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
    """The 32-pixel band of a station's four SHAFT columns, as one index per x.

    Every row of those columns is this, which is the vertical-invariance
    contract discharged by construction rather than by care. The shape is the
    delivered guide-rail cross-section (vendor/art/forge_line/README.md): four
    fluted rails, mirrored about the centre, drawn as one row and asserted to
    be one row on import. Both stations take the same strip."""
    # THE DELIVERED CROSS-SECTION, NOT AN AVERAGE. `kit_cross_section` was
    # the best the sheets allowed -- a column MEAN of a lit strip, which kept
    # the flute spacing and lost every edge, and it was a third of the screen.
    # The strip below was drawn as one row repeated (asserted on import: every
    # row byte-identical, mirrored about the centre), which is the shape a
    # vertically displaced column needs and the one thing a continuous-tone
    # sheet could never supply. Both stations take it.
    art = art_to_indices(RAIL_ART)
    rows = {tuple(r) for r in art}
    if len(rows) != 1:
        raise SystemExit(f"{RAIL_ART}: {len(rows)} distinct rows -- a displaced "
                         f"column needs exactly one")
    row = list(rows.pop())
    if len(row) != SHAFT_COLS * 8 or row != row[::-1]:
        raise SystemExit(f"{RAIL_ART}: {len(row)} px wide / not mirrored")
    return row


def shaft_groups(st):
    """(first column of the group, its width in columns, its phase offset).

    THE TWIN IS TWO GROUPS AND THAT IS THE PER-COLUMN CLAIM MADE VISIBLE: one
    rod one column wide and one two columns wide, half a turn apart, inside a
    single station. Nothing in the table knows they belong to one machine —
    they are simply three adjacent words, and two of them agree."""
    return ((0, SHAFT_COLS, 0),)


def car_pixels(wcols):
    """The elevator car: a riveted box with a hole cut in it.

    THE HOLE IS THE WHOLE MECHANISM. BG1 is transparent inside WINDOW and
    opaque everywhere else on the car; the rider is an OBJ at priority 0, which
    in mode 4 loses to BG1's normal priority and beats BG2's. So he is drawn
    exactly where the glass is and nowhere else — the car occludes him without
    a window register, a mask, or a single per-scanline cycle.
    """
    w, h = wcols * 8, CAR_H
    buf = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            edge = x < 2 or x >= w - 2 or y < 3 or y >= h - 3
            band = y in (3, 4, h - 5, h - 4)
            # FLAT PANELS, no dither. A 1-index checker on a 32 px box reads
            # as noise at this size and fights the one thing the car exists to
            # frame; the shell gets its form from the bands and the rivets.
            buf[y][x] = Wm(1 / 15) if edge else (Br(6 / 11) if band else
                                            Wm((9 if 4 <= x < w - 4 else 6) / 15))
    for y in range(3, h - 3, 9):                 # rivet courses on the shell
        for x in range(3, w - 3, 6):
            buf[y][x] = Br(9 / 11)
    wx, wy, ww, wh = WINDOW
    for y in range(wy, wy + wh):                 # the frame around the glass...
        for x in range(wx, wx + ww):
            buf[y][x] = Br(4 / 11)
    for y in range(wy + 2, wy + wh - 2):         # ...and the glass itself: a
        for x in range(wx + 2, wx + ww - 2):     #   HOLE, so the rider shows
            buf[y][x] = 0
    return buf


def head_pixels(st, wcols):
    """The one thing in a shaft column that is NOT row-uniform, and therefore
    the one thing its displacement is seen to move.

    The DROP HAMMER takes the kit's ram at the size it was drawn — 32 px wide
    is exactly four columns, which is why the station is four columns and not
    three. The TWIN takes the kit's support post, twice, at 16 px: two rods of
    the same machine, half a turn apart, and the table does not know they are
    one machine — they are simply adjacent words, two of which agree."""
    if st == ELEVATOR:
        return car_pixels(wcols)
    w, h = wcols * 8, HEAD_ROWS * 8
    return [list(r) for r in kit("ram", (w, h))]


# --- the static columns: the pier, the legs, the deck and the channel -------
# NONE OF THIS OWES THE MECHANISM ANYTHING. These columns are never displaced
# (a leg's word holds BG1 at rest; a belt's word drives BG2 and leaves BG1 at
# its fallback), so the art is free: horizontal courses, bolt rows, hazard
# bands, a lit deck edge — every shape the shafts are forbidden.
def paint_pier(buf):
    for y in range(PXH):
        for x in range(8):
            course = (y % 24) < 2
            lit = x == 7
            v = 3 if course else 7 + ((x * 5 + (y // 24) * 3) % 5)
            buf[y][x] = Wm((13 if lit else v) / 15)
    # A FURNACE HATCH, lit from below. `y` here is a MAP row and the edge and
    # glow tests used to compare it with canvas-relative numbers (72, 74):
    # every row failed the edge test and the glow ran off the ramp's dark end,
    # so the hatch drew as a flat darkest-molten rectangle with no rim. Found
    # when the tone fractions were recorded: thirty-two "hand tones" below 0.
    for y in range(FLOOR * 8 + 72, FLOOR * 8 + 104):
        r = y - FLOOR * 8
        for x in range(1, 7):
            edge = r in (72, 73, 102, 103) or x in (1, 6)
            buf[y][x] = Br(9 / 11) if edge else Ml((6 + 20 * (1 - (r - 74) / 28)) / 31)


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
                    v = Wm((15 if 1 <= x < 7 else 3) / 15)
                elif y < top + 7:
                    v = Br((9 - (y - top - 4)) / 11)
                else:
                    v = Wm((2 if x in (0, 7) else 10 + ((x + st) % 3)) / 15)
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
            v = 1 if edge else (9 if inner else 5)
            buf[y][cx + x] = Br((2 + 5 * glow) / 11) if (glow > 0.45 and not edge) \
                else Wm(v / 15)
    for y in range(top, top + 12):                    # the capital
        for x in range(w):
            over = y < top + 3
            buf[y][cx + x] = Wm((0 if x in (0, w - 1) else (13 if over else 7)) / 15)
    for gy in range(top + 20, bot - 12, 32):          # bolt courses
        for y in (gy, gy + 1, gy + 2):
            for x in range(1, w - 1):
                buf[y][cx + x] = Br((3 + (5 if y == gy + 1 else 0)) / 11)
    if side == 0:                                     # one plaque a station
        py = top + 46 + st * 4
        for y in range(py, py + 10):
            for x in range(1, w - 1):
                rim = y in (py, py + 9) or x in (1, w - 2)
                buf[y][cx + x] = Br((10 if rim else 4 + ((x + y + st) % 3) * 2) / 11)
    for y in range(bot - 12, bot):                    # the splayed foot
        k = (y - (bot - 12)) // 4
        for x in range(w):
            buf[y][cx + x] = Wm((4 if x < k or x >= w - k else 8) / 15)


def paint_overhead(buf, cx, w):
    """The plant above the line, in the BELT columns' upper half.

    THOSE COLUMNS DRIVE BG2, so BG1 in them is at its fallback and STATIC —
    which makes the whole upper half of a conveyor bay free 8bpp art standing
    in front of a wall that never moves. It was empty in the first cut and the
    picture read as two machines in a blue room; the kit's six dark panel tiles
    fill it with ducting, valves and hatches for nothing per frame.
    """
    # THREE panels, NOT six, and none of them mirrored. Converted art dedupes
    # badly — every pixel of authored shading differs slightly from its
    # neighbour — so six variants plus a vertical flip filled the 256-tile page
    # exactly and left no headroom for anything else. Three, laid in a fixed
    # order, read as one run of plant rather than as six different things, and
    # cost a third of the tiles.
    PANELS = ("panel_duct", "panel_valve", "panel_hatch")
    top = GANTRY_ROW * 8 + 16
    for i, x0 in enumerate(range(cx, cx + w, 16)):
        tile = kit(PANELS[i % len(PANELS)], (16, 16))
        for y0 in (top, top + 16):
            for y in range(16):
                for x in range(16):
                    if x0 + x >= cx + w:
                        continue
                    v = tile[y][x]
                    if v:
                        buf[y0 + y][x0 + x] = v
    for x in range(cx, cx + w):                  # a shadow line under the plant
        for y in (top + 32, top + 33):
            buf[y][x] = Wm(1 / 15)


def paint_belt_front(buf, cx, w):
    """BG1 in a BELT column: STATIC, because that column's word drives BG2.
    So the conveyor's frame, its rollers and the deck under it are full-detail
    8bpp standing in front of a belt that runs. That is the layering doing the
    work, and it is why the picture is not four bays of empty air."""
    # THE KIT'S ROLLER FRAME, tiled, WITH ITS MIDDLE CUT OUT. The art is a
    # closed housing; drawn whole it would hide the belt running behind it,
    # which is the one thing in these columns that moves. So the frame's top
    # and bottom courses are kept and the band between them is dropped — the
    # rollers still read, and the tread shows through where the belt is.
    top = BELT_ROW * 8 - 8
    frame = kit("roller", (64, 32))
    for x in range(cx, cx + w):
        for y in range(32):
            if 10 <= y < 22:
                continue                         # ...the window the belt runs in
            v = frame[y][x % 64]
            if v:
                buf[top + y][x] = v


# WHICH COLUMNS HAVE A FLOOR, RECORDED BY THE PAINTER THAT LAYS ONE.
#
# This is the collision map and it is not a second description of the picture —
# it is the SAME call. A shaft column cannot have a deck in it, because a
# vertically displaced column must be identical row to row and a deck is a
# horizontal course; so the holes in the floor are not a design decision that
# could drift from the art, they are what the mechanism costs, and the set
# below is the painter's own record of where it did and did not lay one.
DECK_COLS = set()


_MELT = []


def melt_art():
    """The molten channel, 256 x (PXH - MELT_ROW*8), tiling on 64 px. It was a
    hash-noise formula over the molten ramp -- the brightest thing on screen
    and the least authored. The hall shows only its top rows (its camera
    bottoms out at SMIL_CAM_MAX); the melt, from MELT_CAM, shows all of it."""
    if not _MELT:
        art = art_to_indices(MELT_ART, shown=PXH - MELT_ROW * 8)
        if len(art) < PXH - MELT_ROW * 8 or len(art[0]) != PX:
            raise SystemExit(f"{MELT_ART}: {len(art[0])}x{len(art)}, need "
                             f"{PX} wide and at least {PXH - MELT_ROW * 8} tall")
        _MELT.append(art)
    return _MELT[0]


def paint_deck_and_melt(buf, cx, w):
    """The HALL's floor: the deck it stands on and the channel under it."""
    DECK_COLS.update(range(cx // 8, (cx + w) // 8))
    paint_floor(buf, cx, w, DECK_ROW * 8, MELT_ROW * 8, PXH)


def paint_floor(buf, cx, w, d0, m0, bottom):
    """The floor and the channel under it, at pixel rows d0 and m0.

    BOTH ROOMS PAINT THEIR FLOOR THROUGH HERE, and that is what makes the
    channel one channel rather than two that agree. The hall's deck is at
    DECK_ROW and the lobby's at LOBBY_FLOOR, and those two rows are chosen so
    that each lands on the SAME SCREEN LINE in its own room (asserted below
    the constants); the channel is then the same art rows at the same screen
    rows in both, because this function samples `melt_art()[y - m0]` and both
    callers pass a m0 sixteen pixels under their own floor.

    Static art in every column that gets it, so it carries the horizontal
    courses, the hazard skirt and the lit lip that no displaced column could
    hold.
    """
    # THE DECK IS THE KIT'S BASE FOOTING, tiled. It is 96 px of authored
    # riveted plate with arches under it; the rail lays it down repeating and
    # every column that gets it is static, so it keeps every horizontal course
    # the art was drawn with.
    deck = kit("footing", (96, 16))
    for x in range(cx, cx + w):
        for y in range(d0, min(m0, d0 + 16)):
            v = deck[y - d0][x % 96]
            if v:
                buf[y][x] = v
        for y in range(d0 + 16, m0):             # ...and its shadowed under-run
            buf[y][x] = Wm((3 + ((x // 4 + y) % 2)) / 15)
        # THE LIP, AND IT IS AS DEEP AS THE SURFACE RISES. A rippling column
        # is displaced DOWNWARD, so at its highest it shows RIPPLE_AMP rows
        # from above the channel at the top of its band — and if those rows
        # were floor plate the melt would look like it had swallowed the
        # decking. They are the crust the plate sits on instead, brightening
        # into the channel, which is also what the deck band shows where it
        # meets the melt.
        for y in range(m0 - RIPPLE_AMP, m0):
            buf[y][x] = Ml((24 + (y - m0 + RIPPLE_AMP) * 3 / RIPPLE_AMP) / 31)
        for y in range(m0, bottom):              # the channel: delivered art
            buf[y][x] = melt_art()[y - m0][x % PX]


def paint_shaft_house(buf, cx, w):
    """The UPPER screen: what a rider sees on the way up.

    The shaft columns need nothing — they are row-uniform over the whole 512 px
    map by construction, so the guide rails simply continue. Everything else up
    here is static art in columns the table holds at rest or does not drive at
    all: landing platforms with lit edges, a run of plant, and the hoist beams
    the cars hang from. It is the second screen the camera climbs into, and it
    exists to show that a per-column table and a vertical camera compose."""
    for lvl, ry in enumerate((3, 13, 22)):
        y0 = ry * 8
        for x in range(cx, cx + w):               # a landing platform
            for y in range(y0, y0 + 6):
                r = y - y0
                buf[y][x] = Wm((14 if r < 2 else (3 if r > 3 else 8)) / 15)
            for y in range(y0 + 6, y0 + 10):      # ...and its shadowed soffit
                buf[y][x] = Wm((2 + ((x // 5 + y) % 2)) / 15)
        for x in range(cx, cx + w, 24):           # hangers up to the beam above
            for k in range(3):
                for y in range(max(0, y0 - 18), y0):
                    if x + k < cx + w:
                        buf[y][x + k] = Wm((4 + (3 if k == 1 else 0)) / 15)


def paint_bg1():
    buf = [[0] * PX for _ in range(PXH)]
    paint_pier(buf)
    for st, (s, w) in enumerate(zip(STATION_AT, STATION_W)):
        prof = shaft_profile(st)
        sx = (s + 1) * 8
        for x in range(len(prof)):               # THE SHAFTS: one index per x,
            for y in range(PXH):                 #   every row identical
                buf[y][sx + x] = prof[x]
        for k0, wc, _ in shaft_groups(st):
            head = head_pixels(st, wc)
            # THE CAR REPLACES ITS BOX; THE RAM IS KEYED INTO IT. A ram is a
            # shape running inside a guide and the rails must show around it,
            # so a transparent pixel there means "leave the shaft". The CAR is
            # a box that fills its shaft, and its transparent pixels are the
            # GLASS — they have to CLEAR what is behind them, because what is
            # behind them is the guide rails and BG1 at normal priority beats
            # an OBJ at priority 0. Painted with the ram's rule, the rider was
            # occluded by the rails showing through his own window: visible as
            # a four-pixel sliver where the rails happened to be transparent.
            opaque_box = (st == ELEVATOR)
            # ...AND EACH STATION'S HEAD SITS AT ITS OWN ROW. A ram and a car
            # are the same shape and were pasted at one row until the deck
            # became a place to stand; what separates them is what each has to
            # MEET (see the CAP_ROW/CAR_ROW note above), so the paste asks
            # `head_row` rather than assuming. Splitting the constants without
            # splitting this put the car's art sixteen pixels from where the
            # rider was being staged against it — the port drew and the man in
            # it did not.
            row0 = head_row(st)
            for y in range(HEAD_ROWS * 8):
                for x in range(wc * 8):
                    v = head[y][x]
                    if v or opaque_box:
                        buf[row0 * 8 + y][sx + k0 * 8 + x] = v
        paint_upright(buf, s * 8, st, 0)                  # the near upright
        paint_upright(buf, (s + 1 + SHAFT_COLS) * 8, st, 1)   # ...and the far
        paint_crown(buf, s * 8, (2 + SHAFT_COLS) * 8, st)
        bx = (s + BELT_AT) * 8
        bw = (w - BELT_AT) * 8
        paint_overhead(buf, bx, bw)
        paint_belt_front(buf, bx, bw)
        paint_deck_and_melt(buf, s * 8, 8)
        paint_deck_and_melt(buf, (s + 1 + SHAFT_COLS) * 8, 8)
        paint_deck_and_melt(buf, bx, bw)
    paint_deck_and_melt(buf, 0, 8)
    # ---- the upper screen, in every column the table does not drive ---------
    for st, (sc, w) in enumerate(zip(STATION_AT, STATION_W)):
        paint_shaft_house(buf, (sc + BELT_AT) * 8, (w - BELT_AT) * 8)
    paint_shaft_house(buf, TAIL_AT * 8, (COLS - TAIL_AT) * 8)
    paint_overhead(buf, TAIL_AT * 8, (COLS - TAIL_AT) * 8)
    paint_belt_front(buf, TAIL_AT * 8, (COLS - TAIL_AT) * 8)
    paint_deck_and_melt(buf, TAIL_AT * 8, (COLS - TAIL_AT) * 8)
    return buf


# --------------------------------------------------------------------------
# THE LOBBY — the same mode, the same CHR page, a different room
# --------------------------------------------------------------------------
# A flat interior with two lift bays and a call button beside each: the scene
# the ride leaves from and comes back to. It costs almost nothing because it
# shares EVERYTHING except its tilemap — mode 4, the 8bpp CHR page, both
# palettes, the OBJ sheet. Two scenes, one art set, and what changes across the
# edge is which map BG1SC points at.
#
# THE DOORS ARE SPRITES, AND THE REASON IS THE RAIL'S OWN SUBJECT INVERTED.
# The obvious idea on a mode-4 rail is to make the leaves offset columns and
# slide them with a word. It cannot work, and the reason is the one fact this
# whole rail is built on: A DISPLACED COLUMN MOVES WHOLE. A door is a PARTIAL
# reveal — the leaf retracts while the wall above it and the floor below it
# hold still — and there is no word that displaces part of a column. The hall's
# machines work precisely because a ram FILLS its column.
#
# So the leaves are OBJ, sliding pixel-granular at priority 1 (mode 4 scores
# that 4, over BG1's normal 3), over a bay drawn dark in BG1. ONE leaf graphic
# serves both sides — the right-hand one sets the OAM H-flip bit — and the
# whole animation costs nothing but the OAM shadow that is already committed
# every frame.
LOBBY_FLOOR = 19              # the deck's map row -- and THE SAME SCREEN LINE
                              #   the hall's deck lands on, which is what
                              #   carries the channel across the lift's edge
assert LOBBY_FLOOR * 8 == FLOOR_Y, (
    f"the lobby's floor is at screen {LOBBY_FLOOR * 8} and the hall's at "
    f"{FLOOR_Y}: a rider stepping out of the lift would change height and the "
    f"channel under him would jump")
assert LOBBY_FLOOR * 8 + DECK_PLATE == CHANNEL_Y
assert PXH - MELT_ROW * 8 == 224 - CHANNEL_Y, (
    "the hall's channel must run from the deck to the map's last row: the "
    "camera rests at the bottom, so those are the same rows the lobby shows")
DOOR_W = 8                    # a bay is this wide in COLUMNS: two 32 px leaves
DOOR_ROWS = 8                 # ...and the opening is this tall, in rows: 64 px,
                              #   which is a 32 px figure with headroom over him
                              #   rather than a slot he exactly fills
DOOR_TRAVEL = 30              # how far a leaf slides to stand open, in pixels
DOOR_TOP = LOBBY_FLOOR - DOOR_ROWS
LEAF_BOX = 32                 # the leaf sprite, which is the OBJ box
LEAF_ROWS = DOOR_ROWS * 8 // LEAF_BOX   # ...so a side is this many cells STACKED

# A 64 px opening cannot be one sprite: OBSEL's large size in this rail's pair
# is 64x64 and a leaf is 32 wide, so the box that is tall enough is twice as
# wide as the bay. Two 32x32 cells stacked is the shape that fits — and it
# costs no CHR at all, because `leaf_pixels` is written on a period that
# DIVIDES 32, so the same graphic is its own continuation and the seam between
# the two cells is not visible.
assert DOOR_ROWS * 8 == LEAF_ROWS * LEAF_BOX, "the opening must be whole cells"


# --------------------------------------------------------------------------
# DELIVERED ART IS IMPORTED BY LOOKUP, WITH THE DRIFT MEASURED
# --------------------------------------------------------------------------
# Three assets now arrive authored to THIS palette (the lobby wall, the
# guide-rail cross-section, the molten channel). None needs a resample; each
# needs the same thing: nearest entry, a count of how many were exact, and a
# refusal if some colour is nowhere near -- which is what "authored against a
# different palette" looks like. They are all authored against a PUBLISHED
# SNAPSHOT, and the palette is refitted from time to time, so exact lookup
# would break every asset at every refit; nearest-entry does not, and the
# drift it reports says how far the snapshot has moved under the art.
ART_DRIFT = 28                 # counts a delivered colour may sit from an entry.
                               #   The channel was drawn against the pre-refit
                               #   MOLTEN ramp and its darkest crust tone moved
                               #   25 when the key bleed came out; the rest of
                               #   its colours sit within 17 and the wall's
                               #   within 9. Past this is a different palette.
ART_FIT = {}                   # name -> (exact, distinct, worst), for the summary


def is_key_hue(r, g, b):
    """On the KEY'S HUE AXIS: red and blue both up, green well down.

    The sheets are keyed on magenta and every asset's edge blends the key
    toward the art through values no key test can claim without eating real
    pixels; the sheet fit once spent eleven of ninety-six entries on that
    halo, and one of them -- the old darkest molten, (5,0,7) -- was then
    AUTHORED INTO the delivered channel as a crust tone. So a colour on this
    axis is not art whichever file it arrives in: the fitter drops it from
    the cloud, and `art_to_indices` imports it nearest and does not gate it,
    because no entry will ever be near it again and that is the point.

    Safe here for a reason particular to this art: steel is neutral to blue,
    molten runs red to white through orange, brass brown to gold, and NONE of
    them puts red and blue up together with green down.
    """
    return r > 48 and b > 48 and g < 0.60 * min(r, b)


def art_to_indices(name, drift=ART_DRIFT, shown=None):
    """A delivered PNG under the kit -> a 2-D list of BG1 CGRAM indices.

    `shown` is how many of its rows a room ever puts on screen; the drift
    gate covers THOSE. The palette is fitted to what is shown (see
    `tools/fit_mill_palette.py`), so a colour that exists only in rows no
    camera reaches has no entry near it by construction, and refusing the
    file for it would be refusing the fit. The whole file is still imported
    -- every row lands on its nearest entry -- and the summary reports the
    drift of the shown rows beside the file's."""
    from PIL import Image
    im = Image.open(KIT / name).convert("RGB")
    W, H = im.size
    shown = H if shown is None else shown
    rgbs = [((w & 31) << 3 | (w & 31) >> 2,
             ((w >> 5) & 31) << 3 | ((w >> 5) & 31) >> 2,
             ((w >> 10) & 31) << 3 | ((w >> 10) & 31) >> 2) for w in PAL_BG1]
    px = im.load()
    if SOURCE is not None:                       # the fitter: colours, not entries
        return [[_source_id(px[x, y]) for x in range(W)] for y in range(H)]
    cache, worst, exact, worst_all = {}, 0, 0, 0
    on_screen = {px[x, y] for y in range(shown) for x in range(W)}
    for c in {px[x, y] for y in range(H) for x in range(W)}:
        j = min(range(len(rgbs)),
                key=lambda i: (2 * (rgbs[i][0] - c[0]) ** 2
                               + 4 * (rgbs[i][1] - c[1]) ** 2
                               + (rgbs[i][2] - c[2]) ** 2))
        d = max(abs(rgbs[j][k] - c[k]) for k in range(3))
        cache[c] = BG1_IX0 + j
        if is_key_hue(*c):                   # the bleed: imported, not gated
            continue
        worst_all = max(worst_all, d)
        if c in on_screen:
            worst = max(worst, d)
            exact += (d == 0)
    if worst > drift:
        raise SystemExit(f"{name}: a shown colour is {worst} counts from the "
                         f"nearest BG1 entry -- this was authored against a "
                         f"different palette")
    ART_FIT[name] = (exact, len(on_screen), worst, shown, H, worst_all)
    return [[cache[px[x, y]] for x in range(W)] for y in range(H)]


# --------------------------------------------------------------------------
# THE LOBBY WALL IS IMPORTED, AND IT IS THE SOURCE OF TRUTH FOR THE BAYS
# --------------------------------------------------------------------------
# The wall above the deck is a delivered 256x176 asset authored to THIS
# palette (vendor/art/forge_line/README.md records the request it answers).
# Unlike the three sheets, it needs no resample and no nearest-entry search:
# every colour in it is already an exact CGRAM entry, so the import is a
# LOOKUP and a colour that is not in the palette stops the build by name.
# That is the whole difference between art fitted onto a palette and art
# authored to one.
#
# AND THE BAYS ARE FOUND, NOT DECLARED. `LOBBY_DOORS` used to say where the
# painter would cut two holes; now the art has them, so the code reads them
# back the way `paint_deck_and_melt` records `DECK_COLS` — one source, no
# second description to drift. They are NOT tile-aligned in the delivered
# art and they do not have to be: the leaves that cover them are sprites,
# positioned in pixels.
LOBBY_ART = KIT / "mode4_asset01_lobby_interior_wall.png"
RAIL_ART = "mode4_guide_rail_cross_section_32x8.png"
MELT_ART = "mode4_molten_metal_channel_256x88.png"
LOBBY_ART_H = 176              # the wall the asset covers; the floor is inside
                               #   it and the channel below that
LOBBY_ART_FIT = []             # (exact, distinct, worst drift), for the summary


def _lobby_art():
    """(index buffer 256 x LOBBY_FLOOR*8, [(x0, w), ...] for each bay found).

    THE ART IS SEATED, NOT ASSUMED. It was authored on its own 176 px canvas
    with its floor line at y=164 and a band reserved at the top — the shape a
    wall elevation takes when it expects a HUD over it, which this rail does
    not have. So the import finds the bays and SLIDES the whole wall until
    their bottom edge meets this lobby's deck. On the delivered asset that is
    12 px, and it lands the openings at exactly DOOR_TOP*8 — but the number is
    derived, so a redrawn wall with its floor somewhere else still seats.

    The band the slide opens at the top is filled with a coffered ceiling in
    the art's own two darkest tones. It is the one part of this wall we draw,
    and it is drawn because the delivered art left it blank.
    """
    from PIL import Image
    im = Image.open(LOBBY_ART).convert("RGB")
    if im.size != (PX, LOBBY_ART_H):
        raise SystemExit(f"lobby art is {im.size}, expected {(PX, LOBBY_ART_H)}")
    raw = art_to_indices(LOBBY_ART.name)
    if SOURCE is None:
        LOBBY_ART_FIT.append(ART_FIT[LOBBY_ART.name])

    def lum(i):                     # in BGR555 units: the +28 below is in them
        r, g, b = rgb555(i)
        return 2 * r + 4 * g + b

    # A BAY IS A TALL RUN OF COLUMNS WHOSE PIXELS ARE ALL THE DARKEST TONE.
    # The brief asked for flat dark recesses precisely so the sprites could
    # cover them, which makes "flat and dark" the thing to search for. The
    # reserved band at the top is the same colour across the full width, so a
    # bay is the run that does NOT reach row 0. Darkest by LUMINANCE, not the
    # lowest index: an index is a position in one ramp and the ramps are not
    # ordered against each other.
    dark = min({v for r in raw for v in r}, key=lum)
    def dark_runs(xs):
        """Contiguous row runs where every column in `xs` is the dark index."""
        col = [y for y in range(LOBBY_ART_H)
               if all(raw[y][x] == dark for x in xs)]
        out = []
        for y in col:
            if out and y == out[-1][1] + 1:
                out[-1][1] = y
            else:
                out.append([y, y])
        return [(a, b) for a, b in out if b > a]

    tall = [x for x in range(PX)
            if sum(1 for y in range(LOBBY_ART_H) if raw[y][x] == dark) >= 48]
    spans, run = [], None
    for x in tall + [None]:
        if run and x == run[1] + 1:
            run = (run[0], x)
            continue
        if run and run[1] - run[0] >= 20:
            spans.append((run[0], run[1] - run[0] + 1))
        run = (x, x) if x is not None else None
    if len(spans) != 2:
        raise SystemExit(f"lobby art: found {len(spans)} bays, expected 2")

    # The opening is the LONGEST dark run in those columns. The reserved band
    # at the top and the shadow line under the floor are dark across the whole
    # width too, so "the only dark run" is not true and the tallest one is.
    bottoms = set()
    for x0, w in spans:
        body = max(dark_runs(range(x0, x0 + w)), key=lambda r: r[1] - r[0])
        if body[1] - body[0] + 1 < 32:
            raise SystemExit(f"lobby art: the bay at x={x0} is only "
                             f"{body[1] - body[0] + 1} px tall")
        bottoms.add(body[1])
    if len(bottoms) != 1:
        raise SystemExit("lobby art: the two bays do not share a floor line")

    # SEAT IT ON BOTH AXES.
    #
    # Vertically: the bays' bottom edge meets this lobby's floor, and THE ART
    # RIDES UP TO MEET IT. The wall was authored on its own 176 px canvas with
    # a band reserved at the top — the shape a wall elevation takes when it
    # expects a HUD over it, which this rail does not have — and its floor
    # line at y=164. This lobby's floor is at LOBBY_FLOOR*8, twelve pixels
    # higher, because the twelve rows that buys at the bottom are where the
    # molten channel goes: the room is the ground floor at the foot of the
    # shaft and the channel is what is under it. So the slide is NEGATIVE and
    # what it drops off the top is exactly the reserved band, which was a
    # coffered ceiling this file drew and nobody needed. The number is still
    # derived, so a redrawn wall with its floor somewhere else still seats.
    #
    # Horizontally: THE BAYS MUST LAND ON THE TILE GRID. They arrive at x=44
    # and x=148, which are not multiples of 8, and a bay whose edge falls
    # mid-tile has no correct priority bit — mark that tile and the wall
    # notches the SHUT doors, leave it and a retracted leaf shows through 4 px
    # of pier. Neither is acceptable and no tilemap can say both, so the art is
    # rolled instead until the openings are whole tiles. The wall was authored
    # to tile horizontally (its two edge columns are an ordinary adjacency, at
    # the 71st percentile of this image's own column-to-column change), so the
    # roll wraps rather than padding, and the joint it moves inland is one the
    # picture already contained.
    fl = LOBBY_FLOOR * 8
    slide = fl - (bottoms.pop() + 1)
    if slide > 0:
        raise SystemExit(
            f"lobby art: the wall's bays end {slide} px above this lobby's "
            f"floor, so seating it would open a band at the top with nothing "
            f"authored in it")
    roll = -(spans[0][0] % 8)                    # ...left, to the nearest grid
    raw = [[row[(x - roll) % PX] for x in range(PX)] for row in raw]
    spans = [((x0 + roll) % PX, w) for x0, w in spans]
    for x0, w in spans:
        if x0 % 8 or w % 8:
            raise SystemExit(f"lobby art: bay at x={x0} w={w} is not whole "
                             f"tiles even after seating")
    buf = [[dark] * PX for _ in range(fl)]
    for y in range(fl):
        src = y - slide
        if 0 <= src < LOBBY_ART_H:
            buf[y][:] = raw[src]
    return buf, spans


_LOBBY_ART_CACHE = []


def lobby_art():
    if not _LOBBY_ART_CACHE:
        _LOBBY_ART_CACHE.append(_lobby_art())
    return _LOBBY_ART_CACHE[0]


# A LEAF RETRACTS INTO THE WALL, WHICH MEANS THE WALL HAS TO BEAT IT.
#
# The leaves are OBJ at priority 1, which mode 4 scores 4 (`RenderMode4`'s
# `spritePriorities[4] = {2,4,6,8}`), and BG1's NORMAL priority is 3 — so a
# leaf drew over every pixel of the wall, including the pier it is supposed to
# slide into. On screen the doors opened in FRONT of the building. A real lift
# retracts its leaves into a pocket and the door surround occludes them.
#
# BG1's HIGH priority is 7 (`RenderTilemap<0, 8, 3, 7>`), above the leaf's 4,
# so the fix is a tilemap bit rather than any change to how the leaves move:
# every wall tile a retracted leaf would cover gets bit 13 set and the leaf
# disappears behind it. The player is raised to OBJ priority 3 (score 8) to
# stay in front of that same wall — see MIL_LOBBY_ATTR.
#
# THE POCKETS ARE DERIVED FROM THE BAYS, and only columns lying ENTIRELY
# outside every bay are marked. The delivered art does not put the bays on the
# tile grid, so each opening has a 4-px sliver of wall sharing its edge tile;
# marking that tile would clip the leaf INSIDE the opening, which reads as a
# gap, while leaving it lets the leaf overlap the pier's edge by 4 px, which
# reads as the leaf being at the pier. The second is the better error.
TILE_HI = 0x2000              # bit 13 of a tilemap word: this tile is HIGH
                              #   priority (SnesPpu.cpp:1024). Not to be
                              #   confused with BIT_BG1 above, which is the
                              #   same bit in an OFFSET word and means
                              #   something else entirely.


def lobby_hi_cols():
    """Tile columns whose whole 8 px lies outside every bay."""
    bays = lobby_bays()
    return {c for c in range(COLS)
            if all(c * 8 + 8 <= x0 or c * 8 >= x0 + w for x0, w in bays)}


# THE PICTURE IS ONE MAP ROW BELOW THE SCANLINE THAT SHOWS IT. A BG row is
# fetched as `(realY + vScroll) >> 3` with realY the scanline (SnesPpu.cpp:186)
# and the first DISPLAYED scanline is 1, so at VSCROLL 0 screen row y shows map
# row y+1 — measured here: screen 175 draws map 176, the deck's first row.
# Rows computed in SCREEN space are therefore one short at the bottom, which
# left the leaves' last row over an unmarked deck tile and drew a one-pixel
# band of door across the pier. The conversion is written out rather than a
# bare +1 so the next reader does not have to rediscover which way it goes.
SCANLINE_LEAD = 1


def lobby_hi_rows():
    """The MAP rows a leaf covers, from the screen rows it occupies.

    A leaf's cells stack from the opening's top for the whole opening's
    height, so it spans screen rows [DOOR_TOP*8, LOBBY_FLOOR*8) — and the map
    rows drawn there are those plus the scanline lead.
    """
    top = DOOR_TOP * 8 + SCANLINE_LEAD
    bot = LOBBY_FLOOR * 8 - 1 + SCANLINE_LEAD
    return range(top // 8, bot // 8 + 1)


def lobby_bays():
    """[(x, width)] in PIXELS, read off the art."""
    return lobby_art()[1]


def paint_lobby():
    """BG1's lobby map: the delivered wall art above, the deck below, cut
    against the SAME tile set the hall uses — one CHR page, two rooms.

    THE BAYS ARE NOT DRAWN HERE. They are in the art, and `lobby_bays` reads
    them back out of it, so there is exactly one statement of where a lift
    opening is and the sprites that cover them cannot drift from the hole.

    THE FLOOR AND THE CHANNEL ARE THE HALL'S OWN, through `paint_floor` — the
    same footing plate and the same rows of the same delivered channel, at the
    same screen height. What is under this room is what is under that one.
    """
    buf = [[0] * PX for _ in range(PXH)]
    art, _ = lobby_art()
    fl = LOBBY_FLOOR * 8
    for y in range(fl):
        buf[y][:] = art[y]
    paint_floor(buf, 0, PX, fl, fl + DECK_PLATE, SCREEN_H)
    for y in range(SCREEN_H, PXH):               # ...and nothing below it: the
        for x in range(PX):                      #   lobby does not scroll, so
            buf[y][x] = art[0][0]                #   these rows are unreachable
    return buf


# The leaf's own OBJ palette: it is 4bpp like every sprite, and steel in the
# rider's eight knight colours would be wrong, so it takes OBJ palette 1.
LEAF_PAL = [(0, 0, 0), (3, 3, 4), (7, 7, 8), (11, 11, 12), (15, 15, 17),
            (19, 19, 21), (24, 18, 8), (29, 24, 14)]


def leaf_pixels():
    """One lift leaf, 32x32, in indices into LEAF_PAL. The right-hand leaf is
    this one H-FLIPPED by its OAM attribute bit, so the pair costs one
    graphic — and EVERY VERTICAL PERIOD HERE DIVIDES 32, so the same graphic
    stacked under itself continues without a seam and one cell covers a
    64 px opening twice over."""
    buf = [[0] * LEAF_BOX for _ in range(LEAF_BOX)]
    for y in range(LEAF_BOX):
        for x in range(LEAF_BOX):
            if x >= LEAF_BOX - 2:
                buf[y][x] = 7                    # the meeting edge, lit brass
            elif x < 2:
                buf[y][x] = 1                    # ...and the stile at the jamb
            else:
                # A panelled door, not a grid: the shading runs ACROSS the leaf
                # only, and the one horizontal datum is a single recessed line
                # on a period that divides 32 so the stack has no seam.
                panel = 3 <= (x % 16) < 13
                buf[y][x] = (2 if y % 16 == 0 else
                             4 if panel else 3)
    for x in range(3, LEAF_BOX - 3):             # the panel's lit top edge
        for y in range(1, LEAF_BOX, 16):
            if 3 <= (x % 16) < 13:
                buf[y][x] = 5
    for y in range(4, LEAF_BOX, 8):              # rivets down the stile
        buf[y][3] = 6
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
# THE RIDER — one OBJ, traced from the vendored camelot pack
# --------------------------------------------------------------------------
# `vendor/art/camelot/arthurPendragon_.png`, CC0 (analogStudios_ / Kevin's
# Mom's House), the same source and the same two idle cells `smelter` uses.
# Reused rather than authored because the kit ships no figure and this tree
# already has one whose provenance is traced in docs/92 §5.1.
#
# TWO CELLS, NOT ONE. He is standing in a lift, so the animation is a breath —
# and the pack's idle row gives it for 512 B. TICK: ok -- the two cells are
# indexed by the rail's PHASE, which the scaler already expressed against the
# declared tick. Nothing here counts hardware frames.
CAMELOT = ROOT / "vendor" / "art" / "camelot"
# The pack's own row map: idle [0], run [1,2]. Two idle cells and eight run
# cells — the rider stands in the lift and WALKS in the lobby, and the two
# scenes index the same sheet.
RIDER_CELLS = ([(0, 0), (0, 2)]
               + [(1, c) for c in range(4)] + [(2, c) for c in range(4)])
RIDER_IDLE0, RIDER_IDLE_N = 0, 2
RIDER_WALK0, RIDER_WALK_N = 2, 8
RIDER_BOX = 32                          # the pack's cell IS the OBJ box
FRAMES_PER_GROUP = 4                    # four 32x32 cells fill one 64-tile group
                                        # TICK: ok -- OBJ NAME-TABLE GEOMETRY,
                                        #   not a rate: a 32x32 cell is 4x4
                                        #   tiles and a group is 64, so this 4
                                        #   is fixed by the PPU's name table
                                        #   and cannot vary with region
RIDER_SLOTS = 16                        # ...four groups: ten rider cells, then
LEAF_SLOT = 12                          #   the lift leaf at the last group


def _rider_cells():
    from PIL import Image
    sheet = Image.open(CAMELOT / "arthurPendragon_.png").convert("RGBA")
    out = []
    for row, col in RIDER_CELLS:
        # NO CROP AND NO RE-CENTRING: the pack's cell already measures exactly
        # the OBJ box, and re-centring a frame that is already exact pushes the
        # art down and moves the feet off the number everything else is written
        # against (vendor/art/camelot/README.md).
        c = sheet.crop((col * RIDER_BOX, row * RIDER_BOX,
                        (col + 1) * RIDER_BOX, (row + 1) * RIDER_BOX))
        assert c.size == (RIDER_BOX, RIDER_BOX)
        out.append(c)
    return out


def rider_head():
    """The HIGHEST inked row any pose reaches — the other end of `rider_feet`.

    The poses disagree here (11, 12 or 13 depending on the stride) where they
    agree exactly on the feet, so this is the minimum: the bound has to hold
    for whichever cell is on screen.
    """
    return min(min(y for y in range(RIDER_BOX) for x in range(RIDER_BOX)
                   if c.load()[x, y][3] > 127) for c in _rider_cells())


def rider_ink_x():
    """(leftmost, rightmost) inked column across every pose -- the same idea
    as rider_feet on the other axis, and for the same reason: the box is not
    the figure, so 'centred in the glass' has to be computed from the ink."""
    l, r = RIDER_BOX, 0
    for c in _rider_cells():
        px = c.load()
        xs = [x for y in range(RIDER_BOX) for x in range(RIDER_BOX) if px[x, y][3] > 127]
        l, r = min(l, min(xs)), max(r, max(xs))
    return l, r


def rider_feet():
    """The lowest INKED row in the rider's cells, which is not the box's floor.

    THE BOX IS NOT THE FIGURE. His cell is 32 px and the art stops at row 27 in
    all ten poses — four blank rows underneath — so a stand height computed as
    `floor - RIDER_BOX` leaves him hanging those four pixels above the deck.
    Measured on the shipped ROM: his ink ended at screen row 171 with the
    deck's top edge at 175. Emitted rather than written down, so a redrawn
    sprite re-seats him instead of quietly floating.
    """
    feet = set()
    for c in _rider_cells():
        px = c.load()
        feet.add(max(y for y in range(RIDER_BOX) for x in range(RIDER_BOX)
                     if px[x, y][3] > 127))
    if len(feet) != 1:
        raise SystemExit(f"rider poses disagree on where his feet are: {feet}")
    return feet.pop()


def rider_sheet():
    """(CHR blob, rider palette, leaf palette).

    ONE palette over every rider cell, from the union of their opaque colours —
    the pack measures Arthur at 8, so this is a lossless conversion and not a
    quantisation. The LIFT LEAF rides in the same blob at LEAF_SLOT, on its own
    OBJ palette: one upload, one ROM claim, and the two never share a colour.
    """
    cells = _rider_cells()
    allc = set()
    for c in cells:
        px = c.load()
        for y in range(RIDER_BOX):
            for x in range(RIDER_BOX):
                r, g, b, a = px[x, y]
                if a > 127:
                    allc.add((r >> 3, g >> 3, b >> 3))
    assert len(allc) <= 15, f"rider needs {len(allc)} colours, 4bpp has 15"
    order = sorted(allc, key=lambda c: 2 * c[0] + 5 * c[1] + c[2])
    c2i = {c: i + 1 for i, c in enumerate(order)}
    words = [rgb(0, 0, 0)] + [rgb(*c) for c in order]
    words += [rgb(0, 0, 0)] * (16 - len(words))

    assert len(cells) <= RIDER_SLOTS
    def put(slot, get):
        for ty in range(4):
            for tx in range(4):
                group, within = divmod(slot, FRAMES_PER_GROUP)
                ti = group * 64 + within * 4 + ty * 16 + tx
                for y in range(8):
                    rowpx = [get(tx * 8 + x, ty * 8 + y) for x in range(8)]
                    for pl in range(2):
                        lo = hi = 0
                        for x in range(8):
                            v = rowpx[x] >> (pl * 2)
                            lo |= (v & 1) << (7 - x)
                            hi |= ((v >> 1) & 1) << (7 - x)
                        blob[ti * 32 + pl * 16 + y * 2] = lo
                        blob[ti * 32 + pl * 16 + y * 2 + 1] = hi

    blob = bytearray(RIDER_SLOTS * 16 * 32)      # 16 tiles a 32x32 cell
    for slot, cell in enumerate(cells):
        px = cell.load()
        def get(x, y, px=px):
            r, g, b, a = px[x, y]
            return c2i[(r >> 3, g >> 3, b >> 3)] if a > 127 else 0
        put(slot, get)

    leaf = leaf_pixels()
    put(LEAF_SLOT, lambda x, y: leaf[y][x])
    lpal = [rgb(*c) for c in LEAF_PAL] + [rgb(0, 0, 0)] * (16 - len(LEAF_PAL))
    return bytes(blob), words, lpal


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
def cut(buf, tiles=None, index=None):
    """A painted picture -> a tilemap over a SHARED tile set.

    Passing the accumulators in is what lets the hall and the lobby cut against
    ONE CHR page: whatever the second room has in common with the first — every
    course of wall, every deck row — costs it nothing. Two scenes, one page,
    and BG12NBA never changes across the edge.
    """
    tiles = [] if tiles is None else tiles
    index = {} if index is None else index
    tmap = []
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
    for st, s in enumerate(STATION_AT):
        head = range(head_row(st) * 8, head_row(st) * 8 + HEAD_ROWS * 8)
        for x in range((s + 1) * 8, (s + 1 + SHAFT_COLS) * 8):
            seen = {buf[y][x] for y in range(PXH) if y not in head}
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
    """The tail run past the last station has no station of its own, so it
    takes the last one's direction: it is the same line continuing off the
    right-hand edge, and a tail running the other way would read as a second
    machine nobody can see."""
    st = station_of(col)
    if st is None:
        st = len(STATION_AT) - 1
    return (BELT_DIR[st % len(BELT_DIR)] * BELT_STEP * phase) & 0x3FF


def column_word(col, phase):
    """The word for SCREEN column `col`. Where it is STORED is row_table's
    business — that is the one place the lead is applied."""
    k = kind(col)
    if k == "pier":
        return 0                                 # unreachable, or at rest
    if k == "shaft":
        return BIT_BG1 | BIT_VSEL | (piston_v(col, phase) & V_MASK)
    # AN UPRIGHT TAKES THE BELT'S WORD, and that is deliberate rather than a
    # fall-through nobody noticed. The obvious reading is that a pillar should
    # hold BG1 at rest — but its BG1 art does not move either way, because the
    # word drives BG2, and what the choice actually decides is what happens
    # BEHIND the pillar. Driving BG2 runs the tread on unbroken past it; the
    # alternative leaves those columns on BG2HOFS and puts a visible step in
    # the belt at every upright in the hall.
    #
    # (There was a dead `"leg"` branch here for the other choice until
    # 2026-08-30, matching a name `kind` has never returned. It was never
    # reached, so the rail has always behaved this way — the branch was
    # documentation of an intention the code did not carry out.)
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


def _lead_row(word_of):
    """One 32-word row with THE LEAD APPLIED: index j holds the word for
    SCREEN COLUMN j + LEAD, because that is the column the PPU will hand it
    to. Every row the rail emits goes through here and nowhere else."""
    out = bytearray()
    for j in range(COLS):
        w = word_of(j + LEAD) if j + LEAD < COLS else 0
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


def row_table():
    """One row per phase, then the flat control."""
    return (b"".join(_lead_row(lambda c, p=p: column_word(c, p))
                     for p in range(PHASES))
            + _lead_row(flat_word))


# --------------------------------------------------------------------------
# THE CHANNEL RIPPLES, AND IT IS THE FLOOR OF BOTH ROOMS
# --------------------------------------------------------------------------
# Every room shows the same molten channel at the same screen rows, and the
# rows above it are a different picture in each. So each room reads the offset
# table in BANDS: the PPU fetches the row BG3VOFS names (rowOffset =
# VScroll >> 3, SnesPpu.cpp:257-276), and an HDMA channel rewriting that port
# at each band's first line hands every band of the picture its own 32 words.
#
#   the LOBBY   the wall and the doors  -> a row with NO enable bit: nothing
#                                          in the room above the floor moves
#               the channel             -> the RIPPLE row
#
#   the HALL    the machines and the car -> the running row, as ever
#               the deck                 -> the same zero row
#               the channel              -> the RIPPLE row
#
# ...and the hall's band edges MOVE, because its deck and channel are at fixed
# world rows and the camera climbs: the channel band shrinks to nothing as the
# lift rises, which is the per-scanline claim visible as motion rather than as
# a static split.
#
# THE RIPPLE DISPLACES DOWNWARD ONLY. A vertical word replaces the layer's
# scroll (vScroll = word & $3FF), so a column pushed UP by k samples k rows
# past the map's bottom edge, which wrap to its TOP -- a room's ceiling at the
# foot of its own channel. Pushed DOWN by k it samples k rows of the deck's
# lip above the channel instead, which reads as the surface lifting under the
# floor.
RIPPLE_PHASES = 32            # a full wave, in table rows -- and in PHASES:
                              #   the row is `phase & (RIPPLE_PHASES - 1)`, so
                              #   the surface completes a wave four times in
                              #   the machines' own cycle.
                              #
                              #   IT WAS A ROW PER FOUR PHASES, and at the
                              #   rail's 0.375 phases a frame that is 341
                              #   frames a wave: measured over twelve frames,
                              #   not one pixel of the picture moved. A demo
                              #   nobody can see the mechanism in is not a
                              #   demo, so the surface now swells in about 85
                              #   frames and the columns step visibly against
                              #   each other
RIPPLE_AMP = 6                # px, the surface's rise, 0..AMP -- and the lip
                              #   above the channel is drawn this deep, so a
                              #   fully risen column shows lit crust and never
                              #   the floor plate above it
RIPPLE_WAVES = 2              # across the 32 columns
assert PHASES % RIPPLE_PHASES == 0
BAND_MAX = 127                # the longest hold ONE HDMA entry can carry: a
                              #   non-repeat count byte is 7 bits, so a band
                              #   deeper than this is written as two entries


def ripple_k(col, phase):
    import math
    t = (phase % RIPPLE_PHASES) / RIPPLE_PHASES
    x = col / COLS
    return int(round(RIPPLE_AMP * (0.5 + 0.5 * math.sin(
        2 * math.pi * (RIPPLE_WAVES * x + t)))))


def ripple_word(col, phase):
    if kind(col) == "pier":
        return 0
    return BIT_BG1 | BIT_VSEL | ((-ripple_k(col, phase)) & V_MASK)


def ripple_flat_word(col):
    """The ripple's own control: every enable and axis bit still set, the
    surface at rest -- flat_word's rule on the melt's row."""
    if kind(col) == "pier":
        return 0
    return BIT_BG1 | BIT_VSEL | 0


def ripple_table():
    """RIPPLE_PHASES rows, then the flat control, at the hall row's stride."""
    return (b"".join(_lead_row(lambda c, p=p: ripple_word(c, p))
                     for p in range(RIPPLE_PHASES))
            + _lead_row(ripple_flat_word))


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------
def main():
    buf = paint_bg1()
    assert_shaft_invariance(buf)
    shared, ix = [], {}
    tiles1, map1 = cut(buf, shared, ix)
    lobby_tiles, map_lobby = cut(paint_lobby(), shared, ix)
    assert lobby_tiles is tiles1

    assert len(tiles1) <= CHR1_TILES, (
        f"BG1 needs {len(tiles1)} tiles, the page holds {CHR1_TILES}")
    chr1 = b"".join(encode_8bpp(t, f"bg1 tile {i}") for i, t in enumerate(tiles1))
    chr1 += bytes(64 * (CHR1_TILES - len(tiles1)))

    # BG2: one tile per MAP ROW (the H-invariance contract), plus the tread
    # phases, which are the one thing along a row that may differ.
    # ONE TILE PER MAP ROW — but DEDUPED. Most of a 64-row wall is the same
    # flat row, and a page with 64 copies of it in was 74 tiles for a 64-tile
    # budget. The map keeps a per-row index into the deduped set, which is the
    # same shape the BG1 cut uses.
    wall_ix, tiles2 = [], []
    seen = {}
    for r in range(ROWS):
        t = wall_row(r)
        k = tuple(tuple(row) for row in t)
        if k not in seen:
            seen[k] = len(tiles2)
            tiles2.append(t)
        wall_ix.append(seen[k])
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
                    t, g = wall_ix[r], BG2_G_WALL
                w = t | (g << 10)
                out += bytes((w & 0xFF, w >> 8))
        return bytes(out)

    (OUT / "mil_chr1.bin").write_bytes(chr1)
    (OUT / "mil_chr2.bin").write_bytes(chr2)
    def mlobby():
        hi_c, hi_r = lobby_hi_cols(), set(lobby_hi_rows())
        out = bytearray()
        for r in range(ROWS):
            for c in range(COLS):
                t = map_lobby[r][c] if r < len(map_lobby) else 0
                if r in hi_r and c in hi_c:
                    t |= TILE_HI            # ...the pocket a leaf retracts into
                out += bytes((t & 0xFF, t >> 8))
        return bytes(out)

    (OUT / "mil_map1.bin").write_bytes(m1())
    (OUT / "mil_lobby.bin").write_bytes(mlobby())

    (OUT / "mil_map2.bin").write_bytes(m2())
    # ONE PALETTE BLOB, TWO GROUPS, and the offset is emitted beside it: two
    # claims are two blobs the packer orders by SIZE, and an uploader reaching
    # the second by a distance from the first reads a sign it does not choose.
    (OUT / "mil_pal.bin").write_bytes(pal_bytes(PAL_BG1) + pal_bytes(PAL_BG2))
    (OUT / "mil_row.bin").write_bytes(row_table())
    (OUT / "mil_ripple.bin").write_bytes(ripple_table())
    rchr, rpal, lpal = rider_sheet()
    (OUT / "mil_obj.bin").write_bytes(rchr)
    (OUT / "mil_obj_pal.bin").write_bytes(pal_bytes(rpal) + pal_bytes(lpal))

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
SMIL_STATION_A    = {STATION_AT[0]}      ; each station's first SCREEN column:
SMIL_STATION_B    = {STATION_AT[1]}     ;   the upright, then SHAFT_COLS shafts
SMIL_BELT_AT      = {BELT_AT}
SMIL_SHAFT_COLS   = {SHAFT_COLS}
SMIL_WORLD_H      = {WORLD_H}    ; the world is two screens tall...
SMIL_CAM_MAX      = {CAM_MAX}    ; ...so the camera climbs this far
SMIL_FLOOR        = {FLOOR}     ; the forge floor's first map row
SMIL_CAP_ROW      = {CAP_ROW}     ; the ram's map row
SMIL_DECK_ROW     = {DECK_ROW}     ; the deck's map row...
SMIL_STAND_Y      = {STAND_Y}    ; ...and its top, where a figure's feet go
SMIL_LIFT_COL     = {STATION_AT[ELEVATOR] + 1}     ; the lift's first SCREEN column, and the
                              ;   first of the four the car bridges when it is
                              ;   down. Same number as SMIL_CAR_COL, derived
                              ;   from the station rather than from the car

; THE FLOOR, ONE BIT A SCREEN COLUMN, RECORDED BY THE PAINTER THAT LAID IT.
; Not a second description of the picture — the same call. A shaft column is
; displaced vertically so it must be identical row to row, and a deck is a
; horizontal course; the four columns of each station's shaft therefore cannot
; have one, and the holes in this map are what the mechanism costs rather than
; a level design that could drift from the art.
;
;   {"".join("#" if c in DECK_COLS else "." for c in range(COLS))}
;   {"".join(str(c % 10) for c in range(COLS))}
;
; The lift's own four columns are the second hole, and they are the reason
; this map is not the whole answer: while the car is DOWN they are ground, and
; while it is anywhere else they are not. That half is not expressible here and
; is read from the live offset word — see mil_col.asm.
SMIL_DECK_LO      = ${sum(1 << c for c in DECK_COLS if c < 16):04X}     ; screen columns 0..15, bit c = column c
SMIL_DECK_HI      = ${sum(1 << (c - 16) for c in DECK_COLS if c >= 16):04X}     ; ...and 16..31
SMIL_ELEVATOR     = {ELEVATOR}      ; ...which station's shaft carries the car

; THE FLOOR BOTH ROOMS SHARE, and the bands that put the channel under it.
SMIL_SCREEN_H     = {SCREEN_H}    ; the picture, in lines
SMIL_FLOOR_Y      = {FLOOR_Y}    ; the deck's SCREEN row -- in the lobby always,
                           ;   in the hall at rest. The rooms agree on it
SMIL_CHANNEL_Y    = {CHANNEL_Y}    ; ...and the channel's, likewise
SMIL_MELT_ROW     = {MELT_ROW}     ; the channel's MAP row, for the hall's band
                           ;   edges, which move with its camera
SMIL_BAND_MAX     = {BAND_MAX}    ; the longest hold one HDMA entry carries
SMIL_RIPPLE_PHASES = {RIPPLE_PHASES}    ; ripple rows in mil_ripple.bin, then a flat one
SMIL_RIPPLE_MASK  = {RIPPLE_PHASES - 1}     ; phase AND this = the ripple row
SMIL_RIPPLE_FLAT  = {RIPPLE_PHASES}    ; ...and the control row's index
SMIL_RIPPLE_AMP   = {RIPPLE_AMP}      ; the surface's rise, px, downward
SMIL_CAR_COL      = {STATION_AT[ELEVATOR] + 1}     ; its first SCREEN column
SMIL_CAR_ROW      = {CAR_ROW}     ; the car's map row
SMIL_CAR_H        = {CAR_H}     ; ...and its height in pixels
SMIL_WIN_X        = {WINDOW[0]}      ; the glass, inside the car
SMIL_WIN_Y        = {WINDOW[1]}
SMIL_WIN_W        = {WINDOW[2]}
SMIL_WIN_H        = {WINDOW[3]}
SMIL_RIDER_BOX    = {RIDER_BOX}     ; the OBJ box: OBSEL's 32x32 size pair
SMIL_RIDER_INK_L  = {rider_ink_x()[0]}      ; leftmost / rightmost column his ART reaches
SMIL_RIDER_INK_R  = {rider_ink_x()[1]}     ;   in the box, across every pose
SMIL_RIDER_HEAD   = {rider_head()}     ; the highest row his ART reaches in the box
SMIL_RIDER_FEET   = {rider_feet()}     ; ...and the lowest row his ART reaches
                                ;   inside it. The two differ by four blank
                                ;   rows, which is exactly how far he floated.
SMIL_SCANLINE_LEAD = {SCANLINE_LEAD}      ; screen row y draws MAP row y+1
                                ;   (SnesPpu.cpp:186, first displayed
                                ;   scanline is 1) — so a figure standing on
                                ;   a map row is placed against y-1
SMIL_RIDER_SLOTS  = {RIDER_SLOTS}      ; ...one whole 64-tile grid group
SMIL_RIDER_SLOT_TILES = 4      ; a 32x32 cell is 4 tiles wide in the name table
SMIL_RIDER_IDLE0  = {RIDER_IDLE0}
SMIL_RIDER_IDLE_N = {RIDER_IDLE_N}
SMIL_RIDER_WALK0  = {RIDER_WALK0}
SMIL_RIDER_WALK_N = {RIDER_WALK_N}
; TICK: ok -- a count of CELLS IN A SHEET, not of frames on a clock. Which cell
;   shows is chosen by ES_MIL_STEP (pixels walked) or by ES_MIL_PHASE, which
;   TS_STEP advances at the region's own rate — so the sheet's length is a
;   property of the art and is already region-correct.
SMIL_RIDER_FRAMES = {len(RIDER_CELLS)}
SMIL_LEAF_SLOT    = {LEAF_SLOT}     ; the lift leaf, in the same OBJ blob
SMIL_LEAF_TILE    = {(LEAF_SLOT // 4) * 64 + (LEAF_SLOT % 4) * 4}    ; ...and its tile index in the name table
SMIL_LEAF_BOX     = {LEAF_BOX}
SMIL_LEAF_ROWS    = {LEAF_ROWS}      ; ...stacked this many deep to fill the opening

; --- the lobby ------------------------------------------------------------
SMIL_LOBBY_FLOOR  = {LOBBY_FLOOR}     ; the deck's map row
SMIL_DOOR_AX      = {lobby_bays()[0][0]}     ; the two lift bays' left edge, in PIXELS,
SMIL_DOOR_BX      = {lobby_bays()[1][0]}    ;   READ OFF THE WALL ART (not tile-aligned,
                                ;   and it does not need to be: the leaves
                                ;   that cover them are sprites)
SMIL_DOOR_W       = {DOOR_W}      ; a bay, in columns
SMIL_DOOR_ROWS    = {DOOR_ROWS}
SMIL_DOOR_TOP     = {DOOR_TOP}     ; the opening's top map row
SMIL_DOOR_TRAVEL  = {DOOR_TRAVEL}     ; a leaf's slide, in pixels
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
    print(f"  mill: the floor is screen row {FLOOR_Y} in both rooms and the "
          f"channel {224 - CHANNEL_Y} lines under it; ripple "
          f"{RIPPLE_PHASES}+1 rows x {ROW_BYTES} B, amplitude {RIPPLE_AMP} px")
    print(f"  mill: chr1 {len(chr1)} B ({len(tiles1)}/{CHR1_TILES} x 8bpp), "
          f"chr2 {len(chr2)} B ({len(tiles2)}/{CHR2_TILES} x 2bpp), "
          f"pal {2 * (len(PAL_BG1) + len(PAL_BG2))} B "
          f"({len(PAL_BG1)} BG1 + {len(PAL_BG2)} BG2), "
          f"row table {PHASES}+1 x {ROW_BYTES} B, "
          f"rider {len(rchr)} B ({len(RIDER_CELLS)} cells)")
    for name, (e, n, w, shown, h, w_all) in sorted(ART_FIT.items()):
        rows = "" if shown == h else (f" over the {shown} rows shown of {h}"
                                      f" (whole file {w_all})")
        print(f"  mill: {name}: {e}/{n} colours exact, worst drift {w}{rows} of "
              f"{ART_DRIFT} allowed")
    print(f"  mill: lobby bays read at {[b[0] for b in lobby_bays()]} px")


if __name__ == "__main__":
    main()
