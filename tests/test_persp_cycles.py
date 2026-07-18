"""Per-frame CPU-budget measurement for a LIVE second Mode-7 camera on the
split_h_persp_demo perspective rail (kit rule #1: measure, never estimate).

This is the authoritative measurement behind the shipping decision that camera B
uses PRECOMPUTED poses rather than a second LIVE per-scanline solve. It runs the
engine's per-frame table build (sf_mode7_cam + sf_mode7_tick -> pv_rebuild)
back-to-back while a minimal NMI counts frames, HDMA off, and computes

    master_clocks_per_tick = frames * 357368 / ticks   (one NTSC frame = 1364*262)

Findings pinned here (measured; see docs/guides/split_h.md "live-B budget"):
  * A SINGLE full per-scanline solve at camera A's spec (224 lines, interp1) is
    ~492,000 mc = ~138% of ONE 60fps frame. It already exceeds one frame ALONE.
  * The cheapest genuine second live solve for camera B's 112-line band
    (quarter-res, interp4) is ~185,000 mc = ~52% of a frame; added to camera A
    the combined work is ~190% of a frame. The naive both-full worst case is
    ~977,000 mc = ~273%.
  * => A second live per-scanline solve CANNOT fit a 60fps CPU frame by any
    incremental route (half-res / band-only / time-slice). Precomputed poses
    remain the shipping path. This test guards that verdict against regression
    (and guards camera A's own solve from ballooning further).

NOTE: the perspective rail's E010 heartbeat (= FRAME_COUNTER) is the NMI/VBlank
counter; it advances at ~60/sec REGARDLESS of game-loop overrun (the HDMA
display is decoupled from the CPU solve rate), so it is a LIVENESS check, not a
CPU-budget gate. This free-running ticks/frames method is the budget instrument.
"""
import subprocess
from pathlib import Path

import pytest

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

WR = MemoryType.SnesWorkRam
FRAME_MC = 1364 * 262            # 357,368 master clocks per NTSC frame

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
INCLUDES = ["-I", "infrastructure/rom_template", "-I", "lib/macros", "-I", "engine"]
LDCFG = "infrastructure/rom_template/lorom_64k.cfg"
SRC = "tests/persp_cycles_test.asm"


def _build(tag, defs):
    obj = BUILD / f"persp_cycles_{tag}.o"
    sfc = BUILD / f"persp_cycles_{tag}.sfc"
    BUILD.mkdir(exist_ok=True)
    dflags = []
    for d in defs:
        dflags += ["-D", d]
    ca = subprocess.run(["ca65", "--cpu", "65816", *INCLUDES, *dflags, SRC,
                         "-o", str(obj)], cwd=str(ROOT), capture_output=True, text=True)
    if ca.returncode != 0:
        pytest.skip(f"ca65 failed for {tag}:\n{ca.stderr}")
    ld = subprocess.run(["ld65", "-C", LDCFG, str(obj), "-o", str(sfc)],
                        cwd=str(ROOT), capture_output=True, text=True)
    if ld.returncode != 0:
        pytest.skip(f"ld65 failed for {tag}:\n{ld.stderr}")
    return sfc


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _cost_pct(runner, sfc):
    runner.load_rom(str(sfc), run_seconds=3.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", f"{sfc.name} did not boot"
    ticks = runner.read_u32(WR, 0xE030)
    frames = runner.read_u32(WR, 0xE034)
    assert ticks > 20 and frames > 50, \
        f"measurement window too small: ticks={ticks} frames={frames}"
    mc = frames * FRAME_MC / ticks
    return 100.0 * mc / FRAME_MC, mc


def test_single_full_solve_exceeds_one_frame(runner):
    """Camera A's spec solve (224 lines, interp1) alone is >100% of a 60fps
    frame — so there is NEGATIVE headroom for a second live solve."""
    sfc = _build("full", ["CY_L0=0", "CY_L1=224", "CY_INTERP=1", "CY_ANGLE=1"])
    pct, mc = _cost_pct(runner, sfc)
    assert pct > 110.0, (
        f"single full per-scanline solve measured {pct:.1f}% of a frame "
        f"({mc:.0f} mc) — expected >110% (regression if it dropped, but the "
        f"live-B infeasibility argument rests on this being >100%)")


def test_cheapest_second_solve_pushes_over_budget(runner):
    """The cheapest genuine second live solve for camera B's band (112 lines,
    quarter-res interp4) added to camera A's full solve exceeds 100% of a frame:
    live-B does not fit by any incremental route."""
    full_pct, _ = _cost_pct(runner, _build(
        "full", ["CY_L0=0", "CY_L1=224", "CY_INTERP=1", "CY_ANGLE=1"]))
    band_pct, _ = _cost_pct(runner, _build(
        "band2i4", ["CY_L0=112", "CY_L1=224", "CY_INTERP=4", "CY_ANGLE=1"]))
    combined = full_pct + band_pct
    assert band_pct > 25.0, (
        f"cheapest band-2 second solve unexpectedly cheap ({band_pct:.1f}%) — "
        f"re-open the live-B feasibility question if this holds up")
    assert combined > 100.0, (
        f"camera A ({full_pct:.1f}%) + cheapest camera-B second solve "
        f"({band_pct:.1f}%) = {combined:.1f}% of a frame — live-B would only be "
        f"feasible if this were <100%")


def test_worst_case_two_full_solves(runner):
    """Both cameras solving full every frame is ~2x one solve — the naive
    live-B worst case, far over budget."""
    sfc = _build("double", ["CY_DOUBLE=1", "CY_L0=0", "CY_L1=224",
                            "CY_INTERP=1", "CY_ANGLE=1"])
    pct, mc = _cost_pct(runner, sfc)
    assert pct > 200.0, (
        f"two full solves measured {pct:.1f}% ({mc:.0f} mc) — expected ~273%")


def test_rail_solve_fits_one_frame(runner):
    """STANDING SOLVE-BUDGET GATE (the Phase-P shipped optimization): the
    perspective rail's per-frame CPU SOLVE — camera A rebuilding the WHOLE floor
    (0..224) every frame at the demo's SHIPPED interp4 (split_h_persp_demo
    A_INTERP default) — fits within ONE 60fps CPU frame.

    SOLVE-ONLY, HDMA-off (what this instrument isolates) — it makes NO claim
    about the integrated demo loop's cadence: with the rail's CH5|CH6 HDMA
    steal the solve is ~92.6%, and the full loop (solve + the ~85k mc = 23.9%
    band-2 splice + origin restamp) closes in 2 frames = 30 Hz pose motion at
    HEAD (PR #223 independent review, M1). The in-situ loop-rate gate is
    test_split_h_persp_demo.py::test_cadence_true_60fps_in_situ (xfail at HEAD).

    Measured: interp1 full solve = ~138% (did NOT fit); interp4 full solve =
    ~87% (the solve fits). This gate FAILS if a future change pushes camera A's
    per-frame solve back over one frame. The paired
    test_single_full_solve_exceeds_one_frame documents the interp1 baseline that
    motivated the drop to interp4."""
    sfc = _build("i4full", ["CY_L0=0", "CY_L1=224", "CY_INTERP=4", "CY_ANGLE=1"])
    pct, mc = _cost_pct(runner, sfc)
    assert pct < 100.0, (
        f"rail per-frame solve measured {pct:.1f}% of a 60fps frame ({mc:.0f} mc) "
        f"— the SOLVE must stay < 100% (one frame); interp4 measured ~87%, so a "
        f"regression has pushed it over.")
