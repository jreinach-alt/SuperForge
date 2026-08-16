"""railshooter — the REDESIGNED rail, proven in pixels and OAM.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)` — an
absolute frame by construction — and every drive is a fixed per-frame input
list, so the whole trajectory is a pure function of the replay triple.

WHAT THIS RAIL IS NOW. The engine layer is unchanged: a decoupled pinhole 1/z
projection, four PRE-DRAWN size tiers with a grow-only hysteresis, a
depth-sorted OAM emit with no sort, the `pool` contract, one wrapping Mode 7
plane, the sky split. The GAME layer is the spec's:

    G1  the ship is FIXED and flies ITSELF around a repeating S-curve
    G2  the curve is a TRANSLATION of the camera origin, never a pose rotation
    G3  the player controls ONE thing: a world-anchored aiming reticle, which
        the ship's swing DRAGS across the screen
    G4  the rail is slow enough to track an approaching hazard for seconds
    G5  a kill must not resemble a miss — a flash, and a score that moves
    G6  a hazard that reaches the ship costs exactly one of five life segments;
        at zero the rail fails and restarts itself

Every one is a named case below, and the state cycles the spec makes
mandatory are each driven end to end rather than sampled.

=============================================================================
HOW "THE CAMERA TRANSLATES AND THE POSE DOES NOT CHANGE" IS PROVEN (G2)
=============================================================================
This is the redesign's load-bearing constraint and it has no output byte of its
own — the pose lives in two HDMA pointer sets. So it is proven from the
RENDERED side, by the one asymmetry that separates the two implementations:

    `rs_project` is DECOUPLED FROM THE MODE 7 MATRIX. It reads `cam_x` and the
    baked LUT and nothing else. So a curve expressed as a POSE ROTATION would
    swing the floor while leaving every projected sprite exactly where it was;
    a curve expressed as a CAMERA TRANSLATION moves both.

The reticle, left alone, is a world-anchored point that never moves. Its
screen x therefore traces `cam_x` and only `cam_x`. Watching it sweep a full
sinusoid — centre, one extreme, centre, the other extreme — is a rendered
measurement of the camera's world position, and it is exactly what a
rotation-driven curve could not produce.

The second half is a stronger form of "nothing drifted": a full period is 256
frames and the rail advances 1.5 px/frame, so a period is exactly 384 world px
= TWELVE of the plane's 32-px grid periods, AND `cam_x` returns to the value it
started at. The floor one period later must therefore be BYTE-IDENTICAL. A pose
that had moved, or a forward advance that had drifted, breaks that equality.
(A HALF period does not qualify and the first draft of this case wrongly used
one: at a half period `cam_x` is MIRRORED about the rail's centre, not equal.)

Corroboration, and labelled as corroboration rather than as the assertion:
`ES_PERSP_IDX` is the WRAM index table the PPU's indirect HDMA fetches the
per-scanline matrix rows through — the transport the pose selects. It is
byte-identical across the whole period. (Structurally it could not be
otherwise: `persp_set_pose` is called once, from the scene's enter, and the
redesign deleted both the heading state and the NMI retarget that used to
write it — see main.asm's `sm_nmi_hook`.)

WHAT IS DELIBERATELY NOT READ. `US_CAM_X`, `US_LEAN`, `US_SCORE`, `US_LIVES`
and every pool `alive[]` all sit one call away — and reading them is the
proxy-variable move CLAUDE.md rule 2 forbids, because on every one of these the
question is whether the value REACHES the picture. The score is read as DIGIT
TILES, the lives as SEGMENT TILES, the pool as OAM ENTRIES, the curve as the
reticle's rendered x and the floor's pixels.

The one place a declared word IS read is the published pool census, and it is
read as the SUBJECT of its own case (the pool's own answer, compared against
the window that renders the same slots) rather than as evidence for something
else. The oracle reads the pool arrays too — as its INPUT, with the assertion
surface still the rendered OAM.

Power-on fidelity comes free rather than as a case: `Machine` seeds power-on
RAM, so every assertion below is made against a ROM booted from random memory,
and none of this rail's WRAM claims are `[init] zero`.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from machine import Machine, MemoryType                        # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "railshooter.sfc"
MAP = json.loads((BUILD / "rs" / "symbol_map.json").read_text())

O = MemoryType.SnesSpriteRam
C = MemoryType.SnesCgRam
W = MemoryType.SnesWorkRam

# --- the rail's declared geometry (game/railshooter/railshooter.inc) --------
# Named here so a wrong constant is a mismatch against the picture rather than
# a silent re-spelling of the source. OAM index order IS priority, and this
# list is front-to-back.
RET_SLOT = 0
BURST_SLOT = 1
SHIP_SLOT = 2
HAZ_SLOT0, HAZ_N = 3, 4
SHOT_SLOT0, SHOT_N = 7, 3
# The HUD is IN FRONT OF the pylons: lower index wins on this
# hardware, and the premise that let the HUD sit last -- "the two bands can
# never share a scanline" -- was false.
SCORE_SLOT0, SCORE_DIGITS = 10, 4
LIFE_SLOT0, LIFE_N = 14, 5
PYL_SLOT0, PYL_SLOTS = 22, 6
# Everything that is NOT the HUD — the reticle, the flash, the ship, the
# hazards, the tracers and the pylons. Not a contiguous range, because the HUD
# now sits between the tracers and the pylons.
PLAY_SLOTS = tuple(range(0, SCORE_SLOT0)) + \
    tuple(range(PYL_SLOT0, PYL_SLOT0 + PYL_SLOTS))

SHIP_X, SHIP_Y = 112, 150
T_SHIP_F0, T_SHIP_F1 = 0, 4
T_HAZ = (8, 12, 164, 166)            # tier 0 (nearest) .. tier 3 (farthest)
T_PYL = (64, 68, 168, 170)
T_BURST = (72, 76)
T_BULLET = 174
T_LIFE_FULL, T_LIFE_EMPTY = 192, 194
T_DIGIT = (128, 130, 132, 134, 136, 138, 140, 142, 160, 162)
ATTR_SHIP, ATTR_SHIP_FLIP = 0x30, 0x70

# The S-curve's shape, from railshooter.inc. One bend is half a period.
PATH_PERIOD = 256
PATH_QUARTER = PATH_PERIOD // 4
SCREEN_CENTRE = 128

# Mesen captures 239 rows and the visible frame starts 7 rows in: MEASURED, by
# finding the first row carrying a floor colour (row 51 = scanline 44, the
# split_band seam). Stated rather than assumed, because every band constant
# below rides on it.
ROW0 = 7
SEAM = 44
SKY_ROWS = (0, SEAM + ROW0)                      # rows 0..50
FLOOR_ROWS = (SEAM + ROW0, 224 + ROW0 - 1)       # rows 51..230
HUD_ROWS = (8 + ROW0, 24 + ROW0)                 # the HUD band, rows 15..30

# The floor's own palette (tools/gen_railshooter_assets.py FLOOR_PAL), as RGB
# after the PPU's 5-bit expansion. These are the colours the SKY may not show.
FLOOR_GRID = (66, 206, 239)          # the cyan grid line
FLOOR_MAJOR = (239, 99, 206)         # the magenta major line
# Where the smoothness case reads the plane. Near the BOTTOM of the floor band,
# because the pinhole's lateral gain grows with screen y and a held path entry
# shows up there first: the shipped 64-entry table stepped 21 px per lurch here
# against 9 at row 90.
FLOOR_SMOOTH_ROW = 200
# The life bar's two states (HAZARD_PAL indices 9 and 10).
LIFE_GREEN = (0, 255, 0)
# How many GREEN pixels one full life segment paints. MEASURED (the glyph is a
# 16x16 frame with a hollow border), and it is the constant that turns "the bar
# shows green" into "the bar shows ALL of its green" — see the occlusion case.
LIFE_SEG_GREEN_PX = 80
# Absolute frames, all past the fade-in.
BOOT = 120
# Where the read-before-write detector is sampled. It must start EARLY: the
# detector answers "is anything still unwritten and already consumed?", so the
# evidence for a pool read before its first spawn erases itself as the pools
# fill. The first pylon spawns at frame 128 and hazards on a 40-frame schedule,
# so frame 20 is the sample that actually bites and frame 400 is nearly blind.
UNINIT_LADDER = (20, 40, 60, 90, 120, 150, 200, 300, 400)


# --- helpers -----------------------------------------------------------------
def _sym(name, scene="rail"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} is not in the emitted map — did the allocator move it?")


@pytest.fixture
def rail():
    """A factory for Machines parked on an ABSOLUTE frame, which CLOSES every
    one it handed out at teardown.

    The Mesen2 core is a process-global singleton, so a module that leaves it
    parked strands the NEXT module's fresh runner and the red lands on the
    victim (AGENTS.md, "hand the core back"). A fixture rather than a `with`
    block per case because several cases here drive two trajectories from the
    same boot frame, and teardown must reach both even when the first
    assertion between them fails.
    """
    made = []

    def make(frames=BOOT, drives=()):
        m = Machine(str(ROM)).advance(frames)
        for n, pad in drives:
            m.advance(n, pad1=pad)
        made.append(m)
        return m

    yield make
    for m in reversed(made):
        m.close()


def _entry(oam, slot):
    """One OAM entry as (x, y, tile, attr, x9, size) — x9 and size from the
    HI TABLE, which is where the ninth x bit and the size select actually
    live. Reading the low table alone would miss both."""
    x, y, tile, attr = oam[slot * 4:slot * 4 + 4]
    pair = (oam[512 + (slot >> 2)] >> ((slot & 3) * 2)) & 3
    return x, y, tile, attr, pair & 1, (pair >> 1) & 1


def _oam(m):
    return m.read_bytes(O, 0, 544)


def _x9(oam, slot):
    """The sprite's full NINE-bit screen x, as a signed screen offset.

    OAM x is nine bits and the ninth lives in the hi table; a sprite hanging off
    the left edge has x9 set and a small low byte, so reading the low byte alone
    reports it on the RIGHT of the screen. Every lateral assertion in this file
    goes through here."""
    e = _entry(oam, slot)
    v = e[0] + 256 * e[4]
    return v - 512 if v >= 256 else v


def _emitted(oam, slot0, n):
    """A sub-window's EMITTED entries, in OAM slot order.

    A slot nothing wrote this frame is parked with tile 0 by rs_obj_disarm, so
    `tile != 0` is the emitted test. Slot order matters and is the whole point
    of the cases that use this — do not sort."""
    out = []
    for s in range(slot0, slot0 + n):
        e = _entry(oam, s)
        if e[2] != 0:
            out.append(e)
    return out


def _shot_entries(oam):
    return [_entry(oam, s) for s in range(SHOT_SLOT0, SHOT_SLOT0 + SHOT_N)]


def _shots_flying(oam):
    return [e for e in _shot_entries(oam) if e[2] == T_BULLET]


def _score_tiles(oam):
    """The four score digits as RENDERED TILE NUMBERS — the output region the
    score claims to produce, not the word it is stored in."""
    return tuple(_entry(oam, SCORE_SLOT0 + i)[2] for i in range(SCORE_DIGITS))


def _score_value(oam):
    """...and the same tiles decoded, so a case can say `+1` rather than
    compare opaque tile tuples. Still a read of the PICTURE."""
    v = 0
    for t in _score_tiles(oam):
        if t not in T_DIGIT:
            pytest.fail(f"score slot holds tile {t}, which is not a digit frame")
        v = v * 10 + T_DIGIT.index(t)
    return v


def _life_tiles(oam):
    return tuple(_entry(oam, LIFE_SLOT0 + i)[2] for i in range(LIFE_N))


def _life_full(oam):
    """How many life segments RENDER as full. Both frames are drawn at the same
    place, so this counts a state change and not something vanishing."""
    return sum(1 for t in _life_tiles(oam) if t == T_LIFE_FULL)


def _live(m, sym):
    """One of the rail's published pool counts, addressed through the EMITTED
    map rather than a literal — the test-side of the rule
    `allocator/no_literals.py` enforces in ASM."""
    return m.read_u16(W, _sym(sym)["start"])


def _img(m, tmp_path, name):
    return Image.open(m.screenshot(str(tmp_path / f"{name}.png"))).convert("RGB")


def _diff_frac(a, b, rows):
    pa, pb = a.load(), b.load()
    y0, y1 = rows
    n = (y1 - y0) * a.width
    return sum(1 for y in range(y0, y1) for x in range(a.width)
               if pa[x, y] != pb[x, y]) / n


# The Mode 7 plane's own four colours (FLOOR_PAL, after the PPU's 5-bit
# expansion). A pixel showing one of these is the PLANE; anything else in the
# floor band is an OBJ drawn over it.
FLOOR_COLOURS = frozenset({(24, 16, 66), (16, 24, 58),
                           (66, 206, 239), (239, 99, 206)})


def _plane_diff(a, b, rows):
    """(differing, compared) over the pixels where the PLANE is visible in BOTH
    images.

    The sprites in the floor band are excluded deliberately: the actor field's
    spawn schedule is 40 frames and does not divide the 256-frame S period, so
    the ACTORS are legitimately in different places one period apart. What must
    return is the PLANE, and this measures exactly that.
    """
    pa, pb = a.load(), b.load()
    y0, y1 = rows
    differing = compared = 0
    for y in range(y0, y1):
        for x in range(a.width):
            ca, cb = pa[x, y], pb[x, y]
            if ca in FLOOR_COLOURS and cb in FLOOR_COLOURS:
                compared += 1
                differing += ca != cb
    return differing, compared


def _colours(img, rows):
    px = img.load()
    y0, y1 = rows
    return {px[x, y] for y in range(y0, y1) for x in range(img.width)}


def _count_colour(img, rows, rgb):
    px = img.load()
    y0, y1 = rows
    return sum(1 for y in range(y0, y1) for x in range(img.width)
               if px[x, y] == rgb)


def _play_sprite_crossing_the_hud(oam):
    """The first PLAY-window slot whose sprite covers a HUD scanline, or None.

    The PPU's own range rule — a sprite covers line L iff `((L - y) & 0xFF) < h`
    — so this sees the 8-bit y WRAP the pylon's top segment relies on, which is
    exactly the case the "disjoint bands" premise missed. Sizes
    come from the hi table against OBSEL mode 3: small = 16x16, large = 32x32.
    """
    # The play window is NOT one contiguous range any more: a later change put the
    # HUD in the middle of it, so the pylons — the very sprites that reach these
    # scanlines — sit AFTER the bar. Scanning `range(0, SCORE_SLOT0)` would miss
    # exactly the case this helper exists for.
    for s in PLAY_SLOTS:
        e = _entry(oam, s)
        if e[2] == 0:
            continue
        h = 32 if e[5] else 16
        for line in range(HUD_ROWS[0] - ROW0, HUD_ROWS[1] - ROW0):
            if ((line - e[1]) & 0xFF) < h:
                return s
    return None


# --- an INDEPENDENT projection oracle ----------------------------------------
# The rail's pinhole, recomputed in Python from the SAME two LUT blobs the ROM
# reads and the rail's own declared constants — a second implementation, not a
# re-reading of the first. It exists because the lateral half of the projection
# is otherwise unobservable at the OAM layer: a sign fault leaves the slot
# emitted, the tile right, the order right and the size right, and only moves
# the sprite.
#
# ITS STATED LIMIT, unchanged from the shipped rail: it is
# independent of the ROM's ARITHMETIC but NOT of its LUT INPUTS. Both sides read
# rs_proj_scan.bin and rs_proj_scale.bin, so a wrong perspective curve in the
# generator would be invisible to it. That is what the structural sawtooth case
# and the committed renders are for.
#
# Reading the pool arrays HERE is not the proxy move rule 2 forbids: they are
# the oracle's INPUT, and the assertion surface is still the rendered OAM.
PROJ_SCAN = (BUILD / "assets" / "rs_proj_scan.bin").read_bytes()
PROJ_SCALE = (BUILD / "assets" / "rs_proj_scale.bin").read_bytes()
WORLD_PX, WORLD_MASK = 1024, 1023
Z_FAR, Q_LOG2 = 640, 3
CENTRE_OFF = {8: 16, 12: 16, 164: 8, 166: 8}
LARGE_TILES = (8, 12)
POOL_STRIDE = 16                 # 8 slots x 2 B per field (railshooter.inc)
OBS_BASE, PYL_BASE = 0, 4 * POOL_STRIDE


def _pool(m, base, field_index, n):
    """One parallel array of one pool, as words."""
    start = _sym("ES_RS_ACTORS")["start"] + base + field_index * POOL_STRIDE
    raw = m.read_bytes(W, start, n * 2)
    return [raw[i * 2] | (raw[i * 2 + 1] << 8) for i in range(n)]


def _project(wx, z, cam_x):
    """The oracle: 65816 arithmetic, spelled out, including its truncations."""
    if z == 0 or z > Z_FAR:
        return None
    bucket = min(z >> Q_LOG2, len(PROJ_SCAN) - 1)
    sy = PROJ_SCAN[bucket]
    scale = PROJ_SCALE[bucket * 2] | (PROJ_SCALE[bucket * 2 + 1] << 8)
    dx = (wx - cam_x) & WORLD_MASK
    if dx >= WORLD_PX // 2:
        dx -= WORLD_PX
    term = ((abs(dx) * scale) >> 8) & 0xFFFF       # the word at ACC+1
    if dx < 0:
        term = (-term) & 0xFFFF
    return (term + SCREEN_CENTRE) & 0xFFFF, sy


def _expected_hazards(m):
    """The hazard window the depth-sorted emit must produce: tier 0..3, and
    within a tier in ascending pool-slot order."""
    cam_x = m.read_u16(W, _sym("US_CAM_X")["start"])
    alive, wx, z, tier = (_pool(m, OBS_BASE, i, HAZ_N) for i in range(4))
    out = []
    for want in range(len(T_HAZ)):
        for k in range(HAZ_N):
            if not alive[k] or tier[k] != want:
                continue
            p = _project(wx[k], z[k], cam_x)
            if p is None:
                continue
            tile = T_HAZ[want]
            sx = (p[0] - CENTRE_OFF[tile]) & 0xFFFF
            out.append((sx & 0xFF, p[1], tile, (sx >> 8) & 1,
                        1 if tile in LARGE_TILES else 0))
    return out


# --- driving the pad the way a pilot does ------------------------------------
def _target(oam):
    """The nearest hazard ON SCREEN, as (slot, x9, y, tile) — nearest meaning
    the lowest tier, which is also the lowest OAM slot the depth-sorted emit
    gave it. Returns None when the window is empty."""
    live = [(s, _x9(oam, s)) + tuple(_entry(oam, s)[1:3])
            for s in range(HAZ_SLOT0, HAZ_SLOT0 + HAZ_N)
            if _entry(oam, s)[2] != 0]
    if not live:
        return None
    return min(live, key=lambda h: T_HAZ.index(h[3]))


def _steer_onto_target(m, max_frames=120):
    """Fly the reticle onto the nearest hazard using only what is ON SCREEN.

    This is the pilot's loop, and driving it from rendered positions rather
    than from world state is the point: it exercises the d-pad -> world aim ->
    projection -> screen path end to end, so a reversed axis or a broken drag
    cannot pass. Returns the frame count it took, or None if it never landed.
    """
    for step in range(max_frames):
        oam = _oam(m)
        tgt = _target(oam)
        if tgt is None:
            m.advance(1)
            continue
        _, tx, ty, tile = tgt
        half = 16 if tile in LARGE_TILES else 8
        rcx, rcy = _x9(oam, RET_SLOT) + 8, _entry(oam, RET_SLOT)[1] + 8
        pad = {}
        if tx + half - rcx > 4:
            pad["right"] = True
        elif rcx - (tx + half) > 4:
            pad["left"] = True
        if ty + half - rcy > 4:
            pad["down"] = True
        elif rcy - (ty + half) > 4:
            pad["up"] = True
        if not pad:
            return step
        m.advance(1, pad1=pad)
    return None


def _fire_once(m):
    """One rising edge on A: press for a frame, release for a frame.

    The release is not decoration — `rs_fire` reads the PRESS edge, so holding
    A spawns exactly one shot no matter how long it is held, and a second shot
    needs a real release in between."""
    m.advance(1, pad1={"a": True})
    m.advance(1)


# =============================================================================
# G2 — THE CURVE. A full S period, both bends, translation and not rotation.
# =============================================================================
def test_the_camera_translates_across_a_full_s_period_and_the_floor_returns(rail, tmp_path):
    """The spec's first mandatory cycle, driven across a FULL period.

    The reticle is left alone, so its world position never changes and its
    RENDERED screen x is a measurement of `cam_x` and nothing else. A curve
    expressed as a pose rotation would leave it pinned at screen centre for the
    whole period, because `rs_project` does not read the heading.

    Sampled every EIGHTH of a period, nine samples, so the last one closes the
    loop on the first. The boot frame is not phase-aligned to the sine and does
    not need to be: every assertion below is a statement about the SHAPE (a
    full-period return, a half-period mirror, a span) rather than about
    absolute phase.
    """
    STEP = PATH_PERIOD // 8
    # TWO trajectories, and they are separate ON PURPOSE: `screenshot()` costs
    # one emulated frame, so a capture taken inside the sampling loop shifts
    # every later sample's phase by one frame relative to where it would
    # otherwise land. That is invisible in `dist` (which is read from WRAM) and
    # visible in OAM (which parks one frame behind), so it presents as "the
    # curve drifted 10 px over a period" when nothing drifted at all. Measured
    # while writing this case; recorded in the friction log.
    m = rail(BOOT)
    xs = []
    for k in range(9):
        xs.append(_x9(_oam(m), RET_SLOT))
        if k < 8:
            m.advance(STEP)

    # --- the camera TRANSLATES, and it does so in BOTH directions -----------
    lo, hi = min(xs), max(xs)
    assert hi - lo > 100, (
        f"the reticle's rendered x barely moved across a full S period "
        f"({lo}..{hi}, samples {xs}). It is a world-anchored point projected by "
        f"a pinhole that never reads the heading, so this IS the camera's world "
        f"displacement — a span this small means the curve is not translating "
        f"the camera at all.")
    assert lo < SCREEN_CENTRE < hi, (
        f"the reticle swept {lo}..{hi}, entirely on one side of screen centre "
        f"({SCREEN_CENTRE}) — that is one bend, not an S. the spec asks "
        f"for a REPEATING S and §3 asks the test to drive both bends.")

    # --- it is a SINE that crosses over, not a drift or a wobble ------------
    # Any two samples a HALF period apart are the same phase negated, so the
    # reticle must sit on opposite sides of centre at every such pair. This is
    # the "both bends" claim stated as a shape rather than as two lucky
    # samples, and it holds whatever phase the boot frame lands on.
    for i in range(4):
        a, b = xs[i] - SCREEN_CENTRE, xs[i + 4] - SCREEN_CENTRE
        if abs(a) <= 3 and abs(b) <= 3:
            continue                       # both at the crossing: no sign to test
        assert a * b < 0, (
            f"samples {i} and {i + 4} are a half period apart at {xs[i]} and "
            f"{xs[i + 4]} — both on the same side of centre. The path is not "
            f"crossing over, so it is a wobble, not an S. All: {xs}")

    # --- a FULL period returns the camera exactly ---------------------------
    assert xs[0] == xs[8], (
        f"the reticle did not return to its starting screen x after a full "
        f"period: {xs[0]} -> {xs[8]}. The S-curve is drifting rather than "
        f"repeating. All: {xs}")

    # --- and so does the floor, to the byte ---------------------------------
    # A full period is 256 frames at 1.5 px/frame = 384 world px = exactly
    # TWELVE of the plane's 32-px grid periods, and cam_x returns to the same
    # value, so the floor must be byte-identical. A pose that had moved, or a
    # forward advance that had drifted, breaks this. Captured on its own
    # Machine so the captures cannot perturb the sampling above.
    f = rail(BOOT)
    a = _img(f, tmp_path, "phase0")
    f.advance(2 * STEP - 1)                 # -1: the capture above cost a frame
    b = _img(f, tmp_path, "phase2")
    f.advance(6 * STEP - 1)
    c = _img(f, tmp_path, "phase8")
    differing, compared = _plane_diff(a, c, FLOOR_ROWS)
    assert compared > 20000, (
        f"only {compared} plane pixels were comparable between the two frames "
        f"— the floor band is mostly covered, so this case is not measuring "
        f"the plane")
    assert differing == 0, (
        f"{differing} of {compared} plane pixels differ after one full S "
        f"period: the camera did not return to the same world position, or "
        f"something other than the S-curve is moving the plane")
    moved, seen = _plane_diff(a, b, FLOOR_ROWS)
    assert moved > 0.2 * seen, (
        f"only {moved} of {seen} plane pixels changed between the start of the "
        f"period and a quarter in — the camera translation is not reaching the "
        f"Mode 7 origin")


def test_the_curve_moves_the_picture_every_frame_and_never_in_lurches(rail, tmp_path):
    """The curve must be SMOOTH, not merely present.

    The case above proves the camera translates and returns. It is blind to
    HOW the translation is delivered, and the shipped redesign delivered it at
    15 Hz: 64 baked entries held four frames each with no interpolation, so the
    whole Mode 7 plane stood perfectly still for three frames and then jumped
    up to 21 screen px sideways, forever, on the rail's headline mechanic. Every
    acceptance criterion as literally worded still passed. The owner's original
    complaint about this rail was that the turning "just jumps from one state to
    the next", so a stepped curve is the ONE regression this change cannot ship.

    Two rendered surfaces, because they fail together and are read differently:

      A  the RETICLE's OAM x, hands-off, every frame of a full period. It is a
         world-anchored point projected by a pinhole that never reads the
         heading, so its screen x IS `cam_x` — sampled at frame resolution.
      B  the PLANE's own pixels: the magenta major grid line's x centroid near
         the bottom of the screen, where the perspective gain is largest and a
         held table entry is most visible. This is what the pilot actually sees
         judder, and no OAM read can stand in for it.

    A stationary moment is NOT a defect — the sine genuinely rests at its two
    extremes — so the assertion is not "it moves every frame" but "a pause means
    the camera is at rest, not that a table entry is being held": every still
    frame must be followed by a SMALL step. Under the coarse table the step
    after a still frame was 10 px on the aim and 21 on the floor; it is now 2
    and 6, and the six remaining pauses sit at the sine's two extremes.
    """
    # --- A: the aim point, every frame of a full period ---------------------
    m = rail(BOOT)
    xs = []
    for _ in range(PATH_PERIOD + 1):
        xs.append(_x9(_oam(m), RET_SLOT))
        m.advance(1)
    d = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    moving = sum(1 for v in d if v)

    assert moving >= 0.6 * PATH_PERIOD, (
        f"the rendered aim moved on only {moving} of {PATH_PERIOD} frames "
        f"({100 * moving // PATH_PERIOD}%). The camera's lateral position is "
        f"being held across frames — a path table sampled once every K frames "
        f"caps this at about 1/K, and the shipped 64-entry table measured 25%. "
        f"deltas: {d[:32]}")
    assert max(abs(v) for v in d) <= 5, (
        f"the rendered aim jumped {max(abs(v) for v in d)} px in ONE frame. "
        f"The S-curve is being delivered in steps rather than continuously. "
        f"deltas: {d[:32]}")

    # A pause is only legitimate if the camera is genuinely at rest there, so
    # every still frame must be followed by a SMALL step — not by a lurch.
    for i, v in enumerate(d):
        if v:
            continue
        j = i + 1
        while j < len(d) and d[j] == 0:
            j += 1
        if j >= len(d):
            break
        assert abs(d[j]) <= 3, (
            f"the aim stood still at frame index {i} and then moved "
            f"{abs(d[j])} px — a held table entry, not a camera at rest. That "
            f"is the 15 Hz judder a later review measured; deltas: {d[i - 2:j + 2]}")

    # --- B: the PLANE itself, over consecutive frames mid-bend --------------
    # An absolute frame by construction, chosen to sit off the sine's extremes
    # so the window is genuinely in motion; the travel guard below refuses to
    # let this case pass by measuring a stationary moment.
    f = rail(300)
    cent = []
    for k in range(16):
        px = _img(f, tmp_path, f"smooth{k:02d}").load()
        hits = [x for x in range(256) if px[x, FLOOR_SMOOTH_ROW] == FLOOR_MAJOR]
        assert hits, (
            f"no major grid line on screen row {FLOOR_SMOOTH_ROW} at capture "
            f"{k} — this case is not measuring the plane")
        cent.append(sum(hits) / len(hits))
    steps = [cent[i + 1] - cent[i] for i in range(len(cent) - 1)]

    assert sum(abs(s) for s in steps) >= 30, (
        f"the plane travelled only {sum(abs(s) for s in steps):.1f} px across "
        f"{len(steps)} frames — the window is stationary, so this case is not "
        f"measuring smoothness. centroids: {cent}")
    assert max(abs(s) for s in steps) <= 12, (
        f"the Mode 7 plane moved {max(abs(s) for s in steps):.1f} px sideways "
        f"in ONE frame at screen row {FLOOR_SMOOTH_ROW}. The floor is lurching, "
        f"which is what a held path entry looks like at the bottom of the "
        f"screen (the shipped 64-entry table measured 21.0). steps: {steps}")
    still = sum(1 for s in steps if s == 0)
    assert still <= 5, (
        f"the plane was completely still on {still} of {len(steps)} frames in a "
        f"window it travels {sum(abs(s) for s in steps):.1f} px across — it is "
        f"moving in bursts, not continuously. steps: {steps}")


def test_the_pose_transport_is_untouched_for_a_whole_s_period(rail):
    """CORROBORATION for the case above, and labelled as such.

    `ES_PERSP_IDX` is the WRAM index table the PPU's INDIRECT HDMA fetches each
    scanline's Mode 7 matrix row through — it is the transport a pose change
    would have to move, not a game variable. Byte-identity across a full period
    says the plane's orientation was never retargeted.

    This is not the primary instrument (the rendered case above is); it is here
    because the primary instrument proves the POSITIVE claim ("the camera
    translates") directly and this one closes the negative claim ("and the pose
    did not change") against the closest readable hardware state.

    BOTH halves of the transport are read, and the second is why this case is
    not half-armed. `persp_set_pose` writes the index-table
    pointers from `heading & 31` and the two channels' DASB BANK bytes from
    `heading >> 5` (`mode7_persp.asm:96-127`), so a heading that moved by a
    multiple of 32 would leave `ES_PERSP_IDX` byte-identical and change only the
    banks — invisible to an index-table read alone.
    """
    idx, hdma = _sym("ES_PERSP_IDX"), _sym("ES_SM_HDMA", None)   # rail / global
    m = rail(BOOT)

    def transport():
        return (m.read_bytes(W, idx["start"], idx["size"]),
                m.read_bytes(W, hdma["start"], hdma["size"]))

    first = transport()
    seen = [first]
    for _ in range(8):
        m.advance(PATH_QUARTER)
        seen.append(transport())
    assert all(s[0] == first[0] for s in seen), (
        "the perspective HDMA index table moved during the S-curve — the pose "
        "is being retargeted, which is exactly what the spec forbids")
    assert all(s[1] == first[1] for s in seen), (
        "the Mode 7 HDMA channel descriptors moved during the S-curve. "
        "`persp_set_pose` writes the two pose blobs' DASB bank bytes from "
        "heading >> 5, so this is a pose retarget by a multiple of 32 headings "
        "— the half of the transport the index table cannot see")


def test_the_ship_banks_into_each_bend_and_the_floor_does_not_rotate(rail, tmp_path):
    """The ship's lean is the curve made legible ON THE SHIP.

    It is driven by the PATH's slope, not by input, so across a period it must
    show BOTH lean frames — and the straight frame between them. Read as the
    ship's OAM tile and attribute, which is where the frame and the H-flip
    actually live."""
    m = rail(BOOT)
    seen = set()
    for _ in range(PATH_PERIOD + 8):
        e = _entry(_oam(m), SHIP_SLOT)
        seen.add((e[2], e[3]))
        m.advance(1)
    assert (T_SHIP_F1, ATTR_SHIP) in seen, "the ship never banked one way"
    assert (T_SHIP_F1, ATTR_SHIP_FLIP) in seen, "the ship never banked the other"
    assert (T_SHIP_F0, ATTR_SHIP) in seen, (
        "the ship never flew straight — the bank has no neutral, so it reads "
        "as a permanent tilt rather than as banking into a bend")


def test_the_ship_holds_station_under_every_direction_of_the_pad(rail):
    """G1/the spec: the ship is FIXED and does not respond to input AT ALL.

    Driven on every axis including the diagonals, because "does not respond" is
    a claim about the whole pad and a single-axis check would lock one axis and
    ship the others. Read as the ship's own OAM entry."""
    pads = [{}, {"left": True}, {"right": True}, {"up": True}, {"down": True},
            {"left": True, "up": True}, {"right": True, "down": True},
            {"a": True}, {"left": True, "a": True}]
    for pad in pads:
        m = rail(BOOT, drives=((30, pad),))
        x, y, _, _, x9, size = _entry(_oam(m), SHIP_SLOT)
        assert (x, y, x9, size) == (SHIP_X, SHIP_Y, 0, 1), (
            f"holding {pad or 'nothing'} for 30 frames moved the ship to "
            f"({x + 256 * x9},{y}); it must stay planted at ({SHIP_X},{SHIP_Y})")


# =============================================================================
# G3 — THE DRAG, and correcting it. the spec's second mandatory cycle.
# =============================================================================
def test_the_swing_drags_the_reticle_and_the_d_pad_corrects_it_back(rail):
    """The whole of the spec's skill demand, driven as one cycle:
    ship swings -> the reticle's SCREEN position moves although the player
    touched nothing -> the d-pad brings it back onto a target.

    The drag half is measured with NO input at all, which is what makes it a
    drag rather than a control test."""
    m = rail(BOOT)
    x0 = _x9(_oam(m), RET_SLOT)
    m.advance(PATH_QUARTER)                 # a quarter period, hands off
    x1 = _x9(_oam(m), RET_SLOT)
    assert abs(x1 - x0) > 30, (
        f"the reticle moved only {abs(x1 - x0)} px in a quarter of an S period "
        f"with NO input — the ship's swing is not dragging it, so there is "
        f"nothing for the pilot to compensate for")

    # ...and now the pad takes it back onto a target, using only what is on
    # screen. This is the control half, and it closes the cycle.
    took = _steer_onto_target(m)
    assert took is not None, (
        "the d-pad could not bring the reticle onto a hazard within 120 "
        "frames — the pad has less authority than the drag, which is the "
        "failure mode the spec exists to prevent")
    oam = _oam(m)
    tgt = _target(oam)
    half = 16 if tgt[3] in LARGE_TILES else 8
    rcx, rcy = _x9(oam, RET_SLOT) + 8, _entry(oam, RET_SLOT)[1] + 8
    assert abs(rcx - (tgt[1] + half)) <= 8 and abs(rcy - (tgt[2] + half)) <= 8, (
        f"the steering loop declared success at reticle ({rcx},{rcy}) but the "
        f"target's centre is ({tgt[1] + half},{tgt[2] + half})")


@pytest.mark.parametrize("pad,axis,want", [
    ({"left": True}, "x", -1),
    ({"right": True}, "x", +1),
    ({"up": True}, "y", -1),
    ({"down": True}, "y", +1),
])
def test_each_d_pad_direction_moves_the_reticle_the_right_way(rail, pad, axis, want):
    """Input tied to the VISIBLE result, end to end (test-authoring rule 8).

    A self-consistent-but-reversed mapping passes any "the variable changed"
    check; this drives the physical pad and reads the sprite's rendered
    position. The camera drift over 20 frames is far smaller than the pad's
    authority, so the sign is unambiguous.

    UP pushes the aim point further down the rail, which the pinhole renders
    HIGHER on screen (toward the horizon) — hence want = -1 on y."""
    m = rail(BOOT)
    oam0 = _oam(m)
    before = _x9(oam0, RET_SLOT) if axis == "x" else _entry(oam0, RET_SLOT)[1]
    m.advance(20, pad1=pad)
    oam1 = _oam(m)
    after = _x9(oam1, RET_SLOT) if axis == "x" else _entry(oam1, RET_SLOT)[1]
    moved = after - before
    assert moved * want > 0 and abs(moved) >= 8, (
        f"holding {pad} for 20 frames moved the reticle's rendered {axis} by "
        f"{moved}; expected a move of at least 8 px in direction {want}")


# =============================================================================
# G5 — A HIT IS LEGIBLE, AND A KILL DOES NOT RESEMBLE A MISS
# =============================================================================
def test_firing_on_target_destroys_it_flashes_and_moves_the_score(rail):
    """The spec's third mandatory cycle, end to end: target present -> fire
    -> the target is visibly gone -> the score moves.

    Every step is read from the picture: the hazard window before and after,
    the burst slot's tile, and the score's DIGIT TILES."""
    m = rail(BOOT)
    assert _steer_onto_target(m) is not None, "could not acquire a target"
    oam0 = _oam(m)
    tgt = _target(oam0)
    before_window = {(e[0], e[1], e[2]) for e in
                     _emitted(oam0, HAZ_SLOT0, HAZ_N)}
    score0 = _score_value(oam0)

    _fire_once(m)
    oam1 = _oam(m)

    assert _entry(oam1, BURST_SLOT)[2] in T_BURST, (
        f"no kill flash in the burst slot after firing on a target; it holds "
        f"tile {_entry(oam1, BURST_SLOT)[2]}. the spec: a destroyed hazard "
        f"must leave via a distinct visible event")

    # ...and it is OVER THE WRECK, which nothing asserted before.
    # "A flash happened" is satisfied by a flash in the corner of the screen,
    # and a flash the pilot cannot associate with the thing they shot is not the
    # feedback the spec asks for. Both boxes are read from the rendered OAM
    # and compared at their CENTRES, because the burst is 32x32 over a target
    # that is 32 or 16 (`rs_kill` pulls the flash back by RS_BURST_OFF at the two
    # small tiers to centre it).
    b = _entry(oam1, BURST_SLOT)
    bcx, bcy = _x9(oam1, BURST_SLOT) + 16, b[1] + 16
    thalf = 16 if tgt[3] in LARGE_TILES else 8
    tcx, tcy = tgt[1] + thalf, tgt[2] + thalf
    assert abs(bcx - tcx) <= 12 and abs(bcy - tcy) <= 12, (
        f"the kill flash rendered centred at ({bcx}, {bcy}) but the hazard it "
        f"killed was last rendered centred at ({tcx}, {tcy}) — the burst is not "
        f"pinned to the wreck, so the pilot cannot tell WHAT they hit")

    assert _score_value(oam1) == score0 + 1, (
        f"the rendered score went {score0} -> {_score_value(oam1)} on a kill")
    after_window = {(e[0], e[1], e[2]) for e in
                    _emitted(oam1, HAZ_SLOT0, HAZ_N)}
    assert (tgt[2], tgt[3]) not in {(y, t) for _, y, t in after_window}, (
        "the hazard that was hit is still in the rendered window unchanged")
    assert len(after_window) < len(before_window) or after_window != before_window


def test_a_kill_and_a_miss_are_distinguishable_in_the_rendered_output(rail):
    """The shipped rail's CORE failure, and the spec's fourth mandatory
    cycle. Its hit test worked and was invisible: a killed hazard was recycled
    to the horizon, which looks exactly like one that flew past.

    Two runs from the same boot frame, differing ONLY in whether the reticle is
    on a target when A is pressed. The rendered difference must be
    unmistakable — not a subtle one."""
    # --- the KILL run --------------------------------------------------------
    hit = rail(BOOT)
    assert _steer_onto_target(hit) is not None
    hit_score0 = _score_value(_oam(hit))
    _fire_once(hit)
    hit_oam = _oam(hit)
    hit_burst = _entry(hit_oam, BURST_SLOT)[2]
    hit_score = _score_value(hit_oam)
    hit_shots = len(_shots_flying(hit_oam))

    # --- the MISS run: same boot, aim parked well off any target ------------
    miss = rail(BOOT)
    # push the aim to the far end of its depth range, where the field is not
    miss.advance(90, pad1={"up": True})
    miss.advance(60, pad1={"left": True})
    miss_score0 = _score_value(_oam(miss))
    _fire_once(miss)
    miss_oam = _oam(miss)
    miss_burst = _entry(miss_oam, BURST_SLOT)[2]
    miss_score = _score_value(miss_oam)
    miss_shots = len(_shots_flying(miss_oam))

    assert hit_burst in T_BURST and miss_burst == 0, (
        f"the kill flash does not separate the two: kill run burst tile "
        f"{hit_burst}, miss run burst tile {miss_burst}. If both are the same "
        f"the pilot cannot tell a hit from a miss, which is the exact defect "
        f"the spec was written about")
    assert hit_score == hit_score0 + 1 and miss_score == miss_score0, (
        f"the score does not separate the two: kill {hit_score0}->{hit_score}, "
        f"miss {miss_score0}->{miss_score}")
    assert hit_shots >= 1 and miss_shots >= 1, (
        "a tracer must fly on EVERY press — if it only flew on a hit, the "
        "tracer itself would be the feedback and a miss would look like a "
        "dead trigger")


def test_a_hazard_that_flies_past_unshot_produces_no_flash_and_no_score(rail):
    """The other half of "a kill does not resemble a miss": the SILENT case.

    A whole hazard approach and departure with no input at all must leave the
    burst slot parked and the score digits unmoved — so that when a flash does
    appear, it means something."""
    m = rail(BOOT)
    score0 = _score_tiles(_oam(m))
    bursts, scores = set(), set()
    for _ in range(200):                    # more than one full approach
        oam = _oam(m)
        bursts.add(_entry(oam, BURST_SLOT)[2])
        scores.add(_score_tiles(oam))
        m.advance(1)
    assert bursts == {0}, (
        f"a kill flash appeared without a shot being fired: tiles {bursts}")
    assert scores == {score0}, (
        f"the score moved without a shot being fired: {scores}")


# =============================================================================
# G6 — DAMAGE, THE LIFE BAR, AND THE FAIL STATE
# =============================================================================
def test_a_hazard_reaching_the_ship_costs_exactly_one_life_segment(rail):
    """The spec's fifth mandatory cycle, first half — and EXACTLY one is the
    load-bearing word. Read as the rendered life-segment tiles, sampled every
    frame so a two-segment drop cannot hide inside a coarse sample."""
    m = rail(60)
    seen = [_life_full(_oam(m))]
    for _ in range(400):
        m.advance(1)
        n = _life_full(_oam(m))
        if n != seen[-1]:
            seen.append(n)
        if len(seen) >= 4:
            break
    assert len(seen) >= 3, (
        f"the life bar never lost two segments in 400 frames ({seen}) — "
        f"nothing is reaching the ship, so the damage path is not driven")
    for a, b in zip(seen, seen[1:]):
        assert b == a - 1, (
            f"the bar went {a} -> {b}: a hazard reaching the ship must cost "
            f"EXACTLY one segment. Sequence: {seen}")


def test_five_hits_empty_the_bar_and_the_rail_restarts_itself(rail, tmp_path):
    """The whole failure cycle, driven end to end: five segments lost one at a
    time -> the bar renders EMPTY -> the rail restarts itself with five back.

    Also captures the three renders the spec's last mandatory item asks for
    (the bar at 5, mid, and 0) as a by-product of driving the cycle, so they
    are the same run rather than three staged ones."""
    m = rail(BOOT)                          # past the fade: the renders this
    marks, order = {}, []                   #   captures have their real colours
    for _ in range(1200):
        n = _life_full(_oam(m))
        if not order or n != order[-1]:
            order.append(n)
            if n in (5, 3, 0) and n not in marks:
                marks[n] = _img(m, tmp_path, f"bar{n}")
        m.advance(1)

    assert order[:6] == [5, 4, 3, 2, 1, 0], (
        f"the bar did not empty one segment at a time: {order[:8]}")
    assert 5 in order[6:], (
        f"the rail never restarted itself after the bar emptied: {order} — "
        f"the spec asks for a self-restarting fail state so the demo loops")
    for want in (5, 3, 0):
        assert want in marks, f"never rendered the bar at {want}"

    # ...and the three renders are genuinely different pictures in the HUD band
    assert _diff_frac(marks[5], marks[3], HUD_ROWS) > 0.0
    assert _diff_frac(marks[3], marks[0], HUD_ROWS) > 0.0
    # the full bar shows the segment green; the empty bar must not
    assert LIFE_GREEN in _colours(marks[5], HUD_ROWS), (
        "the full life bar does not render its green segment colour at all")
    assert LIFE_GREEN not in _colours(marks[0], HUD_ROWS), (
        "the EMPTY life bar still shows the full segment's green — a pilot "
        "cannot see that they are out")


def test_the_fail_state_clears_the_field_and_the_rail_returns(rail):
    """The fail state is a still, empty rail rather than a frozen mess: every
    hazard and pylon slot parked, the HUD still rendering. Read as the OAM
    windows."""
    m = rail(2)
    for _ in range(1200):
        if _life_full(_oam(m)) == 0:
            break
        m.advance(1)
    else:
        pytest.fail("never reached the fail state")
    m.advance(20)
    oam = _oam(m)
    assert _emitted(oam, HAZ_SLOT0, HAZ_N) == [], (
        "hazards are still rendered during the fail state")
    assert _emitted(oam, PYL_SLOT0, PYL_SLOTS) == [], (
        "pylons are still rendered during the fail state")
    assert _life_tiles(oam) == (T_LIFE_EMPTY,) * LIFE_N
    assert all(_entry(oam, SCORE_SLOT0 + i)[2] in T_DIGIT
               for i in range(SCORE_DIGITS)), (
        "the score stopped rendering during the fail state")


# =============================================================================
# G4 — THE RAIL, SLOWED. And the field it bends around.
# =============================================================================
def test_a_hazard_is_trackable_for_seconds_as_it_crosses_the_screen(rail):
    """the spec: "an object is trackable for seconds, not an instant".

    Measured as the number of FRAMES a single hazard is continuously rendered
    between the horizon band and the near band, read from its OAM y — not from
    a speed constant, which would be a proxy for the thing being claimed."""
    m = rail(BOOT)
    ys, frames = [], 0
    for _ in range(400):
        emitted = _emitted(_oam(m), HAZ_SLOT0, HAZ_N)
        near = [e for e in emitted if e[2] in (T_HAZ[0], T_HAZ[1])]
        if near:
            ys.append(max(e[1] for e in near))
            frames += 1
        m.advance(1)
    assert frames >= 120, (
        f"a hazard was in the two NEAR tiers for only {frames} frames of 400 "
        f"— under two seconds of the approach is spent large enough to aim at")
    assert max(ys) - min(ys) > 60, (
        f"the near-tier hazards only covered {max(ys) - min(ys)} scanlines; "
        f"they are not descending toward the ship")


def test_the_rail_advances_by_itself_and_the_floor_is_never_static(rail, tmp_path):
    """G4/R1: the ground rushes toward you with no input and never stops. Read
    as FLOOR PIXELS across three widely separated instants."""
    m = rail(BOOT)
    a = _img(m, tmp_path, "rail_a")
    m.advance(7)
    b = _img(m, tmp_path, "rail_b")
    m.advance(7)
    c = _img(m, tmp_path, "rail_c")
    for lhs, rhs, label in ((a, b, "0->7"), (b, c, "7->14")):
        frac = _diff_frac(lhs, rhs, FLOOR_ROWS)
        assert frac > 0.02, (
            f"the floor changed in only {frac:.1%} of its pixels over {label} "
            f"frames — the rail has stopped advancing")


def test_the_pylon_the_curve_bends_around_reaches_the_near_band(rail, tmp_path):
    """the spec: the curve must be LEGIBLE ON THE SPRITE LAYER — the player
    has to see WHAT the ship is swinging around.

    Read as the pylon window's rendered entries: the column must reach a NEAR
    tier (its 32x32 frames), stand more than one segment tall, and be laterally
    off the ship's own column at that moment.

    THE LATERAL CLAUSE IS ASSERTED, not just promised. A test name
    — and a docstring — is a contract; that clause sat unchecked, and it is the
    half that carries the spec's actual demand. A pylon the ship flies
    straight THROUGH is not something the pilot sees it swinging around, and a
    column pinned to the ship's own screen x would satisfy every other assertion
    here.

    WHICH MOMENT it is asserted at is the whole subtlety, and getting it wrong
    reads as a rail defect. The pylon stands on the rail's CENTRE column, so
    while it is still distant it sits near screen centre — MEASURED at x≈117 at
    tier 1, overlapping the ship's column — and it is the ship's own swing that
    carries it past as it grows. So the claim belongs on the NEAREST tier: at
    tier 0, where the column is 32x96 and unmissable, the ship's centre must
    not be inside it. Measured, it sweeps 79 -> -211 across its tier-0 pass
    while the ship holds x=112, i.e. 17 px of clearance at the tightest.
    """
    m = rail(BOOT)
    best = None
    nearest_x = []
    for _ in range(PATH_PERIOD + 64):
        oam = _oam(m)
        segs = _emitted(oam, PYL_SLOT0, PYL_SLOTS)
        near = [e for e in segs if e[2] in (T_PYL[0], T_PYL[1])]
        nearest_x += [_x9(oam, s) for s in range(PYL_SLOT0, PYL_SLOT0 + PYL_SLOTS)
                      if _entry(oam, s)[2] == T_PYL[0]]
        if len(near) > (len(best) if best else 0):
            best = near
            m.screenshot(str(tmp_path / "pylon_near.png"))
        m.advance(1)
    assert best is not None, (
        "the pylon never reached a near tier in a full S period — there is "
        "nothing on the sprite layer for the pilot to see the ship avoiding")
    assert len(best) >= 3, (
        f"the pylon rendered only {len(best)} segment(s) at its nearest — a "
        f"single block does not read as the structure the rail bends around")
    assert all(e[5] == 1 for e in best), (
        "the near pylon segments are not rendering at the large hardware size")
    ys = sorted(e[1] for e in best)
    assert ys[-1] - ys[0] >= 32 * (len(best) - 1) - 1, (
        f"the pylon's segments are not stacked into a column: y = {ys}")

    # ...and at its NEAREST the ship is not inside it: the swing carried it past.
    assert nearest_x, (
        "the pylon never reached its nearest tier in a full S period, so the "
        "'flies around it' claim was never put to the test")
    ship_cx = SHIP_X + 16
    through = [x for x in nearest_x if x <= ship_cx < x + 32]
    assert not through, (
        f"on {len(through)} frame(s) the nearest pylon's 32-px column contained "
        f"the ship's own centre (x={ship_cx}); it rendered at x = "
        f"{sorted(set(through))[:8]}. The ship flies THROUGH the structure it is "
        f"supposed to be swinging around — the spec asks the pilot to see "
        f"WHAT it is avoiding, and a column the ship passes through reads as a "
        f"target it failed to dodge")


def test_no_pylon_segment_is_emitted_into_the_bottom_of_the_screen(rail):
    """The stack's top segment goes to a NEGATIVE screen y and `rs_put` stores
    the low byte, so the PPU renders it wrapped.

    That is arithmetically correct while the true top is > -32: the wrapped part
    landing on scanlines 0..k is exactly the part of the column at true y 0..k,
    which is why the column reads as continuous off the top of the frame. But
    the margin is thin and was undocumented — the smallest wrapping y the audit
    observed was 233, and a 32-tall sprite starts painting at the BOTTOM of the
    screen once its y is <= 223. Nine scanlines. One more stack segment, or a
    near-band `sy` shifted down ten pixels, and a 32-px slab of pylon appears at
    the bottom of the frame with nothing above it.

    So the constraint gets a name and a test: no emitted pylon segment may land
    in [192, 223], the band where a wrapped segment would be visibly detached.
    Anything at 224+ is the legitimate off-the-top wrap; anything below 192 is
    an honest on-screen position.
    """
    m = rail(BOOT)
    bad = []
    for f in range(PATH_PERIOD + 64):
        oam = _oam(m)
        for s in range(PYL_SLOT0, PYL_SLOT0 + PYL_SLOTS):
            e = _entry(oam, s)
            if e[2] != 0 and 192 <= e[1] <= 223:
                bad.append((f, s, e[1], e[2]))
        m.advance(1)
    assert not bad, (
        f"{len(bad)} pylon segment(s) were emitted with a screen y in "
        f"[192, 223], where the 8-bit OAM y wrap puts a detached slab at the "
        f"bottom of the frame instead of a column running off the top. "
        f"First few (frame, slot, y, tile): {bad[:6]}")


# =============================================================================
# THE KEPT ENGINE LAYER — unchanged mechanisms, re-proven against the new game
# =============================================================================
def test_the_hazard_window_is_depth_ordered_on_every_frame(rail):
    """R5: nearer hazards take LOWER OAM slots and therefore draw in front.
    The order invariant, checked on every frame of a long run rather than
    sampled: no farther hazard may sit at a lower slot than a nearer one."""
    m = rail(BOOT)
    for f in range(240):
        window = _emitted(_oam(m), HAZ_SLOT0, HAZ_N)
        tiers = [T_HAZ.index(e[2]) for e in window]
        assert tiers == sorted(tiers), (
            f"frame {f}: the hazard window is out of depth order, tiers "
            f"{tiers} at slots {HAZ_SLOT0}.. — a farther hazard is drawing in "
            f"front of a nearer one")
        m.advance(1)


def test_the_hazard_window_matches_an_independent_projection_oracle(rail):
    """The whole declared window against a SECOND implementation, every frame.

    This is the case that sees a defect the picture cannot: a sign fault in the
    lateral projection leaves the slot emitted, the tile right, the order right
    and the size right, and only moves the sprite."""
    m = rail(BOOT)
    for f in range(90):
        want = _expected_hazards(m)
        m.advance(1)                       # OAM parks one advance behind WRAM
        got = [(e[0], e[1], e[2], e[4], e[5])
               for e in _emitted(_oam(m), HAZ_SLOT0, HAZ_N)]
        assert got == want, f"frame {f}: window {got} != oracle {want}"


def test_all_four_pre_drawn_tiers_render_at_their_hardware_size(rail):
    """R4: the SNES cannot scale a sprite, so an object grows by swapping
    between four PRE-DRAWN frames. Read as the OAM tile AND the hi-table SIZE
    bit, which is where the 16x16 / 32x32 select actually lives."""
    m = rail(BOOT)
    seen = {}
    for _ in range(PATH_PERIOD):
        for e in _emitted(_oam(m), HAZ_SLOT0, HAZ_N):
            seen.setdefault(e[2], set()).add(e[5])
        m.advance(1)
    assert set(seen) == set(T_HAZ), (
        f"only tiers {sorted(seen)} ever rendered; all four of {T_HAZ} must")
    for tile, sizes in seen.items():
        want = 1 if tile in LARGE_TILES else 0
        assert sizes == {want}, (
            f"tier tile {tile} rendered with size bits {sizes}, expected "
            f"{{{want}}} — the pre-drawn frame and the hardware size disagree")


def test_a_hazard_descends_from_the_horizon_to_the_near_band(rail):
    """R3: the pinhole maps depth to a scanline, so an approach is a monotone
    descent. Read as the sawtooth in the window's lowest rendered y."""
    m = rail(BOOT)
    ys = []
    for _ in range(320):
        window = _emitted(_oam(m), HAZ_SLOT0, HAZ_N)
        ys.append(max((e[1] for e in window), default=None))
        m.advance(1)
    runs, cur = [], []
    for y in ys:
        if y is None:
            continue
        if cur and y < cur[-1]:
            runs.append(cur)
            cur = []
        cur.append(y)
    runs.append(cur)
    good = [r for r in runs if len(r) > 20 and r[0] < 110 and r[-1] > 150]
    assert good, (
        f"no hazard made a monotone descent from above scanline 110 to below "
        f"150; run extents were {[(r[0], r[-1], len(r)) for r in runs]}")


def test_the_pool_allocates_flies_frees_and_reuses_the_slot(rail):
    """POOL, the pool contract, driven as a whole cycle on the tracers:
    allocate -> active -> free -> the slot REUSED. Read as the tracer slots'
    OAM tiles and y, never as `alive[]`."""
    m = rail(BOOT)
    m.advance(30, pad1={"left": True})      # aim off the field so it flies free
    _fire_once(m)
    m.advance(1)
    flying = [s for s in range(SHOT_SLOT0, SHOT_SLOT0 + SHOT_N)
              if _entry(_oam(m), s)[2] == T_BULLET]
    assert flying, "firing produced no tracer in the shot window"
    slot = flying[0]
    y0 = _entry(_oam(m), slot)[1]

    ys = [y0]
    for _ in range(40):
        m.advance(1)
        e = _entry(_oam(m), slot)
        if e[2] != T_BULLET:
            break
        ys.append(e[1])
    else:
        pytest.fail(f"the tracer in slot {slot} never freed (y trace {ys})")
    assert min(ys) < y0, "the tracer never climbed toward the horizon"
    assert _entry(_oam(m), slot)[2] == 0, "the freed slot is not parked"

    _fire_once(m)
    m.advance(1)
    reused = _entry(_oam(m), slot)
    assert reused[2] == T_BULLET, (
        f"the freed slot {slot} was not reused by the next shot; it holds "
        f"tile {reused[2]}")


def test_a_full_tracer_pool_swallows_the_extra_press(rail):
    """The pool's FULL path: three slots, four presses, three tracers."""
    m = rail(BOOT)
    m.advance(30, pad1={"left": True})
    for _ in range(SHOT_N + 1):
        _fire_once(m)
    m.advance(1)
    oam = _oam(m)
    flying = _shots_flying(oam)
    assert len(flying) == SHOT_N, (
        f"{len(flying)} tracers rendered from {SHOT_N + 1} presses into a "
        f"{SHOT_N}-slot pool; the extra press must be swallowed")


def test_the_published_pool_count_matches_the_actors_on_screen(rail):
    """`pool_count`'s two callers, across a whole fill-and-drain cycle.

    The published counts are the SUBJECT here, not evidence for something else:
    each is compared against the OAM window that renders the same slots. ORDER
    MATTERS — `rs_pool_census` writes before `rs_draw` and the harness parks OAM
    one advance behind WRAM, so the counts are read FIRST and the window one
    frame later."""
    m = rail(BOOT)
    m.advance(30, pad1={"left": True})

    def sample(label):
        shots = _live(m, "US_SHOTS_LIVE")
        hazards = _live(m, "US_HAZARDS_LIVE")
        m.advance(1)
        oam = _oam(m)
        assert shots == len(_shots_flying(oam)), (
            f"{label}: published shots_live={shots} but "
            f"{len(_shots_flying(oam))} tracers render")
        assert hazards == len(_emitted(oam, HAZ_SLOT0, HAZ_N)), (
            f"{label}: published hazards_live={hazards} but "
            f"{len(_emitted(oam, HAZ_SLOT0, HAZ_N))} hazards render")

    sample("idle")
    for i in range(SHOT_N):
        _fire_once(m)
        sample(f"fill {i + 1}")
    sample("saturated")
    for i in range(60):
        m.advance(1)
        if i % 15 == 0:
            sample(f"drain {i}")


def test_the_sky_band_and_the_floor_are_disjoint_in_colour(rail, tmp_path):
    """R6: the Mode 7 floor and the Mode 1 sky band are two different modes
    either side of the split_band seam. Read as screenshot colour sets."""
    m = rail(BOOT)
    img = _img(m, tmp_path, "bands")
    sky = _colours(img, SKY_ROWS)
    floor = _colours(img, FLOOR_ROWS)
    assert FLOOR_GRID in floor and FLOOR_MAJOR in floor, (
        "the floor band is not showing the Mode 7 grid's own colours")
    assert FLOOR_GRID not in sky and FLOOR_MAJOR not in sky, (
        f"a floor colour is bleeding above the seam at scanline {SEAM}")


@pytest.mark.parametrize("blob,first_word,count", [
    ("rs_obj_pal.bin", 128, 32),
])
def test_the_palette_blob_lands_in_cgram_byte_for_byte(rail, blob, first_word, count):
    """The asset upload's DESTINATION region, read directly and compared to the
    source bytes — necessary because a silent no-op in the upload path passes
    every downstream check (that class of defect)."""
    src = (BUILD / "assets" / blob).read_bytes()
    m = rail(BOOT)
    got = m.read_bytes(C, first_word * 2, count * 2)
    assert bytes(got) == src[:count * 2], (
        f"{blob} did not land at CGRAM word {first_word}")


def test_the_rail_reads_no_uninitialised_wram(rail):
    """CLAUDE.md rule 5, checked with the instrument that can see it.

    Power-on RAM is random here, so a routine that reads a word before anything
    wrote it consumes garbage. The rail used to: `rs_cache_one` loaded WX, Z
    and TIER and ran the projection BEFORE testing `alive`, so every dead pool
    slot read three words spawn had never written — 38 flagged reads in 400
    frames, against 0 for `m7_oshoot` and `racer`, which build on the SAME pool
    contract. Nothing reached the picture, because `RSC_VIS` is stamped 0 and
    both consumers gate on it, which is exactly why no rendered-output case
    here could see it and why this one exists alongside them rather than
    instead.

    The sharp edge it removes: the garbage tier indexed a 24-byte descriptor
    table unmasked, an out-of-bounds read on every dead slot every frame.

    This is also what lets `rs_obj/feature.toml` keep declining `[init] zero` on
    `rs_actors` honestly — the argument for not pre-zeroing is that the arrays
    are never read before they are written, and this is that claim under test
    rather than asserted.

    SAMPLED ON A LADDER, AND THE EARLY SAMPLES ARE THE ONLY STRONG ONES.
    `get_uninitialized_reads()` recomputes `WriteCounter == 0 and ReadCounter
    > 0` from the CURRENT counters, so it answers "is anything still unwritten
    and already consumed?" — not "did a read-before-write ever happen?". Those
    diverge here: a dead slot's fields are read from frame 0 and are WRITTEN the
    moment that slot first spawns, so the evidence erases itself as the pools
    fill. The first draft of this case sampled frame 400 alone and the
    `rail-reads-the-pool-before-checking-alive` plant walked straight past it —
    measured on the planted ROM, the count decays 36 (frame 20) → 30 → 24 → 18
    → 12 → 6 → 0 by frame 300. The harness reported it TEST-BLIND, which is
    exactly what that plant exists to do.
    """
    m = rail(UNINIT_LADDER[0])
    seen = []
    for i, frame in enumerate(UNINIT_LADDER):
        if i:
            m.advance(frame - UNINIT_LADDER[i - 1])
        found = m.get_uninitialized_reads()
        total = sum(len(v) for v in found.values())
        seen.append((frame, total))
        assert total == 0, (
            f"at frame {frame} the rail had read {total} byte(s) that nothing "
            f"wrote since power-on: "
            f"{ {str(k): [hex(a) for a in v[:12]] for k, v in found.items()} }. "
            f"On real hardware those are DRAM garbage, not zeroes. `m7_oshoot` "
            f"and `racer` both measure 0 over the same window. Ladder so far: "
            f"{seen}")


def test_the_hud_is_never_occluded_by_the_play_field(rail, tmp_path):
    """The life bar must show ALL of its green, including on the frames a play
    sprite shares its scanlines.

    Four places used to assert that "the HUD band and the play band cannot
    share a scanline". That is FALSE: the pylon's ground point cannot reach the
    sky band, but its SPRITE extends 96 px above that point, and the premise
    reasoned about the wrong object. Measured here: a play-window sprite crosses
    HUD scanlines 8..23 on about a tenth of all frames.

    The premise was load-bearing — it is what justified giving the HUD the
    LAST slots in the window, behind the pylons, on the grounds that "the
    priority never arises". So the real invariant gets a test instead of a
    premise, and it is a PIXEL invariant rather than a box one: a full segment
    paints LIFE_SEG_GREEN_PX green pixels, so the bar's rendered green must be
    exactly that times the number of segments the OAM tiles say are full. A
    pylon drawn over a segment removes green and this goes red; the existing
    life-bar case would not notice, because it only asks whether the colour is
    present at all — and on the empty-bar assertion an occluding pylon would
    actually HELP it pass.

    Both regimes are exercised and the case refuses to pass without seeing the
    crossing one, so it cannot quietly degrade into "the HUD is fine when
    nothing is near it".
    """
    m = rail(BOOT)
    crossing = clear = 0
    for f in range(240):
        oam = _oam(m)
        slot = _play_sprite_crossing_the_hud(oam)
        want = (slot is not None and crossing < 6) or \
               (slot is None and clear < 3 and f % 40 == 0)
        if not want:
            m.advance(1)
            continue
        n0 = _life_full(oam)
        img = _img(m, tmp_path, f"hudclear{f:03d}")
        if _life_full(_oam(m)) != n0:
            continue            # a segment dropped across the capture: skew
        green = _count_colour(img, HUD_ROWS, LIFE_GREEN)
        assert green == LIFE_SEG_GREEN_PX * n0, (
            f"frame {f}: the OAM tiles say {n0} life segment(s) are full, which "
            f"is {LIFE_SEG_GREEN_PX * n0} green pixels, but the HUD band renders "
            f"{green}. " + (f"Play-window slot {slot} is on the HUD's scanlines "
                            f"and is drawing OVER the bar." if slot is not None
                            else "Something is eating the bar with nothing near it."))
        if slot is None:
            clear += 1
        else:
            crossing += 1

    assert crossing >= 3, (
        f"only {crossing} frame(s) with a play sprite on the HUD's scanlines "
        f"were checked — this case is not exercising the overlap it exists for")
    assert clear >= 2, f"only {clear} clear-band control frame(s) were checked"
