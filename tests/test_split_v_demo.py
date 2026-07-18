"""split_v_demo — vertical left/right dual-view via window-clipped dual BG cameras.

Proves the sf_split_v v1 done-conditions on the cycle-accurate emulator by
reading the RENDERED framebuffer (kit rule #2 — every assertion reads pixels or
hardware regions, never an engine proxy variable):

  D1  boots -> the left half renders camera A, the right half renders camera B
      of the SAME landscape at a different scroll, with a clean straight vertical
      seam and ZERO cross-bleed.
  D2  input moves each camera INDEPENDENTLY: P1 (port 0) scrolls only the left
      half, P2 (port 1) scrolls only the right half.
  D3  a swept seam moves the rendered boundary between the two cameras.
  D4  a red player marker straddling the seam is CLIPPED to the left half by the
      OBJ window (-DOBJ_CLIP variant), and the right-half marker is confined out.
  D5  non-vacuity control (-DNO_WINDOW): the window recipe is compiled out, the
      view collapses to ONE full-screen camera, and the D1 two-region signature
      (a horizon discontinuity at the seam) MUST be ABSENT.

The stage is a side-on LANDSCAPE (sky over green hills, a grey mountain, a brown
dirt base) built from a 32-column height map, uploaded ONCE and shared by both
BG cameras (BG2 points at BG1's base). The seam is drawn with ZERO sprites: a
window-2 band masks all BG layers so the white BACKDROP shows through as the
seam bar. The test reads the HORIZON — the sky->terrain transition row per
column; the white seam columns carry no terrain and are EXCLUDED. Camera A is
the NO_WINDOW render (pure full-screen camera A); the dual view's left half must
match it exactly (zero bleed), the right half (camera B) diverges, with a sharp
horizon step where they meet.

Capture note: a screenshot taken on the same tick as an input change can catch
the BG scroll one commit before it settles, so every grab() runs a few settle
frames first (the rendered output then matches the committed camera).
"""
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

SHADOW_WH0 = 0xE10A            # window-1 left edge (seam) shadow -> PPU $2126
SHADOW_W12SEL = 0x0182        # $0100 + ES_SHADOW_W12SEL -> PPU $2123
SHADOW_TMW = 0x0187           # $0100 + ES_SHADOW_TMW    -> PPU $212E

# stage constants (must match templates/split_v_demo/main.asm)
SEAM0 = 128
BAND_HW = 6                   # seam-band half-width (white bar = 2*BAND_HW px)
Y_TOP = 14                    # skip the top overscan band in the screenshot
SETTLE = 3                    # frames to let a scroll commit settle before a grab


# --- framebuffer helpers ------------------------------------------------------
def _sky_dist2(p, s):
    return (p[0] - s[0]) ** 2 + (p[1] - s[1]) ** 2 + (p[2] - s[2]) ** 2


def _is_white(p):
    return p[0] > 200 and p[1] > 200 and p[2] > 200


def _is_black(p):
    return p[0] < 40 and p[1] < 40 and p[2] < 40


def _is_red(p):
    return p[0] > 150 and p[1] < 80 and p[2] < 80


def _grab(runner):
    """Screenshot the current frame -> (w, h, PixelAccess). Uses img.load() (not
    the deprecated getdata()) so pixels are addressed as pix[x, y]."""
    runner.run_frames(SETTLE)
    path = "/tmp/e2e_screenshots/split_v_demo.png"
    Path("/tmp/e2e_screenshots").mkdir(parents=True, exist_ok=True)
    runner.take_screenshot(path)
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return w, h, img.load()


def _horizon(w, h, pix):
    """Screen row of the sky->terrain transition per column, or None for a column
    masked by the white seam bar (white reached before terrain) — such columns
    carry no terrain signal and are excluded from every comparison."""
    sky = pix[8, Y_TOP]
    hz = []
    for x in range(w):
        row = None
        for y in range(Y_TOP, h - 8):
            p = pix[x, y]
            if _is_white(p):
                row = None           # seam-bar column -> exclude
                break
            if _sky_dist2(p, sky) > 3000 and not _is_black(p):
                row = y              # terrain top
                break
        hz.append(row)
    return hz


def _grab_horizon(runner):
    w, h, pix = _grab(runner)
    return w, h, _horizon(w, h, pix)


def _seam(runner):
    return runner.read_bytes(WR, SHADOW_WH0, 1)[0]


def _nearest(hz, x, step):
    while 8 <= x < len(hz) - 8:
        if hz[x] is not None:
            return hz[x]
        x += step
    return None


def _seam_discontinuity(hz, seam):
    """Horizon step across the seam, sampled just OUTSIDE the white bar — large
    when two cameras meet there, ~0 for a single continuous camera."""
    left = _nearest(hz, seam - (BAND_HW + 4), -1)
    right = _nearest(hz, seam + (BAND_HW + 4), +1)
    if left is None or right is None:
        return 0
    return abs(left - right)


def _both(a, b, x0, x1):
    return [x for x in range(x0, x1) if a[x] is not None and b[x] is not None]


def _changed(a, b, x0, x1):
    return sum(1 for x in _both(a, b, x0, x1) if abs(a[x] - b[x]) > 2)


# --- fixtures -----------------------------------------------------------------
@pytest.fixture(scope="module")
def roms():
    make = subprocess.run(["make", "split_v_demo"], cwd=str(ROOT),
                          capture_output=True, text=True)
    if make.returncode != 0:
        pytest.skip(f"`make split_v_demo` failed (toolchain?):\n{make.stderr}")
    script = ROOT / "templates" / "split_v_demo" / "build_split_v_variants.sh"
    var = subprocess.run(["bash", str(script)], cwd=str(ROOT),
                         capture_output=True, text=True)
    if var.returncode != 0:
        pytest.skip(f"variant build failed (toolchain?):\n{var.stderr}")
    return {
        "default": BUILD / "split_v_demo.sfc",
        "nowin": BUILD / "split_v_demo_nowin.sfc",
        "objclip": BUILD / "split_v_demo_objclip.sfc",
        "diagonal": BUILD / "split_v_demo_diagonal.sfc",
    }


@pytest.fixture(scope="module")
def runner():
    # ONE MesenRunner for the whole module (CLAUDE.md: never create a fresh
    # instance per test — load_rom() on the shared runner re-inits cleanly).
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module")
def cam_a_ref(roms, runner):
    """The single-camera-A horizon: the NO_WINDOW render is pure full-screen
    camera A (the window and seam bar are compiled out). The dual view's left
    half must match this exactly; the right half (camera B) must diverge."""
    runner.load_rom(str(roms["nowin"]), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "nowin ROM did not boot"
    runner.run_frames(20)
    _, _, hz = _grab_horizon(runner)
    return hz


# --- D1 -----------------------------------------------------------------------
def test_d1_two_camera_split_clean_seam(roms, runner, cam_a_ref):
    """D1: left half == camera A exactly (zero bleed), right half == a different
    camera (camera B), with a sharp horizon step where they meet at the seam."""
    runner.load_rom(str(roms["default"]), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "default ROM did not boot"
    runner.run_frames(20)

    # the committed window recipe: window 1 (split) + window 2 (seam band) ->
    # W12SEL = BG1 win1-in|win2-in ($A) | BG2 win1-out|win2-in ($B)<<4 = $BA;
    # TMW masks BG1+BG2+BG3 in their windows ($07).
    assert runner.read_bytes(WR, SHADOW_W12SEL, 1)[0] == 0xBA, "W12SEL != 0xBA"
    assert runner.read_bytes(WR, SHADOW_TMW, 1)[0] == 0x07, "TMW != 0x07"
    seam = _seam(runner)
    assert seam == SEAM0, f"seam(WH0)={seam}, expected {SEAM0}"

    w, h, hz = _grab_horizon(runner)

    # LEFT half is camera A, EXACTLY (== the single-camera reference).
    left_cols = _both(hz, cam_a_ref, 8, seam - BAND_HW - 2)
    left_hits = sum(1 for x in left_cols if abs(hz[x] - cam_a_ref[x]) <= 2)
    assert left_cols and left_hits / len(left_cols) > 0.95, \
        f"left half is not camera A / camera-B bled left ({left_hits}/{len(left_cols)})"

    # RIGHT half is a DIFFERENT camera (camera B, a different scroll).
    right_cols = _both(hz, cam_a_ref, seam + BAND_HW + 2, 248)
    right_diff = sum(1 for x in right_cols if abs(hz[x] - cam_a_ref[x]) > 2)
    assert right_cols and right_diff / len(right_cols) > 0.4, \
        f"right half does not render a second camera ({right_diff}/{len(right_cols)})"

    # clean seam: the two cameras meet at a SHARP horizon step.
    assert _seam_discontinuity(hz, seam) > 20, \
        f"no clean seam step at the boundary (disc={_seam_discontinuity(hz, seam)})"


# --- D2 -----------------------------------------------------------------------
def test_d2_cameras_scroll_independently(roms, runner, cam_a_ref):
    """D2: P1 input scrolls ONLY the left half; P2 input scrolls ONLY the right
    half. Measured on the rendered horizon of each half (seam columns skipped)."""
    runner.load_rom(str(roms["default"]), run_seconds=0.4)
    runner.run_frames(12)
    seam = _seam(runner)
    w, h, h0 = _grab_horizon(runner)

    runner.set_input(0, right=True)
    runner.run_frames(30)
    runner.set_input(0)
    w, h, h1 = _grab_horizon(runner)
    assert _changed(h0, h1, 8, seam - 12) > 10, "P1 did not move the LEFT camera"
    assert _changed(h0, h1, seam + 12, 248) == 0, \
        "P1 disturbed the RIGHT camera (not independent)"

    runner.set_input(1, right=True)
    runner.run_frames(30)
    runner.set_input(1)
    w, h, h2 = _grab_horizon(runner)
    assert _changed(h1, h2, seam + 12, 248) > 10, "P2 did not move the RIGHT camera"
    assert _changed(h1, h2, 8, seam - 12) == 0, \
        "P2 disturbed the LEFT camera (not independent)"


# --- D3 -----------------------------------------------------------------------
def _band_is_camera_a(hz, cam_a_ref, x0, x1):
    cols = _both(hz, cam_a_ref, x0, x1)
    if not cols:
        return 0.0
    return sum(1 for x in cols if abs(hz[x] - cam_a_ref[x]) <= 2) / len(cols)


def test_d3_swept_seam_moves_boundary(roms, runner, cam_a_ref):
    """D3: sweeping the seam (P1 shoulders) moves the rendered camera boundary.
    A band just right of centre flips from camera B to camera A as the seam
    sweeps past it, then back."""
    BAND = (140, 166)
    runner.load_rom(str(roms["default"]), run_seconds=0.4)
    runner.run_frames(12)
    seam0 = _seam(runner)
    w, h, a = _grab_horizon(runner)
    in_a0 = _band_is_camera_a(a, cam_a_ref, *BAND)
    assert in_a0 < 0.3, f"band should start as camera B ({in_a0:.2f})"

    runner.set_input(0, r=True)
    runner.run_frames(60)
    runner.set_input(0)
    seam_r = _seam(runner)
    w, h, b = _grab_horizon(runner)
    in_ar = _band_is_camera_a(b, cam_a_ref, *BAND)
    assert seam_r > seam0, f"seam shadow did not move right ({seam0}->{seam_r})"
    assert in_ar > 0.8, f"seam did not sweep past the band ({in_ar:.2f})"

    runner.set_input(0, l=True)
    runner.run_frames(110)
    runner.set_input(0)
    seam_l = _seam(runner)
    w, h, c = _grab_horizon(runner)
    in_al = _band_is_camera_a(c, cam_a_ref, *BAND)
    assert seam_l < seam_r, f"seam shadow did not move left ({seam_r}->{seam_l})"
    assert in_al < 0.3, f"seam did not sweep back ({in_al:.2f})"


# --- D4 -----------------------------------------------------------------------
def _red_columns(w, h, pix, y0, y1):
    """X columns that contain a red player-marker pixel in the band [y0,y1)."""
    cols = set()
    for y in range(y0, y1):
        for x in range(w):
            if _is_red(pix[x, y]):
                cols.add(x)
    return cols


def test_d4_obj_window_clips_marker_at_seam(roms, runner, cam_a_ref):
    """D4: in the -DOBJ_CLIP ROM the OBJ window confines sprites to the left half
    — the P1 marker straddling the seam is clipped (red left of seam, ZERO at or
    right of it) and the right-half P2 marker is gone."""
    runner.load_rom(str(roms["objclip"]), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "objclip ROM did not boot"
    runner.run_frames(20)
    # OBJ participates in window masking (TMW bit4 set on top of the $07 BG mask).
    assert runner.read_bytes(WR, SHADOW_TMW, 1)[0] == 0x17, "OBJ window not enabled"
    seam = _seam(runner)
    w, h, pix = _grab(runner)
    cols = _red_columns(w, h, pix, 160, 200)     # the player-marker row band
    left = [x for x in cols if x < seam]
    across = [x for x in cols if x >= seam]
    assert left, "left-of-seam marker missing — vacuous clip test"
    assert not across, f"marker NOT clipped: red at/across the seam {sorted(across)}"


def test_d4_default_marker_not_clipped(roms, runner, cam_a_ref):
    """D4 non-vacuity: in the DEFAULT ROM (no OBJ clip) the markers DO render at
    and right of the seam — proving the objclip clip is real."""
    runner.load_rom(str(roms["default"]), run_seconds=0.4)
    runner.run_frames(20)
    assert runner.read_bytes(WR, SHADOW_TMW, 1)[0] == 0x07, "default must not clip OBJ"
    seam = _seam(runner)
    w, h, pix = _grab(runner)
    cols = _red_columns(w, h, pix, 160, 200)
    assert any(x >= seam for x in cols), "default markers should render across the seam"


# --- D6 (diagonal seam) -------------------------------------------------------
def _seam_band_center(w, h, pix, y):
    """Mean X of the white seam-bar pixels on row y (None if the bar isn't there)."""
    xs = [x for x in range(w) if _is_white(pix[x, y])]
    return sum(xs) // len(xs) if xs else None


def test_d6_diagonal_seam_slants(roms, runner, cam_a_ref):
    """D6: the -DDIAGONAL ROM HDMA-drives WH0/WH2/WH3 per scanline, so the white
    seam bar SLANTS — its centre X rises monotonically down the screen."""
    runner.load_rom(str(roms["diagonal"]), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "diagonal ROM did not boot"
    runner.run_frames(20)
    w, h, pix = _grab(runner)
    ys = list(range(30, 200, 20))
    centers = [_seam_band_center(w, h, pix, y) for y in ys]
    assert all(c is not None for c in centers), f"seam bar missing on some rows: {centers}"
    # strictly increasing (the slant), by a real amount top-to-bottom
    assert all(centers[i] < centers[i + 1] for i in range(len(centers) - 1)), \
        f"seam did not slant monotonically: {list(zip(ys, centers))}"
    assert centers[-1] - centers[0] > 40, \
        f"slant too shallow to be a diagonal: {centers[0]}..{centers[-1]}"


def test_d6_straight_seam_is_vertical(roms, runner, cam_a_ref):
    """D6 non-vacuity: the DEFAULT (straight) seam's bar centre is ~CONSTANT down
    the screen — proving the diagonal slant is a real per-scanline effect, not an
    artifact of the detector."""
    runner.load_rom(str(roms["default"]), run_seconds=0.4)
    runner.run_frames(20)
    w, h, pix = _grab(runner)
    centers = [c for y in range(30, 200, 20)
               if (c := _seam_band_center(w, h, pix, y)) is not None]
    assert centers, "straight seam bar not found"
    assert max(centers) - min(centers) <= 4, \
        f"straight seam should be vertical, but centre varied: {centers}"


# --- D5 -----------------------------------------------------------------------
def test_d5_no_window_collapses_to_single_camera(roms, runner, cam_a_ref):
    """D5 non-vacuity control: -DNO_WINDOW collapses the view to ONE full-screen
    camera. The D1 two-region signature — a sharp horizon step at the seam — MUST
    be ABSENT: the horizon runs continuously across the centre (one camera)."""
    runner.load_rom(str(roms["nowin"]), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "nowin ROM did not boot"
    runner.run_frames(20)
    # window masking compiled out -> all window shadows zero
    assert runner.read_bytes(WR, SHADOW_W12SEL, 1)[0] == 0x00, "window not compiled out"
    assert runner.read_bytes(WR, SHADOW_TMW, 1)[0] == 0x00, "TMW not compiled out"

    w, h, hz = _grab_horizon(runner)
    disc = _seam_discontinuity(hz, SEAM0)
    assert disc < 6, \
        f"D5 FAILED: -DNO_WINDOW still shows a two-region seam step (disc={disc})"
