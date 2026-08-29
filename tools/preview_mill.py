#!/usr/bin/env python3
"""mill — render the AUTHORED picture, before the hardware sees it.

A preview, and it is honest about being one: it composites BG1 over BG2 with
the rail's own palettes and its own tilemaps, at rest, so an art edit can be
looked at in a second instead of a build-and-boot. It is NOT evidence — the
picture the ROM draws is the one that counts (CLAUDE.md rule 3), and
tests/test_mill.py reads that. What this catches is the class the emulator is
too slow a loop for: composition, contrast and whether a thing is legible.

    python3 tools/preview_mill.py [out.png]
"""
import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# THE GENERATOR READS sys.argv[1] AT IMPORT TIME and mkdir()s it — it is a
# script first and a module second. Hiding this tool's own argv across the
# import is the whole fix; the alternative is importing it and silently
# creating a DIRECTORY named after the PNG this tool is about to write.
_argv, sys.argv = sys.argv, sys.argv[:1]
import gen_mill_assets as G                                       # noqa: E402
sys.argv = _argv


def expand(w):
    """BGR555 -> RGB888 the way Mesen does it: (v<<3)|(v>>2), not v*255//31.
    The two agree at 0 and 31 and differ by one in between, and this repo has
    already paid for the difference once."""
    r, g, b = w & 31, (w >> 5) & 31, (w >> 10) & 31
    return tuple((v << 3) | (v >> 2) for v in (r, g, b))


def main():
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "build/mill_preview.png")
    cg1 = [expand(w) for w in G.PAL_BG1]
    cg2 = [expand(w) for w in G.PAL_BG2]
    buf = G.paint_bg1()
    G.assert_shaft_invariance(buf)
    im = Image.new("RGB", (G.PX, 224))
    px = im.load()
    # BG2 first: one tile per map row, tread across the belt band.
    wall = [G.wall_row(r) for r in range(G.ROWS)]
    gant = (G.gantry_row(0), G.gantry_row(1))
    tread = [G.tread_tile(k) for k in range(G.BELT_PHASES)]
    for y in range(224):
        r, ty = y // 8, y % 8
        for x in range(G.PX):
            c, tx = x // 8, x % 8
            if r in (G.GANTRY_ROW, G.GANTRY_ROW + 1):
                v, base = gant[r - G.GANTRY_ROW][ty][tx], 0
            elif G.BELT_ROW <= r < G.BELT_ROW + 2:
                v, base = tread[c % G.BELT_PHASES][ty][tx], 4
            else:
                v, base = wall[r][ty][tx], 0
            px[x, y] = cg2[base + v] if v else cg2[0]
    for y in range(224):                       # ...then BG1 over it
        for x in range(G.PX):
            v = buf[y][x]
            if v:
                px[x, y] = cg1[v - G.BG1_IX0]
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    print(f"  {out}  {G.PX}x224")


if __name__ == "__main__":
    main()
