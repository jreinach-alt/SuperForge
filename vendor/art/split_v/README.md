# vendor/art/split_v — the two pack-derived blobs, vendored

`tools/gen_split_v_assets.py` derives these two blobs from the original
art-pack zips. **The two packs are under different grants — see the Licence
section below; one of them is not CC0.** The zips are NOT vendored and the
normal build does not need them: these committed blobs are what the generator
emits by default, so a bare checkout builds. Point `SF_SOURCE_ART_DIR` at a
directory holding the pack zips to re-derive from source instead.

| file | pack | what it is |
|---|---|---|
| `sv_stage_pal.bin` | Four Seasons Platformer Tileset [16x16][FREE] — Rotting Pixels | the 8-colour stage ramp, derived from region (0,0,16,32) |
| `sv_knight_chr.bin` | camelot [version 1.0] — analogStudios_ | 32x32 Arthur Pendragon frame 0, traced, OBJ-grid laid out |

Everything else the generator emits is **authored**, not derived, so it is
regenerated from scratch on every build and is not vendored.

**These cannot drift silently.** When `SF_SOURCE_ART_DIR` IS set the generator
does a fresh conversion and byte-compares it against the vendored copy, failing
the build on a mismatch. Re-vendoring is therefore a deliberate act: delete the
file, regenerate with the pack zips on disk, and commit the new bytes with the
reason.

Licences and grants: this repo's `NOTICE`, traced in `docs/92` §5.1–§5.2.
**The two packs are NOT under the same grant** — the
camelot pack (`sv_knight_chr.bin`) is CC0; the Four Seasons tileset
(`sv_stage_pal.bin`) is **Rotting Pixels' own permissive grant, which is not
CC0** (free + commercial use, modification allowed, credit optional, but no
public-domain dedication — we cannot re-dedicate someone else's work). Credit
is optional under both and is given anyway in the generator's header.

*Corrected twice on 2026-08-16, and the second time is the instructive one.
This paragraph had read "Both packs are CC0" — contradicting
`vendor/art/four_seasons_tileset/README.md`'s own, correct, statement that the
tileset is not CC0 and must not be flattened to it (`docs/92` §5.1). Fixing
the paragraph left the file's **opening sentence** still saying "CC0 pack
zips", so it went on contradicting itself in exactly the shape the first
correction was raised for. Both are now fixed. The lesson —* a sentence that
covers N artifacts under one licence clause is a defect risk proportional to N
— *applies to a file's summary line as much as to its licence paragraph, and
the summary line is the one nobody re-reads.*
