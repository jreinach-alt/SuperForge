"""lakeside's soundtrack and its two cues, on the chip that plays them.

TEST SURFACE, per CLAUDE.md rule 2 — the rendered output, never a proxy. For
audio that is the S-DSP: `VxENVX > 0` (byte v*0x10+8) says a voice is
SOUNDING, `VxSRCN` (v*0x10+4) says which sample it is keyed to, and `NON`
(0x3D) says which voices are taking the one noise generator. The ca65 SFX
queue byte is consumed and cleared inside the frame that fills it, so it is
unreadable at any frame boundary and is never asserted on here.

WHAT THIS RAIL SOUNDS LIKE, AND WHY IT IS TESTABLE AT ALL

`lakeside` is a screen effect: a lake surface half-added over a lakeshore
world, drifting left, with B latching it STILL. It has one song written for
it (`shallow_water_song`) and two cues:

  * `wave_break` — a noise swell into a break into a long drain, queued once
    per SURF CYCLE. Not on a timer: the cue's clock is `US_WAVE`, which counts
    the same region-scaled pixels `wat_advance` moves the surface by, from the
    same zero, so `US_WAVE == ES_WAT_SCROLL mod LK_SURF_PERIOD_PX` holds for
    ever and the break is heard on the frame the swash on screen restarts.
  * `select` — the B press that latches and releases the still gate.

THE STILLED CASE IS THE ONE WORTH HAVING, and it is why the wave was hung off
the picture's own position rather than a frame counter. `wat_advance` is
skipped while `US_STILLED` is set, and `lk_wave_cue` sits in the SAME branch,
so a frozen lake cannot crash. "Stilled" is a LATCHED state rather than a
per-frame condition, which makes that a bar of zero — an exact equality on a
long window — rather than a fraction. A rail whose water is visibly frozen and
audibly breaking would be the sharpest possible version of a sound and a
picture disagreeing, and this module refuses it by measurement.

THE OTHER CUE IS ABOUT EDGES. `select` fires off ES_INP_PRESS, the rising edge
the `input` feature publishes, so it runs at most once per press however long B
is held. The mistake the site invites is `ES_INP_CUR`, one token away, which
sounds on every held frame — so the toggle drive HOLDS B for 60% of its length
and the case is a fraction, not a count. Both readings are audible; only the
fraction tells them apart. `tests/test_hud_game_audio.py` makes the same
measurement on the same shape.

WHY "NOTHING ON G OR H" IS NOT A FLAT EQUALITY HERE.
`tests/test_screen_effect_audio.py` can assert voices 6/7 are NEVER live on
the music-only rails, because those rails queue nothing. This one queues two
effects, and 6/7 are exactly where TAD plays them — so the honest form is a
statement about WHAT is there rather than whether anything is: on a drive with
no input at all the only cue that can fire is the wave, so the set of samples
ever keyed on 6/7 must be exactly {saw}, and the voices must fall silent
between waves. A song part scored on G or H would key some other sample there,
or would keep the voices live through the lull. The stilled window gives back
the equality in its strongest form: 6/7 flat zero for 256 consecutive frames.

EVERY FIXTURE ASSERTS THE GAME STATE MOVED, so a rotted drive fails naming
`ES_WAT_SCROLL` or `US_STILLED` rather than going quiet on a cue and reading
as a defect in the audio.
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
SFX_VOICES = (6, 7)                 # G/H — where the driver plays effects
MUSIC_MASK = 0x3F                   # NON bits for voices 0-5

# Instrument order in assets/audio/slice_b.terrificaudio, which is what SRCN
# indexes. `saw` voices `wave_break`; `pluck` voices `select` (and the song's
# lead, but that is on a MUSIC voice and this module only reads 6/7).
SAW = 5
PLUCK = 2

# --- the addresses, from the allocator's emitted map ------------------------
_MAP = json.loads((SUPERFORGE / "build" / "lks" / "symbol_map.json").read_text())
_LAKE_DP = {p["sym"]: p["start"]
            for p in _MAP["scenes"]["lake"]["placements"] if p["class"] == "dp"}
_GLOBAL_DP = {p["sym"]: p["start"]
              for p in _MAP["globals"] if p["class"] == "dp"}
DP_SCROLL = _LAKE_DP["ES_WAT_SCROLL"]
DP_STILLED = _LAKE_DP["US_STILLED"]
DP_WAVE = _LAKE_DP["US_WAVE"]
DP_SM_CTL = _GLOBAL_DP["ES_SM_CTL"]

# --- the art's own cycle, read where the ROM reads it -----------------------
# The wave's cadence is LK_SURF_PERIOD_PX of drift, and that number is
# GENERATED (build/assets/lk_art.inc) — re-authoring the surf moves it. Reading
# it here for the same reason water.asm does: a copy would go stale with every
# gate still green. LK_WATER_SPEED comes from the rail's own tuning include.
_ART = {}
for _line in (SUPERFORGE / "build" / "assets" / "lk_art.inc").read_text().splitlines():
    if "=" in _line and not _line.lstrip().startswith(";"):
        _k, _v = _line.split("=", 1)
        _ART[_k.strip()] = int(_v.strip())
assert _ART["LK_ART_FORMAT"] == 2, (
    f"lk_art.inc is format {_ART['LK_ART_FORMAT']} — this module reads 2")
SURF_PERIOD_PX = _ART["LK_SURF_PERIOD_PX"]

_INC = (SUPERFORGE / "game" / "lakeside" / "lakeside.inc").read_text()
SPEED = int(next(l.split("=")[1].split(";")[0]
                 for l in _INC.splitlines() if l.startswith("LK_WATER_SPEED")))
# NTSC publishes the base rate to the pixel (tick_scale: the scale is 1 and the
# carried fraction stays 0), so one cycle is this many frames on this machine.
# On PAL the same 128 px arrive in fewer, larger steps and the wall-clock
# interval is the same — which is the point of hanging the cue off TS_STEP.
CYCLE_FRAMES = SURF_PERIOD_PX // SPEED          # 128

# --- the drives -------------------------------------------------------------
DRIFT_FRAMES = 560              # >= four wave onsets, so three gaps to measure
STILL_FRAMES = 320              # ...and a long look at a frozen shore
STILL_SETTLE = 64               # a wave already breaking when the surface
                                #   latches plays out; that is right, the sea
                                #   does not stop mid-break. One wave is ~52
                                #   frames, so this covers the longest one that
                                #   can be in flight at the press.
LEAD = 40                       # idle frames before the first B press
PRESSES = 11
PERIOD = 40                     # frames per press cycle...
HOLD = 24                       # ...of which this many hold B down (60%)


def _rom():
    p = SUPERFORGE / "build" / "lakeside.sfc"
    assert p.exists(), "build/lakeside.sfc not built — run `make lakeside`"
    return str(p)


def _u16(r, addr):
    return int.from_bytes(r.read_bytes(W, addr, 2), "little")


def _enter_lake(r, budget=240):
    """Drive from the title into a lake scene whose TICK IS RUNNING.

    Two waits, and the second one is not redundant. `ES_SM_CTL` names the
    destination scene as soon as a faded transition BEGINS — measured on this
    ROM, it reads `lake` a full 16 frames before `lake::tick` runs for the
    first time, because scene_mgr holds the switch under fade's ramp. A drive
    keyed to that byte alone spends its first presses on a scene that is not
    yet ticking, and they are silently swallowed (observed: the first press of
    a press train vanished, and only that one).

    So the live signal is the scene's own output: ES_WAT_SCROLL advancing is
    `lake::tick` having called `wat_advance`. Frame-counted throughout, never
    wall-clocked (CLAUDE.md rule 2).
    """
    for i in range(budget):
        r.frame_step(1, start=(i < 3))
        if r.read_bytes(W, DP_SM_CTL, 1)[0] == 1:
            break
    else:
        raise AssertionError("never reached the lake scene")
    was = _u16(r, DP_SCROLL)
    for _ in range(budget):
        r.frame_step(1)
        if _u16(r, DP_SCROLL) != was:
            return
    raise AssertionError("the lake scene never started ticking")


def _sample(r):
    d = r.read_bytes(DSP, 0, 128)
    return (tuple((d[v * 0x10 + 4], d[v * 0x10 + 8]) for v in range(8)),
            d[0x3D], _u16(r, DP_STILLED), _u16(r, DP_WAVE), _u16(r, DP_SCROLL))


def _sfx_live(rows, srcn=None):
    """Frames on which an SFX voice is sounding (optionally with one sample)."""
    return [i for i, (v, _, _, _, _) in enumerate(rows)
            if any(e and (srcn is None or s == srcn)
                   for s, e in (v[6], v[7]))]


def _runs(indices):
    out = []
    prev = None
    for i in indices:
        if prev is None or i != prev + 1:
            out.append([i, i])
        else:
            out[-1][1] = i
        prev = i
    return out


@pytest.fixture(scope="module")
def sea():
    """One boot: the lake drifting, then latched still by a B press.

    The two halves share a drive on purpose — the stilled claim is only worth
    anything if the sea was demonstrably alive first, and the same rows prove
    both.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    drift, still = [], []
    try:
        _enter_lake(r)
        for _ in range(DRIFT_FRAMES):
            r.frame_step(1)
            drift.append(_sample(r))
        r.frame_step(1, b=True)             # the latch
        for _ in range(STILL_FRAMES):
            r.frame_step(1)
            still.append(_sample(r))
    finally:
        # The core is a PROCESS-GLOBAL singleton and `frame_step` parks it, so
        # a failure above would strand the NEXT module's runner and make it
        # name itself (tests/conftest.py, the parked-core guard).
        r.stop()
    return drift, still


@pytest.fixture(scope="module")
def toggled():
    """A press train: B held for 24 of every 40 frames, eleven times.

    The long hold is the whole point. A cue read off the HELD state has 60% of
    this drive to sound in; the correct one, read off ES_INP_PRESS, has eleven
    instants. LEAD idle frames come first so the first press lands on a scene
    that has been ticking for a while, not on the frame the drive starts.
    """
    r = MesenRunner(enable_audio=True)
    r.boot_rom(_rom(), frames=300)
    rows = []
    try:
        _enter_lake(r)
        before = _u16(r, DP_STILLED)
        for i in range(LEAD + PRESSES * PERIOD):
            held = i >= LEAD and (i - LEAD) % PERIOD < HOLD
            r.frame_step(1, b=held)
            rows.append(_sample(r))
    finally:
        r.stop()
    return rows, before


# ---------------------------------------------------------------------------
# the drifting sea
# ---------------------------------------------------------------------------
def test_the_drive_actually_drifted(sea):
    """Non-vacuity, and it is the game state rather than a cue.

    The surface moves LK_WATER_SPEED px per published tick and NTSC publishes
    that to the pixel, so a clean drive advances ES_WAT_SCROLL by exactly one
    per frame and never latches still. A drive that stopped drifting — a
    changed control, a boot that never reached the scene, a tick that stopped
    being called — fails HERE, naming the water, instead of failing the cue
    cases below and reading as a defect in the sound.
    """
    drift, _ = sea
    moved = drift[-1][4] - drift[0][4]
    assert moved == (len(drift) - 1) * SPEED, (
        f"the surface drifted {moved} px across {len(drift)} frames, not the "
        f"{(len(drift) - 1) * SPEED} a clean NTSC drive gives — the cue cases "
        f"below would be measuring a lake that is not running")
    assert {s for _, _, s, _, _ in drift} == {0}, (
        "the surface latched still during the drifting half of the drive")


def test_the_song_plays_for_the_whole_drive(sea):
    """Not merely audible once — CONTINUOUS.

    A song that keys on at load and then runs out of data would look alive on
    frame 1 and leave the rest silent. `shallow_water_song`'s bass and kit play
    all sixteen bars, so "some music voice is sounding" is true nearly always;
    the bar sits well below what a working song reads (measured 0.98) so a
    tempo or arrangement change cannot flip it.
    """
    drift, _ = sea
    live = sum(1 for v, _, _, _, _ in drift
               if any(v[k][1] for k in MUSIC_VOICES))
    frac = live / len(drift)
    assert frac > 0.90, (
        f"a music voice is sounding on only {frac:.0%} of {len(drift)} frames "
        f"— the song is not running continuously; check that sf_audio_tick is "
        f"pumped every frame and that Tad_LoadSong ran")


def test_only_the_sea_is_on_the_channels_an_effect_ducks(sea):
    """The honest form of "nothing is scored on G or H" for a rail with cues.

    TAD's channels G and H map onto DSP voices 6 and 7, and the driver ducks
    them for the duration of any sound effect — so a part written there
    vanishes every time the game makes a noise. On the music-only rails that is
    an equality (`tests/test_screen_effect_audio.py`): those rails queue
    nothing, so any sounding at all is a song part. This rail queues, so the
    claim has to be about WHAT is keyed rather than whether anything is.

    This drive takes NO INPUT, so `select` cannot fire and the only cue that
    can is the wave. Two readings therefore hold together:

      * the set of samples ever keyed on 6/7 is exactly {saw} — a song part
        would key one of the song's own five instruments there;
      * the voices go quiet between waves — a song part would hold them live
        through the lull, and the shore's lull is most of the drive.
    """
    drift, _ = sea
    keyed = {s for v, _, _, _, _ in drift for s, e in (v[6], v[7]) if e}
    assert keyed == {SAW}, (
        f"samples {sorted(keyed)} are keyed on voices 6/7 across a drive whose "
        f"only possible cue is `wave_break` (saw = {SAW}) — anything else "
        f"there is a song part scored on G or H, where an effect erases it")
    frac = len(_sfx_live(drift)) / len(drift)
    assert frac < 0.55, (
        f"voices 6/7 are live on {frac:.0%} of {len(drift)} frames — the "
        f"shore has no lull, so something is holding those voices between "
        f"waves")


def test_no_music_voice_takes_the_noise_generator(sea):
    """There is ONE noise generator, and this rail reaches for it every 2 s.

    The driver zeroes the volume of any music channel sharing it the moment an
    effect wants it (`audio-driver.asm`, the `SfxNoise` branch). A noise hi-hat
    in `shallow_water_song` would therefore drop out on the wave's cadence —
    the worst version of the bug, because it would sound deliberate. The kit is
    samples, and this reads that off NON rather than off the MML.
    """
    drift, still = sea
    bad = [(half, i, non)
           for half, rows in (("drift", drift), ("still", still))
           for i, (_, non, _, _, _) in enumerate(rows) if non & MUSIC_MASK]
    assert not bad, (
        f"a music voice is in the noise mask on {len(bad)} frames (first "
        f"{bad[0]}) — that voice is silenced whenever an effect plays noise")


def test_the_waves_come_on_the_surf_s_own_cadence(sea):
    """Not once, not every frame — every LK_SURF_PERIOD_PX of drift.

    `wat_nmi_surf` picks the swash phase out of ES_WAT_SCROLL, so the wave the
    player watches restarts every SURF_PERIOD_PX px. `lk_wave_cue` counts the
    same pixels from the same zero, so the break should be heard on the frame
    that cycle turns over — which on NTSC, where TS_STEP publishes SPEED to the
    pixel, is every CYCLE_FRAMES frames. Both numbers are READ (from the
    generated art include and the rail's tuning include) rather than written
    here, so re-authoring the surf moves the picture and this expectation
    together.

    The tolerance is the width of one queue delay: `sf_audio_tick` hands the
    driver at most one request per frame, so a break landing on the same frame
    as a `select` is delivered one frame late. Measured on this tree the gaps
    are 127, 129, 128 against a 128 expectation.
    """
    drift, _ = sea
    starts = [a for a, _ in _runs(_sfx_live(drift, SAW))]
    assert len(starts) >= 4, (
        f"only {len(starts)} wave(s) broke in {len(drift)} frames, against the "
        f"{len(drift) // CYCLE_FRAMES} a {CYCLE_FRAMES}-frame cadence gives — "
        f"the cue is firing once, or not at all")
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert all(abs(g - CYCLE_FRAMES) <= 4 for g in gaps), (
        f"the breaks came {gaps} frames apart, not {CYCLE_FRAMES} +/- 4 — the "
        f"wave cue is not counting the surf's own cycle")


def test_the_cue_clock_is_the_picture_s_own_position(sea):
    """The invariant the whole design rests on, checked every frame.

    `US_WAVE` and `ES_WAT_SCROLL` are advanced by the SAME published step in
    the SAME branch from the SAME zero, so `US_WAVE == ES_WAT_SCROLL mod
    SURF_PERIOD_PX` is not an approximation — it is exact on every frame of the
    drive, and it is what makes "the sound and the surface cannot disagree" a
    measurement rather than a claim. A free-running cue clock passes every
    other case in this module and fails this one.

    This reads game state, not the chip, and it is deliberately not the only
    evidence for the cadence — `test_the_waves_come_on_the_surf_s_own_cadence`
    is that, on the DSP. This one says WHY that cadence is the picture's.
    """
    drift, _ = sea
    bad = [(i, w, sc) for i, (_, _, _, w, sc) in enumerate(drift)
           if w != sc % SURF_PERIOD_PX]
    assert not bad, (
        f"US_WAVE and ES_WAT_SCROLL disagree on {len(bad)} of {len(drift)} "
        f"frames (first: frame {bad[0][0]}, wave={bad[0][1]}, "
        f"scroll={bad[0][2]}) — the wave cue is running off a clock of its "
        f"own, so the sound can break while the picture does not")


# ---------------------------------------------------------------------------
# the stilled sea — the case with a bar of zero
# ---------------------------------------------------------------------------
def test_the_press_latched_the_surface(sea):
    """The game-state half of the stilled claim, and it comes first.

    One B press on the rising edge flips US_STILLED and it STAYS flipped —
    that is what makes stillness a state rather than a condition, and it is
    what lets the silence case below be an equality over a long window instead
    of a fraction. A drive whose press did not land fails here, naming the
    gate, rather than passing the silence case vacuously.
    """
    drift, still = sea
    assert {s for _, _, s, _, _ in drift} == {0}, "the drive began stilled"
    assert {s for _, _, s, _, _ in still} == {1}, (
        f"US_STILLED reads {sorted({s for _, _, s, _, _ in still})} across the "
        f"{len(still)} frames after the B press, not a latched 1 — the press "
        f"did not land or the latch does not hold")
    held = still[-1][4] - still[0][4]
    assert held == 0, (
        f"the surface drifted {held} px while latched still — the gate is not "
        f"stopping wat_advance, so the silence case below would be measuring "
        f"a moving lake")


def test_a_stilled_lake_never_breaks(sea):
    """THE MODULE'S BEST CASE, and it is a bar of zero.

    `lk_wave_cue` sits inside the same `US_STILLED` branch that gates
    `wat_advance`, so a frozen surface cannot queue a break. The asserted
    window is STILL_FRAMES - STILL_SETTLE = 256 frames against a 128-frame
    cadence, so a lake still counting would break twice inside it — the plant
    is not subtle and neither is the reading.

    The first STILL_SETTLE frames are skipped and that is the design rather
    than slack: a wave already breaking when the player latches the surface
    plays out, because the sea does not stop mid-break. STILL_SETTLE is longer
    than one whole effect, so what is asserted after it is silence that the
    gate produced.
    """
    _, still = sea
    tail = still[STILL_SETTLE:]
    live = _sfx_live(tail, SAW)
    assert not live, (
        f"the wave voice sounds on {len(live)} of {len(tail)} frames (first at "
        f"+{live[0] + STILL_SETTLE}) with the surface LATCHED STILL — the cue "
        f"is not gated on US_STILLED, so the shore crashes over a frozen lake")
    noisy = [i for i, (_, non, _, _, _) in enumerate(tail) if non]
    assert not noisy, (
        f"the noise generator is taken on {len(noisy)} of {len(tail)} stilled "
        f"frames (first at +{noisy[0] + STILL_SETTLE}, NON="
        f"{tail[noisy[0]][1]:#04x}) — nothing on a frozen lake should be "
        f"reaching for it. Read the NON bits before the gate: 0x40/0x80 is an "
        f"effect on voice 6/7 and means the cue slipped past US_STILLED; "
        f"anything in 0x3F is a MUSIC channel and the defect is in the song's "
        f"kit, not in this rail")


# ---------------------------------------------------------------------------
# the toggle cue
# ---------------------------------------------------------------------------
def test_the_toggle_actually_toggled(toggled):
    """The drive's own check: the state moved, once per press and no more.

    ES_INP_PRESS is `cur & ~prev`, so eleven presses are eleven flips however
    long B is held for each — and an odd count leaves the surface latched. A
    site reading ES_INP_CUR instead would flip once per HELD FRAME, so this
    case reds on the same plant the cue case below does, from the game state
    rather than from the chip. Two readings of one defect.
    """
    rows, before = toggled
    st = [before] + [s for _, _, s, _, _ in rows]
    flips = [i for i in range(1, len(st)) if st[i] != st[i - 1]]
    assert len(flips) == PRESSES, (
        f"US_STILLED flipped {len(flips)} times across {PRESSES} presses "
        f"(at {flips[:14]}) — a flip per HELD frame is the ES_INP_CUR defect; "
        f"fewer is a press train that did not land")
    assert st[-1] == 1, "an odd number of presses must leave the surface still"


def test_the_toggle_is_audible(toggled):
    """`select` is voiced by pluck (assets/audio/sound-effects.txt)."""
    rows, _ = toggled
    assert _sfx_live(rows, PLUCK), (
        "no pluck voice ever sounded on an SFX channel — the B toggle has no "
        "cue reaching the chip")


def test_the_toggle_cue_is_the_press_and_not_the_hold(toggled):
    """B is DOWN for 60% of this drive and the cue must not be.

    `select` is queued on the arm reached by ES_INP_PRESS's B bit — the rising
    edge the `input` feature publishes — so it runs once per press however long
    B is held. Reading ES_INP_CUR instead is one token away and is the mistake
    the site invites: planted that way the pluck sounds through every held
    frame, and `test_the_toggle_actually_toggled` reds too because the latch
    then flips once a frame. The bar sits far below a held cue and far above
    what eleven short pluck hits cost (measured 0.09 against a 0.60 hold).
    """
    rows, _ = toggled
    frac = len(_sfx_live(rows, PLUCK)) / len(rows)
    assert frac < 0.30, (
        f"the pluck voice is live on {frac:.0%} of frames, against a drive "
        f"holding B for {HOLD}/{PERIOD} of each cycle — the toggle cue is "
        f"reading the HELD state (ES_INP_CUR) rather than the press edge "
        f"(ES_INP_PRESS)")
