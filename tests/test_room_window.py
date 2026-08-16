"""this slice — "the room": the lantern, end to end.

WHAT THESE TESTS READ. Every assertion here lands on rendered OUTPUT — the
screenshot's pixels, the OAM shadow's bytes, the WRAM table the HDMA channel
actually consumes. None of them reads a "was the window armed?" flag, and
none derives its expectation from the artifact under test.

THE ORACLE IS THE GENERATOR, NOT THE ROM. `tools/gen_room_assets.py` and
`tools/gen_iris_lut.py` say what colour a given screen pixel must be and how
wide the lit span must be on a given scanline; the tests re-derive that in
Python and compare to what the PPU produced. So a wrong tile, a wrong
palette, a wrong window bound and a wrong colour-math field all fail here —
the chain is asset -> VRAM -> PPU -> pixel, checked at both ends.

THE CENTRE COMES FROM OAM, NOT FROM THE IRIS TABLE. Deriving the expected
window bounds from the table the window is built from would be a tautology:
if the table were wrong, the expectation would move with it and the test
would still pass. The hero's OAM entry is produced by a different code path
(room_hero's hero_place), so using it as the anchor keeps the two
independent — and it is itself rendered output.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType       # noqa: E402
from mz_drive import content_top, load_tool            # noqa: E402

ROM = SUPERFORGE / "build" / "room.sfc"


def _room_symbols():
    """Addresses from the emitted map, not hardcoded copies of it.

    These tests used to carry `SM_CTL = 0x14` and `0x04A4` as literals —
    faithful transcriptions of one build's allocation that silently broke
    the day a new global dp claim re-packed the map (C2: save's sv_args
    landed at $00 and pushed sm_ctl to $23). The allocator emits
    symbol_map.json precisely so a consumer can ask; asking is the fix
    that repairs the CLASS of breakage, not the instance.
    """
    jmap = json.loads((SUPERFORGE / "build" / "rm" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in jmap["globals"]}
    for sc in jmap["scenes"].values():
        for p in sc["placements"]:
            syms.setdefault(p["sym"], p)
    return syms


_SYMS = _room_symbols()

rooms = load_tool("gen_room_assets")
iris = load_tool("gen_iris_lut")

# --- the room's geometry, taken from the generators and the feature --------
RADIUS = iris.RADIUS
HALF = iris.half_widths()
TILE = rooms.T
VIS_ROWS = rooms.VIS_ROWS
SCANLINES = 224
COLDATA_SUB = 6                 # window_iris.asm's COLDATA intensity
SPAWN = (128 - 8, 112 - 8)      # room_logic's RM_SPAWN_X/Y

# The SNES displays tilemap pixel rows 1..224 when BGnVOFS = 0, so screen
# scanline S shows tilemap pixel row S+1. MEASURED, not assumed: the top
# visible line of this ROM is the wall-cap tile's pixel row 1, not row 0.
VOFS_SKEW = 1


def bgr_to_rgb5(word: int) -> tuple:
    return (word & 31, (word >> 5) & 31, (word >> 10) & 31)


def px5(img, x, y) -> tuple:
    """A screenshot pixel as 5-bit BGR555 components."""
    return tuple(c >> 3 for c in img.getpixel((x, y)))


def dim(rgb5: tuple) -> tuple:
    """Colour math: subtract COLDATA from a pixel, saturating at 0.

    This is the arithmetic in SnesPpu.cpp:1367-1372 — per-component
    subtract, clamped, halving off (CGADSUB bit 6 is clear).
    """
    return tuple(max(c - COLDATA_SUB, 0) for c in rgb5)


def bg1_colour_at(sx: int, sy: int) -> tuple:
    """The UNLIT-independent BG1 colour at a screen pixel, from the generator.

    Walks the same path the PPU does: screen pixel -> tilemap cell -> tile
    art -> palette index -> BGR555. Nothing here reads the ROM.
    """
    ty = sy + VOFS_SKEW
    col, row = sx // TILE, ty // TILE
    tid = rooms.bg1_pick(col, row)
    art = {rooms.TL_FLOOR_A: rooms.floor_tile(rooms.FLOOR_D),
           rooms.TL_FLOOR_B: rooms.floor_tile(rooms.FLOOR_L),
           rooms.TL_WALL: rooms.wall_tile(False),
           rooms.TL_WALL_TOP: rooms.wall_tile(True)}[tid]
    idx = art[(ty % TILE) * TILE + (sx % TILE)]
    return rooms.BG1_COLORS[idx]


# The BG3 caption (room.asm's s_caption, at tilemap row 1 col 2). BG3 is
# DELIBERATELY outside colour math — CGADSUB's bit 2 is clear — so it stays
# full brightness everywhere, lantern or no lantern. Pixels it covers are
# therefore not BG1 pixels and are excluded from the BG1 samplers below;
# test_caption_is_never_dimmed asserts the invariant positively instead of
# leaving it as a hole in the coverage.
CAPTION = "A LANTERN IN A DARK ROOM"
CAPTION_ROW, CAPTION_COL = 1, 2


def bg3_covers(sx: int, sy: int) -> bool:
    ty = sy + VOFS_SKEW
    return (ty // TILE == CAPTION_ROW
            and CAPTION_COL <= sx // TILE < CAPTION_COL + len(CAPTION))


def decor_cells():
    return [(c, r) for r in range(VIS_ROWS) for c in range(32)
            if rooms.has_decor(c, r)]


def expected_bounds(cx: int, cy: int, scanline: int):
    """(left, right) of the lit span, or None when the row has no lantern."""
    dy = scanline - cy
    if abs(dy) > RADIUS:
        return None
    h = HALF[dy + RADIUS]
    return max(cx - h, 0), min(cx + h, 255)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runner():
    assert ROM.exists(), f"{ROM} missing — run `make room`"
    r = MesenRunner()
    r.boot_rom(str(ROM))                  # 120 EMULATED frames of boot
    yield r
    r.stop()


@pytest.fixture(scope="module")
def anchor(runner, tmp_path_factory):
    """Screenshot row that IS scanline 0 — LOCATED on the TITLE frame.

    `content_top` finds the letterbox by asking which rows are entirely
    black, which needs a frame with no fully-black scanline. The room does
    not qualify and that is the feature working, not a defect: the bottom
    wall's shadow row is (3,3,4) and the row below it is the floor tile's
    grout line (5,5,5), and subtracting COLDATA's 6 saturates both to black.
    The letterbox is a property of the CAPTURE, not of the frame, so
    measuring it on the title screen (backdrop $1000, no black rows) and
    reusing it for the room is sound — and it beats hardcoding a 7.
    """
    shot = tmp_path_factory.mktemp("anchor") / "title.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    return content_top(Image.open(str(shot)).convert("RGB"))


# scene_mgr's control block: +0 cur scene id, +2 transition phase (0 = run).
SM_CTL = _SYMS["ES_SM_CTL"]["start"]
SCENE_TITLE, SCENE_ROOM = 0, 1


def scene_state(runner):
    b = runner.read_bytes(MemoryType.SnesWorkRam, SM_CTL, 4)
    return b[0], b[2]


def settle(runner, want, limit=300):
    """Block until scene `want` is running (transition phase 0).

    The runner is module-scoped, so a test cannot assume which scene the
    previous one left behind. Driving from the OBSERVED state rather than
    from an assumed one is the difference between a helper and a guess —
    the same reason mz_drive polls instead of counting frames.

    `limit` is EMULATED frames. It used to be a loop of run_frames(5), i.e.
    a five-second wall budget wearing a frame count's clothes: a transition
    needs a number of FRAMES to complete, and under host load five wall
    seconds buys far fewer of them. Same reads, same failure message — only
    the clock the budget is kept in changed.

    ...and then TWO more frames, for the ROM's OWN pipeline rather than for
    the harness. Measured: at the frame the scene manager first reports
    (want, phase 0) the fade level in ES_FADE_CTL has already reached 15 —
    but INIDISP is a PPU register, so the NMI has not yet committed that
    level for the frame being rendered, and the screen is still a fade step
    behind the variable. A caller that reads PIXELS right after the flag
    therefore sees the last step, and two tests did: the residue test read
    the title's white one notch dim and the caption test counted zero
    full-white pixels. The old five-frame polling granularity hid it by
    overshooting the arrival by up to four frames — an accident worth
    replacing with a stated reason.

    This is NOT the screenshot's presentation lag; `take_screenshot` absorbs
    that itself and is frame-synchronous. This is game state on its way to a
    hardware register. Callers that only read WRAM pay two frames they do not
    need, which is 9 ms.
    """
    try:
        runner.wait_until(lambda: scene_state(runner) == (want, 0),
                          max_frames=limit, what=f"scene {want} running")
    except TimeoutError:
        cur, phase = scene_state(runner)
        raise AssertionError(
            f"scene {want} never settled: stuck at (scene {cur}, phase {phase})")
    runner.wait_frames(2)                 # let the picture catch up to the flag


def press_start(runner):
    runner.set_input(0, start=True)
    runner.wait_frames(4)                 # 4 EMULATED frames of the press
    runner.set_input(0)
    runner.wait_frames(4)


def enter_room(runner, respawn=False):
    """Leave the hero standing in a freshly-entered room, wherever we were.

    `respawn` forces a title round-trip first, so a test that needs the
    hero at his spawn point gets him there rather than inheriting the
    previous test's walk.
    """
    cur, _ = scene_state(runner)
    if respawn and cur == SCENE_ROOM:
        press_start(runner)
        settle(runner, SCENE_TITLE)
        cur = SCENE_TITLE
    if cur != SCENE_ROOM:
        settle(runner, SCENE_TITLE)
        press_start(runner)
    settle(runner, SCENE_ROOM)


def back_to_title(runner):
    if scene_state(runner)[0] != SCENE_TITLE:
        press_start(runner)
    settle(runner, SCENE_TITLE)


def shoot(runner, tmp_path, name):
    p = tmp_path / f"{name}.png"
    runner.take_screenshot(str(p), settle_frames=2)
    return Image.open(str(p)).convert("RGB")


# The bearer's OAM slot, from the emitted map (this slice pinned the HUD pips
# at slots 0..7, so the hero packs at 8 — reading slot 0 here would read a
# pip). X9 lives 2 bits per sprite in the hi table at 512 + slot/4.
HERO_SLOT = _SYMS["ES_O_HERO"]["start"]


def hero_centre(runner):
    """The lantern's centre, read out of the OAM shadow the PPU renders."""
    oam = runner.read_bytes(MemoryType.SnesSpriteRam, HERO_SLOT * 4, 4)
    hi = runner.read_bytes(MemoryType.SnesSpriteRam, 512 + HERO_SLOT // 4, 1)[0]
    x = oam[0] | (((hi >> ((HERO_SLOT % 4) * 2)) & 1) << 8)
    return x + 8, oam[1] + 8


# --------------------------------------------------------------------------
# the ROM exists and boots
# --------------------------------------------------------------------------

def test_room_rom_is_a_valid_512k_image():
    assert ROM.stat().st_size == 512 * 1024


def test_room_scene_renders_the_room(runner, anchor, tmp_path):
    """Boot -> START -> the room is on screen, with the hero where he spawns."""
    enter_room(runner, respawn=True)
    assert hero_centre(runner) == (SPAWN[0] + 8, SPAWN[1] + 8)
    img = shoot(runner, tmp_path, "room")
    colours = {img.getpixel((x, anchor + y))
               for x in range(0, 256, 4) for y in range(0, SCANLINES, 4)}
    assert len(colours) > 8, (
        f"the room frame has only {len(colours)} distinct colours — it did "
        f"not render")


# --------------------------------------------------------------------------
# the table the HDMA channel actually reads
# --------------------------------------------------------------------------

def _iris_table(runner):
    """The 451 live bytes of the iris table, straight out of WRAM."""
    return runner.read_bytes(MemoryType.SnesWorkRam,
                             _SYMS["ES_IRIS_TAB"]["start"], 451)


def test_iris_table_matches_the_lut_oracle(runner):
    """Every one of the 224 rows, against gen_iris_lut's circle.

    This reads the bytes the DMA controller fetches, not a flag saying the
    table was built. The structural bytes are checked too: a wrong repeat
    count would silently stretch part of the circle down the screen.
    """
    enter_room(runner)
    cx, cy = hero_centre(runner)
    tab = _iris_table(runner)
    assert tab[0] == 0x80 | 127, f"first entry header is ${tab[0]:02X}"
    assert tab[255] == 0x80 | 97, f"second entry header is ${tab[255]:02X}"
    assert tab[450] == 0x00, "the table is not terminated"
    wrong = []
    for s in range(SCANLINES):
        off = 1 + 2 * s if s < 127 else 256 + 2 * (s - 127)
        got = (tab[off], tab[off + 1])
        want = expected_bounds(cx, cy, s)
        want = (0xFF, 0x00) if want is None else want
        if got != want:
            wrong.append((s, got, want))
    assert not wrong, f"{len(wrong)} scanline(s) wrong, first 5: {wrong[:5]}"


# --------------------------------------------------------------------------
# the pixels — the whole point
# --------------------------------------------------------------------------

def test_inside_is_lit_and_outside_is_dimmed(runner, anchor, tmp_path):
    """The composited result, sampled either side of the window boundary.

    For each sampled scanline the expected colour comes from the ASSET
    GENERATOR (tile art + palette), and the expected dimming from the
    colour-math arithmetic — so this fails on a wrong tile, a wrong palette
    upload, a wrong window bound, a wrong CGWSEL prevent mode and a wrong
    CGADSUB layer mask alike.
    """
    enter_room(runner)
    cx, cy = hero_centre(runner)
    img = shoot(runner, tmp_path, "lit")
    checked = 0
    for s in range(cy - 40, cy + 41, 8):
        span = expected_bounds(cx, cy, s)
        assert span is not None
        left, right = span
        for sx, lit in ((left + 2, True), (right - 2, True),
                        (left - 3, False), (right + 3, False)):
            if not 0 <= sx < 256:
                continue
            # skip the hero (an OBJ over BG1) and the caption (BG3)
            if abs(sx - cx) <= 9 and abs(s - cy) <= 9:
                continue
            if bg3_covers(sx, s):
                continue
            base = bg1_colour_at(sx, s)
            want = base if lit else dim(base)
            got = px5(img, sx, anchor + s)
            assert got == want, (
                f"scanline {s}, x={sx} ({'inside' if lit else 'outside'} the "
                f"window at [{left},{right}]): got {got}, expected {want} "
                f"(base {base})")
            checked += 1
    assert checked >= 30, f"only {checked} pixels sampled — coverage too thin"


def test_rows_beyond_the_lantern_are_dark_the_whole_way_across(
        runner, anchor, tmp_path):
    """The empty-window rows: WH0 > WH1 means the WHOLE row is outside.

    This is the hardware fact the table's shape depends on
    (SnesPpuTypes.h:118-122). If it were wrong, those rows would be fully
    LIT instead — the exact opposite — and the table would need per-row
    head/tail arithmetic it does not have.
    """
    enter_room(runner)
    cx, cy = hero_centre(runner)
    img = shoot(runner, tmp_path, "beyond")
    far = [s for s in range(SCANLINES) if abs(s - cy) > RADIUS + 4]
    assert len(far) > 40
    for s in far[::11]:
        for sx in range(4, 252, 37):
            if bg3_covers(sx, s):
                continue
            base = bg1_colour_at(sx, s)
            got = px5(img, sx, anchor + s)
            assert got == dim(base), (
                f"scanline {s} is beyond the lantern (cy={cy}, R={RADIUS}) "
                f"but x={sx} reads {got}, not the dimmed {dim(base)}")


def test_decor_layer_is_clipped_to_the_lantern(runner, anchor, tmp_path):
    """CROSS-LAYER: BG2 must be absent outside the window, present inside.

    A single-layer VRAM read cannot see this bug — BG2's tiles and palette
    can be perfectly uploaded while the layer is visible across the whole
    screen, which is what a wrong W12SEL invert bit or a missing TMW bit
    produces. So the assertion is on the COMPOSITED pixel: at a decor cell
    inside the lantern the decor colour must be on screen, and at one
    outside it the BG1 floor must be, with no decor colour anywhere on that
    cell.
    """
    enter_room(runner)
    cx, cy = hero_centre(runner)
    img = shoot(runner, tmp_path, "decor")
    core = rooms.BG2_COLORS[rooms.DEC_CORE]
    edge = rooms.BG2_COLORS[rooms.DEC_EDGE]
    inside = outside = 0
    for col, row in decor_cells():
        # the diamond's centre pixel, in screen space
        sx = col * TILE + 3
        sy = row * TILE + 3 - VOFS_SKEW
        if not 0 <= sy < SCANLINES:
            continue
        if abs(sx - cx) <= 9 and abs(sy - cy) <= 9:
            continue                        # the hero covers this cell
        if bg3_covers(sx, sy):
            continue                        # the caption covers this cell
        # THREE-WAY, not two. A pixel exactly on the boundary is neither
        # confidently inside nor confidently outside, and calling it
        # "outside" because it failed the inside test is how a correct ROM
        # gets failed: the window bounds are INCLUSIVE, so span[0] itself is
        # lit. Skip the 2-px boundary band rather than guess at it — the
        # edge is asserted precisely, byte for byte, by the iris-table test.
        span = expected_bounds(cx, cy, sy)
        lit = span is not None and span[0] + 2 <= sx <= span[1] - 2
        unlit = span is None or sx < span[0] - 2 or sx > span[1] + 2
        if not lit and not unlit:
            continue
        got = px5(img, sx, anchor + sy)
        if lit:
            assert got == core, (
                f"decor cell ({col},{row}) is INSIDE the lantern but pixel "
                f"({sx},{sy}) reads {got}, not the decor core {core}")
            inside += 1
        else:
            assert got not in (core, edge, dim(core), dim(edge)), (
                f"decor cell ({col},{row}) is OUTSIDE the lantern but pixel "
                f"({sx},{sy}) reads {got} — BG2 is not being clipped")
            assert got == dim(bg1_colour_at(sx, sy)), (
                f"decor cell ({col},{row}) outside the lantern should show "
                f"dimmed BG1, got {got}")
            outside += 1
    assert inside >= 3, f"only {inside} decor cells fell inside the lantern"
    assert outside >= 20, f"only {outside} decor cells fell outside"


# --------------------------------------------------------------------------
# it MOVES — every direction, and idle
# --------------------------------------------------------------------------

@pytest.mark.parametrize("held,dx,dy", [
    ({"left": True}, -1, 0),
    ({"right": True}, +1, 0),
    ({"up": True}, 0, -1),
    ({"down": True}, 0, +1),
    ({"left": True, "up": True}, -1, -1),
    ({"right": True, "down": True}, +1, +1),
    ({}, 0, 0),
])
def test_lantern_follows_the_player_in_every_direction(
        runner, anchor, tmp_path, held, dx, dy):
    """Drive the whole state cycle, not one direction.

    A test that only walks one way locks that way and ships the others
    broken — this repo's streaming engine shipped exactly that. So all four
    axes, both diagonals, and idle; and the assertion is that the LIT PIXELS
    moved with the hero, recomputed against his new OAM position each time.
    """
    enter_room(runner, respawn=True)             # fresh spawn, centred
    before = hero_centre(runner)

    # Deterministic drive: exactly 30 emulated frames of held input, then 4
    # released frames so the final tick lands and OAM commits. The movement
    # and centring assertions below depend on this precondition, so it must
    # not be a wall-clock sleep that host load can shrink to zero emulated
    # frames (that class — the friction log "C1 close-out"). The scene
    # is static after the release, so the free-running OAM read and
    # screenshot below stay sound.
    with runner.frame_stepping():
        runner.frame_step(30, **held)
        runner.frame_step(4)
    after = hero_centre(runner)

    if dx == 0 and dy == 0:
        assert after == before, f"idle moved the hero {before} -> {after}"
    else:
        moved_x = (after[0] - before[0])
        moved_y = (after[1] - before[1])
        assert (moved_x > 0) == (dx > 0) and (moved_x < 0) == (dx < 0), \
            f"x moved {moved_x} for dx={dx}"
        assert (moved_y > 0) == (dy > 0) and (moved_y < 0) == (dy < 0), \
            f"y moved {moved_y} for dy={dy}"

    # the lit region must be centred on where the hero IS now
    cx, cy = after
    img = shoot(runner, tmp_path, "moved")
    left, right = expected_bounds(cx, cy, cy)
    for sx, lit in ((left + 2, True), (right - 2, True),
                    (left - 3, False), (right + 3, False)):
        if not 0 <= sx < 256 or abs(sx - cx) <= 9:
            continue
        base = bg1_colour_at(sx, cy)
        want = base if lit else dim(base)
        assert px5(img, sx, anchor + cy) == want, (
            f"after {held or 'idle'} the lantern is not centred on the hero: "
            f"x={sx} on scanline {cy} (span [{left},{right}]) reads "
            f"{px5(img, sx, anchor + cy)}, expected {want}")


def test_walking_into_a_corner_clips_the_lantern_against_the_edge(
        runner, anchor, tmp_path):
    """The screen edges — where the compact table form would have needed
    special cases, and where the spec requires the player to be able to go."""
    enter_room(runner, respawn=True)
    # 120 EMULATED frames of walk guarantee arrival at the wall clamp under
    # any host load — the exact-corner assertion below fails on an under-run,
    # which is what a wall-clock sleep permits (that class). Then 4
    # released frames so the final tick lands and OAM commits.
    with runner.frame_stepping():
        runner.frame_step(120, left=True, up=True)
        runner.frame_step(4)
    cx, cy = hero_centre(runner)
    assert cx == 8 + 8 and cy == 8 + 8, (
        f"the wall clamp did not hold the hero at the corner: ({cx},{cy})")
    img = shoot(runner, tmp_path, "corner")
    # the lantern is half off-screen: rows above cy-? still exist, and every
    # row that has no lantern at all must be dark across its full width
    for s in range(cy + RADIUS + 6, SCANLINES, 23):
        for sx in range(4, 252, 61):
            if bg3_covers(sx, s):
                continue
            base = bg1_colour_at(sx, s)
            assert px5(img, sx, anchor + s) == dim(base), (
                f"corner frame: scanline {s} x={sx} is beyond the lantern "
                f"but is not dimmed")
    # ...and the lit span on the hero's own scanline is clamped at x=0
    left, right = expected_bounds(cx, cy, cy)
    assert left == 0, f"expected the span to clamp at 0, got {left}"
    assert px5(img, 1, anchor + cy) == bg1_colour_at(1, cy), \
        "the leftmost pixel of the hero's scanline should be lit"


# --------------------------------------------------------------------------
# the disarm path — why the title scene exists
# --------------------------------------------------------------------------

def test_returning_to_the_title_leaves_no_window_residue(
        runner, anchor, tmp_path):
    """A lantern left armed would dim a scene that never wrote a window.

    The title's text palette is fixed and known, so the assertion is exact:
    its white must be $7FFF and its backdrop $1000, not those minus COLDATA.
    """
    enter_room(runner, respawn=True)
    back_to_title(runner)
    img = shoot(runner, tmp_path, "back_at_title")

    seen = {img.getpixel((x, anchor + y))
            for x in range(256) for y in range(SCANLINES)}
    want_white = bgr_to_rgb5(0x7FFF)
    want_back = bgr_to_rgb5(0x1000)
    seen5 = {tuple(c >> 3 for c in p) for p in seen}
    assert want_white in seen5, (
        f"the title's white ({want_white}) is not on screen — it renders as "
        f"{dim(want_white)} if the room's colour math leaked out")
    assert dim(want_white) not in seen5, \
        "a dimmed white is on the title screen: colour math survived the exit"
    assert want_back in seen5, (
        f"the title backdrop ({want_back}) is not on screen; dimmed would be "
        f"{dim(want_back)}")
    # and the sprites the room armed are parked again — the hero AND the
    # this slice additions (pip 0 stands in for the pinned HUD row)
    oam = runner.read_bytes(MemoryType.SnesSpriteRam, HERO_SLOT * 4, 4)
    assert oam[1] == 0xF0, f"the hero was left on screen (Y={oam[1]:#04x})"
    pip0 = runner.read_bytes(MemoryType.SnesSpriteRam, 0, 4)
    assert pip0[1] == 0xF0, f"pip 0 was left on screen (Y={pip0[1]:#04x})"


def test_caption_is_never_dimmed_inside_or_outside_the_lantern(
        runner, anchor, tmp_path):
    """BG3 is excluded from colour math, so the caption is full brightness.

    The complement of the dimming tests, and not redundant with them: those
    prove that the layers CGADSUB names get darker, this proves that a layer
    it does not name is untouched. A CGADSUB with every bit set would pass
    every other test in this file and fail this one — and it would look
    wrong on screen, because the room's only readable text would fade with
    the lantern.

    Both states are exercised: the caption sits at the top of the screen, so
    it is outside the lantern when the hero is centred and inside it when he
    walks into the top-left corner.
    """
    white = bgr_to_rgb5(0x7FFF)

    def caption_whites(img):
        return sum(1 for sx in range(CAPTION_COL * TILE,
                                     (CAPTION_COL + len(CAPTION)) * TILE)
                   for sy in range(CAPTION_ROW * TILE - VOFS_SKEW,
                                   (CAPTION_ROW + 1) * TILE - VOFS_SKEW)
                   if px5(img, sx, anchor + sy) == white)

    enter_room(runner, respawn=True)             # caption far from the light
    far = caption_whites(shoot(runner, tmp_path, "caption_far"))
    assert far > 100, (
        f"only {far} full-white caption pixels with the lantern far away — "
        f"the caption is being dimmed, so CGADSUB names BG3")

    # Walk the light onto the caption — deterministically, so the near-state
    # half of the coverage is guaranteed rather than load-dependent: under a
    # wall-clock walk an under-run leaves the lantern short of the caption
    # and the near == far equality passes without exercising the near state.
    with runner.frame_stepping():
        runner.frame_step(120, left=True, up=True)
        runner.frame_step(4)
    near = caption_whites(shoot(runner, tmp_path, "caption_near"))
    assert near == far, (
        f"the caption changed brightness when the lantern reached it "
        f"({far} white pixels before, {near} after) — BG3 must be identical "
        f"in both states")


# --------------------------------------------------------------------------
# what the lantern costs, MEASURED
# --------------------------------------------------------------------------

MC_PER_FRAME = 357368            # allocator/substrate.toml [frame.ntsc]
IRIS_TAB = 0x04A4                # the iris_tab claim (build/rm/*.inc)
IRIS_FIRST_DATA = IRIS_TAB + 1                  # row 0's WH0
IRIS_LAST_DATA = IRIS_TAB + 256 + 2 * 96 + 1    # row 223's WH1
SM_FRAME = 0x04A0                # scene_mgr's frame counter


def _clock_at_write(runner, addr, max_frames=300):
    """Master clock the next time the CPU writes `addr`, or None.

    The budget is EMULATED frames, so a None means "the CPU did not write
    this in N frames of the ROM's own time" — a claim about the ROM. The
    wall deadline it replaced meant "the CPU did not write this in N seconds
    of the HOST's time", which on a loaded box is a much shorter stretch of
    ROM time, and the difference is a red test with nothing wrong in the
    kernel. Measured: this node went red at rep 2 of 10 under four CPU
    burners before the conversion.

    THE BREAKPOINT IS THE STOPWATCH; THE WRITE COUNTER IS THE ORACLE. A True
    out of run_to_break does not mean a breakpoint matched — it means
    execution was observed stopped with the clock moved, and Mesen's
    `IsExecutionStopped()` is `_executionStopped || _emu->IsThreadPaused()`,
    whose second term also covers the EmulatorLock / DebugBreakHelper pauses
    that briefly halt a free-running emulator. Catch one of those and
    `_settle_at_break` then Steps the machine to a real stop, so the caller is
    handed a plausible master clock for a write that never happened. Measured
    at ~2.6% of idle reps here, which is exactly the shape of this node's CI
    flake. So the breakpoint stays — it is what parks the CPU AT the
    store, which is the only way to time the rebuild — but whether a write
    happened is asked of `write_count`, the memory system's own tally for the
    byte. A reported break with the counter unmoved is not a write, and the
    watch resumes on what is left of the budget.

    `addr` is a low-mirror WRAM address, so the same number is both the
    SnesMemory CPU address the breakpoint names and the SnesWorkRam offset the
    counter indexes. They are not the same claim in general — the counter is
    bank-agnostic — and here that is a feature: the room is the only scene
    running, and its rebuild is the only writer of these bytes.
    """
    before = runner.write_count(MemoryType.SnesWorkRam, addr)
    runner.set_breakpoints([(MemoryType.SnesMemory, addr, "write")])
    start = runner.ppu_frame_count()
    while True:
        left = max_frames - (runner.ppu_frame_count() - start)
        if left <= 0:
            return None
        broke = runner.run_to_break(max_frames=left)
        if runner.write_count(MemoryType.SnesWorkRam, addr) > before:
            return runner.snes_state_snapshot().master_clock
        if not broke:
            return None
        # Stopped, but the byte is untouched: a thread pause wearing a
        # breakpoint's clothes. Keep watching.


def test_table_rebuild_cost_is_measured_not_estimated(runner):
    """The per-frame cost of rebuilding all 224 rows, in master cycles.

    AGENTS.md forbids estimating a cycle count, and the fixed-table design
    (window_iris/feature.toml) trades bytes and cycles for the absence of
    screen-edge special cases — so the cost is exactly the number that has
    to be on the record for that trade to be a decision rather than a hope.

    METHOD, and why it needs no probe ROM. Two write breakpoints, on the
    FIRST and LAST data bytes of the table. Between those two stores the CPU
    does nothing but the rebuild, so the master-clock difference IS the
    rebuild — measured on the shipped binary rather than on a copy of the
    kernel, which is the property the col_map measurement went to some
    trouble to get.

    Reduced with min() over several frames: a frame in which the NMI fires
    mid-rebuild carries the NMI's cost too, and the minimum is the sample
    where it did not. Both ends are printed so the NMI's contribution stays
    visible rather than being quietly discarded.

    UNDER MOVEMENT, and that is not incidental: the kernel now skips the
    rebuild entirely when neither centre coordinate moved (the idle-skip), so a
    standing hero produces no table writes and nothing to measure. What is
    being measured is a rebuild, which only happens when the lantern moves —
    test_idle_frame_skips_the_rebuild asserts the other half.
    """
    enter_room(runner, respawn=True)
    samples = []
    runner.set_input(0, left=True, up=True)   # keep the lantern moving
    runner.debug_break()
    try:
        for _ in range(8):
            t0 = _clock_at_write(runner, IRIS_FIRST_DATA)
            t1 = _clock_at_write(runner, IRIS_LAST_DATA)
            if t0 is not None and t1 is not None and 0 < t1 - t0:
                samples.append(t1 - t0)
    finally:
        runner.set_breakpoints([])
        runner._frame_stepping = True
        runner.debug_resume(clear_input=False)
        runner.set_input(0)

    assert len(samples) >= 3, f"only {len(samples)} usable samples: {samples}"
    cost, worst = min(samples), max(samples)
    share = 100.0 * cost / MC_PER_FRAME
    print(f"\niris table rebuild: {cost} mc/frame ({share:.2f}% of the "
          f"{MC_PER_FRAME} mc NTSC frame); worst sample {worst} mc "
          f"(includes an NMI); n={len(samples)}")
    # A REGRESSION GUARD around the measured figure, not a budget claim.
    # Measured at 74,458 mc = 20.84% of the frame (12,410 CPU cycles FastROM
    # at mc/6, 9,307 at mc/8 — substrate.toml's misnamed pin documents the
    # conversion). Was 118,454 mc = 33.1% before the three-range fill and the
    # 16-bit LUT; the guard moved down with it, because a guard left at the
    # old value would silently permit the whole regression back.
    assert cost < MC_PER_FRAME // 4, (
        f"the rebuild costs {cost} mc ({share:.1f}% of a frame), past the "
        f"25% guard around its measured 20.8% — the kernel got materially "
        f"more expensive")


def test_idle_frame_skips_the_rebuild(runner):
    """The idle-skip half of the optimisation, on the WRITES not on a flag.

    A stationary lantern's table is already exactly what the frame would
    write, so the rebuild is skipped. Asserted by watching for a WRITE to the
    table across several frames of no input: the observable claim is "the CPU
    does not touch these bytes", and a breakpoint on the store is the only
    thing that actually says so. Reading the table back would pass either way,
    since a redundant rebuild produces identical bytes — which is precisely
    the indirect-evidence trap here.

    Then it moves and requires the write to come back, so a kernel that had
    stopped rebuilding ALTOGETHER could not pass this pair.
    """
    enter_room(runner, respawn=True)
    # The stationary precondition is established in EMULATED frames, not
    # wall-clock. debug_break parks at the canonical scanline (the frame's
    # game update complete); frame_step then latches all-buttons-released and
    # advances exactly 6 frames, so any final walk-tick rebuild has landed
    # before the breakpoint arms — under any host load. The wall-clock
    # predecessor (set_input(0) + run_frames(6)) let a loaded CI runner lag
    # the sleep, and the breakpoint legitimately caught the released walk's
    # final rebuild (the friction log "C1 close-out — the
    # CI #169 flake").
    runner.debug_break()
    runner.frame_step(6)                      # 6 emulated idle frames, exact
    try:
        idle = _clock_at_write(runner, IRIS_FIRST_DATA, max_frames=90)
        assert idle is None, (
            "the table was rewritten while the lantern was stationary — the "
            "idle-skip is not firing, so standing still pays a full rebuild")
        # ...and the skip must not be permanent: moving rebuilds again. The
        # timed-out idle probe left the machine free-running; debug_break
        # re-parks it, then frame_step latches the walk for exactly 4
        # emulated frames before the write breakpoint re-arms.
        runner.set_breakpoints([])
        runner.debug_break()
        runner.frame_step(4, left=True, up=True)
        moving = _clock_at_write(runner, IRIS_FIRST_DATA, max_frames=180)
        assert moving is not None, (
            "moving the lantern did not rebuild the table — the idle-skip is "
            "stuck on, and the window would lag the hero")
    finally:
        runner.set_breakpoints([])
        runner._frame_stepping = True
        runner.debug_resume(clear_input=False)
        runner.set_input(0)


def test_the_room_holds_60fps(runner):
    """Cadence, the invariant the cost number exists to protect.

    A per-frame figure only matters if the loop actually delivers a frame
    per frame. Driven under movement in both axes, because the rebuild runs
    every tick and a diagonal walk is the busiest the room gets.

    The band is 60..61, not exactly 60: the counter is incremented in the
    NMI and the two reads bracket the stepped run from the main thread, so
    one boundary can legitimately land either side of a VBlank. What would
    be a real defect is the counter advancing by FEWER than the frames
    stepped — that is a dropped frame, and it is what this catches.
    """
    enter_room(runner, respawn=True)
    for held in ({}, {"right": True, "down": True}, {"left": True, "up": True}):
        runner.set_input(0, **held)
        before = runner.read_u16(MemoryType.SnesWorkRam, SM_FRAME)
        runner.frame_step(60)
        after = runner.read_u16(MemoryType.SnesWorkRam, SM_FRAME)
        runner.set_input(0)
        assert 60 <= after - before <= 61, (
            f"under {held or 'idle'} the game delivered {after - before} "
            f"frames across 60 stepped PPU frames — the loop is missing "
            f"frames, so the room does not hold 60 fps")
