"""sprite_game — the OBJ-only catch game, and the oam_sprites isolation test.

Lockstep-native: `Machine` only, no MesenRunner,
no wall-clock surface, every read taken from a parked exact frame and every
capture landed on an absolute one.

WHAT THIS RAIL IS FOR, and therefore what these tests must prove. `sprite_game`
is the OBJ-only rail — the only one in the set with no BG macros at all, which
makes it a genuine oam_sprites isolation test"*. So beyond the source's own
done-condition (boots, both sprites visible, a catch scores and relocates the
dot — twice, so the cycle really advances), the module owes an ISOLATION proof:
the whole rendered frame is two 8x8 sprites over the backdrop colour and
NOTHING else — no BG pipeline composed, no text, one VRAM claim in the entire
map (`test_the_whole_screen_is_two_sprites_over_bare_backdrop`,
`test_the_composition_is_obj_only`).

THE CATCH IS ASSERTED ON ITS RENDERED OUTPUT: the dot's OAM entry (and its
pixels) JUMPING to the next preset. The score word is read too — it is the
rail's own named done-condition ("score ($3A) increments by 1") and the game
state the rail teaches — but as the supplement, never the substitute: every
catch assertion pairs it with the relocation the player sees. The collision
contract under test is `engine_col_box` exactly (sf_collision.inc:20-28):
STRICT half-open [x, x+w) — an
edge-to-edge touch is NOT a catch — which gets its own boundary-walk test
at |px - dot_x| = 8 -> 6.

STATE CYCLES RUN BOTH WAYS. The player is driven right-then-left and
down-then-up back to its start; the X9 bit is driven over the 256 edge and
back (this rail has NO clamp — the source bounds nothing — so X9 is live
behaviour, not defence); the dot's preset cycle is driven through all four
spots AND the wrap back to preset 0, with the score required to track
catches 1:1 the whole way (one pass = one catch, the self-debounce).

THE STAGING CLAIM READS THE SHADOW, NOT HARDWARE OAM (the scroller port's
falsification finding, the spec): `oam_nmi_dma` commits the whole shadow
every armed VBlank whether or not the scene staged anything, so hardware
write counters climb identically in both worlds. The shadow is this
feature's own output region; hardware OAM is the composed one. Each is read
for the claim it can actually carry.
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
ROM = BUILD / "sprite_game.sfc"
ASSETS = BUILD / "assets"
# One expression, the shape conftest resolves a module's map from at COLLECTION
# time (it refuses a module whose map it cannot see).
_JMAP = json.loads((SUPERFORGE / "build" / "sprg" / "symbol_map.json").read_text())

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
C_OBJ = _sym("ES_C_OBJ_PAL", "play")["start"]           # CGRAM word index
C_BACKDROP = _sym("ES_C_BACKDROP_COLOR", "play")["start"]
OAM_PLAYER = _sym("ES_O_PLAYER", "play")["start"]       # sprite slot
OAM_DOT = _sym("ES_O_DOT", "play")["start"]
OAM_PAD = _sym("ES_O_HI_PAD", "play")["start"]
OAM_PAD_N = _sym("ES_O_HI_PAD", "play")["size"]
OAM_SHADOW = _sym("ES_OAM_SHADOW")["start"]             # WRAM byte address
DP_SCORE = _sym("US_SCORE", "play")["start"]            # DP offset = WRAM addr

# --- the rail's geometry, from game/sprite_game/sprg.inc ---------------------
HOME_X, HOME_Y, SPEED, SIZE = 120, 100, 2, 8
PARK_Y = 0xF0
OAM_HI_BASE = 512                       # the hi table: last 32 B of the 544

BOOT = 90                               # the absolute frame every read lands on

# The rail's actors, written out here. `sprite_tile` is eight rows of $FF,$00
# then eight of $00,$00 — an 8x8 block of colour index 1; OBJ_RED/OBJ_YELLOW
# are the two palettes' index-1 colours; `dot_presets` is the catch cycle. All
# are written out rather than read from anywhere so the assertions survive on
# a bare runner; `test_the_vendored_art_still_matches_the_reference` re-reads
# them out of an external reference tree wherever one IS configured, so the
# constants cannot rot.
REFERENCE_SPRITE_TILE = bytes([0xFF, 0x00] * 8 + [0x00, 0x00] * 8)
REFERENCE_OBJ_RED = 0x001F
REFERENCE_OBJ_YELLOW = 0x03FF
PRESETS = [(200, 60), (60, 60), (200, 160), (60, 160)]
# An OPTIONAL external reference tree, named by `SF_REFERENCE_TREE`.
# Unset on an ordinary runner, which is why the cases below SKIP rather
# than fail: they are ground-truth checks against a second, independent
# implementation, and there is nothing to check against when none is on
# disk.
_REFERENCE_TREE = Path(os.environ.get("SF_REFERENCE_TREE",
                                      "/nonexistent/reference-tree"))
REFERENCE_MAIN = _REFERENCE_TREE / "templates" / "sprite_game" / "main.asm"


def _oam(m, slot):
    """The four low-table bytes of one sprite, plus its X9 and size bits."""
    x, y, tile, attr = m.read_bytes(O, slot * 4, 4)
    hi = m.read_byte(O, OAM_HI_BASE + slot // 4)
    bits = (hi >> ((slot % 4) * 2)) & 3
    return x, y, tile, attr, bits & 1, (bits >> 1) & 1


def _score(m):
    return m.read_u16(W, DP_SCORE)


def _dot(m):
    """The dot's rendered position — the catch's output region."""
    e = _oam(m, OAM_DOT)
    return e[0], e[1]


def _chase_one_catch(m, max_frames=300):
    """Hold the pad toward the dot until the dot RELOCATES (= a catch).

    Reads only rendered output (the OAM low-table bytes the PPU draws) to
    pick each frame's pad, so the drive is a pure function of the machine's
    own trajectory — deterministic and replayable. All chase coordinates
    stay in 60..200, so the 8-bit OAM X cannot alias (no wrap ambiguity),
    and every spawn/preset/home coordinate is EVEN with SPEED = 2, so the
    approach lands exact pixel parities. Returns frames spent.
    """
    x0, y0 = _dot(m)
    for i in range(max_frames):
        if _dot(m) != (x0, y0):
            return i
        px, py, *_ = _oam(m, OAM_PLAYER)
        pad = {}
        if px < x0:
            pad["right"] = True
        elif px > x0:
            pad["left"] = True
        if py < y0:
            pad["down"] = True
        elif py > y0:
            pad["up"] = True
        m.advance(1, pad1=pad)
    raise AssertionError(f"no catch within {max_frames} frames "
                         f"(dot at ({x0}, {y0}))")


@pytest.fixture(scope="module", autouse=True)
def rom_built():
    r = subprocess.run(["make", "sprite_game"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"make sprite_game failed rc={r.returncode}:\n{r.stdout}\n{r.stderr}")
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
    """VRAM at the claim's base against sprg_obj_chr.bin.

    The DESTINATION region, read directly. A test that only asserted "a red
    square renders" would pass with half the block uploaded — every pixel is
    colour index 1 in plane 0, so a missing plane 1/2/3 looks identical.
    """
    want = (ASSETS / "sprg_obj_chr.bin").read_bytes()
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
def test_the_vendored_art_still_matches_the_reference():
    """Re-read this module's constants out of the reference tree so they cannot
    rot: the tile bytes, both colour equates, and the preset table.

    Reference-gated exactly like test_hud_game's asset ground truth: the tree
    is read-only and never a build dependency, so this skips where it is
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
    assert f"OBJ_RED    = ${REFERENCE_OBJ_RED:04X}" in src
    assert f"OBJ_YELLOW = ${REFERENCE_OBJ_YELLOW:04X}" in src
    body = src.split("dot_presets:", 1)[1].split("\n\n", 1)[0]
    nums = []
    for line in body.splitlines():
        line = line.split(";")[0].strip()
        if not line.startswith(".word"):
            continue
        nums += [int(t.strip()) for t in line[len(".word"):].split(",")]
    assert [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)] == PRESETS, (
        "the reference dot_presets has moved away from this module's copy")


def test_the_obj_palettes_are_the_destination_of_the_blob(fresh):
    """CGRAM at the claim's base against sprg_obj_pal.bin — BOTH palettes —
    and index 1 of each is the declared colour: palette 0 red, palette 1 yellow.

    CGRAM is the region a whole sprite pipeline can silently skip — a
    `[sprites]` section that is never parsed no-ops the upload while every
    downstream effect still "works" and the sprite is merely invisible or
    wrong-coloured. So it is read directly, and
    the two index-1 words are named — they are what "independently-coloured"
    physically is.
    """
    want = (ASSETS / "sprg_obj_pal.bin").read_bytes()
    got = fresh.read_bytes(C, C_OBJ * 2, len(want))
    assert got == want
    assert int.from_bytes(got[2:4], "little") == REFERENCE_OBJ_RED, (
        "OBJ palette 0 index 1 is not OBJ_RED")
    assert int.from_bytes(got[34:36], "little") == REFERENCE_OBJ_YELLOW, (
        "OBJ palette 1 index 1 is not OBJ_YELLOW")


def test_the_backdrop_is_black(fresh):
    assert fresh.read_u16(C, C_BACKDROP * 2) == 0x0000, "backdrop is not black"


# =============================================================================
# 2. THE RESTING STATE — one tile, two palettes, two spawns
# =============================================================================
def test_both_actors_rest_at_their_spawns_from_one_shared_tile(fresh):
    """OAM entries 0 and 1: the source's spawns, the SAME tile, palettes 0/1.

    The tile equality is the rail's second teaching read off the table the
    PPU draws from: two sprites, one CHR block, told apart only by the attr's
    palette-select bits.
    """
    px, py, ptile, pattr, px9, psize = _oam(fresh, OAM_PLAYER)
    dx, dy, dtile, dattr, dx9, dsize = _oam(fresh, OAM_DOT)
    assert (px, py) == (HOME_X, HOME_Y), f"player spawn ({px}, {py})"
    assert (dx, dy) == PRESETS[0], f"dot spawn ({dx}, {dy})"
    assert ptile == dtile == 0, "both actors must draw the claim's one tile"
    assert (pattr >> 1) & 7 == 0, f"player attr {pattr:#04x}: want palette 0"
    assert (dattr >> 1) & 7 == 1, f"dot attr {dattr:#04x}: want palette 1"
    assert pattr & 1 == dattr & 1 == 0, "tile bit 8 set on an actor"
    assert (px9, psize, dx9, dsize) == (0, 0, 0, 0), (
        "8x8 sprites with X < 256 have X9 and size clear")
    for i in range(OAM_PAD_N):
        assert _oam(fresh, OAM_PAD + i)[1] == PARK_Y, (
            f"hi-pad slot {i} is on screen")


def test_both_actors_are_restaged_every_frame_not_written_once(fresh):
    """The SHADOW's write counters climb per frame — the source's per-frame
    spr_clear + spr shape, and the staging path under test for the whole run.

    Read on the OAM shadow, this feature's own output region, NOT hardware
    OAM: `oam_nmi_dma` commits the whole shadow every armed VBlank whether or
    not the scene staged anything, so a hardware counter climbs identically
    with the staging deleted.
    """
    before = [fresh.writes(W, OAM_SHADOW + OAM_PLAYER * 4),
              fresh.writes(W, OAM_SHADOW + OAM_DOT * 4)]
    fresh.advance(30)
    after = [fresh.writes(W, OAM_SHADOW + OAM_PLAYER * 4),
             fresh.writes(W, OAM_SHADOW + OAM_DOT * 4)]
    assert after[0] >= before[0] + 30, (
        f"player X staged {after[0] - before[0]} times in 30 frames")
    assert after[1] >= before[1] + 30, (
        f"dot X staged {after[1] - before[1]} times in 30 frames")


# =============================================================================
# 3. MOVEMENT — both directions of both axes, idle, and the 256 edge
# =============================================================================
def test_the_dpad_moves_the_player_right_and_back(fresh):
    """Right then left, back to the start — the reverse leg is the test.

    Read from OAM, which is what the PPU draws, not from the DP word the draw
    is derived from.
    """
    x0 = _oam(fresh, OAM_PLAYER)[0]
    fresh.advance(10, pad1={"right": True})
    fresh.advance(1)                        # OAM lags the tick by one park
    x1 = _oam(fresh, OAM_PLAYER)[0]
    assert x1 == x0 + 10 * SPEED, f"right: {x0} -> {x1}"
    fresh.advance(10, pad1={"left": True})
    fresh.advance(1)
    assert _oam(fresh, OAM_PLAYER)[0] == x0, "left did not return the player"


def test_the_dpad_moves_the_player_down_and_back(fresh):
    y0 = _oam(fresh, OAM_PLAYER)[1]
    fresh.advance(10, pad1={"down": True})
    fresh.advance(1)
    y1 = _oam(fresh, OAM_PLAYER)[1]
    assert y1 == y0 + 10 * SPEED, f"down: {y0} -> {y1}"
    fresh.advance(10, pad1={"up": True})
    fresh.advance(1)
    assert _oam(fresh, OAM_PLAYER)[1] == y0, "up did not return the player"


def test_idle_frames_leave_both_actors_still(fresh):
    """The third state of the cycle: no pad held, nothing may move —
    both full OAM entries, byte for byte."""
    before = (_oam(fresh, OAM_PLAYER), _oam(fresh, OAM_DOT))
    fresh.advance(45)
    assert (_oam(fresh, OAM_PLAYER), _oam(fresh, OAM_DOT)) == before
    assert _score(fresh) == 0


def test_the_player_crosses_the_screen_edge_and_x9_tracks_bit_8(fresh):
    """NO CLAMP is the source's shape, and X9 is its live consequence: driven
    past X = 256 the low byte wraps and the hi-table bit must SET; driven
    back it must CLEAR. Both directions of the bit's cycle, because a stale
    X9 renders a sprite 256 px away — the failure this project has a
    lessons-learned entry about.

    (Home X = 120, so 80 held-right frames put the player at 280 = $118:
    low byte 24, X9 = 1. The dot's X9 — bit 2 of the same rebuilt byte —
    must stay 0 throughout.)
    """
    fresh.advance(80, pad1={"right": True})
    fresh.advance(1)
    x, _, _, _, x9, _ = _oam(fresh, OAM_PLAYER)
    assert (x, x9) == ((HOME_X + 160) & 0xFF, 1), (
        f"at 280 the OAM must read (24, X9=1), got ({x}, {x9})")
    assert _oam(fresh, OAM_DOT)[4] == 0, "the dot's X9 was disturbed"
    fresh.advance(80, pad1={"left": True})
    fresh.advance(1)
    x, _, _, _, x9, _ = _oam(fresh, OAM_PLAYER)
    assert (x, x9) == (HOME_X, 0), (
        f"back at home the OAM must read (120, X9=0), got ({x}, {x9})")


# =============================================================================
# 4. THE CATCH — relocation rendered, score tracking, strict contract, wrap
# =============================================================================
def test_the_first_catch_scores_and_relocates_the_dot(fresh):
    """The reference oracle's own script (right 40, up 25): the dot JUMPS to
    preset 1 — the catch's rendered output — and the score word (the
    done-condition's "$3A increments by 1") reads exactly 1."""
    assert _dot(fresh) == PRESETS[0]
    fresh.advance(40, pad1={"right": True})
    fresh.advance(25, pad1={"up": True})
    fresh.advance(1)
    assert _dot(fresh) == PRESETS[1], "the dot did not jump to preset 1"
    assert _score(fresh) == 1


def test_touching_edge_to_edge_is_not_a_catch_on_either_side(fresh):
    """The col_box contract, on the boundary itself — and on BOTH its
    signs. Boxes span the half-open [x, x+w), so |px - dot_x| = 8 shares
    ZERO pixels and must not catch — held there for 30 frames — while one
    more step (diff 6, two shared columns) must. Walked from the LEFT
    (px - dot_x = -8) and then, against the relocated dot, from the RIGHT
    (px - dot_x = +8): the two edges are enforced by DIFFERENT ends of the
    in-range compare, so a one-sided walk passes with the positive bound
    widened to the shmup's closed-range shape — which is precisely what the
    first falsification plant proved before this test grew its second leg.
    """
    # ---- leg A: the LEFT edge of preset 0's dot (d = -8, then -6) ----------
    fresh.advance(20, pad1={"up": True})        # py 100 -> 60: y aligned
    fresh.advance(36, pad1={"right": True})     # px 120 -> 192 = dot_x - 8
    fresh.advance(1)
    px, py, *_ = _oam(fresh, OAM_PLAYER)
    assert (px, py) == (PRESETS[0][0] - SIZE, PRESETS[0][1]), (
        f"the approach missed the left edge: player at ({px}, {py})")
    fresh.advance(30)                           # parked touching, 30 frames
    assert _dot(fresh) == PRESETS[0], "a left edge-to-edge touch caught"
    assert _score(fresh) == 0
    fresh.advance(1, pad1={"right": True})      # px 194: 2 shared columns
    fresh.advance(1)
    assert _dot(fresh) == PRESETS[1], "a 2-px overlap did not catch (left)"
    assert _score(fresh) == 1
    # ---- leg B: the RIGHT edge of preset 1's dot (d = +8, then +6) ---------
    # The catch left the player at (194, 60) and the dot at (60, 60) — same
    # row, so a straight left drive walks d down from +134 and STOPS at +8,
    # one step short of the overlap zone (|d| < 8 first at px = 67).
    fresh.advance(63, pad1={"left": True})      # px 194 -> 68 = dot_x + 8
    fresh.advance(1)
    px, py, *_ = _oam(fresh, OAM_PLAYER)
    assert (px, py) == (PRESETS[1][0] + SIZE, PRESETS[1][1]), (
        f"the approach missed the right edge: player at ({px}, {py})")
    fresh.advance(30)
    assert _dot(fresh) == PRESETS[1], "a right edge-to-edge touch caught"
    assert _score(fresh) == 1
    fresh.advance(1, pad1={"left": True})       # px 66: 2 shared columns
    fresh.advance(1)
    assert _dot(fresh) == PRESETS[2], "a 2-px overlap did not catch (right)"
    assert _score(fresh) == 2


def test_four_catches_walk_the_preset_cycle_and_wrap(fresh):
    """The dot's whole state cycle — all four presets AND the wrap back to
    preset 0 (the source's `and #$0003`) — with the score required to track
    relocations 1:1 the entire way: one pass = one catch (the self-debounce),
    asserted at every step rather than once at the end."""
    seen = [_dot(fresh)]
    for n in range(1, 5):
        _chase_one_catch(fresh)
        seen.append(_dot(fresh))
        assert _score(fresh) == n, (
            f"catch {n}: score {_score(fresh)} — a pass did not count once")
    assert seen == [PRESETS[0], PRESETS[1], PRESETS[2], PRESETS[3],
                    PRESETS[0]], f"the dot walked {seen}"


# =============================================================================
# 5. THE PICTURE — landed on an absolute frame
# =============================================================================
# THE CAPTURE IS 256x239, NOT 256x224, and the offset is READ OUT OF THE
# EMULATOR'S SOURCE rather than guessed: `SnesPpu.cpp:1410` places a
# non-overscan frame at scanline + 6, and :1505-1508 blank the top 7 / bottom
# 8 rows. An 8x8 OBJ at OAM Y = v occupies scanlines v+1 .. v+8, so PNG rows
# v+7 .. v+14; OAM X = h occupies PNG columns h .. h+7. (test_hud_game's
# derivation, reused: both subjects here are OBJs.)
SHOT_DY = 6


def _pixels(path):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    return img.size, list(img.getdata())


def _classify(path):
    """Every pixel of the capture, bucketed: red, yellow, black, other."""
    (w, h), d = _pixels(path)
    buckets = {"red": [], "yellow": [], "black": 0, "other": []}
    for y in range(h):
        for x in range(w):
            r, g, b = d[y * w + x]
            if r > 150 and g < 90 and b < 90:
                buckets["red"].append((x, y))
            elif r > 150 and g > 150 and b < 90:
                buckets["yellow"].append((x, y))
            elif r < 40 and g < 40 and b < 40:
                buckets["black"] += 1
            else:
                buckets["other"].append((x, y, (r, g, b)))
    return (w, h), buckets


def _bbox(pts):
    xs, ys = sorted({x for x, y in pts}), sorted({y for x, y in pts})
    return xs, ys


def _sprite_at(pts, ox, oy, who):
    """Assert `pts` is exactly one 8x8 block at OAM position (ox, oy)."""
    assert len(pts) == 64, f"{who}: {len(pts)} px, want 64"
    xs, ys = _bbox(pts)
    assert xs == list(range(ox, ox + 8)), f"{who} cols {xs[0]}..{xs[-1]}"
    assert ys == list(range(oy + 1 + SHOT_DY, oy + 1 + SHOT_DY + 8)), (
        f"{who} rows {ys[0]}..{ys[-1]}, OAM Y is {oy}")


def test_the_whole_screen_is_two_sprites_over_bare_backdrop(fresh, tmp_path):
    """The done-condition's picture AND the isolation proof in one census:
    64 red px at the player's spawn, 64 yellow px at the dot's, and EVERY
    other pixel backdrop-black — nothing else may draw, because nothing else
    is composed. A stray BG tile, a lit garbage tilemap, a wrong TM bit or an
    unparked pad sprite all land in `other`/miscounts and fail loudly. This
    is the rail's why-here, read off the screen.
    """
    (w, h), bk = _classify(fresh.screenshot(str(tmp_path / "boot.png")))
    assert not bk["other"], f"non-backdrop pixels beyond the actors: " \
                            f"{bk['other'][:4]}"
    _sprite_at(bk["red"], HOME_X, HOME_Y, "player")
    _sprite_at(bk["yellow"], *PRESETS[0], "dot")
    assert bk["black"] == w * h - 128, "the backdrop census does not close"


def test_the_catch_repaints_the_dot_at_its_new_spot(fresh, tmp_path):
    """The relocation on PIXELS: after the oracle catch the yellow block
    renders at preset 1 and nowhere else — the last link between the OAM
    assertion and what the player sees."""
    fresh.advance(40, pad1={"right": True})
    fresh.advance(25, pad1={"up": True})
    fresh.advance(1)                    # settle: the staged OAM is committed,
    px, py, *_ = _oam(fresh, OAM_PLAYER)  # so entry, picture and this read
    assert _dot(fresh) == PRESETS[1]      # all describe the same rest state
    _, bk = _classify(fresh.screenshot(str(tmp_path / "caught.png")))
    assert not bk["other"]
    _sprite_at(bk["yellow"], *PRESETS[1], "relocated dot")
    _sprite_at(bk["red"], px, py, "player")


# =============================================================================
# 6. THE COMPOSITION — the map-level half of the isolation proof
# =============================================================================
def test_the_composition_is_obj_only():
    """The emitted map itself: no BG feature in the scene, no text, ONE vram
    claim in the whole game (the 16-word OBJ CHR block), one channel (the
    OAM shadow's VBlank DMA). The pixel census proves nothing else DREW;
    this proves nothing else was even COMPOSED — the isolation is by
    construction, not by luck.
    """
    scenes = _JMAP["scenes"]
    assert list(scenes) == ["play"], f"one scene expected: {list(scenes)}"
    everything = scenes["play"]["placements"] + _JMAP["globals"]
    vram = [p for p in everything if p["class"] == "vram"]
    assert [p["sym"] for p in vram] == ["ES_V_OBJ_CHR"], (
        f"vram claims beyond the OBJ CHR block: {[p['sym'] for p in vram]}")
    feats = {p["consumer"] for p in everything
             if p["consumer"].startswith("engine:")}
    bg = {f for f in feats if "_bg" in f or "text" in f or "font" in f}
    assert not bg, f"BG/text features composed in the OBJ-only rail: {bg}"
    chans = [(c["name"], c["ch"]) for c in scenes["play"]["channels"]]
    assert chans == [("oamq", 0)], (
        f"channels beyond the OAM shadow DMA: {chans}")


# =============================================================================
# 7. POWER-ON FIDELITY
# =============================================================================
def test_the_rom_reads_nothing_it_never_wrote(fresh):
    """Rule 5: RAM is random at boot, so every byte read must be written
    first. `LoadRomParked` arms the access counters from the reset vector,
    so this is complete by construction rather than a sample."""
    fresh.assert_no_uninitialized_reads()
