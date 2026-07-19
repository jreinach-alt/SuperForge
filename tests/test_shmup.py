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
SPAWN_IX_ADDR, HURTLOCK = 0x3A, 0x54
BUL_ALIVE, BUL_X, BUL_Y = 0x1800, 0x1810, 0x1820
ENE_ALIVE, ENE_X, ENE_Y = 0x1830, 0x1840, 0x1850
LIVES, GAMEOVER = 0x1858, 0x185A
VOFS = 0x0122
SHIP_SPAWN_X, SHIP_SPAWN_Y = 120, 180
SPAWN_XS = [24, 120, 200, 64, 168, 88, 216, 40]  # ghost spawn columns (main.asm)


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


def _white_count(img, x0, y0, x1, y1):
    return sum(1 for y in range(y0, y1) for x in range(x0, x1)
               if all(c > 200 for c in img.getpixel((x, y))))


def _fly_into_ghost(r, max_frames=900):
    """Drive the ship INTO a ghost. Pre-positions it at the predicted next spawn
    column (SPAWN_IX -> SPAWN_XS) while hugging the top, so the next ghost spawns
    right onto it. Stops input the frame LIVES drops -> the respawn reads cleanly.
    Returns True on contact."""
    lives0 = r.read_u16(WR, LIVES)
    for _ in range(max_frames):
        target = SPAWN_XS[r.read_u16(WR, SPAWN_IX_ADDR) & 7]
        px = r.read_u16(WR, PX)
        kw = dict(up=True)
        if px + 2 < target:
            kw["right"] = True
        elif px - 2 > target:
            kw["left"] = True
        r.set_input(0, **kw)
        r.run_frames(1)
        if r.read_u16(WR, LIVES) < lives0:
            r.set_input(0)
            return True
    r.set_input(0)
    return False


def test_boots_renders_world_ship_and_hud(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    img = _shot(runner)
    # terrain islands visible: count BRIGHT pixels (sum>180) — the tan/green tiles
    # sit well above the night-sky navy backdrop (~sum 90), so this tracks the
    # terrain itself, not the (deliberately non-black) sky.
    terrain = sum(1 for p in img.getdata() if sum(p) > 180)
    assert terrain > 5000, "terrain islands not visible"
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
    # islands (x=40) must change between shots. Threshold sum>180 tracks the
    # bright terrain tiles (islands >=238) and excludes the night-sky navy
    # backdrop (<=131), so this proves the TERRAIN moved, not the static sky.
    rows1 = frozenset(y for y in range(40, 220)
                      if sum(img1.getpixel((40, y))) > 180)
    rows2 = frozenset(y for y in range(40, 220)
                      if sum(img2.getpixel((40, y))) > 180)
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


def test_ghost_contact_costs_a_ship_with_blink_and_respawn(runner):
    """Fly the ship into a ghost: it costs a life, respawns at spawn, and blinks
    through i-frames. Rendered-result check: OAM slot 0 toggles drawn/parked."""
    runner.load_rom(_rom(), run_seconds=0.6)
    assert runner.read_u16(WR, LIVES) == 3, "starts with three ships"
    assert _fly_into_ghost(runner), "never collided with a ghost"
    # frame-precise: the respawn happens on the contact frame
    assert runner.read_u16(WR, LIVES) == 2, "ghost contact did not cost a ship"
    assert runner.read_u16(WR, HURTLOCK) > 0, "no i-frames granted after the hit"
    assert (runner.read_u16(WR, PX), runner.read_u16(WR, PY)) == \
        (SHIP_SPAWN_X, SHIP_SPAWN_Y), "ship did not respawn at the spawn point"
    # RENDERED: the ship blinks — OAM slot 0 alternates drawn (y<0xE0, at spawn X)
    # and parked (y>=0xE0) across the i-frame window.
    drawn = parked = 0
    for _ in range(24):
        runner.run_frames(1)
        ox, oy = _oam(runner, 0)[:2]
        if oy >= 0xE0:
            parked += 1
        else:
            drawn += 1
            assert abs(ox - SHIP_SPAWN_X) <= 2, "a drawn blink frame is not at spawn X"
    assert drawn > 0 and parked > 0, \
        f"i-frame blink not rendered (drawn={drawn}, parked={parked})"


def test_zero_lives_freezes_into_game_over_and_start_restarts(runner):
    """Spend all three ships: GAME OVER latches, the world freezes, the banner
    renders, and START restarts to a fresh game (rendered + state checks)."""
    runner.load_rom(_rom(), run_seconds=0.6)
    for _ in range(3):
        while runner.read_u16(WR, HURTLOCK) > 0:   # let i-frames lapse
            runner.run_frames(4)
        if runner.read_u16(WR, LIVES) == 0:
            break
        assert _fly_into_ghost(runner), "a scripted hit failed to land"
    runner.run_frames(3)
    assert runner.read_u16(WR, GAMEOVER) == 1, "zero ships did not reach GAME OVER"
    # world frozen: ghost Y positions do not advance while GAME OVER holds
    before = [runner.read_u16(WR, ENE_Y + i * 2) for i in range(4)]
    runner.run_frames(20)
    after = [runner.read_u16(WR, ENE_Y + i * 2) for i in range(4)]
    assert before == after, "the world kept moving during GAME OVER"
    # RENDERED: the GAME OVER / PRESS START banner paints white text into a band
    # that is pure-black-or-terrain (zero white) during play.
    img = _shot(runner)
    assert _white_count(img, 80, 92, 176, 120) > 40, "GAME OVER banner not rendered"
    # START begins a fresh game
    runner.set_input(0, start=True)
    runner.run_frames(3)
    runner.set_input(0)
    runner.run_frames(3)
    assert runner.read_u16(WR, GAMEOVER) == 0, "START did not clear GAME OVER"
    assert runner.read_u16(WR, LIVES) == 3, "restart did not restore three ships"
    assert runner.read_u16(WR, SCORE) == 0, "restart did not reset the score"


def test_rom_title_is_astro_barrage():
    """Pin the ROM header title so it can never silently regress to a placeholder
    (the SUPERFORGE TEST default that shipped on every rail before the fix)."""
    data = (ROOT / "build" / "shmup.sfc").read_bytes()
    title = data[0x7FC0:0x7FD5].decode("latin1").rstrip("\x00 ")
    assert title == "ASTRO BARRAGE", f"ROM title regressed to {title!r}"


def test_bullet_pool_never_overflows_under_mashing(runner):
    """Rising-edge fire fills the 6-slot pool and swallows further presses — the
    live-bullet count reaches exactly the pool size and never exceeds it."""
    runner.load_rom(_rom(), run_seconds=0.6)
    def alive():
        return sum(1 for i in range(6) if runner.read_u16(WR, BUL_ALIVE + i*2) == 1)
    peak = 0
    for _ in range(60):
        runner.set_input(0, a=True)      # press (rising edge -> one bullet)
        runner.run_frames(1)
        runner.set_input(0)              # release, so the next press is a new edge
        runner.run_frames(1)
        n = alive()
        peak = max(peak, n)
        assert n <= 6, f"bullet pool overflowed ({n} > 6)"
    assert peak == 6, f"pool never filled to its 6-slot ceiling (peak={peak})"
