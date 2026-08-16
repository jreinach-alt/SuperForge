"""The octagon course: its geometry, and streaming under a full lap of it.

The course is a regular-octagon ring (tools/gen_m7_assets), replacing the
circle. What that buys as a streaming stress is NOT a higher peak — measured,
both shapes already hit the theoretical maximum of 10 staged slices in a
single frame, which is what 48 px/frame on a 45-degree heading costs when
both axes cross a tile boundary together. What it changes is the DUTY CYCLE:

    longest unbroken run at >=8 slices/frame   octagon 29 frames, ring 19
    mean length of such a run                  octagon 13.3,      ring 3.5
    runs of 20+ frames per 2 laps              octagon 8,         ring 0
    staged slices per lap                      octagon 1593,      ring 1191

A circle is continuously diagonal, so it oscillates through the worst case
in short bursts. The octagon's four 45-degree sides hold the camera at the
worst case for half a second at a time, and its four axis-aligned sides drop
to the cheap 6-slices case in between. Sustained peak load is what exposes a
queue that cannot drain as fast as it fills — mode7_stream clamps at 8 slices
per frame, so a 9- or 10-slice frame defers work, and only a sustained run
says whether the deferral ever catches up.

test_streaming_survives_a_full_lap is that question, asked of the ROM.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

WR = MemoryType.SnesWorkRam
RACE = 1


@pytest.fixture(scope="module")
def gen():
    return D.load_tool("gen_m7_assets")


@pytest.fixture(scope="module")
def world(gen):
    return gen.world_map()


# --- geometry ---------------------------------------------------------------

def test_world_inc_start_agrees_with_the_generator(gen):
    """The spawn point and the map are one geometry, not two descriptions of
    it. world.inc's CAM0 is written by hand; if the generator's octagon moves
    and CAM0 does not, the car spawns off the road and every drive test
    starts from a lie."""
    tx, ty = gen.start_tile()
    assert (D.world_const("CAM0_TX"), D.world_const("CAM0_TY")) == (tx, ty)
    assert D.world_const("CAM0_PX") == tx * 8 + 4
    assert D.world_const("CAM0_PY") == ty * 8 + 4


def test_the_start_tile_is_on_the_start_finish_line(gen, world):
    tx, ty = gen.start_tile()
    assert world[ty * gen.WORLD_T + tx] == 6, \
        "the camera does not spawn on the start/finish spoke"


def test_road_width_is_uniform_on_straights_and_diagonals(gen, world):
    """The octagon norm is a NORM, so its value is perpendicular distance and
    a band has the same width everywhere. Asserted on the generated map, not
    on the formula: a road that pinches at the corners would still be an
    octagon."""
    C, W = gen.CENTER_T, gen.WORLD_T
    ROAD_TILES = gen.TRACK_TILE_IDS
    widths = {}
    for name, (ux, uy) in (("E", (1, 0)), ("NE", (1, -1)), ("N", (0, -1)),
                           ("NW", (-1, -1)), ("W", (-1, 0)), ("SW", (-1, 1)),
                           ("S", (0, 1)), ("SE", (1, 1))):
        n = math.hypot(ux, uy)
        hits = [k for k in range(gen.OCT_IN - 20, gen.OCT_OUT + 20)
                if world[(round(C + uy * k / n) & 511) * W
                         + (round(C + ux * k / n) & 511)] in ROAD_TILES]
        assert hits, f"no road along the {name} ray"
        widths[name] = max(hits) - min(hits) + 1
    assert len(set(widths.values())) == 1, \
        f"road width varies by direction: {widths}"
    assert widths["E"] == 2 * gen.OCT_HALF_W + 1, widths


def test_centre_line_is_one_cell_wide_on_every_side(gen, world):
    """The painted centre line must be ONE cell thick perpendicular to the
    road, on all eight sides.

    Each line cell paints a full stripe through itself, so two cells across
    the width put two stripes one tile apart — which renders as two parallel
    dashed lines, not one thick one. That is exactly what selecting the
    line by the norm's integer level set produced on the 45-degree sides:
    cells sit 1/sqrt(2) apart in oct_dist there, so both |dx|+|dy| = 283 and
    284 floor to 200. The axis-aligned sides were fine, which is why the
    straights always looked right.

    Measured over the WHOLE map, by the run of adjacent line cells within a
    single row and within a single column. A correct line is one cell across
    its cross-section, so:
      * a vertical line (east/west sides) has row-runs of 1, column-runs long;
      * a horizontal line (north/south sides) is the reverse;
      * a 45-degree staircase has BOTH runs of 1.
    So min(max row-run, max column-run) == 1 on every side, and the doubled
    diagonal — two cells side by side in a row — makes it 2.

    (An earlier version of this test walked the perpendicular in the (1,1)
    direction and passed on the bug: the two offending cells are adjacent in
    a ROW, so a diagonal walk visits only one of them. It was rewritten
    after failing to fail.)"""
    W, C = gen.WORLD_T, gen.CENTER_T
    sides = {"EW": set(), "NS": set(), "diag": set()}
    for y in range(W):
        base = y * W
        for x in range(W):
            if world[base + x] not in gen.LINE_TILES:
                continue
            dx, dy = x - C, y - C
            ax, ay = abs(dx), abs(dy)
            diag = ((ax + ay) * gen.INV_SQRT2_Q14) >> 14
            key = ("diag" if diag >= ax and diag >= ay
                   else "EW" if ax >= ay else "NS")
            sides[key].add((x, y))

    def longest_run(cells, key, other):
        by = {}
        for c in cells:
            by.setdefault(key(c), []).append(other(c))
        best = 0
        for vals in by.values():
            vals.sort()
            run = 1
            for a, b in zip(vals, vals[1:]):
                run = run + 1 if b == a + 1 else 1
                best = max(best, run)
            best = max(best, run)
        return best

    worst = {}
    for name, cells in sides.items():
        assert cells, f"no centre-line cells found on the {name} sides"
        rows = longest_run(cells, lambda c: c[1], lambda c: c[0])
        cols = longest_run(cells, lambda c: c[0], lambda c: c[1])
        worst[name] = min(rows, cols)
    assert set(worst.values()) == {1}, (
        f"centre line is more than one cell across its cross-section — it "
        f"renders as parallel lines there: {worst}")


def test_the_track_fills_the_map(gen, world):
    """The point of the octagon: use the world the streaming has to page."""
    W = gen.WORLD_T
    xs = [x for x in range(W)
          if any(world[y * W + x] not in (0, 1) for y in range(0, W, 4))]
    span = max(xs) - min(xs) + 1
    assert span / W > 0.80, \
        f"track spans only {span}/{W} tiles ({span / W:.0%}) of the map"


def test_the_streamed_window_never_wraps_track_onto_track(gen, world):
    """A torus world plus a course near the edges means the VRAM window at
    one side can wrap onto the opposite side, and the player sees phantom
    road on the horizon. The generator asserts the bound; this asserts the
    consequence, on the map itself: from anywhere on the road, the +/-64
    tile window must not contain a second, unconnected piece of track."""
    C, W = gen.CENTER_T, gen.WORLD_T
    east = C + gen.OCT_OUT                     # outermost point, east straight
    for wx in range(east - 64, east + 65):
        for wy in (C, C + 32, C - 32):
            if wx < W:
                continue                        # not wrapped
            assert world[(wy & 511) * W + (wx & 511)] in (0, 1), (
                f"wrapped window cell ({wx & 511},{wy & 511}) is track — the "
                f"octagon is too large for the streamed window")


# --- the streaming stress ---------------------------------------------------

@pytest.fixture(scope="module")
def raced():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    lut = D.load_tool("gen_move_lut")
    runner = MesenRunner()
    runner.boot_rom(str(SUPERFORGE / "build" / "microzero.sfc"))
    runner.wait_frames(30)
    runner.debug_break()
    D.enter_race(runner, syms)
    yield runner, syms, lut
    runner.debug_resume()
    runner.stop()


def test_streaming_survives_a_full_lap(raced, gen, world):
    """THE stress test. Drive one complete lap of the octagon at full
    throttle — all eight sides, including four sustained 45-degree runs at
    the maximum staging load — in integer lockstep with the oracle, then stop
    and compare EVERY tile of the 128x128 VRAM window against the world.

    Two failures this can catch that a cardinal-axis leg cannot:
      * staging that falls permanently behind under sustained peak load
        (the clamp defers slices; if the deferral never catches up, the
        window is stale and the mismatch is at the trailing edge);
      * a lockstep break, i.e. the loop missing a frame under the heaviest
        streaming the declared envelope can produce — which is gate
        condition 5's cadence claim, asked at the hardest point on the map.
    """
    runner, syms, lut = raced
    sim = D.sim_from_rom(runner, syms, lut)
    start_lap = sim.lap

    d_min, d_max = 10 ** 9, 0
    for i in range(1200):
        D.drive_sim(runner, sim, 1, **D.track_buttons(sim, lut))
        D.assert_matches_sim(runner, syms, sim, f"lap frame {i}")
        d = gen.oct_dist(sim.x - lut.CENTER_PX, sim.y - lut.CENTER_PX)
        d_min, d_max = min(d_min, d), max(d_max, d)
        if sim.lap > start_lap:
            break
    else:
        raise AssertionError(f"never completed a lap (lap={sim.lap})")

    # the controller kept the car on the road for the whole circuit — if it
    # had not, the streaming claim would be about driving across the grass
    assert gen.OCT_IN * 8 <= d_min and d_max <= gen.OCT_OUT * 8, (
        f"left the road during the lap: octagon distance {d_min}..{d_max} px, "
        f"road is {gen.OCT_IN * 8}..{gen.OCT_OUT * 8}")

    D.brake_to_stop(runner, syms)
    D.assert_window_exact(runner, syms, world, "after a full octagon lap")


def test_the_seam_geometry_is_declared_once(gen):
    """Everything that bakes the Mode-1/Mode-7 seam agrees with world.inc.

    world.inc owns HUD_LINES. The asset generators cannot all import it (a
    tool reaching into one game's header would invert the dependency), so
    the ones that carry their own copy are GUARDED here instead. A later review
    found two copies; there are four — the Makefile's `--lines` for the pose
    tables is the seam expressed as 224-HUD_LINES and drifts the same way.

    Failure mode this closes: move the seam in world.inc and the band tables
    and perspective head-skip follow at assembly time, while the gradient
    keeps baking a 44-line sky and the pose tables keep 180 rows — and the
    tests that carry their own copy keep agreeing with the stale value."""
    import re
    hud = D.world_const("HUD_LINES")
    total = 224

    assert D.load_tool("gen_gradient").HUD_LINES == hud, \
        "tools/gen_gradient.py's HUD_LINES has drifted from world.inc"

    mk = (SUPERFORGE / "Makefile").read_text()
    m = re.search(r"gen_pose_tables\.py --lines (\d+)", mk)
    assert m, "the Makefile no longer invokes gen_pose_tables with --lines"
    assert int(m.group(1)) == total - hud, (
        f"the Makefile builds {m.group(1)} pose rows but world.inc's seam "
        f"implies {total - hud}")
