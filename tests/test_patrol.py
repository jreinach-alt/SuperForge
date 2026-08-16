"""patrol — the composition rail, asserted against what was drawn.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)`, which
lands on the ABSOLUTE frame N by construction.

WHAT THIS RAIL IS, and therefore what these cases have to prove. Its own
source states its done-conditions:

    - boots; terrain + red player + 2 magenta enemies rendered; HITS 00000
    - both enemies bounce inside their EXACT bounds forever
    - walking into an enemy's beat -> contact -> respawn at (200,200), HITS
      ticks (text), and the player can keep playing
    - standing outside the beats -> no hits

Those are the test surface, and on top of them the reason this rail exists
at all: THE COMPOSITION — one game_loop driving sprites, BG terrain, a text
HUD, tile collision, jump physics and enemy patrol at once, with each surface
asserted on its own output region.

THE PATROL MECHANISM UNDER TEST (read out of `sf_enemy.inc`, not out of any
prose about it): an enemy paces at 1 px/frame and turns — a direction flip with
NO move that frame — for EITHER of two reasons: the tentative box overlaps a
solid (wall ahead), or the LEADING bottom corner (front edge: newx+7 walking
right, newx walking left) has no solid under it (ledge ahead). The ground
enemy's beat is bounded by two walls, the platform enemy's by two ledges, so
the two turn causes are discriminated by the two enemies' EXACT rest bounds:

    E1 (ground, walls):   ex 88..152  (wall faces at 88-1 and 152+8)
    E2 (platform, ledges): ex 32..64  (platform spans px 32..71; at the right
        bound the box is 64..71 — flush with the platform's LAST pixel. A
        trailing-corner probe would rest at 71 with a 7 px overhang; no ledge
        probe at all would walk to the border at 240. The bound 64 IS the
        leading-corner lesson.)

FRAME ACCOUNTING, measured on this ROM (the convention its sibling rails
share): a parked read after `advance(N)` shows tick (N-1)'s committed state — the
constant one-commit presentation lag of the park point. The triangle-wave
oracles below take the TICK number; every caller passes `frame - 1`.

READ ORDER IS LOAD-BEARING: a parked OAM read and the NEXT
screenshot describe the same committed frame; an OAM read AFTER a shot is
one commit ahead of that shot's picture. Every case below reads OAM before
it captures.

NO PHASE RECOVERY NEEDED, and why that is stated rather than skipped: the
periodic-background trap applies to DISPLACEMENT recovery on a scrolling
pattern. This rail's BG never scrolls (the scroll is pinned at
enter, as maze's does), so every background claim here is exact byte
identity of a window that is asserted to move by ZERO, and the moving things
(the actors) are asserted on OAM + their solid-colour bboxes, which are not
periodic.
"""
import os
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "patrol.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "pat" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="play"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_CHR = _sym("ES_V_PAT_CHR")["start"]           # BG CHR page, VRAM words
V_MAP = _sym("ES_V_PAT_MAP_V")["start"]         # BG tilemap base, VRAM words
V_OBJ = _sym("ES_V_POBJ_CHR")["start"]          # OBJ CHR page, VRAM words
V_TXT = _sym("ES_V_TEXT_MAP")["start"]          # BG3 text tilemap, VRAM words
C_PAL = _sym("ES_C_PAT_PAL")["start"]           # BG palette group 0, CGRAM
C_OBJ = _sym("ES_C_POBJ_PAL")["start"]          # OBJ palettes 0+1, CGRAM words

# --- the rail's geometry (game/patrol/patrol.inc, re-derived) ----------------
MAP_DIM = 32
SPAWN = (200, 200)
SPEED = 2                               # player px/frame
E1_Y, E2_Y = 200, 152                   # the two beat rows
E1_LO, E1_HI = 88, 152                  # ground beat: wall-bounded
E2_LO, E2_HI = 32, 64                   # platform beat: ledge-bounded
E1_PERIOD = 2 * (E1_HI - E1_LO + 1)     # 130: width 64 each way + 1 turn frame
E2_PERIOD = 2 * (E2_HI - E2_LO + 1)     # 66
WALL_L_REST = 168                       # flush against wall col 20 (160..167)
BORDER_R_REST = 240                     # flush against border col 31 (248..255)
JUMP_APEX_Y = 161                       # 200 - 38.25 px of arc, floor'd

# --- the picture -------------------------------------------------------------
# Mesen hands back a 256x239 frame; the active 224 scanlines start at PNG row
# 7 (the measured constant every rail here shares). With patrol_bg's
# enter-time VOFS -1 (world y = screen y) and the OBJ +1 scanline rule, BOTH
# surfaces land at PNG row = its coordinate + 7 — re-verified here by the boot
# test: the player at OAM (200, 200) must occupy PNG (200..207, 207..214).
PIC_Y0, PIC_H, PIC_W = 7, 224, 256

BLACK = (0, 0, 0)                       # word 0: the backdrop
GREY = (115, 115, 115)                  # BG_GREY $39CE through (v<<3)|(v>>2)
RED = (255, 0, 0)                       # OBJ_RED $001F (player)
MAGENTA = (255, 0, 255)                 # OBJ_MAGEN $7C1F (both enemies)
WHITE = (255, 255, 255)                 # the HUD glyph colour

LEVEL_CELLS = 32 + 2 * 26 + 4 + 5       # ground + borders + low walls + plat
                                        # = 93 grey tiles = 5952 grey px

TXT_ATTR = (7 << 10) | (1 << 13)        # BG3 palette 7, priority 1
HUD_ROW, LABEL_C, DIGITS_C = 1, 1, 6    # "HITS" col 1; four digits col 6..9


def _glyph(ch):
    return TXT_ATTR | (ord(ch) - 32)


BOOT = 90                               # an absolute frame, well past the fade


@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle."""
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make patrol` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


# --- helpers -----------------------------------------------------------------

def _pixels(machine, name):
    path = machine.take_screenshot(str(BUILD / "shots" / f"pat_{name}.png"))
    with Image.open(path) as im:
        return list(im.convert("RGB").getdata())


def _at(px, x, y):
    return px[y * PIC_W + x]


def _bbox(px, colour):
    pts = [(x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W) if _at(px, x, y) == colour]
    assert pts, f"no {colour} pixels on screen"
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return len(pts), min(xs), max(xs), min(ys), max(ys)


def _actors(m):
    """OAM entries 0..2 as (x, y) triples — player, E1, E2."""
    b = m.read_bytes(O, 0, 12)
    return [(b[i * 4], b[i * 4 + 1]) for i in range(3)]


def _hits_cells(m):
    raw = m.read_bytes(V, (V_TXT + HUD_ROW * 32 + DIGITS_C) * 2, 8)
    return [raw[i * 2] | (raw[i * 2 + 1] << 8) for i in range(4)]


def _expected_e1(t):
    """The ground patroller's triangle wave, by TICK number (wall turns).

    From 120 walking right: +1/frame to 152 (tick 32), one turn frame (the
    flip commits no move), -1/frame to 88 (tick 97), one turn frame, back up.
    """
    if t <= 0:
        return 120
    t = (t - 1) % E1_PERIOD + 1
    if t <= 32:
        return 120 + t
    if t == 33:
        return E1_HI
    if t <= 97:
        return E1_HI - (t - 33)
    if t == 98:
        return E1_LO
    return E1_LO + (t - 98)


def _expected_e2(t):
    """The platform patroller's triangle wave, by TICK number (ledge turns)."""
    if t <= 0:
        return 48
    t = (t - 1) % E2_PERIOD + 1
    if t <= 16:
        return 48 + t
    if t == 17:
        return E2_HI
    if t <= 49:
        return E2_HI - (t - 17)
    if t == 50:
        return E2_LO
    return E2_LO + (t - 50)


# =============================================================================
# 1. THE UPLOADS — the destination regions, byte for byte
# =============================================================================

def test_bg_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claimed CHR base, against pat_bg_chr.bin — all THREE tiles,
    including the two blank ones (rule 5: uploaded explicitly, so the whole
    claim is read, not just the tile that shows a colour)."""
    want = (ASSETS / "pat_bg_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_CHR * 2, len(want)))
    assert got == want, (
        f"the BG character block at VRAM word ${V_CHR:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_obj_character_block_is_the_destination_of_the_blob(fresh):
    want = (ASSETS / "pat_obj_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_OBJ * 2, len(want)))
    assert got == want, (
        f"the OBJ character block at VRAM word ${V_OBJ:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_both_palettes_are_the_destinations_of_their_blobs(fresh):
    """CGRAM at both claimed bases — the BG group 0 (word 0 IS the backdrop)
    and the full 32-word OBJ claim: palette 0's red AND palette 1's magenta,
    which is the attr $00 / $02 split the actors are staged with."""
    for label, base, blob in (("bg", C_PAL, "pat_bg_pal.bin"),
                              ("obj", C_OBJ, "pat_obj_pal.bin")):
        want = (ASSETS / blob).read_bytes()
        got = bytes(fresh.read_bytes(C, base * 2, len(want)))
        assert got == want, (
            f"{label} palette at CGRAM word {base} is not {blob} — "
            f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")


def test_tilemap_is_the_level_blob_rendered_cell_by_cell(fresh):
    """All 1,024 tilemap words in VRAM, each against the SAME pat_map byte the
    play scene binds as col_map's world — the one-source property maze also
    holds, asserted at the picture end: what blocks is provably what shows."""
    blob = (ASSETS / "pat_map.bin").read_bytes()
    raw = bytes(fresh.read_bytes(V, V_MAP * 2, MAP_DIM * MAP_DIM * 2))
    bad = []
    for i in range(MAP_DIM * MAP_DIM):
        word = raw[i * 2] | (raw[i * 2 + 1] << 8)
        if word != blob[i]:
            bad.append((i % MAP_DIM, i // MAP_DIM, word, blob[i]))
    assert not bad, (
        f"{len(bad)} of {MAP_DIM * MAP_DIM} tilemap cells differ from the "
        f"level blob; first 8 (col, row, vram, blob): {bad[:8]}")


def test_the_level_blob_is_the_declared_level_rebuilt_independently(fresh):
    """The blob itself, against the level's four terrain loops written out
    longhand HERE and shared with nothing — ground row 26, borders cols 0/31
    rows 0..25, low walls cols 10/20 rows 24..25, platform row 20 cols 4..8,
    tile id 2, rows 28..31 blank. And the flag table: entry 2 = $01, all 255
    others zero (`sf_tile_flags 2, SF_FLAG_SOLID`). Written here rather than
    imported so that a generator bug cannot agree with itself."""
    grid = [[0] * MAP_DIM for _ in range(MAP_DIM)]
    for c in range(32):
        grid[26][c] = 2
    for r in range(26):
        grid[r][0] = grid[r][31] = 2
    for r in (24, 25):
        grid[r][10] = grid[r][20] = 2
    for c in range(4, 9):
        grid[20][c] = 2
    want_map = bytes(b for row in grid for b in row)
    assert (ASSETS / "pat_map.bin").read_bytes() == want_map, (
        "pat_map.bin is not the level the four terrain loops describe")
    flags = (ASSETS / "pat_flags.bin").read_bytes()
    assert len(flags) == 256 and flags[2] == 1, "tile 2 must be SOLID ($01)"
    assert all(b == 0 for i, b in enumerate(flags) if i != 2), (
        "tile 2 is the only flagged tile in this level")


# An OPTIONAL external tree holding a second, independent implementation of
# this rail, named by `SF_REFERENCE_TREE`. It is read-only and never a build
# dependency: the variable is unset on an ordinary runner, so the case below
# SKIPs rather than fails when no such tree is on disk.
_REFERENCE_TREE = Path(os.environ.get("SF_REFERENCE_TREE",
                                      "/nonexistent/reference-tree"))
REFERENCE_MAIN = _REFERENCE_TREE / "templates" / "patrol" / "main.asm"


@pytest.mark.skipif(not REFERENCE_MAIN.exists(),
                    reason="SF_REFERENCE_TREE is unset or holds no patrol "
                           "source — optional, never a build dependency")
def test_the_vendored_constants_still_match_the_reference_source():
    """Ground truth from outside this tree, the same shape hud_game uses:
    re-read the tile byte table and the three colour equates out of the
    reference source, so a hand-copied constant here cannot silently rot."""
    src = REFERENCE_MAIN.read_text()
    assert "OBJ_RED   = $001F" in src
    assert "OBJ_MAGEN = $7C1F" in src
    assert "BG_GREY   = $39CE" in src
    # terrain_tile == sprite_tile == eight $FF,$00 rows + 16 zero bytes
    rows = [ln.strip() for ln in src.splitlines()]
    i = rows.index("terrain_tile:")
    tile_lines = rows[i + 1:i + 5]
    assert tile_lines[0] == tile_lines[1] == ".byte $FF,$00, $FF,$00, $FF,$00, $FF,$00"
    assert tile_lines[2] == tile_lines[3] == ".byte $00,$00, $00,$00, $00,$00, $00,$00"
    gen = (ASSETS / "pat_obj_chr.bin").read_bytes()
    assert gen == bytes([0xFF, 0x00] * 8 + [0x00] * 16), (
        "the generated solid tile is not the reference's literal byte table "
        "— one of the two has changed and they are meant to agree")


# =============================================================================
# 2. THE PICTURE — the composited boot frame
# =============================================================================

def test_boot_frame_is_the_level_the_hud_and_all_three_actors(fresh):
    """The first done-condition on BOTH surfaces at once, at absolute frame
    90: the level in grey (EXACTLY 5,952 px = the 93 level cells — the census
    IS the level), the white HITS line, the red player at spawn, and both
    magenta patrollers at the positions tick 89 of their triangle waves name.
    Five colours and no sixth. OAM read BEFORE the shot (module header)."""
    e1, e2 = _expected_e1(BOOT - 1), _expected_e2(BOOT - 1)
    assert _actors(fresh) == [SPAWN, (e1, E1_Y), (e2, E2_Y)], (
        "OAM disagrees with spawn + the two triangle waves at tick 89")
    px = _pixels(fresh, "boot")
    pic = [_at(px, x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W)]
    census = {c: pic.count(c) for c in set(pic)}
    assert census[GREY] == LEVEL_CELLS * 64, (
        f"grey census {census.get(GREY)} != {LEVEL_CELLS * 64} — the drawn "
        f"level is not the 93-cell room")
    assert census[RED] == 64 and census[MAGENTA] == 128, (
        "the cast is not one red 8x8 player + two magenta 8x8 enemies")
    assert census.get(WHITE, 0) > 0, "no white HUD pixels"
    assert set(census) == {BLACK, GREY, RED, MAGENTA, WHITE}, (
        f"unexpected colours on screen: {set(census)}")
    n, x0, x1, y0, y1 = _bbox(px, RED)
    assert (x0, x1, y0, y1) == (200, 207, 207, 214), (
        f"player drawn at ({x0}..{x1}, {y0}..{y1}), not spawn — this is also "
        f"the assertion that pins PIC_Y0 and the VOFS -1 alignment")
    _, ex0, ex1, ey0, ey1 = _bbox(px, MAGENTA)
    assert ey0 == E2_Y + PIC_Y0 and ey1 == E1_Y + PIC_Y0 + 7, (
        "the two enemies are not on their beat rows")
    assert {ex0, ex1} == {min(e1, e2), max(e1, e2) + 7}, (
        "the magenta extremes do not match the two triangle positions")


def test_hud_line_reads_HITS_0000(fresh):
    """The HUD's own output region: the BG3 tilemap words. Label 'HITS' at
    row 1 col 1, four '0' digits at col 6. The pixel positions (8,8) and
    (48,8) are fixed; the digit COUNT is four packed-BCD digits rather than a
    five-digit binary print, for the same reason hud_game packs its own —
    BCD is what the HUD renders directly and binary needs a divide."""
    raw = bytes(fresh.read_bytes(V, (V_TXT + HUD_ROW * 32 + LABEL_C) * 2, 8))
    label = [raw[i * 2] | (raw[i * 2 + 1] << 8) for i in range(4)]
    assert label == [_glyph(c) for c in "HITS"], "label cells are not 'HITS'"
    assert _hits_cells(fresh) == [_glyph("0")] * 4, "counter is not 0000"


# =============================================================================
# 3. THE PATROLLERS — full bounce cycles against the triangle oracles
# =============================================================================
# The reference's own test spec (its README): "exact turn bounds on both sides,
# multiple round trips at constant speed with clean single-step turns, and
# the ledge patroller never overhanging its platform". Here that is one
# assertion per FRAME against the closed-form triangle wave — bounds, speed,
# the no-move turn frame, and both directions all fall out of trace equality,
# and a single wrong sample names its frame.

def test_ground_patroller_walks_its_wall_bounded_beat_forever(boot):
    """E1, 150 consecutive frames from frame 60 — more than one full 130-frame
    period, covering BOTH turns (wall 152, wall 88) and both directions.
    Every sample must equal the oracle; the beat bound check is explicit so
    the never-leaves-the-beat claim is named, not implied."""
    m = boot(60)
    trace = []
    for f in range(61, 61 + 150):
        m.advance(1)
        trace.append((f, _actors(m)[1]))
    bad = [(f, got, (_expected_e1(f - 1), E1_Y)) for f, got in trace
           if got != (_expected_e1(f - 1), E1_Y)]
    assert not bad, (
        f"{len(bad)} of 150 E1 samples off the triangle wave; first 5 "
        f"(frame, got, want): {bad[:5]}")
    assert all(E1_LO <= got[0] <= E1_HI for _, got in trace), (
        "E1 left its wall-bounded beat")


def test_ledge_patroller_never_overhangs_its_platform(boot):
    """E2, 140 consecutive frames from frame 60 — more than TWO full 66-frame
    periods (multiple round trips), both ledge turns twice each.

    THE LEADING-CORNER LESSON lives in the right bound: the platform spans px
    32..71, and the oracle's rest is 64 — box 64..71, flush with the LAST
    platform pixel. A trailing-corner probe would rest at 71 (7 px overhang);
    a wall-only patroller would walk clean off to the border at 240. Trace
    equality against the 32..64 triangle discriminates all three."""
    m = boot(60)
    trace = []
    for f in range(61, 61 + 140):
        m.advance(1)
        trace.append((f, _actors(m)[2]))
    bad = [(f, got, (_expected_e2(f - 1), E2_Y)) for f, got in trace
           if got != (_expected_e2(f - 1), E2_Y)]
    assert not bad, (
        f"{len(bad)} of 140 E2 samples off the triangle wave; first 5 "
        f"(frame, got, want): {bad[:5]}")
    assert all(E2_LO <= got[0] <= E2_HI for _, got in trace), (
        "E2 overhung its platform — the leading-corner ledge probe is broken")


def test_the_turn_is_drawn_flush_on_the_platform_edge(boot):
    """The composited never-overhang proof: parked at E2's right rest, the
    PICTURE must show the magenta box at exactly (64..71, 159..166) — its
    last column ON the platform's last grey column (71), one row above the
    platform top. OAM is read at the park BEFORE the shot; both surfaces
    describe the same committed frame."""
    m = boot(60)
    m.run_until(lambda mm: _actors(mm)[2][0] == E2_HI, max_frames=E2_PERIOD + 2,
                what="E2 at its right rest")
    assert _actors(m)[2] == (E2_HI, E2_Y)
    e1x = _actors(m)[1][0]
    px = _pixels(m, "e2_edge")
    pts = [(x, y) for y in range(E2_Y + PIC_Y0 - 1, E2_Y + PIC_Y0 + 9)
           for x in range(PIC_W) if _at(px, x, y) == MAGENTA]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert (len(pts), min(xs), max(xs), min(ys), max(ys)) == (
        64, E2_HI, E2_HI + 7, E2_Y + PIC_Y0, E2_Y + PIC_Y0 + 7), (
        "E2 is not drawn as a full 8x8 flush at the platform edge")
    # the platform's own last grey pixel is column 71, directly under E2
    assert _at(px, 71, 160 + PIC_Y0) == GREY and _at(px, 72, 160 + PIC_Y0) == BLACK, (
        "the platform top row does not end at px 71 — the flushness claim "
        "has nothing to be flush against")
    # and E1, wherever its wave has it, is drawn where OAM says
    n1, x0, x1, y0, y1 = _bbox(px, RED)
    assert (x0, y0) == (200, 207), "the idle player moved"
    e1_pts = [(x, y) for y in range(E1_Y + PIC_Y0, E1_Y + PIC_Y0 + 8)
              for x in range(PIC_W) if _at(px, x, y) == MAGENTA]
    assert min(p[0] for p in e1_pts) == e1x, (
        "E1's drawn box disagrees with its pre-shot OAM x")


# =============================================================================
# 4. THE PLAYER — move-check, jump cycle, edge-gated input
# =============================================================================

def test_idle_outside_the_beats_nothing_hits_and_nothing_drifts(boot):
    """The fourth done-condition AND the idle state cycle: 140 frames (more
    than one E1 period, so the ground enemy sweeps its whole beat past the
    player's row) with nothing held. The player must sit at spawn on EVERY
    frame, the HITS cells must never change, and the level tilemap must
    never be rewritten (the write counter on its first cell: enter-time
    writes only)."""
    m = boot()
    map_writes0 = m.writes(V, V_MAP * 2)
    cells0 = _hits_cells(m)
    assert cells0 == [_glyph("0")] * 4
    for f in range(140):
        m.advance(1)
        assert _actors(m)[0] == SPAWN, f"the idle player moved on frame {BOOT + 1 + f}"
    assert _hits_cells(m) == cells0, "HITS changed with the player at spawn"
    assert m.writes(V, V_MAP * 2) == map_writes0, (
        "the level tilemap was rewritten during play — the level is static")


def test_running_right_rests_flush_against_the_border(boot):
    """Horizontal move-check against the border wall: from spawn, 30 held
    frames overshoot the 20-frame walk to the wall face; the rest is (240,
    200) — box 240..247 against border px 248 — and 5 more held frames do
    not move it. Both surfaces: OAM rest + the drawn red box beside grey."""
    m = boot()
    m.advance(30, pad1={"right": True})
    assert _actors(m)[0] == (BORDER_R_REST, 200)
    m.advance(5, pad1={"right": True})
    assert _actors(m)[0] == (BORDER_R_REST, 200), "pushed into the border"
    px = _pixels(m, "border_rest")
    n, x0, x1, y0, y1 = _bbox(px, RED)
    assert (n, x0, x1, y0, y1) == (64, 240, 247, 207, 214)
    assert _at(px, 248, 203 + PIC_Y0) == GREY, (
        "no border wall pixel at px 248 beside the resting player")


def test_running_left_rests_flush_against_the_low_wall(boot):
    """The same move-check against low wall col 20 (px 160..167): 50 held
    frames from spawn rest at (168, 200) — the wall between the player and
    the ground enemy's beat, which is why walking cannot produce a hit."""
    m = boot()
    m.advance(50, pad1={"left": True})
    assert _actors(m)[0] == (WALL_L_REST, 200)
    px = _pixels(m, "wall_rest")
    n, x0, x1, y0, y1 = _bbox(px, RED)
    assert (n, x0, x1, y0, y1) == (64, 168, 175, 207, 214)
    assert _at(px, 167, E1_Y + PIC_Y0 + 4) == GREY, (
        "no wall pixel at px 167 beside the resting player")


def test_jump_full_cycle_apex_and_landing_exact(boot):
    """The whole jump state cycle, apex AND landing: one A press at rest, then
    45 frame-by-frame samples — take-off, ascent to the exact apex pixel
    (161 = 200 - 38.25 floor'd, straight out of JUMP_VEL/GRAVITY), descent,
    landing at EXACTLY 200, and a stable rest (every remaining sample 200: no
    embedding, no hover, no bounce). An apex-only test passes while the landing
    frame buries the sprite in the floor."""
    m = boot()
    m.advance(1, pad1={"a": True})
    ys = []
    for _ in range(45):
        m.advance(1)
        ys.append(_actors(m)[0][1])
    assert min(ys) == JUMP_APEX_Y, (
        f"apex {min(ys)} != {JUMP_APEX_Y} — the jump arc changed")
    assert ys[-1] == 200, "did not land back at rest"
    landing = ys.index(200)
    assert all(y == 200 for y in ys[landing:]), (
        f"unstable rest after landing: {ys[landing:landing + 8]}")
    assert all(y <= 200 for y in ys), "embedded below the ground during the arc"
    assert _actors(m)[0][0] == SPAWN[0], "an A-only jump moved the player in x"


def test_jump_is_edge_gated_holding_A_gives_one_arc(boot):
    """The reference's btnp lesson (hud_game's edge-vs-level surface, composed
    here): A held for 60 straight frames produces exactly ONE take-off — the
    trace leaves y=200 once and, after landing, stays grounded for the rest
    of the hold."""
    m = boot()
    ys = []
    for _ in range(60):
        m.advance(1, pad1={"a": True})
        ys.append(_actors(m)[0][1])
    departures = sum(1 for i in range(1, len(ys))
                     if ys[i] != 200 and ys[i - 1] == 200)
    assert departures == 1, (
        f"{departures} take-offs during a 60-frame hold — jump reads level "
        f"input, not the rising edge")
    assert ys[-1] == 200, "still airborne after one arc's worth of hold"


# =============================================================================
# 5. CONTACT — the beat entered, the knockback, the counter, keep playing
# =============================================================================
# The third done-condition, choreographed the way the game is played: the
# beat zone is fenced by wall 20, so the player JUMPS it (the level comment
# calls the low walls "jumpable" — 16 px against a 38 px arc) and lands
# inside E1's beat. Every leg is asserted on OAM/VRAM, and the whole thing
# is deterministic under lockstep.

def _enter_the_beat(m):
    """From boot: walk to the wall, jump it holding left, land in the beat.
    Returns the landing x. Asserts the player is inside E1's reach and that
    no hit has happened yet is the CALLER's business (some choreographies
    want the hit)."""
    m.advance(50, pad1={"left": True})
    assert _actors(m)[0] == (WALL_L_REST, 200), "did not reach the wall rest"
    m.advance(1, pad1={"a": True, "left": True})
    for _ in range(40):
        m.advance(1, pad1={"left": True})
    x, y = _actors(m)[0]
    assert y == 200, "did not land back on the ground row"
    assert E1_LO <= x <= E1_HI, (
        f"landed at x={x}, outside E1's beat {E1_LO}..{E1_HI} — the jump "
        f"did not clear the wall")
    return x


def test_contact_knocks_back_ticks_HITS_and_play_continues(boot):
    """Enter the beat, stand still, let E1 sweep in: the respawn (both
    surfaces), the counter's four VRAM cells reading 0001, and movement
    still working afterwards — 'the player can keep playing'."""
    m = boot()
    _enter_the_beat(m)
    frames = m.run_until(lambda mm: _actors(mm)[0] == SPAWN,
                         max_frames=E1_PERIOD + 40,
                         what="the knockback respawn")
    assert frames > 0, "respawned instantly — the landing itself was a hit?"
    assert _hits_cells(m) == [_glyph("0")] * 3 + [_glyph("1")], (
        "HITS does not read 0001 after one contact")
    px = _pixels(m, "after_hit")
    n, x0, x1, y0, y1 = _bbox(px, RED)
    assert (x0, y0) == (200, 207), "the drawn player is not back at spawn"
    m.advance(5, pad1={"right": True})
    assert _actors(m)[0][0] > SPAWN[0], "cannot move after the knockback"


def test_second_contact_counts_0002_the_full_bcd_reprint_cycle(boot):
    """The counter's own state cycle driven TWICE: two choreographed hits,
    the cells reading 0001 then 0002 — the BCD add and the queue reprint
    both repeat, so the first tick was not a one-shot."""
    m = boot()
    _enter_the_beat(m)
    m.run_until(lambda mm: _actors(mm)[0] == SPAWN,
                max_frames=E1_PERIOD + 40, what="first respawn")
    assert _hits_cells(m)[-1] == _glyph("1")
    _enter_the_beat(m)
    m.run_until(lambda mm: _actors(mm)[0] == SPAWN,
                max_frames=E1_PERIOD + 40, what="second respawn")
    assert _hits_cells(m) == [_glyph("0")] * 3 + [_glyph("2")], (
        "the second contact did not print 0002")


# =============================================================================
# 6. THE STAGING MECHANISMS — write counters on the features' own regions
# =============================================================================

def test_hits_cells_are_written_only_when_the_value_changes(boot):
    """hud_game's reprint-on-change discipline, composed here, on the
    DESTINATION's write counters (reading the cells cannot see it: an
    unchanged reprint leaves byte-identical VRAM). 100 idle frames add ZERO
    writes to all four digit cells and the label; the one choreographed hit
    then adds EXACTLY ONE write per digit-cell byte."""
    m = boot()
    digit_addrs = [(V_TXT + HUD_ROW * 32 + DIGITS_C + i) * 2 for i in range(4)]
    label_addr = (V_TXT + HUD_ROW * 32 + LABEL_C) * 2
    before = [m.writes(V, a) for a in digit_addrs]
    label_before = m.writes(V, label_addr)
    m.advance(100)
    after_idle = [m.writes(V, a) for a in digit_addrs]
    assert after_idle == before, (
        f"idle frames rewrote the counter cells: {before} -> {after_idle} — "
        f"the dirty gate is not gating")
    _enter_the_beat(m)
    m.run_until(lambda mm: _actors(mm)[0] == SPAWN,
                max_frames=E1_PERIOD + 40, what="the respawn")
    m.advance(30)                       # plenty of idle after the one commit
    after_hit = [m.writes(V, a) for a in digit_addrs]
    assert after_hit == [b + 1 for b in before], (
        f"one contact should write each digit cell exactly once: "
        f"{before} -> {after_hit}")
    assert m.writes(V, label_addr) == label_before, (
        "the label was rewritten by the running scene")


def test_the_cast_is_restaged_every_frame_not_written_once(boot):
    """The OAM SHADOW's write counter — the feature's own output region. The
    tick calls pat_obj_place unconditionally, a spr_clear plus three spr calls
    every frame, so 30 idle frames must restage entry 0 at least 30 times."""
    shadow = _sym("ES_OAM_SHADOW", scene=None)["start"]
    m = boot()
    before = m.writes(W, shadow)
    m.advance(30)
    after = m.writes(W, shadow)
    assert after - before >= 30, (
        f"the OAM shadow's first byte was written {after - before} times over "
        f"30 frames — the cast is staged once, not re-staged per frame")


# =============================================================================
# 7. WHY THIS RAIL IS IN THE SWEEP — the spec row 7: the composition
# =============================================================================

def test_the_composition_reference_composes_disjoint_claims(fresh):
    """Every surface the rail composes, placed by the allocator with no two
    overlapping — the collision-freedom the whole repo exists to prove, read
    back from the emitted map: four VRAM regions (BG CHR, level map, text
    map, OBJ CHR), three CGRAM regions (BG group 0, text palette 7, the two
    OBJ palettes), four OAM slots. The composited boot frame (the boot test)
    is the picture of all of them at once; this case is the ledger."""
    def span(n):
        p = _sym(n)
        return (p["start"], p["start"] + p["size"], n)

    vram = [span(n) for n in ("ES_V_PAT_CHR", "ES_V_PAT_MAP_V",
                              "ES_V_POBJ_CHR", "ES_V_TEXT_MAP")]
    for i in range(len(vram)):
        for j in range(i + 1, len(vram)):
            a, b = vram[i], vram[j]
            assert a[1] <= b[0] or b[1] <= a[0], f"VRAM overlap: {a} vs {b}"
    cgram = [span(n) for n in ("ES_C_PAT_PAL", "ES_C_TEXT_PAL", "ES_C_POBJ_PAL")]
    for i in range(len(cgram)):
        for j in range(i + 1, len(cgram)):
            a, b = cgram[i], cgram[j]
            assert a[1] <= b[0] or b[1] <= a[0], f"CGRAM overlap: {a} vs {b}"
    oam = [span(n) for n in ("ES_O_PLAYER", "ES_O_ENEMIES", "ES_O_HI_PAD")]
    assert sorted((a, b) for a, b, _ in oam) == [(0, 1), (1, 3), (3, 4)], (
        "the four OAM slots are not the pinned 0/1..2/3 layout")
