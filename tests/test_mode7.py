"""Run-gate for the Mode 7 macros: the perspective floor renders and steers.

Reads the real outputs: the rendered pixels (perspective compression below
the horizon, rotation under LEFT), the per-scanline matrix HDMA table in
WRAM, and the debug-region heartbeat. The proven racing-camera parameters
(l0=96, l1=224, s0=192, s1=24, sh=16, interp=2, wrap=1, focus 192) over a
16x16px two-green checkerboard map.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

HORIZON = 96                    # pv_l0 — the floor starts at this scanline


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rgb(img):
    img = img.convert("RGB")
    w, h = img.size
    return list(img.getdata()), w, h


def _row(data, w, h, y):
    """Pixel row at SNES scanline y (screenshot may carry overscan rows)."""
    yy = int(y * h / 224.0)
    return [data[yy * w + x] for x in range(w)]


def _transitions(row):
    return sum(1 for i in range(1, len(row)) if row[i] != row[i - 1])


def test_mode7_floor_renders_and_steers(runner):
    rom = BUILD / "mode7_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=2.0)

    # --- boots + heartbeat advances ---
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    f1 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    f2 = runner.read_u16(WR, 0xE010)
    assert f2 > f1 > 0, f"frame heartbeat not advancing: {f1} -> {f2}"

    # --- the per-scanline matrix HDMA table is real: nonzero, VARYING
    # matrix-A coefficients (the perspective ramp). pv_rebuild double-buffers
    # at $7E:A000 / $7E:A900; entries are 4 bytes (A lo, A hi, B lo, B hi).
    def a_coeffs(base):
        raw = runner.read_bytes(WR, base, 256)
        return [raw[i] | (raw[i + 1] << 8) for i in range(0, 256, 4)]

    best = max((a_coeffs(0xA000), a_coeffs(0xA900)),
               key=lambda v: len(set(v) - {0}))
    distinct = set(best) - {0}
    assert len(distinct) >= 8, \
        f"matrix-A HDMA table not a perspective ramp: {sorted(distinct)[:8]}"

    # --- the rendered floor: not a blank/single-colour screen, two checker
    # greens below the horizon, and perspective compression (a row just
    # below the horizon shows far more checker transitions than a row near
    # the bottom of the screen, where the squares render large).
    runner.take_screenshot("/tmp/_m7_0.png")
    d0, w, h = _rgb(Image.open("/tmp/_m7_0.png"))
    floor_colors = set(_row(d0, w, h, 110)) | set(_row(d0, w, h, 200))
    assert len(floor_colors) >= 2, \
        f"floor shows {len(floor_colors)} colour(s) — checkerboard not rendered"
    assert len(set(d0)) >= 2, "screen is uniformly one colour"

    t_far = _transitions(_row(d0, w, h, 104))     # just below the horizon
    t_near = _transitions(_row(d0, w, h, 210))    # near the bottom
    assert t_far > t_near, (
        f"no perspective compression: transitions at scanline 104 = {t_far}, "
        f"at 210 = {t_near} (far rows must show smaller checkers)")
    assert t_far >= 4, f"far floor row barely patterned ({t_far} transitions)"

    # --- steering: hold LEFT 30 frames -> the camera angle advances and the
    # rendered floor visibly rotates (pixels change below the horizon).
    angle0 = runner.read_bytes(WR, 0x01DE, 1)[0]      # M7_PV_ANGLE
    runner.set_input(0, left=True)
    runner.run_frames(30)
    runner.set_input(0)
    angle1 = runner.read_bytes(WR, 0x01DE, 1)[0]
    assert angle1 != angle0, "LEFT did not advance the camera angle"

    runner.take_screenshot("/tmp/_m7_1.png")
    d1, w1, h1 = _rgb(Image.open("/tmp/_m7_1.png"))
    assert (w1, h1) == (w, h)
    y0, y1 = int(100 * h / 224.0), int(220 * h / 224.0)
    region = range(y0 * w, y1 * w)
    diff = sum(1 for i in region if d0[i] != d1[i])
    assert diff > 0.05 * len(region), (
        f"steering did not rotate the rendered floor: only {diff} of "
        f"{len(region)} pixels changed below the horizon")
