#!/usr/bin/env python3
"""measure_tb_cost.py — what does a candidate timebase COST, per frame, measured.

WHY THIS EXISTS. `tools/rate_oracle.py` says whether a scheme reaches speed
parity. It says nothing about what the scheme costs, and on this console that
is the half that kills things: `docs/95` §4 refuted 6-ticks-per-5-frames on the
TIGHTEST rail purely on budget, with the average short (+16.1% of usable work
returned against +20% demanded) and the peak measured not to fit (a doubled
tick at 121% of a PAL frame in work alone).

So this measures, per candidate and per region, on the shipping variant images:

  * TICK COST — master clocks from `world::tick`'s entry to the return of its
    last callee. min / median / max across a run, because the lump scheme's
    cost is BIMODAL by construction and an average would hide exactly the
    thing that fails: the doubled frame.
  * LOOP PERIOD — master clocks between consecutive entries to that same
    tick. `sm_frame_sync` parks the main loop on the NMI, so a loop that FITS
    reads exactly one frame and one that does not reads two. That is the
    rail's own cadence oracle, the instrument `docs/95` §4.3 used, and it is
    an observation rather than a sum.

The addresses are READ from the `-Ln` label file `tools/build_scroller_tb.sh`
emits beside each variant, and each callee's return site is found by scanning
the tick's own bytes for the `jsr` that calls it — `tools/measure_sh2_swarm.py`'s
method, unchanged.

    python3 tools/measure_tb_cost.py                       # every variant
    python3 tools/measure_tb_cost.py build/scroller.sfc

`SF_REGION` is per process, so this re-executes itself once per region —
`tools/pal_probe.py`'s pattern. Report only: exits 0 unless a child fails.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

DEFAULT_ROMS = ["build/scroller.sfc", "build/scroller_tb_lump.sfc",
                "build/scroller_tb_accum6_5.sfc", "build/scroller_tb_accum.sfc",
                "build/scroller_tb_intscale.sfc", "build/scroller_tb_intup.sfc"]

# The drive rate_oracle.py uses on this rail: RIGHT held, so every frame
# actually pays for a camera move.
PAD = {"right": True}
SAMPLES = 40


def labels(lbl: Path) -> dict:
    out = {}
    for line in lbl.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "al":
            out[parts[2].lstrip(".")] = int(parts[1], 16)
    return out


def return_site(rom: bytes, caller: int, end: int, callee: int) -> int:
    """The address `jsr callee` returns to, found inside the caller's bytes.
    LoROM bank 0: CPU $8000-$FFFF is file offset $0000-$7FFF."""
    pat = bytes([0x20, callee & 0xFF, callee >> 8])
    at = rom.index(pat, caller - 0x8000, end - 0x8000)
    return 0x8000 + at + 3


def worker(args):
    from mesen_runner import MemoryType, MesenRunner

    MEM = MemoryType.SnesMemory
    region = os.environ.get("SF_REGION", "auto")
    out = []
    runner = MesenRunner()
    try:
        for rom_s in args.roms:
            rom_p = SUPERFORGE / rom_s
            lbl = rom_p.with_suffix(".lbl")
            if not lbl.exists():                # the stock rail's own twin
                lbl = SUPERFORGE / "build" / "scroller_tb_off.lbl"
            lab = labels(lbl)
            tick, draw = lab["tick"], lab["scr_obj_draw"]
            end = return_site(rom_p.read_bytes(), tick, tick + 0x60, draw)
            top, sync = lab["input_read"], lab["sm_frame_sync"]

            runner.boot_rom(str(rom_p), frames=90)
            with runner.frame_stepping():
                for _ in range(30):
                    runner.frame_step(1, **PAD)
                # --- tick cost: entry -> the return of its last callee ------
                # Four marks, in the order one frame visits them:
                #   input_read -> tick -> (tick's last callee returns) ->
                #   sm_frame_sync. The loop finishes long before VBlank on
                #   this rail and then sits in `wai`, so the NMI fires INSIDE
                #   sm_frame_sync and never inside the span below — which is
                #   what makes input_read -> sm_frame_sync a clean reading of
                #   the main loop's own per-frame work.
                costs, entries, mains = [], [], []
                with runner.breakpoints([(MEM, top, "exec"),
                                         (MEM, tick, "exec"),
                                         (MEM, end, "exec"),
                                         (MEM, sync, "exec")]):
                    t0 = t1 = None
                    for _ in range(SAMPLES * 4 + 4):
                        if not runner.run_to_break(max_frames=240):
                            raise RuntimeError("breakpoint never hit")
                        st = runner.snes_state_snapshot()
                        if st.cpu_pc == top:
                            t0 = st.master_clock
                        elif st.cpu_pc == tick:
                            t1 = st.master_clock
                            entries.append(st.master_clock)
                        elif st.cpu_pc == end and t1 is not None:
                            costs.append(st.master_clock - t1)
                            t1 = None
                        elif st.cpu_pc == sync and t0 is not None:
                            mains.append(st.master_clock - t0)
                            t0 = None
            periods = [b - a for a, b in zip(entries, entries[1:])]
            costs, periods, mains = sorted(costs), sorted(periods), sorted(mains)
            out.append(dict(
                rom=rom_s, region=region, md5=runner.rom_md5 if hasattr(
                    runner, "rom_md5") else "",
                tick_min=costs[0], tick_med=costs[len(costs) // 2],
                tick_max=costs[-1],
                loop_min=periods[0], loop_med=periods[len(periods) // 2],
                loop_max=periods[-1],
                main_med=mains[len(mains) // 2]))
    finally:
        runner.stop()
    print("SFTBCOST " + json.dumps(out))


def _child(args, region):
    env = dict(os.environ, SF_REGION=region)
    argv = [sys.executable, __file__, "--worker", *args.roms]
    r = subprocess.run(argv, env=env, capture_output=True, text=True,
                       cwd=str(SUPERFORGE))
    line = next((x for x in r.stdout.splitlines()
                 if x.startswith("SFTBCOST ")), None)
    if line is None:
        raise SystemExit(f"{region} pass failed:\n{r.stdout}\n{r.stderr}")
    return json.loads(line[len("SFTBCOST "):])


# The two-region frame table. Measured: substrate.toml [frame.ntsc], and
# docs/95 §4.2 / this tool's own loop-period readings for PAL.
# TICK: ok — a TWO-REGION table is the shape the tick-substrate rule exists
#   to ask for; the NTSC number appears here only beside its PAL partner and
#   the caller picks by region instead of assuming.
FRAME = {"ntsc": 357368, "pal": 425568}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("roms", nargs="*", default=DEFAULT_ROMS)
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if not args.roms:
        args.roms = DEFAULT_ROMS
    if args.worker:
        return worker(args)

    recs = {r: _child(args, r) for r in ("ntsc", "pal")}

    # --- what PAL actually RETURNS on this rail ----------------------------
    # docs/95 §4.2 measured +14.8%..+17.4% of usable per-frame work on the
    # TIGHTEST rail — less than the frame's own +19.1%, because the fixed NMI
    # and sync cost does not shrink when the frame gets longer. That number is
    # a property of THAT rail's fixed cost, so it is re-measured here rather
    # than inherited.
    #
    # usable = frame - (the main loop's work outside the scene tick)
    #                - (the NMI). The first term is measured below; the second
    # is docs/93 §7's measured worst NMI frame, 16,800 mc, which that pass
    # found IDENTICAL IN BOTH REGIONS to the master cycle — cited, not
    # re-measured here.
    NMI_MC = 16800
    st = {r: recs[r][0] for r in ("ntsc", "pal")}
    fixed = {r: st[r]["main_med"] - st[r]["tick_med"] for r in st}
    usable = {r: FRAME[r] - fixed[r] - NMI_MC for r in st}
    print("usable per-frame work on THIS rail (docs/95 §4.2's number, "
          "re-measured here)")
    for r in ("ntsc", "pal"):
        print(f"  {r:<5} frame {FRAME[r]:>9,} mc  - main loop outside the "
              f"tick {fixed[r]:>6,} mc  - NMI {NMI_MC:,} mc "
              f" = {usable[r]:>9,} mc usable")
    print(f"  PAL returns {100.0 * (usable['pal'] / usable['ntsc'] - 1):+.1f}%"
          f" of usable per-frame work "
          f"(the FRAME grew +{100.0 * (FRAME['pal'] / FRAME['ntsc'] - 1):.1f}%;"
          f" a whole-extra-tick scheme needs +20.0%)")
    print()
    print(f"{'':<26} {'':<5} {'tick mc (min/med/max)':<28} {'% frame':>8}  "
          f"loop mc (med)   fits")
    base = {}
    for region in ("ntsc", "pal"):
        frame = FRAME[region]
        for rec in recs[region]:
            name = Path(rec["rom"]).stem
            if rec["rom"] == args.roms[0]:
                base[region] = rec["tick_med"]
            delta = rec["tick_med"] - base[region]
            fits = "1 frame" if rec["loop_med"] < 1.5 * frame else "2 FRAMES"
            print(f"{name:<26} {region:<5} "
                  f"{rec['tick_min']:>7,} /{rec['tick_med']:>7,} /"
                  f"{rec['tick_max']:>7,}  "
                  f"{100.0 * rec['tick_med'] / frame:>7.3f}%  "
                  f"{rec['loop_med']:>10,}   {fits}"
                  + (f"   ({delta:+,} mc vs stock)" if delta else ""))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
