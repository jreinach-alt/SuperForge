#!/usr/bin/env python3
"""Measure the CPU-store VBlank ceiling — evidence for the VWF upload decision.

Answers the question `` §3 leaves open: how many
VRAM words can a plain CPU load/store loop commit inside one VBlank, and how
does that compare against a GP-DMA of the same payload once the MEASURED
128-byte-equivalent per-transfer arm charge is paid?

Both sides come off the same instrument, `vendor/probes/probe_vblank.asm`:

  cmd 1 -> single GP-DMA of N bytes         (the pinned 5952 B/frame ceiling)
  cmd 4 -> K CPU word stores, no DMA at all (the txt_q commit shape)

Method is cmd 1's, unchanged: screen ON, so writes that miss the VBlank
window are dropped by the PPU; delivery is a prefix, so a trial fully landed
iff its LAST word landed; the target is wiped to $EEEE between families and
the sweep is ASCENDING, so a fresh tail can only come from the trial that
attempted it.

This is a standalone instrument, NOT part of `make measure`: it informs a
design decision and pins nothing. Run from the repo root:

    python3 tools/measure_cpu_store_vblank.py
"""
import json
import subprocess
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

WR, VR = MemoryType.SnesWorkRam, MemoryType.SnesVideoRam


def cmd(runner, syms, c, param=0, param2=0):
    s0 = runner.read_u16(WR, syms["US_SEQ"])
    runner.write_bytes(WR, syms["US_PARAM"], param.to_bytes(2, "little"))
    runner.write_bytes(WR, syms["US_PARAM2"], param2.to_bytes(2, "little"))
    runner.write_bytes(WR, syms["US_CMD"], bytes([c]))
    for _ in range(30):
        runner.wait_frames(1)     # EMULATED frames: run_frames(1) sleeps
                                  # 16 ms of WALL and buys whatever the
                                  # host managed, which on a loaded box is
                                  # several frames and on a parked core is
                                  # none at all.
        if runner.read_u16(WR, syms["US_SEQ"]) != s0:
            return
    raise AssertionError(f"probe never answered cmd={c} param={param} k={param2}")


def tail_landed(runner, syms, words):
    last = words - 1
    got = runner.read_bytes(VR, (syms["ES_V_PROBE_TARGET"] + last) * 2, 2)
    return got == last.to_bytes(2, "little")


def wipe(runner, syms):
    for off in range(0, 4096, 512):
        cmd(runner, syms, 3, param=off)
    assert runner.read_bytes(VR, syms["ES_V_PROBE_TARGET"] * 2, 2) == b"\xEE\xEE"


def sweep_cpu(runner, syms, lo, hi, step):
    """Largest K (words) whose tail landed. Ascending, monotonicity checked."""
    best, seen_fail = None, False
    trials = []
    for k in range(lo, hi + 1, step):
        cmd(runner, syms, 4, param2=k)
        landed = tail_landed(runner, syms, k)
        trials.append((k, landed))
        if landed:
            assert not seen_fail, f"non-monotone CPU-store delivery at K={k}"
            best = k
        else:
            seen_fail = True
    return best, trials


def main():
    r = subprocess.run(["make", "build/probe_vblank.sfc"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"probe build failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads(
        (SUPERFORGE / "build" / "probe_map" / "symbol_map.json").read_text())
    syms = {p["sym"]: p["start"] for p in
            jmap["scenes"]["probe"]["placements"] + jmap["globals"]}
    sub = (SUPERFORGE / "allocator" / "substrate.toml").read_text()
    dma_ceiling = int([ln for ln in sub.splitlines()
                       if ln.startswith("vblank_usable_bytes")][0]
                      .split("=")[1].split("#")[0])
    arm = int([ln for ln in sub.splitlines()
               if ln.startswith("arm_cost_bytes")][0]
              .split("=")[1].split("#")[0])

    runner = MesenRunner()
    runner.boot_rom(str(SUPERFORGE / "build" / "probe_vblank.sfc"), frames=60)
    try:
        wipe(runner, syms)
        # coarse then fine: the ceiling is a few hundred words, not thousands
        coarse, _ = sweep_cpu(runner, syms, 32, 1024, 32)
        assert coarse, "not even 32 CPU word stores landed — probe broken"
        wipe(runner, syms)
        fine, trials = sweep_cpu(runner, syms, max(4, coarse - 32),
                                 coarse + 32, 4)
        words = fine or coarse
    finally:
        runner.stop()

    # byte-equivalence: the CPU-store ceiling occupies the whole VBlank, the
    # same window cmd 1's DMA ceiling occupies, so
    #   cost_per_word (B-equiv) = dma_ceiling / cpu_word_ceiling
    per_word = dma_ceiling / words
    out = {
        "cpu_store_word_ceiling": words,
        "resolution_words": 4,
        "dma_ceiling_bytes": dma_ceiling,
        "arm_cost_bytes": arm,
        "cpu_store_cost_bytes_equiv_per_word": round(per_word, 2),
        "crossover_words": round(arm / (per_word - 2), 1),
        "note": "cmd 4: K CPU 16-bit stores to $2118 from ROM long,x, screen "
                "on, no DMA. Byte-equivalence is vs cmd 1's measured "
                "single-DMA ceiling over the same VBlank window. Crossover is "
                "where CPU cost per word equals DMA payload (2 B/word) plus "
                "the amortised arm charge.",
    }
    (SUPERFORGE / "build" / "measurements_cpu_store.json").write_text(
        json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    print(f"\nCPU-store ceiling: {words} VRAM words/VBlank "
          f"(~{per_word:.1f} B-equiv per word)")
    print(f"GP-DMA of W words costs {arm} + 2W B-equiv; "
          f"crossover at W ~ {out['crossover_words']} words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
