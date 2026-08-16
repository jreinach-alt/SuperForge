#!/usr/bin/env python3
"""gen_jumper_assets.py — deterministic art + world for the `jumper` rail.

Emits (byte-identical on re-run, pure integer math):

  jr_bg_chr.bin    3 x 4bpp BG tiles, 32 B each = 96 B
                   tiles 0/1 EMPTY · tile 2 SOLID index 1 — the terrain keeps
                   tile id 2 (`sf_load_bg_tile 2`), so jr_flags[2] is the
                   entry `sf_tile_flags 2, SF_FLAG_SOLID` sets
  jr_bg_pal.bin    16 BGR555 words = 32 B  (group 0; word 0 IS the backdrop)
  jr_obj_chr.bin   2 x 4bpp OBJ tiles = 64 B   tile 0 EMPTY · tile 1 SOLID
                   index 1 (`sf_load_obj_tile 1`)
  jr_obj_pal.bin   16 BGR555 words = 32 B  (OBJ palette 0)
  jr_world.bin     1,024 B — the 32x32 world, one tile id per cell
  jr_flags.bin     256 B — tile id -> collision flag byte (entry 2 = 1)

THE TILE ART. Both drawn tiles are the same 32-byte pattern: eight `$FF,$00`
rows + sixteen `$00` bytes — a 4bpp tile whose every pixel is colour index 1,
exactly what encode_4bpp(SOLID_TILE) emits. Colours: OBJ_RED $001F (player),
BG_GREY $39CE (terrain).

THE WORLD IS FIVE mset LOOPS, ROW FOR ROW. The loops are level DESIGN — each
platform reachable from the one below, the overhang clear of platform 1's
takeoff window — so they are baked as data here and layout() below writes
them out loop bound for loop bound:

    ground    row 26, cols 0..31       (top px 208 -> rest y 200)
    plat1     row 22, cols 8..12       (top px 176 -> rest y 168)
    plat2     row 18, cols 15..19      (top px 144)
    plat3     row 14, cols 22..26      (top px 112)
    overhang  row 22, cols 28..30      (bottom px 183 -> bonk snap y 184)
    borders   cols 0 and 31, rows 0..25

One blob, two consumers: jumper_bg builds the VRAM tilemap from these bytes
at scene enter, col_map probes them — so the drawn terrain and the solid
terrain agree by construction (jumper_rom/feature.toml).

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): encode_4bpp asserts every
pixel index; the world writer asserts every cell holds a declared tile id.
"""
import sys
from pathlib import Path

OBJ_RED = 0x001F         # BGR555 pure red — the player
BG_GREY = 0x39CE         # BGR555 mid grey — the terrain

TILE_EMPTY = 0           # never drawn: index 0 renders as the backdrop
TILE_SOLID = 2           # the terrain tile id
FLAG_SOLID = 1           # bit 0 — sf_map.inc's SF_FLAG_SOLID

DIM = 32                 # the world is 32x32 tiles = 256x256 px

BG_PAL = [0x0000, BG_GREY] + [0x0000] * 14
OBJ_PAL = [0x0000, OBJ_RED] + [0x0000] * 14

EMPTY_TILE = [[0] * 8 for _ in range(8)]
SOLID_TILE = [[1] * 8 for _ in range(8)]


def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp. Asserts rather than masks."""
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    out = bytearray()
    for pair in (0, 2):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                assert 0 <= v <= 15, (
                    f"{label}: pixel ({x},{y}) index {v} outside 4bpp 0..15")
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


def layout():
    """The five terrain loops, written out bound for bound."""
    world = [[TILE_EMPTY] * DIM for _ in range(DIM)]
    for col in range(0, 32):            # @ground:  row 26, full width
        world[26][col] = TILE_SOLID
    for col in range(8, 13):            # @plat1:   row 22, cols 8..12
        world[22][col] = TILE_SOLID
    for col in range(15, 20):           # @plat2:   row 18, cols 15..19
        world[18][col] = TILE_SOLID
    for col in range(22, 27):           # @plat3:   row 14, cols 22..26
        world[14][col] = TILE_SOLID
    for col in range(28, 31):           # @overhang: row 22, cols 28..30
        world[22][col] = TILE_SOLID
    for row in range(0, 26):            # @border:  cols 0 + 31, rows 0..25
        world[row][0] = TILE_SOLID
        world[row][31] = TILE_SOLID
    return world


def encode_world(world):
    out = bytearray()
    for row in world:
        for cell in row:
            assert cell in (TILE_EMPTY, TILE_SOLID), (
                f"world cell holds undeclared tile id {cell}")
            out.append(cell)
    assert len(out) == DIM * DIM, f"world is {len(out)} B, expected {DIM*DIM}"
    return bytes(out)


def encode_flags():
    flags = bytearray(256)
    flags[TILE_SOLID] = FLAG_SOLID      # sf_tile_flags 2, SF_FLAG_SOLID
    return bytes(flags)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "jr_bg_chr.bin": encode_4bpp(EMPTY_TILE, "bg tile 0 (empty)")
                         + encode_4bpp(EMPTY_TILE, "bg tile 1 (pad)")
                         + encode_4bpp(SOLID_TILE, "bg tile 2 (terrain)"),
        "jr_bg_pal.bin": encode_pal(BG_PAL, "bg palette"),
        "jr_obj_chr.bin": encode_4bpp(EMPTY_TILE, "obj tile 0 (empty)")
                          + encode_4bpp(SOLID_TILE, "obj tile 1 (player)"),
        "jr_obj_pal.bin": encode_pal(OBJ_PAL, "obj palette"),
        "jr_world.bin": encode_world(layout()),
        "jr_flags.bin": encode_flags(),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
