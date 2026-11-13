"""levelgen.py — reference model of SuperForge Dungeons' level generator.

Spec: docs/dungeons/03_level_generation.md. This file is the ORACLE: the ROM's
generator must produce, for the same (run_seed, floor), the same metatile map
and the same spawn table, byte for byte. Change the algorithm here and in the
spec together, never one alone.

Shape of the algorithm (template stitching on a coarse grid):
  1. walk    — a self-avoiding random walk over a GW x GH cell grid lays the
               CRITICAL PATH from the start cell to the boss cell.
  2. branch  — short side branches off the path; each branch tip is a
               treasure room.
  3. loops   — a few extra doors between already-occupied neighbours, so the
               map is not a pure tree (co-op players can split and rejoin).
  4. pick    — per cell, a template whose door set covers the cell's needed
               doors, chosen by weight; optionally mirrored left-right.
  5. stamp   — the template interior and a generated border (with door gaps)
               are written into a (GW*16) x (GH*16) metatile map.
  6. spawns  — markers become floor and are listed in a spawn table.

Every random decision is exactly one draw from prng.Stream, in a fixed order,
so the draw count is part of the contract (the ROM test asserts it).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(__file__))
import prng  # noqa: E402

CELL = 16                      # metatiles per cell side
N, E, S, W = 1, 2, 4, 8        # door bits (the ROM stores the same nibble)
DIRS = ((N, 0, -1), (E, 1, 0), (S, 0, 1), (W, -1, 0))
OPPOSITE = {N: S, S: N, E: W, W: E}

# Metatile ids in the generated map. The ROM's map is one byte per metatile;
# the low 6 bits are the id, the top 2 bits are reserved for runtime state
# (opened door, looted chest) — spec §4.1.
MT = {
    "void": 0x00, ".": 0x01, ":": 0x02, "t": 0x03,
    "#": 0x10, "o": 0x11, "~": 0x20,
    "door": 0x04, "x": 0x05,
}
WALKABLE = {0x01, 0x02, 0x03, 0x04, 0x05}
SHOT_PASS = WALKABLE | {0x20}
MARKERS = {"s": 1, "e": 2, "c": 3, "B": 4}   # spawn-table type codes
TYPES = ("start", "normal", "treasure", "boss")

HERE = os.path.dirname(__file__)


@dataclass
class Template:
    name: str
    type: str
    doors: int
    weight: int
    flip: bool
    rows: list[str]

    def mirrored(self) -> "Template":
        d = self.doors & (N | S)
        if self.doors & E:
            d |= W
        if self.doors & W:
            d |= E
        return Template(self.name + "~", self.type, d, self.weight, False,
                        [r[::-1] for r in self.rows])


def load_templates(path: str | None = None) -> list[Template]:
    path = path or os.path.join(HERE, "data", "templates.txt")
    out: list[Template] = []
    cur = None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        # Comments are "# ..." or a bare "#"; a row like "##..##" is map data
        # (space is not in the legend, so the two can never be confused).
        if line.startswith("# ") or line == "#" or not line.strip():
            continue
        if line.startswith("@"):
            parts = line[1:].split()
            kv = dict(p.split("=") for p in parts[1:])
            doors = sum({"N": N, "E": E, "S": S, "W": W}[c] for c in kv["doors"])
            cur = Template(parts[0], kv["type"], doors, int(kv["weight"]),
                           kv.get("flip") == "yes", [])
            out.append(cur)
        else:
            cur.rows.append(line)
    for t in out:
        if len(t.rows) != CELL - 2 or any(len(r) != CELL - 2 for r in t.rows):
            raise ValueError(f"template {t.name}: interior must be 14x14")
        if t.type not in TYPES:
            raise ValueError(f"template {t.name}: unknown type {t.type}")
    return out


@dataclass
class Level:
    gw: int
    gh: int
    cells: dict = field(default_factory=dict)     # (cx,cy) -> door mask
    kind: dict = field(default_factory=dict)      # (cx,cy) -> type
    path: list = field(default_factory=list)
    choice: dict = field(default_factory=dict)    # (cx,cy) -> (template, flipped)
    tiles: bytearray = field(default_factory=bytearray)
    spawns: list = field(default_factory=list)    # (type, mx, my)
    draws: int = 0

    @property
    def width(self) -> int:
        return self.gw * CELL

    def at(self, mx: int, my: int) -> int:
        return self.tiles[my * self.width + mx]


# --- 1. critical path ---------------------------------------------------------
def _walk(st: prng.Stream, gw: int, gh: int, length: int) -> list:
    """Self-avoiding walk of `length` cells. One draw for the start column,
    then one draw per step choosing among the open neighbours (N,E,S,W order).
    A dead end restarts the walk from a fresh start draw (bounded: 8 tries,
    then the length shrinks by one — always terminates)."""
    while True:
        for _ in range(8):
            x, y = st.below(gw), 0
            path = [(x, y)]
            while len(path) < length:
                opts = [(x + dx, y + dy) for _, dx, dy in DIRS
                        if 0 <= x + dx < gw and 0 <= y + dy < gh
                        and (x + dx, y + dy) not in path]
                if not opts:
                    break
                x, y = opts[st.below(len(opts))]
                path.append((x, y))
            if len(path) == length:
                return path
        length -= 1


def _link(lv: Level, a, b) -> None:
    for bit, dx, dy in DIRS:
        if (a[0] + dx, a[1] + dy) == b:
            lv.cells[a] |= bit
            lv.cells[b] |= OPPOSITE[bit]
            return
    raise AssertionError("cells not adjacent")


def generate(run_seed: int, floor: int, templates: list[Template] | None = None,
             gw: int = 4, gh: int = 4) -> Level:
    templates = templates or load_templates()
    st = prng.Stream(prng.level_seed(run_seed, floor))
    lv = Level(gw, gh)

    # Depth scales the path: floor 0 -> 5 cells, +1 every two floors, cap 9.
    length = min(5 + floor // 2, 9)
    lv.path = _walk(st, gw, gh, length)
    for c in lv.path:
        lv.cells[c] = 0
        lv.kind[c] = "normal"
    lv.kind[lv.path[0]] = "start"
    lv.kind[lv.path[-1]] = "boss"
    for a, b in zip(lv.path, lv.path[1:]):
        _link(lv, a, b)

    # --- 2. branches: 2 attempts, each grows 1-2 cells off a non-boss path cell
    for _ in range(2):
        root = lv.path[st.below(len(lv.path) - 1)]
        cur = root
        grow = 1 + st.below(2)
        for _ in range(grow):
            opts = [(cur[0] + dx, cur[1] + dy) for _, dx, dy in DIRS
                    if 0 <= cur[0] + dx < gw and 0 <= cur[1] + dy < gh
                    and (cur[0] + dx, cur[1] + dy) not in lv.cells]
            if not opts:
                break
            nxt = opts[st.below(len(opts))]
            lv.cells[nxt] = 0
            lv.kind[nxt] = "normal"
            _link(lv, cur, nxt)
            cur = nxt
        if cur != root:
            lv.kind[cur] = "treasure"

    # --- 3. loops: each occupied pair not yet joined gets a door with p=40/256.
    # Pairs are visited in row-major order of the first cell, E then S, so the
    # draw order is fixed. Boss cell never gains a second door (one way in).
    boss = lv.path[-1]
    for cy in range(gh):
        for cx in range(gw):
            a = (cx, cy)
            if a not in lv.cells or a == boss:
                continue
            for bit, dx, dy in ((E, 1, 0), (S, 0, 1)):
                b = (cx + dx, cy + dy)
                if b in lv.cells and b != boss and not lv.cells[a] & bit:
                    if st.chance(40):
                        _link(lv, a, b)

    # --- 4. pick templates (row-major order) ---------------------------------
    for cy in range(gh):
        for cx in range(gw):
            c = (cx, cy)
            if c not in lv.cells:
                continue
            need = lv.cells[c]
            pool = []
            for t in templates:
                if t.type != lv.kind[c]:
                    continue
                for v in ([t, t.mirrored()] if t.flip else [t]):
                    if v.doors & need == need:
                        pool.append(v)
            if not pool:
                raise RuntimeError(f"no template for {lv.kind[c]} doors={need:04b}")
            # Weights are rescaled into one 256-sum draw (spec §3.4 step 4).
            ws = [v.weight for v in pool]
            total = sum(ws)
            scaled = [max(1, w * 256 // total) for w in ws]
            while sum(scaled) > 256:
                scaled[scaled.index(max(scaled))] -= 1
            lv.choice[c] = pool[st.weighted(scaled)]

    # --- 5. stamp ------------------------------------------------------------
    w, h = gw * CELL, gh * CELL
    lv.tiles = bytearray([MT["void"]] * (w * h))
    for (cx, cy), t in sorted(lv.choice.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        ox, oy = cx * CELL, cy * CELL
        doors = lv.cells[(cx, cy)]
        for y in range(CELL):
            for x in range(CELL):
                edge = x in (0, CELL - 1) or y in (0, CELL - 1)
                if edge:
                    gap = ((y == 0 and doors & N) or (y == CELL - 1 and doors & S)) and x in (7, 8)
                    gap = gap or (((x == 0 and doors & W) or (x == CELL - 1 and doors & E)) and y in (7, 8))
                    v = MT["door"] if gap else MT["#"]
                else:
                    ch = t.rows[y - 1][x - 1]
                    if ch in MARKERS:
                        lv.spawns.append((MARKERS[ch], ox + x, oy + y))
                        v = MT["."]
                    else:
                        v = MT[ch]
                lv.tiles[(oy + y) * w + ox + x] = v
    lv.draws = st.draws
    return lv


# --- validation (the template linter + the per-level invariant) ---------------
def reachable(lv: Level, start) -> set:
    w, h = lv.width, lv.gh * CELL
    seen, todo = {start}, [start]
    while todo:
        x, y = todo.pop()
        for _, dx, dy in DIRS:
            q = (x + dx, y + dy)
            if 0 <= q[0] < w and 0 <= q[1] < h and q not in seen and lv.at(*q) in WALKABLE:
                seen.add(q)
                todo.append(q)
    return seen


def validate(lv: Level) -> list[str]:
    """Every spawn and the exit must be reachable on foot from the start."""
    errs = []
    starts = [(x, y) for t, x, y in lv.spawns if t == MARKERS["s"]]
    if not starts:
        return ["no start marker"]
    reach = reachable(lv, starts[0])
    for t, x, y in lv.spawns:
        if (x, y) not in reach:
            errs.append(f"spawn type {t} at ({x},{y}) unreachable")
    exits = [i for i, v in enumerate(lv.tiles) if v == MT["x"]]
    if not exits:
        errs.append("no exit tile")
    for i in exits:
        if (i % lv.width, i // lv.width) not in reach:
            errs.append(f"exit at {i % lv.width},{i // lv.width} unreachable")
    return errs


def lint_templates(templates: list[Template]) -> list[str]:
    """The per-template rules of spec 03 §6, checked on each orientation:

    * door reach — stamped alone with ALL its doors open, every door gap
      reaches every marker (so any subset the generator opens is fine: the
      interior connectivity does not depend on which doors exist);
    * pack spread — any two `e` markers are >= 3 rows apart (OAM line
      ledger, spec 02 §3);
    * start rooms carry an `s`, boss rooms a `B` and an `x`.
    """
    errs = []
    for t0 in templates:
        for t in ([t0, t0.mirrored()] if t0.flip else [t0]):
            lv = Level(1, 1)
            lv.cells[(0, 0)] = t.doors
            lv.choice[(0, 0)] = t
            lv.tiles = bytearray(CELL * CELL)
            # reuse the stamp rules for one cell
            for y in range(CELL):
                for x in range(CELL):
                    edge = x in (0, CELL - 1) or y in (0, CELL - 1)
                    if edge:
                        gap = ((y == 0 and t.doors & N) or (y == CELL - 1 and t.doors & S)) and x in (7, 8)
                        gap = gap or (((x == 0 and t.doors & W) or (x == CELL - 1 and t.doors & E)) and y in (7, 8))
                        v = MT["door"] if gap else MT["#"]
                    else:
                        ch = t.rows[y - 1][x - 1]
                        if ch in MARKERS:
                            lv.spawns.append((MARKERS[ch], x, y))
                            v = MT["."]
                        else:
                            v = MT[ch]
                    lv.tiles[y * CELL + x] = v
            gaps = {N: (7, 0), S: (7, CELL - 1), W: (0, 7), E: (CELL - 1, 7)}
            targets = [(x, y) for _, x, y in lv.spawns]
            targets += [(i % CELL, i // CELL) for i, v in enumerate(lv.tiles) if v == MT["x"]]
            for bit, g in gaps.items():
                if not t.doors & bit:
                    continue
                reach = reachable(lv, g)
                missing = [p for p in targets if p not in reach]
                if missing:
                    errs.append(f"{t.name}: door {'NESW'[[N, E, S, W].index(bit)]} cannot reach {missing[:3]}")
                for other, g2 in gaps.items():
                    if t.doors & other and g2 not in reach:
                        errs.append(f"{t.name}: door gaps not mutually connected")
            rows = sorted(y for k, _, y in lv.spawns if k == MARKERS["e"])
            if any(b - a < 3 for a, b in zip(rows, rows[1:])):
                errs.append(f"{t.name}: enemy markers closer than 3 rows ({rows})")
            kinds = {k for k, *_ in lv.spawns}
            if t.type == "start" and MARKERS["s"] not in kinds:
                errs.append(f"{t.name}: start room without s")
            if t.type == "boss" and not (MARKERS["B"] in kinds and MT["x"] in lv.tiles):
                errs.append(f"{t.name}: boss room needs B and x")
    return sorted(set(errs))


def ascii_map(lv: Level) -> str:
    inv = {v: k for k, v in MT.items() if len(k) == 1}
    inv[MT["void"]] = " "
    inv[MT["door"]] = "+"
    rows = []
    for y in range(lv.gh * CELL):
        rows.append("".join(inv.get(lv.at(x, y), "?") for x in range(lv.width)))
    for t, x, y in lv.spawns:
        r = list(rows[y])
        r[x] = "secB"[t - 1]
        rows[y] = "".join(r)
    return "\n".join(rows)


if __name__ == "__main__":
    seed = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x1234
    floor = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    lv = generate(seed, floor)
    print(ascii_map(lv))
    print(f"path={lv.path} draws={lv.draws} spawns={len(lv.spawns)} errs={validate(lv)}")
