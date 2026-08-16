"""breaker — the paddle-and-ball rail, end to end on the emulator.

THE TEST SURFACE IS THE RENDERED OUTPUT, EVERYWHERE (CLAUDE.md rule 2).
"A brick broke" is asserted as *that BG1 tilemap cell in VRAM is now tile 0*,
not as "a counter changed". "The paddle moved" is asserted as *the OAM X bytes
the PPU will read*, not as "US_PX changed". "GAME OVER is showing" is asserted
as *the glyph tiles sitting in BG3's tilemap*. Where a DP word appears at all
it is either NAVIGATION (get the machine into the state under test) or it is
asserted BESIDE the output region it is supposed to explain — never instead of
it. The one exception is scene_mgr's own ES_SM_CTL, used to know which scene is
live; that is an engine fact, and it is never the thing a test claims.

The case list is the rail's own done-condition block, written to be
emulator-verifiable. Each test below names the condition it discharges.

STATE-CYCLE COVERAGE, not snapshots (AGENTS.md "Test discipline"): the module
drives WAIT -> PLAY -> brick break -> paddle rally -> ball lost -> WAIT ->
GAME OVER -> title -> PLAY, in that order, and asserts the render at each
edge. A rail tested only on its opening frame ships its endings broken.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "breaker.sfc"
_JMAP = json.loads((SUPERFORGE / "build" / "bk" / "symbol_map.json").read_text())


def _sym(name, scene=None):
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — the allocator moved it?")


# Addresses are ASKED FOR, never hardcoded: this file reads the same map the
# ROM was assembled against, so a re-pack moves the test with the code.
SM_CTL = _sym("ES_SM_CTL")["start"]
BRK_MAP = _sym("ES_V_BRK_MAP", "play")["start"]         # VRAM WORD address
TXT_MAP = _sym("ES_V_TEXT_MAP", "play")["start"]
TITLE_TXT_MAP = _sym("ES_V_TEXT_MAP", "title")["start"]
BRK_Q = _sym("ES_BRK_Q", "play")["start"]               # WRAM ($7E) offset
OAM_PADDLE = _sym("ES_O_PADDLE", "play")["start"]
OAM_BALL = _sym("ES_O_BALL", "play")["start"]
DP = {k: _sym("US_" + k.upper(), "play")["start"]
      for k in ("px", "bx", "by", "vx", "vy", "score", "balls", "bricks",
                "gstate")}

SCENE_TITLE, SCENE_PLAY = 0, 1
W, V, O = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
           MemoryType.SnesSpriteRam)

# --- the arena's declared shape (game/breaker/breaker.inc + breaker_bg.asm) --
# Restated here as an ORACLE, deliberately independent of the ROM: these are
# the numbers the rail promises, and the tests check the machine against them
# rather than against whatever the machine happens to hold.
ROW_CEIL, ROW_WALL_LO, ROW_WALL_HI = 2, 3, 28
ROW_BRICK_LO, ROW_BRICK_HI = 5, 11
COL_HI = 31
BRICK_TOTAL = (ROW_BRICK_HI - ROW_BRICK_LO) * (COL_HI - 1)      # 6 x 30 = 180
TILE_EMPTY, TILE_WALL = 0, 1
BRICK_TILES = (2, 3, 4, 5)
PADDLE_Y, PADDLE_MIN_X, PADDLE_MAX_X, PADDLE_W = 200, 8, 224, 24
PARK_Y = 240
HUD_ROW, HUD_SCORE_C, HUD_BALLS_C = 1, 2, 20
MSG_ROW0, MSG_COL, MSG_W = 14, 10, 11


# --- the RENDER oracle, built from the asset generator ----------------------
# Importing the generator rather than restating its numbers is deliberate: the
# generator IS the declaration of what the arena's colours are, so a test that
# re-typed them could agree with itself while the ROM shipped something else.
sys.path.insert(0, str(SUPERFORGE / "tools"))
import gen_breaker_assets as _GEN                                    # noqa: E402

_GRAD = _GEN.grad_tabs()


def _chan(word, i):
    """Channel i (0=R 1=G 2=B) of a 15-bit BGR555 word."""
    return (word >> (i * 5)) & 31


def _snes8(c):
    """5-bit channel -> the 8-bit value the renderer produces.

    BIT REPLICATION, `(c << 3) | (c >> 2)`, not `round(c * 255/31)`. The two
    agree everywhere except a handful of low values (3 -> 24 vs 25), and this
    file found the difference the honest way: a green brick came back one
    count low in R and the arithmetic version was the thing that was wrong.
    """
    return (c << 3) | (c >> 2)


def _ramp(scanline):
    """The (R,G,B) intensity rgb_gradient adds on this scanline, read out of
    the COLDATA tables the ROM actually ships."""
    return tuple(_GRAD[i * _GEN.TOTAL_LINES + scanline] & 31 for i in range(3))


def _near_scanline(px, x, y, want, slack=1):
    """`want` on scanline y, allowing +-`slack` lines.

    The HDMA head entry's exact line-0 phase is a MEASURED property of the
    hardware, not a chosen one (rgb_gradient.asm says so), and the ramp moves
    by at most one intensity step per line — so the slack is over WHICH LINE
    the table byte lands on, never over the value.
    """
    return any(px(x, yy) == want
               for yy in range(y - slack, y + slack + 1))


# =============================================================================
# harness
# =============================================================================

def _tile(r, row, col, base=None):
    """One BG tilemap cell, as a tile id — the PPU's own input."""
    base = BRK_MAP if base is None else base
    b = r.read_bytes(V, (base + row * 32 + col) * 2, 2)
    return (b[0] | b[1] << 8) & 0x3FF


def _map_words(r, base):
    raw = r.read_bytes(V, base * 2, 1024 * 2)
    return [(raw[i * 2] | raw[i * 2 + 1] << 8) for i in range(1024)]


def _text(r, row, col, n, base=None):
    """BG3 cells decoded back to ASCII. bg_text's mapping is glyph = ascii-$20
    and glyph n IS tile n, so this inverts the renderer exactly.

    `base` defaults to the PLAY scene's tilemap. The two scenes' bg_text
    claims land on different VRAM pages (title 1024, play 3072) and reading
    one through the other's base returns font CHR as if it were text — which
    is exactly the mojibake the first run of this file produced."""
    base = TXT_MAP if base is None else base
    raw = r.read_bytes(V, (base + row * 32 + col) * 2, n * 2)
    return "".join(chr(((raw[i * 2] | raw[i * 2 + 1] << 8) & 0x3FF) + 0x20)
                   for i in range(n))


def _oam(r, slot):
    """One OAM entry as (x_low, y, tile, attr) — the bytes the PPU reads."""
    return tuple(r.read_bytes(O, slot * 4, 4))


def _oam_hi(r, slot):
    """The sprite's 2 bits of the hi table: bit 0 = X9, bit 1 = size."""
    byte = r.read_bytes(O, 512 + slot // 4, 1)[0]
    return (byte >> (slot % 4) * 2) & 3


def _dp(r, name):
    return r.read_u16(W, DP[name])


def _scene(r):
    return r.read_bytes(W, SM_CTL, 3)[0]


def _phase(r):
    return r.read_bytes(W, SM_CTL, 3)[2]


def _settle(r, want_scene, budget=240):
    """Advance until scene_mgr has landed on `want_scene` and stopped fading."""
    for _ in range(budget):
        if _scene(r) == want_scene and _phase(r) == 0:
            return
        r.frame_step(1)
    raise AssertionError(f"scene {want_scene} never went live (phase machine "
                         f"stuck at scene {_scene(r)} phase {_phase(r)})")


def _press_start(r):
    r.frame_step(2, start=True)
    r.frame_step(1)


def _goto_play(r):
    """Navigation, not assertion: leave the machine in a fresh play scene."""
    if _scene(r) != SCENE_TITLE:
        _press_start(r)
        _settle(r, SCENE_TITLE)
    _press_start(r)
    _settle(r, SCENE_PLAY)


def _shot(r, tmp_path, name):
    """A render, with the image row that IS scanline 0.

    Same letterbox anchor microzero's gradient suite established: the border
    is black and the 224-line content span has no black row inside it, so the
    first non-black row is scanline 0.
    """
    path = tmp_path / f"{name}.png"
    r.take_screenshot(str(path), settle_frames=2)
    img = Image.open(path).convert("RGB")
    w, h = img.size
    top = next(y for y in range(h)
               if any(img.getpixel((x, y)) != (0, 0, 0) for x in range(w)))
    return img, top


@pytest.fixture(scope="module")
def r():
    assert ROM.exists(), f"{ROM} missing — run `make breaker`"
    run = MesenRunner()
    run.boot_rom(str(ROM), frames=90)
    run.debug_break()            # deterministic frame-stepping from here on
    yield run
    run.stop()


# =============================================================================
# 1. it boots, and the arena is really there
#    done-condition: "walls + 180 bricks visible on BG1 (VRAM + rendered
#    pixels), HUD labels + counters printed on BG3"
# =============================================================================

def test_title_boots_and_renders_its_own_text(r):
    assert _scene(r) == SCENE_TITLE, "the boot scene is the title"
    _settle(r, SCENE_TITLE)
    assert _text(r, 8, 10, 12, TITLE_TXT_MAP) == "BRICK BUSTER"
    assert _text(r, 14, 10, 11, TITLE_TXT_MAP) == "PRESS START"


def test_break_queue_is_defined_before_its_first_reader(r):
    """Power-on fidelity (rule 5). sm_nmi_hook commits breaker_bg's cell queue
    on EVERY frame of EVERY scene, so its count byte has a reader from frame
    one. Random DRAM there would have the title's first VBlank writing garbage
    words to garbage VRAM addresses."""
    assert r.read_bytes(W, BRK_Q, 1)[0] == 0


def test_arena_tilemap_is_the_declared_level(r):
    """The BG1 tilemap in VRAM, cell for cell, against the declared geometry —
    not a spot check and not a hash of the ROM's own output."""
    _goto_play(r)
    m = [w & 0x3FF for w in _map_words(r, BRK_MAP)]

    def at(row, col):
        return m[row * 32 + col]

    assert all(at(ROW_CEIL, c) == TILE_WALL for c in range(32)), \
        "the ceiling is a wall right across"
    for row in range(ROW_WALL_LO, ROW_WALL_HI):
        assert at(row, 0) == TILE_WALL and at(row, COL_HI) == TILE_WALL, \
            f"row {row} is missing a side wall"
    # the pit is OPEN — this is the hole the ball is lost through, and a
    # closed one would make losing a ball impossible
    assert at(ROW_WALL_HI, 0) == TILE_EMPTY
    assert all(at(31, c) == TILE_EMPTY for c in range(32))

    bricks = [(row, col) for row in range(32) for col in range(32)
              if at(row, col) in BRICK_TILES]
    assert len(bricks) == BRICK_TOTAL, f"expected {BRICK_TOTAL} bricks"
    assert {row for row, _ in bricks} == set(range(ROW_BRICK_LO, ROW_BRICK_HI))
    assert {col for _, col in bricks} == set(range(1, COL_HI))
    # the rainbow: each brick row is ONE colour, and consecutive rows differ
    per_row = [at(row, 1) for row in range(ROW_BRICK_LO, ROW_BRICK_HI)]
    for i, row in enumerate(range(ROW_BRICK_LO, ROW_BRICK_HI)):
        assert {at(row, c) for c in range(1, COL_HI)} == {per_row[i]}, \
            f"brick row {row} is not one colour"
    assert all(a != b for a, b in zip(per_row, per_row[1:])), \
        "adjacent brick rows must differ — that is what makes it a rainbow"


def test_arena_renders_walls_bricks_and_the_night_ramp(r, tmp_path):
    """The composited picture, against the DECLARED colours, per scanline.

    A VRAM-only assertion cannot tell "BG1 holds the right tiles" from "BG2 is
    covering BG1" — the layer-priority failure this project has a
    lessons-learned entry about. So this reads pixels, and it checks them
    against an oracle built from the ASSET GENERATOR rather than from the
    render: palette entry + that scanline's COLDATA byte. Getting this right
    requires the palette, the tilemap, the layer order, CGADSUB and three
    indirect HDMA channels to ALL be correct at once, which is why one
    assertion covers so much.
    """
    _goto_play(r)
    img, top = _shot(r, tmp_path, "arena")

    def px(x, y):
        return img.getpixel((x, top + y))

    def expect(base_word, y):
        """The colour scanline y must show for a pixel of `base_word`."""
        add = _ramp(y)
        return tuple(_snes8(min(31, _chan(base_word, i) + add[i]))
                     for i in range(3))

    # --- the side walls: grey BG1, plus the wash BG1 is a colour-math target
    for y in (ROW_BRICK_LO * 8 + 4, 120, 200):
        for x in (4, 252):
            assert _near_scanline(px, x, y, expect(_GEN.BG_PAL[1], y)), \
                f"wall pixel ({x},{y}) is {px(x, y)}, want ~{expect(_GEN.BG_PAL[1], y)}"

    # --- the brick band: four DISTINCT hues on screen, each one the declared
    # base colour of its row plus that row's wash
    hues = []
    for i, row in enumerate(range(ROW_BRICK_LO, ROW_BRICK_HI)):
        y = row * 8 + 4
        want = expect(_GEN.BG_PAL[_GEN.BRICKS[i % 4][0]], y)
        got = px(128 + 3, y)                    # inside the 7 px face
        assert _near_scanline(px, 128 + 3, y, want), \
            f"brick row {row} renders {got}, want ~{want}"
        hues.append(want)
    assert len(set(hues)) >= 4, "the wall must read as a rainbow, not one hue"

    # --- the backdrop: BG2's bed plus the wash, read through the holes in the
    # arena well clear of the bricks, the HUD and the paddle
    for y in (100, 140, 180):
        assert _near_scanline(px, 128, y, expect(_GEN.SKY_PAL[1], y)), \
            f"backdrop at y={y} is {px(128, y)}, want ~{expect(_GEN.SKY_PAL[1], y)}"
    blues = [px(128, y)[2] for y in (100, 140, 180)]
    assert blues[0] > blues[-1], \
        f"the wash must DARKEN downward, got blues {blues}"


def test_hud_labels_and_counters_are_printed(r):
    _goto_play(r)
    assert _text(r, HUD_ROW, HUD_SCORE_C, 5) == "SCORE"
    assert _text(r, HUD_ROW, HUD_BALLS_C, 5) == "BALLS"
    assert _text(r, HUD_ROW, 8, 4) == "0000", "the opening score, printed"
    assert _text(r, HUD_ROW, 26, 1) == "3", "three balls, printed"
    assert _text(r, MSG_ROW0, MSG_COL, MSG_W).strip() == "PRESS A"


# =============================================================================
# 2. the paddle, and the ball riding it
#    done-condition: "d-pad moves the paddle BOTH directions (OAM + pixels),
#    clamped to the walls; in WAIT the ball rides the paddle"
# =============================================================================

def test_paddle_moves_both_directions_in_oam(r):
    """BOTH directions, because a one-direction test locks one and ships the
    other broken (AGENTS.md's state-cycle rule applied to an axis)."""
    _goto_play(r)
    home = _oam(r, OAM_PADDLE)[0]
    r.frame_step(10, left=True)
    left = _oam(r, OAM_PADDLE)[0]
    r.frame_step(10, right=True)
    right = _oam(r, OAM_PADDLE)[0]
    assert left < home, f"Left did not move the sprite: {home} -> {left}"
    assert right > left, f"Right did not move the sprite: {left} -> {right}"


def test_paddle_is_three_segments_eight_pixels_apart(r):
    """24 px of bat out of an 8x8 tile — assert the three OAM entries really
    are adjacent and really are the same tile, since a wrong tile or a wrong
    gap renders as a broken bat rather than as a failure anywhere else."""
    _goto_play(r)
    seg = [_oam(r, OAM_PADDLE + i) for i in range(3)]
    xs = [s[0] for s in seg]
    assert xs[1] == xs[0] + 8 and xs[2] == xs[0] + 16, f"segments at {xs}"
    assert all(s[1] == PADDLE_Y for s in seg), "all three sit on one row"
    assert len({s[2] for s in seg}) == 1, "one tile, drawn three times"
    assert all(_oam_hi(r, OAM_PADDLE + i) & 2 == 0 for i in range(3)), \
        "every sprite here is 8x8: the hi table's size bits must stay clear"


def test_paddle_clamps_to_both_walls_in_oam(r):
    _goto_play(r)
    r.frame_step(120, left=True)
    assert _oam(r, OAM_PADDLE)[0] == PADDLE_MIN_X, "clamped off the left wall"
    r.frame_step(150, right=True)
    assert _oam(r, OAM_PADDLE)[0] == PADDLE_MAX_X, "clamped off the right wall"
    assert _oam(r, OAM_PADDLE + 2)[0] == PADDLE_MAX_X + 16 <= 248, \
        "the rightmost segment stays inside the right wall"


def test_in_wait_the_ball_rides_the_paddle(r):
    _goto_play(r)
    for buttons in ({"left": True}, {"right": True}, {}):
        r.frame_step(12, **buttons)
        r.frame_step(1)                     # OAM lags the state by one frame
        paddle_x = _oam(r, OAM_PADDLE)[0]
        ball = _oam(r, OAM_BALL)
        assert ball[0] == (paddle_x + (PADDLE_W - 8) // 2) & 0xFF, \
            f"the ball is not centred on the bat: {ball[0]} vs {paddle_x}"
        assert ball[1] == PADDLE_Y - 8, "...and not sitting on top of it"


# =============================================================================
# 3. launch, bounce, break
#    done-condition: "A launches (state 0 -> 1, ball rises); the ball bounces
#    off walls and paddle, staying inside the arena; brick cells it hits go to
#    tile 0 in VRAM, BRICKS drops, SCORE rises and the printed counter
#    reprints"
# =============================================================================

def test_a_launches_and_the_ball_rises_in_oam(r):
    _goto_play(r)
    assert _dp(r, "gstate") == 0
    y0 = _oam(r, OAM_BALL)[1]
    r.frame_step(2, a=True)
    assert _dp(r, "gstate") == 1, "A moves WAIT -> PLAY"
    r.frame_step(20)
    y1 = _oam(r, OAM_BALL)[1]
    assert y1 < y0 - 20, f"the ball should have risen: {y0} -> {y1}"
    assert _text(r, MSG_ROW0, MSG_COL, MSG_W).strip() == "", \
        "launching wipes the prompt off BG3"


def test_a_brick_hit_clears_that_cell_in_vram_and_reprints_the_score(r):
    """THE headline behaviour, asserted on the two regions it produces: the
    BG1 tilemap cell the PPU reads, and the BG3 cells the score is printed
    into. A counter-only assertion would pass with the tilemap untouched --
    which is a bricks-you-can-still-bounce-off bug, invisible to it."""
    _goto_play(r)
    before = [w & 0x3FF for w in _map_words(r, BRK_MAP)]
    assert _text(r, HUD_ROW, 8, 4) == "0000"
    r.frame_step(2, a=True)
    for _ in range(240):                    # play until the first brick falls
        r.frame_step(1)
        if _dp(r, "bricks") < BRICK_TOTAL:
            break
    else:
        pytest.fail("the ball never reached the wall in 240 frames")
    r.frame_step(4)                         # let the VBlank commit land
    after = [w & 0x3FF for w in _map_words(r, BRK_MAP)]

    changed = [i for i in range(1024) if before[i] != after[i]]
    assert changed, "a brick was counted but no VRAM cell changed"
    for i in changed:
        assert before[i] in BRICK_TILES, \
            f"cell {divmod(i, 32)} was {before[i]}, not a brick — a wall broke"
        assert after[i] == TILE_EMPTY, \
            f"cell {divmod(i, 32)} went to {after[i]}, not empty"
    assert len(changed) == BRICK_TOTAL - _dp(r, "bricks"), \
        "the tilemap and the counter disagree about how many bricks fell"

    # ...and the printed score followed. It is packed BCD, so hex4's nibble
    # walk renders it as four decimal digits.
    for _ in range(30):
        r.frame_step(1)
        if _text(r, HUD_ROW, 8, 4) != "0000":
            break
    printed = _text(r, HUD_ROW, 8, 4)
    assert printed.isdigit() and int(printed) == 10 * len(changed), \
        f"printed score {printed!r} does not match {len(changed)} brick(s)"


def test_the_ball_stays_inside_the_arena(r):
    """A rally of 240 frames with a bot on the bat: every frame, the ball's
    OAM position must be inside the walls. Reflection bugs show up here as a
    ball outside the box, which no single-frame snapshot would catch."""
    _goto_play(r)
    r.frame_step(2, a=True)
    for _ in range(240):
        px, bx = _dp(r, "px"), _dp(r, "bx")
        r.frame_step(1, right=(px + 12 < bx + 4), left=(px + 12 > bx + 4))
        x, y, _tile_id, _attr = _oam(r, OAM_BALL)
        assert _oam_hi(r, OAM_BALL) & 1 == 0, "X9 set: the ball left the screen"
        assert 8 <= x <= 248 - 8, f"ball x={x} is inside a side wall"
        assert (ROW_CEIL + 1) * 8 <= y <= PARK_Y, f"ball y={y} left the arena"


def test_a_paddle_bot_keeps_the_rally_alive(r):
    """done-condition: "a closed-loop paddle bot keeps the rally alive (paddle
    bounce works)". Without a working bounce the ball is lost inside ~120
    frames, so surviving 300 with the counter untouched IS the bounce."""
    _goto_play(r)
    r.frame_step(2, a=True)
    balls0 = _dp(r, "balls")
    for _ in range(300):
        px, bx = _dp(r, "px"), _dp(r, "bx")
        r.frame_step(1, right=(px + 12 < bx + 4), left=(px + 12 > bx + 4))
    assert _dp(r, "balls") == balls0, "the bot dropped a ball — no bounce"
    assert _dp(r, "bricks") < BRICK_TOTAL, "a live rally must break bricks"
    assert _oam(r, OAM_BALL)[1] < PARK_Y, "the ball is still in play"


# =============================================================================
# 4. the endings, and the way back
#    done-condition: "losing a ball returns to WAIT with BALLS down one;
#    losing the last ball -> state 2 + GAME OVER rendered; Start rebuilds the
#    wall and resets the counters (all 180 bricks back in VRAM)"
# =============================================================================

def _lose_one_ball(r):
    """Launch and park the bat in the corner so the ball falls through."""
    n = _dp(r, "balls")
    r.frame_step(2, a=True)
    for _ in range(400):
        r.frame_step(1, left=True)
        if _dp(r, "balls") < n:
            return
    pytest.fail("a parked bat still did not lose the ball in 400 frames")


def test_losing_a_ball_returns_to_wait_and_reprints_the_counter(r):
    _goto_play(r)
    assert _text(r, HUD_ROW, 26, 1) == "3"
    _lose_one_ball(r)
    assert _dp(r, "gstate") == 0, "a lost ball goes back to WAIT"
    r.frame_step(1)
    ball, paddle_x = _oam(r, OAM_BALL), _oam(r, OAM_PADDLE)[0]
    assert ball[1] == PADDLE_Y - 8 and ball[0] == (paddle_x + 8) & 0xFF, \
        "the next ball is back on the bat"
    # The counters go first and settle in a frame or two; the prompt block
    # follows at one cell per frame (brk_hud's declared priority), so the
    # prompt needs its own wait rather than riding on the counter's.
    for _ in range(40):
        r.frame_step(1)
        if _text(r, HUD_ROW, 26, 1) == "2":
            break
    assert _text(r, HUD_ROW, 26, 1) == "2", "BALLS did not reprint on BG3"
    for _ in range(4 * MSG_W):
        r.frame_step(1)
        if _text(r, MSG_ROW0, MSG_COL, MSG_W).strip() == "PRESS A":
            break
    assert _text(r, MSG_ROW0, MSG_COL, MSG_W).strip() == "PRESS A", \
        "the next ball's prompt is not back on BG3"


def test_the_last_ball_ends_the_round_and_renders_game_over(r):
    _goto_play(r)
    for _ in range(3):
        _lose_one_ball(r)
    assert _dp(r, "gstate") == 2, "three balls gone is GAME OVER"
    # The block is BOTH rows, written one cell per frame through the VBlank
    # queue, so it takes 2*MSG_W frames to land. Waiting for the FIRST row and
    # then asserting the second is a race the test would win most of the time
    # -- which is worse than losing it.
    for _ in range(4 * MSG_W):
        r.frame_step(1)
        if _text(r, MSG_ROW0 + 2, MSG_COL, MSG_W) == "PRESS START":
            break
    assert _text(r, MSG_ROW0, MSG_COL, MSG_W).strip() == "GAME OVER", \
        "GAME OVER is not on BG3"
    assert _text(r, MSG_ROW0 + 2, MSG_COL, MSG_W) == "PRESS START"
    assert _text(r, HUD_ROW, 26, 1) == "0", "...and BALLS printed 0"
    assert _oam(r, OAM_BALL)[1] == PARK_Y, \
        "the ball must be parked, not frozen mid-flight over the end screen"


def test_start_rebuilds_the_whole_wall(r):
    """The restart path: GAME OVER -> Start -> title -> Start ->
    play, and the wall is back IN VRAM. Asserting the counter would pass with
    an empty arena on screen."""
    _goto_play(r)
    r.frame_step(2, a=True)
    for _ in range(300):                    # knock some bricks out first
        px, bx = _dp(r, "px"), _dp(r, "bx")
        r.frame_step(1, right=(px + 12 < bx + 4), left=(px + 12 > bx + 4))
    m = [w & 0x3FF for w in _map_words(r, BRK_MAP)]
    assert sum(t in BRICK_TILES for t in m) < BRICK_TOTAL, \
        "the setup did not actually break anything"

    _press_start(r)
    _settle(r, SCENE_TITLE)
    _press_start(r)
    _settle(r, SCENE_PLAY)

    m = [w & 0x3FF for w in _map_words(r, BRK_MAP)]
    assert sum(t in BRICK_TILES for t in m) == BRICK_TOTAL, \
        "the restart did not rebuild all 180 bricks in VRAM"
    assert _text(r, HUD_ROW, 8, 4) == "0000" and _text(r, HUD_ROW, 26, 1) == "3"
    assert _text(r, MSG_ROW0, MSG_COL, MSG_W).strip() == "PRESS A"


def test_leaving_the_arena_takes_its_colour_math_with_it(r, tmp_path):
    """breaker_obj and rgb_gradient are ARMED by play::enter and must be
    DISARMED by play::exit. A tint or a stray sprite left behind would render
    on the title through registers that scene never wrote — the exact bug
    class the title screen exists to expose."""
    _goto_play(r)
    _press_start(r)
    _settle(r, SCENE_TITLE)
    r.frame_step(30)
    for slot in (OAM_PADDLE, OAM_PADDLE + 1, OAM_PADDLE + 2, OAM_BALL):
        assert _oam(r, slot)[1] == PARK_Y, f"slot {slot} came back with us"
    img, top = _shot(r, tmp_path, "title_after_play")
    # The title is BG3-on-backdrop. With the arena's colour math left armed,
    # every backdrop pixel would carry the ramp; disarmed, the backdrop is the
    # flat near-black $1000 the title's own enter wrote.
    bg = {img.getpixel((x, top + y)) for x in (8, 128, 248) for y in (40, 190)}
    assert len(bg) == 1, f"the title backdrop is not flat: {bg}"
    rr, gg, bb = bg.pop()
    assert rr < 40 and gg < 40 and bb < 40, \
        f"the title backdrop is tinted {(rr, gg, bb)} — rg_disarm did not run"
