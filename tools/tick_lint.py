#!/usr/bin/env python3
"""
tick_lint.py — the FRAME-ASSUMPTION lint.

WHY THIS EXISTS. `docs/95` §5.5 answered `docs/94` §5.5 by enumerating
**185 named sites** that assume one logic tick equals one hardware frame — 27
engine per-frame routines, 135 declared game-state words across 27 rails, 5
frame-indexed asset generators, 18 substrate and harness sites. That number is
the real cost of region speed compensation, and it was previously unknown.

It was also PROSE IN A DOCUMENT, which means it was already rotting: the next
countdown anybody writes is site 186 and no gate notices. This repo has a
settled answer to that shape — `tools/width_lint.py` for a class the assembler
cannot see, `tools/no_wallclock.py` for a class the test runner cannot see —
and this is the same move for the class the ALLOCATOR cannot see. The
allocator proves that two features do not collide in space. Nothing in the
tree proves anything about their unit of TIME.

Deliberately built on `no_wallclock.py`'s shape — same CLI, same baseline
mechanism, same override grammar — because that is the shape this repo already
knows how to operate.

--------------------------------------------------------------------------
WHAT THIS GATE IS FOR, AND WHAT IT IS NOT
--------------------------------------------------------------------------

A finding is NOT a defect. Every rail in this tree ships one tick per frame on
purpose and every one of these sites is correct today. What a finding says is:
*this site would have to be re-decided if the tick ever stopped being the
frame.* The gate's job is to keep that population COUNTED and BOUNDED, so the
185 can only go down, and so a new frame-clocked countdown is a thing somebody
chose in front of a reviewer rather than a thing that appeared.

That is why it is wired as `make tick-check` and is NOT in `make gates` or
`make bare-check`: a gate whose baseline holds 185 entries has to earn its
place before it is allowed to fail a landing.

--------------------------------------------------------------------------
THE CHECKS
--------------------------------------------------------------------------

  Check 1: `tick-state`     game/*/state.toml
           A declared game-state word whose OWN COMMENT names a frame unit —
           frames, tick, timer, clock, anim(ation), countdown, i-frames, or
           8.8 (this kit's per-frame fixed-point rate format). This is
           `docs/95` §5.2's rule, mechanised: the declaration's comment is
           where the author said what the unit was.

  Check 2: `tick-routine`   engine/**/*.asm, game/**/*.asm
           A routine whose name ends `_tick` / `_step` / `_advance` — the
           shape `docs/95` §5.1 derived its 27 from. These are what
           `main.asm`'s four-line loop and the NMI call once per hardware
           frame. Name only, deliberately: a doc-phrase rule was tried and
           it swept in every `obj_place` whose header happens to say "per
           frame", which is a routine that RUNS each frame without COUNTING
           in frames — a different thing, and 45 findings of noise.

  Check 3: `tick-constant`  engine/**, game/**  (.asm/.inc)
           An equate whose NAME carries a frame unit (`*_FRAMES`, `*_RATE`,
           `*_PER_FRAME`) or whose comment gives it one in UNIT SHAPE
           ("px/frame", "per frame", "N frames"). `MXL_STEP_FRAMES =
           MXL_TILE_PX` is the type specimen: a grid slide that is exactly
           TILE_PX frames long at 1 px/frame, with no correct 5/6. The unit
           shape is what separates `ROLL_PEAK_CAP ; 4.0 px/frame` (a rate)
           from `EDGE = 2  # frame line` (a border) — the loose comment rule
           the state check uses would take both.

  Check 4: `tick-generator` tools/gen_*.py
           A build-time table baked against a frame index — a `*_FRAMES`
           constant, a per-frame step, or a comment naming px/frame. These
           tables are correct under a 6:5 tick scheme and WRONG under a
           delta-scale one, so they have to be re-derived either way.

  Check 5: `tick-substrate` anywhere in scope
           The NTSC frame's master-cycle count as a literal (357368 / 357366),
           or a read of the substrate's `frame.ntsc` table by name. Both mean
           "the frame" where they should mean "this region's frame".

  Check 6: `bare-override`
           A `TICK: ok` with no reason text. Rejected, for the same reason
           width_lint and no_wallclock reject theirs: the reason is the whole
           value of an override, and a bare one is how a convention rots into
           a rubber stamp.

--------------------------------------------------------------------------
THE OVERRIDE
--------------------------------------------------------------------------

    ; TICK: ok — <reason text>          (assembly)
    # TICK: ok — <reason text>          (Python, TOML)

within 3 lines before, on, or after the flagged line. Em-dash, en-dash,
double-hyphen, " - " and ": " are all accepted separators, exactly as in
`width_lint.py` and `no_wallclock.py`; the reason text is REQUIRED.

The reason a site legitimately takes: it is region-independent by
construction (a table indexed by something other than time), it is already
expressed as a rate against a declared tick, or it is a frame-unit word in a
context that is not a clock at all.

--------------------------------------------------------------------------
WHAT THIS LINT DOES **NOT** CATCH — read this before trusting it
--------------------------------------------------------------------------

  1. IT IS LEXICAL, NOT SEMANTIC. It finds sites that SAY they are counted in
     frames. A countdown named `t` with no comment, in a rail whose loop runs
     it once per frame, is invisible here and is exactly as frame-coupled as
     one named `t_frames`. The population it bounds is "sites that declare
     their unit", and the honest reading of a clean run is "no NEW site
     declared a frame unit", not "no new site is frame-coupled".
  2. IT CANNOT TELL A RATE FROM AN INTEGER. `docs/95` §5.2's whole point is
     that class A (8.8 rate accumulators, 33 of them) scales cleanly by 5/6
     and classes B and C (30 integer countdowns, 9 small-integer dividers) do
     not. That distinction is a judgement about what the number MEANS and the
     lint does not attempt it — it reports the site and the human classifies.
  3. IT DOES NOT SEE THE CALL GRAPH. Whether a `*_step` routine is actually
     clocked once per frame depends on its caller. `docs/95` §5.1 hand-read
     31 exported routines down to the 27 the frame really clocks; this lint
     reports the shape, not the hand-reduction, so its routine count is a
     superset by construction.
  4. VENDOR IS OUT OF SCOPE. `vendor/` is frozen, and `vendor/mesen_runner.py`
     carries one of `docs/95` §5.4's `357368` sites. That site is real and
     stays uncounted here; §5.4 remains its record.
  5. A CLEAN RUN IS NOT A REGION-CORRECT TREE. Nothing in this gate measures
     anything. `tools/rate_oracle.py` is the instrument that says whether a
     rail's rate actually matches across regions; this one only says whether
     the surface that would have to change has grown.

--------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------

    python3 tools/tick_lint.py engine game tools allocator tests
    python3 tools/tick_lint.py --baseline reports/tick_lint_baseline.json ...
    python3 tools/tick_lint.py --json engine
    python3 tools/tick_lint.py --by-class engine game tools allocator tests
    python3 tools/tick_lint.py --write-baseline reports/tick_lint_baseline.json ...

Exit codes:
    0 — no NEW findings (all overridden or present in the baseline)
    1 — new findings
    2 — usage / IO error

Directory arguments expand over the extensions each check reads, SKIPPING any
path with a `fixtures` component — this lint's own regression fixtures are
deliberately-violating files and must not be scanned by the live gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- The vocabulary ---------------------------------------------------------

# A word that names a unit of FRAMES in a comment. `docs/95` §5.2's rule,
# verbatim: "the declaration's own comment names frames, ticks, a timer, a
# clock, an animation, a countdown, or 8.8".
RE_FRAME_WORD = re.compile(
    r"\b(frames?|ticks?|timers?|clocks?|anim\w*|countdowns?|i-frames?"
    r"|per[- ]frame|px/f\b|px/frame)\b|(?<![\w.])8\.8(?![\w.])",
    re.IGNORECASE)

# A TOML state declaration:  name = "u16@dp"    # comment
RE_TOML_DECL = re.compile(r'^\s*([a-z_][a-z0-9_]*)\s*=\s*"([^"]+)"\s*(?:#(.*))?$')

# A ca65 routine label at column 0.  `rs_burst_step:`
RE_ASM_LABEL = re.compile(r"^([a-z_][a-z0-9_]*)\s*:")
RE_TICK_NAME = re.compile(r"_(tick|step|advance)$")

# A ca65 equate.  `MXL_STEP_FRAMES = MXL_TILE_PX   ; ...`
RE_ASM_EQUATE = re.compile(
    r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*([^;]+?)\s*(?:;(.*))?$")
RE_FRAME_CONST_NAME = re.compile(r"(_FRAMES?$|_RATE$|_PER_FRAME$|^FRAME)")

# A Python module-level constant in a generator.
RE_PY_CONST = re.compile(
    r"^([A-Z_][A-Z0-9_]*)\s*=\s*([^#]+?)\s*(?:#(.*))?$")

# The NTSC frame, as a literal. 357368 is the substrate's pin; 357366 is what
# the machine reads back over a 19-frame window.
RE_FRAME_MC = re.compile(r"(?<![\d.])35736[68](?![\d.])")

# A read of the substrate's NTSC frame table BY NAME.
RE_FRAME_NTSC = re.compile(r'\[\s*["\']frame["\']\s*\]\s*\[\s*["\']ntsc["\']\s*\]'
                           r'|^\s*\[frame\.ntsc\]')

# A UNIT-SHAPED frame phrase, for equates and generator constants. Much
# tighter than RE_FRAME_WORD on purpose: `EDGE = 2  # frame line` is a border,
# not a clock, and `ROLL_FIX = 8  # the 8.8 fraction width` is a shift, not a
# rate. Requiring the plural, or a "per frame" / "/frame" unit, separates
# "this number is measured in frames" from "the word frame appears".
RE_FRAME_UNIT = re.compile(
    r"per[- ]frame|px/f\b|/frame\b|\bframes\b|frame divider|frame index"
    r"|frame count", re.IGNORECASE)

# --- Override grammar (width_lint's, verbatim in shape) ---------------------

RE_TICK_OK = re.compile(
    r"[#;]\s*TICK:\s*ok"
    r"(?:\s*[—–]|\s*--|\s+-\s+|\s*:\s+)"
    r"\s*(\S.*\S|\S)", re.IGNORECASE)
RE_TICK_BARE = re.compile(r"[#;]\s*TICK:\s*ok\s*$", re.IGNORECASE)

OVERRIDE_RADIUS = 3

# Which extensions each scan reads.
ASM_EXT = (".asm", ".inc")
PY_EXT = (".py",)
TOML_EXT = (".toml",)
ALL_EXT = ASM_EXT + PY_EXT + TOML_EXT


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "rule": self.rule,
                "message": self.message, "severity": self.severity}


def has_override(lines: list[str], lineno: int,
                 window: int = OVERRIDE_RADIUS) -> Optional[str]:
    idx = lineno - 1
    for i in range(max(0, idx - window), min(len(lines), idx + window + 1)):
        m = RE_TICK_OK.search(lines[i])
        if m:
            return m.group(1).strip()
    return None


def detect_bare_overrides(path: str, lines: list[str]) -> list[Finding]:
    out = []
    for i, line in enumerate(lines):
        if RE_TICK_BARE.search(line) and not RE_TICK_OK.search(line):
            out.append(Finding(
                path, i + 1, "bare-override",
                "bare `TICK: ok` is rejected — the reason text after the "
                "separator is REQUIRED. Say what makes this site "
                "region-independent (indexed by something other than time; "
                "already a rate against a declared tick; a frame word that is "
                "not a clock) so a reviewer can check it."))
    return out


# --- Check 1: declared game state -------------------------------------------

def _toml_comment_block(lines: list[str], i: int) -> str:
    """A declaration's own comment: the trailing comment on its line plus the
    comment-only continuation lines beneath it, which is how this tree writes
    a two-line unit description."""
    text = ""
    m = RE_TOML_DECL.match(lines[i])
    if m and m.group(3):
        text += m.group(3)
    j = i + 1
    while j < len(lines) and re.match(r"^\s{4,}#", lines[j]):
        text += " " + lines[j].split("#", 1)[1]
        j += 1
    return text


def check_state(path: str, lines: list[str]) -> list[Finding]:
    if not path.replace("\\", "/").endswith("state.toml"):
        return []
    out, inherited = [], False
    for i, line in enumerate(lines):
        m = RE_TOML_DECL.match(line)
        if not m:
            # A blank line or a section header ends a declaration group, so a
            # bare companion cannot inherit across it.
            if not line.strip() or line.lstrip().startswith("["):
                inherited = False
            continue
        doc = _toml_comment_block(lines, i)
        hit = RE_FRAME_WORD.search(doc)
        own = (m.group(3) or "").strip()
        if hit:
            unit, inherited = repr(hit.group(0).strip()), True
        elif not own and inherited:
            # A BARE COMPANION: `stepy` directly under `stepx  # this frame's
            # x step`. It has no comment of its own because it shares the one
            # above, and it is exactly as frame-coupled. Reproducing docs/95
            # §5.2's 135 needs these three (m7_dungeon:stepy, m7_oshoot:stepy,
            # mode7_explore:step_dy) — without them the doc's own stated rule
            # mechanises to 132.
            unit = "inherited from the declaration above"
        else:
            inherited = False
            continue
        out.append(Finding(
            path, i + 1, "tick-state",
            f"`{m.group(1)}` is declared in a frame unit ({unit}). One tick "
            f"is one frame here; if that ever stops being true this word "
            f"needs a rounding decision, and docs/95 §5.2 measured that 39 "
            f"of these have no correct x5/6."))
    return out


# --- Check 2 + 3: engine routines and constants -----------------------------

def _asm_doc_above(lines: list[str], i: int, n: int = 4) -> str:
    return " ".join(lines[max(0, i - n):i + 1])


def check_asm(path: str, lines: list[str]) -> list[Finding]:
    out = []
    for i, line in enumerate(lines):
        lab = RE_ASM_LABEL.match(line)
        if lab and RE_TICK_NAME.search(lab.group(1)):
            name = lab.group(1)
            out.append(Finding(
                path, i + 1, "tick-routine",
                f"`{name}` is a per-frame routine by name. The kit's only "
                f"clock is the NMI, and main.asm's loop calls one of these "
                f"once per hardware frame — so its unit of time is the "
                f"frame, not a declared tick."))
        eq = RE_ASM_EQUATE.match(line)
        if eq and not line.lstrip().startswith(";"):
            name, val, cmt = eq.group(1), eq.group(2), eq.group(3) or ""
            by_name = RE_FRAME_CONST_NAME.search(name)
            by_doc = RE_FRAME_UNIT.search(cmt)
            if by_name or by_doc:
                why = "its name" if by_name else "its comment"
                out.append(Finding(
                    path, i + 1, "tick-constant",
                    f"`{name} = {val}` carries a frame unit in {why}. A "
                    f"constant measured in frames is the hardest class to "
                    f"region-scale — docs/95 §5.1 names "
                    f"`MXL_STEP_FRAMES = MXL_TILE_PX` as the specimen: at "
                    f"x6/5 it is 1.2 px/frame, which the grid cannot express."))
    return out


# --- Check 4: build-time generators -----------------------------------------

def check_generator(path: str, lines: list[str]) -> list[Finding]:
    p = path.replace("\\", "/")
    if not (p.startswith("tools/gen_") or "/gen_" in p):
        return []
    out = []
    for i, line in enumerate(lines):
        m = RE_PY_CONST.match(line)
        if not m:
            continue
        name, val, cmt = m.group(1), m.group(2), m.group(3) or ""
        by_name = RE_FRAME_CONST_NAME.search(name)
        by_doc = RE_FRAME_UNIT.search(cmt)
        if by_name or by_doc:
            out.append(Finding(
                path, i + 1, "tick-generator",
                f"`{name} = {val.strip()}` bakes a table against a FRAME "
                f"index at build time. docs/95 §5.3: a 6:5 tick scheme leaves "
                f"these correct (a tick indexes a row); a delta-scale scheme "
                f"requires every one regenerated at 5/6 length with new "
                f"steps, and each has a bit-exact Python mirror that must be "
                f"re-calibrated with it."))
    return out


# --- Check 5: substrate and harness -----------------------------------------

def check_substrate(path: str, lines: list[str]) -> list[Finding]:
    out = []
    for i, line in enumerate(lines):
        if RE_FRAME_MC.search(line):
            out.append(Finding(
                path, i + 1, "tick-substrate",
                "the NTSC frame's master-cycle count as a literal. A PAL "
                "frame is 425,568 mc (measured); every percent-of-frame and "
                "modulo built on this number means 'the NTSC frame' where it "
                "reads as 'the frame'."))
        if RE_FRAME_NTSC.search(line):
            out.append(Finding(
                path, i + 1, "tick-substrate",
                "the substrate's `frame.ntsc` table read BY NAME. It is the "
                "only frame table there is; a second region needs a second "
                "table and a caller that chooses."))
    return out


# --- The file pass ----------------------------------------------------------

def lint_file(path: str) -> list[Finding]:
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError as e:
        return [Finding(path, 1, "io-error", str(e))]
    ext = Path(path).suffix
    raw: list[Finding] = []
    if ext in TOML_EXT:
        raw += check_state(path, lines)
    if ext in ASM_EXT:
        raw += check_asm(path, lines)
    if ext in PY_EXT:
        raw += check_generator(path, lines)
    raw += check_substrate(path, lines)

    kept = [f for f in raw if has_override(lines, f.line) is None]
    kept.extend(detect_bare_overrides(path, lines))
    seen, out = set(), []
    for f in sorted(kept, key=lambda f: (f.line, f.rule)):
        key = (f.file, f.line, f.rule)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def expand(paths: list[str]) -> list[str]:
    files: list[str] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for x in sorted(path.rglob("*")):
                if not x.is_file() or x.suffix not in ALL_EXT:
                    continue
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
    ap = argparse.ArgumentParser(
        description="the frame-assumption lint: what assumes tick == frame.")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-baseline", default=None)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--by-class", action="store_true",
                    help="print the per-rule and per-file census, which is "
                         "what reconciles against docs/95 §5.5's 185")
    args = ap.parse_args(argv)

    try:
        files = expand(args.paths)
    except FileNotFoundError as e:
        print(f"tick_lint: file not found: {e}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for f in files:
        findings.extend(lint_file(f))
    n_all = len(findings)

    if args.baseline:
        try:
            base = json.loads(Path(args.baseline).read_text())
        except FileNotFoundError:
            print(f"tick_lint: baseline not found: {args.baseline}",
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
            print(f"tick_lint: wrote baseline ({len(findings)} entries) to "
                  f"{args.write_baseline}")
        return 0

    if not args.quiet:
        if args.json:
            print(json.dumps([f.to_dict() for f in findings], indent=2))
        elif not args.by_class:
            for f in findings:
                print(format_finding(f))

        if args.by_class:
            from collections import Counter
            allf = [f for f in (findings if args.baseline else findings)]
            per_rule = Counter(f.rule for f in allf)
            per_file = Counter(f.file for f in allf)
            print("by rule:")
            for r, n in sorted(per_rule.items()):
                print(f"  {r:<16} {n:>4}")
            print("top files:")
            for fpath, n in per_file.most_common(20):
                print(f"  {n:>4}  {fpath}")

        if args.summary:
            from collections import Counter
            counts = Counter(f.rule for f in findings)
            print()
            print(f"tick_lint: {len(findings)} NEW finding(s) across "
                  f"{len(files)} file(s)"
                  + (f"; {n_all - len(findings)} held by the baseline"
                     if args.baseline else ""))
            print("  checked: declared state in a frame unit / _tick,_step,"
                  "_advance routines /\n"
                  "  frame-named equates / frame-indexed generators / the "
                  "NTSC frame constant\n"
                  "  and the substrate's frame.ntsc table.\n"
                  "  NOT checked: an undeclared frame coupling, rate-vs-"
                  "integer, the call graph,\n"
                  "  vendor/, or whether any rate actually matches — that is "
                  "tools/rate_oracle.py.\n"
                  "  docs/96 §3.")
            for rule, n in sorted(counts.items()):
                print(f"  {rule}: {n}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
