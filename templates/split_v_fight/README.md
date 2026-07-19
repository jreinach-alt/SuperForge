# split_v_fight — the seamless distance-driven fighting-game split

## What it is

A ground-level two-fighter arena whose camera splits **seamlessly** into
left/right halves as the fighters part, and merges just as seamlessly as they
close — no pop, no shift. The split is not a toggle: the two cameras diverge
*continuously* from the fighter distance, so at zero separation the halves are
pixel-identical and the ever-present seam is invisible. A vertical **beveled
BG3 bar** grows from zero width to mark the divide once the halves part. The
fighters may walk past each other and **swap sides** — the split follows the
crossover.

The arena is dressed with real CC0 art: a grass-topped dirt floor under an open
sky, converted from the **Four Seasons** platformer tileset, and the two
fighters are one **camelot knight** (Arthur) drawn twice as a P1/P2 palette swap
— red team on the left, blue team on the right, each facing the centre — so the
side-swap reads at a glance. All of it is band-safe by construction: the stage
palette and both team palettes avoid the tones the bevel probe reads at the seam
(see the provenance + band-safety notes in `assets/stage.inc` / `assets/knight.inc`
and `main.asm`). Assets are converted with `tools/png2snes.py`; provenance and
grants are in [`examples/itch_cc0/LICENSES.md`](../../examples/itch_cc0/LICENSES.md).

| Input | Action |
|---|---|
| P1 (port 0) D-pad Left / Right | walk fighter 1 (red, left) |
| P2 (port 1) D-pad Left / Right | walk fighter 2 (blue, right) |
| — | crossing over triggers a clash SFX; arena music plays throughout |

The **default build is interactive** (two controllers). The `-DAUTODEMO` build
takes no input: the fighters march wall-to-wall through each other, swapping
sides and back, so the whole seamless separate/merge/side-swap cycle plays out
on its own. Static `-DHOLD=n` builds freeze the fighters at ±n px about centre
for race-free framebuffer proofs (see `build_split_v_fight.sh`).

## What it teaches

- **Seamless vertical split via continuous camera divergence** — the
  `sf_split_v_bevel` (one-time setup) + `sf_split_v_spread` (per-frame) pair in
  [`lib/macros/sf_split_v.inc`](../../lib/macros/sf_split_v.inc), built on the
  PPU window system in [`lib/macros/sf_window.inc`](../../lib/macros/sf_window.inc).
  Full write-up: [`docs/guides/split_v.md`](../../docs/guides/split_v.md).
- **A zero-sprite divider on BG3** — a 3-tone beveled bar (highlight / mid /
  shadow) uploaded to BG3 CHR and revealed only inside a window band, whose
  half-width ramps from zero so it steals no screen width at merge. Shows the
  forced-blank discipline for CHR + CGRAM uploads (the PPU drops those writes
  with the display on).
- **OBJ that follow a side-swap** — each fighter is drawn against its current
  half's camera by re-picking the assignment every frame
  ([`lib/macros/sf_sprite.inc`](../../lib/macros/sf_sprite.inc)), so a crossover
  is handled without any per-sprite X9/wraparound bookkeeping.
- **Wiring TAD audio into a rail** — music + a triggered SFX over the
  [`lib/macros/sf_audio.inc`](../../lib/macros/sf_audio.inc) front door (the
  `lorom_tad.cfg` build shape).

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`WALK_SPD`** (the equates block) — how many px/frame each fighter walks.
   Raise it and the fighters (and the split opening/closing) move faster. If you
   push it up, raise `SPR_STEP` too, or the divider visibly lags the fighters.
2. **`MERGE_DX`** — the fighter separation (px) below which the view is fully
   merged. Lower it and the split starts opening while the fighters are still
   close; raise it and they must part further before the seam appears.
3. **`SPR_STEP`** — the per-frame ease rate (8.8 fixed) the spread chases its
   target with. Smaller = the divider opens and closes more slowly and smoothly;
   larger = it snaps to the fighter distance.

## How it's verified

```bash
make split_v_fight                       # build the default ROM (lorom_tad.cfg)
bash templates/split_v_fight/build_split_v_fight.sh   # the -D proof variants
python -m pytest tests/test_split_v_fight.py -q       # 7 rendered-output asserts
```

The suite ([`tests/test_split_v_fight.py`](../../tests/test_split_v_fight.py))
reads the **rendered framebuffer** on the cycle-accurate emulator: the merge is
pixel-identical to a no-split reference; the authored beveled bar renders its
highlight-and-shadow tones and ramps from zero width; the fighters track their
halves and swap sides seamlessly through a crossover; and the arena clamp holds
under adversarial input. To watch it run, boot
`build/split_v_fight_autodemo.sfc` in any SNES emulator (or drive it from
`MesenRunner`, as the tests do).
