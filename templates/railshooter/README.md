# railshooter — Mode 7 forward rail shooter (approaching hazards on a rushing floor)

## What it is

An on-rails forward shooter: the Mode 7 ground rushes toward you at a constant
speed, hazards approach out of the horizon and grow as they near, and you strafe
between lanes and fire. The floor is a single Mode 7 background (the hardware
scales and rotates it for free); the ship, the obstacles, the bullets, and the
lock-on reticle are OBJ sprites composited on top. It shares the racer's Mode 7
spine but swaps in a rail driver (auto-advance, never stops) and a strafing ship.

| Button | Action |
|---|---|
| **D-pad left / right** | strafe (slides the camera laterally and banks the ship) |
| **A** | fire a forward bullet |

Forward motion is automatic — there is no throttle.

## What it teaches

- **A decoupled pinhole (1/z) projection, NOT the Mode 7 matrix inverse** — the
  design at the heart of the rail (full model:
  [`docs/guides/pseudo3d_rail.md`](../../docs/guides/pseudo3d_rail.md)). Each
  obstacle and bullet carries a forward depth `z` in world pixels; `sf_rail.inc`
  + `engine/mode7_project.asm` project it through a baked 1/z LUT
  (`assets/mode7_project.inc`, from `assets/make_project_lut.py`) to a scanline,
  scale, and size tier, **fully decoupled from the Mode 7 affine matrix** — the
  grid is pure backdrop. (Anchoring hazards to the matrix gives only ~14
  world-px of forward depth; the pinhole z axis is arbitrary, so an obstacle
  descends smoothly over ~50 frames instead of snapping in 2-3.)
- **Pre-drawn size tiers (the SNES cannot scale sprites)** — an object "grows"
  by swapping between four pre-drawn size frames by distance (`rail_tier_tbl`).
  A grow-only hysteresis (`obs_tier_hysteresis`, `TIER_HYST`) stops the tier from
  flickering when `z` sits on a threshold.
- **Depth-sorted OAM emit with no sort** — `sf_rail_draw_sorted`
  (`engine/rail_draw.asm`) buckets the live actors by their size tier and emits
  them tier 0 -> 3 into ascending OAM slots, so nearer obstacles (lower slot)
  draw in front — correct back-to-front layering re-derived from depth every
  frame, decoupled from an actor's pool slot.
- **Mode 7 floor + OBJ + the sky split** — `sf_mode7.inc`
  (`sf_mode7_perspective`, `sf_mode7_cam`): the map fills VRAM words
  `$0000-$3FFF`, so `OBSEL = $62` moves the OBJ name base to word `$4000`; a CH2
  HDMA TM-split turns BG1 off above the horizon to reveal the CGRAM[0] sky; and
  strafing banks the plane a few heading units and eases back (`BANK_MAX`).
- **Pooled actors** — `sf_pool.inc` (`sf_pool_spawn`, `sf_pool_kill_x`): a
  6-obstacle field that recycles far ahead on pass, and a 4-bullet pool that
  recedes toward the horizon; a nested loop culls any bullet/obstacle pair inside
  the hit window.

## Three things to tweak

- **`RAIL_SPEED`** (`main.asm`, in the tuning block; default 6) — world pixels
  per frame the camera auto-advances. Raise it and the floor rushes faster.
- **`RAIL_DEPTH_STEP`** (`main.asm`, in the depth tuning; default 12) — the `z`
  an obstacle closes per frame (~51-frame approach). Lower it for a slower, more
  drawn-out descent from the horizon.
- **`obs_lane_x`** (`main.asm`, in DATA; `.word 512, 464, 560, 488`) — the four
  lateral lanes obstacles spawn into, around the rail centre (512). Spread them
  wider or add lanes to change the weave field.

> Tuning the perspective curve itself (camera height, focal length, horizon,
> the tier thresholds) means editing `assets/make_project_lut.py` and
> regenerating `mode7_project.inc` — those constants are baked into the LUT, not
> read at runtime. See the guide's "which constant lives where" table.

## How it's verified

- **Build:** `make railshooter` (the generic rule reads the `LDCFG: lorom_64k.cfg`
  sentinel — a 64KB image whose BANK1 holds the 32KB Mode 7 ground blob).
- **Test:** `python -m pytest tests/test_railshooter.py -q` — reads the rendered
  output: with no input the camera keeps advancing (a distinct sky sits above the
  grid); LEFT vs RIGHT move the camera and ship opposite ways and bank the plane;
  a tracked obstacle's OAM screen_y descends roughly monotonically from the
  horizon while its tile and size bit step through the four tiers; the depth-sort
  holds (no far/small obstacle sits at a lower OAM slot than a near/large one);
  and firing spawns a receding bullet that removes an obstacle on contact.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/railshooter.sfc', run_seconds=1.5); r.take_screenshot('/tmp/railshooter.png'); r.stop()"`
