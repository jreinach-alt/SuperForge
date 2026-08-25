"""`make rail-registered`, tried against a real violation at every site.

runtime: ~1:16 — ~35 gate invocations (each plant runs the gate at least
twice: planted, then undone), measured 2026-08-25. It was 16:12 on the same
box the same day: one gate run cost 27 s, ~97% of it re-parsing every test
module once per RAIL in `guard_visible_readers` / `determinism_demanding_
modules`; memoizing those pure-per-module derivations in the tool cut a run
to 2 s and this module followed. For one decisive check select a node:
`pytest tests/test_rail_registered.py::test_the_live_tree_is_registered -q` (~2 s).

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
  * the eleven plant tests fail if it accepts a broken one (ten sites;
    site 9 carries two, one per shape of its demand condition).

Together they force the exit status to be a function of the tree.

THE COUNT HAS MOVED TWICE, and the plants moved with it:

  * THIRTEEN plants over TWELVE sites until 2026-08-22, when the hosted
    workflow was retired and the `.github/workflows/ci.yml` site went with it
    (site 4 as it was numbered then; every site after it moved down one). The
    plants for that site and for its companion ROM-step sweep were removed
    with the checks they exercised.
  * TWELVE over ELEVEN until 2026-08-23. Sites 6 and 7 read `bare_check.sh`'s
    two hand-maintained rail lists; both lists were replaced by derivation and
    the pair collapsed into one site — the landing gate's derived
    expected-image set. Its plant is a DIFFERENT SHAPE from the two it
    replaces, and deliberately so: removing the rail from the `gates:` run-list
    would fire site 2 as well, so the plant instead leaves the rail in the
    run-list and breaks the target's resolution to an image. That is what makes
    site 6 more than a restatement of site 2.

See `tools/rail_registered.py`'s docstring for the sweep the ci.yml site
carried, and for how the hole it left was closed.

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
    # site 6 asks whether the landing gate still CONSUMES the derived
    # expected-image set, so bare_check.sh is read (its two hand-maintained
    # rail lists are gone — see the module docstring); site 8 reads AGENTS.md;
    # site 9 reads the determinism gate (its `--falsify` plant hardcodes a
    # rail's ROM, which `make determinism FALSIFY=1` needs for every module)
    shutil.copy2(SUPERFORGE / "tools" / "bare_check.sh",
                 root / "tools" / "bare_check.sh")
    shutil.copy2(SUPERFORGE / "tools" / "determinism_gate.py",
                 root / "tools" / "determinism_gate.py")
    # site 6's expected-image set has a leg that reads the VARIANT SCRIPTS'
    # own call sites — the images no `game/` dir backs. Copy them all: which
    # ones the derivation reaches is decided by the Makefile, not here, and a
    # skeleton that carried a chosen subset would be a second opinion about
    # that.
    for script in sorted((SUPERFORGE / "tools").glob("build_*.sh")):
        shutil.copy2(script, root / "tools" / script.name)
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
# the eleven plants — one registration removed, one site named
# --------------------------------------------------------------------------
#
# Sites 1-8 and 10 plant against `breaker` (a legacy rail, present at every
# unconditional site). Site 9's demand condition is "a Machine-driving
# module names this rail's ROM or map anywhere, or the falsify plant
# hardcodes it", which breaker's module does not satisfy — so its plants
# remove rails the condition actually derives. It gets TWO rows, one per shape — see
# the comment on the second.

SITES = [
    ("1/10", "breaker", "Makefile", "gates breaker shmup", "gates shmup",
     False, "`.PHONY`"),
    # This one now names TWO sites for breaker, and correctly: the derived
    # expected-image set is built FROM the run-list, so a rail dropped from it
    # is also a rail the landing gate stops demanding. The assertion below
    # rejects collateral on OTHER rails, not a second true finding on this one.
    ("2/10", "breaker", "Makefile", "run room; run breaker; run shmup",
     "run room; run shmup", False, "gates: rail list"),
    ("3/10", "breaker", "Makefile", "for rom in microzero room breaker shmup",
     "for rom in microzero room shmup", False, "gates: md5 list"),
    ("4/10", "breaker", "tests/conftest.py",
     '    "build/bk/symbol_map.json": (\n'
     '        "breaker",\n'
     '        ["--game", "game/breaker", "--features-dir", '
     '"engine/features"]),\n', "", False, "conftest.MAPS"),
    ("5/10", "breaker", "tests/conftest.py",
     '               "bk": "build/bk/symbol_map.json",\n', "", False,
     "conftest._SUBDIR_MAP"),
    # Site 6's plant is deliberately NOT "drop breaker from the gates run
    # list" — that is site 2's plant, and it would fire both. This one leaves
    # the rail in the run-list and breaks what the target RESOLVES TO: the
    # derivation reads each gates target's own rule for the
    # `$(BUILD)/X.sfc` it names, so a rule pointed at a different image drops
    # `breaker.sfc` out of the set the landing gate demands while site 2 stays
    # green. It is the shape a careless rename takes, and it is the whole
    # reason site 6 is a site rather than a restatement.
    ("6/10", "breaker", "Makefile",
     "breaker: $(BUILD)/breaker.sfc", "breaker: $(BUILD)/breaker_renamed.sfc",
     False, "landing gate's derived expected-image set"),
    ("7/10", "breaker", "tests/test_map_freshness_guard.py",
     '        "test_breaker.py": ["build/bk/symbol_map.json"],\n', "", False,
     "freshness-guard reviewed dict"),
    # replace-first is safe: the block is the FIRST " breaker" in AGENTS.md
    # (the prose mentions live far below the build-and-test fence)
    ("8/10", "breaker", "AGENTS.md", " breaker", "", False,
     "AGENTS.md build-first block"),
    ("9/10", "scroller", "Makefile",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game scroller",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game", False,
     "Makefile determinism prereqs"),
    # Site 9 gets a SECOND row because its demand condition has two shapes
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
    ("9/10", "microzero", "Makefile",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game scroller",
     "determinism: split_h_2p_demo sh2-variants hud_game scroller", False,
     "Makefile determinism prereqs (lazy-map rail)"),
    # Site 10 is site 9's unconditional sibling: `make test` collects EVERY
    # module, so it must pre-build EVERY rail. Planted on `breaker` like the
    # other unconditional sites. Removing it from `test:` is exactly the
    # commit that would restore the recorded drop — a `make test XDIST=4`
    # that dies with `INTERNALERROR> ... assert not crashitem` naming
    # test_allocator.py, a pure-Python module with nothing to do with breaker.
    ("10/10", "breaker", "Makefile",
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
# the disarm guard — the mechanism that makes "all ten" mean something
# --------------------------------------------------------------------------

# Deleting a site's check must not read as a PASS. `check()` records the site
# numbers whose logic actually RAN, and `main()` refuses when that set is not
# all ten — so a gate someone quietly disarmed fails instead of printing
# "present at all N sites" from a constant. The expected count is derived from
# `range()`, not typed, and the assertion below reads the two lists the refusal
# prints, so the property has now survived TWO renumberings — twelve to eleven,
# then eleven to ten — without either half being restated.
#
# This is a later review: the property was real
# but nothing in the suite kept it that way, and it is precisely the kind of
# guard that rots silently — its whole job is to fire on a tree nobody has
# broken yet. Both shapes are planted: an UNCONDITIONAL site (6) and a
# CONDITIONALLY-DEMANDED one (9, whose `evaluated.add` is
# deliberately placed BEFORE its demand test so that "the check ran" cannot be
# confused with "the check complained").

DISARM_PLANTS = [
    (6, """        evaluated.add(6)
        if rail not in measured:
            problems.append(
                f"{rail}: site 6/10 -- the LANDING gate's derived "
                f"expected-image set does not contain `{rail}.sfc`, so "
                f"bare-check would not notice if this rail's ROM stopped "
                f"being built at all, and its size and md5 would silently "
                f"leave build/bare_check.json. The set is derived from the "
                f"`gates:` run-list: each target it runs contributes the "
                f"`$(BUILD)/X.sfc` its own rule names, so the usual cause is "
                f"a `{rail}:` rule that no longer names $(BUILD)/{rail}.sfc "
                f"(site 2 would still be green -- the rail IS in the "
                f"run-list, it just no longer resolves to an image).")
"""),
    (9, """        evaluated.add(9)
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
                f"{rail}: site 9/10 -- absent from the Makefile "
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
        # and crucially NOT sites 4/5/7 (nor any other per-rail site).
        assert "zz_norails: site 0/10" in out, out
        assert "zz_norails: site 4/10" not in out
        assert "zz_norails: site 5/10" not in out
        assert "zz_norails: site 7/10" not in out
    finally:
        shutil.rmtree(skeleton / "game" / "zz_norails")
    assert run_gate(skeleton).returncode == 0


def test_a_landing_gate_that_stopped_consuming_the_derivation_is_named(
        skeleton):
    """Site 6's other half: the set is only worth deriving if it is READ.

    `expected_images()` could be perfect and `tools/bare_check.sh` could have
    gone back to carrying its own list of ROMs, and every per-rail site-6
    check would still pass while the landing gate demanded nothing. That is
    the fail-open shape the two retired lists had, arriving by a different
    door — so the gate asks whether the landing gate still runs
    `--expected-images` at all. Not a per-rail site: the answer is the same
    for every rail, which is exactly why it is checked once.
    """
    # The INVOCATION, not the prose that explains it — the flag is named in
    # the census block's comments too, and a plant that only took out the
    # comment would leave the gate correctly green.
    undo = plant(skeleton, "tools/bare_check.sh",
                 '"--expected-images"], capture_output=True',
                 '"--list"], capture_output=True')
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, (
            f"the gate ACCEPTED a landing gate that no longer consumes the "
            f"derived expected-image set:\n{out}")
        assert "no longer runs" in out and "--expected-images" in out, out
    finally:
        undo()
    assert run_gate(skeleton).returncode == 0, "the undo did not restore"


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
