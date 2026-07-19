# patrol — dodge patrolling enemies (enemy patrol + the whole kit)

## What it is

Two magenta enemies pace their beats — one on the ground between two low walls,
one on a floating platform turning at its ledges — while a red player runs and
jumps through. Touching an enemy knocks the player back to the spawn and ticks a
`HITS 00000` counter; getting past them is the game. It is the rail that
composes every kit surface at once: sprites, BG terrain, a text HUD, tile
collision, jump physics, and enemy patrol.

| Button | Action |
|---|---|
| **D-pad left/right** | run |
| **A** | jump |

## What it teaches

- **Enemy patrol** — `sf_enemy.inc` (`sf_patrol_step`): an enemy paces back and
  forth and turns at its bounds. The ground enemy bounces between two walls; the
  ledge enemy uses a leading-corner check so it turns before it overhangs its
  platform.
- **Contact and knockback** — `sf_collision.inc` (`col_box`) tests the player
  box against each enemy; an overlap respawns the player at `SPAWN_X`/`SPAWN_Y`,
  bumps `HITS`, and reprints the counter (`sf_text.inc`).
- **Composition** — the same per-axis move-check (`sf_map.inc`) and physics
  step (`sf_physics.inc`) as the jumper rail, plus sprites, terrain, and the
  HUD, all driven from one `game_loop`. This is the reference for how the kit's
  surfaces fit together in one game.
- **jmp trampolines** — the contact gates jump around `col_box` expansions
  because a short branch cannot span them; the named labels here show that
  idiom.

## Three things to tweak

- **`SPEED`** (`main.asm`, in the equates) — the player's run step in pixels per
  frame. Raise it to move faster between the enemy beats.
- **`SPAWN_X` / `SPAWN_Y`** (`main.asm`, in the equates) — where the player
  starts and respawns after a hit. Move it into a beat and every respawn lands
  you in danger.
- **`OBJ_MAGEN`** (`main.asm`, in the equates) — the enemy colour as a 15-bit
  BGR value. Change it to recolour both patrollers.

## How it's verified

- **Build:** `make patrol` (-> `build/patrol.sfc`).
- **Test:** `python -m pytest tests/test_patrol.py -q` — drives a scripted trace
  ROM (`build/patrol_test.sfc`, built by `make testroms`) that records each
  enemy's x after every patrol step, and verifies the whole bounce cycle from
  the recorded trace: exact turn bounds on both sides (walls 40..104, ledge
  144..192), multiple round trips at constant speed with clean single-step
  turns, and the ledge patroller never overhanging its platform.
- **See it:** boot the playable rail headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/patrol.sfc', run_seconds=1.0); r.take_screenshot('/tmp/patrol.png'); r.stop()"`
