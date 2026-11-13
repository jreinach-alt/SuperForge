# 07 — Assets and audio

> DRAFT SPEC. **Provenance is a gate, not a courtesy.** Every non-original
> asset carries a per-pack README under `vendor/art/<pack>/` (licence, source
> URL, sha256 against the archive) and a NOTICE entry, as `docs/92` does it.
> Nothing is traced, recoloured or "inspired-by" from the genre reference. The
> look is our own.

## 1. Art direction (one paragraph the artist and the agent both hold)

The setting is warm torchlight in cold stone. The floor is a desaturated
slate. Walls are darker, with a lit top edge. Braziers and chests are the only
warm accents, so the eye finds loot.

Heroes are compact, 16×16, readable from the silhouette alone:

- **P1** in cool blue, **P2** in amber. That is the same CHR, palette swapped.
- Each hero's weapon is a separate swing sprite, so the weapon change is
  visible.

Enemies read by colour family:

- grunts: rust
- archers: green
- brutes: bone
- skitters: violet

The boss is two-tone with one glowing weak point.

## 2. Asset list, tier M

| asset | format | count | notes |
|---|---|---|---|
| floor/wall metatiles | 16×16, 4bpp, in BG palettes 0–5 | ~32: floor ×4, rubble, brazier ×2 frames, doorway, gate, stairs, wall ×8 autotile, pillar, chasm ×4 edge | **the `tiles16` quad layout** (N, N+1, N+16, N+17) is the generator's job, asserted from VRAM |
| hero | 16×16 OBJ, **streamed** (02 §1.2) | 4 directions × (idle 2 + walk 4 + roll 3 + hurt 1 + downed 1) = 44 | left = HFLIP of right; one CHR set, two palettes |
| swing | 16×16 OBJ, **streamed** | 5 melee bases × 3 frames × 3 directions (left by flip) = 45 | |
| shots | 8×8 | arrow ×2, bolt, stone, ember ×2, enemy bolt | 8-direction arrows use flips plus 2 diagonals |
| drops | 8×8 | gear bag (tinted per owner), ammo, potion, spark | |
| enemies | 16×16 (brute 32×32) | 4 types × (walk 2 + windup 1 + attack 1 + hurt 1) | they share OBJ name table 1 |
| boss | BG2 4bpp tiles, 64×64 px per pose | 3 poses | it is the BG2 layer (02 §1); its tiles are in the boss BG CHR, not in an OBJ name table |
| FX | 8×8 / 16×16 | hit spark ×3, puff ×3, blast ×4, heal ×2, stun ×2 | |
| HUD | BG3 2bpp | HP bar fill ×9, digits, icons B/L/R/X | through `text_chr` |
| UI font | BG3 2bpp | the kit's vendored font | `docs/11` |

**Placeholder path.** `vendor/art/dungeon_sprites` holds a CC0 16×16 hero and
ghost, provenance-traced in `docs/92` §5.1. They are good enough to stand in
for the hero and an enemy through M5. Final art replaces them through the same
generator.

## 3. The asset generator (`tools/gen_dungeons_assets.py`)

It is the single source of truth for every blob, and also the tests' oracle.
It reads:

- `tools/dungeons/data/templates.txt` → the ROM template blob: 196 B each,
  plus a header of type, doors, weight and flip.
- `tools/dungeons/data/gear.toml` → base, enchant, multiplier and weight
  tables.
- a `tools/dungeons/data/enemies.toml` (to write, from 05 §2).
- the art PNGs → CHR + palettes, through the repo's shared encoders. Never
  silently mask an index: the asset-codec rule.

It emits blobs plus a `.inc` of counts and offsets. It never emits addresses,
because the allocator does that.

## 4. Audio

| cue | source | status |
|---|---|---|
| hit, pickup, footstep, explosion, chime, select | the existing `assets/audio/sound-effects.txt` cues | **reuse** |
| swing (3 weights), bow, roll, potion, revive, down, gate seal/open, boss roar | new TAD SFX | new |
| camp theme | new MML | new |
| floor theme (biome 1) | new MML | new; the per-cell echo comes from the `room` ambience-SFX pattern |
| boss theme | new MML | tier S |

- TAD owns the SPC outright, and an over-budget song **fails the build**.
- **Audio has never run on a cart** (`JAM.md` row 6c). M10 includes a flashcart
  listen-through.
