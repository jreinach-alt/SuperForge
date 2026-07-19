# hud_game — a movable sprite with a live text HUD

## What it is

A red player you move around the screen with the d-pad, over a white
`SCORE 00000` line drawn on the BG3 text layer. Pressing A bumps the score and
the on-screen counter reprints — but only on the frame the value actually
changes, so the HUD costs one small tilemap write instead of a per-frame
reprint. It is the smallest complete demo of the text surface composed with
sprites and input.

| Button | Action |
|---|---|
| **D-pad** | move the player (screen space) |
| **A** | bump the score by 1 (counted once per press) |

## What it teaches

- **The text surface** — `sf_text.inc` (`sf_text_init`, `print`,
  `sf_print_u16`): a BG3 tile font plus a 16-bit number printer. The label is
  printed once at boot; the counter is reprinted only when `SCORE` changes.
- **The cheap-HUD pattern** — reprint-on-change. The A-press branch compares
  and rewrites the digits, and the NMI commits that tilemap edit next VBlank;
  an idle frame writes nothing.
- **Sprite + input composition** — `sf_sprite.inc` (`spr`, `spr_clear`) draws
  the player each frame; `sf_input.inc` (`btn` for held d-pad, `btnp` for the
  A rising edge) reads the pad; `sf_clamp0` (from `sf_camera.inc`) keeps the
  8px sprite on screen.
- **Edge vs level input** — the d-pad uses `btn` (moves while held) while the
  score uses `btnp` (fires once on press), so holding A does not run the score
  up every frame.

## Three things to tweak

- **`SPEED`** (`main.asm`, in the equates) — the player's move step in pixels
  per frame. Raise it and the player crosses the screen faster.
- **`OBJ_RED`** (`main.asm`, in the equates) — the player's colour as a 15-bit
  BGR value. Change it (e.g. `$7FE0` for cyan) and the sprite recolours.
- **`str_score`** (`main.asm`, in the DATA section) — the HUD label text. Edit
  the bytes (keep the trailing `0`) to relabel the counter, e.g. `"COINS"`.

## How it's verified

- **Build:** `make hud_game` (-> `build/hud_game.sfc`).
- **Test:** `python -m pytest tests/test_hud_game.py -q` — reads the rendered
  output, not proxy state: the BG3 tilemap words for the `SCORE` label and the
  five digits, the white HUD pixels and red sprite pixels in a screenshot, OAM
  X moving under a right press while the HUD stays put, and the counter's VRAM
  digit tiles changing when A bumps the score (a held A counts exactly once).
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/hud_game.sfc', run_seconds=1.0); r.take_screenshot('/tmp/hud_game.png'); r.stop()"`
