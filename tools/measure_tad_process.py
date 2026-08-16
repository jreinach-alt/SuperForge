#!/usr/bin/env python3
"""measure_tad_process.py — Tad_Process steady-state per-frame cost, measured
on the cycle-accurate emulator against the REAL build/room.sfc (never a
modified copy, never an estimate).

The G6 measurement owed by the audio design review: the room
game's main loop pays one `jsl Tad_Process` every frame (game/room/main.asm);
this tool measures what that call costs in steady state — music PLAYING, SFX
queue empty, no load in flight.

Method — exec-breakpoint bracketing of the shipped ROM (the "instrument via
the debugger's cycle counting between parked points" shape; cousin of
measure_col_map_cost.py's mark-write bracketing):

  1. Relink the exact build objects with `-Ln` into a temp dir and REQUIRE the
     relinked+checksum-fixed image byte-identical to build/room.sfc — so the
     label addresses provably describe the ROM being measured. Take
     Tad_Process from the labels; find the unique `22 <addr>` (jsl) site in
     the ROM bytes. Nothing is hardcoded; a drifted build fails loudly.
  2. Exec breakpoints on the `jsl Tad_Process` instruction and on the
     instruction after it. master_clock delta between consecutive hits =
     jsl + Tad_Process body + rtl — the per-frame price the loop pays.
  3. Sample at the title and in room A idle. Both brackets sit in VBLANK
     (scanlines 235/237), where Mesen2 never schedules HDMA processing —
     so the room-vs-title delta is NOT an HDMA steal (measurement falsified
     that first reading). The delta is the per-scanline DRAM REFRESH slot
     (hClock ~538, exactly 40 mc, IncMasterClock40): it fires every
     scanline at both sites, and only the ROOM bracket's phase-locked
     hClock window [244..724] contains it (the title's [732..1168] does
     not). Refresh is machine overhead, not Tad_Process work — TAD state
     is identical at both sample sites and both distributions are
     bit-stable; delta-corrected, the two sites agree exactly.
     Full evidence:

Units: master clock is the measured quantity. CPU cycles = mc / 8, because
every fetch runs through bank $00 (vendor/rom/lorom_512k.cfg links all CODE
into ROM0 at $00:8000) where ROM pages are unconditionally 8 mc/cycle — the
header's FastROM byte + MEMSEL=1 accelerate only banks $80-$BF/$C0-$FF
(Mesen2 SnesMemoryManager.cpp: bank-0 quadrant page>=$80 -> 8, vs the
MEMSEL-gated 6/8 for the mirror quadrants). WRAM/DP are 8 mc; I/O and
internal cycles are 6 mc, so /8 slightly undercounts true cycles (the true
count sits in [mc/8, mc/6]); /8 is the repo's slow-bus convention (divide
master clocks by 8, per docs/01's budget table) and the honest headline for
a bank-$00 ROM.

Usage:  python3 tools/measure_tad_process.py    (after `make room`)
"""
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from mesen_runner import MemoryType, MesenRunner  # noqa: E402

WR, DSP = MemoryType.SnesWorkRam, MemoryType.SpcDspRegisters
MEM = MemoryType.SnesMemory
ROM = SUPERFORGE / "build" / "room.sfc"

# Allocator-emitted addresses, never literals (the test-suite idiom).
SYMS = {p["sym"]: p for p in json.loads(
    (SUPERFORGE / "build" / "rm" / "symbol_map.json").read_text())["globals"]}
TAD_STATE_ADDR = SYMS["ES_TAD_BSS"]["start"] + 2   # TadPrivate_state (+2: after
                                                   # Tad_flags, Tad_audioMode)
TAD_ZP = SYMS["ES_TAD_ZP"]["start"]                # Tad_sfxQueue_sfx/pan
STATE_PLAYING = 0x82                               # TadState::PLAYING
QUEUE_EMPTY = 0xFF                                 # tad-audio.s:992-994/1199-1201


def derive_bracket() -> tuple[int, int]:
    """(jsl_site, return_site) CPU addresses, derived from a verified relink."""
    with tempfile.TemporaryDirectory() as td:
        sfc, lbl = Path(td) / "relink.sfc", Path(td) / "relink.lbl"
        objs = [SUPERFORGE / "build" / o for o in
                ("room.o", "rm_tad_wrapper.o", "rm_tad_data.o")]
        subprocess.run(["ld65", "-C", str(SUPERFORGE / "vendor/rom/lorom_512k.cfg"),
                        "-o", str(sfc), *map(str, objs), "-Ln", str(lbl)],
                       check=True)
        subprocess.run([sys.executable, str(SUPERFORGE / "tools/fix_checksum.py"),
                        str(sfc)], check=True, capture_output=True)
        if hashlib.md5(sfc.read_bytes()).hexdigest() != \
                hashlib.md5(ROM.read_bytes()).hexdigest():
            raise SystemExit("relink is NOT byte-identical to build/room.sfc — "
                             "stale objects? run `make room` and retry")
        tad_process = None
        for line in lbl.read_text().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2] == ".Tad_Process":
                tad_process = int(parts[1].split(":")[-1], 16)
        if tad_process is None:
            raise SystemExit("Tad_Process not in the label file")
    rom = ROM.read_bytes()
    pat = bytes([0x22, tad_process & 0xFF, (tad_process >> 8) & 0xFF,
                 (tad_process >> 16) & 0xFF])
    hits, i = [], rom.find(pat)
    while i != -1:
        hits.append(i)
        i = rom.find(pat, i + 1)
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one `jsl Tad_Process` site, "
                         f"found {len(hits)}: {[hex(h) for h in hits]}")
    bank, off = divmod(hits[0], 0x8000)          # LoROM file->CPU mapping
    site = (bank << 16) | (0x8000 + off)
    print(f"Tad_Process=${tad_process:06X}  jsl site=${site:06X}  "
          f"return site=${site + 4:06X}  (derived; relink md5-verified)")
    return site, site + 4


def sample(r: MesenRunner, site: int, ret: int, n: int) -> list[int]:
    """n consecutive frames' [jsl .. after-rtl] master-clock deltas. Every
    hit's (K, PC) is asserted so a missed break cannot corrupt a sample."""
    out = []
    with r.breakpoints([(MEM, site, "exec"), (MEM, ret, "exec")]):
        for _ in range(3):                       # align to the jsl site first
            if not r.run_to_break(max_frames=600):
                raise SystemExit("breakpoint never hit — wrong address?")
            s = r.snes_state_snapshot()
            if (s.cpu_k, s.cpu_pc) == (site >> 16, site & 0xFFFF):
                break
        else:
            raise SystemExit("never landed on the jsl site")
        while len(out) < n:
            mc0 = r.snes_state_snapshot().master_clock
            for expect in (ret, site):
                if not r.run_to_break(max_frames=600):
                    raise SystemExit("breakpoint never hit mid-sample")
                s = r.snes_state_snapshot()
                if (s.cpu_k, s.cpu_pc) != (expect >> 16, expect & 0xFFFF):
                    raise SystemExit(f"expected ${expect:06X}, stopped at "
                                     f"${s.cpu_k:02X}:{s.cpu_pc:04X}")
                if expect == ret:
                    out.append(s.master_clock - mc0)
    return out


def preconditions(r: MesenRunner) -> dict:
    d = r.read_bytes(DSP, 0, 128)
    return dict(state=r.read_bytes(WR, TAD_STATE_ADDR, 1)[0],
                queue=tuple(r.read_bytes(WR, TAD_ZP, 2)),
                sfx_envx={v: d[v * 0x10 + 8] for v in (6, 7)})


def require_steady(pre: dict, where: str) -> None:
    if pre["state"] != STATE_PLAYING:
        raise SystemExit(f"{where}: TadPrivate_state={pre['state']:#04x} "
                         f"!= PLAYING — not steady state")
    if pre["queue"] != (QUEUE_EMPTY, QUEUE_EMPTY):
        raise SystemExit(f"{where}: SFX queue {pre['queue']} not empty")
    if any(v != 0 for v in pre["sfx_envx"].values()):
        raise SystemExit(f"{where}: an SFX voice is live "
                         f"(ENVX {pre['sfx_envx']}) — not steady state")


def report(name: str, xs: list[int], frame_mc: int) -> None:
    dist = sorted(Counter(xs).items())
    worst = max(xs)
    print(f"{name}: n={len(xs)} min={min(xs)} "
          f"median={statistics.median(xs):.0f} max={worst} mc  "
          f"distribution={dist}")
    print(f"  worst {worst} mc = {worst / 8:.1f} CPU cycles (/8, bank-$00 "
          f"slow bus) = {100 * worst / frame_mc:.3f}% of the {frame_mc} mc "
          f"frame  [true cycles in {worst / 8:.0f}..{worst / 6:.0f}]")


def main() -> int:
    with open(SUPERFORGE / "allocator" / "substrate.toml", "rb") as f:
        frame_mc = tomllib.load(f)["frame"]["ntsc"]["mc_per_frame"]
    site, ret = derive_bracket()
    r = MesenRunner()
    try:
        r.boot_rom(str(ROM), frames=120)
        for _ in range(80):                      # async song load behind title
            if r.read_bytes(WR, TAD_STATE_ADDR, 1)[0] == STATE_PLAYING:
                break
            r.frame_step(10)
        else:
            raise SystemExit("song never reached PLAYING")
        pre = preconditions(r)
        require_steady(pre, "title")
        print(f"title preconditions: {pre}")
        title = sample(r, site, ret, 32)

        r.frame_step(3, start=True)              # title -> room A
        r.frame_step(3)
        r.frame_step(60)                         # fade + enter + fade-in
        r.frame_step(150)                        # ambience one-shot finished
        pre = preconditions(r)
        require_steady(pre, "room A")
        print(f"room A preconditions: {pre}")
        room = sample(r, site, ret, 64)
    finally:
        r.stop()

    report("title steady-state (bracket phase misses the refresh slot)",
           title, frame_mc)
    report("room A steady-state (in-situ; bracket phase contains the "
           "refresh slot)", room, frame_mc)
    if len(set(title)) == 1 and len(set(room)) == 1:
        delta = room[0] - title[0]
        print(f"both distributions bit-stable; room-title delta {delta} mc = "
              f"the per-scanline DRAM refresh slot (hClock ~538, "
              f"IncMasterClock40) inside the room bracket's phase window "
              f"only — machine overhead, not Tad_Process work; TAD state "
              f"identical at both sites (both brackets are in VBlank, where "
              f"HDMA never processes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
