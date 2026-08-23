#!/usr/bin/env python3
"""
batch_union.py — resolve a batch landing's conflicts as a KEEP-BOTH union,
                 and prove the result still parses.

WHY THIS EXISTS. Landing a batch of rail ports means merging N branches that
each appended themselves to the same handful of registration files — the
`Makefile`, `tests/conftest.py`, `tools/bare_check.sh`,
`docs/09_feature_register.md`, and (until the hosted workflow was retired on
2026-08-22) `.github/workflows/ci.yml`. Every one of those conflicts has the
same correct resolution: KEEP BOTH SIDES. It is mechanical, so it gets done
with a throwaway script, and the throwaway script is where the damage happens.

THE THREE DROPS THIS TOOL EXISTS FOR: three consecutive landings lost a
ci.yml rail step's

    test "$size" -eq 524288 || { echo "::error::..."; exit 1; }

line, because it sat at a hunk boundary — patrol's in the sprite_game merge,
jumper's in the stomper merge, stomper's in the scroll_run merge. The line is
the ONLY thing in a CI step that fails on a truncated link, so losing it turns
the step into "make it and hope". `make rail-registered` named each drop (its
ci.yml site, by rail) which is why they were caught at all; that is a backstop,
not a reason to keep generating them — and it is a backstop that no longer
exists, since the site went out with the workflow file (docs/44 §6).

The boundary shape is worth naming, because it is not a freak alignment. Every
rail step in ci.yml ends with an assert line and is followed by a blank line
and `- name: make <next>`. When two branches each append a step there, git
frequently aligns the conflict on the BLANK LINE rather than on the assert, so
the PREVIOUS rail's assert ends up INSIDE both sides and the new rail's assert
sits in the shared trailing context. Any resolver that "dedupes the repeated
boundary line" then deletes one real assert — and since every rail asserts the
same 524,288 bytes, the deletion is invisible to a diff-reading human: the file
still contains plenty of identical-looking assert lines, just one fewer than it
has steps.

So this tool does NOT dedupe, ever. Its contract is arithmetic:

    every non-marker line inside a conflict region appears in the output,
    in order, ours before theirs — and the tool COUNTS them and refuses if
    the count does not match.

That check is the whole point. A union that silently drops a line is the
defect; a union that duplicates one is a visible, harmless nuisance you fix by
hand. The two failure directions are not symmetric and this tool is biased
accordingly.

NO REGEX SUBSTITUTION. Plain string and list operations only. The sibling cut
from the same landing: a shape-repair pass written with `re.sub` died on
`re.error: bad escape` because the replacement text ended in `; do \\` —
backslashes in a replacement string are an escape language, and Makefile / shell
/ CI text is full of them. Batch 1 had already learned "plain `str.replace`
only" and the lesson did not survive into batch 2's first draft, so it is
written into the tool this time rather than into a memory. `re` is not
imported here; keep it that way.

WHAT IT DOES NOT DO. It does not know whether keep-both is the RIGHT
resolution — for a registration list it always is, for a doc paragraph or a
version pin it often is not, and this tool cannot tell those apart. It reads
`<<<<<<<` and unions. Review the diff. In particular `docs/09_feature_register.md`
§3.1 'serves' entries are HAND-WRITTEN prose that `make register-write` does
NOT regenerate, so carry those across before regenerating, not after.

And the validation battery is a PARSE check, not a correctness check — with
ONE named exception, added because the parse-only reading shipped a defect.
A `.yml` that loads is not a workflow that runs the steps you meant, and
`make -n gates` proves the recipe expands, not that the rails are registered.
`make rail-registered` is the authoritative shape check for a rail landing,
and this tool prints that reminder on every run rather than letting a green
verdict imply more than it is.

THE EXCEPTION: the ci.yml STEP SHAPE (see `ci_rom_steps` below). Batch 4
produced the other half of the drop class and the arithmetic contract above
could not see it — `ac7b738` MOVED `svd-nowin`'s assert into the following
step instead of deleting it, so every line survived, the count matched, the
YAML parsed, and the ROM's size ended up asserted nowhere. A tool whose whole
purpose is "do not lose the assert line" that passes a union which relocated
the assert line is not doing its job. So a step that builds and measures a ROM
must also assert its size, and this refuses the union if one does not.

USAGE
    tools/batch_union.py FILE...            union in place, then validate
    tools/batch_union.py --check FILE...    validate only; writes nothing
    tools/batch_union.py --check Makefile tests/conftest.py

Recovery, if a union comes out wrong: `git checkout --merge -- FILE` restores
the conflicted state, markers and all.

Exit: 0 iff every file unioned cleanly AND every validator passed.
"""
from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

OURS_MARK = "<<<<<<<"
BASE_MARK = "|||||||"
MID_MARK = "======="
THEIRS_MARK = ">>>>>>>"

RAIL_REMINDER = (
    "reminder: a parse is not a registration. `make rail-registered` is the "
    "authoritative shape check for a rail landing — it is what named all "
    "three of the assert lines this tool exists to stop dropping, back when "
    "they lived in a workflow file it read.")


class ConflictError(Exception):
    """The markers themselves are malformed — refuse rather than guess."""


# --------------------------------------------------------------------------
# the union
# --------------------------------------------------------------------------

@dataclass
class Hunk:
    """One conflict region. `base` is diff3's common ancestor, and is DROPPED
    — it is the text both sides changed, not text either side wants."""
    start: int                       # line index of the `<<<<<<<` marker
    ours: list[str] = field(default_factory=list)
    base: list[str] = field(default_factory=list)
    theirs: list[str] = field(default_factory=list)

    @property
    def kept(self) -> list[str]:
        return self.ours + self.theirs


@dataclass
class Union:
    text: str
    hunks: list[Hunk]
    kept_lines: int                  # lines emitted from inside conflicts
    conflict_lines: int              # non-marker lines that were inside them

    @property
    def dropped(self) -> int:
        """Lines that were inside a conflict and are NOT in the output.

        Base lines are deliberately not counted as conflict content (see
        `Hunk`), so on a well-formed run this is always 0 and any other value
        is a bug in this file, caught here rather than in CI three landings
        later.
        """
        return self.conflict_lines - self.kept_lines


def _starts(line: str, mark: str) -> bool:
    """Marker test. A conflict marker is 7 identical characters at the start
    of a line, optionally followed by a label — `str.startswith`, no regex."""
    return line.startswith(mark)


def union_text(text: str) -> Union:
    """Keep-both union: ours then theirs, per hunk, nothing deduped.

    Plain list operations throughout. The line list keeps its terminators via
    `splitlines(keepends=True)` so a file with no trailing newline round-trips
    unchanged — a batch landing should not also be a whitespace commit.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    hunks: list[Hunk] = []
    conflict_lines = 0

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not _starts(line, OURS_MARK):
            out.append(line)
            i += 1
            continue

        h = Hunk(start=i)
        i += 1
        side = "ours"
        closed = False
        while i < n:
            cur = lines[i]
            if _starts(cur, OURS_MARK):
                raise ConflictError(
                    f"line {i + 1}: a second `{OURS_MARK}` inside an unclosed "
                    f"conflict that opened at line {h.start + 1}. Conflicts do "
                    f"not nest; this file was hand-edited or concatenated.")
            if _starts(cur, BASE_MARK):
                if side != "ours":
                    raise ConflictError(
                        f"line {i + 1}: `{BASE_MARK}` after `{MID_MARK}` in the "
                        f"conflict at line {h.start + 1}")
                side = "base"
                i += 1
                continue
            if _starts(cur, MID_MARK):
                if side == "theirs":
                    raise ConflictError(
                        f"line {i + 1}: a second `{MID_MARK}` in the conflict "
                        f"at line {h.start + 1}")
                side = "theirs"
                i += 1
                continue
            if _starts(cur, THEIRS_MARK):
                if side != "theirs":
                    raise ConflictError(
                        f"line {i + 1}: `{THEIRS_MARK}` before any `{MID_MARK}` "
                        f"in the conflict at line {h.start + 1}")
                closed = True
                i += 1
                break
            getattr(h, side).append(cur)
            i += 1

        if not closed:
            raise ConflictError(
                f"the conflict opened at line {h.start + 1} is never closed "
                f"by `{THEIRS_MARK}` — refusing to guess where it ends")

        conflict_lines += len(h.ours) + len(h.theirs)
        out.extend(h.kept)
        hunks.append(h)

    kept = sum(len(h.kept) for h in hunks)
    u = Union(text="".join(out), hunks=hunks,
              kept_lines=kept, conflict_lines=conflict_lines)
    if u.dropped:
        raise ConflictError(
            f"INTERNAL: {u.dropped} conflict line(s) did not reach the output. "
            f"This is the exact defect this tool exists to prevent (three "
            f"dropped ci.yml assert lines) — do not use the result.")
    return u


def has_conflict_markers(text: str) -> bool:
    for line in text.splitlines():
        if _starts(line, OURS_MARK):
            return True
    return False


# --------------------------------------------------------------------------
# the validation battery — a PARSE check, per file kind
# --------------------------------------------------------------------------

def _validate_python(text: str, _path: Path) -> tuple[bool, str]:
    try:
        ast.parse(text)
    except SyntaxError as e:
        return False, f"ast.parse: line {e.lineno}: {e.msg}"
    return True, "ast.parse ok"


# --------------------------------------------------------------------------
# the ci.yml STEP SHAPE — the one semantic check in a parse-only battery
# --------------------------------------------------------------------------
#
# WHY A PARSE WAS NOT ENOUGH, on the record. The three drops above were
# LOST LINES, and the arithmetic contract stops those. Batch 4 produced the
# other half of the class and the arithmetic could not see it: `ac7b738`'s
# shape repair inserted `split_v_seamtrial`'s `- name:` between `svd-nowin`'s
# `echo` and its `test "$size" -eq 524288`, so the assert MOVED rather than
# vanished. Every line survived. The YAML still parsed. The line count was
# unchanged. And `build/svd_nowin.sfc`'s size went from asserted-once to
# asserted-nowhere, because `make rail-registered`'s ci.yml site was scoped to
# rails under `game/` and `svd-nowin` is a variant target. Fifth instance of
# the drop class across waves, first uncaught.
#
# So the battery gains ONE semantic check, narrowly scoped to the invariant
# the landings actually violate: a step that builds and measures a ROM must
# assert its size, in its own block, after the stat that feeds `$size`. It is
# deliberately the same condition `tools/rail_registered.py`'s ROM-step sweep
# used, so the two tools could not disagree about what a ROM step is — this
# one caught it at UNION time, before the commit; that one caught it at GATE
# time, after.
#
# THAT PAIRING IS OVER as of 2026-08-22. The hosted workflow was retired and
# `.github/workflows/ci.yml` deleted, so the gate-time sweep went with the
# file it read (docs/44 §6) and this repository no longer contains a workflow
# for this check to fire on. It is kept because the check is dispatched on the
# FILENAME, not on a path: it still runs over `tests/fixtures/batch_union/`'s
# recorded conflicts, and it would still run over any `ci.yml` a future
# landing put back. What is gone is the gate-time half in the form it had:
# nothing catches this SHAPE after the commit any more.
#
# THE FAILURE IT PROTECTED AGAINST IS COVERED AGAIN as of 2026-08-23, by a
# different mechanism and one worth knowing about before writing another
# shape check. `tools/bare_check.sh` no longer carries a list of ROMs at all:
# it measures every `build/*.sfc` the gate block leaves behind, takes each
# image's expected length from that image's own header, and demands the set
# `tools/rail_registered.py --expected-images` derives from the `gates:`
# run-list. `build/svd_nowin.sfc` is in that set, so the descendant of the
# recorded defect — a variant ROM that stops being built or comes out the
# wrong length — goes RED by name at gate time (docs/44 §7). What this tool
# still uniquely offers is UNION time, before the commit.
#
# PLAIN STRING OPS ONLY, like everything else here. No `re` import (the module
# docstring says why, and `tests/test_batch_union.py` asserts it).

_STAT = "stat -c%s "
_ASSERT = 'test "$size" -eq'


def _rom_of(line: str) -> str | None:
    """The `build/x.sfc` a `stat -c%s ...` line measures, or None."""
    if _STAT not in line:
        return None
    tail = line.split(_STAT, 1)[1].lstrip()
    tok = ""
    for ch in tail:
        if ch.isspace() or ch in ")\"'`;":
            break
        tok += ch
    return tok if tok.endswith(".sfc") else None


def ci_rom_steps(text: str) -> list[tuple[str, list[str], bool]]:
    """(step name, ROMs it stats, does it assert their size) per ROM step.

    A step opens at a `- name:` line and runs to the next one. It counts as a
    ROM step when its block invokes `make` AND stats at least one `*.sfc` —
    the stat is the observable that says "this step measured a ROM", since a
    target's outputs cannot be known from text. `asserted` requires the assert
    to appear AFTER the first stat: a union that aligns one line differently
    can park it above, where `$size` is unset and the step dies on a shell
    error instead of on a size mismatch.
    """
    lines = text.splitlines()
    opens = [i for i, ln in enumerate(lines)
             if ln.strip().startswith("- name:")]
    steps = []
    for n, i in enumerate(opens):
        end = opens[n + 1] if n + 1 < len(opens) else len(lines)
        block = lines[i:end]
        name = lines[i].strip()[len("- name:"):].strip()
        if not any(ln.strip().startswith("make ") or ln.strip() == "make"
                   for ln in block):
            continue
        roms, first_stat = [], None
        for k, ln in enumerate(block):
            rom = _rom_of(ln)
            if rom is not None:
                roms.append(rom)
                if first_stat is None:
                    first_stat = k
        if first_stat is None:
            continue
        asserted = any(_ASSERT in ln for ln in block[first_stat + 1:])
        steps.append((name, roms, asserted))
    return steps


def ci_step_shape(text: str) -> tuple[bool, str]:
    """The step-shape verdict for a workflow candidate."""
    steps = ci_rom_steps(text)
    if not steps:
        return True, "no ROM-building steps"
    bad = [(name, roms) for name, roms, ok in steps if not ok]
    if bad:
        detail = "; ".join(
            f"`{name}` stats {', '.join(roms)} but has no "
            f"`{_ASSERT} N` after it" for name, roms in bad)
        return False, (
            f"ci.yml step shape: {len(bad)} of {len(steps)} ROM step(s) lost "
            f"their size assert — {detail}. This is the observed shape: "
            f"the assert did not vanish, it MOVED into the following step, so "
            f"no line was lost and the YAML still parses. Move the "
            f"`{_ASSERT} N ...` line back above the next `- name:`.")
    return True, f"{len(steps)} ROM step(s), all assert their size"


def _validate_yaml(text: str, _path: Path) -> tuple[bool, str]:
    shape_ok, shape = ci_step_shape(text)
    try:
        import yaml                                     # noqa: PLC0415
    except ImportError:
        parse = "yaml SKIPPED (pyyaml not installed)"
    else:
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as e:
            # a file that does not parse has no reviewable step shape either;
            # report the parse error, which is the actionable one
            return False, f"yaml.safe_load: {str(e).splitlines()[0]}"
        parse = "yaml.safe_load ok"
    if not shape_ok:
        return False, f"{parse}; {shape}"
    return True, f"{parse}; {shape}"


def _validate_shell(text: str, path: Path) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(text)
        tmp = Path(fh.name)
    try:
        r = subprocess.run(["bash", "-n", str(tmp)],
                           capture_output=True, text=True, timeout=60)
    finally:
        tmp.unlink(missing_ok=True)
    if r.returncode != 0:
        first = (r.stderr.strip().splitlines() or ["(no message)"])[0]
        # bash names the temp file; say the real one
        return False, f"bash -n: {first.replace(str(tmp), path.name)}"
    return True, "bash -n ok"


def _validate_makefile(text: str, _path: Path) -> tuple[bool, str]:
    """`make -n gates` against the CANDIDATE, from the repo root.

    `-f` on a temp copy rather than on the file in place, so `--check` really
    writes nothing and a broken candidate is never the tree's Makefile even
    for the length of one subprocess.

    WHAT `-n` CATCHES, stated narrowly because the obvious reading is too
    generous: MAKE-level parse errors over the whole file — "recipe commences
    before first target" (a hunk landed at the wrong offset, the most likely
    union damage), "missing 'endef', unterminated 'define'", "invalid syntax
    in conditional", "missing separator". All three were measured against
    this repo's Makefile; all exit 2.

    WHAT IT DOES NOT CATCH: shell syntax inside a recipe. `-n` PRINTS recipe
    lines instead of running them, so a `gates:` body that lost a backslash
    mid-continuation still expands cleanly here and fails only when run. Nor
    does it check that the gate block still names every rail — that is
    `make rail-registered`, which is the reminder this tool prints on every
    invocation.

    *** `BUILD=` IS LOAD-BEARING AND MUST NOT BE DROPPED. ***

    `-n` IS NOT A DRY RUN when the recipe invokes `$(MAKE)`. GNU make treats
    any recipe line containing `$(MAKE)` as recursive and EXECUTES it even
    under `-n`, so that sub-makes can print their own output — and this
    repo's whole `gates:` body is one backslash-continued shell line with
    `$(MAKE)` inside its `run()` function. So `make -n gates` really runs
    that shell: the `rm -f $(BUILD)/gates_summary.txt`, every `printf >>`,
    the `cat`. Measured, painfully: calling this validator from a pytest
    module during a live `make gates` DELETED the running block's
    `build/gates_summary.txt` and left the final summary reading `measure ok`
    for a gate that had failed twenty minutes earlier (a DX work item;
    , the friction log).

    Overriding `BUILD` on the command line fixes it at the root: a
    command-line variable beats the file's `BUILD := build` AND propagates to
    every sub-make through MAKEFLAGS, so whatever the recipe executes writes
    into a throwaway directory. Parse errors are unaffected — make parses the
    whole file before it builds anything, which is the property this check
    actually rests on.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".mk", delete=False,
                                     dir=str(REPO)) as fh:
        fh.write(text)
        tmp = Path(fh.name)
    sandbox = tempfile.mkdtemp(prefix="batch_union_build_")
    try:
        r = subprocess.run(
            ["make", "-f", str(tmp), "-n", "gates", f"BUILD={sandbox}"],
            cwd=REPO, capture_output=True, text=True, timeout=300)
    finally:
        tmp.unlink(missing_ok=True)
        shutil.rmtree(sandbox, ignore_errors=True)
    if r.returncode != 0:
        first = (r.stderr.strip().splitlines() or ["(no message)"])[0]
        return False, f"make -n gates: {first.replace(str(tmp), 'Makefile')}"
    return True, "make -n gates ok"


def validator_for(path: Path):
    """Pick the battery member by name/suffix. Unknown kinds are NOT an
    error — a unioned .md or .txt has nothing to parse, and refusing it would
    push people back to the throwaway script."""
    if path.name == "Makefile" or path.suffix == ".mk":
        return _validate_makefile
    if path.suffix == ".py":
        return _validate_python
    if path.suffix in (".yml", ".yaml"):
        return _validate_yaml
    if path.suffix == ".sh":
        return _validate_shell
    return None


def validate(text: str, path: Path) -> tuple[bool, str]:
    v = validator_for(path)
    if v is None:
        return True, "no parser for this kind — not checked"
    return v(text, path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

@dataclass
class FileResult:
    path: Path
    hunks: int
    kept: int
    ok: bool
    detail: str
    wrote: bool = False


def process(path: Path, *, check_only: bool) -> FileResult:
    text = path.read_text()
    if has_conflict_markers(text):
        u = union_text(text)
        candidate, hunks, kept = u.text, len(u.hunks), u.kept_lines
    else:
        candidate, hunks, kept = text, 0, 0

    ok, detail = validate(candidate, path)
    wrote = False
    if not check_only and candidate != text:
        path.write_text(candidate)
        wrote = True
    return FileResult(path=path, hunks=hunks, kept=kept, ok=ok,
                      detail=detail, wrote=wrote)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.strip().splitlines()[1].strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path,
                    help="conflicted files to union (or, with --check, to "
                         "validate)")
    ap.add_argument("--check", action="store_true",
                    help="validate only — compute the union in memory, run "
                         "the battery on it, write nothing")
    a = ap.parse_args(argv)

    results: list[FileResult] = []
    failed = False
    for p in a.files:
        if not p.exists():
            print(f"  {p}: MISSING", file=sys.stderr)
            failed = True
            continue
        try:
            results.append(process(p, check_only=a.check))
        except ConflictError as e:
            print(f"  {p}: REFUSED — {e}", file=sys.stderr)
            failed = True

    mode = "check" if a.check else "union"
    print(f"batch_union ({mode}):")
    for r in results:
        verdict = "ok  " if r.ok else "FAIL"
        wrote = "written" if r.wrote else ("would write" if not a.check
                                           and r.hunks else "unchanged")
        print(f"  {verdict}  {str(r.path):<40} "
              f"{r.hunks} hunk(s), {r.kept} line(s) kept, {wrote}")
        print(f"        {r.detail}")
        if not r.ok:
            failed = True

    total_hunks = sum(r.hunks for r in results)
    total_kept = sum(r.kept for r in results)
    print(f"  ---- {len(results)} file(s), {total_hunks} conflict(s), "
          f"{total_kept} line(s) kept (ours then theirs, nothing deduped)")
    print(f"  {RAIL_REMINDER}")
    if not a.check and any(r.wrote for r in results):
        print("  recovery, if a union came out wrong: "
              "`git checkout --merge -- FILE`")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
