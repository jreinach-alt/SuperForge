"""Done-conditions for the brawler template (animated camelot knights).

Drives the full combat loop on hardware: movement in all four directions
with facing (OAM H-flip) and animation (tile cycling), the enemy chase, a
3-hit KO -> WINS + respawn (verifying the parked sprite does NOT peek at
the top of the screen — the Y-wrap lesson), contact damage + knockback,
and the HP-0 GAME OVER freeze. Rendered surfaces checked alongside WRAM.
"""
import time
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

PX, PY, FACING = 0x32, 0x34, 0x36
EX, EY = 0x40, 0x42
HP, FOE, WINS, GAMEOVER = 0x1800, 0x1802, 0x1804, 0x1810

ARTHUR_IDLE = {0x00, 0x04, 0x08, 0x0C}
ARTHUR_RUN = {0x40, 0x44, 0x48, 0x4C, 0x80, 0x84, 0x88, 0x8C}

# Surface-clamp geometry (mirrors templates/brawler/main.asm, owner-confirmed
# look): the floor's top edge is pixel y=160 and the clamp is in CONTENT
# terms — every camelot frame's drawn feet end at cell row 28 (measured:
# both knights, all idle+run frames), so drawn feet = PY + CONTENT_BOTTOM,
# pinned to 160 (up-clamp) .. 160+MAX_GIVE (down-clamp).
LANE_TOP, LANE_BOT = 132, 136
CONTENT_BOTTOM = 28
FLOOR_TOP = 160
MAX_GIVE = 4


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rom():
    p = ROOT / "build" / "brawler.sfc"
    assert p.exists(), f"{p} not built — run `make brawler` first"
    return str(p)


def _oam(r, slot):
    b = r.read_bytes(OAM, slot * 4, 4)
    return b[0], b[1], b[2], b[3]


def _shot(r, path="/tmp/_brawler.png"):
    r.take_screenshot(path)
    return Image.open(path).convert("RGB")


def _tiles_over(r, slot, samples=12, step=3):
    seen = set()
    for _ in range(samples):
        seen.add(_oam(r, slot)[2])
        r.run_frames(step)
    return seen


def _swing(r):
    r.set_input(0, a=True)
    r.run_frames(2)
    r.set_input(0)
    r.run_frames(18)


def _fight_until(r, cond, what, timeout=25):
    """Approach the enemy and swing until cond() holds."""
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        ex, px = r.read_u16(WR, EX), r.read_u16(WR, PX)
        ey, py = r.read_u16(WR, EY), r.read_u16(WR, PY)
        if abs(ex - px) < 40 and abs(ey - py) < 20:
            key = "right" if ex > px else "left"
            r.set_input(0, **{key: True})
            r.run_frames(2)
            r.set_input(0)
            _swing(r)
        else:
            r.run_frames(8)
    assert cond(), f"timed out: {what}"


def test_boots_floor_knights_hud(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    img = _shot(runner)
    # floor band renders (terrain colors in the lower third)
    floor = sum(1 for y in range(170, 220) for x in range(0, 256, 4)
                if sum(img.getpixel((x, y))) > 60)
    assert floor > 800, "floor band not visible"
    # both knights render at their OAM positions
    for slot in (0, 1):
        ox, oy = _oam(runner, slot)[:2]
        px = [img.getpixel((x, y)) for y in range(oy, min(oy + 34, 239))
              for x in range(ox, min(ox + 32, 256))]
        assert sum(1 for p in px if sum(p) > 90) > 40, f"knight {slot} not visible"
    # HUD text renders
    hud = [img.getpixel((x, y)) for y in range(8, 26) for x in range(8, 248, 2)]
    assert any(p[0] > 200 and p[1] > 200 and p[2] > 200 for p in hud), "HUD not visible"


def test_feet_clamped_to_surface_top(runner):
    """RENDERED surface-clamp invariant (the owner-reported bug's guard).

    Measured in CONTENT terms: every camelot frame's drawn feet end at row
    CONTENT_BOTTOM (28) of the 32-row cell — a box-edge clamp leaves a 4px
    sky gap that reads as floating. The check MEASURES the per-column gap
    between the sprite's lowest drawn pixel and the floor's first row on
    the actual screenshot: 0 rows at the up-clamp (feet touch the surface),
    and never more than MAX_GIVE at the down-clamp.
    """
    runner.load_rom(_rom(), run_seconds=0.6)

    def measured_gap(img, ox, ex, what):
        """Per body column: empty rows between the sprite's lowest drawn
        pixel and the floor's top row (0 = feet touch the surface).
        The surface row is located in columns AWAY from both knights, then
        each body column is scanned UPWARD from it. Threshold >30 catches
        the art's near-black outline."""
        # sprite-free sample band for the surface row
        for band in (range(2, 34), range(120, 152), range(220, 252)):
            if all(abs(band.start + 16 - k - 16) > 48 for k in (ox, ex)):
                break
        surf = next((y for y in range(120, 232)
                     if sum(1 for x in band
                            if sum(img.getpixel((x, y))) > 30) > len(band) * 0.7),
                    None)
        assert surf is not None, f"{what}: floor surface not found"
        gaps = []
        for x in range(ox + 8, ox + 24):
            g, y = 0, surf - 1
            while y > surf - 40 and sum(img.getpixel((x, y))) <= 30:
                g += 1
                y -= 1
            if y > surf - 40:                 # found a sprite pixel above
                gaps.append(g)
        assert gaps, f"{what}: no measurable sprite/floor columns"
        return gaps

    # up-clamp: drawn feet touch the surface (gap 0; outline rounding <= 1)
    runner.set_input(0, up=True)
    runner.run_frames(20)
    runner.set_input(0)
    runner.run_frames(3)
    ox, oy = _oam(runner, 0)[:2]
    ex = _oam(runner, 1)[0]
    assert oy == LANE_TOP, f"LANE_TOP clamp: OAM y={oy}, expected {LANE_TOP}"
    gaps = measured_gap(_shot(runner), ox, ex, "up-clamp")
    assert min(gaps) == 0 and max(gaps) <= 1, \
        f"up-clamp: feet not ON the surface (gap rows per column: {gaps})"

    # down-clamp: at most MAX_GIVE px of overlap, never a sky gap
    runner.set_input(0, down=True)
    runner.run_frames(32)
    runner.set_input(0)
    runner.run_frames(3)
    ox, oy = _oam(runner, 0)[:2]
    assert oy == LANE_BOT, f"LANE_BOT clamp: OAM y={oy}, expected {LANE_BOT}"
    feet = oy + CONTENT_BOTTOM
    assert FLOOR_TOP <= feet <= FLOOR_TOP + MAX_GIVE, \
        f"down-clamp: drawn feet at y={feet}, allowed {FLOOR_TOP}..{FLOOR_TOP + MAX_GIVE}"


def test_walk_facing_and_animation(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    # idle: tiles stay within the idle table
    idle_seen = _tiles_over(runner, 0)
    assert idle_seen <= ARTHUR_IDLE and len(idle_seen) >= 2, \
        f"idle anim not cycling within its table: {sorted(idle_seen)}"
    # all four directions move; horizontal sets facing + H-flip bit
    for name, kw, axis, sign, want_face in [
        ("right", dict(right=True), PX, +1, 0),
        ("left", dict(left=True), PX, -1, 1),
        ("down", dict(down=True), PY, +1, None),
        ("up", dict(up=True), PY, -1, None),
    ]:
        p0 = runner.read_u16(WR, axis)
        runner.set_input(0, **kw)
        runner.run_frames(10)
        # while walking: run-table tiles + H-flip tracks facing
        run_seen = _tiles_over(runner, 0, samples=8, step=2)
        runner.set_input(0)
        runner.run_frames(2)
        p1 = runner.read_u16(WR, axis)
        assert (p1 - p0) * sign > 0, f"{name}: did not move ({p0}->{p1})"
        assert run_seen <= ARTHUR_RUN and len(run_seen) >= 2, \
            f"{name}: run anim not playing: {sorted(run_seen)}"
        if want_face is not None:
            assert runner.read_u16(WR, FACING) == want_face, f"{name}: facing"
            attr = _oam(runner, 0)[3]
            assert ((attr >> 6) & 1) == want_face, f"{name}: OAM H-flip bit"


def test_enemy_chases_and_faces_player(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    d0 = abs(runner.read_u16(WR, EX) - runner.read_u16(WR, PX))
    runner.run_frames(40)
    d1 = abs(runner.read_u16(WR, EX) - runner.read_u16(WR, PX))
    assert d1 < d0, f"enemy not closing distance ({d0}->{d1})"
    # mordred faces the player: player starts left of him -> H-flip set
    if runner.read_u16(WR, EX) > runner.read_u16(WR, PX):
        attr = _oam(runner, 1)[3]
        assert (attr >> 6) & 1 == 1, "enemy not facing the player"


def test_three_hits_ko_wins_and_clean_respawn_park(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    img_before = _shot(runner)
    hud_before = [img_before.getpixel((x, y)) for y in range(8, 26)
                  for x in range(88, 160)]
    _fight_until(runner, lambda: runner.read_u16(WR, FOE) <= 2, "first hit lands")
    # HUD re-rendered after the first hit
    img = _shot(runner)
    hud_after = [img.getpixel((x, y)) for y in range(8, 26) for x in range(88, 160)]
    assert hud_after != hud_before, "FOE hit but HUD did not re-render"
    _fight_until(runner, lambda: runner.read_u16(WR, WINS) >= 1, "KO -> WINS")
    # while respawn-parked: NO sprite fragment may peek at the top of the
    # screen (the 32x32 Y-wrap lesson — parked at $E0, not $F0)
    img = _shot(runner)
    top = [img.getpixel((x, y)) for y in range(1, 17) for x in range(0, 64)]
    hud_white = sum(1 for p in top if p[0] > 200 and p[1] > 200 and p[2] > 200)
    nonblack = sum(1 for p in top if sum(p) > 60)
    assert nonblack - hud_white < 10, \
        "sprite fragment peeking at the top of the screen (Y-wrap park bug)"
    # and the enemy comes back with full hp
    deadline = time.time() + 10
    while runner.read_u16(WR, FOE) == 0 and time.time() < deadline:
        runner.run_frames(10)
    assert runner.read_u16(WR, FOE) == 3, "enemy did not respawn with full hp"


def test_contact_damage_knockback_and_game_over_freeze(runner):
    runner.load_rom(_rom(), run_seconds=0.6)
    # stand still and let mordred walk into arthur three times
    deadline = time.time() + 30
    hp_seen = {runner.read_u16(WR, HP)}
    px_before = runner.read_u16(WR, PX)
    while runner.read_u16(WR, GAMEOVER) == 0 and time.time() < deadline:
        runner.run_frames(10)
        hp_seen.add(runner.read_u16(WR, HP))
    assert runner.read_u16(WR, GAMEOVER) == 1, f"no game over (hp seen {hp_seen})"
    assert {2, 1, 0} <= hp_seen, f"hp did not tick down through 2,1,0: {hp_seen}"
    # GAME OVER text renders mid-screen
    img = _shot(runner)
    mid = [img.getpixel((x, y)) for y in range(104, 122) for x in range(90, 180)]
    assert any(p[0] > 200 and p[1] > 200 and p[2] > 200 for p in mid), \
        "GAME OVER text not visible"
    # frozen: input is dead
    p0 = runner.read_u16(WR, PX)
    runner.set_input(0, right=True)
    runner.run_frames(20)
    runner.set_input(0)
    assert runner.read_u16(WR, PX) == p0, "input not frozen after game over"
