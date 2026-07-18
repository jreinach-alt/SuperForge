# split_v_fight — audit-2 (remediation validation)

**Scope:** Independent validation ("audit-2" step) of remediation commit `ee041dd` on branch
`claude/split-v-diagonal-seam` — the F-1 (clamp escape) and F-2 (missing test) fixes from
audit-1. Fresh independent agent (not the implementer, not audit-1). Worktree-isolated,
materialized-kit build, Mesen2 framebuffer + WRAM verification.

**Verdict: CLEAN.** The FX1-primary clamp holds; the F-3 test discriminates; gates green;
renders confirmed. No new finding introduced by the remediation.

## Gates & tests (materialized kit)

- `width-check`: clean (178 files) · `zp-check`: 0 findings (219 files) · `cleanroom_check`: clean.
- Build: `split_v_fight.sfc` + `split_v_fight_autodemo.sfc` both built (only the pre-existing
  benign `BANK1 does not exist` ld65 warning).
- `pytest test_split_v_fight.py test_split_v_demo.py`: **12 passed** (4 fight + 8 demo).

## F-1 — clamp holds (four emulator traces, WRAM read after 300 frames of jammed input)

Invariant: `ARENA_LO(24) <= FX1 <= FX2 <= ARENA_HI(232)` and `FX2-FX1 >= MIN_GAP(16)`.

| Input | FX1 | FX2 | gap | result |
|-------|-----|-----|-----|--------|
| both-LEFT | 24 | 40 | 16 | HOLD |
| both-RIGHT | 216 | 232 | 16 | HOLD |
| cross-in (P1→ P2←) | 216 | 232 | 16 | HOLD |
| spread-out (P1← P2→) | 24 | 232 | 208 | HOLD |

both-LEFT parks at `[ARENA_LO, ARENA_LO+MIN_GAP]=(24,40)`; both-RIGHT at
`[ARENA_HI-MIN_GAP, ARENA_HI]=(216,232)`. No underflow (pre-fix reproduced −270..−272). FX1's
clamp references the fixed arena only, never FX2 — the escape path is closed.

## F-2 — F-3 test discriminates (verified by temporary local revert of a materialized copy)

- Pre-fix ROM: `test_f3_both_left_stays_in_arena` **FAILS** — `FX1 escaped the arena: 65266` (−270).
- Fixed ROM: **PASSES**.

Meaningful (fails one way, passes the other). No tracked file was modified — the revert was on a
copy inside the materialized kit only; HEAD stayed at `ee041dd`.

## Width-tracking

Interactive branch enters A16 at `main.asm:253`; the whole clamp is A16. The new multi-path
labels `@f1_hi` / `@f1_done` / `@f2_hi` / `@f2_done` each carry `.a16` — correct for their
branch/fall-through entries. `width-check` clean.

## Regressions — none

- **Unsigned-compare hazard:** N/A — pre-clamp FX1 min = `ARENA_LO - WALK_SPD = 22 > 0`, never
  negative, so unsigned `cmp #ARENA_LO` is safe; even a hypothetically pre-underflowed FX1 is
  pulled back by the high clamp.
- **Boundary off-by-one:** FX1 high `#(ARENA_HI-MIN_GAP+1)=217` + `bcc` → allows exactly 216;
  FX2 high `#(ARENA_HI+1)=233` + `bcc` → allows exactly 232; FX2 low `beq` allows the exact
  `FX1+MIN_GAP` equality. All correct, confirmed by the observed wall-park values.
- **AUTODEMO branch** still reaches BOTH states (MERGED and SPLIT observed in the render run).
- No register-width regression.

## Render (autodemo ROM, auditor's own screenshots from the verified binary)

- **MERGED:** white=0 (no seam bar), red_meanx=87.5, blue_meanx=175.5 (both fighters visible).
- **SPLIT:** white=2821 (diagonal seam present), red_meanx=67.5, blue_meanx=195.5, split across
  midline x=128 (red left, blue right).

Boot magic `SFDB` present. Clean-room: no retail titles introduced by the commit.
