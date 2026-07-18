#!/usr/bin/env python3
# =============================================================================
# make_assets.py — generate the meteor_event template's binary art (self-
# contained; no parent-toolchain reach-back, no commercial source material).
# =============================================================================
# Emits FOUR artifacts into this directory:
#
#   meteor_map.bin   32,768-byte INTERLEAVED Mode 7 VRAM blob (even bytes =
#                    128x128 tilemap, odd bytes = 8bpp tile pixels — the native
#                    Mode 7 VRAM word layout DMA'd by sf_mode7_load_map). The
#                    image is a CRATERED ROCK (distributed craters + a hot
#                    core + a molten rim) over a black sky, dead-centred on the
#                    128x128 grid so the affine pivot (MET_CX/MET_CY = 512) sits
#                    EXACTLY on the meteor's art centre (so the Mode-7 zoom is
#                    centred and the tumble spins in place). NO magenta flare
#                    (that was a test hack — dropped per the locked design).
#
#   meteor_pal.inc   the Mode 7 / BG palette: 16 BGR15 colours. Index 0 = black
#                    backdrop; 1..3 grey rock; 4 = platform GREEN (shared with
#                    BG1/OBJ); 5 orange; 6 white player; 7 hot yellow core;
#                    8 deep-red molten rim. >= 4 DISTINCT meteor colours.
#                    During the Mode-1 phase these same CGRAM 0..15 entries also
#                    serve BG1 (gotcha: CGRAM 0-15 is SHARED), so the platform
#                    green lives at index 4 here too.
#
#   obj_assets.inc   the OBJ CHR + OBJ palette. OBSEL $62 -> small=16x16,
#                    large=32x32. 64 tiles (4 tile-rows x 16) = 2048 bytes:
#                    - green 16x16 platform/ground block  -> tiles {0,1,16,17}
#                    - white 16x16 player block           -> tiles {2,3,18,19}
#                    - meteor SPRITE fireball frames (radial: hot core -> cooler
#                      edge), pre-drawn at growing sizes for the far approach:
#                        FAR  16x16 tiny blob   -> tiles {4,5,20,21}
#                        MID  16x16 fuller blob -> tiles {6,7,22,23}
#                        BIG  32x32 fireball    -> 4x4 block, base tile 8
#                          (tiles 8,9,10,11 / 24..27 / 40..43 / 56..59)
#                    Mode-7 owns VRAM $0000-$3FFF; OBJ CHR lives at word $4000
#                    (OBSEL $62) so it survives the Mode-1 <-> Mode-7 swap.
#
#   bg_assets.inc    the Mode-1 BG1 CHR: tile 0 = blank(black), tile 1 = solid
#                    green platform/ground (same green index 4 as the OBJ block).
#
# Regenerate:  python3 templates/meteor_event/assets/make_assets.py
# =============================================================================
import os
import math

HERE = os.path.dirname(os.path.abspath(__file__))

# --- shared palette indices (CGRAM 0..15, shared BG1 <-> Mode7) ---
PAL = [0x0000] * 16
PAL[0] = 0x0000   # backdrop black
PAL[1] = 0x18C6   # dark grey rock
PAL[2] = 0x2D6B   # mid grey rock
PAL[3] = 0x3DEF   # light grey rock
PAL[4] = 0x03E0   # GREEN platform/ground (BG tile1 + OBJ ground share this)
PAL[5] = (0 << 10) | (16 << 5) | 31    # orange (r=31,g=16,b=0)
PAL[6] = 0x7FFF   # white player
PAL[7] = (4 << 10) | (31 << 5) | 31    # hot yellow core (r=31,g=31,b=4)
PAL[8] = (0 << 10) | (0 << 5) | 24     # deep-red molten rim (r=24,g=0,b=0)
# index 9 left for a brighter orange-red used on the sprite fireball edge
PAL[9] = (0 << 10) | (8 << 5) | 31     # red-orange (r=31,g=8,b=0)


# ---------------------------------------------------------------------------
# Mode 7 meteor map (128x128, 8bpp tiles, interleaved VRAM blob)
# ---------------------------------------------------------------------------
def meteor_color(tx, ty):
    """Per-tile 8bpp palette index for the meteor on the 128x128 grid.

    A CRATERED ROCK — lumpy (clearly non-circular) outline so a tumble reads as
    a body spinning, with a hot core, distributed dark craters and a molten rim.
    Dead-centred on the affine pivot (tile 64,64 = MET_CX/CY = pixel 512). NO
    magenta flare — the lumpy silhouette + distributed craters carry the tumble.
    The art is symmetric about NEITHER axis (the crater set is asymmetric), so
    two frames at different rotation angles differ — the tumble check's signal."""
    cx, cy = 64, 64
    dx, dy = tx - cx, ty - cy
    d = math.hypot(dx, dy)
    ang = math.atan2(dy, dx)
    # lumpy outline: base radius modulated by angle -> clearly non-circular
    R = 25.0 + 4.0 * math.sin(3 * ang + 0.7) + 2.5 * math.sin(5 * ang - 1.3)
    if d > R:
        return 0          # black sky
    # hot core + orange shell (centred on the pivot)
    if d <= 5.0:
        return 7          # hot yellow core
    if d <= 9.0:
        return 5          # orange shell
    # distributed dark craters -> surface features that visibly rotate. The set
    # is asymmetric (no mirror symmetry) so the spin is legible frame-to-frame.
    for kx, ky, kr in ((-11, -5, 4), (8, 10, 5), (-5, 13, 3), (14, 1, 3), (3, -14, 4)):
        if (tx - (cx + kx)) ** 2 + (ty - (cy + ky)) ** 2 <= kr * kr:
            return 1      # dark crater
    # rocky body: mottled grey, darker toward the rim, with a cheap crater hash
    if d <= 16.0:
        return 2 + ((tx ^ ty) & 1)        # mid grey (2 or 3)
    if d <= 21.0:
        return 1 + ((tx + ty) & 1)        # darker grey (1 or 2)
    return 8              # deep-red molten rim


def build_mode7_blob():
    NCOLORS = 10
    tile_data = bytearray()
    for ci in range(256):
        if ci < NCOLORS:
            tile_data += bytes([ci]) * 64
        else:
            tile_data += bytes(64)
    assert len(tile_data) == 256 * 64, len(tile_data)

    tilemap = bytearray(128 * 128)
    for ty in range(128):
        for tx in range(128):
            tilemap[ty * 128 + tx] = meteor_color(tx, ty)

    blob = bytearray(0x8000)
    for i in range(0x4000):
        blob[2 * i] = tilemap[i] if i < len(tilemap) else 0
        blob[2 * i + 1] = tile_data[i] if i < len(tile_data) else 0
    return blob


# ---------------------------------------------------------------------------
# 4bpp planar tile encoder (SNES 4bpp: 2 bitplanes interleaved per row for the
# low pair, then 2 for the high pair). Encodes ARBITRARY 8x8 palette-index art.
# ---------------------------------------------------------------------------
def tile_4bpp(px):
    """px: 8x8 list-of-rows of palette indices 0..15 -> 32 bytes SNES 4bpp."""
    out = bytearray()
    # planes 0,1 interleaved row by row (16 bytes), then planes 2,3 (16 bytes)
    for plane_pair in (0, 2):
        for y in range(8):
            b_lo = b_hi = 0
            for x in range(8):
                v = px[y][x]
                bit_lo = (v >> plane_pair) & 1
                bit_hi = (v >> (plane_pair + 1)) & 1
                b_lo |= bit_lo << (7 - x)
                b_hi |= bit_hi << (7 - x)
            out.append(b_lo)
            out.append(b_hi)
    return bytes(out)


def solid_tile_4bpp(ci):
    px = [[ci] * 8 for _ in range(8)]
    return tile_4bpp(px)


def fiery_block(npx, r):
    """Render an npx-by-npx FIERY meteor speck (distant fireball) as a grid of
    palette indices, centred in the cell with apparent radius r. Lumpy edge
    R(a)=r*(1+0.04*sin(2a)). Owner-approved pixel rule (d = dist from centre):
      d<=0.26r ->7 (yellow core); <=0.46r ->5 (orange); <=0.80r ->9 (red-orange);
      else ->8 (deep red). Transparent (0) outside R(a)."""
    n = npx
    c = (n - 1) / 2.0
    grid = [[0] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            dx, dy = x - c, y - c
            d = math.hypot(dx, dy)
            a = math.atan2(dy, dx)
            R = r * (1.0 + 0.04 * math.sin(2 * a))
            if d > R:
                grid[y][x] = 0
            elif d <= 0.26 * r:
                grid[y][x] = 7
            elif d <= 0.46 * r:
                grid[y][x] = 5
            elif d <= 0.80 * r:
                grid[y][x] = 9
            else:
                grid[y][x] = 8
    return grid


def rocky_block(npx, r):
    """Render an npx-by-npx ROCKY meteor (resolved rock) as a grid of palette
    indices, centred with apparent radius r. Lumpy edge R(a)=r*(1+0.14*sin(3a+0.7)
    +0.07*sin(5a-1.3)) — matches the Mode-7 rock's silhouette so the crossover is
    seamless. Owner-approved pixel rule:
      d<=0.26r ->7 (core); <=0.46r ->5 (orange); d>0.86r ->8 (red rim);
      else grey body 2+((x^y)&1), EXCEPT craters ->1 at the relative offsets below
      (each crater radius 0.15r). Transparent (0) outside R(a)."""
    n = npx
    c = (n - 1) / 2.0
    craters = [(-0.32, -0.18), (0.22, 0.30), (-0.10, 0.42), (0.40, -0.05)]
    grid = [[0] * n for _ in range(n)]
    for y in range(n):
        for x in range(n):
            dx, dy = x - c, y - c
            d = math.hypot(dx, dy)
            a = math.atan2(dy, dx)
            R = r * (1.0 + 0.14 * math.sin(3 * a + 0.7) + 0.07 * math.sin(5 * a - 1.3))
            if d > R:
                grid[y][x] = 0
                continue
            if d <= 0.26 * r:
                grid[y][x] = 7
            elif d <= 0.46 * r:
                grid[y][x] = 5
            elif d > 0.86 * r:
                grid[y][x] = 8
            else:
                v = 2 + ((x ^ y) & 1)        # mottled grey body
                for (ox, oy) in craters:     # dark craters reorient under flips
                    if math.hypot(dx - ox * r, dy - oy * r) <= 0.15 * r:
                        v = 1
                        break
                grid[y][x] = v
    return grid


def block_to_tiles(grid):
    """Cut an (8k x 8k) palette-index grid into 8x8 tiles in PPU name order:
    left-to-right within a tile-row, top tile-row first (matches the 16-wide
    name-table stride the engine uses for large sprites). Returns list of 32-byte
    tiles."""
    n = len(grid)
    tw = n // 8
    tiles = []
    for trow in range(tw):
        for tcol in range(tw):
            sub = [grid[trow * 8 + r][tcol * 8: tcol * 8 + 8] for r in range(8)]
            tiles.append(tile_4bpp(sub))
    return tiles


BLANK = bytes(32)

# 32x32 sprite base tiles read a 4x4 block on the 16-wide name grid:
#   {N..N+3, N+16..N+19, N+32..N+35, N+48..N+51}
def _block16_slots(base):
    return [base + r * 16 + col for r in range(4) for col in range(4)]


def emit_obj(f):
    # 128-tile CHR (8 tile-rows x 16 = 4096 bytes), in the upper-32KB OBJ region.
    #   16x16 sprite at base N reads {N,N+1,N+16,N+17}
    #   32x32 sprite at base N reads {N..N+3, N+16..N+19, N+32..N+35, N+48..N+51}
    # The SIX meteor sprite growth frames are each a SINGLE OBJ sprite (no 2x2
    # tiling): three 16x16 FIERY specks (r=3/5/7) then three 32x32 ROCKY frames
    # (r=10/13/15.5); the last (r15.5) is the crossover frame and resembles the
    # Mode-7 rock so the hand-off is seamless.
    NTILES = 128
    tiles = [BLANK] * NTILES

    # green platform/ground 16x16 -> {0,1,16,17}
    for t in (0, 1, 16, 17):
        tiles[t] = solid_tile_4bpp(4)
    # white player 16x16 -> {2,3,18,19}
    for t in (2, 3, 18, 19):
        tiles[t] = solid_tile_4bpp(6)

    # --- 16x16 FIERY specks: base tiles 4, 6, 8 (rows 0/1) ---
    for base, r in ((4, 3.0), (6, 5.0), (8, 7.0)):
        blk = fiery_block(16, r)
        bt = block_to_tiles(blk)             # [TL,TR,BL,BR]
        for slot, t in zip((base, base + 1, base + 16, base + 17), bt):
            tiles[slot] = t

    # --- 32x32 ROCKY frames: base tiles 64, 68, 72 (rows 4-7, all free) ---
    for base, r in ((64, 10.0), (68, 13.0), (72, 15.5)):
        blk = rocky_block(32, r)
        bt = block_to_tiles(blk)             # 16 tiles, name order
        for slot, t in zip(_block16_slots(base), bt):
            tiles[slot] = t

    f.write("; GENERATED by make_assets.py — OBJ CHR (128 tiles, 4096 bytes).\n")
    f.write("; {0,1,16,17}=green ground  {2,3,18,19}=white player\n")
    f.write("; meteor sprite growth (each a SINGLE OBJ sprite):\n")
    f.write(";   16x16 FIERY  base 4 (r3), 6 (r5), 8 (r7)\n")
    f.write(";   32x32 ROCKY  base 64 (r10), 68 (r13), 72 (r15.5 = crossover frame)\n")
    f.write("meteor_obj_chr_bytes = %d\n" % (NTILES * 32))
    f.write("meteor_obj_chr:\n")
    for t in tiles:
        for i in range(0, 32, 16):
            f.write("    .byte " + ", ".join("$%02X" % b for b in t[i:i + 16]) + "\n")
    f.write("\n; OBJ palette (16 BGR15): match BG/CGRAM (4 green, 6 white, fireball 5/7/8/9)\n")
    f.write("meteor_obj_pal:\n")
    for c in PAL:
        f.write("    .word $%04X\n" % c)


def emit_bg(f):
    f.write("; GENERATED by make_assets.py — BG1 CHR: tile0 blank, tile1 green platform.\n")
    f.write("meteor_bg_chr_bytes = 64\n")
    f.write("meteor_bg_chr:\n")
    for ci in (0, 4):
        t = solid_tile_4bpp(ci)
        for i in range(0, 32, 16):
            f.write("    .byte " + ", ".join("$%02X" % b for b in t[i:i + 16]) + "\n")


def emit_pal(f):
    f.write("; GENERATED by make_assets.py — Mode 7 / BG1 shared palette (CGRAM 0..15).\n")
    f.write("; >=4 distinct meteor colours (1,2,3,5,7,8) for the textured-plane gate.\n")
    f.write("METEOR_PAL_COUNT = 16\n")
    f.write("meteor_pal:\n")
    for c in PAL:
        f.write("    .word $%04X\n" % c)


def main():
    blob = build_mode7_blob()
    with open(os.path.join(HERE, "meteor_map.bin"), "wb") as f:
        f.write(blob)
    with open(os.path.join(HERE, "meteor_pal.inc"), "w") as f:
        emit_pal(f)
    with open(os.path.join(HERE, "obj_assets.inc"), "w") as f:
        emit_obj(f)
    with open(os.path.join(HERE, "bg_assets.inc"), "w") as f:
        emit_bg(f)
    seen = set()
    for ty in range(128):
        for tx in range(128):
            seen.add(meteor_color(tx, ty))
    print("wrote meteor_map.bin (%d bytes), meteor_pal.inc, obj_assets.inc, bg_assets.inc" % len(blob))
    print("distinct meteor map colour indices:", sorted(seen))


if __name__ == "__main__":
    main()
