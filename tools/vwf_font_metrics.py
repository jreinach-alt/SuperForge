#!/usr/bin/env python3
"""vwf_font_metrics.py — report a bitmap face's VWF advance metrics.

Analysis instrument for the VWF work.
It answers, for any GNU-Unifont `.hex` face, the two questions a VWF renderer's
declaration depends on:

  1. What is the advance distribution — i.e. how wide is the widest glyph, which
     bounds the worst-case dirty tile span per revealed glyph?
  2. Do bearings vary — i.e. is a build-time left-alignment (bearing-stripping)
     pass required, or are the glyphs already flush left?

Ink extents are derived the way the renderer will derive them: OR the 8 rows of
a glyph, take the leftmost and rightmost set column; advance = ink +
letterspacing. Blank glyphs (space) get a fixed advance.

This measures the SOURCE FONT, not the renderer. It pins nothing and is not part
of `make measure`. Run from the repo root:

    python3 tools/vwf_font_metrics.py vendor/fonts/unscii-8.hex
    python3 tools/vwf_font_metrics.py vendor/fonts/unscii-8.hex --letterspacing 0
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

LO, HI = 0x20, 0x7F                 # the 96 glyphs font_rom ships
SPACE_ADVANCE_INK = 2               # blank glyph: ink treated as 2 px


def parse_hex(path: Path) -> dict[int, list[int]]:
    glyphs: dict[int, list[int]] = {}
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        code, _, data = ln.partition(":")
        rows = [int(data[i:i + 2], 16) for i in range(0, len(data), 2)]
        if len(rows) != 8:
            raise SystemExit(f"glyph ${int(code, 16):04X}: {len(rows)} rows, want 8")
        glyphs[int(code, 16)] = rows
    return glyphs


def ink_extent(rows: list[int]) -> tuple[int, int] | None:
    """(leftmost, rightmost) set column, MSB = column 0. None if blank."""
    mask = 0
    for r in rows:
        mask |= r
    if mask == 0:
        return None
    cols = [c for c in range(8) if mask & (0x80 >> c)]
    return cols[0], cols[-1]


def metrics(glyphs: dict[int, list[int]], letterspacing: int) -> dict[int, dict]:
    out = {}
    for cp in range(LO, HI + 1):
        rows = glyphs.get(cp, [0] * 8)
        e = ink_extent(rows)
        if e is None:
            out[cp] = {"bearing": None, "ink": SPACE_ADVANCE_INK,
                       "advance": SPACE_ADVANCE_INK + letterspacing}
            continue
        left, right = e
        ink = right - left + 1
        out[cp] = {"bearing": left, "ink": ink, "advance": ink + letterspacing}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("hexfile")
    ap.add_argument("--letterspacing", type=int, default=1)
    ap.add_argument("--strings", nargs="*", default=[
        "iiii", "mmmm", "XXXX", "....", "i.i.i", "il1|!", "mnwv", "VHNMW",
        "MICROZERO", "The quick brown fox", "End. Next: go",
    ])
    args = ap.parse_args()

    m = metrics(parse_hex(Path(args.hexfile)), args.letterspacing)
    adv = Counter(v["advance"] for v in m.values())
    bearing = Counter(v["bearing"] for v in m.values() if v["bearing"] is not None)

    print(f"face: {args.hexfile}   letterspacing: {args.letterspacing} px")
    print(f"advance histogram: {dict(sorted(adv.items()))}")
    print(f"bearing histogram: {dict(sorted(bearing.items()))}")
    if len(bearing) > 1:
        print("  -> bearings VARY: a build-time left-alignment pass is REQUIRED "
              "(a renderer compositing straight from this face would put a "
              "variable gap in front of every glyph)")
    else:
        print("  -> bearings uniform: glyphs are already flush left")

    by_adv = sorted((v["advance"], chr(k)) for k, v in m.items())
    print(f"narrowest: {by_adv[:7]}")
    print(f"widest:    {by_adv[-7:]}")
    print(f"\nworst-case tiles dirtied by ONE revealed glyph: "
          f"floor((7 + {max(v['ink'] for v in m.values())} - 1) / 8) + 1 = "
          f"{(7 + max(v['ink'] for v in m.values()) - 1) // 8 + 1}")

    print("\nrendered extents (advance px -> 2bpp tiles at 8 px/tile):")
    for s in args.strings:
        total = sum(m[ord(c)]["advance"] for c in s)
        per = " ".join(f"{c}:{m[ord(c)]['advance']}" for c in s)
        print(f"  {s!r:24} {total:4d} px  {-(-total // 8):3d} tiles   [{per}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
