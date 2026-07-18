"""Run-gate for the text macros: font upload, print, decimal conversion.

Reads the real outputs: the VRAM font bytes at the BG3 CHR slot, the VRAM BG3
tilemap words the NMI committed, the decimal-conversion buffers, and the
rendered white text pixels on screen.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam

_WHITE = lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "text_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


def test_boots_and_completes(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE008) == 1


def test_font_state_initialized(runner):
    assert runner.read_u16(WR, 0xE014) == 160, "FONT_BASE_TILE != 160"
    assert runner.read_bytes(WR, 0xE016, 1)[0] == 0, "VWF_ACTIVE != 0 (mono)"


def test_font_uploaded_to_vram(runner):
    # 'H' = tile 200 (160 + $48-$20). BG3 CHR base word $2000, 2bpp tile =
    # 8 words -> 'H' at word $2640 = byte $4C80. Glyph rows BP0=BP1=bitmap.
    h = runner.read_bytes(VR, 0x4C80, 16)
    expect = bytes.fromhex("424242427e7e42424242424200000000")
    assert h == expect, f"'H' glyph bytes wrong in VRAM: {h.hex()}"


def test_print_writes_tilemap(runner):
    # shadow words recorded by the ROM
    assert runner.read_u16(WR, 0xE010) == 0x3CC8  # 'H' pal 7
    assert runner.read_u16(WR, 0xE012) == 0x3CC9  # 'I'
    assert runner.read_u16(WR, 0xE018) == 0x3CD3  # 'S' of SCORE at (1,2)
    # the NMI must commit the shadow to the real BG3 tilemap (VRAM word $6000)
    vram_h = runner.read_u16(VR, 0xC000)          # byte addr of word $6000
    assert vram_h == 0x3CC8, f"VRAM BG3 tilemap (0,0) = {vram_h:04x}, want 3cc8"
    vram_s = runner.read_u16(VR, 0xC000 + 2 * 64 + 2)
    assert vram_s == 0x3CD3, f"VRAM BG3 tilemap (1,2) = {vram_s:04x}, want 3cd3"


def test_decimal_conversion_edges(runner):
    cases = [(0xE020, b"00000\x00"), (0xE028, b"00042\x00"),
             (0xE030, b"10000\x00"), (0xE038, b"65535\x00")]
    for addr, want in cases:
        got = runner.read_bytes(WR, addr, 6)
        assert got == want, f"dec5 @ {addr:04x}: {got!r} != {want!r}"


def test_print_u16_writes_digit_tiles(runner):
    assert runner.read_u16(WR, 0xE040) == 0x3CB1  # '1'
    assert runner.read_u16(WR, 0xE042) == 0x3CB2  # '2'
    assert runner.read_u16(WR, 0xE044) == 0x3CB5  # '5'


def test_text_renders_above_bg1(runner):
    # composited priority: BG1 green cells sit exactly under "HI" — the white
    # glyphs must render ON TOP (the print macros set the BG3 priority bit;
    # without it Mode 1 occludes unflagged BG3 behind BG1), and green must
    # show through the glyph gaps (proving BG1 is really there underneath).
    runner.take_screenshot("/tmp/_text_prio.png")
    img = Image.open("/tmp/_text_prio.png").convert("RGB")
    w = img.size[0]
    d = list(img.getdata())
    region = [d[y * w + x] for y in range(0, 15) for x in range(0, 16)]
    white = sum(1 for p in region if _WHITE(p))
    green = sum(1 for p in region if p[0] < 90 and p[1] > 150 and p[2] < 90)
    assert white > 15, f"text occluded by BG1: {white} white px under 'HI'"
    assert green > 15, f"BG1 underlay missing: {green} green px (test invalid)"


def test_text_renders_white_pixels(runner):
    runner.take_screenshot("/tmp/_text0.png")
    img = Image.open("/tmp/_text0.png").convert("RGB")
    w, h = img.size
    d = list(img.getdata())
    # white pixels in the printed rows (y 0-40 covers tile rows 0, 2, 4)
    top = sum(1 for y in range(0, 41) for x in range(w) if _WHITE(d[y * w + x]))
    assert top > 100, f"printed text not visible: {top} white pixels in rows 0-40"
    # and nothing below — text must not bleed outside where we printed
    below = sum(1 for y in range(60, h) for x in range(w) if _WHITE(d[y * w + x]))
    assert below == 0, f"unexpected white pixels below the text: {below}"
