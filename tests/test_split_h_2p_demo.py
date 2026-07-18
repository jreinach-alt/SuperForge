"""split_h_2p_demo — 2-player split screen: two live-positioned Mode-7 cameras.

Every assertion READS THE RENDERED FRAMEBUFFER (kit rule #2) or, for the loop-
cadence gate, the two WRAM counters whose LOCKSTEP is the claim itself.

Mechanism under test: both bands stream ROM-resident per-scanline pose tables
via INDIRECT-mode HDMA (DMAP $43) through template-owned index tables; each
band's world position is live via the origin channel pair (M7X/M7Y + M7HOFS/
M7VOFS, NON-REPEAT DMAP $03), re-stamped every frame in VBlank. No live solve.

DONE-CONDITIONS:
  T1  two per-scanline PERSPECTIVE bands (the run-length RAMP inside each band
      proves per-line matrix streaming — a flat/held matrix gives a constant
      run) with the seam at EXACTLY scanline 112 (run + red both step in one
      line; the screenshot +7-row offset is modeled, not ignored).
  C1  independent WORLD POSITION: band 1 (cool stripe, red~0) vs band 2 (warm
      stripe, red~255). -DSAME_ORIGIN folds camera 2 onto camera 1 -> band 2
      red MUST die (same metric, flipped).
  M1  independent MOTION: both bands' pixels change over time in the default
      build (different pan speeds); the -DFREEZE build is the flip control
      (same metric, zero change).
  CAD the loop closes EVERY frame: G_FRAMES (main-loop iterations) and E010
      (NMI count) advance +1 TOGETHER per stepped frame. This is the in-situ
      60fps gate the live-solve rail lacked (its loop measured 2 frames /
      30 Hz motion while its solve-only budget gate stayed green). WRAM-read
      based — immune to the harness frame-stepping video-skip artifact.
  R1  heading retarget: -DRETARGET flips band 2's pose pointers (2 bytes,
      VBlank) to the 45-degree pose from the PREFERRED 64-angle shipping set
      at frame 90 -> band 2 re-renders decisively, band 1 byte-stable. Proves
      (a) a non-trivial heading pose streams, (b) retarget-by-pointer works.
  S1  temporal stability: the frozen scene is byte-stable across stepped
      frames. Non-vacuity: R1 shows the SAME band-signature metric firing on a
      real content change through the same capture path.
  P5' latch guard: -DLATCH_VIOLATION write-twices M7HOFS mid-display with the
      SAME value HDMA delivers (pure latch interleave). Compared FROZEN-vs-
      FROZEN (both builds FREEZE=1) — the rotating-baseline confound that made
      the perspective rail's P5 non-discriminating cannot recur here.
  PB  per-band matrix channel pairs (the 256-pose rotation-smoothness rail):
      structural masks $0C/$30/$C0 with the LOAD-BEARING allocation order
      (band-2's pair on lower channels; -DPERBAND_BADORDER inverts it), the
      line-0 stray-write gate (static FREEZE builds ONLY — cross-ROM stepped
      screenshots are phase-polluted; badorder leaks EXACTLY screenshot row
      7 = PPU line 0), and the DoD: pose-step interval <= 1 frame on the
      256-pose rotate default (per-frame WRAM heading trace + pointer/bank
      binding vs the $7E:E040 DASB mirrors + move256 8.8 motion model +
      the 63->64 slice-boundary pointer+bank same-frame flip).
"""
import json
import struct
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

# Harness screenshots are 256x239: PPU scanline L renders at image y = L + 7
# (7 blank padding rows on top). Model it — do not sample scanline-space rows.
OFF = 7

SEAM = 112
# Mid/near band-local rows: the far rows (k < ~30) legitimately mix stripes
# (wide world FOV per scanline at far scale), so the pure-red rows start lower.
B1_ROWS = (56, 80, 104)            # band-1 scanlines
B2_ROWS = (168, 192, 216)          # band-2 scanlines (= 112 + k)

G_FRAMES = 0xE030                  # main-loop iteration counter (word)
HEARTBEAT = 0xE010                 # NMI counter mirror (word)
MSK_MATRIX = 0xE020                # classic: matrix pair; PERBAND: band-2 pair
MSK_ORIGIN = 0xE022                # origin pair
MSK_BAND1 = 0xE024                 # PERBAND: band-1 matrix pair
G_BANKS = 0xE040                   # POSES=256: stamped-DASB mirrors (AB1,CD1,AB2,CD2)

H1_ADDR, H2_ADDR = 0xC06A, 0xC06C  # heading words
AB1_PTR, CD1_PTR = 0xC001, 0xC011  # band-1 pose pointers (both table shapes)
AB2_PTR_PERBAND, CD2_PTR_PERBAND = 0xC084, 0xC094   # band-2, per-band tables
AB2_PTR_CLASSIC, CD2_PTR_CLASSIC = 0xC004, 0xC014   # band-2, shared tables
AB_BANK_BASE, CD_BANK_BASE = 0x02, 0x06             # 256-set slice-0 banks


@pytest.fixture(scope="module")
def roms():
    r = subprocess.run(["make", "build/split_h_2p_demo.sfc"], cwd=str(ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"build failed:\n{r.stderr}")
    v = subprocess.run(
        ["bash", "templates/split_h_2p_demo/build_split_h_2p_variants.sh"],
        cwd=str(ROOT), capture_output=True, text=True)
    if v.returncode != 0:
        pytest.skip(f"variant build failed:\n{v.stderr}")
    return {
        "default": BUILD / "split_h_2p_demo.sfc",
        "freeze": BUILD / "split_h_2p_demo_freeze.sfc",
        "sameorigin": BUILD / "split_h_2p_demo_sameorigin.sfc",
        "retarget": BUILD / "split_h_2p_demo_retarget.sfc",
        "latch": BUILD / "split_h_2p_demo_latch.sfc",
        "rotate": BUILD / "split_h_2p_demo_rotate.sfc",          # 256-pose default
        "rotate64": BUILD / "split_h_2p_demo_rotate64.sfc",      # 64-pose A/B
        "rotfreeze": BUILD / "split_h_2p_demo_rotfreeze.sfc",    # 256 + FREEZE
        "perband": BUILD / "split_h_2p_demo_perband.sfc",        # static per-band
        "badorder": BUILD / "split_h_2p_demo_badorder.sfc",      # inverted order
        # --- sprite stress rail (SP_N WRAM-poked at $C0C0) ---
        "spr_sweep": BUILD / "split_h_2p_demo_spr_sweep.sfc",    # integrated: input+AI+tiers
        "spr_rot": BUILD / "split_h_2p_demo_spr_rot.sfc",        # auto-rotate, no AI
        "spr_pinvis": BUILD / "split_h_2p_demo_spr_pinvis.sfc",  # all-visible pinned
        "spr_cyc": BUILD / "split_h_2p_demo_spr_cyc.sfc",        # cycle instruments
        "spr_cycaway": BUILD / "split_h_2p_demo_spr_cycaway.sfc",
        "spr_cycfar": BUILD / "split_h_2p_demo_spr_cycfar.sfc",
        "spr_cycai": BUILD / "split_h_2p_demo_spr_cycai.sfc",    # AI-only tick
        "spr_cycint": BUILD / "split_h_2p_demo_spr_cycint.sfc",  # integrated tick
        "spr_tier": BUILD / "split_h_2p_demo_spr_tier.sfc",      # tier-ladder still
        "spr_tieroff": BUILD / "split_h_2p_demo_spr_tieroff.sfc",
        "spr_culloff": BUILD / "split_h_2p_demo_spr_culloff.sfc",
        "sprites": BUILD / "split_h_2p_demo_sprites.sfc",        # SHIPPED default
        "spr_alt": BUILD / "split_h_2p_demo_spr_alt.sfc",        # 30 Hz reproject probe
        "spr_pin_a": BUILD / "split_h_2p_demo_spr_pin_a.sfc",    # glue-proof stills
        "spr_pin_b": BUILD / "split_h_2p_demo_spr_pin_b.sfc",
        "spr_pin_c": BUILD / "split_h_2p_demo_spr_pin_c.sfc",
        "spr_pinfwd": BUILD / "split_h_2p_demo_spr_pinfwd.sfc",  # wrong-matrix control
    }


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


# --- framebuffer helpers ------------------------------------------------------

def _grab(runner, tag):
    path = f"/tmp/sf_2p_{tag}.png"
    runner.take_screenshot(path)
    return Image.open(path).convert("RGB").load()


def _row_stats(pix, scanline, x0=8, x1=248):
    """(longest same-colour run, mean red) of one PPU scanline."""
    y = scanline + OFF
    best = run = 1
    prev = pix[x0, y]
    red = prev[0]
    for x in range(x0 + 1, x1):
        c = pix[x, y]
        red += c[0]
        if c == prev:
            run += 1
            best = max(best, run)
        else:
            run = 1
        prev = c
    return best, red / (x1 - x0)


def _band_sig(pix, scanlines, x0=8, x1=248, step=2):
    sig = []
    for s in scanlines:
        y = s + OFF
        sig.extend(pix[x, y] for x in range(x0, x1, step))
    return sig


def _sig_diff(a, b):
    return sum(1 for p, q in zip(a, b) if p != q)


def _diff_rows(pa, pb, w=256, h=239):
    """Image rows (screenshot y) where two full-frame grabs differ anywhere."""
    return [y for y in range(h)
            if any(pa[x, y] != pb[x, y] for x in range(w))]


def _first_transition_x(pix, scanline, x0=8, x1=248, thresh=60):
    y = scanline + OFF
    prev = pix[x0, y]
    for x in range(x0 + 1, x1):
        c = pix[x, y]
        if abs(c[0] - prev[0]) + abs(c[1] - prev[1]) + abs(c[2] - prev[2]) > thresh:
            return x
        prev = c
    return None


def _row_jitter(pix, s0, s1):
    """Mean |dx| of the first colour transition between adjacent scanlines —
    smooth for a clean trapezoid, spiky when the shared latch tears."""
    xs = [_first_transition_x(pix, s) for s in range(s0, s1)]
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return 0.0
    return sum(abs(xs[i + 1] - xs[i]) for i in range(len(xs) - 1)) / (len(xs) - 1)


# --- tests ---------------------------------------------------------------------

def test_boots(roms, runner):
    runner.load_rom(str(roms["default"]), run_seconds=1.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "demo did not boot"


def test_structural_channels_and_liveness(roms, runner):
    """Masks: matrix pair $0C + origin pair $30 (allocator, fresh boot) and the
    NMI/display LIVENESS heartbeat. This heartbeat is NOT a loop-rate claim —
    test_cadence_true_60fps_in_situ is the loop-rate gate."""
    runner.load_rom(str(roms["default"]), run_seconds=1.0)
    assert runner.read_u16(WR, MSK_MATRIX) == 0x0C, "matrix channels not CH2|CH3"
    assert runner.read_u16(WR, MSK_ORIGIN) == 0x30, "origin channels not CH4|CH5"
    hb0 = runner.read_u16(WR, HEARTBEAT)
    time.sleep(2.0)
    advanced = (runner.read_u16(WR, HEARTBEAT) - hb0) & 0xFFFF
    assert advanced >= 110, f"NMI/display not alive: {advanced}/~120"


def test_cadence_true_60fps_in_situ(roms, runner):
    """THE BUDGET GATE (in situ, whole loop — not a solve-only instrument):
    across stepped frames, G_FRAMES (loop iterations) and E010 (NMI count)
    both advance +1 per frame, in lockstep. A loop that overruns even one
    scanline quantizes to +1 NMI per 2 loop iterations and FAILS here (that is
    precisely the shipped state of the live-solve rail — measured 30 Hz).
    WRAM-only: immune to the frame-stepping video-skip artifact."""
    runner.load_rom(str(roms["default"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        g0, h0 = runner.read_u16(WR, G_FRAMES), runner.read_u16(WR, HEARTBEAT)
        for i in range(1, 13):
            runner.frame_step(1)
            g = runner.read_u16(WR, G_FRAMES)
            h = runner.read_u16(WR, HEARTBEAT)
            assert (g - g0) & 0xFFFF == i, \
                f"loop iteration missed a frame at step {i}: G_FRAMES +{(g-g0)&0xFFFF}"
            assert (h - h0) & 0xFFFF == i, \
                f"NMI count skewed at step {i}: E010 +{(h-h0)&0xFFFF}"


def test_t1_two_perspective_bands_seam_exact(roms, runner):
    """Per-line matrix streaming + the seam at EXACTLY scanline 112.
    The run-length RAMP inside each band (near rows ~2x the far rows) proves a
    NEW matrix per scanline is consumed (a held matrix -> constant run). The
    ramp restarting at line 112 + the red stripe step pin the seam row."""
    runner.load_rom(str(roms["freeze"]), run_seconds=1.0)
    pix = _grab(runner, "freeze")
    for base in (0, SEAM):          # both bands
        far, _ = _row_stats(pix, base + 40)
        near, _ = _row_stats(pix, base + 104)
        assert near >= 1.4 * far, \
            f"band@{base}: no per-line ramp (far run {far}, near run {near})"
    run_above, red_above = _row_stats(pix, SEAM - 1)
    run_below, red_below = _row_stats(pix, SEAM)
    assert red_above < 40 and red_below > 150, \
        f"red does not step at 112: {red_above:.0f} -> {red_below:.0f}"
    assert run_above >= 1.5 * run_below, \
        f"ramp does not restart at 112: run {run_above} -> {run_below}"
    # and the step is AT 112, not smeared around it: 110/111 cool, 112/113 warm
    for s, want_warm in ((110, False), (111, False), (112, True), (113, True)):
        _, red = _row_stats(pix, s)
        assert (red > 150) == want_warm, f"seam smeared: scanline {s} red {red:.0f}"


def test_c1_independent_world_position(roms, runner):
    """Band 2 views the WARM stripe (world X 768) while band 1 views the COOL
    stripe (world X 512): the red channel is the position signal."""
    runner.load_rom(str(roms["freeze"]), run_seconds=1.0)
    pix = _grab(runner, "freeze_c1")
    red1 = max(_row_stats(pix, s)[1] for s in B1_ROWS)
    red2 = min(_row_stats(pix, s)[1] for s in B2_ROWS)
    assert red1 < 25, f"band 1 not cool: red {red1:.0f}"
    assert red2 > 200, f"band 2 not warm: red {red2:.0f}"


def test_c1_same_origin_control(roms, runner):
    """NON-VACUITY (-DSAME_ORIGIN): camera 2 folded onto camera 1 -> band 2
    leaves the warm stripe -> the SAME red metric MUST die."""
    runner.load_rom(str(roms["sameorigin"]), run_seconds=1.0)
    pix = _grab(runner, "sameorigin")
    red2 = max(_row_stats(pix, s)[1] for s in B2_ROWS)
    assert red2 < 25, f"SAME_ORIGIN control failed to fold: band 2 red {red2:.0f}"


def test_m1_independent_motion(roms, runner):
    """Both cameras pan (different speeds) -> both bands' pixels change over
    ~30 frames. Flip control: the FREEZE build shows ZERO change on the same
    metric. (Two far-apart free-running grabs — deliberately NOT consecutive
    stepped frames, which the harness video-skip artifact can alias.)"""
    runner.load_rom(str(roms["default"]), run_seconds=1.0)
    pix_a = _grab(runner, "mot_a")
    a = _band_sig(pix_a, B1_ROWS), _band_sig(pix_a, B2_ROWS)
    time.sleep(0.6)
    pix_b = _grab(runner, "mot_b")
    d1 = _sig_diff(a[0], _band_sig(pix_b, B1_ROWS))
    d2 = _sig_diff(a[1], _band_sig(pix_b, B2_ROWS))
    assert d1 > 30, f"band 1 static in the motion build ({d1})"
    assert d2 > 30, f"band 2 static in the motion build ({d2})"

    runner.load_rom(str(roms["freeze"]), run_seconds=1.0)
    pix_f = _grab(runner, "frz_a")
    f = _band_sig(pix_f, B1_ROWS), _band_sig(pix_f, B2_ROWS)
    time.sleep(0.6)
    pix_fb = _grab(runner, "frz_b")
    assert _sig_diff(f[0], _band_sig(pix_fb, B1_ROWS)) == 0, "freeze band 1 moved"
    assert _sig_diff(f[1], _band_sig(pix_fb, B2_ROWS)) == 0, "freeze band 2 moved"


def test_s1_temporal_stability(roms, runner):
    """Frozen scene: byte-stable band signatures across 10 stepped frames.
    Non-vacuity for the metric: test_r1 shows the same signature firing on a
    real band-2 change through the same capture path."""
    runner.load_rom(str(roms["freeze"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        pix = _grab(runner, "stab_0")
        ref1, ref2 = _band_sig(pix, B1_ROWS), _band_sig(pix, B2_ROWS)
        for i in range(1, 10):
            runner.frame_step(1)
            pix = _grab(runner, f"stab_{i}")
            assert _sig_diff(ref1, _band_sig(pix, B1_ROWS)) == 0, f"band 1 @ {i}"
            assert _sig_diff(ref2, _band_sig(pix, B2_ROWS)) == 0, f"band 2 @ {i}"


def test_r1_heading_retarget_streams_64set_pose(roms, runner):
    """-DRETARGET flips band 2's index pointers to the 45-degree pose (sliced
    from the 64-angle shipping set) at frame 90: band 2 re-renders decisively;
    band 1 is byte-stable through the flip (its pointers were not touched)."""
    runner.load_rom(str(roms["retarget"]), run_seconds=1.0)   # ~60 frames < 90
    pix = _grab(runner, "ret_pre")
    pre1, pre2 = _band_sig(pix, B1_ROWS), _band_sig(pix, B2_ROWS)
    time.sleep(1.2)                                           # well past frame 90
    pix = _grab(runner, "ret_post")
    assert _sig_diff(pre2, _band_sig(pix, B2_ROWS)) > 60, \
        "band 2 did not re-render after the pose retarget"
    assert _sig_diff(pre1, _band_sig(pix, B1_ROWS)) == 0, \
        "band 1 changed — the retarget leaked across the seam"
    # the band boundary survives the retarget: bottom-of-band-1 still differs
    # sharply from top-of-band-2 (content discontinuity at the seam row)
    sig_above = _band_sig(pix, (SEAM - 2, SEAM - 1))
    sig_below = _band_sig(pix, (SEAM, SEAM + 1))
    assert _sig_diff(sig_above, sig_below) > 40, "seam vanished after retarget"


def test_rot_cadence_true_60fps_in_situ(roms, runner):
    """MOVEMENT + ROTATION ON BOTH CAMERAS still closes every frame — the
    64-POSE CLASSIC SHAPE (the `rotate64` A/B build; the 256-pose default has
    its own gate, test_rot256_dod_pose_step_every_frame). This build advances
    both headings (every 4 / every 6 frames, opposite senses), drives both
    cameras forward along their headings, and recomputes all FOUR pose
    pointers EVERY frame (deliberate worst case) — and the loop must stay in
    +1/+1 lockstep with the NMI counter, exactly like the fixed-angle build.
    Also confirms in WRAM that both headings and both positions are really
    advancing (the work is not compiled out), and that every frame's position
    delta equals the EXACT 8.8 fractional-accumulator decomposition of
    move64[h] (the constant-speed motion fix: a revert to integer velocities,
    a broken sign-extension, or a dropped fraction strip all fail this
    model)."""
    mv = (ROOT / "templates" / "split_h_2p_demo" / "assets" / "move64.bin"
          ).read_bytes()
    runner.load_rom(str(roms["rotate64"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        g0, h0 = runner.read_u16(WR, G_FRAMES), runner.read_u16(WR, HEARTBEAT)
        h1_0, h2_0 = runner.read_u16(WR, 0xC06A), runner.read_u16(WR, 0xC06C)
        p1_0, p2_0 = runner.read_u16(WR, 0xC062), runner.read_u16(WR, 0xC066)
        # 8.8 accumulator model state: positions + fraction bytes, both cams
        POS_ADDRS = (0xC060, 0xC062, 0xC064, 0xC066)
        FRAC_ADDRS = (0xC072, 0xC074, 0xC076, 0xC078)
        pos = [runner.read_u16(WR, a) for a in POS_ADDRS]
        frac = [runner.read_u16(WR, a) & 0xFF for a in FRAC_ADDRS]
        for i in range(1, 25):
            runner.frame_step(1)
            g = (runner.read_u16(WR, G_FRAMES) - g0) & 0xFFFF
            h = (runner.read_u16(WR, HEARTBEAT) - h0) & 0xFFFF
            assert g == i, f"rotate loop missed a frame at step {i}: +{g}"
            assert h == i, f"NMI skew at step {i}: +{h}"
            # pointer<->heading BINDING (audit-1 hardening): each band's pose
            # pointers must equal blob + OWN_heading*448 — band 1 from H1,
            # band 2 from H2 (a mix-up driving both from one heading passes
            # the change-only guards below but fails this formula).
            h1 = runner.read_u16(WR, 0xC06A)
            h2 = runner.read_u16(WR, 0xC06C)
            assert runner.read_u16(WR, 0xC001) == (0x8000 + h1 * 448) & 0xFFFF, \
                f"band-1 AB pointer not bound to H1 at step {i}"
            assert runner.read_u16(WR, 0xC011) == (0x8000 + h1 * 448) & 0xFFFF, \
                f"band-1 CD pointer not bound to H1 at step {i}"
            assert runner.read_u16(WR, 0xC004) == (0x8000 + h2 * 448) & 0xFFFF, \
                f"band-2 AB pointer not bound to H2 at step {i}"
            assert runner.read_u16(WR, 0xC014) == (0x8000 + h2 * 448) & 0xFFFF, \
                f"band-2 CD pointer not bound to H2 at step {i}"
            # exact-motion model: this frame used the (already advanced)
            # headings; frac += vel; POS += floor(sum/256); frac = sum & $FF.
            vels = (struct.unpack_from("<hh", mv, h1 * 4)
                    + struct.unpack_from("<hh", mv, h2 * 4))
            for j in range(4):
                s = frac[j] + vels[j]
                pos[j] = (pos[j] + (s // 256)) & 0x3FF
                frac[j] = s & 0xFF
            got_pos = [runner.read_u16(WR, a) for a in POS_ADDRS]
            got_frac = [runner.read_u16(WR, a) & 0xFF for a in FRAC_ADDRS]
            assert got_pos == pos and got_frac == frac, \
                f"motion diverged from the 8.8 model at step {i}: " \
                f"pos {got_pos} vs {pos}, frac {got_frac} vs {frac}"
        assert runner.read_u16(WR, 0xC06A) != h1_0, "camera 1 heading frozen"
        assert runner.read_u16(WR, 0xC06C) != h2_0, "camera 2 heading frozen"
        assert (runner.read_u16(WR, 0xC062) != p1_0
                or runner.read_u16(WR, 0xC066) != p2_0), "positions frozen"


def test_rot_both_bands_rotate(roms, runner):
    """Rotate-in-place on the 256-POSE DEFAULT (ROTATE POSES=256 FREEZE):
    across 12-frame hops both bands' pixels change (each camera's heading
    advanced 12 poses = 16.9° per hop — the DoD's rendered-rotation half:
    both bands' CONTENT rotates through the per-band channel pairs) while
    the seam discontinuity persists. 12-frame hops sidestep the
    frame-stepping video-skip aliasing (a 2-frame pairing cannot mask a
    12-frame delta). The per-frame step-interval half of the DoD is
    test_rot256_dod_pose_step_every_frame (WRAM trace — video-skip immune)."""
    runner.load_rom(str(roms["rotfreeze"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        pix = _grab(runner, "rot_0")
        prev1, prev2 = _band_sig(pix, B1_ROWS), _band_sig(pix, B2_ROWS)
        for hop in range(1, 4):
            runner.frame_step(12)
            pix = _grab(runner, f"rot_{hop}")
            cur1, cur2 = _band_sig(pix, B1_ROWS), _band_sig(pix, B2_ROWS)
            assert _sig_diff(prev1, cur1) > 20, f"band 1 not rotating at hop {hop}"
            assert _sig_diff(prev2, cur2) > 20, f"band 2 not rotating at hop {hop}"
            sig_above = _band_sig(pix, (SEAM - 2, SEAM - 1))
            sig_below = _band_sig(pix, (SEAM, SEAM + 1))
            assert _sig_diff(sig_above, sig_below) > 40, f"seam lost at hop {hop}"
            prev1, prev2 = cur1, cur2


def test_p5_latch_violation_tears(roms, runner):
    """NEGATIVE CONTROL: -DLATCH_VIOLATION write-twices M7HOFS mid-display with
    the SAME value HDMA delivers -> pure latch-interleave corruption -> band-1
    rows jitter. FROZEN-vs-FROZEN comparison (both builds FREEZE=1): the clean
    baseline is deterministic, so the threshold attributes the tear to the
    violation — not to scene motion (the perspective rail's P5 confound)."""
    runner.load_rom(str(roms["freeze"]), run_seconds=0.5)
    clean = _row_jitter(_grab(runner, "latch_clean"), 20, 100)
    runner.load_rom(str(roms["latch"]), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "latch ROM did not boot"
    worst = 0.0
    for i in range(10):             # the collision phase drifts and can hold a
        # clean phase for several grabs (audit-1 measured tears in only 2 of 6
        # samples) — a wider window keeps the max-over-window robust
        worst = max(worst, _row_jitter(_grab(runner, f"latch_{i}"), 20, 100))
        time.sleep(0.1)
    assert worst > 2.0 * max(clean, 0.5), \
        f"latch violation did not corrupt: clean={clean:.2f} worst={worst:.2f}"


# --- per-band matrix channel pairs (the 256-pose rotation-smoothness rail) -----

def test_perband_structural_masks_and_allocation_order(roms, runner):
    """PERBAND channel shape: band-2's matrix pair $0C (allocated FIRST ->
    CH2|CH3), band-1's pair $30 (SECOND -> CH4|CH5), origin pair $C0 (CH6|CH7)
    — all 6 allocator channels. THE ALLOCATION ORDER IS LOAD-BEARING (the
    stray-write mask depends on band-1's pair sitting on numerically HIGHER
    channels so its line-0 write lands LAST in the HBlank): asserted as
    band-2 mask < band-1 mask. Same shape on the 256-pose rotate default.
    Non-vacuity: the -DPERBAND_BADORDER control inverts the SAME two mask
    reads (band-1 pair $0C, band-2 pair $30)."""
    runner.load_rom(str(roms["perband"]), run_seconds=1.0)
    assert runner.read_u16(WR, MSK_MATRIX) == 0x0C, "band-2 pair not CH2|CH3"
    assert runner.read_u16(WR, MSK_BAND1) == 0x30, "band-1 pair not CH4|CH5"
    assert runner.read_u16(WR, MSK_ORIGIN) == 0xC0, "origin pair not CH6|CH7"
    assert runner.read_u16(WR, MSK_MATRIX) < runner.read_u16(WR, MSK_BAND1), \
        "allocation order broken: band-2's pair must sit on LOWER channels"

    runner.load_rom(str(roms["rotate"]), run_seconds=1.0)
    assert runner.read_u16(WR, MSK_MATRIX) == 0x0C, "256 rotate: band-2 pair"
    assert runner.read_u16(WR, MSK_BAND1) == 0x30, "256 rotate: band-1 pair"
    assert runner.read_u16(WR, MSK_ORIGIN) == 0xC0, "256 rotate: origin pair"

    runner.load_rom(str(roms["badorder"]), run_seconds=1.0)
    assert runner.read_u16(WR, MSK_BAND1) == 0x0C, "badorder control: band-1 pair"
    assert runner.read_u16(WR, MSK_MATRIX) == 0x30, "badorder control: band-2 pair"


def test_perband_line0_mask_gate_static(roms, runner):
    """THE LINE-0 STRAY-WRITE GATE (static scenes — cross-ROM stepped
    screenshots are phase-polluted, so all three grabs are FREEZE builds
    after a free run; the scene is deterministic-static):
      (a) classic vs per-band render BYTE-IDENTICAL (0 differing rows) — the
          channel restructure is invisible when the mask works;
      (b) per-band vs -DPERBAND_BADORDER differ at EXACTLY screenshot row 7
          (= PPU line 0 + the modeled +7 offset) and NOWHERE else — the
          skip-prefix stray unit wins the HBlank when the allocation order
          is inverted, and only line 0 carries it.
    (b) is the non-vacuity control for (a): the same full-frame row-diff
    metric flips from [] to [7] on the control build, so the equality in (a)
    cannot be a vacuous pass of the capture path. The skip prefix aims at a
    pose that DIFFERS from band-1's by construction (rot45) — a broken mask
    MUST show at row 7."""
    runner.load_rom(str(roms["freeze"]), run_seconds=2.0)
    pix_classic = _grab(runner, "l0_classic")
    runner.load_rom(str(roms["perband"]), run_seconds=2.0)
    pix_perband = _grab(runner, "l0_perband")
    runner.load_rom(str(roms["badorder"]), run_seconds=2.0)
    pix_badorder = _grab(runner, "l0_badorder")

    assert _diff_rows(pix_classic, pix_perband) == [], \
        "classic vs per-band render not byte-identical"
    assert _diff_rows(pix_perband, pix_badorder) == [OFF], \
        "badorder control must leak EXACTLY PPU line 0 (screenshot row 7)"
    assert _diff_rows(pix_classic, pix_badorder) == [OFF], \
        "classic vs badorder must differ at exactly PPU line 0"


def test_rot256_dod_pose_step_every_frame(roms, runner):
    """THE ROTATION-SMOOTHNESS DoD (owner rule: pose-step interval <= 1 FRAME
    at the demo's turn rates) + the 6-channel budget gate + the per-band
    pointer/bank binding, all on the 256-pose rotate default:
      - 24 stepped frames of sustained turn: G_FRAMES and E010 advance +1/+1
        (the in-situ 60fps gate ON the 6-channel build — the ~+2 channels of
        HDMA steal must not break the budget);
      - h1 advances +1 (mod 256) and h2 advances -1 (mod 256) EVERY frame —
        no two consecutive frames hold an equal heading (the step-per-frame
        rule, WRAM-read, video-skip immune);
      - per-band binding: band-1's pointers == $8000 + (h1 & 63)*448 with
        stamped banks base+(h1>>6), band-2's from h2 (read from the DASB
        debug mirrors at $7E:E040+ that the VBlank stamper writes) — a
        mix-up driving both bands from one heading fails the formulas;
      - exact 8.8 motion model vs move256[h] (velocity indexed by h DIRECTLY:
        exact forward direction at every one of the 256 headings).
    Non-vacuity controls: the rotate64 A/B build FAILS the same
    consecutive-frames-differ metric (its cam-1 heading holds for 4 frames —
    asserted below) and its G_BANKS mirrors stay zero (no stamper), proving
    both metrics measure real 256-build behaviour, not the harness."""
    mv = (ROOT / "templates" / "split_h_2p_demo" / "assets" / "move256.bin"
          ).read_bytes()
    runner.load_rom(str(roms["rotate"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        g0, n0 = runner.read_u16(WR, G_FRAMES), runner.read_u16(WR, HEARTBEAT)
        prev_h1 = runner.read_u16(WR, H1_ADDR)
        prev_h2 = runner.read_u16(WR, H2_ADDR)
        POS_ADDRS = (0xC060, 0xC062, 0xC064, 0xC066)
        FRAC_ADDRS = (0xC072, 0xC074, 0xC076, 0xC078)
        pos = [runner.read_u16(WR, a) for a in POS_ADDRS]
        frac = [runner.read_u16(WR, a) & 0xFF for a in FRAC_ADDRS]
        for i in range(1, 25):
            runner.frame_step(1)
            g = (runner.read_u16(WR, G_FRAMES) - g0) & 0xFFFF
            n = (runner.read_u16(WR, HEARTBEAT) - n0) & 0xFFFF
            assert g == i, f"256 loop missed a frame at step {i}: +{g}"
            assert n == i, f"NMI skew at step {i}: +{n}"
            h1 = runner.read_u16(WR, H1_ADDR)
            h2 = runner.read_u16(WR, H2_ADDR)
            # the DoD: a pose step EVERY frame, +1/-1, opposite senses
            assert h1 == (prev_h1 + 1) & 0xFF, \
                f"step {i}: h1 {prev_h1}->{h1} is not +1/frame"
            assert h2 == (prev_h2 - 1) & 0xFF, \
                f"step {i}: h2 {prev_h2}->{h2} is not -1/frame"
            assert h1 != prev_h1 and h2 != prev_h2, \
                f"step {i}: heading held across consecutive frames"
            prev_h1, prev_h2 = h1, h2
            # per-band pointer binding (band-local pose within the slice)
            want1 = (0x8000 + (h1 & 63) * 448) & 0xFFFF
            want2 = (0x8000 + (h2 & 63) * 448) & 0xFFFF
            assert runner.read_u16(WR, AB1_PTR) == want1, f"AB1 ptr @ {i}"
            assert runner.read_u16(WR, CD1_PTR) == want1, f"CD1 ptr @ {i}"
            assert runner.read_u16(WR, AB2_PTR_PERBAND) == want2, f"AB2 ptr @ {i}"
            assert runner.read_u16(WR, CD2_PTR_PERBAND) == want2, f"CD2 ptr @ {i}"
            # per-band bank binding (the stamped-DASB debug mirrors)
            banks = runner.read_bytes(WR, G_BANKS, 4)
            want_banks = [AB_BANK_BASE + (h1 >> 6), CD_BANK_BASE + (h1 >> 6),
                          AB_BANK_BASE + (h2 >> 6), CD_BANK_BASE + (h2 >> 6)]
            assert list(banks) == want_banks, \
                f"step {i}: stamped banks {list(banks)} != {want_banks}"
            # exact 8.8 motion model against move256[h] (h indexes directly)
            vels = (struct.unpack_from("<hh", mv, h1 * 4)
                    + struct.unpack_from("<hh", mv, h2 * 4))
            for j in range(4):
                s = frac[j] + vels[j]
                pos[j] = (pos[j] + (s // 256)) & 0x3FF
                frac[j] = s & 0xFF
            got_pos = [runner.read_u16(WR, a) for a in POS_ADDRS]
            got_frac = [runner.read_u16(WR, a) & 0xFF for a in FRAC_ADDRS]
            assert got_pos == pos and got_frac == frac, \
                f"motion diverged from the move256 8.8 model at step {i}"

    # non-vacuity: the SAME consecutive-frames metric fails on the 64-pose
    # A/B build (heading holds between steps), and its bank mirrors stay 0.
    runner.load_rom(str(roms["rotate64"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        held = 0
        prev = runner.read_u16(WR, H1_ADDR)
        for _ in range(8):
            runner.frame_step(1)
            h1 = runner.read_u16(WR, H1_ADDR)
            if h1 == prev:
                held += 1
            prev = h1
        assert held >= 4, \
            f"rotate64 control: cam-1 heading should HOLD most frames ({held}/8)"
        assert runner.read_bytes(WR, G_BANKS, 4) == b"\x00\x00\x00\x00", \
            "rotate64 control: no DASB stamper -> mirrors must stay zero"


def test_rot256_bank_delivery_render_period(roms, runner):
    """DASB BANK DELIVERY read off the RENDERED FRAMEBUFFER (audit-1 D2
    hardening — closes the mirror-proxy gap): the $7E:E040 debug mirrors are
    written one instruction after the hardware `sta $4307,x` from the same A
    value, so a wrong VALUE cannot hide — but a wrong CHANNEL OFFSET (CHX)
    would keep the mirrors green while the hardware fetches a stale slice.
    Discriminator: on the 256 rotfreeze build (headings advance +1/-1 per
    frame, positions frozen) only (h & 63) feeds the pose POINTER — the slice
    index travels ONLY in the stamped bank byte. So rendered band content
    must be a function of h with period 256, not 64:
      - hops of +64 and +192 frames land on the SAME (h & 63) in a DIFFERENT
        slice -> if (and only if) the banks reach the fetching channel, the
        bands re-render at slice scale (audit-1 measured ~17k px; my probe
        ~25k per band) -> assert > 8,000 differing pixels per band. A
        dead/stale DASB path has render period 64: both hops would read
        ~0-5k px (one-pose capture-lag noise at most) and FAIL. This
        +64-hop-differs assertion IS the bank-delivery discriminator.
      - a FULL +256 wrap is pixel-IDENTICAL (audit-1 measured 0 px) — proves
        the metric can read zero through the same capture path (the
        non-vacuity pairing for the differ-assertions; conversely the differ
        assertions prove the same metric fires on a real change).
    Both bands are asserted (each pair has its own CHX homes). All hops are
    >= 12 frames (video-skip safe); WRAM headings pin the hop arithmetic
    (lag-free). HARNESS-LAG NOTE (audit-1 §4): captures under frame-stepping
    carry a rare 0-or-1-frame lag, which breaks a single-capture identity
    check on a rotating scene (my probe hit exactly that: a lone +256
    capture read 4.7k px = one-pose scale). The wrap identity is therefore
    the MIN over the three pairwise diffs of THREE wrap-aligned captures
    (ref, +256, +512): with lag in {0,1}, pigeonhole guarantees two captures
    share a lag value and diff EXACTLY 0."""
    runner.load_rom(str(roms["rotfreeze"]), run_seconds=1.0)
    with runner.frame_stepping():
        runner.frame_step(1)
        h_ref = runner.read_u16(WR, H1_ADDR)
        ref = _grab(runner, "period_ref")
        runner.frame_step(64)
        c64 = _grab(runner, "period_c64")
        assert (runner.read_u16(WR, H1_ADDR) - h_ref) & 0xFF == 64
        runner.frame_step(128)
        c192 = _grab(runner, "period_c192")
        assert (runner.read_u16(WR, H1_ADDR) - h_ref) & 0xFF == 192
        runner.frame_step(64)
        w256 = _grab(runner, "period_w256")
        assert (runner.read_u16(WR, H1_ADDR) - h_ref) & 0xFF == 0
        runner.frame_step(256)
        w512 = _grab(runner, "period_w512")
        assert (runner.read_u16(WR, H1_ADDR) - h_ref) & 0xFF == 0

    def band_px_diff(a, b, y0, y1):
        return sum(1 for y in range(y0, y1)
                   for x in range(256) if a[x, y] != b[x, y])

    BAND1 = (OFF, SEAM + OFF)              # PPU scanlines 0..111
    BAND2 = (SEAM + OFF, 224 + OFF)        # PPU scanlines 112..223
    for name, (y0, y1) in (("band1", BAND1), ("band2", BAND2)):
        d64 = band_px_diff(ref, c64, y0, y1)
        d192 = band_px_diff(ref, c192, y0, y1)
        assert d64 > 8000, \
            f"{name}: +64-frame same-(h&63) hop differs by only {d64} px — " \
            f"render period looks like 64: stamped banks are NOT reaching " \
            f"the fetching channel"
        assert d192 > 8000, \
            f"{name}: +192-frame same-(h&63) hop differs by only {d192} px"
        wrap_min = min(band_px_diff(ref, w256, y0, y1),
                       band_px_diff(ref, w512, y0, y1),
                       band_px_diff(w256, w512, y0, y1))
        assert wrap_min == 0, \
            f"{name}: full +256 wrap not pixel-identical (min pairwise " \
            f"{wrap_min} px over 3 wrap-aligned captures — period-256 " \
            f"identity broken beyond the 0/1-frame capture-lag class)"


def test_rot256_bank_boundary_crossing(roms, runner):
    """POINTER+BANK FLIP TOGETHER at a 64-pose slice boundary, in the SAME
    frame. From boot h1=0 (+1/frame) reaches 63->64 at ~step 64: the pose
    pointer must wrap $EE40 -> $8000 exactly when the stamped AB1/CD1 banks
    step base -> base+1 (h2, running 128 -> 64 downward, crosses 64->63 one
    frame later: its banks step base+1 -> base). A stamper that lags the
    pointer rewrite by even one frame shows a torn pair here. Non-vacuity:
    the pointer/bank formulas themselves (a stale bank with a wrapped
    pointer, or vice versa, fails the same-frame pairing); the rotate64
    zero-mirror control in test_rot256_dod_pose_step_every_frame proves the
    mirror bytes are genuinely stamper-written."""
    runner.load_rom(str(roms["rotate"]), run_seconds=0.5)   # ~30 frames < 60
    with runner.frame_stepping():
        runner.frame_step(1)
        # advance until h1 is just below the slice boundary (bounded walk)
        h1 = runner.read_u16(WR, H1_ADDR)
        for _ in range(70):
            if h1 >= 60:
                break
            runner.frame_step(1)
            h1 = runner.read_u16(WR, H1_ADDR)
        assert 60 <= h1 < 64, f"could not park h1 below the boundary ({h1})"
        saw_h1_cross = saw_h2_cross = False
        prev_h1 = h1
        prev_h2 = runner.read_u16(WR, H2_ADDR)
        for _ in range(12):
            runner.frame_step(1)
            h1 = runner.read_u16(WR, H1_ADDR)
            h2 = runner.read_u16(WR, H2_ADDR)
            banks = runner.read_bytes(WR, G_BANKS, 4)
            ab1 = runner.read_u16(WR, AB1_PTR)
            ab2 = runner.read_u16(WR, AB2_PTR_PERBAND)
            if prev_h1 == 63 and h1 == 64:
                assert ab1 == 0x8000, f"h1 63->64: pointer {ab1:04x} != $8000"
                assert banks[0] == AB_BANK_BASE + 1 and \
                    banks[1] == CD_BANK_BASE + 1, \
                    f"h1 63->64: banks {list(banks[:2])} did not flip with ptr"
                saw_h1_cross = True
            if prev_h2 == 64 and h2 == 63:
                assert ab2 == (0x8000 + 63 * 448) & 0xFFFF, \
                    f"h2 64->63: pointer {ab2:04x} != $EE40"
                assert banks[2] == AB_BANK_BASE and \
                    banks[3] == CD_BANK_BASE, \
                    f"h2 64->63: banks {list(banks[2:])} did not flip with ptr"
                saw_h2_cross = True
            prev_h1, prev_h2 = h1, h2
        assert saw_h1_cross, "h1 never crossed the 63->64 slice boundary"
        assert saw_h2_cross, "h2 never crossed the 64->63 slice boundary"


# =============================================================================
# SPRITE STRESS RAIL (SPRITES=N builds): players + AI followers + size tiers
# =============================================================================
# WRAM map (templates/split_h_2p_demo/sprites_2p.inc):
SP_N_ADDR = 0xC0C0          # live sprite count (word, test-poked)
SP_SLOT_ADDR = 0xC0C2       # OAM-shadow compaction cursor (visible*4)
SP_OVER_ADDR = 0xC0CA       # per-pass overflow count (slots beyond 128)
SP_HOLD_ADDR = 0xC0CC       # poked nonzero -> input/AI freeze (still capture)
SP_ENTS = 0xC320            # 128 x 8 B entities (x,y,heading,wp,fx,fy)
POS_ADDRS_SP = (0xC060, 0xC062, 0xC064, 0xC066)
FRAC_ADDRS_SP = (0xC072, 0xC074, 0xC076, 0xC078)

_SPA = ROOT / "templates" / "split_h_2p_demo" / "assets"
_SINCOS = (_SPA / "sp_sincos.bin").read_bytes()
_VK = (_SPA / "sp_vk.bin").read_bytes()
_RECIP_LO = (_SPA / "sp_recip_lo.bin").read_bytes()
_RECIP_HI = (_SPA / "sp_recip_hi.bin").read_bytes()
_TIER_LUT = (_SPA / "sp_tier_lut.bin").read_bytes()
_TIER_NOCULL = (_SPA / "sp_tier_nocull.bin").read_bytes()
_MOVE256 = (_SPA / "move256.bin").read_bytes()
SP_TIER_HALF = (8, 8, 8, 16, 16)


def sp_project(wx, wy, px, py, h, band_top, forward=False, nocull=False):
    """Bit-exact Python mirror of sp_project_band (sprites_2p.inc). Used ONLY
    to pick WHERE to sample the framebuffer — every pass/fail reads pixels
    (the mode7_oshoot meta-lesson). Returns (sx, sy, tier) or None."""
    c, s = struct.unpack_from("<hh", _SINCOS, (h & 255) * 4)
    if forward:
        s = -s
    dx = ((wx - px + 512) & 1023) - 512
    dy = ((wy - py + 512) & 1023) - 512
    adx, mdx = (-dx, True) if dx < 0 else (dx, False)
    ady, mdy = (-dy, True) if dy < 0 else (dy, False)
    if adx > 176 or ady > 176:
        return None                      # Chebyshev pre-cull
    ac, mc = (-c, True) if c < 0 else (c, False)
    asn, ms = (-s, True) if s < 0 else (s, False)
    t1 = (adx * asn + 128) >> 8          # v = dx*sin + dy*cos
    t2 = (ady * ac + 128) >> 8
    v = (-t1 if mdx ^ ms else t1) + (-t2 if mdy ^ mc else t2)
    if v >= 0:
        return None
    d = -v
    if d > 255 or _VK[d] == 0xFF:
        return None
    k = _VK[d]
    tier = (_TIER_NOCULL if nocull else _TIER_LUT)[k]
    if tier == 0xFF:
        return None                      # tier-scaled seam-margin cull
    t1 = (adx * ac + 128) >> 8           # u = dx*cos - dy*sin
    t2 = (ady * asn + 128) >> 8
    u = (-t1 if mdx ^ mc else t1) + (-t2 if mdy ^ (not ms) else t2)
    au = -u if u < 0 else u
    if au >= 256:
        return None
    r = _RECIP_LO[k] | (_RECIP_HI[k] << 8)
    sxoff = ((au * (r & 0xFF)) >> 8) + (au if r >> 8 else 0)
    if sxoff >= 160:
        return None
    sx = 128 - sxoff if u < 0 else 128 + sxoff
    return sx, band_top + k, tier


def _is_marker(px):
    """Player-marker magenta ($7C1F): red+blue, no green — disjoint from the
    floor's green/red-green space AND from the AI discs' white."""
    r, g, b = px[:3]
    return r > 150 and b > 150 and g < 80


def _is_white(px):
    r, g, b = px[:3]
    return r > 200 and g > 200 and b > 200


def _patch_count(pix, sx, sy, classify, half=7):
    n = 0
    for y in range(sy - half + OFF, sy + half + 1 + OFF):
        for x in range(sx - half, sx + half + 1):
            if 0 <= x < 256 and 0 <= y < 239 and classify(pix[x, y]):
                n += 1
    return n


def _sp_poke_n(runner, n):
    runner.write_bytes(WR, SP_N_ADDR, struct.pack("<H", n))


# The two-port scripted input: per phase (frames, port0 buttons, port1
# buttons). frame_step latches port 0 per step; the port-1 override is set
# per phase and persists (split_v two-port pattern).
SP_SCRIPT = [
    (10, dict(right=True, b=True), dict(left=True)),
    (8, dict(b=True), {}),
    (6, {}, dict(right=True, b=True)),
    (6, {}, {}),
]


def _sp_run_script(runner, rom, script, n=16):
    runner.load_rom(str(rom), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "sprite ROM no boot"
    _sp_poke_n(runner, n)
    traj = []
    with runner.frame_stepping():
        runner.frame_step(2)             # settle (idle-persistence lesson)
        for frames, p0, p1 in script:
            runner.set_input(1, **p1)
            for _ in range(frames):
                runner.frame_step(1, **p0)
                traj.append(tuple(runner.read_u16(WR, a) for a in
                                  (H1_ADDR, H2_ADDR) + POS_ADDRS_SP)
                            + tuple(runner.read_u16(WR, a) & 0xFF
                                    for a in FRAC_ADDRS_SP))
        runner.set_input(1)              # port-1 override persists — clear it
    return traj


def _sp_model_script(script):
    """Exact integer model of the scripted camera trajectory from boot state:
    turn (+-1 pose/frame held) THEN move (2.0 px/f move256 8.8 accumulators),
    matching sp_players. The determinism test asserts the EMULATED trajectory
    equals this model byte-for-byte."""
    h = [0, 128]
    pos = [512, 512, 768, 512]
    frac = [0, 0, 0, 0]
    out = []
    for frames, p0, p1 in script:
        for _ in range(frames):
            for cam, btn in ((0, p0), (1, p1)):
                if btn.get("right"):
                    h[cam] = (h[cam] + 1) & 255
                if btn.get("left"):
                    h[cam] = (h[cam] - 1) & 255
                if btn.get("b"):
                    vx, vy = struct.unpack_from("<hh", _MOVE256, h[cam] * 4)
                    for j, vv in ((cam * 2, vx), (cam * 2 + 1, vy)):
                        s = frac[j] + vv
                        pos[j] = (pos[j] + (s >> 8)) & 0x3FF
                        frac[j] = s & 0xFF
            out.append((h[0], h[1]) + tuple(pos) + tuple(frac))
    return out


def test_sp_input_determinism_two_ports(roms, runner):
    """PROGRAMMED INPUTS (increment 1): deterministic two-port scripts.
    TEST SURFACE: WRAM camera state (headings, positions, 8.8 fraction
    accumulators) — the motion/cadence class where WRAM is the sanctioned
    oracle. Asserts:
      (a) two full reruns of the same script produce BYTE-IDENTICAL
          trajectories (load_rom reboot between);
      (b) the trajectory equals the exact integer model (turn-then-move,
          move256 8.8 accumulators) — a wrong port mapping, a dropped
          fraction, or an auto-read race all diverge;
      (c) idle persistence: with no input, 2 settle frames then 6 more
          leave every camera word untouched (split-v lesson);
      (d) INPUT-SCRAMBLE CONTROL (non-vacuity): flipping one button in the
          script changes the SAME trajectory metric."""
    t1 = _sp_run_script(runner, roms["spr_sweep"], SP_SCRIPT)
    t2 = _sp_run_script(runner, roms["spr_sweep"], SP_SCRIPT)
    assert t1 == t2, "scripted trajectory not reproducible across runs"
    assert t1 == _sp_model_script(SP_SCRIPT), \
        "trajectory diverged from the turn-then-move 8.8 input model"
    # (c) parked: no input -> state frozen after the 2-frame settle
    runner.load_rom(str(roms["spr_sweep"]), run_seconds=0.6)
    _sp_poke_n(runner, 16)
    with runner.frame_stepping():
        runner.frame_step(2)
        base = [runner.read_u16(WR, a)
                for a in (H1_ADDR, H2_ADDR) + POS_ADDRS_SP]
        for _ in range(6):
            runner.frame_step(1)
        after = [runner.read_u16(WR, a)
                 for a in (H1_ADDR, H2_ADDR) + POS_ADDRS_SP]
    assert base == after, f"no-input run drifted: {base} -> {after}"
    # (d) scramble control: left instead of right in phase 0, port 0
    scr = [(10, dict(left=True, b=True), dict(left=True))] + SP_SCRIPT[1:]
    t3 = _sp_run_script(runner, roms["spr_sweep"], scr)
    assert t3 != t1, "input-scramble control did not alter the trajectory"


def test_sp_player_marker_renders_in_other_band(roms, runner):
    """PLAYER MARKERS (increment 1): player 2's world-space marker renders in
    BAND 1 (camera 1's view) once camera 1 turns and drives within range; in
    each player's OWN band the marker projects to v>=0 (behind the pivot) and
    self-culls by construction -> band 2 shows ZERO magenta.
    TEST SURFACE: the rendered framebuffer (magenta patch at the position the
    bit-exact mirror predicts from live WRAM); the own-band zero-count is the
    built-in flip of the same metric."""
    runner.load_rom(str(roms["spr_sweep"]), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    _sp_poke_n(runner, 2)                # players only: no AI discs in frame
    with runner.frame_stepping():
        runner.frame_step(2)
        for _ in range(64):              # h1: 0 -> 192 (face +x, toward P2)
            runner.frame_step(1, left=True)
        assert runner.read_u16(WR, H1_ADDR) == 192
        for _ in range(68):              # drive ~136 px toward P2
            runner.frame_step(1, b=True)
        runner.write_bytes(WR, SP_HOLD_ADDR, b"\x01\x00")   # freeze world
        runner.frame_step(4)             # settle the snapshot pipeline
        p1x = runner.read_u16(WR, POS_ADDRS_SP[0])
        p1y = runner.read_u16(WR, POS_ADDRS_SP[1])
        h1 = runner.read_u16(WR, H1_ADDR)
        p2x = runner.read_u16(WR, POS_ADDRS_SP[2])
        p2y = runner.read_u16(WR, POS_ADDRS_SP[3])
        pix = _grab(runner, "sp_marker")
    exp = sp_project(p2x, p2y, p1x, p1y, h1, 0)
    assert exp is not None, \
        f"P2 not projectable from P1=({p1x},{p1y}) h1={h1} — script drifted"
    sx, sy, tier = exp
    got = _patch_count(pix, sx, sy, _is_marker, half=SP_TIER_HALF[tier])
    assert got >= 6, f"no magenta marker at predicted ({sx},{sy}), tier {tier}"
    # own-band self-cull: band 2 (camera 2's view) carries NO magenta at all
    band2 = sum(1 for y in range(SEAM + OFF, 224 + OFF)
                for x in range(256) if _is_marker(pix[x, y]))
    assert band2 == 0, f"band 2 shows {band2} magenta px — own-band cull broken"


# --- AI followers (increment 2) -----------------------------------------------

_WAY = (_SPA / "sp_way.bin").read_bytes()
_WORLD_MAIN = (_SPA / "sp_world_main.bin").read_bytes()


def _sp_ai_model(n_followers, frames):
    """Exact integer model of sp_ai_tick (one tick per G_FRAMES loop
    iteration — mapping verified on the emulator): steer (cross-sign, +-1
    heading step, 180-degree dot tie-break) then move at half speed through
    the 8.8 accumulators. Identical to the build-time simulation that proves
    bounded waypoint arrival for every follower."""
    ents = []
    for i in range(2, 2 + n_followers):
        x, y = struct.unpack_from("<HH", _WORLD_MAIN, i * 4)
        ents.append(dict(x=x, y=y, h=0, wp=((i - 2) >> 3) & 3, fx=0, fy=0,
                         loop=(i - 2) & 7))
    for _f in range(frames):
        for e in ents:
            tx, ty = struct.unpack_from("<HH", _WAY,
                                        e["loop"] * 16 + e["wp"] * 4)
            dx = ((tx - e["x"] + 512) & 1023) - 512
            dy = ((ty - e["y"] + 512) & 1023) - 512
            if max(abs(dx), abs(dy)) < 24:
                e["wp"] = (e["wp"] + 1) & 3
                continue
            fx, fy = struct.unpack_from("<hh", _MOVE256, e["h"] * 4)
            cross = (fx >> 3) * (dy >> 3) - (fy >> 3) * (dx >> 3)
            if cross < 0:
                e["h"] = (e["h"] + 1) & 255
            elif cross > 0:
                e["h"] = (e["h"] - 1) & 255
            else:
                dot = (fx >> 3) * (dx >> 3) + (fy >> 3) * (dy >> 3)
                if dot < 0:
                    e["h"] = (e["h"] + 1) & 255
            vx, vy = struct.unpack_from("<hh", _MOVE256, e["h"] * 4)
            for ax, vv in (("x", vx >> 1), ("y", vy >> 1)):
                s = e["f" + ax] + vv
                e[ax] = (e[ax] + (s >> 8)) & 1023
                e["f" + ax] = s & 0xFF
    return [(e["x"], e["y"], e["h"], e["wp"], e["fx"], e["fy"]) for e in ents]


def _sp_read_followers(runner, lo, hi):
    out = []
    for i in range(lo, hi):
        e = runner.read_bytes(WR, SP_ENTS + i * 8, 8)
        x, y, hw, fw = struct.unpack("<HHHH", e)
        out.append((x, y, hw & 0xFF, (hw >> 8) & 0xFF, fw & 0xFF, fw >> 8))
    return out


def test_sp_ai_followers_exact_model_and_ncap(roms, runner):
    """AI FOLLOWERS (increment 2): after F stepped frames the ENTIRE follower
    state block (x, y, heading, waypoint, both 8.8 fraction bytes) equals the
    exact integer steering model at EXACTLY F ticks — a wrong steering sense,
    a dropped tie-break, a broken fraction carry or a tick-rate skew all
    diverge within a few frames. Model equivalence transfers the build-time
    bounded-arrival proof (every follower reaches >= 3 waypoints within the
    simulated frame bound) to the emulated implementation.
    TEST SURFACE: WRAM entity state (motion class). Determinism: two boots
    reach the identical state at the same tick count. N-cap: followers at
    index >= SP_N never move (their world-table bytes stay pristine)."""
    states = []
    for _run in range(2):
        runner.load_rom(str(roms["spr_sweep"]), run_seconds=0.6)
        assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
        _sp_poke_n(runner, 16)           # 14 followers live, 2..15
        with runner.frame_stepping():
            runner.frame_step(1)         # flush the in-flight frame at old N
            parked0 = _sp_read_followers(runner, 20, 24)  # beyond SP_N now
            runner.frame_step(60)
            g = runner.read_u16(WR, G_FRAMES)
            got = _sp_read_followers(runner, 2, 16)
            parked1 = _sp_read_followers(runner, 20, 24)
        assert got == _sp_ai_model(14, g), \
            f"follower state diverged from the exact AI model at tick {g}"
        # N-cap: entities >= SP_N do not tick once the count is lowered
        # (they DID tick during the boot window at the compile default 128)
        assert parked0 == parked1, \
            f"entities >= SP_N kept moving: {parked0} -> {parked1}"
        states.append((g, got))
    # Determinism across boots: each boot independently matched the SAME pure
    # function of its tick count (the exact-model asserts above) — the tick
    # counts themselves differ by wall-clock load variance, so equal-g raw
    # comparison would be flaky by construction. Two independent exact-model
    # matches at 60+ ticks each IS the reproducibility proof.
    assert all(g >= 60 for g, _ in states)


def test_sp_ai_reaches_waypoints_bounded_and_renders(roms, runner):
    """WAYPOINT ARRIVAL measured ON THE EMULATOR + the rendered-output check:
      (a) free-run ~15 s polling each sampled follower's waypoint index —
          every one of followers 2..9 advances >= 1 waypoint within 1000
          frames (E010 is the frame clock; the build-time simulation bounds
          the FIRST arrival well under that);
      (b) rendered ring check: SP_HOLD freezes the world, the pipeline
          settles, and every follower the bit-exact mirror projects to an
          interior position must show WHITE disc pixels there in the
          screenshot; 3 far-from-any-prediction floor spots show ZERO white
          (the same-metric flip — white only exists where sprites are).
    TEST SURFACE: framebuffer for (b); WRAM waypoint indices + NMI frame
    clock for (a)."""
    runner.load_rom(str(roms["spr_sweep"]), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    _sp_poke_n(runner, 32)
    n0 = runner.read_u16(WR, HEARTBEAT)
    wp0 = [_sp_read_followers(runner, i, i + 1)[0][3] for i in range(2, 10)]
    seen = [set() for _ in range(8)]
    frames = 0
    while frames < 1000 and not all(len(s) > 0 for s in seen):
        time.sleep(0.5)
        frames = (runner.read_u16(WR, HEARTBEAT) - n0) & 0xFFFF
        for j in range(8):
            wp = _sp_read_followers(runner, 2 + j, 3 + j)[0][3]
            if wp != wp0[j]:
                seen[j].add(wp)
    laggards = [2 + j for j in range(8) if not seen[j]]
    assert not laggards, \
        f"followers {laggards} reached no waypoint within {frames} frames"
    # (b) freeze + settle + rendered ring check at mirror-predicted spots
    runner.write_bytes(WR, SP_HOLD_ADDR, b"\x01\x00")
    time.sleep(0.2)
    st = {a: runner.read_u16(WR, a) for a in
          (H1_ADDR, H2_ADDR) + POS_ADDRS_SP}
    ents = _sp_read_followers(runner, 2, 32)
    pix = _grab(runner, "sp_ai_ring")
    preds = []
    for (x, y, _h, _wp, _fx, _fy) in ents:
        for band, (px, py, hh, top) in enumerate(
                ((st[POS_ADDRS_SP[0]], st[POS_ADDRS_SP[1]], st[H1_ADDR], 0),
                 (st[POS_ADDRS_SP[2]], st[POS_ADDRS_SP[3]], st[H2_ADDR], 112))):
            pt = sp_project(x, y, px, py, hh, top)
            if pt is None:
                continue
            sx, sy, tier = pt
            lo, hi = (14, 98) if band == 0 else (126, 210)
            if 20 <= sx <= 235 and lo <= sy <= hi:
                preds.append((sx, sy, tier))
    assert len(preds) >= 2, \
        f"only {len(preds)} interior follower projections — world drifted?"
    for sx, sy, tier in preds[:8]:
        got = _patch_count(pix, sx, sy, _is_white, half=SP_TIER_HALF[tier])
        assert got >= 10, \
            f"no white disc at predicted ({sx},{sy}) tier {tier}: {got} px"
    # same-metric flip: floor spots far from every prediction carry NO white
    spots = [(40, 40), (200, 60), (70, 170)]
    for sx, sy in spots:
        if all(abs(sx - qx) > 30 or abs(sy - qy) > 30 for qx, qy, _ in preds):
            assert _patch_count(pix, sx, sy, _is_white, half=7) == 0, \
                f"white pixels on bare floor at ({sx},{sy}) — classifier broken"
    runner.write_bytes(WR, SP_HOLD_ADDR, b"\x00\x00")


# --- size tiers + seam margins (increment 3) -----------------------------------

_WORLD_TIER = (_SPA / "sp_world_tier.bin").read_bytes()
SP_TIER_DIAM = (10, 12, 14, 18, 22)      # drawn disc diameters per tier (2r)


def _white_extent(pix, sx, sy):
    """(width, height) of the disc at a predicted centre, measured as the
    CONTIGUOUS white runs through the centre row / centre column (discs are
    solid, so the through-centre run is the diameter; a detached neighbour
    can never join a contiguous run — the bbox version was neighbour-prone).
    The centre probes +-1 px to absorb the mirror's 1-px rounding."""
    def run_h(cy):
        if not _is_white(pix[sx, cy]):
            return 0
        lo = sx
        while lo - 1 >= 0 and _is_white(pix[lo - 1, cy]):
            lo -= 1
        hi = sx
        while hi + 1 < 256 and _is_white(pix[hi + 1, cy]):
            hi += 1
        return hi - lo + 1

    def run_v(cx):
        cy = sy + OFF
        if not _is_white(pix[cx, cy]):
            return 0
        lo = cy
        while lo - 1 >= 0 and _is_white(pix[cx, lo - 1]):
            lo -= 1
        hi = cy
        while hi + 1 < 239 and _is_white(pix[cx, hi + 1]):
            hi += 1
        return hi - lo + 1

    width = max(run_h(sy + OFF + d) for d in (-1, 0, 1))
    height = max(run_v(sx + d) for d in (-1, 0, 1))
    return width, height


def _tier_world_projections(runner, n):
    """Mirror-project the first n tier-world entries against the live pinned
    camera state; [(idx, sx, sy, tier)] for the non-culled ones."""
    st = {a: runner.read_u16(WR, a) for a in (H1_ADDR,) + POS_ADDRS_SP}
    out = []
    for i in range(n):
        wx, wy = struct.unpack_from("<HH", _WORLD_TIER, i * 4)
        pt = sp_project(wx, wy, st[POS_ADDRS_SP[0]], st[POS_ADDRS_SP[1]],
                        st[H1_ADDR], 0)
        if pt is not None:
            out.append((i,) + pt)
    return out


def test_sp_tier_ladder_extents_and_boundaries(roms, runner):
    """SIZE TIERS (increment 3): on the pinned tier-ladder still the RENDERED
    disc extent at each mirror-predicted position matches the committed
    LUT's tier for that row (drawn diameters 10/12/14/18/22 px, +-3), the
    ladder covers ALL FIVE tiers, and walking the ladder by row the tier
    index never jumps by more than ONE step (no popping worse than one tier
    step — the LUT boundaries are contiguous by construction and the render
    must follow them).
    TEST SURFACE: framebuffer extents. NON-VACUITY: the -DSP_TIEROFF build
    (constant tier 2) collapses the far-vs-near extent spread on the SAME
    metric at the SAME predicted positions."""
    runner.load_rom(str(roms["spr_tier"]), run_seconds=0.8)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    _sp_poke_n(runner, 24)               # the ladder only (no cluster/probes)
    time.sleep(0.3)
    pix = _grab(runner, "sp_tier")
    preds = _tier_world_projections(runner, 24)
    assert len(preds) >= 20, f"ladder lost sprites: {len(preds)}"
    seen_tiers = set()
    by_k = []
    for i, sx, sy, tier in preds:
        if not (16 <= sx <= 239 and 10 <= sy <= 110):
            continue                     # extent window must fit the band
        w, h = _white_extent(pix, sx, sy)
        exp = SP_TIER_DIAM[tier]
        assert abs(w - exp) <= 3, \
            f"ladder {i} @k={sy}: tier {tier} width {w} != ~{exp}"
        assert abs(h - exp) <= 3, \
            f"ladder {i} @k={sy}: tier {tier} height {h} != ~{exp}"
        seen_tiers.add(tier)
        by_k.append((sy, tier))
    assert seen_tiers == {0, 1, 2, 3, 4}, f"ladder missed tiers: {seen_tiers}"
    by_k.sort()
    for (k0, t0), (k1, t1) in zip(by_k, by_k[1:]):
        assert 0 <= t1 - t0 <= 1, \
            f"tier popped {t0}->{t1} between rows {k0}->{k1}"
    # --- SP_TIEROFF control: constant tier -> the extent spread collapses ---
    spread = max(t for _k, t in by_k) - min(t for _k, t in by_k)
    assert spread == 4                   # default build spans the full ladder
    runner.load_rom(str(roms["spr_tieroff"]), run_seconds=0.8)
    _sp_poke_n(runner, 24)
    time.sleep(0.3)
    pix = _grab(runner, "sp_tieroff")
    widths = []
    for i, sx, sy, _tier in preds:       # same predicted centres (positions
        if not (16 <= sx <= 239 and 10 <= sy <= 110):
            continue                     # are tier-independent)
        w, h = _white_extent(pix, sx, sy)
        widths.append(w)
        assert abs(w - SP_TIER_DIAM[2]) <= 3, \
            f"TIEROFF sprite {i} width {w} != constant ~14"
    assert max(widths) - min(widths) <= 4, \
        "TIEROFF control failed to collapse the size ladder"


def test_sp_seam_margin_cull_and_culloff_control(roms, runner):
    """SEAM DISCIPLINE (increment 3, the measured-margin deliverable): with
    the margin culls folded into the tier LUT, NO white sprite pixel may
    touch PPU rows 111-112 (the 2-row guard band: band-1 content ends at
    k<=103+7/95+15 = 110; band-2 content starts at 112+9-8 = 113). The tier
    world carries three DEAD-ZONE PROBES (entries 60..62, rows 110/104/7 —
    band-local) that the default build must CULL.
    NON-VACUITY: -DSP_CULLOFF renders the probes; their boxes cross the band
    edges and the SAME guard-band metric flips to nonzero (incl. the k=7
    band-2 probe bleeding UP into band-1 territory).
    TEST SURFACE: framebuffer white counts on exact rows (+7 offset
    modeled)."""
    def guard_white(pix):
        return sum(1 for y in (111 + OFF, 112 + OFF)
                   for x in range(256) if _is_white(pix[x, y]))

    runner.load_rom(str(roms["spr_tier"]), run_seconds=0.8)
    _sp_poke_n(runner, 63)               # ladder + cluster + margin probes
    time.sleep(0.3)
    pix = _grab(runner, "sp_seam_default")
    assert guard_white(pix) == 0, "default build leaked white into the guard band"
    runner.load_rom(str(roms["spr_culloff"]), run_seconds=0.8)
    _sp_poke_n(runner, 63)
    time.sleep(0.3)
    pix = _grab(runner, "sp_seam_culloff")
    leaked = guard_white(pix)
    assert leaked > 20, \
        f"CULLOFF control only leaked {leaked} px — probes missing?"


# --- the stress sweep (increment 4: THE deliverable) ---------------------------

SWEEP_NS = (8, 16, 24, 32, 48, 64, 96, 128)
SHIP_DEFAULT_N = 24                      # largest N with lockstep AND >=15%
                                         # modeled headroom (cycint: 24->31%,
                                         # 32->10%) — the ship rule


def _sp_cadence_gate(runner, rom, n, steps=24):
    """The in-situ +1/+1 gate on an integrated build with BOTH players
    actively turning+driving (scripted input, ports 0+1)."""
    runner.load_rom(str(rom), run_seconds=0.6)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    _sp_poke_n(runner, n)
    time.sleep(0.2)
    with runner.frame_stepping():
        runner.set_input(1, right=True, b=True)
        runner.frame_step(2, left=True, b=True)
        g0 = runner.read_u16(WR, G_FRAMES)
        h0 = runner.read_u16(WR, HEARTBEAT)
        lock, gd, hd, i = True, 0, 0, 0
        for i in range(1, steps + 1):
            runner.frame_step(1, left=True, b=True)
            gd = (runner.read_u16(WR, G_FRAMES) - g0) & 0xFFFF
            hd = (runner.read_u16(WR, HEARTBEAT) - h0) & 0xFFFF
            if gd != i or hd != i:
                lock = False
                break
        runner.set_input(1)
    return dict(n=n, lockstep=lock, step=i, g=gd, nmi=hd)


def test_sp_cadence_sweep_curve(roms, runner):
    """THE SPRITES-VS-CADENCE CURVE (the sprint deliverable): the in-situ
    +1/+1 lockstep gate over N in {8..128} on the INTEGRATED build (scripted
    two-port input + AI pathing + tiers, scattered world), plus the same grid
    on the ALTERNATE-FRAME REPROJECTION probe (halves re-project at 30 Hz
    over the 60 Hz display — an owner feel-test question, NOT the default).
    Durable asserts (border points are recorded, not asserted):
      - full-rate build holds lockstep at the ship default (24) and at 32;
      - full-rate build BREAKS at 128 (the gate metric's non-vacuity: the
        same counter pair reads a miss when the budget is truly blown);
      - the alt-frame probe holds lockstep at 64 (the measured 'doubled
        ceiling' data point: full-rate breaks at 48, alt holds 64).
    The whole curve lands in /tmp/e2e_screenshots/task2_curve.json.
    TEST SURFACE: the two WRAM counters whose lockstep IS the claim."""
    curve = {"full": [], "altframe": []}
    for key, rom in (("full", roms["spr_sweep"]), ("altframe", roms["spr_alt"])):
        for n in SWEEP_NS:
            r = _sp_cadence_gate(runner, rom, n)
            curve[key].append(r)
    full = {r["n"]: r["lockstep"] for r in curve["full"]}
    alt = {r["n"]: r["lockstep"] for r in curve["altframe"]}
    assert full[SHIP_DEFAULT_N], "ship default N lost lockstep"
    assert full[32], "N=32 lost lockstep (was: lockstep with 10% headroom)"
    assert not full[128], \
        "N=128 held lockstep?! the gate metric reads nothing (vacuous)"
    assert alt[64], "alt-frame probe lost its measured N=64 lockstep"
    out = Path("/tmp/e2e_screenshots")
    out.mkdir(exist_ok=True)
    (out / "task2_curve.json").write_text(json.dumps(curve, indent=2))


def test_sp_overflow_row_forensics(roms, runner):
    """OBJ-PER-SCANLINE OVERFLOW FORENSICS: the tier world's cluster packs
    ~30 32x32 sprites onto ONE tier-3 row (band-local k=78). The hardware's
    34-sliver/line limit divided by 4 slivers per 32x32 OBJ = 8 fully-drawn
    sprites per row — the sliver limit binds long before the 32-OBJ range
    limit (30 < 32: range-over never trips here). Measured: exactly ~8 of
    the ~30 intended centres render solid white.
    NON-VACUITY: sparse ladder rows in the SAME frame render EVERY disc
    (same centre-presence metric, zero drops).
    TEST SURFACE: framebuffer centre-presence counts vs the mirror intent."""
    runner.load_rom(str(roms["spr_tier"]), run_seconds=0.8)
    _sp_poke_n(runner, 63)
    time.sleep(0.3)
    pix = _grab(runner, "sp_overflow")
    st = {a: runner.read_u16(WR, a) for a in (H1_ADDR,) + POS_ADDRS_SP}

    def centre_white(sx, sy):
        return sum(1 for dx in range(-3, 4) for dy in range(-3, 4)
                   if 0 <= sx + dx < 256
                   and _is_white(pix[sx + dx, sy + OFF + dy]))

    cluster, ladder = [], []
    for i in range(60):
        wx, wy = struct.unpack_from("<HH", _WORLD_TIER, i * 4)
        pt = sp_project(wx, wy, st[POS_ADDRS_SP[0]], st[POS_ADDRS_SP[1]],
                        st[H1_ADDR], 0)
        if pt is None:
            continue
        (cluster if i >= 24 else ladder).append(pt)
    assert len(cluster) >= 25, f"cluster shrank: {len(cluster)} visible"
    rows = {sy for _sx, sy, _t in cluster}
    assert len(rows) == 1, f"cluster no longer shares one row: {rows}"
    drawn = sum(1 for sx, sy, _t in cluster if centre_white(sx, sy) >= 20)
    assert drawn < len(cluster) - 10, \
        f"no overflow on a {len(cluster)}-sprite row? {drawn} drawn"
    assert 5 <= drawn <= 11, \
        f"per-row ceiling drifted: {drawn} full sprites (sliver model: 8)"
    # sparse-row control: interior ladder discs all render. NOTE the window:
    # the cluster's 32x32 BOXES span rows 62..93 and consume slivers across
    # that whole span even where transparent — a ladder disc at k=64 was
    # eaten by the pileup (measured; the damage radius of an overloaded row
    # is the OBJ BOX height, not the drawn pixels). Control rows must clear
    # the box span: 16x16 ladder discs need k+8 < 62.
    checked = 0
    for sx, sy, _t in ladder:
        if 20 <= sx <= 235 and 12 <= sy <= 52:
            assert centre_white(sx, sy) >= 20, \
                f"sparse-row disc missing at ({sx},{sy})"
            checked += 1
    assert checked >= 4, f"too few sparse-row controls: {checked}"
    (Path("/tmp/e2e_screenshots") / "task2_overflow.json").write_text(
        json.dumps(dict(intended=len(cluster), drawn_full=drawn,
                        row=sorted(rows)[0],
                        model="34 slivers / 4 per 32x32 OBJ = 8")))


def test_sp_shipped_default_gate(roms, runner):
    """THE SHIPPED RAIL (_sprites, SPRITES=24 SP_INPUT): boots, the 6-channel
    masks hold, sprites are ON SCREEN, no OAM overflow ever at this N, and
    the in-situ cadence gate holds lockstep with both players active — the
    ship rule (lockstep AND >=15% modeled headroom) selected N=24.
    TEST SURFACE: framebuffer (white presence) + WRAM counters."""
    runner.load_rom(str(roms["sprites"]), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_u16(WR, MSK_MATRIX) == 0x0C
    assert runner.read_u16(WR, MSK_BAND1) == 0x30
    assert runner.read_u16(WR, MSK_ORIGIN) == 0xC0
    assert runner.read_u16(WR, SP_N_ADDR) == SHIP_DEFAULT_N
    pix = _grab(runner, "sp_default")
    white = sum(1 for y in range(OFF, 224 + OFF) for x in range(0, 256, 2)
                if _is_white(pix[x, y]))
    assert white > 30, f"no sprites on screen in the shipped default ({white})"
    assert runner.read_u16(WR, SP_OVER_ADDR) == 0, "OAM overflow at N=24?!"
    r = _sp_cadence_gate(runner, roms["sprites"], SHIP_DEFAULT_N)
    assert r["lockstep"], f"shipped default broke cadence: {r}"


# --- the glue proof: pinned stills + the wrong-matrix control -------------------

SP_MIRBASE = 0xE400


def _sp_expected_main(runner, n=128, forward=False):
    """Mirror-projected expectations for the STATIC main world against live
    WRAM camera state; {band: [(i, sx, sy, tier)]}."""
    st = {a: runner.read_u16(WR, a) for a in
          (H1_ADDR, H2_ADDR) + POS_ADDRS_SP}
    exp = {0: [], 1: []}
    for i in range(n):
        wx, wy = struct.unpack_from("<HH", _WORLD_MAIN, i * 4)
        pt = sp_project(wx, wy, st[POS_ADDRS_SP[0]], st[POS_ADDRS_SP[1]],
                        st[H1_ADDR], 0, forward)
        if pt:
            exp[0].append((i,) + pt)
        pt = sp_project(wx, wy, st[POS_ADDRS_SP[2]], st[POS_ADDRS_SP[3]],
                        st[H2_ADDR], 112, forward)
        if pt:
            exp[1].append((i,) + pt)
    return exp


def _sp_interior(band, sx, sy):
    lo, hi = (14, 98) if band == 0 else (126, 210)
    return 20 <= sx <= 235 and lo <= sy <= hi


def test_sp_glue_proof_pinned_and_forward_control(roms, runner):
    """THE FRAMEBUFFER GLUE PROOF (the mode7_oshoot meta-lesson): at three
    pinned heading pairs on the ASYMMETRIC main world, WHITE disc pixels are
    present at every interior position the bit-exact mirror predicts from
    live WRAM — and the ASM's own $7E:E400 debug mirrors agree with the
    Python mirror within 1 px (drift DIAGNOSTIC; the pass/fail oracle is the
    render). NON-VACUITY (wrong-matrix): the -DSP_FORWARD build projects
    with the FORWARD floor matrix; every discriminating predicted spot
    (>=24 px from anything the control build legitimately draws) must MISS.
    TEST SURFACE: framebuffer patches at mirror-predicted positions."""
    for tag in ("spr_pin_a", "spr_pin_b", "spr_pin_c"):
        runner.load_rom(str(roms[tag]), run_seconds=0.8)
        assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", f"{tag} no boot"
        # PARK before touching the $7E:E400 mirrors: the free-running loop
        # rewrites every entry as sentinel-then-value each frame, and a read
        # landing in that window fakes a 32k-px "drift" (audit-1 finding 1
        # caught the $7FFF sentinel live — the own-paper-cut sampling race).
        # At the canonical park the loop idles in `wai`; reads are race-free.
        with runner.frame_stepping():
            runner.frame_step(2)
            exp = _sp_expected_main(runner)
            pix = _grab(runner, f"glue_{tag}")
            checked = 0
            for band in (0, 1):
                for i, sx, sy, tier in exp[band]:
                    if not _sp_interior(band, sx, sy):
                        continue
                    got = _patch_count(pix, sx, sy, _is_white,
                                       half=SP_TIER_HALF[tier])
                    assert got >= 8, \
                        f"{tag}: no white at predicted ({sx},{sy}) b{band} i{i}"
                    # ASM mirror drift diagnostic (never the oracle)
                    base = SP_MIRBASE + band * 512 + i * 4
                    msx = runner.read_u16(WR, base)
                    msy = runner.read_u16(WR, base + 2)
                    assert abs(msx - sx) <= 1 and abs(msy - sy) <= 1, \
                        f"{tag}: ASM mirror drift b{band} i{i}: ({msx},{msy})" \
                        f" vs ({sx},{sy})"
                    checked += 1
        assert checked >= 6, f"{tag}: only {checked} interior glue checks"
    # ---- wrong-matrix control ----
    runner.load_rom(str(roms["spr_pinfwd"]), run_seconds=0.8)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    time.sleep(0.2)
    exp_inv = _sp_expected_main(runner)              # where CORRECT math lands
    exp_fwd = _sp_expected_main(runner, forward=True)  # what the control draws
    fwd_pts = [(sx, sy) for b in (0, 1) for _i, sx, sy, _t in exp_fwd[b]]
    pix = _grab(runner, "glue_fwd")
    misses = spots = 0
    for band in (0, 1):
        for i, sx, sy, tier in exp_inv[band]:
            if not _sp_interior(band, sx, sy):
                continue
            if any(abs(fx - sx) < 24 and abs(fy - sy) < 24
                   for fx, fy in fwd_pts):
                continue                             # control paints nearby
            spots += 1
            if _patch_count(pix, sx, sy, _is_white, half=7) < 5:
                misses += 1
    assert spots >= 4, f"only {spots} discriminating control spots"
    assert misses == spots, \
        f"WRONG-MATRIX CONTROL DID NOT FAIL: {spots - misses} hits — vacuous"
