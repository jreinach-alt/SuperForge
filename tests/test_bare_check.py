"""`make bare-check`, tried against real violations.

runtime: ~47 s for the whole module, measured (9 cases) — each test clones
this repo into tmp, and the clone is what dominates. That is only affordable
because of the gate-block substitution below; without it this module would be
half an hour. It was ~30-42 s over 6 cases before the three census cases
landed on 2026-08-23; those three run a real (if tiny) gate block, so they
cost more than a substituted one and the number was re-measured rather than
extrapolated.

AGENTS.md: "when you add a gate, prove it fails on a real violation before
believing it." bare-check stands where a CI push trigger otherwise would, so
the violations that matter are the ones a hosted runner catches and a local
`make gates` structurally cannot:

  * work that is not committed — the clone can only ever see HEAD;
  * a STALE ARTIFACT making a build target a no-op — this escaped local runs
    three separate times as a stale build/probe_vblank.sfc, sitting there
    looking green while the no_literals channel rules had broken the probe
    build outright;
  * a vendored file that is gone from the commit but still referenced, hidden
    behind that same stale artifact.

HOW THE PLANTS ARE ISOLATED. Every test clones THIS repo into tmp and plants
there. Nothing touches the live working tree — which matters more here than
usual, because these plants deliberately break the build, and a plant that
leaked would break the tree the rest of the suite is running against. No lock
is needed for the same reason.

WHY THE GATE BLOCK IS SUBSTITUTED. `bare-check` runs `make gates`, which is
~8 minutes; four plants would be half an hour. `BARE_CHECK_GATES` swaps in the
one target each plant is about, so what is under test is the PIPELINE — refuse,
clone, verify the tip, hide any configured sibling tree, run, record, propagate
the exit code —
which is the part that could silently stop having teeth. The gate block itself
is proven by `make gates`' own tests and by running it for real.

...WITH ONE EXCEPTION, and it is the reason `_plant_cheap_gates` exists. The
ROM CENSUS step deliberately does NOT run under a substituted block: a
substitute builds one target, so "svd_nowin.sfc is absent" would be true and
meaningless, and a gate that fails for a reason it did not test is noise. The
census plants therefore cannot use `BARE_CHECK_GATES` — they keep the gate
command as `make gates` and replace what `gates:` DOES, with a stand-in that
runs in seconds and still carries the two things the census reads: a `run
<target>;` sequence for the derivation, and a summary file for the artifact.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent

# The tools the landing gate RUNS, as opposed to the tree it checks. Each is
# taken from the WORKING TREE into every planted clone for the same reason
# bare_check.sh itself is (see the `repo` fixture): a change to any of them
# must be under test before it is committed, not after.
GATE_TOOLS = ("bare_check.sh", "rail_registered.py", "fix_checksum.py")


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          capture_output=True, text=True)


def _run_bare_check(repo, gates="make toy", allow_dirty=False, extra_env=None):
    """Run the planted repo's OWN tools/bare_check.sh against itself."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
    env.update({
        "BARE_CHECK_GATES": gates,
        "BARE_CHECK_DIR": str(repo.parent / "bc-scratch"),
        # A plant must not reach a real reference tree even by accident, and
        # naming a path that does not exist also exercises the "nothing to
        # hide" arm of the isolation code.
        "SF_REFERENCE_TREE": str(repo.parent / "no-such-reference-tree"),
        "XDIST": "2",
    })
    if allow_dirty:
        env["BARE_CHECK_ALLOW_DIRTY"] = "1"
    env.update(extra_env or {})
    proc = subprocess.run(["bash", str(repo / "tools" / "bare_check.sh")],
                          cwd=repo, capture_output=True, text=True,
                          env=env, timeout=1200)
    report = repo / "build" / "bare_check.json"
    doc = json.loads(report.read_text()) if report.exists() else None
    return proc, doc


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    """A committed, self-contained copy of this repo, cloned once.

    --no-local for the same reason bare_check.sh uses it: this repo is itself
    a shallow session clone, and a hardlink clone does not copy .git/shallow.
    """
    root = tmp_path_factory.mktemp("bc")
    repo = root / "pristine"
    subprocess.run(["git", "clone", "--quiet", "--no-local",
                    str(SUPERFORGE), str(repo)], check=True, timeout=300)
    _git(repo, "config", "user.email", "plant@superforge.invalid")
    _git(repo, "config", "user.name", "bare-check plant")
    # Hooks do not clone; keep it that way so a plant's commit is never gated.
    _git(repo, "config", "--unset", "core.hooksPath", check=False)
    return repo


@pytest.fixture
def repo(pristine, tmp_path):
    """A fresh copy of the pristine clone, per test."""
    dst = tmp_path / "repo"
    shutil.copytree(pristine, dst, symlinks=True)
    # Test the tools IN THE WORKING TREE, not the ones in HEAD. The clone
    # carries HEAD's copies, so without this an edit to bare_check.sh is
    # tested only after it is committed — which is the wrong way round for a
    # gate, and cost one 8-minute run to notice (the substituted gate block
    # was silently ignored and the full block ran instead). Committed as part
    # of the plant so the clone inside bare-check sees it too.
    for tool in GATE_TOOLS:
        shutil.copy2(SUPERFORGE / "tools" / tool, dst / "tools" / tool)
        _git(dst, "add", f"tools/{tool}")
    _git(dst, "commit", "-qm", "test: use the working tree's gate tools",
         check=False)
    return dst


_GATES_RULE = re.compile(r"^gates: \| \$\(BUILD\)\n(?:\t.*\n)*", re.M)


def _plant_cheap_gates(repo, runs, *, post="", extra_rules=""):
    """Swap `gates:` for a seconds-scale stand-in, and commit it.

    `runs` is the `run <target>;` sequence — the thing `expected_images()`
    derives the expected set from, so a plant controls what the census
    demands by writing this. `post` is a shell fragment run after the
    builds (how an image gets corrupted AFTER `fix_checksum.py` has had its
    say — it refuses a lying header at build time, so the only way to plant
    one is behind its back). `extra_rules` is appended after the stand-in.
    """
    mk = repo / "Makefile"
    src = mk.read_text()
    assert _GATES_RULE.search(src), "PLANT GUARD: Makefile lost `gates:`"
    cheap = (
        "gates: | $(BUILD)\n"
        '\t@run() { $(MAKE) "$$1"; }; \\\n'
        f"\t{runs} \\\n"
        + (f"\t{post} \\\n" if post else "")
        + "\tprintf '  toy          ok       exit 0\\n' "
          "> $(BUILD)/gates_summary.txt\n")
    mk.write_text(_GATES_RULE.sub(lambda _m: cheap + extra_rules, src,
                                  count=1))
    _git(repo, "add", "Makefile")
    _git(repo, "commit", "-qm", "plant: a seconds-scale stand-in for gates:")


# ---------------------------------------------------------------------------
# 1. the refusal — the property a local `make gates` cannot have at all
# ---------------------------------------------------------------------------

def test_uncommitted_work_is_refused_and_the_file_is_named(repo):
    """The single most valuable thing this gate says.

    A clone holds only HEAD. If the tree is dirty, whatever bare-check reports
    is a verdict on a different tree than the one in front of you — so it must
    not report one. And it must say WHICH paths, or the reader has to go
    find them.
    """
    (repo / "engine" / "PLANTED_UNCOMMITTED.inc").write_text("; not in HEAD\n")

    proc, doc = _run_bare_check(repo)

    assert proc.returncode == 2, (
        f"a dirty tree did not refuse (exit {proc.returncode})\n{proc.stdout}")
    assert "NOT COMMITTED" in proc.stdout, proc.stdout
    assert "PLANTED_UNCOMMITTED.inc" in proc.stdout, (
        f"the refusal did not name the offending path:\n{proc.stdout}")
    assert doc is not None and doc["verdict"] == "REFUSED", doc
    # ...and it refused BEFORE running anything, or the refusal is decoration.
    assert "gates" not in (doc.get("steps") or {}), doc


def test_a_file_the_build_needs_but_HEAD_lacks_goes_red(repo):
    """The same violation, past the refusal — the deeper property.

    The dirty-tree refusal is a fast, precise front door, but it is a
    heuristic: it says "this could be wrong". This says the pipeline is
    actually load-bearing. The build here NEEDS a file that exists only in the
    working tree, so it succeeds locally and cannot succeed from a clone.
    """
    # Commit a rule that requires a file, and leave the file uncommitted.
    mk = repo / "Makefile"
    mk.write_text(mk.read_text().replace(
        "toy: no-literals $(BUILD)/toy.sfc",
        "toy: no-literals $(BUILD)/toy.sfc engine/PLANTED_NEEDED.inc", 1))
    _git(repo, "add", "Makefile")
    _git(repo, "commit", "-qm", "plant: toy needs a file that is not committed")
    (repo / "engine" / "PLANTED_NEEDED.inc").write_text("; working tree only\n")

    # The plant is honest only if the LOCAL build is green on it.
    local = subprocess.run(["make", "toy"], cwd=repo, capture_output=True,
                           text=True, timeout=600)
    assert local.returncode == 0, (
        f"the plant is not the shape it claims — local `make toy` already "
        f"fails:\n{local.stdout}\n{local.stderr}")

    proc, doc = _run_bare_check(repo, allow_dirty=True)

    assert proc.returncode == 1, (
        f"bare-check passed a build that only works on this machine "
        f"(exit {proc.returncode})\n{proc.stdout[-3000:]}")
    assert doc["verdict"] == "RED", doc
    assert any(v.startswith("FAIL") for v in doc["steps"].values()), doc


# ---------------------------------------------------------------------------
# 2. the stale tree — the defect that escaped local runs three times
# ---------------------------------------------------------------------------

def _plant_broken_no_literals(repo):
    """Break the probe_vblank build the way the documented defect did.

    `allocator/no_literals.py` is NOT a prerequisite of
    `$(BUILD)/probe_vblank.sfc` (Makefile, the probe recipe), so editing it
    leaves an already-built .sfc newer than everything make checks. That is
    precisely why the original defect was invisible: `make
    build/probe_vblank.sfc` had nothing to do and exited 0.
    """
    nl = repo / "allocator" / "no_literals.py"
    src = nl.read_text()
    plant = (
        "\n# --- PLANT: the channel rules reject the vblank probe ---\n"
        "if any('probe_vblank' in _a for _a in sys.argv):\n"
        "    print('no_literals: PLANTED refusal for probe_vblank', "
        "file=sys.stderr)\n"
        "    sys.exit(1)\n\n")
    # Insert immediately BEFORE the __main__ guard. Neither end of the file
    # works: appending puts it after `main()` has already exited, and
    # prepending lands above `from __future__ import annotations`, which must
    # be the first statement — that one broke EVERY no_literals call, so
    # `make toy` failed inside setup.sh and bare-check went red for the wrong
    # reason. Both mistakes were made; both cost a run.
    marker = 'if __name__ == "__main__":'
    assert marker in src, "no_literals.py lost its __main__ guard"
    nl.write_text(src.replace(marker, plant + marker, 1))


def test_a_stale_artifact_hides_a_broken_build_locally_and_bare_check_finds_it(repo):
    """The `NO STALE TREE` claim in bare_check.sh's own header, end to end.

    Both halves are asserted, because only the pair is the claim: the local
    build must be GREEN on the stale tree (or this is not the defect), and
    bare-check must be RED on the same commit (or it is not the fix).
    """
    built = subprocess.run(["make", "build/probe_vblank.sfc"], cwd=repo,
                           capture_output=True, text=True, timeout=600)
    assert built.returncode == 0, f"{built.stdout}\n{built.stderr}"
    artifact = repo / "build" / "probe_vblank.sfc"
    before = artifact.stat().st_mtime_ns

    _plant_broken_no_literals(repo)
    _git(repo, "add", "allocator/no_literals.py")
    _git(repo, "commit", "-qm", "plant: no_literals rejects probe_vblank")

    # HALF ONE — local is green, and green because the target NO-OPPED. Guard
    # the ARTIFACT, not just the exit code: a run that rebuilt and happened to
    # pass would prove nothing about staleness.
    local = subprocess.run(["make", "build/probe_vblank.sfc"], cwd=repo,
                           capture_output=True, text=True, timeout=600)
    assert local.returncode == 0, (
        f"the stale artifact did not hide the break — local build already "
        f"fails, so this plant is not the documented shape:\n{local.stdout}")
    assert artifact.stat().st_mtime_ns == before, (
        "the artifact was rebuilt, so the target was not a no-op and the "
        "plant does not reproduce the stale-tree defect")

    # HALF TWO — the fresh clone has no build/ at all, so it must build it,
    # and the build must fail.
    proc, doc = _run_bare_check(repo, gates="make probes", allow_dirty=True)

    assert proc.returncode == 1, (
        f"bare-check passed a build that only 'works' because of a stale "
        f"artifact (exit {proc.returncode})\n{proc.stdout[-3000:]}")
    assert doc["verdict"] == "RED", doc
    # stdout AND stderr: make sends the recipe's diagnostic to stderr, and a
    # gate that goes red for the wrong reason is not this gate.
    combined = proc.stdout + proc.stderr
    assert "PLANTED refusal" in combined, (
        f"red, but not for the planted reason:\n{combined[-3000:]}")


def test_a_deleted_vendored_file_still_referenced_goes_red(repo):
    """The same class, on the vendored material rather than on a tool.

    `.incbin`/`.include` targets are invisible to make, so deleting one and
    leaving the ROM in build/ is green locally for exactly the same reason —
    and this is the shape that would let `vendor/` rot silently.
    """
    built = subprocess.run(["make", "build/probe_vblank.sfc"], cwd=repo,
                           capture_output=True, text=True, timeout=600)
    assert built.returncode == 0, f"{built.stdout}\n{built.stderr}"
    artifact = repo / "build" / "probe_vblank.sfc"
    before = artifact.stat().st_mtime_ns

    # The victim has to be a file the BUILD reads and make does NOT track.
    # header.inc/init.inc/ppu_reset.inc are all listed prerequisites of the
    # probe rule, so deleting one makes `make` itself error ("No rule to make
    # target") and the stale artifact never gets a chance to hide anything.
    # The ld65 config is read by the linker and named nowhere in the rule's
    # prerequisites — exactly the untracked-input shape.
    victim = repo / "vendor" / "rom" / "lorom_32k.cfg"
    assert victim.exists(), f"{victim} — plant needs a real vendored input"
    _git(repo, "rm", "-q", str(victim.relative_to(repo)))
    _git(repo, "commit", "-qm", "plant: delete a vendored include still used")

    local = subprocess.run(["make", "build/probe_vblank.sfc"], cwd=repo,
                           capture_output=True, text=True, timeout=600)
    assert local.returncode == 0 and artifact.stat().st_mtime_ns == before, (
        "the plant is not the stale-artifact shape — make already rebuilds "
        "or fails here")

    proc, doc = _run_bare_check(repo, gates="make probes", allow_dirty=True)
    assert proc.returncode == 1, (
        f"bare-check passed a commit missing a file its build reads "
        f"(exit {proc.returncode})\n{proc.stdout[-3000:]}")
    assert doc["verdict"] == "RED", doc


# ---------------------------------------------------------------------------
# 3. the ROM census — derived at both ends, so both ends get a violation
# ---------------------------------------------------------------------------
#
# Until 2026-08-23 the landing gate measured a hand-maintained, rail-scoped
# list of ROMs, and `make gates`'s build list is not rail-scoped: eight
# variant/control images the block builds were measured nowhere and seven more
# had never been measured at all. Both ends are derived now — WHAT IS MEASURED
# from `build/*.sfc`, WHAT MUST BE THERE from the `gates:` run-list — and each
# end fails in its own way, so each gets its own plant.


def test_an_expected_image_that_is_not_built_goes_red_by_name(repo):
    """The property the retired ci.yml ROM-step sweep uniquely had.

    A rail census asks "for each dir under game/, is it named here?" and so
    cannot see a target that builds an image and then stops. This plant is
    exactly that shape: a target whose rule names an image, whose recipe
    succeeds, and which produces no file. The old measured list would have
    said nothing — the image was never in it.
    """
    _plant_cheap_gates(
        repo, "run toy; run ghost;",
        extra_rules="ghost: $(BUILD)/ghost.sfc\n\n"
                    "$(BUILD)/ghost.sfc:\n"
                    "\t@true\n")

    proc, doc = _run_bare_check(repo, gates="make gates")

    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, (
        f"bare-check passed a gate block that stopped building an image it "
        f"is supposed to build (exit {proc.returncode})\n{combined[-3000:]}")
    assert doc["verdict"] == "RED", doc
    assert "EXPECTED IMAGE ABSENT" in combined, combined[-3000:]
    assert "build/ghost.sfc" in combined, (
        f"red, but the run did not NAME the missing image:\n"
        f"{combined[-3000:]}")
    assert doc["steps"]["rom-census"].startswith("FAIL"), doc["steps"]
    assert doc["measurement"]["absent"] == ["ghost"], doc["measurement"]


def test_an_image_whose_header_lies_about_its_length_goes_red(repo):
    """The other end: the expected SIZE now comes from the image itself.

    `tools/fix_checksum.py` refuses to patch a checksum over a header that
    declares the wrong length, and it runs on every linked image on every
    build — which is what makes the header a per-image authority and let the
    hand-maintained `rom:size` list retire. So the plant has to go in AFTER
    the build, behind that refusal's back, which is also the only way this
    could ever happen for real (a poked byte, a truncated copy).
    """
    _plant_cheap_gates(
        repo, "run toy;",
        # $7FD7 declares 2^N KB. toy links 32,768 B and declares $05; $06
        # says 65,536 while the file stays 32,768.
        post="$(PY) -c \"f=open('$(BUILD)/toy.sfc','r+b');"
             "f.seek(0x7FD7);f.write(b'\\x06');f.close()\";")

    proc, doc = _run_bare_check(repo, gates="make gates")

    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, (
        f"bare-check passed an image whose header lies about its length "
        f"(exit {proc.returncode})\n{combined[-3000:]}")
    assert doc["verdict"] == "RED", doc
    # BOTH numbers, or the reader cannot tell which end is wrong.
    assert "build/toy.sfc" in combined and "32768" in combined \
        and "65536" in combined, (
        f"red, but the run did not name the file and both lengths:\n"
        f"{combined[-3000:]}")
    assert doc["steps"]["rom-census"].startswith("FAIL"), doc["steps"]
    assert doc["rom_sizes"]["toy"]["ok"] is False, doc["rom_sizes"]["toy"]


def test_the_census_records_every_image_and_says_where_it_got_its_numbers(
        repo):
    """The healthy arm — without it the two plants above are a constant.

    Also the artifact's shape: the census is the thing the landing rule
    quotes, so it has to carry the count, the md5s, and where each half of
    the derivation came from.
    """
    _plant_cheap_gates(repo, "run toy;")

    proc, doc = _run_bare_check(repo, gates="make gates")

    assert proc.returncode == 0, f"{proc.stdout[-3000:]}{proc.stderr[-3000:]}"
    assert doc["verdict"] == "GREEN", doc
    assert doc["steps"]["rom-census"] == "pass", doc["steps"]

    m = doc["measurement"]
    assert m["absent"] == [], m
    assert m["measured_count"] == len(doc["rom_sizes"]) >= 1, m
    assert m["expected_count"] == 1, (
        f"the stand-in runs one image-producing target, so exactly one "
        f"image should be demanded: {m}")
    assert "header" in m["expected_size_from"], m
    assert "--expected-images" in m["expected_set_from"], m
    # MEASURED is wider than DEMANDED, on purpose: setup.sh's own sanity
    # test links microzero before the block runs, and the census counts it
    # without anything having asked for it. A census that only counted what
    # it demanded would be the old list wearing a derivation's clothes.
    assert m["measured_count"] >= m["expected_count"], m

    # toy is 32,768 B and its header says so; the md5 is RECORDED, not pinned.
    assert doc["rom_sizes"]["toy"] == {
        "expected": "32768", "actual": "32768", "ok": True,
        "expected_from": "header"}, doc["rom_sizes"]["toy"]
    assert re.fullmatch(r"[0-9a-f]{32}", doc["rom_md5"]["toy"]), doc["rom_md5"]
    assert set(doc["rom_md5"]) == set(doc["rom_sizes"]), (
        "the two census tables disagree about which images were measured")
    # ...and the COUNT is on the surface a reader actually looks at.
    assert f"measured: {m['measured_count']} image(s)" in proc.stdout, \
        proc.stdout[-2000:]


# ---------------------------------------------------------------------------
# 4. the artifact — it is the citable result, so its shape is load-bearing
# ---------------------------------------------------------------------------

def test_a_green_run_records_the_sha_it_checked_and_what_it_did_not_hold(repo):
    """the landing policy's landing rule is "cite a bare-check result on the
    exact tip", so the result has to carry the tip — and it has to carry the
    isolation properties it did NOT hold, or citing it implies parity with a
    bare runner that it does not have.
    """
    proc, doc = _run_bare_check(repo, gates="make toy")

    assert proc.returncode == 0, f"{proc.stdout[-3000:]}"
    assert doc["verdict"] == "GREEN", doc
    assert doc["sha"] == _git(repo, "rev-parse", "HEAD").stdout.strip(), doc
    assert doc["isolation"]["fresh_clone"] is True, doc
    assert doc["isolation"]["not_reproduced"], (
        "the artifact claims no residue at all — it runs on this box, so "
        "'different machine' is always residue")
    assert doc["gate_command"] == "make toy", doc
    # A substituted gate block must be impossible to mistake for a real run.
    assert "NOT A LANDING-GATE RUN" in proc.stdout, proc.stdout[-2000:]


def test_the_clone_is_verified_against_the_working_tree_tip(repo):
    """A clone that is not at HEAD would silently check another commit."""
    src = (repo / "tools" / "bare_check.sh").read_text()
    assert 'CLONE_SHA" != "$SHA' in src, (
        "bare_check.sh no longer compares the clone's HEAD to the working "
        "tree's — the gate could check a different commit than the one cited")
    proc, doc = _run_bare_check(repo, gates="make toy")
    assert proc.returncode == 0
    assert "verified == working tree HEAD" in proc.stdout, proc.stdout[-2000:]
