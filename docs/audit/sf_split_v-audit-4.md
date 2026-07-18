# sf_split_v v2 — Audit 4 (production-hardening: shared-CHR + zero-sprite colour seam)

**Commit:** `66ff321` on `claude/sf-split-v-9mkvvo` (diff `dc189cf..66ff321`)
**Auditor:** independent audit agent (did NOT write this code) · research-only, no changes pushed
**Verdict: CLEAN.** All D1–D5 done-conditions hold on the rendered framebuffer, all three gates
(width / zp / cleanroom) are green on a fresh materialization, the two new high-risk mechanisms
(shared-CHR VRAM override + two-window coloured seam) are provably correct, and no findings rise
above LOW.

> NOTE (agent isolation): this report was authored in the audit agent's isolated worktree at the
> same relative path (`asm_repo_staging/docs/audit/sf_split_v-audit-4.md`). The orchestrator should
> relocate it into the `claude/sf-split-v-9mkvvo` branch worktree (`/home/user/SuperForge`). Not
> committed/pushed, per brief.

---

## 1. Test suite — 3× fresh runs (verbatim), no Pillow deprecation warnings

Materialized to `/tmp/av2_kit` via `tools/dryrun_split.sh`; ROMs built fresh.

### Run 1
```
============================= test session starts ==============================
platform linux -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/bin/python3
cachedir: .pytest_cache
rootdir: /tmp/av2_kit
collecting ... collected 6 items

tests/test_split_v_demo.py::test_d1_two_camera_split_clean_seam PASSED   [ 16%]
tests/test_split_v_demo.py::test_d2_cameras_scroll_independently PASSED  [ 33%]
tests/test_split_v_demo.py::test_d3_swept_seam_moves_boundary PASSED     [ 50%]
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 66%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 83%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]

============================== 6 passed in 10.04s ==============================
```

### Run 2 (`python3 -W all` — warnings surfaced)
```
tests/test_split_v_demo.py::test_d1_two_camera_split_clean_seam PASSED   [ 16%]
tests/test_split_v_demo.py::test_d2_cameras_scroll_independently PASSED  [ 33%]
tests/test_split_v_demo.py::test_d3_swept_seam_moves_boundary PASSED     [ 50%]
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 66%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 83%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]

============================== 6 passed in 9.92s ===============================
```

### Run 3
```
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 66%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 83%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]

============================== 6 passed in 9.91s ===============================
```

**Pillow deprecation warnings:** NONE across all three runs (`grep -in "deprecat|getdata|Warning"` →
NONE). The `getdata()` → `img.load()` migration is complete and clean.

## Gates (fresh materialization, `/tmp/av2_kit`)
```
width-check: clean (177 files)
zp_lint: 0 finding(s) across 218 file(s); 167 DP symbols covering 208 bytes
cleanroom: clean
```

---

## 2. Per-criterion table

| Criterion | Result | Evidence |
|-----------|--------|----------|
| **D1** left=camA / right=camB / clean seam / zero bleed | ✓ | Test `test_d1` (tests/test_split_v_demo.py:181): W12SEL=$BA, TMW=$07, seam=128. Independent proof: LEFT half of split render matches pure-camera-A (nowin) 102/102 columns (0 diff); RIGHT half diverges 50/48. Render `default.png`. |
| **D2** independent per-camera input | ✓ | Test `test_d2` (:216): P1 moves only left, P2 only right, cross-half unchanged (==0). |
| **D3** swept seam moves boundary | ✓ | Test `test_d3` (:249): band flips camB→camA as seam sweeps right, back on left. |
| **D4** straddling marker clipped + right marker confined out | ✓ | Test `test_d4_obj_window_clips_marker_at_seam` (:280): TMW=$17, red left-of-seam present, ZERO at/right. Non-vacuity `test_d4_default_marker_not_clipped` (:302): default TMW=$07, red DOES cross. Render `objclip.png` shows P1 clipped to a sliver + P2 gone. |
| **D5** -DNO_WINDOW collapses; D1 signature absent | ✓ | Test `test_d5` (:325): TMW=$00, seam discontinuity <6. Render `nowin.png` = one continuous camera, no seam. |
| **Clean-room** | ✓ | Changed files (`sf_split_v.inc`, `main.asm`, `test_split_v_demo.py`, `split_v.md`, `roadmap.md`) grep-clean vs. the gate's lineage + commercial lists; `cleanroom_check.sh` clean on fresh materialization AND with this report present. |
| **Gates** width/zp/cleanroom | ✓ | See §1. |

---

## 3. Visual re-render (settle frames applied; `/tmp/av2_render/`)

- **default.png** — Two distinct camera views of the SAME landscape (left frames a tall mountain
  peak; right frames a different lower ridge), a clean full-height WHITE backdrop seam bar with NO
  sprites inside it, and one red marker per half (P1 just left of the seam, P2 in the right half).
- **objclip.png** — The P1 marker straddling the seam is clipped to a red sliver at the seam's left
  edge (its across-seam portion gone); the right-half P2 marker is entirely absent (OBJ confined to
  the left half). The seam bar is intact and full-height.
- **nowin.png** — One continuous single-camera scene (camera A), NO seam bar, no split, no markers;
  the horizon is continuous across centre. Confirms the D5 collapse.
- **autodemo_a.png / autodemo_b.png** (~40 frames apart) — The white seam bar stays FIXED at centre
  while the two halves pan independently: between the two frames the left half's mountain drifts off
  the left edge and the right half's terrain shifts differently. The classic split-screen look.

Playfield colour census (default): exactly 6 colours — sky-blue, grass-green, mountain-grey,
dirt-brown, white (backdrop/seam), red (markers). No stray/garbage colours anywhere.

---

## 4. Adversarial findings

### Shared-CHR override — CORRECT (highest-risk surface)
- **Two genuinely different cameras from one VRAM copy, proven.** Compared the split view's halves
  against a pure-camera-A render (the nowin ROM): LEFT half matches camera A exactly (102/102 cols,
  0 diff → no camera-B bleed, window does not disturb camera A); RIGHT half diverges substantially
  (50 diff / 48 same) → BG2 is rendering camera-B content (a different scroll) from the SAME shared
  base, not accidentally identical, not one camera. This is the strongest non-vacuity proof of the
  override.
- **NMI never clobbers the override.** Read `engine/nmi_handler.asm` end-to-end: it commits BG
  scrolls ($210D–$2114), BGMODE/MOSAIC/TM/INIDISP, and the window regs (W12SEL/W34SEL/WOBJSEL/
  WBGLOG/WOBJLOG/TMW/TSW/WH0–3) — but NEVER writes BG2SC ($2108) or BG12NBA ($210B). The setup-time
  `$2108=$58` / `$210B=$22` writes hold for the life of the ROM. The comment at main.asm:100 is
  accurate.
- **No double-write of VRAM.** `mset #2` is gone (main.asm:180 now `mset #1` only); CHR uploaded
  once (`@chr` loop). No region is written twice.
- **No glitch from BG2 reading BG1's map/CHR** — render is clean (6 colours, no artefacts at the
  layer seam).

### Coloured-seam window math — CORRECT
- W12SEL=$BA decodes exactly: BG1 low nibble = win1-inside($02)|win2-inside($08)=$0A; BG2 high
  nibble = (win1-outside($03)|win2-inside($08))=$0B<<4=$B0 → $BA. Matches the test assertion and the
  guide table.
- W34SEL=$08 = BG3 win2-inside (band). **BG3 IS masked in the band** — confirmed decisive: gfxmode
  #1 sets TM=$17 (BG3 ON, main screen) and BGMODE=$09 (BG3 priority=1, i.e. BG3 can render in FRONT
  of BG1/BG2), and the demo never uploads BG3 content. If BG3 were not masked in the band, its
  default VRAM could show in the seam. It does not: the seam band is 100% white across every
  non-marker row (0 non-white pixels sampled), and the whole frame has only 6 legit colours → the
  backdrop is genuinely revealed, not a masked BG.
- WBGLOG=$00 (OR): BG1 masked = win1-inside OR win2-inside; BG2 = win1-outside OR win2-inside; BG3 =
  win2-inside only (win1 not selected in W34SEL). All-masked-in-band → backdrop. Correct.
- No wrong-layer bleed into the seam bar.

### `sf_split_v_colorseam` assemble-time arithmetic — CORRECT with a documented operand trap
- The macro wraps args with `#` INTERNALLY (`#sf_seam`, `#(sf_seam-sf_hw)`, `#(sf_seam+sf_hw)`), so
  callers pass BARE literals (demo: `SEAM0, BAND_HW, 0` → 128, 6). Band edges = 122 / 134 — correct.
- **Operand-convention trap (LOW):** if a caller mistakenly passes `#128`, the macro emits
  `#(#128 - 6)` → an assemble error. This is a *loud* failure (not silent corruption) and IS
  documented in both the macro header (:94 "BARE literals") and the guide (:83). Accept.

### `sf_split_v_move` width + clamp — CORRECT
- `sep #$20`/`.a8` … byte writes to WH0/WH1/WH2/WH3 … `rep #$20`/`.a16`. No A8 leak past the macro;
  width annotations present; `sbc #sf_hw`/`adc #sf_hw` are 1-byte A8 immediates (bare literal 6).
- `lda sf_seam` in A8 reads SEAM's low byte only — safe because SEAM is always 0..255 (high byte 0,
  set A16 from `#SEAM0` and only inc/dec'd within the clamp).
- **Clamp: no underflow/overflow.** Seam clamp (main.asm:275–291) holds SEAM in [SEAM_LO=64,
  SEAM_HI=192] (R increments only if <192; L decrements only if ≥65). Band extremes: seam=64 →
  [58,70]; seam=192 → [186,198] — both within [0,255]. Safe. `make width-check` clean.

### Tests non-vacuous — CONFIRMED
- D1 proves left=camA / right=camB *against the shared-CHR stage*: the LEFT-half equality
  (>0.95 match to camera A) and RIGHT-half divergence (>0.4) would BOTH fail if BG2 were
  mis-configured (identical to A → right wouldn't diverge; not-camera-A → left wouldn't match). The
  independent nowin-vs-split pixel comparison corroborates this outside the test.
- D4 red-marker check is non-vacuous: `test_d4_default_marker_not_clipped` asserts red IS present
  at/right of the seam in the default ROM, so the objclip "no red at/right" assertion is a real
  clip, not an empty set. `_is_red` (p[0]>150, p[1]<80, p[2]<80) matches the marker's $001F red.
- Excluding white seam columns from the horizon read hides no cross-bleed: the LEFT-half zero-bleed
  claim is verified on the terrain horizon (non-seam columns) AND independently by the direct
  pixel comparison (LEFT 0/102 diff vs camera A).

### Power-on fidelity — CLEAN
- Render is BYTE-STABLE across 4 power-on RAM seeds (identical MD5 of the framebuffer). No
  dependency on uninitialized WRAM/VRAM.
- Despite BG3 being enabled + high-priority + never-initialized, no BG3 garbage appears anywhere
  (band or elsewhere): masked in the band, occluded by opaque BG1/BG2 elsewhere. 6-colour census
  confirms.

### Sprite / behaviour — CLEAN
- The 52-sprite OBJ divider is gone; only 2 marker sprites remain (`spr #1` ×2). `spr_clear` each
  frame. No OAM issue; the OBJ window (objclip) correctly clips one marker and hides the other.
  `DIVY`/`RCOLX` scratch ZP (old divider) removed cleanly; no dangling references.

### Clean-room grep — CLEAN
- Changed files (incl. the new guide `docs/guides/split_v.md`) grep-clean against the gate's
  lineage and commercial name lists. `cleanroom_check.sh` passes on a fresh materialization AND with
  this report present in the tree.

---

## 5. Severity & disposition

| # | Finding | Severity | Disposition |
|---|---------|----------|-------------|
| 1 | `colorseam`/`move`/`cameras` operand convention differs from `sf_split_v`/`sf_window` (bare literals, not `#N`); a `#N` caller gets an assemble error | LOW | **Accept** — loud (not silent) failure; documented in macro header + guide. |
| 2 | Automated per-frame cost-regression test deferred (no cheap cycle counter in harness) | LOW | **Accept/defer** — cost is deterministic (4 byte writes + 2 scroll commits), spec-verified, documented in the guide backlog. |

No HIGH or MEDIUM findings.

**Overall: CLEAN.** The v2 shared-CHR override and the two-window coloured seam are correct,
render-verified, byte-stable across power-on seeds, and gate-clean. Ship.
