"""Measurement gate for the flagship's two per-frame service calls (kit rule
#1: measure on the emulator, never estimate). The platformer game loop leaves
sf_parallax_tick and sf_bright_fade_tick running every frame; both carry a
cycle-cost comment in main.asm, and this pins those numbers to a real
measurement instead of a doc-comment estimate.

METHOD — frame-budget differential (the bend_cycles_test technique). Three ROMs
run the SAME back-to-back counter loop; two put a routine under test at the top
of the loop, one runs the loop empty:

    master_clocks_per_iter = frames * 357368 / iterations   (NTSC frame =
    1364 * 262 master clocks); 1 CPU fast cycle = 6 master clocks (WRAM).

Subtracting the empty-loop baseline from a routine ROM's per-iteration cost
isolates the routine, canceling the counter overhead. The asserted bounds are
loose sanity rails; the VALUE THIS TEST PRODUCES is the printed measured cycle
count, which is what the main.asm comments cite.
"""
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

FRAME_MC = 1364 * 262            # 357,368 master clocks per NTSC frame
MC_PER_CYC = 6                  # WRAM fast cycle = 6 master clocks


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _mc_per_iter(runner, rom_name, run_seconds=2.0):
    rom = BUILD / f"{rom_name}.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=run_seconds)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", f"{rom_name} never booted"
    iters = runner.read_u32(WR, 0xE030)
    frames = runner.read_u32(WR, 0xE034)
    assert iters > 1000 and frames > 50, \
        f"{rom_name} window too small: iters={iters} frames={frames}"
    return frames * FRAME_MC / iters


def test_parallax_and_fade_tick_costs(runner):
    base = _mc_per_iter(runner, "plat_cyc_base_test")
    parallax = _mc_per_iter(runner, "plat_cyc_parallax_test")
    fade = _mc_per_iter(runner, "plat_cyc_fade_test")

    parallax_cyc = (parallax - base) / MC_PER_CYC
    fade_cyc = (fade - base) / MC_PER_CYC

    print(f"\nframe-budget baseline (empty loop): {base:.1f} mc/iter")
    print(f"sf_parallax_tick   : {parallax - base:.1f} mc = {parallax_cyc:.1f} CPU cyc/frame")
    print(f"sf_bright_fade_tick (idle): {fade - base:.1f} mc = {fade_cyc:.1f} CPU cyc/frame")

    # loose sanity rails — the point is the printed measurement the main.asm
    # comments cite, not a tight pin. Parallax reads world-X, runs two 16-bit
    # ratio multiplies, and emits the 3-band table (measured ~690 cyc); the idle
    # fade tick is the sep/rep-framed fast-exit (measured ~35 cyc). The old doc
    # estimates (~150 / ~10) counted only the byte stores / routine body and
    # omitted the multiplies and macro framing. Bounds are deterministic: the
    # frame-budget method reads in-ROM counters, so it is host-load-independent.
    assert 450 < parallax_cyc < 1000, \
        f"sf_parallax_tick out of expected range: {parallax_cyc:.1f} cyc"
    assert 10 < fade_cyc < 80, \
        f"sf_bright_fade_tick idle out of expected range: {fade_cyc:.1f} cyc"
