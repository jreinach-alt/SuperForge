# mode7_chamber — Mode 7 "barrel chamber" effect demo

## What it is

An autonomous Mode 7 tech demo: a stone-textured floor bows into a barrel and
rolls endlessly beneath a Mode 1 HUD band, darkened top and bottom by a
brightness vignette. There is no rotation matrix — the angle is held constant and
the floor texture scrolls vertically, so the "spin" you see is really a roll
through a fixed barrel bow. It layers four cooperating per-scanline HDMA effects
over one Mode 7 plane.

| Button | Action |
|---|---|
| (none) | autonomous demo — the roll drives itself; the joypad is not read |

## What it teaches

- **Four per-scanline HDMA effects over one Mode 7 plane** —
  `sf_mode7_chamber.inc`: `sf_mode7_barrel` bows M7A top->mid->bottom (the
  barrel); `sf_mode7_modesplit` drives BOTH $2105 (BGMODE) and $212C (TM) at
  scanline 32 to put a clean Mode 1 HUD band above the Mode 7 floor;
  `sf_mode7_vignette` ramps $2132 (COLDATA) for a depth vignette. Each uses a
  distinct HDMA channel (CH2-CH4) so none collides with the engine's Mode 7
  matrix channels (CH5/CH6).
- **Apparent rotation from a vertical scroll** — with the angle held constant a
  16.8 `posy` accumulator scrolls the texture and wraps to the 1024px periodic
  map (M7SEL wrap). Because the angle never changes, the costly perspective-table
  rebuild runs ONCE (at init), not per frame — that is what buys the cycle budget.
- **A self-driving motion model** — the roll runs in "legs": each leg is three
  surges (accelerate smoothly to a random peak, then decelerate faster toward a
  creep), then a dead-stop hold, then a reverse. Forward and reverse draw their
  random peaks from SEPARATE Galois LFSR streams, so each direction keeps its own
  variance. `sf_fx.inc` colour math (additive) is what makes the COLDATA vignette
  visible.

## Three things to tweak

- **`PV_SH_CHAMBER`** (`main.asm`, camera equates; default 1440) — the vertical
  texel height, the "make the rows narrow" knob. A larger value squashes the
  floor rows vertically, packing more horizontal detail per screen; detail peaks
  around 1440 and beyond that the rows go sub-texel and alias.
- **`PEAK_CAP`** (`main.asm`, roll equates; default $0400 = 4.0 px/frame) — the
  hard cap on a surge's peak speed. Raise it for a faster, wilder roll; lower it
  for a slow, stately drift.
- **`HOLD_FRAMES`** (`main.asm`, roll equates; default 30) — how many frames the
  floor sits dead-stopped between legs before it reverses (60 fps, so ~0.5 s).
  Raise it for a longer pause at each turnaround.

## How it's verified

- **Build:** `make mode7_chamber` (the `LDCFG: lorom_64k.cfg` sentinel selects a
  64KB image whose BANK1 holds the 32KB Mode 7 chamber-map blob).
- **Test:** `python -m pytest tests/test_mode7_chamber.py -q` — reads the rendered
  output: the floor undulates (posy rides the surge/hold cycle, no rotation
  matrix); the floor bows (per-scanline M7A varies top->mid->bottom); a clean
  Mode 1 HUD band sits above the Mode 7 floor; and the vignette leaves the mid
  band brighter than the top and bottom.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/mode7_chamber.sfc', run_seconds=1.5); r.take_screenshot('/tmp/mode7_chamber.png'); r.stop()"`
