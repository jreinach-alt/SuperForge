# vendor/art/split_v — the two pack-derived blobs, vendored

`tools/gen_split_v_assets.py` derives these two blobs from the original
art-pack zips. **Both packs are CC0 — see the Licence section below.** The zips are NOT vendored and the
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
Both packs are CC0 — the camelot pack (`sv_knight_chr.bin`) and the Four
Seasons tileset (`sv_stage_pal.bin`). Credit is optional under both and is
given anyway in the generator's header.
