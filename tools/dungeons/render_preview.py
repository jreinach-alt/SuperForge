"""render_preview.py — draw generated floors as PNG, for humans.

Not an oracle and not a test input: a picture of what the reference model
produces, so a designer can judge layouts without a ROM. 4 px per metatile.

    python3 tools/dungeons/render_preview.py OUT.png [seed ...]
"""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
import levelgen as L  # noqa: E402

PX = 4
COL = {
    0x00: (12, 10, 18), 0x01: (92, 84, 96), 0x02: (110, 98, 90),
    0x03: (230, 150, 60), 0x04: (160, 120, 70), 0x05: (240, 220, 120),
    0x10: (40, 36, 52), 0x11: (60, 56, 76), 0x20: (20, 30, 60),
}
SPAWN = {1: (80, 200, 255), 2: (230, 60, 60), 3: (250, 210, 40), 4: (200, 60, 230)}


def draw(lv) -> Image.Image:
    w, h = lv.width, lv.gh * L.CELL
    im = Image.new("RGB", (w * PX, h * PX))
    d = ImageDraw.Draw(im)
    for y in range(h):
        for x in range(w):
            d.rectangle([x * PX, y * PX, x * PX + PX - 1, y * PX + PX - 1], fill=COL[lv.at(x, y)])
    for t, x, y in lv.spawns:
        d.ellipse([x * PX - 2, y * PX - 2, x * PX + PX + 1, y * PX + PX + 1], fill=SPAWN[t])
    # the critical path, cell centre to cell centre
    pts = [((cx * L.CELL + 8) * PX, (cy * L.CELL + 8) * PX) for cx, cy in lv.path]
    d.line(pts, fill=(80, 200, 255), width=1)
    return im


def main(argv):
    out = argv[1]
    seeds = [int(a, 0) for a in argv[2:]] or [0x1234, 0xBEEF, 0x0007, 0x5A5A]
    floors = (0, 4, 8)
    tiles = [[draw(L.generate(s, f)) for f in floors] for s in seeds]
    tw, th = tiles[0][0].size
    pad = 6
    sheet = Image.new("RGB", (len(floors) * (tw + pad) + pad, len(seeds) * (th + pad) + pad), (0, 0, 0))
    for r, row in enumerate(tiles):
        for c, im in enumerate(row):
            sheet.paste(im, (pad + c * (tw + pad), pad + r * (th + pad)))
    sheet.save(out)
    print(out, sheet.size)


if __name__ == "__main__":
    main(sys.argv)
