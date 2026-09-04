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

THE TAKE CLOSES, AND WHAT CLOSES IT IS THE RAIL'S OWN CYCLE. The picture was
once a pure function of `ES_MIL_PHASE` and closed on the phase coming back
round (`reports/mill_loop.md`); it is a function of the phase AND the camera
now, and for two commits this paragraph said the take was therefore a journey
that ended with the car gone through the top and reported a large seam. That
stopped being true when the climb started handing back to the lobby: the
recorded take is lobby -> doors -> hall -> climb -> lobby, and the measured
seam is 0.00/255 with the first and last frames byte-identical. Which is the
honest outcome either way — reports/gallery_loop_seams.md draws the line that a
sequence going somewhere reports its seam rather than faking a small one, and
this one has no seam to fake.
"""
import json
import re
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "mill"
CAPTURES = 260                  # a CEILING over the lead-in trip and the take,
                                #   not a schedule: the cycle closing is what
                                #   ends it. One trip measures ~360 emulated
                                #   frames, so two is ~240 captures at STEP 3.

# THE TAKE IS A CLIMB, not a turn of the animation. The world is two screens
# tall and the camera goes up it and back, because the question the clip has to
# answer is what a PER-COLUMN table does while the whole picture scrolls —
# every column driven by a word, and every column that is not, keeping step.
#
# THE SEAM CANNOT BE ZERO HERE AND THE ARITHMETIC SAYS WHY. The picture is a
# function of two things now, the phase and the camera, and their periods share
# no factor: the camera's round trip is 2 * SMIL_CAM_MAX / SMIL_CAM_STEP frames
# (THREE DEAD CONSTANTS lived here — CAR_TOP, TAIL and a CAM_MAX the comment
# said was "asserted below rather than trusted", which nothing asserted and
# which had gone stale at 224 against a generator that says 288. The drive
# waits on the ROM's own state and never read any of them.)
# and the phase's is SMIL_PHASES / 0.375. The take closes where the CAMERA
# closes, at the bottom of the world, with the machines at a different point in
# their stroke than they opened on. That is a loop of a MOVE, and the measured
# seam is the honest number for one.

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


# ONE TRIP, AS DATA, RUN TWICE. (name, pad held, done-when, stall budget in
# captures.) The first pass is the lead-in and the recorder drops it; the
# second is the take. Everything waits on the ROM's own state — a fixed plan
# drifts against the ROM's tick and films a plausible clip of the wrong thing.
TRIP = (
    ("the lobby settles", {}, lambda r: _at_rest(r, LOBBY), 150),
    ("cross to the far bay", {"right": True},
     lambda r: _u16(r, DOOR + 2) >= DOOR_TRAVEL, 200),
    ("board", {"up": True}, lambda r: _scene(r) == HALL, 200),
    ("the hall settles", {}, lambda r: _at_rest(r, HALL), 200),
    ("start the climb", {"up": True}, lambda r: _u16(r, CAR) > 0, 200),
    ("ride to the top", {}, lambda r: _scene(r) == LOBBY, 400),
    ("arrive", {}, lambda r: _at_rest(r, LOBBY), 200),
)


class Drive:
    """One capture per call, each advancing STEP frames.

    IT LOOPS, AND THE LOOP POINT IS A ROOM THE MACHINES ARE NOT IN. The take
    is one whole round trip — the doors part to reveal him where the lift set
    him down, he crosses the lobby, boards the other bay, rides the shaft past
    the pistons and the belts, and is set down again behind shut doors. Driven
    three times and measured, that cycle is 348 emulated frames to the frame
    and settles at the same px with both bays shut, so the take can open and
    close on it.

    THE SEAM IS IN THE LOBBY FOR A REASON. The picture in the hall is a
    function of the phase, the camera AND the car, and those periods share no
    factor — a take that closed there could only report a large seam honestly
    (reports/gallery_loop_seams.md). The lobby has none of them on screen: the
    wall is static art, the doors are shut and he is behind them, so the two
    ends of the cycle are the same picture rather than merely a similar one.

    THE LEAD-IN IS A WHOLE TRIP AND IT IS DROPPED. The ROM boots into the
    middle of the lobby, which is NOT on the cycle — he has never ridden, so
    no bay has set him down. So the drive runs the trip once to reach the
    cycle, sets `.started` there, and runs it again for the take.
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.step = 0
        self.held = 0
        self.lap = 0

    def __call__(self, r, i):
        name, pad, ready, budget = TRIP[self.step]
        self.held += 1
        if self.held > budget:
            raise Stalled(f"mill: '{name}' (lap {self.lap}) did not finish in "
                          f"{budget} captures — the choreography no longer "
                          f"matches the ROM")
        if ready(r):
            self.step += 1
            self.held = 0
            if self.step == len(TRIP):
                self.step = 0
                self.lap += 1
                if self.lap == 1:
                    self.started = True      # ...the stored take opens HERE
                else:
                    self.done = True         # ...and closes one cycle later
        return r.frame_step(STEP, **pad)


def make_drive():
    return Drive()
