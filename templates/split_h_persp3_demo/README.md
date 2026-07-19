# split_h_persp3_demo — three stacked Mode-7 camera bands

## What it is

A demo rail that stacks THREE horizontal views of ONE flat top-down Mode-7 world,
each band a different camera matrix (a different zoom) swapped in at a seam
scanline by HDMA. Two seams, three distinct camera regions, one shared map in
VRAM. It is the three-camera extension of the two-band `split_h_matrix_demo`, and
it proves the only budget-viable path to extra Mode-7 cameras: flat *precomputed*
per-band matrices instead of a live perspective solve per band.

| Input | Action |
|---|---|
| — | none; autonomous. The bands are entirely HDMA-driven; the loop idles. |

The three on-screen checker periods — 8 px (top, 1.0x), 32 px (middle, 0.25x),
16 px (bottom, 0.5x) — are the "three distinct cameras" signal. The `-DONE_CAM`
build collapses all three bands to camera A's scale as a non-vacuity control.

## What it teaches

- **Multiple Mode-7 cameras for ~nil CPU** — the perspective rail
  (`split_h_persp_demo`) measured that a single live per-scanline solve already
  costs most of a 60 fps frame, so a second is out of budget. This rail instead
  emits NON-REPEAT HDMA tables (2 HBlank writes per band per channel) that hold a
  CONSTANT matrix per band, so three cameras cost the same as one.
- **The matrix-band compiler** — `sf_split_h_matrix_bands` in
  [`lib/macros/sf_split_h.inc`](../../lib/macros/sf_split_h.inc) takes one list of
  `(count, M7A, M7B, M7C, M7D)` tuples and binds the two NON-REPEAT tables (AB and
  CD, `DMAP $03`) on two allocator channels.
- **The BYPASS-not-coexist rule** — because the engine's perspective HDMA also
  owns `M7A-D`, this rail does the minimal Mode-7 init by hand (`BGMODE=7`,
  `M7SEL`, map + CGRAM upload, `M7X/Y` once under forced blank) and drives the
  matrix itself. `M7X/Y/M7HOFS/VOFS` are set once under forced blank, so the
  write-twice latch can never tear.
- Deep dive with the measured cost chain:
  [`docs/guides/split_h.md`](../../docs/guides/split_h.md).

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`SCALE_B`** (default `$0040` = 0.25) — the middle band's zoom in 8.8 fixed.
   Raise it toward `$0100` and the middle checker shrinks toward the top band's
   8-px period; lower it and the middle magnifies further.
2. **`SEAM1` / `SEAM2`** (default 75 / 150) — the two seam scanlines. Move them to
   resize the three bands (each band's line count is derived from these).
3. **`COLOR_LIGHT_GREEN`** (default `$03E0`) — one of the two checker colours
   (15-bit BGR). Change it to recolour the world all three cameras look at.

## How it's verified

```bash
make split_h_persp3_demo
bash templates/split_h_persp3_demo/build_split_h_persp3_variants.sh   # the -DONE_CAM control
python -m pytest tests/test_split_h_persp3_demo.py -q
```

[`tests/test_split_h_persp3_demo.py`](../../tests/test_split_h_persp3_demo.py)
reads the rendered framebuffer: three distinct checker periods (that collapse to
one on the `-DONE_CAM` control), two clean single-scanline seams, and temporal
stability (the scene is HDMA-static, so there is no double buffer to desync). To
watch it, boot `build/split_h_persp3_demo.sfc` in any SNES emulator (or drive it
from `MesenRunner`, as the tests do).
