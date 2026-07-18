# Seam-IRQ band origin + gradient payload (`split_h_irq_grad_demo`)

The split-screen family's **channel unlock**: move a band's per-frame ORIGIN
writes off their HDMA channel pair and onto a **seam-scanline IRQ**, freeing
both channels — then spend one of them on a real per-scanline raster payload
(a COLDATA gradient here). Proven standalone on this rail; the 2-player rail
port (whose 256-pose build has all 6 allocator channels busy) is the main
line's follow-up.

Everything below is measured on the emulator (the cold-start rail
`templates/seam_irq_trial/` + this demo's suite); nothing is estimated.

## Why

The 2p rail's per-band origin costs a channel PAIR (M7X/M7Y + M7HOFS/M7VOFS,
NON-REPEAT DMAP `$03`): 8 bytes once per frame, at one specific HBlank — the
seam. That is a *scheduling* job, not a *bandwidth* job: a V-count IRQ can
deliver the same 8 bytes at the same instant. HDMA channels are the scarce
resource (6 allocator channels; the 256-pose build uses ALL of them); the CPU
at the seam line is idle (the loop is parked in `wai`).

## The mechanism (the shipping shape)

- **Boot (forced blank):** band-1's four origin registers are written
  directly — they hold through lines 0..111 every frame. CH0/CH1 (the
  allocator RESERVES them for general DMA — they are never handed to HDMA
  effects) are pre-armed as general-purpose DMA:
  - CH0: DMAP `$03`, BBAD `$1F`, 4 bytes from `$7E:C100` → M7X/M7Y
  - CH1: DMAP `$03`, BBAD `$0D`, 4 bytes from `$7E:C104` → M7HOFS/M7VOFS
- **VBlank (game loop, after the GATED wai):** re-stamp band-1's origin
  registers directly (VBlank = safe latch window), advance positions,
  restage band-2's 8 bytes into the WRAM source blocks, **re-arm CH0/CH1
  A1T + DAS** (a general-DMA fire consumes both — the DAS-is-single-shot
  lesson).
- **Seam IRQ (once per frame):** spin on the HBlank flag, then ONE MDMAEN
  write (`$420B = $03`) fires both channels back-to-back. Ack via `$4211`
  read. Handler preserves A only; ~26 CPU cycles + the DMA.
- **Vector + enable:** `SF_IRQ_VECTOR = seam_irq` before the `header.inc`
  include (the engine's additive opt-in — default stays the stub,
  byte-identical); NMITIMEN composed through `SHADOW_NMITIMEN`
  (`sf_irq.inc`: `sf_nmitimen_or` / `sf_irq_arm_v vtime` / `sf_irq_disarm`);
  `sf_irq_arm_v` ends in CLI (the coldstart SEI otherwise masks IRQ
  forever — and an armed-but-masked IRQ line makes every `wai` fall
  through immediately: measured ~28k wakes/s).

**The gold assertion:** a static scene rendered by this mechanism is
**byte-identical** to the same scene rendered by the classic HDMA-origin
pair (0 differing rows, full frame). The mechanism is a drop-in
replacement. Non-vacuity: firing the same DMA at scanline 60 corrupts
exactly content lines 60..111.

## The timing model (measured, and where the first build went wrong)

- **The render pipeline is one line deep.** Content line L's pixels are
  drawn during INTERNAL scanline L+1 (internal scanline 0 is a pre-render
  line; the harness screenshot offset "+7" = the PPU's +6 output-buffer
  offset + this pipeline line). The V counter (IRQ match, OPVCT latch)
  counts INTERNAL scanlines. **Therefore: arm `VTIME = SEAM` (112), not
  SEAM−1.** The first trial build armed 111 and corrupted exactly content
  line 111 — one full row — before the model was corrected.
- **V-only IRQ fire point:** CPU IRQ asserts ~14 master clocks (dot ~3)
  into the matching internal scanline. With VTIME=112 the handler enters
  at dot ~47 of scanline 112 — while content line 111 is still being drawn
  (dots 23..278). It does no register writes yet.
- **The write window:** the DMA's B-bus bytes must land after dot ~277 of
  scanline 112 (all of content line 111 flushed) and complete by dot ~22
  of scanline 113 (content line 112's first flush trigger). The handler
  spin-gates on the **HBlank flag** (`$4212` bit 6, sets at dot 274;
  `bit $4212` / `bvc` — 6 cycles/iteration) and then fires. The per-line
  HDMA transfer event (dot 276) **pauses the CPU**, so the MDMAEN write
  always lands strictly after that line's HDMA — there is no general-DMA /
  HDMA overlap window to worry about.
- **Measured completion:** OPHCT/OPVCT latched one instruction after the
  MDMAEN write returns reads **dot ~11-15 of scanline 113** — inside the
  window. The margin degrades gracefully: past dot 23 the only flush
  triggers are the DMA's own writes, so a late fire produces a bounded
  left-edge partial-flush, not a hard tear wall.
- **H+V dot-precision is NOT needed.** An H+V trigger (bit `$10` + HTIME)
  through the same HBlank gate converges to the same dot-274 sync point —
  measured byte-identical render. WITHOUT the gate, an H+V fire risks
  landing MDMAEN in the dot 274..276 zone where a general-DMA start meets
  the HDMA trigger. Ship V-only + the spin gate.

## H1 — the wai-gate pattern (THE export for the future 2p port)

`wai` wakes on IRQ as well as NMI — measured ~2 wakes/frame with the seam
IRQ armed (~1 on the control). A loop that does its "VBlank" table writes
right after a bare `wai` will write **mid-frame** after the seam wake. Gate
on the NMI counter:

```asm
game_loop:
    lda f:$7E0000 + $E010       ; NMI counter
    sta f:$7E0000 + PREV_NMI
@sleep:
    wai
    lda f:$7E0000 + $E010
    cmp f:$7E0000 + PREV_NMI
    beq @sleep                  ; woke on the seam IRQ -> sleep again
    ; --- VBlank window: table writes safe here ---
```

The cadence gate (loop/NMI/IRQ counters +1/+1/+1 per stepped frame over 24
frames) holds on the shipped moving+gradient build.

## Why general-DMA and not CPU stores in the handler

Two reasons, both measured/derived:

1. **Budget.** 8 byte-writes by CPU (load+store each) ≈ 380-440 master
   clocks — it does not fit the ~340 mc window once HDMA steals its share.
   The pre-armed dual-channel fire moves ~1 CPU store into the window; the
   DMA itself moves 8 bytes at bus speed (~100 mc for both channels).
2. **The shared Mode-7 ValueLatch.** ALL M7 registers share ONE write-twice
   latch (`reg = value<<8 | latch; latch = value`). Each register's lo/hi
   must be written back-to-back. DMA mode `$03` sends exactly
   B,B,B+1,B+1 — the per-register order. The demo's `-DIRQ_INTERLEAVE`
   tear control writes the same 8 bytes as 16-bit stores (byte order
   Xlo→`$211F`, Ylo→`$2120`, Xhi→`$211F`, Yhi→`$2120`): every pair
   interleaves through the latch, both registers corrupt, and band 2
   visibly breaks — the H4 latch-discipline violation made visible,
   compared frozen-vs-frozen.

Constraint inherited from the engine: CH0/CH1 are the dma_scheduler's
VBlank bulk channels in engine scenes. This rail owns them outright; a
consumer that also runs the scheduler must re-arm A1T/DAS **after** the
scheduler's VBlank work (the gated-wai loop's post-wai window already is).

## The gradient payload

One freed channel drives COLDATA (`$2132`), 1 byte per line, DMAP `$00`:

- **Plane-select trick:** `$E0 | v` sets R=G=B to v in ONE write (bits
  7/6/5 select B/G/R planes; bits 4-0 intensity) — a gray ramp is a
  1-byte/line table.
- **Table:** `[$80|112, 112 vals][$80|112, 112 vals][$00]` (repeat mode =
  a NEW byte every scanline), built at boot into WRAM by a ~15-line loop
  (`v = line >> 3`, 0..27 down 224 lines). No committed generated blob →
  no provenance surface.
- **Color math:** fixed-color ADD on BG1 — CGWSEL `$00` (bit 1 = 0 →
  fixed-color source; bits 7-4 = 0 → never clip / never prevent),
  CGADSUB `$01` (bit 7 = 0 add, bit 6 = 0 full, bit 0 = BG1). Bits
  verified against the emulator core's register decode.
- **Test metric by design:** every world color + the backdrop carries
  BLUE = 0, so the rendered blue channel is EXACTLY the gradient term —
  checker-immune. Measured per-row blue means at content lines
  0/56/112/168/223: 0 / 57 / 115 / 173 / 222 — strictly monotonic;
  `-DNO_GRAD` flips the same metric to all-zero.

## Channel budget

| build | matrix | origin | gradient | free |
|---|---|---|---|---|
| this rail (IRQ origin) | `$0C` (2) | **0 — freed** | `$10` (1) | **3** |
| classic control (`-DHDMA_ORIGIN`) | `$0C` (2) | `$30` (2) | — | 2 |
| the 2p 256-pose rail today | `$3C` (4) | `$C0` (2) | — | 0 |
| the 2p rail after the port | `$FC`→`$3C`+2 freed | IRQ | 1+ available | 1+ |

## Porting notes for the 2p rail (main line owns this)

- The wai-gate is the single load-bearing loop change; the 2p loop already
  does all writes post-wai, so the gate slots in around its existing `wai`.
- `stamp_origins`' band-2 half becomes `stamp_band2_stage` (same
  subtraction math, target = the DMA source blocks); band-1's half becomes
  direct register stores (or stays HDMA — freeing ONE channel instead of
  two — but band-1's values are boot-stable between VBlanks, so direct
  stores are free).
- The seam handler + `rearm_seam_dma` copy verbatim; VTIME = the seam
  content line (112).
- The IRQ counter mirror (`$7E:E050`, +1/frame lockstep with `$E010`) and
  the wake counter (`$E058`, ~2×frames) are the cadence/health probes the
  port's tests should keep.

## Files

- `templates/split_h_irq_grad_demo/` — the demo rail (+ variants script).
- `templates/seam_irq_trial/` — the cold-start trial (kept: it carries the
  fire-point measurement probes and the mis-timed-IRQ control).
- `lib/macros/sf_irq.inc` — the opt-in macro layer (vector + NMITIMEN
  shadow compose + arm/disarm).
- `infrastructure/rom_template/header.inc` — the `SF_IRQ_VECTOR` opt-in
  (default byte-identical; proven by a 99-ROM md5 sweep).
- `engine/engine_state.inc` — `ES_SHADOW_NMITIMEN` (`$3D`) +
  `SHADOW_NMITIMEN` alias.
- Tests: `tests/test_split_h_irq_grad_demo.py` (9),
  `tests/test_seam_irq_trial.py` (8).
