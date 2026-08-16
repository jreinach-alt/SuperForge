# vendor/art/camelot — the brawler rail's knights

Two PNGs from **analogStudios_ / Kevin's Mom's House, "camelot"** (the
`legends_` series): <https://analogstudios.itch.io/camelot> →
<https://kevins-moms-house.itch.io/camelot>.

These are the **original pack files, unmodified**, extracted from the pack
archive `camelot_ [version 1.0].zip` — every one sha256-matched against its zip
member, recorded in [`docs/92`](../../../docs/92_provenance_audit.md) §5.1.
`tools/gen_brawler_assets.py` reads them at build time and emits the SNES CHR +
palette + animation blobs the `brawler` rail links.

| file | native | pack path | used for |
|---|---|---|---|
| `arthurPendragon_.png` | 256×256 (8×8 grid of 32×32) | `camelot_ [version 1.0]/arthurPendragon_.png` | the player: 4-frame idle, 8-frame run, 4-frame hit (right-facing; walking left is an OBJ HFLIP) |
| `mordred_.png` | 256×352 (8×11 grid of 32×32) | `camelot_ [version 1.0]/mordred_.png` | the enemy: 4-frame idle, 8-frame run |
| `READ ME.txt` | — | `camelot_ [version 1.0]/- READ ME -.txt` | the pack's own row map, quoted below. Renamed only to drop the leading dash (a leading `-` is an option to half the tools that would ever touch it) |

**32×32 is the pack's cell AND the art's box** — unlike the `dungeon_sprites`
pack, no crop and no centre-paste happens here. `png2snes.py`'s `recenter` is
skipped entirely for a frame that already measures exactly the OBJ box
("already exact; keep author's framing", `tools/png2snes.py:381`), and
`gen_brawler_assets.py` reproduces that branch. It matters: the author frames
every knight with **four transparent rows under the feet**, so the drawn
content ends at row 28 of 32. That number is what anchors the lane band to the
floor's surface — re-centring would have moved it to 24 and left a visible
4 px sky gap under the feet.

Arthur uses 8 opaque colours and Mordred 7, so the 4bpp OBJ palettes are not a
quantisation either. That is what makes the conversion lossless and exactly
reproducible, which the cross-check below relies on.

## The pack's row map

The sheets are row-major grids of 32×32 cells and the rows are per-character
animations. The pack's own `READ ME.txt` gives the order; the two conversions
use these collected-frame ranges (a "collected" frame is a NON-EMPTY cell,
counted in row-major order — `collect_frames` skips empty cells, so the index
is not simply `row*8 + col` on a sheet with gaps):

| character | animation | collected frames |
|---|---|---|
| Arthur | idle | 0–3 |
| Arthur | run | 8–11 + 16–19 |
| Arthur | hit | 48–51 |
| Mordred | idle | 8–11 |
| Mordred | run | 16–19 + 24–27 |

Only the **right-facing** quarter of each row is taken (cols 0–3). The pack
also ships left-facing frames in cols 4–7; the rail's facing idiom H-flips the
right ones instead, which halves the CHR. That is the whole reason Arthur fits
in exactly one 256-tile OBJ name table.

The pack's "hit" row is a **damage-reaction flash, not an attack swing**. This
rail uses Arthur's as a pseudo-swing for compactness; a real swing would
composite the separate `excalibur_` weapon sheet as an overlay sprite. Recorded
here because it is a property of the ART, not of this rail.

## Licence

**CC0** — the author's itch.io page links the CC-0 deed; read from that page
and recorded on 2026-07-18. The operative record is this repo's
[`NOTICE`](../../../NOTICE), and the trace behind it is
[`docs/92`](../../../docs/92_provenance_audit.md) §5.1.

The grant is taken from the author's PAGE and not from any file inside the zip
— CLAUDE.md's warning about taking an asset's provenance from a licence its
own author shipped beside it. (The zip's own `READ ME.txt` is a contact note,
not a grant.) That gives this pack the same strength of provenance as
`vendor/art/dungeon_sprites`: a live-verified link to the deed itself.

The blobs `tools/gen_brawler_assets.py` emits into `build/assets/` are
mechanical format conversions and inherit the same dedication.

## Why the PNGs and not the converted `.inc` blobs

the asset-import rule: a converter that byte-traces a *derived* asset
must be ground-truthed against a render it did not produce, because validating
it against your own re-rendering of your own output is a tautology. Reading the
**original PNG** removes that trap at the root — the PNG is independent of
anything this repo produces. `platformer` and `shmup` take the same route for
the same reason.

## `ref_arthur.inc` / `ref_mordred.inc` — fixtures, NOT build inputs

Committed **reference conversions** of the same PNGs: the output of a
`png2snes.py` conversion, frozen as bytes.

Nothing in the build reads them. `tests/test_brawler.py` does, as an
**independent cross-check**: the CHR, the palette, the per-frame tile offsets
and the animation tables this repo derives from the PNGs must equal these blobs
byte for byte. That is a real check precisely because the two derivations share
no code — this one is `tools/gen_brawler_assets.py`, that one was
`png2snes.py`, and they agree only if both read the same pixels correctly.

They also carry the load contract in their headers, which this rail honours:

> upload `arthur_chr` at an OBJ tile index that is a **MULTIPLE OF 16**. A
> frame's OAM tile = base + `arthur_f<N>`. 16x16+ sprites read their lower tile
> rows at +16 tile numbers — this blob is laid out for that, which is WHY base
> must be 16-aligned.

Both bases here are name-table origins (tile 0 and tile 256), so both are
16-aligned by construction.
