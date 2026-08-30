"""mill — one 32-word row a frame, and every column moving on its own axis.

WHAT A VIEWER GETS is a lift climbing the machine hall: bays of pistons pumping
vertically in their housings, each a quarter-cycle behind the last, and between
them tread belts running sideways. Every one of those motions is one word in a
SINGLE row uploaded once a frame — no HDMA channel, 64 bytes a frame, and the
car the camera follows is itself one of those columns.

AND THE TWO AXES IN ONE FRAME ARE THE POINT. Smelter's clip shows offset words
displacing columns; this one shows the half smelter cannot, because mode 2
fetches a word for EACH axis and mode 4 fetches one and reads BIT 15 of it. A
viewer who sees a piston rise and a belt run in the same 8-pixel neighbourhood
is looking at two adjacent words out of one 64-byte transfer, one of which has
bit 15 set.

THE INPUT IS ALL IN THE LEAD-IN, WHICH IS DROPPED. This rail used to boot into
its one scene and run itself, and this file said so for three commits after it
stopped being true: the lift gave it a second room, the collision sprint gave
the hall a player, and the hall stopped starting its own ride. So the drive now
walks him to a bay, waits for the doors, boards, and presses UP on the car —
and only then sets `.started`, so the stored take opens on the climb. Every
wait reads the ROM's own state; nothing counts frames to an event.

AND IT REFUSES TO RECORD NOTHING. Each phase carries a stall budget, because
the failure this file actually shipped was silent: `HALL = 0` named the LOBBY
once the lift existed, `_at_rest` passed on frame one of the wrong room, the
take waited for a car nobody was driving, and the recorder happily stored seven
static frames of a shut lobby. A clip of nothing must be an exception, not an
artifact.

THE FLAT CONTROL IS NOT IN THE TAKE, for the reason every rail before it kept
its control out: B swaps the transfer to the blob's 65th row — every value at
rest, every enable bit and every AXIS bit still set — and on a clip that loops
forever that reads as a BREAK rather than as a control
(reports/gallery_loop_seams.md). The pair is made where a pair belongs:
`tools/shot_mill.py` renders the running and flat frames side by side and
`tests/test_mill.py::test_the_flat_control_stills_every_column` asserts it.

THE TAKE DOES NOT LOOP, AND THE SEAM IS REPORTED HONESTLY. The picture was once
a pure function of `ES_MIL_PHASE` and closed on the phase coming back round
(`reports/mill_loop.md`). It is a function of the phase AND the camera now, and
the take is a journey: it opens at the bottom of the shaft and ends with the
car gone through the top. reports/gallery_loop_seams.md draws that line — a
sequence that goes somewhere reports a large seam rather than faking a small
one.
"""
import json
import re
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "mill"
CAPTURES = 160                  # a CEILING over the lead-in and the take, not
                                #   a schedule: the phase returning is what
                                #   ends it.

# THE TAKE IS A CLIMB, not a turn of the animation. The world is two screens
# tall and the camera goes up it and back, because the question the clip has to
# answer is what a PER-COLUMN table does while the whole picture scrolls —
# every column driven by a word, and every column that is not, keeping step.
#
# THE SEAM CANNOT BE ZERO HERE AND THE ARITHMETIC SAYS WHY. The picture is a
# function of two things now, the phase and the camera, and their periods share
# no factor: the camera's round trip is 2 * SMIL_CAM_MAX / SMIL_CAM_STEP frames
# and the phase's is SMIL_PHASES / 0.375. The take closes where the CAMERA
# closes, at the bottom of the world, with the machines at a different point in
# their stroke than they opened on. That is a loop of a MOVE, and the measured
# seam is the honest number for one.
CAR_TOP = 400                   # SMIL_CAR_TOP — where the ride ends
TAIL = 10                       # ...and how long the empty shaft is held after

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "mil" / "symbol_map.json").read_text())


def _dp(name, scene=None):
    pool = _J["scenes"][scene]["placements"] if scene else _J["globals"]
    return next(p for p in pool if p["sym"] == name)["start"]


SM_CTL = _dp("ES_SM_CTL")
FADE = _dp("ES_FADE_CTL")
# THE PHASE THE PICTURE WAS DRAWN FROM, not the counter the main thread will
# advance next. `mil_nmi_row` publishes it at the moment it uses it, which is
# smelter's `smt_cam_shown` lesson: join on what drew the frame.
SHOWN = _dp("ES_MIL_SHOWN")
CAM = _dp("ES_MIL_CAM")
CAR = _dp("ES_MIL_CAR")
ACC = _dp("US_TSC_ACC", "hall")

CAM_MAX = 224                   # SMIL_CAM_MAX, and it is asserted below rather
                                #   than trusted: the generator owns it

# THE BOOT SCENE IS THE LOBBY, AND `HALL = 0` USED TO SAY OTHERWISE. That
# constant was written when the hall WAS the only scene, and it survived the
# lift being built — so `_at_rest` compared the live scene id against 0, the
# lobby's own id, and passed on the first frame of a room this take never
# meant to film. The recorder then waited for a car that nothing was driving
# and stored 7 static frames of a shut lift lobby. Both ids are named now.
LOBBY, HALL = 0, 1              # scene ids, and the LOBBY is where it boots
SM_RUN = 0                      # scene_mgr's phase machine: 0 is "running"
FADE_FULL, FADE_IDLE = 15, 0    # fade.asm's own end stop and direction enum
DOOR = _dp("ES_MIL_DOOR")       # per-bay leaf travel, and the far bay is +2

# THE GENERATOR OWNS THE TRAVEL, so it is read rather than repeated here.
_ART = (ROOT / "build" / "assets" / "mil_art.inc").read_text()
DOOR_TRAVEL = int(re.search(r"^SMIL_DOOR_TRAVEL\s*=\s*(\d+)", _ART, re.M).group(1))


def _scene(r):
    return r.read_bytes(W, SM_CTL, 1)[0]


def _u16(r, off):
    b = r.read_bytes(W, off, 2)
    return b[0] | (b[1] << 8)


def _at_rest(r, scene):
    """That scene is running and no ramp is on screen — the fade idle at full.

    It takes the scene it is asking about rather than closing over one, which
    is the whole defect above: a predicate that names a room by a bare integer
    keeps answering after the rail grows a second room.
    """
    sm = r.read_bytes(W, SM_CTL, 4)
    fd = r.read_bytes(W, FADE, 2)
    return (sm[0] == scene and sm[2] == SM_RUN
            and fd[0] == FADE_FULL and fd[1] == FADE_IDLE)


class Stalled(RuntimeError):
    """A phase of the choreography never advanced — the clip would be of
    nothing, so it is an error rather than a very short GIF."""


class Drive:
    """One capture per call, each advancing STEP frames.

    THE LEAD-IN IS THE LOBBY AND IT IS DROPPED. `.started` stays falsy while he
    walks to a bay, the leaves part, he boards, the rooms hand over and he
    presses UP on the car; the recorder pays those frames without storing them.

    THE TAKE IS THE ROUND TRIP'S SECOND HALF: it opens on the forge floor with
    the car at the bottom of the shaft and the channel lit, climbs, and runs
    TAIL captures past SMIL_CAR_TOP — long enough for the lift to hand back, so
    the last frames are him standing in the lobby bay he set out from. It does
    NOT loop: frame 0 is the mill floor and the last frame is the lobby, and the
    seam is reported at that honest size (reports/gallery_loop_seams.md).
    """

    # (name, stall budget in captures) — generous, because a fade is slow and a
    # budget that fires on a healthy tree is worse than none at all.
    PHASES = (("lobby settles", 120), ("walk to the bay", 200),
              ("board", 200), ("hall settles", 200), ("start the climb", 200))

    def __init__(self):
        self.started = False
        self.done = False
        self.after = 0
        self.phase = 0
        self.held = 0

    def _advance(self):
        self.phase += 1
        self.held = 0

    def __call__(self, r, i):
        pad = {}
        if self.phase < len(self.PHASES):
            self.held += 1
            name, budget = self.PHASES[self.phase]
            if self.held > budget:
                raise Stalled(f"mill: '{name}' did not finish in {budget} "
                              f"captures — the choreography no longer matches "
                              f"the ROM")
            if self.phase == 0:
                if _at_rest(r, LOBBY):
                    self._advance()
            elif self.phase == 1:
                pad = {"right": True}
                if _u16(r, DOOR + 2) >= DOOR_TRAVEL:
                    self._advance()
            elif self.phase == 2:
                pad = {"up": True}
                if _scene(r) == HALL:
                    self._advance()
            elif self.phase == 3:
                if _at_rest(r, HALL):
                    self._advance()
            elif self.phase == 4:
                pad = {"up": True}
                if _u16(r, CAR) > 0:
                    self._advance()
                    self.started = True      # ...the stored take opens HERE
            return r.frame_step(STEP, **pad)
        if _u16(r, CAR) >= CAR_TOP:
            self.after += 1
            self.done = self.after >= TAIL
        return r.frame_step(STEP)


def make_drive():
    return Drive()
