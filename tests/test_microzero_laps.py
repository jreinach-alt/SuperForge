"""microzero — race_logic lap detection.

The world is quartered around the ring centre (0 NE, 1 NW, 2 SW, 3 SE;
y grows south) and the start/finish spoke runs due east, so the spoke IS the
3->0 sector edge. A lap counts only when every sector was visited since the
last one.

The drive is a real circuit of the generated ring track: a steering
controller (tangent + radius correction, run against the ORACLE so the
button sequence is deterministic and independent of the ROM) laps the car
around at the declared max. Every frame the ROM's own lap/sector/checkpoint
bytes and its position are compared with the oracle, and the path is checked
against the world map itself — the car really does drive on the road, so the
lap counter is counting laps of the track, not of an abstraction.
"""
import json
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

# from the generator (SSoT): road body, every centre-line variant and
# the start/finish spoke — kerbs excluded, they are the edge not the road
ROAD_TILES = D.load_tool("gen_m7_assets").DRIVABLE_TILE_IDS
# the ring controller lives in mz_drive (shared with the loop test)


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


def test_start_line_wiggle_never_scores_a_lap(booted):
    """Crossing the start/finish spoke back and forth is not a lap: the
    3->0 edge only counts with every sector's checkpoint bit set, so the
    counter must stay at zero however often the line is crossed."""
    runner, syms, world, lut = booted

    def sector():
        return D.race_state(runner, syms)[6]

    def ckpt():
        return D.race_state(runner, syms)[7]

    D.brake_to_stop(runner, syms)
    D.steer_to(runner, syms, 0)
    D.brake_to_stop(runner, syms)
    start_lap = D.lap(runner, syms)
    crossings, prev = 0, sector()
    for _ in range(4):
        for h in (0, 32):                    # north over the line, south back
            D.steer_to(runner, syms, h)      # at rest: steering does not move
            D.drive(runner, 16, b=True)
            D.brake_to_stop(runner, syms)
            cur = sector()
            crossings += cur != prev
            prev = cur
            assert D.lap(runner, syms) == start_lap, \
                "a wiggle over the start/finish line scored a lap"
    assert crossings >= 6, f"only {crossings} spoke crossings — geometry drifted"
    assert ckpt() == (1 << 0) | (1 << 3), \
        (f"checkpoint mask is {ckpt():#06b} — the wiggle only ever visits NE "
         f"and SE, so a circuit can never look complete from here")


def test_three_laps_of_the_ring_count_exactly(booted):
    """Drive the real circuit at the declared max. The ROM's lap counter
    must step 0->1->2->3 on the SAME frames the oracle does, every sector
    checkpoint must be collected before each lap scores, the whole physics
    state stays byte-identical throughout, and the path stays on the road
    of the generated world map."""
    runner, syms, world, lut = booted
    D.brake_to_stop(runner, syms)
    D.steer_to(runner, syms, 0)
    D.brake_to_stop(runner, syms)
    sim = D.sim_from_rom(runner, syms, lut)
    start_lap = sim.lap

    lap_frames, off_road, ckpt_before_lap = [], 0, []
    for f in range(700):
        prev_lap, prev_ckpt = sim.lap, sim.ckpt
        D.drive_sim(runner, sim, 1, **D.track_buttons(sim, lut))
        if sim.lap != prev_lap:
            lap_frames.append(f)
            ckpt_before_lap.append(prev_ckpt)
        assert D.lap(runner, syms) == sim.lap, \
            f"frame {f}: ROM lap {D.lap(runner, syms)} vs oracle {sim.lap}"
        # the sector byte must stay a sector on EVERY frame, the scoring
        # frame included — the lap branch does extra work (HUD staging) with
        # the sector index live in X, and a clobber there shows up here and
        # nowhere else (the lap counter itself keeps counting correctly)
        rom_sector = D.race_state(runner, syms)[6]
        assert rom_sector <= 3, \
            f"frame {f}: sector byte is {rom_sector} — X was clobbered"
        if world[(sim.y >> 3) * 512 + (sim.x >> 3)] not in ROAD_TILES:
            off_road += 1
        if len(lap_frames) == 3:
            break
    D.assert_matches_sim(runner, syms, sim, "after three laps")

    assert len(lap_frames) == 3, f"only {len(lap_frames)} laps in 700 frames"
    assert D.lap(runner, syms) == start_lap + 3
    assert all(c == lut.CKPT_ALL for c in ckpt_before_lap), \
        f"a lap scored on an incomplete circuit: {ckpt_before_lap}"
    gaps = [b - a for a, b in zip(lap_frames, lap_frames[1:])]
    assert all(g > 100 for g in gaps), f"laps double-counted at the line: {gaps}"
    assert off_road == 0, \
        f"the circuit left the road for {off_road} frames — not a track lap"
    assert D.vel(runner, syms) == lut.VEL_MAX, "the circuit was not run at max"
    print(f"\nlap frames {lap_frames} (gaps {gaps}), off-road {off_road}")

    # RACE_LAPS is also the finish line: the tick that scored lap 3 requested
    # the results scene, so the phase machine has left "run" and race::tick no
    # longer runs. (The car therefore cannot be braked from here — the
    # full-window streaming invariant is checked mid-race in the stream and
    # physics suites, which is its proper home.)
    ctl = syms["ES_SM_CTL"]["start"]
    assert runner.read_bytes(WR, ctl + 1, 1)[0] == 2, "results not requested"
    assert runner.read_bytes(WR, ctl + 2, 1)[0] != 0, "still in the run phase"


def test_no_uninitialized_reads_across_the_lap_path(booted):
    """Power-on contract over the whole lap history — the sector machine
    reads only the state rl_arm seeded."""
    runner, _, _, _ = booted
    runner.frame_step(10)
    runner.assert_no_uninitialized_reads()
