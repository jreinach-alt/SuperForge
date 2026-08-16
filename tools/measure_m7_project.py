#!/usr/bin/env python3
"""measure_m7_project.py — what the world->screen projection costs, measured.

CLAUDE.md rule 1: measure cycle counts, never estimate. This drives the
SHIPPING m7_dungeon ROM — not a probe built for the occasion — with execution
breakpoints at four addresses and reads Mesen's master clock at each hit:

    obj_draw            the whole per-frame cast: hero + three enemies
    m7p_project         one world point, entered
    (the return site)   ...and left
    tick's rts          the cast finished

so a run yields both the aggregate (what the frame pays for sprites) and its
decomposition (what ONE projection costs, and what a pre-culled point costs
instead — the comparisons-only path that never multiplies).

THE ADDRESSES ARE READ, NOT TRANSCRIBED. `make m7dg-labels` assembles a twin
with `-g`, links it with `-Ln`, and `cmp`s the result against the shipped
`.sfc`; a label file that does not describe the shipping binary fails there
rather than quietly measuring something else. The return site is then found by
scanning obj_draw's own bytes for the `jsr` — the same "ask, never hardcode"
rule the tests follow for addresses.

Usage:  python3 tools/measure_m7_project.py [heading ...]
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
HEADING = next(p["start"] for p in SYMS["scenes"]["dungeon"]["placements"]
               if p["sym"] == "US_HEADING")


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

    LoROM bank 0: CPU $8000-$FFFF is file offset $0000-$7FFF.
    """
    pat = bytes([0x20, callee & 0xFF, callee >> 8])
    at = rom.index(pat, caller - 0x8000, end - 0x8000)
    return 0x8000 + at + 3


def park_at(runner, heading, limit=600):
    with runner.frame_stepping():
        for _ in range(limit):
            if runner.read_bytes(W, HEADING, 2)[0] == heading:
                return
            runner.frame_step(1)
    raise RuntimeError(f"heading never reached {heading}")


def trace(runner, marks, frames=1):
    """[(name, master_clock)] over `frames` passes through obj_draw."""
    got = []
    with runner.breakpoints([(MEM, a, "exec") for a in marks]):
        # 4 breakpoints x (1 obj_draw + 3 projections x 2 + 1 rts) per frame
        for _ in range(8 * frames):
            # 600 EMULATED frames, not a wall deadline: a False here is a
            # claim about the ROM rather than about host load.
            if not runner.run_to_break(max_frames=600):
                raise RuntimeError("breakpoint never hit")
            st = runner.snes_state_snapshot()
            got.append((marks.get(st.cpu_pc, hex(st.cpu_pc)), st.master_clock))
    return got


def main(argv) -> int:
    if not LBL.exists():
        print(f"{LBL} missing — run `make m7dg-labels` first")
        return 2
    lab = labels()
    rom = ROM.read_bytes()
    obj_draw, tick, proj = lab["obj_draw"], lab["tick"], lab["m7p_project"]
    ret = return_site(rom, obj_draw, tick, proj)
    tick_rts = tick + 11            # lda/inc/sta/jsr/jsr = 11 bytes, then rts
    assert rom[tick_rts - 0x8000] == 0x60, "tick does not end in rts where expected"
    marks = {obj_draw: "obj_draw", proj: "proj", ret: "proj_end",
             tick_rts: "done"}
    print(f"obj_draw ${obj_draw:04X}  m7p_project ${proj:04X}  "
          f"return ${ret:04X}  tick rts ${tick_rts:04X}   (from {LBL.name})")

    headings = [int(a) for a in argv[1:]] or [0, 10, 40, 91, 150, 203]
    runner = MesenRunner()
    rows = []
    try:
        runner.boot_rom(str(ROM), frames=90)
        for h in headings:
            park_at(runner, h)
            runner.debug_break()
            ev = trace(runner, marks)
            # one pass: obj_draw ... (proj, proj_end) x3 ... done
            start = next(i for i, (n, _) in enumerate(ev) if n == "obj_draw")
            ev = ev[start:]
            total = next(c for n, c in ev if n == "done") - ev[0][1]
            calls = [(ev[i + 1][1] - ev[i][1])
                     for i in range(len(ev) - 1)
                     if ev[i][0] == "proj" and ev[i + 1][0] == "proj_end"]
            rows.append((h, total, calls))
    finally:
        runner.stop()

    print(f"\n{'heading':>8} {'obj_draw (mc)':>14}   per m7p_project call (mc)")
    for h, total, calls in rows:
        print(f"{h:>8} {total:>14}   {calls}")

    # The calls come in enemy order, and the three enemies are three different
    # shapes — which is the decomposition worth reading, not a min/max over a
    # threshold. Enemy 0 sits on the pivot's own row, so its dy is ZERO and two
    # of the four multiplies exit on their first test; enemy 1 is the only seed
    # that exercises all four; enemy 2 is outside the circumradius and never
    # reaches a multiply at all.
    by_enemy = [[cs[i] for _, _, cs in rows if len(cs) > i] for i in range(3)]
    totals = [t for _, t, _ in rows]
    shape = ["dy = 0: two of four products are trivial",
             "dx and dy both non-zero: the full four products",
             "pre-culled: comparisons only, never multiplies"]
    print()
    for i, (cs, why) in enumerate(zip(by_enemy, shape)):
        if cs:
            print(f"enemy {i}  {min(cs):>6}..{max(cs):<6} mc   {why}")
    print(f"obj_draw whole  {min(totals)}..{max(totals)} mc "
          f"(hero + all three enemies, every frame)")
    projected = by_enemy[1] or by_enemy[0]

    with open(SUPERFORGE / "allocator" / "substrate.toml", "rb") as f:
        frame = tomllib.load(f)["frame"]["ntsc"]
    mc = frame.get("mc_per_frame")
    if isinstance(mc, int):
        print(f"\nframe = {mc} mc (allocator/substrate.toml [frame.ntsc])")
        print(f"  obj_draw worst = {max(totals)} mc = "
              f"{100.0 * max(totals) / mc:.2f}% of the frame")
        for n in (3, 8, 16):
            cost = n * max(projected)
            print(f"  {n:>2} full projections = {cost:>6} mc = "
                  f"{100.0 * cost / mc:5.2f}% of the frame")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
