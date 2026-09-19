"""tools/map_lint.py against planted violations.

A gate is only worth the findings it can be PROVEN to produce. Every rule here
is checked against a fixture that plants it, and the two silences — a region
origin, and an address read out of the symbol map — are checked too, because a
lint that fires on everything gets switched off.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LINT = ROOT / "tools" / "map_lint.py"
FIX = ROOT / "tests" / "fixtures" / "map_lint" / "plain.py"


def _run(*args):
    return subprocess.run([sys.executable, str(LINT), *args],
                          capture_output=True, text=True, cwd=ROOT)


def test_plants_all_fire():
    r = _run(str(FIX), "--summary")
    assert r.returncode == 1, r.stdout + r.stderr
    lits = [l for l in r.stdout.splitlines() if "map-literal-address" in l]
    bare = [l for l in r.stdout.splitlines() if "bare-override" in l]
    assert len(lits) == 4, "\n".join(lits)   # 3 plants + the bare stamp's site
    assert len(bare) == 1, "\n".join(bare)
    assert "$3C00" in r.stdout and "$2000" in r.stdout and "$0200" in r.stdout


def test_the_silences_hold():
    """A region origin and a map-derived address must NOT fire."""
    src = FIX.read_text()
    assert "read_bytes(V, 0, 512)" in src and 'MAP["aur_map2"]' in src
    r = _run(str(FIX))
    for line in r.stdout.splitlines():
        n = int(line.split(":")[1])
        assert "V, 0," not in FIX.read_text().splitlines()[n - 1]
        assert "MAP[" not in FIX.read_text().splitlines()[n - 1]


def test_a_reasoned_override_silences_its_site():
    r = _run(str(FIX))
    ls = FIX.read_text().splitlines()
    fired = {int(l.split(":")[1]) for l in r.stdout.splitlines()}
    ok = next(i for i, l in enumerate(ls, 1) if "a real override" in l)
    assert (ok - 1) not in fired, "a reasoned override did not silence its site"


BASELINE = ROOT / "reports" / "map_lint_baseline.json"


def test_the_tree_is_clean_against_its_baseline():
    r = _run("tests", "tools", "--baseline", str(BASELINE), "--summary")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "accessor call site(s) examined" in r.stdout


def test_the_baseline_is_empty():
    """The RATCHET. A baselined finding is neither derived nor approved — it
    is a third thing, and the only reason it ever passes is that it was
    already there when the gate landed. The seven it shipped with were driven
    to zero (four derived from the emitted map, three from the probe's own
    equates), so the file's job now is to say the tree is clean.

    It must still EXIST: `map_lint` treats a missing baseline as an empty one,
    so deleting it would look identical here while removing the artifact a
    reviewer reads. This asserts the stronger thing — present and empty.
    """
    assert BASELINE.exists(), \
        "the baseline file is gone — an absent baseline and an empty one " \
        "behave the same in the gate and read very differently to a person"
    entries = json.loads(BASELINE.read_text())
    assert entries == [], (
        f"{len(entries)} grandfathered finding(s) are back in the baseline. "
        f"Derive the address out of the rail's symbol_map.json, or write a "
        f"`# MAP: ok — <reason>` at the site; do not re-baseline it: "
        f"{[ (e['file'], e['line']) for e in entries ]}")


def test_the_gate_reports_itself_disarmed():
    """If an accessor is renamed off Machine the lint must SAY so, not pass.

    A gate that silently stops matching reads as clean, which is the worst
    failure a gate has.
    """
    src = LINT.read_text()
    assert '"read_u16": 1' in src and "_verify_scope" in src
    assert "DISARMED" in src
