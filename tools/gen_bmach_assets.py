#!/usr/bin/env python3
"""Generate the `bmach` rail's art — the buried machine, in 16x16 blocks.

WHAT MAKES THIS RAIL DIFFERENT: its BG1 is switched to 16x16 tiles, so one
tilemap entry covers four times the area and a 64x64 map holds a
1024x1024-pixel world in 8 KB. The cost lands entirely in CHR, because a
block is four tiles at the FIXED offsets N, N+1, N+16, N+17
(SnesPpu.cpp:241-245) and two blocks that share an 8x8 corner cannot share
storage for it. So the budget here is the DISTINCT BLOCK COUNT, and the
packing is laid out to spend exactly four slots per block and no more: eight
blocks fill a 16-slot stride pair with zero gap.

The source art is `vendor/art/buried_machine` — seven continuous-tone sheets
with 0.00% of aligned 8x8 blocks constant, so they are RESAMPLED and never
sliced. That pack's README carries the measurement and the provenance.
"""
import pathlib
import sys
from collections import deque

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import gen_mill_assets as G                                       # noqa: E402
from kit_import import is_key, key_to_alpha, resample, map_to_palette  # noqa

KIT = ROOT / "vendor" / "art" / "buried_machine"
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets")

# --- the palette ------------------------------------------------------------
# BG1 is 4bpp under mode 2, so a tilemap entry picks one of EIGHT groups of
# sixteen and the palette field is per-BLOCK. That is what pays for the
# descent: the ruins, the machine and the furnace are three sub-palettes, and
# a block changes zone by changing its palette field, not by spending CHR.
SW_SAND = [(3, 2, 1), (6, 4, 2), (9, 6, 3), (12, 9, 5), (15, 12, 7),
           (18, 15, 10), (22, 19, 13), (25, 22, 16), (28, 25, 20), (30, 28, 24)]
SW_STEEL = [(2, 2, 4), (3, 4, 6), (5, 6, 8), (7, 8, 11), (9, 11, 14),
            (12, 14, 17), (15, 17, 20), (19, 21, 24), (23, 25, 27), (27, 28, 30)]
SW_HOT = [(4, 1, 0), (9, 2, 0), (14, 3, 0), (19, 5, 1), (24, 7, 1),
          (28, 10, 2), (30, 14, 3), (31, 19, 5), (31, 24, 10), (31, 29, 20)]

SUBPAL = 16                       # entries per 4bpp group
PAL_SAND, PAL_STEEL, PAL_HOT = 0, 1, 2


def _ramp(sw):
    """15 steps + a transparent slot 0: one 4bpp group."""
    return [0] + [G.rgb(*c) for c in G._stretch(G._anchors(sw), 15)]


PAL_BG1 = _ramp(SW_SAND) + _ramp(SW_STEEL) + _ramp(SW_HOT)


def group(n):
    """The palette list and index base a block of zone `n` maps against.

    Entry 0 of every 4bpp group is TRANSPARENT and is not offered to the
    fitter, so the fifteen it maps into are entries 1..15 and no block can
    accidentally quantise a lit pixel onto the transparent slot.
    """
    return PAL_BG1[n * SUBPAL + 1:(n + 1) * SUBPAL], 1


# --- reading the sheets -----------------------------------------------------
def components(path, minarea=800):
    """Every isolated asset on a sheet, as (x, y, w, h). Both keying paths:
    the magenta five and the one that arrived alpha-cut."""
    im = Image.open(path)
    W, H = im.size
    px = im.convert("RGB").load()
    solid = [[0 if is_key(*px[x, y]) else 1 for x in range(W)] for y in range(H)]
    if im.mode == "RGBA":
        ac = im.getchannel("A").load()
        for y in range(H):
            for x in range(W):
                if ac[x, y] < 128:
                    solid[y][x] = 0
    seen = [[0] * W for _ in range(H)]
    out = []
    for sy in range(H):
        for sx in range(W):
            if seen[sy][sx] or not solid[sy][sx]:
                continue
            q = deque([(sx, sy)])
            seen[sy][sx] = 1
            x0 = x1 = sx
            y0 = y1 = sy
            area = 0
            while q:
                x, y = q.popleft()
                area += 1
                x0, x1 = min(x0, x), max(x1, x)
                y0, y1 = min(y0, y), max(y1, y)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if (0 <= nx < W and 0 <= ny < H and not seen[ny][nx]
                                and solid[ny][nx]):
                            seen[ny][nx] = 1
                            q.append((nx, ny))
            if area >= minarea:
                out.append((x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    return im, sorted(out, key=lambda c: (c[1], c[0]))


UNIT = 96.0            # native sheet pixels per 16-pixel block


def block_run(im, box, zone, bw=None, bh=None):
    """One asset -> a bw x bh grid of 16x16 blocks, indexed against `zone`.

    The run size comes from the asset's NATIVE ASPECT rather than being forced
    to one block: a doorway jamb is 1x2 on the sheet and squashing it into a
    single block is what turns readable art into mush.
    """
    x, y, w, h = box
    bw = bw or max(1, min(4, round(w / UNIT)))
    bh = bh or max(1, min(5, round(h / UNIT)))
    pal, ix0 = group(zone)
    src = key_to_alpha(im.crop((x, y, x + w, y + h)))
    buf = map_to_palette(resample(src, (bw * 16, bh * 16)), pal, ix0)
    grid = []
    for by in range(bh):
        for bx in range(bw):
            grid.append(tuple(tuple(buf[by * 16 + r][bx * 16:bx * 16 + 16])
                              for r in range(16)))
    return bw, bh, grid


# --- CHR ---------------------------------------------------------------------
def encode_4bpp(rows, who):
    """One 8x8 tile, 32 bytes: bitplane pair 0/1 interleaved by row, then 2/3."""
    out = bytearray()
    for pair in range(2):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                assert 0 <= v < 16, f"{who}: index {v} is not 4bpp"
                lo |= ((v >> (pair * 2)) & 1) << (7 - x)
                hi |= ((v >> (pair * 2 + 1)) & 1) << (7 - x)
            out += bytes((lo, hi))
    return bytes(out)


def quarters(block):
    """A 16x16 block as its four 8x8 tiles, in the PPU's own quad order:
    N = top-left, N+1 = top-right, N+16 = bottom-left, N+17 = bottom-right
    (SnesPpu.cpp:241-245 — `+1` for the right half via useSecondTile, `+16`
    for the lower row via (realY + VScroll) & 8)."""
    tl = tuple(r[0:8] for r in block[0:8])
    tr = tuple(r[8:16] for r in block[0:8])
    bl = tuple(r[0:8] for r in block[8:16])
    br = tuple(r[8:16] for r in block[8:16])
    return tl, tr, bl, br


BLOCKS_PER_BAND = 8            # 8 blocks fill a 16-slot stride PAIR exactly


def pack_chr(blocks):
    """Lay `blocks` into CHR at four slots each and return (bytes, base_ids).

    THE PACKING IS THE WHOLE ECONOMY. The quad's `+16` fixes a 16-tile stride,
    so blocks are laid eight to a 32-slot band — even N across the band's first
    row, their lower halves in its second. Four slots per block, zero gap. Lay
    them consecutively instead and every block would burn 32 slots.
    """
    nband = (len(blocks) + BLOCKS_PER_BAND - 1) // BLOCKS_PER_BAND
    slots = [None] * (nband * 32)
    base = []
    for k, blk in enumerate(blocks):
        n = (k // BLOCKS_PER_BAND) * 32 + (k % BLOCKS_PER_BAND) * 2
        tl, tr, bl, br = quarters(blk)
        slots[n], slots[n + 1], slots[n + 16], slots[n + 17] = tl, tr, bl, br
        base.append(n)
    blank = tuple((0,) * 8 for _ in range(8))
    out = bytearray()
    for i, t in enumerate(slots):
        out += encode_4bpp(t if t is not None else blank, f"slot {i}")
    return bytes(out), base


# --- the block kit ----------------------------------------------------------
# WHICH SHEET FEEDS WHICH ZONE. The descent is three palettes and the art is
# sorted into them here rather than at draw time: a block carries its zone in
# the tilemap entry's palette field, so the same masonry block can appear in
# the ruins warm and deep down cold if it is entered twice. It is not, today —
# every block is entered once, and the zone is a property of the sheet it came
# from.
# NO CAPS. These were 22/20/16/12/14 and that left 352 of the 436 supplied
# assets — 81% of the art — unread, while the whole design conversation was
# being had against a vocabulary a quarter the size of the one on disk. The
# cap was self-imposed and was never the hardware's: the tilemap index is 10
# bits, so 1024 slots at four per block is 256 blocks RESIDENT, and a room's
# terrain measures 7-11 distinct blocks. The library lives in ROM and the
# resident page is per room.
SHEETS = (
    ("sandstone_ruins.png",     PAL_SAND,  None),
    ("machine_structure.png",   PAL_STEEL, None),
    ("platforms.png",           PAL_STEEL, None),
    ("pipes.png",               PAL_STEEL, None),
    ("hazards_transitions.png", PAL_HOT,   None),
)


def build_kit(budget=128):
    """Every kit block, deduplicated, with a map from source asset to its run.

    Dedup is by CONTENT and it is what makes the budget reachable: flat
    structural fills recur across a sheet and across sheets, and two identical
    16x16 blocks are one block however many assets drew them.
    """
    # THE EMPTY BLOCK IS ALWAYS INDEX 0. Every cell the world does not place
    # something in resolves here, and it must be genuinely transparent —
    # filling air with a solid block turns the whole map into a slab with
    # rectangles cut in it, which is exactly what the first render showed.
    empty = tuple((0,) * 16 for _ in range(16))
    blocks, kit = {empty: 0}, [empty]
    runs = []
    for fname, zone, take in SHEETS:
        im, cs = components(str(KIT / fname))
        if take is not None:
            cs = cs[::max(1, len(cs) // take)][:take]
        for c in cs:
            bw, bh, grid = block_run(im, c, zone)
            ids = []
            for blk in grid:
                key = blk
                if key not in blocks:
                    blocks[key] = len(kit)
                    kit.append(blk)
                ids.append(blocks[key])
            runs.append((fname, zone, bw, bh, ids))
    return kit, runs


# --- the rods: the parts that slide -----------------------------------------
# A rod is built from its MEDIAN ROW PROFILE rather than from the resampled
# block, and that is not a shortcut — it is what makes vertical invariance
# hold BY CONSTRUCTION. Art driven by a vertical offset column must be
# identical along its length or the variation visibly travels with the column;
# reconstructing every row from one profile guarantees it, where inspecting a
# resampled block only hopes for it.
#
# The pack README records what the reconstruction costs (under three grey
# levels of 255 for the nine segments that sit at the grain floor) and why
# `row_variance == 0` could not be used as the acceptance test on grainy
# source: pure noise with no structure scores 48 of 64 on it.
ROD_SHEET = "rod_segments.png"
ROD_INSET = 0.03               # drop the antialiased end caps before profiling


def rod_profiles(zone=PAL_STEEL, want=9):
    """The `want` most uniform rod segments, each as ONE 16-wide index row.

    Ranked by mean absolute deviation from their own median profile, which is
    the measure that separates grain from structure. The nine that pass sit at
    1.3-2.6; the structured ones run to 35.
    """
    import statistics
    im, cs = components(str(KIT / ROD_SHEET))
    pal, ix0 = group(zone)
    scored = []
    for c in cs:
        x, y, w, h = c
        if h < 2.2 * w:
            continue                      # not a shaft: too squat
        inset = max(4, int(h * ROD_INSET))
        src = key_to_alpha(im.crop((x, y + inset, x + w, y + h - inset)))
        small = resample(src, (16, 64)).convert("RGB").load()
        prof = [statistics.median([small[i, r][0] for r in range(64)])
                for i in range(16)]
        dev = statistics.mean(
            sum(abs(small[i, r][0] - prof[i]) for i in range(16)) / 16
            for r in range(64))
        scored.append((dev, c))
    scored.sort()
    rods = []
    for dev, c in scored[:want]:
        x, y, w, h = c
        inset = max(4, int(h * ROD_INSET))
        src = key_to_alpha(im.crop((x, y + inset, x + w, y + h - inset)))
        buf = map_to_palette(resample(src, (16, 64)), pal, ix0)
        # the profile: per-column MODE down the 64 rows, so one bad row cannot
        # move it the way a mean would
        row = tuple(max(set(col), key=col.count)
                    for col in ([buf[r][i] for r in range(64)] for i in range(16)))
        rods.append((round(dev, 2), row))
    return rods


def rod_block(row):
    """A rod segment as a 16x16 block: the profile, sixteen times."""
    return tuple(row for _ in range(16))


# --- the world ---------------------------------------------------------------
# 64 x 64 BLOCKS, which under tiles16 is 1024 x 1024 PIXELS in an 8 KB map --
# four screens wide by four and a half tall, continuous, no repeats. That is
# the whole reason the rail exists: the same map at 8x8 would cover 512 x 512.
COLS = 64
ROWS = 64
WORLD_W = COLS * 16
WORLD_H = ROWS * 16

# the descent, in map rows
SKY_ROWS = 4                   # open air above the ruins
RUIN_TOP = SKY_ROWS
MACHINE_TOP = 22               # the ruins give way
FURNACE_TOP = 46               # and the machine stands over the heat

# collision classes, one per map cell
AIR, SOLID, PLATFORM, HAZARD = 0, 1, 2, 3


def zone_of_row(r):
    if r < MACHINE_TOP:
        return PAL_SAND
    if r < FURNACE_TOP:
        return PAL_STEEL
    return PAL_HOT


def entry(base_slot, pal, hflip=False, vflip=False):
    """One tilemap word. Under tiles16 the index field is the block's BASE
    slot N — the PPU derives N+1/N+16/N+17 itself, so nothing else is stored.
    Bits: 0-9 index, 10-12 palette, 13 priority, 14 H flip, 15 V flip."""
    return (base_slot & 0x3FF) | ((pal & 7) << 10) \
        | (0x4000 if hflip else 0) | (0x8000 if vflip else 0)


def kit_by_sheet(runs):
    """Block ids grouped by the sheet they came from, so the world asks for a
    PLATFORM or a PIPE rather than for a number nobody can check."""
    out = {}
    for fname, zone, bw, bh, ids in runs:
        out.setdefault(fname, []).extend(ids)
    return out


def flattest(kit, ids):
    """The most uniform block in a pool, by pixel variance.

    MASS WANTS ONE BLOCK, NOT TWENTY. Picking a different block per cell reads
    as television static rather than masonry — the first carved render showed
    exactly that. Variety belongs on edges and features; the body of a wall is
    one repeated block, and which one is measured rather than chosen.
    """
    best, score = ids[0], None
    for i in ids:
        flat = [v for row in kit[i] for v in row]
        if not flat:
            continue
        m = sum(flat) / len(flat)
        var = sum((v - m) ** 2 for v in flat) / len(flat)
        lit = sum(1 for v in flat if v) / len(flat)
        if lit < 0.9:                 # a fill block has to actually be solid
            continue
        if score is None or var < score:
            best, score = i, var
    return best


# --- terrain: synthesised, not sourced --------------------------------------
# THE SHEETS CONTAIN OBJECTS, NOT TERRAIN. Arches, columns, pipes and platforms
# are drawn things; edges and corners are a SYSTEM, and asking an illustrator
# for a role-tagged autotile set gets a picture with labels on it rather than a
# set. So terrain is derived here from two inputs the rail already has — a
# zone's flat fill block and its palette ramp — the same way every other
# generated asset in this tree is made.
N, S, E, W = 1, 2, 4, 8         # which faces are EXPOSED (open to air)


def _shade(v, lift):
    """Move an index along its 15-step ramp without leaving the group."""
    if v == 0:
        return 0
    return max(1, min(15, v + lift))


def terrain_block(fill, faces):
    """One autotile piece: the fill block, lit where it meets open air.

    THE SHADING IS DIRECTIONAL, because a non-directional rim made all sixteen
    pieces look alike — seen on the first render, where a floor edge and a
    ceiling edge were indistinguishable. Light falls from above, so a top face
    gets a bright lip over a dark shoulder (a lit edge reads as a SURFACE), a
    bottom face gets shadow alone (an underside is never lit), and the sides
    get a weaker version. That asymmetry is what makes a chamber read as a room
    rather than as a rectangle.

    `faces` is an OR of N/S/E/W for the sides open to air. All sixteen
    combinations are legal, so the caller indexes this by a neighbour bitmask
    and never thinks about corners.
    """
    out = []
    for y in range(16):
        row = []
        for x in range(16):
            v = fill[y][x]
            lift = 0
            if faces & N:
                if y == 0:
                    lift = max(lift, 7)
                elif y == 1:
                    lift = max(lift, 5)
                elif y < 5:
                    lift = min(lift, -3)
            if faces & S:
                if y >= 14:
                    lift = min(lift, -6)
                elif y >= 11:
                    lift = min(lift, -3)
            if faces & W:
                if x == 0:
                    lift = max(lift, 4)
                elif x < 3:
                    lift = min(lift, -2)
            if faces & E:
                if x == 15:
                    lift = min(lift, -5)
                elif x > 12:
                    lift = min(lift, -2)
            row.append(_shade(v, lift))
        out.append(tuple(row))
    return tuple(out)


def terrain_set(fill):
    """The sixteen pieces, indexed by exposed-face bitmask."""
    return [terrain_block(fill, f) for f in range(16)]


def world(kit, runs, base, terrain, fixtures):
    """The map, the collision grid, and the piston banks.

    CONNECTIVITY IS CONSTRUCTED AND THEN PROVED. The first version carved
    chambers and shafts independently and produced SEVEN disconnected air
    regions with 28% of the world solid dead rock — a world you cannot walk
    through, which rendered green because nothing checked. Here every shaft is
    cut from one chamber's floor to the NEXT chamber's ceiling, so the route is
    connected by the way it is built, and `check_world` re-derives it with a
    flood fill and refuses to emit a map that is not one region.

    Terrain is autotiled: every solid cell picks its piece from the exposed
    faces of its neighbours, so chambers get lit floors, dark ceilings and
    shaded walls without a single edge being placed by hand.
    """
    by = kit_by_sheet(runs)
    sand, steel = by["sandstone_ruins.png"], by["machine_structure.png"]
    deck, pipe = by["platforms.png"], by["pipes.png"]
    hot = by["hazards_transitions.png"]

    def pick(pool, salt):
        return pool[salt % len(pool)]

    grid = [[SOLID] * COLS for _ in range(ROWS)]
    prop = {}                       # cells that carry an OBJECT, not terrain

    for r in range(RUIN_TOP):       # the sky
        for c in range(COLS):
            grid[r][c] = AIR

    # --- the route ----------------------------------------------------------
    # Seven halls down the map, alternating side to side, each joined to the
    # next by a shaft cut through the floor between them. The last one is the
    # furnace hall, which is the destination and fills the band that used to be
    # dead rock.
    # THE WIDTHS ARE WHAT MAKE THE ROUTE CONNECT, and the first version got it
    # wrong: halls 20-36 wide alternating sides of a 64-column map never
    # OVERLAP, so every shaft between them started in solid rock and the world
    # came apart into seven regions. Each hall now spans more than half the
    # map, so consecutive halls always share columns and a shaft always has
    # somewhere legal to land.
    halls, r, left = [], RUIN_TOP + 2, True
    while r < ROWS - 10:
        w = 34 + (len(halls) % 3) * 4
        h = 6 + (len(halls) % 2) * 2
        c0 = 2 if left else COLS - 2 - w
        for rr in range(r, r + h):
            for cc in range(c0, c0 + w):
                grid[rr][cc] = AIR
        halls.append({"row": r, "col": c0, "w": w, "h": h,
                      "zone": None, "role": None})
        r += h + 3
        left = not left
    # the furnace hall: wide, deep, and the floor of the world
    fr = ROWS - 9
    for rr in range(fr, ROWS - 2):
        for cc in range(2, COLS - 2):
            grid[rr][cc] = AIR
    halls.append({"row": fr, "col": 2, "w": COLS - 4, "h": ROWS - 2 - fr,
                  "zone": PAL_HOT, "role": "furnace"})

    # --- ZONE IS A PROPERTY OF THE HALL, NOT OF THE ROW --------------------
    # A row threshold let one hall straddle two zones and painted a quarter of
    # the props in a ramp they were never fitted against. A room has one
    # material; the room BETWEEN two materials is a transition and says so.
    n = len(halls)
    for i, hall in enumerate(halls):
        if hall["zone"] is not None:
            continue
        t = i / max(1, n - 1)
        if t < 0.33:
            hall["zone"], hall["role"] = PAL_SAND, "ruins"
        elif t < 0.45:
            hall["zone"], hall["role"] = PAL_SAND, "transition"
        elif t < 0.80:
            hall["zone"], hall["role"] = PAL_STEEL, "machine"
        else:
            hall["zone"], hall["role"] = PAL_STEEL, "transition"

    # --- the entrance: the sky opens into the first hall --------------------
    h0 = halls[0]
    hr, ex = h0["row"], h0["col"] + 4
    for rr in range(0, hr + 1):
        for cc in range(ex, ex + 3):
            grid[rr][cc] = AIR

    # --- the shafts, each cut BETWEEN a pair, so the route cannot break -----
    shaft_cols = set()
    for a, b in zip(halls, halls[1:]):
        ar, ac, aw, ah = a["row"], a["col"], a["w"], a["h"]
        br, bc, bw = b["row"], b["col"], b["w"]
        lo, hi = max(ac, bc), min(ac + aw, bc + bw)
        sx = (lo + hi) // 2 - 1 if hi - lo >= 4 else max(ac, bc)
        for rr in range(ar + ah, br + 1):
            for cc in range(sx, sx + 3):
                if 0 <= cc < COLS:
                    grid[rr][cc] = AIR
        shaft_cols.update(range(sx - 1, sx + 4))

    # --- the piston banks, standing in the machine halls --------------------
    banks = []
    for i, hall in enumerate(halls):
        hr, c0, w, h = hall["row"], hall["col"], hall["w"], hall["h"]
        if hall["role"] not in ("machine", "transition") or len(banks) >= 4:
            continue
        # A BANK MAY NOT STAND OVER A SHAFT MOUTH. One did, sealing the only
        # way down to the furnace hall and splitting the world in two — caught
        # by the gate, not by looking. Slide it along until it clears.
        bx = c0 + 5 + i * 3
        while bx + 4 < c0 + w and any(x in shaft_cols for x in range(bx, bx + 4)):
            bx += 4
        if bx + 4 >= c0 + w:
            continue
        banks.append({"col0": bx, "width": 4, "phase": len(banks) * 32,
                      "travel": 24 + len(banks) * 8, "row0": hr, "rows": h})
        # THE BANK LEAVES HEADROOM. Filling the hall's full height walled it
        # in half and orphaned everything past it — two of the three regions
        # the gate found. A piston is a column you get past and ride, not a
        # partition, so the top two rows of the hall stay open above it.
        for cc in range(bx, bx + 4):
            for rr in range(hr + 2, hr + h):
                grid[rr][cc] = SOLID

    # --- props: objects from the sheets, on hall floors and ceilings --------
    # A ZONE MAY ONLY DRAW FROM POOLS FITTED TO IT. `deck` is fitted against
    # the steel ramp, so lending it to a sandstone hall painted twelve props in
    # a ramp they were never quantised for — the last of the mixing, and
    # invisible until it was counted.
    # --- fixtures -----------------------------------------------------------
    # PLACED AS ASSETS, NOT AS BLOCKS. Each fixture keeps the footprint the
    # artist drew it at, so an arch arrives as an arch instead of as four
    # blocks that happened to pass an edge test. Pistons are extensible and
    # take their length from the hall they stand in.
    by_zone = {}
    for fx in fixtures:
        by_zone.setdefault(fx.zone, []).append(fx)

    def free(r, c, w, h):
        return all(0 <= r + dr < ROWS and 0 <= c + dc < COLS
                   and grid[r + dr][c + dc] == AIR
                   and (r + dr, c + dc) not in prop
                   for dr in range(h) for dc in range(w))

    def place(fx, r, c, length=None):
        w, h, cells = fx.footprint(length)
        if not free(r, c, w, h):
            return False
        for dr, dc, b in cells:
            prop[(r + dr, c + dc)] = b
        return True

    for n, hall in enumerate(halls):
        hr, c0, w, h = hall["row"], hall["col"], hall["w"], hall["h"]
        pool = [f for f in by_zone.get(hall["zone"], []) if f.kind == "unit"]
        ext = [f for f in by_zone.get(hall["zone"], []) if f.kind == "extensible"]
        if not pool:
            continue
        floor = hr + h - 1
        # a bay rhythm rather than a stride: fixtures are laid left to right
        # with a gap between them, so the hall reads as a colonnade of things
        # that each occupy their own width.
        c = c0 + 1
        k = n
        while c < c0 + w - 2:
            fx = pool[k % len(pool)]
            k += 1
            if place(fx, floor - fx.h + 1, c):
                c += fx.w + 1 + (k % 2)
            else:
                c += 1
        # one piston per machine hall, as tall as the hall allows
        if ext and hall["role"] in ("machine", "transition"):
            fx = ext[n % len(ext)]
            length = max(1, h - 3)
            for cc in (c0 + w // 3, c0 + 2 * w // 3):
                if place(fx, hr, cc, length):
                    break
    return grid, halls, banks, prop


def check_world(grid):
    """Refuse a world you cannot walk through.

    THE GATE THAT WAS MISSING. The first layout rendered as a plausible picture
    while being seven disconnected air regions with a quarter of the map dead
    rock. A picture cannot show that and a look did not catch it; a flood fill
    does, in milliseconds, every build. Returns the stats so the emitter can
    print them rather than merely pass.
    """
    from collections import deque
    seen = [[False] * COLS for _ in range(ROWS)]
    regions = []
    for r in range(ROWS):
        for c in range(COLS):
            if seen[r][c] or grid[r][c] != AIR:
                continue
            q = deque([(r, c)])
            seen[r][c] = True
            n = 0
            rows = set()
            while q:
                y, x = q.popleft()
                n += 1
                rows.add(y)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if (0 <= ny < ROWS and 0 <= nx < COLS and not seen[ny][nx]
                            and grid[ny][nx] == AIR):
                        seen[ny][nx] = True
                        q.append((ny, nx))
            regions.append((n, min(rows), max(rows)))
    regions.sort(reverse=True)
    big = regions[0]
    assert len(regions) == 1, (
        f"the world is {len(regions)} disconnected air regions, not one: "
        f"{[(n, a, b) for n, a, b in regions[:6]]}")
    assert big[1] <= RUIN_TOP and big[2] >= ROWS - 4, (
        f"the route spans rows {big[1]}..{big[2]}, not surface to floor")
    dead = 0
    for r in range(ROWS):
        if all(grid[r][c] != AIR for c in range(COLS)):
            dead += 1
    assert dead <= 6, f"{dead} map rows have no route in them at all"
    return {"regions": len(regions), "air": big[0],
            "spans": (big[1], big[2]), "dead_rows": dead}


def faces_of(grid, r, c):
    """Which sides of a solid cell are open to air — the autotile index."""
    f = 0
    if r == 0 or grid[r - 1][c] == AIR:
        f |= N
    if r == ROWS - 1 or grid[r + 1][c] == AIR:
        f |= S
    if c > 0 and grid[r][c - 1] == AIR:
        f |= W
    if c < COLS - 1 and grid[r][c + 1] == AIR:
        f |= E
    return f


def zone_map(halls):
    """Per-CELL material, so a transition hall can carry both.

    A row constant cannot express a transition — the material has to change
    THROUGH a room, not at its edge. A hall whose role is "transition" dithers
    between its own zone and the next one down on a vertical probability
    gradient, per block, because a 4bpp tilemap entry carries one palette field
    and the mixing therefore has to happen BETWEEN blocks rather than inside
    one. That is also how the hardware wants it done.
    """
    zm = [[None] * COLS for _ in range(ROWS)]
    order = list(halls)
    for n, h in enumerate(order):
        nxt = order[n + 1]["zone"] if n + 1 < len(order) else h["zone"]
        r0, r1 = h["row"], min(ROWS, h["row"] + h["h"])
        for r in range(r0, r1):
            for c in range(COLS):
                if h["role"] != "transition" or nxt == h["zone"]:
                    zm[r][c] = h["zone"]
                else:
                    # depth through the hall drives the odds; a stable hash of
                    # the cell decides, so the dither is deterministic
                    t = (r - r0 + 1) / max(1, r1 - r0)
                    k = ((r * 73856093) ^ (c * 19349663)) % 1000 / 1000.0
                    zm[r][c] = nxt if k < t else h["zone"]
    cur = order[0]["zone"]
    for r in range(ROWS):
        for c in range(COLS):
            if zm[r][c] is None:
                zm[r][c] = cur
        cur = zm[r][COLS // 2]
    return zm


def zone_rows(halls):
    """Which zone paints each map row, derived from the HALLS.

    Mass belongs to the room above it, so the material changes where a room
    changes rather than at an arbitrary row constant. This replaces
    `zone_of_row`, which was a threshold that let a hall straddle two zones and
    painted a quarter of the props in a ramp they had never been fitted to.
    """
    out = [None] * ROWS
    for h in halls:
        for r in range(h["row"], min(ROWS, h["row"] + h["h"])):
            out[r] = h["zone"]
    cur = halls[0]["zone"]
    for r in range(ROWS):
        if out[r] is None:
            out[r] = cur
        else:
            cur = out[r]
    return out


def paint(grid, prop, kit, terrain, base, zmap):
    """The tilemap: autotiled terrain everywhere, props where they were placed."""
    words = bytearray()
    for r in range(ROWS):
        for c in range(COLS):
            zone = zmap[r][c]
            if (r, c) in prop:
                w = entry(base[prop[(r, c)]], zone)
            elif grid[r][c] == AIR:
                w = entry(base[0], zone)
            else:
                w = entry(base[terrain[zone][faces_of(grid, r, c)]], zone)
            words += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(words)


def check_palette(prop, fitted, zrows):
    """No block may be painted in a ramp it was not fitted against.

    Every block is quantised against ONE 15-step ramp at kit time. Painting it
    with a different group does not recolour it — it re-reads its indices in
    the wrong ramp, and the block comes out in colours nobody chose. It is
    invisible in a thumbnail and obvious in a screenshot, which is why it
    survived three renders and is a gate now. Measured before this existed:
    15 of 59 props, 25%.
    """
    bad = [(r, c, fitted.get(b), zrows[r])
           for (r, c), b in prop.items() if fitted.get(b) != zrows[r]]
    assert not bad, (
        f"{len(bad)} of {len(prop)} props are painted in a ramp they were not "
        f"fitted against, e.g. {bad[:4]}")
    return len(prop)


# --- adjacency: what may sit next to what, derived from the pixels ----------
# THE KIT DOES NOT COME WITH RULES, so they are measured off the art. Two
# blocks may share a side when the strip of pixels they would present to each
# other agrees: a wall whose right column ends mid-course cannot butt against
# one whose left column starts somewhere else, and a lit strip cannot meet an
# empty one without a visible seam.
#
# The score weights the two disagreements differently on purpose. An OPACITY
# break — solid meeting transparent — is a hole in the picture and costs
# double; a VALUE difference is a shading step and costs its own size. Measured
# over all 12,321 ordered pairs the scores run 0 to 43 with a median of 11.75,
# so the rule discriminates rather than admitting everything.
OPACITY_WEIGHT = 2.0
EMPTY_PENALTY = 8.0            # a strip with no overlap at all is not a join
JOIN_MAX = 3.0                 # measured: median 13 partners per block here

OPPOSITE = {"E": "W", "W": "E", "N": "S", "S": "N"}


def edge_strips(block):
    """The four 16-pixel borders a block presents to its neighbours."""
    return {"N": tuple(block[0]), "S": tuple(block[15]),
            "W": tuple(r[0] for r in block), "E": tuple(r[15] for r in block)}


def seam_cost(leaving, arriving):
    """How badly two facing strips disagree. 0 is a seamless join."""
    import statistics
    breaks = sum(1 for a, b in zip(leaving, arriving) if (a != 0) != (b != 0))
    both = [(a, b) for a, b in zip(leaving, arriving) if a and b]
    step = statistics.mean(abs(a - b) for a, b in both) if both \
        else EMPTY_PENALTY
    return breaks * OPACITY_WEIGHT + step


def adjacency(kit, join_max=JOIN_MAX):
    """For every block and side, the blocks that may legally sit there.

    Returns {side: {block: [partners]}} for the four sides. `E` means "may sit
    to my right", and it is derived against that block's own `W` strip, so the
    relation is directional and is not assumed symmetric.
    """
    strips = [edge_strips(b) for b in kit]
    out = {}
    for side in ("E", "W", "N", "S"):
        opp = OPPOSITE[side]
        table = {}
        for i in range(len(kit)):
            table[i] = [j for j in range(len(kit))
                        if seam_cost(strips[i][side], strips[j][opp]) <= join_max]
        out[side] = table
    return out


TILEABLE_MIN = 6               # partners on a side before a block counts as
                               # terrain rather than as a thing standing alone


def classify(kit, adj):
    """Split the kit into what TILES and what STANDS ALONE.

    This falls out of the adjacency rather than being declared: a block most
    others can butt against is field material, and a block almost nothing joins
    is an object that has to be placed deliberately with air or a matching
    partner around it. Placing a prop as if it were terrain is what produced
    the seams in the first renders.
    """
    tileable, standalone = [], []
    for i in range(len(kit)):
        deg = min(len(adj[s][i]) for s in ("E", "W", "N", "S"))
        (tileable if deg >= TILEABLE_MIN else standalone).append(i)
    return tileable, standalone


def object_chains(kit, runs, adj, side="E", maxlen=4):
    """Seamless same-sheet chains of objects — the arrangement vocabulary.

    AN ARRANGEMENT IS NOT INVENTED, IT IS FOUND. A colonnade is whatever chain
    the adjacency says butts together without a seam; a pipe run is the same
    thing on the pipe sheet. Placing objects at a fixed stride, which is what
    the first world did, puts a seam between every pair because nothing
    checked whether they join.

    Measured on this kit: 327 seamless horizontal pairs and 138 vertical, 61
    objects that can begin a 3-run, and 28 with no horizontal partner at all —
    those last are returned by `loners` and must be placed with air beside them.
    """
    sheet = {}
    for fname, zone, bw, bh, ids in runs:
        for i in ids:
            sheet.setdefault(i, fname)
    out = []
    for i in range(len(kit)):
        if i not in sheet:            # synthesised terrain is not an object
            continue
        chain = [i]
        while len(chain) < maxlen:
            nxts = [j for j in adj[side][chain[-1]]
                    if j != chain[-1] and sheet.get(j) == sheet.get(i)
                    and j not in chain]
            if not nxts:
                break
            chain.append(nxts[0])
        if len(chain) >= 2:
            out.append((sheet[i], tuple(chain)))
    return out


def loners(kit, runs, adj):
    """Objects nothing joins on either side — placed alone, never in a row."""
    sheet = {}
    for fname, zone, bw, bh, ids in runs:
        for i in ids:
            sheet.setdefault(i, fname)
    # block 0 is the empty one — it is not an object and is never a prop
    return [i for i in range(1, len(kit))
            if i in sheet
            and not any(j != i and sheet.get(j) == sheet.get(i)
                        for j in adj["E"][i] + adj["W"][i])]


# --- fixtures: the unit of composition is the ASSET, not the block ----------
# THE ARTIST ALREADY GROUPED THESE AND THE FIRST PASS THREW IT AWAY. An arch
# drawn 2x2 on the sheet is four blocks that belong together; `block_run`
# recorded that footprint and `build_kit` kept it in `runs`, and then the world
# flattened everything into a bag of blocks and tried to re-derive the
# relationships by matching edges. Measured: 24 of 84 assets are multi-block,
# and every "arrangement" the edge walk produced was four blocks long because
# the walk's own cap was four.
#
# So a FIXTURE is an asset placed whole. Three kinds:
#   unit        — the asset's own bw x bh footprint, placed as one thing
#   extensible  — a cap, a repeatable body, a cap: the piston, whose length is
#                 a property of where it is standing rather than of the art
#   loner       — one block nothing joins, placed with air around it
class Fixture:
    __slots__ = ("kind", "zone", "w", "h", "cells", "body", "sheet")

    def __init__(self, kind, zone, w, h, cells, sheet, body=None):
        self.kind, self.zone, self.sheet = kind, zone, sheet
        self.w, self.h, self.cells, self.body = w, h, cells, body

    def footprint(self, length=None):
        """(w, h, [(dr, dc, block)]) — for an extensible fixture, `length` is
        how many body blocks sit between the caps."""
        if self.kind != "extensible":
            return self.w, self.h, self.cells
        n = max(1, length if length is not None else 1)
        out = [(0, 0, self.cells[0])]
        for k in range(n):
            out.append((1 + k, 0, self.body[k % len(self.body)]))
        out.append((1 + n, 0, self.cells[-1]))
        return 1, n + 2, out


def unit_fixtures(runs):
    """Every asset, as a fixture that keeps its footprint."""
    out = []
    for fname, zone, bw, bh, ids in runs:
        cells = [(k // bw, k % bw, ids[k]) for k in range(len(ids))]
        out.append(Fixture("unit", zone, bw, bh, cells, fname))
    return out


def piston_fixtures(runs, rod_ids, zone=PAL_STEEL):
    """Cap / body / cap, with the rod profiles as the repeatable middle.

    THIS IS THE SHAPE THE MECHANISM ACTUALLY NEEDS. A piston is not a picture
    of a fixed height — it is a head, a shaft as long as the hall it stands in,
    and a foot. The rods are the only blocks in the kit that may repeat
    vertically without the repeat showing, because they are built from one
    median row.
    """
    heads = [ids[0] for f, z, bw, bh, ids in runs
             if f == "pistons.png" and bh >= 2]
    feet = [ids[-1] for f, z, bw, bh, ids in runs
            if f == "pistons.png" and bh >= 2]
    if not heads:                      # the pistons sheet is objects-only here
        heads = feet = [rod_ids[0]]
    return [Fixture("extensible", zone, 1, 3,
                    [heads[i % len(heads)], feet[i % len(feet)]],
                    "pistons.png", body=[rod_ids[i % len(rod_ids)]])
            for i in range(len(rod_ids))]


# --- rooms -> world ---------------------------------------------------------
# THE ANCHORS PLACE WHOLE FIXTURES. The first room preview blitted a fixture's
# FIRST BLOCK, so a 1x2 arch showed its top half standing on nothing and a
# stair fragment appeared alone in mid-air — the same asset-splitting mistake
# the fixture model was built to end, resurfacing in the renderer that consumed
# it. An anchor now places the whole footprint, seated on the floor for `o` and
# hung from the ceiling for `x`, and refuses rather than placing a fragment.
def seat_fixture(fx, r, c, occupied, free_at, ceiling=False):
    """Whole-footprint placement at an anchor. Returns the cells or None."""
    w, h, cells = fx.footprint()
    top = r if ceiling else r - h + 1
    if not all(free_at(top + dr, c + dc) and (top + dr, c + dc) not in occupied
               for dr in range(h) for dc in range(w)):
        return None
    return [(top + dr, c + dc, b) for dr, dc, b in cells]


DRESS_EVERY = 3          # one border cell in this many gets an object


def dress_border(kit, plain, pool, r, c, side):
    """An object to stand in for a plain terrain piece on a room's border.

    ROOM TOPS AND WALLS WERE THE SAME BLOCK EVERYWHERE, which is what made the
    rooms read as boxes however good their interiors were. The sheets are full
    of wall courses, cornices and springers that belong exactly there. Which
    one may stand in is not a guess: the candidate's edge facing INTO the room
    has to agree with the plain piece it replaces, so the substitution cannot
    open a seam. That is what the adjacency work is actually for.
    """
    if not pool or (r * 7 + c * 13) % DRESS_EVERY:
        return None
    inward = {"N": "S", "S": "N", "W": "E", "E": "W"}[side]
    want = edge_strips(kit[plain])[inward]
    body = [v for row in kit[plain] for v in row]
    # AMONG THE ONES THAT DO NOT OPEN A SEAM, TAKE THE MOST DIFFERENT. Picking
    # the lowest seam cost selects the block most similar to the one being
    # replaced, so 301 substitutions landed and the walls still looked
    # identical. Fit is the constraint; contrast is the objective.
    legal = [c for c in pool
             if seam_cost(edge_strips(kit[c])[inward], want) <= JOIN_MAX * 2]
    if not legal:
        return None

    def difference(c):
        other = [v for row in kit[c] for v in row]
        return sum(1 for a, b in zip(body, other) if a != b)

    legal.sort(key=lambda c: (-difference(c), c))
    return legal[(r * 3 + c) % min(4, len(legal))]


# --- flips: vocabulary, not compression -------------------------------------
# THE FLIP BITS WERE WRITTEN AND NEVER EMITTED. `entry` has taken hflip/vflip
# since the first commit and the only reference to them in this file was that
# definition. What they buy here is NOT compression — measured, the sheets
# contain no near-mirror pairs at all, because the artist drew each piece once
# — it is COVERAGE. The sheet does not have to contain a right-hand bracket
# for the world to have one, and an arch is one half plus its mirror rather
# than two authored halves that may not agree.
#
# Under tiles16 a flip mirrors the WHOLE 16x16 block: hMirror swaps which half
# the PPU draws as well as flipping each tile (SnesPpu.cpp:238-244), and
# vMirror swaps the +16 row select the same way. So a mirrored block needs no
# CHR of its own — only the bit.
def flip_cells(cells, w, h, hflip=False, vflip=False):
    """Mirror a fixture's cell layout. The BLOCKS are unchanged — only where
    they sit, and the bits the tilemap will carry."""
    out = []
    for dr, dc, b in cells:
        r = (h - 1 - dr) if vflip else dr
        c = (w - 1 - dc) if hflip else dc
        out.append((r, c, b))
    return sorted(out)


class Placement:
    """One block on the map: which block, and how it is mirrored."""
    __slots__ = ("block", "hflip", "vflip")

    def __init__(self, block, hflip=False, vflip=False):
        self.block, self.hflip, self.vflip = block, hflip, vflip

    def word(self, base, pal):
        return entry(base[self.block], pal, self.hflip, self.vflip)


def mirrored(fx, hflip=False, vflip=False):
    """A fixture placed mirrored — an arch from one half, a right bracket from
    a left one. Costs a bit, not a block."""
    w, h, cells = fx.footprint()
    return w, h, [(r, c, Placement(b, hflip, vflip))
                  for r, c, b in flip_cells(cells, w, h, hflip, vflip)]


# --- per-room CHR residency --------------------------------------------------
# THE LIBRARY NO LONGER FITS, AND THAT IS THE POINT. All 436 assets come to 557
# blocks = 2,240 slots = 71,680 B, past both the 1024-slot tilemap index and
# the console's whole 65,536 B of VRAM. So the library lives in ROM and a page
# is uploaded per ROOM, which a screen-sized room makes natural: the room IS
# the streaming unit, the transition between rooms is when the upload happens,
# and a room's terrain measures 7-11 distinct blocks against a page that holds
# far more.
#
# This is what removes the budget from the design conversation. The question
# stops being "does the world fit in 128 blocks" and becomes "does any single
# ROOM fit in a page", which is a much easier thing to satisfy and a much
# easier thing to check.
PAGE_BLOCKS = 128               # 512 slots, 16,384 B — half the index space,
                                # leaving the other half for the second page a
                                # transition needs while both rooms are visible


def room_blocks(cells):
    """The distinct blocks one room needs resident, in first-use order.

    Order matters: the room's local block ids are indices into ITS page, so
    the tilemap is written against the page rather than against the library.
    """
    order, seen = [], set()
    for b in cells:
        if b not in seen:
            seen.add(b)
            order.append(b)
    return order


def check_pages(rooms):
    """No room may need more blocks than a page holds.

    The gate that replaces the global budget. A room that overflows is a room
    that has to be simplified or split — a build-time answer, not a runtime
    surprise.
    """
    over = [(name, len(bs)) for name, bs in rooms if len(bs) > PAGE_BLOCKS]
    assert not over, (
        f"{len(over)} room(s) need more than a {PAGE_BLOCKS}-block page: "
        f"{over[:4]}")
    return {"rooms": len(rooms),
            "max": max(len(bs) for _, bs in rooms) if rooms else 0,
            "median": sorted(len(bs) for _, bs in rooms)[len(rooms) // 2]
            if rooms else 0}
