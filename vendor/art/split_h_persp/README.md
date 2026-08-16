# vendor/art/split_h_persp — the `split_h_persp_demo` rail's oracle

**One file, and a pointer to a second that was already here.**
`tools/gen_split_h_persp_assets.py` reads both as its refusal oracle and
refuses to emit anything that disagrees with them — or anything at all if
either is absent — a gate that passes when its evidence is missing is not a
gate. Nothing here is a build input.

| file | what it is |
|---|---|
| `ref_palette.inc` | the five `COLOR_*` equates in CGRAM index order 0..4 |
| **`../split_h_2p/ref_checker_map.bin`** | the 32,768 B interleaved Mode 7 blob — **already vendored** |

### Why the map oracle is the neighbouring directory's file

This rail and `split_h_2p_demo` want **byte-identical** checker maps — md5
`3862ea7ca2e418846c273a5b47e392b0` for both, measured 2026-08-07. The same
algorithm produced them (`MAP_W=128 BLOCK=4 STRIPE=32 PHASE=16`, four solid
8bpp CHR tiles), and both rails read the same warm/cool stripe field for the
same reason: it is the per-band *world position* oracle, orthogonal to the
checker period.

Copying it a second time under this directory would put two identical 32 KB
blobs in the tree and give a future editor two places to drift. So this rail
names `../split_h_2p/ref_checker_map.bin` directly — in the generator, in
`$(SHP_ORACLE)`, and here. The provenance of that file is recorded in
`../split_h_2p/README.md` and is unchanged by this rail reading it.

### What the palette oracle is NOT

The palettes **differ**: `split_h_2p_demo` ships the forest/autumn five
(`$5400 $0DA0 $1340 $00DF $023F`), this rail ships the cool-green /
warm-red five (`$5400 $0140 $7FE0 $014A $7FFF`). Same *structure* — a
backdrop, a cool pair with red 0 and a warm pair with red high — different
bytes. That is why this file exists at all rather than the rail reusing
`../split_h_2p/ref_palette.inc`, and why the generator asserts the red
separation (cool R=0, warm R>0) on top of the byte match: the separation is
what the rendered per-band position test reads, so a re-theme that softened
it must fail here first.
