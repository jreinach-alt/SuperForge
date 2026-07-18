"""sf_window run-gate: PPU window masking, verified from rendered pixels.

A fully-green BG1 with a magenta backdrop; sf_window masks BG1 inside window 1
on the main screen, so the windowed band reveals the magenta backdrop. The band
starts as the right half: the LEFT half stays green, the RIGHT half is magenta.
The ROM slides the window's left edge (WH0) left each frame, so the clip column
moves over time.

Primary evidence is rendered screenshot pixels (never a proxy variable):
  - the left half is green and the right half is magenta (the mask clips BG1),
  - the green->magenta clip column moves LEFT between two frames (moving WH0
    moves the clip edge: frame-A != frame-B at the boundary).
The SHADOW_WH0 mirror at $7E:E010 is a structural cross-check, not the proof.

ROM contract (tests/window_test.asm):
  $7E:E000="SFDB", $7E:E008=1; $7E:E010 mirrors SHADOW_WH0 (window 1 left edge).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

ROW = 110                       # sample row (mid-screen, clear of any HUD)
LEFT_X = 60                     # left half — BG1 visible (green)
RIGHT_X = 200                   # right half — BG1 masked -> backdrop (magenta)

_GREEN = lambda p: p[0] < 90 and p[1] > 140 and p[2] < 90
_MAGENTA = lambda p: p[0] > 140 and p[1] < 90 and p[2] > 140


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _clip_column(img, row):
    """Lowest x where the row turns from green (BG) to magenta (backdrop)."""
    w, _ = img.size
    d = list(img.getdata())
    for x in range(w):
        if _MAGENTA(d[row * w + x]):
            return x
    return None


def _shoot(r, name):
    path = SHOTS / name
    SHOTS.mkdir(parents=True, exist_ok=True)
    r.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


def test_window_masks_and_edge_moves(runner):
    rom = BUILD / "window_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make window_test` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "ROM did not boot"
    assert runner.read_u16(WR, 0xE008) == 1, "ROM did not reach the frame loop"

    # --- Frame A: band is the right half. Left=green, right=magenta. ---
    img_a = _shoot(runner, "window_a.png")
    wh0_a = runner.read_bytes(WR, 0xE010, 1)[0]

    px_left = img_a.getpixel((LEFT_X, ROW))
    px_right = img_a.getpixel((RIGHT_X, ROW))
    assert _GREEN(px_left), f"left half not green (BG should show): {px_left}"
    assert _MAGENTA(px_right), \
        f"right half not magenta (BG should be masked to backdrop): {px_right}"

    clip_a = _clip_column(img_a, ROW)
    assert clip_a is not None, "no green->magenta clip column found in frame A"

    # --- Frame B: WH0 has slid left, so the clip column moves left too. ---
    runner.run_frames(30)
    img_b = _shoot(runner, "window_b.png")
    wh0_b = runner.read_bytes(WR, 0xE010, 1)[0]
    clip_b = _clip_column(img_b, ROW)
    assert clip_b is not None, "no clip column found in frame B"

    # The shadow (and therefore the PPU edge) moved left.
    assert wh0_b < wh0_a, f"WH0 did not decrease ({wh0_a} -> {wh0_b})"
    # The RENDERED clip column moved left, correlated with the WH0 delta.
    moved = clip_a - clip_b
    assert moved > 0, f"clip column did not move left ({clip_a} -> {clip_b})"
    # Right-half pixel is still magenta the whole time (mask still active).
    assert _MAGENTA(img_b.getpixel((RIGHT_X, ROW))), "mask lost between frames"
