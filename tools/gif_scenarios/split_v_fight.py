"""split_v_fight — a round of the fight, cut on the round start.

THE CLAIM IS STILL THE SPLIT, and it is still a claim about CONTINUITY that a
still cannot make: the two half-cameras diverge continuously from the fighter
separation, so at zero separation the halves are pixel-identical and the
ever-present seam is invisible, and a beveled BG3 bar grows from ZERO width as
they part. What has changed is that the fighters now have a REASON to separate
and close, so the clip shows the mechanism being driven by a game rather than
by a demo walking wall to wall.

    FIGHT       the count's last beat, both fighters on their marks, the view
                merged and the divider nowhere
    closing     they walk together — the split at its narrowest
    trading     swings land, the pack's own blade sweeps, life bars empty a
                segment at a time; the knockback throws them apart and the
                divider opens with the distance
    a dodge     one hops a swing, which is the vertical gate the jump exists
                for
    KO          a bar empties, the loser plays the pack's death frame and the
                round holds
    3 2 1       the next round counts in over a merged view
    FIGHT       ...and the take closes on that beat

THE LOOP POINT IS THE ROUND START, and it is the thing this rail did not have.
The previous cut measured seam 5.40 / 9.5% of pixels, and it could not do
better: its fighters crossed twice per circuit and the pair's MIDPOINT drifted
as they did, so no capture held separation, spread and midpoint at once. A
round start settles all three at once, by construction — `round_arm` puts both
fighters back on their marks and refills both bars — which is why the drive
brackets on it rather than on a pose it has to fly back to.

...AND THE BEAT IT CUTS ON IS *FIGHT*, NOT "3". At the start of a countdown the
spread is whatever the KO left it at, easing down at 0.75 px/frame; by the
FIGHT beat, 96 frames later, it has reached exactly zero from any starting
value inside SV_SPREAD_MAX. So the two ends agree about the cameras as well as
about the fighters, and the fighters' own animation clocks agree too — both
were zeroed by the same `round_arm`, the same number of frames earlier.

EVERY BEAT WAITS ON THE ROM. The spread is an EASE, a swing is a countdown, a
KO is a bar reaching zero: none of those is a number of frames, and a frame
plan would open the split most of the way and call it open (the lesson this
drive's first version was written around).
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "split_v_fight"
CAPTURES = 260                  # a CEILING, not a schedule: `.done` closes the
                                # take on the round start
SETTLE = 40                     # EMULATED frames — into the opening count

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "sv" / "symbol_map.json").read_text())


def _dp(name):
    return next(p for p in _J["scenes"]["fight"]["placements"]
                if p["sym"] == name)["start"]


SPREAD, FX1, FX2 = (_dp(n) for n in ("ES_SV_SPREAD", "US_FX1", "US_FX2"))
RSTATE, RTIMER, HP, SWG, JMP = (_dp(n) for n in
                                ("US_RSTATE", "US_RTIMER", "US_HP",
                                 "US_SWG", "US_JMP"))

# game/split_v_fight/split_v.inc, restated: the drive reads the ROM's state and
# has to know what the values MEAN.
R_COUNT, R_LIVE, R_KO = 0, 1, 2
COUNT_STEP = 32                 # the FIGHT beat is the last COUNT_STEP frames
REACH = 44                      # SV_SWING_REACH: inside this, a swing lands


def _u16(r, off):
    b = r.read_bytes(W, off, 2)
    return b[0] | (b[1] << 8)


class Round:
    """One capture per call; both pads latched, every beat read off the ROM.

    `started` stays falsy until the opening FIGHT beat, so the boot, the fade
    and the first "3 2 1" are dropped lead-in; `done` closes the take on the
    NEXT one. Between them the drive plays a round: close, trade, dodge, and
    let the KO land.
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.fought = False         # a LIVE round has happened since `started`
        self.n = 0

    def _step(self, r, p1=None, p2=None):
        r.set_input(1, **(p2 or {}))    # pad 2 persists across the step
        return r.frame_step(STEP, **(p1 or {}))

    def _fight_beat(self, r):
        return (_u16(r, RSTATE) == R_COUNT
                and _u16(r, RTIMER) <= COUNT_STEP)

    def __call__(self, r, i):
        self.n += 1
        if not self.started:
            # lead-in: idle through the boot and the opening count
            if self._fight_beat(r):
                self.started = True
                self.n = 0
            return self._step(r)

        if _u16(r, RSTATE) != R_LIVE:
            # the count's last beat, or the KO hold. Both are the ROM's own
            # pauses and both are worth watching; the only thing to decide is
            # whether the round has come back round.
            #
            # `fought` is what makes that question honest. The take OPENS on a
            # FIGHT beat, and that beat lasts COUNT_STEP frames — so a close
            # condition that only asks "is this a FIGHT beat" fires on the beat
            # it opened on and ships a two-frame clip. It did.
            if self.fought and self._fight_beat(r):
                self.done = True
            return self._step(r)
        self.fought = True

        # ---- live: close the distance, then trade ---------------------------
        fx1, fx2 = _u16(r, FX1), _u16(r, FX2)
        gap = abs(fx1 - fx2)
        toward = ({"right": True}, {"left": True}) if fx1 < fx2 \
            else ({"left": True}, {"right": True})
        if gap > REACH - 6:
            return self._step(r, *toward)

        # In range. P1 swings whenever its blade is down; P2 answers with a
        # hop every other exchange, which is the vertical gate on screen.
        p1 = {"a": True} if _u16(r, SWG) == 0 else {}
        p2 = {}
        if _u16(r, SWG + 2) == 0 and _u16(r, JMP + 2) == 0 and (self.n // 16) % 2:
            p2 = {"b": True}
        return self._step(r, p1, p2)


def make_drive():
    return Round()
