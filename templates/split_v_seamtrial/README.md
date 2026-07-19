# split_v_seamtrial — the seamless vertical-split trial

## What it is

A trial rail that proves, in isolation, the seamless left/right camera split the
`split_v_fight` fighting rail is built on. One stage is viewed by two cameras
(`camA = mid - spread`, `camB = mid + spread`) either side of an always-on centre
window. At `spread = 0` the halves are pixel-identical, so the ever-present seam is
invisible; as `spread` grows the halves diverge and a beveled BG3 bar opens from
zero width to mark the divide. It runs on its own — `spread` sweeps
`0 -> SPREAD_MAX -> 0` as a triangle wave, so the separate-then-merge cycle plays
out with no input. It exists as a stepping stone: it isolates the seamless
mechanism so `split_v_fight` can drive that same divergence from the fighter
distance without also debugging the fighting loop.

| Input | Action |
|---|---|
| — | none; autonomous. `spread` sweeps out and back on its own. |

Compile-time knobs (no variant script): `-DHOLD=n` freezes `spread` at `n` px for
a race-free framebuffer still; `-DNOWIN` compiles the window out for a no-split
single-camera reference.

## What it teaches

- **A seamless vertical split from continuous camera divergence** — a single
  centre window (`window 1`) held on forever, with the two halves scrolled to
  `mid ± spread`. Because a PPU window boundary is a single-pixel edge with no gap,
  identical halves hide the seam completely. Built on the window macros in
  [`lib/macros/sf_window.inc`](../../lib/macros/sf_window.inc); the composed rail
  folds this into [`lib/macros/sf_split_v.inc`](../../lib/macros/sf_split_v.inc).
- **A zero-sprite beveled divider on BG3** — a 3-tone bar (dark / mid / light)
  uploaded to BG3 CHR at word `$7000` and revealed only inside a second window
  band whose half-width `hw = spread>>4` ramps from zero, so it steals no screen
  width at merge. Shows the forced-blank discipline for VRAM/CGRAM uploads and the
  15-bit VRAM address wrap that forces the non-default BG3 CHR base.
- **Static BG3 tilemap vs. the NMI's one-VBlank triple-map DMA** — the bar map is
  written both into the engine's BG3 shadow and directly under forced blank, so a
  truncated VBlank transfer can never drop rows of the divider.
- **The design write-up:** [`docs/guides/split_v.md`](../../docs/guides/split_v.md).

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`SPREAD_MAX`** (equates block; default 48) — the fullest divergence the sweep
   reaches. Raise it and the halves part further (and the divider band widens);
   lower it and the split stays subtle.
2. **`SPR_STEP`** (default `$00C0`, 0.75 px/frame in 8.8) — how fast `spread`
   sweeps. Larger opens and closes the split faster; smaller makes it glacial.
3. **`MID_CAM`** (default 96) — the shared viewpoint both cameras straddle. Change
   it to frame a different column of the stage at merge.

## How it's verified

```bash
make split_v_seamtrial          # default 32K build (no HDMA engine)
```

This trial rail has no dedicated pytest suite — its seamless mechanism is locked
by the rendered-output asserts of the rail it graduated into,
[`tests/test_split_v_fight.py`](../../tests/test_split_v_fight.py) (merge is
pixel-identical to a no-split reference; the beveled bar ramps from zero width).
To watch the trial itself, boot the ROM headless and grab a frame:

```bash
PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/split_v_seamtrial.sfc', run_seconds=1.5); r.take_screenshot('/tmp/split_v_seamtrial.png'); r.stop()"
```

The `.sfc` also runs in any SNES emulator (Mesen2, bsnes, snes9x) or on real
hardware via a flashcart.
