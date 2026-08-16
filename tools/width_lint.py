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

           SINGLE-FILE LIMITATION (deliberate): only same-file arrivals
           exist. Callers of an exported routine that live in another file
           (e.g. `col_map_at`'s callers in race.asm) are invisible from
           the defining file in either direction — a cross-file
           caller/callee width-contract violation is NOT caught. In-file
           `jsr`/`jsl` sites ARE checked against the entry annotation.

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
RE_CALL = re.compile(
    r"^\s*(jsr|jsl)\s+([A-Za-z_@][\w@:.]*)",
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


# --- Public API --------------------------------------------------------------

def lint_file(path: str | Path) -> list[Finding]:
    """Run all four checks against a single ASM file. Returns findings."""
    fa = analyze_file(path)
    findings: list[Finding] = []
    findings.extend(check_multipath_labels(fa))
    findings.extend(check_tax_tay_cross_width(fa))
    findings.extend(check_macro_contracts(fa))
    findings.extend(check_stz_long(fa))
    findings.sort(key=lambda f: (f.file, f.line, f.rule))
    return findings


def lint_paths(paths: list[str]) -> list[Finding]:
    """Run linter against multiple paths. Files only — caller globs."""
    all_findings: list[Finding] = []
    for p in paths:
        all_findings.extend(lint_file(p))
    return all_findings


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

    # Expand directories: caller is responsible for globbing, but support a
    # single path that's a directory by descending (one level) for convenience.
    files: list[str] = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            files.extend(str(x) for x in sorted(path.rglob("*.asm")))
            files.extend(str(x) for x in sorted(path.rglob("*.inc")))
        elif path.exists():
            files.append(str(path))
        else:
            print(f"width_lint: file not found: {p}", file=sys.stderr)
            return 2

    findings: list[Finding] = []
    for f in files:
        findings.extend(lint_file(f))
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
                "  (fallthrough/branch/jmp/jsr/jsl; cross-file callers "
                "invisible), tax/tay in\n"
                "  A8/I16, macro sep/rep contracts, stz-long"
            )
            for rule, n in sorted(counts.items()):
                print(f"  {rule}: {n}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
