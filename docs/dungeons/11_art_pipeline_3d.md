# 11 — Art pipeline: Blender prerenders → SNES assets

> DRAFT SPEC, owner direction of 2026-11-16: art is **modelled in Blender and
> prerendered**. That is the classic 16-bit prerendered-sprite technique: the
> models are 3D, and what the console draws is 2D pixel art rendered from
> them.
>
> **OPEN (09 Q8):** Fable already built a Blender → SuperForge intake in
> another project, and this spec has not seen it. That repo is not in the
> session (attaching it was refused). This file is therefore written as a
> **contract**: what the build needs, wherever it comes from. If Fable's
> existing tool meets it, use that tool; where they differ, this file says
> which side moves (§6).

## 1. Principle: the build never runs Blender

Blender is an **authoring** tool, not a build dependency. A bare clone has to
build and pass `make bare-check` on a box with no Blender on it.

| layer | committed? | who reads it |
|---|---|---|
| `.blend` scenes + the `bpy` render script (`tools/dungeons/render/*.py`) | yes, the sources. A large `.blend` goes in Git LFS, or in a sibling art repo pinned by hash | the artist / Fable, in Blender |
| **render outputs**: RGBA PNG sheets + a JSON manifest, under `vendor/art/dungeons/` (the existing `!vendor/art/**/*.png` un-ignore covers it) | **yes: the build's input** | `tools/gen_dungeons_assets.py` |
| CHR / palette / metasprite blobs | no (`build/`) | the allocator and ROM |

**The renders are deterministic.** The same `.blend`, script and Blender
version give the same pixels:

- fixed sampling seed
- no denoiser
- the Workbench or Eevee engine with fixed settings

`tools/dungeons/render/check_renders.py` re-renders on an artist's box and
diffs the result against the committed PNGs. It never runs in CI.

## 2. The camera contract (everything must agree with the game's projection)

The game is **top-down with a 3/4 tilt**. Walls show a face (03 §4.2). So:

- **Orthographic camera,** elevation **35°** from the horizontal, yaw locked
  to the 4 cardinal directions for characters (right/left by HFLIP, so
  render 3: right, up, down).
- **Scale:** 1 Blender unit = 16 px = one metatile. A hero is 1.4 units tall
  and must fit **16×16 px including the weapon-free silhouette**.
- **The foot point** (the root bone origin projected to screen) is written to
  the manifest per frame. The game anchors the 10×6 foot box (05 §1) to it,
  so an animation never "slides" against collision.
- **Light:** one key light from the upper left (matching the wall-face
  autotiling), a cool fill, and a **rim light**, so the silhouette survives
  quantisation.
- **Outline:** a 1-px dark outline added *after* downscale, by the intake
  rather than by Blender (§4 step 4). At 16 px, a rendered outline aliases
  into mush.

## 3. What gets rendered

| asset | render | sheet layout |
|---|---|---|
| hero (one model, palette-swapped ×2) | 3 directions × (idle 2, walk 4, roll 3, hurt 1, downed 1) at 64×64, downscaled ×4 → 16×16 | one PNG per animation, frames left to right |
| swings | each melee base: 3 directions × 3 frames, the weapon only (separate render layer) | same |
| enemies | side view only (left by HFLIP): walk 2, windup 1, attack 1, hurt 1 | same |
| the boss (BG2) | 3 poses at 256×256 → 64×64, **as BG tiles** | one PNG per pose |
| metatiles | each metatile kind rendered from the same 35° camera as a 16×16 cell; walls in their 8 autotile variants (03 §4.2) | one atlas per biome, a 16-cell-wide grid (the `tiles16` quad, §4 step 6) |
| set-piece rooms | one 256×256 render per set-piece template (10 §2) | sliced into metatiles by the intake |

## 4. The intake (`tools/gen_dungeons_assets.py`): seven steps, each refusing rather than guessing

1. **Load.** Read the manifest and PNGs, and check that every frame named in
   the manifest exists and is the declared size.
2. **Downscale.** A ×4 → ×1 box filter on premultiplied alpha. Alpha is then
   thresholded at 50% to 1-bit, because the SNES has no partial transparency.
3. **Quantise to a palette that is fitted to the picture.** Each sprite family
   (the hero, an enemy set, a biome's BG) gets **15 colours + transparent**,
   fitted by area-weighted k-means over every frame of the family, in
   **BGR555** space (the SNES colour space, so the fit sees the real
   rounding). The kit precedent for fitting the palette to what is on screen
   is `tools/fit_mill_palette.py`.
4. **Outline.** Any opaque pixel touching transparency gets the family's
   darkest entry, if a toggle in the manifest asks for it.
5. **Index and verify.**
   - **No silent masking.** Any pixel that cannot map to the fitted palette is
     an error naming the file and coordinate. The rule: encoders refuse,
     never mask, as `gen_hero_sprite.encode_4bpp` already does.
   - **Hero frames are fitted once**, so that P2 is the same CHR with a
     different palette. The intake emits both palettes: P2's is the P1 ramp
     hue-rotated in a manifest-declared way, and checked for contrast against
     each biome's floor.
6. **Pack.**
   - BG metatiles go into the `tiles16` quad layout (N, N+1, N+16, N+17),
     with metatile-level dedupe. Mirrored duplicates become flip bits.
   - Streamed hero and swing frames go into the ROM frame blob (02 §1.2):
     4 tiles each, in DMA order.
   - Enemy frames become resident CHR with tile dedupe.
   - Emit counts and offsets as a `.inc`. Never emit addresses.
7. **Report.** Write `build/dungeons/art_report.txt`:
   - per family: the colours used, the worst quantisation error, the tile
     count against budget (name table 256, BG CHR ≤ 512 tiles)
   - a contact sheet PNG of every frame as the SNES will draw it, built from
     the encoded CHR and palette rather than from the source. That makes the
     contact sheet itself a decode test.

## 5. Tests (M2/M3 grow these; they read the ROM)

- **The CHR round trip.** The tiles in VRAM after `floor::enter`, decoded with
  the CGRAM palette, equal the intake's contact-sheet pixels for 5 metatiles
  and 3 hero frames.
- **The streamed slot.** After a known input sequence, the hero's VRAM slot
  equals the frame blob entry for the expected animation frame (08 M3).
- **The P2 palette.** CGRAM OBJ palette 1 equals the intake's derived P2
  ramp, and the contrast check is asserted at build time.
- **Readability (judged, not asserted).** A screenshot of both heroes on each
  biome's floor goes in the milestone report.

## 6. Reconciling with Fable's existing Blender intake

When the owner points at it (09 Q8):

| if Fable's tool… | then |
|---|---|
| renders at a different angle | **the game's projection wins.** The 35° choice is tied to the wall-face autotiling and the foot-box collision |
| quantises per frame | move to per-family fitting (§4 step 3), or P2's palette swap and the stream slots break |
| emits addresses or fixed VRAM offsets | strip them. The allocator places everything (CLAUDE.md, "never guess an address") |
| has its own manifest format | keep it, and write an adapter into §4 step 1 |
| already does outline/rim/scale differently and the art reads well | prefer the proven tool, and amend this file |
