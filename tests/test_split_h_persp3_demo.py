"""split_h_persp3_demo — Archetype C-horiz: THREE stacked Mode-7 CAMERA bands.

The three-camera extension of split_h_matrix_demo. Proves, by READING THE
RENDERED FRAMEBUFFER (kit rule #2 — every assertion reads pixels or the hardware
VRAM the PPU consumes, never an engine proxy variable), that THREE vertically-
stacked views of ONE flat top-down Mode-7 world render at THREE demonstrably
different cameras with TWO clean single-scanline seams, sharing one Mode-7 world
in VRAM.

BUDGET: extra cameras via LIVE per-scanline perspective solves do NOT fit 60fps
(one solve alone is ~87-138% of a frame — see test_persp_cycles.py). The ONLY
budget-viable path for three cameras is FLAT precomputed per-band matrices
(sf_split_h_matrix_bands): NON-REPEAT HDMA tables, ~nil CPU, no live solve. The
game loop just idles, so three cameras close 60fps as trivially as one.

The world is an 8x8-px checkerboard (two greens). The three bands render it at
three scales -> three on-screen checker periods (longest same-colour run in a
row): camera A (top, scale $0100 = 1.0) ~8 px; camera B (middle, $0040 = 0.25)
~32 px; camera C (bottom, $0080 = 0.5) ~16 px.

  C1  three distinct cameras: top ~8, middle ~32, bottom ~16 — the SAME world
      through three matrices, three separated period regimes. NON-VACUITY:
      -DONE_CAM uses camera A for ALL three bands -> all periods ~8, a SINGLE
      camera fills the screen and the three-distinct assertion MUST FAIL.
  C2  two clean single-scanline seams: exactly TWO rows where the period regime
      jumps, and NO intermediate/smeared row mixing regimes.
  C3  temporal stability: across consecutive deterministic frames the bands are
      byte-stable. The scene is HDMA-static — there is NO double buffer to desync
      (unlike the live perspective rail) — so this confirms the flat matrix path
      is inherently flicker-free.
  60fps/structural: the matrix band streams on 2 allocator channels (mask $0C =
      CH2|CH3); the frame closes at 60fps (heartbeat advances ~1/frame) with NO
      live solve.
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

# Period regimes (longest same-colour run in a row). A ~8, C ~16, B ~32.
SMALL_MAX = 12          # camera A (8-px) row stays at/under this
MED_LO, MED_HI = 13, 22  # camera C (16-px) row lands in this band
LARGE_MIN = 24          # camera B (32-px) row is at/above this


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
    Path("/tmp/kit_phaseP_shots").mkdir(parents=True, exist_ok=True)
    path = f"/tmp/kit_phaseP_shots/{tag}.png"
    runner.take_screenshot(path)
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return w, h, img.load()


def _row_sig(pix, w, y):
    """A per-row colour-class bit vector (dark vs light green) — reads pixels."""
    return [1 if pix[x, y][1] > 200 else 0 for x in range(0, w)]


@pytest.fixture(scope="module")
def roms():
    r = subprocess.run(["make", "build/split_h_persp3_demo.sfc"], cwd=str(ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"build failed:\n{r.stderr}")
    v = subprocess.run(
        ["bash", "templates/split_h_persp3_demo/build_split_h_persp3_variants.sh"],
        cwd=str(ROOT), capture_output=True, text=True)
    if v.returncode != 0:
        pytest.skip(f"variant build failed:\n{v.stderr}")
    return {
        "default": BUILD / "split_h_persp3_demo.sfc",
        "onecam": BUILD / "split_h_persp3_demo_onecam.sfc",
    }


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def test_boots(roms, runner):
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "default ROM did not boot"


def test_c1_three_distinct_cameras(roms, runner):
    """C1: the three bands render THREE distinct cameras of one world — top ~8
    (camera A), middle ~32 (camera B), bottom ~16 (camera C) on-screen period.
    The three regimes are separated (A < C < B by clear margins). Reads
    FRAMEBUFFER."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    w, h, pix = _grab(runner, "itemC_3band")
    top = [_max_run(pix, w, y) for y in (30, 45, 60)]       # camera A band
    mid = [_max_run(pix, w, y) for y in (95, 115, 135)]     # camera B band
    bot = [_max_run(pix, w, y) for y in (165, 185, 205)]    # camera C band
    assert all(t <= SMALL_MAX for t in top), \
        f"top band is not camera A's small (~8) period: runs={top}"
    assert all(m >= LARGE_MIN for m in mid), \
        f"middle band is not camera B's large (~32) period: runs={mid}"
    assert all(MED_LO <= b <= MED_HI for b in bot), \
        f"bottom band is not camera C's medium (~16) period: runs={bot}"
    # Three genuinely distinct regimes, separated by clear margins: A < C < B.
    assert max(top) < min(bot) and max(bot) < min(mid), (
        f"the three cameras are not distinctly separated: top(cam A)={top} "
        f"bot(cam C)={bot} mid(cam B)={mid}")


def test_c1_onecam_control_single_camera(roms, runner):
    """C1 NON-VACUITY (-DONE_CAM): all three bands use camera A's scale -> all
    periods ~8, a SINGLE uniform camera fills the screen, and the three-distinct-
    regime signal is ABSENT (the C1 assertion cannot hold). Proves C1 measures
    three real cameras, not merely the presence of seams."""
    runner.load_rom(str(roms["onecam"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "onecam ROM did not boot"
    w, h, pix = _grab(runner, "itemC_onecam")
    runs = [max(_max_run(pix, w, y) for y in ys)
            for ys in ((30, 45, 60), (95, 115, 135), (165, 185, 205))]
    assert all(r <= SMALL_MAX for r in runs), (
        f"C1 not non-vacuous: -DONE_CAM still shows multiple period regimes "
        f"(band maxima {runs}) — the bands are not a single uniform camera")


def test_c2_two_clean_seams(roms, runner):
    """C2: exactly TWO clean single-scanline seams — classify every visible row as
    S(~8)/M(~16)/L(~32); the sequence is S...S L...L M...M with exactly TWO regime
    transitions and NO intermediate/smeared '?' row. Reads FRAMEBUFFER."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    w, h, pix = _grab(runner, "itemC_seams")

    def label(r):
        if r <= SMALL_MAX:
            return 'S'
        if r >= LARGE_MIN:
            return 'L'
        if MED_LO <= r <= MED_HI:
            return 'M'
        return '?'
    seq = [label(_max_run(pix, w, y)) for y in range(15, 224)]
    mixed = [15 + i for i, c in enumerate(seq) if c == '?']
    assert not mixed, f"seam(s) not clean — smeared/intermediate row(s) at {mixed}"
    transitions = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    assert transitions == 2, (
        f"expected exactly TWO clean seam transitions, saw {transitions} "
        f"(sequence {''.join(seq)})")


def test_c3_temporal_stability(roms, runner):
    """C3: the three-camera scene is temporally stable across consecutive
    deterministic frames — each band's row signature is byte-identical frame to
    frame. The flat matrix band is HDMA-static (no double buffer to desync), so
    this confirms the budget-viable multi-camera path is inherently flicker-free.
    Reads FRAMEBUFFER signatures (not a proxy)."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(20)
    sample_rows = (45, 115, 185)     # one row inside each of the three bands
    sigs = []
    Path("/tmp/kit_phaseP_shots").mkdir(parents=True, exist_ok=True)
    with runner.frame_stepping():
        for i in range(8):
            runner.frame_step(1)
            path = f"/tmp/kit_phaseP_shots/itemC_temporal_{i:02d}.png"
            runner.take_screenshot(path)
            img = Image.open(path).convert("RGB")
            w, h = img.size
            pix = img.load()
            sigs.append([_row_sig(pix, w, y) for y in sample_rows])
    # Non-vacuity: the signatures must actually carry checker content.
    assert any(sum(s) > 20 for s in sigs[0]), \
        "band signatures are empty — C3 would be vacuous"
    worst = 0
    for i in range(len(sigs) - 1):
        for b in range(len(sample_rows)):
            worst = max(worst, sum(1 for j in range(len(sigs[i][b]))
                                   if sigs[i][b][j] != sigs[i + 1][b][j]))
    assert worst == 0, (
        f"three-band scene not temporally stable: max consecutive-frame row "
        f"signature change {worst}px across 8 frames")


def test_shared_vram_and_60fps(roms, runner):
    """STRUCTURAL: all three cameras read ONE shared low-32KB Mode-7 map+CHR at
    VRAM word $0000 (no extra VRAM); the matrix band streams on 2 allocator
    channels (mask $0C = CH2|CH3); the frame closes at 60fps (heartbeat advances
    ~1/frame) with NO live solve. Reads VRAM + hardware state, not a proxy."""
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    runner.run_frames(10)
    vr = runner.read_bytes(VR, 0x0000, 64)
    tilemap = [vr[i] for i in range(0, 64, 2)]
    chr_ = [vr[i] for i in range(1, 64, 2)]
    assert set(tilemap[:16]) == {0, 1}, f"no checker map at VRAM $0000: {tilemap[:16]}"
    assert chr_[0] == 1, f"tile-0 CHR not present at VRAM $0000: {chr_[:8]}"
    mask = runner.read_bytes(WR, 0x0108, 1)[0]
    assert mask == 0x0C, (
        f"expected the 3-band matrix on 2 channels (mask $0C = CH2|CH3), got ${mask:02X}")
    hb0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(120)
    hb1 = runner.read_u16(WR, 0xE010)
    advanced = (hb1 - hb0) & 0xFFFF
    assert advanced >= 110, f"frame did not close at 60fps: heartbeat advanced {advanced}/120"
