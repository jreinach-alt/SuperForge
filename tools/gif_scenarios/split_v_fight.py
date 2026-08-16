"""split_v_fight — the seamless distance-driven camera split.

THE CLAIM IS THAT THE SPLIT IS NOT A TOGGLE, and that is a claim about
CONTINUITY, so a still cannot make it and a clip can. The two half-cameras
diverge continuously from the fighter separation: at zero separation the
halves are pixel-identical and the ever-present seam is invisible; as the
fighters part, a beveled BG3 bar grows from ZERO width. The beats:

    merged      both fighters together, no divider anywhere in the picture
    opening     the halves diverging, the bar growing off zero width
    open        both on their walls, the split at its 40-unit cap
    re-merged   walked back together — the bar shrinks back INTO nothing,
                which is the half of the claim a one-direction clip would
                leave untested
    crossing    they walk THROUGH each other, inside the merged window
    swapped     ...and the split re-opens with the fighters exchanged: the
                split follows the crossover
    closed      and back to merged from the crossed side

BOTH PADS, AND THAT IS WHY THE DRIVE SETS THEM SEPARATELY. `frame_step` latches
one controller and advances; `set_input(1, ...)` latches pad 2 without
advancing and persists across steps (which is what the recorder's own `hold2`
relies on). Fighter 2 needs to CHANGE direction three times here, so `hold2` is
not enough and the drive sets pad 2 itself each capture.

EVERY BEAT WAITS ON THE ROM. The spread is an EASE — 0.75 px/frame chasing a
target that moves at 2 — so "frames to fully open" is a tuning constant, not a
fact, and SV_DWELL exists in the rail precisely because the ease has not caught
up when the fighters reach the walls. So the drive walks until ES_SV_SPREAD
reports the cap and until US_FX1 has genuinely passed US_FX2. A frame plan
would open the split most of the way and call it open.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "split_v_fight"
CAPTURES = 200                  # 10.0 s at 1:1
SETTLE = 60                     # EMULATED frames — past the fade-in, merged

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "sv" / "symbol_map.json").read_text())


def _dp(name):
    return next(p for p in _J["scenes"]["fight"]["placements"]
                if p["sym"] == name)["start"]


SPREAD, FX1, FX2 = (_dp(n) for n in ("ES_SV_SPREAD", "US_FX1", "US_FX2"))
CAP = 40                        # measured: the ease's fixed point on the walls

APART = ({"left": True}, {"right": True})       # (pad1, pad2)
TOGETHER = ({"right": True}, {"left": True})
IDLE = ({}, {})


def _u16(r, off):
    b = r.read_bytes(W, off, 2)
    return b[0] | (b[1] << 8)


class Split:
    """One capture per call; both pads latched, the beat read off the ROM.

    THE BEATS CYCLE rather than ending, and the dwells are gone. Measured on
    the first cut of this drive: 33% of the raw transitions were fully static,
    in four holds — a 9-capture opening idle, two 12-capture wall dwells, and
    a 36-capture tail where the fighters had reached the walls with nothing
    left to do. Two of those four are the rail's ease saturating (the fighters
    arrive at the walls ~12 captures before the 0.75 px/frame spread finishes
    chasing them, and the divider's width only steps every 16 spread units, so
    the picture genuinely holds); the other two were mine. So: no explicit
    dwell, and the sequence loops, which is also the right shape for a file
    that loops forever.
    """

    def __init__(self):
        self.phase = 0
        self.n = 0

    def _next(self, to=None):
        self.phase = self.phase + 1 if to is None else to
        self.n = 0

    def _step(self, r, pads):
        p1, p2 = pads
        r.set_input(1, **p2)            # pad 2 persists across the step
        return r.frame_step(STEP, **p1)

    def __call__(self, r, i):
        p, self.n = self.phase, self.n + 1
        spread = _u16(r, SPREAD)

        if p == 0:                                  # merged, seam invisible
            if self.n > 4:
                self._next()
            return self._step(r, IDLE)

        if p == 1:                                  # part to the cap
            if spread >= CAP:
                self._next()
            return self._step(r, APART)

        if p == 2:                                  # close, THROUGH each other
            if spread >= CAP and _u16(r, FX1) > _u16(r, FX2):
                self._next()
            return self._step(r, TOGETHER)

        # ...and back, which re-crosses through the merge and re-opens on the
        # original sides. Then round again: the whole claim is a cycle.
        if spread >= CAP and _u16(r, FX1) < _u16(r, FX2) and self.n > 8:
            self._next(to=2)
        return self._step(r, APART)


def make_drive():
    return Split()
