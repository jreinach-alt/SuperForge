"""Dispatcher Mode 4 (8bpp BG1 + offset-per-tile) render gate.

Mode 4 combines Mode 3's 8bpp richness with Mode 2's OPT. This gate proves BOTH
render: a smooth 8bpp colour ramp on screen AND a controller-toggled tile-column
OPT warp. Evidence is rendered pixels — a ramp-row distinct-colour count plus a
warp-on/off frame diff — never a proxy.

ROM contract (tests/mode4_test.asm): 8bpp ramp tiles repeating across rows
10..17; A released = flat, A held = column N shifted N*8 px (NMI flushes OPT).
$7E:E008=1, $7E:E010=SHADOW_BGMODE ($04), $7E:E011=SHADOW_TM ($13).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

# Ramp region (rows 10..17 → y 80..143).
RAMP_Y = 100
RX0, RX1 = 16, 240
RY0, RY1 = 84, 140


def _diff(a, b):
    n = 0
    for y in range(RY0, RY1, 2):
        for x in range(RX0, RX1, 2):
            if a.getpixel((x, y)) != b.getpixel((x, y)):
                n += 1
    return n


@pytest.fixture(scope="module")
def state():
    rom = BUILD / "mode4_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode4_test` first"
    SHOTS.mkdir(parents=True, exist_ok=True)
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))

        r.set_input(0)
        r.run_frames(12)
        p_off = SHOTS / "mode4_off.png"
        r.take_screenshot(str(p_off))
        img_off = Image.open(p_off).convert("RGB")

        r.set_input(0, a=True)
        r.run_frames(12)
        p_on = SHOTS / "mode4_on.png"
        r.take_screenshot(str(p_on))
        img_on = Image.open(p_on).convert("RGB")

        r.set_input(0)
        r.run_frames(12)
        p_off2 = SHOTS / "mode4_off2.png"
        r.take_screenshot(str(p_off2))
        img_off2 = Image.open(p_off2).convert("RGB")
    finally:
        r.stop()
    return {"debug": debug, "off": img_off, "on": img_on, "off2": img_off2}


def test_boots(state):
    assert state["debug"][0:4] == b"SFDB"
    assert state["debug"][0x08] == 0x01 and state["debug"][0x09] == 0x00


def test_shadow_regs(state):
    assert state["debug"][0x10] == 0x04, "SHADOW_BGMODE != $04"
    assert state["debug"][0x11] == 0x13, "SHADOW_TM != $13"


def test_8bpp_ramp_richness(state):
    """RENDERED proof of the 8bpp richness: a horizontal scan across the ramp
    rows shows many distinct colours."""
    img = state["off"]
    seen = set()
    for x in range(RX0, RX1):
        seen.add(img.getpixel((x, RAMP_Y)))
    assert len(seen) >= 24, f"8bpp ramp only {len(seen)} distinct colours"


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
