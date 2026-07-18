"""Run-gate for sf_parallax_bands / sf_parallax_tick: two bands of one BG layer
move at observably different rates from one world-X, and FREEZE (pixels stop
moving) the moment world-X stops changing.

Reads the real outputs: rendered screenshot pixels per band (the stripes'
on-screen shift), with the ROM's world-X mirror at $7E:E010 as the exact
displacement ground truth. The freeze assertion is the USER-VISIBLE invariant
— consecutive rendered frames are byte-identical — never an implementation
proxy like "the ratios are zero" (the documented spec-trap: zeroing ratios
teleports the layer to world-zero instead of freezing it).

ROM contract (tests/parallax_test.asm):
  BG1 vertical stripes, 64px period. Bands split at scanline 112:
  ratio_top = 64/256 (0.25), ratio_bot = 192/256 (0.75). Holding RIGHT
  advances world-X 2px/frame; released, world-X freezes.
  $7E:E010 = world-X, $7E:E012 = allocated HDMA channel.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

RATIO_TOP = 0x40                 # 0.25 in fraction-byte units (n/256)
RATIO_BOT = 0xC0                 # 0.75
STRIPE_PERIOD = 64               # px — shifts are unambiguous mod 64
TOP_ROWS = (40, 60)              # screenshot rows inside the top band
BOT_ROWS = (150, 180)            # screenshot rows inside the bottom band


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
    """Stripe pattern of a row: 1 = green pixel, 0 = background."""
    return [1 if img.getpixel((x, y))[1] > 120 else 0 for x in range(256)]


def _band_shift(img_a, img_b, y):
    """Leftward pixel shift of the stripe pattern at row y between two
    screenshots (content shifts left as HOFS grows). Returns (shift,
    mismatch) for the best shift in 0..63: b[x] == a[(x+s) % 256]."""
    a, b = _row_bits(img_a, y), _row_bits(img_b, y)
    best = None
    for s in range(STRIPE_PERIOD):
        m = sum(1 for x in range(256) if b[x] != a[(x + s) % 256])
        if best is None or m < best[1]:
            best = (s, m)
    return best


def test_parallax_bands_move_and_freeze(runner):
    rom = BUILD / "parallax_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    # the macro armed a real HDMA channel
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"sf_parallax_bands failed to allocate: {chan:#x}"
    assert runner.read_u16(WR, 0xE010) == 0, "world-X moved without input"

    # baseline: world-X = 0, frozen
    img0 = _shot(runner, "parallax_base.png")
    for y in TOP_ROWS + BOT_ROWS:
        assert sum(_row_bits(img0, y)) > 50, f"no stripes at row {y}"

    # --- MOTION: hold RIGHT; world-X advances 2px/frame ---
    runner.set_input(0, right=True)
    runner.run_frames(30)
    runner.set_input(0)
    runner.run_frames(5)                       # settle: world-X is now stable
    wx = runner.read_u16(WR, 0xE010)
    # guard the degenerate sample (wx == 0, or both bands' expected shifts
    # coincide mod 64, i.e. wx % 128 == 0) — extend the hold and re-read
    for _ in range(4):
        if wx != 0 and wx % 128 != 0:
            break
        runner.set_input(0, right=True)
        runner.run_frames(10)
        runner.set_input(0)
        runner.run_frames(5)
        wx = runner.read_u16(WR, 0xE010)
    assert wx > 0 and wx % 128 != 0, f"could not reach a usable world-X: {wx}"

    expected_top = ((wx * RATIO_TOP) >> 8) % STRIPE_PERIOD
    expected_bot = ((wx * RATIO_BOT) >> 8) % STRIPE_PERIOD
    assert expected_top != expected_bot       # guaranteed by wx % 128 != 0

    img1 = _shot(runner, "parallax_moved.png")
    for y in TOP_ROWS:
        s, m = _band_shift(img0, img1, y)
        assert m <= 4, f"top band row {y}: no clean shift (mismatch {m})"
        assert s == expected_top, \
            f"top band row {y}: shift {s} != world_x*{RATIO_TOP}/256 = {expected_top} (wx={wx})"
    for y in BOT_ROWS:
        s, m = _band_shift(img0, img1, y)
        assert m <= 4, f"bottom band row {y}: no clean shift (mismatch {m})"
        assert s == expected_bot, \
            f"bottom band row {y}: shift {s} != world_x*{RATIO_BOT}/256 = {expected_bot} (wx={wx})"
    # the two bands moved at observably different rates
    assert expected_top != expected_bot

    # --- FREEZE: world-X stopped → pixels stop moving, in BOTH bands ---
    # (the per-frame sf_parallax_tick keeps rebuilding the table; with
    # world-X unchanged the rendered frame must be byte-identical)
    img_f1 = _shot(runner, "parallax_frozen_a.png")
    runner.run_frames(3)
    img_f2 = _shot(runner, "parallax_frozen_b.png")
    assert img_f1.tobytes() == img_f2.tobytes(), \
        "pixels moved while world-X was frozen (freeze invariant broken)"
    runner.run_frames(7)
    img_f3 = _shot(runner, "parallax_frozen_c.png")
    assert img_f1.tobytes() == img_f3.tobytes(), \
        "pixels drifted across 10 frozen frames"
    assert runner.read_u16(WR, 0xE010) == wx, "world-X drifted without input"
