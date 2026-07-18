"""Done-condition for the hud_game template: sprite + live text HUD.

Reads the real outputs: the VRAM BG3 tilemap words for the label and counter,
the rendered white HUD pixels and red sprite pixels, OAM movement under d-pad
input, and the counter's VRAM digit tiles changing when A bumps the score.
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

_WHITE = lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200
_RED = lambda p: p[0] > 150 and p[1] < 90 and p[2] < 90

# BG3 tilemap at VRAM word $6000 (byte $C000); cell (tx, ty) at byte
# $C000 + (ty*32 + tx)*2. Text tile word = $1C00 | (160 + ascii - $20).
_BG3 = 0xC000


def _cell(tx, ty):
    return _BG3 + (ty * 32 + tx) * 2


def _tile(ch):
    return 0x3C00 | (160 + ord(ch) - 0x20)


def _count(img, pred):
    return sum(1 for p in img.getdata() if pred(p))


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "hud_game.sfc"
    assert rom.exists(), f"{rom} not built — run `make hud_game` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


def test_boots(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"


def test_hud_label_and_counter_in_vram(runner):
    # "SCORE" at tiles (1..5, 1)
    for i, ch in enumerate("SCORE"):
        got = runner.read_u16(VR, _cell(1 + i, 1))
        assert got == _tile(ch), f"label[{i}] = {got:04x}, want {_tile(ch):04x}"
    # "00000" at tiles (7..11, 1)
    for i in range(5):
        got = runner.read_u16(VR, _cell(7 + i, 1))
        assert got == _tile("0"), f"digit[{i}] = {got:04x}, want {_tile('0'):04x}"


def test_hud_and_sprite_render(runner):
    runner.take_screenshot("/tmp/_hud0.png")
    img = Image.open("/tmp/_hud0.png").convert("RGB")
    w = img.size[0]
    d = list(img.getdata())
    hud = sum(1 for y in range(8, 16) for x in range(w) if _WHITE(d[y * w + x]))
    assert hud > 50, f"HUD text not visible: {hud} white pixels in its row"
    assert _count(img, _RED) > 20, "player sprite not visible"


def test_dpad_moves_sprite_not_hud(runner):
    x0 = runner.read_bytes(OAM, 0, 1)[0]
    runner.set_input(0, right=True)
    runner.run_frames(15)
    runner.set_input(0)
    x1 = runner.read_bytes(OAM, 0, 1)[0]
    assert x1 > x0, f"sprite did not move right (OAM X {x0} -> {x1})"
    # the HUD stays put while the sprite moves
    runner.take_screenshot("/tmp/_hud1.png")
    img = Image.open("/tmp/_hud1.png").convert("RGB")
    w = img.size[0]
    d = list(img.getdata())
    hud = sum(1 for y in range(8, 16) for x in range(w) if _WHITE(d[y * w + x]))
    assert hud > 50, "HUD text vanished while the sprite moved"


def test_a_press_bumps_score_once(runner):
    score0 = runner.read_u16(WR, 0xE010)
    # hold A across several frames — the edge (btnp) must count it ONCE
    runner.set_input(0, a=True)
    runner.run_frames(10)
    runner.set_input(0)
    runner.run_frames(5)
    score1 = runner.read_u16(WR, 0xE010)
    assert score1 == score0 + 1, f"held A counted {score1 - score0} times, want 1"


def test_score_updates_hud_digits(runner):
    # press A until the score's units digit is 3, then check the VRAM tile
    target = 3
    score = runner.read_u16(WR, 0xE010)
    while score < target:
        runner.set_input(0, a=True)
        runner.run_frames(4)
        runner.set_input(0)
        runner.run_frames(4)
        score = runner.read_u16(WR, 0xE010)
    assert score == target
    runner.run_frames(2)  # let the NMI commit the reprint
    got = runner.read_u16(VR, _cell(11, 1))   # units digit
    assert got == _tile("3"), f"units digit tile = {got:04x}, want {_tile('3'):04x}"
    # leading digits still zero-padded
    got = runner.read_u16(VR, _cell(7, 1))
    assert got == _tile("0"), f"leading digit = {got:04x}, want {_tile('0'):04x}"
