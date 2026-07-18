"""Closed-loop input driver — emulator proof on the platformer template.

Proves the generic drivers (infrastructure/test_harness/input_driver.py)
generalize beyond racing to the platformer genre — the two motions you program
constantly:
  - walk_to_x  : drive_to_u16 on the player X coordinate (PX)
  - jump cycle : drive_until on GROUNDED / PIXY (liftoff -> apex -> land)

Both are deterministic and reproducible, replacing the template's bespoke bot
(tests/_platformer_bot.py) whose walk_to is wall-clock (time.time + run_frames)
and whose jumps are open-loop magic-number arcs ("tuned" hold counts).
"""
import os

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
from infrastructure.test_harness.input_driver import drive_to_u16, drive_until

ROM = "build/platformer.sfc"
WR = MemoryType.SnesWorkRam
PX, PIXY, GROUNDED = 0x32, 0x5C, 0x3A          # player x, pixel-y, grounded flag
SPAWN_Y = 184

pytestmark = pytest.mark.skipif(
    not os.path.exists(ROM), reason="build/platformer.sfc not built (run make platformer)")


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rd(r, addr):
    return r.read_u16(WR, addr)


def _new_game(r):
    """Boot to a fresh game at the spawn. START from the title always starts a
    new game (the soft-restart path), regardless of any battery save."""
    r.load_rom(ROM, run_seconds=1.0)


def test_walk_to_x_reaches_and_reproducible(runner):
    """Closed-loop walk arrives at a KNOWN x coordinate, reproducibly."""
    def go():
        _new_game(runner)
        with runner.frame_stepping():
            runner.frame_step(8, start=True)         # title -> game
            runner.frame_step(40)                    # settle at spawn
            d = {"right": True} if _rd(runner, PX) < 54 else {"left": True}
            frames = drive_to_u16(runner, PX, 54, hold=d, tol=2, max_frames=300)
            return frames, _rd(runner, PX)

    f1, x1 = go()
    f2, x2 = go()
    assert abs(x1 - 54) <= 2, f"walk landed at {x1}, target 54"
    assert (f1, x1) == (f2, x2), f"walk not deterministic: {(f1, x1)} vs {(f2, x2)}"


def test_jump_cycle_reproducible(runner):
    """A jump observed closed-loop: leaves the ground, rises to an apex above
    spawn, and lands back at spawn grounded — deterministic, no magic counts."""
    def go():
        _new_game(runner)
        with runner.frame_stepping():
            runner.frame_step(8, start=True)
            runner.frame_step(40)
            assert _rd(runner, GROUNDED) == 1, "not grounded at spawn"
            y0 = _rd(runner, PIXY)
            runner.frame_step(4, a=True)             # press jump
            drive_until(runner, lambda: _rd(runner, GROUNDED) == 0,
                        hold={"a": True}, max_frames=20, what="liftoff")
            apex = [y0]

            def landed():
                apex[0] = min(apex[0], _rd(runner, PIXY))
                return _rd(runner, GROUNDED) == 1

            land = drive_until(runner, landed, max_frames=120, what="land")
            return apex[0], land, _rd(runner, PIXY)

    a1, l1, yl1 = go()
    a2, l2, yl2 = go()
    assert a1 < SPAWN_Y, f"jump did not rise (apex PIXY {a1} >= spawn {SPAWN_Y})"
    assert yl1 == SPAWN_Y, f"did not land back at spawn (PIXY {yl1})"
    assert (a1, l1, yl1) == (a2, l2, yl2), (
        f"jump not deterministic: {(a1, l1, yl1)} vs {(a2, l2, yl2)}")
