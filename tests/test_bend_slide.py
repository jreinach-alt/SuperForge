"""Run-gate for E-SLIDE (bend/tunnel v1.1): the pure-roll pointer-slide
fast-path. For an animated roll with NO horizontal scroll, the per-frame tick
does NO table rebuild — it advances only the channel's HDMA source pointer
A1Tn into a once-baked oversized table, phasing the roll by sliding the read
window. Near-zero per-frame cost; reverses under a negative speed.

Two proofs, both required by the addendum:
  1. RENDERED-PIXEL roll + reverse: bend_slide_test.asm arms the marquee tunnel
     as a pure roll (base scroll 0 -> slide path) and FLIPS the speed sign at
     frame 90 via sf_bend_phase. We measure the vertical roll direction (the
     shift of the per-scanline edge-x signature) before and after the flip and
     assert it REVERSES — the same armed slide rolls and reverses live.
  2. COST: the slide path (bend_cycles_test, base 0) is near-zero, and the
     optimized refill path (bend_cycles_refill_test, base 100) is the ~74k-mc
     S1 cost. Both measured on the frame-budget harness (kit rule #1).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

FRAME_MC = 1364 * 262


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


def _vertical_roll_dy(img_a, img_b):
    """Best vertical shift dy aligning b's edge profile onto a's (positive dy =
    pattern rolled DOWN). Same method as test_bend_reverse."""
    y_top, y_bot = _lit_range(img_a)
    y_top += 4
    y_bot -= 4
    pa = [_first_edge(img_a, y) for y in range(y_top, y_bot)]
    pb = [_first_edge(img_b, y) for y in range(y_top, y_bot)]
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


def test_slide_rolls_and_reverses_on_pixels(runner):
    rom = BUILD / "bend_slide_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"slide tunnel failed to allocate: {chan:#x}"

    # --- FORWARD window (direction flag still 1) ----------------------------
    # find a frame solidly before the flip (flip is at FRAME_COUNTER 90)
    assert runner.read_u16(WR, 0xE018) == 1, "should start forward"
    f0 = _shot(runner, "slide_fwd0.png")
    runner.run_frames(6)
    assert runner.read_u16(WR, 0xE018) == 1, "still forward for this window"
    f1 = _shot(runner, "slide_fwd1.png")
    dy_fwd = _vertical_roll_dy(f0, f1)

    # --- advance past the flip into the REVERSE window ----------------------
    for _ in range(120):
        runner.run_frames(1)
        if runner.read_u16(WR, 0xE018) == 0:
            break
    assert runner.read_u16(WR, 0xE018) == 0, "roll did not flip to reverse"
    runner.run_frames(2)
    r0 = _shot(runner, "slide_rev0.png")
    runner.run_frames(6)
    r1 = _shot(runner, "slide_rev1.png")
    dy_rev = _vertical_roll_dy(r0, r1)

    assert dy_fwd != 0, f"forward slide not rolling: dy={dy_fwd}"
    assert dy_rev != 0, f"reverse slide not rolling: dy={dy_rev}"
    # the decisive E-SLIDE+reverse assertion: direction flips with the speed sign
    assert (dy_fwd > 0) != (dy_rev > 0), (
        f"slide did not reverse: forward dy={dy_fwd}, reverse dy={dy_rev}"
    )


def _measure(runner, rom_name):
    rom = BUILD / rom_name
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    rebuilds = runner.read_u32(WR, 0xE030)
    frames = runner.read_u32(WR, 0xE034)
    assert rebuilds > 100 and frames > 50, \
        f"{rom_name}: window too small: rebuilds={rebuilds} frames={frames}"
    return frames * FRAME_MC / rebuilds


def test_slide_cost_is_near_zero_and_refill_is_optimized(runner):
    slide_mc = _measure(runner, "bend_cycles_test.sfc")
    refill_mc = _measure(runner, "bend_cycles_refill_test.sfc")

    slide_pct = 100.0 * slide_mc / FRAME_MC
    refill_pct = 100.0 * refill_mc / FRAME_MC

    # the slide is just A1Tn arithmetic — well under 2% of a frame.
    assert slide_mc < 7000, (
        f"E-SLIDE not near-zero: {slide_mc:.0f} mc/tick ({slide_pct:.2f}% of a "
        "frame) — expected ~1,300 mc (~0.4%)"
    )
    # the refill is the S1 optimized path — ~74k mc, well under the v1 ~167k.
    assert refill_mc < 107000, (
        f"refill regressed: {refill_mc:.0f} mc/tick ({refill_pct:.1f}%) — "
        "v1.1 target ~73,900 mc (~20.7%)"
    )
    # and the slide must be dramatically cheaper than the refill (the whole point)
    assert slide_mc * 5 < refill_mc, (
        f"slide ({slide_mc:.0f}) not much cheaper than refill ({refill_mc:.0f})"
    )
