# sf_split_v — audit-6 (remediation validation)

**Scope:** Independent validation ("audit-2" step) of the remediation commit `8d77a22`
on branch `claude/split-v-diagonal-seam` for the DIAGONAL coloured seam. The core feature
was already audited CLEAN in audit-5; this audit validates ONLY the three fixes (M1/M2/L1)
in `engine/hdma_engine.asm`, function `hdma_build_split_diag` + helpers.

**Verdict: CLEAN.** All three fixes are correct. No new finding introduced by the
remediation. Gates clean, 8/8 tests pass ×3, diagonal render still slants.

## Findings table

| ID | Fix | Correct? | Evidence |
|----|-----|----------|----------|
| M1 | `HDMA_SPLITD_BBAD` = `HDMA_SPLITD_OFF` ($0197), off the $0199 collision | YES | Disjointness trace below; 8 words fit $0189-$0198 exactly, no overrun into $0199/$019A |
| M2 | check `hdma_alloc == $FFFF` after ALL 3 allocs, no-op if <3 free | YES | Every alloc has `cmp #$FFFF / beq @fail`; `@fail` is `.a16 / rts` before any config/enable |
| L1 | `cpx #225` -> `cpx #HDMA_SCANLINES` | YES | `HDMA_SCANLINES = 225` (hdma_engine.asm:17); loop covers scanlines 0..224 |

## M1 — aliasing disjointness trace (the adversarial focus)

Symbols: `HDMA_SPLITD_OFF = $0197` (2 bytes → $0197-$0198); `HDMA_SPLITD_BBAD = $0197`
(aliased). The last scratch byte is $0198; $0199 = `ES_STREAM_DMA_CHAN`,
$019A = `ES_M7S_PTR` (engine_state.inc: iris sub-block claimed $89-$98 = 16 bytes; the 8
SPLITD words CH0..OFF occupy $0189-$0198 exactly). **No overrun.**

Time-ordering in `hdma_build_split_diag`:

- **CONFIG phase** (lines 2864-2876): three (write BBAD → `jsr _hdma_splitd_cfg`) pairs.
  `_hdma_splitd_cfg` READS `HDMA_SPLITD_BBAD` at line 2934 (A8, low byte $0197) and never
  touches OFF. The 3rd cfg call `rts` (2945) returns to line 2877.
- **FILL phase** (lines 2878-2900): the FIRST write to `HDMA_SPLITD_OFF` is `stz` at line
  2888, strictly AFTER the 3rd cfg returned. `_hdma_splitd_fill` reads `HDMA_SPLITD_OFF`
  (line 2972) and never touches BBAD.

Therefore every BBAD read completes before any OFF write. **No path reads BBAD after OFF
is written for the same pass.** The stale BBAD value ($0029, last config) sitting in $0197
is unconditionally overwritten by the fill phase's OFF store before any fill reads it — no
stale-read hazard. The A16 BBAD store to $0197 writes $0197-$0198 and does NOT touch ACC
($0195-$0196) or any other live scratch — no adjacency corruption. Aliasing is safe.

## M2 — alloc-failure handling

Lines 2844-2859: each of the three `jsr hdma_alloc` is followed by `cmp #$FFFF / beq @fail`;
on all-success `bra @alloc_ok` skips `@fail`. `@fail` (2857) is `.a16 / rts` — it configures
and enables NOTHING, so no garbage `$43n0`/table writes occur under channel contention.
`@fail` (.a16) and `@alloc_ok` (.a16/.i16) are correctly width-annotated multi-path labels
(width-check clean confirms).

Partial-alloc leak: `hdma_alloc` reserves a channel per successful call (via `hdma_request`);
if alloc 3 fails after 1 & 2 succeed, those two channels stay reserved until `hdma_off`. This
is a bounded leak, acceptable for the static arm-once builder and consistent with the
"no-op if <3 free" docstring. Noted, not a defect.

## L1 — HDMA_SCANLINES

`HDMA_SCANLINES = 225` (hdma_engine.asm:17). Fill loop: X from 0, `inx`, `cpx #HDMA_SCANLINES`,
`bne @line` → 225 iterations (scanlines 0..224), then terminator. Identical behaviour to the
old literal, now symbolic. Correct.

## Regression verification (fresh materialization)

- `make width-check`: clean (177 files) — the new `@fail`/`@alloc_ok` targets and the alias
  introduce no new width-lint finding vs baseline.
- `make zp-check`: 0 findings (218 files, 167 DP symbols / 208 bytes).
- `tools/cleanroom_check.sh`: clean.
- `tests/test_split_v_demo.py`: 8 passed ×3 (three consecutive runs).

## Owner-validated render (diagonal ROM, settle frames)

Rendered `build/split_v_demo_diagonal.sfc` (boot marker `SFDB`, +20 frames). White seam-bar
centre X per screenshot row (256×239 capture):

```
y= 20 -> 78    y= 60 -> 98    y=100 -> 118   y=140 -> 138   y=180 -> 158
y= 40 -> 88    y= 80 -> 108   y=120 -> 128   y=160 -> 148   y=200 -> 168
```

Monotonically rising, ~0.5 px/scanline slope — the seam SLANTS (centre rises top→bottom),
matching the ~72 + s*0.5 design (the constant ~4 px offset is the screenshot's top-overscan
crop; the slope is exact). Render unchanged from audit-5.

## New findings introduced by the remediation

None.
