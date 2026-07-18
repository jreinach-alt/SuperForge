# sf_split_v — audit-2 (landscape-stage + horizon-test REWORK)

**Scope:** commit `0bb0210` on `claude/sf-split-v-9mkvvo` ONLY — the demo-stage rework
(abstract 8-colour "rainbow" stage → legible side-on LANDSCAPE built from a 32-column
height map) and the corresponding test rewrite (colour-block classification → HORIZON-line
read). The `sf_split_v` primitive (`lib/macros/sf_split_v.inc`) is **byte-identical** to
audit-1 (`diff b5460cc..0bb0210` touches only `templates/split_v_demo/main.asm`,
`tests/test_split_v_demo.py`, `docs/roadmap.md`).

**Independent agent** — did not author the code or the rework. Research-only; no code
changes, nothing pushed.

**Method:** fresh materialization (`tools/dryrun_split.sh /tmp/audit_ls_kit`), gates +
suite from the materialized kit, cycle-accurate Mesen2 renders read at the framebuffer,
ca65 listing inspection for width encoding, multi-seed power-on probes.

---

## OVERALL VERDICT: **CLEAN**

All D1–D5 + clean-room + the three gates pass on a fresh materialization. The rewritten
horizon tests are **non-vacuous and genuinely discriminating** (verified by measuring the
actual signal margins, not just "green"). Render is **bit-stable** across 5 distinct
power-on seeds and frame-to-frame once settled (0-column horizon delta). Width discipline
on the new tilemap-fill loop is correct at the encoded-byte level. No HIGH or MEDIUM
findings. Two LOW observations (one carried over from audit-1, one new doc nit) — accept.

---

## Per-criterion table

| Criterion | Result | Evidence |
|---|---|---|
| **D1** left=camA / right=camB / clean seam / zero bleed | ✓ | `test_d1_*` PASS. Measured: left half matches camA ref **116/116 cols (100%, zero bleed)**; right diverges **68/116 (59%)**; seam step **disc@128 = 72** (threshold >20). `main.asm:198-206` window recipe; test asserts committed `W12SEL=$32`, `TMW=$03`, `WH0=128`. |
| **D2** independent per-half camera input | ✓ | `test_d2_*` PASS. Non-driven half asserted to change **== 0 cols** (strict). P1→left only, P2→right only (`main.asm:222-255`). |
| **D3** swept seam moves rendered boundary | ✓ | `test_d3_*` PASS. Asserts BOTH `seam_shadow moved` AND band flips camB→camA→camB (`in_a 0.x→>0.8→<0.3`) — shadow-move coupled to render-change, not one alone. `main.asm:256-272,277`. |
| **D4** straddling marker clipped to half (OBJ window) | ✓ | `test_d4_obj_window_*` PASS + `test_d4_default_*` non-vacuity PASS. Measured: default white cols `120-135,152-159`; objclip `120-127` only (across-seam + right marker fully clipped at the seam boundary, last white col 127 vs seam 128). `main.asm:201-202`. |
| **D5** `-DNO_WINDOW` collapses → D1 signature ABSENT | ✓ | `test_d5_*` PASS. nowin **disc@128 = 0** (threshold <6) vs default 72; window shadows asserted all-zero. `main.asm:198-199`. |
| **Clean-room** (no retail titles / lineage vocab in `asm_repo_staging/`) | ✓ | `cleanroom_check.sh` clean. Both gate pattern classes (the retail-title list and the lineage list, lines 31/38 of the gate) grep-clean against all rework files incl. new height-map comments. |
| **Gate: width-check** | ✓ | `clean (177 files)`. |
| **Gate: zp-check** | ✓ | `0 finding(s) across 218 file(s)`. |
| **Gate: cleanroom_check** | ✓ | `cleanroom: clean` (also re-confirmed clean WITH this report present in the tree). |

---

## 1. Suite output (fresh materialization, run 4×)

```
$ bash tools/dryrun_split.sh /tmp/audit_ls_kit
scrub_split: OK — 71 substitutions across 18 files; comment lineage guard clean
done — self-contained tree at: /tmp/audit_ls_kit

$ make width-check ; make zp-check ; bash tools/cleanroom_check.sh
width-check: clean (177 files)
zp_lint: 0 finding(s) across 218 file(s); symbol table has 167 DP symbols covering 208 bytes
cleanroom: clean

$ PYTHONPATH=. python3 -m pytest tests/test_split_v_demo.py -v   (RUN 1)
tests/test_split_v_demo.py::test_d1_two_camera_split_clean_seam PASSED   [ 16%]
tests/test_split_v_demo.py::test_d2_cameras_scroll_independently PASSED  [ 33%]
tests/test_split_v_demo.py::test_d3_swept_seam_moves_boundary PASSED     [ 50%]
tests/test_split_v_demo.py::test_d4_obj_window_clips_marker_at_seam PASSED [ 66%]
tests/test_split_v_demo.py::test_d4_default_marker_not_clipped PASSED    [ 83%]
tests/test_split_v_demo.py::test_d5_no_window_collapses_to_single_camera PASSED [100%]
======================= 6 passed, 11 warnings in 10.01s ========================

RUN 2: 6 passed, 11 warnings in 9.85s
RUN 3: 6 passed, 11 warnings in 9.85s
RUN 4: 6 passed, 11 warnings in 9.86s
```

**Flakiness: none observed.** 4/4 clean runs (each a separate process = a distinct
`RamState::Random` mt19937 seed). The horizon read, despite being denser/more sensitive
than the old colour-block read, has a wide margin to every threshold (see §4) so seed
variation does not approach a boundary. (One non-blocking `Pillow getdata` DeprecationWarning
×11 — cosmetic, see Friction.)

---

## 2. Visual re-render (frame ~23, after settle)

Captured to `/tmp/e2e_screenshots/audit2_{default,nowin,objclip}.png`.

- **default** — TWO viewpoints of one landscape with a vertical seam at centre. Left half
  frames a hill+mountain rising toward centre; right half (camera B, scroll 192) frames a
  DIFFERENT mountain falling away to rolling hills. The two silhouettes meet at a sharp,
  discontinuous step at the centre seam (the visible two-region signature). Two white OBJ
  markers sit at the seam (P1 straddling, P2 just right). Sky solid light-blue, dirt base
  solid brown — no garbage pixels, no cross-bleed across the seam.
- **nowin** — ONE continuous landscape: a single grey mountain on the left, an unbroken run
  of green hills across the rest, no centre discontinuity, no seam. This is exactly the D1
  signature being ABSENT (camera A full-screen).
- **objclip** — same dual-view as default, but only the LEFT marker pixel remains; the
  across-seam portion of the straddling marker AND the right-half P2 marker are clipped away
  (OBJ confined to the left half). The seam silhouette step is unchanged.

The three renders read unmistakably by eye as: two-cams-with-seam / one-cam / two-cams-with-
clipped-marker. The owner's "validate by eye" objection is resolved.

---

## 3. Adversarial findings

### Are the horizon tests vacuous / self-fulfilling?  **NO.**

Measured the actual signal margins on the live ROMs rather than trusting the assertions:

- **D1 left==camA, right!=camA:** left match = **116/116 (100%)** against the independent
  `-DNO_WINDOW` reference render (not a designed constant — it's a *separately compiled* pure
  camera-A ROM). Zero columns bleed. Right diverges 68/116. A broken ROM that bled camera B
  into the left half, or rendered camera A on both halves, would drop the left-match below the
  0.95 gate or the right-diff below 0.4. The check is discriminating in BOTH directions.
- **D1 seam step:** default disc@128 = **72**; the threshold is >20, so the test is not
  riding a marginal value. Achieved because `CAM_B0=192` deliberately lands a sharp mountain
  step at the seam (`main.asm:62`).
- **D5 fails the D1 signature:** nowin disc@128 = **0** vs threshold <6. The gap between the
  two regimes (72 vs 0) is enormous — D5 genuinely fails what D1 requires, on a ROM that is
  the *same source* compiled with the window compiled out. This is a real non-vacuity control.

### D3 — real boundary-move proof?  **YES.**

`test_d3` does not pass on a static seam: it asserts `seam_r > seam0` (the WH0 shadow
actually moved right) **AND** the fixed band at x∈[140,166] flips from camera-B (`in_a<0.3`)
to camera-A (`in_a>0.8`) as the seam sweeps past it, then asserts `seam_l < seam_r` and the
band flips back. A ROM where the shadow moved but the render didn't track (or vice-versa)
fails one of the coupled asserts. Not vacuous.

### D4 — non-vacuous clip?  **YES.**

`test_d4_obj_window` asserts `left` (white pixels left of seam) is **non-empty** before
asserting `across` is empty — so it cannot pass by the marker simply being absent. Measured:
objclip white cols = `120-127` (present, left), `>=128` = `[]` (clipped). The companion
`test_d4_default_marker_not_clipped` proves the same straddling marker DOES render across in
the no-clip ROM (`128-135,152-159` present), so the clip is demonstrably real, not a
mis-positioned sprite. Clip boundary is exact (last white 127, seam 128).

### "Settle frames" — masking instability?  **NO — verified.**

Grabbed the default ROM TWICE with no input, `SETTLE` frames apart: **0 columns** of horizon
differ. The rendered camera is bit-stable frame-to-frame once settled. The settle-frame
reasoning in the test docstring is sound: a screenshot on the same tick as an input change
can capture the BG scroll one commit before the NMI flushes it — a capture-timing artifact of
reading mid-pipeline, NOT a per-frame render instability. The 0-delta resettle proves there is
no underlying oscillation being hidden.

### Width discipline on the new tilemap-fill loop.  **CORRECT** (verified at encoded bytes).

Inspected the ca65 listing (`-l`). Every branch target and width-sensitive op encodes for its
runtime width:

- `cmp f:hmap, x` → `DF rr rr rr` — the **long abs-indexed** form (opcode $DF), 1-byte compare
  in A8. The long `f:` read is correct; X is i16 and bounded 0..31 over a 32-byte table (no
  overrun). No A8 leak.
- `and #$00FF` → `29 FF 00` (3-byte, A16 immediate). This is the exact bug class from the
  Mode-1 streaming regression (an `and #$00FF` assembling 1-byte A8). Here it assembles
  correctly as A16 because `@settile` does `rep #$30` + `.a16` **before** the `and`. Verified.
- `cmp #GND_DIRT` → `C9 18` (1-byte, A8); `cpx #6`/`cpx #13` → `E0 06 00`/`E0 0D 00` (2-byte,
  i16). A/I widths match the operands.
- Branch targets `@grass`,`@dirt`,`@sky`,`@settile` all carry explicit `.a8`; `@row`/`@col`
  carry `.a16/.i16`. `make width-check` clean. The `; WIDTH-RISK:` contract at `main.asm:129`
  accurately describes "toggles A8 for the byte compares then restores A16 before mset" — and
  the restore (`rep #$30` at `@settile`) is present before `mset`. Contract is honest.
- **Silhouette correctness (off-by-one check):** `cmp hmap,x; bcc @sky` ⇒ ground-top row =
  `hmap[col]` (rows `< hmap` are sky). `cmp #24; bcs @dirt` ⇒ rows ≥24 dirt. Mountain
  `cpx #6; bcc @grass` / `cpx #13; bcs @grass` ⇒ cols 6..12 inclusive. Matches the rendered
  silhouette exactly; no garbage columns. The fill `mset`s run AFTER `gfxmode` (`main.asm:124`
  then 131+), so they are not wiped by gfxmode's tilemap-zero.

### Power-on fidelity.  **CLEAN.**

- 5 distinct power-on seeds (5 fresh `load_rom` cycles) render **byte-identical horizons
  (0-col delta, disc=72 each)**. No read-before-write of random RAM affects the visible output.
- BG3 is enabled on the main screen (engine TM=$17 = OBJ+BG1+BG2+BG3) but **fully occluded**:
  the fill loop writes an OPAQUE solid tile (index 1..4, never tile 0) to EVERY cell of both
  BG1 and BG2, so there is no colour-0 gap for BG3 (uninit tilemap) to show through. Confirmed
  by the renders (clean solid sky/terrain, no stray pixels). VRAM/CGRAM/OAM are written under
  forced blank before `gfxmode` turns the screen on; OAM is `spr_clear`ed before NMI enable.
  No read-before-write observed.

### Clean-room grep.  **CLEAN.**

Both gate pattern classes (the retail-title list and the lineage list, `cleanroom_check.sh`
lines 31/38) grep-clean across `templates/split_v_demo/`, `tests/test_split_v_demo.py`, and
`docs/roadmap.md`, including all the new landscape/height-map comments. Full-tree
`cleanroom_check.sh` clean, and re-confirmed clean with THIS report present in the tree (the
report refers to the forbidden tokens only by description, never verbatim).

---

## 4. Findings — severity / disposition

| # | Sev | Finding | Disposition |
|---|---|---|---|
| F1 | LOW | (carried from audit-1) the `sf_split_v` macro signature differs from the spec §9 *intent* sketch (`sf_split_v cameraA, cameraB, seam_x` vs the implemented `sf_split_v seam, obj_clip`, caller owning the two camera scrolls). The spec text labels its API line "(intent)". Primitive is unchanged by this rework. | **Accept.** Documented in the macro header; the caller-owns-cameras split is the cleaner factoring and was already accepted at audit-1. |
| F2 | LOW | Doc nit: the `main.asm` header comment (`main.asm:11-17`) describes the stage as "grey mountain and a brown dirt base" while the height map actually renders TWO mountain shoulders meeting at the seam in the default view (camera B reveals a second peak). Cosmetic — the description is not wrong, just understated. | **Accept / optional.** No functional impact. |

No HIGH or MEDIUM findings. No fixes required to ship.

---

## Friction (no `dx_paper_cuts.md` in the kit — noted here)

- `Image.getdata()` raises a Pillow DeprecationWarning ×11 per run (removal slated Pillow 14,
  2027). Cosmetic now; a one-line swap to `get_flattened_data()` in `_grab_image` would
  silence it. Non-blocking.
- The feature branch was already checked out in the primary worktree, so the standard
  fetch/checkout preamble reported "already used by worktree" in that tree; this audit ran
  from the agent's isolated worktree (re-checked-out at `0bb0210`). Made no commits.
