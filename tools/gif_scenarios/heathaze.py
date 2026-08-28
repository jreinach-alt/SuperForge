"""heathaze — the mirage and its control, cut on the shimmer's own period.

THE TAKE IS THE EFFECT AND NOTHING ELSE. It opens on the desert already up and
already at full brightness, and closes on the same frame of the same shimmer.
No title card, no fade ramps: at 20 fps a card held for a third of a second
between two ramps does not read as a scene change, it reads as a FLASH — and
the round trip cost 54 of the previous take's 120 captures, so nearly half the
clip was the one picture with no shimmer in it. What that trip proved is not
lost with it. `desert` still hands BG1VOFS back and `title` still writes the
port from `hz_flat`'s own composed symbol;
`tests/test_heathaze.py::test_the_title_returns_undisplaced` asserts the
returned title PIXEL-IDENTICAL to the one before the warp ever armed, and
`tools/shot_heathaze.py` renders the same pair for a human. It is a transition
claim, proved where transition claims are proved rather than by making a viewer
sit through it on every loop.

WHAT A VIEWER GETS, in order, all of it inside one scene:

    the DESERT     below the horizon every scanline is drawn from a slightly
                   different SOURCE ROW, so the ground compresses and stretches
                   and the road, its dashes and the saguaro trunks boil, with a
                   small horizontal term beside it; the sky and the ridge above
                   the band perfectly still
    the CONTROL    B, and both channels switch to blob 64, the 65th: a complete
                   HDMA table whose every displacement is zero. One variable
                   moves — the "before distortion / after heat haze" pair,
                   live, from one binary
    and BACK       B again — the shimmer RESUMES rather than restarting, which
                   is what makes the toggle a control instead of a reset, and
                   is also what lets the take close on a phase the flat beat
                   never interrupted

THE LOOP POINT IS THE PHASE COMING BACK ROUND, AND IT WAS MEASURED. The picture
is a pure function of `ES_HZ_PHASE`: `hz_nmi_commit` points the vertical channel
at blob `phase` and the horizontal one at `(phase + HZ_HORIZ_LEAD) & 63`, so
equal phase is an identical frame whatever the accumulator behind it holds.
Driving the recorder's own 3-frame grid over 240 captures and comparing decoded
frames byte for byte: 64 distinct pictures, and captures 57, 114, 171 and 228
are pixel-identical to capture 0. **57 captures — 171 emulated frames, 2.85 s —
is the interval at which the opening picture returns**, and this take holds two
of them plus the capture it closes on: 115 frames, 5.75 s at 1:1, opening and
closing on one picture.

THE ANCHOR IS THE CARRIED FRACTION AT ZERO, and that is not decoration. The
shimmer advances `HZ_PHASE_BASE` = 0.375 phases a frame through `TS_STEP`, which
publishes whole phases and carries the rest, so a capture is 1.125 phases and 57
of them are 64.125 — the whole 64-phase loop, plus an eighth of a phase the
accumulator is still holding. Where the anchor leaves that eighth decides how
many multiples of 57 close exactly: from this one it takes FIVE periods to reach
a whole phase, so the first four all close (all four measured above), and from a
capture whose fraction read 96/256 it takes two — measured, the return at 57 was
pixel-identical and the one at 114 was a phase out. So the drive waits for the
fraction rather than taking the first settled capture it sees.

THE SAME EIGHTH IS WHY THE CLIP IS NOT A LOOP OF A LOOP. Inside the take, seven
captures in eight repeat exactly 57 later and the eighth sits one phase further
on — invisible in boiling air, and nothing to do with the join, which is one
specific pair of captures and measures 0 differing pixels of 61,184. It is also
why the drive closes on the PHASE and not on the picture: at capture 57 the
picture is the flat control, and only the phase underneath it says a period has
gone by.

THE BEATS ARE IN CAPTURES because they are durations, not events: how long a
viewer looks at the shimmer before the control interrupts it is a choice, and
there is no byte in the ROM that has an opinion about it. The two ends are the
opposite case and are read off the ROM — the take opens on a state and closes
on the phase returning to the value it opened with, for the second time.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "heathaze"
CAPTURES = 200                  # a CEILING over the 16-capture lead-in and the
                                #   115 the take keeps, not a schedule: the
                                #   phase returning is what ends it.

# The beats, in captures of three emulated frames each — durations in the ROM's
# own time rather than in the host's. They sum to PERIODS * 57, which is what
# puts the closing shimmer back on the opening one.
SHIMMER_A = 44                  # 2.20 s: long enough to read as boiling air
FLAT      = 20                  # 1.00 s: the same picture, dead still
SHIMMER_B = 50                  # 2.50 s: it resumes, and runs to the mark
PERIODS   = 2                   # ...and 44 + 20 + 50 = 114 = 2 x 57

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "hz" / "symbol_map.json").read_text())


def _dp(name, scene=None):
    pool = _J["scenes"][scene]["placements"] if scene else _J["globals"]
    return next(p for p in pool if p["sym"] == name)["start"]


SM_CTL = _dp("ES_SM_CTL")
FADE = _dp("ES_FADE_CTL")
# SCENE-SCOPED, and that is why nothing below reads them until the desert is the
# scene running: in the title these direct-page words belong to something else,
# exactly as main.asm's sm_nmi_hook says of the phase it guards.
PHASE = _dp("ES_HZ_PHASE", "desert")
ACC = _dp("US_TSH_ACC", "desert")

# The scene ids come from the allocator's emitted edges, so a manifest reorder
# moves them here too.
_EDGE = {(e["src"], e["dst"]): e["dst_scene_index"] for e in _J["edges"]}
TITLE, DESERT = _EDGE[("desert", "title")], _EDGE[("title", "desert")]

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

    A press lasts ONE frame of the two the drive advances. `take_screenshot`
    releases the pad for its own frame, so the toggle is edge-detected exactly
    once per press and a held button could not be photographed at all.
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
                return self._step(r, start=True)        # -> desert
            if _at_rest(r, DESERT) and _u16(r, ACC) == 0:
                self.started = True
                self.mark = _u16(r, PHASE)
                self.n = 0
            return self._step(r)

        if _u16(r, PHASE) == self.mark:
            self.periods += 1
            self.done = self.periods >= PERIODS
        press = {}
        if self.n == SHIMMER_A:
            press = {"b": True}                         # -> flat
        elif self.n == SHIMMER_A + FLAT:
            press = {"b": True}                         # -> shimmer again
        return self._step(r, **press)


def make_drive():
    return Drive()
