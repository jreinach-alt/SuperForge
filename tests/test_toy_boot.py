"""an earlier phase gate conditions 1-4: the good toy builds through the
allocator + no-literals gate and BOOTS on MesenRunner with the emitted map
proven real by reading the rendered OUTPUT (VRAM/CGRAM bytes + a screenshot)
at allocator-assigned addresses taken from symbol_map.json — no address in
this test is hand-written. The collision toy STOPS the build. The no-literals
gate fails on a planted literal.

Power-on fidelity: the toy inits by contract (no blanket WRAM clear) and the
uninit-read detector must find ZERO read-before-write bytes.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

VR, CG, WR = MemoryType.SnesVideoRam, MemoryType.SnesCgRam, MemoryType.SnesWorkRam


def _make(*targets) -> subprocess.CompletedProcess:
    return subprocess.run(["make", *targets], cwd=SUPERFORGE,
                          capture_output=True, text=True)


@pytest.fixture(scope="module")
def built():
    r = _make("toy")
    assert r.returncode == 0, f"make toy failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["toy"]["placements"] + jmap["globals"]}
    return syms


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module")
def booted(built, runner):
    runner.load_rom_with_uninit_detection(
        str(SUPERFORGE / "build" / "toy.sfc"), frames=120)
    return built


def test_boots_with_signature_at_emitted_addresses(booted, runner):
    scratch = booted["US_SCRATCH"]["start"]
    assert runner.read_bytes(WR, scratch, 4) == b"SFOK"
    hb1 = runner.read_u16(WR, scratch + 4)
    runner.wait_frames(10)
    hb2 = runner.read_u16(WR, scratch + 4)
    assert hb2 != hb1, "heartbeat frozen — the toy main loop is not running"


def test_user_state_at_both_scopes(booted, runner):
    assert runner.read_u16(WR, booted["US_SCORE"]["start"]) == 0
    assert runner.read_byte(WR, booted["US_LIVES"]["start"]) == 3
    # scene @dp vars live in the direct page (WRAM offset == DP offset)
    assert runner.read_u16(WR, booted["US_PLAYER_X"]["start"]) == 64
    assert runner.read_u16(WR, booted["US_PLAYER_Y"]["start"]) == 48


def test_vram_rendered_output_at_emitted_addresses(booted, runner):
    """The emitted .inc is real, not paper: the bytes land at the word
    addresses the allocator assigned (VRAM is byte-read at word*2)."""
    chr_base = booted["ES_V_FEAT_A_CHR"]["start"]
    tile1 = runner.read_bytes(VR, (chr_base + 8) * 2, 16)
    assert tile1 == b"\xFF" * 16, f"CHR tile 1 wrong: {tile1.hex()}"

    map_base = booted["ES_V_FEAT_A_MAP"]["start"]
    row0 = runner.read_bytes(VR, map_base * 2, 64)
    assert row0 == b"\x01\x00" * 32, f"tilemap row 0 wrong: {row0[:8].hex()}..."

    font_base = booted["ES_V_FEAT_B_FONT"]["start"]
    marker = runner.read_bytes(VR, font_base * 2, 2)
    assert marker == b"\xEF\xBE", f"font marker wrong: {marker.hex()}"


def test_cgram_palette_at_emitted_index(booted, runner):
    pal = booted["ES_C_FEAT_A_PAL"]["start"]
    cg = runner.read_bytes(CG, pal * 2, 8)
    colors = [int.from_bytes(cg[i:i + 2], "little") for i in range(0, 8, 2)]
    assert colors == [0x6000, 0x001F, 0x03E0, 0x7FFF], \
        f"palette wrong: {[hex(c) for c in colors]}"


def test_screenshot_exact_structure_no_uninit_pixels(booted, runner, tmp_path):
    """Rendered-output rule, exact form: the frame is EXACTLY the white tile
    row over the blue backdrop (plus the 224-in-239 letterbox padding).
    A single pixel outside {white, blue, black} means the scene displayed
    memory it never initialized — loose thresholds once passed random VRAM
    noise here; never again."""
    from PIL import Image
    shot = tmp_path / "toy.png"
    runner.take_screenshot(str(shot), settle_frames=2)
    img = Image.open(shot).convert("RGB")
    w, h = img.size
    white_row = [img.getpixel((x, 10)) for x in range(0, w, 8)]
    assert all(p == (255, 255, 255) for p in white_row), \
        f"tile row at y=10 not solid white: {set(white_row)}"
    mid = [img.getpixel((x, y)) for y in range(40, 200, 16) for x in range(0, w, 16)]
    assert all(p == (0, 0, 198) for p in mid), \
        f"backdrop not uniform blue: {set(mid) - {(0, 0, 198)}}"
    allowed = {(255, 255, 255), (0, 0, 198), (0, 0, 0)}
    stray = {p for p in img.getdata() if p not in allowed}
    assert not stray, f"uninitialized display pixels leaked: {sorted(stray)[:8]}"
    # keep a copy for the close-out render evidence
    keep = SUPERFORGE / "build" / "toy_render.png"
    shutil.copy(shot, keep)


def test_no_uninitialized_reads_without_blanket_clear(booted, runner):
    """Power-on fidelity BY CONTRACT: no blanket WRAM zero-clear anywhere,
    and still zero read-before-write bytes since power-on."""
    runner.assert_no_uninitialized_reads()


def test_collision_toy_stops_the_build():
    """The ALLOCATOR must refuse engine/toy_bad, on the collision.

    `assert r.returncode != 0` here could not fail between 2026-07-28 and
    2026-07-29: the target exited non-zero on every path, including the path
    that detected a toothless allocator. The target now reports
    the verdict in its status, so this assertion is load-bearing again — and
    tests/test_make_gates.py plants the toothless case to prove it fires.
    """
    r = _make("toy-bad")
    assert r.returncode == 0, (
        "make toy-bad FAILED — the allocator did not refuse the collision toy "
        f"for the right reason:\n{r.stdout}\n{r.stderr}")
    assert "ALLOCATION FAILED" in r.stderr
    assert "VRAM overlap" in r.stderr and "pin_a_map" in r.stderr


def test_planted_literal_fails_no_literals_gate(tmp_path):
    """Gate condition 4: plant a raw allocated-address literal in a copy of
    the toy engine source; the no-literals check must fail it."""
    planted = tmp_path / "planted.asm"
    src = (SUPERFORGE / "engine" / "toy" / "main.asm").read_text()
    src = src.replace("@spin:", "    sta $7E0203      ; PLANTED literal\n@spin:")
    assert "PLANTED" in src
    planted.write_text(src)
    # NOTE: no `--partial-files`. This invocation hands ONE
    # file a whole composition's map, which the whole-composition rom-backing
    # pass cannot answer — it survives only because the toy composition has ZERO rom
    # claims. Add one and this test fails with a rom-backing error that has
    # nothing to do with its subject. Naming the dependency, not restructuring
    # the test: that is separate work (the brief's out-of-scope list).
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "no_literals.py"),
         "--map", str(SUPERFORGE / "build" / "symbol_map.json"), str(planted)],
        capture_output=True, text=True)
    assert r.returncode == 1
    assert "raw address operand" in r.stderr
