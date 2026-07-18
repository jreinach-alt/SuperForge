# AUDIT-1 — seam-IRQ origin + gradient payload (`split_h_irq_grad_demo` + engine opt-in IRQ path)

- **Date:** 2026-07-03
- **Auditor:** independent audit-1 agent (did not write the code; research-only, no code changes)
- **Spec (source of record):** `docs/sprints/split_h_irq_gradient_handoff.md` (parent repo)
- **Implementation under audit:** the three commits above base `11791aa` on the dev branch —
  `2ae1c8d` (Task 0 cold-start trial), `8cd4bbf` (Task 1 engine opt-in IRQ path),
  `879efea` (Task 2 demo template + tests + guide + docs)
- **Environment:** fresh materialization at `/tmp/kit_audit1` (branch) and `/tmp/kit_base`
  (base commit `11791aa`) via `tools/dryrun_split.sh`; all measurements on the emulator
  core via the harness — nothing estimated.

**AGGREGATE VERDICT: FINDINGS** — the mechanism, engine opt-in, tests, and docs all check
out against the spec; every measured claim reproduced. One MEDIUM finding (an intermittent
capture-path flake in the shipped suite, observed on the auditor's first full-suite run) and
three LOW findings/observations. No HIGH findings. Recommend a small remediation pass
(F1, optionally F3), then audit-2.

---

## 1. Test-suite re-runs (verbatim output)

All runs from the fresh materialization `/tmp/kit_audit1`.

**Builds** (`make split_h_irq_grad_demo && make seam_irq_trial` + both variant scripts):

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

**Run 1 of the two new suites — 1 FAILURE (see finding F1):**

```
$ python -m pytest tests/test_split_h_irq_grad_demo.py tests/test_seam_irq_trial.py -q
...
E       AssertionError: frozen build changed (112/112 rows) — capture path unstable
E       assert (not [7, 8, 9, 10, 11, 12, ...])
tests/test_split_h_irq_grad_demo.py:203: AssertionError
=========================== short test summary info ============================
FAILED tests/test_split_h_irq_grad_demo.py::test_m1_live_motion_through_the_irq
1 failed, 16 passed in 45.92s
```

**Run 2 (same command, same materialization):**

```
17 passed in 45.80s
```

**Isolation + repeat runs of the failing test / suite:**

```
$ pytest tests/test_split_h_irq_grad_demo.py::test_m1_live_motion_through_the_irq -q   (×2)
1 passed in 3.10s
1 passed in 3.18s
$ pytest tests/test_split_h_irq_grad_demo.py -q    (×3)
9 passed in 24.13s
9 passed in 24.18s
9 passed in 24.17s
```

Net: 1 failure in 6 runs that included the test — an intermittent, order-/timing-dependent
flake in the FREEZE-stability arm of M1, not a deterministic regression. The mechanism
assertions (gold equivalence, tear, mistime, gradient, cadence, wakes) never failed.

**Untouched baseline (expect 28):**

```
$ python -m pytest tests/test_split_h_2p_demo.py tests/test_gen_pose_tables.py -q
28 passed in 40.84s
```

**Full split-family regression (spec hard-boundary 3):**

```
$ python -m pytest tests/test_split_h_demo.py tests/test_split_h_matrix_demo.py \
    tests/test_split_h_persp_demo.py tests/test_split_h_persp3_demo.py \
    tests/test_split_v_demo.py tests/test_split_v_fight.py tests/test_persp_cycles.py -q
57 passed, 1 xfailed in 92.16s (0:01:32)
```

## 2. Gates ×4 (verbatim, from `/tmp/kit_audit1`)

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

Parent-repo gates on the branch worktree (the shared engine files changed there):

```
width_lint: 0 finding(s) across 320 file(s)
zp_lint: 0 finding(s) across 333 file(s); symbol table has 187 DP symbols covering 230 bytes
```

Both match the implementing agent's claims (0/320, 0/333).

## 3. DoD-1 byte-stability — verified INDEPENDENTLY

Two materializations: `/tmp/kit_audit1` (branch head) vs `/tmp/kit_base` (base commit
`11791aa`, via a separate git worktree). Built the full pre-existing 2-player demo family
from each and compared md5:

```
IDENTICAL split_h_2p_demo            18aa3e5dd5ec0144f6a5767ff71a170a
IDENTICAL split_h_2p_demo_sameorigin 5ffe0176b61d5ee006c12f250aaa7938
IDENTICAL split_h_2p_demo_retarget   667a23a87287cce5c28b002d6c554dfa
IDENTICAL split_h_2p_demo_latch      a6979efa2111ced491117913f9cde4ad
IDENTICAL split_h_2p_demo_rotate     2d599837174fd080ae95cdcff9ad9f2e
IDENTICAL split_h_2p_demo_rotate64   10860bd17c8c8089c3cdafd472d5696a
IDENTICAL split_h_2p_demo_rotfreeze  ff4ce69cc19ecc304f78f18ec03448be
IDENTICAL split_h_2p_demo_perband    9c696ee87212418366aa933253ded615
IDENTICAL split_h_2p_demo_badorder   ed451bf4cacfee87bb0946ead0b84519
```

Parent-repo ROM (phase12_0), branch build vs base build:

```
929420a61464e19b7f7de850e2f5e48d  build/mode7_racing_12_0.sfc   (both sides)
```

The `header.inc` mechanism (`.ifndef SF_IRQ_VECTOR / SF_IRQ_VECTOR = NMI_STUB / .endif` +
`.word SF_IRQ_VECTOR`) emits the identical vector word by construction when no override is
defined; the md5 sweep confirms it empirically. **DoD-1 byte-stability: VERIFIED** (10 ROMs
independently; the implementing agent's own 99-ROM sweep claim is consistent with the
mechanism and spot-check).

## 4. DoD-6-adjacent — timing claims cross-checked on the emulator core

Loaded `build/seam_irq_trial.sfc` fresh and read the trial's measurement mirrors directly:

```
magic: b'SFDB'
entry: H dot 48, V scanline 112        ($7E:E054-E057)
fire-done: H dot 11, V scanline 113    ($7E:E05A-E05D)
IRQ count E050: 85   NMI E010: 85   wakes E058: 170   loops E030: 85
```

Guide claims vs measured: handler entry "dot ~47 of scanline 112" → measured dot 48 ✓;
"fire completion dot ~11-15 of scanline 113" → measured dot 11 ✓ (≤ the dot-22 flush
threshold the test enforces); "IRQ once/frame in lockstep with the NMI counter" → 85 == 85 ✓;
"wai wakes ~2×/frame" → 170 = 2 × 85 exactly ✓; loop closes every frame → 85 ✓.
**All documented timing numbers reproduce.**

## 5. Per-DoD-criterion table

| # | DoD item | Verdict | Evidence |
|---|----------|---------|----------|
| 1 | Engine opt-in IRQ path, additive; regression green; untouched ROMs byte-identical | **✓** | `infrastructure/rom_template/header.inc:88-94` (default = stub via `.ifndef`); `engine/engine_state.inc:180-188` (`ES_SHADOW_NMITIMEN = $3D`, documented-free byte); `asm_repo_staging/lib/macros/sf_irq.inc` (compose macros, arm incl. CLI, disarm incl. ack). Regression: 57+1x split family + 28 baseline + 17 new. Byte-identity: §3 (10 ROMs, independent) |
| 2 | Demo ships: two bands, independent origins (band-2 via IRQ), visible gradient, allocator masks in a structural test (3 used / ≥3 free) | **✓** | `templates/split_h_irq_grad_demo/main.asm` (seam handler L191-231, gated wai L513-551, gradient build L710-742); `test_s1_structural_masks` asserts matrix `$0C` + origin `0` + gradient `$10`, popcount 3, and the control's `$30`; auditor's own renders confirm two bands + visible vertical ramp (§7) |
| 3 | Equivalence gold assertion: byte-identical (gradient-disabled option) | **✓** | `test_g1_gold_equivalence` compares full frames (256×239, all rows, per-pixel RGB) of FREEZE+NO_GRAD IRQ build vs FREEZE HDMA control; `rows == []` asserted; re-ran green ×2 full-suite + ×3 module runs. Trial's `test_g1_gold_equivalence_vs_hdma_control` likewise. Spec's "or run the comparison with the gradient disabled" option taken — valid per spec text |
| 4 | Gradient test: monotonic brightness, `-DNO_GRAD` flips same metric, rendered screenshot | **✓ (with LOW deviation F2)** | `test_gr_gradient_monotonic_blue_ramp`: per-row blue mean non-decreasing across all 224 content lines, span 0→≥200, ≥20 distinct steps; `test_gr_no_grad_control_flips`: max blue == 0. "Strictly monotonic" read as staircase-monotonic (see F2). Screenshot re-rendered by auditor from the built binary ✓ |
| 5 | Cadence + IRQ lockstep + H4 tear green; every new assertion has a flip control | **partial (LOW, F3)** | Cadence +1/+1/+1 ×24 green (`test_cad_cadence_and_irq_lockstep`, `test_h5_cadence_and_irq_lockstep`); tear control green with span assertions (`min(rows) ≥ seam+7`, ≥100 rows, band-1 stable); mistime control asserts the EXACT expected span (rows 67..118 = content 60..111); wake metric has its control (48 vs 24). Gap: the +1/+1/+1 lockstep assertion itself has no explicit flip control (e.g. `E050 == 0` on the HDMA build is never asserted) — see F3 |
| 6 | Gates ×4 clean on a materialization including reports; provenance same-commit for committed generated assets | **✓** | §2 (all four clean; re-run by auditor including this report — see §9). No committed generated blob added: the gradient table is built at boot into WRAM (spec offered the choice; rationale stated in-code and in the guide); pose/checker blobs are read-only references to the 2p rail's already-registered assets (129 blobs accounted for) |
| 7 | Audit chain audit-1 → remediation → audit-2, fresh agents | **in-flight (by design)** | This report IS audit-1. Remediation + audit-2 pending orchestrator dispatch |
| 8 | Roadmap row (measured numbers) + paper cuts + guide + owner-validated render | **✓** | Roadmap: one row appended at table top, no existing row edited (append-only verified in diff); `docs/dx_paper_cuts.md`: 6-entry section appended; guide `docs/guides/split_h_irq_grad.md` (mechanism, measured timing model, wai-gate pattern, 2p porting notes). Owner render: auditor independently re-rendered all four variants from the fresh-built binaries — the claimed visuals reproduce |
| 9 | Renders from the verified binary, rendered by the claimant | **✓ (as auditable)** | The agent's private render provenance is unauditable from the repo; the auditor re-rendered every claimed visual from freshly built binaries and confirmed each (gold pair visually identical; tear = band-2 corrupt / band-1 clean; freeze = two bands + visible ramp) |

## 6. Parallel-session boundary check

`git diff 11791aa..HEAD --stat` touches exactly 12 files. **None** of the forbidden files
(`templates/split_h_2p_demo/**`, `tests/test_split_h_2p_demo.py`, `tests/test_gen_pose_tables.py`,
`tools/gen_pose_tables.py`, `templates/split_h_persp*`) appear in the diff. `asm_repo_staging/docs/roadmap.md`:
+1 line, inserted at the top of the table body, no existing row modified. `docs/dx_paper_cuts.md`:
+50 lines, pure append at EOF. Shared engine files (`engine/engine_state.inc`,
`infrastructure/rom_template/header.inc`) changed additively with default-path behavior
proven byte-identical (§3). The new templates `.incbin` the 2p rail's committed assets
read-only (see F4). **Boundaries respected.**

## 7. Adversarial test-surface review (indirect-evidence rule)

Per-test assertion surface, both suites:

| Test | Surface | Verdict |
|---|---|---|
| `test_boots` (both) | WRAM debug magic | fine (liveness precondition only) |
| `test_s1_structural_masks` (both) | WRAM mirrors of the allocator's actual return values (`sta f:G_MSK` straight from `hdma_request`) | proxy-adjacent but **spec-mandated** (DoD-2 "state them in a structural test"); the behavioral claims are carried by the framebuffer tests. Accept (F5) |
| `test_g1_gold_equivalence` (both) | full-frame screenshot, per-pixel RGB, all 239 rows | rendered output ✓ |
| `test_g1_mistime_control_flips_metric` (trial) | same full-frame metric; asserts the EXACT expected row span (content 60..111) | rendered output, non-vacuous by construction ✓ |
| `test_g2_hv_trigger_same_gate_identical` (trial) | full-frame screenshot | rendered output ✓ |
| `test_t1_latch_interleave_tears` (demo) | full-frame diff; requires ≥100 corrupt rows all ≥ seam+7; band-1 byte-stable | rendered output, frozen-vs-frozen ✓ |
| `test_gr_*` (demo) | per-row blue mean of the screenshot — the world's palette carries B=0 everywhere (verified in source: all four colors + backdrop `$0000`), so blue IS the COLDATA term | rendered output, checker-immune metric, flip control present ✓ |
| `test_m1_live_motion_through_the_irq` (demo) | screenshot diffs across 24-frame hops, per band, FREEZE flip control | rendered output ✓ — but the FREEZE arm is the flaky one (F1) |
| `test_cad_*` / `test_h5_*` | WRAM loop/NMI/IRQ counters, +1/+1/+1 per stepped frame | counters whose lockstep IS the claim (sanctioned by the brief) ✓; lacks own flip control (F3) |
| `test_h1_wai_*` (both) | WRAM raw wake counter, with the no-IRQ control flipping the same metric | counter-is-the-claim ✓ |
| `test_w1_fire_window_measured` (trial) | H/V counter latches captured inside the handler | measured hardware state ✓; reproduced by auditor (§4) |

No proxy-variable assertion masquerading as a rendering claim was found.

## 8. User-visible invariant, re-derived from first principles

The invariant: *a user watching the demo sees two independently-positioned camera bands
with a clean seam at content line 112, identical to the HDMA-origin build.* Does the test
surface prove what a user would see?

- **Identity:** the gold assertion compares the ENTIRE frame byte-wise, so seam position,
  band content, and seam cleanliness are all inherited from the HDMA control — which is the
  2p rail's shipped, separately-verified mechanism (its suite pins the seam at exactly
  content line 112). Full-frame equality is the strongest possible form of the invariant. ✓
- **Independence:** band-2 renders the warm stripe (world +256 in X) while band-1 renders
  the cool stripe — visually confirmed in the auditor's renders; M1 additionally shows both
  bands moving at different speeds through the same IRQ path on the default build. ✓
- **Non-vacuity of the controls:** the mistime control moves ONLY the fire line and the
  frame visibly corrupts over exactly the predicted 52-row span (asserted row-exact — a
  metric that could not pass vacuously); the tear control changes ONLY the delivery byte
  order and corrupts exactly band 2 (≥100 rows, none above the seam). Both flip the same
  full-frame metric the gold assertion uses. Both re-ran green for the auditor. ✓
- **Live-ness:** the gold pair is frozen-vs-frozen (correct per the rotating-baseline
  lesson); the M1 + CAD tests carry the moving case. The one soft spot is F1's capture
  flake in M1's freeze arm — a harness artifact, not an invariant violation (the failure
  mode observed is "both captures differ everywhere", not "seam moved"). ✓ with F1 noted.

**Conclusion: the test surface genuinely proves the user-visible invariant.**

## 9. Gates on a materialization including this report

After writing this report the auditor re-materialized and re-ran the cleanroom gate; the
result is recorded in the audit branch's commit (clean — this file uses "the emulator
core" / harness-API names only).

---

## Findings

### F1 — MEDIUM — intermittent capture-path flake in `test_m1_live_motion_through_the_irq` (FREEZE arm)

**Observed:** on the auditor's FIRST full-suite run from a fresh materialization, the
FREEZE-stability assertion failed with `frozen build changed (112/112 rows)` — i.e. both
captures of the frozen build differed on every content row. Passed on 5 subsequent runs
(2 isolated, 3 module-scope, 1 full-suite). The implementing agent's "17/17 verified"
claim is honest but the suite carries a latent order-/timing-dependent flake.

**Analysis:** a 224-row full-frame difference on a frozen ROM is a capture-path artifact
(one screenshot reflecting a different display state — e.g. a pre-settle frame or a stale
video buffer under `frame_stepping`), not an origin-mechanism failure; the mechanism's own
stability evidence (gold equivalence frozen-vs-frozen, S1-style temporal checks in the
sibling suites) never flapped. The test's own failure message anticipates this
("capture path unstable").

**Recommendation: FIX (remediation).** Options, cheapest first: (a) capture-retry — on a
nonzero diff of the frozen pair, recapture once before failing; (b) extra settle frames
between `frame_step` and `take_screenshot`; (c) root-cause the harness's screenshot/video
staleness under `frame_stepping` and fix centrally (benefits every suite). At minimum (a),
plus a paper-cut entry (filed by this audit).

### F2 — LOW — "strictly monotonic" read as staircase-monotonic (acknowledged deviation)

DoD-4 says "column-sampled brightness strictly monotonic down the ramp region." The
shipped ramp is by design a 28-step staircase (`v = line >> 3`), so per-row STRICT
monotonicity is mathematically impossible for the design the spec itself sketches
(224 lines, 32 intensity levels max). The test asserts non-decreasing across all 224
lines + span 0→≥200 + ≥20 distinct levels — which is the correct reading of intent and
is non-vacuous (the NO_GRAD control zeroes it). **Recommendation: ACCEPT** (document
nothing further; the test docstring already states the interpretation).

### F3 — LOW — the cadence/IRQ-lockstep assertion lacks its own flip control

DoD-5: "every new assertion has a non-vacuity control that flips the same metric." The
wake-rate, gradient, gold, tear, and mistime metrics all have controls. The +1/+1/+1
lockstep assertion does not: nothing asserts that the IRQ counter STAYS 0 on the
`-DHDMA_ORIGIN` build (which would prove E050 only advances via the real IRQ path and
that the lockstep metric can flip). It is near-vacuity-proof in practice (three
independent counters agreeing per-frame ×24 can't pass by accident), but the letter of
DoD-5 is unmet for this one assertion. **Recommendation: FIX (cheap)** — add
`assert runner.read_u16(WR, G_IRQCNT) == 0` (and optionally `G_ENTRY/G_FIRE` all-zero)
after loading the HDMA control in an existing test; two lines. Alternatively ACCEPT with
rationale.

### F4 — LOW — cross-template asset coupling via `.incbin` (observation)

Both new templates `.incbin` the 2p rail's committed blobs
(`templates/split_h_2p_demo/assets/poses1_ab.bin` / `poses1_cd.bin` / `checker_map.bin`).
Read-only — the boundary contract is respected — but it couples these rails' ROM images to
assets the MAIN LINE owns and may regenerate; a regeneration would silently change these
ROMs (both equivalence sides shift together, so tests keep passing — which is exactly why
nobody would notice). Acknowledged in template comments. **Recommendation: ACCEPT/DEFER** —
note for the future 2p port; if the coupling ever bites, give the demo its own registered
asset copies.

### F5 — LOW — structural mask tests read WRAM mirrors (observation, spec-sanctioned)

`test_s1_structural_masks` reads WRAM mirrors of the allocator's return values rather than
hardware state ($420C is write-only, so no stronger read exists). The mirrors are stored
directly from `hdma_request`'s live return, and DoD-2 explicitly asks for the masks "in a
structural test"; the behavioral proof lives in the framebuffer tests. **Recommendation:
ACCEPT.**

## Ambiguities-resolved list (implementing agent's calls, checked against spec intent)

1. **VTIME = SEAM, not SEAM−1** — resolved by measurement after a real one-row corruption;
   verified independently by this audit (§4: entry V=112, completion 113@11). Matches H2's
   "verify WHERE the V-IRQ actually fires" intent. ✓
2. **H+V dot-precision not needed** — spec left it open ("investigate whether…"); resolved
   by the `-DHV` same-gate byte-identical build + a cited mechanism for why an UNGATED H+V
   fire would be worse. ✓
3. **Gradient table: boot-built WRAM vs committed blob** — spec offered the choice and
   demanded a reason; boot-built chosen, reason stated (no provenance surface, ~15-line
   loop). ✓
4. **Guide as a NEW file** rather than a section in the family guide — deliberate
   parallel-session conflict avoidance (`split_h.md` is main-line-owned); DoD-8 says
   "guide section for the new demo," which a dedicated guide satisfies. ✓
5. **Control variant implies NO_GRAD** — spec's "-DHDMA_ORIGIN … (and no gradient)"
   implemented as an implied define + an `.error` guard against combining the tear control
   with the HDMA control. ✓
6. **Emulator-core source-file citations in the trial template's comments** — follows
   existing kit precedent (several guides + engine files carry the same citation style);
   the cleanroom gate is the arbiter and passes. ✓

## Recommendation summary

| Finding | Severity | Action |
|---|---|---|
| F1 capture flake in M1 | MEDIUM | **fix** (remediation sprint: retry/settle or harness root-cause) |
| F2 staircase vs "strictly monotonic" | LOW | accept |
| F3 lockstep flip control missing | LOW | fix (2 lines) or accept with rationale |
| F4 cross-template asset coupling | LOW | accept/defer (note for the 2p port) |
| F5 mask mirrors | LOW | accept |

**Verdict: FINDINGS** — remediation recommended for F1 (and optionally F3), then audit-2.
Everything else verified clean: byte-stability (independent 10-ROM md5 sweep), gates ×4
(kit) + 2 (parent), full split-family + baseline regression, all measured timing claims,
boundary contract, append-only shared docs, and the user-visible invariant.
