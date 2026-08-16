"""maze — col_map against a hand-built map, asserted against what it drew.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)`, which
lands on the ABSOLUTE frame N by construction.

WHAT THIS RAIL IS, and therefore what these cases have to prove. Its source
states its own done-conditions:

    - boots; grey walls + red player visible
    - the player moves freely in open floor (all four directions)
    - walking into a wall stops AT the wall edge (no overlap, no pass-through,
      no sticking — the free axis still slides)

and its README adds the coordinates those conditions mean in pixels:
left-wall stop x=8, interior-wall stop x=88, top y=8, bottom y=208, right
x=240. Those five numbers are this module's spec.

What makes the rail worth a test at all is *col_map against a hand-built map*.
The load-bearing structural fact is that the mz_room blob is BOTH the BG
render source and col_map's bound world, so the walls drawn and the walls
probed cannot drift — asserted here by comparing the VRAM tilemap against a
hand-built geometry written out longhand below AND against the blob byte for
byte, then driving the player into every wall face and reading the stop out of
OAM bytes and rendered pixels.

STATE CYCLES (the repo's own rule: a collision rail walked one direction ships
the others broken): every border wall is approached ON ITS OWN AXIS (left wall
moving left, right wall moving right, top moving up, bottom moving down); the
interior wall A is approached from the left and slid along; interior wall B is
approached from ABOVE and from BELOW; open-floor movement is driven out AND
back on both axes; idle must hold the frame; opposite directions cancel.

MOVEMENT TIMING, MEASURED (not assumed): the pad is latched at the park and
polled at each frame boundary, and the staged OAM entry reaches hardware on
the NEXT VBlank — so after `advance(n, pad)` hardware OAM shows (n-1) steps,
and one released frame settles the nth. `_hold` therefore advances n held + 2
released frames and the position is exactly n * MZ_SPEED further (measured at
n = 1, 2, 3, 5 before writing this down; the settle is 2 frames only to keep
the picture and OAM trivially coherent — measured identical at +1 and +2).

The one derived picture constant, PIC_Y0 = 7, was re-measured ON THIS ROM two
independent ways that agree: the left border wall (world y 0..223) occupies
PNG rows 7..230, and the sprite whose OAM Y is 100 occupies PNG rows 107..114.
Both give +7 (the same value test_scroller.py measured on its own ROM).
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
ROM = BUILD / "maze.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "maze" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="room"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_CHR = _sym("ES_V_MZ_CHR")["start"]            # BG CHR page, VRAM words
V_MAP = _sym("ES_V_MZ_MAP")["start"]            # BG tilemap base, VRAM words
V_OBJ = _sym("ES_V_MZ_OBJ_CHR")["start"]        # OBJ CHR page, VRAM words
C_PAL = _sym("ES_C_MZ_PAL")["start"]            # BG palette group 0, CGRAM
C_OBJ = _sym("ES_C_MZ_OBJ_PAL")["start"]        # OBJ palette 0, CGRAM words

MAP_DIM = 32                            # 32x32 cells, 8 px each
SPEED = 2                               # game/maze/maze.inc MZ_SPEED
SPAWN = (40, 100)                       # the scene's own spawn, main.asm:129-132

TILE_WALL = 2                           # the one solid-flagged tile id

# --- the picture, MEASURED (module docstring) --------------------------------
PIC_Y0, PIC_H, PIC_W = 7, 224, 256
GREY = (115, 115, 115)                  # CGRAM word 1 = $39CE (5-bit 14 -> 115)
RED = (255, 0, 0)                       # OBJ CGRAM word 129 = $001F
BLACK = (0, 0, 0)                       # word 0: the backdrop

BOOT = 90                               # an absolute frame, well past the fade


def _reference_room():
    """The hand-built room, written out here from the four boot loops and
    their termination constants — NOT from the generator (asserting the
    generator's output against the generator's own algorithm would be the
    tautology CLAUDE.md's asset rule names). border_h:
    rows 0 + 27, cols 0..31 (`cmp #32`); border_v: cols 0 + 31, rows 0..27
    (`cmp #28`); wall A: col 12, rows 1..13 (`lda #1` / `cmp #14`); wall B:
    row 18, cols 18..30 (`lda #18` / `cmp #31`).
    """
    room = [[0] * MAP_DIM for _ in range(MAP_DIM)]
    for i in range(32):
        room[0][i] = TILE_WALL
        room[27][i] = TILE_WALL
    for i in range(28):
        room[i][0] = TILE_WALL
        room[i][31] = TILE_WALL
    for row in range(1, 14):
        room[row][12] = TILE_WALL
    for col in range(18, 31):
        room[18][col] = TILE_WALL
    return room


ROOM = _reference_room()
N_WALL_TILES = sum(v == TILE_WALL for row in ROOM for v in row)   # 142


@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle.

    Each case builds its own Machine (the core is a process-global singleton)
    and this teardown resumes the core at module end — the module-boundary
    contract tests/conftest.py enforces.
    """
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make maze` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


# --- helpers -----------------------------------------------------------------

def _pos(m):
    """The player's hardware OAM entry position (bytes 0..1 of entry 0)."""
    b = m.read_bytes(O, 0, 2)
    return b[0], b[1]


def _hold(m, frames, **buttons):
    """Hold a pad state for `frames`, then settle 2 released frames.

    Post-condition (measured, module docstring): the position has advanced by
    exactly frames * MZ_SPEED on each free axis, and hardware OAM, the staged
    shadow and the next screenshot all agree.
    """
    m.advance(frames, pad1={k: True for k in buttons})
    m.advance(2)
    return m


def _pixels(m, name):
    """The frame current NOW as a flat RGB list (the capture's own +1 frame is
    spent after the copy, pads released — harmless to a settled position)."""
    path = m.take_screenshot(str(BUILD / "shots" / f"maze_{name}.png"))
    with Image.open(path) as im:
        return list(im.convert("RGB").getdata())


def _at(px, x, y):
    return px[y * PIC_W + x]


def _red_bbox(px):
    reds = [(x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
            for x in range(PIC_W) if _at(px, x, y) == RED]
    assert reds, "no red pixels — the player is not on screen"
    xs = [x for x, _ in reds]
    ys = [y for _, y in reds]
    return (min(xs), max(xs), min(ys), max(ys), len(reds))


def _assert_player_at(m, x, y, shot=None):
    """The player's position, on BOTH output surfaces.

    OAM bytes say where the entry is; the pixels say where the PPU composited
    it. They fail differently (a dropped OAM commit vs a stale X9 / OBSEL
    clobber), so wall-stop cases assert both.
    """
    assert _pos(m) == (x, y), f"OAM says {_pos(m)}, want {(x, y)}"
    if shot is not None:
        bbox = _red_bbox(_pixels(m, shot))
        want = (x, x + 7, y + PIC_Y0, y + PIC_Y0 + 7, 64)
        assert bbox == want, f"drawn player bbox {bbox}, want {want}"


# =============================================================================
# 1. THE UPLOADS — the destination regions, byte for byte
# =============================================================================

def test_bg_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claimed CHR base, against mz_bg_chr.bin — all THREE tiles,
    including the two all-zero ones: an upload that silently no-ops over
    power-on-clear VRAM would render the same wall, which is exactly why the
    zero tiles are written explicitly (rule 5) and read back here."""
    want = (ASSETS / "mz_bg_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_CHR * 2, len(want)))
    assert got == want, (
        f"BG CHR at VRAM word ${V_CHR:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_obj_character_block_is_the_destination_of_the_blob(fresh):
    want = (ASSETS / "mz_obj_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_OBJ * 2, len(want)))
    assert got == want, (
        f"OBJ CHR at VRAM word ${V_OBJ:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_both_palettes_are_the_destinations_of_their_blobs(fresh):
    """CGRAM at both claimed bases — the whole 16 words each, including BG
    word 0, the backdrop the floor renders as."""
    for label, base, blob in (("bg", C_PAL, "mz_bg_pal.bin"),
                              ("obj", C_OBJ, "mz_obj_pal.bin")):
        want = (ASSETS / blob).read_bytes()
        got = bytes(fresh.read_bytes(C, base * 2, len(want)))
        assert got == want, (
            f"{label} palette at CGRAM word {base} is not {blob} — "
            f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")


def test_the_tilemap_is_the_declared_room_rendered_from_the_blob(fresh):
    """All 1,024 tilemap words in VRAM, each against the room as declared.

    TWO comparisons on one region, because they catch different defects:

      1. VRAM word == the room rebuilt from the loop bounds
         (_reference_room). A generator that drifted (wrong wall span) fails
         here even though blob and VRAM would still agree with each other.
      2. VRAM low byte == the mz_room BLOB byte, all 1024. The blob is what
         col_map probes, so this is the rail's single-source property — the
         wall the PPU fetches and the wall the move-check hits are the same
         byte — read off the hardware destination.

    Every cell is checked rather than a corner sample: a render loop that
    dropped its `and #255` mask or mis-strided would leave most cells right.
    """
    raw = bytes(fresh.read_bytes(V, V_MAP * 2, MAP_DIM * MAP_DIM * 2))
    blob = (ASSETS / "mz_room.bin").read_bytes()
    bad_rule, bad_blob = [], []
    for row in range(MAP_DIM):
        for col in range(MAP_DIM):
            i = row * MAP_DIM + col
            word = raw[i * 2] | (raw[i * 2 + 1] << 8)
            if word != ROOM[row][col]:
                bad_rule.append((col, row, word))
            if raw[i * 2] != blob[i]:
                bad_blob.append((col, row, raw[i * 2], blob[i]))
    assert not bad_rule, (
        f"{len(bad_rule)} of 1024 tilemap cells are not the declared room; "
        f"first 8: {bad_rule[:8]}")
    assert not bad_blob, (
        f"{len(bad_blob)} tilemap cells differ from the mz_room blob (the "
        f"collision world) — the two surfaces drifted; first 8: {bad_blob[:8]}")


# =============================================================================
# 2. THE PICTURE — the composited result
# =============================================================================

def test_boot_frame_is_the_walled_room_with_the_red_player(fresh):
    """The rail's headline done-condition, read off the drawn frame.

    The wall census is EXACT: 142 wall tiles x 64 px = 9,088 grey pixels (the
    spawn box overlaps no wall), the player is a solid 8x8 = 64 red, and
    everything else is backdrop — three colours, no fourth. A palette bleed,
    a CHR corruption or a stray sprite all show up as a fourth colour or a
    wrong census before they show up anywhere else.
    """
    px = _pixels(fresh, "boot")
    pic = [_at(px, x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W)]
    greys = pic.count(GREY)
    reds = pic.count(RED)
    assert greys == N_WALL_TILES * 64, (
        f"{greys} grey pixels, want {N_WALL_TILES * 64} (142 wall tiles)")
    assert reds == 64, f"expected a solid 8x8 red player, got {reds} red pixels"
    assert greys + reds + pic.count(BLACK) == PIC_W * PIC_H, (
        "the picture holds colours other than backdrop, walls and the player")
    assert _red_bbox(px) == (40, 47, 107, 114, 64), "player not at the spawn"


def test_wall_geometry_lands_where_the_map_says(fresh):
    """Three scanline cuts through the drawn frame, against the room's own
    geometry — the picture-side half of the single-source property.

    PNG row 7 is world y 0 (the top border: all grey); PNG row 47 is world
    y 40, which cuts the left border, interior wall A (col 12 -> px 96..103)
    and the right border; PNG row 151 is world y 144, wall B's first line
    (cols 18..30 -> px 144..247, meeting the right border). The VOFS -1 pin
    is what makes these land: drop it and every cut is one pixel off.
    """
    px = _pixels(fresh, "geometry")
    assert all(_at(px, x, PIC_Y0) == GREY for x in range(PIC_W)), (
        "PNG row 7 (world y 0) is not solid top-border grey")
    cut40 = {x for x in range(PIC_W) if _at(px, x, 40 + PIC_Y0) == GREY}
    want40 = set(range(0, 8)) | set(range(96, 104)) | set(range(248, 256))
    assert cut40 == want40, (
        f"world y 40 grey columns {sorted(cut40)} != border + wall A + border")
    cut144 = {x for x in range(PIC_W) if _at(px, x, 144 + PIC_Y0) == GREY}
    want144 = set(range(0, 8)) | set(range(144, 256))
    assert cut144 == want144, (
        f"world y 144 grey columns != border + wall B (cols 18..30) + border")


# =============================================================================
# 3. OPEN-FLOOR MOVEMENT — all four directions, out AND back
# =============================================================================

def test_moves_freely_in_open_floor_all_four_directions_and_back(boot):
    """Each axis driven out and driven home, positions exact at every leg.

    The out-AND-back is the state-cycle rule: a rail that only ever walks
    right locks that direction and ships the reverse broken. Home again must
    be EXACTLY the spawn — off-by-one accumulation over a there-and-back is
    the classic sign of an asymmetric axis handler.
    """
    m = boot()
    x0, y0 = SPAWN
    _hold(m, 5, right=True)
    _assert_player_at(m, x0 + 10, y0)
    _hold(m, 5, left=True)
    _assert_player_at(m, x0, y0, shot="home_x")
    _hold(m, 5, down=True)
    _assert_player_at(m, x0, y0 + 10)
    _hold(m, 5, up=True)
    _assert_player_at(m, x0, y0, shot="home_y")


def test_idle_holds_the_frame_still(boot):
    """The third state: nothing held. 60 frames must change nothing —
    a drifting position, a re-published stale shadow or an uninitialised
    OAM byte would move here while every driven case still passed."""
    m = boot()
    entry0 = bytes(m.read_bytes(O, 0, 4))
    a = _pixels(m, "idle_a")
    m.advance(60)
    b = _pixels(m, "idle_b")
    assert a == b, (
        f"the picture moved over 60 idle frames — "
        f"{sum(x != y for x, y in zip(a, b))} pixels differ")
    assert bytes(m.read_bytes(O, 0, 4)) == entry0


def test_opposite_directions_cancel(boot):
    """Left+Right and Up+Down held together net to zero — the mover applies
    both deltas rather than branching, so this is arithmetic, not priority,
    and it pins the input combination a four-way `beq` chain gets wrong."""
    m = boot()
    a = _pixels(m, "cancel_a")
    m.advance(30, pad1={"left": True, "right": True, "up": True, "down": True})
    m.advance(2)
    b = _pixels(m, "cancel_b")
    assert a == b, "holding all four directions moved the player"
    assert _pos(m) == SPAWN


# =============================================================================
# 4. THE WALLS — every border face on its own axis, no overlap, no tunnel
# =============================================================================
# The stop coordinates come straight out of the geometry: a border tile is
# 8 px, the box is 8 px, so a stop against a wall whose near face is
# at pixel P leaves the box's near edge exactly at P -+ 8. The second hold in
# each case is the no-tunnel half: MZ_SPEED (2) < 8 means a step can never
# cross a wall cell, and continuing to push must change NOTHING.

def test_left_wall_stops_at_the_edge(boot):
    m = boot()
    _hold(m, 60, left=True)              # 32 px of travel needs 16 held frames
    _assert_player_at(m, 8, 100, shot="left_stop")
    _hold(m, 30, left=True)
    _assert_player_at(m, 8, 100)         # no tunnel, no creep


def test_top_wall_stops_at_the_edge(boot):
    m = boot()
    _hold(m, 60, up=True)                # 92 px of travel needs 46 held frames
    _assert_player_at(m, 40, 8)
    _hold(m, 30, up=True)
    _assert_player_at(m, 40, 8)


def test_bottom_wall_stops_at_the_edge(boot):
    m = boot()
    _hold(m, 60, down=True)              # 108 px needs 54 held frames
    _assert_player_at(m, 40, 208)        # row 27 starts at 216; box ends 215
    _hold(m, 30, down=True)
    _assert_player_at(m, 40, 208)


def test_right_wall_stops_at_the_edge(boot):
    """Routed along the bottom corridor (y=208), UNDER interior wall B, so the
    only thing that can stop the run is the right border itself."""
    m = boot()
    _hold(m, 60, down=True)              # (40, 208)
    _hold(m, 120, right=True)            # 200 px needs 100 held frames
    _assert_player_at(m, 240, 208, shot="right_stop")
    _hold(m, 30, right=True)
    _assert_player_at(m, 240, 208)


def test_interior_wall_a_stops_from_the_left(boot):
    """The reference test's headline case: wall A's near face is at col 12 =
    px 96, so pushing right at y=100 (inside its row span) stops at 88."""
    m = boot()
    _hold(m, 40, right=True)             # 48 px needs 24 held frames
    _assert_player_at(m, 88, 100, shot="wall_a_stop")
    _hold(m, 30, right=True)
    _assert_player_at(m, 88, 100)


def test_interior_wall_b_stops_from_above_and_below(boot):
    """Both vertical faces of wall B (row 18: py 144..151, cols 18..30).

    FROM BELOW: bottom corridor to (176, 208), then up — the box's top edge
    stops at 152. FROM ABOVE: around wall A through the mid-gap, along the
    top corridor to (176, 8), then down — the box's bottom edge stops at 143,
    i.e. y = 136. One wall, two approach directions, two different stop
    values: a probe that only tested one corner pair would get exactly one
    of these wrong.
    """
    m = boot()
    _hold(m, 60, down=True)              # (40, 208), the bottom corridor
    _hold(m, 68, right=True)             # 136 px -> (176, 208), under wall B
    _hold(m, 40, up=True)                # 56 px of travel to the stop
    _assert_player_at(m, 176, 152, shot="wall_b_below")
    _hold(m, 20, up=True)
    _assert_player_at(m, 176, 152)

    m2 = boot()
    _hold(m2, 10, down=True)             # (40, 120): below wall A's span
    _hold(m2, 40, right=True)            # (120, 120): the mid-gap corridor
    _hold(m2, 70, up=True)               # (120, 8): the top corridor
    _hold(m2, 28, right=True)            # (176, 8): above wall B
    _hold(m2, 80, down=True)             # 128 px of travel to the stop
    _assert_player_at(m2, 176, 136, shot="wall_b_above")
    _hold(m2, 20, down=True)
    _assert_player_at(m2, 176, 136)


# =============================================================================
# 5. THE SLIDE — the per-axis move-check's whole point
# =============================================================================

def test_slides_along_wall_a_and_reaches_the_gap_below(boot):
    """Diagonal into wall A: the blocked axis pins, the free axis KEEPS
    MOVING, and past the wall's end the blocked axis frees — the player
    reaches the gap below the wall's end.

    Frame-exact through the corner: wall A spans world y 8..111, so with the
    X probe testing the CURRENT y before Y steps, the first 6 diagonal frames
    slide (y 100 -> 112, x pinned at 88) and every frame after moves both
    axes. 5 frames: (88, 110) — the slide. 10 more: x has been free for 9 of
    them -> (106, 130) — past wall A's column, through the gap. A move-check
    that cancelled the whole move on a blocked axis (the stick bug) would
    leave the player at (88, 100); one that committed the blocked axis (no
    probe) would put it inside the wall.
    """
    m = boot()
    _hold(m, 40, right=True)             # pressed against wall A at (88, 100)
    _hold(m, 5, right=True, down=True)
    _assert_player_at(m, 88, 110, shot="slide")   # slid, not stuck, no overlap
    _hold(m, 10, right=True, down=True)
    _assert_player_at(m, 106, 130)       # through the gap below the wall


def test_slides_along_the_top_wall(boot):
    """The same property on the other axis: pinned against the top border,
    a held up+right keeps sliding right at y=8."""
    m = boot()
    _hold(m, 60, up=True)                # (40, 8)
    _hold(m, 5, up=True, right=True)
    _assert_player_at(m, 50, 8)
    _hold(m, 5, up=True, right=True)
    _assert_player_at(m, 60, 8)


# =============================================================================
# 6. THE STAGING — the feature's own output region
# =============================================================================

def test_the_player_is_restaged_every_frame_not_written_once(boot):
    """The OAM SHADOW's write counter — maze_obj's own output region.

    Hardware OAM is the wrong surface for this claim: oam_nmi_dma commits the
    whole shadow every armed VBlank whether or not mzo_draw ran, so its write
    counter climbs identically in both worlds (test_scroller.py §5 caught
    exactly that with a plant). The shadow byte distinguishes them: 30 idle
    frames must add >= 30 writes to the entry's X byte.
    """
    shadow = _sym("ES_OAM_SHADOW", scene=None)["start"]
    m = boot()
    before = m.writes(W, shadow)
    m.advance(30)
    after = m.writes(W, shadow)
    assert after - before >= 30, (
        f"the OAM shadow's player X byte was written {after - before} times "
        f"over 30 frames — the sprite is staged once, not re-staged per frame")


# =============================================================================
# 7. WHY THIS RAIL IS IN THE SWEEP — the spec row 5
# =============================================================================

def test_col_map_probes_the_same_bytes_the_screen_shows(fresh):
    """The spec's "why here": col_map against a hand-built map.

    The structural half of the claim, at the allocator's own addresses:

      1. the three VRAM claims are disjoint (an aliased claim can hold "the
         right bytes" in both regions while one overwrites the other);
      2. the rendered tilemap's low bytes ARE the mz_room blob — the exact
         bytes col_map's binding reads (CM_WORLD_BLOB = ES_R_MZ_ROOM_ADDR);
      3. the flag table is exactly `sf_tile_flags 2, SF_FLAG_SOLID`:
         entry 2 = $01 and NOTHING else is flagged, so every
         wall-stop in this file is attributable to tile 2 alone.

    The behavioural half is sections 4 and 5: the stop coordinates those
    cases pin are derivable only from the same room geometry this case reads
    out of VRAM — together they say the map the hand built, the map the PPU
    draws, and the map the probe consults are one map.
    """
    for a, b, an, bn in (("ES_V_MZ_CHR", "ES_V_MZ_MAP", "bg chr", "tilemap"),
                         ("ES_V_MZ_CHR", "ES_V_MZ_OBJ_CHR", "bg chr", "obj chr"),
                         ("ES_V_MZ_MAP", "ES_V_MZ_OBJ_CHR", "tilemap", "obj chr")):
        ra = range(_sym(a)["start"], _sym(a)["start"] + _sym(a)["size"])
        rb = range(_sym(b)["start"], _sym(b)["start"] + _sym(b)["size"])
        assert not (set(ra) & set(rb)), f"{an} and {bn} claims overlap in VRAM"

    blob = (ASSETS / "mz_room.bin").read_bytes()
    raw = bytes(fresh.read_bytes(V, V_MAP * 2, MAP_DIM * MAP_DIM * 2))
    assert raw[0::2] == blob, (
        "the rendered tilemap and col_map's world blob disagree — the "
        "single-source property is broken")

    flags = (ASSETS / "mz_flags.bin").read_bytes()
    assert len(flags) == 256 and flags[TILE_WALL] == 1 and sum(flags) == 1, (
        "mz_flags is not the declared flag table (tile 2 solid, nothing else)")
