# mode7_explore — a streaming Mode 7 exploration overworld

## What it is

A top-down **Mode 7 exploration** game: an avatar walks a large authored
overworld — 512×512 tiles (4096×4096 px), *several* screens wide **and** tall —
that is far bigger than the 128×128 Mode 7 VRAM window. Regions **stream** into
the window seamlessly as the camera walks (no pop-in, tearing, or black bands),
and water + mountains block movement. The overworld dawns in from black at boot
while the music rises, and the explorable region is framed by an ocean coast.

Walk onto the **house** a short way north-west of the spawn and a **mosaic wipe**
dissolves the streaming overworld into a **Mode 1 town interior** — a small room
with a plank floor, stone walls, a table, and a door. Walk the room, step onto the
**door**, and a mosaic wipe carries you back out to the Mode 7 overworld at the
exact spot you left (the streamed world resumes with no pop-in). This
streaming-overworld ⇆ Mode-1-interior scene transition is the rail's signature.

| Input | Action |
|---|---|
| D-pad Up / Down / Left / Right | walk the avatar one tile (overworld: the camera scrolls the world under it; town: the avatar walks the fixed room) |
| step onto the house / the door | trigger the mosaic wipe into the town / back to the overworld |
| — | holding a diagonal against a wall slides along the open axis; music plays throughout |

The avatar stays screen-centred; the **camera** carries the world position.

## What it teaches

- **Mode 7 2-axis tilemap streaming** — the leading row/column of a world larger
  than the 128×128 VRAM window streams in as the camera walks, via
  [`lib/macros/sf_mode7_stream.inc`](../../lib/macros/sf_mode7_stream.inc)
  (`sf_mode7_stream_init` / `_set_cam` / `_tick`) over
  [`engine/mode7_stream.asm`](../../engine/mode7_stream.asm) + its VBlank DMA
  dispatch. Full write-up:
  [`docs/guides/mode7_overworld_streaming.md`](../../docs/guides/mode7_overworld_streaming.md).
- **World-space collision with NO separate collision table** — movement reads the
  SAME flat ROM tilemap byte the streamer reads, then maps tile id → terrain
  class through a 256-byte `tile_terrain_lut`. The tilemap is the single source
  of truth: what you SEE blocked is what rejects the step (a second 512×512 table
  would blow the 512 KB ROM). See `terr_at_world` / `try_start_step` in
  [`main.asm`](main.asm).
- **Screen-centred camera + grid-step movement** — the D-pad slides the Mode 7
  camera a tile at a time; a held diagonal falls through a blocked priority axis
  to the open one, so you slide along walls instead of freezing.
- **Wiring TAD audio + a boot fade** — overworld music through
  [`lib/macros/sf_audio.inc`](../../lib/macros/sf_audio.inc) on the streaming +
  audio link shape (`lorom_tad_stream.cfg`), plus a brightness dawn-in that the
  stock NMI commits from `SHADOW_INIDISP`.

## Three things to tweak

1. **`STEP_FRAMES`** in [`main.asm`](main.asm) (the grid constants block, = 8) —
   how many frames one tile-slide takes. Lower it and the avatar walks faster
   (the camera scrolls more px/frame).
2. **`#Song::ode_to_joy`** in [`main.asm`](main.asm) (the `sf_music` call after
   the avatar is drawn) — the overworld track. Swap it for another `Song::` id
   from [`assets/audio/tad_audio_enums.inc`](../../assets/audio/tad_audio_enums.inc)
   to change the music.
3. **`LANDMARK_STEP`** in
   [`assets/make_explore_world.py`](assets/make_explore_world.py) (= 32) — the
   spacing of the TOWN (house) landmark lattice. Regenerate the world
   (`python3 assets/make_explore_world.py`) and rebuild to dot the map with more
   or fewer houses.

## How it's verified

```bash
make mode7_explore                               # build the ROM (lorom_tad_stream.cfg)
python -m pytest tests/test_mode7_explore.py -q  # 13 rendered-output asserts
```

The suite
([`tests/test_mode7_explore.py`](../../tests/test_mode7_explore.py)) drives the
avatar with **real D-pad input** on the cycle-accurate emulator and asserts on
the **rendered destination**: the 128×128 VRAM tilemap matches the authored world
at the camera's position with 0 mismatches/0 garbage while walking all four
cardinals + idle; the several-windows sweep stays byte-exact the whole way (no
wrap-repeat); the TOWN landmark lattice renders at its world positions; a wall
stops the avatar adjacent (not inside) the blocked tile; a diagonal along a wall
keeps moving; and no all-black scanline appears in the Mode 7 area. To watch it,
boot `build/mode7_explore.sfc` in any SNES emulator (or drive it from
`MesenRunner`, as the tests do).
