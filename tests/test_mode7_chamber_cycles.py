"""Per-frame CPU-cost gate for the Mode 7 chamber (kit rule #1: measure on the
emulator, never estimate).

mode7_chamber_cycles_test runs the chamber's per-frame engine work (sf_mode7_cam
+ sf_mode7_tick) back-to-back while a minimal NMI counts frames; the cost is
    master_clocks_per_tick = frames * 357368 / ticks   (NTSC frame = 1364*262).

The chamber holds the Mode 7 ANGLE constant, so the tick takes the cheap ORIGIN
path (mode7_set_origin: recompute M7X/M7Y) and NEVER the per-frame pv_rebuild.
Measured ~3,640 mc (~1.0% of a frame). This gate pins it LOW so a regression that
makes the chamber rebuild the full per-scanline matrix every frame is caught —
that path costs ~431,000 mc (~121% of a frame, i.e. it cannot fit at 60 fps),
which is exactly why the chamber rolls via posy (origin) instead of rotating.

Measurement assertion, not a render — the visual proofs live in
test_mode7_chamber.py.
"""
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

FRAME_MC = 1364 * 262            # 357,368 master clocks per NTSC frame


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def test_chamber_per_frame_cost_is_origin_path_not_rebuild(runner):
    rom = BUILD / "mode7_chamber_cycles_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=3.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    ticks = runner.read_u32(WR, 0xE030)
    frames = runner.read_u32(WR, 0xE034)
    assert ticks > 1000 and frames > 50, \
        f"measurement window too small: ticks={ticks} frames={frames}"

    mc_per = frames * FRAME_MC / ticks
    pct = 100.0 * mc_per / FRAME_MC

    # Origin path measures ~3,640 mc (~1.0%). Gate well below the pv_rebuild path
    # (~431,000 mc, ~121%) so any regression that forces a per-frame rebuild trips
    # this; generous headroom above the real cost to avoid emulator-timing flake.
    assert mc_per < 12000, (
        f"chamber per-frame cost {mc_per:.0f} mc ({pct:.2f}% of a frame) is far "
        f"above the ~3,640 mc origin path — did the tick start rebuilding the "
        f"full per-scanline matrix every frame (the ~121%-of-a-frame path)?"
    )
