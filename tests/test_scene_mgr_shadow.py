"""scene_mgr's channel-register shadow clear: does it run, and what does it cost?

`sm_nmi_core` MVNs the whole 128-byte `ES_SM_HDMA` block to `$4300` on every
armed frame, so any slot NOBODY programmed still reaches the real DMA register
file. `sm_init` zeroed the block at BOOT ONLY: after a scene it held the
PREVIOUS scene's live HDMA configuration, so a later scene that armed a channel
number an earlier scene had used inherited that scene's DMAP/BBAD/A1T. A later review
armed ch6 in `results::enter`, which fired race's leftover `tmi` config into
`$212C` (TM) every scanline; the results screen rendered as total garbage while
`no_literals` was clean and 266/266 tests passed.

On real hardware the untouched case is worse than stale. Power-on RAM is random
DRAM garbage (CLAUDE.md rule 5), so a slot that is neither zeroed nor programmed
carries an arbitrary DMAP, an arbitrary BBAD and an arbitrary source address —
one HDMAEN bit away from HDMA driving an arbitrary PPU port. That is why the
clear moved into the transition rather than being left to boot.

This module asserts the two things about that change that the declaration-driven
tests in test_decl_impl_channels.py cannot:

  * it RUNS, inside the forced-blank switch, observed at the store itself;
  * it COSTS what it is documented to cost, MEASURED on the cycle-accurate
    emulator rather than counted off the datasheet.

The residual-state consequences (no scene sees another scene's configuration)
are asserted in test_decl_impl_channels.py, against the declarations.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

WR = MemoryType.SnesWorkRam
ROM = SUPERFORGE / "build" / "microzero.sfc"
MAP = SUPERFORGE / "build" / "mz" / "symbol_map.json"

WRAM_BANK = 0x7E0000
FRAME_MC = 357368               # NTSC: 1364 mc/scanline x 262 scanlines
MC_PER_FAST_CYCLE = 6           # 21.477 MHz master / 3.58 MHz FastROM

# The loop stores descending 16-bit zeros from +(SIZE-2) down to +0. Both probe
# offsets sit inside channel PROBE_CH's 16-byte slot, which NO claim in microzero
# occupies, so the clear loop is the only writer of either — a probe on, say,
# +0 would also catch bgm's arm code writing ch0's DMAP. That premise is not
# assumed: the probe_channel_is_unclaimed fixture asserts it.
PROBE_CH = 7
PROBE_SPAN_ITERS = 7            # (SIZE-2) -> (SIZE-16) is 7 stores
# Sanity band on the measured per-iteration cost. Measured 98 mc; the band is
# wide enough that host load cannot make it flaky and narrow enough that a
# rewrite into something structurally slower (a byte loop, an unrolled block
# move through a slow region) is caught.
PER_ITER_MC_RANGE = (40, 220)
# Ceiling on the whole block as a fraction of one frame. It runs once per scene
# change, inside the forced-blank switch, on a frame whose display is already
# black — so this is not a per-frame budget, it is a guard against the clear
# quietly becoming a large memset.
MAX_FRAME_FRACTION = 0.05


@pytest.fixture(scope="module")
def built():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"


@pytest.fixture(scope="module")
def syms(built):
    return {p["sym"]: p for p in json.loads(MAP.read_text())["globals"]}


@pytest.fixture(scope="module")
def probe_channel_is_unclaimed(built):
    """the measurement's soundness rests on an unstated premise.

    Both probes sit in channel PROBE_CH's slot BECAUSE no claim occupies it, so
    the clear loop is provably the slot's only writer. If a future feature
    claims that channel, its arm code writes the same bytes, `clear_runs` starts
    pairing mismatched hits, and the delta can still land inside the wide
    (40, 220) band — a SILENT MIS-MEASUREMENT rather than a failure. Assert the
    premise instead of relying on it.
    """
    scenes = json.loads(MAP.read_text())["scenes"]
    claimed = {(sid, c["name"], cls)
               for sid, sc in scenes.items()
               for cls in ("channels", "dma_init")
               for c in sc.get(cls, []) if c["ch"] == PROBE_CH}
    assert not claimed, (
        f"channel {PROBE_CH} is no longer unclaimed: {sorted(claimed)}. The "
        f"cost probe reads that channel's shadow slot on the premise that "
        f"sm_hdma_shadow_clear is its only writer; a claim there makes the "
        f"measurement silently wrong, not merely fragile. Re-point the probes "
        f"at whichever channel is still unclaimed and update PROBE_CH.")


@pytest.fixture(scope="module")
def clear_runs(built, syms, probe_channel_is_unclaimed):
    """Every observed pass of the shadow-clear loop, with its machine state.

    Breaks on the loop's FIRST store and on its 8th (7 iterations later), both
    inside channel 7's unclaimed slot, and pairs them up. Each pair carries the
    master clock at both ends plus the scene-manager phase and NMITIMEN at the
    start, so "did it run inside the forced-blank switch" and "what did it cost"
    are answered from the same observation.
    """
    base = syms["ES_SM_HDMA"]["start"]
    size = syms["ES_SM_HDMA"]["size"]
    ctl = syms["ES_SM_CTL"]["start"]
    first, nth = base + size - 2, base + size - 16

    runner = MesenRunner()
    runner.boot_rom(str(ROM))
    hits = []
    try:
        runner.debug_break()
        # START at the title drives the one transition this needs; the boot-time
        # sm_init pass has already happened during the free-running load.
        runner.set_input(0, start=True)
        with runner.breakpoints([
                (MemoryType.SnesMemory, WRAM_BANK + first, "write"),
                (MemoryType.SnesMemory, WRAM_BANK + nth, "write")]):
            for _ in range(12):
                # EMULATED frames, not a wall deadline. This
                # budget is not a guard here, it is the loop's real EXIT: the
                # drive contains exactly ONE transition, so after its two
                # stores the hunt waits for a break that will never come and
                # leaves on the budget. MEASURED on this drive: first break 17
                # frames in, second 0 frames later, then nothing. 300 frames
                # is ~10x the full 31-frame transition, and it ends the dead
                # wait in ~1.4 s of ROM time instead of burning 10 wall
                # seconds — deterministic AND faster.
                if not runner.run_to_break(max_frames=300):
                    break
                s = runner.snes_state_snapshot()
                cur, _nxt, phase = runner.read_bytes(WR, ctl, 3)
                hits.append({"mc": s.master_clock, "pc": s.cpu_pc,
                             "scene": cur, "phase": phase,
                             "nmitimen": s.internal_regs.nmitimen})
                if len(hits) >= 6:
                    break
    finally:
        runner.stop()
    assert hits, (
        f"nothing ever wrote ${WRAM_BANK + first:06X} — the channel-register "
        f"shadow clear (sm_hdma_shadow_clear) never ran at all")
    # Pair the alternating FIRST / NTH hits.
    runs = [{"start": hits[i], "end": hits[i + 1],
             "delta_mc": hits[i + 1]["mc"] - hits[i]["mc"]}
            for i in range(0, len(hits) - 1, 2)]
    assert runs, f"only one breakpoint hit observed ({hits}) — no complete pass"
    return {"size": size, "runs": runs, "hits": hits}


def test_the_forced_blank_switch_clears_the_channel_register_shadow(clear_runs):
    """The clear runs inside the scene switch, not only at boot.

    `ES_SM_CTL+2 == 2` is scene_mgr's "blank switch" phase — forced blank is on
    screen, NMI is masked, and exit/enter run. Observing the loop's store with
    the phase machine in that state is the direct evidence that the transition
    clears the block; before this change the only pass was `sm_init`'s, at boot.

    NMITIMEN must read $00 at the same instant: the switch masks NMI before it
    touches anything (long uploads under NMI corrupt VRAM), and if the clear ever
    drifted outside that window the MVN could deliver a half-cleared block.
    """
    switch = [r for r in clear_runs["runs"] if r["start"]["phase"] == 2]
    assert switch, (
        "the shadow clear never ran with the phase machine in the forced-blank "
        "switch (phase 2) — observed passes: "
        + str([(r["start"]["scene"], r["start"]["phase"])
               for r in clear_runs["runs"]]))
    for r in switch:
        assert r["start"]["nmitimen"] == 0, (
            f"the shadow clear ran with NMITIMEN=${r['start']['nmitimen']:02X}; "
            f"the switch masks NMI first, so a non-zero value means the clear "
            f"has drifted out of the forced-blank window and sm_nmi_core can "
            f"MVN a half-cleared block to $4300")


def test_measured_cost_of_the_transition_clear(clear_runs):
    """What the clear costs, measured — never estimated (CLAUDE.md rule 1).

    The master clock advances monotonically at 21.477 MHz, so the delta between
    the loop's 1st and 8th store is exactly 7 iterations of a straight-line
    body. This test's band is on that PER-ITERATION figure, modally 98 mc.

    The block total it extrapolates below is ~2.6% LOW and knowingly so: a
    7-iteration window is shorter than one scanline, so it cannot see the +40
    mc DRAM-refresh stall the loop takes 4 times across its 4.64 scanlines.
    Measured over all 64 stores the block is 6,334 mc = 1.80% of a frame (see
    `sm_hdma_shadow_clear`'s header block in scene_mgr.asm — cited by ROUTINE,
    not by line: this read `:43-54` until 2026-08-15, when the spec's cut path
    moved the paragraph and those lines became unrelated text. A docstring so
    nothing went red, which is why the sweep missed it). The extrapolation
    stays here because the per-iteration band is what this test is FOR and
    1.80% is far inside the 5% ceiling — but read the printed total as a lower
    bound, not as the measurement.

    The printed "CPU cycles at the FastROM rate" figure is likewise a lower
    bound with the wrong divisor: the loop runs at 8 mc/fetch from bank $00, not
    6, which is why per-iteration is 98 and not the datasheet's 78.

    `make measure` is the check that the STEADY-STATE per-frame budget is
    untouched (its pins stay exact, because transitions are not in the measured
    path). This is the check on the transition itself.
    """
    switch = [r for r in clear_runs["runs"] if r["start"]["phase"] == 2]
    assert switch, "no forced-blank-switch pass to measure"
    iters = clear_runs["size"] // 2
    for r in switch:
        per_iter = r["delta_mc"] / PROBE_SPAN_ITERS
        total_mc = per_iter * iters
        frac = total_mc / FRAME_MC
        detail = (f"{r['delta_mc']} mc over {PROBE_SPAN_ITERS} iterations "
                  f"= {per_iter:.1f} mc/iteration; {iters} iterations "
                  f"= {total_mc:.0f} mc = {total_mc / MC_PER_FAST_CYCLE:.0f} "
                  f"CPU cycles at the FastROM rate = {frac * 100:.3f}% of one "
                  f"NTSC frame")
        assert PER_ITER_MC_RANGE[0] <= per_iter <= PER_ITER_MC_RANGE[1], (
            f"the shadow clear's per-iteration cost is outside the measured "
            f"band {PER_ITER_MC_RANGE} mc: {detail}. Either the loop body "
            f"changed shape or the probe offsets no longer bracket exactly "
            f"{PROBE_SPAN_ITERS} stores.")
        assert frac <= MAX_FRAME_FRACTION, (
            f"the shadow clear now costs {frac * 100:.2f}% of a frame: {detail}")
        print(f"\nsm_hdma_shadow_clear: {detail}")


def test_the_clear_reaches_the_top_of_the_block(clear_runs, syms):
    """The loop covers the WHOLE 128 bytes, not just the slots a claim names.

    A clear that stopped short — a wrong initial index, a `bpl` that should have
    been `bne` — would leave the top of the block holding whatever was there
    before, which `sm_nmi_core` MVNs to `$4300` on the very next armed frame
    regardless. Channel 7's slot is the top 16 bytes and no microzero claim
    occupies it, so it is exactly the region only this loop touches: it must
    read as zero once the ROM is running a scene.
    """
    import mz_drive as D

    runner = MesenRunner()
    try:
        runner.boot_rom(str(ROM))
        runner.debug_break()
        D.enter_race(runner, syms)
        base = syms["ES_SM_HDMA"]["start"]
        size = syms["ES_SM_HDMA"]["size"]
        block = runner.read_bytes(WR, base, size)
    finally:
        runner.stop()
    tail = block[size - 16:]             # channel 7: claimed by nothing
    assert set(tail) == {0}, (
        f"channel 7's shadow slot is not zero after the transition: "
        f"{tail.hex()} — the clear does not reach the top of the block, and "
        f"sm_nmi_core MVNs all {size} bytes to $4300 regardless")
