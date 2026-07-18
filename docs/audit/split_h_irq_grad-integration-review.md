# INTEGRATION REVIEW — seam-IRQ origin + gradient payload line

- **Date:** 2026-07-03
- **Reviewer:** independent integration reviewer (fresh session; did not write,
  audit, or remediate any of the six commits under review; research only, no fixes).
- **Line under review:** `claude/seam-irq-gradient-demo-1wdr4j`, 6 commits above base
  `11791aa` (`2ae1c8d3` trial, `8cd4bbfc` engine, `879efea6` demo, `2ad7e425` audit-1,
  `6aee2e99` remediation, `65f1d3f3` audit-2).
- **Governing contract:** `docs/sprints/split_h_irq_gradient_handoff.md` (parent repo).
- **Environment:** fresh toolchain bootstrap (`tools/setup.sh`, 8/8 incl. the parent
  phase12_0 sanity build + 24-assertion test), fresh materialization at
  `/tmp/kit_gradrev` via `tools/dryrun_split.sh`, base-commit materialization at
  `/tmp/kit_base_rev` (scratch git worktree at `11791aa`). Every DoD number below was
  RE-MEASURED on the emulator core via the harness runner — nothing transcribed from
  the session's own reports.

**AGGREGATE VERDICT: INTEGRATE.** Every checklist line passes with evidence; every
re-measured number matches the session's claim exactly; the merge preview against the
sprite-rail line (`50b6123b`) conflicts only on the two designated append-only docs and
the combined tree verifies green. Findings: 0 blocking, 3 observations (below).

---

## 1. Boundary compliance — ✓

`git diff --name-only 11791aa..HEAD` = exactly 14 files. ZERO touches to
`templates/split_h_2p_demo/**`, `tests/test_split_h_2p_demo.py`,
`tests/test_gen_pose_tables.py`, `tools/gen_pose_tables.py`, or any persp-rail file
(`templates/split_h_persp*`, their tests). Shared docs verified append-only by diff
inspection: `asm_repo_staging/docs/roadmap.md` +1 line inserted at the top of the table
body, 0 deletions; `docs/dx_paper_cuts.md` +73 lines pure EOF append, 0 deletions
(`git diff ... | grep -c '^-[^-]'` = 0 for both).

## 2. Engine additivity — ✓ (proven byte-identical, 22 ROMs)

The two shared parent files changed additively by construction:

- `infrastructure/rom_template/header.inc` — `$FFEE` now emits `SF_IRQ_VECTOR`,
  defaulting to `NMI_STUB` via `.ifndef`; the default emits the identical vector word.
- `engine/engine_state.inc` — `ES_SHADOW_NMITIMEN = $3D` claims a documented-free DP
  byte (former ES_GFXMODE slot) + the `SHADOW_NMITIMEN` alias. No existing symbol moved.

**Empirical proof (this reviewer's own sweep, superset of audit-1's):** built the full
2p family (default, sameorigin, retarget, latch, rotate, rotate64, rotfreeze, perband,
badorder, freeze) AND the full persp-demo family (12 variants) from the base-commit
materialization and from the gradient-head materialization — **all 22 ROMs
md5-IDENTICAL** pairwise (e.g. `split_h_2p_demo` `18aa3e5d…`, `_rotate` (the 256 build)
`2d599837…`, `split_h_persp_demo` `0eb9a3a7…`). Parent sanity path: `tools/setup.sh`
phase12_0 build + 24-assertion test PASSED on the branch head.

## 3. Suites + gates — ✓ (verbatim, from `/tmp/kit_gradrev`)

```
$ python -m pytest tests/test_seam_irq_trial.py tests/test_split_h_irq_grad_demo.py -q
17 passed in 45.03s
$ python -m pytest tests/test_split_h_2p_demo.py tests/test_gen_pose_tables.py -q
28 passed in 40.68s
$ python -m pytest tests/test_split_h_demo.py tests/test_split_h_matrix_demo.py \
    tests/test_split_h_persp_demo.py tests/test_split_h_persp3_demo.py \
    tests/test_split_v_demo.py tests/test_split_v_fight.py tests/test_persp_cycles.py -q
57 passed, 1 xfailed in 90.84s
```

The split-family tally is **57+1x**, matching audit-1/audit-2's claim (the review
brief's "56" expectation was stale). One run-ordering note, disclosed in full: this
reviewer's FIRST split-family run — executed concurrently with a second emulator
instance doing the re-measurements below — failed
`test_split_h_persp_demo.py::test_c3_origin_splice_temporal_stability` once; it passed
in isolation (1.62 s), at module scope (18+1x), and in the clean full-family re-run
above. The persp ROMs are md5-identical to base (§2), so the branch cannot have caused
it; it is the same box-level capture/timing flake class audit-1 filed as F1 and
audit-2's §1 warned about under CPU contention. See Observation O1.

Gates ×4 from `/tmp/kit_gradrev` re-materialized WITH this report present:

```
cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)
width-check: clean (192 files)
zp_lint: 0 finding(s) across 233 file(s); symbol table has 168 DP symbols covering 209 bytes
provenance: clean — 129 blob(s) accounted for (95 generated, 6 third-party, 9 attested, 19 artifact)
```

## 4. DoD spot-verification — ✓ all re-measured (their numbers vs mine)

| Claim | Session's number | Reviewer's re-measurement | Match |
|---|---|---|---|
| Gold equivalence, gradient off (FREEZE+NO_GRAD IRQ vs FREEZE HDMA control) | 0 differing rows | **0 differing rows** (full frame, per-pixel RGB) | ✓ |
| Equivalence with gradient ON (FREEZE vs HDMA control) | differs only on gradient rows | **216 differing rows = exactly content lines 8..223** (lines 0..7 carry gradient value 0); zero rows differ outside the nonzero-gradient region; zero nonzero-gradient rows fail to differ | ✓ |
| Gradient ramp (per-row blue mean, lines 0/56/112/168/223) | 0 / 57 / 115 / 173 / 222 | **0.0 / 57.0 / 115.0 / 173.0 / 222.0**, monotonic non-decreasing across all 224 lines, 28 distinct levels | ✓ exact |
| `-DNO_GRAD` flips the metric | all-zero | **max blue = 0.0** | ✓ |
| Cadence on the SHIPPED demo (moving + gradient + IRQ) | +1/+1/+1 loop/NMI/IRQ ×24 stepped frames | **+1/+1/+1 lockstep, all 24 steps** (E030/E010/E050) | ✓ |
| Seam rows | band-1 line 111 + band-2 line 112 pixel-exact vs control | **screenshot rows 118 and 119 both pixel-exact** (256/256 columns) vs the HDMA control | ✓ |
| H4 tear control | band 2 corrupts, 112 rows, band 1 stable | **112 differing rows, min row 119** (all ≥ seam+7; band 1 byte-stable), frozen-vs-frozen | ✓ |
| Mistime control (trial, VTIME=60) | exactly content lines 60..111 | **rows 67..118 exactly = the exact expected 52-row span** | ✓ |
| Trial gold equivalence | 0 differing rows | **0 differing rows** | ✓ |
| W1 fire window | entry V=112 dot ~47-48; completion V=113 dot 11-15 | **entry (H48, V112); fire-done (H11, V113)** | ✓ |
| IRQ/NMI lockstep + wakes (trial free-run) | IRQ==NMI; wakes = 2× | **IRQ 85 / NMI 84 / wakes 169** (read mid-frame; ±1 skew is read-ordering) | ✓ |

H1 wai-gate confirmed from source in BOTH templates
(`templates/split_h_irq_grad_demo/main.asm` game_loop `:513-526`,
`templates/seam_irq_trial/main.asm` `:525-537`): snapshot `$E010`, `wai`, re-read,
`beq @sleep` — the loop distinguishes NMI wake from IRQ wake exactly as `sf_irq.inc`'s
documented contract. Both mis-timed controls flip real full-frame metrics (rows above).

**Owner render:** re-rendered by this reviewer from the freshly built shipped binary →
`/tmp/e2e_screenshots/gradrev_final.png` — two perspective bands (cool over warm),
clean seam, visible vertical brightness ramp down the frame. Matches the owner-validated
visual.

**Adversarial test-surface pass:** both new suites read rendered framebuffers or the
WRAM counters whose lockstep IS the claim; every metric has a `-D` flip control
(including the post-remediation exact-zero IRQ-counter check on the HDMA control at
`tests/test_split_h_irq_grad_demo.py:256`). No proxy assertion found. The M1 freeze-arm
retry (remediation F1) verified one-way by inspection: `break` fires only on a
zero-diff fresh capture pair; the moving arm stays single-attempt (`attempts=1`,
no override at the call site).

## 5. Audit-chain integrity — ✓ (with Observation O2)

- Structure: audit-1 (`2ad7e425`, FINDINGS: 1 MEDIUM + 3 LOW) → remediation
  (`6aee2e99`) → audit-2 (`65f1d3f3`, REMEDIATION VERIFIED). Distinct fresh
  materializations per step (`/tmp/kit_audit1` + `/tmp/kit_base`, `/tmp/kit_audit2`).
- Remediation footprint matches audit-2's claim exactly: `git show 6aee2e99 --stat` =
  1 file, `tests/test_split_h_irq_grad_demo.py` +23/−8; F1 fix = the retry helper,
  F3 fix = the two-line exact-zero assert audit-1 recommended verbatim.
- Audit-2's independent evidence is its own (5/5 consecutive full-suite runs; the
  measured 0-vs-78 counter flip — a measurement audit-1 never took), not a transcription.
- Verdicts supported: F1/F3 closed at the recommended mechanism; F2/F4/F5 acceptances
  documented in-tree and their subjects untouched by the remediation (confirmed by diff).
- No self-audit in substance: the audit-1 report critiques the implementation
  (4 findings incl. a MEDIUM against the shipped suite); audit-2 adversarially probes
  the remediation (the one-way-retry analysis). Provenance caveat → O2.

## 6. Merge preview vs the sprite-rail line — ✓ (local only, NOT pushed)

`git merge origin/claude/split-screen-rotation-smoothness-vu13t7` (head `50b6123b`)
onto the local review branch:

- **Conflict list: `asm_repo_staging/docs/roadmap.md` ONLY** (both lines prepended a
  2026-07-03 row at the same table-top line). `docs/dx_paper_cuts.md` **auto-merged
  cleanly** — the sprite line inserted its section near the top of the file while the
  gradient line appended at EOF, so the hunks never overlapped; both sections verified
  present post-merge (`## split_h_2p sprite stress rail — Task-2 sprint (2026-07-03)`
  at line 32, `## Seam-IRQ origin + gradient payload …` at line 15287). No code, test,
  engine, or template conflicts.
- **Union resolution:** roadmap keeps BOTH new rows (sprite row on top, gradient row
  second, both above the 2026-07-02 rows; zero conflict markers remain). Committed
  locally as `b71653b9` — **`merge-preview: sprite-rail line (50b6123b) into gradient
  review branch — union-resolved roadmap (both 2026-07-03 rows kept; dx_paper_cuts
  auto-merged, both sections verified present)`** — for orchestrator inspection/cherry;
  deliberately NOT pushed.
- **Combined-tree verification** (fresh materialization `/tmp/kit_merged`, this report
  present; verbatim):

```
$ python -m pytest tests/test_seam_irq_trial.py tests/test_split_h_irq_grad_demo.py -q
17 passed in 44.89s
$ python -m pytest tests/test_split_h_2p_demo.py tests/test_gen_pose_tables.py -q
38 passed in 90.50s          (post-merge count: the sprite rail's +10 over the 28 baseline)
$ make split_h_2p_demo && bash templates/split_h_2p_demo/build_split_h_2p_variants.sh
built build/split_h_2p_demo.sfc (cfg=lorom_64k.cfg)
built build/split_h_2p_demo_sprites.sfc  (ROTATE=1 POSES=256 SPRITES=24 SP_INPUT=1)
$ gates ×4
cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)
width-check: clean (193 files)
zp_lint: 0 finding(s) across 234 file(s); symbol table has 168 DP symbols covering 209 bytes
provenance: clean — 141 blob(s) accounted for (107 generated, 6 third-party, 9 attested, 19 artifact)
```

The two mechanisms coexist: the gradient rail's suites are unaffected by the sprite
rail's harness/test additions and vice versa (provenance grew 129 → 141 blobs, all
sprite-rail assets, all registered).

## 7. Findings

| # | Severity | Finding | Disposition |
|---|---|---|---|
| O1 | LOW (observation) | The capture/timing flake class audit-1 filed as F1 is BOX-WIDE, not suite-local: an inherited persp test (`test_c3_origin_splice_temporal_stability`, ROM byte-identical to base) failed once under two-emulator CPU contention and passed 3/3 clean re-runs. The shipped M1 retry fixes the gradient suite's exposure; the central harness root-cause (audit-1's option (c)) remains open. | **ACCEPT** — pre-existing, not this line's regression. Recommend the main line schedule the central fix; no new paper cut filed (audit-1's F1 entry already covers it). |
| O2 | LOW (observation) | Audit-agent provenance is not independently provable from git metadata: both audit commits carry the same orchestrator session trailer. This matches the repo-wide convention (the sprite-rail line's audit commits show the identical pattern — the orchestrator commits/merges each auditor's report), and the reports' content (distinct materializations, distinct independent measurements, the audit-2 dispatch paper cut written from inside an agent worktree) supports the fresh-agent structure. | **ACCEPT** — protocol followed as far as a repo can evidence it. |
| O3 | INFO | The review brief's expected split-family count (56) was stale; the measured and audit-claimed count is 57+1xfail (the family grew by one test between the handoff brief's drafting and base `11791aa`). | **ACCEPT** — audit numbers verified correct. |

No blocking findings. The audit chain's own F2/F4/F5 acceptances stand unchallenged.

## 8. Verdict

**INTEGRATE.** The mechanism is proven byte-identical to the HDMA origin on the
framebuffer; the engine change is additive with 22-ROM empirical byte-stability plus
the parent sanity path; all suites and gates are green from fresh materializations
including this report; the audit chain is structurally sound and its verdicts
reproduce; the merge against the sprite-rail line conflicts only where the contract
said it would and the combined tree verifies green.
