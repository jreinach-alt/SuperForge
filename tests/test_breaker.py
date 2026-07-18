"""Done-conditions for the breaker template (paddle-and-ball block-breaker).

Test-authoring discipline: every assertion reads the real output region —
screenshot pixels (paddle/ball/bricks visible and moving the right way),
the BG1 tilemap VRAM bytes (the wall, and the cells broken bricks vacate),
CGRAM palette entries, the BG3 tilemap words (the printed HUD counters),
OAM (sprite placement) — never a proxy variable alone. The debug mirrors at
$7E:E010+ are supplements, cross-checked against hardware bytes.

State cycle coverage: WAIT (ball rides paddle) -> launch (A) -> PLAY ->
wall/paddle bounce (both axes reversing) -> brick break -> ball lost ->
WAIT again -> all balls lost -> GAME OVER -> Start -> full reset. The paddle
is driven in BOTH directions with OAM and rendered-pixel evidence; a
closed-loop bot proves the paddle bounce keeps a rally alive.

Geometry (from templates/breaker/main.asm):
  paddle: 3x8px CYAN sprites (tile 2, OAM slots 0-2) at y=200
  ball:   8x8 WHITE sprite (tile 1, OAM slot 3); rides the paddle at y=192
  bricks: BG1 cells rows 5..10 x cols 1..30 (tiles 2..5 cycling), 180 total
  walls:  BG1 tile 1 at row 2 + cols 0/31 rows 3..27; the bottom is open
  HUD:    "SCORE" + 5 digits at BG3 row 1 cols 1../7..; "BALLS" + 5 digits
          at cols 20../26..; messages print at pixel y=128/144 (rows 16/18)
  debug:  $E010 score (10/brick), $E012 balls, $E014 bricks left,
          $E016 state (0=wait 1=play 2=game-over 3=win)
"""
import time
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam
OAM = MemoryType.SnesSpriteRam
CG = MemoryType.SnesCgRam

BG1_MAP = 0xB000            # BG1 tilemap VRAM byte address (word $5800)
BG3_MAP = 0xC000            # BG3 tilemap VRAM byte address (word $6000)

DBG_SCORE = 0xE010
DBG_BALLS = 0xE012
DBG_BRICKS = 0xE014
DBG_STATE = 0xE016

BRICK_ROWS = range(5, 11)   # map rows 5..10
BRICK_COLS = range(1, 31)   # map cols 1..30
BRICK_TILES = (2, 3, 4, 5)
BRICK_TOTAL = 180

_WHITE = lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200
_CYAN = lambda p: p[0] < 90 and p[1] > 150 and p[2] > 150
_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90
_GREEN = lambda p: p[1] > 130 and p[0] < 110 and p[2] < 110
_GREY = lambda p: 90 < p[0] < 180 and 90 < p[1] < 180 and 90 < p[2] < 180


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rom():
    p = BUILD / "breaker.sfc"
    assert p.exists(), f"{p} not built — run `make breaker` first"
    return str(p)


def _shot(r, path="/tmp/_breaker_shot.png"):
    r.take_screenshot(path)
    return Image.open(path).convert("RGB")


def _blob_centroid(img, pred, y_min=0, y_max=239):
    """Centroid of pixels matching pred inside a row band. None if absent."""
    pts = [
        (x, y)
        for y in range(y_min, min(y_max, img.height))
        for x in range(img.width)
        if pred(img.getpixel((x, y)))
    ]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), len(pts))


def _dbg(r):
    return dict(
        score=r.read_u16(WR, DBG_SCORE),
        balls=r.read_u16(WR, DBG_BALLS),
        bricks=r.read_u16(WR, DBG_BRICKS),
        state=r.read_u16(WR, DBG_STATE),
    )


def _map_row(r, row):
    """Tile-id bytes (low byte of each tilemap word) of one BG1 map row."""
    raw = r.read_bytes(VR, BG1_MAP + row * 64, 64)
    return [raw[i * 2] for i in range(32)]


def _count_bricks_vram(r):
    n = 0
    for row in BRICK_ROWS:
        tiles = _map_row(r, row)
        n += sum(1 for c in BRICK_COLS if tiles[c] in BRICK_TILES)
    return n


def _bg3_glyph(ch):
    return 0x3C00 | (160 + ord(ch) - 0x20)


def _read_hud_u16(r, col):
    """Decode the 5-digit counter printed at BG3 row 1, tile column `col`."""
    digits = ""
    for i in range(5):
        w = r.read_bytes(VR, BG3_MAP + (1 * 32 + col + i) * 2, 2)
        word = w[0] | (w[1] << 8)
        digits += chr(((word & 0x3FF) - 160 + 0x20) & 0x7F)
    return digits


def _paddle_x(r):
    return r.read_bytes(OAM, 0, 1)[0]   # paddle-left sprite = OAM slot 0


def _ball(r):
    b = r.read_bytes(OAM, 12, 4)        # ball = OAM slot 3 (tile 1)
    assert b[2] == 1, f"OAM slot 3 is not the ball (tile {b[2]})"
    return b[0], b[1]


def _tap(r, frames=3, **btn):
    r.set_input(0, **btn)
    r.run_frames(frames)
    r.set_input(0)


def _bot_step(r):
    """One closed-loop frame: relaunch from WAIT, else steer under the ball."""
    if r.read_u16(WR, DBG_STATE) == 0:
        _tap(r, a=True)
        return
    bx, _ = _ball(r)
    padx = _paddle_x(r)
    if bx + 4 < padx + 10:
        r.set_input(0, left=True)
    elif bx + 4 > padx + 14:
        r.set_input(0, right=True)
    else:
        r.set_input(0)
    r.run_frames(1)


# ---------------------------------------------------------------------------
# boot: the whole field renders — walls, 6 brick rows, paddle, ball, HUD —
# verified in VRAM, CGRAM, OAM, and rendered pixels
# ---------------------------------------------------------------------------

def test_boots_field_rendered(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert _dbg(runner) == dict(score=0, balls=3, bricks=BRICK_TOTAL, state=0)

    # BG1 tilemap: walls (top row all tile 1, side cols mid-arena) + bricks
    assert _map_row(runner, 2) == [1] * 32, "top wall missing"
    row_mid = _map_row(runner, 14)
    assert row_mid[0] == 1 and row_mid[31] == 1, "side walls missing"
    assert _count_bricks_vram(runner) == BRICK_TOTAL
    # row colours cycle 2,3,4,5 down the wall; play area below is open
    assert _map_row(runner, 5)[1] == 2 and _map_row(runner, 6)[1] == 3
    assert _map_row(runner, 7)[1] == 4 and _map_row(runner, 8)[1] == 5
    assert _map_row(runner, 9)[1] == 2 and _map_row(runner, 10)[30] == 3
    assert _map_row(runner, 15)[15] == 0, "play area not open"

    # CGRAM: wall + brick colours landed in BG palette 0
    cg = runner.read_bytes(CG, 0, 12)
    assert cg[2] | (cg[3] << 8) == 0x39CE   # slot 1 wall grey
    assert cg[4] | (cg[5] << 8) == 0x001F   # slot 2 red
    assert cg[8] | (cg[9] << 8) == 0x03FF   # slot 4 yellow

    # BG3 tilemap: HUD labels + zero-padded counters
    for i, ch in enumerate("SCORE"):
        w = runner.read_bytes(VR, BG3_MAP + (1 * 32 + 1 + i) * 2, 2)
        assert w[0] | (w[1] << 8) == _bg3_glyph(ch), f"HUD glyph {ch!r}"
    assert _read_hud_u16(runner, 7) == "00000"
    assert _read_hud_u16(runner, 26) == "00003"

    # OAM: paddle centred (slot 0 x=116), ball riding it (slot 3, +8 / y192)
    assert _paddle_x(runner) == 116
    assert _ball(runner) == (124, 192)

    # screen: each element visible as pixels in its own region
    img = _shot(runner)
    red = _blob_centroid(img, _RED)
    green = _blob_centroid(img, _GREEN)
    assert red and red[2] > 800, "red brick rows not rendered"
    assert green and green[2] > 400, "green brick row not rendered"
    assert red[1] < 90 and green[1] < 90, "brick pixels outside the wall band"
    grey = _blob_centroid(img, _GREY)
    assert grey and grey[2] > 500, "walls not rendered"
    pad = _blob_centroid(img, _CYAN, y_min=190)
    assert pad and 100 <= pad[2] <= 260, "cyan paddle not rendered"
    ball = _blob_centroid(img, _WHITE, y_min=185, y_max=205)
    assert ball and 15 <= ball[2] <= 80, "white ball not rendered on the paddle"


# ---------------------------------------------------------------------------
# paddle: both d-pad directions move it on screen; it stays on its row
# ---------------------------------------------------------------------------

def test_paddle_moves_both_directions_on_screen(runner):
    for name, kw, sign in [("right", dict(right=True), +1), ("left", dict(left=True), -1)]:
        runner.load_rom(_rom(), run_seconds=0.5)
        img = _shot(runner)
        before = _blob_centroid(img, _CYAN, y_min=190)
        assert before, "paddle not visible before input"
        runner.set_input(0, **kw)
        runner.run_frames(20)
        runner.set_input(0)
        runner.run_frames(2)
        img = _shot(runner)
        after = _blob_centroid(img, _CYAN, y_min=190)
        assert after, "paddle not visible after input"
        moved = (after[0] - before[0]) * sign
        assert moved > 25, f"{name}: paddle blob moved {moved:.0f}px on screen"
        assert abs(after[1] - before[1]) < 2, f"{name}: paddle left its row"


def test_paddle_clamps_at_walls_ball_rides(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    _tap(runner, frames=120, left=True)
    runner.run_frames(2)
    assert _paddle_x(runner) == 8, "left clamp (OAM)"
    # in WAIT the ball rides the paddle: centre offset +8, y 192
    assert _ball(runner) == (16, 192), "ball not riding the clamped paddle"
    img = _shot(runner)
    pad = _blob_centroid(img, _CYAN, y_min=190)
    assert pad and pad[0] < 40, "paddle pixels not at the left wall"

    _tap(runner, frames=160, right=True)
    runner.run_frames(2)
    assert _paddle_x(runner) == 224, "right clamp (OAM)"
    assert _ball(runner) == (232, 192)
    img = _shot(runner)
    pad = _blob_centroid(img, _CYAN, y_min=190)
    assert pad and pad[0] > 215, "paddle pixels not at the right wall"


# ---------------------------------------------------------------------------
# launch: A flips WAIT -> PLAY and the ball rises off the paddle
# ---------------------------------------------------------------------------

def test_launch_transitions_to_play(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    assert _dbg(runner)["state"] == 0
    _, by0 = _ball(runner)
    assert by0 == 192
    _tap(runner, a=True)
    runner.run_frames(20)
    assert _dbg(runner)["state"] == 1, "A did not start PLAY"
    _, by1 = _ball(runner)
    assert by1 < by0, "ball did not rise after launch"


# ---------------------------------------------------------------------------
# ball: bounces inside the arena, both axes reversing; never escapes the
# walls or passes the top (closed-loop bot keeps the rally going)
# ---------------------------------------------------------------------------

def test_ball_bounces_within_arena(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    _tap(runner, a=True)
    xs, ys, dxs, dys = [], [], [], []
    prev = _ball(runner)
    deadline = time.time() + 8
    while time.time() < deadline:
        _bot_step(runner)
        cur = _ball(runner)
        xs.append(cur[0])
        ys.append(cur[1])
        if cur[0] != prev[0]:
            dxs.append(cur[0] - prev[0])
        if cur[1] != prev[1]:
            dys.append(cur[1] - prev[1])
        prev = cur
    runner.set_input(0)
    assert min(xs) >= 8 and max(xs) <= 240, f"ball x escaped walls ({min(xs)}..{max(xs)})"
    assert min(ys) >= 24, f"ball passed the top wall (y={min(ys)})"
    assert any(d > 0 for d in dxs) and any(d < 0 for d in dxs), "x never reversed"
    assert any(d > 0 for d in dys) and any(d < 0 for d in dys), "y never reversed"
    # it actually travelled — reached a side wall or the brick band and back
    assert min(xs) <= 24 or max(xs) >= 224 or min(ys) <= 96, \
        "ball never crossed the arena"


# ---------------------------------------------------------------------------
# bricks: a hit clears the BG1 cell in VRAM, score/bricks mirrors track it,
# and the printed HUD counter (BG3 VRAM glyphs) reprints
# ---------------------------------------------------------------------------

def test_brick_break_clears_cell_and_scores(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    assert _count_bricks_vram(runner) == BRICK_TOTAL
    digits_before = _read_hud_u16(runner, 7)
    _tap(runner, a=True)
    deadline = time.time() + 10
    while time.time() < deadline and runner.read_u16(WR, DBG_SCORE) < 10:
        runner.run_frames(5)
    s1 = runner.read_u16(WR, DBG_SCORE)
    assert s1 >= 10, "ball broke no bricks in 10s"
    runner.run_frames(3)                       # let the NMI commit the shadow
    cleared = BRICK_TOTAL - _count_bricks_vram(runner)
    hud = _read_hud_u16(runner, 7)
    d = _dbg(runner)
    # the ball may break another brick between reads — bound, don't pin
    assert s1 // 10 <= cleared <= d["score"] // 10 + 1, \
        f"VRAM cleared cells {cleared} vs score {s1}..{d['score']}"
    assert abs((BRICK_TOTAL - d["bricks"]) - cleared) <= 1, \
        "bricks mirror out of step with VRAM"
    assert d["score"] >= (BRICK_TOTAL - d["bricks"]) * 10 - 10, \
        "score out of step with bricks"
    assert hud != digits_before, "HUD score digits did not reprint"
    assert hud.isdigit() and s1 - 10 <= int(hud) <= d["score"] + 20, \
        f"HUD shows {hud!r}, score {s1}..{d['score']}"


# ---------------------------------------------------------------------------
# paddle bounce: the closed-loop bot keeps the rally alive — no ball lost,
# bricks keep breaking, and the broken cells show in VRAM
# ---------------------------------------------------------------------------

def test_paddle_bounce_keepalive_bot(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    _tap(runner, a=True)
    start_score = runner.read_u16(WR, DBG_SCORE)
    deadline = time.time() + 15
    while time.time() < deadline:
        _bot_step(runner)
    runner.set_input(0)
    d = _dbg(runner)
    assert d["balls"] == 3, "bot lost a ball — paddle bounce broken"
    gained = d["score"] - start_score
    assert gained >= 50, f"rally broke only {gained // 10} bricks in 15s"
    runner.run_frames(3)
    assert BRICK_TOTAL - _count_bricks_vram(runner) >= 5, \
        "VRAM does not show the broken bricks"
    Path("/tmp/e2e_screenshots").mkdir(parents=True, exist_ok=True)
    runner.take_screenshot("/tmp/e2e_screenshots/breaker_rally.png")


# ---------------------------------------------------------------------------
# lost ball: with the paddle parked the ball falls past it — BALLS ticks
# down, the game returns to WAIT, and the ball rides the paddle again
# ---------------------------------------------------------------------------

def test_lose_ball_returns_to_wait(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    _tap(runner, frames=120, left=True)        # park the paddle at the wall
    _tap(runner, a=True)
    deadline = time.time() + 45
    while time.time() < deadline and runner.read_u16(WR, DBG_BALLS) == 3:
        runner.run_frames(10)
    d = _dbg(runner)
    assert d["balls"] == 2, "ball never fell past the parked paddle"
    assert d["state"] == 0, "lost ball did not return to WAIT"
    runner.run_frames(5)
    bx, by = _ball(runner)
    assert by == 192 and bx == _paddle_x(runner) + 8, \
        "ball not riding the paddle after the loss"
    # BALLS HUD counter reprinted on BG3
    assert _read_hud_u16(runner, 26) == "00002"
    # "PRESS A" prompt rendered in the message band
    img = _shot(runner)
    msg = _blob_centroid(img, _WHITE, y_min=124, y_max=142)
    assert msg and msg[2] >= 30, "PRESS A prompt not rendered"


# ---------------------------------------------------------------------------
# full cycle: lose all three balls -> GAME OVER (state + rendered text);
# Start rebuilds the wall in VRAM and resets every counter
# ---------------------------------------------------------------------------

def test_full_cycle_game_over_restart(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    _tap(runner, frames=120, left=True)        # park the paddle at the wall

    frames, balls_seen = 0, {3}
    while frames < 5400:                       # 90 s cap
        d = _dbg(runner)
        balls_seen.add(d["balls"])
        if d["state"] == 2:
            break
        if d["state"] == 0:
            _tap(runner, a=True)
            frames += 3
        runner.run_frames(30)
        frames += 30
    d = _dbg(runner)
    assert d["state"] == 2, f"never reached GAME OVER ({d}, {frames} frames)"
    assert d["balls"] == 0
    assert {2, 1, 0} <= balls_seen, "ball count did not step down through 2,1,0"

    # GAME OVER / PRESS START rendered: white pixels in the message band
    img = _shot(runner)
    band = sum(
        1 for x in range(64, 192) for y in range(125, 165)
        if _WHITE(img.getpixel((x, y)))
    )
    assert band >= 80, "GAME OVER / PRESS START text not rendered"

    # Start restarts: wall rebuilt in VRAM, counters reset, back to WAIT
    _tap(runner, start=True)
    runner.run_frames(10)
    assert _count_bricks_vram(runner) == BRICK_TOTAL, "brick wall not rebuilt in VRAM"
    assert _dbg(runner) == dict(score=0, balls=3, bricks=BRICK_TOTAL, state=0)
    assert _read_hud_u16(runner, 7) == "00000"


# ---------------------------------------------------------------------------
# WIN: a closed-loop frame-stepped paddle bot clears ALL 180 bricks — the
# wall is gone in VRAM, the mirrors reach bricks=0 / state=3 (WIN), and the
# "YOU WIN!" message actually renders (BG3 VRAM glyphs + screen pixels)
# ---------------------------------------------------------------------------

def test_win_full_clear_renders_you_win(runner):
    """Drives the full WAIT -> PLAY -> WIN state cycle deterministically.

    The bot (tests/_breaker_bot.py) reads ball/paddle state from WRAM and
    the live brick map from VRAM each catch, aims via the paddle's english
    zones (bot-side simulation of the ROM's own collision rules — the game
    is untouched), and advances with frame_step. Frame-stepping runs at
    host speed, so the ~8k-frame rally finishes in O(1 minute).
    """
    from tests import _breaker_bot

    runner.load_rom(_rom(), run_seconds=0.5)
    bot = _breaker_bot.WinBot(runner)
    with runner.frame_stepping():
        won = bot.run(frame_cap=40000, wall_cap=400.0)
        assert won, f"bot did not clear the wall within {bot.frames} frames"

        # real output: every brick cell in the BG1 tilemap is gone
        runner.frame_step(3)            # let the final NMI commit the DMA
        assert _count_bricks_vram(runner) == 0, \
            "VRAM still shows brick tiles after the win"
        # mirrors agree (supplement)
        d = _dbg(runner)
        assert d["bricks"] == 0, f"BRICKS mirror {d['bricks']} != 0"
        assert d["state"] == 3, f"STATE mirror {d['state']} != 3 (WIN)"
        assert d["balls"] == 3, "bot lost a ball on the way to the win"
        assert d["score"] == BRICK_TOTAL * 10, f"score {d['score']} != 1800"

        # the printed HUD score counter shows 1800 (BG3 VRAM glyphs)
        assert _read_hud_u16(runner, 7) == "01800"

        # "YOU WIN!" printed at (96,128) -> BG3 row 16, cols 12..19
        for i, ch in enumerate("YOU WIN!"):
            w = runner.read_bytes(VR, BG3_MAP + (16 * 32 + 12 + i) * 2, 2)
            assert w[0] | (w[1] << 8) == _bg3_glyph(ch), \
                f"BG3 glyph {i} of 'YOU WIN!' missing"

        # and the message is visible as rendered pixels on screen
        img = _shot(runner, "/tmp/_breaker_win.png")
        band = sum(
            1 for x in range(88, 168) for y in range(124, 142)
            if _WHITE(img.getpixel((x, y)))
        )
        assert band >= 60, "'YOU WIN!' text not rendered on screen"
    # context manager restored free-running for any test that follows
