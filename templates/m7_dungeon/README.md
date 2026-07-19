# m7_dungeon — Mode 7 rotating-floor dungeon (tank controls)

## What it is

A top-down dungeon crawler with **tank controls**: your facing always reads "up",
and the dungeon floor — a single Mode 7 background — **rotates and scrolls
underneath** a hero pinned at screen centre. Walls block you, three enemies
patrol the corridors, and touching one knocks you back to the start with a screen
flash. The whole floor is drawn by one uniform affine matrix per frame (no
per-scanline HDMA), so it is cheap enough to leave budget for collision, three
world-space sprite projections, and audio.

| Button | Action |
|---|---|
| **LEFT / RIGHT** | turn the heading (the whole floor rotates under you) |
| **B** or **UP** | throttle forward along the way you face |
| **Y** or **DOWN** | reverse |
| *(release throttle)* | coast to a stop |

## What it teaches

- **Static-affine Mode 7** — `sf_mode7_affine.inc` (`sf_boss_mode7_on` /
  `sf_boss_center` / `sf_boss_matrix`): one uniform matrix committed from shadows
  by the stock VBlank handler, with the pivot moved to the player each frame (a
  *moving pivot*) so the world rotates + scrolls around a centred hero. No custom
  NMI, no perspective table — contrast the per-scanline rebuild the `persp_cycles`
  gate measures at ~138% of a frame.
- **OBJ over Mode 7** — the map fills VRAM words `$0000-$3FFF`, so the OBJ name
  base moves to `$4000` via `OBSEL = $62`; the affine matrix never touches OBJ, so
  the hero + enemy sprites composite on top, upright.
- **World-space collision** — `dungeon_terrain.bin` is a 128×128 tile LUT emitted
  from the *same* `is_wall()` predicate that paints the walls (`assets/make_dungeon.py`),
  so what you see is what blocks you. `footprint_solid` samples the hero's 4
  corners; `move_x`/`move_y` commit each axis separately (diagonal-into-wall
  *slides*), and the speed cap keeps a step under one tile so nothing tunnels.
- **world→screen sprite projection** — enemies live in world space and project
  through the inverse of the render matrix (a pure rotation's inverse is its
  transpose at scale 1.0), then cull off-screen — see `draw_enemies`.
- **Audio + feedback** — TAD music + SFX via `sf_audio.inc` (`sf_audio_init` /
  `sf_audio_tick` / `sf_music` / `sf_sfx`), and a get-hit screen flash via
  `sf_fx.inc` (`sf_bright_fade`).

## Three things to tweak

- **`SPEED_CAP`** (`main.asm`, tank-control tuning) — the tank's top speed
  (8.8 fixed). Raise it and you cover ground faster; push it past ~2 tiles/frame
  and a single step can tunnel a wall (that is why it is capped).
- **`PATROL_SPEED`** (`main.asm`, patrol/contact tuning) — how fast the enemies
  pace their corridors. Raise it for a harder dodge; the wall-turn patrol still
  keeps them out of walls.
- **`sf_music #Song::ode_to_joy`** (`main.asm`, in `RESET`) — the boot theme. Swap
  `ode_to_joy` for any id in `assets/audio/tad_audio_enums.inc` (e.g.
  `Song::gimo_297`) to change the music.

## How it's verified

- **Build:** `make m7_dungeon` (the generic rule reads the `LDCFG:` sentinel and
  links the TAD audio objects).
- **Test:** `python -m pytest tests/test_m7_dungeon.py -q` — 28 checks that read the
  rendered output (framebuffer pixels, OAM/CGRAM bytes, recorded WAV): boots into a
  textured Mode 7 floor, tank turn/drive rotate + scroll it, world-space collision
  blocks + slides + never tunnels, enemies project/cull/patrol on the floor, contact
  knocks the hero back and flashes the screen, and the committed `maze_route.json`
  solves the maze with zero hits. The `-D` control ROMs
  (`build_m7_dungeon_variants.sh`) prove the collision / projection / sprite-size
  asserts are non-vacuous.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/m7_dungeon.sfc', run_seconds=1.0); r.take_screenshot('/tmp/m7_dungeon.png'); r.stop()"`
