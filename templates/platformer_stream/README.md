# platformer_stream — a playable platformer on a 4-screens-each-way streaming world

## What it is

A side-view platformer whose level is several screens **wide and tall** (128x128
tiles = 1024x1024 px = 4 screens per axis). You run and jump a hero through a
Four Seasons world that **streams seamlessly on both axes** as the camera follows
you — forward, back, up, down — with no pop-in, tearing, or black bands.
World-space collision blocks the walls and floors, and a 16-bit world-Y physics
integrator lets the hero span the full 1024px height (not capped at one screen).
The default `make platformer_stream` build is fully playable; it boots straight
into gameplay (a streaming rail has no title screen by design) — you spawn in an
air shaft and gravity drops you ~5 screens to the floor.

| Button | Action |
|---|---|
| **D-pad left / right** | walk |
| **A** | jump (hold for a higher jump) |

## What it teaches

- **2-axis BG1 streaming** — `sf_stream.inc` over `engine/bg_stream.asm` +
  `engine/bg_stream_row.asm` (`sf_stream_init`, `sf_stream_row_init`,
  `sf_stream_set_cam2`, `sf_stream_tick2`): a 64x64 hardware tilemap ring whose
  edge columns and rows are refilled from a ROM level as the camera crosses tile
  boundaries, so a 1024x1024 world scrolls through a 32x32-visible window with no
  seams. The full streaming design is in
  [`docs/guides/normal_bg_streaming.md`](../../docs/guides/normal_bg_streaming.md).
- **World-space collision, decoupled from the ring** — `ps_solidprobe` /
  `walk_blocked` / `col_solid` read a ROM-resident 128x128 collision table by
  **world** tile coordinate, independent of which window is currently streamed
  in. So what blocks you is the true world geometry, not whatever happens to be
  in the ring.
- **16-bit world-Y physics** — `sf_physics.inc` (`sf_physics_step_world`,
  `sf_jump`, `sf_jump_cut`): gravity, a variable-height jump, landing snap, and
  head bump run against a 16-bit world Y, so the hero can fall the full
  1024px-tall level in one continuous arc.
- **Camera follow clamped to the world** — `sf_camera.inc` (`sf_camera_follow`)
  clamps both axes to 1024x1024 and the hero draws screen-relative (world minus
  camera), so it stays centred until the camera hits a world edge.
- **A dusk-sky backdrop gradient** — `sf_fx.inc` (`sf_gradient_rgb`): a 3-channel
  HDMA RGB ramp added on the backdrop only, so open sky reads as a warm sunset
  instead of bare black.

## Three things to tweak

- **`SPAWN_X` / `SPAWN_Y`** (`main.asm`, in the equates; default 272, 136) — the
  hero's world-pixel spawn, currently in the mouth of the air shaft. Move it onto
  the left plateau to start grounded instead of falling.
- **The dusk gradient** (`main.asm`: `DUSK_TOP_R/G/B`, `DUSK_BOT_R/G/B`, and
  `SKY_DUSK`) — the 5-bit RGB intensities at the top and bottom of the sky ramp
  (and the flat backdrop colour under it). Change them to repaint the sky from
  sunset to noon or night.
- **The level itself** — the world blobs are generated, not hand-authored:
  re-run `tools/level_pipeline_bg.py --seasons --tall` to emit a new
  column-major + row-major + collision set, per
  [`docs/guides/normal_bg_streaming.md`](../../docs/guides/normal_bg_streaming.md).

## How it's verified

- **Build:** `make platformer_stream` (the generic rule reads the
  `LDCFG: lorom_stream.cfg` sentinel and assembles with `-D BG_STREAM_2AXIS`; a
  512KB LoROM image with the column-major, row-major, CHR, and collision blobs in
  BANK1-4).
- **Test:** `python -m pytest tests/test_platformer_stream.py -q` — proves
  integration on deterministic drives (the engine's raw 2-axis correctness is
  proven separately): drive the player right then left across several screens and
  assert the destination BG1 VRAM tilemap matches the authored level at the
  player's world-X (forward and reverse); and spawn high and let gravity drop the
  hero down the open shaft, asserting the streamed-in VRAM matches the level below.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/platformer_stream.sfc', run_seconds=1.5); r.take_screenshot('/tmp/platformer_stream.png'); r.stop()"`
