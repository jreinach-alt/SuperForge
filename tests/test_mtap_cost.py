"""What players 3 and 4 cost per frame, measured on the shipped binaries (docs/102 MT-8).

CLAUDE.md rule 1: a cycle count is measured, never estimated. METHOD — the
labelled-twin pattern `m7_dungeon` established: `make fp-labels` (and `make
mtap-probe`, for the probe) assembles the ROM a second time with `-g` / `-Ln`
and `cmp`s the twin against the shipping ROM, so the label file is proved to
describe the binary under test. Two execution breakpoints bracket the one
`jsr mtap_read` (its label and the instruction after it); the master-clock
difference between consecutive hits is the whole cost of the call, jsr and
rts included. Sampled over many frames and reported as min / max.

THREE NUMBERS, because the call's cost depends on WHERE in the frame it is
made (docs/102 §7.2):

  * no adapter — a flag test, on `four_pads`. Every rail that does not compose
    `mtap` pays nothing at all: it has no call.
  * with an adapter, called AFTER the automatic read — `four_pads`' timing:
    its loop resumes from an NMI body that outlasts the read, so the D7 guard
    never waits. This is the work itself: the P3 copy, slot 3's twelve
    clocks, the census clock, and — on two calls in every
    census period (33 calls: the MTAP_CENSUS_EVERY = 32 countdown, reloaded
    by the second half) — one half of the presence census. Sampled across more
    than two census periods so both halves are in the sample, and bounded at
    two scanlines on EVERY call, census calls included.
  * with an adapter, called at the TOP OF VBLANK, before the automatic read
    has started — `mtap_probe`'s timing, the worst case the D7 guard exists
    for: the call waits the read's start out, then its 4224 master cycles,
    then does the work. Bounded from both sides: below by the read's own
    length (a call that took less did not wait, and its P3/P4 are corrupt —
    the guard is the only thing that makes this number large), above by the
    work bound + the read + the read's latest start on the line.

This module drives the legacy MesenRunner (breakpoints are its surface), so
it is a module of its own — a Machine and a runner never share one.
"""
import collections
import json
import sys
from pathlib import Path

import pytest

from conftest import run_make

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mesen_runner as mr  # noqa: E402

BUILD = SUPERFORGE / "build"
FP_ROM, FP_LBL = BUILD / "four_pads.sfc", BUILD / "four_pads.lbl"
MP_ROM, MP_LBL = BUILD / "mtap_probe.sfc", BUILD / "mtap_probe.lbl"
MEM = MemoryType.SnesMemory

MC_PER_LINE = 1364                 # master cycles per NTSC scanline (fullsnes)
AUTO_READ_MC = 4224                # the automatic read's length (fullsnes)
AUTO_READ_LATEST_START = 382       # H=95.5 dots x 4 mc: its latest start on
                                   #   the first VBlank line (fullsnes)
BUDGET_PRESENT = 2 * MC_PER_LINE   # docs/102: under 2 scanlines, every call
BUDGET_ABSENT = 200                # jsr + lda dp + bne + rts, with margin
# The worst case: the work (bounded above, on every call) + waiting out the
# whole read + the latest it can start after the caller arrives on line 225.
BUDGET_WORST = BUDGET_PRESENT + AUTO_READ_MC + AUTO_READ_LATEST_START
CENSUS_EVERY = 32                  # MTAP_CENSUS_EVERY (engine/features/mtap)
SAMPLES = 2 * CENSUS_EVERY + 8     # > two census periods: both halves, twice


@pytest.fixture(scope="module", autouse=True)
def labels_built():
    for target in ("fp-labels", "mtap-probe"):
        r = run_make(target)
        assert r.returncode == 0, f"make {target} failed:\n{r.stdout}\n{r.stderr}"
    yield


def _labels(lbl):
    out = {}
    for line in lbl.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "al":
            out[parts[2].lstrip(".")] = int(parts[1], 16)
    return out


def _mtap_on(map_dir):
    jmap = json.loads((BUILD / map_dir / "symbol_map.json").read_text())
    return next(p["start"] for p in jmap["globals"] if p["sym"] == "ES_MTAP_ON")


def _measure(rom, lbl, marks, map_dir, port2, samples=SAMPLES):
    lab = _labels(lbl)
    begin, end = lab[marks[0]], lab[marks[1]]
    assert end - begin == 3, f"{marks[0]}..{marks[1]} must be exactly one `jsr abs`"
    runner = MesenRunner(port2=port2)
    costs = []
    try:
        runner.boot_rom(str(rom), frames=60)
        detected = runner.read_u16(MemoryType.SnesWorkRam, _mtap_on(map_dir))
        runner.debug_break()
        with runner.breakpoints([(MEM, begin, "exec"), (MEM, end, "exec")]):
            t0 = None
            while len(costs) < samples:
                # EMULATED-frame budget: a False is a claim about the ROM.
                assert runner.run_to_break(max_frames=10), "no breakpoint hit"
                st = runner.snes_state_snapshot()
                pc = st.cpu_pc & 0xFFFF
                if pc == begin & 0xFFFF:
                    t0 = st.master_clock
                elif pc == end & 0xFFFF and t0 is not None:
                    # Close a pair ONLY on the end mark: run_to_break can stop
                    # at a PC that is neither mark (a stop the runner makes on
                    # its own, see its docstring); counting that as the call's
                    # end once cut calls short (audit-3 N7: 10..3,560 mc).
                    costs.append(st.master_clock - t0)
                    t0 = None
    finally:
        runner.stop()
        mr.ensure_port2_device(mr.PORT2_PAD)     # hand the plain pad back
    return detected, costs


def _report(what, costs):
    h = sorted(collections.Counter(costs).items())
    print(f"\nmtap_read, {what}: min {min(costs)} max {max(costs)} mc "
          f"({max(costs) / MC_PER_LINE:.2f} scanlines worst) over "
          f"{len(costs)} calls; histogram {h}")


def test_the_absent_path_is_a_flag_test():
    detected, costs = _measure(FP_ROM, FP_LBL, ("fp_pads_begin", "fp_pads_end"),
                               "fp", mr.PORT2_PAD)
    assert detected == 0, "a plain pad in port 2 was detected as an adapter"
    _report("no adapter (four_pads)", costs)
    assert max(costs) < BUDGET_ABSENT, costs


def test_a_call_after_the_auto_read_stays_under_two_scanlines_census_included():
    """four_pads' timing: the guard does not wait, so this is the work. The
    census calls are the expensive ones — the sample must contain them (two
    calls per period costing more than the plain call), or the bound below
    says nothing about them."""
    detected, costs = _measure(FP_ROM, FP_LBL, ("fp_pads_begin", "fp_pads_end"),
                               "fp", mr.PORT2_MULTITAP)
    assert detected == 1, "the adapter was not detected"
    _report("adapter, after the auto-read (four_pads)", costs)
    plain = collections.Counter(costs).most_common(1)[0][0]
    census = [c for c in costs if c > plain]
    assert len(census) >= 4, (
        f"{len(census)} census call(s) in {len(costs)} — two periods should "
        f"hold at least four (two halves each); the bound below would not "
        f"cover them. costs {costs}")
    hi = max(costs)
    assert hi < BUDGET_PRESENT, (
        f"worst {hi} mc = {hi / MC_PER_LINE:.2f} scanlines; budget "
        f"{BUDGET_PRESENT} mc")


def test_a_caller_at_the_top_of_vblank_pays_the_auto_read_wait():
    """mtap_probe's timing: every call lands on the first VBlank line before
    the automatic read has started (the D7 race, on purpose). The guard must
    wait the WHOLE read out — so no call may cost less than the read itself —
    and the wait is bounded by the read's latest start."""
    detected, costs = _measure(MP_ROM, MP_LBL, ("mp_read_begin", "mp_read_end"),
                               "mtap_probe", mr.PORT2_MULTITAP)
    assert detected == 1, "the adapter was not detected"
    _report("adapter, top of VBlank (mtap_probe, the worst case)", costs)
    lo, hi = min(costs), max(costs)
    assert lo > AUTO_READ_MC, (
        f"a call cost {lo} mc, less than the automatic read's {AUTO_READ_MC}: "
        f"it cannot have waited the read out")
    assert hi < BUDGET_WORST, (
        f"worst {hi} mc = {hi / MC_PER_LINE:.2f} scanlines; budget "
        f"{BUDGET_WORST} mc (work bound + the read + its latest start)")
