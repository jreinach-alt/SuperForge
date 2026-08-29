"""mill — one 32-word row a frame, and every column moving on its own axis.

WHAT A VIEWER GETS is the machine hall running and nothing else: four bays of
pistons pumping vertically in their housings, each bay a quarter-cycle behind
the last, and between them four tread belts running sideways, two one way and
two the other. Every one of those motions is one word in a SINGLE row uploaded
once a frame. There is no camera, no player and no HDMA channel — 64 bytes a
frame is the whole cost of the picture.

AND THE TWO AXES IN ONE FRAME ARE THE POINT. Smelter's clip shows offset words
displacing columns; this one shows the half smelter cannot, because mode 2
fetches a word for EACH axis and mode 4 fetches one and reads BIT 15 of it. A
viewer who sees a piston rise and a belt run in the same 8-pixel neighbourhood
is looking at two adjacent words out of one 64-byte transfer, one of which has
bit 15 set.

NO INPUT IN THE WHOLE TAKE, and that is a first for this gallery. Every other
clip drives something; here the ROM boots into its one scene and the row table
is the performance. The recorder's own released-pad capture frame therefore
costs nothing at all — the cost it usually carries is horizontal travel a
player would have had (the smelter note), and nothing here is being driven.

THE FLAT CONTROL IS NOT IN THE TAKE, for the reason every rail before it kept
its control out: B swaps the transfer to the blob's 65th row — every value at
rest, every enable bit and every AXIS bit still set — and on a clip that loops
forever that reads as a BREAK rather than as a control
(reports/gallery_loop_seams.md). The pair is made where a pair belongs:
`tools/shot_mill.py` renders the running and flat frames side by side and
`tests/test_mill.py::test_the_flat_control_stills_every_column` asserts it.

THE LOOP POINT IS THE PHASE COMING BACK ROUND, AND IT WAS MEASURED. The picture
is a pure function of `ES_MIL_PHASE`: `mil_nmi_row` moves the blob's row
`phase` into BG3's map and nothing else varies. Driving this scenario's own
anchor and hashing decoded frames, the numbers are in `reports/mill_loop.md`
and PERIODS below closes the take on the return that measurement named.

WHY ONE TURN IS ALL THERE IS. The table closes on SMIL_PHASES = 64, and every
motion in it is periodic in that: the pistons' cosine, each bay's quarter-cycle
lag, and both belt directions complete a whole number of cycles. A viewer who
watches one turn has seen all the animation the rail has.
"""
import json
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

HALL = 0                        # the only scene, and the boot scene
SM_RUN = 0                      # scene_mgr's phase machine: 0 is "running"
FADE_FULL, FADE_IDLE = 15, 0    # fade.asm's own end stop and direction enum


def _u16(r, off):
    b = r.read_bytes(W, off, 2)
    return b[0] | (b[1] << 8)


def _at_rest(r):
    """The hall is running and no ramp is on screen — the fade idle at full."""
    sm = r.read_bytes(W, SM_CTL, 4)
    fd = r.read_bytes(W, FADE, 2)
    return (sm[0] == HALL and sm[2] == SM_RUN
            and fd[0] == FADE_FULL and fd[1] == FADE_IDLE)


class Drive:
    """One capture per call, each advancing STEP frames.

    THE TAKE IS THE RIDE, and it is a cutscene: it opens on the forge floor,
    the car climbs, the camera follows it until the world runs out, and then
    the car keeps going and leaves through the top. NO INPUT ANYWHERE — the
    scene drives itself, which is what a cutscene is.

    IT DOES NOT LOOP AND CANNOT. Every other clip in this gallery closes on the
    state it opened in; this one opens at the bottom of a shaft and ends with
    the lift gone. The seam is reported like any other and it is large, because
    the honest number for a sequence that goes somewhere is a large one
    (reports/gallery_loop_seams.md draws that line).
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.after = 0
        self.n = 0

    def __call__(self, r, i):
        self.n += 1
        if not self.started:
            if _at_rest(r) and _u16(r, ACC) == 0:
                self.started = True
                self.n = 0
            return r.frame_step(STEP)
        if _u16(r, CAR) >= CAR_TOP:
            self.after += 1
            self.done = self.after >= TAIL
        return r.frame_step(STEP)


def make_drive():
    return Drive()
