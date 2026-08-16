#!/usr/bin/env python3
"""gen_sr_assets.py — deterministic art + level for the `scroll_run` rail.

Emits (byte-identical on re-run, pure integer math):

  sr_bg_chr.bin    4 x 4bpp BG tiles, 32 B each = 128 B
                   tile 0 EMPTY · tile 1 EMPTY (pad — nothing loads a BG
                   tile 1) · tile 2 SOLID index 1 (terrain grey) ·
                   tile 3 SOLID index 2 (goal gold)
  sr_bg_pal.bin    16 BGR555 words = 32 B  (BG palette group 0, CGRAM 0..15;
                   word 0 IS the backdrop — black; word 1 grey; word 2 gold)
  sr_obj_chr.bin   2 x 4bpp OBJ tiles = 64 B   tile 0 empty, tile 1 solid red
  sr_obj_pal.bin   16 BGR555 words = 32 B  (OBJ palette 0, CGRAM 128..143)
  sr_world.bin     2048 B — the 64x32 world: one tile id per cell. Rows 0..27
                   are the level, row for row; rows 28..31 are pad (tile 0) —
                   they sit below the 224 px screen and nothing ever writes
                   them
  sr_flags.bin     256 B — tile id -> collision flag byte (col_map's
                   CM_FLAGS). Entry 2 = $01 (bit 0, SOLID); entry 3 = $02
                   (bit 1 — `sf_tile_flags 3, $02`: the goal's own non-solid
                   flag. Bit 1 is also the one-way-platform bit, so the goal
                   pillar's top can be landed on from above but does not block
                   from the side)

THE TILE ART. Three tiles carry ink: terrain = eight `$FF,$00` rows + 16 zero
bytes (4bpp colour index 1), the sprite identical, goal = eight `$00,$FF`
rows + 16 zeros (colour index 2 — bitplane 1, so the goal is a different
palette entry with the same silhouette). test_scroll_run.py asserts the
destination VRAM against these blobs.

THE LEVEL is 28 rows x 64 tile-id bytes, laid out as a `.repeat` structure so
the run reads as a sequence of obstacles rather than as a bitmap. A
`* - level = 28 * 64` size guard becomes the len() assert below:

  rows 0..19   border cols 0/63 only
  row 20       + the SEAM platform cols 30..34 (crosses the page seam at 32!)
               + the tall pillar col 44 (its top row)
  row 21       + pillar col 44
  row 22       + pillar col 14, platforms cols 24..27 and 38..41, pillar 44
  row 23       + pillars cols 14, 44
  rows 24..25  + pillars 14/44 and the GOAL (tile 3) at col 60
  rows 26..27  solid floor, all 64 cols

Colours:
  OBJ_RED = $001F   BG_GREY = $39CE   BG_GOLD = $035F

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): encode_4bpp asserts every
pixel index is 0..15; the level builder asserts every row is exactly 64 cells
and every tile id has a flags entry. An author error stops the generator
naming the offending cell; it never quietly becomes a different tile.
"""
import sys
from pathlib import Path

OBJ_RED = 0x001F         # BGR555 pure red — the runner
BG_GREY = 0x39CE         # BGR555 mid grey — the terrain
BG_GOLD = 0x035F         # BGR555 gold — the goal pillar

BG_PAL = [0x0000, BG_GREY, BG_GOLD] + [0x0000] * 13
OBJ_PAL = [0x0000, OBJ_RED] + [0x0000] * 14

EMPTY_TILE = [[0] * 8 for _ in range(8)]
SOLID1_TILE = [[1] * 8 for _ in range(8)]    # every pixel index 1
SOLID2_TILE = [[2] * 8 for _ in range(8)]    # every pixel index 2

WORLD_W, WORLD_H = 64, 32    # tiles; rows 28..31 are pad (see header)
LEVEL_ROWS = 28


def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3)."""
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    out = bytearray()
    for y, row in enumerate(rows):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} px, expected 8"
        for x, v in enumerate(row):
            assert 0 <= v <= 15, (
                f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
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


def level_rows():
    """The level, row for row.

    Each row is built the way the .repeat blocks read, then asserted to 64
    cells — the whole-table size guard applied PER ROW, so a miscount names
    its row instead of shearing the rest of the map sideways.
    """
    def border(mid):
        return [2] + mid + [2]

    rows = []
    for _ in range(20):                          # rows 0..19: borders only
        rows.append(border([0] * 62))
    # row 20: seam platform cols 30..34 + pillar col 44
    rows.append(border([0] * 28 + [0] + [2] * 5 + [0] * 9 + [2] + [0] * 18))
    # row 21: pillar col 44
    rows.append(border([0] * 43 + [2] + [0] * 18))
    # row 22: pillar 14 + platform 24..27 + platform 38..41 + pillar 44
    rows.append(border([0] * 13 + [2] + [0] * 9 + [2] * 4 + [0] * 10
                       + [2] * 4 + [0] * 2 + [2] + [0] * 18))
    # row 23: pillars 14, 44
    rows.append(border([0] * 13 + [2] + [0] * 29 + [2] + [0] * 18))
    # rows 24..25: pillars 14/44 + the goal at col 60
    for _ in range(2):
        rows.append(border([0] * 13 + [2] + [0] * 29 + [2] + [0] * 15
                           + [3] + [0] * 2))
    for _ in range(2):                           # rows 26..27: solid floor
        rows.append([2] * 64)
    assert len(rows) == LEVEL_ROWS, f"level is {len(rows)} rows, want 28"
    for y, row in enumerate(rows):
        assert len(row) == WORLD_W, f"level row {y} is {len(row)} cells, want 64"
    # sanity: the cells the tests navigate by — the features of the run this
    # level exists to pose, asserted here so a bad edit names the feature
    assert rows[20][30:35] == [2] * 5, "seam platform (row 20 cols 30..34)"
    assert rows[22][24:28] == [2] * 4, "platform row 22 cols 24..27"
    assert rows[22][38:42] == [2] * 4, "platform row 22 cols 38..41"
    assert [rows[r][14] for r in range(22, 26)] == [2] * 4, "pillar col 14"
    assert [rows[r][44] for r in range(20, 26)] == [2] * 6, "pillar col 44"
    assert [rows[r][60] for r in (24, 25)] == [3, 3], "goal col 60"
    return rows


def world_blob():
    rows = level_rows()
    rows += [[0] * WORLD_W for _ in range(WORLD_H - LEVEL_ROWS)]  # pad 28..31
    flat = bytes(v for row in rows for v in row)
    assert len(flat) == WORLD_W * WORLD_H
    assert set(flat) <= {0, 2, 3}, "level holds a tile id with no CHR/flags"
    return flat


def flags_blob():
    flags = bytearray(256)
    flags[2] = 0x01              # SOLID (bit 0) — sf_tile_flags 2, SF_FLAG_SOLID
    flags[3] = 0x02              # GOAL/PLATFORM (bit 1) — sf_tile_flags 3, $02
    return bytes(flags)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "sr_bg_chr.bin": encode_4bpp(EMPTY_TILE, "bg tile 0 (empty)")
                         + encode_4bpp(EMPTY_TILE, "bg tile 1 (pad)")
                         + encode_4bpp(SOLID1_TILE, "bg tile 2 (terrain)")
                         + encode_4bpp(SOLID2_TILE, "bg tile 3 (goal)"),
        "sr_bg_pal.bin": encode_pal(BG_PAL, "bg palette"),
        "sr_obj_chr.bin": encode_4bpp(EMPTY_TILE, "obj tile 0 (empty)")
                          + encode_4bpp(SOLID1_TILE, "obj tile 1 (player)"),
        "sr_obj_pal.bin": encode_pal(OBJ_PAL, "obj palette"),
        "sr_world.bin": world_blob(),
        "sr_flags.bin": flags_blob(),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
