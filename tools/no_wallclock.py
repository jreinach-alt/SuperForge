#!/usr/bin/env python3
"""
no_wallclock.py — the time-coupling lint.

WHY THIS EXISTS. `AGENTS.md` has said for two work items that "`run_frames` /
`set_input` are wall-clock and are for interactive verification only — a
measurement or capture calibrated against them drifts with host load", and the
dx-suite-time work item claimed to have closed the class. It had not:
on `main` at 2026-08-05 there were 22 wall-clock CALL sites across 12 files
under `tests/` + `tools/`, and one batch alone diagnosed five load-sensitivity
failures the expensive way — a red, an hour of triage, a root cause.

The gap was philosophical, and this repo already knows the answer. A hardcoded
address is *impossible* here (`allocator/no_literals.py`). A width bug is
*visible* (`tools/width_lint.py`). The class that has cost the most was
prevented by PROSE. This is the gate that was missing.

Deliberately built on `width_lint.py`'s shape — same CLI, same baseline
mechanism, same override grammar — because that is the shape this repo already
knows how to operate. If you have run `make width-check`, you have run this.

--------------------------------------------------------------------------
THE CHECKS
--------------------------------------------------------------------------

  Check 1: `wallclock-sleep`
           A `time.sleep(...)` call. Sleeping is a measurement of the host,
           not of the machine under test.

  Check 2: `wallclock-run-frames`
           A `.run_frames(n)` call. It sleeps n/60 WALL seconds beside a core
           that advances on its own thread: it buys ~4x its argument under
           free-run and **zero** on a parked runner. `wait_frames(n)` /
           `frame_step(n)` are the emulated-frame equivalents.

  Check 3: `wallclock-run-seconds`
           A `run_seconds=` keyword. `load_rom(rom, run_seconds=2.0)` gives
           the ROM a different amount of boot on every host.
           `boot_rom(rom, frames=N)` is the emulated-frame equivalent, and
           `boot_to_frame(rom, N)` is the one that lands on an EXACT absolute
           frame (which is what a screenshot assertion needs).

  Check 4: `wallclock-timeout-s`
           A `timeout_s=` keyword. `run_to_break(timeout_s=)` bounds a
           breakpoint hunt on wall time; `max_frames=` bounds it on the PPU's
           own frame counter. AGENTS.md: "If you add a `run_to_break`, pass
           `max_frames=` — reach for `timeout_s=` only for a wait that is
           genuinely on wall time, and say so in a comment."

  Check 5: `free-run-read`
           A read of emulator state taken while the core is FREE-RUNNING, on a
           path where a wall-clock advance is what calibrated it. Precisely:
           inside one function body, in line order, a read call
           (`read_bytes`, `read_u16`, `take_screenshot`, `snes_*`, …) that is
           reached AFTER a wall-clock advance (checks 1-3) and with the core
           not parked (no `debug_break` / `frame_step` / `frame_stepping()`
           since the last resume or ROM load). That is the exact shape of the
           capture race measured at 58% stale under 6 CPU burners
           (`mesen_runner._park_for_capture`'s docstring).

  Check 6: `bare-override`
           A `# WALL-CLOCK: ok` with no reason text. Rejected — the reason is
           the whole value of the override, and a bare one is how an override
           convention rots into a rubber stamp.

--------------------------------------------------------------------------
THE OVERRIDE
--------------------------------------------------------------------------

    # WALL-CLOCK: ok — <reason text>

within 3 lines before, on, or after the flagged line. Em-dash, en-dash,
double-hyphen, " - " and ": " are all accepted separators; the reason text is
REQUIRED. Legitimate exceptions exist and this is how you express them —
AGENTS.md: "The one deliberate exception is audio, which is a recording of real
time and stays wall-clock". A wait on the filesystem, on a real thread, or on
a deliberate real-time gap is the same kind of case.

Reviewers spot-check the reasons. Rubber-stamping is the regression.

--------------------------------------------------------------------------
WHAT THIS LINT DOES **NOT** CATCH — read this before trusting it
--------------------------------------------------------------------------

Every gate in this repo states its own limits; one that does not is worse than
none. See `docs/45_time_coupling_gate.md` for the full statement. In short:

  1. SINGLE-FILE, SINGLE-FUNCTION. Check 5's park model is per function body.
     A fixture that parks the core and yields it to a test function is
     invisible from that test — the read there reads as unparked-but-not-
     wall-advanced, which is not a finding, so this direction fails SAFE (no
     false positive) and blind (no catch).
  2. IT DOES NOT SEE ACROSS THE CALL BOUNDARY. `D.enter_race(runner, syms)`
     may sleep, park, or resume; this lint does not open it. Helper modules
     (`tests/mz_drive.py`, `tests/plf_drive.py`, `tools/*.py`) are themselves
     scanned, so the sleep is found where it is WRITTEN — but the caller's
     park state is not modelled through it.
  3. IT CANNOT SEE A BUDGET THAT IS ALREADY A NUMBER. `frame_step(30)` where
     the scene needs 40 is a wrong constant, not a wall-clock coupling, and
     no static rule distinguishes them.
  4. IT DOES NOT KNOW WHETHER A CAPTURE LANDS ON AN ABSOLUTE FRAME. A boot
     that free-runs `wait_frames(120)` and captures is legal here and still
     host-dependent by ±2 frames, because `wait_frames` returns ">= n". That
     is Deliverable 2's job (`boot_to_frame`), not this gate's — the two are
     complementary and neither subsumes the other.
  5. NEW WALL-CLOCK VOCABULARY IS INVISIBLE. `time.monotonic()` deadlines,
     `threading.Event.wait(timeout=)`, `subprocess(timeout=)` and
     `select.select` are NOT flagged: every one of them appears in this tree
     for legitimate process-coordination reasons (`test_bare_check.py`,
     `test_repo_tree_lock.py`), and flagging them would have produced a
     baseline of noise that teaches people to ignore the gate. The five names
     above are the ones that couple a TEST OF THE EMULATOR to the host.

--------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------

    python3 tools/no_wallclock.py tests tools
    python3 tools/no_wallclock.py --baseline reports/time_lint_baseline.json tests tools
    python3 tools/no_wallclock.py --json tests
    python3 tools/no_wallclock.py --write-baseline reports/time_lint_baseline.json tests tools

Exit codes:
    0 — no violations (or all overridden / present in the baseline)
    1 — violations found
    2 — usage / IO / syntax error

Directory arguments expand to `**/*.py`, SKIPPING any path with a `fixtures`
component — this lint's own regression fixtures are deliberately-violating
Python and must not be scanned by the live gate.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# --- The vocabulary ---------------------------------------------------------

# Methods whose call is a WALL-CLOCK advance of the machine.
WALL_ADVANCE_METHODS = frozenset({"run_frames"})

# Keyword arguments that hand a wall-clock budget to the harness.
WALL_KEYWORDS = {
    "run_seconds": "wallclock-run-seconds",
    "timeout_s": "wallclock-timeout-s",
}

# Reads of emulator state. A read taken on a free-running core after a
# wall-clock advance is check 5's finding.
READ_METHODS = frozenset({
    "read_byte", "read_bytes", "read_u16", "read_u32", "read_region",
    "read_wram", "read_vram", "read_sram",
    "take_screenshot", "capture_frames",
    "snes_console_state", "snes_dma_state", "snes_internal_regs",
    "snes_cpu_a", "snes_state_snapshot",
    "get_access_counts", "write_count", "get_uninitialized_reads",
    "ppu_frame_count",
})

# Names shared with the filesystem API. `Path(p).read_bytes()` is not a read
# of the emulator, and it appears in this tree beside real captures
# (`test_wait_primitives._raw_composite`). Every MesenRunner read takes at
# least a `mem_type` argument, so arity discriminates them exactly.
FS_AMBIGUOUS_READS = frozenset({"read_bytes", "read_byte", "read_text"})

# Methods that PARK the core (or prove it is parked).
PARK_METHODS = frozenset({"debug_break", "frame_step", "frame_stepping",
                          "_park_for_capture", "_park_at_canonical_scanline",
                          # boot_to_frame free-runs then PARKS on an exact
                          # absolute frame — its net state is parked.
                          "boot_to_frame"})

# Methods that hand the core back to free-run.
RESUME_METHODS = frozenset({"debug_resume", "load_rom", "boot_rom",
                            "load_rom_with_uninit_detection",
                            "run_test", "stop"})

# `run_to_break` resumes the core to hunt a breakpoint and returns parked on a
# hit — it is modelled as a park because a hit is the only path that reads.
PARK_METHODS = PARK_METHODS | {"run_to_break"}


# --- Override grammar (width_lint's, verbatim in shape) ---------------------

# Required form: "# WALL-CLOCK: ok <SEP> <reason text>" where <SEP> is one of
# em-dash —, en-dash –, double-hyphen --, " - ", or ": ". The reason text
# after the separator must be non-empty.
RE_WALLCLOCK_OK = re.compile(
    r"#\s*WALL-CLOCK:\s*ok"
    r"(?:\s*[—–]|\s*--|\s+-\s+|\s*:\s+)"
    r"\s*(\S.*\S|\S)",
    re.IGNORECASE,
)
# Bare "# WALL-CLOCK: ok" with nothing after — rejected.
RE_WALLCLOCK_BARE = re.compile(
    r"#\s*WALL-CLOCK:\s*ok\s*$",
    re.IGNORECASE,
)

OVERRIDE_RADIUS = 3


@dataclass
class Finding:
    file: str
    line: int
    rule: str  # 'wallclock-sleep' | 'wallclock-run-frames'
    #          | 'wallclock-run-seconds' | 'wallclock-timeout-s'
    #          | 'free-run-read' | 'bare-override'
    message: str
    # 'error' gates. There is no 'warn' tier: a gate whose findings do not
    # gate is a report, and this repo has enough of those.
    severity: str = "error"

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
            "severity": self.severity,
        }


def has_override(lines: list[str], lineno: int,
                 window: int = OVERRIDE_RADIUS) -> Optional[str]:
    """The reason text of a valid override within `window` lines of `lineno`
    (1-based), or None. A BARE `# WALL-CLOCK: ok` is not an override."""
    idx = lineno - 1
    lo = max(0, idx - window)
    hi = min(len(lines), idx + window + 1)
    for i in range(lo, hi):
        m = RE_WALLCLOCK_OK.search(lines[i])
        if m:
            return m.group(1).strip()
    return None


def detect_bare_overrides(path: str, lines: list[str]) -> list[Finding]:
    """A `# WALL-CLOCK: ok` with no reason is itself a finding."""
    out = []
    for i, line in enumerate(lines):
        if RE_WALLCLOCK_BARE.search(line) and not RE_WALLCLOCK_OK.search(line):
            out.append(Finding(
                path, i + 1, "bare-override",
                "bare `# WALL-CLOCK: ok` is rejected — the reason text after "
                "the separator is REQUIRED. Say what makes this wait "
                "legitimately wall-clock (a recording of real time, a "
                "filesystem mtime, a real thread) so a reviewer can check it."))
    return out


# --- Call classification ----------------------------------------------------

def _called_name(node: ast.Call) -> str:
    """The bare name of a call target: `r.run_frames(1)` -> 'run_frames',
    `time.sleep(1)` -> 'sleep', `sleep(1)` -> 'sleep'."""
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return ""


def _is_time_sleep(node: ast.Call, sleep_aliases: set[str]) -> bool:
    f = node.func
    if isinstance(f, ast.Attribute) and f.attr == "sleep":
        # time.sleep / asyncio.sleep — both are wall-clock.
        return True
    if isinstance(f, ast.Name) and f.id in sleep_aliases:
        return True
    return False


def _is_emulator_read(node: ast.Call, name: str) -> bool:
    """A READ_METHODS call that is really a read of the machine.

    `Path(png).read_bytes()` shares the name with `runner.read_bytes(mem,
    addr, n)`; the emulator form always passes a `mem_type`, the filesystem
    form takes nothing. Arity is an exact discriminator and needs no
    type inference."""
    if name not in READ_METHODS:
        return False
    if name in FS_AMBIGUOUS_READS and not node.args and not node.keywords:
        return False
    return True


def _sleep_aliases(tree: ast.AST) -> set[str]:
    """Names bound to `time.sleep` by `from time import sleep [as X]`."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("time", "asyncio"):
            for a in node.names:
                if a.name == "sleep":
                    out.add(a.asname or a.name)
    return out


# --- Check 5's per-function park model --------------------------------------

@dataclass
class _Event:
    line: int
    kind: str    # 'wall' | 'park' | 'resume' | 'read'
    name: str


def _function_bodies(tree: ast.AST):
    """Every function/lambda body in the module, innermost first is NOT
    required — nested defs are yielded separately and their events are not
    attributed to the enclosing function (a closure's park state is its own)."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _own_calls(fn: ast.AST) -> list[ast.Call]:
    """Calls lexically inside `fn` but NOT inside a nested function def."""
    out: list[ast.Call] = []

    def walk(node, top=False):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda)) and not top:
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda)) and top:
                continue
            if isinstance(child, ast.Call):
                out.append(child)
            walk(child)

    walk(fn, top=True)
    return out


def _free_run_reads(path: str, tree: ast.AST, lines: list[str],
                    sleep_aliases: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for fn in _function_bodies(tree):
        events: list[_Event] = []
        for call in _own_calls(fn):
            name = _called_name(call)
            line = call.lineno
            if _is_time_sleep(call, sleep_aliases):
                events.append(_Event(line, "wall", "time.sleep"))
                continue
            if name in WALL_ADVANCE_METHODS:
                events.append(_Event(line, "wall", name))
                continue
            if any(kw.arg == "run_seconds" for kw in call.keywords if kw.arg):
                # A run_seconds= load is a wall advance AND a resume.
                events.append(_Event(line, "wall", f"{name}(run_seconds=)"))
                events.append(_Event(line, "resume", name))
                continue
            if name in PARK_METHODS:
                events.append(_Event(line, "park", name))
                continue
            if name in RESUME_METHODS:
                events.append(_Event(line, "resume", name))
                continue
            if _is_emulator_read(call, name):
                events.append(_Event(line, "read", name))

        events.sort(key=lambda e: e.line)
        parked = False
        wall_since_park = None      # the wall advance that calibrated the read
        for ev in events:
            if ev.kind == "park":
                parked, wall_since_park = True, None
            elif ev.kind == "resume":
                parked, wall_since_park = False, None
            elif ev.kind == "wall":
                if not parked:
                    wall_since_park = ev
            elif ev.kind == "read":
                if not parked and wall_since_park is not None:
                    findings.append(Finding(
                        path, ev.line, "free-run-read",
                        f"`{ev.name}` reads a FREE-RUNNING core, and the only "
                        f"thing that placed it in time is the wall-clock "
                        f"`{wall_since_park.name}` on line "
                        f"{wall_since_park.line}. What this reads is a "
                        f"function of host load. Park first "
                        f"(`with r.frame_stepping():` / `debug_break()`), or "
                        f"bound the wait in EMULATED frames "
                        f"(`wait_frames` / `wait_until` / `frame_step`)."))
    return findings


# --- The file pass ----------------------------------------------------------

def lint_file(path: str) -> list[Finding]:
    src = Path(path).read_text()
    lines = src.splitlines()
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        return [Finding(path, e.lineno or 1, "syntax-error",
                        f"could not parse: {e.msg}")]

    aliases = _sleep_aliases(tree)
    raw: list[Finding] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)

        if _is_time_sleep(node, aliases):
            raw.append(Finding(
                path, node.lineno, "wallclock-sleep",
                "`sleep()` blocks on the HOST clock. If this is waiting for "
                "the emulated machine, wait in emulated frames "
                "(`wait_frames` / `wait_until` / `frame_step`); if it is "
                "waiting on a real thread, a file, or a genuine real-time "
                "gap, say so in a `# WALL-CLOCK: ok — <reason>` override."))

        elif name in WALL_ADVANCE_METHODS:
            raw.append(Finding(
                path, node.lineno, "wallclock-run-frames",
                "`run_frames(n)` sleeps n/60 WALL seconds beside a core that "
                "advances on its own thread — it buys ~4x its argument under "
                "free-run and ZERO on a parked runner. Use `wait_frames(n)` "
                "(emulated frames, free-running) or `frame_step(n)` "
                "(emulated frames, parked)."))

        for kw in node.keywords:
            if kw.arg in WALL_KEYWORDS:
                rule = WALL_KEYWORDS[kw.arg]
                if kw.arg == "run_seconds":
                    msg = ("`run_seconds=` gives the ROM a different amount "
                           "of boot on every host. Use `boot_rom(rom, "
                           "frames=N)` for an emulated-frame budget, or "
                           "`boot_to_frame(rom, N)` to land on an EXACT "
                           "absolute frame (what a screenshot assertion "
                           "needs).")
                else:
                    msg = ("`timeout_s=` bounds this wait on the HOST clock. "
                           "Pass `max_frames=` so the bound is the PPU's own "
                           "frame counter — AGENTS.md: reach for `timeout_s=` "
                           "only for a wait that is genuinely on wall time, "
                           "and say so in a comment.")
                raw.append(Finding(path, kw.value.lineno if hasattr(
                    kw.value, "lineno") else node.lineno, rule, msg))

    raw.extend(_free_run_reads(path, tree, lines, aliases))

    # Overrides suppress; bare overrides are their own finding.
    kept = [f for f in raw if has_override(lines, f.line) is None]
    kept.extend(detect_bare_overrides(path, lines))
    # Collapse to the baseline's own key. Two `run_frames` on ONE line are one
    # baseline entry no matter what, so reporting them as two findings would
    # make the printed count disagree with what the baseline can express —
    # and a count that cannot be reconciled with the file is how a baseline
    # starts getting regenerated instead of read.
    seen, out = set(), []
    for f in sorted(kept, key=lambda f: (f.line, f.rule)):
        key = (f.file, f.line, f.rule)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def expand(paths: list[str]) -> list[str]:
    """Directory args expand to **/*.py, skipping any `fixtures` component —
    this lint's own regression fixtures are deliberately-violating Python."""
    files: list[str] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for x in sorted(path.rglob("*.py")):
                if "fixtures" in x.parts or "__pycache__" in x.parts:
                    continue
                files.append(str(x))
        elif path.exists():
            files.append(str(path))
        else:
            raise FileNotFoundError(p)
    return files


def format_finding(f: Finding) -> str:
    return f"{f.file}:{f.line}: [{f.rule}] {f.message}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="the time-coupling lint: wall-clock waits in tests.")
    parser.add_argument("paths", nargs="+", help="Python files or directories")
    parser.add_argument("--baseline", type=str, default=None,
                        help="baseline JSON (grandfathered findings)")
    parser.add_argument("--json", action="store_true",
                        help="emit findings as JSON")
    parser.add_argument("--write-baseline", type=str, default=None,
                        help="write current findings as a new baseline")
    parser.add_argument("--quiet", action="store_true",
                        help="exit code only")
    parser.add_argument("--summary", action="store_true",
                        help="print a per-rule summary after the findings")
    args = parser.parse_args(argv)

    try:
        files = expand(args.paths)
    except FileNotFoundError as e:
        print(f"no_wallclock: file not found: {e}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for f in files:
        findings.extend(lint_file(f))

    n_all = len(findings)

    if args.baseline:
        try:
            base = json.loads(Path(args.baseline).read_text())
        except FileNotFoundError:
            print(f"no_wallclock: baseline not found: {args.baseline}",
                  file=sys.stderr)
            return 2
        base_set = {(b["file"], b["line"], b["rule"]) for b in base}
        findings = [f for f in findings
                    if (f.file, f.line, f.rule) not in base_set]

    if args.write_baseline:
        Path(args.write_baseline).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write_baseline).write_text(
            json.dumps([f.to_dict() for f in findings], indent=2) + "\n")
        if not args.quiet:
            print(f"no_wallclock: wrote baseline ({len(findings)} entries) to "
                  f"{args.write_baseline}")
        return 0

    if not args.quiet:
        if args.json:
            print(json.dumps([f.to_dict() for f in findings], indent=2))
        else:
            for f in findings:
                print(format_finding(f))

        if args.summary:
            from collections import Counter
            counts = Counter(f.rule for f in findings)
            print()
            # The summary says WHAT was examined, not just how much was
            # found — `0 finding(s)` read repo-wide as "no time coupling"
            # is exactly how the prose rule this replaces went stale.
            print(f"no_wallclock: {len(findings)} NEW finding(s) across "
                  f"{len(files)} file(s)"
                  + (f"; {n_all - len(findings)} grandfathered by the baseline"
                     if args.baseline else ""))
            print("  checked: time.sleep / run_frames / run_seconds= / "
                  "timeout_s=, and reads of a\n"
                  "  FREE-RUNNING core calibrated by one of them "
                  "(per-function park model).\n"
                  "  NOT checked: park state across a call or a fixture "
                  "boundary; whether a\n"
                  "  capture lands on an ABSOLUTE frame; wrong frame "
                  "constants; time.monotonic\n"
                  "  deadlines and subprocess/thread timeouts. docs/45 §4.")
            for rule, n in sorted(counts.items()):
                print(f"  {rule}: {n}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
