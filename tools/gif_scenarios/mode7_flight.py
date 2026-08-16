"""mode7_flight — the LEAD clip.

ONE CONTINUOUS FLIGHT, and every beat is one of this rail's axes:

    cruise      the spawn altitude under throttle — the establishing shot, so
                the climb that follows has something to be measured against
    climb       R held to the CEILING CLAMP: the ground recedes, the horizon
                fills with world, the shadow goes small. Held past the clamp
                on purpose, so the end stop is in the clip
    dive        L held to the FLOOR CLAMP: the ground comes up to meet the
                ship, features go large, the shadow is the big one
    turn left   the heading axis alone, under throttle — the cloud band and
                the ground plane sweep at DIFFERENT rates, which is the
                parallax the factored pose buys
    turn right  the same axis the other way, so the clip is not a
                one-direction claim and the parallax reverses with it
    both axes   turning and climbing and thrusting at once, which is the
                composition the whole S_a(k) * R(h) factoring exists for

THE ALTITUDE BEATS ARE STATE-DRIVEN, the heading beats are counted, and the
difference is the point of the __init__ rule. Altitude has EVENTS — index 80
is the ceiling and 0 is the floor, both clamps — so the drive holds R until
the ROM says 80 rather than counting the 40 frames it takes today. Heading
has no event: it sweeps 0..255 at a constant rate under a held direction, so
"sweep until the byte has moved 96 units" is what an event would be if there
were one, and that is what these wait on.

THROTTLE IS HELD FOR THE WHOLE TAKE. Full gameplay speed is the format rule
(the split_h lesson), and on a flight rail the throttle IS the speed.

DAY/NIGHT IS NOT IN THIS CLIP, and that is arithmetic rather than choice. The
clock is free-running at 32 phase units a frame and 1,024 to the step, so a
full cycle is 2,048 frames = 34 s at 1:1 — five times the budget. What the
clip DOES hold is the part of the arc it can: measured on this binary the sky
walks (33,90,181) noon-blue toward (57,49,99) over the take, with the terrain
ambient dimming under it, so the light moves visibly without a cut. The poles
are the still renders' job — tools/shot_mode7_flight.py photographs both.

THE MOVING PALETTE IS THIS RAIL'S OWN CONTRIBUTION TO THE FORMAT. The take
holds 1,336 distinct RGB values (HDMA rewrites CGRAM per scanline, and the
clock walks it), which is what surfaced the recorder's shared-palette bug: a
frame-0 palette plus the quantiser's default dither turned the last third of
this clip into orange noise AND blew the 2 MB budget at 2.60 MB. The palette
is now built over the whole take with dither off — same contract clause,
1.21 MB, four times closer to the picture. See quantize_take().
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "mode7_flight"
CAPTURES = 150                  # 7.5 s at 1:1
SETTLE = 60                     # EMULATED frames — past the boot fade-in

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "m7f" / "symbol_map.json").read_text())
_POSE = next(p for p in _J["scenes"]["sky"]["placements"]
             if p["sym"] == "ES_M7F_POSE")["start"]
HEAD, ALTIDX = _POSE + 8, _POSE + 10     # m7f_cam.asm's own field offsets

CEILING, FLOOR = 80, 0          # M7F_ALT_MAXIDX / the bottom of the axis
SWEEP = 96                      # heading units per turn beat (~135 degrees)
THROTTLE = dict(b=True)


def _alt(r):
    return r.read_bytes(W, ALTIDX, 1)[0]


def _head(r):
    return r.read_bytes(W, HEAD, 1)[0]


class Flight:
    """One capture per call; the beat it is in decides what is held."""

    def __init__(self):
        self.phase = 0
        self.n = 0              # captures spent in the current beat
        self.mark = None        # heading at the start of a turn beat

    def _next(self):
        self.phase += 1
        self.n = 0
        self.mark = None

    def __call__(self, r, i):
        p, self.n = self.phase, self.n + 1

        if p == 0:                                  # cruise, establishing
            if self.n > 18:
                self._next()
            return r.frame_step(STEP, **THROTTLE)

        if p == 1:                                  # climb to the clamp
            if _alt(r) >= CEILING and self.n > 4:
                self._next()
            return r.frame_step(STEP, r=True, **THROTTLE)

        if p == 2:                                  # ...and held against it
            if self.n > 6:
                self._next()
            return r.frame_step(STEP, r=True, **THROTTLE)

        if p == 3:                                  # dive to the floor clamp
            if _alt(r) <= FLOOR and self.n > 4:
                self._next()
            return r.frame_step(STEP, l=True, **THROTTLE)

        if p == 4:                                  # ...and held against it
            if self.n > 6:
                self._next()
            return r.frame_step(STEP, l=True, **THROTTLE)

        if p == 5:                                  # the heading axis, left
            if self.mark is None:
                self.mark = _head(r)
            if (self.mark - _head(r)) % 256 >= SWEEP:
                self._next()
            return r.frame_step(STEP, left=True, **THROTTLE)

        if p == 6:                                  # ...and back the other way
            if self.mark is None:
                self.mark = _head(r)
            if (_head(r) - self.mark) % 256 >= SWEEP:
                self._next()
            return r.frame_step(STEP, right=True, **THROTTLE)

        # both axes at once, for whatever the take has left
        return r.frame_step(STEP, left=True, r=True, **THROTTLE)


def make_drive():
    return Flight()
