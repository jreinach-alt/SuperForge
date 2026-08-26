"""The collection-time symbol-map guard, tried against real violations.

runtime: ~6 s on a warm build tree, measured (18 cases), and ~21 s when a
map is stale and has to be rebuilt first — minutes on a cold tree, because
the cases rebuild maps and drive collection repeatedly and a cold tree pays
for every one.

For the one live-tree check select `::test_the_tree_agrees_with_the_rule`
rather than the module.

AGENTS.md: "when you add a gate, prove it fails on a real violation before
believing it." So this drives `conftest.py`'s guard through both directions —
and specifically through the two shapes an mtime-based guard gets WRONG, which
is why the shipped one compares content instead:

  * a map that is MISSING or built from an older tree  -> must be refused
  * a wrong map that is NEWER than every source        -> must still be
    refused (the mtime false negative)
  * a correct map whose SOURCES have newer mtimes      -> must be accepted
    (the mtime false positive that fired on a green tree)

The guard runs a real allocator subprocess per map, so the fixtures here are
real emitted maps, not hand-written stand-ins.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "tests"))

import conftest as guard  # noqa: E402


TOY_MAP = "build/symbol_map.json"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway SUPERFORGE whose `build/symbol_map.json` we can vandalise.

    The allocator is invoked with cwd=SUPERFORGE and repo-relative game paths, so
    the sandbox needs the declaration sources and the allocator itself. Copied
    rather than symlinked: a test that writes into the real tree is the defect
    this suite is currently carrying elsewhere.
    """
    root = tmp_path / "repo"
    (root / "build").mkdir(parents=True)
    for d in ("allocator", "engine/toy"):
        shutil.copytree(SUPERFORGE / d, root / d)
    subprocess.run(
        [sys.executable, str(root / "allocator" / "allocate.py"),
         "--game", "engine/toy", "--out", str(root / "build")],
        cwd=root, capture_output=True, text=True, check=True)
    monkeypatch.setattr(guard, "SUPERFORGE", root)
    monkeypatch.setattr(guard, "_verdict_cache", {})
    return root


def test_a_freshly_emitted_map_is_accepted(sandbox):
    assert guard.verdict(TOY_MAP) is None


def test_a_missing_map_is_refused(sandbox):
    (sandbox / TOY_MAP).unlink()
    assert "MISSING" in guard.verdict(TOY_MAP)


def test_a_map_from_an_older_tree_is_refused(sandbox):
    """The reported failure: a `build/` that predates a declaration change.

    Modelled the way it actually happens — a claim grew, so the emitted map
    no longer carries what the tests will ask it for.
    """
    toml = sandbox / "engine" / "toy" / "feat_a" / "feature.toml"
    src = toml.read_text()
    assert "bytes = 4" in src, "fixture assumption: feat_a_pos is 4 DP bytes"
    grown = src.replace("bytes = 4", "bytes = 6", 1)
    toml.write_text(grown)
    reason = guard.verdict(TOY_MAP)
    assert reason is not None and "STALE" in reason, reason


def test_a_wrong_map_that_is_newer_than_everything_is_still_refused(sandbox):
    """The mtime FALSE NEGATIVE, which is why the guard compares content.

    A hand-edited or half-written `build/` is newer than every source, so an
    mtime check calls it fresh. Here a symbol is removed — exactly the shape
    that surfaces downstream as `KeyError: 'ES_...'` at collection.
    """
    p = sandbox / TOY_MAP
    d = json.loads(p.read_text())
    assert d["globals"], "fixture assumption: the toy map emits globals"
    dropped = d["globals"].pop()["sym"]
    # WALL-CLOCK: ok — mtime granularity on the FILESYSTEM. No emulator is
    # running; the wait exists so the rewritten map is strictly newer.
    time.sleep(0.01)
    p.write_text(json.dumps(d, indent=2))          # newest file in the tree
    assert p.stat().st_mtime > max(
        f.stat().st_mtime for f in (sandbox / "engine").rglob("*")), \
        "fixture assumption: the vandalised map is the newest file"
    reason = guard.verdict(TOY_MAP)
    assert reason is not None and "STALE" in reason, \
        f"dropping {dropped} was not caught: {reason}"


def test_a_correct_map_with_newer_sources_is_accepted(sandbox):
    """The mtime FALSE POSITIVE, reproduced.

    A full suite run bumps the mtime of source `.toml` files without changing
    a byte of them. `make` correctly calls the map out of date; the map is
    nevertheless exactly right, and refusing collection here made three
    modules uncollectable on a green tree.
    """
    now = time.time() + 10
    for f in (sandbox / "engine").rglob("*.toml"):
        import os
        os.utime(f, (now, now))
    assert guard.verdict(TOY_MAP) is None, \
        "a byte-identical map was refused because its sources were touched"


def test_the_guard_checks_exactly_the_collection_time_reads():
    """Scope, asserted on the real test modules.

    Both counted shapes, and the excluded one, are live in this tree — so
    this is a check on the rule rather than on a fixture of the rule.
    """
    # 1. the read written at module scope (the module that reported the bug)
    c2 = (SUPERFORGE / "tests" / "test_c2_slice_c.py").read_text()
    assert guard.maps_named_in(c2) == {"build/rm/symbol_map.json"}

    # 2. a module-scope CALL to a module-level helper that does the read
    room = (SUPERFORGE / "tests" / "test_room_window.py").read_text()
    assert guard.maps_named_in(room) == {"build/rm/symbol_map.json"}, (
        "test_room_window reads its map through _SYMS = _room_symbols() at "
        "module scope — an indirection the guard has to follow, or the very "
        "module whose KeyError motivated it goes unguarded")

    # 3. a read inside a FIXTURE that builds the map first: NOT guarded.
    #    This is a CI run — build/colmap_map/ does not exist until
    #    the probe fixture runs `make probe-colmap`, and demanding it up
    #    front refused the whole suite.
    colmap = (SUPERFORGE / "tests" / "test_col_map.py").read_text()
    assert "colmap_map" in colmap and "make" in colmap
    assert guard.maps_named_in(colmap) == set(), (
        "test_col_map builds its own map in the probe fixture — guarding it "
        "refuses a module that looks after itself")

    assert guard.maps_named_in("no maps here") == set()


def test_the_three_read_shapes_resolve_and_the_two_non_reads_do_not():
    """The parser's rule, on synthetic modules covering every shape.

    Written as fixtures rather than only against the tree so the rule stays
    pinned when the tree stops happening to use one of them.
    """
    P = 'MAP = R / "build" / "mz" / "symbol_map.json"\n'
    want = {"build/mz/symbol_map.json"}

    # READS at collection time
    assert guard.maps_named_in(
        'S = json.loads((R / "build" / "mz" / "symbol_map.json").read_text())'
    ) == want, "direct module-scope read"
    assert guard.maps_named_in(
        'def load():\n    return json.loads((R / "build" / "mz" /'
        ' "symbol_map.json").read_text())\nS = load()\n'
    ) == want, "module-scope call to a module-level helper"
    assert guard.maps_named_in(
        P + "S = json.loads(MAP.read_text())\n"
    ) == want, "module-scope read through a module-level path constant"

    # NOT reads at collection time
    assert guard.maps_named_in(P) == set(), (
        "naming a path touches no disk, so it cannot KeyError at collection")
    assert guard.maps_named_in(
        P + "def fixture():\n    return json.loads(MAP.read_text())\n"
    ) == set(), (
        "a read inside a fixture is not a collection-time read — the fixture "
        "may `make` the map first, and several in this suite do")


def test_the_tree_agrees_with_the_rule():
    """Which real modules the guard covers, stated so a change is visible.

    Not derived from a second scan of the same source — a crude text scan
    cannot tell a module-scope read from a fixture-scope one, which is the
    entire distinction, so it would either duplicate the parser or contradict
    it. This is the reviewed list instead.
    """
    covered = {m.name: sorted(guard.maps_named_in(m.read_text()))
               for m in sorted((SUPERFORGE / "tests").glob("test_*.py"))
               if guard.maps_named_in(m.read_text())}
    assert covered == {
        # an earlier phase a later sweep. Its map IS in conftest.MAPS
        # ("breaker"), which is what this line is confirming — the guard's
        # message asks for exactly that check when a module is added. an
        # earlier phase a later sweep. Registering it in conftest.MAPS was NOT
        # a formality: unregistered, the resolver fell back to the toy map and
        # the module demanded `make toy` while its own rail map went unbuilt --
        # a rail's tests can be green against the wrong map's freshness. The
        # sweep's LAST rail. Its map IS in conftest.MAPS ("mode7_flight") and
        # in _SUBDIR_MAP ("m7f"); registering it moved that rail from "sites
        # 5+6+9 not required" to demanded in `make rail-registered`, which is
        # this guard and that gate agreeing about the same fact from two
        # directions — and it is why the three edits belong in one commit.
        "test_mode7_flight.py": ["build/m7f/symbol_map.json"],
        "test_m7_dungeon.py": ["build/m7dg/symbol_map.json"],
        "test_breaker.py": ["build/bk/symbol_map.json"],
        # an earlier phase a later sweep, same shape: its map IS in
        # conftest.MAPS ("shmup").
        "test_shmup.py": ["build/sh/symbol_map.json"],
        # an earlier phase a later sweep, same shape: its map IS in conftest.MAPS
        # ("split_v_fight"). Registering it was not a formality — the module
        # first composed the path in two steps (BUILD / "sv" / ...), which this
        # guard's resolver does not recognise, so it reported the read as
        # `build/symbol_map.json` and the module would have been checked for
        # freshness against the TOY map. The single-expression shape is load
        # bearing.
        "test_split_v_fight.py": ["build/sv/symbol_map.json"],
        # an earlier phase a later sweep, same shape: its map IS in conftest.MAPS
        # ("split_h_2p_demo") and in _SUBDIR_MAP ("sh2"). Both were added with
        # the rail; `make rail-registered` then moved that rail from "sites 5+6
        # not required" to demanded, which is this guard and that gate agreeing
        # about the same fact from two directions.
        "test_split_h_2p_demo.py": ["build/sh2/symbol_map.json"],
        # ...and the sprite module beside it, which reads the SAME map in the same
        # single-expression shape. Two modules on one rail is not a special
        # case for the resolver, but it is worth the line: the sprite module
        # also IMPORTS the demo module (for its Mode 7 oracle), and an import
        # is not a map read — this entry is here because of its own
        # module-scope `_JMAP`, not because of that import.
        "test_split_h_2p_sprites.py": ["build/sh2/symbol_map.json"],
        # an earlier phase a later sweep, same shape: its map IS in conftest.MAPS
        # ("mode7_explore") and in _SUBDIR_MAP ("m7x"). Registering it moved
        # that rail from "sites 5+6 not required" to demanded in
        # `make rail-registered`, which is this guard and that gate agreeing
        # about the same fact from two directions — and it is why the two
        # edits belong in one commit.
        "test_mode7_explore.py": ["build/m7x/symbol_map.json"],
        # an earlier phase a later sweep, same shape: its map IS in conftest.MAPS
        # ("platformer_stream") and in _SUBDIR_MAP ("pfs"). Same pairing as the
        # two entries above — registering it moved that rail from "sites 5+6
        # not required" to demanded in `make rail-registered`, so this guard
        # and that gate now agree about the same fact from two directions.
        "test_platformer_stream.py": ["build/pfs/symbol_map.json"],
        # A later sweep, same shape ×2: both maps ARE in conftest.MAPS and
        # _SUBDIR_MAP ("hud_game"/"hud", "scroller"/"scr"). Worth a line beyond
        # the pairing above, because this list used to be the one registration
        # site no gate mentioned — two rails hit it independently,
        # minutes into a full suite. Since the spec H-3 it is SITE 9 of
        # `make rail-registered`'s twelve: the gate parses this dict literal
        # via ast and demands an entry for every reader conftest's own
        # scanner sees, so the miss now surfaces in seconds, named. (The
        # list stays hand-reviewed — see the docstring above for why a
        # second scan cannot replace it.)
        "test_hud_game.py": ["build/hud/symbol_map.json"],
        "test_scroller.py": ["build/scr/symbol_map.json"],
        "test_lakeside.py": ["build/lks/symbol_map.json"],
        "test_camera_follow.py": ["build/cf/symbol_map.json"],
        # Same family, same shape: its map IS in conftest.MAPS
        # ("maze") and in _SUBDIR_MAP ("maze"), added with the module.
        "test_maze.py": ["build/maze/symbol_map.json"],
        # Same family, same shape: map in conftest.MAPS ("jumper")
        # and _SUBDIR_MAP ("jr"); this entry + those two + determinism prereqs
        # were wired TOGETHER, before the module's first run, per the gate's
        # own site list.
        "test_jumper.py": ["build/jr/symbol_map.json"],
        "test_patrol.py": ["build/pat/symbol_map.json"],
        # Same family, same shape: its map IS in conftest.MAPS
        # ("sprite_game") and in _SUBDIR_MAP ("sprg"), added in the same
        # commit as this entry per the pairing rule above.
        "test_sprite_game.py": ["build/sprg/symbol_map.json"],
        # Same family (stomper), same shape: its map IS in
        # conftest.MAPS ("stomper") and in _SUBDIR_MAP ("st"); registering it
        # moves the rail from "sites 5+6+9 not required" to demanded in
        # `make rail-registered`, the two directions agreeing as above.
        "test_stomper.py": ["build/st/symbol_map.json"],
        # Same family, same shape: its map IS in conftest.MAPS
        # ("scroll_run") and in _SUBDIR_MAP ("sr") — the pairing that moves
        # the rail from "sites 5+6 not required" to demanded in
        # `make rail-registered`, so this guard and that gate agree about the
        # same fact from two directions.
        "test_scroll_run.py": ["build/sr/symbol_map.json"],
        # A later sweep, same shape ("split_h_demo" / "shd").
        "test_split_h_demo.py": ["build/shd/symbol_map.json"],
        "test_brawler.py": ["build/br/symbol_map.json"],
        # Same family, the matrix-band PAIR: two modules, two
        # maps, one feature set. Both maps are in conftest.MAPS
        # ("split_h_matrix_demo" / "split_h_persp3_demo") and in
        # _SUBDIR_MAP ("shm" / "shp3"). The pair is the first case
        # where two SEPARATE rails share every engine feature, so the
        # two entries here are what keeps their maps distinguishable:
        # a module reading the wrong sibling's map would find every
        # symbol it asked for, at the same values, and be checked for
        # freshness against the wrong build.
        "test_split_h_matrix_demo.py": ["build/shm/symbol_map.json"],
        "test_split_h_persp3_demo.py": ["build/shp3/symbol_map.json"],
        "test_split_v_demo.py": ["build/svd/symbol_map.json"],
        "test_split_v_seamtrial.py": ["build/svs/symbol_map.json"],
        "test_seam_irq_trial.py": ["build/sit/symbol_map.json"],
        "test_split_h_irq_grad_demo.py": ["build/shg/symbol_map.json"],
        # Same family, same shape: its map IS in conftest.MAPS
        # ("split_h_persp_demo") and in _SUBDIR_MAP ("shp").
        "test_split_h_persp_demo.py": ["build/shp/symbol_map.json"],
        # racer (a later sweep B-6): the module names the rail's map by its
        # build subdir ("rc"), the same shape every rail above uses.
        "test_racer.py": ["build/rc/symbol_map.json"],
        # mode7_chamber : same shape, build
        # subdir "m7c".
        "test_mode7_chamber.py": ["build/m7c/symbol_map.json"],
        # railshooter (the POOL debut): same shape — the
        # module reads its rail's map at COLLECTION time.
        "test_railshooter.py": ["build/rs/symbol_map.json"],
        # m7_oshoot : same shape again — the module reads its
        # rail's map at COLLECTION time to address the pool arrays, the matrix
        # shadow and the census words by SYMBOL rather than by literal.
        "test_m7_oshoot.py": ["build/mo/symbol_map.json"],
        "test_rpg.py": ["build/rpg/symbol_map.json"],
        "test_c2_slice_c.py": ["build/rm/symbol_map.json"],
        "test_room_window.py": ["build/rm/symbol_map.json"],
        "test_slice_b_audio.py": ["build/rm/symbol_map.json"],
    }, (f"the set of collection-time map readers changed: {covered}. If a "
        f"module was ADDED, good — confirm its map is in conftest.MAPS. If "
        f"one DROPPED OUT, check it did not just move its read into a "
        f"fixture without building the map there.")


def test_every_declared_subdir_resolves_to_a_declared_map():
    """No subdir may resolve to a map the guard cannot check."""
    import conftest
    unknown = set(conftest._SUBDIR_MAP.values()) - set(guard.MAPS)
    assert not unknown, f"_SUBDIR_MAP points at undeclared maps: {unknown}"


def test_self_emitted_maps_are_not_guarded():
    """A module that allocates into tmp_path names no build/ map, so
    selecting it alone costs no allocator subprocess and demands no built
    ROM."""
    for name in ("test_allocator", "test_no_literals", "test_spc_claim"):
        text = (SUPERFORGE / "tests" / f"{name}.py").read_text()
        assert "symbol_map.json" in text, f"{name} stopped reading maps"
        assert guard.maps_named_in(text) == set(), (
            f"{name} now reads a build/ map — it used to emit its own")


# --------------------------------------------------------------------------
# HOW the refusal REPORTS — the xdist misattribution
# --------------------------------------------------------------------------
#
# The guard's refusal is right and must not weaken. Its REPORTING was wrong
# under xdist, and wrong in the most expensive way a report can be: it named
# an innocent module.
#
# The mechanism. `pytest_collectstart` is called by `collect_one_node`
# OUTSIDE the `CallInfo` that protects `collector.collect()`, so a raise there
# is not a collection error — it is an exception escaping the collection loop.
# Single-process pytest turns that into a usage error and prints the message,
# which is fine. Under xdist the WORKER PROCESS DIES holding whichever item it
# had been handed, and the controller reports
#
#     INTERNALERROR> ... assert not crashitem, (crashitem, node)
#     AssertionError: ('tests/test_allocator.py::...', <WorkerController gw0>)
#     no tests ran
#
# naming a pure-Python module that passes alone, never naming the module with
# the stale map, never printing the map or the `make` line. It reads like a
# build race and is not one. `make test` takes the rail list as prerequisites
# so the front door cannot reach this state — but
# `pytest tests/ -k something -n 4` is what people type while iterating, and
# that path kept producing it. the spec states it as a residual; these are
# its regression tests.
#
# THE REPRODUCTION, and why it is built this way. The plants load the SHIPPED
# conftest by path and re-export its hooks (`tests/test_park_guard.py`'s
# pattern, for the same reason: a copied guard drifts from the real one), then
# repoint its `SUPERFORGE` at the throwaway root. The map is then MISSING by
# construction — the sandbox has no `build/` at all — so the reproduction does
# not depend on what this repo happens to have built, and it costs no
# allocator subprocess (`verdict` short-circuits on a missing file).
#
# TEST SURFACE (CLAUDE.md rule 2): the output region read is the pytest
# process's own stdout/stderr and exit status, from a real `-n 2` run over a
# real tree. Not the hook's return value — the defect WAS the hook's return
# path being correct and its transport being wrong.

_GUARD_SHIM = f"""
import importlib.util, pathlib, sys
_spec = importlib.util.spec_from_file_location(
    "superforge_real_conftest", {str(SUPERFORGE / "tests" / "conftest.py")!r})
_real = importlib.util.module_from_spec(_spec)
sys.modules["superforge_real_conftest"] = _real
_spec.loader.exec_module(_real)

# point the guard at THIS tree, which has no build/ — so the map it is asked
# about is MISSING by construction, on any box, in any build state
_real.SUPERFORGE = pathlib.Path(__file__).resolve().parent
_real._verdict_cache.clear()
_real._module_seen.clear()

# Register the WHOLE shipped module as a plugin rather than re-exporting hooks
# by name. `tests/test_park_guard.py` re-exports three names, and this change
# had to edit that list the moment the guard's hook changed — a shim that
# names hooks silently stops exercising the one you just added. Registering
# the module means the plants run against every hook the real conftest ships,
# which is the property both files actually want.
def pytest_configure(config):
    config.pluginmanager.register(_real, "superforge_real_conftest")
"""

# The culprit: reads a map from conftest.MAPS at MODULE SCOPE. `zz_` so
# alphabetical collection hands it to a worker AFTER the innocents, which is
# what made the old failure land on someone else's name.
_CULPRIT = """
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent
SYMS = json.loads((ROOT / "build" / "bk" / "symbol_map.json").read_text())

def test_uses_the_map():
    assert SYMS
"""

# The innocents: pure Python, pass alone, pass under -n. These are the names
# the old INTERNALERROR printed.
_INNOCENT_A = """
def test_one(): assert 1 == 1
def test_two(): assert 2 == 2
def test_three(): assert 3 == 3
def test_four(): assert 4 == 4
"""

_INNOCENT_B = """
def test_five(): assert 5 == 5
def test_six(): assert 6 == 6
"""


@pytest.fixture(scope="module")
def guard_plants(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("guardreport")
    (root / "conftest.py").write_text(_GUARD_SHIM)
    (root / "test_zz_reads_a_missing_map.py").write_text(_CULPRIT)
    (root / "test_aaa_innocent.py").write_text(_INNOCENT_A)
    (root / "test_bbb_innocent.py").write_text(_INNOCENT_B)
    return root


def _run(root: Path, *args) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    env.pop("PYTEST_CURRENT_TEST", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = ""
    return subprocess.run(
        [sys.executable, "-m", "pytest", ".", "-q", "-p", "no:randomly",
         *args],
        cwd=root, capture_output=True, text=True, timeout=300, env=env)


@pytest.mark.parametrize("args", [(), ("-n", "2")], ids=["serial", "xdist2"])
def test_the_refusal_names_the_module_and_its_map(guard_plants, args):
    """The fix, stated as the property that was missing: the report is about
    the module that reads the stale map, in BOTH runners."""
    r = _run(guard_plants, *args)
    out = r.stdout + r.stderr

    assert "INTERNALERROR" not in out, (
        f"the guard still crashes the runner instead of failing collection:"
        f"\n{out}")
    assert "test_zz_reads_a_missing_map.py" in out, (
        f"the refusal does not name the module that reads the missing map:"
        f"\n{out}")
    assert "build/bk/symbol_map.json is MISSING" in out, (
        f"the refusal does not name the map:\n{out}")
    assert "make breaker" in out, (
        f"the refusal does not name the command that fixes it:\n{out}")
    # the innocents must not be blamed. `crashitem` is the field the old
    # AssertionError carried them in, so their absence from the error surface
    # is the exact regression this locks.
    head = out.split("short test summary", 1)[0]
    for innocent in ("test_aaa_innocent", "test_bbb_innocent"):
        assert f"ERROR {innocent}" not in head and \
               f"{innocent}.py::" not in head, (
            f"{innocent} is named in the failure surface:\n{out}")


@pytest.mark.parametrize("args", [(), ("-n", "2")], ids=["serial", "xdist2"])
def test_the_refusal_does_not_weaken(guard_plants, args):
    """The half that must NOT change — and the half the first fix broke.

    Changing the failure's SHAPE changed its REACH. Serially a failed
    `CollectReport` still stops everything (`_pytest/main.py::
    pytest_runtestloop` raises `Interrupted` on `session.testsfailed`); under
    xdist that loop is replaced by `DSession.pytest_runtestloop`, which has no
    such check, so the first version returned `6 passed, 1 error`. Non-zero
    exit, so nothing would have shipped green — but on a cold tree, where
    EIGHT modules read maps, it meant running ~1,500 tests against ROMs that
    do not exist. `pytest_collection_modifyitems` drops the items so both
    runners agree: NOTHING runs.
    """
    r = _run(guard_plants, *args)
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert " passed" not in out, (
        f"tests RAN despite a missing map — the refusal weakened:\n{out}")
    assert "1 error" in out, out
    # and it says so as an interruption, not as a footnote under a green run
    assert "Interrupted" in out, (
        f"the session did not stop — the refusal became a footnote:\n{out}")


def test_the_escape_hatch_still_works(guard_plants):
    """`--continue-on-collection-errors` is the documented "I know" flag.

    A guard that ignores its own escape hatch is one people route around, so
    the item drop is conditioned on it. The culprit still ERRORs; the rest
    still runs.
    """
    r = _run(guard_plants, "--continue-on-collection-errors")
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "6 passed" in out, out
    assert "1 error" in out, out
    assert "test_zz_reads_a_missing_map.py" in out, out


def test_a_clean_tree_collects_normally(tmp_path):
    """The pair, so the guard is not a constant.

    Same shim, same runners, no module reading a `build/` map: everything must
    collect and pass. Without this, a hook that failed every module would
    satisfy the two tests above.
    """
    root = tmp_path / "clean"
    root.mkdir()
    (root / "conftest.py").write_text(_GUARD_SHIM)
    (root / "test_aaa_innocent.py").write_text(_INNOCENT_A)
    (root / "test_bbb_innocent.py").write_text(_INNOCENT_B)
    for args in ((), ("-n", "2")):
        r = _run(root, *args)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "6 passed" in r.stdout, r.stdout
        assert "Interrupted" not in r.stdout + r.stderr, (
            "the item drop fired on a tree with no refusal — the guard now "
            "stops healthy runs")


def test_the_refusal_lands_before_the_module_is_imported(guard_plants):
    """The property the old hook had and the new one must keep.

    The guard exists to replace a `KeyError` five frames down a collection
    traceback with one actionable line. If the report were produced AFTER the
    import, the import's own exception would arrive first and the guard would
    be decoration. The culprit's module-scope read raises `FileNotFoundError`
    if it ever executes — so its absence from the output is the evidence.
    """
    out = _run(guard_plants).stdout + _run(guard_plants).stderr
    assert "FileNotFoundError" not in out, (
        f"the module was IMPORTED before the guard reported — the guard is "
        f"now decoration on top of the error it exists to replace:\n{out}")


def test_the_hook_is_the_one_pytest_protects():
    """Why `pytest_make_collect_report` and not `pytest_collectstart`.

    This is a claim about pytest's own machinery, so it is checked against
    pytest's own source rather than asserted from memory (CLAUDE.md, "if you
    are about to state what a tool does, open the tool"): in
    `_pytest/runner.py::collect_one_node`, `pytest_collectstart` is called
    bare and `pytest_make_collect_report`'s DEFAULT implementation is the one
    that wraps `collector.collect()` in a `CallInfo`. A raise from the first
    escapes the collection loop; a failed report from the second is a
    first-class collection error that xdist transports.
    """
    import inspect
    from _pytest import runner
    src = inspect.getsource(runner.collect_one_node)
    assert "pytest_collectstart(collector=collector)" in src
    assert "pytest_make_collect_report(collector=collector)" in src
    assert src.index("pytest_collectstart") < \
        src.index("pytest_make_collect_report"), (
        "pytest_make_collect_report no longer runs after pytest_collectstart "
        "— the guard's 'before the import' property rests on that order")

    # and the guard registers on the protected hook, not the bare one
    assert hasattr(guard, "pytest_make_collect_report")
    assert not hasattr(guard, "pytest_collectstart"), (
        "conftest re-grew a pytest_collectstart hook — a raise from there is "
        "what crashed xdist workers")
