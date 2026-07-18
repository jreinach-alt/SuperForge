"""Run-gate for the scrolling-level macros: sf_level.inc.

A 512px ROM level across both hardware pages. Verifies point probes on each
page, the seam-straddling box, a physics landing ON the seam platform, the
clamped camera, and — per the rendered-result rule — that the right-half
world actually draws on screen at a scrolled camera with no BG2 double image.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam

PLAT_REST = 168     # seam platform top (176) - 8

_GREY = lambda p: abs(p[0] - p[1]) < 30 and abs(p[1] - p[2]) < 30 and 80 < p[0] < 200


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "level_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    r.load_rom(str(rom), run_seconds=0.7)
    assert r.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert r.read_u16(WR, 0xE008) == 1
    yield r
    r.stop()


def test_point_probes_both_pages(runner):
    assert runner.read_u16(WR, 0xE010) == 1, "platform point, left page"
    assert runner.read_u16(WR, 0xE012) == 1, "platform point, RIGHT page"
    assert runner.read_u16(WR, 0xE014) == 0, "air point past the platform"
    assert runner.read_u16(WR, 0xE016) == 1, "wall point, right page"


def test_box_straddles_the_seam(runner):
    assert runner.read_u16(WR, 0xE018) == 1, \
        "box with corners on BOTH pages missed the seam platform"
    assert runner.read_u16(WR, 0xE01A) == 0, \
        "box above the platform false-positived"


def test_physics_lands_on_seam_platform(runner):
    t = list(runner.read_bytes(WR, 0xE020, 40))
    assert t[-1] == PLAT_REST, f"final y={t[-1]}, want {PLAT_REST}"
    land = next(i for i, y in enumerate(t) if y == PLAT_REST)
    assert all(y == PLAT_REST for y in t[land:]), "rest not stable on the seam"
    deltas = [b - a for a, b in zip(t, t[1:land + 1])]
    assert all(0 <= d <= 4 for d in deltas), "fall not clamped/monotonic"
    assert runner.read_u16(WR, 0xE048) == 1, "grounded not set on the platform"


def test_camera_clamped_value(runner):
    assert runner.read_u16(WR, 0xE050) == 300 - 128, "cam_x != pwx - 128"


def test_right_half_renders_on_screen(runner):
    # camera at 172: world px 172..427 visible. The col-40 wall (320..327)
    # lands at screen x 148..155; the seam platform (232..287) at 60..115.
    # Both live partly/fully on the RIGHT page — if the page-1 transport
    # didn't reach VRAM, these are black.
    runner.run_frames(10)
    runner.take_screenshot("/tmp/_level0.png")
    img = Image.open("/tmp/_level0.png").convert("RGB")
    w = img.size[0]
    d = list(img.getdata())

    def grey_in(x0, x1, y0, y1):
        return sum(1 for y in range(y0, y1) for x in range(x0, x1)
                   if _GREY(d[y * w + x]))

    assert grey_in(146, 158, 165, 205) > 40, \
        "right-page wall (world col 40) not rendered at the scrolled camera"
    assert grey_in(58, 118, 178, 190) > 100, \
        "seam platform not rendered across the page boundary"
    assert grey_in(0, 256, 215, 230) > 1000, "floor not rendered full-width"


def test_no_bg2_double_image(runner):
    # if the BG2 LAYER were still on the main screen, its copy of the
    # right-half tilemap would render at scroll 0 — putting the col-40 wall
    # ALSO at screen x = (40-32)*8 = 64..71 in rows 160..207 (left of the
    # platform's rows there are air in the real composition).
    runner.take_screenshot("/tmp/_level1.png")
    img = Image.open("/tmp/_level1.png").convert("RGB")
    w = img.size[0]
    d = list(img.getdata())
    ghost = sum(1 for y in range(190, 205) for x in range(64, 72)
                if _GREY(d[y * w + x]))
    assert ghost == 0, f"BG2 double image suspected ({ghost} grey px)"
