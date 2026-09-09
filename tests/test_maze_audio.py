"""The maze's footstep, on the chip that plays it.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy: the
S-DSP voice. `VxENVX > 0` on an SFX channel says the voice is SOUNDING.

THIS RAIL HAS NO STEP COMMIT, which is the whole reason the cue needed new
state. The rpg's overworld walks a GRID, so a footstep hangs on the step that
commits; its own source says giving a cue an edge there "needs an edge latch,
and this rail has no state for one". The maze moves freely, two pixels a
frame, so "is moving" is true on every held-input frame and a cue on it fires
at 60 Hz. state.toml's `cell` is that latch: the 16 px stride the player was
in last tick, and the footstep is its CHANGE.

Three drives, because one of them cannot fail: walking must sound, standing
still must be silent, and PUSHING INTO A WALL must not machine-gun. The last
is the one that catches a cue placed on input or on the blocked arms — both
of which are re-entered every frame while the direction is held — and it is
also why this rail's answer is not the room rail's "silent when pinned": the
maze SLIDES along a wall by design, so a diagonal push keeps travelling and
should keep stepping. What it must not do is step faster than walking.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
SFX_VOICES = (6, 7)


def _drive(rom, drive, frames):
    r = MesenRunner(enable_audio=True)
    r.boot_rom(rom, frames=300)
    live = 0
    for i in range(frames):
        drive(r, i)
        d = r.read_bytes(DSP, 0, 128)
        if any(d[v * 0x10 + 8] for v in SFX_VOICES):
            live += 1
    r.stop()
    return live / frames


@pytest.fixture(scope="module")
def rom():
    p = SUPERFORGE / "build" / "maze.sfc"
    assert p.exists(), "build/maze.sfc not built — run `make maze` first"
    return str(p)


@pytest.fixture(scope="module")
def walking(rom):
    return _drive(rom, lambda r, i: r.frame_step(
        1, right=(i % 80 < 40), left=(i % 80 >= 40),
        down=(i % 160 < 80), up=(i % 160 >= 80)), 600)


@pytest.fixture(scope="module")
def idle(rom):
    return _drive(rom, lambda r, i: r.frame_step(1), 300)


@pytest.fixture(scope="module")
def shoving(rom):
    return _drive(rom, lambda r, i: r.frame_step(1, up=True, left=True), 300)


def test_walking_makes_footsteps(walking):
    """Measured at 0.41 — roughly four steps a second at MZ_SPEED = 2."""
    assert walking > 0.10, (
        f"the step voice is live on {walking:.0%} of walking frames — the "
        f"footstep is not reaching the chip at all")


def test_standing_still_is_silent(idle):
    """The cue is the stride's CHANGE, and a parked player changes none.

    An exact zero, not a threshold: nothing else on this rail queues anything,
    so any sounding voice here is a footstep that should not exist.
    """
    assert idle == 0.0, (
        f"the step voice is live on {idle:.0%} of frames with NO input — the "
        f"cue is firing off position or off the tick rather than off a change "
        f"of stride")


def test_shoving_into_a_wall_does_not_machine_gun(shoving, walking):
    """The cadence stays the walk's when the walk is blocked.

    WHAT THIS CATCHES, precisely, because the bar is relative: a cue placed on
    either BLOCKED arm of the move check. Those arms are re-entered every frame
    the direction is held into a wall and are not reached at all on a free
    walk, so such a defect raises this drive without raising the walking one.
    A cue that fires every frame regardless is caught by the idle case instead
    — planted, that reads 86% with no input at all.

    It is deliberately NOT asserted silent: the maze SLIDES along a wall by
    design, so a diagonal shove keeps travelling and should keep stepping. The
    claim is only that it never steps FASTER than walking does.
    """
    assert shoving <= walking + 0.05, (
        f"pushing into a wall sounds on {shoving:.0%} of frames against "
        f"{walking:.0%} for a free walk — the cue is on the input or the "
        f"blocked arm, not on the stride")
