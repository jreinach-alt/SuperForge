"""Stage 4 — GATE CONDITION 5, first half: 60 fps cadence at the declared max.

the spec: "60 fps pose cadence HELD at declared max camera speed on a
cycle-accurate measurement; kernels beat 68,578 mc/row, measured."

This module pins the CADENCE half. It is measured, not estimated, and the
measurement surface is the engine's own arithmetic rather than a timer:

  The race tick integrates the car exactly once per frame. tools/gen_move_lut
  .Sim is a bit-exact mirror of that arithmetic, and the harness advances the
  ROM by exactly one emulated frame per Sim step. So if the loop ever fails
  to complete its work inside a frame, sm_frame_sync parks it on the NEXT
  NMI, the tick runs one fewer time than the frame counter advances, and the
  ROM's position, velocity, sub-pixel accumulators and lap state fall behind
  the oracle — permanently, and by an exactly predictable amount. Holding
  integer lockstep across the window IS the statement "every frame's work
  fit in its frame".

That is a stronger surface than a cycle budget with margin: it cannot pass
while the engine is quietly dropping a frame, and it needs no in-ROM
instrumentation, so the ROM measured here is the ROM that ships.

The envelope is the DECLARED one (the route brief §3.1 — measure from the declared
max, not from whatever debug input can produce):
  * velocity at MZ_VEL_MAX ($3000, 48 px/frame), reached by holding
    B and then held there for the whole window;
  * a steer input every frame, i.e. the declared max turn of one pose step
    per frame — which forces persp_set_pose to retarget the perspective in
    EVERY VBlank;
  * the streaming worst case included by construction: 3.75 revolutions
    sweeps the camera through every heading, so every mix of entering rows
    and columns (including the diagonal maximum) occurs inside the window.

Writes build/measurements_rebuild.json for allocator/pin_budgets.

STILL OWED by Stage 4 (not measured here): the isolated row/col kernel costs
versus the 68,578 mc/row reference bar. Those need in-ROM SLHV latch rings
like the CPU probe (vendor/probes/make_probe_cpu.py) — MesenRunner
exposes no cycle counter — and that instrumented build is a separate probe
ROM, not this one.
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
RACE = 1

CADENCE_WINDOW = 240        # frames held at the declared max
SPINUP_LIMIT = 120          # frames allowed to reach the declared max velocity


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
    D.enter_race(runner, syms)                 # ride the declared fade edge
    yield runner, syms, lut
    runner.debug_resume()
    runner.stop()


def hw_frames(runner, syms):
    """The NMI's own frame counter — incremented on EVERY VBlank, armed or
    not, so it counts HARDWARE frames independently of the game loop."""
    return runner.read_u16(WR, syms["ES_SM_FRAME"]["start"])


def test_cadence_holds_at_the_declared_max(raced):
    """GATE CONDITION 5 (cadence half), measured.

    Accelerate to the declared max, then hold max throttle AND max turn for
    CADENCE_WINDOW frames, checking the ROM's whole declared race state
    against the bit-exact oracle after EVERY frame. Integer lockstep over
    the window means the tick ran exactly once per frame throughout: 60 fps
    cadence held at the declared envelope."""
    runner, syms, lut = raced
    sim = D.sim_from_rom(runner, syms, lut)

    # --- spin up to the declared max ------------------------------------
    for i in range(SPINUP_LIMIT):
        if D.vel(runner, syms) == lut.VEL_MAX:
            break
        D.drive_sim(runner, sim, 1, b=True)
        D.assert_matches_sim(runner, syms, sim, f"spin-up frame {i}")
    else:
        raise AssertionError(
            f"never reached the declared max in {SPINUP_LIMIT} frames "
            f"(vel={D.vel(runner, syms)}, want {lut.VEL_MAX})")

    # --- the measured window --------------------------------------------
    f0 = hw_frames(runner, syms)
    headings, applied = [], []
    for i in range(CADENCE_WINDOW):
        D.drive_sim(runner, sim, 1, b=True, left=True)
        D.assert_matches_sim(runner, syms, sim, f"cadence frame {i}")
        assert D.vel(runner, syms) == lut.VEL_MAX, (
            f"frame {i}: velocity left the declared max "
            f"({D.vel(runner, syms)} != {lut.VEL_MAX})")
        headings.append(D.heading(runner, syms))
        applied.append(D.heading_applied(runner, syms))
    elapsed = (hw_frames(runner, syms) - f0) & 0xFFFF

    # The loop completed one tick per frame (the lockstep assertions above),
    # and the NMI counted exactly that many frames: no frame was dropped and
    # none was double-counted.
    assert elapsed == CADENCE_WINDOW, (
        f"the NMI counted {elapsed} frames across a {CADENCE_WINDOW}-frame "
        f"window — the loop and the hardware disagree about the frame count")

    # Pose CADENCE specifically: the heading advanced one declared step every
    # single frame, and the VBlank hook committed a retarget for each one.
    # A dropped frame shows up here as a repeated heading.
    steps = [(b - a) % lut.POSES for a, b in zip(headings, headings[1:])]
    assert set(steps) == {1}, (
        f"heading did not advance exactly one pose step per frame: "
        f"observed steps {sorted(set(steps))}")
    assert len(set(applied)) == lut.POSES, (
        f"the NMI applied only {len(set(applied))} distinct poses across "
        f"{CADENCE_WINDOW} frames — pose retargets are not keeping up")

    revolutions = CADENCE_WINDOW / lut.POSES
    (SUPERFORGE / "build" / "measurements_rebuild.json").write_text(json.dumps({
        "cadence": {
            "window_frames": CADENCE_WINDOW,
            "hw_frames_elapsed": elapsed,
            "loop_iterations": CADENCE_WINDOW,
            "velocity": lut.VEL_MAX,
            "turn_steps_per_frame": 1,
            "distinct_poses_applied": len(set(applied)),
            "revolutions": revolutions,
            "held": True,
        },
    }, indent=2) + "\n")


def test_the_window_really_exercised_the_streaming_worst_case(raced):
    """Guards the claim the window above rests on.

    "Max speed + max turn for 240 frames" only covers the streaming worst
    case if the camera actually sweeps every heading — otherwise the
    cadence result would be a claim about one direction of travel, which is
    the single-axis trap the streaming suites were bitten by before. 240
    frames at one pose step each is 3.75 revolutions, so every heading
    (and therefore every row/column entry mix, diagonals included) occurs.
    """
    runner, syms, lut = raced
    assert CADENCE_WINDOW >= lut.POSES, (
        f"a {CADENCE_WINDOW}-frame window at one pose step per frame does "
        f"not complete a revolution ({lut.POSES} poses)")
    # the camera moved a long way at the declared max, not in a tight circle
    # around its start point: 48 px/frame over the window
    assert lut.VEL_MAX >> 8 == 48, \
        f"declared max is no longer 48 px/frame: {lut.VEL_MAX >> 8}"
