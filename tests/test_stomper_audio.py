"""The stomper's cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy: the
S-DSP voice. `VxSRCN` says which sample is keyed (the queue byte is consumed
and reset inside the same frame, so it is unreadable at a frame boundary) and
`VxENVX > 0` says the voice is SOUNDING.

Instrument -> SRCN is the project file's instrument ORDER
(assets/audio/slice_b.terrificaudio): tri_bass 0, square_lead 1, pluck 2,
step 3, bell 4, saw 5, kick 6.

THE FIXTURE DIAGNOSES ITSELF. The drive has to actually land a stomp for the
kill cue to mean anything, and a stomp needs the player falling onto an enemy
that is patrolling a lane 80 px left of spawn. Three earlier drive geometries
produced zero kills — two swept symmetrically around spawn and never reached
the lane, and one held left and pinned the player against the wall at x=8
while the enemy patrolled 94..152 out of reach. All three would have passed a
bare "is the bell audible" test by never testing it. So the fixture reads the
game's own US_FOES counter and the assertion is that it FELL: a drive that
stops landing stomps fails loudly instead of going quiet.

STATED LIMIT: the `hurt` cue is not asserted. `hit` and `thud` are both voiced
by `step` (sound-effects.txt), so on this surface they are indistinguishable,
and forcing a hurt without also forcing a stomp needs a drive that approaches
an enemy without ever falling onto it. What IS asserted is that the two cues
which can be told apart — the take-off and the kill — both sound, and that the
step voice's cadence is the arc's rather than the frame's.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
WRAM = MemoryType.SnesWorkRam
SFX_VOICES = (6, 7)
SQUARE_LEAD, STEP, BELL = 1, 3, 4
FRAMES = 1200


def _foes_addr():
    """US_FOES from the emitted scene map — never hardcoded.

    A probe earlier in this sprint hardcoded a scene address, measured zero
    events for a whole run, and reported the rail as broken. The map is the
    only thing that knows where the counter is.
    """
    import re
    inc = (SUPERFORGE / "build" / "st" / "engine_state_play.inc").read_text()
    m = re.search(r"^US_FOES\s*=\s*\$([0-9A-Fa-f]+)", inc, re.M)
    assert m, "US_FOES is not in build/st/engine_state_play.inc"
    return int(m.group(1), 16)


@pytest.fixture(scope="module")
def stomper():
    rom = SUPERFORGE / "build" / "stomper.sfc"
    assert rom.exists(), "build/stomper.sfc not built — run `make stomper` first"
    foes = _foes_addr()
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(rom), frames=300)
    r.frame_step(3, start=True)                      # title -> play
    r.frame_step(3)
    r.frame_step(120)                                # fade + enter, settle
    u16 = lambda a: int.from_bytes(r.read_bytes(WRAM, a, 2), "little")  # noqa: E731
    before = u16(foes)
    rows = []
    for i in range(FRAMES):
        # walk into the patrol lane, then hover inside it, jumping steadily.
        left = i < 90 or (i >= 90 and i % 48 < 24)
        right = i >= 90 and i % 48 >= 24
        r.frame_step(1, a=(i % 30 < 3), left=left, right=right)
        d = r.read_bytes(DSP, 0, 128)
        rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])
    after = u16(foes)
    r.stop()
    return {"rows": rows, "foes_before": before, "foes_after": after}


def _live(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


def test_the_drive_actually_stomps_something(stomper):
    """Non-vacuity for the kill case — see the module docstring."""
    assert stomper["foes_after"] < stomper["foes_before"], (
        f"US_FOES stayed at {stomper['foes_before']} across {FRAMES} frames — "
        f"the drive never landed a stomp, so the kill-cue case below is "
        f"asserting nothing. The drive geometry has rotted, not the audio")


def test_the_take_off_is_audible(stomper):
    """`jump` is voiced by square_lead (sound-effects.txt)."""
    assert _live(stomper["rows"], SQUARE_LEAD) > 0, (
        "no square_lead voice ever sounded on an SFX channel — the take-off "
        "cue never reached the chip")


def test_the_kill_confirms_with_its_own_voice(stomper):
    """`pickup` is voiced by bell, and nothing else on this rail uses it.

    The kill is deliberately NOT an impact: `hit` and `thud` are both `step`,
    so scoring a stomp with either would be indistinguishable from being hurt
    by one — to the test, and to the player.
    """
    assert _live(stomper["rows"], BELL) > 0, (
        "US_FOES fell, so a stomp landed, but no bell voice ever sounded — "
        "the kill cue is not reaching the chip")


def test_the_landing_sounds_once_per_landing_not_once_per_frame(stomper):
    """The cadence is the arc's, not the frame's.

    Both writers of US_GROUNDED run on every frame the box rests on floor, so
    a landing cue placed on the state rather than the edge re-sounds while the
    player stands still. Measured on jumper, whose helper is the same shape:
    8% of frames with the edge test, 51% without it.
    """
    frac = _live(stomper["rows"], STEP) / len(stomper["rows"])
    assert frac < 0.25, (
        f"the step voice is live on {frac:.0%} of frames — the landing cue is "
        f"firing off the GROUNDED STATE rather than the edge into it")
