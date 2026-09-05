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
HORIZON = 152

# THE CLIFF LINE IS WHERE IT IS BECAUSE OF THE WRITING, not the landscape.
# The figures are 16x32 sprites standing with their feet on this line, so they
# reach up from it; the word's tall loops reach DOWN to about ten pixels above
# its baseline's ascender. At 188 those two overlapped by three pixels and OBJ
# priority 3 won, which sliced the tops off the T's oval and both loops — with
# the CHR, the tilemap and the stream all provably correct. Measured at
# (107,189): the pen has full coverage and the screen shows the figures' body
# colour. Ten pixels of daylight is the fix, and it is a layout number rather
# than a drawing one.
CLIFF = 178


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
    # THE HORIZON GLOW IS COOL, AND HAS TO BE. It is part of the SKY, so it
    # is phase-independent — it does not cycle with the aurora — and a warm
    # glow (which is what this was) reads as a green band left behind above
    # the hills once the curtains have gone blue. Weighted blue-over-green it
    # sits under every hue the cycle visits.
    return (0.004 + 0.115 * t ** 2.4 + 0.020 * glow,
            0.008 + 0.140 * t ** 2.4 + 0.030 * glow,
            0.050 + 0.155 * t ** 1.5 + 0.048 * glow)


# Three curtains, SEPARATED and NARROW. Merged at a wider sigma they read as
# one rectangular slab of light; the dark sky between them is what makes them
# curtains, and the taper is what keeps each one whole inside the screen.
#            cx   amp  freq   wob   top  bot  gain  sigma
CURTAINS = ((74,  13, 0.021, 1.00,  22, 128, 1.00, 19.0),
            (139, 16, 0.015, 0.62,  14, 116, 0.92, 22.0),
            (198,  9, 0.029, 1.40,  34,  98, 0.60, 15.0))
EDGE = 34.0


def aurora_at(x, y, ph=0):
    """-> (intensity, depth down the curtain 0..1, which curtain).

    The depth and the index are what the hue needs: the fringe colour is a
    function of HEIGHT within a curtain, and each curtain lags the cycle by
    its own amount. The brightest curtain at this pixel wins all three.

    The PHASE reaches the shape as well as the colour — each curtain breathes
    a little wider and narrower and its rays drift sideways — so the outer
    columns go black and come back as the cycle turns.
    """
    t = 2 * math.pi * ph / HUE_PHASES
    best = (0.0, 0.0, 0)
    for ci, (cx, amp, freq, wob, top, bot, gain, sig) in enumerate(CURTAINS):
        sig = sig * (1.0 + HUE_WIDTH * math.sin(t + ci * 2.1))
        drift = amp * math.sin(freq * x) + 0.5 * amp * math.sin(2.3 * freq * x)
        body = math.exp(-(abs(x - (cx + drift)) / sig) ** 2)
        v = (y - top) / float(bot - top)
        if v < -0.25 or v > 1.25:
            continue
        env = smooth(clamp01((v + 0.10) / 0.34)) * smooth(clamp01((1.10 - v) / 0.46))
        ray = 0.70 + 0.30 * math.sin(0.9 * x + 2.4 * v
                                     + HUE_RAY * t + ci * 1.7)
        val = gain * body * env * (1.0 - 0.55 * v) * ray
        if val > best[0]:
            best = (val, clamp01(v), ci)
    edge = smooth(clamp01(x / EDGE)) * smooth(clamp01((W - 1 - x) / EDGE))
    return best[0] * edge, best[1], best[2]


def aurora(x, y):
    """The cycle's WIDEST reach at this pixel.

    The tinted set has to be the UNION over phases, not one phase's: a tile
    the curtain only covers when it is wide still has to be in the set, or it
    would hold whatever it was painted with at phase 0 and never go black
    again — which is the same fringe bug as the threshold one, arriving
    through the shape instead of through the colour.
    """
    return max(aurora_at(x, y, ph)[0] for ph in range(HUE_PHASES))


# =============================================================================
# THE HUE CYCLE — and why it is CHR and not a palette
# =============================================================================
# A colour cycle is the classic INDEXED trick: rewrite one CGRAM word and every
# pixel using it changes at once, for two bytes. Direct colour is precisely the
# mode that gives that up — the pixel IS the colour, so there is no palette to
# cycle and the colour lives in the CHR. Animating it is therefore CHR traffic,
# and the cost is the demonstration: HUE_PHASES copies of every tile the aurora
# tints, a quarter of a megabyte of ROM, against two bytes for the same effect
# on an indexed layer.
#
# The field cannot do it. It supplies one LOW BIT per channel — 2 of 31 in red
# and green, 4 in blue — which cannot take a green curtain to violet; and being
# per TILE, anything driven by it is an 8x8 block, which is what the first cut
# of this rail looked like.
HUE_PHASES = 16
HUE_LO, HUE_HI = 168.0, 252.0     # cyan-teal .. violet: no green, no magenta
HUE_THR = 0.02                    # below this the aurora is not drawn AT ALL
                                  # (see bg1_px) — a pixel too faint to be in
                                  # the cycling set must not be tinted either,
                                  # or it keeps phase 0's hue for the whole
                                  # cycle and leaves a teal fringe standing
                                  # around a violet curtain
# THE RATE IS A CURVE, NOT A SLICE COUNT. A phase is 300 tile-updates however
# they are paced, so a slow cycle means a low AVERAGE rate and the shape is
# only free to redistribute it. This is a raised sine to the fourth power over
# RATE_LEN frames, summing to exactly one phase: the aurora drifts at a tile
# or two a frame for most of the pass and then moves at six, which is what
# "variable rate" has to mean when the budget is fixed.
#
# It is safe to leave the picture PERMANENTLY straddling two phases, which is
# what a continuous sweep does — measured on the real quantised art, a 50/50
# scattered mix of two adjacent phases is indistinguishable from either. That
# is what makes a smooth curve preferable to the burst-and-hold it replaces;
# at a coarser phase step it would not be.
RATE_LEN = 192
RATE_POW = 4
RATE_FLOOR = 0.45                 # tiles a frame at the curve's TROUGH. Not
                                  # zero: a raised sine alone is flat on the
                                  # floor for a third of its period, and a
                                  # third of the cycle standing perfectly
                                  # still is not a continuous transition. At
                                  # 0.45 the error diffusion emits a tile
                                  # every other frame down there, so the
                                  # picture is always moving and only the RATE
                                  # of it breathes

# TWO THINGS A REAL AURORA DOES THAT A UNIFORM HUE ROTATION DOES NOT.
#
# It is not one colour at a time. The N2+ emission at the LOWER border runs
# violet and pink where the body of the curtain is green — that magenta fringe
# under a green sheet is the single most recognisable thing in an aurora
# photograph, and it is a function of HEIGHT, not of time.
HUE_FRINGE = 38.0                 # degrees, added over the bottom of a curtain
HUE_FRINGE_FROM = 0.55            # ...starting this far down it

# And the curtains do not change together. Each one lags the cycle by its own
# amount, so at any moment the three are wearing three different colours —
# which is what stops the picture reading as one object being recoloured.
HUE_LAG = (0, 5, 11)

# THE SHAPE MOVES TOO, and it costs nothing: the sixteen phases already exist,
# so painting each one with the curtains slightly narrower or wider — and with
# the ray striations drifting sideways — makes the outer columns go BLACK and
# come back as the cycle turns. That reads as the curtain breathing, which is
# a stronger cue for motion than the colour is, and the layer still never
# scrolls.
#
# Both are kept SMALL because the picture permanently straddles two adjacent
# phases: a tenth of the width and a sixteenth of a ray period per step are
# under what the mix can show.
HUE_WIDTH = 0.10                  # of sigma, peak to peak
HUE_RAY = 1.0                     # ray periods drifted over a whole cycle


def hue_deg(ph):
    """The cycle's base hue at phase `ph`, in degrees.

    A there-and-back sweep rather than a full hue loop: a full loop passes
    through yellow and red, which an aurora does not do and the picture does
    not want. LINEAR rather than eased, so every step is the same size — the
    dwell belongs in how long a phase is HELD, which is a tuning constant the
    rail owns, not in the size of the colour steps. An eased path puts 22
    degrees between two phases in the middle of its sweep and 2 at the ends,
    and the big ones read as jumps however long the hold is.
    """
    t = (ph % HUE_PHASES) / float(HUE_PHASES)
    tri = 2 * t if t < 0.5 else 2 - 2 * t
    return HUE_LO + (HUE_HI - HUE_LO) * tri


def hue_weights(deg):
    h = (deg % 360) / 60.0
    c, x = 1.0, 1 - abs(h % 2 - 1)
    return [(c, x, 0), (x, c, 0), (0, c, x),
            (0, x, c), (x, 0, c), (c, 0, x)][int(h) % 6]


def tint(a, deg):
    wr, wg, wb = hue_weights(deg)
    return (wr * 0.95 * a + 0.26 * a ** 3,
            wg * 0.95 * a + 0.10 * a ** 3,
            wb * 0.95 * a + 0.30 * a ** 4)


def bg1_px(x, y, ph=0):
    r, g, b = sky(y)
    a, v, ci = aurora_at(x, y, ph)
    # NOT `a > 0`. A pixel the cycling set does not cover must not be tinted at
    # all, or it wears phase 0's colour for the whole cycle — which is a teal
    # fringe standing still around a violet curtain. At this threshold the
    # cut-off is under one lattice step, so it costs nothing visible.
    if a > HUE_THR:
        deg = (hue_deg(ph + HUE_LAG[ci])
               + HUE_FRINGE * smooth(clamp01((v - HUE_FRINGE_FROM)
                                             / (1.0 - HUE_FRINGE_FROM))))
        ar, ag, ab = tint(a, deg)
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


def fit_tile(px, force=None):
    """Choose the palette FIELD that fits this 8x8 block, then dither into it.

    The field is per tile, so it is chosen per tile: for each of the eight
    fields the block is dithered onto that field's lattice and the squared
    error is summed. `force` pins the field instead — which every TINTED tile
    needs, because its bytes are replaced twelve times over the hue cycle
    while its map word (and so its field) is uploaded once and never touched.
    """
    best = None
    for f in (range(8) if force is None else (force,)):
        base = ((f & 1) << 1, f & 2, f & 4)
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
    return best[1], best[2], best[0]


def _block(ph, tx, ty):
    return [tuple(to5(v) for v in bg1_px(tx * 8 + i, ty * 8 + j, ph))
            for j in range(8) for i in range(8)]


def _tinted():
    """The cells the aurora reaches, padded to a whole number of slices.

    EVERY tile it tints, not just the bright cores: a cell left out keeps its
    phase-0 colour for the whole cycle, so a faint teal fringe would sit
    around a violet curtain and never move.
    """
    lit = {}
    for ty in range(TH):
        for tx in range(TW):
            v = max(aurora(tx * 8 + i, ty * 8 + j)
                    for j in range(8) for i in range(8))
            if v > 0:
                lit[(tx, ty)] = v
    keep = sorted((c for c, v in lit.items() if v > HUE_THR))
    rest = sorted((c for c in lit if c not in set(keep)),
                  key=lambda c: -lit[c])
    while len(keep) % 4:                 # a round number of tiles per phase
        keep.append(rest.pop(0))
    return sorted(keep)


def cut_bg1():
    """-> (tiles, words, hue_base, hue_cells, hue_fields).

    Two populations, and they are laid out differently on purpose.

    The SKY tiles dedupe, as any tilemap art does. The TINTED tiles do not:
    each is rewritten sixteen times over the cycle, so two cells that happen
    to match at one phase must still own separate VRAM slots or updating one
    would update the other. They are also given a CONTIGUOUS run of tile
    indices, so a slice of the cycle is ONE DMA with one VMADD.

    THE RUN IS ORDERED SCATTERED ON SCREEN, and the reason is what the eye
    does with a picture that is permanently mid-transition. A frame is always
    a mix of two adjacent phases, so the only question is HOW that mix is
    distributed. Scattered, it dissolves: the tiles carrying the new hue are
    spread over the whole sky, no two adjacent, and at five degrees of hue
    apart the difference is under the dither's own noise — the curtains simply
    drift in colour with nothing to see moving.

    A SCREEN-COHERENT ORDER WAS TRIED AND REJECTED BY THE OWNER, and the
    record matters because the measurement that motivated it was correct and
    the conclusion drawn from it was not. Ordered bottom-up the phase boundary
    is a horizontal line that climbs, and measured on six frames across a
    phase that line does not show as a colour STEP — the largest mean-colour
    step between adjacent tile rows sits at the hills' edge and does not move
    with the cursor. That much is true. What it misses is that a coherent
    front is legible as MOTION even when it is not legible as a seam: the eye
    follows an edge sweeping up the screen where it cannot see a boundary
    standing still. Watched side by side, the scattered cycle reads as light
    breathing and the coherent one reads as a wipe. This order is the one the
    rail ships.
    """
    tint_cells = _tinted()
    slot_of = {}
    for k, c in enumerate(tint_cells):
        slot_of[c] = (k * 97) % len(tint_cells)     # 97 is coprime with 304

    tiles, ix, words = [], {}, [0] * (TW * TH)
    for ty in range(TH):
        for tx in range(TW):
            if (tx, ty) in slot_of:
                continue
            f, by, _ = fit_tile(_block(0, tx, ty))
            key = (f, tuple(by))
            if key not in ix:
                ix[key] = len(tiles)
                tiles.append(by)
            words[ty * TW + tx] = ix[key] | (f << 10)

    hue_base = len(tiles)
    tiles.extend([0] * 64 for _ in tint_cells)
    fields = [0] * len(tint_cells)
    # The field is chosen ACROSS the cycle, not for phase 0: the map word is
    # uploaded once, so one field has to serve every hue the tile will wear.
    probe = range(0, HUE_PHASES, max(1, HUE_PHASES // 4))
    for c in tint_cells:
        blocks = [_block(ph, c[0], c[1]) for ph in probe]
        best = min(range(8),
                   key=lambda f: sum(fit_tile(b, force=f)[2] for b in blocks))
        slot = slot_of[c]
        fields[slot] = best
        _, by, _ = fit_tile(_block(0, c[0], c[1]), force=best)
        tiles[hue_base + slot] = by
        words[c[1] * TW + c[0]] = (hue_base + slot) | (best << 10)
    return tiles, words, hue_base, tint_cells, slot_of, fields


def rate_curve(total):
    """-> a RATE_LEN table of whole tiles a frame, summing to exactly `total`.

    Error-diffused, so a fractional rate under one tile a frame becomes "a
    tile every few frames" rather than nothing — the quiet part of the curve
    still moves. The residue is corrected onto the peak, where one tile more
    or less is invisible, so the table sums to a phase EXACTLY and the cursor
    wraps where the colour does.
    """
    shape = [((1 - math.cos(2 * math.pi * i / RATE_LEN)) / 2) ** RATE_POW
             for i in range(RATE_LEN)]
    amp = (total - RATE_FLOOR * RATE_LEN) / sum(shape)
    if amp <= 0:
        raise SystemExit("RATE_FLOOR alone already exceeds a phase")
    out, carry = [], 0.0
    for v in shape:
        want = RATE_FLOOR + v * amp + carry
        n = int(round(want))
        carry = want - n
        out.append(max(0, n))
    i = 0
    while sum(out) != total:                # the rounding residue, onto the peak
        j = max(range(RATE_LEN), key=lambda t: out[t])
        out[j] += 1 if sum(out) < total else -1
        i += 1
        assert i < 64
    return out


def hue_blob(tint_cells, slot_of, fields):
    """HUE_PHASES copies of every tinted tile, in VRAM slot order.

    Slot order is what makes a slice one transfer: phase p's slice j is the
    bytes for slots [j*SLICE, (j+1)*SLICE), which land at a contiguous VRAM
    run — one VMADD, one DMA.
    """
    n = len(tint_cells)
    cell_of = {slot_of[c]: c for c in tint_cells}
    out = bytearray()
    for ph in range(HUE_PHASES):
        for slot in range(n):
            tx, ty = cell_of[slot]
            _, by, _ = fit_tile(_block(ph, tx, ty), force=fields[slot])
            out += chr8([by])
    return bytes(out)


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
# order and the `.assert`s in main.asm are all ONE number. The generator
# prints what the art actually occupies — that is the figure to watch, and it
# is not the same figure as the claim.
CHR1_TILES = 352                  # x 64 B, EIGHT bpp
CHR2_TILES = 224                  # x 32 B
OBJ_TILES = 64                    # four rows of the PPU's 16-wide OBJ grid
WRITE_BYTES = 6144
RATE_BYTES = 256
HUE_CHUNK = 32768                 # ...and the hue blob is bank_tiled at the
                                  # LoROM window, which is clean here because
                                  # 32768 / 64 is 512 whole 8bpp tiles, so a
                                  # chunk boundary never splits one


def pad(blob, n, what):
    if len(blob) > n:
        raise SystemExit("%s needs %d B, claim is %d" % (what, len(blob), n))
    return blob + bytes(n - len(blob))


if __name__ == "__main__":
    import write_on
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
    out.mkdir(parents=True, exist_ok=True)

    tiles1, words1, hue_base, tint_cells, slot_of, fields = cut_bg1()
    cov, tim = write_on.ink(W, H)
    tiles2, words2, ink_base, ink_cells = cut_bg2(cov)
    stream, peak, total = write_stream(cov, tim, ink_base, ink_cells,
                                       write_on.FRAMES)
    hue = hue_blob(tint_cells, slot_of, fields)
    hue_chunks = -(-len(hue) // HUE_CHUNK)

    (out / "aur_chr1.bin").write_bytes(pad(chr8(tiles1), CHR1_TILES * 64, "chr1"))
    (out / "aur_map1.bin").write_bytes(map_bytes(words1))
    (out / "aur_chr2.bin").write_bytes(pad(chr4(tiles2), CHR2_TILES * 32, "chr2"))
    (out / "aur_map2.bin").write_bytes(map_bytes(words2))
    (out / "aur_pal.bin").write_bytes(pal_bytes(PAL_BG2) + pal_bytes(PAL_OBJ))
    (out / "aur_obj.bin").write_bytes(pad(obj_sheet(), OBJ_TILES * 32, "obj"))
    (out / "aur_write.bin").write_bytes(pad(stream, WRITE_BYTES, "write"))
    (out / "aur_hue.bin").write_bytes(pad(hue, hue_chunks * HUE_CHUNK, "hue"))

    rate = rate_curve(len(tint_cells))
    (out / "aur_rate.bin").write_bytes(pad(bytes(rate), RATE_BYTES, "rate"))
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

; --- the hue cycle ------------------------------------------------------
AUR_HUE_BASE    = %d        ; the first BG1 tile the aurora owns. The sky's %d
                          ;   tiles dedupe and come first; these do NOT dedupe
                          ;   — each is rewritten every phase, so two cells
                          ;   that match at phase 0 still need separate slots
AUR_HUE_TILES   = %d      ; ...and they are CONTIGUOUS, so a frame's run of
                          ;   them is one VMADD and one transfer
AUR_HUE_BYTES   = %d    ; AUR_HUE_TILES x 64 — the slice of chr1 the RISE
                          ;   re-uploads to take the aurora back out of the
                          ;   sky. The base page holds those tiles UNLIT, so
                          ;   restoring is a DMA out of the picture the ROM
                          ;   already ships, exactly as the pen's erase is
AUR_HUE_OFF     = %d      ; ...at this offset into the chr1 blob
AUR_HUE_PHASES  = %d
AUR_RATE_LEN    = %d       ; the rate curve: whole tiles a frame, one entry
AUR_RATE_PEAK   = %d         ;   per frame, summing to EXACTLY one phase so the
                          ;   cursor wraps where the colour does
AUR_HUE_PHASE_B = %d    ; one whole phase, for stepping the source
AUR_HUE_CHUNKS  = %d        ; ...bank_tiled at the 32 KB window
AUR_HUE_PER_CHUNK = %d    ; and a window holds this many WHOLE 8bpp tiles,
AUR_HUE_CHUNK_SH = %d      ;   which is why bank_tiled is clean here: a chunk
                          ;   boundary never splits a tile. The shift beside
                          ;   it is log2 of the same number, so the NMI hook
                          ;   reaches a chunk without a divide

; --- the figures --------------------------------------------------------
AUR_FIGS        = %d
AUR_FIG_TOP     = %d      ; every figure's OAM Y — a 16x32 sprite whose bottom
                          ;   row sits on the cliff edge
""" % (W, H, TW, TH, CLIFF,
       ink_base, len(ink_cells), write_on.FRAMES, peak,
       len(ink_cells) * 32, ink_base * 32,
       hue_base, hue_base, len(tint_cells),
       len(tint_cells) * 64, hue_base * 64, HUE_PHASES,
       RATE_LEN, max(rate), len(tint_cells) * 64, hue_chunks,
       HUE_CHUNK // 64, (HUE_CHUNK // 64).bit_length() - 1,
       len(FIGURES), CLIFF + 2 - OBJ_H)
    for n, (fx, h, w) in enumerate(FIGURES):
        inc += "AUR_FIG%d_X       = %d\n" % (n, fx - OBJ_W // 2)
    (out / "aur_art.inc").write_text(inc)

    print("BG1 %d/%d 8bpp tiles (%d sky + %d the aurora's own)"
          % (len(tiles1), CHR1_TILES, hue_base, len(tint_cells)))
    print("BG2 %d/%d 4bpp tiles, %d of them ink; write %d/%d B, %d uploads, peak %d"
          % (len(tiles2), CHR2_TILES, len(ink_cells), len(stream), WRITE_BYTES,
             total, peak))
    print("HUE %d phases x %d tiles = %d B -> %d chunks (%d B claimed)"
          % (HUE_PHASES, len(tint_cells), len(hue), hue_chunks,
             hue_chunks * HUE_CHUNK))
    print("RATE %d frames a phase, %d..%d tiles a frame (peak %d B), "
          "so the cycle closes in %d frames = %.0f s NTSC"
          % (RATE_LEN, min(rate), max(rate), max(rate) * 64,
             HUE_PHASES * RATE_LEN, HUE_PHASES * RATE_LEN / 60.0))
