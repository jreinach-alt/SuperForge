"""sf_meta_draw run-gate: multi-OBJ metasprites on real hardware.

Reads the REAL output surfaces: the six OAM part entries (positions, tiles,
hi-table size bits), the composited screenshot vs a PIL render of the SOURCE
48x48 frame, and the animation cycle order.
"""
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
from tests.test_png2snes import best_shift_match, render_reference_sprite, bgr15_quantize

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

# the converter's fixed 48x48 layout: one 32x32 + five 16x16
PART_OFFS = [(0, 0, 1), (32, 0, 0), (32, 16, 0), (0, 32, 0), (16, 32, 0), (32, 32, 0)]
F0_TILES = [0x00, 0x40, 0x42, 0x44, 0x46, 0x48]
BX, BY = 80, 60


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module")
def attack_frame0(tmp_path_factory):
    z = ROOT / "examples" / "itch_cc0" / "Four_Seasons_Platformer_Sprites.zip"
    if not z.exists():
        pytest.skip(f"{z} missing")
    d = tmp_path_factory.mktemp("fs_sprites")
    with zipfile.ZipFile(z) as zf:
        zf.extractall(d)
    frames = sorted(
        (d / "Sprites [Enemies]" / "Brickhead" / "Brickhead_1" / "Attack").glob("*.png"))
    return Image.open(frames[0]).convert("RGBA")


def _load(runner):
    rom = ROOT / "build" / "meta_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, 0xE008) == 1


def test_parts_land_at_table_positions_with_size_bits(runner):
    _load(runner)
    # catch the ROM on anim step 0 (frame loops 4 steps x 8 frames)
    for _ in range(40):
        if runner.read_u16(WR, 0xE010) == 0:
            break
        runner.run_frames(2)
    assert runner.read_u16(WR, 0xE010) == 0, "never observed anim step 0"
    runner.run_frames(2)                # let the OAM DMA catch the mirror up
    assert runner.read_u16(WR, 0xE010) == 0, "step advanced during settle"
    oam = runner.read_bytes(OAM, 0, 24)
    hi = runner.read_bytes(OAM, 512, 2)
    for slot, ((dx, dy, large), tile) in enumerate(zip(PART_OFFS, F0_TILES)):
        x, y, t = oam[slot * 4], oam[slot * 4 + 1], oam[slot * 4 + 2]
        assert x == BX + dx, f"part {slot} x: {x} != {BX + dx}"
        assert y == BY + dy, f"part {slot} y: {y} != {BY + dy}"
        assert t == (tile & 0xFF), f"part {slot} tile: {t} != {tile & 0xFF}"
        size_bit = (hi[slot // 4] >> ((slot % 4) * 2 + 1)) & 1
        assert size_bit == large, f"part {slot} hi-table size bit {size_bit} != {large}"


def test_composited_metasprite_matches_source_render(runner, attack_frame0):
    _load(runner)
    for _ in range(40):
        if runner.read_u16(WR, 0xE010) == 0:
            break
        runner.run_frames(2)
    runner.run_frames(2)
    runner.take_screenshot("/tmp/_meta.png")
    shot = Image.open("/tmp/_meta.png").convert("RGB")
    # reference: source frame re-centered into the 48x48 box, BGR15-quantized
    ref = render_reference_sprite(attack_frame0, 48)
    ratio = best_shift_match(shot, ref, BX, BY)
    assert ratio >= 0.97, f"composited metasprite mismatch vs source ({ratio:.0%})"


def test_base256_name_bit_and_x9_render(runner):
    """audit-1 (S2) F-2/F-7: the static instance at OBJ base 256 / X=479
    exercises the 9-bit tile path (attribute name-select bit) and the
    hi-table X9 bit — and its left-edge peek actually RENDERS."""
    _load(runner)
    oam = runner.read_bytes(OAM, 0, 48)
    hi = runner.read_bytes(OAM, 512, 3)
    for k, ((dx, dy, large), tile) in enumerate(zip(PART_OFFS, F0_TILES)):
        slot = 6 + k                          # instance 2 = slots 6-11
        x9 = (hi[slot // 4] >> ((slot % 4) * 2)) & 1
        size_bit = (hi[slot // 4] >> ((slot % 4) * 2 + 1)) & 1
        attr = oam[slot * 4 + 3]
        t = oam[slot * 4 + 2]
        want_x = 479 + dx
        assert oam[slot * 4] == (want_x & 0xFF), f"part {k} x low byte"
        assert x9 == (want_x >> 8) & 1 == 1, f"part {k} X9 bit not set"
        assert attr & 1 == 1, f"part {k} name-select bit (tile bit 8) not set"
        assert t == ((256 + tile) & 0xFF), f"part {k} tile low byte"
        assert size_bit == large, f"part {k} size bit"
        assert oam[slot * 4 + 1] == 120 + dy, f"part {k} y"
    # rendered: the dx=32 parts' right 8px peek at the left screen edge
    runner.run_frames(2)
    runner.take_screenshot("/tmp/_meta9.png")
    img = Image.open("/tmp/_meta9.png").convert("RGB")
    peek = [img.getpixel((x, y)) for y in range(126, 168) for x in range(0, 15)]
    assert sum(1 for p in peek if sum(p) > 60) > 40, \
        "base-256/X9 instance not visible at the left edge"


def test_attack_animation_cycles_in_order(runner):
    _load(runner)
    first_tiles = [0x00, 0x04, 0x08, 0x0C]      # large part of frames 0-3
    seen = []
    for _ in range(60):
        t = runner.read_bytes(OAM, 0, 4)[2]
        if not seen or seen[-1] != t:
            seen.append(t)
        runner.run_frames(3)
    assert set(seen) == set(first_tiles), f"tiles seen {seen}"
    ring = {first_tiles[i]: first_tiles[(i + 1) % 4] for i in range(4)}
    for a, b in zip(seen, seen[1:]):
        assert ring[a] == b, f"anim steps out of order: {seen}"
