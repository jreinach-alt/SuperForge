#!/usr/bin/env python3
"""gen_sky.py — deterministic microzero BG2 sky-band assets.

Emits (byte-identical on re-run, pure integer math):
  sky_chr.bin   SKY_TILES x 32 B, 4bpp — a dithered luminance ramp
  sky_map.bin   32x32 BG2 tilemap words, little-endian
  sky_pal.bin   SKY_COLORS BGR555 words — the ramp's base colours

Division of labour with rgb_gradient: this layer supplies TEXTURE, the
COLDATA gradient supplies COLOUR. The base colours here are a dark ramp, so
the per-scanline fixed-colour add (deep blue at the top of the band, warm at
the horizon) lands on top of them and reads as a smooth vertical gradient
with dither banding — the reference sky treatment. Making the base colours
bright instead would saturate against the add and flatten the gradient.

NO PIXEL USES PALETTE INDEX 0. Index 0 is transparent for a BG layer, so a
0 pixel would punch through to the backdrop — and the backdrop is outside
color math, so those pixels would render as unlit holes in the sky.
"""
import sys
from pathlib import Path

T = 8                                   # tile side, px
SKY_TILES = 8                           # CHR slots claimed
SKY_COLORS = 4                          # ramp entries: palette indices 1..4
MAP_W = MAP_H = 32                      # BG2 32x32 tilemap
SKY_PAL = 4                             # BG2 palette number (CGRAM 64..79)

# Base ramp, deliberately dark — see the module docstring. (r, g, b), 5-bit.
RAMP = [(1, 1, 2), (3, 3, 5), (5, 5, 8), (7, 7, 11)]
assert len(RAMP) == SKY_COLORS


def bgr(r: int, g: int, b: int) -> int:
    assert 0 <= r < 32 and 0 <= g < 32 and 0 <= b < 32, (r, g, b)
    return (b << 10) | (g << 5) | r


def encode_4bpp(pixels: list[int]) -> bytes:
    """64 palette indices (row-major) -> one 32-B SNES 4bpp tile.

    Rejects any index outside 1..SKY_COLORS instead of masking it: silent
    bitwise quantisation in an asset encoder is a documented trap (index 5
    becoming index 1 with no diagnostic). Index 0 is rejected too — see the
    module docstring."""
    assert len(pixels) == 64, len(pixels)
    bad = {p for p in pixels if not 1 <= p <= SKY_COLORS}
    assert not bad, (
        f"sky tile uses palette indices {sorted(bad)} — legal range is "
        f"1..{SKY_COLORS} (0 is transparent and would show the backdrop)")
    # hardware layout: bytes 0..15 are bitplanes 0/1 interleaved per row,
    # bytes 16..31 are bitplanes 2/3 the same way
    out = bytearray()
    for lo_plane in (0, 2):
        for y in range(T):
            row = pixels[y * T:(y + 1) * T]
            for plane in (lo_plane, lo_plane + 1):
                byte = 0
                for x, p in enumerate(row):
                    byte |= ((p >> plane) & 1) << (7 - x)
                out.append(byte)
    return bytes(out)


def dither_tile(a: int, b: int, level: int) -> list[int]:
    """An 8x8 ordered dither between palette indices a and b.

    level 0 = all a, 4 = all b; the 4x4 Bayer threshold gives the stops in
    between, which is what produces visible banding rather than a hard edge
    where two ramp colours meet."""
    bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
    out = []
    for y in range(T):
        for x in range(T):
            thr = bayer[y & 3][x & 3]
            out.append(b if thr < level * 4 else a)
    return out


def tiles() -> list[bytes]:
    """The ramp: solid, half-dither, solid, ... across the base colours.

    8 tiles cover the 6 visible tile rows of the band with headroom."""
    seq = []
    for i in range(SKY_COLORS - 1):
        seq.append(dither_tile(i + 1, i + 2, 0))     # solid colour i+1
        seq.append(dither_tile(i + 1, i + 2, 2))     # half-way dither
    seq.append(dither_tile(SKY_COLORS, SKY_COLORS, 0))          # solid top
    seq.append(dither_tile(SKY_COLORS - 1, SKY_COLORS, 3))      # spare stop
    assert len(seq) == SKY_TILES, len(seq)
    return [encode_4bpp(p) for p in seq]


def tilemap() -> bytes:
    """Horizontal bands, one tile row per ramp stop, darkest at the top.

    The band is HUD_LINES(44) scanlines tall = 6 tile rows; rows past that
    are never displayed (TM shows BG2 only above the seam) but are still
    written, so no displayed-or-not cell is left uninitialised."""
    attr = SKY_PAL << 10                 # palette select; priority 0, no flip
    out = bytearray()
    for row in range(MAP_H):
        tile = min(row, SKY_TILES - 1)
        for _ in range(MAP_W):
            out += (attr | tile).to_bytes(2, "little")
    return bytes(out)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    chr_blob = b"".join(tiles())
    assert len(chr_blob) == SKY_TILES * 32, len(chr_blob)
    (out / "sky_chr.bin").write_bytes(chr_blob)

    map_blob = tilemap()
    assert len(map_blob) == MAP_W * MAP_H * 2, len(map_blob)
    (out / "sky_map.bin").write_bytes(map_blob)

    pal_blob = b"".join(bgr(*c).to_bytes(2, "little") for c in RAMP)
    assert len(pal_blob) == SKY_COLORS * 2, len(pal_blob)
    (out / "sky_pal.bin").write_bytes(pal_blob)

    print(f"sky assets -> {out} ({SKY_TILES} tiles, {len(map_blob)} B map, "
          f"{SKY_COLORS} colours at CGRAM {SKY_PAL * 16 + 1})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
