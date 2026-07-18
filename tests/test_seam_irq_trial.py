"""seam_irq_trial — cold-start trial: band-2 Mode-7 origin via a seam-scanline
IRQ + pre-armed GP-DMA pair, proven against the classic HDMA-origin control.

Every assertion reads the rendered framebuffer or the WRAM counters whose
lockstep is the claim itself. Static scene -> cross-ROM pixel equality valid.

Measured facts this suite locks (the H1/H2 trial deliverables):
  G1  the GOLD equivalence: IRQ-origin build vs HDMA-origin control render
      BYTE-IDENTICAL frames (0 differing rows). -DMISTIME (fire at scanline
      60) flips the SAME metric: exactly content lines 60..111 differ.
  G2  the H+V build (-DHV) through the same HBlank spin gate is also
      byte-identical -> H+V dot-precision is NOT required for the seam.
  H1  wai wakes on the seam IRQ too: raw wake counter ~2x frames on the IRQ
      builds, ~1x on the HDMA control (same metric, flipped); the gated-wai
      loop keeps the cadence at +1/+1 regardless.
  H5  cadence: loop counter (E030) and NMI counter (E010) advance +1/+1 per
      stepped frame with the IRQ armed; the IRQ counter (E050) advances +1
      per frame in lockstep (no double-fires, no missed frames).
  W1  the fire window, measured on-emulator: handler entry at V = 112
      (internal scanlines; VTIME = SEAM because content line L draws during
      internal scanline L+1), fire completion in scanline 113 before dot 22.
  S1  structural: the IRQ build allocates ONLY the matrix pair (mask $0C,
      origin mask 0 = both origin channels FREED); the control allocates the
      classic origin pair ($30).
"""
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

OFF = 7                     # content line L renders at screenshot y = L + 7
SEAM = 112

HEARTBEAT = 0xE010          # NMI counter (word)
MSK_MATRIX = 0xE020
MSK_ORIGIN = 0xE022
G_FRAMES = 0xE030           # main-loop iteration counter (word)
G_IRQCNT = 0xE050           # seam-IRQ fire counter (word)
G_ENTRY = 0xE054            # entry OPHCT lo/hi, OPVCT lo/hi
G_WAKES = 0xE058            # raw wai-wake counter (word)
G_FIRE = 0xE05A             # post-fire OPHCT lo/hi, OPVCT lo/hi


@pytest.fixture(scope="module")
def roms():
    r = subprocess.run(["make", "build/seam_irq_trial.sfc"], cwd=str(ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"build failed:\n{r.stderr}")
    v = subprocess.run(
        ["bash", "templates/seam_irq_trial/build_seam_irq_trial_variants.sh"],
        cwd=str(ROOT), capture_output=True, text=True)
    if v.returncode != 0:
        pytest.skip(f"variant build failed:\n{v.stderr}")
    return {
        "default": BUILD / "seam_irq_trial.sfc",
        "hdma": BUILD / "seam_irq_trial_hdma.sfc",
        "hv": BUILD / "seam_irq_trial_hv.sfc",
        "mistime": BUILD / "seam_irq_trial_mistime.sfc",
    }


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _grab(runner, tag):
    path = f"/tmp/sf_seamtrial_{tag}.png"
    runner.take_screenshot(path)
    return Image.open(path).convert("RGB").load()


def _diff_rows(pa, pb, w=256, h=239):
    return [y for y in range(h)
            if any(pa[x, y] != pb[x, y] for x in range(w))]


def _latched(runner, base):
    b = runner.read_bytes(WR, base, 4)
    return b[0] | (b[1] << 8), b[2] | (b[3] << 8)   # (H dots, V scanline)


def test_boots(roms, runner):
    for tag, rom in roms.items():
        runner.load_rom(str(rom), run_seconds=1.0)
        assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", f"{tag} did not boot"


def test_s1_structural_channels_freed(roms, runner):
    """IRQ build: matrix pair only ($0C), origin mask 0 — BOTH origin channels
    freed (the whole point of the mechanism). Control: classic origin pair."""
    runner.load_rom(str(roms["default"]), run_seconds=1.0)
    assert runner.read_u16(WR, MSK_MATRIX) == 0x0C, "matrix pair not CH2|CH3"
    assert runner.read_u16(WR, MSK_ORIGIN) == 0x00, \
        "origin channels were allocated on the IRQ build — nothing was freed"
    runner.load_rom(str(roms["hdma"]), run_seconds=1.0)
    assert runner.read_u16(WR, MSK_MATRIX) == 0x0C
    assert runner.read_u16(WR, MSK_ORIGIN) == 0x30, "control origin pair not CH4|CH5"


def test_g1_gold_equivalence_vs_hdma_control(roms, runner):
    """THE trial deliverable: the seam-IRQ + GP-DMA origin renders BYTE-
    IDENTICAL to the HDMA-origin control on the same static scene."""
    runner.load_rom(str(roms["default"]), run_seconds=1.5)
    pa = _grab(runner, "default")
    runner.load_rom(str(roms["hdma"]), run_seconds=1.5)
    pb = _grab(runner, "hdma")
    rows = _diff_rows(pa, pb)
    assert rows == [], f"IRQ vs HDMA control differ on image rows {rows[:8]}"


def test_g2_hv_trigger_same_gate_identical(roms, runner):
    """H+V dot-precision is NOT needed: the -DHV build (H+V trigger through
    the same HBlank spin gate) is also byte-identical to the control."""
    runner.load_rom(str(roms["hv"]), run_seconds=1.5)
    pa = _grab(runner, "hv")
    runner.load_rom(str(roms["hdma"]), run_seconds=1.5)
    pb = _grab(runner, "hdma")
    rows = _diff_rows(pa, pb)
    assert rows == [], f"HV vs HDMA control differ on image rows {rows[:8]}"


def test_g1_mistime_control_flips_metric(roms, runner):
    """NON-VACUITY: firing the SAME DMA at scanline 60 corrupts exactly
    content lines 60..111 (warm origin invades band 1 below the fire line);
    all rows outside that span stay byte-identical to the control."""
    runner.load_rom(str(roms["mistime"]), run_seconds=1.5)
    pa = _grab(runner, "mistime")
    runner.load_rom(str(roms["hdma"]), run_seconds=1.5)
    pb = _grab(runner, "hdma")
    rows = _diff_rows(pa, pb)
    expect = list(range(60 + OFF, SEAM + OFF))      # content lines 60..111
    assert rows == expect, (
        f"mistime corruption span wrong: got {len(rows)} rows "
        f"[{rows[0] if rows else '-'}..{rows[-1] if rows else '-'}], "
        f"want [{expect[0]}..{expect[-1]}]")


def test_h5_cadence_and_irq_lockstep(roms, runner):
    """Loop, NMI and IRQ counters all advance +1 per stepped frame with the
    IRQ armed (WRAM-read based — immune to the frame-stepping video skip)."""
    runner.load_rom(str(roms["default"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        g0 = runner.read_u16(WR, G_FRAMES)
        h0 = runner.read_u16(WR, HEARTBEAT)
        q0 = runner.read_u16(WR, G_IRQCNT)
        for i in range(1, 25):
            runner.frame_step(1)
            g = (runner.read_u16(WR, G_FRAMES) - g0) & 0xFFFF
            h = (runner.read_u16(WR, HEARTBEAT) - h0) & 0xFFFF
            q = (runner.read_u16(WR, G_IRQCNT) - q0) & 0xFFFF
            assert g == i, f"loop missed a frame at step {i}: +{g}"
            assert h == i, f"NMI count skewed at step {i}: +{h}"
            assert q == i, f"IRQ not once-per-frame at step {i}: +{q}"


def test_h1_wai_wakes_on_irq(roms, runner):
    """The H1 hazard, measured: with the seam IRQ armed the loop's wai returns
    ~2x per frame (IRQ + NMI); the gated loop still closes +1/+1 (above).
    Non-vacuity: the HDMA control (no IRQ) wakes ~1x per frame — the same
    metric, flipped by removing the IRQ."""
    runner.load_rom(str(roms["default"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        w0 = runner.read_u16(WR, G_WAKES)
        runner.frame_step(24)
        wakes = (runner.read_u16(WR, G_WAKES) - w0) & 0xFFFF
    assert 46 <= wakes <= 50, f"expected ~48 wakes over 24 frames, got {wakes}"

    runner.load_rom(str(roms["hdma"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        w0 = runner.read_u16(WR, G_WAKES)
        runner.frame_step(24)
        wakes = (runner.read_u16(WR, G_WAKES) - w0) & 0xFFFF
    assert 23 <= wakes <= 25, f"control: expected ~24 wakes over 24 frames, got {wakes}"


def test_w1_fire_window_measured(roms, runner):
    """The measured write window: handler entry during internal scanline 112
    (= VTIME = SEAM; content line 111 draws during scanline 112), fire
    completion inside scanline 113 before its content flush at dot 23."""
    runner.load_rom(str(roms["default"]), run_seconds=1.5)
    eh, ev = _latched(runner, G_ENTRY)
    fh, fv = _latched(runner, G_FIRE)
    print(f"\nmeasured: entry=(H{eh},V{ev}) fire_done=(H{fh},V{fv})")
    assert ev == SEAM, f"entry scanline {ev}, want {SEAM} (internal scanlines)"
    assert eh < 274, f"entry at dot {eh} — already past the HBlank gate?"
    assert fv == SEAM + 1, f"fire completed in scanline {fv}, want {SEAM + 1}"
    assert fh <= 22, (
        f"fire completed at dot {fh} of scanline {fv} — past the content "
        f"flush threshold (22); the seam would left-edge tear")
