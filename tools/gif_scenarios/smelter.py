"""smelter — a run across the foundry floor, and the melt taking him.

THE TAKE IS A PERFORMANCE, not a turn of the animation. The knight crosses two
and a half screens by jumping plates that are moving under him, then stops being
careful, walks off, and the world takes him — and the mosaic dissolves the whole
thing and puts him back at the start. What it shows is the rail as a GAME, and
the effect is still all of it: every plate he lands on is a word in the offset
table, and the collision that catches him reads the same word the picture is
drawn from.

It replaced a 2.9 s loop of the effect alone. That take is still the right shape
for an effect and the wrong one for a rail that scrolls and can be lost.

THE DRIVE PLAYS, IT DOES NOT REPLAY. Every beat is decided from the ROM's own
state and the ROM's own table, so a change to the course or the physics moves
the performance with it instead of leaving a fixed plan pressing buttons at the
wrong moments. Three beats, each ending on a fact rather than a count: cross
until past CROSS_TO, then hold right and stop jumping, then hands off while the
wipe runs.

WHAT IT COST TO MAKE THIS RECORDABLE, because the number that fixed it is not
where anyone would look. The capture spends a frame of its own with BOTH PADS
RELEASED, so while recording, one frame in three is a frame the knight is not
driven through. That costs HORIZONTAL TRAVEL and nothing else — the jump is a
fixed impulse on the press EDGE, so the arc and the apex are untouched. Measured
on one jump from the spawn: 60 px of reach at full input, 42 px while recording,
and a jump from the plate's left edge needs the whole 60 to arrive. The first
recorded take was ten deaths long and never crossed a single gap.

The fix is WALK_IN, below: take off from deeper into the plate, which spends
plate he is standing on anyway and gives the two reaches a window they share.
The game is unchanged and every other clip in the tree is untouched — the
alternative was changing the shared recorder so a capture carries the drive's
pad, which every clip is shot through.

THE FLAT CONTROL IS STILL NOT IN THE TAKE. B swaps the transfer to the blob's
flat row and holding it is the "before / after" pair, live, from one binary — on
a clip that loops it reads as a BREAK rather than as a control
(reports/gallery_loop_seams.md). The pair is made where a pair belongs:
`tools/shot_smelter.py` renders the running and flat frames side by side, and
`tests/test_smelter.py::test_the_flat_control_levels_every_column` asserts it.

THE SEAM IS NO LONGER ZERO AND CANNOT BE. The old take closed on the phase
coming back round, so its ends were pixel-identical and the loop was invisible.
A run has somewhere to be: it opens on the spawn at full brightness and closes
on the spawn at full brightness, one death later, with the plates at a different
point in their harmonics. Measured on the written file: mad 11.66/255, 25.8% of
pixels past 16, ends at luma 51.9 / 51.7. The brightness matches; what differs
is where the plates are. That is a loop of a PERFORMANCE, and it is the honest
number for one.


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
CAPTURES = 460                  # a CEILING over the lead-in and the run, not a
                                #   schedule: the wipe going idle is what ends
                                #   the take. Measured at 1-frame granularity
                                #   the run is ~480 frames; the recorder steps
                                #   3 at a time and re-decides each step, so
                                #   this is deliberately loose — and looser
                                #   than the arithmetic suggests, because
                                #   `take_screenshot` spends a frame of its own
                                #   with the pads RELEASED, so one capture in
                                #   four is a frame the knight is not being
                                #   driven through.

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

# --- the performance ------------------------------------------------------
# The clip is a RUN now, not a loop of the effect, so the drive plays the game.
# It reads the ROM's own state and the ROM's own table to decide each beat,
# which is what keeps it a recording rather than a fixed plan that drifts.
KN_X = _dp("ES_SMT_KN_X", "works")
KN_PLATE = _dp("ES_SMT_KN_PLATE", "works")
MOS_CTL = _dp("ES_MOS_CTL")
AIRBORNE = 0xFFFF

CROSS_TO = 640                  # 2.5 screens, and then he stops being careful

# The jump's reach is 4v/g = 64 px and the slots are 64 apart, so a crossing is
# never about distance. It is about HEIGHT, and the window below is two-sided
# because both directions cost him:
#   * a target more than an apex ABOVE cannot be reached at all;
#   * a target too far BELOW is worse and is the one a one-sided rule misses —
#     he clears it at apex height, then has to FALL the difference, and drifts
#     past the plate's 32 px while doing it. Traced on the binary: he flew over
#     a whole slot and died beyond the next one.
# TUNED AT THE RECORDER'S CADENCE, which is the only one the take is shot in.
# The pair was first set against the full-input reach of 60 px and left three
# deaths in the run; at the recorded reach of 42 the landing lands differently
# and the window wants re-measuring rather than re-reasoning. Swept: (32,16)
# reached 1.45 screens, (32,24) 1.96, (32,32) 2.20, and (24,24) 2.70 with a
# single death — the one at the end, which is the point of the take.
JUMP_UP, JUMP_DOWN = 24, 24

# ...and the flight is ~32 frames at 0.375 phases a frame, so the target has
# moved about this far by the time he arrives. A player leads the plate; so
# does this.
JUMP_LEAD = 6

# HOW FAR ONTO THE PLATE HE WALKS BEFORE TAKING OFF, and this is the number that
# makes the take recordable at all.
#
# The capture spends a frame of its own with BOTH PADS RELEASED (mesen_runner's
# take_screenshot; STEP = EVERY - SHOT_FRAMES), so while recording, one frame in
# three is a frame he is not being driven through. That costs HORIZONTAL travel
# and nothing else — the jump is a fixed impulse on the press EDGE, so releasing
# A mid-flight cannot change the arc, and the height is untouched. Measured, one
# jump from the spawn:
#
#   full input        reach 60 px over 29 frames  -> lands on slot 1
#   recorder cadence  reach 42 px over 29 frames  -> lands on NOTHING
#
# A jump from the plate's left edge needs the whole 60 to arrive, so at 42 he
# falls short of every slot and the take was ten deaths long. Taking off from
# deeper in spends plate he is standing on anyway, and the two reaches then
# share a window — measured at both cadences:
#
#   walk-in  0 px   full lands, recorder FALLS
#   walk-in  8 px   both land
#   walk-in 12 px   both land
#   walk-in 15 px   both walk off the edge first (the plate test is on his
#                   CENTRE, so 16 is already off)
#
# So the fix is here, in the performance, and not in the physics or the
# recorder: the game is unchanged and every other clip in the tree is untouched.
WALK_IN = 10

_ART = {}
for _line in (ROOT / "build" / "assets" / "smt_art.inc").read_text().splitlines():
    _h, _, _r = _line.partition("=")
    if _r and _h.strip().startswith("SMT_"):
        try:
            _ART[_h.strip()] = int(_r.split(";")[0].strip())
        except ValueError:
            pass
SLOTS = _ART["SMT_PLAT_COUNT"]
SLOT_COL = [_ART[f"SMT_PLAT_{i}_COL"] for i in range(SLOTS)]
ROW_BYTES = _ART["SMT_ROW_BYTES"]
PHASES = _ART["SMT_PHASES"]
PLAT_TOP_PX = _ART["SMT_PLAT_TOP_PX"]
_BLOB = (ROOT / "build" / "assets" / "smt_col.bin").read_bytes()
_MASK = 0x03FF


ROW_BIAS = 1                    # smelter.inc's off-by-one, and tests/ re-solves
                                #   it from the picture rather than trusting it


def _slot_top(slot, phase):
    """A slot's top edge as a PICTURE ROW, out of the SAME table the ROM reads.
    The drive knows what the player can see and nothing else."""
    at = (phase % PHASES) * ROW_BYTES + SLOT_COL[slot] * 2
    word = (_BLOB[at] | (_BLOB[at + 1] << 8)) & _MASK
    return PLAT_TOP_PX - word - ROW_BIAS


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
    """One capture per call, each advancing STEP frames — and now a PERFORMANCE.

    The take used to be one turn of the animation, closing when the phase came
    back round. It is a RUN now: the knight crosses two and a half screens by
    jumping the slots, then stops being careful, walks off, and the world takes
    him. What the clip shows is the rail as a game rather than the rail as an
    effect, and the effect is still all of it — every plate he lands on is a
    word in the offset table.

    THE DRIVE PLAYS, IT DOES NOT REPLAY. Every beat is decided from the ROM's
    own state and the ROM's own table, so a tuning change to the course or the
    physics moves the performance with it instead of leaving a fixed plan
    pressing buttons at the wrong moments. That is the same rule the lead-in
    already followed — `_at_rest` waits for the scene to actually be running
    rather than counting frames at it.

    THREE BEATS, and each ends on a fact rather than a count:
      `cross`  jump the slots until he is past CROSS_TO. The window is
               two-sided and the target is LED, because the plate moves during
               the flight; both numbers were measured by driving it.
      `fall`   hold right and stop jumping. He walks off the next edge, which
               is the only honest way to end a platformer demo.
      `wipe`   hands off entirely while the mosaic runs. It ends when the state
               byte goes idle, which is also when he is back on the spawn.
    """

    def __init__(self):
        self.started = False
        self.done = False
        self.stage = "cross"
        self.n = 0

    def _step(self, r, **press):
        if press:
            r.frame_step(1, **press)
            r.frame_step(STEP - 1)
        else:
            r.frame_step(STEP)

    def _play_step(self, r):
        """Advance STEP frames, RE-DECIDING EACH ONE.

        The recorder captures every STEP'th frame, and the first version of
        this drive decided once per capture — one pad held for three frames.
        That is fine for a clip that only watches, and useless for one that
        plays: a jump is edge-triggered and a landing window is twelve pixels,
        so deciding at a third of the frame rate mistimes both. The take ran
        out of its capture ceiling without ever crossing.

        So the capture cadence and the decision cadence are separated here. The
        gif still gets one frame in three; the knight gets an answer every
        frame, which is what the ROM is asking for.
        """
        for _ in range(STEP):
            r.frame_step(1, **self._play(r))

    def _play(self, r):
        """The pad for this capture, from where the knight actually is."""
        if self.stage == "wipe":
            return {}                       # ...hands off: it is not his frame
        pad = {"right": True}
        if self.stage != "cross":
            return pad                      # ...`fall`: no more jumps
        slot = _u16(r, KN_PLATE)
        if slot == AIRBORNE:
            return pad
        phase = _u16(r, PHASE)
        if slot + 1 < SLOTS:
            drop = _slot_top(slot + 1, phase + JUMP_LEAD) - _slot_top(slot, phase)
            if not -JUMP_UP <= drop <= JUMP_DOWN:
                return {}                   # ...WAIT, standing still. Holding
                                            #    right through a wait is not
                                            #    waiting: it walks him off the
                                            #    edge, which is how every early
                                            #    version of this drive died
        if _u16(r, KN_X) - SLOT_COL[slot] * 8 < WALK_IN:
            return pad                      # ...walk further onto it first
        pad["a"] = True
        return pad

    def __call__(self, r, i):
        self.n += 1
        if not self.started:
            if _at_rest(r, TITLE):
                return self._step(r, start=True)        # -> works
            if _at_rest(r, WORKS):
                self.started = True
                self.n = 0
            return self._step(r)

        wiping = r.read_bytes(W, MOS_CTL, 1)[0] != 0
        if self.stage == "cross" and _u16(r, KN_X) >= CROSS_TO:
            self.stage = "fall"
        elif self.stage == "fall" and wiping:
            self.stage = "wipe"
        elif self.stage == "wipe" and not wiping:
            self.done = True                # ...he is back on the spawn plate

        return self._play_step(r)


def make_drive():
    return Drive()
