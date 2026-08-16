# vendor/art/spaceship_pack — the shmup rail's source art

Eight PNGs from the **AlcWilliam "Spaceship Pack"**, hosted via the
`pixel-by-pixel.itch.io` account:
<https://pixel-by-pixel.itch.io/alcwilliam-space-ship-pack>.

These are the **original pack files**, unmodified, extracted from the pack
archive `Spaceship Pack.zip` — every one sha256-matched against its zip member,
recorded in [`docs/92`](../../../docs/92_provenance_audit.md) §5.1.
`tools/gen_shmup_assets.py` reads them at build time and emits the SNES CHR +
palette blobs the `shmup` rail links.

| file | native | used for |
|---|---|---|
| `ship_2.png` | 48×48 | the player ship (downscaled 3× to the 16×16 OBJ box) |
| `ship_5.png` | 48×48 | the enemy fighter (rotated 180°, nosed down at the player) |
| `turbo_blue.png` | 96×48 (2 frames) | the engine plume composited onto both ships' 2-step flicker |
| `explosion_sheet.png` | 336×48 (7 frames) | the kill-burst; frames 0–3 only (4–6 go too dark to read at 16 px) |
| `planet_1/2/4/6.png` | 48×48 each | the drifting planet field (downscaled to 32×32 = 4×4 BG tiles) |

`explosion_sheet.png` is the pack's `Space Ships Explosion.png`, renamed only to
drop the spaces (a filename with spaces in a Makefile prerequisite is a bug
waiting to happen).

## Licence — recorded as it actually stands, not laundered

**Carried here in full rather than summarised, because the honest form is not
"CC0":** the reachable itch.io page states, quoted as recorded on 2026-07-19,
*"Free for commercial use."* (+ *"No generative AI was used"*) — a permissive
commercial grant — and the page carries **no explicit CC0 deed label**. The
recorded verification alongside it carries the pack owner's own CC0
*attestation*.

So: **a live permissive commercial grant, plus an open question about the CC0
deed**, and that open question travels with the files — it is logged as such in
[`NOTICE`](../../../NOTICE) and
[`docs/92`](../../../docs/92_provenance_audit.md) §7 Q1 rather than rounded off
to the nearer word. **Confirm the explicit CC0 deed / attribution terms with
the author at the next release.** This is CLAUDE.md's "an asset's provenance
taken from a licence its own author wrote is not evidence" applied to an
attestation: it already flags its own uncertainty, and the flag is the part
worth keeping.

The derived blobs `tools/gen_shmup_assets.py` emits into `build/assets/` are
mechanical format conversions of these files and inherit the same grant.

## Why vendored rather than fetched at build time

The build must work from a bare checkout with nothing but this tree on disk —
no network, no sibling directory, no unpacked archive. 11 KB of PNG is the
whole cost of keeping that true, and it is what lets the asset tests below run
anywhere instead of skipping.

## Why the PNGs and not a converted `.inc` blob

the asset-import rule: a converter that byte-traces a *derived* asset
must be ground-truthed against a render it did not produce, because
validating it against your own re-rendering of your own output is a tautology —
one that has shipped visibly broken art on this project before. Reading the
**original PNG** removes the trap at the root: the PNG is independent of
anything this repo produces, and `tests/test_shmup.py` compares the rendered
SNES frame back to it.
