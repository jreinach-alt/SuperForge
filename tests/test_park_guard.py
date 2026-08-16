"""The parked-core guard in tests/conftest.py, tried against real violations.

AGENTS.md: "when you add a gate, prove it fails on a real violation before
believing it." The violation here is the one `make gates` actually hit: a
module parks the process-global Mesen core and finishes without resuming it,
and the NEXT module's fresh runner dies with *"the emulated frame counter has
not advanced for 30.0s... execution is PARKED in frame-stepping mode"* — a red
naming a module nobody touched.

Test surface (CLAUDE.md rule 2). Two surfaces, both the real thing:

  * the EMULATOR'S OWN STATE — `IsExecutionStopped()` on the process-global
    core, read across the whole cycle free-run -> parked -> resumed ->
    stopped. Not `_frame_stepping`, which is a per-instance flag documented
    to read stale-True after a timed-out `run_to_break`, and not any variable
    the guard itself maintains.
  * the PYTEST REPORT of a real subprocess run over real plant modules that
    boot a real ROM: which module the error is attributed to, and whether the
    innocent neighbour after it passed. The plants are not mocks — they park
    the core exactly the way the module it replaced did.

The plants live in a tmp dir with a conftest that re-exports THIS repo's
conftest, so the hooks under test are the shipped ones and cannot drift from
a copy.
"""
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

import conftest as guard                                        # noqa: E402
from mesen_runner import MesenRunner                             # noqa: E402

ROM = SUPERFORGE / "build" / "toy.sfc"

# A plant module's preamble: reach the real harness from anywhere on disk.
_PREAMBLE = f"""
import sys
sys.path.insert(0, {str(SUPERFORGE / "vendor")!r})
from mesen_runner import MesenRunner
ROM = {str(ROM)!r}
"""

# The violation: park, then finish holding the runner alive in a module global
# so even __del__ cannot rescue the core.
_PARKS_AND_LEAKS = _PREAMBLE + """
_held = None

def test_parks_and_never_resumes():
    global _held
    _held = MesenRunner()
    _held.load_rom(ROM, 1.0)
    _held.debug_break()
    _held.frame_step(1)
    # the emulator's own answer, not a flag: this module DID park it
    assert _held._lib.IsExecutionStopped()
"""

# The correct shape: park, resume, hand on.
_PARKS_AND_RESUMES = _PREAMBLE + """
_held = None

def test_parks_and_resumes():
    global _held
    _held = MesenRunner()
    _held.load_rom(ROM, 1.0)
    with _held.frame_stepping():
        _held.frame_step(1)
    # the machine, not a flag: it must be advancing again
    f0 = _held.ppu_frame_count()
    _held.wait_frames(10)
    assert _held.ppu_frame_count() > f0
"""

# The other correct shape, and the one that makes the guard cheap to leave on:
# an ordinary teardown. stop() resumes first, and leaves the core NOT stopped.
_PARKS_THEN_STOPS = _PREAMBLE + """
def test_parks_then_stops():
    r = MesenRunner()
    r.load_rom(ROM, 1.0)
    r.debug_break()
    r.frame_step(1)
    r.stop()
"""

# A module whose module-scoped fixture parks and THEN fails in teardown. The
# module is already red; the core must still be handed back, or the next
# module becomes a second victim of one bug.
_PARKS_THEN_TEARDOWN_RAISES = _PREAMBLE + """
import pytest

@pytest.fixture(scope="module")
def held():
    r = MesenRunner()
    r.load_rom(ROM, 1.0)
    yield r
    r.debug_break()
    r.frame_step(1)
    raise RuntimeError("teardown blew up after parking")

def test_uses_the_fixture(held):
    assert held.ppu_frame_count() >= 0
"""

# The innocent neighbour. wait_frames is the wall-of-shame call: on a parked
# core it is the one that raises the misleading 30 s stall.
_VICTIM = _PREAMBLE + """
def test_innocent_neighbour_sees_a_running_machine():
    r = MesenRunner()
    r.load_rom(ROM, 1.0)
    f0 = r.ppu_frame_count()
    r.wait_frames(20)
    assert r.ppu_frame_count() > f0, "the emulator did not advance"
    r.stop()
"""

# Re-export the SHIPPED conftest's hooks, so this exercises the real guard
# rather than a copy that can drift from it. Loaded by PATH under a distinct
# module name: a plain `from conftest import ...` inside a file that is itself
# named conftest.py imports ITSELF (observed — "partially initialized module").
_SHIM_CONFTEST = f"""
import importlib.util, sys
_spec = importlib.util.spec_from_file_location(
    "superforge_real_conftest", {str(SUPERFORGE / "tests" / "conftest.py")!r})
_real = importlib.util.module_from_spec(_spec)
sys.modules["superforge_real_conftest"] = _real
_spec.loader.exec_module(_real)

# Register the WHOLE module rather than re-exporting hooks by name. This block
# used to name three hooks, and the earlier DX change had to edit it the
# moment the map guard's hook changed shape (`pytest_collectstart` ->
# `pytest_make_collect_report` + `pytest_collection_modifyitems`, the item
# B). A shim that names hooks silently stops exercising the one you just
# added — which is the opposite of why this loads the shipped conftest at all.
def pytest_configure(config):
    config.pluginmanager.register(_real, "superforge_real_conftest")
"""


def _plant(tmp_path, **modules) -> Path:
    """Write a throwaway pytest tree; return its root."""
    root = tmp_path / "plants"
    root.mkdir()
    (root / "conftest.py").write_text(textwrap.dedent(_SHIM_CONFTEST))
    for name, src in modules.items():
        (root / f"{name}.py").write_text(textwrap.dedent(src))
    return root


def _run_pytest(root: Path, *names: str, env_extra=None) -> subprocess.CompletedProcess:
    """Run the plants in a SUBPROCESS — the core is per-process, so the plant
    must not park the core this very suite is running on."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    env.pop("PYTEST_CURRENT_TEST", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
         *[str(root / f"{n}.py") for n in names]],
        cwd=root, capture_output=True, text=True, env=env, timeout=300)


@pytest.fixture(scope="module")
def built_rom():
    assert ROM.exists(), f"{ROM} missing — run `make toy`"
    return ROM


# --------------------------------------------------------------------------
# the predicate, against the emulator's own state
# --------------------------------------------------------------------------

def test_core_is_parked_tracks_the_emulator_not_a_flag(built_rom):
    """Drive the whole cycle and read the core each time.

    free-run -> parked -> resumed -> stopped. The last one is the reason the
    guard can be left on always: an ordinary `stop()` leaves the core NOT
    stopped, so a well-behaved module is never a finding.
    """
    r = MesenRunner()
    try:
        r.load_rom(str(built_rom), 1.0)
        assert guard.core_is_parked() is False, "free-running core read parked"

        r.debug_break()
        assert guard.core_is_parked() is True, "parked core read free-running"

        r.frame_step(1)
        assert guard.core_is_parked() is True, "frame_step left it unparked?"

        r.debug_resume()
        assert guard.core_is_parked() is False, "resume did not clear the park"

        r.debug_break()
        assert guard.core_is_parked() is True
        r.stop()
        assert guard.core_is_parked() is False, (
            "stop() left the core parked — the guard would fire on every "
            "module with an ordinary teardown")
    finally:
        try:
            r.debug_resume()
        except Exception:
            pass
        r.stop()


def test_a_thread_pause_does_not_read_as_a_park(built_rom, monkeypatch):
    """The CI #612/#613 shape, PLANTED — a gate you have not broken is not a gate.

    Mesen's `IsExecutionStopped()` is `_executionStopped || IsThreadPaused()`
    (Core/Debugger/Debugger.cpp:738), and `IsThreadPaused()` is true inside any
    caller's `Lock()`/`Unlock()` window (Core/Shared/Emulator.cpp:876+895). So
    on a contended runner the flag reads TRUE for a healthy free-running core,
    which is how the guard called a free-running core PARKED twice in CI.

    The contention that produces it is not reproducible on demand, so plant the
    flag instead: force the disjunct true and leave the machine genuinely
    running. The predicate must still answer False, because it asks the
    MACHINE — and the machine is advancing.
    """
    r = MesenRunner()
    try:
        r.load_rom(str(built_rom), 1.0)
        lib = guard._mesen_core_lib()
        assert lib is not None, "no core loaded — nothing to plant into"

        monkeypatch.setattr(lib, "IsExecutionStopped", lambda: True,
                            raising=False)
        assert bool(lib.IsExecutionStopped()) is True, "the plant did not take"

        # The old predicate WAS this call, so this is the regression:
        t0 = time.time()
        verdict = guard.core_is_parked()
        elapsed = time.time() - t0
        assert verdict is False, (
            "a free-running core read PARKED with the thread-pause disjunct "
            "planted — core_is_parked() is reading the flag, not the machine")
        # ...and it must notice quickly, not sit out the whole confirm window:
        # the machine is producing scanlines continuously.
        assert elapsed < guard._PARK_CONFIRM_S, (
            f"took {elapsed:.3f}s to see a running machine; the confirm window "
            f"is {guard._PARK_CONFIRM_S}s and progress should end it at once")

        # The other direction, with the SAME plant in place: a genuinely
        # parked core must still be called parked. A predicate that answered
        # False here would have traded a false positive for a false negative,
        # which is the worse of the two — the guard exists to catch this.
        r.debug_break()
        r.frame_step(1)
        assert guard.core_is_parked() is True, (
            "a genuinely parked core read free-running — the frame/scanline "
            "confirmation is not discriminating")
    finally:
        try:
            r.debug_resume()
        except Exception:
            pass
        r.stop()


def test_unpark_repairs_a_parked_core(built_rom):
    """The repair arm: after `_unpark_core`, the machine demonstrably runs."""
    r = MesenRunner()
    try:
        r.load_rom(str(built_rom), 1.0)
        r.debug_break()
        r.frame_step(1)
        assert guard.core_is_parked() is True

        assert guard._unpark_core() is True
        assert guard.core_is_parked() is False
        f0 = r.ppu_frame_count()
        # The machine, not a flag: the PPU frame counter must move.
        r._frame_stepping = False
        r.wait_frames(10)
        assert r.ppu_frame_count() > f0
    finally:
        r.stop()


def test_no_emulator_no_check():
    """A session that never loads the core must not dlopen it to be told so.

    Read through `sys.modules`, so this is the honest question — but assert it
    against the shipped helper rather than by inspection.
    """
    saved = sys.modules.pop("mesen_runner", None)
    try:
        assert guard._mesen_core_lib() is None
        assert guard.core_is_parked() is False
    finally:
        if saved is not None:
            sys.modules["mesen_runner"] = saved


# --------------------------------------------------------------------------
# the guard, against a real leak, in a real pytest run
# --------------------------------------------------------------------------

def test_a_leaked_park_names_the_culprit_not_the_victim(tmp_path, built_rom):
    """The failure it replaced, reproduced — and re-attributed.

    Without the guard the VICTIM is the only red (proved by the companion
    test below). With it, the culprit module errors by name and the victim
    passes, because the guard repaired the core after reporting.
    """
    root = _plant(tmp_path, test_aa_parker=_PARKS_AND_LEAKS,
                  test_bb_victim=_VICTIM)
    r = _run_pytest(root, "test_aa_parker", "test_bb_victim")
    out = r.stdout + r.stderr

    assert "PARKED CORE" in out, out[-4000:]
    assert "test_aa_parker.py" in out, out[-4000:]
    # attributed to the culprit's teardown, as an ERROR
    assert "ERROR test_aa_parker.py" in out, out[-4000:]
    # and the innocent neighbour is NOT red
    assert "test_bb_victim" not in out.split("short test summary info")[-1], (
        "the victim was reported as failing:\n" + out[-4000:])
    assert "1 error" in out, out[-4000:]
    assert r.returncode != 0


def test_without_the_guard_the_victim_is_the_one_that_reds(tmp_path, built_rom):
    """The counterfactual, so the attribution claim above is not a tautology.

    Same two plants, guard disabled: the parker passes and the innocent
    neighbour dies on the 30 s stall naming ITSELF. This is the shape
    `make gates` reported, and the reason the guard exists.
    """
    root = _plant(tmp_path, test_aa_parker=_PARKS_AND_LEAKS,
                  test_bb_victim=_VICTIM)
    r = _run_pytest(root, "test_aa_parker", "test_bb_victim",
                    env_extra={"SF_NO_PARK_GUARD": "1"})
    out = r.stdout + r.stderr

    assert "PARKED CORE" not in out
    assert "has not advanced" in out, out[-4000:]
    assert "FAILED test_bb_victim.py" in out, out[-4000:]
    assert r.returncode != 0


def test_a_failing_teardown_does_not_get_to_keep_the_core(tmp_path, built_rom):
    """The exception path: the module is red for its own reason AND leaked a
    park. The park must still be repaired, and said out loud, so the next
    module is not a second victim of one bug."""
    root = _plant(tmp_path, test_ee_raiser=_PARKS_THEN_TEARDOWN_RAISES,
                  test_ff_victim=_VICTIM)
    r = _run_pytest(root, "test_ee_raiser", "test_ff_victim")
    out = r.stdout + r.stderr

    assert "teardown blew up after parking" in out, out[-4000:]
    assert "PARKED CORE: test_ee_raiser.py left the shared Mesen2 core " \
           "parked" in out, out[-4000:]
    assert "the guard resumed it" in out, out[-4000:]
    # the neighbour survives
    assert "has not advanced" not in out, out[-4000:]
    # the raiser's own test passed, its TEARDOWN errored, and the neighbour
    # ran normally: 2 passed + 1 error, not a cascade.
    assert "2 passed" in out and "1 error" in out, out[-4000:]


@pytest.mark.parametrize("src,label", [(_PARKS_AND_RESUMES, "resumes"),
                                       (_PARKS_THEN_STOPS, "stops")],
                         ids=["frame_stepping-ctxmgr", "park-then-stop"])
def test_a_module_that_hands_the_core_back_is_clean(tmp_path, built_rom,
                                                    src, label):
    """No false positive on either correct shape.

    A guard that fired on `with runner.frame_stepping():` or on an ordinary
    `stop()` would be deleted within a week — most of the suite parks.
    """
    root = _plant(tmp_path, **{f"test_cc_{label}": src,
                               "test_dd_victim": _VICTIM})
    r = _run_pytest(root, f"test_cc_{label}", "test_dd_victim")
    out = r.stdout + r.stderr
    assert "PARKED CORE" not in out, out[-4000:]
    assert "2 passed" in out, out[-4000:]
    assert r.returncode == 0
