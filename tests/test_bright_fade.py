"""Run-gate for sf_bright_fade + sf_bright_fade_tick: an armed fade moves the
RENDERED screen luminance monotonically in the right direction across ≥3
sample points, ends at the target, and works in BOTH directions (down to
black, back up to full — state-cycle coverage).

Assertions are on screenshot pixels (mean luminance). Per the test spec, no
exact frame-by-frame values are asserted (NMI/input timing skews the sample
phase) — only the monotonic direction and the endpoints.

ROM contract (tests/bright_fade_test.asm):
  White backdrop, boot brightness 15 (init_ppu's SHADOW_INIDISP=$0F).
  A press → sf_bright_fade #0,#60 (down); B press → sf_bright_fade #15,#60
  (up); sf_bright_fade_tick every frame. $7E:E010 = heartbeat,
  $7E:E014 = SHADOW_INIDISP mirror (supplemental ground truth).
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


def _lum(runner, name):
    """Mean luminance over a center grid of the frame."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    runner.take_screenshot(str(path))
    img = Image.open(path).convert("RGB")
    w, h = img.size
    pts = [
        img.getpixel((x, y))
        for x in range(w // 4, 3 * w // 4, 16)
        for y in range(h // 4, 3 * h // 4, 16)
    ]
    return sum(sum(p) / 3 for p in pts) / len(pts)


def _press(runner, **btn):
    """One clean press edge: hold a few frames, release."""
    runner.set_input(0, **btn)
    runner.run_frames(3)
    runner.set_input(0)


def test_bright_fade_down_then_up(runner):
    rom = BUILD / "bright_fade_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    # frame loop alive
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    # boot state: full brightness (the documented init_ppu starting value)
    assert runner.read_u16(WR, 0xE014) == 0x0F, "boot SHADOW_INIDISP != $0F"
    l0 = _lum(runner, "bright_fade_start.png")
    assert l0 > 180, f"start screen not bright (white @ brightness 15): {l0}"

    # --- fade DOWN: A press arms target 0 over 60 frames ---
    _press(runner, a=True)
    runner.run_frames(12)               # ~1/4 through the fade
    d1 = _lum(runner, "bright_fade_down_mid1.png")
    runner.run_frames(20)               # ~3/5 through
    d2 = _lum(runner, "bright_fade_down_mid2.png")
    runner.run_frames(45)               # past the end (60 frames + slack)
    d3 = _lum(runner, "bright_fade_down_end.png")

    assert d1 < l0 - 15, f"luminance did not start falling: {l0} -> {d1}"
    assert d2 < d1 - 25, f"luminance not monotonically falling: {d1} -> {d2}"
    assert d3 < d2, f"luminance rose at the tail of the fade: {d2} -> {d3}"
    assert d3 < 12, f"fade-down did not end near-black: {d3}"
    assert runner.read_u16(WR, 0xE014) == 0x00, "fade-down did not land on 0"

    # --- fade UP: B press arms target 15 over 60 frames (the other half of
    #     the state cycle) ---
    _press(runner, b=True)
    runner.run_frames(12)
    u1 = _lum(runner, "bright_fade_up_mid1.png")
    runner.run_frames(20)
    u2 = _lum(runner, "bright_fade_up_mid2.png")
    runner.run_frames(45)
    u3 = _lum(runner, "bright_fade_up_end.png")

    assert u1 > d3 + 15, f"luminance did not start rising: {d3} -> {u1}"
    assert u2 > u1 + 25, f"luminance not monotonically rising: {u1} -> {u2}"
    assert u3 > u2, f"luminance fell at the tail of the fade: {u2} -> {u3}"
    assert u3 > l0 - 20, f"fade-up did not return to full brightness: {u3} vs {l0}"
    assert runner.read_u16(WR, 0xE014) == 0x0F, "fade-up did not land on 15"
