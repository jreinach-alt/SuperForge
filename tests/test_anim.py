"""sf_anim run-gate: the animation clock + H-flip facing on real hardware.

Reads the REAL output surface (OAM slot 0 tile + attr bytes, screenshot
pixels) alongside the ROM's debug mirrors, and drives the full state cycle:
all four idle steps IN ORDER (wrap included) and both facing states.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

IDLE_TILES = [0x00, 0x04, 0x08, 0x0C]      # arthur_anim_idle (base 0)


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _oam0(r):
    b = r.read_bytes(OAM, 0, 4)
    return b[0], b[1], b[2], b[3]          # x, y, tile, attr


def test_idle_animation_cycles_in_order(runner):
    rom = ROOT / "build" / "anim_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE008) == 1

    # sample the HARDWARE OAM tile for ~3 full cycles (4 steps x 8 frames)
    seen = []
    for _ in range(50):
        tile = _oam0(runner)[2]
        if not seen or seen[-1] != tile:
            seen.append(tile)
        runner.run_frames(3)
    assert set(seen) == set(IDLE_TILES), f"OAM tiles seen {seen}"
    # order: every consecutive pair must be adjacent in the cycle (wrap incl.)
    ring = {IDLE_TILES[i]: IDLE_TILES[(i + 1) % 4] for i in range(4)}
    for a, b in zip(seen, seen[1:]):
        assert ring[a] == b, f"steps out of order: {seen}"
    # the sprite actually renders (Arthur pixels at (100,100))
    runner.take_screenshot("/tmp/_anim.png")
    img = Image.open("/tmp/_anim.png").convert("RGB")
    region = [img.getpixel((x, y)) for y in range(100, 134) for x in range(100, 132)]
    assert sum(1 for p in region if sum(p) > 60) > 80, "animated sprite not visible"


def test_facing_mirror_tracks_hflip_bit(runner):
    rom = ROOT / "build" / "anim_test.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    # collect (facing mirror, OAM attr bit6) pairs across several flips
    pairs = set()
    flips = 0
    last_face = runner.read_u16(WR, 0xE014)
    for _ in range(80):
        face_pre = runner.read_u16(WR, 0xE014)
        runner.run_frames(2)                # let the OAM DMA catch the mirror up
        attr = _oam0(runner)[3]
        face_post = runner.read_u16(WR, 0xE014)
        if face_pre == face_post:           # discard flip-boundary samples
            pairs.add((face_pre, (attr >> 6) & 1))
        if face_post != last_face:
            flips += 1
            last_face = face_post
        runner.run_frames(5)
    assert flips >= 3, "facing never flipped"
    assert pairs == {(0, 0), (1, 1)}, f"H-flip bit does not track facing: {sorted(pairs)}"
