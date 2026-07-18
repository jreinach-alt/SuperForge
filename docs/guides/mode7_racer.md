# The Mode 7 racing rail (`templates/racer/`)

The genre rail for kart-style racers on the Mode 7 perspective floor: a
closed-circuit track, a steerable camera with accelerate/coast physics, a
fixed-screen vehicle sprite, and a sprite-based HUD. Build with `make racer`,
verify with `tests/test_racer.py`. This guide explains the architecture, the
knobs, and the adaptation paths.

## Architecture — who commits what (3 lines)

1. **Main thread** (your game loop): update camera state (`sf_mode7_cam`),
   then `sf_mode7_tick` rebuilds the per-scanline HDMA matrix tables when the
   angle/perspective changed (~10k cycles) and re-anchors the rotation origin
   when only the position changed (cheap).
2. **The stock engine NMI** commits everything during VBlank: M7SEL/M7X/M7Y,
   the BG1 scroll shadows, the HDMA channel configs (CH5 = matrix A/B,
   CH6 = matrix C/D), and the OAM DMA. A rail ROM has **no custom VBlank
   code**.
3. **HDMA itself** feeds `$211B-$211E` per scanline during active display —
   zero CPU cost. That per-scanline matrix rewrite *is* the perspective.

## The perspective trapezoid (`sf_mode7_perspective l0, l1, s0, s1, sh, interp, wrap`)

The renderer maps a trapezoid of the map onto the screen band `l0..l1`. Each
parameter, with the two worked value sets:

| Param | Meaning | Racing (the racer rail) | Flight (`sf_mode7_on` default) |
|---|---|---|---|
| `l0` | horizon scanline — the floor starts here | 96 | 45 |
| `l1` | bottom scanline | 224 | 224 |
| `s0` | far-scale: texel step per pixel at `l0`. Bigger = the far row spans more map = stronger compression at the horizon | 192 | 436 |
| `s1` | near-scale: texel step at `l1`. Smaller = tighter, lower camera | 24 | 77 |
| `sh` | vertical texel height (0 = derive from horizontal). Nonzero squashes vertical relative to horizontal — the road-like aspect | 16 | 0 |
| `interp` | per-scanline interpolation factor (1/2/4) — the rebuild computes every Nth line and lerps between; 2 is the proven cost/quality point | 2 | 2 |
| `wrap` | 1 = the 1024px map tiles infinitely; 0 = clamps | 1 | 1 |

Pair each set with its rotation anchor: `sf_mode7_focus 192` (racing — the
camera position maps to scanline 192's screen center, low in the view, where
the kart sprite sits) or `sf_mode7_focus 168` (flight). The racing set reads
as "standing on the road"; the flight set as "looking down from altitude".
Confidence: both sets are **engine-verified** (the racing set is the
`mode7_test` run-gate's; the flight set is the renderer's default).

Above `l0` the same Mode 7 layer keeps rendering with whatever matrix the
table's head band holds — a stretched smear of the map. That is **expected**
with the engine's CH5/CH6-only HDMA scope; a real sky needs the engine's
per-scanline mode-split (Mode 1 band above, Mode 7 floor below), which is
also the text-HUD path, and is out of rail scope. The racer's HUD is sprites
for the same reason: **BG3 does not exist in Mode 7** — the mode has exactly
one BG layer plus OBJ, so `sf_text`/`print` have nothing to draw on.

## The camera integration pattern (the racer's per-frame core)

Heading + speed -> position, transcribed from the proven racing-camera
lineage (`templates/racer/main.asm`, "integrate" section):

```asm
    lda R_ANGLE
    and #$00FF
    jsr sincos              ; sina/cosa <- signed 8.8 (engine mode7_math)

    sep #$10                ; smul16 contract: .a16 .i8, DP=0, DB=0
    .i8
    lda a:sina
    sta a:math_a
    lda R_SPEED             ; 8.8 speed
    sta a:math_b
    jsr smul16              ; math_p = sina x speed (s32, 16.16)
    ; pos -= step: 16.16 subtract, then wrap the integer word
    lda R_POSX + 0
    sec
    sbc a:math_p + 0
    sta R_POSX + 0
    lda R_POSX + 2
    sbc a:math_p + 2
    and #$03FF              ; wrap to the 1024px map
    sta R_POSX + 2
    ; ... same with cosa for R_POSY ...
    rep #$30
    .a16
    .i16
    sf_mode7_cam R_POSX + 2, R_POSY + 2, R_ANGLE
    sf_mode7_tick
```

Three load-bearing details:

- **Forward subtracts.** The renderer's convention: negative sin/cos steps
  advance "toward the horizon". Adding instead reverses the world.
- **The position is 16.16** (fraction word + integer word) so sub-pixel speed
  accumulates; only the integer word goes to `sf_mode7_cam` (which re-zeroes
  the engine-side fraction — your DP copy owns the accumulation).
- **The wrap is `and #$03FF` on the integer word only** — with `wrap=1` the
  rendered map tiles seamlessly, so position space is the torus 0..1023.

Steering is a plain `inc`/`dec` + `and #$00FF` on the angle byte:
`sf_mode7_cam` flags the expensive matrix rebuild **only when the angle
changed**, so driving straight stays on the cheap path.

## The track-asset pipeline

```
templates/racer/assets/make_track.py        (author: 1024x1024 PNG)
        |  toolchain/mode7_map_converter.py::convert_map_png
        |     (8x8 tile split + dedup -> tileset, 128x128 tilemap, palette)
        |  toolchain/mode7_assets.py::interleave_mode7_data
        v     (even bytes = tilemap, odd bytes = 8bpp tiles — the native
               Mode 7 VRAM word layout)
track_map.bin (32,768 B, committed)  +  track_palette.inc (CGRAM words)
        v
.segment "BANK1" / .incbin  ->  sf_mode7_load_map track_map, #$8000
```

Constraints the converter enforces: **max 256 unique 8x8 tiles, max 256
colors**. The racer's track stays tiny (7 tiles / 7 colors) by authoring
solid-color tiles on the 128x128-tile grid — checker variation between two
greens / two grays gives the motion cue for free. Regenerate with
`PYTHONPATH=. python3 templates/racer/assets/make_track.py` from a kit root
(needs `toolchain/`); the blob fills BANK1 of the 64KB image, so the racer
has its own explicit Makefile rule with `lorom_64k.cfg` (the `mode7_test`
rule is the precedent).

One converter consequence worth knowing: **CGRAM color 0 is whatever color
the converter sees first** (scan order from tile 0,0). With `wrap=1` the
floor always covers the screen so color 0 barely shows, but if you switch to
`wrap=0`/transparent-out-of-map, design the top-left of your PNG with that
in mind.

## The vehicle sprite (OBJ over Mode 7)

OBJ rendering is mode-independent — sprites composite over the Mode 7 floor
exactly as over any BG. Two gotchas the template bakes in:

- **The map owns VRAM words `$0000-$3FFF`**, so the OBJ name base must move
  out of it: `OBSEL = $62` (name base word `$4000`, size pair 16x16/32x32),
  and the CHR uploads at word `$4000` (`sf_load_obj_chr 1024, ...` — tile
  1024 x 16 words = word `$4000`; OAM tile numbers stay 0.. relative to the
  base).
- **`SHADOW_TM` needs the OBJ bit before `sf_mode7_on`** — `mode7_init`
  preserves only bit 4 (OBJ) and ORs in BG1. Forget it and the floor renders
  with no sprites.

The kart itself is a fixed-screen 32x32 OBJ near bottom-center (the world
moves under it — the classic kart-racer camera), with a lean frame on steer
and H-flip for the opposite bank. The HUD speed bar is six 16x16-small
sprites carrying 8x8 tick graphics.

## Adaptation paths

- **Different track**: edit `make_track.py`'s `tile_color()` (any closed
  circuit drawn on the 128x128 grid works), regenerate, rebuild. Keep tiles
  ≤256 / colors ≤256; solid-tile authoring keeps you far from both walls.
- **Flight-camera variant**: swap the perspective call to the flight set
  (`45, 224, 436, 77, 0, 2, 1` + `sf_mode7_focus 168`), drop the throttle
  for free-flight controls — `mode7_test`'s steering plus a constant speed
  is already an airship. The integration pattern is identical.
- **AI karts / track objects on the floor**: needs world->screen sprite
  projection — the documented method (not shipped rail code) is in
  [`mode7_sprite_projection.md`](mode7_sprite_projection.md).
- **Speed/feel**: `ACCEL`, `DECEL`, `SPEED_CAP` (8.8) at the top of
  `main.asm`, all `.ifndef`-overridable. The perspective knobs above change
  the camera character; `sh` is the one to touch for road aspect.

## Streaming worlds (>1024x1024): not a kit rail

The kit's Mode 7 rail is a **single 128x128-tile map with wrap on** — the
whole world lives in VRAM at once, and that is the honest scope. Bigger
worlds are a proven technique in the parent engine lineage (a 4096x4096
racer streamed at 48 px/frame) but the kit does not ship the surface, so
treat this as the adaptation map, not a recipe:

- **The architecture that worked**: keep the full map as a flat ROM tilemap
  (bank-per-64-rows addressing), track the camera's tile position per frame,
  and stream the leading edge — the rows/columns entering the 128x128 VRAM
  window — through WRAM staging buffers that a VBlank handler DMAs into
  VRAM. CPU decompression is avoided entirely; flat ROM reads feed the
  buffers.
- **Landmine 1 — position space**: camera/actor coordinates live in the
  full world space (e.g. 0..4095), while the VRAM tilemap stays 128x128 and
  the PPU samples it modulo 1024px. Every consumer of a coordinate must
  know which space it is in; mixing them corrupts silently.
- **Landmine 2 — VRAM-wrapped buffer writes**: Mode 7 reads tiles at
  `(row % 128, col % 128)`, so a streamed row/column must be written into
  its staging buffer at the **wrapped** position (`world_coord & $7F`), not
  sequentially — and the per-frame streaming clamp must cover the maximum
  tiles/frame at top speed, or skipped columns leave stale strips of a
  previous map region on screen.

Both landmines are documented incidents in the parent lineage, not theory.
Porting the surface means bringing over the row/col staging buffers, the
VBlank DMA dispatch, and the flat-ROM addressing macro — deferred until a
project actually needs it. (Confidence: **engine-verified in the parent
lineage**; the kit ships no streaming code.)
