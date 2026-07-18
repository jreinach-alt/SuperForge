# Task 0 (PR #223 docs-honest remediation) — AUDIT-1

- **Branch under audit:** `task0-pr223-docs-honest` (8 commits on
  `claude/split-screen-rotation-smoothness-vu13t7`; the brief said 7 — the extra is
  the required paper-cuts commit `2618dad`, no scope creep).
- **Spec (source-of-record):** `docs/audit/sf_split_h-persp-pr223-independent-review.md`
  (findings M1, M3, minors 1/2/4/5/8) + the Task 0 brief in the parent sprint handoff
  (`docs/sprints/split_h_2p_stress_handoff.md` items 1-5). M2 fixed by a prior sprint
  (verified: provenance gate clean). M4 + minor 3 out of scope (verified: not touched).
- **Role:** independent audit-1, fresh agent, research-only. Every measured number the
  remediation quotes was **re-measured on the emulator from a fresh materialization**
  (`tools/dryrun_split.sh /tmp/kit_audit1`), not transcribed.
- **Method:** fresh materialization → `make split_h_persp_demo` + all 11 variants →
  full suite re-run → full diff read vs base → adversarial re-measurement of the two
  rebuilt tests (P2, P5) + the new cadence gate using the tests' EXACT metrics on the
  positive, negative, and confound builds → tree-wide claim sweep → all four gates.

## AGGREGATE VERDICT: **CLEAN — ship.**

All 5 remediation items land as specified. The two rebuilt tests (P2, P5) are no
longer vacuous/confounded — adversarially re-verified with independent runs of their
exact metrics on both sides plus the confound builds. The cadence gate is a strict
xfail that fails at HEAD for exactly the measured reason. Every quoted number
reproduced within tick/phase variance (most byte-exact). All four gates clean. One
LOW residual wording nit (below) — accept or fix opportunistically; it does not
block shipping.

---

## 1. Test-suite re-runs (verbatim)

Primary suites, from `/tmp/kit_audit1`:

```
$ python -m pytest tests/test_split_h_persp_demo.py tests/test_persp_cycles.py \
    tests/test_split_h_persp3_demo.py tests/test_split_h_2p_demo.py \
    tests/test_gen_pose_tables.py -q
.x.............................................                          [100%]
46 passed, 1 xfailed in 67.29s (0:01:07)
```

Split-family regression:

```
$ python -m pytest tests/test_split_h_demo.py tests/test_split_h_matrix_demo.py \
    tests/test_split_v_demo.py tests/test_split_v_fight.py -q
.............................                                            [100%]
29 passed in 45.21s
```

The single `x` is the cadence gate; verified explicitly:

```
tests/test_split_h_persp_demo.py::test_cadence_true_60fps_in_situ XFAIL  [ 50%]
tests/test_split_h_persp_demo.py::test_cadence_metric_noseam_control PASSED [100%]
========================= 1 passed, 1 xfailed in 2.28s =========================
```

Count reconciles: persp_demo 17→19 (+cadence gate +noseam control; 18 pass + 1 xfail),
cycles 4, persp3 6, 2p 12, pose-tables 6 = 47 collected.

Gates (verbatim, from `/tmp/kit_audit1`):

```
$ bash tools/cleanroom_check.sh
cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)
$ make width-check
width-check: clean (189 files)
$ make zp-check
zp_lint: 0 finding(s) across 230 file(s); symbol table has 167 DP symbols covering 208 bytes
$ make provenance-check
provenance: clean — 126 blob(s) accounted for (92 generated, 6 third-party, 9 attested, 19 artifact)
```

## 2. Per-item verdict table

| # | Item (per the Task 0 brief) | Verdict | Evidence |
|---|---|---|---|
| 1 | "true 60 fps" claim corrections: main.asm header, guide table cell + "cheap"-splice line + HDMA-on framing, roadmap Phase P row; structural test renamed; cycles docstring scoped to SOLVE | **✓** | `templates/split_h_persp_demo/main.asm:125-143` (honest CADENCE paragraph, 30 Hz motion / 60 fps display / HDMA-on ~93%); `docs/guides/split_h.md:338-385` (table cell now "86.6 % (the SOLVE fits)", HDMA-off caveat + 92.6 % HDMA-on + "real headroom ~7 %, not 13.4 %", splice "**NOT cheap**: ~85k mc ≈ 23.9 %"); `docs/roadmap.md:35` (Phase P row corrected with bracketed M1 correction note); `tests/test_split_h_persp_demo.py:736` (`test_structural_channels_and_display_liveness`, failure msg "liveness only — NOT a 60fps loop-rate claim"); `tests/test_persp_cycles.py:120-143` ("STANDING SOLVE-BUDGET GATE … makes NO claim about the integrated demo loop's cadence") |
| 2 | P2 redesign: +7 offset modeled, seam pair pinned at SEAM+OFF−1, retuned threshold, noseam control of the same metric; C2 docstring corrected + `step_y` pin; SKY_ROWS[0] 4→8 | **✓** | `tests/test_split_h_persp_demo.py:78-83` (`OFF = 7` with rationale), `:411-455` (pinned pair y118→119 = PPU 111→112, bar >60, ±4 quiet <30, in-test stillnoseam control <30), `:620-651` (C2 offset explanation + `step_y == SEAM + OFF` assert), `:683-686` (SKY_ROWS 8-first). All thresholds re-measured — §3 |
| 3 | P5 frozen-vs-frozen: stilllatch variant (FREEZE+HOLD_B+LATCH_VIOLATION); comparison on same jitter metric | **✓** | `build_split_h_persp_variants.sh:31-36,54` (stilllatch build + honest role notes for the rotating latch build); `tests/test_split_h_persp_demo.py:550-577` (still vs stilllatch, n_frames=10, bar `>2×max(clean, 0.5)`). Discrimination re-measured — §3 |
| 4 | In-situ cadence gate reading pv_buffer $01C6 + heartbeat $E010 over 16 stepped frames, xfail(strict=True) at HEAD; noseam control passes | **✓** | `tests/test_split_h_persp_demo.py:282-345` (`_cadence_flips` WRAM-only per the M4 hazard; `@pytest.mark.xfail(strict=True, reason=…M1…)`; `test_cadence_metric_noseam_control`). `PV_BUFFER=0x01C6` verified = `ENGINE_STATE_BASE($0100)+ES_M7_PV_BUFFER($C6)` in `engine/engine_state.inc:581,894`. XFAIL-at-HEAD + control-passes verified live — §1, §3 |
| 5 | Stale guide subsection ($60→$6C etc.), stale main.asm comments (CH2-only / OBJ-on / TM $11), vendor trade name rephrased by mechanism in both files | **✓** | Guide "Demo & tests" section now `NMI_HDMA_ENABLE == $6C` + full variant/test list incl. stillsame/sky/stilllatch/CAD (`split_h.md:714-774`); zero `== $60` / "no extra HDMA channel" survivors (grep clean); `main.asm:559-570` (CH2/CH3 free, pv_rebuild hardware channels = CH5/CH6 via `M7_OWNED_MASK=$60`, shadow-vs-hardware distinction), `:103-110` + `:703-736` (OBJ OFF / TM $00-$01, terminator comment `$01` not `$11`); trade name → "the vendor's serial math coprocessor used by stock racing carts" in both `main.asm:34-35` and `split_h.md:307-308`; tree-wide grep for the trade-name token: **zero hits** in shipping files (incl. `docs/audit/`) |

Out-of-scope confirmation: M4 (harness frame-skip) not touched beyond the documented
hazard note inside `_cadence_flips`' docstring (which is *why* the gate is WRAM-only —
correct). M5 / minor 3 untouched. M2 covered by the prior sprint (provenance clean,
126 blobs).

## 3. Per-claim re-measurement table (agent's number vs mine)

All re-measured on the fresh `/tmp/kit_audit1` materialization with the tests' exact
metric code (extracted, not imported, to avoid trusting the assertions).

| Claim (docstring/comment) | Agent / review | Audit-1 re-measurement | Verdict |
|---|---|---|---|
| P2 seam-pair G+B diff, still build, y118→119 | 108 | **108** | exact |
| P2 checker false peaks (window-max trap) | 216 at other rows | **216** at y=104 AND y=128 | exact |
| P2 quiet floor ±4 rows of the seam pair | ≤5 | **≤4** (114:0, 115:3, 116:0, 117:0, 119:0, 120:0, 121:0, 122:4) | ✓ |
| P2 noseam control, same pair | 2 | **2** | exact |
| P2 would FAIL on the noseam build (non-vacuity) | — | positive bar `>60` vs measured **2** → fails; in-test control `<30` passes | ✓ discriminates |
| P5 frozen clean jitter (still) | 0.556 | **0.556** | exact |
| P5 frozen stilllatch max jitter over window | 5.519 | **5.519** (7/10 samples 5.519, 3/10 clean-phase 0.556 → max-over-window design justified) | exact |
| P5 rotating default max jitter (the old confound) | 7.111 | **7.111** (samples 2.33-7.11; old design would have called the UNTAMPERED build "corrupted": 7.111 > 2×0.556) | exact — confound proven real AND now gone (comparison path is still vs stilllatch only) |
| P5 rotating latch build (demo, not comparison side) | review: 2.4-14.2 sweep | **12.574** max (4.7-12.6) | consistent |
| P5 separation | ~10× | 5.519 / 0.556 = **9.9×**; bar 1.111 → tear is 5.0× the bar | ✓ |
| Cadence at HEAD: pv_buffer flips | 8/16 | **8/16**, strict alternation | exact |
| Cadence at HEAD: heartbeat pattern | +2,0 | **+2,0 ×8** | exact |
| Cadence noseam control | 16/16, +1/frame | **16/16**, all deltas **+1** | exact |
| interp4 full-floor solve (HDMA off) | 309,363 mc = 86.6 % | **309,601 mc = 86.6 %** (Δ0.08 %, tick quantization) | exact |
| C2 red step: 0.0 above, 169.4 from y=119 | 0.0 / 169.4 | **0.0 (y≤118) / 169.4 (y≥119)** — step exactly at PPU 112 + 7 | exact |
| 92.6 % HDMA-on solve, ~85k mc ≈ 23.9 % splice, 110-120 % loop total | review M1 instrumented decomposition | quoted verbatim from the review with attribution; **corroborated** by my cadence re-measurement (the 2-frame loop those numbers predict is what I measure) — not independently re-decomposed (would require rebuilding the review's instrumented ROMs; the review is the source-of-record) | consistent |

Wording-vs-reality check (deliverable 5): all corrected texts state exactly the
review's measured reality — solve 86.6 % HDMA-off / ~92.6 % HDMA-on, integrated loop
2 frames → 30 Hz motion, display 60 fps. Tree-wide `true 60` sweep over
shipping files finds only 4 survivors, **all correct**: two about the `-DNO_SEAM`
build (true per review measurement 4, re-verified by my 16/16 control measurement)
and two in the guide's **2p-rail** section (`split_h.md:513,593`) — which the diff
correctly did **not** touch (verified: no hunks in that region; the 2p rail's +1/+1
lockstep is independently gated by its own in-situ test).

## 4. Deviations list

1. **LOW — residual unqualified "60fps check" comment.**
   `templates/split_h_persp_demo/main.asm:449`:
   `; --- heartbeat mirror ($7E:E010) — SEQUENCING screenshots + 60fps check ---`.
   Every other E010 reference in the remediation is scoped to display/NMI liveness;
   this inline comment (not part of the review's enumerated stale-comment list)
   retains the ambiguous label. It labels the WRAM mirror store, not a headline
   claim, and the heartbeat *does* advance ~60/s — but "display-liveness check"
   would match the corrected vocabulary. **Recommend: accept** (or fix
   opportunistically in any follow-up touching the file). Does not gate.
2. **INFO — commit count.** The brief said 7 commits; the branch carries 8. The
   extra (`2618dad`) is the mandatory paper-cuts entry — required by the close-out
   discipline, no scope creep. No action.

No HIGH or MEDIUM deviations found.

## 5. Ambiguities-resolved list

1. **P5 clean-phase sampling rate.** The P5 docstring says "1 of 8 measured 0.556";
   my 10-frame window measured 3/10 clean-phase samples. This is run-to-run
   collision-phase drift, exactly the phenomenon the docstring cites as the reason
   for MAX-over-window — the design is robust to it (worst plausible all-clean
   window is vanishingly unlikely at the observed ~70 % tear duty). Resolution
   matches spec intent; no finding.
2. **"xfail allowed at HEAD" (brief) vs `strict=True` (shipped).** The spec offered
   xfail; the agent shipped `xfail(strict=True)`, which is stronger — when the
   band-1-only rebuild lands, XPASS becomes a hard failure forcing the docs/gate
   flip. Matches the review's "fails at HEAD, documenting the known gap" intent.
   Better than asked; no finding.
3. **P2 crispness window ±4 vs the 216-px false peaks at y=104/128.** The false
   peaks sit outside the ±4 quiet window by construction; the test pins the seam
   LOCATION rather than hunting a window max, so the peaks cannot re-enter the
   metric path. Verified the profile between the false peaks and the window is
   quiet (≤8). Sound design; no finding.
4. **Old test name survivor in `docs/roadmap.md:36`.** Intentional: the parked
   live-B row is historical narrative and now carries "(test since renamed
   `test_structural_channels_and_display_liveness` per that finding)". Matches the
   rename item's intent; no finding.

## 6. Paper cuts

No new paper cuts from this audit. The one friction hit (the dispatch preamble's
`git checkout <branch>` fails when the branch is checked out in another worktree;
worked around with `git checkout -b task0-audit-1 task0-pr223-docs-honest`) is
already filed by the implementing agent in the Task 0 section of the parent
`docs/dx_paper_cuts.md` ("worktree branch dance") — verified present; duplicate not
filed.
