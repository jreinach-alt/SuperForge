"""The time-coupling lint's own tests — tools/no_wallclock.py.

A gate nobody has tried to break is exactly the indirect-evidence trap
CLAUDE.md rule 2 warns about, so every check here is exercised against a
DELIBERATELY-VIOLATING fixture under tests/fixtures/no_wallclock/ and against
a clean control. The two shapes that matter most are the ones an override
convention rots through:

  * a violation must be REFUSED (the gate has teeth),
  * a BARE `# WALL-CLOCK: ok` must itself be refused (the stamp is not the
    reason).

The last group runs the gate against the LIVE tree via the real `make
time-check` recipe, so a baseline that drifts away from the tree is a red
here rather than a surprise at push time.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
FIX = SUPERFORGE / "tests" / "fixtures" / "no_wallclock"
sys.path.insert(0, str(SUPERFORGE / "tools"))

import no_wallclock as NW  # noqa: E402


def rules(name):
    """The rule names the lint reports for one fixture, in line order."""
    return [f.rule for f in NW.lint_file(str(FIX / name))]


def run_cli(*args):
    return subprocess.run([sys.executable, str(SUPERFORGE / "tools" / "no_wallclock.py"),
                           *args], capture_output=True, text=True, cwd=SUPERFORGE)


# =============================================================================
# THE CHECKS
# =============================================================================
def test_a_clean_module_is_clean():
    """The control arm. Without this, every green below could be a gate that
    finds nothing anywhere."""
    assert rules("clean.py") == []


def test_every_wallclock_shape_is_refused():
    """One finding per rule, and no rule silently missing."""
    assert rules("sleeper.py") == [
        "wallclock-sleep", "wallclock-run-frames",
        "wallclock-run-seconds", "wallclock-timeout-s",
    ]


def test_a_read_of_a_free_running_core_is_refused():
    """The measured flake: a read placed in time only by a wall sleep."""
    found = [(f.line, f.rule) for f in NW.lint_file(str(FIX / "free_run_read.py"))]
    assert ("free-run-read" in [r for _, r in found]), found
    # ...and the message names the wall advance that calibrated it, because
    # "this is load-dependent" without the culprit is not actionable.
    msg = [f.message for f in NW.lint_file(str(FIX / "free_run_read.py"))
           if f.rule == "free-run-read"][0]
    assert "run_frames" in msg and "line 10" in msg


def test_parking_before_the_read_clears_it():
    """The documented fix must actually satisfy the gate — a rule whose fix
    still fails teaches people to override instead."""
    lines = [f.line for f in NW.lint_file(str(FIX / "free_run_read.py"))
             if f.rule == "free-run-read"]
    assert 19 not in lines, \
        "the parked read (debug_break before read_bytes) was still flagged"


def test_a_filesystem_read_is_not_an_emulator_read():
    """`Path(p).read_bytes()` shares the name with the harness read and is
    NOT a read of the machine. Arity discriminates them; this is the
    false positive that would have made the rule unusable."""
    lines = [f.line for f in NW.lint_file(str(FIX / "free_run_read.py"))
             if f.rule == "free-run-read"]
    assert 24 not in lines, "a Path.read_bytes() was flagged as an emulator read"


# =============================================================================
# THE OVERRIDE
# =============================================================================
def test_an_override_with_a_reason_suppresses():
    assert rules("overridden.py") == []


def test_a_bare_override_is_itself_a_finding():
    """The rubber stamp. It must NOT suppress, and must be named."""
    got = rules("bare_override.py")
    assert "bare-override" in got, got
    assert "wallclock-sleep" in got, \
        "a bare stamp suppressed the finding it was placed on"


@pytest.mark.parametrize("sep,ok", [
    ("— because audio is real time", True),
    ("-- because audio is real time", True),
    (" - because audio is real time", True),
    (": because audio is real time", True),
    ("", False),
    (" ", False),
])
def test_the_reason_text_is_required(tmp_path, sep, ok):
    p = tmp_path / "m.py"
    p.write_text(f"import time\n\n\ndef f():\n"
                 f"    time.sleep(1)   # WALL-CLOCK: ok{sep}\n")
    found = [f.rule for f in NW.lint_file(str(p))]
    if ok:
        assert found == [], f"a valid override with {sep!r} did not suppress"
    else:
        assert "wallclock-sleep" in found, \
            f"{sep!r} was accepted as a reason — the stamp is not the reason"


def test_the_override_radius_is_three_lines(tmp_path):
    """±3, matching width_lint. A wider radius silences neighbours."""
    body = "import time\n\n\ndef f():\n" + "".join(
        f"    x = {i}\n" for i in range(5)) + "    time.sleep(1)\n"
    near = body.replace("    x = 2\n", "    x = 2  # WALL-CLOCK: ok — near\n")
    far = body.replace("    x = 0\n", "    x = 0  # WALL-CLOCK: ok — far\n")
    (tmp_path / "near.py").write_text(near)
    (tmp_path / "far.py").write_text(far)
    assert [f.rule for f in NW.lint_file(str(tmp_path / "near.py"))] == []
    assert [f.rule for f in NW.lint_file(str(tmp_path / "far.py"))] == \
        ["wallclock-sleep"]


# =============================================================================
# THE CLI + THE BASELINE
# =============================================================================
def test_the_cli_exit_code_is_the_verdict():
    """A gate whose exit code does not carry the verdict is decoration —
    this repo has the toy-bad history to prove it."""
    assert run_cli(str(FIX / "clean.py")).returncode == 0
    assert run_cli(str(FIX / "sleeper.py")).returncode == 1


def test_a_baseline_grandfathers_and_only_that(tmp_path):
    base = tmp_path / "b.json"
    w = run_cli("--write-baseline", str(base), str(FIX / "sleeper.py"))
    assert w.returncode == 0, w.stderr
    assert len(json.loads(base.read_text())) == 4

    # Grandfathered -> clean.
    assert run_cli("--baseline", str(base), str(FIX / "sleeper.py")).returncode == 0
    # A NEW site in a file whose other sites are baselined must still fail.
    grown = tmp_path / "grown.py"
    grown.write_text((FIX / "sleeper.py").read_text() + "\n\ndef test_new(r):\n"
                     "    r.run_frames(9)\n")
    shifted = json.loads(base.read_text())
    for e in shifted:
        e["file"] = str(grown)
    (tmp_path / "b2.json").write_text(json.dumps(shifted))
    r = run_cli("--baseline", str(tmp_path / "b2.json"), str(grown))
    assert r.returncode == 1, "a NEW wall-clock site slipped past the baseline"
    assert "wallclock-run-frames" in r.stdout


def test_a_missing_baseline_is_an_error_not_a_pass(tmp_path):
    """Fails CLOSED. A gate that treats an absent baseline as "nothing to
    suppress" passes silently the day someone deletes it."""
    r = run_cli("--baseline", str(tmp_path / "nope.json"), str(FIX / "sleeper.py"))
    assert r.returncode == 2, r.stdout


def test_directory_expansion_skips_fixtures():
    """These fixtures are deliberately-violating Python and must never be
    scanned by the live gate — otherwise the gate can never be clean."""
    files = NW.expand([str(SUPERFORGE / "tests")])
    assert not any("fixtures" in f for f in files)
    assert any(f.endswith("test_no_wallclock.py") for f in files)


def test_a_docstring_mention_is_not_a_finding(tmp_path):
    """AST-based, deliberately. Half the raw-grep census on main was prose
    explaining why run_frames was removed — a gate that flags its own
    changelog gets ignored."""
    p = tmp_path / "m.py"
    p.write_text('"""This used to be run_frames(30) and time.sleep(1)."""\n'
                 "# run_seconds=2.0 was the old boot\n")
    assert NW.lint_file(str(p)) == []


def test_a_syntax_error_is_reported_not_swallowed(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("def f(:\n")
    assert [f.rule for f in NW.lint_file(str(p))] == ["syntax-error"]


# =============================================================================
# THE LIVE GATE
# =============================================================================
def test_make_time_check_is_clean_on_this_tree():
    """The gate as a human runs it. A baseline that has drifted away from the
    tree fails HERE, in a named test, instead of at someone's push."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    r = subprocess.run(["make", "time-check"], cwd=SUPERFORGE, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, \
        f"make time-check is not clean:\n{r.stdout}\n{r.stderr}"


# The plant lands in a NEW file rather than an existing module. `tests/*.py`
# is the gate's own scope, so a new file there is inside it — but a leading
# underscore keeps pytest from collecting it, so no xdist worker can be
# mid-collection on the file this test is writing. Mutating an existing test
# module would have made the plant race the suite.
_PLANT = SUPERFORGE / "tests" / "_planted_wallclock.py"


def test_the_gate_refuses_a_planted_violation(repo_tree_lock):
    """Trusting a green gate you have not tried to break is on the
    anti-pattern list. Plant a fresh wall-clock wait inside the gate's live
    scope and confirm the shipped baseline does not cover it."""
    assert not _PLANT.exists(), "a previous run left the plant behind"
    try:
        _PLANT.write_text("def planted(runner):\n    runner.run_frames(30)\n")
        r = run_cli("--baseline", "reports/time_lint_baseline.json",
                    "tests", "tools")
        assert r.returncode == 1, \
            "the live gate ACCEPTED a freshly planted run_frames — either " \
            "the baseline covers more than its entries, or the gate has no " \
            f"teeth:\n{r.stdout}"
        assert "_planted_wallclock.py" in r.stdout
        assert "wallclock-run-frames" in r.stdout
    finally:
        _PLANT.unlink(missing_ok=True)
    # ...and the restore really restored: the gate is clean again.
    assert run_cli("--baseline", "reports/time_lint_baseline.json",
                   "tests", "tools").returncode == 0


def test_the_gate_refuses_a_planted_bare_override(repo_tree_lock):
    """The other half: a stamp with no reason must not buy silence."""
    assert not _PLANT.exists(), "a previous run left the plant behind"
    try:
        _PLANT.write_text("def planted(runner):\n"
                          "    # WALL-CLOCK: ok\n"
                          "    runner.run_frames(30)\n")
        r = run_cli("--baseline", "reports/time_lint_baseline.json",
                    "tests", "tools")
        assert r.returncode == 1, r.stdout
        assert "bare-override" in r.stdout, r.stdout
        assert "wallclock-run-frames" in r.stdout, \
            "the bare stamp silenced the finding it sat on"
    finally:
        _PLANT.unlink(missing_ok=True)
