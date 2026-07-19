# platformer — the flagship rail

## What it is

A complete little side-scrolling platform game in one ROM, start to restart:
walk and jump a hero across a 512×224 level, collect all the coins to WIN, stomp
or dodge two patrol ghosts, and don't fall in a pit. It is the kit's showcase —
title → game → game-over / win → soft-restart back to the title, with a dusk
parallax sky, music + sound effects, and a battery-SRAM "continue".

| Button | Action |
| --- | --- |
| D-pad left / right | Walk |
| A **or** B | Jump (hold for a higher jump) |
| START (in game) | Pause / unpause |
| START (menus) | Begin, or return to the title |
| SELECT (title) | Continue from the banked save (only when it is offered) |

Rules: collect all 6 coins to WIN. A side touch from a ghost or a pit fall costs
one of your 3 lives; at zero it's GAME OVER. Land on a ghost's head to stomp it.
A GAME OVER with coins collected banks them — the title then offers SELECT =
CONTINUE, restoring the bank on a fresh level.

## What it teaches

This rail composes most of the kit; open `main.asm` at `game_loop` (the
once-per-frame heartbeat) and read down. It exercises:

- **Scene state machine + soft restart** (`sf_scene`, `lib/macros/sf_scene.inc`):
  a declared id→init/tick table with `sf_scene_goto` / `sf_scene_dispatch`, and
  the discipline that each scene init rebuilds only what it owns — no power cycle.
- **Scrolling level world** (`sf_level`, `lib/macros/sf_level.inc`): a 64×32
  two-page tilemap with camera follow, per-axis box collision, one-way platforms,
  a pit death plane (`sf_pit`), coins as flagged tiles, and a patrol that walks
  across the world's page seam (`sf_level_patrol_step`).
- **Jump physics** (`sf_jump`, `sf_jump_cut`): a variable-height jump, landing
  snap, and head bump.
- **Sprites + animation** (`sf_sprite`, `sf_anim`): a 16×16 hero with H-flip
  facing, a shared animation clock, and an invulnerability (i-frame) blink.
- **Look & feel** (`sf_fx`, `lib/macros/sf_fx.inc` — the look-&-feel group): a
  two-band BG2 parallax skyline, a dusk RGB gradient on the backdrop through
  color math, and a brightness fade-in on every scene transition. The VRAM /
  CGRAM / HDMA-channel budget is mapped in the `LOOK & FEEL` header block.
- **Battery save / continue** (`sf_save`, `lib/macros/sf_save.inc`): a slot-0
  coin bank with a magic + CRC + version + length validity gate (`cont_gate`),
  falling back cleanly to a new game on any invalid slot.
- **Audio over TAD** (`sf_audio`): per-scene music and jump / coin / hurt / stomp
  SFX, and the audio-plus-SRAM build shape (`lorom_tad_sram.cfg`, selected by the
  `LDCFG:` sentinel — see `docs/guides/adapting_a_rail.md`).
- **HUD text** (`sf_text`): reprint-on-change LIVES + COINS counters.

## Three things to tweak

1. **`TOTAL_COINS`** (`main.asm`, the world-geometry equates) — how many coins
   WIN the game. Lower it to 3 and the win card fires halfway through the level;
   the HUD and the `sf_scene_goto SC_WIN` gate track it automatically.
2. **The dusk gradient** (`DUSK_TOP_R/G/B` → `DUSK_BOT_R/G/B` in `main.asm`) —
   the top-to-bottom sky color ramp (0–31 per channel). Swap in a dawn or noon
   palette and the whole backdrop re-ramps; the sky is drawn by `sf_gradient_rgb`
   at boot.
3. **`PLX_RTOP` / `PLX_RBOT`** (`main.asm`) — the two parallax band speeds, each
   a fraction of camera X (`n/256`). Raise `PLX_RBOT` and the near hills chase
   the camera harder; set both equal and the sky scrolls as one flat plane.

## How it's verified

Everything is checked on the cycle-accurate emulator (Mesen2, headless) reading
rendered output — VRAM / OAM / CGRAM bytes and screenshots — never a proxy.

```bash
make platformer                                    # build build/platformer.sfc
python -m pytest tests/test_platformer.py \
                 tests/test_platformer_v2.py \
                 tests/test_platformer_v3.py \
                 tests/test_platformer_cycles.py \
                 tests/test_input_driver_platformer.py -q
```

- `tests/test_platformer.py` — the full game: a closed-loop bot drives the whole
  6-coin WIN route (both platforms, the seam ledge with a mid-route stomp, both
  pits), plus the soft restart, pit-death → GAME OVER, the stale-BG regression,
  the pause freeze, and the B-jump alias.
- `tests/test_platformer_v2.py` — the look-&-feel gates (parallax rates + freeze,
  the dusk ramp, the fade-in), rendered-pixel only.
- `tests/test_platformer_v3.py` — the save/continue lifecycle, including honest
  corrupt / wrong-version / wrong-length SRAM fallbacks.
- `tests/test_platformer_cycles.py` — the measured per-frame cost of
  `sf_parallax_tick` and `sf_bright_fade_tick` (frame-budget method).

To see a frame yourself, boot the ROM headless and grab a screenshot:

```python
from infrastructure.test_harness.mesen_runner import MesenRunner
r = MesenRunner(); r.load_rom("build/platformer.sfc", run_seconds=1.5)
r.take_screenshot("/tmp/platformer_title.png"); r.stop()
```
