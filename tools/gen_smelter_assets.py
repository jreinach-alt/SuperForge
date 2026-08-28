#!/usr/bin/env python3
"""Assets for the `smelter` rail — a foundry floor where every 8-pixel column
scrolls on its own, out of BG3's tilemap and not out of an HDMA channel.

THREE KINDS OF OUTPUT, and the third is the point of the rail.

  the PLATES   BG1 4bpp tile art: steel plates, and nothing else. BG1 is
               TRANSPARENT everywhere a plate is not, which is what lets a
               per-column vertical offset move one plate without moving the
               world behind it.

  the MELT     BG2 4bpp tile art: a cavern wall with no horizontal feature in
               it at all, a bright crust line, and the melt below. The wall's
               vertical uniformity is deliberate and load-bearing: displacing
               a column of it shows nothing, so the ONLY thing a viewer (or a
               test) can see move is the crust — which is exactly the edge the
               per-column equality is asserted on.

  the TABLE    `smt_col.bin` — SMT_PHASES complete 32-word BG3 offset rows,
               plus a flat control, at a 64 B stride. Each word is one
               column's vertical scroll for one layer, with the enable bit
               that says WHICH layer (bit 13 = BG1, bit 14 = BG2).

OFFSET-PER-TILE, AND WHY IT IS NOT AN HDMA EFFECT. In modes 2, 4 and 6 the
PPU stops reading BG3's tilemap as tiles: for every 8-pixel column it fetches
a word out of it and uses it as that column's scroll (Mesen2
Core/SNES/SnesPpu.cpp, GetHorizontalOffsetByte / GetVerticalOffsetByte at
:257-276, applied in GetTilemapData at :153-169). The whole mechanism runs out
of the ordinary tilemap fetch a layer already pays for, so it costs ZERO HDMA
channels and zero per-scanline CPU. What it costs is the VBlank upload of the
row — 64 B a frame here — and that is the entire per-frame price of every
column on screen moving independently.

ONE VALUE A COLUMN, TWO GATES. A column's word carries ONE offset and two
enable bits, so BG1 and BG2 can each be gated in or out of it but they cannot
be displaced by DIFFERENT amounts in the same column. That is not a limitation
this file works around, it is the shape it is designed to: the plate columns
drive BG1 and the gap columns drive BG2, so the melt is calm under the plates
and erupts in the gaps the player has to jump.

THE OFFSET REPLACES THE SCROLL, it does not add to it (vScroll = word & $3FF,
SnesPpu.cpp:167), so every number in this table is an ABSOLUTE position, and a
column whose enable bit is clear falls back to its layer's own BGnVOFS.
"""
import math
import pathlib
import sys

# --------------------------------------------------------------------------
# geometry — every number here is emitted into smt_art.inc, never restated
# --------------------------------------------------------------------------
COLS = 32                    # 256 px / 8: one offset word each
PHASES = 64                  # the animation loop
PHASE_SHIFT = 6              # stride 64 B -> a phase is (index << 6)
STRIDE = 1 << PHASE_SHIFT

# BG1 — the plates. A 32x64 map (512 px tall) so no scroll value in range ever
# wraps; the plate band is two rows, and its TOP is the edge everything is
# measured against.
PLAT_MAP_ROW = 40
PLAT_TOP_PX = PLAT_MAP_ROW * 8          # 320
PLAT_BASE = 240                          # screen y = 320 - 240 = 80
PLAT_AMP = 40                            # ...so y travels 40..120

# Four plates, each four columns (32 px) wide: (first column, width).
# The GAPS between them are where the melt erupts, which is the same fact as
# "a column drives one layer or the other" seen from the picture's side.
PLATES = ((3, 4), (11, 4), (19, 4), (27, 4))
# Each plate's own frequency and phase in the 64-frame loop. Integer
# frequencies so every plate closes the loop; DIFFERENT ones so no two plates
# ever settle into lockstep — the independence is meant to be watchable, and
# two plates on one frequency read as one plate cut in half.
PLATE_FREQ = (1, 2, 1, 3)
PLATE_OFF = (0.00, 0.25, 0.50, 0.10)

# BG2 — the melt. Same map shape. Rows 0..31 are wall, row 32 is the crust,
# 33..63 the body: the crust's top pixel is the measurable edge.
CRUST_MAP_ROW = 32
CRUST_TOP_PX = CRUST_MAP_ROW * 8        # 256
MELT_BASE = 126                          # screen y = 256 - 126 = 130
MELT_AMP = 40                            # a jet lifts the crust to y = 90
MELT_RIPPLE = 4                          # ...and nothing is ever perfectly
                                         #    still, which is what keeps a
                                         #    gallery clip from reading as a
                                         #    frozen frame
# The jets, one per gap between plates (and the two screen edges), each with
# its own frequency and phase. RECTIFIED: a jet rises out of the surface and
# falls back to it rather than dipping below, because a jet that went down
# would read as a hole.
#
# THE GAPS ARE DELIBERATELY UNEQUAL — 3, 4, 4, 4 and 1 columns wide — and the
# odd ones are the sharpest thing in the picture. A jet's amplitude is an arch
# across its run (0 at the edges, 1 in the middle), so a 4-wide gap lifts two
# columns together, a 3-wide gap lifts EXACTLY ONE while both its neighbours
# hold still, and the 1-wide gap at the right edge is a single 8-pixel column
# of melt standing alone. That is the whole claim of the mechanism made
# visible: the granularity is one column, not one layer and not one band.
JET_FREQ = (1, 2, 1, 2, 3)
JET_OFF = (0.00, 0.35, 0.62, 0.18, 0.80)

# The enable bits, from the hardware. They are ALSO emitted by the allocator
# as ES_OPT_WORKS_BG1 / _BG2 and the ASM builds nothing from these — this file
# needs them because it is the thing that writes the words.
BIT_BG1 = 0x2000
BIT_BG2 = 0x4000

# --------------------------------------------------------------------------
# palettes (BGR555)
# --------------------------------------------------------------------------
def rgb(r, g, b):
    return (b << 10) | (g << 5) | r


# Group 0 — BG1's plates. Word 0 is the 4bpp transparent slot AND the hardware
# backdrop at once, which is why this group is claimed with `at = 0`: one word,
# two meanings, one owner. Nothing ever sees it here (BG2 is opaque across the
# whole picture), and it is claimed anyway because the hardware does not care
# what we expect to see.
PAL_PLATE = [
    rgb(2, 2, 4),        # 0 backdrop / transparent
    rgb(7, 8, 10),       # 1 plate shadow
    rgb(13, 14, 16),     # 2 plate body
    rgb(20, 21, 23),     # 3 plate highlight
    rgb(26, 27, 28),     # 4 plate top edge
    rgb(9, 6, 4),        # 5 rust
    rgb(4, 4, 6),        # 6 plate underside
    rgb(16, 12, 6),      # 7 rivet
] + [0] * 8

# Group 1 — BG2's cavern and melt.
PAL_MELT = [
    rgb(0, 0, 0),        # 0 unused (BG2 is opaque everywhere)
    rgb(4, 3, 5),        # 1 wall dark
    rgb(6, 5, 8),        # 2 wall light
    rgb(31, 30, 14),     # 3 crust white-hot
    rgb(31, 20, 2),      # 4 crust orange
    rgb(28, 9, 0),       # 5 melt bright
    rgb(20, 4, 0),       # 6 melt mid
    rgb(12, 1, 0),       # 7 melt dark
] + [0] * 8


# --------------------------------------------------------------------------
# tiles — 8x8 index grids
# --------------------------------------------------------------------------
def solid(v):
    return [[v] * 8 for _ in range(8)]


def wall_tile(shift):
    """A cavern-wall tile with VERTICAL streaks only: every row is identical,
    so displacing a column of wall is invisible. That is the point — the wall
    is the still background against which the crust's movement is the whole
    signal, and a wall with a horizontal seam in it would make the per-column
    equality unreadable at exactly the rows it matters."""
    row = [2 if ((x + shift) % 5 == 0 or (x + shift) % 7 == 3) else 1
           for x in range(8)]
    return [list(row) for _ in range(8)]


def crust_tile(seed):
    """The melt's surface: two white-hot rows over orange over the body. The
    TOP row is the edge every measurement lands on, so it is the brightest
    thing in the palette and it is unbroken across the tile."""
    rows = [[3] * 8, [3 if (x + seed) % 3 else 4 for x in range(8)],
            [4] * 8, [4 if (x + seed) % 4 else 5 for x in range(8)],
            [5] * 8, [5 if (x * 3 + seed) % 5 else 6 for x in range(8)],
            [6] * 8, [6 if (x + seed) % 3 else 5 for x in range(8)]]
    return rows


def melt_tile(seed):
    rows = []
    for y in range(8):
        rows.append([5 if ((x * 5 + y * 3 + seed) % 11 == 0) else
                     (7 if ((x + y * 2 + seed) % 9 == 0) else 6)
                     for x in range(8)])
    return rows


def plate_top(kind):
    """kind: 0 left end, 1 middle, 2 right end. Row 0 is the plate's TOP EDGE
    and it is a single bright line across the tile — the same reason the crust
    is: this is the edge the per-column assertion reads."""
    rows = [[4] * 8, [3] * 8,
            [2, 2, 3, 2, 2, 2, 3, 2],
            [2] * 8,
            [2, 7, 2, 2, 2, 2, 7, 2],
            [1] * 8, [1] * 8, [1, 1, 1, 5, 5, 1, 1, 1]]
    if kind == 0:
        for y in range(8):
            rows[y][0] = 0 if y >= 6 else 4
    if kind == 2:
        for y in range(8):
            rows[y][7] = 0 if y >= 6 else 4
    return rows


def plate_under(kind):
    rows = [[6 if (x + y) % 5 else 1 for x in range(8)] for y in range(8)]
    for y in range(8):
        if y >= 5:
            rows[y] = [0] * 8
    if kind == 0:
        for y in range(5):
            rows[y][0] = 0
    if kind == 2:
        for y in range(5):
            rows[y][7] = 0
    return rows


# BG1's tiles: 0 must be fully transparent — every column that is not a plate
# shows it at every row, which is what makes BG1 a layer carrying four movable
# objects rather than a picture.
PLATE_TILES = [
    ("clear", solid(0)),
    ("top_l", plate_top(0)), ("top_m", plate_top(1)), ("top_r", plate_top(2)),
    ("und_l", plate_under(0)), ("und_m", plate_under(1)),
    ("und_r", plate_under(2)),
]
MELT_TILES = [
    ("wall_a", wall_tile(0)), ("wall_b", wall_tile(3)),
    ("crust_a", crust_tile(0)), ("crust_b", crust_tile(2)),
    ("melt_a", melt_tile(0)), ("melt_b", melt_tile(5)),
]

T_CLEAR, T_TOP_L, T_TOP_M, T_TOP_R, T_UND_L, T_UND_M, T_UND_R = range(7)
# BG2's tiles sit after BG1's in one shared CHR claim, so their ids are offset.
MELT_BASE_TILE = len(PLATE_TILES)
T_WALL_A, T_WALL_B, T_CRUST_A, T_CRUST_B, T_MELT_A, T_MELT_B = \
    (MELT_BASE_TILE + i for i in range(6))

ATTR_G0 = 0 << 10            # palette group 0 — the plates
ATTR_G1 = 2 << 10            # palette group 2 — the cavern and the melt. Not
                             # group 1: bg_text pins CGRAM words 28..31 for
                             # its 2bpp palette 7, which lands inside group
                             # 1, and the title scene composes both.


# --------------------------------------------------------------------------
# tilemaps — 32 x 64 words each (a 512 px tall map, so no scroll in range
# wraps and every screen row is the row this file drew)
# --------------------------------------------------------------------------
MAP_ROWS = 64


def plate_map():
    m = [[T_CLEAR | ATTR_G0] * COLS for _ in range(MAP_ROWS)]
    for first, width in PLATES:
        for i in range(width):
            c = first + i
            kind = 0 if i == 0 else (2 if i == width - 1 else 1)
            m[PLAT_MAP_ROW][c] = (T_TOP_L + kind) | ATTR_G0
            m[PLAT_MAP_ROW + 1][c] = (T_UND_L + kind) | ATTR_G0
    return [w for row in m for w in row]


def melt_map():
    m = []
    for r in range(MAP_ROWS):
        if r < CRUST_MAP_ROW:
            row = [(T_WALL_A if (c + r) % 2 == 0 else T_WALL_B) | ATTR_G1
                   for c in range(COLS)]
        elif r == CRUST_MAP_ROW:
            row = [(T_CRUST_A if c % 2 == 0 else T_CRUST_B) | ATTR_G1
                   for c in range(COLS)]
        else:
            row = [(T_MELT_A if (c + r) % 3 else T_MELT_B) | ATTR_G1
                   for c in range(COLS)]
        m.append(row)
    return [w for row in m for w in row]


# --------------------------------------------------------------------------
# the offset table — the rail's subject
# --------------------------------------------------------------------------
def plate_of(col):
    """Which plate owns this column, or None. A column belongs to at most one:
    that is what makes "the plate's columns share one value" a fact about the
    table rather than an accident of how it was built."""
    for i, (first, width) in enumerate(PLATES):
        if first <= col < first + width:
            return i
    return None


def gaps():
    """The runs of columns that belong to no plate, left to right. These are
    the melt's — one jet each."""
    out, run = [], []
    for c in range(COLS):
        if plate_of(c) is None:
            run.append(c)
        elif run:
            out.append(run)
            run = []
    if run:
        out.append(run)
    return out


GAPS = gaps()


def plate_word(plate, phase):
    f, off = PLATE_FREQ[plate], PLATE_OFF[plate]
    v = PLAT_BASE + PLAT_AMP * math.sin(2 * math.pi * (f * phase / PHASES + off))
    return BIT_BG1 | (int(round(v)) & 0x3FF)


def melt_word(col, phase):
    # Which jet this column sits in, and where across it: 0 at the edges, 1 in
    # the middle. A jet is an ARCH rather than a step, so the crust leaves the
    # plates' level smoothly and the eye reads a column of melt rising rather
    # than a rectangle appearing.
    g = next(i for i, run in enumerate(GAPS) if col in run)
    run = GAPS[g]
    if len(run) == 1:
        shape = 1.0
    else:
        t = (col - run[0]) / (len(run) - 1)
        shape = math.sin(math.pi * t)
    drive = math.sin(2 * math.pi * (JET_FREQ[g] * phase / PHASES + JET_OFF[g]))
    jet = MELT_AMP * shape * max(0.0, drive)
    # ...and a small travelling ripple under all of it, so no column is ever
    # exactly still. A clip that holds a frozen frame reads as the effect
    # breaking, which is the seam lesson the last two rails paid for.
    ripple = MELT_RIPPLE * math.sin(2 * math.pi * (phase / PHASES + col / 11.0))
    return BIT_BG2 | (int(round(MELT_BASE + jet + ripple)) & 0x3FF)


def column_word(col, phase):
    p = plate_of(col)
    return plate_word(p, phase) if p is not None else melt_word(col, phase)


def flat_word(col):
    """The control. THE ENABLE BIT STAYS SET and only the VALUE goes to its
    base, so exactly one variable moves between "running" and "flat" — the
    heathaze rule: a control that also disarms the mechanism cannot tell a
    broken table from a broken transfer."""
    p = plate_of(col)
    return (BIT_BG1 | PLAT_BASE) if p is not None else (BIT_BG2 | MELT_BASE)


# THE ONE-COLUMN LEAD, and it is MEASURED, not assumed.
#
# The PPU fetches a column's tilemap data BEFORE it fetches that column's
# offset words: in mode 2 the eight-cycle group for column g runs
# GetTilemapData for BG2 and BG1 (cases 0 and 1) and only THEN
# GetHorizontalOffsetByte / GetVerticalOffsetByte (cases 2 and 3), so the
# words fetched with column index g are latched in time for column g + 1
# (Mesen2 Core/SNES/SnesPpu.cpp FetchTileData, :316-330). The latches are also
# cleared at the start of each scanline's fetch (:284-287), so SCREEN COLUMN 0
# CANNOT BE DISPLACED AT ALL — it always shows its layer's own BGnVOFS.
#
# Confirmed on the shipped binary before this shift existed: the plate whose
# words sat in table columns 3..6 rendered at screen columns 4..6 with column
# 3 at the fallback — three columns wide instead of four, with an invisible
# ghost beside it. tests/test_smelter.py asserts both halves of the rule
# against the rendered picture.
#
# So the ROW IS WRITTEN ONE COLUMN TO THE LEFT of the columns it displaces.
# Everything above this line is expressed in SCREEN columns, which is the only
# frame of reference the art, the collision and the tests share; the shift
# lives here, once, at the boundary where a screen column becomes a table
# index.
def col_table():
    out = bytearray()
    for phase in range(PHASES):
        for col in range(COLS):
            w = column_word((col + 1) % COLS, phase)
            out += bytes((w & 0xFF, w >> 8))
    for col in range(COLS):
        w = flat_word((col + 1) % COLS)
        out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


def h_row():
    """The H row — row 0 of BG3's map, which the PPU reads as the HORIZONTAL
    offset word for every column. All zero: with neither enable bit set no
    horizontal displacement is applied, which is how a V-only table is
    expressed. It is uploaded ONCE, at scene enter; only the V row is rewritten
    per frame."""
    return bytes(COLS * 2)


# --------------------------------------------------------------------------
def encode_4bpp(rows, label):
    """8x8 indices -> 32 B SNES 4bpp (planes 0/1 interleaved, then 2/3)."""
    assert len(rows) == 8, f"{label}: expected 8 rows, got {len(rows)}"
    for y, row in enumerate(rows):
        assert len(row) == 8, f"{label}: row {y} has {len(row)} px"
        for x, v in enumerate(row):
            assert 0 <= v <= 15, (
                f"{label}: pixel ({x},{y}) index {v} is outside 4bpp 0..15")
    out = bytearray()
    for pair in (0, 2):
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = rows[y][x]
                lo = (lo << 1) | ((v >> pair) & 1)
                hi = (hi << 1) | ((v >> (pair + 1)) & 1)
            out += bytes((lo, hi))
    assert len(out) == 32, f"{label}: encoded {len(out)} B, expected 32"
    return bytes(out)


def encode_words(words, label, count):
    assert len(words) == count, f"{label}: {len(words)} words, expected {count}"
    out = bytearray()
    for i, w in enumerate(words):
        assert 0 <= w <= 0xFFFF, f"{label}: entry {i} {w:#06x} is not 16-bit"
        out += bytes((w & 0xFF, (w >> 8) & 0xFF))
    return bytes(out)


ART_INC = """; smt_art.inc — GENERATED by tools/gen_smelter_assets.py. Do not edit.
;
; The SHAPE of the offset table and the geometry the plates and the melt were
; drawn at. Emitted rather than restated so the table, the walker that uploads
; it, the collision that reads it and the tests that assert on it cannot
; disagree about a single number.
SMT_COLS          = {cols}     ; offset words per row (256 px / 8)
SMT_PHASES        = {phases}     ; the loop closes here
SMT_FLAT_INDEX    = {flat}     ; the control row: same shape, base values
SMT_ROW_COUNT     = {rows}     ; phases + the control
SMT_PHASE_SHIFT   = {shift}      ; stride {stride} B -> a row is (index << {shift})
SMT_ROW_BYTES     = {stride}
SMT_TILE_COUNT    = {tiles}
SMT_PAL_MELT_OFF  = 32     ; the melt group's byte offset in smt_pal.bin

; --- BG1: the plates -------------------------------------------------------
SMT_PLAT_MAP_ROW  = {prow}     ; the plate band's first tilemap row
SMT_PLAT_TOP_PX   = {ptop}    ; ...in map pixels: the edge measurements use
SMT_PLAT_BASE     = {pbase}    ; the flat control's value for a plate column
SMT_PLAT_AMP      = {pamp}
SMT_PLAT_COUNT    = {pcount}
SMT_VOFS_BG1      = {vbg1}      ; the fallback for a column with bit 13 clear
{platcols}

; --- BG2: the melt ---------------------------------------------------------
SMT_CRUST_MAP_ROW = {crow}     ; the crust line's tilemap row
SMT_CRUST_TOP_PX  = {ctop}    ; ...in map pixels
SMT_MELT_BASE     = {mbase}    ; the flat control's value for a gap column
SMT_MELT_AMP      = {mamp}
SMT_VOFS_BG2      = {vbg2}    ; the fallback for a column with bit 14 clear —
                             ;   the plates' columns, where the melt is calm
"""


def main(argv):
    out = pathlib.Path(argv[1] if len(argv) > 1 else "build/assets")
    out.mkdir(parents=True, exist_ok=True)

    tiles = PLATE_TILES + MELT_TILES
    chr_blob = b"".join(encode_4bpp(rows, name) for name, rows in tiles)
    (out / "smt_chr.bin").write_bytes(chr_blob)
    (out / "smt_pmap.bin").write_bytes(
        encode_words(plate_map(), "smt_pmap", COLS * MAP_ROWS))
    (out / "smt_mmap.bin").write_bytes(
        encode_words(melt_map(), "smt_mmap", COLS * MAP_ROWS))
    # ONE PALETTE BLOB, TWO CGRAM GROUPS. The two 16-word halves go to CGRAM
    # 0 and 32, which are not contiguous — but the BLOB is, and that is what
    # the uploader needs: a single base symbol plus a small positive byte
    # offset. Two separate blobs would leave the loader adding the difference
    # between two linker-placed symbols, and the allocator is free to order
    # them either way (it put the melt's first), so that difference can be
    # NEGATIVE and absolute-long indexed addressing would carry it into the
    # wrong bank.
    (out / "smt_pal.bin").write_bytes(
        encode_words(PAL_PLATE + PAL_MELT, "smt_pal", 32))
    (out / "smt_hrow.bin").write_bytes(h_row())

    col = col_table()
    assert len(col) == (PHASES + 1) * STRIDE, len(col)
    (out / "smt_col.bin").write_bytes(col)

    (out / "smt_art.inc").write_text(ART_INC.format(
        cols=COLS, phases=PHASES, flat=PHASES, rows=PHASES + 1,
        shift=PHASE_SHIFT, stride=STRIDE, tiles=len(tiles),
        prow=PLAT_MAP_ROW, ptop=PLAT_TOP_PX, pbase=PLAT_BASE, pamp=PLAT_AMP,
        pcount=len(PLATES), vbg1=0,
        platcols="\n".join(
            f"SMT_PLAT_{i}_COL     = {first}"
            f"{' ' * (5 - len(str(first)))}; ...and it is {w} columns wide"
            for i, (first, w) in enumerate(PLATES)),
        crow=CRUST_MAP_ROW, ctop=CRUST_TOP_PX, mbase=MELT_BASE, mamp=MELT_AMP,
        vbg2=MELT_BASE))

    print(f"smt_chr.bin  {len(chr_blob):6d} B  ({len(tiles)} tiles)")
    print(f"smt_pmap.bin   4096 B  (32x64 words, {len(PLATES)} plates)")
    print(f"smt_mmap.bin   4096 B  (32x64 words, crust at map row "
          f"{CRUST_MAP_ROW})")
    print(f"smt_pal.bin      64 B  (two 16-word groups: 0 and 2)")
    print(f"smt_hrow.bin  {COLS * 2:6d} B  (the H row: all zero, V-only table)")
    print(f"smt_col.bin  {len(col):6d} B  ({PHASES} phases + 1 flat control "
          f"x {STRIDE} B; {len(GAPS)} jets, {len(PLATES)} plates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
