"""The arena shooter's three cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy: the
S-DSP voice. `VxSRCN` says which sample is keyed, `VxENVX > 0` says it is
SOUNDING. Instrument -> SRCN is the project file's instrument ORDER: tri_bass
0, square_lead 1, pluck 2, step 3, bell 4, saw 5, kick 6.

This rail's game.toml used to decline audio because "adding a soundtrack would
be content it does not have". That was true when it was written; the Phase 1
pass built the content, so the reason expired rather than the rail changing.

STATED LIMIT, up front: `explosion` and `hit` are BOTH voiced by `step`
(sound-effects.txt), so on this surface a chaser dying and the player being
caught are not separable by instrument — and unlike brawler's pair, both also
take the noise generator, so the noise mask does not separate them either.
What is asserted is that the two SEPARABLE cues sound (`laser` is the only
`saw` on this rail) and that the events behind them actually happened, read
from the game's own counters. The explosion's own shape is asserted elsewhere,
on the shmup, by test_sfx_vocabulary.
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
STEP, SAW = 3, 5
FRAMES = 1200


def _syms(*names):
    inc = (SUPERFORGE / "build" / "mo" / "engine_state_arena.inc").read_text()
    out = []
    for n in names:
        m = re.search(rf"^{n}\s*=\s*\$([0-9A-Fa-f]+)", inc, re.M)
        assert m, f"{n} is not in build/mo/engine_state_arena.inc"
        out.append(int(m.group(1), 16))
    return out


@pytest.fixture(scope="module")
def oshoot():
    rom = SUPERFORGE / "build" / "m7_oshoot.sfc"
    assert rom.exists(), "build/m7_oshoot.sfc not built — run `make m7_oshoot` first"
    kills, hits = _syms("US_KILLS", "US_HITS")
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(rom), frames=300)
    u = lambda a: int.from_bytes(r.read_bytes(WRAM, a, 2), "little")  # noqa: E731
    k0, h0, rows = u(kills), u(hits), []
    for i in range(FRAMES):
        # spin, walk, and fire on a rising edge every six frames
        r.frame_step(1, a=(i % 6 < 2), left=(i % 120 < 60),
                     right=(i % 120 >= 60), up=(i % 40 < 20))
        d = r.read_bytes(DSP, 0, 128)
        rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])
    k1, h1 = u(kills), u(hits)       # BEFORE stop: the runner is gone after
    r.stop()
    return {"rows": rows, "kills": (k0, k1), "hits": (h0, h1)}


def _heard(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


def test_the_drive_actually_fights(oshoot):
    """Non-vacuity for both cue cases — see the module docstring."""
    k0, k1 = oshoot["kills"]
    assert k1 > k0, (
        f"US_KILLS stayed at {k0} across {FRAMES} frames — the drive shot "
        f"nothing down, so the explosion case is asserting nothing. The drive "
        f"has rotted, not the audio")


def test_the_gun_is_audible(oshoot):
    """`laser` is voiced by saw, and nothing else on this rail uses it."""
    assert _heard(oshoot["rows"], SAW) > 0, (
        "no saw voice ever sounded on an SFX channel — the gun is not "
        "reaching the chip")


def test_the_kill_is_audible(oshoot):
    """`explosion` is voiced by step. So is `hit` — see the module's limit."""
    assert _heard(oshoot["rows"], STEP) > 0, (
        "US_KILLS rose, so chasers died, but no step voice ever sounded — "
        "neither the explosion nor the contact is reaching the chip")


@pytest.fixture(scope="module")
def saturating():
    """A drive that MASHES, so the bolt pool actually fills.

    This exists because the case below was vacuous without it. The main drive
    presses on a rising edge every six frames, and at MO_BUL_N = 8 slots with
    MO_BUL_LIFE = 90 frames the pool never fills at that rate — so moving the
    gun cue above the pool-full bail changed the ROM (md5 checked) and changed
    nothing observable. At every SECOND frame the pool saturates and the two
    separate cleanly: 30% of frames clean against 87% planted.
    """
    rom = SUPERFORGE / "build" / "m7_oshoot.sfc"
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(rom), frames=300)
    live = 0
    for i in range(900):
        r.frame_step(1, a=(i % 2 < 1), left=(i % 120 < 60), right=(i % 120 >= 60))
        d = r.read_bytes(DSP, 0, 128)
        if any(d[v * 0x10 + 8] and d[v * 0x10 + 4] == SAW for v in SFX_VOICES):
            live += 1
    r.stop()
    return live / 900


def test_a_swallowed_shot_makes_no_sound(saturating):
    """The gun cue sits BELOW the pool-full bail, so it cannot get ahead of the pool.

    `do_fire` claims a bolt slot and bails on `bmi` when the pool is full. A
    cue above that bail sounds on every press regardless of whether a bolt
    exists — which is both wrong and, on a rail whose gun is its subject,
    loud. Measured under a drive that presses every second frame: 30% of
    frames with the cue below the bail, 87% with it above. The bar sits
    between, far from both.
    """
    assert saturating < 0.55, (
        f"the gun sounds on {saturating:.0%} of frames while the bolt pool is "
        f"saturated — presses that spawn nothing are still making a noise, so "
        f"the cue is above the pool-full bail")
