# scroll_run — run and jump across a two-screen scrolling level

## What it is

A 512px-wide run: sprint and jump from the left edge to the gold goal pillar at
the far right, over raised platforms and past solid pillars, with the camera
following you and clamping at both world edges. Reach the goal and it prints
GOAL and freezes. It is the compact demo of a scrolling level whose world is
wider than one screen — the crucial part being a platform that straddles the
seam between the two 256px background pages.

| Button | Action |
|---|---|
| **D-pad left / right** | run |
| **A** | jump (fixed height) |

Reaching the goal prints GOAL and freezes input.

## What it teaches

- **Scrolling levels with a page seam** — `sf_level.inc`
  (`sf_level_load`, `sf_level_solid_box`, `sf_level_physics_step`): the world is
  512px = two 256px BG pages, and collision + physics stay correct as the player
  crosses the seam (the platform at cols 30..34 spans col 32, the page boundary).
- **Camera follow with edge clamps** — `sf_camera.inc` (`sf_camera_follow`,
  `sf_clamp0`): the camera keeps the player near screen centre but clamps at 0
  and at the right edge, so you never scroll past the level.
- **Fixed-height jump physics** — `sf_physics.inc` (`sf_jump`): one edge-triggered
  take-off with no `sf_jump_cut`, so this jump is a fixed height (contrast the
  platformer's variable, hold-for-higher jump); `SF_GRAVITY` and `SF_JUMP_VEL`
  in that include tune the arc.
- **Goal detection + text** — the gold pillar (tile id 3) carries its own
  non-solid flag; the tile under the player's centre is probed each frame, and
  hitting the goal ends the game and prints GOAL with `sf_text.inc` (`print`).

## Three things to tweak

- **`SPEED`** (`main.asm`, in the equates; default 2) — the run step in pixels
  per frame. Raise it to sprint faster.
- **The `level` map** (`main.asm`, in DATA) — the 64x28 grid of tile IDs
  (2 = solid grey, 3 = gold goal). Move the goal, add pillars, or reshape the
  seam platform to redesign the course; the `.assert` keeps it exactly 28 rows.
- **`OBJ_RED`** (`main.asm`, in the equates) — the player's colour as a 15-bit
  BGR value. Change it to recolour the runner.

## How it's verified

- **Build:** `make scroll_run` (-> `build/scroll_run.sfc`).
- **Test:** `python -m pytest tests/test_scroll_run.py -q` — a closed-loop bot
  runs the level left to right and reads the rendered output at both camera
  extremes: the camera is clamped at the left edge on boot, follows the player
  past screen centre, the player crosses the page seam and the obstacle course,
  the camera clamps at the right edge, and touching the goal pillar ends the game
  (won state set, GOAL text on screen, input frozen).
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/scroll_run.sfc', run_seconds=1.0); r.take_screenshot('/tmp/scroll_run.png'); r.stop()"`
