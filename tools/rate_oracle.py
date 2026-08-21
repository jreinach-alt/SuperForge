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
    for a rail whose action is EDGE-triggered and which therefore cannot be
    driven by holding anything.

    The three streams are merged onto ONE timeline rather than concatenated,
    because `_script_at` takes the last entry at or before t and each entry
    is a WHOLE pad state: an event that carried only the tap would silently
    release the direction.
    """
    marks = set()
    if start_s is not None:
        marks |= {0.0, start_s, start_s + 0.3}
        t0 = start_s + 0.6
    else:
        t0 = 0.0
    marks.add(t0)
    for k in range(n):
        marks.add(t0 + lead_s + k * half_s)
    if tap:
        _b, per, hold_s = tap
        k = 0
        while t0 + k * per < span_s:
            marks.add(t0 + k * per)
            marks.add(t0 + k * per + hold_s)
            k += 1
    hold = hold or {}

    def _pad(t):
        if start_s is not None and t < start_s:
            return {}
        if start_s is not None and start_s <= t < start_s + 0.3:
            return {"start": True}
        if t < t0:
            return {}
        p = dict(hold)
        d = t - t0
        p[first if d < lead_s else
          (first if int((d - lead_s) // half_s) % 2 == 0 else second)] = True
        if tap:
            b, per, hold_s = tap
            if (d % per) < hold_s - 1e-9:
                p[b] = True
        return p

    return [(t, _pad(t)) for t in sorted(marks)]


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
        # A horizontal shuttle. The world is 512 px and the runner spawns at
        # x=16, so the LEFT clamp is 16 px away — the shuttle therefore opens
        # by running RIGHT for a full half-period and reverses on a 0.6 s
        # beat (72 px at the NTSC rate), which keeps him between roughly 16
        # and 160 in both regions.
        script=_axis_shuttle(0.6, "right", "left"),
        warmup_s=2.0, window_s=12.0, guard=[],
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
                     "output the sprite Y is derived from. THIS ONE IS THE "
                     "NON-VACUITY CONTROL: the ballistic arc is NOT scaled "
                     "(see the rail's own note), so it must still read the "
                     "frame ratio while run_x reads parity. An instrument "
                     "that showed both at parity would be measuring itself."),
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
        script=_axis_shuttle(0.5, "left", "right"),
        warmup_s=2.0, window_s=12.0, guard=[],
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
            dict(name="fall_y", kind="distance", unit="px/256",
                 mem="wram", fields=[("US_PYF", 0, 2, 65536)],
                 why="the player's 8.8 vertical position. THIS ONE IS THE "
                     "NON-VACUITY CONTROL: the ballistic arc is NOT scaled "
                     "(see the rail's own note), so it must still read the "
                     "frame ratio while the two horizontal rates read "
                     "parity."),
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
        # START clears the title, then a horizontal shuttle with A held down
        # so the ship also fires. SHIP_MIN_X/MAX_X are 8 and 224 and the ship
        # spawns at 120; a 0.6 s half-period is 72 px at the NTSC rate, which
        # keeps it off both clamps. A is held rather than tapped because the
        # bullet observable wants the pool busy, and the fire gate is a
        # per-frame pool spawn rather than a press edge.
        script=_axis_shuttle(0.6, "right", "left", start_s=0.5,
                             hold={"a": True}),
        warmup_s=3.0, window_s=12.0,
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
            dict(name="ship_y", kind="distance", unit="screen px",
                 mem="wram", fields=[("US_PY", 0, 2, 65536)],
                 why="the ship's own y. It is the axis the shuttle does NOT "
                     "drive, so it moves only when the drive's held "
                     "direction changes nothing about it — kept as the "
                     "cross-check that the tick is doing per-axis work."),
        ],
    ),
    "breaker": dict(
        rom="build/breaker.sfc", map="build/bk/symbol_map.json",
        scene="play",
        klass="shooting",
        # START clears the title; A launches the ball off the paddle; then a
        # horizontal shuttle runs the bat. The bat is clamped to [8, 224] and
        # starts at 116, so a 0.5 s half-period (90 px at the NTSC rate)
        # stays inside. A is re-tapped on the shuttle's beat so a LOST ball
        # relaunches rather than leaving the window measuring a dead rail —
        # the guard below is what makes that visible if it fails anyway.
        script=_axis_shuttle(0.5, "right", "left", start_s=0.5,
                             hold={"a": True}),
        warmup_s=3.0, window_s=10.0,
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
        # Hold RIGHT for the whole run. The overworld is a 1024 px TORUS, so
        # there is no clamp anywhere and a held direction walks for ever —
        # the grid slide simply re-arms itself every STEP_FRAMES frames.
        script=[(0.0, {"right": True})],
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
