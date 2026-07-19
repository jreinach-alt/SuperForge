# stomper — stomp the patrollers (jump-to-defeat combat)

## What it is

The patrol demo with a way to fight back: two magenta enemies pace fixed beats,
and now landing on one from above defeats it (it vanishes, you bounce off).
Touch one any other way and you are knocked back to spawn. A "FOES" counter
ticks down per stomp; clear both and the screen reads CLEAR and the game keeps
running. It is the smallest complete demo of stomp combat over the kit's jumper
physics and patrol AI.

| Button | Action |
|---|---|
| **D-pad left / right** | move |
| **A** | jump (fixed height) |

Defeat an enemy by landing on its head; any other contact hurts you.

## What it teaches

- **Stomp-vs-hurt resolution** — `sf_enemy.inc` (`sf_stomp_check`): one call per
  enemy returns land-on-top (stomp: cull the enemy, bounce the player, count
  down) versus side/underneath contact (hurt: knock back to spawn). The player's
  falling velocity is what distinguishes the two.
- **Patrol AI, culled when dead** — `sf_enemy.inc` (`sf_patrol_step`): each enemy
  paces its beat only while its alive flag is set, so a defeated enemy stops
  moving and stops drawing.
- **Jumper physics + tile collision** — `sf_physics.inc` (`sf_jump`,
  `sf_physics_step`) and `sf_map.inc` (`sf_solid_box`): a fixed-height jump, then
  the integrator resolves gravity, landing, and the solid walls of the arena.
- **A live HUD counter** — `sf_text.inc` (`print`, `sf_print_u16`): the FOES
  number is reprinted each time it changes, and CLEAR is printed once both
  enemies are down.

## Three things to tweak

- **`SPEED`** (`main.asm`, in the equates; default 2) — the player's move step in
  pixels per frame. Raise it to line up stomps more easily.
- **`SPAWN_X` / `SPAWN_Y`** (`main.asm`, in the equates; default 200, 200) —
  where the player starts and returns to after a hurt. Move it nearer an enemy
  to make the knock-back sting less.
- **`OBJ_MAGEN`** (`main.asm`, in the equates) — the enemies' colour as a 15-bit
  BGR value. Change it to recolour the patrollers.

## How it's verified

- **Build:** `make stomper` (-> `build/stomper.sfc`).
- **Test:** `python -m pytest tests/test_stomper.py -q` — closed-loop bots read
  the rendered output: driving the player onto an enemy from above culls its
  sprite (magenta pixels drop), bounces the player (its y trace dips then rises),
  and ticks the FOES digit down; side contact knocks the player back without
  killing the enemy; and CLEAR appears only once both enemies are defeated.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/stomper.sfc', run_seconds=1.0); r.take_screenshot('/tmp/stomper.png'); r.stop()"`
