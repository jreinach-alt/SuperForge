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


def _axis_shuttle(half_s, first, second, start_s=None, n=200, hold=None,
                  lead_s=0.0, tap=None, span_s=60.0):
    """A one-axis pad script that REVERSES on a fixed real-time half-period.

    Written in SECONDS like every script here, so each region converts it
    with its own frame period and neither machine is handed more input than
    the other. It exists because most rails CLAMP — a screen edge, a world
    edge, a maze wall — and an actor parked against a clamp reads zero
    progress, which measures the wall rather than the rail. Reversing before
    the wall keeps the axis moving for the whole window, and it costs
    nothing: `kind="distance"` sums |delta|, so a reversal is not a gap.

    `start_s` presses START once (a rail behind a title screen). `lead_s`
    holds `first` for that long before the shuttle begins, for a rail whose
    interesting band is not where it spawns. `hold` is a pad state held for
    the whole run on top of the alternating direction. `tap` is
    (button, period_s, hold_s) — a button pressed on its own real-time beat,
    for a rail whose action is EDGE-triggered and therefore cannot be driven
    by holding anything.

    THE PHASE IS CARRIED AS AN INDEX, NEVER RECOVERED FROM THE TIMESTAMP, and
    that is not a style preference — it is a measured bug. Deriving the
    direction as `int((t - t0) // half_s) % 2` reads the k-th boundary back as
    k-1 whenever the float sum lands a ulp low (t0 = 0.5 + 0.6 is
    1.0999999999999999, so the 0.7 s boundary divides to 0.999...), the
    reversal is silently skipped, and the actor walks into the clamp the
    shuttle exists to avoid. That showed up as `room` reading 83.7 px/s on
    NTSC where the same drive had read 120.198 before — a harness fault that
    looks exactly like a broken ROM.

    The three streams are merged onto ONE timeline rather than concatenated,
    because `_script_at` takes the last entry at or before t and each entry
    is a WHOLE pad state: an event that carried only the tap would silently
    release the direction.
    """
    hold = hold or {}
    t0 = (start_s + 0.6) if start_s is not None else 0.0

    # (time, direction-or-None, tap-on-or-None) events, each carrying the
    # phase it establishes. Merged by time, then folded forward so every
    # emitted pad state is complete.
    ev = []
    if start_s is not None:
        ev += [(0.0, "", None), (start_s, "start", None), (start_s + 0.3, "", None)]
    if lead_s > 0.0:
        ev.append((t0, first, None))
    for k in range(n):
        ev.append((t0 + lead_s + k * half_s,
                   first if k % 2 == 0 else second, None))
    if tap:
        b, per, hold_s = tap
        k = 0
        while k * per < span_s:
            ev.append((t0 + k * per, None, True))
            ev.append((t0 + k * per + hold_s, None, False))
            k += 1

    ev.sort(key=lambda e: e[0])
    out, cur_dir, cur_tap, booted = [], None, False, start_s is None
    for t, d, tp in ev:
        if d == "start":
            out.append((t, {"start": True}))
            continue
        if d == "":
            out.append((t, {}))
            continue
        if d is not None:
            cur_dir, booted = d, True
        if tp is not None:
            cur_tap = tp
        if not booted:
            continue
        pad = dict(hold)
        pad[cur_dir] = True
        if cur_tap and tap:
            pad[tap[0]] = True
        out.append((t, pad))
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
    # ======================================================================
    # --- fleet lane A ---
    # ======================================================================
    # Ten more rails — the walkers, the scrollers and the shooters. Every
    # entry below follows the four rules the registry above established, and
    # the two that cost the most to learn are worth restating here:
    #
    #  * THE OBSERVABLE IS GAME-VISIBLE PROGRESS, never a frame counter. A
    #    scroll word the PPU renders from, a world position the sprite is
    #    drawn at, an OAM byte read straight out of the table the PPU draws.
    #    Each one carries the sentence that says why it is fair for its rail.
    #  * THE DRIVE IS INDEXED ON SECONDS AND IT MUST NOT HIT A WALL. Most of
    #    these rails CLAMP (a screen edge, a world edge, a maze wall), and a
    #    clamped axis reads zero progress in whichever region reaches the
    #    clamp first — which is a measurement of the wall, not of the rail.
    #    `_axis_shuttle` reverses on a real-time half-period chosen so the
    #    actor stays inside its bounds in BOTH regions, and `kind="distance"`
    #    (sum of |delta|) is direction-blind, so reversing costs nothing.
    #    `--halves` is the check: a drive that touches a wall shows up as two
    #    halves that disagree.

    # ------------------------------------------------------------- SCROLL
    "camera_follow": dict(
        rom="build/camera_follow.sfc", map="build/cf/symbol_map.json",
        scene="world",
        klass="scrolling",
        # A horizontal shuttle inside the 512 px world. The player spawns at
        # the world centre (256) and CF_PLAYER_MAX_X is 504, so a 0.8 s
        # half-period (96 px at the NTSC rate) never reaches either clamp in
        # either region — measured: the halves agree to the printed digit.
        script=_axis_shuttle(0.8, "right", "left"),
        warmup_s=2.0, window_s=12.0, guard=[],
        observables=[
            dict(name="cam_x", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_CF_CAM", 0, 2, 65536)],
                 why="cf_bg's NMI commit writes BG1HOFS straight from this "
                     "word (cf_bg.asm:201). Mid-world the camera tracks the "
                     "player exactly, so world px/s here IS the speed the "
                     "picture slides at — and it is the rail's SUBJECT, "
                     "because the sprite holds screen centre while this "
                     "moves."),
            dict(name="player_x", kind="distance", unit="world px",
                 mem="wram", fields=[("US_PWX", 0, 2, 65536)],
                 why="the player's own world x, the word the camera is a "
                     "pure function of. It is the other half of the rail's "
                     "two-space split, and reading both says the scroll and "
                     "the actor move at one rate rather than two."),
        ],
    ),
    "scroll_run": dict(
        rom="build/scroll_run.sfc", map="build/sr/symbol_map.json",
        scene="run",
        klass="scrolling",
        # RUN RIGHT for two seconds first, THEN shuttle, and tap A on its own
        # beat. All three parts are load-bearing:
        #  * the camera CLAMPS at 0 until the runner passes SR_HALF_W = 128,
        #    and he spawns at x=16. A shuttle from the spawn therefore reads
        #    cam_x = 0 in both regions — a measurement of the clamp, not of
        #    the rail.
        #  * A is EDGE-triggered (do_jump), so a held A is one jump and then
        #    nothing; it has to be tapped.
        #  * THE TAPS ARE NOT OPTIONAL ON THIS RAIL. Measured: holding RIGHT
        #    from the spawn advances the runner to x = 104 and then STOPS —
        #    655 of 700 frames blocked against a wall he is meant to jump.
        #    The level is authored around the arc.
        #
        # THAT LAST FACT IS WHY THIS RAIL IS MEASURED AND NOT CONVERTED. Its
        # traversal rate is the run AND the arc together, and tick_scale's
        # single gain expresses r but not the gravity r^2 an arc needs, so
        # scaling the run alone stretches every jump a fifth further on PAL
        # and changes what the runner can clear. The numbers are in the
        # ledger: uncompensated cam_x reads 0.86321, and a run-only
        # conversion read 0.97471 with PAL halves of 105.7 and 120.2 — the
        # drive itself goes non-uniform, because the fraction of the window
        # the runner spends blocked or airborne stops being the same in the
        # two regions.
        script=_axis_shuttle(0.6, "right", "left", lead_s=2.0,
                             tap=("a", 0.9, 0.2)),
        warmup_s=3.0, window_s=12.0, guard=[],
        observables=[
            dict(name="cam_x", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_SR_CAM", 0, 2, 65536)],
                 why="sr_bg's VBlank commit writes BG1HOFS from this word "
                     "(sr_bg.asm's srb_nmi_commit). It is the scroll the PPU "
                     "renders with, so world px/s is the speed the level "
                     "slides past."),
            dict(name="run_x", kind="distance", unit="world px",
                 mem="wram", fields=[("US_PX", 0, 2, 65536)],
                 why="the runner's world x — what the camera follows and "
                     "what the level's geometry is authored against."),
            dict(name="fall_y", kind="distance", unit="px/256",
                 mem="wram", fields=[("US_PYF", 0, 2, 65536)],
                 why="the runner's 8.8 vertical position, the integrator "
                     "output the sprite Y is derived from — the arc itself, "
                     "in the units the physics keeps. On this rail it is not "
                     "a control but the SUBJECT: the level cannot be crossed "
                     "without it, which is what puts scroll_run out of "
                     "tick_scale's reach."),
        ],
    ),
    # ------------------------------------------------------------- WALKERS
    "maze": dict(
        rom="build/maze.sfc", map="build/maze/symbol_map.json",
        scene="room",
        klass="walking",
        # A VERTICAL shuttle in the open left chamber. Horizontal is the
        # wrong axis here: interior wall A stands 48 px right of the spawn,
        # and a drive that walks into it measures the wall. The chamber runs
        # from y=8 to y=208 at the spawn column, and the spawn is y=100, so a
        # 0.5 s half-period (60 px at the NTSC rate) stays clear of both.
        script=_axis_shuttle(0.5, "down", "up"),
        warmup_s=2.0, window_s=12.0, guard=[],
        observables=[
            dict(name="player_oam_y", kind="distance", unit="OAM px",
                 mem="oam", fields=[("ES_O_PLAYER", 1, 1, 256)],
                 why="byte 1 of the player's OAM entry is the Y the PPU "
                     "draws the sprite at — rendered output, not the word "
                     "behind it. The room is one screen with scroll pinned "
                     "(maze_bg), so OAM px/s IS the walking speed a player "
                     "sees."),
            dict(name="player_y", kind="distance", unit="world px",
                 mem="wram", fields=[("US_PY", 0, 2, 65536)],
                 why="the game's own y, the word the per-axis move-check "
                     "commits only when col_map says the 8x8 box is clear. "
                     "Reading it beside the OAM byte says the collision "
                     "gate, not just the draw, runs at the measured rate."),
        ],
    ),
    "sprite_game": dict(
        rom="build/sprite_game.sfc", map="build/sprg/symbol_map.json",
        scene="play",
        klass="walking",
        # Hold RIGHT for the whole run. This rail has NO CLAMP at all — the
        # player wraps as an unsigned 16-bit word and sprg_obj re-derives X9
        # every frame — so there is no wall to shuttle away from and the
        # simplest drive is also the most uniform one.
        script=[(0.0, {"right": True})],
        warmup_s=2.0, window_s=12.0, guard=[],
        observables=[
            dict(name="player_oam_x", kind="distance", unit="OAM px",
                 mem="oam", fields=[("ES_O_PLAYER", 0, 1, 256)],
                 why="byte 0 of the player's OAM entry — the X the PPU draws "
                     "him at, taken out of the sprite table itself. The "
                     "modulus is 256 because that is what the byte holds; "
                     "the 2 px step makes the unwrap unambiguous."),
            dict(name="player_x", kind="distance", unit="world px",
                 mem="wram", fields=[("US_PX", 0, 2, 65536)],
                 why="the game's own x, which sprg_obj turns into that OAM "
                     "byte plus its X9 bit. It is the full-width word, so it "
                     "sees the wrap the byte cannot."),
        ],
    ),
    "hud_game": dict(
        rom="build/hud_game.sfc", map="build/hud/symbol_map.json",
        scene="play",
        klass="walking",
        # A horizontal shuttle. The player spawns at screen centre (124) and
        # is clamped to [0, 248]; a 0.7 s half-period is 84 px at the NTSC
        # rate, so he swings between roughly 124 and 208 and never parks.
        script=_axis_shuttle(0.7, "right", "left"),
        warmup_s=2.0, window_s=12.0, guard=[],
        observables=[
            dict(name="player_oam_x", kind="distance", unit="OAM px",
                 mem="oam", fields=[("ES_O_PLAYER", 0, 1, 256)],
                 why="byte 0 of the player's OAM entry — the X the PPU draws "
                     "him at. This rail's picture is a sprite over a static "
                     "text line, so the sprite's motion is the whole of the "
                     "visible progress."),
            dict(name="player_x", kind="distance", unit="screen px",
                 mem="wram", fields=[("US_PX", 0, 2, 65536)],
                 why="the game's own x, clamped to the screen by the tick. "
                     "It is what hud_obj_place turns into the OAM byte."),
        ],
    ),
    "patrol": dict(
        rom="build/patrol.sfc", map="build/pat/symbol_map.json",
        scene="play",
        klass="walking",
        # A horizontal shuttle on the ground floor. The player spawns at
        # x=200 and the run is a per-axis move-check against col_map, so a
        # half-period that reaches a wall would measure the wall: 0.5 s is
        # 60 px at the NTSC rate, which stays on open floor.
        # NO JUMP IN THIS DRIVE, and that was measured rather than chosen.
        # Tapping A every 1.2 s to exercise the arc made the HORIZONTAL
        # numbers meaningless: the hero's vertical position decides which
        # frames he touches a patrolling enemy, `do_contact` KNOCKS HIM BACK
        # to the spawn, and a teleport is a large |delta| that `distance`
        # cannot tell from walking. player_x went from a flat 1.00128 to
        # 1.02211 with a PAL first half of 125.2 px/s — faster than the
        # engine can walk, which is the teleport showing through. The guard
        # below is the standing check on that: a window that contains a
        # knockback is a window whose distance is about the knockback.
        script=_axis_shuttle(0.5, "left", "right"),
        warmup_s=2.0, window_s=12.0, guard=[("US_HITS", 2, 0)],
        observables=[
            dict(name="player_x", kind="distance", unit="world px",
                 mem="wram", fields=[("US_PX", 0, 2, 65536)],
                 why="the player's x, committed only when pat_solid_box "
                     "says the 8x8 box at the tentative position is clear. "
                     "The room is one screen with scroll pinned, so this is "
                     "also the screen px the sprite is drawn at."),
            dict(name="e1_x", kind="distance", unit="world px",
                 mem="wram", fields=[("US_E1X", 0, 2, 65536)],
                 why="the ground enemy's x. It is driven by the rail's OTHER "
                     "rate (PAT_PATROL_SPEED, half the player's) and by no "
                     "input at all — a beat that walks itself, so it is the "
                     "one observable here that no drive script can pace."),
        ],
    ),
    "room": dict(
        rom="build/room.sfc", map="build/rm/symbol_map.json",
        scene="room",
        klass="walking",
        # START clears the title, then a horizontal shuttle. room_logic
        # CLAMPS the hero to [8, 232]; he spawns at 120, and a 0.7 s
        # half-period is 84 px at the NTSC rate, so he swings between roughly
        # 120 and 204 without ever parking against a wall.
        script=_axis_shuttle(0.7, "right", "left", start_s=0.5),
        warmup_s=3.0, window_s=12.0, guard=[],
        observables=[
            dict(name="hero_oam_x", kind="distance", unit="OAM px",
                 mem="oam", fields=[("ES_O_HERO", 0, 1, 256)],
                 why="byte 0 of the lantern-bearer's OAM entry — the X the "
                     "PPU draws him at. The room is one screen and does not "
                     "scroll, so his OAM px/s IS the walking speed."),
            dict(name="hero_x", kind="distance", unit="screen px",
                 mem="wram", fields=[("US_PX", 0, 2, 65536)],
                 why="the hero's own x. The window_iris lantern is centred "
                     "on it every frame, so this word is also the rate the "
                     "LIGHT moves across the room — the rail's subject."),
        ],
    ),
    # ------------------------------------------------------------- SHOOTERS
    "shmup": dict(
        rom="build/shmup.sfc", map="build/sh/symbol_map.json",
        scene="play",
        klass="shooting",
        # START clears the title, then a horizontal shuttle with A TAPPED on
        # its own beat. Both details were forced by measurement:
        #  * `shm_fire` reads ES_INP_PRESS, so a HELD A fires exactly ONE
        #    bullet and then nothing. With the guns silent the fighters reach
        #    the ship inside 7 s and the guard fires. Tapping every 0.15 s
        #    keeps the bullet pool busy.
        #  * SHIP_MIN_X/MAX_X are 8 and 224 and the ship spawns at 120; a
        #    0.6 s half-period is 72 px at the NTSC rate, which keeps it off
        #    both clamps.
        #
        # THE WINDOW IS 3 s BECAUSE THE SHIP CANNOT BE KEPT ALIVE LONGER, and
        # that is a property of the rail rather than of the drive. There is no
        # safe place to stand: the eight spawn columns
        # (24/40/64/88/120/168/200/216) and the CLOSED 16 px overlap test
        # leave exactly one safe band, x in [137, 151], and no clamp lands
        # there — so no open-loop script can park in it at the same x in both
        # regions. Nor is there a safe row: a fighter spawns at y=24 and is
        # culled at y=208, and the ship's own [32, 200] lies inside that.
        # Measured with this drive, the first hit lands at ~6.5 s on the PAL
        # arm. Warm 3 s + window 3 s therefore closes before it in all four
        # arms (the NTSC arms take no hit at all in 20 s).
        #
        # THE COST IS ship_tile's RESOLUTION, stated rather than hidden: it is
        # an EVENT counter at ~10 Hz, so 3 s is ~30 events and one event is
        # 3.3%. `--warmup 3 --window 12` reads it to 0.01% and trades the
        # guard for it; both runs belong in a report of this rail.
        script=_axis_shuttle(0.6, "right", "left", start_s=0.5,
                             tap=("a", 0.15, 0.1)),
        warmup_s=3.0, window_s=3.0,
        guard=[("US_GOVER", 2, 0), ("US_LIVES", 2, 3)],
        observables=[
            dict(name="field_scroll", kind="distance", unit="BG px",
                 mem="wram", fields=[("ES_SHM_SCROLL", 0, 2, 256)],
                 why="shmup_bg's shadow of BG1VOFS, committed to the PPU "
                     "every VBlank (shmup_bg.asm's shm_vblank_scroll). The "
                     "planet field IS the sense of flying, so BG px per "
                     "second is the speed the world comes at the player. "
                     "The modulus is the map's own 256 px height, which is "
                     "what shm_drift masks to."),
            dict(name="ship_oam_x", kind="distance", unit="OAM px",
                 mem="oam", fields=[("ES_O_SHIP", 0, 1, 256)],
                 why="byte 0 of the ship's OAM entry — where the PPU draws "
                     "it. The playfield does not scroll horizontally, so "
                     "this is the ship's speed as the player sees it."),
            dict(name="ship_tile", kind="transitions", unit="tile changes",
                 mem="oam", fields=[("ES_O_SHIP", 2, 1, 256)],
                 why="the ship's OAM tile byte, read out of the sprite table "
                     "the PPU draws from — rendered output, not the counter "
                     "behind it. It is the engine-plume ANIMATION CLOCK, "
                     "which docs/95 §5.2 puts in class C (a small-integer "
                     "divider with no correct x5/6). Counting the frames on "
                     "which the drawn tile CHANGES measures the flicker "
                     "where a player perceives it, and it is the one "
                     "observable here that no drive script can pace."),
        ],
    ),
    "breaker": dict(
        rom="build/breaker.sfc", map="build/bk/symbol_map.json",
        scene="play",
        klass="shooting",
        # START clears the title, A launches the ball off the bat, and the bat
        # shuttles on a 0.5 s half-period (90 px at the NTSC rate, inside its
        # [8, 224] clamp).
        #
        # THE WINDOW IS SHORT ON PURPOSE, AND THIS IS THE ONE ENTRY IN THE
        # REGISTRY WHERE THAT IS TRUE. A billiard cannot be kept alive by an
        # open-loop script: the ball leaves the bat, bounces, and comes down
        # somewhere the bat is not. Measured both ways — bat shuttling and
        # bat parked — each ball lives ~1.95 s and the round is over at
        # ~7.3 s.
        #
        # THE WINDOW IS PLACED FROM THE MEASURED TIMES IN ALL FOUR ARMS
        # (before/after x ntsc/pal), because they are not the same. The ball
        # LAUNCHES at 1.11 s on NTSC and 1.26 s on PAL — the title fade is
        # counted in frames, so it takes longer in real time there — and the
        # first ball is LOST at 3.06 s on both NTSC arms, 3.20 s on PAL after
        # and 3.60 s on PAL before. Warm 1.35 s + window 1.60 s closes at
        # 2.95 s, inside every one of those, so the numerator never contains
        # a relaunch teleport — which a gate on the DENOMINATOR could not
        # have removed.
        #
        # THOSE SAME TIMES ARE THEMSELVES A MEASUREMENT, and a cleaner one
        # than the path integral: the first ball's FLIGHT lasts 1.95 s on
        # NTSC, 2.34 s on PAL uncompensated (a ratio of 0.83) and 1.94 s on
        # PAL compensated (0.995). No drive script paces that at all.
        script=_axis_shuttle(0.5, "right", "left", start_s=0.5,
                             tap=("a", 0.15, 0.1)),
        warmup_s=1.35, window_s=1.6,
        guard=[("US_GSTATE", 2, 1)],
        observables=[
            dict(name="paddle_oam_x", kind="distance", unit="OAM px",
                 mem="oam", fields=[("ES_O_PADDLE", 0, 1, 256)],
                 why="byte 0 of the bat's leftmost OAM entry — where the PPU "
                     "draws it. The arena does not scroll, so OAM px/s is "
                     "the bat's speed exactly as the player feels it under "
                     "the d-pad."),
            dict(name="ball_path", kind="path2d", unit="screen px",
                 mem="wram",
                 fields=[("US_BX", 0, 2, 65536), ("US_BY", 0, 2, 65536)],
                 why="the ball's 2-D path length. The ball is the only "
                     "actor here that NO drive script can pace — it is a "
                     "billiard integrating its own velocity — so its "
                     "distance per real second is the purest progress "
                     "measure on the rail. The guard requires the round to "
                     "still be live, because a ball sitting on the bat in "
                     "WAIT contributes zero to the numerator and real "
                     "seconds to the denominator."),
        ],
    ),
    # --------------------------------------------------------------- MODE 7
    "rpg": dict(
        rom="build/rpg.sfc", map="build/rpg/symbol_map.json",
        scene="overworld",
        klass="mode7",
        # A VERTICAL shuttle. The overworld is a 1024 px TORUS with no clamp
        # anywhere, but it has TERRAIN: a press into a blocked tile is
        # rejected outright, and the spawn is walled to the EAST — measured,
        # holding RIGHT for 120 frames moves the camera zero pixels while
        # DOWN moves it 106. The north/south axis is open at the spawn in
        # both directions, and a 1.0 s half-period keeps the walk inside the
        # ground that was probed.
        #
        # THIS RAIL IS MEASURED AND NOT CONVERTED, and the reading is what
        # says why. 53.43 px/s at 60.0988 fps is 8 px every 9 frames, which
        # is the GRID SLIDE exactly: `try_step` commits the destination TILE
        # (RPG_CAM_TX/TY) up front and arms RPG_STEP_N = STEP_FRAMES = 8,
        # and `advance_step` then adds +-1 px to ES_M7ORG and decrements that
        # counter once a frame, so 8 frames of 1 px land the camera origin on
        # the tile the index already says it is at. The two are WELDED: scale
        # the pixel delta and after 8 frames the origin is 9.6 px along while
        # the index says 8, and the floor and the avatar drift apart a little
        # more on every step. This is docs/95 §5.1 #11's hard-integer class
        # verbatim.
        # The other way round — counting the slide in PIXELS REMAINING rather
        # than frames — works arithmetically and re-defines RPG_STEP_N, which
        # is a byte inside `rpg_logic`'s declared 18-byte `rpg_hot` claim
        # whose layout that feature.toml documents, beside RPG_TOWN_REP.
        # That is surgery on a feature's declared claim, not a rate expressed
        # through TS_STEP.
        # The TOWN has no rate to express at all: its avatar renders only at
        # tile*8 (town.asm's read_step says so in as many words — "NOT a
        # per-frame pixel slide, because the town avatar renders only at
        # tile*8 and has no sub-tile pixel state a slide could drive"), so
        # its walk IS an integer frame throttle and 8/1.2018 = 6.66 has no
        # correct answer.
        script=_axis_shuttle(1.0, "down", "up"),
        warmup_s=3.0, window_s=12.0, guard=[],
        observables=[
            dict(name="m7_path", kind="path2d", unit="world px",
                 mem="wram",
                 fields=[("ES_M7ORG", 0, 2, 1024), ("ES_M7ORG", 2, 2, 1024)],
                 why="ES_M7ORG +0/+2 are the Mode 7 camera's world x/y, "
                     "committed to the PPU by mode7_persp's NMI hook every "
                     "VBlank. The floor is drawn FROM this point, so the "
                     "path it traces is the ground the player covers. The "
                     "modulus is the 128x128-tile world's 1,024 px torus, "
                     "not 65,536 — a 16-bit unwrap would read the world "
                     "wrap as a 1,016 px jump."),
        ],
    ),
    # --- fleet lane B ---------------------------------------------------
    # The Mode 7 and camera rails. Every observable below is a word the PPU is
    # DRIVEN FROM — a Mode 7 camera origin the floor is drawn out of, or an OAM
    # byte the sprite table hands the PPU — never a frame counter and never a
    # counter that only feeds one. Where a rail can die, stall or change scene
    # inside the window, a `guard` says so: a window that spans a dead rail
    # averages a live half with a frozen half and reports a ratio about
    # nothing.
    "mode7_explore": dict(
        rom="build/mode7_explore.sfc", map="build/m7x/symbol_map.json",
        scene="overworld",
        klass="mode7",
        # RIGHT and DOWN together, and both halves earn their place. The
        # dispatch priority is LEFT, RIGHT, UP, DOWN with a FALL-THROUGH on a
        # blocked axis, so holding two open directions keeps her walking when
        # one is refused by water or mountain — a single held axis measures the
        # terrain as much as the rail. And both lead AWAY from the one
        # enterable house: the spawn is tile (258,258) and the door is
        # (254,254), so a rightward, downward walk cannot trip the scene swap
        # and strand the window in an interior that does not move this camera.
        script=[(0.0, {"right": True, "down": True})],
        warmup_s=2.0, window_s=12.0, guard=[],
        observables=[
            dict(name="cam_path", kind="path2d", unit="world px",
                 mem="wram",
                 fields=[("ES_M7ORG", 0, 2, 4096), ("ES_M7ORG", 2, 2, 4096)],
                 why="ES_M7ORG +0/+2 is the camera mxl_apply_camera publishes "
                     "(m7x_logic.asm:328) — the word `mode7_stream` reads to "
                     "decide which world rows enter VRAM, and the same "
                     "position m7a_set_center turns into the affine pivot. "
                     "The floor is drawn FROM it, so the path length it traces "
                     "is the ground she covers. The modulus is the authored "
                     "world's 4,096 px (M7X_WORLD_PX); the clamp keeps the "
                     "camera at 512..3,576 so it never reaches one."),
        ],
    ),
    "mode7_flight": dict(
        rom="build/mode7_flight.sfc", map="build/m7f/symbol_map.json",
        scene="sky",
        klass="mode7",
        # B and LEFT: the throttle ramps to its cap and holds there while the
        # heading turns, so the airship flies a constant-radius circle over the
        # plane. Nothing on this rail can die — the altitude clamps at both
        # ends and there is no fail state — so no guard is declared.
        # THE WINDOW IS 30 s BECAUSE ONE OBSERVABLE IS AN EVENT COUNT. `prop`
        # changes about 7.5 times a second, so a 14 s window holds ~106 events
        # and ONE event is 0.94% — the whole tolerance. Thirty seconds is ~225,
        # where a single boundary event is 0.44%.
        script=[(0.0, {"b": True, "left": True})],
        warmup_s=3.0, window_s=30.0, guard=[],
        observables=[
            dict(name="cam_path", kind="path2d", unit="px/65536",
                 mem="wram",
                 fields=[("ES_M7F_POSE", 0, 4, 1024 << 16),
                         ("ES_M7F_POSE", 4, 4, 1024 << 16)],
                 why="M7F_POSX / M7F_POSY, the camera's 16.16 world position "
                     "(m7f_cam.asm:135). m7f_origin derives M7X/M7Y and the "
                     "screen origin from it and the NMI commits those to the "
                     "PPU every VBlank, so the Mode 7 floor is drawn out of "
                     "this pair — the path it traces is the ground flown "
                     "over. Read WHOLE at 16.16 rather than at the integer "
                     "half, because summing hypot() over integer deltas "
                     "charges the two regions different rounding. The modulus "
                     "is the plane's own period, M7F_WRAP + 1 = 1,024 px, "
                     "scaled into 16.16: m7f_apply_step masks the integer word "
                     "to exactly that."),
            dict(name="prop", kind="transitions", unit="tile changes",
                 mem="oam", fields=[("ES_O_SHIP", 2, 1, 256)],
                 why="the airship's OAM TILE byte, read out of the sprite "
                     "table the PPU draws from — rendered output, not the "
                     "counter behind it. obj_draw picks M7F_SHIP_TILE_A or _B "
                     "from US_PROP_F (m7f_obj.asm:257), so counting the frames "
                     "on which the drawn tile CHANGES measures the propeller "
                     "in the only place a viewer can perceive it. This is the "
                     "observable that adjudicates the animation DIVIDER: "
                     "M7F_PROP_RATE stays the 8 it was authored at and what "
                     "moves is how fast the clock walks toward it."),
            dict(name="daynight", kind="transitions", unit="palette steps",
                 mem="wram", fields=[("ES_M7F_CLOCK", 2, 2, 65536)],
                 why="M7F_TODROW — the day/night palette ROW tod_commit last "
                     "wrote (m7f_floor.asm:62). It changes only on the frame "
                     "the routine actually re-uploads sixteen CGRAM words, so "
                     "counting its changes counts SUNSETS ARRIVING, not a "
                     "phase accumulating. It is the observable the day/night "
                     "judgment is answerable to: the full cycle is 64 of these "
                     "steps, 34 s on NTSC."),
        ],
    ),
    "boss": dict(
        rom="build/boss.sfc", map="build/bs/symbol_map.json",
        scene="arena",
        klass="mode7",
        # A SHUTTLE ON THE STRAFE, AND NO FIRE BUTTON. Holding a direction
        # parks the ship against its clamp at 8 or 232 and the position measure
        # goes to zero; alternating every 0.4 s keeps it moving across the
        # whole span. A is deliberately absent: a held A kills the boss in
        # about six seconds (240 HP at 5 a bolt, one bolt per eight frames) and
        # the window would then span the death track and the result hold.
        #
        # The warmup clears the 60-frame reveal and the 45-frame hold, so the
        # window opens inside FIGHT — which is what the guard then requires. It
        # covers BOTH ways this rail can leave: the boss dying takes the state
        # to DEATH and the player dying takes it to LOSE.
        script=[(0.0, {})]
               + [(2.0 + 0.4 * k, {"left": True} if k % 2 == 0
                  else {"right": True}) for k in range(40)],
        # MEASURED: with this drive the player takes his third rain hit at
        # t = 7.0 s, so the window closes at 6.2 and the guard is what says
        # whether that held on the day.
        warmup_s=2.2, window_s=4.0, guard=[("US_B_STATE", 2, 3)],
        observables=[
            dict(name="spin", kind="distance", unit="heading units",
                 mem="wram", fields=[("US_B_HEADING", 0, 1, 256)],
                 why="the boss's ring heading. `su_fight` indexes bs_ring_bin "
                     "with it and m7t_apply writes the result into the Mode 7 "
                     "matrix shadow the NMI commits, so the WHOLE BOSS rotates "
                     "by it — heading units per second is the rate the thing "
                     "on screen turns. It is also the observable the phase "
                     "schedule moves (+1, +2 or +3 by HP third), which is why "
                     "its base is not a build-time constant and the rail "
                     "scales the state STEP instead."),
            dict(name="player_x", kind="distance", unit="screen px",
                 mem="oam", fields=[("ES_O_PLAYER", 0, 1, 256)],
                 why="the player ship's OAM X byte, read out of the sprite "
                     "table the PPU draws from — rendered output, not US_P_X "
                     "behind it. Screen pixels per second here is the strafe "
                     "speed, which is the one rate on this rail the player "
                     "commands directly."),
        ],
    ),
    "boss_saucer": dict(
        rom="build/boss_saucer.sfc", map="build/sau/symbol_map.json",
        scene="arena",
        klass="mode7",
        # Same drive as `boss` and for the same two reasons: a held direction
        # parks the ship against its clamp, and a held A kills the saucer
        # inside the window. The warmup clears the reveal and the hold; the
        # guard requires FIGHT and covers both ways this rail can leave it.
        script=[(0.0, {})]
               + [(2.0 + 0.4 * k, {"left": True} if k % 2 == 0
                  else {"right": True}) for k in range(40)],
        warmup_s=2.2, window_s=4.0, guard=[("US_B_STATE", 2, 3)],
        observables=[
            dict(name="star_near", kind="distance", unit="scroll units",
                 mem="wram", fields=[("US_STAR_NEAR", 0, 2, 65536)],
                 why="the near star band's scroll. `stars_update` advances it "
                     "at a rate read off the fight's own PHASE and draw_frame "
                     "turns it into the star sprites' OAM positions, so this "
                     "is the sky sliding behind the fight — and it is the one "
                     "observable that keeps moving whatever the player does."),
            dict(name="player_x", kind="distance", unit="screen px",
                 mem="oam", fields=[("ES_O_PLAYER", 0, 1, 256)],
                 why="the player ship's OAM X byte, read out of the sprite "
                     "table the PPU draws from — rendered output, not the "
                     "variable behind it. Screen pixels per second here is the "
                     "strafe, the one rate the player commands directly."),
        ],
    ),
    "meteor_event": dict(
        rom="build/meteor_event.sfc", map="build/met/symbol_map.json",
        scene=None,
        klass="mode7",
        # HOLD RIGHT FROM BOOT, AND LET THE WHOLE EVENT RUN INSIDE THE WINDOW.
        # This rail is a Mode 1 walk that trips a Mode 7 cutscene and hands
        # back, so a window narrow enough to sit in one phase would measure one
        # third of it. Twelve seconds covers the walk to the trigger at world x
        # 240, the freeze, the capture, the 180-tick cutscene and the walk that
        # resumes after — and both observables below are GLOBAL claims, so they
        # survive the scene swap that happens in the middle of it.
        #
        # `scene=None` for the same reason: the two observables are in the
        # GLOBAL pool, and the window spans both scenes.
        script=[(0.0, {"right": True})],
        warmup_s=0.5, window_s=12.0, guard=[],
        observables=[
            dict(name="cam", kind="distance", unit="world px",
                 mem="wram", fields=[("US_G_CAMX", 0, 2, 65536)],
                 why="the camera `camera_commit` publishes — the scroll the "
                     "Mode 1 layer is drawn at, and the player's screen x is "
                     "FIXED, so this word is the whole of what moves on "
                     "screen during the walk. It stands still through the "
                     "freeze and the cutscene by design, which is why the "
                     "window has to span all three phases for the number to "
                     "mean the rail rather than one phase of it."),
            dict(name="meteor_y", kind="distance", unit="px / cutscene s",
                 mem="oam", fields=[("ES_O_METEOR", 1, 1, 256)],
                 gate=("US_G_STATE", 2, 3),
                 why="the meteor's OAM Y byte, read out of the sprite table "
                     "the PPU draws from. Its whole approach is the BAKED "
                     "per-frame track US_G_TIMER indexes, so screen pixels "
                     "per second here is exactly the rate that playhead "
                     "walks.\n"
                     "  THE GATE IS NOT OPTIONAL and the registry header says "
                     "why: the numerator is BOUNDED — the track is a fixed "
                     "path and the whole of it runs inside a 12 s window in "
                     "both regions — so ungated this reads 0.99989 on the "
                     "UNCOMPENSATED binary, which is the trap that entry "
                     "describes. Counting only the seconds US_G_STATE holds "
                     "MET_ST_SCENE turns it into 'how fast does the cutscene "
                     "play', which is a property of the playhead alone."),
        ],
    ),
    "railshooter": dict(
        rom="build/railshooter.sfc", map="build/rs/symbol_map.json",
        scene="rail",
        klass="mode7",
        # NO PAD. The ship is FIXED and flies itself around a baked S-curve;
        # the only thing the player owns is the aiming reticle, and moving it
        # would add a rate the drive script paces rather than one the rail
        # generates. The guard is the fail state: five hazard strikes stop the
        # run and put a 120-frame countdown in front of a self-restart, and a
        # window spanning that averages a live rail with a dead one.
        # MEASURED, and the guard is what found it: with nobody shooting, the
        # ship takes its fifth hazard strike at t = 8.0 s and the rail freezes
        # for a 120-frame countdown. A window closing at 8.5 s spans half a
        # second of that, which drags the forward rate from 30.05 px/s to
        # 26.33 in its second half — a dead rail averaged into a live one,
        # exactly what the guard exists to make visible. The window closes at
        # 7.5 s.
        script=[(0.0, {})],
        warmup_s=1.5, window_s=6.0, guard=[("US_FAIL_T", 2, 0)],
        observables=[
            dict(name="cam_fwd", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_M7ORG", 2, 2, 1024)],
                 why="M7Y — the forward half of the camera origin `rs_advance` "
                     "publishes (rs_logic.asm:270) and the NMI hook commits to "
                     "the PPU every armed frame. The Mode 7 plane is drawn "
                     "FROM it, so world pixels per second here is the rate the "
                     "ground comes at the ship.\n"
                     "  THE TWO AXES ARE MEASURED SEPARATELY, NOT AS A "
                     "path2d, and on this rail that is worth 3.7 points. "
                     "path2d sums hypot() of the per-frame delta PAIR, and "
                     "hypot is SUBADDITIVE: two unit steps taken one axis at a "
                     "time sum to 2 while the same displacement taken in one "
                     "frame is 1.414. This rail advances its state 1 or 2 "
                     "times per frame, so a doubled frame folds two steps into "
                     "one delta and path2d charges PAL for the shortcut — "
                     "measured at 0.96255 against 0.99850 on the same binary. "
                     "Summing |delta| per AXIS is additive and immune to it."),
            dict(name="cam_swing", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_M7ORG", 0, 2, 1024)],
                 why="M7X — the lateral half of the same origin, and the whole "
                     "of the S-curve: `rs_path_step` sets it to RS_CENTRE + "
                     "rs_path[dist] and rs_advance publishes it. Lateral world "
                     "pixels per second is the rate the rail SWINGS, which the "
                     "forward measure cannot see. Same per-axis reasoning as "
                     "cam_fwd. The modulus is the plane's own period "
                     "(RS_WORLD_MASK + 1 = 1,024), which rs_advance masks both "
                     "axes to."),
            dict(name="ship_pose", kind="transitions", unit="tile changes",
                 mem="oam", fields=[("ES_O_RS_SHIP", 2, 1, 256)],
                 why="the ship's OAM TILE byte, read out of the sprite table "
                     "the PPU draws from — rendered output, not US_LEAN behind "
                     "it. rs_path_step grades the path's own slope into nine "
                     "bank poses and a rate limiter walks ONE pose per state "
                     "step toward the target, so the frames on which the drawn "
                     "pose CHANGES measure the bank ramp — the one animation "
                     "on this rail, and the one that would drift if the "
                     "odometer and the ramp were on different clocks."),
        ],
    ),
    # DEFERRED, NOT CONVERTED, and this entry is the measurement that says so.
    # The rail reads 0.83208 / 0.80538 / 0.86167 below and the shipping image is
    # byte-identical to what it was.
    #
    # WHY. Every velocity on this rail is a RUNTIME word read out of one baked
    # LUT: `move256[h]`, 8.8 with a constant 2.0 px/frame magnitude, which
    # SH2_DRIVE_AXIS accumulates for the two cameras and swm_ai accumulates at
    # half rate for each of 22 followers with its own per-entity 8-bit
    # fractions. There is no build-time constant for TS_STEP to take, so the
    # mechanism the other nine rails use does not reach it.
    #
    # AND THE STATE-STEP FORM DOES NOT FIT, measured rather than argued. Running
    # `cam_advance` + `swm_ai` 1 or 2 times per frame OVERRUNS the PAL frame:
    # SWM_BEAT — the scene tick's own counter, which sh2_swarm.asm pairs with
    # scene_mgr's VBlank count precisely so an overrun is visible — reached 423
    # against ES_SM_FRAME's 479, so an eighth of PAL frames dropped their game
    # update. The pre-change image runs 479/479 in both regions. That is
    # docs/95 §4.3's O(tick) objection landing on a real rail, and it is the
    # first time in this lane it has bitten: the other nine rails' state steps
    # are a dozen adds, and this one steers a 24-entity swarm through a
    # projection.
    #
    # Narrowing the loop to `cam_advance` alone DOES fit (479/479, heading at
    # 1.2 units a frame), and it is not taken: it would put the floor at parity
    # and leave the cast it is projected against at 0.832, which is a new
    # inconsistency rather than a partial fix.
    #
    # WHAT WOULD CONVERT IT: a SECOND baked move LUT at the PAL magnitude
    # (2.4036 px/frame), selected by ES_RGN_PAL at scene enter. Both consumers
    # read the same blob, so one +1 KB rom claim and a generator argument would
    # scale the cameras AND the swarm at ZERO per-frame cost — which is the
    # shape this rail wants and is asset-pipeline work across seven variant
    # images, not a timebase composition.
    "split_h_2p_demo": dict(
        rom="build/split_h_2p_demo.sfc", map="build/sh2/symbol_map.json",
        scene="split",
        klass="mode7",
        # PAD 1 ONLY, holding B and RIGHT: B drives camera 1 forward at a
        # constant 2.0 px/frame through the move LUT and RIGHT steps its
        # heading, so it flies a constant-radius circle. The shipping build's
        # pad control REPLACES the autonomous step (cam_input, not cam_drive),
        # so with nothing held the cameras stand still — which is why the
        # script holds something. `mesen_runner` drives port 1 here, so camera
        # 2 stays parked and is not measured.
        script=[(0.0, {"b": True, "right": True})],
        warmup_s=2.0, window_s=14.0, guard=[],
        observables=[
            dict(name="cam1_x", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_SH2_POS", 0, 2, 1024)],
                 why="camera 1's world X. `cam_stamp` writes it into the "
                     "origin table HDMA feeds to M7X at scanline 0, so band 1 "
                     "of the picture is drawn FROM this word. Read as a "
                     "PER-AXIS distance rather than as half a path2d: hypot is "
                     "subadditive and this rail advances its state 1 or 2 "
                     "times per frame, so a doubled frame would be charged for "
                     "the shortcut (railshooter's entry carries the "
                     "measurement). The modulus is the plane's own period, "
                     "SH2_WRAP + 1 = 1,024, which SH2_DRIVE_AXIS masks to."),
            dict(name="cam1_y", kind="distance", unit="world px",
                 mem="wram", fields=[("ES_SH2_POS", 2, 2, 1024)],
                 why="camera 1's world Y, the other axis of the same origin "
                     "and the same HDMA table. Both are needed because the "
                     "move LUT splits a CONSTANT 2.0 px/frame magnitude "
                     "between them by heading, so either axis alone measures "
                     "the heading as much as the speed."),
            dict(name="cam1_head", kind="distance", unit="heading units",
                 mem="wram", fields=[("ES_SH2_ROT", 0, 2, 256)],
                 why="camera 1's heading, 0..255. `cam_ptrs` turns it into the "
                     "pose-table pointer band 1's two INDIRECT HDMA channels "
                     "stream a fresh 4-byte matrix unit from on every one of "
                     "its 112 scanlines — so the whole band rotates by it. It "
                     "is also the index the move LUT is read at, which is why "
                     "the rail scales the state step: the rotation and the "
                     "translation have to advance together or the camera "
                     "points somewhere the floor is not."),
        ],
    ),
    "m7_dungeon": dict(
        rom="build/m7_dungeon.sfc", map="build/m7dg/symbol_map.json",
        scene="dungeon",
        klass="mode7",
        # B AND LEFT, and B ALONE WOULD MEASURE THE MAZE. Measured: holding the
        # throttle straight walks him into the corridor wall inside three
        # seconds and the position stops changing at all, so the rail would
        # read zero and the reason would be the level, not the timebase. With
        # the turn held too he circles inside the START cell, bumping walls,
        # which is motion the maze cannot stop.
        #
        # THE WINDOW IS SHORT AND THE GUARD SAYS WHY: an enemy reaches him at
        # about 3.3 s and a contact knocks the hero HOME — a teleport no path
        # measure should average into a walking speed.
        script=[(0.0, {"b": True, "left": True})],
        warmup_s=0.5, window_s=2.5,
        guard=[("US_HITS", 2, 0), ("US_PAUSED", 2, 0)],
        observables=[
            dict(name="heading", kind="distance", unit="heading units",
                 mem="wram", fields=[("US_HEADING", 0, 1, 256)],
                 why="the hero's heading, 0..255. `m7a_set_heading` turns it "
                     "into the affine matrix the VBlank commit writes, so the "
                     "WHOLE DUNGEON FLOOR rotates by it — heading units per "
                     "second is the rate the world turns under the player, "
                     "which no position measure captures."),
            dict(name="hero_path", kind="path2d", unit="px/65536",
                 mem="wram",
                 fields=[("US_POSX", 0, 4, 1 << 32),
                         ("US_POSY", 0, 4, 1 << 32)],
                 why="the hero's 16.16 world position, read WHOLE — the pair "
                     "m7a_set_center re-pins the affine pivot from every "
                     "frame, so the floor is drawn out of it. Read at 16.16 "
                     "rather than at the integer half for the reason "
                     "m7_oshoot's entry gives: summing hypot() over integer "
                     "deltas charges the two regions different rounding and "
                     "measures the quantiser as much as the rail."),
        ],
    ),
    "m7_oshoot": dict(
        rom="build/m7_oshoot.sfc", map="build/mo/symbol_map.json",
        scene="arena",
        klass="mode7",
        # UP and LEFT together: the throttle drives forward along the facing
        # while the facing turns, so the hero walks a constant-radius circle
        # and BOTH observables are exercised at once. The guard is what makes
        # the position half honest — a chaser contact TELEPORTS him back to
        # spawn (arena.asm's @hit), which is a 500 px step no path measure
        # should be allowed to average into a walking speed.
        # THE WINDOW IS SHORT AND THE GUARD IS WHY. Measured: the first chaser
        # reaches him at t = 4.03 s on NTSC and 4.84 s on PAL, and after that
        # the position measure is averaging 500 px teleports. Three seconds of
        # circling is 340 world px and 540 heading units — 1% is three px and
        # five units, which is resolution enough, and it is honest resolution
        # rather than a longer window with a dead rail inside it.
        script=[(0.0, {"up": True, "left": True})],
        warmup_s=0.8, window_s=2.2, guard=[("US_HITS", 2, 0)],
        observables=[
            dict(name="heading", kind="distance", unit="heading units",
                 mem="wram", fields=[("US_HEADING", 0, 1, 256)],
                 why="the hero's heading, 0..255. `m7a_set_heading` turns it "
                     "into the affine matrix the VBlank commit writes, so the "
                     "WHOLE FLOOR rotates by it — heading units per second is "
                     "the rate the arena turns under the player, which no "
                     "position measure captures. It is also the observable "
                     "that survives a knockback: @hit clears the speed and "
                     "the strafe and leaves the facing alone."),
            dict(name="hero_path", kind="path2d", unit="px/65536",
                 mem="wram",
                 fields=[("US_POSX", 0, 4, 1 << 32),
                         ("US_POSY", 0, 4, 1 << 32)],
                 why="the hero's 16.16 world position, read WHOLE — the pair "
                     "m7a_set_center re-pins the affine pivot from every "
                     "frame, which is what keeps him at screen centre while "
                     "the arena slides under him. Path length here is the "
                     "ground he covers.\n"
                     "  READ AT 16.16 AND NOT AT THE INTEGER HALF, and the "
                     "difference is 2.4 points of ratio. Summing hypot() over "
                     "INTEGER per-frame deltas measures the quantiser as much "
                     "as the rail: a 1.25 px/frame step lands as a 1-or-2 px "
                     "delta and a 1.50 px/frame step lands as a different mix, "
                     "so the two regions are charged different rounding. "
                     "Measured both ways on the same binary: 0.97168 at the "
                     "integer half against 1.00103 at 16.16, with the rail's "
                     "own step exactly 385/320 = 1.203125 either way. The "
                     "modulus is the word's own 2^32; the hero circles inside "
                     "a 17 px radius and never approaches the world wrap."),
        ],
    ),
    "mode7_chamber": dict(
        rom="build/mode7_chamber.sfc", map="build/m7c/symbol_map.json",
        scene="chamber",
        klass="mode7",
        # NO PAD AT ALL, and that is the rail: the roll drives itself in legs
        # of three surges, holds dead for half a second, then reverses. Holding
        # Up/Down would walk m7_barrel's bow step, which changes the picture
        # without changing the motion — so the empty script measures the roll
        # and nothing else.
        #
        # THE WINDOW IS LONG BECAUSE THE CYCLE IS. One surge is ~7 s and a leg
        # is ~21 s, so a 14 s window would compare two different parts of the
        # cycle. 30 s spans more than a whole leg in both regions.
        script=[(0.0, {})],
        warmup_s=1.0, window_s=30.0, guard=[],
        observables=[
            dict(name="roll_y", kind="distance", unit="world px",
                 mem="wram", fields=[("US_POSY", 1, 2, 1024)],
                 why="the INTEGER half of the 16.8 vertical position. "
                     "`roll_commit` (m7c_roll.asm:61) copies exactly this word "
                     "into MB_M7Y and derives MB_VOFS from it, and mb_commit_"
                     "origin writes both to the PPU every VBlank — so this is "
                     "the world row the bottom scanline is standing on. World "
                     "pixels per second here IS the speed the chamber rolls "
                     "at. The modulus is the plane's own period (CH_MAP_MASK "
                     "+ 1 = 1024), which the roll wraps to in both "
                     "directions."),
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
    jmap = json.loads(Path(args.map).read_text() if args.map
                      else (SUPERFORGE / rail["map"]).read_text())

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
    for flag, val in (("--rom", args.rom), ("--map", args.map),
                      ("--label", args.label),
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
                    help="override the rail's ROM (a variant or a "
                         "pre-change image); see --map, which such an image "
                         "almost always needs too")
    ap.add_argument("--map", default=None,
                    help="override the rail's emitted symbol map. A PRE-CHANGE "
                         "image needs its PRE-CHANGE map: the allocator packs "
                         "a scene's user words alphabetically, so declaring a "
                         "new one moves every word that sorts after it, and "
                         "reading an old ROM through the new map reads the "
                         "wrong dp bytes. Measured, not reasoned: `room`'s "
                         "hero_x read 0.000 that way while its OAM observable "
                         "(a claim that did not move) read correctly.")
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
