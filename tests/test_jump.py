"""Run-gate for the jump-physics macros: sf_jump + sf_physics_step.

The ROM records the pixel y after EVERY physics step across three scripted
traces; these tests verify the whole state cycle — ascent, apex height and
timing, head-bump snap, descent, terminal-velocity clamp, pixel-exact landing,
and rest stability — per the "apex AND landing" / state-cycle disciplines.
"""
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

REST = 200          # rest pixel y on the ground row
APEX = REST - 38    # analytic apex: sum(4.5 - 0.25k, k=1..18) = 38.25 px
BUMP = 176          # head-bump snap: first row below the ceiling tile


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "jump_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


@pytest.fixture(scope="module")
def traces(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE008) == 1
    return (list(runner.read_bytes(WR, 0xE040, 64)),
            list(runner.read_bytes(WR, 0xE080, 64)),
            list(runner.read_bytes(WR, 0xE0C0, 64)))


def test_jump_full_cycle(traces):
    t1 = traces[0]
    apex = min(t1)
    apex_i = t1.index(apex)
    assert abs(apex - APEX) <= 3, f"apex y={apex}, want ~{APEX} (height off)"
    assert 14 <= apex_i <= 22, f"apex at step {apex_i}, want ~18 (timing off)"
    # ascent: non-increasing to the apex; descent: non-decreasing after it
    assert all(a >= b for a, b in zip(t1[:apex_i], t1[1:apex_i + 1])), \
        "ascent not monotonic"
    assert all(a <= b for a, b in zip(t1[apex_i:], t1[apex_i + 1:])), \
        "descent not monotonic"


def test_landing_exact_and_rest_stable(runner, traces):
    t1 = traces[0]
    assert t1[-1] == REST, f"final y={t1[-1]}, want {REST}"
    land_i = next(i for i in range(len(t1)) if i > 20 and t1[i] == REST)
    assert all(y == REST for y in t1[land_i:]), \
        "rest not stable — y drifts after landing (embed/hover bug)"
    assert max(t1) == REST, f"overshoot below rest: max y={max(t1)}"
    assert runner.read_u16(WR, 0xE010) == 1, "grounded flag not set after T1"
    assert runner.read_u16(WR, 0xE012) == 0, "vy not zeroed at rest"
    assert runner.read_u16(WR, 0xE014) == REST


def test_head_bump_snaps_below_ceiling(traces):
    t2 = traces[1]
    assert min(t2) == BUMP, \
        f"bump min y={min(t2)}, want exactly {BUMP} (snap below the tile)"
    bump_i = t2.index(BUMP)
    assert bump_i < 12, f"bump at step {bump_i} — should hit early, ~step 7"
    assert t2[-1] == REST and all(y == REST for y in t2[-10:]), \
        "did not settle back at rest after the bump"


def test_fall_clamped_at_terminal_velocity(traces):
    t3 = traces[2]
    deltas = [b - a for a, b in zip(t3, t3[1:])]
    assert all(d >= 0 for d in deltas), "fall not monotonic"
    assert max(deltas) <= 4, f"fall step {max(deltas)} px > SF_MAX_FALL (4)"
    assert 4 in deltas, "terminal velocity never reached (clamp untested)"
    assert t3[-1] == REST and all(y == REST for y in t3[-10:]), \
        "did not land at rest after the fall"
