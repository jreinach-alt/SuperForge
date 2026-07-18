"""Run-gate for E-DIR (bend/tunnel v1.1): a NEGATIVE (two's-complement) tunnel
speed REVERSES the roll direction.

The phase advance is a wrapping 16-bit add and the curve is sampled at
(scanline + phase) & $FF, so speed #$FFFE (= -2) rolls the per-scanline
displacement pattern the OPPOSITE way to a positive speed. bend_reverse_test.asm
is identical to bend_test.asm except the speed sign.

We read RENDERED PIXELS and measure the roll DIRECTION, not just "frames
differ": the per-scanline stripe-edge-x profile is a vertical signature of the
sine displacement; as the tunnel rolls, that signature slides vertically. We
find the best vertical shift dy that aligns two frames N apart, and assert the
NEGATIVE-speed ROM's dy has the OPPOSITE SIGN to the POSITIVE-speed bend_test's
dy (kit rule #2 — direction reversal proven on output, not asserted by fiat).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

FRAMES_APART = 6                 # capture window for the roll (small dy)


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


def _edge_profile(img, y_top, y_bot):
    """Per-row leftmost stripe-edge x — the vertical signature of the bend."""
    return [_first_edge(img, y) for y in range(y_top, y_bot)]


def _vertical_roll_dy(img_a, img_b):
    """Best vertical shift dy (in scanlines) that aligns b's edge profile onto
    a's: prof_b[i] ~= prof_a[i - dy]. Positive dy = pattern rolled DOWN."""
    y_top, y_bot = _lit_range(img_a)
    y_top += 4
    y_bot -= 4
    pa = _edge_profile(img_a, y_top, y_bot)
    pb = _edge_profile(img_b, y_top, y_bot)
    n = len(pa)
    best = None
    for dy in range(-20, 21):
        diffs = []
        for i in range(n):
            j = i - dy
            if 0 <= j < n and pa[j] >= 0 and pb[i] >= 0:
                diffs.append(abs(pb[i] - pa[j]))
        if len(diffs) < n // 2:
            continue
        err = sum(diffs) / len(diffs)
        if best is None or err < best[1]:
            best = (dy, err)
    assert best is not None, "could not align the bend profiles vertically"
    return best[0]


def _measure_roll(runner, rom_name, tag):
    rom = BUILD / rom_name
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"{rom_name}: tunnel failed to allocate: {chan:#x}"
    img_a = _shot(runner, f"{tag}_a.png")
    runner.run_frames(FRAMES_APART)
    img_b = _shot(runner, f"{tag}_b.png")
    assert img_a.tobytes() != img_b.tobytes(), f"{rom_name}: not rolling"
    return _vertical_roll_dy(img_a, img_b)


def test_negative_speed_reverses_the_roll(runner):
    # positive speed (#2): the marquee forward/downward roll
    dy_pos = _measure_roll(runner, "bend_test.sfc", "rev_pos")
    # negative speed (#$FFFE = -2): the reverse roll
    dy_neg = _measure_roll(runner, "bend_reverse_test.sfc", "rev_neg")

    # both must actually roll (nonzero vertical motion)
    assert dy_pos != 0, f"positive-speed roll dy=0 (not rolling): {dy_pos}"
    assert dy_neg != 0, f"negative-speed roll dy=0 (not rolling): {dy_neg}"

    # the decisive E-DIR assertion: the roll DIRECTION flips with the sign
    assert (dy_pos > 0) != (dy_neg > 0), (
        f"negative speed did NOT reverse the roll: pos dy={dy_pos}, "
        f"neg dy={dy_neg} (same sign)"
    )
