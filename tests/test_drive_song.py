"""The action rails' song, on the chip that plays it.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. A
song's rendered output is the S-DSP voice set, and the two things asserted
here are the two arrangement decisions that would silently wreck the music
under gameplay. Neither is visible in the MML text; both are visible on the
chip while the rail runs.

  * `VxENVX` on voices 6 and 7. TAD maps song channels G and H onto those
    two voices and DUCKS them while a sound effect plays (docs/mml-syntax.md,
    "Engine Limitations"; audio-driver.asm's `musicSfxChannelMask`). A part
    written to G or H therefore VANISHES every time the game makes a noise —
    on the shmup, most of the time. `drive_song` is scored on A-F only, and
    the observable of that is voices 6/7 sitting at ENVX 0 whenever no effect
    is playing.

  * `NON` ($3D), the per-voice noise-enable mask. There is exactly one noise
    generator, and when a sound effect wants it the driver ZEROES the volume
    of every music channel that is also using it (audio-driver.asm, the
    `SfxNoise` branch: `nonShadow_music` under `noiseLock`). A noise hi-hat
    would drop out under every explosion. So the kit is samples — a
    pitch-dropping `kick` one-shot and the `step` burst as snare and hat —
    and the observable of THAT is that no music voice ever appears in NON.

The non-vacuity case matters as much as either: an empty song passes both of
the above trivially, so the six music voices are also asserted to be doing
work.

Driving is `frame_step` throughout — emulated frames, no host clock.
"""
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

DSP = MemoryType.SpcDspRegisters
NON = 0x3D                      # S-DSP per-voice noise enable
MUSIC_VOICES = tuple(range(6))  # channels A-F
SFX_VOICES = (6, 7)             # channels G/H — TAD's two effect channels
MUSIC_MASK = 0x3F
PANNED = (1, 3)                 # channels B (p40) and D (p96)
CENTRED = (0, 2, 4, 5)          # lead, bass, snare/hat, kick


def _rom(name):
    p = SUPERFORGE / "build" / f"{name}.sfc"
    assert p.exists(), f"{p} not built — run `make {name}` first"
    return str(p)


def _sample(r, frames, drive):
    """Per-frame ENVX for all eight voices, plus the NON mask."""
    rows = []
    for i in range(frames):
        drive(r, i)
        d = r.read_bytes(DSP, 0, 128)
        rows.append(([d[v * 0x10 + 8] for v in range(8)], d[NON]))
    return rows


@pytest.fixture(scope="module")
def shmup_song():
    """Two windows on one boot: the TITLE, and a firing drive in play.

    The title is the window because it is the only place the reserved-voice
    claim can be stated as an equality. The song plays from boot (the rail's
    one `Tad_LoadSong` is in its boot block and PLAY_SONG_IMMEDIATELY is
    TAD's default), so all six parts are running — but there is no gameplay,
    so nothing queues an effect. Measured: voices 6/7 live on 0 of 480 frames.

    Standing still in PLAY does not give that window, which is what the first
    version of this fixture got wrong. It read 8 busy frames out of 360 and
    the assertion blamed the song for being scored on G or H. It was not:
    with no input the ship does not dodge, an enemy reaches it, and the
    resulting `step`-voiced effect is the game working correctly. A test that
    accuses the ROM of the test's own bug is the shape this repo keeps paying
    for, so the window moved rather than the threshold.

    The firing drive stays for the noise case, which needs effects competing
    for the one noise generator to mean anything.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom("shmup"), frames=240)
    title = _sample(r, 480, lambda rr, i: rr.frame_step(1))
    r.frame_step(3, start=True)                       # title -> play
    r.frame_step(3)
    r.frame_step(120)                                 # fade + enter, settle
    loud = _sample(r, 420, lambda rr, i: rr.frame_step(
        1, a=(i % 6 < 3), left=(i % 240 < 120), right=(i % 240 >= 120)))
    r.stop()
    return {"title": title, "loud": loud}


def test_the_song_reserves_the_sound_effect_voices(shmup_song):
    """Nothing of the music is scored where an effect would erase it.

    An equality, not a threshold: on the title the song is playing in full
    and no effect can be queued, so a part on G or H would show up as a
    continuously sounding voice 6 or 7 and every other frame count in this
    module says what "continuously" looks like (88-99% for the melodic
    parts, 16-17% for the one-shot kit).
    """
    rows = shmup_song["title"]
    busy = [i for i, (env, _) in enumerate(rows)
            if any(env[v] for v in SFX_VOICES)]
    assert not busy, (
        f"voices 6/7 sound on {len(busy)} of {len(rows)} frames of the title, "
        f"where no effect can be queued (first at frame {busy[0]}) — the song "
        f"is scored on G or H, and every part written there is ducked away the "
        f"moment the game makes a noise")


def test_the_song_actually_drives_six_voices(shmup_song):
    """Non-vacuity: silence would satisfy every other case in this module."""
    rows = shmup_song["title"]
    live = {v: sum(1 for env, _ in rows if env[v]) / len(rows)
            for v in MUSIC_VOICES}
    # Observed: 0.88, 0.93, 0.88, 0.99 for the four melodic parts and 0.17,
    # 0.16 for the two one-shot drum channels, which sound briefly and often
    # rather than continuously. The bar sits below the tightest of those by a
    # wide margin and far above the 0.00 a channel nobody wrote would give.
    dead = sorted(v for v, f in live.items() if f < 0.10)
    assert not dead, (
        f"music voices {dead} sound on under 10% of frames "
        f"(live fractions { {v: round(f, 3) for v, f in live.items()} }) — the "
        f"song is not using the six channels the reserved-voice case assumes "
        f"it uses")


def test_the_kit_never_takes_the_noise_generator(shmup_song):
    """The drums are samples, so an explosion cannot mute them.

    There is one noise generator; the driver zeroes the volume of any music
    channel sharing it with an effect. A snare on `N` would pass a listening
    test on a quiet screen and disappear in a firefight.
    """
    for name in ("title", "loud"):
        bad = [(i, non) for i, (_, non) in enumerate(shmup_song[name])
               if non & MUSIC_MASK]
        assert not bad, (
            f"{name} drive: a music voice is in the noise mask on "
            f"{len(bad)} frames (first frame {bad[0][0]}, NON={bad[0][1]:#04x}) "
            f"— that voice is silenced whenever an effect plays noise")


# =============================================================================
# the stereo image — a pan that never reaches the chip is not a pan
# =============================================================================

def _sgn(b):
    return b - 256 if b > 127 else b


@pytest.fixture(scope="module")
def racer_pan():
    """VOL_L vs VOL_R per music voice on the racer, over the title.

    The racer rather than the shmup because the racer is one of the three
    rails that did NOT set an audio mode until this song arrived. TAD's
    default is MONO (tad-audio.inc:123) and in mono the driver collapses
    every channel to centre, so the song's `p40` and `p96` were being
    authored and then discarded. This is the case that says otherwise.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom("racer"), frames=240)
    off = {v: 0 for v in MUSIC_VOICES}
    lit = {v: 0 for v in MUSIC_VOICES}
    for _ in range(480):
        r.frame_step(1)
        d = r.read_bytes(DSP, 0, 128)
        for v in MUSIC_VOICES:
            if d[v * 0x10 + 8]:
                lit[v] += 1
                if _sgn(d[v * 0x10 + 0]) != _sgn(d[v * 0x10 + 1]):
                    off[v] += 1
    r.stop()
    return {v: (off[v] / lit[v] if lit[v] else None) for v in MUSIC_VOICES}


def test_the_panned_parts_are_actually_panned(racer_pan):
    """Measured: 100% on both, and 0% on every voice with the rail in MONO."""
    flat = {v: racer_pan[v] for v in PANNED if (racer_pan[v] or 0) < 0.90}
    assert not flat, (
        f"voices {sorted(flat)} carry the song's `p40`/`p96` but their "
        f"VOL_L and VOL_R agree (divergence {flat}) — the rail is in MONO, "
        f"where the driver collapses every channel to centre, so the stereo "
        f"image is authored and thrown away")


def test_nothing_else_drifts_off_centre(racer_pan):
    """The other half of the claim, so the first cannot pass by accident.

    Only two parts carry a pan command. A rail that panned everything —
    or a driver that put a channel off-centre on its own — would satisfy
    the case above while meaning something different.
    """
    drifted = {v: racer_pan[v] for v in CENTRED if racer_pan[v]}
    assert not drifted, (
        f"voices {sorted(drifted)} sit off centre (divergence {drifted}) "
        f"but the song writes no pan for the lead, bass or kit")
