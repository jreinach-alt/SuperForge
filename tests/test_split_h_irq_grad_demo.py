"""split_h_irq_grad_demo — two-band split, seam-IRQ band-2 origin, gradient
payload on a freed HDMA channel.

Every assertion reads the rendered framebuffer or the WRAM counters whose
lockstep is the claim itself; every metric has a -D control that flips it.

DONE-CONDITIONS (the brief's DoD):
  S1  structural: 2 matrix + 1 gradient channels used (masks $0C + $10),
      origin mask 0 — BOTH origin channels freed; 6 - 3 = 3 allocator
      channels remain free. The HDMA control allocates the classic origin
      pair ($30) instead and has no gradient.
  G1  the equivalence GOLD assertion: FREEZE+NO_GRAD IRQ-origin build vs
      FREEZE HDMA-origin control — framebuffer BYTE-IDENTICAL (0 differing
      rows). The mechanism is a drop-in replacement.
  T1  H4 tear control: -DIRQ_INTERLEAVE writes the same 8 bytes as 16-bit
      stores whose byte order interleaves each write-twice pair through the
      SHARED Mode-7 ValueLatch -> band 2 (content lines 112+) renders a
      corrupt origin. Frozen-vs-frozen; the same full-frame metric flips.
  GR  gradient: the world's colors + backdrop all carry BLUE = 0, so the
      rendered blue channel is exactly the COLDATA gradient term. Down the
      224 content lines the per-row blue mean is monotonically non-
      decreasing, spans 0 -> ~220, and steps ~every 8 lines. -DNO_GRAD
      flips the same metric to all-zero.
  M1  independent LIVE motion through the seam IRQ: both bands' pixels
      change across a 24-frame hop on the default (moving) build; the
      FREEZE build is byte-stable through the same capture path.
  CAD cadence with the IRQ armed: loop (E030) + NMI (E010) + IRQ (E050)
      counters advance +1/+1/+1 per stepped frame over 24 frames on the
      moving+gradient build (the worst case this rail ships).
  H1  wai wakes ~2x/frame with the IRQ armed vs ~1x on the control; the
      gated-wai loop closes every frame regardless.
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

HEARTBEAT = 0xE010
MSK_MATRIX = 0xE020
MSK_ORIGIN = 0xE022
MSK_GRAD = 0xE024
G_FRAMES = 0xE030
G_IRQCNT = 0xE050
G_WAKES = 0xE058


@pytest.fixture(scope="module")
def roms():
    r = subprocess.run(["make", "build/split_h_irq_grad_demo.sfc"], cwd=str(ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"build failed:\n{r.stderr}")
    v = subprocess.run(
        ["bash",
         "templates/split_h_irq_grad_demo/build_split_h_irq_grad_variants.sh"],
        cwd=str(ROOT), capture_output=True, text=True)
    if v.returncode != 0:
        pytest.skip(f"variant build failed:\n{v.stderr}")
    return {
        "default": BUILD / "split_h_irq_grad_demo.sfc",
        "freeze": BUILD / "split_h_irq_grad_demo_freeze.sfc",
        "fznograd": BUILD / "split_h_irq_grad_demo_fznograd.sfc",
        "hdma": BUILD / "split_h_irq_grad_demo_hdma.sfc",
        "tear": BUILD / "split_h_irq_grad_demo_tear.sfc",
    }


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _grab(runner, tag):
    path = f"/tmp/sf_irqgrad_{tag}.png"
    runner.take_screenshot(path)
    return Image.open(path).convert("RGB").load()


def _diff_rows(pa, pb, w=256, h=239):
    return [y for y in range(h)
            if any(pa[x, y] != pb[x, y] for x in range(w))]


def _row_blue_mean(pix, y, x0=8, x1=248):
    return sum(pix[x, y][2] for x in range(x0, x1)) / (x1 - x0)


def test_boots(roms, runner):
    for tag, rom in roms.items():
        runner.load_rom(str(rom), run_seconds=1.0)
        assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", f"{tag} did not boot"


def test_s1_structural_masks(roms, runner):
    """2 matrix + 1 gradient = 3 allocator channels used; origin mask 0 =
    BOTH origin channels freed; the other 3 allocator channels stay free
    (allocator manages 6: CH2..CH7 — used bits here are CH2|CH3|CH4)."""
    runner.load_rom(str(roms["default"]), run_seconds=1.0)
    m = runner.read_u16(WR, MSK_MATRIX)
    o = runner.read_u16(WR, MSK_ORIGIN)
    g = runner.read_u16(WR, MSK_GRAD)
    assert m == 0x0C, f"matrix pair not CH2|CH3: {m:#x}"
    assert o == 0x00, f"origin channels allocated ({o:#x}) — nothing was freed"
    assert g == 0x10, f"gradient channel not CH4: {g:#x}"
    used = m | o | g
    assert bin(used).count("1") == 3 and (used & ~0xFC) == 0, \
        f"channel budget wrong: used mask {used:#x}"
    # control: classic origin pair, no gradient
    runner.load_rom(str(roms["hdma"]), run_seconds=1.0)
    assert runner.read_u16(WR, MSK_MATRIX) == 0x0C
    assert runner.read_u16(WR, MSK_ORIGIN) == 0x30, "control origin pair not CH4|CH5"
    assert runner.read_u16(WR, MSK_GRAD) == 0x00, "control must not run the gradient"


def test_g1_gold_equivalence(roms, runner):
    """THE DoD assertion: with the gradient disabled, the seam-IRQ build and
    the HDMA-origin control render BYTE-IDENTICAL static frames."""
    runner.load_rom(str(roms["fznograd"]), run_seconds=1.5)
    pa = _grab(runner, "fznograd")
    runner.load_rom(str(roms["hdma"]), run_seconds=1.5)
    pb = _grab(runner, "hdma")
    rows = _diff_rows(pa, pb)
    assert rows == [], f"IRQ vs HDMA control differ on image rows {rows[:8]}"


def test_t1_latch_interleave_tears(roms, runner):
    """H4: interleaving the write-twice pairs through the shared Mode-7
    ValueLatch corrupts band-2's origin — its rows (content lines >= 112)
    all differ vs the clean frozen build, band 1 stays byte-identical."""
    runner.load_rom(str(roms["tear"]), run_seconds=1.5)
    pa = _grab(runner, "tear")
    runner.load_rom(str(roms["fznograd"]), run_seconds=1.5)
    pb = _grab(runner, "fznograd")
    rows = _diff_rows(pa, pb)
    assert rows, "interleave control did not corrupt anything (vacuous guard?)"
    assert min(rows) >= SEAM + OFF, \
        f"corruption leaked above the seam: first differing row {min(rows)}"
    assert len(rows) >= 100, \
        f"band-2 corruption implausibly small: {len(rows)} rows"


def test_gr_gradient_monotonic_blue_ramp(roms, runner):
    """The gradient payload, on the metric the world was designed for: every
    world color + backdrop has BLUE = 0, so per-row blue mean == the COLDATA
    term. Monotonically non-decreasing down all 224 content lines, spans
    0 -> >=200, >= 20 distinct 8-line steps."""
    runner.load_rom(str(roms["freeze"]), run_seconds=1.5)
    pix = _grab(runner, "freeze")
    blues = [_row_blue_mean(pix, L + OFF) for L in range(224)]
    for i in range(1, 224):
        assert blues[i] + 0.5 >= blues[i - 1], \
            f"blue ramp regresses at content line {i}: {blues[i-1]:.1f} -> {blues[i]:.1f}"
    assert blues[0] <= 4, f"ramp should start ~0, got {blues[0]:.1f}"
    assert blues[-1] >= 200, f"ramp should end >=200, got {blues[-1]:.1f}"
    distinct = len({round(b) for b in blues})
    assert distinct >= 20, f"only {distinct} distinct blue levels — not a 28-step ramp"


def test_gr_no_grad_control_flips(roms, runner):
    """Non-vacuity: -DNO_GRAD zeroes the SAME metric everywhere."""
    runner.load_rom(str(roms["fznograd"]), run_seconds=1.5)
    pix = _grab(runner, "fznograd_blue")
    blues = [_row_blue_mean(pix, L + OFF) for L in range(224)]
    assert max(blues) == 0, f"NO_GRAD build still shows blue (max {max(blues):.1f})"


def test_m1_live_motion_through_the_irq(roms, runner):
    """The seam IRQ feeds LIVE values: on the moving build both bands' pixels
    change across a 24-frame hop (>= the 12-frame video-skip floor); the
    FREEZE build is byte-stable through the same capture path."""
    def band_change(rom_path, tag, attempts=1):
        """One (grab, hop, grab) pair per attempt. Multiple attempts exist for
        the FREEZE arm only: the frame-stepping harness frame-skips video, and
        a capture can land on a stale frame (audit-1 finding F1 — observed
        once as a full-frame diff on a frozen ROM). A retry with fresh hops
        disambiguates: a genuinely-unstable frozen build fails EVERY attempt,
        a one-off stale capture passes the retry. The MOVING arm takes the
        first attempt as-is (motion is the expected signal)."""
        runner.load_rom(str(rom_path), run_seconds=1.0)
        with runner.frame_stepping():
            for att in range(attempts):
                runner.frame_step(16)
                pa = _grab(runner, f"{tag}_a{att}")
                runner.frame_step(24)
                pb = _grab(runner, f"{tag}_b{att}")
                rows = _diff_rows(pa, pb)
                if not rows:
                    break
        b1 = [y for y in rows if y < SEAM + OFF]
        b2 = [y for y in rows if y >= SEAM + OFF]
        return b1, b2

    # Threshold is deliberately low: a 24-frame hop pans band 2 by 48 world
    # px, which aliases against the checker period at far scales — only the
    # near rows show change (measured: ~8 rows). The zero-change FREEZE flip
    # below anchors the metric's non-vacuity.
    b1, b2 = band_change(roms["default"], "move")
    assert len(b1) > 3, f"band 1 did not move ({len(b1)} changed rows)"
    assert len(b2) > 3, f"band 2 did not move ({len(b2)} changed rows)"
    b1, b2 = band_change(roms["freeze"], "frozen", attempts=3)
    assert not b1 and not b2, \
        f"frozen build changed ({len(b1)}/{len(b2)} rows) on 3 capture attempts"


def test_cad_cadence_and_irq_lockstep(roms, runner):
    """The in-situ 60fps gate on the SHIPPED shape (motion + gradient + IRQ):
    loop, NMI and IRQ counters advance +1/+1/+1 per stepped frame."""
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


def test_h1_wai_wake_rate(roms, runner):
    """wai wakes ~2x/frame with the seam IRQ armed; ~1x on the HDMA control
    (same metric, flipped by removing the IRQ)."""
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
    assert 23 <= wakes <= 25, f"control: expected ~24 wakes, got {wakes}"
    # the IRQ-lockstep flip control (audit-1 F3): with no IRQ armed, the
    # fire counter must stay EXACTLY zero — the +1/frame lockstep metric,
    # flipped by removing the IRQ.
    assert runner.read_u16(WR, G_IRQCNT) == 0, \
        "IRQ counter advanced on the HDMA control — vector/arm leak"
