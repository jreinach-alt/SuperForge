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
    generator is genuinely in use, by an SFX voice, and never by a music one.
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


# THE WIND'S CADENCE CONSTANTS ARE GONE, with the mechanism they described.
# This module used to derive a re-queue period from `HZ_WIND_PHASES` and
# `HZ_PHASE_BASE` and check it against the 212-tick length of a `wind` sound
# effect, because continuity had to be MANUFACTURED: an effect is a one-shot,
# so the bed only held if the rail re-queued it faster than it ran out. The
# wind is a noise channel in the song now (far_ridge_song, channel F) and a
# song channel with `&` slurs sends no key-off at all, so there is no cadence
# left to keep in step with anything and no constant to read.
#
# `HZ_WIND_PHASES` was removed from heathaze.inc in the same change, and this
# module's collection-time read of it is what caught the removal — in the
# landing gate rather than here, because the rail's own module was not re-run
# after the constant went. dx_paper_cuts has the entry.

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

# The longest run of frames the wind may be inaudible for. A song noise
# channel that is slurred throughout never keys off, so the correct reading
# is ZERO and that is what the shipped binary measures across the whole
# 600-frame drive. Eight leaves room for a key-on landing either side of a
# sample without weakening what it catches: the defect it exists for is the
# part scored as `N17 w1` rather than `N17,1 &`, where the default note
# length takes over and the voice sounds on 112 of 600 frames with whole
# silent bars between.
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
                # (SRCN, ENVX, VOL_L) — the VOLUME is here because loudness
                # is the product of the envelope and the channel volume, and
                # a row without it can only answer "is this sounding".
                [(d[v * 0x10 + 4], d[v * 0x10 + 8], d[v * 0x10 + 0])
                 for v in range(8)],
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
            if any(voices[v][0] == srcn and voices[v][1] for v in SFX_VOICES)]


def _amp(rows, voice):
    """Peak VOL x ENVX for `voice` — what the S-DSP actually contributes.

    The chip multiplies a voice's envelope by its channel volume, so neither
    byte alone is loudness: the effect-based wind sat at ENVX 48 with VOL 18
    and read as "sounding" on every frame it was inaudible. VOL is signed
    (a negative value inverts the phase), so magnitude is what counts.
    """
    def mag(vol):
        return abs(vol - 256 if vol > 127 else vol)
    return max(mag(row[voice][2]) * row[voice][1] for row, _ in rows)


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
           for s, e in [voices[v][:2]] if e and s in MUSIC_ONLY]
    assert not bad, (
        f"a music-only instrument is keyed on an SFX voice on {len(bad)} "
        f"frames (first: frame {bad[0][0]}, voice {bad[0][1]}, SRCN "
        f"{bad[0][2]}) — that part is on TAD channel G or H and the driver "
        f"ducks it for the duration of every effect this rail queues")


def test_exactly_one_music_voice_takes_the_noise_generator(driven):
    """There is ONE noise generator, and the wind is now the part that holds it.

    THIS CASE USED TO FORBID WHAT IT NOW REQUIRES, and the reversal is the
    design change rather than a weakening. The wind was a low-priority SOUND
    EFFECT re-queued on a cadence; it was measured on the chip at roughly 7%
    of a music voice's amplitude (VOL 18 / ENVX 48 against the drone's 42 /
    127) and could not be heard under the song. It is now a NOISE CHANNEL IN
    THE SONG (`far_ridge_song.mml`, channel F), which is where the hardware
    wants weather: a music channel cannot be ducked for an effect or dropped
    for priority, `w`/`&` sustain the noise with no re-trigger seam, it mixes
    in the score's own units, and it reaches the echo -- which is what makes a
    band of noise read as moving air rather than as tape hiss.

    So the claim inverts, and what replaces it is SHARPER, not looser. The
    hazard the old case existed for is real and unchanged: a song channel
    sharing the generator is muted the moment an effect wants it. What makes
    that safe here is that NO EFFECT ON THIS RAIL PLAYS NOISE -- the only cue
    is `select`, voiced by pluck. The three assertions are that whole
    argument:

      * EXACTLY ONE music voice is in the mask, never two. A second noise part
        would fight the first for one generator.
      * It is the WIND's voice -- the one keyed to `saw`. Any other channel in
        the mask means a part was scored into the generator by accident.
      * NO SFX VOICE is ever in the mask. That is the condition under which a
        song noise channel is legal at all; the day this rail gains a noisy
        cue, the wind goes silent under it and this case says so first.
    """
    rows, _, _, _ = driven
    music_bits = [(i, non & MUSIC_MASK) for i, (_, non) in enumerate(rows)]
    multi = [(i, m) for i, m in music_bits if m and (m & (m - 1))]
    assert not multi, (
        f"two music voices share the noise generator on {len(multi)} frames "
        f"(first {multi[0][0]}, mask={multi[0][1]:#04x}) — there is only one, "
        f"so one of those parts is silent whenever the other sounds")
    wrong = [(i, m, [v for v in MUSIC_VOICES if m >> v & 1])
             for i, (row, non) in enumerate(rows)
             for m in [non & MUSIC_MASK]
             if m and not all(row[v][0] == SAW for v in MUSIC_VOICES if m >> v & 1)]
    assert not wrong, (
        f"a music voice that is NOT the wind is in the noise mask on "
        f"{len(wrong)} frames (first {wrong[0][0]}, voices {wrong[0][2]}) — "
        f"the wind is the one part scored with N<0-31>, so anything else "
        f"there was put on the generator by accident")
    sfx_noise = [(i, non) for i, (_, non) in enumerate(rows)
                 if non & ~MUSIC_MASK & 0xFF]
    assert not sfx_noise, (
        f"a SOUND EFFECT takes the noise generator on {len(sfx_noise)} frames "
        f"(first {sfx_noise[0][0]}, NON={sfx_noise[0][1]:#04x}) — the song's "
        f"wind channel is muted for every one of them, which is the whole "
        f"reason this rail's only cue is a pluck")


# =============================================================================
# the weather
# =============================================================================

def _wind_voice(rows):
    """The music voice keyed to `saw`, which on this rail is the wind alone."""
    for row, _ in rows:
        for v in MUSIC_VOICES:
            if row[v][0] == SAW and row[v][1]:
                return v
    return None


def test_the_wind_is_audible(driven):
    """The wind is voiced by `saw` on a MUSIC channel (far_ridge_song.mml, F).

    `saw` is the one instrument in the project the rest of this song does not
    use, so a music voice keyed to it is the wind and nothing else.
    """
    rows, _, _, _ = driven
    v = _wind_voice(rows)
    assert v is not None, (
        "no music voice was ever keyed to saw and sounding — the wind channel "
        "never reached the chip; check that far_ridge_song's channel F is "
        "scored and that the export was regenerated")
    assert any(non & (1 << v) for _, non in rows), (
        f"the wind is on voice {v} but that voice is never in the noise mask "
        f"— it is playing saw's WAVEFORM rather than the noise generator, so "
        f"the part is a buzz and not weather; check the N<0-31> commands")


def test_the_wind_is_loud_enough_to_be_heard_under_the_song(driven):
    """THE CASE THE ORIGINAL BUG WOULD HAVE FAILED, and the reason it exists.

    The wind's first implementation SOUNDED on 99.8% of frames and swept its
    noise band exactly as scored — and was reported as inaudible, correctly.
    Every assertion in this module passed on it, because they all asked
    WHETHER the voice was sounding and none asked HOW LOUD. `ENVX > 0` is true
    at an amplitude nobody can hear, which makes presence-only audibility an
    indirect-evidence test in the sense CLAUDE.md rule 2 forbids: green while
    the feature is silently broken.

    So the claim here is a RATIO, measured against this song's own drone
    rather than against an absolute the mix could drift away from. A voice's
    contribution is VOL x ENVX (the S-DSP multiplies the envelope by the
    channel volume), and the bar is that the wind reaches a quarter of the
    loudest music voice's peak product.

    MEASURED on the shipped binary: the wind peaks at VOL 36 x ENVX 127 =
    4572 against the loudest music voice's 5334, a ratio of 0.86. The original
    effect-based bed peaked at VOL 18 x ENVX 48 = 864 against the same
    denominator — 0.16.

    THE BAR WAS SET BY A PLANT, NOT BY EYE, and the first attempt at it was
    too loose to be worth having. Scoring the channel at `v3` instead of `v9`
    drops the wind to VOL 12 (1524, ratio 0.29) — plainly too quiet to hear,
    and it PASSED a 0.25 bar chosen by guessing. At 0.50 the shipped reading
    keeps a wide margin while both the `v3` plant and the original effect-based
    bed red. A bar for an audibility claim has to be checked against a
    deliberately-too-quiet build; a threshold nothing was ever measured
    against is the same indirect evidence this case exists to replace.
    """
    rows, _, _, _ = driven
    v = _wind_voice(rows)
    assert v is not None, "no wind voice — see test_the_wind_is_audible"
    wind_amp = _amp(rows, v)
    music_amp = max(_amp(rows, m) for m in MUSIC_VOICES if m != v)
    ratio = wind_amp / music_amp
    assert ratio > 0.50, (
        f"the wind peaks at {wind_amp} against the loudest music voice's "
        f"{music_amp} — a ratio of {ratio:.2f}. It is sounding, and it is too "
        f"quiet to hear under the song; that is exactly the state the "
        f"effect-based bed shipped in")


def test_the_wind_is_a_bed_and_not_a_single_gust(driven):
    """CONTINUITY, which is the whole design problem weather poses.

    A SOUND EFFECT could not be continuous without help: it is a one-shot, so
    the first implementation re-queued it every 85 frames to overlap its own
    1.70 s length, and the seam was permanent maintenance — the cadence and
    the effect length had to stay in step or the bed lapsed.

    A SONG CHANNEL IS CONTINUOUS BY CONSTRUCTION, and that is most of why the
    part moved. `saw` LOOPS, so `play_noise` runs until a key-off; every band
    carries its own length and every join is a `&` slur, so no key-off is ever
    sent and the noise clock changes inside one held breath. There is no
    cadence left to drift.

    The bars stay because the mechanism can still fail, and its failure mode
    is now a SCORING error rather than an arithmetic one. Planted with the
    slurs removed and the lengths dropped -- `N17 w1` rather than `N17,1 &`,
    which is how this part was first written -- the default note length takes
    over and the voice sounds on 112 of 600 frames with silent bars between:
    both halves red. MEASURED on the shipped binary: 600/600 frames, longest
    silent run zero.
    """
    rows, _, _, _ = driven
    v = _wind_voice(rows)
    assert v is not None, "no wind voice — see test_the_wind_is_audible"
    live = [i for i, (row, non) in enumerate(rows)
            if row[v][1] and non & (1 << v)]
    frac = len(live) / len(rows)
    gap = _longest_gap(live, len(rows))
    assert frac > 0.90, (
        f"the wind sounds on {frac:.1%} of {len(rows)} frames — that is a "
        f"gust, not a bed; a song noise channel should hold across its slurs, "
        f"so check that every band carries a length and every join a `&`")
    assert gap <= MAX_SILENT_RUN, (
        f"the wind is inaudible for {gap} consecutive frames — the bed lapses "
        f"even though it sounds on {frac:.1%} of the drive overall")


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
