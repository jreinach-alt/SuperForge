# L09 — Budgets & limits: the real numbers

Every number below is either measured on the cycle-accurate emulator by a
committed test you can re-run, or a hardware constant tagged
(hardware-reference). Kit rule #1 applies to you too: **measure, never
estimate.** Builds on [L01](L01_the_frame.md), [L02](L02_graphics_model.md),
[L04](L04_dma.md).

## The idea

**The frame is the wall.** One NTSC frame is 1364 x 262 = **357,368 master
clocks** (`tests/test_persp_cycles.py`); a CPU cycle costs 6/8/12 of those
depending on the memory region — WRAM is always 8 (hardware-reference:
`scenarios/knowledge.md`, trap bank). Everything your loop does must fit
inside one frame, or motion quantizes to 30 Hz. Measured spans, all
emulator-measured and test-guarded:

| Work (per frame) | Measured | Receipt |
|---|---|---|
| Mode 7 tick, angle held (origin-only path) | ~3,640 mc ≈ 1% | `tests/test_mode7_chamber_cycles.py` |
| Full per-scanline Mode 7 rebuild, 224 lines interp1 | 492,436 mc = 138% | `tests/test_persp_cycles.py` (rerun: same) |
| Same solve at the shipped interp4 | 307,832 mc = 86% | same test's `<100%` gate |
| Cheapest genuine *second* live solve (112-line band) | 185,028 mc = 52% | same test — live-B cannot fit |
| Split-rail sprite projection, per sprite per band | visible 5,595 mc · behind-camera 2,003 · pre-culled 606 | `docs/guides/split_h.md` (Mesen2-measured; naive core was 8,522/6,965 — cull order is the budget) |
| One AI follower | 6,074 mc | `docs/guides/split_h.md` |

The two-player sprite rail's ship default is N=24 sprites at 58% of a frame
(31% headroom); 32 costs 75%, and 48 (103%) is where the loop stops closing
every frame — the committed N-curve and its lockstep gates are in
`docs/guides/split_h.md` and `tests/test_split_h_2p_demo.py`.

**Sprites per scanline.** 128 OAM entries exist, but each scanline the PPU
ranges only 32 OBJs and fetches at most **34 8-pixel slivers**
(hardware-reference: `scenarios/knowledge.md` K4/KF2). The kit measured the
sliver wall forensically: ~30 32x32 sprites packed on one row render exactly
~8 full sprites (34 ÷ 4 slivers each), and the pileup eats sprites up to 16
rows away — an OBJ's *box* consumes slivers across its full height even where
transparent (`tests/test_split_h_2p_demo.py::test_sp_overflow_row_forensics`,
`docs/guides/split_h.md`). And X=$100 does not hide a sprite from the range
limit — hide via Y (hardware-reference: trap T-5).

**Memory ceilings.** VRAM 64 KB shared by every CHR + tilemap, and word
addresses are 15-bit — pointing BG3 CHR at "$A000" silently wraps onto $2000,
a real kit bug (`lib/macros/sf_split_v.inc`). CGRAM 512 B (256 colors), OAM
544 B (the sprite rail commits it as one GP-DMA per VBlank). A Mode 7 map+CHR
alone owns words $0000-$3FFF (hardware-reference sizes:
`scenarios/knowledge.md` KF2/KF6; layouts: the templates).

**The DMA-per-VBlank window.** DMA moves 8 master clocks per byte, FastROM
irrelevant (hardware-reference: trap T-1). Only ~37 of the 262 lines are
blanking ≈ 50k mc — barely 6 KB of transfer *if DMA ran wall-to-wall*, and
the NMI also spends the window (auto-joypad alone ~4,224 mc —
`engine/nmi_handler.asm`). The kit hit the wall exactly there: three 2 KB
tilemap DMAs overrun VBlank and the third truncates at a nondeterministic row
(`lib/macros/sf_split_v.inc`, `docs/guides/split_v.md`). Big uploads go under
forced blank; per-frame streaming moves only the leading edge — that is why
the streaming rails exist.

## See it live

```bash
python -m pytest tests/test_persp_cycles.py -q     # 4 passed — the budget gates
PYTHONPATH=. python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
WR = MemoryType.SnesWorkRam
FRAME_MC = 1364 * 262            # master clocks in one NTSC frame
r = MesenRunner()
for tag in ("full", "i4full"):   # ROMs the pytest run just built
    r.load_rom(f"build/persp_cycles_{tag}.sfc", run_seconds=3.0)
    ticks  = r.read_u32(WR, 0xE030)   # completed solve iterations
    frames = r.read_u32(WR, 0xE034)   # NMI frames in the same window
    mc = frames * FRAME_MC / ticks
    print(f"{tag}: {mc:,.0f} mc/solve = {100*mc/FRAME_MC:.0f}% of a frame")
r.stop()
EOF
```

Observed: `full: 492,436 mc/solve = 138% of a frame` and `i4full: 307,832
mc/solve = 86% of a frame` — the table's numbers, reproduced on your machine
by the free-running instrument (a solve loop ticking one counter while the
NMI ticks another; the ratio is the cost; HDMA off, screen dark). The
instrument's wall-clock window can wobble the last tick (~±1%) on a loaded
machine — a stable rerun lands on these exact figures.

## Exercise

The same instrument, third ROM: measure the *cheapest possible second live
camera* yourself. Extend the snippet's loop with `"band2i4"` (a 112-line,
quarter-resolution solve) and rerun. Expected: ~52% of a frame (measured:
`185,028 mc = 52%`) — which, added to the 86% the first camera already costs,
is why the two-player rail streams precomputed pose tables instead of solving
live (`docs/guides/split_h.md`, "the budget lesson, applied").

## What breaks if…

- **…you estimate instead of measuring.** The kit swapped a 16x16 software
  multiply for the 8x8 hardware unit and projected ~3x; it measured **1.52x**
  — in slow ROM every opcode fetch is 8 mc, so the LUT/OAM tail dominated
  (`docs/guides/split_h.md`). Estimates flatter you; the emulator doesn't.
- **…you treat the frame heartbeat as a budget gate.** The NMI counter
  advances at 60 Hz *even while your loop overruns* — display and CPU are
  decoupled. An overrun shows up as game state advancing +1 per **two**
  frames: silky screen, 30 Hz gameplay. Gate loop-counter and NMI-counter
  lockstep, the way `tests/test_split_h_2p_demo.py` does.
- **…you park a crowd on one row.** Eight full 32x32 sprites render; the rest
  vanish — and so do innocent sprites within 16 rows. Design formations
  around the sliver math or budget flicker.
- **…you queue "just" 6 KB of DMA in one VBlank.** The tail transfers
  mid-render or truncates; the corruption row moves run to run. Forced blank
  for bulk, streaming for the rest.
- **…your loop creeps past 100%.** Nothing crashes. The game simply halves
  its rate — the most polite catastrophic failure on the platform, and the
  reason every cost above has a regression gate.

Next: [L10 — ship it](L10_ship_it.md).
