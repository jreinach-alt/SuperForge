# split_v_fight (seamless) — AUDIT-2: side-SWAP support

**Auditor:** independent audit-2 agent (research/verification only; no code changed)
**Commit under audit:** `7e867d8` "split_v_fight: support fighters SWAPPING sides (position-based assignment)"
**Branch:** `claude/superforge-seamless-split-rail-mt9q6b` (reviewed at HEAD `7e867d8`, checked out detached)
**Diff base:** `origin/claude/split-mode-spec...HEAD` (swap change is the top commit `7e867d8`)
**Materialized kit:** `/tmp/kit_audit2` (via `asm_repo_staging/tools/dryrun_split.sh`)
**Predecessor:** `split_v_fight_seamless-audit-1.md` (audited the seamless core CLEAN)

## Aggregate verdict: **CLEAN — ship.**

The side-swap extension is correct, seamless, and non-vacuously tested. I independently
reproduced every claimed property by my own pixel + OAM measurement (not trusting the test's
numbers), stress-tested the crossing, the tie-break, the OAM edges, and the independent clamp,
and confirmed the audit-1 seamless properties (S1–S4) do not regress. Two **LOW** cosmetic
comment-drift nits (autodemo still described as "ping-pong apart/together" in two header
comments) are the only findings — accept or fix at leisure; no functional impact.

---

## 1. Suite + gates (verbatim, from the materialized kit)

`make split_v_fight && bash templates/split_v_fight/build_split_v_fight.sh` build all six
variants (incl. the new `split_v_fight_cross.sfc`) with only the pre-existing benign
`BANK1 does not exist` ld65 warning.

```
$ PYTHONPATH=. python3 -m pytest tests/test_split_v_fight.py -v
tests/test_split_v_fight.py::test_s1_merge_is_seamless PASSED            [ 14%]
tests/test_split_v_fight.py::test_s2_bar_ramps_from_zero PASSED          [ 28%]
tests/test_split_v_fight.py::test_s3_fighters_track_halves PASSED        [ 42%]
tests/test_split_v_fight.py::test_s4_autodemo_reaches_merge_and_split PASSED [ 57%]
tests/test_split_v_fight.py::test_s5_both_left_stays_in_arena PASSED     [ 71%]
tests/test_split_v_fight.py::test_s6_crossed_state_frames_correctly PASSED [ 85%]
tests/test_split_v_fight.py::test_s7_autodemo_swaps_sides PASSED         [100%]
============================== 7 passed in 45.85s ==============================
```

`test_split_v_demo.py` (the seamless-core rail): **8 passed** (D1–D6, unchanged).

Gates:
```
width-check: clean (179 files)
zp_lint: 0 finding(s) across 220 file(s); 167 DP symbols, 208 bytes
cleanroom: clean (name tripwire only)
```

**S1–S4 (audit-1 seamless properties) still hold** — S1 merge is pixel-seamless vs the
`nowin` reference, S2 the beveled divider ramps 0→full, S3 fighters track their halves, S4 the
(now cross-over) autodemo reaches both a merged and a split frame with the divider bounded and
re-merging. The swap change did not regress seamlessness.

## 2. Independent pixel + OAM measurement (my own, not the test's)

My own colour predicates and mean-X, at ~110 frames, plus a raw OAM decode (idx, X9, Y, tile):

| Build | FX1 | FX2 | red mean-X | blue mean-X | bar_core | bar_span | OAM (left, right) |
|---|---|---|---|---|---|---|---|
| NORMAL `-DHOLD=100` | 28 | 228 | **67.5** (L) | **195.5** (R) | 1085 | (14,230) | tile1@x64, tile2@x192 |
| CROSSED `-DHOLD=-100` | 228 | 28 | **195.5** (R) | **67.5** (L) | 1085 | (14,230) | tile2@x64, tile1@x192 |

- **NORMAL → red left (<128), blue right (>128); CROSSED → red right, blue left** — an exact
  mirror. Confirmed.
- Both states place the fighters at screen-X **64 / 192**, i.e. toward the **inner halves
  framing the seam** (~68/~196 by pixel mean), **NOT** stranded at the outer edges (~11/~251).
  The only thing that changes between NORMAL and CROSSED is which colour/tile is drawn at
  64 vs 192 (tile1=red, tile2=blue swap OAM slots) — screen framing is preserved. Confirmed.
- Divider present + **full-height** in the crossed state: `bar_core`=1085 (>600),
  span (14,230) = top overscan cutoff through the floor. Confirmed.
- Visual (screenshots `/tmp/audit2_shots/normal.png`, `crossed.png`): I SEE a full-height
  white divider down the centre; NORMAL has the red block just left of the seam and the blue
  block just right; CROSSED is the mirror (blue left, red right). Backgrounds identical.

**Autodemo cross-over** (my sweep, red seen where):
- red_left=**True**, red_right=**True** (red genuinely traverses both halves — it starts at the
  left wall and marches to the right wall through the other fighter). blue likewise both halves.
- Min `bar_core` while the two are within 24px of each other = **0** — the crossing IS a
  seamless merge. Screenshot `/tmp/audit2_shots/auto_cross.png`: at FX1=125/FX2=131 there is
  **no divider bar**, the red+blue blocks are coincident at centre, background continuous.

## 3. Adversarial / edge scrutiny (tested on the emulator)

**(a) Exact crossing frame / tie-break (`beq → red_left`).** Fine single-frame sweep across a
live autodemo crossover, and a dedicated static `-DHOLD=0` (FX1==FX2==128) build:
- `-DHOLD=0`: FX1=FX2=128 → `bar_core=0` (fully merged, no divider), both sprites at screen
  x=128 (tile1 red + tile2 blue overlapped). The tie-break renders one clean single-view frame.
- Live crossover, frame-by-frame: `f66` FX1=122<FX2=134 (red left, OAM tile1@124/tile2@132) →
  `f67` FX1=126<FX2=130 (red still left, 127/129) → `f68` FX1=129>FX2=127 (**crossed**, OAM
  tile2@127/tile1@129 — the assignment flipped). `bar_core=0` on **every** frame across the
  flip. The tile/colour swap happens while the two sprites are essentially coincident and the
  view is merged → **no 1-frame flicker, pop, or gap.**

**(b) OAM X9 / off-screen wrap.** Raw OAM decode at both static extremes and near the crossing:
all active sprite screen-X values were 64/192 (extremes), 121–135 (near crossing) — every one
in [0,255] with the **X9 high bit clear**. No fighter wraps or ghosts to the wrong edge. The
"no OAM X9 handling needed" claim holds because screen-X = (worldX−cam)&$FF stays in-range by
the spread-tracking construction.

**(c) Independent-clamp F-1 escape.** Drove the interactive build 300 frames per case:
| input | FX1 | FX2 | in [24,232]? |
|---|---|---|---|
| both LEFT | 24 | 24 | ✅ |
| both RIGHT | 232 | 232 | ✅ |
| f1→R, f2→L (cross-press) | 232 | 24 | ✅ |
| f1→L, f2→R | 24 | 232 | ✅ |
Neither fighter underflows/overflows; both can occupy the same wall value (they walk through
each other freely). The old F-1 escape (FX1 marching to −272) is impossible: each FX is clamped
to the fixed arena with no reference to the other, and because movement is incremental (±2/frame)
the clamp fires while the value is still positive, so a 16-bit wrap is never reached. Confirmed.

**(d) Are S6/S7 vacuous / confoundable?** No.
- **S6** asserts `blue < 128 < red` AND `40<blue<128` AND `128<red<216` AND divider core>600
  AND full-height — "both on one side" would fail the split test, and stranded-at-edges would
  fail the inner-band bounds. It also cross-checks the NORMAL split (`red<128<blue`) in the same
  test, so it cannot pass if the layout were hard-coded to one orientation. Robust.
- **S7** requires red in BOTH halves (`rx<108` and `rx>148`) — which can only happen if red
  actually crosses from the left wall past the other fighter to the right — AND
  `min core when close ≤ 20`, which I independently reproduced as 0. It cannot pass without a
  real crossover + seamless merge. Robust.

**(e) Width-tracking (manual re-read + `make width-check`).** All new branch/fall-through
targets are annotated and match runtime width:
- Position-dispatch OBJ block (`main.asm:499–545`): entry is A16 (sf_split_v_spread exits A16);
  `lda FX1 / cmp FX2` is a valid unsigned 16-bit position compare (FX in [24,232], never
  negative); `@red_left`, `@blue_left`, `@fighters_drawn` all `.a16 .i16`; the two long arms
  correctly use `jmp` (targets are past two `spr` pairs, out of ±127 branch range).
- Independent clamp (`main.asm:378–401`): `@f1_hi/@f1_store/@f2_hi/@f2_store` all `.a16`.
- Autodemo state machine (`main.asm:275–339`): `@to_right/@dwell_a/@to_left/@dwell_b_done/
  @dwell_a_done/@moved` all `.a16 .i16`; FDIR compares are 16-bit but FDIR is only ever set via
  `lda #imm`/`stz` in A16, so the high byte is always 0 — compares valid.
`make width-check` clean (179 files).

## 4. Docs vs code

- `lib/macros/sf_split_v.inc` header (`sf_split_v_spread`): the old "the split_v_fight rail
  PREVENTS crossing with its FX1<FX2 clamp" wording is **gone**; it now correctly states the
  caller must re-pick the actor↔camera assignment BY POSITION each frame, the macro is symmetric
  in mid/spread, and "split_v_fight does the position assignment every frame, so its fighters can
  cross and SWAP sides seamlessly." Matches the code.
- `docs/guides/split_v.md` "Side-switching": rewritten from the "invariant / prevents crossing"
  framing to describe genuine swap support (position re-pick each frame, independent arena clamp,
  S6/S7 as proof). Matches the code.
- No stale `MIN_GAP`, `OPEN_MAX/OPEN_MIN`, "prevents crossing", or "FX1<FX2 clamp" references
  remain in the guide, macro, or template (grep clean; the one `FX1 < FX2` hit is a correct
  in-code comment on the dispatch branch).

## 5. Findings

| # | Sev | File:line | Finding | Recommend |
|---|---|---|---|---|
| F-1 | LOW | `templates/split_v_fight/main.asm:38` | Header comment: "-DAUTODEMO … the fighters ping-pong apart/together on their own." The autodemo is now a wall-to-wall **cross-over** (they march THROUGH each other and swap sides), not an apart/together ping-pong. Cosmetic drift; the detailed state-machine comment at :268 is correct. | accept or fix (1-line) |
| F-2 | LOW | `templates/split_v_fight/build_split_v_fight.sh:6` | Same stale "ping-pong apart/together" phrasing in the autodemo variant's header comment. | accept or fix (1-line) |

No MEDIUM or HIGH findings. Optional nicety (not a finding): the `-DHOLD=n` header comment at
`main.asm:39–41` doesn't mention that a NEGATIVE n produces a crossed/swapped state (the build
script and the RESET comment both do), so it's covered elsewhere.

## Evidence artifacts
- Screenshots: `/tmp/audit2_shots/{normal,crossed,auto_cross,tie}.png`
- Measurement scripts: `/tmp/kit_audit2/audit2_measure.py`, `audit2_adv.py`
