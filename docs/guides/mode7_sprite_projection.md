# Projecting sprites onto the Mode 7 floor (world → screen)

> **Static-affine rotating floor? Use the TRANSPOSE, not this perspective
> method.** This guide documents the **perspective-floor** projection (the
> per-scanline HDMA road/racer view). For a rail with a **uniform static-affine**
> rotating floor (the boss / `m7_dungeon` / `m7_oshoot` lineage), the world→screen
> map is the **inverse of the forward matrix = its TRANSPOSE** at scale 1.0:
> `sx=((dx·A+dy·C)>>8)+128, sy=((dx·B+dy·D)>>8)+112`. The right reference is
> `templates/m7_dungeon/main.asm` `draw_enemies` (and `templates/m7_oshoot/main.asm`
> `draw_bullets`) — a working, rendered-floor-tested transpose projection. Using
> the forward matrix `(A,B)/(C,D)` is the swim-onto-walls bug those rails' `-D`
> non-vacuity controls reproduce.

How to place an OBJ sprite (an AI kart, a pickup, a shadow) so it sits
visually anchored to a Mode 7 ground-plane position while the camera moves
and rotates. This documents the **method** — solved, debugged and verified
on the engine lineage this kit's renderer is ported from (worked
implementation: parent lineage; kit-side code: compose on request — no
projection code ships with the rail).

Confidence tiers used below, per AGENTS.md:

- **engine-verified (parent lineage)** — the method and its failure modes
  were implemented, measured, and shipped against this exact renderer
  algorithm in the parent engine; the numbers in the worked examples come
  from there.
- **verified here** — the kit-side WRAM table layout and symbols were read
  from this repo's `engine/mode7_hdma.asm` / `engine/engine_state.inc` and
  cross-checked against the `mode7_test` run-gate, which asserts on those
  tables.
- **derive per config** — anything depending on the active perspective
  parameter set. Do not copy constants; re-derive or use the empirical
  method.

## 1. The Mode 7 forward transform (screen → world)

The PPU computes, per scanline V (with the matrix HDMA rewriting A/B/C/D
every line), a world texel for each screen pixel H. In the renderer's
center-anchored form (engine-verified, parent lineage):

```
world_x = (A·(H − 128) + B·(V − anchor_y)) / 256 + M7X
world_y = (C·(H − 128) + D·(V − anchor_y)) / 256 + M7Y
```

- `A,B,C,D` — the per-scanline matrix values, 8.8 signed.
- `M7X, M7Y` — the rotation origin. In this kit the engine NMI commits them
  from the shadows `M7_PV_NMI_M7X` / `M7_PV_NMI_M7Y` (`$7E:01F0` / `$01F2`,
  **verified here** — `engine_state.inc`), which `pv_set_origin` derives
  from the camera position and the focus scanline.
- The screen anchors (the `−128`, and `anchor_y`) depend on how
  `pv_set_origin` programs the scroll registers for the active focus.
  **Derive per config**: validate your anchors by computing `world_x` at
  screen center on the focus scanline and checking it equals the camera
  position — if it doesn't, your anchor convention is off, fix that before
  touching anything else.

Everything below is inverting this transform: given a world position, find
the screen pixel (H, V).

## 2. screen_y first — and why analytical formulas betray you

**screen_y must be right before screen_x can work.** The H equations read
the matrix at scanline V; a wrong V reads the wrong A/B/C/D and every
correct H formula then fails. (engine-verified, parent lineage: a
17-scanline screen_y error burned hours pointing suspicion at three
successive — correct — screen_x formulas.)

The depth↔scanline relationship is **not** the textbook pinhole projection.
This renderer linearizes a *reciprocal* curve and then maps it through a
LUT: it computes `ZR0 = 2^21/s0`, `ZR1 = 2^21/s1`, lerps
`pv_zr(V) = ZR0 + (V − l0)·zr_inc` per scanline, and converts back through
`pv_ztable[pv_zr >> 4]` (**verified here** — `mode7_hdma.asm` step 4a and
the per-line emit). Consequences:

- A constant focal length (`screen_x = 128 + dx·D/depth`) diverges with
  depth — the effective D varies (parent lineage measured it sliding from
  ~165 at far depth to ~50 up close).
- `depth ∝ 1/(V − horizon)` is also wrong: in the parent derivation the
  actual relation was `depth(V) = K·(224 − V) / pv_zr(V)` — depth depends
  on **both** factors, and that V-dependent numerator is exactly what the
  naive formula drops. Solving that for V gives a closed form *for that
  parameter set*; with this kit's LUT step in the path, treat any closed
  form as **derive per config** and validate it empirically before trusting
  it.

When in doubt — or on any new parameter set — skip the analytics and use
the **empirical scanline search** (section 5), which is also how the parent
bug was found in seconds after hours of formula work.

## 3. The core principle: read the tables the renderer actually built

Never reconstruct A/B/C/D from theory, the sine LUT, or the Z-table —
reconstruction drifts from the hardware by interpolation and edge cases.
The renderer already wrote the exact per-scanline values HDMA will feed the
PPU; **read those**.

Kit-side layout (**verified here**, `engine/mode7_hdma.asm` + the
`mode7_test` run-gate which asserts on these addresses):

```
pv_hdma_ab0 = $7E:A000   A/B data, buffer 0      pv_hdma_ab1 = $7E:A900
pv_hdma_cd0 = $7E:A400   C/D data, buffer 0      pv_hdma_cd1 = $7E:AD00
PV_HDMA_STRIDE = $0900   (buffer 1 = buffer 0 + stride)
```

- **Data entry layout**: 4 bytes per displayed scanline —
  `[A lo, A hi, B lo, B hi]` in the AB table, `[C lo, C hi, D lo, D hi]` in
  CD. All 8.8 signed.
- **Scanline → offset**: the body band covers `l0..l1`; the entry for
  displayed scanline V (l0 ≤ V < l1) is at `base + (V − l0)·4`. (The HDMA
  header tables at `$A820/$A830` — 3-byte `[count, ptr lo, ptr hi]`
  entries, repeat-mode body — handle the one-line-early latch so entry 0
  takes effect exactly at l0; you read the data tables, not the headers.)
- **Which buffer**: `M7_PV_BUFFER` (`$7E:01C6`) names the buffer holding
  the freshest rebuild — `pv_rebuild` flips it first, then emits, and the
  channel config points HDMA at the same side. `base = $A000 + buffer·$0900`
  (AB) / `$A400 + buffer·$0900` (CD). Robust alternative for tooling: read
  both buffers and use whichever holds a varying nonzero ramp (the
  `mode7_test` gate does exactly this).
- Interpolation (`interp` 2/4) is already resolved in these tables — the
  lerp passes fill every line before HDMA sees them. Another reason to read
  rather than recompute.
- Reading them from 65816 main-thread code: `$A000+` is **outside** the
  bank-$00 low-WRAM mirror, so use DB=$7E or `f:$7E0000 + addr, x` long
  addressing (the kit's standard high-WRAM read rule). From a Python probe
  they are plain `SnesWorkRam` offsets.

## 4. Inverting for H — the dual-path rule

With V known and (A, B) read at V (and `dx = world_x − M7X`,
`dy = world_y − M7Y`):

```
from the X equation:  H = 128 + (dx·256 − B·(V − anchor_y)) / A
from the Y equation:  H = 128 + (dy·256 − D·(V − anchor_y)) / C
```

Both are exact; their *divisors* go degenerate at different angles. At
cos(angle) ≈ 0, A ≈ 0 and the X equation explodes; at sin(angle) ≈ 0, C ≈ 0
and the Y equation does. (engine-verified, parent lineage: an
X-equation-only implementation failed precisely at angle 192.)

**Selection rule**: compare |A| vs |C| at the target scanline; divide by
whichever is larger. If **both** are < 4, cull the sprite — it is too close
to the degenerate band to place stably.

| Path | Divisor | Multiplier | Delta |
|---|---|---|---|
| X equation | A | B | dx |
| Y equation | C | D | dy |

Implementation shape (engine-verified, parent lineage, ~80 lines of 65816):
one signed 16×16 multiply for `mult·(V − anchor_y)`, a 32-bit numerator
subtract, sign tracking via XOR of the operand signs, an unsigned 32/16
divide, then re-apply sign and add 128. The kit's `engine/mode7_math.asm`
has all the primitives (`smul16`, `udiv32`).

## 5. The empirical scanline search (the proven debugging tool)

For each candidate scanline V in `l0..l1`:

1. read A (and B) from the active AB table at `base + (V − l0)·4`;
2. compute the **forward** transform's world position at screen center
   (H = 128) for this V;
3. score `|world − target|`; keep the best V.

This needs no depth formula at all — it asks the renderer's own tables
"which scanline shows this world position at center screen?" It is O(180)
table reads, trivially done in a Python probe over MesenRunner WRAM dumps,
and it is the ground truth that arbitrates every analytical formula. In the
parent lineage it resolved the screen_y bug unambiguously (best-match error
1 world unit at the correct V vs 109 at the formula's V). Use it:

- as the oracle when deriving a closed-form screen_y for your parameter set;
- as a fallback projection for tooling/tests where per-frame cost is free;
- as the first diagnostic whenever a projected sprite "swims" against the
  floor.

## 6. The lessons list (all engine-verified, parent lineage)

1. **Never derive projection formulas from theory for a nonstandard
   perspective.** This renderer's linearized-reciprocal + LUT depth curve is
   not a pinhole camera; classic racing-game formulas do not transfer.
2. **screen_y before screen_x.** Every H formula reads coefficients at V;
   wrong V poisons them all.
3. **Empirical beats analytical** on a nonstandard system. The scanline
   search found in seconds what formula derivation missed for hours.
4. **Dual-path or it breaks at four angles.** Always pick the equation with
   the larger |divisor|; cull when both are tiny.
5. **Read the actual HDMA tables, never reconstruct.** The tables are what
   the hardware will display — byte-for-byte.

Want this as kit code? It composes from the pieces named here
(`mode7_math.asm` primitives + the table reads) — ask, and it becomes a
scenario with its own run-gate. Until then, treat this page as the
adaptation path, not a shipped surface.
