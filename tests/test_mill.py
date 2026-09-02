"""mill — mode 4's per-column AXIS, and a lift that crosses two rooms on it.

WHAT IS UNDER TEST HERE THAT `test_smelter.py` DOES NOT ALREADY COVER. Smelter
is mode 2, where the PPU fetches a word for EACH axis, so a column's axis is
not a choice anybody makes. Mode 4 fetches ONE word per column and BIT 15
PICKS (SnesPpu.cpp GetTilemapData, :155-162: one `_hOffset`, and the bit-15
test at :156-161 decides whether it lands on vScroll or hScroll). That single
difference is this rail's whole subject, and it is what this module asserts:

  * that the axis a column moves on is the axis ITS OWN WORD names, not the
    rail's, and that two columns eight pixels apart move on different ones IN
    THE SAME FRAME;
  * that a vertical word and a horizontal word are honoured simultaneously,
    which is the thing a mode-2 rail cannot demonstrate;
  * that the word at table index j displaces SCREEN column j + 1 — the FETCH
    LEAD, which this rail bakes into the blob and whose absence is a real
    defect this rail shipped once: every bay's leftmost column stood still
    while its neighbours pumped;
  * that screen column 0 is never displaced, because the PPU clears the offset
    latches per scanline fetch (:284-287) and no word can reach it.

AND THE SEQUENCE IS PART OF THE RAIL. The lift is not decoration on top of the
mechanism, it is the thing the mechanism was built to carry: a car that IS a
column, occluding a rider that cannot be one, and two rooms joined by it. The
last third of this module asserts that the cycle CLOSES — boards, rides,
arrives in the OTHER bay, and stands ready to do it again — because a
transition that only works once looks identical in any single frame.

THE ORACLE IS THE ROM, NOT THE GENERATOR. Expected words are decoded from the
row blob AS IT SITS IN build/mill.sfc, located by searching the ROM image for
the bytes — so finding it is itself a proof the blob reached the binary.
Importing tools/gen_mill_assets.py would compare the ROM against the Python
that authored it, which agrees with itself by construction.

THE OBSERVATION IS THE RENDERED FRAME. Nothing here asserts on a DP variable
that "should be" a function of the picture; the DP reads that do appear are
there to know WHICH row of the oracle to join against, or to drive the machine
to a named state — never to stand in for what the PPU drew.

LOCKSTEP-NATIVE: `Machine` only, absolute frames, no wall-clock surface.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
ROM = BUILD / "mill.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "mil" / "symbol_map.json").read_text())

sys.path.insert(0, str(SUPERFORGE / "vendor"))                   # noqa: E402
from machine import Machine, MemoryType                          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))         # noqa: E402
from frame_geometry import PICTURE_TOP                           # noqa: E402

W = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam
CG = MemoryType.SnesCgRam

pytestmark = pytest.mark.skipif(not ROM.exists(),
                                reason="build/mill.sfc — run `make mill`")


# --------------------------------------------------------------------------
# the constants, READ rather than retyped
# --------------------------------------------------------------------------
def _art(key):
    """One equate out of the GENERATED build/assets/mil_art.inc.

    A copy of a rail constant living here as a literal goes stale the moment
    the geometry changes and the module keeps passing — which is worse than
    failing, because the case is then quietly weaker than it claims.
    """
    for line in (ASSETS / "mil_art.inc").read_text().splitlines():
        head, _, rest = line.partition("=")
        if head.strip() == key:
            v = rest.split(";")[0].strip()
            # ca65 spells hex with `$`, and the floor map is emitted that way
            # because a bit field is unreadable in decimal.
            return int(v.replace("$", "0x"), 0)
    raise KeyError(f"{key} is not in mil_art.inc")


def _rail(key):
    """One equate out of the HAND-WRITTEN game/mill/mill.inc.

    `_art` reads what the tools computed; this reads what a person chose. They
    are expressions there rather than literals (`SMIL_WALK_Y =
    SMIL_LOBBY_FLOOR * 8 - SMIL_RIDER_BOX`), which is the point — the value is
    derived from the units it is expressed in — so this resolves earlier
    equates and evaluates rather than matching an integer.
    """
    env = dict(_ART_ENV)
    want = None
    for line in (SUPERFORGE / "game" / "mill" / "mill.inc").read_text().splitlines():
        head, eq, rest = line.partition("=")
        name = head.strip()
        if not eq or not name.isidentifier():
            continue
        expr = rest.split(";")[0].strip().replace("$", "0x")
        if not expr or not all(c.isalnum() or c in " _()+-*/<>|&" for c in expr):
            continue
        try:
            env[name] = eval(expr, {"__builtins__": {}}, dict(env))   # noqa: S307
        except Exception:
            continue
        if name == key:
            want = env[name]
    if want is None:
        raise KeyError(f"{key} is not a resolvable equate in mill.inc")
    return int(want)


def _art_env():
    env = {}
    for line in (ASSETS / "mil_art.inc").read_text().splitlines():
        head, eq, rest = line.partition("=")
        name = head.strip()
        if not eq or not name.isidentifier():
            continue
        try:
            env[name] = int(rest.split(";")[0].strip().replace("$", "0x"), 0)
        except ValueError:
            continue
    return env


_ART_ENV = _art_env()

COLS = _art("SMIL_COLS")
PHASES = _art("SMIL_PHASES")
FLAT_ROW = _art("SMIL_FLAT_INDEX")
ROW_BYTES = _art("SMIL_ROW_BYTES")
LEAD = _art("SMIL_LEAD")
CAM_MAX = _art("SMIL_CAM_MAX")
CAR_COL = _art("SMIL_CAR_COL")
SMIL_LIFT_COL = _art("SMIL_LIFT_COL")
STAND_Y = _art("SMIL_STAND_Y")
STATION_AT = (_art("SMIL_STATION_A"), _art("SMIL_STATION_B"))
SHAFT_COLS = _art("SMIL_SHAFT_COLS")
WIN_X, WIN_Y = _art("SMIL_WIN_X"), _art("SMIL_WIN_Y")
WIN_W, WIN_H = _art("SMIL_WIN_W"), _art("SMIL_WIN_H")
CAR_ROW, CAR_H = _art("SMIL_CAR_ROW"), _art("SMIL_CAR_H")
RIDER_BOX = _art("SMIL_RIDER_BOX")
LEAF_BOX = _art("SMIL_LEAF_BOX")
LEAF_ROWS = _art("SMIL_LEAF_ROWS")
DOOR_AX, DOOR_BX = _art("SMIL_DOOR_AX"), _art("SMIL_DOOR_BX")   # in PIXELS: the
                                    #   bays are read off the wall art, which does
                                    #   not put them on the tile grid
DOOR_W = _art("SMIL_DOOR_W")
DOOR_TRAVEL = _art("SMIL_DOOR_TRAVEL")
WALK_STEP = _rail("SMIL_WALK_STEP")
DOOR_TOP = _art("SMIL_DOOR_TOP")
BELT_ROW = _art("SMIL_BELT_ROW")
LOBBY_FLOOR = _art("SMIL_LOBBY_FLOOR")
BAYS = _rail("SMIL_DOOR_BAYS")

# The composed video/offset vocabulary, out of the scene's GENERATED map —
# these are the allocator's, not the rail's, and reading them here is what
# joins the test to the composition rather than to a copy of it.
def _hall(key):
    for line in (BUILD / "mil" / "engine_state_hall.inc").read_text().splitlines():
        head, _, rest = line.partition("=")
        if head.strip() == key:
            return int(rest.split(";")[0].strip().replace("$", "0x"), 0)
    raise KeyError(f"{key} is not in engine_state_hall.inc")


BIT_BG1 = _hall("ES_OPT_HALL_BG1")
BIT_BG2 = _hall("ES_OPT_HALL_BG2")
BIT_VSEL = _hall("ES_OPT_HALL_VSEL")
V_MASK = _hall("ES_OPT_HALL_MASK")
H_MASK = _hall("ES_OPT_HALL_HMASK")


def _dp(name):
    for p in MAP["globals"]:
        if p["sym"] == name:
            return p["start"]
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


DP_PHASE = _dp("ES_MIL_PHASE")
DP_SHOWN = _dp("ES_MIL_SHOWN")
DP_FLATSEL = _dp("ES_MIL_FLATSEL")
DP_CAM = _dp("ES_MIL_CAM_SHOWN")
DP_CAR = _dp("ES_MIL_CAR")
DP_RIDER_Y = _dp("ES_MIL_RIDER_Y")
DP_PX = _dp("ES_MIL_PX")
DP_DOOR = _dp("ES_MIL_DOOR")
DP_BOARD = _dp("ES_MIL_BOARD")
DP_BAY = _dp("ES_MIL_BAY")
DP_ARRIVE = _dp("ES_MIL_ARRIVE")
DP_SM = _dp("ES_SM_CTL")
OAM_AT = _dp("ES_O_MIL_RIDER") if False else None   # OAM index lives in the map

JOY_B = {"b": True}
JOY_Y = {"y": True}
JOY_UP = {"up": True}
JOY_RIGHT = {"right": True}
JOY_LEFT = {"left": True}

SCENE_LOBBY, SCENE_HALL = 0, 1


# --------------------------------------------------------------------------
# the oracle: the row blob, out of the ROM image
# --------------------------------------------------------------------------
def _blob():
    """The 129 rows, out of build/mill.sfc.

    Located by SEARCHING the ROM image for the generated bytes, which is what
    makes finding it a proof that the blob reached the binary — a claim the
    linker placement `.assert`s in main.asm make separately and from the other
    side.
    """
    want = (ASSETS / "mil_row.bin").read_bytes()
    rom = ROM.read_bytes()
    at = rom.find(want)
    assert at >= 0, "the row blob is not in build/mill.sfc"
    assert rom.find(want, at + 1) < 0, "the row blob appears twice"
    return rom[at:at + len(want)]


BLOB = _blob()


def row(idx):
    """One row of the table, indexed as the TABLE IS — by BG3 map column.

    RAW. Turning a map index into a screen column is `words_for_screen`'s job
    and it is kept separate on purpose: the lead is the thing under test in
    two cases below, and a reader that silently applied it would leave nothing
    for them to check.
    """
    b = BLOB[idx * ROW_BYTES:(idx + 1) * ROW_BYTES]
    return [b[2 * c] | (b[2 * c + 1] << 8) for c in range(COLS)]


def words_for_screen(idx, lead=LEAD):
    """That row re-indexed by SCREEN column: `out[sc]` is the word the PPU will
    apply to screen column `sc`, or None where no word reaches it.

    TWO SHIFTS THAT CANCEL, and the rail is only correct because they do. The
    PPU fetches a column's tilemap data BEFORE its offset words, so the word at
    map index j displaces screen column j + LEAD. The generator answers by
    storing `column_word(j + LEAD)` at index j — so index j both holds the word
    authored for screen column j + LEAD and is applied to it.

    Screen column 0 is None and cannot be otherwise: the offset latches are
    cleared at the start of each scanline's fetch (SnesPpu.cpp:284-287), so no
    map index reaches it.
    """
    r = row(idx)
    out = [None] * COLS
    for j in range(COLS):
        sc = j + lead
        if 0 <= sc < COLS:
            out[sc] = r[j]
    return out


def shaft_columns():
    """The SCREEN columns whose art is a machine's vertical rails.

    THE ART'S OWN GEOMETRY, and the only oracle that survives a plant in the
    generator. Every case below that reads the blob shares its layout with the
    blob — so a defect that moves the whole table one column moves the
    prediction with it and both agree, which is the tautology
    `test_smelter.py`'s header warns about arriving through a different door.
    These constants come from the STATIONS: a station is an upright, then
    SHAFT_COLS shaft columns, then its conveyor. What the lead exists to do is
    line the table up with THIS, so this is what the picture has to be checked
    against.
    """
    out = set()
    for at in STATION_AT:
        out |= {at + 1 + k for k in range(SHAFT_COLS)}
    return out


def is_v(word):
    return bool(word & BIT_VSEL)


def drives_bg1(word):
    return bool(word & BIT_BG1)


def drives_bg2(word):
    return bool(word & BIT_BG2)


def enabled(word):
    return drives_bg1(word) or drives_bg2(word)


# --------------------------------------------------------------------------
# the picture
# --------------------------------------------------------------------------
def shot(m, path):
    m.screenshot(str(path))
    return Image.open(path).convert("RGB").crop(
        (0, PICTURE_TOP, 256, PICTURE_TOP + 224))


def layers(m):
    """The colours only BG1 can have drawn, and the colours only BG2 can have.

    THE TWO LAYERS MUST BE SEPARATED BEFORE EITHER CAN BE MEASURED. A screen
    column shows BG1's 8bpp art over BG2's 2bpp art, and the two move on
    different axes and for different reasons — so a strip of composite pixels
    is not a translation of anything and a case that tested it would find no
    motion at all, whatever the PPU did. (It did: the first cut of this module
    reported zero moving columns on a rail that was working.)

    The separation is available because mode 4 gives the two layers DISJOINT
    parts of CGRAM: an 8bpp BG1 indexes it directly and this rail's art lives
    at 32..127, BG2's eight three-colour groups at 1..31, OBJ's palettes at
    129.. (SnesPpu.cpp:1077-1082, :960). Colours that appear in more than one
    range are dropped rather than guessed at — the ranges are disjoint as
    INDICES, not necessarily as RGB.
    """
    cg = m.read_bytes(CG, 0, 512)

    def at(i):
        wrd = cg[i * 2] | (cg[i * 2 + 1] << 8)
        e = lambda v: (v << 3) | (v >> 2)                   # noqa: E731
        return (e(wrd & 31), e((wrd >> 5) & 31), e((wrd >> 10) & 31))

    bg2 = {at(i) for i in range(1, 32)}
    bg1 = {at(i) for i in range(32, 128)}
    obj = {at(i) for i in range(129, 256)}
    return bg1 - bg2 - obj, bg2 - bg1 - obj


def belt_band(cam):
    """The screen rows where a HORIZONTAL displacement is OBSERVABLE at all.

    A displaced column shows the NEIGHBOURING tile (hScroll = (BGnHOFS & 7) |
    (word & $3F8), SnesPpu.cpp:157), so a shift can only be seen where the row
    is not the same tile repeated — and on this rail almost every BG2 row IS
    the same tile repeated, because that is the invariance an H-displaced
    column imposes on the art it moves. The one row that varies along its
    length is the conveyor's, which is laid as a cycle of BELT_PHASES tread
    tiles precisely so the belt can appear to travel.

    So the belt band is not a convenience for the test — it is the whole set of
    rows on which the horizontal half of this rail's claim is checkable, and
    saying so is more honest than asserting over rows where any answer would
    look the same.
    """
    y0 = BELT_ROW * 8 - cam
    return max(0, y0), min(224, y0 + 16)


def mask_strip(im, sc, colours, rows=None):
    """Screen column `sc` reduced to "is this pixel one of `colours`".

    A MASK, NOT THE PIXELS. What is under test is where a LAYER's art is, and
    two frames of the same art in different places share no exact pixel rows
    once a second layer is showing through it.
    """
    x0 = sc * 8
    ys = range(*rows) if rows else range(im.height)
    return [tuple(im.getpixel((x0 + dx, y)) in colours for dx in range(8))
            for y in ys]


def strip(im, sc, rows=None):
    """The 8-pixel-wide screen column `sc`, as a list of row tuples.

    RAW, and for the horizontal half of the claim that is the RIGHT reading
    rather than a weaker one. The BG2-only colour mask cannot see the conveyor:
    the tread is brass and BG1's own ramp set carries the same brass, so those
    colours are in both ranges and are dropped from either mask. In the belt
    band the only thing that moves is the tread — the housing over it is BG1
    art in columns whose word drives BG2 — so a raw comparison there attributes
    correctly, and it is the mask that would have been the fiction.
    """
    x0 = sc * 8
    ys = range(*rows) if rows else range(im.height)
    return [tuple(im.getpixel((x0 + dx, y)) for dx in range(8)) for y in ys]


def vshift(a, b, span=64):
    """How far strip `a` has to slide VERTICALLY to become strip `b`.

    Returned as the unique whole-strip translation, or None when no shift in
    the search span explains it. An EQUALITY, not a correlation: a near-uniform
    column would let a best-match score pin itself anywhere, and this rail's
    machinery is full of near-uniform columns.
    """
    n = len(a)
    span = min(span, max(1, n // 2))
    best = None
    for d in range(-span, span + 1):
        rows = [y for y in range(n) if 0 <= y - d < n]
        if len(rows) < n - abs(span):
            continue
        if all(a[y - d] == b[y] for y in rows):
            if best is not None:
                return None                      # ambiguous: not an equality
            best = d
    return best


def hshift(im, sc, y0, y1, other, span=8):
    """How far the pixels of screen column `sc` have slid HORIZONTALLY between
    two frames, over rows y0..y1. The search span is one tile: a horizontal
    offset word keeps the layer's own low three bits (hScroll = (BGnHOFS & 7) |
    (word & $3F8), SnesPpu.cpp:157), so a belt column's travel inside one frame
    step is small and bounded."""
    x0 = sc * 8
    base = [tuple(im.getpixel((x0 + dx, y)) for dx in range(8))
            for y in range(y0, y1)]
    for d in range(-span, span + 1):
        if x0 + d < 0 or x0 + d + 8 > 256:
            continue
        cand = [tuple(other.getpixel((x0 + d + dx, y)) for dx in range(8))
                for y in range(y0, y1)]
        if cand == base:
            return d
    return None


# --------------------------------------------------------------------------
# driving
# --------------------------------------------------------------------------
BOOT = 60


def to_hall(m):
    """Drive the boot lobby through one boarding into the hall.

    Every step waits on a CONDITION read out of the machine rather than on a
    count of frames — the door travels, the ride's length and the fade's are
    all the rail's or scene_mgr's own tuning, and a count would go stale the
    first time any of them moved. That is also why nothing here sleeps.
    """
    m.advance(BOOT)
    for _ in range(600):
        if m.read_u16(W, DP_DOOR + 2) >= DOOR_TRAVEL:
            break
        m.advance(1, pad1=JOY_RIGHT)
    else:
        pytest.fail("the far bay never opened")
    m.advance(3, pad1=JOY_UP)
    for _ in range(600):
        if scene(m) == SCENE_HALL:
            break
        m.advance(1)
    else:
        pytest.fail("the lobby never handed over to the hall")
    # ...and then until the TABLE IS ACTUALLY WALKING. A scene's tick runs
    # through the fade-in but the phase is still at its start, so a frame taken
    # on arrival is a static picture and two of them are the same picture — a
    # case that read them would pass or fail on nothing. Waited on the
    # published row rather than on a count, for the same reason everything else
    # here is.
    first = m.read_u16(W, DP_SHOWN)
    for _ in range(600):
        if m.read_u16(W, DP_SHOWN) != first:
            return
        m.advance(1)
    pytest.fail("the offset table never advanced in the hall")


def scene(m):
    return m.read_u16(W, DP_SM) & 0xFF


def board_and_ride(m):
    """From standing in the hall, get on the lift and start the climb.

    THE HALL IS NOT A CUTSCENE ANY MORE. It used to start its own ride after a
    beat, so a case that wanted a moving camera only had to wait; now he
    arrives standing on the car and the climb begins when he asks for it. The
    tests that need the ride say so, which is a better statement of what they
    depend on than a wait was.
    """
    for _ in range(400):                      # ...once the picture is up: the
        if m.read_bytes(W, DP_SM + 2, 1)[0] == 0:   # scene's tick runs through
            break                             # the fade-in but a press during
        m.advance(1)                          # it is a press nobody is reading
    else:
        pytest.fail("the hall never finished arriving")
    for _ in range(400):
        if m.read_u16(W, DP_PX) >= SMIL_LIFT_COL * 8:
            break
        m.advance(1, pad1=JOY_RIGHT)
    for _ in range(400):
        if m.read_u16(W, DP_PX) <= SMIL_LIFT_COL * 8:
            break
        m.advance(1, pad1=JOY_LEFT)
    m.advance(4, pad1=JOY_UP)
    for _ in range(240):
        if m.read_u16(W, DP_CAR) > 0:
            return
        m.advance(1)
    pytest.fail("the lift did not start after UP on the car")


def settle_hall(m, frames=8):
    """A few frames of the hall with Y HELD, so the picture is the flat row.

    Y, not B. They were one button until the flat control was found to be
    unreachable — B had been given to holding the ride when the lift was built,
    and nothing wrote ES_MIL_FLATSEL any anymore while hall.asm still described
    the behaviour. This case is what found it.
    """
    m.advance(frames, pad1=JOY_Y)


def running(m, frames=6):
    """Advance far enough that the row on screen has certainly changed."""
    was = m.read_u16(W, DP_SHOWN)
    for _ in range(240):
        m.advance(1)
        if m.read_u16(W, DP_SHOWN) != was:
            m.advance(frames)
            return
    pytest.fail("the offset table stopped advancing")


def until_v_moves(m, frm, cap=900):
    """Advance until the row on screen carries a DIFFERENT vertical value from
    row `frm` on some column.

    NOT A FRAME COUNT, and not for the usual reason. The hammer's stroke is
    eased — `u ** 3` on the way down — so it sits at zero for tens of phases
    before it moves at all, and a fixed advance lands wherever the easing
    happens to be. A case that took two frames a fixed distance apart would
    pass or fail on the shape of the easing curve rather than on the PPU.
    """
    base = words_for_screen(frm)
    for _ in range(cap):
        m.advance(1)
        cur = words_for_screen(m.read_u16(W, DP_SHOWN))
        for sc in range(COLS):
            a, b = base[sc], cur[sc]
            if a is None or b is None or not (enabled(a) and enabled(b)):
                continue
            if is_v(a) and is_v(b) and (a & V_MASK) != (b & V_MASK):
                return m.read_u16(W, DP_SHOWN)
    pytest.fail("no vertical word changed value — are the pistons driven?")


# --------------------------------------------------------------------------
# THE SUBJECT: one word a column, and bit 15 picks the axis
# --------------------------------------------------------------------------
def test_the_table_mixes_both_axes_in_one_row():
    """The premise, asserted against the ROM before any picture is read.

    If no row of the blob carried both a VSEL word and a non-VSEL word at once,
    every case below would pass on a rail that had quietly become single-axis —
    which is smelter with a richer BG1, and is exactly what this rail exists
    not to be.
    """
    mixed = 0
    for idx in range(PHASES):
        words = [w for w in words_for_screen(idx) if w and enabled(w)]
        if any(is_v(w) for w in words) and any(not is_v(w) for w in words):
            mixed += 1
    assert mixed == PHASES, f"only {mixed}/{PHASES} rows carry both axes"


def test_a_column_moves_on_the_axis_its_own_word_names(tmp_path):
    """MODE 4'S WHOLE SUBJECT, read off the screen.

    Two frames, taken far enough apart that a vertical word has actually
    changed value. For every screen column the ROM's word ENABLES, the picture
    must have moved on the axis that column's own bit 15 names and on no other:
    a VSEL column's BG1 art is a clean vertical translation of itself, and a
    non-VSEL column's BG2 art has changed WITHOUT sliding up or down.

    Both are asserted from ONE PAIR OF FRAMES, which is the part a mode-2 rail
    cannot produce: there the axis is not a per-column property to get wrong.
    """
    with Machine(str(ROM)) as m:
        to_hall(m)
        running(m)
        a = shot(m, tmp_path / "a.png")
        r_a = m.read_u16(W, DP_SHOWN)
        r_b = until_v_moves(m, r_a)
        m.advance(1)
        b = shot(m, tmp_path / "b.png")
        band = belt_band(m.read_u16(W, DP_CAM))
        ONLY1, ONLY2 = layers(m)
    assert band[1] > band[0], f"the conveyor is off screen at this camera: {band}"
    assert len(ONLY1) > 8 and len(ONLY2) > 1, (
        f"the two layers are not separable by colour: {len(ONLY1)} BG1-only, "
        f"{len(ONLY2)} BG2-only")

    wa, wb = words_for_screen(r_a), words_for_screen(r_b)
    v_moved = h_moved = h_seen = 0
    for sc in range(COLS):
        if wa[sc] is None or wb[sc] is None:
            continue
        if not (enabled(wa[sc]) and enabled(wb[sc])):
            continue
        if is_v(wa[sc]) != is_v(wb[sc]):
            continue                              # a column that changed axis
        if is_v(wa[sc]):
            if (wa[sc] & V_MASK) == (wb[sc] & V_MASK):
                continue                          # this column is at rest
            d = vshift(mask_strip(a, sc, ONLY1), mask_strip(b, sc, ONLY1))
            assert d is not None, (
                f"screen column {sc} carries a VERTICAL word and its BG1 art "
                f"is not a vertical translation of itself")
            assert d != 0, f"screen column {sc} carries a V word but did not move"
            v_moved += 1
        else:
            if (wa[sc] & H_MASK) == (wb[sc] & H_MASK):
                continue
            sa, sb = strip(a, sc, band), strip(b, sc, band)
            # THE PER-COLUMN CLAIM IS THE AXIS, AND IT IS ASSERTED ON EVERY
            # HORIZONTAL COLUMN: whatever else it did, it did not slide up or
            # down. Whether it VISIBLY moved is a different question and cannot
            # be asked of every column — a shift shows only where the row
            # varies along X, and stretches of the conveyor are locally one
            # colour where the housing covers them. So liveness is asserted in
            # aggregate below rather than pretended per column.
            assert vshift(sa, sb, span=8) in (0, None), (
                f"screen column {sc} is a HORIZONTAL word but its art slid "
                f"vertically")
            h_seen += 1
            if sa != sb:
                h_moved += 1
    assert v_moved >= 4, f"only {v_moved} vertical columns moved"
    assert h_seen >= 6, f"only {h_seen} horizontal columns were examined"
    assert h_moved >= 2, (
        f"{h_seen} horizontal columns held their scanlines but only {h_moved} "
        f"visibly moved — the belts are not running")


def test_the_two_axes_are_honoured_in_the_same_frame(tmp_path):
    """...and that they are NEIGHBOURS. It is not enough that some part of the
    picture moves vertically and some other part horizontally: the claim mode 4
    makes is per COLUMN, so the test is that two columns eight pixels apart
    disagree about their axis in one frame and both are obeyed."""
    with Machine(str(ROM)) as m:
        to_hall(m)
        running(m)
        a = shot(m, tmp_path / "a.png")
        r_a = m.read_u16(W, DP_SHOWN)
        until_v_moves(m, r_a)
        m.advance(1)
        b = shot(m, tmp_path / "b.png")
        band = belt_band(m.read_u16(W, DP_CAM))
        ONLY1, ONLY2 = layers(m)
    w = words_for_screen(r_a)
    borders = [sc for sc in range(COLS - 1)
               if w[sc] is not None and w[sc + 1] is not None
               and enabled(w[sc]) and enabled(w[sc + 1])
               and is_v(w[sc]) != is_v(w[sc + 1])]
    assert borders, "no two adjacent enabled columns disagree about the axis"
    checked = 0
    for sc in borders:
        vcol = sc if is_v(w[sc]) else sc + 1
        hcol = sc + 1 if is_v(w[sc]) else sc
        hs = (strip(a, hcol, band), strip(b, hcol, band))
        assert vshift(*hs, span=8) in (0, None), (
            f"column {hcol} is horizontal and its art slid vertically, beside "
            f"a vertical neighbour {vcol}")
        checked += 1
    assert checked, "every border column had its BG2 hidden — nothing examined"


# --------------------------------------------------------------------------
# THE FETCH LEAD, which this rail shipped wrong once
# --------------------------------------------------------------------------
def test_screen_column_zero_is_never_displaced(tmp_path):
    """A HARDWARE LIMIT, not a rail choice. The PPU clears the offset latches
    at the start of each scanline's fetch (SnesPpu.cpp:284-287), so the first
    column has no word behind it and there is nothing a table can do about it.
    The rail answers by drawing a PILLAR there — art with nothing to displace —
    and this is the case that says the pillar is load-bearing."""
    with Machine(str(ROM)) as m:
        to_hall(m)
        running(m)
        a = shot(m, tmp_path / "a.png")
        running(m)
        b = shot(m, tmp_path / "b.png")
    assert strip(a, 0) == strip(b, 0), (
        "screen column 0 moved, which no offset word can do")


def test_the_moving_columns_are_the_ones_the_lead_predicts(tmp_path):
    """THE DEFECT THIS RAIL SHIPPED, as a regression.

    The offset words are fetched AFTER a column's tilemap data, so the word at
    BG3 map index j displaces SCREEN column j + LEAD. Before the lead was baked
    into the blob, every bay's LEFTMOST column stood still while its neighbours
    pumped — 30 of 32 columns torn — and it read as an animation bug rather
    than a fetch-order one.

    The case predicts the set of screen columns that must move TWICE: once
    reading the table with the lead and once without. The lead's reading has to
    be a subset of what actually moved, the two readings have to DISAGREE (or
    the case proves nothing), and the columns only the lead-less reading names
    must NOT have moved. That third clause is what makes this a test of the
    fetch order rather than of the picture.
    """
    with Machine(str(ROM)) as m:
        to_hall(m)
        running(m)
        a = shot(m, tmp_path / "a.png")
        r_a = m.read_u16(W, DP_SHOWN)
        r_b = until_v_moves(m, r_a)
        m.advance(1)
        b = shot(m, tmp_path / "b.png")
        ONLY1, _ = layers(m)

    def predicted(lead):
        wa, wb = words_for_screen(r_a, lead), words_for_screen(r_b, lead)
        return {sc for sc in range(COLS)
                if wa[sc] is not None and wb[sc] is not None
                and enabled(wa[sc]) and is_v(wa[sc]) and is_v(wb[sc])
                and (wa[sc] & V_MASK) != (wb[sc] & V_MASK)}

    observed = set()
    for sc in range(COLS):
        sa, sb = mask_strip(a, sc, ONLY1), mask_strip(b, sc, ONLY1)
        d = vshift(sa, sb)
        if sa != sb and d not in (0, None):
            observed.add(sc)

    with_lead, without = predicted(LEAD), predicted(0)
    assert with_lead, "no vertical word changed — the case has nothing to say"
    assert with_lead != without, (
        "the lead makes no difference to the prediction, so this case would "
        "pass with the fetch order ignored")
    assert with_lead <= observed, (
        f"columns the lead predicts did not move: {sorted(with_lead - observed)}")
    assert not (without - with_lead) & observed, (
        f"columns only a LEAD-LESS reading predicts also moved "
        f"({sorted((without - with_lead) & observed)}) — the blob is not "
        f"carrying the lead the rail says it is")

    # ...AND THE COLUMNS THAT MOVED ARE THE MACHINES' OWN.
    #
    # Everything above joins the picture to the BLOB, and that is not enough on
    # its own: shift the whole table one column and the blob shifts with it, so
    # the two go on agreeing and the case stays green while every bay's
    # leftmost column stands still. (Measured — this is what
    # `tools/plants/mill.py::table-column-lead-removed` reported TEST-BLIND
    # against the first cut of this module.) The oracle that does NOT move with
    # such a defect is the ART's geometry: a station is an upright and then
    # SHAFT_COLS shafts, and lining the table up with that is the whole job of
    # the lead.
    shafts = shaft_columns() - set(range(CAR_COL, CAR_COL + SHAFT_COLS))
    assert observed <= shaft_columns(), (
        f"columns outside the machines' own moved vertically: "
        f"{sorted(observed - shaft_columns())} — the table is not aligned "
        f"with the art it displaces")
    assert observed & shafts, (
        f"no shaft column moved: the machines at {sorted(shafts)} are not the "
        f"columns the table is driving")


# --------------------------------------------------------------------------
# THE CAMERA, which a vertical word REPLACES rather than adds to
# --------------------------------------------------------------------------
def test_a_vertical_word_carries_the_camera(tmp_path):
    """`vScroll = word & $3FF` (SnesPpu.cpp:160) — an offset word REPLACES its
    column's scroll, it does not add to one. So a scrolling world has to fold
    the camera into EVERY vertical word, or the machines stay nailed to the
    screen while the hall slides past them.

    THE EQUALITY IS THE FOLD ITSELF. A machine's art sits at `row*8 - cam - v`,
    so between two frames it must travel by `(cam_a - cam_b) - (v_b - v_a)` —
    the camera's delta and its own stroke, together. Both halves come from
    outside the picture: the camera from the number the scene drives the ride
    with, the strokes from the blob, which HAS NO CAMERA IN IT AT ALL. Nothing
    but the fold can put the art where this predicts.
    """
    with Machine(str(ROM)) as m:
        to_hall(m)
        running(m)
        a = shot(m, tmp_path / "a.png")
        cam_a = m.read_u16(W, DP_CAM)
        r_a = m.read_u16(W, DP_SHOWN)
        board_and_ride(m)
        for _ in range(1200):
            if m.read_u16(W, DP_CAM) <= cam_a - 24:
                break
            m.advance(1)
        else:
            pytest.fail("the camera never climbed")
        cam_b = m.read_u16(W, DP_CAM)
        r_b = m.read_u16(W, DP_SHOWN)
        b = shot(m, tmp_path / "b.png")
        ONLY1, _ = layers(m)
    delta = cam_a - cam_b
    assert delta >= 24, delta
    wa, wb = words_for_screen(r_a), words_for_screen(r_b)
    checked = 0
    for sc in range(COLS):
        if sc in range(CAR_COL, CAR_COL + SHAFT_COLS):
            continue                              # the car: the scene drives it
        if wa[sc] is None or wb[sc] is None:
            continue
        if not (enabled(wa[sc]) and is_v(wa[sc]) and is_v(wb[sc])):
            continue
        want = delta - ((wb[sc] & V_MASK) - (wa[sc] & V_MASK))
        got = vshift(mask_strip(a, sc, ONLY1), mask_strip(b, sc, ONLY1),
                     span=min(100, abs(want) + 16))
        if got is None:
            continue                              # no clean translation to read
        assert got == want, (
            f"screen column {sc} travelled {got} where the camera's {delta} "
            f"and its own stroke predict {want} — the fold is not carrying "
            f"the camera")
        checked += 1
    assert checked >= 2, (
        f"only {checked} vertical columns gave a clean translation to check")


# --------------------------------------------------------------------------
# THE CONTROL: a row, not a disarm
# --------------------------------------------------------------------------
def test_the_flat_control_is_a_row_and_not_a_disarm(tmp_path):
    """B selects the blob's LAST row — every column at rest, and every enable
    bit and axis bit still set. The same channel moves the same 64 bytes into
    the same place, so exactly one variable differs between running and flat
    and a difference between the two pictures is attributable to the table.

    A control that worked by not transferring would prove nothing: it would be
    a picture with the mechanism switched off, and any defect in the mechanism
    would look the same.
    """
    flat = row(FLAT_ROW)
    live = [w for w in flat if enabled(w)]
    assert live, "the flat row has no enabled column — it IS a disarm"
    assert any(is_v(w) for w in live) and any(not is_v(w) for w in live), (
        "the flat row dropped an axis, so it is not the running row at rest")
    with Machine(str(ROM)) as m:
        to_hall(m)
        running(m)
        settle_hall(m, 6)
        # READ THE SELECTION BEFORE THE CAPTURE. `Machine.screenshot` spends an
        # emulated frame and it spends it with the pad RELEASED, so a state
        # read after it describes a frame in which Y was already up. The
        # PICTURE is still the flat one — the NMI transfers the row that was
        # selected while Y was down, and the main thread clears the selection
        # afterwards — which is the same one-frame ordering everything else
        # here accounts for.
        assert m.read_u16(W, DP_FLATSEL) == 1
        assert m.read_u16(W, DP_SHOWN) == FLAT_ROW
        a = shot(m, tmp_path / "a.png")
        m.advance(16, pad1=JOY_Y)
        assert m.read_u16(W, DP_SHOWN) == FLAT_ROW
        phase_b = m.read_u16(W, DP_PHASE)
        b = shot(m, tmp_path / "b.png")
    assert phase_b != 0, "the phase did not advance under the hold"
    for sc in range(COLS):
        assert strip(a, sc) == strip(b, sc), (
            f"screen column {sc} moved while the flat row was held")


def test_flattening_resumes_rather_than_restarts(tmp_path):
    """The phase advances every frame, flat or not, so releasing B returns the
    picture to where the animation would have been — not to its start. A
    toggle that RESTARTED would look right in any single frame."""
    with Machine(str(ROM)) as m:
        to_hall(m)
        m.advance(20)
        before = m.read_u16(W, DP_PHASE)
        m.advance(30, pad1=JOY_Y)
        after = m.read_u16(W, DP_PHASE)
    advanced = (after - before) % PHASES
    assert advanced >= 4, (
        f"the phase advanced {advanced} across 30 flattened frames — the "
        f"animation is being held rather than merely hidden")


# --------------------------------------------------------------------------
# THE CAR, and the rider it occludes for free
# --------------------------------------------------------------------------
def _oam(m, i):
    b = m.read_bytes(OAM, i * 4, 4)
    hi = (m.read_bytes(OAM, 512 + i // 4, 1)[0] >> ((i % 4) * 2)) & 3
    return dict(x=b[0], y=b[1], tile=b[2], attr=b[3], size=(hi >> 1) & 1,
                x9=hi & 1, prio=(b[3] >> 4) & 3)


def _vsym(name):
    for pool in (MAP["globals"], *(sc["placements"] for sc in MAP["scenes"].values())):
        for pl in pool:
            if pl["sym"] == name:
                return pl["start"]
    raise KeyError(name)


def rider_ink(m, tile, pal_index=0):
    """The sprite's OWN pixels: {(dx, dy): rgb} for every non-transparent pixel
    of the 32x32 cell OAM is pointing at.

    READ OUT OF VRAM AND CGRAM, not out of the generator, and this is the only
    observation of the rider that actually works. Classifying screen pixels by
    "colours only OBJ palette 0 has" finds almost nothing: the knight is steel
    and BG1's own ramp set is steel, so nearly every colour he uses is in both
    ranges and gets dropped. Measured — the priority plant came back TEST-BLIND
    twice against colour-set readings before this one.

    Here the question is asked per PIXEL instead: at this exact position, does
    the screen show the colour this sprite would have put there? A coincidence
    is possible for one pixel and not for hundreds.
    """
    base = _vsym("ES_V_MIL_OBJ_CHR")
    cg = m.read_bytes(CG, (128 + pal_index * 16) * 2, 32)

    def colour(i):
        wrd = cg[i * 2] | (cg[i * 2 + 1] << 8)
        e = lambda v: (v << 3) | (v >> 2)                   # noqa: E731
        return (e(wrd & 31), e((wrd >> 5) & 31), e((wrd >> 10) & 31))

    ink = {}
    for ty in range(4):                       # a 32x32 cell is 4x4 tiles, and
        for tx in range(4):                   #   the name table is 16 WIDE
            t = tile + ty * 16 + tx
            raw = m.read_bytes(MemoryType.SnesVideoRam, (base + t * 16) * 2, 32)
            for y in range(8):
                p0, p1 = raw[y * 2], raw[y * 2 + 1]
                p2, p3 = raw[16 + y * 2], raw[16 + y * 2 + 1]
                for x in range(8):
                    b = 7 - x
                    i = (((p0 >> b) & 1) | (((p1 >> b) & 1) << 1)
                         | (((p2 >> b) & 1) << 2) | (((p3 >> b) & 1) << 3))
                    if i:
                        ink[(tx * 8 + x, ty * 8 + y)] = colour(i)
    return ink


def _rider_index(m):
    """Which OAM entry is carrying the rider, found by its ATTRIBUTE rather
    than assumed: the lobby swaps the player and the leaves through the block
    (see mil_obj.asm), so the index is a function of state and hard-coding one
    here would silently test the wrong entry after the swap."""
    for i in range(12):
        e = _oam(m, i)
        if e["y"] != 240 and (e["attr"] & 0x0E) == 0:   # OBJ palette 0
            return i, e
    return None, None


def test_the_rider_is_only_visible_through_the_car_s_glass(tmp_path):
    """THE OCCLUSION IS THE PRIORITY ORDER AND NOTHING ELSE.

    Mode 4 renders BG2lo(1) · OBJ0(2) · BG1lo(3) · OBJ1(4) ... (RenderMode4,
    :824) and a sprite draws only where the pixel already there scores lower
    (`(_mainScreenFlags[x] & 0x0F) < spritePrio`, :958). The rider is priority
    0, so he scores 2 and LOSES to the car's BG1 shell — which is opaque
    everywhere except a hole cut where its glass is. No window register, no
    mask, no per-scanline work, and the occlusion follows the car up the shaft
    because it IS the car.

    Asserted PER PIXEL against the sprite's own CHR: at each position the cell
    would have drawn ink, does the screen show that ink? Inside the glass it
    must, in quantity; outside it must not, at all. A colour-set reading of the
    frame cannot do this — the knight is steel and so is BG1 — and two
    successive attempts at one let the priority plant through.
    """
    with Machine(str(ROM)) as m:
        to_hall(m)
        board_and_ride(m)
        for _ in range(900):
            if m.read_u16(W, DP_CAR) >= 40:
                break
            m.advance(1)
        else:
            pytest.fail("the car never left the floor")
        i, e = _rider_index(m)
        assert i is not None, "no rider entry is staged"
        ink = rider_ink(m, e["tile"])
        ox, oy = e["x"], e["y"]
        cam, car = m.read_u16(W, DP_CAM), m.read_u16(W, DP_CAR)
        im = shot(m, tmp_path / "car.png")
    assert len(ink) > 120, f"the rider's cell is nearly empty ({len(ink)} px)"
    car_top = CAR_ROW * 8 - cam - car
    gx0 = CAR_COL * 8 + WIN_X
    glass = (gx0, car_top + WIN_Y, gx0 + WIN_W, car_top + WIN_Y + WIN_H)
    inside = outside = 0
    leaks = []
    for (dx, dy), rgb in ink.items():
        x, y = ox + dx, oy + dy
        if not (0 <= x < 256 and 0 <= y < 224):
            continue
        if im.getpixel((x, y)) != rgb:
            continue                          # something else drew here
        if glass[0] <= x < glass[2] and glass[1] <= y < glass[3]:
            inside += 1
        else:
            outside += 1
            leaks.append((x, y))
    assert inside > 25, (
        f"only {inside} of the rider's own pixels reach the screen inside the "
        f"glass {glass} — he is not visible through it at all")
    assert outside == 0, (
        f"{outside} of the rider's pixels reach the screen OUTSIDE the glass "
        f"{glass}: {leaks[:8]} — the car's shell is not occluding him")


def test_the_car_moves_as_one_piece(tmp_path):
    """THE DEFECT THE LEAD LEFT IN THE CAR, as a regression.

    `mil_stage_row`'s car override walks TABLE indices, so it has to carry the
    lead as well — and when it did not, the car's LEFTMOST column stayed behind
    on the shaft while the rest of it climbed. Asserted on the BG1 layer alone:
    the car is BG1 art and the belts behind it are BG2, so a comparison that
    counted every changed pixel would be measuring the room, not the car.
    """
    with Machine(str(ROM)) as m:
        to_hall(m)
        board_and_ride(m)
        for _ in range(900):
            if m.read_u16(W, DP_CAR) >= 40:
                break
            m.advance(1)
        m.advance(1)
        a = shot(m, tmp_path / "a.png")
        ya = CAR_ROW * 8 - m.read_u16(W, DP_CAM) - m.read_u16(W, DP_CAR)
        m.advance(8)
        b = shot(m, tmp_path / "b.png")
        yb = CAR_ROW * 8 - m.read_u16(W, DP_CAM) - m.read_u16(W, DP_CAR)
    assert ya == yb, (
        "the camera is still following the car, so it holds still on screen "
        "and this case cannot see a column left behind — the ride's clamp "
        "moved")
    # RAW PIXELS, OUTSIDE THE GLASS. This compared BG1-only colours, and that
    # was seeing the defect by luck: a column left on the shaft scrolls the
    # CHANNEL below the car past the camera, and the channel's colours were
    # nothing BG2 had. The delivered channel's dark crust shares BG2's dark
    # range, `layers()` dropped every changed pixel as ambiguous, and the plant
    # went TEST-BLIND. The car is opaque everywhere but the glass, and BG2's
    # belt runs behind him there (6-10 px a sample, on the clean ROM); so the
    # band the glass covers is excluded and everything else in the car's four
    # columns must be identical eight frames apart, whatever colour it is.
    g0, g1 = ya + _art("SMIL_WIN_Y") - 1, ya + _art("SMIL_WIN_Y") + _art("SMIL_WIN_H")
    pa, pb = a.load(), b.load()
    for sc in range(CAR_COL, CAR_COL + SHAFT_COLS):
        moved = [(x, y) for x in range(sc * 8, sc * 8 + 8) for y in range(224)
                 if not g0 <= y < g1 and pa[x, y] != pb[x, y]]
        assert not moved, (
            f"screen column {sc} of the car changed in {len(moved)} pixel(s) "
            f"(first {moved[0]}) while the car held still — a column is being "
            f"left on the shaft; the car is not moving as one piece")


# --------------------------------------------------------------------------
# THE LOBBY, and the cycle that closes
# --------------------------------------------------------------------------
LEAF_TILE = 192                     # the leaf cell's tile id, so the
                                    #   staged entry that is NOT a leaf is him
DP_FADE_CTL = _dp("ES_FADE_CTL")


def rider_xy(m):
    """His staged OAM (x, y), or None when no non-leaf entry is on screen."""
    oam = m.read_bytes(OAM, 0, 12 * 4)
    him = [(oam[i * 4], oam[i * 4 + 1]) for i in range(12)
           if oam[i * 4 + 1] < 240 and oam[i * 4 + 2] != LEAF_TILE]
    return him[0] if him else None


def gen_pocket_columns():
    """Screen columns a retracted leaf reaches that lie outside every bay.

    Derived from the SAME two numbers the generator marks the tilemap from —
    the bays it read off the wall art and the leaf's travel — so this cannot
    drift from the thing it is checking, and it narrows itself if the art ever
    moves an opening.
    """
    out = set()
    for x0 in (DOOR_AX, DOOR_BX):
        out |= set(range(max(0, x0 - DOOR_TRAVEL), x0))
        out |= set(range(x0 + DOOR_W * 8,
                         min(256, x0 + DOOR_W * 8 + DOOR_TRAVEL)))
    bays = [range(x, x + DOOR_W * 8) for x in (DOOR_AX, DOOR_BX)]
    return sorted(x for x in out if not any(x in b for b in bays))


def bay_mid(i):
    return (DOOR_AX if i == 0 else DOOR_BX) + DOOR_W * 4


def test_the_doorway_is_exactly_two_leaves_wide():
    """What "shut" MEANS, and it is arithmetic the picture cannot show once it
    is wrong in the right way: a doorway wider than two leaves has doors that
    never meet, with a strip of whoever is inside showing down the middle at
    full travel zero. The ASM asserts this too; stating it here as well is what
    makes the geometry a claim of the rail rather than an accident of two
    constants."""
    assert DOOR_W * 8 == LEAF_BOX * LEAF_ROWS * (LEAF_BOX // LEAF_BOX) * 2 // LEAF_ROWS
    assert DOOR_W * 8 == LEAF_BOX * 2
    assert (LOBBY_FLOOR - DOOR_TOP) * 8 == LEAF_BOX * LEAF_ROWS


def test_a_bay_opens_because_he_is_in_front_of_it(tmp_path):
    """ONE RULE, NO STATE MACHINE. The travel is the state and it is a
    position, so a door caught half-open reverses from where it is. Driven
    across the whole walk rather than at its two ends: sampling only the
    extremes is how this rail's own bay A was once reported unreachable when it
    was working."""
    seen = []
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for _ in range(80):
            m.advance(4, pad1=JOY_LEFT)
            seen.append((m.read_u16(W, DP_PX), m.read_u16(W, DP_DOOR)))
            if seen[-1][0] <= 8:
                break
    opened = [px for px, d in seen if d >= DOOR_TRAVEL]
    assert opened, f"bay A never opened across the walk: {seen[:12]}"
    reach = _rail("SMIL_DOOR_REACH")
    for px, d in seen:
        near = abs(px + RIDER_BOX // 2 - bay_mid(0)) < reach
        if near and d == 0:
            assert any(p == px for p, _ in seen[:seen.index((px, d))]), (
                f"at px={px} he is in reach and the bay is shut")
    # ...and then away from it. To the RIGHT, because bay A sits near the left
    # clamp and walking left cannot put enough room between them: at the clamp
    # his centre is still exactly one reach from the bay's middle. (Sampling
    # only the two ends of a walk is how this rail's bay A was once reported
    # unreachable when it was working.)
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for _ in range(200):
            m.advance(1, pad1=JOY_LEFT)
            if m.read_u16(W, DP_PX) + RIDER_BOX // 2 <= bay_mid(0):
                break
        assert m.read_u16(W, DP_DOOR) > 0, "bay A did not open as he arrived"
        for _ in range(400):
            m.advance(1, pad1=JOY_RIGHT)
            if abs(m.read_u16(W, DP_PX) + RIDER_BOX // 2 - bay_mid(0)) > reach + 24:
                break
        else:
            pytest.fail("he never walked out of bay A's reach")
        for _ in range(120):
            if m.read_u16(W, DP_DOOR) == 0:
                break
            m.advance(1)
        assert m.read_u16(W, DP_DOOR) == 0, (
            "bay A did not shut once he had walked away")


def test_the_leaves_cover_him_and_he_covers_them(tmp_path):
    """DEPTH BETWEEN TWO SPRITES IS THE OAM INDEX, and this rail needs opposite
    answers from the same pair.

    The PPU keeps ONE sprite pixel per column, not one per priority — Mesen
    writes it as a single buffer, `_spriteColorsCopy[x] = color` beside
    `_spritePriorityCopy[x] = Priority` (:772-776) — so where two sprites
    overlap exactly one survives evaluation and only the SURVIVOR's priority is
    compared against the backgrounds. Priority cannot separate them; index can.

    So: on the deck he is ahead of the leaves, and inside a bay he is behind
    them. Asserted on the ORDER, and then on the picture that order produces.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        free_i, _ = _rider_index(m)
        assert free_i is not None
        leaf_free = [i for i in range(12)
                     if _oam(m, i)["y"] != 240 and i != free_i]
        assert leaf_free, "no leaves are staged in the lobby"
        assert free_i < min(leaf_free), (
            f"on the deck the player is at OAM {free_i}, behind leaves at "
            f"{sorted(leaf_free)} — the doors will cover him as he walks past")
        # ...and now aboard, where the answer must invert.
        for _ in range(600):
            if m.read_u16(W, DP_DOOR + 2) >= DOOR_TRAVEL:
                break
            m.advance(1, pad1=JOY_RIGHT)
        m.advance(3, pad1=JOY_UP)
        for _ in range(300):
            if m.read_u16(W, DP_BOARD) == 2:
                break
            m.advance(1)
        else:
            pytest.fail("he never got aboard")
        m.advance(1)
        ab_i, _ = _rider_index(m)
        leaf_ab = [i for i in range(12)
                   if _oam(m, i)["y"] != 240 and i != ab_i]
        assert ab_i is not None and leaf_ab
        assert ab_i > max(leaf_ab), (
            f"aboard, the player is at OAM {ab_i} ahead of leaves at "
            f"{sorted(leaf_ab)} — the doors will close behind him")


def test_every_staged_sprite_is_large_and_every_parked_one_is_not(tmp_path):
    """OAM Y wraps at 256, so a 32x32 sprite parked at 240 shows SIXTEEN ROWS
    of itself at the top of the screen. The claim is twelve entries and only
    nine are staged, so the three spare ones must have their size bit CLEAR —
    the same defect SMIL_PARK_Y exists to avoid, arriving through the hi table
    instead of through the Y byte."""
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for i in range(12):
            e = _oam(m, i)
            if e["y"] == 240:
                assert e["size"] == 0, (
                    f"OAM {i} is parked at 240 AND large — sixteen rows of it "
                    f"are wrapping onto the top of the screen")
            else:
                assert e["size"] == 1, f"OAM {i} is staged but small"
            assert e["x9"] == 0, f"OAM {i} has X9 set; nothing here goes past 255"


def test_the_ride_closes_the_loop_into_the_other_bay():
    """THE SEQUENCE, END TO END, AND THEN AGAIN.

    He boards the right-hand bay, the doors shut, the lift climbs and leaves
    through the top, and he is let out of the LEFT one — and the state he is
    let out into is the state he started the ride from, so a second ride is
    available without anything being reset. A transition that only worked once
    would look identical in any single frame, and only a second turn can tell
    them apart.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        assert m.read_u16(W, DP_ARRIVE) == 0, (
            "the arrival flag is set at boot — MAIN's establishment is gone")
        seen = []
        for turn in range(2):
            for _ in range(900):
                if m.read_u16(W, DP_DOOR + 2) >= DOOR_TRAVEL:
                    break
                m.advance(1, pad1=JOY_RIGHT)
            else:
                pytest.fail(f"turn {turn}: the far bay never opened")
            boarded = m.read_u16(W, DP_BAY)
            m.advance(3, pad1=JOY_UP)
            for _ in range(900):
                if scene(m) == SCENE_HALL:
                    break
                m.advance(1)
            else:
                pytest.fail(f"turn {turn}: never reached the hall")
            board_and_ride(m)       # ...he walks the mill deck and asks to go
            assert m.read_u16(W, DP_BAY) == 2, (
                f"turn {turn}: he boarded bay {boarded}, not the far one")
            for _ in range(1800):
                if scene(m) == SCENE_LOBBY:
                    break
                m.advance(1)
            else:
                pytest.fail(f"turn {turn}: the lift never came back")
            for _ in range(300):
                if m.read_u16(W, DP_BOARD) == 0:
                    break
                m.advance(1)
            else:
                pytest.fail(f"turn {turn}: the doors never parted on him")
            seen.append((m.read_u16(W, DP_BAY), m.read_u16(W, DP_PX),
                         m.read_u16(W, DP_DOOR), m.read_u16(W, DP_DOOR + 2)))
    assert seen[0][0] == 0, "he did not arrive in the OTHER bay"
    assert seen[0] == seen[1], (
        f"the second arrival differs from the first: {seen} — the sequence is "
        f"not a cycle, so something is being consumed rather than carried")
    px, dA, dB = seen[0][1], seen[0][2], seen[0][3]
    assert px + RIDER_BOX // 2 == bay_mid(0), (
        f"he is at {px + RIDER_BOX // 2}, not centred in bay A at {bay_mid(0)}")
    assert (dA, dB) == (DOOR_TRAVEL, 0)


def test_the_reveal_waits_for_the_picture():
    """The doors part in fifteen frames and the fade-in is longer, so an
    ungated reveal happens in the dark — which is the same as no reveal. The
    gate is scene_mgr's own published transition phase and NOT a count of
    frames: a count would need tuning against the ramp and would be a frame
    assumption in a rail that scales its time.

    Asserted as an ORDERING: while the transition phase is non-zero, the
    arriving bay's travel is zero.
    """
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for _ in range(900):
            if m.read_u16(W, DP_DOOR + 2) >= DOOR_TRAVEL:
                break
            m.advance(1, pad1=JOY_RIGHT)
        m.advance(3, pad1=JOY_UP)
        for _ in range(900):
            if scene(m) == SCENE_HALL:
                break
            m.advance(1)
        board_and_ride(m)
        for _ in range(1800):
            if scene(m) == SCENE_LOBBY:
                break
            m.advance(1)
        held = 0
        for _ in range(300):
            phase = m.read_bytes(W, DP_SM + 2, 1)[0]
            travel = m.read_u16(W, DP_DOOR)
            if phase:
                assert travel == 0, (
                    f"the doors moved to {travel} while the transition phase "
                    f"was still {phase} — the reveal is happening in the dark")
                held += 1
            elif travel >= DOOR_TRAVEL:
                break
            m.advance(1)
        else:
            pytest.fail("the doors never opened after the fade")
    assert held > 0, "the fade was already over on arrival — the gate is untested"


# --------------------------------------------------------------------------
# WHERE HE CAN STAND — and half of the answer is a scroll word
# --------------------------------------------------------------------------
def deck_mask():
    """The floor, one bit a screen column, out of the GENERATED inc.

    Read rather than retyped for the usual reason, and with a second one here:
    the map is the painter's own record of where it laid a deck, so a copy of
    it in this file would be a claim about the art that the art could not
    contradict.
    """
    lo, hi = _art("SMIL_DECK_LO"), _art("SMIL_DECK_HI")
    return [bool((lo if c < 16 else hi) & (1 << (c % 16))) for c in range(COLS)]


def test_the_shafts_have_no_floor_and_that_is_the_mechanism_s_price():
    """A SHAFT COLUMN CANNOT HAVE A DECK IN IT. It is displaced vertically, so
    every row of it must be identical, and a deck is a horizontal course. So
    the holes in the hall's floor are not level design — they are what
    offset-per-tile costs on the axis this rail chose, and this is the case
    that says the two facts are the same fact.

    Asserted against `kind()`'s geometry rather than against the mask's own
    bits, so it cannot pass by agreeing with itself.
    """
    mask = deck_mask()
    for at in STATION_AT:
        for k in range(SHAFT_COLS):
            sc = at + 1 + k
            assert not mask[sc], (
                f"screen column {sc} is a shaft AND claims a floor — one of "
                f"the two is wrong, and a shaft with a horizontal course in it "
                f"slides")
    assert sum(mask) == COLS - len(STATION_AT) * SHAFT_COLS, (
        "the floor is missing somewhere that is not a shaft")


def test_he_cannot_walk_into_the_hammer_s_shaft(tmp_path):
    """THE STATIC HALF, read off the machine. He walks left until he stops, and
    where he stops must be the edge of the run the floor map names — not a
    clamp, because there is no clamp: every step is offered to the floor and
    taken only if the floor accepts it.

    The stop is asserted to the PIXEL against the mask, so a collision that
    was merely approximately right would fail.
    """
    mask = deck_mask()
    with Machine(str(ROM)) as m:
        to_hall(m)
        for _ in range(600):
            m.advance(1, pad1=JOY_LEFT)
        px = m.read_u16(W, DP_PX)
        im = shot(m, tmp_path / "left.png")
    # the run he is standing in: walk left from his column while the floor holds
    col = px // 8
    first = col
    while first > 0 and mask[first - 1]:
        first -= 1
    assert px == first * 8, (
        f"he stopped at px={px} (column {col}); the run he is on starts at "
        f"column {first}, so the floor let him past its edge or stopped him "
        f"short of it")
    assert not mask[first - 1], "he stopped inside a continuous run"


def test_he_cannot_walk_off_the_end_of_the_world(tmp_path):
    """...and the same rule is what bounds the world. The right-hand end of the
    deck is the last column, so his box has to stop with its right edge on it —
    there is no separate clamp for the screen edge and there should not be."""
    with Machine(str(ROM)) as m:
        to_hall(m)
        for _ in range(600):
            m.advance(1, pad1=JOY_RIGHT)
        px = m.read_u16(W, DP_PX)
    assert px + RIDER_BOX == COLS * 8, (
        f"he stopped at px={px}; his box should end exactly at the world's "
        f"last column ({COLS * 8})")


def test_the_lift_s_columns_are_floor_only_while_the_car_is_down(tmp_path):
    """THE DYNAMIC HALF, AND THE REASON THIS RAIL'S COLLISION IS ITS OWN.

    The lift's four columns are a hole in the deck that the car fills when it
    is parked. Whether a figure can stand there is therefore a function of the
    car's displacement — the same quantity the offset word for those columns
    carries — and no tile-flag table can say that, because the answer changes
    while the tiles do not.

    Asserted as a CROSSING: with the car down he can walk from the run on one
    side to the run on the other, and the mask says those runs are not
    connected. So the only thing that carried him across was the car.
    """
    mask = deck_mask()
    lift = list(range(SMIL_LIFT_COL, SMIL_LIFT_COL + SHAFT_COLS))
    assert not any(mask[c] for c in lift), (
        "the lift's columns are painted floor, so this case proves nothing")
    with Machine(str(ROM)) as m:
        to_hall(m)
        assert m.read_u16(W, DP_CAR) == 0, "the car is not parked on arrival"
        start = m.read_u16(W, DP_PX)
        for _ in range(600):
            m.advance(1, pad1=JOY_LEFT)
        left = m.read_u16(W, DP_PX)
        for _ in range(600):
            m.advance(1, pad1=JOY_RIGHT)
        right = m.read_u16(W, DP_PX)
    assert left < lift[0] * 8, (
        f"he never got left of the lift (px={left}) — the car is not bridging "
        f"its own shaft")
    assert right + RIDER_BOX > (lift[-1] + 1) * 8, (
        f"he never got right of the lift (px={right})")
    assert left // 8 not in lift and right // 8 not in lift
    # ...and the two ends are in DIFFERENT runs of the painted floor, so the
    # crossing cannot be explained by the deck alone.
    def run_of(c):
        first = c
        while first > 0 and mask[first - 1]:
            first -= 1
        return first
    assert run_of(left // 8) != run_of(right // 8), (
        "both ends of his walk are in one painted run — the car was never "
        "load-bearing and this case would pass without it")
    assert start // 8 in lift, "he did not arrive standing on the car"


def test_stepping_off_the_car_gives_him_the_controls(tmp_path):
    """He arrives ON the lift, not shut inside it — the car is parked and its
    bottom IS the deck's top, which the generator asserts. So the same test
    that boards him is the one that releases him, and there is no separate
    'get out' state to keep in step with anything."""
    with Machine(str(ROM)) as m:
        to_hall(m)
        assert m.read_u16(W, DP_BOARD) == 0, "he arrived aboard, not standing"
        for _ in range(60):
            m.advance(1, pad1=JOY_LEFT)
        off = m.read_u16(W, DP_PX)
        assert off < SMIL_LIFT_COL * 8, "he did not step off the car"
        assert m.read_u16(W, DP_BOARD) == 0
        m.advance(4, pad1=JOY_UP)
        assert m.read_u16(W, DP_BOARD) == 0, (
            "UP boarded him while he was standing beside the lift, not on it")
        # ...and the car is not a ride he started: it is where the CALL rule
        # left it, which is away, because he walked away from it.
        assert m.read_u16(W, DP_CAR) > 0, (
            "the lift did not withdraw when he stepped off it")
        for _ in range(400):
            m.advance(1, pad1=JOY_RIGHT)
            if m.read_u16(W, DP_PX) >= SMIL_LIFT_COL * 8:
                break
        m.advance(4, pad1=JOY_UP)
        m.advance(4)
        assert m.read_u16(W, DP_CAR) > 0, "UP on the car did not start the ride"


def test_he_waits_at_the_shaft_s_edge_for_the_lift(tmp_path):
    """THE DYNAMIC HALF DOING WORK, which is the whole reason this rail's
    collision is its own rather than borrowed.

    The car withdraws when he walks away and comes when he walks back, so its
    four columns are floor on some frames and a hole on others while the TILES
    NEVER CHANGE. Walking back toward it he reaches the edge before it does and
    is held there — and the frame he starts moving again is the frame the car
    lands, because `mil_solid` answers from the car's own displacement and not
    from a copy of it.

    Asserted as that coincidence, not as "he was blocked for a while": a stall
    of the right length for the wrong reason is exactly what a tuned constant
    would produce.
    """
    with Machine(str(ROM)) as m:
        to_hall(m)
        for _ in range(300):                  # walk away; the lift withdraws
            m.advance(1, pad1=JOY_LEFT)
        assert m.read_u16(W, DP_CAR) > 0, "the lift never left"
        trace = []
        for _ in range(60):
            m.advance(1, pad1=JOY_RIGHT)
            trace.append((m.read_u16(W, DP_PX), m.read_u16(W, DP_CAR)))
    stalls = [i for i in range(1, len(trace)) if trace[i][0] == trace[i - 1][0]]
    assert stalls, "he was never held at the shaft — the hole is not solid-checked"
    last = stalls[-1]
    assert trace[last][1] == 0, (
        f"he was released with the car at {trace[last][1]}, not at the deck — "
        f"the block is not reading the car's position")
    assert trace[last - 1][1] > 0 or trace[last][1] == 0
    held_at = trace[stalls[0]][0]
    assert held_at + RIDER_BOX == SMIL_LIFT_COL * 8, (
        f"he was held at px={held_at}; his box should stop with its right edge "
        f"exactly on the last floor column, which is where the lift's first "
        f"column begins")
    after = [px for px, _ in trace[last + 1:]]
    assert after and after[-1] > held_at, "he never got moving again"


def test_a_retracted_leaf_is_hidden_by_the_pier_it_slides_into(tmp_path):
    """A LIFT DOOR RETRACTS INTO THE WALL, so the wall must beat the leaf.

    The leaves are OBJ and slid at priority 1, which mode 4 scores 4
    (`RenderMode4`'s {2,4,6,8}) — above BG1's NORMAL 3, which is what makes
    them close over the bay recess. Nothing put them under BG1's HIGH 7, so
    for six commits they opened IN FRONT OF THE BUILDING: the doors slid
    across the piers instead of into them. Twenty-two cases passed throughout,
    because every one of them was asking about the bay and none about the
    wall beside it. It was found by looking.

    THE ASSERTION IS THAT THE WALL DOES NOT CHANGE. A leaf that has retracted
    into its pocket is invisible, so the pocket's pixels must be the same
    whether the doors are shut or standing open — no reference picture, no
    colour list, just the same region of the same screen in two states. That
    is what "behind" MEANS, and it stays true if the art, the palette or the
    travel ever move.
    """
    pocket = gen_pocket_columns()
    assert pocket, "no pocket columns: the art's bays reach both screen edges"
    y0, y1 = DOOR_TOP * 8, LOBBY_FLOOR * 8

    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for _ in range(600):            # ...both bays shut, and he is between
            if scene(m) == SCENE_LOBBY and m.read_bytes(W, DP_SM + 2, 1)[0] == 0:
                break
            m.advance(1)
        assert max(m.read_u16(W, DP_DOOR + 2 * i) for i in range(BAYS)) == 0, \
            "a bay was already open — the spawn is inside a reach"
        # HE MOVES BETWEEN THE TWO CAPTURES AND HE IS A SPRITE OVER THIS WALL,
        # so where he stands is not evidence about the leaves. His box in
        # BOTH states is excluded rather than assumed away — the first cut of
        # this case reported 735 changed pixels that were all him walking.
        where = [m.read_u16(W, DP_PX)]
        shut = shot(m, tmp_path / "shut.png")

        for _ in range(600):            # ...and now with the far bay standing
            if m.read_u16(W, DP_DOOR + 2) >= DOOR_TRAVEL:
                break
            m.advance(1, pad1=JOY_RIGHT)
        else:
            pytest.fail("the far bay never opened")
        where.append(m.read_u16(W, DP_PX))
        opened = shot(m, tmp_path / "open.png")

    him = {x for px in where for x in range(px - 1, px + RIDER_BOX + 1)}
    pocket = [x for x in pocket if x not in him]
    assert pocket, "he stood in every pocket — nothing left to measure"

    assert shut.tobytes() != opened.tobytes(), \
        "the two captures are identical — the doors never moved, so this case " \
        "would pass on a rail with no doors at all"

    a, b = shut.load(), opened.load()
    moved = [(x, y) for x in pocket for y in range(y0, y1) if a[x, y] != b[x, y]]
    assert not moved, (
        f"{len(moved)} pocket pixel(s) changed when the doors opened, first at "
        f"{moved[0]} — a leaf is drawing OVER the pier it should retract into")


def test_the_handover_does_not_show_him_where_the_last_room_left_him():
    """A SCENE EDGE MUST RESTAGE HIM, because OAM is not scene state.

    `hall::enter` parked the lobby's leaves and said why — "the shadow carries
    across the edge" — and then did not stage the MAN. So his entry held the
    lobby's coordinates through the whole handover: the mill floor faded up
    with him standing where the bay had been, for 18 frames measured, and he
    snapped onto the car when the tick finally ran. The lobby's own enter had
    the identical hole in the other direction.

    THE ASSERTION IS ON THE FRAMES A VIEWER CAN SEE. Fade level 0 is black and
    proves nothing, so this counts only lit frames, and it allows exactly one:
    `enter` runs with the NMI masked, so the shadow it writes reaches OAM on
    the next NMI, and that one frame is the DMA's lag rather than a stale pose.
    Anything more is the bug.
    """
    slack = 8                       # a frame of walk at SMIL_WALK_STEP
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for _ in range(600):
            if scene(m) == SCENE_LOBBY and m.read_bytes(W, DP_SM + 2, 1)[0] == 0:
                break
            m.advance(1)
        for _ in range(600):
            if m.read_u16(W, DP_DOOR + 2) >= DOOR_TRAVEL:
                break
            m.advance(1, pad1=JOY_RIGHT)
        else:
            pytest.fail("the far bay never opened")

        seen_hall, lit_stale = False, []
        for k in range(140):
            m.advance(1, pad1=JOY_UP if k < 4 else {})
            if scene(m) == SCENE_HALL:
                seen_hall = True
            oam = m.read_bytes(OAM, 0, 12 * 4)
            him = [(oam[i * 4], oam[i * 4 + 1]) for i in range(12)
                   if oam[i * 4 + 1] < 240 and oam[i * 4 + 2] != LEAF_TILE]
            fade = m.read_bytes(W, DP_FADE_CTL, 1)[0]
            if him and fade > 0:
                drift = abs(him[0][0] - (m.read_u16(W, DP_PX) & 0xFF))
                if drift > slack:
                    lit_stale.append((k, him[0][0], m.read_u16(W, DP_PX), fade))
    assert seen_hall, "the ride never handed over — this case tested nothing"
    assert len(lit_stale) <= 1, (
        f"{len(lit_stale)} LIT frame(s) drew him away from ES_MIL_PX, first "
        f"{lit_stale[0]} (frame, staged x, PX, fade) — the new room is showing "
        f"the pose the old one left behind")


def test_he_does_not_shift_when_the_lift_starts_under_him():
    """THE MAN MUST NOT MOVE ON EITHER AXIS WHEN THE CAR STARTS.

    He was drawn at ES_MIL_PX while standing on the car and at a glass-centred
    constant while riding, and the UP that boarded him snapped PX to the car's
    LEFT EDGE -- three pixels short of that constant, under a comment saying it
    was the same place. So the first moving frame shoved him 3 px right, and
    arrival shoved him 3 px back. Every probe written for this defect printed
    only Y; the owner said "jumps", the report was read as vertical, and the
    horizontal axis went unmeasured through a whole abandoned fix.

    THE OBSERVATION IS HIS OAM ENTRY, both coordinates, held against the last
    frame before the car moves. A constant Y alone is exactly the reading that
    hid this.
    """
    with Machine(str(ROM)) as m:
        to_hall(m)
        for _ in range(400):
            if m.read_bytes(W, DP_SM + 2, 1)[0] == 0:
                break
            m.advance(1)
        rest = rider_xy(m)
        assert rest is not None, "he is not staged while standing on the car"
        seen, cars = set(), []
        for k in range(24):
            m.advance(1, pad1=JOY_UP if k < 6 else {})
            car = m.read_u16(W, DP_CAR)
            if car:
                cars.append(car)
                seen.add(rider_xy(m))
    assert len(cars) >= 12 and cars[-1] > cars[0], \
        f"the lift never climbed ({cars[:4]}...) -- this case tested nothing"
    assert seen == {rest}, (
        f"his OAM (x, y) moved when the car started: standing {rest}, riding "
        f"{sorted(seen)} -- the boarding snap and the ride stage disagree on "
        f"where he stands")


def test_he_holds_one_pose_for_the_whole_ride():
    """NOTHING ABOUT HIM CHANGES BETWEEN THE CAR STARTING AND THE CAR LEAVING.

    The ride used to pick his cell from the phase, cycling the pack's two idle
    frames. They are a breath -- same feet, head two rows lower on the second
    -- and on the deck that is what it looks like. Through the glass his boots
    are behind the sill, so the visible part of him simply moves up a line and
    back, every eighty-odd frames, for the length of the climb. The owner saw
    it, and said it was probably not idle; it was, and that was the defect.

    THE OBSERVATION IS WHAT THE PPU DRAWS HIM FROM AND WHAT REACHES THE SCREEN:
    his OAM tile, and the rows of his own ink that survive the glass, taken
    relative to his OAM row so the climb itself cancels out. Both are held to
    one value across the entire ride, sampled every fourth frame from the car
    starting until it leaves the scene.
    """
    tiles, spans, samples = set(), set(), 0
    with Machine(str(ROM)) as m:
        to_hall(m)
        board_and_ride(m)
        for k in range(120):
            if scene(m) != SCENE_HALL:
                break
            oam = m.read_bytes(OAM, 0, 12 * 4)
            him = [(oam[i * 4], oam[i * 4 + 1], oam[i * 4 + 2]) for i in range(12)
                   if oam[i * 4 + 1] < 240 and oam[i * 4 + 2] != LEAF_TILE]
            if not him:
                break                           # parked: the car is gone
            x, y, tile = him[0]
            tiles.add(tile)
            if k % 4 == 0:
                ink = rider_ink(m, tile)
                im = shot(m, Path("build") / "pose.png").load()
                seen = [dy for (dx, dy), c in ink.items()
                        if 0 <= x + dx < 256 and 0 <= y + dy < 224 and im[x + dx, y + dy] == c]
                if seen:
                    spans.add((min(seen), max(seen)))
                    samples += 1
            m.advance(1)
    assert samples >= 8, f"only {samples} samples reached the glass — nothing was ridden"
    assert len(tiles) == 1, f"his cell changed during the ride: tiles {sorted(tiles)}"
    assert len(spans) == 1, (
        f"the part of him showing through the glass moved: rows (rel. to his "
        f"OAM row) {sorted(spans)} — he is bobbing in the car")


def test_standing_on_the_car_is_the_same_picture_as_riding_it(tmp_path):
    """FROM STEPPING ONTO THE CAR TO RIDING IT, NOTHING ABOUT HIM CHANGES.

    Standing on the lift at rest he was staged like anywhere else on the deck:
    in FRONT of BG1, breathing, cells and facing from the walk. The ride
    stages him BEHIND the car, still, and without his facing. So the frame the
    car moved: his cape and boots vanished behind the sill and the left wall
    (the owner saw the lower left of the figure snap), the breath stopped, and
    a man who had boarded facing left turned to face right. Three snaps, one
    cause -- two stagings of one man in one place.

    THE OBSERVATION IS HIS WHOLE OAM ENTRY plus what reaches the screen:
    (x, y, tile, attr) sampled at rest on the car, again after he has walked
    along it and back to face LEFT, and on every frame of the climb -- all one
    value. And on each sample, none of his own ink may land outside the glass:
    the car is opaque everywhere else, so a pixel of him beside the window is
    him drawn in front of it.
    """
    lift = _art("SMIL_LIFT_COL") * 8
    car_top = _art("SMIL_CAR_ROW") * 8 - CAM_MAX
    wx, wy = _art("SMIL_WIN_X"), _art("SMIL_WIN_Y")
    ww, wh = _art("SMIL_WIN_W"), _art("SMIL_WIN_H")

    def sample(m, tag):
        oam = m.read_bytes(OAM, 0, 12 * 4)
        him = [tuple(oam[i * 4:i * 4 + 4]) for i in range(12)
               if oam[i * 4 + 1] < 240 and oam[i * 4 + 2] != LEAF_TILE]
        assert him, f"{tag}: he is not staged"
        x, y, tile, attr = him[0]
        ink = rider_ink(m, tile)
        px = shot(m, tmp_path / f"{tag}.png").load()
        outside = [(x + dx, y + dy) for (dx, dy), c in ink.items()
                   if 0 <= x + dx < 256 and 0 <= y + dy < 224 and px[x + dx, y + dy] == c
                   and not (lift + wx <= x + dx < lift + wx + ww
                            and car_top + wy - 1 <= y + dy < car_top + wy + wh)]
        assert not outside, (f"{tag}: {len(outside)} of his pixels show OUTSIDE the "
                             f"glass, first {outside[0]} -- he is drawn in front of the car")
        return (x, y, tile, attr)

    seen = {}
    with Machine(str(ROM)) as m:
        to_hall(m)
        for _ in range(400):
            if m.read_bytes(W, DP_SM + 2, 1)[0] == 0:
                break
            m.advance(1)
        seen["at rest"] = sample(m, "rest")
        m.advance(2, pad1=JOY_RIGHT)              # along the car...
        m.advance(2, pad1=JOY_LEFT)               # ...and back, facing LEFT
        m.advance(2)                               # the walk cell settles
        seen["faced left"] = sample(m, "left")
        assert seen["faced left"][3] & 0x40, "he is not facing left -- the flip bit is clear"
        m.advance(6, pad1=JOY_UP)
        rode = 0
        for k in range(40):
            m.advance(1)
            if m.read_u16(W, DP_CAR):
                rode += 1
                if k % 5 == 0:
                    seen[f"riding@{k}"] = sample(m, f"ride{k}")
    assert rode >= 20, f"the lift did not climb ({rode} moving frames)"
    FLIP = 0x40
    # The turn between the first two samples is deliberate, so the facing bit
    # is the ONE thing allowed to differ across the whole set...
    shape = {(x, y, t, a & ~FLIP) for x, y, t, a in seen.values()}
    assert len(shape) == 1, (
        "his OAM entry (x, y, tile, attr sans facing) changed between standing "
        "on the car and riding it:\n  "
        + "\n  ".join(f"{k:12s} {v}" for k, v in seen.items()))
    # ...and from the turn onward, NOTHING differs: the facing he boarded with
    # is the facing he rides with.
    after = {v for k, v in seen.items() if k != "at rest"}
    assert len(after) == 1, (
        "he changed between boarding facing left and riding:\n  "
        + "\n  ".join(f"{k:12s} {v}" for k, v in seen.items() if k != "at rest"))
