"""microzero — the mode7_stream kernels, built entirely
through the allocator: leading-edge streaming keeps the WHOLE 128x128 VRAM
window byte-exact against the declared world under heading-based driving in
every direction (cardinal legs incl. a world-wrap crossing, plus an off-axis
diagonal that stages rows AND cols in the same frames), the frame cadence
stays lockstep at the declared max speed (positions match the movement LUT
integer-exactly), the staging cost is bounded frame-anchored against the
reference bar (68,578 mc/row), the allocation report carries the F9 VBlank
budget, and the uninit detector stays clean across the whole path.
"""
import ctypes
import json
import re
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

ROW_STAGE_BAR_MC = 68578         # [measured.stream] row_stage_mc — the bar
FRAME_MC = 357368                # NTSC frame, master cycles (substrate)
DIAG = 40                        # southeast-ish heading: rows + cols together


@pytest.fixture(scope="module")
def booted():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    world = (SUPERFORGE / "build" / "assets" / "world_map.bin").read_bytes()
    lut = D.load_tool("gen_move_lut")
    runner = MesenRunner()
    runner.load_rom_with_uninit_detection(
        str(SUPERFORGE / "build" / "microzero.sfc"), frames=120)
    runner.debug_break()
    D.enter_race(runner, syms)
    runner.debug_break()
    runner.frame_step(2)
    yield runner, syms, world, lut
    runner.debug_resume()
    runner.stop()


SPRINT = 60                      # frames held at the declared max
TO_MAX = 48                      # MZ_VEL_MAX / MZ_ACCEL: frames to top speed


def test_window_tracks_world_through_full_drive_cycle(booted):
    """Cardinal legs (east runs toward the 512-tile world wrap from
    world.inc's CAM0_TX),
    reverse directions, then an off-axis diagonal; after each leg the
    ENTIRE window is byte-exact (a skipped column/row, a stale reverse
    edge, or a wrap bug leaves stale tiles somewhere and fails here).
    Each leg accelerates past the top of the ramp, so it covers the
    declared-max staging load, then brakes to rest — the full-window
    invariant is a stopped-camera claim (see mz_drive.assert_window_exact)."""
    runner, syms, world, lut = booted
    D.assert_window_exact(runner, syms, world, "seeded start")
    legs = ((48, 50, "east + wrap"), (32, 50, "south"),
            (16, 55, "west (reverse)"), (0, 55, "north (reverse)"),
            (DIAG, 50, "diagonal (rows+cols same frame)"))
    for h, n, tag in legs:
        D.steer_to(runner, syms, h)
        D.drive(runner, n, b=True)
        assert D.vel(runner, syms) == lut.VEL_MAX, \
            f"{tag}: leg never reached the declared max"
        D.brake_to_stop(runner, syms)
        D.assert_window_exact(runner, syms, world, "after " + tag)


def test_cadence_lockstep_at_declared_max_speed(booted):
    """Gate condition 5's slice-level form: 60 frames held at the declared
    max on the diagonal heading (worst streaming load). Velocity is pinned
    at MZ_VEL_MAX for every one of them and the position + both sub-pixel
    accumulators track the oracle EXACTLY — a tick that spills past VBlank
    drops a frame of integration and breaks the equality."""
    runner, syms, world, lut = booted
    D.steer_to(runner, syms, DIAG)
    D.drive(runner, TO_MAX, b=True)              # climb the ramp
    assert D.vel(runner, syms) == lut.VEL_MAX
    sim = D.sim_from_rom(runner, syms, lut)
    for i in range(SPRINT):
        D.drive_sim(runner, sim, 1, b=True)
        assert D.vel(runner, syms) == lut.VEL_MAX, f"speed dipped at {i}"
    D.assert_matches_sim(runner, syms, sim, "declared-max change")
    D.brake_to_stop(runner, syms)
    D.assert_window_exact(runner, syms, world, "after lockstep change")


def test_stage_cost_measured_beats_the_reference_bar(booted):
    """Frame-anchored bound against [measured.stream] row_stage_mc =
    68,578. A deterministic change at the declared max diagonal holds
    LUT-exact lockstep (asserted above and re-checked here), so every
    frame's staging PLUS the whole rest of the engine fit inside one
    357,368-mc frame. The per-frame staging load is derived from the LUT
    (tile crossings per frame, both axes); attributing the ENTIRE frame to
    staging bounds one 128-B stage at FRAME_MC / worst_slices — well under
    the reference's cost for the same stage. Raw per-frame CPU-cycle
    deltas are recorded as the work signature (CycleCount ticks through
    WAI at 6 clocks and halts during DMA, so busy frames show FEWER
    cycles; the inversion itself proves the frames stayed frame-shaped)."""
    runner, syms, world, lut = booted
    lib = runner._lib
    have_cpu_state = hasattr(lib, "GetCpuState")
    if have_cpu_state:
        lib.GetCpuState.restype = None
        lib.GetCpuState.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    buf = (ctypes.c_uint8 * 512)()

    def cycles():
        lib.GetCpuState(buf, 0)
        return int.from_bytes(bytes(buf[0:8]), "little")

    D.steer_to(runner, syms, DIAG)
    D.drive(runner, TO_MAX, b=True)              # climb to the declared max
    assert D.vel(runner, syms) == lut.VEL_MAX
    sim = D.sim_from_rom(runner, syms, lut)
    c0 = cycles() if have_cpu_state else 0
    D.drive_sim(runner, sim, 30, b=True)
    c1 = cycles() if have_cpu_state else 0
    D.assert_matches_sim(runner, syms, sim, "change lost cadence")

    # worst per-frame slice load, taken from the oracle at the declared max
    # (tile crossings per frame on both axes, sub-pixel phase included)
    def worst_slices():
        probe = lut.Sim(sim.x, sim.y, h=sim.h, vel=lut.VEL_MAX,
                        sub_x=sim.sub_x, sub_y=sim.sub_y)
        prev, worst = (probe.x >> 3, probe.y >> 3), 0
        for _ in range(60):
            probe.frame(b=True)
            cur = (probe.x >> 3, probe.y >> 3)
            span = sum(abs(((c - p + 256) & 511) - 256)
                       for c, p in zip(cur, prev))
            worst, prev = max(worst, span), cur
        return worst

    ws = worst_slices()
    assert ws >= 6, f"declared-max diagonal should cross >=6 tiles/frame ({ws})"
    slice_bound_mc = FRAME_MC // ws
    print(f"\ndeclared-max diagonal h{DIAG} at vel ${lut.VEL_MAX:04X}: worst "
          f"{ws} slices/frame sustained lockstep -> <= {slice_bound_mc} mc "
          f"per 128-B stage (whole-frame attribution)")
    print(f"reference bar: {ROW_STAGE_BAR_MC} mc/row -> margin "
          f"{ROW_STAGE_BAR_MC / slice_bound_mc:.1f}x")
    assert slice_bound_mc < ROW_STAGE_BAR_MC, \
        "frame-anchored bound no longer beats the reference bar"
    if have_cpu_state:
        D.brake_to_stop(runner, syms)
        idle0 = cycles()
        D.drive(runner, 30)
        idle = cycles() - idle0
        busy = c1 - c0
        print(f"raw CPU-cycle/30-frame: busy {busy} vs idle {idle}")
        assert busy < idle, "no work signature vs idle"


def test_report_carries_the_vblank_budget(booted):
    """The F9 model in the live map: the race scene's VBlank sum includes
    the stream's 16 transfers x 128 B and stays inside the measured 5952-B
    budget (the newest slice's test asserts the exact composition line)."""
    report = (SUPERFORGE / "build" / "mz" / "allocation_report.txt").read_text()
    m = re.search(r"VBLANK-DMA (\d+) \+ (\d+) arm/5952 B/frame "
                  r"\((\d+) transfers\)", report)
    assert m, "race VBlank budget line missing"
    data_b, arm_b, transfers = map(int, m.groups())
    assert data_b >= 2048 and transfers >= 16, (data_b, transfers)
    assert data_b + arm_b <= 5952
    _, _, world, _ = booted
    assert len(world) == 512 * 512


def test_second_vblank_vmdatal_consumer_composes(tmp_path, repo_tree_read_lock):
    """The composition gate's POSITIVE, and the counterpart to the BGMODE and
    COLDATA negatives: a second feature uploading to VRAM in VBlank alongside
    mode7_stream's VMDATAL claim must ALLOCATE, because VBlank transfers are
    serialised queue entries rather than concurrent register owners.

    Run against the REAL microzero declaration through the REAL CLI, so what
    is proven is the whole composition — 7 active channels, streaming, OAM,
    plus the new consumer — and not a hand-built fixture. Both claims must
    land on distinct channels, both must appear against VMDATAL in the
    report, and the VBlank budget must charge for both.
    """
    import shutil
    gdir = tmp_path / "game"
    feats = tmp_path / "features"
    # SHARED lock for the copy only: `test_register.py` plants into live
    # `engine/features/*/feature.toml` and a copy taken mid-plant allocates
    # differently than this test expects (a recorded finding).
    with repo_tree_read_lock():
        shutil.copytree(SUPERFORGE / "game" / "microzero", gdir)
        shutil.copytree(SUPERFORGE / "engine" / "features", feats)

    # The BASELINE comes from a second run of the CLI against these same
    # pristine copies, NOT from build/mz/allocation_report.txt. Reading the
    # build tree made this test depend on an artifact none of its fixtures
    # produce: it passed under `make test` only because another module's
    # fixture had built first, and standalone it died with a FileNotFoundError
    # rather than a diagnosable assertion (VWF a later review). Two CLI runs over
    # one tmp tree is the whole fix, and it also makes the delta a comparison
    # of like with like — same features dir, same game dir, one added feature.
    out_base = tmp_path / "out_base"
    rb = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(gdir), "--features-dir", str(feats),
         "--out", str(out_base)],
        capture_output=True, text=True)
    assert rb.returncode == 0, (
        f"the UNMODIFIED declaration was refused, so there is no baseline to "
        f"measure the new consumer against:\n{rb.stderr}")

    up = feats / "hud_upload"
    up.mkdir()
    (up / "feature.toml").write_text(
        'name = "hud_upload"\nrole = "feature"\n[[claims.hdma]]\nname = "hudq"\n'
        'registers = ["VMDATAL"]\nband = [0, 224]\nphase = "vblank"\n'
        '[claims.dma]\nvblank_bytes_per_frame = 64\n'
        'vblank_transfers_per_frame = 1\n')
    gt = (gdir / "game.toml").read_text()
    (gdir / "game.toml").write_text(gt.replace(
        '"mode7_stream", "player_car"', '"mode7_stream", "player_car",\n'
        '            "hud_upload"'))
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(gdir), "--features-dir", str(feats), "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, f"the composition was refused:\n{r.stderr}"

    report = (out / "allocation_report.txt").read_text()
    race = report.split("scene 'race'")[1]
    vmdatal = [ln for ln in race.splitlines() if "VMDATAL" in ln]
    # A COUNT here would break every time a real feature adds a VBlank VRAM
    # upload (vwf's vwfq did exactly that), and the count was never the point.
    # The properties are: the injected consumer composes, it is NOT merged with
    # an existing one, and every consumer gets its own channel in this phase.
    names = {ln.split()[1] for ln in vmdatal}
    assert {"mzs", "hudq"} <= names, f"expected mzs + hudq among {vmdatal}"
    assert len(vmdatal) >= 2
    chans = {ln.split()[0] for ln in vmdatal}
    assert len(chans) == len(vmdatal), (
        f"two vblank VMDATAL claims landed on one channel: {vmdatal}")
    assert all("vblank" in ln for ln in vmdatal)

    m = re.search(r"VBLANK-DMA (\d+) \+ (\d+) arm/5952 B/frame "
                  r"\((\d+) transfers\)", race)
    assert m, "race VBlank budget line missing"
    data_b, arm_b, transfers = map(int, m.groups())
    # charged relative to the REAL declaration this runs against, so the
    # assertion stays about hud_upload rather than about whatever else is in the
    # scene: read the baseline run's report and require exactly the delta.
    base = re.search(r"VBLANK-DMA (\d+) \+ (\d+) arm/5952 B/frame "
                     r"\((\d+) transfers\)",
                     (out_base / "allocation_report.txt")
                     .read_text().split("scene 'race'")[1])
    assert base, "baseline race VBlank budget line missing"
    base_b, _, base_x = map(int, base.groups())
    assert data_b == base_b + 64, "the new consumer's bytes were not charged"
    assert transfers == base_x + 1, "the new consumer's transfer was not charged"
    assert data_b + arm_b <= 5952

    # the emitted map must give each claim its OWN channel symbol — ASM binds
    # channels through these, never by number (this is the step the allocator
    # unit tests stop short of)
    inc = (out / "engine_state_race.inc").read_text()
    syms = dict(re.findall(r"^(ES_H_\w+_CH) = (\S+)", inc, re.M))
    assert {"ES_H_MZS_CH", "ES_H_HUDQ_CH"} <= set(syms), syms
    assert syms["ES_H_MZS_CH"] != syms["ES_H_HUDQ_CH"]


def test_no_uninitialized_reads_across_the_streaming_path(booted):
    """Power-on contract over the whole drive history: staged slots are the
    only buffer bytes the DMA ever read, meta words were written before
    use, and no kernel touched RAM it didn't own."""
    runner, _, _, _ = booted
    runner.frame_step(10)
    runner.assert_no_uninitialized_reads()
