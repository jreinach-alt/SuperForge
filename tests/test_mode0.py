"""Run-gate for the all-modes gfxmode dispatcher, Mode 0 path.

Proves engine_gfxmode(0) configures the PPU so four independent BG layers
RENDER. Primary evidence is rendered screenshot pixels (one per screen
quadrant) plus the CGRAM destination bytes the ROM uploaded — never a proxy
variable. The shadow-register reads (SHADOW_BGMODE/SHADOW_TM) are a structural
cross-check, not the render proof.

ROM contract (tests/mode0_test.asm):
  4 × 2bpp BG layers, one per quadrant; BG1 red (UL), BG2 green (UR),
  BG3 blue (LL), BG4 yellow (LR). $7E:E000="SFDB", $7E:E008=1 on completion,
  $7E:E010=SHADOW_BGMODE (expect $00), $7E:E011=SHADOW_TM (expect $1F).
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

# Quadrant pixel-sample coordinates (256x224 visible region).
QUAD_BG1 = (60, 50)     # upper-left  — RED
QUAD_BG2 = (200, 50)    # upper-right — GREEN
QUAD_BG3 = (60, 160)    # lower-left  — BLUE
QUAD_BG4 = (200, 160)   # lower-right — YELLOW (R+G)


@pytest.fixture(scope="module")
def state():
    rom = BUILD / "mode0_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode0_test` first"
    r = MesenRunner()
    try:
        r.load_rom(str(rom), run_seconds=0.5)
        debug = bytes(r.read_bytes(WR, 0xE000, 0x20))
        cgram = bytes(r.read_bytes(CG, 0, 256))
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / "mode0.png"
        r.take_screenshot(str(path))
        img = Image.open(path).convert("RGB")
    finally:
        r.stop()
    return {"debug": debug, "cgram": cgram, "img": img}


def _dom(rgb):
    r, g, b = rgb
    t = 100
    if r > t and g > t and b < 50:
        return "Y"
    if r > t and g < 50 and b < 50:
        return "R"
    if r < 50 and g > t and b < 50:
        return "G"
    if r < 50 and g < 50 and b > t:
        return "B"
    return f"OTHER:{rgb}"


def test_boots(state):
    assert state["debug"][0:4] == b"SFDB"
    assert state["debug"][0x08] == 0x01 and state["debug"][0x09] == 0x00


def test_shadow_regs(state):
    # Structural cross-check: BGMODE=$00, TM=$1F (BG1+BG2+BG3+BG4+OBJ).
    assert state["debug"][0x10] == 0x00, "SHADOW_BGMODE != $00"
    assert state["debug"][0x11] == 0x1F, "SHADOW_TM != $1F"


# --- RENDERED-OUTPUT proof: four quadrants show four distinct colours. ---

def test_bg1_quadrant_red(state):
    px = state["img"].getpixel(QUAD_BG1)
    assert _dom(px) == "R", f"BG1 quadrant {QUAD_BG1} = {px}"


def test_bg2_quadrant_green(state):
    px = state["img"].getpixel(QUAD_BG2)
    assert _dom(px) == "G", f"BG2 quadrant {QUAD_BG2} = {px}"


def test_bg3_quadrant_blue(state):
    px = state["img"].getpixel(QUAD_BG3)
    assert _dom(px) == "B", f"BG3 quadrant {QUAD_BG3} = {px}"


def test_bg4_quadrant_yellow(state):
    px = state["img"].getpixel(QUAD_BG4)
    assert _dom(px) == "Y", f"BG4 quadrant {QUAD_BG4} = {px}"


# --- CGRAM destination bytes the ROM uploaded landed (per-layer ramp tops). ---

def test_cgram_ramps_loaded(state):
    cg = state["cgram"]
    # bright red @ color 3 = $001F (bytes 6,7)
    assert cg[6] == 0x1F and cg[7] == 0x00, "BG1 red ramp top wrong"
    # bright green @ color 35 = $03E0 (bytes 70,71)
    assert cg[70] == 0xE0 and cg[71] == 0x03, "BG2 green ramp top wrong"
    # bright blue @ color 67 = $7C00 (bytes 134,135)
    assert cg[134] == 0x00 and cg[135] == 0x7C, "BG3 blue ramp top wrong"
    # bright yellow @ color 99 = $03FF (bytes 198,199)
    assert cg[198] == 0xFF and cg[199] == 0x03, "BG4 yellow ramp top wrong"
