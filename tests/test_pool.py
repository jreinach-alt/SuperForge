"""sf_pool run-gate: the full slot lifecycle on the emulator.

The ROM drives a 4-slot pool through empty -> filling -> kill -> REUSE ->
full/overflow -> kill_x, recording each result in the debug region. Per the
state-cycle discipline this covers every transition the macros claim, not
just the spawn-only happy path.
"""
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam

EXPECT = [
    (0xE00A, 0x0000, "count after init"),
    (0xE00C, 0x0000, "1st spawn offset"),
    (0xE00E, 0x0002, "2nd spawn offset"),
    (0xE010, 0x0004, "3rd spawn offset"),
    (0xE012, 0x0003, "count with 3 live"),
    (0xE014, 0x0002, "spawn reuses the killed slot's hole"),
    (0xE016, 0x0006, "4th spawn offset"),
    (0xE018, 0xFFFF, "spawn when full returns $FFFF"),
    (0xE01A, 0x0004, "count when full"),
    (0xE01C, 0x0003, "count after kill_x slot 0"),
]


def test_pool_full_lifecycle():
    rom = ROOT / "build" / "pool_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        assert r.read_bytes(WR, 0xE000, 4) == b"SFDB", "ROM did not boot"
        assert r.read_u16(WR, 0xE008) == 1, "ROM did not run to completion"
        for addr, want, what in EXPECT:
            got = r.read_u16(WR, addr)
            assert got == want, f"{what}: ${addr:04X} = {got:#06x}, want {want:#06x}"
    finally:
        r.stop()
