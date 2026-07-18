# The Mode 7 free-flight rail (`templates/mode7_flight/`)

The genre rail for **free-flight over a Mode 7 perspective floor**: pilot an
airship across a fixed wrapping ground plane where **input-controlled altitude
drives the perspective scale** (climb → the ground recedes; descend → it
approaches), with **free movement** (heading turn + throttle, not the racer's
forward-lock) and an **animated airship + an altitude-scaled ground shadow**
composited over the floor. Build with `make mode7_flight`, verify with
`tests/test_mode7_flight.py` + the `mode7_flight` `oracle.json`.

It forks the `racer` spine (the Mode 7 perspective floor + the stock engine NMI +
the `sf_mode7` macro group + the `sincos` → `smul16` camera integrator) and
rebuilds the control layer for flight. The one genuinely net-new piece — and the
reason this rail exists — is **re-deriving the perspective scale from an altitude
state variable every frame**.

## Architecture — who commits what (3 lines)

Identical to every Mode 7 rail (see `mode7_racer.md` for the full version):

1. **Main thread** (the game loop): update the camera (`sf_mode7_cam`) and the
   per-frame scale (`sf_mode7_scale`), then `sf_mode7_tick` rebuilds the
   per-scanline HDMA matrix tables.
2. **The stock engine NMI** commits everything during VBlank (M7SEL/M7X/M7Y, the
   scroll shadows, the HDMA channel configs, the OAM DMA). No custom VBlank code.
3. **HDMA** feeds `$211B-$211E` per scanline — zero CPU cost. That per-scanline
   matrix rewrite *is* the perspective.

## The control map (owner-settled)

| Input | Action |
|-------|--------|
| D-pad ◄ / ► | turn heading left / right (rotate the Mode 7 angle) |
| B | throttle forward along heading (signed 8.8 speed, capped); release → coast to hover |
| Y | reverse thrust (speed goes negative) |
| L shoulder | descend — altitude ↓ → scale ↑ → ground approaches |
| R shoulder | climb — altitude ↑ → scale ↓ → ground recedes |

**Signed speed is the trick.** `R_SPEED` is a *signed* 8.8 word, so reverse (Y)
and hover (release → bleed toward 0) fall out of the **same** `sincos` → `smul16`
integrator the racer uses — `smul16` sign-handles, so a negative speed steps the
camera backward for free. No separate reverse code path.

## The altitude → scale pattern (the net-new piece)

This is the pattern the cold-start trial surfaced as undocumented (Gap A). It is
now a first-class primitive — `sf_mode7_scale` (added to `lib/macros/sf_mode7.inc`
for this rail).

`sf_mode7_scale s0, s1` is the **scale-only** counterpart of `sf_mode7_focus`:
it writes `M7_PV_S0`/`M7_PV_S1` and flags `M7_DIRTY_REBUILD`, leaving the rest of
the trapezoid (l0/l1/sh/interp/wrap) as the last `sf_mode7_perspective` set it.

The **intuition** (now in the `sf_mode7_perspective` header too): a **bigger `s0`**
makes the far scanline span more map, so the ground looks **farther / more
compressed** (recedes); a smaller `s0` brings it closer. So altitude maps to
scale directly. The rail keeps the **altitude → scale curve in `main.asm`** (like
the racer keeps its day-night phase machine in the template, not the macro) so
the library stays orthogonal:

```asm
; per frame, after the L/R altitude control updates R_ALT (clamped [0, ALT_MAX]):
    jsr compute_scales       ; R_S0 = S0_LOW + (alt*S0_SPAN)>>8 ; R_S1 likewise
    sf_mode7_scale R_S0, R_S1 ; writes M7_PV_S0/S1 + flags M7_DIRTY_REBUILD
    ...
    sf_mode7_tick            ; consumes the dirty flag -> rebuilds with the new scale
```

`compute_scales` is a linear interpolation via `umul16` (the engine's 16×16
unsigned multiply): `alt` is 0..255, the spans are ≤ 960, so the product fits and
`(product >> 8)` is read straight out of `math_p+1`. Swap it for a LUT if you want
a non-linear altitude feel — the rail intentionally leaves the curve to the game.

The cold-start's measured endpoints, reproduced by this rail: altitude **low**
(alt 0) → s0/s1 ≈ 220/40, ground near/big (~4 color-transitions per floor row);
altitude **high** (alt 240) → s0/s1 ≈ 1120/265, ground far/small (~22
transitions/row, fine cells packed to the horizon). **Clamp** altitude at both
ends — `ALT_MIN` is the closest approach, **not** a ground collision (no crash;
out of scope per the DoD).

## ⚠ The Gap-B cost note (read this before adding more to the loop)

The `sf_mode7` cost model is tuned for the **opposite** of an altitude game.
`sf_mode7_cam` flags the ~10k-cycle `M7_DIRTY_REBUILD` **only when the angle
changes**, specifically so straight driving stays cheap. An altitude game inverts
that: **every frame the player climbs or descends fires the full ~10k-cycle
rebuild** — there is no scale-only cheap path (the ZR0/ZR1 reciprocal recompute is
not split from the rotation-matrix work). `sf_mode7_scale` flags the same full
rebuild.

~10k cycles is roughly ⅓ of the ~28–37k/frame budget. This rail stays at a hard
60 fps because the flight loop carries **only** the Mode-7 rebuild + the two OBJs
+ input — day/night is **out of scope** here precisely so the budget has room. If
you add a day-night gradient, palette cycling, audio, and more OBJ on top of a
per-frame altitude rebuild, that rebuild becomes the thing most likely to push you
over budget. The engine fix (split `M7_DIRTY_REBUILD` into `_SCALE`/`_ANGLE` so an
altitude-only change recomputes just the ZR ramp) is a deferred rail-promotion
backlog item, **not** built here — this rail documents the cost rather than
engineering around it.

## The airship + the altitude-scaled shadow (composited over Mode 7)

OBJ rendering is mode-independent, but the Mode 7 map fills VRAM words
`$0000-$3FFF` wholesale, so the OBJ name base must move out of it: `OBSEL = $62`
(name base word `$4000` = tile 1024), CHR uploaded there. The airship still draws
above the horizon because the sky TM-split (`arm_sky_split`) keeps OBJ on in both
the sky band and the floor band.

### The 4bpp sprite asset format (the cold-start DX cut, now documented)

The airship art (`assets/airship.inc`, the sanctioned reuse — pixel data only,
with a clean kit-side header) is **24 frames × 512 bytes** of SNES 4bpp tile data
+ a 16-color (32-byte) BGR555 palette. Frame order: 12 directions (`pitch*4+turn`)
× 2 propeller states (frames 0–11 = prop A, 12–23 = prop B). **Each 512-byte
frame = 4 blocks of 128 bytes; each block is one tile-row of 4 contiguous 8×8 4bpp
tiles** (planar: rows 0–7 of plane0/1, then plane2/3).

The load contract for a 32×32 OBJ: the SNES hardware reads an N×N sprite's lower
tile-rows at **+16 tile numbers** (the 16-wide VRAM tile grid), so upload each of
a frame's 4 blocks to a VRAM tile-row 16 apart, and the frame's **base tile must
be 16-aligned** (`sf_load_obj_chr` asserts this). The rail uploads the straight-
facing prop-A frame (relative tile 0) and prop-B frame (relative tile 64), then
**animates the propeller by flipping the OAM tile number** between them every
`PROP_RATE` frames — no per-frame tile DMA needed.

### The ground shadow

`assets/make_shadow.py` generates a dark flattened ellipse in two sizes (a 32×32
BIG and a 16×16 SMALL, same block layout). The rail selects between them by the
**OAM size bit + tile number + screen-Y offset**, all driven by altitude: low →
BIG, close under the airship; high → SMALL, lower toward the horizon. That gives a
strong, cheap second altitude readout layered on top of the perspective change —
and it is OAM-readable, so the test asserts it directly.

## What's out of scope (hold this line)

- **Day/night cycle** — already proven by `racer`; orthogonal, and kept out here
  to leave budget for the per-frame altitude rebuild (see Gap B above).
- **Streaming a large world** — `mode7_explore` proves it; this rail is the fixed
  wrapping plane (`wrap=1`, so free movement never hits a black edge).
- **Terrain collision / crash / landing** — altitude clamps at the floor; no
  crash. Pure perspective effect.

## Done-condition

`tests/test_mode7_flight.py` (A1 altitude→perspective with clamps, A2 free
movement, A3 airship + scaling shadow — all reading rendered output) + the
`mode7_flight` `oracle.json` (A4: boots into flight over the textured plane with
airship + shadow; descend approaches; climb recedes; turn rotates the floor).
Both run under `make check`.
