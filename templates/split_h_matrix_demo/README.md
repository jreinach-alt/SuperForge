# split_h_matrix_demo — two stacked Mode-7 camera bands

## What it is

A demo rail that stacks TWO horizontal views of ONE flat top-down Mode-7 world,
each band rendered through a different camera matrix (a different zoom) swapped in
at the seam scanline by HDMA. One seam, two distinct camera regions, one shared
map in VRAM. It is the dedicated two-camera rail for the `sf_split_h` matrix-band
primitive, and the two-band sibling of the three-band `split_h_persp3_demo`.

| Input | Action |
|---|---|
| — | none; autonomous. The bands are entirely HDMA-driven; the loop idles. |

The top band renders the 8x8 world checker at an 8-px on-screen period (1.0x
scale); the bottom at 32 px (0.25x). That 8-vs-32 ratio is the "two distinct
cameras" signal. The `-DAUTODEMO` build animates the bottom band's zoom each
frame; `-DNO_MATRIX_SPLIT` collapses both bands to one camera as a control.

## What it teaches

- **A second Mode-7 camera for ~nil CPU** — a flat *precomputed* matrix per band
  via `sf_split_h_matrix_bands` in
  [`lib/macros/sf_split_h.inc`](../../lib/macros/sf_split_h.inc): one list of
  `(count, M7A, M7B, M7C, M7D)` tuples compiled into two NON-REPEAT HDMA tables
  (`DMAP $03`) that each hold a constant matrix for their band. Two bands cost the
  same as one — no live perspective solve.
- **The NON-REPEAT trap** — each band's HDMA count byte has bit7 = 0, so the
  4-byte matrix unit transfers ONCE per band and holds. bit7 = 1 (REPEAT) would
  re-read every scanline, walk off the short table, and collapse the plane.
- **BYPASS not coexist** — because the engine's perspective HDMA also owns
  `M7A-D`, this rail does the minimal Mode-7 init by hand (`BGMODE=7`, `M7SEL`,
  map + CGRAM upload, `M7X/Y` once under forced blank) and drives the matrix
  itself. `M7X/Y/M7HOFS/VOFS` are set once under forced blank, so the write-twice
  latch can never tear.
- **Patching an HDMA table live** — the `-DAUTODEMO` build shadows the matrix
  tables in WRAM and rewrites the bottom band's scale word each VBlank (guard-safe
  under the NMI). Deep dive: [`docs/guides/split_h.md`](../../docs/guides/split_h.md).

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`SCALE_B`** (default `$0040` = 0.25) — the bottom band's zoom in 8.8 fixed.
   Raise it toward `$0100` and the bottom checker shrinks toward the top's 8-px
   period; lower it and it magnifies further.
2. **`SEAM`** (default 112) — the seam scanline where the top band ends and the
   bottom begins. Move it to resize the two bands.
3. **`COLOR_LIGHT_GREEN`** (default `$03E0`) — one of the two checker colours
   (15-bit BGR). Change it to recolour the world both cameras look at.

## How it's verified

```bash
make split_h_matrix_demo
bash templates/split_h_matrix_demo/build_split_h_matrix_variants.sh   # the -D controls
python -m pytest tests/test_split_h_matrix_demo.py -q
```

[`tests/test_split_h_matrix_demo.py`](../../tests/test_split_h_matrix_demo.py)
reads the rendered framebuffer: two distinct checker periods with the expected
~4x ratio (that collapses to one on the `-DNO_MATRIX_SPLIT` control), one clean
single-scanline seam, and one shared world in VRAM. To watch it, boot
`build/split_h_matrix_demo_autodemo.sfc` in any SNES emulator (or drive it from
`MesenRunner`, as the tests do).
