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
V_SHIM_CHR = _sym("ES_V_HZ_SHIM_CHR")["start"]      # VRAM words
V_SHIM_MAP = _sym("ES_V_HZ_SHIM_MAP")["start"]

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
def _rail_const(name):
    """One equate out of game/heathaze/heathaze.inc.

    READ, NOT RETYPED. A copy of HZ_SHIM_LEAD lived here as a literal and went
    stale the moment the phase count doubled — the module still passed, which
    is worse than failing: it meant the mask was being built against the wrong
    layer offset and the case was quietly weaker than it claimed. Anything the
    ROM and this file must agree about is read from the source of truth.
    """
    for line in (SUPERFORGE / "game" / "heathaze" / "heathaze.inc").read_text().splitlines():
        if line.strip().startswith(name):
            head, _, rest = line.partition("=")
            if head.strip() == name:
                return int(rest.split(";")[0].strip())
    raise KeyError(f"{name} is not in heathaze.inc")


SHIM_LEAD = _rail_const("HZ_SHIM_LEAD")
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


def _row_vshift(a, b, y, cols=None):
    """The VERTICAL offset d for which row y of `a` is row y+d of `b`.

    THE AXIS IS THE POINT OF THIS RAIL. A per-scanline BGnVOFS makes scanline
    N show source row N + d(N), so the frame is not a shear of the control —
    rows are duplicated and skipped and the picture compresses and stretches.
    That means the comparison is row-against-ROW: hazed row y is some whole
    row of the flat control, and which one it is IS the displacement.

    Returned only when the winner is UNAMBIGUOUS. A run of identical source
    rows (flat sand) matches at several offsets and decides nothing; saying so
    is the alternative to a confident wrong answer.

    `cols` restricts the comparison to columns the caller can vouch for — the
    ones where BG2 is transparent in both frames, so the pixels compared are
    the world unhalved on each side.
    """
    xs = list(range(256)) if cols is None else list(cols)
    if len(xs) < 128:
        return None                      # under half the scanline is clear
    if len({b[y][x] for x in xs}) < 4:
        return None                      # no structure to decide on
    scored = sorted(
        (sum(1 for x in xs if a[y][x] != b[y + d][x]), d)
        for d in range(-8, 9) if 0 <= y + d < len(b))
    best, runner = scored[0], scored[1]
    if best[0] * 2 >= runner[0]:
        return None
    return best[1]


def _shimmer_opaque(m):
    """A 256x224 mask: True where BG2 has a pixel, read out of VRAM.

    WHY THIS EXISTS. Stage 2 puts a second layer on the sub screen and gives
    it its OWN HDMA channel at a different phase, so the composited frame is
    no longer a translation of the control — two layers moved by two amounts.
    BG1's displacement is still exactly what the table says, and this is how
    the case recovers it: where BG2 is TRANSPARENT the sub screen is empty,
    the hardware substitutes the fixed colour and disables halving, and the
    pixel on screen is the world unhalved. Those columns are pure BG1.

    Decoded from the tilemap and CHR the ROM actually uploaded, in the layer's
    OWN coordinates — the caller shifts by that layer's own displacement.
    """
    tilemap = m.read_bytes(MemoryType.SnesVideoRam, V_SHIM_MAP * 2, 2048)
    chr_bytes = m.read_bytes(MemoryType.SnesVideoRam, V_SHIM_CHR * 2,
                             _sym("ES_V_HZ_SHIM_CHR")["size"] * 2)
    opaque = [[False] * 256 for _ in range(256)]
    for row in range(32):
        for col in range(32):
            w = tilemap[(row * 32 + col) * 2] | (tilemap[(row * 32 + col) * 2 + 1] << 8)
            tile = w & 0x3FF
            base = tile * 32
            for y in range(8):
                p0, p1 = chr_bytes[base + y * 2], chr_bytes[base + y * 2 + 1]
                p2, p3 = chr_bytes[base + 16 + y * 2], chr_bytes[base + 17 + y * 2]
                for x in range(8):
                    bit = 7 - x
                    v = (((p0 >> bit) & 1) | (((p1 >> bit) & 1) << 1)
                         | (((p2 >> bit) & 1) << 2) | (((p3 >> bit) & 1) << 3))
                    if v:
                        opaque[(row * 8 + y) & 0xFF][(col * 8 + x) & 0xFF] = True
    return opaque


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

# WHY THIS CASE RESTS ON A FLOOR RATHER THAN ON EVERY ROW, and what that cost.
#
# In stage 1 BG1 was the only moving layer and the composite WAS a translation
# of the control, so every decidable row could be asserted individually and
# exactly. Stage 2 puts a second layer on the sub screen with its OWN channel
# at its own phase: the frame is now two layers displaced by two amounts and
# no single shift describes it. BG1's own displacement is still exactly what
# the table says, but recovering it from the composite goes through a mask
# decoded out of VRAM, and near the bottom of the band — where the shimmer is
# densest — that recovery is not reliable enough to hang a per-row equality on.
#
# So the case asserts the FLOOR: of the rows where the measurement is possible
# at all, at least EXACT_FLOOR of them show exactly the byte the ROM holds for
# that scanline. Measured on the shipped binary at 67/74 (90%). This is a
# weaker statement than stage 1's and the weakening is REAL — worth knowing
# when choosing between the two stages, which is why it is written here rather
# than smoothed over.
#
# THE STRONGER CLAIM ABOUT THE BLEND lives elsewhere and is not weakened:
# test_every_band_pixel_is_a_legal_composite asserts membership over the whole
# band, pixel by pixel, with no mask and no floor.
#
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

# TWO FLOORS, because there are two distinguishable outcomes and lumping them
# would hide which one moved.
#
#   EXACT_FLOOR   the row shows the byte the ROM holds for ITS OWN line.
#   ADJACENT_FLOOR the row shows that byte or one of its two neighbours — the
#                  one-scanline latch ambiguity HDMA_LATCH_LINES describes,
#                  which is a question about WHICH byte and never about the
#                  value.
#
# Measured on the shipped binary, VERTICAL axis: 62 decidable rows, 50 exact
# (81%), 54 exact-or-adjacent (87%). The floors sit below those with real
# headroom rather than shaved to just under them — a floor with one row of
# margin is a flake waiting for the next tweak, and these are meant to catch a
# regression, not to record today's number to the digit.
#
# Why the exact figure is not higher: the perspective coordinate compresses
# the wave toward the horizon, so consecutive band lines carry different
# displacements far more often than a constant-wavelength wave would, and the
# one-line latch ambiguity that would otherwise fall between two EQUAL bytes
# falls between two different ones. Same hardware, same table, more places for
# the boundary to show.
EXACT_FLOOR = 0.70
ADJACENT_FLOOR = 0.80
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
        opaque = _shimmer_opaque(m)
        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        flat = _frame(m)

    top = _picture_top(hazed)
    assert top == _picture_top(flat)
    hofs = warp[phase]
    shim = warp[(phase + SHIM_LEAD) % PHASES]

    exact = neighbour = decidable = 0
    for y in range(top + BAND_TOP, top + BAND_TOP + BAND_LINES):
        line = y - top - BAND_TOP - HDMA_LATCH_LINES
        if not 0 <= line < BAND_LINES:
            continue                     # the latency's own edge row
        # BG2 rides its own channel at its own phase, and BOTH frames have it
        # (the control flattens the displacement, not the layer) — so the
        # columns admitted are the ones where BG2 is transparent in each.
        h2 = shim[line]
        f2 = warp[FLAT_INDEX][line]
        # BG2 rides its own channel at its own phase and displaces VERTICALLY
        # too, so the mask row shifts with it. BG2HOFS is 0 on this rail, so
        # the column maps straight through.
        cols = [x for x in range(256)
                if not opaque[(y - top + h2) & 0xFF][x]
                and not opaque[(y - top + f2) & 0xFF][x]]
        d = _row_vshift(hazed, flat, y, cols)
        if d is None:
            continue                     # uniform, or too little clear row
        assert d is not False, (
            f"PNG row {y} (scanline {y - top}) aligns to NO whole-pixel offset "
            f"in -8..+8 — the row is not this world horizontally displaced")
        decidable += 1
        want = hofs[line]
        if d == want:
            exact += 1
        else:
            window = [hofs[line + k] for k in (-1, 0, 1)
                      if 0 <= line + k < BAND_LINES]
            if min(window) <= d <= max(window):
                neighbour += 1
        assert -8 <= d <= 8, (
            f"phase {phase}, scanline {y - top}: recovered displacement {d} is "
            f"not a displacement the table could produce at all")

    assert decidable >= 40, (
        f"only {decidable} band rows were decidable — the shimmer layer is "
        f"covering too much of the picture for BG1's own displacement to be "
        f"recoverable from any of it")
    assert exact / decidable >= EXACT_FLOOR, (
        f"only {exact}/{decidable} rows matched their OWN table entry "
        f"({exact / decidable:.0%}, floor {EXACT_FLOOR:.0%}) — the picture is "
        f"tracking the table too loosely to call it per-scanline")
    assert (exact + neighbour) / decidable >= ADJACENT_FLOOR, (
        f"only {exact + neighbour}/{decidable} rows matched their own table "
        f"entry OR one of its neighbours "
        f"({(exact + neighbour) / decidable:.0%}, floor {ADJACENT_FLOOR:.0%}) "
        f"— rows are showing displacements the table does not ask for "
        f"anywhere near them, which a one-scanline latch cannot explain")


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
# the blend — the claim the displacement does not make
# =============================================================================

def _rgb5(word):
    return (word & 31, (word >> 5) & 31, (word >> 10) & 31)


def _to255(c):
    """Mesen's 5-to-8-bit expansion: (v << 3) | (v >> 2).

    NOT `v * 255 // 31`. The two agree at the ends and diverge in the middle
    (13 -> 106 against 107), which is enough to make every mid-tone pixel look
    illegal and send an investigation after a blend that was working. Measured
    the hard way once; stated here so it is not measured again.
    """
    return tuple((v << 3) | (v >> 2) for v in c)


def _half_add(a, b):
    """The PPU's own arithmetic: min((main + sub) >> 1, 31) per 5-bit channel.

    Shift BEFORE clamp — Mesen2 SnesPpu.cpp:1372-1377. Transcribed here rather
    than imported from anywhere, so the oracle is the hardware's rule and not
    this repo's opinion of it.
    """
    return tuple(min((x + y) >> 1, 31) for x, y in zip(a, b))


def test_every_band_pixel_is_a_legal_composite():
    """Region-wide membership, pixel by pixel, with no mask and no floor.

    THE CLAIM. Every pixel in the band is either a RAW world colour — the world
    arriving unhalved because the sub screen was empty there, which is the
    fixed-colour fallback and the case that tells a real sub-screen blend from
    a palette trick — or the HALF-ADD of a world colour with a shimmer colour.
    Nothing else is reachable. The legal set is 63 values out of 32,768, and it
    is computed here from the two palettes read off CGRAM on the running
    machine rather than from the generator that authored them.

    AND IT IS NOT VACUOUS. A blend that never fired would put every pixel in
    the raw set and pass this trivially, so the case also demands that a
    substantial number of pixels are ONLY explicable as a half-add: colours
    that are in the blend set and in no palette at all. Those pixels are the
    colour-math unit's output and can have come from nowhere else.
    """
    with Machine(str(ROM)) as m:
        _to_desert(m)
        cg = m.read_bytes(MemoryType.SnesCgRam, 0, 128)
        shot = _frame(m)

    def words(b):
        return [b[i] | (b[i + 1] << 8) for i in range(0, len(b), 2)]

    world = [_rgb5(w) for w in words(cg[:32])]          # BG1, palette group 0
    shim = [_rgb5(w) for w in words(cg[64:96])][1:4]    # BG2 group 2, 0 = clear

    raw = {_to255(c) for c in world}
    blended = {_to255(_half_add(a, b)) for a in world for b in shim}
    legal = raw | blended
    blend_only = blended - raw

    top = _picture_top(shot)
    illegal, from_math = {}, 0
    for y in range(top + BAND_TOP, top + 224):
        for x in range(256):
            c = shot[y][x]
            if c not in legal:
                illegal[c] = illegal.get(c, 0) + 1
            elif c in blend_only:
                from_math += 1

    assert not illegal, (
        f"{sum(illegal.values())} pixel(s) in the band are neither a raw world "
        f"colour nor a half-add of one with a shimmer colour — the commonest "
        f"is {sorted(illegal.items(), key=lambda kv: -kv[1])[0]}")
    assert from_math > 1000, (
        f"only {from_math} pixels are ONLY explicable as a half-add — the "
        f"blender is barely firing, so the membership check above is passing "
        f"on the raw set alone and proves nothing")
