"""The frame-assumption lint's own tests — tools/tick_lint.py.

A gate nobody has tried to break is exactly the indirect-evidence trap
CLAUDE.md rule 2 warns about, so every check here runs against a
DELIBERATELY-VIOLATING fixture under tests/fixtures/tick_lint/ and against a
clean control. Three shapes matter most:

  * a violation must be REFUSED (the gate has teeth),
  * a BARE `TICK: ok` must itself be refused (the stamp is not the reason),
  * the two rules that separate a UNIT from a WORD must hold: `EDGE = 2
    ; frame line` is a border and `ROLL_FIX = 8 ; the 8.8 fraction width` is
    a shift, and neither is a clock. Those two false positives are why the
    equate check uses a tighter vocabulary than the state check, and if that
    ever regresses the baseline fills with noise and the gate stops being
    read.

The last group runs the gate against the LIVE tree through the real
`make tick-check` recipe, so a baseline that drifts away from the tree is a
red here rather than a surprise later. It also pins the reconciliation
`docs/96` §3 reports: the state check reproduces `docs/95` §5.2's 135
exactly, and the 27 rails with it.
"""
import json
import subprocess
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
FIX = SUPERFORGE / "tests" / "fixtures" / "tick_lint"
sys.path.insert(0, str(SUPERFORGE / "tools"))

import tick_lint as TL  # noqa: E402


def rules(name):
    return [f.rule for f in TL.lint_file(str(FIX / name))]


def lines_for(name, rule):
    return [f.line for f in TL.lint_file(str(FIX / name)) if f.rule == rule]


# --- the checks have teeth --------------------------------------------------

def test_clean_state_is_clean():
    assert rules("clean_state.toml") == []


def test_declared_frame_state_is_refused():
    # i-frames, an animation clock, an 8.8 rate, and a "this frame's" step.
    assert lines_for("frame_state.toml", "tick-state") == [3, 5, 7, 9, 10, 20, 23]


def test_bare_companion_declaration_inherits_the_unit():
    """`stepy` (line 10) has NO comment of its own — it shares `stepx`'s.
    It is exactly as frame-coupled, and the three of these in the live tree
    are the whole difference between docs/95's 135 and the 132 its own
    stated rule mechanises to."""
    assert 10 in lines_for("frame_state.toml", "tick-state")


def test_per_frame_routine_is_refused_by_name():
    assert lines_for("frame_engine.asm", "tick-routine") == [7]


def test_frame_unit_equates_are_refused():
    # MXL_STEP_FRAMES (by name) and ROLL_PEAK_CAP (`4.0 px/frame`, by unit).
    assert lines_for("frame_engine.asm", "tick-constant") == [2, 3]


def test_a_frame_that_is_a_border_is_not_a_clock():
    """`EDGE = 2  ; frame line` and `ROLL_FIX = 8  ; the 8.8 fraction width`
    are the two false positives the loose state vocabulary produced. The
    equate check must NOT take either."""
    assert 4 not in lines_for("frame_engine.asm", "tick-constant")
    assert 5 not in lines_for("frame_engine.asm", "tick-constant")


def test_a_routine_that_merely_runs_each_frame_is_not_a_clock():
    """`obj_place` says "called once per frame" in its header and does not
    COUNT in frames. A doc-phrase rule swept in 45 of these; the name rule
    does not."""
    assert 10 not in lines_for("frame_engine.asm", "tick-routine")


def test_ntsc_frame_constant_and_frame_ntsc_read_are_refused():
    assert lines_for("frame_substrate.py", "tick-substrate") == [2, 3, 5]


# --- the override convention ------------------------------------------------

def test_a_reasoned_override_suppresses():
    assert 13 not in lines_for("frame_state.toml", "tick-state")
    assert 12 not in lines_for("frame_engine.asm", "tick-routine")


def test_a_bare_override_is_itself_a_finding():
    got = TL.lint_file(str(FIX / "frame_state.toml"))
    bare = [f for f in got if f.rule == "bare-override"]
    assert [f.line for f in bare] == [24]
    # and it does NOT suppress the site it is stamped on
    assert 23 in lines_for("frame_state.toml", "tick-state")


# --- the live tree ----------------------------------------------------------

def test_make_tick_check_is_clean():
    r = subprocess.run(["make", "tick-check"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 NEW finding(s)" in r.stdout


def test_baseline_matches_the_tree_exactly():
    """The baseline must be neither stale nor padded: every entry in it must
    still be a live finding. A baseline with dead entries is how a gate's
    population quietly stops meaning anything."""
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "tools" / "tick_lint.py"),
         "engine", "game", "tools", "allocator", "tests", "--json"],
        cwd=SUPERFORGE, capture_output=True, text=True)
    live = {(f["file"], f["line"], f["rule"]) for f in json.loads(r.stdout)}
    base = json.loads(
        (SUPERFORGE / "reports" / "tick_lint_baseline.json").read_text())
    stale = {(b["file"], b["line"], b["rule"]) for b in base} - live
    assert not stale, f"baseline entries that are no longer findings: {stale}"


def test_state_check_reproduces_docs95_135_across_27_rails():
    """docs/95 §5.2 reports 135 declared frame-unit words across 27 of the 37
    rails. That is the number this gate exists to bound, so it is pinned:
    if a rail gains one, this fails and somebody decides in front of a
    reviewer."""
    base = json.loads(
        (SUPERFORGE / "reports" / "tick_lint_baseline.json").read_text())
    st = [b for b in base if b["rule"] == "tick-state"]
    assert len(st) == 135
    assert len({b["file"] for b in st}) == 27
