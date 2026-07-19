# split_h_demo — the cockpit horizontal raster-band split

## What it is

The demo rail for `sf_split_h`: a receding Mode-7 **perspective floor** in the
lower band, under a genuine BG3 **tile instrument panel** in the top band. HDMA
rewrites `BGMODE` and `TM` at a fixed scanline, so the top renders as Mode 1 (BG3
visible) and the bottom as Mode 7 (the floor) across one clean scanline seam. A
live fill-bar on BG3 tracks input, and the Mode-7 camera can spin to stress the
split under a full per-frame matrix rebuild. It proves the primitive, not a game.

| Input | Action |
|---|---|
| P1 D-pad ← / → | drive the instrument-bar fill down / up |
| P1 L / R shoulders | spin the Mode-7 camera (the "split under load" stress) |

The `-DAUTODEMO` build takes no input: it sweeps the bar and spins the camera on
the frame counter.

### The build variants

`build_split_h_variants.sh` emits the matrix. Several exist to drive the test
oracles (deliberate non-vacuity **controls**), not to be watched:

| Build | What it is |
|---|---|
| `split_h_demo` (default) | Mode/TM split + colour-tint band, interactive. |
| `_autodemo` | Self-running: bar sweep + continuous camera spin. |
| `_threeband` | Adds a 3-region brightness split via `sf_split_h_bands`. |
| `_bright` | Archetype-D brightness band (top full, bottom dimmed). |
| `_toggle` | P1 A cycles the mode/TM split OFF then back ON (lifecycle). |
| `_nosplit` | **Control:** split compiled out — the top tile band must vanish. |
| `_nocolor` | **Control:** COLDATA band compiled out — the tint change must vanish. |
| `_freeze` | **Control:** bar fill pinned — the two-state fill difference must vanish. |

## What it teaches

- **A horizontal raster-band split** via `sf_split_h_2band` in
  [`lib/macros/sf_split_h.inc`](../../lib/macros/sf_split_h.inc): per-band HDMA on
  `BGMODE` (mode change) and `TM` (layer enable), routed through the HDMA channel
  allocator (`hdma_request` / `hdma_bind_direct`), plus the cheaper archetype-D
  bands on `COLDATA` (a tint) and `INIDISP` (brightness).
- **Two-palette CGRAM budgeting** — the Mode-7 floor palette (group 0) and the BG3
  HUD palette (group 4) must not overlap; a build-time `.assert` fails if they do.
- **Manual BG3 placement in the upper 32 KB** — `BG3SC`/`BG34NBA` set by hand so
  BG3 clears Mode 7's low-32 KB VRAM, and the write-once base regs the engine NMI
  never re-commits.
- **The split holding under load** — spinning the camera forces a full
  per-scanline matrix rebuild (CH5/CH6) while the split's band HDMA (CH2/CH3) must
  keep rendering. And **the kit DMA idiom** — building the dynamic bar row in WRAM
  and enqueuing a GP-DMA on the VBlank queue rather than a mid-frame forced blank.
  Deep dive: [`docs/guides/split_h.md`](../../docs/guides/split_h.md).

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`SPLIT`** (default 40) — the seam scanline. It is both the band boundary and
   the perspective horizon, so moving it grows one band at the other's expense and
   reshapes the floor.
2. **`ROT_SPD`** (default 2) — camera angle units per frame while a shoulder is
   held. Raise it and the floor spins faster under the same stress.
3. **`COL_BOT`** (default `$E4`) — the lower band's added-colour intensity. Change
   it to retint the floor (the `$E0 | n` plane-select form sets R=G=B).

## How it's verified

```bash
make split_h_demo
bash templates/split_h_demo/build_split_h_variants.sh   # the -D matrix
python -m pytest tests/test_split_h_demo.py -q
```

[`tests/test_split_h_demo.py`](../../tests/test_split_h_demo.py) reads the rendered
framebuffer: the top-band tile signature is present (and absent on `-DNO_SPLIT`),
the colour band shifts pixels (absent on `-DNO_COLORBAND`), the bar fill differs
between states (pinned on `-DFREEZE_BAR`), the three- and brightness-band builds
render their distinct regions, and the toggle build cycles the split off and back
on. To watch it, boot `build/split_h_demo_autodemo.sfc` in any SNES emulator (or
drive it from `MesenRunner`, as the tests do).
