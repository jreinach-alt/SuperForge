# 11 — Art pipeline: Blender prerenders → SNES assets

> DRAFT SPEC, owner direction of 2026-11-16: art is **modelled in Blender and
> prerendered**, using the pipeline Fable built and shipped for SUPERFORGE GT
> (the `jreinach-alt/sf-gt` repo, read at `82add51`).
>
> **This file adopts that pipeline rather than inventing one.** Citations of
> the form `sf-gt:path` are to that repo, and its contract is
> `sf-gt:docs/fgt/art_bible.md`. Its code is first-party, from the same owner
> under the same zlib licence. Ported files keep a header line naming their
> sf-gt origin and commit, so the provenance trail survives the copy.

## 1. What sf-gt proves (and what Dungeons inherits)

| proven in sf-gt | evidence | Dungeons use |
|---|---|---|
| The build never runs Blender. Rendered, **indexed PNGs are checked in** and are the converters' input | `art_bible.md` §0 | same rule: a bare clone builds with no Blender |
| Models are **built by script**, not hand-modelled: 8 cars from a parts kit | `art/fgt/cars/car_models.py` + `carlib.py` | heroes, enemies, props and tiles built by script from a dungeon kit (§3) |
| Blender renders **data, not colour**: R = sunlight, G = material id, B = ambient occlusion, supersampled | `art/fgt/cars/pixelate.py` header | the same three-channel data pass |
| **No colour matching anywhere.** Per sprite pixel: material vote, then a brightness step on that material's ramp. Small features get heavier votes so they survive at low resolution | `pixelate.py` steps 1–2 | the same, with vote tables per sprite size |
| **Fixed palette role layout.** Index *n* means the same thing in every frame, so one palette swap repaints a model | `art_bible.md` §2 (the car's 16-entry role table) | P1/P2 heroes, elite enemies and biome swaps are all palette swaps |
| Cleanup and outline happen **after** the downscale, in Python. Tiny sprites get the shadow but no outline ring | `pixelate.py` steps 3–4 | the same rule for 8×8 drops and shots |
| A pixel outside the box is an **error, never a silent crop** | `pixelate.py` step 5 | same |
| **A fixed anchor** (ground point) per size, published as data and read by the engine | `anchors.json`, `FGT_CAR_T<t>_ANCHOR_*` | the foot point anchors the 10×6 foot box (05 §1) |
| Streaming one frame per VBlank from ROM into fixed VRAM slots: 1.3 MB of car frames through 16 KB | `sf-gt:README.md` | **precedent for `obj_stream`** (02 §1.2), which drops from "New" to "Near" |
| A staged `build_all.sh`: render → pixelate → sheets → convert → `--check` | `art/fgt/cars/build_all.sh` | `art/dungeons/build_all.sh`, same stages |

### 1.1 The operational lessons sf-gt paid for (`sf-gt:docs/fgt/dx_paper_cuts_cars.md`)

- **Use Cycles with direct light only.** That means a point sun at 2 samples
  with zero bounces, and the sky term taken from the AO pass. Path tracing ran
  at 16 s a frame on a loaded box; this setup runs at about 1 s, and **the
  shading is repeatable instead of noisy, which is better for pixel art.**
- **The material id must survive the compositor bit-exactly.** Use view
  transform **Raw**, 8-bit PNG, and `dither_intensity = 0`. The default
  dither adds noise to the ids.
- **Do not hash Blender's PNGs for determinism.** They carry render-time
  metadata. Hash the derived indexed PNGs instead.
- **Render scratch goes under `build/`.** A 2.4 MB log in an ignored scratch
  directory once tripped the cleanroom gate's file-size check.
- **Blender 4.2 API notes:**
  - `use_auto_smooth` is gone; use `set_sharp_from_angle`.
  - Booleans need `material_mode = 'TRANSFER'`.
  - `modifier_apply` works headless inside `temp_override`.
- **The anchor table:** a single "anchor = box bottom − 4" rule could not hold
  once the camera tilt was real. **Measure the anchor from the renders and
  publish it as data**, never as a formula in prose.
- **Toolchain:** Blender 4.2 LTS at `~/toolchains/blender/blender`, run
  headless as `blender -b --factory-startup -P script.py -- args`. It is not
  installed in this container, so the first track-A1 session installs it.

## 2. What is new for Dungeons (sf-gt does not cover it)

| need | why it is new | approach |
|---|---|---|
| **Skinned, animated characters** | sf-gt's cars are rigid bodies on a turntable | a script-built low-poly body with a simple armature: hips, spine, head, 2 × (upper arm, forearm), 2 × (thigh, shin), cloak bones. Walk, roll, swing, hurt and downed are **keyed in script** as actions, and the sprite frames are those actions rendered |
| **Top-down 3/4 camera, 3 directions** | cars use 33 yaw angles around a chase camera | orthographic, **35° depression**, yaw at 0° / 90° / 180° (right, up, down). Left is an HFLIP, so the model and its light must be left-right symmetric, the same constraint sf-gt states |
| **Tiles (BG), not sprites** | sf-gt's floor is Mode 7 data plus a sky band | metatiles rendered from the same 35° camera on a 16-px grid (§4) |
| **Set-piece rooms** (10 §2) | — | one 256×256 render per template, cut into metatiles by the converter |
| **Weapons as their own layer** | — | the swing is a separate render layer of the same action, so the weapon sprite is independent of the body (05 §1.1) |

## 3. The dungeon kit (script-built models, the `carlib` pattern)

`art/dungeons/kit.py` provides parametric parts, and `art/dungeons/models.py`
composes them into one function per model. This is the sf-gt `car_models.py`
pattern.

| model | parts (all low-poly, flat-shaded, bevelled 1 step) |
|---|---|
| wanderer (both heroes) | hooded cloak (a cloth-like mesh skinned to cloak bones), satchel, lantern hook, boots |
| Rootling / Thornspitter / Cairnback / Mothwick (10 §5) | root-tube sweeps; a bulb + petals; a stacked-stone mound; a moth body + flame wings |
| the Hollow Crown (boss, BG2) | an antler crown over an empty void-material core, with orbiting debris |
| props and tiles | wall blocks with a lit top bevel, root walls, braziers, chests, gates, stairs, chasm lips |

## 4. Palette role layouts (the contract the art and the engine share)

**Hero (OBJ palettes 0 and 1: one CHR, two palettes)**

| index | role |
|---|---|
| 0 | transparent |
| 1–5 | **cloak ramp**, dark → light. This is what differs between P1 (dusk blue) and P2 (amber) |
| 6–7 | trim (silver for P1, copper for P2) |
| 8–9 | skin, shadow and lit |
| 10–11 | leather, dark and light |
| 12 | lantern glow |
| 13 | metal highlight |
| 14 | eye / detail dark |
| 15 | outline and drop shadow |

**Enemies (OBJ palettes 4–6).** The same shape of table: 1–5 is the body
ramp, 6–8 is the secondary ramp, 12 is the "glow" (the ember eye, the candle
wing), and 15 is the outline. An **elite** is a palette swap on 1–5 with a
gold 12.

**Biome BG (palettes 2–6).** These go per material family:

- floor ramp (5)
- wall ramp (5)
- top-bevel light (2)
- the biome glow (2)
- transparent

That matches 10 §2's "glow hue on lit edges".

**Swing layer.** A weapon material maps into the hero palette's 10–13, so
swings need no palette of their own.

## 5. Stages (`art/dungeons/build_all.sh`, the sf-gt stage shape)

1. `gen_palettes.py` → `palettes.json`: role ramps per hero, enemy and biome,
   in BGR555.
2. `render_actor.py` (Blender) → `build/dgn_art_work/`: supersampled
   data frames (R sun, G material, B AO) for every action × direction.
3. `pixelate.py` → `art/dungeons/frames/<model>_<action>_<dir>.png`, indexed.
   Material vote, ramp step, cleanup, outline, fit check. The vote tables
   come from sf-gt's, tuned for 16 px.
4. `render_tiles.py` (Blender) + `pixelate_tiles.py` →
   `art/dungeons/tiles/<biome>.png`, an indexed atlas 16 metatiles wide.
5. `sheets.py` → `anchors.json` (the foot point per model and size, measured
   from the renders), the contact sheets, and a "lineup" of both heroes and
   every enemy on each biome floor.
6. `tools/gen_dungeons_assets.py` (the converter, in the build) →
   `build/dungeons/`:
   - hero and swing frame blobs in DMA order (`obj_stream`)
   - resident enemy CHR (deduped)
   - the `tiles16` quad-layout BG CHR (N, N+1, N+16, N+17), deduped, with
     mirrors folded into flip bits
   - palettes
   - a `.inc` of counts, offsets and anchors, never addresses

   It **refuses** a pixel outside its role table, a frame off its anchor, or
   a frame that touches no pixel. This is the `cars_convert.py` contract.

## 6. Tests (they read the ROM, per the house rules)

- **The CHR round trip.** For 5 metatiles and 3 hero frames, VRAM tiles
  decoded with the live CGRAM equal the indexed PNG pixels.
- **The streamed slot.** After a known input sequence, the hero's VRAM slot
  equals the frame blob entry for the expected action, direction and frame
  (08 M3).
- **The palette swap.** CGRAM OBJ palettes 0 and 1 differ only in entries
  1–7, and those equal `palettes.json`'s P1 and P2 ramps.
- **The anchor.** A hero at a known world position has its OAM x/y equal to
  world − camera − anchor, from `anchors.json`.
- **Readability (judged).** Each milestone report carries the lineup sheet
  rendered **from the built ROM** (a screenshot), not from the PNGs.

## 7. Porting plan (track A1/A2 in 08)

1. Port `pixelate.py`'s vote → step → cleanup → outline → fit core and
   `build_all.sh`'s stage runner. Keep their structure and their refusal
   messages.
2. Write the new parts: the armature rig, the 35° camera rig, the
   action-keyed renders, the tile renders.
3. Start with the wanderer's walk cycle in one direction, all the way through
   to a screenshot of it walking in the M3 ROM. That is the vertical slice.
   Only then build the full roster.
