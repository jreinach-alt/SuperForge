"""Dispatcher Mode 2 (offset-per-tile / OPT) render gate.

Proves engine_gfxmode(2) + the offset engine warp the BG1 checkerboard. The
state cycle is OPT-off vs OPT-on, driven by controller input; the assertion
frame-diffs the two RENDERED frames over the checkerboard region. A proxy on
the shadow buffer is explicitly avoided — a uniform tilemap looks identical
under any offset, so only the rendered pixels prove the warp.

ROM contract (tests/mode2_test.asm): 2D checkerboard BG1; A released → flat,
A held → column N shifted by N*8 px (NMI flushes the OPT shadow each frame).
$7E:E008=1, $7E:E010=SHADOW_BGMODE ($02), $7E:E011=SHADOW_TM ($13).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

# Checkerboard region to diff (avoid overscan border).
RX0, RX1 = 32, 224
RY0, RY1 = 40, 180


def _diff(a, b):
    n = 0
    for y in range(RY0, RY1, 2):
        for x in range(RX0, RX1, 2):
            if a.getpixel((x, y)) != b.getpixel((x, y)):
                n += 1
    return n


@pytest.fixture(scope="module")
def state():
    rom = BUILD / "mode2_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode2_test` first"
    SHOTS.mkdir(parents=True, exist_ok=True)
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))

        # State 1: OPT off (A released) — flat checkerboard.
        r.set_input(0)
        r.run_frames(12)
        p_off = SHOTS / "mode2_off.png"
        r.take_screenshot(str(p_off))
        img_off = Image.open(p_off).convert("RGB")

        # State 2: OPT on (A held) — warped checkerboard.
        r.set_input(0, a=True)
        r.run_frames(12)
        p_on = SHOTS / "mode2_on.png"
        r.take_screenshot(str(p_on))
        img_on = Image.open(p_on).convert("RGB")

        # State 3: back to OPT off — confirm the warp is reversible.
        r.set_input(0)
        r.run_frames(12)
        p_off2 = SHOTS / "mode2_off2.png"
        r.take_screenshot(str(p_off2))
        img_off2 = Image.open(p_off2).convert("RGB")
    finally:
        r.stop()
    return {"debug": debug, "off": img_off, "on": img_on, "off2": img_off2}


def test_boots(state):
    assert state["debug"][0:4] == b"SFDB"
    assert state["debug"][0x08] == 0x01 and state["debug"][0x09] == 0x00


def test_shadow_regs(state):
    assert state["debug"][0x10] == 0x02, "SHADOW_BGMODE != $02"
    assert state["debug"][0x11] == 0x13, "SHADOW_TM != $13"


def test_checkerboard_renders(state):
    """The flat checkerboard renders red+blue tiles (not a black backdrop)."""
    img = state["off"]
    colours = set()
    for x in range(RX0, RX1, 4):
        colours.add(img.getpixel((x, 100)))
    # Expect at least 2 distinct non-black colours.
    bright = [c for c in colours if max(c) > 40]
    assert len(bright) >= 2, f"checkerboard did not render: {colours}"


def test_opt_warp_changes_render(state):
    """RENDERED proof of OPT: the A-held (warped) frame differs measurably from
    the A-released (flat) frame across the checkerboard region."""
    n = _diff(state["off"], state["on"])
    assert n > 80, f"OPT warp produced too small a frame-diff ({n} px)"


def test_warp_reverses(state):
    """Releasing A reverts the warp — off2 matches off far more closely than
    on did (the state cycle is reversible, not a one-way change)."""
    n_off_on = _diff(state["off"], state["on"])
    n_off_off2 = _diff(state["off"], state["off2"])
    assert n_off_off2 < n_off_on, (
        f"warp did not revert: off↔off2 diff {n_off_off2} not < "
        f"off↔on diff {n_off_on}"
    )
