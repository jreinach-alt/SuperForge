# The Mode 7 "barrel chamber" effect (`templates/mode7_chamber/`)

A reusable **effect capability**: a **rolling**, **barrel-curved** Mode 7 floor
under a **Mode 1 HUD band**, with a **brightness vignette** — the four
cooperating per-scanline HDMA writes a debugger teardown + save-state extraction
resolved (the Mode 7 barrel-chamber recreation spec under `docs/sprints/`).
Build with `make mode7_chamber`, verify with `tests/test_mode7_chamber.py`.

**CLEAN-ROOM:** the stone art is original placeholder art
(`assets/make_chamber.py`); only the Mode 7 effect **technique** is recreated,
never any commercial-game content. The register **values** (the barrel M7A
table, the COLDATA vignette table, the BGMODE/TM split bytes) are factual
hardware configuration.

## The effect in four layers

The chamber composes four per-scanline writes over the engine's Mode 7
**perspective floor** (the racer/flight path, CH5/CH6 matrix HDMA):

1. **Vertical ROLL — NO rotation** (owner-corrected motion model; see the spec
   addendum v1.1 / v1.3). The angle is held **constant**; instead `posy` scrolls
   the floor texture, so the apparent rotation is that vertical roll through the
   static barrel — the "popsicle stick in a PVC pipe" motion — not an affine
   matrix. The roll runs in **legs**, each one direction and made of `NUM_HUMPS`
   (3) **surges**: the speed rises smoothly to a randomised peak (hard-capped at
   `PEAK_CAP`, ~half the former max), touches it momentarily, then drops **quickly**
   (`DECEL` > `ACCEL`) toward a slow creep — speed up / slow down, 3 times. After
   the surges the leg stops dead, holds ~0.5 s, then **reverses**. Forward and
   reverse legs draw surge peaks from **separate LFSR streams** (`RNG_F`/`RNG_R`),
   so each direction has its own variance pattern. `posy` is a 16.8 accumulator
   advanced by the signed velocity each frame and wrapped to the 1024px periodic
   map (M7SEL set to **wrap**, `sf_mode7_flags #$00`), so the roll is seamless.
   Because the angle never changes, `sf_mode7_cam` only sets `M7_DIRTY_ORIGIN`
   (the cheap M7X/M7Y re-anchor), so the heavy perspective rebuild runs just
   **once** (forced at init) — *cheaper* than a spin. Tunables: `ACCEL`/`DECEL`
   (rise/fall feel), `PEAK_MIN`/`PEAK_RNGMASK`/`PEAK_CAP` (surge speed + cap),
   `NUM_HUMPS` (surges per leg), `HOLD_FRAMES` (the pause).
2. **Per-scanline M7A barrel** (`sf_mode7_barrel`). The engine computes M7A
   inline (a perspective trapezoid); the **G1 hook** lets you inject an
   arbitrary per-scanline M7A curve **without forking** `pv_rebuild`. A smooth
   **raised-cosine** `$0100 -> $0180 -> $0100` bow (1.0 flat at the floor edges,
   1.5 bulge mid — zero slope at the peak, so no mid-screen corner) bows the
   floor into a **barrel**. The barrel is stamped once into the active AB buffer
   and persists (the buffer never flips while the angle is constant).
3. **Dual-register mode-split** (`sf_mode7_modesplit`). Two direct HDMA channels
   switch **BOTH** `$2105` (BGMODE) **AND** `$212C` (TM) at a configurable
   scanline, so a clean **Mode 1 HUD band** renders above the Mode 7 floor. The
   captured chamber uses BGMODE `$09 -> $07` and TM `$14 -> $17` at line 32; the
   band bytes and the split line are all macro parameters (G2/G3). This is the
   dual-register generalisation of the racer's single-register `arm_sky_split`.
4. **COLDATA vignette** (`sf_mode7_vignette`). One direct HDMA channel ramps the
   `$2132` fixed colour `0 -> 8 -> 0` (`$E0..$E8..$E0`) down the frame, brightest
   through the middle. Visible **only** with additive colour math on
   (`sf_colormath_on #1, #$21` + `sf_colormath_tint #0,#0,#0`) — the captured
   effect's documented dependency.

## The HDMA channel allocation (G4 — no collision)

The mode-split + vignette channels are programmed **directly** (`$43xx` + an OR
into `NMI_HDMA_ENABLE`), exactly like the racer's `arm_sky_split`. They are
**not** added to `M7_OWNED_MASK`, so the engine NMI's Mode-7 ownership gate
passes them through untouched — there is **no contention** with the CH5/CH6
matrix HDMA (unlike the old `engine_mode7_hud` CH3 raw-override, which collided
with the gradient). Each effect gets an explicit, distinct channel:

| CH | Role | Armed by |
|----|------|----------|
| 0,1 | reserved (VBlank bulk DMA) | `hdma_alloc_init` |
| **2** | BGMODE `$2105` split | `sf_mode7_modesplit` (`CH_BGM`) |
| **3** | TM `$212C` split | `sf_mode7_modesplit` (`CH_TM`) |
| **4** | COLDATA `$2132` vignette | `sf_mode7_vignette` (`CH_COL`) |
| **5,6** | Mode 7 matrix AB/CD (M7A barrel in the A column) | `mode7_init` |
| 7 | free | — |

Verified on the emulator: `NMI_HDMA_ENABLE == $7C`, `M7_OWNED_MASK == $60` —
distinct channels, no double-claim (the `test_mode7_chamber.py` channel-config
assertion locks this in). This matches the captured allocation's **roles**
(BGMODE/TM/COLDATA/M7A on distinct channels); the kit pairs M7A with the matrix
CH5/CH6 (the engine's matrix HDMA is a CH5/CH6 pair, where the capture used CH5
alone for M7A) — the barrel override lives in that pair's A column.

## Arming the capability (the setup sequence)

After `sf_mode7_on` + `sf_mode7_perspective` (with `l0` = the split scanline)
+ a first `sf_mode7_tick`:

```ca65
sf_colormath_on #1, #$21              ; additive math (the vignette dependency)
sf_colormath_tint #0, #0, #0
sf_mode7_barrel chamber_barrel        ; G1: the M7A bow curve (u16/floor-scanline)
sf_mode7_modesplit #$09, #$07, #$10, #$11, #32, CH_BGM, CH_TM, BGM_TABLE, TM_TABLE
sf_mode7_vignette chamber_vignette, CH_COL, VIGN_TABLE, #CHAMBER_VIGNETTE_LEN
lda #$01                              ; force ONE rebuild so the barrel gets
sta M7_DIRTY_REBUILD                   ;   stamped into the active AB buffer
sf_mode7_tick                          ; full rebuild + barrel stamp
```

Then each frame: advance the **roll** state machine (accumulate the signed
velocity into `posy`, wrap to the map), set the camera (constant angle),
`sf_mode7_cam`, `sf_mode7_tick`. With the angle constant, `sf_mode7_cam` marks
only `M7_DIRTY_ORIGIN`, so `sf_mode7_tick` does **not** rebuild — the barrel
stamped at init persists (the double-buffer never flips).
That is why the init must **force** the one rebuild above (otherwise `pv_rebuild`
/ `mode7_barrel_apply` never run and the bow is never stamped). If you instead
animate the **angle**, the barrel re-stamps automatically every rebuild.

## The data tables (`assets/make_chamber_tables.py`)

- `chamber_barrel`: one u16 M7A word per **floor** scanline (index 0 = `l0`),
  a symmetric `$0100 -> $0180 -> $0100` **raised-cosine** bow (smooth peak — a
  triangle ramp would render a corner at screen-centre).
- `chamber_vignette`: the COLDATA HDMA table in raw direct-mode encoding
  (`[count, value]...  $00`), ramping `$E0..$E8..$E0`.

Both encode factual hardware register values — regenerate with the committed
generator; the exact intermediate words are not load-bearing (the **symmetric
bow** and the **0->8->0 ramp** are).

## Done-condition (output-reading test)

`tests/test_mode7_chamber.py` asserts on **rendered output**: (a) the floor
**rolls** (`posy` scrolls in legs of 3 surges capped at ~half the former max,
then a dead stop + reverse — sampled from the signed velocity mirror, with the
COLDATA ramp read from WRAM — and the floor re-paints; no rotation),
(b) it **bows** (the per-scanline M7A in the active AB HDMA buffer is a symmetric
barrel, peak mid-floor, ~1.0 at the edges), (c) a clean **Mode 1 HUD band** sits
above the textured Mode 7 floor (proved by a band-wide distinct-color check, since
the axis-aligned floor can have uniform single scanlines), (d) the **vignette**
(mid floor brighter than top/bottom). Plus the channel-config check above.

## Performance (measured, `tests/test_mode7_chamber_cycles.py`)

Per-frame CPU cost of the running chamber, measured on Mesen2 by the frame-budget
method (`mode7_chamber_cycles_test.asm`):

| Per-frame path | master clocks | % of an NTSC frame |
|---|---|---|
| **Chamber as built** (constant angle -> ORIGIN path: recompute M7X/M7Y) | ~3,640 | **~1.0 %** |
| If it rotated (per-frame `pv_rebuild`, full 192-line matrix at SH=1440/interp=1) | ~431,000 | **~121 %** |

The chamber is **~1 % of a frame** on the CPU — effectively free. That is the
whole point of rolling via `posy` with a **constant angle**: the per-scanline
matrix is built **once** at init, and each frame only re-anchors the M7X/M7Y
origin (cheap). A true per-frame rotation would rebuild the matrix and cost
**more than a whole frame** (it cannot hit 60 fps at this density) — so rotation
is the bottleneck we designed around, not a knob to turn on.

The remaining per-frame load is hardware, not the CPU loop: the **5 HDMA channels**
(BGMODE, TM, COLDATA, M7 A/B, M7 C/D) stream ~11 bytes/scanline over the floor
band during active display, and the NMI commits the shadows in VBlank. Both are
well within budget — the ROM runs at a hard 60 fps on the cycle-accurate emulator.
The real ceiling for *extending* this effect is HDMA channel/bandwidth budget (8
channels total) and, if you ever need motion that changes the matrix shape
(true rotation/zoom), the `pv_rebuild` cost above.
