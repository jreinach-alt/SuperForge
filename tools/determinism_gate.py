#!/usr/bin/env python3
"""make determinism — the D-DH5 gate, scoped to one Machine-substrate module.

Runs the module TWICE, in fresh processes, each with SF_DETERMINISM_LOG
pointed at its own manifest; the Machine layer appends every observable
event (loads, advances with both pads, reads/writes with content hashes,
capture hashes) in program order. The verdict is byte-identity of the two
manifests — every recorded read and every PNG bit-identical, not merely
"green twice" — plus equal pytest exit codes (identical reads with
differing verdicts would be Python-side nondeterminism, equally a failure).

Polarity: NON-INVERTED, toy-bad's convention — exit 0 means the property
HELD. A deterministically-RED module still passes this gate when its two
runs are bit-identical: a reproducible red is a real finding with a replay
triple, which is the pilot's success outcome, not a gate failure. The gate
prints both pytest exits so a red-but-deterministic run is legible.

Disarm guard: an empty or trivially-short manifest fails — "identical"
must never be achievable by recording nothing (the summary prints the
event census so a pass names what it compared).

Falsification:
`--falsify` copies the module, plants a WALL-COUPLED READ (the machine is
poked with the host clock and read back, so the manifest carries host time)
plus a marker read, runs the planted copy through the same twice-compare,
and requires BOTH: the manifests DIFFER (sensitivity — the gate can see a
wall-coupled read) AND the marker appears in both manifests (liveness —
the plant demonstrably reached the run). Green without both is blindness,
not health.

Usage:
    python3 tools/determinism_gate.py [--module tests/test_x.py] [--falsify]
    make determinism [MODULE=tests/test_x.py]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
DEFAULT_MODULE = "tests/test_split_h_2p_sprites.py"
OUT = SUPERFORGE / "build" / "determinism"

# The plant's marker read: an (addr, count) pair no real test uses, greppable
# in the manifest as the liveness observable.
MARKER_ADDR, MARKER_COUNT = 0x1F3, 7

PLANT = f'''

# ---- PLANTED by tools/determinism_gate.py --falsify (never committed) ----
def test_planted_wall_coupled_read():
    """A read whose bytes are the HOST CLOCK: the exact defect class the
    determinism gate exists to catch. Two runs must produce differing
    manifests; the marker read below must appear in both."""
    import struct as _struct
    import sys as _sys
    import time as _time
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "vendor"))
    from machine import Machine as _Machine, MemoryType as _MT
    _m = _Machine(str(_Path(__file__).resolve().parent.parent / "build" / "microzero.sfc"))
    _m.advance(2)
    _m.write_bytes(_MT.SnesWorkRam, {MARKER_ADDR}, _struct.pack("<Q", _time.time_ns()))
    _m.read_bytes(_MT.SnesWorkRam, {MARKER_ADDR}, 8)      # wall-coupled bytes
    _m.read_bytes(_MT.SnesWorkRam, {MARKER_ADDR}, {MARKER_COUNT})  # the marker
    _Machine.close_current()
'''


def run_once(module: Path, log_path: Path, tag: str) -> int:
    log_path.unlink(missing_ok=True)
    env = dict(os.environ)
    env["SF_DETERMINISM_LOG"] = str(log_path)
    env.setdefault("SF_MESEN_HOME", str(OUT / "mesen_home"))
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(module), "-q", "-rs", "-p", "no:cacheprovider"],
        cwd=SUPERFORGE, env=env, capture_output=True, text=True)
    tail = "\n".join((r.stdout or "").strip().splitlines()[-3:])
    print(f"  {tag}: pytest exit {r.returncode}; {tail.splitlines()[-1] if tail else '(no output)'}")
    if not log_path.exists():
        print(f"  {tag}: NO MANIFEST WRITTEN — the module never drove a "
              f"Machine (or SF_DETERMINISM_LOG was lost). Gate disarmed.")
        print(r.stdout[-2000:], r.stderr[-2000:], sep="\n")
        sys.exit(2)
    return r.returncode


def census(log_path: Path) -> dict:
    kinds: dict = {}
    with open(log_path) as f:
        for line in f:
            k = json.loads(line)[0]
            kinds[k] = kinds.get(k, 0) + 1
    return kinds


def compare(module: Path, a: Path, b: Path) -> tuple[bool, int, int]:
    rc1 = run_once(module, a, "run 1")
    rc2 = run_once(module, b, "run 2")
    return a.read_bytes() == b.read_bytes(), rc1, rc2


def first_divergence(a: Path, b: Path) -> str:
    la, lb = a.read_text().splitlines(), b.read_text().splitlines()
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return f"line {i + 1}:\n    run1: {x[:160]}\n    run2: {y[:160]}"
    return (f"lengths differ: {len(la)} vs {len(lb)} events; first extra: "
            f"{(la + lb)[min(len(la), len(lb))][:160]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default=DEFAULT_MODULE)
    ap.add_argument("--falsify", action="store_true")
    args = ap.parse_args()
    module = SUPERFORGE / args.module
    if not module.exists():
        print(f"determinism: module {module} does not exist")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)

    if args.falsify:
        # The copy must live in tests/ — the module resolves the repo root
        # from its own __file__ and leans on tests/conftest.py; a copy in
        # build/ imports nothing. Named so default collection ignores it
        # (pytest only auto-collects test_*.py; the gate passes the path
        # explicitly), gitignored so a crashed run cannot dirty the tree.
        planted = SUPERFORGE / "tests" / f"planted_determinism_{module.stem}.py"
        src = module.read_text()
        planted.write_text(src + PLANT)
        try:
            print(f"determinism --falsify: planted copy at {planted}")
            same, rc1, rc2 = compare(planted, OUT / "falsify1.jsonl",
                                     OUT / "falsify2.jsonl")
            marker = f'["read", 15, {MARKER_ADDR}, {MARKER_COUNT},'
            live = all(marker in (OUT / f"falsify{i}.jsonl").read_text()
                       for i in (1, 2))
            if not live:
                print("determinism --falsify: FAIL — the marker read never "
                      "reached the manifest; the plant did not run, so the "
                      "'manifests differ' below (or not) proves nothing")
                return 1
            if same:
                print("determinism --falsify: FAIL — a host-clock read "
                      "produced IDENTICAL manifests; the gate is BLIND")
                return 1
            print("determinism --falsify: OK — plant reached both runs "
                  "(marker present) and the gate went red on it "
                  "(manifests differ). Sensitivity + liveness both proven.")
            return 0
        finally:
            planted.unlink(missing_ok=True)

    same, rc1, rc2 = compare(module, OUT / "run1.jsonl", OUT / "run2.jsonl")
    c = census(OUT / "run1.jsonl")
    total = sum(c.values())
    if total < 10:
        print(f"determinism: FAIL — manifest holds only {total} event(s); "
              f"a comparison over (almost) nothing is a disarmed gate")
        return 1
    if not same:
        print(f"determinism: FAIL — the two manifests differ.\n  first "
              f"divergence at {first_divergence(OUT / 'run1.jsonl', OUT / 'run2.jsonl')}")
        return 1
    if rc1 != rc2:
        print(f"determinism: FAIL — identical manifests but differing pytest "
              f"exits ({rc1} vs {rc2}): Python-side nondeterminism")
        return 1
    verdict = "green" if rc1 == 0 else f"RED (pytest exit {rc1}) but reproducible"
    print(f"determinism OK: two runs of {args.module} bit-identical — "
          + ", ".join(f"{v} {k}(s)" for k, v in sorted(c.items()))
          + f"; module verdict {verdict}. Exit 0 = the D-DH5 property held.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
