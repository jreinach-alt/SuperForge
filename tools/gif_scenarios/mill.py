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

PERIODS = 1                     # one complete turn of the row table

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
ACC = _dp("US_TSC_ACC", "hall")

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

    `started` stays falsy through the boot and the fade-in ramp, so all of that
    is dropped lead-in — the recorder pays those frames and not their
    screenshots. The anchor also waits for the timebase accumulator to be back
    at zero, so the take opens at a repeatable point INSIDE a phase and not
    merely at a repeatable phase: TS_STEP publishes whole units and carries the
    remainder, so equal phase with unequal carry is a frame that will diverge.

    NO PRESS ANYWHERE. This rail has one scene, boots into it, and the only
    input it reads is the flat control the take deliberately leaves out.
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.mark = None        # the phase the take opened on
        self.periods = 0
        self.n = 0

    def __call__(self, r, i):
        self.n += 1
        if not self.started:
            if _at_rest(r) and _u16(r, ACC) == 0:
                self.started = True
                self.mark = _u16(r, SHOWN)
                self.n = 0
            return r.frame_step(STEP)

        if _u16(r, SHOWN) == self.mark:
            self.periods += 1
            self.done = self.periods >= PERIODS
        return r.frame_step(STEP)


def make_drive():
    return Drive()
