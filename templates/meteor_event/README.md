# meteor_event — an in-level cutscene that swaps Mode 1 <-> Mode 7

## What it is

A tiny Mode-1 platformer slice that becomes a cutscene and returns. You walk a
player right across a flat ground with two platforms; when you reach the trigger a
"meteor event" fires: the screen freezes, the BG platforms are captured as
sprites, and the game forced-blank-swaps to a STATIC Mode-7 meteor scene. The
meteor grows, falls off the bottom, and a red impact glow rises behind the sprites
and recedes — then the game swaps back to the Mode-1 level and hands control back.
It is one state machine: PLAY -> FREEZE -> CAPTURE -> SCENE -> RESTORE -> PLAY.

| Button | Action |
|---|---|
| **D-pad RIGHT** | walk the player right toward the trigger |
| (during the cutscene) | input is gated — the player holds still; control returns after |

## What it teaches

- **A Mode-1 <-> Mode-7 mid-level swap** — `sf_scene_mode.inc`
  (`sf_swap_to_mode7`, `sf_swap_to_mode1_begin/end`): under a forced blank, tear
  down one video mode and build the other (re-upload the map/CHR, re-stage the
  palette, flip BGMODE). Mode 7 fills VRAM $0000-$3FFF, which overlaps the Mode-1
  BG1 CHR, so the two modes cannot coexist — the swap is the whole point.
- **The BG->OBJ "capture" trick** — before blanking the Mode-1 BG, `ST_CAPTURE`
  walks the visible BG1 tilemap and emits an OBJ sprite pixel-aligned to each
  platform cell (`spr tile, mx*8 - hofs, my*8 - vofs`). The captured ground lands
  on the SAME pixels the BG tiles occupied, so it survives the swap composited
  over the Mode-7 meteor.
- **Whole-plane affine Mode 7** — `sf_mode7_affine.inc`
  (`sf_boss_mode7_on/center/matrix`): the meteor art is centered on the affine
  pivot, so ramping `g_scale` grows it IN PLACE while the scroll slides it off the
  bottom and a slow angle ramp tumbles it.
- **An OBJ-excluded color-math glow** — `sf_fx.inc` gradient + color math: a
  top-black -> bottom-red ADD gradient tints the lower band while OBJ is excluded,
  so the meteor glow reddens the scene without staining the captured ground or the
  player.

## Three things to tweak

- **`WALK_SPEED`** (`main.asm`, equates; default 2 px/frame) — how fast the player
  walks right. Raise it to reach the trigger sooner.
- **`TRIGGER_X`** (`main.asm`, equates; default 240) — the world X the player must
  reach for the meteor event to fire. Lower it to trigger the cutscene almost
  immediately; raise it for a longer walk-up.
- **`SCN_END`** (`main.asm`, the scene sub-timeline; default 180 frames = ~3 s) —
  how long the Mode-7 meteor scene runs before it swaps back and returns control
  (`SPRITE_END` splits it into the sprite-approach and Mode-7 halves).

## How it's verified

- **Build:** `make meteor_event` (the `LDCFG: lorom_64k.cfg` sentinel selects a
  64KB image whose BANK1 holds the 32KB Mode-7 meteor-map blob). Negative-control
  variants build via `build_meteor_event_variants.sh` (`-DNO_CAPTURE`,
  `-DNO_FREEZE`, `-DNO_SCALE`, `-DNO_GRADIENT`), which each break one behavior so a
  passing test is proven non-vacuous.
- **Test:** `python -m pytest tests/test_meteor_event.py -q` — reads the rendered
  output: the player walks right and the camera follows; at the trigger the freeze
  holds input (the player pixel does not move); the capture lands the OBJ ground on
  the platform pixels; the swap shows the Mode-7 meteor with the captured sprites
  on top; the meteor grows and the red glow rises then recedes; and the swap back
  restores a walkable Mode-1 level.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/meteor_event.sfc', run_seconds=2.0); r.take_screenshot('/tmp/meteor_event.png'); r.stop()"`
