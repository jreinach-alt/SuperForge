"""Dispatcher Mode 6 (hi-res 512 + offset-per-tile) render gate.

Mode 6 = BG1 4bpp hi-res (Mode-5 main/sub pair) + BG3 OPT source; no BG2. This
gate proves BOTH render: the 512-wide hi-res split (fine per-column detail) AND
a controller-toggled OPT column warp. Evidence is rendered pixels — the 512
width + per-column transition count + a warp-on/off frame diff — never a proxy.

ROM contract (tests/mode6_test.asm): column-varying hi-res pairs over rows
8..23; A released = flat, A held = column N shifted N*8 px (NMI flushes OPT).
$7E:E008=1, $7E:E010=SHADOW_BGMODE ($06), $7E:E011=SHADOW_TM ($11).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")


def _diff(a, b):
    n = 0
    w, h = a.size
    for y in range(h // 3, 2 * h // 3, 4):
        for x in range(0, w, 2):
            if a.getpixel((x, y)) != b.getpixel((x, y)):
                n += 1
    return n


@pytest.fixture(scope="module")
def state():
    rom = BUILD / "mode6_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode6_test` first"
    SHOTS.mkdir(parents=True, exist_ok=True)
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))

        r.set_input(0)
        r.run_frames(12)
        p_off = SHOTS / "mode6_off.png"
        r.take_screenshot(str(p_off))
        img_off = Image.open(p_off).convert("RGB")

        r.set_input(0, a=True)
        r.run_frames(12)
        p_on = SHOTS / "mode6_on.png"
        r.take_screenshot(str(p_on))
        img_on = Image.open(p_on).convert("RGB")

        r.set_input(0)
        r.run_frames(12)
        p_off2 = SHOTS / "mode6_off2.png"
        r.take_screenshot(str(p_off2))
        img_off2 = Image.open(p_off2).convert("RGB")
    finally:
        r.stop()
    return {"debug": debug, "off": img_off, "on": img_on, "off2": img_off2}


def test_boots(state):
    assert state["debug"][0:4] == b"SFDB"
    assert state["debug"][0x08] == 0x01 and state["debug"][0x09] == 0x00


def test_shadow_regs(state):
    assert state["debug"][0x10] == 0x06, "SHADOW_BGMODE != $06"
    assert state["debug"][0x11] == 0x11, "SHADOW_TM != $11"


def test_screenshot_is_512_wide(state):
    assert state["off"].size[0] == 512, (
        f"Mode 6 screenshot width {state['off'].size[0]} != 512"
    )


def test_hires_per_column_detail(state):
    """RENDERED 512-px proof: high-frequency adjacent-column transitions across
    the content band (the hi-res main/sub split)."""
    img = state["off"]
    w, h = img.size
    transitions = 0
    for y in range(h // 3, 2 * h // 3, 4):
        prev = img.getpixel((0, y))
        for x in range(1, w):
            cur = img.getpixel((x, y))
            if cur != prev:
                transitions += 1
            prev = cur
    assert transitions > 200, (
        f"too few per-column transitions ({transitions}) — hi-res split "
        "did not render"
    )


def test_opt_warp_changes_render(state):
    """RENDERED proof of OPT: warp-on differs measurably from warp-off."""
    n = _diff(state["off"], state["on"])
    assert n > 80, f"OPT warp frame-diff too small ({n} px)"


def test_warp_reverses(state):
    n_off_on = _diff(state["off"], state["on"])
    n_off_off2 = _diff(state["off"], state["off2"])
    assert n_off_off2 < n_off_on, (
        f"warp did not revert: off↔off2 {n_off_off2} not < off↔on {n_off_on}"
    )
