"""Run-gate for E-HSCROLL (bend/tunnel v1.1): a base horizontal scroll composes
UNDER the per-scanline bend, so `scroll #layer, CAM_X, 0` pans the bent layer.

The engine refill now builds offset[line] = base_scroll + scaled_curve[idx],
reading base_scroll from the layer's SHADOW_BGnHOFS. The ROM
(tests/bend_hscroll_test.asm) arms a STATIC sine bend (speed 0, so the ONLY
frame-to-frame motion is the base scroll) and pans CAM_X right then left.

We read RENDERED PIXELS (kit rule #2):
  1. As the base scroll moves one way, the whole stripe pattern shifts one
     direction across frames; when the pan reverses, the shift reverses.
  2. The per-scanline sine SHAPE persists through the pan (the layer stays bent
     while panning — the stripe edge x still varies per scanline every frame).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

STRIPE_PERIOD = 64


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _shot(runner, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    runner.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


def _row_bits(img, y):
    return [1 if img.getpixel((x, y))[1] > 120 else 0 for x in range(256)]


def _lit_range(img):
    h = img.size[1]
    lit = [y for y in range(h) if sum(_row_bits(img, y)) > 20]
    assert lit, "no stripe BG visible at all"
    return lit[0], lit[-1]


def _first_edge(img, y):
    bits = _row_bits(img, y)
    for x in range(1, 256):
        if bits[x] == 1 and bits[x - 1] == 0:
            return x
    return -1


def _signed_shift(img_a, img_b, y):
    """Signed best shift in (-32..31] aligning row y of b onto a:
    b[x] == a[(x - s) % 256] for shift s (positive s = pattern moved right)."""
    a, b = _row_bits(img_a, y), _row_bits(img_b, y)
    best = None
    for s in range(-STRIPE_PERIOD // 2, STRIPE_PERIOD // 2):
        m = sum(1 for x in range(256) if b[x] != a[(x - s) % 256])
        if best is None or m < best[1]:
            best = (s, m)
    return best


def _edge_span(img):
    """How much the stripe edge x varies per scanline (the bend shape)."""
    y_top, y_bot = _lit_range(img)
    edges = [_first_edge(img, y) for y in range(y_top + 4, y_bot - 3)]
    edges = [e for e in edges if e >= 0]
    return (max(edges) - min(edges)) if len(edges) > 50 else 0


def _mid_band_shift(img_a, img_b):
    """Median signed shift over a clean middle band (robust to the bend)."""
    y_top, y_bot = _lit_range(img_a)
    rows = range(y_top + 16, y_bot - 16, 4)
    shifts = []
    for y in rows:
        s, m = _signed_shift(img_a, img_b, y)
        if m <= 8:
            shifts.append(s)
    assert shifts, "no clean rows to measure the pan shift"
    shifts.sort()
    return shifts[len(shifts) // 2]


PAN_WINDOW = 4                   # frames between the two captures (small shift)
# ROM constants (bend_hscroll_test.asm): pan speed and turn period.
CAM_STEP = 2
CAM_TURN = 40


def _capture_pan_shift(runner, want_increasing, tag):
    """Step frame-by-frame to a CLEAN monotonic PAN_WINDOW (CAM_X moves exactly
    PAN_WINDOW*CAM_STEP in the wanted direction — i.e. no turn inside), capture
    the two frames, and return (signed pixel shift, span0, span1). Retries until
    it finds a window whose measured pixel shift is non-degenerate (the median
    can round to 0 on a marginal window); robust to where the cycle starts."""
    expect_delta = PAN_WINDOW * CAM_STEP
    for _ in range(220):
        c0 = runner.read_u16(WR, 0xE014)
        runner.run_frames(1)
        c1 = runner.read_u16(WR, 0xE014)
        if want_increasing and c1 <= c0:
            continue
        if (not want_increasing) and c1 >= c0:
            continue
        # we are moving the right way; is there room for a full clean window
        # before the turn? (turn limit is CAM_STEP*CAM_TURN)
        cam0 = c1
        img0 = _shot(runner, f"bend_hscroll_{tag}0.png")
        runner.run_frames(PAN_WINDOW)
        cam1 = runner.read_u16(WR, 0xE014)
        delta = cam1 - cam0
        # require a clean, fully-monotonic window of the expected size (no turn)
        if abs(delta) != expect_delta:
            continue
        if (delta > 0) != want_increasing:
            continue
        img1 = _shot(runner, f"bend_hscroll_{tag}1.png")
        shift = _mid_band_shift(img0, img1)
        if shift == 0:
            continue                                   # degenerate — keep looking
        return shift, _edge_span(img0), _edge_span(img1)
    raise AssertionError(f"could not find a clean {tag} pan window")


def test_bend_pans_both_ways_and_stays_bent(runner):
    rom = BUILD / "bend_hscroll_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.2)

    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"sf_bend failed to allocate: {chan:#x}"

    # --- RIGHT-PAN window (CAM_X increasing) --------------------------------
    shift_right, span_r0, span_r1 = _capture_pan_shift(runner, True, "r")
    assert 0 < abs(shift_right) < 24, \
        f"right-pan shift implausible (aliasing?): {shift_right}"
    assert span_r0 >= 10 and span_r1 >= 10, \
        "the layer is not bent during the right pan (sine shape lost)"

    # --- LEFT-PAN window (CAM_X decreasing) ---------------------------------
    shift_left, span_l0, span_l1 = _capture_pan_shift(runner, False, "l")
    assert 0 < abs(shift_left) < 24, \
        f"left-pan shift implausible (aliasing?): {shift_left}"
    assert span_l0 >= 10 and span_l1 >= 10, \
        "the layer is not bent during the left pan (sine shape lost)"

    # --- the decisive assertion: pan DIRECTION flips with the scroll --------
    assert (shift_right > 0) != (shift_left > 0), (
        f"pan did not reverse: right-shift={shift_right}, left-shift={shift_left} "
        "(same sign — base scroll is not composing into the bend correctly)"
    )
