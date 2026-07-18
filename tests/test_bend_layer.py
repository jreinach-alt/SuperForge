"""Run-gate for E-LAYER (bend/tunnel v1.1): sf_tunnel arms the per-scanline
curve bend on a SELECTABLE layer (BG2 here), not just BG1.

The ROM (tests/bend_layer_test.asm) puts the vertical-stripe reference feature
on BG2 only (BG1 blank) and arms sf_tunnel ..., #2. The engine derives BBAD
from HDMA_BEND_LAYER (2 -> $0F BG2HOFS), so any per-scanline horizontal
displacement read from rendered pixels can only come from the BG2 bend. We read
RENDERED PIXELS (kit rule #2): the stripe edge x must vary per scanline along
the sine curve, and the pattern must advance between frames (the roll).
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


def _row_shift(img_a, img_b, y):
    a, b = _row_bits(img_a, y), _row_bits(img_b, y)
    best = None
    for s in range(STRIPE_PERIOD):
        m = sum(1 for x in range(256) if b[x] != a[(x + s) % 256])
        if best is None or m < best[1]:
            best = (s, m)
    return best


def test_bend_on_bg2_displaces_and_rolls(runner):
    rom = BUILD / "bend_layer_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)

    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"sf_tunnel (BG2) failed to allocate: {chan:#x}"
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    img_a = _shot(runner, "bend_layer_a.png")
    y_top, y_bot = _lit_range(img_a)
    assert y_bot - y_top > 120, f"stripe band too small: {y_top}..{y_bot}"

    # PRIMARY (a): BG2's stripe edge x varies per scanline along the curve.
    edges = [_first_edge(img_a, y) for y in range(y_top + 4, y_bot - 3)]
    edges = [e for e in edges if e >= 0]
    assert len(edges) > 100, "could not track the BG2 stripe edge down the frame"
    span = max(edges) - min(edges)
    assert span >= 12, \
        f"BG2 not bent: stripe edge x varies only {span}px per scanline (flat)"
    assert len(set(edges)) >= 8, \
        f"BG2 stripe edge takes only {len(set(edges))} x values — not a curve"

    # PRIMARY (b): the BG2 tunnel rolls (pattern advances between frames).
    runner.run_frames(8)
    img_b = _shot(runner, "bend_layer_b.png")
    assert img_a.tobytes() != img_b.tobytes(), \
        "frames identical 8 apart — the BG2 tunnel is not rolling"

    rows = list(range(y_top + 12, y_bot - 12, max(1, (y_bot - y_top) // 8)))
    clean_moved = 0
    for y in rows:
        s, m = _row_shift(img_a, img_b, y)
        if m <= 6 and s != 0:
            clean_moved += 1
    assert clean_moved >= len(rows) // 2, \
        f"BG2 roll not visible: only {clean_moved}/{len(rows)} rows shifted"
