# jumper — run and jump across platforms (jump physics)

## What it is

A red player with gravity: run left and right with the d-pad, jump with A.
There is solid ground along the bottom, three floating platforms at rising
heights (each reachable from the one below), and a low overhang to bonk your
head on. The vertical axis is owned entirely by the physics step (take-off,
ascent, head bump, apex, descent, landing snap, rest); the horizontal axis is
the same per-axis move-check the maze rail uses.

| Button | Action |
|---|---|
| **D-pad left/right** | run |
| **A** | jump (only from the ground or a platform) |

## What it teaches

- **Jump physics as one call** — `sf_physics.inc` (`sf_jump`,
  `sf_physics_step`): `sf_jump` starts a jump only when grounded; `sf_physics_step`
  integrates 8.8 fixed-point velocity, applies gravity up to a terminal fall,
  handles head bumps and landing snap, and maintains the `grounded` flag.
- **Fixed-point vertical motion** — `PYF` is an 8.8 value; its high byte `PYI`
  is the pixel row used for collision probes and the sprite draw. Sub-pixel
  velocity is what makes the arc smooth instead of steppy.
- **Separated axes** — horizontal uses the tentative-move / `sf_solid_box`
  check (revert if solid); vertical is the physics step. Keeping them apart is
  what lets you slide under the overhang and land cleanly on a platform edge.
- **Assemble-time feel tuning** — gravity, jump velocity, and terminal fall are
  `.ifndef`-guarded, so a game can redefine them before the include.

## Three things to tweak

- **`SF_JUMP_VEL`** (define before `.include "sf_physics.inc"`, default `$0480`
  = 4.5 px/frame take-off) — the jump strength. Raise it for a higher jump;
  the default clears ~38 px.
- **`SF_GRAVITY`** (define before the include, default `$0040` = 0.25 px/f^2) —
  fall acceleration. Lower it for a floatier, moon-jump feel; raise it for a
  snappier drop.
- **`SPEED`** (`main.asm`, in the equates) — the horizontal run step in pixels
  per frame.

## How it's verified

- **Build:** `make jumper` (-> `build/jumper.sfc`).
- **Test:** `python -m pytest tests/test_jumper.py -q` — reads the rendered
  result and the physics outcome: the player boots resting on the ground at a
  stable y; a jump rises ~38 px and lands back at EXACTLY the rest y (full
  cycle); jumping from below onto a platform lands ON it (rest = platform
  top - 8); walking off a platform edge falls and lands below; and the overhang
  bonks the head (the ascent dies early, y never enters it).
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/jumper.sfc', run_seconds=1.0); r.take_screenshot('/tmp/jumper.png'); r.stop()"`
