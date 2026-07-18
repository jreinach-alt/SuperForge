"""Run-gate for the BG macros: a BG1 tilemap renders and scrolls.

Reads the real outputs: the VRAM tilemap, rendered green pixels, the committed
SHADOW_BG1HOFS, and the on-screen horizontal shift between frames.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam

_GREEN = lambda p: p[0] < 90 and p[1] > 150 and p[2] < 90


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _leftmost_green(img):
    w, _ = img.size
    d = list(img.getdata())
    y = 112
    for x in range(w):
        if _GREEN(d[y * w + x]):
            return x
    return -1


def _green_count(img):
    return sum(1 for p in img.getdata() if _GREEN(p))


def test_bg_renders_and_scrolls(runner):
    rom = BUILD / "bg_scroll_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    # tilemap at VRAM word $5800 (byte $B000): stripes — even cells tile0, odd tile1
    tm = runner.read_bytes(VR, 0xB000, 8)
    assert tm[0:2] == b"\x00\x00" and tm[2:4] == b"\x01\x00", f"tilemap not striped: {tm.hex()}"

    # the BG actually renders (green stripes on screen)
    runner.take_screenshot("/tmp/_bg0.png")
    img0 = Image.open("/tmp/_bg0.png").convert("RGB")
    assert _green_count(img0) > 500, "BG green stripes not visible"
    left0 = _leftmost_green(img0)
    sh0 = runner.read_u16(WR, 0x0120)               # SHADOW_BG1HOFS

    # advance ~30 frames — scroll must move (shadow advances + picture shifts)
    runner.run_frames(30)
    runner.take_screenshot("/tmp/_bg1.png")
    img1 = Image.open("/tmp/_bg1.png").convert("RGB")
    sh1 = runner.read_u16(WR, 0x0120)
    assert sh1 > sh0 > 0, f"SHADOW_BG1HOFS did not advance: {sh0} -> {sh1}"
    # The stripes repeat every 16px, so a single capture can alias (the shift
    # happens to be ≡ 0 mod 16 under load-dependent frame timing — seen when
    # the whole suite runs). Sample across a few extra 7-frame advances
    # (7 is coprime with 16): consecutive captures can only all match left0
    # if the rendered picture is truly frozen.
    lefts = [_leftmost_green(img1)]
    for _ in range(4):
        if lefts[-1] != left0:
            break
        runner.run_frames(7)
        runner.take_screenshot("/tmp/_bgN.png")
        lefts.append(_leftmost_green(Image.open("/tmp/_bgN.png").convert("RGB")))
    assert any(left != left0 for left in lefts), \
        f"the rendered stripes did not scroll (leftmost green stayed at {left0})"
