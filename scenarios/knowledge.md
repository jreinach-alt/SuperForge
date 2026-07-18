# scenarios/knowledge.md — the knowledge-realm catalog

The kit's agent answers questions about the **whole SNES**, not only what the
engine implements. This file is the acceptance bar for that realm: the
interrogation sets, the troubleshooting sets, and the anti-folklore trap bank.
An answer passes only if it is correct, sourced, **and tiered**.

**The confidence gradient (every claim is labeled):**

1. **engine-verified** — implemented here and measured on the emulator
   (cite the code / the measured number).
2. **hardware-reference** — known from the fetched references
   (`docs/reference/hardware/`), *not* tested here — say so.
3. **honest-unknown** — "I don't know yet; here's how I'd verify it."

Never dress reference-recall as tested experience. Reason from the hardware
*mechanism*, not community folklore.

---

## K-series — expert interrogation

| ID | The question | The correct answer rests on | Verify with |
|---|---|---|---|
| K1 | Tilemap at VRAM word $5800 — why write `$58`, not `$B0`? | BGnSC encodes word addresses: `(value & 0x7C) << 8` | `sf_bg.inc`; any scroller ROM's VRAM dump |
| K2 | 16×16 sprite tile layout in VRAM? | PPU reads `{N, N+1, N+16, N+17}` — row 2 is +16 tiles, hardware-fixed | `sf_meta.inc`; brawler OAM/VRAM dump |
| K3 | Hide a sprite off the left edge? | 9-bit X: low byte in the OAM low table, X9 in the hi-table (2 bits/sprite) | `sf_sprite.inc`/`sf_meta.inc` (X9 by construction) |
| K4 | More than 32 sprites on a scanline? | the PPU drops them (Range limit); flicker or design around it | a crowded-row demo + `$213E` |
| K5 | Multi-slot DMA only moves the first chunk — why? | DAS ($4305) is consumed per transfer — re-arm before every MDMAEN; mind bank boundaries | the engine's DMA dispatchers (re-arm pattern throughout) |
| K6 | Per-scanline parallax HOFS — how? | HDMA + the BGnHOFS write-twice latch; non-repeat entries hold a value across N lines | `docs/reference/hardware/README.md` routing |
| K7 | Long VRAM upload under forced-blank — safe? | No — INIDISP blanking does NOT mask NMI ($4200); mask NMI or upload in chunks | `sf_video.inc` (`sf_load_*` force-blank + mask by construction) |
| K8 | Random BRK crashes — why? | 65816 width tracking: a width-mismatched immediate executes a stray $00 as BRK | `tools/width_lint.py`; the `width-check` gate |
| K9 | Mode 7 perspective / matrix format? | 1.7.8 signed fixed-point M7A-D, per-scanline HDMA, sin + reciprocal LUTs | `sf_mode7.inc`; `docs/guides/mode7_sprite_projection.md` |
| K10 | Cycles per frame for game logic? | ~28k-37k CPU cycles at FastROM after engine overhead — measured, not estimated | measure on the emulator; never quote folklore |
| K11 | WRAM/ZP map — what's reserved vs free? | `engine_state.inc` + the kit's game-memory contract ($1800-$1DFF arrays) | `lib/macros/README.md` "Game memory contract" |
| K12 | How does audio work; what can I ship? | TAD driver (vendored, zlib) + a compiled song set; build your own set with tad-compiler; no commercial samples ever | `sf_audio.inc`; `NOTICE`; `tests/test_audio.py` |
| K13 | Real hardware? Other emulators? | honest: verified on Mesen2 (cycle-accurate); state what's NOT yet confirmed on bsnes / real hardware | the confidence gradient |
| K14 | Can I ship a commercial game with this? | zlib first-party code / CC0 docs + assets — yes, no obligations on ROMs (one exception: the dizworld Mode 7 perspective path is CC BY 4.0 — credit Brad Smith) | `LICENSE`, `NOTICE`, `JAM.md` |
| K15 | Why ca65? Why this vs PVSnesLib / libSFX? | honest positioning: macro-library-over-engine vs C-library vs bare-metal lib — strengths AND weaknesses | a straight comparison, no bluffing |

## KF-series — newcomer foundations

Same knowledge base, teaching altitude: the answer must build the *model*.

| ID | The question | Must teach |
|---|---|---|
| KF1 | How do BG layers relate; what goes where? | layers per mode; Mode 1 as the workhorse (BG1 playfield / BG2 secondary / BG3 HUD); priority vs sprites |
| KF2 | My real limits — VRAM, tiles, layers? | 64 KB VRAM shared by everything; bytes/tile by bit depth; 128 sprites, 32/scanline |
| KF3 | Standard collision approach? | tile flags (`col_map`) for terrain — the idiomatic approach; AABB (`col_box`) for actor-vs-actor |
| KF4 | Where does game state live; how do I structure the loop? | WRAM layout + the game-memory contract; the frame loop (`sf_frame_begin`/`end`) as the update pattern |
| KF5 | Walk me through NMI/VBlank — what breaks otherwise? | NMI fires at VBlank start; **per-memory write windows differ**: VRAM ≈ VBlank/forced-blank; CGRAM also HBlank (that's why raster palette HDMA works); OAM ≈ VBlank/forced-blank; WRAM is always writable; forced-blank does NOT mask NMI |
| KF6 | When DMA vs direct register writes? | direct = a few registers; DMA = bulk (OAM 544 B, CGRAM 512 B, tilemaps, CHR) within the VBlank budget |

## AX-series — expert proactive-landmine gauntlet

For expert "write me X" asks, the bar is not "produces working code" — it's
**surfacing the landmine the user didn't ask about**, with the macro/example
encoding it by construction.

| ID | The request | Must surface UNPROMPTED | Tier |
|---|---|---|---|
| AX1 | "VRAM upload routine." | VRAM write windows; VMAIN increment mode; DMA can't cross a bank boundary | engine-verified |
| AX2 | "Set up the SPC700, play a sample." | the full IPL boot handshake; BRR 9-byte blocks; echo buffer eating ARAM | hardware-reference (TAD abstracts it — say so) |
| AX3 | "MVN to copy between banks." | operand order vs byte order; A=count−1; MVP for overlap; the bank-byte pitfalls that make indexed loops safer here | engine-verified + caveat |
| AX4 | "Read controller 1 in my NMI." | wait for $4212 bit 0 to clear; don't mix auto-read and manual strobe | engine-verified |
| AX5 | "Do a 16÷8 divide." | $4204-$4206 + ~16-cycle wait before $4214; same shape for the multiplier | engine-verified |
| AX6 | "HDMA gradient sky." | HDMA and general DMA share the 8 channels — don't double-book | engine-verified (the allocator exists for this) |
| AX7 | "Why is my Mode 7 matrix garbage?" | $211B-$2120 are write-twice (low then high); M7A/M7B double as the multiplier | engine-verified |
| AX8 | "Reset vector → native mode." | boots in emulation mode; XCE; REP/SEP + assembler width annotations in sync | engine-verified (the width discipline) |

## T-series — troubleshooting (symptom → diagnosis)

Tooling-agnostic: MesenRunner reads any `.sfc`'s hardware state regardless of
who built it. Route through `docs/troubleshooting.md` FIRST (symptom-indexed).

| ID | Symptom | Diagnosis rests on |
|---|---|---|
| T1 | sprite on the wrong side / wrapped | OAM X9 bit |
| T2 | sprites flicker / vanish | 32-per-scanline Range limit |
| T3 | VRAM corrupts mid-frame | NMI during upload / DMA bank boundary |
| T4 | random crashes / BRK | width tracking |
| T5 | Mode 7 wrong / tearing | HDMA table build / M7 setup |
| T6 | no sound | TAD init / SPC state |
| T7 | "show me what the hardware is doing" | MesenRunner inspection (universal) |
| T8 | "I'm on a different toolchain — help?" | the universal-vs-engine boundary: always offer hardware diagnosis; be honest about not porting their build |
| T9 | colors are wrong | CGRAM / palette upload |

## TD-series — expert differential diagnosis

The expert brings a bug whose obvious explanation is usually wrong; the
deliverable is the **discriminating signal**, tiered.

| ID | Symptom | Differentiate among | The discriminator |
|---|---|---|---|
| TD1 | Mode 7 shears near the horizon | 1.7.8 precision loss · malformed HDMA table · write-twice latch timing · center interaction · $211A wrap | which scanline the latch commits; full-matrix vs A/B-only rebuild *(engine-verified)* |
| TD2 | APU voice clicks on loop | BRR loop-flag block · echo buffer (ESA/EDL) overwriting samples · IPL race | an ARAM layout map; BRR block flags *(hardware-reference)* |
| TD3 | streamed tiles corrupt | VMAIN increment vs last-written byte · DMA overrunning VBlank · forced-blank trade | VMAIN bit 7 vs $2118/$2119 order; bytes-per-VBlank budget *(engine-verified)* |
| TD4 | sprites vanish in crowded rows | 32/line Range vs 34-tile Time · X=$100 still counts (hardware bug) · opposite scan directions | $213E Range/Time-Over flags *(engine-verified + hw-ref)* |
| TD5 | raster split jitters ±1 line | DRAM refresh (~40 mc EVERY line) · IRQ timing · auto-joypad steal · HDMA pause · MEMSEL | reason in master cycles; name DRAM refresh *(hardware-reference)* |
| TD6 | shadow tints everything | CGWSEL source · CGADSUB enables · TM/TS main-vs-sub · window confinement | the main/sub-screen model *(engine-verified)* |
| TD7 | enhancement-chip RAM corruption | bus-ownership gating (RON/RAN) · handoff timing · SA-1 mapping | **reference-ONLY — zero engine experience; say so** (the honesty test) |
| TD8 | input missed/doubled | auto-read racing manual reads · mixing $4016 strobe with auto-read · completion timing | when the auto-read completes vs when the handler reads *(engine-verified)* |

## The trap bank — anti-folklore acceptance test

**Rubric:** *Bait* = the plausible myth · *Reality* = the mechanism · *the
tell* = the discriminator a reasoner states that a parrot can't fake.
**Pass** = debunk from the mechanism, state the tell, tier the claim.
**Fail** = confirm the bait. Timing in **master cycles** (NTSC ≈1364
mc/scanline; a CPU cycle = 6/8/12 mc by region + MEMSEL).

| # | Bait → Reality | The tell |
|---|---|---|
| T-1 | "DMA is ~1 CPU cycle/byte; FastROM speeds it up" → DMA is **8 mc per byte** + per-channel + per-MDMAEN overhead; **FastROM does nothing for DMA** | converts to mc; splits per-byte vs per-channel; FastROM irrelevant |
| T-2 | "CGRAM is VBlank-only like VRAM" → CGRAM is writable in VBlank, **HBlank**, and forced-blank (why raster-palette HDMA works); a mid-render write hits the index being drawn | separates the write-twice latch (real, not the bug) from the access window; CGRAM ≠ VRAM |
| T-3 | "multiplies are instant; one shared unit" → **two** multipliers: CPU $4202/$4203→$4216 needs ~8 CPU cycles (early read = garbage); Mode 7 M7A×M7B→$2134 is combinatorial but render-gated | names both units + latencies + intermediate-read garbage |
| T-4 | "FastROM = whole system at 3.58 MHz" → per-region 6/8/12 mc; **WRAM is always 8 mc**; only banks $80-$FF ROM at 6 mc with MEMSEL | breaks the speedup down by region |
| T-5 | "X=$100 is a free off-screen hide" → it **still counts** toward the 32/line Range limit (hide via Y); Range scans low→high, Time scans high→low — opposite directions | the X=$100 bug + the opposite scan directions |
| T-6 | "raster jitter = you miscounted instructions" → the CPU pauses ~40 mc mid-EVERY-scanline for **DRAM refresh**, plus auto-joypad, HDMA, MEMSEL, IRQ latency | names DRAM refresh unprompted |
| T-7 | "stack per-layer alpha" → one main ± sub (or fixed) operation per pixel; TM/TS assign layers; **only OBJ palettes 4-7** participate | the single-operation ceiling + the OBJ palette restriction |
| T-8 | "read $4218 first thing in NMI; unused bits are 0" → auto-read isn't done when NMI fires (gate on $4212.0); unused high bits are **open bus, not 0** | the busy window AND open-bus ≠ 0 |

**Rapid-fire probes** (state flatly; pass = correct it): HDMA does not run
through VBlank (re-inits ~V=0) · DMA can't WRAM→WRAM ($2180→$2180 fails; use
MVN/MVP) · there is no 8×16 sprite mode (OBSEL size *pairs*) · CGRAM does not
require forced-blank · write-only PPU registers read open bus, not
last-written · the APU runs on its own resonator (~0.25% fast — sync on the
handshake, never on counted CPU cycles).

---

These facts enter at **hardware-reference** tier (sourced to the fetched
references) until verified on the emulator here; the engine-verified subset
is marked. If an answer here ever contradicts a template, that's a build-time
bug — file it.
