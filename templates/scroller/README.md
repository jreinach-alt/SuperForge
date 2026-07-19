# scroller — scroll a tilemap background under a fixed sprite

## What it is

A background-scrolling demo: a green checkerboard fills BG1, and the d-pad
scrolls it in all four directions while a red sprite stays pinned at screen
centre, so the world appears to slide beneath it. It is the smallest
end-to-end tour of the SNES BG pipeline plus sprite-over-BG compositing — the
starting point you grow a camera-follow game out of.

| Button | Action |
|---|---|
| **D-pad** | scroll the world (each direction moves BG1 under the sprite) |

## What it teaches

- **The BG pipeline** — `sf_bg.inc` (`gfxmode`, `mset`, `scroll`): `gfxmode #1`
  turns on a 32x32 BG1 tilemap, the boot loop `mset`s a checkerboard into it
  cell by cell, and `scroll #1, CAM_X, CAM_Y` writes the camera into the BG1
  scroll shadows each frame.
- **Sprite-over-BG compositing** — `sf_sprite.inc` (`spr`, `spr_clear`): the
  sprite is redrawn every frame at a fixed screen position, so it composites on
  top of the moving background instead of scrolling with it.
- **Forced-blank uploads** — the tile art and palettes go to VRAM/CGRAM during
  the boot forced blank (`sf_load_bg_tile`, `sf_bg_color`, `sf_load_obj_tile`,
  `sf_obj_color`), before the screen turns on, because the PPU cannot take those
  writes mid-frame.

## Three things to tweak

- **`SPEED`** (`main.asm`, in the equates; default 2) — the scroll step in
  pixels per frame. Raise it and the world flies past; lower it for a slow
  drift.
- **`BG_GREEN`** (`main.asm`, in the equates) — the checkerboard colour as a
  15-bit BGR value. Change it to recolour the background.
- **The checkerboard build loop** (`main.asm`, `@row` / `@col` in INIT) — the
  `(mx ^ my) & 1` test picks each cell's tile. Swap the expression (or `mset` a
  different tile id) to draw a different map.

## How it's verified

- **Build:** `make scroller` (-> `build/scroller.sfc`).
- **Test:** `python -m pytest tests/test_scroller.py -q` — reads the rendered
  result: the green checkerboard and the red sprite are both visible; each of
  the four d-pad directions scrolls the BG the correct way (checked against both
  the on-screen pattern and the committed scroll shadows); and the sprite holds
  its screen position while the world moves under it.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/scroller.sfc', run_seconds=1.0); r.take_screenshot('/tmp/scroller.png'); r.stop()"`
