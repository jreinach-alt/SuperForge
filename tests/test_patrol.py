"""Run-gate for the enemy patrol macro: sf_patrol_step.

The ROM records enemy x after EVERY patrol step across two scripted traces
(wall-bounded and ledge-bounded); these tests verify the whole bounce cycle —
exact turn bounds on both sides, multiple round trips, constant speed, and
that the ledge patroller never overhangs its platform.
"""
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

# T1: walls at px 32..39 and 112..119 -> box (8px) bounces between 40 and 104
T1_MIN, T1_MAX = 40, 104
# T2: platform px 144..199 -> leading-corner ledge turns at 144 and 192
T2_MIN, T2_MAX = 144, 192


@pytest.fixture(scope="module")
def traces():
    r = MesenRunner()
    rom = BUILD / "patrol_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    r.load_rom(str(rom), run_seconds=0.5)
    assert r.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert r.read_u16(WR, 0xE008) == 1
    t1 = list(r.read_bytes(WR, 0xE040, 200))
    t2 = list(r.read_bytes(WR, 0xE110, 200))
    r.stop()
    return t1, t2


def _turn_steps(trace):
    """Turn frames are the only zero-move steps (direction flip, no move)."""
    return [i for i in range(1, len(trace)) if trace[i] == trace[i - 1]]


def test_wall_patrol_exact_bounds(traces):
    t1 = traces[0]
    assert min(t1) == T1_MIN, f"left wall bound {min(t1)}, want {T1_MIN}"
    assert max(t1) == T1_MAX, f"right wall bound {max(t1)}, want {T1_MAX}"
    assert t1.count(T1_MAX) >= 2 and t1.count(T1_MIN) >= 1, \
        "fewer than 1.5 round trips in 200 steps"


def test_wall_patrol_constant_speed_and_turns(traces):
    t1 = traces[0]
    deltas = [abs(b - a) for a, b in zip(t1, t1[1:])]
    # every step moves exactly SPEED px except the turn frames (no move)
    assert set(deltas) <= {0, 1}, f"step sizes {set(deltas)}, want {{0,1}}"
    turns = _turn_steps(t1)
    assert turns, "no turn frames recorded"
    assert all(t1[i] in (T1_MIN, T1_MAX) for i in turns), \
        "zero-move (turn) frame away from a bound — stall bug"


def test_ledge_patrol_never_overhangs(traces):
    t2 = traces[1]
    assert min(t2) == T2_MIN, f"left ledge bound {min(t2)}, want {T2_MIN}"
    assert max(t2) == T2_MAX, f"right ledge bound {max(t2)}, want {T2_MAX}"
    # the entire box must stay on the platform every single step
    assert all(T2_MIN <= x <= T2_MAX for x in t2), "box overhung the ledge"
    assert all(t2[i] in (T2_MIN, T2_MAX) for i in _turn_steps(t2)), \
        "turned away from a ledge bound — phantom ledge"


def test_ledge_patrol_full_coverage(traces):
    # the enemy paces the platform end-to-end (every x in range is visited)
    t2 = traces[1]
    assert set(range(T2_MIN, T2_MAX + 1)) <= set(t2), \
        "patrol does not cover the platform end-to-end"
