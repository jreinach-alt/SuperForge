"""Guards for the suite.

Two of them, and they answer the same shape of question — *is a red telling
the truth about who caused it?*

  1. **Generated symbol maps must describe the current declarations** (the
     collection-time guard documented below).
  2. **A module may not finish with the shared Mesen core parked** (the
     parked-core guard, further down beside `pytest_runtest_teardown`). The
     core is a process-global singleton, so one module's leaked park strands
     the NEXT module's runner and the failure names the victim.

Most test modules in here read `build/<x>/symbol_map.json` at MODULE SCOPE
— addresses are asked for from the allocator's emitted map, never hardcoded
(AGENTS.md "the one idea that changes how you work"), and the natural place
to do that is beside the constants they feed. That read therefore happens at
COLLECTION, before any fixture has had a chance to `make` anything.

So a `build/` left over from an earlier phase does not fail as "your build is
stale". It fails as `KeyError: 'ES_O_HERO2'` from inside a dict comprehension
five frames down a collection traceback, which reads like a broken test and
costs ten minutes before "oh — rebuild".

This guard turns that into one line naming the map and the command that fixes
it.

HOW STALENESS IS DECIDED — by asking the allocator, not by guessing. The map
is re-emitted into a temp dir and compared BYTE FOR BYTE with the committed
one (the allocator is deterministic: same inputs, byte-identical
`symbol_map.json`). "The committed map differs from what today's declarations
produce" is then the exact claim, with no proxy in it. It costs ~130 ms per
map, once per session, and only for the maps the collected modules name.

The obvious cheaper design — compare mtimes against the Makefile's
prerequisite list — was written first and thrown away, for two independent
reasons that between them cover both error directions:

  * FALSE POSITIVE, observed within the hour: something in a full suite run
    bumps the mtime of two `engine/features/*/feature.toml` files without
    changing a byte (`git status` clean). `make` then correctly calls every
    game map out of date, and the mtime guard refused to collect three
    modules whose maps were perfect. A guard that cries wolf on a green tree
    gets deleted. (The mtime bump is a separate defect — tests should not
    touch the source tree — filed in the friction log. This guard is
    simply immune to it.)
  * FALSE NEGATIVE, found by trying to break it: a map that is WRONG but
    NEWER than everything — a hand-edited or half-written `build/` — sails
    through an mtime check. The content check catches it, which is how the
    negative test in `tests/test_map_freshness_guard.py` can exist at all.

SCOPE is per-module and derived from the module's own source, by parsing it:
a module is checked against exactly the maps it reads AT COLLECTION TIME.
Reads that live inside a fixture do not count — that fixture may `make` the
map first, and several do. Selecting a single allocator unit test therefore
demands no built ROM at all, and a NEW module that reads a map at module
scope is covered the day it is written, with nothing to register here.
"""
import ast
import contextlib
import ctypes
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# the lockstep core binding
# --------------------------------------------------------------------------
#
# The Machine substrate (vendor/machine.py) needs the patched core built by
# vendor/mesen_patches/apply.sh, and the core is a PROCESS-GLOBAL singleton
# whose first load wins — so the binding must be decided before any module
# imports mesen_runner, which is exactly here. When the patched core exists
# and nothing bound one explicitly, bind the whole run to it: it is a
# SUPERSET of the stock core (every stock export unchanged; see
# vendor/mesen_patches/README.md), so legacy modules see the core they
# always saw, and the Machine modules can run at all. An explicit
# SF_MESEN_CORE always wins; a missing patched core changes nothing (the
# Machine modules then fail with the message naming the build command,
# which is the honest verdict — never a skip).
_LOCKSTEP_CORE = "/tmp/Mesen2-lockstep/InteropDLL/obj.linux-x64/MesenCore.so"
if not os.environ.get("SF_MESEN_CORE", "").strip() and os.path.exists(_LOCKSTEP_CORE):
    os.environ["SF_MESEN_CORE"] = _LOCKSTEP_CORE


# --------------------------------------------------------------------------
# the repo-tree lock
# --------------------------------------------------------------------------
#
# Two modules PLANT into this repo's own working tree — `docs/09_feature_
# register.md`, `engine/features/*/feature.toml`, `engine/toy/*/feature.toml`
# — rather than into a tmp_path copy: `tests/test_register.py` and
# `tests/test_make_gates.py`. That is not sloppiness, it is their subject. The
# thing under test is the census `make register` computes FROM THIS TREE and
# the gates `make` runs OVER IT, and a copy is not that thing. Every other
# planting module in the suite copies first and is already isolated
# (test_microzero_*, test_reg_gate, test_c2_sram_class, test_oam_pin, ...).
#
# Two of those tests overlapping is not a flake, it is CORRUPTION. Both
# modules' `planted_text` reads the original, writes the plant, and restores
# in a `finally` — so when two windows overlap on one file, each restores the
# other's PLANT. Observed, not theorised: `pytest tests/test_register.py -n 3`
# during this change left three wrong rows in `docs/09_feature_register.md` (a
# `depends` edge, a `role`, and a hand-owned §3.1 gloss) plus a wrong
# `engine/features/fade/feature.toml`, indistinguishable from ordinary
# uncommitted edits. And it is STICKY: the next run then reds in
# `test_committed_register_agrees_with_the_tree` for a reason that has nothing
# to do with that run, which is the worst shape a red can have here now that
# the spec says a red is real on first occurrence.
#
# So the two modules take an exclusive inter-process lock for the length of
# every test. Deliberately NOT `xdist_group` + `--dist loadgroup`, which was
# built first and thrown away: xdist workers re-parse the ORIGINAL command
# line (`workermanage.py` sends `config.invocation_params.args`) and
# `remote.py:393` computes the loadgroup flag from it BEFORE any conftest
# configures, so a `config.option.dist` fixed up here reaches the controller's
# scheduler and never the workers — the group suffix is never applied and the
# grouping silently does nothing. Measured that way, not assumed: `-n 3` with
# the mark still reported bare nodeids and still corrupted the tree. Making it
# work needs either an ini file (`--dist loadgroup` in addopts, which makes
# xdist a hard requirement of every single-threaded run too) or a write to
# xdist's internal `option.loadgroup`. A lock needs neither, holds under ANY
# `-n`/`--dist`, and cannot fail open when a caller forgets a flag.
#
# POSIX-only (`fcntl.flock`). This repo is Linux-only already — ca65 via apt,
# `MesenCore.so` — so that costs nothing here.
#
# Planters are not the only side of this. Other modules COPY OR SCAN the live
# `engine/features/` tree at TEST time and allocate from what they find —
# `test_microzero_{gradient,race_floor,stream}.py` each `copytree` it into
# `tmp_path` to build a deliberately-infeasible variant. Serialising planter
# against planter leaves planter-against-READER wide open: a copy taken while
# `fade/feature.toml` is mid-plant captures the plant, and the copy then
# allocates differently than the test expects. That is a transient red, not
# sticky corruption (the copy is in `tmp_path`; the planter still restores),
# which is why it is a lesser class than the one above — but single-threaded
# CI had ZERO exposure to it and the `-n 2` flip creates it, with the exposure
# growing with `-n`. Filed as A recorded finding.
#
# So the one lock file carries BOTH sides of a readers-writer pair: planters
# take `LOCK_EX` (as before), live-tree readers take `LOCK_SH` for exactly the
# length of their copy. Readers do not exclude each other — the three copytrees
# may still overlap freely, which is the whole point of using `LOCK_SH` rather
# than widening the exclusive lock — and no reader can overlap a plant.
#
# WHAT IS DELIBERATELY *NOT* LOCKED, because the sweep that found the three
# measured it rather than assuming: `test_reg_ownership.py` (`_all_shipping()`
# globs the live tree) also reads
# it at test time, as does every fixture that shells out to `make microzero` /
# `make room` / `make toy`. Those reads ARE structurally exposed — planting
# `[[claims.dp]]` -> `[[claims.wram]]` in `fade/feature.toml` and re-running
# `allocate.py` over the live tree changes the emitted `symbol_map.json`
# (md5 8dc49553… -> ca404606…), so the divergence is real and not theoretical.
# The 21-pair sweep behind that (four tracked-file plants + the `zz_plant` dir
# plant, each held in turn while each reader ran, including `make toy` under
# the `engine/toy/feat_a` role plant) stayed green — but green there proves
# LESS than it looks, and a later review measured where it stops. What survives
# an extra or altered neighbour is a REFUSAL: the composition negatives assert
# the allocator rejects a rogue feature, and it still rejects it with a
# neighbour changed. Readers that assert success do NOT survive. Measured, same
# `fade` DP -> WRAM plant: `make microzero` and `make room` both red (2/2) —
# the regenerated `.inc` hands ca65 an absolute address where the ASM uses DP
# addressing, "Illegal addressing mode", and the build fixtures assert
# returncode 0. And a plant whose `name` disagrees with its directory makes
# `load_feature` RAISE for every consumer that globs the live dir, which reds
# `test_reg_ownership` too (the probe in `test_repo_tree_lock.py` was that
# shape and now derives its name from its directory). So: the residual is
# ACTIVE for the build fixtures and for any reader that LOADS rather than
# refuses — not latent. Left open on purpose anyway:
# closing it completely would mean holding this lock across the `make` fixtures,
# which is most of the suite, and that would serialise away the parallel
# speedup the lock exists to make safe. If a future test asserts on the CONTENT
# of a live-tree allocation rather than on a refusal, it needs `LOCK_SH` too.
#
# `test_reg_gate.py` USED to be named above as an unlocked live-tree reader,
# and stopped being one. Its live-tree tests assert on the CONTENT of a
# live-tree allocation — a clean shipped tree, and four planted-copy guards
# whose baseline invocation must go green before the plant is judged — which
# is exactly the class the sentence above names, so all five now take
# `LOCK_SH` for the length of the read (`repo_tree_read_lock`). Nothing in
# that file reads the live tree outside the lock.
REPO_TREE_LOCK = SUPERFORGE / "build" / ".repo_tree.lock"


@contextlib.contextmanager
def _repo_tree_flock(mode):
    """Hold `REPO_TREE_LOCK` in `mode` for the block. `LOCK_EX` | `LOCK_SH`.

    NOT CRASH-ATOMIC, by construction. A worker
    killed inside the window — SIGKILL, OOM — runs neither the test's own
    `finally` restore nor the unlock below; the OS drops the flock on process
    death, so the NEXT acquirer proceeds normally while a planted tracked file
    survives on disk, looking exactly like an ordinary uncommitted edit. No
    lock can fix that: the restore is remember-the-text-and-write-it-back, and
    a dead process cannot write anything back. RECOVERY IS MANUAL AND CHEAP —
    `git status` shows the survivors (plants only ever touch tracked files:
    `docs/09_feature_register.md`, `engine/features/*/feature.toml`,
    `engine/toy/*/feature.toml`) and `git checkout -- <paths>` restores them.
    Deliberately not automated: crash-recovery machinery would have to tell a
    plant from a real edit, and getting that wrong discards the developer's
    work — a far worse failure than the one it fixes.
    """
    REPO_TREE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(REPO_TREE_LOCK, "w") as fh:
        fcntl.flock(fh, mode)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


@pytest.fixture
def repo_tree_lock():
    """Serialise the tests that plant into this repo's working tree.

    Function-scoped and held for the whole test, so a plant's window can
    never overlap another test's read of the same file. Both modules opt in
    with `pytestmark = pytest.mark.usefixtures("repo_tree_lock")`; the two of
    them together run in ~2 s, so serialising them costs nothing measurable
    even at `-n 4`.
    """
    with _repo_tree_flock(fcntl.LOCK_EX):
        yield


@pytest.fixture
def repo_tree_read_lock():
    """Hand a live-tree reader a SHARED lock — for the copy, not the test.

    Used as `with repo_tree_read_lock(): shutil.copytree(SUPERFORGE/..., dst)`.
    It is a factory rather than a fixture that holds the lock itself so the
    window stays tight: these tests spend seconds in `allocate.py` and `make`
    AFTER the copy, all of it against `tmp_path`, and holding the lock across
    that would serialise them against the planters for no reason.
    """
    return lambda: _repo_tree_flock(fcntl.LOCK_SH)


# --------------------------------------------------------------------------
# the parked-core guard
# --------------------------------------------------------------------------
#
# `MesenRunner` instances are per-module; the Mesen2 core they drive is a
# PROCESS-GLOBAL SINGLETON (`mesen_runner._GLOBAL_LIB`, and the block above it
# says so at length). Those two facts together make one specific
# failure possible, and it has happened:
#
#   a module parks the core (`debug_break`/`frame_step`/`run_to_break`) and
#   finishes without `debug_resume` — its runner leaked, or `stop()` never ran
#   — and the NEXT module's brand-new runner meets a machine that does not
#   advance. That runner's `_frame_stepping` is False, so nothing on its own
#   instance knows to resume; `load_rom`'s resume-first guard consults the
#   flag, not the core. The observed symptom is the stall guard's
#
#     "the emulated frame counter has not advanced for 30.0s (frozen at frame
#      66) ... execution is PARKED in frame-stepping mode"
#
#   raised inside the VICTIM. `make gates` reported it as four failures across
#   test_measure_vblank.py and test_microzero_gradient.py on a branch that
#   touched neither and whose microzero md5 was byte-identical to main's;
#   isolated, 12 passed; a second full run, 924 passed
#. A red that names a module
#   nobody edited is the worst shape a red can have here, now that the spec
#   says a red is real on first occurrence.
#
# So: at every MODULE BOUNDARY, ask the core itself whether it is parked, and
# if it is, fail the module that just finished.
#
# WHY THE PREDICATE IS THE CORE AND NOT A FLAG. `_frame_stepping` is per
# instance and is documented to read stale-True after a timed-out
# `run_to_break`. `IsExecutionStopped()` is the
# emulator's own answer. Measured on this tree, one signal, three states:
# free-running False / parked True / after `stop()` False. `stop()` reading
# False is what makes this cheap to leave on — the ordinary, correct teardown
# is not a finding, and only an actually-wedged core is.
#
# WHY THE BOUNDARY AND NOT EVERY TEST. Parking WITHIN a module is the whole
# point of frame-stepping; a test that parks and hands on to the next test in
# the same module is fine, and several do exactly that. The hazard is a park
# that outlives the runner that made it. The check costs one C call per
# module.
#
# WHY IT RUNS AFTER THE REAL TEARDOWN (`wrapper=True`, check after the yield).
# Module-scoped fixtures are finalised inside `teardown_exact(nextitem)`, i.e.
# inside the very hook this wraps, and a fixture's `runner.stop()` resumes the
# core. Checking before the yield would fail every module with a well-behaved
# yield-fixture.
#
# WHY IT REPAIRS *AND* REPORTS. A silent auto-heal would be worse than the
# flake: it would hide a module that leaks core state, which is the thing that
# needs fixing. So the culprit's teardown ERRORS — the module is named, red,
# on first occurrence, with no retry and no skip — and only then is the core
# resumed, so the modules after it report their own truth instead of a
# cascade of borrowed failures. The resume is stated in the failure message,
# never assumed.
_PARK_GUARD_DISABLE = "SF_NO_PARK_GUARD"


class ParkedCoreError(AssertionError):
    """A test module finished with the process-global Mesen core parked."""


def _mesen_core_lib():
    """The process-global MesenCore handle, or None if nothing loaded it.

    Read out of `sys.modules` rather than imported: a session that never
    touches the emulator (`pytest tests/test_allocator.py`) must not pay for
    a `MesenCore.so` dlopen just to be told there is nothing to check.
    """
    mod = sys.modules.get("mesen_runner")
    return getattr(mod, "_GLOBAL_LIB", None) if mod is not None else None


# How long to keep asking the machine before calling it parked. Paid ONLY on
# the branch where `IsExecutionStopped()` already said "stopped" — a
# free-running core costs one C call, exactly as before. A thread pause is a
# lock held across a debugger call, i.e. milliseconds; 0.75 s is three orders
# of magnitude of headroom and still an eighth of the 6 s a hung module would
# otherwise take to be diagnosed by hand.
_PARK_CONFIRM_S = 0.75
_PARK_POLL_S = 0.002


def _core_progress():
    """The machine's own (frame, scanline), or None if it cannot be read.

    Read through the same `GetPpuState` call `MesenRunner.ppu_frame_count`
    uses. Scanline is included because a frame counter alone has a ~1/60 s
    granularity: a core that is running slowly under contention can hold one
    frame number across a whole poll window while its scanline sweeps, and
    "no frames yet" would then read as "parked".
    """
    mod = sys.modules.get("mesen_runner")
    lib = _mesen_core_lib()
    if mod is None or lib is None or not hasattr(lib, "GetPpuState"):
        return None
    try:
        buf = (ctypes.c_uint8 * mod._PPU_STATE_BUF_SIZE)()
        lib.GetPpuState(buf, mod._CPU_TYPE_SNES)
        f = mod._PPU_STATE_FRAMECOUNT_OFFSET
        s = mod._PPU_STATE_SCANLINE_OFFSET
        return (int.from_bytes(bytes(buf[f:f + 4]), "little"),
                int.from_bytes(bytes(buf[s:s + 2]), "little"))
    except Exception:      # pragma: no cover - a torn-down ctypes handle
        return None


def core_is_parked(confirm_s: float = _PARK_CONFIRM_S) -> bool:
    """True iff the DEBUGGER is holding the shared core stopped.

    WHY THIS IS NOT JUST `IsExecutionStopped()`. It was, and that is a
    different question from the one this guard asks. Mesen's own definition
    (`Core/Debugger/Debugger.cpp:738`) is::

        bool Debugger::IsExecutionStopped()
        { return _executionStopped || _emu->IsThreadPaused(); }

    — and `Emulator::IsThreadPaused()` (`Core/Shared/Emulator.cpp:876`) is
    `!_emuThread || _threadPaused`, with `_threadPaused` set inside
    `WaitForLock()` whenever ANY caller holds the emulator lock. So the
    predicate answers "not executing at this instant", which on a contended
    box is true of a perfectly healthy FREE-RUNNING core that happens to be
    inside someone's `Lock()`/`Unlock()` window. It reported exactly that
    twice in CI (two CI runs), failing
    `test_park_guard.py::test_core_is_parked_tracks_the_emulator_not_a_flag`
    on a free-running core, and it is the same conflation AGENTS.md records
    behind `run_to_break` "reporting breaks no breakpoint produced".

    So: keep the cheap call as a FAST NEGATIVE — `_executionStopped` false and
    no thread pause means definitely running, one C call, no change in cost
    for the overwhelmingly common case — and when it says stopped, ask the
    MACHINE. A parked core's (frame, scanline) is frozen; a descheduled
    free-running one's is not, it is merely slow. Any movement inside
    `confirm_s`, or the flag clearing itself, means not parked.

    This is the same discipline the harness applies everywhere else: wait on
    emulated progress, not on a flag and not on wall time.
    """
    lib = _mesen_core_lib()
    if lib is None or not hasattr(lib, "IsExecutionStopped"):
        return False
    try:
        if not lib.IsExecutionStopped():
            return False                      # fast negative, one C call
    except Exception:      # pragma: no cover - a torn-down ctypes handle
        return False

    start = _core_progress()
    if start is None:
        # No readable PPU state — fall back to the flag rather than inventing
        # an answer. This is the pre-2026-08-05 behaviour, kept for the path
        # where the debugger is up enough to answer IsExecutionStopped but not
        # enough to hand over a PPU struct.
        return True

    deadline = time.time() + confirm_s
    while time.time() < deadline:
        try:
            if not lib.IsExecutionStopped():
                return False                  # the pause cleared: it was one
        except Exception:  # pragma: no cover
            return False
        if _core_progress() not in (None, start):
            return False                      # the machine moved: not parked
        # This polls whether the EMULATION THREAD is stopped. A parked
        # core advances zero frames, so an emulated-frame wait here would
        # block forever on exactly the state being detected.
        # WALL-CLOCK: ok — no emulated clock exists to wait on here
        time.sleep(_PARK_POLL_S)
    return True


def _unpark_core(timeout_s: float = 5.0) -> bool:
    """Resume the shared core. True iff it demonstrably runs again.

    Deliberately a bare `ResumeExecution` retry loop rather than
    `MesenRunner.debug_resume`: there is no runner to call it on — the one
    that parked the core is exactly the object that went away. The retry is
    `debug_resume`'s own (ResumeExecution is subject to a lost-wakeup race,
    observed there), and it is a repair of a machine, not a re-run of a test.

    The emulation-speed flag is left alone: `debug_break` raised it and the
    next runner's `load_rom` lowers it to that runner's own policy through
    `_apply_free_run_speed`. Forcing a value here would be this file having a
    second opinion about a policy it does not own.

    The success test is EMULATED PROGRESS, not the stopped flag. Asking
    `core_is_parked()` here would be both wrong and slow: wrong because the
    flag clears the instant `Run()` lands, before the machine has necessarily
    produced a scanline, and slow because that predicate now spends up to
    0.75 s per call confirming a park it was handed. "It demonstrably runs
    again" is what the docstring promises, and the frame/scanline pair is what
    demonstrates it.
    """
    lib = _mesen_core_lib()
    if lib is None or not hasattr(lib, "ResumeExecution"):
        return False
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        before = _core_progress()
        lib.ResumeExecution()
        settle = time.time() + 0.1
        while time.time() < settle:
            if before is None:
                if not core_is_parked(confirm_s=0.05):
                    return True
            elif _core_progress() not in (None, before):
                return True
            # Same reason as core_is_parked: this waits for a RESUME to
            # take on the emulation thread, and what it is waiting for is
            # the frame counter starting to move at all.
            # WALL-CLOCK: ok — no emulated clock exists to wait on here
            time.sleep(0.001)
    return False


def _module_id(item) -> str:
    return item.nodeid.split("::")[0]


def _is_module_boundary(item, nextitem) -> bool:
    """Is `item` the last test of its module in this run?

    `nextitem is None` is the end of the session. Otherwise the boundary is
    where pytest itself puts it: `teardown_exact(nextitem)` pops — and
    finalises — the module node exactly when the next item lives elsewhere.
    """
    return nextitem is None or _module_id(nextitem) != _module_id(item)


def _park_guard_applies(item, nextitem) -> bool:
    return (not os.environ.get(_PARK_GUARD_DISABLE, "").strip()
            and _is_module_boundary(item, nextitem))


# --------------------------------------------------------------------------
# the worker schedule record
# --------------------------------------------------------------------------
#
# THE PROBLEM THIS EXISTS FOR. The parked-core guard above catches ONE named
# way a module poisons its successor, and it catches it by asking the core a
# question at the module boundary. It is silent about everything else that
# crosses a boundary — and when a red lands on a module whose own inputs are
# byte-identical to the last green run's, the first question is "what ran
# BEFORE it, in the same process?" Today that question has no answer at all:
# pytest prints failures, never the ORDER, and under `-n N` the order is
# xdist's to choose and differs run to run. A red therefore arrives with its
# most load-bearing fact — its neighbours — already discarded.
#
# So: one line per MODULE, naming the worker that ran it, its position in
# that worker's sequence, and the state the shared core was in when it
# handed on. Reading the file backwards from a failing module gives its
# predecessors on the same process (the shared-core adjacency) and, through
# the timestamps, what was running CONCURRENTLY on the other workers (the
# shared-filesystem adjacency — `build/`, the repo tree, the `make`
# subprocesses several fixtures shell out to). Both are real here and they
# are different mechanisms, so the record carries both rather than picking.
#
# WHY ONE LINE PER MODULE AND NOT PER TEST. The unit of the hazard is the
# module: runners are module-scoped, the park guard fires at module
# boundaries, and a per-test file would be ~4,000 rows of which 3,990 are
# noise. Failing TEST names are carried inside the module's own row (capped),
# so nothing needed for attribution is lost.
#
# WHY IT PIGGYBACKS ON THE PARK GUARD instead of adding a second boundary
# mechanism. The guard already computes the one expensive fact worth
# recording (`core_is_parked()`, up to 0.75 s when the flag says stopped),
# already knows where the boundary is, and already runs after the real
# teardown. A parallel autouse fixture would run at a DIFFERENT point in the
# finalisation order, would recompute the same predicate, and would then be
# a second opinion about where a module ends. The verdict is computed once
# and shared.
#
# WHAT IT COSTS WHEN NOTHING IS WRONG. One `IsExecutionStopped()` plus one
# `GetPpuState` per module — the same two calls the guard already makes on
# its fast-negative path — and a single `os.write` of a few hundred bytes.
# Nothing is added to the per-test path.
#
# ATOMICITY. Workers are separate PROCESSES appending to one file. The write
# is a single `os.write` on an `O_APPEND` descriptor and every row is far
# under `PIPE_BUF`, so rows from concurrent workers interleave whole and
# never tear. Deliberately not a lock: a lock around an instrumentation write
# would be a new serialisation point in the very schedule it is trying to
# observe.
#
# NEVER FATAL. Every write is wrapped: instrumentation that can fail a test
# run is worse than no instrumentation, because the first thing it would do
# is add a second intermittent failure to an investigation into the first.
#
# WHO IS ALLOWED TO WRITE. Several modules in this suite start a pytest of
# their own in a subprocess — `test_park_guard.py` and
# `test_map_freshness_guard.py` load THIS conftest into those sessions on
# purpose, so the hooks under test are the shipped ones. Those nested
# sessions inherit the outer run's environment, so without a rule they would
# register these hooks, decide they were a fresh run, and TRUNCATE the record
# of the very run that is investigating them — destroying the evidence
# mid-suite, in the one file nobody would think to suspect.
#
# The rule is process ownership, not paths: the first pytest to find no owner
# in the environment claims the file, and the only other processes allowed to
# append are ITS xdist workers — its direct children, which announce
# themselves with `PYTEST_XDIST_WORKER`. A nested run started from a serial
# owner is a direct child too, but carries no worker name; a nested run
# started from inside a worker carries one but is not the owner's child.
# Both are excluded, at any depth.
#
# Paths were tried first and thrown away: the obvious rule ("record only a
# session rooted at this tree") depends on `config.rootpath`, which pytest
# derives from where it was INVOKED — `pytest tests/test_x.py` from the repo
# root roots at the repo, the same command from inside `tests/` roots at
# `tests/`. That silently disarms the record for anyone iterating from the
# test directory, and an instrument that quietly stops recording is worse
# than one that is plainly off.
_SCHEDULE_DISABLE = "SF_NO_SCHEDULE_LOG"
_SCHEDULE_ENV = "SF_SCHEDULE_LOG"
_SCHEDULE_OWNER = "SF_SCHEDULE_OWNER"
_SCHEDULE_DEFAULT = SUPERFORGE / "build" / "worker_schedule.jsonl"

# Failing test names carried per module row. Enough to name the shape of a
# red without turning the row into the pytest log it is meant to be read
# BESIDE.
_SCHEDULE_MAX_NAMES = 12

_sched_state: dict = {
    "seq": 0,           # this process's module counter
    "module": None,     # the module currently open
    "t_start": None,    # when its first test started (epoch seconds)
    "tests": 0,
    "failed": 0,
    "names": [],
}


def schedule_participant() -> bool:
    """Is this process part of the run that OWNS the schedule file?

    True for the pytest that claimed the file and for that pytest's own xdist
    workers. False for every nested session a test started, which is the
    whole point — see the block above.
    """
    owner = os.environ.get(_SCHEDULE_OWNER, "").strip()
    if not owner.isdigit():
        return False
    owner_pid = int(owner)
    if os.getpid() == owner_pid:
        return True
    return (bool(os.environ.get("PYTEST_XDIST_WORKER", "").strip())
            and os.getppid() == owner_pid)


def schedule_path() -> Optional[Path]:
    """Where the schedule is being written, or None when it is off."""
    if os.environ.get(_SCHEDULE_DISABLE, "").strip():
        return None
    if not schedule_participant():
        return None
    override = os.environ.get(_SCHEDULE_ENV, "").strip()
    return Path(override) if override else _SCHEDULE_DEFAULT


def worker_id() -> str:
    """This process's xdist worker name; "main" for a serial run.

    Serial runs record too — the whole point is to be able to compare a
    packing that failed against one that did not, and a serial run is the
    packing every isolated reproduction uses.
    """
    return os.environ.get("PYTEST_XDIST_WORKER") or "main"


def _run_id() -> str:
    """An id shared by every worker of ONE `pytest` invocation.

    xdist sets `PYTEST_XDIST_TESTRUNUID` in every worker of a run, which is
    exactly the grouping key needed to tell this run's rows from the rows of
    the run before it in an appended file. Serial runs have no such value, so
    the controller stamps one at configure time.
    """
    return (os.environ.get("PYTEST_XDIST_TESTRUNUID")
            or os.environ.get("SF_SCHEDULE_RUN_ID") or "-")


def _core_snapshot() -> dict:
    """Cheap, NON-BLOCKING core state for a schedule row.

    Deliberately the raw `IsExecutionStopped()` flag and the (frame,
    scanline) pair rather than `core_is_parked()`: the confirmed verdict can
    cost 0.75 s and the guard already pays for it when it applies. Recording
    the raw flag ALONGSIDE the confirmed verdict is also what makes the
    "flag said stopped but the machine was moving" state — the contended-box
    false positive `core_is_parked` was written to reject — visible in the
    record instead of collapsed into a boolean.
    """
    lib = _mesen_core_lib()
    if lib is None:
        return {"core": "unloaded"}
    snap: dict = {"core": "loaded"}
    try:
        snap["stopped_flag"] = (bool(lib.IsExecutionStopped())
                                if hasattr(lib, "IsExecutionStopped") else None)
    except Exception:      # pragma: no cover - a torn-down ctypes handle
        snap["stopped_flag"] = None
    prog = _core_progress()
    if prog is not None:
        snap["frame"], snap["scanline"] = prog
    return snap


def _machine_snapshot() -> Optional[str]:
    """The ROM of the lockstep Machine still owning the core, if any.

    A Machine that outlives its module holds the core the same way a park
    does — `vendor/machine.py` documents that a second load STEALS the core
    and the old handle starts refusing — so which ROM `_current` points at
    when a module hands on is a boundary fact worth having.
    """
    cls = _machine_class()
    cur = getattr(cls, "_current", None) if cls is not None else None
    if cur is None:
        return None
    try:
        return os.path.basename(getattr(cur, "rom_path", "") or "?")
    except Exception:      # pragma: no cover
        return "?"


def schedule_row(module: str, parked, teardown_failed: bool = False) -> dict:
    """The row for one finished module. Split out so it is testable.

    `parked` is the guard's CONFIRMED verdict, or None when the guard did not
    run (it is disabled) and therefore nobody paid for the confirmation.
    """
    st = _sched_state
    now = time.time()
    row = {
        "run": _run_id(),
        "worker": worker_id(),
        "pid": os.getpid(),
        "seq": st["seq"],
        "module": module,
        "t_start": round(st["t_start"], 3) if st["t_start"] else None,
        "t_end": round(now, 3),
        "tests": st["tests"],
        "failed": st["failed"],
        "parked": parked,
    }
    if st["names"]:
        row["failed_tests"] = st["names"][:_SCHEDULE_MAX_NAMES]
    if teardown_failed:
        row["teardown_failed"] = True
    row.update(_core_snapshot())
    machine = _machine_snapshot()
    if machine is not None:
        row["machine_current"] = machine
    return row


def _schedule_write(row: dict) -> None:
    """Append one row. Single `os.write` on an O_APPEND fd; never raises."""
    path = schedule_path()
    if path is None:
        return
    try:
        line = (json.dumps(row, sort_keys=True) + "\n").encode()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:      # pragma: no cover - instrumentation is never fatal
        pass


def _schedule_close_module(module: str, parked, teardown_failed=False) -> None:
    if schedule_path() is not None:
        _schedule_write(schedule_row(module, parked, teardown_failed))
    _sched_state.update(seq=_sched_state["seq"] + 1, module=None,
                        t_start=None, tests=0, failed=0, names=[])


def pytest_runtest_setup(item):
    """Open a module's window at its first test.

    The close is at the boundary the park guard already identifies, so the
    two ends of a module come from the same definition of where a module
    begins and ends.
    """
    if schedule_path() is None:
        return
    mod = _module_id(item)
    if _sched_state["module"] != mod:
        _sched_state.update(module=mod, t_start=time.time(), tests=0,
                            failed=0, names=[])
    _sched_state["tests"] += 1


def pytest_runtest_logreport(report):
    """Count this module's reds, so a row says whether it was a victim."""
    if schedule_path() is None or not report.failed:
        return
    _sched_state["failed"] += 1
    name = report.nodeid.split("::", 1)[-1]
    if name not in _sched_state["names"]:
        _sched_state["names"].append(name)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    # The teardown this wraps can itself raise — a module-scoped fixture whose
    # finaliser fails. That module is already red, so attribution is not at
    # stake; what IS at stake is the core, because a fixture that parked and
    # then blew up leaves it parked and poisons the next module exactly the
    # same way. So the repair happens on both paths and the report differs:
    # on the exception path the original error is preserved and the repair is
    # announced on stderr (never swallowed into it).
    #
    # The boundary is also where the schedule row is written. The park verdict
    # is computed ONCE here and handed to both consumers: the guard, which
    # decides whether to fail the module, and the row, which records what the
    # module left behind. Recomputing it for the record would double the one
    # expensive call on this path (`core_is_parked` spends up to 0.75 s
    # confirming a stopped flag) and could disagree with the guard's answer,
    # which is the one thing a record of the guard's boundary must not do.
    #
    # `parked` is None — not False — when SF_NO_PARK_GUARD is set: nobody paid
    # for the confirmation, so the row says "unknown" rather than inventing a
    # verdict. The cheap raw flag in `_core_snapshot` is recorded either way.
    boundary = _is_module_boundary(item, nextitem)
    guard_on = not os.environ.get(_PARK_GUARD_DISABLE, "").strip()
    try:
        result = yield
    except BaseException:
        if boundary:
            parked = core_is_parked() if guard_on else None
            _schedule_close_module(_module_id(item), parked,
                                   teardown_failed=True)
            if parked:
                ok = _unpark_core()
                print(f"\nPARKED CORE: {_module_id(item)} left the shared "
                      f"Mesen2 core parked while its teardown was failing; the "
                      f"guard {'resumed' if ok else 'FAILED to resume'} it. "
                      f"The error below is the teardown's own — but this "
                      f"module is also the one that leaked the park.",
                      file=sys.stderr)
        raise
    if not boundary:
        return result
    parked = core_is_parked() if guard_on else None
    _schedule_close_module(_module_id(item), parked)
    if not parked:
        return result
    mod = _module_id(item)
    repaired = _unpark_core()
    raise ParkedCoreError(
        f"PARKED CORE: {mod} finished with the shared Mesen2 core still "
        f"parked (IsExecutionStopped() is True).\n"
        f"  The core is a PROCESS-GLOBAL singleton — one per pytest process, "
        f"not one per MesenRunner — so the next module's fresh runner would "
        f"meet a machine that does not advance and would fail with "
        f"'the emulated frame counter has not advanced ...', naming ITSELF.\n"
        f"  This module is the culprit; the module after it is not.\n"
        f"  Fix: every debug_break()/frame_step()/run_to_break() in {mod} "
        f"must be matched by a debug_resume() before the module ends — use "
        f"`with runner.frame_stepping():` so the resume survives a failed "
        f"assertion, or give the module-scoped runner a yield-fixture whose "
        f"teardown calls stop().\n"
        f"  The guard has now "
        + ("RESUMED the core so the modules after this one report their own "
           "results rather than a cascade of borrowed failures. Nothing was "
           "retried and nothing was skipped."
           if repaired else
           "FAILED to resume the core — later modules in this run are "
           "unreliable; re-run them after fixing this one.")
    )


# --------------------------------------------------------------------------
# the replay triple on every red (docs/53 D-DH3, a later review)
# --------------------------------------------------------------------------
#
# D-DH3 settles that a lockstep trajectory is a pure function of the replay
# triple `(rom md5, seed, input script)` and that **every failure prints
# it**. `Machine._raise` does that for every MachineError — but a MachineError
# is a failure of the SUBSTRATE, and the failure kind a test actually
# produces is a plain `assert`. the spec's own headline scenario is exactly
# that shape: "if the run-3 11 == 12 desync REPRODUCES, leave the test red
# WITH THE TRIPLE IN THE FAILURE TEXT" — and today that red would print
# without it, because nothing appends it.
#
# So: attach the triple to the report of any FAILED test that drove a
# Machine. A pytest report section is the right carrier — it survives xdist
# (sections are serialised with the report), it prints under the traceback
# for the phase that failed, and it cannot perturb the assertion itself.
#
# WHICH MACHINES. "The one that owns the core" is not enough. Machines
# SUPERSEDE each other (vendor/machine.py: a second load steals the core and
# the old handle's methods start refusing), so a test that boots the
# FORWARD/TIEROFF/CULLOFF control builds and then compares them holds three
# trajectories and only the last one is `_current` — while the red is very
# likely ABOUT one of the other two. Their triples are what replays it. So
# the section reports `Machine._current` AND every Machine instance sitting
# in the locals of the failing frames, deduplicated by identity and in that
# order.
#
# STATED LIMIT: direct locals of the traceback frames only — a Machine held
# inside a list, a dict or an attribute is not found, and a machine that was
# closed AND dropped before the assert is gone entirely. Both are recoverable
# by naming the machine in a local, and neither is the shape this
# modules use. Widening this into a general object walk would cost more than
# it buys and would start reporting machines the failure has nothing to do
# with.
_TRIPLE_SECTION = "replay triple (lockstep Machine)"


def _machine_class():
    """`machine.Machine`, or None if this session never imported it.

    Read out of `sys.modules` rather than imported, for the same reason
    `_mesen_core_lib` is: a session that never touches the lockstep
    substrate (`pytest tests/test_allocator.py`) must not pay for the
    import — and `vendor/machine.py` is only on `sys.path` at all because
    some test module put it there.
    """
    mod = sys.modules.get("machine")
    return getattr(mod, "Machine", None) if mod is not None else None


def _machines_for(call, cls):
    """The Machines whose trajectories could explain this failure."""
    found, seen = [], set()

    def add(obj):
        if isinstance(obj, cls) and id(obj) not in seen:
            seen.add(id(obj))
            found.append(obj)

    add(getattr(cls, "_current", None))
    tb = getattr(getattr(call, "excinfo", None), "traceback", None) or ()
    for entry in tb:
        try:
            for value in entry.frame.f_locals.values():
                add(value)
        except Exception:      # pragma: no cover - a frame we cannot read
            continue
    return found


def machine_replay_section(call) -> Optional[str]:
    """The triple(s) to attach to a failing report, or None if no Machine.

    Split out of the hook so it is directly testable — the hook itself is
    then only the wiring (`tests/test_replay_triple.py` exercises both).
    """
    cls = _machine_class()
    if cls is None:
        return None
    machines = _machines_for(call, cls)
    if not machines:
        return None
    lines = [
        "Replay this red exactly: the trajectory is a pure function of the",
        "triple below (docs/53 D-DH3). Same rom + same seed + same input",
        "script reproduces the same frame on any host, under any load.",
        "",
    ]
    for m in machines:
        try:
            rom_md5, seed, script = m.triple
            owner = " [owns the core]" if getattr(cls, "_current", None) is m else ""
            lines += [
                f"  rom          {os.path.basename(getattr(m, 'rom_path', '?'))}"
                f"  md5 {rom_md5}{owner}",
                f"  seed         {seed:#x}"
                + ("   (SF_POWERON_SEED)" if os.environ.get("SF_POWERON_SEED", "").strip()
                   else "   (DEFAULT_POWERON_SEED)"),
                f"  input script {script!r}",
                "",
            ]
        except Exception as exc:   # pragma: no cover - a half-built Machine
            lines.append(f"  <a Machine whose triple could not be read: {exc!r}>")
    return "\n".join(lines).rstrip()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if report.failed:
        section = machine_replay_section(call)
        if section:
            report.sections.append((_TRIPLE_SECTION, section))
    return report


def pytest_configure(config):
    """Give each xdist worker its own Mesen home.

    `mesen_runner._detect_home_dir` reads `SF_MESEN_HOME` ONCE at import and
    otherwise uses the shared `/tmp/mesen_home`. The override mechanism
    already existed; nothing SET it per worker — so `pytest -n 3` would have
    put three concurrent emulators in one home directory, sharing:

      * `Screenshots/` — `take_screenshot` finds the new PNG by diffing the
        directory listing, so a worker can hand back a sibling's frame, and
        every screenshot assertion in the suite is then reading someone
        else's game.
      * `Saves/<rom>.srm` — load-bearing since the SRAM slice: two workers on
        room.sfc would share one battery file, and `virgin_boot`'s "delete
        the .srm, then boot" would delete the other's mid-test.

    Set before any test module imports mesen_runner (`pytest_configure` runs
    ahead of collection), and only when the caller has not chosen a home
    themselves. Single-threaded runs are untouched — `PYTEST_XDIST_WORKER` is
    absent, so the shared default stands and nothing about the default path
    changes.
    """
    # The schedule file holds ONE run. The controller (`pytest_configure` runs
    # there before any worker is spawned, and is the only configure a serial
    # run has) truncates it and stamps a run id; workers then only ever
    # append, so no truncation can race a sibling's write. An appended-forever
    # file was the first shape and was thrown away: every reader of it began
    # by working out where the current run started, which is exactly the
    # archaeology this record exists to abolish.
    if not os.environ.get(_SCHEDULE_OWNER, "").strip():
        os.environ[_SCHEDULE_OWNER] = str(os.getpid())
        os.environ.setdefault("SF_SCHEDULE_RUN_ID",
                              f"{int(time.time())}-{os.getpid()}")
        path = schedule_path()
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("")
            except OSError:
                pass

    # ------------------------------------------------------------------
    # a module runs in ONE process
    # ------------------------------------------------------------------
    #
    # xdist's default scheduler under `-n N` is `--dist load`, and it
    # distributes INDIVIDUAL TESTS, not files. Nothing in this suite is
    # written for that. Two shapes break, and both of them are load-bearing
    # here:
    #
    #   * INTRA-MODULE STATE. `test_measure_cpu.py` fills a module-level
    #     `RESULTS` dict across three tests and writes it out in a fourth;
    #     `test_measure_vblank.py`'s second test reads the JSON its first
    #     test wrote ("single sweep ran first"). Split those across
    #     processes and the reader sees an empty dict or a missing file —
    #     while the test that FILLS it passes, on the other worker.
    #   * MODULE-SCOPED FIXTURES. Nearly every module here boots a ROM once
    #     in a module-scoped fixture. A split runs that fixture on BOTH
    #     workers, which doubles the boot and — because several of those
    #     fixtures shell out to `make` — puts two concurrent `make`
    #     invocations in one `build/`, which nothing serialises (see the
    #     repo-tree lock block above: the `make` fixtures are deliberately
    #     outside it).
    #
    # Neither shape is visible in a failure message. The victim names
    # ITSELF, its inputs are byte-identical to the last green run's, and it
    # passes in isolation because a serial run cannot split anything — which
    # is exactly the shape that reads as "flaky" and is not.
    #
    # MEASURED, not reasoned: a three-test module whose last test reads what
    # the first two wrote, run beside 24 fast tests at `-n 2`, split across
    # workers in 37 of 40 runs and FAILED in every run it split. Under
    # `loadfile` the same experiment split 0 of 30 and failed 0 of 30, with
    # both workers still carrying work (15/12) — the parallelism is in the
    # file count, and this suite has ~120 files.
    #
    # THE FRONT DOOR IS THE MAKEFILE. `PYTEST_DIST` passes `--dist loadfile`
    # on the command line, where the rest of the run's shape is stated and
    # reviewed, and `make test` then CHECKS the property afterwards from the
    # schedule record rather than trusting the flag. This fixup is the
    # BACKSTOP for the command the Makefile does not own — a hand-typed
    # `pytest tests/ -n 4`, which is what people run while iterating and
    # which would otherwise split modules silently. When the Makefile has
    # already passed `loadfile`, this sees it and does nothing.
    #
    # WHY THIS FIXUP REACHES THE SCHEDULER when the `--dist loadgroup` one
    # documented above does not: `loadgroup` needs each WORKER to append a
    # group suffix to its nodeids, and a worker re-parses the original
    # command line before any conftest configures. `loadfile` is decided
    # entirely in the CONTROLLER — `DSession.pytest_xdist_make_scheduler`
    # reads `config.getvalue("dist")` after configure — so setting it here
    # is enough. Verified by the experiment above, not assumed.
    #
    # `SF_XDIST_DIST` overrides, and exists so the sensitivity control in
    # tests/test_worker_schedule.py can put the default back and show the
    # failure returning. A run that sets it is not a normal run.
    #
    # STATED LIMIT: only `load` is rewritten. `--dist worksteal` splits a
    # module exactly the same way, and is left alone because it can only be
    # reached by typing it — overriding a flag someone chose explicitly is
    # worse than letting them have it. Nothing in this repo passes it (the
    # Makefile passes `-n` and nothing else). If it is ever used, the split
    # shows up by name in the schedule summary's `split_modules`, which is
    # the same way this defect would be found again.
    want = os.environ.get("SF_XDIST_DIST", "").strip()
    if want:
        config.option.dist = want
    elif getattr(config.option, "dist", "no") == "load":
        config.option.dist = "loadfile"

    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker and not os.environ.get("SF_MESEN_HOME", "").strip():
        home = Path(tempfile.gettempdir()) / f"mesen_home_{worker}"
        (home / "Screenshots").mkdir(parents=True, exist_ok=True)
        (home / "Saves").mkdir(parents=True, exist_ok=True)
        os.environ["SF_MESEN_HOME"] = str(home)

    # The one marker in this suite, registered here because there is no ini
    # file to register it in. `needs_linked_images` marks cases that OPEN a
    # linked image under build/. A normal run passes no `-m`, so they all run;
    # `tools/setup.sh`'s pre-build sanity step is the single caller that
    # deselects them, because in a fresh clone nothing is linked yet. It is a
    # deselection at ONE NAMED CALL SITE and deliberately not a `skipif` inside
    # the cases -- a case that skips when its subject is missing is how
    # coverage evaporates in silence. tests/test_rom_header.py's
    # "WHY THESE CASES CARRY A MARKER" block owns the full contract, and the
    # tripwire that holds it is in that file.
    config.addinivalue_line(
        "markers",
        "needs_linked_images: opens a linked image under build/; deselected "
        "ONLY by tools/setup.sh's pre-build sanity step")

# map path -> (make target that regenerates it, allocate.py argv minus --out).
# The argv is the same invocation the Makefile recipe uses, so this cannot
# drift into a second opinion about how a map is produced.
MAPS = {
    "build/symbol_map.json": (
        "toy", ["--game", "engine/toy"]),
    "build/mz/symbol_map.json": (
        "microzero",
        ["--game", "game/microzero", "--features-dir", "engine/features"]),
    "build/rm/symbol_map.json": (
        "room",
        ["--game", "game/room", "--features-dir", "engine/features"]),
    "build/bk/symbol_map.json": (
        "breaker",
        ["--game", "game/breaker", "--features-dir", "engine/features"]),
    "build/sh/symbol_map.json": (
        "shmup",
        ["--game", "game/shmup", "--features-dir", "engine/features"]),
    "build/hud/symbol_map.json": (
        "hud_game",
        ["--game", "game/hud_game", "--features-dir", "engine/features"]),
    "build/pl/symbol_map.json": (
        "platformer",
        ["--game", "game/platformer", "--features-dir", "engine/features"]),
    "build/sv/symbol_map.json": (
        "split_v_fight",
        ["--game", "game/split_v_fight", "--features-dir", "engine/features"]),
    "build/m7dg/symbol_map.json": (
        "m7_dungeon",
        ["--game", "game/m7_dungeon", "--features-dir", "engine/features"]),
    "build/m7x/symbol_map.json": (
        "mode7_explore",
        ["--game", "game/mode7_explore", "--features-dir", "engine/features"]),
    "build/sh2/symbol_map.json": (
        "split_h_2p_demo",
        ["--game", "game/split_h_2p_demo", "--features-dir", "engine/features"]),
    "build/pfs/symbol_map.json": (
        "platformer_stream",
        ["--game", "game/platformer_stream", "--features-dir",
         "engine/features"]),
    "build/scr/symbol_map.json": (
        "scroller",
        ["--game", "game/scroller", "--features-dir", "engine/features"]),
    "build/cf/symbol_map.json": (
        "camera_follow",
        ["--game", "game/camera_follow", "--features-dir", "engine/features"]),
    "build/maze/symbol_map.json": (
        "maze",
        ["--game", "game/maze", "--features-dir", "engine/features"]),
    "build/jr/symbol_map.json": (
        "jumper",
        ["--game", "game/jumper", "--features-dir", "engine/features"]),
    "build/pat/symbol_map.json": (
        "patrol",
        ["--game", "game/patrol", "--features-dir", "engine/features"]),
    "build/sprg/symbol_map.json": (
        "sprite_game",
        ["--game", "game/sprite_game", "--features-dir", "engine/features"]),
    "build/st/symbol_map.json": (
        "stomper",
        ["--game", "game/stomper", "--features-dir", "engine/features"]),
    "build/sr/symbol_map.json": (
        "scroll_run",
        ["--game", "game/scroll_run", "--features-dir", "engine/features"]),
    "build/shm/symbol_map.json": (
        "split_h_matrix_demo",
        ["--game", "game/split_h_matrix_demo", "--features-dir",
         "engine/features"]),
    "build/shp3/symbol_map.json": (
        "split_h_persp3_demo",
        ["--game", "game/split_h_persp3_demo", "--features-dir",
         "engine/features"]),
    "build/shd/symbol_map.json": (
        "split_h_demo",
        ["--game", "game/split_h_demo", "--features-dir", "engine/features"]),
    "build/br/symbol_map.json": (
        "brawler",
        ["--game", "game/brawler", "--features-dir", "engine/features"]),
    "build/svd/symbol_map.json": (
        "split_v_demo",
        ["--game", "game/split_v_demo", "--features-dir", "engine/features"]),
    "build/svs/symbol_map.json": (
        "split_v_seamtrial",
        ["--game", "game/split_v_seamtrial",
         "--features-dir", "engine/features"]),
    "build/sit/symbol_map.json": (
        "seam_irq_trial",
        ["--game", "game/seam_irq_trial",
         "--features-dir", "engine/features"]),
    "build/shg/symbol_map.json": (
        "split_h_irq_grad_demo",
        ["--game", "game/split_h_irq_grad_demo",
         "--features-dir", "engine/features"]),
    "build/shp/symbol_map.json": (
        "split_h_persp_demo",
        ["--game", "game/split_h_persp_demo", "--features-dir",
         "engine/features"]),
    "build/m7c/symbol_map.json": (
        "mode7_chamber",
        ["--game", "game/mode7_chamber", "--features-dir", "engine/features"]),
    "build/rpg/symbol_map.json": (
        "rpg",
        ["--game", "game/rpg", "--features-dir", "engine/features"]),
    "build/rc/symbol_map.json": (
        "racer",
        ["--game", "game/racer", "--features-dir", "engine/features"]),
    "build/rs/symbol_map.json": (
        "railshooter",
        ["--game", "game/railshooter", "--features-dir", "engine/features"]),
    "build/mo/symbol_map.json": (
        "m7_oshoot",
        ["--game", "game/m7_oshoot", "--features-dir", "engine/features"]),
    "build/m7f/symbol_map.json": (
        "mode7_flight",
        ["--game", "game/mode7_flight", "--features-dir", "engine/features"]),
    "build/probe_map/symbol_map.json": (
        "probes", ["--game", "vendor/probes/probe_vblank"]),
    "build/colmap_map/symbol_map.json": (
        "probe-colmap", ["--game", "vendor/probes/probe_colmap"]),
}

# The build subdir a module names, as it is written in source:
#   SUPERFORGE / "build" / "mz" / "symbol_map.json"
_SUBDIR_MAP = {"mz": "build/mz/symbol_map.json",
               "rm": "build/rm/symbol_map.json",
               "bk": "build/bk/symbol_map.json",
               "sh": "build/sh/symbol_map.json",
               "hud": "build/hud/symbol_map.json",
               "pl": "build/pl/symbol_map.json",
               "sv": "build/sv/symbol_map.json",
               "m7dg": "build/m7dg/symbol_map.json",
               "m7x": "build/m7x/symbol_map.json",
               "sh2": "build/sh2/symbol_map.json",
               "shp": "build/shp/symbol_map.json",
               "shg": "build/shg/symbol_map.json",
               "rc": "build/rc/symbol_map.json",
               "m7c": "build/m7c/symbol_map.json",
               "rs": "build/rs/symbol_map.json",
               "mo": "build/mo/symbol_map.json",
               "m7f": "build/m7f/symbol_map.json",
               "rpg": "build/rpg/symbol_map.json",
               "pfs": "build/pfs/symbol_map.json",
               "scr": "build/scr/symbol_map.json",
               "cf": "build/cf/symbol_map.json",
               "maze": "build/maze/symbol_map.json",
               "jr": "build/jr/symbol_map.json",
               "pat": "build/pat/symbol_map.json",
               "sprg": "build/sprg/symbol_map.json",
               "st": "build/st/symbol_map.json",
               "sr": "build/sr/symbol_map.json",
               "br": "build/br/symbol_map.json",
               "shm": "build/shm/symbol_map.json",
               "shp3": "build/shp3/symbol_map.json",
               "svd": "build/svd/symbol_map.json",
               "svs": "build/svs/symbol_map.json",
               "sit": "build/sit/symbol_map.json",
               "shd": "build/shd/symbol_map.json",
               "probe_map": "build/probe_map/symbol_map.json",
               "colmap_map": "build/colmap_map/symbol_map.json"}

# A read, as opposed to merely naming a path.
_READS = {"read_text", "read_bytes", "open", "load", "loads"}

# path -> the refusal text for that module, or None. A dict rather than a set
# because `pytest_make_collect_report` fires for the Module node AND for every
# Class node inside it, so the answer has to be remembered, not just the fact
# that the question was asked.
_module_seen: dict = {}
_verdict_cache: dict = {}


def _strings_and_names(stmt):
    strings, names = set(), set()
    for node in ast.walk(stmt):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.add(node.value)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return strings, names


def _map_of(strings) -> str:
    sub = next((d for d in _SUBDIR_MAP if d in strings), None)
    return _SUBDIR_MAP[sub] if sub else "build/symbol_map.json"


def _maps_read_by(stmt, bindings=()) -> set:
    """The MAPS a statement (or function body) both names and READS.

    `bindings` carries module-level `NAME = <...symbol_map.json>` path
    constants, so the split form

        MAP  = ROOT / "build" / "mz" / "symbol_map.json"
        SYMS = json.loads(MAP.read_text())

    is seen as the read it is — the path and the read are two statements and
    only the second one touches disk.
    """
    strings, names = _strings_and_names(stmt)
    if not (names & _READS):
        return set()
    if "symbol_map.json" in strings:
        return {_map_of(strings)}
    return {m for n, m in dict(bindings).items() if n in names}


def _called_names(stmt) -> set:
    return {n.func.id for n in ast.walk(stmt)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def maps_named_in(text: str) -> set:
    """Which of MAPS a module reads AT COLLECTION TIME.

    Collection time is the whole point, and it is why this parses rather than
    greps. The guard exists because a module-level read happens BEFORE any
    fixture can `make` anything. A read inside a FIXTURE is a different
    animal: `tests/test_col_map.py`'s `probe` fixture runs `make probe-colmap`
    and then reads the map it just built, so demanding that map up front would
    refuse a module perfectly capable of looking after itself — which is what
    a line-based version of this did on a CI run, where
    `build/colmap_map/` legitimately does not exist until that fixture runs.

    Two shapes count, and both are real in this suite:

      * the read written at module scope
        (`test_c2_slice_c.py:40`, the module that reported the bug),
      * a module-scope CALL to a module-level helper that does the read
        (`test_room_window.py:56`, `_SYMS = _room_symbols()`), and
      * a module-scope read THROUGH a module-level path constant
        (`MAP = ... ; SYMS = json.loads(MAP.read_text())` — the shape three
        modules already use, so far only from inside their fixtures).

    One level of indirection, not a call graph: that is the pattern the tree
    actually uses, and a fixture is excluded by the same rule for the right
    reason — nothing calls it at module scope.

    Naming a path is not reading one, so a statement must also contain a read
    idiom; `P = ROOT / "build" / "mz" / "symbol_map.json"` touches no disk.
    """
    if "symbol_map.json" not in text:
        return set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()

    # module-level path constants: NAME = <expr naming a symbol_map.json>
    bindings = {}
    for st in tree.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 \
                and isinstance(st.targets[0], ast.Name):
            strings, names = _strings_and_names(st)
            if "symbol_map.json" in strings and not (names & _READS):
                bindings[st.targets[0].id] = _map_of(strings)

    helpers = {st.name: _maps_read_by(st, bindings) for st in tree.body
               if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))}
    named = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            continue
        named |= _maps_read_by(stmt, bindings)
        for fn in _called_names(stmt):
            named |= helpers.get(fn, set())
    return named & set(MAPS)


def verdict(rel_map: str, _cache=True):
    """None when the map matches the current declarations; else the reason."""
    if _cache and rel_map in _verdict_cache:
        return _verdict_cache[rel_map]
    committed = SUPERFORGE / rel_map
    if not committed.exists():
        reason = "is MISSING"
    else:
        _, argv = MAPS[rel_map]
        tmp = Path(tempfile.mkdtemp(prefix="sfmapchk-"))
        try:
            r = subprocess.run(
                [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
                 *argv, "--out", str(tmp)],
                cwd=SUPERFORGE, capture_output=True, text=True)
            fresh = tmp / "symbol_map.json"
            if r.returncode != 0:
                reason = ("cannot be current — the allocator REFUSES today's "
                          "declarations:\n      "
                          + (r.stderr or r.stdout).strip()[:500])
            elif not fresh.exists():
                reason = "cannot be checked — the allocator emitted no map"
            elif fresh.read_bytes() != committed.read_bytes():
                reason = ("is STALE — its bytes differ from what today's "
                          "declarations emit, so it was built from an older "
                          "tree")
            else:
                reason = None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if _cache:
        _verdict_cache[rel_map] = reason
    return reason


def _commands_for(maps) -> str:
    targets, seen = [], set()
    for m in sorted(maps):
        t = MAPS[m][0]
        if t not in seen:
            seen.add(t)
            targets.append(t)
    return "make " + " ".join(targets)


def module_map_refusal(path) -> Optional[str]:
    """The guard's verdict for one test module's maps, as text, or None.

    Split out from the hook so the DECISION (which maps, and are they current)
    is testable without a pytest session, and so the hook below is only about
    REPORTING. Memoised per path: `pytest_make_collect_report` fires for the
    Module node and again for every Class inside it, and the verdict costs an
    allocator subprocess.
    """
    if path is None or path.suffix != ".py" \
            or not path.name.startswith("test_"):
        return None
    key = str(path)
    if key in _module_seen:
        return _module_seen[key]
    try:
        text = path.read_text()
    except OSError:
        _module_seen[key] = None
        return None
    wanted = maps_named_in(text)
    problems = [f"{m} {r}" for m in sorted(wanted) if (r := verdict(m))]
    msg = None
    if problems:
        try:
            rel = path.relative_to(SUPERFORGE).as_posix()
        except ValueError:                      # a module outside the repo
            rel = path.name
        msg = ("build/ symbol maps stale or missing — run "
               "`make toy microzero room`\n"
               + "\n".join(f"  - {p}" for p in problems)
               + f"\n  ({rel} reads them at module scope, so this fails at "
               f"COLLECTION rather than as a KeyError inside a test.)"
               f"\n  Minimal fix for this module: {_commands_for(wanted)}")
    _module_seen[key] = msg
    return msg


@pytest.hookimpl(tryfirst=True)
def pytest_make_collect_report(collector):
    """Refuse a module whose maps are stale — as a COLLECTION ERROR.

    WHAT THIS REPLACED, and why the replacement is about REPORTING and not
    about the refusal. This was a `raise pytest.UsageError` from
    `pytest_collectstart`. The refusal was right and stays exactly as strict:
    no test in the session runs, the exit code is non-zero, and the check
    still lands BEFORE the module is imported, so it beats the `KeyError`
    five frames down a collection traceback that it exists to replace.
    `pytest_make_collect_report` is called by `collect_one_node` immediately
    after `pytest_collectstart` and immediately before `collector.collect()`,
    which is where the import happens — the same window, one hook later.

    What was wrong was the SHAPE of the failure. `pytest_collectstart` is
    called outside the `CallInfo` that protects `collector.collect()`, so an
    exception raised there is not a collection error, it is an exception
    escaping the collection loop. Single-process, pytest turns that into a
    usage error and prints our message, which is fine. UNDER XDIST the worker
    process DIES holding whichever item it had been handed, and the controller
    reports:

        INTERNALERROR> ... assert not crashitem, (crashitem, node)
        INTERNALERROR> AssertionError: ('tests/test_allocator.py::...',
                                        <WorkerController gw0>)
        no tests ran

    — naming a pure-Python module that passes alone, never naming the module
    with the stale map, and never printing the map or the `make` command. It
    reads like a build race and is not one. `make test` takes the rail list as
    prerequisites so the front door cannot reach this state, but
    `pytest tests/ -k something -n 4` is what people type while iterating, and
    that path still produced the misattribution. the spec states it as a
    residual; this is the fix.

    Returning a FAILED `CollectReport` instead of raising is what xdist
    survives: the report is a first-class collection error, it travels to the
    controller through the ordinary channel with the right nodeid attached,
    and the session still stops before any test runs ("Interrupted: N error
    during collection"). The hook is `firstresult`, so returning None defers
    to pytest's own implementation and a healthy tree pays nothing beyond the
    memoised verdict.

    Exit code moves 4 (USAGE_ERROR) -> 2 (INTERRUPTED). Both are hard stops
    and nothing in the repo tests for 4; `make test` reads a true rc either
    way.
    """
    problem = module_map_refusal(getattr(collector, "path", None))
    if problem is None:
        return None
    return pytest.CollectReport(
        nodeid=collector.nodeid,
        outcome="failed",
        # the module name is in the ERROR header pytest prints, and is
        # repeated INSIDE the message so it survives xdist's transport, a
        # `grep`, and a log tail that clipped the header
        longrepr=f"{collector.nodeid}: {problem}",
        result=[])


def pytest_collection_modifyitems(session, config, items):
    """Keep the refusal a REFUSAL under xdist, not a footnote.

    Changing the failure's shape changed its REACH, and the second half is
    not free. Serially, a failed `CollectReport` still stops everything:
    `_pytest/main.py::pytest_runtestloop` raises `Interrupted("N error(s)
    during collection")` before the first test, because a collection error
    increments `session.testsfailed`. UNDER XDIST that loop is replaced by
    `DSession.pytest_runtestloop`, which has no such check — so the first
    version of this fix turned a hard stop into `6 passed, 1 error`. The exit
    code was still non-zero, so nothing would have shipped green; but on a
    cold tree, where EIGHT modules read maps, it would have meant running
    ~1,500 tests against ROMs that do not exist and reading the answer out of
    the wreckage. The whole point of a collection-time guard is to fail before
    that.

    So: when any module refused, drop the items. Both workers compute the same
    refusals from the same tree, so their collections stay identical (xdist
    requires that) and both come back empty — nothing runs, the ERROR reports
    still travel, and `session.shouldstop` gives the controller a reason to
    print. Serially this is a no-op in effect: `Interrupted` is raised from
    the runtestloop before an empty item list could matter, so that message is
    unchanged.

    `--continue-on-collection-errors` is honoured, because it is the
    documented way to say "I know, run the rest anyway" — and a guard that
    ignores its own escape hatch is one people route around.
    """
    if config.getoption("continue_on_collection_errors", False):
        return
    refused = sorted(p for p, msg in _module_seen.items() if msg)
    if not refused:
        return
    items[:] = []
    session.shouldstop = (
        f"{len(refused)} module(s) refused at collection: their build/ symbol "
        f"map is stale or missing (see the ERROR block(s) above for the map "
        f"and the `make` line). Nothing was run.")
