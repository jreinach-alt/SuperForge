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
PLAT_WIDTH = _art("SMT_PLAT_WIDTH")
WORLD_COLS = _art("SMT_WORLD_COLS")     # the words in one row of the table
CAM_COL_MAX = _art("SMT_CAM_COL_MAX")
SCREENS = _art("SMT_SCREENS")
# The world's sixteen plate SLOTS, in WORLD columns. BG1's map repeats every
# 32, so the four drawn groups are plate art in every screen and the level's
# design is which word each of these carries.
PLATES = [(_art(f"SMT_PLAT_{i}_COL"), PLAT_WIDTH)
          for i in range(_art("SMT_PLAT_COUNT"))]

DP_PHASE = _sym("ES_SMT_PHASE")["start"]
DP_FLAT = _sym("ES_SMT_FLATSEL")["start"]
DP_CAM = _sym("ES_SMT_CAM")["start"]
# THE CAMERA THE FRAME WAS DRAWN FROM, published by the NMI at the moment it
# uses it. `ES_SMT_CAM` is one frame ahead — the main thread moves it after the
# transfer fires — and at the world's left edge the clamp hides the difference,
# so a module that read the live word would have been right at the spawn and
# wrong everywhere else. Measured exactly that way before this existed: an
# alignment that explained every column at cam=0 explained none at cam=8.
DP_CAM_SHOWN = _sym("ES_SMT_CAM_SHOWN")["start"]
VRAM_TABLE = _sym("ES_V_SMT_TAB")["start"]          # in WORDS
CG_PLATE = _sym("ES_C_SMT_PPAL")["start"]
CG_MELT = _sym("ES_C_SMT_MPAL")["start"]
CG_OBJ = _sym("ES_C_SMT_OBJ_PAL")["start"]

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
    """One world row of the table, indexed by WORLD column.

    NO SHIFT IS APPLIED HERE ANY MORE, and that is a change worth reading. The
    PPU fetches a column's tilemap data before its offset words, so the word at
    BG3 map column j displaces SCREEN column j + 1 — but the table is now
    WORLD-space and the transfer applies the lead at its READ HEAD, starting
    from world column cam + 1. The two shifts cancel: screen column sc shows
    world column cam + sc and is displaced by THAT column's word, with no
    special case anywhere, including at sc = 0.

    Which is the second change. Screen column 0 used to have no word at all —
    the offset latches are cleared at the start of each scanline's fetch, so it
    fell back to its layer's BGnVOFS. Under scrolling that would be a
    permanently wrong column travelling along the left edge, so the NMI now
    loads those fallback registers with that column's own word out of the same
    row it just transferred. The hardware limit is unchanged; what changed is
    that the port it falls back to carries the right answer.
    """
    b = BLOB[idx * ROW_BYTES:(idx + 1) * ROW_BYTES]
    return [b[2 * c] | (b[2 * c + 1] << 8) for c in range(WORLD_COLS)]


def visible(r, cam):
    """The 32 words that explain this frame's screen columns, at this camera."""
    c0 = cam >> 3
    return [r[c0 + sc] for sc in range(COLS)]


def plate_of(wcol):
    """Which WORLD plate slot owns this world column, or None."""
    for i, (first, width) in enumerate(PLATES):
        if first <= wcol < first + width:
            return i
    return None


def screen_plate_of(sc, cam):
    return plate_of((cam >> 3) + sc)


# --- the picture, read against CGRAM as the ROM left it ---------------------
def _cg(raw, i):
    v = raw[2 * i] | (raw[2 * i + 1] << 8)
    r, g, b = v & 0x1F, (v >> 5) & 0x1F, (v >> 10) & 0x1F
    return (r * 255 // 31, g * 255 // 31, b * 255 // 31)


def _palette(m):
    """The BG palettes AND the knight's, as RGB triples, off the machine.

    The colours a test matches on are the colours the ROM UPLOADED, so a
    palette change moves the test with the art instead of breaking it — and a
    palette that never got uploaded fails here rather than silently matching
    nothing.

    THE KNIGHT'S PALETTE IS IN HERE FOR A REASON. `_classify` picks the
    NEAREST entry it is given, so a palette holding only the BG colours has no
    choice but to call every knight pixel a background one — and his helmet
    highlight landed on the plate's top-edge index, which made `plate_y` report
    HIM as a plate three rows above where the plate actually is. Three cases
    went red and none of them were about the sprite. Entries 48..63 are OBJ
    palette 0 (CGRAM word ES_C_SMT_OBJ_PAL onward), so a knight pixel now
    classifies as a knight pixel and the column scans walk past him.

    The 80 words between the BG palettes and his are NOT read: nothing uploads
    them, they hold power-on garbage, and offering them to a nearest-match
    would let random colour steal a classification.
    """
    raw = m.read_bytes(C, 0, 48 * 2)
    obj = m.read_bytes(C, CG_OBJ * 2, 16 * 2)
    return [_cg(raw, i) for i in range(48)] + [_cg(obj, i) for i in range(16)]


OBJ_IX0 = 48                    # where the knight's 16 entries start above


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
    """One settled frame of the works scene: the picture, the palette, the
    phase the row it was drawn from was chosen by, and the CAMERA — which is
    the second coordinate every equality now needs, because a screen column
    only names a world column once you know where the camera is."""
    out = tmp_path_factory.mktemp("smt")
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        phase = m.read_u16(W, DP_PHASE)
        cam = m.read_u16(W, DP_CAM_SHOWN)
        p = out / "works.png"
        m.screenshot(str(p))
    return Image.open(p).convert("RGB"), pal, phase, cam


def _fit(im, pal, phase, cam):
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
        vis = visible(row(idx), cam)
        bad = 0
        for c in range(COLS):
            w = vis[c]
            if not (w & BIT_BG2):
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

def test_the_world_column_under_a_screen_column_is_the_one_that_moves_it(frame):
    """MEASURED, NOT ASSUMED — and the thing being measured moved.

    In mode 2 the PPU runs GetTilemapData for BG2 and BG1 BEFORE
    GetHorizontalOffsetByte/GetVerticalOffsetByte inside a column's eight-cycle
    group, so the words fetched with index g are latched in time for column
    g+1. The table used to be screen-space with that lead baked into the blob;
    it is world-space now and the DMA applies the lead at its READ HEAD, from
    world column cam+1. The two cancel exactly, and the claim this asserts is
    the resulting one: **screen column sc is displaced by the word for world
    column cam + sc**, with no offset in either direction.

    Sharp on both sides — a shift of +/-1 must NOT explain the picture — which
    is what makes it a measurement of the read head's alignment rather than a
    fitted tolerance. Get it wrong by one and every column is displaced by its
    neighbour's word, which is a picture that still moves and still looks like
    a foundry.
    """
    im, pal, phase, cam = frame
    _, lag, idx = _fit(im, pal, phase, cam)[0]
    base = row(idx)
    c0 = cam >> 3
    for shift in (-1, 0, 1):
        bad = 0
        for c in range(1, COLS - 1):
            w = base[c0 + c + shift]
            if not (w & BIT_BG2):
                continue
            y = crust_y(im, pal, c)
            if y is None or y != where(CRUST_PX, w & VALUE_MASK):
                bad += 1
        if shift == 0:
            assert bad == 0, "the aligned row does not explain the picture"
        else:
            assert bad > 0, (
                f"a shift of {shift:+d} explains the picture too — the read "
                f"head's alignment is not being measured, it is being assumed")


def test_every_melt_column_stands_where_its_word_says(frame):
    """THE HEADLINE EQUALITY. Not "the melt moves": every gap column's crust
    line is at exactly `map row - word - 1`, against the word the ROM holds
    for that column in the row the picture was drawn from."""
    im, pal, phase, cam = frame
    bad, lag, idx = _fit(im, pal, phase, cam)[0]
    assert bad == 0, f"row {idx} (lag {lag}) leaves {bad} column(s) unexplained"
    vis = visible(row(idx), cam)
    checked = 0
    for c in range(COLS):
        w = vis[c]
        if not (w & BIT_BG2):
            continue
        assert crust_y(im, pal, c) == where(CRUST_PX, w & VALUE_MASK), \
            f"screen column {c} (world {(cam >> 3) + c}): crust is not where " \
            f"word ${w:04X} puts it"
        checked += 1
    assert checked >= 12, f"only {checked} melt columns were decidable"


def test_every_plate_column_stands_where_its_word_says(frame):
    """...and the same equality on the OTHER layer, driven by the OTHER
    enable bit out of the same 32 words. Two layers, one table, one value a
    column — the composition's whole shape, asserted on the picture."""
    im, pal, phase, cam = frame
    _, _, idx = _fit(im, pal, phase, cam)[0]
    vis = visible(row(idx), cam)
    checked = 0
    for c in range(COLS):
        w = vis[c]
        if not (w & BIT_BG1):
            continue
        assert plate_y(im, pal, c) == where(PLAT_PX, w & VALUE_MASK), \
            f"screen column {c} (world {(cam >> 3) + c}): the plate is not " \
            f"where word ${w:04X} puts it"
        checked += 1
    # However many plate columns the camera happens to be showing — which is
    # the point of a world: what is on screen is a window, not the level.
    assert checked >= PLAT_WIDTH, f"only {checked} plate column(s) on screen"


def test_the_frame_geometry_is_the_one_this_module_assumes(frame):
    """PICTURE_TOP is imported, and re-solved here anyway.

    frame_geometry.py's own rule: sharing a constant makes it consistent, it
    does not make it true. So this predicts every decidable melt column at
    seven candidate PNG offsets and requires EXACTLY ONE to mismatch zero
    columns — which is the same shape the split-demo predictors use, on a
    picture whose per-column heights vary and therefore constrain the fit far
    more tightly than a uniform one would.
    """
    im, pal, phase, cam = frame
    _, _, idx = _fit(im, pal, phase, cam)[0]
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
    im, pal, _, cam = frame
    assert crust_y(im, pal, 0) == where(CRUST_PX, MELT_BASE)


def test_the_row_bias_is_what_the_rail_says(frame):
    """The off-by-one in game/smelter/smelter.inc, checked against the
    PICTURE rather than against itself: with the bias removed, no column
    would land."""
    im, pal, phase, cam = frame
    _, _, idx = _fit(im, pal, phase, cam)[0]
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
    im, pal, _, cam = frame
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
    im, pal, _, cam = frame
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
    im, pal, phase, cam = frame
    _, _, idx = _fit(im, pal, phase, cam)[0]
    r = row(idx)
    for first, width in PLATES:
        vals = {r[first + i] & VALUE_MASK for i in range(width)}
        assert len(vals) == 1, f"plate at {first} carries {vals}"


def test_the_wall_does_not_move_when_its_column_does(tmp_path):
    """THE COST OF ONE VALUE A COLUMN, PAID IN ART RATHER THAN IN MOTION.

    BG2 carries the cavern wall AND the crust AND the melt body, and a column's
    word displaces the WHOLE column of the layer — one value per column per
    layer is what the hardware gives, so nothing can move the melt and hold the
    wall still. The rail's answer is not to separate them but to make the wall
    INVARIANT under vertical displacement: one tile, every one of its eight rows
    identical, so sliding it costs nothing to look at.

    THAT CLAIM WAS FALSE FOR A WHILE AND NOTHING CAUGHT IT. The tile was
    uniform; the MAP alternated two streak phases on `(c + r) % 2`, and swapping
    the tile every 8 map rows IS a horizontal seam every 8 pixels — the exact
    feature the tile avoided, reintroduced one function later. A displaced
    column slid that seam past the screen and the streaks jumped 3 px sideways
    every 8 px of travel: the background visibly moving with the melt. The owner
    saw it in the gallery clip; no case here could, because every case measured
    the crust's POSITION and none measured what the rest of the column did while
    it moved. There is now only ONE wall tile, so there is no alternation left
    to get wrong.

    THE PAIR IS TWO CAPTURES WITH IDENTICAL ART, AND THAT IS WHAT MAKES THIS A
    ONE-VARIABLE COMPARISON. The wall's pattern lives in its PALETTE now and
    rotates; the melt's CHR swaps. So a pair has to be matched on the art
    itself, and it is matched on the BYTES — the wall's CGRAM words and the
    animated CHR block, read off the machine at each capture. Two frames whose
    palette and CHR are identical differ ONLY in how far each column is
    displaced, and a difference in the wall band is then attributable to
    nothing else.

    MATCHED ON THE BYTES RATHER THAN ON THE PHASE, and the phase was tried
    first. `TS_STEP` publishes WHOLE units and carries the fraction, so the
    phase advances 1 on some frames and 0 on others: the lag between "the phase
    a test reads" and "the phase the NMI drew from" is not constant, and two
    captures at equal `phase % 16` were drawn from different steps often enough
    to fail. The art in CGRAM and VRAM is what actually drew the frame.
    """
    shots = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        for i in range(18):
            m.advance(5)
            art = (m.read_bytes(C, (CG_MELT + WALL_IX0) * 2, WALL_SHADES * 2),
                   _vram_chr(m))
            f = tmp_path / f"w{i}.png"
            m.screenshot(str(f))
            shots.append((art, Image.open(f).convert("RGB")))

    checked = moved = 0
    for i, (ka, a) in enumerate(shots):
        for kb, b in shots[i + 1:]:
            if ka != kb:
                continue                    # ...different art; not comparable
            for c in range(COLS):
                if plate_of(c) is not None:
                    continue                # BG1's plates hang in this band
                ya, yb = crust_y(a, pal, c), crust_y(b, pal, c)
                if ya is None or yb is None:
                    continue
                if abs(ya - yb) >= 8:
                    moved += 1
                checked += 1
                for y in range(2, min(ya, yb) - 2):
                    for x in range(8 * c, 8 * c + 8):
                        assert a.getpixel((x, PICTURE_TOP + y)) \
                            == b.getpixel((x, PICTURE_TOP + y)), (
                                f"column {c} row {y}: the wall moved with the "
                                f"melt. Its crust went {ya} -> {yb}, and at "
                                f"equal art phase everything above "
                                f"{min(ya, yb) - 2} is supposed to be invariant "
                                f"under the displacement that carried it")
    assert checked, "no two captures landed on the same art phase — nothing " \
                    "was compared at all"
    assert moved >= 4, \
        f"only {moved} column comparison(s) had the crust move 8 px — the " \
        f"invariance is not being tested against any displacement"


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


def test_the_flat_row_is_a_row_and_not_a_disarm(tmp_path):
    """THE CONTROL'S OWN CLAIM, read out of VRAM.

    "Flat" has to mean the same mechanism carrying different values, or it is
    not a control: if flattening also cleared the enable bits, running and
    flat would differ in the values AND in whether the offset path applies to
    anything, and a two-variable comparison cannot attribute what it shows.

    A PICTURE CANNOT SEE THIS. A row of zeros levels every column too —
    falling back to BG1VOFS/BG2VOFS lands on exactly the two base values the
    flat row carries — so the flat frame is identical either way. The
    falsification harness found this hole by planting exactly that
    (`tools/plants/smelter.py::flat-row-clears-the-enable-bits`); this is the
    assertion that closes it, and it reads the DESTINATION VRAM row rather
    than the blob, so it also proves the flat row is the one that got there.
    """
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        m.advance(1, pad1=JOY_B)
        m.advance(20)
        assert m.read_u16(W, DP_FLAT) == 1
        v = m.read_bytes(V, (VRAM_TABLE + COLS) * 2, ROW_BYTES)
    assert v == BLOB[FLAT_ROW * ROW_BYTES:(FLAT_ROW + 1) * ROW_BYTES], \
        "BG3's V row is not the blob's flat control row"
    words = [None] + [v[2 * c] | (v[2 * c + 1] << 8) for c in range(COLS - 1)]
    for c in range(1, COLS):
        w = words[c]
        assert w & (BIT_BG1 | BIT_BG2), \
            f"column {c}'s flat word ${w:04X} drives NO layer — the control " \
            f"disarms the mechanism instead of levelling it"
        want = PLAT_BASE if plate_of(c) is not None else MELT_BASE
        assert w & VALUE_MASK == want, \
            f"column {c}'s flat word ${w:04X} is not its layer's base"
        assert bool(w & BIT_BG1) == (plate_of(c) is not None), \
            f"column {c}'s flat word drives the wrong layer"


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
# the melt's CHR animation — the same map, different pixels
# ==========================================================================
#
# The classic BG swap, and the point of asserting it here is that it is the one
# kind of motion in this rail that is NOT the offset table. Four contiguous CHR
# slots are rewritten every VBlank; not one tilemap word moves and not one
# column's displacement changes. So the two mechanisms have to be shown apart,
# and the rail already owns the instrument for that: THE FLAT CONTROL. With
# every column standing on its base, anything left moving in the melt is the
# CHR and can be nothing else.

ANIM_FIRST = _art("SMT_MELT_ANIM_FIRST")
ANIM_TILES = _art("SMT_MELT_ANIM_TILES")
ANIM_FRAMES = _art("SMT_MELT_ANIM_FRAMES")
ANIM_SHIFT = _art("SMT_MELT_ANIM_SHIFT")
ANIM_BYTES = _art("SMT_MELT_ANIM_BYTES")
WALL_IX0 = _art("SMT_WALL_IX0")
WALL_SHADES = _art("SMT_WALL_SHADES")
WALL_FRAMES = _art("SMT_WALL_PAL_FRAMES")
WALL_SHIFT = _art("SMT_WALL_PAL_SHIFT")
VRAM_CHR = _sym("ES_V_SMT_CHR")["start"]            # in WORDS


def _anim_blob():
    """The animation's frames, out of build/smelter.sfc — the same oracle rule
    the column table gets: found by SEARCHING the ROM image, so locating it is
    itself the proof that the blob reached the binary."""
    want = (ASSETS / "smt_melt_anim.bin").read_bytes()
    rom = ROM.read_bytes()
    at = rom.find(want)
    assert at >= 0, "the melt animation is not in build/smelter.sfc"
    assert rom.find(want, at + 1) < 0, "the melt animation appears twice"
    return [rom[at + i * ANIM_BYTES:at + (i + 1) * ANIM_BYTES]
            for i in range(ANIM_FRAMES)]


ANIM = _anim_blob()


def _vram_chr(m):
    return m.read_bytes(V, (VRAM_CHR + ANIM_FIRST * 16) * 2, ANIM_BYTES)


def test_the_melt_chr_in_vram_is_the_frame_the_rom_holds():
    """THE DESTINATION REGION AGAINST THE ROM'S BYTES, and the index against
    the phase.

    Two claims in one pass, both exact. The 128 B in VRAM must equal ONE of the
    eight frames in the blob — not resemble one — which is what says the
    transfer moved the right bytes to the right place. And which one must be
    `(phase >> SHIFT) & (FRAMES - 1)` at a CONSTANT lag across every capture:
    the NMI commits a frame and the main thread advances the phase afterwards,
    so the pixels on screen are one behind the phase a test can read, and a lag
    that varied would mean the index was not a function of the phase at all.

    That last part is what keeps the gallery clip's seam at zero, so it is
    asserted rather than assumed.
    """
    seen = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        for _ in range(8):
            m.advance(5)
            v = _vram_chr(m)
            hits = [i for i, f in enumerate(ANIM) if f == v]
            assert len(hits) == 1, \
                f"VRAM's animated block matches {len(hits)} of the blob's " \
                f"{ANIM_FRAMES} frames — it should be exactly one"
            seen.append((m.read_u16(W, DP_PHASE), hits[0]))
    lags = [lag for lag in range(3)
            if all(((ph - lag) >> ANIM_SHIFT) % ANIM_FRAMES == f
                   for ph, f in seen)]
    assert len(lags) == 1, \
        f"no single lag explains the frame index: {seen} (lags {lags})"
    assert len({f for _, f in seen}) >= 4, \
        f"only {len({f for _, f in seen})} frame(s) were ever uploaded"


def test_the_melt_churns_while_every_column_stands_still(tmp_path):
    """THE CHR SWAP, ISOLATED BY THE RAIL'S OWN CONTROL — and the reason the
    control does NOT freeze it.

    B selects the offset table's flat row: every column at its base, every
    enable bit still set, nothing displaced. So the crust line is one flat row
    across the whole screen and stays there. Anything still moving in the melt
    under those conditions is the CHR and can be nothing else, which is the
    only way to show these two mechanisms apart — a running frame moves for
    both reasons at once.

    IT WOULD HAVE BEEN EASY TO FREEZE THE LAVA WITH THE TABLE, and wrong: the
    control's whole value is that exactly ONE variable moves between running
    and flat. A control that also stopped the CHR would leave two, and a
    two-variable comparison cannot attribute what it shows. So the lava churns
    in both states, and this case is where that decision is written down.
    """
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        m.advance(1, pad1=JOY_B)
        m.advance(20)
        assert m.read_u16(W, DP_FLAT) == 1
        pal = _palette(m)
        rows, chrs = [], []
        for i in range(8):
            m.advance(5)
            chrs.append(_vram_chr(m))
            f = tmp_path / f"c{i}.png"
            m.screenshot(str(f))
            im = Image.open(f).convert("RGB")
            top = crust_y(im, pal, 0)
            band = tuple(im.getpixel((x, PICTURE_TOP + top + dy))
                         for dy in range(4, 20) for x in range(0, 64))
            rows.append((top, band))

    tops = {t for t, _ in rows}
    assert tops == {where(CRUST_PX, MELT_BASE)}, \
        f"the picture is not flat — the crust sits at {tops}"
    bands = [b for _, b in rows]
    assert len(set(bands)) >= 4, \
        f"only {len(set(bands))} distinct melt picture(s) with the columns " \
        f"stationary — the CHR swap is not reaching the screen"
    # ...and the pixels are a FUNCTION of the CHR: same block, same picture.
    byblock = {}
    for c, b in zip(chrs, bands):
        byblock.setdefault(c, set()).add(b)
    assert all(len(v) == 1 for v in byblock.values()), \
        "the same CHR block drew two different melts — something other than " \
        "the swap is moving under the flat control"
    assert len(byblock) == len(set(bands)), \
        "two CHR blocks drew the same melt — a frame is a duplicate"


def _wall_pal_blob():
    """The wall's cycle steps, out of build/smelter.sfc — same oracle rule."""
    want = (ASSETS / "smt_wall_pal.bin").read_bytes()
    rom = ROM.read_bytes()
    at = rom.find(want)
    assert at >= 0, "the wall's colour cycle is not in build/smelter.sfc"
    assert rom.find(want, at + 1) < 0, "it appears twice"
    n = WALL_SHADES * 2
    return [rom[at + i * n:at + (i + 1) * n] for i in range(WALL_FRAMES)]


WALL_PAL = _wall_pal_blob()


def test_the_wall_pattern_flows_one_way_across_the_screen(tmp_path):
    """THE PALETTE CYCLE, AND THE DIRECTION IT MOVES — read off the picture.

    The wall carries NO pattern in its pixels: one tile, every row identical,
    every column its own palette index. So what a viewer sees travelling is the
    eight colours those indices hold, rotating. This is the case that says it
    travels, that it travels ONE WAY, and that the way is left to right.

    THE MEASUREMENT IS THE BRIGHT BAND'S COLUMN. Each step puts the ramp's peak
    at one pixel column of the tile; the case finds it in the rendered frame and
    requires the sequence of positions to advance by exactly +1 (mod 8) from one
    step to the next. A cycle that jittered, reversed, or skipped would satisfy
    "the wall changes" and fail this, which is the difference between animation
    and a direction.

    UNDER THE FLAT CONTROL, so nothing is displaced while it is measured: the
    columns stand still and the only thing moving in the wall band is colour.
    """
    seen = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        m.advance(1, pad1=JOY_B)
        m.advance(20)
        assert m.read_u16(W, DP_FLAT) == 1
        for i in range(14):
            m.advance(4)
            cg = m.read_bytes(C, (CG_MELT + WALL_IX0) * 2, WALL_SHADES * 2)
            f = tmp_path / f"f{i}.png"
            m.screenshot(str(f))
            im = Image.open(f).convert("RGB")
            row = [im.getpixel((x, PICTURE_TOP + 20)) for x in range(WALL_SHADES)]
            seen.append((cg, row.index(max(row, key=sum))))

    # The CGRAM the machine holds must be one of the ROM's steps, and the peak
    # in the PICTURE must be the peak in that step — the palette reached the
    # screen, not merely CGRAM.
    steps = []
    for cg, peak in seen:
        hits = [i for i, f in enumerate(WALL_PAL) if f == cg]
        assert len(hits) == 1, \
            f"the wall's CGRAM matches {len(hits)} of the blob's " \
            f"{WALL_FRAMES} steps — it should be exactly one"
        words = [cg[2 * j] | (cg[2 * j + 1] << 8) for j in range(WALL_SHADES)]
        bright = max(range(WALL_SHADES), key=lambda j: sum(
            ((words[j] >> sh) & 31) for sh in (0, 5, 10)))
        assert bright == peak, \
            f"step {hits[0]}: the palette's brightest entry is {bright} and " \
            f"the picture's brightest column is {peak}"
        steps.append(hits[0])

    assert len(set(steps)) >= 5, f"the cycle barely moved: {steps}"
    # ...and every advance is exactly one column to the RIGHT.
    for a, b in zip(steps, steps[1:]):
        d = (b - a) % WALL_FRAMES
        assert d in (0, 1), \
            f"the cycle went {a} -> {b}: a step of {d}, not a flow"
    assert any((b - a) % WALL_FRAMES == 1 for a, b in zip(steps, steps[1:]))
    peaks = [p for _, p in seen]
    for a, b in zip(peaks, peaks[1:]):
        assert (b - a) % WALL_SHADES in (0, 1), \
            f"the bright band jumped {a} -> {b} — it is not flowing one way"


def test_the_wall_cycle_cannot_impersonate_a_measured_edge():
    """THE INSTRUMENT, PROTECTED — and this is the constraint a palette cycle
    has that a CHR swap does not.

    Every column scan in this module finds its edge by NEAREST CGRAM COLOUR
    against a palette read ONCE. While the wall's colours rotate, a wall pixel's
    actual colour need not be in that snapshot at all — it is matched to
    whatever is closest. So the requirement is not "the wall looks different
    from the crust": it is that every wall shade is closer to some OTHER WALL
    SHADE than to either measured edge, at every step, which holds for every
    snapshot at once.

    Checked here against the ROM's own bytes because the generator asserts the
    same thing, and the generator is what would be wrong.
    """
    shades = set()
    for f in WALL_PAL:
        for j in range(WALL_SHADES):
            shades.add(f[2 * j] | (f[2 * j + 1] << 8))

    def rgb(w):
        return tuple((w >> s) & 31 for s in (0, 5, 10))

    def d2(a, b):
        return sum((x - y) ** 2 for x, y in zip(rgb(a), rgb(b)))

    span = max(d2(a, b) for a in shades for b in shades)
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        raw = m.read_bytes(C, 0, 48 * 2)
    edges = {"the crust's white-hot line": (CG_MELT + 3),
             "the plate's top edge": (CG_PLATE + 4)}
    for name, ix in edges.items():
        w = raw[2 * ix] | (raw[2 * ix + 1] << 8)
        worst = min(d2(s, w) for s in shades)
        assert worst > span, \
            f"a wall shade is within {worst} of {name} while the ramp's own " \
            f"span is {span} — a stale palette snapshot could nearest-match a " \
            f"wall pixel to that edge, and every column scan would find the wall"


def test_the_crust_edge_survives_every_animation_frame():
    """THE ONE ROW THE ANIMATION MAY NOT TOUCH, checked against the ROM.

    `CRUST_IX` — the melt's unbroken white-hot top row — is the edge every
    per-column equality in this module lands on. The animation rewrites the
    crust tiles, so an author adding a frame set that disturbed row 0 would
    take the whole module down at once, with a failure that pointed at the
    offset table and not at the art.

    So: in every frame the ROM holds, the first bitplane row of each crust tile
    is the same as frame 0's. Read out of the blob rather than from the
    generator, because the generator is what would be wrong.
    """
    for i, f in enumerate(ANIM):
        for t in range(2):              # the two crust tiles lead the block
            base, ref = f[t * 32:t * 32 + 2], ANIM[0][t * 32:t * 32 + 2]
            assert base == ref, \
                f"frame {i}, crust tile {t}: row 0 is {base.hex()} against " \
                f"frame 0's {ref.hex()} — the edge every measurement reads " \
                f"is not invariant under the animation"


# ==========================================================================
# the knight — the number is a fact about the WORLD, not about the display
# ==========================================================================
#
# A picture can show that every column scrolls on its own. Only something that
# STANDS on one can show that the offset is a position rather than a display
# trick, and that is what this section asserts: the knight's feet, IN THE
# PICTURE, on the plate's top edge, IN THE PICTURE, at whatever height the word
# THE ROM HOLDS puts it — every frame, through a jump, through a fall, and
# through the flat control.
#
# HE IS FOUND BY HIS OWN PALETTE, never by where he is expected to be.
# `_palette` carries OBJ palette 0 at OBJ_IX0.., so `_knight` is a scan of the
# whole picture for pixels that are his — which means a knight drawn in the
# wrong place, or not drawn at all, fails here rather than being looked for
# somewhere else.

KN_BOX = _art("SMT_KN_BOX")             # the sprite's 32x32 cell
KN_BOTTOM = _art("SMT_KN_BOTTOM")       # ...and where its drawn content ends
DP_KN_X = _sym("ES_SMT_KN_X")["start"]
OAM = MemoryType.SnesSpriteRam


def _knight(im, pal):
    """The bounding box of the knight's OWN pixels, in screen coordinates.

    Returns (x0, x1, y0, y1), or None if he is not in the picture at all —
    which is a real state, not a failure: a jump carries him off the top edge.
    """
    xs, ys = [], []
    for y in range(PICTURE_TOP, im.size[1]):
        for x in range(im.size[0]):
            if _classify(im.getpixel((x, y))[:3], pal) >= OBJ_IX0:
                xs.append(x)
                ys.append(y - PICTURE_TOP)
    return (min(xs), max(xs), min(ys), max(ys)) if xs else None


def _feet(im, pal):
    """The picture row his lowest drawn pixel sits ABOVE — where the metal
    starts if he is standing on it."""
    b = _knight(im, pal)
    return None if b is None else b[3] + 1


def _cols_of(x):
    """The screen columns a 32-pixel box at `x` covers."""
    return range(x // 8, (x + KN_BOX - 1) // 8 + 1)


def _under(im, pal, kn_x):
    """The plate top in the columns a knight at `kn_x` occupies, and None when
    he is over a gap or straddling two plates at different heights."""
    ys = {plate_y(im, pal, c) for c in _cols_of(kn_x)}
    ys.discard(None)
    return ys.pop() if len(ys) == 1 else None


def _kn_x():
    """His X, off the machine at the settled frame every case here starts from.

    A coordinate, not a measurement: it decides WHICH columns to look in, the
    way the phase decides which row of the oracle to join against.
    """
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        return m.read_u16(W, DP_KN_X)


def test_the_knight_is_the_sprite_the_oam_entry_describes(frame):
    """THE DESTINATION REGION AND THE PICTURE, joined.

    OAM says a 32x32 sprite at (X, Y); the picture says pixels in OBJ palette
    0 somewhere. Either half alone is passable while the other is broken — an
    entry with the size bit clear draws a plausible 16x16 corner, and a CHR or
    CGRAM upload that never fired draws a perfectly valid sprite made of
    power-on noise (rule 5). This requires the pixels to fall inside the box
    the entry declares.

    The hardware OAM is one frame behind the shadow the tick stages, so the Y
    is not compared here — the X does not move in this scene, and containment
    is what the case is about. The rows are the ride cases below.
    """
    im, pal, _, cam = frame
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        entry = m.read_bytes(OAM, 0, 4)
        hi = m.read_bytes(OAM, 512, 1)[0]
    assert hi & 0b10 == 0b10, f"OAM hi byte ${hi:02X}: the 32x32 size bit is clear"
    assert hi & 0b01 == 0, "X9 is set with the knight on the left of the screen"
    b = _knight(im, pal)
    assert b is not None, "no pixel in the picture is in the knight's palette"
    assert entry[0] <= b[0] and b[1] <= entry[0] + KN_BOX - 1, \
        f"his pixels span x {b[0]}..{b[1]}, outside the entry at x={entry[0]}"
    assert b[3] - b[2] + 1 <= KN_BOX


def test_the_knight_stands_on_the_word_the_rom_holds(frame):
    """THE SPRITE'S HEADLINE, and it closes the chain in one statement.

    His feet are at `map row - word - 1` for the word THE ROM HOLDS for his own
    columns, in the row the picture was drawn from. Not "he is near the plate",
    and not "his state variable agrees with the plate's" — the PIXELS where his
    art stops, against the BYTES in build/smelter.sfc.

    That is only true because there is one number: `smt_kn_ride` takes his Y
    from `smt_plate_top`, which reads the same blob the VBlank transfer moves
    into VRAM. A rail that computed the collision separately would pass this on
    the frame it was tuned for and drift on every other one.
    """
    im, pal, phase, cam = frame
    _, _, idx = _fit(im, pal, phase, cam)[0]
    words = {row(idx)[c] & VALUE_MASK for c in _cols_of(_kn_x())}
    assert len(words) == 1, f"the knight straddles two heights: {words}"
    assert _feet(im, pal) == where(PLAT_PX, words.pop()), \
        "his feet are not where the plate's own word puts the metal"


def test_the_knight_rides_the_plate_rather_than_hovering_over_it(tmp_path):
    """A SINGLE FRAME CANNOT TELL A RIDE FROM A COINCIDENCE.

    Six captures spread across the harmonic, and the equality has to hold at
    every one of them: a knight pinned to a screen row would match on the frame
    he was placed and miss the other five. The travel is asserted too, because
    a plate that had stopped moving would make the case vacuous.
    """
    kn_x = _kn_x()
    pal, shots = _drive(tmp_path, [(7, None)] * 6)
    seen = []
    for im, _, _ in shots:
        under = _under(im, pal, kn_x)
        assert under is not None, "the knight is not over exactly one plate"
        assert _feet(im, pal) == under, \
            f"feet at {_feet(im, pal)}, metal at {under}"
        seen.append(under)
    assert len(set(seen)) >= 4, f"the plate barely moved: {seen}"
    assert max(seen) - min(seen) >= 30, f"only {max(seen) - min(seen)} px of travel"


def test_the_flat_control_levels_the_knight_too(tmp_path):
    """The control, applied to the player. Flattening the table puts every
    plate on its base — and the knight goes with it, because the height he
    stands at is read out of the table rather than held anywhere of his own."""
    pal, shots = _drive(tmp_path, [(20, JOY_B)])
    im, _, flat = shots[0]
    assert flat == 1
    assert _feet(im, pal) == where(PLAT_PX, PLAT_BASE)


def test_the_jump_leaves_the_metal_and_the_metal_catches_him_again(tmp_path):
    """THE WHOLE TIME-AXIS CYCLE, not the apex.

    An apex-only case passes while the landing embeds him in the floor, which
    is a documented way to ship a broken platformer. This drives ascent, apex,
    descent and landing and requires all four: he leaves the metal, he goes off
    the TOP of the picture entirely, he comes back down onto the plate at the
    ride equality, and the plate is still moving under him afterwards.

    Leaving the picture is also the case that would have caught the vertical
    unit: at 8.8 a Y above the screen and a Y below the world are the same bit
    pattern, and the first build read row 236 as negative and wrapped him back
    to the top instead of respawning him.
    """
    kn_x = _kn_x()
    pal, shots = _drive(tmp_path, [(3, {"a": True})] + [(3, None)] * 21)
    frames = [(_feet(im, pal), _under(im, pal, kn_x)) for im, _, _ in shots]
    assert any(feet is None for feet, _ in frames), \
        "he never leaves the top of the picture — the jump is not a jump"
    airborne = [i for i, (feet, under) in enumerate(frames)
                if feet is not None and under is not None and feet < under - 8]
    assert airborne and airborne[0] == 0, \
        f"he is on the metal at the start of the arc: {frames}"
    landed = [i for i, (feet, under) in enumerate(frames)
              if feet is not None and under is not None and feet == under]
    assert landed, f"he never lands: {frames}"
    assert landed[0] > max(airborne[:1]), "he lands before he rises"
    assert landed == list(range(landed[0], len(frames))), \
        f"he lands and then leaves the metal again untold: {landed}"
    assert frames[landed[0]][1] != frames[-1][1], \
        "the plate stopped moving after the landing — the ride did not resume"


def _hold(tmp_path, pad, shots, every):
    """Drive the works scene with `pad` HELD, capturing every `every` frames.

    `_drive` taps a pad for one frame — right for the toggles it was written
    for, and useless for a walk, which needs the button down. The knight covers
    two pixels a frame, so a tap moves him two.
    """
    out = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        for i in range(shots):
            m.advance(every, pad1=pad)
            f = tmp_path / f"h{i}.png"
            m.screenshot(str(f))
            out.append((Image.open(f).convert("RGB"), m.read_u16(W, DP_KN_X)))
    return pal, out


def test_walking_off_the_span_drops_him_and_the_world_gives_him_back(tmp_path):
    """The other state cycle, on the horizontal axis, and every step of it is
    read off the picture.

    He starts ON the metal; he is carried past his plate's four columns; he
    falls, which is asserted as his feet being further below the nearest metal
    than he is tall rather than as "his state variable says airborne"; he
    reaches the bottom of the world — out of the picture, or past two thirds of
    it, and he cannot leave through the top while walking; and he comes back
    standing on a plate at the ride equality, near where he started.

    The return is the half that needs the vertical sign to mean what it says.
    He passes row 232 on the way out, and in the 8.8 unit the first build used,
    that row and a row above the screen are the same bit pattern: the kill test
    read it as negative, skipped the respawn, and wrapped him round to the top
    of the screen instead.
    """
    span = _art("SMT_PLAT_WIDTH") * 8
    pal, shots = _hold(tmp_path, {"right": True}, 14, 6)
    start = shots[0][1]
    seen = []
    for im, kn_x in shots:
        box = _knight(im, pal)
        seen.append((kn_x, None if box is None else box[3] + 1,
                     _under(im, pal, kn_x)))

    riding = [i for i, (_x, f, u) in enumerate(seen) if u is not None and f == u]
    walked = [i for i, (x, _f, _u) in enumerate(seen) if x > start + span]
    falling = [i for i, (_x, f, u) in enumerate(seen)
               if f is not None and u is not None and f > u + KN_BOX]
    out = [i for i, (_x, f, _u) in enumerate(seen)
           if f is None or f > 2 * PICTURE_LINES // 3]

    assert riding and riding[0] == 0, f"he did not start on the metal: {seen}"
    assert walked, f"he never walked past his plate's {span} px of metal"
    # >= rather than >: the captures are six frames apart, so leaving the metal
    # and being visibly below it can land in the same one. The ORDER is the
    # claim; the cadence is not.
    assert falling and falling[0] >= walked[0], \
        "he walked off the metal and kept standing on air"
    assert out and out[0] >= falling[0], "he never reached the bottom of the world"
    back = [i for i in riding if i > out[0]]
    assert back, "he fell out of the world and never came back onto a plate"
    assert seen[back[0]][0] <= start + span, \
        f"he came back at x={seen[back[0]][0]}, not on the spawn plate"


def test_the_knight_does_not_hide_the_edge_the_per_column_cases_read(frame):
    """THE DEPENDENCY, NAMED — because three unrelated cases rest on it.

    `plate_y` scans a column for the plate's top-edge colour, and the knight
    stands in four of those columns. It keeps working only because the art
    frames every cell with transparent rows under the feet (SMT_KN_BOTTOM), so
    his lowest drawn pixel is ABOVE the edge rather than on it. Art whose
    content reached row 31 would occlude the edge and send
    test_every_plate_column_stands_where_its_word_says red with a message about
    the offset table, which is nowhere near the truth.

    So: in the columns he occupies, the plate's top-edge row is still a plate
    pixel — asserted here, once, where the reason is written down.
    """
    im, pal, _, cam = frame
    feet = _feet(im, pal)
    for c in _cols_of(_kn_x()):
        px = im.getpixel((8 * c + 3, PICTURE_TOP + feet))[:3]
        assert _classify(px, pal) == PLATE_IX, \
            f"column {c} at row {feet} is not the plate's edge — the knight " \
            f"is standing ON it and the plate cases are reading him"
    assert KN_BOTTOM < KN_BOX, "the art has no transparent rows under the feet"


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
