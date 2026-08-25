"""The suite's own schedule record — what ran where, in what order.

`tests/conftest.py`'s "the worker schedule record" block writes one JSON row
per test module: the worker that ran it, its position in that worker's
sequence, the window it occupied, and the state the shared Mesen core was in
when it handed on. This module proves the record is TRUE, because a schedule
that is merely plausible is worse than none — an investigation would spend
its budget chasing an adjacency that never happened.

Every case here runs a REAL pytest session against the REAL conftest in a
subprocess and reads the file that session wrote. Nothing is asserted against
a hand-built dict: the row shapes come out of the hooks, in a session, in the
order a session put them — which is the only claim the record makes.

No emulator is involved and none is needed: the record's subject is pytest's
own scheduling, and the core-state fields degrade to "unloaded" (asserted
below) when nothing imported `mesen_runner`. That is what lets this module
run at full speed and stay honest about what it covers.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
CONFTEST = SUPERFORGE / "tests" / "conftest.py"

# Two modules, three tests, one deliberate red. The red is load-bearing: a
# record that cannot tell a victim from a bystander cannot name a neighbour.
MOD_A = """\
def test_a_one(): pass
def test_a_two(): pass
"""

MOD_B = """\
def test_b_one(): pass
def test_b_fails(): assert False, "planted"
"""

MOD_C = """\
def test_c_one(): pass
"""


def _session(tmp_path, mods, extra_args=(), env_extra=None):
    """Run a real pytest session over `mods` and return the rows it wrote.

    The repo's own `tests/conftest.py` is COPIED in rather than imported, so
    the hooks under test are registered by pytest exactly as they are in a
    real run. `SF_SCHEDULE_LOG` pins the output away from `build/` so a
    session here can never overwrite the record of the run that is
    investigating it.
    """
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    shutil.copy(CONFTEST, work / "conftest.py")
    for name, text in mods.items():
        (work / name).write_text(text)
    log = tmp_path / "schedule.jsonl"
    env = dict(os.environ)
    # A fresh session must not inherit THIS session's xdist identity, or every
    # row it writes would claim the parent's worker and run id.
    # ...nor its ownership of the schedule file: a session that inherited it
    # would correctly refuse to record (that refusal is its own case below),
    # and every assertion here would then be about an empty file.
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_TESTRUNUID",
              "SF_SCHEDULE_RUN_ID", "SF_SCHEDULE_OWNER", "PYTEST_CURRENT_TEST"):
        env.pop(k, None)
    env["SF_SCHEDULE_LOG"] = str(log)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         *extra_args, *sorted(mods)],
        cwd=work, capture_output=True, text=True, env=env)
    rows = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()] \
        if log.exists() else []
    return proc, rows, log


# --------------------------------------------------------------------------
# what a row says
# --------------------------------------------------------------------------

def test_serial_run_records_every_module_in_execution_order(tmp_path):
    """The record's headline claim: module order, as the session ran it."""
    proc, rows, _ = _session(
        tmp_path, {"test_a.py": MOD_A, "test_b.py": MOD_B, "test_c.py": MOD_C})
    assert proc.returncode == 1, proc.stdout          # the planted red
    assert [r["module"] for r in rows] == \
        ["test_a.py", "test_b.py", "test_c.py"], rows
    assert [r["seq"] for r in rows] == [0, 1, 2], rows
    assert {r["worker"] for r in rows} == {"main"}, rows
    assert all(r["pid"] == rows[0]["pid"] for r in rows), rows


def test_a_row_names_the_reds_inside_its_own_module(tmp_path):
    """A victim module must be identifiable from the record alone.

    Without this the file says which modules ran and stays silent about which
    one went red — and the neighbour question is only ever asked ABOUT a red.
    """
    _, rows, _ = _session(
        tmp_path, {"test_a.py": MOD_A, "test_b.py": MOD_B})
    by_mod = {r["module"]: r for r in rows}
    assert by_mod["test_a.py"]["failed"] == 0
    assert "failed_tests" not in by_mod["test_a.py"]
    assert by_mod["test_b.py"]["failed"] == 1
    assert by_mod["test_b.py"]["failed_tests"] == ["test_b_fails"]
    assert by_mod["test_a.py"]["tests"] == 2
    assert by_mod["test_b.py"]["tests"] == 2


def test_rows_carry_a_window_that_can_be_overlapped(tmp_path):
    """`t_start`/`t_end` exist and are ordered — the cross-worker axis.

    Same-worker adjacency is `seq`; CONCURRENT adjacency (two workers in one
    `build/`, two `make` subprocesses, one repo tree) is only reconstructible
    from the windows. Both mechanisms are real here, so the record carries
    both. Only the ordering is asserted — a duration is a property of the box,
    not of the record.
    """
    _, rows, _ = _session(
        tmp_path, {"test_a.py": MOD_A, "test_b.py": MOD_B, "test_c.py": MOD_C})
    for r in rows:
        assert r["t_start"] is not None and r["t_end"] is not None, r
        assert r["t_end"] >= r["t_start"], r
    # serial: each module's window opens no earlier than the previous closed
    for prev, cur in zip(rows, rows[1:]):
        assert cur["t_start"] >= prev["t_start"], (prev, cur)


def test_core_state_degrades_honestly_when_no_emulator_loaded(tmp_path):
    """No `mesen_runner` in the process => "unloaded", not a fabricated value.

    The whole record is only worth reading if its core-state fields mean what
    they say. A row that reported `stopped_flag: false` for a process that
    never loaded a core would read as "the core was healthy" — a claim nobody
    measured.
    """
    _, rows, _ = _session(tmp_path, {"test_a.py": MOD_A})
    assert rows[0]["core"] == "unloaded", rows[0]
    assert "stopped_flag" not in rows[0] and "frame" not in rows[0], rows[0]
    assert "machine_current" not in rows[0], rows[0]
    # the park guard ran (it is on by default) and confirmed a not-parked core
    assert rows[0]["parked"] is False, rows[0]


def test_park_verdict_is_unknown_rather_than_false_when_the_guard_is_off(
        tmp_path):
    """`SF_NO_PARK_GUARD` means nobody paid for the confirmation.

    `core_is_parked()` costs up to 0.75 s per boundary when the stopped flag
    is set, so the record does not call it a second time and does not call it
    when the guard is disabled. What it must NOT do is record the absence of a
    measurement as a measurement of absence.
    """
    _, rows, _ = _session(tmp_path, {"test_a.py": MOD_A},
                          env_extra={"SF_NO_PARK_GUARD": "1"})
    assert rows[0]["parked"] is None, rows[0]


# --------------------------------------------------------------------------
# the properties that make it readable after the fact
# --------------------------------------------------------------------------

def test_each_run_truncates_the_file_so_rows_are_one_run(tmp_path):
    """Two sessions, one path: the second must not be read as the first's tail.

    A file that appends forever makes every reader start by finding where the
    current run began — the archaeology the record exists to abolish.
    """
    _, rows1, log = _session(tmp_path, {"test_a.py": MOD_A, "test_c.py": MOD_C})
    assert len(rows1) == 2
    _, rows2, log2 = _session(tmp_path, {"test_a.py": MOD_A})
    assert log2 == log
    assert [r["module"] for r in rows2] == ["test_a.py"], rows2
    assert rows2[0]["run"] != rows1[0]["run"], (rows1[0], rows2[0])


def test_a_nested_session_cannot_clobber_the_owner_record(tmp_path):
    """The evidence-destroying case, asserted directly.

    Several modules here start a pytest of their own and load this conftest
    into it on purpose (`test_park_guard.py`, `test_map_freshness_guard.py`).
    Those sessions inherit the outer run's environment. If they recorded,
    they would truncate the record of the run investigating them — mid-suite,
    in the one file nobody would suspect. So: a session that finds an owner
    already claimed must write NOTHING, and must still run its tests.
    """
    _, rows, log = _session(tmp_path, {"test_a.py": MOD_A, "test_c.py": MOD_C})
    assert [r["module"] for r in rows] == ["test_a.py", "test_c.py"]
    before = log.read_text()

    # Now re-run as if from inside that owner: an inherited owner pid that is
    # neither us nor our parent is exactly what a nested session sees.
    work = tmp_path / "work"
    env = dict(os.environ)
    env.update(SF_SCHEDULE_LOG=str(log), SF_SCHEDULE_OWNER="1")
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_TESTRUNUID"):
        env.pop(k, None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
         "test_a.py"], cwd=work, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout      # it still RAN the tests
    assert log.read_text() == before, "a nested session rewrote the record"


def test_the_record_can_be_turned_off(tmp_path):
    """`SF_NO_SCHEDULE_LOG` writes nothing and changes no verdict."""
    proc, rows, log = _session(
        tmp_path, {"test_a.py": MOD_A, "test_b.py": MOD_B},
        env_extra={"SF_NO_SCHEDULE_LOG": "1"})
    assert rows == []
    assert not log.exists() or log.read_text() == ""
    assert proc.returncode == 1, proc.stdout   # the planted red still reds


def test_every_line_is_one_whole_json_object(tmp_path):
    """Rows are appended from concurrent processes; none may tear.

    The write is a single `os.write` on an O_APPEND fd, far under PIPE_BUF.
    Parsing every line strictly is the check that holds that property.
    """
    _, rows, log = _session(
        tmp_path, {"test_a.py": MOD_A, "test_b.py": MOD_B, "test_c.py": MOD_C},
        extra_args=("-n", "2"))
    text = log.read_text()
    assert text.endswith("\n")
    for ln in text.splitlines():
        assert isinstance(json.loads(ln), dict)
    assert len(rows) == 3


# --------------------------------------------------------------------------
# the case it was built for
# --------------------------------------------------------------------------

def test_xdist_rows_name_the_worker_and_number_within_it(tmp_path):
    """Under `-n 2` the record must answer "what ran before this, HERE?".

    A module's neighbours are the modules that shared its PROCESS: the Mesen
    core is a process-global singleton, so `gw0`'s park cannot reach `gw1`.
    A `seq` that counted across workers, or a row that did not say which
    worker it came from, would merge two independent histories into one
    fictional order — and every adjacency read out of it would be invented.
    """
    mods = {f"test_m{i}.py": MOD_C.replace("test_c_one", f"test_m{i}")
            for i in range(6)}
    _, rows, _ = _session(tmp_path, mods, extra_args=("-n", "2"))
    assert len(rows) == 6, rows
    workers = {r["worker"] for r in rows}
    assert workers <= {"gw0", "gw1"} and workers, rows
    # per-worker seq is dense from 0 — the process's own history, not a
    # slice of a shared counter
    for w in workers:
        seqs = sorted(r["seq"] for r in rows if r["worker"] == w)
        assert seqs == list(range(len(seqs))), (w, rows)
    # one pid per worker, and distinct across workers
    pids = {r["worker"]: {r2["pid"] for r2 in rows if r2["worker"] == r["worker"]}
            for r in rows}
    assert all(len(v) == 1 for v in pids.values()), pids
    assert len({next(iter(v)) for v in pids.values()}) == len(workers), pids
    # every row of one run shares the run id xdist stamps
    assert len({r["run"] for r in rows}) == 1, rows


def test_predecessors_are_recoverable_for_a_red_module(tmp_path):
    """The end-to-end claim, stated as the question an investigation asks.

    Given a red module, the record must hand back the modules that ran before
    it in the SAME process. This is the whole deliverable: the reproduction
    step replays exactly this list.
    """
    mods = {f"test_m{i}.py": MOD_C.replace("test_c_one", f"test_m{i}")
            for i in range(5)}
    mods["test_zred.py"] = MOD_B
    _, rows, _ = _session(tmp_path, mods, extra_args=("-n", "2"))
    red = [r for r in rows if r["failed"]]
    assert len(red) == 1 and red[0]["module"] == "test_zred.py", rows
    same_worker = [r for r in rows
                   if r["worker"] == red[0]["worker"] and r["seq"] < red[0]["seq"]]
    predecessors = [r["module"] for r in sorted(same_worker,
                                                key=lambda r: r["seq"])]
    # every predecessor is a real module of this session, in this worker only
    assert set(predecessors) <= set(mods) - {"test_zred.py"}, predecessors
    assert len(predecessors) == red[0]["seq"], (predecessors, red[0])


# --------------------------------------------------------------------------
# a module runs in ONE process
# --------------------------------------------------------------------------
#
# The defect this pair pins: xdist's default `--dist load` hands out
# INDIVIDUAL TESTS, so a module whose later test reads what an earlier test
# wrote fails whenever the scheduler puts them on different workers — while
# the test that WROTE the state passes, on the other worker. That is the
# shape of `test_measure_cpu.py`'s `RESULTS` dict and of
# `test_measure_vblank.py`'s "single sweep ran first". Both pass in
# isolation, because a serial run cannot split anything.

# The failing shape, reduced: state written by earlier tests, read by a later
# one. Padding modules give the scheduler something to interleave.
MOD_STATE = """\
RESULTS = {}
def test_fills_a(): RESULTS["a"] = 1
def test_fills_b(): RESULTS["b"] = 2
def test_reads_what_the_others_wrote():
    assert "a" in RESULTS and "b" in RESULTS, f"RESULTS={RESULTS}"
"""


def _state_module_session(tmp_path, env_extra=None):
    mods = {"test_state.py": MOD_STATE}
    mods.update({f"test_pad{i}.py": f"def test_p{i}_1(): pass\n"
                                    f"def test_p{i}_2(): pass\n"
                 for i in range(12)})
    return _session(tmp_path, mods, extra_args=("-n", "2"),
                    env_extra=env_extra)


def test_a_module_is_not_split_across_workers(tmp_path):
    """The fix, asserted on the OUTPUT that matters: it does not go red.

    `tests/conftest.py` pins `--dist loadfile` so every test of a file lands
    in one process. Both halves are asserted — the module is whole AND the
    session is green — because "whole" is the mechanism and "green" is the
    thing anyone cares about.
    """
    proc, rows, _ = _state_module_session(tmp_path)
    assert proc.returncode == 0, proc.stdout
    state = [r for r in rows if r["module"] == "test_state.py"]
    assert len(state) == 1, f"module ran on {len(state)} workers: {state}"
    assert state[0]["tests"] == 3 and state[0]["failed"] == 0, state
    # ...and the run is still genuinely parallel: loadfile distributes FILES,
    # and a suite with one file per worker is not a suite worth parallelising.
    assert len({r["worker"] for r in rows}) == 2, rows


def test_the_default_scheduler_really_does_break_it(tmp_path):
    """The sensitivity control: put `--dist load` back, watch it fail.

    Without this, the case above proves only that a session passed — it
    cannot tell "the pin works" from "this shape never split anyway". The
    escape hatch exists for exactly this: it is the plant, and the plant must
    reproduce the defect the pin removes.

    Asserted as a DISJUNCTION over runs rather than once, because the split is
    the scheduler's timing choice — measured at 37 of 40 on this shape, so a
    single run is a coin the wrong way up about 1 time in 13, and five runs
    make that ~1 in 380,000. If this ever stops reproducing, the pin above
    stops being evidence and this file should say so loudly.
    """
    for _ in range(5):
        proc, rows, _ = _state_module_session(
            tmp_path, env_extra={"SF_XDIST_DIST": "load"})
        state = [r for r in rows if r["module"] == "test_state.py"]
        if len(state) > 1:
            assert proc.returncode != 0, (
                "the module SPLIT across workers and the session still "
                "passed — the reduced shape no longer reproduces the defect, "
                "so test_a_module_is_not_split_across_workers proves nothing")
            assert sum(r["failed"] for r in state) == 1, state
            return
    pytest.fail(
        "`--dist load` did not split a 3-test state-carrying module in 5 "
        "runs beside 24 fast tests; measured at 37/40 when this landed. The "
        "control has gone quiet — re-derive it before trusting the pin.")


def test_the_makefile_passes_loadfile_and_checks_it_afterwards():
    """The pin lives on the command line, and is VERIFIED, not trusted.

    Two separate claims, because a flag alone would be a claim about the run
    rather than a fact about it: `PYTEST_DIST` carries `--dist loadfile`, and
    the `test` recipe runs the post-suite check that reads what the scheduler
    actually did.
    """
    mk = (SUPERFORGE / "Makefile").read_text()
    assert "--dist loadfile" in mk, "PYTEST_DIST lost its loadfile pin"
    assert "schedule_summary.py $(BUILD)/worker_schedule.jsonl --check" in mk, \
        "the `test` recipe no longer checks the schedule after the suite"


@pytest.mark.parametrize("rows,expect_rc,expect_in_output", [
    # a clean parallel run
    ([{"worker": "gw0", "seq": 0, "module": "a.py", "failed": 0},
      {"worker": "gw1", "seq": 0, "module": "b.py", "failed": 0}], 0, "ok"),
    # a split — must FAIL and must NAME the module
    ([{"worker": "gw0", "seq": 0, "module": "a.py", "failed": 0},
      {"worker": "gw1", "seq": 0, "module": "a.py", "failed": 1}], 1, "a.py"),
    # nothing recorded — must PASS but say so, never a silent ok
    ([], 0, "NOTHING TO CHECK"),
])
def test_the_post_suite_check_fails_only_on_a_real_split(
        rows, expect_rc, expect_in_output, tmp_path, capsys):
    """The durable invariant, at its three outcomes.

    The middle case is the regression fixture for the whole defect: if the
    suite ever goes back to test-level distribution, THIS is what turns it
    into a named red instead of an intermittent one. The third case is why
    the check prints its scope — a disarmed check must read as disarmed.
    """
    sys.path.insert(0, str(SUPERFORGE / "tools"))
    from schedule_summary import check_schedule                # noqa: E402
    src = tmp_path / "s.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rc = check_schedule(src)
    out = capsys.readouterr().out
    assert rc == expect_rc, out
    assert expect_in_output in out, out


def test_the_summariser_names_a_split(tmp_path):
    """If the pin ever comes off, the artifact must say so by name."""
    sys.path.insert(0, str(SUPERFORGE / "tools"))
    from schedule_summary import summarise_schedule    # noqa: E402
    rows = [
        {"worker": "gw0", "seq": 0, "module": "m.py", "failed": 0},
        {"worker": "gw1", "seq": 0, "module": "m.py", "failed": 1},
        {"worker": "gw1", "seq": 1, "module": "whole.py", "failed": 0},
    ]
    src = tmp_path / "s.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = summarise_schedule(src)
    assert out["split_modules"] == {"m.py": ["gw0", "gw1"]}
    assert "whole.py" not in out["split_modules"]
    assert "loadfile" in out["split_note"]


# --------------------------------------------------------------------------
# the gate surface
# --------------------------------------------------------------------------

def test_bare_check_embeds_the_schedule_summary():
    """The landing gate must carry the schedule, or the next RED re-does this.

    `tools/bare_check.sh` deletes its clone on green, so a file left in the
    clone's `build/` is not evidence — the summary has to reach
    `build/bare_check.json`, which outlives the run. This asserts the wiring
    exists at all; what it contains is `summarise_schedule`'s subject above.
    """
    src = (SUPERFORGE / "tools" / "bare_check.sh").read_text()
    assert "worker_schedule.jsonl" in src
    assert "suite_schedule" in src


@pytest.mark.parametrize("rows,expect_workers", [
    ([], 0),
    ([{"worker": "gw0", "seq": 0, "module": "a.py", "failed": 0}], 1),
])
def test_summariser_survives_a_thin_or_empty_record(rows, expect_workers,
                                                    tmp_path):
    """The gate summariser must not be a second way for a run to fail.

    A crashed worker leaves a truncated record (its last module has no row —
    the stated limit in the conftest block). The summariser reads whatever is
    there and says so; it never raises.
    """
    sys.path.insert(0, str(SUPERFORGE / "tools"))
    from schedule_summary import summarise_schedule    # noqa: E402
    src = tmp_path / "s.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = summarise_schedule(src)
    assert isinstance(out, dict)
    assert len(out.get("workers", {})) == expect_workers, out


def test_summariser_names_the_neighbours_of_a_red(tmp_path):
    """What the artifact is FOR: a red arrives with its predecessors attached."""
    sys.path.insert(0, str(SUPERFORGE / "tools"))
    from schedule_summary import summarise_schedule    # noqa: E402
    rows = [
        {"worker": "gw0", "seq": 0, "module": "p0.py", "failed": 0},
        {"worker": "gw1", "seq": 0, "module": "q0.py", "failed": 0},
        {"worker": "gw0", "seq": 1, "module": "p1.py", "failed": 0},
        {"worker": "gw0", "seq": 2, "module": "red.py", "failed": 2,
         "failed_tests": ["test_x", "test_y"]},
    ]
    src = tmp_path / "s.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = summarise_schedule(src)
    assert out["workers"]["gw0"] == ["p0.py", "p1.py", "red.py"]
    assert out["workers"]["gw1"] == ["q0.py"]
    red = out["red_modules"]
    assert len(red) == 1
    assert red[0]["module"] == "red.py"
    assert red[0]["worker"] == "gw0"
    # the predecessors, nearest first — the replay order for the pair hunt
    assert red[0]["predecessors"] == ["p1.py", "p0.py"]
    assert red[0]["failed_tests"] == ["test_x", "test_y"]
