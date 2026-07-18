"""Run-gate for sf_colormath_on / sf_colormath_off / sf_colormath_tint: a red
ADD tint on a gray backdrop moves the RENDERED pixels in the mathematically
expected direction (red channel rises, green/blue hold), and the screen
reverts after sf_colormath_off.

Primary assertions read rendered screenshot pixels — the shadow registers in
WRAM are implementation detail, not evidence. The full off → on+tint → off
state cycle is driven through the ROM via controller input.

ROM contract (tests/colormath_test.asm):
  Backdrop = mid-gray (r=g=b=12 of 31). A held → sf_colormath_on #1 (ADD),
  #$20 (backdrop) + sf_colormath_tint #15,#0,#0; released → sf_colormath_off.
  $7E:E010 = frame heartbeat, $7E:E014 = ROM-side state (0=off, 1=on).
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


def _shot(runner, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    runner.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


def _avg_center(img):
    """Average RGB over a grid in the center of the frame (the backdrop is
    uniform — center sampling avoids any overscan border rows)."""
    w, h = img.size
    pts = [
        img.getpixel((x, y))
        for x in range(w // 4, 3 * w // 4, 16)
        for y in range(h // 4, 3 * h // 4, 16)
    ]
    n = len(pts)
    return tuple(sum(p[i] for p in pts) / n for i in range(3))


def test_colormath_tint_cycle(runner):
    rom = BUILD / "colormath_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    # frame loop alive
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    # --- state 1: color math OFF — the plain gray backdrop ---
    assert runner.read_u16(WR, 0xE014) == 0, "ROM should boot with math off"
    off1 = _avg_center(_shot(runner, "colormath_off1.png"))
    r0, g0, b0 = off1
    assert 60 < r0 < 140 and 60 < g0 < 140 and 60 < b0 < 140, \
        f"backdrop not mid-gray: {off1}"
    assert max(off1) - min(off1) < 25, f"backdrop not neutral gray: {off1}"

    # --- state 2: A held → math ON, ADD red tint on the backdrop.
    #     Expected direction: red rises by the tint (12+15 of 31 ≈ +120 in
    #     8-bit), green/blue unchanged ---
    runner.set_input(0, a=True)
    runner.run_frames(8)
    assert runner.read_u16(WR, 0xE014) == 1, "ROM did not see the A press"
    on = _avg_center(_shot(runner, "colormath_on.png"))
    r1, g1, b1 = on
    assert r1 > r0 + 60, f"red did not rise under ADD red tint: {off1} -> {on}"
    assert abs(g1 - g0) < 25, f"green moved under a pure-red tint: {off1} -> {on}"
    assert abs(b1 - b0) < 25, f"blue moved under a pure-red tint: {off1} -> {on}"

    # --- state 3: released → math OFF — pixels revert to the original gray ---
    runner.set_input(0)
    runner.run_frames(8)
    assert runner.read_u16(WR, 0xE014) == 0, "ROM did not see the A release"
    off2 = _avg_center(_shot(runner, "colormath_off2.png"))
    for i, name in enumerate("rgb"):
        assert abs(off2[i] - off1[i]) < 15, \
            f"{name} did not revert after sf_colormath_off: {off1} -> {off2}"
