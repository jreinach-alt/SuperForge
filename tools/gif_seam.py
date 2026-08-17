#!/usr/bin/env python3
"""Measure the loop seam of a GIF — how hard the wrap from last frame to first.

A gallery clip loops forever, so the cut a viewer actually sees is the one
between the LAST frame and the FIRST. That join is the only edit in the file
and it is the one nobody records, so it is measured here rather than eyeballed:
"it looks smooth" is not a result.

The number is read back out of the WRITTEN GIF, decoded through the same
palette the file ships, because the artifact that loops is the file and not the
captures it came from. Two figures, on the RGB pixels of the decoded frames:

    mad     mean absolute difference per channel, 0..255 — the whole-picture
            distance across the join. A clip whose ends genuinely rejoin sits
            near zero; a sharp cut lands in the tens.
    pct>16  percentage of pixels whose largest channel difference clears 16 —
            the fraction of the screen that visibly changes at the wrap.
            Small-but-nonzero `mad` with a large `pct` is a picture that moved
            everywhere a little (a scroll); a large `mad` with a small `pct` is
            one region jumping (a sprite, a card).

BOTH ENDS OF A FADE, NOT JUST THE TAIL. A clip that ends on black only rejoins
invisibly if it BEGINS on black, so `--report` also prints each end's own mean
luma: `first` and `last` near zero is a black-to-black join, and a bright
`first` against a dark `last` is the asymmetry the seam number would otherwise
under-report as merely "large".

Usage:
    python3 tools/gif_seam.py docs/img/gif_boss_saucer.gif [more.gif ...]
    python3 tools/gif_seam.py --json docs/img/*.gif
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageSequence

THRESHOLD = 16          # per-channel difference a viewer reads as a change


def _ends(path):
    """First and last frames of the file, decoded to RGB."""
    im = Image.open(path)
    frames = [f.convert("RGB").copy() for f in ImageSequence.Iterator(im)]
    return frames[0], frames[-1], len(frames)


def _luma(img):
    px = img.load()
    w, h = img.size
    tot = 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            tot += (r * 299 + g * 587 + b * 114) // 1000
    return tot / ((h + 1) // 2 * ((w + 1) // 2))


def seam(path):
    """(mad, pct_over_threshold, first_luma, last_luma, n_stored_frames)."""
    first, last, n = _ends(path)
    if first.size != last.size:
        raise ValueError(f"{path}: frame sizes differ")
    pa, pb = first.load(), last.load()
    w, h = first.size
    total = w * h
    acc = 0
    over = 0
    for y in range(h):
        for x in range(w):
            ar, ag, ab = pa[x, y]
            br, bg, bb = pb[x, y]
            dr, dg, db = abs(ar - br), abs(ag - bg), abs(ab - bb)
            acc += dr + dg + db
            if max(dr, dg, db) > THRESHOLD:
                over += 1
    return (acc / (total * 3), 100.0 * over / total,
            _luma(first), _luma(last), n)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gifs", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows = []
    for g in a.gifs:
        p = Path(g)
        mad, pct, lum0, lum1, n = seam(p)
        rows.append(dict(gif=p.name, mad=round(mad, 2), pct_over=round(pct, 1),
                         first_luma=round(lum0, 1), last_luma=round(lum1, 1),
                         frames=n, bytes=p.stat().st_size))
    if a.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
        return
    print(f"{'gif':28s} {'mad':>7s} {'pct>16':>7s} "
          f"{'first':>7s} {'last':>7s} {'frames':>7s} {'bytes':>9s}")
    for r in rows:
        print(f"{r['gif']:28s} {r['mad']:7.2f} {r['pct_over']:6.1f}% "
              f"{r['first_luma']:7.1f} {r['last_luma']:7.1f} "
              f"{r['frames']:7d} {r['bytes']:9d}")


if __name__ == "__main__":
    main()
