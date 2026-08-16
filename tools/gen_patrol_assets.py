#!/usr/bin/env python3
"""gen_patrol_assets.py — deterministic art, palettes and LEVEL for `patrol`.

Emits (byte-identical on re-run, pure integer math):

  pat_bg_chr.bin    3 x 4bpp BG tiles, 32 B each = 96 B
                    tiles 0/1 EMPTY · tile 2 the terrain tile
  pat_bg_pal.bin    16 BGR555 words = 32 B  (BG group 0; word 0 IS the
                    backdrop slot — black)
  pat_obj_chr.bin   1 x 4bpp OBJ tile = 32 B   (the sprite tile)
  pat_obj_pal.bin   32 BGR555 words = 64 B  (OBJ palette 0: player red;
                    OBJ palette 1: enemy magenta — OAM attr $02)
  pat_map.bin       1,024 B — the 32x32 byte tile-id LEVEL map
  pat_flags.bin     256 B — tile id -> collision flag byte (entry 2 = $01)

THE TILES. The terrain tile and the sprite tile are the SAME 32-byte pattern —
eight `$FF,$00` rows (bitplanes 0/1) then sixteen `$00` bytes (planes 2/3), a
4bpp tile whose every pixel is colour index 1. Both are DERIVED here from that
pixel description and then CHECKED against the literal byte table below
(REFERENCE_TILE_BYTES), so a bug in the encoder cannot quietly redefine the
art: two independent statements of the same 32 bytes have to agree. The BG
puts the terrain art at tile id 2 (`sf_load_bg_tile 2`), so the map bytes are
the `mset` values directly, and tiles 0/1 are written explicitly as blanks
(rule 5 — every byte the feature reads is a byte the feature wrote).

THE COLOURS:
  OBJ_RED   = $001F   player
  OBJ_MAGEN = $7C1F   both enemies (OBJ palette 1 — attr $02)
  BG_GREY   = $39CE   terrain

THE LEVEL is four loops, kept AS LOOPS rather than baked to a bitmap so the
bounds stay the editable knobs — move a number, move a wall:
  @ground    row 26, all 32 cols            (the full-width floor)
  @border    cols 0 + 31, rows 0..25        (the side walls)
  @lowwalls  cols 10 + 20, rows 24..25      (16 px — jumpable; the ground
                                             enemy's beat runs between them)
  @plat      row 20, cols 4..8              (the floating platform the ledge
                                             enemy paces)
Rows 28..31 are empty padding: the level is 32x28 (one 224-line screen) but
col_map's world must be a power of two, so the map is 32x32 with the
off-screen rows blank. One blob, two consumers: patrol_bg renders these bytes
to the BG1 tilemap at enter, and the play scene binds the same bytes as
CM_WORLD_BLOB — the picture and the collision cannot drift.

THE FLAG TABLE is `sf_tile_flags 2, SF_FLAG_SOLID` as data:
entry 2 = $01, nothing else flagged.

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): `encode_4bpp` asserts
every pixel index is 0..15; `encode_pal` asserts 15-bit words; the level
builder asserts every cell it writes was still empty — the four loops are
disjoint by design (the borders stop at row 25, one row above the ground), and
an overlap would mean a loop bound was edited wrong.
"""
import sys
from pathlib import Path

OBJ_RED = 0x001F         # BGR555 pure red — the player
OBJ_MAGEN = 0x7C1F       # BGR555 magenta (OBJ palette 1 — the enemies)
BG_GREY = 0x39CE         # BGR555 mid grey — the terrain

TILE_TERRAIN = 2         # `sf_load_bg_tile 2, terrain_tile`

# The tile stated a second way, as literal bytes: the ground truth the derived
# encoding is held to, so encoder and art cannot drift together.
REFERENCE_TILE_BYTES = bytes(
    [0xFF, 0x00] * 8 + [0x00] * 16)

# --- palettes ----------------------------------------------------------------
BG_PAL = [0x0000, BG_GREY] + [0x0000] * 14            # group 0; word 0 = backdrop
OBJ_PAL = ([0x0000, OBJ_RED] + [0x0000] * 14          # OBJ palette 0 (player)
           + [0x0000, OBJ_MAGEN] + [0x0000] * 14)     # OBJ palette 1 (enemies)

EMPTY_TILE = [[0] * 8 for _ in range(8)]
SOLID_TILE = [[1] * 8 for _ in range(8)]

MAP_DIM = 32


def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3).

    Asserts rather than masks: an index outside 0..15 names its own pixel.
    """
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    for y, row in enumerate(rows):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} px, expected 8"
        for x, v in enumerate(row):
            assert 0 <= v <= 15, (
                f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
    out = bytearray()
    for pair in (0, 2):                      # planes 0/1, then planes 2/3
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                lo = (lo << 1) | ((v >> pair) & 1)
                hi = (hi << 1) | ((v >> (pair + 1)) & 1)
            out += bytes((lo, hi))
    assert len(out) == 32, f"{label}: encoded {len(out)} B, expected 32"
    return bytes(out)


def encode_pal(words, label):
    out = bytearray()
    for i, w in enumerate(words):
        assert 0 <= w <= 0x7FFF, (
            f"{label}: entry {i} value {w:#06x} is not a 15-bit BGR555 word")
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


def build_level():
    """The four mset loops, each with its own bounds."""
    grid = [[0] * MAP_DIM for _ in range(MAP_DIM)]

    def mset(x, y, tile):
        assert 0 <= x < MAP_DIM and 0 <= y < MAP_DIM, f"mset ({x},{y}) OOB"
        assert grid[y][x] == 0, (
            f"level cell ({x},{y}) written twice — the four loops are disjoint "
            f"by design, so an overlap means a bound was edited wrong")
        grid[y][x] = tile

    for mp_i in range(0, 32):                # @ground: row 26, cols 0..31
        mset(mp_i, 26, TILE_TERRAIN)
    for mp_i in range(0, 26):                # @border: cols 0 + 31, rows 0..25
        mset(0, mp_i, TILE_TERRAIN)
        mset(31, mp_i, TILE_TERRAIN)
    for mp_i in range(24, 26):               # @lowwalls: cols 10 + 20
        mset(10, mp_i, TILE_TERRAIN)
        mset(20, mp_i, TILE_TERRAIN)
    for mp_i in range(4, 9):                 # @plat: row 20, cols 4..8
        mset(mp_i, 20, TILE_TERRAIN)

    return bytes(b for row in grid for b in row)


def build_flags():
    flags = bytearray(256)
    flags[TILE_TERRAIN] = 0x01               # sf_tile_flags 2, SF_FLAG_SOLID
    return bytes(flags)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    solid = encode_4bpp(SOLID_TILE, "the solid tile")
    assert solid == REFERENCE_TILE_BYTES, (
        "the derived 4bpp encoding disagrees with the literal byte table above "
        "— the encoder and the art no longer describe the same tile")

    files = {
        "pat_bg_chr.bin": encode_4bpp(EMPTY_TILE, "bg tile 0 (empty)")
                          + encode_4bpp(EMPTY_TILE, "bg tile 1 (blank)")
                          + solid,
        "pat_bg_pal.bin": encode_pal(BG_PAL, "bg palette"),
        "pat_obj_chr.bin": solid,
        "pat_obj_pal.bin": encode_pal(OBJ_PAL, "obj palettes 0+1"),
        "pat_map.bin": build_level(),
        "pat_flags.bin": build_flags(),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
