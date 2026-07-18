"""Run-gate for sf_mosaic_transition (mosaic scene-wipe macros).

Asserts on RENDERED output across the FULL transition state cycle (idle -> OUT
-> swap -> IN -> idle), never a proxy variable (kit rigor rule
"Indirect-Evidence Tests Are Worse Than No Tests"; state-cycle-coverage rule):

  before (idle)  : bright RED checkerboard scene + a white OBJ sprite present
  mid (OUT)      : the dissolve is simultaneously
                     - DARKER (mean screen luminance well below the bright
                       scene) — the darkness ease, a rendered effect
                     - the OBJ sprite is GONE (no white pixels) — OBJ dropped
                       (sprites have no HW mosaic), a rendered effect
                     - SHADOW_MOSAIC is nonzero AND its size nibble > 0 — the
                       PPU mosaic register the NMI commits (pixelation)
  after (idle)   : bright BLUE scene (the swap ran) + the sprite is BACK,
                   mosaic cleared, brightness full

Feature under test: sf_mosaic_transition_arm / _tick / _active scene wipe.
Output regions read: screenshot pixels (luminance, sprite white pixels, BG
hue) — the composited frame; SHADOW_* mirrors are SUPPLEMENTAL ground truth.
State cycle exercised: idle -> OUT (mid sample) -> IN -> idle.

ROM contract (tests/mosaic_transition_test.asm): red checkerboard + white
center sprite; A press arms a wipe to a blue scene (swap recolors BG1).
$7E:E010 heartbeat; $7E:E012/14/16 mirror SHADOW_MOSAIC/INIDISP/TM;
$7E:E018 = sf_mosaic_transition_active.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

# sprite center (ROM places it at 120,100); allow for overscan offset by
# scanning a window around it.
SPR_X, SPR_Y = 120, 100


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _shot(runner, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    runner.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


def _mean_lum(img):
    w, h = img.size
    pts = [img.getpixel((x, y))
           for x in range(w // 6, 5 * w // 6, 12)
           for y in range(h // 6, 5 * h // 6, 12)]
    return sum(sum(p) / 3 for p in pts) / len(pts)


def _white_near_sprite(img):
    """Count near-white pixels in a window around the sprite center (overscan-
    tolerant). The sprite is the only white thing in the scene."""
    return sum(
        1
        for y in range(SPR_Y - 4, SPR_Y + 16)
        for x in range(SPR_X - 6, SPR_X + 12)
        if sum(img.getpixel((x, y))) > 600
    )


def _mean_hue(img):
    """Mean (r,g,b) over the BG (avoiding the sprite center)."""
    w, h = img.size
    rs = gs = bs = n = 0
    for x in range(w // 6, 5 * w // 6, 10):
        for y in range(h // 6, 5 * h // 6, 10):
            if abs(x - SPR_X) < 12 and abs(y - SPR_Y) < 12:
                continue
            r, g, b = img.getpixel((x, y))
            rs += r; gs += g; bs += b; n += 1
    return (rs / n, gs / n, bs / n)


def test_mosaic_wipe_full_cycle(runner):
    rom = BUILD / "mosaic_transition_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"

    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    # --- BEFORE: bright RED scene, sprite present, idle ---
    before = _shot(runner, "mosaic_before.png")
    lum_before = _mean_lum(before)
    assert lum_before > 60, f"scene not bright before wipe: {lum_before}"
    assert _white_near_sprite(before) > 20, "sprite missing before wipe"
    r0, g0, b0 = _mean_hue(before)
    assert r0 > b0 + 30, f"scene not red before wipe: rgb=({r0:.0f},{g0:.0f},{b0:.0f})"
    assert runner.read_u16(WR, 0xE018) == 0, "transition not idle before arm"

    # --- ARM the wipe (A edge) ---
    runner.set_input(0, a=True)
    runner.run_frames(2)
    runner.set_input(0)

    # Step through the wipe frame-by-frame, recording the DARKEST frame, the
    # MIN sprite-white count, and the PEAK mosaic size while a transition is
    # active. This is timing-robust (no dependence on landing on one exact
    # frame) — the wipe necessarily passes through a near-black peak at the
    # swap, full OBJ-drop, and max mosaic, so the extremes are deterministic.
    min_lum = lum_before
    min_white = 9999
    peak_mosaic = 0
    obj_dropped_seen = False
    saved_mid = False
    for _ in range(40):
        runner.run_frames(1)
        if runner.read_u16(WR, 0xE018) == 0:
            break  # wipe finished
        img = _shot(runner, "mosaic_mid_scan.png")
        lum = _mean_lum(img)
        if lum < min_lum:
            min_lum = lum
            _shot(runner, "mosaic_mid.png")  # keep the darkest for the artifact
            saved_mid = True
        min_white = min(min_white, _white_near_sprite(img))
        m = runner.read_bytes(WR, 0xE012, 1)[0]
        peak_mosaic = max(peak_mosaic, m)
        if (runner.read_bytes(WR, 0xE016, 1)[0] & 0x10) == 0:
            obj_dropped_seen = True
    assert saved_mid, "never sampled an active wipe frame"

    # (a) DARKER: the wipe's darkest frame is well below the bright scene
    assert min_lum < lum_before - 25, (
        f"screen did not darken through the wipe ({lum_before:.0f} -> {min_lum:.0f})"
    )
    # (b) SPRITE GONE at some point: the OBJ layer was dropped during the wipe
    assert min_white < 8, "sprite stayed visible through the wipe (OBJ not dropped)"
    assert obj_dropped_seen, "OBJ bit never cleared in SHADOW_TM during the wipe"
    # (c) PIXELATED: peak SHADOW_MOSAIC has a size nibble > 0 and a BG nibble
    assert (peak_mosaic >> 4) > 0, f"mosaic size nibble never > 0 (${peak_mosaic:02X})"
    assert (peak_mosaic & 0x0F) != 0, f"mosaic affected-BG nibble zero (${peak_mosaic:02X})"

    # --- AFTER: let the wipe settle; bright BLUE scene, sprite back, idle ---
    runner.run_frames(40)
    after = _shot(runner, "mosaic_after.png")
    assert runner.read_u16(WR, 0xE018) == 0, "wipe did not return to idle"

    lum_after = _mean_lum(after)
    assert lum_after > 60, f"scene not bright after wipe: {lum_after}"
    assert _white_near_sprite(after) > 20, "sprite not restored after wipe"
    # the scene SWAPPED: now blue (the swap recolored BG1)
    r1, g1, b1 = _mean_hue(after)
    assert b1 > r1 + 30, f"scene did not swap to blue: rgb=({r1:.0f},{g1:.0f},{b1:.0f})"
    # mosaic cleared, brightness restored
    assert runner.read_bytes(WR, 0xE012, 1)[0] == 0, "mosaic not cleared after wipe"
    assert (runner.read_bytes(WR, 0xE014, 1)[0] & 0x0F) == 0x0F, "brightness not full after wipe"
    assert (runner.read_bytes(WR, 0xE016, 1)[0] & 0x10) != 0, "OBJ not restored after wipe"
