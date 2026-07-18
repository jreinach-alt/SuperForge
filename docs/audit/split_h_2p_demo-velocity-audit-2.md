# split_h_2p_demo velocity fix — Audit Protocol audit-2 (remediation verification)

**Increment audited:** `claude/persp-c-horiz-review-ntqlca` — fix commit `61580f1` (8.8 fractional velocities), remediation commit `c50444e` (audit-1 report + motion-model gate hardening). HEAD = `c50444e`.
**Role:** independent AUDIT-2 — I did not build the increment, did not write audit-1 (`asm_repo_staging/docs/audit/split_h_2p_demo-velocity-audit-1.md`), did not write the remediation. Research-only: `/home/user/SuperForge` never modified (`git status` clean before and after; all builds, tests, and the mutant ran in scratchpad copies).
**Method:** commit diff-scope check → line-level verification of the test's model against the `main.asm` ROTATE block semantics and the `gen_assets.py` pack format → fresh materialization (`dryrun_split.sh`) → full 18-test suite + hardened gate 3x solo + four gates → one-mutant differential (hardened gate vs the pre-hardening test from `61580f1` on the identical mutant ROM).

## VERDICT: REMEDIATION VERIFIED

The remediation commit is exactly the audit-1 report plus the test hardening — no source or asset changes. The hardened gate's model is an exact transcription of the ROTATE movement block (post-advance headings; per-axis `s = frac + vel`, `pos += floor(s/256) mod 1024`, `frac = s & $FF`, velocities from the committed `move64.bin` at `h*4`) and is mathematically exact for the reachable range `s ∈ [−512, 767]`. It passes 3/3 solo and in the full 18. The differential is proven by mutation: a scratch-copy ROM with the F1X sign-extension broken (`cmp #$0080` → `cmp #$0180`) **fails the hardened gate at step 1 on the motion-model assertion** — divergence isolated to the mutated axis with the exact +256 un-extended-sign signature — while the **pre-hardening suite (61580f1's test file) passes 18/18 against the same mutant ROM**, confirming audit-1's LOW finding verbatim and that the hardening alone carries the load. All three defect classes audit-1 named are now covered (one mutation-proven, two by verified mechanism — see table). Fresh materialization: 18/18 + all four gates clean. Cleanroom spot-check of the report and commit text: clean.

## Per-finding disposition

| # | Audit-1 finding | Sev | Claimed remediation | Audit-2 disposition |
|---|---|---|---|---|
| 1 | No test pins the fixed motion behavior; integer-velocity revert / broken sign-extension / dropped fraction strip would pass 18/18 | LOW | Cadence gate hardened with the exact 8.8 accumulator model (positions + fractions, both cameras, every step) | **VERIFIED, mutation-proven.** Sign-extension mutant: hardened gate FAILS at step 1 (POS1X 958 vs model 702 = +256 sign defect; other 3 axes + all fractions still exact), pre-hardening suite passes 18/18 on the same ROM. Dropped fraction strip: the emulator's accumulator would retain the integer part, double-counting into the next frame's delta → position diverges from the (stripping) model at step ≤2 — caught by mechanism. Integer-velocity revert: ASM-only revert diverges at step 1 (~±512-scale vs ±2-scale deltas); generator+asset revert makes model and emulator agree on near-zero motion, which then trips the gate's pre-existing position-frozen guards; asset-only tamper fails `test_gen_pose_tables`'s regenerate-byte-compare (same 18 suite) and the provenance gate. All named classes covered. |
| 2 | [info] Task-1 handoff design sound; spike should assert the write-twice/back-to-back-channel nuance | info | Accepted, no code change | **VERIFIED as accepted.** `c50444e` contains no source change (diff scope: report + test only); the nuance is recorded in the shipped report §finding-2 for the future spike. Appropriate for an info note on an unbuilt future task. |
| 3 | [info] Residual ±12% integer-floor dither, expectation-setting | info | Accepted, no code change | **VERIFIED as accepted.** Documented in report §finding-3; no code change present or needed — the hardened model asserts the exact accumulator behavior including that dither. |

**Diff exactness:** `git show --name-status c50444e` → `A .../split_h_2p_demo-velocity-audit-1.md` + `M asm_repo_staging/tests/test_split_h_2p_demo.py` (+27/−1: `import struct`, docstring extension, model block). Nothing else.

**Model correctness:** verified line-against-line with `templates/split_h_2p_demo/main.asm`:
- Ordering — the ASM advances H1/H2 *before* the movement block; the test reads `h1`/`h2` after each `frame_step(1)`, i.e. exactly the headings that frame's movement used. Correct.
- Decomposition — with frac ∈ [0,255] and |vel| ≤ 512, `s ∈ [−512,767]`: sign-extended high byte ≡ Python `s // 256` (floor), low byte ≡ `s & 0xFF`, and `& 0x3FF` ≡ mod-1024 (1024 | 2^16). Exact, no overflow reachable.
- Addresses — POS_ADDRS (C060/62/64/66) and FRAC_ADDRS (C072/74/76/78) and H1/H2 (C06A/C06C) all match main.asm's WRAM layout; the velocity tuple order matches the address order and the ASM's `move64+0,x`/`move64+2,x` indexing; `gen_assets.py` packs `<hh` per heading — the test's unpack is the exact inverse.

## Evidence log (all regenerated by me from scratchpad kits at c50444e)

```
$ git show --name-status c50444e
A  asm_repo_staging/docs/audit/split_h_2p_demo-velocity-audit-1.md
M  asm_repo_staging/tests/test_split_h_2p_demo.py            (2 files, +109/−1)

$ bash asm_repo_staging/tools/dryrun_split.sh $SCRATCH/kit_a2
scrub_split: OK — 71 substitutions across 18 files; comment lineage guard clean
$ make build/split_h_2p_demo.sfc && bash templates/split_h_2p_demo/build_split_h_2p_variants.sh
built all 7 ROMs (5 x 64KB, 2 x 512KB rotate/rotfreeze)

$ python -m pytest tests/test_split_h_2p_demo.py tests/test_gen_pose_tables.py -q
run 1: 17 passed, 1 failed — test_structural_channels_and_liveness (wall-clock NMI
       heartbeat, sleep(2.0) → advanced >= 110; host-load flake)
solo re-run: 1 passed in 3.23s · full re-run: 18 passed in 20.83s
$ for i in 1 2 3; do pytest tests/test_split_h_2p_demo.py::test_rot_cadence_true_60fps_in_situ -q; done
1 passed in 1.64s · 1 passed in 1.64s · 1 passed in 1.65s        (hardened gate, 3/3)

$ bash tools/cleanroom_check.sh ; make width-check ; make zp-check ; make provenance-check
cleanroom: clean · width-check: clean (189 files) · zp_lint: 0 finding(s) across 230 file(s)
provenance: clean — 126 blob(s) accounted for (92 generated, 6 third-party, 9 attested, 19 artifact)
```

Mutant differential (scratch copy only; repo untouched):

```
mutation: main.asm (F1X axis, first of 4 sites): cmp #$0080 → cmp #$0180
          (A pre-masked to $00FF < $0180 always → bcc always taken → NEVER sign-extends)
$ pytest tests/test_split_h_2p_demo.py::test_rot_cadence_true_60fps_in_situ -q   # HARDENED gate
E  AssertionError: motion diverged from the 8.8 model at step 1:
   pos [958, 430, 721, 611] vs [702, 430, 721, 611], frac [116, 32, 206, 182] vs [116, 32, 206, 182]
   → FAILS at step 1; divergence isolated to POS1X, delta exactly +256 (the un-extended sign
     bit: −2 read as +254); other 3 positions + all 4 fractions still model-exact.  1 failed in 1.45s

$ git show 61580f1:asm_repo_staging/tests/test_split_h_2p_demo.py > tests/test_split_h_2p_demo.py
$ pytest tests/test_split_h_2p_demo.py::test_rot_cadence_true_60fps_in_situ -q   # same mutant ROM
1 passed in 1.74s
$ pytest tests/test_split_h_2p_demo.py tests/test_gen_pose_tables.py -q          # audit-1's exact claim
18 passed in 20.80s      → the old suite is blind to the defect; the hardening alone carries the load
```

Cleanroom spot-check: the report file is present in the materialized kit, so the clean `cleanroom_check.sh` run covered it; an independent regex sweep of the report and the `c50444e` commit message produced zero hits.

**Info notes (non-blocking):**
1. `test_structural_channels_and_liveness` flaked once on the first full-suite run (wall-clock heartbeat under host load; passed solo and on the full re-run). The test is untouched by `61580f1`/`c50444e` — environment flake, not a remediation defect; noting for suite-stability awareness.
2. The hardened model reads velocities from the same committed `move64.bin` the ROM incbins, so the model assertion alone cannot pin LUT *content* — that pin lives in `test_gen_pose_tables`'s regenerate-byte-compare and the provenance gate, with the gate's pre-existing position-frozen guards closing the generator-revert path. Coverage is complete as a system; recorded so no one later "simplifies" one of those legs away.
