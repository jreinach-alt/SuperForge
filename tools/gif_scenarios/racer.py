"""racer — one flying lap of the circuit, at the cap the whole way round.

ONE CONTINUOUS TAKE, AND IT OPENS AT RACING SPEED: a FULL LAP of the course
from a mark on the start/finish straight — the first corner off the long
straight, the north straight, the S-complex's two right-handers, the drop
down the west side, the long 45-degree diagonal (the streamer's worst case,
rows and columns staged every frame, held for 152 tiles), the bottom
straight through the chicane, and back onto the mark carrying the same
speed. The standing start and its ramp to the cap are FLOWN, not
photographed: they are the shape the loop cannot hold, because a take that
opens at rest on the chequer and closes at 15 px a frame rejoins a lit
speed bar to a dark one and a screen-filling chequer to open road.

THE LOOP POINT IS A MARK ON THE HOME STRAIGHT, LOOP_AHEAD px north of the
chequer, and the offset is the picture. The Mode-7 floor magnifies the near
rows about 3.3 screen px per world px, so anything the join does not
register lands hardest at the bottom of the frame — and the chequer is the
one high-frequency thing on this circuit, five tiles of black and white
across the whole road. Closing ON it costs mad 97.6 for the same 8 px of
along-track error that costs 2.48 here, where the near field is plain road.

THE HOUR IS WAITED FOR ON THE GRID. The day-night wash steps through eight
COLDATA keyframes on a 480-frame cycle and the lap is 780 frames, so no lap
count closes the clock and the two ends of the take carry the same wash only
if the take opens at the right point in the cycle. The kart holds the grid
with the engine off until the clock reaches it — a dropped capture costs the
take nothing and the kart does not move — and the mark is then reached, and
reached again a lap later, on one keyframe. Measured: the sky band
contributes ZERO pixels to the seam.

THE RESIDUAL IS 8 px OF ALONG-TRACK LATTICE, and it is a property of the
racing line rather than of the cut. A capture is three emulated frames = 45
px at the cap, and the drive's own line is a TWO-lap limit cycle: successive
crossings of the mark land 8 px apart and every second one lands on the
same pixel. So a one-lap take cannot register the floor exactly, and what
those 8 px move is the textured part of it — the grass checker beyond the
kerbs and the centre-line dashes, both in the far and middle bands. The sky
and the near road come back exactly.

THE DRIVE IS THE COURSE, READ FROM THE ROM. Every beat here is
position-shaped, so per the __init__ rule nothing counts frames to a
corner: the drive reads the camera's world position and heading from WRAM
each frame and steers leg to leg around gen_racer_assets.COURSE — the
generator's own vertex list, so the choreography follows the painted road
by construction rather than by a parallel copy of it. A corner beat starts
when the ROM's own position enters the corner's lead window (LEAD px from
the vertex), and the steer holds until the ROM's heading reads the new
leg's bearing. Full throttle the whole take — the format rule, and the
point: the course and the handling are tuned so a flat-out lap is
road-holdable, and this clip is that claim recorded (the probe band is
wide: every lead from 48 to 96 px laps clean, with zero grass and zero
kerb frames; LEAD sits in the middle of it).

THE SUB-CAPTURE PATTERN IS THE STEERING'S RESOLUTION. A capture is three
emulated frames — two the drive steps, one the screenshot pays — and the
pad state the shot frame inherits is whatever the second step held. Turning
exactly onto a bearing therefore decides per FRAME, not per capture: the
second step only holds a turn when at least two more heading steps are
wanted, so the inherited shot frame cannot overshoot the bearing and the
straights stay wobble-free.
"""
import json
import sys
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from gen_racer_assets import (COURSE, KEYS, START_TY,   # noqa: E402  the SSoT
                              TOD_HOLD, TOD_STEP)

ROM = "racer"
CAPTURES = 700                  # a CEILING over the grid wait and the out lap
                                # as well as the take: the MARK closes it, and
                                # the kept lap is 261 captures — 13.1 s at 1:1
SETTLE = 90                     # EMULATED frames — fade-in + song load done
                                # (the test module's BOOT frame)

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "rc" / "symbol_map.json").read_text())


def _sym(name):
    for p in _J["scenes"]["race"]["placements"]:
        if p["sym"] == name:
            return p["start"]
    raise KeyError(f"{name} not in the emitted racer map")


M7ORG, HEAD = _sym("ES_M7ORG"), _sym("US_HEADING")
TOD_PH, TOD_T = _sym("US_TOD_PH"), _sym("US_TOD_T")
LINE_PY = START_TY * 8 + 4      # the start/finish chequer's mid-road pixel row
                                # — the generator's own START_TY, which is
                                # world.inc's CAM0_PY by construction
LOOP_AHEAD = 320                # the mark, north of the chequer. Far enough
                                # that the chequer is out of shot; MEASURED
                                # against its neighbours on the 45 px capture
                                # lattice, which read 2.97 (+32) and 3.76 (+64)
LOOP_PY = LINE_PY - LOOP_AHEAD

# Leg bearings in pose units (64 per revolution, LEFT increments): leg i runs
# COURSE[i] -> COURSE[i+1]; the take opens on leg 15, the start/finish
# straight, heading north — world.inc's CAM0. Each record carries the leg's
# MIDPOINT and its half-length in along-projection units: every positional
# read below folds the 4096 px torus to +/-2048, and the home straight is
# 2,368 px — longer than the fold — so deltas are taken from the midpoint,
# where half a leg plus the lead window always fits.
_DIR_H = {(0, -1): 0, (-1, -1): 8, (-1, 0): 16, (-1, 1): 24,
          (0, 1): 32, (1, 1): 40, (1, 0): 48, (1, -1): 56}
LEGS = []
for _i in range(len(COURSE)):
    _x0, _y0 = COURSE[_i]
    _x1, _y1 = COURSE[(_i + 1) % len(COURSE)]
    _d = ((_x1 > _x0) - (_x1 < _x0), (_y1 > _y0) - (_y1 < _y0))
    _mx, _my = (_x0 + _x1) * 4 + 4, (_y0 + _y1) * 4 + 4   # midpoint, px
    _half = (abs(_x1 - _x0) + abs(_y1 - _y0)) * 4         # half-len, along units
    LEGS.append((_DIR_H[_d], (_mx, _my), _half))

LEAD = 72                       # along-track px before the vertex where the
                                # turn-in starts (r*tan(22.5deg) ~ 63 for the
                                # full-speed circle, plus decision latency)
START_LEG = 15                  # the east straight, heading north

# The unit travel direction per leg, for the along/cross decomposition.
_DIRS = {h: d for d, h in _DIR_H.items()}
_ISQ2_Q14 = 11585               # 2**14 / sqrt(2), gen_m7_assets' constant


def _sdelta(a, b):
    """Signed torus delta a - b, folded to -2048..2047."""
    return ((a - b + 2048) % 4096) - 2048


# --- the day-night clock, and the hour the take is launched from -------------
# race.asm's tod_tick is a four-phase machine over the generator's constants:
# two TOD_HOLD frames of held endpoint either side of two blends that step one
# keyframe every TOD_STEP frames, the last step arriving as the next hold's
# snap. So the cycle is a STEP function of one number — the frames since the
# day hold began — and two moments carry the same wash exactly when that
# function returns the same keyframe for both.
TOD_BLEND = (KEYS - 1) * TOD_STEP           # 112 frames of blend
TOD_CYCLE = 2 * (TOD_HOLD + TOD_BLEND)      # 480 frames of day and night
_PH_BASE = (TOD_HOLD, TOD_HOLD + TOD_BLEND,
            2 * TOD_HOLD + TOD_BLEND, TOD_CYCLE)


def _key_at(p):
    """The gradient keyframe showing at cycle position p."""
    p %= TOD_CYCLE
    if p < TOD_HOLD:
        return 0                                        # the day hold
    p -= TOD_HOLD
    if p < TOD_BLEND:
        return min(p // TOD_STEP, KEYS - 1)             # dimming toward night
    p -= TOD_BLEND
    if p < TOD_HOLD:
        return KEYS - 1                                 # the night hold
    return KEYS - 1 - min((p - TOD_HOLD) // TOD_STEP, KEYS - 1)


def _tod_p(r):
    """Cycle position, read out of the ROM's own phase and countdown."""
    return (_PH_BASE[r.read_bytes(W, TOD_PH, 1)[0]]
            - int.from_bytes(r.read_bytes(W, TOD_T, 2), "little")) % TOD_CYCLE


OUT_FRAMES = 877                # MEASURED on build/racer.sfc: the green flag
                                # to the mark, at the cap
LAP_FRAMES = 780                # MEASURED: the flying lap, mark to mark
# The launch positions worth holding the grid for: the ones from which the
# mark, and the mark a lap later, both sit on ONE keyframe. Two windows of
# four frames qualify; the take takes the brighter.
_HOURS = tuple(p for p in range(TOD_CYCLE)
               if _key_at(p + OUT_FRAMES) == _key_at(p + OUT_FRAMES + LAP_FRAMES))
OPEN_KEY = min(_key_at(p + OUT_FRAMES) for p in _HOURS)
GRID = frozenset(p for p in _HOURS if _key_at(p + OUT_FRAMES) == OPEN_KEY)


class Lap:
    """Steer leg to leg around COURSE, deciding once per emulated frame.

    Two terms, both read back from the ROM each frame. ALONG-track: the leg
    advances when the remaining distance to its end vertex — the projection
    onto the leg's own direction, so a lateral offset cannot mask it — is
    inside LEAD. CROSS-track: the held bearing bends one pose step toward
    the centre line outside a 16 px deadband and two outside 48 px, so a
    corner exit's leftover offset closes gently on the next straight
    instead of riding it end to end."""

    def __init__(self):
        self.leg = START_LEG
        self.rolling = False    # the green flag has dropped
        self.started = False    # the take has opened — the mark, at speed
        self.done = False       # ...and closed — the mark, a lap later
        self.armed = False
        self.prev_y = None

    def _metrics(self, x, y, leg):
        """(remaining true px to the leg's end, cross-track true px)."""
        tgt, (mx, my), half = LEGS[leg]
        sx, sy = _DIRS[tgt]
        dx, dy = _sdelta(x, mx), _sdelta(y, my)
        rem = half - (sx * dx + sy * dy)
        cross = dx * sy - dy * sx
        if sx != 0 and sy != 0:
            rem = (rem * _ISQ2_Q14) >> 14
            cross = (cross * _ISQ2_Q14) >> 14
        return rem, cross

    def _decide(self, r):
        x = int.from_bytes(r.read_bytes(W, M7ORG, 2), "little")
        y = int.from_bytes(r.read_bytes(W, M7ORG + 2, 2), "little")
        h = r.read_bytes(W, HEAD, 1)[0]
        rem, cross = self._metrics(x, y, self.leg)
        if rem <= LEAD:
            self.leg = (self.leg + 1) % len(LEGS)
            _, cross = self._metrics(x, y, self.leg)
        # cross-track: displacement toward the travel direction's LEFT is
        # positive, so a positive error steers RIGHT (h decrements).
        bend = (cross > 16) + (cross > 48) - (cross < -16) - (cross < -48)
        err = (LEGS[self.leg][0] - bend - h) % 64
        return err - 64 if err > 32 else err

    def _loop_point(self, r):
        """True on the capture the kart reaches the loop point — ONCE A LAP.

        The green flag is on the far side of it, so the mark is armed by
        leaving the home straight and disarmed by passing it: what counts is
        a crossing that arrives having been round the course, and the leg
        the steering already tracks says which."""
        y = int.from_bytes(r.read_bytes(W, M7ORG + 2, 2), "little")
        if self.leg != START_LEG:
            self.armed = True
        crossed = (self.armed and self.prev_y is not None
                   and self.prev_y > LOOP_PY >= y)
        self.armed = self.armed and not crossed
        self.prev_y = y
        return crossed

    def __call__(self, r, i):
        if not self.rolling:
            # ON THE GRID, ENGINE OFF, WAITING FOR THE HOUR. The kart holds
            # CAM0 whatever the clock does, so waiting here costs the take
            # nothing but a dropped capture and buys the one launch position
            # from which both ends of the flying lap carry the same wash.
            r.frame_step(STEP)
            self.rolling = _tod_p(r) in GRID
            return

        for sub in range(STEP):
            err = self._decide(r)
            # the LAST stepped frame's pad is what the shot frame inherits,
            # so it only holds a turn when two more steps are wanted.
            want = abs(err) >= 2 if sub == STEP - 1 else err != 0
            r.frame_step(1, b=True,
                         left=want and err > 0, right=want and err < 0)

        if self._loop_point(r):
            self.done = self.started        # the second crossing closes it
            self.started = True             # ...the first opens it


def make_drive():
    return Lap()
