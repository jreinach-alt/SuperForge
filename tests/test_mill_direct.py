"""mill_direct — BG1's pixel bytes read as COLOUR, and the map word's three
dead bits made load-bearing.

WHAT IS UNDER TEST. `direct_color` on `[[claims.video]]` composes CGWSEL bit 0
(docs/100 §3, docs/99 §4). With that bit set the PPU stops looking BG1's 8bpp
pixels up in CGRAM and builds a BGR555 word out of them directly —
`GetRgbColor`'s `if constexpr(bpp == 8 && directColorMode)` arm, Mesen2
SnesPpu.cpp:1071-1076 — from the pixel AND from the tilemap entry's three-bit
palette field, which the very next line of the same function says is IGNORED in
the indexed case (:1077).

So the claim has two halves and only one of them is easy to see:

  * the pixel is the colour, 3-3-2 with blue in the top two bits;
  * the MAP WORD supplies the low bit of each channel.

A test that only checked the first would pass on a build whose tilemaps carry
no palette field at all — the picture would still be recognisable and every
colour would be one step dark in up to three channels. So the palette half gets
cases of its own: one that counts the pixels where the field CHANGES the colour
and refuses a 3-3-2-only prediction at every one of them, and one that finds two
tiles with BYTE-IDENTICAL CHR and different fields on screen at the same time
and requires them to render as different colours.

THE ORACLE IS VRAM, NOT THE GENERATOR. Every expected colour is computed from
the CHR byte and the tilemap word THE PPU ACTUALLY READ, fetched out of the
emulated VRAM. Importing `tools/gen_mill_direct.py` would compare the picture
against the quantiser that authored it, which agrees with itself by
construction — the failure mode `docs/100` §13.3 already records once on this
rail.

THE OBSERVATION IS THE SCREENSHOT. Nothing here asserts on a DP variable that
stands in for the picture. The two DP reads that do appear — the published
camera, and the scene id — are there to know WHICH map row the oracle joins
against and to drive the machine to a named state, which is `test_mill.py`'s
own rule.

AND THERE IS A CONTROL, which is the point of building a variant ROM rather
than a mode. `build/mill.sfc` is the same rail, the same geometry, the same
tile indices and one declaration different, so running the identical assertion
against it must find NOTHING. A predicate that matched both ROMs would be
measuring the art rather than the mechanism.

WHY THE MAPS ARE READ IN A FIXTURE and not at module scope: the variant's
manifest is DERIVED at build time (`tools/build_mill_direct.sh` — one token
different from `game/mill/game.toml`), so registering `build/mild` in
`conftest.MAPS` would point the freshness guard, whose contract is "the
committed map still equals what today's DECLARATIONS produce", at a build
artifact. `test_the_two_builds_allocate_one_map` is the check that replaces it,
and it is stronger for this purpose: it requires the variant's whole allocation
to be the shipping rail's, placement for placement.

LOCKSTEP-NATIVE: `Machine` only, absolute frames, no wall-clock surface.
"""
import collections
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
ROM_DC = BUILD / "mill_direct.sfc"
ROM_IX = BUILD / "mill.sfc"
ASSETS = BUILD / "assets"

sys.path.insert(0, str(SUPERFORGE / "vendor"))                   # noqa: E402
from machine import Machine, MemoryType                          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))         # noqa: E402
from frame_geometry import PICTURE_TOP                           # noqa: E402
import test_mill as mill              # the rail's own drive helpers  # noqa: E402

V = MemoryType.SnesVideoRam
O = MemoryType.SnesSpriteRam
W = MemoryType.SnesWorkRam

pytestmark = pytest.mark.skipif(
    not (ROM_DC.exists() and ROM_IX.exists()),
    reason="build/mill_direct.sfc + build/mill.sfc — run `make mill mill-direct`")

# The frame the lobby cases are photographed on. ABSOLUTE, because the picture
# IS the assertion (CLAUDE.md rule 2): the fade is in by 60 and this leaves
# margin, and every host photographs the same frame.
LOBBY_FRAME = 90

# Mesen hands back the picture one scanline LOW: screen row y renders map row
# y + 1 (`SnesPpu.cpp:186`, the first displayed scanline is 1). The rail emits
# the same fact as SMIL_SCANLINE_LEAD, and it is read rather than retyped.
SCANLINE_LEAD = None                 # filled from mil_art.inc below

# The widest OBJ box this rail uses. A sprite's pixels are not BG1's, so every
# on-screen sprite's box is EXCLUDED from the sampled population — deliberately
# over-excluding (the leaf is smaller than the rider), because a sample that is
# too small is a weaker test and a sample that includes OBJ pixels is a WRONG
# one. What is left is counted, and every case asserts a floor on it.
OBJ_BOX = 32


def _art(key):
    """One equate out of the GENERATED build/assets/mil_art.inc — the same
    reader `test_mill.py` uses, and for the same reason: a rail constant
    retyped here goes stale silently."""
    for line in (ASSETS / "mil_art.inc").read_text().splitlines():
        head, _, rest = line.partition("=")
        if head.strip() == key:
            return int(rest.split(";")[0].strip().replace("$", "0x"), 0)
    raise KeyError(f"{key} is not in mil_art.inc")


SCANLINE_LEAD = _art("SMIL_SCANLINE_LEAD")
FLOOR_Y = _art("SMIL_FLOOR_Y")
PIER_COLS = _art("SMIL_PIER_COLS")
COLS = _art("SMIL_COLS")
ROWS = _art("SMIL_ROWS")


# --------------------------------------------------------------------------
# the colour arithmetic — transcribed from Mesen2, never imported
# --------------------------------------------------------------------------
def direct_bgr555(pixel, pal):
    """The BGR555 word the PPU renders for (8bpp pixel, tilemap palette field).

    SnesPpu.cpp:1071-1076, regrouped per channel:

        R = ((pixel & 0x07) << 2) | ((pal & 1) << 1)
        G = (((pixel >> 3) & 0x07) << 2) | (pal & 2)
        B = (((pixel >> 6) & 0x03) << 3) | (pal & 4)

    Written out here rather than imported from `tools/gen_mill_direct.py`,
    which is the converter under test.
    """
    r = ((pixel & 0x07) << 2) | ((pal & 0x01) << 1)
    g = (((pixel >> 3) & 0x07) << 2) | (pal & 0x02)
    b = (((pixel >> 6) & 0x03) << 3) | (pal & 0x04)
    return r | (g << 5) | (b << 10)


def _rgb(word):
    """BGR555 -> the RGB triple Mesen writes into the PNG. BIT REPLICATION,
    `(c << 3) | (c >> 2)` — full-scale 31 must reach 255 (the skill file's
    capture fact 3; four other modules define the same expression)."""
    def f(c):
        return (c << 3) | (c >> 2)
    return (f(word & 31), f((word >> 5) & 31), f((word >> 10) & 31))


def _sym(symbols, name):
    for p in symbols["globals"]:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} is not in the emitted map — did the allocator "
                   f"move it?")


def _chr_pixel(chr_bytes, tile, x, y):
    """One pixel out of an 8bpp CHR page: four bitplane PAIRS, planes 0/1 then
    2/3 then 4/5 then 6/7, each pair interleaved by row."""
    base = tile * 64
    v = 0
    for pair in range(4):
        off = base + pair * 16 + y * 2
        lo, hi = chr_bytes[off], chr_bytes[off + 1]
        v |= ((lo >> (7 - x)) & 1) << (pair * 2)
        v |= ((hi >> (7 - x)) & 1) << (pair * 2 + 1)
    return v


def _obj_cover(oam):
    """Every screen pixel an on-screen sprite could reach, from OAM."""
    cov = set()
    for i in range(128):
        y = oam[i * 4 + 1]
        if y >= 224:                      # parked below the picture
            continue
        hi = oam[512 + i // 4]
        x = oam[i * 4] | (((hi >> ((i % 4) * 2)) & 1) << 8)
        if x >= 256:                      # X9 set: off the left edge
            x -= 512
        for dy in range(OBJ_BOX):
            for dx in range(OBJ_BOX):
                cov.add((x + dx, y + dy))
    return cov


# --------------------------------------------------------------------------
# the samples
# --------------------------------------------------------------------------
def _sample_lobby(rom, mapdir, tmp_path_factory, name):
    """Every BG1 pixel of the boot lobby ABOVE THE FLOOR, joined to the CHR
    byte and the map word the PPU read for it.

    ABOVE THE FLOOR is the region where nothing displaces a column: the lobby
    writes an offset row with no enable bit in it, and only the melt band below
    the deck reads a ripple row. Both layers' scrolls are at rest there
    (SMIL_BG1_REST), so screen (x, y) is map pixel (x, y + SMIL_SCANLINE_LEAD)
    and the join needs no state from the ROM at all.
    """
    symbols = json.loads((BUILD / mapdir / "symbol_map.json").read_text())
    s_map = _sym(symbols, "ES_V_MIL_LOBBY")
    s_chr = _sym(symbols, "ES_V_MIL_CHR1")
    png = tmp_path_factory.mktemp(name) / "lobby.png"
    with Machine(str(rom)) as m:
        m.advance(LOBBY_FRAME)
        m.screenshot(str(png))
        tmap = m.read_bytes(V, s_map["start"] * 2, s_map["size"] * 2)
        chr1 = m.read_bytes(V, s_chr["start"] * 2, s_chr["size"] * 2)
        oam = m.read_bytes(O, 0, 544)
    im = Image.open(png).convert("RGB")
    cov = _obj_cover(oam)
    out = []
    for y in range(FLOOR_Y):
        for x in range(256):
            if (x, y) in cov:
                continue
            wy = y + SCANLINE_LEAD
            cell = (wy // 8) * COLS + x // 8
            word = tmap[cell * 2] | (tmap[cell * 2 + 1] << 8)
            tile, pal = word & 0x3FF, (word >> 10) & 7
            v = _chr_pixel(chr1, tile, x % 8, wy % 8)
            if v == 0:                    # pixel 0 is transparent (:1047)
                continue
            out.append((x, y, tile, pal, v, im.getpixel((x, y + PICTURE_TOP))))
    return out, tmap


@pytest.fixture(scope="module")
def direct_lobby(tmp_path_factory):
    return _sample_lobby(ROM_DC, "mild", tmp_path_factory, "dc")


@pytest.fixture(scope="module")
def indexed_lobby(tmp_path_factory):
    return _sample_lobby(ROM_IX, "mil", tmp_path_factory, "ix")


@pytest.fixture(scope="module")
def direct_pier(tmp_path_factory):
    """The hall's BUTTRESS column, joined the same way.

    SCREEN COLUMN 0 IS THE ONE THE TABLE CANNOT REACH — the PPU clears the
    offset latches at the start of each scanline's fetch (SnesPpu.cpp:284-287),
    which is why the rail draws masonry there — so it is the one part of the
    hall whose join needs no offset word. Its vertical position does need the
    camera, and `ES_MIL_CAM_SHOWN` is what the rail publishes for exactly that:
    the camera the NMI drew this picture from, so the oracle joins on what was
    drawn rather than on what the main thread will advance to next.
    """
    symbols = json.loads((BUILD / "mild" / "symbol_map.json").read_text())
    s_map = _sym(symbols, "ES_V_MIL_MAP1")
    s_chr = _sym(symbols, "ES_V_MIL_CHR1")
    png = tmp_path_factory.mktemp("pier") / "hall.png"
    with Machine(str(ROM_DC)) as m:
        mill.to_hall(m)
        cam = m.read_u16(W, mill.DP_CAM)
        m.screenshot(str(png))
        tmap = m.read_bytes(V, s_map["start"] * 2, s_map["size"] * 2)
        chr1 = m.read_bytes(V, s_chr["start"] * 2, s_chr["size"] * 2)
    im = Image.open(png).convert("RGB")
    out = []
    for y in range(224):
        for x in range(PIER_COLS * 8):
            wy = (y + SCANLINE_LEAD + cam) % (ROWS * 8)
            cell = (wy // 8) * COLS + x // 8
            word = tmap[cell * 2] | (tmap[cell * 2 + 1] << 8)
            tile, pal = word & 0x3FF, (word >> 10) & 7
            v = _chr_pixel(chr1, tile, x % 8, wy % 8)
            if v == 0:
                continue
            out.append((x, y, tile, pal, v, im.getpixel((x, y + PICTURE_TOP))))
    return out, chr1


# --------------------------------------------------------------------------
# the declaration, and that it is the ONLY thing that differs
# --------------------------------------------------------------------------
def test_the_two_builds_allocate_one_map():
    """Every placement identical; CGWSEL differing in bit 0 and nothing else.

    This is what makes the rendered comparison an argument. If the variant had
    moved a VRAM base, a DP byte or a channel, "the picture changed" would be
    a statement about the allocation and not about the declaration.
    """
    ix = json.loads((BUILD / "mil" / "symbol_map.json").read_text())
    dc = json.loads((BUILD / "mild" / "symbol_map.json").read_text())

    def placements(m):
        out = {}
        for p in m["globals"]:
            out[("global", p["sym"])] = (p["class"], p["start"], p["size"])
        for sid, sc in m["scenes"].items():
            for p in sc["placements"]:
                out[(sid, p["sym"])] = (p["class"], p["start"], p["size"])
        return out

    assert placements(dc) == placements(ix)
    assert dc["spaces"] == ix["spaces"]
    for sid in ix["scenes"]:
        a, b = ix["scenes"][sid]["screen_blend"], dc["scenes"][sid]["screen_blend"]
        assert a["direct_color"] is False and b["direct_color"] is True
        assert b["cgwsel"] == a["cgwsel"] | 0x01, sid
        assert b["cgwsel"] != a["cgwsel"], sid
        for k in ("tm", "ts", "cgadsub"):
            assert a[k] == b[k], (sid, k)
        assert (ix["scenes"][sid]["video_offset"]["bgmode"]
                == dc["scenes"][sid]["video_offset"]["bgmode"])


def test_the_two_builds_draw_the_same_tiles():
    """The variant re-COLOURS the picture; it does not re-draw it.

    The tile INDEX of every cell of BG1's lobby map must be identical in the
    two ROMs' VRAM, and the words must differ only in the palette field — dead
    in one build and the low bit of each channel in the other. Without this,
    "the colours changed" could be a different picture rather than the same one
    read by a different rule.
    """
    _, tm_dc = _lobby_map(ROM_DC, "mild")
    _, tm_ix = _lobby_map(ROM_IX, "mil")
    changed = 0
    for cell in range(ROWS * COLS):
        a = tm_ix[cell * 2] | (tm_ix[cell * 2 + 1] << 8)
        b = tm_dc[cell * 2] | (tm_dc[cell * 2 + 1] << 8)
        assert a & 0x3FF == b & 0x3FF, f"cell {cell}: tile index moved"
        assert a & ~0x1C00 & 0xFFFF == b & ~0x1C00 & 0xFFFF, (
            f"cell {cell}: a bit outside the palette field moved")
        if a != b:
            changed += 1
    # ...and the field is not uniformly zero in the variant, or the case above
    # would be satisfied by two identical maps.
    assert changed > 500, (
        f"only {changed} of {ROWS * COLS} map words carry a palette field the "
        f"indexed build does not — the variant's maps may not have been "
        f"rebuilt")


def _lobby_map(rom, mapdir):
    symbols = json.loads((BUILD / mapdir / "symbol_map.json").read_text())
    s_map = _sym(symbols, "ES_V_MIL_LOBBY")
    with Machine(str(rom)) as m:
        m.advance(LOBBY_FRAME)
        return symbols, m.read_bytes(V, s_map["start"] * 2, s_map["size"] * 2)


# --------------------------------------------------------------------------
# the picture
# --------------------------------------------------------------------------
def test_bg1_renders_the_direct_colour_expression(direct_lobby):
    """Every BG1 pixel on screen IS its own byte, read as colour.

    The population is every opaque BG1 pixel above the floor that no sprite
    box covers, and the expected colour of each comes from the CHR byte and
    the map word THE PPU READ. A single mismatch fails, and the floor on the
    count is what stops a sample that collapsed to nothing from reading green.
    """
    sample, _ = direct_lobby
    assert len(sample) > 20000, (
        f"only {len(sample)} opaque BG1 pixels sampled — the region, the "
        f"scroll assumption or the OBJ exclusion has moved")
    bad = [s for s in sample if _rgb(direct_bgr555(s[4], s[3])) != s[5]]
    assert not bad, (
        f"{len(bad)} of {len(sample)} BG1 pixels do not render the "
        f"direct-colour expression; first at (x={bad[0][0]}, y={bad[0][1]}) "
        f"tile {bad[0][2]} pal {bad[0][3]} pixel {bad[0][4]}: expected "
        f"{_rgb(direct_bgr555(bad[0][4], bad[0][3]))}, screen has {bad[0][5]}")


def test_the_indexed_build_renders_none_of_it(indexed_lobby):
    """The control, and the reason the variant is a ROM and not a mode.

    `build/mill.sfc` is the same rail with `direct_color` absent, so its BG1
    pixels are CGRAM indices and the identical predicate must match NOTHING.
    A predicate that matched both builds would be measuring the art.
    """
    sample, _ = indexed_lobby
    assert len(sample) > 20000, "the control's sample collapsed"
    hits = [s for s in sample if _rgb(direct_bgr555(s[4], s[3])) == s[5]]
    assert not hits, (
        f"{len(hits)} of {len(sample)} pixels of the INDEXED build match the "
        f"direct-colour expression — the two ROMs are not distinguishable by "
        f"this predicate, so it is not testing the mechanism")


# --------------------------------------------------------------------------
# ...and the half a 3-3-2-only test cannot see
# --------------------------------------------------------------------------
def test_the_tilemap_palette_field_is_load_bearing(direct_lobby):
    """The map word's three bits are the low bit of each channel.

    Restricted to the pixels where the field CHANGES the colour, and asserting
    the 3-3-2-only prediction is REFUTED at every one of them. A build whose
    tilemaps carried no palette field would still look like the hall and would
    still pass a test that only checked the pixel's own bits.
    """
    sample, _ = direct_lobby
    live = [s for s in sample
            if direct_bgr555(s[4], s[3]) != direct_bgr555(s[4], 0)]
    assert len(live) > 5000, (
        f"only {len(live)} of {len(sample)} sampled pixels have a palette "
        f"field that changes their colour — this case would be nearly vacuous")
    wrong = [s for s in live if _rgb(direct_bgr555(s[4], 0)) == s[5]]
    assert not wrong, (
        f"{len(wrong)} of {len(live)} pixels match a prediction that IGNORES "
        f"the tilemap palette field, so the field is not reaching the picture")
    right = [s for s in live if _rgb(direct_bgr555(s[4], s[3])) == s[5]]
    assert len(right) == len(live)


# The eye's weighting, `tools/fit_mill_palette.py`'s WEIGHT — the same units
# the shipping palette was fitted under, so "how far apart are the two
# pictures" is measured the way "how far is this palette from the art" was.
WEIGHT = (2, 4, 1)

# What the 3-3-2 grid plus one bit a channel COSTS against 96 entries chosen
# for this picture, measured on this frame: mean 7.6, p95 15, worst 34. The
# bounds below are those numbers with room, and they are the quantiser's only
# oracle — the case above cannot see a quantiser defect at all, because its
# expected colour comes from the CHR byte the quantiser wrote.
MEAN_ERR_MAX = 12
TAIL_ERR_MAX = 24
TAIL_FRACTION = 0.95


def test_the_direct_build_is_the_same_picture(direct_lobby, indexed_lobby):
    """The variant is a RE-COLOURING, and this is what bounds how far it moved.

    Every case above is about the PPU's rule and takes its expected colour from
    the CHR byte the quantiser wrote — so a quantiser that chose badly, or
    truncated where it should have rounded, or fitted each tile to its WORST
    palette field, would leave every one of them green while the hall came out
    muddy. The oracle for that is the other ROM's own picture: the two builds
    draw the same tiles in the same places (asserted above), so the same screen
    pixel in each is the same intended colour twice, and the distance between
    them is exactly what direct colour cost.
    """
    dc, _ = direct_lobby
    ix, _ = indexed_lobby
    other = {(x, y): got for x, y, _t, _p, _v, got in ix}
    errs = []
    for x, y, _t, _p, _v, got in dc:
        ref = other.get((x, y))
        if ref is None:
            continue
        errs.append(sum(w * ((a >> 3) - (b >> 3)) ** 2
                        for w, a, b in zip(WEIGHT, got, ref)))
    assert len(errs) > 20000, "the paired sample collapsed"
    mean = sum(errs) / len(errs)
    within = sum(1 for e in errs if e <= TAIL_ERR_MAX) / len(errs)
    assert mean <= MEAN_ERR_MAX, (
        f"the direct-colour picture is {mean:.1f} weighted units from the "
        f"indexed one on average (bound {MEAN_ERR_MAX}) — the quantiser is "
        f"choosing worse colours than the 3-3-2 grid forces it to")
    assert within >= TAIL_FRACTION, (
        f"only {within:.1%} of pixels are within {TAIL_ERR_MAX} of the "
        f"indexed build (bound {TAIL_FRACTION:.0%})")


def test_two_tiles_one_chr_two_fields_render_differently(direct_pier):
    """The same 64 CHR bytes under two palette fields, on screen at once.

    The strict form of the case above, and the one a per-pixel argument cannot
    quite make: two tiles whose CHR is byte-identical, drawn in the same frame
    with different map-word palette fields, must render as DIFFERENT COLOURS.
    Both tiles are in the hall's buttress — screen column 0, the column the
    offset table can never reach — so their pixels are locatable without an
    offset word.
    """
    sample, chr1 = direct_pier
    assert len(sample) > 500, "the buttress sample collapsed"

    # Group the on-screen tiles by their CHR bytes; keep the groups that carry
    # more than one palette field.
    fields = collections.defaultdict(set)
    for _x, _y, tile, pal, _v, _got in sample:
        fields[bytes(chr1[tile * 64:(tile + 1) * 64])].add((tile, pal))
    groups = [sorted(g) for g in fields.values() if len({p for _, p in g}) > 1]
    assert groups, ("no two on-screen tiles share their CHR bytes and differ "
                    "in their palette field — this frame cannot make the case")

    proved = 0
    for group in groups:
        by_tile = collections.defaultdict(dict)
        for x, y, tile, pal, v, got in sample:
            by_tile[(tile, pal)][(x % 8, y)] = (v, got)
        for i, (ta, pa) in enumerate(group):
            for tb, pb in group[i + 1:]:
                if pa == pb:
                    continue
                a, b = by_tile[(ta, pa)], by_tile[(tb, pb)]
                # The same intra-tile column, in each tile's own rows.
                for (xa, _ya), (va, ga) in a.items():
                    match = [(vb, gb) for (xb, _yb), (vb, gb) in b.items()
                             if xb == xa and vb == va]
                    if not match:
                        continue
                    vb, gb = match[0]
                    assert ga == _rgb(direct_bgr555(va, pa))
                    assert gb == _rgb(direct_bgr555(vb, pb))
                    if direct_bgr555(va, pa) != direct_bgr555(vb, pb):
                        assert ga != gb, (
                            f"tiles {ta} (pal {pa}) and {tb} (pal {pb}) have "
                            f"identical CHR and pixel value {va}, yet render "
                            f"the same colour {ga} — the palette field is not "
                            f"reaching the picture")
                        proved += 1
    assert proved, ("no pixel pair with identical CHR, identical value and "
                    "different fields produced a colour difference — the case "
                    "proved nothing")
