#!/usr/bin/env python3
"""superforge -- mill's BG1, re-cut as DIRECT COLOUR.

The variant half of `tools/gen_mill_assets.py`, and DELIBERATELY A SEPARATE
FILE that imports it rather than a branch threaded through its painters. The
shipping rail's generator must keep emitting the same bytes it always did, and
the cheapest way to be sure of that is for it not to have been edited.

=============================================================================
WHAT DIRECT COLOUR IS, READ OFF THE SILICON
=============================================================================
With CGWSEL bit 0 set, an 8bpp layer's pixel byte IS its colour and CGRAM is
not consulted at all. `GetRgbColor` (Mesen2 SnesPpu.cpp:1068-1077) takes that
arm under `if constexpr(bpp == 8 && directColorMode)` and builds a BGR555 word
from the pixel AND the tilemap entry's 3-bit palette field:

    R = ((pixel & 0x07) << 2) | ((pal & 1) << 1)
    G = (((pixel >> 3) & 0x07) << 2) | (pal & 2)
    B = (((pixel >> 6) & 0x03) << 3) | (pal & 4)

Three bits of red, three of green, TWO of blue, and one more bit per channel
from the map word. In the indexed build those three map bits are dead — the
next line of that same function says so, "Ignore palette bits for 256-color
layers" (:1077) — so this build is the one that makes them load-bearing. It is
also why the quantiser below is per TILE and not per pixel: the palette field
belongs to the map entry, so all 64 pixels of a tile share one, and the
choice of which one is a fit over the tile.

PIXEL 0 IS STILL TRANSPARENT. `if(color > 0)` guards the draw (:1047) whatever
CGWSEL holds, so index 0 in the painted buffer maps to direct value 0 and the
darkest expressible opaque colour is one step up.

=============================================================================
WHY IT QUANTISES THE CUT TILES AND NOT THE PAINTED BUFFER
=============================================================================
`gen_mill_assets.cut()` dedupes 8x8 blocks across BOTH rooms, and the tile
indices it hands back are what the two tilemaps are made of. This module cuts
the SAME painted buffers with the SAME function and then re-colours the tiles
it got, in place, so:

  * the tile COUNT and the tile ORDER are identical to the shipping build;
  * both tilemaps keep their tile numbers exactly, and gain only the palette
    field this build needs;
  * every geometric property the rail proves -- the fetch lead, the column
    plan, the shaft invariance, the floor bitmap -- is the same geometry,
    because it is the same cut.

The two ROMs are therefore comparable frame for frame, which is the point of
building a variant at all rather than a second rail.

Run:  python3 tools/gen_mill_direct.py <outdir>      (after gen_mill_assets)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gen_mill_assets import (                                   # noqa: E402
    BG1_IX0, CHR1_TILES, COLS, PAL_BG1, ROWS, TILE_HI, cut,
    head_row, lobby_hi_cols, lobby_hi_rows, paint_bg1, paint_lobby,
    assert_shaft_invariance, HEAD_ROWS, SHAFT_COLS, STATION_AT)

# The eye's weighting, `tools/fit_mill_palette.py`'s WEIGHT verbatim -- the
# same number the shipping palette was fitted under, so "closer" means the
# same thing in both builds.
WEIGHT = (2, 4, 1)

# A PLANT HOOK, and it is the one the falsification harness aims at. See
# tools/plants/mill.py: a quantiser that ignores the palette field is exactly
# the defect a 3-3-2-only test cannot see, because the picture stays
# recognisable and only the low bit of each channel is wrong.
PALETTE_BITS = True


def encode_8bpp_direct(rows, who):
    """One 8x8 tile, 64 bytes: four bitplane PAIRS, planes 0/1 then 2/3 then
    4/5 then 6/7 -- `gen_mill_assets.encode_8bpp`'s layout, and NOT that
    function.

    It is not that function because of one assert in it: the shipping encoder
    refuses a pixel value at or above 128, because in the INDEXED build a
    pixel value is a CGRAM index and 128 and up belong to OBJ
    (SnesPpu.cpp:960). Here a pixel value is not an index into anything --
    bits 6 and 7 ARE the blue channel (:1076) -- so half the colour space
    would be unreachable under that rule, and the rule is about the other
    build. Copying the loop rather than adding a flag to the shipping one
    keeps the shipping generator untouched, which is what makes its output's
    md5 an argument.
    """
    out = bytearray()
    for pair in range(4):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                assert 0 <= v < 256, f"{who}: value {v} is not one byte"
                lo |= ((v >> (pair * 2)) & 1) << (7 - x)
                hi |= ((v >> (pair * 2 + 1)) & 1) << (7 - x)
            out += bytes((lo, hi))
    return bytes(out)


# --------------------------------------------------------------------------
# the colour arithmetic -- Mesen2 SnesPpu.cpp:1071-1076, transcribed
# --------------------------------------------------------------------------
def direct_bgr555(pixel: int, pal: int) -> int:
    """The BGR555 word the PPU renders for (pixel byte, tilemap palette field).

    Transcribed from the expression, not from a remembered summary of it:

        ((((colorIndex & 0x07) << 1) | (paletteIndex & 0x01)) << 1) |
        (((colorIndex & 0x38) | ((paletteIndex & 0x02) << 1)) << 4) |
        (((colorIndex & 0xC0) | ((paletteIndex & 0x04) << 3)) << 7)

    ...regrouped per channel, which is the same word: the shifts above place
    the pixel's 3/3/2 into bits 2-4 / 7-9 / 13-14 and the palette's three
    bits into 1 / 6 / 12.
    """
    r = ((pixel & 0x07) << 2) | ((pal & 0x01) << 1)
    g = (((pixel >> 3) & 0x07) << 2) | (pal & 0x02)
    b = (((pixel >> 6) & 0x03) << 3) | (pal & 0x04)
    return r | (g << 5) | (b << 10)


def _target(ix: int) -> tuple[int, int, int]:
    """The colour the INDEXED build renders for a painted index, in 5-bit
    channels. That is what this build is trying to reach, so the two ROMs
    differ by quantisation and not by art direction."""
    w = PAL_BG1[ix - BG1_IX0]
    return (w & 31, (w >> 5) & 31, (w >> 10) & 31)


def _best_pixel(t: tuple[int, int, int], pal: int) -> int:
    """The pixel byte closest to target `t` under a fixed palette field.

    Each channel is independent -- the pixel contributes the high bits and the
    palette field the low one -- so the nearest step is arithmetic, not a
    search. The one coupling is TRANSPARENCY: a pixel byte of 0 is not drawn
    at all, so a target that lands there has to be bumped to the cheapest
    non-zero neighbour instead of silently disappearing.
    """
    r = min(7, max(0, round((t[0] - ((pal & 1) << 1)) / 4)))
    g = min(7, max(0, round((t[1] - (pal & 2)) / 4)))
    b = min(3, max(0, round((t[2] - (pal & 4)) / 8)))
    c = r | (g << 3) | (b << 6)
    if c:
        return c
    # Nearest opaque byte: one step up whichever channel costs least. The
    # three candidates are r=1, g=1 and b=1; b is 8 units and the others 4,
    # so this is not a foregone conclusion once the target has any blue.
    return min((1, 1 << 3, 1 << 6),
               key=lambda cand: _err(t, direct_bgr555(cand, pal)))


def _err(t: tuple[int, int, int], word: int) -> int:
    got = (word & 31, (word >> 5) & 31, (word >> 10) & 31)
    return sum(w * (a - b) ** 2 for w, a, b in zip(WEIGHT, t, got))


def quantise_tile(tile: list[list[int]]) -> tuple[list[list[int]], int]:
    """One painted 8x8 index tile -> (direct-colour pixels, palette field).

    The palette field is chosen by fitting all eight of them to the tile's
    OPAQUE pixels and taking the least total weighted error; the pixel bytes
    then follow from it. Ties go to the lowest field, so the choice is
    deterministic and a re-run cannot move a byte.
    """
    px = [v for row in tile for v in row if v]
    if not px:
        return [[0] * 8 for _ in range(8)], 0
    targets = {v: _target(v) for v in set(px)}
    fields = range(8) if PALETTE_BITS else (0,)
    best_pal, best_cost = 0, None
    for pal in fields:
        cost = sum(_err(targets[v], direct_bgr555(_best_pixel(targets[v], pal),
                                                  pal))
                   for v in px)
        if best_cost is None or cost < best_cost:
            best_pal, best_cost = pal, cost
    out = [[(_best_pixel(targets[v], best_pal) if v else 0) for v in row]
           for row in tile]
    return out, best_pal


# --------------------------------------------------------------------------
# the invariance contract, re-checked on the RENDERED colour
# --------------------------------------------------------------------------
def assert_shaft_invariance_rendered(tmap, tiles, pals, buf):
    """`gen_mill_assets.assert_shaft_invariance` says a V-displaced shaft
    column must be identical row to row IN THE PAINTED INDICES. That check
    still runs, on the same buffer, and it is no longer sufficient here: this
    build's colour depends on the tile's palette field as well as its pixels,
    so a shaft whose blocks deduped to one tile in the indexed build could in
    principle be split across tiles that chose different fields -- and the
    seam would slide with the displacement, which is the exact artefact the
    contract exists to prevent.

    So this re-checks the property the picture actually has: for every x in a
    shaft, the set of RENDERED words outside the head band must be a single
    colour.
    """
    for st, s in enumerate(STATION_AT):
        band = range(head_row(st), head_row(st) + HEAD_ROWS)
        for x in range((s + 1) * 8, (s + 1 + SHAFT_COLS) * 8):
            c, xi = x // 8, x % 8
            seen = set()
            for r in range(ROWS):
                if r in band:
                    continue
                t = tmap[r][c]
                for yi in range(8):
                    seen.add(direct_bgr555(tiles[t][yi][xi], pals[t]))
            assert len(seen) == 1, (
                f"station {st} shaft x={x} renders {len(seen)} distinct "
                f"direct colours outside the head band — a V-displaced column "
                f"must be identical row to row")


def main(outdir: str) -> None:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    # The SAME cut the shipping generator makes, from the same painters: one
    # shared tile set across the hall and the lobby, in the same order.
    hall = paint_bg1()
    assert_shaft_invariance(hall)
    tiles, ix = [], {}
    _, map1 = cut(hall, tiles, ix)
    lobby = paint_lobby()
    _, map_lobby = cut(lobby, tiles, ix)
    assert len(tiles) <= CHR1_TILES, (
        f"BG1 needs {len(tiles)} tiles, the page holds {CHR1_TILES}")

    for row in hall:
        for v in row:
            assert v == 0 or v >= BG1_IX0, (
                f"painted index {v} is below BG1_IX0 — the direct-colour cut "
                f"assumes 0 means transparent and everything else is a BG1 "
                f"palette entry")

    dc = [quantise_tile(t) for t in tiles]
    pals = [p for _, p in dc]
    pixels = [q for q, _ in dc]
    assert_shaft_invariance_rendered(map1, pixels, pals, hall)

    chr1 = b"".join(encode_8bpp_direct(t, f"bg1 direct tile {i}")
                    for i, t in enumerate(pixels))
    chr1 += bytes(64 * (CHR1_TILES - len(pixels)))
    (out / "mil_chr1_dc.bin").write_bytes(chr1)

    def emit_map(tmap, hi_cols=(), hi_rows=()):
        hi_c, hi_r = set(hi_cols), set(hi_rows)
        blob = bytearray()
        for r in range(ROWS):
            for c in range(COLS):
                t = tmap[r][c] if r < len(tmap) else 0
                w = t | (pals[t] << 10)
                if r in hi_r and c in hi_c:
                    w |= TILE_HI
                blob += bytes((w & 0xFF, w >> 8))
        return bytes(blob)

    (out / "mil_map1_dc.bin").write_bytes(emit_map(map1))
    (out / "mil_lobby_dc.bin").write_bytes(
        emit_map(map_lobby, lobby_hi_cols(), lobby_hi_rows()))

    # WHAT THE RE-COLOUR COST, measured rather than asserted, in the same
    # eye-weighted squared units `tools/fit_mill_palette.py` reports. THE
    # BASELINE IS THE OTHER ROM, not the source art: this is how far the
    # direct-colour picture lands from the colour the INDEXED build renders
    # for the same painted index, which is the quantity a reader comparing
    # the two renders is looking at. (The fitter's own figure is a different
    # baseline -- indexed build against the kit's source pixels -- so the two
    # numbers do not subtract.)
    n = err = 0
    for t, (q, pal) in zip(tiles, dc):
        for row, qrow in zip(t, q):
            for v, c in zip(row, qrow):
                if v:
                    n += 1
                    err += _err(_target(v), direct_bgr555(c, pal))
    used = sorted({p for p in pals})
    print(f"  mill-direct: {len(pixels)}/{CHR1_TILES} tiles re-cut, "
          f"{len(chr1)} B; palette fields used {used}; "
          f"mean weighted error {err / max(n, 1):.1f} over {n} opaque px "
          f"against what mill.sfc renders for the same pixel")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
