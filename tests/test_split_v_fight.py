"""split_v_fight — SEAMLESS distance-driven fighting-game split.

Proves the split is genuinely SEAMLESS on the cycle-accurate emulator by reading
the RENDERED framebuffer (kit rule #2). Every assertion is on pixels — except the
arena-clamp regression, which reads the fighter world-X the clamp bounds.

The seamless model: the centre window is ALWAYS on; separation is a CONTINUOUS
camera divergence eased from fighter distance (`cam_a = mid - spread`,
`cam_b = mid + spread`). At spread=0 the two halves are pixel-identical, so the
ever-present seam is invisible; the beveled BG3 divider ramps its width from ZERO.
Static `-DHOLD=n` builds freeze the swept variable so every framebuffer assertion
is race-free (freeze the swept variable — no capture-timing race):

  hold_merge (-DHOLD=20)      : fighters close, spread settles at 0  -> MERGED
  hold_split (-DHOLD=100)     : fighters far,   spread settles at 36 -> SPLIT
  nowin (-DNOWIN=1 -DHOLD=20) : the no-split REFERENCE (window off, BG3 off the
                                main screen; one camera, no divider)

  S1 seamless merge  : the MERGED frame is pixel-identical to the no-split
                       reference (near-0 diff) — the split adds NOTHING at merge.
                       Non-vacuity: the SPLIT frame differs from the reference by
                       thousands of pixels, so the metric is not trivially zero.
  S2 bar ramps       : the beveled divider is ABSENT at merge (0 white-core px)
                       and PRESENT + full-height when split (many white-core px).
  S3 fighters halves : split -> red fighter in the left half, blue in the right;
                       merge -> both fighters on screen (near centre).
  S4 dynamic (auto)  : over the self-running cross-over the view reaches BOTH a
                       merged frame (divider gone) and a split frame (divider
                       present), the divider stays BOUNDED, and it re-merges after
                       the peak — the seamless separate/merge animates.
  S5 arena bounds    : both fighters driven the same way stay in the arena — the
                       independent clamp (regression for the F-1 clamp-escape).
  S6 side-swap (static): a CROSSED build frames correctly — the leftmost fighter
                       (blue) in the left half, rightmost (red) in the right, both
                       framing the seam; the split follows a side-switch.
  S7 side-swap (dynamic): the autodemo marches the fighters THROUGH each other —
                       red is seen in both halves and the crossing is a seamless
                       merge (divider collapses to ~0 as they pass).
"""
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam

FX1 = 0x0040            # DP $40: fighter 1 world-x (16-bit)
FX2 = 0x0042            # DP $42: fighter 2 world-x (16-bit)
ARENA_LO = 24           # left wall  (must match main.asm)
ARENA_HI = 232          # right wall
Y_TOP = 14              # skip the top overscan rows
CENTRE = 128
SETTLE = 110            # frames for the eased spread to reach its fixed point

# Merge must be pixel-identical to the no-split reference. The static builds diff
# to exactly 0 in practice (verified deterministic across fresh power-on seeds and
# by an independent audit); a tiny slack tolerates any emulator noise while still
# proving seamlessness — the SPLIT frame differs from the same reference by ~11000.
SEAM_DIFF_MAX = 8


def _u16(runner, addr):
    b = runner.read_bytes(WR, addr, 2)
    return b[0] | (b[1] << 8)


# --- pixel predicates -------------------------------------------------------
def _is_white(p):  return p[0] > 230 and p[1] > 230 and p[2] > 230   # bevel highlight core
def _is_red(p):    return p[0] > 150 and p[1] < 80 and p[2] < 80
def _is_blue(p):   return p[2] > 150 and p[0] < 80 and p[1] < 80


def _grab(runner, rom, frames=SETTLE, name="split_v_fight"):
    runner.load_rom(str(rom), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", f"{rom} did not boot"
    runner.run_frames(frames)
    Path("/tmp/e2e_screenshots").mkdir(parents=True, exist_ok=True)
    path = f"/tmp/e2e_screenshots/{name}.png"
    runner.take_screenshot(path)
    return Image.open(path).convert("RGB")


def _frame_diff(a, b):
    pa, pb = a.load(), b.load()
    w, h = a.size
    return sum(1 for y in range(h) for x in range(w) if pa[x, y] != pb[x, y])


def _bar_core(img):
    """White-core divider pixels in the centre band [118,138) — the beveled bar's
    highlight tile ($7FFF). 0 at merge (divider absent), many when split."""
    px = img.load()
    w, h = img.size
    return sum(1 for y in range(Y_TOP, h - 8) for x in range(118, 138) if _is_white(px[x, y]))


def _bar_span(img):
    """(min_y, max_y) of the white-core divider — proves the bar is FULL height
    (the VBlank-DMA-truncation landmine cut the bar's bottom rows)."""
    px = img.load()
    w, h = img.size
    ys = [y for y in range(Y_TOP, h - 8) for x in range(118, 138) if _is_white(px[x, y])]
    return (min(ys), max(ys)) if ys else (None, None)


def _mean_x(img, pred):
    px = img.load()
    w, h = img.size
    xs = [x for y in range(Y_TOP, h - 8) for x in range(w) if pred(px[x, y])]
    return sum(xs) / len(xs) if xs else None


# --- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def roms():
    make = subprocess.run(["make", "split_v_fight"], cwd=str(ROOT),
                          capture_output=True, text=True)
    if make.returncode != 0:
        pytest.skip(f"`make split_v_fight` failed (toolchain?):\n{make.stderr}")
    script = ROOT / "templates" / "split_v_fight" / "build_split_v_fight.sh"
    var = subprocess.run(["bash", str(script)], cwd=str(ROOT),
                         capture_output=True, text=True)
    if var.returncode != 0:
        pytest.skip(f"variant build failed:\n{var.stderr}")
    return {
        "default":   BUILD / "split_v_fight.sfc",
        "autodemo":  BUILD / "split_v_fight_autodemo.sfc",
        "merge":     BUILD / "split_v_fight_hold_merge.sfc",
        "split":     BUILD / "split_v_fight_hold_split.sfc",
        "nowin":     BUILD / "split_v_fight_nowin.sfc",
        "cross":     BUILD / "split_v_fight_cross.sfc",
    }


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


# --- S1: the merge is SEAMLESS ---------------------------------------------
def test_s1_merge_is_seamless(roms, runner):
    """The MERGED frame is pixel-identical to a no-split single-camera reference:
    turning the split ON at spread=0 changes NOTHING on screen. Non-vacuity: the
    SPLIT frame differs from the same reference by thousands of pixels."""
    ref = _grab(runner, roms["nowin"], name="fight_nowin")
    merge = _grab(runner, roms["merge"], name="fight_merge")
    split = _grab(runner, roms["split"], name="fight_split")

    d_merge = _frame_diff(merge, ref)
    d_split = _frame_diff(split, ref)
    assert d_merge <= SEAM_DIFF_MAX, \
        f"merge not seamless: {d_merge} px differ from the no-split reference"
    assert d_split > 2000, \
        f"non-vacuity failed: SPLIT frame should differ from the reference, got {d_split}"


# --- S2: the divider bar ramps from ZERO -----------------------------------
def test_s2_bar_ramps_from_zero(roms, runner):
    """The beveled divider is ABSENT at merge (zero-width -> no white core) and
    PRESENT + full-height when split."""
    merge = _grab(runner, roms["merge"], name="fight_merge")
    split = _grab(runner, roms["split"], name="fight_split")

    core_merge = _bar_core(merge)
    core_split = _bar_core(split)
    assert core_merge == 0, f"divider must be invisible at merge, saw {core_merge} core px"
    assert core_split > 600, f"divider should be visible when split, saw {core_split} core px"

    # full height: the white core must span nearly the whole visible field (the
    # VBlank multi-tilemap DMA truncation used to cut the bar's bottom rows)
    ymin, ymax = _bar_span(split)
    assert ymin is not None and ymin <= Y_TOP + 12, f"divider top missing (ymin={ymin})"
    assert ymax >= 220, f"divider bottom truncated (ymax={ymax})"


# --- S3: fighters track their own halves -----------------------------------
def test_s3_fighters_track_halves(roms, runner):
    """Split -> red in the left half, blue in the right half. Merge -> both
    fighters present on screen (near centre)."""
    split = _grab(runner, roms["split"], name="fight_split")
    red = _mean_x(split, _is_red)
    blue = _mean_x(split, _is_blue)
    assert red is not None and blue is not None, "a fighter is missing (split)"
    assert red < CENTRE < blue, \
        f"fighters not in opposite halves (red={red:.0f}, blue={blue:.0f})"

    merge = _grab(runner, roms["merge"], name="fight_merge")
    assert _mean_x(merge, _is_red) is not None, "red fighter missing (merged)"
    assert _mean_x(merge, _is_blue) is not None, "blue fighter missing (merged)"


# --- S4: the seamless separate/merge animates ------------------------------
def test_s4_autodemo_reaches_merge_and_split(roms, runner):
    """Over the self-running ping-pong the divider both VANISHES (a seamless
    merged frame) and APPEARS (a split frame) — the continuous eased spread
    drives the whole range, not a binary toggle — AND it re-merges seamlessly
    AFTER separating (not just at the start), with the divider width BOUNDED to
    its design maximum (a regression for the ease-down underflow that ballooned
    the divider on re-merge)."""
    runner.load_rom(str(roms["autodemo"]), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "autodemo did not boot"
    runner.run_frames(20)
    cores = []
    for _ in range(130):                      # ~390 frames spans a full wall-to-close
        runner.run_frames(3)                  # ping-pong incl. the dwell at each extreme
        runner.take_screenshot("/tmp/e2e_screenshots/fight_auto.png")
        img = Image.open("/tmp/e2e_screenshots/fight_auto.png").convert("RGB")
        cores.append(_bar_core(img))
    assert min(cores) <= 20, f"never reached a merged (divider-free) frame; min core={min(cores)}"
    assert max(cores) > 600, f"never reached a split (divider-present) frame; max core={max(cores)}"
    # bounded width: the band half-width is hw = spread>>4 with spread <= SPREAD_MAX
    # (48) -> hw <= 3 -> a ~7 px reveal; a full 20 px sample band going white means
    # `spread` blew past its clamp (the ease-down underflow). Cap well under that.
    assert max(cores) < 2000, f"divider ballooned past its design max (core={max(cores)})"
    # seamless RE-merge: after the first split, the divider must return to ~0
    peak = cores.index(max(cores))
    assert min(cores[peak:]) <= 20, \
        f"view never re-merged after splitting (min core after peak={min(cores[peak:])})"


# --- S5: fighters stay in the arena under adversarial input (F-1 regression) -
def test_s5_both_left_stays_in_arena(roms, runner):
    """Driving BOTH fighters LEFT must NOT walk either off the arena — the
    INDEPENDENT clamp bounds each fighter to [ARENA_LO, ARENA_HI] with no
    reference to the other (regression for the F-1 escape where FX1 marched to
    -272; independent bounds make that escape impossible by construction)."""
    runner.load_rom(str(roms["default"]), run_seconds=0.4)
    runner.run_frames(10)

    runner.set_input(0, left=True)
    runner.set_input(1, left=True)
    runner.run_frames(200)
    runner.set_input(0)
    runner.set_input(1)

    fx1 = _u16(runner, FX1)
    fx2 = _u16(runner, FX2)
    assert ARENA_LO <= fx1 <= ARENA_HI, f"FX1 escaped the arena: {fx1}"
    assert ARENA_LO <= fx2 <= ARENA_HI, f"FX2 escaped the arena: {fx2}"


# --- S6: a crossed / swapped state renders correctly (side-swap support) ----
def test_s6_crossed_state_frames_correctly(roms, runner):
    """When the fighters SWITCH SIDES (FX1 to the right of FX2), the split must
    FOLLOW: the leftmost fighter by world-X (blue here) frames the LEFT half and
    the rightmost (red) the RIGHT half — a mirror of the normal split, colours
    swapped, both framing the seam (NOT stranded at the outer screen edges). The
    divider is still present + full-height."""
    crossed = _grab(runner, roms["cross"], name="fight_cross")   # -DHOLD=-100
    red = _mean_x(crossed, _is_red)
    blue = _mean_x(crossed, _is_blue)
    assert red is not None and blue is not None, "a fighter is missing (crossed)"
    # swapped: blue (world-left) now in the LEFT half, red (world-right) in the RIGHT
    assert blue < CENTRE < red, \
        f"crossed split did not follow the swap (blue={blue:.0f}, red={red:.0f})"
    # framing correct (not stranded at the edges): each fighter sits toward its
    # half's inner region, mirroring the normal split (~68 / ~196), not ~11 / ~251
    assert 40 < blue < CENTRE and CENTRE < red < 216, \
        f"crossed fighters stranded at the outer edges (blue={blue:.0f}, red={red:.0f})"
    # divider still full and present (the swap doesn't break the seamless split)
    assert _bar_core(crossed) > 600, "divider missing in the crossed split"
    ymin, ymax = _bar_span(crossed)
    assert ymin is not None and ymin <= Y_TOP + 12 and ymax >= 220, \
        f"crossed divider not full-height (span {ymin}..{ymax})"

    # contrast vs the NORMAL split: red and blue are on OPPOSITE sides between the
    # two builds (proves the assertion is not vacuous / hard-coded to one layout)
    normal = _grab(runner, roms["split"], name="fight_split")
    assert _mean_x(normal, _is_red) < CENTRE < _mean_x(normal, _is_blue), \
        "normal split sanity: red should be left, blue right"


# --- S7: the autodemo cross-over swaps sides seamlessly ---------------------
def test_s7_autodemo_swaps_sides(roms, runner):
    """The self-running demo marches the fighters THROUGH each other: red must be
    seen in BOTH halves over the cycle (it crosses from the left half to the
    right), and the crossing itself is a seamless MERGE (the divider collapses to
    ~0 as they pass) — the split follows a live side-switch."""
    runner.load_rom(str(roms["autodemo"]), run_seconds=0.4)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "autodemo did not boot"
    runner.run_frames(20)
    red_seen_left = red_seen_right = False
    min_core_when_close = 10_000
    for _ in range(130):                          # spans a full cross-and-return
        runner.run_frames(3)
        runner.take_screenshot("/tmp/e2e_screenshots/fight_swap.png")
        img = Image.open("/tmp/e2e_screenshots/fight_swap.png").convert("RGB")
        rx = _mean_x(img, _is_red)
        if rx is not None and rx < CENTRE - 20:
            red_seen_left = True
        if rx is not None and rx > CENTRE + 20:
            red_seen_right = True
        # near the crossing the two reds/blues overlap in x; track the divider there
        red = _mean_x(img, _is_red)
        blue = _mean_x(img, _is_blue)
        if red is not None and blue is not None and abs(red - blue) < 24:
            min_core_when_close = min(min_core_when_close, _bar_core(img))
    assert red_seen_left, "red never appeared in the left half"
    assert red_seen_right, "red never appeared in the right half (never crossed over)"
    assert min_core_when_close <= 20, \
        f"the crossover was not a seamless merge (divider core near crossing={min_core_when_close})"
