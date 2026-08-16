"""microzero — the title scene, built entirely through the allocator,
boots and RENDERS: VRAM tile words at allocator-assigned addresses match the
declared strings exactly, CGRAM carries the declared palette, the screenshot
has exactly the declared structure (backdrop + white glyphs, zero strays),
the frame heartbeat runs, and the uninit-read detector stays clean (contract
init only — no blanket clears). Every address comes from symbol_map.json.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

VR, CG, WR = MemoryType.SnesVideoRam, MemoryType.SnesCgRam, MemoryType.SnesWorkRam

TXT_ATTR = (7 << 10) | (1 << 13)          # title.asm's BG3 palette-7 attr


def glyph_words(s: str) -> list[int]:
    return [TXT_ATTR | (ord(c) - 0x20) for c in s]


@pytest.fixture(scope="module")
def built():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["title"]["placements"] + jmap["globals"]}
    return syms


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module")
def booted(built, runner):
    runner.load_rom_with_uninit_detection(
        str(SUPERFORGE / "build" / "microzero.sfc"), frames=120)
    return built


def test_heartbeat_runs(booted, runner):
    frame = booted["ES_SM_FRAME"]["start"]
    f0 = runner.read_u16(WR, frame)
    runner.wait_frames(10)
    f1 = runner.read_u16(WR, frame)
    assert f1 != f0, "frame counter frozen — NMI heartbeat dead"
    t = booted["US_T_FRAMES"]["start"]
    t0 = runner.read_u16(WR, t)
    runner.wait_frames(10)
    assert runner.read_u16(WR, t) != t0, "scene tick not running"


def test_title_strings_rendered_in_vram(booted, runner):
    base = booted["ES_V_TEXT_MAP"]["start"]
    for row, col, s in ((6, 11, "MICROZERO"), (14, 10, "PRESS START"),
                        (20, 6, "SCORE "), (20, 17, "LIVES ")):
        addr = (base + row * 32 + col) * 2
        got = runner.read_bytes(VR, addr, len(s) * 2)
        want = b"".join(w.to_bytes(2, "little") for w in glyph_words(s))
        assert got == want, f"row {row} text mismatch: {got.hex()} != {want.hex()}"
    # the surviving-global-state render: score 0000, lives 3
    score = runner.read_bytes(VR, (base + 20 * 32 + 12) * 2, 8)
    assert score == b"".join(w.to_bytes(2, "little") for w in glyph_words("0000"))
    lives = runner.read_bytes(VR, (base + 20 * 32 + 23) * 2, 2)
    assert lives == glyph_words("3")[0].to_bytes(2, "little")


def test_font_glyphs_uploaded(booted, runner):
    font = booted["ES_V_TEXT_CHR"]["start"]
    # glyph 'M' (index $2D), row 0 must be nonzero and BP0 == BP1 (mono font)
    tile = runner.read_bytes(VR, (font + (ord("M") - 0x20) * 8) * 2, 16)
    assert any(tile), "font CHR empty"
    assert all(tile[i] == tile[i + 1] for i in range(0, 16, 2)), \
        "mono font planes must match"


def test_cgram_declared_palette(booted, runner):
    bd = booted["ES_C_BACKDROP_COLOR"]["start"]
    assert runner.read_u16(CG, bd * 2) == 0x28A0          # deep blue
    tp = booted["ES_C_TEXT_PAL"]["start"]
    got = [runner.read_u16(CG, (tp + i) * 2) for i in range(4)]
    assert got == [0x0000, 0x1084, 0x56B5, 0x7FFF], got


def test_screenshot_exact_structure(booted, runner, tmp_path):
    from PIL import Image
    runner.wait_frames(30)                  # fade-in fully done
    shot = tmp_path / "title.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    img = Image.open(shot).convert("RGB")
    w, h = img.size
    px = img.load()

    def snes_rgb(bgr555):
        r = (bgr555 & 31) << 3 | (bgr555 & 31) >> 2
        g = ((bgr555 >> 5) & 31) << 3 | ((bgr555 >> 5) & 31) >> 2
        b = ((bgr555 >> 10) & 31) << 3 | ((bgr555 >> 10) & 31) >> 2
        return (r, g, b)

    backdrop, white = snes_rgb(0x28A0), snes_rgb(0x7FFF)
    allowed = {(0, 0, 0), backdrop, white}
    stray = {p for r in range(h) for p in [px[0, r]] } | \
            {img.getpixel((x, y)) for y in range(h) for x in range(w)} - allowed
    stray -= allowed
    assert not stray, f"stray colors: {sorted(stray)[:8]}"
    # Map row r covers scanlines r*8..r*8+7. The +6 is the letterbox border,
    # and the extra line comes from BGnVOFS, not from an unrendered scanline:
    # screen line N shows BG row N+1, so a map row's glyphs land one screen
    # line lower. (The old comment said "scanline 0 unrendered" — the
    # refuted model; the frame has 224 rendered scanlines. Right constant,
    # wrong reason; a later review.)
    def row_has_white(r):
        return any(img.getpixel((x, y)) == white
                   for y in range(r * 8 + 6, r * 8 + 14) for x in range(w))
    assert row_has_white(6), "logo row has no glyph pixels"
    assert row_has_white(14), "press-start row has no glyph pixels"
    assert not row_has_white(10), "empty row unexpectedly has glyphs"


def test_no_uninitialized_reads(booted, runner):
    runner.wait_frames(30)
    runner.assert_no_uninitialized_reads()
