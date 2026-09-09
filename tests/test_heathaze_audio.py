"""heathaze's soundtrack, its weather and its one cue, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For
audio that is the S-DSP voice: `VxENVX > 0` (byte v*0x10+8) says a voice is
SOUNDING, `VxSRCN` (v*0x10+4) says which sample is keyed, `VxVOL` (v*0x10+0)
says how loud, and `NON` (register 0x3D) says which voices are taking the one
noise generator. Nothing here reads the SFX queue: it is consumed and cleared
inside the frame that fills it (`tad-audio.s:993`), so it reads $FF at every
frame boundary and a test watching it would pass on a silent rail.

WHY THIS RAIL HAS ITS OWN MODULE NOW. `tests/test_screen_effect_audio.py`
covers four rails that compose `audio` for MUSIC ONLY, and its second case is
a flat equality: voices 6 and 7 are TAD channels G and H, the driver ducks
them for the duration of any sound effect, and on a rail that queues nothing
there is no window in which they are legitimately busy. That equality does not
survive this rail gaining content — heathaze now queues a wind bed on a
cadence and a `select` on its B toggle, so 6 and 7 are busy nearly always. The
claim has to be re-stated rather than relaxed, and §"what replaced the
equality" below is where.

THE FOUR CLAIMS, and each has a plant recorded beside it:

  * THE SONG PLAYS, CONTINUOUSLY. `far_ridge_song` is this rail's own piece.
    "The data is linked into the ROM" and "the song is running" are different
    claims and only the second is worth making.
  * NO MUSIC PART IS SCORED WHERE AN EFFECT WOULD ERASE IT — the equality's
    replacement, and it is not a fraction.
  * NO MUSIC VOICE TAKES THE NOISE GENERATOR, with its own non-vacuity: the
    generator is in use every frame, by an SFX voice, and never by a music
    one.
  * THE WEATHER IS A BED AND THE CUE IS AN EVENT. The wind must be CONTINUOUS,
    which a one-shot is not; the toggle must be the PRESS EDGE, which a level
    read is not. Both are fractions and both bars were set against a planted
    defect, not chosen.

EVERY FIXTURE ASSERTS THE GAME STATE MOVED. `US_FLAT` is read before and
after, so a drive that stopped reaching the scene fails naming the control
rather than going quiet on a cue and reading as a defect in the audio.
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

MUSIC_VOICES = tuple(range(6))      # TAD channels A-F
SFX_VOICES = (6, 7)                 # G/H, which the driver ducks for an effect
MUSIC_MASK = 0x3F                   # NON bits for voices 0-5
NON = 0x3D


# --- the instrument table, READ rather than retyped --------------------------
def _srcn():
    """name -> VxSRCN, from the project file the export was built from.

    `test_hud_game_audio.py` carries `BELL = 4  # instrument order in
    slice_b.terrificaudio` as a literal, and a literal copy of a table someone
    else owns goes stale silently — the module still passes, weaker than it
    claims. Adding `wind`'s instrument to that table would have shifted
    nothing today and everything the first time a sample is inserted rather
    than appended.

    The `samples` list is asserted EMPTY because that is the assumption the
    mapping rests on: TAD numbers instruments first and samples after, so a
    non-empty list would not move these indices but WOULD mean this helper
    stopped covering every source the export can key.
    """
    proj = json.loads(
        (SUPERFORGE / "assets" / "audio" / "slice_b.terrificaudio").read_text())
    assert proj["samples"] == [], (
        "the project gained a `samples` entry — VxSRCN is instruments-then-"
        "samples, so this helper no longer names every source it can read")
    return {inst["name"]: i for i, inst in enumerate(proj["instruments"])}


SRCN = _srcn()
SAW = SRCN["saw"]                   # `wind`   — assets/audio/sound-effects.txt
PLUCK = SRCN["pluck"]               # `select` — ...and channel D of the song
# The three the SONG uses and no effect this rail queues does. A part scored on
# G or H with any of them is what the music-only rails' flat equality caught.
MUSIC_ONLY = tuple(SRCN[n] for n in ("tri_bass", "square_lead", "kick"))


# --- the rail's own constants, likewise read ---------------------------------
def _rail_const(name):
    """One equate out of game/heathaze/heathaze.inc.

    Same rule as `tests/test_heathaze.py::_rail_const` and for the same
    reason: anything the ROM and this file must agree about is read from the
    source of truth, never copied into it.
    """
    src = (SUPERFORGE / "game" / "heathaze" / "heathaze.inc").read_text()
    for line in src.splitlines():
        head, _, rest = line.partition("=")
        if head.strip() == name:
            v = rest.split(";")[0].strip()
            # ca65 spells hex with a `$`, which int() does not read.
            return int(v[1:], 16) if v.startswith("$") else int(v, 0)
    raise KeyError(f"{name} is not in heathaze.inc")


WIND_PHASES = _rail_const("HZ_WIND_PHASES")
PHASE_BASE = _rail_const("HZ_PHASE_BASE")       # 8.8 phases per NTSC frame
# The cadence the rail actually runs, DERIVED: phases to the next gust divided
# by phases a frame. 32 / (0x60/256) = 85.33 frames = 1.42 s at 60.1 fps.
WIND_PERIOD = WIND_PHASES * 256.0 / PHASE_BASE
# `wind` is 80+56+64+12 = 212 ticks of the driver's FIXED 125 Hz sound-effect
# clock (vendor docs/sound-effects.md, "Limitations") = 1.696 s = ~102 NTSC
# frames. It is LONGER than the cadence above, which is the whole mechanism:
# the bed is re-queued while the previous one still sounds, so the restart
# never leaves a hole. Stated here as the reason the continuity bar can sit
# where it does; the numbers it is checked against are measured below.
WIND_TICKS = 212

_MAP = json.loads((SUPERFORGE / "build" / "hz" / "symbol_map.json").read_text())
_DP = {p["sym"]: p["start"]
       for p in _MAP["scenes"]["desert"]["placements"] if p["class"] == "dp"}
DP_FLAT = _DP["US_FLAT"]

# --- the drive ---------------------------------------------------------------
TITLE = 60          # past the fade-in, sitting on the title
SETTLE = 79         # title -> desert, both ramps (tests/test_heathaze.py)
PRESSES = 15
PERIOD = 40         # frames per press cycle...
HOLD = 24           # ...of which this many hold B down
FRAMES = PRESSES * PERIOD                       # 600 = 7 full wind cadences

# The longest run of frames the wind may be inaudible for. The design overlaps
# each re-queue with the bed still playing by ~16 frames, so a correct rail
# shows a gap of at most the one frame the key-on itself costs; MEASURED on
# the shipped binary the whole 600-frame drive has exactly one such frame.
# Eight is that measurement with room for a key-on landing either side of a
# sample, and far below the ~17-frame hole a cadence one gust too slow opens.
MAX_SILENT_RUN = 8


def _rom():
    p = SUPERFORGE / "build" / "heathaze.sfc"
    assert p.exists(), "build/heathaze.sfc not built — run `make heathaze`"
    return str(p)


@pytest.fixture(scope="module")
def driven():
    """Reach the desert, then press B `PRESSES` times, holding it most of each cycle.

    THE LONG HOLD IS THE POINT. 24 of every 40 frames have B down, so a cue
    read off the HELD state rather than the press edge has 60% of the drive to
    sound in while the correct one has fifteen instants. Both are audible;
    only the fraction tells them apart.

    No second drive for the weather: the wind is measured on the rail as a
    person actually plays it, with the toggle being worked, because "the bed
    survives the other cue" is part of what continuous means here.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    rows = []
    try:
        r.frame_step(TITLE)
        r.frame_step(1, start=True)
        r.frame_step(SETTLE)
        before = int.from_bytes(r.read_bytes(W, DP_FLAT, 2), "little")
        seen = {before}
        for i in range(FRAMES):
            r.frame_step(1, b=(i % PERIOD < HOLD))
            d = r.read_bytes(DSP, 0, 128)
            rows.append((
                [(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in range(8)],
                d[NON],
            ))
            seen.add(int.from_bytes(r.read_bytes(W, DP_FLAT, 2), "little"))
        after = int.from_bytes(r.read_bytes(W, DP_FLAT, 2), "little")
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failed read above would strand the NEXT module's runner and make it
        # name itself (tests/conftest.py, the parked-core guard).
        r.stop()
    return rows, before, after, seen


def _sfx_live(rows, srcn):
    """Frames on which `srcn` is keyed AND sounding on an SFX voice."""
    return [i for i, (voices, _) in enumerate(rows)
            if any(s == srcn and e for s, e in (voices[v] for v in SFX_VOICES))]


def _longest_gap(hits, total):
    """The longest run of frames in [0, total) that `hits` does not contain."""
    worst, prev = 0, -1
    for i in list(hits) + [total]:
        worst = max(worst, i - prev - 1)
        prev = i
    return worst


# =============================================================================
# non-vacuity: the drive is a game being played
# =============================================================================

def test_the_drive_actually_worked_the_control(driven):
    """`US_FLAT` moved, and it is the GAME STATE rather than a cue.

    Fifteen presses of B is an odd number of toggles, so the flat control ends
    on the opposite value from the one the scene enters with, and both values
    are visited during the drive. A run that stopped reaching the desert — a
    changed control, a boot that never got past the title, a fade that never
    lifted — fails HERE, naming the state, instead of failing an audibility
    case below and reading as a defect in the sound.
    """
    _, before, after, seen = driven
    assert (before, after) == (0, 1), (
        f"the flat control went {before} -> {after}, not 0 -> 1 across "
        f"{PRESSES} presses — the drive is not playing the game the cue cases "
        f"below are measuring")
    assert seen == {0, 1}, (
        f"the control only ever held {sorted(seen)} — the drive never cycled "
        f"the state it claims to")


# =============================================================================
# the song
# =============================================================================

def test_the_song_is_playing_for_most_of_the_drive(driven):
    """Not merely audible once — CONTINUOUS.

    A song that keys on at load and then runs out of data would look alive on
    frame 1 and leave the rest silent. `far_ridge_song` loops at 1536 ticks
    (~44 s) and the drive is ten seconds inside it, so "some music voice is
    sounding" should be true nearly always — the drone is a held pedal and it
    only lapses in the one-frame seam where a whole note keys off and the next
    keys on. MEASURED on the shipped binary: 594 of 600 frames, 99.0%. The bar
    sits well below that and well above what the melody alone would give (it
    sounds on 227 frames, 38%, which is the sparseness the piece is for), so a
    drone that stopped holding cannot pass this by leaving the tune running.
    """
    rows, _, _, _ = driven
    live = [i for i, (voices, _) in enumerate(rows)
            if any(voices[v][1] for v in MUSIC_VOICES)]
    frac = len(live) / len(rows)
    assert frac > 0.85, (
        f"a music voice is sounding on only {frac:.1%} of {len(rows)} frames "
        f"— the song is not running continuously; check that sf_audio_tick is "
        f"pumped every frame and that Tad_LoadSong ran")


# =============================================================================
# what replaced the equality
# =============================================================================

def test_no_music_part_is_scored_where_an_effect_would_erase_it(driven):
    """The music-only rails' flat equality, re-stated for a rail with content.

    `tests/test_screen_effect_audio.py` can assert that voices 6 and 7 never
    sound at all, because the rails it covers queue nothing. This one queues a
    wind bed nearly continuously and a `select` on every press, so that
    equality is simply false here and relaxing it to a fraction would give up
    the claim entirely — "voices 6/7 are busy less than X% of the time" is
    satisfied by a song part.

    So the claim moves from WHETHER those voices sound to WHAT sounds on them.
    The rail queues exactly two effects, voiced by `saw` and `pluck`; the song
    uses `tri_bass`, `square_lead`, `pluck` and `kick`. Three of those four
    belong to no effect this rail can queue, so seeing one of them keyed on an
    SFX voice means a part was written on G or H — and that part vanishes
    every time the game makes a noise, which on this rail is nearly always.
    This is still an EQUALITY, just about the sample rather than the silence.

    The one shape it cannot see is a G part written with `pluck`, which is
    both an effect voice and channel D of the song. That hole is closed by the
    cadence case below: a music part sounds on a schedule of its own, and the
    cadence case bounds `pluck` on an SFX voice to the neighbourhood of a
    press.
    """
    rows, _, _, _ = driven
    bad = [(i, v, s) for i, (voices, _) in enumerate(rows)
           for v in SFX_VOICES
           for s, e in [voices[v]] if e and s in MUSIC_ONLY]
    assert not bad, (
        f"a music-only instrument is keyed on an SFX voice on {len(bad)} "
        f"frames (first: frame {bad[0][0]}, voice {bad[0][1]}, SRCN "
        f"{bad[0][2]}) — that part is on TAD channel G or H and the driver "
        f"ducks it for the duration of every effect this rail queues")


def test_the_kit_never_takes_the_noise_generator(driven):
    """There is ONE noise generator, and a music channel sharing it is muted
    the moment an effect wants it (`audio-driver.asm`, the `SfxNoise` branch).

    `wind` wants it roughly every eighty-five frames and holds it for most of
    the gap, so on this rail a noise part in the song would be gone almost all
    of the time rather than occasionally. The kit is samples: `kick` is a
    one-shot and there is no `N<0-31>` anywhere in the piece.

    THE SECOND HALF IS THE NON-VACUITY. Asserting only "no music voice is in
    NON" would pass just as green on a rail where the noise generator is
    untouched — including one whose wind stopped using it and went silent. So
    the mask must also be NON-ZERO: something is taking the generator, and it
    is on the SFX side of the split.
    """
    rows, _, _, _ = driven
    bad = [(i, non) for i, (_, non) in enumerate(rows) if non & MUSIC_MASK]
    assert not bad, (
        f"a music voice is in the noise mask on {len(bad)} frames (first "
        f"{bad[0][0]}, NON={bad[0][1]:#04x}) — that voice is silenced whenever "
        f"an effect plays noise, which on this rail is nearly every frame")
    used = sum(1 for _, non in rows if non)
    assert used / len(rows) > 0.90, (
        f"the noise generator is claimed on only {used}/{len(rows)} frames — "
        f"nothing is playing noise, so the mask above is vacuously clean; the "
        f"wind bed is not reaching the chip")


# =============================================================================
# the weather
# =============================================================================

def test_the_wind_is_audible(driven):
    """`wind` is voiced by `saw` (assets/audio/sound-effects.txt).

    `saw` is the ONE instrument in the project that this rail's song does not
    use, so seeing it keyed on an SFX voice is the bed and nothing else.
    """
    rows, _, _, _ = driven
    assert _sfx_live(rows, SAW), (
        "no saw voice ever sounded on an SFX channel — the wind bed never "
        "reached the chip; check that hz_weather is called from the tick and "
        "that SFX::wind is in the export")


def test_the_wind_is_a_bed_and_not_a_single_gust(driven):
    """CONTINUITY, which is the whole design problem this effect posed.

    A sound effect is a one-shot: `wind` runs 212 ticks of the driver's fixed
    125 Hz clock — 1.696 s, ~102 NTSC frames — and then it is over. Played
    once it is a gust. `hz_weather` re-queues it every HZ_WIND_PHASES = 32
    shimmer phases, and at HZ_PHASE_BASE = 0.375 phases a frame that is 85.3
    frames — SHORTER than the effect, so each re-queue lands while the
    previous is still sounding and the driver restarts it on the channel
    already playing it (`one_channel` + `interruptible`, vendor
    docs/sound-effects.md).

    TWO ASSERTIONS, BECAUSE A FRACTION ALONE IS NOT CONTINUITY. A bed that
    played for eight seconds and then stopped would still score 80%. So the
    fraction is joined by the longest run of frames with no wind at all.

    MEASURED on the shipped binary across this 600-frame drive: sounding on
    599 frames (99.8%), longest silent run ONE frame — the key-on itself. The
    bars are 90% and eight frames: far below the measurement, and far above
    what the defect they exist for produces. Planted with the cadence raised
    to 48 phases (128 frames, a gust every 2.1 s against a 1.7 s effect) the
    reading falls to 79.7% with a 26-frame hole, and both halves red.
    """
    rows, _, _, _ = driven
    live = _sfx_live(rows, SAW)
    frac = len(live) / len(rows)
    gap = _longest_gap(live, len(rows))
    assert frac > 0.90, (
        f"the wind sounds on {frac:.1%} of {len(rows)} frames — that is a "
        f"gust, not a bed; the re-queue cadence ({WIND_PERIOD:.1f} frames) has "
        f"out-run the {WIND_TICKS}-tick effect it is keeping alive")
    assert gap <= MAX_SILENT_RUN, (
        f"the wind is inaudible for {gap} consecutive frames — the bed lapses "
        f"between gusts even though it sounds on {frac:.1%} of the drive "
        f"overall; the cadence and the effect length have come apart")


# =============================================================================
# the cue
# =============================================================================

def test_the_toggle_is_audible(driven):
    """`select` is voiced by `pluck` (assets/audio/sound-effects.txt).

    The vocabulary's word for "a confirm, a gate accepting" — and `racer` uses
    it for exactly this, a control being operated rather than a thing
    happening in a world. Flattening the shimmer is a SETTING changing.
    """
    rows, _, _, _ = driven
    assert _sfx_live(rows, PLUCK), (
        "no pluck voice ever sounded on an SFX channel — the toggle cue never "
        "reached the chip, even though the control moved")


def test_the_toggle_cue_is_the_press_and_not_the_hold(driven):
    """B is DOWN for 60% of this drive and the cue must not be.

    The site reads ES_INP_PRESS, the rising edge the `input` feature
    publishes; the mistake this rail invites is reading ES_INP_CUR instead,
    which is one token away and needs no other change to compile. Planted that
    way the cue is re-queued on every held frame and the driver restarts it on
    the channel already playing it, so the pluck sounds through the whole
    hold.

    MEASURED: correct, 60 of 600 frames — 10.0%, four frames of decay per
    press, fifteen times. Planted on ES_INP_CUR, 51.8%. The bar is 30%: five
    times the correct reading and well clear of the planted one.

    THE CADENCE CASE ALSO CLOSES THE HOLE the equality case left open. A song
    part scored on G with `pluck` would sound on its own schedule — the song's
    own D channel is live on 30 frames of this drive on a MUSIC voice, and any
    part moved to G would add to the SFX-voice count without regard to the
    pad. This bound is what refuses it.
    """
    rows, _, _, _ = driven
    live = _sfx_live(rows, PLUCK)
    frac = len(live) / len(rows)
    assert frac < 0.30, (
        f"the pluck voice is live on {frac:.1%} of frames, against a drive "
        f"holding B for {HOLD}/{PERIOD} of each cycle — the toggle cue is "
        f"reading the HELD state (ES_INP_CUR) rather than the press edge "
        f"(ES_INP_PRESS), or a music part has been written onto G/H with it")
