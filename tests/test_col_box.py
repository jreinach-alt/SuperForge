"""Boundary regression for the col_box macro (the dedicated run-gate).

col_box_test.asm records four hand-computed AABB cases in the debug region;
this loads the built ROM and asserts them, so the STRICT-overlap boundary has
a standing guard (not just the live exercise in the sprite_game catch cycle).
"""
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def test_col_box_boundaries(runner):
    rom = BUILD / "col_box_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"      # booted
    assert runner.read_u16(WR, 0xE008) == 1                 # ran to completion
    assert runner.read_u16(WR, 0xE00A) == 1, "overlapping boxes should overlap"
    assert runner.read_u16(WR, 0xE00C) == 0, "disjoint boxes should not overlap"
    assert runner.read_u16(WR, 0xE00E) == 1, "1px-overlapping boxes should overlap"
    assert runner.read_u16(WR, 0xE010) == 0, "edge-touching (0px) is STRICT non-overlap"
