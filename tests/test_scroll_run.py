"""Done-condition for the scroll_run template: a two-screen scrolling level.

A closed-loop bot (OAM + the CAM_X/STATE WRAM mirrors — set_input is
wall-clock) runs the level left to right: camera clamped at 0 on boot,
follows past screen-center, player crosses the page seam and the obstacle
course, camera clamps at 256 at the right edge, and the goal pillar ends the
game (STATE=1, GOAL text in VRAM, input frozen). Rendered checks at the two
camera extremes (boot left clamp + the goal's right clamp) per the
layer-composition rule; the audit's seam-mid-screen render is covered by the
run-gate (test_level.py) at cam=172.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam
OAM = MemoryType.SnesSpriteRam

_GREY = lambda p: abs(p[0] - p[1]) < 30 and abs(p[1] - p[2]) < 30 and 80 < p[0] < 200
_GOLD = lambda p: p[0] > 200 and p[1] > 150 and p[2] < 120
_WHITE = lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200


def _pos(r):
    b = r.read_bytes(OAM, 0, 2)
    return b[0], b[1]


def _cam(r):
    return r.read_u16(WR, 0x4C)     # CAM_X mirror (DP $4C)


def _world_x(r):
    return r.read_u16(WR, 0x32)     # PX (DP $32)


def _state(r):
    return r.read_u16(WR, 0xE010)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "scroll_run.sfc"
    assert rom.exists(), f"{rom} not built — run `make scroll_run` first"
    r.load_rom(str(rom), run_seconds=0.6)
    yield r
    r.stop()


def test_boots_camera_clamped_left(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.run_frames(10)
    assert _cam(runner) == 0, "camera not clamped at the left world edge"
    assert _pos(runner) == (16, 200), "player not at rest at the spawn"
    runner.take_screenshot("/tmp/_sr0.png")
    img = Image.open("/tmp/_sr0.png").convert("RGB")
    d = list(img.getdata())
    assert sum(1 for p in d if _GREY(p)) > 1500, "terrain not visible"


def test_run_the_level_to_the_goal(runner):
    # closed-loop: run right with stall-jumps (clears pillar col 14); the
    # tall pillar (col 44, 48px) needs the designed route — retreat, hop
    # onto the platform at cols 38..41 (drift-controlled so the arc lands
    # ON it), then jump from the platform over the pillar.
    r = runner

    def _coast_to_landing(hold_right=False):
        for _ in range(60):
            r.run_frames(1)
            if _state(r) == 1 or _pos(r)[1] in (168, 200):
                break

    last_wx, stall = _world_x(r), 0
    for _ in range(2500):
        if _state(r) == 1:
            break
        wx = _world_x(r)
        y = _pos(r)[1]
        if y == 200 and 330 <= wx <= 356:
            # stuck at the tall pillar: retreat and take the platform route.
            # Takeoff window: the arc must clear y=168 BEFORE the platform's
            # left edge (px 304) — jump at wx~260 and drift in at the apex.
            while _world_x(r) > 252:
                r.set_input(0, left=True)
                r.run_frames(1)
            while _world_x(r) < 258:
                r.set_input(0, right=True)
                r.run_frames(1)
            r.set_input(0, right=True, a=True)   # full arc, right held
            r.run_frames(6)
            r.set_input(0, right=True)
            _coast_to_landing()
            continue
        if y == 168 and wx >= 324:
            # on the platform at its right end: jump the pillar
            r.set_input(0, right=True, a=True)
            r.run_frames(6)
            r.set_input(0, right=True)
            _coast_to_landing(hold_right=True)
            continue
        stall = stall + 1 if wx == last_wx else 0
        last_wx = wx
        r.set_input(0, right=True, a=(stall > 4))
        r.run_frames(1)
    r.set_input(0)
    r.run_frames(5)
    assert _state(r) == 1, f"never reached the goal (world x={_world_x(r)})"
    assert _world_x(r) > 460, "goal state without reaching the goal column"


def test_camera_followed_and_clamped_right(runner):
    # at the goal (world x ~480) the camera must be hard-clamped at 256
    assert _cam(runner) == 256, f"cam={_cam(runner)}, want right clamp 256"
    # and the player draws at screen x = world - 256
    sx, _ = _pos(runner)
    assert abs(sx - (_world_x(runner) - 256)) <= 2, "screen pos != world - cam"


def test_goal_text_and_render(runner):
    # GOAL printed at tiles (14..17, 12)
    word = "".join(chr((runner.read_u16(VR, 0xC000 + (12 * 32 + 14 + i) * 2)
                        & 0xFF) - 160 + 0x20)
                   if runner.read_u16(VR, 0xC000 + (12 * 32 + 14 + i) * 2)
                   else "." for i in range(4))
    assert word == "GOAL", f"win text reads {word!r}"
    runner.take_screenshot("/tmp/_sr_goal.png")
    img = Image.open("/tmp/_sr_goal.png").convert("RGB")
    d = list(img.getdata())
    assert sum(1 for p in d if _WHITE(p)) > 30, "GOAL text not rendered"
    assert sum(1 for p in d if _GOLD(p)) > 10, "goal pillar not on screen"


def test_input_frozen_after_goal(runner):
    wx0 = _world_x(runner)
    runner.set_input(0, left=True, a=True)
    runner.run_frames(40)
    runner.set_input(0)
    assert _world_x(runner) == wx0, "player still moves after the goal"
