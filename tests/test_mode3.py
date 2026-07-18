"""Dispatcher Mode 3 (256-colour / 8bpp BG1) render gate.

Proves engine_gfxmode(3) renders a smooth 256-colour ramp via an 8bpp BG1 tile
+ a CGRAM[N]=N palette. Primary evidence: a horizontal screenshot scan across
the on-screen ramp strip shows many DISTINCT colours (a smooth gradient), which
only renders if the 8bpp path + 256-entry CGRAM both work. CGRAM destination
bytes are cross-checked directly.

ROM contract (tests/mode3_test.asm): 4 ramp tiles (values 0..255) at tile cols
14..17, rows 12..15 → on-screen x≈112..143, y≈96..127. $7E:E008=1,
$7E:E010=SHADOW_BGMODE ($03), $7E:E011=SHADOW_TM ($13).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
CG = MemoryType.SnesCgRam
SHOTS = Path("/tmp/e2e_screenshots")

STRIP_Y = 110           # inside the ramp strip (rows 12..15 → y 96..127)
STRIP_X0 = 112          # tile col 14 left edge
STRIP_X1 = 144          # tile col 18 right edge (exclusive)


@pytest.fixture(scope="module")
def state():
    rom = BUILD / "mode3_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode3_test` first"
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))
        cgram = bytes(r.read_bytes(CG, 0, 512))
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / "mode3.png"
        r.take_screenshot(str(path))
        img = Image.open(path).convert("RGB")
    finally:
        r.stop()
    return {"debug": debug, "cgram": cgram, "img": img}


def test_boots(state):
    assert state["debug"][0:4] == b"SFDB"
    assert state["debug"][0x08] == 0x01 and state["debug"][0x09] == 0x00


def test_shadow_regs(state):
    assert state["debug"][0x10] == 0x03, "SHADOW_BGMODE != $03"
    assert state["debug"][0x11] == 0x13, "SHADOW_TM != $13"


def test_ramp_renders_many_distinct_colours(state):
    """RENDERED proof: a horizontal scan across the ramp strip yields many
    distinct colours — the 8bpp + 256-CGRAM smooth gradient. A flat block (mode
    failed to render the 8bpp tiles) would give 1-2 colours."""
    img = state["img"]
    seen = set()
    for x in range(STRIP_X0, STRIP_X1):
        seen.add(img.getpixel((x, STRIP_Y)))
    assert len(seen) >= 24, (
        f"ramp strip only {len(seen)} distinct colours across "
        f"x[{STRIP_X0}:{STRIP_X1}] — 8bpp ramp did not render"
    )


def test_ramp_is_gradient_not_noise(state):
    """The strip's left half and right half differ (the ramp climbs), and the
    strip is not the black backdrop."""
    img = state["img"]
    left = img.getpixel((STRIP_X0 + 2, STRIP_Y))
    right = img.getpixel((STRIP_X1 - 3, STRIP_Y))
    assert left != right, f"ramp flat: left {left} == right {right}"
    assert max(left) > 10 or max(right) > 10, "ramp strip is all black backdrop"


def test_cgram_ramp_bytes(state):
    """CGRAM[N]=N landed: spot-check a few mid/high entries (byte index = N*2,
    low byte = N, high byte = 0)."""
    cg = state["cgram"]
    for n in (1, 64, 127, 200, 255):
        assert cg[n * 2] == n and cg[n * 2 + 1] == 0, (
            f"CGRAM[{n}] != {n}: got {cg[n*2]:02X}{cg[n*2+1]:02X}"
        )
