"""The repo-tree lock's READER side, proven in both directions.

`tests/conftest.py` serialises the two modules that PLANT into this repo's
working tree behind an exclusive `fcntl` lock. That closed planter-vs-planter.
It left planter-vs-READER open: three modules `copytree` the live
`engine/features/` tree at test time and allocate from what they copied, so a
copy taken mid-plant captures the plant and allocates differently than its test
expects. Single-threaded CI could not reach that; the `-n 2` flip can. Filed as
A recorded finding. fixed by giving those readers a
SHARED lock over exactly their copy.

WHY THIS TEST EXISTS RATHER THAN A CI SOAK. The race is real but rare — the
plant windows are ~0.3-1 s inside a ~205 s suite — which is precisely the
profile the audit called "appears once a quarter and is diagnosed as flake". A
test that runs the suite in parallel and hopes to catch it proves nothing when
it passes. So the interleave is BUILT instead of waited for: a probe subprocess
takes the exclusive lock, plants, and HOLDS, while a reader tries to copy. The
two directions are then decidable rather than probabilistic —

  * WITHOUT the shared lock the reader proceeds and its copy CONTAINS the
    plant (`test_an_unlocked_reader_copies_the_plant`). That is the bug,
    reproduced on demand, and it is also this file's non-vacuity control: it
    proves the probe really does present an observable plant, so the paired
    test below cannot pass by failing to plant anything.
  * WITH it (the production fixture, called exactly as the three readers call
    it) the reader BLOCKS until the planter restores and releases, and its copy
    is CLEAN (`test_the_shared_lock_makes_the_reader_wait_for_a_clean_tree`).

The plant is a new `engine/features/zz_lockprobe_<pid>_<n>/` directory, the same
shape as `test_register.py`'s `planted_dir`, and "did the reader see it" is
answered by looking IN THE COPY — the reader's actual output — not at a flag or
a clock. Both tests remove it in `finally`, and it is untracked, so a leak shows
up in `git status` rather than silently altering a tracked file.

This module is itself a planter: the probe takes the same `LOCK_EX` on the same
lock file the real planters take, so it is mutually exclusive with them by the
same mechanism, and needs no separate coordination.
"""
import itertools
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import REPO_TREE_LOCK

SUPERFORGE = Path(__file__).resolve().parent.parent
FEATURES = SUPERFORGE / "engine" / "features"

# Every probe gets its OWN plant directory. The obvious single fixed path is
# wrong under `-n`: this module's own tests can land in different xdist
# workers, and the fixture's pre-emptive cleanup runs BEFORE its probe takes
# the lock — so a shared path lets one test's setup delete another test's
# live plant out from under it while that one still holds LOCK_EX. Caught by
# running this file's own proof shape at `-n 3`, where the unlocked reader
# then found nothing to capture and red. pid + counter is enough: xdist
# workers are processes, and within one process the tests are sequential.
_PLANT_SEQ = itertools.count()


def _plant_path():
    return FEATURES / f"zz_lockprobe_{os.getpid()}_{next(_PLANT_SEQ)}"

# How long the probe holds the plant while the reader tries to get in. Long
# enough that a reader which does NOT block finishes well inside it (the copy
# is 57 files / ~500 KB, ~10 ms), short enough that both tests together cost
# about a second.
HOLD_S = 0.6

# The probe. Takes the exclusive lock, plants, says so, then waits for a line
# on stdin before restoring and releasing — so the parent decides when the
# window closes and nothing here depends on a sleep matching a sleep.
#
# Restore-then-release is the planters' real ordering (their `finally` runs
# inside the fixture's yield), so a reader that waits correctly is guaranteed a
# clean tree rather than merely a later one.
#
# If the parent dies, stdin closes, `readline()` returns '' and the probe
# cleans up anyway; the alarm is the backstop for a parent that hangs while
# holding the pipe open, so a broken test can never wedge the suite behind a
# permanently-held exclusive lock.
#
# The planted `name` is DERIVED from the directory rather than fixed. The
# allocator requires the two to agree (`allocator/schemas.py:783-786`,
# "features are loaded by directory name"), so a fixed `name = "zz_lockprobe"`
# under a per-probe `zz_lockprobe_<pid>_<n>/` directory makes `load_feature`
# RAISE for every consumer that globs the live features dir while the probe
# holds — turning a tolerable extra neighbour into a hard red for the readers
# this suite deliberately does NOT lock (`test_reg_gate`, `test_reg_ownership`,
# the `make` fixtures). Measured co-scheduled at `-n 3`: 10/10 red with the
# fixed name, 0/10 with this one. A recorded finding.
PROBE = r"""
import fcntl, os, shutil, signal, sys
lock_path, plant_dir = sys.argv[1], sys.argv[2]
signal.alarm(60)
with open(lock_path, "w") as fh:
    fcntl.flock(fh, fcntl.LOCK_EX)
    try:
        os.mkdir(plant_dir)
        with open(os.path.join(plant_dir, "feature.toml"), "w") as f:
            f.write('name = "%s"\nrole = "feature"\n' % os.path.basename(plant_dir))
        sys.stdout.write("PLANTED\n")
        sys.stdout.flush()
        sys.stdin.readline()
    finally:
        shutil.rmtree(plant_dir, ignore_errors=True)
        fcntl.flock(fh, fcntl.LOCK_UN)
sys.stdout.write("RELEASED\n")
sys.stdout.flush()
"""


class Probe:
    """A held plant: `.name` to look for in a copy, `.release()` to end it."""

    def __init__(self, proc, plant):
        self._proc, self.plant, self.name = proc, plant, plant.name

    def release(self):
        self._proc.stdin.write("go\n")
        self._proc.stdin.flush()
        assert self._proc.stdout.readline().strip() == "RELEASED"
        self._proc.wait(timeout=10)


@pytest.fixture
def planting_probe():
    """A subprocess holding LOCK_EX with a plant on disk. Yields a `Probe`.

    The plant is on disk and confirmed before the fixture hands control back,
    so a test body never has to wait for it to appear.
    """
    plant = _plant_path()
    proc = subprocess.Popen(
        [sys.executable, "-c", PROBE, str(REPO_TREE_LOCK), str(plant)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "PLANTED", (
            "the probe never reported a plant — it may have failed to take "
            "the lock or to create the directory")
        assert plant.is_dir(), (
            f"the probe said PLANTED but {plant} does not exist — the test "
            "below would prove nothing")
        yield Probe(proc, plant)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        # Belt and braces: the probe removes its own plant, but a killed probe
        # cannot (the same failure in miniature). An `engine/features/` leak would
        # red `make register` for every later run, so never rely on the child.
        shutil.rmtree(plant, ignore_errors=True)


def test_an_unlocked_reader_copies_the_plant(tmp_path, planting_probe):
    """The bug, on demand — and the control for the test below.

    A reader that copies without taking the shared lock walks straight into
    the open plant window. Asserted by looking in the COPY.
    """
    dst = tmp_path / "features"
    shutil.copytree(FEATURES, dst)          # deliberately unlocked
    planting_probe.release()

    assert (dst / planting_probe.name).is_dir(), (
        "the unlocked reader did NOT capture the plant, so this file's "
        "premise is wrong: either the probe is not planting where the reader "
        "copies from, or the copy is not reading the live tree. The paired "
        "locked test proves nothing until this one fails the way it claims.")


def test_the_shared_lock_makes_the_reader_wait_for_a_clean_tree(
        tmp_path, repo_tree_read_lock, planting_probe):
    """The fix: the reader blocks on the held exclusive lock, then copies a
    tree the planter has already restored.

    Uses the production fixture the three readers use, so what is proven is
    the shipped path and not a re-implementation of it.
    """
    dst = tmp_path / "features"
    done = threading.Event()
    result = {}

    def reader():
        start = time.monotonic()
        with repo_tree_read_lock():
            shutil.copytree(FEATURES, dst)
        result["elapsed"] = time.monotonic() - start
        done.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # While the plant is held the reader must make no progress at all.
    assert not done.wait(HOLD_S), (
        "the reader finished its copy while the planter still held LOCK_EX — "
        "the shared lock is not being taken, so a copy can still capture a "
        f"plant. Copy exists: {dst.exists()}")
    assert not dst.exists(), (
        f"the reader created {dst} before the plant window closed — it is "
        "copying outside the lock")

    planting_probe.release()                # restore + release
    assert done.wait(30), "the reader never completed after the lock released"
    t.join(timeout=10)

    assert not (dst / planting_probe.name).exists(), (
        "the reader waited but still captured the plant — the planter's "
        "restore must complete BEFORE it unlocks, or the wait buys nothing")
    assert (dst / "vwf").is_dir(), (
        "the copy is missing a feature that is certainly in the tree — it did "
        "not copy what it was supposed to copy")
    assert result["elapsed"] >= HOLD_S, (
        f"the reader returned in {result['elapsed']:.3f}s, less than the "
        f"{HOLD_S}s the plant was held — it cannot have blocked on the lock")


def test_readers_do_not_exclude_each_other(tmp_path, repo_tree_read_lock):
    """SHARED, not exclusive: two readers may hold the lock at once.

    This is why the fix is `LOCK_SH` rather than widening `LOCK_EX` to the
    readers — the three copytrees still overlap freely under `-n`, and only
    plants are excluded. Without it the fix would be a silent serialisation.
    """
    both_in = threading.Barrier(2, timeout=10)
    errors = []

    def hold():
        # The barrier failure MUST be collected and asserted on. Left to
        # propagate out of the thread it is only a
        # PytestUnhandledThreadExceptionWarning — and this repo has no
        # `filterwarnings = error` (no pytest.ini / pyproject.toml /
        # setup.cfg at all), so the exact regression this test names would
        # pass: under `LOCK_EX` thread A waits out the 10 s barrier timeout,
        # BrokenBarrierError releases its lock, B acquires and dies on the
        # already-broken barrier, both threads are dead inside join(15), and
        # the liveness assert below holds. Measured: 1 passed in 10.06 s
        # instead of 0.005 s. A recorded finding.
        try:
            with repo_tree_read_lock():
                both_in.wait()              # raises BrokenBarrierError on timeout
        except Exception as e:              # noqa: BLE001 - reported, not swallowed
            errors.append(e)

    ts = [threading.Thread(target=hold, daemon=True) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=15)

    assert not errors, (
        "the two shared-lock holders could not be in the lock at the same "
        "time — one waited out the barrier while the other held, so the "
        "readers are excluding each other and would serialise against each "
        f"other for no reason: {errors}")
    assert not any(t.is_alive() for t in ts), (
        "two shared-lock holders could not be in the lock at the same time — "
        "the readers are excluding each other, which would serialise them "
        "against each other for no reason")
