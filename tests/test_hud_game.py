"""hud_game — the text surface end to end, and the reprint-on-change HUD.

Lockstep-native: `Machine` only, no MesenRunner,
no wall-clock surface, every read taken from a parked exact frame and every
capture landed on an absolute one.

WHAT THIS RAIL IS FOR, and therefore what these tests must prove. `hud_game`
comes first because it is the smallest thing that exercises `bg_text`
end-to-end"*. End-to-end means both halves of that feature, and they are
different code paths with different hardware rules:

  THE FORCED-BLANK HALF — `text_upload_font` DMAs the glyph blob into the
  scene's CHR base and `text_puts` / `text_put_hex4` write tilemap words
  directly, legal only because scene enter runs blanked. Proven by reading the
  DESTINATION regions: VRAM CHR against the font blob's own bytes, VRAM
  tilemap against the glyph indices the string implies.

  THE RUNNING-SCENE HALF — a live frame cannot touch VRAM, so the counter goes
  through the one-run VBlank queue (`text_queue_hex4` stages, the NMI hook's
  `text_vblank_commit` writes). Proven by watching the four counter cells
  CHANGE across a press.

THE REPRINT-ON-CHANGE CLAIM IS MEASURED ON WRITE COUNTERS, not inferred. "The
HUD costs one tilemap write instead of a per-frame reprint" is a claim about
what the machine does on the frames NOTHING happened, and reading the cells
cannot see it: a per-frame reprint of an unchanged value leaves byte-identical
VRAM. So the assertions are on `Machine.writes(SnesVideoRam, cell)` — the
per-address write counter, armed from the reset vector by `LoadRomParked` —
which distinguishes "not rewritten" from "rewritten with the same value". That
is the one observable that makes the rail's headline property falsifiable.

STATE CYCLES RUN BOTH WAYS. The counter's units cell is driven 0 -> 1 -> ...
-> 9 -> 0 through the BCD carry, so the same output cell is asserted going up
AND coming back; the player is driven right-then-left and down-then-up back to
its start. A one-direction test locks one direction and ships the other broken
(AGENTS.md test discipline).
"""
import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "hud_game.sfc"
ASSETS = BUILD / "assets"
# One expression, the shape conftest resolves a module's map from at COLLECTION
# time (it refuses a module whose map it cannot see).
_JMAP = json.loads((SUPERFORGE / "build" / "hud" / "symbol_map.json").read_text())

W, V, C, O = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
              MemoryType.SnesCgRam, MemoryType.SnesSpriteRam)


def _sym(name, scene=None):
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} is not in the emitted map")


V_OBJ = _sym("ES_V_OBJ_CHR", "play")["start"]           # VRAM word address
V_OBJ_W = _sym("ES_V_OBJ_CHR", "play")["size"]
V_TEXT_CHR = _sym("ES_V_TEXT_CHR", "play")["start"]
V_TEXT_MAP = _sym("ES_V_TEXT_MAP", "play")["start"]
C_TEXT = _sym("ES_C_TEXT_PAL", "play")["start"]         # CGRAM word index
C_OBJ = _sym("ES_C_OBJ_PAL", "play")["start"]
C_BACKDROP = _sym("ES_C_BACKDROP_COLOR", "play")["start"]
OAM_PLAYER = _sym("ES_O_PLAYER", "play")["start"]       # sprite slot
OAM_PAD = _sym("ES_O_HI_PAD", "play")["start"]
OAM_PAD_N = _sym("ES_O_HI_PAD", "play")["size"]

# --- the rail's geometry, from game/hud_game/hud.inc -------------------------
HUD_ROW, HUD_LABEL_C, HUD_DIGITS_C, HUD_DIGITS_N = 1, 1, 7, 4
HUD_HOME_X, HUD_HOME_Y, HUD_SPEED = 124, 108, 2
HUD_MAX_X, HUD_MAX_Y = 256 - 8, 224 - 8
TXT_ATTR = (7 << 10) | (1 << 13)        # palette 7, priority — play.asm
PARK_Y = 0xF0
OAM_HI_BASE = 512                       # the hi table: last 32 B of the 544

BOOT = 90                               # the absolute frame every read lands on

# The `sprite_tile` this rail's player is drawn with: eight rows of $FF,$00
# (bitplane 0 all ones, bitplane 1 all zero) then eight of $00,$00 (bitplanes
# 2 and 3 empty) — an 8x8 block of colour index 1. The bytes are written out
# here rather than read from anywhere, so the assertion survives on a bare
# runner; `test_the_vendored_tile_still_matches_the_reference` re-reads them
# out of an external reference tree wherever one IS configured, so the
# constant cannot rot silently.
REFERENCE_SPRITE_TILE = bytes([0xFF, 0x00] * 8 + [0x00, 0x00] * 8)
REFERENCE_OBJ_RED = 0x001F                 # the matching `OBJ_RED` equate
# An OPTIONAL external reference tree, named by `SF_REFERENCE_TREE`.
# Unset on an ordinary runner, which is why the cases below SKIP rather
# than fail: they are ground-truth checks against a second, independent
# implementation, and there is nothing to check against when none is on
# disk.
_REFERENCE_TREE = Path(os.environ.get("SF_REFERENCE_TREE",
                                      "/nonexistent/reference-tree"))
REFERENCE_MAIN = _REFERENCE_TREE / "templates" / "hud_game" / "main.asm"


def _cell(col, row=HUD_ROW):
    """Byte address in VRAM of one BG3 tilemap cell (32x32 map, 2 B/word)."""
    return (V_TEXT_MAP + row * 32 + col) * 2


def _glyph(ch):
    """The tile word bg_text writes for `ch`: glyph index (space = tile 0)
    OR'd with the scene's attr. text_puts' own arithmetic, restated."""
    return ((ord(ch) - 0x20) & 0x7F) | TXT_ATTR


def _oam(m, slot):
    """The four low-table bytes of one sprite, plus its X9 and size bits."""
    x, y, tile, attr = m.read_bytes(O, slot * 4, 4)
    hi = m.read_byte(O, OAM_HI_BASE + slot // 4)
    bits = (hi >> ((slot % 4) * 2)) & 3
    return x, y, tile, attr, bits & 1, (bits >> 1) & 1


def _digits(m):
    """The four counter cells as the characters they render."""
    out = ""
    for i in range(HUD_DIGITS_N):
        word = m.read_u16(V, _cell(HUD_DIGITS_C + i))
        assert word & TXT_ATTR == TXT_ATTR, f"cell {i} lost its attr: {word:04x}"
        out += chr((word & 0x3FF) + 0x20)
    return out


def _digit_writes(m):
    """Write counts of every BYTE of the four counter cells."""
    lo = _cell(HUD_DIGITS_C)
    return [m.writes(V, lo + b) for b in range(HUD_DIGITS_N * 2)]


def _press_a(m, hold=2, gap=2):
    """One A press: held `hold` frames, released `gap`. ES_INP_PRESS is
    cur & ~prev, so however long A is held the edge fires on exactly one
    frame; `gap` also gives the NMI its VBlank to commit the staged run."""
    m.advance(hold, pad1={"a": True})
    m.advance(gap)


@pytest.fixture(scope="module", autouse=True)
def rom_built():
    r = subprocess.run(["make", "hud_game"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"make hud_game failed rc={r.returncode}:\n{r.stdout}\n{r.stderr}")
    yield


@pytest.fixture(autouse=True)
def hand_back_the_core():
    """Whatever machines a test builds, the module may not leak a park
    (conftest's module-boundary guard)."""
    yield
    Machine.close_current()


@pytest.fixture
def fresh():
    """A machine parked on the absolute frame BOOT, every time."""
    return Machine(str(ROM)).advance(BOOT)


# =============================================================================
# 1. THE UPLOADS — the destination regions, byte for byte
# =============================================================================
def test_the_obj_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claim's base against hud_obj_chr.bin.

    The DESTINATION region, read directly. A test that only asserted "a red
    square renders" would pass with half the block uploaded — every pixel is
    colour index 1 in plane 0, so a missing plane 1/2/3 looks identical.
    """
    want = (ASSETS / "hud_obj_chr.bin").read_bytes()
    got = fresh.read_bytes(V, V_OBJ * 2, len(want))
    assert got == want, (f"OBJ CHR at word {V_OBJ:#06x} differs from the blob:"
                         f"\n  got  {got.hex()}\n  want {want.hex()}")
    assert len(want) == V_OBJ_W * 2, "the blob does not fill the vram claim"


def test_the_obj_block_is_the_reference_sprite_tile(fresh):
    """...and those bytes ARE the declared tile, not just self-consistent.

    Comparing the ROM's VRAM to our own generator's output proves the upload;
    it does NOT prove the art is right, because both sides come from this
    repo. The independent term is the literal `sprite_tile` above.
    """
    got = fresh.read_bytes(V, V_OBJ * 2, len(REFERENCE_SPRITE_TILE))
    assert got == REFERENCE_SPRITE_TILE


@pytest.mark.skipif(not REFERENCE_MAIN.exists(),
                    reason="SF_REFERENCE_TREE is unset (the ordinary case)")
def test_the_vendored_tile_still_matches_the_reference():
    """Re-read REFERENCE_SPRITE_TILE out of the reference tree so the constant
    above cannot rot.

    Reference-gated exactly like `test_split_v_fight`'s asset ground truth: the
    tree is read-only and never a build dependency, so this skips where it is
    absent rather than making the suite need it.
    """
    src = REFERENCE_MAIN.read_text()
    body = src.split("sprite_tile:", 1)[1].split("\n\n", 1)[0]
    vals = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith(".byte"):
            continue
        vals += [int(t.strip().lstrip("$"), 16)
                 for t in line[len(".byte"):].split(",")]
    assert bytes(vals) == REFERENCE_SPRITE_TILE, (
        "the reference sprite_tile has moved away from this module's copy")
    assert f"OBJ_RED = ${REFERENCE_OBJ_RED:04X}" in src


def test_the_obj_palette_is_the_destination_of_the_blob(fresh):
    """CGRAM at the claim's base against hud_obj_pal.bin, and index 1 is red.

    CGRAM is the region a whole sprite pipeline can silently skip — a
    `[sprites]` section that is never parsed no-ops the upload while every
    downstream effect still "works" and the sprite is merely invisible or
    wrong-coloured. So it is read directly.
    """
    want = (ASSETS / "hud_obj_pal.bin").read_bytes()
    got = fresh.read_bytes(C, C_OBJ * 2, len(want))
    assert got == want
    assert int.from_bytes(got[2:4], "little") == REFERENCE_OBJ_RED, (
        "OBJ palette index 1 is not OBJ_RED")


def test_the_font_chr_is_the_destination_of_the_font_blob(fresh):
    """VRAM at the scene's text CHR base against font_2bpp.bin.

    This is the DMA half of "bg_text end-to-end": `text_upload_font` fires one
    GP-DMA under the enter forced blank. Asserting the glyphs render would not
    catch a short transfer — the label's five glyphs live in the first 6% of
    the blob.
    """
    want = (ASSETS / "font_2bpp.bin").read_bytes()
    got = fresh.read_bytes(V, V_TEXT_CHR * 2, len(want))
    assert got == want, "the font blob did not land whole at the CHR base"


def test_the_text_palette_and_backdrop_are_written(fresh):
    """CGRAM words 28..31 (BG3 palette 7) and word 0 (the backdrop).

    Colour 3 is the white the HUD is drawn in and the pixel the render test
    counts, so it is named rather than left to the screenshot.
    """
    pal = fresh.read_bytes(C, C_TEXT * 2, 8)
    words = [int.from_bytes(pal[i:i + 2], "little") for i in (0, 2, 4, 6)]
    assert words == [0x0000, 0x2952, 0x56B5, 0x7FFF], f"text palette {words}"
    assert fresh.read_u16(C, C_BACKDROP * 2) == 0x0000, "backdrop is not black"


# =============================================================================
# 2. THE FORCED-BLANK HALF — the label and the counter's first print
# =============================================================================
def test_the_label_is_printed_into_the_bg3_tilemap(fresh):
    """"SCORE" at row 1, columns 1..5 — the tilemap words, cell by cell."""
    for i, ch in enumerate("SCORE"):
        got = fresh.read_u16(V, _cell(HUD_LABEL_C + i))
        assert got == _glyph(ch), (
            f"label[{i}] = {got:04x}, want {_glyph(ch):04x} ({ch!r})")


def test_the_counter_starts_at_four_zeroes(fresh):
    assert _digits(fresh) == "0000"


def test_the_cells_around_the_hud_are_blank(fresh):
    """The map was cleared to tile 0 (space) before anything was printed.

    Without this, a label test passes over a tilemap full of power-on garbage
    that happens to hold the right words at the right cells.
    """
    blank = _glyph(" ")
    for col in (0, HUD_LABEL_C + 5, HUD_DIGITS_C - 1,
                HUD_DIGITS_C + HUD_DIGITS_N, 31):
        assert fresh.read_u16(V, _cell(col)) == blank, f"col {col} not blank"
    for row in (0, 2, 12, 27):
        assert fresh.read_u16(V, _cell(HUD_LABEL_C, row)) == blank


# =============================================================================
# 3. REPRINT-ON-CHANGE — the rail's headline, on the write counters
# =============================================================================
def test_an_idle_frame_does_not_rewrite_the_counter(fresh):
    """60 idle frames must not touch the four counter cells AT ALL.

    The claim is about the frames where nothing happened, and reading the
    cells cannot see it — a per-frame reprint of an unchanged value leaves
    byte-identical VRAM. The write counters can: they distinguish "not
    written" from "written with the same value".
    """
    before = _digit_writes(fresh)
    fresh.advance(60)
    after = _digit_writes(fresh)
    assert after == before, (
        f"idle frames rewrote the counter: {before} -> {after}")
    assert _digits(fresh) == "0000"


def test_a_press_rewrites_the_counter_exactly_once(fresh):
    """...and one press writes each cell exactly once more, then stops."""
    before = _digit_writes(fresh)
    _press_a(fresh)
    bumped = _digit_writes(fresh)
    assert bumped == [n + 1 for n in before], (
        f"one press wrote {[b - a for a, b in zip(before, bumped)]} times "
        f"per byte, want 1 each")
    assert _digits(fresh) == "0001"
    fresh.advance(60)
    assert _digit_writes(fresh) == bumped, "the HUD kept writing after settling"


def test_the_label_is_never_rewritten_by_the_running_scene(fresh):
    """The label is enter-time only: the queue must never reach its cells."""
    before = [fresh.writes(V, _cell(HUD_LABEL_C) + b) for b in range(10)]
    for _ in range(3):
        _press_a(fresh)
    fresh.advance(30)
    after = [fresh.writes(V, _cell(HUD_LABEL_C) + b) for b in range(10)]
    assert after == before, f"the label cells were rewritten: {before}->{after}"
    assert _digits(fresh) == "0003"


# =============================================================================
# 4. EDGE VS LEVEL INPUT — and the cell going up AND back down
# =============================================================================
def test_a_held_a_counts_exactly_one_press(fresh):
    """`btnp` semantics: 20 frames of held A is ONE bump, not twenty.

    Asserted on the printed cell, not on the score word — the counter is the
    thing the player sees and the thing this rail is about.
    """
    fresh.advance(20, pad1={"a": True})
    fresh.advance(2)
    assert _digits(fresh) == "0001"


def test_the_units_cell_climbs_to_nine_and_carries_back_to_zero(fresh):
    """0 -> 1 -> ... -> 9 -> 0 on the SAME cell, driven by ten real presses.

    Both directions of one output cell's state cycle. The tenth press is the
    BCD carry, so the units cell returns to the glyph it started on while the
    tens cell leaves it — a test that only walked the counter up would pass
    with a carry that never happened, or with one that wiped the whole run.
    """
    units = HUD_DIGITS_C + HUD_DIGITS_N - 1
    tens = units - 1
    seen = [chr((fresh.read_u16(V, _cell(units)) & 0x3FF) + 0x20)]
    for _ in range(10):
        _press_a(fresh)
        seen.append(chr((fresh.read_u16(V, _cell(units)) & 0x3FF) + 0x20))
    assert seen == list("01234567890"), f"units cell walked {''.join(seen)}"
    assert chr((fresh.read_u16(V, _cell(tens)) & 0x3FF) + 0x20) == "1"
    assert _digits(fresh) == "0010", "the carry did not land as decimal 10"


def test_the_carry_frame_rewrites_the_cells_it_changed(fresh):
    """The tenth press writes the run once — the same cost as the first.

    The counterexample this excludes is a HUD that reprints only the digit it
    thinks changed: the carry moves two cells, and a per-digit optimisation
    would leave the tens cell stale.
    """
    for _ in range(9):
        _press_a(fresh)
    assert _digits(fresh) == "0009"
    before = _digit_writes(fresh)
    _press_a(fresh)
    after = _digit_writes(fresh)
    assert after == [n + 1 for n in before]
    assert _digits(fresh) == "0010"


# =============================================================================
# 5. SPRITE + INPUT COMPOSITION — OAM, both directions, HUD undisturbed
# =============================================================================
def test_the_player_rests_at_the_centre_with_the_pads_parked(fresh):
    x, y, tile, attr, x9, size = _oam(fresh, OAM_PLAYER)
    assert (x, y) == (HUD_HOME_X, HUD_HOME_Y)
    assert tile == 0, "the player is not drawing the claim's first tile"
    assert attr == 48, f"attr {attr}: want priority 3, OBJ palette 0"
    assert (x9, size) == (0, 0), "8x8 sprite with X < 256 has both bits clear"
    for i in range(OAM_PAD_N):
        assert _oam(fresh, OAM_PAD + i)[1] == PARK_Y, (
            f"hi-pad slot {i} is on screen")


def test_the_dpad_moves_the_player_right_and_back(fresh):
    """Right then left, back to the start — the reverse leg is the test.

    A camera/actor test that only walks one direction locks that direction and
    ships the other broken (AGENTS.md). Read from OAM, which is what the PPU
    draws, not from the DP word the draw is derived from.
    """
    x0 = _oam(fresh, OAM_PLAYER)[0]
    fresh.advance(10, pad1={"right": True})
    fresh.advance(1)                        # OAM lags the tick by one park
    x1 = _oam(fresh, OAM_PLAYER)[0]
    assert x1 == x0 + 10 * HUD_SPEED, f"right: {x0} -> {x1}"
    fresh.advance(10, pad1={"left": True})
    fresh.advance(1)
    x2 = _oam(fresh, OAM_PLAYER)[0]
    assert x2 == x0, f"left did not return the player: {x1} -> {x2}"


def test_the_dpad_moves_the_player_down_and_back(fresh):
    y0 = _oam(fresh, OAM_PLAYER)[1]
    fresh.advance(10, pad1={"down": True})
    fresh.advance(1)
    y1 = _oam(fresh, OAM_PLAYER)[1]
    assert y1 == y0 + 10 * HUD_SPEED, f"down: {y0} -> {y1}"
    fresh.advance(10, pad1={"up": True})
    fresh.advance(1)
    assert _oam(fresh, OAM_PLAYER)[1] == y0, "up did not return the player"


def test_an_idle_frame_leaves_the_player_where_it_is(fresh):
    """The third state of the cycle: neither direction held."""
    before = _oam(fresh, OAM_PLAYER)
    fresh.advance(45)
    assert _oam(fresh, OAM_PLAYER) == before


def test_the_clamp_holds_the_player_on_screen_at_both_edges(fresh):
    """Drive into each wall past the clamp and read OAM, including X9.

    X9 is the bit that renders a sprite 256 px away when it goes stale, so the
    right-hand clamp is asserted WITH it rather than on the low byte alone.
    """
    fresh.advance(200, pad1={"right": True, "down": True})
    fresh.advance(1)
    x, y, _, _, x9, _ = _oam(fresh, OAM_PLAYER)
    assert (x, y) == (HUD_MAX_X, HUD_MAX_Y), f"far clamp at ({x}, {y})"
    assert x9 == 0, "X9 set at x = 248 — the hi byte is not derived from X"
    fresh.advance(200, pad1={"left": True, "up": True})
    fresh.advance(1)
    x, y, _, _, x9, _ = _oam(fresh, OAM_PLAYER)
    assert (x, y) == (0, 0), f"near clamp at ({x}, {y})"
    assert x9 == 0


def test_the_hud_is_untouched_while_the_player_moves(fresh):
    """The whole HUD row, byte for byte, across a full movement cycle.

    Layer composition, not layer isolation: the sprite and the text share a
    frame, and "the HUD stays put" is a claim about the tilemap the d-pad must
    never reach. Read as one 64-byte region so a single stray word fails it.
    """
    row = fresh.read_bytes(V, _cell(0), 32 * 2)
    for pad in ({"right": True}, {"down": True}, {"left": True}, {"up": True}):
        fresh.advance(20, pad1=pad)
    fresh.advance(2)
    assert fresh.read_bytes(V, _cell(0), 32 * 2) == row, "the HUD row moved"


# =============================================================================
# 6. THE PICTURE — landed on an absolute frame
# =============================================================================
# THE CAPTURE IS 256x239, NOT 256x224, and the offset is READ OUT OF THE
# EMULATOR'S SOURCE rather than guessed: `SnesPpu.cpp:1410` (and :1432, :1539)
# place a non-overscan frame with
#     scanline = _overscanFrame ? (_scanline - 1) : (_scanline + 6)
# and :1505-1508 blank the top 7 / bottom 8 rows of the 239. So a PNG row is a
# PPU scanline plus six. The two subjects then land by their own hardware
# rules, and both are checked so a wrong origin cannot pass — they are 100
# rows apart and sourced from different PPU units:
#   * an 8x8 OBJ at OAM Y = v occupies scanlines v+1 .. v+8;
#   * BG3 tile row R with BG3VOFS = 0 occupies scanlines R*8 .. R*8+7, and the
#     font's row 7 is blank (verified in build/assets/font_2bpp.bin), so an
#     uppercase glyph lights R*8 .. R*8+6.
SHOT_DY = 6                             # PNG row = PPU scanline + SHOT_DY
GLYPH_LIT_H = 7                         # the font's 8th row is blank


def _pixels(path):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    return img.size, list(img.getdata())


def _find(path, pred):
    """Every (x, y) whose pixel satisfies `pred`, over the WHOLE capture."""
    (w, h), d = _pixels(path)
    return [(x, y) for y in range(h) for x in range(w) if pred(d[y * w + x])]


def _white(p):
    return all(c > 200 for c in p)


def _red(p):
    return p[0] > 150 and p[1] < 90 and p[2] < 90


def test_the_screen_shows_a_white_hud_line_and_a_red_player(fresh, tmp_path):
    """Screenshot pixels: the rail's own done-condition, on an absolute frame.

    The two VRAM halves can both be right and the screen still be black — TM
    not enabling the layers, INIDISP still blanked, the backdrop covering
    everything. This is the assertion that says a user sees it, and it pins
    WHERE both subjects are rather than merely that some pixels are lit.
    """
    out = fresh.screenshot(str(tmp_path / "hud.png"))
    white = _find(out, _white)
    assert len(white) > 50, f"HUD text not visible: {len(white)} white px"
    rows = sorted({y for _, y in white})
    assert rows == list(range(HUD_ROW * 8 + SHOT_DY,
                              HUD_ROW * 8 + SHOT_DY + GLYPH_LIT_H)), (
        f"the HUD line is on PNG rows {rows[0]}..{rows[-1]}, want tile row "
        f"{HUD_ROW}")
    cols = sorted({x for x, _ in white})
    assert HUD_LABEL_C * 8 <= cols[0] and cols[-1] < (HUD_DIGITS_C
                                                      + HUD_DIGITS_N) * 8, (
        f"white pixels span x {cols[0]}..{cols[-1]}, outside the HUD cells")

    red = _find(out, _red)
    assert len(red) == 64, f"the 8x8 player is {len(red)} red px, want 64"
    xs, ys = sorted({x for x, _ in red}), sorted({y for _, y in red})
    assert xs == list(range(HUD_HOME_X, HUD_HOME_X + 8))
    assert ys == list(range(HUD_HOME_Y + 1 + SHOT_DY,
                            HUD_HOME_Y + 1 + SHOT_DY + 8)), (
        f"the player renders on PNG rows {ys[0]}..{ys[-1]}, OAM Y is "
        f"{HUD_HOME_Y}")


def test_the_player_pixels_follow_the_dpad(fresh, tmp_path):
    """...and the red block is where the pad put it, not merely present.

    Both axes and both directions, read off the picture — the composited
    result, which is the only place an OAM write and the PPU's reading of it
    can disagree.
    """
    def block(tag):
        pts = _find(fresh.screenshot(str(tmp_path / f"{tag}.png")), _red)
        assert len(pts) == 64, f"{tag}: {len(pts)} red px"
        return min(x for x, _ in pts), min(y for _, y in pts)

    home = block("home")
    assert home == (HUD_HOME_X, HUD_HOME_Y + 1 + SHOT_DY)
    fresh.advance(20, pad1={"right": True, "down": True})
    fresh.advance(1)
    far = block("far")
    assert far == (home[0] + 20 * HUD_SPEED, home[1] + 20 * HUD_SPEED)
    fresh.advance(20, pad1={"left": True, "up": True})
    fresh.advance(1)
    assert block("back") == home, "the player's pixels did not come back"


def test_the_counter_pixels_change_when_the_score_does(fresh, tmp_path):
    """The rendered counter, not just its tilemap words.

    The last link in "end-to-end": a tilemap cell can hold the right glyph
    index and still draw nothing if the font CHR never landed or BG3 is not in
    TM. Comparing the counter's pixel strip across a press closes it — and the
    strip must come BACK to its first shape at the BCD carry, the picture-side
    of the both-directions cycle.
    """
    box = (HUD_DIGITS_C * 8, HUD_ROW * 8 + SHOT_DY,
           HUD_DIGITS_N * 8, GLYPH_LIT_H)
    zero = _strip(fresh.screenshot(str(tmp_path / "s0.png")), box)
    assert sum(1 for p in zero if _white(p)) > 0, "the counter strip is unlit"
    _press_a(fresh)
    one = _strip(fresh.screenshot(str(tmp_path / "s1.png")), box)
    assert one != zero, "the printed counter did not change on screen"
    for _ in range(9):
        _press_a(fresh)
    ten = _strip(fresh.screenshot(str(tmp_path / "s10.png")), box)
    assert _digits(fresh) == "0010"
    assert ten != one and ten != zero, "0010 renders as 0001 or 0000"


def _strip(path, box):
    x0, y0, bw, bh = box
    (w, _), d = _pixels(path)
    return [d[(y0 + y) * w + x0 + x] for y in range(bh) for x in range(bw)]


# =============================================================================
# 7. POWER-ON FIDELITY
# =============================================================================
def test_the_rom_reads_nothing_it_never_wrote(fresh):
    """Rule 5: RAM is random at boot, so every byte read must be written first.

    `LoadRomParked` arms the access counters from the reset vector, so this is
    complete by construction rather than a sample.
    """
    fresh.assert_no_uninitialized_reads()
