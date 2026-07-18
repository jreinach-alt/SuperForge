#!/usr/bin/env python3
"""make_dash.py — first-party 2bpp INSTRUMENT-BAND tiles + palette for the
split_h_demo (the horizontal raster-band split template).

CLEAN-ROOM: ORIGINAL abstract instrument art authored from scratch (gauge
blocks + a fill-bar), reproducing NO commercial-game content. This is the
genuine BG3 tile layer that renders in the TOP raster band of the split, above
the Mode 7 floor — proving the split shows a real tile HUD, not a mode smear.

The band is a BG3 (2bpp) tile layer. This script emits the tile CHR + a 4-colour
BG3 palette. The tiles use palette indices 0..3 verbatim (identity 2bpp remap),
so index i maps to the i-th BG3 palette colour:
    0 = transparent (backdrop shows through — the dark band base)
    1 = frame / gauge outline (steel blue)
    2 = bar EMPTY cell (dim)
    3 = bar FILL cell + gauge lit block (bright amber)

Tiles (each 8x8, 16 bytes 2bpp), tile ids as loaded into BG3 CHR:
    0  BLANK        all-0 (transparent)
    1  FRAME_TOP    top border rule
    2  FRAME_BOT    bottom border rule
    3  BAR_EMPTY    an empty gauge cell (outline + dim interior)
    4  BAR_FILL     a filled gauge cell (outline + bright interior)
    5  GAUGE_LIT    a solid lit block (a fixed decorative instrument light)
    6  GAUGE_DIM    a solid dim block (a fixed decorative instrument light)

The ROM writes a run of BAR_FILL then BAR_EMPTY tiles into the BG3 tilemap each
frame; the FILL run length tracks a state variable (input / frame counter), so
the rendered bar responds — the D3 dynamic-instrument done-condition.

Outputs (committed):
    dash_chr.inc      ca65 2bpp tile CHR (dash_chr + DASH_CHR_BYTES + DASH_TILE_*)
    dash_palette.inc  ca65 BG3 palette (dash_pal, 4 words -> CGRAM 16..19)

Regenerate (from the materialized kit root, PYTHONPATH=.):
    PYTHONPATH=. python3 templates/split_h_demo/assets/make_dash.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --- BG3 palette (BGR555), CGRAM group 4 slots 16..19 (idx 0 = transparent) ---
# idx 0 is never displayed for BG3 (transparent), but CGRAM[16] must hold *some*
# colour; use a dark band base so if a transparent BG3 cell falls over the
# top-band backdrop the band still reads dark.
PAL = [
    0x0842,   # 0 dark band base (transparent for BG3 anyway) — dim blue-grey
    0x4210,   # 1 frame / outline — steel blue-grey
    0x2108,   # 2 bar EMPTY interior — dim
    0x1EBF,   # 3 bar FILL / lit — bright amber (R high, G high, B low)
]


def _tiles() -> list[list[int]]:
    """Return a list of 8x8 index buffers (values 0..3), tile id = list index."""
    B, F, E, L = 0, 1, 2, 3   # blank, frame, empty, lit

    def solid(v):
        return [v] * 64

    def rows(rr):
        assert len(rr) == 8 and all(len(r) == 8 for r in rr)
        return [v for r in rr for v in r]

    tiles = []
    # 0 BLANK
    tiles.append(solid(B))
    # 1 FRAME_TOP — a 2px top rule in frame colour, rest transparent
    tiles.append(rows([[F] * 8, [F] * 8] + [[B] * 8] * 6))
    # 2 FRAME_BOT — a 2px bottom rule
    tiles.append(rows([[B] * 8] * 6 + [[F] * 8, [F] * 8]))
    # 3 BAR_EMPTY — an outlined cell with a DIM interior
    tiles.append(rows(
        [[F] * 8] +
        [[F] + [E] * 6 + [F] for _ in range(6)] +
        [[F] * 8]))
    # 4 BAR_FILL — an outlined cell with a BRIGHT interior
    tiles.append(rows(
        [[F] * 8] +
        [[F] + [L] * 6 + [F] for _ in range(6)] +
        [[F] * 8]))
    # 5 GAUGE_LIT — a solid bright block (decorative fixed instrument light)
    tiles.append(solid(L))
    # 6 GAUGE_DIM — a solid dim block
    tiles.append(solid(E))
    return tiles


def main() -> None:
    try:
        from toolchain.asset_codec import encode_2bpp_tile_pixels
    except ImportError:
        sys.exit("toolchain/ not importable — run from kit root with PYTHONPATH=.")

    tiles = _tiles()
    names = ["BLANK", "FRAME_TOP", "FRAME_BOT",
             "BAR_EMPTY", "BAR_FILL", "GAUGE_LIT", "GAUGE_DIM"]

    chr_lines = ["; dash_chr.inc — GENERATED (make_dash.py). BG3 2bpp instrument tiles.",
                 "dash_chr:"]
    for tid, buf in enumerate(tiles):
        enc, _remap = encode_2bpp_tile_pixels(buf, label=f"dash tile {tid}")
        assert len(enc) == 16
        body = ", ".join(f"${b:02X}" for b in enc)
        chr_lines.append(f"    .byte {body}    ; tile {tid} {names[tid]}")
    chr_lines.append("")
    chr_lines.append(f"DASH_CHR_BYTES = {len(tiles) * 16}")
    for tid, nm in enumerate(names):
        chr_lines.append(f"DASH_TILE_{nm} = {tid}")
    chr_lines.append("")
    (HERE / "dash_chr.inc").write_text("\n".join(chr_lines))
    print(f"wrote dash_chr.inc ({len(tiles)} tiles, {len(tiles) * 16} bytes)")

    pal_lines = ["; dash_palette.inc — GENERATED (make_dash.py). BG3 palette group 4 (CGRAM 16..19).",
                 "dash_pal:"]
    for i, w in enumerate(PAL):
        pal_lines.append(f"    .word ${w:04X}    ; BG3 colour {i}")
    pal_lines += ["", f"DASH_PAL_COUNT = {len(PAL)}", ""]
    (HERE / "dash_palette.inc").write_text("\n".join(pal_lines))
    print(f"wrote dash_palette.inc ({len(PAL)} colours)")


if __name__ == "__main__":
    main()
