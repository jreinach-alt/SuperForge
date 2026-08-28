"""lakeside — the surface drifting over the bed, cut on a whole surf cycle.

THE TAKE IS THE LAKE AND NOTHING ELSE. It opens on the scene already up and
already at full brightness, and closes on the same frame of the same wave. No
title card, no fade ramps: at 20 fps a card held for a third of a second between
two ramps does not read as a scene change, it reads as a FLASH — and the round
trip cost 62 of the previous take's 166 captures, so more than a third of the
clip was the one picture with no water in it. What that trip proved is not lost
with it. The composed colour-math state is still per scene and `title` still
composes `blend_off`;
`tests/test_lakeside.py::test_the_title_scene_does_not_inherit_the_lake_blend`
asserts the returned title BIT-IDENTICAL to a title that never visited the lake,
and `tools/shot_lakeside.py` renders the pair for a human. It is a transition
claim, proved where transition claims are proved.

THE CLAIM IS THE BLEND, and what carries it is the SWASH rather than a cut to a
dry bed. The surface is on the sub screen and the blend is a half-add, so the
water's own top edge IS the blend boundary: where the surface has a pixel the
world renders as (world + water) >> 1, and where it has none the world arrives
whole. The wave runs up the shore and the sand it crosses goes dark and cool —
WET SAND — and the backwash draws down and gives it back dry, three times over
the length of this clip. Nothing repaints a wet palette; that shading is the
half-add moving its own boundary, which is the colour math and the animation
being one event. A viewer sees the bed through the water in every frame of the
take, which is what the dry title beat used to have to say out loud.

B IS NOT PRESSED HERE, and dropping it is a choice rather than an oversight.
Stilling the drift is a real property of the rail and `tests/test_lakeside.py`
holds it to a pixel-identical picture pair; what it is not is something to
WATCH. A still beat is a wholly static stretch of clip, and a still beat long
enough to read as deliberate would also have to be a multiple of three frames
long or it would push the wave off the capture grid the loop closes on. The
clip is 6.45 s of water instead, with no fully-static transition in it at all.

THE LOOP POINT IS A WHOLE NUMBER OF SURF CYCLES, AND IT WAS MEASURED. The
picture is a pure function of where the surface has drifted to: BG2's tilemap
is a 4-cell pattern repeated eight times, so 32 px of scroll reproduces the
layer exactly; `wat_nmi_glint` selects the highlight from (scroll >> 3) & 3,
another 32 px; and `wat_nmi_surf` selects the swash band from (scroll >> 2) & 31,
which is LK_SURF_PERIOD_PX = 128. Their common period is 128 px. Driving the
recorder's own 3-frame grid over 280 captures and comparing decoded frames byte
for byte: 128 distinct pictures, and captures 128 and 256 are pixel-identical to
capture 0. The drift is 1 px a frame — LK_WATER_SPEED, published by TS_STEP with
a carried fraction that is zero on every NTSC frame — so a capture is 3 px, 128
px does not divide by 3, and the smallest whole-capture return is **128 captures
on: 384 px, three surf cycles**. The take is those 128 plus the capture it
closes on — 129 frames, 6.45 s at 1:1, opening and closing on one picture — and
the mark it closes on is read off ES_WAT_SCROLL rather than counted to.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "lakeside"
CAPTURES = 200                  # a CEILING over the 11-capture lead-in and the
                                #   129 the take keeps, not a schedule: the
                                #   surf cycle returning is what ends it.

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "lks" / "symbol_map.json").read_text())


def _dp(name, scene=None):
    pool = _J["scenes"][scene]["placements"] if scene else _J["globals"]
    return next(p for p in pool if p["sym"] == name)["start"]


SM_CTL = _dp("ES_SM_CTL")
FADE = _dp("ES_FADE_CTL")
# SCENE-SCOPED, and that is why nothing below reads it until the lake is the
# scene running: in the title this direct-page word belongs to something else.
SCROLL = _dp("ES_WAT_SCROLL", "lake")

# The scene ids come from the allocator's emitted edges, so a manifest reorder
# moves them here too.
_EDGE = {(e["src"], e["dst"]): e["dst_scene_index"] for e in _J["edges"]}
TITLE, LAKE = _EDGE[("lake", "title")], _EDGE[("title", "lake")]

SM_RUN = 0                      # scene_mgr's phase machine: 0 is "running"
FADE_FULL, FADE_IDLE = 15, 0    # fade.asm's own end stop and direction enum

# The surf's cycle, in pixels of drift, read out of the GENERATED layout include
# the ASM pins rather than retyped here — a re-authored wave moves this number
# and a copy would close the loop on the wrong frame with every gate still
# green. `tools/shot_lakeside.py` reads the same file the same way.
_ART = {}
for _line in (ROOT / "build" / "assets" / "lk_art.inc").read_text().splitlines():
    if "=" in _line and not _line.lstrip().startswith(";"):
        _k, _v = _line.split("=", 1)
        _ART[_k.strip()] = int(_v.strip())
PERIOD_PX = _ART["LK_SURF_PERIOD_PX"]


def _u16(r, off):
    b = r.read_bytes(W, off, 2)
    return b[0] | (b[1] << 8)


def _at_rest(r, scene):
    """`scene` is running and no ramp is on screen — the fade idle at full."""
    sm = r.read_bytes(W, SM_CTL, 4)
    fd = r.read_bytes(W, FADE, 2)
    return (sm[0] == scene and sm[2] == SM_RUN
            and fd[0] == FADE_FULL and fd[1] == FADE_IDLE)


class Drive:
    """One capture per call, each advancing STEP frames; the pad is idle.

    `started` stays falsy through the boot, the title, the Start press and both
    fade ramps, so all of that is dropped lead-in — the recorder pays those
    frames and not their screenshots. `done` closes the take on the first
    capture whose drift is a whole number of surf cycles from the mark, which
    on a 3-frame grid is three of them.
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.mark = None        # where the surface had drifted to at the open

    def __call__(self, r, i):
        if not self.started:
            if _at_rest(r, TITLE):
                return r.frame_step(STEP, start=True)   # -> lake
            if _at_rest(r, LAKE):
                self.started = True
                self.mark = _u16(r, SCROLL)
            return r.frame_step(STEP)

        # u16 wraparound is a multiple of the period, so the subtraction needs
        # no unwrapping — the same property wat_advance relies on to run
        # unbounded (water.asm).
        self.done = (_u16(r, SCROLL) - self.mark) % PERIOD_PX == 0
        return r.frame_step(STEP)


def make_drive():
    return Drive()
