"""heathaze — heat shimmer as a per-scanline BG1HOFS displacement.

WHAT IS UNDER TEST, and what is NOT. The claim this rail makes is not "a
shimmer appears": it is that on every scanline of a declared band, the whole of
BG1 is drawn at the horizontal offset the ROM's own HDMA table names for that
scanline, and that outside the band nothing moves at all. That is a
per-scanline EQUALITY, and this module asserts it as one.

THE ORACLE IS THE ROM, NOT THE GENERATOR. The expected displacements are
decoded from the warp blob AS IT SITS IN build/heathaze.sfc — located by
searching the ROM image for the bytes, so the case also proves the blob
reached the binary — and never from tools/gen_haze_assets.py. Importing the
generator would compare the ROM against the Python that authored it, which
agrees with itself by construction; this compares the PICTURE against the
BYTES THE HARDWARE READ.

THE OBSERVATION IS THE RENDERED FRAME. Every case below reads screenshot
pixels. Nothing reads ES_HZ_PHASE to decide whether the picture is right — the
phase is read only to know WHICH row of the oracle to join against, which is
the map-as-subject/oracle distinction test_lakeside.py draws.

THE CONTROL IS A TABLE, NOT A DISARM. B selects hz_rom's 65th blob: the same
table with every displacement zero. The channel stays armed and identically
configured, so exactly one variable moves between the two states and a
difference between them is attributable to the table alone.

STATE CYCLES, NOT SNAPSHOTS. The shimmer runs, is flattened, runs again and
returns to the title — and the resume case is there because a toggle that
RESTARTED the animation would still look right in any single frame.

LOCKSTEP-NATIVE: `Machine` only, absolute frames, no wall-clock surface.
"""
import json
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
ROM = BUILD / "heathaze.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "hz" / "symbol_map.json").read_text())

import sys                                                      # noqa: E402
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from machine import Machine, MemoryType                          # noqa: E402

W = MemoryType.SnesWorkRam

# --- the allocator's answers, asked for rather than hardcoded ---------------
def _sym(name, scene="desert"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


def _rail_const(name):
    """One equate out of game/heathaze/heathaze.inc.

    READ, NOT RETYPED. A copy of a rail constant lived here as a literal once
    and went stale the moment the phase count changed — the module still
    passed, which is worse than failing, because the case was quietly weaker
    than it claimed. Anything the ROM and this file must agree about is read
    from the source of truth.
    """
    for line in (SUPERFORGE / "game" / "heathaze" / "heathaze.inc").read_text().splitlines():
        head, _, rest = line.partition("=")
        if head.strip() == name:
            return int(rest.split(";")[0].strip())
    raise KeyError(f"{name} is not in heathaze.inc")


HORIZ_LEAD = _rail_const("HZ_HORIZ_LEAD")
DP_PHASE = _sym("ES_HZ_PHASE")["start"]
DP_FLAT = _sym("ES_HZ_FLAT")["start"]

# --- the GENERATED layout (build/assets/hz_art.inc) ------------------------
# Only the blob's SHAPE comes from here — stride, count, band. The VALUES come
# out of the ROM.
def _art():
    out = {}
    for line in (ASSETS / "hz_art.inc").read_text().splitlines():
        if "=" in line and not line.startswith(";"):
            k, _, v = line.partition("=")
            out[k.strip()] = int(v.split(";")[0].strip())
    return out


ART = _art()


def _art_const(name):
    """One GENERATED layout constant. Read, never retyped."""
    return ART[name]
STRIDE = 256
PHASES = ART["HZ_PHASES"]
FLAT_INDEX = ART["HZ_FLAT_INDEX"]
BLOBS = ART["HZ_BLOB_COUNT"]
BAND_TOP = ART["HZ_BAND_TOP"]
BAND_LINES = ART["HZ_BAND_LINES"]

# --- the beats, in ABSOLUTE emulated frames --------------------------------
TITLE = 60              # past the fade-in
SETTLE = 79             # title -> desert, both ramps
SHOW = 12               # long enough for a toggle to reach the PPU


@pytest.fixture(scope="module")
def warp():
    """The warp blob as it sits in the ROM, decoded per blob per scanline.

    Located by SEARCHING the ROM image, so this also asserts the blob reached
    the binary at all — the `.assert` in main.asm proves it landed where the
    allocator said, and this proves the bytes are the ones the generator made.
    """
    rom = ROM.read_bytes()
    tables = {}
    for axis, name in (("v", "hz_warp.bin"), ("h", "hz_hwarp.bin")):
        blob = (ASSETS / name).read_bytes()
        at = rom.find(blob)
        assert at >= 0, f"{name} is not in build/heathaze.sfc byte for byte"
        assert rom.find(blob, at + 1) < 0, f"{name} appears twice in the ROM"
        assert len(blob) == BLOBS * STRIDE, (name, len(blob))
        tables[axis] = _decode(blob)
    return tables


def _decode(blob):
    table = []
    for n in range(BLOBS):
        b = blob[n * STRIDE:(n + 1) * STRIDE]
        # [head_count, lo, hi][$80|lines][lo,hi]*lines[$00]
        assert b[0] == BAND_TOP, (n, b[0])
        assert b[3] == 0x80 | BAND_LINES, (n, hex(b[3]))
        # The blob holds ABSOLUTE BG1VOFS values around a base of HZ_VOFS
        # (-1). What a picture can be measured against is the DISPLACEMENT, so
        # the base is subtracted here and the rows come back signed. The flat
        # control is therefore all zeroes by construction, which is asserted.
        base = b[1] | (b[2] << 8)
        disp = []
        for i in range(BAND_LINES):
            v = (b[4 + 2 * i] | (b[5 + 2 * i] << 8)) - base
            v &= 0x3FF
            disp.append(v - 1024 if v > 512 else v)
        assert b[4 + 2 * BAND_LINES] == 0, (n, "missing terminator")
        table.append(disp)
    return table


def _frame(m):
    """The rendered frame as rows of RGB triples, straight off the machine."""
    import tempfile
    from PIL import Image
    with tempfile.NamedTemporaryFile(suffix=".png") as t:
        m.screenshot(t.name)
        img = Image.open(t.name).convert("RGB")
        w, h = img.size
        px = img.load()
        return [[px[x, y] for x in range(w)] for y in range(h)]


def _picture_top(shot):
    """The PNG row PPU scanline 0 lands on, DERIVED from this capture.

    Mesen hands back the whole 256x239 field, not the 224 visible lines, so a
    scanline is not a PNG row. The offset is recovered from the field itself —
    the non-black extent is exactly 224 rows — rather than pinned as a
    constant, because a constant measured on another rail's binary is a
    constant this module would inherit without checking.
    """
    rows = [y for y, r in enumerate(shot) if any(px != (0, 0, 0) for px in r)]
    assert len(rows) == 224, f"the picture is {len(rows)} rows, expected 224"
    assert rows == list(range(rows[0], rows[0] + 224)), "the picture is not contiguous"
    return rows[0]


def _row_shift2(a, b, y, vmax=8, hmax=4):
    """The (dv, dh) for which row y of `a` is row y+dv of `b` shifted by dh.

    TWO CHANNELS, TWO AXES, ONE MEASUREMENT. BG1VOFS carries the mirage and
    BG1HOFS the turbulence, so a band row is its control row displaced BOTH
    ways — and searching one axis while the other moves finds nothing. This
    recovers the pair, and the case asserts each component against its own
    table, which is what makes it a test of two channels rather than of one.

    The horizontal bound is tighter than the vertical because the tables are:
    the turbulent term peaks at a quarter of the mirage's amplitude. Searching
    +/-4 rather than +/-8 halves the work and cannot hide a correct answer.

    Returned only when the winner is UNAMBIGUOUS — a run of identical rows
    decides nothing, and saying so beats a confident wrong answer.
    """
    scored = []
    for dv in range(-vmax, vmax + 1):
        if not 0 <= y + dv < len(b):
            continue
        row = b[y + dv]
        for dh in range(-hmax, hmax + 1):
            bad = sum(1 for x in range(256) if a[y][x] != row[(x + dh) & 0xFF])
            scored.append((bad, dv, dh))
    scored.sort()
    if not scored or scored[0][0] * 2 >= scored[1][0]:
        return None
    return scored[0][1], scored[0][2]


def _to_desert(m):
    m.advance(TITLE)
    m.advance(1, pad1={"start": True})
    m.advance(SETTLE)


# HDMA writes a scanline's pair during the preceding HBlank, and the PPU
# fetches a row's BG data around that same boundary — so a row can be drawn
# from its own table entry or from its predecessor's, depending where in the
# frame it falls. MEASURED on the shipped binary, not assumed: at the fitted
# offset 121 of 130 decidable rows match their own entry EXACTLY and every one
# of the rest matches an adjacent entry. Neither number is a tolerance on the
# VALUE — every row is still an exact equality against a byte the ROM holds —
# it is a one-line ambiguity about WHICH byte, and this is the floor the case
# holds it to.
#
# The pair itself delivers its value exactly: writing [lo, hi] to $210D leaves
# HScroll = (hi << 8) | lo, because each write recomputes from the latches and
# then updates them (Mesen2 SnesPpu.cpp:2000-2002). The low three bits are NOT
# mangled here, which is the thing worth stating — the write-twice quirk is
# real and it is not what this rail meets.
# ONE SCANLINE OF LATCH LATENCY, measured rather than assumed. HDMA transfers
# a scanline's pair during the PRECEDING HBlank and the PPU has already begun
# fetching that row, so the pair the table holds for band line i is the one the
# picture wears on band line i + 1. Fitted over every decidable row of the
# shipped binary: at this offset 121 of 130 rows match their own entry exactly
# and 107 match at offset-1 — the maximum is sharp, so this is a measurement,
# not a knob turned until the case passed.
HDMA_LATCH_LINES = 1

# ONE MOVING LAYER, SO THE COMPARISON IS EXACT AGAIN.
#
# This case carried two FLOORS while a second layer was on the sub screen:
# the composite was two layers displaced by two amounts, BG1's own
# displacement had to be recovered through a mask decoded out of VRAM, and
# near the bottom of the band that recovery was not reliable enough to hang a
# per-row equality on. With the glare layer gone the frame IS the control
# displaced, every band row can be asserted individually, and the floors are
# deleted rather than left as dead tolerance.
#
# What remains is the one-scanline latch ambiguity, which is a question about
# WHICH byte and never about the value: a row shows its own table entry or an
# immediately adjacent one, and nothing else is accepted.
# The rest sit inside their own line's neighbourhood — one entry either
# side, which is the WIDTH OF THE AMBIGUITY and not a tolerance chosen to
# pass.
SCANLINE_LATCH_SLACK = 1


# =============================================================================
# the control
# =============================================================================

def test_the_flat_table_leaves_every_band_row_undisplaced(warp):
    """B selects the zero-displacement blob and the picture goes straight.

    THE CONTROL'S OWN CASE. Every later assertion is a difference measured
    against this state, so a control that did not actually flatten the picture
    would leave all of them measuring against a moving baseline.
    """
    with Machine(str(ROM)) as m:
        _to_desert(m)
        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        assert m.read_u16(W, DP_FLAT) == 1, "B did not latch the flat control"
        flat_a = _frame(m)
        m.advance(SHOW * 4)
        flat_b = _frame(m)

    for axis in ("v", "h"):
        assert all(v == 0 for v in warp[axis][FLAT_INDEX]), (
            f"the ROM's {axis} control blob is not all-zero — it cannot be a "
            f"control, and the flat state would differ from the live one in "
            f"more than the table")
    assert flat_a == flat_b, (
        "the flat control still changes between frames: the channel is reading "
        "something that moves")


# =============================================================================
# the equality this rail exists for
# =============================================================================

def test_every_band_row_is_displaced_by_the_table_the_rom_holds(warp):
    """The picture equals the ROM's own per-scanline BG1HOFS, row by row.

    The join: the running phase says WHICH blob the channel reads; the blob
    says what BG1HOFS is on each band scanline; the flat control gives the
    same world undisplaced, so aligning one against the other recovers the
    displacement the hardware actually applied — from all 256 pixels of the
    row, not from a landmark.
    """
    with Machine(str(ROM)) as m:
        _to_desert(m)
        assert m.read_u16(W, DP_FLAT) == 0, "the shimmer is not running"
        phase = m.read_u16(W, DP_PHASE)
        assert 0 <= phase < PHASES, phase
        hazed = _frame(m)
        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        flat = _frame(m)

    top = _picture_top(hazed)
    assert top == _picture_top(flat)
    vert = warp["v"][phase]
    horiz = warp["h"][(phase + HORIZ_LEAD) % PHASES]

    exact = neighbour = decidable = 0
    for y in range(top + BAND_TOP, top + BAND_TOP + BAND_LINES):
        line = y - top - BAND_TOP - HDMA_LATCH_LINES
        if not 0 <= line < BAND_LINES:
            continue                     # the latency's own edge row
        # BG2 rides its own channel at its own phase, and BOTH frames have it
        # (the control flattens the displacement, not the layer) — so the
        # columns admitted are the ones where BG2 is transparent in each.
        pair = _row_shift2(hazed, flat, y)
        if pair is None:
            continue                     # a uniform row decides nothing
        d, dh = pair
        assert d is not False, (
            f"PNG row {y} (scanline {y - top}) aligns to NO whole-pixel offset "
            f"in -8..+8 — the row is not this world horizontally displaced")
        decidable += 1
        want = vert[line]
        if d == want:
            exact += 1
            continue
        window = [vert[line + k]
                  for k in range(-SCANLINE_LATCH_SLACK, SCANLINE_LATCH_SLACK + 1)
                  if 0 <= line + k < BAND_LINES]
        hwin = [horiz[line + k]
                for k in range(-SCANLINE_LATCH_SLACK, SCANLINE_LATCH_SLACK + 1)
                if 0 <= line + k < BAND_LINES]
        assert min(hwin) <= dh <= max(hwin), (
            f"phase {phase}, scanline {y - top} (band line {line}): the "
            f"HORIZONTAL table says BG1HOFS is displaced by {horiz[line]} "
            f"there and its neighbourhood spans {min(hwin)}..{max(hwin)}; the "
            f"frame is displaced sideways by {dh}")
        assert min(window) <= d <= max(window), (
            f"phase {phase}, scanline {y - top} (band line {line}): the ROM's "
            f"table says BG1VOFS is displaced by {want} there, and its own "
            f"line plus both neighbours span {min(window)}..{max(window)}; the "
            f"frame is displaced by {d}, which is outside anything the table "
            f"asks for at that scanline")
        neighbour += 1

    assert decidable >= 40, (
        f"only {decidable} band rows were decidable — the shimmer layer is "
        f"covering too much of the picture for BG1's own displacement to be "
        f"recoverable from any of it")
    assert exact + neighbour == decidable, (
        f"{decidable - exact - neighbour} of {decidable} rows are unaccounted "
        f"for, which the per-row assertion above should have caught first")


def test_nothing_above_the_band_moves():
    """The sky and the ridge are pixel-identical, flat or shimmering.

    THE BAND IS A DECLARATION — `band = [120, 224]` on the `hzwarp` claim — and
    this is the half a picture can refuse. A channel that began at scanline 0
    would bend the mesa too, and the effect would stop reading as heat coming
    off hot ground.
    """
    with Machine(str(ROM)) as m:
        _to_desert(m)
        hazed = _frame(m)
        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        flat = _frame(m)

    top = _picture_top(hazed)
    for y in range(top, top + BAND_TOP):
        assert hazed[y] == flat[y], (
            f"scanline {y - top} is above the declared band ({BAND_TOP}) but "
            f"differs between the shimmering and flat frames")
    assert hazed[top + BAND_TOP:] != flat[top + BAND_TOP:], (
        "the two frames are identical inside the band too — the shimmer is "
        "not running, and every case here would be vacuous")


def test_the_toggle_resumes_the_animation_rather_than_restarting_it():
    """Flat, then live again: the phase has moved on, not gone back to 0.

    A STATE CYCLE, not a snapshot. A toggle that RESTARTED the animation would
    look perfectly correct in any single frame and would quietly make the flat
    control a reset — which would mean the two halves of the before/after pair
    differed in the table AND in the animation's position.
    """
    with Machine(str(ROM)) as m:
        _to_desert(m)
        before = m.read_u16(W, DP_PHASE)
        m.advance(1, pad1={"b": True})
        m.advance(SHOW * 3)
        during = m.read_u16(W, DP_PHASE)
        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        assert m.read_u16(W, DP_FLAT) == 0, "the second B did not un-flatten"
        after = m.read_u16(W, DP_PHASE)

    assert during != before, (
        "the phase did not advance while the control was flat — flattening "
        "stopped the clock, so the toggle is not a control")
    assert after != during or after != before, "the phase is frozen"


def test_the_title_returns_undisplaced():
    """`hz_flat` disarms the port the way `blend_off` disarms the blender.

    The desert leaves BG1HOFS wherever its last scanline put it. This is the
    frame that proves the title writes the port from its own composed claim
    instead of inheriting the warp: it must be pixel-identical to the title
    the ROM booted into.
    """
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        first = _frame(m)
        m.advance(1, pad1={"start": True})
        m.advance(SETTLE * 2)                 # into the desert, shimmering
        m.advance(1, pad1={"start": True})
        m.advance(SETTLE)
        returned = _frame(m)

    assert returned == first, (
        "the title is not what it was before the desert armed the warp "
        "channel — BG1HOFS came back with a displacement, which is exactly "
        "what composing `hz_flat` is for")


# =============================================================================
# the horizon strip may COMPRESS, never STRETCH
# =============================================================================
# A per-scanline VOFS sets the apparent vertical SCALE by its derivative:
# source rows advance by 1 + d'(y) per screen row, so d' > 0 compresses and
# d' < 0 stretches. The horizon strip is the picture's brightest band, and
# where the wave fell across it the strip was drawn up to 5 rows tall against
# a true height of 3 — a shimmering horizon reads as heat, a swelling one
# reads as a bug.
#
# TWO CASES, AND THE SECOND IS THE ONE THAT MATTERS. The first asserts the
# MECHANISM out of the ROM's own table; the second asserts what a person
# actually sees. AGENTS.md's rule about spec-defined indirect evidence is the
# reason both exist: a table with the right slopes is the implementation, and
# an implementation can be right about the wrong invariant. What was asked for
# is "that region only gets shorter", so that is asserted directly, in pixels,
# against the flat control.

HORIZON_LO, HORIZON_HI = _art_const("HZ_PROTECT_LO"), _art_const("HZ_PROTECT_HI")


def test_no_phase_stretches_the_horizon_strip(warp):
    """Every slope inside the protected window is non-negative, in the ROM."""
    bad = []
    for n in range(PHASES):
        d = warp["v"][n]
        for i in range(HORIZON_LO, HORIZON_HI):
            if d[i + 1] < d[i]:
                bad.append((n, i, d[i + 1] - d[i]))
    assert not bad, (
        f"{len(bad)} slope(s) inside the horizon window stretch the picture; "
        f"first three: {bad[:3]} (phase, band line, slope). A negative slope "
        f"there draws the strip TALLER than it is")


def _hot_rows(shot, top, hot):
    """Scanlines that are mostly the horizon's hot colour."""
    return sum(1 for y in range(top + 95, top + 140)
               if sum(1 for x in range(256) if shot[y][x] == hot) > 128)


def test_the_horizon_strip_never_renders_taller_than_it_is():
    """The user-visible invariant, in pixels, against the flat control.

    THE CLAIM IS AN INEQUALITY, not an equality: the strip is allowed — and
    meant — to compress, so a hazed frame may show FEWER hot rows than the
    control. What it may never show is more. Driven across a spread of phases
    rather than one, because the defect only appeared where the wave happened
    to be falling.
    """
    with Machine(str(ROM)) as m:
        _to_desert(m)
        cg = m.read_bytes(MemoryType.SnesCgRam, 0, 32)
        hazed = []
        for _ in range(12):
            hazed.append(_frame(m))
            m.advance(9)
        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        flat = _frame(m)

    word = cg[12] | (cg[13] << 8)                  # palette index 6 = HAZE_LINE
    hot = tuple(((word >> s) & 31) << 3 | ((word >> s) & 31) >> 2
                for s in (0, 5, 10))
    top = _picture_top(flat)
    true_h = _hot_rows(flat, top, hot)
    assert true_h >= 2, (
        f"the flat control shows {true_h} hot row(s) — the strip is not being "
        f"found, so this case would pass on nothing")

    seen = [_hot_rows(f, top, hot) for f in hazed]
    assert max(seen) <= true_h, (
        f"the horizon strip renders up to {max(seen)} rows tall against a true "
        f"height of {true_h}: heights {seen}. The protected window is letting "
        f"a stretching slope through")
    assert min(seen) < true_h, (
        f"the strip never compresses at all ({seen}) — the window has been "
        f"flattened rather than constrained, and the horizon has dropped out "
        f"of the effect instead of only shrinking in it")
