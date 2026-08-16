"""tools/falsify.py's own tests — the harness that makes a no-op'd plant loud.

The harness exists because falsification plants silently no-op'd three times
once leaving its test GREEN. So the thing to prove here is not
"it can run a plant" — it is that each way a plant can FAIL to reach the
assertion produces its own named verdict, distinct from the test's own
verdict.

Most of this runs against a stubbed `make` / `pytest` so all six verdicts are
reachable in milliseconds. ONE test then drives the real thing end to end
against `make toy`, because a verdict machine that has never met a real build
is a design, not a gate.
"""
import shutil
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "tools"))

import falsify as FZ  # noqa: E402


# =============================================================================
# THE VERDICT MACHINE — every failure mode, against a stubbed build
# =============================================================================
@pytest.fixture
def stub(monkeypatch, tmp_path):
    """A fake build: `make` copies the target file into the artifact, so the
    artifact md5 tracks the source exactly. Every knob the harness reads is
    settable per test."""
    src = tmp_path / "src.asm"
    src.write_text("REAL_LINE\n")
    art = tmp_path / "art.sfc"
    state = {"build_ok": True, "build_out": "", "test_rc": 1,
             "test_out": "1 failed", "reaches": True}

    def fake_make(targets, root=None):
        if not state["build_ok"]:
            return False, state["build_out"]
        # `reaches=False` models a build that ignores the source edit — the
        # mtime-skip case, and any case where the plant misses the artifact.
        art.write_text(src.read_text() if state["reaches"] else "FIXED\n")
        return True, "ok"

    monkeypatch.setattr(FZ, "make", fake_make)
    monkeypatch.setattr(FZ, "run_tests",
                        lambda nodes, root=None: (state["test_rc"], state["test_out"]))
    return src, art, state


def plant(src, art, **kw):
    kw.setdefault("old", "REAL_LINE")
    kw.setdefault("new", "PLANTED")
    kw.setdefault("tests", ["tests/x.py::y"])
    return FZ.Plant(id="p", file=src, artifact=art, build=["x"],
                    why="a stub", **kw)


def test_a_plant_that_fires_is_FIRED(stub):
    src, art, _ = stub
    assert FZ.run_plant(plant(src, art), verbose=False).verdict == FZ.FIRED


def test_a_green_test_is_a_TEST_finding_not_a_pass(stub):
    src, art, state = stub
    state["test_rc"] = 0
    r = FZ.run_plant(plant(src, art), verbose=False)
    assert r.verdict == FZ.TEST_BLIND
    assert "cannot see it" in r.detail


def test_an_unchanged_artifact_is_a_PLANT_failure(stub):
    """THE SILENT-NO-OP FAILURE MODE. The source edit applied, the build ran, the
    binary did not move — so whatever the test says next is about the OLD
    binary. This must never be reported as a fired gate, and must never be
    reported as a hole in the test either."""
    src, art, state = stub
    state["reaches"] = False
    r = FZ.run_plant(plant(src, art), verbose=False)
    assert r.verdict == FZ.PLANT_NO_REACH
    assert "UNCHANGED" in r.detail
    assert r.verdict in FZ.PLANT_FAILURES


def test_the_tests_are_not_even_run_when_the_plant_did_not_reach(stub,
                                                                 monkeypatch):
    """Belt and braces: a green result from a stale binary is worse than no
    result, so the harness must not collect one."""
    src, art, state = stub
    state["reaches"] = False
    called = []
    monkeypatch.setattr(FZ, "run_tests",
                        lambda n, root=None: (called.append(n), (0, ""))[1])
    FZ.run_plant(plant(src, art), verbose=False)
    assert called == []


def test_a_missing_anchor_is_a_PLANT_failure(stub):
    src, art, _ = stub
    r = FZ.run_plant(plant(src, art, old="NOT_THERE"), verbose=False)
    assert r.verdict == FZ.PLANT_NOT_APPLIED


def test_a_no_op_patch_is_a_PLANT_failure(stub):
    src, art, _ = stub
    r = FZ.run_plant(plant(src, art, old="REAL_LINE", new="REAL_LINE"),
                     verbose=False)
    assert r.verdict == FZ.PLANT_NOT_APPLIED


def test_a_broken_build_is_a_PLANT_failure_for_a_test_red_plant(stub):
    src, art, state = stub

    calls = {"n": 0}
    real = FZ.make

    def flaky(targets, root=None):
        calls["n"] += 1
        if calls["n"] == 2:            # baseline ok, planted build breaks
            return False, "ca65: Error: boom"
        return real(targets, root)
    FZ.make = flaky
    try:
        r = FZ.run_plant(plant(src, art), verbose=False)
    finally:
        FZ.make = real
    assert r.verdict == FZ.PLANT_BROKE_BUILD


def test_a_red_baseline_is_refused_before_anything_is_planted(stub):
    src, art, state = stub
    state["build_ok"] = False
    r = FZ.run_plant(plant(src, art), verbose=False)
    assert r.verdict == FZ.BASELINE_RED
    assert src.read_text() == "REAL_LINE\n", "the file was touched anyway"


def test_a_build_fails_plant_needs_the_error_to_NAME_the_defect(stub):
    """"The build broke" does not demonstrate the gate saw anything."""
    src, art, state = stub
    state["build_ok"] = False
    state["build_out"] = "ca65: Error: something unrelated"

    calls = {"n": 0}
    real = FZ.make

    def two_phase(targets, root=None):
        calls["n"] += 1
        if calls["n"] == 1 or calls["n"] == 3:      # baseline + restore
            state["build_ok"] = True
            return real(targets, root)
        state["build_ok"] = False
        return False, "ca65: Error: something unrelated"
    FZ.make = two_phase
    try:
        r = FZ.run_plant(plant(src, art, tests=[], expect="build-fails",
                               build_names="must define FOO"), verbose=False)
    finally:
        FZ.make = real
    assert r.verdict == FZ.PLANT_WRONG_ERROR


def test_a_build_that_ACCEPTS_a_build_fails_plant_is_a_hole(stub):
    src, art, _ = stub
    r = FZ.run_plant(plant(src, art, tests=[], expect="build-fails",
                           build_names="must define FOO"), verbose=False)
    assert r.verdict == FZ.TEST_BLIND


def test_a_failed_restore_overrides_the_verdict(stub, monkeypatch):
    """A harness that reports FIRED while leaving the tree planted is the
    worst outcome available — the next person's red is inherited."""
    src, art, state = stub
    real_write = FZ.write_now
    seen = {"n": 0}

    def wedge(path, text):
        seen["n"] += 1
        if seen["n"] == 2:                 # the restore write
            return                          # ...silently does nothing
        real_write(path, text)
    monkeypatch.setattr(FZ, "write_now", wedge)
    r = FZ.run_plant(plant(src, art), verbose=False)
    assert r.verdict == FZ.RESTORE_BAD
    assert "TREE MAY BE DIRTY" in r.detail


def test_the_file_is_restored_by_copy_after_a_normal_run(stub):
    src, art, _ = stub
    FZ.run_plant(plant(src, art), verbose=False)
    assert src.read_text() == "REAL_LINE\n"


def test_write_now_stamps_mtime_forward(tmp_path):
    """The fix for the copy2 case: an mtime-preserving swap makes `make` a
    no-op, and the plant then tests the OLD binary."""
    import os
    p = tmp_path / "f"
    p.write_text("a")
    os.utime(p, (1, 1))
    FZ.write_now(p, "b")
    assert p.stat().st_mtime > 1000, "write_now did not move the mtime"


def test_a_plant_without_a_why_is_refused(tmp_path):
    """`why` is required. A plant whose realism nobody stated proves little,
    and the summary prints it beside every finding."""
    with pytest.raises(ValueError):
        FZ.Plant(id="p", file=tmp_path / "f", artifact=tmp_path / "a",
                 build=["x"], why="", old="a", new="b", tests=["t"])


# =============================================================================
# THE REAL THING — one end-to-end run against `make toy`
# =============================================================================
def test_a_comment_only_edit_is_caught_as_PLANT_DID_NOT_REACH(
        tmp_path, repo_tree_read_lock):
    """End to end, against the real build.

    A comment-only edit to a real source file is the honest miniature of the
    bug: the source visibly changed, `make` runs, and the ARTIFACT is
    byte-identical — so any verdict drawn from the tests afterwards would be
    about the unplanted binary. The harness must name that, and must leave
    the tree exactly as it found it.

    IN A COPIED SANDBOX, not the live tree. The first version of this test
    ran `make toy` in the repo, and under `make test XDIST=4` that rebuilt
    `build/toy.sfc` while another worker was loading it — six errors in
    test_toy_boot.py, all reading "the emulated frame counter has not
    advanced (frozen at frame 0)" and every one of them attributed to the
    VICTIM. Caught by `make bare-check`, which is what that gate is for.
    `Plant.root` exists because of this.
    """
    root = tmp_path / "repo"
    root.mkdir()
    with repo_tree_read_lock():
        for item in ("Makefile", "allocator", "engine", "vendor/rom", "tools"):
            src = SUPERFORGE / item
            dst = root / item
            dst.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)

    target = root / "engine" / "toy" / "main.asm"
    assert target.exists(), "sandbox is missing engine/toy/main.asm"
    before = target.read_text()
    anchor = before.splitlines()[0]
    p = FZ.Plant(
        id="e2e-comment-only", file=target,
        artifact=root / "build" / "toy.sfc", build=["toy"], root=root,
        old=anchor, new=anchor + "\n; PLANT: a comment, which emits no bytes",
        tests=["tests/test_toy_boot.py"],
        why="a comment emits no bytes, so the ROM cannot move — the "
            "miniature of an mtime-skipped rebuild")
    r = FZ.run_plant(p, verbose=False)
    assert r.verdict == FZ.PLANT_NO_REACH, (
        f"expected the harness to notice the ROM did not move, got "
        f"{r.verdict}: {r.detail}")
    assert target.read_text() == before, "the harness did not restore the file"


def test_the_e2e_sandbox_never_touches_the_live_build(tmp_path):
    """The companion assertion to the one above: `Plant.root` must actually
    redirect `make`. If it silently fell back to SUPERFORGE, the test above would
    still pass — and would still be corrupting another worker's ROM."""
    seen = []
    real = FZ.subprocess.run

    def spy(cmd, **kw):
        seen.append((cmd, kw.get("cwd")))
        return real(["true"], capture_output=True, text=True)
    FZ.subprocess.run = spy
    try:
        FZ.make(["toy"], tmp_path)
        FZ.run_tests(["tests/x.py"], tmp_path)
    finally:
        FZ.subprocess.run = real
    assert [cwd for _, cwd in seen] == [tmp_path, tmp_path], seen
