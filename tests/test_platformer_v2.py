"""V2 look-&-feel run-gates for the platformer flagship — rendered-pixel
evidence only.

Three visible upgrades, three gates:

  PARALLAX  BG2 sky (clouds + skyline silhouette) scrolls at different rates
            from BG1 under real player input, in BOTH walk directions, and
            FREEZES (consecutive rendered frames byte-identical in the sky
            bands) when the player stands still — the user-visible invariant,
            never a ratio/variable proxy.
  GRADIENT  the dusk COLDATA ramp is on screen: backdrop rows go warm-orange
            at the top to deep blue at the bottom, monotonically.
  FADE      a scene transition (title -> game) renders a monotonic luminance
            ramp from black to full brightness.

ROM contract (templates/platformer/main.asm "v2 LOOK & FEEL" header):
  BG2 bands split at scanline 96: clouds ratio 0x20/256 = 0.125, hills
  0x60/256 = 0.375, world-X = camera X (CAMX at $52, follows the player).
  Sky pattern is 8-column (64 px) periodic, so screenshot shifts are
  unambiguous below 64 px; tilemap columns 0-1 of every 8 are empty
  ("valleys") so column x=8 reads pure backdrop for the gradient gate.
  Dusk ramp: top (r,g,b)=(24,8,2) -> bottom (2,0,12), ADD on backdrop only.
  Scene fades: 36 frames, SHADOW_INIDISP stepper.
"""
import time
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
from tests import _platformer_bot as bot

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

PX, CAMX = 0x32, 0x52
E1X, E1ALIVE = 0x42, 0x1808
SHADOW_INIDISP = 0x012E          # engine state base $0100 + ES $2E

RATIO_TOP = 0x20                 # clouds: 32/256 of camera X
RATIO_BOT = 0x60                 # hills:  96/256 of camera X
PERIOD = 64                      # sky pattern period -> shifts unambiguous <64

# Mesen screenshots are 256x239 with the 224-line picture sitting ~6 rows
# down — sample rows are SELECTED BY SIGNAL inside these candidate windows
# rather than hardcoded (game-y ranges + ~6, kept clear of sprites/HUD):
CLOUD_SCAN = range(28, 50)       # clouds: game y 24-39 (band: scanline < 96)
HILL_SCAN = range(102, 117)      # skyline game y 96-110; ghost2 sprite sits
                                 #   at game y 112-127 (screenshot ~118+)
GROUND_SCAN = range(204, 224)    # BG1 ground rows (pit gaps give structure)

CLOUD_CROP = (0, 24, 256, 86)    # freeze-invariant crops: sky bands only,
HILL_CROP = (0, 102, 256, 117)   #   excluding HUD and every sprite lane


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    # v3 save/continue persists battery SRAM across modules (process-global
    # emulator, .srm flushed at ROM unload). Baseline here is a VIRGIN cart:
    # the gradient gate samples the title screen, and a stale save would add
    # a CONTINUE text line to it. bot.virgin_srm flushes-then-deletes the
    # stale .srm (see its docstring for why the order matters). No test in
    # this module reaches game over, so no save is written mid-module.
    bot.virgin_srm(r, ROOT / "build" / "text_test.sfc")
    yield r
    r.stop()


def _rom():
    p = ROOT / "build" / "platformer.sfc"
    assert p.exists(), f"{p} not built — run `make platformer` first"
    return str(p)


def _shot(r, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    r.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


def _row_bits(img, y, pred):
    return [1 if pred(img.getpixel((x, y))) else 0 for x in range(256)]


def _is_cloud(p):                # SKY_CLOUD $525C: pinkish — blue+green high
    return p[1] > 100 and p[2] > 100


def _is_silhouette(p):           # SKY_SILH $2846: dark purple — blue beats red
    return p[2] > p[0] and p[2] > 40


def _is_ground(p):               # BG_BROWN $11B7: warm brown — red dominant
    return p[0] > 120 and p[0] > p[2]


def _pick_rows(img, scan, pred, n=2, min_px=30):
    """Select n sample rows with strong pattern signal in the baseline shot
    (self-calibrates the screenshot's vertical padding offset)."""
    rows = [y for y in scan if sum(_row_bits(img, y, pred)) >= min_px]
    assert len(rows) >= n, \
        f"only {len(rows)} rows with pattern signal in scan {scan}"
    return rows[:: max(1, len(rows) // n)][:n]


def _band_shift(img_a, img_b, y, pred):
    """Leftward pixel shift of the pattern at row y between two screenshots
    (content shifts left as HOFS grows). Best s in 0..PERIOD-1 such that
    b[x] == a[(x+s) % 256]; returns (shift, mismatch_count)."""
    a, b = _row_bits(img_a, y, pred), _row_bits(img_b, y, pred)
    assert sum(a) > 10, f"no pattern signal at row {y}"
    best = None
    for s in range(PERIOD):
        m = sum(1 for x in range(256) if b[x] != a[(x + s) % 256])
        if best is None or m < best[1]:
            best = (s, m)
    return best


def _start_game(r):
    r.set_input(0, start=True)
    r.run_frames(4)
    r.set_input(0)
    r.run_frames(60)             # past the 36-frame scene fade-in


def _stomp_ground_ghost(r, tmo=30):
    """Stomp ghost1 to clear the ground lane (so the camera walk can't be
    interrupted by a hurt-respawn). Ghost1 now turns back at GHOST1_MIN_X=64, so
    the player must approach it in its lane: walk toward it and hop when near, so
    the fall makes head contact (a stomp) rather than a side hit."""
    t0 = time.time()
    while r.read_u16(WR, E1ALIVE) == 1 and time.time() - t0 < tmo:
        d = r.read_u16(WR, E1X) - r.read_u16(WR, PX)
        if abs(d) < 28:
            r.set_input(0, a=True)
            r.run_frames(8)
            r.set_input(0)
            r.run_frames(30)
        elif d > 0:
            r.set_input(0, right=True)
            r.run_frames(4)
            r.set_input(0)
        else:
            r.set_input(0, left=True)
            r.run_frames(4)
            r.set_input(0)
    return r.read_u16(WR, E1ALIVE) == 0


def _settled_cam_shot(r, name):
    """Release input, let physics + camera settle, return (cam_x, shot)."""
    r.set_input(0)
    r.run_frames(8)
    cam = r.read_u16(WR, CAMX)
    img = _shot(r, name)
    assert r.read_u16(WR, CAMX) == cam, "camera moved during the screenshot"
    return cam, img


def test_parallax_two_rates_both_directions_and_freeze(runner):
    runner.load_rom(_rom(), run_seconds=1.2)
    _start_game(runner)
    assert _stomp_ground_ghost(runner), "could not clear ghost1 off the lane"
    bot.walk_to(runner, 30)                  # camera hard-left baseline
    cam0, img0 = _settled_cam_shot(runner, "platformer_v2_plx_cam0.png")
    assert cam0 == 0, f"baseline camera not at 0: {cam0}"

    # --- walk RIGHT: camera advances; BG2 bands shift at their ratios ---
    bot.walk_to(runner, 160)                 # ground lane, west of pit 1
    cam1, img1 = _settled_cam_shot(runner, "platformer_v2_plx_cam1.png")
    assert cam1 > 16, f"camera did not move: {cam1}"

    exp_cloud = ((cam1 * RATIO_TOP) >> 8) - ((cam0 * RATIO_TOP) >> 8)
    exp_hill = ((cam1 * RATIO_BOT) >> 8) - ((cam0 * RATIO_BOT) >> 8)
    exp_bg1 = cam1 - cam0
    # the three rates must be pairwise distinct for the assertion to mean
    # anything (guaranteed for cam1 in 17..63 with ratios 0.125/0.375)
    assert len({exp_cloud, exp_hill, exp_bg1 % PERIOD}) == 3

    cloud_rows = _pick_rows(img0, CLOUD_SCAN, _is_cloud)
    hill_rows = _pick_rows(img0, HILL_SCAN, _is_silhouette)
    ground_rows = _pick_rows(img0, GROUND_SCAN, _is_ground, n=1, min_px=100)

    for y in cloud_rows:
        s, m = _band_shift(img0, img1, y, _is_cloud)
        assert m <= 6, f"cloud row {y}: no clean shift (mismatch {m})"
        assert s == exp_cloud, \
            f"cloud row {y}: shift {s} != cam*{RATIO_TOP}/256 = {exp_cloud} (cam {cam0}->{cam1})"
    for y in hill_rows:
        s, m = _band_shift(img0, img1, y, _is_silhouette)
        assert m <= 6, f"hill row {y}: no clean shift (mismatch {m})"
        assert s == exp_hill, \
            f"hill row {y}: shift {s} != cam*{RATIO_BOT}/256 = {exp_hill} (cam {cam0}->{cam1})"
    # BG1 moves at the full camera rate — different from BOTH sky bands
    s, m = _band_shift(img0, img1, ground_rows[0], _is_ground)
    assert m <= 6, f"ground row: no clean shift (mismatch {m})"
    assert s == exp_bg1 % PERIOD, \
        f"ground shift {s} != camera delta {exp_bg1}"

    # --- FREEZE: standing still => sky pixels byte-identical across frames
    # (the per-frame sf_parallax_tick keeps rebuilding the HOFS table; with
    # the camera unchanged the rendered sky must not move a pixel) ---
    f1 = _shot(runner, "platformer_v2_plx_freeze_a.png")
    runner.run_frames(3)
    f2 = _shot(runner, "platformer_v2_plx_freeze_b.png")
    runner.run_frames(7)
    f3 = _shot(runner, "platformer_v2_plx_freeze_c.png")
    for crop, label in ((CLOUD_CROP, "cloud band"), (HILL_CROP, "hill band")):
        a, b, c = (f.crop(crop).tobytes() for f in (f1, f2, f3))
        assert a == b, f"{label} moved while the player stood still"
        assert a == c, f"{label} drifted across 10 standstill frames"

    # --- walk LEFT back: the shifts reverse (full direction cycle) ---
    bot.walk_to(runner, 30)
    cam2, img2 = _settled_cam_shot(runner, "platformer_v2_plx_cam2.png")
    assert cam2 == cam0, f"camera did not return to baseline: {cam2}"
    for y, pred in ((cloud_rows[0], _is_cloud), (hill_rows[0], _is_silhouette)):
        s, m = _band_shift(img0, img2, y, pred)
        assert m <= 6 and s == 0, \
            f"row {y}: sky did not return after walking left (shift {s}, mismatch {m})"


def test_gradient_dusk_ramp_on_backdrop(runner):
    runner.load_rom(_rom(), run_seconds=1.2)   # title: fade-in complete
    img = _shot(runner, "platformer_v2_gradient_title.png")
    # column x=8 is a sky-pattern valley (tilemap columns 0-1 empty at
    # HOFS 0) — pure backdrop top to bottom; rows avoid the title text
    xs = (6, 8, 10)
    ys = (30, 70, 110, 200)
    samples = []
    for y in ys:
        px = [img.getpixel((x, y)) for x in xs]
        samples.append(tuple(sum(c[i] for c in px) // len(px) for i in range(3)))
    reds = [s[0] for s in samples]
    blues = [s[2] for s in samples]
    assert all(reds[i] > reds[i + 1] for i in range(len(reds) - 1)), \
        f"red not falling down the frame: {samples} at rows {ys}"
    assert all(blues[i] < blues[i + 1] for i in range(len(blues) - 1)), \
        f"blue not rising down the frame: {samples} at rows {ys}"
    # the configured direction: warm top, cool bottom
    assert reds[0] > blues[0] + 30, f"top row not warm: {samples[0]}"
    assert blues[-1] > reds[-1] + 30, f"bottom row not cool: {samples[-1]}"


def test_fade_in_renders_monotonic_luminance_ramp(runner):
    runner.load_rom(_rom(), run_seconds=1.2)   # title settled, full bright

    def lum(img):
        g = img.convert("L")
        d = g.tobytes()
        return sum(d) / len(d)

    # title -> game: the scene init cuts to black (the level rebuilds dark),
    # then arms a 36-frame fade-in. Sample every 5 frames across the window;
    # the early samples land in the black hold, the middle ones on the ramp.
    runner.set_input(0, start=True)
    runner.run_frames(2)
    runner.set_input(0)
    ramp = []
    for i in range(10):
        runner.run_frames(5)
        ramp.append(lum(_shot(runner, f"platformer_v2_fade_{i}.png")))
    runner.run_frames(40)                      # fade done, scene settled
    final = lum(_shot(runner, "platformer_v2_fade_final.png"))
    assert runner.read_bytes(WR, SHADOW_INIDISP, 1)[0] == 0x0F, \
        "fade did not land on full brightness"

    assert ramp[0] < final * 0.4, f"scene entry never went dark: {ramp} vs {final}"
    # the whole sampled ramp is monotonic non-decreasing (small epsilon for
    # sprite/HUD churn), with >= 3 strictly-increasing points on the climb
    assert all(b >= a - 1.0 for a, b in zip(ramp, ramp[1:])), \
        f"luminance ramp not monotonic: {ramp}"
    climb = [v for v in ramp if ramp[0] + 1.0 < v < final - 1.0]
    assert len(climb) >= 3, f"fewer than 3 mid-ramp samples: {ramp} (final {final})"
    assert all(b > a for a, b in zip(climb, climb[1:])), \
        f"mid-ramp samples not strictly increasing: {climb}"
    assert ramp[-1] <= final * 1.05, f"ramp overshot the settled frame: {ramp} vs {final}"
    assert final > ramp[0] * 2, \
        f"fade-in start not meaningfully darker than the settled frame: {ramp[0]} vs {final}"
