"""Closed-loop input driver — emulator proof on the racer template.

Validates ``infrastructure/test_harness/input_driver.py``: program game input to
drive state to a TARGET (not a magic frame count), reproducibly, and prove the
self-validating timeout when the input is inert.

This is the foundation under every "program this input scenario and return
validation screenshots" task — once a drive reaches a known state, a screenshot
is taken at that *known* state instead of whatever a fixed frame count produced.
"""
import os

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
from infrastructure.test_harness.input_driver import drive_to_u8, DriveTimeout

ROM = "build/racer.sfc"
R_ANGLE = 0x3A                      # racer heading 0-255 (templates/racer/main.asm)
TARGET = 64
HOLD_STEER = {"b": True, "left": True}   # throttle + steer left

pytestmark = pytest.mark.skipif(
    not os.path.exists(ROM), reason="build/racer.sfc not built (run make racer)")


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _drive(r, hold, max_frames=600):
    """Boot, settle, then close-loop drive the heading to TARGET. Returns
    (frames_used, final_angle)."""
    r.load_rom(ROM, run_seconds=1.0)
    with r.frame_stepping():
        r.frame_step(5, b=True)                       # boot settle + throttle
        frames = drive_to_u8(r, R_ANGLE, TARGET, hold=hold, tol=2, wrap=256,
                             max_frames=max_frames)
        ang = r.read_bytes(MemoryType.SnesWorkRam, R_ANGLE, 1)[0]
    return frames, ang


def test_drive_to_angle_reaches_target(runner):
    """Closed-loop steering arrives at a KNOWN heading (within tolerance)."""
    frames, ang = _drive(runner, HOLD_STEER)
    d = min((ang - TARGET) % 256, (TARGET - ang) % 256)   # circular distance
    assert d <= 2, f"heading {ang} not within 2 of target {TARGET}"
    assert frames > 0


def test_drive_is_reproducible(runner):
    """Deterministic frame-stepping makes the drive byte-reproducible — the
    property the old open-loop / screenshot-diff approach never had."""
    f1, a1 = _drive(runner, HOLD_STEER)
    f2, a2 = _drive(runner, HOLD_STEER)
    assert (f1, a1) == (f2, a2), (
        f"closed-loop drive not deterministic: {(f1, a1)} vs {(f2, a2)}")


def test_inert_input_times_out(runner):
    """Self-validating property: an input that CANNOT move the state to target
    raises DriveTimeout instead of silently capturing the wrong state. Here,
    throttle-only (no steer) can't reach the heading."""
    runner.load_rom(ROM, run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(5, b=True)
        with pytest.raises(DriveTimeout):
            drive_to_u8(runner, R_ANGLE, TARGET, hold={"b": True}, tol=2,
                        wrap=256, max_frames=200)
