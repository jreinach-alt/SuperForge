"""microzero — the tiny complete game, WHOLE.

THE CLIP IS THE PROOF GATE. microzero's claim is not "a race renders"; it is
title -> race -> results -> title, globals surviving the edges and scene bytes
reused across them. That is a LOOP, and a loop is the one thing a still cannot
show. So this take holds all of it, measured on this binary in captures:

    0     the title card
    6     START taken; the race scene up
    98    lap 1
    172   lap 2
    246   lap 3 — the race tick requests results on that frame
    252   the results card
    286   START taken again; back on the title, loop closed

...which is 14.3 s at 1:1, and the reason CAPTURES sits just past it.

THE RACE IS FLOWN BY THE TESTS' OWN AUTOPILOT. tests/mz_drive.track_buttons
is the controller the suite uses — full throttle, at most one pose step of
steering toward the track heading, which is the declared max turn rate. Two
things make it the right choice here rather than a canned input script:

  * it is FULL SPEED by construction, which is the format rule; and
  * the sim it steers from is re-seeded from the ROM's live race state EVERY
    capture (sim_from_rom), so it is a closed loop on the actual car rather
    than an open-loop plan that drifts. The recorder's own screenshot frame
    releases the pad once per capture, which a lockstep oracle would have to
    be told about; re-seeding means it cannot drift in the first place.

START IS AN EDGE, pressed every other capture on the two cards, and it stops
once the loop has closed — otherwise the clip's last captures would start a
second race and the ending would read as a glitch rather than as a return.
"""
import json
import sys
from pathlib import Path

from tools.record_gallery_clip import STEP

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT / "tests"), str(ROOT / "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mz_drive as D                                    # noqa: E402

ROM = "microzero"
CAPTURES = 292                  # 14.6 s at 1:1 — the whole loop, plus a beat
SETTLE = 60                     # EMULATED frames — the title card is up

TITLE, RACE, RESULTS = 0, 1, 2

_J = json.loads((ROOT / "build" / "mz" / "symbol_map.json").read_text())
SYMS = {n: {p["sym"]: p for p in _J["scenes"][n]["placements"] + _J["globals"]}
        for n in ("title", "race", "results")}
LUT = D.load_tool("gen_move_lut")


class Loop:
    """One capture per call; the scene manager says which card we are on."""

    def __init__(self):
        self.seen_results = False

    def __call__(self, r, i):
        scene, _phase = D.scene_now(r, SYMS["title"])
        if scene == RACE:
            sim = D.sim_from_rom(r, SYMS["race"], LUT)
            return r.frame_step(STEP, **D.track_buttons(sim, LUT))
        if scene == RESULTS:
            self.seen_results = True
            return r.frame_step(STEP, start=(i % 2 == 0))
        # the title card: take it on the way IN, and leave it alone on the
        # way out so the clip ends on the loop closing rather than reopening
        return r.frame_step(STEP, start=(not self.seen_results and i % 2 == 0))


def make_drive():
    return Loop()
