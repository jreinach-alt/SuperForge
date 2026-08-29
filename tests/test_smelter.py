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


def _rail(key):
    """One equate out of the HAND-WRITTEN game/smelter/smelter.inc.

    `_art` reads the generated file; this reads the rail's own, where the
    constants a person chose live — and they are expressions rather than
    literals there (`SMT_SINK_HOLD = (3 * 60 * SMT_PHASE_BASE) / 256`), which
    is the point: the value is derived from the unit it is expressed in. So
    this resolves earlier equates in the same file and evaluates, rather than
    matching an integer.

    READ, NOT RETYPED, for the same reason `_art` is. A hold asserted against a
    number typed here would keep passing after somebody shortened the hold.
    """
    env, want = {}, None
    for line in (SUPERFORGE / "game" / "smelter" / "smelter.inc").read_text().splitlines():
        head, eq, rest = line.partition("=")
        name = head.strip()
        if not eq or not name.isidentifier():
            continue
        expr = rest.split(";")[0].strip().replace("$", "0x")
        if not expr or not all(c.isalnum() or c in " _()+-*/<>|&$" for c in expr):
            continue
        try:
            env[name] = eval(expr, {"__builtins__": {}}, dict(env))   # noqa: S307
        except Exception:
            continue
        if name == key:
            want = env[name]
    if want is None:
        raise KeyError(f"{key} is not a resolvable equate in smelter.inc")
    return int(want)


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
    """One BGR555 word as the 8-bit RGB the SCREENSHOT will hold.

    THE EXPANSION IS THE HARDWARE'S, NOT A RESCALE. A 5-bit channel becomes
    `(v << 3) | (v >> 2)` — the top bits repeated into the bottom — and not
    `v * 255 // 31`. The two agree at 0 and 31 and differ by one in between:
    value 17 is 140 the first way and 139 the second, value 30 is 247 and 246.
    Nearest-match classification never noticed, because one unit is far inside
    every margin here; an EXACT comparison notices immediately, and one cost an
    hour of chasing a splash that was rendering perfectly while the thing
    looking for it computed the wrong colour to look for.
    """
    v = raw[2 * i] | (raw[2 * i + 1] << 8)
    r, g, b = v & 0x1F, (v >> 5) & 0x1F, (v >> 10) & 0x1F
    return tuple((c << 3) | (c >> 2) for c in (r, g, b))


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
    for lag in range(5):
        idx = (phase - lag) % PHASES
        vis = visible(row(idx), cam)
        bad = 0
        for c in range(1, COLS):        # column 0 is not displaced by its own
            w = vis[c]                  #   word — see the fallback case below
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


def test_the_same_agreement_holds_with_the_camera_off_zero(tmp_path):
    """SCROLLING, ASSERTED WHERE IT ACTUALLY HAPPENS — and the case above
    cannot make this claim.

    There is one offset table and it is WORLD space, so scrolling is not a
    rebuild: the DMA's read head moves along a row it was already going to
    transfer, and the layers carry the sub-column remainder in their own H
    ports. The claim is therefore the SAME one — screen column sc shows the
    word for world column cam + sc — but at a camera that is not zero, which is
    the only place it has any content. At cam = 0 a read head that ignored the
    camera entirely produces a byte-identical picture, so every case that
    starts from the settled frame is blind to the whole mechanism.

    Sharp on both sides again, and the unit is now a WHOLE COLUMN: move the
    assumed camera by 8 px either way and no row may explain the picture at any
    lag.

    The camera is PLACED, by writing the knight's world X and the plate he is
    riding — the two quantities `smt_kn_camera` is a function of, at the one
    place the rail computes it. Nothing else is written and nothing else is
    read: the assertion is the rendered frame against the blob in the ROM. He
    is put on a plate rather than dropped into a gap because `_fit` reads the
    crust in gap columns, and a knight falling through them would be occluding
    the thing under test.
    """
    slot = next(i for i, (col, _w) in enumerate(PLATES) if col >= 2 * COLS)
    col, _w = PLATES[slot]
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        m.write_bytes(W, DP_KN_X, ((col + 1) * 8).to_bytes(2, "little"))
        m.write_bytes(W, DP_KN_PLATE, slot.to_bytes(2, "little"))
        m.advance(2)                    # the tick moves the camera, then a
        pal = _palette(m)               #   VBlank draws from it
        phase = m.read_u16(W, DP_PHASE)
        cam = m.read_u16(W, DP_CAM_SHOWN)
        p = tmp_path / "scrolled.png"
        m.screenshot(str(p))
    im = Image.open(p).convert("RGB")

    assert cam >= COLS * 8, f"the camera is still on the first screen: {cam}"
    bad, _lag, _idx = _fit(im, pal, phase, cam)[0]
    assert bad == 0, (
        f"no row of the blob explains the scrolled picture at cam={cam} "
        f"({bad} column(s) wrong at the best fit)")
    for d in (-8, +8):
        off = _fit(im, pal, phase, cam + d)[0][0]
        assert off > 0, (
            f"a camera of {cam + d} explains the picture as well as {cam} — "
            f"the read head is not tracking the camera by whole columns")


def test_every_melt_column_stands_where_its_word_says(frame):
    """THE HEADLINE EQUALITY. Not "the melt moves": every gap column's crust
    line is at exactly `map row - word - 1`, against the word the ROM holds
    for that column in the row the picture was drawn from."""
    im, pal, phase, cam = frame
    bad, lag, idx = _fit(im, pal, phase, cam)[0]
    assert bad == 0, f"row {idx} (lag {lag}) leaves {bad} column(s) unexplained"
    vis = visible(row(idx), cam)
    checked = 0
    for c in range(1, COLS):            # ...except column 0, which the
        w = vis[c]                      #   hardware cannot displace at all
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


def test_the_melt_behind_every_plate_is_one_calm_level(tmp_path):
    """THE DEFECT A PERSON SAW, and the case that had no counterpart.

    A word carries ONE enable bit. A plate column displaces BG1 and leaves BG2
    at BG2VOFS — so the melt behind every plate on screen, sixteen columns of
    thirty-two, is not in the table at all. It is whatever that one register
    holds.

    The rail used to load BG2VOFS with SCREEN COLUMN 0's word, to pay off the
    column the hardware cannot displace. Column 0 is a gap column most of the
    time, so the lava behind all four platforms rose and fell together in a
    rhythm belonging to the left edge, at a different rate from the jets beside
    it, and SNAPPED to the base whenever the camera put a plate under column 0.
    Every case in this module measured where the crust IS in the columns the
    table drives; not one measured the columns it does not.

    So: the melt behind the plates is ONE level, it is the melt's own base, and
    it does not move — across the harmonic and across the camera both, because
    the failure was visible only while something else was changing.
    """
    expect = where(CRUST_PX, _art("SMT_VOFS_BG2"))
    seen = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        for shot in range(8):
            if shot == 4:               # ...and now from somewhere else in
                slot = next(i for i, (col, _w) in enumerate(PLATES)
                            if col >= 2 * COLS)          # the world entirely
                m.write_bytes(W, DP_KN_X, ((PLATES[slot][0] + 1) * 8)
                              .to_bytes(2, "little"))
                m.write_bytes(W, DP_KN_PLATE, slot.to_bytes(2, "little"))
                m.advance(2)
            cam = m.read_u16(W, DP_CAM_SHOWN)
            p = tmp_path / f"calm{shot}.png"
            m.screenshot(str(p))
            im = Image.open(p).convert("RGB")
            rows = {crust_y(im, pal, c) for c in range(1, COLS)
                    if screen_plate_of(c, cam) is not None}
            rows.discard(None)
            seen.append((cam, sorted(rows)))
            m.advance(5)
    for cam, rows in seen:
        assert rows == [expect], (
            f"at cam={cam} the melt behind the plates is at {rows}, not the "
            f"one calm level {expect} — a plate column's BG2 is falling back "
            f"on a register somebody else is driving")
    assert len({cam for cam, _r in seen}) > 1, "the camera never moved"


def test_screen_column_zero_lands_when_the_port_it_falls_back_on_is_free(frame):
    """THE HARDWARE LIMIT, PAID WHERE IT CAN BE AND STATED WHERE IT CANNOT.

    The offset latches are cleared at the start of each scanline's fetch, so
    the leftmost column always shows its layer's own BGnVOFS. That register is
    not column 0's, though — it is the fallback for every column whose word
    drives the other layer — so column 0 can only be given its own answer on a
    layer nothing else is spending.

    BG1VOFS is such a layer: the columns falling back on it are gap columns,
    and a gap column has no plate pixels to place. So when column 0 is a plate
    column, its plate lands exactly on its word, and this case asserts that
    equality.

    BG2VOFS is not: every plate column's melt reads it. It is held at the
    melt's base for their sake, and the price is this — when column 0 is a gap
    column, its melt sits at the base instead of riding its jet. Asserted here
    as the KNOWN cost rather than left as an unexplained column, which is the
    difference between a limit and a bug.
    """
    im, pal, phase, cam = frame
    _, _, idx = _fit(im, pal, phase, cam)[0]
    w = visible(row(idx), cam)[0]
    if w & BIT_BG1:
        assert plate_y(im, pal, 0) == where(PLAT_PX, w & VALUE_MASK), \
            "column 0 is a plate column and BG1VOFS is free — it should land"
    else:
        assert crust_y(im, pal, 0) == where(CRUST_PX, _art("SMT_VOFS_BG2")), \
            "column 0's melt is neither at its word nor at the base it shares"


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
    c0 = cam >> 3
    tops = []
    for first, width in PLATES:
        sc = first - c0
        if sc < 0 or sc + width > COLS:
            continue                    # ...this slot is off screen
        ys = {plate_y(im, pal, sc + i) for i in range(width)}
        assert len(ys) == 1, f"the slot at world column {first} is not level: {ys}"
        tops.append(ys.pop())
    assert len(tops) >= 3, f"only {len(tops)} whole slot(s) on screen"
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
        assert len(vals) == 1, f"the slot at world column {first} carries {vals}"


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
        cam = m.read_u16(W, DP_CAM_SHOWN)
        v = m.read_bytes(V, (VRAM_TABLE + COLS) * 2, COLS * 2)
    # THE SLICE THE READ HEAD MOVED, not the whole row: the table is
    # world-space and the transfer takes 32 words starting one column past the
    # camera. Comparing against the row's start would only ever be right at the
    # world's left edge.
    head = (cam >> 3) + 1
    want = BLOB[FLAT_ROW * ROW_BYTES + head * 2:
                FLAT_ROW * ROW_BYTES + (head + COLS) * 2]
    assert v == want, "BG3's V row is not the flat control row at the camera"
    words = [v[2 * c] | (v[2 * c + 1] << 8) for c in range(COLS)]
    for j, w in enumerate(words):
        wc = head + j                   # ...the WORLD column this word is for
        assert w & (BIT_BG1 | BIT_BG2), \
            f"world column {wc}'s flat word ${w:04X} drives NO layer — the " \
            f"control disarms the mechanism instead of levelling it"
        base = PLAT_BASE if plate_of(wc) is not None else MELT_BASE
        assert w & VALUE_MASK == base, \
            f"world column {wc}'s flat word ${w:04X} is not its layer's base"
        assert bool(w & BIT_BG1) == (plate_of(wc) is not None), \
            f"world column {wc}'s flat word drives the wrong layer"


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
WALL_PX = _art("SMT_WALL_PX_PER_SHADE")     # ...pixels each shade covers
WALL_PERIOD = _art("SMT_WALL_PERIOD")       # ...so the band's period is this
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

    The wall carries NO pattern in its pixels: a run of four tiles, every row
    identical, every FOUR pixel columns one palette index. So what a viewer
    sees travelling is the eight colours those indices hold, rotating. This is
    the case that says it travels, that it travels ONE WAY, and that the way is
    left to right.

    THE MEASUREMENT IS THE BRIGHT BAND'S SHADE. Each step puts the ramp's peak
    on one of the eight shades; the case finds the brightest PIXEL across a
    whole 32-px period in the rendered frame, converts it to the shade it
    belongs to, and requires the sequence to advance by exactly +1 (mod 8) from
    one step to the next. A cycle that jittered, reversed, or skipped would
    satisfy "the wall changes" and fail this, which is the difference between
    animation and a direction.

    THE PIXELS-PER-SHADE IS READ, NOT ASSUMED. It was 1 — all eight shades in
    one 8-px tile — and that period was too fine to read as flow at the cycle's
    rate; widening it to 4 changed the picture and must not change this case's
    meaning, which is what `SMT_WALL_PX_PER_SHADE` being read out of the
    generated .inc buys.

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
            band = [im.getpixel((x, PICTURE_TOP + 20))
                    for x in range(WALL_PERIOD)]
            peak_px = max(range(WALL_PERIOD), key=lambda x: sum(band[x]))
            seen.append((cg, peak_px // WALL_PX))

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
            f"the picture's brightest shade is {peak}"
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


def test_the_wall_band_is_as_wide_as_the_rail_declares(frame):
    """THE PICTURE AGAINST THE DECLARATION, because the case above now MEASURES
    IN the declaration's unit.

    `test_the_wall_pattern_flows_one_way_across_the_screen` converts the
    brightest pixel to the shade it belongs to by dividing by
    `SMT_WALL_PX_PER_SHADE`. That is only a measurement of the flow if the
    emitted constant is TRUE OF THE ART — if the tiles were built at one pixel
    a shade while the .inc still said four, the flow case would divide by the
    wrong number, read a peak that is not there, and could pass or fail for
    reasons that have nothing to do with the cycle.

    So: on a wall row, across two full periods, the colour runs are exactly
    `SMT_WALL_PX_PER_SHADE` wide and there are exactly `SMT_WALL_SHADES` of
    them per `SMT_WALL_PERIOD`. Read off the rendered frame, against numbers
    read out of the generated .inc — neither of them typed here.

    This is also the case that says the band is wide enough to READ. The first
    version put all eight shades in one 8-px tile and the travelling band was a
    bright column every 8 pixels: technically a flow, visually a shimmer.
    """
    im, _pal, _phase, _cam = frame
    y = PICTURE_TOP + 20
    band = [im.getpixel((x, y))[:3] for x in range(2 * WALL_PERIOD)]

    runs = []
    for px in band:
        if runs and runs[-1][0] == px:
            runs[-1][1] += 1
        else:
            runs.append([px, 1])
    # the first and last run may be clipped by the window
    inner = runs[1:-1]
    assert inner, f"the wall row at y={y} is one flat colour: {runs}"
    assert all(n == WALL_PX for _c, n in inner), (
        f"the wall's colour runs are {[n for _c, n in inner]} px wide and the "
        f"rail declares SMT_WALL_PX_PER_SHADE = {WALL_PX}")
    assert len(inner) >= 2 * WALL_SHADES - 2, (
        f"only {len(inner)} runs across two periods of {WALL_PERIOD} px — the "
        f"art's period is not the {WALL_PERIOD} px the .inc emits")
    for x in range(WALL_PERIOD):
        assert band[x] == band[x + WALL_PERIOD], (
            f"the wall does not repeat at {WALL_PERIOD} px: pixel {x} and "
            f"pixel {x + WALL_PERIOD} differ")


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
DP_KN_PLATE = _sym("ES_SMT_KN_PLATE")["start"]
KN_AIRBORNE = 0xFFFF                    # smt_obj.asm: not a plate index
OAM = MemoryType.SnesSpriteRam

# --- the splash: the melt's answer, in his own OAM entry -------------------
DP_KN_SINK = _sym("ES_SMT_KN_SINK")["start"]
SPLASH_BOX = _art("SMT_SPLASH_BOX")
SPLASH_FRAMES = _art("SMT_SPLASH_FRAMES")
SPLASH_SHIFT = _art("SMT_SPLASH_SHIFT")
SPLASH_LIFE = _art("SMT_SPLASH_LIFE")
SPLASH_TILE0 = _art("SMT_SPLASH_TILE0")
SPLASH_STEP = _art("SMT_SPLASH_STEP")
V_OBJ_CHR = _sym("ES_V_SMT_OBJ_CHR")["start"]
CG_OBJ_PAL = _sym("ES_C_SMT_OBJ_PAL")["start"]
OBJ_GRID = 16                   # tiles across the OBJ name table's grid


def _obj_tile(m, tile):
    """One 4bpp OBJ tile out of VRAM, as an 8x8 grid of palette INDICES.

    Read from the hardware, never from the blob: the point of the case below is
    that what is on the screen is the tile the OAM entry names, so every link
    in that chain has to come off the machine.
    """
    d = m.read_bytes(V, (V_OBJ_CHR + tile * 16) * 2, 32)
    out = []
    for y in range(8):
        p0, p1, p2, p3 = d[y * 2], d[y * 2 + 1], d[16 + y * 2], d[16 + y * 2 + 1]
        out.append([((p0 >> (7 - x)) & 1) | (((p1 >> (7 - x)) & 1) << 1)
                    | (((p2 >> (7 - x)) & 1) << 2) | (((p3 >> (7 - x)) & 1) << 3)
                    for x in range(8)])
    return out


def _obj_cell(m, base):
    """The 16x16 an OAM entry draws from base tile `base`, as indices.

    The PPU reads a 16x16 sprite as {N, N+1, N+16, N+17} — the second row is
    a whole grid row away, not two tiles along — which is exactly why the
    splash's frames are laid out as 2x2 blocks stepping along ONE row.
    """
    tl, tr = _obj_tile(m, base), _obj_tile(m, base + 1)
    bl, br = _obj_tile(m, base + OBJ_GRID), _obj_tile(m, base + OBJ_GRID + 1)
    return ([a + b for a, b in zip(tl, tr)] + [a + b for a, b in zip(bl, br)])


def _obj_pal(m):
    raw = m.read_bytes(C, CG_OBJ_PAL * 2, 32)
    return [_cg(raw, i) for i in range(16)]


def _splash_pal_ix(m):
    """Which palette entries the SPLASH draws in — decoded from its own tiles.

    Not typed here and not taken from the generator: the splash's six frames
    are read out of VRAM and the indices they use ARE the answer, so moving a
    colour moves this with it.
    """
    ix = set()
    for f in range(SPLASH_FRAMES):
        for line in _obj_cell(m, SPLASH_TILE0 + f * SPLASH_STEP):
            ix |= {i for i in line if i}
    return {OBJ_IX0 + i for i in ix}


def _under_the_melt(m):
    """Drive right until he is under, and return the machine there.

    ES_SMT_KN_SINK is read as a COORDINATE — where in the state cycle we are —
    the way `_kn_x` reads his position and `_fit` reads the phase. Every
    assertion below is on the rendered frame.
    """
    for _ in range(240):
        if m.read_u16(W, DP_KN_SINK):
            return True
        m.advance(1, pad1={"right": True})
    return False


def _knight(im, pal, skip=()):
    """The bounding box of the knight's OWN pixels, in screen coordinates.

    Returns (x0, x1, y0, y1), or None if he is not in the picture at all —
    which is a real state, not a failure: a jump carries him off the top edge,
    and the melt takes him under.

    `skip` IS LOAD-BEARING AND IS THE SPLASH. He and it are both OBJ out of one
    16-colour group — the splash runs from the entry he vacates — so "is he in
    the picture" cannot be "is there an OBJ pixel" once the splash exists. Pass
    `_splash_pal_ix(m)` and the three cases that ask whether he is GONE get an
    answer about him.

    It went unnoticed for a while, because `_cg` expanded 5-bit channels
    wrongly and the splash's pixels were resolving to the melt's colours by
    nearest match — the right answer for the wrong reason. Fixing `_cg` made
    them resolve to OBJ, exactly, and three cases went red at once.
    """
    xs, ys = [], []
    for y in range(PICTURE_TOP, im.size[1]):
        for x in range(im.size[0]):
            ix = _classify(im.getpixel((x, y))[:3], pal)
            if ix >= OBJ_IX0 and ix not in skip:
                xs.append(x)
                ys.append(y - PICTURE_TOP)
    return (min(xs), max(xs), min(ys), max(ys)) if xs else None


def _feet(im, pal):
    """The picture row his lowest drawn pixel sits ABOVE — where the metal
    starts if he is standing on it."""
    b = _knight(im, pal)
    return None if b is None else b[3] + 1


def _cols_of(world_x, cam):
    """The SCREEN columns a 32-pixel box at world `world_x` covers.

    His X is a world coordinate and `plate_y` reads screen columns, so the
    camera is subtracted exactly here — the same place `smt_kn_draw` does it,
    and for the same reason.
    """
    sx = world_x - cam
    lo, hi = sx // 8, (sx + KN_BOX - 1) // 8
    return range(max(0, lo), min(COLS - 1, hi) + 1)


def _under(im, pal, world_x, cam):
    """The plate top in the columns a knight at world `world_x` occupies, and
    None when he is over a gap, off screen, or straddling two heights."""
    cols = list(_cols_of(world_x, cam))
    if not cols:
        return None
    ys = {plate_y(im, pal, c) for c in cols}
    ys.discard(None)
    return ys.pop() if len(ys) == 1 else None


def _kn_x():
    """His WORLD x and the camera, off the machine at the settled frame every
    case here starts from.

    Coordinates, not measurements: they decide WHICH columns to look in, the
    way the phase decides which row of the oracle to join against. They come as
    a pair because a world x names a screen column only once you know where the
    camera is.
    """
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        return m.read_u16(W, DP_KN_X), m.read_u16(W, DP_CAM_SHOWN)


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
    kn_x, kcam = _kn_x()
    # WORLD columns: his box in world space, which is what the table is
    # indexed by. `_cols_of` is the screen-side twin and is not wanted here.
    words = {row(idx)[c] & VALUE_MASK
             for c in range(kn_x // 8, (kn_x + KN_BOX - 1) // 8 + 1)}
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
    kn_x, kcam = _kn_x()
    pal, shots = _drive(tmp_path, [(7, None)] * 6)
    seen = []
    for im, _, _ in shots:
        under = _under(im, pal, kn_x, kcam)
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
    descent and landing and requires all four: he starts on the metal, he
    genuinely leaves the PICTURE through the top, he comes back down onto a
    plate at the ride equality, and the plate is still moving under him.

    THE DRIVE SPANS A WHOLE PLATE CYCLE, and that is not padding. His spawn
    slot travels 56 px, and a jump's apex only clears the top of the screen
    when the plate is near its HIGH point — from the bottom of its travel the
    same jump stays comfortably on screen. Jumping once and asserting he
    leaves the picture would be asserting the phase he happened to jump at.
    So he jumps whenever he is grounded, across enough frames to cover the
    slot's period, and the claim is that it happens AT ALL.

    Leaving the picture is also the case that would have caught the vertical
    unit: at 8.8 a Y above the screen and a Y below the world are the same bit
    pattern, and the first build read row 236 as negative and wrapped him back
    to the top instead of respawning him.
    """
    frames = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        for i in range(16):
            # Jump on every grounded frame — a closed loop on the ROM's own
            # state, so the arcs start where the ROM is ready rather than on a
            # cadence this test invented.
            for _ in range(9):
                grounded = m.read_u16(W, DP_KN_PLATE) != KN_AIRBORNE
                m.advance(1, pad1={"a": True} if grounded else None)
            # BOTH READS BEFORE THE CAPTURE. `take_screenshot` spends an
            # emulated frame, so a read after it is a frame later than the
            # picture — the harness says so in as many words, and this rail
            # spent a long measurement session learning what that costs.
            cam = m.read_u16(W, DP_CAM_SHOWN)
            kn_x = m.read_u16(W, DP_KN_X)
            f = tmp_path / f"j{i}.png"
            m.screenshot(str(f))
            im = Image.open(f).convert("RGB")
            box = _knight(im, pal)
            frames.append((None if box is None else box[3] + 1,
                           _under(im, pal, kn_x, cam),
                           None if box is None else box[2]))

    # HE RISES A WHOLE APEX ABOVE THE METAL, and that is the claim — not that
    # he leaves the picture, which this case asserted twice and which the
    # geometry invalidated twice. An apex is v^2/2g and both numbers are tuned
    # against the SLOT PITCH, so how close the top of the arc comes to the top
    # of the SCREEN is an accident of where the spawn plate happens to be
    # sitting. Twice now a tuning pass has moved it: the first version wanted
    # him to vanish entirely, the second wanted his art clipped by row 0, and
    # both were asserting an old amplitude rather than the jump.
    #
    # The negative-Y half of the 9.7 unit is NOT lost with it. That defect bit
    # at the OTHER end — row 232, on the way out of the world — and
    # test_walking_off_the_span_drops_him_and_the_world_gives_him_back is where
    # it is covered, which is also the case the plant names.
    rise = [under - feet for feet, under, _t in frames
            if feet is not None and under is not None]
    assert rise and max(rise) >= 24, \
        f"he never rises a full apex above the metal — the jump is not a " \
        f"jump: {frames}"
    landed = [i for i, (feet, under, _t) in enumerate(frames)
              if feet is not None and under is not None and feet == under]
    # ...and then he is LEFT ALONE, so the descent finishes and the metal
    # catches him. Captured while jumping he is airborne at almost every
    # instant, which says nothing about the landing — the half an apex-only
    # case gets wrong.
    settle = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal2 = _palette(m)
        for _ in range(6):
            grounded = m.read_u16(W, DP_KN_PLATE) != KN_AIRBORNE
            m.advance(1, pad1={"a": True} if grounded else None)
        m.advance(80)                   # ...no input at all: land, then ride
        for i in range(5):
            m.advance(6)
            cam = m.read_u16(W, DP_CAM_SHOWN)
            kn_x = m.read_u16(W, DP_KN_X)
            f = tmp_path / f"s{i}.png"
            m.screenshot(str(f))
            im = Image.open(f).convert("RGB")
            settle.append((_feet(im, pal2), _under(im, pal2, kn_x, cam)))
    landed = [i for i, (feet, under) in enumerate(settle)
              if feet is not None and under is not None and feet == under]
    assert len(landed) == len(settle), \
        f"after the arc he is not riding the metal at every capture: {settle}"
    airborne = [i for i, (feet, under, _t) in enumerate(frames)
                if feet is None or (under is not None and feet < under - 8)]
    assert airborne, "he never leaves the metal at all"
    tops = {u for _f, u in settle if u is not None}
    assert len(tops) >= 3, \
        f"the plate stopped moving after the landing — the ride did not " \
        f"resume: {tops}"


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
            out.append((Image.open(f).convert("RGB"), m.read_u16(W, DP_KN_X),
                        m.read_u16(W, DP_CAM_SHOWN)))
    return pal, out


def test_walking_off_the_span_drops_him_and_the_world_gives_him_back(tmp_path):
    """The other state cycle, on the horizontal axis, and every step of it is
    read off the picture.

    He starts ON the metal; he is carried past his plate's four columns; he
    falls, which is asserted as his feet being further below the nearest metal
    than he is tall rather than as "his state variable says airborne"; he
    goes UNDER — out of the picture entirely, because the melt now takes him at
    its own surface rather than letting him fall to a fixed row near the bottom
    — and he comes back standing on a plate at the ride equality, near where he
    started.

    The return is the half that needs the vertical sign to mean what it says.
    In the 8.8 unit the first build used, a fall and a jump's apex are the same
    bit pattern once the row passes 128: the kill test read a fall as negative,
    skipped the respawn, and wrapped him round to the top of the screen.

    THREE OF THESE USED TO BE TRUE FOR THE WRONG REASON, and shortening the
    fall is what exposed it. All three leaned on him DRIFTING RIGHT through a
    long descent to a fixed row near the bottom of the picture:

      "he walked past the metal"      was x > start + span, and x only got
                                      there in the air. The plate logic has
                                      always used his CENTRE, so his centre
                                      clearing the span is the event — and it
                                      happens while x is still inside it.
      "he is falling"                 compared his feet to the metal UNDER HIM,
                                      which over a gap is nothing at all — it
                                      only ever fired once he had drifted as
                                      far as the NEXT plate — and it wanted a
                                      full body-height of drop, which no longer
                                      EXISTS: the metal is at row ~68 and the
                                      melt takes him at ~101. Unsupported and
                                      descending below the metal he left is the
                                      claim, and it survives any fall length.
      "he reached the bottom"         was two thirds of the picture, a depth he
                                      no longer reaches because the melt's
                                      surface is well above it.

    Each is now the statement the rail actually makes, and none of them depends
    on how far he falls.
    """
    # TWO CADENCES, and the reason is the three-second hold. Walking off and
    # going under takes about 35 frames; the hold and the wipe take another
    # 210. One spacing cannot see both — coarse enough to reach the return
    # steps over the fall entirely. So: every other frame until he is gone,
    # then every tenth until he is riding again.
    span = _art("SMT_PLAT_WIDTH") * 8
    seen, last_u, start = [], None, None
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        skip = _splash_pal_ix(m)
        every, gone = 2, False
        for k in range(60):
            kn_x = m.read_u16(W, DP_KN_X)
            cam = m.read_u16(W, DP_CAM_SHOWN)
            p = tmp_path / f"cyc{k}.png"
            m.screenshot(str(p))
            im = Image.open(p).convert("RGB")
            if start is None:
                start = kn_x
            box = _knight(im, pal, skip)
            u = _under(im, pal, kn_x, cam)
            if u is not None:
                last_u = u
            seen.append((kn_x, None if box is None else box[3] + 1, u, last_u))
            if box is None and not gone:
                gone, every = True, 10
            m.advance(every - 1, pad1={"right": True})

    riding = [i for i, (_x, f, u, _l) in enumerate(seen)
              if u is not None and f == u]
    walked = [i for i, (x, _f, _u, _l) in enumerate(seen)
              if x + KN_BOX // 2 > start + span]
    falling = [i for i, (_x, f, u, lu) in enumerate(seen)
               if f is not None and u is None and lu is not None and f > lu]
    gone = [i for i, (_x, f, _u, _l) in enumerate(seen) if f is None]

    assert riding and riding[0] == 0, f"he did not start on the metal: {seen}"
    assert walked, f"his centre never cleared his plate's {span} px of metal"
    # >= rather than >: the captures are six frames apart, so leaving the metal
    # and being visibly below it can land in the same one. The ORDER is the
    # claim; the cadence is not.
    # ONLY FIRSTS ARE USED FROM HERE DOWN. While the mosaic runs, the picture
    # is smeared enough that lava pixels nearest-match the OBJ palette and
    # `_knight` reports a box 248 px wide; those captures are noise in every
    # list. The ORDER of the first real occurrence of each state is the claim,
    # and the states are separated by the wipe rather than interleaved with it.
    assert falling and falling[0] >= walked[0], \
        "he walked off the metal and kept standing on air"
    assert gone and gone[0] >= falling[0], \
        "he fell and never left the picture — the melt did not take him"
    back = [i for i in riding if i > gone[0]]
    assert back, "he went under and never came back onto a plate"
    assert seen[back[0]][0] <= start + span, \
        f"he came back at x={seen[back[0]][0]}, not on the spawn plate"


def test_he_sinks_into_the_lava_and_leaves_only_once_he_is_under(tmp_path):
    """WHAT THE LAVA IS, asserted — and it used to be nothing.

    He fell to a fixed screen row near the bottom of the picture and only then
    died, so a player watched a knight drop THROUGH molten metal and off the
    edge of the world. Every other surface in this rail is a word in the offset
    table read back by the collision; the lava was a picture the physics did
    not know about. It is `smt_melt_top` now — the crust line in his own centre
    column, out of the same word the PPU displaced that column by, with the
    plate-column fallback in it.

    TWO HALVES, AND THE FIRST ONE IS WHY THIS CASE WAS REWRITTEN. Killing him
    on CONTACT was the first attempt and it was wrong for the picture: the
    death was one frame long, and the melt's own bubbling — the thing a player
    is meant to watch — never had time to be seen. So:

      HE GOES IN.   There are frames where his lowest drawn pixel is BELOW the
                    surface. He is descending into it, with the lava drawn
                    behind him.
      HE LEAVES ONLY WHEN UNDER.  There is NO frame where his highest drawn
                    pixel is below the surface. That is what "fully submerged"
                    means, and SMT_KN_TOP — the art's own first drawn row,
                    measured per build — is what makes it a statement about him
                    rather than about his 32 px cell.

    His pixels come off the rendered frame; the surface comes off the ROM's
    row, re-derived every capture, because the surface MOVES: a jet at its peak
    takes him earlier than the level of the lake would.
    """
    base = where(CRUST_PX, _art("SMT_VOFS_BG2"))
    kn_top = _art("SMT_KN_TOP")
    seen, gone_at = [], None
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        skip = _splash_pal_ix(m)
        for k in range(30):
            kn_x = m.read_u16(W, DP_KN_X)
            phase = m.read_u16(W, DP_PHASE)
            cam = m.read_u16(W, DP_CAM_SHOWN)
            p = tmp_path / f"sink{k}.png"
            m.screenshot(str(p))
            im = Image.open(p).convert("RGB")
            box = _knight(im, pal, skip)
            if box is None:
                gone_at = k
                break
            _b, _lag, idx = _fit(im, pal, phase, cam)[0]
            wcol = (kn_x + KN_BOX // 2) >> 3
            w = row(idx)[wcol]
            surface = (where(CRUST_PX, w & VALUE_MASK) if w & BIT_BG2 else base)
            seen.append((k, box[2], box[3], surface))
            m.advance(1, pad1={"right": True})

    assert gone_at is not None, "he never went under"
    entered = [k for k, _t, b, surf in seen if b > surf]
    assert entered, (
        "he never had a pixel below the melt's surface — he is stopping ON the "
        "lava rather than going into it, and the hold has nothing to show")
    for k, top, _b, surf in seen:
        assert top <= surf, (
            f"capture {k}: his highest drawn pixel is at row {top}, below the "
            f"lava's surface at {surf} — he is fully submerged and still being "
            f"drawn")
    # ...and the frame he left was the one that would have broken the rule
    assert seen[-1][1] + (seen[-1][2] - seen[-1][1]) >= seen[-1][3] - kn_top, \
        "he vanished long before he was submerged"


def test_the_melt_holds_him_under_before_it_wipes(tmp_path):
    """THE THREE SECONDS, READ OFF THE PICTURE and not off the counter.

    He goes under and the foundry carries on: the plates keep their harmonics,
    the wall keeps flowing, and the lava keeps boiling over the place he went
    in. That hold is the reason the melt's CHR animation is worth having — the
    first version armed the wipe on contact and the whole death was one frame,
    with nothing to look at.

    Both edges are picture events. He is gone when no OBJ pixel is in the
    frame; the wipe has started when no row of the blob explains the frame at
    any lag, because the mosaic smears the crust lines the table put there. The
    gap between them is the hold, in emulated frames.

    The expected length is DERIVED, never typed: `SMT_SINK_HOLD` is spent in
    US_TSC units at `SMT_PHASE_BASE` per frame, both read out of the rail's own
    .inc. That is what makes this a test of the hold rather than a test of a
    number somebody wrote in two places.

    AND A HOLD IS NOT A PAUSE, which is the half worth asserting explicitly
    because it is the half a reasonable implementation gets wrong. Only the
    KNIGHT stops. Across the hold the melt's CHR must take more than one value
    in VRAM — the bubbles are rising, which is the whole reason to hold at all
    — and the row of the blob that explains the picture must change, because
    the plates are still on their harmonics. A hold that froze the foundry
    would satisfy the length assertion above and show a still frame for three
    seconds.
    """
    every = 6
    expected = _rail("SMT_SINK_HOLD") * 256 / _rail("SMT_PHASE_BASE")
    gone_at, wipe_at, caps = None, None, []
    chr_seen, rows_seen = [], []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        skip = _splash_pal_ix(m)
        for k in range(48):
            phase = m.read_u16(W, DP_PHASE)
            cam = m.read_u16(W, DP_CAM_SHOWN)
            melt = _vram_chr(m)
            p = tmp_path / f"hold{k}.png"
            m.screenshot(str(p))
            im = Image.open(p).convert("RGB")
            here = _knight(im, pal, skip)
            bad, _lag, idx = _fit(im, pal, phase, cam)[0]
            caps.append((k, here is not None, bad))
            if gone_at is not None:
                chr_seen.append(melt)
                rows_seen.append(idx)
            if gone_at is None and here is None:
                gone_at = k
            elif gone_at is not None and bad >= 6:
                wipe_at = k
                break
            m.advance(every - 1, pad1={"right": True})

    assert gone_at is not None, f"he never left the picture: {caps}"
    assert wipe_at is not None, f"the wipe never started: {caps}"
    held = (wipe_at - gone_at) * every
    assert abs(held - expected) <= 2 * every, (
        f"the melt held him for about {held} frames and the rail's own "
        f"constants say {expected:.0f} — the hold is not being spent in the "
        f"unit it is written in")

    # ...and the foundry ran the whole time
    assert len({bytes(c) for c in chr_seen}) > 1, (
        "the melt's CHR never changed across the hold — the bubbles are not "
        "animating, so three seconds of holding shows a still frame")
    assert len(set(rows_seen)) > 1, (
        "one row of the blob explains every frame of the hold — the plates "
        "stopped, so the hold froze the world instead of only the knight")


def test_the_splash_on_screen_is_the_frame_the_rom_holds(tmp_path):
    """THE WHOLE CHAIN, JOINED — OAM to VRAM to CGRAM to pixels.

    The melt answers him going in with a splash, and it costs no claim: it runs
    out of the knight's OWN OAM entry, taken the frame he vacates it, with the
    size bit cleared so the same entry that drew a 32x32 knight draws a 16x16
    burst. Which means "is the splash right" is a question about four things
    agreeing, and this reads all four off the machine:

      the OAM entry     says where it is, which tile it starts at, and that
                        the size bit is CLEAR
      VRAM              holds that tile and its three neighbours, decoded to
                        palette indices here rather than trusted
      CGRAM             says what colour each index is
      the SCREENSHOT    must show exactly that, pixel for pixel

    Both directions, which is what makes it a join and not a sighting: every
    pixel the tile says is a splash index must BE that index's colour on
    screen, and every pixel it says is transparent must NOT be a splash colour.
    A frame that drew the wrong tile, at the wrong place, from a stale palette,
    or at 32x32, fails on one of the two.

    THE COMPARISON IS EXACT, and it can only be exact because `_cg` expands a
    5-bit channel the way the hardware does. It did not: with `v * 255 // 31`
    every index-17 pixel came out one short of the truth, and a splash that was
    rendering perfectly measured as barely rendering at all. Nearest-match
    classification never noticed, because one unit is far inside every margin
    in this module. See `_cg`.
    """
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        assert _under_the_melt(m), "he never went into the melt"
        # ---- and put him over a JET, not over a plate column ---------------
        # Where he actually drowns, his centre is a plate column — and a plate
        # column's melt is at the base by design (docs/100 §12.1), so the
        # surface there is a CONSTANT and this case would be asserting an
        # equality with no content. It passed a planted defect that pinned the
        # splash to the base for exactly that reason.
        #
        # His X is written, and nothing else: `smt_kn_splash` reads it fresh
        # every frame, so this moves the splash into a gap column whose melt is
        # a jet and therefore moving. The assertion below still reads the OAM
        # entry off the machine against the ROM's own word.
        gap = next(c for c in range(COLS) if plate_of(c) is None and c > COLS // 2)
        m.write_bytes(W, DP_KN_X, (gap * 8 + 4 - KN_BOX // 2).to_bytes(2, "little"))
        m.advance(SPLASH_STEP << SPLASH_SHIFT)      # ...past the first frame
        pal = _obj_pal(m)
        cgpal = _palette(m)
        oam = m.read_bytes(OAM, 0, 4)
        hi = m.read_bytes(OAM, 512, 1)[0]
        cell = _obj_cell(m, oam[2])
        kn_x = m.read_u16(W, DP_KN_X)
        phase = m.read_u16(W, DP_PHASE)
        cam = m.read_u16(W, DP_CAM_SHOWN)
        p = tmp_path / "splash.png"
        m.screenshot(str(p))
    im = Image.open(p).convert("RGB")

    # ---- WHERE IT IS: on the melt's surface in his own column --------------
    # Without this the case is blind to a splash pinned at a fixed height: the
    # cell would still agree with the picture at its own coordinates, wherever
    # those were. The melt is a moving thing read out of the offset table, so
    # the same join the plates get applies here — the row the ROM's word puts
    # the crust on, against the row the OAM entry actually staged.
    _bad, _lag, idx = _fit(im, cgpal, phase, cam)[0]
    w = row(idx)[(kn_x + KN_BOX // 2) >> 3]
    surface = (where(CRUST_PX, w & VALUE_MASK) if w & BIT_BG2
               else where(CRUST_PX, _art("SMT_VOFS_BG2")))
    assert surface != where(CRUST_PX, _art("SMT_VOFS_BG2")), (
        f"the sampled column's melt is at its base, so this equality has no "
        f"content — pick a column whose jet is off its rest")
    assert oam[1] + _art("SMT_SPLASH_BASE_Y") == surface, (
        f"the splash's surface row is {oam[1] + _art('SMT_SPLASH_BASE_Y')} and "
        f"the melt's crust in his column is at {surface} — it is not coming "
        f"out of the lava, it is floating over it")

    assert hi & 0b10 == 0, \
        "the size bit is set — the splash is being drawn 32x32, as the knight"
    lo = SPLASH_TILE0
    hi_tile = SPLASH_TILE0 + (SPLASH_FRAMES - 1) * SPLASH_STEP
    assert lo <= oam[2] <= hi_tile and (oam[2] - lo) % SPLASH_STEP == 0, (
        f"tile {oam[2]} is not one of the splash's frames "
        f"({lo}..{hi_tile} step {SPLASH_STEP})")

    drawn = {i for row in cell for i in row if i}
    assert drawn, f"the tile the OAM entry names is empty: tile {oam[2]}"
    splash_cols = {pal[i] for i in drawn}
    checked = 0
    for cy in range(SPLASH_BOX):
        for cx in range(SPLASH_BOX):
            x, y = oam[0] + cx, oam[1] + PICTURE_TOP + cy
            if not (0 <= x < im.size[0] and 0 <= y < im.size[1]):
                continue
            px = im.getpixel((x, y))[:3]
            ix = cell[cy][cx]
            if ix:
                assert px == pal[ix], (
                    f"cell ({cx},{cy}) holds index {ix} = {pal[ix]} and the "
                    f"screen shows {px}")
                checked += 1
            else:
                assert px not in splash_cols, (
                    f"cell ({cx},{cy}) is transparent and the screen shows "
                    f"{px}, a colour only the splash draws")
    assert checked >= 5, f"only {checked} splash pixels — the frame is empty"


def test_the_splash_burns_out_and_the_melt_keeps_holding(tmp_path):
    """THE BURST IS SHORTER THAN THE HOLD, and both lengths are read.

    A splash that ran the whole three seconds would be a light left on; one
    that outlived the hold would still be in the air when the wipe took the
    screen. So: it is there when he goes under, it is gone well before the
    mosaic starts, and the gap between them is the melt holding him with
    nothing thrown.

    The length is DERIVED — `SMT_SPLASH_LIFE` is spent in the same scaled phase
    step as the hold, so the expected number of emulated frames comes out of
    the rail's own two .inc files and not out of a number typed here.

    Splash pixels are found by EXACT colour, from CGRAM. They cannot be found
    by nearest match: the ramp is lava, so it resolves to the melt's own tones,
    and the brightest resolves to the plates'. That is a deliberate consequence
    of the splash being made of the stuff it lands in (docs/100), and it is why
    this reads CGRAM instead of `_classify`.
    """
    every = 4
    expect = SPLASH_LIFE * 256 / _rail("SMT_PHASE_BASE")
    seen = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        assert _under_the_melt(m), "he never went into the melt"
        pal = _obj_pal(m)
        want = {pal[i] for i in range(16)} - {pal[0]}
        for k in range(28):
            p = tmp_path / f"burn{k}.png"
            m.screenshot(str(p))
            im = Image.open(p).convert("RGB")
            n = sum(1 for y in range(PICTURE_TOP, im.size[1])
                    for x in range(im.size[0])
                    if im.getpixel((x, y))[:3] in want)
            seen.append(n)
            m.advance(every - 1, pad1={"right": True})

    lit = [i for i, n in enumerate(seen) if n]
    assert lit and lit[0] <= 1, \
        f"nothing was thrown when he went under: {seen}"
    burned = (lit[-1] + 1) * every
    assert abs(burned - expect) <= 3 * every, (
        f"the splash lasted about {burned} frames and the rail's own constants "
        f"say {expect:.0f}")
    assert seen[-1] == 0, \
        f"the splash is still burning at the end of the run: {seen}"
    assert max(seen) >= 15, \
        f"the burst never grew past {max(seen)} pixels — it is a dot, not a splash"


def test_the_fall_dissolves_the_picture_before_it_gives_him_back(tmp_path):
    """THE DEATH IS AN EVENT, not a cut — asserted on the picture and nowhere
    else.

    The respawn used to happen in the frame he crossed the kill row: he
    blinked from the bottom of the world to the spawn with nothing in between,
    and every frame of it was a legal running frame. It is now the mosaic's
    swap callback, fired at peak black, so the fall, the dissolve, the move and
    the return are one legible thing.

    The assertion is that the picture STOPS BEING EXPLICABLE and then starts
    again. While the mosaic runs, the PPU is replicating one pixel across each
    block, so the crust lines the offset table put in place are smeared away
    and no row of the blob explains the frame at any lag; when the wipe lets
    go, a row explains it exactly again. A cut has no such run — every one of
    its frames is explained — which is precisely the difference this measures.

    Measured on the shipped binary: a contiguous run of captures at 6-15
    unexplained columns, bracketed on both sides by exact fits.
    """
    caps = []
    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        m.advance(1, pad1=JOY_START)
        m.advance(SETTLE)
        pal = _palette(m)
        # FOUR FRAMES A CAPTURE, NINETY OF THEM. The wipe used to start on the
        # frame he touched the lava; the melt holds him under for three seconds
        # first now, so the run has to reach ~250 frames to see it at all and
        # the cadence pays for that. The wipe itself is ~34 frames, so it is
        # still 8 captures wide at this spacing.
        for k in range(90):
            phase = m.read_u16(W, DP_PHASE)
            cam = m.read_u16(W, DP_CAM_SHOWN)
            p = tmp_path / f"die{k}.png"
            m.screenshot(str(p))
            im = Image.open(p).convert("RGB")
            caps.append(_fit(im, pal, phase, cam)[0][0])
            m.advance(3, pad1={"right": True})

    # the longest run of captures no row of the blob explains
    best = run = 0
    for bad in caps:
        run = run + 1 if bad >= 6 else 0
        best = max(best, run)
    assert best >= 5, (
        f"the picture stayed explicable throughout — the fall is a cut, not a "
        f"dissolve. Per-capture unexplained columns: {caps}")
    assert caps[0] == 0 and caps[-1] == 0, (
        f"the run does not open and close on a frame the table explains: "
        f"{caps}")


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
    kn_x, kcam = _kn_x()
    for c in _cols_of(kn_x, kcam):
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
        cam = m.read_u16(W, DP_CAM_SHOWN)
        # BG3 map row 0 is the H row and row 1 the V row: BG3VOFS is 0, and
        # the vertical row is the horizontal one plus 0x20 WORDS.
        h = m.read_bytes(V, VRAM_TABLE * 2, COLS * 2)
        v = m.read_bytes(V, (VRAM_TABLE + COLS) * 2, COLS * 2)
    assert h == bytes(COLS * 2), "the H row is not all zero — a V-only " \
        "table is expressed by a row with neither enable bit set"
    # ...and the V row is 32 words of a WORLD row, taken at the read head.
    head = (cam >> 3) + 1
    hits = [i for i in ((phase - lag) % PHASES for lag in range(4))
            if v == BLOB[i * ROW_BYTES + head * 2:
                         i * ROW_BYTES + (head + COLS) * 2]]
    assert hits, \
        f"BG3's V row is not any row the blob holds near phase {phase} at " \
        f"the camera's read head (world column {head})"


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
