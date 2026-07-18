# split_v_fight — audit-1 (feature audit)

**Scope:** Independent audit of the `templates/split_v_fight/` rail (the distance-driven
merge/split camera director) on branch `claude/split-v-diagonal-seam` — `main.asm`,
`build_split_v_fight.sh`, `tests/test_split_v_fight.py`, and the `docs/guides/split_v.md`
composition section. Fresh independent agent (not the implementer), materialized-kit build +
Mesen2 framebuffer verification, gates run for real.

**Verdict: PASS with findings.** The director reaches both states, the diagonal seam appears
only in SPLIT, fighters land in opposite halves, input drives the transition, gates clean,
11/11 tests pass (8 demo + 3 fight). Two actionable findings (one Medium, one Low) plus one
pre-existing observation.

## Findings table

| ID | Sev | Summary | Status |
|----|-----|---------|--------|
| F-1 | Medium | Interactive clamp escapes the arena when both fighters press the SAME direction at the minimum gap | fixed |
| F-2 | Low | No test covers the both-same-direction clamp edge — the escape was invisible to CI | fixed |
| OBS-1 | — | Power-on frame flap (window recipe not latched until the first NMI); pre-existing, family-wide, not a regression | not fixed (out of scope) |

## F-1 — clamp escape (Medium)

`main.asm` interactive branch clamped fighter 1 with a **both-relative** rule: FX1 was pinned
to `[ARENA_LO, FX2-MIN_GAP]`. When BOTH fighters walk left at the minimum gap, FX2 drops below
`ARENA_LO+MIN_GAP`, so the `FX2-MIN_GAP` upper bound drags FX1 *below* the floor. FX1 then
chases FX2 leftward every frame with nothing anchoring it to the arena.

**Reproduced** (materialized kit, default build, P1+P2 both LEFT for 200 frames): FX1 ($40)
reached `65264` = −272 (16-bit underflow), i.e. the fighter walked hundreds of pixels off the
left edge. The camera followed it off-stage.

**Fix (FX1-primary ordering):** FX1 is clamped to the FIXED arena range
`[ARENA_LO, ARENA_HI-MIN_GAP]` with **no reference to FX2**, so it can never escape; FX2 is
then clamped to `[FX1+MIN_GAP, ARENA_HI]`. Because `FX1 <= ARENA_HI-MIN_GAP`, the FX2 range is
always non-empty and FX2 likewise can never leave the arena. Both-same-direction input now
parks both fighters against the wall with the gap intact (the trailing fighter shoves the lead
one, which is the natural fighting-game behaviour). Per-frame `WALK_SPD=2` << `ARENA_LO=24`, so
the clamp always catches the boundary before any 16-bit underflow.

## F-2 — missing clamp-edge test (Low)

The F1/F2 tests drove the fighters in OPPOSITE directions only (apart, then together), which
never exercises the escape path. Added `test_f3_both_left_stays_in_arena`: drives BOTH fighters
LEFT for 200 frames, then asserts `ARENA_LO <= FX1 <= ARENA_HI`, `ARENA_LO <= FX2 <= ARENA_HI`,
`FX1 <= FX2`, and `FX2-FX1 >= MIN_GAP`. Fails against the pre-fix ROM (FX1 = 65264 > ARENA_HI),
passes against the fixed ROM.

## OBS-1 — power-on flap (not a regression, out of scope)

For the first frame(s) before the initial NMI commits the window recipe, the split can flash.
This is the same power-on-fidelity behaviour the whole `sf_split_v` family shows (kit rule #5:
never zero-init to hide it). It is pre-existing and not introduced by this rail; left as-is.

## Verification

- Gates: `width-check` clean (178 files), `zp-check` 0 findings, `cleanroom_check` clean.
- Tests: `test_split_v_fight.py` 4/4 (incl. the new F-3), `test_split_v_demo.py` 8/8.
- Render: MERGED frame = no seam bar + both fighters visible; SPLIT frame = diagonal white
  seam + red fighter left / blue fighter right; input toggles the transition.
