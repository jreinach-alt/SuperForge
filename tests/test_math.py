"""Run-gate for the sf_math macros: trig / sqrt / atan2 / random.

Debug-region ROM (tests/math_test.asm): the ROM computes hand-checkable
cases on the emulated CPU and this test reads the results back from WRAM.
All expectations below are MEASURED engine outputs (verified against the
LUT convention: angles 0..255 = one turn; the sine table stores the
negated sine, so sin(64) = -$0100 and atan2 is its inverse pair).
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
    rom = BUILD / "math_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    r.load_rom(str(rom), run_seconds=1.0)
    yield r
    r.stop()


def test_boots_and_completes(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE008) == 1


def test_sin_cos_key_angles(runner):
    # negated-sine convention: a quarter turn reads -1.0
    assert runner.read_u16(WR, 0xE00A) == 0x0000      # sin(0)
    assert runner.read_u16(WR, 0xE00C) == 0xFF00      # sin(64)  = -1.0
    assert runner.read_u16(WR, 0xE00E) == 0x0100      # sin(192) = +1.0
    assert runner.read_u16(WR, 0xE010) == 0x0100      # cos(0)   = +1.0
    assert runner.read_u16(WR, 0xE012) == 0xFF00      # cos(128) = -1.0


def test_sqrt(runner):
    assert runner.read_u16(WR, 0xE014) == 0x0200      # sqrt(4.0)  = 2.0
    assert runner.read_u16(WR, 0xE016) == 0x0000      # sqrt(0)    = 0
    assert runner.read_u16(WR, 0xE018) == 0x0500      # sqrt(25.0) = 5.0


def test_atan2_cardinals(runner):
    # the inverse pair of the negated-sine convention
    assert runner.read_u16(WR, 0xE01A) == 0x0000      # atan2(+1,  0)
    assert runner.read_u16(WR, 0xE01C) == 0x0040      # atan2( 0, +1) = 1/4 turn
    assert runner.read_u16(WR, 0xE01E) == 0x0080      # atan2(-1,  0) = 1/2 turn
    assert runner.read_u16(WR, 0xE020) == 0x00C0      # atan2( 0, -1) = 3/4 turn


def test_rnd_range_and_determinism(runner):
    draws = [runner.read_u16(WR, 0xE030 + 2 * i) for i in range(32)]
    replay = [runner.read_u16(WR, 0xE070 + 2 * i) for i in range(8)]
    other = [runner.read_u16(WR, 0xE080 + 2 * i) for i in range(8)]

    assert all(d < 16 for d in draws), f"sf_rnd #16 out of range: {draws}"
    assert len(set(draws)) >= 6, f"draws suspiciously non-random: {draws}"
    assert draws[:8] == replay, "same seed must replay the same sequence"
    assert draws[:8] != other, "different seed must give a different sequence"
