#!/usr/bin/env python3
"""gen_shmup_assets.py — the `shmup` rail's art, from the ORIGINAL pack PNGs.

Emits into `build/assets` (byte-identical on re-run — every step below is
integer math over vendored bytes, and nothing consults a dict iteration order,
a float, a clock or a PRNG):

  shm_bg_chr.bin     66 x 4bpp BG tiles = 2112 B
                     tile 0 blank (the night sky reads through it)
                     tiles 1..64  four planets, 4x4 tiles each, p*16 + r*4 + c
                     tile 65      the solid HUD bar (BG2 shares this page)
  shm_bg_pal.bin     16 BGR555 words = 32 B   BG palette 2 (CGRAM 32..47)
  shm_obj_chr.bin    48 x 4bpp OBJ tiles = 1536 B, on the 16-WIDE VRAM GRID a
                     16x16 sprite requires (see the layout note below)
  shm_ship_pal.bin   16 words = 32 B   OBJ palette 0 (CGRAM 128..143)
  shm_foe_pal.bin    16 words = 32 B   OBJ palette 1 (CGRAM 144..159)
  shm_burst_pal.bin  16 words = 32 B   OBJ palette 2 (CGRAM 160..175)

SOURCE = THE PACK'S OWN PNGs, NOT DERIVED .inc BLOBS. That is the
whole reason this generator looks the way it does. CLAUDE.md's asset-import
rule says a converter that byte-traces a *derived* asset must be ground-truthed
against a render it did not produce, because checking it against your own
re-rendering of your own output is a tautology — and that tautology has shipped
visibly broken art on this project. Reading `vendor/art/spaceship_pack/*.png`
removes the trap at its root: the PNG is independent of everything this repo
produces, so `tests/test_shmup.py` can compare the RENDERED SNES FRAME back to
it and the comparison means something.

THE 16-WIDE OBJ GRID IS HARDWARE, NOT A CHOICE. The PPU reads a 16x16 sprite
as four 8x8 tiles at {N, N+1, N+16, N+17} — the second row is always +16 tile
numbers, never +2. So the OBJ CHR blob is laid out as a 16-tile-wide grid:

  row 0 (tiles  0..15)  ship f0 | ship f1 | foe f0 | foe f1 | burst f0..f3
  row 1 (tiles 16..31)  ...the bottom half of each of those, at +16
  row 2 (tiles 32..47)  tile 32 = the bullet (8x8, small); 33..47 blank

NO SILENT MASKING (CLAUDE.md's asset-encoder rule): `encode_4bpp` asserts every
pixel index is 0..15, and `quantize` asserts it produced <= 15 live colours.
An out-of-range value stops the generator naming the offending pixel; it never
quietly becomes a different colour.
"""
import sys
from pathlib import Path

from PIL import Image

ART = Path(__file__).resolve().parent.parent / "vendor/art/spaceship_pack"

# --- the rail's geometry, restated once -------------------------------------
OBJ_GRID_W = 16          # tiles per VRAM row — the +16 rule above
OBJ_TILES = 48           # 3 grid rows
BG_TILES = 66            # 1 blank + 4 planets x 16 + 1 HUD bar
PLANET_SIDE = 4          # tiles per planet side (4x4 = 32x32 px)
PLANETS = ("planet_1.png", "planet_2.png", "planet_4.png", "planet_6.png")
BAR_TILE = 65            # the solid HUD-bar tile, last in the BG page

# The HUD bar's colour, in the BG palette's own space. Written as a 5-bit BGR
# triple rather than a packed word so it reads as a colour and not an address.
BAR_RGB5 = (0, 1, 3)     # near-black navy: darker than the sky, so the band reads


# =============================================================================
# image primitives — all integer, all deterministic
# =============================================================================

def load(name):
    """A vendored PNG as (w, h, [(r,g,b,a)]) with colour reduced to 5 bits.

    Reducing to the SNES's own 5-bit channel depth BEFORE quantizing, rather
    than after, is what keeps the palette exact: quantize in 8-bit space and
    two representatives can collapse onto one BGR555 word afterwards, silently
    costing a colour.
    """
    im = Image.open(ART / name).convert("RGBA")
    w, h = im.size
    px = im.load()
    out = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            out.append((r >> 3, g >> 3, b >> 3, a))
    return w, h, out


def crop(src, x0, y0, w, h):
    sw, _sh, pix = src
    return (w, h, [pix[(y0 + y) * sw + (x0 + x)] for y in range(h)
                   for x in range(w)])


def rot180(src):
    w, h, pix = src
    return (w, h, list(reversed(pix)))


def downscale(src, dw, dh):
    """Exact area-weighted box reduction, in integers.

    Coverage is computed in units of 1/dw (1/dh) so every weight is an integer
    and the result does not depend on floating point. A destination pixel is
    OPAQUE iff opaque source area is the majority of its footprint; its colour
    is the area-weighted mean of the opaque contributors only, so a ship's
    outline does not bleed toward transparent black.
    """
    sw, sh, pix = src
    spans_x = _spans(sw, dw)
    spans_y = _spans(sh, dh)
    out = []
    for dy in range(dh):
        for dx in range(dw):
            acc = [0, 0, 0]
            wop = wall = 0
            for sy, wy in spans_y[dy]:
                for sx, wx in spans_x[dx]:
                    r, g, b, a = pix[sy * sw + sx]
                    w = wy * wx
                    wall += w
                    if a >= 128:
                        wop += w
                        acc[0] += r * w
                        acc[1] += g * w
                        acc[2] += b * w
            if wop * 2 <= wall:
                out.append((0, 0, 0, 0))
            else:
                out.append(tuple((c + wop // 2) // wop for c in acc) + (255,))
    return (dw, dh, out)


def _spans(src_n, dst_n):
    """For each destination index, the (source index, integer weight) pairs."""
    rows = []
    for d in range(dst_n):
        lo, hi = d * src_n, (d + 1) * src_n
        row = []
        for s in range(src_n):
            a, b = max(lo, s * dst_n), min(hi, (s + 1) * dst_n)
            if b > a:
                row.append((s, b - a))
        rows.append(row)
    return rows


def over(base, top):
    """`top` composited over `base` (both same size); alpha is 1-bit here."""
    w, h, bp = base
    _tw, _th, tp = top
    return (w, h, [t if t[3] >= 128 else b for b, t in zip(bp, tp)])


def paste(base, top, x0, y0):
    """`top` stamped into `base` at (x0, y0), CLIPPED at the edges.

    Clipping rather than asserting is deliberate: the plume is stamped at the
    ship's tail, and the tail is at the bottom edge of the pack's 48x48 box —
    the flame is *supposed* to run off it.
    """
    w, h, bp = base
    tw, th, tp = top
    out = list(bp)
    for y in range(th):
        if not 0 <= y0 + y < h:
            continue
        for x in range(tw):
            t = tp[y * tw + x]
            if t[3] >= 128 and 0 <= x0 + x < w:
                out[(y0 + y) * w + (x0 + x)] = t
    return (w, h, out)


def blank(w, h):
    return (w, h, [(0, 0, 0, 0)] * (w * h))


def saturate(src, num=3, den=2):
    """Push every opaque pixel `num/den` further from its own luma.

    A 3x area reduction AVERAGES a thin bright line with its dark neighbours,
    and a 48x48 filigree hull comes out of it as mud — measured, not assumed:
    `ship_5` reduced without this reads brown-grey where the pack draws it
    red-orange. So a small contrast/sharpen pass runs first and the silhouette
    survives the reduction. Integer luma with the usual 77/151/28 weights,
    clamped to the 5-bit range.
    """
    w, h, pix = src
    out = []
    for r, g, b, a in pix:
        if a < 128:
            out.append((0, 0, 0, 0))
            continue
        luma = (r * 77 + g * 151 + b * 28) >> 8
        out.append(tuple(max(0, min(31, luma + (c - luma) * num // den))
                         for c in (r, g, b)) + (255,))
    return (w, h, out)


# =============================================================================
# palette: deterministic median cut in 5-bit space
# =============================================================================

def quantize(images, n=15):
    """One shared palette of <= n colours for `images`, plus the mapped frames.

    Median cut, made deterministic at every choice point: boxes are split on
    the widest channel (ties -> lowest channel index), on the population median
    of a list sorted by (that channel, then the whole colour), and the next box
    to split is the one with the largest population (ties -> the one whose
    sorted colour list is smallest). Representatives are population-weighted
    integer means. Nothing here depends on set or dict ordering.
    """
    hist = {}
    for img in images:
        for r, g, b, a in img[2]:
            if a >= 128:
                hist[(r, g, b)] = hist.get((r, g, b), 0) + 1
    colours = sorted(hist)
    boxes = [colours]
    while len(boxes) < n and any(len(b) > 1 for b in boxes):
        i = min(range(len(boxes)),
                key=lambda k: (-sum(hist[c] for c in boxes[k]) if
                               len(boxes[k]) > 1 else 1, boxes[k]))
        box = boxes[i]
        ch = max(range(3), key=lambda c: (max(x[c] for x in box)
                                          - min(x[c] for x in box), -c))
        box = sorted(box, key=lambda c: (c[ch], c))
        half = _median_split(box, hist)
        boxes[i:i + 1] = [box[:half], box[half:]]
    pal = sorted(_mean(b, hist) for b in boxes)
    assert len(pal) <= n, f"quantize produced {len(pal)} colours, max {n}"
    return pal, [_map(img, pal) for img in images]


def _median_split(box, hist):
    """The index that puts half the POPULATION on each side (never 0 or len)."""
    total = sum(hist[c] for c in box)
    run = 0
    for i, c in enumerate(box):
        run += hist[c]
        if run * 2 >= total and i + 1 < len(box):
            return i + 1
    return len(box) - 1


def _mean(box, hist):
    tot = sum(hist[c] for c in box)
    return tuple((sum(c[k] * hist[c] for c in box) + tot // 2) // tot
                 for k in range(3))


def _map(img, pal):
    """Pixels -> palette INDICES, 0 = transparent, live colours from 1."""
    w, h, pix = img
    out = []
    for r, g, b, a in pix:
        if a < 128:
            out.append(0)
            continue
        best = min(range(len(pal)),
                   key=lambda i: (sum((pal[i][k] - (r, g, b)[k]) ** 2
                                      for k in range(3)), i))
        out.append(best + 1)
    return (w, h, out)


def pal_bytes(pal):
    """A 16-entry BGR555 palette: index 0 transparent, then the live colours.

    All 16 words are written even though the tail is unused — the whole claim
    is defined before anything reads it (CLAUDE.md rule 5), and an undefined
    tail invites a second feature to put a colour there.
    """
    words = [0] + [(b << 10) | (g << 5) | r for r, g, b in pal]
    words += [0] * (16 - len(words))
    assert len(words) == 16 and all(0 <= w < 0x8000 for w in words)
    return b"".join(bytes((w & 0xFF, w >> 8)) for w in words)


# =============================================================================
# SNES 4bpp encoding
# =============================================================================

def encode_4bpp(tile):
    """One 8x8 tile of palette indices -> 32 B, planes 0/1 then 2/3.

    NO SILENT MASKING: an index outside 0..15 stops the build naming its
    coordinates. The `& 0x0F` that would "fix" it here is the exact
    anti-pattern the asset-encoder rule forbids.
    """
    for i, v in enumerate(tile):
        assert 0 <= v <= 15, \
            f"pixel ({i % 8},{i // 8}) is palette index {v}, not 0..15"
    out = bytearray()
    for pair in (0, 2):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = tile[y * 8 + x] >> pair
                lo |= (v & 1) << (7 - x)
                hi |= ((v >> 1) & 1) << (7 - x)
            out += bytes((lo, hi))
    return bytes(out)


def tiles_of(img, tx, ty, gw, gh):
    """A gw x gh block of 8x8 tiles cut from `img` at tile (tx, ty), row-major."""
    w, _h, pix = img
    out = []
    for r in range(gh):
        for c in range(gw):
            x0, y0 = (tx + c) * 8, (ty + r) * 8
            out.append([pix[(y0 + y) * w + x0 + x]
                        for y in range(8) for x in range(8)])
    return out


def solid(index):
    return [index] * 64


def empty():
    return [0] * 64


# =============================================================================
# the actors
# =============================================================================

PLUME_DY = 22            # the pack's plume sits at y20; +22 lands it on the tail


def ship_frames(png, rotate):
    """A 48x48 pack ship -> two 16x16 frames, the engine plume alternating.

    The plume flicker IS the rail's animation, and it is the pack's OWN two
    plume frames alternating — no repainting, just the pair the artist drew.
    Composited BEFORE the downscale, so the 3x reduction blends the flame into
    the hull the way it blends everything else, and rotated AFTER, so a ship
    nosed down at the player keeps its flame at the engine rather than the nose.
    """
    hull = load(png)
    plume = load("turbo_blue.png")
    out = []
    for i in range(2):
        big = over(hull, paste(blank(48, 48),
                               crop(plume, i * 48, 0, 48, 48), 0, PLUME_DY))
        out.append(saturate(downscale(rot180(big) if rotate else big, 16, 16)))
    return out


def burst_frames():
    """Frames 0..3 of the 7-frame 48x48 blast sheet, at 16x16.

    Frames 4..6 go too dark to read at 16 px — at a quarter of the sheet's
    resolution the late frames are a few dim pixels, so the blast is better
    served by the four that still have shape.
    """
    sheet = load("explosion_sheet.png")
    return [downscale(crop(sheet, i * 48, 0, 48, 48), 16, 16) for i in range(4)]


def bullet_tile(index):
    """One 8x8 tile: a 4-px bright column with transparent corners."""
    t = empty()
    for y in range(6):
        for x in range(2, 6):
            t[y * 8 + x] = index
    return t


# =============================================================================
# emit
# =============================================================================

def build_bg():
    """The BG page: blank, four 4x4-tile planets, the HUD bar. One palette."""
    small = [downscale(load(p), PLANET_SIDE * 8, PLANET_SIDE * 8)
             for p in PLANETS]
    pal, mapped = quantize(small, n=14)     # 14 live + bar + transparent = 16
    bar = len(pal) + 1                      # the bar's index, after the art
    pal = list(pal) + [BAR_RGB5]
    tiles = [empty()]
    for m in mapped:
        tiles += tiles_of(m, 0, 0, PLANET_SIDE, PLANET_SIDE)
    tiles.append(solid(bar))
    assert len(tiles) == BG_TILES, f"BG page is {len(tiles)} tiles, want {BG_TILES}"
    return b"".join(encode_4bpp(t) for t in tiles), pal_bytes(pal)


def build_obj():
    """The OBJ page, on the 16-wide grid, + the three OBJ palettes."""
    ship_pal, ship = quantize(ship_frames("ship_2.png", False), n=15)
    foe_pal, foe = quantize(ship_frames("ship_5.png", True), n=14)
    burst_pal, burst = quantize(burst_frames(), n=15)
    foe_pal = list(foe_pal) + [(31, 31, 12)]        # the bullet's yellow rides
    bullet_ix = len(foe_pal)                        #   the enemy palette

    grid = [empty() for _ in range(OBJ_TILES)]
    for slot, img in enumerate(ship + foe + burst):
        tl, tr, bl, br = tiles_of(img, 0, 0, 2, 2)
        grid[slot * 2], grid[slot * 2 + 1] = tl, tr
        grid[OBJ_GRID_W + slot * 2], grid[OBJ_GRID_W + slot * 2 + 1] = bl, br
    grid[OBJ_GRID_W * 2] = bullet_tile(bullet_ix)
    return (b"".join(encode_4bpp(t) for t in grid),
            pal_bytes(ship_pal), pal_bytes(foe_pal), pal_bytes(burst_pal))


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    bg_chr, bg_pal = build_bg()
    obj_chr, ship_pal, foe_pal, burst_pal = build_obj()
    for name, data in (("shm_bg_chr.bin", bg_chr),
                       ("shm_bg_pal.bin", bg_pal),
                       ("shm_obj_chr.bin", obj_chr),
                       ("shm_ship_pal.bin", ship_pal),
                       ("shm_foe_pal.bin", foe_pal),
                       ("shm_burst_pal.bin", burst_pal)):
        (out / name).write_bytes(data)
        print(f"  {name}: {len(data)} B")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
