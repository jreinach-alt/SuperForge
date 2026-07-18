"""split_h_persp_demo — Archetype C-horiz PERSPECTIVE rail: framebuffer tests.

TWO vertically-stacked, independently-animating Mode-7 perspective cameras over
ONE shared world (the 2-player top/bottom racer pattern). Every assertion READS
THE RENDERED FRAMEBUFFER via MesenRunner + Pillow (kit rule #2 — never a proxy
variable). Mechanism: the engine perspective renderer (sf_mode7_tick -> pv_rebuild,
CH5/CH6, per-scanline REPEAT-mode trapezoid, camera A) is POST-PATCHED each frame —
band-2 [SEAM..L1) of the ACTIVE AB/CD buffer is overwritten with a SECOND camera B
(mode7_band_splice, which consults pv_buffer and writes the freshly-flipped active
buffer). Camera A auto-rotates (live solve); camera B zoom-loops through KPOSES
precomputed near-scale poses (the budget/double-buffer-safe substitute for a second
live solve).

INDEPENDENT WORLD POSITION (camera-pos capability): camera B is not merely a
different SCALE/ANGLE of camera A's spot — it is panned to a DIFFERENT WORLD
LOCATION. Its whole Mode-7 ORIGIN is spliced per band via HDMA: CH2 drives the
centre M7X/M7Y ($211F/$2120) and CH3 the scroll M7HOFS/M7VOFS ($210D/$210E), both
DMAP $03 (write-2-registers-twice), NON-REPEAT (2 HBlank transfers/frame each).
The world map paints WARM (red-tinted) / COOL (no-red) stripes with an IDENTICAL
green+blue checker, so the RED channel is a pure position signal (which stripe a
camera views) orthogonal to the green+blue period/luminance signal. C1-C3 cover it.

DONE-CONDITIONS covered:
  C1  band-2 shows a DIFFERENT WORLD REGION than band-1 (panned +256 world px into
      the red stripe), read as the red channel; -DSAME_CENTER control folds the
      origin back onto camera A -> band-2 not red -> the C1 assertion FAILS.
  C2  the origin splice keeps a single crisp seam (red-content boundary at SEAM).
  C3  the panned band-2 world region is temporally stable (no origin-splice desync).
  P1  two DISTINCT camera floors (period differs) AND each band animates on its
      OWN driver (camera A rotates while B held; camera B zoom-loops while A frozen).
  P2  exactly ONE clean single-scanline seam, at EXACTLY PPU scanline SEAM
      (the +7 screenshot-row offset is modeled), with the -DNO_SEAM control
      proving the seam-pair metric goes quiet when the splice is off.
  P3  TEMPORAL STABILITY (the flicker fix): across 12 CONSECUTIVE deterministic
      frames the band-2 region is byte-for-byte stable (no 30 Hz double-buffer
      desync), even though pv_rebuild flips the double buffer every frame.
      NEGATIVE CONTROL: -DFIXED_BUFFER_SPLICE (splice into a FIXED buffer, ignoring
      pv_buffer) reinstates the bug -> band-2 alternates camera-B/camera-A across
      frames -> the SAME stability metric FAILS. This is what proves P3 catches it.
  P4  -DNO_SEAM: both bands = camera A -> the "two bands differ" (P1) signal ABSENT.
  P5  -DFREEZE -DHOLD_B -DLATCH_VIOLATION (stilllatch): a code-side write-twice
      to a shared-latch register during active display -> the frozen floor TEARS
      vs the frozen still build on the SAME jitter metric (frozen-vs-frozen; the
      original rotating-vs-frozen comparison was confounded by scene motion).
  CAD in-situ loop-cadence gate: pv_buffer must flip EVERY stepped frame (WRAM
      read — immune to the frame-stepping video-skip artifact). XFAIL at HEAD:
      the shipped loop closes every 2nd frame (30 Hz motion, PR #223 review M1);
      the -DNO_SEAM control proves the metric passes on a true-60 build.

The deterministic frame-step path (debug_break/frame_step) is what makes P3
meaningful: run_frames() only sleeps while the emulator free-runs, so a single
settled grab lands on whichever ~30 Hz phase the wall clock hits — blind to
alternation. frame_step advances EXACTLY one PPU frame per call and parks at a
fixed pipeline position, so consecutive-frame captures are bit-deterministic.
"""
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

WR = MemoryType.SnesWorkRam
PV_BUFFER = 0x01C6              # engine M7_PV_BUFFER: the double-buffer index (0/1)
NMI_HDMA_ENABLE = 0x0108

# Per-scanline matrix double-buffer (mode7_hdma.asm): buffer 0 AB = $7E:A000,
# buffer 1 AB = $7E:A900. The buffer is PV_L0-relative — buffer index 0 == screen
# scanline PV_L0 — and the demo sets PV_L0 = 0, so buffer index == screen scanline.
# Each scanline entry is 4 bytes: M7A (s16), M7B (s16). M7A = base + idx*4.
PV_HDMA_AB0 = 0xA000
PV_HDMA_AB1 = 0xA900

SEAM = 112

# Harness screenshots are 256x239 with 7 blank padding rows on top: PPU scanline
# L renders at image y = L + OFF. Assertions that pin an exact scanline (P2 seam
# pair, C2 red step) MUST model this — the original P2 sampled y 100-113 and
# never contained the real seam (screenshot y 118->119 = PPU 111->112), making
# it fully vacuous (PR #223 independent review, finding M3).
OFF = 7

TOP_ROWS = (60, 70, 80, 90, 100)                # camera A band (above the seam)
BOT_ROWS = (120, 130, 140, 150, 160, 170, 180)  # camera B band (below the seam)


def _find_root(p):
    for d in [p] + list(p.parents):
        if (d / "Makefile").exists():
            return d
    return p.parent.parent
ROOT = _find_root(Path(__file__).resolve())
BUILD = ROOT / "build"


def _px(img):
    return img.load()


def _transition_xs(pix, y, x0=20, x1=236, thresh=60):
    xs, prev = [], pix[x0, y]
    for x in range(x0 + 1, x1):
        c = pix[x, y]
        if abs(c[0] - prev[0]) + abs(c[1] - prev[1]) + abs(c[2] - prev[2]) > thresh:
            xs.append(x)
        prev = c
    return xs


def _mean_period(pix, y):
    xs = _transition_xs(pix, y)
    if len(xs) < 2:
        return None
    return sum(xs[i + 1] - xs[i] for i in range(len(xs) - 1)) / (len(xs) - 1)


def _first_transition_x(pix, y, x0=20, x1=236, thresh=60):
    prev = pix[x0, y]
    for x in range(x0 + 1, x1):
        c = pix[x, y]
        if abs(c[0] - prev[0]) + abs(c[1] - prev[1]) + abs(c[2] - prev[2]) > thresh:
            return x
        prev = c
    return None


def _row_jitter(pix, y0, y1):
    xs = [_first_transition_x(pix, y) for y in range(y0, y1)]
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    return sum(abs(xs[i + 1] - xs[i]) for i in range(len(xs) - 1)) / (len(xs) - 1)


def _row_lum_sig(pix, y, x0=20, x1=236):
    return [1 if (pix[x, y][1] + pix[x, y][2]) > 300 else 0 for x in range(x0, x1)]


def _band_sig(pix, rows):
    """A compact per-band luminance signature (concatenated row bit-vectors).
    Reads rendered pixels only; used to measure whether a band CHANGED."""
    sig = []
    for y in rows:
        sig.extend(_row_lum_sig(pix, y))
    return sig


def _sig_diff(a, b):
    return sum(1 for i in range(min(len(a), len(b))) if a[i] != b[i])


def _mean_band_period(pix, rows):
    ps = [_mean_period(pix, y) for y in rows]
    ps = [p for p in ps if p]
    return sum(ps) / len(ps) if ps else None


def _mean_red(pix, rows, x0=30, x1=226):
    """Mean RED channel over a band. The world map paints WARM (red-tinted)
    stripes and COOL (no-red) stripes with an IDENTICAL green+blue checker, so the
    red channel is a pure WORLD-POSITION signal (which stripe a camera views),
    orthogonal to the green+blue period/luminance signal the other tests read.
    Reads rendered FRAMEBUFFER pixels only."""
    tot = n = 0
    for y in rows:
        for x in range(x0, x1):
            tot += pix[x, y][0]
            n += 1
    return tot / n if n else 0.0


def _band_red_sig(pix, rows, x0=20, x1=236):
    """Per-band RED-channel bit signature (position-sensitive), for temporal
    stability of the panned band-2 (its cool/G+B signature is identical to
    band-1's, so a red-aware signature is what proves the RED world region is
    stable frame-to-frame)."""
    sig = []
    for y in rows:
        sig.extend(1 if pix[x, y][0] > 128 else 0 for x in range(x0, x1))
    return sig


def _grab(runner, tag, settle=20):
    runner.run_frames(settle)
    Path("/tmp/e2e_screenshots").mkdir(parents=True, exist_ok=True)
    path = f"/tmp/e2e_screenshots/{tag}.png"
    runner.take_screenshot(path)
    return Image.open(path).convert("RGB")


def _step_capture(runner, tag, n_frames, settle=20):
    """DETERMINISTIC per-frame capture: park at a frame boundary, then advance
    EXACTLY one PPU frame per screenshot. Returns a list of PIL images, one per
    consecutive frame. This is the only path that can observe ~30 Hz alternation
    (run_frames free-runs and is phase-blind)."""
    Path("/tmp/e2e_screenshots").mkdir(parents=True, exist_ok=True)
    runner.run_frames(settle)
    imgs, bufs = [], []
    with runner.frame_stepping():
        for i in range(n_frames):
            runner.frame_step(1)
            bufs.append(runner.read_bytes(WR, PV_BUFFER, 1)[0])
            path = f"/tmp/e2e_screenshots/{tag}_{i:02d}.png"
            runner.take_screenshot(path)
            imgs.append(Image.open(path).convert("RGB"))
    return imgs, bufs


def _max_consecutive_band_diff(imgs, rows):
    """MAX luminance-signature change between consecutive frames in a band."""
    sigs = [_band_sig(_px(im), rows) for im in imgs]
    return max((_sig_diff(sigs[i], sigs[i + 1]) for i in range(len(sigs) - 1)),
               default=0)


def _max_row_jitter_window(runner, tag, y0, y1, n_frames=6, settle=20):
    """MAX per-scanline jitter over consecutive frames (phase-insensitive)."""
    Path("/tmp/e2e_screenshots").mkdir(parents=True, exist_ok=True)
    runner.run_frames(settle)
    best = 0.0
    for i in range(n_frames):
        path = f"/tmp/e2e_screenshots/{tag}_{i}.png"
        runner.take_screenshot(path)
        best = max(best, _row_jitter(_px(Image.open(path).convert("RGB")), y0, y1))
        runner.run_frames(1)
    return best


def _read_active_m7a(runner, n=224):
    """Read the per-scanline M7A coefficient array FROM THE ACTIVE HDMA buffer —
    the exact bytes the PPU's CH5 matrix DMA streams this frame (not a proxy).
    Follows pv_buffer ($01C6) to the active AB base ($A000 buffer 0 / $A900 buffer
    1), then decodes M7A as a signed 16-bit at base + idx*4 (idx == screen scanline
    since PV_L0 == 0)."""
    buf = runner.read_bytes(WR, PV_BUFFER, 1)[0]
    base = PV_HDMA_AB0 if buf == 0 else PV_HDMA_AB1
    raw = bytes(runner.read_bytes(WR, base, n * 4))
    return [struct.unpack_from("<h", raw, i * 4)[0] for i in range(n)], buf


@pytest.fixture(scope="module")
def roms():
    r = subprocess.run(["make", "build/split_h_persp_demo.sfc"], cwd=str(ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"build failed:\n{r.stderr}")
    v = subprocess.run(
        ["bash", "templates/split_h_persp_demo/build_split_h_persp_variants.sh"],
        cwd=str(ROOT), capture_output=True, text=True)
    if v.returncode != 0:
        pytest.skip(f"variant build failed:\n{v.stderr}")
    return {
        "default": BUILD / "split_h_persp_demo.sfc",
        "noseam": BUILD / "split_h_persp_demo_noseam.sfc",
        "stillnoseam": BUILD / "split_h_persp_demo_stillnoseam.sfc",
        "latch": BUILD / "split_h_persp_demo_latch.sfc",
        "stilllatch": BUILD / "split_h_persp_demo_stilllatch.sfc",
        "holdb": BUILD / "split_h_persp_demo_holdb.sfc",
        "freeze": BUILD / "split_h_persp_demo_freeze.sfc",
        "still": BUILD / "split_h_persp_demo_still.sfc",
        "stillfixed": BUILD / "split_h_persp_demo_stillfixed.sfc",
        "stillsame": BUILD / "split_h_persp_demo_stillsame.sfc",
        "sky": BUILD / "split_h_persp_demo_sky.sfc",
        "stillsky": BUILD / "split_h_persp_demo_stillsky.sfc",
    }


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def test_boots(roms, runner):
    runner.load_rom(str(roms["default"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "default ROM did not boot"


def _cadence_flips(runner, rom_path, n=16):
    """Frame-step a build and return (per-frame pv_buffer flip flags, heartbeat
    deltas). WRAM reads ONLY — frame_stepping() frame-skips the video output
    (consecutive stepped screenshots alias even on a true-60 ROM), so pixel
    metrics are off-limits here; pv_buffer ($01C6 = M7_PV_BUFFER, flipped once
    per pv_rebuild == once per game-loop iteration) is the loop-rate signal."""
    runner.load_rom(str(rom_path), run_seconds=0.5)
    with runner.frame_stepping():
        runner.frame_step(1)
        prev = runner.read_bytes(WR, PV_BUFFER, 1)[0]
        hb_prev = runner.read_u16(WR, 0xE010)
        flips, hb_deltas = [], []
        for _ in range(n):
            runner.frame_step(1)
            buf = runner.read_bytes(WR, PV_BUFFER, 1)[0]
            hb = runner.read_u16(WR, 0xE010)
            flips.append(buf != prev)
            hb_deltas.append((hb - hb_prev) & 0xFFFF)
            prev, hb_prev = buf, hb
    return flips, hb_deltas


@pytest.mark.xfail(
    strict=True,
    reason="PR #223 independent review, finding M1: the shipped integrated loop "
    "(interp4 solve ~92.6% HDMA-on + band-2 splice ~85k mc = 23.9% + origin "
    "restamp) totals ~110-120% of a frame; the sf_frame handshake quantizes the "
    "overrun to 2 frames -> pv_rebuild runs every 2nd frame (30 Hz pose motion; "
    "measured pv_buffer flips 8/16 stepped frames). Flips loudly to XPASS when "
    "the band-1-only rebuild follow-up (rebuild [PV_L0..SEAM) only, measured "
    "~75-81% total) lands.")
def test_cadence_true_60fps_in_situ(roms, runner):
    """IN-SITU LOOP-CADENCE GATE (the gate whose absence let the false 'true
    60 fps' headline ship): frame-step the default rotating build and assert the
    game loop closes EVERY frame — pv_buffer ($01C6) flips once per pv_rebuild,
    i.e. once per loop iteration, so a true-60 loop alternates it every stepped
    frame. Also asserts the E010 heartbeat advances +1/frame (the loop copies
    FRAME_COUNTER; a 2-frame loop shows +2,0,+2,0 — measured at HEAD).

    NON-VACUITY: test_cadence_metric_noseam_control runs the SAME metric on the
    -DNO_SEAM build (solve only, no splice — measured true 60 fps) and PASSES,
    proving the metric can distinguish the two loop rates. WRAM reads only —
    immune to the frame-stepping video-skip harness artifact."""
    flips, hb_deltas = _cadence_flips(runner, roms["default"])
    assert all(flips), (
        f"game loop did not close every frame: pv_buffer flipped only "
        f"{sum(flips)}/{len(flips)} stepped frames (flip pattern {flips}) — "
        f"the loop is running at a sub-60fps cadence")
    assert all(d == 1 for d in hb_deltas), (
        f"heartbeat not +1/frame: deltas {hb_deltas}")


def test_cadence_metric_noseam_control(roms, runner):
    """NON-VACUITY CONTROL for the cadence gate: the -DNO_SEAM build compiles
    the band-2 splice out, leaving solve-only per-frame work that fits one frame
    (review M1 measurement 4: every splice-free build runs true 60 fps) — the
    SAME pv_buffer-flip + heartbeat metric must PASS here. Measured: flips
    16/16, heartbeat deltas all +1. If the metric were broken (e.g. pv_buffer
    address wrong, stepping misbehaving) this control would fail too, instead
    of the xfail above silently 'confirming' a fake finding."""
    flips, hb_deltas = _cadence_flips(runner, roms["noseam"])
    assert all(flips), (
        f"noseam control loop not at 60fps: pv_buffer flipped "
        f"{sum(flips)}/{len(flips)} stepped frames ({flips}) — either the "
        f"solve-only budget regressed or the cadence metric is broken")
    assert all(d == 1 for d in hb_deltas), (
        f"noseam control heartbeat not +1/frame: {hb_deltas}")


def test_p1_two_distinct_perspective_views(roms, runner):
    """P1 (distinct): band-2 (camera B, spliced) has a MEASURABLY different
    on-screen texel period than the SAME rows with camera A everywhere. Both
    builds freeze camera A (angle 0) so the comparison isolates camera-B-vs-A.
    Reads FRAMEBUFFER pixels."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    bpix = _px(_grab(runner, "persp_still"))
    runner.load_rom(str(roms["stillnoseam"]), run_seconds=0.5)
    apix = _px(_grab(runner, "persp_stillnoseam"))
    rels = []
    for y in BOT_ROWS:
        bp, ap = _mean_period(bpix, y), _mean_period(apix, y)
        if bp and ap:
            rels.append(abs(bp - ap) / max(bp, ap))
    assert rels, "no measurable checker period in the bottom band"
    mean_rel = sum(rels) / len(rels)
    assert mean_rel > 0.20, (
        f"bottom band is not a distinct camera: mean relative period diff "
        f"{mean_rel:.3f} (camera B vs camera A, both frozen)")


def test_p1_camera_a_animates_independently(roms, runner):
    """P1 (camera A independent): -DHOLD_B holds camera B's matrix at pose 0 while
    camera A auto-rotates. Over consecutive deterministic frames the TOP band
    (camera A) CHANGES — camera A animates on its OWN driver, with camera B's pose
    NOT advancing (so the motion is camera A's alone, not camera B's).

    NOTE: we do NOT assert the bottom band is constant here — both bands share the
    GLOBAL Mode-7 M7X/M7Y origin (per-band differences live only in the spliced
    per-scanline matrix), so camera A's rotation moves the origin and thus repaints
    band-2 too. Camera B's OWN-driver independence is proven separately by the
    -DFREEZE test (camera A frozen -> only band-2 moves). Reads FRAMEBUFFER."""
    runner.load_rom(str(roms["holdb"]), run_seconds=0.5)
    imgs, _ = _step_capture(runner, "persp_holdb", 8)
    top_change = _max_consecutive_band_diff(imgs, TOP_ROWS)
    assert top_change > 40, (
        f"camera A did not animate (top band static): max change {top_change}px")


def test_p1_camera_b_animates_independently(roms, runner):
    """P1 (camera B independent): -DFREEZE freezes camera A (angle 0) while camera
    B zoom-loops. Over consecutive deterministic frames the BOTTOM band (camera B)
    CHANGES while the TOP band (camera A) stays CONSTANT — camera B moves on its
    own driver, independent of camera A. Reads per-frame FRAMEBUFFER signatures."""
    runner.load_rom(str(roms["freeze"]), run_seconds=0.5)
    imgs, _ = _step_capture(runner, "persp_freeze", 20)
    top_change = _max_consecutive_band_diff(imgs, TOP_ROWS)
    bot_change = _max_consecutive_band_diff(imgs, BOT_ROWS)
    assert bot_change > 40, (
        f"camera B did not animate (bottom band static): max change {bot_change}px")
    assert top_change < 10, (
        f"camera A moved when it should be frozen (top change {top_change}px)")


def _pair_diff(pix, y):
    """G+B luminance-signature change between screenshot rows y and y+1."""
    a, b = _row_lum_sig(pix, y), _row_lum_sig(pix, y + 1)
    return sum(1 for i in range(len(a)) if a[i] != b[i])


def test_p2_clean_single_scanline_seam(roms, runner):
    """P2: the camera A->B seam is ONE crisp transition row at EXACTLY PPU
    scanline SEAM (112), adjacent rows near-unchanged — no multi-row smear.
    Deterministic still build; the +7 screenshot offset is MODELED: the seam is
    the pair y = SEAM+OFF-1 -> SEAM+OFF (118->119), i.e. PPU 111 (camera A's
    last row) vs PPU 112 (camera B's first row).

    Thresholds from measurement (this harness, still build): the seam pair's
    G+B signature diff = 108; the quiet rows within +/-4 of the seam measure
    <=5; the -DNO_SEAM control's seam pair = 2. Positive bar >60 (1.8x below
    the measured seam, 12x above the quiet floor); quiet/control bar <30.
    Checker row-edges inside a band produce FALSE peaks of ~216 (measured at
    y=104 and y=128) — the original window-max design latched onto exactly such
    an edge, which is why this test pins the seam LOCATION instead of hunting a
    window maximum (PR #223 review, M3).

    NOSEAM CONTROL (non-vacuity): the stillnoseam build compiles the band-2
    splice out -> both bands are camera A -> the SAME seam-pair metric goes
    quiet (measured 2). A metric that stays loud without the splice would be
    measuring checker texture, not the seam."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    pix = _px(_grab(runner, "persp_seam"))
    seam_pair = SEAM + OFF - 1          # y=118 vs y=119 == PPU 111 vs PPU 112
    seam_d = _pair_diff(pix, seam_pair)
    assert seam_d > 60, (
        f"no crisp camera A->B seam at PPU {SEAM} (screenshot pair "
        f"{seam_pair}->{seam_pair + 1}): G+B signature diff {seam_d} "
        f"(measured 108 on the good build)")
    # crispness: the +/-4 adjacent row pairs are quiet — a mid-active-display
    # smear would spread the transition across several rows.
    for y in range(seam_pair - 4, seam_pair + 5):
        if y == seam_pair:
            continue
        d = _pair_diff(pix, y)
        assert d < 30, (
            f"seam smeared: adjacent row pair {y}->{y + 1} changed {d}px "
            f"(quiet floor measured <=5)")
    # NOSEAM control: the exact same metric must go quiet without the splice.
    runner.load_rom(str(roms["stillnoseam"]), run_seconds=0.5)
    npix = _px(_grab(runner, "persp_seam_noseam_ctrl"))
    ctrl_d = _pair_diff(npix, seam_pair)
    assert ctrl_d < 30, (
        f"NOSEAM control still shows a seam signature ({ctrl_d}px at pair "
        f"{seam_pair}->{seam_pair + 1}) — P2's metric is not measuring the "
        f"camera A->B splice")


def test_p3_matrix_seam_data_in_active_buffer(roms, runner):
    """#3 (matrix/seam DATA): read the per-scanline M7A coefficients straight from
    the ACTIVE double-buffer — the bytes CH5's matrix HDMA feeds the PPU this frame,
    NOT a proxy variable — and prove the seam lives EXACTLY at scanline SEAM in the
    data. Frozen build (still) so the table is static.

    - Camera-A region (idx 0..SEAM-1) is a SMOOTH perspective ramp: M7A is monotonic
      non-increasing (the engine interpolates in 0/-4 steps), so NO positive jump.
    - Camera B's band starts EXACTLY at idx == SEAM with a clear M7A discontinuity
      (a large positive jump — camera B's far scale vs camera A's near foreground),
      and there is NO such jump anywhere in camera A's interior. A PV_L0 off-by-one
      would slide this jump off SEAM and FAIL — this guards seam placement in the
      exact data the PPU consumes."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    runner.run_frames(20)
    m7a, buf = _read_active_m7a(runner)
    JUMP = 20                                   # a "clear discontinuity" threshold
    # Camera A interior: consecutive transitions strictly within idx 0..SEAM-1.
    a_diffs = [m7a[i + 1] - m7a[i] for i in range(SEAM - 1)]
    a_max_up = max(a_diffs)
    assert a_max_up < JUMP, (
        f"camera-A ramp is not monotonic non-increasing (buf={buf}): a positive "
        f"jump of {a_max_up} within idx 0..{SEAM - 1} — perspective ramp is broken "
        f"or the seam leaked into camera A's band")
    # The seam: a large positive discontinuity at EXACTLY idx == SEAM.
    seam_jump = m7a[SEAM] - m7a[SEAM - 1]
    assert seam_jump >= JUMP, (
        f"no camera-A->B discontinuity at idx == SEAM ({SEAM}): jump {seam_jump} "
        f"(m7a[{SEAM}]={m7a[SEAM]} m7a[{SEAM - 1}]={m7a[SEAM - 1]}, buf={buf}) — the "
        f"seam is not where PV_L0/SEAM place it in the buffer the PPU consumes")


def test_p3_guarded_default_is_clean(roms, runner):
    """P3 (clean): low per-scanline horizontal jitter in BOTH bands — the
    perspective trapezoids are smooth. Deterministic still build."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    pix = _px(_grab(runner, "persp_clean_p3"))
    jt, jb = _row_jitter(pix, 50, 105), _row_jitter(pix, 120, 200)
    assert jt < 2.5 and jb < 2.5, f"not clean: jitter top={jt:.1f} bot={jb:.1f}"


def test_p3_temporal_stability(roms, runner):
    """P3 (THE FIX — temporal stability): across 12 CONSECUTIVE deterministic
    frames the band-2 region is byte-stable, even though pv_rebuild flips the
    double buffer every frame (the pv_buffer flag is observed to take BOTH values
    across the window). The correct apply-hook re-splices camera B into the
    freshly-flipped ACTIVE buffer every frame, so no frame reverts to camera A.

    Reads OUTPUT, not a proxy: each frame's band-2 luminance signature is captured
    from the rendered framebuffer; the metric is the MAX signature change between
    any two consecutive frames. A stable band == 0 (identical every frame)."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    imgs, bufs = _step_capture(runner, "persp_temporal", 12)
    assert len(set(bufs)) == 2, (
        f"double buffer did not flip across the window (pv_buffer={bufs}); the "
        f"stability test is only meaningful while the buffer alternates")
    bot_change = _max_consecutive_band_diff(imgs, BOT_ROWS)
    assert bot_change <= 4, (
        f"band-2 is NOT temporally stable: max consecutive-frame change "
        f"{bot_change}px across 12 frames (pv_buffer={bufs}) — a 30 Hz flicker")


def test_p3_fixed_buffer_control_flickers(roms, runner):
    """P3 NEGATIVE CONTROL (-DFIXED_BUFFER_SPLICE): the same static scene, but the
    splice targets the FIXED buffer 0 (ignoring pv_buffer). On the ~30 Hz of frames
    where pv_rebuild flipped to buffer 1, band-2 reverts to camera A -> a large
    consecutive-frame change. The SAME metric that PASSES for the correct build
    (<=4 px) MUST FAIL here — this is what proves the P3 test catches the bug."""
    runner.load_rom(str(roms["stillfixed"]), run_seconds=0.5)
    imgs, bufs = _step_capture(runner, "persp_fixed_ctrl", 12)
    bot_change = _max_consecutive_band_diff(imgs, BOT_ROWS)
    assert bot_change > 40, (
        f"the fixed-buffer control did NOT flicker (max change {bot_change}px, "
        f"pv_buffer={bufs}) — the P3 negative control is vacuous")


def test_p4_noseam_control_single_camera(roms, runner):
    """P4 NON-VACUITY (-DNO_SEAM): both bands are camera A -> the bottom band is a
    smooth continuation of the top floor, NOT a distinct camera (period grows
    ~monotonically toward the foreground, no abrupt regime change at the seam).
    Uses the frozen stillnoseam build so the period ramp is deterministic (the
    free-running noseam build's camera A rotates, perturbing the ramp)."""
    runner.load_rom(str(roms["stillnoseam"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "noseam ROM did not boot"
    npix = _px(_grab(runner, "persp_noseam_ctrl"))
    periods = [_mean_period(npix, y) for y in (90, 110, 130, 150, 170)]
    periods = [p for p in periods if p]
    assert len(periods) >= 4, f"could not measure period ramp: {periods}"
    assert all(periods[i + 1] >= periods[i] - 3 for i in range(len(periods) - 1)), (
        f"noseam floor is not a single continuous camera: periods={periods}")


def test_p5_latch_violation_corrupts(roms, runner):
    """P5 NEGATIVE CONTROL (-DFREEZE -DHOLD_B -DLATCH_VIOLATION): a code-side
    write-twice to M7HOFS/VOFS ($210D/$210E) during active display, while the
    per-scanline REPEAT-mode matrix HDMA streams, TEARS the floor — per-scanline
    jitter multiplies vs the clean build on the SAME metric.

    FROZEN-vs-FROZEN (the PR #223 M3 fix, same pattern as the 2p rail's
    test_p5_latch_violation_tears): the original compared a ROTATING latch build
    against one settled frame of the frozen still build — rotation alone beats a
    2x threshold (measured: the untampered rotating default reaches jitter 7.1
    vs the frozen 0.56 baseline), so the untampered build passed as "corrupted"
    and the test attributed scene motion to the latch. Both sides now FREEZE
    both cameras, so the only difference is the violation itself.

    Thresholds from measurement (this harness): frozen clean = 0.556; frozen
    stilllatch = 5.519 (a ~10x separation), with occasional clean-phase samples
    (1 of 8 measured 0.556 — the collision phase drifts), hence MAX over a
    10-frame window. Bar: >2x max(clean, 0.5) = ~1.11 — 5x below the measured
    tear, 2x above the clean floor."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    clean_jit = _row_jitter(_px(_grab(runner, "persp_clean_ref")), 50, 105)
    runner.load_rom(str(roms["stilllatch"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "stilllatch ROM did not boot"
    latch_jit = _max_row_jitter_window(runner, "persp_latch", 50, 105,
                                       n_frames=10)
    assert latch_jit > 2.0 * max(clean_jit, 0.5), (
        f"latch violation did not corrupt (frozen-vs-frozen): "
        f"clean={clean_jit:.2f} max latch over window={latch_jit:.2f}")


def test_c1_band2_independent_world_position(roms, runner):
    """C1 (the NEW capability — independent WORLD POSITION): camera B is panned
    +256 world px to world X 768 (the WARM/red stripe) while camera A stays at
    world X 512 (the COOL stripe). Band-2 therefore shows a DIFFERENT WORLD REGION
    than band-1 — not merely a different zoom of the same spot. Read as the mean
    RED channel (the position-only signal): band-2 is strongly red, band-1 is not.
    FRAMEBUFFER pixels only. Deterministic still build."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    pix = _px(_grab(runner, "campos_c1_still"))
    top_r = _mean_red(pix, TOP_ROWS)     # camera A — cool stripe (world X 512)
    bot_r = _mean_red(pix, BOT_ROWS)     # camera B — warm stripe (world X 768)
    assert top_r < 20, f"band-1 (camera A) unexpectedly red: mean R={top_r:.1f}"
    assert bot_r > 80, (
        f"band-2 did NOT pan to the red world region: mean R={bot_r:.1f} — the "
        f"per-band M7X/M7Y + M7HOFS/M7VOFS origin splice is not panning the view")
    assert bot_r - top_r > 60, (
        f"band-2/band-1 world content not distinct by position: "
        f"bot R={bot_r:.1f} top R={top_r:.1f}")


def test_c1_same_center_control_no_pan(roms, runner):
    """C1 NON-VACUITY (-DSAME_CENTER): camera B's whole ORIGIN (M7X/M7Y centre +
    M7HOFS/M7VOFS scroll) is folded onto camera A's via the SAME CH2/CH3 channels,
    so band-2 samples camera A's world region (only the scale/angle matrix still
    differs) — band-2 is NOT red. The C1 'different world content' signal is ABSENT
    -> the same assertion that PASSES for the panned build MUST FAIL here. Proves
    C1 measures WORLD POSITION, not merely the presence of the splice channels."""
    runner.load_rom(str(roms["stillsame"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "stillsame ROM did not boot"
    pix = _px(_grab(runner, "campos_c1_same"))
    top_r = _mean_red(pix, TOP_ROWS)
    bot_r = _mean_red(pix, BOT_ROWS)
    # Same-centre: band-2 is the same (cool) world region as band-1 -> NOT red.
    assert bot_r < 20, (
        f"SAME_CENTER control still panned band-2 (mean R={bot_r:.1f}) — the C1 "
        f"control is vacuous; C1 must be measuring something other than position")
    assert not (bot_r - top_r > 60), (
        f"SAME_CENTER control shows a position difference it should not "
        f"(bot R={bot_r:.1f} top R={top_r:.1f})")


def test_c2_origin_splice_clean_band_step(roms, runner):
    """C2: the per-band ORIGIN change (mid-frame M7X/M7Y + M7HOFS/M7VOFS writes,
    HDMA at HBlank) yields a CLEAN band step, NOT a smear. Read the mean RED per
    row down band-2: the cool->red world-region boundary must be a single-row STEP
    (0 above, saturated below, transition spanning <=2 rows) — a mid-active-display
    register write would instead smear the change across many rows. This is the
    position analogue of P2 and confirms the extra CH2/CH3 splice is HBlank-clean.
    NOTE: the step lands at screenshot y = SEAM+OFF (119) — EXACTLY the seam
    scanline (PPU 112) displaced by the harness's +7-row screenshot padding.
    (An earlier draft misread the +7 offset as "the boundary lands a few rows
    INTO band-2 (world-X wrap)" — confabulated physics; that misdiagnosis is
    what hid P2's vacuous window. PR #223 review, minor 5.) Measured: mean red
    0.0 for every row above, 169.4 from y=119 down. Deterministic still build."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    pix = _px(_grab(runner, "campos_c2_step"))
    def mean_red_row(y):
        return sum(pix[x, y][0] for x in range(30, 226)) / 196
    prof = [(y, mean_red_row(y)) for y in range(SEAM, 204)]  # band-2 up to L1-20
    # find the first strong low->high red step
    step_y = None
    for i in range(1, len(prof)):
        if prof[i - 1][1] < 40 and prof[i][1] > 120:
            step_y = prof[i][0]
            break
    assert step_y is not None, f"no cool->red world-region step in band-2: {prof[:12]}"
    # the step is AT the seam scanline (PPU 112 -> screenshot SEAM+OFF), pinning
    # the origin splice's band boundary to the exact row the HDMA table places it
    assert step_y == SEAM + OFF, (
        f"red world-region step at y={step_y}, expected y={SEAM + OFF} "
        f"(= PPU seam {SEAM} + screenshot offset {OFF})")
    # crispness: the row just above is cool (~0), the step row is saturated,
    # and there is no multi-row ramp (the immediate predecessor must be quiet).
    above = mean_red_row(step_y - 1)
    at = mean_red_row(step_y)
    assert above < 40 and at > 120, (
        f"red band step not crisp at y={step_y}: above={above:.1f} at={at:.1f}")
    # below stays red (the region does not flicker back within a few rows)
    assert all(mean_red_row(y) > 120 for y in range(step_y, step_y + 6)), (
        f"red world region not held below the step at y={step_y}")


def test_c3_origin_splice_temporal_stability(roms, runner):
    """C3: the panned band-2's WORLD REGION is temporally stable with the origin
    splice active — across 12 CONSECUTIVE deterministic frames (the double buffer
    flips every frame) the band-2 RED signature is byte-stable. The CH2/CH3 origin
    tables are re-stamped and re-armed every frame; a desync would flip band-2's
    sampled region (red<->cool) and spike this metric. Reads FRAMEBUFFER."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    imgs, bufs = _step_capture(runner, "campos_c3_temporal", 12)
    assert len(set(bufs)) == 2, (
        f"double buffer did not flip across the window (pv_buffer={bufs})")
    sigs = [_band_red_sig(_px(im), BOT_ROWS) for im in imgs]
    worst = max((_sig_diff(sigs[i], sigs[i + 1]) for i in range(len(sigs) - 1)),
                default=0)
    # The band must actually BE red (non-vacuous), then stable.
    assert sum(sigs[0]) > 200, (
        f"band-2 red signature is empty ({sum(sigs[0])} set) — C3 would be vacuous")
    assert worst <= 4, (
        f"panned band-2 world region is NOT temporally stable: max consecutive "
        f"red-signature change {worst}px across 12 frames (pv_buffer={bufs})")


SKY_H = 48                              # -DSKY_HORIZON floor-start scanline
# Screenshot rows INSIDE the sky band: y=8..36 == PPU 1..29, all < SKY_H.
# (Was (4, ...): y=4 is inside the 7-row screenshot padding, not the PPU frame.)
SKY_ROWS = (8, 12, 20, 28, 36)


def _band_rgb(pix, rows, x0=30, x1=226):
    """Mean [R,G,B] over a set of rows — reads rendered FRAMEBUFFER pixels."""
    tot = [0, 0, 0]
    n = 0
    for y in rows:
        for x in range(x0, x1):
            c = pix[x, y]
            tot[0] += c[0]
            tot[1] += c[1]
            tot[2] += c[2]
            n += 1
    return [t / n for t in tot] if n else [0, 0, 0]


def test_b_horizon_knob_sky_vs_floor(roms, runner):
    """ITEM B (the horizon build knob): -DSKY_HORIZON arms a TM ($212C) HDMA band
    that turns the Mode-7 floor (BG1) OFF for lines 0..SKY_H-1, so the CGRAM[0]
    backdrop (blue-violet $5400) shows as a SKY band above the horizon. The DEFAULT
    build renders the floor all the way to the top screen edge (floor-to-edge, no
    sky). Reads the FRAMEBUFFER above the horizon (kit rule #2):
      * SKY build   -> backdrop colour (blue-dominant B, ~0 R and G — no floor).
      * DEFAULT build -> floor content (the checker's high green channel).
    Below the horizon BOTH render the Mode-7 floor (the knob changes only the
    band above the horizon). Deterministic still builds."""
    runner.load_rom(str(roms["stillsky"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "sky ROM did not boot"
    spix = _px(_grab(runner, "itemB_sky"))
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    dpix = _px(_grab(runner, "itemB_floor"))
    sky_above = _band_rgb(spix, SKY_ROWS)
    def_above = _band_rgb(dpix, SKY_ROWS)
    # SKY variant: the band above the horizon is the backdrop (blue), NOT floor.
    assert sky_above[2] > 120 and sky_above[1] < 40 and sky_above[0] < 40, (
        f"-DSKY_HORIZON band above the horizon is not the backdrop colour: "
        f"mean RGB={[round(v) for v in sky_above]} (expected blue-dominant sky)")
    # DEFAULT variant: floor rendered to the top edge (checker green present).
    assert def_above[1] > 80, (
        f"default build did not render floor-to-edge above the horizon: "
        f"mean RGB={[round(v) for v in def_above]} (expected floor checker)")
    # Below the horizon BOTH render the Mode-7 floor (only the top band changed).
    sky_below = _band_rgb(spix, (60, 80, 100))
    def_below = _band_rgb(dpix, (60, 80, 100))
    assert sky_below[1] > 80 and def_below[1] > 80, (
        f"floor below the horizon differs between builds: sky={sky_below} "
        f"default={def_below}")


def test_structural_channels_and_display_liveness(roms, runner):
    """STRUCTURAL: the matrix streams on CH5/CH6 ($60); the independent-world-
    position capability adds exactly TWO channels — CH2 (M7X/M7Y centre) + CH3
    (M7HOFS/M7VOFS scroll) — for mask $6C. The band-2 matrix splice itself still
    adds NO channel (it is CPU writes into the active WRAM buffer).

    The heartbeat check is DISPLAY/NMI LIVENESS ONLY — E010 mirrors
    FRAME_COUNTER (the NMI/VBlank counter), which advances ~60/s REGARDLESS of
    how badly the game loop overruns (the HDMA display re-streams the committed
    double buffer independent of the loop rate; PR #223 independent review, M1).
    It makes NO CPU-budget claim: the in-situ loop-rate gate is
    test_cadence_true_60fps_in_situ (xfail at HEAD) and the solve-budget
    instrument is test_persp_cycles.py."""
    runner.load_rom(str(roms["still"]), run_seconds=0.5)
    runner.run_frames(10)
    mask = runner.read_bytes(WR, NMI_HDMA_ENABLE, 1)[0]
    assert mask == 0x6C, (
        f"expected CH5|CH6 matrix + CH2|CH3 origin splice (mask $6C), "
        f"got ${mask:02X}")
    hb0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(120)
    hb1 = runner.read_u16(WR, 0xE010)
    advanced = (hb1 - hb0) & 0xFFFF
    assert advanced >= 110, (
        f"display/NMI not alive: heartbeat advanced {advanced}/120 (liveness "
        f"only — NOT a 60fps loop-rate claim)")
