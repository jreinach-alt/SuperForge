"""Done-conditions for the sprite_game template (a minimal catch game).

Follows the test-authoring discipline: verifies the rendered result (both
sprites visible, correct colours) AND drives the full state cycle (catch ->
score++ -> dot relocates, twice) AND all four player directions.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

SCORE = 0x3A
DOT_X = 0x36
DOT_Y = 0x38

_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90
_YELLOW = lambda p: p[0] > 150 and p[1] > 150 and p[2] < 90


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rom():
    p = BUILD / "sprite_game.sfc"
    assert p.exists(), f"{p} not built — run `make sprite_game` first"
    return str(p)


def _count(r, pred):
    r.take_screenshot("/tmp/_sg_shot.png")
    img = Image.open("/tmp/_sg_shot.png").convert("RGB")
    return sum(1 for p in img.getdata() if pred(p))


def _player(r):
    b = r.read_bytes(OAM, 0, 4)
    return b[0], b[1]


def test_boots_both_sprites_visible(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert _player(runner) == (120, 100)                       # player OAM slot 0
    assert runner.read_bytes(OAM, 4, 4)[0] == 200              # dot OAM slot 1 at preset 0
    assert runner.read_u16(WR, SCORE) == 0
    assert 56 <= _count(runner, _RED) <= 72, "red player not visible"
    assert 56 <= _count(runner, _YELLOW) <= 72, "yellow dot not visible"


def test_player_moves_all_four_directions(runner):
    runner.load_rom(_rom(), run_seconds=0.4)
    sx, sy = _player(runner)
    for name, kw, (ex, ey) in [
        ("right", dict(right=True), (+1, 0)),
        ("left", dict(left=True), (-1, 0)),
        ("up", dict(up=True), (0, -1)),
        ("down", dict(down=True), (0, +1)),
    ]:
        runner.load_rom(_rom(), run_seconds=0.4)            # reset to spawn
        runner.set_input(0, **kw)
        runner.run_frames(20)
        runner.set_input(0)
        runner.run_frames(2)
        px, py = _player(runner)
        assert (px - sx) * ex + (py - sy) * ey > 15, f"{name}: player ({sx},{sy})->({px},{py})"
        if ex:
            assert py == sy
        else:
            assert px == sx


def test_catch_cycle_score_and_dot_relocate(runner):
    """Drive onto the dot twice — score increments and the dot cycles presets."""
    runner.load_rom(_rom(), run_seconds=0.4)
    assert runner.read_u16(WR, SCORE) == 0

    # catch #1: dot at preset 0 (200,60). Player spawns (120,100): go right then up.
    runner.set_input(0, right=True); runner.run_frames(40); runner.set_input(0)
    runner.set_input(0, up=True); runner.run_frames(25); runner.set_input(0); runner.run_frames(2)
    assert runner.read_u16(WR, SCORE) == 1, "catch #1 did not register"
    assert (runner.read_u16(WR, DOT_X), runner.read_u16(WR, DOT_Y)) == (60, 60), "dot did not move to preset 1"

    # catch #2: dot now at preset 1 (60,60). Player ~ (200, 50): go left then down onto it.
    runner.set_input(0, left=True); runner.run_frames(70); runner.set_input(0)
    runner.set_input(0, down=True); runner.run_frames(12); runner.set_input(0); runner.run_frames(2)
    assert runner.read_u16(WR, SCORE) == 2, "catch #2 did not register"
    assert (runner.read_u16(WR, DOT_X), runner.read_u16(WR, DOT_Y)) == (200, 160), "dot did not cycle to preset 2"
