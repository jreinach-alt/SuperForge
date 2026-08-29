#!/usr/bin/env python3
"""Convert a chroma-keyed concept sheet into SNES-shaped indexed art.

WHAT THIS IS AND IS NOT. The sheets are not pixel art — measured on the three
supplied 2026-08-29: 109k-159k unique colours, 0.00% of aligned 8x8 blocks
constant, and no integer upscale factor (edge energy sits at chance for every
N in 2..12, so there is no smaller grid underneath). They cannot be SLICED.
What they can be is RESAMPLED, because each asset is isolated on a chroma key
— and that is the whole difference from the earlier sheets, which composited
everything into one picture at an unknown scale.

So this is a conversion, not an extraction, and it has four steps that each
matter:

  1. KEY FIRST, RESAMPLE SECOND. The key is not one colour — it varies by a
     few counts per channel and carries the same grain as the art — so it is
     matched by predicate, not by equality, and turned into ALPHA before any
     resampling. Resampling first mixes magenta into every edge pixel and
     leaves a pink fringe that no later quantise can remove.
  2. PREMULTIPLIED downsample, then a coverage threshold. A box filter over
     un-premultiplied RGBA drags the key's colour into partly-covered pixels
     even when their alpha is right.
  3. MAP TO THE RAIL'S OWN PALETTE, not to a per-asset median cut. Every asset
     quantised independently would need its own 32 colours and the layer has
     96 for everything. The rail's ramps are the palette; this finds the
     nearest entry to each pixel in them.
  4. REPORT WHAT THE REDUCTION COST — the colour count actually used and, for
     art bound for a vertically displaced column, how many rows differ from
     the modal row. A shaft strip with a foot on it is not usable however
     good it looks, and that is a number rather than an opinion.
"""
import argparse
import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
_argv, sys.argv = sys.argv, sys.argv[:1]
import gen_mill_assets as G                                       # noqa: E402
sys.argv = _argv


def is_key(r, g, b):
    """The magenta the sheets are keyed on, matched loosely because it is not
    one colour: the grain moves it by a few counts per channel."""
    return g < 110 and r > 150 and b > 150


def key_to_alpha(im):
    im = im.convert("RGB")
    a = Image.new("L", im.size, 255)
    px, ap = im.load(), a.load()
    for y in range(im.size[1]):
        for x in range(im.size[0]):
            if is_key(*px[x, y]):
                ap[x, y] = 0
    im.putalpha(a)
    return im


def resample(im, size, coverage=0.45):
    """Premultiply, box-filter, un-premultiply, threshold the coverage."""
    px = im.load()
    pre = Image.new("RGBA", im.size)
    pp = pre.load()
    for y in range(im.size[1]):
        for x in range(im.size[0]):
            r, g, b, a = px[x, y]
            f = a / 255
            pp[x, y] = (int(r * f), int(g * f), int(b * f), a)
    small = pre.resize(size, Image.BOX)
    out = Image.new("RGBA", size)
    sp, op = small.load(), out.load()
    for y in range(size[1]):
        for x in range(size[0]):
            r, g, b, a = sp[x, y]
            if a / 255 < coverage:
                op[x, y] = (0, 0, 0, 0)
            else:
                f = 255 / a
                op[x, y] = (min(255, int(r * f)), min(255, int(g * f)),
                            min(255, int(b * f)), 255)
    return out


def expand(w):
    """BGR555 -> RGB888 as Mesen does it: (v<<3)|(v>>2)."""
    return tuple((v << 3) | (v >> 2)
                 for v in (w & 31, (w >> 5) & 31, (w >> 10) & 31))


def map_to_palette(im, palette, ix0):
    """Nearest entry, weighted the way the eye is. Returns an index buffer
    where 0 is transparent and every other value is a real CGRAM index."""
    rgb = [expand(w) for w in palette]
    px = im.load()
    buf = [[0] * im.size[0] for _ in range(im.size[1])]
    cache = {}
    for y in range(im.size[1]):
        for x in range(im.size[0]):
            r, g, b, a = px[x, y]
            if not a:
                continue
            k = (r, g, b)
            if k not in cache:
                cache[k] = ix0 + min(
                    range(len(rgb)),
                    key=lambda i: (2 * (rgb[i][0] - r) ** 2
                                   + 4 * (rgb[i][1] - g) ** 2
                                   + (rgb[i][2] - b) ** 2))
            buf[y][x] = cache[k]
    return buf


def row_variance(buf):
    """For art bound for a V-displaced column: how many rows differ from the
    most common one? Anything but 0 means the column would visibly slide."""
    from collections import Counter
    rows = [tuple(r) for r in buf]
    return len(rows) - Counter(rows).most_common(1)[0][1]


def render(buf, palette, ix0, scale=4):
    rgb = [expand(w) for w in palette]
    h, w = len(buf), len(buf[0])
    im = Image.new("RGB", (w, h), (24, 24, 28))
    p = im.load()
    for y in range(h):
        for x in range(w):
            if buf[y][x]:
                p[x, y] = rgb[buf[y][x] - ix0]
    return im.resize((w * scale, h * scale), Image.NEAREST)


def convert(sheet, box, size, palette=None, ix0=None):
    palette = G.PAL_BG1 if palette is None else palette
    ix0 = G.BG1_IX0 if ix0 is None else ix0
    src = key_to_alpha(Image.open(sheet).crop(box))
    return map_to_palette(resample(src, size), palette, ix0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet")
    ap.add_argument("box", help="x0,y0,x1,y1")
    ap.add_argument("size", help="WxH")
    ap.add_argument("--out", default="build/kit/asset.png")
    a = ap.parse_args()
    box = tuple(int(v) for v in a.box.split(","))
    size = tuple(int(v) for v in a.size.split("x"))
    buf = convert(a.sheet, box, size)
    used = len({v for r in buf for v in r if v})
    print(f"  {size[0]}x{size[1]}  {used} palette entries used, "
          f"{row_variance(buf)} of {size[1]} rows differ from the modal row")
    pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    render(buf, G.PAL_BG1, G.BG1_IX0).save(a.out)
    print(f"  {a.out}")


if __name__ == "__main__":
    main()
