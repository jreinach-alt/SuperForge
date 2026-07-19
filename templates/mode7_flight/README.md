# mode7_flight — Mode 7 free-flight airship

## What it is

Pilot an airship freely over a Mode 7 perspective floor. Unlike the racer's
forward-lock you turn and throttle in any direction, and — the distinctive part —
you control ALTITUDE: climbing pushes the ground away (the perspective scale
grows) and descending brings it closer. An animated airship sits fixed on screen
while its ground shadow separates as you climb; the plane wraps, so you never
reach an edge.

| Button | Action |
|---|---|
| **D-pad left/right** | turn heading (rotate the Mode 7 angle) |
| **B** | throttle forward along heading; release to coast to a hover |
| **Y** | reverse thrust (steps the camera backward) |
| **L shoulder** | descend — the ground approaches |
| **R shoulder** | climb — the ground recedes |

## What it teaches

- **Altitude-driven perspective scale** — `sf_mode7.inc` `sf_mode7_scale`: every
  frame `compute_scales` interpolates the near/far scales (S0/S1) from an 8-bit
  altitude and re-installs them, so climbing and descending zoom the whole Mode 7
  floor. This is the piece that sets flight apart from the fixed-scale racer.
- **A signed-8.8 speed integrator** — forward (B), reverse (Y), and hover all fall
  out of ONE `sincos` -> `smul16` step because the speed is signed; a negative
  speed steps the camera backward for free.
- **A sky above a single-layer plane** — Mode 7 has one BG, so `arm_sky_split`
  runs a 2-band TM HDMA on CH2 that turns BG1 off above the horizon, revealing the
  CGRAM[0] sky-blue backdrop. OBJ stays on in both bands so the airship draws over
  the sky.
- **OBJ over Mode 7** — the map fills VRAM words $0000-$3FFF, so `OBSEL=$62` moves
  the OBJ name base to word $4000; the airship's two propeller frames and the two
  shadow sizes upload there.

## Three things to tweak

- **`SPEED_CAP`** (`main.asm`, throttle tuning; default $0300 = 3 px/frame) — the
  top forward speed. Raise it for a faster airship; `SPEED_REV` is the reverse cap.
- **`ALT_STEP`** (`main.asm`, altitude tuning; default 3) — how much the altitude
  changes per held L/R frame. Raise it to climb and dive more quickly.
- **`S0_HIGH`** (`main.asm`, altitude tuning; default 1180) — the far-scale at
  maximum altitude. Raise it so the ground shrinks away more dramatically at the
  top of a climb (`S0_LOW` sets the close-up scale at the floor).

## How it's verified

- **Build:** `make mode7_flight` (the `LDCFG: lorom_64k.cfg` sentinel selects a
  64KB image whose BANK1 holds the 32KB Mode 7 ground-map blob).
- **Test:** `python -m pytest tests/test_mode7_flight.py -q` — reads the rendered
  output: the ground floor renders under a sky band; throttle moves the camera
  over the plane and reverse backs it up; climbing raises the derived scale (the
  ground recedes) and descending lowers it; and the airship + shadow render, the
  shadow separating as altitude rises.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/mode7_flight.sfc', run_seconds=1.5); r.take_screenshot('/tmp/mode7_flight.png'); r.stop()"`
