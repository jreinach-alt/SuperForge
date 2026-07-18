"""Run-gate for the tile-collision macros: col_map, sf_tile_flags, sf_solid_box.

The ROM builds a known map (solid wall, unflagged floor, non-solid hazard) and
records hand-computed query results; this reads them back, including the
flag-bit independence, out-of-bounds, and +7-corner edge-adjacency contracts,
plus the gfxmode tilemap-dimension fix col_map's bounds check depends on.
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
    rom = BUILD / "col_map_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


def test_boots_and_completes(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE008) == 1


def test_col_map_solid_and_unflagged(runner):
    assert runner.read_u16(WR, 0xE010) == 1, "solid wall tile not detected"
    assert runner.read_u16(WR, 0xE012) == 0, "unflagged floor tile reads solid"
    assert runner.read_u16(WR, 0xE014) == 0, "empty cell reads solid"


def test_col_map_flag_bit_independence(runner):
    assert runner.read_u16(WR, 0xE016) == 1, "hazard bit not detected on hazard tile"
    assert runner.read_u16(WR, 0xE018) == 0, "solid bit leaks onto hazard tile"


def test_col_map_out_of_bounds_returns_zero(runner):
    assert runner.read_u16(WR, 0xE01A) == 0, "OOB query did not return 0"


def test_solid_box_corners(runner):
    assert runner.read_u16(WR, 0xE01C) == 1, "box straddling into the wall missed"
    assert runner.read_u16(WR, 0xE01E) == 0, "clear box reads solid"
    assert runner.read_u16(WR, 0xE020) == 0, \
        "edge-adjacent box collides — the +7 far-corner contract is broken"


def test_gfxmode_sets_tilemap_dims(runner):
    assert runner.read_bytes(WR, 0xE022, 1)[0] == 32, \
        "gfxmode did not set TILEMAP_WIDTH_BG1 (col_map bounds check broken)"
