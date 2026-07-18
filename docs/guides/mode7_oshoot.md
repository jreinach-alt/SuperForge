# The Mode 7 overhead-shooter rail (`templates/m7_oshoot/`)

The genre rail for a **top-down run-and-gun on a rotating Mode 7 plane** —
top-down run-and-gun on a rotating Mode 7 floor (facing always reads 'up'). The player's facing always
reads **"up"**; the **floor rotates underneath** as you turn so forward (up on
screen) is always along your heading; **fire shoots forward**, bullets stream
across the spinning floor, and **timed enemy waves** chase the hero. Build with
`make m7_oshoot`, verify with `tests/test_m7_oshoot.py` + the `m7_oshoot`
`oracle.json`.

It **forks `templates/m7_dungeon/`** — it keeps that rail's static-affine
rotating floor, moving pivot, world→screen transpose-matrix sprite projection,
and world-space contact/HITS verbatim — and **composes `sf_pool`** (the actor
pools from the `shmup` rail). The genuinely net-new pieces over `m7_dungeon`
are: **8-way aim glue** (move = aim = facing), **`sf_pool` bullets fired along
the facing and projected onto the rotating plane**, **bullet↔enemy world-space
collision**, and **timed enemy waves**. Everything that was hard in
`m7_dungeon` (the rotating render, the moving pivot, the inverse/transpose
projection that keeps sprites glued to the floor) is inherited, not re-solved.

## Architecture — static affine, ~no HDMA (inherited from m7_dungeon)

Like `m7_dungeon` (and unlike the racer / free-flight rails), this rail is a
**uniform affine plane** — flat, no per-scanline perspective HDMA:

1. **Main thread** (the game loop): `sf_boss_matrix #SCALE_VIEW, R_ANGLE`
   rotates the whole plane uniformly (`SCALE_VIEW` = 1.0, flat) — call it FIRST
   after `sf_frame_begin` so the whole visible frame reads one matrix;
   `sf_boss_center R_POSX, R_POSY` pins the player's WORLD (x,y) to screen
   centre (128,112). Both are shadow writes.
2. **The stock engine NMI** commits everything during VBlank (M7SEL/M7X/M7Y +
   scroll from the shadows, OAM DMA). **No custom NMI, no perspective HDMA.** A
   uniform matrix is ~50 cycles, not the ~10k a per-scanline rebuild costs.
3. The affine matrix **never touches OBJ** — the hero stays pinned at screen
   centre and **upright** (no flip) while the world spins beneath it.

**The moving pivot is the centre of rotation.** Pinning it to the player every
frame (`sf_boss_center R_POSX, R_POSY` runs each frame, just a shadow write the
stock NMI commits) keeps the player screen-centred as the floor both spins and
scrolls. The boss rail pins the pivot once; here it tracks the player.

## The control map (model A — "face-where-you-move", owner-settled)

Model A, **NOT twin-stick**: one D-pad drives move = aim = facing together.

| Input | Action |
|-------|--------|
| D-pad (8-way) | move the hero's WORLD position along one of 8 compass headings; **`R_ANGLE` snaps to that heading** so the floor rotates to read facing "up" |
| A | **fire forward** — spawn a bullet at the hero world pos with velocity along the heading (up on screen = along the heading in world) |
| (release) | **last facing persists** — `R_MOVING=0`, the world freezes but `R_ANGLE` holds, so **stand-and-shoot** works |

`R_MOVING` is recomputed every frame: zeroed, then set to 1 only if a valid
D-pad direction is held (an opposite-pair cancel reads as idle). When idle,
`move_x`/`move_y` are **skipped** (`lda R_MOVING; beq move_skip`) so the world
position is deterministically **frozen** — "freeze" here means the world pixels
do not move, while the last `R_ANGLE` (and therefore the floor orientation)
persists.

> **Idle-test note (joypad latency).** The harness frees the emulator on its own
> thread and `set_input(0)` lands asynchronously, so after releasing the D-pad
> the ROM can still read "held" in `JOY1_CURRENT` for ~1 more frame and commit
> one last move step. The idle-persistence test **settles 2 frames after release
> before sampling its baseline**, then asserts the world pos is frozen exactly —
> it tests the real invariant ("once truly idle, pixels don't move"), not a racy
> pre-/post-latency sample.

## Bullets on the rotating plane — the crux (transpose matrix, shared snapshot)

Bullets are **`sf_pool` actors that live in WORLD space** and are **projected
onto the spinning floor every frame** — this is the keystone the rail's S3
Audit Protocol guards. `fire_bullet` spawns a bullet at the hero world pos with
a velocity along the facing (forward = **negate** the `sincos`×speed product —
the same sign convention as the hero step); `update_bullets` advances every
live bullet in world space and despawns it at max range. Neither needs the
matrix — they run **before** the matrix snapshot.

`draw_bullets` is ~95% a copy of `m7_dungeon`'s `draw_enemies`: it projects each
live bullet's world offset from the pivot onto the floor. The floor's forward
matrix `M=[[A,B],[C,D]]` is **screen→texel**; placing a sprite is the opposite,
**world→screen**, which is `M⁻¹`. At scale 1.0 `M` is a pure rotation, so its
inverse is the **transpose** `[[A,C],[B,D]]` (swap B↔C). With `(dx,dy) =
bullet_world − player_world` (pivot = screen centre):

```
screen_x = ((dx·A + dy·C) >> 8) + 128
screen_y = ((dx·B + dy·D) >> 8) + 112
```

Two non-negotiable traps (both inherited from the m7_dungeon projection bug
class — get either wrong and bullets **swim onto the wall pillars** under
rotation):

1. **Use the TRANSPOSE `(A,C)/(B,D)`, not the forward `(A,B)/(C,D)`.** The
   `-DBULLET_PROJ_FORWARD` non-vacuity build uses the forward matrix and the
   floor-vs-wall ring test FAILS — proving the projection test isn't a
   tautology.
2. **The matrix snapshot must be SHARED.** Right after `sf_boss_matrix` commits,
   the loop copies the live matrix into `M7A_SAV..M7D_SAV` (`$3E–$44`).
   `draw_enemies` AND `draw_bullets` both read that **one snapshot**, so bullets
   and enemies are projected with the EXACT matrix the floor rendered with — and
   stay glued to their floor tiles. A snapshot-per-actor reintroduces the swim.

OBSEL is `$62` (16×16 small / 32×32 large pair) and bullets are **16×16**
(`HERO_SIZE_BIT` clear) — the m7_dungeon phantom-diamond lesson: a 32×32 OBJ
pulls neighbouring CHR tiles into its lower quadrants. Off-screen bullets are
**culled** (OAM slot parked at `Y=$F0`, not wrapped to a bogus on-screen X).

## Bullet↔enemy collision is world-space (rotation-invariant)

`bullet_enemy_collide` is a **nested world-space AABB** over the bullet and
enemy pools — it **never reads the matrix**, so it is **rotation-invariant** by
construction (the same render-independent-world-model principle as
`m7_dungeon`'s wall collision). On overlap it kills both pool slots and ticks
`KILLS`. It is an **inline AABB** rather than a `col_box` link — equally
rotation-invariant (world-space box), smaller, and a sound ROM-budget call. The
`-DNO_BULLET_COLLISION` non-vacuity build gates this `jsr` out: bullets then
pass through enemies and KILLS stays 0 at every angle — proving the hit test is
load-bearing.

The decisive correctness property the DoD requires: at **multiple plane rotation
angles**, a fired bullet KILLS its enemy (the enemy despawns — OAM slot parked
at `Y=$F0` AND the enemy-red pixels vanish at the rendered location). That proves
two things at once: world-space hit detection is rotation-invariant, AND the
**visible** bullet position coincides with where the hit registers.

## Enemy waves (`sf_pool`) — spawn, chase, contact

`enemy_waves` spawns chasers on a `SPAWN_PERIOD` cadence at world-ring positions
(pop-in); `chase_enemies` steps every live chaser toward the player's world
position each frame. Enemies are projected onto the floor with the SAME shared
transpose snapshot (`draw_enemies`), render **red** on the floor, and are
**culled** off-window (parked off-screen, pop in when approached) — exercising
the projection under **both** rotation and translation. **Hero-enemy contact**
is a world-space box overlap → knock the hero back to spawn (`R_POSX/Y` reset,
speed 0, `R_MOVING=0`) + tick `HITS`, with a post-respawn grace window so an
enemy beat crossing the spawn can't immediately re-hit. The **visible** proof of
a hit is the hero teleporting back to screen-centre on the spawn tile.

> **Chasers FLOAT over interior pillars** (gameplay convention, not a bug). Only
> the player and bullets interact with the floor obstacles; the chasers ignore
> pillar collision so they can't box themselves in (no pathfinding). This
> diverges from `m7_dungeon`, where the world model applies uniformly. It does
> NOT mask a projection bug — `test_enemy_chases_and_projects_on_floor` reads the
> rendered floor ring at the chaser centre and passes; the chasers genuinely sit
> on the spinning floor, they just don't collide with the pillars on it.

> **HITS HUD deferred.** Mode 7 owns the BG and there's no spare BG text layer,
> so the HITS readout is deferred (same as `m7_dungeon`). The outputs are the
> debug mirror (`DBG_HITS`) and the visible respawn.

## The meta-lesson: Mode 7 sprite tests must read the RENDERED floor

The sharpest lesson `m7_dungeon` established — and the one this rail re-applies —
is that **a projection test must read the rendered floor, not a same-formula
oracle.** OAM coordinates or a same-8.8-formula oracle PROVE NOTHING: the engine
and the oracle can be wrong the **same way** (a wrong-direction matrix passes an
OAM-vs-`_project` check because that check *is* the same formula). `m7_dungeon`
shipped three visibly-wrong things past a green self-referential suite.

So every projection/affine-sprite assertion in `tests/test_m7_oshoot.py` is an
**oracle-free, rendered-output** read: it samples a ring of framebuffer pixels
around each drawn bullet/enemy centre and classifies FLOOR (blue checker) vs
WALL (terracotta) pixels, or counts enemy-RED pixels at projected centres. Each
crux gate has a **`-D` non-vacuity control build** that FAILS the same check
(`-DBULLET_PROJ_FORWARD` for the bullet projection/glue; `-DNO_BULLET_COLLISION`
for hit-through-rotation), wired in `build_m7_oshoot_variants.sh`. The takeaway:
**for Mode 7, "the OAM matches my projection formula" is not "it's on the floor"
— read the floor.**

> **Open-floor non-vacuity is geometry-fragile.** A forward-matrix bullet over
> *sparse* floor often still lands on floor by luck, so the control wouldn't
> discriminate. The fix: a regular pillar lattice (pitch 6) + a frozen-bullet
> build flag that parks the bullet at a large screen offset, so the
> forward-vs-transpose difference reliably lands the bullet on a wall. Carry this
> "lay a pillar lattice for the test" pattern to any future open-floor Mode 7
> rail.

## Placeholder art

The rail ships **placeholder art** (owner-settled), CC0-style generated assets
(swap in real CHR by editing the emitters): a checker floor + pillar lattice, a
16×16 hero, a red enemy diamond, a yellow bullet diamond. Keep the wall art and
the world-space collision LUT in lockstep (the test mirrors the wall predicate).

## Done-condition (what "it works" means)

The rail is validated by **rendered output**, never a proxy:

- **`tests/test_m7_oshoot.py`** — the full acceptance gate (13 tests): boots a
  textured rotating Mode 7 floor with the hero centred + upright; 8-way input
  rotates the rendered floor (before/after diff) and snaps the heading; the
  facing persists when idle (stand-and-shoot); a fired bullet renders ON the
  floor at multiple headings (framebuffer ring) and stays **glued** to the same
  floor spot through a full rotation sweep; the bullet KILLS its enemy at
  multiple plane angles and the enemy despawns (OAM parked `Y=$F0` + enemy-red
  vanishes); timed enemy waves spawn, project red on the floor, chase, cull +
  pop-in; contact knocks the hero back + ticks HITS; a multi-frame film-strip of
  the full loop is regenerated from the verified binary and surfaced — with
  `-DBULLET_PROJ_FORWARD` / `-DNO_BULLET_COLLISION` non-vacuity controls.
- **`templates/m7_oshoot/oracle.json`** — the declarative, catalog-proven
  scenario set, run by `tests/test_oracles.py`. Each scenario reads the rendered
  framebuffer (screenshot pixels / blobs) or OAM bytes, never a WRAM proxy:
  - `boots_into_textured_rotating_mode7_arena` — boots a textured arena floor.
  - `eight_way_input_rotates_the_rendered_floor` — input rotates the rendered
    floor (the static-affine plane only moves under input, so a before/after
    diff is a true rotation signal).
  - `fired_bullet_renders_yellow_on_the_floor` — a fired bullet draws yellow on
    the floor.
  - `enemy_wave_chaser_renders_red_on_the_floor` — a wave chaser draws red on the
    floor.

`lorom_64k.cfg` (same as `m7_dungeon`). See also `docs/guides/mode7_dungeon.md`
for the substrate this rail forks.
