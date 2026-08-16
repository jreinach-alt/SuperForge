# vendor/art/split_h_matrix — the matrix-band pair's independent oracle

One artefact, frozen as committed bytes: the reference conversion this rail's
asset generator is held to. **It is not a build input.**
`tools/gen_split_h_matrix_assets.py`
reads it as its refusal oracle, and `tests/test_split_h_matrix_assets.py`
reads it again — asserting that the gate refuses a perturbed reference, a
drifted generator, and an absent oracle. Nothing else opens it.

| file | size | what it is |
|---|---|---|
| `ref_checker_map.bin` | 32,768 B | the interleaved Mode 7 VRAM blob — a 128×128 tilemap in the even bytes, two solid 8bpp CHR tiles in the odd |

### Provenance — the exact algorithm and its constants

`ref_checker_map.bin` ← `build()`: `MAP_W=128`, `TILE_WORDS=64`,
`tilemap[row*128 + col] = (row ^ col) & 1`; CHR = two solid tiles, tile 0 =
64 bytes of `$01` and tile 1 = 64 bytes of `$02`; byte-interleaved
(`out[0::2] = tilemap`, `out[1::2] = chr`).

**`split_h_persp3_demo` wants the same file, byte for byte**
(`md5 07a9125927a98955daa1445b2ffd2c2c`): the two rails differ in band count
and in nothing else, art included. One oracle therefore serves both, and
`tools/gen_split_h_matrix_assets.py` emits one blob that both ROMs `.incbin`
— a second copy would only give a future editor two places to drift.

### Why vendored rather than gated on a tree that may not be there

AGENTS.md's skip census names asset ground-truth as "a real coverage hole
worth closing": it is the one asset check that is not a tautology, and a check
that only runs where some other directory happens to exist is a check that
never runs. The fix is to vendor the oracle with its provenance rather than to
delete the skip. This directory is that fix applied at authoring time — the
ground-truth comparison in `tests/test_split_h_matrix_assets.py` runs under
`make bare-check` and adds nothing to the bare skip count.

### Not the palette

The three checker colours are equates, not a file: `$5400` backdrop, `$01E0`
dark green, `$03E0` light green. They live in
`tools/gen_split_h_matrix_assets.py`'s `PALETTE` tuple; there is no binary to
vendor.
