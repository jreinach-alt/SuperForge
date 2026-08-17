"""split_v_fight — a round of the fight, cut on the round start.

THE CLAIM IS THE SPLIT, and it is a claim about CONTINUITY that a still cannot
make: the two half-cameras diverge continuously from the fighter separation, so
at zero separation the halves are pixel-identical and the ever-present seam is
invisible, and a beveled BG3 bar grows from ZERO width as they part. The round
below is shaped so that a viewer watches that happen once in each direction,
before any punch is thrown:

    FIGHT       the count's last beat, both fighters on their marks, the view
                merged and the divider nowhere
    breaking    they back away to the arena walls — the divider opens from
                nothing, and the two halves pull apart onto different stretches
                of the stage
    wide        held at full separation, where the ridge and the treeline on
                one side of the bar plainly do not join the ones on the other
    closing     they walk back together — the divider narrows to nothing and
                the two halves re-join into one continuous picture
    trading     swings land, the pack's own blade sweeps, life bars empty a
                segment at a time — all of it inside melee range, so the view
                stays merged and the seam stays invisible, which is the other
                half of the same claim
    a dodge     one hops a swing, which is the vertical gate the jump exists
                for
    KO          a bar empties, the loser plays the pack's death frame and the
                round holds
    3 2 1       the next round counts in over a merged view
    FIGHT       ...and the take closes on that beat

THE OPEN AND THE CLOSE ARE THE POINT, and the drive did not used to have them.
It walked the fighters straight into melee range and kept them there, and
MEASURED over the whole live round that gap stays between 26 and 44 px — which
is far inside SV_MERGE_DX (128), so the spread target clamps to exactly ZERO
and the divider is not merely thin, it is absent. The old clip showed a fight
on a shared screen and never once showed the mechanism the rail exists for.
Nor could the knockback rescue it: SV_KNOCKBACK is 12 px against the 84 px the
pair would have to gain to reach the merge distance at all.

Backing off to the walls first is what buys the picture. dx reaches 208, the
spread eases to its plateau of 40 — the arena's real ceiling, below the
SV_SPREAD_MAX of 48, because the target is (dx - SV_MERGE_DX) / 2 — and since
split_v_bg puts cam A at mid - spread and cam B at mid + spread, the two halves
end up 80 px of world apart. Read off the recorded GIF, the divider runs
0 -> 3 -> 5 -> 3 -> 0 px across the take (5 px is hw = 40 >> 4 = 2, spanning
x 126..130), and the ridge and treeline plainly do not meet across it.

EVERY BEAT WAITS ON THE ROM. The spread is an EASE, a swing is a countdown, a
KO is a bar reaching zero: none of those is a number of frames, and a frame
plan would open the split most of the way and call it open (the lesson this
drive's first version was written around). The break-apart beat is the sharpest
case of it — SV_SPR_STEP eases at 0.75 px/frame while the fighters separate at
2 px/frame each, so the picture lags the positions by tens of frames and
"they have reached the walls" is nowhere near "the split has finished opening".
What is waited on is both at once: the fighters STOPPED (the arena clamp holds
them) and the spread STOPPED (the ease reached its target and the ROM's own
`@settled` branch pins it there).

THE LOOP POINT IS THE ROUND START. The take opens on a FIGHT beat and closes on
the next one, which is the one moment the fighters are back on their marks with
the view merged, the bars refilled and both animation clocks zeroed — all by
the same `round_arm`, the same number of frames earlier. Measured with
tools/gif_seam.py, not eyeballed.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "split_v_fight"
CAPTURES = 420                  # a CEILING, not a schedule: `.done` closes the
                                # take on the round start. Raised from 260 for
                                # the break-apart and close-in beats, which are
                                # ~60 captures of live round the old drive did
                                # not play.
SETTLE = 40                     # EMULATED frames — into the opening count

# Captures held at full separation once the ROM says the split has finished
# opening. This is the ONLY count in the drive and it is not a substitute for
# an event: the beat it belongs to has already been detected off ES_SV_SPREAD,
# and this is how long the finished picture stays on screen afterwards so a
# viewer can read it. 12 captures is 0.6 s of the 20 Hz clip.
WIDE_HOLD = 12

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
    NEXT one. Between them the drive plays a round in four beats — break,
    hold, close, trade — advanced by what the ROM reports, never by a count.
    """

    BREAK, WIDE, CLOSE, TRADE = "break", "wide", "close", "trade"

    def __init__(self):
        self.started = False
        self.done = False
        self.fought = False         # a LIVE round has happened since `started`
        self.beat = None            # None until a round goes live
        self.last = None            # (fx1, fx2, spread) at the previous capture
        self.held = 0
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
            self.beat = None                    # a new round breaks apart again
            return self._step(r)
        self.fought = True
        if self.beat is None:
            self.beat, self.last, self.held = self.BREAK, None, 0

        fx1, fx2 = _u16(r, FX1), _u16(r, FX2)
        gap = abs(fx1 - fx2)
        # Which way is OUT depends on who is on the left, and they cross: a
        # fixed pad assignment would drive them together after a swap.
        out = ({"left": True}, {"right": True}) if fx1 < fx2 \
            else ({"right": True}, {"left": True})
        into = (out[1], out[0])

        # ---- break: back off until BOTH the walk and the ease have stopped ---
        if self.beat is self.BREAK:
            now = (fx1, fx2, _u16(r, SPREAD))
            stopped = now == self.last
            self.last = now
            if stopped:
                self.beat = self.WIDE
            return self._step(r, *out)

        # ---- wide: hold the finished picture ---------------------------------
        if self.beat is self.WIDE:
            self.held += 1
            if self.held >= WIDE_HOLD:
                self.beat = self.CLOSE
            return self._step(r, *out)

        # ---- close: walk back in, the divider narrowing with the gap ---------
        if self.beat is self.CLOSE:
            if gap > REACH - 6:
                return self._step(r, *into)
            self.beat = self.TRADE

        # ---- trade: swings and a dodge, at a range the divider never sees ----
        # A landed hit throws the defender SV_KNOCKBACK px and the pair walk
        # back in, so the gap breathes — but only between 26 and 44 px, which
        # is nowhere near SV_MERGE_DX, so the divider stays at zero for every
        # frame of this beat. The open and the close are the two beats above;
        # this one is the merged half of the claim.
        if gap > REACH - 6:
            return self._step(r, *into)

        # In range. P1 swings whenever its blade is down; P2 answers with a
        # hop every other exchange, which is the vertical gate on screen.
        p1 = {"a": True} if _u16(r, SWG) == 0 else {}
        p2 = {}
        if _u16(r, SWG + 2) == 0 and _u16(r, JMP + 2) == 0 and (self.n // 16) % 2:
            p2 = {"b": True}
        return self._step(r, p1, p2)


def make_drive():
    return Round()
