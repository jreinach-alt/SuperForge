#!/usr/bin/env python3
"""gen_m7_dungeon_assets.py — the m7_dungeon rail's art, as .bin blobs.

Emits into $(BUILD)/assets (deterministic, byte-identical on re-run):

    m7dg_map.bin        32,768 B  interleaved Mode 7 VRAM blob
                                  (tilemap in even bytes, 8bpp CHR in odd)
    m7dg_tilemap.bin    16,384 B  the SAME tile ids, PACKED — what col_map reads
    m7dg_pal.bin           18 B   the floor/wall/goal CGRAM palette, BGR555 LE
    m7dg_flags.bin        256 B   tile id -> collision flag, 1 = solid
    m7dg_hero_chr.bin     576 B   18-tile 4bpp OBJ grid, the plan-view knight
    m7dg_hero_pal.bin      32 B   16 BGR555 words, OBJ palette
    m7dg_enemy_chr.bin    576 B   the plan-view slime
    m7dg_enemy_pal.bin     32 B
    m7dg_win_chr.bin      576 B   the gold sparkle-star win card
    m7dg_win_pal.bin       32 B

SELF-CONTAINED BY REQUIREMENT. The build runs from a bare checkout with
nothing but this tree on disk, so this file imports nothing and names no path
outside the repo. The maze predicate, the tile-dedup converter and the Mode 7
interleave are all derived here from the descriptions in
`vendor/art/m7_dungeon/README.md`.

...which is what makes `vendor/art/m7_dungeon/` a real oracle rather than an
echo: those blobs came out of a different program on a different run, and this
generator REFUSES to write anything that disagrees with them. See that
directory's README.

THE SINGLE SOURCE OF TRUTH is `is_wall(tx, ty)`. It paints the wall art AND
classifies collision, so "what you see is what blocks you" holds by
construction rather than by a second table someone has to keep in sync.

WHAT SHIPS IS THE 256-BYTE FLAG TABLE, not the 16,384-byte terrain array.
Solidity turns out to be a perfect function of tile id (8 distinct ids, 0
conflicts), so a flag table over the tilemap already in ROM answers every query
bit-identically for 64x fewer bytes. The terrain array is still
BUILT here, as an intermediate, for exactly one reason: comparing it to the
vendored `ref_dungeon_terrain.bin` is what proves this `is_wall()` is the same
predicate, cell for cell, independently of anything the converter does.

...AND a 16,384-byte PACKED TILE-ID MAP alongside it, which is
the honest correction to the sentence above. `col_map` computes
`offset = ty * W + tx` — PACKED bytes. The Mode 7 blob is INTERLEAVED (tilemap
in the even bytes, CHR in the odd), so the probe cannot read it: it would fetch
a CHR byte for every second tile. So the rail ships BOTH the 256-byte flag
table and a 16 KB packed tile-id map, and the total is 16,640 B against the
16,384 B of a plain terrain array — 256 bytes MORE, not 64x fewer.

The saving the flag table was measured to offer is real but UNREALISED here,
and the only thing that would realise it is a col_map that reads the
interleaved blob at stride 2 — a further engine change deliberately NOT taken
in this slice. What the flag table does still buy is the invariant below: the
map that draws the wall and the map that blocks you are ONE array, so they
cannot drift.

The indirection introduces exactly one hazard, and it is guarded rather than
hoped: `flag_table()` asserts at generation time that no tile id is solid at one
world cell and floor at another. A future re-theme whose dedup collapses a wall
tile and a floor tile into one art tile then FAILS THE BUILD instead of shipping
a silent hole in a wall.

Run:
    python3 tools/gen_m7_dungeon_assets.py build/assets
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENDOR = REPO / "vendor" / "art" / "m7_dungeon"

WORLD_T = 128                    # world side, tiles — the full Mode 7 plane
TILE_PX = 8
TERRAIN_BYTES = WORLD_T * WORLD_T
BLOB_BYTES = 2 * TERRAIN_BYTES

# --- colours (RGB), the camelot-dungeon stone theme --------------------------
# Cool dark flagstone floor, warm brick walls, a green exit. The 2-tone checker
# is the ROTATION MOTION CUE — without it a spinning floor of one colour reads
# as a still image. A third mortar tone per surface gives the flagstone/brick
# read without sub-tile detail that would shimmer at Mode 7 magnification
# (every colour here is a whole 8px tile).
#
# The band discipline is load-bearing for the rail's colour tests, so it is
# stated: floor stays COOL (b > r) and DARK; walls stay WARM (r > b) and below
# r = 205, so the enemy's bright orange (r >= 205) separates from brick by
# brightness alone; goal stays GREEN. Floor / wall / enemy / hero is then a
# clean four-way split no sampler can confuse.
FLOOR_A = (32, 40, 64)      # flagstone dark    -> reserved to CGRAM index 0
FLOOR_B = (72, 92, 132)     # flagstone light   (the motion cue)
FLOOR_M = (52, 64, 96)      # flagstone mortar/seam
WALL = (144, 92, 60)        # brick body
WALL_LT = (184, 120, 84)    # brick face highlight  (r < 205)
WALL_MO = (104, 64, 44)     # brick mortar
GOAL = (88, 196, 116)       # goal floor — the destination reads green
GOAL_LT = (150, 232, 176)   # goal highlight

# --- the authored maze -------------------------------------------------------
# A logical CELL grid. '#' wall, '.' floor, 'S' start, 'G' goal, 'D' dead-end.
# Each cell expands to CELL=3 floor tiles inside WALL_T=2-thick walls, so
# corridors are 24 px wide (roomy for the 8 px hero footprint) and wall bands
# are 16 px thick. Everything outside the maze is solid void.
#
# Solution, three turns: S runs RIGHT along the top, turns DOWN the centre
# column, turns RIGHT, then DOWN into the GOAL at the SE. Two dead-ends branch
# off — an NE pocket and a W pocket — so the maze is a maze and not a corridor.
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
CELL = 3                     # floor tiles per cell edge
WALL_T = 2                   # wall thickness between/around cells
PITCH = CELL + WALL_T        # world tiles per logical cell step
ORIGIN_TX = 6                # world tile of the maze top-left wall
ORIGIN_TY = 6
ROWS = len(MAZE)
COLS = len(MAZE[0])


def _cell(cx: int, cy: int) -> str:
    """The logical cell char, normalised to '#' or '.'. Out of bounds is wall,
    which is what makes the maze a bounded island in a solid plane."""
    if 0 <= cy < ROWS and 0 <= cx < COLS:
        return "#" if MAZE[cy][cx] == "#" else "."
    return "#"


def is_wall(tx: int, ty: int) -> bool:
    """The world-space wall predicate — the SINGLE SOURCE OF TRUTH for both the
    rendered wall art and the collision classification.

    A world tile maps back to a logical cell plus a sub-position inside it. The
    WALL_T-thick leading borders are the interesting part: a border is OPEN
    (floor) exactly when the neighbour it faces is floor, which is what joins
    adjacent floor cells into continuous corridors instead of leaving each cell
    walled off in its own box. The corner border needs all three of W, N and NW
    open, or the diagonal would cut a hole between two corridors that only touch
    at a point."""
    rx, ry = tx - ORIGIN_TX, ty - ORIGIN_TY
    if rx < 0 or ry < 0:
        return True
    cx, sx = divmod(rx, PITCH)
    cy, sy = divmod(ry, PITCH)
    if cx >= COLS or cy >= ROWS:
        return True
    if _cell(cx, cy) == "#":
        return True
    in_bx = sx < WALL_T          # leading X border of this cell
    in_by = sy < WALL_T          # leading Y border of this cell
    if not in_bx and not in_by:
        return False             # interior floor body
    if in_bx and not in_by:      # left border: open iff the W neighbour is floor
        return _cell(cx - 1, cy) == "#"
    if in_by and not in_bx:      # top border: open iff the N neighbour is floor
        return _cell(cx, cy - 1) == "#"
    return not (_cell(cx - 1, cy) != "#" and _cell(cx, cy - 1) != "#"
                and _cell(cx - 1, cy - 1) != "#")


def is_goal(tx: int, ty: int) -> bool:
    """Is this world tile inside the GOAL cell's floor body?

    Visual marker ONLY — the goal is walkable floor and collision treats it as
    0. That is deliberate: a goal you cannot walk into is not a goal."""
    for cy in range(ROWS):
        for cx in range(COLS):
            if MAZE[cy][cx] == "G":
                bx = ORIGIN_TX + cx * PITCH + WALL_T
                by = ORIGIN_TY + cy * PITCH + WALL_T
                return bx <= tx < bx + CELL and by <= ty < by + CELL
    return False


def cell_world_center(ch: str):
    """World tile + pixel centre of the floor body of the cell tagged `ch`.
    The rail's spawn and goal coordinates come from here, not from a literal."""
    for cy in range(ROWS):
        for cx in range(COLS):
            if MAZE[cy][cx] == ch:
                tx = ORIGIN_TX + cx * PITCH + WALL_T + CELL // 2
                ty = ORIGIN_TY + cy * PITCH + WALL_T + CELL // 2
                return (tx, ty), (tx * TILE_PX + 4, ty * TILE_PX + 4)
    return None, None


def tile_color(tx: int, ty: int):
    """The whole-tile colour at a world tile. Every tile is one flat colour, so
    the converter's dedup below collapses the 16,384-tile plane to one tile per
    distinct colour — which is why the tileset is 8 tiles and not 8,000."""
    seam = ((tx + ty) & 3) == 0                    # sparse diagonal mortar
    if is_wall(tx, ty):
        if seam:
            return WALL_MO
        return WALL_LT if not (tx & 1) or not (ty & 1) else WALL
    if is_goal(tx, ty):
        return GOAL_LT if ((tx >> 1) ^ (ty >> 1)) & 1 else GOAL
    if seam:
        return FLOOR_M
    return FLOOR_B if ((tx >> 1) ^ (ty >> 1)) & 1 else FLOOR_A


def terrain() -> bytes:
    """The 128x128 world terrain array, row-major [ty*128+tx], 1 = solid.

    NOT A SHIPPED ARTEFACT — see the module docstring. This exists so the
    predicate can be compared against the vendored terrain array, cell for
    cell, without the tile-dedup converter in the way."""
    out = bytearray(TERRAIN_BYTES)
    for ty in range(WORLD_T):
        for tx in range(WORLD_T):
            out[ty * WORLD_T + tx] = 1 if is_wall(tx, ty) else 0
    return bytes(out)


# =============================================================================
# The Mode 7 map converter, self-contained.
#
# The conversion this reproduces runs over a 1024x1024 RGB PNG that an
# authoring step paints first.
# THE PNG IS ELIDED HERE and the pixel source is read straight from
# tile_color(): the authoring step paints flat 8x8 blocks, so
#   pixel(x, y) == tile_color(x // 8, y // 8)
# identically, and a round trip through a lossless RGB PNG cannot change that.
# Dropping it removes a Pillow dependency from a CI-critical path and removes
# an intermediate file that nothing reads. `--png` still writes it, for looking
# at; the byte-identity gate below is what proves the elision was sound.
# =============================================================================

def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    """8-bit RGB -> the hardware's 0bbbbbgggggrrrrr word. Truncating (>> 3),
    not rounding: matching the source converter matters more than being
    marginally more accurate, and the two differ on real colours."""
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def convert_map() -> tuple[bytes, bytes, bytes]:
    """Tile-dedup the 128x128 plane. Returns (tile_data, tilemap, palette).

    Scan order is row-major over tiles and row-major over pixels within a tile,
    and BOTH the palette and the tileset are indexed by first appearance in that
    order. That is not a detail — it is the whole of why the emitted tile ids
    and colour indices are what they are, and any reordering here changes every
    byte downstream.

    `tile_data` is padded to the full 256 tiles (16,384 B) because the
    interleave wants one CHR byte per tilemap byte; the pad is never referenced
    by the tilemap."""
    color_map: dict[tuple[int, int, int], int] = {}
    palette_rgb: list[tuple[int, int, int]] = []
    unique_tiles: dict[tuple[int, ...], int] = {}
    tile_pixel_data: list[list[int]] = []
    tilemap: list[int] = []

    for ty in range(WORLD_T):
        for tx in range(WORLD_T):
            indices = []
            for _py in range(TILE_PX):
                for _px in range(TILE_PX):
                    color = tile_color(tx, ty)
                    if color not in color_map:
                        if len(palette_rgb) >= 256:
                            raise ValueError("more than 256 unique colours")
                        color_map[color] = len(palette_rgb)
                        palette_rgb.append(color)
                    indices.append(color_map[color])

            key = tuple(indices)
            if key not in unique_tiles:
                if len(unique_tiles) >= 256:
                    raise ValueError(f"more than 256 unique tiles at ({tx},{ty})")
                unique_tiles[key] = len(unique_tiles)
                tile_pixel_data.append(indices)
            tilemap.append(unique_tiles[key])

    tile_data = bytearray()
    for tile in tile_pixel_data:
        tile_data.extend(tile)
    while len(tile_data) < TERRAIN_BYTES:      # pad to 256 tiles x 64 B
        tile_data.append(0)

    palette = bytearray()
    for i in range(256):
        bgr = rgb_to_bgr555(*palette_rgb[i]) if i < len(palette_rgb) else 0
        palette += struct.pack("<H", bgr)

    return bytes(tile_data), bytes(tilemap), bytes(palette)


def palette_used(palette: bytes) -> int:
    """How many CGRAM entries are live. Index 0 always counts; above it, the
    highest non-zero word wins. (A colour whose BGR555 word is literally $0000
    would be miscounted — none is, and the byte-identity gate would catch it.)"""
    return max(i for i in range(256)
               if i == 0 or palette[i * 2] or palette[i * 2 + 1]) + 1


def reserve_backdrop(tile_data: bytes, palette: bytes) -> tuple[bytes, bytes]:
    """Force CGRAM index 0 to FLOOR_A.

    CGRAM word 0 is the Mode 7 BACKDROP — the colour the PPU shows wherever the
    plane does not cover the screen. Leaving whatever colour happened to be
    scanned first (here the wall mortar, at world tile 0,0) means the floor
    shows through as brick at the plane edges. So index 0 is claimed for the
    floor, and the colour evicted from it is appended as a fresh duplicate at
    the end so no pixel that referenced it changes appearance."""
    want = rgb_to_bgr555(*FLOOR_A)
    idx0 = struct.unpack_from("<H", palette, 0)[0]
    if idx0 == want:
        return tile_data, palette
    free = palette_used(palette)
    td = bytearray(tile_data)
    for i, b in enumerate(td):
        if b == 0:
            td[i] = free
    pal = bytearray(palette)
    struct.pack_into("<H", pal, free * 2, idx0)
    struct.pack_into("<H", pal, 0, want)
    return bytes(td), bytes(pal)


def interleave(tilemap: bytes, tile_data: bytes) -> bytes:
    """[map[0], chr[0], map[1], chr[1], ...] — the 32,768 B Mode 7 VRAM blob.

    Mode 7 VRAM is read as words whose LOW byte is the tilemap entry and whose
    HIGH byte is the CHR pixel. Interleaving at build time means the upload is
    one DMA instead of a CPU loop (or two DMAs with a stride)."""
    if len(tilemap) != TERRAIN_BYTES or len(tile_data) != TERRAIN_BYTES:
        raise ValueError(f"want {TERRAIN_BYTES} B each, got "
                         f"{len(tilemap)} and {len(tile_data)}")
    out = bytearray(BLOB_BYTES)
    out[0::2] = tilemap
    out[1::2] = tile_data
    return bytes(out)


def build_map() -> tuple[bytes, bytes, bytes]:
    """(interleaved 32,768 B blob, tilemap, used-colours-only palette)."""
    tile_data, tilemap, palette = convert_map()
    tile_data, palette = reserve_backdrop(tile_data, palette)
    blob = interleave(tilemap, tile_data)
    return blob, tilemap, palette[:palette_used(palette) * 2]


# =============================================================================
# The collision flag table — 256 B instead of 16,384 B, and the guard that
# makes the trade safe.
# =============================================================================

class TileFlagConflict(ValueError):
    """A tile id is solid at one world cell and floor at another."""


def flag_table(tilemap: bytes, terr: bytes) -> bytes:
    """tile id -> 1 (solid) / 0 (floor), 256 bytes, derived from the rendered
    tilemap and the terrain the SAME predicate produced.

    THE ASSERT IS THE POINT. The 64x saving over a per-cell array is only
    available because solidity happens to be a function of tile id — the art
    dedup never collapsed a wall tile and a floor tile into one. Nothing
    guarantees that stays true: a re-theme that made, say, a seam wall tile and
    a seam floor tile identical pixels would merge them, and then ONE flag has
    to answer for both. Whichever way it answered, the map would ship a wall
    you can walk through or a patch of floor you cannot.

    So the conflict is refused here, loudly, at build time, naming the tile and
    a world cell of each kind — rather than discovered by a player."""
    if len(tilemap) != TERRAIN_BYTES or len(terr) != TERRAIN_BYTES:
        raise ValueError(f"want {TERRAIN_BYTES} B each, got "
                         f"{len(tilemap)} and {len(terr)}")

    witness: dict[int, dict[int, int]] = {}       # tile -> flag -> cell index
    for cell, tid in enumerate(tilemap):
        witness.setdefault(tid, {}).setdefault(terr[cell], cell)

    conflicts = sorted(t for t, seen in witness.items() if len(seen) > 1)
    if conflicts:
        lines = ["m7_dungeon collision flag table: solidity is NOT a function "
                 "of tile id, so a 256-byte flag table CANNOT represent this "
                 "map. The art dedup has collapsed a wall tile and a floor "
                 "tile into one tile id:"]
        for tid in conflicts:
            seen = witness[tid]
            where = []
            for flag in sorted(seen):
                c = seen[flag]
                where.append(f"{'solid' if flag else 'floor '} at world tile "
                             f"({c % WORLD_T},{c // WORLD_T})")
            lines.append(f"  tile id {tid}: " + " AND ".join(where))
        lines.append("Fix the art so the two surfaces differ in at least one "
                     "pixel, or ship the full 16,384-byte terrain array "
                     "instead of the flag table.")
        raise TileFlagConflict("\n".join(lines))

    flags = bytearray(256)
    for tid, seen in witness.items():
        flags[tid] = next(iter(seen))
    return bytes(flags)


def assert_flags_equivalent(flags: bytes, tilemap: bytes, terr: bytes) -> None:
    """flags[tilemap[cell]] == terr[cell] at every one of the 16,384 world
    cells. With zero conflicts this is implied — but "implied" is what the
    build is being asked to prove, and the check costs milliseconds."""
    for cell in range(TERRAIN_BYTES):
        if flags[tilemap[cell]] != terr[cell]:
            raise AssertionError(
                f"flag table disagrees with the terrain at world tile "
                f"({cell % WORLD_T},{cell // WORLD_T}): tile id "
                f"{tilemap[cell]} -> flag {flags[tilemap[cell]]}, "
                f"terrain says {terr[cell]}")


def write_png(path: Path) -> None:
    """The authored 1024x1024 source image — reference only, never read back.
    Requires Pillow; the blob path deliberately does not."""
    from PIL import Image
    img = Image.new("RGB", (WORLD_T * TILE_PX, WORLD_T * TILE_PX))
    px = img.load()
    for ty in range(WORLD_T):
        for tx in range(WORLD_T):
            c = tile_color(tx, ty)
            for py in range(TILE_PX):
                for pxi in range(TILE_PX):
                    px[tx * TILE_PX + pxi, ty * TILE_PX + py] = c
    img.save(path)


# =============================================================================
# The OBJ sprites — hero, enemy, win card.
#
# The camera is a PLAN VIEW: straight down at the floor, zero tilt, hero pinned
# at screen centre while the Mode 7 plane rotates under it (tank controls). Two
# consequences drive every pixel below.
#
# (1) Sprites must read as FOOTPRINTS FROM DIRECTLY OVERHEAD. A face, a chest,
#     a backplate, legs, a puddle "front" — each would betray a tilted camera
#     that is not there. What you can see from straight up is the crown of a
#     helmet, a shoulder ring, hands at the shoulder line; and for a slime, a
#     rim, a body and a specular highlight. Nothing else.
#
# (2) OBJ sprites do NOT rotate with the Mode 7 floor. So anything with a
#     strong orientation contradicts the world the instant it spins. Both
#     characters are therefore built from CONCENTRIC DISTANCE BANDS, which
#     makes them radially symmetric by construction rather than by eye. The
#     hero's single forward plume is the one deliberate exception, and it is
#     honest: tank controls mean the hero permanently faces screen-up.
#
# All three are authored from literals and math.hypot — no image is read, so
# there is no upstream and no provenance question.
# =============================================================================

import math                                                     # noqa: E402

OBJ_GRID_TILES = 18       # 16x16 sprite = the PPU quad {0, 1, 16, 17}
OBJ_TILE_BYTES = 32       # 8x8 4bpp planar

# Hero — bright, DESATURATED steel/bone. Deliberately out of every terrain
# band: the floor is cool and dark, the walls are warm, the enemy is warm and
# bright, the goal is gold. A grey knight collides with none of them, which is
# what lets a colour sampler tell hero from world without a mask.
HERO_PAL = [
    (0, 0, 0),           # 0 transparent
    (49, 49, 66),        # 1 dark cool outline
    (156, 148, 148),     # 2 mid steel — helmet dome + shoulder ring
    (239, 231, 222),     # 3 bone highlight — crown apex, plume, hands
    (99, 99, 123),       # 4 mid-dark shade — the recessed neck groove
]

# Enemy — warm slime. The bright body renders (231,107,74): warm AND brighter
# than any brick tone (r >= 205), so it clears the walls by brightness while
# the mid-orange shade, which WOULD land in the rendered-wall band, is kept
# strictly interior. The outermost ring is the neutral dark outline, so the
# ring a floor sampler reads around the sprite never sees a wall-band colour.
ENEMY_PAL = [
    (0, 0, 0),           # 0 transparent
    (49, 24, 24),        # 1 dark outline rim
    (173, 74, 49),       # 2 mid-orange shade — INTERIOR ONLY
    (231, 107, 74),      # 3 bright body — the enemy-warm anchor
    (255, 222, 181),     # 4 glossy highlight
]

# Win card — gold. Warm-YELLOW (high green), so it never trips the enemy-warm
# band even though it shares no screen region with the enemy anyway.
WIN_PAL = [
    (0, 0, 0),           # 0 transparent
    (120, 80, 20),       # 1 outline (dark gold)
    (248, 200, 64),      # 2 body (gold)
    (255, 244, 176),     # 3 highlight
]

_N = 16                  # sprite side, px
_CX = _CY = 7.5          # centre of a 16-px span

# Hero radial bands, apex outward (distance from centre, in px)
_R_CROWN = 2.35          # bone helmet APEX — the top of the head, top-lit
_R_DOME = 3.3            # steel helmet dome around it
_R_GROOVE = 4.2          # recessed neck groove — reads as head-over-shoulders
_R_RING = 6.2            # steel shoulder ring (pauldrons) — widest armour
_R_EDGE = 7.0            # dark silhouette outline (the footprint rim)

# Slime radial bands
_R_BODY = 5.5            # bright warm body — dominates the blob
_R_SHADE = 6.1           # interior rim darkening (kept off the outer ring)
_R_SLIME_EDGE = 6.9      # dark outline rim — the outermost pixels


def hero_grid() -> list[list[int]]:
    """Plan-view knight: concentric footprint + the forward plume + hands."""
    g = [[0] * _N for _ in range(_N)]
    for y in range(_N):
        for x in range(_N):
            d = math.hypot(x - _CX, y - _CY)
            if d <= _R_CROWN:
                g[y][x] = 3
            elif d <= _R_DOME:
                g[y][x] = 2
            elif d <= _R_GROOVE:
                g[y][x] = 4
            elif d <= _R_RING:
                g[y][x] = 2
            elif d <= _R_EDGE:
                g[y][x] = 1

    # The helm PLUME, tapering to a tip at row 0 — the sole intentional break
    # in the radial symmetry, and the only orientation cue the sprite may show.
    for ry, (x0, x1) in {0: (7, 8), 1: (6, 9), 2: (6, 9)}.items():
        for x in range(x0, x1 + 1):
            g[ry][x] = 3
    # Frame its base so the crest reads as a ridge rather than a smear. Note
    # what is NOT done: nothing bright goes low on the head, because two
    # symmetric bright pips read as EYES, and eyes mean a tilted camera.
    g[2][5] = 1
    g[2][10] = 1

    # HANDS — gauntlets at 3 and 9 o'clock, at the widest point of the
    # shoulders, bone-bright so they read as hands and not as armour.
    for hx0, hx1 in ((1, 2), (13, 14)):
        for x in range(hx0, hx1 + 1):
            for y in (7, 8):
                g[y][x] = 3
    return g


def enemy_grid() -> list[list[int]]:
    """Plan-view slime: concentric warm blob + one glossy highlight."""
    g = [[0] * _N for _ in range(_N)]
    for y in range(_N):
        for x in range(_N):
            d = math.hypot(x - _CX, y - _CY)
            if d <= _R_BODY:
                g[y][x] = 3
            elif d <= _R_SHADE:
                g[y][x] = 2
            elif d <= _R_SLIME_EDGE:
                g[y][x] = 1

    # The specular cap of an overhead light on a wet dome, offset up. ONE
    # connected shape — two dots would read as eyes, i.e. a face, i.e. a tilt.
    for ry, x0, x1 in ((3, 7, 8), (4, 6, 9), (5, 7, 8)):
        for x in range(x0, x1 + 1):
            if g[ry][x] == 3:            # only over body, so it stays glossy
                g[ry][x] = 4
    return g


def win_grid() -> list[list[int]]:
    """A 4-point sparkle star: core, body diamond, long thin arms, halo."""
    g = [[0] * _N for _ in range(_N)]
    for y in range(_N):
        for x in range(_N):
            dx, dy = abs(x - _CX), abs(y - _CY)
            core = dx + dy <= 1.5
            body = dx + dy <= 4.0
            arm = (dx <= 1.0 and dy <= 7.0) or (dy <= 1.0 and dx <= 7.0)
            halo = (dx + dy <= 5.0) or (dx <= 2.0 and dy <= 7.5) \
                or (dy <= 2.0 and dx <= 7.5)
            if core:
                g[y][x] = 3
            elif body or arm:
                g[y][x] = 2
            elif halo:
                g[y][x] = 1
    return g


def encode_tile_4bpp(grid, ox: int, oy: int) -> bytes:
    """The 8x8 sub-grid at (ox,oy) -> 32 B SNES 4bpp planar.

    Planes 0,1 interleave by row in the first 16 bytes; planes 2,3 in the
    second 16. Bit 7 of each byte is the LEFTMOST pixel."""
    out = bytearray(OBJ_TILE_BYTES)
    for y in range(8):
        p = [0, 0, 0, 0]
        for x in range(8):
            v = grid[oy + y][ox + x]
            assert 0 <= v <= 15, v
            for plane in range(4):
                p[plane] |= ((v >> plane) & 1) << (7 - x)
        out[y * 2] = p[0]
        out[y * 2 + 1] = p[1]
        out[16 + y * 2] = p[2]
        out[16 + y * 2 + 1] = p[3]
    return bytes(out)


def obj_chr(grid) -> bytes:
    """A 16x16 sprite on the OBJ grid: 18 tiles, content at 0/1/16/17.

    The PPU reads a 16x16 sprite as {N, N+1, N+16, N+17} — the lower row is
    +16 tile numbers away, NOT +2, because OBJ CHR is a 16-tile-wide sheet.
    That is hardware, not a convention, so the 14 tiles between the two rows
    are padding by necessity and the blob must be laid out this way or the
    bottom half of the sprite is whatever tiles happen to sit at +2."""
    tiles = [bytes(OBJ_TILE_BYTES)] * OBJ_GRID_TILES
    tiles[0] = encode_tile_4bpp(grid, 0, 0)      # TL
    tiles[1] = encode_tile_4bpp(grid, 8, 0)      # TR
    tiles[16] = encode_tile_4bpp(grid, 0, 8)     # BL
    tiles[17] = encode_tile_4bpp(grid, 8, 8)     # BR
    return b"".join(tiles)


def obj_pal(colors) -> bytes:
    """16 BGR555 words, zero-padded. A 4bpp OBJ palette is 16 entries whether
    or not the art uses them, and CGRAM is written as a block."""
    pal = bytearray()
    for rgb in colors:
        pal += struct.pack("<H", rgb_to_bgr555(*rgb))
    return bytes(pal) + bytes(2 * (16 - len(colors)))


# =============================================================================
# Emit
# =============================================================================

def vendored(name: str) -> bytes | None:
    """A reference blob, or None if it is not on disk. Absence is
    tolerated so the generator still runs in a stripped tree; when the file IS
    there — and it is committed, so it always is — disagreement is fatal."""
    p = VENDOR / name
    return p.read_bytes() if p.exists() else None


def inc_bytes(name: str, label: str) -> bytes | None:
    """The `.byte` / `.word` run following `label:` in a vendored ca65 include.

    A deliberately dumb text reader. The vendored sprites are ca65 source
    rather than blobs, and the whole value of those files is that a program
    this repo does not run produced them — so they are read as text, not
    assembled and not imported."""
    p = VENDOR / name
    if not p.exists():
        return None
    out, taking = bytearray(), False
    for line in p.read_text().splitlines():
        s = line.split(";")[0].strip()
        if s == f"{label}:":
            taking = True
            continue
        if not taking:
            continue
        if s.startswith(".byte"):
            out += bytes(int(v.strip().lstrip("$"), 16) for v in s[5:].split(","))
        elif s.startswith(".word"):
            for v in s[5:].split(","):
                out += struct.pack("<H", int(v.strip().lstrip("$"), 16))
        elif s:
            break
    if not out:
        raise SystemExit(f"gen_m7_dungeon_assets: label '{label}' not found in "
                         f"{name} — the vendored fixture is not what it was")
    return bytes(out)


def check_oracle(name: str, got: bytes, ref_name: str, notes: list,
                 ref: bytes | None = None) -> None:
    """Refuse to emit anything that disagrees with the reference blob.

    This is a build gate, not a test convenience. The generator shares no code
    with the program that made the reference, so a mismatch means one of the
    two is wrong and neither has authority — stop and look, do not ship."""
    if ref is None:
        ref = vendored(ref_name)
    if ref is None:
        notes.append(f"{name}: NO ORACLE ({ref_name} absent) — UNVERIFIED")
        return
    if got != ref:
        diff = sum(a != b for a, b in zip(got, ref))
        raise SystemExit(
            f"gen_m7_dungeon_assets: {name} disagrees with the vendored "
            f"{ref_name} — {diff} of {max(len(got), len(ref))} bytes differ "
            f"(lengths {len(got)} vs {len(ref)}). The port and the reference "
            f"cannot both be right; do not re-vendor to make this go away.")
    notes.append(f"{name}: byte-identical to {ref_name} ({len(ref)} B)")


def write(path: Path, blob: bytes, made: list) -> None:
    path.write_bytes(blob)
    made.append(f"{path.name} ({len(blob)} B)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("outdir", help="directory to write the .bin blobs into")
    ap.add_argument("--png", metavar="PATH",
                    help="also write the authored 1024x1024 source image "
                         "(reference only; needs Pillow)")
    args = ap.parse_args(argv)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    made: list[str] = []
    notes: list[str] = []

    # --- the floor: map blob, palette, collision ---------------------------
    blob, tilemap, pal = build_map()
    check_oracle("map blob", blob, "ref_dungeon_map.bin", notes)

    terr = terrain()
    check_oracle("terrain (intermediate, not shipped)", terr,
                 "ref_dungeon_terrain.bin", notes)

    flags = flag_table(tilemap, terr)
    assert_flags_equivalent(flags, tilemap, terr)
    notes.append(f"flag table: {len(set(tilemap))} distinct tile ids, 0 "
                 f"conflicts, equivalent to the terrain at all "
                 f"{TERRAIN_BYTES} world cells")

    write(out / "m7dg_map.bin", blob, made)
    # The PACKED tile-id map — the same 16,384 ids the interleaved blob carries
    # in its even bytes, written contiguously because that is the only layout
    # col_map's `offset = ty * W + tx` can index. Emitted from the SAME
    # `tilemap` the blob was interleaved from, so the two cannot disagree.
    write(out / "m7dg_tilemap.bin", tilemap, made)
    write(out / "m7dg_pal.bin", pal, made)
    write(out / "m7dg_flags.bin", flags, made)
    notes.append(f"packed tile-id map: {len(tilemap)} B, identical to the "
                 f"even bytes of the interleaved blob")
    if bytes(blob[0::2]) != bytes(tilemap):
        raise SystemExit("gen_m7_dungeon_assets: the packed tile-id map "
                         "disagrees with the interleaved blob's even bytes")

    # --- the OBJ sprites ---------------------------------------------------
    # The vendored sprites are ca65 source, so the reference is parsed out of
    # the .inc.
    for stem, grid, pal_rgb, inc, chr_label, pal_label in (
            ("hero", hero_grid(), HERO_PAL,
             "ref_hero.inc", "hero_chr", "hero_pal"),
            ("enemy", enemy_grid(), ENEMY_PAL,
             "ref_enemy.inc", "enemy_chr", "enemy_pal"),
            ("win", win_grid(), WIN_PAL,
             "ref_win.inc", None, "win_pal")):
        chr_blob = obj_chr(grid)
        pal_blob = obj_pal(pal_rgb)

        if chr_label is not None:
            check_oracle(f"{stem} CHR", chr_blob, f"{inc}:{chr_label}", notes,
                         ref=inc_bytes(inc, chr_label))
        else:
            # The win card is the one shape mismatch. The vendored bytes hold
            # it as two tight 64-byte row blobs instead of the 18-tile grid, to
            # save 448 B in a bank that was nearly full. This repo emits the
            # uniform grid
            # for all three — the allocator places ROM here and uniformity is
            # worth more than 448 B in a 512 KB image — so the comparison is on
            # tile CONTENT: the quad against top‖bot, and the padding against
            # zero. Checking only the quad would let a corrupted pad through.
            top = inc_bytes(inc, "win_chr_top")
            bot = inc_bytes(inc, "win_chr_bot")
            if top is None or bot is None:
                notes.append(f"{stem} CHR: NO ORACLE ({inc} absent) — UNVERIFIED")
            else:
                quad = chr_blob[:2 * OBJ_TILE_BYTES] \
                    + chr_blob[16 * OBJ_TILE_BYTES:18 * OBJ_TILE_BYTES]
                check_oracle(f"{stem} CHR quad {{0,1,16,17}}", quad,
                             f"{inc}:win_chr_top‖win_chr_bot", notes,
                             ref=top + bot)
                pad = chr_blob[2 * OBJ_TILE_BYTES:16 * OBJ_TILE_BYTES]
                if pad != bytes(len(pad)):
                    raise SystemExit("gen_m7_dungeon_assets: win CHR padding "
                                     "tiles 2..15 are not zero")
                notes.append("win CHR: padding tiles 2..15 all zero (448 B)")

        check_oracle(f"{stem} palette", pal_blob, f"{inc}:{pal_label}", notes,
                     ref=inc_bytes(inc, pal_label))
        write(out / f"m7dg_{stem}_chr.bin", chr_blob, made)
        write(out / f"m7dg_{stem}_pal.bin", pal_blob, made)

    if args.png:
        write_png(Path(args.png))
        notes.append(f"wrote reference image {args.png}")

    print("gen_m7_dungeon_assets: " + ", ".join(made))
    for n in notes:
        print("  " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
