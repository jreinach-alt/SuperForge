"""mode7_explore — the streamed 512x512-tile overworld, and the town wipe.

TWO CLAIMS, ONE TAKE. The world is 4096x4096 px — sixteen times what the Mode 7
VRAM window holds — and it streams in around the avatar as she goes; and
stepping onto the one enterable house carries her into a Mode 1 interior
through a MOSAIC WIPE, with the return landing on the spot she left. Both are
motion claims and neither survives a still.

    wander      a walk WEST, which is the streaming: 12 tiles is most of a
                VRAM window of world arriving under her feet, and if the
                stream ever fell behind, this is where it would show
    approach    back east and north onto the house tile, one axis at a time
    wipe in     the mosaic dissolve
    town        the Mode 1 interior, walked
    wipe out    the door, and the same dissolve carrying her back
    overworld   ...at the spot she left, walking again

STATE-DRIVEN, AND THIS RAIL IS WHY THE RULE EXISTS. Two earlier attempts at a
clip here used a fixed frame plan and both produced a plausible GIF that never
entered the town: holding a direction for 4.5 tiles let the atomic 8-frame
slide finish AFTER the button changed, and even a frame-accurate plan that
genuinely reached the tile still rendered the overworld at the capture where
the town should be, because take_screenshot sits between steps and drifts the
plan against the ROM's own tick. So every beat here
is a poll: walk until the camera reports the tile, idle until the wipe reports
idle, tap until the scene changes. tools/record_m7x_clip.py is the ancestor of
this drive and the reason it is shaped this way.

THE DOOR IS EDGE-TAPPED, not held. The grid step is atomic and re-triggers off
a held direction, so holding Down in the interior walks past the door; the tap
is one frame of Down and the rest of the capture released.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "mode7_explore"
CAPTURES = 200                  # 10.0 s at 1:1
SETTLE = 60                     # EMULATED frames — the picture has dawned in

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "m7x" / "symbol_map.json").read_text())


def _sym(n):
    for p in _J["scenes"]["overworld"]["placements"] + _J["globals"]:
        if p["sym"] == n:
            return p["start"]
    raise KeyError(f"{n} not in the emitted map — did the allocator move it?")


PX, PY, MOS, SM = (_sym(n) for n in
                   ("US_CAM_PX", "US_CAM_PY", "ES_MOS_CTL", "ES_SM_CTL"))
HOUSE = (254, 254)              # the one enterable door, in world tiles
WEST_EDGE = 246                 # 12 tiles west of the spawn at (258, 258)
OVERWORLD = 0                   # ES_SM_CTL's scene id


def _tile(r):
    return (r.read_u16(W, PX) // 8, r.read_u16(W, PY) // 8)


def _wiping(r):
    return r.read_bytes(W, MOS, 1)[0] != 0


def _scene(r):
    return r.read_bytes(W, SM, 1)[0]


class Explore:
    """One capture per call; every beat waits on the ROM, never on a count."""

    def __init__(self):
        self.phase = 0
        self.n = 0
        self.taps = 0
        self.seen_wipe = False

    def _next(self):
        self.phase += 1
        self.n = 0

    def __call__(self, r, i):
        p, self.n = self.phase, self.n + 1

        if p == 0:                                  # the long streaming walk
            if _tile(r)[0] > WEST_EDGE:
                return r.frame_step(STEP, left=True)
            self._next()
            return r.frame_step(STEP)

        if p == 1:                                  # back east to the column
            if _tile(r)[0] < HOUSE[0]:
                return r.frame_step(STEP, right=True)
            self._next()
            return r.frame_step(STEP)

        if p == 2:                                  # north onto the house
            if _tile(r)[1] > HOUSE[1] and not _wiping(r):
                return r.frame_step(STEP, up=True)
            self._next()
            return r.frame_step(STEP)

        if p == 3:                                  # the dissolve owns the frame
            if _wiping(r):
                self.seen_wipe = True
            elif self.seen_wipe:
                self._next()
            return r.frame_step(STEP)

        # Walk the interior — and COME BACK. The exit is a TILE, not a region,
        # so a wander that ends off the door column never leaves: the first cut
        # of this drive walked left/right on a modulo and spent the last 40
        # captures tapping Down at a wall, ending the clip inside the town.
        if p == 4:                                  # ...out
            if self.n > 5:
                self._next()
            return r.frame_step(STEP, left=True)

        if p == 5:                                  # ...and back
            if self.n > 5:
                self._next()
            return r.frame_step(STEP, right=True)

        if p == 6:                                  # EDGE-tap south to the door
            if self.taps < 6 and not _wiping(r):
                self.taps += 1
                r.frame_step(1, down=True)
                return r.frame_step(STEP - 1)
            if _scene(r) == OVERWORLD and not _wiping(r):
                self._next()
            return r.frame_step(STEP)

        # ...back outside, at the spot she left. Walk on.
        return r.frame_step(STEP, right=self.n % 40 < 20,
                            down=self.n % 40 >= 20)


def make_drive():
    return Explore()
