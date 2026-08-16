# vendor/art/split_h_2p — the `split_h_2p_demo` rail's independent oracle

Seven artefacts, frozen as committed bytes: the reference conversions this
rail's asset generator is held to. **Nothing here is a build input.**
`tools/gen_split_h_2p_assets.py` reads them as its refusal oracle, and
`tests/test_split_h_2p_assets.py` reads them again — asserting that the gate
refuses a perturbed reference, a drifted generator **and an absent oracle**;
nothing else does. That last direction was soft until it was tested: deleting
this directory used to print `NO ORACLE … UNVERIFIED` and emit the blobs
anyway, exit 0. It is now a build refusal, and `$(SH2_ORACLE)` in the Makefile
names these files rather than `$(wildcard …)`, so their absence cannot make
the dependency evaporate either.

| file | size | what it is |
|---|---|---|
| `ref_checker_map.bin` | 32,768 B | the interleaved Mode 7 VRAM blob — 128×128 tilemap in the even bytes, four solid 8bpp CHR tiles in the odd |
| `ref_poses1_ab.bin` | 448 B | the fixed-angle (`--angles 1`) per-scanline `[A,B]` pose table, 112 lines × 4 B, s8.8 LE |
| `ref_poses1_cd.bin` | 448 B | the matching `[C,D]` table (`C = −B`, `D = A`) |
| `ref_poses256_ab.bin` | 114,688 B | the 256-heading `[A,B]` set — 256 poses × 448 B, in heading order (the rotation set) |
| `ref_poses256_cd.bin` | 114,688 B | its `[C,D]` partner |
| `ref_move256.bin` | 1,024 B | 256 forward vectors, `(dx, dy)` s16 in 8.8 |
| `ref_palette.inc` | 5 words | the `COLOR_*` equates, in CGRAM index order 0..4 |

### Provenance — the exact algorithms and arguments

Each blob is stated here completely enough to be rebuilt from this text alone.
That is the point: the generator in `tools/` was written from these
descriptions, so a byte match means the description and the bytes agree.

- `ref_checker_map.bin` ← `build_map()`: `MAP_W=128`, `BLOCK=4`, `STRIPE=32`,
  `PHASE=16`,
  `tile = ((row//4) ^ (col//4)) & 1 + (2 if ((col+16)//32)&1 else 0)`; CHR =
  four solid tiles, tile *k* = 64 bytes of value *k*+1; byte-interleaved
  `out[0::2] = tilemap`, `out[1::2] = chr`.
- `ref_poses1_{ab,cd}.bin` ← `tools/gen_pose_tables.py --angles 1 --out-prefix
  poses1`, i.e. at that tool's own defaults `--lines 112 --scale-far 1.5
  --scale-near 0.625`. Hyperbolic ramp `S(k) = K/(k+k0)` solved through
  `S(0)=scale_far`, `S(111)=scale_near`, emitted as `round(S·256)`; at angle 0
  that gives `A = D = ramp[k]`, `B = C = 0`. Ramp ends: 384 … 160.
- `ref_poses256_{ab,cd}.bin` ← the same tool at `--angles 256 --out-prefix
  poses256`, i.e. the same defaults again (`--lines 112 --scale-far 1.5
  --scale-near 0.625`): 256 poses at `2πh/256`, concatenated in HEADING ORDER
  at 448 B each. That ordering and that stride ARE the runtime's address
  arithmetic (`ptr = slice_base + (h & 63)*448`, `bank = base + (h >> 6)`), so
  the byte-identity check is what proves them. The four 28,672 B bank slices
  the ROM `.incbin`s are cut from this blob by
  `tools/gen_split_h_2p_assets.py`, after the match.
- `ref_move256.bin` ← `emit_move_lut(256)`:
  `entry h = round(2*256*(-sin, -cos)(2πh/256))` as two
  s16 words — a constant 2.0 px/frame forward vector at every heading.
- `ref_palette.inc` ← five `COLOR_*` equates, unmodified.

### The sprite projector's tables

All six are committed bytes from a `gen_sprite_assets.py` run with no
arguments — every constant is in the descriptions below. They are the INVERSE
side of the same geometry as the pose tables above: that generator takes
`scale_ramp` from `tools/gen_pose_tables.py` rather than re-deriving it, so a
match here is a match against the very ramp the floor streams.

- `ref_sp_sincos.bin` ← the `sincos` block: 256 × (cos, sin) s8.8 with
  magnitudes clamped to ±255. The clamp is load-bearing — it is what lets the
  projector's dot products be 8×8 hardware multiplies.
- `ref_sp_vk.bin` ← the `vk` block: `d -> argmin_k |g(k) - d|` over
  `d ∈ [1, g(0)]`, `$FF` outside. Ties go to the lowest `k` (`min`'s own rule).
- `ref_sp_recip_lo.bin` / `ref_sp_recip_hi.bin` ← `round(65536/RAMP[k])`
  split into low byte and 9th bit.
- `ref_sp_tier_nocull.bin` ← the FULL row→tier ladder (`raw_tier`), which is
  what the runtime reads. The companion `sp_tier_lut.bin` (the same table with
  `$FF` seam marks) is NOT vendored: nothing at runtime reads it, and its only
  consumer is a scenario-authoring pass this rail does not build.
- `ref_sp_chr.bin` ← the `chr_bytes` block: 64 OBJ names, five character
  tokens at heights 10/12/14/18/22 px, colour index 1 only, plane 0 only.

**Not vendored, deliberately:** `sp_way.bin` (the AI waypoint loops) and the
four `sp_world_*.bin` scenario/instrument worlds. Nothing in this rail reads
them — the AI and the cycle instrument are a later stage — and a `rom` claim
declared ahead of its reader is exactly the `grad_tabs` shape
`make rom-unbacked` exists to refuse (docs/37). The rail's own cast
(`sh2_markers.bin`) is generated here rather than vendored, and is gated by
simulation rather than by an oracle; `marker_world` in the generator says why.

## Why these are a real oracle and not a tautology

`tools/gen_split_h_2p_assets.py` is a **self-contained re-implementation**. It
shares no code with the program that produced these bytes — it cannot, because
the build runs from a bare checkout with nothing but this tree on disk. It
re-derives the checker algebra and the perspective ramp from the descriptions
above and then **refuses to write anything that disagrees with these bytes**.

Stated precisely, because "self-contained" reads stronger than it is: this is a
**re-typing of the same algorithm at the same constants** — it catches
transcription error and drift, which is what a regression oracle is for, and it
is not an independent derivation of the geometry.

That is what makes the comparison worth running. These blobs came out of a
*different program* on a *different run*. If the two agree byte-for-byte across
32,768 + 448 + 448 bytes, the re-derivation reproduced the checker parity, the
stripe phase, the warm/cool split that is the rail's own position oracle, the
CHR tile ordering, the interleave, the hyperbolic ramp constants, the rounding
and the little-endian s8.8 packing — all of them, or the bytes would differ.

That is also why they are vendored rather than fetched. An asset check that
can only run where some other directory happens to exist is a check that never
runs; these bytes are in the tree, so this rail's asset ground truth runs
anywhere the repo does.
