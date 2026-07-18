# Pseudo-3D rail shooter on the Mode 7 floor (`templates/railshooter/`)

The genre rail for a forward / on-rails shooter where the ground rushes toward
the viewer, hazards approach out of the horizon and grow, and you strafe + fire.
Build with `make railshooter`, verify with `tests/test_railshooter.py`. The
scaffolding is `lib/macros/sf_rail.inc`; this guide is the *why* + the *don't*.

It shares the racer's Mode 7 spine ([`mode7_racer.md`](mode7_racer.md) — the
perspective trapezoid, the CH2 sky split, OBJ-over-Mode-7) but adds the one
mechanic that *makes* it a rail shooter: **approaching depth actors that scale
through pre-drawn size tiers** — and it places them with a projection that is
deliberately NOT the Mode 7 matrix. That decision is the heart of this page.

Confidence tiers (per AGENTS.md): **kit-verified** — implemented in this kit and
checked on the emulator (the railshooter ROM + `tests/test_railshooter.py`);
**genre-canon** — the documented technique of the shipping forward-shooter era,
cross-referenced below. Constants are **derive per project** unless noted.

---

## 1. The model: a decoupled pinhole (1/z), NOT a Mode 7 matrix inverse

A depth actor carries one scalar — its forward depth **z**, in world pixels
ahead of the camera. The projection is the textbook pinhole camera:

```
screen_y(z) = clamp( HORIZON_Y + CAM_H*256 / z , HORIZON_Y, 223 )
scale(z)    = FOCAL*256 / z                       (.8 fixed perspective factor)
screen_x    = 128 + ((lane_x - cam_x) * scale) >> 8
size_tier   = 0..3 by z thresholds (nearer = bigger)
```

`z` decrements per frame as the actor approaches; when it reaches the camera you
recycle it to a far z. `screen_y` is **monotone in z**, so the sprite walks
smoothly down the screen from the horizon to the bottom over dozens of frames.

This is the canon of the pseudo-3D racing/forward-shooter literature — Jake
Gordon's "How to build a racing game" (`jakesgordon.com/writing/...`,
`Util.project`: project a world point by `1/z`, render segments back-to-front,
`Util.increase` to advance + recycle the road) and Lou's Pseudo-3D page
(`extentofthejam.com/pseudo`: `scale = 1/z`, the per-line scale cache).
**(genre-canon)**

**The kit bakes the curve into a LUT.** `templates/railshooter/assets/make_project_lut.py`
emits `mode7_project.inc` — a z-bucketed table of `(scanline_byte, scale_word)`
computed by pure pinhole arithmetic (no emulator, no ROM read-back), and it
**asserts screen_y is monotone in z** before writing, so a bad constant edit
fails loudly. `engine/mode7_project.asm` consumes it: in `PROJ_DEPTH` (z),
`PROJ_OBJ_X` (lane_x), `PROJ_CAM_X`; out `PROJ_SX/SY/TIER/CULLED`. The kit's
general Mode 7 LUT generator `toolchain/mode7_lut.py` bakes the same shape for
the *floor* (`scanline = horizon + height*256/D`). **(kit-verified.)**

### Which projection constants live where (mirrored vs LUT-only vs imported)

The pinhole tuning constants split three ways. Know which is which before you
tune — the cold-start trap is editing a LUT-only constant in `main.asm` (no
effect) or a mirrored one in only one place (silent drift):

| Constant(s) | Lives in | Sync burden |
|---|---|---|
| `Z_NEAR` | **Mirrored** — declared in BOTH `main.asm` and `make_project_lut.py` | **By hand.** The LUT bakes the z range with it; `main.asm` clamps/recycles z against it. Keep the two literals equal — nothing checks this for you. |
| `CAM_H`, `FOCAL`, `HORIZON_Y` | **LUT-only** — `make_project_lut.py` | None for `main.asm`. They shape the baked `(scanline, scale)` curve and never appear in the runtime; editing them in `main.asm` would do nothing. Regenerate `mode7_project.inc` after a change. |
| `PROJ_DMAX`, `PROJ_TIER_T0..T2`, `PROJ_Q` | **Imported** — generated `mode7_project.inc`, `.include`d by `main.asm` | None — single source of truth. `main.asm` reads these equates; they're emitted by the generator, so a tier-threshold or far-edge change propagates automatically on regen. |

So: edit a tier threshold or the far edge? Change `make_project_lut.py`,
regenerate, done (imported). Change the camera height / focal / horizon? LUT-only
— regenerate. Change `Z_NEAR`? It's the **one** value you must edit in two files.

### DEAD-END: don't derive the projection from the Mode 7 affine matrix

The obvious-looking idea is to place an actor by inverting the Mode 7 transform
(read the per-scanline A/B/C/D the renderer built, solve for the screen pixel of
a world point on the floor). That world→screen inversion is real and documented
([`mode7_sprite_projection.md`](mode7_sprite_projection.md)) — use it when you
genuinely want a sprite *welded to a floor texel* (an AI kart on a racetrack).

But it is **the wrong tool for an approaching hazard**, and here is the trap that
burned four rounds of this work: the Mode 7 floor has only **~14 world-pixels of
true forward depth** between the horizon scanline and the bottom of the screen
(measured: the matrix's vertical coefficient `A_V` dwarfs the depth coefficient
`D_V`). Anchor an obstacle to the matrix and its entire approach is a 2-3 frame
*snap* across those 14 px — there is no room for the multi-frame descent a rail
shooter needs. The pinhole z axis is **arbitrary** (Z_NEAR..Z_FAR, e.g. 16..640),
so the same obstacle descends over ~50 frames. **Decouple the actors from the
matrix; let the Mode 7 grid be pure backdrop.** That is exactly how the shipping
forward shooters did it — the floor is Mode 7, the *objects* are independently
projected OAM sprites. **(kit-verified the 14px floor; genre-canon the split.)**

---

## 2. Pre-drawn size tiers (the SNES has no sprite scaling)

The SNES PPU **cannot scale sprites** — OBSEL exposes only two fixed sizes at
once, and the affine transform applies to the BG plane only, never to OBJ. So an
object that "grows as it approaches" is faked by **swapping between pre-drawn
discrete size frames by distance**. The visible *stepping* between sizes is the
genre's hallmark — the same trick in the era's kart racers and forward shooters.
**(genre-canon: SNESdev wiki "Mode 7", Wikipedia "Mode 7" on pre-drawn sizes;
contrast the contemporaneous arcade super-scaler boards, which had true
hardware sprite *zoom* in silicon — the SNES lacked that and faked it with
discrete cels, which is why the size stepping is visible.)**

The kit ships **4 tiers**, selected by z thresholds in the projection LUT
(`PROJ_TIER_T0/T1/T2`), with two pre-drawn art frames per OAM size:

| Tier | z band | OAM size | art |
|---|---|---|---|
| 0 | nearest | 32×32 large | full detail |
| 1 |  | 32×32 large | medium |
| 2 |  | 16×16 small | full |
| 3 | farthest | 16×16 small | tiny |

### Hysteresis stops tier flicker

A naive "tier = f(z) each frame" flickers when z sits on a threshold (two tiers
alternate frame to frame). The fix is **grow-only hysteresis** (the Phase 12-6
size-grade technique): the stored tier only advances when z falls a margin
*below* the next threshold, and never shrinks during the monotone approach (it
resets on recycle). The railshooter's `obs_tier_hysteresis` is the worked
example; `sf_rail_draw_sorted` orders + selects art by the *stored* (hysteresis)
tier, not the raw projected one. **(kit-verified.)**

---

## 3. Depth ordering = OAM index (the tier-bucket sorted draw)

On the SNES, sprite priority among same-priority OBJ is the **OAM slot index**:
lower index draws in front. For correct back-to-front layering of depth actors,
the era technique is to **recompute the OAM slot order from depth every frame**,
decoupled from the actor's pool-slot identity — so death/respawn order never
matters. (Jake Gordon's segment renderer paints back-to-front for the same
reason. **genre-canon.**)

The cheapest correct form needs **no sort and no comparisons**: bucket by the
size tier you already computed. `sf_rail_draw_sorted` (engine
`rail_draw.asm`) does exactly this:

1. Project every live actor once; cache `(sx, sy, tier, vis)` per pool slot.
2. Walk tier 0 → 3; in each pass emit the matching live+visible actors via the
   engine `spr` path (call order = ascending OAM slot). Tier 0 (nearest) lands
   in the lowest slots → drawn in front; tier 3 in the highest.
3. Park the unused slots off-screen (`y=$F0`) so the OAM window is exactly
   `count` deterministic slots.

Net cost: `count` `engine_spr` calls + one projection per actor, no sort.
**(kit-verified: `tests/test_railshooter.py::test_railshooter_obstacles_drawn_depth_sorted`
asserts on real OAM bytes that no far/small obstacle ever sits at a lower OAM
slot than a near/large one.)**

### DEAD-END: the fixed pool-slot → OAM-slot map (the recycle "pop")

The tempting simplification is "pool slot k always draws at OAM slot base+k"
(stable, easy to test). It is **wrong for depth**: it layers by pool identity,
not distance. When a near actor recycles to far and a farther actor keeps its
low slot, the far actor now draws *in front of* a nearer one, and the recycled
actor visibly *pops* its old depth order. Re-deriving the order from the
per-frame tier (above) removes both. A test that pins "slot k = pool k" will
pass while the layering is wrong — track an actor by its `lane_x`/`depth_z`
identity instead (the kit tests locate an obstacle in OAM by matching the
routine's projection cache, then assert on the matched entry's real bytes).

---

## 4. Lateral lanes

Spawn actors into a few discrete lateral lanes (`lane_x` offsets from the rail
centre) so they rarely share a screen column. The pinhole `screen_x` fans them
out across the screen as they near and converges them to centre at the horizon —
a readable "weave between the gaps" field, and overlap-priority is mostly moot
because columns rarely collide. The railshooter cycles 4 lanes
(`obs_lane_x: .word 512, 464, 560, 488` around camera 512). **(kit-verified.)**

---

## 5. Waves (a pacing lever)

Table-driven spawning at discrete depths/frames is the pacing + count-cap knob,
and it further reduces cross-depth overlap (you control how many actors share a
depth band). `sf_rail_wave` documents the interface (a ROM wave table of
`{trigger, count, lane_pattern, kind}` + a cursor) but is **SCAFFOLDED, not yet
shipped** — the railshooter uses the simpler proven path (seed N actors
staggered across the depth range + recycle on pass). Adopt `sf_rail_wave` only
with your own run-gate; see its header in `sf_rail.inc`.

---

## 6. Cycle-cost notes

- **Projection per actor:** one `mode7_project` call = a LUT bucket lookup
  (`z >> PROJ_Q_LOG2`), a byte-table read for `screen_y`, a word-table read for
  `scale`, one signed 16×16 multiply (`smul16`) for the lateral offset, and an
  add. Tens of cycles; cheap for a pool of 4-12 actors.
- **The LUT is the win:** no per-frame divide. `screen_y` and `scale` are baked;
  the runtime does shifts + a multiply, never a divide. (The Mode 7 *floor* HDMA
  rebuild is the expensive part of the frame, ~10k cycles — and it only runs when
  the camera angle/perspective changes; see [`mode7_racer.md`](mode7_racer.md).)
- **The sorted draw is sort-free:** 4 tier passes over N actors = O(4N) cache
  reads + N `engine_spr` calls. No comparisons, no swaps.
- Keep the pool small (the railshooter uses 6 obstacles + 4 bullets). The OAM is
  128 slots shared with the player + HUD + reticle; budget the windows.

---

## 7. How to build one

1. **Start from the rail.** Copy `templates/railshooter/` (the worked example:
   rail camera, strafe + bank, the obstacle field, firing + reticle, the 4
   tiers). It is the reference; adapt it rather than starting from zero.
2. **Include the scaffolding.** `.include "sf_rail.inc"` (alongside `sf_pool.inc`,
   `sf_sprite.inc`, `sf_mode7.inc`), and `.include "rail_draw.asm"` in the CODE
   segment after `mode7_project.asm` (the sf_mode7 link order).
3. **Lay out the depth-actor pool** (the convention in `sf_rail.inc`'s header):
   `ALIVE[N]`, `LANE_X[N]`, `DEPTH_Z[N]`, `TIER[N]` parallel word arrays in the
   `$1800-$1DFF` game-array region, plus a projection-cache scratch span
   (`N*4` words) and an 8-word param block for the sorted draw.
4. **Bake the projection LUT.** Tune the pinhole constants in
   `make_project_lut.py` (`HORIZON_Y`, `CAM_H`, `FOCAL`, `Z_NEAR`, `Z_FAR`, the
   tier thresholds) to taste, regenerate `mode7_project.inc`. Keep the mirror
   constants in `main.asm` (`Z_NEAR`, etc.) in sync — they're cross-checked by
   eye, not the assembler.
5. **Define the per-tier descriptor table** in RODATA (`rail_tier_tbl`: 4 rows
   of `{tile, flags, center_off}`) mapping each tier to its OAM tile, attribute
   (size bit + palette), and half-width centre offset.
6. **Per frame:** advance each actor's `DEPTH_Z` (recycle on pass); apply your
   tier hysteresis into `TIER[]`; then `spr_clear`, draw the player at slot 0,
   fill the param block, and `sf_rail_draw_sorted` to emit the field depth-first.
7. **Optional:** a wave table (see §5, scaffolded), banking on strafe (tilt the
   Mode 7 `angle` a few units and ease back — the railshooter does this), a
   textured/scrolling sky band above the horizon (the racer uses a flat CGRAM
   backdrop via the CH2 TM-split).
8. **Verify on the emulator.** Assert on real OAM/screenshot bytes:
   screen_y descends monotonically over a full approach, the tile + size bit
   step through the tiers, lateral lanes project to the right side of centre,
   and the depth-sort holds (nearer = lower OAM slot). `tests/test_railshooter.py`
   is the template's gate and the pattern to copy.
   - **Floor screenshot tip:** when asserting on a screenshot floor/region, the
     region *mean* blends in detail-line / ravine colors, so don't assert on
     absolute brightness — assert on channel **ordering** (e.g. `r > g > b` for
     a warm floor). The ordering survives the blend; a brightness threshold
     doesn't.

---

## 8. Forking into a NEW named template (vs adapting in place)

§7 step 1 says "copy `templates/railshooter/` and adapt it" — that works when you
want to *edit the railshooter*. If instead you want a **separate, additionally-
named template** (`templates/<name>/`) that coexists with the railshooter, there
are four seams a fresh build hits. Here is the tight checklist; each item points
at the railshooter file that is the worked example.

1. **Copy the dir + the asset generators; rewrite the `.incbin` / `.include`
   asset paths.** `cp -r templates/railshooter templates/<name>`, then in
   `templates/<name>/main.asm` repoint every asset include to the new dir's
   `assets/` (the railshooter `.include`s `assets/mode7_project.inc`,
   `assets/obstacles.inc`, `assets/vehicle.inc`, `assets/ground_palette.inc`,
   and `.incbin`s the ground map blob — see `main.asm` §902-915 and the Makefile
   prerequisite `templates/railshooter/assets/ground_map.bin`). Copy the asset
   generators too (`make_ground.py`, `make_obstacles.py`, `make_project_lut.py`)
   and re-run them into `templates/<name>/assets/` so the blobs are yours, not
   shared. Auto-discovery (`make <name>`, `make all`) picks the new dir up with
   no Makefile edit — *for the link step only* (see next).

2. **Add an explicit `LDCFG_64K` rule to the Makefile.** This is the documented
   non-default-link-shape exception (Makefile header, "EXCEPTION — non-default
   link shapes: the generic rule links `lorom.cfg`…"): the generic auto-discovery
   pattern links the 32KB `lorom.cfg`, but a Mode 7 floor needs the 32KB
   interleaved map blob in BANK1, so the image must be 64KB linked with
   `lorom_64k.cfg`. Copy the railshooter's explicit rule verbatim and rename it —
   the `build/railshooter.sfc` target (Makefile §106-110) is the template:
   ```make
   build/<name>.sfc: templates/<name>/main.asm templates/<name>/assets/ground_map.bin $(ENGINE_DEPS)
   	$(CA65) $(INCLUDES) $< -o build/<name>.o
   	$(LD65) -C $(LDCFG_64K) build/<name>.o -o $@
   ```
   The explicit rule wins over the generic template pattern. Without it the ROM
   builds (auto-discovery) but at the wrong size/shape and the map blob has
   nowhere to land — a silent run-gate failure, not a build error.

3. **Add `templates/<name>/oracle.json`.** It is auto-discovered next to the ROM
   and schema-validated by `tests/test_oracles.py` (the manifest discovery walks
   for `oracle.json` siblings, loads + schema-checks each — the anti-indirect-
   evidence gate). Copy `templates/railshooter/oracle.json`, set
   `"template"`/`"rom"` to your name, and rewrite the `scenario[]` asserts to your
   sprites (OAM slots/tiles) and floor region. It declares the boot magic +
   heartbeat addresses and the real OAM/screenshot assertions — keep them reading
   *output regions*, not proxy variables.

4. **Add `tests/test_<name>.py`.** Copy `tests/test_railshooter.py` as the
   pattern: a module-scoped `MesenRunner` fixture, input-injection scenarios, and
   assertions on real OAM bytes + screenshot pixels (channel ordering per §7.8).
   The oracle.json covers the schema-driven boot/render asserts; the Python test
   is for the input-driven scenarios (strafe, bank, fire) the oracle can't drive.

---

## See also

- [`mode7_racer.md`](mode7_racer.md) — the shared Mode 7 spine: perspective
  trapezoid params, the sky TM-split, OBJ-over-Mode-7, the camera integration.
- [`mode7_sprite_projection.md`](mode7_sprite_projection.md) — the OTHER
  projection: world→screen via the Mode 7 *matrix inverse*, for sprites welded
  to a floor texel (an AI racer on a track). The contrast with §1 here is the
  whole point: matrix-inverse for *floor-anchored* objects, decoupled pinhole for
  *approaching depth* objects.
- `lib/macros/sf_rail.inc` — the scaffolding (record convention, `sf_rail_project`,
  `sf_rail_draw_sorted`, the scaffolded `sf_rail_wave`).
- `lib/macros/sf_pool.inc` — the actor pool a depth actor is built on;
  `lib/macros/sf_enemy.inc` — its 2D-platformer sibling (patrol + stomp).
- `engine/mode7_project.asm` + `engine/rail_draw.asm` — the projection routine +
  the depth-sorted emit; `templates/railshooter/assets/make_project_lut.py` —
  the LUT generator.
