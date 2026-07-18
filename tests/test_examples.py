"""Done-conditions for the example scenarios (the repo's acceptance gates).

These tests are also the worked examples an agent learns the testing discipline
from, so they follow it exactly (test-authoring skill):
  - assert on the RENDERED result (screen pixels: colour + position), not only
    the intermediate OAM buffer;
  - drive the WHOLE input space (all four d-pad directions, held and tapped);
  - tie physical input to the on-screen result so a reversed mapping can't pass.
Run via `make test` (builds build/*.sfc first) or `make check` (+ width gate).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90
_CYAN = lambda p: p[0] < 90 and p[1] > 120 and p[2] > 120


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rom(name):
    p = BUILD / f"{name}.sfc"
    assert p.exists(), f"{p} not built — run `make examples` first"
    return str(p)


def _shot(r, path="/tmp/_ex_shot.png"):
    r.take_screenshot(path)
    return Image.open(path).convert("RGB")


def _centroid(img, pred):
    """(cx, cy, count) of pixels matching pred — the on-screen blob position."""
    w, _ = img.size
    try:
        data = list(img.get_flattened_data())
    except AttributeError:  # older Pillow
        data = list(img.getdata())
    xs = ys = n = 0
    for i, p in enumerate(data):
        if pred(p):
            xs += i % w
            ys += i // w
            n += 1
    return (xs / n, ys / n, n) if n else (None, None, 0)


def _oam(r):
    b = r.read_bytes(OAM, 0, 4)
    return b[0], b[1]


def test_hello_world_boots_and_renders_red(runner):
    """Boots; a red sprite is actually visible; backdrop is the defined baseline."""
    runner.load_rom(_rom("hello_world"), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert _oam(runner) == (120, 100)                       # engine placed it
    img = _shot(runner)
    _, _, n = _centroid(img, _RED)
    assert 56 <= n <= 72, f"expected ~64 red px on screen, got {n}"   # player sees it
    assert img.getpixel((8, 8)) == (0, 0, 0)                # defined-black backdrop, not garbage


def test_move_sprite_all_four_directions_visible(runner):
    """Every d-pad direction moves the sprite the right way — in OAM AND on screen."""
    runner.load_rom(_rom("move_sprite"), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    sx, sy = _oam(runner)
    scx, scy, _ = _centroid(_shot(runner), _RED)

    # (label, input, OAM axis sign) — exactly one axis nonzero per case.
    cases = [
        ("right", dict(right=True), (+1, 0)),
        ("left", dict(left=True), (-1, 0)),
        ("up", dict(up=True), (0, -1)),
        ("down", dict(down=True), (0, +1)),
    ]
    for name, kw, (ex, ey) in cases:
        runner.load_rom(_rom("move_sprite"), run_seconds=0.4)   # reset to spawn
        runner.set_input(0, **kw)
        runner.run_frames(40)
        runner.set_input(0)
        runner.run_frames(2)
        ox, oy = _oam(runner)
        cx, cy, n = _centroid(_shot(runner), _RED)
        assert n > 40, f"{name}: sprite not visible after move ({n} px)"
        # active axis moved the right way (OAM)
        assert (ox - sx) * ex + (oy - sy) * ey > 30, f"{name}: OAM ({sx},{sy})->({ox},{oy})"
        # inactive axis unchanged (OAM)
        if ex:
            assert oy == sy, f"{name}: OAM Y drifted {sy}->{oy}"
        else:
            assert ox == sx, f"{name}: OAM X drifted {sx}->{ox}"
        # on-screen centroid moved the SAME way (catches a reversed mapping)
        assert (cx - scx) * ex + (cy - scy) * ey > 20, \
            f"{name}: screen ({scx:.0f},{scy:.0f})->({cx:.0f},{cy:.0f})"

    # control: with no input the sprite holds (input genuinely drives it)
    runner.load_rom(_rom("move_sprite"), run_seconds=0.4)
    hold = _oam(runner)
    runner.run_frames(40)
    assert _oam(runner) == hold


def test_buttons_btnp_edge_detect_visible(runner):
    """Visible cyan sprite; holding A advances exactly ONE step (rising edge)."""
    runner.load_rom(_rom("buttons"), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    _, _, n = _centroid(_shot(runner), _CYAN)
    assert n > 40, f"cyan sprite not visible ({n} px)"
    assert _oam(runner)[0] == 40
    runner.set_input(0, a=True)
    runner.run_frames(40)
    runner.set_input(0)
    runner.run_frames(2)
    assert _oam(runner)[0] == 56     # held 40 frames -> ONE 16px step (edge, not held)
    runner.set_input(0, a=True)
    runner.run_frames(40)
    runner.set_input(0)
    runner.run_frames(2)
    assert _oam(runner)[0] == 72     # second press -> one more step
