"""mode7_flight — the LEAD clip.

ONE CLOSED CIRCUIT, and every beat is one of this rail's axes:

    climb       R held to the CEILING CLAMP: the ground recedes, the horizon
                fills with world, the shadow goes small. Held past the clamp
                on purpose, so the end stop is in the clip
    level       back to the altitude it started on
    dive        L held to the FLOOR CLAMP: the ground comes up to meet the
                ship, features go large, the shadow is the big one
    level       ...and back again
    the turn    which is running under all four of them: the cloud band and
                the ground plane sweep at DIFFERENT rates, which is the
                parallax the factored pose buys, and turning while climbing
                and thrusting at once is the composition the whole
                S_a(k) * R(h) factoring exists for

THE LOOP POINT IS A CLOSED CIRCUIT, because this rail has no scene edge to
fade on: one scene, one continuous flight, nothing that returns to black
inside a sensible clip length. What it has instead is a pose that can be flown
back to. Under a held throttle at saturated speed and a held direction, the
heading sweeps at a constant 2 units per capture and the ship traces a CIRCLE
— so a full 256 units of heading brings the world position round with it, and
the clip rejoins itself on the same ground, at the same altitude, pointing the
same way. The take opens when the speed ramp has finished (the acceleration is
flown, not captured — a circle drawn while still accelerating is a spiral and
does not close) and closes on `(head - mark) % 256 == 0` with the altitude
back on its spawn index. Both are read off ES_M7F_POSE, not counted to.

THE ALTITUDE BEATS ARE STATE-DRIVEN, and they are symmetric on purpose:
index 80 is the ceiling and 0 is the floor, both clamps, so the drive holds R
until the ROM says 80 and L until it says 0, and each excursion is unwound
back to the spawn index 40 before the circuit closes. An altitude that did not
come back would leave the ground at a different scale across the join.

THROTTLE IS HELD FOR THE WHOLE TAKE. Full gameplay speed is the format rule,
and on a flight rail the throttle IS the speed — it is also what makes the
circle a circle rather than a spiral.

THE DAY/NIGHT CLOCK CANNOT COME ROUND, SO THE TAKE PICKS ITS HOUR. The clock
free-runs at 32 phase units a frame with 1,024 to the step and 64 steps to the
cycle, so a full revolution of the light is 2,048 frames — 34 s at 1:1, well
past what the 2 MB budget holds, and no clip inside the budget can close it.
What the clip CAN choose is where in the cycle it sits, because the palette is
a STEP function over four interpolated snapshots (dawn, day, dusk, night) and
the steps are not equally far apart. The circuit spans 12 of them, and across
the cycle that span costs between 1 and 21 units of zenith colour depending
only on which step it starts from: it is worst across day->dusk, where the sky
drops from (4,11,23) to (7,5,11), and best inside dawn->day, where step 8's
(5,9,20) meets step 20's (5,10,20).

So the take opens on the CLOCK as well as on the throttle — it waits out the
run-up until ES_M7F_CLOCK reads step 8, which is a bright morning sky and the
hour whose 12-step span very nearly closes. That run-up is long (the rail
boots on the `day` snapshot, so step 8 is most of a cycle away) and it is
flown, not photographed: the recorder pays a dropped capture's frame without
taking its picture. The poles are the still renders' job —
tools/shot_mode7_flight.py photographs both.

THE MOVING PALETTE IS THIS RAIL'S OWN CONTRIBUTION TO THE FORMAT. The take
holds well over a thousand distinct RGB values (HDMA rewrites CGRAM per
scanline, and the clock walks it), which is what surfaced the recorder's
shared-palette bug: a frame-0 palette plus the quantiser's default dither
turned the last third of this clip into orange noise AND blew the 2 MB budget.
The palette is built over the whole take with dither off — same contract
clause, four times closer to the picture. See quantize_take().
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "mode7_flight"
CAPTURES = 900                  # a CEILING over the circuit plus the run-up to
                                #   the hour: the heading closes the take.
SETTLE = 60                     # EMULATED frames — past the boot fade-in

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "m7f" / "symbol_map.json").read_text())


def _sym(name):
    return next(p for p in _J["scenes"]["sky"]["placements"]
                if p["sym"] == name)["start"]


_POSE = _sym("ES_M7F_POSE")
HEAD, ALTIDX, SPEED = _POSE + 8, _POSE + 10, _POSE + 12  # m7f_cam's offsets
CLOCK = _sym("ES_M7F_CLOCK")            # m7f_floor's free-running TOD phase

CEILING, FLOOR, SPAWN_ALT = 80, 0, 40   # M7F_ALT_MAXIDX, the floor, the spawn
TOD_SHIFT = 10                  # M7F_TOD_STEP = 1,024 phase units to a step
OPEN_STEP = 8                   # the hour whose 12-step span very nearly closes
TURN = dict(left=True)          # the circuit's one direction
THROTTLE = dict(b=True)


def _alt(r):
    return r.read_bytes(W, ALTIDX, 1)[0]


def _head(r):
    return r.read_bytes(W, HEAD, 1)[0]


def _speed(r):
    b = r.read_bytes(W, SPEED, 2)
    return b[0] | (b[1] << 8)


def _tod_step(r):
    b = r.read_bytes(W, CLOCK, 2)
    return ((b[0] | (b[1] << 8)) >> TOD_SHIFT) & 63


class Flight:
    """One capture per call; the beat it is in decides what is held.

    The take is bracketed by the pose: it opens when the throttle ramp has
    saturated, and closes when the heading has come the whole way round with
    the altitude back on its spawn index.
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.mark = None
        self.top = 0            # the saturating speed, as the ROM reports it
        self.phase = 0

    def _open(self, r):
        """Fly the acceleration and the hours; open on the saturated speed at
        the chosen step of the day/night clock."""
        spd = _speed(r)
        if spd > self.top:
            self.top = spd
            return                      # still accelerating: a spiral, not a circle
        if _tod_step(r) != OPEN_STEP:
            return                      # the right circle, the wrong hour
        self.started = True
        self.mark = _head(r)

    def _close(self, r):
        if (_head(r) - self.mark) % 256 == 0 and _alt(r) == SPAWN_ALT:
            self.done = True

    def __call__(self, r, i):
        if not self.started:
            r.frame_step(STEP, **TURN, **THROTTLE)
            self._open(r)
            return

        # THE PHASE ADVANCES BEFORE THE PAD IS CHOSEN, and that ordering is
        # load-bearing rather than tidy. The altitude index moves 2 a capture,
        # so a beat that picked its pad first and then noticed it had arrived
        # would hold the stick one capture too long and leave the ship at 42
        # or 38 — and the circuit closes on the altitude being back at exactly
        # its spawn index, which it would then never be.
        alt = _alt(r)
        if self.phase == 0 and alt >= CEILING:
            self.phase = 1
        elif self.phase == 1 and alt <= SPAWN_ALT:
            self.phase = 2
        elif self.phase == 2 and alt <= FLOOR:
            self.phase = 3
        elif self.phase == 3 and alt >= SPAWN_ALT:
            self.phase = 4

        pad = ({0: dict(r=True),        # climb to the ceiling clamp
                1: dict(l=True),        # ...and back to the spawn index
                2: dict(l=True),        # dive to the floor clamp
                3: dict(r=True)}        # ...and back again
               .get(self.phase, {}))    # 4: level, turning, until it closes

        r.frame_step(STEP, **pad, **TURN, **THROTTLE)
        if self.phase == 4:
            self._close(r)


def make_drive():
    return Flight()
