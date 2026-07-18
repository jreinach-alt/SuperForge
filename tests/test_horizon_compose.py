"""Run-gate for the glowing-horizon COMPOSITION (DoD v1.3 Addendum) — three
already-shipped kit bricks layered into one convincing scene:

  GEOMETRY   sf_bend_v SF_CURVE_HORIZON  (per-scanline BG1VOFS 1/z perspective)
  COLOR      sf_gradient_stops           (per-scanline COLDATA sky->glow->ground)
  HAZE       sf_colormath_on #1 (ADD)    (ground tints toward each row's color)

All assertions read RENDERED PIXELS from a screenshot — the HDMA tables in WRAM
are implementation detail, not evidence (kit rule #2). The proxies for
"convincing" (C-DONE a-d):

  (a) GEOMETRY INTACT — the V-bend ground still compresses toward the horizon:
      the green-band spacing varies, max:min >= 3x (reuses the v1.2 spacing
      logic on the ground region).
  (b) VERTICAL COLOR GRADIENT — the SKY rows ramp monotonically in brightness
      from the top down toward the horizon.
  (c) BRIGHT HORIZON BAND — the horizon-row region is measurably brighter than
      the rows just above AND just below it.
  (d) ATMOSPHERIC FADE — a ground band NEAR the horizon is tinted CLOSER (RGB
      distance) to the horizon color than a FOREGROUND ground band.

Plus the transient-sky-gap close: the gradient + glow band are COLDATA
(screen-fixed), so they stay at a fixed screen row while the ground rolls
beneath them (sf_bend_tick) — proven by comparing the sky/glow rows across two
frames N apart while the ground band structure shifts.

ROM contract (horizon_compose_test.sfc):
  BG1 horizontal green bands (8px on/off) under a sky region + white horizon
  line; sf_tunnel_v SF_CURVE_HORIZON amp 128 speed +2 (rolling); a 5-stop
  COLDATA gradient (dark sky -> bright warm glow at the horizon scanline ->
  ground tint); ADD color math on BG1 + backdrop.
  $7E:E010 heartbeat, $7E:E012 bend channel, $7E:E016 gradient first channel.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")

HORIZON_Y = 48          # the horizon scanline (tile row 6 * 8) — the glow stop


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


def _mid_x(img):
    return img.size[0] // 2


def _lum(px):
    return (px[0] + px[1] + px[2]) / 3.0


def _green_bits(img, x=None):
    """Down the centre column: 1 = green ground band, 0 otherwise (sky / gap /
    glow / horizon line are all 0). Green-specific so the sky stays out of the
    band-spacing measurement."""
    if x is None:
        x = _mid_x(img)
    out = []
    for y in range(img.size[1]):
        r, g, b = img.getpixel((x, y))
        out.append(1 if (g > 150 and g > b + 40 and g > r + 20) else 0)
    return out


def _band_edges(bits):
    return [y for y in range(1, len(bits)) if bits[y] == 1 and bits[y - 1] == 0]


def _ground_run(img):
    """Resolvable horizon->foreground spacing run between consecutive green-band
    top edges (mirrors test_bend_v._clean_run: stop after crossing into the wide
    foreground band so the bottom-screen wrap tail is dropped)."""
    edges = _band_edges(_green_bits(img))
    if len(edges) < 3:
        return []
    spac = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
    kept = [spac[0]]
    smallest = spac[0]
    for s in spac[1:]:
        kept.append(s)
        if s >= 6 * max(1, smallest) and len(kept) >= 3:
            break
    return kept


def _row_lum(img, y, x=None):
    if x is None:
        x = _mid_x(img)
    # average a few columns for robustness
    w = img.size[0]
    xs = [w // 4, w // 2, 3 * w // 4]
    return sum(_lum(img.getpixel((cx, y))) for cx in xs) / len(xs)


def _row_rgb(img, y):
    w = img.size[0]
    xs = [w // 4, w // 2, 3 * w // 4]
    r = sum(img.getpixel((cx, y))[0] for cx in xs) / len(xs)
    g = sum(img.getpixel((cx, y))[1] for cx in xs) / len(xs)
    b = sum(img.getpixel((cx, y))[2] for cx in xs) / len(xs)
    return (r, g, b)


def test_horizon_composition_renders_glowing_horizon(runner):
    rom = BUILD / "horizon_compose_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)

    # --- secondary: boot magic + BOTH effects allocated real, distinct channels ---
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    bend_ch = runner.read_u16(WR, 0xE012)
    grad_ch = runner.read_u16(WR, 0xE016)
    assert 3 <= grad_ch <= 7, f"gradient failed to allocate: {grad_ch:#x}"
    assert 3 <= bend_ch <= 7, f"bend failed to allocate: {bend_ch:#x}"
    # C-CHAN: no collision — gradient owns CH3-CH5, bend lands clear on CH6.
    assert grad_ch == 3, f"gradient not first-fit CH3 (got {grad_ch})"
    assert bend_ch >= grad_ch + 3, \
        f"bend channel {bend_ch} collides with gradient CH{grad_ch}-{grad_ch+2}"
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    img = _shot(runner, "horizon_compose_a.png")

    # --- (a) GEOMETRY INTACT: the V-bend ground still compresses (>=3x) --------
    run = _ground_run(img)
    assert len(run) >= 3, f"too few resolvable ground bands: run={run}"
    ratio = max(run) / min(run)
    assert ratio >= 3.0, \
        f"ground compression lost under composition: max/min spacing {ratio:.2f}x " \
        f"(need >=3x — the gradient/colormath must not clobber the V bend) run={run}"
    # most-compressed band at the horizon (top) end, expanding downward
    min_idx = run.index(min(run))
    assert min_idx < len(run) / 2, \
        f"compression INVERTED (most-compressed at index {min_idx}/{len(run)}): {run}"

    # --- (b) VERTICAL COLOR GRADIENT: the sky ramps top->horizon (monotonic) ---
    # Read the BLUE channel of the sky region: the COLDATA sky ramp is the
    # screen-fixed backdrop tint (dark navy at the top brightening toward the
    # horizon), and blue is the cleanest carrier of it — the only intruder in the
    # sky band is the compressed GREEN ground bands rolling through, which spike
    # green/luma but not blue. Bin the sky into top/mid/upper thirds (robust to a
    # band landing on any single row) and require the blue ramp to rise.
    def _band_blue(y0, y1):
        ys = range(y0, y1)
        return sum(_row_rgb(img, y)[2] for y in ys) / len(list(ys))

    sky_top = _band_blue(8, 18)            # near the top of the sky
    sky_mid = _band_blue(24, 34)
    sky_hi = _band_blue(38, HORIZON_Y - 2)  # just above the horizon
    assert sky_hi > sky_mid >= sky_top - 4, \
        f"sky blue ramp not monotonic top->horizon: top={sky_top:.0f} mid={sky_mid:.0f} " \
        f"hi={sky_hi:.0f}"
    assert sky_hi > sky_top + 15, \
        f"sky does not visibly brighten toward the horizon: top blue {sky_top:.0f} -> " \
        f"horizon blue {sky_hi:.0f}"

    # --- (c) BRIGHT HORIZON BAND: the glow region outshines above AND below ----
    # The bright COLDATA stop spreads a few rows around the horizon scanline; find
    # the brightest row in a window around it and require it to beat the rows well
    # above (mid-sky) and well below (near-horizon ground).
    band = [(y, _row_lum(img, y)) for y in range(HORIZON_Y - 4, HORIZON_Y + 20)]
    glow_y, glow_lum = max(band, key=lambda t: t[1])
    above_lum = _row_lum(img, HORIZON_Y - 18)        # mid sky
    below_lum = _row_lum(img, HORIZON_Y + 36)        # ground past the band
    assert glow_lum > above_lum + 15, \
        f"horizon band not brighter than the sky above: glow {glow_lum:.0f}@y{glow_y} " \
        f"vs above {above_lum:.0f}"
    assert glow_lum > below_lum + 15, \
        f"horizon band not brighter than the ground below: glow {glow_lum:.0f}@y{glow_y} " \
        f"vs below {below_lum:.0f}"

    # --- (d) ATMOSPHERIC FADE: near-horizon ground tints CLOSER to the horizon --
    # color than the foreground ground (RGB distance). The horizon color is the
    # glow row's color; the near band sits just below the glow, the far band deep
    # in the foreground.
    horizon_rgb = _row_rgb(img, glow_y)
    near_rgb = _row_rgb(img, HORIZON_Y + 40)         # ground near the horizon
    far_rgb = _row_rgb(img, 200)                     # foreground ground

    def _dist(a, b):
        return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5

    d_near = _dist(near_rgb, horizon_rgb)
    d_far = _dist(far_rgb, horizon_rgb)
    assert d_near < d_far, \
        f"no atmospheric fade: near-horizon ground dist {d_near:.0f} is NOT closer to " \
        f"the horizon color than the foreground dist {d_far:.0f} " \
        f"(horizon={horizon_rgb} near={near_rgb} far={far_rgb})"


def test_horizon_band_stays_fixed_while_ground_rolls(runner):
    """Closes the v1.2 transient-sky gap: the COLDATA gradient + glow band are
    SCREEN-FIXED, so they stay put while the ground rolls beneath them. Over N
    frames the GROUND band structure must shift (the V tunnel rolls) WHILE the
    sky + glow rows hold their color/brightness."""
    rom = BUILD / "horizon_compose_test.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.run_frames(6)
    img_a = _shot(runner, "horizon_fixed_a.png")
    runner.run_frames(14)
    img_b = _shot(runner, "horizon_fixed_b.png")

    # the ground IS rolling: the green-band edge pattern shifts between frames
    edges_a = _band_edges(_green_bits(img_a))
    edges_b = _band_edges(_green_bits(img_b))
    assert edges_a and edges_b, "no ground bands found"
    assert edges_a != edges_b, "ground band structure identical — the V tunnel is not rolling"

    # the GLOW BAND stays at a FIXED screen row while the ground rolls beneath it:
    # the brightest row in the horizon window must sit at (nearly) the same screen
    # y in both frames. If the band scrolled with the ground (NOT screen-fixed) its
    # screen position would march several px like the ground bands do.
    def _glow_y(img):
        window = [(y, _row_lum(img, y)) for y in range(HORIZON_Y - 6, HORIZON_Y + 22)]
        return max(window, key=lambda t: t[1])[0]

    ga, gb = _glow_y(img_a), _glow_y(img_b)
    assert abs(ga - gb) <= 4, \
        f"glow band moved with the ground ({ga} -> {gb}) — the COLDATA band is NOT " \
        f"screen-fixed (the transient-sky gap is not closed)"

    # corroborate that the ground genuinely marched (a real roll, not a still frame):
    # the median green-band edge shifted more than the glow band did.
    import statistics
    med_a = statistics.median(edges_a)
    med_b = statistics.median(edges_b)
    assert abs(med_a - med_b) >= 2, \
        f"ground did not visibly roll (median edge {med_a} -> {med_b}) — cannot " \
        f"distinguish screen-fixed from co-scrolling"
