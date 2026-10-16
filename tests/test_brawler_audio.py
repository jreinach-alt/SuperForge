"""The brawler's three cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy: the
S-DSP voice. `VxSRCN` says which sample is keyed, `VxENVX > 0` says it is
SOUNDING, and `NON` ($3D) says which voices are taking the noise generator.

THREE EVENTS, AND TWO OF THEM SHARE A SAMPLE. The swing landing takes `hit`,
the player taking damage takes `thud`, and both are voiced by `step`
(sound-effects.txt) — so SRCN alone cannot tell dealing a blow from receiving
one. The KO deliberately takes `chime` (bell) rather than a third thump, so a
win is never mistaken for a hit, by the test or by the player.

What separates `hit` from `thud` is that hit OPENS WITH A NOISE TRANSIENT
(`play_noise 14 sn 3`) and thud does not. That is audible, and on the chip it
is readable: the voice appears in NON while the transient plays. Nothing else
on this rail uses the noise generator, so a voice in NON is a landed swing.

THE DRIVE IS CLOSED-LOOP and has to be: this rail is a fight, so a drive that
does not track its opponent gets killed rather than winning. It reads the
foe's position and lane every frame, closes to swing range, matches the lane,
and swings only when no swing is already running (US_ATTACKT == 0). An earlier
authored drive spent its whole budget dying with the player at hp 0 before the
fight had resolved anything — and the boot matters too: 426 idle frames is
long enough for the foe to land all three hits, so the drive starts at frame
90, right after the fade, with hp and FOE both still at 3.
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
NON = 0x3D
SFX_VOICES = (6, 7)
STEP, BELL = 3, 4
FRAMES = 1800


def _syms(*names):
    inc = (SUPERFORGE / "build" / "br" / "engine_state_fight.inc").read_text()
    out = []
    for n in names:
        m = re.search(rf"^{n}\s*=\s*\$([0-9A-Fa-f]+)", inc, re.M)
        assert m, f"{n} is not in build/br/engine_state_fight.inc"
        out.append(int(m.group(1), 16))
    return out


@pytest.fixture(scope="module")
def brawler():
    rom = SUPERFORGE / "build" / "brawler.sfc"
    assert rom.exists(), "build/brawler.sfc not built — run `make brawler` first"
    px, py, ex, ey, hp, wins, at = _syms(
        "US_PX", "US_PY", "US_EX", "US_EY", "US_HP", "US_WINS", "US_ATTACKT")
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(rom), frames=90)          # right after the fade, hp/FOE = 3
    u = lambda a: int.from_bytes(r.read_bytes(WRAM, a, 2), "little")  # noqa: E731
    hp0, wins0, rows = u(hp), u(wins), []
    for _ in range(FRAMES):
        a, b, c, d_, t = u(px), u(py), u(ex), u(ey), u(at)
        r.frame_step(1, right=a < c - 10, left=a > c + 10,
                     down=b < d_ - 2, up=b > d_ + 2,
                     a=(abs(a - c) <= 22 and abs(b - d_) <= 8 and t == 0))
        v = r.read_bytes(DSP, 0, 128)
        rows.append(([(v[n * 0x10 + 4], v[n * 0x10 + 8]) for n in SFX_VOICES],
                     v[NON]))
    hp1, wins1 = u(hp), u(wins)          # BEFORE stop: the runner is gone after
    r.stop()
    return {"rows": rows, "hp": (hp0, hp1), "wins": (wins0, wins1)}


def _heard(rows, srcn):
    return sum(1 for voices, _ in rows if any(s == srcn and e for s, e in voices))


def test_the_fight_actually_resolves(brawler):
    """Non-vacuity for everything below: a KO happened and damage was taken."""
    w0, w1 = brawler["wins"]
    h0, h1 = brawler["hp"]
    assert w1 > w0, (
        f"WINS stayed at {w0} across {FRAMES} frames — the drive never landed "
        f"a KO, so the chime case is asserting nothing. The drive has rotted, "
        f"not the audio")
    assert h1 < h0, (
        f"HP stayed at {h0} — the player was never hit, so nothing on this "
        f"drive could have fired `thud`")


def test_the_impacts_are_audible(brawler):
    """`hit` and `thud` are both voiced by step."""
    assert _heard(brawler["rows"], STEP) > 0, (
        "no step voice ever sounded on an SFX channel — neither the landed "
        "swing nor the damage taken is reaching the chip")


def test_the_ko_confirms_with_its_own_voice(brawler):
    """`chime` is bell, and nothing else on this rail uses it.

    The KO is deliberately not a third impact: `hit` and `thud` already share
    `step`, so a thump for the win would be indistinguishable from either.
    """
    assert _heard(brawler["rows"], BELL) > 0, (
        "WINS rose, so a KO landed, but no bell voice ever sounded — the KO "
        "cue is not reaching the chip")


def test_the_landed_swing_carries_its_noise_transient(brawler):
    """What tells dealing a blow from taking one, on a shared sample.

    `hit` opens with `play_noise 14 sn 3` and `thud` does not, so the swing's
    landing puts its voice in NON for the length of the transient. Nothing
    else on this rail takes the noise generator, so a voice there IS a landed
    swing — the one reading that separates the two `step` cues.
    """
    noisy = sum(1 for voices, non in brawler["rows"]
                if any(non & (1 << v) for v in SFX_VOICES))
    assert noisy > 0, (
        "no SFX voice ever appeared in the noise mask — `hit`'s transient "
        "never played, so what sounded on the step voice was `thud` alone and "
        "the landed swing has no cue")
