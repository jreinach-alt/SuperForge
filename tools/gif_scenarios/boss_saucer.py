"""boss_saucer — the Mode 7 scale axis, run as a boss fight.

THE WHOLE CYCLE, IN ORDER, and the clip is sized to hold exactly one of it:
the saucer grows in over the star field, settles at rest size, lunges (which
is the scale axis m7_affine does not have), aims a sight line down out of its
own emitter and fires the lance along it, and — because the drive is shooting
the entire time — breaks off, recedes and dies. The result card holds over the live arena, the screen fades
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

THE DODGE IS THE CHOREOGRAPHY, AND IT IS NOW ALSO THE ONLY WAY TO WIN. The
beam is latched onto the gunship's lane with two-thirds of the dive still to
run, and it is drawn as a lance from the saucer's own ventral emitter to that
lane — so the telegraph is a sight line the player can read and leave. This
drive latches a dodge direction on the telegraph's RISING EDGE (read off
US_BEAM_STATE, not counted to), holds it only until the ship is clear of the
column, and then steers back under the saucer, because the saucer's hitbox is
its RENDERED disc: bolts only land from underneath. Measured on this binary,
a drive that just held a lane died with the saucer on 35 hp.

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
PX, BX = (_dp(n) for n in ("US_P_X", "US_BEAM_X"))
FADE = _dp("ES_FADE_CTL")
SAU_ST_RESULT = 6               # saucer.inc: hold the card, then fade to RESET
SPAWN_X = 120                   # saucer.inc: SAU_PLAYER_X0


def _u16(r, off):
    b = r.read_bytes(W, off, 2)
    return b[0] | (b[1] << 8)


def _black(r):
    """The fade has finished ramping and is sitting at brightness 0."""
    lvl, direction = r.read_bytes(W, FADE, 2)
    return lvl == 0 and direction == 0


class Fight:
    """One capture per call; A held, each beam dodged once, then back to lane.

    The take CLOSES ON THE ROM: once the result card has been up, the next
    capture that finds the ramp finished at brightness 0 is the last one. The
    card is required first so the boot ramp's own brief black — armed before
    the scene has drawn anything — cannot end the take at capture zero.
    """

    def __init__(self):
        self.dodge = None
        self.prev_beam = 0
        self.done = False
        self.seen_result = False

    def _pad(self, r):
        beam, px, bx = _u16(r, BM), _u16(r, PX), _u16(r, BX)
        if beam and not self.prev_beam:
            self.dodge = "right" if bx < 128 else "left"
        self.prev_beam = beam
        if beam:
            # hold the latched direction only until the column cannot reach
            return {self.dodge: True} if abs(px + 4 - bx) < 28 else {}
        self.dodge = None
        if px < SPAWN_X - 2:
            return {"right": True}
        if px > SPAWN_X + 2:
            return {"left": True}
        return {}

    def __call__(self, r, i):
        pad = self._pad(r)
        if _u16(r, ST) == SAU_ST_RESULT:
            self.seen_result = True
        r.frame_step(STEP, a=True, **pad)
        if self.seen_result and _black(r):
            self.done = True


def make_drive():
    return Fight()
