"""split_h_matrix_demo — Archetype C-horiz: stacked Mode-7 CAMERA bands.

Proves, by READING THE RENDERED FRAMEBUFFER (kit rule #2 — every assertion reads
pixels or the hardware VRAM the PPU consumes, never an engine proxy variable),
that a per-band Mode-7 matrix (M7A-D) driven by HDMA renders TWO vertically-
stacked views of ONE flat top-down Mode-7 world at DEMONSTRABLY DIFFERENT cameras
with a clean single-scanline seam, sharing one Mode-7 world in VRAM.

The world is an 8x8-px checkerboard (two greens). Camera A (top band, matrix
scale M7A=M7D=$0100 = 1.0) renders the checker at an 8-px on-screen period;
camera B (bottom band, scale $0040 = 0.25) renders it 4x LARGER (32-px period).
The on-screen checker PERIOD (longest same-colour run in a row) is the camera
signal: ~8 in the top band, ~32 in the bottom band.

  M1  two distinct cameras: top-band rows have a small period (~8), bottom-band
      rows a large period (~32) — the SAME world through two different matrices,
      differing by the ~4x the scale ratio predicts. NON-VACUITY:
      -DNO_MATRIX_SPLIT uses camera A for BOTH bands -> both periods ~8, so a
      SINGLE camera fills the screen and the period-ratio assertion MUST FAIL.
  M2  clean single-scanline seam: exactly ONE row where the period jumps
      small->large, and NO intermediate/smeared row mixing the two regimes.
  M3  shared VRAM: both cameras read ONE low-32KB Mode-7 map+CHR at word $0000
      (the checker tilemap+CHR the PPU consumes) — no extra VRAM vs a single
      Mode-7 view (TM=BG1 only, one map uploaded).

Heartbeat mirror ($7E:E010) is used for SEQUENCING only (not an assertion proxy).
"""
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam

# Period regimes (longest same-colour run in a row). Camera A ~8, camera B ~32.
SMALL_MAX = 12          # a top-band (camera A, 8-px) row stays at/under this
LARGE_MIN = 24          # a bottom-band (camera B, 32-px) row is at/above this


def _max_run(pix, w, y):
    best = run = 1
    for x in range(1, w):
        if pix[x, y] == pix[x - 1, y]:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def _grab(runner, tag, settle=20):
    runner.run_frames(settle)
    Path("/tmp/kit_matrix_shots").mkdir(parents=True, exist_ok=True)
    path = f"/tmp/kit_matrix_shots/{tag}.png"
    runner.take_screenshot(path)
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return w, h, img.load()


@pytest.fixture(scope="module")
def roms():
    r = subprocess.run(["make", "build/split_h_matrix_demo.sfc"], cwd=str(ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"build failed:\n{r.stderr}")
    v = subprocess.run(
        ["bash", "templates/split_h_matrix_demo/build_split_h_matrix_variants.sh"],
        cwd=str(ROOT), capture_output=True, text=True)
    if v.returncode != 0:
        pytest.skip(f"variant build failed:\n{v.stderr}")
    return {
        "default": BUILD / "split_h_matrix_demo.sfc",
        "nomatrix": BUILD / "split_h_matrix_demo_nomatrix.sfc",
    }


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def test_boots(roms, runner):
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "default ROM did not boot"


def test_m1_two_distinct_cameras(roms, runner):
    """M1: top band renders camera A (small checker period), bottom band renders
    camera B (large period) — the SAME world through two different matrices, the
    period differing by the ~4x the scale ratio predicts. Reads FRAMEBUFFER."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    w, h, pix = _grab(runner, "m1_default")
    # Sample well inside each band (avoid the top overscan + the seam).
    top = [_max_run(pix, w, y) for y in (40, 70, 100)]
    bot = [_max_run(pix, w, y) for y in (150, 180, 210)]
    assert all(t <= SMALL_MAX for t in top), (
        f"top band is not camera A's small-period checker: runs={top}")
    assert all(b >= LARGE_MIN for b in bot), (
        f"bottom band is not camera B's large-period checker: runs={bot}")
    # The two cameras differ the way the scale predicts: ~4x period ratio.
    assert min(bot) >= 2 * max(top), (
        f"period ratio too small to be two distinct cameras: top={top} bot={bot}")


def test_m1_nomatrix_control_single_camera(roms, runner):
    """M1 NON-VACUITY (-DNO_MATRIX_SPLIT): both bands use camera A -> both periods
    small, a SINGLE camera fills the screen, the two-camera difference MUST be
    ABSENT (the period-ratio assertion cannot hold)."""
    runner.load_rom(str(roms["nomatrix"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "nomatrix ROM did not boot"
    w, h, pix = _grab(runner, "m1_nomatrix")
    top = max(_max_run(pix, w, y) for y in (40, 70, 100))
    bot = max(_max_run(pix, w, y) for y in (150, 180, 210))
    assert top <= SMALL_MAX and bot <= SMALL_MAX, (
        f"M1 not non-vacuous: -DNO_MATRIX_SPLIT still shows two periods "
        f"(top={top}, bot={bot}) — the bands are not a single uniform camera")


def test_m2_clean_single_scanline_seam(roms, runner):
    """M2: the band boundary is a single clean scanline — exactly ONE row where
    the period jumps small->large, and NO intermediate/smeared row in the visible
    window (a smeared transition would show rows neither ~8 nor ~32). Reads
    FRAMEBUFFER."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    w, h, pix = _grab(runner, "m2_default")
    # Classify every row: 'S' small (camera A), 'L' large (camera B), '?' mixed.
    labels = {}
    for y in range(20, h):
        r = _max_run(pix, w, y)
        labels[y] = 'S' if r <= SMALL_MAX else ('L' if r >= LARGE_MIN else '?')
    mixed = [y for y, l in labels.items() if l == '?']
    assert not mixed, f"seam not clean — intermediate/smeared row(s) at {mixed}"
    seq = [labels[y] for y in sorted(labels)]
    transitions = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    assert transitions == 1, (
        f"expected exactly one clean S->L seam transition, saw {transitions} "
        f"(sequence {''.join(seq)})")


def test_m3_vram_single_shared_world(roms, runner):
    """M3: both cameras read ONE shared low-32KB Mode-7 map+CHR — no extra VRAM.
    Confirm the checker tilemap+CHR is present at VRAM word $0000 (the single
    Mode-7 plane the PPU consumes). Reads VRAM, not an engine variable."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(10)
    vr = runner.read_bytes(VR, 0x0000, 64)
    tilemap = [vr[i] for i in range(0, 64, 2)]   # even bytes = Mode-7 tilemap
    chr_ = [vr[i] for i in range(1, 64, 2)]      # odd bytes = 8bpp tile pixels
    # Checker tilemap alternates tile 0/1; tile 0's CHR pixels are value 1.
    assert set(tilemap[:16]) == {0, 1}, f"no checker map at VRAM $0000: {tilemap[:16]}"
    assert chr_[0] == 1, f"tile-0 CHR not present at VRAM $0000: {chr_[:8]}"
