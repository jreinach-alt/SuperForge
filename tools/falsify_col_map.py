#!/usr/bin/env python3
"""falsify_col_map.py — plant each defect the col_map tests claim to catch,
confirm the claimed test goes RED, then revert.

AGENTS.md: "Trusting a green test you have not tried to break.":
"Falsify everything ... a plant that doesn't fire is information, not a pass."
Two plants in the VWF work failed to fire and had to be diagnosed; this
script exists so that diagnosis is mechanical rather than remembered.

A plant is (file, old, new, test that must fail). The script applies one at a
time, rebuilds nothing itself (pytest's fixtures run `make`), runs ONLY the
named test, and records the outcome. **A build failure is NOT a fired gate** —
it is reported separately, because "the build broke" does not demonstrate that
the assertion under test can see the defect.

Usage:  python3 tools/falsify_col_map.py [substring-of-plant-id ...]
"""
import hashlib
import subprocess
import sys
from pathlib import Path

F = Path(__file__).resolve().parent.parent
KERNEL = F / "engine" / "features" / "col_map" / "col_map.asm"
GEN = F / "tools" / "gen_col_flags.py"
SCENE = F / "game" / "microzero" / "scenes" / "race.asm"
PROBE = F / "vendor" / "probes" / "probe_colmap.asm"
PROBE_T = "tests/test_col_map.py"
SCENE_T = "tests/test_col_map_scene.py"
T7 = "test_t7_col_map_and_vwf_are_correct_across_the_same_window"

PLANTS = [
    dict(id="P1-bank-term-dropped", file=KERNEL,
         old="""    lda z:CM_T0
    .repeat CM_CHUNK_SHIFT
        lsr                     ; ty >> log2(rows per chunk) = the chunk index
    .endrepeat
    clc
    adc #CM_WORLD_BLOB_BANK""",
         new="""    lda z:CM_T0
    .repeat CM_CHUNK_SHIFT
        lsr                     ; ty >> log2(rows per chunk) = the chunk index
    .endrepeat
    and #0                      ; PLANT: always chunk 0
    clc
    adc #CM_WORLD_BLOB_BANK""",
         test=f"{PROBE_T}::test_t1_col_map_matches_the_world_blob_across_every_chunk_bank",
         why="every query with ty >= 64 reads the wrong world row"),

    dict(id="P2-axes-transposed", file=KERNEL,
         old="""    lda z:CM_PY
    lsr
    lsr
    lsr
    and #(CM_H - 1)             ; ty = (py >> 3) mod H — the world is a torus""",
         new="""    lda z:CM_PX                 ; PLANT: transpose the world
    lsr
    lsr
    lsr
    and #(CM_H - 1)             ; ty = (py >> 3) mod H — the world is a torus""",
         test=f"{PROBE_T}::test_t1_col_map_matches_the_world_blob_across_every_chunk_bank",
         why="the octagon is not symmetric under transpose on the start spoke"),

    dict(id="P3-flag-table-shifted", file=GEN,
         old="    return bytes(flag_for(i) for i in range(TABLE_ENTRIES))",
         new="    return bytes(flag_for(i - 1) for i in range(TABLE_ENTRIES))  # PLANT",
         test=f"{PROBE_T}::test_t2_col_map_flags_the_octagon_bands_at_hand_derived_boundaries",
         why="shifts every id; EXPECTED to be caught earlier by the "
             "generator's own unclassified-tile assert, which is itself a gate"),

    dict(id="P3b-kerbs-marked-drivable", file=GEN,
         old="""    if tile_id in world.DRIVABLE_TILE_IDS:
        f |= FLAG_DRIVABLE""",
         new="""    if tile_id in world.TRACK_TILE_IDS:   # PLANT: TRACK where DRIVABLE meant
        f |= FLAG_DRIVABLE""",
         test=f"{PROBE_T}::test_t2_col_map_flags_the_octagon_bands_at_hand_derived_boundaries",
         why="kerbs become DRIVABLE (3, not 2). Passes the generator's guard "
             "-- every flagged tile is still non-zero -- so only T2's "
             "hand-derived bands can see it"),

    dict(id="P4-bounds-check-instead-of-mask", file=KERNEL,
         old="""    lda z:CM_PX
    lsr
    lsr
    lsr
    and #(CM_W - 1)             ; tx = (px >> 3) mod W""",
         new="""    lda z:CM_PX
    lsr
    lsr
    lsr
    cmp #CM_W                   ; PLANT: bounds-check instead of wrapping
    bcc :+
    lda #0
:   .a16""",
         test=f"{PROBE_T}::test_t3_col_map_is_total_over_the_u16_input_space",
         why="f(x+4096, y) stops equalling f(x, y) — totality broken"),

    dict(id="P5-stale-by-one-frame", file=SCENE,
         old="""    lda z:ES_M7ORG + 0          ; the camera's world pixel x (already wrapped
    sta z:CM_PX                 ;   to 0..4095 by rl_integrate)
    lda z:ES_M7ORG + 2
    sta z:CM_PY""",
         new="""    lda z:CM_PX                 ; PLANT: reuse last frame's coordinate
    sta z:CM_PX
    lda z:CM_PY
    sta z:CM_PY""",
         test=f"{SCENE_T}::test_t4_the_live_consumer_tracks_the_camera_every_frame",
         why="the result no longer describes the camera it is read beside"),

    dict(id="P6-db-not-restored", file=KERNEL,
         old="""    lda a:CM_WORLD_WIN, x          ; the tile id — one byte, so 0..255 always
    plb                         ; DB restored: the caller's bank is intact""",
         new="""    lda a:CM_WORLD_WIN, x          ; the tile id — one byte, so 0..255 always
    nop                         ; PLANT: drop the plb, leaving DB on a chunk bank""",
         test=f"{SCENE_T}::{T7}",
         why="the original hypothesis about HOW this breaks was wrong -- banks "
             "$00-$3F all mirror low WRAM ($0000-$1FFF) and the I/O page "
             "($2100-$21FF), so leaving DB on chunk bank 1..8 is "
             "indistinguishable from DB=0 for every `a:` access microzero "
             "makes after the call. In fact it kills the ROM outright. IT "
             "FIRES, BUT NOT WHERE IT IS AIMED: the red traced to "
             "mz_drive.py:84 inside D.enter_race ('race scene never settled'), "
             "i.e. the ROM is dead before any assertion in T7 executes. So "
             "this plant demonstrates the DEFECT is fatal, not that T7 can see "
             "it. P12 and P13 are the plants that exercise T7's own "
             "assertions. Kept, because the null result IS the finding."),

    dict(id="P7-row-off-by-one", file=KERNEL,
         old="    and #(CM_ROWS_PER_CHK - 1)  ; the row's index WITHIN its 32 KB chunk\n"
             "    xba                         ; * 256",
         new="    inc                         ; PLANT: off-by-one row\n"
             "    and #(CM_ROWS_PER_CHK - 1)  ; the row's index WITHIN its 32 KB chunk\n"
             "    xba                         ; * 256",
         test=f"{PROBE_T}::test_t1_col_map_matches_the_world_blob_across_every_chunk_bank",
         why="off-by-one row. Originally aimed at T8, where it did NOT fire: "
             "adjacent world rows carry the same flag at 98.3% of tiles "
             "(measured), so T8's then single-tile check was a coin flip. Two "
             "fixes came out of that null result -- T8 now compares the whole "
             "120x120 streamed window against the blob, and this plant is "
             "aimed at T1, whose contract IS the addressing sweep (it changes "
             "6/512 swept coordinates)."),

    dict(id="P8-window-vs-blob", file=KERNEL,
         old="    adc z:CM_T1\n    tax",
         new="    adc z:CM_T1\n    inc                         ; PLANT: one tile east\n    tax",
         test=f"{PROBE_T}::test_t1_col_map_matches_the_world_blob_across_every_chunk_bank",
         why="one tile east. Aimed at T1 for the same reason as P7, and the "
             "reasoning is worth keeping: T8's point check only discriminates "
             "when the OFFSET's OWN axis is the neighbour that differs. "
             "MEASURED over all 512x512 = 262144 tiles, using T8's own "
             "`neighbours_differ` predicate (any of the 4 torus-wrapped von "
             "Neumann neighbours carries a different FLAG BYTE): 9072 tiles = "
             "3.461%; where an x-neighbour AND a y-neighbour both differ, 3728 "
             "= 1.422% -- too rare to park on reliably, and forcing it would "
             "make T8 flaky for no gain. (These replace 2.94% / 1.06%, which "
             "no candidate definition of five could reproduce it "
             "and neither could this remediation; the definition above is "
             "stated so the next reader can check it in ten lines of Python. "
             "The conclusion drawn from them was unaffected.) So addressing "
             "defects are T1's contract (it sweeps 512 coordinates and catches "
             "both offsets); T8's contract is composition, carried by its "
             "whole-window streamer-vs-blob check with the point check as "
             "corroboration."),

    dict(id="P10-scratch-store-dropped", file=KERNEL,
         old=""".endif
    sta z:CM_T1""",
         new=""".endif
                                ; PLANT: the scratch store is dropped""",
         test=f"{SCENE_T}::test_t6_no_byte_of_cm_hot_is_ever_read_before_it_is_written",
         why="col_map declares NO `[init] zero`: its contract is "
             "write-before-read by construction (feature.toml), and T6 is the "
             "only thing that proves it. Dropping this store leaves +8/+9 "
             "never written while `adc z:CM_T1` reads them, so on hardware the "
             "row offset would be power-on garbage. Added because the "
             "declaration was deleted, so the gate that replaces it had to "
             "be shown to fire."),

    dict(id="P11-probe-param2-uninit", file=PROBE,
         old="""    sta f:US_PARAM2_LONG        ; cmd 3 reads this at @arm_one before the host
                                ; has necessarily written it (Mesen
                                ; flagged $7E0204/5 as uninitialised
                                ; reads). Power-on RAM is random — CLAUDE.md
                                ; rule 5 applies to probe fixtures too.
""",
         new="",
         test=f"{PROBE_T}::test_t9_the_probe_reads_no_byte_of_its_own_state_before_writing_it",
         why="restores the shipped defect: MAIN zeroed "
             "cmd/mark/param/seq/acc but not param2, which @arm_one reads on "
             "every cmd-3 query. It went unseen for a whole work item because the "
             "probe fixture used `load_rom`, which inits the debugger AFTER "
             "the run and leaves the per-address history incomplete. The "
             "remediation armed the detector on that fixture and added T9, so "
             "the class is now GATED rather than fixed once."),

    dict(id="P12-t7-bank-term-dropped", file=KERNEL,
         old="""    lda z:CM_T0
    .repeat CM_CHUNK_SHIFT
        lsr                     ; ty >> log2(rows per chunk) = the chunk index
    .endrepeat
    clc
    adc #CM_WORLD_BLOB_BANK""",
         new="""    lda z:CM_T0
    .repeat CM_CHUNK_SHIFT
        lsr                     ; ty >> log2(rows per chunk) = the chunk index
    .endrepeat
    and #0                      ; PLANT: always chunk 0
    clc
    adc #CM_WORLD_BLOB_BANK""",
         test=f"{SCENE_T}::{T7}",
         why="deliberately the SAME edit as P1, aimed at a different "
             "assertion. T7 had no falsification of its own; "
             "the remediation then measured that it had none available -- this "
             "edit was GREEN against the old single-frame level 3, because that "
             "sample lands at tile (456,154) out in the grass and 96% of the "
             "world's wrong answers are grass too. T7 now checks col_map on "
             "every frame of the 40-frame window (37 distinct tiles, chunks "
             "2/3/4), which is what gives level 3 power. If this ever goes "
             "green again, T7 has lost its teeth."),

    dict(id="P13-t7-stomps-vwf-pen", file=KERNEL,
         old="    sta z:CM_FLAG               ; the output region the tests read",
         new="    sta z:CM_FLAG               ; the output region the tests read\n"
             "    sta z:CM_FLAG - 42          ; PLANT: one byte into vwf's DP pen",
         test=f"{SCENE_T}::{T7}",
         why="col_map writing OUTSIDE its declared claim, into ES_VWF_PEN -- "
             "the one class the allocator's separation is meant to make "
             "impossible to do by accident, and precisely what a composition "
             "test is for. This and five sibling offsets ($40 $41 $42 $43 $47) "
             "were ALL GREEN against T7's old `any(chr_bytes)` level 2, "
             "because a non-zero check cannot tell a live reveal from a frozen "
             "strip still holding earlier ink -- the hole the old docstring "
             "named and did not close. Level 2 now requires the strip to take "
             "more than one state across the window (measured: 3 states, ink "
             "56 -> 68, reproducible run to run)."),
]


def run(plant) -> dict:
    src = plant["file"].read_text()
    assert plant["old"] in src, f"{plant['id']}: anchor not found in {plant['file'].name}"
    plant["file"].write_text(src.replace(plant["old"], plant["new"], 1))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", plant["test"],
                            "-q", "--no-header", "-x"],
                           cwd=F, capture_output=True, text=True, timeout=1800)
        out = r.stdout + r.stderr
        built = "failed" not in out.lower() or "make " not in out
        if "make microzero failed" in out or "make probe-colmap failed" in out:
            verdict = "BUILD BROKE (not a fired gate)"
        elif r.returncode != 0 and " failed" in out:
            verdict = "RED — the gate fired"
        elif r.returncode == 0:
            verdict = "STILL GREEN — the test cannot see this defect"
        else:
            verdict = f"INCONCLUSIVE (rc={r.returncode})"
        tail = [l for l in out.splitlines() if l.strip()][-1:]
        return {"verdict": verdict, "tail": tail[0] if tail else ""}
    finally:
        plant["file"].write_text(src)


def main(argv) -> int:
    want = argv[1:]
    sel = [p for p in PLANTS if not want or any(w in p["id"] for w in want)]
    rows = []
    for p in sel:
        print(f"--- planting {p['id']} ...", flush=True)
        res = run(p)
        rows.append((p["id"], p["test"].split("::")[-1], res["verdict"], res["tail"]))
        print(f"    {res['verdict']}  |  {res['tail']}", flush=True)

    print("\n" + "=" * 78)
    for pid, test, verdict, _ in rows:
        print(f"{verdict:<38} {pid:<28} {test[:40]}")
    bad = [r for r in rows if not r[2].startswith("RED")]
    print("=" * 78)
    print(f"{len(rows) - len(bad)}/{len(rows)} plants fired.")
    if bad:
        print("NOT FIRED (report these honestly — a plant that does not fire is "
              "information, not a pass):")
        for pid, test, verdict, tail in bad:
            print(f"  {pid}: {verdict} — {tail}")
    # Verify the tree is clean again -- SOURCES *and* ARTIFACTS. Reverting the
    # source is not enough: build/ still holds whatever the last plant produced,
    # and the next `make` only notices because of an mtime. Printing "(clean)"
    # while build/microzero.sfc is a planted ROM is exactly the kind of
    # almost-true status line this script exists to refuse.
    d = subprocess.run(["git", "diff", "--stat"], cwd=F,
                       capture_output=True, text=True)
    print("\ngit diff after revert:", d.stdout.strip() or "(clean)")

    print("rebuilding the artifacts the plants overwrote ...", flush=True)
    r = subprocess.run(["make", "microzero", "probe-colmap"], cwd=F,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  REBUILD FAILED (rc={r.returncode}) — build/ still holds "
              f"planted artifacts:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
        return 1
    for name in ("microzero.sfc", "probe_colmap.sfc"):
        p = F / "build" / name
        print(f"  {hashlib.md5(p.read_bytes()).hexdigest()}  build/{name}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
