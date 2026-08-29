#!/usr/bin/env python3
"""
falsify.py — the falsification harness: make a silently-no-op'd plant impossible.

WHY THIS EXISTS. "Trusting a green test you have not tried to break" is on
AGENTS.md's anti-pattern list, and this repo does try — `tools/falsify_*.py`
are hand-rolled plant scripts, one per work item. The ritual keeps failing in the
SAME way: **the plant does not reach the thing under test, and nothing says so.**

Three instances in one batch alone. The worst one left its test GREEN and was
caught only by md5'ing the artifact by hand: the plant swapped a file in with
`shutil.copy2`, which PRESERVES MTIME, so `make` saw nothing newer and skipped
the rebuild — the test then ran against the OLD binary and passed, while the
script's `assert old in src` guard sat there quietly confirming the source had
been edited. The guard was true. The conclusion drawn from it was false.

The distinction this harness exists to draw:

    a failure of the TEST   — "the assertion cannot see this defect" (a hole)
    a failure of the PLANT  — "the defect never reached the assertion" (noise)

Reported separately, always, because they call for opposite responses:
the first is a test to strengthen, the second is a plant to fix. A harness
that conflates them turns a broken plant into a false "the gate is fine".

--------------------------------------------------------------------------
THE SEQUENCE — every step is checked, and any step failing is a PLANT failure
--------------------------------------------------------------------------

  0. baseline   build the artifact; record md5_before. A baseline that will
                not build cannot falsify anything.
  1. snapshot   the target file's bytes, IN MEMORY. Restore is by copy, never
                by `git checkout` — a git restore silently discards
                uncommitted work wrapped around the plant (AGENTS.md).
  2. patch      `old` must be present (or `content` given for a whole-file
                swap). Absent anchor -> PLANT-NOT-APPLIED.
  3. REBUILD    and require md5(artifact) != md5_before.
                *** THIS IS THE STEP THAT WAS MISSING. ***
                An unchanged artifact means the plant never reached the
                binary the test loads -> PLANT-DID-NOT-REACH-ARTIFACT.
                Every file this harness writes gets an explicit
                `os.utime(now)` first, so an mtime-preserving copy cannot
                make `make` skip; the md5 check is the backstop that does not
                depend on getting that right.
                A rebuild that FAILS is PLANT-BROKE-THE-BUILD — which is a
                legitimate OUTCOME for a plant aimed at a build-time gate
                (see `expect="build-fails"`), and a plant failure otherwise.
  4. run        the named tests. Expected RED. Green -> TEST-BLIND, the
                finding this whole exercise is for.
  5. restore    write the snapshot back, rebuild, and require
                md5(artifact) == md5_before. Not returning is
                RESTORE-INCOMPLETE and the tree is left dirty ON PURPOSE with
                a loud message: a harness that hides a failed restore is
                worse than one that never restored.

--------------------------------------------------------------------------
DEFINING PLANTS
--------------------------------------------------------------------------

A plant set is a Python module under `tools/plants/` exposing `PLANTS`, a list
of `Plant`. `make falsify` runs every set; `make falsify SET=col_map_binding`
runs one. See `tools/plants/col_map_binding.py` for a worked example.

    Plant(id="...", file=..., old="...", new="...",
          artifact=BUILD/"microzero.sfc", build=["microzero"],
          tests=["tests/test_x.py::test_y"], why="...")

`expect` picks what "fired" means:
    "test-red"    (default) the named tests must FAIL after the rebuild.
    "build-fails" the REBUILD must fail, and its output must contain
                  `build_names` — for gates that live in the assembler
                  (a ca65 `.error`, an allocator refusal). The artifact-md5
                  check is skipped, because there is no new artifact; the
                  restore check still runs.

--------------------------------------------------------------------------
WHAT THIS HARNESS DOES NOT DO
--------------------------------------------------------------------------

  * It does not know whether your plant is a REALISTIC defect. A plant that
    breaks something no reasonable change would break proves little; that
    judgement stays with the author, and is why `why=` is required.
  * It cannot restore an uncommitted edit made by ANOTHER process while it
    holds the tree. Do not run it beside a suite.
  * It is not crash-atomic. A SIGKILL mid-plant leaves the planted text on
    disk; `git status` shows it and `git checkout -- <file>` fixes it, which
    is the same recovery `tools/falsify_col_map.py` documents.
  * An artifact md5 that CHANGES proves the plant reached the build, not that
    it reached the code path the test exercises. That is what step 4 is for,
    and why a still-green test is reported as a finding rather than swallowed.

Exit: 0 iff every selected plant FIRED and the tree restored exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
PLANT_DIR = SUPERFORGE / "tools" / "plants"


# --- verdicts ---------------------------------------------------------------
# Split deliberately into PLANT failures and TEST findings.
FIRED = "FIRED"
TEST_BLIND = "TEST-BLIND"                       # a finding about the test
PLANT_NOT_APPLIED = "PLANT-NOT-APPLIED"         # ...the rest are about the plant
PLANT_NO_REACH = "PLANT-DID-NOT-REACH-ARTIFACT"
PLANT_BROKE_BUILD = "PLANT-BROKE-THE-BUILD"
PLANT_WRONG_ERROR = "PLANT-BUILD-FAILED-UNNAMED"
BASELINE_RED = "BASELINE-WOULD-NOT-BUILD"
RESTORE_BAD = "RESTORE-INCOMPLETE"
# A plant naming a test that does not exist. pytest exits NON-ZERO for an
# unresolvable node id, so without this the run reads FIRED — the harness's own
# worst failure mode, a green light for an assertion nobody wrote. Caught on
# smelter, where a rename left `table-column-lead-removed` pointing at a case
# that no longer existed and the plant reported FIRED with "(no match in any
# of ...)" as its evidence.
TEST_MISSING = "PLANT-NAMES-NO-TEST"

PLANT_FAILURES = {PLANT_NOT_APPLIED, PLANT_NO_REACH, PLANT_BROKE_BUILD,
                  PLANT_WRONG_ERROR, BASELINE_RED, RESTORE_BAD, TEST_MISSING}


@dataclass
class Plant:
    id: str
    file: Path
    artifact: Path
    build: list[str]
    why: str
    old: Optional[str] = None
    new: Optional[str] = None
    content: Optional[str] = None       # whole-file swap (the copy2 shape)
    tests: list[str] = field(default_factory=list)
    # The tree `make` and `pytest` run in. Defaults to this repo — a plant
    # against the shipping tree is the normal case. A test that plants into a
    # SHARED artifact (build/toy.sfc, build/microzero.sfc) while an xdist
    # suite is using it must point this at a copied sandbox instead: rebuilding
    # a ROM another worker is loading gives that worker a truncated file and a
    # machine frozen at frame 0, attributed to the victim.
    root: Optional[Path] = None
    expect: str = "test-red"            # "test-red" | "build-fails"
    build_names: Optional[str] = None   # required substring of a failing build

    def __post_init__(self):
        if self.content is None and (self.old is None or self.new is None):
            raise ValueError(f"{self.id}: give old+new, or content")
        if self.expect == "test-red" and not self.tests:
            raise ValueError(f"{self.id}: expect=test-red needs tests")
        if self.expect == "build-fails" and not self.build_names:
            raise ValueError(f"{self.id}: expect=build-fails needs build_names")
        if not self.why:
            raise ValueError(f"{self.id}: `why` is required — a plant whose "
                             f"realism nobody stated proves little")


@dataclass
class Result:
    plant: Plant
    verdict: str
    detail: str = ""


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else "(absent)"


def write_now(path: Path, text: str) -> None:
    """Write, then stamp mtime to NOW.

    The mtime stamp is the whole point. `shutil.copy2` preserves the SOURCE's
    mtime, so a plant swapped in that way can be OLDER than the artifact —
    `make` then skips the rebuild and the test runs against the unplanted
    binary while every source-side guard reads true. This has happened here.
    (The md5 check downstream is the backstop; this is the fix.)
    """
    path.write_text(text)
    now = time.time()
    os.utime(path, (now, now))


def make(targets: list[str], root: Optional[Path] = None) -> tuple[bool, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    r = subprocess.run(["make", *targets], cwd=root or SUPERFORGE, env=env,
                       capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def run_tests(nodes: list[str], root: Optional[Path] = None) -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-m", "pytest", *nodes,
                        "-q", "--no-header"],
                       cwd=root or SUPERFORGE, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _tail(out: str, n: int = 1) -> str:
    lines = [l for l in out.splitlines() if l.strip()]
    return " | ".join(lines[-n:]) if lines else ""


def run_plant(p: Plant, verbose: bool = True) -> Result:
    def say(*a):
        if verbose:
            print(*a, flush=True)

    say(f"--- plant {p.id}")
    say(f"    why: {p.why}")

    # 0. baseline
    ok, out = make(p.build, p.root)
    if not ok:
        return Result(p, BASELINE_RED, _tail(out, 3))
    before = md5(p.artifact)
    say(f"    baseline artifact {before}  {p.artifact.name}")

    # 1. snapshot IN MEMORY (never `git checkout` — AGENTS.md)
    original = p.file.read_text()

    # 2. patch
    if p.content is not None:
        planted = p.content
        if planted == original:
            return Result(p, PLANT_NOT_APPLIED,
                          "`content` is identical to the file on disk")
    else:
        if p.old not in original:
            return Result(p, PLANT_NOT_APPLIED,
                          f"anchor not found in {p.file.name}: {p.old[:60]!r}")
        planted = original.replace(p.old, p.new, 1)
        if planted == original:
            return Result(p, PLANT_NOT_APPLIED, "old == new: the patch is a no-op")

    verdict, detail = FIRED, ""
    try:
        write_now(p.file, planted)

        # 3. REBUILD, and require the artifact to have MOVED.
        built, bout = make(p.build, p.root)
        if p.expect == "build-fails":
            if built:
                verdict, detail = TEST_BLIND, "the build ACCEPTED the plant"
            elif p.build_names not in bout:
                first = next((l.strip() for l in bout.splitlines()
                              if ": Error:" in l or "FAILED" in l), _tail(bout))
                verdict, detail = (PLANT_WRONG_ERROR,
                                   f"build failed WITHOUT {p.build_names!r}: {first}")
            else:
                verdict, detail = FIRED, f"build refused, naming {p.build_names!r}"
        elif not built:
            verdict, detail = PLANT_BROKE_BUILD, _tail(bout, 3)
        else:
            after = md5(p.artifact)
            say(f"    planted  artifact {after}")
            if after == before:
                verdict = PLANT_NO_REACH
                detail = (f"{p.artifact.name} md5 is UNCHANGED after the "
                          f"rebuild — the plant never reached the binary the "
                          f"test loads, so a green test below would mean "
                          f"nothing. (This is the failure mode this gate exists for: an "
                          f"mtime-preserving copy makes `make` a no-op.)")
            else:
                # 4. the tests must go RED
                rc, tout = run_tests(p.tests, p.root)
                if rc == 4 or "no tests ran" in tout or "no match in any" in tout:
                    # pytest's USAGE_ERROR, or a node id it could not resolve.
                    # Non-zero, so this would otherwise read as the defect
                    # being caught.
                    verdict = TEST_MISSING
                    detail = ("the plant names a test that does not exist, so "
                              "nothing was actually run — a rename is the "
                              f"usual cause. {_tail(tout, 2)}")
                elif rc == 0:
                    verdict = TEST_BLIND
                    detail = ("the named test(s) stayed GREEN against a "
                              "planted defect that DID reach the artifact — "
                              f"the assertion cannot see it. {_tail(tout)}")
                else:
                    verdict, detail = FIRED, _tail(tout)
    finally:
        # 5. restore by copy, then prove the artifact came back.
        write_now(p.file, original)
        rok, rout = make(p.build, p.root)
        restored = md5(p.artifact)
        if not rok or restored != before:
            verdict = RESTORE_BAD
            detail = (f"artifact is {restored}, wanted {before} "
                      f"(rebuild {'ok' if rok else 'FAILED'}). THE TREE MAY BE "
                      f"DIRTY — check `git status` and `git diff`. "
                      f"{_tail(rout, 2)}")

    say(f"    {verdict}  {detail}")
    return Result(p, verdict, detail)


def load_sets(names: list[str]) -> list[tuple[str, list[Plant]]]:
    out = []
    files = sorted(PLANT_DIR.glob("*.py"))
    for f in files:
        if f.name.startswith("_"):
            continue
        name = f.stem
        if names and name not in names:
            continue
        spec = importlib.util.spec_from_file_location(f"plants_{name}", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out.append((name, list(mod.PLANTS)))
    if names and not out:
        raise SystemExit(f"falsify: no plant set named {names}; have "
                         f"{[f.stem for f in files]}")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="run falsification plants; report plant failures and test "
                    "findings SEPARATELY.")
    ap.add_argument("sets", nargs="*", help="plant set names (default: all)")
    ap.add_argument("--only", default=None,
                    help="substring filter on plant ids")
    ap.add_argument("--list", action="store_true", help="list plants and exit")
    a = ap.parse_args(argv)

    sets = load_sets(a.sets)
    selected = [(sn, p) for sn, plants in sets for p in plants
                if not a.only or a.only in p.id]
    if a.list:
        for sn, p in selected:
            print(f"{sn}/{p.id}  -> {p.expect}  {p.tests or p.build_names}")
        return 0
    if not selected:
        raise SystemExit("falsify: nothing selected")

    results = [run_plant(p) for _, p in selected]

    print("\n" + "=" * 78)
    for r in results:
        print(f"{r.verdict:<30} {r.plant.id}")
    print("=" * 78)

    fired = [r for r in results if r.verdict == FIRED]
    blind = [r for r in results if r.verdict == TEST_BLIND]
    broken = [r for r in results if r.verdict in PLANT_FAILURES]

    print(f"{len(fired)}/{len(results)} plants FIRED.")
    if blind:
        print("\nTEST FINDINGS — the plant reached the artifact and the "
              "assertion still passed. These are HOLES IN THE TESTS:")
        for r in blind:
            print(f"  {r.plant.id}\n      {r.detail}\n      why: {r.plant.why}")
    if broken:
        print("\nPLANT FAILURES — the defect never reached the assertion, so "
              "these say NOTHING about the tests. Fix the plant:")
        for r in broken:
            print(f"  {r.plant.id}: {r.verdict}\n      {r.detail}")

    dirty = subprocess.run(["git", "status", "--short"], cwd=SUPERFORGE,
                           capture_output=True, text=True).stdout.strip()
    print(f"\ngit status after restore: {dirty or '(clean)'}")
    return 0 if (not blind and not broken) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
