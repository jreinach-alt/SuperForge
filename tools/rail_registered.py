#!/usr/bin/env python3
"""superforge -- a new game rail must be REGISTERED in all eleven places, or it
is half-wired and nothing says so.

WHY THIS EXISTS. Adding a rail under `game/` is not one edit, it is eleven,
and four of them have each been missed at least once across successive rail
waves. The interesting one is silent AND points the wrong way: registering a
rail's map in
`conftest.MAPS` but not in `conftest._SUBDIR_MAP` leaves `_map_of()` --
which keys off the SECOND dict -- falling back to `build/symbol_map.json`,
the TOY map. The rail's own map then goes unchecked for freshness while the
module demands `make toy`, which reads as an unrelated prerequisite problem
rather than "your rail is not registered". A rail's tests can be green
against another game's freshness.

The root of it is that the same fact -- this rail's name -- has to be written
into a dozen unrelated lists, and nothing joins them. An early brief said four
sites; this gate shipped checking six. Measurement then found a rail's name
living in ELEVEN places (two rails went green on the six sites the gate knew
and still tripped over the five it did not), so the gate grew to the derived
census. A TWELFTH arrived with the prerequisite change: `make test` now takes
the rail list as PREREQUISITES, which is what turns "the tree must be
pre-built" from a comment into a fact of the build.

WHY ELEVEN AND NOT TWELVE -- the count changed by DECISION, not by rot. Site 4
used to be `.github/workflows/ci.yml`. On 2026-08-22 the owner retired the
hosted workflow entirely, file and manual-dispatch hatch together: the project
regularly blew through the available Actions usage, a failure there never
reported back into the working session, and repeated failure mail was not
worth what the runs bought. The workflow file was deleted, so the site it was
went with it and every site after it moved down one. `make bare-check` is the
gate of record and there is no hosted alternative in the tree. A reader
counting eleven here and twelve in an older report is looking at that decision,
not at a check somebody quietly dropped -- the disarm guard below still refuses
any run in which fewer than all eleven checks execute.

THE ELEVEN SITES, and what each one being absent costs:

  1. Makefile `.PHONY`                 a stale file named `breaker` in the
                                       tree makes the target a silent no-op
  2. Makefile `gates:` rail list       `make gates` never builds the rail
  3. Makefile `gates:` md5 list        the summary omits the rail's md5, so
                                       the render-verification check has a
                                       hole (a SEPARATE list from 2)
  4. tests/conftest.py `MAPS`          the freshness guard cannot check the
                                       map at all
  5. tests/conftest.py `_SUBDIR_MAP`   the freshness guard checks the WRONG
                                       map (the toy fallback above)
  6. tools/bare_check.sh size list     the LANDING gate never asserts the
                                       rail's ROM links at its pinned size --
                                       a truncated link passes bare-check
  7. tools/bare_check.sh rom_md5 list  build/bare_check.json omits the
                                       rail's md5, so the one artifact the
                                       landing rule cites cannot pin the
                                       rail's binary
  8. tests/test_map_freshness_guard.py the hand-reviewed dict in
     reviewed dict                     `test_the_tree_agrees_with_the_rule`:
                                       missing an entry, the suite goes red
                                       minutes in, in a module the change
                                       never touched, under a name that
                                       mentions neither the rail nor the
                                       site (two rails hit this
                                       independently)
  9. AGENTS.md BUILD-FIRST block       the list that decides whether a cold
                                       tree can run `make test` at all;
                                       missing, an xdist run dies with
                                       INTERNALERROR naming an innocent
                                       pure-Python test
 10. Makefile `determinism:` prereqs   `make determinism MODULE=tests/
                                       test_<rail>.py` dies on a missing
                                       ROM/map instead of running the
                                       module -- the gate's "module list"
                                       IS this prerequisite list — demanded
                                       of every rail whose ROM a
                                       Machine-driving module needs, WHEREVER
                                       in that module the need is written
 11. Makefile `test:` prereqs          `make test` runs against an UNBUILT
                                       rail, and the collection-time
                                       freshness guard refuses. Serially
                                       that names the rail and the fix in
                                       one line; UNDER XDIST the worker
                                       dies and pytest prints
                                       `INTERNALERROR> ... assert not
                                       crashitem` naming an INNOCENT module
                                       -- test_allocator.py, which is pure
                                       Python and passes alone. Site 10's
                                       sibling: 10 keeps ONE module's rail
                                       buildable, 11 keeps ALL of them
                                       buildable, because the suite
                                       collects every module. Found by
                                       review, and reproduced on the base
                                       commit — pre-existing, not
                                       introduced by the rail that
                                       surfaced it

WHAT IS DERIVED VS WHAT IS LISTED. Nothing here is a hardcoded list of rails
or of map subdirectories:

  * the RAILS are the `game/*` dirs that carry a `game.toml`;
  * a rail's MAP DIRECTORY comes from the Makefile's own `allocate.py`
    invocation (`--game game/X ... --out $(BUILD)/y`), variables expanded --
    so this cannot become a second opinion about where a map lives;
  * sites 4 and 5 are demanded only when SOME `tests/test_*.py` actually
    READS that rail's symbol map at COLLECTION TIME, which is the condition
    that makes them load-bearing. Every module is parsed, not just
    `test_<rail>.py`: `microzero`'s map is read by `test_microzero_*.py` and
    `room`'s by `test_room_window` / `test_c2_slice_c` / `test_slice_b_audio`,
    and those rails need the two dicts just as much. The parse follows one
    level through a module-scope helper call, one level through a module-scope
    path constant, and one level through a module-scope `import` of a sibling
    in `tests/` — the shape `test_platformer.py` uses, where the read lives in
    `tests/plf_drive.py`;
  * site 8 is demanded per READER MODULE, and its condition is the freshness
    guard's OWN scanner (`conftest.maps_named_in`), not this file's wider
    derivation above — deliberately: the reviewed dict must equal what that
    scanner sees (`test_the_tree_agrees_with_the_rule` asserts exactly that),
    so demanding an entry the scanner cannot see (e.g. `test_platformer.py`,
    whose read hides in a sibling import) would order an edit the guard's own
    test refuses;
  * site 10 is demanded of every rail whose ROM some `tests/test_*.py`
    needs in order to run under `make determinism MODULE=` — that is, a
    module which DRIVES a `Machine` (imports `vendor/machine.py`) and names
    the rail's ROM or map ANYWHERE in its text — PLUS every rail the
    determinism gate's own `--falsify` plant hardcodes, which `make
    determinism FALSIFY=1` needs for EVERY module. Deliberately NOT the
    collection-time condition sites 4/5/8 use, and here is why:
    those sites are about the FRESHNESS GUARD, where a map nobody reads at
    import time genuinely needs no registering, but site 10 is about the
    ROM being BUILT, which a module needs whether its map read happens at
    collection or inside a test body. Under the old conjunction `microzero`
    — driven by `test_machine.py` and `test_replay_triple.py` and hardcoded
    in the falsify plant — was silently EXEMPT, because its only map read
    is inside a test body (`test_machine.py`'s `:163`); dropping it from
    `determinism:` left the gate green while `make determinism FALSIFY=1`
    would die on the missing ROM. The exempted class was set to GROW, not
    shrink: a lockstep-native module has less reason than a legacy one to
    read a symbol map at collection time. Extra prerequisites (fixture
    targets like `sh2-variants`) are fine; the check is presence of the
    demanded, not absence of others;
  * sites 6, 7 and 9 are asked of EVERY rail, textually — 9 is prose
    (AGENTS.md's build-first `make` block), and is stated as a textual check
    rather than dressed up as anything sharper;
  * site 11 is asked of EVERY rail UNCONDITIONALLY, and deliberately not
    conditioned the way site 10 is. `make test` collects the WHOLE `tests/`
    tree in one process group, so every rail's ROM and map must exist before
    pytest starts — there is no per-module narrowing to derive against. It is
    site 9's executable twin: 9 asks the PROSE list to name the rail so a
    human building a cold tree by hand gets it right, 11 asks the BUILD to
    enforce it so nobody has to. Extra prerequisites (`probes`,
    `sh2-variants`) are fine, same rule as site 10.

`engine/toy` and `vendor/probes/*` are NOT rails and are not asked for any of
this -- they are fixtures with their own targets.

WHAT WAS LOST WITH THE WORKFLOW, stated rather than quietly dropped. Site 4 had
a companion that was NOT a site: a SWEEP over ci.yml's steps, running from the
opposite end. The eleven sites all start from the rail census -- "for each dir
under `game/`, is it named here?" -- and that framing has a structural blind
spot. `svd-nowin` fell straight into it: it builds `build/svd_nowin.sfc` but is
a VARIANT target, not a rail (no `game/svd_nowin/` exists), so when a union's
shape repair went one line too high and moved that step's
`test "$size" -eq 524288` into the FOLLOWING step, no per-rail site was ever
asked about it. Nothing was deleted, the YAML stayed valid, a removed-line scan
saw nothing, and the ROM's size ended up asserted NOWHERE. The sweep started
from ci.yml's own steps instead: any step that ran make and stat'd a
`build/*.sfc` had to carry a `test "$size" -eq N` after that stat.

With the workflow gone the sweep has nothing to read, so it was removed with
the site. THE FAILURE MODE IT COVERED DOES NOT GO WITH IT -- it moves. The
remaining measurement lists are `tools/bare_check.sh`'s size list, its rom_md5
tuple and the Makefile `gates:` md5 loop, and ALL THREE are rail-scoped, while
`make gates`'s `run <target>;` list is not: it builds variant and control
targets that no `game/` dir backs. Eight of those ROMs -- svd_nowin,
shd_autodemo, shp_autodemo, rs_probe, sit_origin, sit_mistime, shg_nograd,
shg_origin -- were measured ONLY in ci.yml, and as of this change their size is
asserted nowhere and their bytes are pinned nowhere. No check here covers them,
and none was added in passing: closing it means deciding which list is the
authority (`make gates`'s build list against `bare_check.sh`'s measured list is
the same shape the sweep had), and that is a decision, not a cleanup.

DELIBERATE LIMIT, stated because a gate believed stronger than it is, is the
wound CLAUDE.md rule 6 already carries: this checks that a rail is NAMED at
each site, not that the site's recipe is correct. A rail listed in `.PHONY`
does not prove its recipe builds anything, and a rail named in the `gates:`
list does not prove its build passes. The build gates prove that; this one
proves the wiring exists. With the sweep gone, NO arm of this gate reads a
recipe's content any more — it is now a naming check end to end.

USAGE
    tools/rail_registered.py            exit 1 + a per-rail, per-site report
    tools/rail_registered.py --list     print the derived rail -> map table
                                        (`make rail-registered`)
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"
GAMES = REPO / "game"

sys.path.insert(0, str(REPO / "tests"))


class RailError(Exception):
    """The tree itself is inconsistent — not a missing registration."""


# --------------------------------------------------------------------------
# the Makefile: variables, the allocator invocations, .PHONY, the gates lists
# --------------------------------------------------------------------------

def _logical_lines(text: str) -> list[str]:
    """Join backslash continuations — every list here is written across them."""
    return re.sub(r"\\\n\s*", " ", text).splitlines()


def make_vars(lines: list[str]) -> dict[str, str]:
    """`NAME := VALUE` / `NAME = VALUE`, with `$(X)` expanded transitively."""
    raw: dict[str, str] = {}
    for ln in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*[:?]?=\s*(.*?)\s*$", ln)
        if m:
            raw.setdefault(m.group(1), m.group(2))

    def expand(v: str, depth: int = 0) -> str:
        if depth > 8:
            return v
        return re.sub(r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]",
                      lambda m: expand(raw.get(m.group(1), ""), depth + 1), v)

    return {k: expand(v) for k, v in raw.items()}


def allocator_invocations(lines: list[str], vars_: dict[str, str]
                          ) -> list[tuple[list[str], str, str]]:
    """Every `allocate.py` call in the Makefile as (argv-minus-out, game, out).

    argv-minus-out is kept in source order because `conftest.MAPS` claims to
    carry "the same invocation the Makefile recipe uses" — a claim worth
    checking rather than trusting.
    """
    def expand(tok: str) -> str:
        return re.sub(r"\$[({]([A-Za-z_][A-Za-z0-9_]*)[)}]",
                      lambda m: vars_.get(m.group(1), ""), tok)

    out = []
    for ln in lines:
        if "allocate.py" not in ln:
            continue
        toks = [expand(t) for t in ln.split()]
        i = toks.index([t for t in toks if t.endswith("allocate.py")][0])
        argv = toks[i + 1:]
        game = outdir = None
        trimmed, skip = [], False
        for j, t in enumerate(argv):
            if t == "--out":
                outdir = argv[j + 1] if j + 1 < len(argv) else None
                skip = True
                continue
            if skip:
                skip = False
                continue
            if t.startswith(">") or t.startswith("2>"):
                break
            if t == "--game":
                game = argv[j + 1] if j + 1 < len(argv) else None
            trimmed.append(t)
        if game and outdir:
            out.append((trimmed, game, outdir))
    return out


def phony_targets(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for ln in lines:
        if ln.startswith(".PHONY:"):
            names |= set(ln.split(":", 1)[1].split())
    return names


def gates_recipe(text: str) -> str:
    """The body of the `gates:` target — both of its lists live in here."""
    m = re.search(r"^gates:.*?(?=^\S)", text, re.M | re.S)
    if not m:
        raise RailError("Makefile has no `gates:` target")
    return m.group(0)


def gates_rail_list(recipe: str) -> set[str]:
    """The `run <target>;` sequence — what `make gates` actually executes."""
    return set(re.findall(r"\brun\s+([A-Za-z0-9_.-]+)\s*;", recipe))


def gates_md5_list(recipe: str) -> set[str]:
    """The `for rom in ...; do` list — a SEPARATE list from the one above."""
    m = re.search(r"for\s+rom\s+in\s+([^;]+);", recipe)
    if not m:
        raise RailError("Makefile `gates:` has no `for rom in ...` md5 loop")
    return set(m.group(1).split())


# --------------------------------------------------------------------------
# tools/bare_check.sh — the landing gate's two rail lists (sites 6 + 7)
# --------------------------------------------------------------------------

BARE = REPO / "tools" / "bare_check.sh"


def bare_check_sizes(text: str) -> set[str]:
    """The `for spec in rom:size ...; do` size-assert list, names only."""
    joined = re.sub(r"\\\n\s*", " ", text)
    m = re.search(r"for\s+spec\s+in\s+([^;]+);\s*do", joined)
    if not m:
        raise RailError("tools/bare_check.sh has no `for spec in rom:size` "
                        "size-assert loop")
    return {tok.split(":")[0] for tok in m.group(1).split() if ":" in tok}


def bare_check_md5s(text: str) -> set[str]:
    """The embedded-Python `for rom in ("a", "b", ...)` md5 tuple."""
    m = re.search(r"for\s+rom\s+in\s+\((.*?)\)\s*:", text, re.S)
    if not m:
        raise RailError("tools/bare_check.sh has no `for rom in (...)` "
                        "rom_md5 tuple")
    return set(re.findall(r'"([^"]+)"', m.group(1)))


# --------------------------------------------------------------------------
# tests/test_map_freshness_guard.py — the hand-reviewed dict (site 8)
# --------------------------------------------------------------------------

GUARD_TEST = REPO / "tests" / "test_map_freshness_guard.py"


def freshness_reviewed_dict() -> dict:
    """The dict literal `test_the_tree_agrees_with_the_rule` compares against.

    Read as DATA via ast so the check sees exactly what the assert holds —
    not a regex over comments, which the file is full of.
    """
    if not GUARD_TEST.exists():
        raise RailError("tests/test_map_freshness_guard.py is missing")
    tree = ast.parse(GUARD_TEST.read_text())
    for node in tree.body:
        if (isinstance(node, ast.FunctionDef)
                and node.name == "test_the_tree_agrees_with_the_rule"):
            for st in ast.walk(node):
                if isinstance(st, ast.Assert) \
                        and isinstance(st.test, ast.Compare):
                    for comp in st.test.comparators:
                        if isinstance(comp, ast.Dict):
                            return ast.literal_eval(comp)
    raise RailError(
        "test_map_freshness_guard.py: the reviewed dict "
        "(test_the_tree_agrees_with_the_rule's `covered == {...}` literal) "
        "was not found")


# --------------------------------------------------------------------------
# AGENTS.md — the BUILD-FIRST make block (site 9, a textual prose check)
# --------------------------------------------------------------------------

AGENTS = REPO / "AGENTS.md"


def agents_build_first(text: str) -> set[str]:
    """The `make ...` target list under the BUILD FIRST marker.

    The block is a comment inside AGENTS.md's build-and-test fence: a
    `#   make a b c \\` line plus `#        d e \\` continuations. Collect
    the tokens; `make` itself is dropped.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if "BUILD FIRST" in ln),
                 None)
    if start is None:
        raise RailError("AGENTS.md has no BUILD FIRST block")
    tokens: set[str] = set()
    in_cmd = False
    for ln in lines[start:start + 40]:
        body = ln.strip().lstrip("#").strip()
        if not in_cmd:
            if body.startswith("make "):
                in_cmd = True
            else:
                continue
        cont = body.endswith("\\")
        tokens |= set(body.rstrip("\\").split())
        if not cont:
            break
    if not in_cmd:
        raise RailError("AGENTS.md's BUILD FIRST block has no `make ...` "
                        "command within 40 lines of the marker")
    tokens.discard("make")
    return tokens


# --------------------------------------------------------------------------
# Makefile `determinism:` prerequisites (site 10)
# --------------------------------------------------------------------------

def determinism_prereqs(lines: list[str]) -> set[str]:
    for ln in lines:
        m = re.match(r"^determinism:\s*(.*)$", ln)
        if m:
            return set(m.group(1).split())
    raise RailError("Makefile has no `determinism:` target")


# --------------------------------------------------------------------------
# Makefile `test:` prerequisites (site 11)
# --------------------------------------------------------------------------

def test_prereqs(lines: list[str]) -> set[str]:
    """The NORMAL prerequisites of `test:` — the list that pre-builds the tree.

    Everything from `|` rightward is dropped: those are ORDER-ONLY
    prerequisites (`| $(BUILD)`), which make treats as "must exist" and not
    as "must be up to date". A rail parked there would look registered and
    build nothing, so counting it would be a fails-open read of the site this
    check exists for.
    """
    for ln in lines:
        m = re.match(r"^test:\s*(.*)$", ln)
        if m:
            return set(m.group(1).split("|", 1)[0].split())
    raise RailError("Makefile has no `test:` target")


_MACHINE_RE = re.compile(r"^\s*(from\s+machine\s+import\b|import\s+machine\b)",
                         re.M)

DET_GATE = REPO / "tools" / "determinism_gate.py"


def _module_string_constants(text: str) -> set[str]:
    """Every string constant ANYWHERE in a module — not just module scope.

    Site 10's derivation deliberately looks at the whole module: a `Machine`
    built inside a fixture or a test body needs its ROM built exactly as much
    as one bound at import time does.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _names_rom(text: str, rail: str) -> bool:
    """Does this source name `<rail>.sfc`?

    Textual over the raw source rather than over string constants, because
    the shapes in this suite are several — `SUPERFORGE / "build" / "x.sfc"`,
    the literal `"build/x.sfc"`, and (in the determinism gate's `--falsify`
    PLANT) a whole test module embedded inside one f-string, where the path
    is not a string constant of the OUTER module at all. The `.sfc` suffix
    keeps the match tight: `platformer.sfc` does not occur inside
    `platformer_stream.sfc`. A rail named only in a comment would be
    over-demanded, which errs toward "one prerequisite too many" — the safe
    direction, and the opposite of the recorded hole.
    """
    return f"{rail}.sfc" in text


def _names_map(strings: set[str], subdir: str) -> bool:
    return "symbol_map.json" in strings and subdir in strings


_MODULE_TEXT_CACHE: dict[str, str] | None = None


def _test_module_texts() -> dict[str, str]:
    global _MODULE_TEXT_CACHE
    if _MODULE_TEXT_CACHE is None:
        _MODULE_TEXT_CACHE = {
            mod.name: mod.read_text()
            for mod in sorted((REPO / "tests").glob("test_*.py"))}
    return _MODULE_TEXT_CACHE


def determinism_demanding_modules(rail: str, subdir: str) -> list[str]:
    """Modules whose `make determinism MODULE=` run needs `<rail>.sfc` built.

    A module qualifies when it DRIVES a Machine and names the rail's ROM or
    its symbol map anywhere in the module — not only at collection time.
    See the site-10 bullet in this file's docstring for why the two
    conditions are decoupled.
    """
    return [name for name, text in sorted(_test_module_texts().items())
            if _MACHINE_RE.search(text)
            and (_names_rom(text, rail)
                 or _names_map(_module_string_constants(text), subdir))]


def falsify_plant_rails(all_rails: list[str]) -> list[str]:
    """Rails hardcoded in the determinism gate's OWN `--falsify` plant.

    `make determinism FALSIFY=1` appends that plant to whichever module it
    was pointed at, so the ROM the plant names is a prerequisite of the
    target for EVERY module, not just its own rail's. Textual by necessity:
    the plant is source code inside an f-string.
    """
    if not DET_GATE.exists():
        raise RailError("tools/determinism_gate.py is missing")
    text = DET_GATE.read_text()
    return [r for r in all_rails if _names_rom(text, r)]


def guard_visible_readers(rel_map: str) -> list[str]:
    """Modules whose collection-time read of rel_map the freshness guard's
    OWN scanner sees — site 8's demand condition (see the docstring)."""
    import conftest                                    # noqa: PLC0415
    return [m.name for m in sorted((REPO / "tests").glob("test_*.py"))
            if rel_map in conftest.maps_named_in(m.read_text())]


# --------------------------------------------------------------------------
# tests/conftest.py — the two dicts, read as data, not re-implemented
# --------------------------------------------------------------------------

def conftest_registries() -> tuple[dict, dict]:
    import conftest                                    # noqa: PLC0415
    return conftest.MAPS, conftest._SUBDIR_MAP


# --------------------------------------------------------------------------
# does `tests/test_<rail>.py` read a symbol map at COLLECTION time?
# --------------------------------------------------------------------------
#
# The parser primitives are conftest's own (`_strings_and_names`, `_READS`,
# `_called_names`) so the two cannot disagree about what a read looks like.
# What is NOT reused is `_map_of`, because `_map_of` consults `_SUBDIR_MAP` —
# one of the two dicts under test here — and a gate that resolves its own
# question through the registry it is checking answers "registered" every
# time. So this collects the raw path components instead.

def _read_strings(stmt, bindings) -> set:
    import conftest                                    # noqa: PLC0415
    strings, names = conftest._strings_and_names(stmt)
    if not (names & conftest._READS):
        return set()
    if "symbol_map.json" in strings:
        return strings
    acc = set()
    for n, s in bindings.items():
        if n in names:
            acc |= s
    return acc


def collection_time_map_strings(text: str, sibling_source=None) -> set:
    """Every string constant in a module-scope statement that READS a map.

    Three shapes, all real in this suite: the read written at module scope; a
    module-scope call to a module-level helper that reads; and a read through
    a module-level path constant. Plus one this file adds and conftest's own
    guard does not follow — a module-scope `import` of a sibling in `tests/`
    that does the read (`test_platformer.py` -> `tests/plf_drive.py`), which
    is still a COLLECTION-time read and still needs the map registered.
    """
    import conftest                                    # noqa: PLC0415
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()

    bindings = {}
    for st in tree.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 \
                and isinstance(st.targets[0], ast.Name):
            strings, names = conftest._strings_and_names(st)
            if "symbol_map.json" in strings and not (names & conftest._READS):
                bindings[st.targets[0].id] = strings

    helpers = {st.name: _read_strings(st, bindings) for st in tree.body
               if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))}

    found = set()
    for st in tree.body:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef)):
            continue
        found |= _read_strings(st, bindings)
        for fn in conftest._called_names(st):
            found |= helpers.get(fn, set())
        if sibling_source is not None and isinstance(st, (ast.Import,
                                                          ast.ImportFrom)):
            mods = ([a.name for a in st.names] if isinstance(st, ast.Import)
                    else [st.module or ""])
            for mod in mods:
                src = sibling_source(mod.split(".")[0])
                if src:
                    found |= collection_time_map_strings(src)
    return found


def _sibling_source(name: str):
    p = REPO / "tests" / f"{name}.py"
    return p.read_text() if p.exists() and name != "conftest" else None


_READER_CACHE = None


def collection_time_readers(subdir: str) -> list[str]:
    """Test modules that read `build/<subdir>/symbol_map.json` at collection.

    Every `tests/test_*.py`, not just `tests/test_<rail>.py`: `microzero`'s
    map is read by `test_microzero_*.py` and `room`'s by `test_room_window`
    / `test_c2_slice_c` / `test_slice_b_audio`, and those rails need sites 5
    and 6 just as much as a rail whose module happens to share its name. The
    module name is a convention, the READ is the condition.
    """
    global _READER_CACHE
    if _READER_CACHE is None:
        _READER_CACHE = {
            mod.name: collection_time_map_strings(
                mod.read_text(), sibling_source=_sibling_source)
            for mod in sorted((REPO / "tests").glob("test_*.py"))}
    return [name for name, strings in _READER_CACHE.items()
            if "symbol_map.json" in strings and subdir in strings]


# --------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------

def rails() -> list[str]:
    if not GAMES.is_dir():
        raise RailError("no game/ directory")
    return sorted(d.name for d in GAMES.iterdir()
                  if d.is_dir() and (d / "game.toml").exists())


def rail_maps() -> dict[str, tuple[str, list[str]]]:
    """rail -> (map path relative to the repo, the Makefile's argv-minus-out).

    Derived from the Makefile, so `conftest.MAPS` is checked against the
    build's own opinion rather than against a copy of it.
    """
    lines = _logical_lines(MAKEFILE.read_text())
    vars_ = make_vars(lines)
    out = {}
    for argv, game, outdir in allocator_invocations(lines, vars_):
        if not game.startswith("game/"):
            continue
        rail = game.split("/", 1)[1]
        out[rail] = (f"{outdir.rstrip('/')}/symbol_map.json", argv)
    return out


SELF_TARGET = "rail-registered"


def self_registration_problems(gates_rails: set[str]) -> list[str]:
    """The gate about registration must itself be registered.

    Awkward, and worth saying so plainly rather than skipping: a gate cannot
    detect its own absence from the runner that would have run it. Delete
    `run rail-registered;` from `make gates` and `make gates` simply stops
    calling this, and nothing here executes to complain.

    THIS GOT WEAKER when the hosted workflow was retired (2026-08-22). While
    ci.yml existed there were TWO runners, so the check caught the asymmetric
    half — present in one list, missing from the other — on whichever surface
    still ran the gate. There is one runner now (`make gates`, which
    `make bare-check` runs inside the clone), so the only surfaces that reach
    this at all are a direct `make rail-registered` and
    `pytest tests/test_rail_registered.py`. What remains is worth keeping: it
    still fires when someone drops `run rail-registered;` from `make gates`
    and then runs the gate by hand or through the suite. What is gone is the
    property that ANY runner could catch the other's omission.
    """
    problems = []
    if SELF_TARGET not in gates_rails:
        problems.append(
            f"{SELF_TARGET}: absent from the Makefile `gates:` rail list. "
            f"The gate that checks registration is not registered.")
    return problems


def check() -> tuple[list[str], list[str], set]:
    """Return (problems, notes, evaluated-site-numbers).

    Empty problems == every rail is registered. `evaluated` carries the
    site numbers whose check logic actually RAN, so the summary can print
    a count that goes down if a check is deleted — a disarmed pass must
    read as disarmed, not print "all sites" from a constant.
    """
    mk_text = MAKEFILE.read_text()
    lines = _logical_lines(mk_text)
    phony = phony_targets(lines)
    recipe = gates_recipe(mk_text)
    gates_rails = gates_rail_list(recipe)
    gates_md5 = gates_md5_list(recipe)
    MAPS, SUBDIR = conftest_registries()
    maps = rail_maps()
    if not BARE.exists():
        raise RailError("tools/bare_check.sh is missing")
    bare_text = BARE.read_text()
    bare_sizes = bare_check_sizes(bare_text)
    bare_md5 = bare_check_md5s(bare_text)
    reviewed = freshness_reviewed_dict()
    if not AGENTS.exists():
        raise RailError("AGENTS.md is missing")
    build_first = agents_build_first(AGENTS.read_text())
    det_prereqs = determinism_prereqs(lines)
    suite_prereqs = test_prereqs(lines)
    plant_rails = falsify_plant_rails(rails())

    problems: list[str] = self_registration_problems(gates_rails)
    notes: list[str] = []
    evaluated: set = set()

    for rail in rails():
        if rail not in maps:
            problems.append(
                f"{rail}: site 0/11 -- the Makefile has no `allocate.py "
                f"--game game/{rail} ... --out ...` recipe, so this rail has "
                f"no map and none of the other sites can be checked")
            continue
        rel_map, mk_argv = maps[rail]

        evaluated.add(1)
        if rail not in phony:
            problems.append(
                f"{rail}: site 1/11 -- absent from the Makefile's `.PHONY` "
                f"list. A stale file named `{rail}` makes the target a "
                f"silent no-op.")
        evaluated.add(2)
        if rail not in gates_rails:
            problems.append(
                f"{rail}: site 2/11 -- absent from the `gates:` rail list "
                f"(the `run {rail};` sequence). `make gates` never builds it.")
        evaluated.add(3)
        if rail not in gates_md5:
            problems.append(
                f"{rail}: site 3/11 -- absent from the `gates:` md5 list (the "
                f"`for rom in ...` loop -- a SEPARATE list from site 2). The "
                f"summary omits its md5, so the render check has a hole.")

        evaluated.add(6)
        if rail not in bare_sizes:
            problems.append(
                f"{rail}: site 6/11 -- absent from tools/bare_check.sh's "
                f"size-assert list (the `for spec in rom:size ...` loop). "
                f"The LANDING gate never checks the rail's ROM links at its "
                f"pinned size -- a truncated link passes bare-check.")
        evaluated.add(7)
        if rail not in bare_md5:
            problems.append(
                f"{rail}: site 7/11 -- absent from tools/bare_check.sh's "
                f"rom_md5 list (the embedded `for rom in (...)` tuple). "
                f"build/bare_check.json omits the rail's md5, so the one "
                f"artifact the landing rule cites cannot pin its binary.")
        evaluated.add(9)
        if rail not in build_first:
            problems.append(
                f"{rail}: site 9/11 -- absent from AGENTS.md's BUILD-FIRST "
                f"`make` block. That list decides whether a cold tree can "
                f"run the full suite at all: under xdist the missing ROM "
                f"surfaces as INTERNALERROR naming an innocent pure-Python "
                f"test (AGENTS.md's own paragraph; spot check M-3).")
        evaluated.add(11)
        if rail not in suite_prereqs:
            problems.append(
                f"{rail}: site 11/11 -- absent from the Makefile `test:` "
                f"prerequisite list, so `make test` can run against an "
                f"UNBUILT {rail}. The suite collects EVERY module, so the "
                f"collection-time freshness guard refuses; serially that "
                f"names the rail and the fix, but under xdist the worker "
                f"dies and pytest prints `INTERNALERROR> ... assert not "
                f"crashitem` naming an INNOCENT module. Site 9 asks "
                f"AGENTS.md's prose to carry this list; "
                f"this site asks the build to enforce it.")

        subdir = Path(rel_map).parent.name
        readers = collection_time_readers(subdir)

        # The module list IS the prerequisite list, and this demand is not
        # conditioned on a collection-time map read: the ROM must be BUILT
        # either way.
        evaluated.add(10)
        drivers = determinism_demanding_modules(rail, subdir)
        in_plant = rail in plant_rails
        if (drivers or in_plant) and rail not in det_prereqs:
            if drivers:
                why = (f"{', '.join(drivers)} drive(s) a Machine and name(s) "
                       f"its ROM/map. `make determinism MODULE=tests/"
                       f"{drivers[0]}` would die on a missing ROM/map "
                       f"instead of running the module")
            else:
                why = ("tools/determinism_gate.py's own `--falsify` plant "
                       "hardcodes its ROM, so `make determinism FALSIFY=1` "
                       "would die on it for EVERY module")
            problems.append(
                f"{rail}: site 10/11 -- absent from the Makefile "
                f"`determinism:` prerequisite list, but {why}.")

        evaluated |= {4, 5, 8}
        if not readers:
            notes.append(
                f"{rail}: sites 4+5+8 not required -- no test module reads "
                f"`{subdir}/symbol_map.json` at collection time "
                f"(map {rel_map})")
            continue

        if rel_map not in MAPS:
            problems.append(
                f"{rail}: site 4/11 -- `{rel_map}` is absent from "
                f"tests/conftest.py MAPS, but {', '.join(readers)} read(s) it "
                f"at COLLECTION time. The freshness guard cannot check it.")
        else:
            target, argv = MAPS[rel_map]
            if target != rail:
                problems.append(
                    f"{rail}: site 4/11 -- conftest.MAPS['{rel_map}'] names "
                    f"make target '{target}', not '{rail}'. The guard's "
                    f"'minimal fix' line would tell a reader to run the "
                    f"wrong target.")
            if list(argv) != list(mk_argv):
                problems.append(
                    f"{rail}: site 4/11 -- conftest.MAPS['{rel_map}'] argv "
                    f"{list(argv)} is not the Makefile's invocation "
                    f"{list(mk_argv)}. The guard would re-emit the map a "
                    f"different way than the build does, so 'STALE' would "
                    f"stop meaning what it says.")

        if subdir not in SUBDIR:
            problems.append(
                f"{rail}: site 5/11 -- '{subdir}' is absent from "
                f"tests/conftest.py _SUBDIR_MAP. THIS ONE IS SILENT: "
                f"`_map_of()` keys off _SUBDIR_MAP, so it falls back to "
                f"build/symbol_map.json (the TOY map) -- "
                f"{', '.join(readers)} would be checked for freshness "
                f"against another game, and would demand `make toy`, which "
                f"reads as an unrelated prerequisite problem.")
        elif SUBDIR[subdir] != rel_map:
            problems.append(
                f"{rail}: site 5/11 -- _SUBDIR_MAP['{subdir}'] is "
                f"'{SUBDIR[subdir]}', not '{rel_map}'.")

        for module in guard_visible_readers(rel_map):
            entry = reviewed.get(module)
            if entry is None or rel_map not in entry:
                problems.append(
                    f"{rail}: site 8/11 -- test_map_freshness_guard.py's "
                    f"reviewed dict has no entry mapping {module} -> "
                    f"{rel_map}, but the guard's own scanner "
                    f"(conftest.maps_named_in) sees that module read it at "
                    f"collection time. test_the_tree_agrees_with_the_rule "
                    f"goes red minutes into a full suite, in a module the "
                    f"port never touched.")

    return problems, notes, evaluated


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true",
                    help="print the derived rail -> map table and exit 0")
    args = ap.parse_args(argv)

    try:
        if args.list:
            maps = rail_maps()
            for rail in rails():
                rel, argv_ = maps.get(rail, ("(no allocator recipe)", []))
                print(f"  {rail:<16} {rel:<32} {' '.join(argv_)}")
            return 0
        problems, notes, evaluated = check()
        n_rails = len(rails())
    except RailError as e:
        print(f"RAIL REGISTRATION FAILED: {e}", file=sys.stderr)
        return 1

    if problems:
        print("RAIL NOT REGISTERED: a rail under game/ is wired into some of "
              "its eleven sites and not others.\n"
              "(Makefile .PHONY | gates rail list | gates md5 list | "
              "conftest.MAPS | conftest._SUBDIR_MAP | bare_check.sh "
              "size list | bare_check.sh rom_md5 list | freshness-guard "
              "reviewed dict | AGENTS.md build-first block | determinism "
              "prereqs | test prereqs)",
              file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    ALL_SITES = set(range(1, 12))
    if evaluated != ALL_SITES:
        print(f"RAIL REGISTRATION FAILED: only site checks "
              f"{sorted(evaluated)} ran (expected all of "
              f"{sorted(ALL_SITES)}) — the gate is DISARMED, not clean.",
              file=sys.stderr)
        return 1

    conftest_checked = n_rails - len(notes)
    print(f"rail-registered OK: {n_rails} rail(s) under game/ present at all "
          f"{len(evaluated)} sites "
          f"(.PHONY, gates rail list, gates md5 list, "
          f"conftest.MAPS, conftest._SUBDIR_MAP, bare_check.sh size "
          f"list, bare_check.sh rom_md5 list, freshness-guard reviewed dict, "
          f"AGENTS.md build-first block, determinism prereqs, test prereqs); "
          f"sites 4+5+8 demanded of {conftest_checked}/{n_rails} "
          f"(the rails whose test module reads their map at collection "
          f"time), site 10 of the rails a Machine-driving module names "
          f"anywhere plus the falsify plant's own, site 11 of every rail "
          f"(the suite collects every module, so `make test` must pre-build "
          f"all of them)")
    for n in notes:
        print(f"  note: {n}")
    print("  checked: the rail is NAMED at each site — not that the site's "
          "recipe is correct. The build gates prove that.")
    print("  NOT checked, since the hosted workflow was retired on 2026-08-22: "
          "the ROM-step sweep that ran over ci.yml's steps and caught a VARIANT "
          "target built-but-never-measured. Every remaining measurement list "
          "(bare_check.sh sizes, bare_check.sh md5s, the gates md5 loop) is "
          "rail-scoped, so eight variant/control ROMs `make gates` builds are "
          "now measured nowhere — see this file's docstring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
