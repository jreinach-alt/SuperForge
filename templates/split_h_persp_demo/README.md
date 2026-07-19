# split_h_persp_demo — two live perspective Mode-7 camera bands

## What it is

The perspective sibling of `split_h_matrix_demo`: two genuinely-different
*perspective* views of ONE flat top-down Mode-7 world, stacked at a clean
single-scanline seam, each a full per-scanline trapezoid — and both animating on
their own. The top band is the live engine perspective renderer auto-rotating;
the bottom band is a second camera that zoom-loops through precomputed poses over
a different world region. It is the two-live-cameras-over-one-world pattern (the
2-player top/bottom racer shape) taken to its perspective limit.

| Input | Action |
|---|---|
| — | none; autonomous. Camera A rotates and camera B zoom-loops on their own. |

### The build variants

`build_split_h_persp_variants.sh` emits the matrix. Most exist to drive the test
oracles (deterministic stills and non-vacuity **controls**), not to be watched:

**Showcase**

| Build | What it is |
|---|---|
| `split_h_persp_demo` (default) | Both cameras animate: A rotates, B zoom-loops. |
| `_sky` | Adds a backdrop sky band above the horizon (`-DSKY_HORIZON`). |
| `_freeze` | Camera A frozen; camera B keeps zoom-looping. |
| `_holdb` | Camera B held at pose 0; camera A keeps rotating. |

**Test instruments & controls** (deterministic; drive the oracles)

| Build | Role |
|---|---|
| `_still` | Both cameras frozen — the deterministic still the seam/clean tests read. |
| `_stillnoseam` | Camera A everywhere + frozen — the band-A baseline. |
| `_noseam` | Skip the band-2 splice — the "two bands differ" non-vacuity control. |
| `_stillsame` | Camera B's origin folded onto camera A — world-position control. |
| `_stillfixed` | The buggy fixed-buffer splice — the temporal-stability negative control. |
| `_latch` / `_stilllatch` | A code-side write-twice during active display — the latch-tear control. |
| `_stillsky` | The still `_sky` frame the sky/floor framebuffer test samples. |

## What it teaches

- **Two live perspective cameras over one map** — one seam, one shared low-32 KB
  VRAM, no extra VRAM; camera A is the live `sf_mode7_perspective` /
  `sf_mode7_tick` solve, camera B is spliced over band 2 via
  `sf_split_h_persp_capture` / the engine band splice
  ([`lib/macros/sf_split_h.inc`](../../lib/macros/sf_split_h.inc),
  [`lib/macros/sf_mode7.inc`](../../lib/macros/sf_mode7.inc)).
- **Why the second camera is precomputed** — one live per-scanline solve already
  costs most of a 60 fps frame (measured in
  [`tests/persp_cycles_test.asm`](../../tests/persp_cycles_test.asm)), and a second
  solve would also double-flip the perspective double buffer and tear it. So
  camera B's poses are solved once at boot into WRAM and spliced per frame.
- **The active-buffer apply-hook rule** — the splice must target the freshly
  flipped active buffer every frame, or a ~30 Hz flicker appears (the
  `-DFIXED_BUFFER_SPLICE` control reinstates that bug on purpose).
- **An independent world position per band** — two 1-channel splices on the
  Mode-7 origin (`M7X/M7Y` centre and `M7HOFS/M7VOFS` scroll), on channels the
  perspective renderer never owns. Deep dive:
  [`docs/guides/split_h.md`](../../docs/guides/split_h.md).

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`B_POSX`** (default 768) — camera B's world X, on the warm (red) stripe. Move
   it toward 512 and band 2 samples the cool stripe, so its red signal fades.
2. **`A_S1`** (default 96) — camera A's near-scale (its zoom). Change it and the
   top floor recedes at a different rate.
3. **`SEAM`** (default 112) — the seam scanline. Move it to grow one band at the
   other's expense (the band-2 byte offsets track it automatically).

## How it's verified

```bash
make split_h_persp_demo
bash templates/split_h_persp_demo/build_split_h_persp_variants.sh   # the -D matrix
python -m pytest tests/test_split_h_persp_demo.py -q
```

[`tests/test_split_h_persp_demo.py`](../../tests/test_split_h_persp_demo.py) reads
the rendered framebuffer: the two bands are distinct cameras (and collapse on
`-DNO_SEAM`), each animates on its own driver, the seam is a clean single scanline,
band 2 samples a different-coloured world region (folded on `-DSAME_CENTER`), and
the scene is temporally stable across consecutive frames (flickers on
`-DFIXED_BUFFER_SPLICE`). The solve-budget gate is
[`tests/persp_cycles_test.asm`](../../tests/persp_cycles_test.asm). To watch it,
boot `build/split_h_persp_demo.sfc` in any SNES emulator (or drive it from
`MesenRunner`, as the tests do).
