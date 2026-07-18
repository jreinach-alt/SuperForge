# Normal-BG (Mode 1) 2-axis streaming platformer — the side-view-bigger-than-one-screen recipe

**Rail:** `templates/platformer_stream/` — a side-view **Mode 1** platformer
where the player runs / jumps / falls through a believable Four Seasons level
LARGER than one screen on **both** axes (128×128 tiles = 1024×1024 px = 4
screens/axis); the level streams in seamlessly as the follow-camera pans —
forward, back, up, down, idle — with no pop-in, tearing, or black bands.

**Done-condition:** `tests/test_platformer_stream.py` (5 tests) + the
`platformer_stream` `oracle.json` (3 scenarios). The substrate's both-axes
engine correctness (incl. UP) is byte-proven separately by
`tests/test_bg_stream2d.py`. **Read "The verification split" below before
writing or reviewing any test for this rail** — the split is the design
decision, not an accident.

This is the normal-BG sibling of the Mode 7 `mode7_explore` rail
(`docs/guides/mode7_overworld_streaming.md`): same "world bigger than the
hardware window, stream the leading edge per VBlank" idea, but on a **normal
Mode-1 BG1 tilemap** (a 64×64 hardware ring) with **side-view gravity physics**
instead of an overhead Mode 7 plane.

---

## What the rail composes

| Brick | From | Role |
|---|---|---|
| 2-axis BG1 tilemap streaming | `lib/macros/sf_stream.inc` (`sf_stream_init` / `sf_stream_row_init` / `sf_stream_set_cam2` / `sf_stream_tick2`) over `engine/bg_stream.asm` (column producer) + `engine/bg_stream_row.asm` (row producer) | slide a 64×64 BG1 ring over a level wider AND taller than the ring; the engine NMI drains `STREAM_PENDING` (columns, stride-32) + `STREAM_ROW_PENDING` (rows, stride-1) each VBlank |
| 16-bit world-Y jump physics | `lib/macros/sf_physics.inc` (`sf_physics_step_world`) | gravity, variable-height jump (`sf_jump` / `sf_jump_cut`), head bump, landing snap — across the full 1024-px-tall level (NOT capped at one 256-px screen) |
| world-space box collision | `walk_blocked` / `ps_solidprobe` / `ps_owprobe` in the template `main.asm` | read a ROM-resident **row-major collision table** by WORLD tile coordinate — INDEPENDENT of the streamed ring window, so collision is correct over the whole 1024×1024 level |
| follow camera (both axes clamped) | `lib/macros/sf_camera.inc` (`sf_camera_follow`) | the camera follows the player and clamps to the 1024×1024 world; the player draws SCREEN-relative (world − camera) |
| dusk-sky backdrop | `lib/macros/sf_fx.inc` (`sf_gradient_rgb` + color math on the backdrop, CH3..CH5) | a warm-orange→blue-purple dusk ramp on the PPU fixed colour so open sky reads as a real sunset, not bare black/purple |
| level + art pipeline | `tools/level_pipeline_bg.py --tall --seasons` + the Four Seasons CC0 tileset | the believable level (floor with pits, stacked terraces, wood platforms, a deep open fall-shaft) → column-major + row-major flat tilemaps, CHR, palette, and the world-space collision table |
| 512 KB bank layout | `infrastructure/rom_template/lorom_stream.cfg` (`-D BG_STREAM_2AXIS`) | BANK1 = column-major level, BANK2 = row-major level, BANK3 = CHR, BANK4 = world-space collision |

The hard part — the 2-axis streaming substrate — is proven and packaged. This
rail is the *application*: a player, side-view gravity, world-space collision,
and a believable authored level.

---

## The four moving parts

### 1. The level is FLAT + indexable BOTH ways; the BG1 window is 64×64 wrapped

- The **level** is 128×128 tiles (1024×1024 px). It lives as TWO flat ROM
  copies of the SAME tilemap so each producer reads contiguously:
  - `level_flat.bin` — **column-major** (128 cols × 256 B): the horizontal
    column producer reads col N at offset `N * 256`.
  - `level_flat_row.bin` — **row-major** (128 rows × 256 B): the vertical row
    producer reads row M at offset `M * 256`.
  Each copy is EXACTLY 32 KB = one LoROM bank, so neither axis' producer pointer
  crosses a bank seam (LoROM banks are NOT contiguous in CPU address).
- The **BG1 VRAM tilemap** stays **64×64** (`BG1SC=$5B`, VRAM word $5800); the
  PPU samples it **modulo 64**. A streamed column/row is written at the
  **ring-wrapped** position (`world_col & $3F`, `world_row & $3F`) — the
  position-wrap rule (CLAUDE.md "Mode 7 VRAM Buffer Writes Must Be
  Position-Wrapped" applies to normal-BG rings too). The 64×64 ring gives a
  64-col × 64-row resident window — comfortably more than the 32×28 visible
  screen, so the producers stay ahead of the camera.

### 2. Both producers are armed, keyed to the follow camera

```asm
    jsr hdma_alloc_init                       ; reserve CH0/CH1; free CH2..CH7
    ...
    sf_stream_init     level_flat,     #BGW_WORLD_W_TILES   ; column axis (claims CH2)
    sf_stream_row_init level_flat_row, #BGW_WORLD_H_TILES   ; row axis
    ...
game_tick:
    ...
    sf_camera_follow PX, PYF, WORLD_W_PX, WORLD_H_PX, CAMX, CAMY
    ; commit CAMX/CAMY -> SHADOW_BG1HOFS/VOFS (+ ES_BG_SHADOW_DIRTY)
    sf_stream_set_cam2 CAMX, CAMY             ; feed BOTH axes the follow camera
    sf_stream_tick2                           ; queue leading/trailing col + row
```

`sf_stream_init` BAKES IN the `BG_TILEMAP_DIRTY` disown, so the ROM does NOT
carry a manual disown step. The per-frame clamp inside the producers covers the
max tile displacement per frame (walk = 2 px/f = 0.25 tile/f; fall = 4 px/f =
0.5 tile/f — both well inside the +8-tile cap), so no tiles are ever skipped.

### 3. Collision is WORLD-space, independent of the ring

`walk_blocked` / `ps_solidprobe` index `level_collision` (a 128×128 row-major
byte table, $01 = solid) by WORLD tile coordinate, NOT by ring slot. This is
why the player can collide correctly anywhere in the 1024×1024 level even though
only a 64×64 window is resident in VRAM. The physics integrator
(`sf_physics_step_world`) calls these caller-supplied probes for its vertical
arc; the horizontal walk does a tentative-X box probe per axis.

> **Gotcha (fixed in S2b-M2b):** the player's feet rest ON the floor's top
> pixel, so the feet CONTACT line is the solid floor row itself. The horizontal
> box probe must test the 8 px STRICTLY ABOVE the feet (`[PYF-8 .. PYF-1]`),
> not `[PYF-7 .. PYF]` — counting the contact line as body makes walking ALONG
> any floor read as "blocked into a wall."

### 4. The level naturally exercises BOTH axes through ordinary play

The authored level (`author_level_seasons` in `tools/level_pipeline_bg.py`) is
designed so a real player drives both streaming axes without scripted input:

- A **deep open fall-shaft** (an air column) drops the player ~5 screens under
  gravity from the spawn to the bedrock floor — the camera pans DOWN and the row
  producer reveals new authored content at every depth band.
- A **continuous bedrock floor with pits** + the full level width gives the
  horizontal run; walking RIGHT then LEFT pans the camera east/west past the
  64-col ring (the column producer's forward + reverse).
- **Stacked terraces + wood platforms at many heights** fill the vertical bands
  so panning down (or jumping up) always reveals genuinely new geometry, never a
  repeat of the top strip.

---

## The verification split (the design decision — read before testing)

The streaming ENGINE's 2-axis correctness — forward AND reverse, BOTH axes,
**including UP** — is ALREADY proven **byte-perfect** by
`tests/test_bg_stream2d.py`: a SCRIPTED camera walks the authored level in all
four directions + idle, and every visible cell is asserted tile-for-tile against
the authored ground-truth. So the PLAYABLE template test does NOT re-prove
UP-streaming through a fragile scripted multi-screen climb (jump-arc-vs-step
tuning is a rabbit hole). Instead it proves **integration** — that the template
wires the proven substrate to real PLAYER motion — on **deterministic** drives:

| Axis / behaviour | How the TEMPLATE test proves it (`tests/test_platformer_stream.py`) | OUTPUT region read |
|---|---|---|
| Horizontal (forward + reverse) | drive the player RIGHT then LEFT across several screens; assert the BG1 VRAM tilemap matches the authored level at the player's world-X (both directions) | BG1 VRAM tilemap words vs authored level |
| Vertical DOWN | spawn HIGH, let GRAVITY drop the player down the shaft; assert the VRAM tilemap matches the authored level at the player's world-Y as it falls (3 depth bands + landed) | BG1 VRAM tilemap words vs authored level |
| Jump physics | hold A; assert the apex rises AND the landing returns to a stable floor rest (16-bit world-Y, full ascent→apex→descent→land→rest cycle) | the integrator's committed world-Y (PYF) |
| Collision | walk into a wall; read the player's real world-X + the collision table; assert the box's leading column is AIR and the next column is SOLID (stopped flush, never inside) | committed world-X + the ROM collision table |

**The three-way split (codify this in every test/review):**

1. **Template test** (`tests/test_platformer_stream.py`) = INTEGRATION on
   DETERMINISTIC axes (horizontal via input, vertical-DOWN via gravity). Reads
   real OUTPUT regions (VRAM / world position / collision table), never a proxy.
2. **Substrate test** (`tests/test_bg_stream2d.py`) = the ENGINE, BOTH axes
   (incl. UP), scripted camera, byte-exact vs authored ground-truth.
3. **Player UP-traversal** (climbing back up several screens) = GAMEPLAY,
   **owner-validated via render** (the project's "Done = owner-validated
   render"), NOT an automated scripted climb. A scripted multi-screen climber is
   a banned rabbit hole — the UP axis is already engine-proven (2) and the
   playable wiring is proven on the deterministic DOWN axis (1).

Why decoupled: re-proving UP through a closed-loop climb would couple the test
to jump-arc-vs-platform-spacing tuning — fragile, slow, and redundant with the
substrate's scripted-camera UP proof. The deterministic DOWN fall exercises the
exact same vertical streaming wiring (row producer, `sf_stream_tick2`, the
follow camera) under real player physics, with zero input-timing fragility.

---

## Build

```bash
make build/platformer_stream.sfc      # 512 KB LoROM, -D BG_STREAM_2AXIS, lorom_stream.cfg
# regenerate the level (believable Four Seasons, 128x128, 2-axis):
python3 tools/level_pipeline_bg.py \
    --tileset-zip "<Four Seasons tileset zip>" \
    --out-dir tests/fixtures/platformer_stream --tall --seasons
```

See `templates/platformer_stream/main.asm` for the full wiring and
`tools/level_pipeline_bg.py::author_level_seasons` for the level design.
