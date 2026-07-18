"""Run-gate for sf_pal / sf_pal_cycle / sf_pal_cycle_stop / sf_pal_cycle_tick:
the four cycled CGRAM entries render as four screen strips whose colors are
always a cyclic rotation of (RED, GREEN, BLUE, WHITE), the rendered color AT
THE SAME SCREEN POSITION changes over time per the rotation, and a stop call
freezes the screen.

Assertions are on RENDERED screenshot pixels at fixed screen positions —
SHADOW_CGRAM bytes are implementation detail (a shadow can rotate perfectly
while the commit bridge ships nothing; the screen is the evidence).

ROM contract (tests/pal_cycle_test.asm):
  BG1 = four 64px vertical strips of color indices 1..4; CGRAM 1-4 fed via
  sf_pal as RED/GREEN/BLUE/WHITE; sf_pal_cycle #1,#4,#8 (rotate right every
  8 frames); sf_pal_cycle_tick before sf_frame_end every frame. A press →
  sf_pal_cycle_stop. $7E:E010 = heartbeat, $7E:E014 = 1 cycling / 0 stopped.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

BASE = ("R", "G", "B", "W")
ROTATIONS = {  # rotate right: entry i's color moves to entry i+1
    ("R", "G", "B", "W"),
    ("W", "R", "G", "B"),
    ("B", "W", "R", "G"),
    ("G", "B", "W", "R"),
}


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


def _classify(px):
    r, g, b = px
    hi = [c > 150 for c in px]
    lo = [c < 80 for c in px]
    if all(hi):
        return "W"
    if hi[0] and lo[1] and lo[2]:
        return "R"
    if hi[1] and lo[0] and lo[2]:
        return "G"
    if hi[2] and lo[0] and lo[1]:
        return "B"
    return None


def _strip_row(img):
    """Find a screenshot row where all four strips classify cleanly; return
    (y, centers). Strips are 64px (of the 256px frame) — sample the centers."""
    w, h = img.size
    centers = [w * (2 * i + 1) // 8 for i in range(4)]
    good = [
        y for y in range(h)
        if all(_classify(img.getpixel((x, y))) for x in centers)
    ]
    assert len(good) > 120, f"strips not visible (only {len(good)} clean rows)"
    return good[len(good) // 2], centers


def _tuple_at(img, y, centers):
    return tuple(_classify(img.getpixel((x, y))) for x in centers)


def test_pal_cycle_rotates_then_freezes(runner):
    rom = BUILD / "pal_cycle_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE014) == 1, "ROM should boot cycling"

    # frame loop alive
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    # locate the strips once (geometry is static; only the palette rotates)
    img0 = _shot(runner, "pal_cycle_t0.png")
    y, centers = _strip_row(img0)

    # --- the rotation, observed at fixed screen positions over time ---
    tuples = [_tuple_at(img0, y, centers)]
    for i in range(1, 4):
        runner.run_frames(10)           # speed=8 → 1-2 steps per sample gap
        img = _shot(runner, f"pal_cycle_t{i}.png")
        tuples.append(_tuple_at(img, y, centers))

    for i, t in enumerate(tuples):
        # every snapshot shows all four distinct colors as a cyclic rotation
        # of the fed (R,G,B,W) — rotation preserves the set and the order
        assert t in ROTATIONS, f"sample {i} is not a rotation of RGBW: {t}"
    assert len(set(tuples)) >= 2, \
        f"rendered colors never changed at fixed positions: {tuples}"

    # --- stop: colors must freeze ON SCREEN (no snap-back, no further steps) ---
    runner.set_input(0, a=True)
    runner.run_frames(4)
    runner.set_input(0)
    runner.run_frames(6)                # let the stop + any in-flight DMA land
    assert runner.read_u16(WR, 0xE014) == 0, "ROM did not see the stop press"

    frozen_a = _shot(runner, "pal_cycle_stop_a.png")
    runner.run_frames(24)               # 3x the rotation period
    frozen_b = _shot(runner, "pal_cycle_stop_b.png")

    ta = _tuple_at(frozen_a, y, centers)
    tb = _tuple_at(frozen_b, y, centers)
    assert ta in ROTATIONS, f"post-stop screen not a valid rotation: {ta}"
    assert ta == tb, f"colors kept rotating after sf_pal_cycle_stop: {ta} -> {tb}"
    # the strongest freeze evidence: the rendered frames are byte-identical
    assert frozen_a.tobytes() == frozen_b.tobytes(), \
        "frames differ after stop — screen did not freeze"
