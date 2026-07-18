"""Done-condition for the patrol template: dodge patrolling enemies.

Reads real outputs — per-frame OAM positions for all three actors, VRAM HUD
digit tiles, rendered pixels — while driving with set_input. Verifies both
enemies' exact patrol bounds, contact -> respawn + HITS text, the no-hit
safety of the spawn zone, and that play continues after a knockback.
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

SPAWN = (200, 200)
E1_MIN, E1_MAX = 88, 152    # ground beat between the low walls
E2_MIN, E2_MAX = 32, 64     # platform beat (ledge turns)

_GREY = lambda p: abs(p[0] - p[1]) < 30 and abs(p[1] - p[2]) < 30 and 80 < p[0] < 200
_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90
_MAGENTA = lambda p: p[0] > 150 and p[1] < 90 and p[2] > 150


def _slot(r, n):
    b = r.read_bytes(OAM, n * 4, 2)
    return b[0], b[1]


def _digit_units(r):
    return r.read_u16(VR, 0xC000 + (1 * 32 + 10) * 2)  # tile (10,1)


def _tile(ch):
    return 0x3C00 | (160 + ord(ch) - 0x20)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "patrol.sfc"
    assert rom.exists(), f"{rom} not built — run `make patrol` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


def test_boots_and_renders_all_actors(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.run_frames(10)
    runner.take_screenshot("/tmp/_patrol0.png")
    img = Image.open("/tmp/_patrol0.png").convert("RGB")
    d = list(img.getdata())
    assert sum(1 for p in d if _GREY(p)) > 1500, "terrain not visible"
    assert sum(1 for p in d if _RED(p)) > 20, "player not visible"
    assert sum(1 for p in d if _MAGENTA(p)) > 40, "enemies not visible (2x)"
    assert _digit_units(runner) == _tile('0'), "HITS not 00000 at boot"


def test_enemies_patrol_exact_bounds(runner):
    xs1, xs2 = [], []
    for _ in range(160):
        runner.run_frames(1)
        xs1.append(_slot(runner, 1)[0])
        xs2.append(_slot(runner, 2)[0])
    assert min(xs1) == E1_MIN and max(xs1) == E1_MAX, \
        f"ground beat [{min(xs1)},{max(xs1)}], want [{E1_MIN},{E1_MAX}]"
    assert min(xs2) == E2_MIN and max(xs2) == E2_MAX, \
        f"platform beat [{min(xs2)},{max(xs2)}], want [{E2_MIN},{E2_MAX}]"
    assert all(E2_MIN <= x <= E2_MAX for x in xs2), "enemy 2 left its platform"


def test_spawn_zone_is_safe(runner):
    hits0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(100)      # stand still at spawn through full beats
    assert runner.read_u16(WR, 0xE010) == hits0, "hit while outside the beats"
    assert _slot(runner, 0) == SPAWN, "player moved without input"


def test_contact_respawns_and_counts(runner):
    # jump the low wall (col 20) into the ground beat and walk at the enemy
    r = runner
    hits0 = r.read_u16(WR, 0xE010)
    r.set_input(0, left=True)
    hit_frame = None
    for i in range(400):
        r.run_frames(1)
        if i % 30 == 0:
            r.set_input(0, left=True, a=True)   # hop periodically (the wall)
        else:
            r.set_input(0, left=True)
        if r.read_u16(WR, 0xE010) > hits0:
            hit_frame = i
            break
    r.set_input(0)
    r.run_frames(3)
    assert hit_frame is not None, "never reached the enemy (navigation)"
    assert r.read_u16(WR, 0xE010) == hits0 + 1, "hit counted more than once"
    # spawn-zone tolerance: input release is wall-clock racy, the player may
    # walk a few px post-respawn before the release lands (audit-1 F3)
    x, y = _slot(r, 0)
    assert abs(x - SPAWN[0]) <= 8 and y == SPAWN[1], \
        f"not respawned near {SPAWN}: at {(x, y)}"
    assert _digit_units(r) == _tile(chr(ord('0') + hits0 + 1)), \
        "HITS text does not show the new count"
    runner.take_screenshot("/tmp/_patrol_hit.png")


def test_playable_after_knockback(runner):
    x0, y0 = _slot(runner, 0)
    runner.set_input(0, right=True)
    runner.run_frames(10)
    runner.set_input(0)
    runner.run_frames(2)
    assert _slot(runner, 0)[0] > x0, "player stuck after the knockback"
