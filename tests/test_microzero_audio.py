"""microzero's song, and the one cue a lap earns.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For
audio that is the S-DSP: `VxENVX > 0` says a voice is SOUNDING and `VxSRCN`
says which sample it is keyed to. Nothing here reads a queue byte or a driver
flag; the queue is consumed and cleared inside the frame that fills it, so it
is unreadable at any frame boundary anyway.

TWO CLAIMS, and they are different in kind.

  * THE SONG. `circuit_song` is this rail's own — the third in the tree, after
    `slice_b_song` (the room's ambient piece) and `drive_song` (the action
    rails', in D minor). A racing game wanted neither, so this one is A
    mixolydian over I - bVII - IV. The assertion is that its six channels are
    actually keyed on the chip across a real drive, which is what separates
    "the song data is linked into the ROM" from "the song is playing".
  * THE LAP CHIME. `race_logic` increments this rail's `lap` word; the rail
    latches the change and chimes on it. The counter is a LEVEL, read fresh
    every tick, so a cue on the value rather than on its change rings for
    every frame of the lap it counts — several seconds of bell. That is the
    cadence defect this tree has paid for on four rails now, and the fraction
    case below is what catches it.

THE DRIVE IS THE REFERENCE MODULE'S OWN, oracle-steered
(`tests/mz_drive.py`, shared with `test_microzero_laps.py`): full throttle
with at most one pose step of correction toward the track heading each frame.
So the car really laps the generated ring, and the chime is counting laps of
the track rather than of an abstraction. Every frame of it samples the DSP,
including the frames inside the helper's own loop, so no frame a cue could
sound on is unsampled.
"""
import json
import sys
from pathlib import Path

import pytest

from conftest import run_make

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

DSP = MemoryType.SpcDspRegisters
MUSIC_VOICES = tuple(range(6))      # TAD channels A-F
SFX_VOICES = (6, 7)                 # G/H, ducked while an SFX plays
BELL = 4                            # instrument order in slice_b.terrificaudio
RACE_LAPS = 3
LIMIT = 900
TITLE_FRAMES = 240
MUSIC_MASK = 0x3F   # NON bits for voices 0-5


@pytest.fixture(scope="module")
def raced():
    """Boot with audio on, enter the race, and lap the ring, sampling as we go.

    Returns `(rows, lap_frames)` — one DSP snapshot per driven frame, and the
    frame indices the ROM's lap counter stepped on. The drive stops AT
    RACE_LAPS because the race tick requests the results scene on that frame,
    after which `race::tick` no longer runs and there is nothing left to
    measure on this scene.
    """
    r = run_make("microzero")
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    lut = D.load_tool("gen_move_lut")

    # `boot_rom`, not `load_rom(run_seconds=)`: an EMULATED frame budget rather
    # than a wall-clock sleep. 300 frames is the boot budget the other rail
    # audio modules use and it is generous on purpose — `Tad_Init` alone costs
    # four hardware frames handshaking the S-SMP out of the IPL.
    runner = MesenRunner(enable_audio=True)
    runner.boot_rom(str(SUPERFORGE / "build" / "microzero.sfc"), frames=300)
    rows, lap_frames, title = [], [], []
    try:
        # THE TITLE FIRST, and it is a different measurement: the song is
        # playing in full and NOTHING on this rail can queue an effect there
        # (`mz_lap_edge` runs in the race scene's tick only), so voices 6/7 and
        # the noise mask can be asserted as EQUALITIES rather than thresholds.
        for _ in range(TITLE_FRAMES):
            runner.frame_step(1)
            d = runner.read_bytes(DSP, 0, 128)
            title.append(([d[v * 0x10 + 8] for v in range(8)], d[0x3D]))
        D.enter_race(runner, syms)
        runner.frame_step(2)

        D.brake_to_stop(runner, syms)
        D.steer_to(runner, syms, 0)
        D.brake_to_stop(runner, syms)
        sim = D.sim_from_rom(runner, syms, lut)

        for f in range(LIMIT):
            prev = sim.lap
            D.drive_sim(runner, sim, 1, **D.track_buttons(sim, lut))
            d = runner.read_bytes(DSP, 0, 128)
            rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in range(8)])
            assert D.lap(runner, syms) == sim.lap, (
                f"frame {f}: ROM lap {D.lap(runner, syms)} vs oracle "
                f"{sim.lap} — the drive rotted, so the audio cases below "
                f"would be measuring a car that is not lapping the track")
            if sim.lap != prev:
                lap_frames.append(f)
            if sim.lap >= RACE_LAPS:
                break
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failed assertion above would strand the NEXT module's runner and
        # make it name itself. `finally` is what keeps this module the one
        # that reports its own failure (tests/conftest.py, the parked-core
        # guard).
        runner.stop()

    assert len(lap_frames) == RACE_LAPS, (
        f"the drive scored {len(lap_frames)} laps in {LIMIT} frames, not "
        f"{RACE_LAPS} — the chime cases have nothing to count")
    return rows, lap_frames, title


def _live(rows, voices, srcn=None):
    """Frames on which any of `voices` is sounding (optionally, that sample)."""
    return sum(1 for row in rows
               if any(row[v][1] and (srcn is None or row[v][0] == srcn)
                      for v in voices))


def test_the_song_is_playing_on_every_channel_it_writes(raced):
    """`circuit_song` keys six voices, and all six must actually sound.

    "The song is in the ROM" and "the song is playing" are different claims,
    and only the second is worth making: a channel whose instrument never
    keys on — the `E<rate>` GAIN trap this tree already paid for, where a
    DECREASE-mode envelope falls from a key-on level of zero and stays at
    ENVX 0 for ever — links, loads, and is silent. So the assertion is
    per-voice, not aggregate.
    """
    rows, _, _ = raced
    silent = [v for v in MUSIC_VOICES if not _live(rows, (v,))]
    assert not silent, (
        f"music voice(s) {silent} never sounded across {len(rows)} frames of "
        f"the drive — those channels of `circuit_song` are keyed but making "
        f"no sound")


def test_the_song_is_playing_for_most_of_the_drive(raced):
    """Not merely audible once — CONTINUOUS.

    A song that keys on at load and then runs out of data would satisfy the
    per-voice case above on frame 1 and leave the rest of the race in
    silence. The drive is hundreds of frames long and the piece loops, so
    "some music voice is sounding" should be true almost always; the bar is
    set well below what a working song reads so a tempo or loop-point change
    cannot flip it.
    """
    rows, _, _ = raced
    frac = _live(rows, MUSIC_VOICES) / len(rows)
    assert frac > 0.90, (
        f"a music voice is sounding on only {frac:.0%} of the drive — the "
        f"song is not running continuously; check the loop point (`L`) and "
        f"that Tad_Process is pumped every frame")


def test_a_completed_lap_chimes(raced):
    """`chime` is voiced by bell (assets/audio/sound-effects.txt)."""
    rows, lap_frames, _ = raced
    assert _live(rows, SFX_VOICES, BELL) > 0, (
        f"no bell voice ever sounded on an SFX channel across {len(lap_frames)} "
        f"completed laps — the lap cue never reached the chip")


def test_the_chime_is_an_instant_not_the_whole_lap(raced):
    """The cadence case: `lap` is a LEVEL and the cue must be on its change.

    A lap here takes upwards of a hundred frames, so a cue read off the
    counter's VALUE puts the bell on nearly every frame from the first lap to
    the finish — the shape jumper, stomper, maze and platformer_stream each
    carry a latch to avoid. Planted (the `cmp`/`beq` pair in `mz_lap_edge`
    replaced by nops) it reads 97% of the drive, and the other three cases in
    this module stay GREEN on that plant, which is why this one exists. The
    chime's own two notes set the ceiling for a correct rail; the bar sits far
    enough between the two that neither the effect's length nor the exact lap
    geometry can flip it.
    """
    rows, lap_frames, _ = raced
    frac = _live(rows, SFX_VOICES, BELL) / len(rows)
    assert frac < 0.25, (
        f"the bell voice is live on {frac:.0%} of the drive — the lap cue is "
        f"firing off the COUNTER rather than the edge into it, so it rings "
        f"for every frame of the lap it counts. `mz_lap_edge` compares "
        f"US_LAP_LONG against US_LAPPREV precisely so it cannot")


def test_the_song_reserves_the_sound_effect_voices(raced):
    """Nothing of `circuit_song` is scored where an effect would erase it.

    TAD's channels G and H map onto DSP voices 6 and 7, and the driver DUCKS
    them for the duration of any sound effect (`audio-driver.asm`,
    `musicSfxChannelMask`). A part written there vanishes every time the game
    makes a noise — on this rail, once a lap.

    Asserted as an EQUALITY, on the title, because nothing on the title can
    queue an effect: the only cue this rail has is `mz_lap_edge`, which runs
    in the race scene's tick. So a part on G or H shows up as a voice
    sounding at all, and the bar is zero. (The race drive cannot make this
    claim — the chime is exactly what sounds there.)

    Planted — four bars added to a `G` channel in circuit_song.mml, the whole
    audio blob re-exported — voices 6/7 sound on 235 of 240 title frames.
    """
    _, _, title = raced
    busy = [i for i, (env, _) in enumerate(title)
            if any(env[v] for v in SFX_VOICES)]
    assert not busy, (
        f"voices 6/7 sound on {len(busy)} of {len(title)} title frames (first "
        f"at frame {busy[0]}), where no effect can be queued — `circuit_song` "
        f"is scored on G or H, and every part written there is ducked away the "
        f"moment the game makes a noise")


def test_the_kit_never_takes_the_noise_generator(raced):
    """The drums are samples, so an effect cannot mute them.

    There is exactly one noise generator, and when an effect wants it the
    driver zeroes the volume of every music channel sharing it (the `SfxNoise`
    branch). A snare written as `N<0-31>` passes a listening test on a quiet
    screen and disappears under anything that makes noise. `circuit_song`'s
    kit is `step` and `kick` — real samples — and NON must therefore hold no
    music voice at any point.

    Planted — the hat subroutine's `o5 c%12` swapped for `N16,%12` — a music
    voice is in the mask on 177 of 240 title frames. Both plants re-export the
    shared audio blob and both restore to a BYTE-IDENTICAL export, which is
    also the compiler's determinism observed rather than assumed.
    """
    _, _, title = raced
    bad = [(i, non) for i, (_, non) in enumerate(title) if non & MUSIC_MASK]
    assert not bad, (
        f"a music voice is in the noise mask on {len(bad)} title frames "
        f"(first frame {bad[0][0]}, NON={bad[0][1]:#04x}) — that voice is "
        f"silenced whenever an effect plays noise")


def test_the_title_is_not_silent(raced):
    """Non-vacuity for the two equalities above: silence satisfies both."""
    _, _, title = raced
    live = sum(1 for env, _ in title if any(env[v] for v in MUSIC_VOICES))
    assert live / len(title) > 0.90, (
        f"a music voice sounds on only {live}/{len(title)} title frames — the "
        f"two equality cases above would pass on a silent chip, so this is "
        f"what stops them being vacuous")
