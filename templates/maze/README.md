# maze — walk a walled room with tile collision

## What it is

A red player you move with the d-pad through a grey walled room: a border wall
plus two interior walls, all built from one solid-flagged tile. The movement is
the canonical per-axis move-check — compute the tentative position, test it
against the map, keep it only if the cell is clear — so you slide along a wall
instead of sticking to it. It is the smallest complete demo of tile collision.

| Button | Action |
|---|---|
| **D-pad** | move the player (slides along walls, never tunnels through) |

## What it teaches

- **Tile collision** — `sf_map.inc` (`sf_tile_flags`, `sf_solid_box`): mark a
  tile id solid once, then `sf_solid_box` samples the player's box against the
  tilemap and reports blocked/clear.
- **The per-axis move-check** — X and Y are tested and committed separately, so
  a diagonal push into a wall keeps the free axis moving (a slide) instead of
  cancelling the whole move (a stick). This is the reusable movement idiom the
  jumper and patrol rails build on.
- **Building a tilemap with `mset`** — the border and interior walls are drawn
  cell-by-cell into the BG1 tilemap at boot; `gfxmode #1` sets a 32x32 map.
- **No-tunnel movement** — `SPEED` stays under one tile per frame so a single
  step cannot cross a wall cell.

## Three things to tweak

- **`SPEED`** (`main.asm`, in the equates) — the player's move step in pixels
  per frame. Keep it under 8 (one tile) so the collision can never be skipped
  over in a single step.
- **The interior walls** (`main.asm`, the `@wall_a` / `@wall_b` build loops in
  INIT) — the `mset` column/row/count values place the two inner walls. Change
  them to redraw the room; they read solid because tile 2 is flagged
  `SF_FLAG_SOLID`.
- **`OBJ_RED`** (`main.asm`, in the equates) — the player's colour as a 15-bit
  BGR value. Change it to recolour the sprite.

## How it's verified

- **Build:** `make maze` (-> `build/maze.sfc`).
- **Test:** `python -m pytest tests/test_maze.py -q` — reads the rendered
  result: grey walls and the red player are visible; the player moves freely in
  open floor on all four axes; walking into the left, right, top, bottom, and an
  interior wall stops AT the wall edge (no overlap, no pass-through); and the
  free axis still slides along a wall and can reach the gap below it.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/maze.sfc', run_seconds=1.0); r.take_screenshot('/tmp/maze.png'); r.stop()"`
