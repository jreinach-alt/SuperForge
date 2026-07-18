# Audit-1 — `split_v_fight` seamless rearchitecture

- **Branch:** `claude/superforge-seamless-split-rail-mt9q6b` @ `8352faf`
- **Sprint:** rebuild `templates/split_v_fight` on the SEAMLESS split core (proven by
  `templates/split_v_seamtrial`, PR #221 merged) — always-on centre window,
  continuous distance→spread divergence, beveled BG3 divider, fighters back as OBJ.
- **Kit materialized at:** `/tmp/kit_audit1` (via `asm_repo_staging/tools/dryrun_split.sh`)
- **Role:** independent audit-1 — research/verification only. No code changes, no remediation.
- **Aggregate verdict: CLEAN — ship.** All 4 acceptance criteria and all 5 landmines pass.
  The seamless invariant was independently re-derived and re-measured (merge diff = 0
  exactly, split diff = 11,432 px), the divider is full-height (span 14→230 of a 239 px
  frame, not truncated), and the tests read the actual rendered framebuffer (no
  proxy-variable / indirect-evidence assertions). One LOW observation (accept as-is).

---

## 1. Test suite — VERBATIM output

### `tests/test_split_v_fight.py` (5 tests)
```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/bin/python3
cachedir: .pytest_cache
rootdir: /tmp/kit_audit1
collecting ... collected 5 items

tests/test_split_v_fight.py::test_s1_merge_is_seamless PASSED            [ 20%]
tests/test_split_v_fight.py::test_s2_bar_ramps_from_zero PASSED          [ 40%]
tests/test_split_v_fight.py::test_s3_fighters_track_halves PASSED        [ 60%]
tests/test_split_v_fight.py::test_s4_autodemo_reaches_merge_and_split PASSED [ 80%]
tests/test_split_v_fight.py::test_s5_both_left_stays_in_arena PASSED     [100%]

============================== 5 passed in 25.60s ==============================
```

### `tests/test_split_v_demo.py` (retained `sf_split_v_diagonal` still works)
```
collected 8 items

tests/test_split_v_demo.py::test_d1_two_camera_split_clean_seam PASSED   [ 12%]
tests/test_split_v_demo.py::test_d2_cameras_scroll_independently PASSED  [ 25%]
tests/test_split_v_demo.py::test_d3_swept_seam_moves_boundary PASSED     [ 37%]
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 50%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 62%]
tests/test_split_v_demo.py::test_d6_diagonal_seam_slants PASSED          [ 75%]
tests/test_split_v_demo.py::test_d6_straight_seam_is_vertical PASSED     [ 87%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]

============================== 8 passed in 11.73s ==============================
```

### Gates
```
width-check: clean (179 files)
zp_lint: 0 finding(s) across 220 file(s); symbol table has 167 DP symbols covering 208 bytes
cleanroom: clean (name tripwire only — NOT a completeness guarantee; ...)
```
Direct lint of the two new files: `width_lint.py lib/macros/sf_split_v.inc
templates/split_v_fight/main.asm` → no findings; `zp_lint.py` same → exit 0.

---

## 2. Acceptance-criteria matrix

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Replace binary MERGED/SPLIT state machine + `sf_window_off` toggle + backdrop band with always-on centre window, continuous distance→spread (eased), beveled BG3 divider, fighters as OBJ | ✓ | `main.asm`: eased spread `L402-439` (ease `SPREADF` 8.8 toward `clamp((dx-MERGE_DX)/2,0,SPREAD_MAX)`, no hysteresis/state); no `sf_window_off` in the default path (only in the `.ifdef NOWIN` reference `L214`); fighters as OBJ `L454-462` (`spr #1`/`spr #2`); divider is BG3 bar via `sf_split_v_bevel` `L209` |
| 2 | Fold reusable bits into `lib/macros/sf_split_v.inc`: `sf_split_v_bevel` + per-frame `sf_split_v_spread`; keep `sf_split_v_diagonal` (unused here) | ✓ | `sf_split_v.inc`: `sf_split_v_bevel` `L258-373`, `sf_split_v_spread` `L391-448`, `sf_split_v_diagonal` retained `L162-188` and exercised by `test_split_v_demo.py::test_d6_diagonal_seam_slants` (PASS) |
| 3 | Rewrite `tests/test_split_v_fight.py` to assert SEAMLESSNESS on the framebuffer (merge ≈ no-split ref; bar ramps from zero; fighters track halves) — not "seam present/absent" | ✓ | `test_split_v_fight.py`: S1 pixel-diff merge vs `nowin` reference (`L140-153`), S2 bar-core ramp + full-height span (`L157-172`), S3 red-left/blue-right mean-x (`L176-188`). All read rendered pixels via `runner.take_screenshot` + PIL |
| 4 | Update `docs/guides/split_v.md` | ✓ | New "The SEAMLESS split" section + macro-table rows for `sf_split_v_bevel`/`sf_split_v_spread` + rewritten `split_v_fight` composition example (docs diff) |

### Landmine matrix (a–e)

| Landmine | Verdict | Evidence |
|---|---|---|
| (a) VRAM char-base ≥$8000 words wraps (15-bit) — BG3 CHR must be $7000, BG34NBA=$07 | ✓ | `sf_split_v.inc L268` `lda #$7000` → VMADD; `L282-283` `lda #$07 / sta $210C` (BG34NBA). Bar CHR sits at word $7000, no wrap |
| (b) BG3 scroll must be set explicitly (uninit = garbage) | ✓ | `sf_split_v.inc L345` `scroll #3, #0, #0` (comment L344 cites the landmine) |
| (c) NMI truncates 3 full tilemap DMAs at VBlank — static bar must survive | ✓ | Bar tilemap written UNDER FORCED BLANK (`L294` `sta $2100=$8F` ... `L337` `=$0F`) AND dirty bit cleared (`L338-340`, keep only BG1). BG3 shadow also populated as belt (`L329`). Independent render confirms bar full-height, span 14→230 (see §3) |
| (d) `ES_*` are OFFSETS — use absolute `BG_TILEMAP_DIRTY` | ✓ | `sf_split_v.inc L338/340` use `BG_TILEMAP_DIRTY`; `engine_state.inc L778` `BG_TILEMAP_DIRTY = ENGINE_STATE_BASE + ES_BG_TILEMAP_DIRTY` = `$013C` (absolute). Not the `ES_` offset `$3C` |
| (e) prove "invisible" by pixel-diffing vs a known-good render, not a derived metric | ✓ | S1 diffs the merge frame against the `-DNOWIN` single-camera reference ROM (an independent code path: window OFF + BG3 off TM); merge diff ≈ 0, split diff > 2000 for non-vacuity. Re-verified independently (§3) |

---

## 3. Independent re-derivation of the seamless invariant (my own measurement)

Re-derived from first principles: at `spread=0`, `cam_a = mid-0 = cam_b`, so BG1 and
BG2 show the identical camera; the always-on window merely selects "left half of view
A, right half of view B" of the SAME image → pixel-identical to a single-camera render.
The band `hw = spread>>4 = 0` writes an empty window-2 band (`WH2=1 > WH3=0`, `spread.inc
L432-441`) so window 2 is inactive and no divider pixel shows. As `spread` grows the
halves diverge (real content discontinuity) and the band opens.

Measured (my own script, both ROMs under MesenRunner @ 110 frames, 256×239 frame):

```
diff(merge, ref)  : 0        (seamless => ~0)                 [PASS — exact]
diff(split, ref)  : 11432    (non-vacuity => thousands)       [PASS]
bar_core merge    : 0        (expect 0)                        [PASS]
bar_core split    : 1085     (expect >600)                    [PASS]
bar_span split    : (14, 230)  full-height, bottom NOT truncated [PASS]
bar white-core rows: first=7  last=230  (frame h=239)         [PASS]
split red mean_x  : 67.5   (left half)                        [PASS]
split blue mean_x : 195.5  (right half)                       [PASS]
merge red mean_x  : 111.5 / blue 151.5 (both present, near centre)
```

Screenshots saved to `/tmp/e2e_screenshots/audit_{merge,split,nowin}.png`. What I SEE:
- **merge** and **nowin (reference)** are visually identical — one seamless landscape
  (blue sky, grey mountain, green hills, brown dirt), NO divider, red + blue fighters
  near centre. Diff = 0 confirms pixel identity.
- **split** shows a clean **vertical white beveled bar** down the centre, running the
  FULL height top-to-bottom (no bottom truncation), with the red fighter in the LEFT
  half and the blue fighter in the RIGHT half — each half a distinct camera of the same
  stage.

The invariant holds independently of the test's own numbers.

---

## 4. Indirect-evidence / proxy-variable scrutiny

- **S1 merge-diff is a TRUE pixel diff against a genuine reference, not a tautology.**
  The `-DNOWIN` reference is a *different code path* (`main.asm L211-222`: `sf_window_off`
  + `SHADOW_TM=$13` dropping BG3) — a single-camera render with no window and no divider.
  It is NOT the windowed ROM with the divider masked out, so a merge==ref match genuinely
  proves the split machinery contributes nothing at spread=0. Non-vacuity guard
  (`d_split > 2000`) present.
- **S2 "bar ramps from zero" is a REAL divider measurement.** `_bar_core` counts
  highlight-core white ($7FFF) pixels in the centre band `x∈[118,138)` — the actual
  rendered bevel, not a derived spread/hw variable. It additionally asserts full-height
  span (`ymin ≤ 26`, `ymax ≥ 220`), directly guarding landmine (c).
- **S3 reads mean-x of red/blue pixels** in the rendered frame — the fighters' actual
  on-screen positions, not their world-X globals.
- **S4** samples `_bar_core` across ~240 auto-demo frames and asserts both a merged
  (core ≤ 20) and split (core > 600) frame occur — reads pixels each sample.
- **S5 (arena clamp) reads `FX1`/`FX2` world-X** (DP $40/$42). This is the ONLY
  non-pixel assertion, and it is legitimate: the clamp's contract is literally to bound
  those two variables, so reading them IS reading the feature's output (the test docstring
  states this). Not a proxy.

No indirect-evidence assertions found.

---

## 5. Width-tracking review (two new macros)

- **`sf_split_v_bevel` (`L258-373`)**: enters A16/I16, toggles A8 for VMAIN/BG34NBA/
  forced-blank/dirty-clear byte writes, each followed by `rep #$30`+`.a16`+`.i16`; every
  branch target inside the tilemap loop (`b3barL L316`, `b3barR L321`, `b3store L325`,
  `b3fill L304`) carries explicit `.a16`/`.i16`. Exits A16/I16. WIDTH-RISK comment present
  (`L256-257`). Correct.
- **`sf_split_v_spread` (`L391-448`)**: enters A16, `beq empty` (`L411`) taken from A16;
  `empty` (`L432`) and `done` (`L443`) both annotated `.a16/.i16` and both reached in
  A16 (the `empty` arm does `rep #$20` before falling to `done`). The `pha`(A16, 2 bytes)
  … `sep #$20`/store/`rep #$20` … `pla`(A16, 2 bytes) sequence (`L414-421`) is
  stack-balanced across the A8 toggle. Correct.
- **`sta f:$7E0000 + SHADOW_BG3_TILEMAP, x` (`L329`)**: `SHADOW_BG3_TILEMAP = $B200`
  (16-bit WRAM addr), so `f:$7E0000 + $B200` is a full 24-bit constant → ca65 emits
  absolute-long,X ($9F), the ONLY long-indexed form (there is no long,Y — the macro
  correctly indexes with X and computes the byte offset from X, comment `L303`). Correct.
- **`BG_TILEMAP_DIRTY` dirty-clear (`L338-340`)**: `lda`/`and #$01`/`sta` on the absolute
  `BG_TILEMAP_DIRTY = $013C` (bank $00 WRAM, absolute addressing with DB=$00). Uses the
  absolute alias, not the `ES_` offset. Correct.

---

## Deviations / findings

| # | Finding | Severity | Recommendation |
|---|---------|----------|----------------|
| 1 | `SEAM_DIFF_MAX = 40` slack in S1 is generous; the actual merge diff is exactly 0 (measured). The slack does not mask any real seam (a real seam pop would be thousands of px, as the split-vs-ref 11,432 shows), but a subtle ≤40 px regression could slip through. | LOW | **Accept.** The comment (`test L54-58`) documents the rationale; the non-vacuity guard and the 11k px split gap make a masked regression implausible. Could tighten to `<= 8` in a future touch-up, but not blocking. |

No HIGH or MEDIUM findings.

## Ambiguities resolved

- **Is the `-DNOWIN` reference an independent path or a tautology?** Resolved:
  independent — window OFF + BG3 dropped from TM vs window ON + BG3 bar. A merge==ref
  match is a genuine seamlessness proof (§4).
- **Does the divider survive the VBlank multi-DMA truncation?** Resolved: yes — written
  under forced blank AND dirty-bit cleared AND shadow populated; independent render shows
  full-height span 14→230 with no bottom truncation (§3, landmine c).
- **Is `sf_split_v_diagonal` still functional after being folded/retained?** Resolved:
  yes — `test_split_v_demo.py::test_d6_diagonal_seam_slants` PASS.

---

## Aggregate verdict: **CLEAN — ship.**

All 4 acceptance criteria ✓, all 5 landmines ✓, seamless invariant independently
re-derived and re-measured, no indirect-evidence assertions, width-tracking correct, all
gates green. The single finding is LOW and accepted as-is. Audit-2 not required.
