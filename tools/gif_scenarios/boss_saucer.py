"""boss_saucer — the Mode 7 scale axis, run as a boss fight.

THE WHOLE CYCLE, IN ORDER, and the clip is sized to hold exactly one of it:
the saucer grows in over the star field, settles at rest size, lunges (which
is the scale axis m7_affine does not have), telegraphs its beam and fires the
column, and — because the drive is shooting the entire time — breaks off,
recedes and dies. The result card holds over the live arena, the screen fades
out, and the arena re-arms behind the black.

THE LOOP POINT IS THE FADE, AND ON THIS RAIL IT IS THE REAL THING. `su_result`
runs `fade_start_out` and hands to RESET, whose timer outlasts the ramp so the
re-init lands at brightness 0; `su_reset` then re-arms `fade_start_in` and the
saucer is tiny again. So the fight already begins and ends on black, and this
take is bracketed to exactly that: the first kept capture is the last black
frame before the ramp arms, the last is the first black frame the ramp reaches.
A viewer sees the arena dissolve into darkness and dawn back out of it, which
is the same event either side of the join.

THE BOOT RAMP IS THE SAME RAMP, so the take runs the boot cycle rather than
skipping one to reach a RESET. `su_reset` re-arms the very routine the scene's
own init calls, from the same brightness 0, so the two openings are one event.
Measured on this binary: the first kept capture sits at fade level 1 of 15 —
the arena at 6% over a star field, which is the black the fade-out closes on.
The cycle is 254 captures, 12.7 s at 1:1, and CAPTURES is the ceiling over it.

THE DODGE IS THE CHOREOGRAPHY. The beam latches onto the player's lane at the
lunge apex, so the telegraph is a dodge window and standing in it is what
ignoring the window costs. This drive flips lanes on the telegraph's RISING
EDGE — read off US_BEAM_STATE, not counted to — so every beam in the clip is
a real dodge rather than a light show.

A IS HELD THROUGHOUT. Full gameplay speed, and it is also what makes the take
terminate: the HP drain is what turns the window into a whole fight instead of
a slice of one.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "boss_saucer"
CAPTURES = 300                  # a CEILING over the 254-capture cycle, not a
                                #   schedule: the fade ends the take.
SETTLE = 1                      # EMULATED frames — the boot ramp has not armed

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "sau" / "symbol_map.json").read_text())


def _dp(name, scene="arena"):
    pool = _J["scenes"][scene]["placements"] + _J["globals"]
    return next(p for p in pool if p["sym"] == name)["start"]


ST, BM, HP = (_dp(n) for n in ("US_B_STATE", "US_BEAM_STATE", "US_B_HP"))
FADE = _dp("ES_FADE_CTL")
BM_TELEGRAPH = 1                # sau_obj's own enum: 0 idle, 1 telegraph, 2 fire
SAU_ST_RESULT = 6               # saucer.inc: hold the card, then fade to RESET


def _u16(r, off):
    b = r.read_bytes(W, off, 2)
    return b[0] | (b[1] << 8)


def _black(r):
    """The fade has finished ramping and is sitting at brightness 0."""
    lvl, direction = r.read_bytes(W, FADE, 2)
    return lvl == 0 and direction == 0


class Fight:
    """One capture per call; A held, lanes flipped on the telegraph edge.

    The take CLOSES ON THE ROM: once the result card has been up, the next
    capture that finds the ramp finished at brightness 0 is the last one. The
    card is required first so the boot ramp's own brief black — armed before
    the scene has drawn anything — cannot end the take at capture zero.
    """

    def __init__(self):
        self.dir = "left"
        self.prev_beam = 0
        self.done = False
        self.seen_result = False

    def __call__(self, r, i):
        beam = _u16(r, BM)
        if beam == BM_TELEGRAPH and self.prev_beam != BM_TELEGRAPH:
            self.dir = "right" if self.dir == "left" else "left"
        self.prev_beam = beam
        if _u16(r, ST) == SAU_ST_RESULT:
            self.seen_result = True
        r.frame_step(STEP, a=True, **{self.dir: True})
        if self.seen_result and _black(r):
            self.done = True


def make_drive():
    return Fight()
