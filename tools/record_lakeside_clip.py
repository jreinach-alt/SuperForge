#!/usr/bin/env python3
"""Record the lakeside gallery clip — the rail's own recorder.

Usage:  python3 tools/record_lakeside_clip.py [out.gif]

The take is choreographed rather than a hold, because what this rail is FOR is
a state cycle: the world with the blender composed off, the same world with a
sub-screen layer half-added over it, the surface stilled, the surface resumed,
and the world again with the blender off.

IT RETURNS TO THE TITLE ON PURPOSE, and that serves two ends at once. A gallery
clip loops forever, so its last frame is glued back onto its first and the join
is invisible only when both land on the same instant of the ROM
(`record_gallery_clip`'s own rule). Here the instant that satisfies that is also
the transition-hygiene claim: the composed colour-math state is per scene, so
the title returned to is the title departed from — the same picture, because
nothing carried the blend across the edge.

Timing comes from `record_gallery_clip`: every 3rd emulated frame at 50 ms,
so one clip second is one gameplay second, and the recorder asserts that 1:1
guarantee rather than trusting it. The beats below are in CAPTURES (3 frames
each); `SETTLE` covers a scene switch plus both fade ramps.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE))
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from tools.record_gallery_clip import record_clip, STEP  # noqa: E402

ROM = SUPERFORGE / "build" / "lakeside.sfc"

TITLE_HOLD = 6      # the opening title, blender composed OFF
SETTLE     = 27     # a scene switch + both fade ramps (~81 frames)
DRIFT_A    = 27     # the surface drifting over the world
STILL      = 12     # B latched: the same surface, holding
DRIFT_B    = 21     # B again: the drift resumes


class Drive:
    """One capture per call, each advancing STEP frames; a press is one capture.

    A press lasts exactly one capture because stilling is a LATCHED TOGGLE —
    `take_screenshot` releases both pads for its own frame, so a held control
    would re-trigger on every capture and could not be photographed at all.
    """

    def __init__(self):
        self.marks, i = {}, TITLE_HOLD
        self.marks[i] = {"start": True}; i += 1 + SETTLE + DRIFT_A
        self.marks[i] = {"b": True};     i += 1 + STILL
        self.marks[i] = {"b": True};     i += 1 + DRIFT_B
        self.marks[i] = {"start": True}; i += 1 + SETTLE
        self.total = i

    def __call__(self, runner, i):
        runner.frame_step(STEP, **self.marks.get(i, {}))
        self.done = i >= self.total - 1


def main(out):
    drive = Drive()
    path, n, size = record_clip(str(ROM), out, drive=drive,
                                captures=drive.total + 2, settle_frames=60)
    print(f"{path}  {n} captures, {size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "docs/img/gif_lakeside.gif"))
