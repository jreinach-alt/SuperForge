"""The four screen-effect rails' soundtrack, on the chip that plays it.

ONE MODULE FOR FOUR RAILS, because they make ONE claim between them and it is
the same claim four times: `heathaze`, `lakeside`, `smelter` and
`mode7_flight` compose `audio` for MUSIC ONLY. None of them has a discrete
event to sound — no landing, no kill, no arrival, nothing whose 0 -> 1 edge is
a moment — so none imports `sf_sfx_queue_c` and none declares a `prev` word.
A per-rail module would be four copies of one fixture.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For
music that is the S-DSP voice: `VxENVX > 0` says a voice is SOUNDING and
`VxSRCN` says which sample it is keyed to.

THREE CLAIMS, and the second two are what make the first mean anything:

  * THE SONG PLAYS, continuously, across a long drive. "The data is linked
    into the ROM" and "the song is playing" are different claims and only the
    second is worth making.
  * NOTHING IS SCORED ON G OR H. Those map onto voices 6 and 7, which the
    driver ducks for the duration of any sound effect. On these four rails the
    voices should be silent for a stronger reason than on the others: there is
    no cue to duck for, so a voice sounding there is a part of the song that
    would vanish the day one is added.
  * NO MUSIC VOICE IN NON. There is one noise generator and the driver zeroes
    the volume of any music channel sharing it. `slice_b_song`'s kit does not
    take it; this asserts that on every rail that loads it, not just on the
    two that loaded it first.

The last two are EQUALITIES rather than fractions, which they can be precisely
because these rails queue nothing: there is no window in which voice 6 or 7 is
legitimately busy.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
MUSIC_VOICES = tuple(range(6))      # TAD channels A-F
SFX_VOICES = (6, 7)                 # G/H, ducked while an effect plays
MUSIC_MASK = 0x3F                   # NON bits for voices 0-5
FRAMES = 420                        # seven seconds, well past the song's loop

RAILS = ("heathaze", "lakeside", "smelter", "mode7_flight")


@pytest.fixture(scope="module", params=RAILS)
def played(request):
    """Boot each rail and let it play, sampling the DSP every frame.

    No input at all: these rails are pictures, and the claim is that the
    soundtrack runs whether or not anyone touches the pad.
    """
    rom = SUPERFORGE / "build" / f"{request.param}.sfc"
    assert rom.exists(), f"{rom} missing — run `make {request.param}` first"
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(rom), frames=300)
    rows = []
    try:
        for _ in range(FRAMES):
            r.frame_step(1)
            d = r.read_bytes(DSP, 0, 128)
            rows.append(([d[v * 0x10 + 8] for v in range(8)], d[0x3D]))
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failure above would strand the NEXT module's runner and make it
        # name itself (tests/conftest.py, the parked-core guard).
        r.stop()
    return request.param, rows


def test_the_song_is_playing_for_most_of_the_drive(played):
    """Not merely audible once — CONTINUOUS.

    A song that keys on at load and then runs out of data would look alive on
    frame 1 and leave the rest silent. `slice_b_song` loops at 768 ticks and
    this drive is seven seconds, so "some music voice is sounding" should be
    true nearly always. The bar sits well below what a working song reads, so
    a tempo or loop-point change cannot flip it — but it is NOT 100%: this
    piece has a composed whole-bar rest at the end of its loop, which is the
    window `test_slice_b_audio.py` measures room B's echo tail in.
    """
    rail, rows = played
    live = sum(1 for env, _ in rows if any(env[v] for v in MUSIC_VOICES))
    frac = live / len(rows)
    assert frac > 0.80, (
        f"{rail}: a music voice is sounding on only {frac:.0%} of {len(rows)} "
        f"frames — the song is not running continuously; check that "
        f"sf_audio_tick is pumped every frame and that Tad_LoadSong ran")


def test_nothing_is_scored_where_an_effect_would_erase_it(played):
    """An EQUALITY, and on these rails it can be one.

    TAD's channels G and H map onto DSP voices 6 and 7 and the driver ducks
    them for the duration of any sound effect. These four rails queue NOTHING,
    so there is no window in which those voices are legitimately busy: any
    sounding at all is a part of the song written where a future cue would
    erase it.

    Planted — eight bars added to a `G` channel in slice_b_song.mml, the shared
    audio blob re-exported, all four ROMs relinked — this case reds on ALL FOUR
    rails and nothing else in the module moves. That is the parameterisation
    earning its place: one plant, four independent readings. The restore
    re-exports BYTE-IDENTICAL, which is the compiler's determinism observed
    rather than assumed.
    """
    rail, rows = played
    busy = [i for i, (env, _) in enumerate(rows)
            if any(env[v] for v in SFX_VOICES)]
    assert not busy, (
        f"{rail}: voices 6/7 sound on {len(busy)} of {len(rows)} frames "
        f"(first at {busy[0]}) on a rail that queues no effects at all — the "
        f"song is scored on G or H")


def test_the_kit_never_takes_the_noise_generator(played):
    """There is one noise generator, and a music channel sharing it is muted
    the moment an effect wants it (`audio-driver.asm`, the `SfxNoise` branch).

    `slice_b_song`'s kit is samples, and this asserts that on every rail that
    loads it rather than only on the two that loaded it first — the song is
    one artifact but the composition around it is four.
    """
    rail, rows = played
    bad = [(i, non) for i, (_, non) in enumerate(rows) if non & MUSIC_MASK]
    assert not bad, (
        f"{rail}: a music voice is in the noise mask on {len(bad)} frames "
        f"(first {bad[0][0]}, NON={bad[0][1]:#04x}) — that voice is silenced "
        f"whenever an effect plays noise")
