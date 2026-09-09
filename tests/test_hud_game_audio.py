"""hud_game's one cue, on the chip that plays it.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For a
sound effect that is the S-DSP voice: `VxSRCN` says which sample is keyed (the
queue byte is consumed and reset inside the same frame, so it is unreadable at
any frame boundary) and `VxENVX > 0` says the voice is actually SOUNDING.

ONE CUE AND NO LATCH, which is the whole entry for this rail. `bump_score` is
already gated on ES_INP_PRESS's A bit — the `input` feature publishes the
RISING edge, not the held state — so a `pickup` on its @bump arm runs at most
once per press however long A is held. That is the by-construction shape
`sprite_game`'s catch and `jumper`'s take-off have, and the opposite of a cue
read off a level (`maze`'s walk, `microzero`'s lap counter), which has to
declare a `prev` word.

SO THE CADENCE CASE IS THE POINT, and it is aimed at exactly the mistake this
rail invites: swapping ES_INP_PRESS for ES_INP_CUR. The drive HOLDS A for a
long stretch of every cycle, so a level-read cue would sound through all of it
while the correct one fires once per press. Both are audible; only the
fraction tells them apart.

THE SCORE IS THE DRIVE'S OWN CHECK. Every fixture here asserts the game's
counter actually moved, so a rotted drive fails on the counter rather than
going quiet on the cue and reading as a defect in the audio.
"""
import json
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
W = MemoryType.SnesWorkRam
SFX_VOICES = (6, 7)
BELL = 4                        # instrument order in slice_b.terrificaudio

_MAP = json.loads((SUPERFORGE / "build" / "hud" / "symbol_map.json").read_text())
_DP = {p["sym"]: p["start"]
       for p in _MAP["scenes"]["play"]["placements"] if p["class"] == "dp"}
DP_SCORE = _DP["US_SCORE"]

PRESSES = 15
PERIOD = 40                     # frames per press cycle...
HOLD = 24                       # ...of which this many hold A down


def _rom():
    p = SUPERFORGE / "build" / "hud_game.sfc"
    assert p.exists(), "build/hud_game.sfc not built — run `make hud_game`"
    return str(p)


@pytest.fixture(scope="module")
def pressed():
    """Press A `PRESSES` times, holding it for most of each cycle.

    The long hold is deliberate and is what the cadence case needs: 24 of
    every 40 frames have A down, so a cue read off the HELD state rather than
    the press edge has 60% of the drive to sound in, while the correct one has
    fifteen instants.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    rows = []
    try:
        before = int.from_bytes(r.read_bytes(W, DP_SCORE, 2), "little")
        for i in range(PRESSES * PERIOD):
            r.frame_step(1, a=(i % PERIOD < HOLD))
            d = r.read_bytes(DSP, 0, 128)
            rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES])
        after = int.from_bytes(r.read_bytes(W, DP_SCORE, 2), "little")
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failed read above would strand the NEXT module's runner and make it
        # name itself (tests/conftest.py, the parked-core guard).
        r.stop()
    return rows, before, after


def _live(rows, srcn):
    return sum(1 for row in rows if any(s == srcn and e for s, e in row))


def test_the_drive_actually_scored(pressed):
    """Non-vacuity, and it is the counter rather than the cue.

    `score` is PACKED BCD (+$0001 per press), so fifteen presses read $0015
    and not 15. A drive that stopped scoring — a changed control, a clamp, a
    boot that never reached the scene — fails HERE, naming the game state,
    instead of failing the audibility case below and reading as a defect in
    the sound.
    """
    _, before, after = pressed
    assert (before, after) == (0x0000, 0x0015), (
        f"the drive scored {before:#06x} -> {after:#06x}, not 0x0000 -> "
        f"0x0015 — {PRESSES} presses did not land, so the cue cases below "
        f"would be measuring a game that is not being played")


def test_scoring_is_audible(pressed):
    """`pickup` is voiced by bell (assets/audio/sound-effects.txt)."""
    rows, _, _ = pressed
    assert _live(rows, BELL) > 0, (
        "no bell voice ever sounded on an SFX channel — the score cue never "
        "reached the chip")


def test_the_cue_is_the_press_and_not_the_hold(pressed):
    """A is DOWN for 60% of this drive and the cue must not be.

    `bump_score` reads ES_INP_PRESS, the rising edge; the mistake this rail
    invites is reading ES_INP_CUR instead, which is one token away. Planted
    that way the bell sounds through every held frame — and the SCORE case
    above reds too, because holding A then scores once a frame instead of
    once a press, which is a second reading of the same defect from the game
    state rather than the chip. The bar sits far below a held cue and far
    above what fifteen short bell hits cost.
    """
    rows, _, _ = pressed
    frac = _live(rows, BELL) / len(rows)
    assert frac < 0.30, (
        f"the bell voice is live on {frac:.0%} of frames, against a drive "
        f"holding A for {HOLD}/{PERIOD} of each cycle — the score cue is "
        f"reading the HELD state (ES_INP_CUR) rather than the press edge "
        f"(ES_INP_PRESS)")
