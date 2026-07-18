"""Done-condition for the maze template: solid-wall movement.

Drives the player with real input and reads the real outputs: OAM position,
rendered grey wall + red player pixels, wall-stop coordinates (no overlap, no
pass-through), and the slide-along-wall behaviour. All four directions get a
wall-stop check (the border surrounds the room).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

_GREY = lambda p: abs(p[0] - p[1]) < 30 and abs(p[1] - p[2]) < 30 and 80 < p[0] < 200
_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90


def _pos(r):
    b = r.read_bytes(OAM, 0, 2)
    return b[0], b[1]


def _hold(r, frames, **btn):
    r.set_input(0, **btn)
    r.run_frames(frames)
    r.set_input(0)
    r.run_frames(2)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "maze.sfc"
    assert rom.exists(), f"{rom} not built — run `make maze` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


def test_boots_and_renders(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.take_screenshot("/tmp/_maze0.png")
    img = Image.open("/tmp/_maze0.png").convert("RGB")
    d = list(img.getdata())
    assert sum(1 for p in d if _GREY(p)) > 2000, "walls not visible"
    assert sum(1 for p in d if _RED(p)) > 20, "player not visible"


def test_moves_freely_in_open_floor(runner):
    # spawn (40,100) is open floor; small moves in all four directions succeed
    x0, y0 = _pos(runner)
    _hold(runner, 5, right=True)
    assert _pos(runner)[0] > x0, "right blocked in open floor"
    _hold(runner, 5, left=True)
    _hold(runner, 5, down=True)
    assert _pos(runner)[1] > y0, "down blocked in open floor"
    _hold(runner, 5, up=True)


def test_left_wall_stops_player(runner):
    _hold(runner, 60, left=True)        # border col 0 = px 0..7 -> stop at x=8
    x, _ = _pos(runner)
    assert x == 8, f"left wall stop at x={x}, want 8 (no overlap/pass-through)"
    # keep pushing — must not tunnel through
    _hold(runner, 30, left=True)
    assert _pos(runner)[0] == 8, "player tunnelled into the left wall"


def test_interior_wall_stops_player_right(runner):
    # interior wall col 12 (px 96..103) spans rows 1..13 (px 8..111). At
    # y=100 the player is inside its span -> pushing right stops at x=88.
    _hold(runner, 80, right=True)
    x, y = _pos(runner)
    assert y < 112, f"test precondition: player y={y} must be in wall A's span"
    assert x == 88, f"interior wall stop at x={x}, want 88"


def test_slides_along_wall_not_stuck(runner):
    # pressed against wall A, pushing down must still move (slide), and past
    # the wall's end (row 13, py>=112) pushing right must succeed again.
    x0, y0 = _pos(runner)
    _hold(runner, 30, down=True, right=True)   # diagonal into the wall
    x1, y1 = _pos(runner)
    assert y1 > y0, "player stuck on wall — free axis did not slide"
    _hold(runner, 30, down=True)
    _hold(runner, 20, right=True)
    assert _pos(runner)[0] > 96, "player could not pass the wall gap below"


def test_top_and_bottom_walls_stop_player(runner):
    # route back to the open left chamber first (clear of interior walls A/B)
    _hold(runner, 120, left=True)
    assert _pos(runner)[0] == 8, "navigation precondition: back at left border"
    _hold(runner, 120, up=True)
    assert _pos(runner)[1] == 8, f"top wall stop at y={_pos(runner)[1]}, want 8"
    _hold(runner, 150, down=True)
    # bottom border row 27 = px 216..223 -> stop with player bottom at 215
    assert _pos(runner)[1] == 208, \
        f"bottom wall stop at y={_pos(runner)[1]}, want 208"


def test_right_wall_stops_player(runner):
    # head into the right chamber along the bottom (below wall B's row), then
    # push right to the border col 31 (px 248..255) -> stop at x=240
    _hold(runner, 150, right=True)
    x, _ = _pos(runner)
    assert x == 240, f"right wall stop at x={x}, want 240"
