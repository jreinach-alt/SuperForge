#!/usr/bin/env python3
"""gen_stomper_assets.py — deterministic world + art for the `stomper` rail.

Emits (byte-identical on re-run, pure integer math):

  st_world.bin    1024 B — 32x32 tile-id bytes: the arena, loop for
                  loop (tile 2 = solid terrain, 0 = empty)
  st_flags.bin    256 B  — tile-id -> collision flag table: [2] = 1 (SOLID
                  bit 0), everything else 0
  st_bg_chr.bin   3 x 4bpp BG tiles, 96 B — tiles 0/1 EMPTY (explicit — rule
                  5), tile 2 solid colour-index-1
  st_bg_pal.bin   16 BGR555 words = 32 B — BG group 0: word 0 backdrop black,
                  word 1 terrain grey
  st_obj_chr.bin  2 x 4bpp OBJ tiles, 64 B — tile 0 EMPTY, tile 1 solid
  st_obj_pal.bin  32 BGR555 words = 64 B — OBJ pal 0 word 1 player red,
                  OBJ pal 1 word 1 enemy magenta

HOW THE ARENA IS BUILT.

Four `mset` loops, kept as loops so the bounds stay the editable knobs:
    ground     row 26, all 32 columns          (@ground:  x 0..31, y 26)
    borders    columns 0 and 31, rows 0..25    (@border:  y 0..25)
    low walls  columns 10 and 20, rows 24..25  (@lowwalls: y 24..25)
    platform   row 20, columns 4..8            (@plat:    x 4..8)
All four write tile 2, and exactly that id is flagged solid
(`sf_tile_flags 2, SF_FLAG_SOLID`), which st_flags.bin mirrors.
Rows 27..31 stay empty (0) — they are below the 224 px screen.

The TILES: `terrain_tile` and `sprite_tile` are the SAME 32-byte pattern — eight
`$FF,$00` rows (bitplanes 0/1: every pixel colour index 1) then sixteen `$00`
bytes (bitplanes 2/3) — which is what encode_4bpp(SOLID) produces
byte-identically (the scroller generator's own fidelity check, same pattern).
Nothing draws tile 0/1 (or OBJ tile 0), so they could be left to whatever
`sf_coldstart` zeroed. Rule 5 forbids inheriting a cleared VRAM, so the empty
tiles are written EXPLICITLY here and uploaded with the rest.

The COLOURS:
    OBJ_RED   = $001F   player
    OBJ_MAGEN = $7C1F   enemies (magenta)
    BG_GREY   = $39CE   terrain
placed where its `sf_bg_color 0,1` / `sf_obj_color 0,1` / `sf_obj_color 1,1`
calls put them: BG group 0 word 1, OBJ palette 0 word 1, OBJ palette 1 word 1.

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): encode_4bpp asserts every
pixel index is 0..15 and encode_pal every entry is 15-bit; an out-of-range
author error stops the generator naming the offending pixel.
"""
import sys
from pathlib import Path

# --- the colour equates ----------
OBJ_RED = 0x001F
OBJ_MAGEN = 0x7C1F
BG_GREY = 0x39CE

# --- the level vocabulary ---------------------------------------------------
TILE_TERRAIN = 2         # sf_load_bg_tile 2 / mset ... #2 / sf_tile_flags 2
FLAG_SOLID = 1           # bit 0 (SF_FLAG_SOLID)

EMPTY_TILE = [[0] * 8 for _ in range(8)]
SOLID_TILE = [[1] * 8 for _ in range(8)]

BG_PAL = [0x0000, BG_GREY] + [0x0000] * 14
OBJ_PAL0 = [0x0000, OBJ_RED] + [0x0000] * 14      # player (attr palette 0)
OBJ_PAL1 = [0x0000, OBJ_MAGEN] + [0x0000] * 14    # enemies (attr palette 1)


def build_world():
    """The arena: @ground / @border / @lowwalls / @plat, loop for loop.
    32x32 bytes, row-major."""
    w = [[0] * 32 for _ in range(32)]
    for x in range(32):                    # @ground: row 26, every column
        w[26][x] = TILE_TERRAIN
    for y in range(26):                    # @border: columns 0 and 31
        w[y][0] = TILE_TERRAIN
        w[y][31] = TILE_TERRAIN
    for y in range(24, 26):                # @lowwalls: columns 10 and 20
        w[y][10] = TILE_TERRAIN
        w[y][20] = TILE_TERRAIN
    for x in range(4, 9):                  # @plat: row 20, columns 4..8
        w[20][x] = TILE_TERRAIN
    return bytes(b for row in w for b in row)


def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3).
    Asserts rather than masks: an index outside 0..15 names its own pixel."""
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    out = bytearray()
    for y, row in enumerate(rows):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} px, expected 8"
        for x, v in enumerate(row):
            assert 0 <= v <= 15, (
                f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
    for pair in (0, 2):                    # planes 0/1, then planes 2/3
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


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    flags = bytearray(256)
    flags[TILE_TERRAIN] = FLAG_SOLID
    files = {
        "st_world.bin": build_world(),
        "st_flags.bin": bytes(flags),
        "st_bg_chr.bin": encode_4bpp(EMPTY_TILE, "bg tile 0 (empty)")
                         + encode_4bpp(EMPTY_TILE, "bg tile 1 (empty)")
                         + encode_4bpp(SOLID_TILE, "bg tile 2 (terrain)"),
        "st_bg_pal.bin": encode_pal(BG_PAL, "bg palette"),
        "st_obj_chr.bin": encode_4bpp(EMPTY_TILE, "obj tile 0 (empty)")
                          + encode_4bpp(SOLID_TILE, "obj tile 1 (actor)"),
        "st_obj_pal.bin": encode_pal(OBJ_PAL0, "obj palette 0 (player)")
                          + encode_pal(OBJ_PAL1, "obj palette 1 (enemies)"),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
