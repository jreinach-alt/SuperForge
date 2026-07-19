# camera_follow — a scrolling camera that tracks the player

## What it is

A red player you move with the d-pad through a 512x448 world (four screens)
over a tiled checkerboard background. The camera centres the player and scrolls
the background to follow, but clamps at the world edges so the view never runs
off the world — there the player walks toward the screen edge instead of the
camera scrolling past it. It is a focused demo of the camera-follow primitive.

| Button | Action |
|---|---|
| **D-pad** | move the player through the world (camera follows, then clamps) |

## What it teaches

- **Camera follow with edge clamp** — `sf_camera.inc`
  (`sf_camera_follow`): given the player's world position and the world size,
  it produces a clamped camera origin and scrolls BG1 to it, so the player
  holds screen-centre in open world and the camera stops at the borders.
- **World space vs screen space** — the player lives in world coordinates
  (`PWX`/`PWY`); the sprite is drawn at `world - camera` (`SCRX`/`SCRY`), which
  is the whole trick behind a scrolling actor.
- **A repeating tiled background** — the checkerboard is built once with
  `mset` (`sf_bg.inc`) and repeats every 256 px as the camera scrolls, so a
  small tilemap covers a large world.
- **`sf_clamp0`** keeps the player inside the world bounds independently of the
  camera clamp.

## Three things to tweak

- **`WORLD_W` / `WORLD_H`** (`main.asm`, in the equates) — the world size in
  pixels. Grow them and the camera scrolls further before it clamps; shrink
  them toward 256/224 and the camera barely moves.
- **`SPEED`** (`main.asm`, in the equates) — the player's move step in pixels
  per frame. Raise it to cross the world faster.
- **`OBJ_RED`** (`main.asm`, in the equates) — the player's colour as a 15-bit
  BGR value. Change it to recolour the sprite.

## How it's verified

- **Build:** `make camera_follow` (-> `build/camera_follow.sfc`).
- **Test:** `python -m pytest tests/test_camera_follow.py -q` — reads the
  rendered result: the green BG and red sprite are visible, the player boots at
  world centre with the sprite screen-centred, and on all four axes the camera
  TRACKS mid-world (sprite holds centre while the BG scrolls) then CLAMPS at the
  world edge (camera stops, sprite moves to the on-screen edge and stays on
  screen).
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/camera_follow.sfc', run_seconds=1.0); r.take_screenshot('/tmp/camera_follow.png'); r.stop()"`
