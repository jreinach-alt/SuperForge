#!/usr/bin/env python3
"""Say WHICH KIND of red a pytest log holds: a tree defect, or the shared
emulator core losing a wall-clock race.

WHY THIS EXISTS. `make bare-check`'s verdict is one bit, and two very
different events set it. A rail that broke sets it. So does a
`MachineError` raised in a fixture's teardown AFTER the test passed,
because the process-global Mesen core did not resume inside a ten-second
HOST deadline on a box running an xdist fleet, sixty-five ROM builds and
a suite that clones this repo six times. Both print RED. Reading which
one you got has cost a forensic dig per run.

The guards below are legitimate — you need SOME way to call a dead core
dead — but every one of them is bounded against the WALL while verifying
against EMULATED progress, so their false-positive rate tracks host load
rather than tree state. That is exactly the property that makes them
worth naming separately in the artifact.

WHAT THIS DOES NOT DO: it does not change a verdict. RED stays RED, the
exit code is untouched, and a `harness-liveness` reading is a note for
the reader, never a pass. A second observation of the same signature is
still a bug report — against the harness rather than against the rail.
"""
from __future__ import annotations

import re
import sys
import pathlib

# (vendor source, message fragment). The fragment must still be present in
# the file it names — tests/test_harness_faults.py asserts every row, so
# this table cannot drift away from the guards it claims to describe while
# quietly reading every fault as a defect.
LIVENESS_GUARDS = (
    ("vendor/mesen_runner.py", "the emulated frame counter has not advanced for"),
    ("vendor/mesen_runner.py", "debug_resume: emulator did not resume free-running"),
    ("vendor/machine.py", "close(): the core did not resume free-running"),
)

_SECTION = re.compile(r"^=+ (FAILURES|ERRORS) =+$")
_OTHER_SECTION = re.compile(r"^=+ [a-z]")
_BANNER = re.compile(r"^_+ (.+?) _+$")
_EXC = re.compile(r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Failure|Timeout))\b")
_PHASE = re.compile(r"^ERROR at (setup|teardown) of ")
_E_LINE = re.compile(r"^E\s")
_FILE = re.compile(r"^(tests/\S+?\.py):\d+")

# Modules that assert ON the guard messages by design: they exist to prove the
# guards fire, so their tracebacks quote the very text below. A red in one of
# them is a red in the guard, which is a defect -- never evidence that the
# core was merely slow. Named rather than left to luck.
GUARD_TEST_MODULES = ("test_park_guard", "test_wait_primitives", "test_machine")


def _reading(lines: list[str], file: str) -> str:
    if file and any(m in file for m in GUARD_TEST_MODULES):
        return "defect"
    # Only `E ` lines count -- that is where pytest puts the RAISED message.
    # The same text appears in a traceback's SOURCE lines whenever the frame
    # that raises is shown (it is, in the wedge fixture), and matching those
    # would read any test that merely displays a guard as a harness fault.
    for line in lines:
        if not _E_LINE.match(line):
            continue
        for _src, frag in LIVENESS_GUARDS:
            if frag in line:
                return "harness-liveness"
    return "defect"


def _finish(raw: dict) -> dict:
    title = raw["title"]
    m = _PHASE.match(title)
    phase = m.group(1) if m else "call"
    test = re.sub(r"^ERROR at (setup|teardown) of ", "", title).strip()
    excs, seen, file = [], set(), ""
    for line in raw["body"]:
        e = _EXC.match(line)
        if e and e.group(1) not in seen:
            seen.add(e.group(1))
            excs.append(e.group(1))
        if not file:
            f = _FILE.match(line)
            if f:
                file = f.group(1)
    return {
        "test": test,
        "file": file,
        "phase": phase,
        "section": raw["section"],
        "exceptions": excs,
        "reading": _reading(raw["body"], file),
    }


def scan(text: str) -> list[dict]:
    """Parse the FAILURES / ERRORS blocks of a pytest log into fault dicts."""
    faults: list[dict] = []
    section = None
    cur: dict | None = None
    for line in text.splitlines():
        m = _SECTION.match(line)
        if m:
            if cur:
                faults.append(cur)
                cur = None
            section = m.group(1)
            continue
        if section is None:
            continue
        if _OTHER_SECTION.match(line):
            if cur:
                faults.append(cur)
                cur = None
            section = None
            continue
        b = _BANNER.match(line)
        # The inner `_ _ _ _` rules match the banner shape; a real banner
        # carries a test name, so require a character that is not one of them.
        if b and b.group(1).strip("_ "):
            if cur:
                faults.append(cur)
            cur = {"section": section, "title": b.group(1).strip(), "body": []}
            continue
        if cur is not None:
            cur["body"].append(line)
    if cur:
        faults.append(cur)
    return [_finish(f) for f in faults]


def summarize(faults: list[dict]) -> str:
    """One word for the whole run: none / defect / harness-liveness / mixed."""
    if not faults:
        return "none"
    kinds = {f["reading"] for f in faults}
    if kinds == {"harness-liveness"}:
        return "harness-liveness"
    if len(kinds) > 1:
        return "mixed"
    return "defect"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(f"usage: {argv[0]} <pytest-log>...", file=sys.stderr)
        return 2
    faults: list[dict] = []
    for arg in argv[1:]:
        p = pathlib.Path(arg)
        if p.exists():
            faults += scan(p.read_text(errors="replace"))
    for f in faults:
        print(f"  {f['reading']:<17} {f['phase']:<8} "
              f"{'/'.join(f['exceptions']) or '?':<28} {f['test']}")
    print(f"reading: {summarize(faults)}  ({len(faults)} fault(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
