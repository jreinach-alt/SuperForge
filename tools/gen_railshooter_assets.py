#!/usr/bin/env python3
"""gen_railshooter_assets.py — superforge: the railshooter rail's art + its LUT.

Seven blobs, all AUTHORED here from integer shapes — there is no converter and
no source image, so there is nothing to fall back to and nothing to fetch:

    rs_map.bin         32,768 B  the interleaved Mode 7 grid plane: a 128x128
                                 tilemap in the EVEN bytes, three solid 8bpp
                                 tiles in the ODD bytes
    rs_floor_pal.bin        8 B  4 BGR555 words, ABSOLUTE CGRAM indices at 0
    rs_obj_chr.bin      7,168 B  224 tiles x 32 B, 4bpp, on the 16-wide OBJ grid
    rs_obj_pal.bin         64 B  2 x 16 BGR555 words (OBJ palettes 0 and 1)
    rs_proj_scan.bin       81 B  screen_y per z bucket
    rs_proj_scale.bin     162 B  FOCAL*256/z per z bucket, u16 LE
    rs_path.bin           512 B  256 x s16: one full S period of LATERAL camera
                                 offset — the curve the rail flies.
                                 ONE ENTRY PER FRAME, so the curve
                                 is sampled at 60 Hz and not at 15

Deterministic: pure integer arithmetic (plus math.sin/round for the path, the
same shape gen_pose_tables.py uses) from the constants below, so a re-run is
byte-identical.

=============================================================================
THE S-CURVE IS A TRANSLATION. IT IS NOT A ROTATION.
=============================================================================
`rs_path.bin` is a table of LATERAL OFFSETS added to the rail's centre column
and written into the Mode 7 camera origin (M7X), which is a free per-frame
CPU-written VBlank shadow over a wrapping 16-bit world position
(`engine/features/mode7_persp/feature.toml:36,50`).

The POSE table is the quantised thing — 64 headings, so the smallest turn the
plane can make is 5.6 degrees — and steering the curve with it is exactly what
makes a quantised turn read as BINARY in play. So the heading is
pinned at 0 for the whole run and the curve lives here instead.

=============================================================================
THE PROJECTION LUT — a pinhole (1/z), NOT the Mode 7 matrix inverse
=============================================================================
This is the rail's headline, and it is worth stating why the LUT exists rather
than a solve. The camera is a pinhole at height CAM_H above the ground; a point
at forward depth z projects by 1/z:

    screen_y(z) = clamp(HORIZON_Y + CAM_H*256/z, HORIZON_Y, Y_BOTTOM)
    scale(z)    = FOCAL*256/z                  (a .8 perspective factor)
    screen_x    = 128 + ((obj_x - cam_x) * scale) >> 8

It is still a LUT and not a live matrix inverse — that part of the headline
stands. What it is no longer is a DIFFERENT CAMERA from the one the Mode 7
plane is drawn through, and that is the calibration this file records.

=============================================================================
THE PINHOLE IS THE PLANE'S OWN CAMERA. MEASURED, THEN SOLVED.
=============================================================================
The pose blob (`gen_pose_tables.py --lines 180 --scale-far 436 --scale-near
77`) is a per-scanline hyperbola S(k) = K/(k + k0) over band rows k = 0..179,
with k0 = 77*179/(436-77) = 38.39 and K = 436*k0 = 16739. Mode 7 maps band row
k to texture row `cam_y + S(k)*k/256`, so the ground point at row k lies

    d(k) = (K*k0/256) / (k + k0) = 2511 / (k + 38.39)     texture px ahead

which inverts to `k = 2511/d - 38.39`. THAT IS A PINHOLE TOO — with its
vanishing point 38.39 rows ABOVE the seam (screen y 5.6, inside the sky band)
and a lateral focal length of 2511/65.39 = 38.4. The shipped LUT put the
obstacles' vanishing point AT the seam (HORIZON_Y = 44) with CAM_H = 17 and
FOCAL = 44. Two different cameras over one picture.

The consequence is not subtle and it is why the pylons read as sliding rather
than standing. MEASURED on the rendered frame (`rs-probe`, the marker plane;
tests/test_railshooter.py's calibration case), as shipped:

    screen row      55      65      75      85      95     110     130
    SURFACE px/f  1.41    2.14    3.08    4.16    4.84    7.50   10.00
    PYLON   px/f  0.12    0.39    0.92    1.63    2.50    4.00    7.50
    ratio        11.7x    5.6x    3.4x    2.6x    1.9x    1.9x    1.3x

A surface point crossed rows 50->200 in 29 frames; a pylon took 153. NO SINGLE
SPEED FIXES THAT — the ratio is a 9x SPREAD across the screen, so any scalar
on either side can only make the two agree on one row. The shapes have to
match, and they match iff the two cameras are the same camera:

    k(z) = A/z - k0     with    A = 2511 * RS_OBS_STEP / rail_speed

so    HORIZON_Y = 44 - k0 = 6          the PLANE's vanishing row, not the seam
      CAM_H*256 = A       -> CAM_H  = 98      at 5 z/frame and 128/256 px/frame
      FOCAL     = 38.4*A/2511 -> 384          the plane's own lateral focal

`rail_speed` (RS_RAIL_SPEED_88) and RS_OBS_STEP are then locked together: one
z unit IS 1/9.8 of a texture px, so an actor closing 5 z per frame closes
exactly the 128/256 texture px the rail advances. The surface and everything
standing on it move at ONE rate, at every row, by construction.

THE PAIR IS FREE ALONG THAT LINE, and 128/5 is chosen rather than fitted.
Any (speed, step) with step = 9.8 * speed keeps the same LUT and the same
lock; what moves is the crossing time (53.8/speed frames) and, less obviously,
the SMOOTHNESS. `cam_y` is a 13-bit INTEGER — Mode 7 has no fractional scroll —
so the plane advances in whole texture px, which at the bottom row is 18.8
screen px however slowly the rail is going. 128/256 emits exactly one such step
every OTHER frame: a regular 30 Hz cadence rather than the irregular 2-or-3
frame pattern any non-dyadic speed produces, and irregular is what reads as
judder (this rail already paid for that once on the lateral axis — see
PATH_N below). 105/4 would buy a 2.2-second approach at a 41%-duty stutter;
262/10 would buy a perfectly smooth 0.9 s. 128/5 is 1.8 s at a regular
half-rate, which is the balance taken.

WHAT THE LOCK COSTS, stated plainly. The plane's visible depth is only
d(0) - d(179) = 65.4 - 11.6 = 53.8 texture px — that is a fact of the pose
blob's 436:77 scale ratio, not a tuning choice — so a ground-locked crossing
takes 53.8/rail_speed frames and NOTHING else. 1.5 px/frame therefore buys a
36-frame crossing, which is far too short to aim at; the rail speed is what
sets the approach, and 128/256 = 0.5 px/frame buys 108 frames (1.8 s) of an
approach that is MOVING AND GROWING the whole way — against the shipped rail's
76 frames of a near-static speck in the top six scanlines followed by 78 frames
of real approach. That is the owner's own
first option — "slow the surface further" — arrived at by solving rather than
by feel, and the second option ("move the pillars faster") is the same
equation read the other way: it would buy a 0.6-second approach.

Z_FAR = 640 IS UNDER THE SEAM. A/38.39 = 653, so an actor spawned at RS_Z_FAR
projects to scanline 45 — one row inside the plane. It rises out of the horizon
rather than popping in below it, and NO actor is ever projected into the sky
band, so the change needed no new cull for that. (It did need one for the
LATERAL axis: see rs_project's nine-bit guard.) The tier thresholds were
re-solved to keep their SCREEN bands where they were (y = 98 / 71 / 56).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

# =============================================================================
# the S-curve the rail flies
# =============================================================================
# 256 signed words, one full period, ONE ENTRY PER FRAME. The driver indexes it
# with `dist & 255` at RS_PATH_SHIFT = 0, so one S period is 256 frames and each
# bend is 128.
#
# WHY 256 AND NOT 64, and it is the reason this blob is 512 B rather
# than 128. The first cut baked 64 entries and held each for four frames
# (`dist >> 2`) with no interpolation. `cam_x` lands in BOTH M7X and the floor's
# HOFS, so the whole Mode 7 plane sat perfectly still for three frames and then
# jumped up to 21 screen px sideways at the bottom of the screen — a 15 Hz
# stutter on the redesign's headline mechanic, measured as per-frame floor
# deltas of -21.0/0/0/0/-17.0/0/0/0 at screen row 200.
#
# That is the SAME defect class the forward axis was already given 8.8 sub-pixel
# accumulation to avoid — an integer step of 1 or 2 reads as steppy at this
# scale — at four times the step size. Baking the period at frame resolution
# costs +384 B of a 512 KB image, makes the lookup CHEAPER (the shift loop
# disappears), and preserves the exact sine — the four phases the tests sample
# are the same points on the same curve.
#
# AMPLITUDE, and why 64 — the number the LATERAL half of the ground lock moves
# it to. The reticle is a world-anchored ground point at RS_RET_Z_INIT, and the
# amplitude that matters is the one the PILOT SEES: amplitude x the lateral
# gain at that depth. The shipped rail had 144 world px at a gain of
# 44/60 = 0.73, i.e. a +/-105 SCREEN px drag across a bend. The corrected FOCAL
# is the plane's own (384/227 = 1.69 at the same point), so 144 would drag the
# aim +/-243 px — off both edges of a 256-px frame, and MEASURED doing exactly
# that: the reticle spent whole bends culled and four cases went red on a
# parked OAM entry.
#
# 64 x 1.69 = +/-108 screen px. The drag the pilot compensates for is therefore
# the SHIPPED drag, to within three pixels; what shrank is the WORLD amplitude,
# because the projection had been under-reading the plane's lateral gain by
# 2.3x. The same correction is why the plane's own sideways sweep at the aim's
# row drops from +/-243 px to +/-108: the GRID was always moving that far, and
# the aim point standing on it was not.
# The pose blob the lock is solved against (Makefile: gen_pose_tables.py
# --lines 180 --scale-far 436 --scale-near 77). Named here because the
# projection's three constants are DERIVED from them and the derivation is
# asserted in build_proj() — a pose regenerated at a different scale ratio must
# fail this file, not ship a plane the actors slide over.
PERSP_LINES = 180
SCALE_FAR, SCALE_NEAR = 436, 77
# The rail's forward speed and the actors' depth step, in the units
# game/railshooter/railshooter.inc spells them. They are the OTHER half of the
# lock: A = 2511 * OBS_STEP / (RAIL_SPEED_88/256).
RAIL_SPEED_88 = 128
OBS_STEP = 5

PATH_N = 256
PATH_AMP = 64
# The largest single-frame lateral step the baked curve may take, in WORLD px.
# The sine's own peak slope is AMP*2*pi/N = 144*2*pi/256 = 3.53 world px/frame,
# so 4 is the tightest integer bound the rounded table can satisfy. Asserted in
# build_path() so a future N or AMP that reintroduces a stepped curve fails
# HERE, in the generator, rather than as a judder nobody measures.
PATH_MAX_STEP = 4

# =============================================================================
# the Mode 7 grid plane
# =============================================================================
MAP_W = 128                 # world side, in tiles (= 1024 px, the Mode 7 wrap)
M7_TILE_BYTES = 64          # one 8x8 8bpp tile
GRID_STEP = 4               # a grid line every 4 tiles
MAJOR_STEP = 16             # a magenta major line every 16 tiles (lane refs)

# Absolute CGRAM indices, because a Mode 7 8bpp pixel value IS the index.
# Index 0 is BOTH palette entry 0 and the Mode 7 BACKDROP slot, and this rail
# SEES it: split_band turns BG1 off above the seam, so every sky scanline that
# sky_band's ramp does not cover is this colour. Deep space, therefore.
FLOOR_PAL = (
    0x2043,                 # 0 deep-space sky / backdrop        rgb(24,16,64)
    0x1C62,                 # 1 dark surface between grid lines  rgb(16,24,56)
    0x7728,                 # 2 bright cyan grid line            rgb(64,200,232)
    0x659D,                 # 3 magenta major line               rgb(232,96,200)
)
FLOOR_TILE_GROUND = 0       # tile id -> CHR tile holding solid index 1
FLOOR_TILE_GRID = 1
FLOOR_TILE_MAJOR = 2

# =============================================================================
# the pinhole projection
# =============================================================================
# The plane's own camera, solved above. HORIZON_Y is the MODE 7 PLANE's
# vanishing row (6), not the split_band seam (44) — the seam is where the plane
# starts being DRAWN, and the two are 38.39 rows apart because the pose blob's
# hyperbola has k0 = 38.39. A LUT keyed to the seam is a second camera over the
# same picture, and that is the whole of the sliding defect.
SEAM_Y = 44                 # the split_band seam == pose_rom's band top
HORIZON_Y = 6               # the PLANE's vanishing row: SEAM_Y - k0 (38.39)
Y_BOTTOM = 223              # lowest usable scanline (an obstacle centre clamps)
CAM_H = 98                  # A/256, A = 2511 * OBS_STEP / rail_speed
FOCAL = 384                 # 38.4 * A / 2511: the plane's own lateral focal
Z_NEAR = 16                 # the LUT's low end; actors are freed long before
Z_FAR = 640                 # spawn depth — A/k0 = 653, so it lands ONE
                            #   scanline under the seam and never above
PROJ_Q = 8                  # world px per bucket
PROJ_Q_LOG2 = 3
PROJ_N = (Z_FAR // PROJ_Q) + 1          # 81 buckets covering z in [0, 640]
# Re-solved from the new mapping to keep the tier bands on the SAME screen
# rows they occupied before (y = 98 / 71 / 56). Must equal RS_TIER_T0/T1/T2 in
# game/railshooter/railshooter.inc — rs_project reads those, this file only
# asserts the bands stay distinct.
TIER_T0, TIER_T1, TIER_T2 = 272, 384, 498


def screen_y(z: int) -> int:
    """The floor is the SEAM, not HORIZON_Y: the plane's vanishing row is above
    the seam and nothing may be projected into the sky band. At Z_FAR the
    unclamped value is 44.2, so the clamp is a guard rather than a shaper."""
    return min(Y_BOTTOM, max(SEAM_Y, HORIZON_Y + (CAM_H * 256) // z))


def scale_of(z: int) -> int:
    return min((FOCAL * 256) // z, 0xFFFF)


def build_proj() -> tuple[bytes, bytes]:
    """Bucket k covers z = k*Q, sampled at the bucket MIDPOINT so the value is
    representative of the whole bucket rather than of its left edge."""
    scan = bytearray()
    scale = bytearray()
    for k in range(PROJ_N):
        z = max(k * PROJ_Q + PROJ_Q // 2, 1)
        scan.append(screen_y(z) & 0xFF)
        scale += (scale_of(z) & 0xFFFF).to_bytes(2, "little")
    # screen_y must be monotone NON-INCREASING in z (nearer = lower on screen).
    # Pure pinhole math guarantees it; assert so a bad constant edit fails
    # loudly rather than shipping an unsound projection.
    ys = [screen_y(k * PROJ_Q + PROJ_Q // 2) for k in range(1, PROJ_N)]
    assert all(ys[i] >= ys[i + 1] for i in range(len(ys) - 1)), \
        "screen_y(z) is not monotone in z — projection unsound"
    # The ground lock, asserted where it is DECIDED. `k0` is the pose blob's own
    # hyperbola constant; a LUT whose vanishing row is not SEAM_Y - k0, or whose
    # A is not 2511*step/speed, is a second camera and the pylons slide again.
    k0 = SCALE_NEAR * (PERSP_LINES - 1) / (SCALE_FAR - SCALE_NEAR)
    assert abs((SEAM_Y - HORIZON_Y) - k0) < 1.0, (
        f"HORIZON_Y {HORIZON_Y} is not the PLANE's vanishing row "
        f"(SEAM_Y {SEAM_Y} - k0 {k0:.2f}) — the projection is a second camera")
    a_lock = 2511 * OBS_STEP / (RAIL_SPEED_88 / 256)
    assert abs(CAM_H * 256 - a_lock) / a_lock < 0.02, (
        f"CAM_H*256 = {CAM_H * 256} but the ground lock wants {a_lock:.0f} "
        f"(= 2511 * {OBS_STEP} / {RAIL_SPEED_88 / 256:.4f}) — an actor closing "
        f"z at that step would not track the surface")
    assert abs(FOCAL - 38.4 * CAM_H * 256 / 2511) / FOCAL < 0.02, (
        f"FOCAL {FOCAL} is not the plane's own lateral focal "
        f"({38.4 * CAM_H * 256 / 2511:.0f}) — objects would drift sideways "
        f"against the grid they stand on")
    assert screen_y(Z_FAR) <= SEAM_Y + 1, (
        f"z = Z_FAR projects to {screen_y(Z_FAR)}, below the seam — actors "
        f"would pop in rather than rise out of the horizon")
    assert Z_NEAR < TIER_T0 < TIER_T1 < TIER_T2 < Z_FAR, "tier thresholds"
    # Each tier must occupy a DISTINCT scanline band, or the pre-drawn size
    # tiers would swap without the object appearing to move.
    bands = [screen_y(t) for t in (TIER_T0, TIER_T1, TIER_T2)]
    assert bands[0] > bands[1] > bands[2], f"tier bands not distinct: {bands}"
    return bytes(scan), bytes(scale)


def build_path() -> bytes:
    """One full S period of lateral camera offset, s16 LE, ONE ENTRY PER FRAME.

    A pure sine, so the curve has no corners and the ship's bank (driven from
    the sine's own derivative, i.e. the table read a quarter period along)
    leads the swing rather than lagging it.
    """
    out = bytearray()
    for i in range(PATH_N):
        v = round(PATH_AMP * math.sin(2 * math.pi * i / PATH_N))
        out += (v & 0xFFFF).to_bytes(2, "little")
    def at(i):
        w = out[i * 2] | (out[i * 2 + 1] << 8)
        return w - 0x10000 if w >= 0x8000 else w
    # The four phases every test samples. A wrong amplitude or a wrong period
    # must fail HERE, not as a mystifying render.
    assert at(0) == 0 and at(PATH_N // 2) == 0, "the S must cross zero twice"
    assert at(PATH_N // 4) == PATH_AMP, "the first bend must reach +amplitude"
    assert at(3 * PATH_N // 4) == -PATH_AMP, "the second bend must reach -amp"
    # the curve must be sampled finely enough that no single frame
    # takes a visible lateral jump. This is the generator-side half of the
    # smoothness invariant the rendered-output test asserts; a coarse table put
    # back here fails the build instead of shipping a 15 Hz judder.
    steps = [abs(at((i + 1) % PATH_N) - at(i)) for i in range(PATH_N)]
    assert max(steps) <= PATH_MAX_STEP, (
        f"the S-curve steps {max(steps)} world px in one frame, over the "
        f"{PATH_MAX_STEP} px bound — the curve is quantised and the whole "
        f"Mode 7 plane will judder")
    return bytes(out)


def build_map(probe: bool = False) -> bytes:
    """The interleaved Mode 7 blob: tilemap in the even bytes, CHR in the odd.

    A rail shooter's ground is a streaming reference grid — a dark surface with
    bright lines, so the auto-advance reads as speed. Every 8x8 tile is one
    solid colour, which is why three CHR tiles cover the whole world.

    `probe=True` builds the MEASUREMENT plane instead (`rs_map_probe.bin`,
    reachable only through the `rs-probe` ROM). It re-spends the magenta index
    so that colour marks ONE THING: the major lines are demoted to ordinary
    cyan grid lines and every grid INTERSECTION becomes an 8x8 magenta square.
    Magenta then appears nowhere else in the frame — not in the sky ramp, not
    in either OBJ palette — so a rendered marker is found by colour alone, and
    its lattice period is the grid's own 32 world px, which is under the
    plane's ~54-px visible depth: one or two marker rows are on screen at every
    instant, at every rail speed. That is what makes "how fast does the SURFACE
    move at screen row r" a measurement rather than an estimate.
    """
    tilemap = bytearray(MAP_W * MAP_W)
    for ty in range(MAP_W):
        for tx in range(MAP_W):
            if probe:
                on_x, on_y = tx % GRID_STEP == 0, ty % GRID_STEP == 0
                t = (FLOOR_TILE_MAJOR if on_x and on_y else
                     FLOOR_TILE_GRID if on_x or on_y else FLOOR_TILE_GROUND)
            elif tx % MAJOR_STEP == 0 or ty % MAJOR_STEP == 0:
                t = FLOOR_TILE_MAJOR
            elif tx % GRID_STEP == 0 or ty % GRID_STEP == 0:
                t = FLOOR_TILE_GRID
            else:
                t = FLOOR_TILE_GROUND
            tilemap[ty * MAP_W + tx] = t
    chr_bytes = bytearray(MAP_W * MAP_W)
    for t, idx in ((FLOOR_TILE_GROUND, 1), (FLOOR_TILE_GRID, 2),
                   (FLOOR_TILE_MAJOR, 3)):
        chr_bytes[t * M7_TILE_BYTES:(t + 1) * M7_TILE_BYTES] = \
            bytes([idx]) * M7_TILE_BYTES
    out = bytearray(2 * MAP_W * MAP_W)
    out[0::2] = tilemap
    out[1::2] = chr_bytes
    return bytes(out)


# =============================================================================
# the OBJ sheet
# =============================================================================
# 4bpp, so an index is 0..15 and 0 is TRANSPARENT. Two palettes:
#   0  the ship          dark hull -> lit hull -> canopy -> engine glow
#   1  the hazards       dark rock -> hot rim -> the bullet's white, the
#                        reticle's cyan
SHIP_PAL = (
    0x0000,                 # 0 transparent
    0x1084,                 # 1 hull shadow
    0x2929,                 # 2 hull
    0x39CE,                 # 3 hull lit
    0x7FFF,                 # 4 canopy highlight
    0x7E00,                 # 5 canopy blue
    0x02FF,                 # 6 engine core (hot yellow-white)
    0x015F,                 # 7 engine flame (orange)
) + (0x0000,) * 8
# Palette 1 carries the whole non-ship world: hazards, pylons, the tracer, the
# reticle, the kill flash AND the HUD. Sixteen entries is enough because the
# redesign adds no new *material*, only new shapes — indices 8..15 were the
# shipped rail's unused tail and are where the HUD and the flash land, so the
# CGRAM claim does not grow.
HAZARD_PAL = (
    0x0000,                 # 0 transparent
    0x0806,                 # 1 rock shadow
    0x114C,                 # 2 rock
    0x1A93,                 # 3 rock lit
    0x02FF,                 # 4 hot rim (yellow)
    0x7FFF,                 # 5 white — the bullet tracer core
    0x7F00,                 # 6 cyan — the reticle
    0x03FF,                 # 7 amber — the reticle's inner tick
    0x6318,                 # 8 HUD silver — the score digits
    0x03E0,                 # 9 life segment FULL (green)
    0x0008,                 # 10 life segment EMPTY (dark red)
    0x23FF,                 # 11 kill-flash core (hot white-yellow)
    0x011F,                 # 12 kill-flash rim (red)
    0x5A0E,                 # 13 pylon lit face
    0x30E6,                 # 14 pylon dark face
    0x031F,                 # 15 pylon warning stripe (amber)
)

OBJ_TILE_BYTES = 32         # 8x8 4bpp
OBJ_GRID_W = 16             # the OBJ name grid the {N,N+1,N+16,N+17} rule forces
OBJ_TILES = 224             # fourteen grid rows

# Base tile numbers, OBJ-name-base relative.
#
# A 32x32 frame at base N reads {N..N+3, N+16..N+19, N+32..N+35, N+48..N+51} —
# four rows and four columns — so rows 0..3 hold four of them and rows 4..7 the
# next four. A 16x16 frame at base N reads {N, N+1, N+16, N+17} — TWO rows — so
# a row-PAIR holds eight, and the eighth ends at column 15. That is why the ten
# digits cannot be contiguous: the ninth would want base 144, whose N+16 row is
# already the eighth frame's bottom half. RS_DIGIT_TAB (railshooter.inc) is the
# ten-entry table that resolves it, rather than arithmetic that would be wrong.
T_SHIP_F0 = 0               # rows 0..3: 32x32
T_SHIP_F1 = 4
T_HAZ_T0 = 8
T_HAZ_T1 = 12
T_PYL_T0 = 64               # rows 4..7: 32x32
T_PYL_T1 = 68
T_BURST_A = 72
T_BURST_B = 76
T_DIGIT = (128, 130, 132, 134, 136, 138, 140, 142,   # rows 8..9:   16x16
           160, 162)                                 # rows 10..11: 16x16
T_HAZ_T2 = 164
T_HAZ_T3 = 166
T_PYL_T2 = 168
T_PYL_T3 = 170
T_RETICLE = 172
T_BULLET = 174
T_LIFE_FULL = 192           # rows 12..13: 16x16
T_LIFE_EMPTY = 194


def encode_4bpp(px, ox: int, oy: int) -> bytes:
    """One 8x8 window of `px` -> 32 B SNES 4bpp (planes 0/1 interleaved per
    row, then planes 2/3). NO masking: an index outside 0..15 is a bug in the
    art, not something to silently quantise (the asset-codec rule)."""
    out = bytearray()
    for lo_hi in (0, 2):
        for row in range(8):
            b0 = b1 = 0
            for col in range(8):
                v = px[oy + row][ox + col]
                if not 0 <= v <= 15:
                    raise ValueError(f"palette index {v} at ({ox + col},"
                                     f"{oy + row}) is outside 4bpp 0..15")
                b0 |= ((v >> lo_hi) & 1) << (7 - col)
                b1 |= ((v >> (lo_hi + 1)) & 1) << (7 - col)
            out += bytes((b0, b1))
    return bytes(out)


def blank(n: int):
    return [[0] * n for _ in range(n)]


def draw_ship(lean: int):
    """A 32x32 delta-wing seen from behind. `lean` shears the hull sideways so
    the strafe frame reads as a bank rather than a slide."""
    p = blank(32)
    for y in range(32):
        sh = (lean * (31 - y)) // 12          # shear: strongest at the nose
        for x in range(32):
            dx = x - 16 + sh
            # wings: a triangle that opens toward the tail
            if 14 <= y <= 27 and abs(dx) <= (y - 13) * 1.35:
                p[y][x] = 2 if abs(dx) > (y - 13) * 0.75 else 3
            # hull: a narrow column running the whole length
            if 4 <= y <= 28 and abs(dx) <= 3 - (28 - y) // 12:
                p[y][x] = 3 if abs(dx) <= 1 else 2
            # canopy
            if 8 <= y <= 15 and abs(dx) <= 1:
                p[y][x] = 5 if y > 9 else 4
            # wingtip shadow
            if 24 <= y <= 27 and 5 < abs(dx) <= (y - 13) * 1.35:
                p[y][x] = 1
    # engines: two flares at the tail
    for ex in (-4, 4):
        for y in range(27, 31):
            for x in range(-2, 3):
                xx, yy = 16 + ex + x - (lean * (31 - y)) // 12, y
                if 0 <= xx < 32:
                    p[yy][xx] = 6 if abs(x) <= 1 and y < 30 else 7
    return p


def draw_hazard(size: int, radius: float):
    """An octagonal hazard block, drawn at `radius` inside a `size` frame.

    Four PRE-DRAWN size tiers are the rail's second lesson: the SNES cannot
    scale a sprite, so an object "grows" by swapping frames with distance.
    """
    p = blank(size)
    c = (size - 1) / 2.0
    for y in range(size):
        for x in range(size):
            dx, dy = abs(x - c), abs(y - c)
            d = max(dx, dy) * 0.62 + (dx + dy) * 0.38    # octagon metric
            if d <= radius:
                if d > radius - 1.1:
                    p[y][x] = 4                          # hot rim
                elif (x + y) % 5 < 2:
                    p[y][x] = 3                          # facet highlight
                elif d < radius * 0.45:
                    p[y][x] = 1                          # core shadow
                else:
                    p[y][x] = 2
    return p


def draw_reticle():
    """16x16 lock-on brackets: four corners plus a centre tick."""
    p = blank(16)
    for i in range(5):
        for (bx, by, sx, sy) in ((1, 1, 1, 1), (14, 1, -1, 1),
                                 (1, 14, 1, -1), (14, 14, -1, -1)):
            p[by][bx + sx * i] = 6
            p[by + sy * i][bx] = 6
    for i in (7, 8):
        p[i][7] = p[i][8] = 7
    return p


def draw_bullet():
    """16x16 tracer: a short bright bar with a soft tail."""
    p = blank(16)
    for y in range(4, 12):
        for x in range(6, 10):
            p[y][x] = 5 if 5 <= y <= 9 and 6 <= x <= 9 else 4
    p[3][7] = p[3][8] = 4
    p[12][7] = p[12][8] = 4
    return p


def draw_pylon(size: int, inset: int):
    """One SEGMENT of the obstacle column the rail's S-curve bends around.

    The column is a THREE-TALL STACK of this one frame, which is what makes it
    affordable: stacked sprites do not share scanlines, so a 32x96 structure
    costs ONE sprite and FOUR 8x8 slivers on any single scanline, where a wall
    four sprites wide would cost four and sixteen — and the per-scanline limit
    is 32 and 34, not the 128-entry table.

    The frame tiles vertically on purpose: repeating it three times gives an
    evenly-striped column that reads as one structure rather than three blocks.

    `inset` is what makes the four tiers PRE-DRAWN sizes rather than one frame
    shown at two hardware sizes: the slab narrows as the tier recedes, exactly
    as the hazard's octagon radius does.
    """
    p = blank(size)
    for y in range(size):
        for x in range(inset, size - inset):
            edge = x < inset + 2 or x >= size - inset - 2
            p[y][x] = 14 if edge else 13
    band = size // 4                             # the warning stripe
    for y in range(band, band + max(2, size // 8)):
        for x in range(inset + 1, size - inset - 1):
            p[y][x] = 15
    return p


def draw_burst(size: int, r_in: float, r_out: float):
    """The kill flash: a ring between r_in and r_out, hot core inside.

    Two frames — a small filled burst then a wide thin ring — are what make a
    kill NOT resemble a miss. A hazard that simply flies past
    produces neither frame, so the difference is in the rendered OAM and in the
    pixels, not in a variable.
    """
    p = blank(size)
    c = (size - 1) / 2.0
    for y in range(size):
        for x in range(size):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            if d <= r_in:
                p[y][x] = 11
            elif d <= r_out:
                p[y][x] = 12 if d > r_out - 1.6 else 11
    # four spokes, so the flash reads as an explosion rather than a dot
    for i in range(int(r_out) + 3):
        for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            x, y = int(c) + dx * i, int(c) + dy * i
            if 0 <= x < size and 0 <= y < size and i > r_in:
                p[y][x] = 12
    return p


def draw_life(full: bool):
    """One life-bar segment: a filled green block, or a dark-red empty frame.

    Both frames are the SAME shape, so a lost segment reads as a state change
    at a fixed position rather than as something disappearing.
    """
    p = blank(16)
    body, edge = (9, 5) if full else (10, 10)
    for y in range(3, 13):
        for x in range(1, 13):
            border = y in (3, 12) or x in (1, 12)
            p[y][x] = edge if border else body
    if not full:
        for y in range(5, 11):
            for x in range(3, 11):
                p[y][x] = 0                      # hollow: the segment is gone
    return p


# 7-segment masks, a..g = bit 0..6 (a top, b top-right, c bottom-right,
# d bottom, e bottom-left, f top-left, g middle). Segments beat a hand-drawn
# bitmap font here: ten digits from one geometry, and a wrong digit is a wrong
# MASK rather than a typo nobody can see.
DIGIT_SEG = (0b0111111, 0b0000110, 0b1011011, 0b1001111, 0b1100110,
             0b1101101, 0b1111101, 0b0000111, 0b1111111, 0b1101111)
SEG_BOX = {                       # (x0, y0, x1, y1) inclusive, in a 16x16 cell
    0: (4, 2, 11, 3),    1: (10, 3, 11, 7),   2: (10, 9, 11, 13),
    3: (4, 12, 11, 13),  4: (3, 9, 4, 13),    5: (3, 3, 4, 7),
    6: (4, 7, 11, 8),
}


def draw_digit(v: int):
    p = blank(16)
    for s in range(7):
        if not (DIGIT_SEG[v] >> s) & 1:
            continue
        x0, y0, x1, y1 = SEG_BOX[s]
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                p[y][x] = 8
    return p


def place(sheet, art, base_tile: int, claimed: set | None = None) -> None:
    """Blit `art` (a square index grid) into the 16-wide OBJ tile sheet at
    `base_tile`, in the {N, N+1, ..., N+16, ...} order the PPU reads.

    `claimed` accumulates every tile index written. Two frames sharing a tile
    is silent — the second simply wins and the first renders half of somebody
    else — and the {N, N+16} rule makes it easy to do by accident, so the
    caller asserts on this set rather than on a tile COUNT (an all-blank tile
    is indistinguishable from an unwritten one, which is what made a count
    wrong on the first try).
    """
    n = len(art) // 8
    for ty in range(n):
        for tx in range(n):
            tile = base_tile + ty * OBJ_GRID_W + tx
            if tile >= len(sheet):
                raise ValueError(f"frame at base {base_tile} runs off the sheet"
                                 f" (tile {tile} of {len(sheet)})")
            if claimed is not None:
                if tile in claimed:
                    raise ValueError(f"frame at base {base_tile} overwrites "
                                     f"tile {tile}, already claimed")
                claimed.add(tile)
            sheet[tile] = encode_4bpp(art, tx * 8, ty * 8)


def build_obj_chr() -> bytes:
    sheet = [bytes(OBJ_TILE_BYTES)] * OBJ_TILES
    cl: set[int] = set()
    place(sheet, draw_ship(0), T_SHIP_F0, cl)
    place(sheet, draw_ship(8), T_SHIP_F1, cl)       # the bank, H-flipped for
                                                    #   the other direction
    place(sheet, draw_hazard(32, 15.0), T_HAZ_T0, cl)  # tier 0 nearest/largest
    place(sheet, draw_hazard(32, 10.5), T_HAZ_T1, cl)  # tier 1
    place(sheet, draw_hazard(16, 7.5), T_HAZ_T2, cl)   # tier 2
    place(sheet, draw_hazard(16, 4.0), T_HAZ_T3, cl)   # tier 3 farthest
    place(sheet, draw_pylon(32, 4), T_PYL_T0, cl)   # the same four tiers, for
    place(sheet, draw_pylon(32, 9), T_PYL_T1, cl)   #   the column the S bends
    place(sheet, draw_pylon(16, 2), T_PYL_T2, cl)   #   around — narrowing as
    place(sheet, draw_pylon(16, 5), T_PYL_T3, cl)   #   it recedes, stacked 3x
    place(sheet, draw_burst(32, 5.0, 11.0), T_BURST_A, cl)
    place(sheet, draw_burst(32, 2.0, 15.0), T_BURST_B, cl)
    place(sheet, draw_reticle(), T_RETICLE, cl)
    place(sheet, draw_bullet(), T_BULLET, cl)
    place(sheet, draw_life(True), T_LIFE_FULL, cl)
    place(sheet, draw_life(False), T_LIFE_EMPTY, cl)
    for v in range(10):
        place(sheet, draw_digit(v), T_DIGIT[v], cl)
    # 8 frames x 16 tiles (32x32) + 18 frames x 4 tiles (16x16) = 200 tiles,
    # every one written exactly once (place() raises on a double claim). The
    # remaining 24 are the spare 16x16 slots on rows 12..13.
    assert len(sheet) == OBJ_TILES
    assert len(cl) == 8 * 16 + 18 * 4 == 200, len(cl)
    out = bytearray()
    for t in sheet:
        out += t
    return bytes(out)


def pal_bytes(words) -> bytes:
    out = bytearray()
    for w in words:
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("outdir", type=Path)
    a = ap.parse_args()
    a.outdir.mkdir(parents=True, exist_ok=True)

    plane = build_map()
    assert len(plane) == 0x8000, len(plane)
    (a.outdir / "rs_map.bin").write_bytes(plane)

    probe = build_map(probe=True)
    assert len(probe) == 0x8000, len(probe)
    (a.outdir / "rs_map_probe.bin").write_bytes(probe)

    fpal = pal_bytes(FLOOR_PAL)
    assert len(fpal) == 8, len(fpal)
    (a.outdir / "rs_floor_pal.bin").write_bytes(fpal)

    chr_sheet = build_obj_chr()
    assert len(chr_sheet) == OBJ_TILES * OBJ_TILE_BYTES == 7168, len(chr_sheet)
    (a.outdir / "rs_obj_chr.bin").write_bytes(chr_sheet)

    path = build_path()
    assert len(path) == 2 * PATH_N == 512, len(path)
    (a.outdir / "rs_path.bin").write_bytes(path)

    opal = pal_bytes(SHIP_PAL) + pal_bytes(HAZARD_PAL)
    assert len(opal) == 64, len(opal)
    (a.outdir / "rs_obj_pal.bin").write_bytes(opal)

    scan, scale = build_proj()
    assert len(scan) == PROJ_N == 81, len(scan)
    assert len(scale) == 2 * PROJ_N == 162, len(scale)
    (a.outdir / "rs_proj_scan.bin").write_bytes(scan)
    (a.outdir / "rs_proj_scale.bin").write_bytes(scale)

    print(f"rs_map.bin        {len(plane):6d} B  128x128 grid, 3 tiles")
    print(f"rs_map_probe.bin  {len(probe):6d} B  the MEASUREMENT plane: "
          f"magenta marks grid intersections and nothing else")
    print(f"rs_floor_pal.bin  {len(fpal):6d} B  "
          + " ".join(f"${w:04X}" for w in FLOOR_PAL))
    print(f"rs_obj_chr.bin    {len(chr_sheet):6d} B  {OBJ_TILES} tiles")
    print(f"rs_obj_pal.bin    {len(opal):6d} B  2 x 16 words")
    print(f"rs_proj_scan.bin  {len(scan):6d} B  y[0]={scan[0]} "
          f"y[{PROJ_N - 1}]={scan[-1]} horizon={HORIZON_Y}")
    print(f"rs_proj_scale.bin {len(scale):6d} B  "
          f"tier bands y = {[screen_y(t) for t in (TIER_T0, TIER_T1, TIER_T2)]}")
    print(f"rs_path.bin       {len(path):6d} B  {PATH_N} x s16, "
          f"amplitude {PATH_AMP} world px (S period = 256 frames, "
          f"one entry per frame)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
