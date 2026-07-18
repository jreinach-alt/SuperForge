# Audit-1 — `sf_split_v` v1 (vertical dual-view primitive + `split_v_demo` rail)

- **Branch:** `claude/sf-split-v-9mkvvo` @ `470cf7a`
- **Spec:** `origin/claude/split-mode-spec:docs/split_mode_spec.md` §9 (owner-settled 2026-06-30 v1 DoD)
- **Auditor:** audit-1 (independent; did not write the code; research-only, no code changes)
- **Materialized kit under test:** `/tmp/audit1_kit` (via `asm_repo_staging/tools/dryrun_split.sh`)
- **Verdict: CLEAN — ship.** All D1–D5 + clean-room + gates PASS. One LOW deviation (macro signature differs from the spec's *intent* sketch) — accept. No HIGH/MEDIUM findings.

---

## 1. Test suite (fresh materialization, run VERBATIM)

`make split_v_demo` + `build_split_v_variants.sh` build cleanly; the fixture drives all three ROMs.

**Run 1:**
```
tests/test_split_v_demo.py::test_d1_two_camera_split_clean_seam PASSED   [ 14%]
tests/test_split_v_demo.py::test_d1_zero_cross_bleed_at_seam PASSED      [ 28%]
tests/test_split_v_demo.py::test_d2_cameras_scroll_independently PASSED  [ 42%]
tests/test_split_v_demo.py::test_d3_swept_seam_moves_boundary PASSED     [ 57%]
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 71%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 85%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]
======================== 7 passed, 12 warnings in 9.36s ========================
```
**Run 2 (flakiness — RamState::Random re-seeds per load):** `7 passed ... in 9.08s`. No flakiness.

(Only warning: a Pillow `getdata` deprecation — cosmetic, LOW, non-blocking.)

## 2. Gates (fresh materialization)

```
width-check: clean (177 files)
zp_lint: 0 finding(s) across 218 file(s); 167 DP symbols covering 208 bytes
cleanroom: clean
```

## 3. Per-criterion table

| Criterion | Verdict | Evidence |
|---|---|---|
| **D1** two-camera split, clean straight seam, ZERO cross-bleed | ✓ | `test_d1_two_camera_split_clean_seam` + `test_d1_zero_cross_bleed_at_seam` PASS. Both read the **framebuffer** (`_grab` → screenshot → per-pixel `_classify` against 8 self-sampled block colours). Left region must match camera-A phase >95%; right must match camera-B phase >95% AND camera-A <5%; a per-pixel scan asserts `bleed_b_left==0` and `bleed_a_right==0`. Runtime regs confirm W12SEL=$32, TMW=$03, WH0=128. Visual: `split_v_default.png` shows a clean centre seam, left = red/grn/blu/yel (cam A scroll 0), right = orange/grey/red/grn (cam B, +64 phase) — discontinuous at the seam. |
| **D2** input moves each camera INDEPENDENTLY | ✓ | `test_d2_cameras_scroll_independently` PASS, measured on rendered output (`_dominant` colour per half). P1(port0) right → `left1!=left0` AND `right1==right0`; P2(port1) right → `right2!=right1` AND `left2==left1`. Engine `input_handler.asm` reads `JOY2_CURRENT` for player 1 (L44); `mesen_runner.py` Port2 enable makes P2 drive. |
| **D3** swept seam moves the rendered boundary | ✓ | `test_d3_swept_seam_moves_boundary` PASS. P1 R-shoulder → `seam_r>seam0` (shadow) AND `_cam_a_extent` (rendered cam-A column count) grows by >8px; L-shoulder shrinks it. Both the WH0 shadow AND the rendered extent are asserted, so the shadow read is anchored to pixels, not a bare proxy. |
| **D4** seam-straddling sprite clipped to its half (OBJ window) | ✓ | `test_d4_obj_window_clips_marker_at_seam` PASS: `left>0` (non-vacuous: marker present left of seam) AND `across==0` (clipped). Companion `test_d4_default_marker_not_clipped` PASS: default ROM `across>0` (proves the clip is real, not a missing sprite). TMW=$13 in objclip, $03 in default. Visual: `split_v_objclip.png` shows only the left-of-seam white block; the across-seam P1 portion AND the right-half P2 marker (at seam+24, inside the masked band) are gone. |
| **D5** `-DNO_WINDOW` non-vacuity control → D1 two-region assertion MUST FAIL | ✓ | `test_d5_no_window_collapses_to_single_camera` PASS. Asserts window shadows zero (W12SEL=$00, TMW=$00 — `sf_split_v_off`/compiled-out path), then applies D1's right-half check and asserts `not(right_b>0.95)` (the D1 property fails) AND `right_a>0.95` (whole screen is single camera A). Visual: `split_v_nowin.png` is one continuous 8-block cycle, NO seam discontinuity. |
| **Clean-room** (no retail titles / eliminated-lineage vocab in `asm_repo_staging/`) | ✓ | `cleanroom_check.sh` clean on the full materialized tree. Targeted grep over the new files (`sf_split_v.inc`, `templates/split_v_demo/*`, `test_split_v_demo.py`) for the gate's full retail-title list and eliminated-lineage vocabulary list (as defined in `tools/cleanroom_check.sh`): **zero hits**. Roadmap entry is mechanism-only. (This audit doc deliberately does not quote those forbidden tokens verbatim, so it itself passes the gate.) |
| **Gates** clean on fresh materialization | ✓ | width/zp/cleanroom all clean (§2). |

## 4. Adversarial findings

1. **D1 tests read the framebuffer, not a proxy (rule #2 satisfied).** Every D1 pass/fail reads screenshot pixels classified against block colours self-sampled from the render. The W12SEL/TMW/WH0 shadow reads are *gating asserts* only; the verdict is pixel-based. ✓
2. **D5 is a genuine non-vacuity control.** It positively asserts both the failure of the D1 property (`right_b` NOT >95%) and the single-camera collapse (`right_a` >95%). A window that silently zeroed only one nibble would fail one of the two halves. The `block_refs` fixture itself is sampled from the nowin ROM (pure cam-A) — independent of any BGR15→RGB888 constant. ✓
3. **D4 OBJ-clip is not vacuous.** Asserts the marker IS present left of seam (`left>0`) before asserting it's clipped across (`across==0`); the default-ROM companion proves the across-seam marker renders when clipping is off. ✓
4. **`obj_clip` arg handling (blank / 0 / 1) is correct.** Verified by assembling the macro for all three forms and reading the ca65 listing: blank → TMW=$03, no WOBJSEL store; `0` → TMW=$03, no WOBJSEL store; `1` → TMW=$13 + `sta SHADOW_WOBJSEL`. The `.ifblank`/`.if` branching resolves as documented. The seam store emits a long write (`8F 0A E1 7E` = `sta f:$7EE10A`), correct WRAM addressing.
5. **`sf_split_v_off` / `-DNO_WINDOW` truly zero the window shadows.** `sf_window_off` `stz`'s W12SEL/W34SEL/WOBJSEL/WBGLOG/TMW/TSW. Runtime read on nowin ROM: W12SEL=$00, TMW=$00 (D5 asserts both). WH0-3 edge shadows are intentionally left as-is (harmless with enables cleared) — documented; nowin's WH0 reads 0 only because `-DNO_WINDOW` skips the `sf_split_v` call entirely, so WH0 is never written (and the coldstart WRAM clear left it 0). No impact on any assertion.
6. **Width/ZP discipline sound.** `main.asm` branch targets `@row`/`@col` are re-annotated `.a16`; `game_loop:` is entered in A16/I16; the `btn / cmp / and #$00FF` loop runs entirely A16 (the `and #$00FF` is correctly a 16-bit immediate here, not the A8-leak bug class). The `sf_split_v` macro's WIDTH-RISK contract (enter A16 → sub-macros toggle A8 for byte stores → restore A16 → exit A16) holds: every `sf_window_*` sub-macro does `sep #$20 / … / rep #$20`. `btn` documents A16-in/A16-out with X/Y preserved. `width-check` clean.
7. **Power-on fidelity — BG3 enabled-but-unused is SAFE.** `gfxmode #1` sets TM=$17 (BG1+BG2+BG3+OBJ) and BGMODE=$09 (Mode 1 + BG3-priority bit), but the demo never writes BG3's tilemap (word $6000) or CHR. This is NOT an uninit-read bug: `sf_coldstart` clears all 64 KB of VRAM to zero under forced blank (verified in `sf_core.inc`), so BG3 reads tile 0 = transparent everywhere. Empirically confirmed: 4 successive power-on loads (RamState::Random re-seeds each) all render identically (exactly 8 block hues + black backdrop + white markers, zero garbage); BG3 tilemap at word $6000 reads all-zero. No VRAM/CGRAM/OAM region is read-before-write. (The legitimate forced-blank VRAM clear, not a "zero-init to be safe" shortcut.)

## 5. Deviations

| # | Deviation | Severity | Recommendation |
|---|---|---|---|
| 1 | **Macro signature differs from the spec's intent sketch.** §9 "Macro API (intent)" sketches `sf_split_v cameraA, cameraB, seam_x`; the shipped macro is `sf_split_v seam, obj_clip`. The spec's signature implies the macro programs the two cameras (scroll); the shipped macro programs ONLY the window-clip recipe and the demo's CALLER owns the two `scroll` writes (`sf_split_v.inc` L21-23 documents this explicitly). The spec text labels the API as "(intent)" / "Mechanism-only", and the §9 register recipe ("two BG layers each scrolled to a camera") frames the cameras as caller-owned. The shipped split — macro = window recipe, caller = cameras — is a defensible, arguably cleaner factoring and is fully documented in the macro header and the roadmap entry. | **LOW** | **Accept.** The spec marks the signature as intent, not contract; the DoD done-conditions (D1–D5) are all met by the shipped factoring. Flag for the owner's awareness only; no fix needed. |
| 2 | **Pillow `getdata` DeprecationWarning** in `_grab`. | **LOW** | **Defer.** Cosmetic; `get_flattened_data` migration is a trivial opportunistic follow-up, not a v1 blocker. |

## 6. Ambiguities resolved

- **"zero cross-bleed" interpretation:** the spec says "0 right-camera px left of seam, vice-versa." The implementation realises this with a phase offset (cam B = cam A + 64 = +2 blocks) so camera-B content is *never colour-coincident* with camera-A content, making per-pixel bleed directly measurable (`test_d1_zero_cross_bleed_at_seam`). Sound and matches spec intent.
- **Seam read as proxy:** resolved — the seam shadow (WH0) is only a gating assert; D1/D3 cross-check it against the rendered camera-A extent, so it is anchored to pixels.
- **nowin WH0=0 vs default WH0=128:** resolved — `-DNO_WINDOW` skips `sf_split_v` entirely, so WH0 is never written; coldstart left it 0. No criterion depends on nowin's WH0.

## 7. Materialization note (per brief)

The kit does NOT commit `.sfc` binaries — the test fixture builds all three ROMs fresh from source (`make split_v_demo` + `build_split_v_variants.sh`). The "tracked binary" re-rendered for the visual cold-read here IS the fresh build (`/tmp/audit1_kit/build/split_v_demo*.sfc`), so the stale-binary divergence class (committed `.sfc` ≠ source) does not apply to this kit.

## Visual artifacts

- `/tmp/e2e_screenshots/split_v_default.png` — two camera halves, clean centre seam, markers.
- `/tmp/e2e_screenshots/split_v_nowin.png` — one continuous full-screen camera A (D5 collapse).
- `/tmp/e2e_screenshots/split_v_objclip.png` — seam-straddling marker clipped to the left half.
