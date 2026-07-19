#!/usr/bin/env python3
"""make_dungeon.py — authored SHORT MAZE Mode 7 dungeon floor for m7_dungeon.

Authors a 1024x1024 PNG on the 128x128 tile grid (the full Mode 7 plane) where:
  - A small HAND-AUTHORED MAZE (see MAZE below) occupies a bounded region; the
    rest of the plane is solid wall/void. The maze is a clear START->GOAL path with
    a few turns and two dead-ends.
  - FLOOR is a two-tone checker — a strong MOTION CUE so the rotation + the
    scrolling pivot read clearly under the centred hero.
  - The GOAL cell is painted a DISTINCT colour so the destination reads on screen.
A distinct warm WALL colour makes the orientation obvious under rotation.

The single `is_wall(tx,ty)` predicate is the SINGLE SOURCE OF TRUTH for BOTH the
rendered wall ART and the world-space collision LUT — so "what you see is what
blocks you" by construction. S3 indexes the emitted terrain table by world tile.
(The GOAL is purely visual — it is walkable floor, so collision treats it as 0.)

Outputs (committed):
    dungeon.png             authored source image (1024x1024) — reference only
    dungeon_map.bin         32768-byte interleaved Mode 7 VRAM blob (BANK1)
    dungeon_palette.inc     ca65 CGRAM data (dungeon_pal + DUNGEON_PAL_COUNT)
    dungeon_terrain.bin     16384-byte world terrain table, row-major [ty*128+tx]
                            (1 = solid/wall, 0 = floor/walkable) — S3 collision LUT

Regenerate (from the materialized kit root, PYTHONPATH=.):
    PYTHONPATH=. python3 templates/m7_dungeon/assets/make_dungeon.py
"""
from __future__ import annotations

import sys
import struct
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

# --- colours (RGB) — camelot-dungeon stone theme (Wave-D dressing) ------------
# camelot_ ships CHARACTER sheets only (no tileset), so the painter AUTHORS the
# stone texture; the palette evokes the pack's medieval-dungeon theme: cool
# blue-grey flagstone floor, warm brown brick walls, a green exit. The 2-tone
# checker is KEPT as the rotation MOTION CUE (the rail's whole point), enriched
# with a third mortar/seam tone per surface for a flagstone/brick read.
# Palette discipline: floor stays COOL (b>r) and DARK, walls stay WARM (r>b) and
# below r=205 (so the demon enemy's bright orange r>=205 separates by brightness),
# goal stays GREEN — a clean 4-way split floor/wall/enemy/hero. CGRAM idx0=FLOOR_A.
FLOOR_A = (32, 40, 64)     # flagstone dark   -> reserved to CGRAM index 0
FLOOR_B = (72, 92, 132)    # flagstone light  (motion cue)
FLOOR_M = (52, 64, 96)     # flagstone mortar/seam (mid cool tone)
WALL    = (144, 92, 60)    # brick body   (warm brown)
WALL_LT = (184, 120, 84)   # brick face highlight (r<205, warm)
WALL_MO = (104, 64, 44)    # brick mortar (dark warm seam)
GOAL    = (88, 196, 116)   # GOAL floor (distinct GREEN — reads as the destination)
GOAL_LT = (150, 232, 176)  # GOAL highlight (checker light variant)

# =============================================================================
# AUTHORED MAZE — a SHORT, SIMPLE maze on a logical CELL grid. Each char:
#   '#' = wall cell, '.' = floor cell, 'S' = start, 'G' = goal, 'D' = dead-end.
# Each logical cell expands to CELL=3 floor tiles surrounded by WALL=2-tile-thick
# walls, so on the world tile grid corridors are 24px wide (comfortable for the
# 8px-footprint hero) and wall bands are 16px thick. The maze top-left wall sits
# at world tile (ORIGIN_TX, ORIGIN_TY); everything outside the maze = solid void.
#
# Solution (3 turns): S runs RIGHT along the top, turns DOWN the centre column,
# turns RIGHT, then DOWN into the GOAL (SE). Two dead-ends branch off: an NE
# pocket (top-right) and a W pocket (left side).
# =============================================================================
MAZE = [
    "#########",
    "#S....#D#",
    "#####.#.#",
    "#D..#.#.#",
    "###.#.#.#",
    "#...#...#",
    "#.#####.#",
    "#.....#G#",
    "#########",
]
CELL = 3                   # floor tiles per cell edge (24px corridors)
WALL_T = 2                 # wall thickness between/around cells (16px bands)
PITCH = CELL + WALL_T      # world tiles per logical cell step
ORIGIN_TX = 6              # world tile of the maze top-left wall
ORIGIN_TY = 6
ROWS = len(MAZE)
COLS = len(MAZE[0])


def _cell(cx: int, cy: int) -> str:
    """Logical cell char, normalised: '#' for wall, '.' for any walkable cell."""
    if 0 <= cy < ROWS and 0 <= cx < COLS:
        ch = MAZE[cy][cx]
        return '#' if ch == '#' else '.'
    return '#'


def is_wall(tx: int, ty: int) -> bool:
    """World-space wall predicate — the single source of truth for the art (and
    the collision terrain table). Maps a world tile back to a logical maze cell +
    sub-position; the WALL_T-thick borders join adjacent floor cells into open
    corridors so the maze reads as continuous passages."""
    rx, ry = tx - ORIGIN_TX, ty - ORIGIN_TY
    if rx < 0 or ry < 0:
        return True
    cx, sx = divmod(rx, PITCH)
    cy, sy = divmod(ry, PITCH)
    if cx >= COLS or cy >= ROWS:
        return True
    if _cell(cx, cy) == '#':
        return True
    in_bx = sx < WALL_T       # leading X border of this cell
    in_by = sy < WALL_T       # leading Y border of this cell
    if not in_bx and not in_by:
        return False          # interior floor body
    if in_bx and not in_by:   # left border: open iff the W neighbour is floor
        return _cell(cx - 1, cy) == '#'
    if in_by and not in_bx:   # top border: open iff the N neighbour is floor
        return _cell(cx, cy - 1) == '#'
    # corner border: open only if W, N AND NW neighbours are all floor
    return not (_cell(cx - 1, cy) != '#' and _cell(cx, cy - 1) != '#'
                and _cell(cx - 1, cy - 1) != '#')


def is_goal(tx: int, ty: int) -> bool:
    """Is this world tile inside the GOAL cell's floor body? (Visual marker only —
    the goal is walkable floor; collision treats it as 0.)"""
    for cy in range(ROWS):
        for cx in range(COLS):
            if MAZE[cy][cx] == 'G':
                bx = ORIGIN_TX + cx * PITCH + WALL_T
                by = ORIGIN_TY + cy * PITCH + WALL_T
                return bx <= tx < bx + CELL and by <= ty < by + CELL
    return False


def cell_world_center(ch: str):
    """World tile + pixel centre of the floor body of the cell tagged `ch`."""
    for cy in range(ROWS):
        for cx in range(COLS):
            if MAZE[cy][cx] == ch:
                tx = ORIGIN_TX + cx * PITCH + WALL_T + CELL // 2
                ty = ORIGIN_TY + cy * PITCH + WALL_T + CELL // 2
                return (tx, ty), (tx * 8 + 4, ty * 8 + 4)
    return None, None


def tile_color(tx: int, ty: int):
    """Per-tile stone colour. The BOLD 2-tile checker (light/dark) is kept as the
    rotation motion cue; a third mortar/seam tone is laid on a sparse diagonal so
    the surfaces read as flagstone / brick without adding sub-tile detail that
    would shimmer at Mode 7 scale (every colour is a whole 8px tile)."""
    seam = ((tx + ty) & 3) == 0                      # sparse diagonal mortar/seam
    if is_wall(tx, ty):
        if seam:
            return WALL_MO                           # brick mortar joint
        return WALL_LT if not (tx & 1) or not (ty & 1) else WALL
    if is_goal(tx, ty):
        return GOAL_LT if ((tx >> 1) ^ (ty >> 1)) & 1 else GOAL
    if seam:
        return FLOOR_M                               # flagstone seam
    return FLOOR_B if ((tx >> 1) ^ (ty >> 1)) & 1 else FLOOR_A


def build_png(path: Path) -> None:
    img = Image.new("RGB", (1024, 1024))
    px = img.load()
    for ty in range(128):
        for tx in range(128):
            c = tile_color(tx, ty)
            for py in range(8):
                for pxi in range(8):
                    px[tx * 8 + pxi, ty * 8 + py] = c
    img.save(path)
    print(f"wrote {path}")


def build_terrain() -> bytes:
    """128x128 world terrain byte table, row-major [ty*128+tx], from the SAME
    is_wall() predicate that paints the art: 1 = solid/wall, 0 = floor/walkable.
    This is the world-space collision LUT the S3 ASM indexes by world tile."""
    out = bytearray(128 * 128)
    for ty in range(128):
        for tx in range(128):
            out[ty * 128 + tx] = 1 if is_wall(tx, ty) else 0
    return bytes(out)


def reserve_backdrop(tile_data: bytes, palette: bytes):
    """Force CGRAM index 0 to FLOOR_A (the Mode 7 backdrop slot), remapping any
    tile pixel that landed on index 0 to a freshly appended duplicate colour."""
    from toolchain.mode7_assets import rgb_to_bgr555
    want = rgb_to_bgr555(*FLOOR_A)
    idx0 = struct.unpack_from("<H", palette, 0)[0]
    if idx0 == want:
        return tile_data, palette
    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    free = used
    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:
            td[i] = free
    pal = bytearray(palette)
    struct.pack_into("<H", pal, free * 2, idx0)
    struct.pack_into("<H", pal, 0, want)
    return bytes(td), bytes(pal)


def main() -> None:
    try:
        from toolchain.mode7_map_converter import convert_map_png
        from toolchain.mode7_assets import interleave_mode7_data
    except ImportError:
        sys.exit("toolchain/ not importable — run from kit root with PYTHONPATH=.")

    png = HERE / "dungeon.png"
    build_png(png)

    tile_data, tilemap, palette = convert_map_png(str(png))
    tile_data, palette = reserve_backdrop(tile_data, palette)
    blob = interleave_mode7_data(tilemap, tile_data)
    assert len(blob) == 0x8000, len(blob)
    (HERE / "dungeon_map.bin").write_bytes(blob)
    print(f"wrote dungeon_map.bin ({len(blob)} bytes)")

    terrain = build_terrain()
    assert len(terrain) == 16384, len(terrain)
    (HERE / "dungeon_terrain.bin").write_bytes(terrain)
    print(f"wrote dungeon_terrain.bin ({len(terrain)} bytes)")

    used = max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1
    lines = [
        "; dungeon_palette.inc — GENERATED (make_dungeon.py). CGRAM idx0 = floor.",
        "dungeon_pal:",
    ]
    for i in range(used):
        word = palette[i * 2] | (palette[i * 2 + 1] << 8)
        lines.append(f"    .word ${word:04X}    ; colour {i}")
    lines += ["", f"DUNGEON_PAL_COUNT = {used}", ""]
    (HERE / "dungeon_palette.inc").write_text("\n".join(lines))
    print(f"wrote dungeon_palette.inc ({used} colours)")

    (s_tile, s_px) = cell_world_center('S')
    (g_tile, g_px) = cell_world_center('G')
    print(f"maze START cell-centre world tile {s_tile} px {s_px}")
    print(f"maze GOAL  cell-centre world tile {g_tile} px {g_px}")


if __name__ == "__main__":
    main()
