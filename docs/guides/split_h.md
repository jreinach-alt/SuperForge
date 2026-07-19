# `sf_split_h` — horizontal raster-band split via HDMA

A production guide for the horizontal (top/bottom) raster-band split: HDMA
rewrites a PPU register at HBlank between scanlines, so different scanline
*bands* render differently. This is the clean, well-proven axis for per-region
rendering on stock SNES — e.g. a Mode-7 perspective floor under a genuine tile
HUD band. The split is armed once and costs essentially nothing per frame.

Rail: `templates/split_h_demo/` · macros: `lib/macros/sf_split_h.inc` ·
engine: `engine/hdma_alloc.asm` (`hdma_bind_direct`) ·
tests: `tests/test_split_h_demo.py` (D1–D4 + controls, all read the framebuffer).

## Mechanism

The PPU register latch (BGMODE `$2105`, TM `$212C`, COLDATA `$2132`, the window
edges, the Mode-7 matrix) takes effect **per-scanline at HBlank**. An HDMA
channel that rewrites one such register at a chosen scanline produces a **clean
single-scanline band boundary** — the seam is one crisp row, not a smear. (A
*mid-active-display* code-side register write, by contrast, renders piecewise +
pipeline-smeared; that is why the horizontal split is done with HDMA, never with
a mid-scanline `sta`.)

A 2-band split on one register is a 5-byte HDMA table:

```
    [split, top_byte, $01, bot_byte, $00]
    [split, top]   lines 0..split-1  -> register = top_byte  (the top band)
    [ 1,    bot]   line split          -> register = bot_byte  (the bottom band)
    [ 0        ]   terminator          -> register holds bot_byte for the rest
```

**N bands** generalise this: `.byte c0,v0, c1,v1, ..., $00`. Each `count` (`c_i`)
is a **7-bit line count** (1..127, bit 7 = 0 → non-repeat: write one value byte,
hold it for `c_i` scanlines); `v_i` is the register byte for that band; the final
`$00` **terminates** the table and the last value holds to the frame end. The
bands tile top-to-bottom (band0 = lines `0..c0-1`, band1 = lines `c0..c0+c1-1`,
…); the counts should sum to ≤ 224. `sf_split_h_bands reg_sel, table, id,
{c0,v0, c1,v1, ...}` emits this and arms it (it appends the `$00` — do NOT include
it); `sf_split_h_2band` is the 2-band wrapper.

Arm several channels — one register each — to compose a multi-register band. The
canonical archetype-A "Mode-7 floor + tile HUD" split drives **two** registers
together:

| register | top band | bottom band | meaning |
|----------|----------|-------------|---------|
| `BGMODE` (`$2105`) | `$09` | `$07` | top = Mode 1 (+ BG3 priority); bottom = Mode 7 |
| `TM` (`$212C`)     | `$04` | `$01` | top = BG3 only (the HUD); bottom = BG1 (the floor) |

Above the split the PPU is in Mode 1 and renders the BG3 tile layer; below it,
Mode 7 renders the perspective floor.

> **The band renders a few scanlines BELOW the nominal `split`** (HDMA count +
> the one-line latch latency). Size the HUD tilemap content to the *actual* band
> height, not to `split`. The switch itself is a clean single-scanline seam.

## Channel routing — the HDMA-target registry

Splits route through the **HDMA allocator**, not hand-hardcoded `$43xx`
programming. `sf_split_h_arm` calls `hdma_request` for one free channel, then
`hdma_bind_direct` (`engine/hdma_alloc.asm`) binds that channel to the register's
BBAD and arms it (ORs the channel bit into `NMI_HDMA_ENABLE`; the engine NMI
re-arms `$420C` from that mask every VBlank). The allocator owns the
channel↔register map, so two independent splits can never collide on a channel —
the collision class hand-rolled CH2/CH3 programming used to hit.

`hdma_bind_direct` requires A16/I16 and **DB=$00** (the `$43xx` DMA registers are
bank-$00 I/O; `NMI_HDMA_ENABLE` is mirrored low WRAM). The `sf_split_h_arm` macro
forces DB=$00 around the call. Reserve CH0/CH1 first with `hdma_alloc_init` at
boot.

## VRAM budget

Mode 7 occupies the **entire low 32 KB** of VRAM (interleaved 16 KB map + 16 KB
8bpp CHR). Tile layers for a split MUST live in the **upper 32 KB**:

```
    Mode 7 map + CHR   VRAM word $0000..$3FFF   (sf_mode7_load_map)
    BG3 tilemap        VRAM word $4800          (BG3SC  $2109 = $48)
    BG3 CHR            VRAM word $5000          (BG34NBA $210C = $05)
```

Both `$4800`/`$5000` are ≥ `$4000`, clear of the whole Mode-7 region. Set
`$2109`/`$210C` **once** during forced blank and they persist — the engine NMI
does not re-commit them.

> **Do NOT use the engine `gfxmode` / `mset` path for the BG3 HUD in a Mode-7
> split.** `gfxmode #1` sets BG34NBA=`$0A`, which puts BG3 CHR at word `$2000` —
> *inside* Mode 7's region; and the NMI's BG3-tilemap DMA targets word `$6000`.
> Set the BG3 base registers manually and write the BG3 tilemap directly to VRAM
> (under forced blank at boot). The per-frame **dynamic bar row** is updated the
> **kit-idiomatic** way — no mid-frame forced blank: `draw_bar` builds the 24
> tilemap words into a stable WRAM buffer (`BAR_BUF`), then the game loop sets
> `VMAIN`/`VMADD` and enqueues a GP-DMA of the buffer on the engine VBlank DMA
> queue (`dma_queue_add`, `BBAD=$18`/`DMAP=$01`, priority 1). The NMI drains it
> during VBlank (Phase 3, before any tilemap/stream DMA), so the port is stable
> and the display never blanks. This mirrors the `sf_fx.inc` CGRAM idiom (set
> `$2121`/`$2116` in the main loop, queue the `$2122`/`$2118` DMA) — it works
> because the GP-DMA queue drain touches only DMAP/BBAD/src/size on CH0, and
> nothing between the main-loop `VMADD` set and the NMI writes `$2115`/`$2116`
> (Mode-7 tick builds tables in WRAM; `sf_frame_end` runs audio/fade only), so
> the latched address holds to the drain.

**Per-band CGRAM discipline (mandatory):** the band palettes MUST NOT overlap.
This palette-hi-byte / CGRAM-overlap trap was the hardest build bug in the
primitive — a HUD that silently renders in the *floor* palette because its tiles
resolved to the wrong CGRAM region. The demo's **CGRAM budget map (archetype
A)**:

| CGRAM index | owner | selected by | notes |
|-------------|-------|-------------|-------|
| `0` | Mode-7 backdrop | index 0 (always) | the fixed backdrop colour |
| `0..FLOOR_PAL_COUNT-1` (`0..5`) | **Mode-7 floor** (group 0) | Mode-7 pixel palette index | the receding ground plane; the floor CHR indexes low CGRAM directly |
| `6..15` | *reserved / free* | — | the buffer that keeps the two regions apart |
| `16..19` (group 4) | **BG3 HUD** | BG3 **tilemap-word hi-byte** = `$10` (`PAL_HI = $1000`) | the instrument panel: frame + gauge + fill bar |

**How the tilemap hi-byte selects the group.** A BG3 tilemap word is
`vhopppcc cccccccc` — bits 0–9 the tile number, **bits 10–12 the palette
GROUP**, bit 13 priority, 14–15 flip. `PAL_HI = $1000` puts `%100` in bits
10–12 → **group 4** → the BG3 tiles read CGRAM `16 + (4bpp:16 / 2bpp:4)*group`;
for the demo's 2bpp BG3 that is CGRAM `16..19`. A common trap is ORing `$10`
into the tilemap word's **low** byte (the tile number) instead of the high byte
— the tiles then keep group 0 and render in the *floor* palette.

**Why the two must not overlap.** The Mode-7 floor CHR indexes CGRAM `0..5`
directly (no group concept — Mode 7 is 8bpp-ish, one flat palette). If the BG3
HUD's group-4 window (`16..19`) ever slid down into `0..5`, the HUD would draw in
floor colours and the seam would look "tinted." The demo enforces this at
**compile time**: `main.asm` computes `FLOOR_CGRAM_END = FLOOR_PAL_COUNT - 1` and
`BG3_CGRAM_BASE = 16`, then

```asm
.assert FLOOR_CGRAM_END < BG3_CGRAM_BASE, error, "CGRAM overlap: ..."
```

fails the build with a clear message if a future edit grows the floor palette
past index 15 (or moves the HUD group down) so the two collide. Keep a gap.

**~2 content modes per frame, max.** Mode 7 alone is the low 32 KB, so a split
can support the Mode-7 floor plus roughly one tile layer's worth of upper-32 KB
content. Do not design for 3+ simultaneous *content* modes — it is
VRAM-impossible.

## Cost

The band switch is HDMA — the CPU is not involved during active display.
Per-frame cost is the NMI re-arming `$420C` (a handful of cycles) plus the tiny
per-band table re-arm; a static split is **effectively free** against the
~28–37 k-cycle frame budget. The demo's only recurring CPU cost is the ~24-word
bar-row VRAM write for the dynamic instrument (well under one scanline, done
under a brief top-of-frame forced blank).

**Under load.** The band split is independent of what the Mode-7 engine does to
its own matrix: the mode/layer band drives BGMODE/TM on their own HDMA channels
(CH2/CH3), while the Mode-7 matrix rides CH5/CH6. The demo binds the camera
angle to the shoulder buttons, so holding one spins the floor and makes
`sf_mode7_tick` do a **full per-scanline matrix rebuild every frame** — the
CH5/CH6 matrix HDMA is rewritten continuously. The band split renders
identically under that load: the seam stays a single clean scanline and the top
tile band is untouched (test `test_d5_split_holds_under_rotation_load` reads the
rendered floor-band pixels to confirm the scene genuinely rotated, then asserts
the split still holds and the seam is un-smeared). This is expected — the split
registers and the matrix registers do not share a latch (see the guard below,
which is about the *matrix-band* case where they would).

## The ValueLatch guard (matrix bands only)

The Mode-7 write-twice latch byte is **shared** across M7A–D (`$211B`–`$211E`),
M7X (`$211F`), M7Y (`$2120`), M7HOFS (`$210D`) and M7VOFS (`$210E`). Note that
`$210D`/`$210E` are the SAME PPU addresses as BG1HOFS/BG1VOFS — a code-side BG1
scroll write shares this same latch. If an HDMA channel writes a matrix register
*between* the two bytes of a code-side write-twice to any shared-latch register,
**both corrupt**.

- **v1 payloads (BGMODE / TM / TS / COLDATA / brightness / window) do NOT touch
  that latch — no guard needed, proven safe.**
- A **matrix band** (archetype C-horiz — a per-band Mode-7 camera) DOES touch it.
  Its contract: every code-side write-twice pair to a shared-latch register
  happens ONLY in VBlank / forced blank (the shadow→NMI-commit pattern, never in
  the main loop during active display), while the matrix-band HDMA fires only
  during active display — the two are then structurally non-interleaving.
- **BOTH shipped matrix variants satisfy this BY CONSTRUCTION** (see the archetype
  section below): they write M7X/Y/M7SEL/M7HOFS/VOFS ONLY once under forced blank
  at boot (the perspective variant lets the engine NMI commit M7X/Y in VBlank) and
  drive M7A–D entirely by HDMA during active display — no code-side write-twice can
  ever interleave.
- **The guard is now PROVEN load-bearing, not just theoretical.** The shipped
  perspective variant (`split_h_persp_demo`) ships a `-DLATCH_VIOLATION` **negative
  control**: a code-side write-twice to a shared-latch register (`$210D`/`$210E`)
  DURING active display, while the per-scanline REPEAT-mode matrix HDMA streams,
  measurably TEARS the floor (per-scanline jitter multiplies vs the clean default).
  The flat NON-REPEAT band could not manufacture this collision (it wrote the
  matrix only 2×/frame); the REPEAT-mode per-scanline density (224 latch
  writes/frame) is where it bites. Framebuffer-verified — test `P5`.

## Archetype C-horiz — stacked Mode-7 camera bands

Render TWO (or more) vertically-stacked views of ONE Mode-7 world, each band a
DIFFERENT camera set by the Mode-7 matrix (M7A–D) changing at the band seam via
HDMA. Trial-proven, framebuffer-verified: top band scale `$0100` (1.0) → an 8-px
on-screen checker period; bottom band scale `$0040` (0.25) → 4× larger (32-px
period). SAME map + CHR + CGRAM, only the matrix differs. Shipped as the
`split_h_matrix_demo` rail (`sf_split_h_matrix_bands` / `sf_split_h_matrix_band`).

- **THE NON-REPEAT TRAP (the #1 gotcha).** Each band's HDMA count byte has
  **bit7 = 0 (NON-REPEAT)**: the 4-byte matrix unit transfers ONCE per band and
  HOLDS for `count` scanlines — a flat per-band camera, and **cheap** (2 HBlank
  writes/frame per channel). Do **NOT** set bit7 (REPEAT): repeat mode re-reads a
  NEW 4-byte matrix unit *every* scanline, walks off the short per-band table, and
  **collapses the whole plane to tile 0**. NON-REPEAT is required for flat cameras.
- **BYPASS, not coexist (the exclusivity rule).** The engine's
  `sf_mode7_perspective` / `pv_rebuild` owns the per-scanline M7A–D stream on
  CH5/CH6 (a single-camera trapezoid). A per-band matrix cannot layer on it — it
  must OWN the M7A–D HDMA. So a matrix band is **mutually exclusive** with the
  perspective renderer: do the MINIMAL Mode-7 init (BGMODE=7, M7SEL, load map,
  CGRAM, M7X/Y once under forced blank) and do NOT call the perspective renderer;
  the band drives M7A–D itself.
- **Register + channel recipe (cost = 2 channels).** AB channel: DMAP `$03`
  (write-2-registers), BBAD `$1B` → entry `[count,A_lo,A_hi,B_lo,B_hi]` streams
  into M7A (`$211B`) + M7B (`$211C`). CD channel: DMAP `$03`, BBAD `$1D` →
  `[count,C_lo,C_hi,D_lo,D_hi]` into M7C (`$211D`) + M7D (`$211E`).
- **M7X / M7Y foldable.** Set ONCE under forced blank for a constant-centre
  stack (scale/rotation-per-band alone reprojects the shared centre). A per-band
  centre would need a 3rd channel — NOT in this variant.
- **VRAM shared / free.** Both cameras read the SAME low-32KB Mode-7 map + CHR
  (word `$0000`) — no extra VRAM vs a single Mode-7 view.
- **Guard satisfied by construction** — see the ValueLatch guard above.

### The PERSPECTIVE variant (shipped) — per-band *per-scanline* camera

The flat variant above holds a **constant** matrix per band. The **perspective**
variant renders TWO full **per-scanline** trapezoids — two genuinely-different,
**independently-animating** perspective floors (the 2-player top/bottom racer
pattern), one per band, at a clean single-scanline seam. Shipped as the
`split_h_persp_demo` rail (`sf_split_h_persp_capture` / `sf_split_h_persp_splice`).

- **MECHANISM — USE the engine renderer, then SPLICE (do NOT hand-roll a REPEAT
  ramp).** The engine's `sf_mode7_perspective` / `sf_mode7_tick` → `pv_rebuild`
  already owns CH5/CH6 and streams a full per-scanline REPEAT-mode AB/CD trapezoid
  for the LIVE camera A across the whole floor band — its HBlank cost is the SAME as
  the shipping flight/racer rails (proven 60fps). The perspective variant
  **post-patches** the active AB/CD buffer's band-2 scanlines `[seam .. L1)` with a
  SECOND camera B's per-scanline matrix. That splice is CPU writes into WRAM: it
  adds **NO** HDMA channel — still just CH5|CH6 (mask `$60`).
- **⚠ THE APPLY-HOOK RULE (the 30 Hz double-buffer-desync failure mode).** The
  per-scanline matrix HDMA table is **DOUBLE-BUFFERED**, and `pv_rebuild` FLIPS it
  every rebuild (`mode7_hdma.asm` "Step 1 — flip the double buffer") before emitting
  camera A. The splice **MUST** therefore target the **ACTIVE** buffer
  (`pv_hdma_ab0/cd0 + pv_buffer_x`), re-stamped every rebuild frame — exactly the
  `mode7_barrel_apply` pattern, which is why the engine hook `mode7_band_splice`
  consults `pv_buffer`. Splicing into a **FIXED** buffer from the main loop is the
  classic bug: on the ~half of frames where `pv_rebuild` flipped to the *other*
  buffer, band-2 reverts to camera A → a **30 Hz flicker**. It is invisible to a
  single settled-frame test (that grab lands on whichever ~30 Hz phase the wall
  clock hits), so it MUST be caught by a **multi-frame temporal-stability test**:
  advance EXACTLY one PPU frame at a time (`frame_step`) and assert band-2 is
  byte-stable across ~12 consecutive frames while `pv_buffer` is observed to flip.
  The `-DFIXED_BUFFER_SPLICE` build reinstates the bug as the negative control that
  proves the test catches it (test `P3`).
- **INDEPENDENT WORLD POSITION (per-band origin splice — the camera-pos
  capability).** The band-2 *matrix* splice above only changes band-2's
  **scale/angle**, because a camera's WORLD POSITION feeds the **global** Mode-7
  origin (`pv_set_origin` → M7X/M7Y + M7HOFS/M7VOFS), which both bands otherwise
  share. To give band-2 a **different world location** (a true 2-player pan, not
  just a zoom of the same spot), splice the **whole origin per band via HDMA**:
    - **CH2** drives **M7X/M7Y** (`$211F`, DMAP `$03` write-2-registers-twice → M7X
      then M7Y);
    - **CH3** drives **M7HOFS/M7VOFS** (`$210D`, DMAP `$03` → M7HOFS then M7VOFS).

  Both tables are **NON-REPEAT** two-band shapes (`[SEAM, band1_origin, 1,
  band2_origin, 0]`), so each channel does just **2 HBlank transfers/frame** — a few
  bytes, NOT a solve. Band-1's slot is re-stamped each frame from the engine's live
  `nmi_m7x/m7y` + `SHADOW_BG1HOFS/VOFS` (so band-1 tracks camera A's rotation and
  agrees with the NMI's global commit); band-2's slot holds camera B's origin,
  captured ONCE at boot (right after camera B's first tick, when the engine origin
  solve reflects camera B's `posx/posy`).
  **Both registers are required — centre ALONE is insufficient (framebuffer-proven).**
  In the perspective model the centre re-adds itself (`… + M7X`), so splicing only
  M7X/M7Y shifts the sampled texel by just `(1 − M7A)·Δ` per scanline — ≈0 in the
  near band, so the view barely moves. `pv_set_origin` always moves centre AND
  scroll together (scroll = centre − screen-half); they cancel in the matrix term
  and leave a **rigid world translation of Δ**. So a clean pan needs BOTH splices.
  Cost: **+2 HDMA channels** (CH2+CH3; CH5/CH6 remain the matrix, so the full mask
  is `$6C`). CH2/CH3 are the only channels the perspective renderer never
  enables/owns (`pv_rebuild` owns CH5/CH6; CH0/CH1 are allocator-reserved), so they
  never collide with the engine stream. The **ValueLatch guard** extends
  unchanged: M7X/M7Y/M7HOFS/M7VOFS are written by CODE only in VBlank (NMI commit) /
  forced blank; the CH2/CH3 splices fire only during active display, and every HDMA
  channel transfer is atomic per scanline (complete write-twice pairs), so the
  M7A-D/M7X/Y/M7HOFS/VOFS shared latch is never left half-written across channels.
  `-DSAME_CENTER` folds camera B's origin back onto camera A's (same channels, same
  mechanism) → band-2 = the same world region (only scale differs): the C1
  non-vacuity control. Tests `C1` (band-2 is a different, red-tinted world region —
  read on the RED channel, orthogonal to the green+blue period signal), `C2` (the
  origin band-step is HBlank-clean, not smeared), `C3` (the panned region is
  temporally stable). NOTE the on-screen colour boundary is EXACTLY at the seam
  scanline: it appears at screenshot row `SEAM+7` only because harness
  screenshots carry 7 blank padding rows on top (PPU scanline L = image y L+7).
  An earlier draft misread that offset as a "world-X wrap lands the boundary a
  few rows into band-2" effect — confabulated physics; the C2 test now pins
  `step_y == SEAM+7`.
- **BOTH cameras animate — the budget decision (live A + precomputed B).** Camera A
  is a LIVE solve (auto-rotates via `sf_mode7_cam` → `pv_rebuild`). Making
  camera B a *second* live solve is BOTH a budget blocker AND *incorrect*: a 2nd
  rebuild flips the buffer a 2nd time, so both bands land in the SAME physical
  buffer HDMA is displaying this frame → a torn back-buffer. So camera B animates
  via **PRECOMPUTED** per-pose band-2 tables (the spec §2.3 documented substitute
  for the vendor's serial math coprocessor used by stock racing carts): K poses
  are solved ONCE at boot (under
  forced blank — no frame budget) into WRAM, and the per-frame apply-hook splices
  the CURRENT pose's band-2 into the active buffer. Both bands animate; only 1
  rebuild + 1 splice per frame.
- **Live-B budget — MEASURED infeasible (do not re-attempt without re-measuring).**
  A full per-scanline `pv_rebuild` is FAR more expensive than earlier drafts of
  this guide assumed. Measured on the emulator via `tests/persp_cycles_test.asm`
  (free-running ticks/frames, HDMA off; cost = `frames*357368/ticks`, one NTSC
  frame = 357,368 mc), at camera A's shipping params (224 lines, interp1):

  | approach for the second (camera B) solve      | mc/tick | % of one 60fps frame |
  |-----------------------------------------------|--------:|---------------------:|
  | camera A's own full solve (baseline, ALONE)   | 492,436 | **137.8 %**          |
  | camera B full band-2 (112 ln, interp1)        | 276,723 | 77.4 %               |
  | camera B half-res band-2 (112 ln, interp2)    | 214,912 | 60.1 %               |
  | camera B quarter-res band-2 (112 ln, interp4) | 185,028 | 51.8 %               |
  | both cameras full, 2 solves/frame (worst)     | 977,178 | 273.4 %              |

  A single solve already costs ~138 % of a frame — there is **negative** headroom,
  not the "~1/3 of a frame" earlier drafts (and the task brief) assumed. Every
  incremental route was measured: half-scanline-res (interp2), band-2-only, and
  quarter-res all still add ≥52 % on top of camera A's 138 %, landing the combined
  work at 190–273 % of a frame; time-slicing camera B to every other frame
  amortizes to +26–39 % on top of a camera A that is *already* over one frame.
  **Verdict: a genuine second live per-scanline solve cannot fit a 60 fps CPU
  frame by any incremental approach. Precomputed poses remain the shipping path.**
  (Corroborated by `tests/mode7_chamber_cycles_test.asm`, which documents the same
  full-rebuild path at ~431,000 mc / ~121 % and is why the chamber rolls via the
  origin, not rotation.)
- **Camera A's OWN SOLVE fits one frame via `interp4` (the shipped optimization) —
  but the INTEGRATED demo loop still closes in 2 frames (30 Hz motion).**
  The table above is about a *second* (camera B) live solve. Camera A's OWN
  full-floor rebuild at `interp1` is the 137.8 % row. The rail ships camera A at
  **`interp4`** (`A_INTERP` default in `split_h_persp_demo/main.asm`):
  quarter-scanline resolution — solve every 4th scanline, interpolate the 3
  between. Measured full-floor (0..224) solve:

  | camera A live full-floor solve | mc/tick | % of one 60fps frame |
  |--------------------------------|--------:|---------------------:|
  | `interp1` (per-scanline)       | 492,436 | **137.8 %** (overruns)       |
  | `interp2` (half-res)           | 370,131 | 103.6 % (still overruns)     |
  | `interp4` (quarter-res)        | 309,363 | **86.6 %** (the SOLVE fits)  |

  These numbers are **HDMA-off** (what the cycles instrument isolates). With the
  rail's CH5|CH6 per-scanline REPEAT HDMA active the solve measures ~**92.6 %**
  (the steal is ~23-25k mc/frame ≈ 7 %), so the real interp4 headroom is ~7 %,
  not 13.4 %. **The shipped demo loop does NOT close at 60 fps** (PR #223
  independent review, finding M1): per frame the loop also runs the band-2
  matrix splice (~85k mc ≈ 23.9 % — see the cost bullet below) plus the origin
  restamp, totalling ~110-120 % of a frame — and the `sf_frame` handshake
  quantizes ANY overrun to a whole extra frame. The game loop therefore closes
  once per TWO frames → **30 Hz pose motion** (`interp1` was *also* 30 Hz by the
  same quantization — an earlier draft's "~43 fps motion" was impossible). The
  DISPLAY holds 60 fps throughout: HDMA re-streams the committed double buffer
  every frame, decoupled from the loop rate.
  Quality: at camera A's params (`S0=320`, `S1=96`) the matrix ramp is gentle
  enough that quarter-res interpolation is **visually indistinguishable** from
  per-scanline — no stair-stepping near the (`PV_L0=0` top-edge) horizon, framebuffer-
  judged. `interp2` (103.6 %) does NOT fit, so `interp4` is the shipped default.
  **Standing gates:** `test_persp_cycles.py::test_rail_solve_fits_one_frame`
  asserts the full-floor `interp4` solve stays < one frame (solve-budget gate);
  `test_split_h_persp_demo.py::test_cadence_true_60fps_in_situ` is the in-situ
  loop-rate gate — it FAILS at HEAD (shipped `xfail(strict=True)`) and flips
  loudly to XPASS when the band-1-only-rebuild follow-up (rebuild `[PV_L0..SEAM)`
  only, measured ≈75-81 % total — feasible) lands.
- **The E010 heartbeat is a LIVENESS check, not a CPU-budget gate.** `E010` mirrors
  `FRAME_COUNTER` = the NMI/VBlank counter; it advances at ~60/sec REGARDLESS of
  how badly the game loop overruns, because the HDMA display re-streams the
  last-committed double-buffer every frame independent of the CPU solve rate
  (measured: a build burning 30k+ extra cycles/frame — game loop demonstrably at
  30 fps — still shows `E010` at ~120/120). So `test_split_h_persp_demo`'s
  `structural_channels_and_display_liveness` ">= 110/120" assertion proves the
  display/NMI is alive, NOT that per-frame work fits. The in-situ loop-rate gate
  is `test_cadence_true_60fps_in_situ` (reads `pv_buffer` flips per stepped
  frame in WRAM; xfail at HEAD — the shipped loop closes in 2 frames); the
  authoritative CPU-budget instrument is the free-running `persp_cycles_test`
  (`ticks/frames`) above.
- **Two-call API (capture + per-frame apply).**
  `sf_split_h_persp_capture seam, save_ab, save_cd` — build camera B via the engine
  macros + one `sf_mode7_tick`, then capture the active buffer's band-2 `[seam..L1)`
  AB (A,B) + CD (C,D) into WRAM (`mode7_band_capture`). Call it once per precomputed
  pose (vary scale/angle between poses). `sf_split_h_persp_splice seam, save_ab,
  save_cd` — call EVERY frame AFTER `sf_mode7_tick`; it re-applies the chosen pose's
  band over band-2 into the **active** buffer (`mode7_band_splice`). Pass the
  current pose's table addresses (via the API block) to advance camera B.
- **Cost = 2 channels (matrix) + 1 rebuild + splice; +2 channels for the origin
  pan.** CH5|CH6 (engine-owned) drive the matrix; per frame = 1 `pv_rebuild`
  (measured ~492k mc ≈ 138 % of a frame at interp1, ~309k ≈ 87 % at the shipped
  interp4 — see the budget tables above; this is why there is only ONE live
  solve) + the band-2 matrix splice copy — **NOT cheap**: measured ~85k mc ≈
  **23.9 % of a frame** (896 bytes through a `[dp],y` loop with a per-line width
  toggle, not the plain "WRAM memcpy" an earlier draft called it; it is what
  tips the integrated loop over one frame → the 30 Hz loop cadence above). The
  independent-world-position capability adds CH2 (M7X/M7Y) +
  CH3 (M7HOFS/M7VOFS) — full mask `$6C` — plus a ~16-store per-frame band-1 origin
  re-stamp (negligible). The DISPLAY holds 60 fps (HDMA); the game-loop rate is
  bounded by the solve + splice total above (the display is decoupled from
  it via the committed double-buffer). Budget instrument: `persp_cycles_test`.
- **Save-table sizing.** Each save table is `(M7_PV_L1 - seam) * 4` bytes (4 bytes
  per band-2 scanline). AB and CD are SEPARATE tables — do NOT overlap them. Park
  them in free WRAM (`split_h_persp_demo` uses `$7E:C000+`, the 8 KB gap between the
  engine heap and the `$E000` debug region); the engine routines take the addresses
  via the API block, so there is **no new persistent DP state** (`make zp-check`
  stays clean).
- **Guard PROVEN load-bearing** — the `-DLATCH_VIOLATION` per-scanline negative
  control (test `P5`) is the proof; see the ValueLatch guard above. This is the
  per-scanline negative control the backlog note required before shipping.
- **Exclusivity** — like the flat band, this OWNS the Mode-7 renderer (it drives
  `sf_mode7_perspective` / `sf_mode7_tick` directly). Do NOT combine with
  `sf_split_h_matrix_band` on the same scene (both own M7A–D).

### C-horiz perspective — hard-won gotchas

Four failure modes cost real debugging time on this rail. Each is now a mechanism
you must respect (and, where testable, a shipped test/negative control).

1. **Double-buffer desync (the 30 Hz flicker).** The per-scanline matrix table is
   DOUBLE-BUFFERED and `pv_rebuild` FLIPS the active buffer EVERY frame, then emits
   camera A into the newly-active buffer. A main-loop splice that writes a FIXED
   buffer therefore lands in the displayed buffer only ~half the frames; on the
   other ~half band-2 still holds camera A → the band alternates camera-B/camera-A
   at ~30 Hz. THE FIX: splice the ACTIVE buffer, re-stamped every rebuild frame —
   read `pv_buffer` and target `pv_hdma_ab0/cd0 + pv_buffer_x` (the
   `mode7_band_splice` / `mode7_barrel_apply` pattern). `mode7_band_splice` consults
   `pv_buffer`, so both bands stay coherent through the double-flip.

2. **A single settled frame is BLIND to 30 Hz alternation.** A free-running grab
   lands on whichever ~30 Hz phase the wall clock happens to hit, so it can read a
   perfectly clean frame while the display flickers. The desync is only observable
   with a MULTI-FRAME TEMPORAL-STABILITY test: advance EXACTLY one PPU frame at a
   time (`frame_step`) and assert band-2 is byte-stable across ≥10 consecutive
   frames WHILE `pv_buffer` is observed to take both values. Ship a
   `-DFIXED_BUFFER_SPLICE`-style negative control (reinstate the fixed-buffer bug)
   so the SAME stability metric is proven to FAIL when the bug is present —
   otherwise a green stability test is vacuous.

3. **The buffer is PV_L0-RELATIVE — index 0 == screen scanline PV_L0.** The AB/CD
   double-buffer is NOT indexed by screen scanline 0; buffer index 0 corresponds to
   screen scanline `PV_L0`. The band-2 splice offset is therefore `(seam - PV_L0)*4`
   (4 bytes/scanline), NOT `seam*4`. Misreading this as screen-scanline-0-relative
   mis-maps the seam by `PV_L0` scanlines — an off-by-`PV_L0` that slides the
   camera-A→B discontinuity off the intended seam row. (A data-level test that reads
   M7A from the active buffer and asserts the discontinuity sits at exactly
   `idx == seam` catches this class directly.)

4. **The frozen above-horizon "head."** The renderer builds the floor matrix for
   scanlines `PV_L0..PV_L1`; rows ABOVE `PV_L0` are not solved — they hold the
   horizon matrix value FROZEN (M7A stuck at the far-scale limit), rendering a flat,
   face-on strip pinned to the top edge. Two clean options: set `PV_L0 = 0` so the
   floor recedes all the way to the top edge (no head — what this rail ships), OR
   MASK the rows above the horizon to the backdrop for a deliberate sky. Do NOT
   leave the frozen strip visible.

#### The horizon build knob (`-DSKY_HORIZON`)

`split_h_persp_demo` exposes the two horizon behaviours from gotcha #4 as a
build knob (framebuffer-tested, `test_b_horizon_knob_sky_vs_floor`):

- **DEFAULT — floor-to-edge (`PV_L0 = 0`).** The Mode-7 floor fills every scanline
  up to the top screen edge; there is no sky and no frozen head.
- **`-DSKY_HORIZON` — sky-above-horizon.** A TM (`$212C`) HDMA band turns the
  Mode-7 floor (BG1) OFF for lines `0..SKY_H-1` so the `CGRAM[0]` backdrop shows
  through as a SKY band; the floor renders from line `SKY_H`. This is the racer's
  `sf_mode7_sky_split` / `arm_sky_split` technique, but bound on an **allocator-
  chosen** channel via `hdma_request` + `hdma_bind_direct` (NOT the macro's
  hardcoded CH2 — the origin splice owns CH2/CH3 here). NOTE: the sky band is
  masked to TM `$00` (all layers off), NOT the racer macro's `$10` (OBJ on): a
  demo that initialises no OAM would otherwise paint power-on-random sprite garbage
  into the sky. A rail WITH sprites uses `$10/$11` to keep a HUD/avatar above the
  horizon.

### Three stacked cameras (`split_h_persp3_demo`) — the budget-viable path for N cameras

Extra cameras beyond the live-A + precomputed-B pair CANNOT be LIVE per-scanline
solves: one solve alone is 87–138 % of a 60 fps CPU frame (the live-B budget table
above), so a third live solve is hopeless. The ONLY budget-viable path for three
(or more) cameras is **FLAT precomputed per-band matrices** via the N-band
`sf_split_h_matrix_bands` compiler: NON-REPEAT HDMA tables that hold a CONSTANT
matrix per band (2 HBlank writes/band/channel, ~nil CPU, NO live solve). The
`split_h_persp3_demo` rail stacks THREE cameras of one flat world at three scales
(`$0100`/`$0040`/`$0080` → on-screen checker periods ~8/~32/~16 px), two clean
single-scanline seams, distinguished by scale:

- **Mechanism / channels.** `sf_split_h_matrix_bands` with THREE
  `(count,M7A,M7B,M7C,M7D)` tuples emits the AB+CD tables and binds them on 2
  allocator channels (mask `$0C` = CH2|CH3, DMAP `$03`). One shared low-32KB Mode-7
  map+CHR at VRAM word `$0000` — NO extra VRAM per camera.
- **Budget = ONE camera's.** The scene is entirely HDMA-driven; the game loop just
  `wai`s. Three cameras cost the SAME as one (no `pv_rebuild`), so it closes 60 fps
  trivially — confirmed by the cycles-gate reasoning (no live solve) and the
  demo's `test_shared_vram_and_60fps` heartbeat check.
- **Temporal stability is inherent.** There is NO double buffer here (no
  `pv_rebuild` flip), so the flat matrix path cannot desync — `test_c3_temporal_stability`
  confirms byte-stable bands across consecutive deterministic frames.
- **Non-vacuity control.** `-DONE_CAM` collapses all three bands to camera A's
  scale → a single uniform camera fills the screen → the three-distinct-period
  assertion (`test_c1_three_distinct_cameras`) FAILS, proving C1 measures three
  real cameras, not merely the presence of seams.

### 2-player split screen (`split_h_2p_demo`) — two live-positioned perspective cameras, ~zero CPU

The C-horiz family's two-player rail: BOTH bands are per-scanline **perspective**
floors of one world, each with a fully **live, independent world position** —
and **no live matrix solve at all**. Per-frame CPU ≈ 40 VBlank stores (~1% of a
frame), so the loop closes EVERY frame: true 60 fps motion, gated in situ.

- **MATRIX — indirect-mode HDMA from ROM pose tables (the shipping mechanism).**
  Two allocator channels (BBAD `$1B`/`$1D`) run DMAP **`$43`** (indirect +
  write-2-registers-twice) with a **template-owned 7-byte index table** per
  channel in WRAM: `[$80|112, ptr(band-1 pose)] [$80|112, ptr(band-2 pose)] [0]`
  (`pv_rebuild`'s own 3-byte-entry form; `$80` = REPEAT — the NON-REPEAT trap is
  inverted here: repeat is REQUIRED, each scanline consumes a NEW 4-byte unit).
  The pointed-to pose tables are **band-local, ROM-resident** (448 B = 112 lines
  × 4 B), generated by `tools/gen_pose_tables.py`. **Retargeting a band's camera
  (heading change) is ONE 2-byte pointer rewrite in VBlank** — no copy, no solve.
  `hdma_bind_direct` accepts the `$43` DMAP verbatim; the ONE register it does
  not cover is the indirect DATA bank (`$43x7`) — the rail sets it once under
  forced blank (`set_indirect_banks`).
- **ORIGIN — per-band live position via the origin channel pair.** A second
  allocator pair (DMAP `$03` NON-REPEAT, BBAD `$1F` = M7X/M7Y and `$0D` =
  M7HOFS/M7VOFS), the proven origin-splice shape `[112, band1, 1, band2, 0]`.
  At **fixed heading the per-band origin is pure subtraction** — `M7X/Y = pos`,
  `HOFS = posx − 128`, `VOFS = posy − band_bottom_line` (band 1 bottom = 112,
  band 2 = 224: each camera "sits" at the bottom-centre of its own band) — no
  engine solve. Both positions re-stamp EVERY frame in the VBlank window right
  after `wai`, so the next frame's HDMA init fetch can never observe a
  half-written entry (the unsynchronized-restamp hazard class is closed by
  construction).
- **The budget lesson, applied.** One live per-scanline solve costs 86–138% of
  a frame (`persp_cycles_test`), and the live-A rail's integrated loop
  measurably closes in 2 frames (30 Hz motion) while its solve-only budget gate
  stays green. This rail replaces the solve with table streaming; its
  `test_cadence_true_60fps_in_situ` is the gate the live rail lacked: across
  stepped frames the **loop-iteration counter and the NMI counter must advance
  +1 together** — WRAM-read based (immune to the frame-stepping video-skip
  harness artifact), and a loop that overruns by even one scanline quantizes to
  +1 NMI per 2 iterations and fails it.
- **Heading granularity (the pose-table tool).** `tools/gen_pose_tables.py
  --angles {1,32,64,128,256,512}` emits one AB and one CD blob per set: pose
  *i* = the shared hyperbolic ramp `S(k) = K/(k+k0)` rotated by `2πi/N`
  (`A = S·cos`, `B = S·sin`, `C = −B`, `D = A`), band-local, `blob + i*448`
  addressable. **256 poses (1.40625° steps) is the rotate default** — one pose
  step PER FRAME at the demo turn rate (the smoothness rule below); **64
  (5.6°) stays the single-bank option** (28,672 B = ONE 32KB LoROM bank per
  blob exactly, the classic 4-channel shape). Sets above 64 poses are
  **bank-sliceable by construction**: 64 poses per 28,672-B slice, pose
  `64k + j` at slice *k* offset `j*448` — a consumer `.incbin`s slice *k*
  into its own bank and addresses `ptr = $8000 + (h & 63)*448`,
  `bank = base + (h >> 6)`. 512 (0.7°) is the slow-turn escape hatch
  (tool-supported; the 8.8 format wall where adjacent poses round
  byte-identical sits at ~512-1024). The default build runs the fixed-angle
  set (`--angles 1`); the 45° pose sliced from the 64 set ships as the
  `-DRETARGET` smoke (a non-trivial heading streams + retarget-by-pointer
  works, framebuffer-tested). Position is continuous regardless of
  granularity — only heading snaps.
- **Cost.** Classic shape: 4 allocator channels (2 matrix + 2 origin — mask
  `$3C` on a fresh allocator; the perspective renderer is NOT running, so
  there is no CH5/CH6 ownership to avoid). Per-band shape (`PERBAND` /
  `POSES=256`): **all 6 allocator channels** (4 matrix + 2 origin, mask
  `$FC`) — **the allocator is then FULL**: a later per-band OBJ-window clip
  or sky band would need channel multiplexing (one channel driving two
  registers across the frame via table shape). ~40 CPU stores/frame (+~30
  for the 256 build's four DASB stamps), 448 B ROM per pose per channel,
  one shared low-32KB Mode-7 map+CHR (no extra VRAM per camera).
- **ValueLatch guard by construction** (persp3 pattern): shared-latch registers
  are written by code only under forced blank; HDMA owns them during display;
  every runtime table write sits in VBlank. The `-DLATCH_VIOLATION` control
  write-twices M7HOFS mid-display **with the same value HDMA delivers** (pure
  latch interleave, no value stomp) and is compared **frozen-vs-frozen**
  (`FREEZE` on both sides) — the rotating-baseline confound that made the live
  rail's P5 non-discriminating cannot recur.
- **Tests** (`test_split_h_2p_demo.py`, framebuffer-first): per-line ramp in
  BOTH bands + seam pinned at EXACTLY scanline 112 (the screenshot **+7-row
  offset is modeled** — sample `scanline + 7`, the wrong-window lesson);
  independent position via the warm/cool red signal with the `-DSAME_ORIGIN`
  fold control; independent motion with the `-DFREEZE` flip control; the
  in-situ cadence gate; retarget; frozen temporal stability; the latch tear;
  the per-band structural masks with the allocation-order assert +
  `-DPERBAND_BADORDER` inversion control; the static line-0 gate (classic vs
  per-band byte-identical, badorder leaks EXACTLY screenshot row 7 — static
  scenes only: cross-ROM stepped screenshots are phase-polluted); the
  256-pose DoD trace (step-per-frame + pointer/bank binding + move256 8.8
  motion model); the slice-boundary pointer+bank same-frame flip.
  Tooling tests (`test_gen_pose_tables.py`): determinism, rotation identities,
  slice/bank budgets for all granularities, adjacent-pose distinctness at
  256, the move-LUT convention, and committed-asset byte-identical
  regeneration (the provenance contract).
- **LIVE ROTATION + MOVEMENT on both cameras (`-DROTATE`, measured).** The
  rotation pivot falls out of the origin math for free: the subtraction origin
  zeroes the matrix term at each band's **bottom-centre**, so the pose rotation
  `S(k)·R(θ)` spins the view **about the camera's own ground point** — heading
  needs **NO new origin math at any angle** (the earlier draft of this section
  claimed an origin solve would be needed; that holds only for OTHER pivot
  models, e.g. a look-ahead pivot behind the camera). Both cameras drive
  forward along their headings (`move_lut`: heading → `round(2·(−sin,−cos))`
  in 8.8, screen-up from the pivot maps to world `(−sin,−cos)`) and all four
  pose pointers are recomputed **every frame** (deliberate worst case:
  `ptr = slice_base + (h & 63)·448`, two shift-subtract multiplies;
  `lorom_stream.cfg` link). Two build shapes:
  - **`POSES=256` (the rotate DEFAULT — rotation smoothness).** The owner
    DoD is perceptual-rule-based: **pose-step interval ≤ 1 frame at the
    demo's turn rates.** 256 poses = 1.40625°/pose lets both cameras step
    **one pose EVERY frame** (+1/−1, equal-and-opposite senses — the same
    angular rate as the old cam-1, continuous instead of a jump every 4
    frames' 15 Hz stutter). Velocity indexes `move256` by `h` directly
    (exact forward direction at every heading). Blobs are 4 bank slices
    each (BANK2..5 = AB, BANK6..9 = CD); per frame each band's pointer
    (`$8000 + (h & 63)·448`) AND its pair's two **`$43x7` DASB bytes**
    (`bank = base + (h >> 6)`) are stamped in the same VBlank window
    (`stamp_pose_banks`, debug mirrors at `$7E:E040+`). **Measured: +1/+1
    loop/NMI lockstep over 24 stepped frames on the 6-channel build**
    (`test_rot256_dod_pose_step_every_frame`) with the pointer+bank pair
    flipping in the SAME frame at slice boundaries
    (`test_rot256_bank_boundary_crossing`).
  - **`POSES=64` (the single-bank A/B option, `_rotate64`).** The classic
    4-channel shape: one exact 32KB bank per blob, cam 1 stepping every 4
    frames, cam 2 every 6 (5.6° steps — the visible snap the 256 set
    removes). Kept for A/B comparison and for builds that need the two
    matrix channels back.
- **Per-band matrix channel pairs (`PERBAND` — the 256-set enabler).** The
  indirect data bank (`$43x7`) is per CHANNEL, so with one shared matrix
  pair both cameras' headings would have to sit in the same bank
  simultaneously — impossible under independent rotation once a blob spans
  multiple banks. The unlock: **each band gets its OWN AB+CD channel pair →
  its own `$43x7` → any pose bank per band** (4 matrix + 2 origin = all 6
  allocator channels). Band-1's index tables carry only its entry + a
  terminator (count 0 ends the channel for the frame — silent during band
  2's lines). Band-2's tables open with a **NON-REPEAT count-112 skip
  prefix**: it transfers its 4-byte unit ONCE at line 0, then holds
  silently until line 112. That single stray line-0 write targets the same
  M7 registers as band-1's channels — **masked by CHANNEL PRIORITY**: HDMA
  processes CH0→CH7 within each HBlank and every DMAP-`$43` unit delivers a
  complete lo+hi pair to both registers, so the LAST channel wins
  coherently; allocate band-2's pair FIRST (lower channels) and band-1's
  SECOND (higher channels) and band-1's proper line-0 values overwrite the
  stray unit in the same HBlank. The order is LOAD-BEARING —
  `-DPERBAND_BADORDER` inverts it and exactly PPU line 0 renders band-2's
  skip pose (the tests' non-vacuity control; the skip pointer deliberately
  aims at a pose that DIFFERS from band-1's so a broken mask is VISIBLE).
  Measured: classic vs per-band static render **byte-identical**; badorder
  differs at **exactly screenshot row 7** (= PPU line 0). Per-band layer
  dressing (TM/OBJ enables at the seam) still composes — but note the
  allocator is FULL (see Cost above).

#### The SPRITE STRESS RAIL (`SPRITES=N`) — players + AI + distance tiers, measured

World-space sprites projected per band per frame onto both rotating cameras
(`templates/split_h_2p_demo/sprites_2p.inc`; all numbers below are Mesen2
cycle measurements, not estimates).

**Projection (inverse of the floor map, per sprite per band).** The floor
draws `texel = P + S(k)/256 · R(θ) · (sx−128, k−112)`; the sprite path inverts
it: `(u,v) = R(−θ)·(W−P)`, then `k = sp_vk[−v]` (a 256-byte build-time inverse
LUT over `g(k) = (112−k)·S(k)/256` — the ramp is IMPORTED from the pose tool,
never re-derived), `tier = sp_tier[k]`, `sx = 128 + u·recip(k)>>8` (`recip =
65536/S8.8`, 9 bits, one hardware multiply). Two design rules carry the
budget:

- **Cull order is everything**: wrap-sub dx → `|dx|>176` out → dy likewise
  (Chebyshev pre-cull, zero multiplies) → the v dot → v/d/k/tier culls → only
  THEN the u dot. Measured per sprite per band: **visible 5,595 mc · behind-
  camera 2,003 mc · Chebyshev-culled 606 mc** (the naive core: 8,522 /
  6,965 / 6,965 — culled sprites went from 82% of a visible one to 11%).
  Two numbers get quoted for the visible cost and both are correct, measured
  two ways: **5,595 mc** is the DIRECT per-sprite figure from the pinned
  all-visible cycle instrument (`_spr_cyc`), and **5,653 mc** is the same cost
  read as the SLOPE of the integrated frame cost across N (the sweep, ÷2 for
  the two bands). They agree to +1.0% — the cross-check that the marginal
  per-sprite cost the sweep pays matches the isolated instrument.
- **8×8 hardware-multiply dots**: after the pre-cull `|dx|,|dy| ≤ 176` and the
  sincos LUT is magnitude-clamped to 255, so every rotation product runs
  through `$4202/$4203` with a sign/magnitude split (`t' = (t^m) − m`,
  per-term rounded `>>8`; terms ≤ 176 so the dot fits s16). CAVEAT (measured):
  this bought 1.52×, not the projected ~3× — in slow ROM every opcode fetch is
  8 mc, so once multiplies are cheap the LUT/OAM tail dominates. FastROM is
  the untouched lever.

**OAM: slot compaction + one 544-B VBlank DMA.** Visible sprites claim
consecutive shadow slots; culled sprites store NOTHING; the tail is parked
only up to the previous frame's watermark; hi-table bytes are re-armed each
frame and OR-ed per sprite (X8 + 32×32 size bit) — never carried across
frames. The whole shadow goes up as one GP-DMA in the same VBlank that
commits the floor's pose pointers/banks/origins (the shared-snapshot shape:
zero floor/sprite skew by construction).

**Distance tiers (5 apparent sizes on 2 hardware sizes).** OBSEL `$62` gives
the 16×16/32×32 pair; five disc CHR variants (diameters 10/12/14/18/22 px,
32×32 variants on fully-padded 4×4 name blocks — the phantom-quadrant
lesson) are selected by ONE row→tier size ladder (`sp_tier_nocull`, valid at
every row). Tier switches land exactly on the ladder boundaries (extent-measured
on the render; `-DSP_TIEROFF` collapses the ladder).

**Seam vs SCREEN edges (per-band cull — owner edge-exit fix).** The two
vertical band edges are NOT symmetric: band 1's bottom (`k→111`) and band 2's
top (`k→0`) are the SEAM; band 1's top and band 2's bottom (the near, big-token
edge) are the true SCREEN. An earlier single symmetric LUT (`$FF` for `k<9` or
`k>95`) guarded both, so a fully-visible follower was culled the instant its
LEADING edge neared a screen edge — a big band-2 token popped at `k=96` with its
box bottom still ~13 rows above the screen. The cull is now **per-band** in
`sp_project_band`: each band guards ONLY its seam-facing edge (band 1 culls
`k≥96`, band 2 `k≤8` — cutoffs from `MARGIN32` hi=95 / `MARGIN16` lo=9, per-tier
by k-segregation) and lets its screen edge slide off (hardware clips the OAM box
/ 9-bit X wraps → the follower stays until its TRAILING edge exits). The seam
guard band (PPU rows 111–112) still stays white-free; `-DSP_CULLOFF` disables
the per-band cull and the dead-zone probes bleed (the metric flips). `sp_tier_lut`
keeps its `$FF` marks only as the generator's core-visible depth window
(`d_lo/d_hi`). **Measured cost held** — the dp+`cpx` per-band test is cost-neutral
vs the old abs-long LUT read (per-sprite/visible-band 5,595 mc unchanged).

**Programmed inputs (the test pattern).** `$4200 = $81` (composed: NMI |
auto-joypad); after the VBlank commits the loop polls `$4212` bit 0 then
reads `$4218/$421A`. D-pad Left/Right = ±1 pose step per frame held (the
256-pose step-per-frame model), B = forward 2.0 px/f through the move256 8.8
accumulators. Tests drive BOTH ports deterministically: `set_input(1, …)`
persists across `frame_step` (which re-latches port 0 only — clear port 1
explicitly when done); trajectories are byte-identical across runs and equal
the integer turn-then-move model exactly.

**AI followers.** Waypoint loops (8 seeded asymmetric quads), steering =
sign of `cross(fwd, to_target)` quantized to ±1 heading step/frame (`fwd(h)
= (−sin,−cos)` rotates negative-cross-ward as h grows — mind the sense), a
180°-dot tie-break, movement at 1.0 px/f through per-entity accumulators.
World-space only: the AI never reads the matrix. The emulated state matches
the build-time integer simulation bit-for-bit at tick = loop-iteration
count; the generator PROVES bounded waypoint arrival for all 126 followers
before the ROM is ever built. **Measured: 6,074 mc per follower per frame —
the AI, not the projection, is the top budget term at high N** (staggering
AI across frames is the obvious knob; not taken without an owner ruling).

**The measured curve** (integrated build: scripted 2-port input + AI +
tiers; in-situ +1/+1 gate; `SP_N` is WRAM-poked at `$7E:C0C0`):

| N | integrated tick (% frame) | full-rate lockstep | alt-frame lockstep |
|---|---|---|---|
| 8 | 18% | yes | yes |
| 16 | 37% | yes | yes |
| 24 | 58% (31% headroom) | **yes — SHIP DEFAULT** | yes |
| 32 | 75% (10% headroom) | yes | yes |
| 48 | 103% | no | yes |
| 64 | 145% | no | **yes** |
| 96 | 220% | no | no |
| 128 | 300% | no | no |

The shipped `_sprites` build is `SPRITES=24 SP_INPUT=1` (largest N with
lockstep AND ≥15% modeled headroom; headroom model = tick/0.86 + 7k VBlank
commits vs 357,368 mc). Worst case all-N-visible-in-both-bands (no AI):
lockstep to 24, breaks at 32 — the instrument's linear fit predicted 25.8.

**Alternate-frame reprojection (`-DSP_ALTFRAME`, probe — NOT the default).**
Entity halves own fixed 64-entry OAM shadow regions; each frame one half
re-projects (recompacting inside its region against its own watermark) while
the other region holds 1-frame-old sprites; AI halves tick alternately with
full-velocity accumulate (same average speed, steering rate halves).
**Measured: doubles the integrated lockstep ceiling 32 → 64** while the
display holds 60 Hz — but every sprite (player markers included) updates at
30 Hz. That is an owner FEEL-TEST question; do not make it the default
without one.

**Per-scanline hardware ceiling (forensically measured).** ~30 32×32 sprites
sharing one row render only **8** full sprites = the 34-sliver/line limit ÷ 4
slivers per 32×32 OBJ (the 32-OBJ range limit never binds first at these
counts). NEW datum: an overloaded row damages ±16 NEIGHBOURING rows too —
OBJ boxes consume slivers across their full height even where transparent
(a sparse-row disc 14 rows above the cluster was eaten). Budget tier
boundaries accordingly.

**Debug/lab switches** (see `sprites_2p.inc` header): `SP_PIN`/`SP_H1/2`
(pinned stills), `SP_STATIC` (no AI), `SP_CYCLES`/`SP_CYCAI`/`SP_CYCINT`
(instrument ticks), `SP_VISWORLD/FARWORLD/TIERWORLD` (instrument worlds),
`SP_MIR` (debug position mirrors at `$7E:E400` — diagnostics only),
`SP_FORWARD`/`SP_CULLOFF`/`SP_TIEROFF` (the non-vacuity controls), and
`SP_HOLD` (`$7E:C0CC`, poked: freezes input+AI so a still is capturable).

## Why horizontal is the Mode-7 split axis

Mode 7 is a single BG layer whose camera latches per scanline, so a *vertical*
(left/right) Mode-7 split would need a mid-scanline camera change — which smears.
A Mode-7 dual-view must therefore be **horizontal** (top/bottom bands driven per
scanline by HDMA), which is exactly this primitive. The **vertical** left/right
dual-view is a *different* mechanism (two window-clipped tile-layer cameras) —
the separate `sf_split_v` primitive; see `docs/guides/split_v.md`, "Mode-7
vertical split is NOT feasible".

## Archetype coverage

| # | Archetype | Mechanism | v1 |
|---|-----------|-----------|-----|
| A | Mode-7 floor + tile HUD band | BGMODE + TM bands | **shipped** (the demo) |
| B | Mode-7 backdrop behind a tile playfield | BGMODE + TM/TS bands | shipped (same macros) |
| D | window / colour-math / brightness band (no mode change) | COLDATA / brightness / window band | **shipped** — COLDATA companion (default); brightness band via `-DBRIGHT_BAND` (`SF_SPLIT_BRIGHT`) |
| C-horiz (flat) | stacked per-band Mode-7 camera | M7A–D matrix bands (NON-REPEAT, DMAP `$03`) | **shipped** — the `split_h_matrix_demo` rail; guard satisfied by construction (see below) |
| C-horiz (perspective) | per-band *per-scanline* Mode-7 camera | engine per-scanline REPEAT-mode renderer + band-2 splice (`mode7_band_capture` / `mode7_band_splice`) | **shipped** — the `split_h_persp_demo` rail; guard PROVEN load-bearing via the `-DLATCH_VIOLATION` per-scanline negative control (see below) |
| C-horiz (perspective, independent world position) | per-band camera at a DIFFERENT world location (true 2-player pan) | + per-band ORIGIN splice: CH2 M7X/M7Y (`$211F`) + CH3 M7HOFS/M7VOFS (`$210D`), NON-REPEAT DMAP `$03`, mask `$6C` | **shipped** — the `split_h_persp_demo` rail (default); `-DSAME_CENTER` control; tests `C1`-`C3` (see below) |
| C-horiz (flat, THREE cameras) | THREE stacked per-band Mode-7 cameras, two seams | `sf_split_h_matrix_bands` with three `(count,M7A,M7B,M7C,M7D)` tuples (NON-REPEAT, DMAP `$03`, 2 channels, mask `$0C`) | **shipped** — the `split_h_persp3_demo` rail; `-DONE_CAM` control (see "Three stacked cameras" below) |

## Macro API

| macro / symbol | use |
|----------------|-----|
| `sf_split_h_bands reg_sel, table_label, effect_id, {c0,v0, c1,v1, ...}` | **N-band compiler** — emit an N-entry HDMA table from a `(count,value)` band list + arm it on an allocator channel. Appends the `$00` terminator; do NOT include it |
| `sf_split_h_2band reg_sel, top, bot, split, table_label, effect_id` | 2-band convenience (a thin wrapper over `sf_split_h_bands` — `{split,top, 1,bot}`); emit a 2-band HDMA table in RODATA + arm it |
| `sf_split_h_arm reg_sel, table_label, effect_id` | arm an existing HDMA table on an allocator channel (leaves the channel mask in `ENGINE_A0`) |
| `sf_split_h_off mask` | release the channel + clear its `NMI_HDMA_ENABLE` bit. For a matrix band pass the **2-channel mask** left in `ENGINE_A0` — it disarms both channels at once |
| `sf_split_h_matrix_bands table_ab, table_cd, effect_id, {c0,A0,B0,C0,D0, c1,…}` | **C-horiz bandlist compiler** — emit the two NON-REPEAT AB + CD tables from one `(count,M7A,M7B,M7C,M7D)` band list + arm the flat matrix band on 2 allocator channels (BBAD `$1B`/`$1D`, DMAP `$03`). Appends both `$00` terminators |
| `sf_split_h_matrix_band table_ab, table_cd, effect_id` | **C-horiz arm form** — arm the flat matrix band on two pre-authored NON-REPEAT tables (AB `[count,A_lo,A_hi,B_lo,B_hi,…,$00]` + CD `[count,C_lo,C_hi,D_lo,D_hi,…,$00]`). Fail-soft if <2 channels free; leaves the 2-channel mask in `ENGINE_A0` |
| `sf_split_h_persp_capture seam, save_ab, save_cd` | **C-horiz PERSPECTIVE capture** — call ONCE at boot after a camera-B `sf_mode7_tick`; capture the active AB/CD buffers' band-2 `[seam..L1)` into the caller's static WRAM save tables (`mode7_band_capture`). Each save table is `(L1-seam)*4` bytes |
| `sf_split_h_persp_splice seam, save_ab, save_cd` | **C-horiz PERSPECTIVE apply** — call EVERY frame AFTER `sf_mode7_tick`; re-apply the saved camera-B band over band-2 `[seam..L1)` (all four coefficients) via `mode7_band_splice`. Adds NO HDMA channel (still CH5\|CH6) |
| `SF_SPLIT_BGMODE / _TM / _TS / _COLDATA / _BRIGHT / _W12SEL / _WH0 / _WH1` | BBAD registry equates for `reg_sel` (v1 payloads — no guard) |
| `SF_SPLIT_M7A..M7D / _M7X / _M7Y` | matrix BBAD equates — the matrix band uses `_M7A` (`$1B`) + `_M7C` (`$1D`); flat mode is guard-safe by construction |

`sf_split_h_2band` must be called once per unique `table_label` (the identifier
becomes the RODATA label). To read a band's channel mask back for `sf_split_h_off`,
`lda ENGINE_A0` right after `sf_split_h_2band` / `sf_split_h_arm`.

## Caveats & limits

- **BG3 for the HUD needs manual base regs** (`$2109`/`$210C`) and a manual
  tilemap write — the engine `gfxmode`/`mset` path collides with Mode 7 (see VRAM
  budget). BG3 char base above word `$4000` requires no wrap; place it there.
- **Palette-group bits go in the tilemap-word HIGH byte** (`$1000` = group 4),
  not the low byte — a silent trap that renders your tiles in the floor palette.
- **~2 content modes per frame** — Mode 7 alone is the low 32 KB.
- **Matrix bands are backlog** and require the ValueLatch guard (above).

## Demo & tests

`make split_h_demo` (default) plus `build_split_h_variants.sh` for the `-D`
builds:

- **default** — the cockpit rail: a Mode-7 receding floor under a BG3 instrument
  band (frame + gauge lights + a fill bar), with a COLDATA colour band on the
  floor. P1 Left/Right drives the bar fill; P1 L/R shoulders spin the Mode-7
  camera (the split-under-load stress — a full matrix rebuild every frame).
- **`-DAUTODEMO`** — self-running: the bar sweeps on the frame counter and the
  camera spins continuously (the D5 load runs without a controller).
- **`-DNO_SPLIT`** — D1 non-vacuity: the split is compiled out → one full-screen
  Mode-7 floor, no tile band.
- **`-DNO_COLORBAND`** — D4 non-vacuity reference: the COLDATA band removed.
- **`-DFREEZE_BAR`** — D3 non-vacuity: the bar fill pinned constant.
- **`-DTHREEBAND`** — the **N-band compiler** (`sf_split_h_bands`): adds a 3-band
  `INIDISP` brightness split (full / half / dim) on top of the mode/TM split →
  THREE distinct horizontal brightness regions render.
- **`-DBRIGHT_BAND`** — archetype-D **brightness band** (`SF_SPLIT_BRIGHT`): top
  full `$0F`, bottom dimmed `$08`; the floor region renders dimmer than default.
- **`-DTOGGLE_SPLIT`** — `sf_split_h_off` **lifecycle**: P1 A cycles the mode/TM
  split armed → off (full-screen Mode 7) → re-armed.

Tests read the rendered framebuffer: D1 (top band = structured BG3 tiles, absent
under `-DNO_SPLIT`), D2 (bottom band = textured Mode-7 floor + clean seam), D3
(the bar fill responds to input, frozen under `-DFREEZE_BAR`), D4 (the COLDATA
band tints the floor vs `-DNO_COLORBAND`), D5 (the split holds under a per-frame
Mode-7 matrix rebuild — the floor is driven to spin and the seam/top band stay
clean; non-vacuous because the floor pixels must actually change), plus the
allocator-routing check (enable mask `$7C`). The sweep adds: the **N-band**
3-region brightness stair (`-DTHREEBAND`), the **brightness band** floor-dim vs
default (`-DBRIGHT_BAND`), the **`sf_split_h_off` lifecycle** present→gone→back
(`-DTOGGLE_SPLIT`), and a **structural HDMA-config check** (each channel is a
direct 1-byte HDMA: `DMAP=$00` + the expected `BBAD`; a per-frame-cost proxy).

### The C-horiz rail: `split_h_matrix_demo`

A dedicated rail (separate from the archetype-A cockpit demo above) for the
stacked-camera archetype. `make split_h_matrix_demo` plus
`build_split_h_matrix_variants.sh`:

- **default** — two stacked Mode-7 cameras of ONE checker world: top band
  scale `$0100` (8-px on-screen period), bottom band `$0040` (32-px), clean
  single-scanline seam. Armed via `sf_split_h_matrix_bands` (2 allocator
  channels, NON-REPEAT, DMAP `$03`).
- **`-DNO_MATRIX_SPLIT`** — M1 non-vacuity: the seam is compiled out, BOTH bands
  use camera A → one uniform camera fills the screen (the period-ratio assertion
  fails).
- **`-DAUTODEMO`** — self-running: the bottom band's camera scale sweeps on the
  frame counter (patched into WRAM HDMA tables each VBlank) to show it is live.

Tests (`test_split_h_matrix_demo.py`) read the rendered framebuffer: M1 (top ~8-px
vs bottom ~32-px period, ~4× ratio; absent under `-DNO_MATRIX_SPLIT`), M2 (exactly
one clean small→large seam transition, no smeared row), M3 (the shared checker
map + CHR at VRAM word `$0000`).

### The C-horiz PERSPECTIVE rail: `split_h_persp_demo`

The perspective sibling of `split_h_matrix_demo` — two genuinely-different
**per-scanline** perspective floors, one per band, at a clean single-scanline
seam. `make split_h_persp_demo` plus `build_split_h_persp_variants.sh`:

- **default** — top band = the LIVE engine perspective renderer (camera A) that
  AUTO-ROTATES; bottom band = a SECOND perspective camera (camera B) that
  ZOOM-LOOPS through 8 precomputed near-scale poses, spliced over band-2 every
  frame into the ACTIVE buffer. BOTH bands animate on their own driver. Uses the
  engine renderer (matrix on CH5\|CH6) + the band-2 matrix splice (CPU writes,
  no channel) + the per-band ORIGIN splice on CH2 (M7X/M7Y) and CH3
  (M7HOFS/M7VOFS) — `NMI_HDMA_ENABLE == $6C` (asserted by the structural test).
- **`-DFREEZE`** — hold camera A still (angle 0); camera B keeps zoom-looping. The
  P1 camera-B-independence build (only band-2 moves).
- **`-DHOLD_B`** — hold camera B at pose 0; camera A keeps auto-rotating. The P1
  camera-A-independence build (camera A is the sole driver).
- **`-DFREEZE -DHOLD_B` (`_still`)** — both cameras static, but the double buffer
  still flips + the splice re-applies every frame. The deterministic build for the
  seam / clean / structural tests AND the P3 temporal-stability POSITIVE build.
- **`-DFREEZE -DHOLD_B -DNO_SEAM` (`_stillnoseam`)** — camera A everywhere AND
  frozen: the deterministic camera-A baseline the P1 distinctness assertion
  compares camera B against, and P2's noseam control (the seam-pair metric must
  go quiet without the splice).
- **`-DNO_SEAM`** — P4 non-vacuity: the band-2 splice is compiled out, BOTH bands
  are camera A → a single continuous perspective floor. Also the cadence gate's
  non-vacuity control: solve-only per-frame work fits one frame, so this build
  runs a true-60 loop and the cadence metric passes on it.
- **`-DFIXED_BUFFER_SPLICE`** (with `-DFREEZE -DHOLD_B`, `_stillfixed`) — the P3
  NEGATIVE control: the splice targets the FIXED buffer 0 (ignoring `pv_buffer`),
  reinstating the 30 Hz double-buffer-desync flicker → band-2 alternates
  camera-B/camera-A across frames → the temporal-stability assertion FAILS.
- **`-DFREEZE -DHOLD_B -DLATCH_VIOLATION` (`_stilllatch`)** — P5 negative
  control: a code-side write-twice to a shared-latch register (`$210D`/`$210E`)
  during active display, while the per-scanline REPEAT-mode matrix HDMA streams
  → the frozen floor tears vs the frozen `still` build on the SAME jitter metric
  (frozen-vs-frozen, so the tear is attributable to the violation, not to scene
  motion). Proves the ValueLatch guard is load-bearing. (The free-running
  `-DLATCH_VIOLATION` build also exists as a demo; it is not P5's comparison
  side — camera A's rotation confounds the metric.)
- **`-DFREEZE -DHOLD_B -DSAME_CENTER` (`_stillsame`)** — C1 non-vacuity: camera
  B's whole ORIGIN (centre + scroll) folded onto camera A's via the same CH2/CH3
  channels → band-2 samples camera A's world region → the C1 "band-2 is a
  different world region" red signal MUST die.
- **`-DSKY_HORIZON` (`_sky`, `_stillsky`)** — the ITEM-B horizon knob: a TM
  (`$212C`) HDMA band on an allocator-chosen channel turns BG1 off for lines
  `0..SKY_H-1` so the `CGRAM[0]` backdrop shows as a sky band; default renders
  floor-to-edge.

Tests (`test_split_h_persp_demo.py`) read the rendered framebuffer (or, for the
cadence gate, the WRAM loop counters whose lockstep is the claim itself): P1
(bottom band is a distinct camera — texel period shifts >20% vs the camera-A
baseline; plus per-frame deterministic captures proving camera A animates while
B is held, and camera B animates while A is frozen), P2 (one clean
single-scanline seam-pair at exactly PPU 112 — the +7 screenshot-row offset
modeled — with the `stillnoseam` control quiet on the same metric), P3
**temporal stability** (band-2 byte-stable across 12 consecutive `frame_step`
frames while `pv_buffer` flips) + its `-DFIXED_BUFFER_SPLICE` negative control
(the SAME metric FAILS — the flicker returns), P4 (`-DNO_SEAM` single continuous
camera), P5 (`_stilllatch` tears the frozen floor: jitter >2× the frozen clean
build), C1/C2/C3 (independent world position: band-2 red vs band-1 cool +
`-DSAME_CENTER` control; the origin band-step crisp at exactly the seam; the
panned region temporally stable), B (`-DSKY_HORIZON` backdrop band above the
horizon vs floor-to-edge default), CAD (`test_cadence_true_60fps_in_situ` —
`pv_buffer` must flip every stepped frame; **xfail at HEAD**, the shipped loop
closes every 2nd frame per review M1, with the `-DNO_SEAM` control passing), and
STRUCTURAL (`NMI_HDMA_ENABLE == $6C` — CH5\|CH6 matrix + CH2\|CH3 origin;
heartbeat ≥110/120 as a display/NMI **liveness** check only, no loop-rate claim).

## Backlog / v2 follow-ups

- ~~**Archetype C-horiz PERSPECTIVE variant**~~ — **shipped** as the
  `split_h_persp_demo` rail (`sf_split_h_persp_capture` / `sf_split_h_persp_splice`
  over `mode7_band_capture` / `mode7_band_splice`). The per-scanline negative
  control (`-DLATCH_VIOLATION`, test P5) proved the ValueLatch guard load-bearing.
  See the archetype section + the perspective rail above.
- ~~**N-band tables**~~ — **shipped** as `sf_split_h_bands` (see the Macro API);
  `-DTHREEBAND` demonstrates a 3-region split.
- **Diagonal / animated bands** — a per-scanline table (not a 2-band step) for a
  sloped seam or a moving band boundary.
- **Per-frame cost gate (deferred).** A true per-frame *cycle* regression gate is
  deferred: the test harness has no cheap per-frame cycle counter, and
  instruction-stepping a whole frame under Mesen is far too slow for CI. The
  standing proxy is the **structural HDMA-config check**
  (`test_split_hdma_config_is_direct_1byte`): after arming it reads each split
  channel's `$4300+ch*$10` config and asserts `DMAP=$00` (A→B, absolute table,
  1 byte → 1 register) + the expected `BBAD`, and the `NMI_HDMA_ENABLE == $7C`
  mask — proving the recurring cost is exactly "NMI re-arm + the table" with no
  indirect mode, extra register, or hidden channel. A real cycle gate can be
  added when the harness grows a per-frame cycle read.
