"""The Phase 2 small rails' cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy: the
S-DSP voice. `VxSRCN` says which sample is keyed (the queue byte is consumed
and reset inside the same frame, so it is unreadable at a frame boundary) and
`VxENVX > 0` says the voice is SOUNDING. Instrument -> SRCN is the project
file's instrument ORDER: tri_bass 0, square_lead 1, pluck 2, step 3, bell 4,
saw 5, kick 6.

THE DRIVES ARE CLOSED-LOOP, AND THAT IS THE POINT OF THIS MODULE. Both rails
here fire their cue only on CONTACT — sprite_game when the player box overlaps
the dot, patrol when it overlaps a patroller — and an open-loop input sweep
does not reliably produce contact. Two did not produce ANY: a sweep around
sprite_game's spawn never met a dot at one of four presets, and a sweep on
patrol never met an enemy. Both would have passed a bare "is it audible" test
by never testing it. So each drive reads the game's own positions every frame
and steers toward the target, and each fixture reads the game's own counter
(US_SCORE, US_HITS) so a drive that stops producing events fails LOUDLY
instead of going quiet.

Addresses come from the emitted scene maps, never hardcoded — a probe earlier
in this sprint hardcoded one, measured zero events for a whole run, and
reported the rail as broken.
"""
import re
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
WRAM = MemoryType.SnesWorkRam
SFX_VOICES = (6, 7)
STEP, BELL = 3, 4
FRAMES = 900


def _syms(subdir, *names):
    inc = (SUPERFORGE / "build" / subdir / "engine_state_play.inc").read_text()
    out = []
    for n in names:
        m = re.search(rf"^{n}\s*=\s*\$([0-9A-Fa-f]+)", inc, re.M)
        assert m, f"{n} is not in build/{subdir}/engine_state_play.inc"
        out.append(int(m.group(1), 16))
    return out


def _rom(name):
    p = SUPERFORGE / "build" / f"{name}.sfc"
    assert p.exists(), f"{p} not built — run `make {name}` first"
    return str(p)


def _heard(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


@pytest.fixture(scope="module")
def sprite_game():
    """Steer straight at the dot, every frame, from the dot's own position."""
    px, py, dx, dy, sc = _syms("sprg", "US_PX", "US_PY", "US_DOT_X",
                               "US_DOT_Y", "US_SCORE")
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom("sprite_game"), frames=300)
    u = lambda a: int.from_bytes(r.read_bytes(WRAM, a, 2), "little")  # noqa: E731
    before, rows = u(sc), []
    for _ in range(FRAMES):
        a, b, c, d_ = u(px), u(py), u(dx), u(dy)
        r.frame_step(1, right=a < c, left=a > c, down=b < d_, up=b > d_)
        d = r.read_bytes(DSP, 0, 128)
        rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])
    after = u(sc)
    r.stop()
    return {"rows": rows, "before": before, "after": after}


@pytest.fixture(scope="module")
def patrol():
    """Walk into enemy 1, tracking its patrol, and take the knockbacks."""
    px, e1x, hits = _syms("pat", "US_PX", "US_E1X", "US_HITS")
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom("patrol"), frames=300)
    r.frame_step(3, start=True)
    r.frame_step(3)
    r.frame_step(120)
    u = lambda a: int.from_bytes(r.read_bytes(WRAM, a, 2), "little")  # noqa: E731
    before, rows = u(hits), []
    for i in range(FRAMES):
        p, e = u(px), u(e1x)
        r.frame_step(1, right=p < e, left=p > e, a=(i % 40 < 3))
        d = r.read_bytes(DSP, 0, 128)
        rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])
    after = u(hits)
    r.stop()
    return {"rows": rows, "before": before, "after": after}


def test_the_dot_chaser_actually_catches_something(sprite_game):
    """Non-vacuity for the cue case below — see the module docstring."""
    assert sprite_game["after"] > sprite_game["before"], (
        f"US_SCORE stayed at {sprite_game['before']} across {FRAMES} frames — "
        f"the drive never caught the dot, so the cue case is asserting "
        f"nothing. The drive has rotted, not the audio")


def test_the_catch_is_audible(sprite_game):
    """`pickup` is voiced by bell (sound-effects.txt), and nothing else here."""
    assert _heard(sprite_game["rows"], BELL) > 0, (
        "US_SCORE rose, so catches landed, but no bell voice ever sounded — "
        "the catch cue is not reaching the chip")


def test_the_patrol_actually_catches_the_player(patrol):
    """Non-vacuity for the cue case below."""
    assert patrol["after"] > patrol["before"], (
        f"US_HITS stayed at {patrol['before']} across {FRAMES} frames — the "
        f"drive never walked into a patroller, so the cue case is asserting "
        f"nothing. The drive has rotted, not the audio")


def test_the_knockback_is_audible(patrol):
    """`hit` is voiced by step (sound-effects.txt)."""
    assert _heard(patrol["rows"], STEP) > 0, (
        "US_HITS rose, so knockbacks landed, but no step voice ever sounded — "
        "the knockback cue is not reaching the chip")
