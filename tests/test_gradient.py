"""Run-gate for the sf_gradient_* macros: a red→blue COLDATA gradient renders
as actual screen rows — red-dominant at the top, blue-dominant at the bottom,
monotonic in between.

Primary assertions read RENDERED PIXELS from a screenshot (the HDMA tables in
WRAM are implementation detail, not evidence — a table can be byte-perfect
while the screen shows nothing).

ROM contract (tests/gradient_test.asm):
  sf_gradient_rgb #31,#0,#0, #0,#0,#31 (top pure red → bottom pure blue),
  color math = add fixed color on the black backdrop, so each screen row IS
  the gradient color for that scanline. $7E:E010 = frame heartbeat,
  $7E:E012 = first allocated HDMA channel.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _avg_row(img, y):
    """Average RGB of a row across three sample columns (defeats single-pixel
    noise without averaging the whole row)."""
    px = [img.getpixel((x, y)) for x in (64, 128, 192)]
    return tuple(sum(c[i] for c in px) / 3 for i in range(3))


def test_gradient_renders_red_to_blue(runner):
    rom = BUILD / "gradient_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    # the macro armed real HDMA channels (3 allocated, first returned)
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"sf_gradient_rgb failed to allocate: {chan:#x}"

    # the frame loop is alive (heartbeat advances)
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    SHOTS.mkdir(parents=True, exist_ok=True)
    shot = SHOTS / "gradient.png"
    runner.take_screenshot(str(shot))
    img = Image.open(str(shot)).convert("RGB")
    w, h = img.size

    # locate the rendered scanline range inside the (overscan-padded)
    # screenshot: rows where the gradient is visibly non-black
    lit = [y for y in range(h) if max(_avg_row(img, y)) > 40]
    assert len(lit) > 180, f"gradient not visible (only {len(lit)} lit rows)"
    y_top, y_bot = lit[0], lit[-1]

    # top rows: red-dominant, no blue/green contamination
    r, g, b = _avg_row(img, y_top + 4)
    assert r > 190 and b < 50 and g < 30, f"top row not pure red: {(r, g, b)}"

    # bottom rows: blue-dominant
    r, g, b = _avg_row(img, y_bot - 4)
    assert b > 190 and r < 50 and g < 30, f"bottom row not pure blue: {(r, g, b)}"

    # midpoint: both channels mid-ramp (a hard top/bottom split would pass
    # the two row checks above but is not a gradient)
    y_mid = (y_top + y_bot) // 2
    r, g, b = _avg_row(img, y_mid)
    assert 60 < r < 200 and 60 < b < 200, f"midpoint not mid-ramp: {(r, g, b)}"

    # monotonic ramp: red never rises, blue never falls (small tolerance for
    # 5-bit quantization steps), sampled every 8 rows through the range
    samples = [_avg_row(img, y) for y in range(y_top + 4, y_bot - 3, 8)]
    for i in range(1, len(samples)):
        assert samples[i][0] <= samples[i - 1][0] + 12, \
            f"red rises at sample {i}: {samples[i - 1][0]} -> {samples[i][0]}"
        assert samples[i][2] >= samples[i - 1][2] - 12, \
            f"blue falls at sample {i}: {samples[i - 1][2]} -> {samples[i][2]}"
    # and the ramp actually traverses the range (not a flat tint)
    assert samples[0][0] - samples[-1][0] > 150, "red did not ramp down"
    assert samples[-1][2] - samples[0][2] > 150, "blue did not ramp up"
