"""lakeside — a sub-screen half-add, asserted against the pixels it composited.

runtime: ~1:20 — 12 boots of a 512 KB ROM, each driven 140+ frames in lockstep.

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

THE EXPECTATIONS ARE DERIVED, NOT RETYPED, AND NOT ASKED OF THE COMPOSITION.
Every expected colour in this module is computed here — from CGRAM words read
off the running machine, through a five-line `_half_add` that transcribes the
PPU's own arithmetic (Mesen2 SnesPpu.cpp:1372-1377). Nothing imports the
generator that authored the palette and nothing reads the allocator's composed
byte to decide what a pixel should be; the composed bytes are joined to the
picture only in the two cases that are ABOUT the declaration, and there the map
is the subject rather than the oracle.

WHY AN EQUALITY AND NOT A TOLERANCE. The palettes are chosen so every colour
that can meet on screen produces a distinct answer, which makes `==` the honest
comparison: a tolerance would pass a half-add that had quietly become a full
add. The generator proves the distinctness property at author time
(`assert_blend_colours_are_distinguishable`); these cases spend it.

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

# --- what the ART is, stated where a reader can check it ---------------------
# Palette INDICES inside each group, authored by tools/gen_lakeside_assets.py.
# The colours themselves are never written here — they are read out of CGRAM.
I_BED_NEAR, I_BED_FAR = 5, 6            # BG1 group 0: the two lake-bed depths
I_ROCK, I_ROCK_LIT = 4, 7               # BG1 group 0: the shoreline band
I_CREST, I_TROUGH = 1, 2                # BG2 group 2: the surface's two faces

# The bands, in tilemap rows. Each is 8 px tall and lands on picture rows
# 8r..8r+7 because every layer's vertical offset is -1 (game/lakeside/
# lakeside.inc, LK_VOFS) — a fact this module re-measures rather than assumes,
# in `test_a_world_row_lands_on_the_picture_rows_the_vofs_correction_promises`.
ROW_ROCK = 13                           # the shoreline: BG2 has NO pixel here
ROWS_CREST_BAND = (14, 16)              # BG2 all crest: blend at every x
ROWS_WAVE_NEAR = (17, 19)               # BG2 ripple over the near shelf
ROWS_TROUGH_BAND = (20, 22)             # BG2 all trough: blend at every x
ROWS_WAVE_FAR = (23, 27)                # BG2 ripple over the deep water
ROW_TEXT_OVER_WATER = 21                # the BG3 line inside the trough band

PIC_W = 256
WAVE_PERIOD = 32                        # 8 px crest + 8 px trough + 16 px gap
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


def _cgram_words(machine, base, count):
    raw = machine.read_bytes(C, base * 2, count * 2)
    return [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]


def _palettes(machine):
    """(BG1 group 0, BG2 group 2) as CGRAM words, read off the machine."""
    return _cgram_words(machine, C_LK, 16), _cgram_words(machine, C_WAT, 16)


def _recover_shift(ref, moved, ys, span=15):
    """Every horizontal displacement s for which `moved` IS `ref` shifted by s.

    The picture is what is compared — no engine word is consulted, so a scroll
    accumulator that lied would make this FAIL rather than pass.

    THE SPAN IS 15 BECAUSE THE PATTERN HAS A PERIOD. The ripple repeats every
    32 px, so s is only ever recoverable modulo 32; +-15 is the widest window
    that can hold at most one member of an alias class, which is what makes a
    single-valued answer a measurement rather than a lucky pick. Callers keep
    the expected displacement inside that window.

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


# =============================================================================
# the geometry every band assertion rests on
# =============================================================================

def test_a_world_row_lands_on_the_picture_rows_the_vofs_correction_promises(boot):
    """Tilemap row r occupies picture rows 8r..8r+7 — measured, not assumed.

    Every layer writes a vertical offset of -1 for this reason: scanline N
    shows tilemap line VOFS + N and the first active scanline is 1, so a VOFS
    of 0 would shift the whole world up by one line. If the correction were
    dropped every band constant in this module would be off by one, so the
    boundary is re-measured here instead of being inherited from prose.
    """
    m = _enter_lake(boot())
    img = _shot(m, "geometry")
    _bg1, _bg2 = _palettes(m)
    last_dry = set(_row(img, ROW_ROCK * 8 + 7))
    first_wet = set(_row(img, (ROW_ROCK + 1) * 8))
    rock = {_snes_rgb(_bg1[I_ROCK]), _snes_rgb(_bg1[I_ROCK_LIT])}
    assert last_dry <= rock, (
        f"picture row {ROW_ROCK * 8 + 7} should be the last line of the rock "
        f"band; it holds {sorted(last_dry)}")
    assert not (first_wet & rock), (
        f"picture row {(ROW_ROCK + 1) * 8} should be the first line under "
        f"water; it still holds rock: {sorted(first_wet & rock)}")


# =============================================================================
# the half-add itself
# =============================================================================

def test_the_crest_band_is_the_exact_half_add_of_bed_and_crest(boot):
    """Every pixel of a band where BOTH layers are opaque is (main+sub)>>1.

    The surface's map rows 14..16 are all crest, so this band is opaque on the
    sub screen at every horizontal scroll — which is what makes an equality at
    EVERY x, on any frame, the right assertion rather than a spot check.
    """
    m = _enter_lake(boot())
    img = _shot(m, "crest_band")
    bg1, bg2 = _palettes(m)
    want = _half_add(bg1[I_BED_NEAR], bg2[I_CREST])
    got = set(_band(img, *ROWS_CREST_BAND))
    assert got == {want}, (
        f"the crest band should be exactly {want} everywhere; it holds "
        f"{sorted(got)}. Unblended near bed would be "
        f"{_snes_rgb(bg1[I_BED_NEAR])}, a FULL add "
        f"{_full_add(bg1[I_BED_NEAR], bg2[I_CREST])}")


def test_the_trough_band_is_the_exact_half_add_of_deep_bed_and_trough(boot):
    """The second equality, on a different main operand and a different sub one.

    Two independent pairs matter: a single band could be reproduced by a
    coincidence in one palette entry, and two cannot — the deep bed and the
    trough share no channel value with the near bed and the crest.

    The BG3 line sits on row 21, inside this band, so the rows it occupies are
    excluded here and asserted on their own in
    `test_text_over_the_water_is_not_blended`.
    """
    m = _enter_lake(boot())
    img = _shot(m, "trough_band")
    bg1, bg2 = _palettes(m)
    want = _half_add(bg1[I_BED_FAR], bg2[I_TROUGH])
    got = set(_band(img, ROWS_TROUGH_BAND[0], ROW_TEXT_OVER_WATER - 1))
    got |= set(_band(img, ROW_TEXT_OVER_WATER + 1, ROWS_TROUGH_BAND[1]))
    assert got == {want}, (
        f"the trough band should be exactly {want} everywhere; it holds "
        f"{sorted(got)}")


def _full_add(main_word, sub_word):
    """What the same pixel would be with CGADSUB's halve bit clear."""
    return tuple(((c << 3) | (c >> 2)) for c in
                 (min(a + b, 31)
                  for a, b in zip(_channels(main_word), _channels(sub_word))))


def test_the_half_add_is_not_a_full_add(boot):
    """The halve bit is load-bearing: the full-add colour appears NOWHERE.

    A blend with CGADSUB bit 6 clear renders min(main + sub, 31) and is a
    perfectly plausible-looking picture — brighter water over the same world.
    This case is what separates the two, and it is the assertion the
    `cgadsub_half` falsification plant kills.
    """
    m = _enter_lake(boot())
    img = _shot(m, "halve")
    bg1, bg2 = _palettes(m)
    band = set(_band(img, *ROWS_CREST_BAND)) | set(_band(img, *ROWS_WAVE_NEAR))
    for main_i in (I_BED_NEAR, I_BED_FAR):
        for sub_i in (I_CREST, I_TROUGH):
            full = _full_add(bg1[main_i], bg2[sub_i])
            half = _half_add(bg1[main_i], bg2[sub_i])
            assert full != half, "the palette makes this case vacuous"
            assert full not in band, (
                f"the water band holds {full}, which is the FULL add of "
                f"palette {main_i} and {sub_i} — CGADSUB's halve bit is clear")


# =============================================================================
# the empty-sub fallback — the edge that proves this is a real sub screen
# =============================================================================

def test_above_the_waterline_the_world_is_at_full_intensity(boot):
    """Where the sub screen has NO pixel, the main pixel arrives unhalved.

    The surface's map is empty above row 14, so the rock shoreline at row 13
    has nothing to blend with. The hardware substitutes the fixed colour —
    black, from the boot PPU reset, which this rail never rewrites — and
    disables halving, so the band must be its own CGRAM colours EXACTLY. Halved
    against black it would be half as bright, which is a different and equally
    plausible-looking picture.
    """
    m = _enter_lake(boot())
    img = _shot(m, "edge_above")
    bg1, _bg2 = _palettes(m)
    rock = {_snes_rgb(bg1[I_ROCK]), _snes_rgb(bg1[I_ROCK_LIT])}
    halved = {_half_add(bg1[I_ROCK], 0), _half_add(bg1[I_ROCK_LIT], 0)}
    got = set(_band(img, ROW_ROCK, ROW_ROCK))
    assert got == rock, (
        f"the rock band should be exactly its own palette {sorted(rock)}; it "
        f"holds {sorted(got)} (halved against the fixed colour would be "
        f"{sorted(halved)})")


def test_the_gaps_inside_the_water_band_show_the_bed_at_full_intensity(boot):
    """The same fallback, INSIDE the band, where it cannot be a band boundary.

    The ripple rows carry 16 px of empty surface every 32 px, so the bed shows
    through unblended between the crests. The band therefore holds EXACTLY
    three colours, and this asserts the whole set rather than the presence of
    one: an extra colour would mean the ripple picked up a fourth state, and a
    missing one would mean a whole population vanished.
    """
    m = _enter_lake(boot())
    img = _shot(m, "edge_inside")
    bg1, bg2 = _palettes(m)
    want = {_snes_rgb(bg1[I_BED_NEAR]),
            _half_add(bg1[I_BED_NEAR], bg2[I_CREST]),
            _half_add(bg1[I_BED_NEAR], bg2[I_TROUGH])}
    got = set(_band(img, *ROWS_WAVE_NEAR))
    assert got == want, (
        f"the near ripple rows should hold exactly {sorted(want)} — two blends "
        f"and the unblended bed where the surface has no pixel; they hold "
        f"{sorted(got)}")


def test_the_deep_ripple_rows_hold_their_own_three_populations(boot):
    """The same three-state structure over the OTHER main operand.

    Driving both depths matters: the near shelf and the deep water are
    different CGRAM entries, so a blend that had silently locked onto one main
    colour would still pass the near case.
    """
    m = _enter_lake(boot())
    img = _shot(m, "edge_deep")
    bg1, bg2 = _palettes(m)
    want = {_snes_rgb(bg1[I_BED_FAR]),
            _half_add(bg1[I_BED_FAR], bg2[I_CREST]),
            _half_add(bg1[I_BED_FAR], bg2[I_TROUGH])}
    got = set(_band(img, *ROWS_WAVE_FAR))
    assert got == want, (
        f"the deep ripple rows should hold exactly {sorted(want)}; they hold "
        f"{sorted(got)}")


# =============================================================================
# the per-layer math enable
# =============================================================================

def test_text_over_the_water_is_not_blended(boot):
    """BG3 is absent from `math`, so its pixels are never admitted to the math.

    The line on tilemap row 21 sits inside the surface's uniform trough band,
    so every glyph pixel has an opaque sub-screen pixel underneath it and would
    blend if the enable bit were set. It must be the font's own white, and the
    blended white must appear nowhere in those rows.

    THE POPULATION IS ATTRIBUTED: the rows counted are exactly the eight the
    text row covers, and the two colours asserted are the only ones the band
    can hold — the glyph ink and the blended bed. A count over a wider region
    would be dominated by the band and would say nothing about the glyphs.
    """
    m = _enter_lake(boot())
    img = _shot(m, "text_over_water")
    bg1, bg2 = _palettes(m)
    ink = (255, 255, 255)                       # the BG3 sub-palette's index 3
    blended_ink = _half_add(0x7FFF, bg2[I_TROUGH])
    water = _half_add(bg1[I_BED_FAR], bg2[I_TROUGH])
    row = _band(img, ROW_TEXT_OVER_WATER, ROW_TEXT_OVER_WATER)
    assert blended_ink != ink, "the palette makes this case vacuous"
    assert set(row) == {ink, water}, (
        f"the text row over the water should hold exactly the glyph ink {ink} "
        f"and the blended bed {water}; it holds {sorted(set(row))}")
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
    pictures: one shot, seven advances, one shot. The ripple must have moved
    left by exactly eight pixels, and `_recover_shift` returns EVERY
    displacement that reproduces the row — so a single-valued answer is a
    measurement and a multi-valued one would be a failure of this test's own
    method.
    """
    m = _enter_lake(boot())
    ys = range(ROWS_WAVE_NEAR[0] * 8, ROWS_WAVE_NEAR[1] * 8 + 8)
    a = _shot(m, "drift_a")
    m.advance(7)
    b = _shot(m, "drift_b")
    assert _recover_shift(a, b, ys) == [8 * SPEED], (
        f"expected the ripple to move left by exactly {8 * SPEED} px over 8 "
        f"frames; recovered {_recover_shift(a, b, ys)}")


def test_a_stilled_surface_does_not_move_at_all(boot):
    """The control. One B press latches the drift off; sixteen frames later the
    WHOLE PICTURE must be bit-identical, not merely similar.

    This is what makes the drift case a measurement: a test that only ever
    watches something move cannot tell motion from noise, and one that only
    ever watches it stand still cannot tell a still surface from a dead ROM —
    so the pair is asserted, and `test_the_drift_resumes_after_a_second_press`
    closes the cycle.
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
    ys = range(ROWS_WAVE_FAR[0] * 8, ROWS_WAVE_FAR[1] * 8 + 8)
    a = _shot(m, "resume_a")
    m.advance(7)
    b = _shot(m, "resume_b")
    assert _recover_shift(a, b, ys) == [8 * SPEED], (
        f"the drift did not resume: recovered {_recover_shift(a, b, ys)}")


def test_the_surface_is_continuous_across_both_wraps(boot):
    """One pattern period and one whole map width, both driven.

    The ripple repeats every 32 px and the surface map is 256 px wide on a
    10-bit scroll latch, so a capture pair separated by either distance must be
    identical — and a seam at either wrap would show as a picture that is not.
    32 frames is the pattern period at 1 px per frame; 256 is the map.
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
    runs only at power-on, so a successor that composed no blend half would
    show this world through the lake's colour math. `title` composes
    `blend_off`, whose whole content is the blender's off state, so the return
    edge disarms it through the same vocabulary that armed it.

    The assertion is the strongest available: the returned title screen must be
    BIT-IDENTICAL to a title screen that never visited the lake.
    """
    virgin = _shot(boot(), "title_virgin")
    m = _enter_lake(boot())
    m.advance(1, pad1={"start": True})
    returned = _shot(m.advance(LAKE - TITLE - 1), "title_returned")
    assert virgin.tobytes() == returned.tobytes(), (
        "the title screen differs after a visit to the lake — the blender is "
        "still armed, or something else the lake scene wrote persisted")


def test_the_title_bed_bands_are_the_raw_palette(boot):
    """...and say WHICH colours, so the previous case cannot pass on a wash.

    A bit-identical comparison proves the two title screens agree; it does not
    prove they agree on the UNBLENDED world. This names the colours.
    """
    m = boot()
    img = _shot(m, "title_bands")
    bg1, _bg2 = _palettes(m)
    near = set(_band(img, *ROWS_CREST_BAND))
    far = set(_band(img, ROWS_WAVE_FAR[0], ROWS_WAVE_FAR[1]))
    assert near == {_snes_rgb(bg1[I_BED_NEAR])}, (
        f"the title's near bed should be the raw palette "
        f"{_snes_rgb(bg1[I_BED_NEAR])}; it holds {sorted(near)}")
    assert far == {_snes_rgb(bg1[I_BED_FAR])}, (
        f"the title's deep bed should be the raw palette "
        f"{_snes_rgb(bg1[I_BED_FAR])}; it holds {sorted(far)}")


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
    img = _shot(m, "declared")
    bg1, bg2 = _palettes(m)
    # TS's bg2 bit, CGWSEL's source bit and CGADSUB's bg1 + halve bits, all at
    # once: the crest band is (bed + crest) >> 1 only if the surface reached
    # the sub screen, the blender read the sub screen, and bg1 was admitted.
    assert set(_band(img, *ROWS_CREST_BAND)) == {
        _half_add(bg1[I_BED_NEAR], bg2[I_CREST])}
    # TM's bg1 bit: the world above the waterline is its own palette.
    assert set(_band(img, ROW_ROCK, ROW_ROCK)) == {
        _snes_rgb(bg1[I_ROCK]), _snes_rgb(bg1[I_ROCK_LIT])}
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
    """
    m = _enter_lake(boot())
    chr_src = (ASSETS / "wat_chr.bin").read_bytes()
    map_src = (ASSETS / "wat_map.bin").read_bytes()
    pal_src = (ASSETS / "wat_pal.bin").read_bytes()
    assert m.read_bytes(V, V_WAT_CHR * 2, len(chr_src)) == chr_src
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
    assert colours is not None and len(colours) >= 8, (
        f"the frame holds fewer than 8 colours: "
        f"{colours if colours is None else len(colours)}")
    bg1, _bg2 = _palettes(m)
    # Picture row 12 is sky, and it is ABOVE the text line at tilemap row 2
    # (picture rows 16..23) — a sky row that crossed the glyphs would hold ink
    # and say nothing about the fade.
    assert set(_row(img, 12)) == {_snes_rgb(bg1[1])}, (
        "the sky is not its own palette colour at full brightness — the fade "
        "has not finished, and every equality in this module assumes it has")
