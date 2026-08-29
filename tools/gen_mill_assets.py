#!/usr/bin/env python3
"""mill — the machine hall's art, its offset row, and the geometry both agree on.

THE RAIL'S SUBJECT IS MODE 4'S AXIS BIT. Modes 2 and 6 fetch a word for EACH
axis, so a column can be displaced on both and the axis is not a choice. Mode 4
fetches ONE word and bit 15 picks — so a single 32-word row can pump one bay
vertically and run the next sideways, which is the one thing mode 4 does that
mode 2 cannot (docs/100 §2, §5 O7).

TWO AXES, TWO LAYERS, AND THAT IS NOT DECORATION. Offset-per-tile displaces a
WHOLE COLUMN, so each axis imposes an invariance on the art it moves and the
two invariances are incompatible in one layer:

  a VERTICALLY displaced column shows its own pixels at another row, so
      everything in it that must not appear to move has to be identical row
      to row — smelter's wall, and here the piston SHAFT.
  a HORIZONTALLY displaced column shows the NEIGHBOURING TILE, because the
      layer keeps its own fine three bits and the word's are dropped (hScroll
      = (BGnHOFS & 7) | (word & $3F8), SnesPpu.cpp:157) — so everything that
      must not appear to move has to be the SAME TILE across the map row, and
      what moves has to be a repeating texture whose phase the shift changes.

Put both in one layer and a shifted belt column samples a piston's cap. Put
them on BG1 and BG2 and each gets the invariance it needs, and the table then
exercises the enable bits AND the axis bit in the same 32 words.

  BG1  8bpp, in front. Piston bays: a fluted shaft whose eight rows are
       IDENTICAL, with a piston head two tiles tall that the vertical
       displacement moves. Belt bays: transparent, so BG2 shows through, with
       a static girder across the top — static because those columns' words
       drive the OTHER layer and BG1 is never displaced there.
  BG2  2bpp, behind. One wall tile in every column of every row it fills, so
       any horizontal shift is invariant, plus a belt band of four tread tiles
       repeating across all 32 columns, so a shift of k tiles shows tread
       phase (c + k) % 4 and the belt runs.

8BPP BUYS DEPTH, NOT SIZE. A tile is 64 bytes against 4bpp's 32, so the budget
that bought smelter fifteen tiles buys about sixty here — the hall is a bay
repeated four times with 64 colours of metal in it, not sixty distinct things.
"""
import pathlib
import sys

OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
OUT.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
COLS = 32                     # a 32-tile map row: the table's width and BG's
ROWS = 32                     # ...and its height. 256 px, so no scroll wraps
BAY = 8                       # one machine bay: 4 piston columns, 4 belt
PISTON_COLS = 4               # ...of the bay, on the left
PHASES = 64                   # the loop closes here
PHASE_SHIFT = 6               # a row is 32 words = 64 B -> index << 6
ROW_BYTES = COLS * 2

# THE PISTON'S STROKE, in pixels of vertical displacement. The head sits at
# map row CAP_ROW and a displacement of v puts it at screen row CAP_ROW*8 - v,
# so the stroke has to keep that inside the picture at both ends.
CAP_ROW = 22                  # 176 px down the map
STROKE = 96                   # ...so the head travels screen rows 80..176
BAY_PHASE = 16                # ...and each bay is a quarter-cycle behind

# THE BELT'S RATE, in units of the H field. It is 8-PIXEL granular — the layer
# keeps its own low three bits — so only multiples of 8 do anything, and a
# step of 4 per phase means a tile every other phase. Two bays run one way and
# two the other, because a hall where everything moves together reads as one
# mechanism rather than several.
BELT_STEP = 4
BELT_DIR = (1, -1, 1, -1)

BIT_BG1 = 0x2000              # this column's offset drives BG1
BIT_BG2 = 0x4000              # ...or BG2
BIT_VSEL = 0x8000             # mode 4 ONLY: this word is a V offset
V_MASK = 0x03FF
H_MASK = 0x03F8

# --------------------------------------------------------------------------
# palettes
# --------------------------------------------------------------------------
# BG2 IS 2BPP AND THAT PINS IT TO CGRAM 0..31. A 2bpp tilemap entry's palette
# field is three bits selecting one of eight groups of FOUR, so the whole layer
# lives in the first 32 words whatever else is on screen. BG1 is 8bpp and
# indexes CGRAM directly with no palette field at all, so the two would collide
# on every index BG1 used below 32 — which is why BG1's art starts at 32 and
# the claim reserves from there.
BG1_IX0 = 32
BG1_SHADES = 64


def rgb(r, g, b):
    return (b << 10) | (g << 5) | r


def ramp(a, b, n):
    """n steps from a to b, in 5-bit BGR555 components."""
    return [rgb(*(round(a[i] + (b[i] - a[i]) * k / (n - 1)) for i in range(3)))
            for k in range(n)]


# 64 entries: a cold steel ramp for the shaft, a warm brass one for the head,
# and a short hot run for the glow inside the housing. 8bpp is what makes a
# 24-step ramp affordable at all — at 4bpp the whole layer has sixteen.
PAL_BG1 = (ramp((2, 3, 5), (24, 27, 31), 24)        # 0..23   steel, dark->lit
           + ramp((8, 1, 1), (31, 13, 7), 24)       # 24..47  copper, dark->lit
                                                    #   RED, not brass: the
                                                    #   belt below is warm
                                                    #   yellow and a brass head
                                                    #   read as the same object
           + ramp((10, 0, 0), (31, 22, 6), 16))     # 48..63  furnace glow
assert len(PAL_BG1) == BG1_SHADES

# BG2'S FOUR, AND THE SPLIT IN THEM IS DELIBERATE. 2bpp is four colours for the
# WHOLE layer, and the layer carries two things that must not be confused: a
# wall that must look still and a belt that must look like it is running. So
# the wall gets the two dark ones and the belt gets the two bright ones, and no
# index is shared between them — a belt drawn in the wall's own two shades is a
# belt nobody can see move, which is what the first cut of this rail shipped.
PAL_BG2 = [rgb(1, 1, 3),      # 0 the backdrop — CGRAM word 0, so it is the
                              #   whole screen's border colour as well
           rgb(4, 5, 9),      # 1 the hall wall
           rgb(14, 11, 6),    # 2 the belt's body, warm against the cold hall
           rgb(28, 24, 14)]   # 3 ...and the cleat that catches the light


# --------------------------------------------------------------------------
# BG1 — 8bpp, the machinery
# --------------------------------------------------------------------------
def shaft_tile():
    """The piston housing: EIGHT IDENTICAL ROWS.

    That is the whole vertical-invariance contract, and it is the same one
    smelter's wall carries for the same reason — a vertically displaced column
    shows its own pixels at another row, so a shaft with any horizontal seam
    in it would slide that seam up and down as the piston pumped. Flutes run
    the other way: a fixed shade per pixel COLUMN, which a vertical shift
    cannot move.
    """
    prof = [3, 8, 14, 20, 23, 17, 9, 4]          # a lit round column
    row = [BG1_IX0 + p for p in prof]
    return [list(row) for _ in range(8)]


def cap_tiles():
    """The piston head, two tiles tall — the ONE thing in a piston column that
    is not row-uniform, and therefore the one thing its displacement moves."""
    top = []
    for y in range(8):
        v = (28, 34, 40, 44, 46, 43, 38, 32)[y]
        top.append([BG1_IX0 + min(63, v + (2 if 1 <= x <= 6 else -6))
                    for x in range(8)])
    bot = []
    for y in range(8):
        v = (30, 27, 24, 21, 19, 17, 15, 13)[y]
        bot.append([BG1_IX0 + max(24, v + (0 if 1 <= x <= 6 else -4))
                    for x in range(8)])
    return top, bot


def girder_tile():
    """The frame over the belt bays. STATIC, and it can be: those columns'
    words carry the BG2 enable bit, so BG1 is never displaced there."""
    rows = []
    for y in range(8):
        if y < 2:
            rows.append([BG1_IX0 + (12 if (x % 4) else 20) for x in range(8)])
        elif y < 4:
            rows.append([BG1_IX0 + 8] * 8)
        else:
            rows.append([0] * 8)                  # transparent: BG2 shows
    return rows


BG1_TILES = [("clear", [[0] * 8 for _ in range(8)]),
             ("shaft", shaft_tile()),
             ("cap_a", cap_tiles()[0]),
             ("cap_b", cap_tiles()[1]),
             ("girder", girder_tile())]
T1_CLEAR, T1_SHAFT, T1_CAP_A, T1_CAP_B, T1_GIRDER = range(len(BG1_TILES))


# --------------------------------------------------------------------------
# BG2 — 2bpp, the hall and the belt
# --------------------------------------------------------------------------
BELT_ROW = 16                 # the tread's map row
BELT_PHASES = 4               # ...and how many tiles its pattern repeats over


def wall_tile():
    """The hall behind everything. ITS ART IS UNCONSTRAINED — a horizontal
    shift moves a whole TILE, so what invariance needs is that every column of
    the row holds the SAME tile, not that the tile be featureless. That is the
    one way the H axis is kinder than the V axis, which is pixel-granular."""
    rows = []
    for y in range(8):
        if y in (0, 7):
            rows.append([0] * 8)            # a course line, top and bottom
        else:
            rows.append([0 if x == 0 else 1 for x in range(8)])
    return rows


def tread_tile(k):
    """One phase of the belt. A shift of j tiles shows phase (c + j) % 4, so
    the pattern's PHASE is what the displacement moves — the only shape a
    horizontally displaced column can animate."""
    rows = []
    for y in range(8):
        if y in (0, 7):
            rows.append([2] * 8)            # the belt's rails
        else:
            # A DIAGONAL CLEAT, so the phase step is legible as travel rather
            # than as a flicker: a vertical bar looks the same shifted by any
            # multiple of its period, a sloped one does not.
            rows.append([3 if ((x + y + k * 2) % 8) < 3 else 2
                         for x in range(8)])
    return rows


BG2_TILES = ([("wall", wall_tile())]
             + [(f"tread{k}", tread_tile(k)) for k in range(BELT_PHASES)])
T2_WALL = 0
T2_TREAD0 = 1


# --------------------------------------------------------------------------
# encoders
# --------------------------------------------------------------------------
def encode_8bpp(rows, who):
    """One 8x8 tile, 64 bytes: four bitplane PAIRS, planes 0/1 then 2/3 then
    4/5 then 6/7, each pair interleaved by row the way 4bpp's first pair is."""
    out = bytearray()
    for pair in range(4):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                assert 0 <= v < 256, f"{who}: index {v} is not 8bpp"
                lo |= ((v >> (pair * 2)) & 1) << (7 - x)
                hi |= ((v >> (pair * 2 + 1)) & 1) << (7 - x)
            out += bytes((lo, hi))
    return bytes(out)


def encode_2bpp(rows, who):
    out = bytearray()
    for y in range(8):
        lo = hi = 0
        for x in range(8):
            v = rows[y][x]
            assert 0 <= v < 4, f"{who}: index {v} is not 2bpp"
            lo |= (v & 1) << (7 - x)
            hi |= ((v >> 1) & 1) << (7 - x)
        out += bytes((lo, hi))
    return bytes(out)


def pal_bytes(words):
    out = bytearray()
    for w in words:
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


# --------------------------------------------------------------------------
# the maps
# --------------------------------------------------------------------------
def is_piston(col):
    return (col % BAY) < PISTON_COLS


def map1():
    """BG1: piston columns are SHAFT everywhere but the head; belt columns are
    transparent with a girder over them."""
    out = bytearray()
    for r in range(ROWS):
        for c in range(COLS):
            if is_piston(c):
                t = (T1_CAP_A if r == CAP_ROW else
                     T1_CAP_B if r == CAP_ROW + 1 else T1_SHAFT)
            else:
                t = T1_GIRDER if r == 0 else T1_CLEAR
            out += bytes((t & 0xFF, t >> 8))
    return bytes(out)


def map2():
    """BG2: ONE tile in every column of every row, except the belt band, whose
    four tread phases repeat across all 32 columns — so a horizontal shift is
    invariant off the band and a phase change on it, in every column alike."""
    out = bytearray()
    for r in range(ROWS):
        for c in range(COLS):
            t = (T2_TREAD0 + (c % BELT_PHASES)
                 if BELT_ROW <= r < BELT_ROW + 2 else T2_WALL)
            out += bytes((t & 0xFF, t >> 8))
    return bytes(out)


# --------------------------------------------------------------------------
# the offset row — ONE word a column, and bit 15 picks its axis
# --------------------------------------------------------------------------
def piston_v(col, phase):
    """A stroke: down slow, up slow, a quarter cycle apart per bay."""
    import math
    t = (phase + (col // BAY) * BAY_PHASE) / PHASES
    return int(round(STROKE * (1 - math.cos(2 * math.pi * t)) / 2))


def belt_h(col, phase):
    return (BELT_DIR[(col // BAY) % len(BELT_DIR)] * BELT_STEP * phase) & 0x3FF


def column_word(col, phase):
    if is_piston(col):
        return BIT_BG1 | BIT_VSEL | (piston_v(col, phase) & V_MASK)
    return BIT_BG2 | (belt_h(col, phase) & H_MASK)


def flat_word(col):
    """The control row. THE ENABLE BITS AND THE AXIS BIT STAY SET and only the
    VALUE goes to rest — smelter's rule and heathaze's before it: a control
    that also disarms the mechanism cannot tell a broken table from a broken
    transfer, because both produce the same still picture."""
    if is_piston(col):
        return BIT_BG1 | BIT_VSEL | ((STROKE // 2) & V_MASK)
    return BIT_BG2 | 0


def row_table():
    out = bytearray()
    for phase in range(PHASES):
        for col in range(COLS):
            w = column_word(col, phase)
            out += bytes((w & 0xFF, w >> 8))
    for col in range(COLS):                      # ...and the flat control
        w = flat_word(col)
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------
def main():
    chr1 = b"".join(encode_8bpp(r, n) for n, r in BG1_TILES)
    chr2 = b"".join(encode_2bpp(r, n) for n, r in BG2_TILES)
    (OUT / "mil_chr1.bin").write_bytes(chr1)
    (OUT / "mil_chr2.bin").write_bytes(chr2)
    (OUT / "mil_map1.bin").write_bytes(map1())
    (OUT / "mil_map2.bin").write_bytes(map2())
    # ONE PALETTE BLOB, TWO GROUPS, and the offset is emitted beside it. Two
    # blobs would be two rom claims the packer orders by size, and the uploader
    # reaches the second by an offset from the first — which is a SIGNED
    # distance whose sign the packer decides. Smelter's smt_pal.bin is one blob
    # for the same reason.
    (OUT / "mil_pal.bin").write_bytes(pal_bytes(PAL_BG1) + pal_bytes(PAL_BG2))
    (OUT / "mil_row.bin").write_bytes(row_table())

    inc = f"""; mil_art.inc — GENERATED by tools/gen_mill_assets.py. Do not edit.
; The machine hall's geometry, so the ASM and the tests read ONE copy of it.
SMIL_COLS         = {COLS}
SMIL_ROWS         = {ROWS}
SMIL_BAY          = {BAY}      ; a bay: this wide, piston half then belt half
SMIL_PISTON_COLS  = {PISTON_COLS}
SMIL_PHASES       = {PHASES}     ; the loop closes here
SMIL_FLAT_INDEX   = {PHASES}     ; ...and the control row sits past it
SMIL_ROW_COUNT    = {PHASES + 1}     ; phases + the control
SMIL_PHASE_SHIFT  = {PHASE_SHIFT}      ; a row is {ROW_BYTES} B -> index << {PHASE_SHIFT}
SMIL_ROW_BYTES    = {ROW_BYTES}
SMIL_CAP_ROW      = {CAP_ROW}     ; the piston head's map row
SMIL_STROKE       = {STROKE}
SMIL_BELT_ROW     = {BELT_ROW}
SMIL_BELT_PHASES  = {BELT_PHASES}
SMIL_BG1_IX0      = {BG1_IX0}     ; BG1 is 8bpp and indexes CGRAM directly, so
SMIL_BG1_SHADES   = {BG1_SHADES}     ;   its art starts past BG2's four
SMIL_TILES1       = {len(BG1_TILES)}
SMIL_TILES2       = {len(BG2_TILES)}
SMIL_T1_SHAFT     = {T1_SHAFT}
SMIL_T1_CAP_A     = {T1_CAP_A}
SMIL_T2_TREAD0    = {T2_TREAD0}

; THE FALLBACK PORTS' REST VALUES. A column whose word does not carry a layer's
; enable bit shows that layer at its own BGnVOFS — so BG1's is what every BELT
; column shows for BG1 (the girder at the top of the map) and BG2's is what
; every PISTON column shows for BG2 (the hall with its belt band at rest).
SMIL_PAL2_OFF     = {2 * len(PAL_BG1)}    ; BG2's four words, inside the one blob

SMIL_BG1_REST     = 0
SMIL_BG2_REST     = 0
"""
    (OUT / "mil_art.inc").write_text(inc)
    print(f"  mill: chr1 {len(chr1)} B ({len(BG1_TILES)} x 8bpp), "
          f"chr2 {len(chr2)} B ({len(BG2_TILES)} x 2bpp), "
          f"pal {2 * (len(PAL_BG1) + len(PAL_BG2))} B, "
          f"row table {PHASES}+1 x {ROW_BYTES} B")


if __name__ == "__main__":
    main()
