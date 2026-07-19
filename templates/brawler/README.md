# brawler — side-view beat-'em-up with animated CC0 knights

## What it is

A one-on-one brawler: Arthur Pendragon (you) versus Mordred, both animated
multi-frame 32x32 knights on a terrain floor, with an `HP / FOE / WINS` text
HUD. You move in four directions inside a shallow lane band, face your travel
direction (OAM H-flip), and swing a sword; Mordred walks toward you and hits
back. Defeat him to bank a win and he respawns; lose all your HP and the game
freezes on GAME OVER. It is the genre rail for brawlers and the kit's animated
character-art showcase (art straight from `tools/png2snes.py sprite --anims`).

| Button | Action |
|---|---|
| **D-pad** | move Arthur (4-way, within the lane band); facing follows travel |
| **A** | sword swing (a live 16x16 hitbox in front of Arthur, frames 4..12) |

## What it teaches

- **Multi-frame sprite animation** — `sf_anim.inc` (`sf_anim_step`,
  `sf_anim_tile`): per-actor clocks index idle / run / hit frame tables. The
  clock is reset on every state change so a short table is never indexed by a
  stale longer counter.
- **The facing H-flip idiom** — only the right-facing frames are stored; left
  facing sets the OAM H-flip attribute bit, halving the CHR.
- **The 9-bit tile / second name table** — Arthur loads at OBJ base 0
  (tiles 0-255), Mordred at base 256. The OAM tile byte is only 8 bits, so
  Mordred's high tile bit rides in his attribute name-select bit
  (`MORDRED_FLAGS`), set once because every Mordred tile is >= 256.
- **A timed attack hitbox** — `sf_collision.inc` (`col_box`): the swing's
  hitbox is only live during frames 4..12 and lands one hit per swing (latched),
  the standard "active frames" combat pattern.
- **Content-space clamping** — the lane band pins the knights' *drawn feet*
  (not their OAM box) to the floor's surface top, anchored to the committed art
  baselines by a build-time `.assert`.

## Three things to tweak

- **`FOE_HP`** (`main.asm`, in the tuning block; default 3) — hits to defeat
  Mordred. Raise it for a longer fight. It is `.ifndef`-guarded, so you can also
  define it before the include.
- **`WALK_SPEED`** (`main.asm`, tuning block; default 2) — Arthur's move step in
  pixels per frame. The build asserts it stays <= 8 so the clamps hold.
- **`ENEMY_SPEED`** (`main.asm`, tuning block; default 1) — how fast Mordred
  closes on you. Raise it and he is harder to out-strafe.

## How it's verified

- **Build:** `make brawler` (-> `build/brawler.sfc`).
- **Test:** `python -m pytest tests/test_brawler.py -q` — reads the rendered
  output: the floor, both knights, and the HUD render; the drawn feet clamp to
  the surface top; Arthur walks all four directions, faces his travel direction
  (OAM H-flip), and animates (idle<->run tile cycling); Mordred chases and faces
  Arthur; three landed swings tick FOE down, bank a win, and respawn Mordred
  cleanly parked off-screen; and contact ticks HP down with knockback, freezing
  on GAME OVER at zero.
- **See it:** boot the ROM headless and grab a frame —
  `PYTHONPATH=. python3 -c "from infrastructure.test_harness.mesen_runner import MesenRunner; r=MesenRunner(); r.load_rom('build/brawler.sfc', run_seconds=1.0); r.take_screenshot('/tmp/brawler.png'); r.stop()"`
