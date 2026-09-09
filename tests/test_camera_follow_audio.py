"""The follow-camera rail's footstep, on the chip that plays it.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy: the
S-DSP voice. `VxENVX > 0` on an SFX channel says the voice is SOUNDING.

THIS RAIL WALKS FREELY IN WORLD PIXELS, so there is no step COMMIT to hang a
cue on. `move_player` is LEVEL-triggered — the pad is held to walk, and it
reads ES_INP_CUR, never ES_INP_PRESS — so "is moving" is true on every held
frame and a cue there fires at 60 Hz. state.toml's `cell` is the edge: the
16 px stride the player last occupied, and the footstep is its CHANGE. Same
latch as maze at the same 2 px/frame, and 16 px is the stride the EAR wanted
there (8 px put the voice on 63% of walking frames).

THREE DRIVES, and the third is the sharp one. Walking must sound; standing
still must be silent; and SHOVING INTO THE WORLD EDGE, once the corner is
reached, must be silent too. That last is stronger than maze's answer and the
difference is mechanism: maze SLIDES along a wall, so a diagonal shove keeps
travelling and should keep stepping, while this rail CLAMPS — a pinned player
does not move, so no stride changes and nothing may sound. It is the case that
catches a cue placed on held input or on the clamp arms, both of which are
re-entered every frame the pad is held.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
SFX_VOICES = (6, 7)


def _rom():
    p = SUPERFORGE / "build" / "camera_follow.sfc"
    assert p.exists(), "build/camera_follow.sfc not built"
    return str(p)


def _live(r, drive, frames):
    n = 0
    for i in range(frames):
        drive(r, i)
        d = r.read_bytes(DSP, 0, 128)
        if any(d[v * 0x10 + 8] for v in SFX_VOICES):
            n += 1
    return n / frames


@pytest.fixture(scope="module")
def walking():
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    f = _live(r, lambda rr, i: rr.frame_step(
        1, right=(i % 80 < 40), left=(i % 80 >= 40),
        down=(i % 160 < 80), up=(i % 160 >= 80)), 600)
    r.stop()
    return f


@pytest.fixture(scope="module")
def idle():
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    f = _live(r, lambda rr, i: rr.frame_step(1), 300)
    r.stop()
    return f


@pytest.fixture(scope="module")
def cornered():
    """Shove up-left for 300 frames to REACH the corner, then measure 300 more.

    Measuring from frame 0 would fold in the journey — the player crosses real
    strides on the way and should sound while it does. 9% of the whole shove
    is that travel; the settled window is what the claim is about.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    for _ in range(300):
        r.frame_step(1, up=True, left=True)
    f = _live(r, lambda rr, i: rr.frame_step(1, up=True, left=True), 300)
    r.stop()
    return f


def test_walking_makes_footsteps(walking):
    """Measured at 0.27 — about four steps a second at CF_SPEED = 2."""
    assert walking > 0.10, (
        f"the step voice is live on {walking:.0%} of walking frames — the "
        f"footstep is not reaching the chip at all")


def test_standing_still_is_silent(idle):
    """An exact zero: nothing else on this rail queues anything."""
    assert idle == 0.0, (
        f"the step voice is live on {idle:.0%} of frames with NO input — the "
        f"cue is firing off position or off the tick, not off a stride change")


def test_a_pinned_player_is_silent(cornered):
    """The clamp holds the player still, so no stride changes and none sound.

    Exact, and stronger than maze's answer to the same drive: that rail slides
    along a wall and keeps travelling, this one clamps. A cue on held input or
    on either clamp arm would sound here on every frame, because both are
    re-entered for as long as the pad is held.
    """
    assert cornered == 0.0, (
        f"the step voice is live on {cornered:.0%} of frames while the player "
        f"is clamped in the corner and cannot move — the cue is on the INPUT "
        f"or on the clamp, not on the stride")
