"""microzero — the full loop, and GATE CONDITION 2.

the spec: "User state at both scopes: global score/lives survive the
whole loop (rendered); scene state freed/reused across scenes."

title -> race -> results -> title, driven end to end on the emulator. Every
claim about surviving state is read back as RENDERED TEXT — the BG3 tilemap
words actually sitting in VRAM, decoded to characters — not from the WRAM
variable the scene happened to write. A scene that computed the right number
and failed to draw it fails here.

The two scopes are proven in opposite directions:
  * GLOBAL survives — score and lives are banked in race, spent on entry, and
    still rendered by a title scene that was torn down and re-entered.
  * SCENE state is freed and re-initialised — title's frame counter restarts
    on the revisit, and results' tally occupies WRAM bytes the race scene was
    using for its stream buffers (the allocation report proves the overlap;
    the render proves the runtime re-init).
"""
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

VR, WR = MemoryType.SnesVideoRam, MemoryType.SnesWorkRam

TITLE, RACE, RESULTS = 0, 1, 2
LAP_SCORE = 300                  # RACE_LAPS * RACE_LAP_SCORE (world.inc)


@pytest.fixture(scope="module")
def booted():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {name: {p["sym"]: p for p in
                   jmap["scenes"][name]["placements"] + jmap["globals"]}
            for name in ("title", "race", "results")}
    lut = D.load_tool("gen_move_lut")
    runner = MesenRunner()
    runner.load_rom_with_uninit_detection(
        str(SUPERFORGE / "build" / "microzero.sfc"), frames=120)
    runner.wait_frames(60)
    runner.debug_break()
    runner.frame_step(2)
    yield runner, syms, lut
    runner.debug_resume()
    runner.stop()


# --- rendered-text readback -------------------------------------------------

def text_at(runner, syms, row, col, n):
    """Decode n characters straight out of the scene's BG3 tilemap in VRAM.
    Glyph index IS the tile id (bg_text maps ' ' to tile 0), so the attr bits
    mask off and the rest converts back to ASCII."""
    base = syms["ES_V_TEXT_MAP"]["start"] + row * 32 + col
    raw = runner.read_bytes(VR, 2 * base, 2 * n)
    words = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]
    return "".join(chr((w & 0x3FF) + 0x20) for w in words)


def scene_state(runner, syms):
    ctl = syms["ES_SM_CTL"]["start"]
    cur, _nxt, phase = runner.read_bytes(WR, ctl, 3)
    return cur, phase


def wait_for_scene(runner, syms, scene_id, limit=600):
    """Frame-step until the phase machine has settled INTO scene_id (fade-out,
    forced-blank switch and fade-in all complete)."""
    for _ in range(limit):
        if scene_state(runner, syms) == (scene_id, 0):
            runner.frame_step(2)             # let the render catch up
            return
        runner.frame_step(1)
    raise AssertionError(
        f"scene {scene_id} never settled; stuck at {scene_state(runner, syms)}")


def press_start(runner):
    runner.frame_step(2, start=True)
    runner.frame_step(2)


def globals_now(runner, syms):
    g = syms["title"]
    return (runner.read_u16(WR, g["US_SCORE"]["start"]),
            runner.read_bytes(WR, g["US_LIVES"]["start"], 1)[0])


def run_one_race(runner, syms, lut):
    """START at the title, drive the ring to the finish, settle in results."""
    press_start(runner)
    wait_for_scene(runner, syms["race"], RACE)
    sim = D.sim_from_rom(runner, syms["race"], lut)
    D.drive_laps(runner, syms["race"], sim, lut, 3)
    wait_for_scene(runner, syms["results"], RESULTS)


def finish_tally(runner, syms, limit=300):
    """Let the results tally count up and latch done.

    The settle step is required, not defensive: the tick STAGES the final
    digits on the frame it latches done and the NMI commits them at that
    frame's boundary, so VRAM still holds the previous value the instant
    r_done reads as set. Measured — the cells read '0127' at +0 frames and
    '012C' from +1 onward."""
    done = syms["results"]["US_R_DONE"]["start"]
    for _ in range(limit):
        if runner.read_bytes(WR, done, 1)[0]:
            runner.frame_step(2)             # the last queued run commits
            return
        runner.frame_step(1)
    raise AssertionError("the results tally never caught up to the score")


# --- the tests --------------------------------------------------------------

def test_title_renders_the_boot_globals(booted):
    """Baseline: the values the loop has to preserve, read off the screen."""
    runner, syms, lut = booted
    assert scene_state(runner, syms["title"]) == (TITLE, 0)
    assert text_at(runner, syms["title"], 6, 11, 9) == "MICROZERO"
    assert text_at(runner, syms["title"], 20, 6, 10) == "SCORE 0000"
    assert text_at(runner, syms["title"], 20, 17, 7) == "LIVES 3"
    assert globals_now(runner, syms) == (0, 3)


def test_full_loop_carries_the_globals_and_frees_scene_state(booted):
    """GATE CONDITION 2. One complete title -> race -> results -> title lap of
    the game: a life is spent entering the race, three laps bank the score,
    results tallies it up while the scene RUNS, and the title we come back to
    renders both surviving globals. Scene-scoped state re-initialises."""
    runner, syms, lut = booted
    t_frames = syms["title"]["US_T_FRAMES"]["start"]
    assert runner.read_u16(WR, t_frames) > 0, "title never ticked"

    # ---- race: entering costs a life, and the HUD renders the charge ------
    press_start(runner)
    wait_for_scene(runner, syms["race"], RACE)
    assert globals_now(runner, syms) == (0, 2), "race entry did not cost a life"
    assert text_at(runner, syms["race"], 2, 19, 1) == "2", \
        "the race HUD did not render the charged life count"

    # ---- three laps bank laps x 100 and hand off to results ---------------
    sim = D.sim_from_rom(runner, syms["race"], lut)
    D.drive_laps(runner, syms["race"], sim, lut, 3)
    wait_for_scene(runner, syms["results"], RESULTS)
    assert globals_now(runner, syms) == (LAP_SCORE, 2), "score not banked"
    assert text_at(runner, syms["results"], 6, 12, 7) == "RESULTS"
    assert text_at(runner, syms["results"], 16, 11, 7) == "LIVES 2"

    # ---- the tally counts up THROUGH THE VBLANK QUEUE, with the display on
    tally_cell = text_at(runner, syms["results"], 12, 18, 4)
    finish_tally(runner, syms)
    assert runner.read_u16(WR, syms["results"]["US_TALLY"]["start"]) == LAP_SCORE
    assert text_at(runner, syms["results"], 12, 18, 4) == f"{LAP_SCORE:04X}", \
        "the tally digits on screen never reached the score"
    assert text_at(runner, syms["results"], 12, 18, 4) != tally_cell, \
        "the tally never changed — it was drawn once at enter, not counted up"

    # ---- back to title: the globals survived a full teardown + re-entry ---
    press_start(runner)
    wait_for_scene(runner, syms["title"], TITLE)
    assert text_at(runner, syms["title"], 20, 6, 10) == f"SCORE {LAP_SCORE:04X}"
    assert text_at(runner, syms["title"], 20, 17, 7) == "LIVES 2"
    assert globals_now(runner, syms) == (LAP_SCORE, 2)
    # ...and the SCENE-scoped counter did not: it restarted from its contract
    assert runner.read_u16(WR, t_frames) < 60, \
        "title's scene state survived the revisit — it was not re-initialised"


def test_running_out_of_lives_resets_the_run(booted):
    """The other direction of the same proof: globals that survive can also be
    ACTED on. Two more races empty the lives counter, and the title entered
    with zero lives renders a fresh run."""
    runner, syms, lut = booted
    assert globals_now(runner, syms) == (LAP_SCORE, 2)

    for expect_lives, expect_score in ((1, 2 * LAP_SCORE), (0, 3 * LAP_SCORE)):
        run_one_race(runner, syms, lut)
        finish_tally(runner, syms)
        assert globals_now(runner, syms) == (expect_score, expect_lives)
        press_start(runner)
        wait_for_scene(runner, syms["title"], TITLE)

    # the third race left lives at 0, so THIS title entry starts a new run
    assert globals_now(runner, syms) == (0, 3), "the run did not reset"
    assert text_at(runner, syms["title"], 20, 6, 10) == "SCORE 0000"
    assert text_at(runner, syms["title"], 20, 17, 7) == "LIVES 3"


def test_map_proves_scene_bytes_are_reused_across_scenes(booted):
    """The static half of gate condition 2: results' scene-scoped state and
    VRAM occupy bytes the race scene owns. Same addresses, different owners,
    proven at build time — which is only safe BECAUSE the scenes re-initialise
    them on entry, as the loop test above renders.

    Read from symbol_map.json — the same artifact the ROM's addresses are
    emitted from — rather than by re-parsing the human-readable report."""
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())

    def placed(scene, cls):
        """Scene-SCOPED placements only; globals live in their own list, so
        anything here is a claim the scene owns and releases on exit."""
        return [(p["start"], p["start"] + p["size"], p["sym"])
                for p in jmap["scenes"][scene]["placements"]
                if p["class"] == cls and p["scope"] == scene]

    def overlaps(a, b):
        return [(x[2], y[2]) for x in a for y in b
                if x[0] < y[1] and y[0] < x[1]]

    for cls in ("wram", "vram"):
        shared = overlaps(placed("race", cls), placed("results", cls))
        assert shared, (
            f"results reuses none of race's scene-scoped {cls} — the "
            f"lifetime model is not actually recycling anything: "
            f"race={placed('race', cls)} results={placed('results', cls)}")
        print(f"\n{cls} reuse race->results: {shared}")

    # the transitions are modelled edges with checked reload budgets. These
    # are report-only — symbol_map.json carries no edge section, so this half
    # still parses text.
    report = (SUPERFORGE / "build" / "mz" / "allocation_report.txt").read_text()
    edges = re.findall(r"transition (\S+): reload (\d+) B \(budget (\d+)\)",
                       report)
    assert {e[0] for e in edges} == {"title->race", "race->results",
                                     "results->title"}
    for name, reload_b, budget in edges:
        assert int(reload_b) <= int(budget), f"{name} over its budget"


def test_no_uninitialized_reads_across_the_whole_loop(booted):
    """Power-on contract over three full laps of the game loop, every scene
    entered at least twice — re-entry reads only what each enter contract
    wrote."""
    runner, _, _ = booted
    runner.frame_step(10)
    runner.assert_no_uninitialized_reads()
