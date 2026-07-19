# m7_oshoot — Mode 7 rotating-floor overhead shooter

## What it is

A top-down run-and-gun on a ROTATING Mode 7 ground plane. The D-pad picks one of 8
compass headings and moves the player through the world; the whole floor rotates so
your facing always reads "up", and you fire forward along it. Timed waves of
enemies chase you across the spinning floor, your bullets and the enemies collide
in world space, and walls block you. It is forked from m7_dungeon and keeps that
rail's static-affine floor, world-space collision, and transpose-matrix sprite
projection.

| Button | Action |
|---|---|
| **D-pad (8 ways)** | move along a compass heading; the floor rotates so you face "up". The facing persists when you stop. |
| **A** | fire forward along the facing |

## What it teaches

- **Static-affine rotating Mode 7 with a moving pivot** — `sf_mode7_affine.inc`
  (`sf_boss_mode7_on/center/matrix`): one uniform affine matrix rotates the whole
  floor (~50 cycles, no perspective HDMA), and `sf_boss_center` re-pins the pivot
  to the player's world position every frame so the player stays centred while the
  world spins beneath.
- **Projecting sprites onto the spinning floor** — bullets and enemies live at
  world positions and are projected to screen through the INVERSE (transpose) of
  the render matrix (`draw_bullets` / `draw_enemies`, sharing the `M7A_SAV..D`
  snapshot), so they stay glued to the floor as it rotates.
- **Rotation-independent world-space gameplay** — movement, wall collision
  (candidate-test-commit with per-axis slide against a 128x128 terrain LUT), and
  the bullet<->enemy / hero<->enemy box collisions all run in WORLD space and never
  read the matrix, so the logic is unaffected by the render rotation.
- **Two `sf_pool` object pools** — `sf_pool.inc`: a bullet pool fired along the
  facing and an enemy pool of timed wave chasers, each spawned, advanced, culled,
  and drawn from parallel WRAM arrays.

## Three things to tweak

- **`MOVE_SPEED`** (`main.asm`, aim/move tuning; default $0140 = 1.25 px/frame) —
  how fast the player moves. It is kept slow so per-step collision cannot tunnel a
  wall, so raise it carefully.
- **`SPAWN_PERIOD`** (`main.asm`, wave tuning; default 50 frames) — the gap between
  enemy wave spawns. Lower it for a denser, harder swarm.
- **`BULLET_SPEED`** (`main.asm`, bullet tuning; default $0300 = 3 px/frame) — how
  fast your shots travel (with `BULLET_TTL`, this sets the range). Raise it for
  snappier fire.

## How it's verified

- **Build:** `make m7_oshoot` (the `LDCFG: lorom_64k.cfg` sentinel selects a 64KB
  image whose BANK1 holds the 32KB Mode-7 floor-map blob). Negative-control
  variants (`-DNO_COLLISION`, `-DBULLET_PROJ_FORWARD`, `-DNO_BULLET_COLLISION`,
  `-DDBG_FROZEN_BULLET`) each break one behavior to prove the tests non-vacuous;
  build them via `build_m7_oshoot_variants.sh`.
- **Test:** `python -m pytest tests/test_m7_oshoot.py -q` — reads the rendered
  output: the floor rotates to the held heading; the hero stays centred and
  upright; a wall blocks the hero (per-axis slide); bullets fire along the facing
  and stay glued to the rotating floor; enemy waves chase and are killed by
  bullets; and a hero-enemy contact knocks the hero back.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/m7_oshoot.sfc', run_seconds=1.5); r.take_screenshot('/tmp/m7_oshoot.png'); r.stop()"`
