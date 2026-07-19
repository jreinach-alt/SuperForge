# split_v_demo — minimal vertical dual-view (the sf_split_v demo)

## What it is

The smallest demonstration of a vertical left/right split: ONE shared scrolling
stage rendered through TWO BG-layer cameras, each clipped to its half of the
screen by the PPU window system. Player 1 drives the left camera, player 2 the
right; a coloured backdrop bar (zero sprites) marks the seam, and a red marker
stands in each half. It proves the primitive, not a game — the seamless,
distance-driven version is the `split_v_fight` rail.

| Input | Action |
|---|---|
| P1 (port 0) D-pad ← / → | scroll camera A (left half) |
| P2 (port 1) D-pad ← / → | scroll camera B (right half) |
| P1 L / R shoulders | move the seam, clamped to `[SEAM_LO, SEAM_HI]` |

The `-DAUTODEMO` build takes no input: it pins the seam at centre and pans the two
cameras in opposite directions for the classic split-screen look.

## What it teaches

- **A vertical split from the PPU window system** — `window 1` clips BG1 (camera
  A) to the left and BG2 (camera B) to the right; `window 2` is a thin band at the
  seam that masks the BGs so the backdrop colour (CGRAM 0) shows through as the
  bar. All from [`lib/macros/sf_split_v.inc`](../../lib/macros/sf_split_v.inc)
  (`sf_split_v_colorseam` / `sf_split_v_move` / `sf_split_v_cameras`), built on
  [`lib/macros/sf_window.inc`](../../lib/macros/sf_window.inc). Design write-up:
  [`docs/guides/split_v.md`](../../docs/guides/split_v.md).
- **One VRAM copy, two cameras** — BG2 is pointed at BG1's tilemap (`BG2SC=$58`)
  and CHR (`BG12NBA=$22`), so both cameras read a single shared upload and only the
  scroll differs. Halves the VRAM of a naive two-copy layout.
- **A diagonal seam via HDMA** — the `-DDIAGONAL` build streams `WH0/WH2/WH3` per
  scanline so the split (and its backdrop band) slant, pulling in the HDMA engine.
- **Per-half OBJ clipping** — the `-DOBJ_CLIP` build confines sprites to one half,
  so a marker straddling the seam is clipped across it.

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`BAND_HW`** (default 6) — the seam bar's half-width; the bar is `2*BAND_HW`
   px wide. Raise it for a fatter divider, drop it to 0 for a hairline seam.
2. **`CAM_SPD`** (default 2) — camera scroll speed in px/frame. Raise it and the
   halves pan faster under the D-pad.
3. **`CAM_B0`** (default 192) — camera B's initial scroll. Change it to frame the
   right half on a different part of the asymmetric landscape at boot.

## How it's verified

```bash
make split_v_demo
bash templates/split_v_demo/build_split_v_variants.sh   # the -D control ROMs
python -m pytest tests/test_split_v_demo.py -q
```

[`tests/test_split_v_demo.py`](../../tests/test_split_v_demo.py) reads the rendered
framebuffer on the cycle-accurate emulator: the screen splits into two distinct
regions (and that signature vanishes on the `-DNO_WINDOW` control), the seam bar
renders its colour, the diagonal build slants it, and per-half OBJ clipping crops
the straddling marker. To watch it, boot `build/split_v_demo_autodemo.sfc` in any
SNES emulator (or drive it from `MesenRunner`, as the tests do).
