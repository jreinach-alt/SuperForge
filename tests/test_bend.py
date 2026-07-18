"""Run-gate for sf_bend / sf_tunnel: a per-scanline BGnHOFS curve distortion
bends a flat vertical-stripe BG, and the animated sine tunnel ROLLS (the
per-scanline displacement pattern advances between frames).

Primary assertions read RENDERED PIXELS from a screenshot (the HDMA table in
WRAM is implementation detail, not evidence — a byte-perfect table can render
nothing; kit rule #2). A flat BG would show every stripe at the same x on
every row; the bend must MEASURABLY displace a stripe's x per scanline, and
the animation must advance that pattern frame-to-frame.

ROM contract (tests/bend_test.asm):
  BG1 vertical stripes, 64px period. sf_tunnel SF_CURVE_SINE, amp 14, speed 2
  on BG1 — every scanline offset = sine[(scanline+phase)&$FF]*amp/128, phase
  rolled every frame by sf_bend_tick.
  $7E:E010 = frame heartbeat, $7E:E012 = allocated HDMA channel.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

STRIPE_PERIOD = 64               # px — per-scanline shifts unambiguous mod 64


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
    """Stripe pattern of a row: 1 = green stripe pixel, 0 = background."""
    return [1 if img.getpixel((x, y))[1] > 120 else 0 for x in range(256)]


def _lit_range(img):
    """First/last screenshot rows where the stripe BG is visible."""
    h = img.size[1]
    lit = [y for y in range(h) if sum(_row_bits(img, y)) > 20]
    assert lit, "no stripe BG visible at all"
    return lit[0], lit[-1]


def _first_edge(img, y):
    """x of the first background→stripe transition on row y (the leftmost
    stripe edge). Tracks the per-scanline horizontal displacement of the BG."""
    bits = _row_bits(img, y)
    for x in range(1, 256):
        if bits[x] == 1 and bits[x - 1] == 0:
            return x
    return -1


def _row_shift(img_a, img_b, y):
    """Best horizontal shift (0..63) aligning row y of b onto a, and its
    mismatch count: b[x] == a[(x+s) % 256]."""
    a, b = _row_bits(img_a, y), _row_bits(img_b, y)
    best = None
    for s in range(STRIPE_PERIOD):
        m = sum(1 for x in range(256) if b[x] != a[(x + s) % 256])
        if best is None or m < best[1]:
            best = (s, m)
    return best


def test_bend_displaces_per_scanline_and_rolls(runner):
    rom = BUILD / "bend_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)

    # --- secondary: boot magic + a real HDMA channel + live heartbeat ---
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"sf_tunnel failed to allocate: {chan:#x}"
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    img_a = _shot(runner, "bend_a.png")
    y_top, y_bot = _lit_range(img_a)
    assert y_bot - y_top > 120, f"stripe band too small: {y_top}..{y_bot}"

    # --- PRIMARY (a): a stripe's x-position VARIES per scanline ----------
    # A flat BG shows the leftmost stripe edge at the SAME x on every row
    # (span 0). The sine bend must displace it by a per-scanline amount, so
    # the edge x sweeps a measurable range down the frame.
    edges = [_first_edge(img_a, y) for y in range(y_top + 4, y_bot - 3)]
    edges = [e for e in edges if e >= 0]
    assert len(edges) > 100, "could not track the stripe edge down the frame"
    span = max(edges) - min(edges)
    assert span >= 12, \
        f"BG not bent: stripe edge x varies only {span}px per scanline (flat)"

    # the variation is curved, not a single jump: the edge takes several
    # distinct x values through the range (a flat-with-one-step BG would not)
    assert len(set(edges)) >= 8, \
        f"stripe edge takes only {len(set(edges))} x values — not a smooth curve"

    # --- PRIMARY (b): the tunnel ROLLS (pattern advances between frames) --
    # With sf_bend_tick rolling the phase, two screenshots N frames apart must
    # differ, and the per-scanline stripe pattern must shift cleanly (a clean
    # nonzero shift on most sampled rows — the displacement curve moved).
    runner.run_frames(8)
    img_b = _shot(runner, "bend_b.png")
    assert img_a.tobytes() != img_b.tobytes(), \
        "frames identical 8 apart — the tunnel is not rolling"

    rows = list(range(y_top + 12, y_bot - 12, max(1, (y_bot - y_top) // 8)))
    clean_moved = 0
    for y in rows:
        s, m = _row_shift(img_a, img_b, y)
        if m <= 6 and s != 0:
            clean_moved += 1
    assert clean_moved >= len(rows) // 2, \
        f"roll not visible: only {clean_moved}/{len(rows)} rows shifted cleanly"


def test_bend_curve_bows_both_ways(runner):
    """Secondary corroboration that the displacement is a genuine CURVE, read
    from rendered pixels: the sine bend's per-scanline stripe-edge x excurses
    to BOTH sides of its mid-x (a one-directional ramp or a single step would
    sit on one side). A sine bows the BG left then right down the frame, so
    the edge x must land both well above and well below its midpoint. (A
    static-parabola symmetry assertion would need a parabola-armed ROM — the
    shipped demo arms the marquee sine per the DoD; this is the curve-shape
    corroboration on the rendered output, not the primary done-condition.)"""
    rom = BUILD / "bend_test.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    img = _shot(runner, "bend_shape.png")
    y_top, y_bot = _lit_range(img)
    edges = [_first_edge(img, y) for y in range(y_top + 4, y_bot - 3)]
    xs = [e for e in edges if e >= 0]
    mid = (min(xs) + max(xs)) / 2
    above = sum(1 for e in xs if e > mid + 2)
    below = sum(1 for e in xs if e < mid - 2)
    assert above >= 8 and below >= 8, \
        f"bend does not curve both ways about mid-x: above={above} below={below}"
