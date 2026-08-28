"""smelter — per-column vertical scroll out of BG3's tilemap, for no channel.

WHAT IS UNDER TEST, and what is NOT. The claim this rail makes is not "some
columns move": it is that EVERY 8-pixel column of the picture stands exactly
where the word the ROM holds for that column says it should, that a column
whose enable bit is clear stands at its layer's own register instead, and that
the two are independent column by column. That is a per-column EQUALITY, and
this module asserts it as one.

THE ORACLE IS THE ROM, NOT THE GENERATOR. Expected displacements are decoded
from the column blob AS IT SITS IN build/smelter.sfc — located by searching the
ROM image for the bytes, so the case also proves the blob reached the binary —
and never from tools/gen_smelter_assets.py. Importing the generator would
compare the ROM against the Python that authored it, which agrees with itself
by construction; this compares the PICTURE against the BYTES THE PPU READ.

THE OBSERVATION IS THE RENDERED FRAME, and every colour in it is resolved
against CGRAM AS THE ROM LEFT IT rather than against RGB constants typed here.
Nothing reads ES_SMT_PHASE to decide whether the picture is right — the phase
is read only to know WHICH row of the oracle to join against, which is the
map-as-subject/oracle distinction test_lakeside.py draws.

THE CONTROL IS A ROW, NOT A DISARM. B selects the blob's 65th row: the same 32
words with every value at its base and every enable bit still set. The same
transfer fires the same 64 B into the same place, so exactly one variable moves
between the two states and a difference between them is attributable to the
table alone.

STATE CYCLES, NOT SNAPSHOTS. The columns run, are flattened, run again and
return to the title — and the resume case is there because a toggle that
RESTARTED the animation would still look right in any single frame.

AND THE REFUSALS ARE PART OF THE RAIL. Two of them are asserted here against
THIS TREE'S OWN FEATURES, not against fixtures: `bg_text` composed into the
mode-2 scene, and the offset table composed into the mode-1 one. They are why
`bg_text` is scene-scoped in game/smelter/game.toml, and a test that only read
the picture would leave the reason for that unstated.

LOCKSTEP-NATIVE: `Machine` only, absolute frames, no wall-clock surface.
"""
import dataclasses
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
ROM = BUILD / "smelter.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "smt" / "symbol_map.json").read_text())

sys.path.insert(0, str(SUPERFORGE / "vendor"))                  # noqa: E402
from machine import Machine, MemoryType                          # noqa: E402

sys.path.insert(0, str(SUPERFORGE / "allocator"))                # noqa: E402
from allocate import AllocationError, allocate                   # noqa: E402
from schemas import (StateDecl, load_feature, load_manifest,     # noqa: E402
                     load_state, load_substrate)

W = MemoryType.SnesWorkRam
V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam

# The active picture starts at PNG row PICTURE_TOP: Mesen hands back a 256x239
# image and the 224 visible lines begin there. A fact about the MACHINE, not
# about this rail — tests/frame_geometry.py is where it is established, and
# `test_the_frame_geometry_is_the_one_this_module_assumes` re-solves it from
# THIS rail's picture rather than trusting the import (that module's own rule:
# sharing a constant makes it consistent, not true).
from frame_geometry import PICTURE_LINES, PICTURE_TOP            # noqa: E402


# --- the allocator's answers, asked for rather than hardcoded ---------------
def _sym(name, scene="works"):
    pools = [MAP["scenes"][scene]["placements"], MAP["globals"]]
    for pool in pools:
        for p in pool:
            if p["sym"] == name:
                return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


def _art(key):
    """One equate out of the GENERATED build/assets/smt_art.inc.

    READ, NOT RETYPED. A copy of a rail constant living here as a literal goes
    stale the moment the geometry changes, and the module keeps passing — which
    is worse than failing, because the case is then quietly weaker than it
    claims.
    """
    for line in (ASSETS / "smt_art.inc").read_text().splitlines():
        head, _, rest = line.partition("=")
        if head.strip() == key:
            return int(rest.split(";")[0].strip())
    raise KeyError(f"{key} is not in smt_art.inc")


COLS = _art("SMT_COLS")
PHASES = _art("SMT_PHASES")
FLAT_ROW = _art("SMT_FLAT_INDEX")
ROW_BYTES = _art("SMT_ROW_BYTES")
CRUST_PX = _art("SMT_CRUST_TOP_PX")
PLAT_PX = _art("SMT_PLAT_TOP_PX")
PLAT_BASE = _art("SMT_PLAT_BASE")
MELT_BASE = _art("SMT_MELT_BASE")
PLATES = [(_art(f"SMT_PLAT_{i}_COL"), 4) for i in range(_art("SMT_PLAT_COUNT"))]

DP_PHASE = _sym("ES_SMT_PHASE")["start"]
DP_FLAT = _sym("ES_SMT_FLATSEL")["start"]
VRAM_TABLE = _sym("ES_V_SMT_TAB")["start"]          # in WORDS
CG_PLATE = _sym("ES_C_SMT_PPAL")["start"]
CG_MELT = _sym("ES_C_SMT_MPAL")["start"]

# The composed video mode and the offset table's declared shape, machine-read
# out of the map rather than retyped — the screen_blend precedent.
VO = MAP["scenes"]["works"]["video_offset"]
VO_TITLE = MAP["scenes"]["title"]["video_offset"]
BIT_BG1 = VO["fields"]["BG1"]
BIT_BG2 = VO["fields"]["BG2"]
VALUE_MASK = VO["fields"]["MASK"]

JOY_START = {"start": True}
JOY_B = {"b": True}
TITLE = 40                  # frames on the title before Start
SETTLE = 90                 # ...and after it: the fade, then a settled run


# --- the oracle: the column blob AS IT SITS IN THE ROM ----------------------
def _blob():
    """The 65 rows, out of build/smelter.sfc.

    Located by SEARCHING the ROM image for the generated bytes, which is what
    makes finding it a proof that the blob reached the binary — a claim the
    linker placement `.assert`s make separately and from the other side.
    """
    want = (ASSETS / "smt_col.bin").read_bytes()
    rom = ROM.read_bytes()
    at = rom.find(want)
    assert at >= 0, "the column blob is not in build/smelter.sfc"
    assert rom.find(want, at + 1) < 0, "the column blob appears twice"
    return rom[at:at + len(want)]


BLOB = _blob()


def row(idx):
    """One 32-word offset row, indexed by SCREEN column.

    THE ONE-COLUMN LEAD IS UNDONE HERE, once. The PPU fetches a column's
    tilemap data before it fetches that column's offset words, so the word
    written at table index k displaces screen column k + 1 — measured on this
    binary (test_the_offset_leads_its_column_by_one). Screen column 0 has no
    word at all: the latches are cleared at the start of each scanline's fetch.
    Everything below this line is in screen columns.
    """
    b = BLOB[idx * ROW_BYTES:(idx + 1) * ROW_BYTES]
    words = [b[2 * c] | (b[2 * c + 1] << 8) for c in range(COLS)]
    return [None] + words[:COLS - 1]


def plate_of(col):
    for i, (first, width) in enumerate(PLATES):
        if first <= col < first + width:
            return i
    return None


# --- the picture, read against CGRAM as the ROM left it ---------------------
def _palette(m):
    """CGRAM words 0..47 as RGB triples, read off the running machine.

    The colours a test matches on are the colours the ROM UPLOADED, so a
    palette change moves the test with the art instead of breaking it — and a
    palette that never got uploaded fails here rather than silently matching
    nothing.
    """
    raw = m.read_bytes(C, 0, 48 * 2)
    out = []
    for i in range(48):
        v = raw[2 * i] | (raw[2 * i + 1] << 8)
        r, g, b = v & 0x1F, (v >> 5) & 0x1F, (v >> 10) & 0x1F
        out.append((r * 255 // 31, g * 255 // 31, b * 255 // 31))
    return out


def _classify(px, pal):
    best, bi = None, None
    for i, c in enumerate(pal):
        d = sum((a - b) ** 2 for a, b in zip(px, c))
        if best is None or d < best:
            best, bi = d, i
    return bi


def _edge_y(im, pal, col, want_index):
    """The first picture row in this column whose pixel is CGRAM `want_index`.

    In SCREEN rows: the PNG's PICTURE_TOP offset is removed here, so every number
    a case compares is a scanline of the visible picture.
    """
    for y in range(PICTURE_TOP, im.size[1]):
        if _classify(im.getpixel((8 * col + 3, y))[:3], pal) == want_index:
            return y - PICTURE_TOP
    return None


# The two edges every measurement lands on. Both are a single unbroken bright
# line across their tile's top row, which is why they were drawn that way.
CRUST_IX = CG_MELT + 3          # the melt's white-hot surface
PLATE_IX = CG_PLATE + 4         # a steel plate's top edge


def crust_y(im, pal, col):
    return _edge_y(im, pal, col, CRUST_IX)


def plate_y(im, pal, col):
    return _edge_y(im, pal, col, PLATE_IX)


# THE SCROLL LATCH'S OFF-BY-ONE. The vertical latch reads "scanline N shows
# tilemap line VOFS + N" and the first ACTIVE scanline is 1, so map pixel row P
# lands on picture row P - VOFS - 1. An offset word REPLACES a column's VOFS
# rather than adding to it, so the same relation holds with the word's value in
# place of the register. game/smelter/smelter.inc states it; this is the same
# statement in Python, and test_the_row_bias_is_what_the_rail_says checks the
# two against the picture rather than against each other.
ROW_BIAS = 1


def where(map_px, word_value):
    return map_px - word_value - ROW_BIAS


@pytest.fixture(scope="module")
def frame(tmp_path_factory):
    """One settled frame of the works scene: the picture, the palette, and
    the phase the row it was drawn from was chosen by."""
    out = tmp_path_factory.mktemp("smt")
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        phase = m.read_u16(W, DP_PHASE)
        p = out / "works.png"
        m.screenshot(str(p))
    return Image.open(p).convert("RGB"), pal, phase


def _fit(im, pal, phase):
    """Which row of the blob the picture was drawn from, by exact match.

    The NMI commits a row and the main thread advances the phase afterwards,
    so the row on screen is one behind the phase a test can read. Rather than
    assume the lag, this scores every row and every case then asserts the
    winner is EXACT — a fit that had to tolerate error would not be an
    equality.
    """
    scored = []
    for lag in range(3):
        idx = (phase - lag) % PHASES
        r = row(idx)
        bad = 0
        for c in range(1, COLS):
            w = r[c]
            if w is None or not (w & BIT_BG2):
                continue
            y = crust_y(im, pal, c)
            if y is None or y != where(CRUST_PX, w & VALUE_MASK):
                bad += 1
        scored.append((bad, lag, idx))
    scored.sort()
    return scored


# ==========================================================================
# the mechanism, measured
# ==========================================================================

def test_the_offset_leads_its_column_by_one(frame):
    """MEASURED, NOT ASSUMED. In mode 2 the PPU runs GetTilemapData for BG2
    and BG1 BEFORE GetHorizontalOffsetByte/GetVerticalOffsetByte inside a
    column's eight-cycle group, so the words fetched with column index g are
    latched in time for column g+1. This asserts the shift is exactly one and
    that no other shift explains the picture at all — the maximum is sharp,
    which is what makes it a measurement rather than a fitted tolerance.
    """
    im, pal, phase = frame
    scored = _fit(im, pal, phase)
    _, lag, idx = scored[0]
    base = row(idx)
    for shift in (-1, 0, 1):
        bad = 0
        for c in range(1, COLS - 1):
            w = base[c + shift] if 0 <= c + shift < COLS else None
            if w is None or not (w & BIT_BG2):
                continue
            y = crust_y(im, pal, c)
            if y is None or y != where(CRUST_PX, w & VALUE_MASK):
                bad += 1
        if shift == 0:
            assert bad == 0, "the aligned row does not explain the picture"
        else:
            assert bad > 0, (
                f"a shift of {shift:+d} explains the picture too — the "
                f"one-column lead is not being measured, it is being assumed")


def test_every_melt_column_stands_where_its_word_says(frame):
    """THE HEADLINE EQUALITY. Not "the melt moves": every gap column's crust
    line is at exactly `map row - word - 1`, against the word the ROM holds
    for that column in the row the picture was drawn from."""
    im, pal, phase = frame
    bad, lag, idx = _fit(im, pal, phase)[0]
    assert bad == 0, f"row {idx} (lag {lag}) leaves {bad} column(s) unexplained"
    r = row(idx)
    checked = 0
    for c in range(1, COLS):
        w = r[c]
        if w is None or not (w & BIT_BG2):
            continue
        assert crust_y(im, pal, c) == where(CRUST_PX, w & VALUE_MASK), \
            f"column {c}: crust is not where word ${w:04X} puts it"
        checked += 1
    assert checked >= 12, f"only {checked} melt columns were decidable"


def test_every_plate_column_stands_where_its_word_says(frame):
    """...and the same equality on the OTHER layer, driven by the OTHER
    enable bit out of the same 32 words. Two layers, one table, one value a
    column — the composition's whole shape, asserted on the picture."""
    im, pal, phase = frame
    _, _, idx = _fit(im, pal, phase)[0]
    r = row(idx)
    checked = 0
    for c in range(1, COLS):
        w = r[c]
        if w is None or not (w & BIT_BG1):
            continue
        assert plate_y(im, pal, c) == where(PLAT_PX, w & VALUE_MASK), \
            f"column {c}: the plate is not where word ${w:04X} puts it"
        checked += 1
    assert checked == sum(width for _, width in PLATES), \
        f"{checked} plate columns decidable, {sum(w for _, w in PLATES)} drawn"


def test_the_frame_geometry_is_the_one_this_module_assumes(frame):
    """PICTURE_TOP is imported, and re-solved here anyway.

    frame_geometry.py's own rule: sharing a constant makes it consistent, it
    does not make it true. So this predicts every decidable melt column at
    seven candidate PNG offsets and requires EXACTLY ONE to mismatch zero
    columns — which is the same shape the split-demo predictors use, on a
    picture whose per-column heights vary and therefore constrain the fit far
    more tightly than a uniform one would.
    """
    im, pal, phase = frame
    _, _, idx = _fit(im, pal, phase)[0]
    r = row(idx)
    misses = []
    for cand in range(PICTURE_TOP - 3, PICTURE_TOP + 4):
        bad = 0
        for c in range(1, COLS):
            w = r[c]
            if w is None or not (w & BIT_BG2):
                continue
            y = None
            for py in range(cand, im.size[1]):
                if _classify(im.getpixel((8 * c + 3, py))[:3], pal) == CRUST_IX:
                    y = py - cand
                    break
            if y != where(CRUST_PX, w & VALUE_MASK):
                bad += 1
        misses.append((cand, bad))
    zero = [cand for cand, bad in misses if bad == 0]
    assert zero == [PICTURE_TOP], misses
    assert im.size == (256, PICTURE_TOP + PICTURE_LINES + 8), im.size


def test_screen_column_zero_cannot_be_displaced(frame):
    """The other half of the fetch rule, and it is a REGISTER fact: the
    offset latches are cleared at the start of each scanline's fetch, so the
    leftmost column always shows its layer's own BGnVOFS. Here that is the
    melt's base — the value the works scene writes to BG2VOFS as the fallback
    a column with its bit clear falls back to."""
    im, pal, _ = frame
    assert crust_y(im, pal, 0) == where(CRUST_PX, MELT_BASE)


def test_the_row_bias_is_what_the_rail_says(frame):
    """The off-by-one in game/smelter/smelter.inc, checked against the
    PICTURE rather than against itself: with the bias removed, no column
    would land."""
    im, pal, phase = frame
    _, _, idx = _fit(im, pal, phase)[0]
    r = row(idx)
    for bias in (0, 2):
        wrong = sum(1 for c in range(1, COLS)
                    if r[c] and (r[c] & BIT_BG2)
                    and crust_y(im, pal, c) == PLAT_PX - (r[c] & VALUE_MASK) - bias)
        assert wrong == 0


# ==========================================================================
# independence — the property the rail exists to show
# ==========================================================================

def test_adjacent_columns_hold_different_heights(frame):
    """A jet's arch is 0 at its run's edges and 1 in the middle, and one gap
    is three columns wide — so exactly one column lifts while both its
    neighbours hold still. This is the granularity claim: not a band, not a
    layer, one column."""
    im, pal, _ = frame
    heights = {c: crust_y(im, pal, c) for c in range(COLS)
               if plate_of(c) is None and crust_y(im, pal, c) is not None}
    pairs = [(a, b) for a in heights for b in heights
             if b == a + 1 and heights[a] != heights[b]]
    assert pairs, "no two adjacent melt columns differ — nothing is per-column"
    assert max(abs(heights[a] - heights[b]) for a, b in pairs) >= 8, \
        "adjacent columns differ, but by less than a tile — that is a wobble"


def test_the_plates_are_at_different_heights(frame):
    """Four plates on four harmonics: a viewer can watch one move while its
    neighbour does not. Asserted on the PICTURE — if the four ever shared a
    value the rail would look like one long shelf."""
    im, pal, _ = frame
    tops = []
    for first, width in PLATES:
        ys = {plate_y(im, pal, first + i) for i in range(width)}
        assert len(ys) == 1, f"plate at column {first} is not level: {ys}"
        tops.append(ys.pop())
    assert len(set(tops)) >= 3, f"the plates share heights: {tops}"


def test_a_plate_is_rigid_across_its_own_columns(frame):
    """...and the converse, which is what makes it a PLATFORM rather than a
    ribbon: a plate's four columns carry ONE value, so its surface is flat
    even while the column beside it is 40 pixels away."""
    im, pal, phase = frame
    _, _, idx = _fit(im, pal, phase)[0]
    r = row(idx)
    for first, width in PLATES:
        vals = {r[first + i] & VALUE_MASK for i in range(width)}
        assert len(vals) == 1, f"plate at {first} carries {vals}"


# ==========================================================================
# the control, and the state cycle
# ==========================================================================

def _drive(tmp_path, script):
    """Run the works scene through a script of (frames, pad) and capture."""
    shots = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        for i, (frames, pad) in enumerate(script):
            m.advance(1, pad1=pad) if pad else None
            m.advance(frames)
            p = tmp_path / f"s{i}.png"
            m.screenshot(str(p))
            shots.append((Image.open(p).convert("RGB"),
                          m.read_u16(W, DP_PHASE), m.read_u16(W, DP_FLAT)))
    return pal, shots


def test_the_flat_control_levels_every_column(tmp_path):
    """THE CONTROL. B selects the blob's 65th row — the same 32 words with
    every value at its base and every enable bit still set — so the transfer
    and the mechanism are identical in both states and only the values move.
    Every plate lands on one line and the crust goes straight across."""
    pal, shots = _drive(tmp_path, [(20, JOY_B)])
    im, _, flat = shots[0]
    assert flat == 1
    tops = {plate_y(im, pal, c) for c in range(COLS) if plate_of(c) is not None}
    assert tops == {where(PLAT_PX, PLAT_BASE)}, tops
    crust = {crust_y(im, pal, c) for c in range(COLS)}
    assert crust == {where(CRUST_PX, MELT_BASE)}, crust


def test_flattening_resumes_rather_than_restarts(tmp_path):
    """The state cycle, and the reason the toggle is a control: the phase
    advances while the picture is flat, so un-flattening picks the animation
    up where it went — a toggle that RESTARTED it would look right in any
    single frame and wrong across the pair."""
    pal, shots = _drive(tmp_path, [(30, JOY_B), (30, None), (30, JOY_B)])
    (_, p_flat, f0), (_, p_held, f1), (_, p_back, f2) = shots
    assert (f0, f1, f2) == (1, 1, 0)
    assert p_held != p_flat, "the phase stopped while the picture was flat"
    assert p_back != p_held


def test_the_running_picture_is_not_the_flat_one(tmp_path):
    """Non-vacuity: a rail whose transfer never fired would pass every
    equality above with a flat picture, because the flat row is what enter
    put in VRAM. This is the case that would go red for that."""
    pal, shots = _drive(tmp_path, [(1, None), (20, JOY_B)])
    (run, _, _), (flat, _, _) = shots
    assert run.tobytes() != flat.tobytes()
    moving = [c for c in range(COLS)
              if crust_y(run, pal, c) != crust_y(flat, pal, c)]
    assert len(moving) >= 6, f"only {len(moving)} column(s) ever move"


def test_the_title_is_the_flat_picture_in_another_mode(tmp_path):
    """`title` is mode 1 and `works` is mode 2, and BG1 and BG2 are 4bpp in
    both — so the same art at the same bases draws the same picture. The two
    scenes' plate and crust lines agree because the title writes the same two
    values into BG1VOFS/BG2VOFS that the flat control row carries."""
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        pal = _palette(m)
        p = tmp_path / "title.png"
        m.screenshot(str(p))
    im = Image.open(p).convert("RGB")
    tops = {plate_y(im, pal, c) for c in range(COLS) if plate_of(c) is not None}
    assert tops == {where(PLAT_PX, PLAT_BASE)}
    assert crust_y(im, pal, 0) == where(CRUST_PX, MELT_BASE)


# ==========================================================================
# BG3 is not a layer here — the declaration, and the picture
# ==========================================================================

def test_the_composed_modes_are_the_two_the_rail_declares():
    """Read out of symbol_map.json, not retyped: the title composes mode 1
    with the BG3-priority bit and the works composes mode 2 with the offset
    table."""
    assert (VO_TITLE["bgmode"], VO_TITLE["mode"]) == (0x09, 1)
    assert VO_TITLE.get("offset_axis") is None
    assert (VO["bgmode"], VO["mode"]) == (0x02, 2)
    assert VO["offset_axis"] == "v"
    assert sorted(VO["offset_layers"]) == ["bg1", "bg2"]
    assert VO["registers"] == ["BGMODE", "BG3SC", "BG3HOFS", "BG3VOFS"]


def test_bg3_is_not_on_the_main_screen_in_the_works():
    """The composed TM has no bg3 bit — it cannot, because a bg3 designation
    beside an offset table is refused. The title's does."""
    assert MAP["scenes"]["works"]["screen_blend"]["tm"] & 0x04 == 0
    assert MAP["scenes"]["title"]["screen_blend"]["tm"] & 0x04 == 0x04


def test_the_table_reaches_vram_and_is_the_row_the_picture_shows(tmp_path):
    """THE DESTINATION REGION, read byte for byte. The equalities above
    prove the PICTURE matches the ROM; this proves the bytes got there — the
    upload path's own test, which a downstream assertion can pass through
    while the transfer silently no-ops on a stale VRAM page.
    """
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        phase = m.read_u16(W, DP_PHASE)
        # BG3 map row 0 is the H row and row 1 the V row: BG3VOFS is 0, and
        # the vertical row is the horizontal one plus 0x20 WORDS.
        h = m.read_bytes(V, VRAM_TABLE * 2, ROW_BYTES)
        v = m.read_bytes(V, (VRAM_TABLE + COLS) * 2, ROW_BYTES)
    assert h == bytes(ROW_BYTES), "the H row is not all zero — a V-only " \
        "table is expressed by a row with neither enable bit set"
    want = {(phase - lag) % PHASES: None for lag in range(3)}
    assert any(v == BLOB[i * ROW_BYTES:(i + 1) * ROW_BYTES] for i in want), \
        "BG3's V row is not any row the blob holds near this phase"


def test_no_column_is_displaced_on_the_title(tmp_path):
    """Mode 1 does not fetch offset words at all. The table is still resident
    in ROM and BG3 still has a tilemap — the picture is flat because the
    MODE decides whether the mechanism runs, which is the constraint the
    allocator refuses on."""
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        pal = _palette(m)
        p = tmp_path / "t.png"
        m.screenshot(str(p))
    im = Image.open(p).convert("RGB")
    assert len({crust_y(im, pal, c) for c in range(COLS)}) == 1


def test_the_title_returns_with_bg3_a_layer_again(tmp_path):
    """THE HYGIENE CLAIM, as a pixel equality.

    `works` leaves BG3SC pointing at a page of 32 scroll words. A successor
    that drew text without re-pointing it would render those words AS GLYPHS
    — 64 bytes of vertical scroll positions, displayed as tile ids, in the
    font. The discharge is `bg_text`'s: all four of its BG3 registers are in
    `scene_writes` and the title's enter writes all four.

    Asserted as PIXEL-IDENTICAL to the title before the works ever ran, which
    is the only form of the claim that cannot pass on a picture that is merely
    plausible. This is `blend_off`'s and `hz_flat`'s rule applied to a whole
    layer's identity rather than to a port's value.
    """
    def title_frame(name, run_the_works):
        with Machine(str(ROM)) as m:
            m.advance(TITLE)
            if run_the_works:
                m.advance(1, pad1=JOY_START)
                m.advance(SETTLE)
                m.advance(1, pad1=JOY_START)
                m.advance(SETTLE)
            p = tmp_path / name
            m.screenshot(str(p))
        return Image.open(p).convert("RGB").tobytes()

    assert title_frame("first.png", False) == title_frame("back.png", True)


# ==========================================================================
# the refusals — against THIS TREE'S features, quoted verbatim
# ==========================================================================

FEATURES = SUPERFORGE / "engine" / "features"
SUB = load_substrate(SUPERFORGE / "allocator" / "substrate.toml")


def _tree_features():
    return {d.name: load_feature(d / "feature.toml", SUB)
            for d in sorted(FEATURES.iterdir())
            if (d / "feature.toml").is_file()}


def _scene(tmp_path, *names):
    p = tmp_path / "game.toml"
    p.write_text('[[scene]]\nid = "works"\nfeatures = ['
                 + ", ".join(f'"{n}"' for n in names) + ']\n')
    return load_manifest(p)


def test_bg_text_cannot_compose_beside_the_offset_table(tmp_path):
    """THE REFUSAL THE RAIL'S SHAPE IS BUILT AROUND, on the real features.

    This is why `bg_text` is listed in the title scene and not in
    game/smelter/game.toml's `globals`. Before [[claims.offset]] both
    features claimed "their" BG3 and the build was green; the collision that
    did exist read as an ordinary double-owner, naming neither the hazard nor
    the choice. The message is quoted rather than pattern-matched loosely,
    because the message IS the deliverable.
    """
    feats = _tree_features()
    with pytest.raises(AllocationError) as e:
        allocate(SUB, feats, StateDecl((), {}),
                 _scene(tmp_path, "smt_bg", "smt_opt", "bg_text"))
    msg = str(e.value)
    assert "REGISTER ownership contention in scene 'works'" in msg
    assert "text_bg3 (engine:bg_text)" in msg
    assert "video/offset <- engine:smt_opt" in msg
    assert ("BG3 IS THIS SCENE'S OFFSET TABLE, not a drawable layer" in msg)
    assert ("In modes [2, 4, 6] the PPU reads BG3's map entries as per-column "
            "scroll offsets and never renders the layer") in msg
    assert ("a feature that draws on BG3 and an offset-per-tile feature "
            "cannot both hold this scene") in msg
    assert "put the offset table in a scene of its own (docs/100)" in msg


def test_the_two_scenes_modes_cannot_share_one_scene(tmp_path):
    """The rail's two declared modes, put in one scene. A scene has ONE video
    mode, and the ownership of BGMODE rather than its value is the resource —
    so this refuses whichever way round the two are written."""
    feats = _tree_features()
    with pytest.raises(AllocationError) as e:
        allocate(SUB, feats, StateDecl((), {}),
                 _scene(tmp_path, "smt_bg", "smt_opt", "smt_flat"))
    msg = str(e.value)
    assert "VIDEO MODE contention in scene 'works'" in msg
    assert "smt_mode (engine:smt_opt)" in msg
    assert "smt_title_mode (engine:smt_flat)" in msg
    assert "BGMODE bits 0-2 hold it for the whole frame" in msg


def test_the_offset_table_cannot_compose_under_the_title_s_mode(tmp_path):
    """THE OTHER GAP THE CAPABILITY MAP NAMED, on the SHIPPED offset claim:
    offset-per-tile under a mode that does not fetch offset words.

    `smt_opt` carries its own mode claim, so composing it beside `smt_flat`
    hits the one-mode rule first (above). What is under test here is the
    OTHER rule, so the shipped declaration is taken and its video half
    removed — the `[[claims.offset]]` object is `smt_opt`'s own, unedited, and
    the mode it meets is the title's own mode 1. Writing a fixture feature
    instead would test a toml this file wrote.
    """
    feats = _tree_features()
    feats["smt_opt"] = dataclasses.replace(feats["smt_opt"], video=())
    with pytest.raises(AllocationError) as e:
        allocate(SUB, feats, StateDecl((), {}),
                 _scene(tmp_path, "smt_bg", "smt_opt", "smt_flat"))
    msg = str(e.value)
    assert "OFFSET-PER-TILE contention in scene 'works'" in msg
    assert "smt_table (engine:smt_opt)" in msg
    assert "smt_title_mode (engine:smt_flat)" in msg
    assert "declares mode 1" in msg
    assert "Offset-per-tile exists in modes [2, 4, 6] ONLY" in msg
    assert "FetchTileData branches on the video mode" in msg
    assert "never reads a word of this table" in msg


def test_the_shipped_composition_is_the_one_that_allocates(tmp_path):
    """Non-vacuity for the pair above: the rail's own game.toml composes, so
    the two refusals are catching the compositions they name and not some
    unrelated infeasibility in these features."""
    feats = _tree_features()
    game = SUPERFORGE / "game" / "smelter"
    a = allocate(SUB, feats, load_state(game / "state.toml"),
                 load_manifest(game / "game.toml"))
    assert set(a.scenes) == {"title", "works"}
    assert a.scenes["works"].video_offset["mode"] == 2
    assert a.scenes["title"].video_offset["mode"] == 1
