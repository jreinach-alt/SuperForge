#!/usr/bin/env python3
"""map_lint.py — the MAP-DERIVATION lint, fourth sibling of width/time/tick.

=============================================================================
THE CLASS
=============================================================================
`allocator/no_literals.py` refuses a raw address in the ROM's own source,
because every address in this tree is emitted by the allocator and an address
written by hand is a lie waiting for a repack. That gate's scope is the
translation unit — `.asm` and `.inc`, the files ca65 compiles.

Nothing said the same thing about the PYTHON that reads the machine back.

That is not a smaller problem, it is the same problem pointed the other way. A
test that addresses VRAM or WRAM with a literal does not corrupt the console;
it corrupts the MEASUREMENT. When the allocator repacks — which it does
whenever a claim's size changes — the literal keeps pointing where the thing
used to be, and the module goes RED on a correct ROM. Measured instance
(2026-09-04): BG2's tilemap moved from $3C00 to $5000 when a tile count grew,
and a script holding the old base reported 1,230 wrong pixels in a ROM whose
CHR was byte-identical to the blob that built it. The half hour that cost went
into believing the instrument over the artifact.

The repo's stated failure mode is a test that passes while the feature is
broken. This is its mirror: a test that fails while the feature is fine. It
costs the same thing, which is trust in the gate.

=============================================================================
THE RULE, AND WHY IT IS THIS NARROW
=============================================================================
A call to a `Machine` memory accessor whose ADDRESS argument is built only
from integer literals, and is not zero.

  * Only the address argument. A literal COUNT is fine — `read_bytes(V, base,
    512)` asks for 512 bytes and 512 is 512. A literal MASK, colour, tile
    index or bit pattern is fine and is most of the four-hex-digit constants
    in this tree; a grep for those finds 251 lines and would teach people to
    ignore the gate.
  * Not zero. Address 0 is a hardware REGION ORIGIN — the start of CGRAM, of
    OAM, of WRAM — not an allocator-assigned base. It cannot move, so it
    cannot go stale. Including it turned a 14-site finding into a 128-site
    one, all of the growth legitimate.

WHAT IT DOES NOT CATCH, stated rather than discovered later:
  * an address carried in through a module constant or a fixture argument —
    the rule is single-expression, not a dataflow analysis. `BASE = 0x3C00`
    then `read_bytes(V, BASE, n)` is invisible to it.
  * a literal that is CORRECT. The gate cannot know; it demands the value be
    derived or the exemption be written down, which is the same bar
    `no_literals` sets on the ASM side.
  * anything outside `tests/` and `tools/`. The scratch script that produced
    the measured instance above lived outside the tree entirely, and no gate
    over committed files can reach that. The habit is the only defence there.

=============================================================================
THE OVERRIDE
=============================================================================
    # MAP: ok — <reason text>

within 3 lines of the finding. Em-dash, en-dash, double-hyphen, " - " and ": "
are all accepted separators; the reason text is REQUIRED and a bare
`# MAP: ok` is itself a finding — width_lint's grammar, not a fourth syntax.

Reviewers spot-check the reasons. Rubber-stamping is the regression.

Usage:
    python3 tools/map_lint.py --baseline reports/map_lint_baseline.json tests tools
    python3 tools/map_lint.py --write-baseline reports/map_lint_baseline.json tests tools

Exit: 0 — no NEW findings.  1 — new findings.  2 — bad invocation.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Optional

# --- the accessors, and the position of the ADDRESS in each ------------------
# Read off `vendor/machine.py`. The position is a semantic fact about each
# signature and cannot be derived, so it is written here — and `_verify_scope`
# checks every name still EXISTS on Machine, so a rename makes this gate fail
# loudly instead of quietly checking nothing.
ACCESSOR_ADDR_ARG = {
    "read_bytes": 1,     # (mem_type, address, count)
    "read_byte": 1,      # (mem_type, address)
    "read_u16": 1,       # (mem_type, address)
    "write_bytes": 1,    # (mem_type, address, data)
    "write_byte": 1,     # (mem_type, address, value)
    "reads": 1,          # (mem_type, addr)
    "writes": 1,         # (mem_type, addr)
}
# `read_region(mem_type)` takes no address at all and is deliberately absent.

RE_MAP_OK = re.compile(
    r"#\s*MAP:\s*ok"
    r"(?:\s*[—–]|\s*--|\s+-\s+|\s*:\s+)"
    r"\s*(\S.*\S|\S)",
    re.IGNORECASE,
)
RE_MAP_BARE = re.compile(r"#\s*MAP:\s*ok\s*$", re.IGNORECASE)
OVERRIDE_RADIUS = 3


@dataclass
class Finding:
    file: str
    line: int
    rule: str            # 'map-literal-address' | 'bare-override'
    message: str
    severity: str = "error"

    def to_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "rule": self.rule,
                "message": self.message, "severity": self.severity}

    def key(self) -> tuple:
        return (self.file, self.line, self.rule)


def _literal(node: ast.AST) -> Optional[int]:
    """The integer this expression evaluates to, if it is literals only.

    Folded rather than matched on shape, so `0x7E << 16 | 0x2000` and
    `0x3C00 * 2` are both caught — an address arithmetic-ed out of literals is
    exactly as stale as one written whole.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, int) and not isinstance(node.value, bool) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _literal(node.operand)
        return None if v is None else -v
    if isinstance(node, ast.BinOp):
        a, b = _literal(node.left), _literal(node.right)
        if a is None or b is None:
            return None
        for op, fn in ((ast.Add, lambda x, y: x + y),
                       (ast.Sub, lambda x, y: x - y),
                       (ast.Mult, lambda x, y: x * y),
                       (ast.LShift, lambda x, y: x << y),
                       (ast.BitOr, lambda x, y: x | y)):
            if isinstance(node.op, op):
                return fn(a, b)
    return None


def _addr_arg(call: ast.Call, pos: int) -> Optional[ast.AST]:
    for kw in call.keywords:
        if kw.arg in ("address", "addr"):
            return kw.value
    return call.args[pos] if len(call.args) > pos else None


def scan_source(path: str, text: str) -> tuple[list[Finding], int]:
    """-> (findings, accessor call sites examined)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], 0
    lines = text.splitlines()
    out, seen = [], 0
    for line_i, line in enumerate(lines):
        if RE_MAP_BARE.search(line) and not RE_MAP_OK.search(line):
            out.append(Finding(
                path, line_i + 1, "bare-override",
                "bare `# MAP: ok` is rejected — the reason text after the "
                "separator is REQUIRED. Say why this address cannot come from "
                "the symbol map, so a reviewer can check it."))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        pos = ACCESSOR_ADDR_ARG.get(node.func.attr)
        if pos is None:
            continue
        seen += 1
        arg = _addr_arg(node, pos)
        if arg is None:
            continue
        value = _literal(arg)
        if not value:                      # None, or the legitimate zero
            continue
        if _has_override(lines, node.lineno):
            continue
        out.append(Finding(
            path, node.lineno, "map-literal-address",
            f"`{node.func.attr}` is addressed with the literal ${value:04X}. "
            f"Every address in this tree is EMITTED — read it out of the "
            f"rail's `symbol_map.json` (tests/test_mill.py's `MAP` is the "
            f"shape), so a repack moves the test with the ROM instead of "
            f"against it. If it genuinely cannot be derived, say why in a "
            f"`# MAP: ok — <reason>`."))
    return out, seen


def _has_override(lines: list[str], lineno: int,
                  window: int = OVERRIDE_RADIUS) -> Optional[str]:
    idx = lineno - 1
    for i in range(max(0, idx - window), min(len(lines), idx + window + 1)):
        m = RE_MAP_OK.search(lines[i])
        if m:
            return m.group(1).strip()
    return None


def _verify_scope() -> list[str]:
    """Every accessor named above must still exist on Machine.

    A gate that silently stops matching is worse than no gate: it reads as
    clean. If `read_u16` is ever renamed, this makes the lint say so instead
    of examining zero call sites and exiting 0.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "vendor" / "machine.py")
    if not src.exists():
        return []
    body = src.read_text()
    return [n for n in ACCESSOR_ADDR_ARG if f"def {n}(" not in body]


def collect(targets: list[str]) -> tuple[list[Finding], int, int]:
    findings, files, sites = [], 0, 0
    for t in targets:
        p = pathlib.Path(t)
        walking = p.is_dir()
        paths = sorted(p.rglob("*.py")) if walking else [p]
        for f in paths:
            # `tests/fixtures/` holds SYNTHETIC inputs for the lints
            # themselves — planted violations that must STAY planted. Skipped
            # when WALKING a directory, but not when a file is named
            # explicitly, which is how this lint's own regression test reaches
            # its fixtures. Skipping both ways made the fixtures unreachable
            # and the first run of the regression test examined zero sites.
            if walking and "fixtures" in f.parts:
                continue
            fs, n = scan_source(str(f), f.read_text())
            findings.extend(fs)
            sites += n
            files += 1
    return findings, files, sites


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--baseline")
    ap.add_argument("--write-baseline")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args(argv)

    missing = _verify_scope()
    if missing:
        print("map_lint: DISARMED — these accessors are no longer on Machine "
              "and nothing is being checked for them: " + ", ".join(missing),
              file=sys.stderr)
        return 2

    findings, files, sites = collect(args.targets)

    if args.write_baseline:
        pathlib.Path(args.write_baseline).write_text(
            json.dumps([f.to_dict() for f in findings], indent=2) + "\n")
        print(f"map_lint: wrote baseline ({len(findings)} entries) to "
              f"{args.write_baseline}")
        return 0

    known = set()
    if args.baseline and pathlib.Path(args.baseline).exists():
        for e in json.loads(pathlib.Path(args.baseline).read_text()):
            known.add((e["file"], e["line"], e["rule"]))
    new = [f for f in findings if f.key() not in known]

    for f in new:
        print(f"{f.file}:{f.line}: [{f.rule}] {f.message}")
    if args.summary:
        print(f"map_lint: {len(new)} NEW finding(s) across {files} file(s); "
              f"{sites} accessor call site(s) examined, "
              f"{len(known)} baselined")
        print("  checked: a Machine memory accessor whose ADDRESS argument is "
              "built only from non-zero integer literals")
        print("  NOT checked: an address carried in through a constant or a "
              "fixture argument (single-expression, not dataflow); whether a "
              "literal is CORRECT; anything outside the targets given")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
