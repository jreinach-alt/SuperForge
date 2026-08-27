#!/usr/bin/env python3
"""Assets for the `heathaze` rail — a desert road, and the warp table that
bends it.

TWO KINDS OF OUTPUT, and the second is the point of the rail.

  the WORLD    BG1 tile art: a sky gradient, a mesa ridge, a hot horizon
               strip, and a desert floor with a road receding to it. Ordinary
               4bpp tiles, palette group 0.

  the WARP     `hz_warp.bin` — 32 complete phases of a per-scanline BG1VOFS
               displacement, each 256 B, ready for an HDMA channel to read
               straight out of ROM.

               VERTICAL, and that is the whole character of the effect. An
               inferior mirage comes from a VERTICAL refractive-index
               gradient — hot thin air at the ground, cooler denser air above
               — and rays bend along the gradient, which is why you see an
               inverted patch of sky below the horizon and read it as water.
               Horizontal wobble is the secondary term, from turbulent cells.
               A per-scanline HOFS slides each row sideways and every source
               row still appears exactly once; a per-scanline VOFS makes
               scanline N show source row N + d(N), so rows are DUPLICATED
               AND SKIPPED and the picture compresses and stretches. That
               squashing is the boiling, and a horizontal offset cannot
               produce it at all.

WHY THE WARP IS A TABLE AND NOT ARTWORK. The obvious way to draw heat haze is
to draw it: author a "warped" copy of every affected tile and animate between
them. That doubles the tile budget, warps only what was pre-drawn, and buys a
distortion that cannot follow the art it distorts. The SNES already bends a
whole layer for free — a different BG1HOFS per scanline, delivered by HDMA —
so what this file draws is the DISPLACEMENT, once, in every phase it will ever
need.

WHY 32 RESIDENT PHASES RATHER THAN A REBUILD. platformer_bg prices a
per-scanline table fill at ~16 cycles an entry (platformer_bg.asm:386), which
over this band is ~1,700 CPU cycles a frame out of ~28-37k. Holding every
phase in ROM instead costs 8 KB of the one budget with room to spare and
reduces the per-frame work to choosing which phase the channel reads. That is
water's surf pattern (water/feature.toml, "the phases are all in ROM already,
and what moves is which 512 of them the slots are showing"), and the stride is
256 so choosing a phase is a single 8-bit write to the channel's A1T high
byte.

THE RAMP IS BAKED IN, WHICH IS WHY THE PHASES SCROLL WITHOUT DRAGGING IT.
Amplitude is a function of SCREEN y — zero at the horizon, widest at the hot
ground nearest the viewer, which is the sheet's "strongest distortion close to
the source". Phase is a function of the TABLE index. Because each phase blob
carries its own correctly-ramped column, advancing the index scrolls the wave
UPWARD through a ramp that stays pinned to the screen. Heat rises, and it
costs nothing.
"""
import pathlib
import sys
import math

# --- BGR555 ----------------------------------------------------------------
# The SNES word is B<<10 | G<<5 | R, five bits per channel.


def bgr(r, g, b):
    assert all(0 <= c <= 31 for c in (r, g, b)), f"channel out of range: {r},{g},{b}"
    return (b << 10) | (g << 5) | r


# --- BG1 palette, group 0 (CGRAM words 0..15) ------------------------------
# Word 0 is the 4bpp transparent slot AND the hardware backdrop at once, so
# this feature claims it rather than composing `backdrop` — lake_bg records
# the same fold for the same reason. It is the sky's TOP step, which is what
# lets a four-step gradient fit in three sky entries.
#
# The ramp is deliberately WARM and deliberately WIDE. Warm because the
# subject is heat; wide because stage 2 half-adds a shimmer layer onto these
# colours, and a half-add halves CONTRAST too — a palette packed into a narrow
# band would come back from the blender as a wash.
SKY_TOP   = (8, 13, 27)       # zenith. ALSO the backdrop, by hardware contract
SKY_HI    = (14, 18, 29)
SKY_MID   = (21, 21, 28)
SKY_LOW   = (28, 25, 26)      # bleached, just above the ridge
MESA_DK   = (13, 8, 10)       # the far ridge, a flat silhouette at distance
MESA_LIT  = (20, 12, 11)      # its base, where the light comes back up
HAZE_LINE = (31, 28, 23)      # the hot strip AT the horizon
SAND_DK   = (18, 12, 8)       # ground in shadow, and rock
SAND      = (26, 19, 11)      # open desert floor
SAND_LIT  = (31, 26, 17)      # its glare
ROAD_DK   = (12, 10, 9)       # worn asphalt, warm not blue
ROAD      = (17, 15, 14)      # ...and its sunlit surface
ROAD_LINE = (31, 28, 17)      # the centre dashes
ROCK      = (21, 17, 15)      # lit faces of rock and scree
CACTUS_DK = (4, 11, 6)
CACTUS    = (10, 20, 10)

HZ_PAL = [bgr(*SKY_TOP), bgr(*SKY_HI), bgr(*SKY_MID), bgr(*SKY_LOW),
          bgr(*MESA_DK), bgr(*MESA_LIT), bgr(*HAZE_LINE), bgr(*SAND_DK),
          bgr(*SAND), bgr(*SAND_LIT), bgr(*ROAD_DK), bgr(*ROAD),
          bgr(*ROAD_LINE), bgr(*ROCK), bgr(*CACTUS_DK), bgr(*CACTUS)]

(I_SKY_TOP, I_SKY_HI, I_SKY_MID, I_SKY_LOW, I_MESA_DK, I_MESA_LIT, I_HAZE,
 I_SAND_DK, I_SAND, I_SAND_LIT, I_ROAD_DK, I_ROAD, I_ROAD_LINE, I_ROCK,
 I_CACTUS_DK, I_CACTUS) = range(16)

LEGEND = {"0": I_SKY_TOP, "1": I_SKY_HI, "2": I_SKY_MID, "3": I_SKY_LOW,
          "m": I_MESA_DK, "M": I_MESA_LIT, "h": I_HAZE, "d": I_SAND_DK,
          "n": I_SAND, "N": I_SAND_LIT, "a": I_ROAD_DK, "A": I_ROAD,
          "L": I_ROAD_LINE, "R": I_ROCK, "c": I_CACTUS_DK, "C": I_CACTUS}


def pic(*rows):
    """Eight 8-character rows through LEGEND -> 8x8 indices."""
    assert len(rows) == 8, f"expected 8 rows, got {len(rows)}"
    return [[LEGEND[ch] for ch in row] for row in rows]


def flat(index):
    return [[index] * 8 for _ in range(8)]


def dither(a, b, weight=2):
    """A Bayer-ordered mix of two indices.

    `weight` is how many of the four 2x2 slots take `b`, so 1/2/3 give a
    three-step blend between any pair — which is what turns a four-colour sky
    into a gradient with no visible banding edge.
    """
    order = ((0, 3), (2, 1))            # the classic 2x2 Bayer threshold
    return [[b if order[y & 1][x & 1] < weight else a for x in range(8)]
            for y in range(8)]


def noise(seed):
    """A deterministic 0..255 hash. Desert floor variation, not stripes.

    The modulo patterns this replaced (`(row + col) % 5`) read as corduroy:
    the eye finds a diagonal period instantly and the ground stops being
    ground. A hash has no period to find.
    """
    x = (seed * 2654435761) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 2246822519) & 0xFFFFFFFF
    x ^= x >> 13
    return x & 0xFF


# =============================================================================
# THE TILES
# =============================================================================
HZ_T = {}
HZ_TILES = []


def tile(name, rows):
    assert name not in HZ_T, f"duplicate tile {name}"
    HZ_T[name] = len(HZ_TILES)
    HZ_TILES.append((name, rows))
    return HZ_T[name]


# --- sky: four steps, Bayer-dithered between, so there is no banding edge ---
tile("sky_0", flat(I_SKY_TOP))
tile("sky_01", dither(I_SKY_TOP, I_SKY_HI))
tile("sky_1", flat(I_SKY_HI))
tile("sky_12", dither(I_SKY_HI, I_SKY_MID))
tile("sky_2", flat(I_SKY_MID))
tile("sky_23", dither(I_SKY_MID, I_SKY_LOW))
tile("sky_3", flat(I_SKY_LOW))

# --- the ridge: EIGHT sub-cell profiles, so the skyline is smooth ----------
# `mesa_p{k}` has k rows of low sky above the silhouette, so a per-column top
# in PIXELS resolves to one tile and the ridge steps by 1 px rather than by a
# whole cell. The comb the first pass produced was a per-column top in CELLS —
# eight times too coarse, and the eye read the period instantly.
for k in range(8):
    tile(f"mesa_p{k}", [[I_SKY_LOW] * 8 if y < k else [I_MESA_DK] * 8
                        for y in range(8)])
tile("mesa_body", flat(I_MESA_DK))
tile("mesa_foot", pic("mmmmmmmm", "mmmmmmmm", "mmmmmmmm", "mMmMmMmM",
                      "MMMMMMMM", "MMMMMMMM", "MhMhMhMh", "hhhhhhhh"))

# --- the horizon: the hot strip the band starts under ----------------------
tile("horizon", pic("hhhhhhhh", "hhhhhhhh", "hNhNhNhN", "NNNNNNNN",
                    "NNNNNNNN", "NnNnNnNn", "nnnnnnnn", "nnnnnnnn"))

# --- the desert floor ------------------------------------------------------
tile("sand", flat(I_SAND))
tile("sand_lit", dither(I_SAND, I_SAND_LIT, 1))
tile("sand_dk", dither(I_SAND, I_SAND_DK, 1))
tile("scree", pic("nnnnnnnn", "nnndnnnn", "nndRdnnn", "nnnddnnn",
                  "nnnnnnnd", "nnnnnndR", "nnnnnnnd", "nnnnnnnn"))

# --- the road --------------------------------------------------------------
tile("road", flat(I_ROAD))
tile("road_dk", dither(I_ROAD, I_ROAD_DK, 1))
tile("road_dash", pic("AAAAAAAA", "AAALLAAA", "AAALLAAA", "AAALLAAA",
                      "AAALLAAA", "AAALLAAA", "AAALLAAA", "AAAAAAAA"))
tile("road_l", pic("nnnnnAAA", "nnnnAAAA", "nnnnAAAA", "nnnAAAAA",
                   "nnnAAAAA", "nnAAAAAA", "nnAAAAAA", "nAAAAAAA"))
tile("road_r", pic("AAAnnnnn", "AAAAnnnn", "AAAAnnnn", "AAAAAnnn",
                   "AAAAAnnn", "AAAAAAnn", "AAAAAAnn", "AAAAAAAn"))

# --- the saguaro. ITS TRUNK IS THE TEST SURFACE ----------------------------
# The trunk occupies x = 2..5 of the cell in EVERY body tile, so its left edge
# sits at cell*8 + 2 in an undistorted frame and at cell*8 + 2 + warp[y] in a
# distorted one. A per-scanline displacement is a per-scanline PREDICTION, and
# that is what tests/test_heathaze.py reads back off the screenshot.
#
# The arm is in the TOP tile only, deliberately: it makes the silhouette read
# as a saguaro at eight pixels wide without disturbing the straight edge the
# body tiles give the test.
tile("cact_top", pic("nnnnnnnn", "nncccCnn", "nccCCCnn", "nccCCCnn",
                     "nccCCCcC", "nccCCCcC", "nccCCCnn", "nccCCCnn"))
tile("cact_body", pic("nccCCCnn", "nccCCCnn", "nccCCCnn", "nccCCCnn",
                      "nccCCCnn", "nccCCCnn", "nccCCCnn", "nccCCCnn"))
tile("cact_foot", pic("nccCCCnn", "nccCCCnn", "nccCCCnn", "nccCCCnn",
                      "nccCCCnn", "ndcCCCdn", "nddddddn", "nnnnnnnn"))
tile("boulder", pic("nnnnnnnn", "nnndddnn", "nnddRRdn", "ndddRRRd",
                    "ddRRRRRd", "dRRRRRRd", "ddRRRRdd", "nddddddn"))


# =============================================================================
# THE MAP — 32x32 words, 28 rows visible
# =============================================================================
#   rows  0..9    sky, a four-step Bayer gradient
#   rows 10..12   the mesa ridge, its top placed per column IN PIXELS
#   row     13    the ridge's foot, where the light comes back up
#   row     14    the horizon strip                       (y 112..119)
#   rows 15..27   the desert floor and the road           (y 120..223)
#
# HZ_BAND_TOP = 120 is the first scanline of row 15 and the top of the haze
# band. Above it the layer is undistorted — the sky and the ridge stay still,
# which is what gives the shimmer something to be measured against and is the
# concept sheet's "fade out with region edges" made structural.
HZ_ROWS, HZ_COLS = 32, 32
# THE BAND REACHES ABOVE THE HORIZON, and that is a consequence of what heat
# haze IS. A sightline to a distant object grazes ALONG the hot layer for its
# whole length, so the mesa's foot and the horizon strip are seen through more
# hot air than anything else on screen. Starting the band at the ground line
# would leave the one part of the picture that should shimmer most perfectly
# still.
#
# 100 rather than 96: a blob is 5 bytes of structure plus two per band line and
# the stride is 256, so 125 lines is the ceiling and 124 is the clean number
# under it. The stride is what makes a phase change ONE 8-bit store; a band
# wide enough to break it would cost more per frame than the extra 4 lines buy.
HZ_BAND_TOP = 100
HZ_BAND_LINES = 224 - HZ_BAND_TOP          # 124
GROUND_TOP = 15
RIDGE_BASE_Y = 104

# (first col, last col, top y). Flat tops with talus shoulders between them —
# a skyline reads as mesa country because the FLATS are long, so these runs are
# wide and the ramps between them are short.
MESAS = [(1, 8, 88), (11, 13, 82), (17, 26, 96), (28, 31, 90)]


def ridge_profile():
    """Top-of-ridge y per column, in pixels."""
    top = [RIDGE_BASE_Y] * HZ_COLS
    for c0, c1, y in MESAS:
        for c in range(c0, c1 + 1):
            top[c] = min(top[c], y)
    # Two-column talus either side of every flat, so nothing is a sheer wall.
    out = list(top)
    for c in range(HZ_COLS):
        for d in (1, 2):
            for n in (c - d, c + d):
                if 0 <= n < HZ_COLS:
                    out[c] = min(out[c], top[n] + d * 5)
    return out


MESA_TOP = ridge_profile()

ROAD_MID = 16


def road_half_width(row):
    """Cells either side of centre: 2 at the far end, 7 at the near one.

    Gentler than a 1..8 spread, which stepped a whole cell almost every row
    and read as a staircase rather than as a road going away.
    """
    return 2 + (row - GROUND_TOP) * 5 // (27 - GROUND_TOP)


CACTI = [(4, 20, 23), (27, 18, 22), (11, 24, 26)]


def sky_cell(row):
    return ("sky_0", "sky_0", "sky_0", "sky_01", "sky_01", "sky_1", "sky_1",
            "sky_12", "sky_2", "sky_23")[row]


def floor_cell(row, col):
    """The desert floor: road, furniture, or one of three sand treatments."""
    for c, r0, r1 in CACTI:
        if col == c and r0 <= row <= r1:
            return ("cact_top" if row == r0 else
                    "cact_foot" if row == r1 else "cact_body")

    hw = road_half_width(row)
    lo, hi = ROAD_MID - hw, ROAD_MID + hw
    if col == lo:
        return "road_l"
    if col == hi:
        return "road_r"
    if lo < col < hi:
        if col == ROAD_MID and row >= 19 and (row & 1) == 0:
            return "road_dash"
        return "road" if (row & 1) == 0 else "road_dk"

    # Off-road. A hash, not a modulus: patches with no period for the eye to
    # find. The thresholds are weighted so plain sand dominates and the
    # variants read as scatter rather than as texture.
    n = noise(row * 61 + col * 7 + 1)
    if n < 13:
        return "boulder"
    if n < 42:
        return "scree"
    if n < 96:
        return "sand_lit"
    if n < 138:
        return "sand_dk"
    return "sand"


def cell(row, col):
    if row <= 9:
        return sky_cell(row)
    if row <= 12:
        y0 = row * 8
        top = MESA_TOP[col]
        if top >= y0 + 8:
            return "sky_3"
        if top <= y0:
            return "mesa_body"
        return f"mesa_p{top - y0}"
    if row == 13:
        return "mesa_foot"
    if row == 14:
        return "horizon"
    return floor_cell(row, col)


def map_words():
    """32x32 tilemap words. Palette group 0, no flips, no priority."""
    return [HZ_T[cell(min(row, 27), col)]
            for row in range(HZ_ROWS) for col in range(HZ_COLS)]
# =============================================================================
# BG2: THE SHIMMER LAYER (stage 2) — palette group 2, CGRAM words 32..47
# =============================================================================
# WHAT IT IS FOR. The displacement bends the world; this layer is the GLARE
# that sits in front of it, half-added onto the main screen by the PPU's one
# colour-math unit. Nothing here paints a "hazy" colour: every pixel of the
# shimmer is an OPERAND, and what you see is (world + shimmer) >> 1 where the
# two overlap and the world UNHALVED where the shimmer is transparent — the
# empty-sub fallback, which is the case that tells a real sub-screen blend
# from a palette trick.
#
# SO IT IS MOSTLY TRANSPARENT, ON PURPOSE. A dense sub layer would halve the
# whole band and read as fog. What makes it read as heat is sparse vertical
# wisps over a world that is otherwise at full intensity, thickening toward
# the hot ground exactly as the displacement's amplitude does.
#
# AND ITS COLOURS ARE WARM AND BRIGHT, which is a consequence of the operator
# rather than a preference: a half-add pulls the result toward the mean of the
# two operands, so a shimmer DARKER than the sand would read as soot. These
# sit above the sand's own luminance, so the overlap lightens and desaturates.
SHIM_DIM = (25, 21, 15)
SHIM_MID = (29, 25, 19)
SHIM_HOT = (31, 30, 26)

# Word 0 is the 4bpp TRANSPARENT slot for this group and is never rendered, so
# its value is not a colour decision — it is written black and stated as such.
HZ_SHIM_PAL = [0, bgr(*SHIM_DIM), bgr(*SHIM_MID), bgr(*SHIM_HOT)] + [0] * 12

I_SH_NONE, I_SH_DIM, I_SH_MID, I_SH_HOT = 0, 1, 2, 3
SH_LEGEND = {".": I_SH_NONE, "d": I_SH_DIM, "m": I_SH_MID, "h": I_SH_HOT}


def shim_pic(*rows):
    assert len(rows) == 8, f"expected 8 rows, got {len(rows)}"
    return [[SH_LEGEND[ch] for ch in row] for row in rows]


HZ_SH_T = {}
HZ_SH_TILES = []


def shim_tile(name, rows):
    assert name not in HZ_SH_T, f"duplicate shimmer tile {name}"
    HZ_SH_T[name] = len(HZ_SH_TILES)
    HZ_SH_TILES.append((name, rows))
    return HZ_SH_T[name]


shim_tile("none", [[I_SH_NONE] * 8 for _ in range(8)])
# Four wisps, each a vertical stroke that wanders a pixel or two — the shape a
# rising column of hot air makes. They are drawn at different x within the
# cell so a run of them does not read as a grid.
shim_tile("wisp_a", shim_pic("..d.....", "..dm....", "...m....", "...md...",
                             "..dm....", "..m.....", "..md....", "...d...."))
shim_tile("wisp_b", shim_pic(".....d..", "....dm..", "....m...", "...dm...",
                             "....m...", "....mh..", ".....m..", ".....d.."))
shim_tile("wisp_c", shim_pic("......d.", ".....dm.", ".....m..", "....dm..",
                             ".....m..", ".....d..", "....dm..", "....m..."))
shim_tile("wisp_d", shim_pic("d.......", "dm......", "m.......", "dm......",
                             ".m......", ".mh.....", ".m......", "d......."))
# Two brighter ones for the near ground, where the effect is strongest.
shim_tile("glare_a", shim_pic("..m.....", "..mh..d.", "..h..dm.", ".mh..m..",
                              ".h..dm..", "mh..m...", "m..dm...", "m..m...."))
shim_tile("glare_b", shim_pic(".....m..", "d....mh.", "dm...h..", ".m..mh..",
                              ".mh.h...", "..h.h...", "..mh....", "...m...."))

# THE MIRAGE BAND, and it is the shape the reference sheet is right about.
# A desert mirage is not vertical: just under the horizon the hot ground
# refracts the sky into HORIZONTAL streaks, which is why it reads as standing
# water. Vertical wisps alone read as scratches on the sand — they are the
# right shape for a furnace vent and the wrong one for a road going away.
shim_tile("mirage_a", shim_pic("........", "dmmmd..d", "..dmmmmd", "........",
                               "dmd...dm", "...dmmd.", "........", "..dmd..."))
shim_tile("mirage_b", shim_pic("..dmmd..", "........", "dmmd..dm", "...dmd..",
                               "........", "mmd..dmm", "..dmmd..", "........"))

SHIM_WISPS = ["wisp_a", "wisp_b", "wisp_c", "wisp_d"]
SHIM_GLARE = ["glare_a", "glare_b"]
SHIM_MIRAGE = ["mirage_a", "mirage_b"]

# The glare band straddles the HORIZON — rows 13..16, the mesa's foot through
# the first ground rows — because that is where a sightline has passed through
# the most hot air. It is not "just under the horizon" as a composition
# choice; it is the same reason the displacement peaks there.
MIRAGE_ROW_LO, MIRAGE_ROW_HI = 13, 16


def shim_cell(row, col):
    """One BG2 cell: mostly nothing, thickening toward the hot ground.

    DENSITY TRACKS THE DISPLACEMENT'S OWN RAMP, which is why the two read as
    one effect rather than as two: where the world bends most it is also most
    glared over. Above the band there is nothing at all, so BG2 contributes no
    sub pixel there and the sky arrives unhalved.
    """
    if row < MIRAGE_ROW_LO:
        return "none"
    n = noise(row * 131 + col * 17 + 7)

    # The mirage band: dense and HORIZONTAL, straddling the horizon, where the
    # sightline has passed through the most hot air. Nearly solid, because this
    # is the one place the half-add should visibly lift the whole ground.
    if row <= MIRAGE_ROW_HI:
        return SHIM_MIRAGE[n & 1] if n < 215 else "none"

    # Below it, rising air — THINNING toward the viewer's feet, tracking the
    # displacement's own ramp so the two read as one effect rather than as two.
    # This is the way round it is for the reason HZ_PEAK_Y gives: the near
    # ground is seen through hardly any hot air at all.
    t = (row - MIRAGE_ROW_HI) / (27 - MIRAGE_ROW_HI)
    if n < 96 - 74 * t:
        return SHIM_WISPS[n & 3] if t > 0.45 else SHIM_GLARE[n & 1]
    return "none"


def shim_map_words():
    """32x32 tilemap words. PALETTE GROUP 2 in the attribute bits.

    Group 0 is the world's (hz_bg claims it, word 0 included, because word 0
    is the transparent slot AND the hardware backdrop at once). Group 1 would
    overlap bg_text's 2bpp palette 7 at words 28..31. Group 2 is the first
    that collides with neither — `water` reached the same answer for the same
    reason.
    """
    attr = 2 << 10
    return [HZ_SH_T[shim_cell(min(row, 27), col)] | attr
            for row in range(HZ_ROWS) for col in range(HZ_COLS)]


# =============================================================================
# THE WARP TABLE — 32 phases of a per-scanline BG1VOFS displacement
# =============================================================================
# ONE PHASE, byte for byte, as the HDMA channel walks it:
#
#   [top, lo, hi]        a NON-REPEAT entry: write the pair once at scanline 0
#                        and idle for 119 more. The value is the scene's own
#                        base scroll, so lines 0..119 — sky, ridge, horizon —
#                        are exactly where the scene put them. This is the
#                        head-skip a channel needs because HDMA always starts
#                        at line 0, and it restates the seed rather than
#                        inventing a value (shg_cam's seed claim is the same
#                        shape from the other side).
#   [$80|104]            REPEAT: a new 2-byte unit every scanline for 104
#                        lines, which is what makes the band per-scanline
#                        rather than banded.
#   [lo, hi] x 104       the displacement, one pair per scanline of the band.
#   [$00]                terminator.
#
# Mode 2 is one register written TWICE per transfer, which is exactly what a
# BGnVOFS write-twice latch wants — platformer_bg's parallax channel says the
# same thing about the horizontal sibling of this port.
#
# THE STRIDE IS 256 AND THAT IS A DESIGN CHOICE, not a rounding. A phase's
# address is HZ_WARP + (phase << 8), so its low byte is always zero and
# selecting a phase is ONE 8-bit write to the channel's A1T high byte. 213
# bytes are used and 43 are slack; the slack buys the cheapest possible
# per-frame cost.
# SIXTY-FOUR PHASES, AND THE COUNT IS HOW THIS RAIL GOES SLOWER.
#
# The rate the consumer feeds in is phases-per-frame, so halving it would make
# the wave advance half as often — same 1/N-of-a-cycle jump each time, just
# further apart, which reads as MORE stepped rather than slower. Doubling the
# COUNT instead halves the angular speed AND halves the jump: the motion slows
# and gets smoother in the same change. It costs 8 KB more ROM and not one
# extra cycle, because selecting a blob is still a single 8-bit store.
#
# The ceiling is the bank: a blob is 256 B and HDMA cannot cross a bank
# boundary, so 65 blobs is 16,640 B and 128 phases would be 33 KB — over the
# 32 KB window. haze.asm asserts the placement rather than trusting this note.
HZ_PHASES = 64
HZ_PHASE_STRIDE = 256
# The base the band is displaced AROUND. This is BG1VOFS, and it is HZ_VOFS
# (-1) rather than 0 for the reason heathaze.inc gives: the first active
# scanline is 1, so a VOFS of -1 is what puts world row r on picture rows
# 8r..8r+7. The table's head-skip entry restates this value over the lines
# above the band, so an undistorted scanline is byte-identical to one the CPU
# wrote.
HZ_BASE_VOFS = 0xFFFF

# Amplitude in WHOLE PIXELS at the PEAK, which is the horizon. BG1VOFS is a
# whole-pixel scroll, so the ramp quantises to this many steps and no more —
# which is also why the test can assert an EQUALITY rather than a tolerance.
#
# FOUR, AND THE AXIS IS WHY IT IS NOT MORE. A vertical displacement is louder than
# a horizontal one of the same size: shearing a row sideways still shows every
# source row exactly once, while displacing it vertically DUPLICATES and SKIPS
# rows. At 7 the horizon strip — 8 px tall — is scrambled into a wide pale
# smear that eats the mesa's foot. At 5 it shimmers and stays a horizon.
# Compared on the shipped binary at 4, 5 and 7.
HZ_AMP_MAX = 4

# WHERE THE HAZE IS STRONGEST, and the correction this rail was built wrong
# around the first time.
#
# The obvious reading of "strongest distortion close to the source" puts the
# maximum at the bottom of the screen, nearest the viewer. That is right for a
# LOCALISED source — a furnace vent, an exhaust plume — where the hot column is
# in one place and screen-distance from it IS physical distance from it.
#
# It is exactly backwards for a HOT GROUND PLANE seen in perspective. The hot
# layer is everywhere, the air is the same everywhere, and what varies is how
# much of it a sightline passes THROUGH. Look at the dirt at your feet and you
# look down across a thin layer: almost no refraction. Look at the horizon and
# your sightline grazes ALONG that layer for its whole length: the refraction
# accumulates over hundreds of metres. That is why a desert mirage pools at the
# horizon and the ground at your boots looks normal, and why this ramp peaks
# there and decays toward the viewer.
HZ_PEAK_Y = 116                  # the horizon strip — the longest sightline

# The falloff below the peak. Apparent ground distance on a plane goes like
# 1/(y - horizon), and path length through the hot layer goes with distance, so
# amplitude follows the same reciprocal. HZ_FALLOFF sets how fast: at the
# bottom of the screen the amplitude is HZ_FALLOFF/(HZ_FALLOFF + 108) of the
# peak, which at 40 is a bit over a quarter — visible, but plainly weaker than
# the distance.
HZ_FALLOFF = 40.0

# Above the peak the sky is not hot, so the band ramps in over the ridge's foot
# rather than starting at full strength on the mesa.
HZ_RISE_LINES = HZ_PEAK_Y - HZ_BAND_TOP

# Two components, so the shimmer does not read as one clean sine. The second
# is shorter and travels at twice the rate; both wrap on the 32-phase loop
# (p/32 and 2p/32 are both whole cycles at p = 32), so the animation closes.
HZ_LAMBDA_1, HZ_LAMBDA_2 = 28.0, 11.0
HZ_MIX_1, HZ_MIX_2 = 0.70, 0.30
HZ_PHASE_2 = 1.1                 # a fixed offset, so the two never start together


def amplitude(line):
    """Displacement amplitude at a band line. WIDEST AT THE HORIZON.

    See HZ_PEAK_Y for why this is the way round it is: the quantity that
    matters is path length through hot air, and a sightline to the horizon has
    far more of it than one to the viewer's feet.
    """
    y = HZ_BAND_TOP + line
    if y <= HZ_PEAK_Y:
        # Ramping in over the ridge's foot — the sky above is not hot.
        return HZ_AMP_MAX * (y - HZ_BAND_TOP) / HZ_RISE_LINES
    return HZ_AMP_MAX * HZ_FALLOFF / (HZ_FALLOFF + (y - HZ_PEAK_Y))


def _perspective_u(y):
    """A vertical coordinate in which equal steps are equal GROUND distance.

    The same physical eddy of hot air subtends fewer scanlines the further away
    it is, so a wave of constant wavelength in `y` is a wave that gets
    physically larger with distance — which reads as the horizon boiling in
    slow motion while the near ground vibrates. Integrating the reciprocal
    falloff gives a log, and in THIS coordinate the wave has one physical
    scale everywhere: features compress toward the horizon exactly as the
    ground does.
    """
    return HZ_FALLOFF * math.log(1.0 + (y - HZ_PEAK_Y + HZ_FALLOFF) / HZ_FALLOFF)


def displacement(line, phase):
    """Whole-pixel BG1VOFS offset for one band line in one phase."""
    u = _perspective_u(HZ_BAND_TOP + line)
    a = 2.0 * math.pi
    w1 = math.sin(a * (u / HZ_LAMBDA_1 + phase / HZ_PHASES))
    w2 = math.sin(a * (u / HZ_LAMBDA_2 + 2.0 * phase / HZ_PHASES) + HZ_PHASE_2)
    return int(round(amplitude(line) * (HZ_MIX_1 * w1 + HZ_MIX_2 * w2)))


def vofs_pair(value):
    """BG1VOFS as the write-twice latch takes it: low byte, then high."""
    v = value & 0x3FF
    return bytes((v & 0xFF, (v >> 8) & 0x03))


def warp_phase(phase):
    """One 256 B phase blob."""
    out = bytearray()
    out += bytes((HZ_BAND_TOP,)) + vofs_pair(HZ_BASE_VOFS)      # head skip
    out += bytes((0x80 | HZ_BAND_LINES,))                       # repeat entry
    for line in range(HZ_BAND_LINES):
        out += vofs_pair(HZ_BASE_VOFS + displacement(line, phase))
    out += bytes((0x00,))                                       # terminator
    assert len(out) <= HZ_PHASE_STRIDE, f"phase {phase}: {len(out)} B overruns"
    return bytes(out) + bytes(HZ_PHASE_STRIDE - len(out))


# ONE MORE BLOB THAN THERE ARE PHASES, and it is the control.
#
# `stilling` the animation freezes the phase, which leaves a FIXED warp on
# screen — a perfectly good thing to look at and completely useless as a
# baseline. What the concept sheet's "before distortion / after heat haze"
# pair needs is the same picture with NO displacement at all, from the same
# binary, differing in nothing but this table. So index HZ_FLAT_INDEX is a
# complete, correctly-shaped HDMA table whose every displacement is zero: the
# channel stays armed, the head-skip and repeat entries are byte-identical in
# shape, and only the values are flat.
#
# That matters for the test as much as for the eye. A control that DISARMED
# the channel would differ from the live case in two ways — the table and the
# channel — and a two-variable comparison cannot attribute what it sees.
HZ_FLAT_INDEX = HZ_PHASES


def flat_phase():
    """A complete table, same shape, every displacement zero."""
    out = bytearray()
    out += bytes((HZ_BAND_TOP,)) + vofs_pair(HZ_BASE_VOFS)
    out += bytes((0x80 | HZ_BAND_LINES,))
    out += vofs_pair(HZ_BASE_VOFS) * HZ_BAND_LINES
    out += bytes((0x00,))
    return bytes(out) + bytes(HZ_PHASE_STRIDE - len(out))


def warp_table():
    return b"".join(warp_phase(p) for p in range(HZ_PHASES)) + flat_phase()


# =============================================================================
# ENCODERS — assert, never mask
# =============================================================================
# A bitwise AND that quietly folds an out-of-range index into range is the
# silent-corruption trap AGENTS.md names by example. Every encoder here says
# which pixel was wrong instead.


def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3)."""
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    for y, row in enumerate(rows):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} px, expected 8"
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


ART_INC = """; hz_art.inc — GENERATED by tools/gen_haze_assets.py. Do not edit.
;
; The LAYOUT of the warp blob, for the code that indexes it. The blob itself
; arrives through .incbin; these are the only numbers the ASM needs to walk it,
; and they are emitted rather than restated so the table and the walker cannot
; disagree about the stride.
HZ_PHASES        = {phases}     ; the loop closes here
HZ_FLAT_INDEX    = {flat}     ; the zero-displacement control, same shape
HZ_BLOB_COUNT    = {blobs}     ; phases + the control
HZ_PHASE_SHIFT   = {shift}      ; stride 256 -> a blob is (index << 8)
HZ_BAND_TOP      = {band_top}   ; first distorted scanline
HZ_BAND_LINES    = {band_lines} ; how many the repeat entry covers
HZ_TILE_COUNT    = {tiles}
HZ_SHIM_TILES    = {shim}
"""


def main(argv):
    out = pathlib.Path(argv[1] if len(argv) > 1 else "build/assets")
    out.mkdir(parents=True, exist_ok=True)

    chr_blob = b"".join(encode_4bpp(rows, name) for name, rows in HZ_TILES)
    (out / "hz_chr.bin").write_bytes(chr_blob)
    (out / "hz_map.bin").write_bytes(encode_words(map_words(), "hz_map", 1024))
    (out / "hz_pal.bin").write_bytes(encode_words(HZ_PAL, "hz_pal", 16))

    shim_chr = b"".join(encode_4bpp(rows, n) for n, rows in HZ_SH_TILES)
    (out / "hz_shim_chr.bin").write_bytes(shim_chr)
    (out / "hz_shim_map.bin").write_bytes(
        encode_words(shim_map_words(), "hz_shim_map", 1024))
    (out / "hz_shim_pal.bin").write_bytes(
        encode_words(HZ_SHIM_PAL, "hz_shim_pal", 16))

    warp = warp_table()
    assert len(warp) == (HZ_PHASES + 1) * HZ_PHASE_STRIDE, len(warp)
    (out / "hz_warp.bin").write_bytes(warp)

    (out / "hz_art.inc").write_text(ART_INC.format(
        phases=HZ_PHASES, flat=HZ_FLAT_INDEX, blobs=HZ_PHASES + 1,
        shift=8, band_top=HZ_BAND_TOP,
        band_lines=HZ_BAND_LINES, tiles=len(HZ_TILES),
        shim=len(HZ_SH_TILES)))

    print(f"hz_chr.bin   {len(chr_blob):6d} B  ({len(HZ_TILES)} tiles)")
    print(f"hz_map.bin     2048 B  (32x32 words)")
    print(f"hz_pal.bin       32 B  (16 CGRAM words)")
    print(f"hz_shim_chr.bin  {len(shim_chr):4d} B  ({len(HZ_SH_TILES)} tiles, BG2 sub screen)")
    print(f"hz_shim_map.bin  2048 B  (32x32 words, palette group 2)")
    print(f"hz_shim_pal.bin    32 B  (16 CGRAM words at 32)")
    print(f"hz_warp.bin  {len(warp):6d} B  ({HZ_PHASES} phases + 1 flat "
          f"control x {HZ_PHASE_STRIDE} B, band {HZ_BAND_TOP}..224)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
