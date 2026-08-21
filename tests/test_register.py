"""The feature register's agreement gate.

The surface under test is `tools/gen_register.py` and the `role` field it made
necessary. Every test here PLANTS a real change and asserts the gate goes red,
because a gate that has only ever been observed green is not a gate -- and this
change's whole subject is a document that agreed with itself four times while
disagreeing with the tree.

Two things are asserted that are easy to conflate:

  * the CENSUS agreement -- the generated block vs the tree. Plants: a new dir,
    a changed claim class, a changed role, a new depends edge, and a hand edit
    inside the generated region.
  * the BOUNDARY -- a hand edit OUTSIDE a generated region must stay GREEN.
    Without this, "the gate is red" proves nothing about what it owns.
"""
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

# Every plant here writes into THIS repo's working tree, because the tree is
# the subject: a copy is not the census `make register` checks. So every test
# holds the repo-tree lock (tests/conftest.py) — two `planted_text` windows
# overlapping on one file restore each other's PLANT, which is not a flake
# but a wrong row written into a tracked doc.
pytestmark = pytest.mark.usefixtures("repo_tree_lock")

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "tools"))
sys.path.insert(0, str(SUPERFORGE))

import gen_register as G                                          # noqa: E402
from allocator.schemas import SchemaError, load_feature, load_substrate  # noqa: E402

FEATURES = SUPERFORGE / "engine" / "features"
REGISTER = SUPERFORGE / "docs" / "09_feature_register.md"


def run_check() -> subprocess.CompletedProcess:
    """The gate exactly as CI and a human run it (`make register`)."""
    return subprocess.run([sys.executable, "tools/gen_register.py", "--check"],
                          cwd=SUPERFORGE, capture_output=True, text=True)


@contextmanager
def planted_text(path: Path, new: str):
    original = path.read_text()
    try:
        path.write_text(new)
        yield
    finally:
        path.write_text(original)


@contextmanager
def planted_dir(name: str, toml: str):
    d = FEATURES / name
    assert not d.exists(), f"{name} already exists -- pick another plant name"
    try:
        d.mkdir()
        (d / "feature.toml").write_text(toml)
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------
# the baseline: green, and idempotent
# --------------------------------------------------------------------------

def test_committed_register_agrees_with_the_tree():
    r = run_check()
    assert r.returncode == 0, f"make register is already red:\n{r.stderr}"


def test_write_is_idempotent():
    """--write on an up-to-date doc must not touch a byte."""
    before = REGISTER.read_bytes()
    r = subprocess.run([sys.executable, "tools/gen_register.py", "--write"],
                       cwd=SUPERFORGE, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert REGISTER.read_bytes() == before, "--write mutated an up-to-date doc"


# --------------------------------------------------------------------------
# census plants -- one test each
# --------------------------------------------------------------------------

def test_plant_new_feature_dir_is_caught():
    """A new dir must move the CENSUS specifically.

    The plant also adds the §3.1 serves row it would need, so the serves-key
    check stays quiet and this test can only pass through the census diff.
    Without that, it passed with the census comparison stubbed out -- firing
    through the wrong mechanism while claiming to test this one.
    """
    text = REGISTER.read_text()
    with planted_dir("zz_plant", 'name = "zz_plant"\nrole = "feature"\n\n'
                                 '[[claims.dp]]\nname = "zz_plant_v"\nbytes = 2\n'), \
         planted_text(REGISTER, text.replace(
             _serves_row(text, "tad_rom"),
             _serves_row(text, "tad_rom")
             + "\n| `zz_plant` | a planted dir |", 1)):
        r = run_check()
    assert r.returncode == 1, "a new feature dir did not move the census"
    assert "the committed census disagrees with the tree" in r.stderr, \
        f"red, but not through the census diff:\n{r.stderr}"
    assert "zz_plant" in r.stderr


def test_plant_undeclared_feature_dir_is_caught():
    """A dir with sources and NO feature.toml must be REFUSED, not uncounted.

    The census is built from feature.toml FILES, while the sentence it
    generates counts DIRS ("All N dirs under `engine/features/` accounted
    for") and so does `make register`'s OK line. Those two used to be able to
    disagree in silence: `docs/audit/region_r0-audit-1.md` 3.2 planted exactly
    this shape -- a directory holding an .asm and no declaration -- put 158
    dirs on disk, and the gate printed `census matches the tree (157 dirs)`
    and exited 0. A half-created feature is precisely what this gate exists to
    catch, and it is the mechanism behind paper cut #4.

    `--write` is asserted alongside `--check` because the escape hatch would
    otherwise be to regenerate: a census cannot be truthfully rewritten while
    a dir it claims to account for has nothing to account.
    """
    d = FEATURES / "zz_half_made"
    assert not d.exists(), "pick another plant name"
    before = REGISTER.read_bytes()
    try:
        d.mkdir()
        (d / "half.asm").write_text("; sources present, declaration absent\n")
        on_disk = sum(1 for q in FEATURES.iterdir() if q.is_dir())
        r = run_check()
        w = subprocess.run([sys.executable, "tools/gen_register.py", "--write"],
                           cwd=SUPERFORGE, capture_output=True, text=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    assert r.returncode == 1, (
        f"{on_disk} dirs on disk and --check said OK -- an undeclared feature "
        f"dir is uncounted AND unreported:\n{r.stdout}{r.stderr}")
    assert "zz_half_made" in r.stderr, \
        f"refused, but does not name the dir:\n{r.stderr}"
    assert "no feature.toml" in r.stderr, \
        f"refused, but not for the missing declaration:\n{r.stderr}"
    assert w.returncode == 1, "--write regenerated a census over an undeclared dir"
    assert REGISTER.read_bytes() == before, "--write mutated the doc anyway"


def test_plant_changed_claim_class_is_caught():
    p = FEATURES / "fade" / "feature.toml"
    with planted_text(p, p.read_text().replace("[[claims.dp]]", "[[claims.wram]]", 1)):
        r = run_check()
    assert r.returncode == 1, "a changed claim class did not move the census"
    assert "the committed census disagrees with the tree" in r.stderr, r.stderr
    assert "wram" in r.stderr and "fade" in r.stderr


def test_plant_changed_role_is_caught():
    p = FEATURES / "car_rom" / "feature.toml"
    with planted_text(p, p.read_text().replace('role = "blob"',
                                               'role = "companion"', 1)):
        r = run_check()
    assert r.returncode == 1, "a changed role did not move the census"
    assert "the committed census disagrees with the tree" in r.stderr, r.stderr
    assert "companion" in r.stderr and "car_rom" in r.stderr


def test_plant_new_depends_edge_is_caught():
    p = FEATURES / "fade" / "feature.toml"
    with planted_text(p, p.read_text().replace('role = "feature"',
                                               'role = "feature"\ndepends = ["input"]', 1)):
        r = run_check()
    assert r.returncode == 1, "a new depends edge did not move the census"
    assert "the committed census disagrees with the tree" in r.stderr, r.stderr
    assert "input" in r.stderr and "fade" in r.stderr


def test_plant_hand_edit_INSIDE_generated_region_is_caught():
    """The actual drift case, and the one that has bitten four times."""
    text = REGISTER.read_text()
    assert "| `vwf` | **feature** |" in text
    with planted_text(REGISTER, text.replace("| `vwf` | **feature** |",
                                             "| `vwf` | **blob** |", 1)):
        r = run_check()
    assert r.returncode == 1, "a hand edit inside the generated region survived"
    assert "the committed census disagrees with the tree" in r.stderr, r.stderr


def _serves_row(text, key):
    """The CURRENT full text of a hand-owned §3.1 row, found by its key.

    Tests that plant edits into hand-owned prose must derive the needle from
    the file at runtime -- a hardcoded row literal goes stale the moment an
    author rewords the row, which is the very edit §3.1 exists to permit
    (learned the hard way on a landing)."""
    # The key also heads the dir's row in §3's GENERATED census table
    # ("| `key` | **role** | unused | ..."); the serves row is the match
    # WITHOUT a scope cell, so filter the census shape out rather than
    # taking the first hit (the first hit IS the census, and editing it
    # turns the gate legitimately red -- the wrong-row trap this helper's
    # first draft fell into).
    return next((l for l in text.splitlines()
                 if l.startswith(f"| `{key}` |")
                 and "| unused |" not in l and "| scene |" not in l), None)


def test_plant_hand_edit_OUTSIDE_generated_region_stays_green():
    """The boundary. Without this the suite proves only that SOMETHING is red.

    §3.1 is hand-owned prose; rewording it must not trip the gate, or authors
    learn that the doc is machine property and stop editing the half that is
    theirs.
    """
    text = REGISTER.read_text()
    # The row is found by KEY at runtime, not hardcoded: the old literal
    # needle ("| `split_band` | SPLIT |") went stale when a later sweep
    # legitimately reworded that hand-owned row -- exactly the edit this
    # test exists to keep green -- and turned a landing bare-check RED
    # (2026-08-07). A needle on hand-owned prose must follow the prose.
    old = _serves_row(text, "tad_rom")
    assert old is not None, "the §3.1 row this test edits has moved"
    with planted_text(REGISTER, text.replace(
            old, "| `tad_rom` | a reworded hand-owned serves entry |", 1)):
        r = run_check()
    assert r.returncode == 0, (
        "a hand edit OUTSIDE the generated region turned the gate red -- the "
        f"boundary leaks:\n{r.stderr}")


def test_generated_region_count_tracks_the_tree():
    """§3's heading count is generated, because "all 20 dirs" over a 25-row
    table (5782ed1) is one of the four instances.

    The expected number is READ FROM THE TREE and incremented, not written
    down. An earlier version asserted "**All 26 dirs" — correct on the day,
    and a guaranteed failure for the next change that adds a feature (one
    feature batch added six and turned it red). A test that enforces "counts must follow
    the tree" while hardcoding a count is asserting the opposite of its own
    subject, and this repo has the lesson on file: state counts from
    commands, never from documents."""
    before = len(G.load_tree()[0])
    with planted_dir("zz_count", 'name = "zz_count"\nrole = "blob"\n\n'
                                 '[[claims.rom]]\nname = "zz_count_b"\nbytes = 16\n'):
        fresh = G.generate(REGISTER.read_text())
    assert f"**All {before + 1} dirs" in fresh, (
        f"the heading count did not follow the tree: expected "
        f"{before + 1} dirs after planting one on top of {before}")


# --------------------------------------------------------------------------
# §3.1's key set -- the hand-owned table's only machine-checked property
# --------------------------------------------------------------------------

def test_new_dir_without_a_serves_entry_is_caught():
    with planted_dir("zz_serves", 'name = "zz_serves"\nrole = "feature"\n\n'
                                  '[[claims.dp]]\nname = "zz_serves_v"\nbytes = 2\n'):
        dirs = set(G.load_tree()[0])
        problems = G.check_serves_table(REGISTER.read_text(), dirs)
    assert any("zz_serves" in p and "§3.1" in p for p in problems), problems


def test_stale_serves_entry_for_a_deleted_dir_is_caught():
    text = REGISTER.read_text()
    with planted_text(REGISTER, text.replace(
            _serves_row(text, "tad_rom"),
            _serves_row(text, "tad_rom")
            + "\n| `zz_ghost` | a dir that is not there |", 1)):
        problems = G.check_serves_table(REGISTER.read_text(),
                                        set(G.load_tree()[0]))
    assert any("zz_ghost" in p for p in problems), problems


# --------------------------------------------------------------------------
# the demand-half lint -- prose read, never written
# --------------------------------------------------------------------------

def test_lint_catches_a_citation_of_a_dir_that_does_not_exist():
    dirs = set(G.load_tree()[0])
    problems = G.lint_text("x.md", "see `engine/features/no_such_dir` for this",
                           dirs)
    assert any("no_such_dir" in p for p in problems), problems


def test_lint_ignores_struck_through_history_rows():
    """docs/09 deliberately KEEPS predictions that were checked, struck
    through. Those must not read as live claims or the gate punishes the
    record-keeping it wants."""
    dirs = set(G.load_tree()[0])
    live = "| **col_map** | not built | x |"
    history = "| ~~**col_map**~~ **BUILT** | was: not built | x |"
    assert G.lint_text("x.md", live, dirs), "the live claim should fire"
    assert not G.lint_text("x.md", history, dirs), "history should not fire"


def test_a_strike_alone_does_not_silence_a_live_claim():
    """`~~` exempted ANY row, so wrapping a live subject in
    strikethrough hid it. The exemption now needs a paired affirmative marker.

    The marker match must be CASE-SENSITIVE, and this test is why: written
    with re.I, `\\bBUILT\\b` matches the lower-case 'built' inside 'not built',
    so the exemption fires on precisely the rows it exists to exclude. That
    bug was in the first cut of this fix and this assertion is what caught it.
    """
    dirs = set(G.load_tree()[0])
    struck_only = "| ~~**col_map**~~ | `col_map` | not built |"
    assert G.lint_text("x.md", struck_only, dirs), (
        "a bare strikethrough silenced a live 'not built' claim")


# --- the demand-alias rows: the 17%-reach finding -------------
#
# The lint used to resolve a row ONLY through its subject term, which reached
# the three dirs whose demand term is spelled like the dir (VWF, col_map,
# input) and nothing else. Rows are now ALSO resolved through their supplier
# column, which is where the demand-term -> dir map already lives.

ALIAS_ROWS = [
    # (demand term as written, the dir that supplies it, supplier cell)
    ("GRAD", "rgb_gradient", "`rgb_gradient`"),
    ("STREAM", "mode7_stream", "`mode7_stream`"),
    ("SPLIT", "split_band", "`split_band`"),
    ("SPR", "oam_sprites", "`oam_sprites`"),
    ("TXT", "bg_text", "`bg_text`"),
    ("M7", "mode7_floor", "`mode7_floor`"),
    ("fades", "fade", "`fade`"),
    ("scene flow", "scene_mgr", "`scene_mgr`"),
]


@pytest.mark.parametrize("term,dirname,supplier", ALIAS_ROWS)
def test_lint_reaches_rows_whose_demand_term_is_not_the_dir_name(
        term, dirname, supplier):
    """Every one of these was GREEN before the widening."""
    dirs = set(G.load_tree()[0])
    assert dirname in dirs, f"{dirname} is not a dir any more"
    table = ("| demand | supplied by | status |\n"
             "|---|---|---|\n"
             f"| **{term}** | {supplier} | not built |")
    problems = G.lint_text("x.md", table, dirs)
    assert any(dirname in p for p in problems), (
        f"'{term}' claimed not-built while engine/features/{dirname}/ exists, "
        f"and the lint stayed silent: {problems}")


def test_lint_resolves_the_supplier_column_by_NAME_not_position():
    """docs/09 §1.1 and §1.2 do not share a column order -- §1.2 interposes
    `provenance`. A positional 'second cell' rule reads provenance as the
    supplier and misses the whole of §1.2."""
    dirs = set(G.load_tree()[0])
    like_1_2 = ("| demand | provenance | supplied by | status |\n"
                "|---|---|---|---|\n"
                "| **GRAD** | vendored material | `rgb_gradient` | not built |")
    assert any("rgb_gradient" in p for p in G.lint_text("x.md", like_1_2, dirs))


def test_lint_does_not_fire_on_a_dir_merely_MENTIONED_by_an_unbuilt_row():
    """The widening must not become a false-positive machine. OBJ-HUD is
    genuinely not built and legitimately mentions `oam_sprites`, which
    exists -- resolution is restricted to the supplier column for this."""
    dirs = set(G.load_tree()[0])
    row = ("| demand | supplied by | claim classes | status |\n"
           "|---|---|---|---|\n"
           "| **OBJ-HUD** | &mdash; | oam slots on top of `oam_sprites` | "
           "not built |")
    assert not G.lint_text("x.md", row, dirs), \
        "a true 'not built' fired because the row mentioned an existing dir"


@pytest.mark.parametrize("phrase", [
    "unimplemented", "TODO", "pending", "not yet built", "unbuilt",
    "no supplier exists", "not implemented", "❌",
])
def test_lint_knows_the_not_built_synonyms(phrase):
    """The 27-form sweep found all of these silent."""
    dirs = set(G.load_tree()[0])
    table = ("| demand | supplied by | status |\n"
             "|---|---|---|\n"
             f"| **GRAD** | `rgb_gradient` | {phrase} |")
    assert any("rgb_gradient" in p for p in G.lint_text("x.md", table, dirs)), \
        f"'{phrase}' is not recognised as a not-built claim"


def test_lint_accepts_an_unbolded_subject_cell():
    """A demand row's subject cell may carry no bold at all; requiring
    `**bold**` excluded real rows on typography."""
    dirs = set(G.load_tree()[0])
    table = ("| collider | state |\n"
             "|---|---|\n"
             "| Mode 7 streaming | ❌ not started — `engine/features/mode7_stream` |")
    assert any("mode7_stream" in p for p in G.lint_text("x.md", table, dirs))


def test_reach_is_reported_and_is_the_measured_ratio():
    """`make register` must state what it CHECKED, not only what it found.

    Floors, not equalities, so adding a demand row does not fail the suite --
    but a REGRESSION in the mechanism does.

    THE TOTAL HAS MOVED BEFORE (30 -> 25), AND A MOVE IS NOT A REGRESSION.
    The lint reads the LIVE demand surface — docs/09's demand tables, 25
    rows today. A demand table whose last row ships can be retired to a
    frozen record, and a frozen record is deliberately NOT linted: it is
    *supposed* to contain claims like "not started", and linting it would
    fight the record rather than catch drift. So 25 is the live surface now.

    Reach went 20/30 -> 15/25 in one such retirement: every retired row
    named a dir and was reachable, so the ratio moved (67% -> 60%) only
    because docs/09's unreachable rows became a larger share. A later review
    measured 5/30 before the widening.

    If this floor fails again, check FIRST whether a demand surface was archived
    or renamed before lowering the number -- the guard exists to catch the
    mechanism silently finding nothing, and lowering it thoughtlessly is how it
    stops doing that.
    """
    reached, total = G.reach_report(set(G.load_tree()[0]))
    assert total >= 25, f"the demand tables stopped being found: {total} rows"
    assert reached >= 15, (
        f"demand-lint reach regressed to {reached}/{total}; a later review measured "
        f"5/30 before the widening, 20/30 after, and 15/25 once the design's "
        f"collider table was archived")


def test_the_known_limit_is_real_and_documented():
    """Honesty check: a row with no supplier and a non-dir demand term is NOT
    reachable, and lint_text says so rather than implying full coverage.

    THE EXAMPLE TERM IS LOAD-BEARING AND PERISHABLE. It has to be a demand
    term no `engine/features/` dir is spelled like, and that set SHRINKS every
    time a feature debuts: this case used `POOL` until 2026-08-08, when
    a later change shipped `engine/features/pool/` and the subject cell started
    resolving -- so the lint correctly flagged the row and the assertion went
    red. Measuring the alternatives then showed `SAVE` had gone the same way
    at C2 and nobody had noticed, because only one of them was in the fixture.

    So the second assertion below is the durable half: whatever term is used,
    it must genuinely be unreachable TODAY. If this goes red again, the fix is
    to pick another still-unreachable term (and to strike the graduated one
    from lint_text's KNOWN LIMIT list, which is the thing readers quote), not
    to relax the assertion.

    EVERY LISTED TERM IS GUARDED, NOT JUST THE FIXTURE'S. That is the whole
    lesson of the `SAVE` miss: the guard covered the one term the fixture
    happened to use, so the other listed examples could graduate in silence and
    the doc readers quote kept naming them. `AUD` drives the lint below because
    a fixture needs one term; all three are asserted unreachable, and the
    docstring is required to still name them so the tuple here and the prose
    there cannot drift apart."""
    dirs = set(G.load_tree()[0])
    listed = ("AUD", "OBJ-HUD", "GRAD")
    graduated = [t for t in listed if t.lower() in dirs]
    assert not graduated, (
        f"{', '.join(graduated)} now name(s) a dir -- strike the graduated "
        "term(s) from lint_text's KNOWN LIMIT list AND from gen_register's "
        "module header, and pick another unreachable term if the fixture's "
        "own term is among them")
    doc = G.lint_text.__doc__
    missing = [t for t in listed if t not in doc]
    assert not missing, (
        f"lint_text's KNOWN LIMIT no longer names {', '.join(missing)} -- this "
        "tuple mirrors that list, so update both together")

    term = listed[0]
    table = ("| demand | supplied by | status |\n"
             "|---|---|---|\n"
             f"| **{term}** | &mdash; | not built |")
    assert not G.lint_text("x.md", table, dirs)
    assert "KNOWN LIMIT" in doc


def test_lint_is_read_only():
    """--write must not touch the prose half even when it is contradictory."""
    text = REGISTER.read_text()
    bad = text.replace("## 5. What each unbuilt feature would need",
                       "## 5. What each unbuilt feature would need\n\n"
                       "| **vwf** | needs building | no |", 1)
    with planted_text(REGISTER, bad):
        r = subprocess.run([sys.executable, "tools/gen_register.py", "--write"],
                           cwd=SUPERFORGE, capture_output=True, text=True)
        after = REGISTER.read_text()
    assert r.returncode == 1, "--write ignored a prose contradiction"
    assert "| **vwf** | needs building | no |" in after, \
        "--write rewrote hand-owned prose"


# --------------------------------------------------------------------------
# the schema half -- role as a declaration
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sub():
    return load_substrate(SUPERFORGE / "allocator" / "substrate.toml")


def _write(tmp_path, body) -> Path:
    d = tmp_path / "widget"
    d.mkdir()
    p = d / "feature.toml"
    p.write_text(body)
    return p


def test_missing_role_is_refused(tmp_path, sub):
    p = _write(tmp_path, 'name = "widget"\n\n[[claims.dp]]\nname = "w"\nbytes = 2\n')
    with pytest.raises(SchemaError, match="missing required key 'role'"):
        load_feature(p, sub)


def test_unknown_role_is_refused_and_teaches(tmp_path, sub):
    p = _write(tmp_path, 'name = "widget"\nrole = "supplier"\n\n'
                         '[[claims.dp]]\nname = "w"\nbytes = 2\n')
    with pytest.raises(SchemaError) as e:
        load_feature(p, sub)
    msg = str(e.value)
    assert "supplier" in msg
    # the error must restate the vocabulary, not just refuse
    for role in ("feature", "blob", "companion", "consumer", "game_logic",
                 "fixture"):
        assert role in msg, f"the error does not name '{role}'"


def test_every_declared_role_loads(tmp_path, sub):
    for i, role in enumerate(G.FEATURE_ROLES):
        d = tmp_path / f"w{i}"
        d.mkdir()
        p = d / "feature.toml"
        p.write_text(f'name = "w{i}"\nrole = "{role}"\n\n'
                     f'[[claims.dp]]\nname = "w{i}v"\nbytes = 2\n')
        assert load_feature(p, sub).role == role


def test_fixture_role_inside_engine_features_is_refused():
    """The `fixture` role is what keeps the census scope honest, so its
    placement rule is enforced rather than conventional."""
    with planted_dir("zz_fixture", 'name = "zz_fixture"\nrole = "fixture"\n\n'
                                   '[[claims.dp]]\nname = "zz_f"\nbytes = 2\n'):
        with pytest.raises(G.RegisterError, match="fixture"):
            G.load_tree()


def test_non_fixture_role_outside_engine_features_is_refused():
    p = SUPERFORGE / "engine" / "toy" / "feat_a" / "feature.toml"
    with planted_text(p, p.read_text().replace('role = "fixture"',
                                               'role = "feature"', 1)):
        with pytest.raises(G.RegisterError, match="outside engine/features"):
            G.load_tree()


def _dup_sandbox(root: Path, probe_name: str) -> tuple[Path, Path]:
    """A real two-feature tree on disk, in the shape load_tree() scans.

    `engine/features/vwf/` is the incumbent and sorts first; the probe lives
    outside the census dir (so `fixture` is the role its placement demands)
    and sorts second, which is the ordering that made the silent overwrite
    aim at the wrong file. `probe_name` is the only variable: pass "vwf" for
    the collision, anything else for the control.
    """
    real = root / "engine" / "features" / "vwf"
    real.mkdir(parents=True)
    (real / "feature.toml").write_text(
        'name = "vwf"\nrole = "feature"\n\n'
        '[[claims.dp]]\nname = "zz_real_v"\nbytes = 2\n')
    probe = root / "vendor" / "probes" / "zz_dup_probe" / probe_name
    probe.mkdir(parents=True)
    (probe / "feature.toml").write_text(
        f'name = "{probe_name}"\nrole = "fixture"\n\n'
        f'[[claims.dp]]\nname = "zz_dup_v"\nbytes = 2\n')
    game = root / "game" / "microzero"
    game.mkdir(parents=True)
    (game / "game.toml").write_text(
        'globals = ["vwf"]\n\n[[scene]]\nid = "s"\nfeatures = []\n')
    return real / "feature.toml", probe / "feature.toml"


def test_duplicate_feature_name_is_refused_not_clobbered(tmp_path):
    """`everything[d.name] = d` over a repo-wide glob overwrote
    silently, so a probe declaring name = "vwf" rewrote the real vwf's census
    row and the tool reported CENSUS DRIFT — a true-looking diff aimed at the
    wrong file.

    The collision can only be cross-tree: `load_feature` already requires
    name == directory name, so two dirs under engine/features/ cannot share a
    name. A probe dir named `vwf` outside engine/features/ can, and sorts
    after it, so it lands second and did the overwriting.

    ISOLATED, a later review. This used to plant the probe inside THIS repo, and
    `load_tree()` globs the repo it is asked for — so for the length of the
    window every one of this module's other 17 `load_tree()` callers raised
    the same RegisterError about a file that was fine. Under `-n 3` that is a
    red 1 full-suite run in 3, pointing at `gen_register.py`, where there is
    nothing wrong. The tree here is still real and still on disk and is still
    scanned by the real `load_tree()`; it is simply not the one every other
    test is standing on.
    """
    real_toml, probe_toml = _dup_sandbox(tmp_path, "vwf")

    with pytest.raises(G.RegisterError, match="duplicate feature name") as e:
        G.load_tree(repo=tmp_path)

    # "refused, not clobbered" is only half the property. The damage was a
    # diagnostic aimed at the WRONG FILE, so the refusal has to name both the
    # loser and the incumbent it lost to.
    msg = str(e.value)
    assert str(probe_toml) in msg, \
        f"the refusal does not name the colliding declaration:\n{msg}"
    assert str(real_toml) in msg, \
        f"the refusal does not name the incumbent it collided with:\n{msg}"


def test_the_duplicate_sandbox_loads_when_the_names_differ(tmp_path):
    """Non-vacuity for the test above: the SAME sandbox, one name changed,
    must load. Without this, a sandbox that fails to build at all would still
    satisfy `pytest.raises(RegisterError)` for a reason that has nothing to
    do with duplicate names — the tmp-tree version of asserting on a proxy."""
    _dup_sandbox(tmp_path, "zz_dup_probe_unique")

    census, scope = G.load_tree(repo=tmp_path)

    assert set(census) == {"vwf"}, (
        "the census must hold engine/features/ dirs only — the probe is "
        f"outside it and must not be counted: {sorted(census)}")
    assert scope["vwf"] == "global", scope


def test_companion_gloss_discriminates_against_blob():
    """the gloss is the field's teaching surface (the SchemaError
    reprints it), and the old wording — "holds claims on behalf of shared
    top-level code" — was satisfied by every *_rom blob, which is how
    col_map_rom was mislabelled a companion in docs/09 §1.2 for a week."""
    gloss = G.FEATURE_ROLES["companion"]
    assert "rom" in gloss.lower() and "blob" in gloss.lower(), (
        "the companion gloss does not mention the ROM/non-ROM discriminator, "
        f"so it still does not separate companion from blob: {gloss!r}")


def test_serves_section_is_closed_by_any_heading_level():
    """the terminator was `^#{2,3} `, so a `#### ` sub-heading
    left §3.1 open and every later `| \\`dir\\` |` row counted as a serves
    entry — including the generated census rows."""
    text = REGISTER.read_text()
    anchor = "### 3.1"
    assert anchor in text
    # close §3.1 with a #### heading, then plant a bogus serves row after it
    hacked = text.replace(anchor, anchor, 1)
    idx = hacked.index("\n## ", hacked.index(anchor))
    hacked = (hacked[:idx] + "\n\n#### a sub-heading\n\n"
              "| `zz_not_a_dir` | should not count as a serves entry |\n"
              + hacked[idx:])
    problems = G.check_serves_table(hacked, set(G.load_tree()[0]))
    assert not any("zz_not_a_dir" in p for p in problems), (
        "a row after a #### sub-heading was still read as a §3.1 serves "
        f"entry: {problems}")


def test_every_feature_toml_in_the_tree_declares_a_role():
    """Every declaration, including the ones outside engine/features.

    `role` became required, so a feature.toml without one is a BUILD
    FAILURE — and the ones most easily missed are the probe declarations
    under vendor/, because only `make measure` builds them.

    NO HARDCODED TOTAL. This test was `test_all_33_feature_tomls_declare_a_role`
    and asserted `len(tomls) == 33`; this slice added six dirs and it went red
    while nothing was wrong. The count was never the property under test —
    "no declaration is missed" is, and that is expressed by globbing the
    tree and checking coverage of the place a miss would hide."""
    tomls = [p for p in SUPERFORGE.glob("**/feature.toml")
             if "build/" not in p.as_posix()]
    assert tomls, "no feature.toml found at all — the glob is wrong"
    outside = [p for p in tomls if "engine/" not in p.as_posix()]
    assert outside, (
        "no feature.toml outside engine/ — the vendor/ probe declarations "
        "are the ones a role sweep misses, so their absence here means the "
        "sweep is not reaching them")
    missing = [str(p.relative_to(SUPERFORGE)) for p in tomls
               if not any(ln.startswith("role = ") for ln in
                          p.read_text().splitlines())]
    assert not missing, f"feature.toml without a role: {missing}"
