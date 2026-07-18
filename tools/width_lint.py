#!/usr/bin/env python3
"""
width_lint.py — ca65 8/16-bit width-tracking static analyzer.

Catches the recurring HIGH-severity width-tracking bug class documented in
CLAUDE.md Critical Rule 7. The linter implements three pattern-matching
checks against single-file ca65 source:

  Check 1: Multi-path label has explicit width annotation.
           A label reached from more than one distinct A-width or I-width
           mode must carry an explicit `.a8` / `.a16` / `.i8` / `.i16`
           directive within the lookahead window (5 lines after the label,
           before any non-comment, non-directive instruction).

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
    rule: str  # 'multipath-label' | 'tax-tay-cross-width' | 'macro-no-contract'
    message: str
    label: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
            "label": self.label,
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
    # label name -> list of (line_number, arrival_mode) for branches + fallthrough
    arrivals: dict[str, list[tuple[int, tuple[str, str]]]] = field(default_factory=dict)
    # label name -> line where defined (1-indexed)
    label_def_line: dict[str, int] = field(default_factory=dict)


# --- Helpers -----------------------------------------------------------------

def strip_comment(line: str) -> str:
    """Return the part of `line` before any ';' comment delimiter."""
    idx = line.find(";")
    return line if idx < 0 else line[:idx]


def is_real_instruction(line: str) -> bool:
    """Lines that should terminate the multi-path-label lookahead window."""
    if RE_COMMENT_OR_BLANK.match(line):
        return False
    if RE_DIRECTIVE.match(line):
        # Most directives are bookkeeping (.a8/.a16, .res, .word, .segment).
        # We treat them as non-instructions so a `.a8` after a label still
        # qualifies as the explicit annotation.
        return False
    if RE_LABEL.match(line):
        return False
    return True


def has_explicit_width_annotation(lines: list[str], start_idx: int, window: int = 5) -> bool:
    """
    Scan up to `window` non-blank lines starting at start_idx for an
    explicit `.a8`/`.a16`/`.i8`/`.i16` directive, terminating early when
    a real instruction (other than `sep`/`rep`) is encountered.

    The canonical width-sync block after a multi-path label is the pair
        sep #$20
        .a8
    (or `rep #$20` + `.a16`). The directive on the second line is the
    annotation we require; the `sep`/`rep` on the first line synchronizes
    runtime width but does not by itself update ca65's tracked state.
    The window therefore tolerates one or more leading `sep`/`rep`
    instructions before the annotation.
    """
    n = len(lines)
    seen = 0
    for i in range(start_idx, min(start_idx + window + 8, n)):
        line = lines[i]
        # An annotation line satisfies the requirement.
        if RE_WIDTH_A.match(line) or RE_WIDTH_I.match(line):
            return True
        # sep/rep is a runtime width-sync — allow it as part of the
        # prelude before the annotation.
        if RE_SEP.match(line) or RE_REP.match(line):
            seen += 1
            if seen > window:
                return False
            continue
        if is_real_instruction(line):
            return False
        # Don't count comments/labels against the window.
        if not RE_COMMENT_OR_BLANK.match(line) and not RE_LABEL.match(line):
            seen += 1
            if seen > window:
                return False
    return False


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
        # line for comment-pattern checks elsewhere.
        line = strip_comment(raw)

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
        m = RE_WIDTH_A.match(line)
        if m:
            state.a = m.group(1).lower()
        m = RE_WIDTH_I.match(line)
        if m:
            state.i = m.group(1).lower()

        # Apply sep / rep — these change runtime width. ca65 uses these
        # alongside .a8/.a16, but the directive is what tracks assembler
        # state. For OUR analysis we model the runtime intent: sep #$20
        # means A-width 8, rep #$20 means A-width 16.
        m = RE_SEP.match(line)
        if m:
            mask = int(m.group(1), 16)
            if mask & 0x20:
                state.a = "a8"
            if mask & 0x10:
                state.i = "i8"
        m = RE_REP.match(line)
        if m:
            mask = int(m.group(1), 16)
            if mask & 0x20:
                state.a = "a16"
            if mask & 0x10:
                state.i = "i16"

        # Branches: record the destination label as reached from the
        # current state.
        m = RE_BRANCH.match(line)
        if m:
            label = m.group(2)
            fa.arrivals.setdefault(label, []).append(
                (idx + 1, state.as_tuple())
            )

        # Label definitions: register the line where defined.
        m = RE_LABEL.match(line)
        if m:
            name = m.group(1)
            fa.label_def_line[name] = idx + 1
            # Fall-through arrival: if the previous non-blank/comment line
            # was an instruction that's NOT an unconditional branch / return,
            # this label is reached by fall-through with the current state.
            prev = _previous_real_instruction(lines, idx)
            if prev is not None:
                ptext = strip_comment(prev).strip().lower()
                first_token = ptext.split()[0] if ptext.split() else ""
                if first_token not in UNCOND_BRANCHES and not RE_RETURN.match(prev):
                    fa.arrivals.setdefault(name, []).append(
                        (idx + 1, state.as_tuple())
                    )

    return fa


def _previous_real_instruction(lines: list[str], idx: int) -> Optional[str]:
    """Walk backward from idx-1 and return the first line that is a real
    instruction (not blank, not pure comment, not label, not directive)."""
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
        return lines[i]
    return None


# --- The three checks --------------------------------------------------------

def check_multipath_labels(fa: FileAnalysis) -> list[Finding]:
    """
    Check 1: a label reached from more than one (a_mode, i_mode) pair must
    have an explicit `.a8` / `.a16` / `.i8` / `.i16` annotation in the
    immediate lookahead window.

    A pair only counts as "different" if at least one component differs and
    neither component is UNKNOWN — UNKNOWN means the analyzer never saw an
    annotation on that path, which is too noisy to flag at this resolution.
    """
    findings: list[Finding] = []

    for label, arrivals in fa.arrivals.items():
        if label not in fa.label_def_line:
            # Branch to an external symbol — out of scope.
            continue

        # Reduce arrivals to a set of width-tuples, ignoring UNKNOWN
        # components. This avoids the false-positive where one arrival
        # was from a path that hadn't yet declared its width.
        modes_a = {a for (_ln, (a, _i)) in arrivals if a != UNKNOWN}
        modes_i = {i for (_ln, (_a, i)) in arrivals if i != UNKNOWN}

        # Multi-path = >1 distinct A-width OR >1 distinct I-width.
        is_multipath = len(modes_a) > 1 or len(modes_i) > 1
        if not is_multipath:
            continue

        def_line = fa.label_def_line[label]
        # Lookahead starts on the line AFTER the label definition.
        if has_explicit_width_annotation(fa.lines, def_line):
            continue

        # Allow override directly at the label.
        if has_override(fa.lines, def_line - 1):
            continue

        modes_str = ", ".join(sorted({f"({a}/{i})" for (_ln, (a, i)) in arrivals}))
        findings.append(
            Finding(
                file=fa.path,
                line=def_line,
                rule="multipath-label",
                message=(
                    f"label '{label}' reached from multiple width modes "
                    f"{{{modes_str}}} but has no explicit .a8/.a16/.i8/.i16 "
                    f"annotation within 5 lines"
                ),
                label=label,
            )
        )

    return findings


def check_tax_tay_cross_width(fa: FileAnalysis) -> list[Finding]:
    """
    Check 2: tax / tay in A8 mode must document the cross-width contract.

    In A16/I16 mode, `tax` transfers the full 16-bit accumulator — that's
    the ordinary index-load idiom and not a bug. In A8/I16 mode (the
    Phase 15-1 bug pattern), `tax` ALSO transfers the full 16-bit C
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
    cost agents time twice (S1 + S2a Mode-1 streaming paper cuts).

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
            print(f"width_lint: {len(findings)} finding(s) across {len(files)} file(s)")
            for rule, n in sorted(counts.items()):
                print(f"  {rule}: {n}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
