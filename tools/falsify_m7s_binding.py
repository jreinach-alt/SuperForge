#!/usr/bin/env python3
"""falsify_m7s_binding.py — prove mode7_stream's three binding symbols are a
REAL gate, in BOTH directions:

  A. OMISSION. Remove one binding at a time from the shipping scene and
     confirm the build fails with the `.error` that NAMES that symbol.
  B. MIS-BINDING. Point the whole binding at a DIFFERENT rom claim that
     really exists, and confirm the ROM changes. A binding that compiles
     to the same bytes whatever you bind it to is decorative, not
     load-bearing — and an omission gate alone cannot tell the two apart.

AGENTS.md: "Trusting a green test you have not tried to break. When you add a
gate, prove it fails on a real violation before believing it." A `.error` that
has never been observed to fire is a comment.

This is the sibling of tools/falsify_col_map_binding.py, which covers col_map's
six symbols for the same reason. Direction B is the addition: the
mode7_stream retrofit's acceptance criterion is that the microzero md5 does NOT
move, and "the pin is unmoved" is exactly what a no-op change also produces.
The mis-binding arm is what separates the two.

RESTORE IS BY COPY, NOT BY GIT (AGENTS.md: a `git checkout <file>` undo
silently discards uncommitted work). The snapshot is taken in memory before the
first plant, each plant asserts its target text is present before substituting,
and the final line reports both the restored source diff AND the rebuilt ROM's
md5 — a revert check that covers only tracked sources is half a revert check
when the deliverable is a binary.

Usage:  python3 tools/falsify_m7s_binding.py [substring-of-plant-id ...]
"""
import hashlib
import subprocess
import sys
from pathlib import Path

F = Path(__file__).resolve().parent.parent
SCENE = F / "game" / "microzero" / "scenes" / "race.asm"
ROM = F / "build" / "microzero.sfc"
ROM_PIN = "dea58053943943d693d85f89506a2bba"

# (symbol, the exact binding line in race.asm, the words the .error must carry)
BINDINGS = [
    ("M7S_WORLD_WIN",
     "M7S_WORLD_WIN = ::ES_R_WORLD_MAP_T0_ADDR",
     "must define M7S_WORLD_WIN"),
    ("M7S_BLOB_BANK",
     "M7S_BLOB_BANK = ::ES_R_WORLD_MAP_T0_BANK",
     "must define M7S_BLOB_BANK"),
    ("M7S_CHUNKS",
     "M7S_CHUNKS    = ::ES_R_WORLD_MAP_CHUNKS",
     "must define M7S_CHUNKS"),
]

# Direction B: a DIFFERENT rom claim that really exists in this composition —
# pose_rom's first pose pack. 2 chunks at bank 9 instead of 8 chunks at bank 1,
# so both the MVN stub table and stream_stage_col's span bank must change.
MISBIND = [
    ("M7S_WORLD_WIN = ::ES_R_WORLD_MAP_T0_ADDR",
     "M7S_WORLD_WIN = ::ES_R_POSES_AB_T0_ADDR"),
    ("M7S_BLOB_BANK = ::ES_R_WORLD_MAP_T0_BANK",
     "M7S_BLOB_BANK = ::ES_R_POSES_AB_T0_BANK"),
    ("M7S_CHUNKS    = ::ES_R_WORLD_MAP_CHUNKS",
     "M7S_CHUNKS    = ::ES_R_POSES_AB_CHUNKS"),
]


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else "(absent)"


def build():
    """Run the real target. Returns (ok, combined output)."""
    r = subprocess.run(["make", "microzero"], cwd=F,
                       capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def first_error(out):
    return next((l.strip() for l in out.splitlines()
                 if ": Error:" in l or ".error" in l.lower()), "(none)")


def main():
    wanted = sys.argv[1:]
    plants = [b for b in BINDINGS
              if not wanted or any(w in b[0] for w in wanted)]
    do_misbind = not wanted or any("misbind" in w.lower() for w in wanted)

    original = SCENE.read_text()
    # The guard that turns silent loss into a visible failure.
    for sym, line, _ in plants:
        assert line in original, f"plant target not found in race.asm: {line!r}"
    for old, _ in MISBIND:
        assert old in original, f"misbind target not found in race.asm: {old!r}"

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
    misbind_verdict = None
    try:
        # --- direction A: omission --------------------------------------
        for sym, line, needle in plants:
            print(f"--- plant: omit {sym}")
            planted = original.replace(line, "; PLANT: binding omitted  " + line, 1)
            assert planted != original
            SCENE.write_text(planted)
            ok, out = build()
            named = needle in out
            if ok:
                verdict = "STILL GREEN — THE GATE HAS A HOLE"
            elif named:
                verdict = "RED — the gate fired, naming the symbol"
            else:
                verdict = "RED but UNNAMED — build broke on something else"
            results.append((sym, verdict, first_error(out)))
            print(f"    build: {'ok' if ok else 'FAILED'}   names {sym}: {named}")
            print(f"    {verdict}")
            print(f"    first error: {first_error(out)}\n")

        # --- direction B: mis-binding to a real, different blob ----------
        if do_misbind:
            print("--- plant: misbind — point the binding at pose_rom's "
                  "POSES_AB (2 chunks @ bank 9) instead of WORLD_MAP "
                  "(8 chunks @ bank 1)")
            planted = original
            for old, new in MISBIND:
                planted = planted.replace(old, new, 1)
            assert planted != original
            SCENE.write_text(planted)
            ok, out = build()
            got = md5(ROM) if ok else "(build failed)"
            if not ok:
                misbind_verdict = ("REFUSED — the mis-binding did not even "
                                   "assemble")
            elif got == base_md5:
                misbind_verdict = ("md5 UNMOVED — THE BINDING IS DECORATIVE, "
                                   "not load-bearing")
            else:
                misbind_verdict = f"md5 MOVED to {got} — the binding is load-bearing"
            print(f"    build: {'ok' if ok else 'FAILED'}   md5: {got}")
            print(f"    {misbind_verdict}")
            if not ok:
                print(f"    first error: {first_error(out)}")
            print()
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
        print(f"  {sym:16s} {verdict}")
        if verdict.startswith("RED — the gate fired"):
            fired += 1
    if misbind_verdict:
        print(f"  {'misbind':16s} {misbind_verdict}")
    print(f"\n{fired}/{len(results)} omission gate(s) fired, naming their symbol")

    ok_all = (fired == len(results) and restored == ROM_PIN
              and (misbind_verdict is None
                   or "load-bearing" in misbind_verdict))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
