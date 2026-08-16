"""VWF — the RENDERED half, read off the hardware.

Every assertion below reads an output region the feature produces: the strip
tiles' VRAM CHR bytes, or screenshot pixels. Nothing reads the DP pen, the WRAM
canvas, or a "reveal happened" flag — those are proxies for the thing under test
and would pass while the renderer was silently broken (CLAUDE.md rule 2).

The invariant that proves VWF *specifically* is PROPORTIONAL ADVANCE: two
strings of equal character count and different glyph widths must occupy
different pixel extents. A test that only proves "text appeared" proves
bg_text. So the expectations here come from `build/assets/vwf_widths.bin` — the
generated artifact, read at test time — rather than from a table typed into this
file, which also means a face swap re-aims the assertions instead of breaking
them.

race renders four messages on a 128-frame rotation (race.asm's
vwf_dialog_tick): 'iiii' and 'mmmm' are the extremes, '....' is the narrowest
glyph in the face, and 'End. Next: go' is prose with punctuation. The schedule
is powers-of-two so it is exactly reproducible from ES_SM_FRAME.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

WR, VR = MemoryType.SnesWorkRam, MemoryType.SnesVideoRam
TILE_BYTES = 16

# race.asm's schedule and row placement — the game's declarations, not the
# renderer's.
SLOT_FRAMES = 128
MESSAGES = {0: "iiii", 1: "mmmm", 2: "....", 3: "End. Next: go"}
WHITE = 3                      # text_pal colour 3; race sets it to $7FFF


def _vwf_row_col():
    """(row, col) of the dialog row, READ OUT of race.asm's declaration.

    This used to be `ROW = 4 # VWF_ROW_CELL = ES_V_TEXT_MAP + 4*32 + 2`. The
    row moved to 3 during this change and the constant did not, leaving a wrong
    comment sitting exactly where the next reader looks for the row. It was
    unreferenced, so nothing was broken — which is the whole problem with a
    copied constant: nothing makes it wrong out loud.

    Same rationale as mz_drive.world_const: read the SSoT. If race.asm's
    declaration is ever reshaped this fails loudly instead of silently
    asserting the old geometry.
    """
    src = (SUPERFORGE / "game" / "microzero" / "scenes" / "race.asm").read_text()
    m = re.search(r"^VWF_ROW_CELL\s*=\s*ES_V_TEXT_MAP\s*\+\s*"
                  r"(\d+)\s*\*\s*32\s*\+\s*(\d+)\s*$", src, re.M)
    assert m, ("race.asm has no `VWF_ROW_CELL = ES_V_TEXT_MAP + <row>*32 + "
               "<col>` to read the dialog row's placement from")
    return int(m.group(1)), int(m.group(2))


ROW, COL = _vwf_row_col()


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jm = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jm["scenes"]["race"]["placements"] + jm["globals"]}
    # Everything geometric is DERIVED from the map, so a claim resize re-aims
    # the tests instead of silently mis-addressing them.
    tile0 = syms["ES_R_FONT_BIN"]["size"] // TILE_BYTES          # 96 glyphs
    strips = syms["ES_VWF_CANVAS"]["size"] // TILE_BYTES - 1      # 14 (- guard)
    return {
        "syms": syms,
        "tile0": tile0,
        "strips": strips,
        "chr_byte0": (syms["ES_V_TEXT_CHR"]["start"] + tile0 * 8) * 2,
        "window_px": strips * 8,
        "widths": (SUPERFORGE / "build" / "assets" / "vwf_widths.bin").read_bytes(),
        "glyphs": (SUPERFORGE / "build" / "assets" / "vwf_glyphs.bin").read_bytes(),
    }


@pytest.fixture(scope="module")
def runner(built):
    r = MesenRunner()
    r.load_rom_with_uninit_detection(
        str(SUPERFORGE / "build" / "microzero.sfc"), frames=120)
    D.enter_race(r, built["syms"])
    yield r
    r.stop()


# --------------------------------------------------------------------------
# reading the output region
# --------------------------------------------------------------------------

def strip_chr(runner, b) -> bytes:
    """The strip tiles' CHR, straight out of VRAM."""
    return runner.read_bytes(VR, b["chr_byte0"], b["strips"] * TILE_BYTES)


def ink_columns(chr_bytes, strips) -> set:
    """Every inked pixel column in the window, from the BP0 plane."""
    cols = set()
    for t in range(strips):
        for row in range(8):
            byte = chr_bytes[t * TILE_BYTES + row * 2]
            for c in range(8):
                if byte & (0x80 >> c):
                    cols.add(t * 8 + c)
    return cols


def rendered_extent(chr_bytes, strips) -> int:
    """Rightmost inked column + 1, i.e. the rendered pixel width."""
    cols = ink_columns(chr_bytes, strips)
    return max(cols) + 1 if cols else 0


def advance_of(b, ch) -> int:
    return b["widths"][ord(ch) - 0x20]


def expected_extent(b, text) -> int:
    """Where the ink of `text` must end: sum of advances, less the trailing
    letterspacing pixel of the last glyph (which is blank by construction)."""
    total = sum(advance_of(b, c) for c in text)
    last = text[-1]
    trail = advance_of(b, last) - _ink_width(b, last)
    return total - trail


def _ink_width(b, ch) -> int:
    """The glyph's own inked width, from the mask artifact."""
    g = ord(ch) - 0x20
    mask = 0
    for r in range(8):
        mask |= b["glyphs"][g * 8 + r]
    if mask == 0:
        return 0
    return max(c for c in range(8) if mask & (0x80 >> c)) + 1


def reference_canvas(b, text) -> bytes:
    """An INDEPENDENT second implementation of the compositor, in Python.

    Written from the geometry rather than from vwf.asm: a glyph's column c lands
    at window column pen + c, and a window column maps to bit (7 - col % 8) of
    tile (col // 8). Byte-comparing this against VRAM catches shift errors,
    lost cross-tile carries and plane errors that an extent check cannot.
    (A reference generated by the code under test would be a tautology; a second
    implementation is the alternate path CLAUDE.md's rule allows.)
    """
    canvas = bytearray(b["strips"] * TILE_BYTES)
    pen = 0
    for ch in text:
        if pen >= b["window_px"]:
            break
        g = ord(ch) - 0x20
        for row in range(8):
            mask = b["glyphs"][g * 8 + row]
            for c in range(8):
                if not (mask & (0x80 >> c)):
                    continue
                col = pen + c
                tile, bit = col // 8, 0x80 >> (col % 8)
                if tile >= b["strips"]:
                    continue            # the spill guard is never uploaded
                canvas[tile * TILE_BYTES + row * 2] |= bit       # BP0
                canvas[tile * TILE_BYTES + row * 2 + 1] |= bit   # BP1
        pen += advance_of(b, ch)
    return bytes(canvas)


def goto_slot(runner, b, slot, limit=4000):
    """Frame-step to the start of `slot`'s 128-frame window (deterministic:
    frame_step, never wall-clock — see AGENTS.md)."""
    frame_at = b["syms"]["ES_SM_FRAME"]["start"]
    for _ in range(limit):
        f = runner.read_u16(WR, frame_at)
        if f % SLOT_FRAMES == 0 and (f // SLOT_FRAMES) % len(MESSAGES) == slot:
            return f
        runner.frame_step(1)
    raise AssertionError(f"slot {slot} never came round")


def fully_revealed(runner, b, slot):
    """Step to `slot` and let it reveal to completion. Returns strip CHR."""
    goto_slot(runner, b, slot)
    runner.frame_step(4 * (len(MESSAGES[slot]) + 3))
    return strip_chr(runner, b)


def shoot_blank_row(runner, b, path, max_frames=24):
    """Screenshot the row while it is blank ON SCREEN, not merely in VRAM.

    T5 used to step a fixed ONE frame past the slot boundary. VRAM is blank at
    that instant, but the frame most recently composited still shows the
    OUTGOING message, so the differential picked up `old ink | new ink` and its
    max(x) was the wider of the two. A later review measured it: slot 0 reads 76 px at
    +1 frame (that is 'End. Next: go' bleeding through) against its true 23 px.
    The shipped test passed only because it shot slot 3, which happens to be
    the widest message in the rotation — the contamination was invisible for
    the single slot it looked at.

    Measured at the slot-2 boundary, differential extent of a shot taken N
    frames past it against the fully-revealed '....' (true extent 11 px):

        +0  VRAM inked   23 px      +3  VRAM blank   11 px
        +1  VRAM blank   23 px      +4  VRAM blank   11 px
        +2  VRAM blank   11 px      +5  VRAM inked  (reveal has begun)

    So VRAM blanks a frame before the composited output does, and the capture
    lag is not a fixed frame count I was able to pin down: shooting on the
    first frame whose whole active display was drawn from a blank window works
    standalone and still contaminates inside the module's shared runner. Rather
    than model a lag I cannot measure reliably, take the LARGEST margin the
    game's own cadence allows — shoot on every blank frame and keep the last,
    which lands on the frame before the first glyph appears. Derived from
    observed VRAM state, not from a magic number, and it re-derives itself if
    the reveal cadence or the pipeline depth changes.
    """
    for _ in range(max_frames):
        if not any(strip_chr(runner, b)):
            break
        runner.frame_step(1)
    else:
        raise AssertionError(
            "the window never blanked after the slot opened, so no blank "
            "reference can be taken")
    for _ in range(max_frames):
        runner.take_screenshot(str(path))     # last write wins
        runner.frame_step(1)
        if any(strip_chr(runner, b)):
            return
    raise AssertionError(
        "the reveal never started, so the blank window's end was never "
        "observed and the reference has no bounded settling margin")


# --------------------------------------------------------------------------
# T1 — the invariant that proves VWF and not bg_text
# --------------------------------------------------------------------------

def test_vwf_proportional_advance_in_vram_chr(runner, built):
    b = built
    got = {}
    for slot in (0, 1):
        text = MESSAGES[slot]
        got[text] = rendered_extent(fully_revealed(runner, b, slot), b["strips"])
        assert got[text] == expected_extent(b, text), (
            f"{text!r}: rendered ink ends at px {got[text]}, the width table "
            f"says {expected_extent(b, text)}")
    # equal character count, different rendered width — the whole point
    assert len(MESSAGES[0]) == len(MESSAGES[1])
    assert got["mmmm"] - got["iiii"] == 8, (
        f"'iiii' {got['iiii']} px vs 'mmmm' {got['mmmm']} px — a fixed-width "
        f"renderer would make these equal")


def test_narrow_and_wide_strings_of_equal_length_differ_by_a_whole_tile(runner,
                                                                       built):
    """The tile-count form of the same invariant: the DIRTY SPAN differs too."""
    b = built
    tiles = {}
    for slot in (0, 1, 2):
        chr_b = fully_revealed(runner, b, slot)
        used = {c // 8 for c in ink_columns(chr_b, b["strips"])}
        tiles[MESSAGES[slot]] = max(used) + 1 if used else 0
    assert tiles == {"iiii": 3, "mmmm": 4, "....": 2}, tiles


# --------------------------------------------------------------------------
# T2 — sub-tile packing: what bg_text structurally cannot do
# --------------------------------------------------------------------------

def test_vwf_leaves_no_fixed_width_gap_after_a_narrow_glyph(runner, built):
    b = built
    text = MESSAGES[3]                      # 'End. Next: go' — narrow + wide
    chr_b = fully_revealed(runner, b, 3)
    cols = ink_columns(chr_b, b["strips"])
    assert cols, "nothing rendered"
    lo, hi = min(cols), max(cols)
    # no 8-px blank run inside the text: a fixed-width renderer placing a 3 px
    # '.' in an 8 px cell leaves exactly that.
    run = 0
    for c in range(lo, hi + 1):
        run = 0 if c in cols else run + 1
        assert run < 8, (
            f"{text!r}: {run} blank columns at px {c} — that is a fixed-width "
            f"cell, not a proportional advance")
    # and the whole string must be NARROWER than fixed-width would make it
    assert hi + 1 < len(text) * 8, (
        f"{text!r} rendered {hi + 1} px, fixed-width would be {len(text) * 8}")


# --------------------------------------------------------------------------
# T3 — cross-tile compositing, against an independent implementation
# --------------------------------------------------------------------------

def test_vwf_window_matches_an_independent_compositor_byte_for_byte(runner,
                                                                    built):
    """Subsumes the tile-straddle case: 'End.' puts 'n' at pen 7, so its ink
    spans the tile 0/1 seam, and a lost carry shows up as a byte mismatch."""
    b = built
    for slot in (0, 1, 2, 3):
        chr_b = fully_revealed(runner, b, slot)
        want = reference_canvas(b, MESSAGES[slot])
        assert chr_b == want, (
            f"slot {slot} {MESSAGES[slot]!r}: VRAM strip CHR differs from the "
            f"reference compositor at tiles "
            f"{sorted({i // TILE_BYTES for i in range(len(want)) if chr_b[i] != want[i]})}")


def test_a_glyph_really_does_straddle_a_tile_seam(runner, built):
    """Guards the test above from passing vacuously: if no message placed ink on
    both sides of a seam, the byte comparison would never exercise the carry."""
    b = built
    chr_b = fully_revealed(runner, b, 3)
    seams = 0
    for t in range(b["strips"] - 1):
        for row in range(8):
            left = chr_b[t * TILE_BYTES + row * 2]
            right = chr_b[(t + 1) * TILE_BYTES + row * 2]
            if (left & 0x01) and (right & 0x80):
                seams += 1
    assert seams > 0, ("no glyph spans a tile seam in the sample — the "
                       "cross-tile carry is untested")


# --------------------------------------------------------------------------
# T4 — the line clear, driven as a whole state cycle
# --------------------------------------------------------------------------

def test_line_clear_blanks_the_window_and_leaves_no_residue(runner, built):
    """forward (reveal) -> clear -> forward again. The wide message runs first,
    so a missing clear would leave 'mmmm' ink behind the narrow one."""
    b = built
    wide = fully_revealed(runner, b, 1)                 # 'mmmm', 4 tiles
    assert rendered_extent(wide, b["strips"]) == expected_extent(b, MESSAGES[1])

    goto_slot(runner, b, 2)                             # '....' opens: clear
    runner.frame_step(1)
    cleared = strip_chr(runner, b)
    assert not any(cleared), (
        f"window not blank on open: {sum(1 for x in cleared if x)} non-zero "
        f"bytes remain")

    narrow = fully_revealed(runner, b, 2)               # '....', 2 tiles
    assert rendered_extent(narrow, b["strips"]) == expected_extent(b, MESSAGES[2])
    # the strongest form: no byte of the narrow render may exceed the reference,
    # which is what residue from the wider message would look like
    assert narrow == reference_canvas(b, MESSAGES[2])


# --------------------------------------------------------------------------
# T5 — it is on the screen, not just in VRAM
# --------------------------------------------------------------------------

@pytest.mark.parametrize("slot", sorted(MESSAGES))
def test_vwf_row_is_visible_on_screen(runner, built, tmp_path, slot):
    """The indirection a CHR-only assertion cannot see: correct strip bytes
    that the tilemap never points at render nothing.

    Run over EVERY slot, not just the widest. Shooting only slot 3 is what let
    the contaminated blank reference through: slot 3's own ink is
    wider than anything it could bleed in from, so the defect was invisible
    there and only there. The narrow messages — 'iiii' at 23 px and '....' at
    11 px — are the ones that actually exercise the blank reference, because
    for them the outgoing message is WIDER and shows up immediately as an
    over-long extent.
    """
    b = built
    from PIL import Image
    text = MESSAGES[slot]
    x0 = COL * 8
    extent = expected_extent(b, text)

    # DIFFERENTIAL, for two reasons. The row sits over the sky gradient's bright
    # haze, so a brightness threshold cannot tell VWF ink from the background;
    # and BG3's glyphs land 6 scanlines below row*8 on this scene (the reason
    # test_microzero_hud_lap scans the whole band rather than naming a y), so an
    # assumed y0 would be measuring the wrong scanlines. Shooting the row blank
    # and revealed makes every CHANGED pixel VWF ink, with no threshold and no
    # assumption about where BG3 lands.
    goto_slot(runner, b, slot)
    blank = tmp_path / f"vwf_row_blank_{slot}.png"
    shoot_blank_row(runner, b, blank)
    runner.frame_step(4 * (len(text) + 3))
    chr_b = strip_chr(runner, b)
    shown = tmp_path / f"vwf_row_shown_{slot}.png"
    runner.take_screenshot(str(shown))

    a = Image.open(blank).convert("RGB")
    c = Image.open(shown).convert("RGB")
    HUD_LINES = D.world_const("HUD_LINES")
    band = [(x, y) for y in range(HUD_LINES)
            for x in range(256)
            if a.getpixel((x, y)) != c.getpixel((x, y))]

    # The floor is DERIVED, not a magic 40: every inked column in the strip CHR
    # must produce at least one changed pixel on screen, so the changed-pixel
    # count cannot be below the inked-column count. '....' inks far fewer
    # pixels than 'End. Next: go', and a fixed threshold sized for the latter
    # would either be vacuous for it or reject it.
    cols = ink_columns(chr_b, b["strips"])
    assert len(band) >= len(cols), (
        f"{text!r}: {len(band)} pixels changed in the Mode-1 band but the "
        f"strip CHR inks {len(cols)} columns — the tilemap is probably not "
        f"pointing at the strip tiles, so correct CHR renders nothing")

    # the changed pixels must be ONE 8-scanline row, wholly inside the band...
    ys = {y for _, y in band}
    assert max(ys) - min(ys) < 8, f"ink spans {sorted(ys)} — more than one row"
    assert max(ys) < HUD_LINES, (
        f"ink at y={max(ys)} is past the Mode-1 band's last line "
        f"{HUD_LINES - 1} — the dialog row straddles the seam")
    # ...and that row must be the one race.asm DECLARES. BG3's glyphs land a
    # few scanlines below row*8 on this scene, so the ink straddles the cell
    # boundary and this has to be a two-row window rather than an exact cell.
    # Its sensitivity is honest rather than total: planting the stale `ROW = 4`
    # this finding is about turns slots 0 and 3 red but not 1 and 2, because
    # 'mmmm' and '....' have no ascender and their ink starts low enough to sit
    # inside row 4's window too. A tighter bound would have to hardcode BG3's
    # measured 6-scanline offset, which is the kind of copied constant that
    # produced the defect in the first place.
    assert ROW * 8 <= min(ys), (
        f"ink starts at y={min(ys)}, above race.asm's declared dialog row "
        f"{ROW} (y={ROW * 8}..)")
    assert max(ys) < ROW * 8 + 16, (
        f"ink ends at y={max(ys)}, past the two-row window of race.asm's "
        f"declared dialog row {ROW}")

    # ...starting at the declared column, and ending exactly where the width
    # table says. This is the on-screen form of the proportional-advance claim,
    # and the assertion the contaminated blank reference was defeating.
    xs = {x for x, _ in band}
    assert min(xs) == x0, f"ink starts at x={min(xs)}, the row starts at {x0}"
    assert max(xs) - x0 + 1 == extent, (
        f"{text!r}: on-screen ink ends at px {max(xs) - x0 + 1}, the width "
        f"table says {extent}")


# --------------------------------------------------------------------------
# T6 — the pair the phase gate names: VWF over Mode 7, with the HUD live
# --------------------------------------------------------------------------

def test_vwf_composes_with_mode7_and_the_live_hud_in_one_frame(runner, built,
                                                               tmp_path):
    """Three VBlank consumers and two renderers in a single frame: vwfq's CHR
    commit, bg_text's txt_q lap cell, and mode7_stream's ring."""
    b = built
    syms = b["syms"]
    chr_b = fully_revealed(runner, b, 3)
    assert chr_b == reference_canvas(b, MESSAGES[3]), "VWF strips wrong"

    # bg_text's fixed-width HUD is still in the tilemap, in the same frame
    map0 = syms["ES_V_TEXT_MAP"]["start"]
    attr = (7 << 10) | (1 << 13)
    hud = runner.read_bytes(VR, (map0 + 2 * 32 + 2) * 2, 12)
    want = b"".join((attr | (ord(c) - 0x20)).to_bytes(2, "little")
                    for c in "SCORE ")
    assert hud == want, "bg_text's HUD row is not intact alongside VWF"

    # ...and the live lap digit still comes through txt_q
    lap_cell = runner.read_bytes(VR, (map0 + 2 * 32 + 28) * 2, 2)
    lap_tile = int.from_bytes(lap_cell, "little") & 0x3FF
    assert lap_tile == ord("0") - 0x20, f"lap digit tile {lap_tile}"

    # ...over a Mode 7 floor that is actually drawing
    shot = tmp_path / "vwf_mode7.png"
    runner.take_screenshot(str(shot))
    from PIL import Image
    img = Image.open(shot).convert("RGB")
    # The floor is a checkerboard, so a colour count proves nothing. What only a
    # live Mode 7 transform produces is PERSPECTIVE: the same checker pattern
    # sampled at two depths must differ, and both light and dark must be present.
    row_near = [img.getpixel((x, 190)) for x in range(40, 220, 4)]
    row_far = [img.getpixel((x, 150)) for x in range(40, 220, 4)]
    lum = lambda p: sum(p)
    assert max(map(lum, row_near)) - min(map(lum, row_near)) > 200, (
        "no light/dark contrast below the seam — the Mode 7 floor is not "
        "rendering under the dialog")
    assert row_near != row_far, (
        "the floor samples identically at two depths — no perspective, so the "
        "Mode 7 transform is not live in the frame VWF is rendering into")


# --------------------------------------------------------------------------
# T7 — the init contract (feature.toml: no [init] zero, write-before-read)
# --------------------------------------------------------------------------

def test_no_uninitialized_reads_across_the_vwf_path(runner, built):
    """vwf_begin_line writes the whole canvas before anything reads it, which is
    the claim the toml makes instead of declaring [init] zero. Power-on RAM is
    random, so this is the thing that holds it."""
    b = built
    for slot in (0, 1, 2, 3):
        fully_revealed(runner, b, slot)
    runner.assert_no_uninitialized_reads()


def test_committed_bytes_landing_in_vram_stay_inside_the_declared_budget(
        runner, built):
    """The second surface: what LANDS, counted in the destination region.

    This is the shipped T8, kept but renamed and demoted. Its old docstring
    claimed a post-hoc register read could not see what was programmed, and
    used that to justify reading VRAM INSTEAD of DAS. The justification was
    wrong (see the breakpoint tests above), and the surface it chose cannot see
    an over-long DAS at all: those bytes land outside the window this counts.

    It still earns its place, because it asserts something the register read
    does not — that the bytes actually arrive in the strip tiles, and that a
    reveal frame stays inside the one-glyph two-tile span the worst case is
    derived from. Two surfaces, two different claims; the declaration↔
    implementation claim is the one above.
    """
    b = built
    declared = _declared("vblank_bytes_per_frame")
    assert declared == b["strips"] * TILE_BYTES, (
        f"declared {declared} B but the window is {b['strips'] * TILE_BYTES} B")

    goto_slot(runner, b, 3)
    prev = strip_chr(runner, b)
    worst, worst_reveal = 0, 0
    for i in range(4 * (len(MESSAGES[3]) + 2)):
        runner.frame_step(1)
        cur = strip_chr(runner, b)
        changed = [j for j in range(len(cur)) if cur[j] != prev[j]]
        if changed:
            worst = max(worst, len(changed))
            span = changed[-1] // TILE_BYTES - changed[0] // TILE_BYTES + 1
            if i > 2:                       # past the open frame's full clear
                worst_reveal = max(worst_reveal, span)
        prev = cur
    assert worst <= declared, (
        f"{worst} strip bytes changed in one frame, declared {declared}")
    assert 0 < worst_reveal <= 2, (
        f"a reveal frame touched {worst_reveal} tiles — the claim is sized on "
        f"the two-tile one-glyph bound")


# --------------------------------------------------------------------------
# T8 — declaration vs implementation: what the ROM actually PROGRAMS
# --------------------------------------------------------------------------
# Read the DMA register file AT the MDMAEN write, via a breakpoint. The shipped
# version of this test counted changed bytes inside the strip window instead,
# justifying the substitution with "DAS counts down to zero as the transfer
# runs, so a post-hoc register read cannot see what was programmed". The
# premise is true and the conclusion does not follow — the read does not have
# to be post-hoc. `MesenRunner.breakpoints` + `run_to_break` +
# `snes_state_snapshot` read the channel file at the store, before the transfer
# runs, and tests/test_dma_init_forced_blank.py:230-247 already does exactly
# this in this repo. The register-file read was the original plan; the shipped
# test moved off it.
#
# The substituted surface was blind in the direction the declaration bounds: a
# DAS bumped past the window writes into VRAM the test never reads, so the
# assertion could not move. The window count is KEPT below as a second,
# independent surface — it is a real claim about what lands — but it is no
# longer the only one, and it is no longer the one carrying the test's name.

MDMAEN = 0x420B
VWFQ_SAMPLE_FIRES = 600          # ~600 frames of race: several slot boundaries
# Budgets in EMULATED frames, not wall seconds. MEASURED: the 600
# fires cost 317 emulated frames, no break more than 1 frame from the last. The
# outer guard matters here specifically because multi-channel fires `continue`
# without appending, so the loop can spin without filling the sample. 3600
# frames is a minute of the ROM's own time — an 11x margin that host load
# cannot shrink, which is worth more than the 36x wall margin it replaces.
VWFQ_BUDGET_FRAMES = 3600
VWFQ_BREAK_FRAMES = 300


@pytest.fixture(scope="module")
def vwfq_fires(runner, built):
    """Every MDMAEN write during race, with the channel file as programmed.

    Reuses the module runner rather than building its own. MesenRunner wraps a
    SINGLETON native core, so a second live instance hijacks the first — the
    first attempt here made its own runner (following
    test_dma_init_forced_blank, which is a whole module and can afford one) and
    killed the shared one out from under the test that followed:
    `TimeoutError: frame walk timed out (frame 5057, scanline 224)`.
    Breakpoints park the emulation thread, so this block is defined LAST in the
    file and everything that frame-steps has already run.
    """
    b = built
    inc = (SUPERFORGE / "build" / "mz" / "engine_state_race.inc").read_text()

    def sym(name):
        m = re.search(rf"^{name} = (\S+)", inc, re.M)
        assert m, f"{name} not emitted — the claim did not allocate"
        v = m.group(1)
        return int(v[1:], 16) if v.startswith("$") else int(v)

    want = {"ch": sym("ES_H_VWFQ_CH"), "dmap": sym("ES_H_VWFQ_DMAP"),
            "bbad": sym("ES_H_VWFQ_BBAD")}
    canvas = sym("ES_VWF_CANVAS")
    canvas_bank = sym("ES_VWF_CANVAS_BANK")
    canvas_size = sym("ES_VWF_CANVAS_SIZE")

    r = runner
    out = []
    try:
        r.debug_break()
        hunt_start = r.ppu_frame_count()
        with r.breakpoints([(MemoryType.SnesMemory, MDMAEN, "write")]):
            while (len(out) < VWFQ_SAMPLE_FIRES
                   and r.ppu_frame_count() - hunt_start < VWFQ_BUDGET_FRAMES
                   and r.run_to_break(max_frames=VWFQ_BREAK_FRAMES)):
                s = r.snes_state_snapshot()
                mask = s.cpu_a & 0xFF
                if bin(mask).count("1") != 1:
                    continue                  # multi-channel fire: not vwfq's
                ch = mask.bit_length() - 1
                c = s.dma.channels[ch]
                out.append({"ch": ch, "dmap": c.dmap, "bbad": c.bbad,
                            "das": c.transfer_size, "bank": c.src_bank,
                            "a1t": c.src_address, "site": s.site})
    finally:
        pass                     # shared runner: the module fixture stops it
    assert out, "no MDMAEN write was ever observed — the breakpoint never fired"
    return {"fires": out, "want": want, "canvas": canvas,
            "canvas_bank": canvas_bank, "canvas_size": canvas_size}


def _declared(field):
    toml = (SUPERFORGE / "engine" / "features" / "vwf" / "feature.toml").read_text()
    line = [ln for ln in toml.splitlines() if ln.startswith(field)][0]
    return int(line.split("=")[1].split("#")[0])


def _vwfq(fires):
    """The fires whose programmed encoding matches the vwfq claim's symbols."""
    w = fires["want"]
    return [f for f in fires["fires"]
            if (f["ch"], f["dmap"], f["bbad"]) == (w["ch"], w["dmap"], w["bbad"])]


def test_the_vwfq_sample_actually_caught_vwfq_transfers(vwfq_fires):
    """Non-vacuity. Every assertion below filters to vwfq's encoding, so an
    empty filter would make all of them pass while measuring nothing — the
    exact shape of failure this file's rules exist to prevent."""
    mine = _vwfq(vwfq_fires)
    assert len(mine) >= 8, (
        f"only {len(mine)} of {len(vwfq_fires['fires'])} sampled MDMAEN fires "
        f"matched vwfq's emitted encoding "
        f"(ch={vwfq_fires['want']['ch']}, dmap=${vwfq_fires['want']['dmap']:02X}, "
        f"bbad=${vwfq_fires['want']['bbad']:02X}) — the sample is too thin to "
        f"bound anything")


def test_programmed_dma_matches_the_vwfq_declaration_in_every_field(vwfq_fires):
    """The claim says: 224 B, 1 transfer, mode 1, VMDATAL, from the canvas.
    Read what the ROM PROGRAMS into the channel file at each MDMAEN write."""
    f = vwfq_fires
    mine = _vwfq(f)
    declared = _declared("vblank_bytes_per_frame")
    assert declared == f["canvas_size"] - TILE_BYTES, (
        f"declared {declared} B but the uploadable window (canvas minus the "
        f"spill guard) is {f['canvas_size'] - TILE_BYTES} B")

    over = [x["das"] for x in mine if x["das"] > declared]
    assert not over, (
        f"vwfq programmed DAS {sorted(set(over))} B, past the declared "
        f"{declared} B/frame — bytes the declaration does not account for, "
        f"landing in VRAM beyond the strip window")

    bad_bank = {hex(x["bank"]) for x in mine if x["bank"] != f["canvas_bank"]}
    assert not bad_bank, (
        f"vwfq sourced from bank(s) {bad_bank}, not the canvas's "
        f"${f['canvas_bank']:02X}")

    lo, hi = f["canvas"], f["canvas"] + f["canvas_size"]
    outside = {hex(x["a1t"]) for x in mine if not lo <= x["a1t"] < hi}
    assert not outside, (
        f"vwfq sourced from {outside}, outside the canvas claim "
        f"[${lo:04X}..${hi:04X})")

    sites = {x["site"] for x in mine}
    assert len(sites) == 1, (
        f"vwfq fires from {len(sites)} sites {sites}; the claim declares "
        f"{_declared('vblank_transfers_per_frame')} transfer per frame, which "
        f"the single no-op-unless-dirty commit is what makes true")


def test_the_declared_budget_is_tight_and_not_merely_an_upper_bound(vwfq_fires):
    """The worst case the claim is SIZED on must actually occur in the sample.

    `das <= 224` would also pass if the ROM never transferred more than 32 B —
    the bound would be true and the declaration three times too large, which is
    a budget bug the allocator would have charged the whole scene for. The
    whole-window clear at each slot open is the frame that spends it, so a
    sample crossing a slot boundary must observe exactly 224.
    """
    mine = _vwfq(vwfq_fires)
    assert mine, ("no fire matched vwfq's encoding — see "
                  "test_the_vwfq_sample_actually_caught_vwfq_transfers, which "
                  "is the guard for this")
    declared = _declared("vblank_bytes_per_frame")
    seen = sorted({x["das"] for x in mine})
    assert max(seen) == declared, (
        f"vwfq's largest programmed DAS was {max(seen)} B but the claim "
        f"declares {declared} B/frame (all sizes seen: {seen}) — either the "
        f"sample never crossed a line clear, or the declaration is loose")
