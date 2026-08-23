"""The gates as `make` targets — the layer nothing tested until a later review.

runtime: ~2-3 s on a warm build tree, measured (11 cases) — but it launches
whole `make` pipelines, so on a cold tree a node pays for whatever its target
builds and the module is minutes. It is a landing-time meta-test, not an
iteration loop: to answer one question, select one node.

Every other gate test in this suite invokes the underlying *script*
(`tools/gen_register.py --check`, `allocator/allocate.py`) and calls that "the
gate". It is not. Humans, `tools/setup.sh`, `make gates` and `make bare-check`
all run the **target**, and the target is where the
wiring lives: the inversion, the flag, the redirect, the grep of the
diagnostic. A Makefile-level break — wrong flag, wrong path, `register`
aliased to `register-write`, a recipe that cannot report the failure it names —
leaves every script-level test green.

That is not hypothetical. `make toy-bad` shipped for a day exiting non-zero on
*every* path, including the path that detects a toothless allocator, so its
status was a constant. Seven consumers read only that status. The one test that
would have caught it (`tests/test_toy_boot.py`'s `assert returncode != 0`)
could not fail, because it asserted the constant.

So these tests run the targets, and each one PLANTS the condition the target
claims to detect. `toy-bad` is planted through `TOY_BAD_SRC`, which points the
real recipe at a copy of `engine/toy_bad/` in `tmp_path` — the live tree is
never edited, so a killed run cannot leave it dirty.

WHAT PINS IT IS THE PAIR, NOT EITHER TEST ALONE. Measured against both
degenerate recipes:

  * the old recipe (every branch exits 1) — `..._has_no_teeth` PASSES
    (non-zero *is* what it saw) and `..._passes_on_the_real_tree` FAILS;
  * the opposite degeneracy (every branch exits 0) — the healthy-case test
    passes and `..._has_no_teeth` FAILS.

Neither test alone distinguishes a constant from a verdict; together they force
the exit status to be a function of the outcome, which is the whole property.
Stated explicitly because the failure being remediated here was a test that
asserted a constant and read as though it asserted a verdict.
"""
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

# `test_register_target_goes_RED_on_census_drift` plants into the SAME file
# tests/test_register.py plants into, and the rest of this module runs whole
# gates over the live tree. So it takes the same lock that module takes — one
# lock, not one each (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("repo_tree_lock")

SUPERFORGE = Path(__file__).resolve().parent.parent
REGISTER = SUPERFORGE / "docs" / "09_feature_register.md"
TOY_BAD = SUPERFORGE / "engine" / "toy_bad"


def make(*args) -> subprocess.CompletedProcess:
    """A target exactly as `make gates`, tools/setup.sh and a human invoke it.

    MAKEFLAGS is cleared. Under `make test` the suite runs inside a make
    recipe, so these become RECURSIVE makes: they inherit MAKEFLAGS, print
    `make[1]: Entering directory ...` around their output, and would inherit
    any flag the outer invocation carried (`-n` would turn every one of these
    into a dry run that asserts nothing). Clearing it makes a target behave the
    same whether the suite was started by `make test` or by bare pytest —
    otherwise these tests are environment-dependent in exactly the way the
    drift fixture set was.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    return subprocess.run(["make", *args], cwd=SUPERFORGE,
                          capture_output=True, text=True, env=env)


@contextmanager
def planted_text(path: Path, new: str):
    original = path.read_text()
    try:
        path.write_text(new)
        yield
    finally:
        path.write_text(original)


def toy_bad_copy(tmp_path: Path, name: str) -> Path:
    dst = tmp_path / name
    shutil.copytree(TOY_BAD, dst)
    return dst


# --------------------------------------------------------------------------
# make toy-bad — the collision gate's teeth
# --------------------------------------------------------------------------

def test_toy_bad_passes_on_the_real_tree():
    """The healthy case: the allocator refuses, so the target succeeds.

    This is the half of the pair that the old recipe fails — verified
    by restoring that recipe (every branch `exit 1`) and re-running: this test
    goes red with `assert 2 == 0` while the no-teeth test below stays green.
    """
    r = make("toy-bad")
    assert r.returncode == 0, (
        f"make toy-bad failed on the real tree:\n{r.stdout}\n{r.stderr}")
    assert "toy-bad OK" in r.stdout
    # and it failed for the right reason, not merely failed
    assert "ALLOCATION FAILED" in r.stderr and "VRAM overlap" in r.stderr


def test_toy_bad_goes_RED_when_the_allocator_has_no_teeth(tmp_path):
    """THE plant. Remove the collision; `make toy-bad` must now fail.

    Verified to fire: with the no-teeth branch changed to `exit 0`, this goes
    red (`assert 0 != 0`). It does NOT fire against the old recipe —
    that one exited non-zero here too — which is exactly why it is paired with
    the healthy-case test above. See the module docstring.
    """
    src = toy_bad_copy(tmp_path, "noteeth")
    p = src / "pin_b" / "feature.toml"
    p.write_text(p.read_text().replace("at = 0x1000", "at = 0x2000"))

    r = make("toy-bad", f"TOY_BAD_SRC={src}")
    assert r.returncode != 0, (
        "make toy-bad SUCCEEDED against a toy_bad with NO collision in it — "
        "the target cannot tell a refusal from a toothless allocator:\n"
        f"{r.stdout}")
    assert "no teeth" in r.stdout, (
        "red, but not through the no-teeth branch — the target may be failing "
        f"for an unrelated reason:\n{r.stdout}\n{r.stderr}")


def test_toy_bad_goes_RED_when_the_refusal_is_for_the_wrong_reason(tmp_path):
    """A refusal is not enough: it must be THE collision.

    A malformed declaration makes the allocator refuse too, and a status-only
    gate cannot tell the two apart — which is what the spec change set out
    to fix and did fix. This holds it fixed.
    """
    src = toy_bad_copy(tmp_path, "wrongreason")
    p = src / "pin_b" / "feature.toml"
    p.write_text(p.read_text().replace('role = "fixture"', 'role = "nonsense"'))

    r = make("toy-bad", f"TOY_BAD_SRC={src}")
    assert r.returncode != 0, (
        f"a SchemaError satisfied the collision gate:\n{r.stdout}")
    assert "wrong reason" in r.stdout or "not on the VRAM overlap" in r.stdout, \
        f"red, but not through a reason-check branch:\n{r.stdout}\n{r.stderr}"


def test_toy_bad_goes_RED_when_the_allocator_cannot_run(tmp_path):
    """A crash is not a refusal. Without the ALLOCATION FAILED grep, a broken
    allocator that traceback'd on every input would pass this gate forever."""
    r = make("toy-bad", f"TOY_BAD_SRC={tmp_path / 'nothing_here'}")
    assert r.returncode != 0
    assert "wrong reason" in r.stdout, f"{r.stdout}\n{r.stderr}"


# --------------------------------------------------------------------------
# make register — the target, not the script
# --------------------------------------------------------------------------

def test_register_target_passes_and_reports_its_reach():
    r = make("register")
    assert r.returncode == 0, f"make register is red:\n{r.stdout}\n{r.stderr}"
    assert "register OK" in r.stdout
    # the summary must state what it CHECKED, not only that it found nothing
    assert "demand lint reached" in r.stdout, (
        "make register does not report its reach — a gate's summary line "
        f"should say what it checked:\n{r.stdout}")


def test_register_target_goes_RED_on_census_drift():
    """Plant drift and run the TARGET. Proves `register` passes --check."""
    text = REGISTER.read_text()
    old = "| `vwf` | **feature** |"
    assert old in text, "the census row this test plants into has moved"
    with planted_text(REGISTER, text.replace(old, "| `vwf` | **blob** |", 1)):
        r = make("register")
        after = REGISTER.read_text()
    assert r.returncode != 0, "make register stayed green over census drift"
    assert "REGISTER DRIFT" in r.stderr, f"{r.stdout}\n{r.stderr}"
    assert "| `vwf` | **blob** |" in after, (
        "make register REWROTE the doc — it is aliased to register-write, so "
        "it can never report drift, only erase it")


def test_register_write_target_is_a_different_target():
    """`register` checks, `register-write` rewrites. If a refactor collapsed
    them, the check target would silently repair drift instead of reporting
    it — and `make register` would be green by construction forever."""
    r = subprocess.run(["make", "-n", "register"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "--check" in r.stdout, f"make register does not pass --check: {r.stdout}"
    assert "--write" not in r.stdout, f"make register passes --write: {r.stdout}"

    w = subprocess.run(["make", "-n", "register-write"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert w.returncode == 0, w.stderr
    assert "--write" in w.stdout, f"make register-write: {w.stdout}"


def test_width_check_target_is_clean_and_reports_its_scope():
    """CLAUDE.md rule 6: the baseline is zero. Asserted at the target."""
    r = make("width-check")
    assert r.returncode == 0, f"make width-check is red:\n{r.stdout}\n{r.stderr}"
    assert "0 finding(s)" in r.stdout, r.stdout


# --------------------------------------------------------------------------
# the `gates:` failure policy — measure must not be able to skip the suite
# --------------------------------------------------------------------------

def test_the_gates_skip_decision_ignores_a_measure_only_failure():
    """One legacy-runner flake once cost a whole gate block its suite.

    `measure` drives the free-running MesenRunner and wedges about 1 run in 5.
    It ran BEFORE `test` in the sequence and set the same variable the skip
    decision read, so a flake unrelated to the tree suppressed the ~8-minute
    suite. The recipe now keeps TWO variables: `first` (any failure — still
    the summary line and still the overall exit, so measure's POLARITY IS
    UNCHANGED) and `blocking` (failures other than measure — the only thing
    that skips `test`).

    WHAT THIS TEST PROVES AND WHAT IT DOES NOT. It reads the recipe text, so
    it pins the POLICY AS EXPRESSED, not the policy as executed — the same
    class of check `tools/rail_registered.py` states plainly about itself
    ("the rail is NAMED at each site, not that the site's recipe is
    correct"). The behaviour was demonstrated once by hand, with a forced
    measure red, and the summary pasted into the spec; running it here
    would cost a full gate block plus a full suite per invocation. What this
    catches is the cheap and likely regression: someone restoring `first` to
    the skip decision, or adding a second exempt gate without saying so.
    """
    recipe = _gates_recipe()
    assert 'if [ -z "$$blocking" ]; then run test;' in recipe, (
        "the skip decision no longer reads `blocking` — a measure-only red "
        f"can suppress the suite again :\n{recipe}")
    assert '[ "$$1" != measure ]' in recipe, (
        "measure is no longer exempt from the skip decision ")
    # ...and measure is STILL a gate: run in the sequence, and still feeding
    # `first`, which is the summary line and the overall exit.
    assert "run measure;" in recipe, "measure was dropped from the sequence"
    assert 'if [ $$rc -ne 0 ] && [ -z "$$first" ]; then first="$$1"; ' \
           'overall=$$rc; fi;' in recipe, (
        "the overall-exit accounting changed: a red measure must still make "
        "`make gates` exit non-zero (its polarity is unchanged)")
    # exactly ONE gate is exempt — a second one would be a policy change
    # wearing this one's justification
    assert recipe.count("!= measure") == 1, (
        "more than one gate is exempt from the skip decision; the "
        "exemption is measured for measure only")


def _gates_recipe() -> str:
    import re
    text = (SUPERFORGE / "Makefile").read_text()
    m = re.search(r"^gates:.*?(?=^\S)", text, re.M | re.S)
    assert m, "Makefile has no `gates:` target"
    return m.group(0)


# --------------------------------------------------------------------------
# asset-name collisions between rails — the `make test` cold-tree break
# --------------------------------------------------------------------------

def test_no_recipe_moves_an_asset_another_target_depends_on():
    """A recipe may not `mv` a generated asset that some target needs.

    THE DEFECT THIS PINS, reproduced 2026-08-07 before the fix:

        $ rm -f build/assets/*poses_*.bin \\
              build/{microzero,split_h_demo,racer}.sfc
        $ make microzero split_h_demo racer
        game/racer/main.asm(66): Error: Cannot open include file 'poses_ab.bin'

    `tools/gen_pose_tables.py` always writes `poses_ab.bin`/`poses_cd.bin`
    under the directory it is handed, and three rails want that pair at
    DIFFERENT parameters. `split_h_demo`'s recipe generated into
    `build/assets/` and `mv`'d the two files aside. Inside ONE make
    invocation that is a clobber with no repair: microzero builds the pair,
    make records it as up to date for the run, the `mv` takes it away, and
    racer — which declares it as a prerequisite — never gets it back, because
    make will not remake a target it already made. `make gates` is insulated
    (it drives one `$(MAKE)` per rail), but `test:`'s prerequisite list is one
    invocation in exactly that order — so `make test` could not build the tree
    it exists to pre-build, which is the whole point of that site.

    Checked structurally rather than by rebuilding: the reproduction costs
    three ROM links, and the invariant is textual and exact. A recipe may
    `mv` a file it generated into a scratch path (that is the fix); what it
    may not do is `mv` a path some target line declares as a prerequisite.
    """
    text = (SUPERFORGE / "Makefile").read_text()
    joined = re.sub(r"\\\n\s*", " ", text)

    # every `$(BUILD)/assets/<name>` named as a PREREQUISITE (target lines
    # only — a line with a `:` that is not a recipe line)
    needed = set()
    for ln in joined.splitlines():
        if ln.startswith("\t") or ":" not in ln:
            continue
        rhs = ln.split(":", 1)[1]
        needed |= set(re.findall(r"\$\(BUILD\)/assets/([A-Za-z0-9_.-]+)", rhs))

    # every `$(BUILD)/assets/<name>` a RECIPE line moves or deletes
    taken = {}
    for ln in joined.splitlines():
        if not ln.startswith("\t"):
            continue
        for verb in ("mv", "rm"):
            for m in re.finditer(
                    rf"\b{verb}\b[^\n]*?\$\(BUILD\)/assets/([A-Za-z0-9_.-]+)",
                    ln):
                taken.setdefault(m.group(1), ln.strip())

    clashes = {n: ln for n, ln in taken.items() if n in needed}
    assert not clashes, (
        "a recipe moves or removes a generated asset that another target "
        "declares as a prerequisite — inside one `make` invocation that is an "
        "unrepairable clobber, and `test:` is one invocation over every "
        "rail:\n" + "\n".join(f"  {n}: {ln}" for n, ln in clashes.items()))


def test_the_pose_generator_writes_into_the_directory_it_is_given():
    """The property the fix rests on, asserted rather than assumed.

    The scratch-dir fix only works because `gen_pose_tables.py` takes an
    output DIRECTORY and writes fixed filenames inside it. If it ever grew a
    fixed output path, the recipe would silently go back to clobbering.
    """
    src = (SUPERFORGE / "tools" / "gen_pose_tables.py").read_text()
    assert "poses_ab.bin" in src and "poses_cd.bin" in src
    assert re.search(r"argument\(\s*[\"']out|add_argument\(\s*[\"']out", src), (
        "gen_pose_tables.py no longer takes an output directory argument — "
        "the scratch-dir fix in the shd_poses recipe depends on it")
