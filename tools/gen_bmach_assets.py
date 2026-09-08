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
SHEETS = (
    ("sandstone_ruins.png",     PAL_SAND,  22),
    ("machine_structure.png",   PAL_STEEL, 20),
    ("platforms.png",           PAL_STEEL, 16),
    ("pipes.png",               PAL_STEEL, 12),
    ("hazards_transitions.png", PAL_HOT,   14),
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
        step = max(1, len(cs) // take)
        for c in cs[::step][:take]:
            bw, bh, grid = block_run(im, c, zone)
            ids = []
            for blk in grid:
                key = blk
                if key not in blocks:
                    blocks[key] = len(kit)
                    kit.append(blk)
                ids.append(blocks[key])
            runs.append((fname, zone, bw, bh, ids))
            if len(kit) >= budget:
                break
        if len(kit) >= budget:
            break
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


def world(kit, runs, base):
    """The map, the collision grid, and the piston banks.

    BUILT BY CARVING, not by decorating. The first attempt placed ledges on an
    empty field and rendered as a slab with rectangles in it: a buried place is
    MASS with voids cut through it, so this fills every row below the surface
    solid and then cuts the route out of it. The route descends but has to
    cross the map to keep descending, which is what makes the world's width
    matter as much as its depth.
    """
    by = kit_by_sheet(runs)
    sand, steel = by["sandstone_ruins.png"], by["machine_structure.png"]
    deck, pipe = by["platforms.png"], by["pipes.png"]
    hot = by["hazards_transitions.png"]

    def pool_for(r):
        return sand if r < MACHINE_TOP else (steel if r < FURNACE_TOP else hot)

    def pick(pool, salt):
        return pool[salt % len(pool)]

    grid = [[AIR] * COLS for _ in range(ROWS)]
    mp = [[None] * COLS for _ in range(ROWS)]

    FILL = {id(sand): flattest(kit, sand), id(steel): flattest(kit, steel),
            id(hot): flattest(kit, hot), id(deck): flattest(kit, deck),
            id(pipe): flattest(kit, pipe)}

    def fill(r, c, cls, pool=None, salt=0, flat=False):
        if not (0 <= r < ROWS and 0 <= c < COLS):
            return
        pool = pool if pool is not None else pool_for(r)
        blk = FILL[id(pool)] if flat else pick(pool, salt)
        mp[r][c] = entry(base[blk], zone_of_row(r))
        grid[r][c] = cls

    def carve(r, c):
        if 0 <= r < ROWS and 0 <= c < COLS:
            mp[r][c] = None
            grid[r][c] = AIR

    # --- 1. solid to the horizon -------------------------------------------
    for r in range(RUIN_TOP, ROWS):
        for c in range(COLS):
            fill(r, c, SOLID, flat=True)

    # --- 2. the route: chambers, alternating side to side -------------------
    # Six chambers down the map. Each is a wide void; consecutive chambers sit
    # on opposite sides, and a shaft joins them, so getting down means crossing.
    chambers = []
    r = RUIN_TOP + 3
    left = True
    while r < FURNACE_TOP - 4 and len(chambers) < 6:
        w = 22 + (len(chambers) % 3) * 6
        h = 5 + (len(chambers) % 2) * 2
        c0 = 3 if left else COLS - 3 - w
        for rr in range(r, r + h):
            for cc in range(c0, c0 + w):
                carve(rr, cc)
        # its floor is walkable
        for cc in range(c0, c0 + w):
            fill(r + h, cc, PLATFORM, pool=deck if r >= MACHINE_TOP else sand,
                 salt=r + cc)
        chambers.append((r, c0, w, h))
        # the shaft down to the next chamber, at the far end from the entrance
        sx = c0 + w - 4 if left else c0 + 2
        for rr in range(r + h, r + h + 4):
            for cc in range(sx, sx + 3):
                carve(rr, cc)
        left = not left
        r += h + 4

    # --- 3. the piston banks, standing in the machine chambers -------------
    # Four banks of four 16-pixel columns. These are the columns the offset
    # table displaces, and they stand INSIDE a void so their travel is visible.
    banks = []
    machine = [ch for ch in chambers if ch[0] >= MACHINE_TOP - 4]
    for i, ch in enumerate(machine[:4]):
        cr, c0, w, h = ch
        bx = c0 + 4 + i * 2
        banks.append({"col0": bx, "width": 4, "phase": i * 32,
                      "travel": 24 + i * 8, "row0": cr, "rows": h})
        for cc in range(bx, bx + 4):
            for rr in range(cr, cr + h):
                fill(rr, cc, SOLID, pool=steel, salt=rr + cc)

    # --- 4. the furnace floor ----------------------------------------------
    for c in range(COLS):
        fill(FURNACE_TOP, c, HAZARD, pool=hot, salt=c * 5)

    # --- 5. pipework on the chamber ceilings, for the eye -------------------
    for cr, c0, w, h in chambers:
        if cr < MACHINE_TOP:
            continue
        for cc in range(c0 + 1, c0 + w - 1, 5):
            fill(cr, cc, AIR, pool=pipe, salt=cr + cc)

    blank = entry(base[0], PAL_SAND)   # kit block 0 is the empty one
    words = bytearray()
    for rr in range(ROWS):
        for c in range(COLS):
            w = mp[rr][c] if mp[rr][c] is not None else blank
            words += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(words), grid, banks
