# The Mode 7 rotating-floor dungeon rail (`templates/m7_dungeon/`)

The genre rail for a **top-down dungeon crawler with tank controls**: the
player's facing always reads **"up"** and the dungeon **floor rotates +
scrolls underneath** as the player turns and drives. The floor is the Mode 7
BG, scaled + rotated as one rigid image by a **single uniform affine matrix**;
the hero is an OBJ composited over it at screen centre. The world holds an
authored maze with **world-space wall collision**, **patrolling enemies**
projected onto the spinning floor, and **hero-enemy contact** (knockback +
a HITS counter). Build with `make m7_dungeon`, verify with
`tests/test_m7_dungeon.py` + the `m7_dungeon` `oracle.json`.

It forks the **static-affine** Mode 7 path the **boss rail** uses (a uniform
matrix, `sf_boss_mode7_on` / `sf_boss_center` / `sf_boss_matrix`, no
perspective HDMA) and rebuilds the control + world layers for a dungeon. The
genuinely net-new pieces are the **moving pivot** (the pivot tracks the player
every frame instead of being pinned once) and a **world-space gameplay model**
— collision, patrol, and contact — that is **entirely independent of the
render rotation**.

## Architecture — static affine, ~no HDMA (3 lines)

Unlike the racer / free-flight rails (per-scanline perspective HDMA), this rail
is a **uniform affine plane** — flat, no trapezoid:

1. **Main thread** (the game loop): `sf_boss_matrix #SCALE, R_ANGLE` rotates the
   whole plane uniformly (SCALE=$0100 = 1.0, flat); `sf_boss_center world_x,
   world_y` pins the player's WORLD (x,y) to screen centre (128,112). Both are
   shadow writes — call `sf_boss_matrix` FIRST after `sf_frame_begin` so the
   whole visible frame reads one matrix.
2. **The stock engine NMI** commits everything during VBlank (M7SEL/M7X/M7Y +
   scroll from the shadows, OAM DMA). **No custom NMI, no perspective HDMA.** A
   uniform matrix is ~50 cycles, not the ~10k a per-scanline perspective rebuild
   costs.
3. The affine matrix **never touches OBJ** — so the hero stays pinned at screen
   centre and **upright** (no flip) while the world spins beneath it.

## The control map (tank controls, owner-settled)

| Input | Action |
|-------|--------|
| D-pad ◄ / ► | rotate the heading `R_ANGLE` (the floor matrix follows → the floor rotates; facing stays "up") |
| B or UP | throttle forward along the heading; release → coast to hover |
| Y or DOWN | reverse thrust (speed goes negative) |

**The moving pivot is the whole idea.** The pivot is the centre of rotation;
pinning it to the player every frame keeps the player screen-centred as the
floor spins **and** scrolls. The boss rail pins the pivot *once*; here
`sf_boss_center R_POSX, R_POSY` runs every frame — it is just a shadow write the
stock NMI already commits, so the moving pivot is nearly free.

**Signed speed is the integrator trick** (shared with the flight rail): `R_SPEED`
is a *signed* 8.8 word, so reverse (Y/DOWN) and hover (release → bleed toward 0)
fall out of the **same** `sincos` → `smul16` step that drives forward motion.
Speed is capped SLOW (≤ ~1.25 px/frame) so a single step can never tunnel a
2-tile (16px) wall (see collision below).

## The world model is render-independent (the load-bearing idea)

Every gameplay system — collision, patrol, contact — runs in **WORLD space**
and **never reads the affine matrix**. The render rotation is a pure
presentation layer on top of a flat top-down world. This is what makes the rail
tractable: you do not need the pseudo-3D *inverse* transform for gameplay, only
for drawing sprites.

### Collision — a world-space LUT, the matrix is never read

`dungeon_terrain.bin` is a 128×128 byte LUT (`1`=solid, `0`=floor) emitted by
`assets/make_dungeon.py` from the **same `is_wall()` predicate that paints the
wall art** — so "what you see is what blocks you" by construction. A world pixel
`(wx,wy)` maps to tile `(wx>>3, wy>>3)` and reads `terrain[ty*128+tx]`.

- **Candidate-test-commit, per axis.** The integrator computes the heading step
  but commits each axis only if that axis's candidate footprint is clear. A
  diagonal push into an axis-aligned wall therefore **slides** (the unblocked
  axis still progresses) instead of dead-stopping at the corner.
- **The hero is a body, not a point.** The footprint is an 8px box (HALF=4)
  whose 4 world-space corners are sampled against the LUT, so it can't clip a
  wall corner or half-enter a cell.
- **Why no inverse transform is needed.** Collision asks "is this *world* pixel
  solid?" — a flat LUT lookup. The Mode 7 matrix only affects how the floor is
  *drawn*; it has nothing to say about whether a world cell is a wall. Keeping
  collision off the render path is why the wall-hug squeeze and the committed
  `assets/maze_route.json` solve are deterministic and render-rotation-proof.

The terrain LUT being the SAME source as the art is the ground-truth oracle:
`test_m7_dungeon.py` mirrors `is_wall()` in Python and asserts the hero
footprint never occupies a solid cell (and a `-DNO_COLLISION` negative-control
build walks through walls, proving the assertion isn't vacuous).

### Enemy projection — use the INVERSE (transpose) matrix

Drawing a sprite glued to a world tile is the **one** place the matrix matters,
and the direction is the trap. The floor's forward matrix `M=[[A,B],[C,D]]` is
**screen→texel**; placing a sprite is the opposite, **world→screen**, which is
`M⁻¹`. At the fixed scale 1.0 `M` is a pure rotation, so its inverse is the
**transpose** `[[A,C],[B,D]]` (swap B↔C). With `(dx,dy) = enemy_world −
player_world` (the pivot = screen centre):

```
screen_x = ((dx·A + dy·C) >> 8) + 128
screen_y = ((dx·B + dy·D) >> 8) + 112
```

**Using the forward matrix instead drifts the enemies onto the WALLS** under
rotation — a real defect this build hit (see the gotcha below). Off-screen
enemies are **culled**: when the projection lands outside the window (±16px
slack for the 16px sprite) the OAM slot is **parked** at `Y=$F0` rather than
wrapped to a bogus on-screen position. Patrol drives a far enemy out of view
(dropped) and back in (popped) purely by visibility.

### Contact — a world-space box → knockback + HITS

Hero-enemy contact is a world-space box overlap (8×8). On overlap the hero is
knocked back to the spawn cell (`R_POSX/Y` reset, speed 0) and a HITS counter
ticks, with a post-respawn GRACE window so an enemy beat crossing the spawn
can't immediately re-hit. The **visible** proof of a hit is the hero
teleporting back to screen-centre on the spawn tile.

> **HITS HUD deferred.** Mode 7 owns the BG and there's no spare BG text layer
> for a HITS readout, so the HITS HUD is **deferred** (owner-settled). The S5
> outputs are the debug mirror (`DBG_HITS` at `$E01C`) and the visible respawn;
> a later sprint can add a sprite-glyph HUD.

## The meta-lesson: Mode 7 sprite tests must read the RENDERED floor

The sharpest lesson this rail established — and the one to carry to any Mode 7
sprite/projection work — is that **a projection test must read the rendered
floor, not a same-formula oracle.** All **three** of this rail's visible bugs
passed self-referential checks:

1. **Forward-vs-inverse projection** (enemies drifting onto walls under
   rotation) passed the OAM-vs-`_project` oracle — because that oracle *is* the
   same 8.8 formula as the ASM, so it can't catch a wrong-direction matrix — and
   also passed a distance-only orbit check (blind to rotation direction).
2. **OBJ size vs CHR layout** (the phantom-tile-bleed bug): OBSEL selected the
   16×16/32×32 size pair and the hero's OAM size bit was SET → a 32×32 hero
   pulls in tile 32 (the *enemy* CHR added in S4) into its lower-left quadrant,
   rendering a phantom diamond in the hero's palette. The OAM coordinates were
   perfect; only the **rendered pixels** below the hero showed the bug. **OBJ
   size must match the CHR tile layout** — fix: clear the size bit (16×16).
3. **Invisible enemies** (correct OAM, 0 enemy pixels): the OAM name/tile-high
   bit was set → the slot pointed at empty VRAM tile 288, and palette 0 drew the
   hero's cyan instead of the enemy red. Again, perfect OAM, wrong **render**.

The binding guards in `test_m7_dungeon.py` are therefore **oracle-free,
rendered-output** reads: they sample a ring around each drawn sprite centre and
classify FLOOR (blue checker) vs WALL (terracotta) pixels on the framebuffer,
and they count enemy-RED pixels at projected centres. Each has a non-vacuity
control build (`-DENEMY_PROJ_FORWARD`, `-DBUGGY_SPRITE_SIZE`) that **fails** the
same check. The takeaway: **for Mode 7, "the OAM matches my projection formula"
is not "it's on the floor" — read the floor.**

## Placeholder art

The rail ships **placeholder art** (owner-settled): `make_dungeon.py` (floor
checker + wall bands), `make_hero.py` (a 16×16 cyan body), `make_enemy.py` (a
red diamond). These are CC0-style generated assets — swap in real CHR by
editing the `make_*.py` emitters; keep `is_wall()` and `dungeon_terrain.bin` in
lockstep (the test mirrors `is_wall()`, so changing the wall art without
re-emitting the LUT will break collision).

## Done-condition (what "it works" means)

The rail is validated by **rendered output**, never a proxy:

- **`tests/test_m7_dungeon.py`** — the full acceptance gate (28 tests): boots
  textured; hero centred + upright under all input; tank turn rotates the floor
  (rendered diff) with opposite L/R angle deltas; forward/reverse scroll the
  floor; world-space collision blocks from all facings / in a far room / slides
  / never tunnels at the speed cap (+ a `-DNO_COLLISION` non-vacuity control);
  the committed `assets/maze_route.json` solves the maze with the footprint
  clear every frame; enemies project glued under rotation + translation, render
  red, cull off-screen + pop in, sit on the rendered FLOOR at multiple angles
  (+ `-DENEMY_PROJ_FORWARD` non-vacuity); the hero is 16×16 with no phantom
  diamond (+ `-DBUGGY_SPRITE_SIZE` non-vacuity); patrol moves + wall-turns;
  contact knocks back + ticks HITS; the goal is safe.
- **`templates/m7_dungeon/oracle.json`** — the declarative, catalog-proven
  scenario set, run by `tests/test_oracles.py`. Each scenario reads the rendered
  framebuffer (screenshot pixels / blobs) or OAM bytes:
  - `boots_into_textured_rotating_mode7_dungeon` — hero OAM slot 0 centred +
    upright at (120,104); floor blob ≥4 distinct colours; heartbeat advances.
  - `near_start_enemy_renders_red_on_the_floor` — ≥20 enemy-red pixels on the
    framebuffer (the near-start enemy actually draws in its red palette).
  - `tank_turn_rotates_the_rendered_floor` — `axis_sweep` LEFT and RIGHT, each
    changes ≥20% of the rendered floor (the static affine plane only moves under
    input, so a before/after diff is a true rotation signal); hero stays centred.
  - `drive_forward_scrolls_the_rendered_floor` — `axis_sweep` UP and DOWN, each
    scrolls ≥15% of the rendered floor; hero stays centred.
  - `far_enemy_is_culled_offscreen_at_boot` — the near-exit enemy's OAM slot is
    parked at `Y=$F0` (culled, not wrapped on-screen).
