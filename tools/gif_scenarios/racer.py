"""racer — one flying lap of the circuit, from the green flag.

ONE CONTINUOUS TAKE: the standing start on the chequer, the ramp to the cap
with the speed bar lighting tick by tick, and a FULL LAP of the course —
the first corner off the long straight, the north straight, the S-complex's
two right-handers, the drop down the west side, the long 45-degree diagonal
(the streamer's worst case, rows and columns staged every frame, held for
152 tiles), the bottom straight through the chicane, and back across the
start/finish line at speed. The loop restart lands back on the standing
start, so the GIF reads as race after race.

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

from gen_racer_assets import COURSE                     # noqa: E402  the SSoT

ROM = "racer"
CAPTURES = 292                  # ramp + one lap + carrying speed across the
                                # line: 14.6 s at 1:1
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

    def __call__(self, r, i):
        for sub in range(STEP):
            err = self._decide(r)
            # the LAST stepped frame's pad is what the shot frame inherits,
            # so it only holds a turn when two more steps are wanted.
            want = abs(err) >= 2 if sub == STEP - 1 else err != 0
            r.frame_step(1, b=True,
                         left=want and err > 0, right=want and err < 0)


def make_drive():
    return Lap()
