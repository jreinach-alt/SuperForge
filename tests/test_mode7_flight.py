"""mode7_flight — free flight, and the ALTITUDE AXIS (the sweep's last rail).

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)` — an
absolute frame by construction — and every drive is a fixed per-frame input
list, so the whole trajectory is a pure function of the replay triple.

WHAT THIS RAIL IS — its four teaching claims:

    M1  ALTITUDE DRIVES THE PERSPECTIVE SCALE — climb and the ground recedes,
        descend and it comes up to meet you. The net-new piece, and the reason
        this rail needed a settlement of its own.
    M2  a SIGNED 8.8 speed integrator, so forward, reverse and hover fall out
        of one multiply-and-subtract rather than three mechanisms
    M3  a SKY above a single-layer plane — Mode 7 has one BG, so a two-band TM
        split turns BG1 off above the horizon and reveals the backdrop
    M4  OBJ over Mode 7 — the map fills VRAM words $0000-$3FFF, so the OBJ name
        base moves above it

WHERE THE ASSERTIONS LAND, and why these regions and not others. The Mode 7
matrix ports are WRITE-ONLY, so "what matrix did the PPU render with" is not
readable from the PPU. What IS readable is the thing the PPU reads: the
DOUBLE-BUFFERED WRAM BAND TABLE the two DIRECT HDMA channels stream, byte for
byte, and the PICTURE that results. So this module asserts on

  * the WHOLE composed band table against the generator's OWN arithmetic
    (`_oracle`), every entry of all 160 scanlines — not a spot check on a
    headline value. Adding a subroutine call that quietly rewrote one sector
    byte is a real bug this repo has shipped past a per-field check;
  * SCREENSHOT PIXELS, for the claims that are about what a player sees — the
    sky band, and the ground receding and approaching;
  * OAM bytes, for the shadow that is this rail's only altimeter;
  * CGRAM words, for the sky colour the split reveals.

Nothing here reads an engine variable as a stand-in for any of those. The
altitude index and heading ARE read — in `_pose` — but only to say WHICH
oracle entry the table must match, never as the evidence that the table
changed.

STATE CYCLES ARE THE CRUX ON THIS RAIL and they are driven as cycles, not
snapshots: climb AND dive AND held-level AND turn-while-climbing AND both axes
moving at once, plus the round trip back to the starting altitude. A test that
walked the altitude one way would lock that direction and ship the other
broken — that shape, one axis at a time.

Power-on fidelity comes free rather than as a case: `Machine` seeds power-on
RAM, so every assertion below is made against a ROM booted from random memory,
and none of this rail's WRAM claims are `[init] zero`.
"""
import importlib.util
import json
import struct
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType                        # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "mode7_flight.sfc"
MAP = json.loads((BUILD / "m7f" / "symbol_map.json").read_text())

W = MemoryType.SnesWorkRam
O = MemoryType.SnesSpriteRam
C = MemoryType.SnesCgRam

# --- the generator IS the oracle -------------------------------------------
# Imported rather than re-implemented, deliberately: the claim under test is
# "the ROM's join reproduces the arithmetic the factors were baked for", and a
# second hand-written copy of that arithmetic here would be a second place for
# it to be wrong. The generator is a pure function of its constants and is
# executed by the build, so it is the one definition both sides answer to.
_spec = importlib.util.spec_from_file_location(
    "gen_m7f_factors", SUPERFORGE / "tools" / "gen_m7f_factors.py")
GEN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GEN)

# The SECOND generator, and the same argument: the sky ramp and the horizon fog
# are a pure function of tools/gen_m7f_gradient.py's constants, the build
# executes it to make the blob the ROM streams, and a hand-copied ramp here
# would be a second place for the shape to be wrong.
_gspec = importlib.util.spec_from_file_location(
    "gen_m7f_gradient", SUPERFORGE / "tools" / "gen_m7f_gradient.py")
GRAD = importlib.util.module_from_spec(_gspec)
_gspec.loader.exec_module(GRAD)


def _sym(name, scene="sky"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


# Addresses come from the emitted map, never a literal — the same rule
# `allocator/no_literals.py` enforces in engine ASM, one layer up.
A_TBL = _sym("ES_M7F_TBL")["start"]
N_TBL = _sym("ES_M7F_TBL")["size"]
A_POSE = _sym("ES_M7F_POSE")["start"]
A_JOIN = _sym("ES_M7F_JOIN")["start"]
A_COST = _sym("ES_M7F_COST")["start"]
A_SKY = _sym("ES_M7F_SKY_TBL")["start"]
A_FOG = _sym("ES_M7F_FOG")["start"]
A_CLOCK = _sym("ES_M7F_CLOCK")["start"]
FOG_ENT = 10                    # m7f_floor: one plane's HDMA header table
A_JOIN_DIRTY = A_JOIN + 20      # the change gate's buffers-owed countdown
A_OAM = _sym("ES_OAM_SHADOW", scene=None)["start"]

# --- the rail's declared geometry (engine/features/m7f_cam/m7f_cam.asm) -----
# Named here so a wrong constant is a mismatch against the picture rather than
# a silent re-spelling of the source.
# THE BAND MOVES WITH ALTITUDE. Nothing here is a constant any
# more except the band's BOTTOM and the deck geometry: `GEN.band_top(a)` and
# `GEN.band_lines(a)` are the same functions the generator bakes the profiles
# with, so the test and the ROM answer to one definition rather than two.
BAND_BOT = GEN.BAND_BOT                              # 224, fixed
BAND_TOP_DECK = GEN.BAND_TOP_DECK                    # 64 — the DECK horizon
LINES, SEG = GEN.LINES, GEN.LINES // 2               # 160, 80 — the MAX band
DAT0 = 6
TBL_ONE, BUF = 648, 1296
ALT_SPAWN_IDX, ALT_MAX_IDX = GEN.ALT_SPAWN_IDX, GEN.ALT_LEVELS - 1   # 40, 80

# THE FRAME'S OWN PERIODS, and every byte-identity case has to respect BOTH.
# The airship's propeller is a two-state flip every M7F_PROP_RATE = 8 frames
# (m7f_obj.asm:27, :252-268), so the picture repeats on 16; the day/night clock
# repaints the sky every TOD_STEP_FRAMES. A gap that is a multiple of the first
# and shorter than the second is the only one over which "identical" is a claim
# about the SKIP rather than about either animation.
PROP_PERIOD = 16
IDENT_GAP = PROP_PERIOD

SHIP_SLOT, SHADOW_SLOT = 0, 1
SHIP_X, SHIP_Y = 112, 96
SHADOW_X, SHADOW_Y_LOW = 112, 168
SHADOW_THRESH_IDX = 40
T_SHIP_A, T_SHIP_B = 0, 4
T_SHADOW_BIG, T_SHADOW_SML = 8, 12
HI_SHIP_LARGE, HI_SHADOW_LARGE = 1 << 1, 1 << 3

FRAME_MC, LINE_MC, DOT_MC = 357368, 1364, 4
# The cadence budget, stated as the thing that actually matters: the join may
# cost whatever it costs so long as every frame's work still fits in its frame.
# The measured worst case is ~153,400 mc; the ceiling here is a
# guard against a regression of a different ORDER, not a re-pin of the number.
JOIN_MC_CEILING = 200_000

BOOT = 120          # frames of settle before anything is asserted


# ===========================================================================
# helpers — every one reads an OUTPUT region
# ===========================================================================
def _pose(m):
    """(heading, altitude index). Read to pick the oracle row, never as proof."""
    b = m.read_bytes(W, A_POSE, 14)
    return b[8] | b[9] << 8, b[10] | b[11] << 8


def _back_buf(m):
    """The buffer the tick has just composed — this frame's pose.

    THE PHASE IS THE DESIGN, and it is stated here once rather than discovered
    per case. The NMI hook flips `back` and points both channels at the OTHER
    buffer; the tick then composes into `back`. So at a parked frame boundary
    `back` names the table just written from the CURRENT pose, and the FRONT
    one — the table the picture on screen was streamed from — holds the
    PREVIOUS frame's. `test_the_streamed_buffer_is_exactly_one_frame_behind`
    asserts both halves of that.
    """
    b = m.read_bytes(W, A_JOIN, 18)
    return (b[8] | b[9] << 8) & 1


def _front_buf(m):
    return _back_buf(m) ^ 1


def _geometry(m):
    """The band's LIVE geometry, read out of the rail's own DP state.

    Read rather than computed so a disagreement between the ROM's derive and
    the generator's is visible as a mismatch instead of being papered over by
    the test re-deriving it. `test_the_horizon_tracks_the_altitude` is what
    checks the derive itself against GEN.
    """
    j = m.read_bytes(W, A_JOIN, 36)
    return {"n": j[28] | j[29] << 8, "seg": j[30] | j[31] << 8,
            "horizon": j[32] | j[33] << 8, "dat1": j[34] | j[35] << 8}


def _band_at(m, buf, alt_idx):
    """A buffer's table read with the geometry of a GIVEN altitude.

    The front buffer was composed from the PREVIOUS pose, and under the moving
    horizon that pose had a different band length and a different run-1 offset
    — so reading it with the LIVE geometry would mis-slice it. Geometry is a
    pure function of the altitude index, so the caller says which.
    """
    n = GEN.band_lines(alt_idx)
    seg = n // 2
    dat1 = DAT0 + seg * 4 + 1
    raw = m.read_bytes(W, A_TBL + buf * BUF, BUF)
    out = []
    for k in range(n):
        off = DAT0 + k * 4 if k < seg else dat1 + (k - seg) * 4
        a, b = struct.unpack_from("<hh", raw, off)
        c, d = struct.unpack_from("<hh", raw, TBL_ONE + off)
        out.append((a, b, c, d))
    return out, raw


def _band(m, buf):
    """The composed band table for one buffer: [(A, B, C, D)] x N lines.

    N and run 1's offset are both f(altitude) — under the moving horizon the
    HDMA layout is dynamic, because run 1's count byte must immediately follow
    run 0's data.
    """
    g = _geometry(m)
    raw = m.read_bytes(W, A_TBL + buf * BUF, BUF)
    out = []
    for k in range(g["n"]):
        off = DAT0 + k * 4 if k < g["seg"] else g["dat1"] + (k - g["seg"]) * 4
        a, b = struct.unpack_from("<hh", raw, off)
        c, d = struct.unpack_from("<hh", raw, TBL_ONE + off)
        out.append((a, b, c, d))
    return out, raw


def _oracle(alt_idx, head):
    """The band the generator's arithmetic demands, for this pose.

    Solved over THIS altitude's band length, not over 160 and truncated — the
    hyperbola's near end belongs to the band's last row, wherever that is.
    """
    n = GEN.band_lines(alt_idx)
    row = [GEN.quantise(s) for s in GEN.scale_profile(GEN.ALTS[alt_idx], n)]
    cm, sm, cn, sn = GEN.trig_entry(head)

    def s16(v):
        return v - 65536 if v > 32767 else v
    out = []
    for p in row:
        a, b = s16(GEN.coeff(p, cm, cn)), s16(GEN.coeff(p, sm, sn))
        out.append((a, b, s16((-b) & 0xFFFF), a))
    return out


def _assert_band_matches(m, where):
    """The WHOLE table, every entry, against the oracle. The core assertion.

    Reads the BACK buffer — the one the tick has just composed from the pose
    the same tick settled. See `_back_buf` for why that is the frame-matched
    pair and the front one is deliberately a frame behind.
    """
    head, alt = _pose(m)
    got, _ = _band(m, _back_buf(m))
    want = _oracle(alt, head)
    assert len(got) == len(want), (
        f"{where}: the ROM composed {len(got)} lines and the generator says "
        f"{len(want)} for altitude index {alt} — the band geometry disagrees "
        f"before any coefficient is compared")
    bad = [(k, got[k], want[k]) for k in range(len(want)) if got[k] != want[k]]
    assert not bad, (
        f"{where}: {len(bad)}/{len(want)} band entries disagree with the "
        f"generator's arithmetic at heading {head} / altitude index {alt}. "
        f"First three: {bad[:3]}")
    return head, alt, got


def _oam(m, slot):
    b = m.read_bytes(O, slot * 4, 4)
    hi = m.read_bytes(O, 512 + slot // 4, 1)[0]
    return {"x": b[0], "y": b[1], "tile": b[2], "attr": b[3],
            "x9": (hi >> ((slot % 4) * 2)) & 1,
            "large": (hi >> ((slot % 4) * 2 + 1)) & 1}


def _shot(m, path):
    m.screenshot(str(path))
    return Image.open(path).convert("RGB")


def _top_row(img):
    """The screenshot row that is PPU scanline 0.

    Mesen's frame buffer is 239 rows and the first few are blanked, so a row
    index is not a scanline index. CALIBRATED rather than hardcoded: the first
    row that is not entirely black is the top of the rendered picture, which is
    independent of anything this rail does — the sky/floor boundary is what the
    tests then locate RELATIVE to it, so the calibration cannot launder the
    assertion it serves.
    """
    px = img.load()
    for y in range(img.height):
        if any(px[x, y] != (0, 0, 0) for x in range(img.width)):
            return y
    raise AssertionError("the whole frame is black — nothing rendered")


def _mesen_rgb(word):
    """A BGR555 CGRAM word as Mesen renders it: 5 bits expanded to 8."""
    def e(v):
        return (v << 3) | (v >> 2)
    return e(word & 31), e((word >> 5) & 31), e((word >> 10) & 31)


def _rows_of(img, y0, y1):
    px = img.load()
    return [[px[x, y] for x in range(img.width)] for y in range(y0, y1)]


def _distinct(rows):
    return {c for row in rows for c in row}


def _join_mc(m):
    b = m.read_bytes(W, A_COST, 8)
    h0, v0 = b[0] | b[1] << 8, b[2] | b[3] << 8
    h1, v1 = b[4] | b[5] << 8, b[6] | b[7] << 8
    return ((v1 * LINE_MC + h1 * DOT_MC) - (v0 * LINE_MC + h0 * DOT_MC)) % FRAME_MC


# ===========================================================================
# THE JOIN — the whole table against the generator, through every state cycle
# ===========================================================================
def test_the_composed_band_matches_the_generator_at_the_spawn_pose():
    """M1, at rest. Whole-table, all 160 scanlines, both buffers.

    Both buffers, because `m7f_arm` composes each once at scene enter so the
    first displayed frame is a floor rather than the zeroed skeleton — and a
    rail that composed only the front one would look correct until the first
    swap.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        head, alt, _ = _assert_band_matches(m, "spawn")
        assert (head, alt) == (0, ALT_SPAWN_IDX), (
            f"spawn pose drifted: heading {head}, altitude index {alt}")
        for buf in (0, 1):
            got, _ = _band(m, buf)
            assert got == _oracle(alt, head), f"buffer {buf} disagrees at spawn"


@pytest.mark.parametrize("name,pad,frames", [
    ("climb", {"r": True}, 40),
    ("dive", {"l": True}, 40),
    ("held level", {}, 40),
    ("turn left while climbing", {"left": True, "r": True}, 40),
    ("turn right while diving", {"right": True, "l": True}, 40),
    ("both axes + throttle", {"left": True, "r": True, "b": True}, 40),
])
def test_the_band_tracks_both_axes_through_every_state_cycle(name, pad, frames):
    """M1 + M2, driven as CYCLES rather than snapshots.

    The table is re-derived and compared IN FULL after every single frame, so
    a defect that only fires on one altitude, one heading, one sign quadrant or
    one of the two 80-line segments has nowhere to hide. The two turning cases
    exist because heading and altitude are independent axes of one table: a
    build that froze either while the other moved would pass a single-axis
    sweep, which is the shape this rule is named for.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for i in range(frames):
            m.advance(1, pad1=pad)
            _assert_band_matches(m, f"{name}, frame {i}")


def test_the_altitude_axis_returns_to_its_start_and_the_band_with_it():
    """The ROUND TRIP — descend to the floor, climb back, land on the start.

    A one-way sweep proves the axis moves; only the return proves it is a
    reversible axis rather than a latch. The band is checked the whole way, and
    the arrival is checked as an EQUALITY against the spawn table read before
    the trip — the same bytes, not merely a plausible table.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        head0, alt0 = _pose(m)
        start, _ = _band(m, _back_buf(m))

        for i in range(ALT_SPAWN_IDX + 5):        # to the floor, then hold
            m.advance(1, pad1={"l": True})
            _assert_band_matches(m, f"descent frame {i}")
        _, floor_alt = _pose(m)
        assert floor_alt == 0, f"the descent clamped at {floor_alt}, not 0"

        for i in range(ALT_SPAWN_IDX):            # back up to the spawn level
            m.advance(1, pad1={"r": True})
            _assert_band_matches(m, f"return frame {i}")
        head1, alt1 = _pose(m)
        assert (head1, alt1) == (head0, alt0), (
            f"the round trip landed on ({head1}, {alt1}), not ({head0}, {alt0})")
        got, _ = _band(m, _back_buf(m))
        assert got == start, (
            "the band returned to the spawn altitude but not to the spawn "
            "table — the axis is not reversible byte-for-byte")


def test_the_altitude_clamps_at_both_ends_and_the_band_holds_there():
    """No crash, no ceiling break — the reference states both outright.

    Held against each end stop for longer than the axis is deep, then checked:
    the index is pinned, and the band is STILL the oracle's, which is what
    rules out a clamp that stopped the index while the table walked past it.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(ALT_MAX_IDX + 30, pad1={"r": True})
        _, alt = _pose(m)
        assert alt == ALT_MAX_IDX, f"the ceiling clamp let the index reach {alt}"
        _assert_band_matches(m, "held at the ceiling")

        m.advance(ALT_MAX_IDX + 30, pad1={"l": True})
        _, alt = _pose(m)
        assert alt == 0, f"the floor clamp let the index reach {alt}"
        _assert_band_matches(m, "held at the floor")


def test_the_far_rows_keep_receding_at_the_top_of_the_climb():
    """obs 3, as the invariant that would have caught it — REPLACES the case
    that asserted the opposite.

    An earlier decision reproduced the reference's `pv_ztable` 8-bit
    clamp in the baked profile, and a case here ASSERTED that clamp. Both were
    wrong: that clamp is on the reference's RUNTIME Z accumulator, not on its
    scale profile, and reproducing it left FOUR identical coefficients at the
    top of the band at max altitude — a flat, face-on far region, which is
    exactly what playtesting reported seeing. Audited against both references at
    their own max heights: its curve and ours are strictly
    decreasing to the far row.

    So the invariant is the opposite one, and it is checked where it failed —
    at the top of the climb, on the composed band the PPU actually streams.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(ALT_MAX_IDX + 20, pad1={"r": True})
        band, _ = _band(m, _back_buf(m))
        alt = _pose(m)[1]
    assert alt == ALT_MAX_IDX, "not at the ceiling — the case is vacuous"
    far = [e[0] for e in band[:8]]
    assert len(set(far)) == len(far), (
        f"the top {len(far)} rows of the band share coefficients {far} — the "
        "far field is planar, not receding")
    assert all(a > b for a, b in zip(far, far[1:])), (
        f"the far rows are not strictly receding: {far}")
    # ...and the whole band is monotonic, not just its top.
    a_col = [e[0] for e in band]
    assert all(x >= y for x, y in zip(a_col, a_col[1:])), (
        "the scale profile is not monotonic down the band")


def test_the_two_hdma_tables_keep_their_skeleton_while_the_data_moves():
    """The count bytes and terminators are STRUCTURE, not data.

    An HDMA repeat count is seven bits, so a 160-line band is two 80-line runs
    with a count byte between them and a skip entry before them. The join
    writes 640 data bytes per channel and must step over all four of those
    control bytes; a join that walked straight through would produce a table
    that streams the wrong number of lines and a picture that looks nearly
    right. Checked on BOTH buffers after a drive that moves both axes.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(30, pad1={"left": True, "r": True, "b": True})
        for buf in (0, 1):
            _, raw = _band(m, buf)
            g = _geometry(m)
            for chan, base in (("AB", 0), ("CD", TBL_ONE)):
                assert raw[base + 0] == g["horizon"], (
                    f"buf{buf} {chan}: the sky skip count is {raw[base]}, not "
                    f"the live horizon {g['horizon']}")
                assert raw[base + 5] == 0x80 | g["seg"], f"buf{buf} {chan}: run 0"
                assert raw[base + g["dat1"] - 1] == 0x80 | g["seg"], (
                    f"buf{buf} {chan}: run 1's count is not where the layout "
                    f"says — it must immediately follow run 0's data")
                assert raw[base + g["dat1"] + g["seg"] * 4] == 0, (
                    f"buf{buf} {chan}: terminator")


def test_the_double_buffer_swaps_and_the_streamed_table_is_never_the_live_one():
    """The tear discipline this rail accepts, asserted.

    The tick composes the BACK buffer during active display and the NMI hook
    re-points both channels at it; so across consecutive frames the FRONT
    buffer must alternate, and the channel table addresses must follow it. Read
    from the scene_mgr HDMA shadow — the register file's own staging — rather
    than from the flag that decides it.
    """
    sm = _sym("ES_SM_HDMA", scene=None)["start"]
    ch_ab = _sym("ES_M7F_TBL")            # presence check; channel from the map
    assert ch_ab is not None
    seen = []
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for _ in range(6):
            m.advance(1, pad1={"r": True})
            shadow = m.read_bytes(W, sm, 128)
            addrs = {shadow[c * 16 + 2] | shadow[c * 16 + 3] << 8
                     for c in range(8)}
            seen.append(({A_TBL, A_TBL + BUF} & addrs,
                         {A_TBL + TBL_ONE, A_TBL + BUF + TBL_ONE} & addrs))
        ab_seen = {frozenset(a) for a, _ in seen}
        cd_seen = {frozenset(c) for _, c in seen}
        assert len(ab_seen) == 2, (
            f"the AB channel's table address never alternated: {ab_seen} — the "
            "double buffer is not swapping, so the picture streams a table the "
            "CPU is mid-way through rewriting")
        assert len(cd_seen) == 2, f"the CD channel's table never alternated: {cd_seen}"


def test_the_streamed_buffer_is_exactly_one_frame_behind():
    """The double buffer's PHASE, stated and checked in both halves.

    The tick composes the back buffer from this frame's pose; the NMI hook
    swaps it in. So the table the picture was streamed from is the PREVIOUS
    frame's pose — not stale, not torn, exactly one frame. Asserting only the
    back half would leave "the swap happens at all" untested, and asserting
    only the front half would read as a one-frame BUG rather than the design.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        prev = _pose(m)
        for i in range(12):
            m.advance(1, pad1={"r": True, "left": True})
            cur = _pose(m)
            back, _ = _band_at(m, _back_buf(m), cur[1])
            front, _ = _band_at(m, _front_buf(m), prev[1])
            assert back == _oracle(cur[1], cur[0]), (
                f"frame {i}: the back buffer does not hold THIS frame's pose")
            assert front == _oracle(prev[1], prev[0]), (
                f"frame {i}: the streamed buffer holds neither this frame's "
                f"pose {cur} nor the previous one {prev} — the swap is not "
                "one frame deep")
            assert cur != prev, (
                "the pose did not advance, so this case is vacuous")
            prev = cur


# ===========================================================================
# THE MOVING HORIZON — read off the PICTURE
# ===========================================================================
SKY_UNIFORM = 0.75          # the modal-colour fraction that separates the bands


def _modal_fraction(img, y):
    """What share of a rendered row is its single most common colour."""
    px = img.load()
    row = [px[x, y] for x in range(img.width)]
    return row.count(max(set(row), key=row.count)) / len(row)


def _horizon_row(img):
    """The first rendered row that is not a FLAT band — the horizon, in the
    screenshot's own coordinates. This is the OUTPUT REGION for the whole
    piece: the band's first scanline is a fact about what the player sees, and
    a DP word agreeing with the generator would not prove the split moved.

    FLATNESS, not "differs from the backdrop colour", and the change is the
    sky gradient's doing. Above the horizon BG1 is off, so every pixel of a
    line is one colour — the backdrop plus that line's COLDATA byte — however
    the ramp is shaded; below it the plane's texture takes over. A MAJORITY
    test rather than a total one because the airship is drawn OVER the sky band
    (TM keeps OBJ on above the horizon, which is the point of the split) and at
    high altitude it straddles the horizon: its 32 columns are 12.5% of a
    256-pixel row. The threshold has room on both sides — MEASURED across the
    contact sheet's four poses, sky rows run 0.969..1.000 and the sixty floor
    rows under them peak at 0.641."""
    top = _top_row(img)
    for y in range(top + 1, img.height):
        if _modal_fraction(img, y) < SKY_UNIFORM:
            return y - top
    raise AssertionError("no horizon: the whole picture is a flat band")


def test_the_horizon_tracks_the_altitude_across_a_full_climb_and_dive(tmp_path):
    """obs 2, in pixels, BOTH directions.

    The playtest report was that the sky's share of the screen does not change
    with altitude. So this walks the axis to the floor, up to the ceiling and
    back down, and at each sample reads the horizon OFF THE SCREENSHOT and
    compares it to `GEN.band_top` — the same function the profiles are baked
    with. A one-way sweep would lock one direction; the dive half is what
    proves the anchor follows the axis back down rather than latching.
    """
    seen = {}
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        cg0 = m.read_bytes(C, 0, 2)
        sky = _mesen_rgb(cg0[0] | cg0[1] << 8)
        m.advance(ALT_MAX_IDX + 20, pad1={"l": True})        # to the floor
        for phase, pad in (("climb", {"r": True}), ("dive", {"l": True})):
            for i in range(9):
                m.advance(10, pad1=pad)
                m.advance(3)                                  # let the swap land
                alt = _pose(m)[1]
                img = _shot(m, tmp_path / f"h_{phase}_{i}.png")
                got = _horizon_row(img)
                want = GEN.band_top(alt)
                assert got == want, (
                    f"{phase} sample {i}: altitude index {alt} renders its "
                    f"horizon at scanline {got}, but the band is baked for "
                    f"{want} — the picture and the profile disagree")
                seen[alt] = got
    assert max(seen.values()) - min(seen.values()) >= 30, (
        f"the horizon only moved {max(seen.values()) - min(seen.values())} "
        f"scanlines across the whole altitude range — that is the 'sky does "
        f"not change' observation, not a fix for it")


def test_the_skip_holds_byte_identity_across_a_re_anchor(tmp_path):
    """The skip and the moving horizon, together — the interaction case.

    A height change re-anchors the HDMA layout (run 1's count byte MOVES), and
    the re-anchor rides the same owed-buffers countdown the data does. So after
    it settles, a skipped frame must still render byte-identically — and at a
    DIFFERENT horizon than before. Either half alone would pass on a broken
    build: identity alone passes if nothing re-anchored, and a moved horizon
    alone passes if the skip is publishing a half-written table.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        cg0 = m.read_bytes(C, 0, 2)
        sky = _mesen_rgb(cg0[0] | cg0[1] << 8)
        m.advance(30, pad1={"l": True})
        m.advance(4)
        _park_in_step(m)
        a1 = _shot(m, tmp_path / "ra_a1.png")
        m.advance(20)
        a2 = _shot(m, tmp_path / "ra_a2.png")
        assert _floor_bytes(a1) == _floor_bytes(a2), "not settled into the skip"
        h1 = _horizon_row(a1)

        m.advance(40, pad1={"r": True})          # climb: forces a RE-ANCHOR
        m.advance(4)                              # ...and settle back into skip
        assert m.read_u16(W, A_JOIN_DIRTY) == 0, "did not re-enter the skip"
        _park_in_step(m)
        b1 = _shot(m, tmp_path / "ra_b1.png")
        m.advance(20)
        b2 = _shot(m, tmp_path / "ra_b2.png")
        h2 = _horizon_row(b1)

    assert _floor_bytes(b1) == _floor_bytes(b2), (
        "two skipped frames after a re-anchor render the plane differently — "
        "the skip is publishing a table whose control bytes were rewritten "
        "under it")
    assert h2 != h1, (
        f"the horizon did not move across the re-anchor ({h1} -> {h2}), so the "
        "byte-identity assertion above is vacuous")
# ===========================================================================
# THE CHANGE SKIP — and its double-buffer semantics
# ===========================================================================
def _cost_mc(m):
    return _join_mc(m)


def test_the_skip_engages_when_the_pose_stops_moving_and_the_band_stays_right():
    """The gate is a COUNTDOWN of buffers owed, not a "did it change" flag.

    A one-bit flag would skip the frame after a change, whose BACK buffer still
    held the pose from two frames earlier, and the channels would stream it on
    the next swap — right on alternate frames, a frame behind on the others.
    So the invariant this case asserts is not "the join stopped running" but
    **the band is still correct on every skipped frame**, which is the only
    thing a player can see. The cost is read alongside as the evidence that
    something was actually skipped; on its own it would be a proxy.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(20, pad1={"left": True, "r": True, "b": True})
        moving = _cost_mc(m)
        m.advance(3)                                  # release: drain the owed
        skipped = []
        for i in range(30):
            m.advance(1)
            skipped.append(_cost_mc(m))
            _assert_band_matches(m, f"skip frame {i}")   # THE invariant
        assert max(skipped) * 20 < moving, (
            f"the join still costs {max(skipped)} mc with nothing held against "
            f"{moving} mc under input — the skip is not engaging")
        assert m.read_u16(W, A_JOIN_DIRTY) == 0, "the gate still owes a buffer"


def test_the_skip_transitions_in_and_out_with_no_stale_frame():
    """BOTH directions, driven — the trap is on the way OUT.

    Entering the skip is the easy half. Leaving it is where a naive gate ships
    a frame of the OLD pose: the change is detected, but if the compose is
    deferred to "next frame" the swap has already published a stale table. This
    case asserts the band matches the NEW pose on the VERY FIRST frame under
    resumed input, and that the picture actually moved.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        # TWENTY frames of climb, not forty: from the spawn index (40 of 80)
        # forty would pin the altitude at the CEILING CLAMP, and resuming R
        # there moves nothing — the case would fail on its own vacuity guard
        # rather than on the rail. Stopping mid-range leaves both directions
        # live.
        m.advance(20, pad1={"r": True})
        m.advance(4)                                   # settle into the skip
        assert m.read_u16(W, A_JOIN_DIRTY) == 0, "never entered the skip"
        head0, alt0 = _pose(m)
        idle_cost = _cost_mc(m)

        m.advance(1, pad1={"r": True})                 # the FIRST frame out
        head1, alt1 = _pose(m)
        assert (head1, alt1) != (head0, alt0), "the pose did not move — vacuous"
        _assert_band_matches(m, "the first frame after the skip released")
        assert _cost_mc(m) > idle_cost * 20, (
            "the join did not run on the frame the pose changed — a stale "
            "table is about to be published by the swap")
        for i in range(4):                             # ...and it stays right
            m.advance(1, pad1={"r": True})
            _assert_band_matches(m, f"frame {i} after release")


def test_a_skipped_frame_renders_the_identical_picture(tmp_path):
    """The skip's user-visible claim, in PIXELS.

    Byte-identical screenshots across the skip, and — the non-vacuity half —
    a picture that DOES change once input resumes. Without the second
    assertion, a rail whose display had died would pass the first.
    """
    gap = 20
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(30, pad1={"l": True})
        m.advance(4)                                   # into the skip
        _park_in_step(m)                               # ...and into ONE tod step
        a = _floor_bytes(_shot(m, tmp_path / "skip_a.png"))
        m.advance(gap)
        b = _floor_bytes(_shot(m, tmp_path / "skip_b.png"))
        m.advance(6, pad1={"l": True})
        c = _floor_bytes(_shot(m, tmp_path / "skip_c.png"))
    assert a == b, (
        f"the composed plane renders differently {gap} frames apart inside the "
        "skip — the skip is publishing a buffer the tick did not compose from "
        "the live pose")
    assert a != c, "the plane did not change when input resumed — vacuous"


# ===========================================================================
# THE PICTURE — what a player actually sees
# ===========================================================================
def test_the_sky_band_is_the_backdrop_and_the_floor_is_below_it(tmp_path):
    """M3, as pixels.

    Mode 7 has ONE background, so the sky is the ABSENCE of BG1: a two-band TM
    split turns it off above the horizon and CGRAM word 0 shows through. The
    claim is checkable exactly — every sky line is ONE colour across the whole
    256-pixel row, the band below it is not, and the BOUNDARY lands on the
    declared band top to the scanline. A VRAM assertion could not make any of
    it: the split is a per-scanline register write, and its effect exists only
    in the composited picture.

    UNIFORMITY, not "equals the backdrop word", since the sky gained its ramp:
    colour math adds a different COLDATA byte to the backdrop on every line, so
    the band is many colours down the screen and exactly one ACROSS. That is
    still the BG1-is-off claim — a lit BG1 would put the plane's texture in the
    row — and it is the half of it a gradient cannot launder. WHICH colours is
    the next test's subject.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        img = _shot(m, tmp_path / "sky.png")
        cg0 = m.read_bytes(C, 0, 2)
        # THE HORIZON MOVES, so this is read live rather than
        # written as 64. At the spawn altitude it is 84, and a case that
        # assumed the deck value would fail on a rail that is working.
        horizon = _geometry(m)["horizon"]
    sky = _mesen_rgb(cg0[0] | cg0[1] << 8)
    top = _top_row(img)

    for sl in range(2, horizon):
        assert _modal_fraction(img, top + sl) >= SKY_UNIFORM, (
            f"sky scanline {sl} is not dominated by one flat colour "
            f"({_modal_fraction(img, top + sl):.0%}) — BG1 is still on above "
            f"the horizon")
    below = _distinct(_rows_of(img, top + horizon + 8, top + BAND_BOT - 8))
    assert len(below) >= 4, (
        f"the floor band shows only {len(below)} colour(s) — the plane did "
        "not upload, or the matrix stream is dead")
    assert not (below <= {sky}), "the floor band is sky-coloured all the way down"

    # ...and the split is where it was declared, to the scanline. An off-by-one
    # band would still pass the two set assertions above.
    assert _modal_fraction(img, top + horizon - 1) >= SKY_UNIFORM, (
        f"scanline {horizon - 1} is not flat sky — the split fires too early")
    assert _modal_fraction(img, top + horizon) < SKY_UNIFORM, (
        f"scanline {horizon} is still flat sky — the split fires too late")
    assert sky == _mesen_rgb(cg0[0] | cg0[1] << 8)      # the word the split reveals


def test_climbing_recedes_the_ground_and_diving_brings_it_up(tmp_path):
    """M1, AS THE PLAYER SEES IT — the rail's headline lesson, in pixels.

    The invariant is stated in plain terms first, because a spec's mechanism is
    not the user-visible thing: CLIMBING
    MAKES THE GROUND RECEDE, which means more of the world fits on screen and
    each feature gets smaller. The measurable form of "smaller features" is
    that a fixed screen row crosses MORE colour changes — the texture's spatial
    frequency rises. Checked at three altitudes on the same heading and the
    same world position, so the only thing that differs is the axis under test.
    """
    def transitions(img, y):
        px = img.load()
        row = [px[x, y] for x in range(img.width)]
        return sum(1 for a, b in zip(row, row[1:]) if a != b)

    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        mid = _shot(m, tmp_path / "mid.png")
        m.advance(ALT_MAX_IDX + 10, pad1={"r": True})
        high = _shot(m, tmp_path / "high.png")
        m.advance(2 * ALT_MAX_IDX + 20, pad1={"l": True})
        low = _shot(m, tmp_path / "low.png")

    probe_y = _top_row(mid) + BAND_BOT - 24     # well inside the floor band
    t_low, t_mid, t_high = (transitions(i, probe_y) for i in (low, mid, high))
    assert t_low < t_mid < t_high, (
        f"the ground did not recede monotonically with altitude: row {probe_y} "
        f"crosses {t_low} edges at the floor, {t_mid} at spawn, {t_high} at the "
        "ceiling — climbing must compress more world into the same row")
    assert t_high >= 2 * t_low, (
        f"the axis moves but barely: {t_low} -> {t_high} edges across the whole "
        "81-level range is not a perspective change a player would call one")


def test_the_picture_holds_still_when_nothing_is_held(tmp_path):
    """The hover, as pixels — and the non-vacuity control for every case above.

    With no input the speed bleeds to zero and the camera stops, so the picture
    must not move. Without this, "the picture changed when I held R" would be a
    claim about a rail whose floor drifts on its own.

    TWO WINDOWS, and the reason is that this frame now has THREE periods in it:
    the propeller's 16 frames, the day/night step's 32, and the full 2,048-frame
    cycle. "Identical" is only a statement about the CAMERA over a gap that is a
    whole number of all of them.

      * inside ONE day/night step, the COMPOSED PLANE — the rows below the fog,
        the airship and every cloud. That is the camera's own claim, on the
        only surface the propeller and the wind stay off, in the only window
        where the ambient is not rewriting the floor's own colours;
      * a WHOLE DAY/NIGHT CYCLE apart — 2,048 frames, 34 seconds of held hover,
        and the ENTIRE frame must come back byte-identical. Everything in the
        picture is periodic on a divisor of it: the propeller repeats every 16
        frames, the clock closes its cycle by construction, and the wind's 8.8
        accumulator advances by exactly 2^16 over 2,048 frames and wraps to the
        value it started on. So this arm catches drift the camera accumulates
        over half a minute AND proves all three clocks close.
    """
    assert GRAD.TOD_CYCLE_FRAMES % PROP_PERIOD == 0, (
        "a day/night cycle is no longer a whole number of propeller periods, "
        "so the long-gap arm below can fail on the propeller instead of on the "
        "camera")
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(60)                            # let the throttle bleed to 0
        _park_in_step(m)
        a_img = _shot(m, tmp_path / "hold_a.png")
        m.advance(20)
        b_img = _shot(m, tmp_path / "hold_b.png")
        m.advance(GRAD.TOD_CYCLE_FRAMES - 20)
        c = _shot(m, tmp_path / "hold_c.png").tobytes()
    assert _floor_bytes(a_img) == _floor_bytes(b_img), (
        "the composed plane moved across 20 held frames — the hover is not a "
        "hover")
    assert a_img.tobytes() == c, (
        f"a frame {GRAD.TOD_CYCLE_FRAMES} frames later — one whole day/night "
        f"cycle, nothing held — is not identical: either the camera drifted "
        f"over 34 seconds, or one of the three clocks does not close")


# ===========================================================================
# THE SHADOW — this rail's only altimeter
# ===========================================================================
def test_the_shadow_reports_the_altitude_in_size_tile_and_screen_y():
    """M1's readout, in OAM bytes.

    All THREE properties must move together. A test that read only the tile
    would pass on a build whose size bit was frozen — and the size bit is the
    one that is a read-modify-write hazard, because it shares a hi-table byte
    with the ship's.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(ALT_MAX_IDX + 20, pad1={"l": True})       # the floor
        m.advance(2)
        low = _oam(m, SHADOW_SLOT)
        m.advance(ALT_MAX_IDX + 20, pad1={"r": True})       # the ceiling
        m.advance(2)
        high = _oam(m, SHADOW_SLOT)
        ship = _oam(m, SHIP_SLOT)

    assert low["tile"] == T_SHADOW_BIG and low["large"] == 1, (
        f"at the floor the shadow is tile {low['tile']} large={low['large']}, "
        f"want tile {T_SHADOW_BIG} large=1")
    assert high["tile"] == T_SHADOW_SML and high["large"] == 0, (
        f"at the ceiling the shadow is tile {high['tile']} "
        f"large={high['large']}, want tile {T_SHADOW_SML} large=0")
    assert high["y"] > low["y"], (
        f"the shadow's screen y did not drop toward the horizon on the climb: "
        f"{low['y']} -> {high['y']}")
    assert low["y"] == SHADOW_Y_LOW, f"floor shadow y = {low['y']}"
    assert (low["x"], high["x"]) == (SHADOW_X, SHADOW_X), "the shadow slid sideways"
    assert ship["large"] == 1, (
        "the AIRSHIP's size bit was cleared while the shadow's was rebuilt — "
        "they share one hi-table byte and it must be written whole")
    assert (ship["x"], ship["y"]) == (SHIP_X, SHIP_Y), (
        f"the airship left its fixed screen position: {ship['x']}, {ship['y']}")


def test_the_propeller_animates_and_the_ship_never_leaves_its_slot():
    """M4 — OBJ over Mode 7, and the two-frame flip on its own clock."""
    tiles = set()
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for _ in range(40):
            m.advance(1)
            e = _oam(m, SHIP_SLOT)
            tiles.add(e["tile"])
            assert (e["x"], e["y"]) == (SHIP_X, SHIP_Y)
    assert tiles == {T_SHIP_A, T_SHIP_B}, (
        f"the propeller showed tiles {sorted(tiles)}, want both "
        f"{T_SHIP_A} and {T_SHIP_B} — the animation clock is dead or stuck")


# ===========================================================================
# THE COST — the rail's own budget, read off the shipping binary
# ===========================================================================
def test_the_join_fits_its_frame_under_the_worst_case_input():
    """The gate the whole design was ruled on.

    TWO measurements, and the second is the one that decides. The SLHV latch
    pair gives the join's cost in master clocks; the propeller countdown gives
    the thing that actually matters — it decrements once per TICK, so if a
    frame's work ever overran, `sm_frame_sync` would park the loop on the next
    NMI, the tick would run one fewer time than the hardware frame counter
    advanced, and the countdown would repeat a value. Zero repeats over the
    window IS the statement "every frame's work fit in its frame".
    """
    prop_t = _sym("US_PROP_T")["start"]
    worst = {"left": True, "r": True, "b": True}
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        costs, repeats, prev = [], 0, m.read_u16(W, prop_t)
        for _ in range(240):
            m.advance(1, pad1=worst)
            cur = m.read_u16(W, prop_t)
            if cur == prev:
                repeats += 1
            prev = cur
            costs.append(_join_mc(m))
    assert repeats == 0, (
        f"{repeats} of 240 frames dropped a tick under the worst-case input — "
        "the join no longer fits beside the rail's other per-frame work")
    assert max(costs) < JOIN_MC_CEILING, (
        f"the join's worst frame cost {max(costs)} mc "
        f"({max(costs) / FRAME_MC:.1%} of a frame), over the "
        f"{JOIN_MC_CEILING} mc ceiling — measured at ~153,400")
    assert min(costs) > FRAME_MC // 8, (
        f"the join's cheapest frame cost only {min(costs)} mc, which is too "
        "little for 160 scanlines of composition — the latch pair is measuring "
        "something other than the join, so the ceiling above is vacuous")


# ===========================================================================
# THE SKY RAMP AND THE HORIZON FOG (piece A) — rgb_gradient, horizon-anchored
# ===========================================================================
# The playtest observation 1 was "the top 1/3rd of the screen above the horizon
# is a flat blue square". These read the CURE off the picture, and they read it
# against tools/gen_m7f_gradient.py rather than against a shape written here.
FLOOR_PAL_WORDS = 16                # the m7f_pal claim: CGRAM 0..15
CLOUD_PAL_AT = 160                  # the cloud_pal claim: OBJ palette 2
SHIP_COLS = range(96, 160)          # the airship's columns — OBJ is out of the
                                    #   colour math, so its pixels are not the
                                    #   ramp's and must not be sampled


def _tod(m):
    """The live day/night state: the clock phase, its table step, and which
    snapshot's ramp the cursor is pointing at.

    READ TO SELECT AN ORACLE ROW, never as the evidence that anything
    rendered — the same role `_pose` plays for the band table. Every assertion
    that uses it lands on pixels or on CGRAM.
    """
    phase = m.read_u16(W, A_CLOCK)
    step = phase >> GRAD.TOD_STEP_SHIFT
    snap = m.read_u16(W, A_FOG + 3 * FOG_ENT) // GRAD.SNAP_STRIDE
    return phase, step, snap


assert IDENT_GAP < GRAD.TOD_STEP_FRAMES, (
    "a byte-identity gap of one propeller period no longer fits inside a "
    "day/night step — the clock got faster than the frame's own animation and "
    "there is no window left in which two frames can be identical")


def _park_in_step(m):
    """Land on the FIRST frame of a time-of-day step.

    The day/night clock repaints CGRAM[0] and the COLDATA cursor every
    TOD_STEP_FRAMES frames, so "two frames render identically" is a
    claim about the SKIP only when both frames are inside one step. Parking
    first is what keeps those cases whole-frame instead of retreating to a
    sampled region. It also self-checks that the clock is running: a rail whose
    clock had died would never step and this raises rather than passing a
    byte-identity case for the wrong reason."""
    s0 = _tod(m)[1]
    for _ in range(GRAD.TOD_STEP_FRAMES + 2):
        m.advance(1)
        if _tod(m)[1] != s0:
            return
    raise AssertionError(
        "the day/night clock did not step in TOD_STEP_FRAMES+2 frames")


# The rows that carry ONLY the composed plane. Below the fog band, below the
# airship's box (y 96..128) and below every cloud (y 14..78), so what is left is
# terrain and the ship's shadow — and the shadow is a pure function of the
# altitude, which these cases hold still.
#
# STILL ONLY STABLE INSIDE ONE CLOCK STEP, because the day/night ambient
# rewrites the floor's own fifteen CGRAM words: the terrain's GEOMETRY holds
# but its colours do not. So every short-gap comparison below parks in a step
# first. The whole-frame claim is carried by the 2,048-frame arm, where all
# four clocks — palette, propeller, wind and the camera — close together.
FLOOR_ONLY_TOP = 130


def _floor_bytes(img):
    return _band_bytes(img, _top_row(img) + FLOOR_ONLY_TOP,
                       _top_row(img) + BAND_BOT)


def _band_bytes(img, y0, y1):
    px = img.load()
    return bytes(v for y in range(y0, y1)
                 for x in range(img.width) for v in px[x, y])


def _clamp31(v):
    return 31 if v > 31 else v


def _sky_rgb(zenith, deltas):
    """What a sky scanline must render: the backdrop word plus its COLDATA
    byte, per plane, clamped, then widened the way Mesen widens BGR555."""
    def e(v):
        return (v << 3) | (v >> 2)
    return tuple(e(_clamp31(zenith[p] + deltas[p])) for p in range(3))


def _cgram_5bit(m, index):
    b = m.read_bytes(C, 2 * index, 2)
    w = b[0] | b[1] << 8
    return (w & 31, (w >> 5) & 31, (w >> 10) & 31)


def _expected_sky(zenith, snap, scanline, horizon):
    """The ramp is anchored to the HORIZON, not to scanline 0: the last of its
    RAMP_LEN entries lands on the horizon line and the held zenith byte covers
    whatever is above it. That anchoring is the whole piece."""
    i = scanline - (horizon - GRAD.RAMP_LEN)
    if i < 0:
        return _sky_rgb(zenith, (0, 0, 0))
    return _sky_rgb(zenith, [GRAD.ramp_deltas(snap, p)[i] for p in range(3)])


@pytest.mark.parametrize("name,pad,frames", [
    ("the deck", {"l": True}, ALT_MAX_IDX + 20),
    ("the spawn", {}, 0),
    ("the ceiling", {"r": True}, ALT_MAX_IDX + 20),
])
def test_the_sky_is_the_generators_ramp_at_every_scanline(name, pad, frames,
                                                          tmp_path):
    """Piece A, EXACT, on every sky line of three altitudes.

    Not "there is a gradient" and not a monotonic trend: sky scanline L must
    render exactly `backdrop + ramp[L - (horizon - RAMP_LEN)]`, clamped, for
    every L above the horizon. Two independent things have to be right for that
    — the blob the build baked and the three header tables `fog_reanchor`
    writes in VBlank — so a wrong snapshot offset, a dropped plane, an
    off-by-one in the hold count or a stale anchor all move it.

    The backdrop word and the horizon are both read LIVE, so this is not a test
    of a pattern it designed: it asks the generator what the ROM's own
    CGRAM[0] and its own horizon imply, and then looks.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        if frames:
            m.advance(frames, pad1=pad)
            m.advance(4)                    # let the swap and the re-anchor land
        zenith = _cgram_5bit(m, 0)
        horizon = _geometry(m)["horizon"]
        _, _, snap = _tod(m)                # the clock runs: read it, do not assume
        img = _shot(m, tmp_path / f"ramp_{name.replace(' ', '_')}.png")
    top = _top_row(img)
    px = img.load()
    for sl in range(1, horizon):
        row = [px[x, top + sl] for x in range(img.width)]
        # THE MODAL COLOUR, not the whole set: OBJ draws over the sky band —
        # that is what the split is for — so the airship (32 px) and at most
        # one cloud (16 px) are legitimately in this row. Neither can win a
        # majority of 256, and everything else in the row is the backdrop plus
        # this line's COLDATA byte.
        got = max(set(row), key=row.count)
        share = row.count(got) / len(row)
        want = _expected_sky(zenith, snap, sl, horizon)
        assert got == want and share >= 0.75, (
            f"{name} (horizon {horizon}): sky scanline {sl} is {got} over "
            f"{share:.0%} of the row, but the ramp anchored to that horizon "
            f"says {want} — the COLDATA cursor and the split disagree")


def test_the_sky_ramp_is_not_flat_and_spans_the_band(tmp_path):
    """The playtest observation, stated as the thing that must NOT be true.

    The previous rail rendered ONE colour over the whole sky. A ramp that
    existed but moved by a shade or two would satisfy the exact test above
    (it answers to the generator, and the generator could be flat) and still be
    the flat blue square. So this asserts the SIZE of the change a player sees:
    the sky must take many distinct colours and its top and horizon must be far
    apart in the channel the ramp moves most.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        horizon = _geometry(m)["horizon"]
        img = _shot(m, tmp_path / "ramp_span.png")
    top = _top_row(img)
    px = img.load()
    rows = [px[0, top + sl] for sl in range(1, horizon)]
    assert len(set(rows)) >= 16, (
        f"the sky takes only {len(set(rows))} distinct colours over "
        f"{horizon - 1} scanlines — that is the flat-blue-square report, not a "
        "fix for it")
    lift = max(sum(rows[-1]) - sum(rows[0]), 0)
    assert lift >= 120, (
        f"top of sky {rows[0]} to horizon {rows[-1]} is a total channel lift "
        f"of {lift} — visible as a ramp only to a difference engine")


def test_the_fog_rides_the_moving_horizon_rather_than_a_fixed_scanline(tmp_path):
    """THE TEAR CASE, and the reason the fog is not a static table.

    Every other consumer of `rgb_gradient` has a fixed camera height, so its
    tables are indexed by scanline. Here the horizon travels 40 lines, and a
    scanline-indexed fog would stay behind at the deck horizon while the floor's
    first row walked away from it — white haze floating in open sky, and a hard
    un-hazed seam at the real horizon.

    THE CATCH SURFACE IS THE SCREENSHOT, deliberately: under that failure every
    DP word is still correct (the horizon, the band table and the split all
    agree — only the COLDATA cursor is stale), so a state assertion cannot see
    it. What the picture shows is that the floor's FIRST rendered row carries
    the fog's peak. Checked at two altitudes 40 scanlines apart, and checked
    both ways round: the row must be inside the set the live anchor predicts and
    OUTSIDE the untinted palette, so neither "no fog anywhere" nor "fog nailed
    to line 64" can pass.
    """
    def sample(m, tag):
        horizon = _geometry(m)["horizon"]
        pal = [_cgram_5bit(m, i) for i in range(FLOOR_PAL_WORDS)]
        img = _shot(m, tmp_path / f"fog_{tag}.png")
        top = _top_row(img)
        px = img.load()
        row = {px[x, top + horizon] for x in range(img.width)
               if x not in SHIP_COLS}
        return horizon, pal, row, _tod(m)[2]

    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(ALT_MAX_IDX + 20, pad1={"l": True})       # the deck
        m.advance(4)
        low = sample(m, "deck")
        m.advance(2 * ALT_MAX_IDX + 40, pad1={"r": True})   # the ceiling
        m.advance(4)
        high = sample(m, "ceiling")

    assert high[0] - low[0] >= 30, (
        f"the horizon only moved {high[0] - low[0]} scanlines between the deck "
        f"and the ceiling — this case cannot discriminate")

    for tag, (horizon, pal, row, snap) in (("deck", low), ("ceiling", high)):
        peak = [GRAD.fog_deltas(snap, p)[0] for p in range(3)]
        assert min(peak) > 0, (
            f"{tag}: snapshot {snap}'s fog peak is zero — nothing to catch")
        hazed = {_sky_rgb(c, peak) for c in pal}
        clear = {_sky_rgb(c, (0, 0, 0)) for c in pal}
        assert row <= hazed, (
            f"{tag}: the floor's first row (scanline {horizon}) renders "
            f"{sorted(row - hazed)[:3]}, which the fog's PEAK entry added to no "
            f"palette colour produces — the cursor is not anchored here")
        assert not (row <= clear), (
            f"{tag}: the floor's first row (scanline {horizon}) is pure "
            f"palette — the fog is not landing on the horizon at all")


def test_the_backdrop_word_boots_on_the_day_snapshots_zenith():
    """The two generators agree AT FRAME 1, checked on the silicon.

    `gen_m7f_assets.py` bakes CGRAM[0] into the floor palette and
    `gen_m7f_gradient.py` builds the ramp as a DELTA from it, so a change to
    either alone shows up here as a sky that starts from the wrong colour — and
    everywhere else as a gradient that saturates in its first few lines, which
    is the reported flat square again.

    AT FRAME 1 specifically, because the clock then walks the zenith away from
    it: `tod_arm` seeds the phase ON the day segment so the palette the ROM
    uploaded and the table the clock indexes name the same colour on the frame
    where both are in force. Seeded at zero they would disagree for the eight
    frames before the first step landed.
    """
    with Machine(str(ROM)) as m:
        m.advance(2)                                # before the clock has moved
        got, (_, step, _) = _cgram_5bit(m, 0), _tod(m)
    want = GRAD.SNAPSHOTS[GRAD.DAY_INDEX][1]
    assert got == want, (
        f"CGRAM[0] is 5-bit {got} at step {step}, but gen_m7f_gradient's boot "
        f"snapshot ('{GRAD.SNAPSHOTS[GRAD.DAY_INDEX][0]}') is built as a delta "
        f"from {want} — the palette and the clock table have drifted")


# ===========================================================================
# THE DAY/NIGHT CLOCK (piece D)
# ===========================================================================
def test_the_clock_walks_all_four_snapshots_and_returns_to_where_it_started(
        tmp_path):
    """Piece D as a CYCLE, not a sample — the axis driven all the way round.

    Nothing is held: the airship hovers, so the altitude and the heading are
    fixed and the only thing moving is the time of day. That isolation is what
    makes the picture differences below attributable.

    Three things have to hold together and each would pass on its own with the
    feature broken: CGRAM[0] must equal the generator's interpolated zenith at
    the LIVE step (a clock that advanced but indexed wrongly fails here); all
    four snapshots must actually come into force (a clock stuck in one segment
    passes the first check forever); and the SKY the player sees must differ
    between the four segment centres (a clock that swaps CGRAM and the ramp
    while the split hides them would pass both of the others).

    Then it must come back. A cycle that walks away and stops — a phase that
    saturates rather than wrapping — is the failure a one-way sweep locks in,
    and this rail has that lesson written into its own docstring.
    """
    seg = GRAD.TOD_SEG_FRAMES
    seen_snaps, sky_rows, first = set(), [], None
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for i in range(GRAD.TOD_STEPS // 2):            # half a step's worth
            m.advance(2 * GRAD.TOD_STEP_FRAMES)
            _, step, snap = _tod(m)
            seen_snaps.add(snap)
            got = _cgram_5bit(m, 0)
            want = GRAD.tod_zenith(step)
            assert got == want, (
                f"clock step {step}: CGRAM[0] is 5-bit {got}, the table says "
                f"{want} — the phase advanced but the row it indexes did not "
                f"follow")
        # ...and the picture, at the centre of each of the four segments.
        for i, (name, _z, _h) in enumerate(GRAD.SNAPSHOTS):
            m.advance(1)
            _, _, snap = _tod(m)
            while snap != i:
                m.advance(GRAD.TOD_STEP_FRAMES)
                _, _, snap = _tod(m)
            img = _shot(m, tmp_path / f"tod_{name}.png")
            top = _top_row(img)
            horizon = _geometry(m)["horizon"]
            sky_rows.append((name, tuple(
                img.load()[0, top + y] for y in range(4, horizon, 8))))
        # a full further cycle must land back where it started
        _, step0, snap0 = _tod(m)
        zen0 = _cgram_5bit(m, 0)
        m.advance(GRAD.TOD_CYCLE_FRAMES)
        assert (_tod(m)[1], _tod(m)[2]) == (step0, snap0), (
            f"a full {GRAD.TOD_CYCLE_FRAMES}-frame cycle did not return the "
            f"clock to step {step0} — the phase is not wrapping")
        assert _cgram_5bit(m, 0) == zen0, "the zenith did not come back round"

    assert seen_snaps == set(range(len(GRAD.SNAPSHOTS))), (
        f"the clock only ever put {sorted(seen_snaps)} in force out of "
        f"{list(range(len(GRAD.SNAPSHOTS)))} — it is not walking the cycle")
    for a in range(len(sky_rows)):
        for b in range(a + 1, len(sky_rows)):
            (na, ra), (nb, rb) = sky_rows[a], sky_rows[b]
            assert ra != rb, (
                f"the sky renders identically at {na} and {nb} — the clock is "
                f"moving state that never reaches the picture")
    assert seg * len(GRAD.SNAPSHOTS) == GRAD.TOD_CYCLE_FRAMES


def test_the_snapshot_swap_does_not_pop_the_horizon(tmp_path):
    """The one frame in the cycle where a step could be visible, bounded.

    The zenith is interpolated every eight frames, but the ramp is a ROM blob
    and swaps in ONE — so the horizon's haze, which is `zenith + ramp[last]`,
    can step at a segment boundary. The generator tunes the four snapshots so
    that step is small; this is what holds it to that, on the rendered horizon
    line rather than on the constants, by walking the clock one step at a time
    across a boundary and bounding the largest single-step change.

    The bound is per channel and generous (6 of 31) — the point is to catch a
    snapshot retune that puts a flash on the horizon, not to pin the palette.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        _, _, snap = _tod(m)
        while _tod(m)[2] == snap:                   # walk up to a boundary
            m.advance(GRAD.TOD_STEP_FRAMES)
        m.advance(2 * GRAD.TOD_STEP_FRAMES)         # ...and a little past it
        horizon = _geometry(m)["horizon"]
        seen, snaps = [], []
        for i in range(3 * GRAD.TOD_SEG_STEPS):     # three segments, step by step
            m.advance(GRAD.TOD_STEP_FRAMES)
            img = _shot(m, tmp_path / "pop.png")
            top = _top_row(img)
            seen.append(img.load()[0, top + horizon - 1])   # the haze line
            snaps.append(_tod(m)[2])
    assert len(set(snaps)) >= 3, (
        f"only {len(set(snaps))} snapshots came into force across three "
        f"segments — the walk did not cross the boundaries it is bounding")
    worst = max((max(abs(a - b) for a, b in zip(p, q)), i)
                for i, (p, q) in enumerate(zip(seen, seen[1:])))
    assert worst[0] <= 6 * 8, (
        f"the horizon line jumps by {worst[0] // 8} of 31 in one clock step "
        f"(step {worst[1]}: {seen[worst[1]]} -> {seen[worst[1] + 1]}) — a "
        f"snapshot's haze delta has drifted away from its neighbours' and the "
        f"swap will read as a flash")


def _park_on_segment(m, seg):
    """Advance to the exact step a time-of-day segment opens on."""
    want = seg * GRAD.TOD_SEG_STEPS
    for _ in range(GRAD.TOD_CYCLE_FRAMES // GRAD.TOD_STEP_FRAMES + 2):
        if _tod(m)[1] == want:
            return
        m.advance(GRAD.TOD_STEP_FRAMES)
    raise AssertionError(f"never reached segment {seg}'s opening step")


def test_the_clock_repaints_the_whole_palette_and_the_ground_goes_dark(
        tmp_path):
    """Piece D's other half: the GROUND knows what time it is.

    Colour math on this rail can only ADD — the sky and the floor share one
    global subtract bit — so the COLDATA ramp can light the horizon at dawn but
    can never darken the terrain at night. The first render of the cycle showed
    exactly that: a convincing night sky over a noon-bright landscape. The clock
    therefore rewrites all sixteen CGRAM words, not just the backdrop.

    Both halves are asserted because either alone would pass on a broken build.
    The words must equal the generator's table EXACTLY at two opposite
    segments — a palette that was rewritten with the wrong row fails here. And
    the rendered FLOOR must actually be darker at night — a palette that
    changed in CGRAM while the plane rendered from somewhere else would pass
    the first check and fail this one.
    """
    base = GRAD.floor_palette_5bit()
    shots = {}
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        horizon = _geometry(m)["horizon"]
        for seg, name in ((GRAD.DAY_INDEX, "day"), (3, "night")):
            _park_on_segment(m, seg)
            step = _tod(m)[1]
            got = ([m.read_u16(C, 2 * i) for i in range(FLOOR_PAL_WORDS)]
                   + [m.read_u16(C, 2 * (CLOUD_PAL_AT + i))
                      for i in range(GRAD.CLOUD_WORDS)])
            want = GRAD.tod_palette(step, base)
            assert got == want, (
                f"{name} (step {step}): CGRAM holds "
                f"{[hex(v) for v in got[:4]]}, the table says "
                f"{[hex(v) for v in want[:4]]} — the palette row and the clock "
                f"have come apart")
            shots[name] = _shot(m, tmp_path / f"amb_{name}.png")
    top = _top_row(shots["day"])
    def floor_luma(img):
        px = img.load()
        rows = range(top + horizon + GRAD.FOG_LEN, top + BAND_BOT)
        vals = [sum(px[x, y]) for y in rows for x in range(0, img.width, 4)]
        return sum(vals) / len(vals)
    day, night = floor_luma(shots["day"]), floor_luma(shots["night"])
    assert night < day * 0.6, (
        f"the terrain reads {night:.0f} at night against {day:.0f} at noon — "
        f"the palette moved but the ground did not get dark, which is the "
        f"'night sky over a noon landscape' the ambient exists to fix")


# ===========================================================================
# THE CLOUDS (piece B') — drift, rotation parallax, and the moving-horizon cull
# ===========================================================================
CLOUD_SLOT, CLOUD_N, CLOUD_H = 4, 4, 16
OAM_PARK_Y = 0xF0
# The clouds' x wraps over a period 16 px wider than the screen, so one is
# always entering from the left while another leaves on the right. A delta read
# across that seam has to be taken the SHORT way, exactly as the heading's is.
CLOUD_SPAN = 256 + CLOUD_H


def _clouds(m):
    """Every cloud's rendered (x, y), read from OAM itself.

    X is NINE bits — the low byte in the entry, bit 8 in the hi table — and it
    is read as such because the wrap period runs from -16, so a cloud entering
    from the left is ALWAYS carrying X9. Reading only the low byte would report
    it at x = 240 on the right of the screen, which is the exact bug the bit
    exists to prevent.
    """
    low = m.read_bytes(O, CLOUD_SLOT * 4, CLOUD_N * 4)
    hi = m.read_bytes(O, 512 + CLOUD_SLOT // 4, 1)[0]
    out = []
    for i in range(CLOUD_N):
        x = low[i * 4] | ((hi >> (2 * i)) & 1) << 8
        if x >= 256:
            x -= 512                                # the PPU's signed nine bits
        out.append((x, low[i * 4 + 1]))
    return out


def test_the_clouds_drift_on_the_wind_and_slide_against_both_turns(tmp_path):
    """Piece B', driven through BOTH turn directions AND idle.

    Three cases, and the pair of turns is the crux: a parallax term with the
    WRONG SIGN still moves the clouds, still moves them by the right amount,
    and still passes any single-direction case — it just paints them on the
    canopy instead of leaving them in the world. So this asserts the ORDER of
    the three: turning one way must move the clouds further along than idle
    drift does, and turning the other must move them back the other side of it.

    Read off OAM, and the deltas are taken on the SAME slot across a fixed
    number of frames, so the wind term is common to all three and cancels out
    of the comparison.
    """
    def run(pad, frames=24):
        with Machine(str(ROM)) as m:
            m.advance(BOOT)
            m.advance(4, pad1={"r": True})          # a little sky to be seen in
            before = _clouds(m)[0][0]
            head0 = _pose(m)[0]
            m.advance(frames, pad1=pad)
            # The heading axis is 256 units ROUND, so a turn is read the short
            # way — a raw subtraction reports a left turn of 24 as a right turn
            # of 232 and the two arms would look like the same direction.
            turn = (_pose(m)[0] - head0) & 0xFF
            if turn >= 0x80:
                turn -= 0x100
            slide = (_clouds(m)[0][0] - before) % CLOUD_SPAN
            if slide > CLOUD_SPAN // 2:
                slide -= CLOUD_SPAN
            return slide, turn

    idle, idle_turn = run({})
    left, left_turn = run({"left": True})
    right, right_turn = run({"right": True})

    assert idle_turn == 0, "the idle arm turned — it is not the control it claims"
    assert left_turn != 0 and right_turn != 0, (
        f"neither turn moved the heading ({left_turn}, {right_turn}) — the "
        f"parallax arms are vacuous")
    assert (left_turn > 0) != (right_turn > 0), (
        "left and right turned the heading the same way — the two arms are "
        "not opposite")
    assert idle > 0, (
        f"the clouds did not drift with nothing held ({idle} px in 24 frames) "
        f"— the wind term is dead")
    lo, hi = sorted((left, right))
    assert lo < idle < hi, (
        f"the turns did not straddle the idle drift: left {left}, idle "
        f"{idle}, right {right}. The clouds must slide OPPOSITE the turn — a "
        f"parallax term of the wrong sign moves them by the right amount on "
        f"the wrong side of this and reads as a sky painted on the canopy")


def test_the_clouds_are_culled_against_the_moving_horizon(tmp_path):
    """The cull, at both ends of the altitude axis — an OAM census.

    The horizon travels 40 scanlines, so how much sky there is to put clouds in
    is f(altitude). Two claims, and the second is what makes the first mean
    something: NO drawn cloud's box may reach the band's first scanline at
    either altitude (a cloud sitting on the terrain is the defect), and MORE
    clouds must be drawn at the ceiling than at the deck (a rail that simply
    parked all four would satisfy the first claim perfectly).
    """
    seen = {}
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        m.advance(ALT_MAX_IDX + 20, pad1={"l": True})
        m.advance(4)
        seen["deck"] = (_geometry(m)["horizon"], _clouds(m))
        m.advance(2 * ALT_MAX_IDX + 40, pad1={"r": True})
        m.advance(4)
        seen["ceiling"] = (_geometry(m)["horizon"], _clouds(m))

    drawn = {}
    for tag, (horizon, clouds) in seen.items():
        live = [(x, y) for x, y in clouds if y != OAM_PARK_Y]
        drawn[tag] = len(live)
        for x, y in live:
            assert y + CLOUD_H <= horizon, (
                f"{tag}: a cloud is drawn at y={y}, and its {CLOUD_H}px box "
                f"reaches scanline {y + CLOUD_H} — past the horizon at "
                f"{horizon}. That is a cloud sitting on the ground")
    assert seen["ceiling"][0] - seen["deck"][0] >= 30, "the horizon barely moved"
    assert drawn["ceiling"] > drawn["deck"], (
        f"the same {drawn['deck']} clouds are drawn at the deck and at the "
        f"ceiling — the cull is not following the horizon, so the first "
        f"assertion is passing on a rail that could be parking all four")
    assert drawn["ceiling"] == CLOUD_N, (
        f"only {drawn['ceiling']} of {CLOUD_N} clouds survive at the ceiling, "
        f"where the sky is 104 scanlines deep — the cull is too eager")
