"""What players 3 and 4 cost per frame, measured on the shipped binary (docs/102 MT-8).

CLAUDE.md rule 1: a cycle count is measured, never estimated. METHOD — the
labelled-twin pattern `m7_dungeon` established: `make fp-labels` assembles
four_pads a second time with `-g` / `-Ln` and `cmp`s the twin against the
shipping ROM, so the label file is proved to describe the binary under test.
Two execution breakpoints, on `fp_pads_begin` (the `jsr mtap_read` in the
main loop) and `fp_pads_end` (the instruction after it), bracket the call;
the master-clock difference between consecutive hits is the whole cost of
the call, jsr and rts included. Sampled over many frames and reported as
min / max, because the D7 guard's spin is paid only on frames whose call
lands in VBlank before or after the automatic read rather than during it.

Both configurations, because the claim is two-sided: WITHOUT an adapter the
call is a flag test (and every rail that does not compose `mtap` pays
nothing at all — it has no call); WITH one it stays under two scanlines.

This module drives the legacy MesenRunner (breakpoints are its surface), so
it is a module of its own — a Machine and a runner never share one.
"""
import sys
from pathlib import Path

import pytest

from conftest import run_make

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mesen_runner as mr  # noqa: E402

ROM = SUPERFORGE / "build" / "four_pads.sfc"
LBL = SUPERFORGE / "build" / "four_pads.lbl"
MEM = MemoryType.SnesMemory

MC_PER_LINE = 1364                 # master cycles per NTSC scanline (fullsnes)
BUDGET_PRESENT = 2 * MC_PER_LINE   # docs/102: "well under 2 scanlines"
BUDGET_ABSENT = 200                # jsr + lda dp + bne + rts, with margin
SAMPLES = 24


@pytest.fixture(scope="module", autouse=True)
def labels_built():
    r = run_make("fp-labels")
    assert r.returncode == 0, f"make fp-labels failed:\n{r.stdout}\n{r.stderr}"
    yield


def _labels():
    out = {}
    for line in LBL.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "al":
            out[parts[2].lstrip(".")] = int(parts[1], 16)
    return out


def _measure(port2):
    lab = _labels()
    begin, end = lab["fp_pads_begin"], lab["fp_pads_end"]
    assert end - begin == 3, "fp_pads_begin..end must be exactly one `jsr abs`"
    runner = MesenRunner(port2=port2)
    costs = []
    try:
        runner.boot_rom(str(ROM), frames=60)
        detected = runner.read_u16(MemoryType.SnesWorkRam, _mtap_on())
        runner.debug_break()
        with runner.breakpoints([(MEM, begin, "exec"), (MEM, end, "exec")]):
            t0 = None
            while len(costs) < SAMPLES:
                # EMULATED-frame budget: a False is a claim about the ROM.
                assert runner.run_to_break(max_frames=10), "no breakpoint hit"
                st = runner.snes_state_snapshot()
                if st.cpu_pc & 0xFFFF == begin & 0xFFFF:
                    t0 = st.master_clock
                elif t0 is not None:
                    costs.append(st.master_clock - t0)
                    t0 = None
    finally:
        runner.stop()
        mr.ensure_port2_device(mr.PORT2_PAD)     # hand the plain pad back
    return detected, costs


def _mtap_on():
    import json
    jmap = json.loads((SUPERFORGE / "build" / "fp" / "symbol_map.json").read_text())
    return next(p["start"] for p in jmap["globals"] if p["sym"] == "ES_MTAP_ON")


def test_the_absent_path_is_a_flag_test():
    detected, costs = _measure(mr.PORT2_PAD)
    assert detected == 0, "a plain pad in port 2 was detected as an adapter"
    print(f"\nmtap_read, no adapter: min {min(costs)} max {max(costs)} mc "
          f"over {len(costs)} frames")
    assert max(costs) < BUDGET_ABSENT, costs


def test_the_present_path_stays_under_two_scanlines():
    detected, costs = _measure(mr.PORT2_MULTITAP)
    assert detected == 1, "the adapter was not detected"
    lo, hi = min(costs), max(costs)
    print(f"\nmtap_read, adapter: min {lo} max {hi} mc "
          f"({hi / MC_PER_LINE:.2f} scanlines worst) over {len(costs)} frames")
    assert hi < BUDGET_PRESENT, (
        f"worst {hi} mc = {hi / MC_PER_LINE:.2f} scanlines; budget "
        f"{BUDGET_PRESENT} mc")
