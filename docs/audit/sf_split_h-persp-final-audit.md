# sf_split_h C-horiz PERSPECTIVE series — FINAL PRE-PR AUDIT

- **Branch under audit:** `claude/persp-phaseP` — HEAD `e43b65e9` (verified).
- **Mainline base:** `origin/claude/split-mode-spec`. Full increment:
  `git diff origin/claude/split-mode-spec...HEAD` = 21 files, +3925/-22.
- **Role:** FINAL independent audit. I did NOT build any of this. Research-only; the
  only change is this report.
- **Primary focus:** the un-audited delta = Phase 2 (parked live-B + cycles instrument)
  and Phase P (Items A/B/C), plus a holistic pre-PR certification. Phases L + 1 already
  had a CLEAN audit-1 (`asm_repo_staging/docs/audit/sf_split_h-persp-campos-audit-1.md`);
  I re-ran their tests + controls as regression but did not re-derive them.
- **Method:** fresh materialization; built the perspective + persp3 rails and all
  variants; built + independently ran the free-running cycles instrument; ran the full
  perspective (17) + cycles (4) + persp3 (6) suites and the 29-suite split-family
  regression; RE-RENDERED Items A/B/C and read pixels; read the engine/demo source for
  the E010 semantics, the sky routing, and the latch guard.

## AGGREGATE VERDICT: **CLEAN (ship).**

All 8 DoD ✓. The three capability-critical checks (budget instrument, interp4 quality,
genuine 3-camera stack) all hold with independent evidence. 56/56 tests pass from a
fresh materialization. All three gates clean WITH this report present. No blocking or
non-blocking findings; two informational notes (a test-coverage nuance on the standing
gate, and a deferred underlying-macro follow-up the builder already filed) are recorded
below — neither blocks the PR.

---

## 1. Fresh materialization — full suites (verbatim)

```
$ bash asm_repo_staging/tools/dryrun_split.sh /tmp/kit_final
scrub_split: OK — 71 substitutions across 18 files; comment lineage guard clean
done — self-contained tree at: /tmp/kit_final

$ cd /tmp/kit_final
$ python3 templates/split_h_persp_demo/assets/gen_map.py     # 32768 bytes
$ python3 templates/split_h_persp3_demo/assets/gen_map.py    # 32768 bytes
$ make split_h_persp_demo && make split_h_persp3_demo && make build/persp_cycles_test.sfc
built build/split_h_persp_demo.sfc (cfg=lorom_64k.cfg)
built build/split_h_persp3_demo.sfc (cfg=lorom_64k.cfg)
built build/persp_cycles_test.sfc
$ bash templates/split_h_persp_demo/build_split_h_persp_variants.sh    # 10 variants incl. _sky, _stillsky
$ bash templates/split_h_persp3_demo/build_split_h_persp3_variants.sh  # + _onecam
```

### Perspective (17) + cycles (4) + persp3 (6) = 27

```
tests/test_split_h_persp_demo.py::test_boots PASSED
tests/test_split_h_persp_demo.py::test_p1_two_distinct_perspective_views PASSED
tests/test_split_h_persp_demo.py::test_p1_camera_a_animates_independently PASSED
tests/test_split_h_persp_demo.py::test_p1_camera_b_animates_independently PASSED
tests/test_split_h_persp_demo.py::test_p2_clean_single_scanline_seam PASSED
tests/test_split_h_persp_demo.py::test_p3_matrix_seam_data_in_active_buffer PASSED
tests/test_split_h_persp_demo.py::test_p3_guarded_default_is_clean PASSED
tests/test_split_h_persp_demo.py::test_p3_temporal_stability PASSED
tests/test_split_h_persp_demo.py::test_p3_fixed_buffer_control_flickers PASSED
tests/test_split_h_persp_demo.py::test_p4_noseam_control_single_camera PASSED
tests/test_split_h_persp_demo.py::test_p5_latch_violation_corrupts PASSED
tests/test_split_h_persp_demo.py::test_c1_band2_independent_world_position PASSED
tests/test_split_h_persp_demo.py::test_c1_same_center_control_no_pan PASSED
tests/test_split_h_persp_demo.py::test_c2_origin_splice_clean_band_step PASSED
tests/test_split_h_persp_demo.py::test_c3_origin_splice_temporal_stability PASSED
tests/test_split_h_persp_demo.py::test_b_horizon_knob_sky_vs_floor PASSED
tests/test_split_h_persp_demo.py::test_structural_channels_and_60fps PASSED
tests/test_persp_cycles.py::test_single_full_solve_exceeds_one_frame PASSED
tests/test_persp_cycles.py::test_cheapest_second_solve_pushes_over_budget PASSED
tests/test_persp_cycles.py::test_worst_case_two_full_solves PASSED
tests/test_persp_cycles.py::test_rail_solve_fits_one_frame PASSED
tests/test_split_h_persp3_demo.py::test_boots PASSED
tests/test_split_h_persp3_demo.py::test_c1_three_distinct_cameras PASSED
tests/test_split_h_persp3_demo.py::test_c1_onecam_control_single_camera PASSED
tests/test_split_h_persp3_demo.py::test_c2_two_clean_seams PASSED
tests/test_split_h_persp3_demo.py::test_c3_temporal_stability PASSED
tests/test_split_h_persp3_demo.py::test_shared_vram_and_60fps PASSED
============================= 27 passed in 44.37s ==============================
```

### 29-suite split-family regression

```
$ python -m pytest tests/test_split_h_demo.py tests/test_split_h_matrix_demo.py \
      tests/test_split_v_demo.py tests/test_split_v_fight.py -q
.............................                                            [100%]
29 passed in 45.77s
```

**56/56 total — no regression across the whole feature.**

---

## 2. Capability-critical checks

### Item 1 — the budget correction is REAL and the instrument is sound ✓

I independently rebuilt and ran the free-running cycles ROM
(`tests/persp_cycles_test.asm`) at each interp level (ticks/frames method,
`mc = frames * 357368 / ticks`, HDMA off in the window). Raw measured results
(`run_seconds=3.0`):

```
interp1      ticks=127 frames=175 ->  492436 mc = 137.8% of one frame
interp2      ticks=168 frames=174 ->  370131 mc = 103.6%
interp4      ticks=201 frames=174 ->  309363 mc =  86.6%
band2i4      ticks=337 frames=174 ->  184516 mc =  51.6%   (112 ln, quarter-res)
double       ticks= 64 frames=174 ->  971594 mc = 271.9%
```

- **interp1 > ~120%: TRUE** — measured 137.8% (a single full per-scanline solve alone
  exceeds one frame → negative headroom for a second live solve).
- **interp4 < 100%: TRUE** — measured 86.6% (camera A's shipped solve fits, so camera A
  now runs a true 60 fps CPU-side vs the interp1 ~43 fps it was).
- These match the guide's pinned table (`docs/guides/split_h.md`: 492k/138%,
  370,131/103.6%, 309,363/86.6%, 185,028/51.8%, ~273%) to within measurement noise.
- **Corroboration:** the pre-existing `test_mode7_chamber_cycles.py` independently pins a
  full per-frame matrix rebuild at ~431,000 mc ≈ 121% ("cannot fit at 60 fps") — same
  order, same verdict. The parent budget doc's ~10k figure is refuted; the correction is
  real.
- **`test_rail_solve_fits_one_frame` is load-bearing (non-vacuous):** it builds the
  cycles ROM at interp4 and asserts `< 100%`; my interp1 measurement (137.8%) proves that
  same `< 100%` assertion genuinely fails when the solve is over-budget, and the paired
  `test_single_full_solve_exceeds_one_frame` asserts `> 110%` (interp1). The assertion
  discriminates fit vs no-fit. *(Nuance — see note N1: the gate hardcodes the interp
  level into its own ROM rather than reading the demo's `A_INTERP` define, so it guards
  the engine solve cost, not a source-level revert of the demo constant.)*
- **E010-is-display-not-budget: CONFIRMED.** `$E010` mirrors `FRAME_COUNTER`
  (`engine/engine_state.inc:103` `ES_FRAME_COUNTER`, `= ENGINE_STATE_BASE+$0C`),
  incremented in the NMI handler (`engine/nmi_handler.asm:1023 inc ES_FRAME_COUNTER`).
  The demo mirrors it to `$7E:E010` each loop (`main.asm:438-441 lda FRAME_COUNTER … sta
  f:$7E0000+$E010`). NMI fires every VBlank at 60 Hz regardless of game-loop overrun, so
  E010 is a display/VBlank liveness counter decoupled from the CPU solve — exactly as the
  test docstring and guide (`split_h.md:356-361`) state. The free-running ticks/frames
  ROM is the real budget instrument; the E010 heartbeat is a liveness check. Both the
  claim and the instrument are sound.

### Item 2 — interp4 quality is not visibly degraded ✓

Re-rendered camera A at the shipped interp4 (`build/split_h_persp_demo.sfc`) vs a
`-DA_INTERP=1` control build, same frame index, and read pixels at the PV_L0=0 top-edge
horizon (steepest gradient). Shots: `/tmp/persp_final_audit_shots/camA_interp4.png`,
`camA_interp1.png`.

- Visual comparison of the two renders: **indistinguishable.** The receding checker, the
  cyan-tinted camera-A band, and the top-edge horizon recession are identical to the eye;
  no stair-stepping, banding, or seam artifact appears in interp4.
- Numeric probe (mean row-to-row |Δx| of the first colour transition over the steep top
  rows y=2..29): interp4 = 4.32, interp1 = 1.86. The interp4 figure is inflated by a
  single outlier row (first-transition jumped 24→53→25) at the extreme top edge where the
  checker is sub-pixel-compressed — a transition-detection artifact, not a visible
  stair-step (the rendered image at those rows is a smooth cyan gradient). Excluding that
  row the two are within ~1 px.
- **No degradation regression to flag.** interp4 is a sound ship at the demo's gentle-ramp
  params, matching the builder's claim.

### Item 3 — genuine 3-camera stack, not a proxy ✓

Re-rendered `split_h_persp3_demo` (`/tmp/persp_final_audit_shots/persp3_default.png`,
`persp3_onecam.png`) and read on-screen checker periods (longest same-colour run):

```
default:  top(cam A)=[8,8,8]   mid(cam B)=[32,32,32]   bot(cam C)=[16,16,16]
          separated A<C<B: True
          regime seq (rows 15..223): S…S L…L M…M   transitions=2   smeared '?' rows=[]
control (-DONE_CAM):  band maxima=[8,8,8]  -> all <=12 (single uniform camera)
```

- Three demonstrably distinct on-screen periods ≈ 8 / 32 / 16 px in three bands, cleanly
  separated (A < C < B), with **exactly two** regime transitions and **zero** smeared
  intermediate rows → two clean single-scanline seams. The render visibly shows three
  checker scales stacked.
- **`-DONE_CAM` control flips:** all three bands collapse to period ~8 (one camera fills
  the screen) → the 3-distinct signal is a real measurement, not the mere presence of
  seams.
- **No live solve:** the game loop is `wai; jmp game_loop` (`main.asm:242-246`) — entirely
  HDMA-driven via `sf_split_h_matrix_bands` (2 allocator channels, mask `$0C`, NON-REPEAT,
  precomputed matrices). Three cameras cost the same as one; `test_shared_vram_and_60fps`
  confirms the heartbeat advances ≥110/120 (60 fps holds). Genuine 3-camera stack.

---

## 3. Per-DoD result

| # | DoD | Result | Evidence |
|---|-----|--------|----------|
| 1 | Budget correction real + instrument sound (capability-critical) | ✓ | interp1=137.8% (>120%), interp4=86.6% (<100%), double=271.9%; matches guide table; chamber-cycles ~121% corroborates; `test_rail_solve_fits_one_frame` non-vacuous (interp1 fails its `<100%`); E010=FRAME_COUNTER (NMI/VBlank), display-decoupled — confirmed from engine source |
| 2 | Item A interp4 not visibly degraded (capability-critical) | ✓ | interp4 vs interp1 renders visually identical at the PV_L0=0 top edge; numeric jitter delta is a single sub-pixel detection outlier, not a visible artifact |
| 3 | Item C genuine 3-camera stack (capability-critical) | ✓ | periods 8/32/16 in 3 bands, 2 clean seams, 0 smeared rows; `-DONE_CAM` collapses to 8; loop `wai`s (no solve), mask `$0C`, 60 fps holds |
| 4 | Item B sky knob (allocator, not floor) | ✓ | `-DSKY_HORIZON` renders a `CGRAM[0]` blue backdrop band (y=4 mean RGB (0,0,77)) above the receding floor; default is floor-to-edge (green-cyan (0,94,85)); `arm_sky_split` routes via `hdma_request`+`hdma_bind_direct` (fail-soft), NOT hardcoded CH2 |
| 5 | No regression across the whole feature | ✓ | 17 persp + 4 cycles + 6 persp3 = 27, and the 29-suite regression, all pass from fresh materialization (56/56) |
| 6 | ValueLatch guard still holds with splice + interp4 | ✓ | `test_p5_latch_violation_corrupts` passes (latch build still tears); interp4 changes only solve granularity, not the VBlank-only shared-latch commit path; the sky channel writes TM (`$212C`) single-byte via HDMA (DMAP `$00`, atomic, not a shared write-twice latch) |
| 7 | Clean-room + gates clean WITH report | ✓ | width/zp/cleanroom clean (§5, re-run WITH this report present); shipping kit has no retail titles / no forbidden vendor token (only the exempted console platform-name descriptor); this report describes by mechanism |
| 8 | Paper-cut honesty (sky macro CH2 + OBJ-on) | ✓ | builder flagged BOTH: MEDIUM "sf_mode7_sky_split hardcodes CH2" + LOW "TM $10 paints OAM garbage"; the demo's Item-B path avoids both (allocator channel + TM `$00`) — verified in `arm_sky_split` source |

**Non-vacuity controls exercised and confirmed flipping:** `-DONE_CAM` (persp3 C1 →
all periods 8), `-DNO_SEAM` (P4), `-DLATCH_VIOLATION` (P5 tears), `-DFIXED_BUFFER_SPLICE`
(P3 flickers), `-DSAME_CENTER` (C1 no-pan), `-DA_INTERP=1` (interp1 over-budget in the
cycles gate). None of the passing positive assertions are vacuous.

---

## 4. Informational notes (neither blocks the PR)

- **N1 (accept) — the standing budget gate guards the engine solve cost, not the demo's
  `A_INTERP` define.** `test_rail_solve_fits_one_frame` builds its own cycles ROM at a
  hardcoded interp4 and asserts `< 100%`; it does not read the rail's `A_INTERP`
  (`main.asm:131 .ifndef A_INTERP / A_INTERP=4`). So a source-level revert of the demo
  constant to 1 (which would drop camera A to ~43 fps CPU-side) would NOT be caught by
  this test, and the E010 heartbeat check is display-decoupled (correctly documented) so
  it wouldn't catch it either. The gate is still sound as a regression guard on the
  measured decision (it catches the engine solve ballooning past one frame at interp4),
  and the paired interp1 test documents the >110% baseline. A demo-config-bound assertion
  would be a nice-to-have, not a ship blocker. **Disposition: accept.**
- **N2 (defer) — underlying `sf_mode7_sky_split` macro still hardcodes CH2 and masks
  OBJ-on.** The builder filed this as a MEDIUM+LOW paper cut with a proposed follow-up
  ("`sf_mode7_sky_split` improvement: accept an allocator channel"). The demo's Item-B
  path correctly sidesteps both by hand-rolling `arm_sky_split` through the allocator with
  TM `$00`, so nothing in THIS PR is affected. **Disposition: defer to a follow-up — out
  of scope for this PR** (as the brief permits).

No blocking or non-blocking findings.

---

## 5. Gates (verbatim, cleanroom re-run WITH this report present)

```
$ make width-check
width-check: clean (188 files)

$ make zp-check
zp_lint: 0 finding(s) across 229 file(s); symbol table has 167 DP symbols covering 208 bytes

$ bash tools/cleanroom_check.sh          # re-run below AFTER this report was added to the kit
cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)
```

All three clean. A targeted scan of the materialized shipping kit
(`*.md/*.asm/*.inc/*.py`) for retail titles and forbidden vendor tokens returned only the
console platform-name descriptor that `docs/cleanroom_policy.md` explicitly exempts
(factual hardware reference) — no retail game titles and no forbidden
compiler-provenance token in the shipping kit or in this report. (Parent-repo working
docs outside the kit boundary — `docs/audit/…`, `docs/dx_paper_cuts.md` — carry
incidental such references from unrelated merged sprints; they are not part of the
materialized kit and do not gate cleanroom, but a publish-time reviewer should keep them
out of the shipping tree.)
