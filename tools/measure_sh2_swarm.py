#!/usr/bin/env python3
"""measure_sh2_swarm.py — what the split_h_2p SHOWCASE costs, per frame, measured.

DESIGN REVIEW G10, and it is the point of the rail. Slices 1, 2a and 2b each shipped
an honest "no cycle figure claimed"; this one cannot, because `SPRITES=24` is
justified by a HEADROOM NUMBER and a store count is not a measurement
(CLAUDE.md rule 1: measure cycle counts, never estimate).

WHAT IS DRIVEN. The SHIPPING ROM — `build/split_h_2p_demo.sfc`, not a probe
built for the occasion — with execution breakpoints on each of the scene tick's
callees and on the tick's own return site, reading Mesen's master clock at every
hit. Same discipline and the same label twin as `tools/measure_m7dg_logic.py`,
whose shape this follows.

    sh2_advance   the two pads -> the two headings and the two positions
    swm_ai        the AI: N-2 waypoint followers, each a wrap-residue pair, a
                  4-multiply cross/dot steer and two 8.8 accumulator steps
    swm_players   entities 0/1 take the cameras' positions
    obj_project   both bands' casts into the OAM shadow (the projector)
    swm_beat      the main loop's own frame counter

THE ADDRESSES ARE READ, NOT TRANSCRIBED. `make sh2-labels` assembles a twin with
`-g`, links it with `-Ln` and `cmp`s the result against the shipped `.sfc`, so a
label file that does not describe the shipping binary fails there rather than
quietly measuring something else. Each callee's return site is then found by
scanning the tick's own bytes for the `jsr` that calls it.

THREE WORLD STATES, because the cost is not one number and the SPREAD is the
interesting part:

  * PARKED     no pad held. The cameras stand still, the AI runs, and the cast
               is whatever the seeded world shows — the state a user sees when
               they put the controller down.
  * MOST-CULLED   both pads driving forward (B held) for long enough to walk the
               cameras away from the swarm, so most entities lose the Chebyshev
               pre-cull and the projector exits before a single multiply.
  * MOST-VISIBLE  both pads rotating, sampled at the frame in a swept turn where
               the OAM watermark is highest — the worst case the projector
               actually reaches on this world.

THE N SWEEP. `SWM_N` is a WRAM word and the whole draw+AI path asks it every
frame, so poking it walks the cost curve directly. The slope is the marginal cost of one entity across both bands, and the
whole-tick figure at each N against the frame is the headroom that justifies the
shipped count.

Usage:  python3 tools/measure_sh2_swarm.py
"""
import json
import sys
import tomllib
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from mesen_runner import MemoryType, MesenRunner  # noqa: E402

ROM = SUPERFORGE / "build" / "split_h_2p_demo.sfc"
LBL = SUPERFORGE / "build" / "split_h_2p_demo.lbl"
SYMS = json.loads((SUPERFORGE / "build" / "sh2" / "symbol_map.json").read_text())

W, MEM = MemoryType.SnesWorkRam, MemoryType.SnesMemory
OAM = MemoryType.SnesSpriteRam

# The tick's callees, in the order the tick calls them.
ROUTINES = ["sh2_advance", "swm_ai", "swm_players", "obj_project", "swm_beat"]

# The sweep's grid. 24 is the shipped count; the rest bracket it on both sides
# so the curve is a curve and not two points, and 64 is the table's capacity.
#
# 25..31 ARE HERE BECAUSE THE ANSWER LIVES THERE. The first grid
# jumped 24 -> 32 and the work item concluded from it that "24 is the largest N
# holding >=15% headroom" — a claim the grid cannot support, since it has no row
# between the two. The refined grid measures the boundary instead of
# interpolating it, and `loop_periods` below measures the thing the rule is
# really about.
SWEEP = [1, 2, 8, 16, 24, 25, 26, 27, 28, 29, 30, 31, 32, 48, 64]

# Master clocks per hardware frame come from substrate.toml; a loop that takes
# more than one frame shows up as an integer multiple of it, because
# `sm_frame_sync` parks the loop on the NMI.
LOOP_PERIODS = 12


def wram(name: str) -> int:
    for p in SYMS["scenes"]["split"]["placements"] + SYMS["globals"]:
        if p["sym"] == name:
            return p["start"]
    raise KeyError(f"{name} is not in the emitted map")


SWM_CTL = wram("ES_SWM_CTL")            # +0 the live count, +2 the loop beat
SM_FRAME = wram("ES_SM_FRAME")          # scene_mgr's VBlank counter


def labels() -> dict:
    """{name: cpu address} from ld65's VICE label file."""
    out = {}
    for line in LBL.read_text().splitlines():
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


def u16(runner, addr):
    b = runner.read_bytes(W, addr, 2)
    return b[0] | (b[1] << 8)


def set_n(runner, n):
    runner.write_bytes(W, SWM_CTL, bytes([n & 0xFF, n >> 8]))


def used_slots(runner):
    """The compacted run in hardware OAM — how many markers actually drew."""
    raw = runner.read_bytes(OAM, 0, 512)
    n = 0
    while n < 32 and raw[n * 4 + 1] != 0xF0:
        n += 1
    return n


def drive(runner, frames, **buttons):
    for _ in range(frames):
        runner.frame_step(1, **buttons)


def drive2(runner, frames, p1, p2):
    """Both pads at once — the showcase's own input shape."""
    for _ in range(frames):
        runner.frame_step(1, **p1)
        runner.frame_step(1, controller_index=1, **p2)


def measure(runner, marks, frames=3):
    """{routine: [cost in master clocks]} over `frames` passes through the tick."""
    per_hit = []
    hits_needed = 2 * len(ROUTINES) * frames
    with runner.breakpoints([(MEM, a, "exec") for a in marks]):
        for _ in range(hits_needed + 4):
            if not runner.run_to_break(max_frames=180):
                raise RuntimeError("breakpoint never hit")
            st = runner.snes_state_snapshot()
            per_hit.append((marks.get(st.cpu_pc), st.master_clock))
    out = {}
    for i in range(len(per_hit) - 1):
        name, clock = per_hit[i]
        nxt, nxt_clock = per_hit[i + 1]
        if name in ROUTINES and nxt == name + "!":
            out.setdefault(name, []).append(nxt_clock - clock)
    return out


def loop_periods(runner, tick, n=LOOP_PERIODS):
    """The MAIN LOOP'S PERIOD in master clocks: min, median, max.

    THE INSTRUMENT THAT ANSWERS "DOES IT HOLD 60 fps", and it is not the tick
    sum above. One breakpoint, on the tick's ENTRY; the delta between
    consecutive hits is the WHOLE loop — the tick, its dispatch, `input_read`,
    `input2_read`, `sm_tick`, `fade_tick`, `sm_frame_sync` and every NMI that
    fired inside it. `sm_frame_sync` parks the loop on the NMI, so a loop that
    fits reads exactly one frame and one that does not reads two.

    That distinction is the whole point: the tick can sum to 89% of a frame
    and still hold 60 fps, and `100% - tick%` is not the headroom, because
    the rest of the frame is not free (measured here at 4..11%).
    """
    stamps = []
    with runner.breakpoints([(MEM, tick, "exec")]):
        for _ in range(n + 1):
            if not runner.run_to_break(max_frames=240):
                raise RuntimeError("the tick's entry breakpoint never hit")
            stamps.append(runner.snes_state_snapshot().master_clock)
    d = sorted(b - a for a, b in zip(stamps, stamps[1:]))
    return min(d), d[len(d) // 2], max(d)


def report(title, costs, mc, drawn):
    print(f"\n--- {title}  ({drawn} sprite(s) drawn) ---")
    total = 0
    for name in ROUTINES:
        cs = costs.get(name)
        if not cs:
            print(f"  {name:<14} (not reached)")
            continue
        lo, hi = min(cs), max(cs)
        total += hi
        print(f"  {name:<14} {lo:>6}..{hi:<6} mc   (n={len(cs)})")
    print(f"  {'= the tick':<14} {total:>6} mc = {100.0 * total / mc:5.2f}% "
          f"of the frame")
    return total


def main() -> int:
    if not LBL.exists():
        print(f"{LBL} missing — run `make sh2-labels` first")
        return 2
    lab = labels()
    rom = ROM.read_bytes()
    tick = lab["tick"]
    # The tick's body ends at its last callee's `jsr`; scanning to the next
    # label above it is enough for `return_site` and needs no end symbol.
    tick_end = tick + 0x40
    marks = {}
    for name in ROUTINES:
        a = lab[name]
        marks[a] = name
        marks[return_site(rom, tick, tick_end, a)] = name + "!"
    with open(SUPERFORGE / "allocator" / "substrate.toml", "rb") as f:
        mc = tomllib.load(f)["frame"]["ntsc"]["mc_per_frame"]
    print(f"tick ${tick:04X}, {len(ROUTINES)} routines, {len(marks)} "
          f"breakpoints (from {LBL.name}); frame = {mc} mc "
          f"(allocator/substrate.toml [frame.ntsc])")

    runner = MesenRunner()
    try:
        runner.boot_rom(str(ROM), frames=90)

        # --- PARKED: no pad, the state a released controller renders --------
        with runner.frame_stepping():
            drive(runner, 4)
            parked_n = used_slots(runner)
            parked = measure(runner, marks)

        # --- MOST-CULLED: both cameras driven away from the swarm -----------
        with runner.frame_stepping():
            drive2(runner, 60, {"b": True}, {"b": True})
            culled_n = used_slots(runner)
            culled = measure(runner, marks)

        # --- MOST-VISIBLE: rotate both, take the busiest frame we find ------
        runner.boot_rom(str(ROM), frames=90)
        with runner.frame_stepping():
            best, best_n = None, -1
            for _ in range(48):
                runner.frame_step(1, left=True)
                runner.frame_step(1, controller_index=1, right=True)
                n = used_slots(runner)
                if n > best_n:
                    best_n = n
            # ...then park on a frame at that peak and measure there.
            for _ in range(96):
                runner.frame_step(1, left=True)
                runner.frame_step(1, controller_index=1, right=True)
                if used_slots(runner) >= best_n:
                    break
            visible_n = used_slots(runner)
            best = measure(runner, marks)

        # --- THE N SWEEP ----------------------------------------------------
        # Two instruments per row: the tick's callee sum (what the work COSTS)
        # and the main loop's period (whether it FITS). They answer different
        # questions and the second is the stronger claim — see `loop_periods`.
        sweep = {}
        runner.boot_rom(str(ROM), frames=90)
        with runner.frame_stepping():
            for n in SWEEP:
                set_n(runner, n)
                drive(runner, 3)
                costs = measure(runner, marks, frames=2)
                park_loop = loop_periods(runner, tick)
                sweep[n] = (sum(max(costs[r]) for r in ROUTINES if costs.get(r)),
                            used_slots(runner), park_loop)
            set_n(runner, 24)

        # ...and again with BOTH PADS TURNING, which is the busier regime and
        # the one the cadence gate drives. A row that fits parked and not
        # turning is the interesting kind of failure, so it is measured rather
        # than assumed away.
        turning = {}
        runner.boot_rom(str(ROM), frames=90)
        with runner.frame_stepping():
            for n in SWEEP:
                set_n(runner, n)
                drive2(runner, 3, {"left": True}, {"right": True})
                turning[n] = loop_periods(runner, tick)
            set_n(runner, 24)
    finally:
        runner.stop()

    t_park = report("PARKED (no pad held)", parked, mc, parked_n)
    t_cull = report("MOST-CULLED (both pads driving forward)", culled, mc,
                    culled_n)
    t_vis = report("MOST-VISIBLE (both pads rotating, at the peak)", best, mc,
                   visible_n)

    print(f"\n--- the N sweep (SWM_N poked) ---")
    print(f"  {'N':>4}  {'tick mc':>8}  {'% frame':>8}  {'modelled':>9}  "
          f"{'drawn':>5}  {'loop mc':>9}  {'fr/loop':>7}  {'fr/loop':>7}")
    print(f"  {'':>4}  {'':>8}  {'':>8}  {'headroom':>9}  {'':>5}  "
          f"{'(parked)':>9}  {'parked':>7}  {'turning':>7}")
    for n in SWEEP:
        t, drawn, (_lo, med, _hi) = sweep[n]
        _l2, med2, _h2 = turning[n]
        print(f"  {n:>4}  {t:>8}  {100.0 * t / mc:7.2f}%  "
              f"{100.0 * (mc - t) / mc:8.2f}%  {drawn:>5}  {med:>9}  "
              f"{med / mc:7.3f}  {med2 / mc:7.3f}")
    lo, hi = SWEEP[0], SWEEP[-1]
    slope = (sweep[hi][0] - sweep[lo][0]) / (hi - lo)
    print(f"  slope over N={lo}..{hi}: {slope:.0f} mc per entity "
          f"(AI + both bands' projection)")

    # THE CLIFF, read off the loop period rather than off the model. A row
    # counts as fitting only if it fits in BOTH regimes.
    fits = [n for n in SWEEP
            if round(sweep[n][2][1] / mc, 3) <= 1.0
            and round(turning[n][1] / mc, 3) <= 1.0]
    miss = [n for n in SWEEP if n not in fits]
    print(f"  the measured cadence cliff: 1.000 frames/loop up to N={max(fits)}"
          f"; the first sampled N that does not fit is "
          f"{min(miss) if miss else 'none in the grid'}")
    print(f"  NOTE the two things this table is NOT. (1) 'tick mc' is the sum "
          f"of each routine's MAXIMUM over its samples, not any one frame's "
          f"tick — an upper envelope. (2) '100% - tick%' is a MODEL, not the "
          f"headroom: the tick excludes its own dispatch, input_read, "
          f"input2_read, sm_tick, fade_tick and sm_frame_sync, which the "
          f"loop-period columns include. Where the two disagree, believe the "
          f"loop period.")

    print(f"\nthe span the rail is judged on: {min(t_park, t_cull, t_vis)}.."
          f"{max(t_park, t_cull, t_vis)} mc = "
          f"{100.0 * min(t_park, t_cull, t_vis) / mc:.2f}.."
          f"{100.0 * max(t_park, t_cull, t_vis) / mc:.2f}% of the frame")
    return 0


if __name__ == "__main__":
    sys.exit(main())
