# Audit-1 — `sf_split_h` v1 (horizontal raster-band split primitive)

**Auditor:** independent audit-1 agent (did NOT build this work). Research-only; no code changes except this report.
**Branch:** `claude/sf-split-h-primitive-80m8sg` @ `f8fc4d46cf48b6166948858e140b5d3ba2f69129`
**Materialized kit:** `/tmp/kit_audit1` (via `asm_repo_staging/tools/dryrun_split.sh`; scrub OK, 71 substitutions, comment-lineage clean)
**Date:** 2026-07-01

## Verdict: **CLEAN (ship)**

All 8 DoD items verified ✓. All 7 tests pass on a fresh materialization; split_v regresses 6/6. All three non-vacuity controls actually FLIP their paired positive assertions (run directly, not trusted from comments). All tests read a true output region (framebuffer pixels or the hardware HDMA enable-mask the PPU consumes) — **zero proxy-variable assertions**. Gates clean (width/zp/cleanroom), no baseline changes. Archetype A and D proven on the rendered framebuffer with a clean single-scanline seam. Two LOW observations noted below (documentation nits, defer/accept) — none block ship.

---

## Per-DoD table

| # | DoD | Verdict | Evidence |
|---|-----|---------|----------|
| 1 | Primitive routes through the allocator (not hardcoded CH2/CH3); `hdma_bind_direct` derives channel from bitmask, programs $43x0/1/2-4, ORs bit into NMI_HDMA_ENABLE | ✓ | `engine/hdma_alloc.asm:139-199` (`hdma_bind_direct`); `sf_split_h.inc:105-139` (`sf_split_h_arm` calls `hdma_request` then `hdma_bind_direct`). **Runtime proof:** live ROM `HDMA_ALLOC_MASK ($01D0)=$7F`, `EFFECT_TBL[CH2..CH4]=[0x11 FX_BGM, 0x12 FX_TM, 0x13 FX_COL]` — three distinct effect tags = three distinct `hdma_request` allocations, NOT hardcoded. `NMI_HDMA_ENABLE ($0108)=$7C`. This is genuine, not cosmetic. |
| 2 | Archetype A on the framebuffer: top = genuine BG3 tile instrument band (word $4800/$5000, palette group 4 hi-byte $10, no Mode-7 overlap); bottom = Mode-7 floor; clean single-scanline seam | ✓ | Screenshot `/tmp/kit_audit1_shots/default.png`: top band = frame rule + amber gauge/bar tiles; bottom = receding textured Mode-7 floor. Top band amber (255,173,57) 1264px in CGRAM group 4; floor in group 0 (247,206,90 …). Seam: per-row scan shows instrument-region → floor transition within ≤1-2 scanlines (row 46 backdrop → row 47 textured floor, dom_frac 0.42), no multi-row smear. `main.asm:105-121, 202-209` sets BG3SC=$48 / BG34NBA=$05, palette bits in the word HIGH byte (`PAL_HI=$1000`). |
| 3 | Archetype D: colour/window band changes pixels without a mode change | ✓ | COLDATA band (`SF_SPLIT_COLDATA`, `main.asm:249`). Default floor sig `{(247,206,90),(90,99,107),(255,255,181),(57,66,74)}` vs `-DNO_COLORBAND` `{(214,173,57),(255,231,148),(57,66,74),(24,33,41)}` — genuinely different, same geometry. Screenshot `default.png` (tinted, brighter gold) vs `nocolor.png` (untinted, deeper gold). |
| 4 | Every done-condition reads the rendered framebuffer (no proxy engine/state variable) | ✓ | All 7 tests read framebuffer pixels or the hardware enable-mask. Per-test classification below — **no proxy assertion**. |
| 5 | Each visual claim has a `-D` control that FAILS its paired positive assertion (RUN, not trusted) | ✓ | Ran positive assertions against control ROMs: **D1/NO_SPLIT** amber=0 → `amber>200` FAILS (non-vacuous); **D3/FREEZE_BAR** low=696 high=696 → `high>low+100` FAILS (non-vacuous); **D4/NO_COLORBAND** floor sigs differ (non-vacuous reference). Default flips: D3 default low=624 high=768 (responds). |
| 6 | ValueLatch guard: matrix payloads carry the guard contract in macro+guide; no matrix demo ships v1; guard mechanism-correct per spec §2.1 | ✓ | `sf_split_h.inc:41-51, 79-85` (M7A-Y equates marked guard-required); `guide split_h.md:106-122`. Guard contract (code-side write-twice ONLY in VBlank/forced-blank; matrix-band HDMA ONLY in active display → structurally non-interleaving) is mechanism-correct vs spec §2.1. v1 ships no matrix demo (archetype C-horiz = backlog). See §"ValueLatch" below. |
| 7 | Clean-room: NO retail game titles anywhere in `asm_repo_staging/` split_h files or `engine/hdma_alloc.asm` | ✓ | `grep -niE` over all split_h kit files + parent engine file: zero retail titles (only false-positive substrings "contrast"/"contract"/"cross-stripe"). Mechanism-only prose throughout. cleanroom gate: clean. |
| 8 | Gates clean (width/zp/cleanroom) | ✓ | `width-check: clean (182 files)`; `zp_lint: 0 finding(s) across 223 file(s)`; `cleanroom: clean`. No baseline diff (`reports/width_lint_baseline.json` / `zp_lint_baseline.json` unchanged) — new engine code uses inline `; WIDTH-LINT: ok — …` overrides, no new grandfathered residuals. |

---

## Item 4 — per-test proxy-variable classification (highest-value check)

Every test reads a TRUE output region. Detail:

| Test | Output region read | Proxy? |
|------|--------------------|--------|
| `test_boots_and_split_channels_armed` | `SFDB` magic (boot), heartbeat $E010 (sequencing ONLY — docstring explicitly disclaims any visual claim on it), and **`NMI_HDMA_ENABLE $0108` == $7C** — the hardware register the NMI writes to $420C; the PPU consumes it. | **NO** — the enable-mask is a hardware-consumed region, not an engine bookkeeping proxy. Rule #4 explicitly permits "the WRAM HDMA table/enable-mask the PPU consumes." |
| `test_d1_top_band_is_instrument_tiles` | Screenshot pixels [6,34): ≥2 authored colours + amber_count>200 + structured (row dom_frac<0.85). | NO — pure framebuffer. |
| `test_d1_nosplit_control_has_no_tile_band` | Screenshot pixels [6,34): amber_count<50 on `-DNO_SPLIT`. | NO — framebuffer. |
| `test_d2_bottom_band_is_mode7_floor_clean_seam` | Screenshot pixels: floor band [120,140) ≥4 colours; seam window [SPLIT+8,SPLIT+20). | NO — framebuffer. |
| `test_d3_dynamic_bar_responds_to_input` | Screenshot amber pixels in bar row [16,24) at two input states. | NO — framebuffer (docstring notes it is a pixel read, "not a variable"). |
| `test_d3_freeze_control_bar_does_not_respond` | Same bar-row pixels on `-DFREEZE_BAR`. | NO — framebuffer. |
| `test_d4_coldata_band_tints_floor` | Floor-band [120,140) colour signature, default vs `-DNO_COLORBAND`. | NO — framebuffer. |

**Conclusion: the tests are trustworthy.** No assertion rests on an engine/state variable standing in for a visual output. The one WRAM read that isn't a pixel (the enable-mask) is the hardware register the PPU actually consumes each VBlank, and the test cross-validates it against the same $7C that the framebuffer archetype-A result depends on.

---

## Non-vacuity controls — RUN, observed pass/fail

Ran each control ROM against its **paired POSITIVE assertion** (not the test's negative assertion, and not the script comments):

- **D1 / `-DNO_SPLIT`**: positive `amber>200` → amber=**0** → assertion **FAILS** (GOOD, non-vacuous). Screenshot `nosplit.png`: no instrument band, one full-screen Mode-7 floor extending to the top. Enable mask drops to $64 (split channels gone).
- **D3 / `-DFREEZE_BAR`**: positive `high>low+100` → low=696, high=**696** → assertion **FAILS** (GOOD, non-vacuous). Bar fill pinned.
- **D4 / `-DNO_COLORBAND`**: floor signature genuinely differs from default (`{247,206,90,…}` vs `{214,173,57,…}`) → the D4 positive `with != without` is meaningful; the control is a valid reference. Enable mask $6c (COLDATA channel gone).

All three controls flip. None is vacuous.

---

## ValueLatch guard correctness (item 6)

Spec §2.1: the Mode-7 write-twice latch byte is **shared** across M7A–D (`$211B`–`$211E`), M7X (`$211F`), M7Y (`$2120`), M7HOFS (`$210D`) and M7VOFS (`$210E`) — and `$210D`/`$210E` ARE the BG1 offset registers (physically the same addresses; `$210D` `[[fallthrough]]`s into BG1 scroll in Mesen2). The macro header (`sf_split_h.inc:41-51`) and guide (`split_h.md:106-122`) list exactly this register set. The guard contract — every code-side write-twice to a shared-latch register happens ONLY in VBlank/forced-blank (shadow→NMI-commit), while the matrix-band HDMA fires ONLY during active display, so the two never interleave — is **mechanism-correct**: it is the only reliable way to keep an HDMA matrix write from landing between the two bytes of a code-side write-twice. v1 payloads (BGMODE/TM/TS/COLDATA/brightness/window) do not touch that latch, so they legitimately need no guard. v1 ships NO matrix-band demo (C-horiz = backlog); the equates are provided but marked. **Guard is correct as documented.**

Minor doc note (LOW, accept): the guide/macro list "M7HOFS ($210D)/M7VOFS ($210E)" but do not spell out that these are simultaneously the BG1 offset registers (BG1HOFS/BG1VOFS) — spec §2.1 calls that sharing out explicitly. A one-line "these are the same addresses as BG1HOFS/BG1VOFS" would make the hazard scope self-evident to a reader who only reads the kit. Not a correctness defect (the addresses listed are correct and complete); a clarity nicety for a future matrix-band author.

---

## `hdma_bind_direct` code review (spot-check of the load-bearing new routine)

- Channel-index finder (`@bd_find`, `hdma_alloc.asm:158-174`): walks candidate bit $04→$80 (CH2→CH7) in lock-step with base $20→$70; matches the input mask → Y = ch*$10; a malformed (non-single-bit-2..7) mask falls through `cmp #$0100 / bcc` to a no-op `rts`. Traced CH7 boundary ($80 matches at X=$70) and the malformed-mask exit ($100 > $FF → rts) — both correct. Width annotations (`.a16/.i16` at both branch targets `@bd_find`/`@bd_found`) present.
- Register programming (`:184-192`): $4300+ch*$10=$00 (A→B, absolute table, 1-byte→1-reg), $4301=BBAD, $4302/3/4 = table lo/hi/bank from API_BLOCK_BASE. Correct for direct 1-byte HDMA.
- NMI_HDMA_ENABLE OR (`:194-196`): additive, DB=$00 absolute (mirrored low WRAM). Matches the documented "engine NMI re-arms $420C from this mask" contract.
- WIDTH-RISK header present and accurate (entry/exit A16/I16, internal A8 toggle bracketed, no DB switch, DB=$00 required). `.export hdma_bind_direct` added (`:55`).

No defects found in the new routine.

---

## Deviations list

| # | Deviation | Severity | Recommendation |
|---|-----------|----------|----------------|
| 1 | Guide/macro list M7HOFS/M7VOFS in the shared-latch set but don't note they are the same addresses as BG1HOFS/BG1VOFS (spec §2.1 calls this out explicitly). | LOW | **accept / defer** — addresses listed are correct & complete; a one-line clarification would help a future matrix-band author but is not a correctness gap. Fold into the C-horiz backlog sprint. |
| 2 | The `test_boots_and_split_channels_armed` docstring asserts `enable == 0x7C` with a fixed channel expectation (CH2 BGMODE\|CH3 TM\|CH4 COLDATA\|CH5/CH6 matrix). This couples the test to the allocator's first-fit ordering. If a future engine change re-orders allocation, the mask value would shift and the test would need updating. | LOW | **accept** — the coupling is intentional (it's an allocator-routing sanity check) and the mask is cross-validated by the framebuffer archetype-A result. Not a bug; noted for future maintainers. |

No HIGH or MEDIUM deviations. No silent spec deviations found.

---

## Verbatim gate + test output

```
$ cd /tmp/kit_audit1 && make split_h_demo
… ca65 … templates/split_h_demo/main.asm -o build/split_h_demo.o  [cfg=infrastructure/rom_template/lorom_64k.cfg]
built build/split_h_demo.sfc (cfg=lorom_64k.cfg)

$ bash templates/split_h_demo/build_split_h_variants.sh
built build/split_h_demo_nosplit.sfc  (NO_SPLIT=1)
built build/split_h_demo_nocolor.sfc  (NO_COLORBAND=1)
built build/split_h_demo_freeze.sfc   (FREEZE_BAR=1)
built build/split_h_demo_autodemo.sfc (AUTODEMO=1)

$ python -m pytest tests/test_split_h_demo.py -q
.......                                                                  [100%]
7 passed in 11.08s

$ python -m pytest tests/test_split_v_demo.py -q      # regression
......                                                                   [100%]
6 passed in 9.95s

$ make width-check
width-check: clean (182 files)

$ make zp-check
zp_lint: 0 finding(s) across 223 file(s); symbol table has 167 DP symbols covering 208 bytes

$ bash tools/cleanroom_check.sh
cleanroom: clean (name tripwire only — NOT a completeness guarantee; …)
```

Runtime allocator-routing proof (live ROM, default build):
```
NMI_HDMA_ENABLE ($0108) = 0x7c   (bits 01111100 = CH2|CH3|CH4|CH5|CH6)
HDMA_ALLOC_MASK ($01D0) = 0x7f   (CH0|CH1 reserved + CH2..CH6)
EFFECT_TBL[CH2..CH7]    = [0x11 FX_BGM, 0x12 FX_TM, 0x13 FX_COL, 0x01, 0x01, 0x00]
```
(CH2/3/4 tagged with the three distinct split effect IDs → three separate `hdma_request` calls; CH5/6 = Mode-7 matrix; CH7 free.)

Screenshots: `/tmp/kit_audit1_shots/{default,nosplit,nocolor,freeze,autodemo}.png`.

## Paper cuts

No paper cuts this audit — clean run. Materialization (`dryrun_split.sh`), build, variants, tests, and gates all worked first-try in the isolated worktree.
