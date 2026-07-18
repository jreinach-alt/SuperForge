# Audit-2 — `sf_split_h` v1 remediation validation

**Auditor:** independent audit-2 agent (did NOT build, audit-1, or remediate this work). Research-only; no code changes except this report.
**Branch under review:** `claude/sf-split-h-primitive-80m8sg` @ `904cf2c52775c453c8a55637c8196fb3c57df939` (remediation).
**Base compared against:** `b1cc2a4` (pre-remediation).
**Materialized kit:** `/tmp/kit_audit2` (via `asm_repo_staging/tools/dryrun_split.sh`; scrub OK, 71 substitutions across 18 files, comment-lineage guard clean).
**Date:** 2026-07-01

## Aggregate verdict: **REMEDIATION VERIFIED**

All three remediation items are closed cleanly. The tightened D2 test is genuinely non-vacuous (independently re-derived probe below — clean frame flags zero rows, a synthetic smeared row fires the conjunction). The doc note is present, mechanism-correct, and clean-room in both surfaces. The audit-1 doc no longer trips the name tripwire, and cleanroom is clean WITH all audit docs present in the tree. No regression: the remediation touched exactly four files (audit-1 doc, guide, macro header comment-only, D2 test), no engine change, no macro LOGIC change, and the out-of-scope test assertions (`$7C` first-fit boot check, D4 difference assertion) are untouched. 7/7 split_h tests pass, 6/6 split_v pass (no regression).

---

## Per-finding verdict

### Finding 1 — D2 test-fidelity tightening: **REMEDIATION VERIFIED**

**What changed** (`tests/test_split_h_demo.py`, diff `b1cc2a4..904cf2c`):
- Two new per-scanline helpers added: `_amber_row(w, pix, y)` (`tests/test_split_h_demo.py:102-104`) counts BG3 instrument-amber pixels via `_is_bg3_amber` on framebuffer pixels in a single scanline; `_floor_tex_row(w, pix, y)` (`:107-116`) counts distinct non-backdrop, non-black framebuffer colours in a single scanline.
- The D2 body (`:200-249`) now: (a) keeps the both-bands-present check (top amber > 200 AND floor textured >= 4); AND (b) adds the clean-seam invariant — scans every scanline `y` in `range(Y_TOP1, SPLIT+21)` (rows 34..60) and flags any row where `_amber_row(y) > 30 AND _floor_tex_row(y) >= 4`; asserts `not smeared`.
- The docstring (`:200-207`) now promises exactly what the assertion enforces: "scan every scanline in the seam window and assert that NO row simultaneously carries substantial instrument-amber AND the Mode-7 floor's multi-colour texture." Test-name-is-a-contract satisfied.

**Reads a true output region:** both helpers read framebuffer pixels (`pix[x,y]` from the rendered screenshot). No proxy engine/state variable.

**Non-vacuity — my OWN independent probe** (not the remediation agent's), built fresh at `/tmp/d2_probe.py`, mirroring the test's helpers + thresholds exactly, run against a fresh HEAD build:

```
[clean frame] window=34..60  smeared rows flagged = []
  row : amber  floortex   (amber>30? tex>=4?)
   34 :     0      0
   ...
   46 :     0      0
   47 :     0      4
   48 :     0      4
   ... (floor texture ramps to 4, amber stays 0 across the whole window)
   60 :     0      4

[relaxed amber>-1] floor-textured rows in window (would fire) = [47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 60]

[synthetic smear @row 48] amber=50 floortex=5 -> conjunction FIRES = True

PROBE RESULT: non-vacuous. Clean frame -> 0 flagged; synthetic smear -> flagged.
```

Interpretation:
- **Discriminates a clean seam (passes):** on the real default frame, every seam-window scanline is wholly one band — amber = 0 across the whole window (rows 34..60), and floor-texture ramps up only at row 47. The conjunction flags zero rows. There is no scanline that is simultaneously amber-bearing and floor-textured.
- **The floor clause is real:** relaxing the amber threshold to `>-1` (always true) reduces the conjunction to "floor_tex >= 4", which fires on rows 47..58,60 — proving the floor clause discriminates and that on the clean frame it is the amber clause (correctly at 0 on floor rows) that suppresses those rows. This is a genuine `AND`, not an always-false conjunction.
- **The conjunction CAN fire (would catch a smear):** I painted `AMBER_MIX_THRESH+20 = 50` amber pixels onto a real floor-textured row (row 48, floortex 5). The conjunction FIRES (amber=50 > 30 AND floortex=5 >= 4) — exactly the "smeared/garbled row across the seam" the docstring promises to catch.

The tightened assertion is therefore **not vacuous** and genuinely verifies the docstring's clean-seam claim. Threshold headroom is sound: real instrument rows carry ~72-104 amber px (per the remediation's inline comment), 30 sits well below that yet well above the 0 seen on clean floor/backdrop rows.

### Finding 2 — M7HOFS/VOFS ↔ BG1HOFS/VOFS doc note: **REMEDIATION VERIFIED**

Present, mechanism-correct, and clean-room (no game names) in BOTH surfaces:

- **Guide** (`docs/guides/split_h.md:108-112`): "Note that `$210D`/`$210E` are the SAME PPU addresses as BG1HOFS/BG1VOFS — a code-side BG1 scroll write shares this same latch."
- **Macro header** (`lib/macros/sf_split_h.inc:43-45`): "Note $210D/$210E are the SAME PPU addresses as BG1HOFS/BG1VOFS — a code-side BG1 scroll write shares this same latch."

Mechanism-correct: `$210D` (M7HOFS / BG1HOFS) and `$210E` (M7VOFS / BG1VOFS) are physically the same write-twice-latch PPU registers, so a code-side BG1 scroll write is subject to the same shared-latch corruption hazard as a Mode-7 offset write. This is exactly the clarification the audit-1 LOW deviation #1 requested. Clean-room: prose is mechanism-only; no retail titles introduced (verified by the cleanroom gate below).

### Finding 3 — audit-1 doc eliminated-lineage token / stale-gate fix: **REMEDIATION VERIFIED**

The cleanroom tripwire (`tools/cleanroom_check.sh`, the LINEAGE regex near line 82) scans case-insensitively for the eliminated-lineage vocabulary (the removed scripting-language name plus its siblings) across the whole tree, docs included. The pre-remediation audit-1 doc contained two occurrences of the removed scripting-language name (verified in the base revision `b1cc2a4:.../sf_split_h-audit-1.md` at lines 21 and 43, both in the phrase describing "no proxy engine variable"). The remediation reworded both to the neutral phrase "engine/state variable" (`904cf2c`, diff hunks at doc lines 21 and 43).

Post-remediation confirmation on the materialized tree: grepping the audit-1 doc for the removed token yields zero hits. This validates the remediation's claim that audit-1's "cleanroom clean" was stale — audit-1 ran the gate before its own report was committed into the scanned tree, so the token it introduced was never caught by its own run. (This audit-2 report is worded to describe the token by mechanism, never by literal, so it does not itself trip the same gate — the mistake audit-1 made.)

---

## Regression scope

Diff `b1cc2a4..904cf2c` touched exactly four files:

```
asm_repo_staging/docs/audit/sf_split_h-audit-1.md
asm_repo_staging/docs/guides/split_h.md
asm_repo_staging/lib/macros/sf_split_h.inc
asm_repo_staging/tests/test_split_h_demo.py
```

- **No engine change:** `git diff --name-only b1cc2a4 904cf2c | grep -E "engine/|hdma_alloc"` → no match. `engine/hdma_alloc.asm` and all other engine files untouched.
- **Macro header change is COMMENT-ONLY:** every changed line in `sf_split_h.inc` is a comment line (`;` prefix); no code/macro-logic line changed (`git diff … | grep -vE '^[+-];'` on the +/- lines → empty). Macro LOGIC untouched.
- **Out-of-scope test items untouched:** the `$7C` first-fit enable-mask boot check (`test_boots_and_split_channels_armed`) and the D4 difference assertion (`test_d4_coldata_band_tints_floor`) show zero changes in the D2 diff. The test diff hunks are strictly: 2 new helper defs (`_amber_row`, `_floor_tex_row`) + the D2 test body + its docstring.

Scope is exactly the intended surfaces. No regression introduced.

---

## Gates (run on the materialized tree WITH all audit docs present)

```
$ bash tools/cleanroom_check.sh
cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)

$ make width-check
width-check: clean (182 files)

$ make zp-check
zp_lint: 0 finding(s) across 223 file(s); symbol table has 167 DP symbols covering 208 bytes
```

The materialized tree contains `docs/audit/sf_split_h-audit-1.md` (and the sibling split_v audit docs); cleanroom is clean WITH them present — the exact condition audit-1 failed to check.

---

## Test suite (fresh materialization)

```
$ bash asm_repo_staging/tools/dryrun_split.sh /tmp/kit_audit2
scrub_split: OK — 71 substitutions across 18 files; comment lineage guard clean
done — self-contained tree at: /tmp/kit_audit2

$ cd /tmp/kit_audit2 && make split_h_demo
built build/split_h_demo.sfc (cfg=lorom_64k.cfg)

$ bash templates/split_h_demo/build_split_h_variants.sh
built build/split_h_demo_nosplit.sfc  (NO_SPLIT=1)
built build/split_h_demo_nocolor.sfc  (NO_COLORBAND=1)
built build/split_h_demo_freeze.sfc  (FREEZE_BAR=1)
built build/split_h_demo_autodemo.sfc (AUTODEMO=1)

$ python -m pytest tests/test_split_h_demo.py -q
.......                                                                  [100%]
7 passed in 10.95s

$ python -m pytest tests/test_split_v_demo.py -q      # regression
......                                                                   [100%]
6 passed in 9.92s
```

7/7 split_h (including the tightened D2), 6/6 split_v (no regression).

---

## Framebuffer spot-check (re-rendered from a fresh build of HEAD)

Default rail, `build/split_h_demo.sfc` freshly built at HEAD `904cf2c`, captured at frame ~20:

```
NMI_HDMA_ENABLE $0108 = 0x7c   (expect 0x7c)
top instrument-amber pixels [6,34) = 1264   (archetype A top band present)
floor distinct colours [120,140)   = 5      (Mode-7 floor textured, >=4)
```

Screenshot `/tmp/kit_audit2_shots/default_spotcheck.png` (256x239): top instrument band (amber gauge segments on a frame rule) over a receding textured Mode-7 floor with a gold lane, single clean-scanline seam between them. Archetype A renders. The tightened D2 passes on this rendered frame (probe: 0 smeared rows flagged in the seam window).

Also saved: `/tmp/kit_audit2_shots/default.png` (probe capture).

---

## Paper cuts

No paper cuts this audit — clean run. Materialization, build, variants, tests, and all three gates worked first-try in the isolated worktree. The remediation was tightly scoped and each finding was independently verifiable.
