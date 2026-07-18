"""Mode-1-via-dispatcher smoke — proves the ported @mode1_init superset.

The kit's racer/mode7_flight reach Mode 1 through the bg_engine.asm STUB; this
gate drives the all-modes dispatcher (bg_mode_engine.asm) via gfxmode(1) and
proves the ported @mode1_init produces a WORKING Mode 1 — not just that it set a
shadow byte. Primary evidence: a green BG1 tile renders at the Mode-1 tilemap
address (screenshot pixel). Structural cross-check: SHADOW_TM + the BGMODE low
3 bits.

ROM contract (tests/mode1_test.asm): green 16x14 BG1 block in screen centre.
$7E:E008=1, $7E:E010=SHADOW_BGMODE, $7E:E011=SHADOW_TM (expect $17).
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
    rom = BUILD / "mode1_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode1_test` first"
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / "mode1.png"
        r.take_screenshot(str(path))
        img = Image.open(path).convert("RGB")
    finally:
        r.stop()
    return {"debug": debug, "img": img}


def test_boots(state):
    assert state["debug"][0:4] == b"SFDB"
    assert state["debug"][0x08] == 0x01 and state["debug"][0x09] == 0x00


def test_shadow_regs(state):
    # Mode 1 in the low 3 bits (bit 3 = BG3 priority, set by the port to match
    # the stub); TM = $17 (OBJ + BG1 + BG2 + BG3).
    assert (state["debug"][0x10] & 0x07) == 0x01, "BGMODE low 3 bits != Mode 1"
    assert state["debug"][0x11] == 0x17, "SHADOW_TM != $17"


def test_bg1_tile_renders_green(state):
    """RENDERED proof: the centre BG1 block is green. If @mode1_init failed to
    program BG1SC/BG12NBA/TM, the centre would be backdrop black, not green."""
    img = state["img"]
    w, h = img.size
    px = img.getpixel((w // 2, h // 2))
    r, g, b = px
    assert g > 100 and r < 80 and b < 80, f"centre not green: {px}"


def test_corner_is_backdrop(state):
    """Outside the BG1 block (top-left corner) is the black backdrop — confirms
    the tilemap is selective, not a full-screen fill artifact."""
    img = state["img"]
    px = img.getpixel((8, 8))
    assert max(px) < 80, f"corner not backdrop-dark: {px}"
