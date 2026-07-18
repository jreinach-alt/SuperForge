# `sf_split_v` — vertical left/right window dual-view

A production guide for the vertical (left/right) dual-view split: two BG-layer
cameras of one 2D stage, clipped to the two halves of the screen by the PPU
window system. No mid-scanline register changes, no HDMA — the split is drawn
entirely by the PPU and costs essentially nothing per frame.

Rail: `templates/split_v_demo/` · macros: `lib/macros/sf_split_v.inc` ·
tests: `tests/test_split_v_demo.py` (D1–D5, all read the rendered framebuffer).

## Mechanism

Mode 1, BG1 + BG2 on the main screen, both showing the SAME stage:

- **BG1 = camera A**, scrolled to one viewpoint → shown on the **left** half.
- **BG2 = camera B**, scrolled to another viewpoint → shown on the **right** half.
- **Window 1** is the split edge. `W12SEL` masks BG1 *inside* the right band
  (BG1 → left only) and BG2 *outside* it (BG2 → right only); `TMW` enables the
  masking; `WH0/WH1 = seam/255`.

The window clips per-scanline in hardware, so once set the split is free. A
straight moving seam is one window-edge write per frame.

### The coloured seam (zero sprites)

The demo draws the visible seam bar with **no OBJ at all**: a second window
(window 2) is a thin band `[seam−hw, seam+hw]` that masks BG1 + BG2 + BG3, so
the **backdrop** (CGRAM 0) shows through as the seam colour. Combined with the
window-1 split per layer via OR logic:

| register | value | meaning |
|----------|-------|---------|
| `W12SEL` | `$BA` | BG1 = win1-inside \| win2-inside; BG2 = win1-outside \| win2-inside |
| `W34SEL` | `$08` | BG3 masked inside the band (so BG3 doesn't show in the seam) |
| `WBGLOG` | `$00` | all-OR (combine window 1 + window 2) |
| `TMW`    | `$07` | mask BG1 + BG2 + BG3 (`$17` to also window-clip OBJ) |
| `WH0/WH1`| `seam/255` | window 1 = the split |
| `WH2/WH3`| `seam−hw/seam+hw` | window 2 = the seam band |
| CGRAM 0  | seam colour | shown wherever all layers are masked |

Set CGRAM 0 with `sf_bg_color 0, 0, <bgr15>`.

## VRAM layout & the shared-CHR optimization

Two cameras of one world need the stage in VRAM **once**, not twice. The demo
uploads the stage to BG1's CHR (word `$2000`) + tilemap (`$5800`), then points
BG2 at the SAME base:

```
    lda #$58 : sta $2108    ; BG2SC   = BG1SC  (shared tilemap $5800)
    lda #$22 : sta $210B    ; BG12NBA = BG1 CHR $2000 for BOTH BG1 and BG2
```

(The engine's `gfxmode #1` default puts BG2 at `$5C00`/`$4000`; override it
AFTER `gfxmode` — the NMI never re-commits `BG2SC`/`BG12NBA`, so it holds.) Both
cameras now read one VRAM copy and differ only by scroll. This **halves** the
stage's VRAM and, crucially, means a scrolling/streaming world updates **one**
tilemap, not two. It also frees BG2's old CHR/map regions (~8 KB) for a richer
tileset or more OBJ CHR.

If the two halves ever need genuinely different content (not just different
viewpoints of one world), drop the override and give BG1/BG2 separate bases.

## Cost

The window clipping is PPU hardware — **0 incremental cycles** for a static
split. Per frame the demo writes only:

- two BG scroll commits (camera A + camera B), and
- for a moving seam, `sf_split_v_move` = **4 byte writes** (`WH0`, `WH1`,
  `WH2`, `WH3`) to the shadows.

That's well under 100 cycles against the ~28–37 k-cycle frame budget (<0.3%). A
split scene runs at the same locked 60 fps as a non-split one; what you *spend*
is architectural, not time: BG1 + BG2 are consumed by the two views (leaving
BG3 2bpp for a HUD and OBJ for actors), and VRAM holds one shared stage.

## Macro API

| macro | use |
|-------|-----|
| `sf_split_v seam, obj_clip` | plain split (window 1 only), no seam bar |
| `sf_split_v_colorseam seam, half_width, obj_clip` | split + coloured backdrop seam bar (setup; `seam`/`half_width` are bare literals) |
| `sf_split_v_move seam, half_width` | per-frame: recompute WH0 + the band from the live `seam` (memory symbol) |
| `sf_split_v_seam seam` | per-frame: move just the window-1 edge (plain split) |
| `sf_split_v_diagonal base, slope, half_width, obj_clip` | a DIAGONAL coloured seam — WH0/WH2/WH3 HDMA'd per scanline so the split + band slant (`seam[s] = base + s·slope`, 8.8) |
| `sf_split_v_bevel` | **seamless** setup (once): BG3 beveled divider bar (tiles/palette/tilemap) + the always-on centre window recipe (see below) |
| `sf_split_v_spread mid, spread, cam_a, cam_b` | **seamless** per-frame: diverge the cameras (`cam_a=mid−spread`, `cam_b=mid+spread`), ramp the divider band (`hw=spread>>4`), scroll BG1/BG2 |
| `sf_split_v_cameras cam_a, cam_b` | scroll BG1/BG2 to the two cameras |
| `sf_split_v_off` | collapse to a single full-screen view |

`obj_clip = 1` also confines OBJ to the left half (see the caveat below).

### Diagonal seam (HDMA)

For a slanted seam, the window edges are driven per scanline by HDMA: the engine
builder **`hdma_build_split_diag`** (in `engine/hdma_engine.asm`) allocates 3 HDMA
channels and builds per-scanline tables for WH0 (split), WH2 and WH3 (band) from
`seam[s] = base + (s·slope)` (8.8 fixed). `sf_split_v_diagonal` wraps it: it sets
the same colour-seam window recipe, then arms the HDMA. The caller must
`.include "hdma_alloc.asm"` + `"hdma_engine.asm"` and call `hdma_alloc_init` once
(the allocator), and link a 64 KB cfg (the HDMA engine pushes the ROM over 32 KB).
The `-DDIAGONAL` demo variant shows it. Cost: 3 HDMA channels + a one-time
225-line×3 table build at setup; per-frame cost is still zero (the tables are
static). The scratch reuses the iris DP-shadow block — the diagonal seam and the
iris wipe are mutually exclusive.

## Caveats & limits

- **OBJ window is a single global window.** You can confine *all* sprites to one
  half, but you cannot independently clip left-sprites-to-left AND
  right-sprites-to-right with one window. Manage per-sprite visibility for
  two-sided actors. (A sprite straddling the seam is clipped mid-sprite; a
  sprite fully in the masked half vanishes — both are the OBJ window at work,
  demonstrated by the `-DOBJ_CLIP` D4 test.)
- **Per view = one BG layer.** Each camera is a single 4bpp tile layer, so no
  per-view parallax (you have one spare layer, BG3 2bpp, total).
- **32 sprites/scanline** is the usual hard cap, shared across both halves.
- **Mode 7 vertical split is NOT feasible.** Mode 7 is a single BG layer whose
  camera latches per scanline; a left/right split would need a mid-scanline
  camera change, which smears. A Mode-7 dual-view must be **horizontal**
  (top/bottom bands driven per scanline by HDMA on the matrix) — that is the
  separate `sf_split_h` primitive, not this one. You also can't mix a Mode-7
  half and a tile half side-by-side (the video mode is global per scanline).

## Demo & tests

`make split_v_demo` (default) plus `build_split_v_variants.sh` for the `-D`
builds:

- **default** — interactive: P1 D-pad pans the left camera, P2 (port 1) the
  right, P1 shoulders move the seam (centred by default).
- **`-DAUTODEMO`** — self-running: seam fixed at centre (50/50), the two cameras
  pan independently (the classic split-screen look).
- **`-DOBJ_CLIP`** — per-half OBJ clipping (D4).
- **`-DNO_WINDOW`** — negative control: one full-screen camera, no seam (D5).

Tests read the horizon line (sky→terrain transition per column; the white seam
columns are excluded) and prove: left half == camera A exactly (zero bleed),
right half == a different camera, a sharp seam step, independent per-camera
input, a swept seam, the OBJ clip, and the `-DNO_WINDOW` collapse.

## The SEAMLESS split (always-on window + continuous divergence)

The colour-seam recipe above (and the diagonal HDMA one) turn the split ON and
OFF: `sf_window_off` ↔ re-arm. That is a **discrete pop** — the seam bar snaps
into existence and, because a masked band steals `2·hw` px of content the instant
it appears, everything visibly shifts over by the line width. For a *seamless*
separation (fighters drifting apart with no visible transition), rearchitect from
the effect backward:

- **The centre window is ALWAYS on** — never toggled, never forced-blanked.
- **Separation is a CONTINUOUS camera divergence**, not a state: `cam_a = mid −
  spread`, `cam_b = mid + spread`, both cameras of ONE stage. At `spread = 0` the
  two halves are pixel-identical, so the ever-present seam is **invisible**; as
  `spread` grows the halves diverge and the seam smoothly emerges as a real
  content discontinuity (no pop, no shift, no redraw).
- **The divider draws itself from zero width.** Band half-width `hw = spread>>4`
  is ZERO at merge (no content masked → no width stolen) and grows only after the
  halves part. The divider is a **VERTICAL BEVELED bar on BG3** (highlight core /
  mid / shadow edges) that window 2 reveals only inside the band. Vertical, not
  diagonal: an angled divider encodes the verticality (airborne vs grounded) a
  ground game does not have — use `sf_split_v_diagonal` for a game with flight.

Two macros implement it. `sf_split_v_bevel` (setup, once) uploads the beveled bar
to BG3 CHR word `$7000` (NOT the `gfxmode` default `$A000` — VRAM word addresses
are 15-bit, so `$A000` wraps onto BG1's CHR), sets the bevel palette, writes the
bar into the BG3 tilemap under forced blank (then clears BG3's dirty bit so the
NMI never re-DMAs it — three 2 KB tilemap DMAs overrun VBlank and truncate the
last one), pins BG3 scroll to 0, and installs the always-on window recipe (window
1 splits at centre; window 2 reveals the bar only inside its band; OBJ is NOT
masked, so actors render across both halves). `sf_split_v_spread mid, spread,
cam_a, cam_b` (per frame) diverges the cameras, ramps the band from `spread`, and
scrolls BG1/BG2 — it writes `cam_a`/`cam_b` back so you can place per-half actors
(`(worldX − cam_a) & $FF` in the left half, `(worldX − cam_b) & $FF` in the
right). The caller only has to ease `spread`.

**Side-switching.** `cam_a` frames the LEFT half, `cam_b` the RIGHT, so the actor
you place against `cam_a` must be the one currently to the left (smaller world X).
Because `sf_split_v_spread` is symmetric in `mid`/`spread`, the split handles a
full SIDE-SWAP correctly **as long as the caller re-picks which actor goes with
which camera by position each frame** — when the two cross, the (formerly) left
actor simply moves into the right half and vice-versa, and since `dx → 0` at the
crossing (`spread = 0`, merged) the swap happens under a seamless single view with
no seam. `split_v_fight` does exactly this: each frame it compares the two fighter
X's, draws the leftmost against `cam_a` and the rightmost against `cam_b` (each
keeping its colour), and its fighters are independently arena-clamped so they may
walk through each other and switch sides. `test_s6` (a crossed static build) and
`test_s7` (the autodemo marching them through each other) prove the swap follows
seamlessly. If instead you bind an actor to a fixed camera, a crossing does not
break the split (still seamless, uncorrupted) but the framing inverts — each half
frames the opposite side and the actors slide to the outer screen edges.

### Composition example — `split_v_fight` (seamless distance-driven split)

`templates/split_v_fight/` composes the seamless core into a self-directing
camera: two ground fighters (P1/P2) on the shared stage, whose view separates
SEAMLESSLY as they part and re-merges as they close. There is **no state machine
and no `sf_window_off` toggle** — `spread` is EASED (rate-limited at
`SPR_STEP`/frame) toward `clamp((dx − MERGE_DX)/2, 0, SPREAD_MAX)`, where `dx` is
the fighter distance. Below `MERGE_DX` the target is 0 (fully merged, seamless
single view); above it the divergence tracks the value that keeps each fighter
centred in its half. Fighters are OBJ; each frame the rail draws the leftmost (by
world X) against `cam_a` and the rightmost against `cam_b` — each keeping its
colour — so the fighters can **cross and swap sides** (independently arena-clamped,
they may walk through each other). Ground-level only, no verticality. `-DAUTODEMO`
self-runs a CROSS-OVER (the fighters march through each other wall-to-wall,
swapping sides, with a dwell at each wall); static `-DHOLD=n` builds freeze the
fighters symmetric at ±n px so `spread` settles to a fixed point (race-free
framebuffer proofs; a NEGATIVE `n` freezes a crossed/swapped state),
`-DNOWIN=1 -DHOLD=20` is the no-split reference. Tests
(`tests/test_split_v_fight.py`, all framebuffer): **S1** the merged frame is
pixel-identical to the no-split reference (non-vacuous: the split frame differs by
thousands of px); **S2** the beveled divider is absent at merge and present +
full-height when split; **S3** fighters track their halves; **S4** the autodemo
reaches both merged and split with the divider BOUNDED and re-merging; **S5** the
independent clamp keeps both fighters in the arena; **S6** a crossed build frames
correctly (blue left, red right — the swap); **S7** the autodemo marches them
through each other and the crossover is a seamless merge.

## Backlog / v2 follow-ups

- ~~Diagonal HDMA seam~~ — **DONE** (`sf_split_v_diagonal` / `hdma_build_split_diag`,
  the `-DDIAGONAL` demo, D6 tests). Remaining: an **ANIMATED** slant (rebuild the
  3 tables per frame to sweep the angle) — the current builder is static.
- **Automated cost-regression test.** Deferred: the test harness exposes no cheap
  per-frame CPU-cycle counter, and instruction-stepping a whole frame is too slow
  for CI. The cost is deterministic (the register writes above) and spec-verified.
- **Colour-math seam** (a translucent/tinted seam via the colour window +
  `sf_colormath`) instead of a solid backdrop bar.
- **`sf_split_h`** (horizontal raster bands, incl. the Mode-7 top/bottom
  dual-view) is the next split primitive — a separate sprint.
