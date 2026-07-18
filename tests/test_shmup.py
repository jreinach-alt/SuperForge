"""Done-conditions for the shmup template (converted art + pools + autoscroll).

Per the discipline: verifies the RENDERED result (ship/ghost/terrain pixels,
HUD digits) alongside the WRAM/OAM ground truth, drives all four movement
directions, and plays a full kill: fire -> bullet travels -> ghost dies ->
SCORE increments on screen. Event-driven polling (spawn timing is frame-based
and the emulator free-runs).

Stable-OAM-slot contract under test: slot 0 = ship, 1-6 = bullets, 7-10 =
ghosts (every pool slot drawn every frame, dead at y=$F0).
"""
import time
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

PX, PY, SCORE = 0x32, 0x34, 0x36
BUL_ALIVE, BUL_X, BUL_Y = 0x1800, 0x1810, 0x1820
ENE_ALIVE, ENE_X, ENE_Y = 0x1830, 0x1840, 0x1850
VOFS = 0x0122


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rom():
    p = ROOT / "build" / "shmup.sfc"
    assert p.exists(), f"{p} not built — run `make shmup` first"
    return str(p)


def _shot(r, path="/tmp/_shmup.png"):
    r.take_screenshot(path)
    return Image.open(path).convert("RGB")


def _oam(r, slot):
    b = r.read_bytes(OAM, slot * 4, 4)
    return b[0], b[1], b[2], b[3]


def _wait(r, cond, frames=240, step=4, what="condition"):
    for _ in range(0, frames, step):
        if cond():
            return
        r.run_frames(step)
    pytest.fail(f"timed out waiting for {what}")


def _region_colors(img, x0, y0, x1, y1):
    return {img.getpixel((x, y)) for y in range(y0, y1) for x in range(x0, x1)}


def test_boots_renders_world_ship_and_hud(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    img = _shot(runner)
    # terrain islands visible: the spring grass green + plenty of non-black
    nonblack = sum(1 for p in img.getdata() if sum(p) > 40)
    assert nonblack > 5000, "terrain islands not visible"
    # the ship renders at its OAM position (slot 0): some opaque hero pixels
    sx, sy = _oam(runner, 0)[:2]
    ship_px = _region_colors(img, sx, sy, min(sx + 16, 256), min(sy + 18, 239))
    assert any(sum(p) > 100 for p in ship_px), "ship sprite not visible on screen"
    # HUD row shows text pixels (white font on BG3)
    hud = _region_colors(img, 8, 8, 120, 24)
    assert any(p[0] > 200 and p[1] > 200 and p[2] > 200 for p in hud), \
        "SCORE HUD not visible"


def test_terrain_autoscrolls_down(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    v1 = runner.read_u16(WR, VOFS)
    img1 = _shot(runner)
    runner.run_frames(20)
    v2 = runner.read_u16(WR, VOFS)
    img2 = _shot(runner)
    delta = (v1 - v2) & 0xFFFF
    assert 0 < delta < 200, f"VOFS not decreasing ({v1:#06x}->{v2:#06x})"
    # the rendered island pattern moved: row-profile at a column crossing
    # islands (x=40) must change between shots
    rows1 = frozenset(y for y in range(40, 220)
                      if sum(img1.getpixel((40, y))) > 40)
    rows2 = frozenset(y for y in range(40, 220)
                      if sum(img2.getpixel((40, y))) > 40)
    assert rows1 and rows1 != rows2, "terrain pixels did not move"


def test_ship_moves_all_four_directions_clamped(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    for name, kw, axis, sign in [
        ("right", dict(right=True), PX, +1),
        ("left", dict(left=True), PX, -1),
        ("down", dict(down=True), PY, +1),
        ("up", dict(up=True), PY, -1),
    ]:
        p0 = runner.read_u16(WR, axis)
        runner.set_input(0, **kw)
        runner.run_frames(12)
        runner.set_input(0)
        runner.run_frames(2)
        p1 = runner.read_u16(WR, axis)
        assert (p1 - p0) * sign > 0, f"{name}: ship did not move ({p0}->{p1})"
        # the rendered sprite follows (OAM slot 0 + hero pixels there)
        ox, oy = _oam(runner, 0)[:2]
        assert abs(ox - runner.read_u16(WR, PX)) <= 2
        img = _shot(runner)
        ship_px = _region_colors(img, ox, oy, min(ox + 16, 256), min(oy + 18, 239))
        assert any(sum(p) > 100 for p in ship_px), f"{name}: ship not rendered"
    # clamps hold: drive far left and far up
    runner.set_input(0, left=True, up=True)
    runner.run_frames(150)
    runner.set_input(0)
    runner.run_frames(2)
    assert runner.read_u16(WR, PX) == 8, "left clamp"
    assert runner.read_u16(WR, PY) == 32, "top clamp (HUD protected)"


def test_fire_spawns_bullet_that_travels_up_and_expires(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    assert runner.read_u16(WR, BUL_ALIVE) == 0
    runner.set_input(0, a=True)
    runner.run_frames(3)
    runner.set_input(0)
    _wait(runner, lambda: runner.read_u16(WR, BUL_ALIVE) == 1, 60,
          what="bullet spawn")
    y1 = runner.read_u16(WR, BUL_Y)
    # OAM slot 1 is this bullet (stable slots), and it renders
    runner.run_frames(6)
    y2 = runner.read_u16(WR, BUL_Y)
    assert y2 < y1, f"bullet not travelling up ({y1}->{y2})"
    ox, oy = _oam(runner, 1)[:2]
    assert abs(oy - runner.read_u16(WR, BUL_Y)) <= 8, "OAM slot 1 not the bullet"
    _wait(runner, lambda: runner.read_u16(WR, BUL_ALIVE) == 0, 120,
          what="bullet expiry at the top")
    assert _oam(runner, 1)[1] == 0xF0, "dead bullet slot must park at y=$F0"


def test_ghost_spawns_at_table_column_and_descends(runner):
    runner.load_rom(_rom(), run_seconds=0.4)
    _wait(runner, lambda: runner.read_u16(WR, ENE_ALIVE) == 1, 120,
          what="first ghost spawn")
    assert runner.read_u16(WR, ENE_X) == 24, "first spawn column (table entry 0)"
    y1 = runner.read_u16(WR, ENE_Y)
    runner.run_frames(20)
    y2 = runner.read_u16(WR, ENE_Y)
    assert y2 > y1, f"ghost not descending ({y1}->{y2})"
    # OAM slot 7 = ghost 0, rendered with ghost pixels at its position
    ox, oy = _oam(runner, 7)[:2]
    assert ox == 24
    img = _shot(runner)
    gpx = _region_colors(img, ox, oy, min(ox + 16, 256), min(oy + 18, 239))
    assert any(sum(p) > 100 for p in gpx), "ghost not rendered"


def test_bullet_kills_ghost_and_score_renders(runner):
    runner.load_rom(_rom(), run_seconds=0.4)
    assert runner.read_u16(WR, SCORE) == 0
    img_before = _shot(runner)
    hud_before = [img_before.getpixel((x, y)) for y in range(8, 26)
                  for x in range(56, 100)]
    # park the ship under the first spawn column (24): ghost spans 24..40,
    # bullets fire from PX+4 -> PX=24 puts them at 28..36
    runner.set_input(0, left=True)
    _wait(runner, lambda: runner.read_u16(WR, PX) <= 24, 120, what="ship at x<=24")
    runner.set_input(0)
    runner.run_frames(2)
    # pulse A (rising edges) until the kill lands
    deadline = time.time() + 12
    while runner.read_u16(WR, SCORE) == 0 and time.time() < deadline:
        runner.set_input(0, a=True)
        runner.run_frames(2)
        runner.set_input(0)
        runner.run_frames(4)
    assert runner.read_u16(WR, SCORE) >= 1, "no kill registered (SCORE still 0)"
    runner.run_frames(4)
    # the HUD digits RE-RENDERED (rendered-result check, not just the variable)
    img_after = _shot(runner)
    hud_after = [img_after.getpixel((x, y)) for y in range(8, 26)
                 for x in range(56, 100)]
    assert hud_after != hud_before, "SCORE changed but the HUD did not re-render"
