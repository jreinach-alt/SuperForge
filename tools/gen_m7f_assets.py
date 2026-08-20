#!/usr/bin/env python3
"""mode7_flight assets — the overworld plane, the airship and its shadow.

The sweep's LAST rail. Emits five blobs into an output dir:

    m7f_ground.bin   32,768 B  interleaved Mode 7 VRAM image (tilemap | CHR)
    m7f_pal.bin          32 B  16 BGR555 floor colours; index 0 = THE SKY
    m7f_obj_chr.bin   3,072 B  one 6-row x 16-col OBJ grid: airship frames A/B,
                               a FIVE-STEP shadow ladder, two cloud shapes
    m7f_ship_pal.bin     32 B  16 BGR555 words (OBJ palette 0)
    m7f_shadow_pal.bin   32 B  (OBJ palette 1)

EVERYTHING IS AUTHORED. Nothing is converted out of a source `.bin`, which is
deliberate and is the route `mode7_explore` and `m7_oshoot` took:
a converter between a source asset and this output triggers the
asset-import rule (ground-truth the converter against a render it did not produce),
and the cheapest way to discharge that obligation is not to incur it. What the
rail DOES fix is its BEHAVIOUR and GEOMETRY — the 128x128 wrapping plane, the
spawn over a coast cluster, and the shadow ladder whose five drawn diameters
are the altimeter.

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
# test_the_sky_is_the_generators_ramp_at_every_scanline.
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
# in hardware — so the sheet is authored as a 16-wide grid, the four 32x32
# objects sit at columns 0, 4, 8 and 12 of its first four rows, and the 16x16
# ones fill the two rows below.
GRID_W, GRID_H = 16, 6
OBJ_TILES = GRID_W * GRID_H                      # 96 tiles
OBJ_BYTES = OBJ_TILES * 32                       # 4bpp: 32 B per tile

# ROWS 0-3 ARE THE 32x32 FLOOR, and it is full: a 32x32 object needs four
# consecutive grid rows, so only four of them fit in the sheet at all and all
# four are spoken for — the two airship frames and the two 32-box shadow steps.
SHIP_TILE_A = 0
SHIP_TILE_B = 4

# THE SHADOW LADDER — five steps, biggest first, and the size a player reads is
# the ART inside the box rather than the box. OBSEL carries ONE size pair for
# the whole frame and this rail has already spent it on (16, 32): the airship
# and the largest shadow are 32x32 and the rest are 16x16, so no SIXTH hardware
# size is buyable at any price. What IS buyable is drawn diameter — a 32-box
# holding a 20 px ellipse reads as a step between the 26 px one and the 14 px
# one — so the ladder is two diameters in the 32 box and three in the 16 box,
# and the step a player sees is the ELLIPSE.
#
# Rows 4-5 are the 16x16 floor: eight slots, five used (two clouds + the three
# small shadow steps) and three left free.
SHADOW_TILES = (8, 12, 68, 70, 72)
SHADOW_BOXES = (32, 32, 16, 16, 16)
# (rx, ry) per step. Step 0 and step 2 reproduce the two diameters this rail
# shipped with — 32*0.42 x 32*0.20 and 16*0.42 x 16*0.20 — so the ladder EXTENDS
# the readout rather than redrawing it; the other three are new.
SHADOW_RADII = ((13.44, 6.40), (10.00, 4.80), (6.72, 3.20),
                (5.20, 2.60), (3.10, 1.55))

# The two 16x16 cloud shapes, in the first two slots of the 16x16 floor. Two
# shapes rather than one so four drawn clouds do not read as four copies.
CLOUD_TILE_A = 64
CLOUD_TILE_B = 66

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


SHIP_CX, SHIP_CY = 15.5, 13.0            # the envelope's centre in its 32 box
SHIP_RX, SHIP_RY = 13.5, 6.2
# TWO ENGINES, ONE AT EACH TIP OF THE ENVELOPE, and they are 90 degrees APART
# rather than in step. The rail shipped with a single propeller disc at the bow
# and a static wedge fin over the stern, so one end of the ship moved and the
# other did not. The stern hub is the bow hub mirrored through the envelope's
# centre — cx +/- rx, the two points where a hull that long has room for a disc
# — and the fin moves up onto the envelope's back, where a real airship's
# vertical stabiliser is anyway and where it is not standing in the propeller.
#
# THE PHASE IS THE POINT. Two blades on one two-frame clock could be drawn in
# step, and a pair of engines turning as one reads as a mirrored decal rather
# than as two engines. Anti-phase costs nothing — no third frame, no extra CHR,
# the same eight-frame clock — and at any instant one disc shows its blades
# edge-on while the other shows them flat, which is what two unsynchronised
# engines look like.
SHIP_PROP_HUBS = (SHIP_CX - SHIP_RX, SHIP_CX + SHIP_RX)   # bow, stern
SHIP_PROP_R2 = 30


def _ship_pixel(x: int, y: int, frame: int) -> int:
    """A 32x32 side-on airship: envelope, gondola, dorsal fin, TWO props."""
    ex, ey = (x - SHIP_CX) / SHIP_RX, (y - SHIP_CY) / SHIP_RY
    d = ex * ex + ey * ey
    if d <= 1.0:
        if ey < -0.45:
            return 1
        if abs(x - SHIP_CX) < 3.2 and abs(ey) < 0.72:
            return 4                       # the mid stripe
        return 2 if ey < 0.42 else 3
    # gondola, slung under the envelope
    if 12 <= x <= 20 and 20 <= y <= 24:
        return 5 if y < 23 else 6
    # dorsal fin, over the stern quarter and clear of the stern propeller
    if 19 <= x <= 25 and 3 <= y <= 8 and y >= 9 - (x - 18) * 1.1:
        return 4
    # the two propeller discs, each a two-blade blur, the pair in anti-phase
    for i, hub in enumerate(SHIP_PROP_HUBS):
        px, py = x - hub, y - SHIP_CY
        if px * px + py * py < SHIP_PROP_R2:
            if ((frame ^ i) & 1) == 0:
                if abs(py) > abs(px) * 0.5:
                    return 7
            elif abs(px) > abs(py) * 0.5:
                return 7
    return 0


def _shadow_pixel(x: int, y: int, box: int, rx: float, ry: float) -> int:
    """One rung of the shadow ladder: an ellipse CENTRED IN ITS BOX.

    `box` is the hardware sprite box (32 or 16) and (rx, ry) the drawn ellipse.
    Centring in the box is what lets the ASM place a step by its box alone:
    the ellipse's centre is always box/2 - 0.5 from the box's corner, so a
    screen x of 128 - box/2 puts every rung's centre on the same column and a
    screen y of (the centre locus) - box/2 puts every rung on the same row.
    That is the defect this ladder was built out of — one screen x served a 32
    box and a 16 box, and the 16 one sat eight pixels left of the ship.
    """
    c = box / 2.0 - 0.5
    ex, ey = (x - c) / rx, (y - c) / ry
    d = ex * ex + ey * ey
    if d <= 0.72:
        return 1
    if d <= 1.0:
        return 2
    return 0


def _shadow_step_pixel(step: int):
    """The pixel function for one rung, bound to its box and radii."""
    box, (rx, ry) = SHADOW_BOXES[step], SHADOW_RADII[step]
    return lambda x, y: _shadow_pixel(x, y, box, rx, ry)


def shadow_extent(step: int) -> tuple[int, int]:
    """(width, height) of the rung's drawn ellipse, in pixels."""
    box = SHADOW_BOXES[step]
    on = [(x, y) for y in range(box) for x in range(box)
          if _shadow_step_pixel(step)(x, y)]
    xs, ys = [p[0] for p in on], [p[1] for p in on]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


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
    for step, first in enumerate(SHADOW_TILES):
        _blit(sheet, first, SHADOW_BOXES[step], _shadow_step_pixel(step))
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
    # THE OBJECTS MAY NOT OVERLAP IN THE SHEET. A 32x32 object reads sixteen
    # tiles at a 16-slot row stride and a 16x16 one reads four, so "these fit"
    # is arithmetic nobody can do by eye — and two objects sharing a slot is a
    # picture, not a build error.
    seen = {}
    for name, first, box in (
            [("ship A", SHIP_TILE_A, 32), ("ship B", SHIP_TILE_B, 32),
             ("cloud A", CLOUD_TILE_A, 16), ("cloud B", CLOUD_TILE_B, 16)]
            + [(f"shadow {i}", t, SHADOW_BOXES[i])
               for i, t in enumerate(SHADOW_TILES)]):
        for ty in range(box // 8):
            for tx in range(box // 8):
                slot = first + ty * GRID_W + tx
                assert slot < OBJ_TILES, (name, slot, OBJ_TILES)
                assert slot not in seen, (name, slot, seen[slot])
                seen[slot] = name
    # Every object must cover a real fraction of its box, or "the airship
    # renders" would be a claim about an empty sheet. Counted in PIXELS off the
    # authoring function — a byte count would read the 4bpp planar packing,
    # where a two-colour object legitimately leaves planes 2 and 3 all zero.
    for name, fn, size, floor in (
            ("ship A", lambda x, y: _ship_pixel(x, y, 0), 32, 0.25),
            ("ship B", lambda x, y: _ship_pixel(x, y, 1), 32, 0.25)):
        n = sum(1 for y in range(size) for x in range(size) if fn(x, y))
        assert n > floor * size * size, (name, n, size * size)
    # ...and the two propeller frames must actually DIFFER, or the animation is
    # a timer driving one picture. BOTH ENDS, separately: a single whole-sprite
    # difference passes on the one-engine ship this replaced, so the halves are
    # counted apart and each must move.
    for half, cols in (("bow", range(0, 16)), ("stern", range(16, 32))):
        moved = sum(1 for y in range(32) for x in cols
                    if _ship_pixel(x, y, 0) != _ship_pixel(x, y, 1))
        assert moved >= 20, (
            f"the {half} half of the airship changes in only {moved} pixels "
            f"between the two frames — that end is not animated")
    # THE LADDER MUST READ AS A LADDER. Five rungs are only an altimeter if a
    # player can tell them apart, so each rung is strictly narrower than the one
    # below it by a margin no anti-aliasing could blur, and the top rung is
    # still a visible mark rather than a stray pixel.
    widths = [shadow_extent(i)[0] for i in range(len(SHADOW_TILES))]
    for i in range(1, len(widths)):
        assert widths[i - 1] - widths[i] >= 3, (widths, i)
    assert widths[-1] >= 5, widths
    assert widths[0] <= 32 and min(SHADOW_BOXES) == 16, widths

    (out / "m7f_ground.bin").write_bytes(ground)
    (out / "m7f_pal.bin").write_bytes(pal_bytes(PALETTE))
    (out / "m7f_obj_chr.bin").write_bytes(obj)
    (out / "m7f_ship_pal.bin").write_bytes(pal_bytes(SHIP_PAL))
    (out / "m7f_shadow_pal.bin").write_bytes(pal_bytes(SHADOW_PAL))
    ladder = " ".join(f"{w}x{h}" for w, h in
                      (shadow_extent(i) for i in range(len(SHADOW_TILES))))
    print(f"m7f_ground: {len(ground)} B interleaved  "
          f"m7f_obj_chr: {len(obj)} B ({OBJ_TILES} tiles, "
          f"{OBJ_BYTES // 2} VRAM words)  palettes: 3 x 32 B")
    print(f"  shadow ladder: {ladder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
