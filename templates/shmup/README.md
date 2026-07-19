# shmup — vertical-scrolling shooter rail

## What it is

A vertical shmup in one ROM, built entirely from converted CC0 art: fly a ship
over a drifting island field, shoot the ghosts that descend at you, and don't get
touched. It is the kit's **proof-of-pipeline** template — the ship, the enemies,
and the terrain all came through `tools/png2snes.py` from the packs in
`examples/itch_cc0/` (each `assets/*.inc` header records the exact command).

| Button | Action |
| --- | --- |
| D-pad | Move the ship (clamped to the playfield) |
| A | Fire — one bullet per press (rising edge) |
| START | On GAME OVER, begin a fresh game |

Rules: bullets fly up and a hit bursts a ghost for one point on the SCORE HUD. A
ghost that touches the ship costs one of your 3 lives — the ship respawns at
spawn and blinks while invulnerable; at zero lives it is GAME OVER and the world
freezes until you press START. (SCORE is a 16-bit counter and wraps at 65536 —
about 65k kills away, so you will never see it in normal play.)

## What it teaches

Open `main.asm` at `game_loop` (the once-per-frame heartbeat) and read down. It
composes:

- **Object pools** (`sf_pool`, `lib/macros/sf_pool.inc`): fixed-slot bullet and
  enemy arrays, spawned/killed by index, drawn with the **stable-OAM-slot** idiom
  — every slot is drawn every frame (dead ones parked at `y=$F0`), so OAM slot k
  always belongs to the same actor (0 = ship, 1–6 = bullets, 7–10 = ghosts).
- **Box collision** (`col_box`, `lib/macros/sf_collision.inc`): bullet-vs-ghost
  for the kill, and ship-vs-ghost for the player-damage hit.
- **Vertical autoscroll** (`sf_autoscroll_v`, `lib/macros/sf_bg.inc`): the island
  tilemap drifts down and wraps seamlessly (a 32-row map stamped from an 8×6 patch).
- **Sprite animation** (`sf_anim`, `lib/macros/sf_anim.inc`): a shared frame clock
  cycles the hero and the ghosts through all 8 of their resident VRAM frames.
- **Damage feedback**: i-frames + a blink (`HURTLOCK` & `BLINK_PHASE`), respawn at
  spawn, a LIVES counter, and a GAME-OVER freeze/restart grafted into the loop —
  the "game-loop composition" pattern the thin rail leaves to you.
- **Audio over TAD** (`sf_audio`, `lib/macros/sf_audio.inc`): a boot track
  (`sf_music Song::gimo_297`) plus fire (`SFX::fire_arrow`), kill (`SFX::noise`),
  and hurt (`SFX::player_hurt`) effects, on the audio build shape
  (`lorom_tad.cfg`, selected by the `LDCFG:` sentinel — see
  `docs/guides/adapting_a_rail.md`).
- **HUD text** (`sf_text`): a reprint-on-change SCORE and LIVES row.

## Three things to tweak

1. **`SPAWN_PERIOD`** (`main.asm`, the tuning block) — frames between ghost
   spawns (default 48). Drop it to 16 for a dense swarm; raise it for a lazy
   trickle. Overridable by defining it before the `.include`, or just edit.
2. **`spawn_xs`** (`main.asm`, the DATA section) — the 8-entry table of columns
   the ghosts spawn at, cycled in order. Rewrite it to author an attack pattern
   (e.g. all one column for a firing lane, or a left-to-right sweep).
3. **`START_LIVES`** (`main.asm`, the player-damage tuning) — ships before GAME
   OVER (default 3). Set it to 1 for a one-hit run, or raise it for a forgiving
   demo; the HUD digit and the GAME-OVER gate track it automatically.

## How it's verified

Everything is checked on the cycle-accurate emulator (Mesen2, headless) reading
rendered output — OAM / WRAM bytes and screenshots — never a proxy.

```bash
make shmup                                 # build build/shmup.sfc
python -m pytest tests/test_shmup.py -q
```

`tests/test_shmup.py` boots the ROM and asserts the rendered result: terrain +
ship + HUD render, the terrain autoscrolls, the ship moves in all four directions
(clamped), a fired bullet travels up and expires, a ghost spawns at its table
column and descends, a bullet kills a ghost and the SCORE HUD re-renders, a ghost
that touches the ship costs a life with an i-frame blink and a spawn respawn, and
zero lives freezes into GAME OVER that START restarts.

To see a frame yourself, boot the ROM headless and grab a screenshot:

```python
from infrastructure.test_harness.mesen_runner import MesenRunner
r = MesenRunner(); r.load_rom("build/shmup.sfc", run_seconds=1.5)
r.take_screenshot("/tmp/shmup.png"); r.stop()
```
