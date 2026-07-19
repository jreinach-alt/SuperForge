# rpg — a top-down RPG rail (Mode 7 overworld ⇄ Mode 1 town/battle)

## What it is

A small role-playing game you can walk around. You steer a hero across a designed
overhead world drawn with the SNES **Mode 7** background (grass and paths are
walkable; water and mountains block), walk up to a villager for a dialog box,
enter a flat-tilemap **town** (Mode 1), **save** the game at a save point
(battery SRAM), and drop into a **battle** face-off scene. Music plays throughout
and survives every scene swap.

| Button | What it does |
|--------|--------------|
| D-pad  | Move one tile — overworld: scroll the Mode 7 camera under the centred hero; town: walk the hero sprite |
| A      | Overworld: enter the town (or **talk** when next to a villager). Town: talk / **save** at the save point / take the EXIT gate. Any dialog box: close it. Battle: return to the overworld |
| START  | Overworld: drop into the battle scene |

## What it teaches

- **Mode 7 perspective floor + a real sky** — `lib/macros/sf_mode7.inc`
  (`sf_mode7_on/off`, `_load_map`, `_cam`, `_perspective`, `_focus`, `_tick`,
  `_sky_split`). The horizon split turns BG1 off above the horizon so a sky
  backdrop shows, avoiding the "floor-in-sky" smear.
- **A scene state machine with a soft-restart swap** — `sf_scene.inc` +
  `sf_scene_mode.inc`: three scenes share CHR/palettes across a `goto`, and a
  Mode 7 ⇄ Mode 1 switch is bracketed by a forced blank. See
  `docs/guides/mode7_mode1_transition.md`.
- **Grid movement + a parallel collision table** — the overworld reads
  `assets/ovw_collision.inc` (one terrain byte per tile) instead of reading VRAM
  back per frame; the town reads its own shadow BG1 tilemap.
- **OBJ sprites and OBSEL sizing** — `sf_sprite.inc` (`spr`, `spr_clear`). The
  16x16 hero, the town villager, and the battle hero/foe all live at OBJ name
  base word `$4000`; OBSEL picks the 8x8/16x16 size pair (get the size wrong and
  a 16x16 sprite renders 32x32, dragging neighbouring CHR into view).
- **An opaque BG3 dialog box + text** — `sf_dialog.inc` + `sf_text.inc`.
- **A masked scene wipe** — `sf_mosaic_transition.inc` (pixelate → black → swap →
  de-pixelate) so the mode switch never shows a torn frame.
- **A horizon fog gradient** — `sf_fx.inc` (`sf_gradient_*` + color math) tints
  the floor toward the horizon.
- **Battery-SRAM save/load with a CRC** — `sf_save.inc` (`sf_save`, `sf_load`,
  `sf_save_exists`); a boot-load hook restores the saved scene + tile.
- **Persistent music across swaps** — `sf_audio.inc` (`sf_music`,
  `sf_audio_tick`): the TAD driver keeps playing across a soft scene swap because
  the spine calls `sf_audio_tick` every frame and scene inits never re-init audio.

Copy-to-adapt notes: `docs/guides/adapting_a_rail.md`.

## Three things to tweak

1. **`PV_L0`** (`main.asm`, the Mode 7 horizon scanline, default `40`) — raise it
   for a taller sky and less map on screen, lower it for a thinner sky and more
   walkable ground. `SKY_HORIZON` tracks it, so the sky band follows.
2. **`TOWN_NPC_TX` / `TOWN_NPC_TY`** (`main.asm`, default `16,8`) — move the
   town villager to a different plaza tile; collision + the dialog trigger follow
   the constant (walk up to wherever you put it and press A).
3. **`str_dlg_l0`** (`main.asm`, the villager's first dialog line) — change the
   text the dialog box prints (uppercase ASCII the built-in font renders).

## How it's verified

```bash
make rpg                                  # -> build/rpg.sfc (cfg lorom_tad_m7_sram.cfg, +TAD)
python -m pytest tests/test_rpg.py -q     # boots the ROM in Mesen2, reads OAM/VRAM/SRAM/pixels
python -m pytest tests/test_rpg_corrupt_save.py tests/test_rpg_oracle_two_run.py -q
```

Every assertion reads real rendered output — OAM entries, VRAM tilemap bytes,
SRAM save bytes, screenshot pixels, and recorded-audio energy — never a proxy
game variable. To see it yourself, boot the ROM and grab a frame:

```python
from infrastructure.test_harness.mesen_runner import MesenRunner
r = MesenRunner(); r.load_rom("build/rpg.sfc", run_seconds=1.0); r.run_frames(14)
r.take_screenshot("rpg_overworld.png"); r.stop()
```
