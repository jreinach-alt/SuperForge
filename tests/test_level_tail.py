"""Run-gate for the S3 sf_level extensions — every assertion ON THE SEAM.

The world places the one-way platform (x 224-295) and the patrol ledge
(x 208-311) across the x=256 page boundary, the exact gap these extensions
close (sf_patrol_step was layer-1-only; the old integrator had no one-way).
State cycles: patrol crosses the seam BOTH directions and ledge-turns at
both ends without overhang; the player jumps THROUGH the platform, lands ON
it, stands across the seam, walks off; the pit death-plane respawns.
"""
import time
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam

PXM, PIXY, GROUNDED, DEATHS, EXM, EDIR = 0xE010, 0xE012, 0xE014, 0xE016, 0xE018, 0xE01A

LEDGE_L, LEDGE_R = 208, 304     # enemy box bounds on the ledge (x 208..311-7)
PLAT_REST = 152                 # platform row 20: top 160, box rest 152
GROUND_REST = 184


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _load(runner):
    rom = ROOT / "build" / "level_tail_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE008) == 1


def _walk_to(runner, x, timeout=25):
    key = "right" if runner.read_u16(WR, PXM) < x else "left"
    runner.set_input(0, **{key: True})
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = runner.read_u16(WR, PXM)
        if (key == "right" and p >= x) or (key == "left" and p <= x):
            break
        runner.run_frames(4)
    runner.set_input(0)
    runner.run_frames(3)
    assert abs(runner.read_u16(WR, PXM) - x) < 16, f"could not walk to x={x}"


def test_patrol_crosses_seam_and_ledge_turns(runner):
    _load(runner)
    xs, dirs = [], set()
    for _ in range(60):                      # ~12s: multiple full beats
        xs.append(runner.read_u16(WR, EXM))
        dirs.add(runner.read_u16(WR, EDIR))
        runner.run_frames(12)
    assert dirs == {0, 1}, "enemy never turned"
    assert any(x < 240 for x in xs) and any(x > 272 for x in xs), \
        f"enemy never crossed the page seam (x range {min(xs)}..{max(xs)})"
    assert min(xs) >= LEDGE_L and max(xs) <= LEDGE_R, \
        f"enemy overhung the ledge ({min(xs)}..{max(xs)}, ledge {LEDGE_L}..{LEDGE_R})"


def test_oneway_platform_across_the_seam(runner):
    _load(runner)
    # under the platform, left of the seam
    _walk_to(runner, 236)
    assert runner.read_u16(WR, PIXY) == GROUND_REST
    # full jump: THROUGH the platform from below, lands ON it
    runner.set_input(0, a=True)
    runner.run_frames(30)
    runner.set_input(0)
    deadline = time.time() + 6
    while time.time() < deadline:
        if (runner.read_u16(WR, GROUNDED) == 1
                and runner.read_u16(WR, PIXY) == PLAT_REST):
            break
        runner.run_frames(3)
    assert runner.read_u16(WR, PIXY) == PLAT_REST, \
        f"did not land ON the platform (y={runner.read_u16(WR, PIXY)})"
    # walk RIGHT ACROSS the seam staying grounded on the platform
    runner.set_input(0, right=True)
    deadline = time.time() + 10
    while runner.read_u16(WR, PXM) < 272 and time.time() < deadline:
        runner.run_frames(2)
        assert runner.read_u16(WR, PIXY) == PLAT_REST, \
            f"fell through at x={runner.read_u16(WR, PXM)} (the seam bug)"
    runner.set_input(0)
    assert runner.read_u16(WR, PXM) >= 272, "never crossed the seam on the platform"
    # walk LEFT back across the seam (both crossing directions covered) and
    # off the WEST end -> falls to the ground (the east end drops into the
    # pit's drift range — deliberate level design for the pit test)
    runner.set_input(0, left=True)
    deadline = time.time() + 15
    while time.time() < deadline:
        if (runner.read_u16(WR, GROUNDED) == 1
                and runner.read_u16(WR, PIXY) == GROUND_REST):
            break
        runner.run_frames(3)
    runner.set_input(0)
    assert runner.read_u16(WR, PIXY) == GROUND_REST, "did not fall off the west end"


def test_pit_respawns_in_level_world(runner):
    _load(runner)
    assert runner.read_u16(WR, DEATHS) == 0
    # the pit is at x 320-383; walk right until the death plane trips
    runner.set_input(0, right=True)
    deadline = time.time() + 40
    while runner.read_u16(WR, DEATHS) == 0 and time.time() < deadline:
        runner.run_frames(8)
    runner.set_input(0)
    runner.run_frames(4)
    assert runner.read_u16(WR, DEATHS) >= 1, "pit never tripped the death plane"
    assert runner.read_u16(WR, PXM) < 80, "did not respawn at the start"
