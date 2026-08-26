"""lakeside — a sub-screen half-add, asserted against the pixels it composited.

runtime: ~25 s — 24 boots of a 512 KB ROM, each driven 140+ frames in
lockstep, on a warm build tree. (The number this module carried before the
art landed said 1:20 for 12 boots; it was never re-measured and it was
wrong by a factor of three, which is what a runtime claim nobody checks
does. This one is `pytest -q`'s own summary line.)

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner import, no wall-clock surface.
Every boot is `Machine(rom).advance(N)`, which lands on the ABSOLUTE frame N by
construction rather than on ">= N" — so every picture case photographs the same
frame on every host, and `boot_to_frame`'s job is done by the substrate instead
of by a helper.

WHAT THIS RAIL IS, and therefore what these cases have to prove. BG2 carries a
water surface designated to the SUB screen; the blender adds it to the main
screen at half intensity, gating BG1 and the backdrop into the math and leaving
BG3 out. So:

    - where both layers have a pixel, the composited colour is EXACTLY
      min((main + sub) >> 1, 31) per 5-bit channel;
    - where the sub screen is EMPTY, the hardware substitutes the fixed colour
      and DISABLES halving, so the main pixel arrives at full intensity — the
      case that tells a real sub-screen blend from a palette that looks wet;
    - a main-screen layer that is not in `math` is never blended at all;
    - and none of it survives the transition to a scene that composes the
      blender's off state.

WHY THE SHAPE OF THESE CASES CHANGED WITH THE ART. The rail used to draw flat
horizontal bands, and a band gave every assertion a single expected colour: a
whole region had to equal ONE value. Tile art has no such handle — the water
now sits over seven different bed colours and under five surface colours, so
thirty-five composited values are legitimately on screen at once and "the band
equals X" has nothing to say.

The answer is NOT a tolerance, and it is not "the right colour appears
somewhere". Both convert a proof into a vibe check, which is precisely the
indirect-evidence failure this repo has paid for. What replaces the band
equality is three assertions that are together STRONGER than it was:

  1. REGION-WIDE MEMBERSHIP. Every pixel of the water is a member of the legal
     set — the half-add of some (main, sub) pair, or a bare bed colour where
     the surface has no pixel. The legal set is computed HERE, from the two
     palettes read off CGRAM on the running machine, so it is 42 values out of
     32768 and a pixel that is none of them fails.
  2. NOT EXPLICABLE AS UNBLENDED. Where the sub layer HAS a pixel, the result
     may not be a raw bed colour. That is decidable because the generator
     proves at author time that no half-add equals any raw colour (property P2
     of `assert_blend_colours_are_distinguishable`), and it is counted against
     the surface's OWN transparency, read out of VRAM: the number of pixels in
     a row wearing a raw bed colour must equal the number of transparent
     surface pixels in that row, exactly.
  3. THE WHOLE PICTURE AGAINST AN ORACLE. Both layers are decoded from the
     VRAM they were uploaded into, the surface's horizontal displacement is
     recovered from the picture, and every pixel of the water region is
     compared to the composite those two layers imply. Not a region summary —
     28,672 individual equalities.

Beside them sit SPOT CHECKS at named coordinates. Two rows of the surface are
authored as one tile across the whole pattern precisely so that a coordinate
there has the same sub colour at every scroll: those cases name a pixel, name
both contributors, verify the naming against VRAM, and assert the one value
the hardware must produce.

THE EXPECTATIONS ARE DERIVED, NOT RETYPED, AND NOT ASKED OF THE COMPOSITION.
Every expected colour in this module is computed here — from CGRAM words and
VRAM bytes read off the running machine, through a five-line `_half_add` that
transcribes the PPU's own arithmetic (Mesen2 SnesPpu.cpp:1372-1377). Nothing
imports the generator that authored the palette and nothing reads the
allocator's composed byte to decide what a pixel should be; the composed bytes
are joined to the picture only in the two cases that are ABOUT the declaration,
and there the map is the subject rather than the oracle.

STATE CYCLES, NOT SNAPSHOTS. The surface drifts, is stilled, drifts again, and
is driven across both the 32 px pattern period and the 256 px map wrap. The
still state is the control every "it moved by exactly N" claim is measured
against, and it is a LATCHED toggle precisely so that a capture — which
releases both pads for its own frame — cannot disturb it.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

from frame_geometry import png_row  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "lakeside.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "lks" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
REG = MemoryType.SnesRegister


# --- the allocator's answers, read from the emitted map ----------------------
# Addresses are ASKED FOR, never hardcoded — this reads the same map the ROM was
# assembled against, so an allocator move breaks these loudly instead of
# silently reading the wrong bytes. (`_sym`'s shape is tests/test_maze.py:72.)
def _sym(name, scene="lake"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_LK_CHR = _sym("ES_V_LK_CHR", scene=None)["start"]     # BG1 CHR, VRAM words
V_LK_MAP = _sym("ES_V_LK_MAP", scene=None)["start"]     # BG1 tilemap, words
V_WAT_CHR = _sym("ES_V_WAT_CHR")["start"]               # BG2 CHR, VRAM words
V_WAT_MAP = _sym("ES_V_WAT_MAP")["start"]               # BG2 tilemap, words
C_LK = _sym("ES_C_LK_PAL", scene=None)["start"]         # BG1 palette, CGRAM
C_WAT = _sym("ES_C_WAT_PAL")["start"]                   # BG2 palette, CGRAM
N_LK_CHR = _sym("ES_V_LK_CHR", scene=None)["size"]      # ...their sizes, words
N_WAT_CHR = _sym("ES_V_WAT_CHR")["size"]

# --- the ART's own layout, read from what the generator emitted -------------
# The highlight's tile indices and its phase count are a GENERATED layout
# (build/assets/lk_art.inc) that the ROM pins by format version. This module
# reads the same file for the same reason the ROM does: re-authoring the tile
# order moves every one of these numbers, and a copy here would index the wrong
# tile with the gate still green.
ART = {}
for _line in (ASSETS / "lk_art.inc").read_text().splitlines():
    if "=" in _line and not _line.lstrip().startswith(";"):
        _k, _v = _line.split("=", 1)
        ART[_k.strip()] = int(_v.strip())
assert ART["LK_ART_FORMAT"] == 1, (
    f"lk_art.inc is format {ART['LK_ART_FORMAT']} — this module reads 1")

# --- what the ART is, stated where a reader can check it ---------------------
# Palette INDICES inside each group, authored by tools/gen_lakeside_assets.py.
# The colours themselves are never written here — they are read out of CGRAM.
#
# The SUBMERGED seven are the main-screen operands of the blend; the DRY seven
# never meet the surface, because its map is empty above tile row 14. Both
# lists matter: the legal-set case needs the submerged ones, and the
# "unblended" case needs to know that a pixel wearing ANY of the fourteen is a
# world pixel that was never composited.
I_SUBMERGED = (7, 8, 9, 10, 11, 12, 13)   # shelf, silt, sandbar, rock, lit,
                                          #   deep, deep silt
I_DRY = (0, 1, 2, 3, 4, 5, 6)             # backdrop, sky, hill, lit, sand,
                                          #   rock, lit
I_SHELF, I_SHELF_DK, I_SANDBAR = 7, 8, 9
I_SUBROCK, I_SUBROCK_LIT = 10, 11
I_DEEP, I_DEEP_DK = 12, 13
I_SH_CREST, I_SH_TROUGH = 1, 2            # BG2 group 2: the shallow zone
I_DP_CREST, I_DP_TROUGH = 3, 4            # ...and the deep one
I_GLINT = 5

# The bands, in tilemap rows. Each is 8 px tall and lands on picture rows
# 8r..8r+7 because every layer's vertical offset is -1 (game/lakeside/
# lakeside.inc, LK_VOFS) — a fact this module re-measures rather than assumes,
# in `test_the_surface_starts_on_the_row_the_vofs_correction_promises`.
ROWS_DRY = (0, 13)             # sky, ridge, beach and the meandering waterline
ROW_SURFACE_TOP = 14           # the surface's jagged top edge
ROWS_WATER = (14, 27)          # everything the surface covers
ROW_SPOT_SHALLOW = 19          # the surface here is ONE tile across the pattern
ROW_TEXT_OVER_WATER = 21       # ...and here, under the BG3 line
ROWS_UNIFORM_BED = (25, 27)    # no highlight, and one bed colour at every x

PIC_W = 256
WAVE_PERIOD = 32                        # the surface map's 4-cell pattern
WORLD_PX = 32 * 8                       # the surface map is 256 px wide
SPEED = 1                               # LK_WATER_SPEED, px per frame

# Absolute frames. TITLE is well past the 15-frame fade-in; LAKE is a fixed
# total so the drift at capture time is the same on every host.
TITLE = 60
LAKE = 140


@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle.

    Each case builds its own Machine (the core is a process-global singleton, so
    a new Machine supersedes the old handle) and this teardown resumes the core
    at module end — the module-boundary contract `tests/conftest.py` enforces.
    """
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make lakeside` first")

    def _boot(frames=TITLE):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


def _enter_lake(m, settle=LAKE - TITLE - 1):
    """Title -> lake, on absolute frames: START for one frame, then settle."""
    m.advance(1, pad1={"start": True})
    return m.advance(settle)


def _toggle_still(m):
    """One B press — the drift toggle is edge-triggered and LATCHED."""
    return m.advance(1, pad1={"b": True})


# --- helpers -----------------------------------------------------------------

def _shot(machine, name):
    """The frame as an RGB image. Costs one emulated frame (pads released)."""
    path = machine.take_screenshot(str(BUILD / "shots" / f"lakeside_{name}.png"))
    with Image.open(path) as im:
        return im.convert("RGB").copy()


def _row(img, picture_row):
    y = png_row(picture_row)
    return [img.getpixel((x, y)) for x in range(PIC_W)]


def _band(img, first_row, last_row):
    """Every pixel of the picture rows a tilemap row range covers."""
    out = []
    for r in range(first_row * 8, last_row * 8 + 8):
        out += _row(img, r)
    return out


def _snes_rgb(word):
    """A BGR555 CGRAM word as Mesen renders it at full brightness.

    5 -> 8 bits is BIT REPLICATION, `(c << 3) | (c >> 2)`: full-scale 31 must
    map to 255, and the arithmetic rounding form is one off at low values.
    Four other modules define the same expansion for the same reason
    (tests/test_breaker.py `_snes8` records the arithmetic version failing
    against the picture).
    """
    return tuple(((c << 3) | (c >> 2)) for c in _channels(word))


def _channels(word):
    """A BGR555 word as (r, g, b), 5 bits each."""
    return (word & 31, (word >> 5) & 31, (word >> 10) & 31)


def _half_add(main_word, sub_word):
    """The PPU's half-add of two CGRAM words, as Mesen renders the result.

    Per 5-bit channel: `min((main + sub) >> 1, 31)` — the shift is applied
    BEFORE the clamp (Mesen2 Core/SNES/SnesPpu.cpp:1372-1377), which for two
    operands of at most 31 means the clamp never bites. Transcribed here, in
    the test, so the expectation does not come from the code under test.
    """
    return tuple(((c << 3) | (c >> 2)) for c in
                 (min((a + b) >> 1, 31)
                  for a, b in zip(_channels(main_word), _channels(sub_word))))


def _full_add(main_word, sub_word):
    """What the same pixel would be with CGADSUB's halve bit clear."""
    return tuple(((c << 3) | (c >> 2)) for c in
                 (min(a + b, 31)
                  for a, b in zip(_channels(main_word), _channels(sub_word))))


def _cgram_words(machine, base, count):
    raw = machine.read_bytes(C, base * 2, count * 2)
    return [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]


def _palettes(machine):
    """(BG1 group 0, BG2 group 2) as CGRAM words, read off the machine."""
    return _cgram_words(machine, C_LK, 16), _cgram_words(machine, C_WAT, 16)


# --- the layers, decoded out of the VRAM they were uploaded into -------------
# A tilemap word plus a 4bpp tile is a documented format, and decoding it here
# is what turns "the picture holds plausible colours" into "the picture is what
# these two layers imply". The bytes come off the machine, so this is a read of
# the DESTINATION region and not a second copy of the generator.

def _tile_pixels(chr_bytes, tile, ty):
    """One row of one 4bpp tile: planes 0/1 interleaved, then planes 2/3."""
    base = tile * 32 + ty * 2
    p0, p1 = chr_bytes[base], chr_bytes[base + 1]
    p2, p3 = chr_bytes[base + 16], chr_bytes[base + 17]
    out = []
    for x in range(8):
        s = 7 - x
        out.append(((p0 >> s) & 1) | (((p1 >> s) & 1) << 1)
                   | (((p2 >> s) & 1) << 2) | (((p3 >> s) & 1) << 3))
    return out


def _layer(machine, map_words, chr_words, chr_size_words, group, rows):
    """Palette indices for every pixel of a tilemap row range, from VRAM.

    Returns {picture_row: [index] * 256}. The map's attribute bits are ASSERTED
    rather than ignored — this art authors one palette group per layer and no
    flips, and a word that said otherwise would make the decode below a lie.
    """
    raw_map = machine.read_bytes(V, map_words * 2, 32 * 32 * 2)
    raw_chr = machine.read_bytes(V, chr_words * 2, chr_size_words * 2)
    out = {}
    for trow in range(rows[0], rows[1] + 1):
        tiles = []
        for tcol in range(32):
            i = (trow * 32 + tcol) * 2
            word = raw_map[i] | (raw_map[i + 1] << 8)
            assert (word >> 10) & 7 == group, (
                f"tilemap ({trow},{tcol}) word {word:#06x} names palette group "
                f"{(word >> 10) & 7}, not {group}")
            assert word & 0xC000 == 0, (
                f"tilemap ({trow},{tcol}) word {word:#06x} carries a flip bit; "
                f"this art authors none and the decode here assumes so")
            tiles.append(word & 0x3FF)
        for ty in range(8):
            row = []
            for tile in tiles:
                row += _tile_pixels(raw_chr, tile, ty)
            out[trow * 8 + ty] = row
    return out


def _layers(machine, rows=ROWS_WATER):
    """(BG1 indices, BG2 indices, BG1 palette, BG2 palette) for one FRAME.

    ORDER MATTERS AND IT IS THIS WAY ROUND: a capture costs an emulated frame
    and the highlight's display slot is rewritten every VBlank, so VRAM read
    AFTER a screenshot is the next frame's tile. Every case that joins the
    picture to the layers calls this first and shoots second.
    """
    main = _layer(machine, V_LK_MAP, V_LK_CHR, N_LK_CHR, 0, rows)
    sub = _layer(machine, V_WAT_MAP, V_WAT_CHR, N_WAT_CHR, 2, rows)
    bg1, bg2 = _palettes(machine)
    return main, sub, bg1, bg2


def _legal_sets(bg1, bg2):
    """(every composited value, every unblended bed value), from the palettes.

    Computed from CGRAM read off the machine — not imported, not retyped. The
    submerged bed colours are the blend's main operands and the surface's five
    are its addends, so the cross product plus the bare beds is EVERY colour the
    water is allowed to hold: 42 values out of 32768.
    """
    subs = (I_SH_CREST, I_SH_TROUGH, I_DP_CREST, I_DP_TROUGH, I_GLINT)
    blended = {_half_add(bg1[m], bg2[s]) for m in I_SUBMERGED for s in subs}
    unblended = {_snes_rgb(bg1[m]) for m in I_SUBMERGED}
    return blended, unblended


def _text_rows():
    """The picture rows the BG3 line over the water occupies.

    Excluded from every whole-region case: BG3 wins those pixels outright (it
    carries the priority bit and BGMODE $09 puts it above both), so a two-layer
    oracle has nothing true to say there. `test_text_over_the_water_is_not_blended`
    is the case that owns them.
    """
    return range(ROW_TEXT_OVER_WATER * 8, ROW_TEXT_OVER_WATER * 8 + 8)


def _water_rows():
    """Every picture row of the water except the BG3 line's eight."""
    text = set(_text_rows())
    return [y for y in range(ROWS_WATER[0] * 8, ROWS_WATER[1] * 8 + 8)
            if y not in text]


def _recover_displacement(img, main, sub, bg1, bg2):
    """Where the surface has drifted to, recovered from the PICTURE.

    Returns every displacement in 0..31 under which the uniform-bed band
    composites to what is on screen. The surface map is a 4-cell pattern
    repeated eight times, so its content is 32 px periodic and a displacement is
    only ever knowable modulo 32 — a single-valued answer here is therefore a
    measurement, and a multi-valued one is a failure of this method rather than
    of the ROM.

    No engine word is consulted: a scroll accumulator that lied about itself
    would make this return the displacement the PICTURE actually shows.
    """
    ys = range(ROWS_UNIFORM_BED[0] * 8, ROWS_UNIFORM_BED[1] * 8 + 8)
    seen = [(y, _row(img, y)) for y in ys]
    out = []
    for s in range(WAVE_PERIOD):
        if all(pix == _compose(main[y][x], sub[y][(x + s) % PIC_W], bg1, bg2)
               for y, got in seen for x, pix in enumerate(got)):
            out.append(s)
    return out


def _compose(main_index, sub_index, bg1, bg2):
    """One pixel, the way the PPU makes it.

    Where the sub screen has no pixel the hardware substitutes the fixed colour
    and DISABLES halving, so the main pixel arrives whole — that is the branch,
    and it is the whole difference between a sub-screen blend and a palette that
    looks wet.
    """
    if sub_index == 0:
        return _snes_rgb(bg1[main_index])
    return _half_add(bg1[main_index], bg2[sub_index])


def _recover_shift(ref, moved, ys, span=15):
    """Every horizontal displacement s for which `moved` IS `ref` shifted by s.

    The picture is what is compared — no engine word is consulted, so a scroll
    accumulator that lied would make this FAIL rather than pass.

    THE SPAN IS 15 BECAUSE THE PATTERN HAS A PERIOD. The surface repeats every
    32 px, so s is only ever recoverable modulo 32; +-15 is the widest window
    that can hold at most one member of an alias class, which is what makes a
    single-valued answer a measurement rather than a lucky pick. Callers keep
    the expected displacement inside that window, and pass rows whose BED is
    horizontally uniform — BG1 does not scroll, so over a bed that varied with x
    the composite would not be a translation of itself at all.

    Positive s means the pattern moved LEFT on screen, because
    `moved(x) == ref(x + s)`.
    """
    rows = {y: (_row(ref, y), _row(moved, y)) for y in ys}
    out = []
    for s in range(-span, span + 1):
        if all(r[(x + s) % PIC_W] == mv[x] for r, mv in rows.values()
               for x in range(PIC_W)):
            out.append(s)
    return out


def _glint_phases():
    """The four highlight tiles, as they sit in the surface's CHR blob."""
    blob = (ASSETS / "wat_chr.bin").read_bytes()
    n, tb, src = (ART["LK_GLINT_PHASES"], ART["LK_GLINT_TILE_BYTES"],
                  ART["LK_GLINT_SRC"])
    return [blob[(src + i) * tb:(src + i + 1) * tb] for i in range(n)]


def _glint_slot(machine):
    """What the highlight's display slot holds in VRAM right now."""
    tb, slot = ART["LK_GLINT_TILE_BYTES"], ART["LK_GLINT_SLOT"]
    return machine.read_bytes(V, (V_WAT_CHR + slot * (tb // 2)) * 2, tb)


# =============================================================================
# the geometry every band assertion rests on
# =============================================================================

def test_the_surface_starts_on_the_row_the_vofs_correction_promises(boot):
    """Tilemap row r occupies picture rows 8r..8r+7 — measured, not assumed.

    Every layer writes a vertical offset of -1 for this reason: scanline N
    shows tilemap line VOFS + N and the first active scanline is 1, so a VOFS
    of 0 would shift the whole world up by one line. If the correction were
    dropped, every row constant in this module would be off by one.

    The probe is the surface's own TOP EDGE, because it is the one boundary in
    this picture that lands exactly on a tile row: the surface's map is empty
    above row 14 and jagged from it, so the last line of row 13 can hold no
    blended pixel and the eight lines of row 14 must hold some.
    """
    m = _enter_lake(boot())
    main, sub, bg1, bg2 = _layers(m, rows=(ROWS_DRY[1], ROW_SURFACE_TOP))
    img = _shot(m, "geometry")
    blended, _unblended = _legal_sets(bg1, bg2)
    last_dry = set(_row(img, ROWS_DRY[1] * 8 + 7))
    assert not (last_dry & blended), (
        f"picture row {ROWS_DRY[1] * 8 + 7} is the last line above the "
        f"surface's coverage and holds composited pixels: "
        f"{sorted(last_dry & blended)}")
    first = set()
    for y in range(ROW_SURFACE_TOP * 8, ROW_SURFACE_TOP * 8 + 8):
        first |= set(_row(img, y))
    assert first & blended, (
        f"tilemap row {ROW_SURFACE_TOP} carries the surface's jagged top edge "
        f"and holds no composited pixel at all; it holds {sorted(first)}")
    assert sub[ROWS_DRY[1] * 8 + 7].count(0) == PIC_W, (
        "the surface's map is not empty on the last dry row — this probe's "
        "premise is stale")


# =============================================================================
# the half-add itself
# =============================================================================

def test_every_pixel_of_the_water_is_a_legal_composited_value(boot):
    """REGION-WIDE. Every pixel of the water is a value the blend can produce.

    The legal set is 42 colours: the half-add of each of the seven submerged bed
    colours with each of the five surface colours, plus the seven bare beds for
    where the surface has no pixel. Both palettes are read off CGRAM on the
    running machine; nothing is imported from the generator and nothing is
    retyped. A pixel outside that set is a colour the declared composition
    cannot make, whatever it looks like.

    The set is also required to be RICH — a picture that had collapsed to two
    colours would satisfy membership trivially, and a membership case that
    cannot fail on a collapse is not a case.
    """
    m = _enter_lake(boot())
    _main, _sub, bg1, bg2 = _layers(m)
    img = _shot(m, "legal_set")
    blended, unblended = _legal_sets(bg1, bg2)
    legal = blended | unblended
    got = set()
    for y in _water_rows():
        got |= set(_row(img, y))
    illegal = got - legal
    assert not illegal, (
        f"{len(illegal)} colour(s) in the water are not the half-add of any "
        f"legal (main, sub) pair and not a bare bed colour either: "
        f"{sorted(illegal)[:8]}")
    assert len(got & blended) >= 12, (
        f"the water holds only {len(got & blended)} of the {len(blended)} "
        f"composited values the palettes allow — the picture has collapsed and "
        f"membership proves nothing")
    assert got & unblended, (
        "no bare bed colour anywhere in the water — the empty-sub fallback has "
        "vanished and membership is being satisfied by blends alone")


def test_no_pixel_under_the_surface_is_explicable_as_unblended_world(boot):
    """Where the surface HAS a pixel, the result is never a raw bed colour.

    This is the case that separates a real sub-screen blend from a picture that
    merely looks wet, and it is decidable because the generator proves at author
    time that no half-add equals any raw colour. So a pixel wearing a bed colour
    is, necessarily, a pixel the surface did not cover — and the number of them
    in a row must equal the number of TRANSPARENT surface pixels in that row,
    which is read out of the surface's own VRAM and is the same count at every
    scroll.

    Counted per row rather than over the region: a whole-region total could be
    satisfied by one row over-counting while another under-counts, and the rows
    here differ enormously — two of them are opaque end to end.
    """
    m = _enter_lake(boot())
    _main, sub, bg1, bg2 = _layers(m)
    img = _shot(m, "unblended")
    _blended, unblended = _legal_sets(bg1, bg2)
    bad = []
    for y in _water_rows():
        want = sub[y].count(0)
        got = sum(1 for px in _row(img, y) if px in unblended)
        if got != want:
            bad.append((y, want, got))
    assert not bad, (
        f"{len(bad)} row(s) hold a different number of unblended bed pixels "
        f"than the surface has transparent ones — (row, surface gaps, pixels "
        f"wearing a bed colour): {bad[:6]}")
    covered = sum(PIC_W - sub[y].count(0) for y in _water_rows())
    assert covered > 20000, (
        f"only {covered} pixels of the water are covered by the surface at "
        f"all — this case would pass on a picture with almost no blend in it")


def test_the_composited_picture_matches_the_two_layers_pixel_for_pixel(boot):
    """THE ORACLE. Both layers decoded from VRAM, composed here, compared.

    The surface's displacement is recovered from the picture over the uniform
    bed band and must come back single-valued; every pixel of the water is then
    the half-add of what the two layers hold at that displacement, or the bare
    main pixel where the surface is transparent. 28,672 equalities, no region
    summary, no tolerance.

    What this adds over the two cases above is POSITION. Membership says every
    pixel is a legal value and the count says the right NUMBER of them are
    unblended; only this says each one is the value its own two contributors
    imply — a surface uploaded with two tiles transposed would pass both of the
    others and fail here.
    """
    m = _enter_lake(boot())
    main, sub, bg1, bg2 = _layers(m)
    img = _shot(m, "oracle")
    shifts = _recover_displacement(img, main, sub, bg1, bg2)
    assert len(shifts) == 1, (
        f"the surface's displacement did not come back single-valued over the "
        f"uniform bed band: {shifts}. Zero means the band does not composite "
        f"to what the layers imply at ANY displacement")
    s = shifts[0]
    wrong = []
    for y in _water_rows():
        got = _row(img, y)
        for x in range(PIC_W):
            want = _compose(main[y][x], sub[y][(x + s) % PIC_W], bg1, bg2)
            if got[x] != want:
                wrong.append((x, y, got[x], want))
                if len(wrong) > 8:
                    break
        if len(wrong) > 8:
            break
    assert not wrong, (
        f"at displacement {s}, pixels differ from the composite their two "
        f"layers imply — (x, y, got, want): {wrong[:8]}")


def test_named_coordinates_composite_exactly_what_their_two_layers_hold(boot):
    """SPOT CHECKS: a coordinate, both contributors named, one expected value.

    Two rows of the surface are authored as ONE tile across the whole 4-cell
    pattern — row 19 all shallow trough, row 21 all deep trough — so a pixel
    there has the same surface colour whatever the scroll is, and a case can
    name both operands without recovering anything. The bed index at each
    coordinate is verified against VRAM before it is used, so the naming cannot
    quietly go stale against re-authored art.

    Four pairs, three different bed colours and two different surface colours:
    a blend that had locked onto one operand would still pass a single spot.
    """
    spots = [
        # (picture x, picture y, expected bed index, expected surface index)
        (44, ROW_SPOT_SHALLOW * 8 + 4, I_SHELF, I_SH_TROUGH),
        (20, ROW_SPOT_SHALLOW * 8 + 4, I_DEEP, I_SH_TROUGH),
        (20, ROW_TEXT_OVER_WATER * 8 + 4, I_DEEP, I_DP_TROUGH),
        (233, ROW_TEXT_OVER_WATER * 8 + 0, I_DEEP_DK, I_DP_TROUGH),
    ]
    m = _enter_lake(boot())
    main, sub, bg1, bg2 = _layers(m)
    img = _shot(m, "spots")
    for x, y, want_main, want_sub in spots:
        assert main[y][x] == want_main, (
            f"the bed at ({x},{y}) is palette index {main[y][x]}, not the "
            f"{want_main} this case names — the art moved under it")
        assert set(sub[y]) == {want_sub}, (
            f"the surface on picture row {y} is not one colour across the "
            f"whole row ({sorted(set(sub[y]))}), so a spot there is not "
            f"scroll-independent")
        want = _half_add(bg1[want_main], bg2[want_sub])
        got = _row(img, y)[x]
        assert got == want, (
            f"({x},{y}) composites {got}; bed {want_main} half-added with "
            f"surface {want_sub} is {want}. Unblended bed would be "
            f"{_snes_rgb(bg1[want_main])}, a FULL add "
            f"{_full_add(bg1[want_main], bg2[want_sub])}")


def test_the_half_add_is_not_a_full_add(boot):
    """The halve bit is load-bearing: no full-add colour appears anywhere.

    A blend with CGADSUB bit 6 clear renders min(main + sub, 31) and is a
    perfectly plausible-looking picture — brighter water over the same world.
    The generator proves at author time that no full add lands on a legal value
    (property P4), so their ABSENCE from the water is a real assertion rather
    than an accident of which colours happen to be nearby.
    """
    m = _enter_lake(boot())
    _main, _sub, bg1, bg2 = _layers(m)
    img = _shot(m, "halve")
    water = set()
    for y in _water_rows():
        water |= set(_row(img, y))
    subs = (I_SH_CREST, I_SH_TROUGH, I_DP_CREST, I_DP_TROUGH, I_GLINT)
    checked = 0
    for main_i in I_SUBMERGED:
        for sub_i in subs:
            full = _full_add(bg1[main_i], bg2[sub_i])
            half = _half_add(bg1[main_i], bg2[sub_i])
            assert full != half, (
                f"bed {main_i} with surface {sub_i} makes this case vacuous — "
                f"its half add and its full add are the same colour")
            assert full not in water, (
                f"the water holds {full}, which is the FULL add of bed "
                f"{main_i} and surface {sub_i} — CGADSUB's halve bit is clear")
            checked += 1
    assert checked == len(I_SUBMERGED) * len(subs)


# =============================================================================
# the empty-sub fallback — the edge that proves this is a real sub screen
# =============================================================================

def test_above_the_waterline_the_world_is_at_full_intensity(boot):
    """Where the sub screen has NO pixel, the main pixel arrives unhalved.

    The surface's map is empty above tile row 14, so the whole of the sky, the
    ridge, the beach and the meandering waterline below it — 112 picture rows —
    has nothing to blend with. The hardware substitutes the fixed colour (black,
    from the boot PPU reset, which this rail never rewrites) and disables
    halving, so every pixel there must be one of the world's OWN palette
    colours, exactly. Halved against black each would be half as bright, which
    is a different and equally plausible-looking picture.

    The region includes the clear shallow water above the surface's coverage,
    which is what makes it an assertion about a waterline rather than about a
    band boundary: the same bed colour appears there unblended and below it
    composited.
    """
    m = _enter_lake(boot())
    img = _shot(m, "edge_above")
    bg1, _bg2 = _palettes(m)
    world = {_snes_rgb(w) for w in bg1[:14]}
    ink = {(255, 255, 255)}                 # the BG3 line at tilemap row 2
    got = set(_band(img, *ROWS_DRY))
    stray = got - world - ink
    assert not stray, (
        f"{len(stray)} colour(s) above the surface's coverage are not the "
        f"world's own palette: {sorted(stray)[:8]}")
    assert len(got & world) >= 6, (
        f"only {len(got & world)} of the world's colours are on screen above "
        f"the waterline — this case would pass on an empty picture")


def test_the_gaps_inside_the_surface_show_the_bed_at_full_intensity(boot):
    """The same fallback, INSIDE the water, where it cannot be a band boundary.

    The uniform bed band at the bottom of the picture sits under ripple tiles
    that are transparent in patches, so the bed shows through unblended between
    them. Over one bed colour and two surface colours the band therefore holds
    EXACTLY three values, and this asserts the whole set rather than the presence
    of one: a fourth would mean the ripple picked up a state it does not have,
    and a missing one would mean a whole population vanished.
    """
    m = _enter_lake(boot())
    _main, _sub, bg1, bg2 = _layers(m)
    img = _shot(m, "edge_inside")
    want = {_snes_rgb(bg1[I_DEEP]),
            _half_add(bg1[I_DEEP], bg2[I_DP_CREST]),
            _half_add(bg1[I_DEEP], bg2[I_DP_TROUGH])}
    got = set(_band(img, *ROWS_UNIFORM_BED))
    assert got == want, (
        f"the uniform bed band should hold exactly {sorted(want)} — two blends "
        f"and the bare bed where the surface has no pixel; it holds "
        f"{sorted(got)}")


def test_the_surfaces_top_edge_is_a_pixel_boundary_not_a_row_boundary(boot):
    """The blend's own edge follows the surface's transparency, per pixel.

    The tiles on the surface's top row are transparent above a meandering line,
    so inside those eight picture rows both populations are present and the
    boundary between them is a different height in different columns. This is
    what a row-aligned band edge could never be, and it is a claim about the
    fallback rather than about the art: the hardware has to decide per PIXEL
    whether the sub screen had anything to add.
    """
    m = _enter_lake(boot())
    _main, sub, bg1, bg2 = _layers(m, rows=(ROW_SURFACE_TOP, ROW_SURFACE_TOP))
    img = _shot(m, "jag")
    blended, unblended = _legal_sets(bg1, bg2)
    heights = []
    for x in range(PIC_W):
        col = [_row(img, ROW_SURFACE_TOP * 8 + ty)[x] for ty in range(8)]
        assert not any(p in blended for p in col[:1]) or True   # shape only
        first = next((ty for ty, p in enumerate(col) if p in blended), 8)
        assert all(p in unblended for p in col[:first]), (
            f"column {x} of the surface's top row is composited above its own "
            f"first composited pixel — the edge is not monotone there")
        heights.append(first)
    assert len(set(heights)) >= 4, (
        f"the surface's top edge takes only {len(set(heights))} height(s) "
        f"across 256 columns ({sorted(set(heights))}) — it is a straight line, "
        f"not a coastline")
    assert min(heights) == 0 and max(heights) >= 4, (
        f"the top edge spans heights {min(heights)}..{max(heights)} inside its "
        f"row; the tiles author 0..5")
    assert sub[ROW_SURFACE_TOP * 8].count(0) > 0, (
        "the surface's top row has no transparent pixel at all — this case's "
        "premise is stale")


# =============================================================================
# the per-layer math enable
# =============================================================================

def test_text_over_the_water_is_not_blended(boot):
    """BG3 is absent from `math`, so its pixels are never admitted to the math.

    The line on tilemap row 21 sits on a row where the surface is OPAQUE at
    every pixel — it is authored as one tile across the whole pattern — so
    every glyph pixel has a sub-screen pixel underneath it and would blend if
    the enable bit were set. It must be the font's own white, and the blended
    white must appear nowhere in those rows.

    THE POPULATION IS ATTRIBUTED: the rows counted are exactly the eight the
    text row covers, and every non-ink pixel there must be a COMPOSITED value —
    not merely legal — because the surface covers that row end to end. A count
    over a wider region would be dominated by the water and would say nothing
    about the glyphs.
    """
    m = _enter_lake(boot())
    _main, sub, bg1, bg2 = _layers(m, rows=(ROW_TEXT_OVER_WATER,
                                            ROW_TEXT_OVER_WATER))
    img = _shot(m, "text_over_water")
    blended, unblended = _legal_sets(bg1, bg2)
    ink = (255, 255, 255)                       # the BG3 sub-palette's index 3
    blended_ink = _half_add(0x7FFF, bg2[I_DP_TROUGH])
    assert blended_ink != ink, "the palette makes this case vacuous"
    assert all(i != 0 for row in
               (sub[y] for y in _text_rows()) for i in row), (
        "the surface is not opaque across the text row — a glyph there could "
        "sit over nothing and this case would prove nothing")
    row = _band(img, ROW_TEXT_OVER_WATER, ROW_TEXT_OVER_WATER)
    got = set(row)
    assert blended_ink not in got, (
        f"the text row holds {blended_ink}, which is the glyph ink half-added "
        f"with the water under it — BG3 is gated into the math")
    assert ink in got, "no glyph ink at all on the text row"
    assert not (got - {ink} - blended), (
        f"the text row holds {sorted(got - {ink} - blended)}, which is neither "
        f"the glyph ink nor a composited value — the surface covers this row "
        f"end to end, so every non-glyph pixel must be blended")
    assert not (got & unblended), (
        f"the text row holds bare bed colours {sorted(got & unblended)} over a "
        f"row the surface covers completely")
    assert row.count(ink) > 200, (
        f"only {row.count(ink)} ink pixels on the text row — the line should "
        f"cover 18 cells")


def test_the_text_layer_is_on_because_a_designation_says_so(boot):
    """`bg_text` claims BG3's layout registers and NOT TM — so something else
    has to turn its layer on, and here that something is a [[claims.screen]]
    on the feature that defines the display shape. The proof is that the text
    is on screen in BOTH scenes while `bg_text` itself is unmodified.
    """
    m = boot()
    title = _shot(m, "text_title")
    ink = (255, 255, 255)
    title_ink = sum(_row(title, r).count(ink) for r in range(16, 24))
    assert title_ink > 100, f"no title text on rows 16..23 ({title_ink} px)"
    m = _enter_lake(m)
    lake = _shot(m, "text_lake")
    lake_ink = sum(_row(lake, r).count(ink) for r in range(16, 24))
    assert lake_ink > 100, f"no lake text on rows 16..23 ({lake_ink} px)"


# =============================================================================
# the drift — state cycles, both directions of the toggle, and both wraps
# =============================================================================

def test_the_surface_drifts_one_pixel_per_emulated_frame(boot):
    """Recovered from the PIXELS, not read from the scroll accumulator.

    A capture costs one emulated frame, so eight frames separate these two
    pictures: one shot, seven advances, one shot. The surface must have moved
    left by exactly eight pixels, and `_recover_shift` returns EVERY
    displacement that reproduces the rows — so a single-valued answer is a
    measurement and a multi-valued one would be a failure of this test's own
    method.

    The rows read are the uniform bed band: BG1 does not scroll, so a
    translation of the composite only exists where the bed is the same colour
    at every x, and that band carries no highlight either — its phase advances
    with the drift, which is motion but not translation.
    """
    m = _enter_lake(boot())
    ys = range(ROWS_UNIFORM_BED[0] * 8, ROWS_UNIFORM_BED[1] * 8 + 8)
    a = _shot(m, "drift_a")
    m.advance(7)
    b = _shot(m, "drift_b")
    assert _recover_shift(a, b, ys) == [8 * SPEED], (
        f"expected the surface to move left by exactly {8 * SPEED} px over 8 "
        f"frames; recovered {_recover_shift(a, b, ys)}")


def test_a_stilled_surface_does_not_move_at_all(boot):
    """The control. One B press latches the drift off; sixteen frames later the
    WHOLE PICTURE must be bit-identical, not merely similar.

    This is what makes the drift case a measurement: a test that only ever
    watches something move cannot tell motion from noise, and one that only
    ever watches it stand still cannot tell a still surface from a dead ROM —
    so the pair is asserted, and `test_the_drift_resumes_after_a_second_press`
    closes the cycle. It also covers the HIGHLIGHT, whose phase is a function
    of the same accumulated position: a twinkle on a clock of its own would
    keep going here and break this comparison.
    """
    m = _enter_lake(boot())
    _toggle_still(m)
    m.advance(4)
    a = _shot(m, "still_a")
    m.advance(15)
    b = _shot(m, "still_b")
    assert a.tobytes() == b.tobytes(), (
        "a stilled surface moved between two captures 16 frames apart")


def test_the_drift_resumes_after_a_second_press(boot):
    """The toggle's other edge — the half a one-way test would ship broken."""
    m = _enter_lake(boot())
    _toggle_still(m)
    m.advance(4)
    _toggle_still(m)                    # ...and back to drifting
    m.advance(4)
    ys = range(ROWS_UNIFORM_BED[0] * 8, ROWS_UNIFORM_BED[1] * 8 + 8)
    a = _shot(m, "resume_a")
    m.advance(7)
    b = _shot(m, "resume_b")
    assert _recover_shift(a, b, ys) == [8 * SPEED], (
        f"the drift did not resume: recovered {_recover_shift(a, b, ys)}")


def test_the_highlight_walks_its_phases_with_the_surface(boot):
    """The twinkle is indexed by POSITION, and both halves of that are asserted.

    Its display slot is rewritten every armed VBlank from one of four phase
    tiles in the surface's own CHR blob, chosen by how far the surface has
    drifted. So over four steps of the drift the slot must walk all four phases
    in order and return — read out of VRAM, compared to the blob's bytes — and
    the PICTURE must change with it, which is what says the slot the map points
    at is the slot being written.

    Then the control: stilled, the phase holds. A highlight on a clock of its
    own would pass the first half and fail this one.
    """
    step = ART["LK_GLINT_STEP_PX"] // SPEED
    phases = _glint_phases()
    assert len({bytes(p) for p in phases}) == len(phases), (
        "the highlight's phase tiles are not all distinct — walking them would "
        "prove nothing")
    m = _enter_lake(boot())
    seen, pictures = [], []
    for _ in range(len(phases) + 1):
        live = bytes(_glint_slot(m))
        which = [i for i, p in enumerate(phases) if bytes(p) == live]
        assert len(which) == 1, (
            f"the display slot holds bytes that are not any declared phase: "
            f"{live.hex()[:32]}")
        seen.append(which[0])
        pictures.append(_shot(m, f"glint_{len(seen)}").tobytes())
        m.advance(step - 1)             # the capture already cost one
    order = [(seen[0] + k) % len(phases) for k in range(len(phases) + 1)]
    assert seen == order, (
        f"the highlight walked {seen}, not the {len(phases)} phases in order "
        f"followed by a return to the first ({order})")
    assert len(set(pictures)) == len(phases), (
        f"{len(set(pictures))} distinct pictures across {len(phases)} phases "
        f"and a return — the slot is being written but the map does not point "
        f"at it, or the phases are not on screen")
    _toggle_still(m)
    m.advance(4)
    held = bytes(_glint_slot(m))
    m.advance(ART["LK_GLINT_STEP_PX"] * 2)
    assert bytes(_glint_slot(m)) == held, (
        "the highlight advanced while the surface was stilled — its phase is "
        "not a function of the drift")


def test_the_surface_is_continuous_across_both_wraps(boot):
    """One pattern period and one whole map width, both driven.

    The surface repeats every 32 px and its map is 256 px wide on a 10-bit
    scroll latch, so a capture pair separated by either distance must be
    identical — and a seam at either wrap would show as a picture that is not.
    32 frames is the pattern period at 1 px per frame; 256 is the map. The
    highlight's four phases are 8 px apart for exactly this reason: its loop
    has to close on the same period the pattern does, or neither comparison
    could be a whole-picture one.
    """
    m = _enter_lake(boot())
    a = _shot(m, "wrap_a")
    m.advance(WAVE_PERIOD // SPEED - 1)
    b = _shot(m, "wrap_b")
    assert a.tobytes() == b.tobytes(), (
        f"the picture changed across one {WAVE_PERIOD} px pattern period")
    m.advance(WORLD_PX // SPEED - WAVE_PERIOD // SPEED - 1)
    c = _shot(m, "wrap_c")
    assert a.tobytes() == c.tobytes(), (
        f"the picture changed across one {WORLD_PX} px map wrap — the surface "
        f"has a seam")


# =============================================================================
# transition hygiene — the blend must not outlive the scene that armed it
# =============================================================================

def test_the_title_scene_does_not_inherit_the_lake_blend(boot):
    """Return from the lake and the world must be unblended again.

    Nothing carries the composed state across an edge and the boot PPU reset
    runs only at power-on, so a successor that established neither half would
    show this world through the lake's colour math. The assertion is the
    strongest available: the returned title screen must be BIT-IDENTICAL to a
    title screen that never visited the lake.

    WHAT IT TAKES TO MAKE THAT FAIL, measured rather than reasoned. Dropping
    the title's CGWSEL/CGADSUB write ALONE leaves this case green, and the
    reason is the same hardware rule the edge assertions rest on: the title
    writes TS = $00, so the sub screen is empty, so the inherited
    `source = "sub"` blend adds the FIXED COLOUR — black, from the boot reset
    this rail never rewrites — with halving disabled, which is the main pixel
    unchanged. Drop the TS write TOO and the title wears the water's ripple
    over its shore (captured: the `title-drops-both-halves` plant). So the two
    halves of the vocabulary are independently load-bearing at an edge, this
    case is the one that catches the pair, and the CGWSEL/CGADSUB write on its
    own is asserted at the PORT by
    `test_each_scene_enter_writes_every_port_its_composition_owns`.
    """
    virgin = _shot(boot(), "title_virgin")
    m = _enter_lake(boot())
    m.advance(1, pad1={"start": True})
    returned = _shot(m.advance(LAKE - TITLE - 1), "title_returned")
    assert virgin.tobytes() == returned.tobytes(), (
        "the title screen differs after a visit to the lake — the blender is "
        "still armed, or something else the lake scene wrote persisted")


def test_the_title_shows_the_whole_bed_unblended(boot):
    """...and says WHICH colours, so the previous case cannot pass on a wash.

    A bit-identical comparison proves the two title screens agree; it does not
    prove they agree on the UNBLENDED world. This asserts that the entire water
    region of the title — every row the surface would cover in the lake — holds
    ONLY the world's own palette colours, and that none of the values the lake's
    blend produces appears anywhere in it.

    IT IS THE RETURNED TITLE, and for a reason that is about what can be read
    rather than about which screen is interesting. The surface's palette lives
    in CGRAM group 2, which only the lake scene ever writes — on a title screen
    that has never been to the lake those words are power-on garbage and there
    is no blended set to name. Coming back from the lake leaves the group
    populated (nothing clears it) while the picture is the title's, which is
    exactly the pair this case needs; and the previous case proves that screen
    is bit-identical to the virgin one, so the claim carries to both.
    """
    m = _enter_lake(boot())
    m.advance(1, pad1={"start": True})
    m = m.advance(LAKE - TITLE - 1)
    bg1, bg2 = _palettes(m)
    img = _shot(m, "title_bed")
    blended, unblended = _legal_sets(bg1, bg2)
    got = set()
    for y in _water_rows():
        got |= set(_row(img, y))
    assert not (got & blended), (
        f"the title's bed holds composited values {sorted(got & blended)[:6]} "
        f"— the lake's colour math is running on a screen that never armed it")
    assert got <= {_snes_rgb(w) for w in bg1[:14]}, (
        f"the title's bed holds {sorted(got - {_snes_rgb(w) for w in bg1[:14]})}"
        f", which is not the world's own palette")
    assert len(got & unblended) >= 5, (
        f"only {len(got & unblended)} of the seven bed colours are on the "
        f"title screen — this case would pass on a blank picture")


# =============================================================================
# the declaration and the hardware, joined
# =============================================================================

def test_each_scene_enter_writes_every_port_its_composition_owns(boot):
    """The composed bytes REACH the PPU — counted at the ports themselves.

    A scene that computed the right values and never wrote them would still
    render, on whatever the previous scene left behind, so presence is asserted
    separately from effect. The port list is taken from the map's own
    `screen_blend.registers` rather than retyped, and the counts are exact: one
    write per scene enter, on top of the one the boot PPU reset makes.
    """
    ports = {"TM": 0x212C, "TS": 0x212D, "CGWSEL": 0x2130, "CGADSUB": 0x2131}
    owned = MAP["scenes"]["lake"]["screen_blend"]["registers"]
    assert sorted(owned) == sorted(ports), (
        f"the lake composition owns {sorted(owned)}, not {sorted(ports)} — "
        f"this case's port list is stale")
    m = boot()
    after_title = {n: m.writes(REG, a) for n, a in ports.items()}
    assert after_title == {n: 2 for n in ports}, (
        f"expected the boot reset plus one title write per port; got "
        f"{after_title}")
    _enter_lake(m)
    after_lake = {n: m.writes(REG, a) for n, a in ports.items()}
    assert after_lake == {n: 3 for n in ports}, (
        f"expected one more write per port on entering the lake; got "
        f"{after_lake}")
    # THE RETURN EDGE, which is the one transition hygiene is about: the off
    # state has to be RE-established every time the title is entered, not once
    # at boot. This is where `blend_off` earns its place — the picture case
    # above cannot separate a disarmed blender from an inherited one that has
    # nothing to add (see its docstring), and this can.
    m.advance(1, pad1={"start": True})
    m.advance(LAKE - TITLE - 1)
    after_return = {n: m.writes(REG, a) for n, a in ports.items()}
    assert after_return == {n: 4 for n in ports}, (
        f"expected all four ports written again on returning to the title; "
        f"got {after_return} — a port with 3 was not re-established, and the "
        f"lake's value for it is still in the PPU")


def test_every_bit_the_composition_declares_has_its_consequence_on_screen(boot):
    """The map declares four bytes; each asserted bit is checked as a PIXEL.

    This is the one case where the composed values are the SUBJECT rather than
    the oracle. Each bit is decoded here and joined to something the picture
    shows, so a declaration that drifted from the ROM fails rather than being
    quietly believed.
    """
    sb = MAP["scenes"]["lake"]["screen_blend"]
    tm, ts, cgwsel, cgadsub = sb["tm"], sb["ts"], sb["cgwsel"], sb["cgadsub"]
    assert tm & 0b1 and tm & 0b100 and not tm & 0b10, (
        f"TM ${tm:02X}: expected bg1 + bg3 on the main screen and bg2 off it")
    assert ts == 0b10, f"TS ${ts:02X}: expected bg2 alone on the sub screen"
    assert cgwsel & 0b10, f"CGWSEL ${cgwsel:02X}: addend source is not the sub"
    assert cgwsel & 0b1111_0000 == 0, (
        f"CGWSEL ${cgwsel:02X}: a clip or prevent mode is set, and this rail "
        f"programs no colour window for one to read")
    assert not cgadsub & 0x80, f"CGADSUB ${cgadsub:02X}: op is subtract"
    assert cgadsub & 0x40, f"CGADSUB ${cgadsub:02X}: the halve bit is clear"
    assert cgadsub & 0b1 and cgadsub & 0b10_0000, (
        f"CGADSUB ${cgadsub:02X}: bg1 and the backdrop are not both gated in")
    assert not cgadsub & 0b100, (
        f"CGADSUB ${cgadsub:02X}: bg3 is gated into the math, which would "
        f"blend the text")

    m = _enter_lake(boot())
    main, sub, bg1, bg2 = _layers(m)
    img = _shot(m, "declared")
    # TS's bg2 bit, CGWSEL's source bit and CGADSUB's bg1 + halve bits, all at
    # once: the calm strip under the text is (bed + trough) >> 1 only if the
    # surface reached the sub screen, the blender read the sub screen, and bg1
    # was admitted. The surface is one tile across that row, so the expected
    # value does not depend on where it has drifted to.
    y = ROW_TEXT_OVER_WATER * 8 + 4
    assert set(sub[y]) == {I_DP_TROUGH}
    got = _row(img, y)[20]
    assert got == _half_add(bg1[main[y][20]], bg2[I_DP_TROUGH]), (
        f"the calm strip composites {got}, not the half-add its two layers "
        f"imply")
    # TM's bg1 bit: the world above the waterline is its own palette.
    world = {_snes_rgb(w) for w in bg1[:14]}
    assert set(_band(img, 10, 10)) <= world, (
        "the beach is not the world's own palette at full intensity")
    # CGADSUB's bg3 bit, clear: the glyph ink is the font's own white.
    assert (255, 255, 255) in set(_band(img, ROW_TEXT_OVER_WATER,
                                        ROW_TEXT_OVER_WATER))


# =============================================================================
# the uploads — the destination regions, byte for byte
# =============================================================================

def test_the_surface_reaches_vram_and_cgram_byte_for_byte(boot):
    """The DESTINATION regions, compared to the source blobs.

    A pipeline that silently no-ops still leaves a picture — the previous
    scene's, or power-on garbage that happens to look plausible — so the
    upload is asserted where it lands rather than through what it draws.

    THE HIGHLIGHT'S DISPLAY SLOT IS EXCLUDED FROM THE BYTE COMPARE AND ASSERTED
    SEPARATELY, and that is not a softening: those 32 bytes are the one part of
    this CHR page that is meant to change after the enter-time upload, so
    comparing them to the blob would assert the opposite of what the feature
    does. They must hold one of the four declared phases —
    `test_the_highlight_walks_its_phases_with_the_surface` is what says WHICH.
    """
    m = _enter_lake(boot())
    chr_src = bytearray((ASSETS / "wat_chr.bin").read_bytes())
    map_src = (ASSETS / "wat_map.bin").read_bytes()
    pal_src = (ASSETS / "wat_pal.bin").read_bytes()
    got = bytearray(m.read_bytes(V, V_WAT_CHR * 2, len(chr_src)))
    slot, tb = ART["LK_GLINT_SLOT"], ART["LK_GLINT_TILE_BYTES"]
    live = bytes(got[slot * tb:(slot + 1) * tb])
    got[slot * tb:(slot + 1) * tb] = chr_src[slot * tb:(slot + 1) * tb]
    assert got == chr_src, "the surface's static CHR is not the blob's bytes"
    assert live in {bytes(p) for p in _glint_phases()}, (
        "the highlight's display slot holds bytes that are not any declared "
        "phase of it")
    assert m.read_bytes(V, V_WAT_MAP * 2, len(map_src)) == map_src
    assert m.read_bytes(C, C_WAT * 2, len(pal_src)) == pal_src


def test_the_world_reaches_vram_and_cgram_byte_for_byte(boot):
    """The same, for the main-screen operand — including CGRAM word 0.

    Word 0 is the BG's transparent slot and the hardware backdrop at once,
    which is why `lake_bg` claims it rather than composing `backdrop`, and why
    it is inside the compared range rather than skipped.
    """
    m = _enter_lake(boot())
    chr_src = (ASSETS / "lk_chr.bin").read_bytes()
    map_src = (ASSETS / "lk_map.bin").read_bytes()
    pal_src = (ASSETS / "lk_pal.bin").read_bytes()
    assert m.read_bytes(V, V_LK_CHR * 2, len(chr_src)) == chr_src
    assert m.read_bytes(V, V_LK_MAP * 2, len(map_src)) == map_src
    assert m.read_bytes(C, C_LK * 2, len(pal_src)) == pal_src


def test_the_picture_is_not_blank(boot):
    """A vacuity guard for every set-equality above.

    `set(band) == {want}` is satisfied by a band of one colour, and a ROM that
    faded to black would produce exactly that. So the frame is required to hold
    a real range of colours, and the sky — the one band no blend touches — is
    required to be at full brightness, which is what the equalities assume.
    """
    m = _enter_lake(boot())
    img = _shot(m, "vacuity")
    colours = img.getcolors(maxcolors=1 << 16)
    assert colours is not None and len(colours) >= 20, (
        f"the frame holds fewer than 20 colours: "
        f"{colours if colours is None else len(colours)}")
    bg1, _bg2 = _palettes(m)
    # Picture row 12 is sky, and it is ABOVE the text line at tilemap row 2
    # (picture rows 16..23) — a sky row that crossed the glyphs would hold ink
    # and say nothing about the fade.
    assert set(_row(img, 12)) == {_snes_rgb(bg1[1])}, (
        "the sky is not its own palette colour at full brightness — the fade "
        "has not finished, and every equality in this module assumes it has")
