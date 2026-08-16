#!/usr/bin/env python3
"""gen_split_h_matrix_assets.py — the matrix-band PAIR's art, as .bin blobs.

ONE generator, TWO rails. `split_h_matrix_demo` and `split_h_persp3_demo`
want byte-identical checker maps (md5
`07a9125927a98955daa1445b2ffd2c2c` for both): the two differ in BAND COUNT and
in nothing else, art included. So both ROMs `.incbin` the blobs this file emits
and the shared `shm_rom` feature declares them once.

Emits into $(BUILD)/assets (deterministic, byte-identical on re-run):

    shm_map.bin       32,768 B  the interleaved Mode 7 VRAM blob — a 128x128
                                tilemap in the EVEN bytes, two solid 8bpp CHR
                                tiles in the ODD ones, exactly as the PPU
                                reads the Mode 7 region.
    shm_pal.bin            6 B  three BGR555 words, CGRAM indices 0..2.

THE WORLD, and why a 1x1-tile checker is the right oracle. Tile (row, col) is
`(row ^ col) & 1`, so the world is an 8x8-PIXEL checkerboard. Under a flat
top-down matrix `M7A = M7D = s`, `M7B = M7C = 0` one screen pixel steps
`s/256` world pixels, so the ON-SCREEN checker period is `8 * 256 / s`:

    s = $0100 (1.0)    ->  8 px
    s = $0080 (0.5)    -> 16 px
    s = $0040 (0.25)   -> 32 px

That period is a property of the RENDERED FRAME and of nothing else, which is
what makes "N distinct cameras over one world" a screenshot assertion rather
than a claim about a variable. It is also why the map must not be pretty: a
world with structure would let a test pass on a landmark instead of on the
scale.

THIS FILE IS ALSO A GATE. It refuses to write anything that disagrees with
the committed reference output under `vendor/art/split_h_matrix/` — so a drift
in either direction stops the build rather than rendering a world nobody
compared. An ABSENT oracle is a refusal too, not a warning: the sibling
generator once carried a "no oracle -> UNVERIFIED, exit 0" shape that emitted
blobs anyway, and this one starts where that one ended up.
"""
import argparse
import hashlib
import sys
from pathlib import Path

MAP_W = 128                     # world side, in tiles
TILE_BYTES = 64                 # one 8x8 8bpp tile

# COLOR_BACKDROP, COLOR_DARK_GREEN, COLOR_LIGHT_GREEN. Word 0 is BOTH palette
# index 0 and the Mode 7 backdrop slot — one owner, by hardware contract — so
# the muted blue-violet is what shows wherever the plane does not reach.
PALETTE = (0x5400, 0x01E0, 0x03E0)

ORACLE = Path(__file__).resolve().parent.parent / "vendor" / "art" / \
    "split_h_matrix" / "ref_checker_map.bin"


def build_map() -> bytes:
    """The interleaved Mode 7 blob: tilemap even, CHR odd.

    Derived from the algorithm stated in
    `vendor/art/split_h_matrix/README.md`, not copied from the oracle's
    bytes — the comparison below is what makes the derivation checkable
    rather than a second opinion.
    """
    tilemap = bytearray(MAP_W * MAP_W)
    for row in range(MAP_W):
        for col in range(MAP_W):
            tilemap[row * MAP_W + col] = (row ^ col) & 1
    chr_bytes = bytearray(MAP_W * MAP_W)
    # Tile 0 = solid palette index 1, tile 1 = solid palette index 2. Mode 7
    # is 8bpp with ABSOLUTE CGRAM indices, so a "tile" is 64 raw index bytes.
    chr_bytes[0:TILE_BYTES] = bytes([0x01]) * TILE_BYTES
    chr_bytes[TILE_BYTES:2 * TILE_BYTES] = bytes([0x02]) * TILE_BYTES
    out = bytearray(2 * MAP_W * MAP_W)
    out[0::2] = tilemap
    out[1::2] = chr_bytes
    return bytes(out)


def build_pal() -> bytes:
    out = bytearray()
    for word in PALETTE:
        out += bytes((word & 0xFF, (word >> 8) & 0xFF))
    return bytes(out)


def check_oracle(blob: bytes) -> str:
    """Refuse anything the committed reference blob disagrees with.

    Absence is a refusal, not a warning — see the module header.
    """
    if not ORACLE.exists():
        raise SystemExit(
            f"gen_split_h_matrix_assets: ORACLE MISSING at {ORACLE}. The "
            "ground-truth comparison is the one check in this generator that "
            "is not a tautology; emitting without it would ship a world "
            "nobody compared. Restore vendor/art/split_h_matrix/ (see its "
            "README for provenance).")
    ref = ORACLE.read_bytes()
    if blob != ref:
        first = next((i for i, (a, b) in enumerate(zip(blob, ref)) if a != b),
                     min(len(blob), len(ref)))
        raise SystemExit(
            "gen_split_h_matrix_assets: GENERATED MAP DISAGREES WITH THE REFERENCE ORACLE. "
            f"len {len(blob)} vs {len(ref)}, first difference at byte {first} "
            f"({blob[first:first + 1].hex()} vs {ref[first:first + 1].hex()}). "
            "Either the derivation drifted or the oracle did; both stop the "
            "build.")
    return hashlib.md5(ref).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("outdir", type=Path)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    blob = build_map()
    assert len(blob) == 0x8000, len(blob)
    digest = check_oracle(blob)
    (args.outdir / "shm_map.bin").write_bytes(blob)

    pal = build_pal()
    assert len(pal) == 2 * len(PALETTE), len(pal)
    (args.outdir / "shm_pal.bin").write_bytes(pal)

    print(f"shm_map.bin  {len(blob):6d} B  md5 {digest}  "
          f"(matches vendor/art/split_h_matrix/ref_checker_map.bin)")
    print(f"shm_pal.bin  {len(pal):6d} B  "
          + " ".join(f"${w:04X}" for w in PALETTE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
