"""split_h_2p_demo — two Mode 7 cameras over one plane, and a cast in both.

ONE CLAIM, AND IT IS A MOTION CLAIM. The top 112 scanlines and the bottom 112
are two INDEPENDENT cameras on the same checker world, streaming ROM-resident
per-scanline poses straight through indirect HDMA — no live perspective solve
anywhere — with 24 markers projected into BOTH bands every frame. A still shows
two floors; only a clip shows them turning opposite ways, at their own
positions, with the swarm walking through both.

THE HANDS-OFF ARM. The shipping ROM's cameras stand still until a pad moves
them, which is the wrong build to record: a clip driven by a script would be a
clip of the script. `-D SH2_AUTOCAM` is the build whose subject IS the
autonomous camera model — the same rotate-and-drive under the ROM's own
authority — so that is the image this records, exactly as its own test module
reads it.

NO DRIVE AT ALL, therefore, and that is the point rather than a shortcut. Every
beat below is a POLL of the ROM's state; the pad is never touched, because on
this build it does nothing.

THE LOOP POINT IS THE SEEDED CAMERA POSE, and it closes by arithmetic rather
than by luck. Each frame steps camera 1's heading +1 and camera 2's -1 through
a 256-entry pose set, and drives both forward along the heading through the
move LUT. The LUT is a circle: over one full turn the 256 forward vectors sum
to exactly zero on both axes, and the 8.8 fraction accumulators come back with
them — so the WHOLE camera state is a pure function of (frames since enter) mod
256, and heading 0 is the pose `enter` seeded. A take that is a whole number of
turns long therefore rejoins its own first frame on the floors exactly.

TWO PERIODS HAVE TO AGREE, and this is what sets the length. The clip samples
every third emulated frame, so the mark can only be recaptured after a whole
number of turns that is also a whole number of captures; 3 and 256 are coprime,
so the first return is 768 frames — three full turns, 256 capture intervals,
12.8 s at 1:1. That is not a budget choice and cannot be shortened: a take half
that long would rejoin half a turn out and both floors would jump.

CLOSING ON THE MARK, NOT ONE CAPTURE SHORT OF IT — the gallery's convention,
and it is worth stating because the other reading is defensible and measurably
worse. The seam is read between the take's LAST frame and its FIRST, so those
two have to be the same instant of the ROM; a take that stops one interval
early rejoins correctly in TIME but is measured three frames out of register,
and this rail says so loudly — measured on both cuts of this very take, mad
13.55 with 28.7% of the picture past 16, against 2.89 and 1.9% for the same
take closed on the mark.

WHAT DOES NOT COME ROUND is the swarm. The 22 followers steer toward waypoint
loops whose periods share nothing with 256, so the markers are wherever the AI
has walked them, and they are the whole of this clip's seam residual. The floors
— which are the rail's subject — register exactly.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import EVERY, STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

# THE AUTONOMOUS BUILD, not the shipping one. The rail's own test module reads
# this same image for every claim about rotation and drive.
#
# `make sh2-variants` builds it — the dispatcher's "run `make <rail>`" hint is
# the generic one and does not reach a `-D` image, which is worth naming here
# because this is the only scenario in the set whose ROM is not its rail's.
ROM = "sh2_autocam"

# A CEILING, not a schedule: `done` closes the take. The lead-in can be up to
# one whole turn of dropped captures (the mark comes round once every 256), so
# the ceiling is that plus the take itself, plus slack.
CAPTURES = 560
SETTLE = 60                     # EMULATED frames — the fade-in has run

TURNS = EVERY                   # capture intervals per turn -> whole captures
POSES = 256                     # headings in the set (sh2_cam's SH2_POSES)
MARK = 0                        # camera 1's seeded heading — the loop point
# ...so the mark recurs on the capture grid every TURNS turns, and the take is
# that many intervals plus the closing frame that repeats the mark.
TAKE = TURNS * POSES // EVERY + 1
assert (EVERY * (TAKE - 1)) % POSES == 0, "the take is not a whole turn count"

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "sh2" / "symbol_map.json").read_text())


def _sym(n):
    for p in _J["scenes"]["split"]["placements"] + _J["globals"]:
        if p["sym"] == n:
            return p["start"]
    raise KeyError(f"{n} not in the emitted map — did the allocator move it?")


ROT, POS, FADE = (_sym(n) for n in ("ES_SH2_ROT", "ES_SH2_POS", "ES_FADE_CTL"))
FADE_IDLE, FADE_FULL = 0, 15


def _heading(r, cam=0):
    """Camera 1's or 2's heading, 0..255 — sh2_cam's SH2_H1 / SH2_H2."""
    return r.read_u16(W, ROT + cam * 2) & (POSES - 1)


def _lit(r):
    """The fade has finished lifting the blank: full brightness, not ramping."""
    b = r.read_bytes(W, FADE, 2)
    return b[0] == FADE_FULL and b[1] == FADE_IDLE


class Split2P:
    """One capture per call. Both ends of the take are ROM state, not counts."""

    def __init__(self):
        self.started = False
        self.done = False

    def __call__(self, r, i):
        r.frame_step(STEP)
        if not self.started:
            # OPEN on the seeded pose, once the picture is lit. `_heading` is
            # the whole camera state on this build — position and both 8.8
            # fractions are functions of the same frame count — so this one
            # word identifies the instant the take has to come back to.
            self.started = _lit(r) and _heading(r) == MARK
            return
        # CLOSE ON THE MARK COMING ROUND — the same instant the take opened on,
        # so the join the seam metric reads is between two frames the ROM drew
        # from the same camera state. (MARK + EVERY*k) % POSES == MARK first
        # holds again at k = TAKE - 1, which is the take's own length asserted
        # by the ROM's state rather than counted to.
        self.done = _heading(r) == MARK


def make_drive():
    return Split2P()
