#!/usr/bin/env python3
"""falsify_col_map_binding.py — prove each of col_map's six required binding
symbols is a REAL gate: remove one binding at a time from the shipping scene
and confirm the build fails with the `.error` that NAMES that symbol.

AGENTS.md: "Trusting a green test you have not tried to break. When you add a
gate, prove it fails on a real violation before believing it." A `.error` that
has never been observed to fire is a comment.

 chose includer-supplied symbols with NO DEFAULTS over a
parameterised `depends`, on the argument that "the undefined-symbol error is
the design review" . That argument is only worth
anything if the errors actually arrive, and arrive NAMING the missing symbol
rather than as a downstream range error three includes later. This script is
the evidence.

What counts as a fired gate, and it is deliberately strict:

  * the build must FAIL (a plant that still builds is a hole), AND
  * ca65's output must contain the feature's own message for THAT symbol.

A build that fails with some other error is reported as NOT FIRED, because
"the build broke" does not demonstrate that the binding check can see the
defect — the same distinction tools/falsify_col_map.py draws between a fired
gate and a broken build.

RESTORE IS BY COPY, NOT BY GIT (AGENTS.md: a `git checkout <file>` undo
silently discards uncommitted work). The snapshot is taken in memory before
the first plant, each plant asserts its target text is present before
substituting, and the final line reports both the restored source diff AND the
rebuilt ROM's md5 — because a revert check that covers only tracked sources is
half a revert check when the deliverable is a binary.

Usage:  python3 tools/falsify_col_map_binding.py [substring-of-plant-id ...]
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

F = Path(__file__).resolve().parent.parent
SCENE = F / "game" / "microzero" / "scenes" / "race.asm"
ROM = F / "build" / "microzero.sfc"
ROM_PIN = "e45ddeabac4218cd71709da7b9fcc849"

# (symbol, the exact binding line in race.asm, the words the .error must carry)
BINDINGS = [
    ("CM_WORLD_W_LOG2",
     "CM_WORLD_W_LOG2      = 9",
     "must define CM_WORLD_W_LOG2"),
    ("CM_WORLD_H_LOG2",
     "CM_WORLD_H_LOG2      = 9",
     "must define CM_WORLD_H_LOG2"),
    ("CM_WORLD_BLOB",
     "CM_WORLD_BLOB        = ::ES_R_WORLD_MAP_T0_ADDR",
     "must define CM_WORLD_BLOB "),
    ("CM_WORLD_BLOB_BANK",
     "CM_WORLD_BLOB_BANK   = ::ES_R_WORLD_MAP_T0_BANK",
     "must define CM_WORLD_BLOB_BANK"),
    ("CM_WORLD_BLOB_CHUNKS",
     "CM_WORLD_BLOB_CHUNKS = ::ES_R_WORLD_MAP_CHUNKS",
     "must define CM_WORLD_BLOB_CHUNKS"),
    ("CM_FLAGS",
     "CM_FLAGS             = ::col_flags_bin",
     "must define CM_FLAGS"),
]


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else "(absent)"


def build():
    """Run the real target. Returns (ok, combined output)."""
    r = subprocess.run(["make", "microzero"], cwd=F,
                       capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def main():
    wanted = sys.argv[1:]
    plants = [b for b in BINDINGS
              if not wanted or any(w in b[0] for w in wanted)]

    original = SCENE.read_text()
    for sym, line, _ in plants:
        # The guard that turns silent loss into a visible failure.
        assert line in original, f"plant target not found in race.asm: {line!r}"

    print("baseline: building the unplanted tree")
    ok, out = build()
    if not ok:
        print("BASELINE BUILD FAILED — cannot falsify against a red tree")
        print(out[-2000:])
        return 2
    base_md5 = md5(ROM)
    print(f"  microzero {base_md5}"
          f"  {'(pin)' if base_md5 == ROM_PIN else '(PIN MOVED!)'}\n")

    results = []
    try:
        for sym, line, needle in plants:
            print(f"--- plant: omit {sym}")
            planted = original.replace(line, "; PLANT: binding omitted  " + line, 1)
            assert planted != original
            SCENE.write_text(planted)
            ok, out = build()
            named = needle in out
            # what ca65 actually said, first error line, for the record
            first = next((l.strip() for l in out.splitlines()
                          if ": Error:" in l or ".error" in l.lower()), "(none)")
            if ok:
                verdict = "STILL GREEN — THE GATE HAS A HOLE"
            elif named:
                verdict = "RED — the gate fired, naming the symbol"
            else:
                verdict = "RED but UNNAMED — build broke on something else"
            results.append((sym, verdict, first))
            print(f"    build: {'ok' if ok else 'FAILED'}   "
                  f"names {sym}: {named}")
            print(f"    {verdict}")
            print(f"    first error: {first}\n")
    finally:
        SCENE.write_text(original)

    print("=== restoring the tree (by copy, not by git) ===")
    ok, out = build()
    restored = md5(ROM)
    diff = subprocess.run(["git", "diff", "--stat", "--", str(SCENE)],
                          cwd=F, capture_output=True, text=True).stdout.strip()
    print(f"  race.asm diff after revert: {diff or '(clean)'}")
    print(f"  microzero rebuilt: {restored}"
          f"  {'(pin restored)' if restored == ROM_PIN else '(PIN NOT RESTORED)'}")

    print("\n=== summary ===")
    fired = 0
    for sym, verdict, _ in results:
        print(f"  {sym:22s} {verdict}")
        if verdict.startswith("RED — the gate fired"):
            fired += 1
    print(f"\n{fired}/{len(results)} binding gate(s) fired, naming their symbol")
    return 0 if (fired == len(results) and restored == ROM_PIN) else 1


if __name__ == "__main__":
    sys.exit(main())
