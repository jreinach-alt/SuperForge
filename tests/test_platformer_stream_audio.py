"""The streaming platformer's two cues, and where they are allowed to live.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy: the
S-DSP voice. `VxSRCN` says which sample is keyed, `VxENVX > 0` says it is
SOUNDING. `jump` is voiced by square_lead and `thud` by step
(sound-effects.txt), so on this rail the two cues are separable by instrument.

THE ARCHITECTURAL POINT THIS MODULE GUARDS. Both events are computed inside
`pfs_logic`, a `role = "game_logic"` FEATURE: `pl_jump` clears PL_GROUND on the
press edge and the integrator's landing arm sets it. Queuing the cues there
would make the physics depend on `audio` — every rail composing the mechanism
would have to compose the soundtrack, with no way to take one without the
other — and would make the CHOICE of sound the feature's, when only "a jump
happened" is mechanism. So the feature stays silent and publishes PL_GROUND,
and the rail latches it in state.toml's `gnd`.

ONE LATCH GIVES BOTH CUES, because PL_GROUND's two edges are the two events:
1 -> 0 is the take-off, 0 -> 1 is the landing. That is what the balance case
below is for — it is a property of the design, not of the drive.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
SFX_VOICES = (6, 7)
SQUARE_LEAD, STEP = 1, 3


def _drive(drive, frames):
    rom = SUPERFORGE / "build" / "platformer_stream.sfc"
    assert rom.exists(), "build/platformer_stream.sfc not built"
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(rom), frames=300)
    rows = []
    for i in range(frames):
        drive(r, i)
        d = r.read_bytes(DSP, 0, 128)
        rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])
    r.stop()
    return rows


def _heard(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


@pytest.fixture(scope="module")
def running():
    """Run right and jump on a slow cadence — one arc per 45 frames."""
    return _drive(lambda r, i: r.frame_step(1, a=(i % 45 < 4), right=True), 900)


@pytest.fixture(scope="module")
def idle():
    return _drive(lambda r, i: r.frame_step(1), 300)


def test_the_take_off_is_audible(running):
    assert _heard(running, SQUARE_LEAD) > 0, (
        "no square_lead voice ever sounded — the take-off cue is not reaching "
        "the chip, so PL_GROUND's 1 -> 0 edge is not being read")


def test_the_landing_is_audible(running):
    assert _heard(running, STEP) > 0, (
        "no step voice ever sounded — the landing cue is not reaching the "
        "chip, so PL_GROUND's 0 -> 1 edge is not being read")


def test_standing_still_is_silent(idle):
    """The cue is the EDGE, and a player at rest crosses none.

    An exact zero, not a threshold: nothing else on this rail queues anything,
    so any voice here is a cue that should not exist. This is the case that
    fails if the cue is ever moved onto the STATE — PL_GROUND is 1 on every
    frame the player rests on a floor.
    """
    live = sum(1 for row in idle if any(e for _, e in row))
    assert live == 0, (
        f"an SFX voice sounds on {live} of {len(idle)} frames with NO input — "
        f"the cue is firing off PL_GROUND's VALUE rather than its edges")


def test_every_take_off_has_a_landing(running):
    """The two cues balance, because ONE latch drives both.

    A player who leaves the floor lands, so the two edges alternate and the
    voices should be heard about equally. Measured at 75 frames each. This is
    the case that catches a latch updated on one edge and not the other: the
    cue that stops being armed goes quiet while the other keeps firing, which
    neither audibility case above would notice.
    """
    j, t = _heard(running, SQUARE_LEAD), _heard(running, STEP)
    assert 0.5 <= j / t <= 2.0, (
        f"take-offs sounded on {j} frames and landings on {t} — the two edges "
        f"of one latch should alternate, so a ratio this far from 1 means one "
        f"edge is not updating the latch")
