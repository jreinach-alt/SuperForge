#!/usr/bin/env python3
"""superforge -- generate the SUPPLY half of docs/09_feature_register.md from the tree.

Closes docs/08_feature_register_spec.md acceptance 5. The register's supply
census is a statement of fact about this repo, so it is derived from the repo
rather than typed by hand: a hand-typed census drifted four separate times,
including inside the work item that wrote it.

WHAT THIS OWNS (regenerated freely, inside BEGIN/END GENERATED markers)
    the §3 census -- dir, role, scope, claim classes, depends edges -- and the
    dir count in its heading, which is itself one of the four drift instances
    ("all 20 dirs" over a 25-row table, fixed in 5782ed1).

WHAT THIS MUST NOT OWN
    the demand half (§1.1/§1.2 rails, phases, status prose), §2's missing-class
    analysis, §4's architecture map, §5's unbuilt-feature needs. Those encode
    intent and measurement, not tree facts.

    But NOT owning prose does not mean not CHECKING it. `lint_demand_half`
    reads those sections and never rewrites a word. That distinction is the
    whole design: three of the four recorded drift instances lived in prose this
    generator is forbidden to emit, so a generator that only emitted the census
    would have caught one of them and been aimed at the wrong surface.

WHAT THE LINT ACTUALLY COVERS -- narrowly, because it was documented in five
places as refusing any prose "claiming a feature dir does not exist while it
does" and measured at 5 of 30 demand rows — the same shape as CLAUDE.md
rule 6's width-lint wound: a gate believed stronger than it is.

    covered      a TABLE ROW that resolves to an existing dir -- through its
                 subject cell, or through the dir named in its `supplied by`
                 column -- and also says not built / not started /
                 unimplemented / unbuilt / TODO / pending / no supplier / X.
                 Any live row in `09` §5 that resolves to an existing dir at
                 all. A `engine/features/X` citation naming no real dir.

    NOT covered  a claim in a PARAGRAPH rather than a table row. A row that
                 names no dir in either place (`AUD`, `OBJ-HUD`, `GRAD` --
                 supplier `--`, demand term not a dir name). A wrong claim
                 about a dir that does not exist yet.
                 THIS EXAMPLE LIST IS LIVE AND SHRINKS AS FEATURES LAND: a
                 term stops being an example the moment a dir spelled like it
                 appears. `POOL` graduated once and
                 `SAVE` had graduated silently at C2; both were still listed
                 here until the debut broke the fixture that used one. Measure
                 with lint_text before quoting this list.

`reach_report` measures the first against the demand tables and `--check`
prints it, so the residual is a number on every run instead of something an
audit has to rediscover. Closing it properly needs a declared demand-term ->
dir mapping on `feature.toml` (a `supplies` field mirroring `role`); that is a
work item of its own, not a widening of this regex.

SCOPE OF THE CENSUS
    engine/features/* only -- the 25 dirs docs/09 §3 accounts for. The other
    eight feature.toml files in the tree (engine/toy, engine/toy_bad,
    vendor/probes) declare role = "fixture" and are excluded here; that
    exclusion is exactly what the `fixture` role is for, and it is asserted
    rather than assumed (a non-fixture dir outside engine/features/, or a
    fixture inside it, is an error).

    And the census is built from feature.toml FILES while the sentence it emits
    counts DIRS, so `load_tree` refuses any dir under engine/features/ that
    carries no feature.toml -- otherwise a half-created feature (sources
    present, declaration absent) is uncounted and the gate says OK anyway.

USAGE
    tools/gen_register.py --check     exit 1 + unified diff if the doc drifted
    tools/gen_register.py --write     regenerate in place
                                      (`make register` / `make register-write`)
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from allocator.allocate import resolve_features                 # noqa: E402
from allocator.schemas import (FEATURE_ROLES, FeatureDecl,      # noqa: E402
                               load_feature, load_manifest, load_substrate)

REPO = Path(__file__).resolve().parent.parent
FEATURES_DIR = REPO / "engine" / "features"
REGISTER = REPO / "docs" / "09_feature_register.md"

# Documents whose DEMAND-half prose is linted against the tree (never
# rewritten). Optional by design: a checkout that does not carry one of these
# is a smaller surface to lint, not a broken gate — so the list is filtered to
# what exists rather than read blind. Reading a missing file here raises
# FileNotFoundError out of `make register`, which is a gate crashing rather
# than reporting.
DEMAND_DOCS = [REGISTER]

MANIFEST = REPO / "game" / "microzero" / "game.toml"
SUBSTRATE = REPO / "allocator" / "substrate.toml"

# Claim classes in a fixed presentation order, mapped to the FeatureDecl field
# holding them. `dma` is not a claim list -- it is the two scalar vblank budget
# fields -- so it is handled separately below.
CLAIM_CLASSES = [
    ("vram", "vram"), ("cgram", "cgram"), ("oam", "oam"),
    ("dp", "dp"), ("wram", "wram"), ("sram", "sram"), ("rom", "rom"),
    ("hdma", "hdma"), ("dma_init", "dma_init"),
    ("reg", "reg"), ("spc", "spc"),
]

BEGIN = "<!-- BEGIN GENERATED: %s -->"
END = "<!-- END GENERATED: %s -->"


class RegisterError(Exception):
    """The doc and the tree disagree, or the tree itself is inconsistent."""


# --------------------------------------------------------------------------
# tree -> facts
# --------------------------------------------------------------------------

def load_tree(repo: Path | None = None
              ) -> tuple[dict[str, FeatureDecl], dict[str, str]]:
    """Return (census features by name, scope by name).

    Scope is computed with the allocator's own `resolve_features`, not by
    reading the manifest lists directly, because `depends` pulls dirs into a
    scope without naming them there: `text_chr` appears in no list in
    game.toml and is scene-scoped purely through `vwf`/`bg_text`. Re-deriving
    that by hand would be a second implementation of the rule, free to drift
    from the one the build uses.

    `repo` scans a DIFFERENT tree, and is a test seam with one purpose: the
    duplicate-name refusal below can only be exercised by a tree that HAS a
    duplicate, and the test used to make one by planting a probe inside THIS
    repo. This glob is repo-wide, so for the length of that window every
    other `load_tree()` caller raised the same RegisterError about a file
    that was fine -- a parallel-only red, 1 full-suite run in 3


    What follows `repo` and what does not: the tree scan, the census filter,
    and the manifest all come from the given root, because they are facts
    ABOUT a tree. The substrate does not -- a scanned tree does not redefine
    the hardware, and `substrate.toml` is this repo's statement about the
    SNES either way.
    """
    repo = REPO if repo is None else Path(repo)
    features_dir = repo / "engine" / "features"
    manifest_path = repo / "game" / "microzero" / "game.toml"

    sub = load_substrate(SUBSTRATE)

    everything: dict[str, FeatureDecl] = {}
    seen: dict[str, Path] = {}
    for p in sorted(repo.glob("**/feature.toml")):
        if "build/" in p.as_posix():
            continue
        d = load_feature(p, sub)
        # A repeated `name` used to overwrite silently: a probe
        # declaring name = "vwf" rewrote the census row for the real vwf and
        # the tool reported it as census DRIFT -- a true-looking diff pointing
        # at the wrong file. The allocator itself cannot hit this (it globs one
        # features dir); this glob is repo-wide, so it must refuse.
        if d.name in everything:
            raise RegisterError(
                f"{p}: duplicate feature name '{d.name}' -- already declared "
                f"by {seen[d.name]}. Names are the census key and must be "
                f"unique across the whole tree, fixtures and probes included")
        everything[d.name] = d
        seen[d.name] = p
        in_census_dir = p.parent.parent == features_dir
        if in_census_dir and d.role == "fixture":
            raise RegisterError(
                f"{p}: role 'fixture' inside engine/features/ -- the census "
                f"accounts for every dir there, so a fixture cannot live here")
        if not in_census_dir and d.role != "fixture":
            raise RegisterError(
                f"{p}: role '{d.role}' outside engine/features/ -- dirs outside "
                f"the census must declare role = \"fixture\"")

    # THE COUNT HAS TO BE A DIR COUNT, because that is what the generated
    # sentence asserts ("All N dirs under `engine/features/` accounted for")
    # and what `make register`'s OK line prints. The census below is built from
    # feature.toml FILES, so without this a directory holding sources and no
    # declaration is invisible to the census, to the count, and to the doc's
    # completeness sentence -- all three still saying OK.
    #
    # Reproduced, not theorised: docs/audit/region_r0_review.md 3.2 planted
    # `engine/features/audit_half_made/` holding an .asm and no feature.toml,
    # so 158 dirs sat on disk, and the gate printed
    # `register OK: census matches the tree (157 dirs)` and exited 0. That is
    # the shape behind that discrepancy -- a half-created feature is exactly the
    # thing this gate exists to catch, and a silent OK is how it ships.
    #
    # Refuse the difference BY NAME, and refuse it in `load_tree` so `--write`
    # refuses too: a census cannot be truthfully regenerated while a dir it
    # claims to account for has nothing to account.
    if features_dir.is_dir():
        undeclared = sorted(q.name for q in features_dir.iterdir()
                            if q.is_dir() and not (q / "feature.toml").exists())
        if undeclared:
            raise RegisterError(
                f"engine/features/ holds {len(undeclared)} dir(s) with no "
                f"feature.toml: {', '.join(undeclared)}. The census is built "
                f"from feature.toml files but the generated sentence counts "
                f"DIRS, so an undeclared dir would be uncounted AND reported "
                f"OK. Declare each one (a feature.toml whose `name` equals the "
                f"directory name) or delete the directory.")

    census = {n: d for n, d in everything.items()
              if (features_dir / n / "feature.toml").exists()}

    manifest = load_manifest(manifest_path)
    scope: dict[str, str] = {}
    for f in resolve_features(manifest.globals_, everything, "globals"):
        scope[f.name] = "global"
    for sc in manifest.scenes:
        for f in resolve_features(sc.features, everything, f"scene '{sc.id}'"):
            scope.setdefault(f.name, "scene")
    return census, scope


def claim_summary(d: FeatureDecl) -> str:
    """`vram`x2, `cgram`, `rom`x3 -- the class census for one dir."""
    parts = []
    for label, attr in CLAIM_CLASSES:
        n = len(getattr(d, attr))
        if n:
            parts.append(f"`{label}`" + (f"&times;{n}" if n > 1 else ""))
    if d.vblank_bytes_per_frame or d.vblank_transfers_per_frame:
        parts.append("`dma`")
    return ", ".join(parts) if parts else "&mdash;"


def census_rows(census: dict[str, FeatureDecl],
                scope: dict[str, str]) -> list[dict]:
    rows = []
    for name in sorted(census):
        d = census[name]
        deps = ", ".join(f"`{x}`" for x in d.depends) if d.depends else "&mdash;"
        rows.append({
            "dir": name,
            "role": d.role,
            "scope": scope.get(name, "unused"),
            "claims": claim_summary(d),
            "depends": deps,
        })
    return rows


# --------------------------------------------------------------------------
# facts -> markdown
# --------------------------------------------------------------------------

def render_census(rows: list[dict]) -> str:
    by_role: dict[str, int] = {}
    for r in rows:
        by_role[r["role"]] = by_role.get(r["role"], 0) + 1
    tally = " &middot; ".join(f"{by_role[k]} {k}" for k in FEATURE_ROLES
                             if k in by_role)

    out = [
        # `len(rows)` IS the dir count: load_tree() refuses any dir under
        # engine/features/ that carries no feature.toml, so the two cannot
        # diverge (see its "THE COUNT HAS TO BE A DIR COUNT" guard).
        f"**All {len(rows)} dirs under `engine/features/` accounted for.** "
        f"{tally}.",
        "",
        "Generated from the tree by `tools/gen_register.py`; `make register` "
        "fails when this block and the tree disagree. Every column here is a "
        "fact a `feature.toml` states -- including `role`, which is declared "
        "rather than inferred because nothing in the claims distinguishes a "
        "blob from a feature. The judgement columns live in "
        "§3.1, which is hand-owned.",
        "",
        "| dir | role | scope | claims | depends |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        out.append(f"| `{r['dir']}` | **{r['role']}** | {r['scope']} | "
                   f"{r['claims']} | {r['depends']} |")
    return "\n".join(out)


def replace_region(text: str, tag: str, body: str) -> str:
    b, e = BEGIN % tag, END % tag
    pat = re.compile(re.escape(b) + r".*?" + re.escape(e), re.S)
    if not pat.search(text):
        raise RegisterError(f"{REGISTER.name}: no '{tag}' generated region "
                            f"(expected {b} ... {e})")
    return pat.sub(lambda _: f"{b}\n{body}\n{e}", text, count=1)


def generate(text: str) -> str:
    census, scope = load_tree()
    return replace_region(text, "census", render_census(census_rows(census, scope)))


def check_serves_table(text: str, dirs: set[str]) -> list[str]:
    """§3.1 is hand-owned prose, so the gate checks its KEYS, not its words.

    The point of splitting the census in two (: "split the row rather
    than regenerating prose") is that `supplies / serves` is a judgement. But an
    unchecked hand table is how §3 drifted in the first place, so the dir set
    must still match: a new dir cannot land without someone writing what it
    serves, and a deleted one cannot linger.
    """
    # `#{1,6}` not `#{2,3}`: a `#### ` sub-heading would not have closed the
    # section, so any later `| `dir` |` row anywhere below it counted as a
    # serves entry.
    m = re.search(r"^### 3\.1\b.*?(?=^#{1,6} |\Z)", text, re.S | re.M)
    if not m:
        return ["docs/09 §3.1 (the hand-owned serves table) is missing"]
    listed = {mm.group(1) for ln in table_rows(m.group(0))
              if (mm := re.match(r"\s*\|\s*`([a-z][a-z0-9_]*)`\s*\|", ln))}
    problems = []
    for d in sorted(dirs - listed):
        problems.append(f"docs/09 §3.1: `{d}` is in the census but has no "
                        f"'supplies / serves' entry")
    for d in sorted(listed - dirs):
        problems.append(f"docs/09 §3.1: `{d}` has a 'supplies / serves' entry "
                        f"but is not a dir under engine/features/")
    return problems


# --------------------------------------------------------------------------
# the demand-half lint -- reads prose, never writes it
# --------------------------------------------------------------------------
#
# Three of the four recorded drift instances were a hand-written sentence claiming
# a dir did not exist while it sat in the tree:
#
#   docs/09 §1.2  a feature: supplied-by "--", status "not built"
#   docs/09 §5    the same feature, still listed as an unbuilt prediction
#   a status table  collider row left at "not started" after it landed
#
# All of these are the same checkable proposition, and none of them live in text
# this generator may emit. So the lint asserts the proposition instead.

# The "this does not exist" vocabulary. A review measured the original three
# forms (not built / not started / ❌) against a 27-form sweep and found
# `unimplemented`, `TODO`, `pending`, `not yet built`, `unbuilt` and
# `no supplier exists` all silent. They are covered here.
#
# Bare `missing` is deliberately NOT in this set: docs/09 §1.1 and §1.2 both
# carry a "missing classes" COLUMN whose legitimate contents would fire on
# every row. `missing` only reads as a not-built claim next to a supplier
# ("supplier missing", "no supplier"), which the `no\s+supplier` alternative
# already covers.
NOT_BUILT = re.compile(
    r"not\s+(?:yet\s+)?(?:built|started|implemented|done|shipped|written)"
    r"|\bunimplemented\b|\bunbuilt\b|\bTODO\b|\bpending\b"
    r"|no\s+supplier|nothing\s+supplies\s+it"
    r"|&#10060;|❌", re.I)

# The row's subject: the first cell, bold or NOT. A review: requiring `**bold**`
# excluded three of five real rows on typography alone.
TERM = re.compile(r"^\s*\|\s*(?:~~)?\s*(?:\*\*)?(.+?)(?:\*\*)?\s*(?:~~)?\s*\|", re.M)
BACKTICKED = re.compile(r"`([a-z][a-z0-9_]*)`")
FEATURE_PATH = re.compile(r"`engine/features/([a-z][a-z0-9_]*)`")

# A struck row is exempt only when the strike is PAIRED with an affirmative
# marker. A bare `~~` exemption silences a live claim — wrapping col_map's
# subject in `~~` and adding "NOT BUILT" was green. All twelve real
# struck spans in the demand docs carry one of these, so tightening costs
# nothing and closes the hole.
#
# AFFIRMED is deliberately CASE-SENSITIVE. Written with re.I it matched the
# lower-case "built" inside "not built", so the exemption fired on exactly the
# rows it exists to exclude and the plant for it stayed green. The real markers
# are shouted -- `**BUILT 2026-07-28**`, `SHIPPED`, ✅ -- and the phrase they
# must be told apart from is not.
STRUCK = re.compile(r"^\s*\|\s*~~")
AFFIRMED = re.compile(r"\bBUILT\b|\bSHIPPED\b|\bDONE\b|\bCLOSED\b"
                      r"|\bDELIVERED\b|&#9989;|✅")

# The demand tables this lint is aimed at, identified by their HEADER rather
# than by section number, so renumbering cannot silently drop one. §1.1 and
# §1.2 do not share a column ORDER (§1.2 interposes `provenance`), which is why
# the supplier column is resolved by NAME and never by position.
DEMAND_HEADERS = ("demand", "collider")
SUPPLIER_COLUMNS = ("supplied by", "state")


def normalise_term(term: str) -> str:
    """A demand term as it would be spelled if it were a dir name.

    'col_map' -> col_map; '**VWF**' -> vwf; 'input (1 pad)' -> input.
    Returns '' when the term cannot name a dir (e.g. 'BG->OBJ capture').
    """
    t = re.sub(r"\(.*?\)", "", term)
    t = t.replace("~~", "").replace("`", "").replace("*", "").strip()
    t = t.lower().replace(" ", "_").replace("-", "_")
    return t if re.fullmatch(r"[a-z][a-z0-9_]*", t or "") else ""


def row_cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def is_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|[\s|:-]+\|?\s*$", line))


def table_rows(text: str) -> list[str]:
    return [ln for ln in text.splitlines()
            if ln.lstrip().startswith("|") and not is_separator(ln)]


def supplier_column(header: str) -> int | None:
    """Index of the column naming the dir that SUPPLIES the row's demand."""
    for i, c in enumerate(row_cells(header)):
        if c.strip().lower().strip("*`") in SUPPLIER_COLUMNS:
            return i
    return None


def row_dirs(line: str, dirs: set[str], supplier_col: int | None) -> set[str]:
    """Every existing dir this row can be resolved to.

    TWO routes, because the subject term alone reaches almost nothing —
    a review measured 5 of 30 rows, the five whose demand term happens to be
    spelled like its dir (`VWF`, `col_map`, `input`). `GRAD`, `STREAM`, `SPR`,
    `TXT`, `M7`, `SPLIT`, `fades` and `scene flow` are all named differently
    from the dir that supplies them.

      1. the SUBJECT cell, if it spells a dir;
      2. the SUPPLIER cell -- the map from demand term to dir is already
         written in the row, in the column that says which dir supplies it.

    Route 2 is restricted to the supplier column on purpose. Scanning the whole
    row would resolve `| **OBJ-HUD** | -- | ... on top of `oam_sprites` ... |
    not built |` through a dir it merely mentions, and OBJ-HUD is genuinely
    not built -- a false red on a true sentence.
    """
    cells = row_cells(line)
    found = set()
    if cells:
        t = normalise_term(cells[0])
        if t in dirs:
            found.add(t)
    if supplier_col is not None and supplier_col < len(cells):
        cell = cells[supplier_col]
        found |= {d for d in BACKTICKED.findall(cell) if d in dirs}
        found |= {d for d in FEATURE_PATH.findall(cell) if d in dirs}
    return found


def exempt_as_history(line: str) -> bool:
    """docs/09 deliberately KEEPS checked predictions, struck through.

    Those must not read as live claims or the gate punishes the record-keeping
    it wants. But the strike alone is too broad: it silences anything.
    Require the affirmative marker every genuine history row already carries.
    """
    return bool(STRUCK.match(line) and AFFIRMED.search(line))


def iter_tables(text: str):
    """Yield (header_line_or_None, supplier_col, [(line_no, row), ...]).

    A table is a run of `|`-leading lines. When the second line is a
    `|---|---|` separator the first is a header, and the supplier column is
    resolved from it BY NAME -- §1.1 and §1.2 order their columns differently,
    so an index would read `provenance` as the supplier in one of them.
    """
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        start = i
        has_header = (start + 1 < len(lines) and is_separator(lines[start + 1]))
        header = lines[start] if has_header else None
        col = supplier_column(header) if has_header else None
        i = start + 2 if has_header else start
        body = []
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            if not is_separator(lines[i]):
                body.append((i + 1, lines[i]))
            i += 1
        yield header, col, body


def walk_tables(text: str):
    """Every table row as (line_no, line, supplier_col)."""
    for _, col, body in iter_tables(text):
        for n, ln in body:
            yield n, ln, col


def lint_text(name: str, text: str, dirs: set[str]) -> list[str]:
    """Contradictions between one document's prose and the tree.

    L1  a backticked `engine/features/X` path must name a dir that exists
    L2  a table row that RESOLVES to an existing dir -- through its subject
        term or through its supplier column -- must not also assert that the
        thing is not built
    L3  no live row in `09` §5 ("what each UNBUILT feature would need") may
        resolve to a dir that exists

    Takes text rather than a path so the historical drift can be replayed
    against today's tree -- see tests/test_register.py, which feeds the four
    the recorded instances back through this function from git history.

    KNOWN LIMIT, deliberately not closed here. A row whose supplier cell is
    `--` AND whose demand term is not spelled like a dir (`GRAD` unbuilt with
    no supplier named; `OBJ-HUD`; `AUD`) cannot be resolved by either route,
    so a false "not built" on one of those stays green. The examples are LIVE
    and a term leaves the list when a dir spelled like it lands -- `POOL` did
    on 2026-08-08, `SAVE` had done so at C2 without anyone noticing, because
    the fixture that guards this limit happened to use the other one. Closing
    it needs a declared demand-term -> dir mapping on `feature.toml` (a
    `supplies` field mirroring `role`), which is its own work item. `make
    register` prints the reach so the residual is visible rather than assumed
    away -- see reach_report().
    """
    problems: list[str] = []

    # L1 -- cited paths must resolve.
    for m in FEATURE_PATH.finditer(text):
        if m.group(1) not in dirs:
            problems.append(
                f"{name}:{text[:m.start()].count(chr(10)) + 1}: cites "
                f"`engine/features/{m.group(1)}` which does not exist")

    # L2 -- "not built" about a dir that is right there.
    for i, ln, col in walk_tables(text):
        if exempt_as_history(ln):
            continue
        hits = row_dirs(ln, dirs, col)
        if hits and NOT_BUILT.search(ln):
            subject = row_cells(ln)[0] if row_cells(ln) else "?"
            problems.append(
                f"{name}:{i}: row '{subject}' says not built/not started, but "
                + " and ".join(f"engine/features/{d}/" for d in sorted(hits))
                + " exists in the tree")

    # L3 -- section-scoped. docs/09 §5 is "What each unbuilt feature would
    # need", so a live row there naming an existing dir contradicts the
    # heading without ever using the words L2 looks for. That is precisely
    # how col_map's §5 row survived 78fa13b's first pass.
    for m in re.finditer(r"^## 5\..*?(?=^## |\Z)", text, re.S | re.M):
        base = text[:m.start()].count("\n")
        for i, ln, col in walk_tables(m.group(0)):
            if exempt_as_history(ln):
                continue
            hits = row_dirs(ln, dirs, col)
            if hits:
                subject = row_cells(ln)[0] if row_cells(ln) else "?"
                problems.append(
                    f"{name}:{base + i}: §5 lists '{subject}' among the "
                    + "UNBUILT, but "
                    + " and ".join(f"engine/features/{d}/" for d in sorted(hits))
                    + " exists in the tree")
    return problems


def lint_demand_half(dirs: set[str]) -> list[str]:
    return [p for path in DEMAND_DOCS if path.exists()
            for p in lint_text(path.name, path.read_text(), dirs)]


def reach_report(dirs: set[str]) -> tuple[int, int]:
    """(rows the L2 rule can resolve, rows in the demand tables).

    A gate's summary line should state what it CHECKED, not just how much it
    found, and this lint is the case for the rule: it was described in five
    places as refusing any prose claiming a dir
    does not exist while it does, and reached 5 of 30 rows. Printing the ratio
    makes the next drift between the claim and the mechanism self-evident
    instead of requiring an audit to measure it.
    """
    reached = total = 0
    for path in DEMAND_DOCS:
        if not path.exists():
            continue
        for header, col, body in iter_tables(path.read_text()):
            if header is None:
                continue
            cells = row_cells(header)
            if not cells or cells[0].lower().strip("*` ") not in DEMAND_HEADERS:
                continue
            total += len(body)
            reached += sum(1 for _, ln in body if row_dirs(ln, dirs, col))
    return reached, total


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true",
                   help="fail with a diff if the committed doc has drifted")
    g.add_argument("--write", action="store_true",
                   help="regenerate the generated regions in place")
    args = ap.parse_args(argv)

    try:
        current = REGISTER.read_text()
        fresh = generate(current)
        census, _ = load_tree()
        problems = (check_serves_table(current, set(census))
                    + lint_demand_half(set(census)))
    except RegisterError as e:
        print(f"REGISTER FAILED: {e}", file=sys.stderr)
        return 1

    if args.write:
        if fresh != current:
            REGISTER.write_text(fresh)
            print(f"register: rewrote {REGISTER.relative_to(REPO)}")
        else:
            print("register: already up to date")
        if problems:
            print("\nregister: the demand half still contradicts the tree "
                  "(--write does not touch prose -- fix these by hand):",
                  file=sys.stderr)
            for p in problems:
                print(f"  {p}", file=sys.stderr)
            return 1
        return 0

    failed = False
    if fresh != current:
        failed = True
        diff = difflib.unified_diff(
            current.splitlines(True), fresh.splitlines(True),
            fromfile=f"a/{REGISTER.relative_to(REPO)} (committed)",
            tofile=f"b/{REGISTER.relative_to(REPO)} (generated from the tree)")
        print("REGISTER DRIFT: the committed census disagrees with the tree.\n"
              "Run `make register-write` to regenerate.\n", file=sys.stderr)
        sys.stderr.writelines(diff)
        print("", file=sys.stderr)
    if problems:
        failed = True
        print("REGISTER DRIFT: prose contradicts the tree "
              "(these are hand-owned -- fix them by hand, not with "
              "`make register-write`):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
    if failed:
        return 1

    n = len(census)
    reached, rows = reach_report(set(census))
    if rows == 0:
        # No demand doc in this checkout: the census half still holds, and
        # saying "reached 0/0" would read as a measurement rather than as an
        # absent surface. Omit the ratio instead of reporting a vacuous one.
        print(f"register OK: census matches the tree ({n} dirs); "
              f"no demand surface in this checkout, so the demand lint had "
              f"nothing to reach")
        return 0
    print(f"register OK: census matches the tree ({n} dirs); "
          f"demand lint reached {reached}/{rows} demand rows and found no "
          f"contradiction")
    if reached < rows:
        print(f"  note: {rows - reached} demand row(s) name no existing dir in "
              f"their subject or supplier column, so a false 'not built' on "
              f"them would NOT be caught. See lint_text's KNOWN LIMIT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
