"""boss_saucer — the Mode 7 scale axis, run as a boss fight.

THE WHOLE CYCLE, IN ORDER, and the clip is sized to hold it: the saucer grows
in over the star field, settles at rest size, lunges (which is the scale axis
m7_affine does not have, four times a fight), telegraphs its beam and fires
the column, and — because the drive is shooting the entire time — breaks off,
recedes and dies. Measured timeline on this binary, holding A: REVEAL frame 3,
HOLD 62, FIGHT 107, first lunge 147, first beam telegraph 192, beam fire 215,
then two more cycles, DEATH 582.

THE DODGE IS THE CHOREOGRAPHY. The beam latches onto the player's lane at the
lunge apex, so the telegraph is a dodge window and standing in it is what
ignoring the window costs. This drive flips lanes on the telegraph's RISING
EDGE — read off US_BEAM_STATE, not counted to — so every beam in the clip is
a real dodge rather than a light show. Holding one direction for ten seconds
would be the "gentle showcase input" the format warns about from the other
side: nothing wrong with the frame rate, nothing happening either.

A IS HELD THROUGHOUT. Full gameplay speed, and it is also what makes the take
terminate: the HP drain is what turns a 10 s window into a whole fight
instead of a slice of one.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "boss_saucer"
CAPTURES = 200                  # 10.0 s at 1:1 — reveal through the death
SETTLE = 10                     # EMULATED frames: REVEAL is already up at 3

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "sau" / "symbol_map.json").read_text())


def _dp(name):
    return next(p for p in _J["scenes"]["arena"]["placements"]
                if p["sym"] == name)["start"]


ST, BM, HP = (_dp(n) for n in ("US_B_STATE", "US_BEAM_STATE", "US_B_HP"))
BM_TELEGRAPH = 1                # sau_obj's own enum: 0 idle, 1 telegraph, 2 fire


def _u16(r, off):
    b = r.read_bytes(W, off, 2)
    return b[0] | (b[1] << 8)


class Fight:
    """One capture per call; A held, lanes flipped on the telegraph edge."""

    def __init__(self):
        self.dir = "left"
        self.prev_beam = 0

    def __call__(self, r, i):
        beam = _u16(r, BM)
        if beam == BM_TELEGRAPH and self.prev_beam != BM_TELEGRAPH:
            self.dir = "right" if self.dir == "left" else "left"
        self.prev_beam = beam
        return r.frame_step(STEP, a=True, **{self.dir: True})


def make_drive():
    return Fight()
