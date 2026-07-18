# sf_split_h C-horiz perspective — Phase L + Phase 1 — AUDIT-1

- Branch under audit: `claude/persp-campos` — HEAD `77813cf5` (verified).
- Increment: Phase L (drop frozen head + matrix/seam DATA test + gotchas) and
  Phase 1 (camera B independent WORLD POSITION via per-band origin splice).
- Method: fresh materialization, build all variants, run the demo suite + the
  29-test split-family regression, re-render the two-camera and control frames and
  READ PIXELS, independently dump the active-buffer M7A, read the guard from code.
- Verdict: **CLEAN (ship).** No blocking or non-blocking findings. All 8 DoD ✓.

---

## 1. Re-run from a fresh materialization (verbatim)

Materialize:

```
$ bash asm_repo_staging/tools/dryrun_split.sh /tmp/kit_audit
scrub_split: OK — 71 substitutions across 18 files; comment lineage guard clean
done — self-contained tree at: /tmp/kit_audit
```

Build the demo + variants:

```
$ cd /tmp/kit_audit && make build/split_h_persp_demo.sfc
built build/split_h_persp_demo.sfc (cfg=lorom_64k.cfg)   [EXIT 0]

$ bash templates/split_h_persp_demo/build_split_h_persp_variants.sh
built build/split_h_persp_demo_noseam.sfc  (NO_SEAM=1)
built build/split_h_persp_demo_stillnoseam.sfc  (FREEZE=1 HOLD_B=1 NO_SEAM=1)
built build/split_h_persp_demo_latch.sfc  (LATCH_VIOLATION=1)
built build/split_h_persp_demo_holdb.sfc  (HOLD_B=1)
built build/split_h_persp_demo_freeze.sfc  (FREEZE=1)
built build/split_h_persp_demo_still.sfc  (FREEZE=1 HOLD_B=1)
built build/split_h_persp_demo_stillfixed.sfc  (FREEZE=1 HOLD_B=1 FIXED_BUFFER_SPLICE=1)
built build/split_h_persp_demo_stillsame.sfc  (FREEZE=1 HOLD_B=1 SAME_CENTER=1)   [EXIT 0]
```

Demo suite (expect 16):

```
$ python -m pytest tests/test_split_h_persp_demo.py -q
................                                                         [100%]
16 passed in 19.01s
```

29-test regression (split_h_demo 12 + split_h_matrix 5 + split_v_demo 8 + split_v_fight 4):

```
$ python -m pytest tests/test_split_h_demo.py tests/test_split_h_matrix_demo.py \
      tests/test_split_v_demo.py tests/test_split_v_fight.py -q
.............................                                            [100%]
29 passed in 45.20s
```

## 2. Re-render two-camera-different-position + SAME_CENTER control (pixels)

Shots saved to `/tmp/persp_campos_audit_shots/` (`still_campos.png`,
`stillsame_control.png`). Mean RED channel per band (position-only signal; the
green+blue checker is identical between the two stripes):

```
STILL   top_red=0.0   bot_red=168.5   diff=168.5     # camera A cool / camera B warm(red)
SAME    top_red=0.0   bot_red=0.0     diff=0.0       # control: band-2 folded onto camera A
```

STILL: top band (camera A) shows the cool cyan/white world region (red≈0); bottom
band (camera B) shows the warm red-tinted region (red≈168) — a genuinely DIFFERENT
world position, not a rescale. SAME_CENTER control: band-2's red collapses to 0 —
band-2 now samples camera A's world region (only scale still differs, visible in
the render as a larger checker). The control flips as designed → C1 measures WORLD
POSITION, not the mere presence of the splice channels.

## 3. Independent active-buffer M7A dump (Phase-L) + guard reasoning

Read straight from the ACTIVE double-buffer (pv_buffer `$01C6` → `$A000`/`$A900`),
`still` build, after 20 frames:

```
PV_BUFFER=1  base=$A900
m7a idx0..9: [320, 316, 312, 312, 308, 304, 300, 300, 296, 292]
camera-A max positive jump within idx 0..111: 0
camera-A interior positive jumps >= 20: []   (none)
seam jump m7a[112]-m7a[111] = 264 - 148 = 116   (>= 20)
idx0..7 constant-320? False   (RAMPS — no frozen head)
```

- idx 0..7 RAMP (not the constant 320 that the old frozen above-horizon head
  produced) → PV_L0=0 removed the frozen head.
- camera-A interior (idx 0..111) monotonic non-increasing, zero positive jumps →
  the perspective ramp is intact and the seam did not leak up.
- exactly one large positive discontinuity at idx==112 (+116) → the seam sits at
  screen scanline 112. Framebuffer (still_campos.png) confirms the floor recedes
  cleanly to row 0 with no flat top strip.

**ValueLatch guard (item 3) — reasoning from the code:** the shared Mode-7 /
BG1-scroll write-twice latches (M7A-D `$211B-$211E`, M7X/M7Y `$211F/$2120`, and
M7HOFS/M7VOFS `$210D/$210E` which alias BG1HOFS/VOFS) are written by CODE ONLY in
VBlank / forced blank: the engine NMI commit (`mode7_nmi.inc` writes M7SEL/M7X/M7Y
write-twice pairs in VBlank; `nmi_handler.asm` commits BG1HOFS/VOFS `$210D/$210E`
from the shadows in VBlank), and boot-time forced-blank setup. `pv_set_origin`
writes only WRAM shadows (`SHADOW_BG1HOFS/VOFS`, nmi_m7x/m7y), not the registers.
The demo's `center_update`/`center_setup` write only the WRAM HDMA tables
(`$7EDC00`+), never PPU registers. During active display ONLY HDMA touches these
regs — CH5/CH6 (matrix) + the new CH2 (M7X/M7Y, BBAD `$1F`, DMAP `$03`) + CH3
(M7HOFS/VOFS, BBAD `$0D`, DMAP `$03`) — and each channel transfers its complete
write-twice unit atomically within one HBlank, so no shared latch is left half-
written across channels. The only code-side active-display write-twice is the
`-DLATCH_VIOLATION` negative control, whose P5 test confirms such a write tears the
floor — proving the guard is load-bearing, not decorative. Guard holds by
construction. ✓

Mechanism sanity check (item 2): CH2 → M7X/M7Y, CH3 → M7HOFS/M7VOFS, both DMAP
`$03`, NON-REPEAT (count bytes SEAM=`$70`, 1, `$00` terminator, bit7=0), band-1
slots re-stamped every frame from live `M7_PV_NMI_M7X/Y` + `SHADOW_BG1HOFS/VOFS`
in `center_update`, matrix splice still targets the ACTIVE buffer via
`mode7_band_splice` (`pv_buffer_x`). The "centre-alone insufficient / full origin
required" claim is mathematically sound — the projection re-adds the centre
(`… + CX`), so a centre-only shift nets `(1−M7A)·Δ` ≈ 0 in the near band, while
moving centre AND scroll together pans rigidly by +Δ — and is empirically
confirmed by the STILL (168.5) vs SAME_CENTER (0.0) red result above. ✓

## 4. Per-DoD result

| # | DoD | Result | Evidence |
|---|-----|--------|----------|
| 1 | PV_L0=0 removes frozen head, seam still at 112 | ✓ | active-buffer M7A ramps idx0..7 (not const 320); seam jump +116 at idx==112; framebuffer has no flat top strip |
| 2 | Origin-splice correct + M7X-alone-insufficient claim real | ✓ | CH2 M7X/M7Y `$1F` DMAP `$03`, CH3 M7HOFS/VOFS `$0D` DMAP `$03`, NON-REPEAT, band-1 re-stamped, matrix splice active-buffer; math + framebuffer confirm |
| 3 | ValueLatch guard holds (capability-critical) | ✓ | code writes shared-latch regs only in VBlank/forced blank; HDMA per-channel atomic; P5 latch control tears (load-bearing) |
| 4 | Band-2 genuinely different WORLD POSITION (capability-critical) | ✓ | re-render: bot_red 168.5 vs top_red 0.0 (diff 168.5); SAME_CENTER control collapses to 0.0/0.0; red is a true position signal read from pixels |
| 5 | C2 clean seam, C3 temporal stability (no flicker) | ✓ | 16/16 incl. C2 crisp red step + C3 red-signature stable across 12 buffer-flipping frames |
| 6 | Budget — +2 channels cheap, 60 fps holds | ✓ | structural test heartbeat ≥110/120 under full load (rebuild + matrix splice + origin splice); NON-REPEAT = 2 HBlank xfers/ch/frame + ~16-store re-stamp, no extra solve |
| 7 | No regression; structural `$6C` correct | ✓ | 29/29 regression green; NMI_HDMA_ENABLE reads `$6C` = CH5\|CH6\|CH2\|CH3 |
| 8 | Clean-room + gates clean WITH report | ✓ | width/zp/cleanroom clean (below); no retail names / no forbidden vendor token in guide, roadmap, or this report |

Non-vacuity controls exercised and confirmed flipping: `-DNO_SEAM` (P4),
`-DLATCH_VIOLATION` (P5), `-DFIXED_BUFFER_SPLICE` (P3), `-DSAME_CENTER` (C1) — each
makes the corresponding positive assertion fail, so none of the passing tests are
vacuous.

Deviations: none. No fix / accept / defer items.

## 5. Gates (verbatim, cleanroom re-run WITH this report present)

```
$ make width-check
width-check: clean (186 files)

$ make zp-check
zp_lint: 0 finding(s) across 227 file(s); symbol table has 167 DP symbols covering 208 bytes

$ bash tools/cleanroom_check.sh          # re-run below AFTER this report was added
cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)
```
