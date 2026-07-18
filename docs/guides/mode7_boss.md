# Mode 7 Boss — "the boss IS the screen"

The genre guide behind `templates/boss/` + `lib/macros/sf_mode7_affine.inc`. For
a giant enemy that **scales and rotates as one rigid image** — it lunges toward
you, it spins, it fills the screen — the boss is not a sprite. It is the entire
Mode 7 background plane, and the hardware transforms it for free.

## The idea

Mode 7 gives you one BG layer that the PPU runs through an affine matrix
(M7A–M7D at `$211B–$211E`) before sampling. The matrix maps **screen pixel →
texel**. If you write ONE uniform matrix that covers the whole plane:

```
M7A = cos(angle) * scale     M7B = sin(angle) * scale
M7C = -M7B                   M7D =  M7A          (uniform: scaleX == scaleY)
```

then the whole BG image scales and rotates as a rigid body, every frame, at
~50 cycles (a dozen register writes via `mode7_set_static`). Upload a boss-face
image into the Mode 7 tilemap + tileset VRAM and that image is now a creature the
hardware can grow, shrink, and spin. The player, the boss's attacks, and the HP
bar are ordinary OBJ sprites composited **over** the plane — the affine matrix
**never touches OBJ**, so sprites stay at their fixed size and screen position
while the boss behind them transforms.

## Two Mode 7 paths — pick the right one

| | `sf_mode7.inc` (perspective floor) | `sf_mode7_affine.inc` (whole-plane) |
|---|---|---|
| Shape | a road/sky receding to a horizon | one rigid image, uniformly scaled/rotated |
| Matrix | rewritten **per scanline** by HDMA | one **static** matrix for the whole frame |
| Cost | ~10,000 cyc/frame to rebuild the table | ~50 cyc/frame |
| HDMA | pins CH5+CH6 | **none** |
| Use for | racers, rail-shooters, flight | bosses, spinning rooms, a whole-screen zoom |

They are mutually exclusive on screen (both repurpose BG1 + Mode 7 VRAM
wholesale). A boss fight uses the affine path; do **not** reach for the
perspective floor or its per-scanline matrix — that's the expensive shape the
cycle budget flags, and you don't need depth for a front-facing boss.

## The three macros

- **`sf_boss_mode7_on`** — switch to BGMODE 7, enable BG1+OBJ, install an
  identity matrix, and set `M7_PV_ACTIVE=1`. That flag makes the **stock engine
  NMI** commit M7SEL/M7X/M7Y + the BG1 scroll shadows (the Mode 7 13-bit scroll)
  during VBlank — so you need **NO custom NMI handler**. It arms **no HDMA**.
  Call it once during forced blank, after `sf_mode7_load_map`.
- **`sf_boss_center cx, cy`** — pin the affine pivot (the one texel that stays
  fixed at every scale) to a map point, and set the scroll so that pivot renders
  at screen center (128,112). The boss scales/rotates *around* that point.
- **`sf_boss_matrix scale, angle`** — the per-frame call. Computes the matrix
  from `(scale, angle)` and commits it via `mode7_set_static`.

### Scale direction — the one gotcha

The matrix maps screen→texel, so a **LARGER scale value samples a WIDER texel
span = the boss looks SMALLER / farther away.** `$0100` is 1.0 (native);
`$0180` (1.5) shows the whole boss; a big value like `$0500` makes it a distant
speck. So a **reveal** (boss grows in) ramps scale *down* from a big value
toward the rest value; a **death** (boss recedes) ramps it *up*. Verify the
direction on the emulator with a screenshot before you lock a ramp — it is
counter-intuitive and easy to invert.

### Call it first, before active display

Write the matrix **first thing after `sf_frame_begin`**. The PPU latches M7A–D
before scanline 0, so writing them at the top of the frame gives the whole
visible frame one consistent matrix (no tearing). This is the proven placement.

## The battle structure (what `templates/boss/` adds on top)

The rendering is the easy ~70%; a fight is the rest. The template ships:

- **A reveal→hold→fight→death/lose→result→reset state machine** (`b_state`). The
  reveal ramps the scale to grow the boss in; death ramps it back out.
- **Masked transitions** via `sf_bright_fade` (`sf_fx.inc`): fade to black, do
  any discontinuous swap under `INIDISP==0`, fade back. This is deliberately a
  forced-blank fade, **not** a mid-VBlank tilemap-swap in a custom NMI — that NMI
  swap is the classic Mode 7 silent-BRK width-risk region, and you don't need it.
- **An attack layer**: an `sf_pool` of projectile sprites raining toward the
  player on a phase-scaled cadence, drawn into stable OAM slots (draw every slot
  every frame, park dead ones off-screen).
- **Hit detection** via `col_box` (`sf_collision.inc`): attack-vs-player drops
  player HP (+ invulnerability frames); player-shot-vs-boss-hitbox drops boss HP.
- **A sprite HP HUD** (the boss has no spare BG layer for text — Mode 7 is one BG
  + OBJ), drawn as segment sprites over the boss BG.

## DON'Ts

- **Don't expect the matrix to scale your sprites.** It transforms the BG only.
  Player/attacks/HUD are fixed-size OBJ; if you want them to "grow," swap tiles
  or use the rail-shooter size-tier path, not the matrix.
- **Don't put the OBJ name base inside the map's VRAM.** The Mode 7 map fills
  VRAM words `$0000–$3FFF`; set OBSEL so the sprite CHR base clears it (the
  template uses `$62` = word `$4000`).
- **Don't ramp `INIT_SCALE` past `REVEAL_SCALE`.** The reveal step is
  `(REVEAL_SCALE − INIT_SCALE)/REVEAL_FRAMES`; inverting the order breaks the
  grow-in direction.
- **Don't write a custom NMI for the swap.** The stock NMI commits everything
  this path needs (M7SEL/M7X/M7Y + scroll); the matrix goes in the main loop.

## Build it

```
make boss
PYTHONPATH=. python3 -m pytest tests/test_boss.py -q
```

Tune the fight by editing the constants at the top of `templates/boss/main.asm`
(boss HP, player HP, attack cadence, scale curve, phases). Author new boss art
with `templates/boss/assets/make_boss.py` (a 1024×1024 PNG → the Mode 7
converter) and sprites with `make_sprites.py`.
