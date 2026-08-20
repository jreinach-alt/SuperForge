# 94 — Region support: the specification

> Status: SPEC — the requirement, not the design. **No implementation exists
> and none is authorised by this file.** The design investigation dispatched
> against it answers §5 and lands its findings as its own doc; this file is
> then amended, not replaced.

## 0. Why this exists

`docs/93` measured what the kit does at 50 Hz and found nothing broken. That
finding is correct and it is not the whole question. A ROM that boots on PAL,
runs 17% slow and draws 224 lines into a 239-line frame is the **standard lazy
conversion of the 16-bit era** — the practice European players spent a
generation complaining about. It clears "it runs". It does not clear "it
works".

This kit's stated proposition is a macro library that *bakes the hardware
landmines in*. PAL conversion is among the most famous landmines on this
console. Shipping the era's bad answer to it contradicts the pitch.

The SNES DEV Game Jam 2026 rule is `Game works on NTSC and PAL`, and the 2025
edition was scored by judges evaluating **proper hardware utilisation**. That
is the criterion this spec is written against.

## 1. What is true today — measured, with sources

| fact | source |
|---|---|
| All 37 rails boot, run and render under PAL; nothing crashes or corrupts | `docs/93` |
| Every rail runs at **83.2%** of NTSC speed under PAL | `docs/93` |
| A PAL frame carries **+19.1% master cycles**; VBlank swallows **≥8,192 B** vs the pinned NTSC **5,952 B** | `docs/93` |
| Active display is **224 lines in both regions** — PAL's extra 50 scanlines are entirely VBlank | Mesen2 `SnesPpu.cpp`: `_vblankStartScanline = OverscanMode ? 240 : 225` is not region-conditional; `_baseVblankEndScanline` 262 NTSC / 312 PAL |
| **Overscan is never enabled.** `stz $2133` zeroes SETINI at reset, so the PPU draws 224 lines — on PAL, into a taller frame | `vendor/rom/ppu_reset.inc:123` |
| **Region is never detected.** `$213F` is read at three sites, all to reset the OPHCT/OPVCT flip-flops; bit 4 is never tested | `sit_cam.asm:409,430`, `shg_cam.asm:475,496`, `m7f_cam.asm:230` |
| The header destination byte is a hardcoded `.byte $01` (North America) with no override | `vendor/rom/header.inc:41` |
| **20 of 37 rails declare `$05` (32 KB)** in the ROM-size byte while shipping 524,288 B | `docs/93`; independently confirmed on `boss_saucer`, `split_v_fight`, `split_v_seamtrial` |
| The APU keeps real time, so music plays at NTSC tempo while the game runs at 5/6 | `docs/93` |

## 2. The requirement

**A player on PAL hardware sees the game the NTSC player sees, at the speed its
designer intended, filling the screen.**

That is the standard deliberately, and it is higher than the jam's literal
wording. "Boots on both" is already true and is not what this spec asks for.

## 3. Tiers, and what each must prove

Each tier is independently shippable and strictly ordered — R1 and R2 both
depend on R0. A tier is done when its criterion is discharged by a test that
reads rendered output, per CLAUDE.md rule 2.

**R0 — the region is known.**
- Boot reads `$213F` bit 4 and stores a region flag readable by game code.
- The flag is correct under `SF_REGION=ntsc` and `SF_REGION=pal`.
- The header destination byte is derivable rather than hardcoded, and a build
  declares the region it targets.
- The ROM-size byte tells the truth on all 37 rails. *(A declaration-lies
  defect found by `docs/93`; it belongs here because it is the same class and
  the same file.)*

**R1 — the screen is filled.**
- On PAL the PPU renders the taller active area; a PAL frame shows no
  top/bottom border that an NTSC frame does not.
- Every per-scanline structure — HDMA tables, IRQ line numbers, Mode 7
  per-line machinery, the split/seam rails — covers the taller area, proven
  per rail rather than assumed.
- On NTSC nothing changes at all (see §4).

**R2 — the speed is preserved.**
- Game-visible rate on PAL is within a stated tolerance of NTSC over a
  measured interval, on at least one rail of each motion class (scrolling,
  Mode 7, sprite animation, physics).
- The tolerance is the investigation's to propose with evidence; this spec
  does not invent one.

**R3 — audio tracks the game.** Scope and feasibility are §5 questions; no
criterion is asserted here.

## 4. Constraints — what must not break

1. **NTSC output is byte-identical.** Every rail's `.sfc` and every rendered
   frame under `SF_REGION=ntsc` must be unchanged by R0 and R1. This is the
   safety property that makes the work reversible and reviewable; a change
   that moves the NTSC picture is out of spec regardless of its merit.
2. `microzero.sfc` holds its pinned md5 `e45ddeabac4218cd71709da7b9fcc849`.
3. All 37 rails keep building. `make bare-check` stays GREEN.
4. Every gate stays clean: `width-check`, `time-check`, `toy-bad`,
   `rom-unbacked`, `measure`, `register`, `rail-registered`, `cleanroom`.
5. The allocator remains the authority. No raw address literals; anything new
   that occupies a resource is **declared**, not allocated by hand.
6. The 512 KB cap and the no-SRAM rule hold for anything this work adds.

## 5. The open questions — the investigation's actual job

Answer each with measurement, not argument. Where an answer cannot be reached
from the emulator, say so and name what would settle it.

1. **How is a PAL border observed at all?** `docs/93` reports Mesen returns
   256×239 for both regions, so frame dimensions do not reveal letterboxing.
   Establish the instrument before trusting any R1 result. If the border is
   not observable in this harness, that is a finding and R1's criterion must
   be restated against something that is.
2. **What does enabling overscan cost, per rail?** Enumerate every
   scanline-sized structure in the tree and how each is sized. Which are
   constants, which are generated, which are derived?
3. **Can scanline coverage become a declared claim?** This kit's thesis is
   that composition is proven at build time. If a feature declared the lines
   it covers, region support could be an allocator property rather than 37
   hand-audits. Evaluate this seriously — including the answer "no, and here
   is why".
4. **Is 6-logic-ticks-per-5-frames viable?** PAL hands back +19.1% cycles and
   the scheme needs +20% logic work — near enough that the budget is not
   obviously the obstacle. Test that rather than assume it, on the *tightest*
   rail, not an easy one.
5. **What assumes one tick equals one frame?** Enumerate: animation counters,
   fade ramps, countdowns, lunge and scale tracks, streaming quotas, IRQ
   phase. This list is the real cost of R2 and it is currently unknown.
6. **What does the audio driver do at 50 Hz**, and what would tracking cost?
7. **Given the 2026-10-31 deadline, what is the recommended stopping point?**
   Recommend against the §2 requirement, and say plainly if you believe §2 is
   wrong.

## 6. Non-goals

Interlace; hi-res modes; 512-line output; PAL-specific art or layout;
region-locked builds; supporting any region other than NTSC and PAL; changing
the jam submission itself.

## 7. Evidence standard

Measured on the emulator, both regions, same ROM, same drive. Rendered output,
never a proxy variable. A claim about what a tool does is checked by reading
the tool. Anything needing real hardware or a second emulator is named as
such and not asserted.
