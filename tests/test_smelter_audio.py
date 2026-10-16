"""smelter's own song and its two cues, on the chip that plays them.

THIS RAIL USED TO BE MUSIC-ONLY and `tests/test_screen_effect_audio.py` still
covers the claim it made then, parameterised across the four screen-effect
rails. What changed on 2026-09-09 is that `smelter` acquired a song written
for it (`assets/audio/mml/foundry_song.mml`, in place of the tree's generic
ambient piece) and TWO discrete cues — so it is no longer one of four rails
making one claim, and the claims it can make are both stronger and weaker than
they were. This module is where the difference lives.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For
audio that is the S-DSP voice: `VxENVX > 0` (byte v*0x10+8) says a voice is
SOUNDING, `VxSRCN` (v*0x10+4) says which sample it is keyed to, and `NON`
(register 0x3D) says which voices are taking the noise generator. Nothing here
reads the request ring or a driver flag: the ring is consumed and cleared
inside the frame that fills it (`engine/features/audio/tad_wrapper.asm`), so a
case watching it would pass on a silent rail.

WHAT G AND H CAN STILL BE ASSERTED AS, NOW THAT THE RAIL QUEUES THINGS.
Channels G/H map onto DSP voices 6 and 7 and the driver DUCKS them for the
duration of any sound effect, so a part scored there vanishes whenever the game
makes a noise. The music-only module asserts that as a flat equality, which it
can because those rails queue nothing. Here voices 6/7 are legitimately busy —
they are where the cues come out — so the equality has to be split in two, and
the pair is what the single equality used to buy:

  * ON A DRIVE WITH NO INPUT AT ALL the equality still holds exactly, and this
    is the strong half: nothing is queued in that window, so ANY sounding on
    6/7 is a part of the song, whatever instrument it is written with.
  * ON THE CUE DRIVE the claim becomes a bound plus an attribution — 6/7 sound
    on only a small fraction of frames, and every frame they sound on carries
    one of the two cue samples. That catches a part scored on G with an
    instrument the song does not otherwise use; the no-input case catches the
    rest.

TWO CUES AND NO LATCH. Both sites in `game/smelter/scenes/works.asm` are gated
on `ES_INP_PRESS`, which the `input` feature publishes as the RISING edge
(`cur & ~prev`), so each runs at most once per press however long the button is
held. The mistake this rail invites is `ES_INP_CUR`, one token away — and on
the B toggle that defect is TWO defects at once, because the same edge drives
the cue and the `eor` that flips `ES_SMT_FLATSEL`. So the cadence case and the
toggle-state case are aimed at the same line from opposite sides, and a
level-read reds both.

THE START CUE IS DIFFERENT AND SAYS SO. Its site runs two instructions before
`SM_SWITCH "WORKS", "TITLE"`, so the scene it lives in is ending; there is no
long hold window to distinguish an edge from a level the way the toggle has.
What it gets instead is an audibility case and the SCENE ID — the drive that
sounds the departure must actually have departed.

EVERY FIXTURE ASSERTS THE GAME STATE MOVED. The idle drive checks that the
animation phase actually advanced and that the scene is the works; the cue
drive checks the toggle's whole alternation and the arrival at the title. A
rotted drive therefore fails naming the game state rather than going quiet on
a cue and reading as a defect in the audio.
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
SFX_VOICES = (6, 7)                 # G/H, ducked while an effect plays
MUSIC_MASK = 0x3F                   # NON bits for voices 0-5

# Instrument order in assets/audio/slice_b.terrificaudio, which is what the
# compiler numbers the sample table by. `select` is voiced by pluck and
# `chime` by bell (assets/audio/sound-effects.txt) — two DIFFERENT samples on
# purpose, which is what lets each cue be attributed to its own press.
PLUCK, BELL = 2, 4
CUE_SAMPLES = (PLUCK, BELL)

_MAP = json.loads((SUPERFORGE / "build" / "smt" / "symbol_map.json").read_text())
_DP = {p["sym"]: p["start"]
       for p in _MAP["scenes"]["works"]["placements"] if p["class"] == "dp"}
DP_FLAT = _DP["ES_SMT_FLATSEL"]
DP_PHASE = _DP["ES_SMT_PHASE"]
DP_CTL = {p["sym"]: p["start"] for p in _MAP["globals"]}["ES_SM_CTL"]

# The scene ids come from the DECLARED edges, not from a hand-written 0 and 1 —
# the same place SM_SWITCH takes its destination from. `sm_nmi_hook` compares
# ES_SM_CTL in A8, so the running scene is its LOW BYTE.
_E = {(e["src"], e["dst"]): e["dst_scene_index"] for e in _MAP["edges"]}
WORKS_ID = _E[("title", "works")]
TITLE_ID = _E[("works", "title")]

TITLE_WAIT = 40             # frames on the title before Start...
SETTLE = 90                 # ...and after it: the fade, then a settled run

# foundry_song's loop is 1344 ticks at #Tempo 54, i.e. 1344 * 60/(48*54) s =
# 31.11 s = 1867 NTSC frames. This drive is longer than that ON PURPOSE: the
# piece's two halves are not the same (the ratchet fills the first, the lead
# the second — the MML header says why), so a drive that fitted inside one
# half would assert continuity over material it never heard, and a drive that
# stopped at the loop point would never prove the song RESTARTS rather than
# running out of data.
LOOP_FRAMES = 1867
IDLE_FRAMES = 2000
PHASE_EVERY = 25            # ...frames between animation-phase samples

PRESSES = 12
PERIOD = 40                 # frames per B press cycle...
HOLD = 24                   # ...of which this many hold B down
START_HOLD = 20             # and Start is held this long, then watched
START_WATCH = 40


def _rom():
    p = SUPERFORGE / "build" / "smelter.sfc"
    assert p.exists(), "build/smelter.sfc not built — run `make smelter`"
    return str(p)


def _enter_works(r):
    """Boot, wait on the title, press Start, let the fade settle."""
    r.boot_rom(_rom(), frames=200)
    r.frame_step(TITLE_WAIT)
    r.frame_step(1, **{"start": True})
    r.frame_step(SETTLE)


def _scene(r):
    return r.read_bytes(W, DP_CTL, 1)[0]


def _sfx_row(d):
    """(srcn, envx) for each of the two sound-effect voices."""
    return [(d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in SFX_VOICES]


def _cue_frames(rows, srcn):
    return [i for i, row in enumerate(rows)
            if any(s == srcn and e for s, e in row)]


@pytest.fixture(scope="module")
def played():
    """The works scene, running, with NO input at all for a full song loop.

    No pad after the one Start that enters the scene, which is what makes the
    G/H case below an equality: nothing is queued inside this window.
    """
    r = MesenRunner(enable_audio=True)
    rows, phases = [], []
    try:
        _enter_works(r)
        scene_before = _scene(r)
        for i in range(IDLE_FRAMES):
            r.frame_step(1)
            d = r.read_bytes(DSP, 0, 128)
            rows.append(([d[v * 0x10 + 8] for v in range(8)], d[0x3D]))
            if i % PHASE_EVERY == 0:
                phases.append(r.read_u16(W, DP_PHASE))
        scene_after = _scene(r)
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failed read above would strand the NEXT module's runner and make
        # it name itself (tests/conftest.py, the parked-core guard).
        r.stop()
    return rows, phases, scene_before, scene_after


@pytest.fixture(scope="module")
def driven():
    """Press B `PRESSES` times holding it for most of each cycle, then Start.

    The long hold is what the cadence case needs: 24 of every 40 frames have B
    down, so a cue read off the HELD state rather than the press edge has 60%
    of the drive to sound in while the correct one has twelve instants. Start
    is held too — the works scene keeps ticking through the departure fade, so
    a level-read there would re-queue as well.
    """
    r = MesenRunner(enable_audio=True)
    b_rows, start_rows, flat_seq, scenes = [], [], [], []
    try:
        _enter_works(r)
        scene_before = _scene(r)
        flat_before = r.read_u16(W, DP_FLAT)
        for i in range(PRESSES * PERIOD):
            r.frame_step(1, **{"b": i % PERIOD < HOLD})
            b_rows.append(_sfx_row(r.read_bytes(DSP, 0, 128)))
            if i % PERIOD == PERIOD - 1:
                flat_seq.append(r.read_u16(W, DP_FLAT))
                scenes.append(_scene(r))
        for i in range(START_HOLD + START_WATCH):
            r.frame_step(1, **{"start": i < START_HOLD})
            start_rows.append(_sfx_row(r.read_bytes(DSP, 0, 128)))
        scene_after = _scene(r)
    finally:
        r.stop()
    return dict(b_rows=b_rows, start_rows=start_rows, flat_before=flat_before,
                flat_seq=flat_seq, scenes=scenes,
                scene_before=scene_before, scene_after=scene_after)


# --- the drive's own checks, before anything is claimed about the sound -----

def test_the_idle_drive_reached_the_works_and_the_columns_moved(played):
    """Non-vacuity for the music cases, and it is the GAME state.

    `ES_SMT_PHASE` is the column animation's position, advanced every frame by
    `smt_advance` from the region-scaled step (SMT_PHASE_BASE = $0060, i.e.
    0.375 phases a frame, so the 64-row table is walked about every 171
    frames). A drive that never entered the works, or that entered and hung,
    fails HERE — naming the rail — instead of failing the continuity case
    below and reading as a defect in the song.
    """
    _, phases, before, after = played
    assert (before, after) == (WORKS_ID, WORKS_ID), (
        f"the idle drive ran in scene {before} -> {after}, not the works "
        f"({WORKS_ID}) throughout — the music cases would be measuring the "
        f"wrong scene")
    assert len(set(phases)) >= 16, (
        f"the column animation visited only {len(set(phases))} distinct "
        f"phases in {len(phases)} samples across {IDLE_FRAMES} frames — the "
        f"rail is not running, so nothing below is being measured on a live "
        f"scene")


def test_the_cue_drive_toggled_the_control_once_per_press(driven):
    """The state half of the edge claim, and the sharper half of the two.

    `ES_SMT_FLATSEL` is the flat/offset control the B press flips. The `eor`
    that flips it and the `select` that sounds it are gated on the SAME
    `ES_INP_PRESS` bit, so this alternation and the cadence case below are two
    readings of one line. B is held for 24 frames of every 40: on the press
    edge that is one flip a cycle and the value alternates; on the held level
    it would be twenty-four flips a cycle, an even number, and every sample
    here would read back 0.
    """
    d = driven
    assert d["flat_before"] == 0, (
        f"the works entered with ES_SMT_FLATSEL = {d['flat_before']}, not 0 — "
        f"scenes/works.asm's enter zeroes it, so the alternation below has no "
        f"known starting point")
    expected = [(i + 1) % 2 for i in range(PRESSES)]
    assert d["flat_seq"] == expected, (
        f"ES_SMT_FLATSEL read {d['flat_seq']} at the end of {PRESSES} press "
        f"cycles, not {expected} — the B toggle is not running once per press "
        f"(all-zero says it is reading the HELD state; all-one-value says it "
        f"stopped toggling at all)")
    assert set(d["scenes"]) == {WORKS_ID}, (
        f"the press drive left the works scene (saw {sorted(set(d['scenes']))}"
        f") — the cue cases would be measuring a scene that is not the one "
        f"with the toggle in it")


def test_the_start_press_left_the_hall(driven):
    """The state half of the departure claim.

    `chime` sounds two instructions before `SM_SWITCH "WORKS", "TITLE"`. If
    the switch stops happening the cue is still audible and still correct —
    which is exactly why the scene id is asserted separately rather than being
    inferred from the sound.
    """
    d = driven
    assert d["scene_before"] == WORKS_ID
    assert d["scene_after"] == TITLE_ID, (
        f"after the Start press the running scene is {d['scene_after']}, not "
        f"the title ({TITLE_ID}) — the departure cue below would be sounding "
        f"for a departure that did not happen")


# --- the song ---------------------------------------------------------------

def test_the_song_plays_continuously_across_a_full_loop(played):
    """Not merely audible once — CONTINUOUS, and over the whole 1344-tick loop.

    Two resolutions, because a global fraction alone can hide a hole: a song
    silent for three seconds in the middle of a thirty-three second drive
    still reads 90%. So the fraction is the headline and the longest unbroken
    silent RUN is the shape.

    Neither bar is 100%: `foundry_song` puts a key-off at the end of every
    whole-note bar on the pedal and quantizes the ostinato at Q6, so the bar
    line is a real instant where all five running voices can be between notes.
    Measured on the shipping ROM: 13 such frames in 2000, none of them
    adjacent — 99.3% live, longest run 1. Planted with `Song::BLANK` loaded
    instead, this case reds at 0% and every other case in the module stays
    green, which is what says it is reading the SONG rather than the driver.
    """
    rows, _, _, _ = played
    live = [any(env[v] for v in MUSIC_VOICES) for env, _ in rows]
    frac = sum(live) / len(live)
    assert frac > 0.90, (
        f"a music voice is sounding on only {frac:.1%} of {len(rows)} frames "
        f"— the song is not running continuously; check that sf_audio_tick is "
        f"pumped every frame and that Tad_LoadSong ran with foundry_song")
    run = worst = 0
    for ok in live:
        run = 0 if ok else run + 1
        worst = max(worst, run)
    assert worst <= 8, (
        f"the longest unbroken silence is {worst} frames of {len(rows)} "
        f"(fraction live {frac:.1%}) — a gap that long is a song that stopped "
        f"and restarted, not a bar line")
    assert len(rows) > LOOP_FRAMES, (
        f"the drive is {len(rows)} frames and the song's loop is "
        f"{LOOP_FRAMES} — it must be longer, or 'continuous' is a claim about "
        f"a window rather than about the loop")


def test_nothing_is_scored_where_a_cue_would_erase_it(played):
    """An EQUALITY, and it is a no-input drive that lets it stay one.

    Voices 6 and 7 are ducked for the duration of any sound effect. This rail
    now queues two, so the equality can only be asserted where none is queued
    — and here none is: after the Start that enters the works this drive
    touches no button for two thousand frames. Any sounding at all in that
    window is a part of `foundry_song` written on G or H, which would drop out
    every time the player toggled the control.
    """
    rows, _, _, _ = played
    busy = [i for i, (env, _) in enumerate(rows)
            if any(env[v] for v in SFX_VOICES)]
    assert not busy, (
        f"voices 6/7 sound on {len(busy)} of {len(rows)} frames (first at "
        f"{busy[0]}) on a drive that queues no effect at all — foundry_song "
        f"is scored on G or H")


def test_the_kit_never_takes_the_noise_generator(played):
    """There is one noise generator, and a music channel sharing it is muted
    the moment an effect wants it (`audio-driver.asm`, the `SfxNoise` branch).

    `foundry_song`'s percussion is `kick` and `step` — SAMPLES — for exactly
    that reason. Neither of this rail's own cues takes noise, but `explosion`,
    `hit` and `skid` sit in the same shared blob and any rail can grow one, so
    a noise part here would be a part that vanishes the day one does.
    """
    rows, _, _, _ = played
    bad = [(i, non) for i, (_, non) in enumerate(rows) if non & MUSIC_MASK]
    assert not bad, (
        f"a music voice is in the noise mask on {len(bad)} frames (first "
        f"{bad[0][0]}, NON={bad[0][1]:#04x}) — that voice is silenced "
        f"whenever an effect plays noise")


# --- the cues ---------------------------------------------------------------

def test_the_toggle_is_audible(driven):
    """`select` is voiced by pluck (assets/audio/sound-effects.txt)."""
    hits = _cue_frames(driven["b_rows"], PLUCK)
    assert hits, (
        "no pluck voice ever sounded on a sound-effect channel across "
        f"{PRESSES} B presses — the toggle cue never reached the chip")


def test_the_toggle_cue_is_the_press_and_not_the_hold(driven):
    """B is DOWN for 60% of this drive and the cue must not be.

    The site reads ES_INP_PRESS, the rising edge; the mistake this rail
    invites is ES_INP_CUR, one token away. Read that way the ring is handed a
    `select` on every held frame and the driver delivers one per frame, so the
    pluck voice sounds through most of the hold. The bar sits far below that
    and far above what twelve short plucks cost — measured on the shipping ROM
    at 10% of frames, and at 62% with the level read planted.
    """
    rows = driven["b_rows"]
    frac = len(_cue_frames(rows, PLUCK)) / len(rows)
    assert frac < 0.30, (
        f"the pluck voice is live on {frac:.0%} of frames, against a drive "
        f"holding B for {HOLD}/{PERIOD} of each cycle — the toggle cue is "
        f"reading the HELD state (ES_INP_CUR) rather than the press edge "
        f"(ES_INP_PRESS)")


def test_leaving_the_hall_is_audible(driven):
    """`chime` is voiced by bell — a DIFFERENT sample from the toggle's pluck.

    That is what makes this case a separate reading rather than a re-reading
    of the one above: the departure is attributable to its own press because
    the chip says which sample keyed, not merely that something did.
    """
    hits = _cue_frames(driven["start_rows"], BELL)
    assert hits, (
        "no bell voice ever sounded on a sound-effect channel across the "
        "Start press — the departure cue never reached the chip")


def test_the_two_cues_do_not_bleed_into_each_others_windows(driven):
    """Each sample belongs to one press, which is the attribution working.

    A bell in the B window would mean the toggle fired `chime`; a pluck in the
    Start window would mean the toggle's cue was still being queued after the
    scene ended. Both are wiring defects a bare "something sounded" case would
    pass.
    """
    assert not _cue_frames(driven["b_rows"], BELL), (
        "the bell voice sounds during the B press drive — the toggle is "
        "queueing `chime` rather than `select`")
    assert not _cue_frames(driven["start_rows"], PLUCK), (
        "the pluck voice sounds during the Start window — a `select` is being "
        "queued after the departure")


def test_only_the_cues_ever_reach_the_effect_voices(driven):
    """The bound the no-input equality becomes once the rail queues things.

    Two halves. Voices 6/7 are busy on only a small share of the drive — a
    PART scored there would sound nearly always — and every frame they are
    busy on carries one of the two cue samples, never one of the song's own.
    Together with the equality on the idle drive this is what the music-only
    module's single equality used to buy. Measured: 10% of frames live, 56%
    with the toggle's level-read planted and 99% with eight bars added to a
    `G` channel — so the bound at 0.35 has margin on both sides.
    """
    rows = driven["b_rows"] + driven["start_rows"]
    busy = [i for i, row in enumerate(rows) if any(e for _, e in row)]
    frac = len(busy) / len(rows)
    assert frac < 0.35, (
        f"the effect voices are busy on {frac:.0%} of {len(rows)} frames — "
        f"{PRESSES + 1} cues cannot fill that much of a drive, so something "
        f"is sounding on G/H that is not a cue")
    stray = sorted({s for row in rows for s, e in row
                    if e and s not in CUE_SAMPLES})
    assert not stray, (
        f"sample(s) {stray} sound on the effect voices, and this rail queues "
        f"only select (pluck={PLUCK}) and chime (bell={BELL}) — a part of "
        f"foundry_song is scored on G or H")
