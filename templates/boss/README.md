# boss — Mode 7 boss battle (the boss IS the screen)

## What it is

A "the boss is the whole screen" fight: the boss face is drawn as the Mode 7
background, so the hardware scales and rotates it for free from one uniform
affine matrix, while the player, the boss's attacks, and the HP bar are sprites
composited on top. The fight is a state machine — the boss fades in and grows
from far away, holds, then you strafe and shoot to deplete its HP across three
escalating phases while dodging a rain of attacks; win or lose, a result screen
holds and the battle loops.

| Button | Action |
|---|---|
| **D-pad left/right** | strafe the player left and right |
| **A (hold)** | fire upward at the boss (rate-limited to a steady stream) |

## What it teaches

- **Static-affine Mode 7** — `sf_mode7_affine.inc` (`sf_boss_mode7_on`,
  `sf_boss_center`, `sf_boss_matrix`): one uniform matrix per frame from a
  (scale, angle), committed by the stock engine NMI with no HDMA. A bigger scale
  makes the boss look *smaller*; ramping it is the reveal and the death recede.
- **OBJ over Mode 7** — the map fills VRAM words `$0000-$3FFF`, so the OBJ name
  base moves to word `$4000` via `OBSEL = $62`; the affine matrix never touches
  OBJ, so the sprites composite upright on top of the scaled boss.
- **A pooled projectile system** — `sf_pool.inc` (`sf_pool_spawn`,
  `sf_pool_kill_x`): an 8-slot attack pool and a 4-slot shot pool over parallel
  WRAM arrays, integrated and culled each frame, with `col_box` for shot-vs-boss
  and attack-vs-player hits.
- **A state machine with masked resets** — INTRO / REVEAL / HOLD / FIGHT /
  DEATH / LOSE / RESULT / RESET dispatched through a jump table; the loop's
  re-init happens under a `sf_bright_fade` fade-to-black, so the discontinuous
  swap never shows on screen.
- **Stable OAM slots** — the draw assigns fixed slots (player 0, attacks 1-8,
  HP bar 9-16, shots 17-20) with the engine Y-sort disabled, so the tests can
  read sprites by identity.

## Three things to tweak

- **`BOSS_HP0`** (`main.asm`, combat tuning; default 240) — the boss's HP, and
  with `SHOT_DMG` it sets how many hits kill it (~48). Lower it for a quicker
  fight; the three phase thresholds are derived from it (`/3` bands).
- **`PLAYER_SPEED`** (`main.asm`, combat tuning; default 3) — the strafe speed
  in pixels per frame. Raise it to dodge the attack rain more easily.
- **`ATK_SPREAD`** (`main.asm`, attack-rain tuning; default 14) — the half-width
  of the central column the attacks rain into. Widen it and staying to a side
  lane no longer keeps you safe.

## How it's verified

- **Build:** `make boss` (the generic rule reads the `LDCFG: lorom_64k.cfg`
  sentinel — a 64KB image whose BANK1 holds the 32KB boss-map blob).
- **Test:** `python -m pytest tests/test_boss.py -q` — reads the rendered
  output: the REVEAL scales the BG boss up; the player sprite composites in
  front of the boss BG; a shot drops boss HP and a HP-bar segment; the attack
  rain drops player HP; attacks render at moving positions; the full state cycle
  runs the win path with a masked reset; win/lose set the result flag and loop;
  and the boss phase advances as HP falls.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/boss.sfc', run_seconds=1.5); r.take_screenshot('/tmp/boss.png'); r.stop()"`
