"""microzero — oam_sprites + player_car, built entirely through the
allocator: the boot park writes the whole 544-B shadow (hardware OAM shows
every sprite hidden on title), race enter uploads the car CHR to the
obj-floored claim and writes ONE exact OAM entry (hardware OAM bytes ==
declared entry; hi-table size bit set), the OBJ palette lands at CGRAM 128,
the render shows the car's declared colors at the pivot line, both TM bands
carry OBJ, and the uninit detector stays clean (the shadow is fully written
before its first DMA read).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

OAM = MemoryType.SnesSpriteRam
VR, CG, WR = MemoryType.SnesVideoRam, MemoryType.SnesCgRam, MemoryType.SnesWorkRam

sys.path.insert(0, str(SUPERFORGE / "tests"))
import mz_drive as D  # noqa: E402

PIVOT_LINE = D.world_const("PIVOT_LINE")   # world.inc is the SSoT
CAR_X, CAR_Y = 120, D.world_const("CAR_LINE")   # player_car.asm CAR_SCREEN_Y


def load_tool(name):
    spec = importlib.util.spec_from_file_location(
        name, SUPERFORGE / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def built():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    return {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}


@pytest.fixture(scope="module")
def runner(built):
    r = MesenRunner()
    # An EXACT absolute boot frame, not `>= 120`. The race is a moving
    # picture, and a free-run budget lands anywhere in a ~100-frame
    # spread under load (measured: 6 reps of `run_seconds=4.0` on the
    # autodemo landed on 6 different frames, 218..337, and produced 5
    # different PNGs; `boot_to_frame` produced 1 and 1). docs/45 §5.
    r.boot_to_frame(str(SUPERFORGE / "build" / "microzero.sfc"), 140,
                    uninit_detection=True)
    yield r
    r.stop()


def test_title_boots_with_every_sprite_parked(built, runner):
    """The boot park through the per-frame DMA: hardware OAM (not the
    shadow) shows all 128 sprites at Y=$F0 with a zeroed hi table."""
    oam = runner.read_bytes(OAM, 0, 544)
    bad = [i for i in range(128) if oam[i * 4 + 1] != 0xF0]
    assert not bad, f"unparked sprites on title: {bad[:8]}"
    assert oam[512:544] == bytes(32), "hi table not cleared"


@pytest.fixture(scope="module")
def in_race(built, runner):
    runner.debug_break()
    D.enter_race(runner, built)
    return built


def test_car_oam_entry_exact(in_race, runner):
    """Hardware OAM carries EXACTLY the declared entry in the claimed slot;
    every other sprite stays parked."""
    slot = in_race["ES_O_CAR"]["start"]
    oam = runner.read_bytes(OAM, 0, 544)
    e = oam[slot * 4: slot * 4 + 4]
    assert e == bytes((CAR_X, CAR_Y, 0, 0x30)), e.hex()
    hi = oam[512 + (slot >> 2)]
    assert (hi >> ((slot & 3) * 2)) & 3 == 2, \
        f"hi bits wrong (want size=large, X9=0): {hi:02x}"
    bad = [i for i in range(128)
           if i != slot and oam[i * 4 + 1] != 0xF0]
    assert not bad, f"non-car sprites unparked: {bad[:8]}"


def test_car_chr_and_palette_uploaded(in_race, runner):
    """Destination-region bytes: the obj chr claim (floored past the Mode-7
    region by the allocator) holds the generated CHR verbatim; OBJ palette 0
    words hold the generated palette."""
    base = in_race["ES_V_CAR_CHR"]["start"]
    assert base >= 0x4000, "obj chr not displaced past the Mode-7 region"
    chr_src = (SUPERFORGE / "build" / "assets" / "car_chr.bin").read_bytes()
    got = runner.read_bytes(VR, base * 2, len(chr_src))
    assert got == chr_src, "car CHR bytes differ in VRAM"
    pal_base = in_race["ES_C_CAR_PAL"]["start"]
    assert pal_base == 128
    pal_src = (SUPERFORGE / "build" / "assets" / "car_pal.bin").read_bytes()
    assert runner.read_bytes(CG, pal_base * 2, len(pal_src)) == pal_src


def test_car_renders_at_the_pivot_line(in_race, runner, tmp_path):
    """Composited proof (layer-priority class): the car's declared body
    color appears exactly in the sprite's screen box and nowhere else on
    those scanlines; the cockpit white sits in the box's upper half."""
    from PIL import Image
    gen = load_tool("gen_car_sprite")
    shot = tmp_path / "car.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    img = Image.open(shot).convert("RGB")

    def rgb(c):
        return tuple(((c >> s) & 31) << 3 | ((c >> s) & 31) >> 2
                     for s in (0, 5, 10))

    red = rgb(gen.PALETTE[1])
    # OAM Y displays from scanline Y+1; the screenshot's scanline-0 row is
    # located, not assumed (mz_drive.content_top — see a later review)
    top = D.content_top(img)
    box_y = range(CAR_Y + 1 + top, CAR_Y + 17 + top)
    box_x = range(CAR_X, CAR_X + 16)
    hits = [(x, y) for y in box_y for x in range(img.size[0])
            if img.getpixel((x, y)) == red]
    assert hits, "car body color absent at the pivot line"
    assert all(x in box_x for x, _ in hits), \
        f"body color outside the sprite box: {hits[:4]}"


def test_vblank_budget_and_channels(in_race):
    """The report carries the composition: OAM's 544-B transfer joins the
    stream's 16 and vwf's 1 in the F9 budget; oamq holds a vblank-phase channel.

    Deliberately EXACT rather than a bound: this line is the one place the whole
    VBlank composition is written down, so a claim appearing or resizing without
    anyone noticing shows up here. Updating it is the price of that, and the
    arithmetic must be stated when it moves — 2592 + 224 (vwf's 14-tile window)
    = 2816 data, 17 + 1 = 18 transfers, 17 x 128 = 2176 arm.
    """
    report = (SUPERFORGE / "build" / "mz" / "allocation_report.txt").read_text()
    assert "VBLANK-DMA 2816 + 2176 arm/5952 B/frame (18 transfers)" in report
    assert "oamq" in report and "OAMDATA" in report


def test_no_uninitialized_reads_with_sprites(in_race, runner):
    """The park wrote the whole shadow before the first commit DMA read it;
    the car path added no unwritten-read anywhere."""
    # PARKED: `in_race` debug_break()s and never resumes, so the wall-clock
    # run_frames(30) this replaces advanced the machine by nothing at all and
    # the assertion covered zero frames of the car path.
    runner.frame_step(30)
    runner.assert_no_uninitialized_reads()
