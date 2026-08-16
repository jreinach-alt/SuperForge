"""deliverable 6.1 — usable VBlank DMA bytes/frame, measured.

The probe ROM (vendor/probes/probe_vblank.asm, allocator-mapped) DMAs a
host-selected byte count of an incrementing word pattern to VRAM inside the
NMI with the screen ON. Writes that miss the VBlank window are dropped by
the PPU, and delivery is a prefix, so a trial fully landed iff its LAST word
landed. The target is wiped to $EEEE once at boot and the sweep is ASCENDING,
so a fresh tail can only come from the trial that attempted it. The largest
fully-delivered count is the usable ceiling through one channel, including
real NMI-entry + DMA-setup overhead.

Writes build/measurements_vblank.json for tools/pin_budgets consumption.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

WR, VR = MemoryType.SnesWorkRam, MemoryType.SnesVideoRam


@pytest.fixture(scope="module")
def probe():
    r = subprocess.run(["make", "build/probe_vblank.sfc"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"probe build failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads(
        (SUPERFORGE / "build" / "probe_map" / "symbol_map.json").read_text())
    syms = {p["sym"]: p["start"] for p in
            jmap["scenes"]["probe"]["placements"] + jmap["globals"]}
    runner = MesenRunner()
    runner.boot_rom(str(SUPERFORGE / "build" / "probe_vblank.sfc"), frames=60)
    yield runner, syms
    runner.stop()


def _cmd(runner, syms, cmd: int, param: int, param2: int = 0):
    """Post a command and wait for the probe's sequence counter to answer.

    The budget is 30 EMULATED frames, not 30 wall sixtieths. The probe
    answers in one or two NMIs, so what matters is that the wait is counted
    in the probe's own frames: the loop this replaced spent 30 x 16.7 ms of
    HOST time, which on a loaded box is a handful of probe frames rather
    than thirty, and the sweep below issues ~250 commands.
    """
    s0 = runner.read_u16(WR, syms["US_SEQ"])
    runner.write_bytes(WR, syms["US_PARAM"], param.to_bytes(2, "little"))
    runner.write_bytes(WR, syms["US_PARAM2"], param2.to_bytes(2, "little"))
    runner.write_bytes(WR, syms["US_CMD"], bytes([cmd]))
    try:
        runner.wait_until(
            lambda: runner.read_u16(WR, syms["US_SEQ"]) != s0,
            max_frames=30, what=f"probe answering cmd={cmd} param={param}")
    except TimeoutError:
        raise AssertionError(f"probe never answered cmd={cmd} param={param}")


def _tail_landed(runner, syms, total_bytes: int) -> bool:
    """Delivery is a prefix, so a trial fully landed iff its LAST word did."""
    last_i = total_bytes // 2 - 1
    got = runner.read_bytes(VR, (syms["ES_V_PROBE_TARGET"] + last_i) * 2, 2)
    return got == last_i.to_bytes(2, "little")


def _trial(runner, syms, n: int) -> dict:
    _cmd(runner, syms, 1, n)
    return {"n": n, "landed": _tail_landed(runner, syms, n),
            "done_v": runner.read_u16(WR, syms["US_DONE_V"]),
            "done_h": runner.read_u16(WR, syms["US_DONE_H"])}


def _wipe(runner, syms):
    """Re-wipe the whole 8 KB target to $EEEE (1 KB per NMI, 8 commands) so a
    stale tail from an earlier sweep can never fake a delivery."""
    for off_words in range(0, 4096, 512):
        _cmd(runner, syms, 3, off_words)
    spot = runner.read_bytes(VR, syms["ES_V_PROBE_TARGET"] * 2, 2)
    assert spot == b"\xEE\xEE", f"wipe did not land: {spot.hex()}"


def _multi_trial(runner, syms, k: int, s: int) -> bool:
    _cmd(runner, syms, 2, s, k)
    return _tail_landed(runner, syms, k * s)


def test_measure_usable_vblank_bytes(probe):
    runner, syms = probe
    trials = []
    largest = None
    for n in range(512, 8192 + 1, 64):        # ascending: tails stay fresh
        t = _trial(runner, syms, n)
        trials.append(t)
        if t["landed"]:
            largest = t
    assert largest is not None, "not even 512 B landed — probe broken"

    # the emulator must actually model active-display write blocking, or
    # this whole measurement is meaningless
    top = trials[-1]
    assert top["n"] == 8192 and not top["landed"], (
        "8 KB 'fully landed' — VRAM write blocking is not being modeled")

    # delivery must be monotone: once a size fails, larger sizes fail too
    seen_fail = False
    for t in trials:
        if not t["landed"]:
            seen_fail = True
        else:
            assert not seen_fail, f"non-monotone delivery at N={t['n']}"

    usable = largest["n"]
    # sanity: between the naive floor and the theoretical ceiling
    # (38 lines * 1364 mc / 8 mc/B = 6479 B)
    assert 4000 <= usable <= 6479, usable
    out = {
        "vblank_usable_bytes": usable,
        "resolution_bytes": 64,
        "completion_v_at_max": largest["done_v"],
        "completion_h_at_max": largest["done_h"],
        "old_engine_start_pin": 5500,
        "note": "one GP-DMA channel fired from NMI entry, screen on, "
                "auto-joyread off; includes NMI-entry + DMA-setup overhead",
    }
    (SUPERFORGE / "build" / "measurements_vblank.json").write_text(
        json.dumps(out, indent=2) + "\n")
    print(f"\nusable VBlank DMA: {usable} B/frame "
          f"(completion at V={largest['done_v']} H={largest['done_h']})")


def test_measure_multi_queue_arm_cost(probe):
    """an earlier phase F9 refinement: K queued transfers per NMI, each fully re-armed.
    usable_total(K) < usable(1) by the per-transfer arm overhead; pin the
    per-additional-transfer cost as byte-equivalents (conservative max over K).
    Runs after the single sweep (definition order) and extends its JSON."""
    runner, syms = probe
    jpath = SUPERFORGE / "build" / "measurements_vblank.json"
    out = json.loads(jpath.read_text())          # single sweep ran first
    usable1 = out["vblank_usable_bytes"]

    step = 16
    totals: dict[int, int] = {}
    for k in (2, 4, 8, 14):
        _wipe(runner, syms)
        hi = ((usable1 // k) // step) * step + step   # ceiling: K*S <= usable1+
        lo = max(step, hi - 384)
        best = None
        seen_fail = False
        for s in range(lo, hi + 1, step):            # ascending: tails fresh
            landed = _multi_trial(runner, syms, k, s)
            if landed:
                assert not seen_fail, \
                    f"non-monotone multi delivery at K={k} S={s}"
                best = k * s
            else:
                seen_fail = True
        assert best is not None, \
            f"K={k}: nothing landed in [{lo},{hi}] — window or probe broken"
        assert best <= usable1, (k, best, usable1)
        totals[k] = best

    # conservative arm estimate: the largest per-additional-transfer cost
    # implied by any K (rounded up); resolution improves with K
    arm = max(-(-(usable1 - t) // (k - 1)) for k, t in totals.items())
    arm = max(arm, 0)
    assert arm < 512, f"arm cost implausibly high: {arm} (totals {totals})"

    out["multi_queue"] = {
        "step_bytes": step,
        "totals_by_transfers": {str(k): t for k, t in totals.items()},
        "note": "cmd 2: K back-to-back NMI GP-DMAs, every slot fully re-armed "
                "(DMAP/BBAD/A1T/A1B/DAS/VMADD); delivery checked at the final "
                "word of the K-th slot",
    }
    out["arm_cost_bytes"] = arm
    jpath.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nmulti-queue totals {totals} -> arm cost {arm} B/transfer")
