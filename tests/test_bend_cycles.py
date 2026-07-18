"""Measurement gate for the per-frame bend tick cost (kit rule #1: measure on
the emulator, never estimate).

bend_cycles_test.asm runs hdma_update_hofs_curve (sf_bend_tick) back-to-back
with the NMI counting frames; the cost in master clocks is
    frames * 357368 / rebuilds      (one NTSC frame = 1364 * 262 master clocks).

NOTE: bend_cycles_test arms a PURE ROLL (base scroll 0), so v1.1 takes the
E-SLIDE pointer-slide fast-path — this ROM now measures the SLIDE cost
(~1,300 mc, ~0.4%). The OPTIMIZED REFILL cost (~73,900 mc, ~20.7%, base scroll
nonzero) and the slide/refill split are pinned by test_bend_slide.py via
bend_cycles_refill_test. This test pins the slide near-zero so a regression that
accidentally forces a rebuild on the pure-roll path is caught. It is a
measurement assertion, not a pixel render — the rendered-output proofs live in
test_bend.py / test_bend_layer.py / test_bend_hscroll.py / test_bend_reverse.py
/ test_bend_slide.py.
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


def test_bend_pure_roll_tick_is_near_zero(runner):
    rom = BUILD / "bend_cycles_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    rebuilds = runner.read_u32(WR, 0xE030)
    frames = runner.read_u32(WR, 0xE034)
    assert rebuilds > 100 and frames > 50, \
        f"measurement window too small: rebuilds={rebuilds} frames={frames}"

    mc_per = frames * FRAME_MC / rebuilds
    pct = 100.0 * mc_per / FRAME_MC

    # Pure roll (base scroll 0) → the E-SLIDE pointer-slide fast-path: ~1,300 mc
    # (~0.4%). Pin near-zero so a regression that forces a rebuild on the
    # pure-roll path (the whole point of E-SLIDE) is caught. (The refill cost is
    # pinned by test_bend_slide.py via bend_cycles_refill_test.)
    assert mc_per < 7000, (
        f"pure-roll tick not near-zero: {mc_per:.0f} mc ({pct:.2f}% of a frame) "
        f"— E-SLIDE expects ~1,300 mc (~0.4%); did the slide path stop firing?"
    )
