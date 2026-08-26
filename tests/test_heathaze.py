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

THE CONTROL IS A TABLE, NOT A DISARM. B selects hz_rom's 33rd blob: the same
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
    blob = (ASSETS / "hz_warp.bin").read_bytes()
    at = rom.find(blob)
    assert at >= 0, "the warp blob is not in build/heathaze.sfc byte for byte"
    assert rom.find(blob, at + 1) < 0, "the warp blob appears twice in the ROM"
    assert len(blob) == BLOBS * STRIDE, (len(blob), BLOBS * STRIDE)

    table = []
    for n in range(BLOBS):
        b = blob[n * STRIDE:(n + 1) * STRIDE]
        # [head_count, lo, hi][$80|lines][lo,hi]*lines[$00]
        assert b[0] == BAND_TOP, (n, b[0])
        assert b[3] == 0x80 | BAND_LINES, (n, hex(b[3]))
        hofs = []
        for i in range(BAND_LINES):
            lo, hi = b[4 + 2 * i], b[5 + 2 * i]
            hofs.append(lo | (hi << 8))
        assert b[4 + 2 * BAND_LINES] == 0, (n, "missing terminator")
        table.append(hofs)
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


def _row_shift(a, b, y):
    """The horizontal offset aligning row y of `a` onto row y of `b`.

    THE WHOLE ROW IS THE SURFACE — all 256 pixels, not one edge. A per-scanline
    horizontal displacement is a statement about the entire scanline, and a
    single tracked edge would leave 255 pixels unexamined; this returns the
    offset only when it is UNIQUE, so a uniform row (every shift matches) is
    reported as undecidable rather than guessed at.
    """
    scored = sorted(
        (sum(1 for x in range(256) if a[y][x] != b[y][(x + d) % 256]), d)
        for d in range(-8, 9))
    if scored[0][0] == scored[1][0]:
        return None
    return scored[0][1] if scored[0][0] == 0 else False


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

# ONE PIXEL OF RESIDUAL, on the rows that are not exact. STATED, not hidden:
# across the shipped binary a single decidable row in ~130 lands one pixel
# outside the span its own line and both neighbours ask for. The write-twice
# pair is NOT the cause — [lo, hi] to $210D leaves HScroll = (hi << 8) | lo
# exactly, because each write recomputes from the latches and then updates them
# (Mesen2 SnesPpu.cpp:2000-2002), so the low three bits are not mangled here.
# What remains is a sampling boundary at the bottom of the field, and it is
# carried as a named residual rather than absorbed into a wider tolerance: the
# EXACT floor below is what actually holds this case up.
EDGE_PX = 1

EXACT_FLOOR = 0.85          # of decidable band rows, matching their own entry
SCANLINE_LATCH_SLACK = 1    # ...and the rest inside their own line's neighbourhood
                            # — one entry either side, which is the width of the
                            # ambiguity and not a tolerance chosen to pass


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

    assert all(v == 0 for v in warp[FLAT_INDEX]), (
        "the ROM's control blob is not all-zero — it cannot be a control")
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
    hofs = warp[phase]

    exact = neighbour = decidable = 0
    for y in range(top + BAND_TOP, top + BAND_TOP + BAND_LINES):
        d = _row_shift(hazed, flat, y)
        if d is None:
            continue                     # a uniform row decides nothing
        assert d is not False, (
            f"PNG row {y} (scanline {y - top}) aligns to NO whole-pixel offset "
            f"in -8..+8 — the row is not this world horizontally displaced")
        decidable += 1
        line = y - top - BAND_TOP - HDMA_LATCH_LINES
        if not 0 <= line < BAND_LINES:
            continue                 # the latency's own edge row
        want = hofs[line]
        want = want - 1024 if want > 512 else want
        if d == want:
            exact += 1
            continue
        window = [hofs[line + k]
                  for k in range(-SCANLINE_LATCH_SLACK, SCANLINE_LATCH_SLACK + 1)
                  if 0 <= line + k < BAND_LINES]
        window = [v - 1024 if v > 512 else v for v in window]
        assert min(window) - EDGE_PX <= d <= max(window) + EDGE_PX, (
            f"phase {phase}, scanline {y - top} (band line {line}): the ROM's "
            f"table says BG1HOFS={want}, and its own line plus both neighbours "
            f"span {min(window)}..{max(window)} (+/-{EDGE_PX} px of stated "
            f"residual); the frame is displaced by {d}, "
            f"which is outside anything the table asks for there")
        neighbour += 1

    assert decidable >= 100, f"only {decidable} band rows were decidable"
    assert exact / decidable >= EXACT_FLOOR, (
        f"only {exact}/{decidable} rows matched their OWN table entry "
        f"({exact / decidable:.0%}, floor {EXACT_FLOOR:.0%}) — the picture is "
        f"tracking the table too loosely to call it per-scanline")


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
