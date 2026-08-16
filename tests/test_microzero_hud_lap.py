"""microzero — the live HUD lap digit.

bg_text writes VRAM under forced blank, which a RUNNING scene cannot do. The
lap digit therefore goes through a one-cell VBlank queue (text_dp's txt_q +
bg_text's text_queue_cell / text_vblank_commit): the tick stages the cell,
the NMI hook commits it with two CPU stores during VBlank.

Both surfaces are checked, because either alone can pass while the feature
is broken:
  * the DESTINATION region — the BG3 tilemap word at the digit's cell, read
    straight out of VRAM. A staged-but-never-committed queue fails here.
  * the RENDERED pixels — the digit's 8-px column in the HUD band of an
    actual screenshot, and that they CHANGE as the lap advances. A cell
    written to the wrong VRAM page, behind the wrong palette, or under a
    layer that never reaches the screen passes the VRAM check and fails
    here.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

VR = MemoryType.SnesVideoRam

TXT_ATTR = (7 << 10) | (1 << 13)     # RACE_TXT_ATTR: palette 7, priority
LAP_COL, LAP_ROW = 28, 2             # RACE_LAP_CELL, in BG3 tilemap cells
HUD_LINES = D.world_const("HUD_LINES")   # world.inc is the SSoT
WHITE = (255, 255, 255)


@pytest.fixture(scope="module")
def booted():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    lut = D.load_tool("gen_move_lut")
    runner = MesenRunner()
    # An EXACT absolute boot frame, not `>= 120`. The race is a moving
    # picture, and a free-run budget lands anywhere in a ~100-frame
    # spread under load (measured: 6 reps of `run_seconds=4.0` on the
    # autodemo landed on 6 different frames, 218..337, and produced 5
    # different PNGs; `boot_to_frame` produced 1 and 1). docs/45 §5.
    runner.boot_to_frame(str(SUPERFORGE / "build" / "microzero.sfc"), 140,
                         uninit_detection=True)
    D.enter_race(runner, syms)
    runner.debug_break()
    runner.frame_step(2)
    yield runner, syms, lut
    runner.debug_resume()
    runner.stop()


def _cell(runner, syms, col, row=LAP_ROW):
    """The BG3 tilemap word actually sitting in VRAM for one HUD cell."""
    base = syms["ES_V_TEXT_MAP"]["start"]
    return runner.read_u16(VR, 2 * (base + row * 32 + col))


def _glyph(ch):
    return ord(ch) - ord(" ")


def _digit_column_pixels(runner, tmp_path, name):
    """The digit cell's 8-px column, everywhere in the HUD band."""
    from PIL import Image
    p = tmp_path / name
    runner.frame_step(2)
    runner.take_screenshot(str(p))
    img = Image.open(p).convert("RGB")
    x0 = LAP_COL * 8
    return [tuple(img.getpixel((x, y)) for x in range(x0, x0 + 8))
            for y in range(HUD_LINES)]


def test_lap_label_and_zero_digit_are_in_the_tilemap(booted):
    """scene enter writes 'LAP' plus the starting digit into the tilemap the
    allocator assigned — read back from VRAM, not from the source string."""
    runner, syms, lut = booted
    for i, ch in enumerate("LAP"):
        got = _cell(runner, syms, 24 + i)
        assert got == _glyph(ch) | TXT_ATTR, \
            f"label cell {i}: VRAM has {got:#06x}, want glyph {ch!r}"
    assert D.lap(runner, syms) == 0
    assert _cell(runner, syms, LAP_COL) == _glyph("0") | TXT_ATTR


def test_digit_is_visible_on_screen_before_any_lap(booted, tmp_path):
    """...and it actually reaches the screen: the glyph's column carries
    white text pixels inside the HUD band."""
    px = _digit_column_pixels(runner=booted[0], tmp_path=tmp_path,
                              name="lap0.png")
    assert any(WHITE in row for row in px), \
        "the lap digit's column has no text pixels — it never composited"


def test_vblank_queue_updates_the_digit_as_laps_are_scored(booted, tmp_path):
    """The feature under test: a RUNNING scene changes a HUD cell. Drive the
    ring; on each lap the tilemap cell must hold the new digit AND the
    rendered column must change. Nothing else in the HUD may move."""
    runner, syms, lut = booted
    before_px = _digit_column_pixels(runner, tmp_path, "before.png")
    score_cells = [_cell(runner, syms, c) for c in range(2, 20)]

    D.brake_to_stop(runner, syms)
    D.steer_to(runner, syms, 0)
    D.brake_to_stop(runner, syms)
    sim = D.sim_from_rom(runner, syms, lut)
    seen = []
    for _ in range(700):
        prev = sim.lap
        D.drive_sim(runner, sim, 1, **D.track_buttons(sim, lut))
        if sim.lap == prev:
            continue
        runner.frame_step(2)                    # let the NMI commit the cell
        got = _cell(runner, syms, LAP_COL)
        want = _glyph(str(sim.lap)) | TXT_ATTR
        assert got == want, (
            f"lap {sim.lap}: tilemap cell is {got:#06x}, want {want:#06x} "
            f"— the VBlank queue did not commit")
        seen.append(sim.lap)
        if len(seen) == 2:
            break
    assert seen == [1, 2], f"laps did not advance cleanly: {seen}"

    after_px = _digit_column_pixels(runner, tmp_path, "after.png")
    assert any(WHITE in row for row in after_px), "the digit stopped rendering"
    assert after_px != before_px, \
        "the rendered digit column never changed — the cell is not on screen"
    assert [_cell(runner, syms, c) for c in range(2, 20)] == score_cells, \
        "the queue wrote outside its one claimed cell"


def test_no_uninitialized_reads_across_the_hud_queue_path(booted):
    """Power-on contract: the NMI commit reads only queue bytes the boot
    init wrote, on frames nothing was staged as well as on frames it was."""
    runner, _, _ = booted
    runner.frame_step(10)
    runner.assert_no_uninitialized_reads()
