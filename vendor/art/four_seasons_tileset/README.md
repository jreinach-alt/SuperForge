# vendor/art/four_seasons_tileset — the brawler rail's floor

One PNG from **Rotting Pixels, "Four Seasons Platformer Tileset [16x16]
[FREE]"**:
<https://rottingpixels.itch.io/four-seasons-platformer-tileset-16x16free>.

The **original pack file, unmodified**, extracted from the pack archive
`Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels.zip` — both
files sha256-matched against their zip members, recorded in
[`docs/92`](../../../docs/92_provenance_audit.md) §5.1.
`tools/gen_brawler_assets.py` reads it at build time and emits the BG CHR,
palette and patch-map blobs the `brawler` rail links.

| file | native | used for |
|---|---|---|
| `four-seasons-tileset.png` | 176×256 | the terrain floor. Only the top-left **64×48 px** are converted (`--region 0,0,64,48`) — an 8×6 grid of 8×8 cells, deduping to 49 unique tiles across a single 12-colour BG palette |
| `RottingPixels.txt` | — | the pack's own follow-us note. **Not a licence** — see below |

That same 64×48 region is the one `ref_terrain.inc` below was converted from,
which is what makes the two comparable at all. Only `brawler` needs this pack
— the `shmup` rail draws the spaceship pack instead.

## Licence

**CC0.** The operative record is this repo's
[`NOTICE`](../../../NOTICE); the trace behind it is
[`docs/92`](../../../docs/92_provenance_audit.md) §5.1–§5.2. The grant is the
author's itch.io page text, quoted as recorded on 2026-07-18:

> This asset pack can be used in both free and commercial projects. You can
> modify it to suit your own needs. Credit is not necessary, but appreciated.

**Recorded as CC0 by the project owner's determination, 2026-08-16**, on
those terms. Credit is optional and given anyway: **floor tiles by Rotting
Pixels**.

The `RottingPixels.txt` shipped inside the zip is kept beside the PNG so the
distinction stays visible — it is the pack author's own file and it is *not*
the licence. That is the exact shape CLAUDE.md warns about ("an asset's
provenance taken from a licence its own author wrote"): the grant this repo
relies on is the itch.io page text quoted above, not this file.

## `ref_terrain.inc` — fixture, NOT a build input

A committed **reference conversion** of the same 64×48 region, frozen as bytes.
Nothing in the build reads it; `tests/test_brawler.py` does, as an independent
cross-check that this repo's CHR, palette and 48-word patch map equal it byte
for byte — a real check because the two conversions share no code (same
argument as `vendor/art/camelot`).
