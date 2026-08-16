"""CPU cycles/frame for the worst case, plus the Mode 7 streaming step cost,
measured cycle-accurately on `probe_cpu` — an instrumented build of a complete
Mode 7 driving scene, assembled from the frozen sources in `vendor/probe_ref/`
(see `vendor/probes/make_probe_cpu.py`). These are the numbers the allocator's
substrate pins are derived from, which is why they are MEASURED on a full
frame's worth of work rather than estimated from a synthetic loop.

Instrument: SLHV-latched (V,H) rings around the game-loop work window and the
NMI handler, converted host-side at 1 line = 1364 mc, 1 dot = 4 mc — ~4 mc
resolution, zero in-ROM arithmetic.

Determinism: scenario timing is FRAME-anchored, never wall-clock. After
a minimal wall-clock boot the runner parks at a frame boundary (debug_break)
and single-steps to a fixed game-loop frame (DBG_FRAMES == ANCHOR_FRAME);
from there every scenario is driven by exact frame counts with latched input
(frame_step), so every run measures the same emulated trajectory.

The pin is the MAX over PIN_PASSES measurement passes of the ladder's
winning rung, each pass a FULL re-boot + re-anchor + replay of the ladder
prefix up to that rung — three independent boots (each parking at a
different wall-clock frame) must land on the same worst-frame number, which
is exactly the reproducibility the old wall-clock method lacked. The passes
must agree within PASS_AGREE_TOL of each other (in practice they are
bit-identical); per-pass values + spread are recorded in
build/measurements_cpu.json. (Sequential same-session windows were tried
first and genuinely differ by up to ~30% — the worst-frame maximum is
position-phase-dependent — so agreement is defined over replayed
trajectories, not over different segments of one drive.)

Scenarios (driven live via frame_step input latching):
  steady   B held, straight line at max speed — the engine's steady state:
           streaming + sprites + HUD + HDMA re-arm, perspective PPU-applied
           with NO pose change. This is the number the substrate pins:
           perspective stays LUT/PPU-offloaded, so the sustained worst case
           must fit one frame.
  diagonal steer to ~45 deg then straight — max row+col stream churn with no
           rebuild; the worst steady stream mix.
  turning  B+LEFT held — a camera-pose change EVERY pose frame forces the
           scene's full software pv_rebuild. Measured here: the rebuild frame
           exceeds one frame and pose cadence drops while the PPU keeps
           rendering 60 fps. That is the naive path a rebuild must avoid
           (docs/01) — recorded as the amortization input, NOT the pin. The
           per-frame DBG_REBUILD flag is asserted over a WINDOW of consecutive
           turning frames, not a single sample.

Writes build/measurements_cpu.json for allocator/pin_budgets consumption.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

WR = MemoryType.SnesWorkRam
FRAME_MC = 357368
LINE_MC, DOT_MC = 1364, 4

# instrument map (fixed by the derivation script; see make_probe_cpu.py)
CY_WORK_IDX, CY_NMI_IDX = 0xE7F0, 0xE7F1
CY_WORK_RING, CY_NMI_RING = 0xE800, 0xF000
DBG_FRAMES, DBG_VEL, DBG_ANGLE, DBG_REBUILD = 0xE00C, 0xE034, 0xE004, 0xE018

ANCHOR_FRAME = 240        # the fixed game-loop frame every run measures from
PIN_PASSES = 3            # full re-boot/re-anchor passes of the winning rung
PASS_AGREE_TOL = 0.05     # the passes must agree within 5% of each other
PIN_WINDOW = 480          # frames of winning-rung cruise per pass — long
                          # enough to sweep the position-phase alignments
                          # whose worst frame the 120-frame ladder windows
                          # can miss (the worst is phase-dependent)
REBUILD_WINDOW = 12       # consecutive turning frames sampled for DBG_REBUILD
REBUILD_MIN_FIRE = 0.8    # ...of which at least 80% must show rebuild-ran


def _mc(v: int, h: int) -> int:
    return v * LINE_MC + h * DOT_MC


def _ring_deltas(runner, ring_base: int, idx_addr: int, count: int) -> list[int]:
    """Decode the last `count` (start,end) latch pairs into mc durations."""
    idx = runner.read_byte(WR, idx_addr)
    out = []
    for k in range(count):
        i = (idx - 1 - k) % 256
        b = runner.read_bytes(WR, ring_base + i * 8, 8)
        sh, sv = b[0] | (b[1] << 8), b[2] | (b[3] << 8)
        eh, ev = b[4] | (b[5] << 8), b[6] | (b[7] << 8)
        if max(sv, ev) >= 262 or max(sh, eh) >= 341:
            continue                          # unwritten/torn slot
        out.append((_mc(ev, eh) - _mc(sv, sh)) % FRAME_MC)
    return out


@pytest.fixture(scope="module")
def runner():
    # the Makefile is the single source of truth for both probe recipes
    r = subprocess.run(["make", "build/probe_cpu.sfc",
                        "build/probe_cpu_step.sfc"],
                       cwd=SUPERFORGE, capture_output=True, text=True)
    assert r.returncode == 0, (
        f"probe build failed:\n{r.stdout}\n{r.stderr}\n"
        "NOTE: this probe is an instrumented build of the Mode 7 scene whose "
        "sources are VENDORED under vendor/probe_ref/ (see that directory's "
        "README) — nothing outside this repo is involved. If the error above "
        "is a missing include or incbin, one of those files has been deleted "
        "or moved; restore it with `git checkout -- vendor/probe_ref/` rather "
        "than hunting a sibling checkout. Note the two shapes are not "
        "interchangeable: .include resolves flat off vendor/probe_ref/inc, "
        ".incbin keeps its assets/racing/ prefix under --bin-include-dir.")
    m = MesenRunner()
    yield m
    m.stop()


def _boot_to_anchor(runner, sfc: Path):
    """Bounded boot, then frame-step to the fixed anchor frame.

    The boot is 30 EMULATED frames (it was 0.5 wall seconds, which buys a
    different amount of boot on a loaded box and a different amount again
    once the speed throttle is lifted); stepping to
    DBG_FRAMES == ANCHOR_FRAME erases the remaining variance, so every run
    proceeds from the identical power-on trajectory state.
    """
    runner.boot_rom(str(sfc), frames=30)
    runner.debug_break()
    for _ in range(600):                       # wait for ROM init if parked early
        if runner.read_bytes(WR, 0xE000, 4) == b"SFDB":
            break
        runner.frame_step(1)
    else:
        raise AssertionError("probe never initialized (no SFDB magic)")
    f = runner.read_u16(WR, DBG_FRAMES)
    assert f < ANCHOR_FRAME - 8, (
        f"boot overran the anchor (DBG_FRAMES={f}); raise ANCHOR_FRAME "
        f"or shorten the boot frame budget")
    # chunk to just short of the anchor (the parked demo holds 60 fps, so
    # loop iterations track frames 1:1), then single-step exactly onto it
    while runner.read_u16(WR, DBG_FRAMES) < ANCHOR_FRAME - 4:
        runner.frame_step(ANCHOR_FRAME - 4 - runner.read_u16(WR, DBG_FRAMES))
    guard = 0
    while runner.read_u16(WR, DBG_FRAMES) < ANCHOR_FRAME and guard < 32:
        runner.frame_step(1)
        guard += 1
    got = runner.read_u16(WR, DBG_FRAMES)
    assert got == ANCHOR_FRAME, f"anchor missed: DBG_FRAMES={got}"


def _cadence_window(runner, frames: int,
                    **buttons) -> tuple[int, list[int], list[int]]:
    """Advance EXACTLY `frames` with latched input; return (loop iterations,
    work mc list, nmi mc list) for the window."""
    f1 = runner.read_u16(WR, DBG_FRAMES)
    runner.frame_step(frames, **buttons)
    iters = (runner.read_u16(WR, DBG_FRAMES) - f1) % 65536
    # parked at the frame boundary the rings are coherent (no torn slots),
    # so read EVERY completed pair of the window — the old free-running
    # 2-entry safety margin silently dropped frames from the max
    n = max(2, min(iters, 110))
    return (iters, _ring_deltas(runner, CY_WORK_RING, CY_WORK_IDX, n),
            _ring_deltas(runner, CY_NMI_RING, CY_NMI_IDX, n))


def _hold_speed(runner, target: int,
                frames: int) -> tuple[int, list[int], list[int]]:
    """Bang-bang throttle to hold DBG_VEL near target, then measure. All
    decisions read parked (deterministic) state — the trajectory is a pure
    function of the anchor."""
    for _ in range(60):                       # reach the band first
        v = runner.read_u16(WR, DBG_VEL)
        if v >= target:
            break
        runner.frame_step(10, b=True)
    got_i, got_w, got_n = 0, [], []
    for _ in range(frames // 10):
        v = runner.read_u16(WR, DBG_VEL)
        i, w, nm = _cadence_window(runner, 10, b=(v < target))
        got_i += i
        got_w += w
        got_n += nm
    return got_i, got_w, got_n


def _pin_pass(runner, sfc: Path, ladder_prefix: list[int]) -> dict:
    """One full measurement pass of the winning rung: re-boot, re-anchor,
    replay the ladder prefix (approach from below exactly as the ladder
    did), measure the final rung. Three of these from three different
    wall-clock park points must agree — that IS the reproducibility."""
    _boot_to_anchor(runner, sfc)
    for t in ladder_prefix[:-1]:
        _hold_speed(runner, t, 120)           # replay, discard
    i, w, nm = _hold_speed(runner, ladder_prefix[-1], PIN_WINDOW)
    assert i >= PIN_WINDOW - 8, (
        f"pin pass broke 60 fps cadence: {i}/{PIN_WINDOW}")
    return {"iters": i, "window_frames": PIN_WINDOW, "work_mc_max": max(w),
            "nmi_mc_max": max(nm), "total_mc": max(w) + max(nm)}


RESULTS = {}


def test_scenarios_on_plain_probe(runner, tmp_path):
    # the plain probe (built by the module fixture via make — the Makefile
    # owns the recipe); scenarios are driven live via frame_step latching
    sfc = SUPERFORGE / "build" / "probe_cpu.sfc"
    try:
        _run_scenarios(runner, sfc)
    finally:
        runner.debug_resume()                  # hand back a live emulator


def _run_scenarios(runner, sfc: Path):
    _boot_to_anchor(runner, sfc)

    # ---- parked baseline (60 fps trivially) ----
    iters, work, nmi = _cadence_window(runner, 120)
    assert iters >= 118, f"parked cadence broken: {iters}/120"
    RESULTS["parked"] = {"work_mc_max": max(work), "nmi_mc_max": max(nmi),
                         "cadence": f"{iters}/120"}

    # ---- speed ladder: find the fastest cruise that HOLDS 60 fps ----
    # (ground truth: the UNPATCHED reference's loop drops to ~30 Hz and below
    # as speed rises — the ~68.6k-mc/row staging kernel dominates. The pin is
    # the worst case that holds cadence; the broken rungs are recorded as the
    # speed envelope the design's optimized staging kernel must beat.)
    ladder = {}
    rungs = (0x0400, 0x0800, 0x0C00, 0x1000, 0x1800)
    pin_scenario = None
    for target in rungs:
        iters, work, nmi = _hold_speed(runner, target, 120)
        entry = {"target_vel": hex(target), "iters_per_120_frames": iters,
                 "work_mc_max": max(work), "nmi_mc_max": max(nmi)}
        ladder[hex(target)] = entry
        if iters >= 118:
            pin_scenario = entry              # fastest rung that held so far
    RESULTS["speed_ladder"] = ladder
    assert pin_scenario is not None, (
        f"NO cruise speed holds 60 fps on the probe — ladder: {ladder}")

    # ---- flat out (VELOCITY_MAX): record the known cadence collapse ----
    for _ in range(40):
        runner.frame_step(60, b=True)
        if runner.read_u16(WR, DBG_VEL) >= 0x3000:
            break
    assert runner.read_u16(WR, DBG_VEL) == 0x3000
    iters, work, nmi = _cadence_window(runner, 240, b=True)
    RESULTS["flat_out_vmax"] = {
        "pose_cadence_hz": round(60.0 * iters / 240, 1),
        "work_mc_max_per_pose_update": max(work), "nmi_mc_max": max(nmi)}

    # ---- turning at speed: full software pv_rebuild every pose frame ----
    iters, work, nmi = _cadence_window(runner, 240, b=True, left=True)
    # DBG_REBUILD is a per-loop-iteration flag (cleared at the loop head,
    # set once pv_rebuild ran) — sample it over a WINDOW of consecutive
    # turning frames instead of trusting one instant (the audit's flake)
    fired = 0
    for _ in range(REBUILD_WINDOW):
        runner.frame_step(1, b=True, left=True)
        fired += 1 if runner.read_byte(WR, DBG_REBUILD) else 0
    need = int(REBUILD_MIN_FIRE * REBUILD_WINDOW)
    assert fired >= need, (
        f"rebuild fired in only {fired}/{REBUILD_WINDOW} sampled turning "
        f"frames (need >= {need})")
    RESULTS["turning_rebuild"] = {
        "pose_cadence_hz": round(60.0 * iters / 240, 1),
        "work_mc_max_per_pose_update": max(work),
        "rebuild_fired_frames": f"{fired}/{REBUILD_WINDOW}"}

    # ---- the pin: MAX over PIN_PASSES full re-boot/re-anchor/replay
    # passes of the winning rung — three independent boots must agree ----
    pin_target = int(pin_scenario["target_vel"], 16)
    prefix = [t for t in rungs if t <= pin_target]
    passes = [_pin_pass(runner, sfc, prefix) for _ in range(PIN_PASSES)]
    totals = [p["total_mc"] for p in passes]
    spread = (max(totals) - min(totals)) / min(totals)
    assert spread <= PASS_AGREE_TOL, (
        f"pin passes disagree by {spread * 100:.1f}% (> "
        f"{PASS_AGREE_TOL * 100:.0f}%): {totals} — the frame anchor is "
        f"leaking wall-clock variance; fix the driving before pinning")
    total = max(totals)
    worst = max(passes, key=lambda p: p["total_mc"])

    # ---- the feasibility pin + gate ----
    RESULTS["pin"] = {
        "cpu_cycles_per_frame_worst_mc": total,
        "scenario": f"cruise@{pin_scenario['target_vel']} holding 60 fps",
        "work_mc": worst["work_mc_max"], "nmi_mc": worst["nmi_mc_max"],
        "passes": totals, "spread_pct": round(spread * 100, 2),
        "anchor_frame": ANCHOR_FRAME,
        "frame_mc": FRAME_MC, "pct_of_frame": round(100 * total / FRAME_MC, 1)}
    assert total < FRAME_MC, (
        f"worst 60fps-holding frame {total} mc exceeds one frame "
        f"({FRAME_MC}) — the architecture must change before an earlier phase")
    # the naive paths are EXPECTED to break cadence on the probe; assert
    # we actually measured that (they are the constraints an earlier phase must beat)
    assert RESULTS["flat_out_vmax"]["pose_cadence_hz"] < 45.0
    assert RESULTS["turning_rebuild"]["pose_cadence_hz"] < 45.0


def test_stream_step_cost(runner):
    """Deliverable 6.3: cycles per Mode 7 row treadmill step (staging a
    128-byte row from flat ROM), via the probe's free-run ticks/frames
    instrument on the CY_STEP build — frame-anchored like the scenarios
    (the CY_STEP bench bypasses the game loop, so the anchor here is a
    fixed PPU frame, not DBG_FRAMES)."""
    sfc = SUPERFORGE / "build" / "probe_cpu_step.sfc"
    runner.boot_rom(str(sfc), frames=30)
    try:
        runner.debug_break()
        f = runner.ppu_frame_count()
        assert f < 140, f"boot overran the stream anchor (ppu frame {f})"
        runner.frame_step(150 - f)             # fixed PPU-frame anchor
        it1 = int.from_bytes(runner.read_bytes(WR, 0xE7F4, 4), "little")
        fr1 = runner.ppu_frame_count()
        runner.frame_step(180)
        it2 = int.from_bytes(runner.read_bytes(WR, 0xE7F4, 4), "little")
        fr2 = runner.ppu_frame_count()
    finally:
        runner.debug_resume()
    iters, frames = it2 - it1, fr2 - fr1
    assert iters > 500 and frames == 180, (iters, frames)
    mc_per_step = frames * FRAME_MC / iters
    RESULTS["stream_row_step"] = {
        "mc_per_step": round(mc_per_step), "iters": iters, "frames": frames,
        "note": "stage one 128-B row from flat ROM into WRAM (upload DMA "
                "cost is separate: 128 B x 8 mc/B + channel arm)"}
    # sanity bounds: a 128-iteration [dp],y copy loop is thousands of mc,
    # far under a frame
    assert 2_000 < mc_per_step < 80_000, mc_per_step


def test_write_measurements(runner):
    out = SUPERFORGE / "build" / "measurements_cpu.json"
    assert "pin" in RESULTS and "stream_row_step" in RESULTS
    out.write_text(json.dumps(RESULTS, indent=2) + "\n")
