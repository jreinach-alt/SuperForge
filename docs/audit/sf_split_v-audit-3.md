# sf_split_v — audit-3 (visible-divider + player-markers + autodemo REWORK)

**Scope:** commit `2449ee2` on `claude/sf-split-v-9mkvvo` ONLY — the third demo rework in
response to owner visual feedback ("no visible frame between the views; what are the white
squares; surface the .sfc"). Net change vs audit-2's `d4856c7`:

- a full-height WHITE DIVIDER BAR (16px, two 8x8 OBJ columns at `seam-8` and `seam`, drawn
  in a per-frame `@divcol` Y loop) framing the seam — also the new D4 OBJ-clip subject;
- two RED player markers (OBJ tile 2, palette slot 2), one grounded in each half;
- a `-DAUTODEMO` build that ignores input, auto-pans the two cameras in opposite directions
  and triangle-sweeps the seam (reaches the commit point via `jmp @commit`);
- DP aliases `DIVY`/`RCOLX`/`FRC` reusing the setup-only scratch `T_MX`/`T_MY`/`T_TILE`
  (`$48/$4A/$4C`);
- the horizon test now returns `None` for white (divider) columns and every comparison
  skips `None`; the seam discontinuity is sampled just OUTSIDE the 16px bar; D4 asserts the
  DIVIDER clip with a non-vacuity companion; `build_split_v_variants.sh` adds the
  `_autodemo` ROM.

`diff d4856c7..2449ee2` touches only `templates/split_v_demo/main.asm`,
`templates/split_v_demo/build_split_v_variants.sh`, `tests/test_split_v_demo.py`,
`docs/roadmap.md`. The `sf_split_v` macro (`lib/macros/sf_split_v.inc`) and the height-map
landscape are **byte-identical** to audit-2 — not re-audited except where the new OBJ code
interacts.

**Independent agent** — did not author the code or any prior rework. Research-only; no code
changes, nothing pushed.

**Method:** two independent fresh materializations (`tools/dryrun_split.sh`), gates + suite
run ≥5× total, cycle-accurate Mesen2 framebuffer renders, ca65 listing inspection for the
new `@divcol`/`@commit` width contracts and the autodemo math, multi-seed power-on probes,
and direct non-vacuity probes (feeding a single-camera render through the D1/D4 logic).

---

## OVERALL VERDICT: **CLEAN**

All D1–D5 + clean-room + the three gates (width / zp / cleanroom) pass on fresh
materialization. The suite is **stable across 5 runs / 2 materializations** (the divider
`None`-exclusion path — flagged as the top flakiness risk — showed zero variance). The new
`@divcol` divider loop and the dual-entry `@commit` label are width-correct at the
encoded-byte level (both entries A16/I16; no A8 leak). The AUTODEMO triangle-sweep is proven
to stay inside `[SEAM_LO, SEAM_HI]` = `[64,190] ⊂ [64,192]` with no underflow/overflow, and
its `jmp @commit` cleanly skips the whole input path. The DP aliases have **no live-range
overlap** (`T_*` are read only in the setup fill loop, which completes before the game loop).
The divider-exclusion tests remain **non-vacuous and do not hide cross-bleed** (verified by
running a single-camera render through the D1/D4 logic — every sub-assertion fails as it
should). Sprite budget is fine (52 sprites/frame total, ≤2–3 per scanline). No HIGH or
MEDIUM findings; 2 LOW (1 inherited cosmetic, 1 observation), all accept/defer.

---

## Per-criterion results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| D1 | left=camA / right=camB / clean straight seam / zero bleed | ✓ | `test_d1_two_camera_split_clean_seam` PASS. W12SEL=$32, TMW=$03, seam=128 (asserted at hardware shadows). Left half matches camera-A reference 110/110 columns; right half diverges; seam discontinuity = 64 (> 20 threshold). `tests/test_split_v_demo.py:177-209`. Render confirms two distinct silhouettes. |
| D2 | independent per-camera input | ✓ | `test_d2_cameras_scroll_independently` PASS. P1 moves only the left horizon (`_changed`>10 left, ==0 right); P2 the mirror. `tests/test_split_v_demo.py:213-237`. |
| D3 | swept seam moves the boundary | ✓ | `test_d3_swept_seam_moves_boundary` PASS. A fixed band [140,166) flips B→A as the seam sweeps right past it, then A→B back; seam shadow moves right then left. `tests/test_split_v_demo.py:251-281`. |
| D4 | straddling divider clipped to its half (OBJ window) | ✓ | `test_d4_obj_window_clips_divider_at_seam` PASS (TMW=$13; white columns left-of-seam present, **zero** at/across seam) + `test_d4_default_divider_not_clipped` companion (TMW=$03; white DOES cross). `tests/test_split_v_demo.py:295-320`. Render confirms half-bar + right marker gone under objclip. |
| D5 | `-DNO_WINDOW` collapses → D1 signature ABSENT | ✓ | `test_d5_no_window_collapses_to_single_camera` PASS. W12SEL=$00, TMW=$00; seam discontinuity = 0 (< 6 threshold). `tests/test_split_v_demo.py:324-340`. Render = one continuous landscape, no divider. |
| Clean-room | no retail-title / lineage vocab in `asm_repo_staging/` | ✓ | Materialized kit `cleanroom_check.sh` = **clean**. The gate's lineage + commercial regexes run against all 3 changed files = clean. (The staging-tree FAIL is only `tools/scrub_split.py`'s own term-list source — a build-time tool NOT shipped into the kit; pre-existing, not from this rework.) |
| Gate: width-check | clean | ✓ | `width-check: clean (177 files)`. |
| Gate: zp-check | clean | ✓ | `zp_lint: 0 finding(s) across 218 file(s)`. |
| Gate: cleanroom | clean (materialized) | ✓ | `cleanroom: clean` on `/tmp/audit3_kit` and `/tmp/audit3_kit2`. |

### Suite stability (top flakiness risk: the divider `None`-exclusion horizon read)

```
RUN 1 (mat #1): 6 passed in 10.05s
RUN 2 (mat #1): 6 passed in  9.86s
RUN 3 (mat #1): 6 passed in  9.87s
RUN 4 (mat #1): 6 passed in  9.87s
RUN 5 (mat #2, second independent materialization): 6 passed in 10.04s
```
Zero failures, zero variance. Multi-seed power-on probe (4 random-RAM boots of the default
ROM): seam=128, discontinuity=64, left-match 110/110 on every boot — bit-stable.

---

## VISUAL re-render (Mesen2, 30 settle frames; autodemo a/b ~40 frames apart)

- **default** — two viewpoints of the landscape (left silhouette ≠ right silhouette → two
  genuine cameras of one world), a clean full-height WHITE divider bar centred on the seam,
  one RED player marker grounded in each half. Matches the intended "two views framed by a
  white divider with a red marker per half."
- **`_objclip`** — the divider is now a HALF-bar: only the left column (x=seam-8) survives;
  the right column (x=seam) and the right-half red marker are both clipped away by the OBJ
  window. Exactly the D4 per-half clip signature.
- **`_nowin`** — one continuous landscape (single full-screen camera A), NO divider, NO
  markers, no seam step. The D5 collapse.
- **`_autodemo`** (two frames ~40 apart) — between frames the seam has moved and the two
  halves have panned in OPPOSITE directions (left half scrolled the mountain off-left; right
  half revealed different terrain), with the divider sweeping across. The primitive plays out
  in motion with no controller.

(Renders captured to `/tmp/audit3_shots/{default,objclip,nowin,autodemo_a,autodemo_b}.png`
and inspected by eye during this audit.)

---

## ADVERSARIAL findings

### Width discipline — `@divcol` and the dual-entry `@commit` (CLEAN)
From the ca65 listing (autodemo build, the most complex path):
- `sf_frame_begin` exits **A16** (`.a16` at its tail), so the autodemo block runs A16
  throughout (`and #$00FF` encodes `29 FF 00` — 3-byte immediate, confirming A16).
- `@commit` is a **multi-path label** (the autodemo `jmp @commit` AND the input
  fall-through). The input path runs entirely under `btn` (`rep #$30` → A16/I16) and ends
  `lda SEAM / … / sta SEAM` in A16; the autodemo path jumps in A16. Both entries are A16/I16
  and the label is annotated `.a16 .i16`. No leak.
- `@divcol` is reached by fall-through (`sta DIVY`, A16) and by `bcc @divcol` (loop tail,
  A16); annotated `.a16 .i16`. Consistent.
- `make width-check` clean (177 files) corroborates the by-hand byte trace.

### AUTODEMO triangle-sweep math (CLEAN)
`phase = FRC & $7F` (0..127); for `phase ≥ 64`, `phase ^= $7F` (= 127−phase → 63..0); so the
folded value ∈ [0,63]. `seam = (folded << 1) + SEAM_LO` ∈ [64, 64+126] = **[64,190]**, which
sits inside `[SEAM_LO, SEAM_HI] = [64,192]` — no underflow, no overflow, no clamp gap. The
`asl a` runs on a value ≤63 in A16 (safe). `jmp @commit` skips the entire input read block
with no fall-through (verified in the listing: jump at `0007D6` lands at `@commit` `000879`,
bypassing every `btn`). Markers at seam±48 ∈ [16,238] and divider columns at seam-8/seam stay
on-screen across the whole sweep. CLEAN.

### DP alias reuse `DIVY`/`RCOLX`/`FRC` over `T_MX`/`T_MY`/`T_TILE` (CLEAN)
`T_MX/T_MY/T_TILE` ($48/$4A/$4C) are referenced ONLY inside the setup tilemap-fill loop
(`main.asm:146-197`), which completes before `game_loop:` (line 231). `DIVY/RCOLX/FRC` are
referenced ONLY at/after `game_loop` (lines 238-345). No instruction reads a `T_*` symbol
after the game loop begins → **no live-range overlap**. (`FRC` is read uninitialized at first
game-loop entry, but it is a free-running frame counter feeding `and #$007F` into a triangle
wave — a random start phase has no correctness impact. See LOW-2.)

### Non-vacuity of the divider-exclusion tests (CLEAN — genuinely discriminating)
The white-column exclusion masks ONLY the divider columns (the 16px bar at the seam). D1's
left compare runs `[8, seam-10]` and right `[seam+10, 248]` — both OUTSIDE the bar — so
cross-bleed in either half would still register (it is not a divider column and is not
excluded). Camera-B bleed across the left half would surface in the many non-divider columns
there. Direct probe: feeding the single-camera (`_nowin`) render through the D1/D4 logic →
seam discontinuity = 0 (D1 needs > 20: FAIL, good), right-half divergence = 0.0 (needs > 0.4:
FAIL, good), white-column count = 0 (D4-default needs across-seam white: FAIL, good). The
exclusion does NOT let a single-camera/broken-split ROM pass, and does NOT hide cross-bleed.

### Sprite budget (CLEAN)
`@divcol` runs DIVY = 8,16,…,200 (< DIV_BOT=208) → 25 iterations × 2 columns = 50 divider
sprites + 2 player markers = **52 sprites/frame**, within the engine's 128-OAM cap
(`engine_spr` `cmp #128`, sprite_engine.asm:64-65). The divider is two vertical columns of
non-overlapping 8x8 sprites (8px tall, 8px step) → **≤2 sprites per scanline** for the bar,
+1 on a marker row → far under the 32/scanline limit. No overflow / dropped-sprite / flicker;
the render shows a clean continuous bar.

### Power-on fidelity / BG3 occlusion (CLEAN)
Harness defaults to `RamPowerOnState=Random` (true per-power-cycle randomness over WRAM /
VRAM / CGRAM / OAM). 4 explicit random-RAM boots + 5 full suite runs all render identically
(seam=128, disc=64, 110/110 left-match). BG3 (enabled by `gfxmode #1`) produces no visible
garbage on any boot — fully occluded by BG1/BG2 priority — i.e. the new OBJ code does not
disturb the prior audits' BG3-occlusion result. CLEAN.

### Clean-room grep (CLEAN)
The gate's eliminated-lineage list and its commercial/hardware/sample-pack name list (both
from `tools/cleanroom_check.sh`) return ZERO hits on `main.asm`,
`build_split_v_variants.sh`, and `test_split_v_demo.py` (the only changed source files;
roadmap.md also clean). The new comments are mechanism-only. Materialized-kit
`cleanroom_check.sh` = clean.

---

## Findings ledger

| ID | Severity | Finding | Recommendation |
|----|----------|---------|----------------|
| LOW-1 | LOW | Pillow `getdata` DeprecationWarning (11×) — inherited, kit-wide, cosmetic. | **Defer** (same as audit-1/-2). |
| LOW-2 | LOW | `FRC` (autodemo frame counter, =$4C) is read uninitialized at first game-loop entry; with random power-on RAM the seam starts at a random triangle-wave phase. No correctness impact (free-running counter, immediately masked), but the autodemo's first seam position is non-deterministic boot-to-boot. | **Accept** — harmless; an explicit `stz FRC` before the loop would make the first frame deterministic if ever desired (optional polish, not required). |

No HIGH or MEDIUM findings. The rework is correct, width-safe, non-vacuous, clean-room clean,
and gate-clean on fresh materialization. **SHIP.**
