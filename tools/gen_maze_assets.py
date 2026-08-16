#!/usr/bin/env python3
"""gen_maze_assets.py — deterministic room, flags, art + palettes for `maze`.

Emits (byte-identical on re-run, pure integer math):

  mz_room.bin      1024 B — the 32x32 byte tile-id map of the walled room.
                   THE rail's load-bearing blob: col_map binds it as its world
                   (CM_WORLD_BLOB) and maze_bg's enter loop renders it to the
                   BG1 tilemap, so the wall you see and the wall that blocks
                   are one byte (maze_rom/feature.toml).
  mz_flags.bin      256 B — tile id -> collision flag byte. Entry 2 = SOLID
                   (bit 0), everything else 0.
  mz_bg_chr.bin      96 B — 3 x 4bpp BG tiles: 0 floor (empty), 1 explicit
                   zero (unused), 2 WALL (solid colour index 1).
  mz_bg_pal.bin      32 B — BG palette group 0: word 0 backdrop black,
                   word 1 wall grey.
  mz_obj_chr.bin     32 B — 1 x 4bpp OBJ tile, solid index 1 (the player).
  mz_obj_pal.bin     32 B — OBJ palette 0: word 1 player red.

HOW THE ROOM IS BUILT:

* FOUR LOOPS, NOT A BITMAP — border rows 0 + 27 across cols 0..31 (@border_h,
  `cmp #32`), border cols 0 + 31 down rows 0..27 (@border_v, `cmp #28`),
  interior wall A at col 12 rows 1..13 (@wall_a, `lda #1` / `cmp #14`),
  interior wall B at row 18 cols 18..30 (@wall_b, `lda #18` / `cmp #31`). Rows
  28..31 exist in the 32x32 map but are off the 224 px screen and stay floor,
  which is what `gfxmode #1`'s shadow clear leaves them at anyway. Keeping the
  room AS loops rather than as a bitmap literal is what makes it editable: the
  bounds above are the knobs, and a reader can move a wall by moving a number.

* THE WALL IS TILE ID 2. The art loads at BG tile 2 (`sf_load_bg_tile 2,
  wall_tile`) and that id is the one flagged solid (`sf_tile_flags 2,
  SF_FLAG_SOLID`), so mz_flags reads as "entry 2 is the wall" and nothing else.
  Tile 1 is emitted as explicit zeros rather than skipped — every byte the
  ROM's CHR claim covers is a byte this generator wrote (rule 5's spirit).

* THE TILE ART. wall_tile and sprite_tile are the SAME 32-byte pattern: eight
  `$FF,$00` rows then sixteen zero bytes — a 4bpp tile whose every pixel is
  colour index 1. `encode_4bpp` must reproduce those bytes exactly, and
  tests/test_maze.py holds the destination VRAM to them. BG_GREY = $39CE is
  the wall, OBJ_RED = $001F the player.

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): encoders assert ranges
and name the offending pixel/entry; nothing is quietly truncated.
"""
import sys
from pathlib import Path

BG_GREY = 0x39CE         # BGR555 mid grey (walls)
OBJ_RED = 0x001F         # BGR555 pure red (player)

MAP_DIM = 32             # the BG1 tilemap is 32x32 cells (gfxmode #1)
TILE_FLOOR = 0           # never drawn: index 0 renders the backdrop
TILE_WALL = 2            # the solid-flagged tile id
FLAG_SOLID = 0x01        # bit 0 — SF_FLAG_SOLID


def build_room():
    """The four room loops, row-major bytes."""
    room = [[TILE_FLOOR] * MAP_DIM for _ in range(MAP_DIM)]
    for i in range(32):              # @border_h: top row 0 + bottom row 27
        room[0][i] = TILE_WALL
        room[27][i] = TILE_WALL
    for i in range(28):              # @border_v: left col 0 + right col 31
        room[i][0] = TILE_WALL
        room[i][31] = TILE_WALL
    for row in range(1, 14):         # @wall_a: vertical, col 12, rows 1..13
        room[row][12] = TILE_WALL
    for col in range(18, 31):        # @wall_b: horizontal, row 18, cols 18..30
        room[18][col] = TILE_WALL
    return bytes(room[r][c] for r in range(MAP_DIM) for c in range(MAP_DIM))


def build_flags():
    flags = bytearray(256)
    flags[TILE_WALL] = FLAG_SOLID
    return bytes(flags)


EMPTY_TILE = [[0] * 8 for _ in range(8)]
SOLID_TILE = [[1] * 8 for _ in range(8)]


def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3).

    Asserts rather than masks: an index outside 0..15 names its own pixel.
    """
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    out = bytearray()
    for pair in (0, 2):                      # planes 0/1, then planes 2/3
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                assert 0 <= v <= 15, (
                    f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
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
    files = {
        "mz_room.bin": build_room(),
        "mz_flags.bin": build_flags(),
        "mz_bg_chr.bin": encode_4bpp(EMPTY_TILE, "bg tile 0 (floor)")
                         + encode_4bpp(EMPTY_TILE, "bg tile 1 (unused)")
                         + encode_4bpp(SOLID_TILE, "bg tile 2 (wall)"),
        "mz_bg_pal.bin": encode_pal([0x0000, BG_GREY] + [0x0000] * 14,
                                    "bg palette"),
        "mz_obj_chr.bin": encode_4bpp(SOLID_TILE, "obj tile 0 (player)"),
        "mz_obj_pal.bin": encode_pal([0x0000, OBJ_RED] + [0x0000] * 14,
                                     "obj palette"),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
