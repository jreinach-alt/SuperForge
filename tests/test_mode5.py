"""Dispatcher Mode 5 (hi-res 512×224, line-doubled) render gate.

Proves engine_gfxmode(5) renders at 512-wide hi-res with the main/sub tile-pair
split. Each tilemap entry fetches a MAIN tile (odd output cols) + a SUB tile
(even output cols); the ROM's pair is main=solid-white / sub=transparent, so the
rendered 512-wide frame carries fine per-column detail (adjacent output columns
differ) that is IMPOSSIBLE in a 256-wide mode (which line-doubles each column).
Evidence is rendered pixels — the screenshot width + the adjacent-column
difference count — never a proxy.

ROM contract (tests/mode5_test.asm): white/transparent main/sub block over rows
8..23. $7E:E008=1, $7E:E010=SHADOW_BGMODE ($05), $7E:E011=SHADOW_TM ($13).
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
def state():
    rom = BUILD / "mode5_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode5_test` first"
    SHOTS.mkdir(parents=True, exist_ok=True)
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))
        path = SHOTS / "mode5.png"
        r.take_screenshot(str(path))
        img = Image.open(path).convert("RGB")
    finally:
        r.stop()
    return {"debug": debug, "img": img}


def test_boots(state):
    assert state["debug"][0:4] == b"SFDB"
    assert state["debug"][0x08] == 0x01 and state["debug"][0x09] == 0x00


def test_shadow_regs(state):
    assert state["debug"][0x10] == 0x05, "SHADOW_BGMODE != $05"
    assert state["debug"][0x11] == 0x13, "SHADOW_TM != $13"


def test_screenshot_is_512_wide(state):
    """Hi-res Mode 5 renders a 512-wide frame buffer."""
    assert state["img"].size[0] == 512, (
        f"Mode 5 screenshot width {state['img'].size[0]} != 512"
    )


def test_hires_per_column_detail(state):
    """RENDERED 512-px proof: inside the content block, horizontally-adjacent
    output columns differ frequently. The main/sub split puts solid white on
    odd cols and transparent (black) on even cols — a per-column alternation
    that a 256-wide (column-doubled) mode cannot produce. Sample several rows
    and count adjacent-pixel transitions across the 512-wide span."""
    img = state["img"]
    w, h = img.size
    # The content block is rows 8..23 (SNES y 64..191). With Mesen's hi-res
    # screenshot vertical scaling, sample a band in the middle of the frame.
    transitions = 0
    rows_checked = 0
    for y in range(h // 3, 2 * h // 3, 4):
        row_changes = 0
        prev = img.getpixel((0, y))
        for x in range(1, w):
            cur = img.getpixel((x, y))
            if cur != prev:
                row_changes += 1
            prev = cur
        if row_changes > 0:
            rows_checked += 1
        transitions += row_changes
    # A solid 256-mode block would have ~2 transitions per row (block edges).
    # The 512-wide main/sub alternation yields dozens-to-hundreds per content
    # row. Require a high aggregate transition count.
    assert transitions > 200, (
        f"too few adjacent-column transitions ({transitions}) across "
        f"{rows_checked} content rows — hi-res per-column split did not render"
    )
