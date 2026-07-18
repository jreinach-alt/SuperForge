"""Run-gate for the stomp macro: sf_stomp_check.

Six hand-crafted contact states exercise every classification branch; each
case records the result code AND the side effects (ealive, vy) so the tests
verify that a stomp kills + bounces, and that nothing else does.
"""
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

BOUNCE = 0x10000 - 0x0300   # -SF_BOUNCE_VEL as unsigned 16-bit
NONE, STOMP, HURT = 0, 1, 2


@pytest.fixture(scope="module")
def cases():
    r = MesenRunner()
    rom = BUILD / "stomp_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    r.load_rom(str(rom), run_seconds=0.5)
    assert r.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert r.read_u16(WR, 0xE008) == 1
    out = []
    for i in range(6):
        base = 0xE010 + 6 * i
        out.append((r.read_u16(WR, base),          # result
                    r.read_u16(WR, base + 2),      # ealive after
                    r.read_u16(WR, base + 4)))     # vy after
    r.stop()
    return out


def test_clean_stomp_kills_and_bounces(cases):
    res, alive, vy = cases[0]
    assert res == STOMP, f"result {res}, want STOMP"
    assert alive == 0, "enemy survived a stomp"
    assert vy == BOUNCE, f"vy {vy:04x}, want bounce {BOUNCE:04x}"


def test_standing_side_contact_hurts(cases):
    res, alive, vy = cases[1]
    assert res == HURT and alive == 1 and vy == 0, cases[1]


def test_rising_from_below_hurts(cases):
    res, alive, vy = cases[2]
    assert res == HURT, f"result {res}, want HURT"
    assert alive == 1 and vy == 0x10000 - 0x0200, "side effects on a hurt"


def test_no_overlap_is_nothing(cases):
    res, alive, vy = cases[3]
    assert res == NONE and alive == 1 and vy == 0x0100, cases[3]


def test_dead_enemy_is_transparent(cases):
    res, alive, vy = cases[4]
    assert res == NONE, "dead enemy still classified contact"
    assert alive == 0 and vy == 0x0100, "dead enemy had side effects"


def test_deep_falling_contact_hurts(cases):
    res, alive, vy = cases[5]
    assert res == HURT, f"7px-deep falling contact: {res}, want HURT"
    assert alive == 1 and vy == 0x0100, "side effects on a deep hit"
