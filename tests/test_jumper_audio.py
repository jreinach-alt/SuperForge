"""The jumper's two cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For a
sound effect that is the S-DSP voice: `VxSRCN` says which sample is keyed (the
queue byte is consumed and reset inside the same frame, so it is unreadable at
any frame boundary) and `VxENVX > 0` says the voice is actually SOUNDING.

This rail is a BALLISTIC ARC and the two cues are its two ends: `jump` at
take-off, `thud` on the landing. Both were added when audio was composed onto
the rail; before that its game.toml said "this rail is silent: nothing queues
music or SFX", which was true of the rail and never of the machine.

THE CADENCE CASE IS THE POINT OF THIS MODULE. Both writers of US_GROUNDED run
on EVERY frame the box rests on floor — the falling arm's ground probe
re-establishes the flag each frame — so a landing cue placed at either store
fires sixty times a second while the player stands still. That is a defect
this tree has already paid for once on the rpg's footstep, and it is invisible
to a test that only asks "is the thud audible": the answer is yes, far too
often. So the assertion is on the FRACTION OF FRAMES the thud voice is live,
against a drive that spends most of its time grounded.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
SFX_VOICES = (6, 7)
SQUARE_LEAD, STEP = 1, 3        # instrument order in slice_b.terrificaudio
FRAMES = 900


@pytest.fixture(scope="module")
def jumper():
    """One long drive that jumps on a slow, known cadence.

    A jump every 60 frames is once a second — deliberately slower than the
    arc takes, so the player is DEMONSTRABLY grounded and at rest for a large
    share of the drive. That is what gives the cadence case something to
    fail against: if the landing cue were on the state rather than the edge,
    those resting frames are exactly where it would sound.
    """
    rom = SUPERFORGE / "build" / "jumper.sfc"
    assert rom.exists(), "build/jumper.sfc not built — run `make jumper` first"
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(rom), frames=300)
    rows = []
    for i in range(FRAMES):
        r.frame_step(1, a=(i % 60 < 3), right=(i % 120 < 60),
                     left=(i % 120 >= 60))
        d = r.read_bytes(DSP, 0, 128)
        rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])
    r.stop()
    return rows


def _live(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


def test_the_take_off_is_audible(jumper):
    """`jump` is voiced by square_lead (sound-effects.txt)."""
    assert _live(jumper, SQUARE_LEAD) > 0, (
        "no square_lead voice ever sounded on an SFX channel — the take-off "
        "cue never reached the chip")


def test_the_landing_is_audible(jumper):
    """`thud` is voiced by step (sound-effects.txt)."""
    assert _live(jumper, STEP) > 0, (
        "no step voice ever sounded on an SFX channel — the landing cue "
        "never reached the chip")


def test_the_landing_sounds_once_per_landing_not_once_per_frame(jumper):
    """The cadence is the ARC's, not the frame's.

    Fifteen jumps in this drive, each landing once. The thud's own decay is
    what sets the ceiling: measured at roughly 8% of frames live, against the
    ~50%+ a per-frame cue would produce on a drive that spends most of its
    time resting on floor. The bar sits between those by a wide margin, so
    neither the effect's length nor the drive's exact geometry can flip it.
    """
    frac = _live(jumper, STEP) / len(jumper)
    assert frac < 0.25, (
        f"the thud voice is live on {frac:.0%} of frames — the landing cue is "
        f"firing off the GROUNDED STATE rather than the edge into it, so it "
        f"re-sounds every frame the player stands still")
