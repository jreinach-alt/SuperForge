#!/usr/bin/env python3
"""measure_m7dg_logic.py — what the m7_dungeon GAME costs, per frame, measured.

CLAUDE.md rule 1: measure cycle counts, never estimate. This drives the
SHIPPING m7_dungeon ROM — not a probe built for the occasion — with execution
breakpoints at each of the tick's routines and its return site, and reads
Mesen's master clock at every hit. The sibling of tools/measure_m7_project.py,
which does the same for the projection; between them the whole tick is
accounted for.

WHAT IS BEING PAID FOR. The rail's per-frame work is dominated by ONE thing —
`col_map_at`, called four times per footprint probe and five times per frame
(the hero's two axes plus three pacing enemies), so TWENTY world-space tile
lookups a frame before a single sprite is placed. The decomposition below is
what makes that visible rather than asserted:

    do_turn       the pad -> the heading
    do_throttle   the pad -> the signed 8.8 speed
    do_integrate  (sin, cos) x speed -> the 16.16 step  (one m7p_mul each)
    move_x        candidate, clamp, FOUR col_map_at probes, commit-or-not
    move_y        the same, at the already-committed x
    do_patrol     three enemies, one paced step each, FOUR probes each
    do_contact    the grace gate, the sanctuary, three AABB tests
    obj_draw      the cast (measured in detail by measure_m7_project.py)

THE ADDRESSES ARE READ, NOT TRANSCRIBED. `make m7dg-labels` assembles a twin
with `-g`, links it with `-Ln`, and `cmp`s the result against the shipped
`.sfc`; a label file that does not describe the shipping binary fails there
rather than quietly measuring something else. Each routine's return site is
then found by scanning the tick's own bytes for the `jsr` that calls it — the
same "ask, never hardcode" rule the tests follow for addresses.

TWO WORLD STATES, because the cost is not one number. At REST the throttle
coasts and the multiply exits on its first test; UNDER THROTTLE the speed is at
the cap and both multiplies run their full significant-bit loops. Both are
reported, and the difference between them is the honest span.

Usage:  python3 tools/measure_m7dg_logic.py
"""
import json
import sys
import tomllib
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from mesen_runner import MemoryType, MesenRunner  # noqa: E402

ROM = SUPERFORGE / "build" / "m7_dungeon.sfc"
LBL = SUPERFORGE / "build" / "m7_dungeon.lbl"
SYMS = json.loads((SUPERFORGE / "build" / "m7dg" / "symbol_map.json").read_text())

W, MEM = MemoryType.SnesWorkRam, MemoryType.SnesMemory
DP = {p["sym"]: p["start"] for p in SYMS["scenes"]["dungeon"]["placements"]}

# The tick's callees, in the order the tick calls them. `do_pause` is first and
# is deliberately not measured on its own: it is four loads and a compare, and
# breaking on it costs more emulator round-trips than the number is worth.
ROUTINES = ["do_turn", "do_throttle", "do_integrate", "move_x", "move_y",
            "do_patrol", "do_contact", "obj_draw"]


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


def drive(runner, frames, **buttons):
    for _ in range(frames):
        runner.frame_step(1, **buttons)


def measure(runner, marks, frames=3):
    """{routine: [cost in master clocks]} over `frames` passes through the tick."""
    per_hit = []
    hits_needed = 2 * len(ROUTINES) * frames
    with runner.breakpoints([(MEM, a, "exec") for a in marks]):
        for _ in range(hits_needed + 4):
            # 600 EMULATED frames, not a wall deadline: a False here is a
            # claim about the ROM rather than about host load.
            if not runner.run_to_break(max_frames=600):
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


def report(title, costs):
    print(f"\n--- {title} ---")
    total = 0
    for name in ROUTINES:
        cs = costs.get(name)
        if not cs:
            print(f"  {name:<14} (not reached)")
            continue
        lo, hi = min(cs), max(cs)
        total += hi
        print(f"  {name:<14} {lo:>6}..{hi:<6} mc   (n={len(cs)})")
    return total


def main() -> int:
    if not LBL.exists():
        print(f"{LBL} missing — run `make m7dg-labels` first")
        return 2
    lab = labels()
    rom = ROM.read_bytes()
    tick, tick_end = lab["tick"], lab["do_pause"]
    marks = {}
    for name in ROUTINES:
        a = lab[name]
        marks[a] = name
        marks[return_site(rom, tick, tick_end, a)] = name + "!"
    print(f"tick ${tick:04X}, {len(ROUTINES)} routines, "
          f"{len(marks)} breakpoints (from {LBL.name})")

    runner = MesenRunner()
    try:
        runner.boot_rom(str(ROM), frames=30)
        with runner.frame_stepping():
            drive(runner, 4)                        # settle, at rest
            rest = measure(runner, marks)
        with runner.frame_stepping():
            drive(runner, 40, b=True)               # ...and at the speed cap
            assert u16(runner, DP["US_SPEED"]) != 0, "the hero never moved"
            moving = measure(runner, marks)
    finally:
        runner.stop()

    t_rest = report("at rest (no throttle)", rest)
    t_move = report("under throttle (at the speed cap)", moving)

    # The brief's question is what the LOGIC costs — collision, patrol,
    # contact — as distinct from the cast, which measure_m7_project.py already
    # decomposes. Both are reported so neither has to be inferred.
    def group(costs, names):
        return sum(max(costs[n]) for n in names if costs.get(n))

    logic = ["move_x", "move_y", "do_patrol", "do_contact"]
    inputs = ["do_turn", "do_throttle", "do_integrate"]
    with open(SUPERFORGE / "allocator" / "substrate.toml", "rb") as f:
        mc = tomllib.load(f)["frame"]["ntsc"].get("mc_per_frame")
    print(f"\nframe = {mc} mc (allocator/substrate.toml [frame.ntsc])")
    for title, costs, total in (("at rest", rest, t_rest),
                                ("under throttle", moving, t_move)):
        g_logic, g_in, g_obj = (group(costs, logic), group(costs, inputs),
                                group(costs, ["obj_draw"]))
        print(f"  {title}:")
        print(f"    collision + patrol + contact  {g_logic:>6} mc = "
              f"{100.0 * g_logic / mc:5.2f}% of the frame")
        print(f"    input + throttle + integrate  {g_in:>6} mc = "
              f"{100.0 * g_in / mc:5.2f}%")
        print(f"    the cast (obj_draw)           {g_obj:>6} mc = "
              f"{100.0 * g_obj / mc:5.2f}%")
        print(f"    the whole tick                {total:>6} mc = "
              f"{100.0 * total / mc:5.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
