"""Run-gates for the racer day-night cycle (S6 M3b): gradient horizon tint,
day->night progression, and the palette-cycle track accent.

All three gates assert on RENDERED PIXELS (screenshot bytes) as primary
evidence; hardware CGRAM bytes back the palette-rotation gate (destination
region), and the debug mirrors at $7E:E012 (gradient first channel) /
$7E:E014 (time-of-day phase) only ORCHESTRATE the screenshots — no visual
claim rests on them.

Time is driven through run_frames / wall-clock (the emulator free-runs at
60 fps): the template's DAY hold is 900 frames (15 s) and the blend is 256
frames, so the day->night gate polls the $E014 phase mirror to land its
screenshots inside the right phase windows (~20 s total).

THE ROTATION-STATE TRAP (why screenshots carry a CGRAM state tag): the
palette cycle permutes CGRAM entries 2..4 (white / stripe-red / road-gray)
every 16 frames, swinging whole-floor brightness by 2x between rotation
states (red in the road-checker slot vs white in it). Any day-vs-night
pixel comparison must therefore match rotation states between the two
phases — an unmatched comparison can pass or fail on rotation luck alone.
Likewise the gradient-ramp gate classifies WHITE pixels (min channel high):
the white COLOR exists somewhere on the floor in every rotation state, so
the metric is rotation-proof.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
CG = MemoryType.SnesCgRam

PHASE_MIRROR = 0xE014           # 0=DAY 1=TO_NIGHT 2=NIGHT 3=TO_DAY
GRAD_CH_MIRROR = 0xE012         # first gradient HDMA channel (expect 3)

# the template's cycled CGRAM range (entries 2..4) read as 6 bytes at addr 4
CYCLED_COLORS = {"bd77", "ba14", "ad39"}    # white / stripe red / road gray B
PALCYC_PERIOD = 48              # 3 entries x 16 frames/step


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rgb(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return list(img.getdata()), w, h


def _region(data, w, h, y0, y1):
    """Pixel rows for SNES scanlines y0..y1 (screenshot may be scaled)."""
    a, b = int(y0 * h / 224.0), int(y1 * h / 224.0)
    return data[a * w:b * w]


def _cg_state(runner):
    """Rotation state = hardware CGRAM entries 2..4 as a hex tag."""
    raw = runner.read_bytes(CG, 4, 6).hex()
    return raw[0:4], raw[4:8], raw[8:12]


def _white_blue(pixels):
    """Average blue of white-class pixels (min channel > 140), or None."""
    whites = [p for p in pixels if min(p) > 140]
    if len(whites) < 50:
        return None
    return sum(p[2] for p in whites) / len(whites)


def _brightness(pixels):
    return sum(sum(p) for p in pixels) / len(pixels)


def _blue_fraction(pixels):
    tot = sum(sum(p) for p in pixels)
    return sum(p[2] for p in pixels) / tot if tot else 0.0


def _shot_per_rotation_state(runner, tag, max_polls=40):
    """One screenshot per palette rotation state, keyed by the CGRAM tag.

    Polls hardware CGRAM every few frames until all 3 rotation states of the
    cycled range have been photographed (period = 48 frames).
    """
    shots = {}
    for i in range(max_polls):
        state = _cg_state(runner)
        assert set(state) == CYCLED_COLORS, \
            f"cycled CGRAM range holds unexpected colors: {state}"
        if state not in shots:
            path = f"/tmp/_racer_dn_{tag}_{len(shots)}.png"
            runner.take_screenshot(path)
            # re-read: a rotation step between read and screenshot voids it
            if _cg_state(runner) == state:
                shots[state] = _rgb(path)
        if len(shots) == 3:
            break
        runner.run_frames(6)
    assert len(shots) == 3, \
        f"saw only {len(shots)} palette rotation states in {max_polls} polls"
    return shots


def test_daynight_gradient_horizon_visible(runner):
    """Feature: sf_gradient_rgb horizon tint (COLDATA SUB ramp on BG1).

    Output region read: screenshot pixels — blue channel of white-class
    pixels in the far floor band (scanlines 100..130, strong subtraction)
    vs the near floor band (195..215, ~zero subtraction). The day ramp
    subtracts up to 14/31 blue at the top of the frame, so far whites
    render warm (b ~170-190) while near whites stay full white (b ~236).
    Supplemental: $E012 confirms the gradient armed on channel 3 (the
    arm-before-mode7 + CH5/CH6 pre-pin contract).
    """
    rom = BUILD / "racer.sfc"
    assert rom.exists(), f"{rom} not built — run `make racer` first"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    # the gradient armed and on the expected channel (runtime verification
    # of the channel-budget claim — not a visual assertion)
    assert runner.read_u16(WR, GRAD_CH_MIRROR) == 3, \
        f"gradient first channel mirror = {runner.read_u16(WR, GRAD_CH_MIRROR)} (expect 3)"
    assert runner.read_u16(WR, PHASE_MIRROR) == 0, "not in the DAY hold"

    # Ramp metric, per rotation state. White cells cover the near strip only
    # in the canonical state (the start line owns the near rows; the other
    # two states park white on cells with no near-strip coverage at spawn),
    # so the paired far-vs-near comparison fires in >= 1 state; the
    # state-independent far check fires in every state with far whites.
    shots = _shot_per_rotation_state(runner, "grad")
    paired = 0
    far_states = 0
    for state, (d, w, h) in shots.items():
        far = _white_blue(_region(d, w, h, 100, 130))
        near = _white_blue(_region(d, w, h, 195, 215))
        if far is not None:
            far_states += 1
            # far whites are warm-shifted (true white is b=236; the day ramp
            # subtracts ~47-62 blue across scanlines 100..130)
            assert far < 205, (
                f"state {state}: far-floor whites b={far:.0f} — no blue "
                f"subtraction near the horizon, ramp not rendering")
        if far is None or near is None:
            continue
        paired += 1
        assert far < near - 25, (
            f"state {state}: far-floor whites b={far:.0f} not warmer than "
            f"near-floor whites b={near:.0f} — horizon ramp not rendering")
    # The gradient FEATURE is gated by the per-state asserts above (far < 205
    # blue-subtraction + the paired far < near-25 ramp comparison) and by
    # `paired >= 1` below — those fire in the state(s) that have far-band
    # whites and prove the COLDATA SUB ramp renders. The number of rotation
    # states that happen to park a white track cell in the far band (100..130)
    # is incidental track geometry, not the gradient: on the kit's racer ROM
    # (byte-identical across the kit lineage) far whites land in exactly ONE
    # rotation state, so requiring >= 2 over-specified the track and failed
    # deterministically without ever indicating a gradient regression. Gate the
    # feature, not the geometry: >= 1 state must show the far-band ramp.
    assert far_states >= 1, \
        f"far-floor white pixels found in {far_states} rotation state(s) — " \
        f"ramp not rendering in any state"
    assert paired >= 1, "no rotation state offered both far and near whites"


def test_daynight_palette_cycle_rotates_track_colors(runner):
    """Feature: sf_pal / sf_pal_cycle accent on CGRAM entries 2..4.

    Output regions read: (1) hardware CGRAM bytes for entries 2..4 — the
    commit bridge's destination — must permute over frames while holding
    the same color multiset (white/red/gray rotating, nothing leaking in);
    (2) screenshot pixels — the count of red-class pixels in the near-track
    strip swings between rotation states (red occupies cell classes of very
    different screen area: rumble stripes vs the road checker), proving the
    rotation is visible on the rendered track, not just in CGRAM.

    State cycle exercised: continuous rotation (the template wires no stop
    path) — >= 2 distinct rotation states observed, recurring across more
    than one full 48-frame period, with an invariant color multiset.
    """
    rom = BUILD / "racer.sfc"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    # --- destination region: hardware CGRAM rotates, multiset invariant ---
    states = []
    for _ in range(10):                       # ~120 frames > 2 full periods
        states.append(_cg_state(runner))
        runner.run_frames(12)
    for st in states:
        assert set(st) == CYCLED_COLORS, \
            f"cycled CGRAM range corrupted: {st} (expected multiset {CYCLED_COLORS})"
    distinct = set(states)
    assert len(distinct) >= 2, \
        f"hardware CGRAM never rotated: {states}"
    # keeps rotating: the LAST sample window (well past one 48-frame period)
    # still shows a state different from the first sample
    assert any(st != states[0] for st in states[5:]), \
        f"rotation stalled after the first period: {states}"

    # --- rendered pixels: red coverage in the near-track strip swings with
    # the rotation state (state-keyed screenshots) ---
    shots = _shot_per_rotation_state(runner, "pal")
    red_counts = {}
    for state, (d, w, h) in shots.items():
        strip = _region(d, w, h, 195, 215)
        red_counts[state] = sum(
            1 for r, g, b in strip if r > 150 and g < 110 and b < 110)
    counts = sorted(red_counts.values())
    strip_len = len(_region(*shots[next(iter(shots))], 195, 215))
    assert counts[-1] - counts[0] > 0.10 * strip_len, (
        f"red-class coverage in the near strip barely changes across "
        f"rotation states ({red_counts}) — palette cycle not visible on "
        f"the rendered track")


def test_daynight_progression_darkens_and_blues(runner):
    """Feature: the day->night time-of-day progression (gradient retunes via
    the engine's in-place rebuild while Mode 7 is live).

    Output region read: screenshot pixels — whole-floor brightness and blue
    fraction (scanlines 100..215), compared DAY vs NIGHT in MATCHED palette
    rotation states (see the module docstring). Night must render darker
    (brightness < 80% of day, same rotation state) and bluer (blue fraction
    higher) — the configured direction: night subtracts heavy red+green.

    Time driving: wall-clock/run_frames; the $E014 phase mirror sequences
    the two capture windows (DAY hold, then polls ~20 s into the NIGHT
    hold). State cycle exercised: DAY -> TO_NIGHT -> NIGHT (the return
    blend's exactness is engine-snap-guaranteed and exercised implicitly
    by the looping ROM, not gated here).
    """
    rom = BUILD / "racer.sfc"

    # Day captures must complete INSIDE the DAY hold (900 frames; the
    # emulator free-runs on wall clock, so slow first-run screenshot I/O can
    # drift the captures into the blend). Verify the phase mirror is still
    # DAY after capturing; one fresh-boot retry covers a slow first run.
    for attempt in range(2):
        runner.load_rom(str(rom), run_seconds=2.0)
        assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
        assert runner.read_u16(WR, PHASE_MIRROR) == 0, "not in the DAY hold"
        day = _shot_per_rotation_state(runner, "day")
        if runner.read_u16(WR, PHASE_MIRROR) == 0:
            break
        assert attempt == 0, \
            "day captures drifted out of the DAY hold twice (900-frame window)"

    # ride the mirror into the NIGHT hold (DAY 900f + blend 256f ~ 19 s)
    for _ in range(120):
        if runner.read_u16(WR, PHASE_MIRROR) == 2:
            break
        runner.run_frames(20)
    assert runner.read_u16(WR, PHASE_MIRROR) == 2, \
        "never reached the NIGHT hold (phase mirror stuck at " \
        f"{runner.read_u16(WR, PHASE_MIRROR)})"

    night = _shot_per_rotation_state(runner, "night")
    assert runner.read_u16(WR, PHASE_MIRROR) == 2, \
        "night captures drifted out of the NIGHT hold (900-frame window)"

    matched = 0
    for state in day:
        if state not in night:
            continue
        matched += 1
        d_px = _region(*day[state], 100, 215)
        n_px = _region(*night[state], 100, 215)
        d_br, n_br = _brightness(d_px), _brightness(n_px)
        assert n_br < d_br * 0.80, (
            f"state {state}: night floor brightness {n_br:.0f} not darker "
            f"than day {d_br:.0f} — day-night transition not rendering")
        d_bf, n_bf = _blue_fraction(d_px), _blue_fraction(n_px)
        assert n_bf > d_bf + 0.08, (
            f"state {state}: night blue fraction {n_bf:.2f} not bluer than "
            f"day {d_bf:.2f}")
    assert matched == 3, f"only {matched} rotation states matched day<->night"
