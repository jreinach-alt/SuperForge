"""The scroller's three cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For a
sound effect that is the S-DSP voice: `VxSRCN` says which sample is keyed (the
queue byte is consumed and reset inside the same frame, so it is unreadable at
any frame boundary) and `VxENVX > 0` says the voice is actually SOUNDING.

THREE CUES, and each one is a different answer to the same question — when is
this event an INSTANT rather than a state?

  * `jump` (square_lead) needs no edge test of its own. `do_jump` already gates
    on ES_INP_PRESS, the rising edge, AND on being grounded, so the take-off
    line runs at most once per airborne arc by construction.
  * `thud` (step) needs one, and this rail needs it more than `jumper` does:
    THREE writers re-establish US_GROUNDED here rather than two — the ground
    probe's standing arm, the solid landing snap, and the ONE-WAY platform's
    snap — and every one of them runs on every frame the box rests. All three
    route through `sr_ground`, which sounds only on the 0 -> 1 transition.
  * `chime` (bell) needs no edge test either, and finding that out is the
    reason this module is worth reading. It was written WITH one, on the
    belief that `goal_check` re-probes the pillar every frame the player
    stands on it. The plant that should have proved that guard load-bearing —
    delete it, expect the tail case to go red — PASSED, because `tick` gates
    on US_STATE at its very top and jumps past `goal_check` entirely once
    won. The guard could never fire. It is gone, and the comment where it
    stood says so.

THE TAIL CASE SURVIVED THAT, and is the reason the module keeps driving for
300 frames past the win: the invariant it asserts — a won game goes and stays
silent — is real whatever mechanism delivers it, and it is falsifiable by the
mistake an author is actually liable to make, which is queueing the cue on the
`@draw` path that DOES run every frame. Planted there it reads 180 of the 200
tail frames. A won scroller is a permanent state, so the honest bar is zero.

The general rule this cost, filed in dx_paper_cuts: A GUARD THAT CANNOT FIRE
READS AS LOAD-BEARING. The only thing that told the two apart was the plant.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
W = MemoryType.SnesWorkRam
O = MemoryType.SnesSpriteRam
SFX_VOICES = (6, 7)
SQUARE_LEAD, STEP, BELL = 1, 3, 4   # instrument order in slice_b.terrificaudio

import json                                                        # noqa: E402
_MAP = json.loads((SUPERFORGE / "build" / "sr" / "symbol_map.json").read_text())
_DP = {p["sym"]: p["start"]
       for p in _MAP["scenes"]["run"]["placements"] if p["class"] == "dp"}
DP_PX, DP_STATE = _DP["US_PX"], _DP["US_STATE"]

ARC_FRAMES = 900
TAIL_FRAMES = 300           # driven past the win; the last 200 must be silent


def _rom():
    p = SUPERFORGE / "build" / "scroll_run.sfc"
    assert p.exists(), "build/scroll_run.sfc not built — run `make scroll_run`"
    return str(p)


def _live(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


class _Drive:
    """One frame at a time, sampling the DSP on every one of them.

    The bot below steers from WRAM and OAM inside nested loops; if only the
    outer loop sampled, the frames a cue actually sounds on could fall in a
    gap and the count would be of the sampling, not of the sound.
    """

    def __init__(self, runner):
        self.r = runner
        self.rows = []

    def step(self, **pad):
        self.r.frame_step(1, **pad)
        d = self.r.read_bytes(DSP, 0, 128)
        self.rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])

    def wx(self):
        b = self.r.read_bytes(W, DP_PX, 2)
        return b[0] | (b[1] << 8)

    def st(self):
        b = self.r.read_bytes(W, DP_STATE, 2)
        return b[0] | (b[1] << 8)

    def oam_y(self):
        return self.r.read_bytes(O, 0, 2)[1]


@pytest.fixture(scope="module")
def arc():
    """A jump every 60 frames — once a second, and slower than the arc takes.

    That is what gives the cadence case something to fail against: the box is
    demonstrably grounded and at rest for most of the drive, and those resting
    frames are exactly where a state-based landing cue would sound.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    d = _Drive(r)
    for i in range(ARC_FRAMES):
        d.step(a=(i % 60 < 3), right=(i % 120 < 60), left=(i % 120 >= 60))
    r.stop()
    return d.rows


def test_the_take_off_is_audible(arc):
    """`jump` is voiced by square_lead (assets/audio/sound-effects.txt)."""
    assert _live(arc, SQUARE_LEAD) > 0, (
        "no square_lead voice ever sounded on an SFX channel — the take-off "
        "cue never reached the chip")


def test_the_landing_is_audible(arc):
    """`thud` is voiced by step (assets/audio/sound-effects.txt)."""
    assert _live(arc, STEP) > 0, (
        "no step voice ever sounded on an SFX channel — the landing cue "
        "never reached the chip")


def test_the_landing_sounds_once_per_landing_not_once_per_frame(arc):
    """THREE writers of US_GROUNDED, one edge test.

    The bar is `jumper`'s, and so is the reasoning: the thud's own decay sets
    the ceiling on a correct rail, while a cue on the STATE would sound on
    every resting frame of a drive that spends most of its time resting. The
    bar sits between those by a wide margin, so neither the effect's length
    nor the drive's exact geometry can flip it.
    """
    frac = _live(arc, STEP) / len(arc)
    assert frac < 0.25, (
        f"the thud voice is live on {frac:.0%} of frames — the landing cue is "
        f"firing off the GROUNDED STATE rather than the edge into it, so it "
        f"re-sounds every frame the box rests. Three sites store US_GROUNDED "
        f"here; all three must go through `sr_ground`")


def _bot_run_to_goal(d):
    """The reference module's own closed-loop bot, sampling as it goes.

    Ported from `tests/test_scroll_run.py::_bot_run_to_goal` — navigation reads
    WRAM and OAM, one frame per iteration, so the trajectory is a function of
    the machine rather than of a hand-tuned script that rots. Every advance
    goes through `_Drive.step`, including the ones inside `coast` and the two
    alignment loops, so no frame the chime could sound on is unsampled.
    """
    def coast(hold_right):
        for _ in range(60):
            d.step(right=hold_right)
            if d.st() == 1 or (d.oam_y() in (168, 200)):
                break

    last, stall = d.wx(), 0
    for _ in range(1200):
        if d.st() == 1:
            return True
        x, y = d.wx(), d.oam_y()
        if y == 200 and 330 <= x <= 356:
            while d.wx() > 252:
                d.step(left=True)
            while d.wx() < 258:
                d.step(right=True)
            for _ in range(6):
                d.step(right=True, a=True)
            coast(hold_right=True)
            continue
        if y == 168 and x >= 324:
            for _ in range(6):
                d.step(right=True, a=True)
            coast(hold_right=True)
            continue
        stall = stall + 1 if x == last else 0
        last = x
        d.step(right=True, a=stall > 4)
    return False


@pytest.fixture(scope="module")
def goal():
    """Run to the goal, then keep driving for `TAIL_FRAMES` past the win.

    The tail is the case. Returns `(rows, win_index)` so the tail can be
    sliced off the same sample stream the win was found in.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    d = _Drive(r)
    won = _bot_run_to_goal(d)
    at = len(d.rows)
    for _ in range(TAIL_FRAMES):
        d.step(right=True)
    r.stop()
    assert won, (
        "the bot never reached the goal pillar — the drive rotted, so the "
        "chime cases below would be measuring a game that never won")
    return d.rows, at


def test_reaching_the_goal_is_audible(goal):
    """`chime` is voiced by bell (assets/audio/sound-effects.txt)."""
    rows, _ = goal
    assert _live(rows, BELL) > 0, (
        "no bell voice ever sounded on an SFX channel — the goal cue never "
        "reached the chip")


def test_the_goal_chimes_once_and_a_won_game_is_silent(goal):
    """The only one of the three with a bar of zero.

    A won scroller is a PERMANENT state — `tick` freezes input and the camera
    holds — so "the chime rang and then the game went quiet" is decidable
    rather than a fraction. 200 frames is over three seconds, far longer than
    the chime's own two notes, so a correct rail has decayed to nothing well
    inside the window.

    WHAT FALSIFIES IT is a cue on the always-run path: `@draw` is reached on
    every frame, won or not, and a `chime` queued there sounds on 180 of this
    200-frame tail. That is the shape the header describes — the guard inside
    `goal_check` was NOT, which is why it was deleted rather than kept "just
    in case".
    """
    rows, at = goal
    tail = rows[at + 100:]
    assert len(tail) >= 190, "the tail is too short to decide silence"
    live = _live(tail, BELL)
    assert live == 0, (
        f"the bell voice is still sounding on {live} of {len(tail)} frames "
        f"more than a second after the win — the goal cue is on a path the "
        f"rail re-enters every frame. It belongs where the win is DECIDED "
        f"(`goal_check`, which `tick` stops calling once US_STATE is 1), not "
        f"where the frame is drawn")
