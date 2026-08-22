"""`make rail-registered`, tried against a real violation at every site.

SLOW BY DESIGN — each case synthesises a violating tree and runs the gate
over every rail, per site (minutes for the module). For one decisive check
select a node: `pytest tests/test_rail_registered.py::test_the_live_tree_is_registered -q` (~30 s).

AGENTS.md: "when you add a gate, prove it fails on a real violation before
believing it." The violation is the one waves 1-5 kept committing — a rail
under `game/` wired into some of its registration sites and not others. Each
test here REMOVES one registration and asserts the gate names THAT site, for
THAT rail.

WHAT PINS THIS IS THE PAIR, not either half — the same discipline
`tests/test_make_gates.py` states for `toy-bad`. A gate that refuses
everything and a gate that refuses nothing are both constants, and both read
like verdicts:

  * `test_the_live_tree_is_registered` fails if the gate refuses a healthy
    tree;
  * the twelve plant tests fail if it accepts a broken one (eleven sites;
    site 10 carries two, one per shape of its demand condition).

Together they force the exit status to be a function of the tree.

The count was THIRTEEN plants over TWELVE sites until 2026-08-22, when the
hosted workflow was retired and the `.github/workflows/ci.yml` site went with
it (site 4 as it was numbered then; every site after it moved down one). The
plants for that site and for its companion ROM-step sweep were removed with
the checks they exercised — see `tools/rail_registered.py`'s docstring for
what the sweep covered and what is now covered nowhere.

Test surface (CLAUDE.md rule 2): the output region read is the gate's own
stderr report and exit status over a REAL tree — a skeleton carrying the
actual `Makefile`, the actual `tests/` (so the collection-time-read
derivation runs against the real modules) and the actual tool. Not a mocked
parser and not a hand-written fixture: the plants edit the same bytes a
careless commit would.

The skeleton is a COPY. A plant that edits the live tree and dies mid-window
leaves a wrong `Makefile` behind looking like an ordinary uncommitted edit,
which is the class the repo-tree lock exists for; a copy has no such window.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
TOOL = SUPERFORGE / "tools" / "rail_registered.py"


@pytest.fixture(scope="module")
def skeleton(tmp_path_factory) -> Path:
    """A throwaway tree carrying everything the gate reads.

    `game/<rail>/game.toml` is stubbed rather than copied — the gate only
    asks whether the file exists, and copying the rails would drag in every
    `.asm` and blob for nothing.
    """
    root = tmp_path_factory.mktemp("railtree")
    (root / "tools").mkdir()
    shutil.copy2(TOOL, root / "tools" / "rail_registered.py")
    # sites 6+7 read the landing gate's two lists; site 9 reads AGENTS.md;
    # site 10 reads the determinism gate (its `--falsify` plant hardcodes a
    # rail's ROM, which `make determinism FALSIFY=1` needs for every module)
    shutil.copy2(SUPERFORGE / "tools" / "bare_check.sh",
                 root / "tools" / "bare_check.sh")
    shutil.copy2(SUPERFORGE / "tools" / "determinism_gate.py",
                 root / "tools" / "determinism_gate.py")
    shutil.copy2(SUPERFORGE / "AGENTS.md", root / "AGENTS.md")
    shutil.copy2(SUPERFORGE / "Makefile", root / "Makefile")
    shutil.copytree(SUPERFORGE / "tests", root / "tests",
                    ignore=shutil.ignore_patterns("__pycache__", "fixtures"))
    (root / "game").mkdir()
    for d in sorted((SUPERFORGE / "game").iterdir()):
        if (d / "game.toml").exists():
            (root / "game" / d.name).mkdir()
            (root / "game" / d.name / "game.toml").write_text("")
    return root


def run_gate(root: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    return subprocess.run([sys.executable, "tools/rail_registered.py"],
                          cwd=root, capture_output=True, text=True, env=env,
                          timeout=120)


def plant(root: Path, rel: str, old: str, new: str, *, regex=False):
    """Edit one file in the skeleton, guarded, and hand back the undo.

    The `assert old in src` guard is what turns a plant that silently matched
    nothing into a visible failure — the sabotage-that-was-a-no-op class
    (AGENTS.md; and the slide plant in a later sweep that stayed green for exactly
    this reason).
    """
    p = root / rel
    src = p.read_text()
    if regex:
        assert re.search(old, src, re.M), f"PLANT GUARD: no match in {rel}"
        p.write_text(re.sub(old, new, src, count=1, flags=re.M))
    else:
        assert old in src, f"PLANT GUARD: {old!r} not in {rel}"
        p.write_text(src.replace(old, new, 1))
    return lambda: p.write_text(src)


# --------------------------------------------------------------------------
# the healthy arm
# --------------------------------------------------------------------------

def test_the_live_tree_is_registered():
    """The real repo passes, so the per-site tests below are not asserting a
    constant."""
    r = run_gate(SUPERFORGE)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "rail-registered OK" in r.stdout


def test_the_target_is_the_gate():
    """Run it the way `make gates`, `make bare-check` and a human do —
    through `make`.

    `tests/test_make_gates.py` exists because a target's wiring (flag, path,
    redirect) is where gates break while every script-level test stays green.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    r = subprocess.run(["make", "rail-registered"], cwd=SUPERFORGE, env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "rail-registered OK" in r.stdout


def test_the_skeleton_itself_is_clean(skeleton):
    """The copy reproduces the live verdict — otherwise every plant below is
    measuring the copy, not the gate."""
    r = run_gate(skeleton)
    assert r.returncode == 0, r.stdout + r.stderr


# --------------------------------------------------------------------------
# the twelve plants — one registration removed, one site named
# --------------------------------------------------------------------------
#
# Sites 1-9 and 11 plant against `breaker` (a legacy rail, present at every
# unconditional site). Site 10's demand condition is "a Machine-driving
# module names this rail's ROM or map anywhere, or the falsify plant
# hardcodes it", which breaker's module does not satisfy — so its plants
# remove rails the condition actually derives. It gets TWO rows, one per shape — see
# the comment on the second.

SITES = [
    ("1/11", "breaker", "Makefile", "gates breaker shmup", "gates shmup",
     False, "`.PHONY`"),
    ("2/11", "breaker", "Makefile", "run room; run breaker; run shmup",
     "run room; run shmup", False, "gates: rail list"),
    ("3/11", "breaker", "Makefile", "for rom in microzero room breaker shmup",
     "for rom in microzero room shmup", False, "gates: md5 list"),
    ("4/11", "breaker", "tests/conftest.py",
     '    "build/bk/symbol_map.json": (\n'
     '        "breaker",\n'
     '        ["--game", "game/breaker", "--features-dir", '
     '"engine/features"]),\n', "", False, "conftest.MAPS"),
    ("5/11", "breaker", "tests/conftest.py",
     '               "bk": "build/bk/symbol_map.json",\n', "", False,
     "conftest._SUBDIR_MAP"),
    ("6/11", "breaker", "tools/bare_check.sh", " breaker:524288", "", False,
     "bare_check.sh size list"),
    ("7/11", "breaker", "tools/bare_check.sh", '"breaker", ', "", False,
     "bare_check.sh rom_md5 list"),
    ("8/11", "breaker", "tests/test_map_freshness_guard.py",
     '        "test_breaker.py": ["build/bk/symbol_map.json"],\n', "", False,
     "freshness-guard reviewed dict"),
    # replace-first is safe: the block is the FIRST " breaker" in AGENTS.md
    # (the prose mentions live far below the build-and-test fence)
    ("9/11", "breaker", "AGENTS.md", " breaker", "", False,
     "AGENTS.md build-first block"),
    ("10/11", "scroller", "Makefile",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game scroller",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game", False,
     "Makefile determinism prereqs"),
    # Site 10 gets a SECOND row because its demand condition has two shapes
    # and the first row only exercises one. `scroller` above reads its map at
    # collection time, so it qualified under the OLD conjunction
    # (`collection-time reader ∧ Machine-driving`) too. `microzero` does not:
    # its only map read is inside a test body (test_machine.py's `:163`), so
    # under that conjunction it was silently EXEMPT
    # it from `determinism:` and the gate stayed GREEN, while `make
    # determinism FALSIFY=1` would have died on the missing ROM for every
    # module (the falsify plant hardcodes build/microzero.sfc). That is
    # a later review, and this row is the regression fixture for it: it fails if
    # the two conjuncts are ever re-coupled.
    ("10/11", "microzero", "Makefile",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game scroller",
     "determinism: split_h_2p_demo sh2-variants hud_game scroller", False,
     "Makefile determinism prereqs (lazy-map rail)"),
    # Site 11 is site 10's unconditional sibling: `make test` collects EVERY
    # module, so it must pre-build EVERY rail. Planted on `breaker` like the
    # other unconditional sites. Removing it from `test:` is exactly the
    # commit that would restore the recorded drop — a `make test XDIST=4`
    # that dies with `INTERNALERROR> ... assert not crashitem` naming
    # test_allocator.py, a pure-Python module with nothing to do with breaker.
    ("11/11", "breaker", "Makefile",
     "test: toy microzero room probes breaker shmup",
     "test: toy microzero room probes shmup", False,
     "Makefile test prereqs"),
]


@pytest.mark.parametrize("site,rail,rel,old,new,regex,label", SITES,
                         ids=[s[0].replace("/", "of") + "-" + s[6]
                              for s in SITES])
def test_a_missing_registration_names_that_site(skeleton, site, rail, rel,
                                                old, new, regex, label):
    undo = plant(skeleton, rel, old, new, regex=regex)
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, f"the gate ACCEPTED a missing {label}:\n{out}"
        assert "RAIL NOT REGISTERED" in out, out
        assert f"{rail}: site {site}" in out, (
            f"expected site {site} ({label}) named for {rail}:\n{out}")
        # and it must not blame a rail that is fine
        others = [ln for ln in out.splitlines()
                  if re.match(r"\s+\w+: site ", ln) and rail not in ln]
        assert not others, f"collateral findings on healthy rails:\n{others}"
    finally:
        undo()
    assert run_gate(skeleton).returncode == 0, "the undo did not restore"


# --------------------------------------------------------------------------
# the disarm guard — the mechanism that makes "all eleven" mean something
# --------------------------------------------------------------------------

# Deleting a site's check must not read as a PASS. `check()` records the site
# numbers whose logic actually RAN, and `main()` refuses when that set is not
# all eleven — so a gate someone quietly disarmed fails instead of printing
# "present at all N sites" from a constant. The expected count is derived from
# `range()`, not typed, and the assertion below reads the two lists the refusal
# prints, so the property survived the drop from twelve sites to eleven without
# either half being restated.
#
# This is a later review: the property was real
# but nothing in the suite kept it that way, and it is precisely the kind of
# guard that rots silently — its whole job is to fire on a tree nobody has
# broken yet. Both shapes are planted: an UNCONDITIONAL site (7) and a
# CONDITIONALLY-DEMANDED one (10, whose `evaluated.add` is
# deliberately placed BEFORE its demand test so that "the check ran" cannot be
# confused with "the check complained").

DISARM_PLANTS = [
    (7, """        evaluated.add(7)
        if rail not in bare_md5:
            problems.append(
                f"{rail}: site 7/11 -- absent from tools/bare_check.sh's "
                f"rom_md5 list (the embedded `for rom in (...)` tuple). "
                f"build/bare_check.json omits the rail's md5, so the one "
                f"artifact the landing rule cites cannot pin its binary.")
"""),
    (10, """        evaluated.add(10)
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
"""),
]


@pytest.mark.parametrize("site,block", DISARM_PLANTS,
                         ids=[f"site{s}" for s, _ in DISARM_PLANTS])
def test_a_deleted_site_check_reads_as_disarmed(skeleton, site, block):
    """Delete one site's check; the gate must REFUSE, naming that site.

    The assertion reads the gate's own exit status and stderr over a real
    tree with a real check removed — not a mocked counter. The missing site
    number is derived from the two lists the message prints (ran vs
    expected), so this survives renumbering rather than pinning prose.
    """
    undo = plant(skeleton, "tools/rail_registered.py", block, "")
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, (
            f"the gate ACCEPTED a tree with site {site}'s check deleted — "
            f"a disarmed gate read as clean:\n{out}")
        assert "is DISARMED, not clean" in out, out
        m = re.search(r"only site checks \[([^\]]*)\] ran "
                      r"\(expected all of \[([^\]]*)\]\)", out)
        assert m, f"the refusal did not name the sites:\n{out}"
        ran = {int(x) for x in m.group(1).split(",")}
        expected = {int(x) for x in m.group(2).split(",")}
        assert expected - ran == {site}, (
            f"expected site {site} to be the one reported missing; "
            f"ran={sorted(ran)} expected={sorted(expected)}\n{out}")
        # a disarmed gate must not ALSO be blaming rails — that would be a
        # different failure wearing the same exit code
        assert "RAIL NOT REGISTERED" not in out, out
    finally:
        undo()
    assert run_gate(skeleton).returncode == 0, "the undo did not restore"


def test_the_conftest_argv_must_match_the_makefile(skeleton):
    """MAPS claims to carry "the same invocation the Makefile recipe uses".

    That is a claim, so it is checked: drift it and the gate says so. Without
    this the two could disagree about how a map is produced, and "STALE"
    would stop meaning "differs from what today's declarations emit".
    """
    undo = plant(skeleton, "tests/conftest.py",
                 '["--game", "game/breaker", "--features-dir", '
                 '"engine/features"]),',
                 '["--game", "game/breaker"]),')
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, out
        assert "is not the Makefile's invocation" in out, out
    finally:
        undo()


def test_a_rail_with_no_test_module_is_not_asked_for_the_two_dicts(skeleton):
    """The condition for sites 4+5+8 is derived, not assumed.

    A rail nothing reads at collection time does not need the freshness
    registry (nor the guard's reviewed dict), and the gate says so in a note
    instead of a finding — otherwise it would demand ceremony for a rail
    whose tests build their own map in a fixture, which several do.
    """
    (skeleton / "game" / "zz_norails").mkdir()
    (skeleton / "game" / "zz_norails" / "game.toml").write_text("")
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        # no allocator recipe for it either, so site 0 is what fires —
        # and crucially NOT sites 4/5/8 (nor any other per-rail site).
        assert "zz_norails: site 0/11" in out, out
        assert "zz_norails: site 4/11" not in out
        assert "zz_norails: site 5/11" not in out
        assert "zz_norails: site 8/11" not in out
    finally:
        shutil.rmtree(skeleton / "game" / "zz_norails")
    assert run_gate(skeleton).returncode == 0


def test_the_gate_checks_its_own_registration(skeleton):
    """`rail-registered` must itself be in the runner that runs it.

    A gate cannot detect its own absence from that runner — the residual is
    stated in the tool. What survives is the half a hand-run or a suite run
    still reaches: drop `run rail-registered;` from `make gates` and any
    OTHER surface that invokes the gate says so.

    This test used to have a second arm. While the hosted workflow existed
    there were two runners, and the gate checked its own membership of both —
    the asymmetric case (present in one list, missing from the other) was the
    thing it could actually catch. The workflow was retired on 2026-08-22, so
    that arm and the property behind it are gone with it, not mislaid.
    """
    undo = plant(skeleton, "Makefile", "run rail-registered; ", "")
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, out
        assert "rail-registered: absent from the Makefile `gates:` rail list" \
            in out, out
    finally:
        undo()
    assert run_gate(skeleton).returncode == 0
