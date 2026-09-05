"""aurora — the card playing itself, one whole pass, black to black.

THE ROM DOES THE CHOREOGRAPHY, AND THAT IS THE POINT OF THIS ONE. Every other
scenario in this directory drives a rail: it presses a button, waits on a
state, presses another. There is nothing to press here. `aur_pres` is five
beats — black, a bare sky brightening, the pen and the rise together, the held
card, black again — so the drive holds no button at all and simply lets the
piece run. What it has to get right is not what to do but WHERE TO CUT.

THE LOOP POINT IS BLACK, WHICH MAKES IT EXACT WITHOUT BEING IDENTICAL. Passes
are deliberately NOT pixel-identical: the hue cursor is left running across the
reset, so each one rises in the colour the cycle has reached (docs/100 §14.6).
That would be a problem for any other loop point — the usual trick is to close
on a repeating phase, and there is no repeating phase here inside a take of
watchable length; the colour journey is 51 s and eight passes long. But the
fade-out reaches INIDISP level 0, and one black frame is the same black frame
whatever colour the aurora was a second earlier. So the take opens and closes
on black and the seam is invisible BY CONSTRUCTION rather than by measurement.

THE PERIOD IS NOT A WHOLE NUMBER OF CAPTURES, AND IT DOES NOT NEED TO BE.
The recorder captures every EVERY=3 emulated frames and the loop is **398**
(`tests/test_aurora.py::test_the_loop_closes_on_the_frame_it_should_and_keeps
_closing` asserts that on the ROM), so 133 captures overshoots by one frame.
On `lakeside` that would matter — its loop point is a moving wave, and landing
off it puts the surface in the wrong place. Here it cannot: the cut lands
inside a beat that is BLACK for about thirty frames (the ramp reaching level 0,
the whole reset drain at 26 frames, and the first frames of the next ramp
before it is visible), and one black frame is the same as another. So the take
is 133 captures, it overshoots the period by one frame, and the seam is
invisible for the same reason the loop point was chosen.

Retuning `AUR_PRES_HOLD` to make 399 was considered and rejected: it would have
moved a number the ROM's own test asserts, in order to satisfy the recorder,
for a seam that is already invisible.

B IS NOT PRESSED, and dropping it is the same choice `lakeside` and `heathaze`
made for the same reason. Freezing the piece is a real property of the rail —
`test_b_stops_the_whole_piece_and_not_merely_the_roll` holds it — but a held
still is a wholly static stretch of a clip that loops forever, and it reads as
the recording having broken rather than as a control. The claim is proved where
claims are proved.

WHAT THE CLIP SHOWS, and what it cannot. It shows the shape: the sky arriving
empty, the word writing itself in one continuous hand, the curtains climbing
out of the horizon, the card standing, the fade. It does NOT show the colour
travelling from cyan-teal to violet — that is 51 s and eight passes, and a take
that long is not a gallery clip. One pass covers about two of the sixteen
phases, so the aurora in this take is one colour band. The journey is asserted
in `test_each_pass_rises_in_a_colour_the_last_one_did_not` and rendered for a
human by the contact sheet, which is where a claim that needs a minute to state
belongs.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import EVERY, STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "aurora"

# The loop's period in frames, and what that is in captures. Asserted on the
# ROM by tests/test_aurora.py, not measured here — a clip is not the place to
# discover a rail's timing.
PERIOD_FRAMES = 398
# EVERY, not STEP: a capture is EVERY emulated frames, of which the drive
# advances STEP and take_screenshot pays the remaining one. Sizing this off
# STEP would ask for half again as many captures as a pass contains.
TAKE = PERIOD_FRAMES // EVERY + 1           # ...plus the frame it closes on

# `captures` IS A CEILING OVER THE LEAD-IN AND THE TAKE TOGETHER, not the take
# alone — `record_clip` runs `for i in range(captures)` and a dropped lead-in
# capture spends one of them. The drive opens on the SECOND entry into UP, so
# the lead-in is one whole pass: 398 frames, 133 captures. Sized as TAKE alone
# the first cut of this file recorded 113 dropped + 20 kept and closed the take
# mid-card — the seam check caught it immediately (first frame luma 0.1
# against a last of 7.0, which is a fade-to-black glued onto a lit sky).
CAPTURES = 2 * TAKE + 8                     # lead-in + take, with margin

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "aur" / "symbol_map.json").read_text())


def _dp(name, scene=None):
    pool = _J["scenes"][scene]["placements"] if scene else _J["globals"]
    return next(p for p in pool if p["sym"] == name)["start"]


# SCENE-SCOPED: the beat word belongs to the credits scene, which is the only
# scene this rail has. Read to find the CUT, never to decide the picture is
# right — the map-as-subject / oracle distinction test_lakeside.py draws.
PST = _dp("ES_AUR_PST", "credits")
P_UP = 0                    # the first beat: black, starting to brighten


def _u16(r, addr):
    return int.from_bytes(r.read_bytes(W, addr, 2), "little")


class Drive:
    """Wait for the top of a pass, then take exactly one period of it.

    The take opens on the frame the piece re-enters UP — the darkest frame
    there is, INIDISP at 0 with the ramp about to start — so the first and last
    captures are the same black and the loop is seamless without the two
    pictures having to be equal anywhere else.
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.n = 0
        self.was = None

    def __call__(self, r, i):
        beat = _u16(r, PST)
        if not self.started:
            # The EDGE into UP, not the state: booting already sits in UP, and
            # opening there would take the boot's own fade rather than a loop's.
            if self.was is not None and beat == P_UP and self.was != P_UP:
                self.started = True
                self.n = 0
            self.was = beat
            return r.frame_step(STEP)
        self.n += 1
        self.done = self.n >= TAKE      # TAKE, not CAPTURES: the latter is
                                        #   the ceiling and includes the lead-in
        return r.frame_step(STEP)


def make_drive():
    return Drive()
