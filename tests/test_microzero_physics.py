"""microzero — race_logic velocity physics.

The fixed 48-px-per-frame debug drive is gone: B accelerates toward the
declared max ($3000 = 48.0 px/f), Down brakes to a stop and then
reverses, releasing everything coasts on friction, and the per-axis step is
the heading's 8.8 unit vector scaled by the signed velocity through the
hardware multiplier, integrated through a sub-pixel accumulator.

Every assertion here reads the ROM's OWN state words (position, velocity,
both accumulators, the sector machine) at the addresses the allocator
emitted, and compares against tools/gen_move_lut.Sim — an independent
integer model of the same arithmetic. A dropped carry, a wrong clamp, a
truncation where the ROM should floor, or a sign applied at the wrong point
all break the equality.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

WR = MemoryType.SnesWorkRam


@pytest.fixture(scope="module")
def booted():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    world = (SUPERFORGE / "build" / "assets" / "world_map.bin").read_bytes()
    lut = D.load_tool("gen_move_lut")
    runner = MesenRunner()
    runner.load_rom_with_uninit_detection(
        str(SUPERFORGE / "build" / "microzero.sfc"), frames=120)
    runner.debug_break()
    D.enter_race(runner, syms)
    runner.debug_break()
    runner.frame_step(2)
    yield runner, syms, world, lut
    runner.debug_resume()
    runner.stop()


def test_starts_at_rest_on_the_start_line(booted):
    """rl_arm's contract: stopped, no sub-pixel debt, zero laps, and the lap
    machine seeded in the start/finish sector (SE) with only that bit set."""
    runner, syms, world, lut = booted
    assert D.vel(runner, syms) == 0
    assert D.race_state(runner, syms)[3:] == (0, 0, 0, 3, 1 << 3)
    assert D.pos_px(runner, syms) == (D.world_const("CAM0_PX"),
                                     D.world_const("CAM0_PY"))


def test_accel_ramp_clamps_at_the_declared_max(booted):
    """Hold B: vel climbs by exactly MZ_ACCEL per frame and STOPS at
    MZ_VEL_MAX — read from the ROM every single frame, not just at the end."""
    runner, syms, world, lut = booted
    D.coast_to_stop(runner, syms)
    sim = D.sim_from_rom(runner, syms, lut)
    frames_to_cap = lut.VEL_MAX // lut.ACCEL
    for i in range(frames_to_cap + 10):
        D.drive_sim(runner, sim, 1, b=True)
        D.assert_matches_sim(runner, syms, sim, f"accel frame {i}")
    assert D.vel(runner, syms) == lut.VEL_MAX, "never reached the declared max"
    D.drive_sim(runner, sim, 5, b=True)
    assert D.vel(runner, syms) == lut.VEL_MAX, "clamp leaked past the max"


def test_coast_decays_to_a_full_stop_and_stays(booted):
    """Release everything: friction walks vel to EXACTLY zero (not to a
    residual creep), and a stopped car does not drift."""
    runner, syms, world, lut = booted
    sim = D.sim_from_rom(runner, syms, lut)
    D.drive_sim(runner, sim, 20, b=True)
    assert D.vel(runner, syms) > 0
    steps = lut.VEL_MAX // lut.FRICTION + 4
    for i in range(steps):
        D.drive_sim(runner, sim, 1)
        D.assert_matches_sim(runner, syms, sim, f"coast frame {i}")
        if D.vel(runner, syms) == 0:
            break
    else:
        pytest.fail("friction never brought the car to rest")
    parked = D.pos_px(runner, syms)
    D.drive_sim(runner, sim, 30)
    assert D.pos_px(runner, syms) == parked, "a stopped car drifted"
    assert D.vel(runner, syms) == 0


def test_brake_then_reverse_clamps_at_the_reverse_cap(booted):
    """Down from full speed: brake to a dead stop, then reverse — and the
    reverse clamp holds at MZ_VEL_MIN, which is NOT the forward cap."""
    runner, syms, world, lut = booted
    D.coast_to_stop(runner, syms)
    sim = D.sim_from_rom(runner, syms, lut)
    D.drive_sim(runner, sim, lut.VEL_MAX // lut.ACCEL, b=True)
    assert D.vel(runner, syms) == lut.VEL_MAX
    saw_stop = False
    for i in range(120):
        D.drive_sim(runner, sim, 1, down=True)
        D.assert_matches_sim(runner, syms, sim, f"brake frame {i}")
        if D.vel(runner, syms) == 0:
            saw_stop = True
    assert saw_stop, "braking never passed through a dead stop"
    assert D.vel(runner, syms) == lut.VEL_MIN, "reverse cap not held"
    D.drive_sim(runner, sim, 5, down=True)
    assert D.vel(runner, syms) == lut.VEL_MIN


def test_sub_pixel_accumulator_moves_the_car_below_one_pixel_per_frame(booted):
    """THE reason the accumulators exist: at a fraction of a pixel per frame
    the car must still travel. Coast down from a tap of B at an off-axis
    heading and check that frames whose whole-pixel step is zero on BOTH axes
    still add up to real displacement — matching the oracle byte for byte."""
    runner, syms, world, lut = booted
    D.coast_to_stop(runner, syms)
    D.steer_to(runner, syms, 4)                  # off-axis: both axes fractional
    D.coast_to_stop(runner, syms)
    sim = D.sim_from_rom(runner, syms, lut)
    start = D.pos_px(runner, syms)
    D.drive_sim(runner, sim, 1, b=True)          # a single tap: vel = MZ_ACCEL
    assert D.vel(runner, syms) == lut.ACCEL

    sub_pixel_frames = 0
    for i in range(40):
        before = D.pos_px(runner, syms)
        ux, uy = lut.unit(sim.h)
        v = sim.vel
        if max(abs(lut.scale(ux, v)), abs(lut.scale(uy, v))) < 256 and v:
            sub_pixel_frames += 1
        D.drive_sim(runner, sim, 1)
        D.assert_matches_sim(runner, syms, sim, f"sub-pixel frame {i}")
        del before
        if D.vel(runner, syms) == 0:
            break
    assert sub_pixel_frames >= 3, "the scenario never went sub-pixel"
    assert D.pos_px(runner, syms) != start, \
        "sub-pixel steps were dropped — the accumulator is not carrying"


def test_long_drive_stays_in_lockstep_and_the_window_stays_exact(booted):
    """The everything-at-once frame under the new physics: accelerate to the
    declared max while steering every frame (a pose retarget in every VBlank)
    on top of live streaming, then coast. State must match the oracle
    EXACTLY at every checkpoint and the streamed 128x128 window must equal
    the world at the camera's wrapped position."""
    runner, syms, world, lut = booted
    D.coast_to_stop(runner, syms)
    D.steer_to(runner, syms, 0)
    D.coast_to_stop(runner, syms)
    sim = D.sim_from_rom(runner, syms, lut)
    for leg, kw in enumerate(({"b": True}, {"b": True, "left": True},
                              {"b": True, "right": True}, {})):
        D.drive_sim(runner, sim, 40, **kw)
        D.assert_matches_sim(runner, syms, sim, f"leg {leg} {kw} end")
        D.brake_to_stop(runner, syms, sim)      # the window check needs rest
        D.assert_matches_sim(runner, syms, sim, f"leg {leg} {kw} braked")
        D.assert_window_exact(runner, syms, world, f"after leg {leg}")
        for _ in range(3):                      # assert_window_exact's idle
            sim.frame()
        D.assert_matches_sim(runner, syms, sim, f"leg {leg} settle")


def test_no_uninitialized_reads_across_the_physics_path(booted):
    """Power-on contract over the whole physics history — the scratch, the
    accumulators and the lap machine read only state rl_arm wrote."""
    runner, syms, world, lut = booted
    runner.frame_step(10)
    runner.assert_no_uninitialized_reads()
