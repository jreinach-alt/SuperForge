"""Run-gate for the STATIC sf_bend / SF_CURVE_PARABOLA arm — the curved-horizon
half of D-CURVE that the shipped suite (test_bend.py, sine tunnel) did not
exercise (audit-1 Deviation #1, MED).

Primary assertions read RENDERED PIXELS from a screenshot (the HDMA table in
WRAM is implementation detail, not evidence — a byte-perfect table can render
nothing; kit rule #2). The parabola LUT is symmetric about the curve centre
scanline (0 displacement at the centre, +peak at the top & bottom edges), so a
vertical stripe's leftmost edge x is displaced LEAST at the centre and MOST
(same direction) toward the edges: the curved-horizon bow. Two properties prove
it on pixels:

  * SYMMETRY — the per-scanline edge-x is symmetric about the curve's extremum
    row (edge-x at centre-d ≈ edge-x at centre+d). This is the curved-horizon
    signature; a ramp or a single step would not mirror.
  * STATIC — two screenshots N frames apart are pixel-identical (no roll) WHILE
    the frame heartbeat keeps advancing. This distinguishes the static sf_bend
    from the animated sf_tunnel (test_bend.py), whose pattern rolls every frame.

ROM contract (tests/bend_parabola_test.asm):
  BG1 vertical stripes, 64px period. sf_bend SF_CURVE_PARABOLA, amp 14 on BG1 —
  every scanline offset = parabola[scanline & $FF] * amp / 128, NO roll. The
  loop calls sf_bend_tick at speed 0 (identical rebuild) so the pixels MUST hold
  while $7E:E010 (heartbeat) advances. $7E:E012 = allocated HDMA channel.
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


def _edges(img):
    """{row: leftmost-stripe-edge-x} over the lit band (interior rows only)."""
    y_top, y_bot = _lit_range(img)
    out = {}
    for y in range(y_top + 4, y_bot - 3):
        e = _first_edge(img, y)
        if e >= 0:
            out[y] = e
    return out


def test_bend_parabola_is_symmetric_curved_horizon(runner):
    rom = BUILD / "bend_parabola_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)

    # --- secondary: boot magic + a real HDMA channel + live heartbeat ---
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"sf_bend failed to allocate: {chan:#x}"
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    img = _shot(runner, "parabola_a.png")
    edges = _edges(img)
    ys = sorted(edges)
    assert len(ys) > 100, "could not track the stripe edge down the frame"

    # --- PRIMARY (a): the BG visibly BENDS (not flat) ---------------------
    # A flat BG shows the leftmost stripe edge at the same x on every row
    # (span 0). The parabola bows it, so the edge x sweeps a measurable range.
    span = max(edges.values()) - min(edges.values())
    assert span >= 6, \
        f"BG not bent: stripe edge x varies only {span}px per scanline (flat)"
    assert len(set(edges.values())) >= 5, \
        f"stripe edge takes only {len(set(edges.values()))} x values — not a curve"

    # --- PRIMARY (b): SYMMETRY about the curve extremum (curved horizon) ---
    # The parabola is flat (quadratic) near its vertex, so several centre rows
    # round to the same extreme edge-x: the vertex is a short PLATEAU. Take its
    # centroid as the symmetry axis, then assert the per-scanline edge-x mirrors
    # about it (edge[centre-d] == edge[centre+d]) for every row that has a
    # partner on both sides — the curved-horizon signature. A ramp or a single
    # step (a non-curve) would NOT mirror.
    vmax = max(edges.values())
    plateau = [y for y in ys if edges[y] >= vmax - 1]
    centre = sum(plateau) / len(plateau)
    # centre must sit inside the band, not at an edge (a real bow, not a ramp)
    assert ys[0] + 8 < centre < ys[-1] - 8, \
        f"extremum at row {centre:.0f} sits at the band edge — not a centred bow"

    mirror_diffs = []
    for y in ys:
        ym = round(2 * centre - y)
        if ym in edges:
            mirror_diffs.append(abs(edges[y] - edges[ym]))
    assert len(mirror_diffs) > 80, "too few mirror pairs to judge symmetry"
    worst = max(mirror_diffs)
    mean = sum(mirror_diffs) / len(mirror_diffs)
    # tolerance: a couple px for sub-pixel rounding / anti-aliasing at edges
    assert worst <= 3, \
        f"edge-x not symmetric about the curve centre (curved horizon): " \
        f"worst mirror diff {worst}px, mean {mean:.2f}px"
    assert mean <= 1.0, \
        f"edge-x weakly symmetric: mean mirror diff {mean:.2f}px > 1px"

    # --- PRIMARY (c): the extremum is a genuine bow, dipping on BOTH sides -
    # The centre row is an extremum; rows well above AND well below it must
    # depart from it (a one-sided ramp would not dip on both sides).
    top_e = edges[ys[0]]
    bot_e = edges[ys[-1]]
    assert vmax - top_e >= 4, f"top does not depart from centre: {vmax-top_e}px"
    assert vmax - bot_e >= 4, f"bottom does not depart from centre: {vmax-bot_e}px"


def test_bend_parabola_is_static_while_loop_runs(runner):
    """The static sf_bend must HOLD: two screenshots 30 frames apart are
    pixel-identical (no roll) WHILE the heartbeat advances — proving the loop is
    running (sf_bend_tick rebuilding the table every frame at speed 0) but the
    bend does not animate. This is the property that separates the static
    sf_bend from the animated sf_tunnel, which rolls frame-to-frame."""
    rom = BUILD / "bend_parabola_test.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    img_a = _shot(runner, "parabola_static_a.png")
    beat_a = runner.read_u16(WR, 0xE010)
    runner.run_frames(30)
    beat_b = runner.read_u16(WR, 0xE010)
    img_b = _shot(runner, "parabola_static_b.png")

    assert beat_b > beat_a, \
        f"heartbeat stalled ({beat_a}->{beat_b}) — loop not running, " \
        f"'static' would be vacuous"
    assert img_a.tobytes() == img_b.tobytes(), \
        "frames differ 30 apart — the static sf_bend is rolling like a tunnel"
