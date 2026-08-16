# vendor/art/m7_dungeon — the `m7_dungeon` rail's independent oracle

Six artefacts, frozen as committed bytes: the reference conversions this rail's
asset generator is held to. **Nothing here is a build input.**
`tests/test_m7_dungeon_assets.py` reads them, and only that.

| file | size | what it is |
|---|---|---|
| `ref_dungeon_map.bin` | 32,768 B | the interleaved Mode 7 VRAM blob — tilemap in even bytes, 8bpp CHR in odd |
| `ref_dungeon_terrain.bin` | 16,384 B | the world-space collision array, row-major `[ty*128+tx]`, 1 = solid |
| `ref_dungeon_palette.inc` | 9 colours | the floor/wall/goal CGRAM palette, `.word` BGR555 |
| `ref_hero.inc` | 18 tiles + 16 words | the plan-view knight OBJ, 4bpp |
| `ref_enemy.inc` | 18 tiles + 16 words | the plan-view slime OBJ, 4bpp |
| `ref_win.inc` | 4 tiles + 16 words | the gold sparkle-star win card, 4bpp, emitted as two tight 64-B row blobs |

## Why these are a real oracle and not a tautology

`tools/gen_m7_dungeon_assets.py` is a **self-contained re-implementation**. It
shares no code with the program that produced these bytes — it cannot, because
the build runs from a bare checkout with nothing but this tree on disk, so
there is no converter module to import and a `../` would be a bug.

That is exactly what makes the comparison worth running. These blobs were
produced by a *different program*, on a *different run*, from a maze predicate
and a tile-dedup converter this repo re-derived from the descriptions of both.
If the two agree byte-for-byte across 32,768 + 16,384 bytes, the re-derivation
reproduced the predicate, the checker phasing, the seam diagonal, the goal
region, the tile dedup order, the palette insertion order, the
`reserve_backdrop` remap and the interleave — all of them, or the bytes would
differ.

This is the asset-import rule satisfied at the root: the generator is
ground-truthed against something this repo did not produce. Contrast
`vendor/art/dungeon_sprites/`, where the same discipline was met by reading the
original pack PNGs instead.

`ref_dungeon_terrain.bin` is checked even though **no 16,384-byte terrain
array ships**. The rail uses a 256-byte tile-id → flag table over the tilemap
that is already in ROM. The terrain array is generated as an intermediate
purely so it can be compared: it is what proves this repo's `is_wall()` is the
same predicate, cell for cell, independently of anything the converter does.
The flag table is then proven equivalent to it over all 16,384 world cells.

## `ref_win.inc` is the shape mismatch worth naming

The reference bytes hold the win card as two tight 64-byte blobs
(`win_chr_top` = tiles TL,TR and `win_chr_bot` = tiles BL,BR) rather than the
18-tile zero-padded OBJ grid the hero and enemy use — a saving of 448 B that
mattered where bank 0 was nearly full. This repo emits the **uniform 18-tile
grid for all three**: the allocator decides ROM placement here, and uniformity
is worth more than 448 B in a 512 KB image. The byte-identity check therefore
compares *tile content*: grid tiles 0/1/16/17 against `win_chr_top` ‖
`win_chr_bot`, and the remaining 14 tiles against zero.

## Provenance and licence

All six are **original procedural art with no pack source, dedicated CC0**.
Per CLAUDE.md's "two kinds of question" rule, an emitted header saying so is
**secondary** — it is the author's own note shipped beside the asset, not
evidence. What is first-hand is that the generating code was read: the three
sprite scripts build their pixels from `math.hypot` distance bands and literal
RGB tuples, with no file read and no image import, so there is no upstream to
have a licence; the floor is authored from a `MAZE` string literal the same
way. `docs/92` §5.2 records that trace. It is then re-derived independently in
`tools/gen_m7_dungeon_assets.py`, whose output is byte-identical, so the
derivation is checkable rather than asserted.

## Re-vendoring

Deliberate act only. Delete the file, put the new bytes in its place, and
commit it with the reason — the same discipline `vendor/art/split_v/README.md`
states. A silent update would turn the oracle into an echo.
