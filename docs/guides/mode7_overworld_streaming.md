# Mode 7 overhead streaming overworld — the avatar-on-a-large-world recipe

**Rail:** `templates/mode7_explore/` — a top-down Mode 7 **exploration** game
where an avatar walks a world LARGER than the 128×128 Mode 7 VRAM window;
regions stream in seamlessly as the camera moves. **Done-condition:**
`tests/test_mode7_explore.py` (11 tests: real-input walk forward/back/idle +
wall collision, all reading the rendered VRAM/OAM/screenshot) + the
`mode7_explore` `oracle.json` (3 scenarios).

This guide is the missing piece a cold-start agent flagged: the kit had a Mode 7
*racer* guide and a Mode 7 *overworld* (the `rpg` rail, 128×128-pinned), but no
recipe for an avatar on a **streaming** Mode 7 world. This is that recipe.

---

## What the rail composes

| Brick | From | Role |
|---|---|---|
| 2-axis Mode 7 tilemap streaming | `lib/macros/sf_mode7_stream.inc` (+ `engine/mode7_stream.asm` / `_nmi.inc`) | stream the leading row/column into the VRAM window as the camera walks |
| Mode 7 seed upload | `sf_mode7_load_map` | upload the initial 128×128 window once at boot |
| screen-centred avatar + grid-step movement + tile collision | forked from `templates/rpg/` | the avatar walks; the camera carries world position |
| 512 KB bank layout | `infrastructure/rom_template/lorom_stream.cfg` | dedicated banks for the flat tilemap + world-space collision |

The hard part — the streaming substrate — is the proven overhead-racing 2-axis
streaming engine, packaged as the kit macro `sf_mode7_stream_*`. This rail is the
*application*: an avatar, world-space collision, and a believable authored world.

---

## The four moving parts

### 1. The world is FLAT + multi-bank, the window is 128×128 wrapped

- The **world** is 256×256 tiles (2048×2048 px) — "several windows" each axis.
  It lives as a **flat ROM tilemap** (1 byte/tile, the tile-id low byte), split
  across ROM banks: `bank = (row >> 7) + WORLD_FLAT_BANK_BASE`,
  `offset = $8000 + (row & 127) * 256`.
- The **VRAM** Mode 7 tilemap stays **128×128**; the PPU samples it **modulo
  128**. A streamed row/column is written at the **VRAM-wrapped** position
  (`world_coord & $7F`), so the hardware auto-wrap lines it up
  (CLAUDE.md "Mode 7 VRAM Buffer Writes Must Be Position-Wrapped").
- Use **WRAP** (`stz $211A` / `M7SEL = $00`), **not FILL** — the window is a
  toroidal slice of the world, not a bordered map.

### 2. Position-space discipline (the #1 landmine)

Two coordinate spaces coexist; every consumer must know which it is in:

- **World space** (0..255 tiles, 0..2047 px): the camera, the avatar's world
  position, collision lookups.
- **VRAM space** (0..127, modulo 128): where a tile lands in the Mode 7 tilemap.

The avatar stays **screen-centred**; the **camera** carries the world position.
The scroll that centres the camera on the 256-px wrapped plane is
`(cam_px − 128) & $1FFF` into the BG1 HOFS/VOFS shadow (= M7HOFS/M7VOFS under
Mode 7; the stock NMI commits it).

### 3. World-space collision (not the 128-pinned `& $7F`)

The `rpg` rail pins everything to 128×128 and wraps coordinates with `& $7F`.
A streaming world must **not** wrap-repeat — the avatar walks genuinely new
terrain. So collision reads a **world-space** table: 256×256, row-major,
**16-bit indexed** `collision[ty*256 + tx]`, split across two ROM banks
(`bank = COLL_BANK_BASE + (ty >> 7)`, `offset = $8000 + (ty & 127)*256 + tx`).
A step into a `TERR_WATER`/`TERR_MOUNTAIN` tile is rejected — the camera does
not move (see `terr_at_world` / `try_start_step` in the template).

Clamp the camera tile to `[64 .. WORLD−1−64]` so the 128 window always holds
real authored data (never crosses the world's toroidal seam).

### 4. The build wiring (three things, all in the template)

1. **`MODE7_STREAM_NMI = 1`** *before* `.include "nmi_handler.asm"` — the stock
   NMI gates the streaming VBlank DMA dispatch behind `.ifdef MODE7_STREAM_NMI`.
   Defining it in source is equivalent to `-D MODE7_STREAM_NMI` on the ca65
   command line, so the **generic sentinel-driven template build needs no
   Makefile edit**.
2. **`; LDCFG: lorom_stream.cfg`** sentinel — the 512 KB layout (bank 0 = code,
   bank 1 = seed, banks 2–3 = flat tilemap, banks 4–5 = world collision).
3. **Generated world data** in `templates/<name>/assets/` — `.incbin`'d by
   basename (copy-safe, GAP-3).

---

## Boot + loop shape (condensed from `templates/mode7_explore/main.asm`)

```asm
MODE7_STREAM_NMI = 1                 ; pull the streaming VBlank DMA dispatch
; ... includes ...
; LDCFG: lorom_stream.cfg

RESET:
    sf_coldstart
    sf_engine_init
    sf_mode7_load_map explore_seed, #$8000      ; seed the initial 128×128 window
    ; ... upload world_palette to CGRAM, avatar OBJ CHR/pal ...
    ; static top-down Mode 7: BGMODE 7, identity affine, M7SEL = $00 (WRAP)
    sf_mode7_stream_init #WORLD_SPAWN_TX, #WORLD_SPAWN_TY
    ; screen on + NMI on; draw the centred avatar

game_loop:
    sf_frame_begin
    jsr explore_tick                 ; D-pad -> grid step (world-space collision)
    sf_frame_end
    jmp game_loop

explore_tick:
    ; advance an in-flight slide, OR read the D-pad and try_start_step
    jsr apply_camera                 ; (cam_px − 128) & $1FFF -> BG1 scroll shadow
    sf_mode7_stream_set_cam cam_px, cam_py   ; update streaming cam tile pos
    sf_mode7_stream_tick             ; stage the leading row/column (NMI DMAs it)
    jsr draw_avatar                  ; OAM 0, screen-centred
```

---

## Authoring a believable world

The world generator (`templates/mode7_explore/assets/make_explore_world.py`)
emits all five artifacts from a **single source of truth** (`terrain_at`):

| Artifact | What |
|---|---|
| `explore_seed.bin` | 32 KB interleaved Mode 7 VRAM seed (the initial 128×128 window, VRAM-wrapped placement matching the engine) |
| `explore_flat_bankN.bin` | the flat streaming tilemap (2 banks × 32 KB) |
| `explore_collision_bankN.bin` | world-space collision (256×256 = 64 KB, two banks) |
| `explore_world.inc` | ca65 constants (dims, spawn, TILE_*/TERR_*, palette) |
| `explore_obj.inc` | the avatar OBJ CHR + palette |

**Reuse the kit's authored tile art** (owner decision): the terrain vocabulary
and palette mirror the `rpg` overworld (grass / dirt-path / water / mountain /
town), drawn as **textured 8×8 tiles** (a checker meadow, a dithered water
ripple, a rocky mountain face, a tiled road, a town roof, a sand coastline, a
forest canopy) — **not** flat solid-colour blocks (which read as a test pattern)
and **not** a synthetic position-id pattern (banned). Geography is generated
believably: a central continent (radial falloff + layered deterministic
sinusoids), ocean + sand coastline at the rim, connected mountain ranges along
high-elevation ridges, forest pockets, and meandering roads connecting a 32-tile
town lattice.

**Seed/stream VRAM-wrap consistency:** the seed MUST place world tile `(wx,wy)`
at VRAM word `(wy & 127)*128 + (wx & 127)` — the SAME wrapped slot the streaming
engine writes — or a row/column the seed placed will be off by the window origin
when it is later re-streamed.

**Hidden test ground-truth:** a TOWN tile sits at every 32-tile lattice point
(authored content — towns — on a regular grid) so the proof test can assert
"world (32k,32m) renders TILE_TOWN" without making the *visible* world a
synthetic pattern.

---

## Verifying the rail

`tests/test_mode7_explore.py` drives the **avatar** with **real D-pad input**
(not a scripted camera) and asserts on the **rendered destination**:

- walk east / south / west / north + idle: the 128×128 VRAM tilemap low bytes
  match the authored world ground-truth at the camera's world position, **0
  mismatches, 0 garbage** — no stale strips, no pop-in (full state-cycle
  coverage, CLAUDE.md "Indirect-Evidence Tests").
- the hidden TOWN landmark lattice renders at its world positions (the streamed
  content IS the authored world, not a coincidental fill).
- **collision:** walk into the mountain wall north of spawn; the camera stops
  **adjacent** to the blocked tile (it does not enter it), proven by the camera
  world tile in WRAM + the blocked-step counter.
- no all-black scanline in the Mode 7 area (the Phase-17 black-band regression
  class), read from the screenshot.

The `oracle.json` adds rendered-pixel + OAM scenarios (boots into a textured
streamed world; walk east; blocked by the wall) under the random power-on regime.
