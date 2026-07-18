"""Done-conditions for the camera_follow template.

Per the discipline: verifies the rendered result (BG + sprite visible) and the
camera-follow behaviour on BOTH axes — while mid-world the camera TRACKS (the
sprite holds screen-centre as the BG scrolls), and at the world edge the camera
and player CLAMP (the sprite moves to the on-screen edge, stays on screen).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

PWX, PWY, CAM_X, CAM_Y = 0x32, 0x34, 0x36, 0x38

_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90
_GREEN = lambda p: p[0] < 120 and p[1] > 120 and p[2] < 120


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rom():
    p = BUILD / "camera_follow.sfc"
    assert p.exists(), f"{p} not built — run `make camera_follow` first"
    return str(p)


def _sprite(r):
    b = r.read_bytes(OAM, 0, 4)
    return b[0], b[1]


def test_boots_centered(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.take_screenshot("/tmp/_cf.png")
    img = Image.open("/tmp/_cf.png").convert("RGB")
    assert sum(1 for p in img.getdata() if _GREEN(p)) > 2000, "BG not visible"
    assert 56 <= sum(1 for p in img.getdata() if _RED(p)) <= 72, "sprite not visible"
    # player at world centre (256,224) -> camera (128,112), sprite screen-centred
    assert runner.read_u16(WR, CAM_X) == 128 and runner.read_u16(WR, CAM_Y) == 112
    assert _sprite(runner) == (128, 112)


# axis: (label, input, camera-reg, sprite-axis index, track-stays-near)
_AXES = [
    ("right", dict(right=True), CAM_X, 0, 128, 256),   # cam clamps at 256
    ("left", dict(left=True), CAM_X, 0, 128, 0),       # cam clamps at 0
    ("down", dict(down=True), CAM_Y, 1, 112, 224),     # cam clamps at 224
    ("up", dict(up=True), CAM_Y, 1, 112, 0),
]


@pytest.mark.parametrize("name,kw,cam_reg,axis,center,clamp_to", _AXES)
def test_camera_tracks_then_clamps(runner, name, kw, cam_reg, axis, center, clamp_to):
    # --- tracking: a moderate move scrolls the camera but holds the sprite centred ---
    runner.load_rom(_rom(), run_seconds=0.4)
    cam0 = runner.read_u16(WR, cam_reg)
    runner.set_input(0, **kw)
    runner.run_frames(20)
    runner.set_input(0)
    runner.run_frames(2)
    cam_t = runner.read_u16(WR, cam_reg)
    spr_t = _sprite(runner)[axis]
    assert cam_t != cam0, f"{name}: camera did not track ({cam0}->{cam_t})"
    assert abs(spr_t - center) <= 6, f"{name}: sprite left centre while tracking ({spr_t})"

    # --- clamping: drive to the world edge; camera clamps + sprite stays on screen ---
    runner.set_input(0, **kw)
    runner.run_frames(200)
    runner.set_input(0)
    runner.run_frames(2)
    assert runner.read_u16(WR, cam_reg) == clamp_to, f"{name}: camera did not clamp to {clamp_to}"
    spr_e = _sprite(runner)[axis]
    assert spr_e != center and 0 <= spr_e < (256 if axis == 0 else 224), \
        f"{name}: sprite not at on-screen edge after clamp ({spr_e})"
