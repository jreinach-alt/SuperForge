#!/usr/bin/env python3
"""gen_m7_assets.py — deterministic microzero Mode-7 floor assets.

Emits (byte-identical on re-run, pure integer math):
  floor_tiles.bin   12 tiles x 64 B, 8bpp (one palette index per pixel)
  floor_pal.bin     17 BGR555 colors, little-endian words
  world_map.bin     512x512 tile ids, row-major, 512 B/row (256 KB) — a ring
                    track over checkered grass, bank-tiled by construction
                    (64 rows per 32 KB window)

Tile set (indices into floor_pal):
  0 grass A (dark)   1 grass B (light)  2 road       3 road center-line
  4 curb A           5 curb B           6 start/finish checker
  7..11 reserved solids (distinct colors, streaming-visible markers)
"""
import sys
from pathlib import Path

T = 8                                   # tile side, px


def bgr(r: int, g: int, b: int) -> int:
    """A BGR555 word from 5-bit components — the hardware's colour layout,
    written the way a human reads it (r, g, b) instead of as a hex literal."""
    assert 0 <= r < 32 and 0 <= g < 32 and 0 <= b < 32, (r, g, b)
    return (b << 10) | (g << 5) | r


def tile_solid(c):
    return bytes([c] * 64)


def tile_checker(a, b, cell=2):
    out = bytearray()
    for y in range(T):
        for x in range(T):
            out.append(a if ((x // cell) + (y // cell)) % 2 == 0 else b)
    return bytes(out)


def tile_vstripe(a, b, w=2):
    out = bytearray()
    for y in range(T):
        for x in range(T):
            out.append(a if (x // w) % 2 == 0 else b)
    return bytes(out)


def tile_line(base, ink, axis, half=1, edge=None):
    """One centre-line tile, drawn ALONG the road rather than always
    vertically.

    axis picks which family of parallel lines the ink follows:
      "V"  x = const   (road running north-south)
      "H"  y = const   (road running east-west)
      "/"  x + y = c   (road running up-right)
      "\\" x - y = c   (road running down-right)

    A single vertical-stripe tile used on all eight sides is what made the
    line read as bars across the north/south straights and as a staircase of
    dashes on the diagonals: the ink has to follow the road.

    `edge` adds one intermediate colour between ink and base. It is worth
    a palette entry: at mid and far distance — which is most of the visible
    road — it visibly removes the diagonal's stair-stepping.

    The WEIGHT matters more than the idea. The edge colour is ~25% of the
    way from road to line, not the 50% blend a coverage argument suggests:
    Mode 7 magnifies these tiles ~3x in the near field, so the edge pixels
    are as large on screen as the ink and a 50% blend reads as a fat olive
    halo tracing its own staircase beside the line. At 25% it softens
    without announcing itself. (Measured by sweeping 50/33/25% and looking
    at both a near-field and a mid-field render.)"""
    c = (T - 1) / 2
    out = bytearray()
    for y in range(T):
        for x in range(T):
            if axis == "V":
                d = abs(x - c)
            elif axis == "H":
                d = abs(y - c)
            elif axis == "/":
                d = abs(x + y - 2 * c) / 2 ** 0.5
            else:
                d = abs(x - y) / 2 ** 0.5
            if d <= half:
                out.append(ink)
            elif edge is not None and d <= half + 1:
                out.append(edge)
            else:
                out.append(base)
    return bytes(out)


def palette() -> list[int]:
    """The 17 floor colours, as BGR555 words. Exposed so tests read the
    palette from the generator (the oracle SSoT) instead of re-declaring
    any colour of it as a literal."""
    # palette: the track look, authored here (this generator stays the
    # oracle SSoT — the committed .inc binaries are reference, not inputs).
    # Vivid greens for grass, blue-grey asphalt, red/white
    # curbing, yellow centre line: chromatic enough to survive the horizon
    # haze the gradient adds on top of it.
    pal = [bgr(0, 0, 0),                 # 0: transparent/black
           bgr(0, 12, 6), bgr(0, 30, 10),        # 1,2: grass dark/light
           bgr(10, 10, 12), bgr(16, 16, 18),     # 3,4: asphalt dark/light
           bgr(31, 0, 0), bgr(31, 31, 31),       # 5,6: curb red / white
           bgr(31, 31, 0),                       # 7: yellow centre line
           bgr(15, 15, 9),                       # 8: line edge — see tile_line
           bgr(31, 0, 31), bgr(12, 16, 0),       # 9,10: markers
           bgr(31, 8, 16), bgr(0, 18, 31),       # 11,12
           bgr(4, 4, 4), bgr(21, 13, 5),         # 13,14
           bgr(3, 12, 3), bgr(31, 31, 31)]       # 15,16
    assert len(pal) == 17
    return pal


# Named indices into palette() — the tile builders and the tests both mean
# "the road colour", not "colour 3".
GRASS_DARK, GRASS_LIT = 1, 2
ROAD, ROAD_LIT = 3, 4
CURB_R, CURB_W = 5, 6
CENTRE_LINE = 7
LINE_EDGE = 8            # the anti-aliasing step (see tile_line)

# --- track geometry: a regular octagon ring --------------------------------
# The course is the level set of a regular-octagon NORM around the world
# centre. Four axis-aligned straights and four 45-degree straights, which is
# the point: the diagonal sides hold the camera on a sustained diagonal at
# the declared max speed, staging the maximum number of rows AND columns
# every frame for the whole length of the side. A circle only touches that
# worst case instantaneously, at four points per lap.
WORLD_T = 512                       # world side, tiles
CENTER_T = WORLD_T // 2
OCT_MID = 200                       # centre-line apothem, tiles
OCT_HALF_W = 12                     # half road width (look-1: what the
                                    # perspective can actually show)
OCT_IN = OCT_MID - OCT_HALF_W
OCT_OUT = OCT_MID + OCT_HALF_W
CURB_T = 2                          # curb thickness, tiles
SPOKE_HALF = 2                      # start/finish spoke half-width, tiles

# 2**14 / sqrt(2), rounded — keeps the norm integer-exact and therefore the
# generated map byte-identical on re-run (no float in the map loop).
INV_SQRT2_Q14 = 11585

# The world is a torus: the streamed VRAM window spans the camera +/- 64
# tiles and wraps mod 512. If the track reaches too far out, the window at
# the east straight wraps onto the WEST side of the track and the player
# sees phantom road in the distance. Wrapped x runs 0..(OCT_OUT-192), which
# must stay outside the octagon: 256 - (OCT_OUT - 192) > OCT_OUT.
assert 2 * OCT_OUT < 448, (
    f"octagon too large for the streamed window: outer apothem {OCT_OUT} "
    f"tiles wraps track onto track (limit 223)")


def oct_dist(dx: int, dy: int) -> int:
    """The regular-octagon norm: max(|dx|, |dy|, (|dx|+|dy|)/sqrt(2)).

    Its level sets are regular octagons with flat N/S/E/W sides and flat
    45-degree sides. Because it is a NORM, its value is the perpendicular
    distance to the corresponding edge — so a band [a, b] has uniform width
    b-a everywhere, corners included, and the road does not pinch or bulge
    where the sides meet. Integer throughout; the map must be reproducible
    byte-for-byte."""
    ax, ay = abs(dx), abs(dy)
    return max(ax, ay, ((ax + ay) * INV_SQRT2_Q14) >> 14)


# sqrt(2) * 2**14, rounded — OCT_MID_DIAG is the single anti-diagonal that
# IS the centre line on the 45-degree sides (see on_centre_line).
SQRT2_Q14 = 23170
OCT_MID_DIAG = (OCT_MID * SQRT2_Q14 + (1 << 13)) >> 14


def on_centre_line(dx: int, dy: int) -> bool:
    """Is this cell ON the centre line? Exactly ONE cell wide, every side.

    The norm's integer level set (oct_dist == OCT_MID) is NOT the right
    test. Along a 45-degree side, cells are spaced 1/sqrt(2) apart in
    oct_dist, so two adjacent integer values of |dx|+|dy| floor to the same
    distance — at OCT_MID = 200 both 283 and 284 do, because 200*sqrt(2) =
    282.84. Most rows therefore got TWO adjacent line cells, and since each
    cell paints a full diagonal stripe through itself, the two stripes
    landed one tile apart and rendered as two parallel dashed lines.

    Selecting the single anti-diagonal |dx|+|dy| == round(OCT_MID*sqrt(2))
    gives one cell per row. It also joins the straights exactly: a side
    switches to diagonal at |dy| > |dx|*(sqrt(2)-1), which at |dx| = OCT_MID
    is |dy| = 83, and 200 + 83 = 283 = OCT_MID_DIAG — the two lines meet on
    the same cell with no step and no gap."""
    ax, ay = abs(dx), abs(dy)
    diag = ((ax + ay) * INV_SQRT2_Q14) >> 14
    if diag >= ax and diag >= ay:
        return ax + ay == OCT_MID_DIAG
    if ax >= ay:
        return ax == OCT_MID
    return ay == OCT_MID


def start_tile() -> tuple[int, int]:
    """Where the camera starts: mid-road on the due-east straight, which is
    where the start/finish spoke crosses it. world.inc's CAM0 must agree —
    tests/test_microzero_track.py asserts that it does."""
    return CENTER_T + OCT_MID, CENTER_T


# Tile ids for the centre line, one per road direction, and how far the
# along-track coordinate advances per tile step in that direction. On a
# 45-degree side one tile step changes (dx-dy) or (dx+dy) by 2, so the dash
# and kerb periods are doubled there to keep their length in ARC equal.
LINE_V, LINE_H, LINE_SLASH, LINE_BACK = 3, 7, 8, 9
DASH_PERIOD = 8                     # tiles: 4 painted, 4 blank
KERB_PERIOD = 8                     # tiles: 4 red, 4 white

TILE_ROAD, TILE_START = 2, 6
TILE_KERB_R, TILE_KERB_W = 4, 5
LINE_TILES = frozenset({LINE_V, LINE_H, LINE_SLASH, LINE_BACK})

# Which tile ids count as being ON the course. Exposed because tests kept
# re-declaring it: when the centre line gained per-direction variants, a
# test carrying its own {2, 3, 6} started counting "driving on the centre
# line" as "off the road" — on exactly the sides whose line tile was new.
DRIVABLE_TILE_IDS = frozenset({TILE_ROAD, TILE_START}) | LINE_TILES
TRACK_TILE_IDS = DRIVABLE_TILE_IDS | {TILE_KERB_R, TILE_KERB_W}


def side_of(dx: int, dy: int) -> tuple[int, int, int]:
    """Which of the eight sides a cell is against.

    Returns (centre-line tile id, coordinate ALONG the road, period scale).
    The along-track coordinate phases the dashes and the kerb blocks, so
    both stay square to the direction of travel instead of to the world
    axes — which is what made them break on the diagonals."""
    ax, ay = abs(dx), abs(dy)
    diag = ((ax + ay) * INV_SQRT2_Q14) >> 14
    if diag >= ax and diag >= ay:
        # 45-degree side. Same-sign quadrants (SE, NW) have outward normal
        # (1,1)/sqrt2, so the road runs (1,-1) — the "/" family, along which
        # (x-y) advances. Opposite-sign quadrants run "\".
        if (dx >= 0) == (dy >= 0):
            return LINE_SLASH, dx - dy, 2
        return LINE_BACK, dx + dy, 2
    if ax >= ay:
        return LINE_V, dy, 1            # east/west straight: road runs N-S
    return LINE_H, dx, 1                # north/south straight: runs E-W


def world_map() -> bytes:
    """512x512 tile ids, row-major — the octagon ring over checkered grass."""
    rows = bytearray()
    for y in range(WORLD_T):
        for x in range(WORLD_T):
            dx, dy = x - CENTER_T, y - CENTER_T
            d = oct_dist(dx, dy)
            line_tile, along, scale = side_of(dx, dy)
            if OCT_IN + CURB_T <= d <= OCT_OUT - CURB_T:
                t = 2
                # Centre line: ONE tile wide, drawn along the road, dashed.
                # It used to be three tiles wide with a fixed vertical
                # stripe inside each — three parallel lines on the straights
                # and a staircase everywhere else.
                if on_centre_line(dx, dy):
                    period = DASH_PERIOD * scale
                    if along % period < period // 2:
                        t = line_tile
                # start/finish: the due-east spoke, across the road
                if abs(dy) <= SPOKE_HALF and dx > 0:
                    t = 6
            elif (OCT_IN <= d < OCT_IN + CURB_T
                  or OCT_OUT - CURB_T < d <= OCT_OUT):
                # kerb BLOCKS alternating along the road, not a per-pixel
                # checker: at distance a 2-px checker is noise, and the
                # blocks are what read as a racing kerb
                period = KERB_PERIOD * scale
                t = 4 if along % period < period // 2 else 5
            else:
                t = 1 if ((x // 4) + (y // 4)) % 2 == 0 else 0
            rows.append(t)
    return bytes(rows)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    pal = palette()
    (out / "floor_pal.bin").write_bytes(
        b"".join(c.to_bytes(2, "little") for c in pal))

    tiles = [
        tile_checker(1, 1),                    # 0: grass A (solid dark)
        tile_checker(1, 2, 4),                 # 1: grass B (coarse checker)
        tile_solid(ROAD),                      # 2: road
        tile_line(ROAD, CENTRE_LINE, "V", edge=LINE_EDGE),   # 3: N-S road
        tile_solid(CURB_R),                    # 4: kerb block, red
        tile_solid(CURB_W),                    # 5: kerb block, white
        tile_checker(CURB_W, 0, 2),            # 6: start/finish
        tile_line(ROAD, CENTRE_LINE, "H", edge=LINE_EDGE),   # 7: E-W road
        tile_line(ROAD, CENTRE_LINE, "/", edge=LINE_EDGE),   # 8: "/" road
        tile_line(ROAD, CENTRE_LINE, "\\", edge=LINE_EDGE),  # 9: "\" road
        tile_solid(ROAD_LIT),                  # 10: spare (road, lighter)
        tile_solid(GRASS_LIT),                 # 11: spare
    ]
    (out / "floor_tiles.bin").write_bytes(b"".join(tiles))

    rows = world_map()
    assert len(rows) == WORLD_T * WORLD_T
    W = WORLD_T
    (out / "world_map.bin").write_bytes(rows)
    print(f"m7 assets -> {out} (tiles {len(tiles)}, map {len(rows)} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
