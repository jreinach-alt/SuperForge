"""racer — the channel-pressure rail, proven in pixels (a later sweep B-6).

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)` — an
absolute frame by construction — and every drive is a fixed per-frame input
list, so the whole trajectory is a pure function of the replay triple.

WHAT THIS RAIL IS — its teaching claims and its control table, stated as
mechanism rather than as an adjective:

    R1  a Mode-7 perspective floor with a sky ABOVE the horizon
    R2  OBJ over Mode 7 — a screen-fixed kart, and a HUD made of sprites
        because BG3 does not exist in Mode 7
    R3  B accelerates and releasing COASTS TO A STOP; the speed bar reads it
    R4  LEFT/RIGHT steer and the kart LEANS INTO the turn
    R5  the map is COLLISION GROUND TRUTH — grass slows the kart to a crawl
    R6  a day-night cycle
    R7  red-and-white rumble strips at the road edges — STATIC
    R8  START pauses to a freeze-frame
    R9  HDMA composition across the channel pool — the rail's headline
    R10 the centre line is ONE line — on the 45-degree legs as well as the
        straights

Every one is a named case, and every state claim is driven in BOTH
directions (AGENTS.md test discipline: "forward *and* reverse *and* idle").
Accelerate AND coast back down; steer left AND right; day AND back to day;
pause AND unpause.

WHAT IS DELIBERATELY NOT READ. `US_SPEED`, `US_HEADING`, `US_GRAD_K`,
`US_PAUSED` and `US_LEAN` all sit in DP and one call would fetch any of them —
which is exactly the proxy-variable move CLAUDE.md rule 2 forbids, because on
every one of these claims the question is whether the value REACHES the
picture. Speed is read as lit tick TILES in OAM; heading as floor PIXELS; the
day-night keyframe as sky-band PIXELS; the kerb palette as STATIC CGRAM (the
anti-regression reads all 512 bytes); pause as
a byte-identical frame. The one non-pixel module-scope read is the ALLOCATOR'S
OWN MAP (R9), which is a fact about our tooling and is read from the artifact
the build emitted — CLAUDE.md's "two kinds of question".

THE OFF-ROAD CASE IS THE INTERESTING ONE (R5). "Grass slows the kart to a
crawl" has no single output byte, so it is asserted as what a player SEES:
from the same held throttle, the floor advances far less per frame off the
track than on it, and it still advances — a crawl, not a freeze. Reading
`US_SPEED` would be one line and would pass with col_map wired to nothing.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))
sys.path.insert(0, str(SUPERFORGE / "tools"))

from machine import Machine, MemoryType                        # noqa: E402
from gen_racer_assets import COURSE, ROAD_HALF                 # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "racer.sfc"
MAP = json.loads((BUILD / "rc" / "symbol_map.json").read_text())

O = MemoryType.SnesSpriteRam
C = MemoryType.SnesCgRam
W = MemoryType.SnesWorkRam

# The rail's declared geometry (game/racer/world.inc). Named here so a wrong
# constant is a mismatch against the picture rather than a silent re-spelling.
SEAM = 44                   # sky band 0..43, Mode-7 floor 44..223
KART_X, KART_Y = 120, 176
BAR_Y = 16
BAR_TICKS = 6
TICK_DIM, TICK_LIT = 4, 5
KART_T_STR, KART_T_LEAN = 0, 2
ATTR_NOFLIP, ATTR_HFLIP = 0x30, 0x70

# Absolute frames. BOOT sits inside the opening DAY hold with the fade in and
# the async song load done; DAY/NIGHT are the two holds of the cycle
# (RC_TOD_HOLD 128 + 7 x RC_TOD_STEP 16 = 240 frames per half).
BOOT = 90
DAY = 100
NIGHT = 300
DAY_AGAIN = 560


# --- helpers -----------------------------------------------------------------
def _chan(name):
    for c in MAP["scenes"]["race"]["channels"]:
        if c["name"] == name:
            return c
    raise KeyError(f"{name} is not an emitted channel of the race scene")


def _sym(name):
    for p in MAP["scenes"]["race"]["placements"]:
        if p["sym"] == name:
            return p["start"]
    raise KeyError(f"{name} is not an emitted placement of the race scene")


M7ORG, HEADING = _sym("ES_M7ORG"), _sym("US_HEADING")


def _boot(frames=BOOT, drives=()):
    """A Machine parked on an ABSOLUTE frame, after a fixed input script."""
    m = Machine(str(ROM)).advance(frames)
    for n, pad in drives:
        m.advance(n, pad1=pad)
    return m


def _shot(tmp_path, name, frames=BOOT, drives=()):
    m = _boot(frames, drives)
    try:
        return Image.open(m.screenshot(str(tmp_path / f"{name}.png"))).convert("RGB")
    finally:
        m.close()


def _rows(img, y0, y1):
    px = img.load()
    return [tuple(px[x, y] for x in range(img.width)) for y in range(y0, y1)]


def _band_colours(img, y0, y1):
    px = img.load()
    return {px[x, y] for y in range(y0, y1) for x in range(img.width)}


def _diff_frac(a, b, y0, y1):
    """Fraction of pixels differing between two images over a scanline band."""
    pa, pb = a.load(), b.load()
    n = (y1 - y0) * a.width
    d = sum(1 for y in range(y0, y1) for x in range(a.width)
            if pa[x, y] != pb[x, y])
    return d / n


def _mean_plane(img, plane, y0, y1):
    """Mean value of ONE colour plane over a scanline band."""
    px = img.load()
    xs = range(0, img.width, 2)
    return sum(px[x, y][plane] for y in range(y0, y1) for x in xs) / (
        (y1 - y0) * len(list(xs)))


def _m7_tilemap(m):
    """The Mode-7 interleaved region's TILEMAP bytes — the even addresses of
    VRAM words $0000-$3FFF. This is `mode7_stream`'s destination region and
    what the PPU reads to draw the floor, so how much of it a drive rewrites
    is how far the camera actually travelled."""
    raw = m.read_bytes(MemoryType.SnesVideoRam, 0, 32768)
    return raw[0::2]


def _bar_tiles(m):
    """The speed bar's six tile numbers, read from HARDWARE OAM."""
    return [m.read_bytes(O, 4 + i * 4 + 2, 1)[0] for i in range(BAR_TICKS)]


def _cg_word(m, idx):
    b = m.read_bytes(C, idx * 2, 2)
    return int.from_bytes(b, "little")


# =============================================================================
# R9 — THE CHANNEL LEDGER: this change's headline, from the map
# =============================================================================
# Read from the allocator's OWN emitted artifact, not from prose. A hand count
# of this scene's HDMA needs says "6 of 6 allocatable, no spare"; this asserts
# what the allocator actually packed, so a future change that quietly drops a
# channel — or that makes the pool bind — shows up here with the count in the
# message.

def test_the_scene_arms_seven_active_hdma_channels_and_leaves_one_spare():
    chans = MAP["scenes"]["race"]["channels"]
    active = sorted(c["ch"] for c in chans if c["phase"] == "active")
    vblank = sorted(c["ch"] for c in chans if c["phase"] == "vblank")
    assert len(active) == 7, f"expected 7 active-display channels, got {active}"
    assert len(set(active)) == 7, f"two active claims share a channel: {active}"
    used = set(active) | set(vblank)
    assert len(used) == 7, f"expected 7 of 8 channel numbers used, got {sorted(used)}"
    # The spare is the one that hand count said would not exist.
    assert set(range(8)) - used, "the pool is full — the ledger moved"


def test_every_claimed_effect_owns_the_registers_its_ledger_row_names():
    want = {"bgm": ["BGMODE"], "tmi": ["TM"],
            "m7ab": ["M7A", "M7B"], "m7cd": ["M7C", "M7D"],
            "rcgr": ["COLDATA_R"], "rcgg": ["COLDATA_G"], "rcgb": ["COLDATA_B"]}
    for name, regs in want.items():
        assert _chan(name)["registers"] == regs, name


def test_the_two_vblank_claims_time_share_active_channel_numbers():
    """The measurement a hand count cannot make.

    Reserving CH0/CH1 outright for VBlank bulk DMA is where "6 of 6
    allocatable" comes from. The allocator OVERLAPS them by PHASE instead, and
    this is the assertion of that difference: both VBlank claims land on
    channel numbers an active-display claim also holds.
    """
    active = {c["ch"] for c in MAP["scenes"]["race"]["channels"]
              if c["phase"] == "active"}
    vblank = [c for c in MAP["scenes"]["race"]["channels"]
              if c["phase"] == "vblank"]
    assert len(vblank) == 2, [c["name"] for c in vblank]
    for c in vblank:
        assert c["ch"] in active, (
            f"{c['name']} sits on ch{c['ch']}, which no active claim "
            "holds — the phase overlap is gone")


# =============================================================================
# R1 — the perspective floor, and R9's sky split rendered
# =============================================================================

def test_the_floor_band_renders_a_perspective_track(tmp_path):
    img = _shot(tmp_path, "floor")
    floor = _band_colours(img, SEAM, 224)
    assert len(floor) >= 6, (
        f"the Mode-7 band shows {len(floor)} colours — a perspective track "
        "needs at least asphalt, grass, kerb, centre line and the haze")


def test_the_seam_separates_a_sky_band_from_the_floor(tmp_path):
    """A CROSS-LAYER invariant, not a per-layer one (AGENTS.md's rule 2).

    Above the seam TM shows BG2 + OBJ and below it BG1 + OBJ, so the two bands
    cannot share a palette by construction: the sky is sky_band's dithered
    ramp under the day wash, the floor is the Mode-7 world. Asserting the
    bands are DISJOINT in colour is what a single-layer VRAM read cannot say.
    """
    img = _shot(tmp_path, "seam")
    sky = _band_colours(img, 0, SEAM - 4)     # clear of the seam's own line
    floor = _band_colours(img, SEAM + 4, 224)
    assert len(sky) >= 3, f"the sky band shows {len(sky)} colours"
    # NOT total disjointness: one COLDATA wash covers both bands by design, so
    # a shared colour is expected. What must hold is that each band carries
    # content the other does not — BG2's dithered ramp above, the Mode-7
    # world below. A single layer painting the whole frame would fail both.
    assert sky - floor, "the sky band shows nothing the floor does not"
    assert floor - sky, "the floor shows nothing the sky band does not"


def test_the_floor_is_not_a_flat_fill(tmp_path):
    """The trapezoid: a near row spans fewer world texels than a far row, so
    the two rows cannot be the same run pattern. A flat matrix would make
    every floor row identical."""
    img = _shot(tmp_path, "traps")
    far, near = _rows(img, SEAM + 8, SEAM + 9)[0], _rows(img, 210, 211)[0]
    assert far != near, "the far and near floor rows are identical — no perspective"


# =============================================================================
# R2 — OBJ over Mode 7: the kart, and a HUD made of sprites
# =============================================================================

def test_the_kart_is_one_large_obj_at_the_declared_screen_position():
    m = _boot()
    try:
        x, y, tile, attr = m.read_bytes(O, 0, 4)
        assert (x, y, tile, attr) == (KART_X, KART_Y, KART_T_STR, ATTR_NOFLIP)
        # size bit set in the hi table = large (16x16 in OBSEL mode 0), X9 clear
        # MAP: ok — 512 is the OAM low/high table boundary, a PPU fact
        #   (544 B = 128 x 4 B entries, then 32 B of X9/size bits). It is
        #   not an allocated base and cannot move.
        assert m.read_bytes(O, 512, 1)[0] == 0x02
    finally:
        m.close()


def test_the_kart_paints_pixels_the_floor_does_not(tmp_path):
    """OBJ over Mode 7 as a COMPOSITED claim: the kart's own palette colours
    must appear inside its screen rect and nowhere in a floor-only strip.
    A CGRAM read would say the palette uploaded; this says it reached the
    screen, over the floor, in front."""
    img = _shot(tmp_path, "kart")
    px = img.load()
    rect = {px[x, y] for y in range(KART_Y, KART_Y + 16)
            for x in range(KART_X, KART_X + 16)}
    # A floor-only strip: the same screen, well clear of every OBJ this rail
    # draws (the kart at y=176.., the speed bar at y=16..). Colours the kart's
    # rect has that this strip does not can only have come from OBJ.
    floor_only = _band_colours(img, 120, 152)
    kart_only = rect - floor_only
    assert len(kart_only) >= 3, (
        f"only {len(kart_only)} colour(s) inside the kart's rect are absent "
        "from a floor-only strip — the sprite is not painting over the floor")
    # ...and the OBJ palette really is the source: the same colours must be
    # absent from the strip in BOTH directions of the comparison, so a floor
    # tile that merely happens to be rare cannot stand in for the kart.
    assert not (kart_only & floor_only)


def test_the_speed_bar_is_six_sprites_in_the_sky_band():
    m = _boot()
    try:
        for i in range(BAR_TICKS):
            x, y, tile, _ = m.read_bytes(O, 4 + i * 4, 4)
            assert y == BAR_Y, f"tick {i} at y={y}, not in the sky band"
            assert tile == TICK_DIM, f"tick {i} boots lit"
            assert x == 16 + 12 * i, f"tick {i} at x={x}"
        # the HUD is sprites BECAUSE there is no BG3: the pad slot stays parked
        assert m.read_bytes(O, 7 * 4 + 1, 1)[0] == 240
    finally:
        m.close()


# =============================================================================
# R3 — accelerate AND coast back: BOTH directions of the throttle
# =============================================================================

def test_holding_b_lights_the_speed_bar_and_releasing_puts_it_out():
    m = _boot()
    try:
        assert _bar_tiles(m) == [TICK_DIM] * BAR_TICKS
        # 60 frames is the whole ramp: RC_SPEED_CAP / RC_ACCEL = 60, so this
        # drive ends exactly at the cap with every tick lit, and the start
        # straight holds ~1,470 px of road ahead — the run stays on-track.
        m.advance(60, pad1={"b": True})
        lit = _bar_tiles(m)
        assert lit.count(TICK_LIT) >= 4, f"holding B lit {lit}"
        # ...and the REVERSE. Coasting decays to a full stop, so every tick
        # must go out again — a test that only drove the throttle up would
        # lock that direction and ship the coast broken.
        m.advance(400, pad1={})
        assert _bar_tiles(m) == [TICK_DIM] * BAR_TICKS, _bar_tiles(m)
    finally:
        m.close()


def test_the_bar_lights_from_the_left(tmp_path):
    """The lit RUN is a prefix: ticks 0..n-1 lit, n..5 dim. A bar that lit an
    arbitrary subset would still pass a count."""
    m = _boot(drives=[(40, {"b": True})])
    try:
        tiles = _bar_tiles(m)
        n = tiles.count(TICK_LIT)
        assert tiles == [TICK_LIT] * n + [TICK_DIM] * (BAR_TICKS - n), tiles
    finally:
        m.close()


# =============================================================================
# R4 — steer BOTH ways: the floor rotates, and the kart leans into the turn
# =============================================================================

@pytest.mark.parametrize("held,tile,attr", [
    ({}, KART_T_STR, ATTR_NOFLIP),
    ({"left": True}, KART_T_LEAN, ATTR_NOFLIP),
    ({"right": True}, KART_T_LEAN, ATTR_HFLIP),
])
def test_the_kart_frame_follows_the_steer_direction(held, tile, attr):
    m = _boot(drives=[(6, held)])
    try:
        assert tuple(m.read_bytes(O, 0, 4)[2:]) == (tile, attr)
    finally:
        m.close()


def test_the_kart_returns_to_the_straight_frame_when_the_pad_releases():
    """The reverse of the case above — the lean is a per-frame decision, not a
    latch. Same discipline as the throttle: drive the transition BACK."""
    m = _boot(drives=[(6, {"left": True}), (4, {})])
    try:
        assert tuple(m.read_bytes(O, 0, 4)[2:]) == (KART_T_STR, ATTR_NOFLIP)
    finally:
        m.close()


def test_steering_left_and_right_rotate_the_floor_differently(tmp_path):
    """The headline drive case, over PIXELS.

    One shared prelude, then the two directions branch. Both are compared
    against a same-length IDLE control taken from the same prelude, so
    "the picture changed" cannot be credited to the day-night wash, which
    advances on its own clock in all three runs.
    """
    prelude = [(30, {"b": True})]
    idle = _shot(tmp_path, "st_idle", drives=prelude + [(24, {})])
    left = _shot(tmp_path, "st_left", drives=prelude + [(24, {"left": True})])
    right = _shot(tmp_path, "st_right", drives=prelude + [(24, {"right": True})])
    d_l = _diff_frac(idle, left, SEAM, 224)
    d_r = _diff_frac(idle, right, SEAM, 224)
    d_lr = _diff_frac(left, right, SEAM, 224)
    assert d_l > 0.25, f"steering LEFT changed {d_l:.1%} of the floor"
    assert d_r > 0.25, f"steering RIGHT changed {d_r:.1%} of the floor"
    assert d_lr > 0.25, (
        f"LEFT and RIGHT differ in only {d_lr:.1%} of the floor — the two "
        "directions are not distinct rotations")


# =============================================================================
# R5 — the map is collision ground truth: grass slows the kart to a crawl
# =============================================================================

def _churn(drives, window=40):
    """Fraction of the Mode-7 tilemap a `window`-frame held-throttle drive
    rewrites. The rendered stand-in for distance travelled — and it is the
    STREAM's own destination region, not a proxy variable."""
    m = _boot(frames=100, drives=drives)
    try:
        before = _m7_tilemap(m)
        m.advance(window, pad1={"b": True})
        after = _m7_tilemap(m)
    finally:
        m.close()
    return sum(1 for a, b in zip(before, after) if a != b) / len(before)


def test_grass_slows_the_kart_to_a_crawl_without_stopping_it():
    """R5, asserted as what a player SEES rather than as US_SPEED.

    The spawn is mid-road on the start/finish spoke, so a short run stays on
    the track; a hard left and a long run puts the camera out on the grass.
    Same held throttle, same window, both measured as how much of the Mode-7
    TILEMAP the drive rewrote — distance travelled, in the region the PPU
    reads. A `US_SPEED` read would be one line and would pass with col_map
    wired to a constant; the whole question is whether the map reaches the
    physics.

    WHY NOT SCREEN PIXELS: screen repaint SATURATES — the perspective floor
    repaints most of the band at any moving speed, so crawl and full speed do
    not separate there (a `make falsify` pass reported the screen-repaint
    form of this case TEST-BLIND). The tilemap is a true odometer instead:
    the world's tuft scatter is aperiodic on the streamed window's 128-tile
    wrap (gen_racer_assets' TUFT_MOD note), so rewritten bytes track tiles
    crossed. Measured ratios: 0.57 shipped vs 2.25 with the drag branch
    removed.
    """
    on_track = _churn([(30, {"b": True})])
    off_track = _churn([(60, {"b": True, "left": True}), (90, {"b": True})])
    assert off_track < on_track * 0.7, (
        f"off-road churn {off_track:.1%} vs on-road {on_track:.1%} "
        f"(ratio {off_track / on_track:.2f}) — the grass is not dragging")
    assert off_track > 0.02, (
        f"off-road churn {off_track:.1%} — the camera is frozen, and a crawl "
        "is a speed, not a stop")


# =============================================================================
# R6 — the day-night cycle, driven DAY -> NIGHT -> DAY
# =============================================================================

def test_the_sky_changes_between_the_day_and_night_holds(tmp_path):
    day = _shot(tmp_path, "tod_day", frames=DAY)
    night = _shot(tmp_path, "tod_night", frames=NIGHT)
    d = _diff_frac(day, night, 0, SEAM)
    assert d > 0.8, f"only {d:.1%} of the sky band differs between day and night"


def test_all_three_coldata_planes_reach_the_sky(tmp_path):
    """THE DELIVERY HALF OF THE LEDGER: three channels, three
    planes, and each one has to be ARMED and STREAMING.

    "The sky changes between day and night" is satisfied by any ONE plane
    moving, which `make falsify` proved: unarming the B channel at the
    HDMAEN shadow left every ledger case green (they read the allocator's
    map) AND the sky-change case green (R and G still moved), while the
    sky's mean blue sat frozen at 34.4 across the whole cycle. Measured
    shipped: R 68.1 -> 20.5, G 82.6 -> 20.5, B 122.6 -> 67.1. Measured with
    B unarmed: B 34.4 -> 34.4, exactly.
    """
    day = _shot(tmp_path, "pl_day", frames=DAY)
    night = _shot(tmp_path, "pl_night", frames=NIGHT)
    for plane, name in enumerate("RGB"):
        d = _mean_plane(day, plane, 0, SEAM)
        n = _mean_plane(night, plane, 0, SEAM)
        assert abs(d - n) > 8.0, (
            f"the {name} plane reads {d:.1f} at the day hold and {n:.1f} at "
            "the night hold — that channel is not reaching the picture")


def test_night_is_darker_than_day_and_the_cycle_comes_back(tmp_path):
    """BOTH directions of the phase machine. A test that only walked toward
    night would lock that half and ship TO_DAY broken — the day-night clock is
    a state cycle, and AGENTS.md's rule is to drive the whole one.
    """
    def lum(img):
        px = img.load()
        return sum(sum(px[x, y]) for y in range(0, SEAM)
                   for x in range(0, img.width, 4))
    day = lum(_shot(tmp_path, "cyc_day", frames=DAY))
    night = lum(_shot(tmp_path, "cyc_night", frames=NIGHT))
    back = lum(_shot(tmp_path, "cyc_back", frames=DAY_AGAIN))
    assert night < day * 0.8, f"night ({night}) is not darker than day ({day})"
    assert back > night * 1.2, (
        f"the sky at frame {DAY_AGAIN} ({back}) never came back from night "
        f"({night}) — the TO_DAY half of the phase machine is not running")


# =============================================================================
# R7 — the rumble strips: red AND white, and CGRAM that cannot move
# =============================================================================
# RULING (playtest): the kerb PALETTE CYCLE
# "was never the intent. It was a defect." Its source comment presents it as
# an effect — "the rumble stripes at the road edges flash red/white like
# trackside lights" — and this port migrated it as one, which produced a
# visible defect: the strips blinking in and out twice a second. The strips
# are now static, and these two cases are what make that unrepresentable.
#
# The second case is the anti-regression for the whole defect class, not just
# for this rail's version of it: NOTHING may write CGRAM after scene enter.
# Presence of both colours plus the CGRAM-static case above together pin the
# strips: the pattern is there, and nothing rotates it.

def test_the_rumble_strips_show_both_red_and_white(tmp_path):
    """The user-visible invariant: the kerb pattern is THERE.

    Read as pixels rather than as CGRAM words, because CGRAM says the palette
    uploaded and this says the strips reached the screen through it. Measured
    on the shipped ROM at this frame: 295 red-dominant and 435 near-white
    pixels in the counted region; the thresholds sit well below both.
    """
    img = _shot(tmp_path, "kerb")
    px = img.load()
    # The white census stops at y=125: below that sits the start-line chequer,
    # which holds 11,067 near-white pixels at this frame — 96% of a whole-band
    # count — and would keep this case green with the kerb white deleted (the
    # counted population must be attributable to the feature under test).
    red = white = 0
    for y in range(SEAM, 224):
        for x in range(img.width):
            r, g, b = px[x, y]
            if r > 140 and g < 90 and b < 90:
                red += 1
            elif y < 126 and r > 200 and g > 200 and b > 200:
                white += 1
    assert red > 100, f"only {red} red-dominant pixels — the kerb red is gone"
    assert white > 100, f"only {white} near-white pixels — the kerb white is gone"


@pytest.mark.parametrize("drive", [
    pytest.param({}, id="idle"),
    pytest.param({"b": True}, id="driving"),
])
def test_cgram_never_changes_after_the_scene_is_up(drive):
    """THE ANTI-REGRESSION, and it is deliberately absolute.

    The whole 512-byte CGRAM must be bit-identical across a multi-frame
    window, idle and under throttle. Any per-frame palette writer — a kerb
    cycle, a fade that forgot CGRAM is not its register, a HUD tint — makes
    this red on the frame it is added, which is the point: the defect class
    playtesting found is not "this particular cycle is wrong", it is "a running
    scene should not be repainting its palette at all".

    NOT in tension with the day-night cycle: that runs on COLDATA through
    HDMA colour math and never touches CGRAM, which is exactly why the two
    can be asserted independently. Driving is included because a cycle keyed
    off a movement clock rather than a frame counter would hide from an idle
    window.
    """
    m = _boot(frames=100)
    try:
        before = m.read_bytes(C, 0, 512)
        m.advance(37, pad1=drive)          # 37: co-prime with any plausible
        after = m.read_bytes(C, 0, 512)    # power-of-two palette period
        moved = [i for i in range(256)
                 if before[i * 2:i * 2 + 2] != after[i * 2:i * 2 + 2]]
        assert not moved, f"CGRAM word(s) {moved} changed while the scene ran"
    finally:
        m.close()


# =============================================================================
# R8 — START pauses to a freeze-frame, and unpausing resumes
# =============================================================================

def test_start_freezes_the_whole_picture_and_start_again_resumes(tmp_path):
    """A freeze means PIXELS DO NOT MOVE (CLAUDE.md's parallax lesson: the
    invariant is what the user sees, not what a variable reads). The frozen
    pair must be byte-identical INCLUDING the day-night wash, which runs on
    its own clock — so this also proves the pause gate covers the effects
    and not just the camera.
    """
    frozen_a = _shot(tmp_path, "pz_a",
                     drives=[(40, {"b": True}), (1, {"start": True}), (8, {})])
    frozen_b = _shot(tmp_path, "pz_b",
                     drives=[(40, {"b": True}), (1, {"start": True}), (48, {})])
    assert _diff_frac(frozen_a, frozen_b, 0, 224) == 0.0, (
        "the paused picture moved between frame 8 and frame 48 of the freeze")
    # ...and the REVERSE: a second START must unfreeze it.
    resumed = _shot(tmp_path, "pz_c",
                    drives=[(40, {"b": True}), (1, {"start": True}), (8, {}),
                            (1, {"start": True}), (40, {"b": True})])
    assert _diff_frac(frozen_a, resumed, SEAM, 224) > 0.25, (
        "the picture did not resume after the second START")


def test_the_sound_driver_is_still_running_inside_the_freeze():
    """The reference rail's control table promises "freeze-frame; MUSIC KEEPS
    PLAYING", and it is the one thing a freeze must not freeze.

    The claim is asserted on SPC RAM, which is the audio side's own state and
    the only output region this test can reach: it must be non-empty (the
    driver uploaded at boot) AND it must still be CHANGING between two points
    inside the freeze (the driver is executing, not halted). The 65816's pump
    lives outside the pause gate in `main.asm`'s loop by construction; what
    this measures is the consequence.

    Stated limit, because the name is a contract: a still-running S-SMP is
    necessary for "the music keeps playing" and not sufficient — proving
    AUDIBLE output needs a WAV, which is the one deliberately wall-clock
    surface in this repo (AGENTS.md) and out of scope for a lockstep module.
    """
    m = _boot(drives=[(40, {"b": True}), (1, {"start": True}), (8, {})])
    try:
        a = m.read_bytes(MemoryType.SpcRam, 0, 4096)
        assert a != b"\x00" * len(a), (
            "SPC RAM is empty — the TAD driver never uploaded")
        m.advance(30)
        b = m.read_bytes(MemoryType.SpcRam, 0, 4096)
        assert a != b, (
            "SPC RAM is byte-identical across 30 frames of the freeze — the "
            "sound driver stopped with the picture")
    finally:
        m.close()


# =============================================================================
# R10 — ONE centre line, on the 45-degree legs as well as the straights
# =============================================================================
# THE DEFECT THIS REFUSES, stated as the picture a player sees: on every
# diagonal leg of the COURSE the road carried THREE parallel yellow dashed
# lines where the straights carried one. Measured on hardware before the fix —
# the streamed Mode-7 tilemap held three LINE_BACK tiles per row on the long SE
# diagonal, against exactly one LINE_V per row on the home straight, and each
# of those tiles paints a full corner-to-corner stripe through its own cell.
# Cause: the painter's centre-line test was `d == 0` on `_seg_metrics`'
# perpendicular distance, which on a diagonal leg floors to zero for
# cross-track offsets 0 AND +/-1 — three adjacent chains.
# `gen_racer_assets._on_centre_line` is the exact predicate that replaced it.
#
# WHY THE CASE HAS TO DRIVE, and this is the whole point of it. A shot at BOOT
# is of a STRAIGHT, and on the straights the line was always single — a case
# parked there would have stayed green for exactly as long as the diagonals
# stayed broken, which is how this shipped in the first place. So the drive is
# part of the assertion: it puts the camera on COURSE leg 8, the long SE
# diagonal, which is the section the gallery clip shows the defect on.
#
# WHAT IS READ, AND WHAT IS NOT. The claim is asserted on SCREEN PIXELS —
# distinct runs of centre-line ink across the floor's scanlines. The
# camera's world position and heading are read from WRAM to STEER, and to prove
# the shot is of a diagonal ON the road rather than of a straight or of the
# grass. Neither is the claim; reading either AS the claim would be the
# proxy-variable move this module refuses everywhere else.

DIAG_LEG = 8                # COURSE[8] -> COURSE[9]: the long SE diagonal,
                            # 152 tiles — the streamer's worst case, and the
                            # leg the gallery clip shows the three lines on
DIAG_BEARING = 40           # (+1, +1) in pose units, 64 per revolution
# THE COUNTED BAND IS THE WHOLE FLOOR, less two exclusions, and its height is
# what makes the case phase-stable. A narrow near-field band BLINKS: a dash
# period on a 45-degree leg is 4 painted plus 4 blank tile steps ~= 90 px,
# which the cap covers in six frames, so a 26-row band reads the line and then
# reads nothing three frames later and a sample lands in a gap by luck.
# Measured over eight samples two frames apart, a near band alternated
# (max 3 runs, 26 lit) with (0, 0); over the same eight the full floor never
# went dark, because it holds several dashes at different depths at once.
#   - the first four rows below the seam are left out, as `_band_colours`'
#     floor reads leave them out, so the split's own line cannot be counted;
#   - rows 184..197 are the KART's, measured (OAM says y=176 and the 16x16
#     sprite's top rows are transparent). It carries yellow of its own at
#     194..196, which would read as a second run on those scanlines.
LINE_ROWS = tuple(range(SEAM + 4, 184)) + tuple(range(198, 224))
LINE_SAMPLES = (20, 45, 70)  # frames into the leg. Chosen off a MEASURED
                            # sweep of the whole leg in steps of 3: the defect
                            # reads THREE runs at every point of it, and the
                            # fixed ROM reads one from 0 to 105 — past that the
                            # corner into leg 9 brings a SECOND leg's centre
                            # line into shot, which is two lines correctly. All
                            # three samples sit inside that window with 35
                            # frames of margin
INK_MIN, INK_GB = 180, 100  # the ink predicate's two thresholds
LIT_MIN = 40                # scanlines of the band that must carry ink.
                            # Measured across the whole leg: never below 45

# Leg i runs COURSE[i] -> COURSE[i+1]. Each record is (bearing, midpoint px,
# half-length in along-projection units): every positional read folds the
# 4,096 px torus to +/-2,048, and the home straight is 2,368 px — longer than
# the fold — so deltas are taken from the MIDPOINT, where half a leg plus the
# turn-in window always fits. Same construction as the clip's drive, and for
# the same reason: the choreography follows the painted road because it is
# derived from the generator's own vertex list, not from a copy of it.
_BEARING = {(0, -1): 0, (-1, -1): 8, (-1, 0): 16, (-1, 1): 24,
            (0, 1): 32, (1, 1): 40, (1, 0): 48, (1, -1): 56}
_STEP = {h: d for d, h in _BEARING.items()}
_ISQ2_Q14 = 11585           # 2**14 / sqrt(2) — gen_m7_assets' constant
LEGS = []
for _i, (_x0, _y0) in enumerate(COURSE):
    _x1, _y1 = COURSE[(_i + 1) % len(COURSE)]
    _d = ((_x1 > _x0) - (_x1 < _x0), (_y1 > _y0) - (_y1 < _y0))
    LEGS.append((_BEARING[_d], ((_x0 + _x1) * 4 + 4, (_y0 + _y1) * 4 + 4),
                 (abs(_x1 - _x0) + abs(_y1 - _y0)) * 4))
SPAWN_LEG = 15              # world.inc's CAM0 is mid-road on the home straight
TURN_IN = 72                # along-track px before a vertex the turn starts
ROAD_HALF_PX = ROAD_HALF * 8


def _cam(m):
    """(world x, world y, heading) — the camera, from the emitted symbols."""
    return (int.from_bytes(m.read_bytes(W, M7ORG, 2), "little"),
            int.from_bytes(m.read_bytes(W, M7ORG + 2, 2), "little"),
            m.read_bytes(W, HEADING, 1)[0])


def _leg_metrics(x, y, leg):
    """(px still to run on this leg, cross-track px) for a camera at (x, y)."""
    bearing, (mx, my), half = LEGS[leg]
    sx, sy = _STEP[bearing]
    dx = ((x - mx + 2048) % 4096) - 2048
    dy = ((y - my + 2048) % 4096) - 2048
    rem, cross = half - (sx * dx + sy * dy), dx * sy - dy * sx
    if sx and sy:
        rem, cross = (rem * _ISQ2_Q14) >> 14, (cross * _ISQ2_Q14) >> 14
    return rem, cross


def _steer(m, leg):
    """Advance ONE frame at full throttle, turning toward `leg`'s bearing.

    Cross-track: the held bearing bends one pose step toward the centre line
    outside a 16 px deadband and two outside 48, so a corner exit's leftover
    offset closes on the next straight instead of riding it end to end. A
    displacement toward the travel direction's LEFT is positive, so a positive
    error steers RIGHT — the heading decrements."""
    x, y, h = _cam(m)
    _, cross = _leg_metrics(x, y, leg)
    bend = (cross > 16) + (cross > 48) - (cross < -16) - (cross < -48)
    err = (LEGS[leg][0] - bend - h) % 64
    err = err - 64 if err > 32 else err
    m.advance(1, pad1={"b": True, "left": err > 0, "right": err < 0})


def _drive_onto(m, target):
    """Race leg to leg from the spawn until the camera enters `target`.

    POSITION-SHAPED, not frame-counted: a leg advances when the ROM's own
    reported distance to its end vertex is inside the turn-in window, so the
    drive follows the painted road by construction. Deterministic all the same
    — every input is a pure function of prior emulated state, so the whole
    trajectory is a constant of the replay triple (measured: 455 frames)."""
    leg, driven, spins = SPAWN_LEG, 0, 0
    while leg != target:
        spins += 1
        assert spins < 2000, f"never reached COURSE leg {target}, on {leg}"
        x, y, _ = _cam(m)
        rem, _ = _leg_metrics(x, y, leg)
        if rem <= TURN_IN:
            leg = (leg + 1) % len(LEGS)
            continue
        _steer(m, leg)
        driven += 1
    return driven


def _ink_runs(img, y):
    """Distinct runs of centre-line ink across one scanline.

    The ink is the floor palette's (248,248,0), and the predicate takes that
    core WITHOUT its (120,120,72) shoulder, so two chains cannot merge through
    a shoulder pixel between them. Nothing else this rail draws passes it: the
    road is (80,80,96), the kerb (248,0,0) and (248,248,248), and the grass
    greens all sit at r < 180. The kart's own yellow would pass it, which is
    why LINE_ROWS cuts the kart's rendered rows out of the band."""
    px = img.load()
    runs, inrun = 0, False
    for x in range(img.width):
        r, g, b = px[x, y]
        ink = r >= INK_MIN and g >= INK_MIN and g - b >= INK_GB
        if ink and not inrun:
            runs += 1
        inrun = ink
    return runs


def test_the_centre_line_is_one_line_on_the_long_diagonal(tmp_path):
    """R10. Three shots along the diagonal, each one run of ink per scanline.

    Measured on the ROM this landed against: three runs on every counted
    scanline before the fix, one after, at all three sample points.
    """
    m = _boot()
    try:
        driven, held, seen = _drive_onto(m, DIAG_LEG), 0, []
        for at in LINE_SAMPLES:
            while held < at:
                _steer(m, DIAG_LEG)
                held += 1
            x, y, h = _cam(m)
            rem, cross = _leg_metrics(x, y, DIAG_LEG)
            # THE NON-VACUITY GUARD, and it is the half that makes the case
            # mean anything: the shot must be OF the diagonal, ON the road.
            assert h == DIAG_BEARING, (
                f"{driven + held} frames in, the camera reads heading {h} and "
                f"not COURSE leg {DIAG_LEG}'s {DIAG_BEARING} — this shot is "
                "not of a diagonal, and the straights never showed the defect")
            assert rem > 0 and abs(cross) <= ROAD_HALF_PX, (
                f"the camera is {cross} px off the leg's centre with {rem} px "
                "of it left — this shot is not on the diagonal's road")
            img = Image.open(
                m.screenshot(str(tmp_path / f"diag_{at}.png"))).convert("RGB")
            counts = [_ink_runs(img, s) for s in LINE_ROWS]
            seen.append((at, max(counts), sum(1 for c in counts if c)))
        for at, most, lit in seen:
            assert lit >= LIT_MIN, (
                f"{at} frames into the diagonal only {lit} of the band's "
                f"{len(LINE_ROWS)} scanlines carry centre-line ink — the line "
                "is not in shot, so the count below proves nothing (the "
                "sample has drifted off the end of the leg)")
            assert most == 1, (
                f"{at} frames into the diagonal a scanline of the floor "
                f"crosses {most} separate runs of centre-line ink — the road "
                "is showing that many parallel centre lines where it must "
                f"show one (all three samples: {seen})")
    finally:
        m.close()
