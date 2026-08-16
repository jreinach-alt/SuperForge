"""split_h_demo — the cockpit raster-band split, asserted on what was drawn.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(90)`, which
lands on the ABSOLUTE frame 90 by construction.

WHAT THIS RAIL IS, and therefore what these cases have to prove. Its source
states its own subject:

    - a horizontal raster-band split via per-band HDMA on BGMODE **and** TM,
      routed through the channel allocator: the top band renders Mode 1 with
      BG3 (a genuine tile instrument panel), the bottom Mode 7 (the floor),
      across ONE clean scanline seam
    - two-palette CGRAM budgeting so the floor and panel palettes cannot
      overlap
    - BG3 placed clear of Mode 7's low 32 KB
    - THE SPLIT HOLDING UNDER LOAD: a spinning camera forces the matrix to be
      rebuilt every frame while the band HDMA must keep rendering
    - a live instrument whose rendered value tracks input
    - a lifecycle: the split turned OFF and back ON (-DTOGGLE_SPLIT), with the
      OFF state being -DNO_SPLIT's picture (no tile band at all)

THE PER-BAND MODE IS A PICTURE CLAIM AND NOTHING ELSE CAN CARRY IT. BGMODE and
TM are write-only PPU ports with no readback, and their per-scanline values
live in a ROM table the CPU never re-reads; a test that read the table would
be asserting on its own input. What "the top 40 scanlines are Mode 1 showing
BG3 and the rest are Mode 7 showing BG1" MEANS is a property of the rendered
frame, so every band case below reads screenshot pixels — at absolute frames,
inside each band and ON the boundary rows 39/40, in every state the rail
claims.

THE STRESS, precisely. `split_band` claims
BGMODE and TM `band = "scene"` — frame-wide — and docs/09 calls it the sole
ACTIVE-PHASE owner of BGMODE. This rail runs that frame-wide claim beside
`mode7_persp`'s two INDIRECT matrix channels while the camera spins, so every
VBlank re-points both pose pointers and both DASB banks. The verdict is a
picture invariant: across the whole 64-heading sweep the floor band CHANGES
every frame and the panel band does not move by one scanline or one pixel.

THE COLOUR ORACLE. The two bands are separated by their PALETTES, which the
allocator placed disjointly (`floor_pal` words 0..16, `text_pal` words 28..31)
and which the ROM writes from two independent sources. So "this scanline is
the floor band" is decidable from the pixels alone: a colour that is in the
floor palette and NOT in the panel palette can only have come from BG1 through
Mode 7. Those thirteen colours are the band oracle below, read from live CGRAM
rather than transcribed.

THE ANCHOR. Mesen hands back a 256x239 frame with a letterbox. The usual
"count the non-black rows" anchor does NOT work on this rail — the panel band
is mostly backdrop, so whole scanlines inside the picture are legitimately
black. The anchor is derived from the BOTTOM instead (the last non-black row
IS visible scanline 223, because the floor reaches the bottom of the frame in
every state this rail has), and `test_the_anchor_agrees_with_itself` proves the
derivation against the split-OFF frame, where the picture is floor edge to edge
and the classic 224-row span is available as an independent witness.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "split_h_demo.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "shd" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="cockpit"):
    pool = (MAP["scenes"][scene]["placements"] if scene else MAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_M7 = _sym("ES_V_M7")["start"]                 # the interleaved Mode 7 region
V_TXT_CHR = _sym("ES_V_TEXT_CHR")["start"]      # BG3 glyph page, VRAM words
V_TXT_MAP = _sym("ES_V_TEXT_MAP")["start"]      # BG3 32x32 tilemap base
C_FLOOR = _sym("ES_C_FLOOR_PAL")["start"]       # floor palette, CGRAM words
C_TXT = _sym("ES_C_TEXT_PAL")["start"]          # BG3 palette 7 (words 28..31)
WR_PERSP_IDX = _sym("ES_PERSP_IDX")["start"]    # the two INDIRECT index tables

_US = {p["sym"]: p["start"]
       for p in MAP["scenes"]["cockpit"]["placements"] if p["consumer"] == "user"}
US_HEADING, US_SPLIT_ON = _US["US_HEADING"], _US["US_SPLIT_ON"]

_CH = {c["name"]: c for c in MAP["scenes"]["cockpit"]["channels"]}


# --- the rail's geometry, restated against game/split_h_demo/split_h_demo.inc
def _inc_const(name):
    """Read one assemble-time constant out of the rail's .inc.

    The .inc is the SSoT for this geometry, so the test reads it rather than
    re-declaring a literal — a re-declared 40 keeps asserting the old seam
    after the game moves, silently, because the number still looks right
    (mz_drive.world_const's reasoning, applied to this rail)."""
    import re
    src = (SUPERFORGE / "game" / "split_h_demo" / "split_h_demo.inc").read_text()
    m = re.search(rf"^\s*{re.escape(name)}\s*=\s*(-?\d+)\b", src, re.M)
    assert m, f"split_h_demo.inc has no decimal constant {name!r}"
    return int(m.group(1))


SEAM = _inc_const("HUD_LINES")                  # 40 — the band boundary
CAM0_TX, CAM0_TY = _inc_const("CAM0_TX"), _inc_const("CAM0_TY")
ROT_SPD = _inc_const("ROT_SPD")
HEAD_MASK = _inc_const("HEAD_MASK")
WORLD_T = _inc_const("WORLD_T_TILES")
TXT_ATTR = (7 << 10) | (1 << 13)                # SHD_TXT_ATTR, palette 7 + pri
HUD_CELL = V_TXT_MAP + 2 * 32 + 21              # SHD_HUD_CELL
M7_TILES = 128                                  # the Mode 7 tilemap is 128x128

PIC_H, PIC_W = 224, 256
BOOT = 90                                       # an absolute frame, past the fade

# The live readout's rendered window, MEASURED on this ROM rather than computed
# from its tilemap row: BG3's glyph ink lands one scanline ABOVE row*8 on this
# scene, so the four cells at row 2 cols 21..24 draw on visible scanlines 15..21
# and columns 192..198 (pixel-diff of advance(90) against four held right
# frames). Declared as a WINDOW with margin because it is the only part of the
# panel band allowed to change, and the sweep case asserts that containment
# rather than merely skipping it.
HUD_PX_LINES = range(14, 24)
HUD_PX_COLS = range(184, 208)

# The five authored panel rows (game/split_h_demo/scenes/cockpit.asm's strings),
# re-expressed here rather than parsed: the assertion is that the ROM drew
# THESE, so the expectation has to be independent of the ROM's own bytes.
PANEL_ROWS = {
    0: (1, "=============================="),
    1: (1, ".o.o.o.o.o.o.o.o.o.o.o.o.o.o.o"),
    2: (2, "HEAD"),
    3: (1, "MODE 1 BG3 OVER MODE 7 BG1"),
    4: (1, "=============================="),
}


def _rgb(bgr):
    r, g, b = bgr & 31, (bgr >> 5) & 31, (bgr >> 10) & 31
    return tuple((v << 3) | (v >> 2) for v in (r, g, b))


def _glyph(ch):
    """The font's tile index for one ASCII character (space is tile 0)."""
    return ord(ch) - ord(" ")


# =============================================================================
# Driving helpers — every boot lands on an absolute frame
# =============================================================================
def _spin(m, frames, direction="right"):
    """Hold one D-pad direction for `frames` frames, then settle one frame.

    HELD, not tapped: the rail spins while the direction is down, and the
    settle frame lets the NMI commit the last heading's pose re-point so the
    picture and the state describe the same frame."""
    for _ in range(frames):
        m.advance(1, pad1={direction: True})
    m.advance(1)
    return m


def _press_a(m):
    """One fresh A press (the split toggle), then settle.

    The rail reads ES_INP_PRESS, so the press must be a 0->1 EDGE: the release
    frame is what makes the NEXT press an edge too, which is the whole point of
    a test that toggles more than once."""
    m.advance(1, pad1={"a": True})
    m.advance(2)
    return m


def _shot(m, path):
    m.screenshot(str(path))
    return Image.open(path).convert("RGB")


@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle.

    `Machine` owns the process-global core as a singleton, so a module-scope
    machine and a `with Machine(...)` inside a case cannot coexist — the second
    closes the first and every read on the stale handle is a read of a dead
    core. scroll_run's shape: the fixture hands back a BOOT FUNCTION and the
    teardown closes whichever machine currently owns the core."""
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make split_h_demo` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


@pytest.fixture(scope="module")
def palettes(boot):
    fresh = boot()
    raw = bytes(fresh.read_bytes(C, 0, 64))
    words = [raw[i] | (raw[i + 1] << 8) for i in range(0, 64, 2)]
    floor = {_rgb(w) for w in words[C_FLOOR:C_FLOOR + 17]}
    panel = {_rgb(w) for w in words[C_TXT:C_TXT + 4]}
    # A colour in the floor palette and NOT in the panel palette can only have
    # reached the screen through BG1 in Mode 7 — that is the band oracle.
    return {"floor": floor, "panel": panel, "floor_only": floor - panel,
            "words": words}


# =============================================================================
# The anchor (derived, then cross-checked against an independent witness)
# =============================================================================
def _anchor(img):
    """The PNG row that IS visible scanline 0.

    Derived from the BOTTOM: the last non-black row is scanline 223, because
    the Mode 7 floor reaches the frame's last line in every state this rail
    has. The usual top-side "the content span is 224 rows" anchor is WRONG
    here — the panel band is mostly backdrop, so rows inside the picture are
    legitimately all black."""
    rows = [{img.getpixel((x, y)) for x in range(img.size[0])}
            for y in range(img.size[1])]
    lit = [y for y, r in enumerate(rows) if r != {(0, 0, 0)}]
    assert lit, "the frame is entirely black — nothing rendered"
    top = lit[-1] - (PIC_H - 1)
    assert 0 <= top and top + PIC_H <= img.size[1], (
        f"the derived anchor {top} does not fit a {PIC_H}-row picture in a "
        f"{img.size[1]}-row frame")
    return top


def _scan(img, top, line):
    """The set of colours on one VISIBLE scanline."""
    return {img.getpixel((x, top + line)) for x in range(PIC_W)}


def _band_first_floor_line(img, top, floor_only):
    """The first visible scanline carrying a floor-only colour, or None."""
    for y in range(PIC_H):
        if _scan(img, top, y) & floor_only:
            return y
    return None


def test_the_anchor_agrees_with_itself(boot, tmp_path, palettes):
    """The bottom-derived anchor, cross-checked against the split-OFF frame.

    In the OFF state the whole frame is Mode 7 floor, so the classic
    "exactly 224 non-black rows" span IS available — an independent witness
    for a constant every other case in this module depends on."""
    with boot() as m:
        on = _shot(m, tmp_path / "anchor_on.png")
        _press_a(m)
        off = _shot(m, tmp_path / "anchor_off.png")
    rows = [{off.getpixel((x, y)) for x in range(off.size[0])}
            for y in range(off.size[1])]
    lit = [y for y, r in enumerate(rows) if r != {(0, 0, 0)}]
    assert len(lit) == PIC_H, (
        f"the split-OFF frame should be {PIC_H} lit scanlines of floor edge to "
        f"edge; found {len(lit)}")
    assert lit == list(range(lit[0], lit[0] + PIC_H)), \
        "the OFF frame's content span has black rows inside it"
    assert _anchor(off) == lit[0] == _anchor(on), (
        f"the two derivations disagree: bottom-derived {_anchor(off)} vs "
        f"span-derived {lit[0]} vs on-frame {_anchor(on)}")


# =============================================================================
# Uploads — the DESTINATION regions, byte for byte
# =============================================================================
def test_the_font_reaches_its_claimed_chr_base(fresh):
    want = (ASSETS / "font_2bpp.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_TXT_CHR * 2, len(want)))
    assert got == want, (
        f"the BG3 glyph page at VRAM word ${V_TXT_CHR:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_the_chr_page_is_clear_of_the_mode7_region(fresh):
    """The reference's manual upper-32KB BG3 placement, discharged by the allocator.

    Its `BG3SC_VAL = $48` / `BG34NBA_VAL = $05` exist because BG3 must not
    land inside Mode 7's low 32 KB. Here that is a claim disjointness the
    allocator proved — this case asserts the PROPERTY those constants were
    defending, against the emitted addresses rather than against them."""
    m7_end = V_M7 + _sym("ES_V_M7")["size"] // 2
    for sym in ("ES_V_TEXT_CHR", "ES_V_TEXT_MAP"):
        p = _sym(sym)
        start, end = p["start"], p["start"] + p["size"]
        assert start >= m7_end or end <= V_M7, (
            f"{sym} at words ${start:04X}..${end:04X} intersects the Mode 7 "
            f"region ${V_M7:04X}..${m7_end:04X}")


def test_all_four_claimed_text_palette_words_are_written(fresh, palettes):
    """Every claimed word, not just the ones the glyphs happen to use.

    scroll_run's §5 lesson: its GOAL text rendered green because word 31 was
    left holding power-on RNG under the default seed. `text_pal` claims FOUR
    words and the ROM must write all four, including the mid tone nothing
    currently draws — an unwritten claimed word is a seed-dependent flap
    waiting for the day something reads it."""
    raw = bytes(fresh.read_bytes(C, C_TXT * 2, 8))
    got = [raw[i] | (raw[i + 1] << 8) for i in range(0, 8, 2)]
    assert got == [0x0000, 0x1084, 0x02E0, 0x7FFF], (
        f"BG3 palette 7 (CGRAM words {C_TXT}..{C_TXT + 3}) is "
        f"{[hex(w) for w in got]}, not the four authored words")


def test_the_floor_palette_reaches_its_claimed_words(fresh):
    want = (ASSETS / "floor_pal.bin").read_bytes()
    got = bytes(fresh.read_bytes(C, C_FLOOR * 2, len(want)))
    assert got == want, (
        f"the floor palette at CGRAM word {C_FLOOR} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_the_two_palettes_do_not_overlap(palettes):
    """The reference's two-palette CGRAM `.assert` (main.asm:181), as a hardware read.

    That build-time guard does not port as work — the allocator proves the
    disjointness for every composition. What is worth asserting is the
    PROPERTY on the machine: the claimed spans do not intersect, and the
    colours actually loaded into them are distinguishable, because the whole
    band oracle in this module rests on that."""
    fp, tp = _sym("ES_C_FLOOR_PAL"), _sym("ES_C_TEXT_PAL")
    assert fp["start"] + fp["size"] <= tp["start"], (
        f"floor_pal words {fp['start']}..{fp['start'] + fp['size'] - 1} "
        f"overlap text_pal at {tp['start']}")
    assert len(palettes["floor_only"]) >= 8, (
        f"only {len(palettes['floor_only'])} floor colours are distinguishable "
        f"from the panel palette — the band oracle would be weak")


def test_the_mode7_region_holds_the_world_window_around_the_camera(fresh):
    """The interleaved region's TILEMAP plane vs the world blob, wrapped.

    mode7_floor seeds a 128x128 tile window positioned so that world tile
    (x, y) lands at VRAM cell (x mod 128, y mod 128) — the wrap the plane's
    own addressing needs. Reading the destination and re-deriving the source
    independently is what makes this an upload test rather than a tautology."""
    world = (ASSETS / "world_map.bin").read_bytes()
    assert len(world) == WORLD_T * WORLD_T
    raw = bytes(fresh.read_bytes(V, V_M7 * 2, M7_TILES * M7_TILES * 2))
    half = M7_TILES // 2
    bad = []
    for ty in range(CAM0_TY - half, CAM0_TY + half):
        for tx in range(CAM0_TX - half, CAM0_TX + half):
            want = world[(ty % WORLD_T) * WORLD_T + (tx % WORLD_T)]
            cell = (ty % M7_TILES) * M7_TILES + (tx % M7_TILES)
            if raw[cell * 2] != want:          # even byte = the tilemap plane
                bad.append((tx, ty, raw[cell * 2], want))
    assert not bad, (
        f"{len(bad)} of {M7_TILES * M7_TILES} seeded Mode 7 cells disagree "
        f"with the world blob; first: {bad[:3]}")


def test_the_panel_tilemap_holds_the_five_authored_rows(fresh):
    """The BG3 map's destination words vs the five strings, and rows 5..31 clear.

    The readout's four cells are excluded here and owned by their own cases —
    they are the one part of the panel that changes after enter."""
    raw = bytes(fresh.read_bytes(V, V_TXT_MAP * 2, 32 * 32 * 2))
    words = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]
    for row, (col0, text) in PANEL_ROWS.items():
        for i, ch in enumerate(text):
            cell = row * 32 + col0 + i
            assert words[cell] == (_glyph(ch) | TXT_ATTR), (
                f"panel row {row} col {col0 + i} is ${words[cell]:04X}, not "
                f"glyph {ch!r} (${_glyph(ch) | TXT_ATTR:04X})")
    blank = _glyph(" ") | TXT_ATTR
    for row in range(5, 32):
        got = set(words[row * 32:(row + 1) * 32])
        assert got == {blank}, (
            f"BG3 row {row} should be cleared to the blank cell ${blank:04X}; "
            f"holds {sorted(hex(w) for w in got)[:4]}")


# =============================================================================
# The seam — a picture claim, inside each band and ON the boundary
# =============================================================================
def test_the_seam_is_exactly_at_the_declared_scanline(fresh, tmp_path,
                                                      palettes):
    """The whole point of the rail, as pixels.

    Not "a boundary exists somewhere": the FIRST scanline carrying a colour
    only the floor palette has must be exactly SEAM, and no scanline above it
    may carry one. That is the per-band TM claim ($04 = BG3 alone above,
    $01 = BG1 alone below) stated the only way the hardware can answer it."""
    img = _shot(fresh, tmp_path / "seam.png")
    top = _anchor(img)
    first = _band_first_floor_line(img, top, palettes["floor_only"])
    assert first == SEAM, (
        f"the floor band starts at scanline {first}, not the declared seam "
        f"{SEAM} — the BGMODE/TM band table and the geometry disagree")


def test_the_boundary_rows_are_the_two_bands(fresh, tmp_path, palettes):
    """Scanlines SEAM-1 and SEAM, read as the two sides of one clean seam.

    ON the boundary, both directions: the last panel row must carry no floor
    colour at all, and the first floor row must carry several. A one-scanline
    slip in either direction fails exactly one of these two."""
    img = _shot(fresh, tmp_path / "boundary.png")
    top = _anchor(img)
    above = _scan(img, top, SEAM - 1)
    below = _scan(img, top, SEAM)
    assert not (above & palettes["floor_only"]), (
        f"scanline {SEAM - 1} (the last panel row) carries floor colours "
        f"{sorted(above & palettes['floor_only'])} — the seam slipped down")
    assert len(below & palettes["floor_only"]) >= 3, (
        f"scanline {SEAM} (the first floor row) carries only "
        f"{sorted(below)} — the seam slipped up")


def test_every_panel_scanline_is_panel_only_and_the_ink_is_where_the_rows_are(
        fresh, tmp_path, palettes):
    """All SEAM scanlines, plus the panel's ink landing on its authored rows.

    The band claim is not just "no floor above the seam" — it is "BG3 is what
    renders there". So every panel scanline's colours must come from the panel
    palette, AND the ink must appear on the scanline spans the five authored
    tilemap rows occupy, which is what proves BG3 is being DRAWN rather than
    merely not-overwritten."""
    img = _shot(fresh, tmp_path / "panel.png")
    top = _anchor(img)
    ink = _rgb(0x7FFF)
    for y in range(SEAM):
        got = _scan(img, top, y)
        assert got <= palettes["panel"], (
            f"panel scanline {y} carries {sorted(got - palettes['panel'])}, "
            f"which is not in BG3's claimed palette")
    for row in PANEL_ROWS:
        span = [y for y in range(row * 8, row * 8 + 8)
                if ink in _scan(img, top, y)]
        assert span, (
            f"panel tilemap row {row} (scanlines {row * 8}..{row * 8 + 7}) "
            f"has no ink — the row is in VRAM but is not rendering")


# =============================================================================
# The stress: the split under a live matrix rebuild
# =============================================================================
def test_the_panel_band_changes_only_in_the_readout_across_the_whole_sweep(
        boot, tmp_path, palettes):
    """THE VERDICT. The frame-wide band claim, held while the matrix churns.

    Drives the camera through the whole 64-heading sweep in BOTH directions and
    asserts three things about each sampled frame:

      - the seam is still exactly at SEAM (not one scanline either way),
      - every panel-band pixel that differs from the boot frame lies inside the
        live readout's measured window — so the ONLY thing moving above the
        seam is the instrument the rail drives on purpose,
      - the floor band CHANGED from the previous sample.

    The third arm is the non-vacuity one and it is not optional: a ROM whose
    matrix channels never fired would pass the first two perfectly, and the
    claim being tested is that the split holds UNDER LOAD."""
    with boot() as m:
        base = _shot(m, tmp_path / "sweep_0.png")
        top = _anchor(base)

        def panel_diff(img):
            return {(x, y) for y in range(SEAM) for x in range(PIC_W)
                    if img.getpixel((x, top + y)) != base.getpixel((x, top + y))}

        def floor(img):
            return [img.getpixel((x, top + y))
                    for y in range(SEAM, PIC_H) for x in range(PIC_W)]

        prev_floor, seen, moved = floor(base), [], set()
        for direction, tag in (("right", "r"), ("left", "l")):
            for i in range(1, 9):       # 8 samples x 4 frames = 32 headings
                _spin(m, 4, direction)
                img = _shot(m, tmp_path / f"sweep_{tag}{i}.png")
                h = m.read_byte(W, US_HEADING)
                if tag == "r":
                    seen.append(h)
                assert _band_first_floor_line(
                    img, top, palettes["floor_only"]) == SEAM, (
                    f"the seam moved at heading {h} (sample {i} spinning "
                    f"{direction}) — the frame-wide BGMODE/TM claim did not "
                    f"hold under the matrix re-point")
                d = panel_diff(img)
                stray = {(x, y) for x, y in d
                         if y not in HUD_PX_LINES or x not in HUD_PX_COLS}
                assert not stray, (
                    f"at heading {h} the panel band changed OUTSIDE the live "
                    f"readout at {sorted(stray)[:5]} ({len(stray)} pixels)")
                moved |= d
                now = floor(img)
                assert now != prev_floor, (
                    f"the floor band did NOT change at heading {h}: the matrix "
                    f"channels are not being re-pointed, so this sweep proves "
                    f"nothing about holding under load")
                prev_floor = now
        assert m.read_byte(W, US_HEADING) == 0, (
            "the sweep did not return to heading 0 — the two directions are "
            "not the same axis")
    assert len(set(seen)) == 8, \
        f"the right sweep visited {sorted(set(seen))}, not eight fresh headings"
    assert moved, (
        "the readout never changed across a 64-heading sweep — the panel-band "
        "invariant above would then be vacuous")


def test_the_pose_pointers_the_indirect_channels_fetch_move_with_the_heading(boot):
    """The matrix re-point's own output region — the streamed index tables.

    The two INDIRECT channels fetch their per-scanline pose through these WRAM
    tables; the pointer words and the DASB bank ARE what the DMA controller
    reads. Corroborates the picture case above from the mechanism's side, and
    fails loudly if the floor ever changes for some other reason."""
    with boot() as m:
        at0 = bytes(m.read_bytes(W, WR_PERSP_IDX, 32))
        _spin(m, 8, "right")
        at8 = bytes(m.read_bytes(W, WR_PERSP_IDX, 32))
        _spin(m, 8, "left")
        back = bytes(m.read_bytes(W, WR_PERSP_IDX, 32))
    assert at8 != at0, (
        "the pose index tables did not move after eight heading steps — "
        "nothing is being re-pointed and there is no live rebuild to hold "
        "the split under")
    assert back == at0, (
        "spinning back to heading 0 did not restore the heading-0 pointers — "
        "the re-point is not a function of the heading")


def test_the_two_band_channels_and_the_matrix_pair_are_distinct(fresh):
    """The composition's channel assignment, from the emitted map.

    Four active channels, four distinct numbers, and the two `split_band`
    claims are frame-wide (`band = "scene"`) while sharing the frame with the
    matrix pair — the arrangement the picture cases above then prove renders."""
    assert set(_CH) == {"bgm", "tmi", "m7ab", "m7cd"}
    chans = {n: c["ch"] for n, c in _CH.items()}
    assert len(set(chans.values())) == 4, f"channels collide: {chans}"
    for n in ("bgm", "tmi"):
        assert _CH[n]["band"] == [0, PIC_H], (
            f"{n} is banded {_CH[n]['band']}, not frame-wide — docs/09's "
            f"SPLIT row says this claim is `band = \"scene\"`")
        assert _CH[n]["phase"] == "active"
    assert _CH["bgm"]["registers"] == ["BGMODE"]
    assert _CH["tmi"]["registers"] == ["TM"]


# =============================================================================
# The lifecycle: OFF and back ON, both directions, more than once
# =============================================================================
def test_the_split_toggles_off_and_on_and_the_picture_follows(boot, tmp_path,
                                                              palettes):
    """The reference's -DTOGGLE_SPLIT lifecycle, driven ON->OFF->ON->OFF.

    In the ON states the seam is exactly at SEAM and the panel band carries no
    floor colour. In the OFF states there is NO seam: floor colours reach
    scanline 0, which is -DNO_SPLIT's picture — the whole screen a single
    Mode 7 floor with no tile band. Four states, three transitions, in both
    directions, which is why this rail has no one-shot latch."""
    with boot() as m:
        top = _anchor(_shot(m, tmp_path / "life_0.png"))
        for i, want_on in enumerate([True, False, True, False]):
            if i:
                _press_a(m)
            img = _shot(m, tmp_path / f"life_{i}.png")
            state = m.read_byte(W, US_SPLIT_ON)
            assert state == int(want_on), \
                f"step {i}: the rail thinks split_on={state}, expected {int(want_on)}"
            first = _band_first_floor_line(img, top, palettes["floor_only"])
            if want_on:
                assert first == SEAM, (
                    f"step {i} (split ON): the floor band starts at {first}, "
                    f"not {SEAM}")
                for y in range(SEAM):
                    assert _scan(img, top, y) <= palettes["panel"], \
                        f"step {i}: panel scanline {y} shows floor colours"
            else:
                assert first == 0, (
                    f"step {i} (split OFF): the floor band starts at {first} — "
                    f"with the band channels disabled the seeded BGMODE/TM "
                    f"must render Mode 7 for all {PIC_H} lines")
                lit = sum(1 for y in range(SEAM)
                          if _scan(img, top, y) & palettes["floor_only"])
                assert lit == SEAM, (
                    f"step {i}: only {lit} of the {SEAM} former panel "
                    f"scanlines show floor — the band did not fully collapse")


def test_the_toggle_disables_the_channels_and_never_repaints_the_panel(boot,
        tmp_path):
    """The OFF state is an ENABLE change, not a repaint.

    the reference's `sf_split_h_off` releases the channels and its re-arm re-programs
    the same RODATA tables; here the tables stay armed in the scene_mgr shadow
    and only the HDMAEN mask moves. The observable consequence is that the BG3
    tilemap in VRAM is byte-identical across the whole cycle — if the toggle
    had gone through a repaint, an OFF frame would have to clear it."""
    n = 32 * 32 * 2
    with boot() as m:
        on = bytes(m.read_bytes(V, V_TXT_MAP * 2, n))
        _press_a(m)
        off = bytes(m.read_bytes(V, V_TXT_MAP * 2, n))
        _press_a(m)
        again = bytes(m.read_bytes(V, V_TXT_MAP * 2, n))
    assert off == on, (
        "the BG3 tilemap changed when the split was disabled — the toggle is "
        "repainting rather than releasing the channels")
    assert again == on, "the re-arm did not restore the panel's tilemap"


# =============================================================================
# The live instrument
# =============================================================================
def _readout(m):
    raw = bytes(m.read_bytes(V, HUD_CELL * 2, 8))
    words = [raw[i] | (raw[i + 1] << 8) for i in range(0, 8, 2)]
    return "".join("0123456789ABCDEF"[(w & 0x3FF) - _glyph("0")]
                   if 0 <= (w & 0x3FF) - _glyph("0") < 10 else
                   "0123456789ABCDEF"[(w & 0x3FF) - _glyph("A") + 10]
                   for w in words)


def test_the_readout_tracks_the_heading_up_and_down(boot, tmp_path):
    """The dynamic instrument, driven in BOTH directions.

    the reference's fill bar tracks P1 Left/Right; here the four-cell hex readout
    does. Read from the BG3 tilemap's destination words — the cells the VBlank
    queue committed — and cross-checked against the rendered pixels changing,
    because a tilemap word nothing draws is not an instrument."""
    with boot() as m:
        assert _readout(m) == "0000", f"the readout boots at {_readout(m)!r}"
        shot0 = _shot(m, tmp_path / "hud_0.png")
        top = _anchor(shot0)
        _spin(m, 12, "right")
        h = m.read_byte(W, US_HEADING)
        assert h == 12 * ROT_SPD & HEAD_MASK
        assert _readout(m) == f"{h:04X}", \
            f"after 12 right frames the readout is {_readout(m)!r}, want {h:04X}"
        shot1 = _shot(m, tmp_path / "hud_1.png")
        _spin(m, 20, "left")
        h2 = m.read_byte(W, US_HEADING)
        assert h2 == (h - 20 * ROT_SPD) & HEAD_MASK
        assert _readout(m) == f"{h2:04X}", \
            f"after 20 left frames the readout is {_readout(m)!r}, want {h2:04X}"
    band = [(x, y) for y in HUD_PX_LINES for x in HUD_PX_COLS]
    assert [shot0.getpixel((x, top + y)) for x, y in band] != \
           [shot1.getpixel((x, top + y)) for x, y in band], \
        "the readout's tilemap words changed but its PIXELS did not"


def test_the_readout_is_staged_only_when_the_heading_changes(boot):
    """Reprint-on-change, measured on the destination cell's write counter.

    hud_game's discipline. An idle frame must not re-commit the run: the
    counter on the readout's first cell moves while the camera turns and
    stands still while it does not."""
    with boot() as m:
        at_rest = m.writes(V, HUD_CELL * 2)
        m.advance(30)
        assert m.writes(V, HUD_CELL * 2) == at_rest, (
            "the readout cell was rewritten during 30 idle frames — the "
            "reprint-on-change gate is not gating")
        _spin(m, 6, "right")
        moved = m.writes(V, HUD_CELL * 2)
        assert moved >= at_rest + 6, (
            f"six heading changes produced {moved - at_rest} commits to the "
            f"readout cell; the VBlank queue is not draining")


def test_an_idle_frame_is_pixel_identical_over_sixty_frames(boot, tmp_path):
    """Nothing moves without input — the rail's rest state.

    The camera spins only while a direction is held (the reference's shoulders), so
    a released ROM must render the same frame indefinitely. A drift here would
    mean the matrix re-point is firing on something other than the heading."""
    with boot() as m:
        a = _shot(m, tmp_path / "idle_a.png").tobytes()
        m.advance(60)
        b = _shot(m, tmp_path / "idle_b.png").tobytes()
    assert a == b, "the idle frame changed over 60 frames with no input"
