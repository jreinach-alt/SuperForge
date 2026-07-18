# AUDIT-2 — seam-IRQ origin + gradient payload — remediation validation

- **Date:** 2026-07-03
- **Auditor:** independent audit-2 agent — NOT the audit-1 agent, NOT the remediation
  author; research + verdict only, no code changes.
- **Inputs:** audit-1 report (`asm_repo_staging/docs/audit/split_h_irq_grad_demo-audit-1.md`,
  commit `2ad7e42`) and the remediation commit `6aee2e9`
  ("remediation: audit-1 F1 + F3 — freeze-arm capture retry + IRQ-lockstep flip control").
- **Environment:** fresh materialization at `/tmp/kit_audit2` via `tools/dryrun_split.sh`
  from the dev branch head (`6aee2e9`); every measurement taken on the emulator core via
  the harness runner — nothing estimated.

**AGGREGATE VERDICT: REMEDIATION VERIFIED** — both fixed findings (F1, F3) are closed
cleanly with correct semantics; the three accepted findings (F2, F4, F5) have their
acceptance rationale in-tree and nothing in the remediation contradicts them; the
remediation's footprint is exactly the one test file (plus the merged audit-1 report and
its paper-cut entries), and no build, baseline, or gate regressed.

---

## 1. Environment + runs (verbatim)

**Builds** (`make split_h_irq_grad_demo && make seam_irq_trial` + both variant scripts,
from `/tmp/kit_audit2`):

```
built build/split_h_irq_grad_demo.sfc (cfg=lorom_64k.cfg)
built build/seam_irq_trial.sfc (cfg=lorom_64k.cfg)
built build/split_h_irq_grad_demo_freeze.sfc  (FREEZE=1)
built build/split_h_irq_grad_demo_fznograd.sfc  (FREEZE=1 NO_GRAD=1)
built build/split_h_irq_grad_demo_hdma.sfc  (FREEZE=1 HDMA_ORIGIN=1)
built build/split_h_irq_grad_demo_tear.sfc  (FREEZE=1 NO_GRAD=1 IRQ_INTERLEAVE=1)
built build/seam_irq_trial_hdma.sfc  (HDMA_ORIGIN=1)
built build/seam_irq_trial_mistime.sfc  (MISTIME=1)
built build/seam_irq_trial_hv.sfc  (HV=1)
```

**Remediated suite, 5 consecutive full runs** (F1 was intermittent — a single green run
is weak evidence; audit-1 hit the flake on its FIRST run from a fresh materialization,
so this exact scenario is re-tested five times):

```
$ for i in 1 2 3 4 5; do python -m pytest tests/test_split_h_irq_grad_demo.py tests/test_seam_irq_trial.py -q | tail -1; done
17 passed in 46.07s
17 passed in 45.75s
17 passed in 45.86s
17 passed in 45.78s
17 passed in 45.91s
```

5/5 green, stable wall-clock. (The orchestrator flagged concurrent CPU-contention flakes
in unrelated wall-clock-sensitive suites on this box; none observed in these runs.)

**Untouched baseline:**

```
$ python -m pytest tests/test_split_h_2p_demo.py tests/test_gen_pose_tables.py -q
28 passed in 47.46s
```

**Gates ×4:**

```
$ bash tools/cleanroom_check.sh
cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)
$ make width-check
width-check: clean (192 files)
$ make zp-check
zp_lint: 0 finding(s) across 233 file(s); symbol table has 168 DP symbols covering 209 bytes
$ make provenance-check
provenance: clean — 129 blob(s) accounted for (95 generated, 6 third-party, 9 attested, 19 artifact)
```

(Cleanroom gate re-run on a re-materialization that includes THIS report — result recorded
in the audit-2 branch commit; this file uses "the emulator core" / harness-API vocabulary
only.)

## 2. F1 — freeze-arm capture retry — **REMEDIATION VERIFIED**

Remediated code: `asm_repo_staging/tests/test_split_h_irq_grad_demo.py:183-203`
(`band_change` helper), call sites `:209` (moving arm) and `:212` (freeze arm).

**(a) Does the retry only forgive stale-capture artifacts, or could it mask a genuinely
unstable frozen build?** Adversarial read of the loop (`:193-200`): each attempt takes a
FRESH (16-frame settle → grab → 24-frame hop → grab) pair and diffs it; the loop breaks
only on `if not rows` — i.e. an attempt is forgiven only when a complete fresh capture
pair is byte-identical. A frozen build that genuinely changes frame-to-frame produces a
nonzero diff on every attempt and fails all three (failure message `:214` now says so
explicitly: "on 3 capture attempts"). The retry direction is one-way by construction:
`break` fires on the PASS condition (zero rows), so a retry can only convert a spurious
FAIL into a PASS — it can never keep retrying "until motion appears" for anyone. Residual
sensitivity cost, stated honestly: a build that is unstable with per-pair probability *p*
is now caught with probability *p*³ per run instead of *p* — the inherent price of any
retry, and exactly audit-1's recommended option (a). Crucially, the retry is NOT the sole
guardian of frozen-build stability: `test_g1_gold_equivalence` (`:127-135`) requires the
frozen IRQ build byte-equal to the frozen HDMA control on a SINGLE capture each, and
`test_t1_latch_interleave_tears` (`:148-149`) requires band 1 byte-stable across two
single captures of two frozen builds — a genuinely drifting frozen build would red those
un-retried surfaces. Verdict: the retry forgives only the capture-path artifact class F1
described (observed failure mode: 112/112 rows differ = whole-frame staleness).

**(b) Does the moving arm keep single-attempt semantics?** Yes. `attempts` defaults to 1
(`:183`) and the moving call site passes no override (`:209`:
`band_change(roms["default"], "move")`). The docstring (`:184-190`) pins the intent
("The MOVING arm takes the first attempt as-is"). Additionally — per the adversarial
point above — even a hypothetical multi-attempt moving arm could not retry toward motion:
a no-motion (zero-diff) attempt hits the `break` immediately and the `len(b1) > 3` /
`len(b2) > 3` assertions (`:210-211`) then fail. One neutral observation: the pre-capture
settle changed from 12 to 16 frames for BOTH arms (the helper is shared), so the commit
message's "moving arm unchanged" is accurate for attempt semantics but not for settle
timing. Behaviorally immaterial: the moving build pans continuously, and the 24-frame
hop (the quantity constrained by the 12-frame video-skip floor) is unchanged. Not a
finding.

**(c) Repeated green runs.** 5/5 full-suite runs green from a fresh materialization
(§1) — the same first-run-fresh-tree scenario in which audit-1 observed the flake.

## 3. F3 — IRQ-lockstep flip control — **REMEDIATION VERIFIED**

Remediated code: `asm_repo_staging/tests/test_split_h_irq_grad_demo.py:253-257`, inside
`test_h1_wai_wake_rate`.

- **Reads the right thing:** `runner.read_u16(WR, G_IRQCNT)` with `G_IRQCNT = 0xE050`
  (`:53`) — the WRAM mirror the demo's IRQ handler increments
  (`templates/split_h_irq_grad_demo/main.asm:226-228`, `G_IRQCNT = $7EE050` at `:142`) —
  and requires **exactly 0** on the `-DHDMA_ORIGIN` build, which is loaded at `:246` and
  is still the loaded ROM at the assertion.
- **Not dead code:** it is the unconditional final statement of a test that passes in all
  5 runs — it executes on every green run. Its placement after the `frame_stepping`
  context even strengthens it: extra free-running frames elapse before the read, giving a
  hypothetical vector/arm leak more opportunity to show before the exact-zero check.
- **Deterministic under power-on-random RAM:** the exact-zero read is of a RAW counter,
  which is only sound because the ROM zeroes it deterministically —
  `templates/split_h_irq_grad_demo/main.asm:234` runs `sf_coldstart`, which clears all
  128 KB of WRAM (`lib/macros/sf_core.inc`: "all WRAM ($7E:0000-$7F:FFFF) zeroed").
  Checked and confirmed; had the mirror been handler-written only, this assertion would
  itself have been a power-on flake.
- **Actually flips — measured, not assumed.** Independent probe on the emulator core via
  the harness runner (fresh loads of both ROMs, `read_u16` of $7E:E050):

  ```
  hdma control  G_IRQCNT after ~85 frames: 0
  default build G_IRQCNT after ~84 frames: 78
  ```

  The control holds the counter at exactly 0 while the IRQ build advances it once per
  frame (78 over ~84 frames incl. boot) — the same metric `test_cad_cadence_and_irq_lockstep`
  (`:217-233`) locksteps +1/frame. Audit-1's F3 gap ("nothing asserts that the IRQ counter
  STAYS 0 on the -DHDMA_ORIGIN build") is closed with precisely the two-line assertion it
  recommended.

## 4. F2 / F4 / F5 — accepted per audit-1 — **ACCEPTANCE CONFIRMED**

- The acceptance rationale is documented in-tree: the audit-1 report (F2 staircase-vs-
  strict monotonicity; F4 cross-template `.incbin` coupling, accept/defer with a note for
  the 2p port; F5 spec-sanctioned WRAM-mirror mask test) was merged in commit `2ad7e42`
  and lives at `asm_repo_staging/docs/audit/split_h_irq_grad_demo-audit-1.md`.
- Nothing in the remediation contradicts the acceptances: the remediation diff touches
  only `test_m1_live_motion_through_the_irq` and the tail of `test_h1_wai_wake_rate`.
  The gradient tests (F2's subject), the asset `.incbin`s (F4's subject), and
  `test_s1_structural_masks` (F5's subject) are byte-for-byte untouched.

## 5. Regression check — **NO REGRESSION**

```
$ git show 6aee2e9 --stat
 .../tests/test_split_h_irq_grad_demo.py            | 31 ++++++++++++++++------
 1 file changed, 23 insertions(+), 8 deletions(-)
```

The remediation commit touches exactly one file. The full post-implementation span
(`git diff 879efea..6aee2e9 --stat`) adds only the merged audit-1 report (+336 lines) and
its two paper-cut entries in `docs/dx_paper_cuts.md` (+12 lines) on top of that test
change — matching the claimed footprint exactly. No ASM, engine, template, tool, or
config file changed, so the ROM images are unchanged by construction; empirically, all
9 variant ROMs rebuilt from the remediated tree, the full 17-test surface passed 5/5,
the 28-test untouched baseline passed, and all four gates are clean (§1). The retry loop
altered no assertion for any test other than M1's freeze arm; the M1 moving-arm and every
other test's semantics are unchanged (the only shared-helper delta is the neutral
12→16-frame settle noted in §2b).

## 6. Paper cuts

One dispatch-protocol paper cut filed this sprint (worktree/branch checkout collision in
the audit dispatch preamble) — appended to `docs/dx_paper_cuts.md` under the sprint
section in the same commit as this report.

---

## Verdict summary

| Finding | Audit-1 action | Audit-2 verdict |
|---|---|---|
| F1 capture flake (M1 freeze arm) | fix | **REMEDIATION VERIFIED** — retry forgives only byte-identical fresh recaptures; one-way (FAIL→PASS only); moving arm single-attempt; frozen stability still covered un-retried by G1 + T1; 5/5 green |
| F3 lockstep flip control | fix (2 lines) | **REMEDIATION VERIFIED** — exact-zero raw-counter assert on the control, live code, deterministic via the full WRAM clear, measured flip 0 vs 78 |
| F2 staircase monotonicity | accept | **ACCEPTANCE CONFIRMED** — rationale in-tree, subject untouched |
| F4 `.incbin` asset coupling | accept/defer | **ACCEPTANCE CONFIRMED** — rationale in-tree, subject untouched |
| F5 mask WRAM mirrors | accept | **ACCEPTANCE CONFIRMED** — rationale in-tree, subject untouched |
| Regression | — | **NONE** — one-file footprint verified; builds, suites (5x), baseline, gates ×4 all clean |

**AGGREGATE: REMEDIATION VERIFIED.**
