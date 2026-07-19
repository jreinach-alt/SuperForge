# split_h_2p_demo — two-player split-screen Mode 7

## What it is

A horizontal split screen: the top half is player 1's Mode-7 floor camera, the
bottom half is player 2's, both looking at the SAME wrapping checker world from
their own position (and, in the rotate/sprite builds, their own heading).
Neither camera runs a live perspective solve — each band streams a ROM-resident
per-scanline pose table straight through the HDMA engine, so the entire
per-frame CPU is ~40 register stores. That headroom is what buys a second
camera, and then a swarm of projected sprites, at a hard 60 fps.

**The DEFAULT build is a zero-input autonomous showcase; `_sprites` is the
playable build.**

| Build / pad | Input | Effect |
|---|---|---|
| `make split_h_2p_demo` (default) | none | both cameras pan on their own; a kit music track plays |
| `_sprites`, pad 1 | D-pad ← / → | rotate camera 1 one pose step per frame held |
| `_sprites`, pad 1 | B | drive camera 1 forward (2 px/frame) |
| `_sprites`, pad 2 | D-pad ← / →, B | the same, for camera 2 |

### The build variants

`build_split_h_2p_variants.sh` emits the whole matrix. They fall into two
groups — the ones you watch/play, and the ones that exist to drive the test
oracles (many are deliberate non-vacuity **controls**, not demos):

**Showcase & playable**

| Build | What it is |
|---|---|
| `split_h_2p_demo` (default) | Zero-input autonomous floor demo + music. |
| `_rotate` | Both cameras rotate AND drive forward — two opposite circles (256-pose). |
| `_rotate64` | Same idea, the 64-pose single-bank shape. |
| `_rotfreeze` | Rotate-in-place (position frozen). |
| `_sprites` | **The play build:** 24 sprites (2 players + 22 AI followers) + size tiers, two-pad input. |
| `_spr_alt` | Alternate-frame reprojection probe — 64 sprites re-projected at 30 Hz. |

**Test instruments & controls** (drive the oracles; not meant to be "played")

| Build | Role |
|---|---|
| `_freeze` | Frozen scene — the still the seam / position / motion tests read. |
| `_sameorigin` | Camera 2 folded onto camera 1 — position non-vacuity control (band-2 red must die). |
| `_retarget` | Band 2's pose flips at frame 90 — the retarget-by-pointer smoke. |
| `_latch` | A write-twice M7HOFS spun across display — the latch-tear negative control. |
| `_perband` / `_badorder` | Per-band channel pairs / inverted allocation order (line-0 stray-write control). |
| `_spr_cyc` / `_spr_cycaway` / `_spr_cycfar` | Cycle-cost instruments (HDMA dark): the full, v-cull, and Chebyshev-cull paths. |
| `_spr_cycai` / `_spr_cycint` | AI-only and integrated per-frame cost instruments. |
| `_spr_rot` / `_spr_pinvis` | Auto-rotate cadence grid / worst-case all-visible pinned. |
| `_spr_tier` / `_spr_tieroff` / `_spr_culloff` | Tier ladder + the constant-tier and margins-off controls. |
| `_spr_pin_a/_b/_c` / `_spr_pinfwd` | Pinned glue-proof stills / the wrong-matrix (`SP_FORWARD`) control. |

### The shipped sprite count (N = 24)

`_sprites` ships `SPRITES=24` because 24 is the largest count that holds +1/+1
loop-vs-NMI cadence lockstep with ≥15% modeled headroom (measured on the
integrated build: 24 → 31% headroom, 32 → 10%, 48+ breaks). It is 2
player-driven cameras plus 22 AI waypoint-followers on the asymmetric main
world. To reproduce the showcase look: drive both pads — rotate with the D-pad
and hold B to advance — so each camera sweeps its half of the followers through
view while the AI paths its loops autonomously. The live count is also
WRAM-poked at `SP_N` (`$7E:C0C0`), which is how the sweep test walks 1..128.

## What it teaches

- **Two independent Mode-7 cameras over ONE map**, split horizontally at
  scanline 112 — each band with its own live world position and heading.
- **Per-scanline matrix streaming** with INDIRECT-mode HDMA (`DMAP $43`)
  through template-owned index tables, and **per-band world position** via the
  origin channel pair (`DMAP $03`) re-stamped each VBlank — no live solve.
- **The HDMA channel allocator** (`hdma_alloc.asm`) and load-bearing channel
  priority ordering (the per-band line-0 stray-write mask).
- **Inverse-Mode-7 sprite projection** (`sprites_2p.inc`): an 8×8
  hardware-multiply dot core (`$4202/$4203`, sign/magnitude split), a
  build-time inverse LUT, OAM slot compaction into a 544-byte shadow, and a
  five-step size-tier ladder — the measured sprite-stress core.
- **Music over the TAD driver** via `lib/macros/sf_audio.inc` (the audio build
  shape: a `*_tad*.cfg` link + the wrapper/data objects).
- Deep dive with the measured cost chain and the sprites-vs-cadence curve:
  `docs/guides/split_h.md`.

## Three things to tweak

1. **`SPRITES=24`** — the count on the `_sprites` line of
   `build_split_h_2p_variants.sh`. Raise it (say 48) and rebuild: more
   character tokens fill the bands, and past the headroom cliff the cadence
   gate visibly breaks (`test_sp_cadence_sweep_curve` records the whole curve).
2. **`P2_X0 = 768`** (`main.asm`) — camera 2's starting world X, centred on the
   warm (red) stripe. Move it toward 512 and band 2 drifts onto the cool
   stripe, so its red half fades — the same effect the `_sameorigin` control
   forces on purpose.
3. **`#Song::ode_to_joy`** (`main.asm`, the `sf_music` line) — the showcase
   track. Swap for any id in `assets/audio/tad_audio_enums.inc`.

## How it's verified

```bash
make split_h_2p_demo
bash templates/split_h_2p_demo/build_split_h_2p_variants.sh   # the -D matrix
python -m pytest tests/test_split_h_2p_demo.py tests/test_split_h_2p_audio.py -q
```

`test_split_h_2p_demo.py` is 27 assertions, every one reading the rendered
framebuffer (or, for the cadence gate, the two WRAM loop counters whose
lockstep IS the claim) and every one paired with a same-metric non-vacuity
control. `test_split_h_2p_audio.py` is the WAV-energy gate on the showcase
music. See it headlessly:

```bash
python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner
r = MesenRunner()
r.load_rom("build/split_h_2p_demo.sfc", run_seconds=2.0)
r.take_screenshot("/tmp/split_h_2p.png")
r.stop()
EOF
```

The `.sfc` also runs in any SNES emulator (Mesen2, bsnes, snes9x) or on real
hardware via a flashcart.
