"""`make rail-registered`, tried against a real violation at every site.

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
  * the thirteen plant tests fail if it accepts a broken one (twelve sites;
    site 11 carries two, one per shape of its demand condition).

Together they force the exit status to be a function of the tree.

Test surface (CLAUDE.md rule 2): the output region read is the gate's own
stderr report and exit status over a REAL tree — a skeleton carrying the
actual `Makefile`, the actual `.github/workflows/ci.yml`, the actual
`tests/` (so the collection-time-read derivation runs against the real
modules) and the actual tool. Not a mocked parser and not a hand-written
fixture: the plants edit the same bytes a careless commit would.

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
    # sites 7+8 read the landing gate's two lists; site 10 reads AGENTS.md;
    # site 11 reads the determinism gate (its `--falsify` plant hardcodes a
    # rail's ROM, which `make determinism FALSIFY=1` needs for every module)
    shutil.copy2(SUPERFORGE / "tools" / "bare_check.sh",
                 root / "tools" / "bare_check.sh")
    shutil.copy2(SUPERFORGE / "tools" / "determinism_gate.py",
                 root / "tools" / "determinism_gate.py")
    shutil.copy2(SUPERFORGE / "AGENTS.md", root / "AGENTS.md")
    shutil.copy2(SUPERFORGE / "Makefile", root / "Makefile")
    (root / ".github" / "workflows").mkdir(parents=True)
    shutil.copy2(SUPERFORGE / ".github" / "workflows" / "ci.yml",
                 root / ".github" / "workflows" / "ci.yml")
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
    """Run it the way CI, `make gates` and a human do — through `make`.

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
# the thirteen plants — one registration removed, one site named
# --------------------------------------------------------------------------
#
# Sites 1-10 and 12 plant against `breaker` (a legacy rail, present at every
# unconditional site). Site 11's demand condition is "a Machine-driving
# module names this rail's ROM or map anywhere, or the falsify plant
# hardcodes it", which breaker's module does not satisfy — so its plants
# remove rails the condition actually derives. It gets TWO rows, one per shape — see
# the comment on the second.

SITES = [
    ("1/12", "breaker", "Makefile", "gates breaker shmup", "gates shmup",
     False, "`.PHONY`"),
    ("2/12", "breaker", "Makefile", "run room; run breaker; run shmup",
     "run room; run shmup", False, "gates: rail list"),
    ("3/12", "breaker", "Makefile", "for rom in microzero room breaker shmup",
     "for rom in microzero room shmup", False, "gates: md5 list"),
    ("4/12", "breaker", ".github/workflows/ci.yml",
     r"      - name: make breaker\n        run: \|\n(?:          .*\n)+", "",
     True, "ci.yml step"),
    ("5/12", "breaker", "tests/conftest.py",
     '    "build/bk/symbol_map.json": (\n'
     '        "breaker",\n'
     '        ["--game", "game/breaker", "--features-dir", '
     '"engine/features"]),\n', "", False, "conftest.MAPS"),
    ("6/12", "breaker", "tests/conftest.py",
     '               "bk": "build/bk/symbol_map.json",\n', "", False,
     "conftest._SUBDIR_MAP"),
    ("7/12", "breaker", "tools/bare_check.sh", " breaker:524288", "", False,
     "bare_check.sh size list"),
    ("8/12", "breaker", "tools/bare_check.sh", '"breaker", ', "", False,
     "bare_check.sh rom_md5 list"),
    ("9/12", "breaker", "tests/test_map_freshness_guard.py",
     '        "test_breaker.py": ["build/bk/symbol_map.json"],\n', "", False,
     "freshness-guard reviewed dict"),
    # replace-first is safe: the block is the FIRST " breaker" in AGENTS.md
    # (the prose mentions live far below the build-and-test fence)
    ("10/12", "breaker", "AGENTS.md", " breaker", "", False,
     "AGENTS.md build-first block"),
    ("11/12", "scroller", "Makefile",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game scroller",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game", False,
     "Makefile determinism prereqs"),
    # Site 11 gets a SECOND row because its demand condition has two shapes
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
    ("11/12", "microzero", "Makefile",
     "determinism: split_h_2p_demo sh2-variants microzero hud_game scroller",
     "determinism: split_h_2p_demo sh2-variants hud_game scroller", False,
     "Makefile determinism prereqs (lazy-map rail)"),
    # Site 12 is site 11's unconditional sibling: `make test` collects EVERY
    # module, so it must pre-build EVERY rail. Planted on `breaker` like the
    # other unconditional sites. Removing it from `test:` is exactly the
    # commit that would restore the recorded drop — a `make test XDIST=4`
    # that dies with `INTERNALERROR> ... assert not crashitem` naming
    # test_allocator.py, a pure-Python module with nothing to do with breaker.
    ("12/12", "breaker", "Makefile",
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
# the disarm guard — the mechanism that makes "all twelve" mean something
# --------------------------------------------------------------------------

# Deleting a site's check must not read as a PASS. `check()` records the site
# numbers whose logic actually RAN, and `main()` refuses when that set is not
# all twelve — so a gate someone quietly disarmed fails instead of printing
# "present at all N sites" from a constant.
#
# This is a later review: the property was real
# but nothing in the suite kept it that way, and it is precisely the kind of
# guard that rots silently — its whole job is to fire on a tree nobody has
# broken yet. Both shapes are planted: an UNCONDITIONAL site (8, the auditor's
# own plant) and a CONDITIONALLY-DEMANDED one (11, whose `evaluated.add` is
# deliberately placed BEFORE its demand test so that "the check ran" cannot be
# confused with "the check complained").

DISARM_PLANTS = [
    (8, """        evaluated.add(8)
        if rail not in bare_md5:
            problems.append(
                f"{rail}: site 8/12 -- absent from tools/bare_check.sh's "
                f"rom_md5 list (the embedded `for rom in (...)` tuple). "
                f"build/bare_check.json omits the rail's md5, so the one "
                f"artifact the landing rule cites cannot pin its binary.")
"""),
    (11, """        evaluated.add(11)
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
                f"{rail}: site 11/12 -- absent from the Makefile "
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


# --------------------------------------------------------------------------
# the ci.yml ROM-step SWEEP — the arm that reaches variant targets
# --------------------------------------------------------------------------
#
# The twelve sites are per-RAIL, so none of them can see a step for a target
# that has no `game/` dir. `svd-nowin` is exactly that, and the recorded drop is what
# it cost: the B-3 union inserted `split_v_seamtrial`'s `- name:` between
# svd-nowin's `echo` and its `test "$size" -eq 524288`, which moved the assert
# into the seamtrial step. No line was removed, the YAML still parsed,
# `make rail-registered` was green, and `build/svd_nowin.sfc`'s 524,288 bytes
# were asserted nowhere at all (bare_check.sh's size list is rail-scoped too —
# Fifth instance of the drop class, and the first uncaught one.
#
# The plant below REPRODUCES that edit rather than approximating it: it lifts
# the seamtrial step's `- name:`/`run: |` header above svd-nowin's assert line,
# exactly as the union did.

_SVD_TAIL = (
    '          test "$size" -eq 524288 || { echo "::error::expected 524288 '
    'bytes, got $size"; exit 1; }\n'
    '\n'
    '      - name: make split_v_seamtrial\n'
    '        run: |\n')

_SVD_F1 = (
    '      - name: make split_v_seamtrial\n'
    '        run: |\n'
    '          test "$size" -eq 524288 || { echo "::error::expected 524288 '
    'bytes, got $size"; exit 1; }\n')


def test_the_real_batch4_f1_drop_is_named(skeleton):
    """Reproduce the recorded union damage; the sweep must name it.

    Test surface: the gate's own stderr + exit status over a real ci.yml with
    the real defect re-planted. The assertion reads the step NAME the gate
    reports, not a count — a sweep that fired on the wrong step would pass a
    count check.
    """
    undo = plant(skeleton, ".github/workflows/ci.yml", _SVD_TAIL, _SVD_F1)
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, (
            f"the gate ACCEPTED a ci.yml step that builds a ROM and never "
            f"asserts its size — the recorded drop all over again:\n{out}")
        assert "RAIL NOT REGISTERED" in out, out
        assert "ci.yml step `make svd-nowin`" in out, (
            f"expected the sweep to name the svd-nowin step:\n{out}")
        assert "build/svd_nowin.sfc" in out, out
        # and it must not blame the step that ABSORBED the assert, nor any
        # healthy rail — this shape leaves seamtrial's block well-formed
        assert "ci.yml step `make split_v_seamtrial`" not in out, out
        others = [ln for ln in out.splitlines() if re.match(r"\s+\w+: site ",
                                                            ln)]
        assert not others, f"collateral per-rail findings:\n{others}"
    finally:
        undo()
    assert run_gate(skeleton).returncode == 0, "the undo did not restore"


def test_a_rail_step_losing_its_assert_is_named_by_the_sweep_too(skeleton):
    """The sweep is not a variants-only check — it covers rails as well.

    Rails are deliberately covered TWICE (site 4 from the rail census, the
    sweep from the step list). This asserts the second arm exists rather than
    letting site 4's finding stand in for it: a `racer` step stripped of its
    assert must be named by BOTH.
    """
    undo = plant(skeleton, ".github/workflows/ci.yml",
                 '          size=$(stat -c%s build/racer.sfc)\n'
                 '          echo "build/racer.sfc = $size bytes"\n'
                 '          test "$size" -eq 524288 || { echo "::error::'
                 'expected 524288 bytes, got $size"; exit 1; }\n',
                 '          size=$(stat -c%s build/racer.sfc)\n'
                 '          echo "build/racer.sfc = $size bytes"\n')
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, out
        assert "ci.yml step `make racer`" in out, (
            f"the sweep did not name the rail's step:\n{out}")
        assert "racer: site 4/12" in out, (
            f"site 4 stopped naming it — the two arms are not redundant "
            f"by accident, they are redundant on purpose:\n{out}")
    finally:
        undo()
    assert run_gate(skeleton).returncode == 0, "the undo did not restore"


def test_an_assert_above_its_stat_is_not_credited(skeleton):
    """Order matters, not just presence.

    A union that aligns one line differently can park the assert ABOVE the
    stat that feeds `$size`. The step then dies on an unset variable rather
    than on a size mismatch — still broken, and a presence-only check would
    call it registered.
    """
    undo = plant(skeleton, ".github/workflows/ci.yml",
                 '          size=$(stat -c%s build/maze.sfc)\n'
                 '          echo "build/maze.sfc = $size bytes"\n'
                 '          test "$size" -eq 524288 || { echo "::error::'
                 'expected 524288 bytes, got $size"; exit 1; }\n',
                 '          test "$size" -eq 524288 || { echo "::error::'
                 'expected 524288 bytes, got $size"; exit 1; }\n'
                 '          size=$(stat -c%s build/maze.sfc)\n'
                 '          echo "build/maze.sfc = $size bytes"\n')
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, (
            f"an assert that runs BEFORE its stat was credited:\n{out}")
        assert "ci.yml step `make maze`" in out, out
    finally:
        undo()
    assert run_gate(skeleton).returncode == 0, "the undo did not restore"


# The sweep's own disarm plant. Its finding count is zero on a healthy tree
# either way, so the number that has to move is the number of steps EXAMINED
# — deleting the sweep must refuse, not print a clean verdict over nothing.
# Same discipline as DISARM_PLANTS above, different mechanism (the sites use a
# set-difference over `evaluated`; the sweep uses its own emptiness), so it
# needs its own plant rather than a row in that table.

def test_a_deleted_ci_sweep_reads_as_disarmed(skeleton):
    undo = plant(skeleton, "tools/rail_registered.py",
                 "    swept = ci_rom_steps(ci_text)\n"
                 "    problems += ci_sweep_problems(swept)\n",
                 "    swept = []\n")
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, (
            f"the gate ACCEPTED a tree with the ci.yml ROM-step sweep "
            f"deleted — a disarmed check read as clean:\n{out}")
        assert "examined 0 steps" in out, out
        assert "is DISARMED, not clean" in out, out
        assert "RAIL NOT REGISTERED" not in out, out
    finally:
        undo()
    assert run_gate(skeleton).returncode == 0, "the undo did not restore"


def test_the_sweep_reports_the_step_count_it_examined(skeleton):
    """A pass must say how much it looked at, or it cannot be read.

    `rail-registered OK` over an empty sweep and over the whole workflow would
    otherwise print the same line. The count is the difference.
    """
    r = run_gate(skeleton)
    assert r.returncode == 0, r.stdout + r.stderr
    m = re.search(r"ci\.yml ROM-step sweep: (\d+) step\(s\) run make and stat "
                  r"a build/\*\.sfc, covering (\d+) ROM\(s\); all (\d+) "
                  r"assert their size", r.stdout)
    assert m, f"the summary does not report the sweep's reach:\n{r.stdout}"
    steps, roms, asserted = (int(g) for g in m.groups())
    # one step per rail, plus `toy`, plus the variant targets — so strictly
    # more than the rail count, which is the property that says the sweep is
    # not just re-running site 4
    n_rails = len([d for d in (skeleton / "game").iterdir() if d.is_dir()])
    assert steps > n_rails, (
        f"the sweep examined {steps} steps for {n_rails} rails — it is not "
        f"reaching the non-rail targets it exists for")
    assert asserted == steps and roms >= steps


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
    """The condition for sites 5+6+9 is derived, not assumed.

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
        # and crucially NOT sites 5/6/9 (nor any other per-rail site).
        assert "zz_norails: site 0/12" in out, out
        assert "zz_norails: site 5/12" not in out
        assert "zz_norails: site 6/12" not in out
        assert "zz_norails: site 9/12" not in out
    finally:
        shutil.rmtree(skeleton / "game" / "zz_norails")
    assert run_gate(skeleton).returncode == 0


def test_the_gate_checks_its_own_registration(skeleton):
    """`rail-registered` must itself be in both runners.

    A gate cannot detect its own absence from the runner that would have run
    it — the residual is stated in the tool. What it CAN catch is the
    asymmetric half, which is exactly the failure site 4 exists for.
    """
    undo = plant(skeleton, ".github/workflows/ci.yml",
                 "      - name: make rail-registered\n"
                 "        run: make rail-registered\n", "")
    try:
        r = run_gate(skeleton)
        out = r.stdout + r.stderr
        assert r.returncode == 1, out
        assert "rail-registered: absent from .github/workflows/ci.yml" in out, out
    finally:
        undo()

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
