# Adapting a rail to a new theme (copy-to-adapt)

A "rail" (`templates/<name>/`) is a small complete game. To make a NEW
differently-themed game, you **copy the nearest rail and re-theme it** — you do
not freeform-generate. `scenarios/README.md` routes the ask to a rail; this
guide is the concrete change-list once you've copied it.

The worked example is the `rpg` rail (Mode 7 overworld ↔ Mode 1 town, dialog,
save) re-themed to, say, a sci-fi `starstation`. The same five steps apply to
any rail; only the asset/symbol names differ.

> **Adapting a STREAMING overworld (`mode7_explore`)?** The five steps below are
> the same, but the rpg-shaped worked example differs in a few specifics — read
> them alongside **`docs/guides/mode7_overworld_streaming.md`** (the streaming
> rail's own guide):
>
> - **World size + collision live in the GENERATOR, not a map blob.** Re-theme
>   `templates/mode7_explore/assets/make_explore_world.py` (`WORLD_T`,
>   `terrain_at`/`tile_at`, the `TEX` textures, `PAL_RGB`, the spawn + corridors).
>   It emits the 8-bank flat tilemap (`explore_flat_bank*.bin`), the 32 KB
>   interleaved seed (`explore_seed.bin`), and the `tile_terrain_lut` (in
>   `explore_world.inc`). Collision is **LUT-derived from the flat tilemap** — the
>   tilemap is the single source of truth — so there is NO separate collision
>   blob to re-theme.
> - **These rpg-rail steps DON'T apply to a streaming overworld:** the `town_chr`
>   / `town_bg_pal` / Mode 1 town scene + the `sf_mosaic_transition`
>   overworld↔town wipe (the streaming rail is a single static-affine Mode 7
>   scene — no scene swap, no mosaic wipe, no town tileset). Skip the change-list
>   "Mosaic-wipe capture" note and the town-asset rows below.
> - **The oracle's ground pixel is over a CHECKER meadow** — use the midpoint +
>   wide-tolerance trick (Step 4, the `screenshot_pixel` bullet), not a single
>   literal grass shade.
> - **`; LDCFG:` is `lorom_stream.cfg`** (512 KB, 8 flat banks) and `main.asm`
>   `.define MODE7_STREAM_NMI` pulls the streaming VBlank DMA dispatch — leave
>   both alone unless you change the world's bank count.

> **The kit now makes copy-to-adapt link-safe and identity-safe by default.** The
> three historical cold-start traps — the Makefile linking the wrong cfg, the
> `.incbin` path needing a directory edit, and the oracle silently testing the
> SOURCE ROM — are closed (GAP-1/2/3). The notes below call out where each was.

## Step 0 — copy the rail

```bash
cp -a templates/rpg templates/starstation
```

You now have `templates/starstation/{main.asm, oracle.json, assets/}`. Build it
with `make starstation` — **no Makefile edit needed** (see step 4).

## Step 1 — re-theme + regenerate the asset generator

Each Mode 7 / town rail ships an asset GENERATOR (`assets/make_<rail>_assets.py`)
that emits the committed `.bin` / `.inc` artifacts. Re-theme the generator, don't
hand-edit its output:

1. Rename `assets/make_rpg_assets.py` → `assets/make_station_assets.py`.
2. Re-theme the art INSIDE it: the terrain palette + tile patterns (rpg:
   grass/water/path/etc → void/lane/nebula/asteroid), the town/interior tiles,
   the avatar sprite. Keep the converter calls (`toolchain.mode7_map_converter`,
   `reserve_sky_backdrop`, the `encode_4bpp` town CHR) — they work on re-themed
   art unchanged. Author tile pixel indices in `0..3` (2bpp) / `0..15` (4bpp);
   the encoders reject out-of-range indices loudly (no silent masking).
3. Regenerate the artifacts from the kit root:
   ```bash
   PYTHONPATH=. python3 templates/starstation/assets/make_station_assets.py
   ```
   This rewrites `ovw_map.bin`, `ovw_palette.inc`, `ovw_collision.inc`,
   `town_assets.inc` (rename these to your theme if you like — see step 2). The
   generator output IS the asset contract: only the symbols it emits
   (`ovw_map`, `ovw_pal`/`ovw_palette`, `town_chr`, `town_bg_pal`, `obj_pal`,
   `TOWN_CHR_BYTES`, the `OVW_SPAWN_*`/`TERR_*` equates) are load-bearing.
   (Note: the generator no longer emits a dead BG2 dialog box — GAP-4. Dialog is
   the `sf_dialog` macro's own opaque BG3 panel; don't re-add a hand-rolled box.)

## Step 2 — re-symbol `main.asm`

`main.asm` references the asset symbols + the on-screen strings. Re-point both:

- **Asset symbols** — if you renamed the generated files/symbols, update the
  `.include "assets/<file>.inc"` lines and the symbol uses (`ovw_map`,
  `ovw_pal`, `town_chr`, `town_bg_pal`, `obj_pal`, …). If you kept the rpg
  names, only the BYTES change and `main.asm` needs no edit here.
- **The `.incbin` map blob** — change ONLY the basename:
  ```asm
  .incbin "assets/ovw_map.bin"     →     .incbin "assets/stn_map.bin"
  ```
  The `assets/` prefix stays. ca65 resolves `.incbin` relative to the INCLUDING
  FILE's directory (NOT via `-I` — that's `.include` only), so a copied template
  needs only the basename changed, never the directory. (This was GAP-3 — the old
  repo-root path `templates/rpg/assets/ovw_map.bin` forced a directory edit and
  broke from a foreign cwd. See `docs/troubleshooting.md` "Cannot open include
  file" for the `.include` vs `.incbin` distinction.)
- **Strings** — re-theme the dialog/UI text (the `sf_dialog` string data, any
  HUD labels). These are plain bytes; no structural change.

Leave the macro structure alone: `sf_mode7*`, `sf_mosaic_transition`,
`sf_dialog`, `sf_save`, `sf_scene*`, `sf_scene_mode` carry the hardware
contracts (setup ordering, width, NMI/forced-blank brackets, the Mode 7 HDMA-TM
OBJ-cull caveat, virgin-SRAM gating). Re-theming never needs to touch them.

## Step 3 — the linker cfg sentinel (already correct after the copy)

`main.asm` carries a `; LDCFG: <cfg>` sentinel near its header (rpg →
`lorom_tad_m7_sram.cfg`). The generic `build/%.sfc` rule reads it and links that
cfg — a `*_tad*.cfg` name also pulls in the TAD audio objects + audio include
path. **Because you copied the rail, the sentinel is already there and correct;
do nothing.** Only touch it if your theme changes the link SHAPE (e.g. you drop
audio → `lorom_m7_sram.cfg`, or drop the map bank). A sentinel-less template
defaults to `lorom.cfg` (the 32KB shape).

This was GAP-2: the generic rule used to link plain `lorom.cfg` for every copied
template, silently dropping the map bank / audio banks / SRAM window. The
sentinel replaced the need to hand-author a bespoke Makefile rule.

## Step 4 — re-point the oracle (re-theme the pixel colors only)

`oracle.json` is the rail's acceptance harness (closed-vocabulary
screenshot/OAM/SRAM asserts, auto-discovered + sabotage-verifiable). After the
copy:

- **Identity is AUTO-DERIVED from the path** (GAP-1): a
  `templates/starstation/oracle.json` is pinned to `template == "starstation"`
  and `rom == "build/starstation.sfc"` automatically. You can DELETE the
  `"template"`/`"rom"` fields, or leave them — but if you leave the SOURCE
  values (`"rpg"`/`"build/rpg.sfc"`) the loader **rejects them loudly** at load
  time, naming the wrong value and "RE-POINTED". (The old trap: a copied oracle
  silently drove the rpg ROM, PASSED, and never tested your game. That false
  green is now impossible.)
- **Re-theme the pixel asserts** — the screenshot color checks are themed to the
  rpg's palette (e.g. the overworld sky pixel). Re-point them to YOUR theme's
  colors at the same screen coordinates. Sanity-check by sabotage: flip one
  asserted pixel to a wrong color and confirm the oracle FAILS — that proves it's
  testing your ROM, not inheriting a pass.
- **CHECKER / dithered ground needs a MIDPOINT color + a WIDE tolerance, NOT a
  single literal shade.** When a `screenshot_pixel` lands over a fine 2-tone
  checker or dithered texture (a grass meadow `dark`/`light` checker; a water
  ripple; any sub-tile dither), the exact pixel sampled FLIPS between the two
  shades as the camera scrolls sub-pixel — a literal single-shade RGB will
  flake/fail frame-to-frame. Target the **BGR midpoint of the two shades** with a
  **tolerance wide enough to span both** (compute `((r0+r1)//2, (g0+g1)//2,
  (b0+b1)//2)` and set the tolerance ≥ half the channel spread). The streaming
  rail is the worked example: `templates/mode7_explore/oracle.json` samples the
  grass meadow floor with `rgb: [37, 111, 49]` (the midpoint of grass-dark
  `(30,92,40)` and grass-light `(52,130,58)`) and `tolerance: 55` — a single
  literal `(30,92,40)` there fails as the checker flips. (Solid-fill ground can
  use a tight tolerance; only checker/dither needs the midpoint+wide trick.)
- **Keep the structure**: the scenario list, drive scripts, and the
  anti-indirect-evidence shape (an outcome scenario must assert a real output
  region, never only a state variable) transfer 1:1.
- **Mosaic-wipe capture**: if you keep the overworld↔town mosaic transition, its
  black-frame capture window is ~`arm + SF_MT_OUT_FRAMES` (default ≈ frame 20;
  deepest ≈ arm+16..24). Single-frame captures FLAKE ±1-2 frames — use a WIDE
  tolerance (the rpg oracle's `tolerance: 24` is the pattern) or sample the
  window. See `lib/macros/sf_mosaic_transition.inc` "CAPTURE TIMING" (GAP-5).

## Step 5 — build + verify

```bash
make starstation                                   # generic rule reads the sentinel
PYTHONPATH=. python3 -m pytest \
  "tests/test_oracles.py::test_oracle_manifest[starstation]" -q
make width-check                                   # no new silent-corruption findings
```

`make starstation` must link the right cfg (the build log echoes `cfg=...`) and
the oracle must pass against YOUR ROM. If the oracle skips, the ROM didn't build
into `build/`. If it passes while your theme colors clearly differ from the rpg's
— sabotage-check a pixel; it should fail.

## The change-list in one screen

| What | Where | The edit |
|---|---|---|
| Re-theme art | `assets/make_<rail>_assets.py` | rewrite tile/palette/sprite art; regenerate the `.bin`/`.inc` |
| Asset symbols | `main.asm` `.include`/symbol uses | re-point only if you renamed the generated symbols |
| Map blob | `main.asm` `.incbin "assets/<X>.bin"` | change the **basename** only (GAP-3: dir is fixed) |
| Strings | `main.asm` dialog/HUD text | re-theme the bytes |
| Linker cfg | `main.asm` `; LDCFG:` sentinel | already correct after copy; touch only if link shape changes (GAP-2) |
| Oracle identity | `oracle.json` `template`/`rom` | auto-derived from path — delete them or re-point (GAP-1) |
| Oracle colors | `oracle.json` pixel asserts | re-point to your theme's colors; sabotage-check |

Macros (`lib/macros/sf_*`) are NEVER edited to re-theme — they hold the hardware
contracts. If your ask needs a mechanic the rail doesn't have, that's a
*composition* (pull a brick from another rail), not an adaptation — see the
"Genre routing map" in `scenarios/README.md`.
