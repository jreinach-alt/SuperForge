"""The stomper's cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy: the
S-DSP voice. `VxSRCN` says which sample is keyed (the queue byte is consumed
and reset inside the same frame, so it is unreadable at a frame boundary) and
`VxENVX > 0` says the voice is SOUNDING.

Instrument -> SRCN is the project file's instrument ORDER
(assets/audio/slice_b.terrificaudio): tri_bass 0, square_lead 1, pluck 2,
step 3, bell 4, saw 5, kick 6.

THE FIXTURE DIAGNOSES ITSELF, AND THAT IS HOW THIS DRIVE GOT FIXED. A stomp
needs the player falling onto an enemy patrolling a lane 80 px left of spawn.
Three authored geometries produced zero kills — two swept symmetrically around
spawn and never reached the lane, one held left and pinned the player against
the wall at x=8 while the enemy patrolled 94..152 out of reach. A fourth landed
exactly one kill, passed locally, and then FAILED IN THE LANDING GATE'S CLONE:
an authored geometry that only just works is a coin-flip against a harness that
re-seeds power-on RAM per load. Every one of them would have passed a bare "is
the bell audible" test by never testing it.

`test_the_drive_actually_stomps_something` is what caught that, by name, and it
is why the drive is now CLOSED-LOOP: it reads the live enemy's position every
frame, walks at it, and jumps when grounded and within the arc's reach, so
landing a stomp is a consequence of the geometry rather than a coincidence of
it. When both are dead it falls back to jumping in place, which keeps the
landing cadence the last case measures meaningful.

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


def _syms(*names):
    """Scene addresses from the emitted map — never hardcoded.

    A probe earlier in this sprint hardcoded a scene address, measured zero
    events for a whole run, and reported the rail as broken. The map is the
    only thing that knows where these live.
    """
    import re
    inc = (SUPERFORGE / "build" / "st" / "engine_state_play.inc").read_text()
    out = []
    for n in names:
        m = re.search(rf"^{n}\s*=\s*\$([0-9A-Fa-f]+)", inc, re.M)
        assert m, f"{n} is not in build/st/engine_state_play.inc"
        out.append(int(m.group(1), 16))
    return out


@pytest.fixture(scope="module")
def stomper():
    rom = SUPERFORGE / "build" / "stomper.sfc"
    assert rom.exists(), "build/stomper.sfc not built — run `make stomper` first"
    foes, px, e1x, e1a, e2x, e2a, gr = _syms(
        "US_FOES", "US_PX", "US_E1X", "US_E1ALIVE", "US_E2X", "US_E2ALIVE",
        "US_GROUNDED")
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(rom), frames=300)
    r.frame_step(3, start=True)                      # title -> play
    r.frame_step(3)
    r.frame_step(120)                                # fade + enter, settle
    u = lambda a: int.from_bytes(r.read_bytes(WRAM, a, 2), "little")  # noqa: E731
    before = u(foes)
    rows = []
    for i in range(FRAMES):
        here, grounded = u(px), u(gr)
        target = u(e1x) if u(e1a) else (u(e2x) if u(e2a) else None)
        if target is None:                           # both down: keep hopping
            r.frame_step(1, a=(i % 30 < 3), left=(i % 60 < 30),
                         right=(i % 60 >= 30))
        else:
            r.frame_step(1, right=here < target - 1, left=here > target + 1,
                         a=(grounded != 0 and abs(here - target) < 20))
        d = r.read_bytes(DSP, 0, 128)
        rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])
    after = u(foes)
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
