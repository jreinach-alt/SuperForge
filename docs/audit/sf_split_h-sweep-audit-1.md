# sf_split_h sweep + C-horiz matrix band — AUDIT-1 (independent verification)

- **Audit type:** AUDIT-1 (independent; the auditor built none of this)
- **Branch under test:** `claude/sf-split-h-primitive-80m8sg`
- **HEAD verified:** `20c2533600a6b4e7755bc09dec584f6bde769913` ("sf_split_h C-horiz (flat): stacked Mode-7 camera bands SHIPPED")
- **Scope:** the two merged builds — (A) the low-risk sweep (commit `e918fa4`, items #1/#3/#4/#5/#6/#7) and (B) the matrix band / C-horiz (commit `20c2533`).
- **Method:** fresh materialization → build both rails + all `-D` variants → full pytest → gates → self-rendered framebuffer reads → source review of the load-bearing routines → forced-collision test of the compile-time guard.

## VERDICT: CLEAN (ship)

All 10 DoD items pass. 23/23 tests pass. width/zp/cleanroom gates clean (cleanroom re-run WITH this report present). Every new test reads rendered framebuffer pixels or the hardware `$43xx`/`$2100`-region registers the PPU consumes — no proxy-variable assertions. The subtlest risk (the VMADD-holds-under-rotation invariant, DoD #3) is sound; reasoning below.

Only two LOW notes (both accept, no action required): a roadmap prose count ("matrix (4)" vs 5 test functions incl. `test_boots`), and the standing structural-only cost proxy for #7 (already documented as deferred backlog with a sound rationale).

---

## 1. Re-run from a fresh materialization (verbatim)

Materialize:

```
scrub_split: OK — 71 substitutions across 18 files; comment lineage guard clean
done — self-contained tree at: /tmp/kit_sweepaudit
```

Build both rails:

```
built build/split_h_demo.sfc (cfg=lorom_64k.cfg)
built build/split_h_matrix_demo.sfc (cfg=lorom_64k.cfg)
```

Build both variant scripts:

```
built build/split_h_demo_nosplit.sfc  (NO_SPLIT=1)
built build/split_h_demo_nocolor.sfc  (NO_COLORBAND=1)
built build/split_h_demo_freeze.sfc  (FREEZE_BAR=1)
built build/split_h_demo_autodemo.sfc  (AUTODEMO=1)
built build/split_h_demo_threeband.sfc  (THREEBAND=1)
built build/split_h_demo_bright.sfc  (BRIGHT_BAND=1)
built build/split_h_demo_toggle.sfc  (TOGGLE_SPLIT=1)
built build/split_h_matrix_demo_nomatrix.sfc  (NO_MATRIX_SPLIT=1)
built build/split_h_matrix_demo_autodemo.sfc  (AUTODEMO=1)
```

Full test suite:

```
$ python -m pytest tests/test_split_h_demo.py tests/test_split_h_matrix_demo.py tests/test_split_v_demo.py -q
.......................                                                  [100%]
23 passed in 33.50s
```

23 pass, exactly as the DoD predicts (12 sweep + 5 matrix + 6 split_v regression).

## 2. Self-rendered framebuffer reads (from the tracked source)

Rendered from the freshly-built binaries; pixels read by the auditor (shots in `/tmp/kit_sweepaudit_shots/`):

| phase | measurement | verdict |
|-------|-------------|---------|
| A cockpit (arch-A) | top-band amber(6..34) = **1264 px**; floor luma(120..140) = **156** | tile HUD + textured floor both present |
| 3-band (`-DTHREEBAND`) | luma top=**81** mid=**62** bot=**37** | strictly descending stair — a genuine third region |
| brightness (`-DBRIGHT_BAND`) | bright floor=**79** vs default floor=**156** | dims (79 < 156−15) |
| toggle (`-DTOGGLE_SPLIT`) | armed=**1264** → off=**0** → rearm=**1264** | full off/re-arm lifecycle flips |
| matrix two-camera | top runs = **[8,8,8]**, bottom = **[32,32,32]** | 4× period ratio the scale predicts |
| matrix control (`-DNO_MATRIX_SPLIT`) | top-max=**8**, bot-max=**8** | single camera (both small) |
| nosplit control (`-DNO_SPLIT`) | top amber=**0** | HUD signature absent |
| matrix autodemo | G_PHASE 36→66; bottom-band M7A byte 100→66 | live band patched in-VBlank |

## 3. Per-DoD table

| # | DoD item | verdict | evidence |
|---|----------|---------|----------|
| 1 | `hdma_bind_direct` backward-compat + DMAP-mode plumbing | ✓ | `engine/hdma_alloc.asm:193` reads `API_BLOCK_BASE+3`. All THREE (and only three) call sites set +3 first: `sf_split_h.inc:124` writes `$00` unconditionally in `sf_split_h_arm`; `:346` and `:368` write `$03` in `sf_split_h_matrix_band`. No stale-scratch leak: any later 1-byte arm re-writes `$00`. Structural test asserts `DMAP=$00` on CH2/3/4 (below). |
| 2 | N-band compiler correctness; 2band wrapper preserved; 3-band renders 3 regions | ✓ | `sf_split_h_bands` emits `.byte sf_pairs, $00` (`:205`); `sf_split_h_2band` is now `sf_split_h_bands …, {split,top,$01,bot}` (`:170`) — identical `[split,top,1,bot,0]` table, signature unchanged; 3-band render = descending stair (81/62/37). |
| 3 | #3 DMA-queue bar write — VMADD holds to drain, incl. under rotation | ✓ | See "Item 3 reasoning" below. Load-bearing invariant confirmed by NMI trace. |
| 4 | CGRAM `.assert` present + fires; guide map correct | ✓ | `main.asm:165` `.assert FLOOR_CGRAM_END < BG3_CGRAM_BASE`. Forced `FLOOR_PAL_COUNT=20` → build FAILS with the exact message (`main.asm(165): Error: CGRAM overlap…`). Guide map (floor 0..5 / free 6..15 / HUD 16..19) matches `FLOOR_PAL_COUNT=6`, `DASH_PAL_COUNT=4`, `BG3_CGRAM_BASE=16`. |
| 5 | brightness band framebuffer-verified, control flips | ✓ | `-DBRIGHT_BAND` floor luma 79 vs default 156; test pairs against default (non-vacuous). |
| 6 | off/re-arm lifecycle framebuffer-verified, control flips | ✓ | armed 1264 → off 0 → rearm 1264 (my read + `test_off_and_rearm_lifecycle`). |
| 7 | #7 structural test reads real `$43xx`; claim sound | ✓/partial | `test_split_hdma_config_is_direct_1byte` reads `$4300+ch*$10` off the debugger bus (`BUS = SnesMemory`) for CH2/3/4 and asserts `DMAP=$00` + expected BBAD. Genuine hardware config, not a proxy. The "cost = re-arm + table, nothing hidden" claim is *structurally* proven (no indirect mode, no extra channel/register); a true cycle gate is correctly deferred as backlog. |
| 7-matrix | Matrix band (C-horiz): two distinct cameras, clean seam, shared VRAM, NON-REPEAT, bypass rule, guard-by-construction, control flips | ✓ | M1 asserts period-ratio (top≤12, bot≥24, bot≥2×top) not "both textured"; M2 exactly one clean S→L transition, no `?` rows; M3 reads checker map+CHR at VRAM word `$0000`. Tables use `.byte count` with bit7=0 (NON-REPEAT); demo never calls `sf_mode7_perspective`/`sf_mode7_tick` (bypass rule real); M7X/Y/M7SEL/offsets set once under forced blank (`main.asm:184-208`) → guard-by-construction correct. `-DNO_MATRIX_SPLIT` collapses to one camera (top/bot both period 8). |
| 8 | Every new test reads output region, no proxy | ✓ | See Item 8 table below. |
| 9 | Clean-room — no retail titles | ✓ | grep across the new template dirs + guide + `hdma_alloc.asm` + `sf_split_h.inc` returns only substring false positives (STRIPE/contrast/contract/"game DP"); `cleanroom_check.sh` name tripwire clean. |
| 10 | Gates clean | ✓ | width-check clean (183 files); zp_lint 0 findings; cleanroom clean (incl. this report). |

## Item 3 — the VMADD-holds-under-rotation invariant (explicit reasoning)

**The claim (`main.asm:685-687` / guide L98-102):** the dynamic bar row is built into WRAM `BAR_BUF`, the main loop sets `VMAIN`($2115)/`VMADD`($2116) then enqueues a CH0 GP-DMA of the 24 words; nothing between the main-loop VMADD set and the NMI drain touches `$2115`/`$2116`, so the latched VRAM address holds to the drain.

**Trace (per-frame ordering).** In `game_loop`: rotation update → `sf_mode7_cam`/`sf_mode7_tick` (`main.asm:400-401`) → toggle/bar-input logic → `draw_bar` + `bar_enqueue` (`:517-518`) → heartbeat WRAM write (`:521-523`) → `sf_frame_end` (`:525`). Critically, **`sf_mode7_tick` runs BEFORE `bar_enqueue`.** So whatever the matrix rebuild does, it happens strictly earlier than the VMADD set at `main.asm:703` — it cannot corrupt an address latched afterward. After `bar_enqueue` only a WRAM long-store (heartbeat) and `sf_frame_end` (`engine_spr_resolve` + `dma_queue_signal`) run; `sf_frame.inc:116-126` shows neither touches `$2115`/`$2116` (they build the OAM DMA-queue entry + set a flag).

**Inside the NMI (`nmi_handler.asm`).** Phase 1/2 touch no VRAM port. **Phase 3 GP-DMA drain is the first PPU-touching action** and it does NOT re-write `$2115`/`$2116` (`@dma_execute`, `:118-151` — only DMAP0/BBAD0/src/size/trigger), so the bar DMA fires against the main-loop-latched VMADD. The queue drains in **insertion order** (Y walks the entries; priority only gates budget-drops, `:98-116`), and `bar_enqueue` (`dma_queue_add`) was enqueued before the OAM entry from `sf_frame_end`, so the bar transfer runs first with the intended VMADD. The tilemap-DMA block (Phase 3B, `:184-296`) does re-set `$2115`/`$2116`, but (a) it runs AFTER the GP-DMA drain, and (b) this rail never sets `BG_TILEMAP_DIRTY` (BG3 is programmed manually), so 3B is skipped entirely. `mode7_nmi.inc` (Phase 4) writes only `$211A/$211F/$2120` (M7SEL/M7X/M7Y), never `$2116`.

**Under the D5 rotation path.** The full matrix rebuild `sf_mode7_tick` builds its tables in WRAM on the MAIN thread (before the VMADD set) and the per-scanline matrix is delivered by CH5/CH6 HDMA. The only Mode-7 code-side register writes in the NMI are the M7X/M7Y write-twice in Phase 4 — a different latch from the VRAM-address port (`$2116`), and after the bar DMA has already completed. **No path writes `$2116` between the main-loop set and the drain.** Invariant holds; the rotation stress does not threaten it. `test_d5_split_holds_under_rotation_load` independently confirms the rendered floor genuinely re-projects (>20% pixels change) while the seam stays un-smeared.

## Item 8 — proxy check (per new test)

Sweep additions (`test_split_h_demo.py`):

| test | reads | proxy? |
|------|-------|--------|
| `test_bands_three_distinct_regions` (#1) | framebuffer band mean-luma (3 windows) + built-in default-build non-vacuity | OUTPUT (pixels) |
| `test_bright_band_dims_floor_region` (#5) | framebuffer floor-band mean-luma, bright vs default | OUTPUT (pixels) |
| `test_off_and_rearm_lifecycle` (#6) | framebuffer top-band amber count at armed/off/rearm | OUTPUT (pixels) |
| `test_split_hdma_config_is_direct_1byte` (#7) | `$4300+ch*$10` DMAP+BBAD off the SNES bus + `NMI_HDMA_ENABLE` mask | OUTPUT (hardware DMA regs the PPU consumes) |

Matrix additions (`test_split_h_matrix_demo.py`):

| test | reads | proxy? |
|------|-------|--------|
| `test_boots` | boot magic `SFDB` | boot-proof only (no visual claim) |
| `test_m1_two_distinct_cameras` | framebuffer per-row longest-run period | OUTPUT (pixels) |
| `test_m1_nomatrix_control_single_camera` | framebuffer per-row period (control) | OUTPUT (pixels) |
| `test_m2_clean_single_scanline_seam` | framebuffer per-row period classify (S/L/?) | OUTPUT (pixels) |
| `test_m3_vram_single_shared_world` | VRAM word `$0000` tilemap+CHR bytes | OUTPUT (VRAM the PPU consumes) |

No test asserts on an engine proxy variable. The heartbeat mirror (`$7E:E010`) is used only for sequencing, and each control test that reads `SFDB` uses it as a boot-proof, not as the visual assertion.

## Non-vacuity controls — observed flips

Every paired control was run and observed to flip its assertion:

- **`-DNO_SPLIT`** → top-band amber = **0** (vs 1264 armed): D1 signature absent. ✓
- **`-DFREEZE_BAR`** → `test_d3_freeze_control_bar_does_not_respond` passes (bar does not respond). ✓
- **`-DNO_COLORBAND`** → floor signature differs from default (`test_d4`); default-build is the non-band reference. ✓
- **`-DTHREEBAND` non-vacuity** → default build does NOT show the descending mid>bot stair (built into `test_bands_three_distinct_regions`). ✓
- **`-DBRIGHT_BAND`** paired against default (79 vs 156). ✓
- **`-DTOGGLE_SPLIT`** → off phase amber = **0**, re-arm = **1264**. ✓
- **`-DNO_MATRIX_SPLIT`** → both bands period **8** (single camera); `test_m1_nomatrix_control_single_camera` passes. ✓

## 4. Deviations

| severity | item | note | disposition |
|----------|------|------|-------------|
| LOW | roadmap prose | roadmap says matrix "(4)" tests; the file has 5 functions (the 4 M-tests + `test_boots`). Actual passing total is 23 as the DoD states. | accept (prose count, not a defect) |
| LOW | #7 cost gate | the cost regression is a structural proxy only (no per-frame cycle read); a true cycle gate is deferred. | accept — already filed as backlog with a sound harness-limitation rationale |

No MEDIUM or HIGH findings. No functional deviation from the DoD.

## 5. Gate tails (verbatim; cleanroom re-run WITH this report present)

```
=== width-check ===
width-check: clean (183 files)

=== zp-check ===
zp_lint: 0 finding(s) across 224 file(s); symbol table has 167 DP symbols covering 208 bytes

=== cleanroom (materialization including this committed report) ===
cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)
```

(The cleanroom re-run WITH this report present is reproduced in the commit-verification section below — this report is written by mechanism only, with no retail names in its prose, so it does not trip the tripwire.)
