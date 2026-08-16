# vendor/art/mode7_chamber — the `mode7_chamber` rail's oracle

**Three files, all of them committed reference conversions.**
`tools/gen_chamber_assets.py` reads them as its refusal oracle: it authors
every blob procedurally from the design constants and refuses to emit anything
that disagrees with these bytes — or anything at all if one is absent (a gate
that passes when its evidence is missing is not a gate). **Nothing here is a
build input.**

| file | size | what it is |
|---|---|---|
| `ref_chamber_map.bin` | 32,768 B | the interleaved Mode 7 blob — 16,384 tilemap bytes in the EVEN positions, 16,384 B of 8bpp CHR in the ODD ones |
| `ref_chamber_palette.inc` | 6 words | six BGR555 words in CGRAM index order 0..5, plus `CHAMBER_PAL_COUNT` |
| `ref_chamber_tables.inc` | — | the **M7A barrel curve** (192 words, the captured `$0100 → $0180 → $0100` raised cosine) and the **COLDATA vignette** HDMA table (`[count, value]` pairs, 217 covered scanlines) |

md5, recorded 2026-08-08 so a silent edit to the oracle is visible:

```
b0f52b636ce58fcdde1f121bf0dcaae3  ref_chamber_map.bin
25400d4729d7dca90eb0c561d2c14bcf  ref_chamber_palette.inc
5b7d1cd711459f3ace170a86a7084fa3  ref_chamber_tables.inc
```

### Provenance — and why reproducing it is legitimate

The art is **first-party and procedural**: original placeholder art (an ashlar
stone floor with an asymmetric inlay), authored from scratch. It reproduces no
commercial-game content — only the Mode 7 effect TECHNIQUE is recreated, never
any game's art. `docs/92` §5.2 records the same trace independently.

Every tile is a **solid colour** decided by a three-line rule over the tile
grid — full-width brass ribs every 8 tiles, otherwise a two-tone ashlar
checker with mortar on the block boundaries. So there is no pixel data to
infer and no format to guess: `gen_chamber_assets.py` re-derives the same
128×128 field from the same constants and the oracle proves it landed on the
same bytes.

That is what makes this an oracle rather than an import. **`CLAUDE.md`'s
asset-import rule** — ground-truth a converter against the SOURCE, never
against a re-rendering of its own output — is satisfied twice over here: the
byte comparison above, and `tests/test_mode7_chamber.py`'s reference-gated
case, which builds and runs a **reference ROM** and compares its rendered
frame to ours. The second is the stronger of the two and it is the one that
skips where that ROM is not on disk.

### The two indices that are not obvious, and are load-bearing

1. **Index 0 is reserved and no pixel uses it.** A `reserve_backdrop` pass
   forces CGRAM word 0 to the dark stone (the Mode 7 out-of-map fill) and
   remaps every pixel that had landed on index 0 to a freshly appended
   duplicate. The result: word 4 duplicates word 0, the ashlar-dark tile draws
   with index **4**, and the rib highlight — which had been index 0 because it
   is the image's first row — moved to index **5**.
2. **The CHR padding is 5, not 0.** That same remap ran over the whole
   16,384-byte CHR block, including the 251 unused tiles, so every padding
   byte reads as index 5. It is invisible (nothing indexes those tiles) and it
   is part of the bytes, so the generator reproduces it rather than "cleaning
   it up" into a mismatch.

### What these oracles are NOT

They are not this rail's shipped blobs. `tools/gen_chamber_assets.py` emits
`m7c_map` and `m7c_pal` byte-identical to the first two, and **four more**
files with no counterpart here at all: the nine-step `bow_a` column set, the
`persp_d` perspective column, and the three-plane `m7c_vign` COLDATA table.
`ref_chamber_tables.inc` carries only one bow (the captured curve) and a
`[count, value]` vignette in HDMA-table form, so it is the oracle for the
**step-8 bow** and for the vignette's per-line intensity profile — not for
those four files themselves.
