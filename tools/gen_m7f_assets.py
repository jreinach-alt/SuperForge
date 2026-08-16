#!/usr/bin/env python3
"""mode7_flight assets — the overworld plane, the airship and its shadow.

The sweep's LAST rail. Emits five blobs into an output dir:

    m7f_ground.bin   32,768 B  interleaved Mode 7 VRAM image (tilemap | CHR)
    m7f_pal.bin          32 B  16 BGR555 floor colours; index 0 = THE SKY
    m7f_obj_chr.bin   2,048 B  one 4-row x 16-col OBJ grid: airship frames A/B,
                               the big ground shadow, the small high shadow
    m7f_ship_pal.bin     32 B  16 BGR555 words (OBJ palette 0)
    m7f_shadow_pal.bin   32 B  (OBJ palette 1)

EVERYTHING IS AUTHORED. Nothing is converted out of a source `.bin`, which is
deliberate and is the route `mode7_explore` and `m7_oshoot` took:
a converter between a source asset and this output triggers the
asset-import rule (ground-truth the converter against a render it did not produce),
and the cheapest way to discharge that obligation is not to incur it. What the
rail DOES fix is its BEHAVIOUR and GEOMETRY — the 128x128 wrapping plane, the
spawn over a coast cluster, the two shadow sizes and the altitude threshold
that switches them.

INDEX 0 IS THE SKY, and that is a hardware contract rather than a convention.
In Mode 7 an 8bpp pixel value IS an absolute CGRAM index, and the rail's sky is
the BACKDROP revealed where the TM split turns BG1 off (`m7f_floor`). So
CGRAM[0] must be the sky colour, and NO floor tile may contain pixel value 0 —
a floor tile that did would punch a sky-coloured hole in the ground. Both are
asserted below.

Deterministic: no RNG seed drift — `random` is not imported. Every cell is a
pure function of its coordinates, so a re-run is byte-identical, which is what
the rebuild proof and `make falsify`'s md5 arm rest on.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

WORLD_T = 128                    # world side, tiles — the full Mode 7 plane
TILE_PX = 8
MAP_BYTES = WORLD_T * WORLD_T    # 16,384: one byte per world tile
BLOB_BYTES = 2 * MAP_BYTES       # 32,768: the interleaved VRAM image
CHR_TILES = 256                  # 8x8 8bpp tiles the interleave has room for:
CHR_BYTES = CHR_TILES * 64       #   the ODD half is 16,384 B and a tile is 64 B

# The rail's spawn: over a detailed continent/coast cluster
# (SPAWN_X 872 / SPAWN_Y 512 in world pixels on a 1024 px plane), so the boot
# picture opens on land with something to fly over rather than on open ocean.
SPAWN_X, SPAWN_Y = 872, 512

# =============================================================================
# Colours (RGB), 16 of them. Index 0 is THE SKY (never appears in a floor tile).
# =============================================================================
# THE ZENITH, not the whole sky. This word is the BASE colour-math ADDS the
# COLDATA sky ramp to (tools/gen_m7f_gradient.py, `day` snapshot's zenith =
# 5-bit (4, 12, 24)), so it is the deepest blue in the picture and the ramp
# climbs from it to the horizon haze. It was a flat light blue — 5-bit
# (12, 22, 29) — until the ramp landed, and it read as a flat blue square
# across the top third of the screen: a bright
# base plus an ADD saturates in the first few lines and there is no gradient
# left to see. Kept in step with the generator by
# test_the_backdrop_word_is_the_day_snapshot_zenith.
SKY = (4 << 3, 12 << 3, 24 << 3)  # index 0 — CGRAM[0], the backdrop's ZENITH
PALETTE = [
    SKY,
    (0x10, 0x28, 0x70),          # 1  deep ocean
    (0x20, 0x48, 0xA0),          # 2  ocean
    (0x38, 0x78, 0xC0),          # 3  shallow / shelf
    (0xD8, 0xC8, 0x88),          # 4  sand
    (0x58, 0x98, 0x48),          # 5  grass
    (0x40, 0x78, 0x38),          # 6  grass, darker
    (0x28, 0x58, 0x28),          # 7  forest
    (0x1C, 0x40, 0x20),          # 8  deep forest
    (0x88, 0x78, 0x58),          # 9  scrub / foothill
    (0x78, 0x68, 0x60),          # 10 rock
    (0xA8, 0xA0, 0x98),          # 11 high rock
    (0xE8, 0xE8, 0xF0),          # 12 snow
    (0x48, 0x88, 0xB8),          # 13 lake
    (0xC0, 0x98, 0x58),          # 14 road / dune
    (0x30, 0x30, 0x38),          # 15 basalt
]


def bgr555(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)


def pal_bytes(colours: list[tuple[int, int, int]]) -> bytes:
    out = bytearray()
    for c in colours:
        out += struct.pack("<H", bgr555(c))
    return bytes(out)


# =============================================================================
# The terrain field. One pure function of (tx, ty) on a WRAPPING 128x128 plane.
# =============================================================================
# Wrapping matters: `wrap = 1` on the reference rail is what lets free movement
# never reach a black edge, so the field must be periodic in
# both axes or the seam would be a visible discontinuity in the picture. Every
# term below is built from sin/cos of 2*pi*t/128, which is periodic by
# construction.
def _wave(tx: int, ty: int, fx: float, fy: float, phase: float) -> float:
    a = 2 * math.pi / WORLD_T
    return math.sin(a * fx * tx + phase) * math.cos(a * fy * ty + phase * 0.5)


def elevation(tx: int, ty: int) -> float:
    """A periodic height field: two continents, a bay, and a mountain spine."""
    e = 0.62 * _wave(tx, ty, 1, 1, 0.0)
    e += 0.30 * _wave(tx, ty, 2, 1, 1.1)
    e += 0.18 * _wave(tx, ty, 1, 3, 2.3)
    e += 0.10 * _wave(tx, ty, 4, 3, 0.7)
    e += 0.06 * _wave(tx, ty, 6, 5, 1.9)
    return e


def terrain(tx: int, ty: int) -> int:
    """Palette index for a world tile. NEVER 0 — index 0 is the sky."""
    e = elevation(tx, ty)
    if e < -0.45:
        return 1
    if e < -0.22:
        return 2
    if e < -0.06:
        return 3
    if e < 0.02:
        return 4
    if e < 0.16:
        # inland water pockets where the low-frequency term dips locally
        return 13 if _wave(tx, ty, 8, 8, 0.4) > 0.72 else 5
    if e < 0.30:
        return 6 if _wave(tx, ty, 5, 7, 2.0) < 0.30 else 14
    if e < 0.44:
        return 7
    if e < 0.56:
        return 8
    if e < 0.66:
        return 9
    if e < 0.76:
        return 10
    if e < 0.86:
        return 11 if _wave(tx, ty, 9, 9, 1.3) < 0.5 else 15
    return 12


# =============================================================================
# The tile CHR. 64 8x8 tiles, each a FLAT colour plus a deterministic dither.
# =============================================================================
# One tile id per palette index (0..15) x four dither phases, so adjacent world
# cells of the same terrain do not read as one flat sheet when the plane spins
# beneath the ship. The dither is a fixed 8x8 checker mask, not noise.
DITHER_PHASES = 4


def tile_id(pal_index: int, phase: int) -> int:
    return pal_index * DITHER_PHASES + phase


def build_chr() -> bytes:
    """256 tile slots x 64 bytes of 8bpp linear pixels (Mode 7 CHR is linear).

    Only the first 64 slots carry terrain (16 palette indices x 4 dither
    phases); the remaining 192 are never referenced by the tilemap and are
    filled with index 1 rather than 0 — a stray 0 anywhere in the odd half
    would be a sky-coloured pixel if the tilemap ever reached it, and the
    sky-contract assertion in main() checks the WHOLE half, not just the part
    the tilemap uses.
    """
    chr_bytes = bytearray()
    for pal_index in range(16):
        for phase in range(DITHER_PHASES):
            # the companion tone: one step darker within the same family, but
            # never 0 (the sky index).
            alt = max(1, pal_index - 1)
            for py in range(TILE_PX):
                for px in range(TILE_PX):
                    on = ((px + py + phase) & 3) == 0
                    v = alt if (on and phase != 0) else pal_index
                    chr_bytes.append(max(1, v))
    chr_bytes += bytes([1]) * (CHR_BYTES - len(chr_bytes))
    assert len(chr_bytes) == CHR_BYTES, len(chr_bytes)
    return bytes(chr_bytes)


def build_ground() -> bytes:
    """The interleaved VRAM image: even byte = tilemap, odd byte = CHR."""
    chr_bytes = build_chr()
    assert len(chr_bytes) == MAP_BYTES, (len(chr_bytes), MAP_BYTES)
    blob = bytearray(BLOB_BYTES)
    for ty in range(WORLD_T):
        for tx in range(WORLD_T):
            pal_index = terrain(tx, ty)
            assert pal_index != 0, (tx, ty)
            phase = (tx ^ ty) & (DITHER_PHASES - 1)
            i = ty * WORLD_T + tx
            blob[2 * i] = tile_id(pal_index, phase)
    for i, b in enumerate(chr_bytes):
        blob[2 * i + 1] = b
    return bytes(blob)


# =============================================================================
# The cast: one 4-row x 16-col OBJ grid.
# =============================================================================
# The SNES reads a 32x32 sprite as a 4x4 block of 8x8 tiles at {N..N+3,
# N+16..N+19, N+32..N+35, N+48..N+51} — the row stride is 16 TILE SLOTS, fixed
# in hardware — so the sheet is authored as a 16-wide grid and the four objects
# sit at columns 0, 4, 8 and 12 of it.
GRID_W, GRID_H = 16, 4
OBJ_TILES = GRID_W * GRID_H                      # 64 tiles
OBJ_BYTES = OBJ_TILES * 32                       # 4bpp: 32 B per tile

SHIP_TILE_A = 0
SHIP_TILE_B = 4
SHADOW_TILE_BIG = 8
SHADOW_TILE_SMALL = 12
# The two 16x16 cloud shapes, in the slots the 32x32 objects leave behind: the
# small shadow takes 12,13,28,29 of its column, so 14,15,30,31 are free beside
# it, and row 2 column 12 (44,45,60,61) is free entirely. Two shapes rather
# than one so four drawn clouds do not read as four copies.
CLOUD_TILE_A = 14
CLOUD_TILE_B = 44

SHIP_PAL = [
    (0x00, 0x00, 0x00),          # 0 transparent
    (0xE8, 0xE0, 0xC8),          # 1 envelope highlight
    (0xC0, 0xB0, 0x90),          # 2 envelope
    (0x90, 0x80, 0x64),          # 3 envelope shade
    (0xD0, 0x50, 0x40),          # 4 fin / stripe
    (0x50, 0x40, 0x38),          # 5 gondola
    (0x30, 0x28, 0x24),          # 6 gondola shade
    (0xF8, 0xF8, 0xF8),          # 7 propeller blur
] + [(0, 0, 0)] * 8
SHADOW_PAL = [
    (0x00, 0x00, 0x00),          # 0 transparent
    (0x18, 0x28, 0x30),          # 1 shadow core
    (0x28, 0x40, 0x50),          # 2 shadow edge
] + [(0, 0, 0)] * 13


def _ship_pixel(x: int, y: int, frame: int) -> int:
    """A 32x32 side-on airship: ellipsoid envelope, gondola, tail fin, prop."""
    cx, cy = 15.5, 13.0
    ex, ey = (x - cx) / 13.5, (y - cy) / 6.2
    d = ex * ex + ey * ey
    if d <= 1.0:
        if ey < -0.45:
            return 1
        if abs(x - cx) < 3.2 and abs(ey) < 0.72:
            return 4                       # the mid stripe
        return 2 if ey < 0.42 else 3
    # gondola, slung under the envelope
    if 12 <= x <= 20 and 20 <= y <= 24:
        return 5 if y < 23 else 6
    # tail fin at the stern
    if 26 <= x <= 30 and abs(y - cy) < (x - 24) * 1.4 and y < 22:
        return 4
    # propeller: a two-blade disc at the bow, flipped between frames
    px, py = x - 2.0, y - cy
    if px * px + py * py < 30:
        if frame == 0 and abs(py) > abs(px) * 0.5:
            return 7
        if frame == 1 and abs(px) > abs(py) * 0.5:
            return 7
    return 0


def _shadow_pixel(x: int, y: int, size: int) -> int:
    """An elliptical ground shadow. size 32 = the BIG (low) one, 16 = small."""
    c = size / 2.0 - 0.5
    ex, ey = (x - c) / (size * 0.42), (y - c) / (size * 0.20)
    d = ex * ex + ey * ey
    if d <= 0.72:
        return 1
    if d <= 1.0:
        return 2
    return 0


def _put_tile(sheet: bytearray, tile: int, pix) -> None:
    """Pack an 8x8 index block into 4bpp SNES planar at slot `tile`."""
    base = tile * 32
    for row in range(8):
        p0 = p1 = p2 = p3 = 0
        for col in range(8):
            v = pix[row][col] & 0x0F
            bit = 7 - col
            p0 |= (v & 1) << bit
            p1 |= ((v >> 1) & 1) << bit
            p2 |= ((v >> 2) & 1) << bit
            p3 |= ((v >> 3) & 1) << bit
        sheet[base + row * 2 + 0] = p0
        sheet[base + row * 2 + 1] = p1
        sheet[base + 16 + row * 2 + 0] = p2
        sheet[base + 16 + row * 2 + 1] = p3


def _blit(sheet: bytearray, first_tile: int, size: int, fn) -> None:
    """Write a size x size object into the 16-wide grid at `first_tile`."""
    for ty in range(size // 8):
        for tx in range(size // 8):
            pix = [[fn(tx * 8 + c, ty * 8 + r) for c in range(8)]
                   for r in range(8)]
            _put_tile(sheet, first_tile + ty * GRID_W + tx, pix)


# --- the clouds: two soft blobs, drawn as sums of discs ---------------------
# AUTHORED, like everything else in this file. Each shape is the union of three
# overlapping circles with the lower half flattened, which is the cheapest
# thing that reads as a cumulus at 16x16; the palette index falls out of the
# distance to the nearest centre, so the lit top and the shaded underside come
# from the geometry rather than from a hand-painted mask.
CLOUD_DISCS = (
    ((5, 9, 4), (10, 8, 5), (8, 11, 4)),        # shape A
    ((4, 10, 4), (9, 9, 5), (12, 11, 3)),       # shape B
)


def _cloud_pixel(x: int, y: int, variant: int) -> int:
    best = None
    for cx, cy, r in CLOUD_DISCS[variant]:
        d2 = (x - cx) ** 2 + (y - cy) ** 2
        if d2 <= r * r and (best is None or d2 < best[0]):
            best = (d2, cy)
    if best is None or y > 13:
        return 0                                 # transparent
    # Lit above the centre it belongs to, shaded well below it.
    if y < best[1] - 1:
        return 1                                 # highlight
    if y < best[1] + 2:
        return 2                                 # body
    return 3                                     # underside


def build_obj() -> bytes:
    sheet = bytearray(OBJ_BYTES)
    _blit(sheet, CLOUD_TILE_A, 16, lambda x, y: _cloud_pixel(x, y, 0))
    _blit(sheet, CLOUD_TILE_B, 16, lambda x, y: _cloud_pixel(x, y, 1))
    _blit(sheet, SHIP_TILE_A, 32, lambda x, y: _ship_pixel(x, y, 0))
    _blit(sheet, SHIP_TILE_B, 32, lambda x, y: _ship_pixel(x, y, 1))
    _blit(sheet, SHADOW_TILE_BIG, 32, lambda x, y: _shadow_pixel(x, y, 32))
    _blit(sheet, SHADOW_TILE_SMALL, 16, lambda x, y: _shadow_pixel(x, y, 16))
    return bytes(sheet)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.splitlines()[-1], file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    ground = build_ground()
    assert len(ground) == BLOB_BYTES, len(ground)
    # THE SKY CONTRACT, asserted: no floor pixel may be index 0.
    assert all(ground[i] != 0 for i in range(1, BLOB_BYTES, 2)), \
        "a floor CHR byte is index 0 — it would render as sky"
    # ...and the spawn must be over land, which is what makes the boot render
    # the coast cluster rather than open ocean.
    stx, sty = SPAWN_X // TILE_PX, SPAWN_Y // TILE_PX
    assert terrain(stx, sty) >= 4, (stx, sty, terrain(stx, sty))
    # The plane WRAPS (the reference rail's `wrap = 1`), so the field must be
    # PERIODIC in both axes or the seam would be a visible discontinuity the
    # moment the ship crosses it. terrain() takes coordinates off the grid
    # happily — every term is sin/cos of 2*pi*t/128 — so the check is direct.
    for t in (0, 37, 91, 127):
        assert terrain(t, 5) == terrain(t + WORLD_T, 5), t
        assert terrain(5, t) == terrain(5, t + WORLD_T), t

    obj = build_obj()
    assert len(obj) == OBJ_BYTES, len(obj)
    # Every object must cover a real fraction of its box, or "the airship
    # renders" would be a claim about an empty sheet. Counted in PIXELS off the
    # authoring function — a byte count would read the 4bpp planar packing,
    # where a two-colour object legitimately leaves planes 2 and 3 all zero.
    for name, fn, size, floor in (
            ("ship A", lambda x, y: _ship_pixel(x, y, 0), 32, 0.25),
            ("ship B", lambda x, y: _ship_pixel(x, y, 1), 32, 0.25),
            ("shadow big", lambda x, y: _shadow_pixel(x, y, 32), 32, 0.15),
            ("shadow small", lambda x, y: _shadow_pixel(x, y, 16), 16, 0.15)):
        n = sum(1 for y in range(size) for x in range(size) if fn(x, y))
        assert n > floor * size * size, (name, n, size * size)
    # ...and the two propeller frames must actually DIFFER, or the animation is
    # a timer driving one picture.
    assert any(_ship_pixel(x, y, 0) != _ship_pixel(x, y, 1)
               for y in range(32) for x in range(32)), "prop frames identical"

    (out / "m7f_ground.bin").write_bytes(ground)
    (out / "m7f_pal.bin").write_bytes(pal_bytes(PALETTE))
    (out / "m7f_obj_chr.bin").write_bytes(obj)
    (out / "m7f_ship_pal.bin").write_bytes(pal_bytes(SHIP_PAL))
    (out / "m7f_shadow_pal.bin").write_bytes(pal_bytes(SHADOW_PAL))
    print(f"m7f_ground: {len(ground)} B interleaved  "
          f"m7f_obj_chr: {len(obj)} B  palettes: 3 x 32 B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
