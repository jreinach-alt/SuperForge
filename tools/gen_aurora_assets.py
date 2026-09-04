#!/usr/bin/env python3
"""gen_aurora_assets — the end-credits sky, drawn WITHOUT A PALETTE.

=============================================================================
WHAT THIS EMITS AND WHY THE SPLIT IS WHERE IT IS
=============================================================================
BG1 is the sky and the aurora, 8bpp, read as DIRECT COLOUR: the pixel byte IS
the colour and no CGRAM word is consulted for it at all. BG2 is everything
that must stay exactly put — the hills, the cliff, the stars and the writing —
4bpp, in one sixteen-entry palette. The figures are OBJ.

That split is forced by the hardware, not chosen. Direct colour acts on an
8bpp layer and nothing else (`GetRgbColor`, Mesen2 SnesPpu.cpp:1071, guarded
by `if constexpr(bpp == 8 && directColorMode)`), so the layer that wants it
must be the 8bpp one; and mode 3 is the ONLY mode that pairs an 8bpp BG1 with
a 4bpp BG2. Mode 4's BG2 is 2bpp — four colours to hold two ridges, a cliff,
two star levels and a nine-step anti-aliased ink ramp, which it cannot — and
mode 7 has no second layer at all.

=============================================================================
THE LATTICE, AND WHY THE DITHER IS NOT OPTIONAL
=============================================================================
A direct-colour pixel carries r3 g3 b2 and the tilemap entry's 3-bit palette
field supplies one more bit of each channel (SnesPpu.cpp:1071-1076):

    R5 = 4*(c & 7)        + 2*(p & 1)
    G5 = 4*((c >> 3) & 7) + 2*((p >> 1) & 1)
    B5 = 8*((c >> 6) & 3) + 4*((p >> 2) & 1)

So 2048 colours are reachable overall — but the field is per TILE, so inside
any one 8x8 block the reachable set is 8 x 8 x 4 and its steps are 4/31,
4/31 and 8/31. A night sky is a long shallow vertical gradient; drawn against
steps that coarse it bands into visible stripes. An ordered dither is what
turns those steps back into a gradient, and it is why this file carries a
Bayer matrix at all.

THE DITHER IS ALSO WHY THE AURORA DOES NOT MOVE. Sliding scanlines across an
8x8 ordered dither by different amounts destroys its vertical coherence and
the gradient stops reading as texture and starts reading as static. The
animation is therefore entirely in the palette FIELD — see `roll_table`.
"""
import math
import random
import sys
from pathlib import Path

W, H = 256, 224
TW, TH = W // 8, H // 8
HORIZON, CLIFF = 152, 188


# --------------------------------------------------------------- the lattice
def rgb5(c, p):
    """The BGR555 a direct-colour pixel byte and palette field make."""
    return ((((c & 7) << 2) | ((p & 1) << 1)),
            ((((c >> 3) & 7) << 2) | (p & 2)),
            ((((c >> 6) & 3) << 3) | ((p & 4) << 0)))


def to5(v):
    return max(0.0, min(31.0, v * 31.0))


# ------------------------------------------------------------- the scene
def smooth(t):
    return t * t * (3 - 2 * t)


def clamp01(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def sky(y):
    t = smooth(clamp01(y / HORIZON))
    glow = math.exp(-((y - HORIZON) / 26.0) ** 2)
    return (0.004 + 0.115 * t ** 2.4 + 0.045 * glow,
            0.008 + 0.140 * t ** 2.4 + 0.040 * glow,
            0.050 + 0.155 * t ** 1.5 + 0.022 * glow)


# Three curtains, SEPARATED and NARROW. Merged at a wider sigma they read as
# one rectangular slab of light; the dark sky between them is what makes them
# curtains, and the taper is what keeps each one whole inside the screen.
#            cx   amp  freq   wob   top  bot  gain  sigma
CURTAINS = ((74,  13, 0.021, 1.00,  22, 128, 1.00, 19.0),
            (139, 16, 0.015, 0.62,  14, 116, 0.92, 22.0),
            (198,  9, 0.029, 1.40,  34,  98, 0.60, 15.0))
EDGE = 34.0


def aurora(x, y):
    out = 0.0
    for cx, amp, freq, wob, top, bot, gain, sig in CURTAINS:
        drift = amp * math.sin(freq * x) + 0.5 * amp * math.sin(2.3 * freq * x)
        body = math.exp(-(abs(x - (cx + drift)) / sig) ** 2)
        v = (y - top) / float(bot - top)
        if v < -0.25 or v > 1.25:
            continue
        env = smooth(clamp01((v + 0.10) / 0.34)) * smooth(clamp01((1.10 - v) / 0.46))
        ray = 0.70 + 0.30 * math.sin(0.9 * x + 2.4 * v)
        out = max(out, gain * body * env * (1.0 - 0.55 * v) * ray)
    return out * smooth(clamp01(x / EDGE)) * smooth(clamp01((W - 1 - x) / EDGE))


def tint(a):
    return (0.26 * a + 0.62 * a ** 3, 0.92 * a - 0.12 * a ** 3,
            0.34 * a + 0.52 * a ** 4)


def bg1_px(x, y):
    r, g, b = sky(y)
    a = aurora(x, y)
    if a > 0:
        ar, ag, ab = tint(a)
        r += ar
        g += ag
        b += ab
    return r, g, b


def ridge(x, n):
    if n == 1:
        return HORIZON - 17 - 10 * math.sin(0.0125 * x) - 4 * math.sin(0.041 * x + 1.2)
    return HORIZON - 5 - 6 * math.sin(0.019 * x + 2.5) - 3 * math.sin(0.05 * x)


def star_field(seed=7):
    rnd = random.Random(seed)
    return [(rnd.randrange(6, W - 6), rnd.randrange(3, HORIZON - 34),
             rnd.choice((0, 0, 1, 1))) for _ in range(96)]


# --------------------------------------------------- BG1: fit and cut, 8bpp
# Per-channel dither PHASES. One shared Bayer grid puts all three channels'
# thresholds at the same pixels, so every channel steps together and the
# result reads as a visible screen door rather than as a gradient. Offsetting
# the grid per channel breaks that lock-step and the texture disappears.
BAYER8 = [[(lambda a, b: ((a & 4) >> 2) | ((b & 4) >> 1) | ((a & 2) << 1)
           | ((b & 2) << 2) | ((a & 1) << 4) | ((b & 1) << 5))(i ^ j, j)
           for i in range(8)] for j in range(8)]
DPHASE = ((0, 0), (3, 5), (6, 2))          # (row, col) offset per channel


def fit_tile(px):
    """Choose the palette FIELD that fits this 8x8 block, then dither into it.

    The field is per tile, so it is chosen per tile: for each of the eight
    fields the block is dithered onto that field's lattice and the squared
    error is summed. Cheap (eight passes over 64 pixels) and it is the only
    place the field can be decided, because the field is what the tile's
    reachable colours ARE.
    """
    best = None
    for f in range(8):
        base = [(((f & 1) << 1), (f & 2), ((f & 4))) for _ in (0,)][0]
        err, out = 0.0, []
        for j in range(8):
            for i in range(8):
                r5, g5, b5 = px[j * 8 + i]
                byte, e = 0, 0.0
                for ch, (val, lo, step, bits, shift) in enumerate((
                        (r5, base[0], 4.0, 7, 0),
                        (g5, base[1], 4.0, 7, 3),
                        (b5, base[2], 8.0, 3, 6))):
                    dj, di = DPHASE[ch]
                    thr = (BAYER8[(j + dj) & 7][(i + di) & 7] + 0.5) / 64.0
                    q = (val - lo) / step
                    n = int(max(0, min(bits, math.floor(q + thr))))
                    byte |= n << shift
                    e += (lo + n * step - val) ** 2
                out.append(byte)
                err += e
        if best is None or err < best[0]:
            best = (err, f, out)
    return best[1], best[2]


def cut_bg1():
    src = [[tuple(to5(v) for v in bg1_px(x, y)) for x in range(W)]
           for y in range(H)]
    tiles, ix, words = [], {}, []
    for ty in range(TH):
        for tx in range(TW):
            block = [src[ty * 8 + j][tx * 8 + i] for j in range(8) for i in range(8)]
            f, by = fit_tile(block)
            key = (f, tuple(by))
            if key not in ix:
                ix[key] = len(tiles)
                tiles.append(by)
            words.append(ix[key] | (f << 10))
    return tiles, words


def chr8(tiles):
    """8bpp planar: bitplanes 0/1 interleaved by row, then 2/3, then 4/5, 6/7."""
    out = bytearray()
    for t in tiles:
        for pair in range(4):
            for j in range(8):
                lo = hi = 0
                for i in range(8):
                    v = t[j * 8 + i] >> (pair * 2)
                    lo |= (v & 1) << (7 - i)
                    hi |= ((v >> 1) & 1) << (7 - i)
                out += bytes((lo, hi))
    return bytes(out)


def map_bytes(words, rows=32, cols=32):
    out = bytearray()
    for r in range(rows):
        for c in range(cols):
            w = words[r * TW + c] if (r < TH and c < TW) else 0
            out += bytes((w & 0xFF, w >> 8))
    return bytes(out)



# ------------------------------------------------------- BG2: 4bpp, one palette
# The layer that must hold ABSOLUTELY STILL: two ridges, the cliff, the stars
# and the writing. Sixteen entries and they are exactly used.
IX_CLEAR, IX_FAR, IX_NEAR, IX_CLIFF, IX_RIM = 0, 1, 2, 3, 4
IX_STAR = (5, 6)
IX_INK0, INK_STEPS = 7, 9                 # 7..15

# EVERY BG2 MAP WORD CARRIES THE PRIORITY BIT, and it has to. The SNES layer
# order for mode 3, front to back, is
#
#     OBJ.3 · BG1.1 · OBJ.2 · BG2.1 · OBJ.1 · BG1.0 · OBJ.0 · BG2.0
#
# so at equal tilemap priority BG1 renders IN FRONT OF BG2 — and BG1 here is a
# full-screen direct-colour sky with almost no transparent pixels, so a BG2
# left at priority 0 is completely hidden. The ROM's first boot showed exactly
# that: correct CHR, correct maps, correct registers, and no hills, no cliff
# and no writing on screen. Raising BG2 to priority 1 puts it above BG1.0,
# which is the only level BG1 uses.
BG2_PRIO = 1 << 13


def bgr555(r, g, b):
    return (b << 10) | (g << 5) | r


# The ink ramp runs from the sky's own darkness up to a warm parchment, so the
# pen's anti-aliased edge dissolves into the night instead of fringing grey.
# The land is nearly black and MUST be: it is a silhouette against a lit sky,
# and every step of BGR555 it is lifted is a step it stops reading as one.
# These are the prototype's own tones carried across — the sky behind the
# ridge measures about (38,44,56) of 255, the far ridge takes 0.30 of it and
# the near ridge 0.15, which is (2,2,3) and (1,1,2) in five bits.
PAL_BG2 = [bgr555(0, 0, 0), bgr555(2, 2, 4), bgr555(1, 1, 2),
           bgr555(0, 0, 1), bgr555(2, 3, 5), bgr555(13, 14, 16),
           bgr555(25, 26, 28)] + [
    bgr555(int(3 + (30 - 3) * (k / (INK_STEPS - 1.0)) ** 0.85),
           int(3 + (29 - 3) * (k / (INK_STEPS - 1.0)) ** 0.90),
           int(4 + (24 - 4) * (k / (INK_STEPS - 1.0)) ** 1.05))
    for k in range(INK_STEPS)]
assert len(PAL_BG2) == 16, len(PAL_BG2)


def ink_index(c):
    """Coverage -> ink ramp entry, or 0 for no ink."""
    return 0 if c <= 0.06 else IX_INK0 + min(INK_STEPS - 1, int(c * (INK_STEPS - 0.01)))


def bg2_static(x, y):
    if y >= CLIFF:
        return IX_CLIFF
    if y >= CLIFF - 2:
        return IX_RIM
    if y >= ridge(x, 2):
        return IX_NEAR
    if y >= ridge(x, 1):
        return IX_FAR
    return IX_CLEAR


def chr4(tiles):
    """4bpp planar: planes 0/1 interleaved by row, then planes 2/3."""
    out = bytearray()
    for t in tiles:
        for pair in range(2):
            for j in range(8):
                lo = hi = 0
                for i in range(8):
                    v = t[j * 8 + i] >> (pair * 2)
                    lo |= (v & 1) << (7 - i)
                    hi |= ((v >> 1) & 1) << (7 - i)
                out += bytes((lo, hi))
    return bytes(out)


def cut_bg2(cov):
    """Static tiles first, then ONE RESERVED TILE PER INKED CELL.

    The writing's tiles are emitted BLANK and filled in at run time by the
    delta stream, so the ROM holds the finished word exactly once — in the
    stream — rather than twice. A cell the pen touches cannot share a tile
    with any other cell, because each fills at its own moment.
    """
    stars = star_field()
    star_at = {(x, y): IX_STAR[m] for x, y, m in stars}
    px = [[bg2_static(x, y) for x in range(W)] for y in range(H)]
    for (x, y), v in star_at.items():
        if px[y][x] == IX_CLEAR:
            px[y][x] = v
    tiles, ix, words = [], {}, [0] * (TW * TH)
    ink_cells = sorted({(x // 8, y // 8) for y in range(H) for x in range(W)
                        if cov[y][x] > 0.06})
    inked = set(ink_cells)
    for ty in range(TH):
        for tx in range(TW):
            if (tx, ty) in inked:
                continue
            block = tuple(px[ty * 8 + j][tx * 8 + i] for j in range(8) for i in range(8))
            if block not in ix:
                ix[block] = len(tiles)
                tiles.append(list(block))
            words[ty * TW + tx] = ix[block] | BG2_PRIO
    # AN INK TILE IS NOT BLANK, IT IS THE GROUND UNDER THE WORD. Emitted
    # empty it is TRANSPARENT, and BG2 transparent means BG1 shows through —
    # so the black band under the cliff would carry the sky's own gradient in
    # exactly the rectangles the writing is going to occupy, which is what the
    # first cut of this looked like: pale blocks tracking the pen.
    ink_base = len(tiles)
    for n, (tx, ty) in enumerate(ink_cells):
        tiles.append([px[ty * 8 + j][tx * 8 + i]
                      for j in range(8) for i in range(8)])
        words[ty * TW + tx] = (ink_base + n) | BG2_PRIO
    return tiles, words, ink_base, ink_cells


# ------------------------------------------------- the writing's delta stream
def write_stream(cov, tim, ink_base, ink_cells, frames):
    """Per frame: [count][ (tile u16, 32 B) x count ].

    The pen crosses tiles DIAGONALLY, so at any moment a tile is partly inked
    — revealing by tilemap swap would climb the word in eight-pixel stairs,
    and generating CHR on the 65816 per frame is out of the question. So the
    changed tiles are computed here and DMA'd in VBlank, which is a handful of
    32-byte transfers a frame.
    """
    slot = {c: n for n, c in enumerate(ink_cells)}
    # ...and the stream's own starting state is that same ground, not zero.
    state = {c: [bg2_static(c[0] * 8 + i, c[1] * 8 + j)
                 for j in range(8) for i in range(8)] for c in ink_cells}
    out, peak, total = bytearray(), 0, 0
    for f in range(frames):
        tau = (f + 1) / float(frames)
        dirty = {}
        for (tx, ty) in ink_cells:
            blk = state[(tx, ty)]
            hit = False
            for j in range(8):
                for i in range(8):
                    x, y = tx * 8 + i, ty * 8 + j
                    c = cov[y][x]
                    v = (ink_index(c) if (c > 0.06 and tim[y][x] is not None
                                          and tim[y][x] <= tau)
                         else bg2_static(x, y))
                    if blk[j * 8 + i] != v:
                        blk[j * 8 + i] = v
                        hit = True
            if hit:
                dirty[(tx, ty)] = list(blk)
        out += bytes((len(dirty),))
        peak = max(peak, len(dirty))
        total += len(dirty)
        for c, blk in dirty.items():
            t = ink_base + slot[c]
            out += bytes((t & 0xFF, t >> 8)) + chr4([blk])
    return bytes(out), peak, total


# ----------------------------------------------------------------- the roll
ROLL_PHASES = 32                  # 32 pages x 832 B = 26,624 B, which is ONE
                                  # LoROM bank window. 64 phases would be
                                  # 53,248 and a DMA source cannot span a bank
                                  # (A1B is constant) — the allocator refuses
                                  # it by name, and bank_tiled is not the way
                                  # out here because it chunks at the WINDOW
                                  # size and 32,768 is not a multiple of the
                                  # 832-byte page, so a transfer would
                                  # straddle the split.


def roll_mask(k, core):
    """The palette-field mask for phase step k. THIS IS THE WHOLE ANIMATION.

    The mask is OR-ed onto the tile's fitted field, and that it is an OR and
    not an XOR is the difference between a wave and a rash. Each tile is
    fitted to the field that suits its own pixels, so adjacent tiles commonly
    sit on DIFFERENT fields; XOR the same bit into both and they SWAP — one
    goes up a lattice step while its neighbour goes down — and the curtain
    breaks into red and blue eight-pixel blocks. That is what the first cut of
    this did. An OR is monotone: a tile either holds still or brightens by one
    step, never against its neighbour.

    The steps are 2 of 31 in red and green. THE BLUE BIT IS NOT LIKE THE
    OTHER TWO: a direct-colour pixel gives blue only two bits, so the field
    bit is worth 4 of 31 there — twice as loud — which is why it is gated to
    the curtain CORES, where the step lands on light already bright enough to
    carry it.
    """
    w = math.sin(2 * math.pi * k / ROLL_PHASES)
    m = 0
    if w > 0.10:
        m |= 2                            # green: the body of the fold
    if w > 0.62:
        m |= 1                            # red too: the crest goes pale
    if w < -0.50 and core:
        m |= 4                            # blue: the trough runs cold
    return m


def roll_pages(words):
    """-> (blob, row0, rows). ALL 64 PHASES of the curtain rows, precomputed.

    The rolling colour is a per-tile field change, and there are two ways to
    put one on the hardware: walk the 143 curtain records each frame and OR a
    phase mask into a WRAM shadow, or precompute every phase and let VBlank
    DMA the one it wants. This is the second, and the trade is stated rather
    than assumed: 64 pages of the thirteen map rows the curtains reach is
    53,248 B of ROM against ~2,000 cycles a frame and 832 B of WRAM. On a
    rail whose CPU has nothing else to do that is the wrong way round — but
    the ROM is 512 KB, the scene is one picture, and what the technique
    demonstrates is unchanged either way: the field IS the colour control.
    What moves is only whether the words are computed or fetched.

    The mask is OR-ed onto each tile's fitted field. See `roll_mask`.
    """
    curtain = {}
    rows = []
    for ty in range(TH):
        for tx in range(TW):
            lit = max(aurora(tx * 8 + i, ty * 8 + j)
                      for j in (0, 4, 7) for i in (0, 4, 7))
            if lit <= 0.22:
                continue
            key = int(round((0.62 * ty - 0.34 * tx) / (2 * math.pi) * ROLL_PHASES)) & 63
            curtain[(tx, ty)] = (key, lit > 0.52)
            rows.append(ty)
    row0, row1 = min(rows), max(rows)
    blob = bytearray()
    for ph in range(ROLL_PHASES):
        for ty in range(row0, row1 + 1):
            for tx in range(32):
                w = words[ty * TW + tx] if tx < TW else 0
                if (tx, ty) in curtain:
                    key, core = curtain[(tx, ty)]
                    m = roll_mask((key + ph) & (ROLL_PHASES - 1), core)
                    w = (w & 0x3FF) | ((((w >> 10) & 7) | m) << 10)
                blob += bytes((w & 0xFF, w >> 8))
    return bytes(blob), row0, row1 - row0 + 1, len(curtain)


# ------------------------------------------------------------- OBJ: the three
# 16x32 sprites (OBSEL size pair 6), so each is 2x4 tiles read as
# N, N+1, N+16, N+17, N+32, N+33, N+48, N+49 — the PPU's 16-wide OBJ grid.
FIGURES = ((106, 28, 5), (126, 31, 6), (148, 26, 5))
OBJ_H, OBJ_W = 32, 16
# The figures are darker than the cliff they stand on, with a cold rim down
# the edge the curtains light. They get their OWN sixteen at CGRAM 128+ —
# sprites read `128 + (palette << 4) + colour` (SnesPpu.cpp:960) — so nothing
# here is taken from BG2's, which is exactly full.
PAL_OBJ = [bgr555(0, 0, 0), bgr555(0, 0, 1), bgr555(3, 5, 6),
           bgr555(7, 10, 11), bgr555(11, 14, 15)] + [0] * 11


def figure_px(n):
    """One figure, feet on the cliff, lit down its left edge by the curtains."""
    fx, h, w = FIGURES[n]
    out = [[0] * OBJ_W for _ in range(OBJ_H)]
    for row in range(OBJ_H):
        y = CLIFF + 1 - (OBJ_H - 1 - row)          # bottom row sits on the edge
        t = (CLIFF + 1 - y) / float(h)
        if not (0.0 <= t <= 1.0):
            continue
        head = 0.17
        if t > 1 - head:
            hy = (t - (1 - head)) / head
            half = w * 0.46 * math.sqrt(max(0.0, 1 - (2 * hy - 1) ** 2))
        else:
            half = w * (0.74 + 0.46 * (1 - t) ** 1.6)
        for col in range(OBJ_W):
            dx = (col - OBJ_W // 2) + 0.5
            if abs(dx) > half:
                continue
            edge = (half - abs(dx))
            if dx < 0 and edge < 1.15:
                out[row][col] = 3 if t > 0.55 else 2
            elif dx < 0 and edge < 2.1 and t > 0.72:
                out[row][col] = 2
            else:
                out[row][col] = 1
    return out


def obj_sheet():
    """Lay the three into the PPU's 16-tile-wide OBJ grid, 4 rows of it."""
    grid = [[0] * 64 for _ in range(64)]           # 64 tiles = 4 rows x 16
    for n in range(len(FIGURES)):
        px = figure_px(n)
        for j in range(4):
            for i in range(2):
                t = j * 16 + n * 2 + i
                grid[t] = [px[j * 8 + b][i * 8 + a] for b in range(8) for a in range(8)]
    return chr4(grid)


def pal_bytes(pal):
    out = bytearray()
    for w in pal:
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


# =============================================================================
# THE PAGES ARE THE RESOURCE; HOW MUCH OF ONE THE ART USES IS A NUMBER
# =============================================================================
# Every blob is padded to its claimed size so the rom claim, the packer's
# order and the `.assert`s in main.asm are all one number. The generator
# prints what the art actually occupies — that is the figure to watch, and it
# is not the same figure as the claim.
CHR1_TILES = 320                  # x 64 B, EIGHT bpp
CHR2_TILES = 224                  # x 32 B
OBJ_TILES = 64                    # four rows of the PPU's 16-wide OBJ grid
WRITE_BYTES = 6144
ROLL_PAGE = 13 * 32 * 2           # the curtain rows, as one VRAM transfer
ROLL_BYTES = ROLL_PHASES * ROLL_PAGE


def pad(blob, n, what):
    if len(blob) > n:
        raise SystemExit("%s needs %d B, claim is %d" % (what, len(blob), n))
    return blob + bytes(n - len(blob))


if __name__ == "__main__":
    import write_on
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
    out.mkdir(parents=True, exist_ok=True)

    tiles1, words1 = cut_bg1()
    cov, tim = write_on.ink(W, H)
    tiles2, words2, ink_base, ink_cells = cut_bg2(cov)
    stream, peak, total = write_stream(cov, tim, ink_base, ink_cells,
                                       write_on.FRAMES)
    recs, row0, rrows, nrec = roll_pages(words1)

    (out / "aur_chr1.bin").write_bytes(pad(chr8(tiles1), CHR1_TILES * 64, "chr1"))
    (out / "aur_map1.bin").write_bytes(map_bytes(words1))
    (out / "aur_chr2.bin").write_bytes(pad(chr4(tiles2), CHR2_TILES * 32, "chr2"))
    (out / "aur_map2.bin").write_bytes(map_bytes(words2))
    (out / "aur_pal.bin").write_bytes(pal_bytes(PAL_BG2) + pal_bytes(PAL_OBJ))
    (out / "aur_obj.bin").write_bytes(pad(obj_sheet(), OBJ_TILES * 32, "obj"))
    (out / "aur_write.bin").write_bytes(pad(stream, WRITE_BYTES, "write"))
    (out / "aur_roll.bin").write_bytes(pad(recs, ROLL_BYTES, "roll"))

    inc = """; aur_art.inc — GENERATED by tools/gen_aurora_assets.py. Do not edit.
; The credits scene's geometry, so the ASM and the tests read ONE copy of it.
AUR_SCREEN_W    = %d
AUR_SCREEN_H    = %d
AUR_COLS        = %d
AUR_ROWS        = %d
AUR_CLIFF       = %d      ; the cliff's top scanline

; --- the writing --------------------------------------------------------
AUR_INK_BASE    = %d      ; the first BG2 tile the pen owns...
AUR_INK_TILES   = %d       ; ...and how many. Emitted holding the GROUND under
                          ;   the word, not blank: an empty BG2 tile is
                          ;   TRANSPARENT and BG1's sky would show through the
                          ;   black band in exactly the rectangles the pen is
                          ;   about to fill
AUR_WRITE_FRAMES = %d      ; the pen's span
AUR_WRITE_PEAK  = %d       ; ...and the most tiles it dirties in any one of
                          ;   them, which is the VBlank cost to size for
AUR_INK_BYTES   = %d      ; AUR_INK_TILES x 32 — the slice of chr2 a REPLAY
                          ;   re-uploads to blank the word again
AUR_INK_OFF     = %d      ; ...at this offset into the chr2 blob

; --- the roll -----------------------------------------------------------
AUR_ROLL_TILES  = %d       ; curtain tiles, which is what the roll moves
AUR_ROLL_ROW0   = %d        ; the first map row a curtain reaches...
AUR_ROLL_ROWS   = %d       ; ...and how many. The page is that row range, so
                          ;   a phase is ONE VBlank transfer and no CPU work
AUR_ROLL_PAGE   = %d      ; AUR_ROLL_ROWS x 32 words x 2
AUR_ROLL_PHASES = %d      ; ...and there are this many pages, one per phase

; --- the figures --------------------------------------------------------
AUR_FIGS        = %d
AUR_FIG_TOP     = %d      ; every figure's OAM Y — a 16x32 sprite whose bottom
                          ;   row sits on the cliff edge
""" % (W, H, TW, TH, CLIFF,
       ink_base, len(ink_cells), write_on.FRAMES, peak,
       len(ink_cells) * 32, ink_base * 32,
       nrec, row0, rrows, ROLL_PAGE, ROLL_PHASES,
       len(FIGURES), CLIFF + 2 - OBJ_H)
    for n, (fx, h, w) in enumerate(FIGURES):
        inc += "AUR_FIG%d_X       = %d\n" % (n, fx - OBJ_W // 2)
    (out / "aur_art.inc").write_text(inc)

    print("BG1 %d/%d 8bpp tiles (%d B page)   BG2 %d/%d 4bpp tiles, %d of them ink"
          % (len(tiles1), CHR1_TILES, CHR1_TILES * 64, len(tiles2), CHR2_TILES,
             len(ink_cells)))
    print("write %d/%d B, %d uploads over %d frames, peak %d a frame"
          % (len(stream), WRITE_BYTES, total, write_on.FRAMES, peak))
    print("roll %d curtain tiles, map rows %d..%d, %d phases x %d B = %d/%d B"
          % (nrec, row0, row0 + rrows - 1, ROLL_PHASES, ROLL_PAGE,
             len(recs), ROLL_BYTES))
