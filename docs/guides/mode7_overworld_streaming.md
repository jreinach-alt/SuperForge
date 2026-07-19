# Mode 7 overhead streaming overworld — the avatar-on-a-large-world recipe

**Rail:** `templates/mode7_explore/` — a top-down Mode 7 **exploration** game
where an avatar walks a world LARGER than the 128×128 Mode 7 VRAM window;
regions stream in seamlessly as the camera moves. **Done-condition:**
`tests/test_mode7_explore.py` (13 tests: real-input walk in all four cardinals +
idle, wall collision, several-windows traversal, and a diagonal-along-a-wall
regression — all reading the rendered VRAM/OAM/screenshot) + the `mode7_explore`
`oracle.json` (3 scenarios).

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
| overworld music | `lib/macros/sf_audio.inc` + the TAD driver | a song plays over the walk (async load pumped by `sf_audio_tick`) |
| 512 KB bank layout | `infrastructure/rom_template/lorom_tad_stream.cfg` | dedicated banks for the flat tilemap + the TAD audio data |

The hard part — the streaming substrate — is the proven overhead-racing 2-axis
streaming engine, packaged as the kit macro `sf_mode7_stream_*`. This rail is the
*application*: an avatar, world-space collision, and a believable authored world.

---

## The four moving parts

### 1. The world is FLAT + multi-bank, the window is 128×128 wrapped

- The **world** is 512×512 tiles (4096×4096 px) — *several* windows each axis.
  It lives as a **flat ROM tilemap** (1 byte/tile, the tile-id low byte), split
  across ROM banks: `bank = (row >> 6) + WORLD_FLAT_BANK_BASE`,
  `offset = $8000 + (row & 63) * 512 + col`. 64 rows fill one 32 KB bank, so the
  512-row world spans **8 banks** (`WORLD_FLAT_BANK_BASE = 2` → banks $02..$09).
- The **VRAM** Mode 7 tilemap stays **128×128**; the PPU samples it **modulo
  128**. A streamed row/column is written at the **VRAM-wrapped** position
  (`world_coord & $7F`), so the hardware auto-wrap lines it up
  (CLAUDE.md "Mode 7 VRAM Buffer Writes Must Be Position-Wrapped").
- Use **WRAP** (`stz $211A` / `M7SEL = $00`), **not FILL** — the window is a
  toroidal slice of the world, not a bordered map.

### 2. Position-space discipline (the #1 landmine)

Two coordinate spaces coexist; every consumer must know which it is in:

- **World space** (0..511 tiles, 0..4095 px): the camera, the avatar's world
  position, collision lookups.
- **VRAM space** (0..127, modulo 128): where a tile lands in the Mode 7 tilemap.

The avatar stays **screen-centred**; the **camera** carries the world position.
The scroll that centres the camera is `(cam_px − 128) & $1FFF` (subtract half the
256-px screen so the camera's world pixel lands at screen centre, masked to the
13-bit Mode 7 scroll register) written into the BG1 HOFS/VOFS shadow
(= M7HOFS/M7VOFS under Mode 7; the stock NMI commits it — see `apply_camera`).

Clamp the camera tile to `[64 .. WORLD−1−64]` = `[64 .. 447]` so the 128 window
always holds real authored data (never crosses the world's toroidal seam).

### 3. World-space collision — LUT-derived from the flat tilemap (NOT a table)

The `rpg` rail pins everything to 128×128 and wraps coordinates with `& $7F`.
A streaming world must **not** wrap-repeat — the avatar walks genuinely new
terrain — so it needs collision in **world space** (0..511, not `& $7F`).

But a 512×512 byte tilemap is already 256 KB (8 banks); a *separate* 512×512
byte collision table would add **another 256 KB**, and the two together exceed
the 512 KB ROM. So there is **no separate collision table**. Instead collision
reads the **SAME flat ROM tilemap byte** the streaming engine reads (a ROM read,
not a VRAM read — always safe) at the world tile:

    bank   = (ty >> 6) + WORLD_FLAT_BANK_BASE
    offset = $8000 + (ty & 63) * 512 + tx
    tile   = [24-bit ptr]                      ; the rendered tile id
    terr   = tile_terrain_lut[tile]            ; 256-byte RODATA LUT -> class

A step into a `TERR_WATER`/`TERR_MOUNTAIN` class is rejected — the camera does
not move. The tilemap is the **single source of truth**: what you SEE is what
blocks you, and there is no collision table to drift out of sync with the art
(see `terr_at_world` / `try_start_step` in the template).

### 4. The build wiring (three things, all in the template)

1. **`MODE7_STREAM_NMI = 1`** *before* `.include "nmi_handler.asm"` — the stock
   NMI gates the streaming VBlank DMA dispatch behind `.ifdef MODE7_STREAM_NMI`.
   Defining it in source is equivalent to `-D MODE7_STREAM_NMI` on the ca65
   command line, so the **generic sentinel-driven template build needs no
   Makefile edit**.
2. **`; LDCFG: lorom_tad_stream.cfg`** sentinel — the 512 KB layout (bank 0 =
   code, bank 1 = seed, banks 2–9 = flat tilemap, bank $0A = TAD audio data). A
   `*_tad*.cfg` name also links the TAD audio objects + audio include path into
   the generic build rule, so wiring music needs no Makefile edit either.
3. **Generated world data** in `templates/<name>/assets/` — `.incbin`'d by
   basename (copy-safe, GAP-3).

---

## Boot + loop shape (condensed from `templates/mode7_explore/main.asm`)

```asm
MODE7_STREAM_NMI = 1                 ; pull the streaming VBlank DMA dispatch
; ... includes (incl. tad-audio / sf_audio) ...
; LDCFG: lorom_tad_stream.cfg

RESET:
    sf_coldstart
    sf_engine_init
    sf_audio_init                                ; boot the TAD driver ONCE
    sf_mode7_load_map explore_seed, #$8000       ; seed the initial 128×128 window
    ; ... upload world_palette to CGRAM, avatar OBJ CHR/pal ...
    ; static top-down Mode 7: BGMODE 7, identity affine, M7SEL = $00 (WRAP)
    sf_mode7_stream_init #WORLD_SPAWN_TX, #WORLD_SPAWN_TY
    ; screen on + NMI on; draw the centred avatar
    sf_music #Song::ode_to_joy                   ; overworld theme (async load)

game_loop:
    sf_frame_begin
    sf_audio_tick                    ; pump the TAD queue + async song load
    jsr explore_tick                 ; D-pad -> grid step (world-space collision)
    sf_frame_end
    jmp game_loop

explore_tick:
    ; advance an in-flight slide, OR read the D-pad and try_start_step
    ;   (held-diagonal priority L>R>U>D, falling through a blocked axis)
    jsr apply_camera                 ; (cam_px − 128) & $1FFF -> BG1 scroll shadow
    sf_mode7_stream_set_cam cam_px, cam_py   ; update streaming cam tile pos
    sf_mode7_stream_tick             ; stage the leading row/column (NMI DMAs it)
    jsr draw_avatar                  ; OAM 0, screen-centred
```

---

## Authoring a believable world

The world generator (`templates/mode7_explore/assets/make_explore_world.py`)
emits all four artifacts from a **single source of truth** (`terrain_at`):

| Artifact | What |
|---|---|
| `explore_seed.bin` | 32 KB interleaved Mode 7 VRAM seed (the initial 128×128 window, VRAM-wrapped placement matching the engine) |
| `explore_flat_bankN.bin` | the flat streaming tilemap (8 banks × 32 KB) |
| `explore_world.inc` | ca65 constants (dims, spawn, TILE_*/TERR_*, palette) **and** the 256-byte `tile_terrain_lut` — the collision substrate |
| `explore_obj.inc` | the avatar OBJ CHR + palette |

There is **no** `explore_collision_bankN.bin` — collision is LUT-derived from the
flat tilemap (part 3 above). The generator actively deletes any stale collision
banks left over from the pre-remediation 256×256 design.

**Reuse the kit's authored tile art** (owner decision): the terrain vocabulary
and palette mirror the `rpg` overworld (grass / dirt-path / water / mountain /
town), drawn as **textured 8×8 tiles** (a checker meadow, a dithered water
ripple, a rocky mountain face, a tiled road, a little house, a sand coastline, a
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

**Landmark lattice (doubles as the test's ground truth):** an authored TOWN (a
little house) sits at every 32-tile lattice point **that falls on walkable land**
— towns on a regular grid, believable authored content. Water and mountain
lattice cells are skipped (no house ever floats in the ocean or buries itself in
a peak). Because the towns are position-regular, the proof test can assert "at
land world (32k,32m) you see a TOWN tile" without making the *visible* world a
synthetic pattern.

---

## Verifying the rail

`tests/test_mode7_explore.py` (13 tests) drives the **avatar** with **real D-pad
input** (not a scripted camera) and asserts on the **rendered destination**:

- walk east / south / west / north + idle: the 128×128 VRAM tilemap low bytes
  match the authored world ground-truth at the camera's world position, **0
  mismatches, 0 garbage** — no stale strips, no pop-in (full state-cycle
  coverage, CLAUDE.md "Indirect-Evidence Tests").
- **several-windows traversal:** walk the full camera-clamp span each axis
  (383 tiles ≈ 3 windows of camera travel); the window stays byte-exact against
  the authored world the whole way — a wrap-repeat would fail once the camera
  passes the seed-window boundary.
- the landmark TOWN lattice renders at its world positions (the streamed content
  IS the authored world, not a coincidental grass fill).
- **collision:** walk into a mountain wall; the camera stops **adjacent** to the
  blocked tile (it does not enter it), proven by the camera world tile in WRAM +
  the blocked-step counter.
- **diagonal fall-through:** a held diagonal along a wall keeps moving — a
  blocked higher-priority axis falls through to the other held axis instead of
  freezing.
- no all-black scanline in the Mode 7 area (the black-band regression class),
  read from the screenshot.

The `oracle.json` adds 3 rendered-pixel + OAM scenarios (boots into a textured
streamed world; walk east; blocked by the wall) under the random power-on regime.
