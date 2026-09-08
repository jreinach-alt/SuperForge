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
    blocks, index, kit = {}, [], []
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
