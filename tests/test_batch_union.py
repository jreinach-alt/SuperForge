"""`tools/batch_union.py`, tried against the three drops it exists to stop.

AGENTS.md: "when you add a gate, prove it fails on a real violation before
believing it." The violation here is on record: three consecutive landings
lost a ci.yml rail step's `test "$size" -eq` assert line at a hunk boundary
(patrol's in the sprite_game merge, jumper's in the stomper merge, stomper's
in the scroll_run merge). `tests/fixtures/batch_union/` holds those three
conflicts in the alignment git produced; its README has the shape.

TEST SURFACE (CLAUDE.md rule 2). The output region read is the tool's actual
OUTPUT TEXT — the resolved file it would write — and the assertion is the
structural invariant the landings really violated: every `- name: make <rail>`
step in the result is terminated by an assert line. Not "the tool returned a
string", not "the hunk count is 1". A test that only counted hunks would have
passed against the script that dropped the lines.

Three properties, because each catches a different way to get this wrong:

  1. NO LINE IS LOST — the multiset of non-marker lines going in equals the
     multiset coming out. This is the anti-drop property, stated as
     arithmetic so it cannot be satisfied by a plausible-looking result.
  2. EVERY STEP KEEPS ITS ASSERT — the semantic form of (1) for this file
     kind, and the one a human reviewing the diff could not see, because
     every rail asserts the same 524,288 bytes.
  3. ORDER IS OURS-THEN-THEIRS — a union that keeps every line but
     interleaves them is not a resolution anyone can review.
"""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
TOOL = SUPERFORGE / "tools" / "batch_union.py"
FIXTURES = SUPERFORGE / "tests" / "fixtures" / "batch_union"

_spec = importlib.util.spec_from_file_location("batch_union", TOOL)
bu = importlib.util.module_from_spec(_spec)
# Registered BEFORE exec: `@dataclass` resolves its own module through
# `sys.modules[cls.__module__]`, and an unregistered module makes that None.
sys.modules["batch_union"] = bu
_spec.loader.exec_module(bu)

MARKERS = (bu.OURS_MARK, bu.BASE_MARK, bu.MID_MARK, bu.THEIRS_MARK)

# The three landings, by the merge that dropped the line and the rail whose
# assert it was. Kept as data so a fourth shape is one row.
DROPS = [
    ("ci_sprite_game_merge.yml", "patrol", ["patrol", "maze", "sprite_game"]),
    ("ci_stomper_merge.yml", "jumper", ["jumper", "patrol", "stomper"]),
    ("ci_scroll_run_merge.yml", "stomper",
     ["stomper", "sprite_game", "scroll_run"]),
]


def _non_marker_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines()
            if not any(ln.startswith(m) for m in MARKERS)]


def _steps_with_asserts(text: str) -> dict[str, bool]:
    """rail -> does its step end with an assert line?

    Reads the resolved text the way CI does: a step opens at
    `- name: make <rail>` and runs until the next `- name:`. The assert must
    be inside it.
    """
    lines = text.splitlines()
    opens = [(i, ln.split("make ", 1)[1].strip())
             for i, ln in enumerate(lines)
             if ln.strip().startswith("- name: make ")]
    out = {}
    for n, (i, rail) in enumerate(opens):
        end = opens[n + 1][0] if n + 1 < len(opens) else len(lines)
        body = lines[i:end]
        out[rail] = any('test "$size" -eq 524288' in ln for ln in body)
    return out


# --------------------------------------------------------------------------
# the three recorded drops
# --------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,dropped_rail,rails", DROPS,
                         ids=[d[0].replace(".yml", "") for d in DROPS])
def test_the_union_keeps_every_steps_assert_line(fixture, dropped_rail, rails):
    """The recorded defect, asserted directly on the resolved text."""
    text = (FIXTURES / fixture).read_text()
    assert bu.has_conflict_markers(text), "fixture lost its conflict markers"

    u = bu.union_text(text)
    have = _steps_with_asserts(u.text)

    assert sorted(have) == sorted(rails), (
        f"the union changed which steps exist: {sorted(have)}")
    missing = [r for r, ok in have.items() if not ok]
    assert not missing, (
        f"{fixture}: step(s) {missing} came out of the union with NO "
        f"`test \"$size\" -eq 524288` line — this is the recorded drop "
        f"reproduced ({dropped_rail}'s was the one lost in the real "
        f"landing). A truncated link would pass CI for those rails.")

    # and the count is right: one assert per step, not "plenty of asserts"
    n_asserts = sum(1 for ln in u.text.splitlines()
                    if 'test "$size" -eq 524288' in ln)
    assert n_asserts == len(rails), (
        f"{n_asserts} assert line(s) for {len(rails)} step(s) — the file "
        f"reads as full of asserts either way, which is exactly why the "
        f"real drops survived review")


@pytest.mark.parametrize("fixture,dropped_rail,rails", DROPS,
                         ids=[d[0].replace(".yml", "") for d in DROPS])
def test_the_union_loses_no_line_at_all(fixture, dropped_rail, rails):
    """The arithmetic form: in-multiset == out-multiset, markers aside."""
    text = (FIXTURES / fixture).read_text()
    u = bu.union_text(text)
    assert sorted(_non_marker_lines(text)) == sorted(u.text.splitlines()), (
        "the union is not line-preserving")
    assert u.dropped == 0
    assert u.kept_lines == u.conflict_lines


@pytest.mark.parametrize("fixture,dropped_rail,rails", DROPS,
                         ids=[d[0].replace(".yml", "") for d in DROPS])
def test_the_union_is_ours_then_theirs(fixture, dropped_rail, rails):
    """Order, not just content — a shuffled union is unreviewable."""
    u = bu.union_text(text=(FIXTURES / fixture).read_text())
    assert len(u.hunks) == 1
    h = u.hunks[0]
    body = u.text
    assert "".join(h.ours) in body and "".join(h.theirs) in body
    assert body.index("".join(h.ours)) < body.index("".join(h.theirs))


@pytest.mark.parametrize("fixture,dropped_rail,rails", DROPS,
                         ids=[d[0].replace(".yml", "") for d in DROPS])
def test_the_resolved_fixture_is_valid_yaml(fixture, dropped_rail, rails):
    u = bu.union_text((FIXTURES / fixture).read_text())
    ok, detail = bu.validate(u.text, Path(fixture))
    assert ok, detail
    assert "yaml" in detail


def test_the_conflicted_fixture_is_NOT_valid_yaml():
    """The pair, so the validator is not a constant.

    A validator that returns ok for everything reads exactly like one that
    works. The conflicted input must FAIL the same call the resolved output
    passes.
    """
    text = (FIXTURES / DROPS[0][0]).read_text()
    ok, detail = bu.validate(text, Path("ci.yml"))
    assert not ok, f"conflict markers parsed as YAML: {detail}"


# --------------------------------------------------------------------------
# the resolver's own edges
# --------------------------------------------------------------------------

def test_a_diff3_conflict_drops_the_BASE_and_keeps_both_sides():
    """`|||||||` sections are the common ancestor — text neither side wants."""
    text = ("keep\n<<<<<<< HEAD\nours\n||||||| base\nancestor\n"
            "=======\ntheirs\n>>>>>>> b\ntail\n")
    u = bu.union_text(text)
    assert u.text == "keep\nours\ntheirs\ntail\n"
    assert u.hunks[0].base == ["ancestor\n"]
    assert "ancestor" not in u.text


def test_a_file_with_no_markers_is_returned_byte_identical():
    text = "a\nb\n\nc"                       # no trailing newline on purpose
    u = bu.union_text(text)
    assert u.text == text and u.hunks == []
    assert not bu.has_conflict_markers(text)


def test_an_unclosed_conflict_is_REFUSED_not_guessed():
    with pytest.raises(bu.ConflictError, match="never closed"):
        bu.union_text("a\n<<<<<<< HEAD\nours\n=======\ntheirs\n")


def test_a_theirs_marker_before_any_separator_is_REFUSED():
    with pytest.raises(bu.ConflictError, match="before any"):
        bu.union_text("a\n<<<<<<< HEAD\nours\n>>>>>>> b\n")


def test_nested_conflict_markers_are_REFUSED():
    with pytest.raises(bu.ConflictError, match="do not nest"):
        bu.union_text("<<<<<<< a\nx\n<<<<<<< b\ny\n=======\nz\n>>>>>>> c\n")


def test_the_tool_imports_no_regex_module():
    """The sibling cut from the same landing, made structural.

    A shape-repair pass written with `re.sub` died on `re.error: bad escape`
    because the replacement text ended in `; do \\` — backslashes in a
    replacement string are an escape language, and Makefile / shell / CI text
    is full of them. A landing batch learned "plain str.replace only" and the lesson
    did not survive the first draft, so it is asserted here.
    """
    src = TOOL.read_text()
    assert "import re" not in src and "re.sub(" not in src, (
        "batch_union.py must use plain string operations — no regex "
        "substitution")


# --------------------------------------------------------------------------
# the validation battery
# --------------------------------------------------------------------------

def test_the_battery_picks_a_parser_per_file_kind():
    kinds = {
        "x.py": bu._validate_python,
        "x.yml": bu._validate_yaml,
        "x.yaml": bu._validate_yaml,
        "x.sh": bu._validate_shell,
        "Makefile": bu._validate_makefile,
    }
    for name, fn in kinds.items():
        assert bu.validator_for(Path(name)) is fn, name
    assert bu.validator_for(Path("notes.md")) is None


@pytest.mark.parametrize("name,good,bad", [
    ("x.py", "def f():\n    return 1\n", "def f(:\n"),
    ("x.yml", "a: 1\nb: [2, 3]\n", "a: 1\n  b: :: [\n"),
    ("x.sh", "set -e\nfor i in 1 2; do echo $i; done\n", "if true; then\n"),
])
def test_each_validator_accepts_valid_and_REFUSES_broken(name, good, bad):
    """Both arms, per parser — a validator that never fails is a constant."""
    ok, detail = bu.validate(good, Path(name))
    assert ok, f"{name} rejected valid input: {detail}"
    ok, detail = bu.validate(bad, Path(name))
    assert not ok, f"{name} accepted broken input: {detail}"


def test_the_makefile_validator_runs_make_n_gates():
    """The real Makefile expands; a mis-offset hunk does not.

    The plant is the union damage `make -n` genuinely catches: a fragment
    landed above the first target, which make refuses with "recipe commences
    before first target". Shell syntax inside a recipe body is NOT caught —
    `-n` prints recipe lines rather than running them — and the tool's
    docstring says so rather than letting this test imply otherwise.
    """
    good = (SUPERFORGE / "Makefile").read_text()
    ok, detail = bu.validate(good, Path("Makefile"))
    assert ok, detail
    assert "make -n gates" in detail

    bad = "\techo a stray recipe line\n" + good
    ok, detail = bu.validate(bad, Path("Makefile"))
    assert not ok, f"a mis-offset hunk expanded cleanly: {detail}"
    assert "recipe commences before first target" in detail, detail


def test_validating_a_makefile_does_not_touch_the_repos_build_dir():
    """`-n` IS NOT A DRY RUN when the recipe invokes `$(MAKE)`. Measured.

    GNU make treats any recipe line containing `$(MAKE)` as recursive and
    EXECUTES it even under `-n`, so sub-makes can print their own output. This
    repo's entire `gates:` body is one backslash-continued shell line with
    `$(MAKE)` inside its `run()` helper — so `make -n gates` really runs that
    shell, including `rm -f $(BUILD)/gates_summary.txt` and every
    `printf >>`.

    It cost a 21-minute gate block: this very test, running inside that
    block's own suite, deleted the live `build/gates_summary.txt` and rebuilt
    it, so the final summary read `measure ok` for a gate that had failed
    twenty minutes earlier and carried two `test` rows. The fix is the
    `BUILD=<tmpdir>` command-line override in
    `_validate_makefile` — command-line variables beat the file's assignment
    and propagate to sub-makes through MAKEFLAGS.

    The surface read here is the repo's REAL `build/gates_summary.txt`: its
    bytes (or its absence) must survive a validation. Asserting on the
    override string instead would pass the day someone drops the argument
    but keeps the comment.
    """
    summary = SUPERFORGE / "build" / "gates_summary.txt"
    before = summary.read_bytes() if summary.exists() else None

    ok, detail = bu.validate((SUPERFORGE / "Makefile").read_text(),
                             Path("Makefile"))
    assert ok, detail

    after = summary.read_bytes() if summary.exists() else None
    assert after == before, (
        "validating a Makefile rewrote the repo's build/gates_summary.txt — "
        "the `-n` recursion escape is back. A validation run during a live "
        "`make gates` would corrupt that block's own summary.")


# --------------------------------------------------------------------------
# the ci.yml STEP SHAPE — the drop that loses no line
# --------------------------------------------------------------------------
#
# The three fixtures above are LOST-LINE conflicts and the arithmetic contract
# stops them. A landing batch produced the other half of the class: `an earlier
# commit inserted `split_v_seamtrial`'s `- name:` between `svd-nowin`'s `echo`
# and its `test "$size" -eq 524288`, so the assert MOVED into the following
# step. Every line survived, the count matched, the YAML parsed, `make
# rail-registered` was green (its ci.yml site was rail-scoped and `svd-nowin`
# is a variant target), and `build/svd_nowin.sfc`'s 524,288 bytes were asserted
# NOWHERE — bare_check's size list was rail-scoped too (the recorded drop).
# Fifth instance across waves, first uncaught.
#
# Gate-time cover was restored on 2026-08-23 by derivation rather than by a
# shape check: bare_check.sh measures every `build/*.sfc` against its own
# header and demands a set derived from `make gates`'s run-list, so
# `svd_nowin` is measured and its absence is named (docs/44 §7). These cases
# still hold the UNION-time half, which is the half that fires before a
# commit exists.
#
# Test surface: the tool's own verdict over the two shapes the defect really
# takes — the resolved file a landing-side hand repair leaves behind (no
# markers), and a conflict whose keep-both union reaches the same shape while
# losing nothing. The assertion reads the STEP NAME the validator reports, not
# a boolean: a check that fired on the wrong step would satisfy a boolean.

MOVED_RESOLVED = "ci_svd_nowin_f1.yml"
MOVED_CONFLICT = "ci_svd_nowin_absorbed_conflict.yml"


def test_the_real_batch4_f1_file_is_REFUSED():
    """The audit's own diff, as a file. The validator must name svd-nowin."""
    text = (FIXTURES / MOVED_RESOLVED).read_text()
    assert not bu.has_conflict_markers(text), "fixture is already resolved"

    # the parse-only reading passes it — which is the whole finding
    import yaml
    assert yaml.safe_load(text) is not None

    ok, detail = bu.validate(text, Path("ci.yml"))
    assert not ok, (
        f"the recorded drop's own file passed the battery — the parse-only reading "
        f"is exactly what shipped it:\n{detail}")
    assert "make svd-nowin" in detail, detail
    assert "build/svd_nowin.sfc" in detail, detail
    # and it must not blame the step that ABSORBED the assert
    assert "`make split_v_seamtrial` stats" not in detail, detail
    assert "1 of 4 ROM step(s)" in detail, detail


def test_the_absorbed_assert_survives_the_arithmetic_and_is_still_REFUSED():
    """A union that loses NO line can still produce the defect.

    This is the fixture that separates the two contracts: the line count is
    preserved, `u.dropped == 0`, every input line is in the output — and the
    result is broken, because the question is which BLOCK the line landed in.
    """
    text = (FIXTURES / MOVED_CONFLICT).read_text()
    u = bu.union_text(text)

    # arithmetic: clean, by the tool's own contract
    assert u.dropped == 0 and u.kept_lines == u.conflict_lines
    assert sorted(_non_marker_lines(text)) == sorted(u.text.splitlines())

    # semantics: broken, and named
    ok, detail = bu.validate(u.text, Path("ci.yml"))
    assert not ok, (
        f"the union preserved every line and produced a step that builds a "
        f"ROM it never asserts — and the battery passed it:\n{detail}")
    assert "make svd-nowin" in detail, detail

    # the residue that makes it reviewable: seamtrial now carries TWO asserts,
    # which is the tool's declared bias (duplicate = visible nuisance) and the
    # signpost a human follows back to the missing one
    steps = dict((name, roms) for name, roms, ok_ in bu.ci_rom_steps(u.text)
                 if not ok_)
    assert list(steps) == ["make svd-nowin"], steps
    assert u.text.count('test "$size" -eq 524288') == 4


# The positive arm used to be a separate test that ran the shape check over
# the repo's own `.github/workflows/ci.yml` and asserted it found more than 20
# ROM steps. That file was deleted on 2026-08-22 when the hosted workflow was
# retired, and there is no whole-workflow text left in this repository to read.
# The pair property — a check that refuses everything reads like one that works
# — is still carried by the test below, which runs the same check over three
# real ci.yml-shaped unions and requires ok on all of them. What is gone is the
# reach assertion: nothing now shows the check scaling past a three-step
# excerpt.


def test_the_three_recorded_drop_fixtures_still_pass_the_shape_check():
    """The new check must not red the fixtures the old contract already fixes.

    Their unions are correct; a shape check that also complained about them
    would be measuring the fixture, not the defect.
    """
    for fixture, _, _ in DROPS:
        u = bu.union_text((FIXTURES / fixture).read_text())
        ok, detail = bu.ci_step_shape(u.text)
        assert ok, f"{fixture}: {detail}"


def test_an_assert_above_its_stat_is_not_credited():
    """Order, not just presence.

    A union aligned one line differently can park the assert ABOVE the stat
    that sets `$size`. The step then dies on an unset variable rather than on
    a size mismatch — still broken, and a presence-only check calls it fine.
    """
    good = ("jobs:\n  g:\n    steps:\n"
            "      - name: make racer\n        run: |\n"
            "          make racer\n"
            "          size=$(stat -c%s build/racer.sfc)\n"
            '          test "$size" -eq 524288 || exit 1\n')
    bad = ("jobs:\n  g:\n    steps:\n"
           "      - name: make racer\n        run: |\n"
           "          make racer\n"
           '          test "$size" -eq 524288 || exit 1\n'
           "          size=$(stat -c%s build/racer.sfc)\n")
    assert bu.ci_step_shape(good)[0], bu.ci_step_shape(good)[1]
    ok, detail = bu.ci_step_shape(bad)
    assert not ok, "an assert that runs BEFORE its stat was credited"
    assert "make racer" in detail


def test_a_yaml_with_no_rom_steps_is_not_a_finding():
    """Scope. The battery runs on every `.yml` a landing conflicts, and most
    of them build nothing — a check that demanded asserts there would be
    noise, and noise is how a gate gets ignored."""
    ok, detail = bu.ci_step_shape("a: 1\nb: [2, 3]\n")
    assert ok and "no ROM-building steps" in detail


def test_a_step_that_never_stats_is_not_a_finding():
    """The stated hole, asserted so it stays a KNOWN one.

    `probe_cpu md5` builds a ROM and pins its bytes with md5sum, which is
    strictly stronger than a size assert. It stats nothing, so this check
    cannot see it — and must not invent a finding about it.
    """
    step = ("jobs:\n  g:\n    steps:\n"
            "      - name: probe_cpu md5\n        run: |\n"
            "          make build/probe_cpu.sfc\n"
            "          actual=$(md5sum build/probe_cpu.sfc | cut -d' ' -f1)\n"
            '          test "$actual" = "11e9" || exit 1\n')
    ok, detail = bu.ci_step_shape(step)
    assert ok and "no ROM-building steps" in detail


def test_a_parse_failure_is_reported_ahead_of_the_shape():
    """A file that does not parse has no reviewable step shape.

    Reporting the shape finding first would send a reader to move an assert
    line in a file whose real problem is a stray marker.
    """
    broken = ("jobs: :: [\n"
              "      - name: make racer\n        run: |\n"
              "          make racer\n"
              "          size=$(stat -c%s build/racer.sfc)\n")
    ok, detail = bu.validate(broken, Path("ci.yml"))
    assert not ok
    assert detail.startswith("yaml.safe_load:"), detail
    assert "step shape" not in detail, detail


# --------------------------------------------------------------------------
# the CLI — the surface a batch integrator actually runs
# --------------------------------------------------------------------------

def run_cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(TOOL), *args],
                          cwd=cwd or SUPERFORGE, capture_output=True, text=True,
                          timeout=300)


def test_check_mode_writes_nothing(tmp_path):
    src = FIXTURES / DROPS[0][0]
    work = tmp_path / "ci.yml"
    shutil.copy2(src, work)
    before = work.read_bytes()
    r = run_cli("--check", str(work))
    assert r.returncode == 0, r.stdout + r.stderr
    assert work.read_bytes() == before, "--check wrote to the file"
    assert "batch_union (check)" in r.stdout
    assert "1 hunk(s)" in r.stdout


def test_write_mode_resolves_the_file_and_reports_it(tmp_path):
    work = tmp_path / "ci.yml"
    shutil.copy2(FIXTURES / DROPS[1][0], work)
    r = run_cli(str(work))
    assert r.returncode == 0, r.stdout + r.stderr
    out = work.read_text()
    assert not bu.has_conflict_markers(out), "markers survived the union"
    assert all(_steps_with_asserts(out).values())
    assert "written" in r.stdout
    assert "git checkout --merge" in r.stdout


def test_the_cli_always_prints_the_rail_registered_reminder(tmp_path):
    """A parse is not a registration, and the tool says so every run.

    The three drops were caught by `make rail-registered`, not by any parse —
    a green verdict here must not read as "the landing is wired".
    """
    work = tmp_path / "ci.yml"
    shutil.copy2(FIXTURES / DROPS[2][0], work)
    for args in (["--check", str(work)], [str(work)]):
        r = run_cli(*args)
        assert "make rail-registered" in r.stdout, r.stdout


def test_the_cli_exits_nonzero_when_a_validator_fails(tmp_path):
    work = tmp_path / "broken.py"
    work.write_text("<<<<<<< HEAD\ndef f(:\n=======\ndef g(:\n>>>>>>> b\n")
    r = run_cli("--check", str(work))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout


def test_the_cli_REFUSES_a_malformed_conflict_rather_than_writing(tmp_path):
    work = tmp_path / "half.yml"
    work.write_text("a: 1\n<<<<<<< HEAD\nb: 2\n=======\nc: 3\n")
    before = work.read_bytes()
    r = run_cli(str(work))
    assert r.returncode == 1
    assert "REFUSED" in r.stderr
    assert work.read_bytes() == before


def test_the_cli_fails_on_the_batch4_f1_file(tmp_path):
    """The surface that would have caught it: `--check` on the landed file.

    The real drop was a landing-side hand repair, so by the time anyone could
    look there were no markers left. `--check` runs the battery on an
    unconflicted file too — this asserts the exit status a landing integrator
    would actually have seen.
    """
    work = tmp_path / "ci.yml"
    shutil.copy2(FIXTURES / MOVED_RESOLVED, work)
    before = work.read_bytes()
    r = run_cli("--check", str(work))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout, r.stdout
    assert "make svd-nowin" in r.stdout, r.stdout
    assert work.read_bytes() == before, "--check wrote to the file"
