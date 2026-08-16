# vendor/art/dungeon_sprites — the platformer rail's source art

Eight PNGs from **analogStudios_ / Kevin's Mom's House, "dungeonSprites"**
(the `fantasy_` series): <https://analogstudios.itch.io/dungeonsprites>
→ <https://kevins-moms-house.itch.io/dungeonsprites>.

These are the **original pack files, unmodified**, extracted from the pack
archive `dungeonSprites_v1.0.zip` — every one sha256-matched against its zip
member, recorded in [`docs/92`](../../../docs/92_provenance_audit.md) §5.1.
`tools/gen_platformer_assets.py` reads them at build time and emits the SNES
CHR + palette blobs the `platformer` rail links.

| file | native | pack path | used for |
|---|---|---|---|
| `fHero_idle_rIdle_0..3.png` | 24×24 | `fHero_/idle_/rIdle_N.png` | the hero, 4-frame idle bob (right-facing; walking left is an OBJ HFLIP) |
| `ghost_idleWalkRun_rIdleWalkRun_0..3.png` | 24×24 | `ghost_/idleWalkRun_/rIdleWalkRun_N.png` | the two patrol ghosts |

Filenames are the pack's, flattened with their directory prefix so the path a
file came from survives (the `shmup` pack precedent, `vendor/art/spaceship_pack`).

**24×24 is the pack's cell, not the art's size.** Every frame's opaque content
fits inside 16×16; the reduction is an **alpha-bbox crop and a centre paste** —
no scaling, no resampling, no colour loss. The hero uses 6 colours, the ghost 3,
so the 4bpp OBJ palette is not a quantisation either. That is what makes the
conversion lossless and exactly reproducible, which the cross-check below relies
on.

## Licence

**CC0** — the author's itch.io page links the CC-0 deed; read from that page
and recorded on 2026-07-18. The operative record is this repo's
[`NOTICE`](../../../NOTICE), and the trace behind it is
[`docs/92`](../../../docs/92_provenance_audit.md) §5.1.

Worth keeping distinct rather than flattened: unlike the spaceship pack —
which carries an owner CC0 *attestation* plus a bare "free for commercial use"
grant, with the deed itself still an open question — this pack's page links the
**CC-0 deed directly**. That is materially stronger provenance, and both are
recorded as they actually stand rather than as one word.

The blobs `tools/gen_platformer_assets.py` emits into `build/assets/` are
mechanical format conversions and inherit the same dedication.

## Why the PNGs and not the converted `.inc` blobs

the asset-import rule: a converter that byte-traces a *derived* asset
must be ground-truthed against a render it did not produce, because validating
it against your own re-rendering of your own output is a tautology. Reading the
**original PNG** removes that trap at the root — the PNG is independent of
anything this repo produces. `shmup` takes the same route for the same reason.

This rail first shipped hand-authored replacement sprites, on the belief that
the pack PNGs were unavailable, and that cost the flagship rail its identity:
the characters were no longer the characters. They were available all along,
in the archive named above, and reading them is what this directory exists
for.

## `ref_hero.inc` / `ref_ghost.inc` — fixtures, NOT build inputs

Committed **reference conversions** of the same PNGs: the output of a
`png2snes.py` conversion, frozen as bytes.

Nothing in the build reads them. `tests/test_platformer.py` does, as an
**independent cross-check**: the CHR and palette this repo derives from the
PNGs must equal these blobs byte for byte. That is a real check precisely
because the two derivations share no code — this one is
`tools/gen_platformer_assets.py`, that one was `png2snes.py`, and they agree
only if both read the same pixels correctly.

They also carry the load contract in their headers, which this rail honours:

> upload `hero_chr` at an OBJ tile index that is a **MULTIPLE OF 16**. A
> frame's OAM tile = base + `hero_f<N>`. 16x16+ sprites read their lower tile
> rows at +16 tile numbers — this blob is laid out for that, which is WHY base
> must be 16-aligned.

Hence `PLF_HERO_TILE = 0` and `PLF_GHOST_TILE = 32`. Spacing them 16 apart
instead of 32 puts the ghost's top row on the hero's bottom row — a bug that
has been shipped before, which is why the note is in the header at all.
