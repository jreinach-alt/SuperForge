#!/usr/bin/env python3
"""rate_oracle.py — what is a rail's REAL-TIME progress rate, per region?

WHY THIS EXISTS. `docs/93` reported "every rail runs at 83.2% of NTSC speed
under PAL" and `docs/94` §2 made speed parity the requirement. Neither number
could be reproduced on demand: there was no instrument that answered, for a
given rail, *how far does the game get per REAL SECOND, on each machine, and
what is the ratio?* `tools/pal_probe.py` answers the neighbouring question —
"is frame N the same picture in both regions?" — and that one is deliberately
frame-anchored, so it cannot see a speed difference at all: at equal frame
index the two regions agree, and that agreement IS the 17%-slow bug.

This tool is the missing half. It is anchored on REAL TIME, not on frames.

--------------------------------------------------------------------------
WHAT IT MEASURES, AND WHY THAT IS NOT A FRAME COUNT
--------------------------------------------------------------------------

A frame counter trivially reports 50 vs 60 and tells you nothing: the player
does not see frames, they see the ship move. So every observable here is
GAME-VISIBLE PROGRESS — a world position, a camera origin the PPU renders
from, a drawn sprite tile, a landing — and each one carries, in the registry
below, the sentence that says why it is a fair measure of "progress" for its
rail. Read those sentences before trusting a ratio.

Real time is derived from the MASTER CLOCK, which the emulator advances at
the region's own rate:

    Mesen2 `Core/SNES/SnesConsole.cpp:209`
        _masterClockRate = _region == ConsoleRegion::Pal ? 21281370 : 21477270;

so real seconds = (master cycles elapsed) / (that rate). Both endpoints of a
measurement window are read exactly, so the rate is Δprogress / Δreal-seconds
with no frame-quantisation term: the *sample instants* differ between regions,
but each is timed exactly and the division is exact. What is left is the
observable's own non-uniformity, which `--halves` reports so the reader can
judge it rather than take it on trust.

--------------------------------------------------------------------------
THE INPUT SCRIPT IS INDEXED ON SECONDS, NOT ON FRAMES — this is load-bearing
--------------------------------------------------------------------------

A human holds RIGHT for two seconds, not for 120 frames. A frame-indexed
script hands PAL 100 frames of RIGHT where NTSC got 120, which is itself a
5/6 throttle on the input, and the rail would then measure slow *because the
harness drove it slow*. Every script below is written in SECONDS and each
region converts with its own frame period. What the ratio then reports is the
game's rate difference and nothing else.

--------------------------------------------------------------------------
THE ONE-PROCESS CONSTRAINT
--------------------------------------------------------------------------

`mesen_runner._apply_region` runs once per process (from
`_make_base_snes_config`), so NTSC and PAL cannot share a process.
`tools/pal_probe.py` solved this by re-executing itself once per region and
diffing the two children's JSON; this follows that precedent exactly rather
than inventing a second pattern.

--------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------

    python3 tools/rate_oracle.py --list
    python3 tools/rate_oracle.py racer
    python3 tools/rate_oracle.py scroller racer brawler platformer
    python3 tools/rate_oracle.py racer --window 20 --halves
    python3 tools/rate_oracle.py racer --json build/rate_racer.json
    python3 tools/rate_oracle.py racer --picture-at 8.0 --outdir build/rate_shots

    # a variant image (deliverable 3's flag builds) under the same registry:
    python3 tools/rate_oracle.py racer --rom build/racer_tb_accum.sfc \
        --label accum

Report-only: it asserts nothing and exits 0 unless a child process fails —
the same contract `tools/pal_probe.py` and `tools/active_lines.py` hold.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import subprocess
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

# Mesen2 Core/SNES/SnesConsole.cpp:209 — read, not remembered. These are the
# rates the emulator actually advances the master clock at, so they are the
# only correct divisor for turning master cycles into real seconds.
MASTER_HZ = {"ntsc": 21_477_270, "pal": 21_281_370}


# ===========================================================================
# THE REGISTRY — one entry per rail, and every observable states its case
# ===========================================================================
#
# `fields` addresses are ALWAYS (claim symbol, byte offset inside the claim).
# The claim's base comes from the allocator's emitted symbol map; the offset
# is the feature's own documented field layout, cited by file:line so it can
# be re-checked when the feature moves. Nothing here is a raw address.
#
# kinds:
#   "distance"     Σ |unwrapped Δ| of one field — path length along an axis.
#                  Unwrapping uses the field's modulus, so a world that wraps
#                  is measured, not truncated.
#   "path2d"       Σ sqrt(Δx² + Δy²) over two fields — path length in 2-D.
#   "advance"      Σ unwrapped Δ (signed) — net displacement.
#   "transitions"  number of frames on which the value CHANGED — the rate at
#                  which a drawn thing visibly changes.
#   "edges"        number of 0 -> non-0 transitions — discrete events.
#
# `gate` (optional) narrows the DENOMINATOR: a rate is numerator / seconds,
# and `gate=(sym, width, value)` counts only the seconds in which that word
# holds that value. It exists because of a measured trap, and the trap is
# worth stating: a jump driven by a real-time input script lands at the
# SCRIPT'S cadence in both regions, so "landings per second" reads 0.99969 —
# PARITY — while the rail is plainly running 17% slow. What that observable
# measured was the harness. Gating the denominator on "airborne" turns it
# into "arcs completed per second OF FLIGHT", which is a property of gravity
# and the arc alone and reads the rail's real ratio. Any observable whose
# numerator the drive script can pace needs a gate, or it is measuring the
# drive.
#
# `mem`: "wram" (dp and wram claims alike — dp is WRAM offset 0 in this kit,
# which is why tests read dp claims straight out of SnesWorkRam) or "oam"
# (the sprite table the PPU actually draws from; slot index comes from the
# rail's `ES_O_*` claim, byte is the offset inside the 4-byte entry).

def _shuttle(period_s, run_s, jump_every_s, jump_hold_s, start_s, n=60):
    """A pad script that runs right/left on a fixed real-time period and taps
    JUMP on another. Written in SECONDS, so each region converts it with its
    own frame period and neither machine is handed more input than the other."""
    out = [(0.0, {})]
    if start_s is not None:
        out += [(start_s, {"start": True}), (start_s + 0.3, {})]
    for k in range(n):
        t = run_s + k * jump_every_s
        held = {}
        if period_s is not None:
            held = {"right" if (int((t - run_s) // period_s) % 2 == 0)
                    else "left": True}
        out.append((t, dict(held, a=True)))
        out.append((t + jump_hold_s, dict(held)))
    return out


def _hop_shuttle(half_ms, jump_every_ms, jump_hold_ms, total_ms,
                 first="left", t0_ms=0, step_ms=25):
    """A pad script that paces LEFT/RIGHT on a real-time half-period and taps
    JUMP on another, both written in REAL TIME so each region converts them
    with its own frame period and neither machine is handed more input than
    the other (the module header's load-bearing rule). Marks begin at
    `t0_ms`, so a caller can prepend a lead-in that walks the actor somewhere
    before the shuttle starts. Consecutive identical pad states are
    collapsed, so the returned list is the state CHANGES.

    EVERY PERIOD IS AN INTEGER NUMBER OF MILLISECONDS and every division here
    is integer division, which is not fussiness — it is a measured defect in
    the first draft, which did the same arithmetic in float seconds. `0.4 //
    0.2` is 1.0 and `0.6 // 0.2` is 2.0, so alternate legs came out 0.25 s
    and 0.15 s: a systematic 12 px LEFT drift per leg pair that walked the
    player 76 px out of the corridor the drive was written to keep it in,
    onto a platform, and mixed two arc lengths into one number (the `jumper`
    entry's halves read 1.717 / 2.096 and the diagnostic put x at [92, 152]
    against an intended [144, 168]). A drive script that quietly drifts is
    measuring itself."""
    other = "right" if first == "left" else "left"
    out = []
    for k in range(0, total_ms - t0_ms + 1, step_ms):
        pad = {first if (k // half_ms) % 2 == 0 else other: True}
        if k % jump_every_ms < jump_hold_ms:
            pad["a"] = True
        if not out or out[-1][1] != pad:
            out.append(((t0_ms + k) / 1000.0, pad))
    return out


RAILS = {
    # ---------------------------------------------------------------- SCROLL
    "scroller": dict(
        rom="build/scroller.sfc", map="build/scr/symbol_map.json",
        scene="world",
        klass="scrolling",
        # Hold RIGHT for the whole run. This rail is the BG pipeline alone, so
        # the camera IS the picture and there is nothing else to disturb it.
        script=[(0.0, {"right": True})],
        warmup_s=2.0, window_s=12.0, guard=[],
        observables=[
            dict(name="cam_x", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_SCR_CAM", 0, 2, 65536)],
                 why="`scroller_bg`'s VBlank commit writes BG1HOFS straight "
                     "from this word (scroller_bg.asm:193). It is the scroll "
                     "position the PPU renders with, so world pixels per "
                     "second here IS the speed the picture slides at."),
        ],
    ),
    # ---------------------------------------------------------------- MODE 7
    "racer": dict(
        rom="build/racer.sfc", map="build/rc/symbol_map.json",
        scene="race",
        klass="mode7",
        # B is the throttle (rc_logic.asm:150); holding RIGHT as well puts the
        # kart into a constant-radius circle. It leaves the track and settles
        # at the off-road speed cap, and that is deliberate: the resulting
        # motion is exactly uniform (4 px and 1 heading unit per frame, both
        # measured), which is the most precise thing this rail can be asked
        # to do. The Mode 7 camera integrator, the pose retarget and the
        # streamer are all on the frame path throughout.
        script=[(0.0, {"b": True, "right": True})],
        warmup_s=4.0, window_s=12.0, guard=[("US_PAUSED", 1, 0)],
        observables=[
            dict(name="m7_path", kind="path2d", unit="world px",
                 mem="wram",
                 fields=[("ES_M7ORG", 0, 2, 4096), ("ES_M7ORG", 2, 2, 4096)],
                 why="ES_M7ORG +0/+2 are M7X/M7Y — 'the camera\'s world pixel "
                     "x/y' in rc_logic.asm:187, committed to the PPU by the "
                     "NMI hook every VBlank (mode7_persp.asm:134). The floor "
                     "is drawn FROM this point, so the path length it traces "
                     "is exactly the ground the player covers. The modulus is "
                     "the streamed world's 4,096 px, not 65,536: a 16-bit "
                     "unwrap would read the world wrap as a 4,056 px jump."),
            dict(name="heading", kind="distance", unit="heading units",
                 mem="wram", fields=[("US_HEADING", 0, 1, 64)],
                 why="the kart\'s heading, 0..63. mode7_persp retargets the "
                     "pose LUTs from it, so the WHOLE FLOOR rotates by it — "
                     "heading units per second is the rate the world turns "
                     "under the player, which no position measure captures."),
        ],
    ),
    # ------------------------------------------------------- SPRITE ANIMATION
    "brawler": dict(
        rom="build/brawler.sfc", map="build/br/symbol_map.json",
        scene="fight",
        klass="sprite animation",
        # Walk LEFT and keep walking. Measured: the foe drifts away, HP
        # settles at 2 and `gameover` stays 0 for at least 23 s, so the walk
        # cycle runs the whole window. A shuttle drive walks back into the
        # foe and dies at ~7 s, which is not long enough to adjudicate 1%.
        script=[(0.0, {"left": True})],
        warmup_s=6.0, window_s=14.0,
        guard=[("US_GAMEOVER", 2, 0), ("US_HP", 2, 2)],
        observables=[
            dict(name="knight_tile", kind="transitions", unit="tile changes",
                 mem="oam", fields=[("ES_O_KNIGHTS", 2, 1, 256)],
                 why="the player knight\'s OAM tile byte, read out of the "
                     "sprite table the PPU draws from — rendered output, not "
                     "the counter behind it. Counting the frames on which the "
                     "drawn tile CHANGES measures the walk cycle in the only "
                     "place a player can perceive it."),
            dict(name="px", kind="distance", unit="world px",
                 mem="wram", fields=[("US_PX", 0, 2, 65536)],
                 why="the knight\'s world x, which brawler_obj turns into the "
                     "OAM X. Walking speed in world pixels per second is the "
                     "other half of 'the same animation at the same speed'."),
        ],
    ),
    # -------------------------------------------------------------- PHYSICS
    "platformer": dict(
        rom="build/platformer.sfc", map="build/pl/symbol_map.json",
        scene="play",
        klass="physics / jump",
        # START clears the title, then bounce on the spawn tile by ALTERNATING
        # A and B every 0.25 s. Two measured reasons for that odd script:
        #
        #  * standing still keeps the hero alive. A run-and-shuttle drive
        #    walks him into a patrolling ghost inside 5 s and the guard below
        #    fires; bouncing on the spawn tile holds `lives` at 3 for 22 s+.
        #  * `do_jump` (play.asm:449) launches on the PRESS EDGE of A-or-B and
        #    CUTS THE RISE when neither is held — a variable-height jump. A
        #    fixed real-time hold therefore buys 9 rise frames on NTSC and 7.5
        #    on PAL, so the two regions fly DIFFERENT ARCS and the ratio
        #    measures the cut, not the engine. Alternating the two face
        #    buttons keeps one of them held at all times (never cut) while
        #    still delivering a fresh press edge (always able to launch), so
        #    both regions fly the SAME full-height arc.
        script=[(0.0, {}), (0.5, {"start": True}), (0.8, {})]
               + [(1.2 + 0.25 * k, {"a": True} if k % 2 == 0 else {"b": True})
                  for k in range(160)],
        warmup_s=3.0, window_s=14.0,
        guard=[("US_GOVER", 2, 0), ("US_LIVES", 2, 3)],
        observables=[
            dict(name="arc_rate", kind="edges", unit="arcs / airborne s",
                 mem="wram", fields=[("US_GROUNDED", 0, 2, 65536)],
                 gate=("US_GROUNDED", 2, 0),
                 why="0 -> non-0 on US_GROUNDED is the frame the hero TOUCHES "
                     "DOWN, and the denominator counts only the seconds the "
                     "hero is OFF the ground. So this is 'how fast does one "
                     "ballistic arc complete', in flight-seconds — a property "
                     "of gravity and the jump impulse alone. Ungated, the "
                     "same numerator reads PARITY, because the drive script "
                     "presses A on a real-time cadence and the hero lands "
                     "once per press in both regions; that number measures "
                     "the harness, not the rail."),
            dict(name="fall_speed", kind="distance", unit="px/256 per air s",
                 mem="wram", fields=[("US_PYF", 0, 2, 65536)],
                 gate=("US_GROUNDED", 2, 0),
                 why="the hero\'s 8.8 vertical position — the integrator "
                     "output the sprite Y is derived from — accumulated over "
                     "airborne seconds. It is vertical speed in the units the "
                     "physics actually keeps, and the finest-grained progress "
                     "measure on this rail: 8.8 px, so a 1% difference is "
                     "hundreds of counts, not one."),
        ],
    ),

    # =================================================== fleet lane C =======
    # --- fleet lane C ---
    # The physics and streaming tail. Every entry below states the same two
    # things its neighbours above do: what GAME-VISIBLE progress the observable
    # is, and why that is a fair measure of it for this rail.
    #
    # A PHYSICS RAIL GETS A PER-ARC MEASURE, and it is gated. The registry's
    # own note above says why: a jump driven by a real-time input script lands
    # at the SCRIPT'S cadence in both regions, so "landings per second" reads
    # PARITY while the rail runs 17% slow. Gating the denominator on
    # "airborne" turns it into "arcs completed per second OF FLIGHT", which is
    # a property of gravity and the impulse alone. Every arc observable below
    # carries that gate.
    # ------------------------------------------------------------ PHYSICS
    "jumper": dict(
        rom="build/jumper.sfc", map="build/jr/symbol_map.json",
        scene="sky",
        klass="physics / jump",
        # RIGHT for one second with no A, then pace LEFT/RIGHT on a 0.2 s
        # half-period and tap A every 0.25 s.
        #
        # THE CORRIDOR IS CHOSEN, not incidental, and the lead-in is what
        # reaches it. This rail's 40.5 px apex can land on exactly ONE of its
        # three platforms -- plat1, row 22, cols 8..12 -- and can bonk the
        # overhang at cols 28..30; either would mix two arc lengths into one
        # number. The band BETWEEN them, x in [104, 215], is free of both,
        # 111 px wide, and the ground under it is unbroken. One second of
        # RIGHT puts the player at x = 168 at 120 px/s and x = 148 at the
        # uncompensated 100, and 0.2 s legs (24 px) keep the shuttle inside
        # [124, 192] from either -- with ~20 px of margin left over for the
        # turnaround PHASE drift, which is real: a 0.2 s leg is 12.02 NTSC
        # frames, so legs alternate 12 and 13 and the centre random-walks.
        # A narrow corridor turns that drift into frames PINNED against a
        # wall, which is lost distance the ratio then reports as a rate
        # difference. (Measured on the first draft, which used the 47 px
        # strip left of plat1: `run` read 0.842 against a frame ratio of
        # 0.832 with the halves 3% apart.)
        #
        # The A cadence is 0.25 s against a 0.6 s flight, so a fresh press
        # edge always arrives soon after a landing in BOTH regions -- and the
        # ground dwell it buys is outside the gated denominator, so it cannot
        # reach the ratio. There is no jump CUT on this rail (do_jump takes
        # off on the press edge and nothing clamps the rise), so a fixed
        # real-time hold flies the same full-height arc in both regions --
        # the trap `platformer` alternates A and B to dodge does not exist
        # here.
        script=([(0.0, {"right": True})]
                + _hop_shuttle(200, 250, 80, 20000, first="left", t0_ms=1000)),
        warmup_s=3.0, window_s=12.0, guard=[],
        observables=[
            dict(name="arc_rate", kind="edges", unit="arcs / airborne s",
                 mem="wram", fields=[("US_GROUNDED", 0, 2, 65536)],
                 gate=("US_GROUNDED", 2, 0),
                 why="0 -> non-0 on US_GROUNDED is the frame the player "
                     "TOUCHES DOWN (phys_step's landing snap and its standing "
                     "probe are the only writers of the 1), and the "
                     "denominator counts only the seconds it is OFF the "
                     "ground. So this is 'how fast does one ballistic arc "
                     "complete', in flight-seconds -- the r-and-r-squared "
                     "pair's whole subject, because an arc that keeps its "
                     "shape keeps this number."),
            dict(name="fall_speed", kind="distance", unit="px/256 per air s",
                 mem="wram", fields=[("US_PYF", 0, 2, 65536)],
                 gate=("US_GROUNDED", 2, 0),
                 why="the player's 8.8 world y -- the integrator output the "
                     "drawn sprite row is derived from (sky.asm refreshes "
                     "US_PYI from its high byte and jr_obj_draw stages that) "
                     "-- accumulated over airborne seconds. 8.8 px is the "
                     "finest-grained progress this rail has, so a 1% "
                     "difference is hundreds of counts rather than one."),
            dict(name="run", kind="distance", unit="world px",
                 mem="wram", fields=[("US_PX", 0, 2, 65536)],
                 why="the player's world x, which jr_obj_draw turns into the "
                     "OAM X the PPU draws from. World pixels per second is "
                     "the run rate a player perceives, and it is the OTHER "
                     "half of 'the same arc at the same speed' -- ungated on "
                     "purpose, because the run does not stop in the air."),
        ],
    ),
}


# ===========================================================================
# The worker: one region's pass
# ===========================================================================

def _sym(jmap, name, scene):
    pool = jmap["scenes"][scene]["placements"] if scene else jmap["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    if scene:                       # fall back to the global pool
        return _sym(jmap, name, None)
    raise KeyError(f"{name} is not in the emitted map — did the allocator "
                   f"move it, or is this rail not composing that feature?")


def _script_at(script, t):
    """The pad state at real time `t` seconds. Scripts are (seconds, pad)."""
    pad = {}
    for when, p in script:
        if t + 1e-9 >= when:
            pad = p
    return pad or None


def _unwrap(prev, cur, modulus):
    """The smallest-magnitude delta consistent with a value that wraps at
    `modulus`. Sampling EVERY frame is what makes this safe: no rail moves
    more than half a modulus in one frame."""
    d = (cur - prev) % modulus
    if d > modulus // 2:
        d -= modulus
    return d


def worker(args):
    import machine as M
    import mesen_runner as _mr
    from mesen_runner import MemoryType

    region = os.environ.get("SF_REGION", "auto")
    hz = MASTER_HZ.get(region)
    if hz is None:
        raise SystemExit("rate_oracle: SF_REGION must be ntsc or pal in a "
                         "worker; 'auto' cannot be timed because the rate "
                         "depends on the region Mesen picked.")

    rail = RAILS[args.rail]
    rom = args.rom or str(SUPERFORGE / rail["rom"])
    jmap = json.loads((SUPERFORGE / rail["map"]).read_text())

    # Resolve every observable's field to a (memory, address, width, modulus).
    plan = []
    for ob in rail["observables"]:
        addrs = []
        for sym, off, width, mod in ob["fields"]:
            p = _sym(jmap, sym, rail["scene"])
            if ob["mem"] == "oam":
                # ES_O_* claims are SPRITE SLOT indices; the OAM low table is
                # 4 bytes per sprite.
                base = p["start"] * 4
            else:
                base = p["start"]
            addrs.append((base + off, width, mod))
        plan.append((ob, addrs))

    def master_clock(lib):
        buf = (ctypes.c_uint8 * _mr._SNES_STATE_BUF_BYTES)()
        lib.GetConsoleState(ctypes.cast(buf, ctypes.c_void_p),
                            _mr._CONSOLE_TYPE_SNES)
        return int.from_bytes(bytes(buf)[0:8], "little")

    m = M.Machine(rom)
    lib = m._lib

    def read(addr, width, mem):
        mt = (MemoryType.SnesSpriteRam if mem == "oam"
              else MemoryType.SnesWorkRam)
        return int.from_bytes(m.read_bytes(mt, addr, width), "little")

    # --- the frame period, measured (this is also the liveness proof) -------
    # The first advance is taken BEFORE the clock is read: a Machine loads at
    # scanline 0 and parks at 224, so a reading spanning the load charges the
    # frame with the extra lines. (pal_probe.py's measured note, same trap.)
    m.advance(1)
    c0, f0 = master_clock(lib), m.ppu_frame_count()
    m.advance(19)
    mc_per_frame = (master_clock(lib) - c0) / (m.ppu_frame_count() - f0)

    warm, win = args.warmup or rail["warmup_s"], args.window or rail["window_s"]
    picture_at = sorted(float(x) for x in args.picture_at.split(",")) \
        if args.picture_at else []
    total_s = max(warm + win, max(picture_at) if picture_at else 0.0)

    # The guard: state that must HOLD for the window to mean anything (the
    # hero still alive, the rail not paused). A rail that dies mid-window
    # averages a live half with a frozen half and reports a ratio that is
    # about nothing; this makes that visible instead of silent.
    guards = [(g[0], _sym(jmap, g[0], rail["scene"])["start"], g[1], g[2])
              for g in rail.get("guard", [])]
    guard_break = None

    gates = [(_sym(jmap, ob["gate"][0], rail["scene"])["start"],
              ob["gate"][1], ob["gate"][2]) if ob.get("gate") else None
             for ob, _ in plan]

    c_start = master_clock(lib)
    prev = [[read(a, w, ob["mem"]) for a, w, _ in addrs] for ob, addrs in plan]
    # [numerator, denominator] per observable. The denominator is real
    # seconds, narrowed by the observable's gate when it declares one.
    acc = [[0.0, 0.0] for _ in plan]
    c_prev = c_start
    marks = []                      # (t, [acc...]) at warm, warm+win/2, end
    want = [warm, warm + win / 2.0, warm + win]
    shots = []

    t = 0.0
    while t < total_s:
        m.advance(1, pad1=_script_at(rail["script"], t))
        c_now = master_clock(lib)
        dt, t = (c_now - c_prev) / hz, (c_now - c_start) / hz
        c_prev = c_now
        for i, (ob, addrs) in enumerate(plan):
            cur = [read(a, w, ob["mem"]) for a, w, _ in addrs]
            d = [_unwrap(prev[i][j], cur[j], addrs[j][2])
                 for j in range(len(cur))]
            k = ob["kind"]
            if k == "distance":
                acc[i][0] += abs(d[0])
            elif k == "advance":
                acc[i][0] += d[0]
            elif k == "path2d":
                acc[i][0] += math.hypot(d[0], d[1])
            elif k == "transitions":
                acc[i][0] += 1 if cur[0] != prev[i][0] else 0
            elif k == "edges":
                acc[i][0] += 1 if (prev[i][0] == 0 and cur[0] != 0) else 0
            else:
                raise SystemExit(f"unknown observable kind {k!r}")
            g = gates[i]
            if g is None or read(g[0], g[1], "wram") == g[2]:
                acc[i][1] += dt
            prev[i] = cur
        if guard_break is None and t >= warm:
            for gname, gaddr, gw, gexp in guards:
                if read(gaddr, gw, "wram") != gexp and t <= warm + win:
                    guard_break = {"sym": gname, "t": t}
                    break
        while want and t >= want[0]:
            marks.append((t, [list(a) for a in acc]))
            want.pop(0)
        while picture_at and t >= picture_at[0] and args.outdir:
            png = (f"{args.outdir}/{Path(rom).stem}.{args.label or 'stock'}"
                   f".{region}.{picture_at[0]:g}s.png")
            m.take_screenshot(png)      # costs one frame, in both regions
            shots.append({"t": picture_at[0], "png": png})
            picture_at.pop(0)

    out = dict(rail=args.rail, region=region, rom=str(rom),
               rom_md5=m.rom_md5, label=args.label or "stock",
               mc_per_frame=mc_per_frame, master_hz=hz,
               fps=hz / mc_per_frame, warmup_s=warm, window_s=win,
               marks=[{"t": mt, "acc": ma} for mt, ma in marks],
               guard_break=guard_break,
               shots=shots,
               names=[ob["name"] for ob, _ in plan])
    m.close()
    print("SFRATE " + json.dumps(out))


# ===========================================================================
# The parent: two children, one ratio
# ===========================================================================

def _run_child(args, region):
    env = dict(os.environ, SF_REGION=region)
    argv = [sys.executable, __file__, args.rail, "--worker",
            "--warmup", str(args.warmup or 0), "--window", str(args.window or 0)]
    for flag, val in (("--rom", args.rom), ("--label", args.label),
                      ("--picture-at", args.picture_at),
                      ("--outdir", args.outdir)):
        if val:
            argv += [flag, str(val)]
    r = subprocess.run(argv, env=env, capture_output=True, text=True,
                       cwd=str(SUPERFORGE))
    line = next((ln for ln in r.stdout.splitlines()
                 if ln.startswith("SFRATE ")), None)
    if line is None:
        raise SystemExit(f"{region} pass failed:\n{r.stdout}\n{r.stderr}")
    return json.loads(line[len("SFRATE "):])


def _rates(rec):
    """(rate over the whole window, first-half rate, second-half rate) per
    observable. Every division uses the observable's own EXACT accumulated
    denominator — real seconds, or the gated subset of them — so there is no
    frame-quantisation term in either half of the fraction."""
    (t0, a0), (t1, a1), (t2, a2) = [(m["t"], m["acc"])
                                    for m in rec["marks"]]
    def r(x, y):
        return [(y[i][0] - x[i][0]) / (y[i][1] - x[i][1]) if y[i][1] > x[i][1]
                else float("nan") for i in range(len(x))]
    return r(a0, a2), r(a0, a1), r(a1, a2)


def _png_delta(pa, pb):
    from PIL import Image, ImageChops
    a, b = Image.open(pa).convert("RGB"), Image.open(pb).convert("RGB")
    if a.size != b.size:
        return f"SIZE {a.size} vs {b.size}"
    diff = ImageChops.difference(a, b)
    n = sum(1 for px in diff.getdata() if px != (0, 0, 0))
    return f"{n} px differ, bbox {diff.getbbox()}"


def report(rail, n, p, halves=False):
    rd = RAILS[rail]
    lines = []
    lines.append(f"{rail}  [{rd['klass']}]  {Path(n['rom']).name}"
                 f"  md5 {n['rom_md5']}  build={n['label']}")
    lines.append(f"  frame period   ntsc {n['mc_per_frame']:>9,.0f} mc"
                 f"  ({n['fps']:.4f} fps)"
                 f"   pal {p['mc_per_frame']:>9,.0f} mc"
                 f"  ({p['fps']:.4f} fps)")
    lines.append(f"  frame-rate ratio  pal/ntsc = "
                 f"{p['fps'] / n['fps']:.5f}"
                 f"   <- what an UNCOMPENSATED rail must beat")
    lines.append(f"  window         warm {n['warmup_s']:g} s, "
                 f"measure {n['window_s']:g} s of REAL time in each region")
    for tag, rec in (("ntsc", n), ("pal", p)):
        gb = rec.get("guard_break")
        if gb:
            lines.append(f"  !! GUARD BROKE on {tag}: {gb['sym']} left its "
                         f"expected value at t={gb['t']:.2f}s — the window "
                         f"spans a dead rail and its rate means nothing.")
    if not n.get("guard_break") and not p.get("guard_break"):
        gl = ", ".join(g[0] for g in rd.get("guard", []))
        lines.append(f"  guard          held in both regions"
                     + (f" ({gl})" if gl else " (none declared)"))
    fn, n1, n2 = _rates(n)
    fp, p1, p2 = _rates(p)
    lines.append("")
    lines.append(f"  {'observable':<14} {'unit':<14} {'NTSC/s':>12} "
                 f"{'PAL/s':>12} {'ratio':>9}  {'':<4}")
    out = []
    for i, ob in enumerate(rd["observables"]):
        ratio = fp[i] / fn[i] if fn[i] else float("nan")
        flag = "PARITY" if abs(ratio - 1.0) < 0.01 else \
               f"{(ratio - 1.0) * 100:+.1f}%"
        lines.append(f"  {ob['name']:<14} {ob['unit']:<14} {fn[i]:>12.3f} "
                     f"{fp[i]:>12.3f} {ratio:>9.5f}  {flag}")
        out.append(dict(name=ob["name"], unit=ob["unit"], kind=ob["kind"],
                        ntsc_per_s=fn[i], pal_per_s=fp[i], ratio=ratio))
        if halves:
            lines.append(f"  {'':<14} {'halves 1st/2nd':<14} "
                         f"{n1[i]:>12.3f} {n2[i]:>12.3f} "
                         f"{p1[i]:>9.3f} {p2[i]:>9.3f}   "
                         f"<- drive uniformity")
    if n["shots"] and p["shots"]:
        lines.append("")
        lines.append("  picture at equal REAL time (the player's question, "
                     "asked of rendered output):")
        for a, b in zip(n["shots"], p["shots"]):
            lines.append(f"    t = {a['t']:g}s   {_png_delta(a['png'], b['png'])}")
    return "\n".join(lines), out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rail", nargs="*", help="rail name(s); --list to see them")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--warmup", type=float, default=None,
                    help="real seconds discarded before the window opens")
    ap.add_argument("--window", type=float, default=None,
                    help="real seconds of measurement")
    ap.add_argument("--halves", action="store_true",
                    help="also print each half's rate (drive uniformity)")
    ap.add_argument("--rom", default=None,
                    help="override the rail's ROM (a flag build)")
    ap.add_argument("--label", default=None, help="name for the ROM variant")
    ap.add_argument("--picture-at", default=None,
                    help="comma-separated REAL seconds to capture at")
    ap.add_argument("--outdir", default=None, help="where captures go")
    ap.add_argument("--json", default=None, help="write the full record here")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.list:
        for k, v in RAILS.items():
            print(f"{k:<14} {v['klass']:<20} {v['rom']}")
            for ob in v["observables"]:
                print(f"    {ob['name']:<12} {ob['kind']:<12} {ob['unit']}")
        return 0

    if not args.rail:
        ap.error("name at least one rail (or --list)")
    if args.worker:
        args.rail = args.rail[0]
        args.warmup = args.warmup or None
        args.window = args.window or None
        return worker(args)
    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)

    records = []
    for name in args.rail:
        if name not in RAILS:
            raise SystemExit(f"unknown rail {name!r}; --list shows them")
        one = argparse.Namespace(**vars(args))
        one.rail = name
        n, p = _run_child(one, "ntsc"), _run_child(one, "pal")
        text, obs = report(name, n, p, halves=args.halves)
        print(text)
        print()
        records.append(dict(rail=name, ntsc=n, pal=p, observables=obs))

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(records, indent=2) + "\n")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
