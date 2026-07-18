"""Done-conditions for the scroller template (scrolling BG + sprite on top).

Per the discipline: verifies the rendered result (BG checkerboard + sprite both
visible), drives ALL FOUR scroll directions (tied to the on-screen pattern AND
the committed shadow scroll), and confirms the sprite holds its screen position
while the world scrolls under it.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

_GREEN = lambda p: p[0] < 90 and p[1] > 150 and p[2] < 90
_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rom():
    p = BUILD / "scroller.sfc"
    assert p.exists(), f"{p} not built — run `make scroller` first"
    return str(p)


def _shot(r, path="/tmp/_scr.png"):
    r.take_screenshot(path)
    return Image.open(path).convert("RGB")


def _count(img, pred):
    return sum(1 for p in img.getdata() if pred(p))


def _green_sig(img):
    """Signature of the green checkerboard's position (changes when it scrolls).

    Full green pattern along a row (h-scroll) and a column (v-scroll), away from
    the centre sprite — any non-period shift changes one or both.
    """
    w, h = img.size
    d = list(img.getdata())
    row, col = 40, 40
    xs = frozenset(x for x in range(w) if _GREEN(d[row * w + x]))   # green x along row 40
    ys = frozenset(y for y in range(h) if _GREEN(d[y * w + col]))   # green y along col 40
    return (xs, ys)


def _sprite(r):
    b = r.read_bytes(OAM, 0, 4)
    return b[0], b[1]


def test_boots_bg_and_sprite_visible(runner):
    runner.load_rom(_rom(), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    img = _shot(runner)
    assert _count(img, _GREEN) > 2000, "BG checkerboard not visible"
    assert 56 <= _count(img, _RED) <= 72, "sprite not visible"
    assert _sprite(runner) == (120, 100)


def test_scroll_all_four_directions_sprite_holds(runner):
    # HOFS at $0120, VOFS at $0122; pattern signature must shift; sprite must hold.
    cases = [
        ("right", dict(right=True), 0x0120),
        ("left", dict(left=True), 0x0120),
        ("down", dict(down=True), 0x0122),
        ("up", dict(up=True), 0x0122),
    ]
    for name, kw, reg in cases:
        runner.load_rom(_rom(), run_seconds=0.4)        # reset cam to 0
        sig0 = _green_sig(_shot(runner))
        reg0 = runner.read_u16(WR, reg)
        sp0 = _sprite(runner)
        runner.set_input(0, **kw)
        runner.run_frames(30)
        runner.set_input(0)
        runner.run_frames(2)
        sig1 = _green_sig(_shot(runner))
        reg1 = runner.read_u16(WR, reg)
        sp1 = _sprite(runner)
        assert reg1 != reg0, f"{name}: scroll shadow {hex(reg)} did not change ({reg0}->{reg1})"
        assert sig1 != sig0, f"{name}: the rendered BG did not scroll ({sig0}->{sig1})"
        assert sp1 == sp0 == (120, 100), f"{name}: sprite did not hold ({sp0}->{sp1})"
