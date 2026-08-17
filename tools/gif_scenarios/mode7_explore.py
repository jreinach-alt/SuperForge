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

THE LOOP POINT IS THE SPAWN TILE, because the wipe this rail is built around
does not reach black — it is a MOSAIC dissolve, which blocks the picture up
rather than darkening it, and the two scenes either side of it are lit. What
the rail does have is a grid: the avatar is tile-locked, every step is atomic,
and the pose is four numbers that can be walked back to exactly. So the take
opens on an idle capture at the spawn — measured on this binary, US_CAM_PX and
US_CAM_PY both 2064, tile (258,258), US_FACING 0 which is Down — and closes
when all four read that again with no slide in flight and no wipe running.

THE LAST LEG IS EAST THEN SOUTH, and the order is the facing. Arriving on the
spawn tile from the north leaves the avatar facing Down, which is the way she
was facing when the clip opened; coming in from the west would land the same
tile wearing a different sprite, and the join would blink.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "mode7_explore"
CAPTURES = 320                  # a CEILING: the spawn pose closes the take
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
FACING, STEP_ACTIVE = (_sym(n) for n in ("US_FACING", "US_STEP_ACTIVE"))
HOUSE = (254, 254)              # the one enterable door, in world tiles
SPAWN = (258, 258)              # ...and where she starts, which is where she ends
WEST_EDGE = 246                 # 12 tiles west of the spawn
OVERWORLD = 0                   # ES_SM_CTL's scene id
FACE_DOWN = 0                   # US_FACING: 0 down, 1 up, 2 left, 3 right


def _tile(r):
    return (r.read_u16(W, PX) // 8, r.read_u16(W, PY) // 8)


def _wiping(r):
    return r.read_bytes(W, MOS, 1)[0] != 0


def _scene(r):
    return r.read_bytes(W, SM, 1)[0]


def _at_spawn(r):
    """The whole pose, and nothing in flight — the clip's own first frame."""
    return (r.read_u16(W, PX) == SPAWN[0] * 8
            and r.read_u16(W, PY) == SPAWN[1] * 8
            and r.read_u16(W, FACING) == FACE_DOWN
            and r.read_u16(W, STEP_ACTIVE) == 0
            and not _wiping(r)
            and _scene(r) == OVERWORLD)


class Explore:
    """One capture per call; every beat waits on the ROM, never on a count."""

    def __init__(self):
        self.phase = 0
        self.n = 0
        self.taps = 0
        self.seen_wipe = False
        self.done = False

    def _next(self):
        self.phase += 1
        self.n = 0

    def __call__(self, r, i):
        p, self.n = self.phase, self.n + 1

        if i == 0:                                  # the pose the clip opens on
            return r.frame_step(STEP)

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

        # ...back outside, at the spot she left — and on home to the spawn
        # tile, EAST FIRST so the last step in is from the north and she ends
        # facing the way she began.
        if _tile(r)[0] < SPAWN[0]:
            return r.frame_step(STEP, right=True)
        if _tile(r)[1] < SPAWN[1]:
            return r.frame_step(STEP, down=True)
        r.frame_step(STEP)
        if _at_spawn(r):
            self.done = True


def make_drive():
    return Explore()
