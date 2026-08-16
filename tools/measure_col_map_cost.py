#!/usr/bin/env python3
"""measure_col_map_cost.py — the per-query cost of the candidate col_map
lookup, measured on the cycle-accurate emulator.

DESIGN-REVIEW scaffolding for, which requires the figure to be
measured rather than estimated. Drives build/probe_colmap.sfc:

    arm 1 (cmd 1)   K iterations of the loop WITH the lookup
    arm 2 (cmd 2)   K iterations of the IDENTICAL loop with the lookup removed

Both arms bracket their loop with a store to the `mark` byte; a WRAM write
breakpoint on that address gives MasterClock at each boundary. The control
arm is what makes this a measurement of the LOOKUP rather than of the loop:
the coordinate walk, the accumulate, the counter and the branch are byte-for-
byte identical in both arms, so everything except `jsr col_map_at` cancels.

    per-query master cycles = (with_mc - without_mc) / K

Usage:  python3 tools/measure_col_map_cost.py [K ...]
"""
import json
import sys
import tomllib
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from mesen_runner import MemoryType, MesenRunner  # noqa: E402

ROM = SUPERFORGE / "build" / "probe_colmap.sfc"
SYMS = json.loads((SUPERFORGE / "build" / "colmap_map" / "symbol_map.json").read_text())

WR = MemoryType.SnesWorkRam
MEM = MemoryType.SnesMemory
WRAM_BANK = 0x7E0000

# Every address comes from the allocator's emitted map, never a literal —
# the same idiom tests/test_measure_vblank.py:36 uses.
_SYM = {p["sym"]: p["start"] for p in
        SYMS["scenes"]["probe"]["placements"] + SYMS["globals"]}


def sym(name: str) -> int:
    if name not in _SYM:
        raise KeyError(f"{name} not in symbol_map.json "
                       f"(have {sorted(_SYM)[:12]}...)")
    return _SYM[name]


def _budget_pins() -> tuple[int | None, int | None, str]:
    """(mc_per_frame, reference-workload cost, where they came from).

    READ, not transcribed. These used to be a hardcoded `357368, 305348` beside
    a comment that cited these very files as their source — so a moved pin
    turned `make measure` red while this tool kept printing stale percentages.
    Anything that names a file as its source has to open it.

    `cpu_worst_frame_mc` is the pinned WORST-FRAME cost of the mini racing reference
    reference workload, not a budget a feature must fit inside — so the
    meaningful denominators below are the frame and that workload's headroom.
    build/measurements_cpu.json is the fresh measurement `make measure` checks
    the pin against; it only exists after a measure run, so it is used as a
    cross-check here, never as a requirement.
    """
    with open(SUPERFORGE / "allocator" / "substrate.toml", "rb") as f:
        frame = tomllib.load(f)["frame"]["ntsc"]
    mc = frame.get("mc_per_frame")
    ref = frame.get("cpu_worst_frame_mc")
    where = "allocator/substrate.toml [frame.ntsc]"
    if not isinstance(mc, int):
        mc = None
    if not isinstance(ref, int): # "MEASURE" in an unpinned tree
        ref = None
    fresh = SUPERFORGE / "build" / "measurements_cpu.json"
    if fresh.exists():
        try:
            m = json.loads(fresh.read_text())["pin"]["cpu_cycles_per_frame_worst_mc"]
        except (KeyError, ValueError):
            m = None
        if m is not None:
            if ref is None:
                ref, where = m, "build/measurements_cpu.json (substrate unpinned)"
            else:
                where += (f"; fresh build/measurements_cpu.json agrees"
                          if m == ref else
                          f"; WARNING fresh build/measurements_cpu.json says "
                          f"{m}, pin says {ref} — run `make measure`")
    return mc, ref, where


def run_arm(runner, cmd: int, k: int, addrs) -> tuple[int, int]:
    """One arm: set cmd/param, catch the two `mark` writes, return
    (elapsed master cycles, the ROM's flag accumulator)."""
    us_cmd, us_param, us_mark, us_acc = addrs
    runner.write_bytes(WR, us_param, k.to_bytes(2, "little"))
    runner.write_bytes(WR, us_cmd, bytes([cmd]))
    clocks = []
    with runner.breakpoints([(MEM, WRAM_BANK + us_mark, "write")]):
        for _ in range(2):
            # 600 EMULATED frames (10 s of emulated time), not a wall deadline: a
            # False under max_frames is a claim about the ROM, a False under
            # timeout_s is a claim about the host (AGENTS.md / run_to_break's
            # docstring). timeout_s stays as run_to_break's own stall guard.
            if not runner.run_to_break(max_frames=600):
                raise RuntimeError(f"arm {cmd}: mark write never hit")
            clocks.append(runner.snes_state_snapshot().master_clock)
    acc = int.from_bytes(runner.read_bytes(WR, us_acc, 2), "little")
    return clocks[1] - clocks[0], acc


def main(argv) -> int:
    ks = [int(a) for a in argv[1:]] or [200, 1000, 4000]
    addrs = (sym("US_CMD"), sym("US_PARAM"), sym("US_MARK"), sym("US_ACC"))
    print(f"probe control block: cmd=${addrs[0]:04X} param=${addrs[1]:04X} "
          f"mark=${addrs[2]:04X} acc=${addrs[3]:04X}  (allocator-emitted)")

    runner = MesenRunner()
    rows = []
    try:
        runner.boot_rom(str(ROM), frames=90)
        runner.debug_break()
        for k in ks:
            with_mc, with_acc = run_arm(runner, 1, k, addrs)
            without_mc, without_acc = run_arm(runner, 2, k, addrs)
            per = (with_mc - without_mc) / k
            rows.append((k, with_mc, without_mc, per, with_acc, without_acc))
    finally:
        runner.stop()

    print(f"\n{'K':>6} {'with (mc)':>12} {'control (mc)':>13} "
          f"{'per query mc':>13} {'acc(with)':>10} {'acc(ctl)':>9}")
    for k, w, c, per, aw, ac in rows:
        print(f"{k:>6} {w:>12} {c:>13} {per:>13.2f} {aw:>10} {ac:>9}")

    pers = [r[3] for r in rows]
    print(f"\nper-query cost: {min(pers):.1f}..{max(pers):.1f} master cycles "
          f"(spread {max(pers) - min(pers):.2f})")
    frame_mc, ref_mc, where = _budget_pins()
    if frame_mc is None or ref_mc is None:
        print("\nsubstrate pins are not set (unpinned placeholders?) — skipping "
              "the frame-budget context; the per-query figure above stands on "
              "its own")
    else:
        head_mc = frame_mc - ref_mc
        print(f"\npins read from {where}")
        print(f"frame = {frame_mc} mc; the pinned reference workload spends "
              f"{ref_mc} mc ({100.0 * ref_mc / frame_mc:.1f}%), leaving "
              f"{head_mc} mc of headroom")
        for n in (1, 4, 16, 64):
            cost = n * max(pers)
            print(f"  {n:>3} queries/frame = {cost:>8.0f} mc = "
                  f"{100.0 * cost / frame_mc:5.2f}% of the frame, "
                  f"{100.0 * cost / head_mc:6.2f}% of that headroom")
    if all(a == 0 for _, _, _, _, _, a in rows):
        print("\ncontrol arm accumulator is 0 on every K, as designed "
              "(the control arm performs no lookup)")
    if any(a == 0 for _, _, _, _, a, _ in rows):
        print("\nWARNING: the lookup arm accumulated 0 flags — the walk never "
              "hit a flagged tile, so the read may not be doing what it claims")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
