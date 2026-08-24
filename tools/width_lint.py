#!/usr/bin/env python3
"""
width_lint.py — ca65 8/16-bit width-tracking static analyzer.

Provenance: vendored from an earlier repository an earlier build
(`tools/width_lint.py`) during the SuperForge extraction, unmodified apart from
this note. It arrives with its own test suite (`tests/test_width_lint.py` +
`tests/fixtures/width_lint/`) — a gate without tests is exactly the
indirect-evidence trap CLAUDE.md rule 2 warns about.

Scope note for this repo: `make width-check` runs STRICT — no baseline file,
zero findings tolerated. A tree that adopts this lint late needs a baseline of
grandfathered residuals — tens of kilobytes of them — and a baseline file is a
thing that quietly grows. This repo's engine/ + game/ measured clean the first
time it ran (0 findings across 19 files), so there is nothing to grandfather
and no baseline to grow. Keep it that way.

Catches the recurring HIGH-severity width-tracking bug class documented in
CLAUDE.md Critical Rule 6. The linter implements four pattern-matching
checks against single-file ca65 source:

  Check 1: Label width annotations are PRESENT and TRUE.
           Arrivals at a label are modelled from fall-through, branches,
           jumps AND `jsr`/`jsl` call sites. Per axis (A and I checked
           independently):
             - a label whose known arrivals disagree on an axis must carry
               an annotation ON THAT AXIS within the lookahead window
               (5 counted lines after the label, before the first real
               instruction) -> 'multipath-label', or
               'annotation-wrong-axis' when only the other axis is
               annotated;
             - a BARE annotation (no `sep`/`rep` on its axis between the
               label and the directive) is an assertion about the arriving
               width and must equal every known arrival on its axis
               -> 'annotation-contradicts-arrival';
             - `sep`/`rep` + directive is a forced narrowing — legal from
               any arriving width, but the pair must agree with each other
               -> 'sep-annotation-mismatch';
             - mixed known/UNKNOWN arrivals on an un-annotated axis are
               reported at lower severity (still gating) instead of being
               silently dropped -> 'unknown-arrival'.

           SINGLE-FILE BY CONSTRUCTION: only same-file arrivals exist here.
           A caller in another file is invisible to this check in both
           directions. That hole is closed for DECLARED routines by check 5
           below and is otherwise unchanged — in-file `jsr`/`jsl` sites ARE
           checked against the entry annotation.

  Check 2: tax / tay cross-width transfers are documented.
           Every `tax` or `tay` must be preceded within 5 lines by either
           (a) `and #$00FF` / `and #$ff` while in `.a16` mode, or
           (b) a `; WIDTH-RISK:` comment explaining the contract.

  Check 3: Shared macros that toggle A-width or I-width declare a contract.
           Every `.macro` definition that contains `sep` or `rep` must have
           a `; WIDTH-RISK:` comment within the 5 comment-lines preceding
           the `.macro` directive.

  Check 4: STZ used with a long / absolute-long operand.
           STZ has no absolute-long addressing mode (only dp / dp,x / abs /
           abs,x). `stz f:$7E0000+addr` or `stz $7E0000` is rejected by ca65
           as the cryptic "Illegal addressing mode" with no opcode named.
           This check flags it BEFORE the build and names the fix:
           `lda #0` + `sta f:$7E0000+addr,x` (abs-long-indexed). `stz a:...`
           (forced absolute, a legal 16-bit form) is NOT flagged.

  Check 5: The ROUTINE CONTRACT, and the cross-file call sites it opens.
           An exported routine may DECLARE its entry contract in a fixed
           comment grammar above its label (AGENTS.md, "The routine
           contract"); the declaration is what turns check 1's stated
           single-file limit from unclosable into closed:

             - a `jsr`/`jsl` whose target is defined in ANOTHER file and
               carries a contract is compared against that contract's
               `entry:` widths -> 'cross-file-width', naming both ends;
             - a declaration the parser cannot read is its own finding
               -> 'contract-malformed'. A header that reads to a human as
               a checked contract while nothing checks it is worse than
               no header at all;
             - a contract whose `entry:` disagrees with the bare
               `.aN`/`.iN` on its own label -> 'contract-directive-
               mismatch'. The declaration and the code cannot drift;
             - `A?` / `I?` declare an explicit UNKNOWN — any arrival is
               legal because the routine establishes its own width. The
               body must then actually do that before its first
               width-sensitive instruction -> 'contract-unknown-not-
               established', so UNKNOWN is a statement rather than an
               opt-out.

           THE PASS ACTIVATES ONLY WHERE THE CALLEE DECLARES. An
           undeclared routine is exactly as unchecked as it was before,
           which is what lets a tree adopt this one routine at a time with
           no baseline and no flood. An UNKNOWN ARRIVAL at a call site
           (the caller's own width is not tracked there) is unprovable
           rather than wrong: it is counted and reported in the summary,
           never fired. Stated limits: the target must be a literal label
           on the `jsr`/`jsl` line (an indirect dispatch through a vector
           is invisible), the pass reads DECLARED entry widths and does
           not verify `exit:`, DB or DP, and the `A?` establishment scan
           walks forward without following branches.

Override mechanism:
  Suppress a single line's findings with
      ; WIDTH-LINT: ok — <reason text>
  within the 3 lines surrounding the flagged location. Bare
  `; WIDTH-LINT: ok` (no reason) is rejected — the reason text is required.
  Em-dash `—`, en-dash `–`, double-hyphen `--`, single-hyphen-with-space
  ` - `, or colon `:` are all accepted as the separator.

Usage:
    python tools/width_lint.py path/to/file.asm [more.asm ...]
    python tools/width_lint.py --baseline reports/width_baseline.json path/to/file.asm
    python tools/width_lint.py --json path/to/file.asm
    python tools/width_lint.py --quiet path/to/file.asm    # exit code only

Exit codes:
    0 — no violations (or all overridden / under baseline)
    1 — violations found
    2 — usage / IO error

This module exposes its functionality programmatically; pytest tests under
tests/test_width_lint.py exercise individual checks against synthetic ASM
fixtures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# --- Token + regex patterns --------------------------------------------------

# Width directives. ca65 syntax is `.a8` / `.a16` / `.i8` / `.i16` as
# standalone directives. Match case-insensitive.
RE_WIDTH_A = re.compile(r"^\s*\.(a8|a16)\b", re.IGNORECASE)
RE_WIDTH_I = re.compile(r"^\s*\.(i8|i16)\b", re.IGNORECASE)

# sep / rep #$NN — change runtime width. Bit $20 = A-width, $10 = I-width.
RE_SEP = re.compile(r"^\s*sep\s+#\$([0-9a-f]+)\b", re.IGNORECASE)
RE_REP = re.compile(r"^\s*rep\s+#\$([0-9a-f]+)\b", re.IGNORECASE)

# Branches and absolute jumps that take a label.
RE_BRANCH = re.compile(
    r"^\s*(bra|bne|beq|bcc|bcs|bvs|bvc|bmi|bpl|brl|jmp|jml)\s+([A-Za-z_@][\w@:.]*)",
    re.IGNORECASE,
)

# Subroutine calls that take a label. A `jsr`/`jsl` site is a REAL arrival
# at the target label — modelling it closed the phantom-fallthrough false
# positives on subroutine entry labels and makes the label check useful for
# in-file caller/callee width contracts.
# A LEADING `::` is ca65's explicit global-scope qualifier and is written all
# over this tree: a macro or a routine expanded INSIDE a scene's `.scope` has
# to say `jsr ::fade_start_in`, because a bare name would resolve against the
# scope first. It names the same routine a bare `jsr` does. Until it was in
# this pattern the cross-file pass could not see those calls at all — not
# checked, and not counted as unprovable or ambiguous either, so the summary
# reported a reach it did not have. It is stripped from the captured name
# rather than carried, so the same-file test and the contract-table lookup
# both see the plain symbol.
RE_CALL = re.compile(
    r"^\s*(jsr|jsl)\s+(?:::)?([A-Za-z_@][\w@:.]*)",
    re.IGNORECASE,
)

# Assembler-time symbol assignments: `NAME = expr` / `NAME := expr`. These
# emit no bytes and are NOT instructions — treating them as instructions made
# _previous_real_instruction stop at them and synthesise phantom fall-through
# arrivals into whatever label followed.
RE_SYMBOL_ASSIGN = re.compile(r"^\s*[A-Za-z_@.][\w@.]*\s*:?=")

# A leading label on an instruction line: `name:` or the ca65 unnamed label
# `:` followed by code (e.g. `:   rts`, `:   .a16`). The lookahead refuses
# `NAME := expr` (an assignment, not a label). Stripping the prefix lets the
# line model see the code behind it — before this, `:   rts` read as a
# non-return (phantom fall-through past an rts) and `:   .a16` hid a width
# directive from the running state.
RE_LABEL_PREFIX = re.compile(r"^\s*(?:[A-Za-z_@][\w@]*)?:(?!=)\s*")

# Label definitions: "FOO:" or "@local:" on a line by itself.
# We require the colon to be followed by only whitespace + optional comment +
# EOL, otherwise constructs like `bne :-` (ca65 anonymous-local-label syntax)
# would be misparsed as a label named `bne`.
# Local labels (@-prefixed) are scoped to the most recent global label, but
# for our purposes we treat each label as its own analysis unit.
RE_LABEL = re.compile(r"^\s*([A-Za-z_@][\w@:.]*)\s*:\s*(;.*)?$")

# tax / tay
RE_TAX_TAY = re.compile(r"^\s*(tax|tay)\b", re.IGNORECASE)

# AND #$00FF (or #$00ff) — the canonical zero-extend before tax/tay.
# Accept any low-byte mask form (#$00FF, #$ff, #$0F, etc) — operationally
# any AND with an immediate that has no high byte set.
RE_AND_LOWBYTE = re.compile(
    r"^\s*and\s+#\$([0-9a-f]{1,4})\b",
    re.IGNORECASE,
)

# .macro / .endmacro
RE_MACRO_START = re.compile(r"^\s*\.macro\s+([A-Za-z_]\w*)", re.IGNORECASE)
RE_MACRO_END = re.compile(r"^\s*\.endmacro\b", re.IGNORECASE)

# STZ with a forced-long (`f:` / `l:`) operand, OR a bare absolute-long
# constant (24-bit hex literal, i.e. > $FFFF). STZ has no abs-long mode, so
# ca65 rejects either with "Illegal addressing mode". We deliberately do NOT
# match `stz a:` (forced absolute — legal) or `stz <...` (forced DP — legal)
# or plain `stz $XX` / `stz LABEL` (ca65 picks dp/abs, both legal).
#   - `stz f:$7E0000+addr,x`  -> forced long  -> illegal
#   - `stz $7E0000`           -> abs-long lit -> illegal
RE_STZ_FORCED_LONG = re.compile(r"^\s*stz\s+[fl]:", re.IGNORECASE)
RE_STZ_LONG_LITERAL = re.compile(
    r"^\s*stz\s+\$([0-9a-f]{5,6})\b", re.IGNORECASE
)

# Comments: ca65 uses ";" for line comments. Anything after ; is a comment.
# WIDTH-RISK and WIDTH-LINT must appear inside a comment.
RE_WIDTH_RISK = re.compile(r";\s*WIDTH-RISK\b", re.IGNORECASE)

# Override comment. Required form: "; WIDTH-LINT: ok <SEP> <reason text>"
# where <SEP> is one of: em-dash —, en-dash –, double-hyphen --, " - ",
# or ":". The reason text after the separator must be non-empty.
RE_WIDTH_LINT_OK = re.compile(
    r";\s*WIDTH-LINT:\s*ok"
    r"(?:\s*[—–]|\s*--|\s+-\s+|\s*:\s+)"
    r"\s*(\S.*\S|\S)",
    re.IGNORECASE,
)
# Bare "; WIDTH-LINT: ok" with nothing after — rejected.
RE_WIDTH_LINT_BARE = re.compile(
    r";\s*WIDTH-LINT:\s*ok\s*$",
    re.IGNORECASE,
)

# Instruction lines that count as "the next real instruction" — we use this
# to bound the multi-path label lookahead window. Anything that's neither
# a comment, a blank line, a label, nor a directive starting with "." is
# considered a real instruction.
RE_DIRECTIVE = re.compile(r"^\s*\.[a-zA-Z]")
RE_COMMENT_OR_BLANK = re.compile(r"^\s*(;.*)?$")


# --- Width state model -------------------------------------------------------

# We represent A-width and I-width independently. Each can be 'a8', 'a16',
# 'i8', 'i16', or 'unknown' (haven't seen an annotation yet on this path).
# Modes are tracked per-line; arrival modes for a label are the union of
# {(a_mode, i_mode)} tuples observed at every place that branches/jumps to
# the label or falls through into it.

UNKNOWN = "unknown"


@dataclass
class WidthState:
    a: str = UNKNOWN  # 'a8' | 'a16' | 'unknown'
    i: str = UNKNOWN  # 'i8' | 'i16' | 'unknown'

    def copy(self) -> "WidthState":
        return WidthState(self.a, self.i)

    def as_tuple(self) -> tuple[str, str]:
        return (self.a, self.i)


@dataclass
class Finding:
    file: str
    line: int
    rule: str  # 'multipath-label' | 'annotation-contradicts-arrival'
    #          | 'annotation-wrong-axis' | 'sep-annotation-mismatch'
    #          | 'unknown-arrival' | 'tax-tay-cross-width'
    #          | 'macro-no-contract' | 'stz-long' | 'bare-override'
    message: str
    label: Optional[str] = None
    # 'error' gates like every finding; 'warn' (the unknown-arrival rule)
    # also gates — the lower severity is informational, the exit code stays
    # binary so the strict zero-baseline keeps meaning zero.
    severity: str = "error"

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
            "label": self.label,
            "severity": self.severity,
        }

    def location(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class FileAnalysis:
    """Pre-pass artifacts collected from a single ASM file."""

    path: str
    lines: list[str]
    # Per-line running width state at the START of each line (after any
    # directive on the previous line has taken effect).
    width_at: list[WidthState] = field(default_factory=list)
    # label name -> list of (line_number, arrival_mode) for branches, calls
    # (jsr/jsl) and fall-through
    arrivals: dict[str, list[tuple[int, tuple[str, str]]]] = field(default_factory=dict)
    # (label name, arrival line) -> 'branch' | 'call' | 'fall' — used to name
    # the arrival kind in finding messages.
    arrival_kinds: dict[tuple[str, int], str] = field(default_factory=dict)
    # label name -> line where defined (1-indexed)
    label_def_line: dict[str, int] = field(default_factory=dict)


# --- Helpers -----------------------------------------------------------------

def strip_comment(line: str) -> str:
    """Return the part of `line` before any ';' comment delimiter."""
    idx = line.find(";")
    return line if idx < 0 else line[:idx]


def strip_label_prefix(code: str) -> str:
    """Strip leading `name:` / unnamed `:` label prefixes from a code line.

    `:   rts` becomes `rts`; `@lbl: bra x` becomes `bra x`; a label-only
    line becomes empty. Bounded so a pathological line cannot loop.
    """
    for _ in range(4):
        m = RE_LABEL_PREFIX.match(code)
        if not m or m.end() == 0:
            break
        code = code[m.end():]
    return code


@dataclass
class AxisAnnotation:
    """The FIRST `.aN`/`.iN` directive found on one axis in a label's
    prelude, plus the `sep`/`rep`-established width (if any) in force at
    the point of the directive."""

    value: str            # 'a8' | 'a16' | 'i8' | 'i16'
    forced: Optional[str]  # width forced by a preceding sep/rep on this
    #                        axis inside the prelude, or None if the
    #                        annotation is BARE (an assertion about the
    #                        arriving width, not a narrowing)
    line: int             # 1-indexed line of the directive


@dataclass
class LabelPrelude:
    """What a label's lookahead window declares, per axis."""

    ann_a: Optional[AxisAnnotation] = None
    ann_i: Optional[AxisAnnotation] = None
    any_annotation: bool = False

    def ann(self, axis: str) -> Optional[AxisAnnotation]:
        return self.ann_a if axis == "a" else self.ann_i


def scan_label_prelude(lines: list[str], start_idx: int,
                       window: int = 5) -> LabelPrelude:
    """
    Scan a label's lookahead window (up to `window` counted lines starting
    at start_idx, ending at the first real instruction) and return the
    annotations found per axis, each with whether a `sep`/`rep` on its
    axis preceded it inside the window.

    That distinction is the semantic core of check 1:

      - a **bare** `.aN`/`.iN` is an *assertion* about the width the label
        is reached in — it must equal every known arrival on its axis;
      - **`sep`/`rep` + directive** is a *forced narrowing* — correct from
        any arriving width, required only to agree with its own sep/rep.

    Window semantics match the historical presence check: `sep`/`rep`,
    directives and other non-comment/non-label lines count toward the
    window; comments, blanks, label lines and symbol assignments do not;
    the first real instruction closes the window.
    """
    n = len(lines)
    pre = LabelPrelude()
    forced = {"a": None, "i": None}
    seen = 0
    for i in range(start_idx, min(start_idx + window + 8, n)):
        code = strip_label_prefix(strip_comment(lines[i]))
        if m := RE_WIDTH_A.match(code):
            pre.any_annotation = True
            if pre.ann_a is None:
                pre.ann_a = AxisAnnotation(m.group(1).lower(), forced["a"], i + 1)
        elif m := RE_WIDTH_I.match(code):
            pre.any_annotation = True
            if pre.ann_i is None:
                pre.ann_i = AxisAnnotation(m.group(1).lower(), forced["i"], i + 1)
        elif m := RE_SEP.match(code):
            mask = int(m.group(1), 16)
            if mask & 0x20:
                forced["a"] = "a8"
            if mask & 0x10:
                forced["i"] = "i8"
        elif m := RE_REP.match(code):
            mask = int(m.group(1), 16)
            if mask & 0x20:
                forced["a"] = "a16"
            if mask & 0x10:
                forced["i"] = "i16"
        elif RE_SYMBOL_ASSIGN.match(code):
            continue          # assembler-time, no window cost
        elif not code.strip():
            continue          # blank / comment-only / label-only line
        elif RE_DIRECTIVE.match(code):
            pass              # other directive: counts, keeps scanning
        else:
            break             # real instruction — window closes
        seen += 1
        if seen > window:
            break
    return pre


def has_explicit_width_annotation(lines: list[str], start_idx: int, window: int = 5) -> bool:
    """
    Compatibility wrapper over `scan_label_prelude` (the split):
    True when the window carries ANY width annotation. Presence alone —
    callers that need the annotation values and their bare/forced status
    use `scan_label_prelude` directly, as check 1 now does.
    """
    return scan_label_prelude(lines, start_idx, window).any_annotation


def has_override(lines: list[str], idx: int, window: int = 3) -> Optional[str]:
    """
    Check if a `; WIDTH-LINT: ok — <reason>` comment appears within `window`
    lines before, on, or after `idx`. Returns the reason text on match, or
    None if no valid override is present. Bare `; WIDTH-LINT: ok` (no
    reason) does NOT count as an override.
    """
    n = len(lines)
    lo = max(0, idx - window)
    hi = min(n, idx + window + 1)
    for i in range(lo, hi):
        m = RE_WIDTH_LINT_OK.search(lines[i])
        if m:
            return m.group(1).strip()
    return None


def has_width_risk_comment(lines: list[str], start_idx: int, window: int = 5,
                           direction: str = "before") -> bool:
    """
    Scan `window` lines before (or after) start_idx for a `; WIDTH-RISK:`
    comment. `direction` is "before" or "after".
    """
    n = len(lines)
    if direction == "before":
        lo = max(0, start_idx - window)
        for i in range(lo, start_idx + 1):
            if RE_WIDTH_RISK.search(lines[i]):
                return True
    else:
        hi = min(n, start_idx + window + 1)
        for i in range(start_idx, hi):
            if RE_WIDTH_RISK.search(lines[i]):
                return True
    return False


def has_width_risk_in_header_block(lines: list[str], start_idx: int) -> bool:
    """
    Scan upward from `start_idx - 1` through the contiguous block of
    comment-or-blank lines. Return True if any of them contains a
    `; WIDTH-RISK:` comment. Stops at the first non-comment, non-blank
    line. Falls through to a 5-line minimum window so a macro defined
    immediately after a code line still gets a small lookback.
    """
    n_scanned = 0
    i = start_idx - 1
    while i >= 0:
        s = lines[i].strip()
        is_blank = (s == "")
        is_comment = s.startswith(";")
        if not (is_blank or is_comment):
            break
        if RE_WIDTH_RISK.search(lines[i]):
            return True
        n_scanned += 1
        i -= 1
    # Minimum 5-line lookback even if a code line breaks the block early.
    if n_scanned < 5:
        lo = max(0, start_idx - 5)
        for j in range(lo, start_idx):
            if RE_WIDTH_RISK.search(lines[j]):
                return True
    return False


# --- Pre-pass: build per-line width state + label arrivals ------------------

# Branches that are unconditional — used to decide whether the next line is
# a fall-through arrival into the following label.
UNCOND_BRANCHES = {"bra", "brl", "jmp", "jml", "rts", "rti", "rtl"}

# Lines that look like a return — also non-fallthrough.
RE_RETURN = re.compile(r"^\s*(rts|rtl|rti|stp|wai)\b", re.IGNORECASE)


def analyze_file(path: str | Path) -> FileAnalysis:
    """
    First pass: read the file, build the running width state at each line,
    and collect every label's arrival modes.
    """
    p = Path(path)
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()

    fa = FileAnalysis(path=str(p), lines=lines)
    fa.width_at = [WidthState() for _ in lines]

    state = WidthState()
    in_macro = False

    for idx, raw in enumerate(lines):
        # Record the state at the START of this line.
        fa.width_at[idx] = state.copy()

        # Strip comments before analyzing instructions, but keep the raw
        # line for comment-pattern checks elsewhere. `code` additionally
        # strips any leading `name:` / `:` label so instructions and
        # directives behind a label prefix are visible to the model
        # (`:  rts` is an rts; `:  .a16` updates the tracked width) —
        # label DEFINITIONS are still matched against `line`.
        line = strip_comment(raw)
        code = strip_label_prefix(line)

        # Track macro nesting — sep/rep inside a macro body don't change
        # the running state for the post-macro caller (the macro's effect
        # depends on call site). We deliberately STILL apply directive
        # changes inside macros so check 1's annotations work, but we
        # reset state at the macro end.
        if RE_MACRO_START.match(line):
            in_macro = True
        elif RE_MACRO_END.match(line):
            in_macro = False

        # Apply explicit `.aN` / `.iN` directives — these set the
        # assembler's tracked width.
        m = RE_WIDTH_A.match(code)
        if m:
            state.a = m.group(1).lower()
        m = RE_WIDTH_I.match(code)
        if m:
            state.i = m.group(1).lower()

        # Apply sep / rep — these change runtime width. ca65 uses these
        # alongside .a8/.a16, but the directive is what tracks assembler
        # state. For OUR analysis we model the runtime intent: sep #$20
        # means A-width 8, rep #$20 means A-width 16.
        m = RE_SEP.match(code)
        if m:
            mask = int(m.group(1), 16)
            if mask & 0x20:
                state.a = "a8"
            if mask & 0x10:
                state.i = "i8"
        m = RE_REP.match(code)
        if m:
            mask = int(m.group(1), 16)
            if mask & 0x20:
                state.a = "a16"
            if mask & 0x10:
                state.i = "i16"

        # Branches: record the destination label as reached from the
        # current state.
        m = RE_BRANCH.match(code)
        if m:
            label = m.group(2)
            fa.arrivals.setdefault(label, []).append(
                (idx + 1, state.as_tuple())
            )
            fa.arrival_kinds[(label, idx + 1)] = "branch"

        # Calls: a jsr/jsl site is a real arrival at the callee's entry
        # label, in the caller's tracked state. (Execution also continues
        # after the call, so calls do not suppress fall-through below.)
        m = RE_CALL.match(code)
        if m:
            label = m.group(2)
            fa.arrivals.setdefault(label, []).append(
                (idx + 1, state.as_tuple())
            )
            fa.arrival_kinds[(label, idx + 1)] = "call"

        # Label definitions: register the line where defined.
        m = RE_LABEL.match(line)
        if m:
            name = m.group(1)
            fa.label_def_line[name] = idx + 1
            # Fall-through arrival: if the previous real instruction is NOT
            # an unconditional branch / return, this label is reached by
            # fall-through with the current state.
            prev = _previous_real_instruction(lines, idx)
            if prev is not None:
                first_token = prev.split()[0].lower() if prev.split() else ""
                if first_token not in UNCOND_BRANCHES and not RE_RETURN.match(prev):
                    fa.arrivals.setdefault(name, []).append(
                        (idx + 1, state.as_tuple())
                    )
                    fa.arrival_kinds[(name, idx + 1)] = "fall"

    return fa


def _previous_real_instruction(lines: list[str], idx: int) -> Optional[str]:
    """Walk backward from idx-1 and return the first REAL instruction as
    comment-stripped, label-prefix-stripped code text.

    Not real, so walked past: blanks, comments, label-only lines, directives,
    and assembler-time symbol assignments (`NAME = expr` / `NAME := expr`) —
    assignments emit no bytes, and stopping at one used to synthesise a
    phantom fall-through arrival into the label that followed.
    A `:`-prefixed instruction
    (`:   rts`) is returned as its instruction, so returns hidden behind an
    unnamed label terminate fall-through correctly.
    """
    for i in range(idx - 1, -1, -1):
        if RE_COMMENT_OR_BLANK.match(lines[i]):
            continue
        if RE_LABEL.match(lines[i]):
            continue
        # Directives don't count as flow-altering, but they don't establish
        # fall-through either — keep walking past them. (Stops at .endmacro
        # too, which is fine.)
        if RE_DIRECTIVE.match(lines[i]):
            continue
        code = strip_comment(lines[i])
        if RE_SYMBOL_ASSIGN.match(code):
            continue
        code = strip_label_prefix(code)
        if not code.strip():
            continue
        if RE_DIRECTIVE.match(code):
            continue
        return code
    return None


# --- The four checks ---------------------------------------------------------

def check_multipath_labels(fa: FileAnalysis) -> list[Finding]:
    """
    Check 1: label width annotations must be PRESENT where paths diverge
    and TRUE against every arrival the file shows. Arrivals
    are fall-throughs, branches/jumps, and jsr/jsl call sites. Per axis
    (A and I independently):

      presence — a label whose known arrivals disagree on an axis must
        carry an annotation on THAT axis in the lookahead window:
        no annotation at all           -> 'multipath-label'
        annotation on the other axis   -> 'annotation-wrong-axis'
      agreement — a BARE annotation (no sep/rep on its axis between the
        label and the directive) asserts the arriving width; every known
        arrival on the axis must equal it -> 'annotation-contradicts-arrival'
      consistency — an annotation behind a sep/rep on its axis is a forced
        narrowing, legal from any arriving width, but it must agree with
        what the sep/rep establishes -> 'sep-annotation-mismatch'
      unknown — an axis reached from BOTH a known and an UNKNOWN width
        with no annotation on the axis is reported at lower severity
        rather than silently dropped -> 'unknown-arrival' (severity=warn;
        still gates). Axes whose every arrival is UNKNOWN stay out of
        scope, as before — too noisy at this resolution.

    Single-file limitation (deliberate, unchanged): only same-file
    arrivals exist. Callers of an exported routine that live in another
    file — e.g. `col_map_at`'s callers in race.asm — are invisible in
    both directions, so a caller/callee width-contract violation across
    files is NOT caught here; in-file jsr/jsl sites are.
    """
    findings: list[Finding] = []

    def arr_str(arrivals: list, label: str, pos: int) -> str:
        return ", ".join(
            f"{t[pos]}@{ln}({fa.arrival_kinds.get((label, ln), 'arrival')})"
            for (ln, t) in arrivals
        )

    for label, arrivals in fa.arrivals.items():
        if label not in fa.label_def_line:
            # Branch/call to an external symbol — out of scope.
            continue

        def_line = fa.label_def_line[label]
        # Allow override directly at the label.
        if has_override(fa.lines, def_line - 1):
            continue

        # Lookahead starts on the line AFTER the label definition.
        pre = scan_label_prelude(fa.lines, def_line)

        for axis, pos in (("a", 0), ("i", 1)):
            vals = [t[pos] for (_ln, t) in arrivals]
            known = {v for v in vals if v != UNKNOWN}
            has_unknown = any(v == UNKNOWN for v in vals)
            multipath = len(known) > 1
            ann = pre.ann(axis)

            if ann is None:
                if multipath:
                    if pre.any_annotation:
                        rule, extra = "annotation-wrong-axis", (
                            " (the window annotates the other axis only)")
                    else:
                        rule, extra = "multipath-label", ""
                    findings.append(Finding(
                        file=fa.path, line=def_line, rule=rule, label=label,
                        message=(
                            f"label '{label}' {axis.upper()}-width differs "
                            f"between arrivals [{arr_str(arrivals, label, pos)}] "
                            f"but has no explicit .{axis}8/.{axis}16 annotation "
                            f"within 5 lines{extra}"),
                    ))
                elif len(known) == 1 and has_unknown:
                    findings.append(Finding(
                        file=fa.path, line=def_line, rule="unknown-arrival",
                        label=label, severity="warn",
                        message=(
                            f"label '{label}' {axis.upper()}-width arrivals mix "
                            f"known and unknown [{arr_str(arrivals, label, pos)}] "
                            f"and the label carries no .{axis}8/.{axis}16 "
                            f"annotation — annotate the label (or the unknown "
                            f"path's origin) so the analyzer can check it"),
                    ))
            elif ann.forced is not None:
                if ann.value != ann.forced:
                    findings.append(Finding(
                        file=fa.path, line=ann.line,
                        rule="sep-annotation-mismatch", label=label,
                        message=(
                            f"label '{label}': directive .{ann.value} at line "
                            f"{ann.line} disagrees with the sep/rep before it, "
                            f"which forces {ann.forced} — one of the two is "
                            f"wrong"),
                    ))
            else:
                bad = sorted(v for v in known if v != ann.value)
                if bad:
                    findings.append(Finding(
                        file=fa.path, line=def_line,
                        rule="annotation-contradicts-arrival", label=label,
                        message=(
                            f"label '{label}' carries bare .{ann.value} (line "
                            f"{ann.line}) but is reached in {'/'.join(bad)} "
                            f"[{arr_str(arrivals, label, pos)}] — a bare "
                            f"annotation asserts the arriving width; either "
                            f"narrow every predecessor to .{ann.value} before "
                            f"it arrives, or resync at the label "
                            f"(sep/rep + directive)"),
                    ))

    return findings


def check_tax_tay_cross_width(fa: FileAnalysis) -> list[Finding]:
    """
    Check 2: tax / tay in A8 mode must document the cross-width contract.

    In A16/I16 mode, `tax` transfers the full 16-bit accumulator — that's
    the ordinary index-load idiom and not a bug. In A8/I16 mode (the
    a later stage-1 bug pattern), `tax` ALSO transfers the full 16-bit C
    register but the high byte is whatever leaked over from a prior A16
    operation — silent index corruption. We flag those specifically.

    A flagged tax/tay passes if preceded within 5 lines by either:
      (a) `and #$00FF` (or any low-byte mask) after `.a16` — the canonical
          zero-extend before transferring back to A8 → X16
      (b) a `; WIDTH-RISK:` comment explaining the contract
      (c) a `; WIDTH-LINT: ok — <reason>` override
    """
    findings: list[Finding] = []

    for idx, line in enumerate(fa.lines):
        m = RE_TAX_TAY.match(strip_comment(line))
        if not m:
            continue
        op = m.group(1).lower()

        state = fa.width_at[idx]
        # Only flag the truly dangerous case: A8 + I16. In that combination
        # `tax`/`tay` transfers the full 16-bit C register into a 16-bit
        # index — the high byte is whatever stale data happened to be in
        # C-high. A16/I16 tax/tay is the ordinary 16-bit index-load and
        # safe; A8/I8 tax/tay is an 8-bit-to-8-bit transfer and also safe.
        if not (state.a == "a8" and state.i == "i16"):
            continue

        if has_override(fa.lines, idx):
            continue

        # Search 5 prior non-blank/comment instructions for the canonical
        # zero-extend OR a WIDTH-RISK comment.
        if _preceded_by_zero_extend_or_riskcomment(fa.lines, idx, window=5):
            continue

        findings.append(
            Finding(
                file=fa.path,
                line=idx + 1,
                rule="tax-tay-cross-width",
                message=(
                    f"'{op}' in A8 mode without preceding `and #$00FF` "
                    f"(after .a16) and no `; WIDTH-RISK:` comment within "
                    f"5 lines — A8/I16 tax/tay transfers the full 16-bit "
                    f"C register; C-high may carry a stale value from a "
                    f"prior A16 operation"
                ),
            )
        )

    return findings


def _preceded_by_zero_extend_or_riskcomment(lines: list[str], idx: int,
                                            window: int = 5) -> bool:
    """
    Return True if any of the `window` non-blank/comment instruction lines
    preceding `idx` is `and #$NN` (high byte zero) — taken as the canonical
    zero-extend before tax/tay. Comments are scanned separately for
    `; WIDTH-RISK:` markers anywhere in the same window.
    """
    seen = 0
    for i in range(idx - 1, -1, -1):
        # Comments scanned independently — WIDTH-RISK can be on its own line.
        if RE_WIDTH_RISK.search(lines[i]):
            return True
        if RE_COMMENT_OR_BLANK.match(lines[i]):
            continue
        # Code line: check if it's an AND mask whose high byte is zero.
        m = RE_AND_LOWBYTE.match(strip_comment(lines[i]))
        if m:
            mask = int(m.group(1), 16)
            # The mask's high byte must be zero. #$00FF, #$ff, #$0F, etc OK;
            # #$0100, #$8000 NOT OK.
            if (mask & 0xFF00) == 0:
                return True
        seen += 1
        if seen >= window:
            break
    return False


def check_macro_contracts(fa: FileAnalysis) -> list[Finding]:
    """
    Check 3: every `.macro` containing `sep` or `rep` must be preceded by
    a `; WIDTH-RISK:` comment somewhere in the contiguous comment-or-blank
    block immediately above the `.macro` directive (with a 5-line minimum
    lookback). The block-scan matches the SuperForge convention of
    multi-paragraph header comments above macros.
    """
    findings: list[Finding] = []
    n = len(fa.lines)
    in_macro = False
    macro_start_idx: Optional[int] = None
    macro_name: Optional[str] = None
    macro_toggles_width = False

    for idx, line in enumerate(fa.lines):
        stripped = strip_comment(line)

        if not in_macro:
            m = RE_MACRO_START.match(stripped)
            if m:
                in_macro = True
                macro_start_idx = idx
                macro_name = m.group(1)
                macro_toggles_width = False
            continue

        # Inside a macro:
        if RE_MACRO_END.match(stripped):
            # Verify contract.
            if macro_toggles_width:
                if not has_width_risk_in_header_block(fa.lines, macro_start_idx):
                    if not has_override(fa.lines, macro_start_idx, window=3):
                        findings.append(
                            Finding(
                                file=fa.path,
                                line=macro_start_idx + 1,
                                rule="macro-no-contract",
                                message=(
                                    f"macro '{macro_name}' contains sep/rep "
                                    f"but no `; WIDTH-RISK:` contract "
                                    f"comment in the contiguous header "
                                    f"comment block above the .macro "
                                    f"directive (or 5-line min lookback). "
                                    f"The `; WIDTH-RISK:` contract must be on "
                                    f"its OWN comment line — the marker has to "
                                    f"directly follow the `;` (e.g. "
                                    f"`; WIDTH-RISK: entry A16, exit A8`). "
                                    f"Folding it into another comment "
                                    f"(`; Clobbers A. WIDTH-RISK: ...`) does "
                                    f"NOT satisfy the check"
                                ),
                                label=macro_name,
                            )
                        )
            in_macro = False
            macro_start_idx = None
            macro_name = None
            macro_toggles_width = False
            continue

        if RE_SEP.match(stripped) or RE_REP.match(stripped):
            macro_toggles_width = True

    return findings


def check_stz_long(fa: FileAnalysis) -> list[Finding]:
    """
    Check 4: STZ used with a long / absolute-long operand.

    STZ's only addressing modes are dp, dp,x, abs, and abs,x — there is NO
    absolute-long (24-bit) STZ. `stz f:$7E0000+addr,x` (forced long) and
    `stz $7E0000` (a 24-bit literal that ca65 resolves to abs-long) both
    assemble to nothing: ca65 emits "Illegal addressing mode" WITHOUT naming
    STZ, which reads as a mysterious "line N: Illegal addressing mode" and
    cost real debugging time twice before this check existed.

    This check catches it at lint time and names the fix. The legal patterns
    `stz a:$xxxx` (forced absolute), `stz <$xx` (forced DP), `stz $xx`, and
    `stz LABEL` are NOT flagged.

    Suppressible with `; WIDTH-LINT: ok — <reason>` (e.g. if a macro arg
    happens to expand to a DP symbol the textual scan can't resolve).
    """
    findings: list[Finding] = []
    for idx, raw in enumerate(fa.lines):
        line = strip_comment(raw)
        if not (RE_STZ_FORCED_LONG.match(line) or RE_STZ_LONG_LITERAL.match(line)):
            continue
        if has_override(fa.lines, idx):
            continue
        findings.append(
            Finding(
                file=fa.path,
                line=idx + 1,
                rule="stz-long",
                message=(
                    "STZ has no absolute-long form (only dp / dp,x / abs / "
                    "abs,x) — ca65 rejects this as \"Illegal addressing "
                    "mode\". Use 'lda #0' + 'sta f:$7E0000+addr,x' "
                    "(abs-long-indexed) to zero WRAM above the DP."
                ),
            )
        )
    return findings


# --- The routine contract: a declaration the linter can read ----------------
#
# The grammar is documented for humans in AGENTS.md, "The routine contract".
# What follows is the parser for it — fixed slots, one line each, in a comment
# block that sits immediately above the routine or macro it binds:
#
#     ; CONTRACT stream_arm
#     ;   entry:    A16 I16 DB=0
#     ;   exit:     A16 I16
#     ;   in:       the enter camera's tile position
#     ;   out:      ST_CAM_* / ST_LAST_* seeded, the staging counters zeroed
#     ;   clobbers: A, X, N, Z
#     ;   assumes:  the seed upload already covers the window around CAM0
#     ;   tail:     rts
#
# `entry:` and `exit:` are the MACHINE slots and are parsed; the rest are
# prose and are only checked for presence. A8 / A16 / I8 / I16 name a width;
# `A?` / `I?` name an explicit UNKNOWN — "any arrival is legal on this axis,
# the routine establishes its own". DB= and DP= are optional and free-form
# (an expression the reader resolves, not one the linter evaluates).
#
# DEGRADING GRACEFULLY IS PART OF THE DESIGN. A file with no CONTRACT block
# is UNDECLARED: every check below finds nothing in it and the cross-file pass
# does not activate for its routines. That is why this could land on a tree
# whose width-lint baseline is zero without moving it by one finding.

RE_CONTRACT = re.compile(r"^\s*;\s*CONTRACT\s+(\S+)\s*$")

CONTRACT_SLOTS_REQUIRED = ("entry", "exit", "clobbers")
CONTRACT_SLOTS_OPTIONAL = ("in", "out", "assumes", "tail")
CONTRACT_SLOTS = CONTRACT_SLOTS_REQUIRED + CONTRACT_SLOTS_OPTIONAL

RE_CONTRACT_SLOT = re.compile(
    r"^\s*;\s{1,}([A-Za-z][A-Za-z-]*)\s*:\s*(.*?)\s*$")
# A comment line that continues the previous slot's prose: indented past the
# slot names, carrying text, and not itself a `name:` slot line.
RE_CONTRACT_CONT = re.compile(r"^\s*;\s{6,}(\S.*?)\s*$")
RE_COMMENT_LINE = re.compile(r"^\s*;")

RE_CONTRACT_A = re.compile(r"^A(8|16|\?)$")
RE_CONTRACT_I = re.compile(r"^I(8|16|\?)$")
RE_CONTRACT_KV = re.compile(r"^(DB|DP)=(\S+)$")

# Instructions that do not depend on either register width, so a routine
# declared UNKNOWN on an axis may run them before it establishes that axis.
# `plp` is deliberately NOT here: it establishes the width AT RUNTIME and ca65
# cannot see through it (sf_asm.inc's SF_SET_P_DB says the same), so a routine
# that plp's still owes the tracker a directive.
WIDTH_NEUTRAL_OPS = {
    "php", "phb", "phd", "phk", "plb", "pld",
    "sei", "cli", "clc", "sec", "cld", "sed", "clv", "xce", "nop",
}
RE_FIRST_TOKEN = re.compile(r"^\s*([a-z]{3})\b", re.IGNORECASE)


@dataclass
class Contract:
    """One parsed CONTRACT block, bound to the routine or macro below it."""

    name: str
    file: str
    line: int              # 1-indexed line of the `; CONTRACT <name>` line
    kind: str              # 'routine' | 'macro'
    bound_line: int        # 1-indexed line of the label / `.macro` directive
    entry_a: str = UNKNOWN  # 'a8' | 'a16' | UNKNOWN
    entry_i: str = UNKNOWN  # 'i8' | 'i16' | UNKNOWN
    exit_a: str = UNKNOWN
    exit_i: str = UNKNOWN
    slots: dict = field(default_factory=dict)
    # Set when the block did not parse. A malformed contract has already
    # produced its own finding, and every check downstream of it is then
    # reading a declaration that does not say what its author meant — so the
    # semantic checks skip it and it never enters the cross-file table. One
    # violation, one diagnosis.
    malformed: bool = False

    def entry(self, axis: str) -> str:
        return self.entry_a if axis == "a" else self.entry_i

    def location(self) -> str:
        return f"{self.file}:{self.line}"


def _parse_machine_slot(axis_prefix: str, text: str) -> tuple[str, str, list]:
    """Parse an `entry:` / `exit:` slot body into (a_width, i_width, errors).

    `none` — for an `exit:` that never happens — parses as UNKNOWN on both
    axes with no error, because "control does not come back" is not a claim
    about widths.
    """
    errs: list[str] = []
    a = i = UNKNOWN
    seen_a = seen_i = False
    toks = text.replace(",", " ").split()
    if not toks:
        return a, i, [f"`{axis_prefix}:` is empty — it must name both axes "
                      f"(e.g. `A16 I16`, or `A? I16` where the width is "
                      f"established by the routine itself)"]
    if len(toks) == 1 and toks[0].lower() == "none":
        return a, i, errs
    for t in toks:
        if m := RE_CONTRACT_A.match(t):
            a = UNKNOWN if m.group(1) == "?" else f"a{m.group(1)}"
            seen_a = True
        elif m := RE_CONTRACT_I.match(t):
            i = UNKNOWN if m.group(1) == "?" else f"i{m.group(1)}"
            seen_i = True
        elif RE_CONTRACT_KV.match(t):
            continue                      # DB= / DP= — read by humans
        else:
            errs.append(
                f"`{axis_prefix}: {text}` carries the token {t!r}, which is "
                f"none of A8/A16/A?, I8/I16/I?, DB=<expr>, DP=<expr>")
    if not seen_a:
        errs.append(f"`{axis_prefix}:` names no A width — say A8, A16, or A? "
                    f"(A? = any arrival is legal, the routine establishes it)")
    if not seen_i:
        errs.append(f"`{axis_prefix}:` names no index width — say I8, I16, "
                    f"or I?")
    return a, i, errs


def parse_contracts(fa: FileAnalysis) -> tuple[list[Contract], list[Finding]]:
    """Every CONTRACT block in one file, plus the malformed ones as findings.

    A malformed block is a FINDING, never a silent skip: a declaration the
    linter cannot read is worse than no declaration, because the header still
    reads to a human as a checked contract while nothing checks it.
    """
    contracts: list[Contract] = []
    findings: list[Finding] = []
    lines = fa.lines
    n = len(lines)

    broken: set = set()

    def bad(line: int, name: str, why: str, at: int = 0) -> None:
        findings.append(Finding(
            file=fa.path, line=line, rule="contract-malformed", label=name,
            message=f"CONTRACT {name}: {why}"))
        broken.add(at or line)

    for idx in range(n):
        m = RE_CONTRACT.match(lines[idx])
        if not m:
            continue
        name = m.group(1)
        slots: dict[str, str] = {}
        slot_line: dict[str, int] = {}
        last: Optional[str] = None
        j = idx + 1
        while j < n and RE_COMMENT_LINE.match(lines[j]):
            if RE_CONTRACT.match(lines[j]):
                break                     # the next contract starts here
            sm = RE_CONTRACT_SLOT.match(lines[j])
            cm = RE_CONTRACT_CONT.match(lines[j])
            if sm and sm.group(1).lower() in CONTRACT_SLOTS:
                last = sm.group(1).lower()
                if last in slots:
                    bad(j + 1, name, f"the `{last}:` slot is written twice",
                    at=idx + 1)
                slots[last] = sm.group(2)
                slot_line[last] = j + 1
            elif sm and not cm:
                bad(j + 1, name,
                    f"`{sm.group(1)}:` is not a contract slot. The slots are "
                    f"{', '.join(CONTRACT_SLOTS)} — a line that is prose "
                    f"continuing the slot above it must be indented under it, "
                    f"and a block comment goes above the CONTRACT line, not "
                    f"inside the block", at=idx + 1)
                last = None
            elif cm and last:
                slots[last] = (slots[last] + " " + cm.group(1)).strip()
            elif lines[j].strip() in (";", ""):
                break                     # a blank comment line closes it
            else:
                break                     # prose resumes: the block is over
            j += 1

        # What the block binds: the first label definition or `.macro` below
        # it, skipping blanks and further prose.
        kind = bound = None
        k = j
        while k < n:
            raw = lines[k]
            if RE_COMMENT_OR_BLANK.match(raw):
                k += 1
                continue
            if mm := RE_MACRO_START.match(strip_comment(raw)):
                kind, bound = "macro", (mm.group(1), k + 1)
            elif lm := RE_LABEL.match(raw):
                kind, bound = "routine", (lm.group(1), k + 1)
            break
        if bound is None:
            bad(idx + 1, name,
                "the block is attached to nothing — a CONTRACT must sit "
                "immediately above the label it describes (or above the "
                "`.macro` directive, for a macro), with only blank lines and "
                "prose comments in between")
            continue
        bound_name, bound_line = bound
        # A contract name may be QUALIFIED — `race::stream_arm`,
        # `microzero::sm_nmi_hook` — and then only its last segment has to
        # match the label. That is not decoration: this tree gives every rail
        # a `sm_nmi_hook` and every scene an `enter`, so a table keyed by bare
        # name could hold at most one of 37 and would report the other 36 as
        # duplicates. A qualified declaration documents the contract and keys
        # uniquely; the cross-file pass then resolves only calls written with
        # the same qualifier, which is the honest reach — a bare `jsr
        # sm_nmi_hook` links against a different routine in every rail's
        # build, and one lint run over the whole tree cannot say which.
        if bound_name != name.rsplit("::", 1)[-1]:
            bad(idx + 1, name,
                f"names {name!r} but the {kind} below it is {bound_name!r} — "
                f"a contract and the thing it describes must carry the same "
                f"name (or a `scope::`-qualified form of it), or a rename "
                f"silently detaches one from the other")

        missing = [s for s in CONTRACT_SLOTS_REQUIRED if s not in slots]
        if missing:
            bad(idx + 1, name,
                f"required slot(s) missing: {', '.join(missing)}. Every "
                f"contract states the machine state it needs on entry, the "
                f"state it leaves, and what it destroys")

        c = Contract(name=name, file=fa.path, line=idx + 1, kind=kind,
                     bound_line=bound_line, slots=slots)
        contracts.append(c)
        for slot, attr in (("entry", "entry"), ("exit", "exit")):
            if slot not in slots:
                continue
            a, i, errs = _parse_machine_slot(slot, slots[slot])
            for e in errs:
                bad(slot_line[slot], name, e, at=idx + 1)
            setattr(c, f"{attr}_a", a)
            setattr(c, f"{attr}_i", i)

    for c in contracts:
        c.malformed = c.line in broken
    return contracts, findings


def check_contract_agrees_with_directives(
        fa: FileAnalysis, contracts: list[Contract]) -> list[Finding]:
    """The declaration and the code must say the same thing about entry width.

    A contract is documentation FIRST, and documentation drifts. This is the
    cheap half of stopping that: inside the defining file, a routine's
    declared `entry:` width must equal the BARE `.aN`/`.iN` the label carries
    — the annotation that already asserts the arriving width for check 1. The
    two are then impossible to change independently, which is what makes the
    cross-file pass's reading of the declaration trustworthy.

    A `sep`/`rep` + directive prelude is a forced NARROWING, not an assertion
    about the arrival, so it is not compared — the contract is free to declare
    what arrives while the code immediately narrows it.
    """
    findings: list[Finding] = []
    for c in contracts:
        if c.kind != "routine" or c.malformed:
            continue
        pre = scan_label_prelude(fa.lines, c.bound_line)
        for axis in ("a", "i"):
            req = c.entry(axis)
            ann = pre.ann(axis)
            if req == UNKNOWN or ann is None or ann.forced is not None:
                continue
            if ann.value != req:
                findings.append(Finding(
                    file=fa.path, line=c.line,
                    rule="contract-directive-mismatch", label=c.name,
                    message=(
                        f"'{c.name}' declares `entry: {req.upper()}` but the "
                        f"label carries a bare .{ann.value} at line "
                        f"{ann.line} — the contract and the directive assert "
                        f"different arriving widths, so one of them is "
                        f"lying to every reader of the other"),
                ))
    return findings


def check_unknown_is_established(
        fa: FileAnalysis, contracts: list[Contract]) -> list[Finding]:
    """`A?` means "I establish my own" — so the body has to actually do it.

    An UNKNOWN entry width tells every caller that any arrival is legal. That
    promise is only true if the routine narrows the axis with a `sep`/`rep`
    before it runs anything whose meaning depends on the width. Without this
    check `A?` would be a way to opt a routine OUT of the cross-file pass by
    writing one character, which is exactly how a declaration convention rots.

    The scan is deliberately shallow — it walks forward from the label over
    the width-neutral instructions and stops at the first thing that is not
    one. It does not follow branches. A routine that establishes its width on
    each arm of an early branch instead of before it will be reported; the
    honest fix there is to narrow before the branch, and the override exists
    for the case where it genuinely cannot.
    """
    findings: list[Finding] = []
    for c in contracts:
        if c.kind != "routine" or c.malformed:
            continue
        for axis, bit in (("a", 0x20), ("i", 0x10)):
            if c.entry(axis) != UNKNOWN:
                continue
            established, blocker, blocker_line = False, None, None
            for k in range(c.bound_line, min(c.bound_line + 40, len(fa.lines))):
                code = strip_label_prefix(strip_comment(fa.lines[k]))
                if not code.strip() or RE_DIRECTIVE.match(code):
                    continue
                sm = RE_SEP.match(code) or RE_REP.match(code)
                if sm and (int(sm.group(1), 16) & bit):
                    established = True
                    break
                tok = RE_FIRST_TOKEN.match(code)
                if tok and tok.group(1).lower() in WIDTH_NEUTRAL_OPS:
                    continue
                blocker, blocker_line = code.strip(), k + 1
                break
            if not established and not has_override(fa.lines, c.bound_line - 1):
                where = (f"'{blocker}' at line {blocker_line}"
                         if blocker else "the end of the scan window")
                findings.append(Finding(
                    file=fa.path, line=c.line,
                    rule="contract-unknown-not-established", label=c.name,
                    message=(
                        f"'{c.name}' declares `entry: {axis.upper()}?` — any "
                        f"arrival legal, the routine establishes its own — "
                        f"but no sep/rep on the {axis.upper()} axis runs "
                        f"before {where}. Either narrow the axis at the top "
                        f"of the routine, or declare the width the callers "
                        f"must actually arrive in"),
                ))
    return findings


def check_cross_file_calls(
        fa: FileAnalysis, contracts: dict,
        label_files: Optional[dict] = None) -> tuple[list[Finding], dict]:
    """THE HOLE CLOSED: a `jsr`/`jsl` into ANOTHER file, checked.

    Check 1 models every same-file arrival at a label, including `jsr`/`jsl`
    sites, and has always said so — and has always said what it could not do:
    a caller in a different file is invisible in both directions, so an
    exported routine's width contract was proven only on the emulator.

    This pass closes that for the routines that DECLARE. For each call whose
    target is not defined in the calling file and does carry a contract, the
    caller's tracked width at the call site is compared against the callee's
    declared `entry:`. Four properties hold it in shape:

      * it activates ONLY where the callee declares. An undeclared routine is
        exactly as unchecked as it was before this pass existed, so the gate
        gains no baseline and no flood, and a tree adopts the grammar one
        routine at a time;
      * an UNKNOWN declaration (`A?`) accepts any arrival, and
        check_unknown_is_established makes the callee earn that;
      * an UNKNOWN ARRIVAL — the caller's own tracked width is not known at
        the site — is not a finding. It is unprovable, not wrong, and firing
        on it would reintroduce the flood by the back door. It is COUNTED and
        the summary reports it, so a pass that proved nothing says so;
      * same-file calls are left to check 1. Reporting them here as well
        would double-count the one arrival two checks can see.

    AND A BARE NAME DEFINED IN MORE THAN ONE FILE IS NOT RESOLVED. A whole-
    tree run sees one flat namespace, so a `jsr` on a name two files define
    would otherwise be checked against whichever declaration this pass read:
    a contract the caller may not link against. That is the indirect-evidence
    shape, and it can fail in both directions (a false finding, or a pass that
    proved nothing). Those calls are counted as AMBIGUOUS and left unchecked;
    the summary names the count, and the way to buy the check is to make the
    routine's name unique.

    This tree's own instance was three `cam_arm`s — sh2_cam's, shg_cam's and
    shp_cam's, seven unresolvable call sites between them — and it was bought
    back the way this paragraph prescribes rather than by a smarter linter:
    sh2_cam's four exports carry its feature prefix now (`sh2_arm`,
    `sh2_tick`, `sh2_advance`, `sh2_region`). The rule outlives the instance,
    which is why the regression test drives synthetic twins.
    """
    findings: list[Finding] = []
    label_files = label_files or {}
    stats = {"checked": 0, "unprovable": 0, "callees": set(),
             "ambiguous": 0, "ambiguous_names": set()}
    for idx, raw in enumerate(fa.lines):
        m = RE_CALL.match(strip_label_prefix(strip_comment(raw)))
        if not m:
            continue
        target = m.group(2)
        if target in fa.label_def_line:
            continue                       # same file — check 1 owns it
        # A scene-scoped call is written `jsr race::stream_nmi_dispatch`, and
        # the contract is declared on the bare label inside that scope. Try
        # the written token first, then its last `::` segment — a name the
        # contract table refuses to hold twice, so the fallback cannot resolve
        # to the wrong routine.
        c = contracts.get(target) or contracts.get(target.rsplit("::", 1)[-1])
        if c is None:
            continue                       # undeclared — unchecked, as before
        if "::" not in c.name and len(label_files.get(c.name, ())) > 1:
            # The declaration is on a bare name that several files define. A
            # qualified contract is disambiguated by its own qualifier and is
            # not subject to this.
            stats["ambiguous"] += 1
            stats["ambiguous_names"].add(c.name)
            continue
        stats["callees"].add(c.name)       # the RESOLVED name, so `race::f`
        #                                    and `world::f` are one callee
        state = fa.width_at[idx]
        overridden = has_override(fa.lines, idx)
        for axis, got in (("a", state.a), ("i", state.i)):
            req = c.entry(axis)
            if req == UNKNOWN:
                continue
            if got == UNKNOWN:
                stats["unprovable"] += 1
                continue
            stats["checked"] += 1
            if got == req or overridden:
                continue
            findings.append(Finding(
                file=fa.path, line=idx + 1, rule="cross-file-width",
                label=target,
                message=(
                    f"{m.group(1).lower()} {target} arrives in .{got}, but "
                    f"'{target}' declares `entry: {req.upper()}` at "
                    f"{c.file}:{c.line}. Narrow at the call site "
                    f"(sep/rep + directive) or fix whichever end is wrong — "
                    f"the two files cannot both be right"),
            ))
    return findings, stats


# --- Public API --------------------------------------------------------------

@dataclass
class ContractStats:
    """What the contract pass actually did, so a disarmed run reads as one."""

    declared: int = 0          # CONTRACT blocks parsed, tree-wide
    routines: int = 0          # of those, ones that bind a routine
    macros: int = 0            # of those, ones that bind a macro
    sites_checked: int = 0     # cross-file call-site AXES actually compared
    sites_unprovable: int = 0  # axes skipped: the caller's own width is UNKNOWN
    sites_ambiguous: int = 0   # calls skipped: the callee's bare name is
    #                            defined in more than one file in the run
    callees: set = field(default_factory=set)  # declared routines called
    #                                            from another file
    ambiguous_names: set = field(default_factory=set)

    def merge(self, other: dict) -> None:
        self.sites_checked += other["checked"]
        self.sites_unprovable += other["unprovable"]
        self.sites_ambiguous += other["ambiguous"]
        self.callees |= other["callees"]
        self.ambiguous_names |= other["ambiguous_names"]


def collect_contracts(paths: list[str]) -> tuple[dict, list[Finding],
                                                 ContractStats]:
    """Phase one: every CONTRACT block in the whole file set, by name.

    The cross-file pass needs the declarations of files it is not currently
    reading, so the run is two-phase. A name declared twice keeps the FIRST
    and reports the second — silently preferring one of two contracts for the
    same symbol is how a caller ends up checked against a declaration that is
    not the one it links against.
    """
    table: dict[str, Contract] = {}
    findings: list[Finding] = []
    stats = ContractStats()
    label_files: dict[str, set] = {}
    for p in paths:
        fa = analyze_file(p)
        for name in fa.label_def_line:
            label_files.setdefault(name, set()).add(fa.path)
        contracts, errs = parse_contracts(fa)
        findings.extend(errs)
        for c in contracts:
            if c.malformed:
                continue          # already a finding; never a checking basis
            stats.declared += 1
            if c.kind == "macro":
                stats.macros += 1
            else:
                stats.routines += 1
            prev = table.get(c.name)
            if prev is not None:
                findings.append(Finding(
                    file=c.file, line=c.line, rule="contract-malformed",
                    label=c.name,
                    message=(
                        f"CONTRACT {c.name}: a contract for this name is "
                        f"already declared at {prev.location()} — two "
                        f"declarations for one symbol means a caller is "
                        f"checked against whichever the linter happened to "
                        f"read first")))
                continue
            table[c.name] = c
    return table, findings, stats, label_files


def lint_file(path: str | Path, contracts: Optional[dict] = None,
              stats: Optional[ContractStats] = None,
              label_files: Optional[dict] = None) -> list[Finding]:
    """Run every check against a single ASM file. Returns findings.

    `contracts` is the tree-wide declaration table from `collect_contracts`.
    Without it the file is linted ALONE — the single-file checks are exactly
    as they were, and the cross-file pass sees only this file's own
    declarations (so it finds nothing, every call being either same-file or
    to an undeclared name). That is the shape the per-file tests use.
    """
    fa = analyze_file(path)
    findings: list[Finding] = []
    findings.extend(check_multipath_labels(fa))
    findings.extend(check_tax_tay_cross_width(fa))
    findings.extend(check_macro_contracts(fa))
    findings.extend(check_stz_long(fa))

    own, errs = parse_contracts(fa)
    if contracts is None:
        findings.extend(errs)
        contracts = {c.name: c for c in own}
    findings.extend(check_contract_agrees_with_directives(fa, own))
    findings.extend(check_unknown_is_established(fa, own))
    xf, xstats = check_cross_file_calls(fa, contracts, label_files)
    findings.extend(xf)
    if stats is not None:
        stats.merge(xstats)

    findings.sort(key=lambda f: (f.file, f.line, f.rule))
    return findings


def lint_paths(paths: list[str]) -> tuple[list[Finding], ContractStats]:
    """The whole-tree run: collect declarations, then lint against them."""
    contracts, findings, stats, label_files = collect_contracts(paths)
    for p in paths:
        findings.extend(lint_file(p, contracts, stats, label_files))
    findings.sort(key=lambda f: (f.file, f.line, f.rule))
    return findings, stats


def detect_bare_overrides(path: str | Path) -> list[Finding]:
    """
    Detect bare `; WIDTH-LINT: ok` (no reason text) — these are rejected
    per spec §5.3 and emitted as findings of their own.
    """
    p = Path(path)
    findings: list[Finding] = []
    for idx, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines()):
        if RE_WIDTH_LINT_BARE.search(line):
            # Only flag if it isn't actually a valid override (e.g. someone
            # writes "; WIDTH-LINT: ok — reason" — that matches BARE only
            # if the rest is empty).
            if not RE_WIDTH_LINT_OK.search(line):
                findings.append(
                    Finding(
                        file=str(p),
                        line=idx + 1,
                        rule="bare-override",
                        message=(
                            "bare `; WIDTH-LINT: ok` is rejected — the "
                            "override convention requires a reason after "
                            "the separator (e.g. `ok — single A8 path`)"
                        ),
                    )
                )
    return findings


# --- CLI ---------------------------------------------------------------------

LINT_EXTENSIONS = (".asm", ".inc")


def expand_paths(paths: list[str]) -> list[str]:
    """Turn the target list into the file list, exactly once.

    A directory expands over EVERY extension this lint reads — `.asm` and
    `.inc` both, because `vendor/rom/sf_asm.inc` is the one file where a width
    mistake is written once and assembled into every ROM. A file is taken as
    given.

    This lives here rather than inside `main` so the pytest mirror can expand
    the SAME target list the Makefile hands the CLI instead of restating the
    globs. Restating them is how the mirror ended up covering `.asm` only
    while the target covered both — a gap that was visible in a comment and
    nowhere else.
    """
    files: list[str] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for ext in LINT_EXTENSIONS:
                files.extend(str(x) for x in sorted(path.rglob(f"*{ext}")))
        elif path.exists():
            files.append(str(path))
        else:
            raise FileNotFoundError(p)
    return files


def format_finding(f: Finding) -> str:
    return f"{f.file}:{f.line}: [{f.rule}] {f.message}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="ca65 8/16-bit width-tracking static analyzer.",
    )
    parser.add_argument("paths", nargs="+", help="ASM files to lint")
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="Path to baseline JSON (suppress findings present in baseline)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit findings as JSON instead of human-readable text",
    )
    parser.add_argument(
        "--write-baseline",
        type=str,
        default=None,
        help="Write current findings as a new baseline JSON file",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress per-finding output; exit code only",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a per-rule summary count after the findings",
    )
    args = parser.parse_args(argv)

    try:
        files = expand_paths(args.paths)
    except FileNotFoundError as e:
        print(f"width_lint: file not found: {e}", file=sys.stderr)
        return 2

    findings, stats = lint_paths(files)
    for f in files:
        findings.extend(detect_bare_overrides(f))

    # Baseline suppression — findings present in the baseline are silenced.
    if args.baseline:
        try:
            base = json.loads(Path(args.baseline).read_text())
            base_set = {(b["file"], b["line"], b["rule"]) for b in base}
            findings = [
                f for f in findings
                if (f.file, f.line, f.rule) not in base_set
            ]
        except FileNotFoundError:
            print(f"width_lint: baseline not found: {args.baseline}", file=sys.stderr)
            return 2

    if args.write_baseline:
        Path(args.write_baseline).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write_baseline).write_text(
            json.dumps([f.to_dict() for f in findings], indent=2) + "\n"
        )
        if not args.quiet:
            print(f"width_lint: wrote baseline ({len(findings)} entries) to "
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
            # The summary says WHAT it checked, not just how much it found —
            # `0 finding(s)` used to read repo-wide as "no width bugs" while
            # the label check verified only annotation PRESENCE
            # .
            print(f"width_lint: {len(findings)} finding(s) across {len(files)} file(s)")
            print(
                "  checked: label annotations present AND true against every "
                "same-file arrival\n"
                "  (fallthrough/branch/jmp/jsr/jsl), tax/tay in A8/I16, macro "
                "sep/rep contracts,\n"
                "  stz-long"
            )
            # The cross-file pass's own reach. It activates only where the
            # CALLEE declares, so these three numbers are the difference
            # between "checked nothing" and "checked something" — a run with
            # 0 declarations is disarmed and says so rather than printing a
            # clean line.
            print(
                f"  contracts: {stats.declared} declared "
                f"({stats.routines} routine, {stats.macros} macro); "
                f"{stats.sites_checked} cross-file call-site width(s) "
                f"compared across {len(stats.callees)} declared callee(s)"
            )
            if stats.sites_unprovable:
                print(
                    f"  unprovable: {stats.sites_unprovable} cross-file "
                    f"width(s) skipped — the CALLER's own tracked width is "
                    f"unknown at the site, which is not a finding and is not "
                    f"a proof either"
                )
            if stats.sites_ambiguous:
                print(
                    f"  ambiguous: {stats.sites_ambiguous} call(s) NOT "
                    f"resolved — the callee's name is defined in more than "
                    f"one file in this run\n"
                    f"  ({', '.join(sorted(stats.ambiguous_names))}), so a "
                    f"whole-tree pass cannot say which one a caller links "
                    f"against.\n"
                    f"  A unique name is what buys the check"
                )
            if stats.declared == 0:
                print(
                    "  NOTE: no contract declared in this file set, so the "
                    "cross-file pass is inert — an exported routine's width\n"
                    "  contract is proven only on the emulator until it "
                    "declares (AGENTS.md, 'The routine contract')"
                )
            for rule, n in sorted(counts.items()):
                print(f"  {rule}: {n}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
