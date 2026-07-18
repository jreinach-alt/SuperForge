# sf_split_v — audit-5 (DIAGONAL coloured seam via per-scanline HDMA)

**Scope:** the follow-up feature commit `6d84ca0` on `claude/split-v-diagonal-seam`
(diff base `b28d585`). Adds `hdma_build_split_diag` + helpers (`engine/hdma_engine.asm`),
`sf_split_v_diagonal` (`lib/macros/sf_split_v.inc`), a `-DDIAGONAL` `split_v_demo`
variant, and D6 ×2 tests. This is the raw-HDMA follow-up to the merged v1/v2 dual-view
(audits 1–4 CLEAN).

**Auditor:** independent audit agent (did NOT author this code). Research-only; no code
changes, nothing pushed.

**Verdict: CLEAN — ship.** 8/8 tests pass, stable ×3 + ×4 under full random power-on;
gates clean; the slant renders exactly (`seam[s] = 72 + s·0.5`, geometry byte-identical
across power-on seeds). Two non-blocking findings (both MEDIUM, both latent-only — they
cannot fire in the shipped demo): a 2-byte scratch-block **overrun past the iris block**
into `ES_STREAM_DMA_CHAN` ($0199), and a **missing alloc-fail guard** on the 2nd/3rd
HDMA channel. Recommend accept-and-file (fix opportunistically); neither gates the ship.

---

## 1. Test suite — fresh materialization, ×3 VERBATIM

Materialized clean: `bash tools/dryrun_split.sh /tmp/adg_kit` →
`scrub_split: OK — 71 substitutions across 18 files; comment lineage guard clean`.

### Run 1
```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/bin/python3
cachedir: .pytest_cache
rootdir: /tmp/adg_kit
collecting ... collected 8 items

tests/test_split_v_demo.py::test_d1_two_camera_split_clean_seam PASSED   [ 12%]
tests/test_split_v_demo.py::test_d2_cameras_scroll_independently PASSED  [ 25%]
tests/test_split_v_demo.py::test_d3_swept_seam_moves_boundary PASSED     [ 37%]
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 50%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 62%]
tests/test_split_v_demo.py::test_d6_diagonal_seam_slants PASSED          [ 75%]
tests/test_split_v_demo.py::test_d6_straight_seam_is_vertical PASSED     [ 87%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]

============================== 8 passed in 11.94s ==============================
```

### Run 2
```
tests/test_split_v_demo.py::test_d1_two_camera_split_clean_seam PASSED   [ 12%]
tests/test_split_v_demo.py::test_d2_cameras_scroll_independently PASSED  [ 25%]
tests/test_split_v_demo.py::test_d3_swept_seam_moves_boundary PASSED     [ 37%]
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 50%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 62%]
tests/test_split_v_demo.py::test_d6_diagonal_seam_slants PASSED          [ 75%]
tests/test_split_v_demo.py::test_d6_straight_seam_is_vertical PASSED     [ 87%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]

============================== 8 passed in 11.63s ==============================
```

### Run 3
```
tests/test_split_v_demo.py::test_d1_two_camera_split_clean_seam PASSED   [ 12%]
tests/test_split_v_demo.py::test_d2_cameras_scroll_independently PASSED  [ 25%]
tests/test_split_v_demo.py::test_d3_swept_seam_moves_boundary PASSED     [ 37%]
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 50%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 62%]
tests/test_split_v_demo.py::test_d6_diagonal_seam_slants PASSED          [ 75%]
tests/test_split_v_demo.py::test_d6_straight_seam_is_vertical PASSED     [ 87%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]

============================== 8 passed in 11.67s ==============================
```

8/8 all three runs, no flakiness. (The default harness regime is already RAM-random —
Mesen2 `RamPowerOnState=Random` — with PPU-latch randomization OFF.)

---

## 2. Per-criterion table

| Criterion | Result | Evidence |
|---|---|---|
| D1 two-camera split / clean seam (unchanged) | ✓ | `test_d1_...` PASS; render `default.png` shows two independent mountains split by a vertical white bar |
| D2 independent scroll (unchanged) | ✓ | `test_d2_...` PASS |
| D3 swept seam (unchanged) | ✓ | `test_d3_...` PASS |
| D4 OBJ clip ×2 (unchanged) | ✓ | `test_d4_obj_...` + `test_d4_default_...` PASS; `objclip.png` shows right-half marker clipped |
| D5 no-window collapse (unchanged) | ✓ | `test_d5_...` PASS; `nowin.png` single full-screen camera |
| **D6 diagonal slant** | ✓ | `test_d6_diagonal_seam_slants` (`tests/test_split_v_demo.py:326`) PASS; measured seam centres rise 78→178 monotonically down the screen, ~0.5 px/line, matching `base=72 slope=$0080` |
| **D6 non-vacuity (straight = vertical)** | ✓ | `test_d6_straight_seam_is_vertical` (`:349`) PASS; default seam centre constant (≤4 px). Control genuinely pins the detector — see §4-g |
| Clean-room (changed files) | ✓ | `cleanroom_check.sh` clean; targeted grep of the 5 changed files for the gate's retail/vendor lists — no hits |
| Gate: width-check | ✓ | `width-check: clean (177 files)` (engine files are out of scope; verified manually — §4-e) |
| Gate: zp-check | ✓ | `zp_lint: 0 finding(s) across 218 file(s)` |
| Gate: cleanroom | ✓ | clean (name tripwire) — re-verified WITH this report present (§6) |

---

## 3. VISUAL confirmation

Rendered fresh from the verified binaries (`run_seconds=0.4` + 30 settle frames):

- **`split_v_demo_diagonal.sfc`** — a **clean straight white slant bar** runs top-left
  to bottom-right across a legible landscape (blue sky / grey mountains / green hills /
  brown dirt), with the two independent camera views either side of it. Programmatic
  sampling of the white-bar centre X per row: `y=20→78, 40→88, 60→98, 80→108, 100→118,
  120→128, 140→138, 160→148, 180→158, 200→168, 220→178` — an exact linear slope of
  ~0.5 px/scanline (10 px per 20 rows), band width a constant 13 white px (2·hw + 1).
  The slant stays fully on-screen (66..190) — no clamping triggers for the demo params.
- **`default` / `nowin` / `objclip` / `autodemo`** — all UNCHANGED from the v2 baseline:
  `default` = straight vertical seam + two cameras; `nowin` = single full-screen camera,
  no seam; `objclip` = straight seam with the right-half marker clipped. The diagonal is
  strictly opt-in (`.elseif .defined(DIAGONAL)` in `main.asm`; the per-frame
  `sf_split_v_move` is `.ifndef DIAGONAL`-gated so HDMA owns WH0/WH2/WH3).

---

## 4. Adversarial analysis (the HDMA code is the whole risk)

### a. HDMA table correctness — CLEAN
- Format `[count=1, byte] × 225 + $00` is correct mode-0 HDMA: count byte `$01` =
  "apply this byte for 1 scanline, advance to next entry"; 225 entries drive scanlines
  0..224; `$00` terminator ends the table. This is a **faithful clone** of the shipping,
  four-audit-CLEAN sibling builders (`hdma_build_wave`, `hdma_build_scanline_scroll`) —
  same `sbc #3 / asl / _hdma_table_addrs` indexing, same terminator pattern
  (`engine/hdma_engine.asm:1633`, `:1649`).
- **225 vs 224:** the engine-wide convention is `HDMA_SCANLINES = 225`
  (`hdma_engine.asm:17`); every sibling loops to 225. Active NTSC display is 224 lines
  (0-223); the 225th entry is harmless (there is no line 225 without overscan — HDMA just
  doesn't reach it). No off-by-one, no stale/garbage line at top or bottom.
- **Nit (LOW, cosmetic):** the new fill loop hardcodes `cpx #225`
  (`hdma_engine.asm:2980`) instead of `cpx #HDMA_SCANLINES` like every sibling.
  Functionally identical; consistency-only.

### b. `$43n0` channel programming — CLEAN
- `DMAP=$00` (mode 0, 1 byte/write to a single reg) is correct for a per-scanline single
  WH byte. `BBAD` = `$26`/`$28`/`$29` = WH0/WH2/WH3 low bytes (correct). `A1T` = table
  home from `_hdma_table_addrs`, `A1B=$7E` (WRAM bank) — correct; tables are built with
  DB=$7E and live in the 1 KB-per-channel `$7EC000+` region (451 bytes used, fits).
- **CH2 collision:** none. `hdma_alloc` deliberately *skips* CH2 (it pins CH2 and
  re-requests so the `sbc #3` CH3-based table indexing holds — `hdma_engine.asm:80`).
  CH0/CH1 are the VBlank bulk-DMA reservations. `hdma_build_split_diag` gets CH3/CH4/CH5.
- **NMI fire path — CLEAN.** `_hdma_enable_channel` sets bits in `NMI_HDMA_ENABLE`, which
  is the SAME byte as `ES_HDMA_ENABLE_MASK` (`NMI_HDMA_ENABLE = ENGINE_STATE_BASE +
  ES_HDMA_ENABLE_MASK`, `engine_state.inc:640`). The NMI writes that mask to `$420C` every
  frame (`nmi_handler.asm:976`). The split-diag channels are NOT in `ES_M7_OWNED_MASK`, so
  the NMI's per-channel shadow→hardware copy is skipped (correct — the builder programmed
  the `$43n0` regs directly, once) and only the `$420C` re-arm applies — exactly the
  documented "retrofitted effect" contract (`nmi_handler.asm:838-854`). All 3 channels
  fire; confirmed by the render (a stable per-scanline slant every frame).

### c. 8.8 accumulator + clamp — CLEAN (verified against the ca65 listing)
- Integer extraction: `xba / and #$00FF` on the 8.8 accumulator = `acc >> 8`, correct.
  Seed: `lda BASE / xba / and #$FF00` = `base << 8`, correct.
- Signed offset: `-hw` pass computes `$0000 - hw = $FFFA` (−6, two's complement); the loop
  does `A(0..255) + $FFFA`. Extremes verified: seam−hw<0 → result negative → `bpl` not
  taken → clamp 0; seam+hw>255 → e.g. 252+6=`$0102` → `cmp #$0100` carry set → `bcc` not
  taken → clamp `$FF`. Both clamp branches flow correctly (the negative-clamp `@nn` sits
  *before* the `cmp #$0100`, so a clamped-0 still passes the upper test). Correct at both
  extremes.
- Demo range (base=72, slope=$0080, 225 lines): acc 72..184; ±hw → 66..190; fully
  on-screen, no clamp fires — matches the measured render.

### d. Scratch reuse ($0189+) — **FINDING M1 (MEDIUM, latent-only)**
The docstring + guide claim the scratch "reuses the iris DP-shadow block." The iris block
is `$0189–$0198` (16 bytes: `HDMA_IRIS_CX`…`HDMA_IRIS_SQRT_ODD`, `hdma_engine.asm:868`),
and `engine_state.inc:319` documents that exact 16-byte claim. The diagonal block is
**`$0189–$019A` (18 bytes)**: `HDMA_SPLITD_BBAD` sits at `$0199–$019A`, **2 bytes past**
the iris block. Those 2 bytes are NOT free scratch:
- `$0199` = `ES_STREAM_DMA_CHAN` / `STREAM_DMA_CHAN` (`engine_state.inc:351`, `:1406`) —
  the BG1 streaming DMA channel number, live in streaming ROMs (mode7_explore,
  platformer_stream) from `streaming_init` onward.
- `$019A` = a documented free DP byte (`$9A`).

**Live collision in the shipped demo: NONE.** `split_v_demo` includes no streaming/iris
code (grep confirmed), and `HDMA_SPLITD_BBAD` is transient setup scratch (live only during
the one-time `hdma_build_split_diag` call, never during gameplay). So the feature ships
correctly. **The risk is latent:** if a *streaming* rail ever armed a diagonal seam AFTER
`streaming_init`, the build would clobber `STREAM_DMA_CHAN` → streaming-DMA corruption.
It's also an allocation-hygiene violation (writing a live-symbol byte the block-claim
comment says it doesn't touch) that `engine_state.inc` does not record.
→ **Accept for ship; file to fix opportunistically** — either move `HDMA_SPLITD_BBAD` down
to reuse an in-iris-block word (only 8 of the 9 SPLITD words need to persist across the
config loop; `BBAD` is a scalar that could share `ACC`/`OFF`'s lifetime), or claim
`$9A`/`$9B` explicitly in `engine_state.inc` and add a "not with streaming" caveat.
`HDMA_TBL_PTR`/`$B0` reuse IS safe (only touched during the one-time setup build; no NMI
or concurrent effect writes it in a split-diag ROM).

### e. Width discipline — CLEAN (verified from the ca65 listing)
Assembled a listing wrapper (`engine_state.inc` + `hdma_alloc.asm` + `hdma_engine.asm`).
Machine-code operand sizes confirm the M/X state at every site:
- A8 sections: `A9 xx` (2-byte imm) around the `$43n0` reg writes (`9F .. 43 00`) and the
  table byte writes (`91 B0` = `sta (dp),y`). The `pha`/`pla` seam-byte save/restore
  (`48`…`68`) is inside A8 and balanced.
- A16 sections: `A9 xx 00` / `C9 00 01` (3-byte imm). The `xba` (`EB`) at both the seed
  and the per-line extraction is in A16 (correct — xba on the 16-bit accumulator).
  `tax`/`tay`/`asl` indexing all A16/I16.
- Every `sep #$20` (`E2 20`) is paired with a matching `rep #$30` (`C2 30`) restore; entry
  and exit are A16/I16 as the contract states. **No A8 leak.**

### f. Power-on fidelity — CLEAN (feature); pre-existing template observation (informational)
The **diagonal geometry is byte-deterministic** across random power-on seeds: rendered the
`_diagonal` ROM under `SF_HW_POWERON=hw` (RAM-random + PPU-latch randomization) across 4
seeds — the white slant bar's shape and position are identical in every frame; the HDMA
tables are built before enable (no read-before-write). What *does* flap under full
PPU-latch randomization is the **palette/CGRAM** (the sky/mountain/dirt colours resolve to
garbage on some seeds) — **but the UNCHANGED `default` ROM flaps identically** (verified:
3 default captures under `SF_HW_POWERON=hw` produced 3 different hashes too). So this is a
**pre-existing `split_v_demo` template CGRAM-init property under full PPU-latch rand, not a
regression from this commit** — and it does not appear under the project's default test
regime (RAM-random, PPU-latch OFF), which is why all 8 tests are stable. No action for this
audit; noted for whoever eventually sequences the `SF_HW_POWERON` rollout.

### g. D6 non-vacuity — CLEAN, genuinely pinned
`test_d6_straight_seam_is_vertical` runs the SAME detector (`_seam_band_center`) on the
`default` (straight) ROM and asserts the centre varies ≤4 px, while the diagonal test
asserts a >40 px rise. The two share the detector, so a broken diagonal ROM (e.g. HDMA not
firing → a straight bar) would FAIL the slant test (constant centre, <40 px rise). The
control genuinely distinguishes a real per-scanline slant from a detector artifact. The
>40 px threshold has healthy margin (measured 100 px). Not vacuous.

### h. Robustness — **FINDING M2 (MEDIUM, latent-only)**
`hdma_build_split_diag` checks `hdma_alloc`'s `#$FFFF` failure return ONLY on the **first**
channel (`hdma_engine.asm:2903` `cmp #$FFFF / bne @got0 / rts`). The 2nd and 3rd allocs
store the result unconditionally (`sta HDMA_SPLITD_CH2` / `CH3`). If only 1 or 2 channels
are free, `$FFFF` becomes a "channel number", then `_hdma_splitd_cfg`/`_fill`/
`_enable_channel` do `sbc #3` → `$FFFC`, `asl` → a wild index into the 5-word
`_hdma_table_addrs`, and `X = ch·16` wraps — writing HDMA config to a bogus `$43n0` and a
garbage table home. The docstring even claims *"no-op (returns) if <3 are free"* — but the
code only guards `<1`. **Cannot fire in the demo** (CH3/CH4/CH5 are always free at setup),
so ship is unaffected; but it's a real contract violation vs. its own docs and would
misbehave in a channel-contended scene (e.g. a diagonal seam layered over Mode-7 HDMA).
→ **Accept for ship; file to fix** — guard all three allocs (roll back the first channel(s)
via `hdma_off`/release and `rts` if any of the three fails), or at minimum honor the
documented "<3 free → return" contract.

### i. Clean-room grep — CLEAN
`cleanroom_check.sh` clean. Targeted case-insensitive grep of the 5 changed files
(`hdma_engine.asm`, `sf_split_v.inc`, `main.asm`, `test_split_v_demo.py`,
`docs/guides/split_v.md`) for the gate's retail-title / hardware-vendor / eliminated-lineage
lists — no hits. Comments describe only the hardware mechanism (WH0/WH2/WH3, `$43n0`, 8.8
fixed) and cross-reference in-kit files.

---

## 5. Findings summary

| ID | Severity | Area | Fires in shipped demo? | Recommendation |
|----|----------|------|------------------------|----------------|
| M1 | MEDIUM | Scratch overrun: `HDMA_SPLITD_BBAD` at `$0199–$019A` spills 2 bytes past the iris block into `ES_STREAM_DMA_CHAN` ($0199) | No (no streaming/iris in demo; transient setup scratch) | Accept + file: relocate `BBAD` into the iris block, or claim `$9A`/`$9B` in `engine_state.inc` + add a "not with streaming" caveat |
| M2 | MEDIUM | Missing alloc-fail guard on the 2nd/3rd `hdma_alloc` (docstring claims "no-op if <3 free"; code guards only <1) | No (3 channels always free at demo setup) | Accept + file: guard all three allocs (release + `rts` on any fail) |
| L1 | LOW | `cpx #225` literal instead of `cpx #HDMA_SCANLINES` (sibling convention) | n/a cosmetic | Accept |
| I1 | INFO | `_diagonal` (and unchanged `default`) palette flaps under full PPU-latch random power-on — pre-existing template CGRAM-init, not this commit | n/a (not in default test regime) | No action here; note for the `SF_HW_POWERON` rollout |

The commit message + guide propagate M1's inaccurate "reuses the iris DP-shadow block"
wording (it's the iris block **+2 bytes**); worth correcting alongside the M1 fix.

**No HIGH findings.** The HDMA table math, `$43n0` programming, NMI fire path, 8.8
accumulator/clamp, and width discipline are all correct and verified against the emulator
render + the ca65 listing.

---

## 6. Report re-materialization check

Re-ran `bash tools/dryrun_split.sh` with this report present in the source tree; confirmed
`scrub_split: OK` and `cleanroom_check.sh` stays clean (report refers to "the gate's lists"
rather than quoting forbidden tokens).
