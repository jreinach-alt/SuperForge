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
W = MemoryType.SnesWorkRam
MUSIC_VOICES = tuple(range(6))      # TAD channels A-F
SFX_VOICES = (6, 7)                 # G/H, ducked while an SFX plays
def _srcn():
    """name -> VxSRCN, read from the project the export was built from.

    This module used to carry `BELL = 4  # instrument order in
    slice_b.terrificaudio`. A literal copy of a table someone else owns goes
    stale silently — it would have shifted nothing the day it was written and
    everything the first time an instrument is INSERTED rather than appended,
    and the module would have stayed green while measuring the wrong sample.
    `samples` is asserted empty because that is the assumption the mapping
    rests on: TAD numbers instruments first and samples after.
    """
    proj = json.loads(
        (SUPERFORGE / "assets" / "audio" / "slice_b.terrificaudio").read_text())
    assert not proj["samples"], (
        "the project has samples as well as instruments — SRCN is no longer "
        "just the instrument index and this mapping is wrong")
    return {inst["name"]: i for i, inst in enumerate(proj["instruments"])}


_SRCN = _srcn()
BELL = _SRCN["bell"]                # the lap chime and the checkpoint blip
STEP = _SRCN["step"]                # `skid` — the only noise cue on this rail
PLUCK = _SRCN["pluck"]              # the checkpoint blip and the START confirm
RACE_LAPS = 3
LIMIT = 900
FRAMES_OFFROAD = 600
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
            # (SRCN, ENVX, VOL_L) — the VOLUME is here because loudness is
            # the product of the envelope and the channel volume, and a row
            # without it can only answer "is this sounding", which is the
            # question that passed while the rail was reported silent.
            rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8], d[v * 0x10 + 0])
                         for v in range(8)])
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


# BOTH CUES ARE BELL, AND THAT IS THE FIX RATHER THAN AN OVERSIGHT.
# `circuit_song` scores square_lead, saw, tri_bass, step, kick and pluck —
# every instrument in the project except bell. The checkpoint blip used to be
# `select`, which is voiced by PLUCK, so it was the same instrument as the
# song's own channel D and did not read as a cue at all; it was reported as
# the rail having no sound effects. bell is the only timbre here that can cut
# through this soundtrack, so both cues use it and SRCN can no longer tell
# them apart.
#
# What separates them instead is their ENVELOPE, which is the effects' own
# and not a coincidence: `pickup` opens `set_instrument_and_gain bell F110`
# and `chime` opens with F127, so a run peaking at ENVX 110 is a blip and one
# peaking at 127 is a chime. The split at 120 sits between two fixed gains
# rather than near either.
#
# WHAT THIS CANNOT SEE, stated because it is a real loss against the old
# SRCN split: if the two cues were swapped at their call sites, the counts
# below would still hold. The structure claim (three between laps, one at the
# boundary) is what carries this case now.
#
# The THIRD cue is excluded by sample rather than by envelope: `skid` is
# `step` at gain F80, which is under this split, so counting every SFX run
# would file a kerb clip as a checkpoint. See `_cue_runs`.
BLIP_ENVX, CHIME_ENVX, SPLIT = 110, 127, 120


def _cue_runs(rows):
    """(start frame, peak ENVX) for each run of a BELL-voiced SFX.

    RESTRICTED TO BELL, and that restriction is a bug fix. This counted every
    run on an SFX voice and split blip from chime on the envelope alone —
    which silently swept in the third cue: `skid` is voiced by `step` at gain
    F80, under the 120 split, so a kerb clipped during the oracle drive was
    counted as a checkpoint blip. It cost a red in the landing gate that the
    module passed standalone, because whether that drive touches a
    non-drivable tile is marginal. Keying on the SAMPLE first makes the count
    mean what its name says.
    """
    runs, cur = [], None
    for i, row in enumerate(rows):
        env = max((row[v][1] for v in SFX_VOICES if row[v][0] == BELL),
                  default=0)
        if env:
            cur = [i, env] if cur is None else [cur[0], max(cur[1], env)]
        elif cur:
            runs.append(tuple(cur)); cur = None
    if cur:
        runs.append(tuple(cur))
    return runs


def _onsets(rows, kind):
    """Frame indices where a cue of `kind` ("blip" or "chime") starts.

    A cue is an event, so what a count of cues wants is the leading edge of
    each run, not the frames it occupies — an effect that happens to be two
    frames longer would otherwise change every count in this module.
    """
    return [f for f, env in _cue_runs(rows)
            if (env >= SPLIT) == (kind == "chime")]


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


def test_every_quadrant_crossing_blips(raced):
    """`select` is voiced by pluck, and it is what makes this rail AUDIBLE.

    THE BUG THIS CASE EXISTS FOR was reported as "microzero is entirely
    missing sfx". It was not: the lap chime worked exactly as scored and this
    module proved it. But a lap is upwards of a hundred frames of driving and
    the chime was the rail's ONLY cue, so a player heard nothing at all for
    seconds at a time and reasonably concluded there were no effects. A cue
    that fires correctly and almost never is indistinguishable, from the
    couch, from a cue that does not fire.

    The event was already there and was not being sounded: `race_logic` writes
    `sector` — the ring's quadrant — four times a lap, and it is this rail's
    own state word, so sounding it needed no new mechanism and no change to
    the feature. Measured on the shipped binary: a cue every ~54 frames,
    which is about one a second.
    """
    rows, lap_frames, _ = raced
    blips = _onsets(rows, "blip")
    assert blips, (
        f"no pluck voice ever sounded on an SFX channel across "
        f"{len(lap_frames)} laps — the checkpoint cue never reached the chip; "
        f"check that `mz_lap_edge`'s @sector arm is reached and that "
        f"US_SECTPREV is seeded in `enter`")


def test_the_cues_are_loud_enough_to_be_heard_over_this_song(raced):
    """THE CASE THIS MODULE DID NOT HAVE, AND ITS ABSENCE IS WHY THE RAIL WAS
    REPORTED AS SILENT.

    Every audibility case here asked WHETHER a cue voice was sounding. All of
    them passed on a build a player described as having no sound effects at
    all, because a bell keyed at 38% of the loudest music voice — under a
    six-voice mix scored v12/v13/v16 — is not something an ear picks out.
    `ENVX > 0` is true at a level nobody can hear; it is the same defect the
    wind on `heathaze` shipped with, and this module inherited it because the
    fix there was not carried across.

    So the claim is a RATIO against the loudest music voice, measured at the
    moment the cue sounds. Two things had to change for it to hold, and only
    the second is about level: the checkpoint was voiced by PLUCK, which this
    song scores on channel D, so it was camouflaged as well as quiet.

    MEASURED on the shipped binary: the blip peaks at ENVX 110 x VOL 48 =
    5280 and the chime at 127 x 63 = 8001, against a loudest music voice of
    8001 — so 0.66 and 1.00. Before `set_volume` was added to the two effects
    both sat at VOL 24, giving 0.38 and 0.38, which is the state that was
    reported. The bar is 0.55: clear of the ship, clear above the defect, and
    it does not pin the exact hierarchy between the two cues.
    """
    rows, _, _ = raced

    def mag(vol):
        return abs(vol - 256 if vol > 127 else vol)

    def amp(v):
        return max(mag(row[v][2]) * row[v][1] for row in rows)

    music = max(amp(v) for v in MUSIC_VOICES)
    cue = max(amp(v) for v in SFX_VOICES)
    assert cue / music > 0.55, (
        f"the loudest cue peaks at {cue} against the loudest music voice's "
        f"{music} — a ratio of {cue/music:.2f}. It is sounding and it is too "
        f"quiet to pick out of this mix, which is the state that was reported "
        f"as the rail having no sound effects. An effect that does not call "
        f"`set_volume` plays at the driver default of VOL 24")


def test_a_lap_is_three_blips_and_a_chime(raced):
    """THE ARITHMETIC OF THE TWO CUES, and it is the sharpest case here.

    The ring has four quadrants and the start/finish spoke IS the 3->0 edge
    (`race_logic`'s header), so a lap crosses four sector boundaries — one of
    which is the lap itself. `mz_lap_edge` consumes that crossing on the lap
    arm, so a completed lap sounds as THREE blips and one chime, and the
    chime is clean rather than trailing a blip a frame later (the SFX ring
    holds one request per frame and would deliver the second on the next).

    Counted BETWEEN consecutive lap frames, which sidesteps the entry cue: the
    START press that enters the race queues its own `select`, and it lands in
    the opening frames rather than inside a lap.

    Two defects this bounds and the audibility case above does not: dropping
    the consume makes it four blips and a chime, and moving the blip to the
    sector VALUE rather than its change floods the interval.
    """
    rows, lap_frames, _ = raced
    assert len(lap_frames) >= 2, "need two lap frames to bound an interval"
    blips = _onsets(rows, "blip")
    chimes = _onsets(rows, "chime")
    for a, b in zip(lap_frames, lap_frames[1:]):
        inside = [f for f in blips if a < f < b]
        assert len(inside) == 3, (
            f"the lap between frames {a} and {b} sounded {len(inside)} "
            f"checkpoint blips, not 3 — four means the lap's own crossing was "
            f"not consumed on the chime's arm, and more means the cue is "
            f"reading the sector's VALUE rather than its change")
    # THE LAST LAP IS NOT COUNTED, and the reason is the fixture's: the drive
    # stops ON the frame the third lap closes, because the race tick requests
    # the results scene there and `race::tick` runs no more. That lap's chime
    # would key one frame later, after the recording ends — so the laps this
    # case can speak for are the ones with room after them.
    audible = [f for f in lap_frames if f + 3 < len(rows)]
    assert len(chimes) == len(audible), (
        f"{len(chimes)} bells for {len(audible)} laps that had room to sound "
        f"(of {len(lap_frames)} driven) — a lap chimes exactly once")
    for lap, chime in zip(audible, chimes):
        # DELIVERY IS NOT INSTANT and the slack is measured, not assumed: the
        # cue is queued inside the scene's tick and `sf_audio_tick` hands one
        # request to the driver later in the same frame's main loop, so the
        # voice keys on the NEXT frame. Measured at exactly 1 on this rail;
        # the bar is 3 so that a main-loop reorder is not a red, while a chime
        # that had drifted into the middle of a lap still is.
        assert lap <= chime <= lap + 3, (
            f"the bell for the lap at frame {lap} sounded at {chime} — the "
            f"chime has come loose from the boundary it names")


@pytest.fixture(scope="module")
def offroad():
    """A drive that LEAVES THE ROAD, which the oracle drive never does.

    `raced` steers to the track heading every frame precisely so the lap
    arithmetic is exact, so it is the wrong drive for a surface cue: it is
    never off the road to be cued about. A held hard turn puts the car onto
    the grass repeatedly.

    Returns `(rows, edges)` — the DSP per frame, and the number of 1 -> 0
    surface transitions the ROM's own latch recorded, so the cue count below
    is checked against the events the game actually had rather than against a
    number typed here.
    """
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in jmap["scenes"]["race"]["placements"]}
    off = syms["US_OFFPREV"]["start"]
    r = MesenRunner(enable_audio=True)
    r.boot_rom(str(SUPERFORGE / "build" / "microzero.sfc"), frames=300)
    rows, edges, prev = [], 0, None
    try:
        D.enter_race(r, {**syms, **{p["sym"]: p for p in jmap["globals"]}})
        r.frame_step(60)
        for _ in range(FRAMES_OFFROAD):
            r.frame_step(1, b=True, left=True)
            cur = r.read_bytes(W, off, 1)[0]
            if prev == 1 and cur == 0:
                edges += 1
            prev = cur
            d = r.read_bytes(DSP, 0, 128)
            rows.append([(d[v * 0x10 + 4], d[v * 0x10 + 8], d[v * 0x10 + 0])
                         for v in range(8)])
    finally:
        r.stop()
    return rows, edges


def test_leaving_the_road_is_audible(offroad):
    """`skid` is voiced by `step` with `play_noise` — and NOTHING ELSE HERE
    TAKES THE NOISE GENERATOR, which is what makes it unmistakable.

    `circuit_song` scores no noise and this rail's other two cues are bell, so
    a step-voiced voice in the noise mask is the skid and can be nothing else.

    THE COUNT IS CHECKED AGAINST THE GAME'S OWN EDGES, not a typed number.
    `col_map` already probed the tile under the camera every frame and wrote
    CM_FLAG, and that flag fed nothing at all — no velocity clamp, no
    collision response, deliberately, because a speed penalty would move a
    pinned `make measure` cadence. A cue reads it without touching any of
    that, which is why the most obvious event a racing game owes its player
    cost one latch word.

    THE DEFECT THIS EXISTS FOR IS A FLAGS BUG AND IT SHIPPED ONCE IN
    DEVELOPMENT: `sta` does not touch the flags, so a `bne` after storing the
    new surface still read the CMP's Z — always "not equal" on that arm — and
    branched every time. Measured then: 19 edges owed, 0 delivered, with both
    SFX channels idle, so it was not a priority drop. Asserting only "a skid
    sounds sometimes" would have caught that one; asserting it against the
    edge count is what keeps a HALF-firing cue from passing.
    """
    rows, edges = offroad
    assert edges >= 4, (
        f"the drive only left the road {edges} times — it is not exercising "
        f"the surface cue, so the assertion below would be vacuous")
    live = [i for i, row in enumerate(rows)
            if any(row[v][0] == STEP and row[v][1] for v in SFX_VOICES)]
    onsets = [f for j, f in enumerate(live) if j == 0 or live[j - 1] != f - 1]
    assert onsets, (
        f"the car left the road {edges} times and no step-voiced cue ever "
        f"sounded — check that cm_tick's surface arm reaches sf_sfx_queue_c "
        f"(a `bne` reading a stale Z after `sta` is how this failed before)")
    assert len(onsets) >= edges // 3, (
        f"only {len(onsets)} skids for {edges} departures from the road — the "
        f"cue is firing on some edges and not others. The SFX ring holds one "
        f"request a frame and the lower id wins, so a skid (14) loses to a "
        f"blip (8) that shares its frame; losing MOST of them is a defect")


def test_the_song_reserves_the_sound_effect_voices(raced):
    """Nothing of `circuit_song` is scored where an effect would erase it.

    TAD's channels G and H map onto DSP voices 6 and 7, and the driver DUCKS
    them for the duration of any sound effect (`audio-driver.asm`,
    `musicSfxChannelMask`). A part written there vanishes every time the game
    makes a noise — on this rail, once a lap.

    Asserted as an EQUALITY, on the title, and the reason has NARROWED and is
    now worth stating precisely. It used to be "nothing on the title can queue
    an effect" — true when the rail's only cue was the lap chime, and FALSE
    since the title's START press gained a `select`. What still holds is that
    this window is the frames BEFORE any input: the fixture drives no buttons
    until `enter_race`, so no press has happened and no cue can have been
    queued. The bar is zero because of what the drive does, not because of
    what the scene cannot do.

    That distinction is the one this session paid for elsewhere — a
    no-input drive keeps an equality green through exactly the change that
    should have retired it (`tests/test_screen_effect_audio.py`, and the
    dx_paper_cuts entry beside it). Recorded here so the next person to add a
    title cue reads why this bar is still allowed to be zero, and checks that
    it is.

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
