"""m7_dungeon — the rotating Mode 7 floor, the cast on it, and the game.

Three layers, one rail, one module:

  1  a textured Mode 7 dungeon floor under ONE uniform affine matrix,
     rotating about a pivot held at screen centre
  2  the hero PINNED at that pivot and the enemies GLUED to their world
     tiles through the matrix's TRANSPOSE
  3  the GAME — tank controls, per-axis collision against col_map, the
     wall-turn patrol, contact knockback, the win card, pause

LAYER 3 CHANGED THE CLOCK, and several tests here changed with it. The tick
used to advance the heading by itself, so a test could reach any heading by
waiting; now the heading is the PLAYER'S, and reaching one means
holding LEFT or RIGHT. And the enemies MOVE, so a cast oracle built on the
static `enemy_world` ROM seeds would be testing where the slimes USED to be.
Both are addressed head-on rather than around: `_turn_to` drives the pad, and
every cast oracle projects the LIVE positions read out of the ROM's own state.

THE DP->OAM PHASE IS EXACT, MEASURED, AND USED. Hardware OAM holds what the
last NMI committed, which is the shadow the PREVIOUS tick wrote — so a test
that reads state and OAM at the same park is off by one frame. `_snap` reads
the state, steps ONE frame, and then reads OAM: measured 8/8 frames matching
exactly at that phase and 0/7 at every other, so the cast tests below assert
EXACT equality rather than "within one step". (An earlier version allowed a
step of slack; it is no longer needed.)

No PPU-register readback exists in this harness (vendor/mesen_runner.py:147 --
ports read back as zeros), so the matrix is never asserted directly. It is
proven by what it draws, which is what CLAUDE.md rule 2 asks for anyway.
"""
import collections
import json
import struct
import sys
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tools"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

# THE COLLISION ORACLE, and it is genuinely independent of what is under test.
# `is_wall(tx, ty)` is the generator's GEOMETRIC wall predicate — the maze
# string, the cell pitch, the border-opening rule. What the ROM does instead is
# read a packed tile-id byte out of ROM, index a 256-entry flag table with it,
# and mask. The two share no arithmetic: the id indirection, col_map's
# `ty * W + tx` addressing, the bank byte and the flag byte are all on the ROM's
# side of the line. (And the generator itself is gated: it refuses to emit a
# terrain array that differs from the reference's committed one, byte for byte.)
from gen_m7_dungeon_assets import is_wall  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "m7_dungeon.sfc"
ASSETS = BUILD / "assets"
# One expression on purpose: conftest resolves the map a module reads at
# COLLECTION time from exactly this shape, and refuses a module whose map it
# cannot see.
_JMAP = json.loads((SUPERFORGE / "build" / "m7dg" / "symbol_map.json").read_text())

W, V, C = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
           MemoryType.SnesCgRam)
O = MemoryType.SnesSpriteRam


def _sym(name, scene=None):
    """Addresses are ASKED FOR, never hardcoded -- this reads the same map the
    ROM was assembled against, so an allocator move breaks the test loudly
    instead of silently reading the wrong bytes."""
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_M7 = _sym("ES_V_M7", "dungeon")["start"]          # word address
C_PAL = _sym("ES_C_M7DG_PAL", "dungeon")["start"]   # word index

# The scene's state. These are DP bytes, and DP is the low page of WRAM, so
# MemoryType.SnesWorkRam reads them where they are.
DP_HEADING = _sym("US_HEADING", "dungeon")["start"]
DP_POSX = _sym("US_POSX", "dungeon")["start"]       # 16.16: +2 is the integer
DP_POSY = _sym("US_POSY", "dungeon")["start"]
DP_SPEED = _sym("US_SPEED", "dungeon")["start"]     # signed 8.8
DP_ENE_POS = _sym("US_ENE_POS", "dungeon")["start"]  # (x, y) pairs, stride 4
DP_ENE_DIR = _sym("US_ENE_DIR", "dungeon")["start"]
DP_HITS = _sym("US_HITS", "dungeon")["start"]
DP_GRACE = _sym("US_GRACE", "dungeon")["start"]
DP_PAUSED = _sym("US_PAUSED", "dungeon")["start"]


@pytest.fixture(scope="module")
def runner():
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make m7_dungeon` first")
    r = MesenRunner()
    r.boot_rom(str(ROM), frames=90)
    yield r
    r.stop()


@pytest.fixture
def fresh(runner):
    """A rebooted world, for every test that DRIVES it.

    Layer 3 made this ROM stateful in a way layers 1 and 2 were not: the hero
    moves, the enemies pace, hits accumulate. A module-scoped runner shared by
    driving tests would make each one depend on the order pytest happened to
    pick — the classic way a suite goes green on Tuesday and red on Wednesday.
    One MesenRunner (its port-1 controller configuration survives a reload),
    one power-on per driving test.
    """
    runner.boot_rom(str(ROM), frames=30)
    return runner


# The screenshot is 256x239; the ACTIVE PICTURE is rows 7..230 (224 lines).
# Measured, not assumed -- the surrounding rows are blanking and are not part
# of the rendered plane, so a geometric oracle over the whole raster is off by
# the asymmetric margin (7 above, 8 below) and reads as a rendering bug.
ACTIVE_TOP, ACTIVE_H = 7, 224


def _shot(runner, tmp_path, tag):
    p = tmp_path / f"{tag}.png"
    runner.take_screenshot(str(p))
    img = Image.open(p).convert("RGB")
    return img.crop((0, ACTIVE_TOP, 256, ACTIVE_TOP + ACTIVE_H))


def _q(img):
    """5-bit quantised pixels — the SNES's own colour depth, so two colours the
    hardware cannot distinguish are not counted as different."""
    return [(r >> 3, g >> 3, b >> 3) for r, g, b in img.getdata()]


# =============================================================================
# READING THE ROM'S OWN STATE
# =============================================================================
def _u16(runner, addr):
    b = runner.read_bytes(W, addr, 2)
    return b[0] | (b[1] << 8)


def _s16(runner, addr):
    v = _u16(runner, addr)
    return v - 0x10000 if v & 0x8000 else v


def _heading(runner):
    return _u16(runner, DP_HEADING)


def _pos(runner):
    return (_u16(runner, DP_POSX + 2), _u16(runner, DP_POSY + 2))


def _enemies(runner):
    """[(x, y)] — the LIVE world positions the patrol is pacing."""
    raw = runner.read_bytes(W, DP_ENE_POS, ENEMY_N * 4)
    return [(raw[i * 4] | (raw[i * 4 + 1] << 8),
             raw[i * 4 + 2] | (raw[i * 4 + 3] << 8)) for i in range(ENEMY_N)]


def _state(runner):
    """Everything an oracle needs about one frame of the world."""
    return {"h": _heading(runner), "pos": _pos(runner),
            "speed": _s16(runner, DP_SPEED), "ene": _enemies(runner),
            "hits": _u16(runner, DP_HITS), "grace": _u16(runner, DP_GRACE),
            "paused": _u16(runner, DP_PAUSED)}


def _oam(runner):
    return bytes(runner.read_bytes(O, 0, 544))


def _snap(runner):
    """(state, oam) for the SAME frame — the measured DP->OAM phase.

    Hardware OAM holds what the last NMI committed, i.e. the shadow the
    PREVIOUS tick wrote, so reading both at one park is off by a frame. Read
    the state, advance exactly one, then read OAM: measured 8/8 exact at this
    phase, 0/7 at lag 1 and lag 2. Must be called inside `frame_stepping()`.
    """
    st = _state(runner)
    runner.frame_step(1)
    return st, _oam(runner)


# =============================================================================
# DRIVING THE ROM
# =============================================================================
# The pad is the only way into this ROM now, which is the point of the slice —
# so these are the test suite's steering wheel, not a convenience layer.
def _turn_to(runner, target, limit=400):
    """Hold LEFT or RIGHT (whichever is the short way) until the heading reads
    `target`. Must be called inside `frame_stepping()`; no throttle is held, so
    the hero coasts to rest while turning rather than driving into a wall."""
    for _ in range(limit):
        h = _heading(runner)
        if h == target:
            return
        d = (target - h) & 255
        runner.frame_step(1, left=(d <= 128), right=(d > 128))
    raise AssertionError(
        f"the heading never reached {target} (stuck at {_heading(runner)}) — "
        f"is do_turn reading the pad?")


def _rest(runner, limit=80):
    """Release everything until the speed reaches exactly zero.

    Turning under residual speed steers the hero through the corridor while the
    heading sweeps, which is real behaviour but makes a route non-reproducible.
    Coming to rest first makes every leg start from the same condition.
    """
    for _ in range(limit):
        if _u16(runner, DP_SPEED) == 0:
            return
        runner.frame_step(1)
    raise AssertionError(
        f"the hero never came to rest (speed {_s16(runner, DP_SPEED)}) — "
        f"is the coast arm of do_throttle bleeding toward zero?")


def _drive(runner, frames, stop_when_stuck=None, **buttons):
    """Hold `buttons` for `frames`, sampling the world EVERY frame.

    Returns the per-frame state list. Sampling every frame rather than at the
    ends is not thoroughness for its own sake: a collision failure is a
    TRANSIENT — the hero enters a wall and the next frame's clamp or knockback
    puts it somewhere legal again — so an end-state assertion is exactly the
    shape of test that passes while the feature is broken.
    """
    out = []
    stuck = 0
    for _ in range(frames):
        runner.frame_step(1, **buttons)
        st = _state(runner)
        if out and st["pos"] == out[-1]["pos"]:
            stuck += 1
        else:
            stuck = 0
        out.append(st)
        if stop_when_stuck is not None and stuck >= stop_when_stuck:
            break
    return out


def _pause_toggle(runner):
    """One rising edge on START, then release so the next call can toggle back.

    The ROM latches the edge against last frame's START bit, so a held button
    toggles once — which is the behaviour, and why the release step is here.
    """
    runner.frame_step(1, start=True)
    runner.frame_step(1)


# --- the geometry the game and the tests both derive from -------------------
# Mirrored from game/m7_dungeon/scenes/dungeon.asm, which mirrors the
# generator's own cell algebra. Written as the algebra for the same reason it
# is written that way there: the pivot, the goal and the patrol seeds are
# consequences of the maze, and if the maze moves these follow it.
_MAZE_ORIGIN_T, _MAZE_WALL_T, _MAZE_CELL = 6, 2, 3
_MAZE_PITCH = _MAZE_CELL + _MAZE_WALL_T


def _cell_px(c):
    return (_MAZE_ORIGIN_T + c * _MAZE_PITCH
            + _MAZE_WALL_T + _MAZE_CELL // 2) * 8 + 4


SPAWN = (_cell_px(1), _cell_px(1))          # the 'S' cell — px 116,116
GOAL = (_cell_px(7), _cell_px(7))           # the 'G' cell — px 356,356
GOAL_HALF = 12
ENEMY_SEED = [(_cell_px(2), _cell_px(1)),   # px 156,116
              (_cell_px(5), _cell_px(3)),   # px 276,196
              (_cell_px(6), _cell_px(5))]   # px 316,276
ENEMY_N = len(ENEMY_SEED)

HERO_HALF = 4                               # the 8 px body: -4 .. +3
FOOTPRINT = [(-HERO_HALF, -HERO_HALF), (HERO_HALF - 1, -HERO_HALF),
             (-HERO_HALF, HERO_HALF - 1), (HERO_HALF - 1, HERO_HALF - 1)]
SPEED_CAP = 0x0140                          # +1.25 px/frame
CONTACT_W = 8

# Compass headings. step = (sin h, cos h) x speed and the world moves by
# `pos -= step`, so heading 0 walks the hero NORTH (-y) and the quarter turns
# fall out of that. Derived here once so no test writes 192 and means "east".
NORTH, WEST, SOUTH, EAST = 0, 64, 128, 192


def _footprint_cells(px, py):
    return [((px + dx) // 8 % 128, (py + dy) // 8 % 128) for dx, dy in FOOTPRINT]


def _inside_wall(px, py):
    """Is the hero's 8 px body overlapping a solid cell at (px, py)?"""
    return any(is_wall(tx, ty) for tx, ty in _footprint_cells(px, py))


# =============================================================================
# STAGE 1 — what the floor IS
# =============================================================================

def test_boots_into_a_textured_mode7_floor(runner, tmp_path):
    """Not 'it booted' -- 'it booted into a PICTURE'. A black screen, a solid
    fill, or a two-tone garbage pattern all fail this."""
    img = _shot(runner, tmp_path, "boot")
    assert img.size == (256, ACTIVE_H), img.size
    counts = Counter(_q(img))
    assert len(counts) >= 4, f"only {len(counts)} distinct colours: {counts.most_common(6)}"
    # and it is not one colour with a rounding halo: the second-commonest
    # colour must be a real presence, which is what makes it a TEXTURE.
    top = counts.most_common(2)
    assert top[1][1] > 0.05 * 256 * 224, f"second colour is noise: {top}"


def test_mode7_vram_matches_the_generated_blob(runner):
    """The destination region, byte for byte, against the source bytes -- not a
    downstream consequence of the upload. An upload that silently no-ops
    (that class of defect) fails here and nowhere else."""
    src = (ASSETS / "m7dg_map.bin").read_bytes()
    got = bytes(runner.read_bytes(V, V_M7 * 2, len(src)))
    assert got == src, (
        f"Mode 7 VRAM differs from m7dg_map.bin at byte "
        f"{next(i for i in range(len(src)) if got[i] != src[i])}")


def test_cgram_holds_the_floor_palette_and_index0_is_the_backdrop(runner):
    """CGRAM index 0 is BOTH palette entry 0 and the Mode 7 backdrop slot, and
    the generator deliberately reserves it to FLOOR_A so the backdrop cannot
    show through the floor. Asserting the whole palette AND that specific
    contract, because the reservation is the part a re-theme would break."""
    src = (ASSETS / "m7dg_pal.bin").read_bytes()
    got = bytes(runner.read_bytes(C, C_PAL * 2, len(src)))
    assert got == src, "CGRAM differs from m7dg_pal.bin"
    assert got[0:2] == src[0:2] and src[0:2] != b"\x00\x00", (
        "CGRAM word 0 must be FLOOR_A, not black — the backdrop would show "
        "through every floor pixel")


# =============================================================================
# STAGE 1 — what the floor DOES
# =============================================================================
def _sprite_mask(oam, grow=2):
    """The screen boxes the cast occupies, from the OAM the frame was drawn
    with — so a floor comparison can exclude the actors WITHOUT guessing where
    they are. Every slot this scene owns, parked ones skipped."""
    boxes = []
    for slot in range(O_HERO, O_HI_PAD + 1):
        x, y = oam[slot * 4], oam[slot * 4 + 1]
        if y == PARK_Y:
            continue
        x9 = (oam[512 + slot // 4] >> ((slot % 4) * 2)) & 1
        sx = x - 256 if x9 else x
        # an OBJ draws one scanline BELOW its OAM y
        boxes.append((sx - grow, y + 1 - grow,
                      sx + OBJ_SIDE + grow, y + 1 + OBJ_SIDE + grow))
    return boxes


def _floor_pixels(img, boxes):
    """The frame's pixels with the cast's boxes removed, as a flat list."""
    px = list(img.getdata())
    out = []
    for i, p in enumerate(px):
        x, y = i % 256, i // 256
        if any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in boxes):
            continue
        out.append(((i, p[0] >> 3, p[1] >> 3, p[2] >> 3)))
    return out


def test_a_full_turn_renders_the_same_floor(fresh, tmp_path):
    """The EXACT invariant, and the strongest thing the floor can assert.

    The heading is a byte, so h and h+256 select the same LUT entry, hence the
    same matrix, hence — with the pivot unmoved — the same picture, exactly.
    That one equality covers three separate ways this rail could be broken: the
    heading failing to wrap in 8 bits, the LUT being indexed with drift (a
    stale high byte, an off-by-one stride), and the matrix picking up state
    from somewhere other than the heading.

    THE CAST IS MASKED OUT, and that is layer 3's doing rather than a
    weakening: the enemies PACE now, so they are genuinely somewhere else after
    256 frames of turning and the whole-frame equality is no longer a true
    statement about a working ROM. The mask comes from the OAM each frame was
    actually drawn with — not from a guess about where the sprites might be —
    and the FLOOR comparison stays exact, over ~57k of the 61k pixels.
    """
    with fresh.frame_stepping():
        _turn_to(fresh, 40)
        oam_a = _oam(fresh)
        a = _shot(fresh, tmp_path, "turn_a")
        for _ in range(256):                # a full turn, one step a frame
            fresh.frame_step(1, left=True)
        assert _heading(fresh) == 40, "the heading did not wrap in 8 bits"
        oam_b = _oam(fresh)
        b = _shot(fresh, tmp_path, "turn_b")

    boxes = _sprite_mask(oam_a) + _sprite_mask(oam_b)
    fa, fb = _floor_pixels(a, boxes), _floor_pixels(b, boxes)
    assert len(fa) > 50000, f"the mask ate the frame: only {len(fa)} px left"
    diff = sum(1 for x, y in zip(fa, fb) if x != y)
    assert diff == 0, (
        f"a full turn did not return the same floor: {diff} of {len(fa)} "
        f"unmasked pixels differ — the heading is not wrapping cleanly in 8 "
        f"bits, or the matrix is not a pure function of it")


def test_a_partial_turn_changes_the_picture(fresh, tmp_path):
    """The companion to the exactness test above, and it is not redundant: a
    ROM whose matrix never changed at all would pass that one trivially.

    Measured on the shipping binary: a quarter turn differs on ~38% of pixels.
    The floor is a repeating checkerboard, so even an unrelated picture agrees
    with it ~72% of the time -- which is exactly why the threshold here is
    deliberately well clear of that floor.
    """
    with fresh.frame_stepping():
        _turn_to(fresh, 40)
        a = _q(_shot(fresh, tmp_path, "part_a"))
        _turn_to(fresh, 104)                # a quarter turn
        b = _q(_shot(fresh, tmp_path, "part_b"))

    changed = sum(1 for x, y in zip(a, b) if x != y) / len(a)
    assert changed > 0.15, (
        f"a quarter turn changed only {changed:.3f} of the frame — the plane "
        f"is not rotating")


def test_the_heading_moves_only_when_the_player_turns(fresh):
    """The clock, stated. The tick used to spin the floor by itself; now it is
    the player's, and BOTH halves of that are the claim: the
    pad turns it, and an untouched pad leaves it exactly where it was."""
    with fresh.frame_stepping():
        h0 = _heading(fresh)
        fresh.frame_step(20)
        assert _heading(fresh) == h0, (
            "the heading drifted with no input — the tick is still spinning "
            "the floor on its own")
        for _ in range(10):
            fresh.frame_step(1, left=True)
        h_left = _heading(fresh)
        assert h_left == (h0 + 10) & 255, f"LEFT moved {h0} to {h_left}"
        for _ in range(10):
            fresh.frame_step(1, right=True)
        assert _heading(fresh) == h0, "RIGHT did not undo LEFT step for step"


# =============================================================================
# STAGE 2 — the cast on the plane
# =============================================================================
# What this slice claims: the hero is PINNED at the pivot the matrix rotates
# about, and every other actor is GLUED to its world tile — it stays on that
# tile as the floor turns, which is only true if the world->screen map is the
# render matrix's TRANSPOSE.
#
# THE ORACLE IS THE LUT, not the ROM's DP shadow. `build/assets/m7_affine_lut.bin`
# is a build artifact produced by a different program (tools/gen_m7_affine_lut.py)
# and is already proven against the reference's runtime solve at every heading
# (tests/test_m7_affine_lut.py), so projecting from it is an INDEPENDENT
# computation rather than a restatement of what the ROM did.

_AFFINE_LUT = struct.unpack(
    "<1024h", (ASSETS / "m7_affine_lut.bin").read_bytes())

SCREEN_CX, SCREEN_CY = 128, 112                         # m7a_set_center's pin
OBJ_SIDE = 16
OBJ_HALF = OBJ_SIDE // 2
OAM_X_LO = -(OBJ_SIDE - 1)      # 9-bit signed x: a sprite may hang off the LEFT
OAM_X_HI = 2 * SCREEN_CX - 1
OAM_Y_HI = 2 * SCREEN_CY - 1    # 8-bit unsigned y: no sign bit, so no top hang
PARK_Y = 0xF0

HERO_TILE, ENEMY_TILE, WIN_TILE = 0, 32, 64
ATTR_PRIO = 0x30
PAL_HERO, PAL_ENEMY, PAL_WIN = 0x00, 0x02, 0x04

O_HERO = _sym("ES_O_HERO", "dungeon")["start"]
O_ENEMIES = _sym("ES_O_ENEMIES", "dungeon")["start"]
O_ENEMY_N = _sym("ES_O_ENEMIES", "dungeon")["size"]
O_WIN = _sym("ES_O_WIN", "dungeon")["start"]
O_WIN_N = _sym("ES_O_WIN", "dungeon")["size"]
O_HI_PAD = _sym("ES_O_HI_PAD", "dungeon")["start"]
V_OBJ_CHR = _sym("ES_V_OBJ_CHR", "dungeon")["start"]    # word address
C_HERO_PAL = _sym("ES_C_HERO_PAL", "dungeon")["start"]  # word index
C_ENEMY_PAL = _sym("ES_C_ENEMY_PAL", "dungeon")["start"]
C_WIN_PAL = _sym("ES_C_WIN_PAL", "dungeon")["start"]
OBJ_TILE_WORDS = 16                                     # 8x8 4bpp = 32 B

assert O_ENEMY_N == ENEMY_N, "the oam claim and the seed table disagree"


def _project(h, wx, wy, pivot, forward=False):
    """World px -> signed screen px under heading `h`'s matrix.

    `forward` feeds the render matrix's own pairing (A,B / C,D) instead of its
    transpose (A,C / B,D). That is the WRONG map — it is the screen->texel
    direction applied world->screen — and it exists here so a test can prove
    the ROM is not doing it. The reference keeps the same mistake as a build flag
    (SuperForge templates/m7_dungeon/main.asm, ENEMY_PROJ_FORWARD).
    """
    a, b, c, d = _AFFINE_LUT[(h & 255) * 4:(h & 255) * 4 + 4]
    dx, dy = wx - pivot[0], wy - pivot[1]
    if forward:
        return (((dx * a + dy * b) >> 8) + SCREEN_CX,
                ((dx * c + dy * d) >> 8) + SCREEN_CY)
    return (((dx * a + dy * c) >> 8) + SCREEN_CX,
            ((dx * b + dy * d) >> 8) + SCREEN_CY)


def _oracle(st, i, forward=False):
    """(x9, oam_x, oam_y) for enemy `i` in state `st`, or None if it is culled.

    Mirrors m7dg_obj's window exactly: the sprite is centred on the projected
    point, and the x window runs into the negative because the OBJ x has a sign
    bit while the y window does not.
    """
    sx, sy = _project(st["h"], *st["ene"][i], st["pos"], forward)
    ox, oy = sx - OBJ_HALF, sy - OBJ_HALF
    if not (OAM_X_LO <= ox <= OAM_X_HI and 0 <= oy <= OAM_Y_HI):
        return None
    return ((ox >> 8) & 1, ox & 0xFF, oy)


def _entry(oam, slot):
    """(x9, x, y, tile, attr) — the sprite as the PPU will read it, X9 included.

    X9 lives in the hi table, not in the entry, and reading the entry without it
    is how a sprite 256 px away passes a test: the low byte is identical either
    way.
    """
    e = oam[slot * 4:slot * 4 + 4]
    hi = (oam[512 + slot // 4] >> ((slot % 4) * 2)) & 3
    return (hi & 1, e[0], e[1], e[2], e[3])


def _size_bit(oam, slot):
    return ((oam[512 + slot // 4] >> ((slot % 4) * 2)) >> 1) & 1


def _matches(oam, slot, want, pal):
    """Does the committed entry equal the oracle's answer, exactly?"""
    got = _entry(oam, slot)
    if want is None:
        return got[2] == PARK_Y
    return got == (want[0], want[1], want[2],
                   ENEMY_TILE if pal == PAL_ENEMY else WIN_TILE,
                   ATTR_PRIO | pal)


def _sweep(runner, headings):
    """[(state, oam)] with the ROM parked at each heading in turn."""
    out = []
    with runner.frame_stepping():
        for h in headings:
            _turn_to(runner, h)
            out.append(_snap(runner))
    return out


# --- what the cast IS -------------------------------------------------------

def test_obj_chr_and_palettes_reached_their_destination_regions(runner):
    """The DESTINATION regions, byte for byte, against the source blobs.

    Three sheets into OBJ VRAM and three palettes into CGRAM. An upload that
    silently no-ops — a DAS armed once for three transfers, a CGADD left at the
    previous palette — fails here and only here: every downstream test would
    still see plausible sprites, because a 16x16 OBJ made of whatever VRAM
    happened to hold is a perfectly valid sprite.
    """
    for tile, blob in ((HERO_TILE, "m7dg_hero_chr.bin"),
                       (ENEMY_TILE, "m7dg_enemy_chr.bin"),
                       (WIN_TILE, "m7dg_win_chr.bin")):
        src = (ASSETS / blob).read_bytes()
        at = (V_OBJ_CHR + tile * OBJ_TILE_WORDS) * 2
        got = bytes(runner.read_bytes(V, at, len(src)))
        assert got == src, f"{blob} is not in VRAM at word ${at // 2:04X}"
    for at, blob in ((C_HERO_PAL, "m7dg_hero_pal.bin"),
                     (C_ENEMY_PAL, "m7dg_enemy_pal.bin"),
                     (C_WIN_PAL, "m7dg_win_pal.bin")):
        src = (ASSETS / blob).read_bytes()
        got = bytes(runner.read_bytes(C, at * 2, len(src)))
        assert got == src, f"{blob} is not in CGRAM at word {at}"


def test_the_collision_blobs_reached_rom_intact():
    """The packed tile-id map and the flag table, read out of the .sfc at the
    offsets the ALLOCATOR emitted — the destination region, byte for byte.

    `make rom-unbacked` proves a claim has an `.incbin` somewhere; this proves
    the bytes that landed at the claimed address are the generator's. They are
    different failures: a claim can be backed by the WRONG blob, or by one the
    linker put somewhere else. And it matters more here than for art — a
    collision map that is subtly not the map you see is a rail whose walls are
    in the wrong place, which looks like a physics bug for a long time.

    (The claim's own placement is `p["start"]`, which for ROM is the flat file
    offset — LoROM window w is file offset w * 32768, and the .sfc is
    headerless.)
    """
    rom = ROM.read_bytes()
    for sym, blob in (("ES_R_M7DG_TILEMAP", "m7dg_tilemap.bin"),
                      ("ES_R_M7DG_FLAGS", "m7dg_flags.bin")):
        at = _sym(sym)["start"]
        src = (ASSETS / blob).read_bytes()
        assert _sym(sym)["size"] == len(src), (
            f"{sym} claims {_sym(sym)['size']} B, {blob} is {len(src)} B")
        assert rom[at:at + len(src)] == src, (
            f"{blob} is not at ROM ${at:06X} — the claim site and the "
            f"allocator's placement have come apart")


def test_the_hero_is_pinned_at_screen_centre_whatever_the_heading(fresh):
    """The camera model, as OAM bytes. The pivot renders at (128,112) at every
    heading, so the hero's entry is a constant — and its X9 must be CLEAR and
    its size bit SET, because a stale X9 would put him 256 px away and a clear
    size bit would draw his top-left quarter."""
    for st, oam in _sweep(fresh, (0, 37, 91, 128, 203)):
        assert _entry(oam, O_HERO) == (
            0, SCREEN_CX - OBJ_HALF, SCREEN_CY - OBJ_HALF, HERO_TILE,
            ATTR_PRIO | PAL_HERO), f"hero moved at heading {st['h']}"


# --- what the cast DOES -----------------------------------------------------

def test_the_enemies_are_glued_to_the_plane(fresh):
    """THE CAST'S REAL CLAIM, and the test worth reading.

    An enemy is not "somewhere plausible on screen" — it is on ITS OWN world
    tile, which means its OAM entry must equal, EXACTLY, what the heading's
    matrix maps its LIVE world position to, with the culled ones parked.
    Checked at eight headings spread around the turn, because a single heading
    proves nothing about rotation: the identity matrix, the forward matrix and
    the transpose all agree at heading 0.

    Every part of the entry is checked, including X9 and the palette bits. A
    dropped X9 is invisible in the low byte and puts the sprite 256 px right.
    """
    for st, oam in _sweep(fresh, (0, 10, 40, 64, 91, 128, 150, 203)):
        for i in range(ENEMY_N):
            want = _oracle(st, i)
            assert _matches(oam, O_ENEMIES + i, want, PAL_ENEMY), (
                f"heading {st['h']}, enemy {i} at world {st['ene'][i]}: OAM "
                f"says {_entry(oam, O_ENEMIES + i)[:3]}, the transpose says "
                f"{want} and the FORWARD matrix says {_oracle(st, i, True)}")


def test_every_visible_sprite_is_16x16(fresh):
    """The hi table's SIZE bit, swept — and asserted with NO oracle at all.

    Every actor on this rail is 16x16, and OBSEL's size pair 0 puts 16x16 in
    the LARGE half, so the bit is set per slot every frame. A clear one draws
    the actor's top-left 8x8 quarter.

    THIS IS A PHASE-FREE INVARIANT AND IT IS TESTED AS ONE. It is true of any
    single frame: a slot that is not parked has its size bit set. Asserting it
    inside a test that has already settled a HEADING from positions ties a
    claim with no phase to an oracle that has one — which is how a byte-
    identical tree goes green on a branch and red on main (CI #548). So: sweep
    consecutive frames, check every unparked slot this scene owns, no
    projection involved.
    """
    seen = 0
    with fresh.frame_stepping():
        for _ in range(600):
            fresh.frame_step(1)
            oam = _oam(fresh)
            for slot in range(O_HERO, O_HI_PAD + 1):
                if oam[slot * 4 + 1] == PARK_Y:
                    continue
                seen += 1
                assert _size_bit(oam, slot) == 1, (
                    f"OAM slot {slot} is visible at "
                    f"({oam[slot * 4]},{oam[slot * 4 + 1]}) with its size bit "
                    f"clear — it will draw as its top-left 8x8 quarter")
    assert seen > 500, (
        f"only {seen} visible-sprite samples in 600 frames — the sweep barely "
        f"exercised the bit it claims to check")


def test_the_projection_is_the_transpose_and_not_the_forward_matrix(fresh):
    """The negative control, run against the shipping binary.

    The forward pairing (A,B / C,D) is the render matrix's OWN direction —
    screen->texel — and applying it world->screen counter-rotates every sprite.
    It still moves, still stays on screen, and still looks like a rotating
    dungeon, which is exactly why it needs a test rather than a look.

    Headings are chosen where the two pairings DIFFER: at 0 and 128 the matrix
    is diagonal and both agree, so those would pass either way. They are also
    walked in SMALL steps — turning is one heading unit per frame and the
    slimes pace while it happens, so a sweep with long jumps between headings
    spends its budget walking the cast out of view and reaches fewer
    discriminating cases than one that stays close.
    """
    checked = 0
    for st, oam in _sweep(fresh, range(6, 128, 10)):
        for i in range(ENEMY_N):
            good, bad = _oracle(st, i), _oracle(st, i, forward=True)
            if good is None or good == bad:
                continue                    # not a discriminating case
            assert _matches(oam, O_ENEMIES + i, good, PAL_ENEMY)
            assert not _matches(oam, O_ENEMIES + i, bad, PAL_ENEMY), (
                f"heading {st['h']} enemy {i}: the committed entry matches the "
                f"FORWARD matrix ({bad}) — the projection is not transposed")
            checked += 1
    assert checked >= 6, (
        f"only {checked} discriminating (heading, enemy) pairs were reached — "
        f"this test is not exercising the transpose")


def test_the_cull_is_the_oracle_s_over_a_whole_turn(fresh):
    """Culling, swept over a whole turn rather than sampled — and asserted
    EXACTLY, entry by entry, not as a set of headings.

    The pre-cull is comparisons only: rotation preserves distance, so a world
    point outside the padded view's circumradius is off-screen at EVERY heading
    and m7_project answers it without a multiply. The claim here is that the
    ROM's park/draw decision agrees with the oracle's at every heading of the
    turn, and the non-vacuity guard is that BOTH answers occur.
    """
    drawn = culled = 0
    for st, oam in _sweep(fresh, range(0, 256, 4)):
        for i in range(ENEMY_N):
            want = _oracle(st, i)
            assert _matches(oam, O_ENEMIES + i, want, PAL_ENEMY), (
                f"heading {st['h']} enemy {i}: cull disagreement — OAM "
                f"{_entry(oam, O_ENEMIES + i)[:3]}, oracle {want}")
            if want is None:
                culled += 1
            else:
                drawn += 1
    assert drawn > 20 and culled > 20, (
        f"the sweep saw {drawn} drawn and {culled} culled — one of the two "
        f"branches was never exercised, so this test proves only the other")


# --- what the cast LOOKS LIKE ----------------------------------------------
# The colour bands are the generator's own, stated in
# tools/gen_m7_dungeon_assets.py: the floor is COOL and dark, the walls are warm
# but below r=205, the enemy's body is warm AND bright (r>=205), the hero is
# desaturated steel/bone, and the win card is GOLD — bright in red AND green
# with the blue well down, which is what separates it from the enemy's warm
# orange (g~107) and the hero's near-neutral bone.

def _is_enemy_px(p):
    return p[0] >= 205 and p[0] - p[2] >= 64


def _is_hero_px(p):
    return abs(p[0] - p[2]) <= 24 and p[0] >= 90


def _is_gold_px(p):
    return p[0] >= 230 and p[1] >= 180 and p[1] - p[2] >= 60


def _drawable_enemies(oam, rad=5):
    """The enemy slots whose sprite CENTRE lands inside the active picture with
    room for a `rad` patch — a stricter window than the ROM's cull, on purpose
    (see the caller). An OBJ draws one scanline BELOW its OAM y."""
    out = []
    for i in range(O_ENEMY_N):
        x, y = oam[(O_ENEMIES + i) * 4], oam[(O_ENEMIES + i) * 4 + 1]
        if y == PARK_Y:
            continue
        cx, cy = x + OBJ_HALF, y + 1 + OBJ_HALF
        if rad <= cx < 256 - rad and rad <= cy < ACTIVE_H - rad:
            out.append(i)
    return out


def _patch(img, cx, cy, rad=5):
    return [img.getpixel((x, y))
            for y in range(max(0, cy - rad), min(ACTIVE_H, cy + rad + 1))
            for x in range(max(0, cx - rad), min(256, cx + rad + 1))]


def test_the_sprites_are_actually_drawn_where_their_oam_entries_say(fresh,
                                                                    tmp_path):
    """The framebuffer, not the tables. Every test above reads OAM, CGRAM and
    VRAM — all of which can be perfectly correct while nothing composites (TM's
    OBJ bit clear renders exactly that: right bytes everywhere, empty screen).

    So: warm-bright enemy pixels at each visible enemy's OAM centre and NOWHERE
    near the hero's, and near-neutral hero pixels at the hero's. An OBJ draws
    one scanline BELOW its OAM y, which is why the centre is oam_y + 1 + 8.
    """
    for h in (0, 40, 91):
        with fresh.frame_stepping():
            _turn_to(fresh, h)
            # The slimes PACE, so whether one is in view at a given heading is
            # a property of the moment, not of the heading. Wait for a frame
            # that has one rather than asserting the cast into position — the
            # claim is about where a drawn sprite lands, and a frame with none
            # simply does not exercise it.
            #
            # "In view" here is stricter than the ROM's own cull, deliberately:
            # m7dg_obj admits any OAM y up to 223, which for a 16 px sprite
            # includes rows that begin below the last visible scanline. Those
            # are legitimately unparked and legitimately invisible, so they are
            # not frames this test can read a pixel from.
            for _ in range(180):
                fresh.frame_step(1)
                oam = _oam(fresh)
                drawn = _drawable_enemies(oam)
                if drawn:
                    break
            else:
                pytest.fail(f"heading {h}: no enemy came fully into view in "
                            f"180 frames — the cull is rejecting everything")
            img = _shot(fresh, tmp_path, f"draw_{h}")

        hx, hy = oam[O_HERO * 4] + OBJ_HALF, oam[O_HERO * 4 + 1] + 1 + OBJ_HALF
        hero_px = _patch(img, hx, hy)
        assert sum(_is_hero_px(p) for p in hero_px) >= 50, (
            f"heading {h}: no hero-coloured pixels at ({hx},{hy}) — "
            f"{collections.Counter(hero_px).most_common(3)}")
        assert not any(_is_enemy_px(p) for p in hero_px), (
            f"heading {h}: the hero's centre holds enemy colours — the two "
            f"sprites are not distinguishable, or the wrong sheet is at tile 0")

        for i in drawn:
            ex = oam[(O_ENEMIES + i) * 4] + OBJ_HALF
            ey = oam[(O_ENEMIES + i) * 4 + 1] + 1 + OBJ_HALF
            px = _patch(img, ex, ey)
            assert sum(_is_enemy_px(p) for p in px) >= 50, (
                f"heading {h}: enemy {i}'s OAM says ({ex},{ey}) but the frame "
                f"holds {collections.Counter(px).most_common(3)} there")


# =============================================================================
# STAGE 3 — THE GAME
# =============================================================================
# The rail stops being a demo here: the floor turns because the player turns it,
# walls stop you, slimes pace and hurt, and the goal says so.
#
# EVERY TEST BELOW DRIVES THE ROM THROUGH THE PAD and reads what the hardware
# then holds — the hero's world position out of the ROM's own state, the cast
# out of OAM, the flash and the win card out of the framebuffer. Nothing here
# asserts on a variable that "should be" a function of the thing under test.

# --- the tank ---------------------------------------------------------------

def test_the_throttle_runs_the_whole_state_cycle(fresh):
    """Forward AND reverse AND coast-to-rest, in one drive.

    A test that only walks one way locks that way and ships the other broken,
    so this exercises the entire cycle: ramp up to the cap, coast back to
    EXACTLY zero, ramp the other way to the reverse cap, coast back again. The
    positions are read alongside the speeds, because "the speed variable ramps"
    would be satisfied by a ROM that never moved the world.
    """
    with fresh.frame_stepping():
        # Hug the north wall FIRST. The start corridor runs east-west and gives
        # both throttle directions room, but a slime paces down its centreline
        # — and a contact knockback zeroes the speed, which would break a ramp
        # measurement for a reason that has nothing to do with the throttle.
        # Eight pixels off centre clears the contact box (the rail's own dodge,
        # the one test_the_slide_pins_one_axis proves).
        _turn_to(fresh, NORTH)
        _drive(fresh, 60, stop_when_stuck=10, b=True)
        _rest(fresh)
        _turn_to(fresh, WEST)
        _rest(fresh)
        start = _pos(fresh)

        fwd = _drive(fresh, 40, b=True)
        assert fwd[-1]["speed"] == SPEED_CAP, (
            f"forward never reached the cap: {fwd[-1]['speed']}")
        assert all(fwd[i]["speed"] <= fwd[i + 1]["speed"]
                   for i in range(len(fwd) - 1)), "the ramp is not monotonic"
        west = fwd[-1]["pos"]
        assert west[0] < start[0], f"WEST did not move west: {start} -> {west}"

        coast = _drive(fresh, 60)
        assert coast[-1]["speed"] == 0, (
            f"the coast did not reach rest: {coast[-1]['speed']}")
        rested = coast[-1]["pos"]
        assert _drive(fresh, 10)[-1]["pos"] == rested, (
            "the hero kept moving at speed 0")

        rev = _drive(fresh, 60, y=True)
        assert rev[-1]["speed"] == -SPEED_CAP, (
            f"reverse never reached its cap: {rev[-1]['speed']}")
        assert rev[-1]["pos"][0] > rested[0], (
            f"reverse did not move EAST while facing west: {rested} -> "
            f"{rev[-1]['pos']}")

        back = _drive(fresh, 60)
        assert back[-1]["speed"] == 0, "the reverse coast did not reach rest"


def test_the_forward_clamp_is_unsigned_and_snaps_out_of_reverse(fresh):
    """TRAP 1, REPRODUCED DELIBERATELY — and therefore tested, not left to be
    rediscovered as a bug.

    the reference's forward clamp is an unsigned `cmp #(SPEED_CAP + 1)`, so every
    negative speed compares ABOVE the cap and one forward frame snaps straight
    to +SPEED_CAP instead of ramping through zero. The asymmetry is the whole
    finding: reverse-to-forward is instantaneous, forward-to-reverse ramps.

    This rail whose recorded route was driven against exactly
    this behaviour, so it is kept — and pinned here, so a later "fix" has to be
    a deliberate decision rather than a silent one.
    """
    with fresh.frame_stepping():
        _turn_to(fresh, NORTH)              # wall-hug first, so a knockback
        _drive(fresh, 60, stop_when_stuck=10, b=True)   # cannot zero the speed
        _rest(fresh)
        _turn_to(fresh, WEST)
        _rest(fresh)
        rev = _drive(fresh, 40, y=True)
        assert rev[-1]["speed"] == -SPEED_CAP, "did not reach the reverse cap"

        one = _drive(fresh, 1, b=True)[0]["speed"]
        assert one == SPEED_CAP, (
            f"one forward frame out of full reverse gave {one}; the unsigned "
            f"clamp makes it snap to +{SPEED_CAP}. If this now ramps, the "
            f"clamp was changed — decide that, do not discover it")

        # ...and the other direction genuinely does ramp, which is what makes
        # the asymmetry a finding rather than a misreading of one arm.
        step = _drive(fresh, 1, y=True)[0]["speed"]
        assert 0 < step < SPEED_CAP, (
            f"forward-to-reverse gave {step}: that arm is signed and must ramp")


# --- collision --------------------------------------------------------------

def test_the_hero_is_never_inside_a_wall_at_any_heading(fresh):
    """THE COLLISION INVARIANT, checked EVERY FRAME of every drive.

    The oracle is the generator's geometric `is_wall`, which shares no
    arithmetic with what the ROM does (a packed tile-id read, a flag-table
    index, a mask) — so agreement is evidence, not a restatement.

    Every frame, not the end state: a collision failure is TRANSIENT. The hero
    enters a wall and the next frame's clamp, or a contact knockback, puts it
    somewhere legal again — so an end-of-drive assertion is exactly the shape
    of test that passes while the feature is broken.

    Eight headings, the four compass directions and the four diagonals, because
    a rail that only ever drove north would ship its east-west arm untested.
    """
    with fresh.frame_stepping():
        for h in (NORTH, 32, WEST, 96, SOUTH, 160, EAST, 224):
            _rest(fresh)
            _turn_to(fresh, h)
            for st in _drive(fresh, 90, b=True):
                px, py = st["pos"]
                assert not _inside_wall(px, py), (
                    f"heading {h}: the hero's body at ({px},{py}) overlaps a "
                    f"solid cell — corners "
                    f"{[(c, is_wall(*c)) for c in _footprint_cells(px, py)]}")


def test_a_wall_stops_the_hero_and_the_wall_is_why(fresh):
    """Not merely "the hero stopped" — a hero that never moved would satisfy
    that. The claim is that it stopped AT the wall: it travelled, it came to a
    halt, and the very next pixel along its heading is one the oracle calls
    solid. Both halves, or the test proves nothing about collision.
    """
    with fresh.frame_stepping():
        _turn_to(fresh, NORTH)
        start = _pos(fresh)
        end = _drive(fresh, 120, stop_when_stuck=15, b=True)[-1]["pos"]
        assert end[1] < start[1], f"the hero never moved north: {start}->{end}"
        assert not _inside_wall(*end), "it stopped INSIDE the wall"
        assert _inside_wall(end[0], end[1] - 1), (
            f"the hero halted at {end} but one pixel further north is still "
            f"clear — it stalled for some other reason than the wall")


def test_the_slide_pins_one_axis_and_lets_the_other_run(fresh):
    """THE SLIDE — the behaviour the per-axis test-and-commit exists for, and
    the reason move_y probes at the ALREADY-COMMITTED x.

    Drive north-east up the start corridor, which is walled north and open
    east. A correct rail pins y at the wall and keeps advancing x. A rail that
    tested both axes against the same pre-move position would dead-stop on the
    diagonal instead.

    THE MEASUREMENT IS TAKEN AFTER THE WALL, and that is what makes it a slide
    test rather than a fixed-point-arithmetic test. At a diagonal heading the
    per-axis step is a fraction of a pixel, so frames where y happens not to
    tick while x does are ordinary — a dead-stopping rail produces plenty of
    them on its way to the wall. What only a sliding rail produces is x still
    climbing AFTER y has reached the value the wall pins it at.
    """
    with fresh.frame_stepping():
        _turn_to(fresh, 224)                # north-east
        run = _drive(fresh, 160, b=True)

    pinned_y = run[-1]["pos"][1]
    assert _inside_wall(run[-1]["pos"][0], pinned_y - 1), (
        f"y settled at {pinned_y} but one pixel further north is clear — this "
        f"drive never reached the wall, so it cannot say anything about the "
        f"slide")
    first = next(i for i, s in enumerate(run) if s["pos"][1] == pinned_y)
    after = run[first:]
    assert all(s["pos"][1] == pinned_y for s in after), (
        "the pinned axis moved again after reaching the wall")
    advancing = sum(1 for a, b in zip(after, after[1:])
                    if b["pos"][0] > a["pos"][0])
    assert advancing >= 20, (
        f"once y was pinned at the wall, x advanced on only {advancing} of "
        f"{len(after)} frames — a diagonal into an axis-aligned wall is "
        f"dead-stopping instead of sliding")
    assert after[-1]["pos"][0] - after[0]["pos"][0] >= 40, (
        f"the free axis advanced only "
        f"{after[-1]['pos'][0] - after[0]['pos'][0]} px along the wall — the "
        f"slide is not carrying the hero")


def test_the_speed_cap_cannot_tunnel_a_wall(fresh):
    """The reason the cap is set where it is, asserted rather than trusted.

    Collision steps ONCE per frame, so a hero that could cross more of a wall
    band than one step probes would pass straight through it. Two things are
    checked every frame of a full-speed run into a wall: the per-frame
    displacement never exceeds two pixels (the band is sixteen), and the body
    is never inside a solid cell — which is what tunnelling would look like on
    the far side.
    """
    with fresh.frame_stepping():
        _turn_to(fresh, EAST)
        run = _drive(fresh, 200, b=True)

    assert max(s["speed"] for s in run) == SPEED_CAP, "never reached the cap"
    for i in range(1, len(run)):
        if run[i]["hits"] != run[i - 1]["hits"]:
            continue                        # a knockback IS a teleport to the
                                            # spawn, and a legitimate one — it
                                            # is not a step the collision probe
                                            # was ever asked to cover
        dx = abs(run[i]["pos"][0] - run[i - 1]["pos"][0])
        dy = abs(run[i]["pos"][1] - run[i - 1]["pos"][1])
        assert dx <= 2 and dy <= 2, (
            f"frame {i}: the world moved ({dx},{dy}) px in one step — a step "
            f"larger than the probe's stride can cross a wall between probes")
        assert not _inside_wall(*run[i]["pos"]), (
            f"frame {i}: tunnelled into a wall at {run[i]['pos']}")


# --- the patrol -------------------------------------------------------------

def test_the_enemies_pace_and_never_enter_a_wall(fresh):
    """The cast is held to the SAME wall predicate the hero is — which is the
    claim the shared footprint routine makes. Checked every frame, against the
    same independent oracle, for every enemy.

    Plus the two halves of "pace": each enemy must actually MOVE, and each must
    REVERSE at least once, or an enemy stuck in a corner would satisfy a
    never-in-a-wall test forever.
    """
    with fresh.frame_stepping():
        run = _drive(fresh, 240)

    for i in range(ENEMY_N):
        track = [s["ene"][i] for s in run]
        for x, y in track:
            assert not _inside_wall(x, y), (
                f"enemy {i} stepped its body into a wall at ({x},{y})")
        assert len(set(track)) > 8, f"enemy {i} never paced: {track[:4]}"
        deltas = {(b[0] - a[0], b[1] - a[1])
                  for a, b in zip(track, track[1:])} - {(0, 0)}
        assert len(deltas) >= 2, (
            f"enemy {i} only ever stepped {deltas} — it never turned at a "
            f"wall, so the reverse arm of the patrol is untested")


# --- contact ----------------------------------------------------------------

def _mean_luma(img):
    px = list(img.getdata())
    return sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px) / len(px)


def test_contact_knocks_the_hero_home_and_flashes_the_screen(fresh, tmp_path):
    """The hit, end to end: the counter, the knockback, and the FRAMEBUFFER.

    The flash is the part that needs the screen. A knockback teleports the hero
    to the spawn, which is invisible when he was already near it — so the flash
    IS the feedback, and a test that only read the hits counter would pass on a
    ROM that never dimmed a pixel. Mean luminance across the whole active
    picture, before / at the hit / after the ramp.

    Getting hit takes driving: the spawn tile is a sanctuary, so the hero must
    leave it, and then stand in the corridor the first slime paces.
    """
    with fresh.frame_stepping():
        _turn_to(fresh, EAST)
        # far enough off the spawn to be hittable (the sanctuary is 8 px), not
        # so far that the slime's beat never comes back
        _drive(fresh, 24, b=True)
        _rest(fresh)
        before = _mean_luma(_shot(fresh, tmp_path, "pre_hit"))
        h0 = _u16(fresh, DP_HITS)

        for _ in range(400):
            fresh.frame_step(1)
            if _u16(fresh, DP_HITS) != h0:
                break
        else:
            pytest.fail("no contact in 400 frames — the slime never reached "
                        "the hero, or contact is not firing")

        hit_pos = _pos(fresh)
        # The dim lands on the NEXT frame, not this one: do_contact writes the
        # brightness into fade's ramp state, fade_tick steps it, and the NMI
        # commits INIDISP at the start of the following frame. So sample the
        # few frames after the hit and take the darkest — a fixed offset would
        # be a guess about the commit phase, and the claim is only that the
        # screen visibly drops.
        dark = _mean_luma(_shot(fresh, tmp_path, "at_hit"))
        for k in range(4):
            fresh.frame_step(1)
            dark = min(dark, _mean_luma(_shot(fresh, tmp_path, f"at_hit{k}")))
        assert _u16(fresh, DP_HITS) == h0 + 1, "hits jumped by more than one"
        assert hit_pos == SPAWN, (
            f"the knockback left the hero at {hit_pos}, not the spawn {SPAWN}")
        assert _s16(fresh, DP_SPEED) == 0, "the knockback did not stop the hero"
        assert _u16(fresh, DP_GRACE) > 0, "the grace window was not armed"

        fresh.frame_step(25)                # the ramp is one level a frame
        after = _mean_luma(_shot(fresh, tmp_path, "recovered"))

    assert dark < 0.5 * before, (
        f"the screen did not darken on the hit: {before:.1f} -> {dark:.1f}")
    assert after > 0.8 * before, (
        f"the screen never recovered: {before:.1f} -> {dark:.1f} -> "
        f"{after:.1f} — the fade armed the level but not the ramp")


def test_the_spawn_sanctuary_holds_an_idle_hero(fresh):
    """The gate that keeps a beat over the start from grinding down a hero who
    is standing still — which is where a respawn puts him.

    Sat on the spawn for long enough that the first slime's pace crosses it
    several times, the hits counter must not move. Non-vacuous because the test
    above proves contact fires at all once the hero drives off the tile.
    """
    with fresh.frame_stepping():
        assert _pos(fresh) == SPAWN, "the hero did not start on the spawn"
        h0 = _u16(fresh, DP_HITS)
        run = _drive(fresh, 300)
    assert run[-1]["hits"] == h0, (
        f"an idle hero on the spawn tile took {run[-1]['hits'] - h0} hits")
    approached = min(abs(s["pos"][0] - s["ene"][0][0]) for s in run)
    assert approached < CONTACT_W, (
        f"the first slime never came within the contact width (closest "
        f"{approached} px) — this test never exercised the sanctuary")


# --- pause ------------------------------------------------------------------

def test_pause_freezes_the_world_and_the_cast_but_keeps_drawing(fresh):
    """START freezes the world, and 'frozen' means BIT-IDENTICAL — the hero,
    the heading, every slime, and the committed OAM, across ten frames with the
    throttle held down the whole time. Then it resumes.

    Rendering is asserted separately, because a pause that also stopped the
    frame would satisfy every equality above: the screen must still be a
    picture, not black.
    """
    with fresh.frame_stepping():
        _turn_to(fresh, EAST)
        _drive(fresh, 20, b=True)           # get everything moving first
        _pause_toggle(fresh)
        assert _u16(fresh, DP_PAUSED) == 1, "START did not pause"

        fresh.frame_step(2)                 # let the last shadow commit
        base, base_oam = _state(fresh), _oam(fresh)
        for i in range(10):
            fresh.frame_step(1, b=True)     # holding the throttle the whole way
            assert _state(fresh) == base, (
                f"frame {i} of the pause moved the world: {_state(fresh)} vs "
                f"{base}")
            assert _oam(fresh) == base_oam, (
                f"frame {i} of the pause moved the cast in OAM")

        _pause_toggle(fresh)
        assert _u16(fresh, DP_PAUSED) == 0, "START did not resume"
        after = _drive(fresh, 20, b=True)
    assert after[-1]["pos"] != base["pos"] or after[-1]["ene"] != base["ene"], (
        "nothing moved after the resume — the pause latched permanently")


def test_a_paused_frame_is_still_a_picture(fresh, tmp_path):
    """The other half of the pause claim, from the framebuffer: the world stops
    and the frame does NOT. A pause that blanked the screen would pass every
    state equality in the test above."""
    with fresh.frame_stepping():
        _pause_toggle(fresh)
        fresh.frame_step(3)
        img = _shot(fresh, tmp_path, "paused")
    counts = Counter(_q(img))
    assert len(counts) >= 4, (
        f"the paused frame holds only {len(counts)} colours — the screen went "
        f"blank rather than freezing")


# --- the goal ---------------------------------------------------------------
# The route is a WALL-HUG, and that is the rail's own design rather than a test
# trick: the corridors are 24 px wide, the contact box is 8 px per axis, and a
# hero that slides along a wall sits ~8 px off the corridor centreline the
# slimes pace down. So the drive that reaches the goal is the drive that uses
# the slide — the same behaviour test_the_slide_pins_one_axis proves — and it
# arrives having taken zero hits.
_ROUTE = (NORTH, EAST, SOUTH, EAST, SOUTH)


def _drive_to_goal(runner):
    for h in _ROUTE:
        _rest(runner)
        _turn_to(runner, h)
        _drive(runner, 400, stop_when_stuck=15, b=True)
    return _pos(runner)


def test_the_win_card_is_parked_until_the_hero_stands_on_the_goal(fresh,
                                                                  tmp_path):
    """The win card, from both surfaces, on both sides of the transition.

    OFF the goal: the three slots are PARKED — not merely unwritten, because
    power-on OAM is random and an unwritten slot is a sprite made of garbage —
    and there is no gold anywhere in the banner row.

    ON the goal: the slots hold the win tile with the win palette at the row
    the banner is drawn on, AND the framebuffer actually has gold pixels there.
    Both, because OAM can be perfect while nothing composites.
    """
    with fresh.frame_stepping():
        fresh.frame_step(1)
        oam = _oam(fresh)
        for slot in range(O_WIN, O_WIN + O_WIN_N):
            assert oam[slot * 4 + 1] == PARK_Y, (
                f"OAM slot {slot} is not parked off the goal")
        img = _shot(fresh, tmp_path, "no_win")
        band = [img.getpixel((x, y)) for y in range(20, 60) for x in range(256)]
        assert not any(_is_gold_px(p) for p in band), (
            "gold pixels in the banner row while the hero is at the spawn")

        end = _drive_to_goal(fresh)
        fresh.frame_step(2)
        oam = _oam(fresh)
        img = _shot(fresh, tmp_path, "win")

    assert abs(end[0] - GOAL[0]) < GOAL_HALF and abs(end[1] - GOAL[1]) < GOAL_HALF, (
        f"the route ended at {end}, which is not inside the goal cell {GOAL} "
        f"+/- {GOAL_HALF} — the drive, not the win card, is what failed")

    xs = []
    for slot in range(O_WIN, O_WIN + O_WIN_N):
        x9, x, y, tile, attr = _entry(oam, slot)
        assert (tile, attr) == (WIN_TILE, ATTR_PRIO | PAL_WIN), (
            f"win slot {slot} holds tile {tile} attr ${attr:02X}")
        assert y != PARK_Y, f"win slot {slot} is still parked on the goal"
        xs.append(x)
        px = _patch(img, x + OBJ_HALF, y + 1 + OBJ_HALF, rad=4)
        assert sum(_is_gold_px(p) for p in px) >= 12, (
            f"win slot {slot}'s OAM says ({x},{y}) but the frame holds "
            f"{collections.Counter(px).most_common(3)} there")
    assert len(set(xs)) == O_WIN_N, f"the three stars overlap: {xs}"


def test_the_route_to_the_goal_takes_no_hits(fresh):
    """The rail's own design, asserted: the corridors are wide enough, and the
    contact box narrow enough, that a hero WALL-HUGGING past a slime clears it.

    This is the property the reference's recorded route depends on, and it is a
    consequence of three constants that could each drift independently
    (the corridor width, the footprint, CONTACT_W). If a re-theme narrows a
    corridor or a tuning pass widens the box, the rail stops being completable
    the way it was designed to be — and this says so.
    """
    with fresh.frame_stepping():
        _drive_to_goal(fresh)
        hits = _u16(fresh, DP_HITS)
    assert hits == 0, (
        f"the wall-hug route took {hits} hit(s) — the slide no longer clears "
        f"the slimes, so either the corridors, the footprint or CONTACT_W "
        f"moved")
