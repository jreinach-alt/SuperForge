# breaker — a paddle-and-ball block-breaker

## What it is

A complete little block-breaker in one ROM: slide a cyan paddle under a white
ball, launch it into a six-row rainbow brick wall, and clear all 180 bricks to
WIN before you run out of balls. Miss the ball three times and it's GAME OVER.
Bounce, brick, lose, and win all blip. Boots into a "BRICK BUSTER / PRESS A"
title, plays, and soft-restarts from GAME OVER or WIN — no power cycle.

| Button | Action |
| --- | --- |
| D-pad left / right | Move the paddle |
| A | Launch the ball (from the WAIT title) |
| START | Restart after GAME OVER or WIN |

Rules: clear all 180 bricks to WIN. Letting the ball fall past the paddle costs
one of your 3 balls; at zero it's GAME OVER. Where the ball strikes the paddle
picks its outgoing angle (four "english" zones), so you can aim.

## What it teaches

Open `main.asm` at `game_loop` (the once-per-frame heartbeat) and read down. It
composes these kit features:

- **Tile-flag terrain + probes** (`sf_tile_flags`, `col_map`,
  `lib/macros/sf_map.inc`): bricks and walls are BG1 cells flagged solid (bit 0)
  or breakable (bit 1); the ball probes its leading edge at two points each axis
  so a cell-spanning contact still registers — the canonical maze move-check,
  here with brick-breaking bolted on.
- **Tilemap building** (`mset`, `lib/macros/sf_bg.inc`): `build_level` lays the
  walls and the six brick rows into the BG1 shadow tilemap, and a brick hit
  `mset`s its cell back to tile 0 as it breaks.
- **Sprite-vs-box collision + english** (`col_box`, `lib/macros/sf_collision.inc`):
  the ball-vs-paddle test, plus a four-zone deflection that reads where the ball
  hit the paddle to choose the outgoing X velocity.
- **Sprites** (`spr`, `spr_clear`, `lib/macros/sf_sprite.inc`): the 3-segment
  paddle and the ball in shadow OAM; the dead ball parks offscreen on the end
  screens.
- **HUD text** (`sf_text`, `lib/macros/sf_text.inc`): reprint-on-change SCORE and
  a single-digit BALLS counter, plus the title / GAME OVER / WIN messages.
- **Audio over TAD** (`sf_audio`, `lib/macros/sf_audio.inc`): wall / paddle /
  brick / lose / win blips, and the audio build shape (`lorom_tad.cfg`, selected
  by the `LDCFG:` sentinel in `main.asm`).

## Three things to tweak

1. **`PADDLE_SPEED`** (`main.asm`, the geometry equates) — how many pixels the
   paddle slides per frame (default 3). Raise it to 5 and the paddle snaps across
   the arena; the wall clamps (`PADDLE_MIN_X` / `PADDLE_MAX_X`) still hold it in.
2. **`BG_RED` / `BG_ORANGE` / `BG_YELLOW` / `BG_GREEN`** (`main.asm`, the colour
   equates) — the four brick-row colours as 15-bit BGR words. Swap one and that
   row recolours: they upload to BG palette 0 with `sf_bg_color` at boot, and the
   rows cycle through the four down the wall.
3. **`BALL_LOST_Y`** (`main.asm`, the geometry equates) — the pit line at y=216,
   16 px below the paddle. Lower it toward the paddle and a dipping ball is lost
   sooner; raise it and near-misses get a longer grace before `floor_check` fires.

## How it's verified

Everything is checked on the cycle-accurate emulator (Mesen2, headless) reading
rendered output — VRAM / OAM / CGRAM bytes and screenshots — never a proxy.

```bash
make breaker                              # build build/breaker.sfc
python -m pytest tests/test_breaker.py -q
```

`tests/test_breaker.py` drives the whole state cycle: the field renders (walls +
180 bricks in VRAM, HUD on BG3, paddle/ball in OAM and pixels), the paddle moves
both directions and clamps, A launches, the ball bounces inside the arena
breaking bricks (VRAM cells clear, SCORE/BALLS reprint), a closed-loop bot keeps
a rally alive and later clears all 180 for the WIN, a lost ball returns to WAIT,
and losing all three reaches GAME OVER with a full Start-reset. The audio blips
are gated on recorded WAV peak.

To see a frame yourself, boot the ROM headless and grab a screenshot:

```python
from infrastructure.test_harness.mesen_runner import MesenRunner
r = MesenRunner(); r.load_rom("build/breaker.sfc", run_seconds=1.0)
r.take_screenshot("/tmp/breaker_title.png"); r.stop()
```
