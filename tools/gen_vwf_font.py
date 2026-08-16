#!/usr/bin/env python3
"""gen_vwf_font.py — superforge: GNU-Unifont .hex -> VWF glyph masks + advance table.

The VWF compositor's ONLY two inputs, and the reason the face is swappable: the
renderer reads these artifacts through `ES_R_VWF_GLYPHS_*` / `ES_R_VWF_WIDTHS_*`
and contains no glyph data, no width constant and no per-character special case.
Pointing this script at a different face and rebuilding is the whole swap.

Two artifacts, 96 glyphs ($20-$7F), deterministic (byte-identical output from the
same input):

  <out>/vwf_glyphs.bin   96 x 8 B — one 1bpp row mask per glyph, LEFT-ALIGNED
  <out>/vwf_widths.bin   96 x 1 B — advance in pixels (ink + letterspacing)

Why 1bpp and not the 2bpp shape font_rom ships:
  - compositing shifts a glyph to a sub-tile pen position, and shifting one
    plane is half the work of shifting two. The commit expands to 2bpp with
    BP0 == BP1, matching gen_font.py's convention, so VWF text lands on colour 3
    of bg_text's existing text_pal — no new CGRAM claim.

Why LEFT-ALIGNED (the "bearing-stripping pass"), and why it is not optional:
  a VWF pen position must mean "the next glyph's ink starts here". unscii-8's
  left bearings are measured at 0 (20 glyphs), 1 (60), 2 (9) and 3 (5) — see
  tools/vwf_font_metrics.py — so compositing straight from the source face would
  put a variable, face-dependent gap in front of every glyph. Stripping at BUILD
  time rather than at runtime keeps the shift off the hot path and is what makes
  the swap free: any real proportional face needs the same pass.

Blank glyphs (space) carry no ink, so their extent is undefined; they get a
fixed SPACE_INK-pixel advance and an all-zero mask.

Usage: gen_vwf_font.py vendor/fonts/unscii-8.hex build/assets [--letterspacing 1]
"""
import argparse
import sys
from pathlib import Path

LO, HI = 0x20, 0x7F                 # the same 96 glyphs font_rom ships
GLYPH_ROWS = 8
SPACE_INK = 2                       # blank glyph: ink treated as 2 px


def parse_hex(path: Path) -> dict[int, list[int]]:
    """GNU-Unifont .hex: `CODE:RRRRRR...`, 8 rows of one byte, MSB = column 0."""
    glyphs: dict[int, list[int]] = {}
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        code, _, data = ln.partition(":")
        cp = int(code, 16)
        rows = [int(data[i:i + 2], 16) for i in range(0, len(data), 2)]
        if len(rows) != GLYPH_ROWS:
            raise SystemExit(f"glyph ${cp:04X}: {len(rows)} rows, want {GLYPH_ROWS}")
        glyphs[cp] = rows
    return glyphs


def ink_extent(rows: list[int]) -> tuple[int, int] | None:
    """(leftmost, rightmost) inked column, MSB = column 0. None if blank."""
    mask = 0
    for r in rows:
        mask |= r
    if mask == 0:
        return None
    cols = [c for c in range(8) if mask & (0x80 >> c)]
    return cols[0], cols[-1]


def strip_and_measure(rows: list[int], letterspacing: int) -> tuple[list[int], int]:
    """Left-align the glyph and return (masks, advance).

    The shift is by the LEFT BEARING, so column 0 of the emitted mask is the
    first inked column — which is what makes a pen position mean what it says.
    """
    extent = ink_extent(rows)
    if extent is None:
        return [0] * GLYPH_ROWS, SPACE_INK + letterspacing
    left, right = extent
    ink = right - left + 1
    return [(r << left) & 0xFF for r in rows], ink + letterspacing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("hexfile")
    ap.add_argument("outdir")
    ap.add_argument("--letterspacing", type=int, default=1,
                    help="pixels added to each glyph's ink extent (default 1)")
    args = ap.parse_args()
    if not 0 <= args.letterspacing <= 4:
        raise SystemExit(f"--letterspacing {args.letterspacing}: want 0..4")

    glyphs = parse_hex(Path(args.hexfile))
    masks = bytearray()
    widths = bytearray()
    for cp in range(LO, HI + 1):
        m, adv = strip_and_measure(glyphs.get(cp, [0] * GLYPH_ROWS),
                                  args.letterspacing)
        masks += bytes(m)
        widths.append(adv)
        if not 1 <= adv <= 9:
            raise SystemExit(f"glyph ${cp:04X}: advance {adv} outside 1..9 — a "
                             f"pen advance wider than a tile breaks the "
                             f"two-tiles-per-glyph dirty-span bound")

    n = HI - LO + 1
    assert len(masks) == n * GLYPH_ROWS and len(widths) == n
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "vwf_glyphs.bin").write_bytes(bytes(masks))
    (out / "vwf_widths.bin").write_bytes(bytes(widths))
    print(f"vwf font: {len(masks)} B masks + {len(widths)} B widths -> {out} "
          f"(letterspacing {args.letterspacing} px, advances "
          f"{min(widths)}..{max(widths)} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
