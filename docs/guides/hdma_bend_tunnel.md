# HDMA bend / tunnel — per-scanline BG curve distortion

The brick behind `sf_bend` / `sf_tunnel` (in `lib/macros/sf_fx.inc`). For a
**normal** background (NOT Mode 7) that bends along a curve — an undulating
heat-haze wave, a forward-rolling tunnel, a static curved horizon — without
touching the BG art. One HDMA channel rewrites the layer's horizontal scroll
register every scanline from a curve LUT, so a flat BG warps for free during
display.

## The idea

`BGnHOFS` ($210D / $210F / $211D) sets a BG layer's horizontal scroll. Write it
**once per scanline** with a per-line offset and each row of the BG slides
independently. Feed those offsets from a curve and the layer bends along that
curve:

```
offset(scanline) = curve[(scanline + phase) & $FF] * amplitude / 128
```

- a **sine** curve → an undulating wave / heat-haze; advance `phase` every frame
  and the wave rolls downward into a forward **tunnel**.
- a **parabola** curve → a static **curved horizon**, symmetric about the screen
  centre (scanline 112): the top and bottom edges pull sideways, flat through
  the middle.

This is a normal-BG **raster** effect on a single HDMA channel — not Mode 7, no
affine matrix, no VRAM repurposing. It composites under sprites and other BG
layers like any normal background.

This is the classic SNES line-scroll raster effect: a per-scanline `BGnHOFS`
offset table fed by HDMA in transfer mode 2 (write-twice). The curved / barrel
horizon shape is a Mode-1 **normal-BG** line scroll from a precalculated per-line
offset table — distinct from a Mode 7 affine rotation (whole-plane spinning
rooms are Mode 7 and a different mechanism; this is normal-BG and stays cheap on
one HDMA channel). The animated sine ripple is the water-shimmer / heat-haze
shape — a small-amplitude sine (~1–4 px) scrolled per line.

## Two ways to use it

| | `sf_bend` (static) | `sf_tunnel` (animated) |
|---|---|---|
| Arms | a curve at a fixed phase | a curve + a per-frame roll speed |
| Per-frame work | **none** — built once at arm | `sf_bend_tick` rebuilds the table |
| Use for | curved horizon, frozen ripple | rolling tunnel, living heat-haze |
| Cost | one build at arm time, then free | ~the measured per-frame cost below |

```asm
; --- static curved horizon (curved/barrel line-scroll), no tick needed ---
sf_bend   #SF_CURVE_PARABOLA, #12        ; arm once; the table never changes

; --- animated sine tunnel (the marquee effect) ---
sf_tunnel #SF_CURVE_SINE, #14, #2        ; curve, amplitude (0-15 px), roll speed
; ... then every frame in the game loop:
    sf_bend_tick                         ; advance phase + rebuild the table
```

Curve selectors: `SF_CURVE_SINE`, `SF_CURVE_PARABOLA`, `SF_CURVE_HORIZON`
(the last is the v1.2 vertical-axis compression ramp — see **Vertical axis**
below). Amplitude is the peak displacement in pixels; the engine scales
`|curve| * amp / 128`, so amp 14 gives ~13–14 px of peak bend. Amplitude is a
full byte — values past 15 are allowed and give a steeper effect (amp 48 ≈ 47 px
of peak displacement); 0–15 is just the gentle range for a subtle H bend.

Both axes are supported (v1.2): the **horizontal** `BGnHOFS` line-scroll bend
(`sf_bend` / `sf_tunnel`, the classic curved horizon / wave / tunnel) and the
**vertical** `BGnVOFS` barrel/horizon row-squash (`sf_bend_v` / `sf_tunnel_v`).

### Selectable layer (BG1/2/3)

Both arm macros take an **optional** trailing layer arg (default BG1), so the
bend can ride any normal BG and leave the gameplay layer free to scroll:

```asm
sf_bend   #SF_CURVE_PARABOLA, #12, #2    ; bend BG2 (engine drives BG2HOFS $210F)
sf_tunnel #SF_CURVE_SINE, #14, #2, #3    ; roll BG3 (BG3HOFS $211D)
```

The engine derives the HDMA target register from the layer (1→`BG1HOFS` $0D,
2→$0F, 3→$11). Omit the arg and you get BG1, unchanged from v1.

### Panning the bent layer (compose a base scroll)

The per-scanline offset is `base_scroll + curve`, where `base_scroll` is read
each rebuild from the bent layer's `SHADOW_BGnHOFS` — the same shadow the
`scroll` macro writes. So you can **pan the bent layer** with the ordinary
`scroll` macro and the bend rides on top:

```asm
game_loop:
    scroll #1, CAM_X, #0                 ; move the base scroll (this layer)
    sf_bend_tick                         ; rebuild: line = CAM_X + curve
```

Drive `CAM_X` up/down and the whole bent stripe pattern pans left/right at your
speed while every scanline keeps its curve displacement. **Order matters:**
`scroll` *before* `sf_bend_tick` so the rebuild reads the new base. (A static
`sf_bend` reads the base only once at arm time — re-arm or use `sf_bend_tick`
with speed 0 if you want a static bend to track a moving base.)

### Reverse roll (negative speed)

The roll is a **wrapping 16-bit add** (`phase += speed`) sampled at
`(scanline + phase) & $FF`, so a **negative two's-complement speed** rolls the
opposite direction:

```asm
sf_tunnel #SF_CURVE_SINE, #14, #2        ; downward (forward) tunnel
sf_tunnel #SF_CURVE_SINE, #14, #$FFFE    ; #$FFFE = −2 → the REVERSE roll (upward)
sf_bend_phase #$FFFD                     ; or flip an armed tunnel's speed to −3
sf_bend_phase #2                          ; back to forward
```

`#0` still freezes the roll. The negative-speed convention is documented on the
`sf_tunnel` / `sf_bend_phase` macro headers as well.

### Controlling the roll

```asm
sf_bend_phase #0      ; freeze the roll (the table holds; pixels stop moving)
sf_bend_phase #3      ; resume / change the roll rate
sf_bend_off           ; release the HDMA channel (routes through hdma_off)
```

`sf_bend_phase #0` is the correct freeze: `sf_bend_tick` keeps running but the
phase no longer advances, so it rebuilds an identical table and the bend simply
holds. (Do not "freeze" by setting amplitude 0 — that flattens the bend instead
of pausing it.)

### The BG needs a vertical reference feature

The bend is a **horizontal** per-scanline displacement, so it is only visible on
BG content with vertical structure. Vertical stripes (the demo's BG) make it
obvious; a horizontally-uniform BG would bend invisibly. Author the BG so columns
matter. (The **vertical** axis is the mirror — it needs HORIZONTAL structure; see
below.)

## Vertical axis — the barrel / horizon row-squash (v1.2)

The same curve-LUT builder also drives the **vertical** scroll register
(`BGnVOFS`) instead of the horizontal one. A per-scanline VERTICAL offset
remaps which source row each screen scanline shows, so a flat horizontal-band
field **squashes**: bands bunch toward the horizon and spread away from it — the
vertical-shooter / pseudo-3D "barrel" look.

```asm
; --- static vertical horizon squash on BG1 (rows bunch toward the horizon) ---
sf_bend_v   #SF_CURVE_HORIZON, #48          ; curve, amplitude (steep: ~47 px)

; --- animated vertical squash that rolls (the V tunnel) ---
sf_tunnel_v #SF_CURVE_HORIZON, #48, #2      ; curve, amplitude, roll speed
; ... then every frame:
    sf_bend_tick                            ; the SAME shared tick (axis-agnostic)
```

`sf_bend_v` / `sf_tunnel_v` are thin wrappers — identical to `sf_bend` /
`sf_tunnel` except they target the layer's **`BGnVOFS`** register (the V register
is always the H register + 1: `BG1VOFS` $0E, `BG2VOFS` $10, `BG3VOFS` $12). They
take the same optional trailing `layer` arg. The shared services
`sf_bend_tick`, `sf_bend_phase`, and `sf_bend_off` are **axis-agnostic** — use
the same ones for H or V.

**The HORIZON curve.** `SF_CURVE_HORIZON` is a **one-sided monotonic** quadratic
ramp (0 at the top rising non-linearly to peak at the bottom). Its per-scanline
slope grows down the frame, so the band spacing **compresses** toward the bottom
— a real horizon, not the symmetric bow you get from `SF_CURVE_PARABOLA` (which
bends both ways about the centre and reads as a barrel/lens). `SINE` and
`PARABOLA` work on the V axis too, but `HORIZON` is the one that reads as a
receding ground plane.

**Vertical field scroll (the V mirror of the H pan).** The per-line offset is
`SHADOW_BGnVOFS + curve`, read each rebuild from the same shadow the `scroll`
macro writes. So a static `sf_bend_v` squash can have its field **panned
vertically** by the ordinary `scroll` macro — the authentic vertical-shooter
ground roll under a fixed horizon:

```asm
game_loop:
    scroll #1, #0, CAM_Y                     ; pan the field vertically
    sf_bend_tick                             ; rebuild: line = CAM_Y + curve
```

As with the H axis: `scroll` **before** `sf_bend_tick`, and a nonzero base
forces the optimized-refill path (the baked pointer-slide can't add a per-frame
base). A pure V roll with `SHADOW_BGnVOFS == 0` still gets the near-zero
pointer-slide.

**The BG needs a HORIZONTAL reference feature.** A vertical displacement is only
visible on content with horizontal structure — horizontal bands (the V demo's
BG) make it obvious; a vertically-uniform BG squashes invisibly.

**Clean-render constraint (important).** A per-line `BGnVOFS` remaps source rows
NON-uniformly, so some source rows are **repeated or skipped**. If the BG art has
fine vertical detail WITHIN a band, that repeat/skip shows as torn / aliased
rows. The kit's V demo avoids this by using **solid horizontal bands** (no
interior vertical detail) — the squash then shows only as the band EDGES moving,
and every rendered row is a clean full-width band (verified on the screenshot,
no garbage). Author V-axis fields the same way: solid bands or horizon-parallel
art whose rows are interchangeable. Steep amplitudes (large squash near the
bottom) can also pull rows from *below* the filled tilemap into view — fill the
field down to the screen bottom (28 rows) so the horizon has content to compress.

## Setup contract

1. `jsr hdma_alloc_init` once after `sf_engine_init` (reserves CH0/CH1; every kit
   HDMA effect needs it).
2. Upload the BG CHR + palette under the coldstart forced blank, bring the BG up
   with `gfxmode`, and `scroll` the layer to its world-zero position.
3. Arm with `sf_bend` (static) or `sf_tunnel` (animated). The first call
   allocates one HDMA channel (3–7), programs its `$43n0` registers
   (DMAP = mode 2 write-twice → `BGnHOFS`), and builds the per-scanline table in
   bank-$7E WRAM. The stock `nmi_handler.asm` re-arms `$420C` every VBlank — a
   kit ROM needs no custom VBlank code.
4. For `sf_tunnel`, call `sf_bend_tick` once per frame in the game loop.

The bend channel is allocated for a non-Mode-7 effect, so the NMI's
ownership-aware shadow commit leaves its `A1Tn` / `$43n0` hardware registers
alone (only the `$420C` re-arm applies) — the same convention the gradient /
parallax / wave effects use.

## Measured per-frame cost

Measured on Mesen2 (kit rule #1 — never estimated), via
`tests/bend_cycles_test.asm` (a frame-budget harness: the rebuild runs
back-to-back with NMI counting frames; cost = `frames * 357368 / rebuilds`
master clocks, where one NTSC frame = 1364 × 262 = 357,368 master clocks):

There are now **two** per-frame paths (`sf_bend_tick` picks one per frame):

| per `sf_bend_tick` | v1 (sep/rep byte loop) | **v1.1 refill (base scroll ≠ 0)** | **v1.1 pointer-slide (pure roll)** |
|---|---|---|---|
| Master clocks / frame | ~166,967 | **~73,847** | **~1,291** |
| ≈ fraction of one NTSC frame | ~46.7 % | **~20.7 %** | **~0.4 %** |
| ≈ CPU cycles | ~20,900 … ~27,800 | **~9,200 … ~12,300** | **~160 … ~215** |

`sf_bend` (static) pays the refill **once** at arm time and is then free.
`sf_tunnel` pays a per-frame cost: the **optimized refill** (~20.7 %) when a
horizontal base scroll is composed, or the **pointer-slide** (~0.4 %, **57×
cheaper**) for a pure roll with no base scroll. Both are measured on the
frame-budget harness (`bend_cycles_test.asm` = pure-roll slide,
`bend_cycles_refill_test.asm` = refill), never estimated.

**Path selection (automatic, per frame):** the tick reads the bent layer's
`SHADOW_BGnHOFS`; if it is **zero** it takes the near-zero pointer-slide; if it
is **nonzero** (you are `scroll`-ing the bent layer — E-HSCROLL) it falls back to
the refill, because a baked table can't add a per-frame-changing base to every
line. The two are mutually exclusive per frame, which is exactly right: you only
pay the refill when you are actually panning.

### The optimized refill (E-PERF)

The amplitude `sin()`/multiply is precomputed once per arm, not per line. The
remaining cost was the 224-line table *rebuild*; v1.1 cuts it three ways:

1. **Skeleton once.** The mode-2 `[count, lo, hi]` count byte (`[1]`) and the
   `$00` end marker never change frame-to-frame; they are written once at arm
   time. The per-frame refill rewrites *only* each entry's offset **word**.
2. **Signed 16-bit scaled LUT.** The precompute now emits the scaled curve as
   256 **signed 16-bit words** (already sign-extended), so each per-line write is
   a single 16-bit store — no `sep`/`rep` toggle and no per-line sign-extension
   branch in the hot loop. The LUT (512 B) lives in its own WRAM region
   (`HDMA_BEND_SCALED_W = $7E:E200`) because it no longer fits in the 1 KB
   channel slot after the live table.
3. **Single-width inner loop.** The loop is pure A16 with no per-iteration
   push/pull (`X` = scaled-LUT byte offset wrapping at 512, `Y` = table write
   offset). With hscroll active it adds exactly one 16-bit `adc base` per line.

### The pointer-slide fast-path (E-SLIDE)

For a pure roll the per-frame rebuild is avoided entirely. At arm time the engine
bakes an **oversized** table **once** — screen height (225) + one full curve
period (256) = 481 mode-2 `[1, lo, hi]` entries, `baked[j] = scaled_curve[j&$FF]`
— in a dedicated 1.5 KB WRAM region (`HDMA_BEND_BAKED = $7E:E400`, too big for
the 1 KB channel slot). Each frame the tick advances ONLY the channel's HDMA
**source pointer** (`A1Tn`, `$43n2/3`) by `3 × k` bytes, so scanline `s` reads
`baked[phase + s] = curve[(phase + s)&$FF]` — the roll phase-shifts by `k`
scanlines with **no table writes at all**. The count bytes are all `$01` (never
`$00`), so HDMA finds no early terminator inside the slideable window and stops
naturally at VBlank after 224 active lines. A **negative speed** wraps the phase
downward and slides the pointer the other way → the reverse roll, free.

The kit's NMI leaves this channel's `A1Tn` untouched (non-Mode-7-owned), so the
slide persists frame-to-frame from the game loop with no custom VBlank code. The
tick falls back to the refill the moment a base scroll is composed (a baked table
can't add a changing base per line), so you never lose the pan — you just pay for
it only while panning. For a static `sf_bend` none of this matters: it never
rebuilds and never slides.

## Under the hood

- Engine builder: `hdma_build_hofs_curve` + `hdma_update_hofs_curve` in
  `engine/hdma_engine.asm` — a curve-LUT generalization of the engine's
  sine-only `hdma_build_scanline_scroll`. Same `hdma_alloc`, `_hdma_table_addrs`,
  `$43n0` DMAP = $02 → BGn{H|V}OFS programming, write-twice `[1, lo, hi]`
  entries, end marker, and `_hdma_enable_channel`.
- **Axis (v1.2):** `HDMA_BEND_AXIS` (`$7E:E0B8`, 0 = H / 1 = V) is added to the
  BBAD register at the **single** computation site in `hdma_build_hofs_curve`:
  `BBAD = (layer-1)*2 + BG1HOFS_REG + axis` (the V register is always H+1). That
  is the **only** mechanical difference — the precompute, the optimized refill,
  and the pointer-slide fast-path are all reused **unchanged** for both axes (the
  table format is identical; only the target register and the base-scroll shadow
  differ). The refill/path-select read `SHADOW_BG{layer}HOFS` for H and
  `SHADOW_BG{layer}VOFS` for V (the shadow page interleaves H,V two bytes apart,
  so the read offset adds `axis*2`).
- Curve LUTs: `engine/hdma_bend_luts.inc` — a **generated** file (do not
  hand-edit; regenerate with `PYTHONPATH=. python3 tools/gen_bend_luts.py`). The
  sine curve is derived from the kit's existing 8.8 sine source-of-truth
  (`toolchain/math_lut.py` `generate_sin_lut`); the parabola is
  `generate_bend_parabola_lut`; the v1.2 horizon ramp is
  `generate_bend_horizon_lut` (a one-sided monotonic quadratic). All are signed
  bytes the engine scales by amplitude.
- State: `HDMA_BEND_*` at `$7E:E0B0` (curve, amp, layer, channel, **axis**); the
  animation phase/speed reuse the wave DP slots `$66/$68`; the signed-16-bit
  scaled-curve LUT (v1.1 E-PERF) lives at `HDMA_BEND_SCALED_W = $7E:E200`
  (512 B); the oversized baked roll table (v1.1 E-SLIDE) at
  `HDMA_BEND_BAKED = $7E:E400` (1.5 KB). The base scroll for a refill is read
  from `SHADOW_BG{layer}{H|V}OFS` (per axis) and held in a DP word (`$B2`, alias
  of the now-unused secondary-table pointer) across the inner loop.
- Tick path select: `hdma_update_hofs_curve` reads the armed axis's
  `SHADOW_BG{layer}{H|V}OFS`; zero → `_hdma_curve_pointer_slide` (advance `A1Tn`
  into `HDMA_BEND_BAKED`); nonzero → `_hdma_curve_fill_table` (the composed-base
  refill) + re-point `A1Tn` at the channel slot.

Demos + output-reading done-conditions (all read rendered pixels):
- `tests/bend_test.asm` / `test_bend.py` — the marquee sine tunnel (BG1): stripe
  x varies per scanline along the curve, and the pattern rolls between frames.
- `tests/bend_parabola_test.asm` / `test_bend_parabola.py` — the static
  curved-horizon parabola, symmetric about screen centre.
- `tests/bend_layer_test.asm` / `test_bend_layer.py` — E-LAYER: the bend on BG2.
- `tests/bend_hscroll_test.asm` / `test_bend_hscroll.py` — E-HSCROLL: the bent
  layer pans right then left while staying bent.
- `tests/bend_reverse_test.asm` / `test_bend_reverse.py` — E-DIR: a negative
  speed reverses the roll direction (opposite sign vs the positive-speed roll).
- `tests/bend_slide_test.asm` / `test_bend_slide.py` — E-SLIDE: the pure-roll
  pointer-slide fast-path rolls and reverses live (speed flips mid-run), and the
  slide cost (~0.4 %) vs refill cost (~20.7 %) are both measured.
- `tests/bend_cycles_test.asm` (pure-roll slide) + `bend_cycles_refill_test.asm`
  (refill) — the per-frame cost measurement harnesses.
- `tests/bend_v_test.asm` / `test_bend_v.py` — V-AXIS (v1.2): a horizontal-band
  field on BG1's `BGnVOFS` with `SF_CURVE_HORIZON`; the band SPACING compresses
  down the frame (cumulative drift from an even grid) and the squash rolls.
- `tests/bend_v_reverse_test.asm` — V-axis reverse roll (negative speed): the
  squash rolls the opposite vertical direction (asserted opposite-sign).
- `tests/bend_v_scroll_test.asm` — V-SCROLL: a static V squash whose field is
  panned vertically by the normal `scroll` macro while staying compressed.
```

## Composing a glowing horizon (DoD v1.3)

The *convincing* perspective horizon is as much a COLOR treatment as geometry.
The kit ships every brick for the documented SNES technique (per-scanline COLDATA
gradient + color math, the look behind every mode-7-style "ground fades to the
horizon" scene). This composition layers THREE already-shipped bricks on the
v1.2 V-bend geometry — **no new engine code**, pure macro assembly:

| Layer | Brick | What it contributes |
|---|---|---|
| Geometry | `sf_bend_v SF_CURVE_HORIZON` (+ `sf_bend_tick`) | the 1/z perspective ground row-squash, rolling toward the viewer |
| Color ramp + glow band | `sf_gradient_stops` | a per-scanline COLDATA ($2132) RGB ramp: dark sky → a **bright warm stop AT the horizon scanline** (the glow band) → ground tint. Screen-fixed (scanline-indexed), so it stays put while the ground rolls. |
| Atmospheric haze | `sf_colormath_on #1` (ADD) | the ground BG pixels tint toward each row's COLDATA color, so distant compressed rows fade into the horizon color (depth) |

**Why ADD:** the horizon glow is *light*, so additive color math washes the
distant ground toward the bright sky/horizon color — atmospheric haze. (A dark
horizon would use SUB.) Enable math on the **ground layer + backdrop**
(`layers = $21` = BG1 bit0 + backdrop bit5): the COLDATA add paints the sky onto
the dark backdrop AND hazes the ground; the HUD/sprite layers stay un-hazed.

**Channel allocation — arm GRADIENT FIRST (the integration gotcha).** The
gradient builder writes its three COLDATA tables at FIXED WRAM addresses
(`$C000/$C1C4/$C388`, the CH3-CH5 region) while `sf_bend_v` places its table by
allocated channel slot. Arm the gradient first → it claims CH3-CH5 (fixed
tables), and `sf_bend_v` then lands on CH6 (table `$CC00`, clear of the gradient
region). Arming the bend first would put its table in CH3's slot and the gradient
rebuild would stomp it. Verified allocation (read from the live ROM):

```
gradient  → CH3, CH4, CH5   COLDATA R/G/B, tables $C000 / $C1C4 / $C388
sf_bend_v → CH6             BG1VOFS, table $CC00   (no overlap)
color math → no HDMA channel (SHADOW_CGWSEL/CGADSUB, the NMI commits)
```

Total: 4 of 8 HDMA channels — comfortable alongside a HUD/parallax layer.

Macro sequence (set color math up first as shadow state, then arm gradient, then
the geometry):

```asm
sf_colormath_on #1, #$21          ; ADD on BG1 + backdrop (shadow; NMI commits)
sf_gradient_ease #2               ; ease-out → faster fade near the horizon = depth
sf_gradient_stops #STOP_WRAM, #5  ; sky → bright glow @horizon → ground (5 stops)
sf_gradient_phase #0              ; STATIC (the glow band is screen-fixed)
sf_gradient_update
sf_tunnel_v #SF_CURVE_HORIZON, #128, #2   ; rolling 1/z ground (lands on CH6)
; loop: sf_bend_tick  (+ sf_gradient_tick, a no-op while static)
```

The stop array is 6 bytes/stop (`scanline:16, r, g, b, pad`, intensities 0-31)
in bank-`$7E` WRAM; place a high-intensity stop at the horizon scanline for the
glow band. The multi-stop builder interpolates every adjacent pair (it is NOT a
2-stop fallback despite a stale comment in `_hdma_stops_fill_tables`), so the
bright middle stop genuinely produces the band.

**Transient-sky gap closed (vs v1.2):** the gradient + glow band are COLDATA
(screen-fixed by scanline), NOT part of the rolling BG, so they hold their screen
row while the ground rolls beneath them — exactly the receding-ground read.

**C-DEPTH note (deferred follow-up):** depth is approximated by the per-row
COLDATA *intensity* ramp (strongest tint toward the horizon). The true per-row
color-math *strength* ramp (HDMA on `$2131/$2130` — vary add↔sub↔half by row) is
the deferred `sf_colormath_hdma` enhancement; it is NOT needed for a convincing
result and is out of scope here.

Demo + output-reading done-condition:
- `tests/horizon_compose_test.asm` / `test_horizon_compose.py` — layers all three
  bricks. Asserts on rendered pixels: (a) the V-bend ground still compresses ≥3×
  (geometry intact, not clobbered); (b) the sky blue-channel ramps monotonically
  top→horizon; (c) the horizon-row region is measurably brighter than the rows
  above and below (the glow band); (d) a ground band near the horizon tints
  CLOSER (RGB distance) to the horizon color than a foreground band (haze); and
  the glow band stays at a fixed screen row while the ground rolls.
