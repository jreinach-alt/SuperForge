"""`mode7_flight`'s soundtrack, on the chip that plays it.

THIS MODULE COVERED FOUR RAILS AND NOW COVERS ONE, and the shrinking is the
point rather than a retreat. `heathaze`, `lakeside`, `smelter` and
`mode7_flight` landed together as MUSIC-ONLY on one argument: a screen effect
has no discrete event whose 0 -> 1 edge is a moment, so none imports
`sf_sfx_queue_c` and none declares a `prev` word. Re-checked per rail rather
than inherited, that argument turned out to hold for exactly one of them —
the other three each had edges sitting in their own `tick` (a B toggle and a
Start in `smelter`, a Start in `heathaze`, a surf cycle whose crest is a timed
moment in `lakeside`) and each now has content and a module of its own.

**And the three passed this module the whole time they were wrong**, because
its drive presses nothing and those three boot into a title scene: the
equalities below were true of a scene with no cues in it while the rail's
actual content sat one Start press away. A case parameterised over rails is
only as strong as its weakest drive. `RAILS` is kept as a tuple so re-adding
one is a one-word change — but a rail belongs here only while it queues
NOTHING, and the day it gains a cue it needs a drive that enters the scene,
not a place in this list.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For
music that is the S-DSP voice: `VxENVX > 0` says a voice is SOUNDING and
`VxSRCN` says which sample it is keyed to.

THREE CLAIMS, and the second two are what make the first mean anything:

  * THE SONG PLAYS, continuously, across a long drive. "The data is linked
    into the ROM" and "the song is playing" are different claims and only the
    second is worth making.
  * NOTHING IS SCORED ON G OR H. Those map onto voices 6 and 7, which the
    driver ducks for the duration of any sound effect. On this rail the
    voices should be silent for a stronger reason than on the others: there
    is no cue to duck for, so a voice sounding there is a part of the song
    that would vanish the day one is added. The three rails that left carry
    the same claim in its honest form for a rail with cues — WHAT sounds on
    6/7 rather than WHETHER — in `tests/test_{heathaze,lakeside,smelter}_audio.py`.
  * NO MUSIC VOICE IN NON. There is one noise generator and the driver zeroes
    the volume of any music channel sharing it. `slice_b_song`'s kit does not
    take it, and this asserts that where the song is actually loaded.

The last two are EQUALITIES rather than fractions, which they can be precisely
because this rail queues nothing: there is no window in which voice 6 or 7 is
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

RAILS = ("mode7_flight",)     # see the header: a rail belongs here only
                              # while it queues NOTHING


@pytest.fixture(scope="module", params=RAILS)
def played(request):
    """Boot the rail and let it play, sampling the DSP every frame.

    No input at all: this rail is a picture, and the claim is that the
    soundtrack runs whether or not anyone touches the pad. That is also
    exactly why this drive could not see the other three rails' content —
    it never leaves the scene it boots into.
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
    """An EQUALITY, and on this rail it can be one.

    TAD's channels G and H map onto DSP voices 6 and 7 and the driver ducks
    them for the duration of any sound effect. This rail queues NOTHING, so
    there is no window in which those voices are legitimately busy: any
    sounding at all is a part of the song written where a future cue would
    erase it.

    Planted — eight bars added to a `G` channel in slice_b_song.mml, the
    shared audio blob re-exported, the ROM relinked — this case reds and
    nothing else in the module moves. The restore re-exports BYTE-IDENTICAL,
    which is the compiler's determinism observed rather than assumed. When
    the plant ran against four rails it reddened all four, which read as the
    parameterisation earning its place; what it actually showed is that a
    defect in the SHARED song is visible from any drive, while a defect in a
    rail's own content is not — the distinction this module now leaves to the
    three per-rail modules.
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

    `slice_b_song`'s kit is samples. The three rails that used to share this
    case now make it against their OWN songs, each of which had to re-earn it
    — `far_ridge_song`, `shallow_water_song` and `foundry_song` are separate
    artifacts and a kit written into any one of them could take the generator
    without this module ever seeing it.
    """
    rail, rows = played
    bad = [(i, non) for i, (_, non) in enumerate(rows) if non & MUSIC_MASK]
    assert not bad, (
        f"{rail}: a music voice is in the noise mask on {len(bad)} frames "
        f"(first {bad[0][0]}, NON={bad[0][1]:#04x}) — that voice is silenced "
        f"whenever an effect plays noise")
