#!/usr/bin/env python3
"""
zp_lint.py — ca65 Direct Page (DP) byte-ownership static analyzer.

Catches the recurring HIGH-severity DP allocation-collision bug class
documented in CLAUDE.md "ZP Allocation Discipline" (sibling of
"Width-Risk Regions"). The linter implements the SSoT discipline
established by the Phase 16-6-0 bright_fade audit chain and the ZP
allocation audit (docs/audit/zp_allocation_landscape.md): every DP byte
touched by `engine/`, `src/`, `tests/`, or `templates/` ASM must be
backed by a declared symbol in engine/engine_state.inc (or one of the
include'd `.inc` files), OR carry an explicit
`; ZP-LINT: ok — <reason>` override within 3 lines.

The check is purely textual cross-reference: the linter parses every
`= $XX` equate from engine/engine_state.inc (and related .inc files),
builds a symbol table mapping DP byte → declaring symbol(s), then walks
every `.asm` file for DP-touching instructions with raw hex operands
(`lda $A0`, `sta <$B0`, `inc $B8`, etc.). A raw hex DP touch passes if
the byte is covered by a declared symbol's range; otherwise it is a
finding.

Detected addressing modes:
  Direct page absolute (8-bit operand)            lda $XX
  Forced DP (`<` prefix)                          lda <$XX
  DP indexed by X / Y                             lda $XX,x   sta $XX,y
  DP indirect, indirect indexed, indirect long    lda ($XX)   lda [$XX]
                                                  lda ($XX),y lda [$XX],y
                                                  lda ($XX,x)
  RMW / store / cmp / load on DP                  inc $XX  dec $XX  cmp $XX
                                                  asl $XX  lsr $XX  rol $XX

Skipped (out of scope for v1 — same as width_lint's macro caveat):
  - DP relocations via tcd/tdc (caller relocates DP base); these are
    flagged once per file with a 'dp-relocation-unhandled' note. ROMs
    that toggle DP (the NMI handler is the only live example) are
    expected to claim their bytes via the .ifdef ENGINE_STATE_BASE
    aliases and trip this linter only when raw $XX appears at a site
    where DP has been retargeted.
  - Macro expansions; if a macro writes to a DP address with a hex
    operand, the linter sees the .macro body's literal write and the
    site is checked at definition time, not at expansion time. Macro
    callers that pass DP bytes as arguments fall through (the literal
    operand never appears in the call site source).

Override mechanism:
  Suppress a single line's findings with
      ; ZP-LINT: ok — <reason text>
  within the 3 lines surrounding the flagged location. Bare
  `; ZP-LINT: ok` (no reason) is rejected — the reason text is required.
  Em-dash `—`, en-dash `–`, double-hyphen `--`, single-hyphen-with-space
  ` - `, or colon `:` are all accepted as the separator.

Usage:
    python tools/zp_lint.py path/to/file.asm [more.asm ...]
    python tools/zp_lint.py --baseline reports/zp_lint_baseline.json
    python tools/zp_lint.py --json path/to/file.asm
    python tools/zp_lint.py --quiet path/to/file.asm    # exit code only

The symbol table is built from `engine/engine_state.inc` by default;
override with `--symbol-table FILE [FILE...]` to specify additional `.inc`
files containing DP byte equates.

Exit codes:
    0 — no violations (or all overridden / under baseline)
    1 — violations found
    2 — usage / IO error

Tests live under tests/test_zp_lint.py with fixtures at
tests/fixtures/zp_lint/.
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

# An equate of the form `SYMBOL = $XX` or `SYMBOL = $0XXX`. We accept any
# hex width, but only addresses < $0100 count as DP claims. (Symbols with
# 16-bit absolute addresses are absolute-WRAM aliases, not DP equates.)
RE_EQUATE = re.compile(
    r"^\s*([A-Za-z_][\w]*)\s*=\s*\$([0-9A-Fa-f]+)\s*(?:;(.*))?$",
)

# Some equates alias another symbol (e.g. SP_BC = ES_SP_BC). We track
# these so we know the symbol exists in the table, even though we can't
# resolve the address without a second pass. For the SSoT cross-reference
# we treat `SYMBOL = OTHER_SYMBOL` as defining `SYMBOL` at OTHER_SYMBOL's
# byte; the linter resolves on second pass.
RE_EQUATE_ALIAS = re.compile(
    r"^\s*([A-Za-z_][\w]*)\s*=\s*([A-Za-z_][\w]*)\s*(?:;(.*))?$",
)

# Size hint: `N bytes` or `N B` somewhere in the comment text — used to
# determine the symbol's byte-range size. Default is 1. The regex does
# NOT require a leading `;` because callers strip the comment delimiter
# before passing the text in.
RE_SIZE_HINT = re.compile(
    r"\b(\d+)\s*(?:bytes?|B)\b",
    re.IGNORECASE,
)

# DP-touching instructions. Each matches a 65816 mnemonic that, in DP mode,
# takes an 8-bit operand. We match `<$XX` (forced DP), `$XX` (DP), and the
# indirect forms `(...)` / `[...]` / `...,x` / `...,y`. The operand value
# is captured for byte-range tracking.
#
# We deliberately avoid the 16-bit absolute and long forms — those have
# different opcodes and aren't part of the DP byte-ownership question.
# The convention is that any operand whose hex value is `$00-$FF` and
# whose addressing mode is plausibly DP-relative is a DP touch.
#
# Examples that match:
#   lda $A0          DP absolute
#   sta <$A0         forced DP
#   inc $B8          DP RMW
#   lda $A0,x        DP indexed X
#   sta $A0,y        DP indexed Y
#   lda ($A0)        DP indirect
#   lda [$A0]        DP indirect long
#   lda ($A0,x)      DP indexed indirect
#   lda ($A0),y      DP indirect indexed
#   lda [$A0],y      DP indirect long indexed
#
# Examples that do NOT match:
#   lda $0100         absolute (DB-relative, not DP)
#   lda f:$7EE000     long
#   sta $0123,x       absolute,x
#   lda #$A0          immediate
#   lda $A0FF         16-bit absolute (operand >= $100)
RE_DP_INSTRUCTION = re.compile(
    # mnemonic
    r"^\s*"
    r"(lda|sta|ldx|stx|ldy|sty|cmp|cpx|cpy|inc|dec|"
    r"asl|lsr|rol|ror|and|ora|eor|adc|sbc|bit|stz|"
    r"trb|tsb)"
    r"\s+"
    # operand: optional `<` or `(` or `[` prefix, then $XX, then optional ,x/,y or ) or ]
    r"(?P<oper>"
    r"(?:<\s*)?\$(?P<hex>[0-9A-Fa-f]{1,2})\b"
    r"(?!\s*[0-9A-Fa-f])"      # not the start of a larger hex
    r"(?P<suffix>(?:\s*,\s*[xy])?(?:\s*\)\s*(?:,\s*y)?)?)"
    r"|"
    # `($XX)`, `($XX),y`, `($XX,x)`, `[$XX]`, `[$XX],y`
    r"[\(\[]\s*\$(?P<ihex>[0-9A-Fa-f]{1,2})\b"
    r"(?!\s*[0-9A-Fa-f])"
    r"\s*(?:,\s*x\s*)?[\)\]]"
    r"(?:\s*,\s*y)?"
    r")",
    re.IGNORECASE,
)

# Override comment. Required form: "; ZP-LINT: ok <SEP> <reason text>"
# Same separator set as width_lint.
RE_ZP_LINT_OK = re.compile(
    r";\s*ZP-LINT:\s*ok"
    r"(?:\s*[—–]|\s*--|\s+-\s+|\s*:\s+)"
    r"\s*(\S.*\S|\S)",
    re.IGNORECASE,
)
# Bare "; ZP-LINT: ok" with nothing after — rejected.
RE_ZP_LINT_BARE = re.compile(
    r";\s*ZP-LINT:\s*ok\s*$",
    re.IGNORECASE,
)

# Comments + blank lines (used for override window scanning).
RE_COMMENT_OR_BLANK = re.compile(r"^\s*(;.*)?$")


# --- Symbol table model ------------------------------------------------------

@dataclass
class SymbolDecl:
    """One DP byte claim by an `ES_*` (or other) symbol."""

    name: str
    start: int   # DP byte (0..255)
    size: int    # bytes claimed (default 1)
    file: str
    line: int

    @property
    def end(self) -> int:
        return self.start + self.size - 1

    def covers(self, byte: int) -> bool:
        return self.start <= byte <= self.end


@dataclass
class SymbolTable:
    """Indexed view of all DP-byte claims, built from one or more .inc files."""

    decls: list[SymbolDecl] = field(default_factory=list)
    by_name: dict[str, SymbolDecl] = field(default_factory=dict)
    # byte (0..255) -> list of SymbolDecl that cover it
    by_byte: dict[int, list[SymbolDecl]] = field(default_factory=dict)

    def add(self, decl: SymbolDecl) -> None:
        self.decls.append(decl)
        self.by_name[decl.name] = decl
        for b in range(decl.start, decl.end + 1):
            self.by_byte.setdefault(b, []).append(decl)

    def covers(self, byte: int) -> bool:
        return byte in self.by_byte


def parse_size_hint(comment: Optional[str]) -> int:
    """Extract `N bytes` size from a comment, default to 1."""
    if not comment:
        return 1
    m = RE_SIZE_HINT.search(comment)
    if m:
        return int(m.group(1))
    return 1


RE_DP_SECTION_END = re.compile(
    r"^\s*;\s*={3,}\s*(Absolute\s+WRAM|Coroutine\s+Pool|HDMA\s+Wave|"
    r"HDMA\s+Table\s+Memory|Mode\s+7\s+HDMA|HDMA\s+Channel\s+Allocator|"
    r"Mode\s+7\s+HDMA\s+Channel|Font\s+System|RGB\s+Gradient|"
    r"Tile\s+Flag)",
    re.IGNORECASE,
)


def build_symbol_table(inc_files: list[str | Path]) -> SymbolTable:
    """
    Parse one or more .inc files and assemble a DP-byte symbol table.

    Two passes:
      Pass 1: collect every `SYMBOL = $XX` equate where the literal hex
              value is < $0100 — these are direct DP claims.
      Pass 2: resolve `SYMBOL = OTHER_SYMBOL` aliases. The alias inherits
              OTHER's byte and size. Aliases to non-DP symbols (e.g.,
              `SCANLINE_OVERFLOW = $7EE108`) are silently dropped.

    Section boundaries: parsing for DP-byte claims STOPS at the first
    `; === Absolute WRAM Addresses ===` (or sibling) section header in
    each .inc file. After that point, every `= $XX` equate is either an
    absolute-WRAM alias (typically $0100+, filtered by the < $0100
    guard), a per-slot field offset (like CO_SLOT_SAVED_REGS = $06),
    or a flag-bit mask (like SCENE_FLAG_HALT = $01) — none of which
    are DP-byte claims even though their hex values fall in the DP
    range. Section-based filtering is the cleanest way to distinguish
    DP claims from these other equates without per-symbol heuristics.

    The two-pass design lets a `.inc` file declare both the canonical
    symbol and aliases that point to it, in any order.
    """
    st = SymbolTable()
    aliases: list[tuple[str, str, str, int]] = []  # (alias_name, target_name, file, line)

    for inc in inc_files:
        p = Path(inc)
        if not p.exists():
            continue
        in_dp_section = True
        for idx, raw in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines()):
            # Once we cross into the absolute-WRAM (or sibling non-DP)
            # section, stop counting equates as DP claims.
            if RE_DP_SECTION_END.match(raw):
                in_dp_section = False
                continue
            if not in_dp_section:
                # Still scan for aliases that re-export a DP symbol under
                # a new name (e.g. `MY_ALIAS = ES_FOO`); these are valid
                # documentation. Skip direct `= $XX` equates because they
                # are out of the DP region in this section.
                m = RE_EQUATE_ALIAS.match(raw)
                if m and not RE_EQUATE.match(raw):
                    aliases.append((m.group(1), m.group(2), str(p), idx + 1))
                continue
            m = RE_EQUATE.match(raw)
            if m:
                name = m.group(1)
                hexval = int(m.group(2), 16)
                comment = m.group(3) if m.group(3) else None
                # Only DP claims (< $0100). Higher addresses are absolute-WRAM
                # aliases and not in scope.
                if hexval < 0x0100:
                    size = parse_size_hint(comment)
                    decl = SymbolDecl(
                        name=name,
                        start=hexval,
                        size=size,
                        file=str(p),
                        line=idx + 1,
                    )
                    # Don't double-declare. First wins (matches ca65 semantics —
                    # subsequent equates would .ifndef-guard themselves).
                    if name not in st.by_name:
                        st.add(decl)
                continue
            m = RE_EQUATE_ALIAS.match(raw)
            if m:
                alias_name = m.group(1)
                target_name = m.group(2)
                aliases.append((alias_name, target_name, str(p), idx + 1))
                continue

    # Pass 2: resolve aliases (one level deep; chains > 1 are rare).
    for alias_name, target, file, line in aliases:
        if alias_name in st.by_name:
            continue
        target_decl = st.by_name.get(target)
        if target_decl is None:
            continue
        new_decl = SymbolDecl(
            name=alias_name,
            start=target_decl.start,
            size=target_decl.size,
            file=file,
            line=line,
        )
        st.add(new_decl)

    return st


# --- Finding model -----------------------------------------------------------

@dataclass
class Finding:
    file: str
    line: int
    rule: str  # 'undeclared-dp-byte' | 'bare-override'
    message: str
    byte: Optional[int] = None
    operand: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
            "byte": self.byte,
            "operand": self.operand,
        }

    def location(self) -> str:
        return f"{self.file}:{self.line}"


# --- Override scan -----------------------------------------------------------

def has_override(lines: list[str], idx: int, window: int = 3) -> Optional[str]:
    """
    Check if a `; ZP-LINT: ok — <reason>` comment appears within `window`
    lines before, on, or after `idx`. Returns the reason text on match, or
    None if no valid override is present. Bare `; ZP-LINT: ok` (no
    reason) does NOT count as an override.
    """
    n = len(lines)
    lo = max(0, idx - window)
    hi = min(n, idx + window + 1)
    for i in range(lo, hi):
        m = RE_ZP_LINT_OK.search(lines[i])
        if m:
            return m.group(1).strip()
    return None


def detect_bare_overrides(path: str | Path, lines: list[str]) -> list[Finding]:
    """Detect bare `; ZP-LINT: ok` (no reason text)."""
    findings: list[Finding] = []
    for idx, line in enumerate(lines):
        if RE_ZP_LINT_BARE.search(line):
            if not RE_ZP_LINT_OK.search(line):
                findings.append(
                    Finding(
                        file=str(path),
                        line=idx + 1,
                        rule="bare-override",
                        message=(
                            "bare `; ZP-LINT: ok` is rejected — the "
                            "override convention requires a reason after "
                            "the separator (e.g. `ok — transient DP scratch`)"
                        ),
                    )
                )
    return findings


# --- The check ---------------------------------------------------------------

def strip_comment(line: str) -> str:
    """Return the part of `line` before any ';' comment delimiter."""
    idx = line.find(";")
    return line if idx < 0 else line[:idx]


def check_dp_touches(path: str | Path, lines: list[str], st: SymbolTable) -> list[Finding]:
    """
    Walk a file and flag any DP-touching instruction whose operand byte
    has no covering symbol declaration AND no nearby override.
    """
    findings: list[Finding] = []
    for idx, raw in enumerate(lines):
        code = strip_comment(raw)
        if not code.strip():
            continue
        m = RE_DP_INSTRUCTION.search(code)
        if not m:
            continue
        hex_str = m.group("hex") or m.group("ihex")
        if hex_str is None:
            continue
        byte = int(hex_str, 16)
        if byte > 0xFF:
            continue
        if st.covers(byte):
            continue
        if has_override(lines, idx):
            continue
        operand = m.group("oper").strip() if m.group("oper") else f"${hex_str.upper()}"
        findings.append(
            Finding(
                file=str(path),
                line=idx + 1,
                rule="undeclared-dp-byte",
                message=(
                    f"DP byte ${byte:02X} touched by raw operand "
                    f"`{operand}` but no covering ES_*/ZP-* symbol is "
                    f"declared in engine_state.inc (or include'd files); "
                    f"add a declaration or apply `; ZP-LINT: ok — <reason>` "
                    f"if intentional"
                ),
                byte=byte,
                operand=operand,
            )
        )
    return findings


# --- Public API --------------------------------------------------------------

def lint_file(path: str | Path, st: SymbolTable) -> list[Finding]:
    """Run all DP checks against a single ASM file. Returns findings."""
    p = Path(path)
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    findings: list[Finding] = []
    findings.extend(check_dp_touches(p, lines, st))
    findings.extend(detect_bare_overrides(p, lines))
    findings.sort(key=lambda f: (f.file, f.line, f.rule, f.byte or 0))
    return findings


def lint_paths(paths: list[str], st: SymbolTable) -> list[Finding]:
    """Run linter against multiple paths."""
    all_findings: list[Finding] = []
    for p in paths:
        all_findings.extend(lint_file(p, st))
    return all_findings


def default_symbol_table_files() -> list[Path]:
    """Default .inc files used to build the symbol table."""
    repo = Path(__file__).resolve().parent.parent
    candidates = [
        repo / "engine" / "engine_state.inc",
        repo / "engine" / "engine_state_m7_legacy.inc",
    ]
    return [c for c in candidates if c.exists()]


# --- CLI ---------------------------------------------------------------------

def format_finding(f: Finding) -> str:
    return f"{f.file}:{f.line}: [{f.rule}] {f.message}"


def expand_paths(paths: list[str]) -> list[str]:
    """Expand directories (one level deep) into their .asm/.inc descendants."""
    files: list[str] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for ext in ("*.asm", "*.inc"):
                files.extend(str(x) for x in sorted(path.rglob(ext)))
        elif path.exists():
            files.append(str(path))
        else:
            raise FileNotFoundError(p)
    return files


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="ca65 Direct Page byte-ownership static analyzer.",
    )
    parser.add_argument("paths", nargs="+", help="ASM files or directories to lint")
    parser.add_argument(
        "--baseline",
        type=str,
        default=None,
        help="Path to baseline JSON (suppress findings present in baseline)",
    )
    parser.add_argument(
        "--symbol-table",
        type=str,
        nargs="+",
        default=None,
        help="Override .inc files used to build the symbol table",
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
        "--quiet", action="store_true",
        help="Suppress per-finding output; exit code only",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a per-rule summary count after the findings",
    )
    args = parser.parse_args(argv)

    # Symbol table — defaults to engine/engine_state.inc + legacy.
    if args.symbol_table:
        inc_files = args.symbol_table
    else:
        inc_files = default_symbol_table_files()
    st = build_symbol_table(inc_files)

    # Expand input paths.
    try:
        files = expand_paths(args.paths)
    except FileNotFoundError as e:
        print(f"zp_lint: file not found: {e}", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for f in files:
        findings.extend(lint_file(f, st))

    # Baseline suppression — findings present in the baseline are silenced.
    if args.baseline:
        try:
            base = json.loads(Path(args.baseline).read_text())
            base_set = {(b["file"], b["line"], b["rule"], b.get("byte"))
                        for b in base}
            findings = [
                f for f in findings
                if (f.file, f.line, f.rule, f.byte) not in base_set
            ]
        except FileNotFoundError:
            print(f"zp_lint: baseline not found: {args.baseline}", file=sys.stderr)
            return 2

    if args.write_baseline:
        Path(args.write_baseline).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write_baseline).write_text(
            json.dumps([f.to_dict() for f in findings], indent=2) + "\n"
        )
        if not args.quiet:
            print(f"zp_lint: wrote baseline ({len(findings)} entries) to "
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
            print(f"zp_lint: {len(findings)} finding(s) across {len(files)} file(s); "
                  f"symbol table has {len(st.decls)} DP symbols covering "
                  f"{len(st.by_byte)} bytes")
            for rule, n in sorted(counts.items()):
                print(f"  {rule}: {n}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
