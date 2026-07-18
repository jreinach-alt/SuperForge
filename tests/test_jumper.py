"""Done-condition for the jumper template: jump physics under real input.

Reads real outputs — OAM position per frame, rendered pixels — while driving
with set_input. Verifies the full input->arc->landing cycle, platform landings
at exact heights, ledge walk-off, the overhang bonk, and rest stability
(grounded frames hold the exact rest y, per the apex-AND-landing rule).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

REST_GROUND = 200   # ground row 26 top (208) - 8
REST_PLAT1 = 168    # platform row 22 top (176) - 8
BONK_Y = 184        # overhang row 22: first clear row below it (176 + 8)

_GREY = lambda p: abs(p[0] - p[1]) < 30 and abs(p[1] - p[2]) < 30 and 80 < p[0] < 200
_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90


def _pos(r):
    b = r.read_bytes(OAM, 0, 2)
    return b[0], b[1]


def _hold(r, frames, **btn):
    r.set_input(0, **btn)
    r.run_frames(frames)
    r.set_input(0)
    r.run_frames(2)


def _trace_y(r, frames, **btn):
    """Per-frame OAM y while holding buttons (state-cycle surface)."""
    r.set_input(0, **btn)
    ys = []
    for _ in range(frames):
        r.run_frames(1)
        ys.append(_pos(r)[1])
    r.set_input(0)
    return ys


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "jumper.sfc"
    assert rom.exists(), f"{rom} not built — run `make jumper` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


def test_boots_renders_and_rests(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.run_frames(10)
    assert _pos(runner)[1] == REST_GROUND, "player not at rest on the ground"
    runner.take_screenshot("/tmp/_jumper0.png")
    img = Image.open("/tmp/_jumper0.png").convert("RGB")
    d = list(img.getdata())
    assert sum(1 for p in d if _GREY(p)) > 1500, "terrain not visible"
    assert sum(1 for p in d if _RED(p)) > 20, "player not visible"


def test_jump_full_cycle_on_ground(runner):
    ys = _trace_y(runner, 50, a=True)   # held A: one jump (btnp edge-gates)
    apex = min(ys)
    assert abs((REST_GROUND - apex) - 38) <= 4, \
        f"apex height {REST_GROUND - apex}px, want ~38"
    land_i = next(i for i, y in enumerate(ys) if i > 20 and y == REST_GROUND)
    assert all(y == REST_GROUND for y in ys[land_i:]), \
        "rest not stable after landing (embed/hover)"
    assert max(ys) == REST_GROUND, "sank below rest during the cycle"


def test_jump_onto_platform_exact_height(runner):
    # platform 1: cols 8..12 (px 64..103), top 176, rest 168. Take off from
    # x=32 (left border stop at 8, then 12 frames right): the arc clears the
    # platform's left edge near apex and the drift carries the box over it.
    _hold(runner, 60, left=True)
    assert _pos(runner)[0] == 8, "precondition: left border stop"
    _hold(runner, 12, right=True)
    x0, _ = _pos(runner)
    assert 28 <= x0 <= 36, f"precondition: takeoff x={x0}, want ~32"
    r = runner
    r.set_input(0, a=True, right=True)
    ys, lock = [], None
    for i in range(60):
        r.run_frames(1)
        x, y = _pos(r)
        ys.append(y)
        if y == REST_PLAT1 and lock is None and i > 10:
            lock = i
            r.set_input(0)      # stop drifting once we touch down
    r.set_input(0)
    r.run_frames(5)
    x, y = _pos(r)
    assert y == REST_PLAT1, f"rest y={y} after platform jump, want {REST_PLAT1}"
    assert 64 - 7 <= x <= 103 + 7, f"x={x} not over platform 1"
    runner.take_screenshot("/tmp/_jumper_plat.png")


def test_walk_off_ledge_falls_and_lands(runner):
    # from platform 1 (left there by the previous test), walk left off the
    # edge; fall (clamped to terminal velocity) to the ground.
    #
    # Frame-stepped: this trace used to be wall-clock (_trace_y) and the
    # per-frame deltas depended on host scheduling — frames slipped
    # between run_frames(1) and the OAM read, which made the
    # terminal-velocity assertion flake (two consecutive S6 full-suite
    # runs). frame_step advances exactly one frame per readback, so the
    # trace is the player's true per-frame OAM y. The context manager
    # restores free-running on exit (even on assertion failure) so the
    # following wall-clock test (test_overhang_bonks_head) keeps working.
    with runner.frame_stepping():
        ys = []
        for _ in range(60):
            runner.frame_step(1, left=True)
            ys.append(_pos(runner)[1])
    assert REST_PLAT1 in ys[:5], "precondition: started on platform 1"
    deltas = [b - a for a, b in zip(ys, ys[1:])]
    assert max(deltas) <= 4, f"fall step {max(deltas)}px > terminal velocity"
    assert ys[-1] == REST_GROUND, f"end y={ys[-1]}, want ground {REST_GROUND}"
    assert all(y == REST_GROUND for y in ys[-5:]), "rest not stable after fall"


def test_overhang_bonks_head(runner):
    # overhang: row 22 cols 28..30 (px 224..247), bottom 183. Stand under it
    # (right border stop, x=240) and jump: y must never pass above
    # BONK_Y=184, then resettle.
    _hold(runner, 150, right=True)      # right border stop -> x=240
    assert _pos(runner)[0] >= 224, "precondition: not under the overhang"
    assert _pos(runner)[1] == REST_GROUND
    ys = _trace_y(runner, 50, a=True)
    assert min(ys) == BONK_Y, \
        f"bonk min y={min(ys)}, want exactly {BONK_Y} (snap below the tile)"
    assert ys[-1] == REST_GROUND and all(y == REST_GROUND for y in ys[-5:]), \
        "did not resettle at rest after the bonk"
    # bump must cut the arc short: airtime under the overhang < free airtime
    air = sum(1 for y in ys if y != REST_GROUND)
    assert air < 30, f"airtime {air} frames — ascent not killed by the bump"
