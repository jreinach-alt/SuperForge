"""smelter — the foundry floor, cut on the column table's own period.

THE TAKE IS THE EFFECT AND NOTHING ELSE. It opens on the works scene already up
and already at full brightness, and closes on the same frame of the same
animation. No title card, no fade ramps: at 20 fps a card held for a third of a
second between two ramps does not read as a scene change, it reads as a FLASH.
What the round trip proves is not lost with it — `works` still hands BG3 back
pointing at a page of scroll words and `title` still re-points BG3SC from
`bg_text`'s own registers;
`tests/test_smelter.py::test_the_title_returns_with_bg3_a_layer_again` asserts
the returned title PIXEL-IDENTICAL to the one before the works ever ran, and
`tools/shot_smelter.py` renders the same pair for a human. It is a transition
claim, proved where transition claims are proved rather than by making a viewer
sit through it on every loop.

WHAT A VIEWER GETS is the columns and nothing else: four steel plates each on
its own harmonic, so no two are ever in step, and between them the melt lifting
out of its own surface column by 8-pixel column — an arch across a four-wide
gap, a single lifted column in a three-wide one, and one lone column of melt
standing at the right-hand edge. Under the plates the melt is calm, because a
column's word drives BG1 or BG2 and not both.

THE FLAT CONTROL IS NOT IN THE TAKE, AND THAT IS DELIBERATE. B swaps the
transfer to the blob's 65th row — every value at its base, every enable bit
still set — and holding it for a second is the "before / after" pair, live,
from one binary. On a clip that loops forever it does not read as a control; it
reads as a BREAK, a second where the picture is frozen and the effect has
apparently stopped working. That is the seam lesson the last two rails paid for
(reports/gallery_loop_seams.md). The pair is still made where a pair belongs:
`tools/shot_smelter.py` renders the running and flat frames side by side, and
`tests/test_smelter.py::test_the_flat_control_levels_every_column` asserts the
control actually levels every one of them.

THE LOOP POINT IS THE PHASE COMING BACK ROUND, AND IT WAS MEASURED. The picture
is a pure function of `ES_SMT_PHASE`: `smt_nmi_row` moves the blob's row
`phase` into BG3's V row and nothing else varies, so equal phase is an
identical frame whatever the accumulator behind it holds. Driving the
recorder's own drive/capture order from this scenario's own anchor, hashing
decoded frames over 384 captures: the stored frames PIXEL-IDENTICAL to frame 0
are **57, 170, 227 and 284**, and the drive's own phase check sees the mark
return at 57, 114 and 171. THE FIRST RETURN IS ALSO THE FIRST IDENTICAL FRAME,
so this take closes there: **58 stored frames, 174 emulated frames, 2.90 s**.

WHY THE FIRST RETURN AND NOT A LATER ONE. 57 captures is 64.125 phases: the
whole loop plus an eighth of a phase the 8.8 accumulator is still carrying,
since `TS_STEP` publishes only whole units. That eighth accumulates, so a
return of the PHASE is not automatically a return of the PICTURE — 114 is one
phase out while 170 and 227 are not, the same irregularity `heathaze` measured
on its own take. The first return is where this one closes because 64 phases is
one complete turn of EVERYTHING: every plate's harmonic and every jet's
completes a whole number of cycles in it, so a viewer who watches 2.9 s has
seen all of the animation there is and a longer take would only repeat it.

THE DRIVE CLOSES ON THE PHASE rather than on the picture, because the phase is
the ROM's own account of where the animation is and the picture is an inference
from it. Which return to close on is what the measurement decided.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "smelter"
CAPTURES = 140                  # a CEILING over the lead-in and the 58 the
                                #   take keeps, not a schedule: the phase
                                #   returning is what ends it.

PERIODS = 1                     # 58 stored frames, 2.90 s — one complete turn
                                #   of every harmonic, closing on a picture
                                #   measured pixel-identical to the opening one

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "smt" / "symbol_map.json").read_text())


def _dp(name, scene=None):
    pool = _J["scenes"][scene]["placements"] if scene else _J["globals"]
    return next(p for p in pool if p["sym"] == name)["start"]


SM_CTL = _dp("ES_SM_CTL")
FADE = _dp("ES_FADE_CTL")
# SCENE-SCOPED, and that is why nothing below reads them until the works is the
# scene running: in the title these direct-page words belong to something else,
# exactly as main.asm's sm_nmi_hook says of the phase it guards.
PHASE = _dp("ES_SMT_PHASE", "works")
ACC = _dp("US_TSC_ACC", "works")

# The scene ids come from the allocator's emitted edges, so a manifest reorder
# moves them here too.
_EDGE = {(e["src"], e["dst"]): e["dst_scene_index"] for e in _J["edges"]}
TITLE, WORKS = _EDGE[("works", "title")], _EDGE[("title", "works")]

SM_RUN = 0                      # scene_mgr's phase machine: 0 is "running"
FADE_FULL, FADE_IDLE = 15, 0    # fade.asm's own end stop and direction enum


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
    """One capture per call, each advancing STEP frames.

    `started` stays falsy through the boot, the title, the Start press and both
    fade ramps, so all of that is dropped lead-in — the recorder pays those
    frames and not their screenshots. `done` closes the take on the capture
    whose phase has come back to the mark for the PERIODS'th time.

    The one press in the whole take is the Start that leaves the title, and it
    lasts ONE frame of the two the drive advances — `take_screenshot` releases
    the pad for its own frame, so the scene's edge-triggered read fires exactly
    once and cannot bounce straight back out of the scene it just entered.
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.mark = None        # the phase the take opened on
        self.periods = 0
        self.n = 0

    def _step(self, r, **press):
        if press:
            r.frame_step(1, **press)
            r.frame_step(STEP - 1)
        else:
            r.frame_step(STEP)

    def __call__(self, r, i):
        self.n += 1
        if not self.started:
            if _at_rest(r, TITLE):
                return self._step(r, start=True)        # -> works
            if _at_rest(r, WORKS):
                self.started = True
                self.mark = _u16(r, PHASE)
                self.n = 0
            return self._step(r)

        if _u16(r, PHASE) == self.mark:
            self.periods += 1
            self.done = self.periods >= PERIODS
        return self._step(r)


def make_drive():
    return Drive()
