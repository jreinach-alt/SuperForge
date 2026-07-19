# boss_saucer — a Mode 7 SCALING boss battle

## What it is

A boss fight whose **signature is SCALING**: the enemy is a flying saucer that
*is* the Mode 7 background plane, and the hardware affine matrix zooms it for
free. It **lunges** at the camera — growing from a far speck to a screen-filling
disc — and at the apex fires a vertical **beam** straight down a column locked to
your position. You are a gunship sprite composited over the saucer; strafe out of
the beam column, shoot the wide saucer down, and mind your 3 HP. Win or lose, a
result card holds over the dimmed arena, then the battle loops.

| Input | Action |
|---|---|
| ← / → (Left / Right) | strafe the gunship along the bottom band |
| A (held) | fire a shot straight up (rate-limited to a steady stream) |
| START | pause / unpause the fight |
| Select | *(unmapped — this rail has no in-game menu)* |

## What it teaches

- **Mode 7 static affine scaling — "the boss IS the screen."** One uniform
  affine matrix per frame scales/zooms the whole plane; no HDMA, no per-scanline
  rebuild. Driven through
  [`lib/macros/sf_mode7_affine.inc`](../../lib/macros/sf_mode7_affine.inc)
  (`sf_boss_mode7_on` installs it, `sf_boss_matrix` writes M7A–D from a
  `(scale, angle)` each frame). The lunge is just a per-frame ramp of `b_scale`.
  Genre write-up: [`docs/guides/mode7_boss.md`](../../docs/guides/mode7_boss.md).
- **OBJ-over-Mode 7 composition.** The map fills VRAM words `$0000–$3FFF`, so the
  OBJ name base moves to word `$4000` (OBSEL size pair 0 = 8×8/16×16). The
  player, beam segments, HP pips, shots, and the text cards are all sprites
  ([`lib/macros/sf_sprite.inc`](../../lib/macros/sf_sprite.inc)) over the affine
  BG, in a stable OAM slot map the tests read by identity.
- **A masked reset under forced blank.** The win/lose loop re-inits the battle
  while the screen is faded to black via
  [`lib/macros/sf_fx.inc`](../../lib/macros/sf_fx.inc) (`sf_bright_fade`) — never
  a live tilemap rebuild the PPU could catch mid-frame.
- **Pooled projectiles + AABB collision.** A 4-slot shot pool
  ([`lib/macros/sf_pool.inc`](../../lib/macros/sf_pool.inc)) feeds `col_box`
  ([`lib/macros/sf_collision.inc`](../../lib/macros/sf_collision.inc)) for
  shot-vs-saucer and beam-vs-player hit tests.
- **TAD music + SFX.** A boss theme plus fire / beam / hit effects through
  [`lib/macros/sf_audio.inc`](../../lib/macros/sf_audio.inc) on the audio + Mode 7
  map link shape (`lorom_tad_m7.cfg`).

## Three things to tweak

1. **`LUNGE_NEAR_SCALE`** in [`main.asm`](main.asm) (the LUNGE block, = `$00A0`) —
   the matrix scale at the lunge apex. The matrix maps screen→texel, so a
   *smaller* value makes the saucer **bigger** at the peak. Drop it toward
   `$0060` and the saucer fills the screen; raise it and the lunge barely grows.
2. **`BOSS_HP0`** in [`main.asm`](main.asm) (the combat-tuning block, = 240) — the
   saucer's HP, ≈ `BOSS_HP0 / SHOT_DMG` = 48 hits to kill. Lower it for a quick
   skirmish, raise it for an endurance fight.
3. **`#Song::gimo_297`** in [`main.asm`](main.asm) (the `sf_music` call at the end
   of `RESET`) — the boss theme. Swap it for any `Song::` id from
   [`assets/audio/tad_audio_enums.inc`](../../assets/audio/tad_audio_enums.inc).

## How it's verified

```bash
make boss_saucer                                 # build the ROM (lorom_tad_m7.cfg)
python -m pytest tests/test_boss_saucer.py -q    # 12 rendered-output asserts
```

The suite ([`tests/test_boss_saucer.py`](../../tests/test_boss_saucer.py)) drives
the fight with **real input** on the cycle-accurate emulator and asserts on the
**rendered output**, never a proxy: the reveal + lunge scaling grow the saucer's
lit-pixel area (near apex ≥ 1.5× far); the beam renders as a contiguous 16-segment
column in OAM and drains player HP in the locked column; a shot drops saucer HP
*and* a lit HUD pip; the player's hull-blue composites in front of the saucer BG;
the full win cycle loops with a masked (INIDISP 0) reset; the lose/win RESULT
shows a **DEFEAT / VICTORY card over a dimmed (not black) scene** with the glyphs
composed in OAM; the boot title card shows the controls then auto-dismisses; and
START freezes the fight. To watch it, boot `build/boss_saucer.sfc` in any SNES
emulator (or drive it from `MesenRunner`, as the tests do).
