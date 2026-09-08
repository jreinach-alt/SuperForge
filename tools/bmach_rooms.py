#!/usr/bin/env python3
"""The `bmach` room library — screen-sized rooms, authored, stitched procedurally.

WHY THIS EXISTS. Three rounds of generating this world tile-by-tile from rules
derived off the tile atlas produced a level that was disconnected, then
connected but noisy, then coherent but undesigned. The reason is structural
rather than a tuning problem: an atlas can say an arch stone EXISTS, it cannot
say that arches span doorways or that pistons stand in bays. That judgement
only lives in somebody's arrangement of them.

Every procedural level generator that produces good-looking output composes
AUTHORED CHUNKS — Spelunky's hand-drawn room templates assembled by a solver,
Isaac's authored rooms on a procedural graph, WFC's constraints learned from an
authored example image. Tile-by-tile from first principles is the mode nobody
uses. So the design lives here, in grids a person can read and correct, and the
generator's job shrinks to choosing rooms and stitching them at connectors.

A ROOM IS ONE SCREEN. 16 x 16 blocks = 256 x 256 px, against a 256 x 224
viewport, so a room is a screen with two blocks of vertical slack. The world is
4 x 4 rooms = the 64 x 64 map the tiles16 claim already buys.

LEGEND
  #   solid mass          (autotiled: the terrain set picks the piece)
  .   air
  =   platform            (walkable, thin)
  ^   hazard
  |   piston bay          (an extensible fixture stands here, full height)
  o   fixture anchor      (a unit fixture from the room's zone, floor-standing)
  x   fixture anchor      (a unit fixture, ceiling-hung)

CONNECTORS are not declared — they are READ off the edges. A room opens on a
side when its edge cells there include air, which means a template cannot claim
a door it did not draw.
"""

ROOM_W = ROOM_H = 16
ROOMS_X = ROOMS_Y = 4

SOLID, AIR, PLATFORM, HAZARD, PISTON, FIX_FLOOR, FIX_CEIL = "#.=^|ox"


def _rows(s):
    r = [ln for ln in s.strip("\n").split("\n")]
    assert len(r) == ROOM_H, f"room is {len(r)} rows, not {ROOM_H}"
    for ln in r:
        assert len(ln) == ROOM_W, f"row {ln!r} is {len(ln)} wide, not {ROOM_W}"
    return tuple(r)


class Room:
    __slots__ = ("name", "zone", "rows", "opens")

    def __init__(self, name, zone, art):
        self.name, self.zone = name, zone
        self.rows = _rows(art)
        self.opens = self._read_openings()

    def _read_openings(self):
        """Which sides this room opens on, read off the drawing itself."""
        o = set()
        if any(c in ".=|" for c in self.rows[0]):
            o.add("N")
        if any(c in ".=|" for c in self.rows[-1]):
            o.add("S")
        if any(r[0] in ".=|" for r in self.rows):
            o.add("W")
        if any(r[-1] in ".=|" for r in self.rows):
            o.add("E")
        return frozenset(o)

    def __repr__(self):
        return f"<Room {self.name} {sorted(self.opens)}>"


# --- the library -------------------------------------------------------------
# Rooms are authored per zone. Each is a screen. The naming says what the room
# IS, because a room with a purpose is the whole point of authoring them.
RUINS = [
    Room("ruins_entrance", 0, """
....##....##....
...##......##...
..##...oo...##..
.##..........##.
##............##
#..............#
#..o........o..#
#==============#
#..............#
#..............#
##............##
.##....====..###
..##.........###
...####......###
......##.....###
.......#.....###
"""),
    Room("ruins_hall", 0, """
################
#..x........x..#
#..............#
#....======....#
#..............#
#.o..........o.#
#===..........=#
#..............#
#..........o...#
#=====.....====#
#..............#
#...o..........#
#..====........#
#..............#
#..............#
################
"""),
    Room("ruins_drop", 0, """
######....######
#####......#####
####........####
###..o....o..###
###==========###
###..........###
###..........###
###....==....###
###..........###
####........####
#####......#####
######....######
######....######
######....######
######....######
######....######
"""),
    Room("ruins_gallery", 0, """
################
#..............#
#.x..x..x..x.x.#
#..............#
#..............#
#..............#
#..............#
#..............#
#....o....o....#
#==============#
#..............#
#..............#
#..o........o..#
#====......====#
#..............#
....########....
"""),
]

MACHINE = [
    Room("machine_bay", 1, """
....########....
....#......#....
....#..||..#....
#####..||..#####
#..x...||...x..#
#......||......#
#......||......#
#..o...||...o..#
#===...||...===#
#......||......#
#......||......#
#..............#
#....======....#
#..............#
#..............#
....########....
"""),
    Room("machine_gantry", 1, """
################
#..x........x..#
#..............#
#=====....=====#
#..............#
#....||||||....#
#....||||||....#
#....||||||....#
#....||||||....#
#..............#
#=..........===#
#..............#
#...o......o...#
#====......====#
#..............#
....########....
"""),
    Room("machine_shaft", 1, """
######....######
#####......#####
####...||...####
###....||....###
###....||....###
###....||....###
###....||....###
###....||....###
###....||....###
###....||....###
###....||....###
###....||....###
####...||...####
#####......#####
######....######
######....######
"""),
    Room("machine_floor", 1, """
....########....
....#......#....
#####......#####
#..............#
#..x........x..#
#..............#
#..............#
#....o....o....#
#==============#
#..............#
#..o........o..#
#=====....=====#
#..............#
#..............#
#..............#
....########....
"""),
]

FURNACE = [
    Room("furnace_mouth", 2, """
....########....
....#......#....
#####......#####
#..............#
#..x........x..#
#..............#
#....======....#
#..............#
#..o........o..#
#====......====#
#..............#
#..............#
#..............#
#..^^^^^^^^^^..#
################
################
"""),
    Room("furnace_hall", 2, """
################
#..x........x..#
#..............#
#....o....o....#
#====......====#
#..............#
#..............#
#..o..o..o..o..#
#==============#
#..............#
#..............#
#..^^....^^....#
################
################
################
################
"""),
]

LIBRARY = RUINS + MACHINE + FURNACE
BY_ZONE = {}
for _r in LIBRARY:
    BY_ZONE.setdefault(_r.zone, []).append(_r)


# --- rooms the stitcher asked for -------------------------------------------
# AUTHORED AGAINST A FAILURE, not guessed. The first solve found no
# arrangement and said so: the terminal furnace row needs rooms that open NORTH
# and not south, and the outer columns need rooms with no door off the edge of
# the world. Each of these fills a named gap.
FURNACE += [
    Room("furnace_pit", 2, """
######....######
#####......#####
####........####
###..........###
###..o....o..###
###==========###
###..........###
###..........###
###....==....###
###..........###
###..^^^^^^..###
################
################
################
################
################
"""),
    Room("furnace_walk", 2, """
....########....
....#......#....
#####......#####
#..............#
#..x........x..#
#....o....o....#
#====......====#
#..............#
#..o........o..#
#==============#
#..............#
#..^^^^^^^^^^..#
################
################
################
################
"""),
]

RUINS += [
    Room("ruins_ledges", 0, """
######....######
#####......#####
####........####
#..............#
#..o........o..#
#====......====#
#..............#
#......==......#
#..............#
#..o........o..#
#====......====#
#..............#
#......==......#
####........####
#####......#####
######....######
"""),
]

MACHINE += [
    Room("machine_duct", 1, """
######....######
#####......#####
####...||...####
#......||......#
#..x...||...x..#
#......||......#
#===...||...===#
#......||......#
#......||......#
#..o...||...o..#
#===...||...===#
#......||......#
####...||...####
#####..||..#####
######....######
######....######
"""),
]

LIBRARY = RUINS + MACHINE + FURNACE
BY_ZONE = {}
for _r in LIBRARY:
    BY_ZONE.setdefault(_r.zone, []).append(_r)


# --- bodies and exits --------------------------------------------------------
# THE ROUTE ASKS FOR SIX OPENING SHAPES PER ZONE and hand-authoring eighteen
# near-identical rooms would be eighteen chances to get a wall wrong. So what
# is authored is the BODY — the room's interior, its ledges, its bays, where
# its fixtures stand — and the exits are carved into the border afterwards at
# fixed, walkable positions. A body is a design; an exit is a hole.
#
# Door positions are not free: a side door sits at the FLOOR of the room, or
# the route would ask the player to reach a hole in a wall four blocks up.
DOOR_ROWS = (11, 12, 13)         # E/W doors, at standing height above the floor
DOOR_COLS = (6, 7, 8, 9)         # N/S doors, mid-span


def with_openings(body, opens, name=None):
    """A copy of `body` with doors cut for exactly `opens`."""
    rows = [list(r) for r in body.rows]
    if "W" in opens:
        for y in DOOR_ROWS:
            rows[y][0] = AIR
    if "E" in opens:
        for y in DOOR_ROWS:
            rows[y][ROOM_W - 1] = AIR
    if "N" in opens:
        for x in DOOR_COLS:
            rows[0][x] = AIR
    if "S" in opens:
        for x in DOOR_COLS:
            rows[ROOM_H - 1][x] = AIR
    art = "\n".join("".join(r) for r in rows)
    out = Room(name or f"{body.name}_{''.join(sorted(opens))}", body.zone, art)
    assert out.opens == frozenset(opens), (
        f"{out.name}: carved {sorted(opens)} but the room reads "
        f"{sorted(out.opens)} — the body's border is not solid")
    return out


def sealed(body):
    """The body with every border solid, so `with_openings` starts from closed."""
    rows = [list(r) for r in body.rows]
    for y in range(ROOM_H):
        rows[y][0] = rows[y][ROOM_W - 1] = SOLID
    for x in range(ROOM_W):
        rows[0][x] = rows[ROOM_H - 1][x] = SOLID
    return Room(body.name, body.zone, "\n".join("".join(r) for r in rows))


NEEDED_SHAPES = (("E",), ("E", "W"), ("S", "W"), ("N", "W"),
                 ("E", "S"), ("E", "N"), ("N", "S"), ("E", "W", "S"))


def expand_library():
    """Every authored body, in every opening shape the route can ask for."""
    out = []
    for body in LIBRARY:
        base = sealed(body)
        for shape in NEEDED_SHAPES:
            out.append(with_openings(base, frozenset(shape)))
    return out


# --- stitching ---------------------------------------------------------------
# The generator's whole job. Choose one room per grid cell so that every pair of
# neighbours AGREES on the edge they share — one opens east exactly when the
# other opens west — and so the zones descend. Connectivity then holds because
# the doors line up, not because a flood fill was run afterwards and something
# was patched.
ZONE_BY_ROW = (0, 0, 1, 2)          # ruins, ruins, machine, furnace


def critical_path():
    """The route through the room grid, laid out BEFORE any room is chosen.

    Pure constraint satisfaction gave a degenerate answer — the same room four
    times across every row, all of them north-south, so the world could only be
    walked straight down. A solver has no reason to prefer a good route unless
    the route is the input. So the path is a serpentine descent: across a row,
    down one, back across the next. Getting to the bottom means crossing the
    world four times, which is the thing the 1024-wide map is FOR.
    """
    path = []
    for rr in range(ROOMS_Y):
        cols = range(ROOMS_X) if rr % 2 == 0 else range(ROOMS_X - 1, -1, -1)
        path.extend((rr, cc) for cc in cols)
    return path


def required_openings(path):
    """Which sides each room on the path must open, from its neighbours in it."""
    need = {cell: set() for cell in path}
    for a, b in zip(path, path[1:]):
        (ar, ac), (br, bc) = a, b
        if br == ar + 1:
            need[a].add("S")
            need[b].add("N")
        elif bc == ac + 1:
            need[a].add("E")
            need[b].add("W")
        elif bc == ac - 1:
            need[a].add("W")
            need[b].add("E")
    return need


def stitch(seed=0):
    """One room per cell: the exact openings the route needs, and variety.

    A room is legal only if its openings EQUAL what the route asks for — a
    surplus door leads into solid rock next door, a missing one breaks the
    route. Among the legal ones, the least-used is taken, so a row does not
    come out as the same room four times.
    """
    path = critical_path()
    need = required_openings(path)
    expanded = {}
    for r in expand_library():
        expanded.setdefault(r.zone, []).append(r)
    grid = [[None] * ROOMS_X for _ in range(ROOMS_Y)]
    used = {}
    missing = []
    for k, (rr, cc) in enumerate(path):
        want = frozenset(need[(rr, cc)])
        pool = [r for r in expanded[ZONE_BY_ROW[rr]] if r.opens == want]
        if not pool:
            missing.append((rr, cc, sorted(want), ZONE_BY_ROW[rr]))
            continue
        pool.sort(key=lambda r: (used.get(r.name, 0), r.name))
        pick = pool[(seed + k) % len(pool)] if len(pool) > 1 else pool[0]
        pick = min(pool, key=lambda r: used.get(r.name, 0))
        used[pick.name] = used.get(pick.name, 0) + 1
        grid[rr][cc] = pick
    assert not missing, (
        "the room library has no room with the openings the route needs:\n  "
        + "\n  ".join(f"cell {c} needs exactly {w} in zone {z}"
                      for r, c, w, z in
                      [(m[0], (m[0], m[1]), m[2], m[3]) for m in missing]))
    return grid


def assemble(grid):
    """The stitched rooms as one 64 x 64 character map."""
    out = []
    for rr in range(ROOMS_Y):
        for y in range(ROOM_H):
            line = "".join(grid[rr][cc].rows[y] for cc in range(ROOMS_X))
            out.append(line)
    return out
