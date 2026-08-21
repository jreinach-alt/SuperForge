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

A rail may also declare `script2`, driving PAD 2 on the same real-time
timeline. Only one rail in the set is two-player (`split_v_fight`), and it
needs the second pad for a reason the first cannot supply: its divider only
opens when the two fighters separate past SV_MERGE_DX, so a one-pad drive
leaves the mechanism the rail exists to show completely still.

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
# holds that value. `sym` may be a `(symbol, byte offset)` pair when the word
# lives inside a multi-field claim. A fourth element flips the test — `gate=(sym, width, 0,
# "ne")` counts the seconds in which the word is NOT that value, which is how
# a rail whose "airborne" is `height != 0` rather than a flag says so. It exists because of a measured trap, and the trap is
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
                 first="left", t0_ms=0, step_ms=25, button="a"):
    """A pad script that paces LEFT/RIGHT on a real-time half-period and taps
    JUMP on another, both written in REAL TIME so each region converts them
    with its own frame period and neither machine is handed more input than
    the other (the module header's load-bearing rule). Marks begin at
    `t0_ms`, so a caller can prepend a lead-in that walks the actor somewhere
    before the shuttle starts. Consecutive identical pad states are
    collapsed, so the returned list is the state CHANGES. `jump_hold_ms = 0`
    presses nothing, which is how a caller asks for a bare shuttle.

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
            pad[button] = True
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
        #  * `do_jump` (play.asm) launches on the PRESS EDGE of A-or-B and
        #    CUTS THE RISE when neither is held — a variable-height jump. A
        #    fixed real-time hold therefore buys 9 rise frames on NTSC and 7.5
        #    on PAL, so the two regions fly DIFFERENT ARCS and the ratio
        #    measures the cut, not the engine. Alternating the two face
        #    buttons keeps one of them held at all times (never cut) while
        #    still delivering a fresh press edge (always able to launch), so
        #    both regions fly the SAME full-height arc.
        #
        # THE ALTERNATION PERIOD IS LONGER THAN THE FLIGHT, and that is the
        # half that makes `arc_rate` readable. `edges` is an INTEGER count, so
        # over a 14 s window it sees ~16 arcs and one boundary arc is worth 6%
        # — far more than the 1% the scheme has to be adjudicated at. The bias
        # cancels in the RATIO only if both regions cut the window at the same
        # phase of the arc, and they do exactly when every press edge finds
        # the hero already grounded: then arcs start at the DRIVE's real-time
        # cadence rather than at "wherever the last landing happened to fall",
        # which is a different instant in each region. 0.9 s clears the
        # longest flight in play here (0.82 s: the UNCOMPENSATED PAL arc,
        # 41 frames at 50.007 fps) with margin, so every edge launches.
        # Measured on the 0.25 s draft: arc_rate 0.94545 with the NTSC halves
        # 1.409 / 1.582; the clean arcs underneath it were 41 frames NTSC and
        # 34 PAL, which is 1.0034, and the rest was the boundary.
        script=[(0.0, {}), (0.5, {"start": True}), (0.8, {})]
               + [(1.2 + 0.9 * k, {"a": True} if k % 2 == 0 else {"b": True})
                  for k in range(40)],
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
    "stomper": dict(
        rom="build/stomper.sfc", map="build/st/symbol_map.json",
        scene="play",
        klass="physics / jump",
        # `jumper`'s drive with the corridor moved. This rail's hazards are
        # its two ENEMIES (a contact knocks the player back to spawn, which
        # would restart every arc from a different place), the 16 px low wall
        # at col 20 (x 160..167) and the platform at cols 4..8. Everything
        # right of that wall is empty ground: enemy 1 paces 88..152 and
        # cannot cross it, enemy 2 is on the far-left platform, and nothing
        # overhangs. RIGHT-first 0.2 s legs from the x=200 spawn keep the run
        # inside [200, 224] -- 32 px clear of the wall, 16 px clear of the
        # right border -- and the guard below is what SAYS so rather than
        # this comment: `hurts` must stay 0 and enemy 1 must stay alive for
        # the window to mean anything.
        script=([(0.0, {})]
                + _hop_shuttle(200, 250, 80, 20000, first="right",
                               t0_ms=200)),
        warmup_s=3.0, window_s=12.0,
        guard=[("US_HURTS", 2, 0), ("US_E1ALIVE", 2, 1)],
        observables=[
            dict(name="arc_rate", kind="edges", unit="arcs / airborne s",
                 mem="wram", fields=[("US_GROUNDED", 0, 2, 65536)],
                 gate=("US_GROUNDED", 2, 0),
                 why="0 -> non-0 on US_GROUNDED is the frame the player "
                     "TOUCHES DOWN (phys_step's landing snap and its "
                     "standing probe are the only writers of the 1), over "
                     "the seconds it is OFF the ground. 'How fast does one "
                     "ballistic arc complete', in flight-seconds -- the "
                     "r-and-r-squared pair's whole subject."),
            dict(name="fall_speed", kind="distance", unit="px/256 per air s",
                 mem="wram", fields=[("US_PYF", 0, 2, 65536)],
                 gate=("US_GROUNDED", 2, 0),
                 why="the player's 8.8 world y -- the integrator output "
                     "US_PYI and therefore the drawn OAM row derive from -- "
                     "accumulated over airborne seconds. 8.8 px is the "
                     "finest-grained progress this rail has."),
            dict(name="run", kind="distance", unit="world px",
                 mem="wram", fields=[("US_PX", 0, 2, 65536)],
                 why="the player's world x, which st_obj_draw turns into the "
                     "OAM X the PPU draws from. World px per second is the "
                     "run rate a player perceives."),
            dict(name="patrol", kind="distance", unit="world px",
                 mem="wram", fields=[("US_E1X", 0, 2, 65536)],
                 why="enemy 1's world x, drawn from the same OAM staging as "
                     "the player. It is the rail's SECOND rate on a "
                     "different base (ST_PATROL_SPEED against ST_SPEED), and "
                     "it is measured because a shared accumulator would "
                     "couple the two silently -- so the pair being separate "
                     "is a claim, and this is the observable that checks "
                     "it. It never stops: the beat turns at the wall and at "
                     "the ledge and paces on."),
        ],
    ),
    # ------------------------------------------------------ 2-PLAYER FIGHT
    "split_v_fight": dict(
        rom="build/split_v_fight.sfc", map="build/sv/symbol_map.json",
        scene="fight",
        klass="physics / jump",
        # THE ONLY TWO-PAD DRIVE IN THE REGISTRY, and both halves earn their
        # place. Fighter 2 (pad 2) walks and NEVER jumps, because this rail's
        # walk is GROUND-ONLY ("a hop is a commitment") — a fighter that
        # jumps stops walking, so measuring the walk on an actor that also
        # jumps would fold the flight time into the walk rate and measure the
        # arc twice. Fighter 1 (pad 1) walks AND jumps, and it is the one
        # that jumps because the gate below can only name a SYMBOL, not an
        # offset inside it: `US_JMP` is a two-element pair claim and its base
        # is fighter 1's word.
        #
        # 0.5 s legs, mirrored: fighter 1 leaves its x=98 mark going LEFT and
        # fighter 2 leaves its x=158 mark going RIGHT. Both stay inside the
        # arena walls (24..232) with room to spare, which matters:
        # `clamp_fighter` PINS a fighter at the wall and a pinned frame is
        # lost distance the ratio would report as a rate difference.
        #
        # NEITHER PAD PRESSES A. No attack means no damage, no KO and no
        # round restart, so the phase clock stays in LIVE — which has no
        # timer — for the whole window, and the guard below is what says so.
        # The warm-up covers the opening count: SV_COUNT_LEN is 128 frames,
        # which is 2.13 s on NTSC and 2.56 s on PAL, and input is gated until
        # it expires.
        script=_hop_shuttle(500, 1200, 300, 20000, first="left",
                            button="b"),
        script2=_hop_shuttle(500, 1000, 0, 20000, first="right"),
        warmup_s=4.0, window_s=12.0,
        guard=[("US_RSTATE", 2, 1), ("US_HP", 2, 4)],
        observables=[
            dict(name="walk", kind="distance", unit="world px",
                 mem="wram", fields=[("US_FX2", 0, 2, 65536)],
                 why="fighter 2's world x, which split_v_obj turns into the "
                     "OAM X of the 32x32 knight against its own half's "
                     "camera. World px per second is the walk speed a player "
                     "perceives, and this fighter never leaves the ground so "
                     "the number is the walk rate and nothing else."),
            dict(name="anim", kind="transitions", unit="tile changes",
                 mem="oam", fields=[("ES_O_FIGHTER2", 2, 1, 256)],
                 why="fighter 2's OAM tile byte, read out of the sprite "
                     "table the PPU draws from — rendered output, not the "
                     "counter behind it. Counting the frames on which the "
                     "drawn tile CHANGES measures the walk cycle where a "
                     "player can actually see it, and it is the observable "
                     "that checks the CLOCK-not-divider answer to docs/95 "
                     "§5.2's class C: the sv_anim_meta rate is untouched and "
                     "only what the clock advances by is scaled."),
            dict(name="jump_path", kind="distance", unit="px/256 per s",
                 mem="wram", fields=[("US_JMP", 0, 2, 65536)],
                 gate=("US_JMP", 2, 0, "ne"),
                 why="fighter 1's jump HEIGHT in 8.8 px — the word "
                     "split_v_obj subtracts from the floor line to get the "
                     "drawn OAM y. Its path length per second is twice the "
                     "apex times the jumps per second, and the jumps per "
                     "second are the DRIVE's, identical in both regions. "
                     "GATED ON AIRBORNE, and the gate is the whole "
                     "difference between a measurement and a tautology: "
                     "ungated, the UNCOMPENSATED build reads 0.99989 — "
                     "PARITY — because the path per jump is a property of "
                     "the constants and the jumps per second are the drive's, "
                     "so the number says nothing at all while the rail runs "
                     "17% slow. Over airborne seconds it is twice the apex "
                     "divided by the flight time, which is exactly what the "
                     "r-and-r-squared pair claims to preserve. `jmp` is the "
                     "height, so airborne is `!= 0` rather than a flag."),
            # NO `divider` OBSERVABLE, and its absence is a MEASUREMENT
            # rather than an omission. SV_SPR_STEP — the ease that opens and
            # closes the BG3 divider — is scaled like every other rate here,
            # but this rail cannot be asked about it fairly, because the
            # divider only moves once the fighters separate past
            # SV_MERGE_DX and WHERE they are is not a rate.
            #
            # The opening count is SV_COUNT_LEN = 128 FRAMES and it stays an
            # integer (docs/95 §5.2's class B), so it runs 2.13 s on NTSC and
            # 2.56 s on PAL. Input is gated until it expires, so the two
            # regions start walking 0.43 s apart in the drive's phase and
            # stay there — there is no restoring force in a pure integration
            # to pull them back. Measured on this exact drive: NTSC reached
            # dx = 176 px and PAL only 116, so the divider opened to 16 px on
            # one machine and never left 0 on the other, and the observable
            # read 0.829 — the frame ratio, of the harness.
            #
            # That is the price of the countdown decision, stated with a
            # number. It costs the divider an oracle line; it does not cost
            # the ease its scale, which the three observables above prove
            # through the same TS_STEP publication.
        ],
    ),
    # ------------------------------------------- PHYSICS OVER A STREAMED WORLD
    "platformer_stream": dict(
        rom="build/platformer_stream.sfc", map="build/pfs/symbol_map.json",
        scene="play",
        klass="physics / streaming",
        # BOUNCE IN PLACE on the spawn column, and both halves of that are
        # measured rather than chosen. Three seconds of NO INPUT first: this
        # world is four screens tall and the hero falls about five of them
        # from spawn to bedrock, so the window has to open after the arrival
        # or it averages one long fall with fifteen hops.
        #
        # NO HORIZONTAL INPUT AT ALL, and that is the half that took two
        # drafts. The bedrock carries 8 px blocks, and a hero that walks
        # while it hops lands on a DIFFERENT one in each region — not because
        # the motion is wrong but because it is right to within a pixel and a
        # block edge is a knife edge. Measured on the shuttle draft: NTSC
        # flew 12 arcs of 35 frames and one of 24, PAL flew 10 of 29, two of
        # 28, one of 20 and TWO OF SIX, the short ones resting at y = 952
        # instead of 960 — one tile up, on a block. `arc_rate` is an integer
        # count over ~15 arcs, so two flipped landings are 13%, and the
        # observable reported 1.17 for a rail whose arcs match to 1%.
        # Standing still removes the sensitivity instead of averaging over
        # it. The horizontal rate is measured on this rail by the streaming
        # demand instead — the worst camera step per axis and the staged-line
        # histogram, both in the change report.
        #
        # A IS HELD FOR 0.7 s OF EVERY 0.9 s, not tapped. `pl_jump` CUTS the
        # rise on every frame A is not held, so a short real-time tap buys a
        # different number of rise frames in each region and the ratio would
        # measure the cut rather than the engine (the trap `platformer`
        # alternates two buttons to dodge; this rail has one jump button, so
        # the answer is to hold it past the 0.6 s flight). Released at 0.7 s
        # the hero is already descending, where the cut is a no-op.
        script=([(0.0, {})]
                + [(3.0 + 0.9 * k + (0.7 if odd else 0.0),
                    {} if odd else {"a": True})
                   for k in range(24) for odd in (0, 1)]),
        #
        # THE WINDOW IS ALIGNED TO THE DRIVE, and that is the third thing the
        # numbers forced. `arc_rate` is an integer `edges` count and 12 s
        # holds only ~13 arcs, so a window that opens or closes MID-FLIGHT
        # charges the numerator a whole landing for part of a flight — 2.6%
        # of the denominator, per end, differently in each region because the
        # flights are different lengths. warm 5.55 s and window 12.6 s (14
        # whole 0.9 s cycles) both fall in the GROUNDED gap between a landing
        # and the next launch on BOTH machines, so every arc inside is a
        # whole one. Measured on the unaligned 5.0/12.0 window: 1.068 with
        # the NTSC halves 1.806 / 1.502, for a rail whose arcs are 35 frames
        # NTSC and 29 PAL — which is 1.003.
        warmup_s=5.55, window_s=12.6, guard=[],
        observables=[
            dict(name="arc_rate", kind="edges", unit="arcs / airborne s",
                 mem="wram", fields=[("ES_PFS_PLAYER", 10, 2, 65536)],
                 gate=(("ES_PFS_PLAYER", 10), 2, 0),
                 why="0 -> non-0 on the player block's `grounded` word is the "
                     "frame the hero TOUCHES DOWN, over the seconds it is "
                     "OFF the ground. 'How fast does one ballistic arc "
                     "complete', in flight-seconds. The gate names the "
                     "SAME word at +10: grounded is 0 exactly while "
                     "airborne."),
            dict(name="fall_speed", kind="distance", unit="world px per air s",
                 mem="wram", fields=[("ES_PFS_PLAYER", 2, 2, 65536)],
                 gate=(("ES_PFS_PLAYER", 10), 2, 0),
                 why="the hero's world y — the 16-bit INTEGER half of the "
                     "16.8 split this rail keeps position in, and the word "
                     "`pl_camera` and `pl_draw` both read — accumulated over "
                     "airborne seconds. This world is four screens tall, so "
                     "the vertical axis is a real degree of freedom rather "
                     "than a decoration."),
        ],
    ),
    # ------------------------------------------------ THE VERTICAL WINDOW RIG
    "split_v_demo": dict(
        rom="build/split_v_demo.sfc", map="build/svd/symbol_map.json",
        scene="demo",
        klass="scrolling / 2-player",
        # THE ONE RIG IN THE SPLIT FAMILY THAT TAKES THE TIMEBASE, so it is
        # the one with an oracle line. Pad 1 holds RIGHT for camera A and
        # alternates the SHOULDERS on a 1 s period for the seam; pad 2 holds
        # LEFT for camera B. Three rates, three observables, one drive.
        #
        # Nothing clamps. The two cameras are masked to a byte — the stage map
        # is 256 px periodic, so a camera walked off either end WRAPS into the
        # world rather than pinning — and the seam starts centred at 128 with
        # 1 s legs of 60 px, inside its [64, 192] bounds with 4 px to spare.
        # A pinned frame is lost distance the ratio would report as a rate
        # difference, and this rail has two ways to pin.
        script=[(k, dict(right=True, **({"r": True} if k % 2 == 0
                                        else {"l": True})))
                for k in range(24)],
        script2=[(0.0, {"left": True})],
        warmup_s=2.0, window_s=12.0, guard=[],
        observables=[
            dict(name="cam_a", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_SVD_CAM", 0, 2, 256)],
                 why="camera A — the word `svd_bg`'s VBlank commit writes "
                     "BG1HOFS from, so it is the scroll the PPU renders the "
                     "LEFT half of the split with. World px per second here "
                     "IS the speed that half slides at. The modulus is 256, "
                     "not 65,536: the stage is 256 px periodic and the camera "
                     "is masked to a byte, so a 16-bit unwrap would read "
                     "every wrap as a 255 px jump."),
            dict(name="cam_b", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_SVD_CAM", 2, 2, 256)],
                 why="camera B, the RIGHT half's scroll, driven by the second "
                     "pad. It is measured beside camera A rather than assumed "
                     "to match it because the two cameras SHARE one "
                     "accumulator — the rail's claim is that they move "
                     "independently, and a shared pair that had coupled them "
                     "would show here."),
            dict(name="seam", kind="distance", unit="screen px",
                 mem="wram", fields=[("ES_SVD_CAM", 4, 2, 65536)],
                 why="the seam's screen x, which `svd_bg` turns into the "
                     "window edge registers every VBlank — the divider the "
                     "player is actually moving. It is the rail's SECOND "
                     "rate on a different base (one px a frame against the "
                     "cameras' two), so it carries its own accumulator and "
                     "this is the observable that checks the split."),
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

    def _gate(g):
        # The gate names a WORD, and a word inside a multi-field claim needs
        # an offset — `("ES_PFS_PLAYER", 10)` is "the grounded flag", not the
        # claim's first word. A bare string keeps meaning offset 0.
        who = g[0] if isinstance(g[0], tuple) else (g[0], 0)
        return (_sym(jmap, who[0], rail["scene"])["start"] + who[1],
                g[1], g[2], (g[3] if len(g) > 3 else "eq"))
    gates = [_gate(ob["gate"]) if ob.get("gate") else None for ob, _ in plan]

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
        m.advance(1, pad1=_script_at(rail["script"], t),
                  pad2=(_script_at(rail["script2"], t)
                        if rail.get("script2") else None))
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
            if g is None or ((read(g[0], g[1], "wram") == g[2])
                             == (g[3] == "eq")):
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
