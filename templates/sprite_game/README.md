# sprite_game — a minimal catch game (move, collide, score)

## What it is

The smallest end-to-end game in the kit: a red player you steer with the d-pad
and a yellow dot to catch. Overlap the dot and it jumps to the next of four
preset spots while your score ticks up. It wires movement, two sprites,
box collision, and game state together with nothing but the macro library — the
starting point you grow a real game out of.

| Button | Action |
|---|---|
| **D-pad** | move the red player (up / down / left / right) |

## What it teaches

- **Box-vs-box collision** — `sf_collision.inc` (`col_box`): each frame the
  player's 8x8 box is tested against the dot's 8x8 box; an overlap is the
  "catch". The catch also self-debounces — the dot moves away the same frame, so
  one pass counts once.
- **Multi-sprite compositing** — `sf_sprite.inc` (`spr`, `spr_clear`): the loop
  clears OAM and redraws the player (OBJ palette 0, red) and the dot (OBJ
  palette 1, yellow) every frame, so two independently-coloured sprites share
  one tile.
- **Per-axis d-pad movement + game state** — X and Y each add or subtract
  `SPEED` from the player's DP position; the catch increments `SCORE` and steps
  `DOT_IDX` through the `dot_presets` table (masked to wrap at 4).

## Three things to tweak

- **`SPEED`** (`main.asm`, in the equates; default 2) — the player's move step
  in pixels per frame. Raise it to dart around faster.
- **`dot_presets`** (`main.asm`, in DATA) — the four (x, y) spots the dot cycles
  through on each catch. Add or edit entries (keep the `and #$0003` mask in sync
  if you change the count) to move the chase around.
- **`OBJ_YELLOW`** (`main.asm`, in the equates) — the dot's colour as a 15-bit
  BGR value. Change it to recolour the dot.

## How it's verified

- **Build:** `make sprite_game` (-> `build/sprite_game.sfc`).
- **Test:** `python -m pytest tests/test_sprite_game.py -q` — reads the rendered
  result: both sprites are visible in the right colours; driving the player onto
  the dot increments the score and relocates the dot (checked twice, so the
  cycle really advances); and all four movement directions work. Deterministic —
  no RNG.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/sprite_game.sfc', run_seconds=1.0); r.take_screenshot('/tmp/sprite_game.png'); r.stop()"`
