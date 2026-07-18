"""Run-gates for the S2 physics tail: variable jump, one-way platforms, pits.

Drives the full state cycle of each feature on the emulator via injected
input, asserting on the ROM's per-frame mirrors + OAM/pixels:
  - tap-jump apex measurably lower than held-jump apex (sf_jump_cut)
  - a full jump from the ground passes THROUGH the platform from below,
    lands ON it (exact rest pixel), stands stably, and walking off the
    edge falls back to the ground (the whole one-way cycle)
  - walking past the ground gap falls into the pit, trips the death plane,
    respawns at the start with the death counter bumped
"""
import time
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam

APEX, PIXY, GROUNDED, DEATHS, PXM = 0xE010, 0xE012, 0xE014, 0xE016, 0xE018

GROUND_REST = 184
PLAT_REST = 152                 # platform row 20: top 160, box rest 152


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _load(runner):
    rom = ROOT / "build" / "physics_tail_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE008) == 1


def _wait(runner, cond, frames, what):
    for _ in range(0, frames, 2):
        if cond():
            return
        runner.run_frames(2)
    pytest.fail(f"timed out waiting for {what}")


def _grounded_at(runner, rest):
    return (runner.read_u16(WR, GROUNDED) == 1
            and runner.read_u16(WR, PIXY) == rest)


def _jump(runner, hold_frames):
    runner.set_input(0, a=True)
    runner.run_frames(hold_frames)
    runner.set_input(0)
    # airborne -> landed (apex mirror updates on the landing frame)
    _wait(runner, lambda: runner.read_u16(WR, GROUNDED) == 0, 60, "takeoff")
    _wait(runner, lambda: runner.read_u16(WR, GROUNDED) == 1, 120, "landing")
    runner.run_frames(2)
    return runner.read_u16(WR, APEX)


def test_variable_height_jump(runner):
    _load(runner)
    assert _grounded_at(runner, GROUND_REST), "did not start at rest"
    tap_apex = _jump(runner, 2)
    held_apex = _jump(runner, 30)
    # full arc tops ~38px above rest; a 2-frame tap must cut well short
    assert held_apex < GROUND_REST - 30, f"held jump too low (apex {held_apex})"
    assert tap_apex > held_apex + 8, (
        f"jump cut ineffective: tap apex {tap_apex} vs held {held_apex}")


def test_oneway_platform_full_cycle(runner):
    _load(runner)
    # walk under the platform (cols 8-12 -> x 64..103; box 8px -> stand at 80)
    runner.set_input(0, right=True)
    _wait(runner, lambda: runner.read_u16(WR, PXM) >= 80, 240, "walk to x>=80")
    runner.set_input(0)
    runner.run_frames(2)
    assert _grounded_at(runner, GROUND_REST)
    # full jump: rises THROUGH the platform, falls back, lands ON it
    runner.set_input(0, a=True)
    runner.run_frames(30)
    runner.set_input(0)
    _wait(runner, lambda: _grounded_at(runner, PLAT_REST), 180,
          f"landing ON the platform (rest {PLAT_REST})")
    # apex proves the box top passed above the platform row (through it)
    assert runner.read_u16(WR, APEX) < PLAT_REST - 4, "arc never rose above the platform"
    # stands stably (grounded holds across a second of frames)
    for _ in range(10):
        runner.run_frames(6)
        assert _grounded_at(runner, PLAT_REST), "standing on the platform flickered"
    # walk off the right edge (col 12 ends at x 103) -> falls to the ground
    runner.set_input(0, right=True)
    _wait(runner, lambda: _grounded_at(runner, GROUND_REST), 300,
          "falling off the platform edge back to the ground")
    runner.set_input(0)


def test_pit_death_plane_respawns(runner):
    _load(runner)
    assert runner.read_u16(WR, DEATHS) == 0
    # ground ends at col 19 (x 159) — walk right into the gap
    runner.set_input(0, right=True)
    _wait(runner, lambda: runner.read_u16(WR, DEATHS) >= 1, 600,
          "pit fall + death plane")
    runner.set_input(0)
    runner.run_frames(4)
    # respawned at the start (held-Right races the release by a few frames,
    # so the respawned player may have walked a little before we let go)
    px = runner.read_u16(WR, PXM)
    assert 16 <= px <= 80, f"did not respawn at the start (x={px})"
    _wait(runner, lambda: _grounded_at(runner, GROUND_REST), 60, "respawn rest")
