"""jumper — 8.8 jump physics, asserted against what the machine drew and where
it put the sprite.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(90)`, which
lands on the ABSOLUTE frame 90 by construction.

WHAT THIS RAIL IS, and therefore what these cases have to prove. Its source
states its own done-conditions:

    - boots; grey terrain + red player standing on the ground (rest y stable)
    - jump rises ~38px and lands back at EXACTLY the rest y (full cycle)
    - jumping from below onto a platform lands ON it (rest = platform top - 8)
    - walking off a platform edge falls (clamped) and lands below
    - the overhang bonks: y never passes into it, ascent dies early

Those are the test surface, plus the spec row 6's reason the rail is in
the sweep at all: 8.8 PHYSICS — sub-pixel vertical motion on a per-frame
integrator whose whole state cycle (standing, take-off, ascent, head bump,
apex, descent, landing snap, rest) the caller never writes a branch of.

THE ARC IS ASSERTED WHOLE, AGAINST AN INDEPENDENT ORACLE, ON THE OUTPUT
SURFACE. `_sim` re-implements the integrator in Python from the declared
constants (`sf_physics.inc:24-28`) over a world rebuilt from the level's five
terrain loops — shared code with the generator: none. Every driven case traces
hardware OAM per frame and requires the WHOLE trajectory equal — every ascent
step, the apex, every descent step, THE LANDING FRAME, and the rest tail. That
is the repo's apex-only trap (CLAUDE.md: "the landing frame is where the bugs
live, not the apex" — an apex depends only on jump-vel + gravity; the rest
position depends on the terminal clamp and the snap, and a snap off by the box
height embeds the sprite in the floor while every apex assertion passes) closed
by construction: a wrong landing frame is a wrong list element, named by index.

FRAME ACCOUNTING (camera_follow's measured convention, re-verified here by
the boot smoke of this port): OAM read at a park describes the PREVIOUS
tick's commit — advance(1, pad) runs the tick whose WRAM effect is immediate
and whose OAM effect is visible one advance later. So a trace reads: press
advance, then N advances each followed by one OAM read; ys[i] = the pixel the
(i+1)-th tick computed. READ ORDER IS LOAD-BEARING where OAM and a screenshot
describe one frame in one breath: OAM is read BEFORE the shot — a parked OAM
read and the NEXT screenshot describe the same committed frame, while an OAM
read AFTER a shot is one commit ahead of that shot's picture.

STATE CYCLES, BOTH DIRECTIONS AND IDLE: ascent AND descent AND landing AND
rest in one assertion; left AND right border stops; walk-off with the
horizontal axis still live (separated axes); 60 idle frames that must hold
the whole picture byte-still.
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
ROM = BUILD / "jumper.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "jr" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="sky"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_CHR = _sym("ES_V_JR_CHR")["start"]            # BG CHR page, VRAM words
V_MAP = _sym("ES_V_JR_MAP")["start"]            # BG tilemap base, VRAM words
V_OBJ = _sym("ES_V_JR_OBJ_CHR")["start"]        # OBJ CHR page, VRAM words
C_PAL = _sym("ES_C_JR_PAL")["start"]            # BG palette group 0, CGRAM
C_OBJ = _sym("ES_C_JR_OBJ_PAL")["start"]        # OBJ palette 0, CGRAM words
OAM_SHADOW = _sym("ES_OAM_SHADOW", scene=None)["start"]

# --- the rail's geometry, written out here rather than imported --------------
# The level's five terrain loops, restated INDEPENDENTLY of
# tools/gen_jumper_assets.py (shared code: none), so a generator that drifted
# from the declared level breaks the tilemap case loudly.
DIM = 32
TILE_SOLID = 2

def _reference_world():
    solid = set()
    solid |= {(c, 26) for c in range(0, 32)}        # ground
    solid |= {(c, 22) for c in range(8, 13)}        # platform 1 (top 176)
    solid |= {(c, 18) for c in range(15, 20)}       # platform 2 (top 144)
    solid |= {(c, 14) for c in range(22, 27)}       # platform 3 (top 112)
    solid |= {(c, 22) for c in range(28, 31)}       # overhang (bottom 183)
    solid |= {(0, r) for r in range(0, 26)}         # left border
    solid |= {(31, r) for r in range(0, 26)}        # right border
    return solid

WORLD = _reference_world()

# --- the physics oracle: the integrator, re-implemented ----------------------
# Constants from sf_physics.inc:24-28 (the defaults the rail ships with).
GRAV, MAXF, JUMPV = 0x0040, 0x0400, 0x0480
SPEED = 2                                       # horizontal px/frame
SPAWN_X, REST_GROUND = 48, 200
REST_PLAT1 = 168                                # platform 1 top 176 - box 8
BONK_Y = 184                                    # overhang row bottom 183 + 1
PLAT1_X0, PLAT1_X1 = 8 * 8, 12 * 8 + 7          # cols 8..12 -> px 64..103


def _solid_box(x, y):
    """sf_solid_box's four corners against the rebuilt world."""
    return any(((cx >> 3) & 31, (cy >> 3) & 31) in WORLD
               for cx in (x, x + 7) for cy in (y, y + 7))


def _phys(pyf, vy, px):
    """One tick of the vertical integrator (sf_physics_step, solid paths)."""
    if vy < 0:                                  # rising
        vy += GRAV
        tent = pyf + vy
        ny = (tent >> 8) & 0xFF
        if _solid_box(px, ny):                  # head bump: snap below, kill
            return ((ny & ~7) + 8) << 8, 0, 0
        return tent, vy, 0
    cy = (pyf >> 8) & 0xFF                      # falling / standing
    if _solid_box(px, cy + 1):                  # ground 1px below -> stand
        return pyf & 0xFF00, 0, 1
    vy = min(vy + GRAV, MAXF)
    tent = pyf + vy
    ny = (tent >> 8) & 0xFF
    if _solid_box(px, ny):                      # landing snap: bottom -> top
        return ((((ny + 7) & ~0x7) - 8) << 8), 0, 1
    return tent, vy, 0


def _sim(ticks, x0=SPAWN_X, y0=REST_GROUND):
    """The whole trajectory under a per-tick input script.

    `ticks` is a list of (right, left, jump_press) tuples — one per tick, in
    the scene tick's own order (horizontal at the CURRENT pixel y, then the
    edge-gated jump, then the physics step). Returns [(px, pixel_y)] per tick.
    """
    px, pyf, vy, grounded = x0, y0 << 8, 0, 1
    out = []
    for right, left, press in ticks:
        pyi = (pyf >> 8) & 0xFF
        newx = px + (SPEED if right else 0) - (SPEED if left else 0)
        if not _solid_box(newx, pyi):
            px = newx
        if press and grounded:
            vy, grounded = -JUMPV, 0
        pyf, vy, grounded = _phys(pyf, vy, px)
        out.append((px, (pyf >> 8) & 0xFF))
    return out


# --- the picture -------------------------------------------------------------
# Mesen hands back 256x239; the active 224 scanlines start at PNG row 7
#.
PIC_Y0, PIC_H, PIC_W = 7, 224, 256
GREY = (115, 115, 115)                          # $39CE -> BGR555 upscale
RED = (255, 0, 0)                               # $001F
BLACK = (0, 0, 0)
BOOT = 90                                       # absolute frame, past the fade


@pytest.fixture(scope="module")
def boot():
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make jumper` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


# --- helpers -----------------------------------------------------------------

def _pixels(machine, name):
    path = machine.take_screenshot(str(BUILD / "shots" / f"jr_{name}.png"))
    with Image.open(path) as im:
        return list(im.convert("RGB").getdata())


def _at(px, x, y):
    return px[y * PIC_W + x]


def _oam_xy(m):
    b = m.read_bytes(O, 0, 2)
    return b[0], b[1]


def _trace(m, frames, pad):
    """Press-advance, then per-frame OAM (x, y): item i = tick i+1's pixels."""
    m.advance(1, pad1=pad)
    out = []
    for _ in range(frames):
        m.advance(1, pad1=pad)
        out.append(_oam_xy(m))
    return out


# =============================================================================
# 1. THE UPLOADS — the destination regions, byte for byte
# =============================================================================

def test_bg_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claimed CHR base vs jr_bg_chr.bin — all three tiles,
    including the two EMPTY ones (uploaded explicitly, rule 5)."""
    want = (ASSETS / "jr_bg_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_CHR * 2, len(want)))
    assert got == want, (
        f"the BG character block at VRAM word ${V_CHR:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_obj_character_block_is_the_destination_of_the_blob(fresh):
    want = (ASSETS / "jr_obj_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_OBJ * 2, len(want)))
    assert got == want, (
        f"the OBJ character block at VRAM word ${V_OBJ:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_both_palettes_are_the_destinations_of_their_blobs(fresh):
    for label, base, blob in (("bg", C_PAL, "jr_bg_pal.bin"),
                              ("obj", C_OBJ, "jr_obj_pal.bin")):
        want = (ASSETS / blob).read_bytes()
        got = bytes(fresh.read_bytes(C, base * 2, len(want)))
        assert got == want, (
            f"{label} palette at CGRAM word {base} is not {blob} — "
            f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")


def test_the_tilemap_is_the_declared_level_and_matches_the_collision_world(fresh):
    """All 1,024 tilemap words vs the level's five terrain loops, rebuilt
    here independently of the generator. This is the rail's one-source
    property made checkable end to end: the same set that drives the physics
    oracle (and therefore every driven case below) must be what is DRAWN —
    display and collision cannot pass these tests while disagreeing."""
    raw = bytes(fresh.read_bytes(V, V_MAP * 2, DIM * DIM * 2))
    bad = []
    for row in range(DIM):
        for col in range(DIM):
            i = (row * DIM + col) * 2
            word = raw[i] | (raw[i + 1] << 8)
            want = TILE_SOLID if (col, row) in WORLD else 0
            if word != want:
                bad.append((col, row, word, want))
    assert not bad, (
        f"{len(bad)} of {DIM * DIM} tilemap cells disagree with the declared "
        f"terrain loops; first 8 (col, row, got, want): {bad[:8]}")


# =============================================================================
# 2. THE PICTURE — the composited boot frame
# =============================================================================

def test_boot_frame_is_the_player_at_rest_on_the_terrain(fresh):
    """The first done-condition on BOTH surfaces at once, with the read order
    the spec demands (OAM at the park BEFORE the shot — one committed frame).

    The player rests at world (48, 200): EXACTLY 64 red pixels in a solid 8x8
    at PNG (48..55, 207..214), sitting flush ON the ground whose top row is
    PNG 215. The terrain census is EXACT — 102 solid cells x 64 px — and the
    frame holds no colour beyond backdrop, terrain grey and player red.
    """
    assert _oam_xy(fresh) == (SPAWN_X, REST_GROUND), (
        "OAM entry 0 is not the spawn rest position")
    px = _pixels(fresh, "boot")
    pic = [_at(px, x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W)]
    reds = [(x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
            for x in range(PIC_W) if _at(px, x, y) == RED]
    assert len(reds) == 64, f"expected a solid 8x8 red player, got {len(reds)}"
    xs, ys = [p[0] for p in reds], [p[1] for p in reds]
    assert (min(xs), max(xs)) == (48, 55), f"player x {min(xs)}..{max(xs)}"
    assert (min(ys), max(ys)) == (207, 214), (
        f"player y {min(ys)}..{max(ys)} — OAM 200 must render at PNG "
        f"207..214 (the OBJ +1 rule plus the VOFS -1 pin)")
    # the visible solid cells: all 102 (world rows 0..27 are on screen)
    grey_want = len(WORLD) * 64
    greys = pic.count(GREY)
    assert greys == grey_want, (
        f"{greys} grey pixels, expected exactly {grey_want} "
        f"({len(WORLD)} solid cells x 64)")
    assert greys + len(reds) + pic.count(BLACK) == PIC_W * PIC_H, (
        "the picture holds colours other than backdrop, terrain, player")
    # flush ON the ground: the row under the sprite's last row is terrain
    assert all(_at(px, x, 215) == GREY for x in range(48, 56)), (
        "the ground's top row is not directly under the resting player")


def test_world_rows_land_on_screen_rows_exactly(fresh):
    """The VOFS -1 pin, asserted at a terrain edge far from the sprite:
    platform 1's top is world row 176, so PNG row 183 is grey across its span
    and PNG row 182 is backdrop. Drop the -1 and both move one row up."""
    px = _pixels(fresh, "rows")
    for x in range(PLAT1_X0, PLAT1_X1 + 1, 8):
        assert _at(px, x, 182) == BLACK, f"(x={x}, PNG 182) not backdrop"
        assert _at(px, x, 183) == GREY, f"(x={x}, PNG 183) not platform top"


# =============================================================================
# 3. THE JUMP — the whole cycle against the oracle, on hardware OAM
# =============================================================================

def test_jump_full_cycle_matches_the_oracle_every_frame(boot):
    """Hold A from rest: 45 frames of hardware OAM must equal the Python
    integrator FRAME FOR FRAME — every ascent step, apex 161 (a 39 px rise),
    every descent step, the terminal-clamped tail, THE LANDING FRAME snapping
    to EXACTLY 200, and the rest of the trace resting there.

    One list equality carries the whole state cycle: take-off, ascent, apex,
    descent, landing, rest — a wrong landing snap (the apex-only trap's
    hiding place) is a wrong element at the landing index, named by pytest.
    """
    m = boot()
    n = 45
    got = _trace(m, n, {"a": True})
    want = _sim([(0, 0, 1)] + [(0, 0, 0)] * (n - 1))  # press tick, then held
    assert got == want, "the drawn arc diverges from the integrator oracle"
    ys = [y for _, y in got]
    assert min(ys) == 161, f"apex {min(ys)}, want 161 (39 px above rest)"
    assert max(ys) == REST_GROUND, "sank below rest during the cycle (embed)"
    land = next(i for i, y in enumerate(ys) if i > 20 and y == REST_GROUND)
    assert all(y == REST_GROUND for y in ys[land:]), (
        "rest not stable after the landing frame (hover/oscillation)")
    # 8.8 IS the why-here: sub-pixel accumulation makes the pixel steps
    # non-uniform — the ascent's per-frame deltas must span >= 3 distinct
    # magnitudes including a 0 px frame (impossible with integer velocity).
    rise = [ys[i] - ys[i + 1] for i in range(ys.index(161))]
    assert len(set(rise)) >= 3 and 0 in rise, (
        f"ascent deltas {sorted(set(rise))} — not an 8.8 sub-pixel arc")


def test_jump_is_edge_and_grounded_gated(boot):
    """Held A does not re-jump (edge gate) and a mid-air press does nothing
    (grounded gate): release A during the ascent, press it again mid-air —
    the whole trace must STILL equal the single-jump oracle, and the rest
    tail after landing must hold while A is pressed again in mid-air."""
    m = boot()
    m.advance(1, pad1={"a": True})              # tick 1: the only real jump
    got = []
    for i in range(2, 47):                      # ticks 2..46 run; reads p1..p45
        pad = {"a": True} if 12 <= i < 30 else {}   # re-press mid-air
        m.advance(1, pad1=pad)
        got.append(_oam_xy(m))
    # the sim models the SECOND press edge truthfully: tick 12 is a rising
    # edge (A was up at 11) — the grounded gate must make it a no-op mid-air
    want = _sim([(0, 0, 1 if i in (1, 12) else 0) for i in range(1, 46)])
    assert got == want, (
        "a mid-air A press altered the arc — the grounded gate is broken")


# =============================================================================
# 4. THE PLATFORM — landing at exact height, then the walk-off
# =============================================================================

def test_jump_onto_platform_lands_on_its_top_exactly(boot):
    """The reference recipe: left to the border stop (x=8), 12 frames right
    (x=32), then A+right — the arc clears platform 1's left edge and the
    drift carries the box over it. The whole drive is checked against the
    oracle; the touchdown must be the platform rest EXACTLY (top 176 - box 8
    = 168) with the sprite over the platform span; five released settle
    frames must hold it (grounded stability on a PLATFORM, not just the
    ground)."""
    m = boot()
    m.advance(60, pad1={"left": True})
    assert _oam_xy(m) == (8, REST_GROUND), "precondition: left border stop"
    m.advance(12, pad1={"right": True})
    m.advance(2)                    # settle released: a MOVING OAM readout is
                                    # one commit behind WRAM,
                                    # so an oracle seeded from it starts a
                                    # step short; at rest the two agree
    x0, y0 = _oam_xy(m)
    assert y0 == REST_GROUND and 28 <= x0 <= 36, (
        f"precondition: takeoff from ({x0}, {y0}), want (~32, 200)")
    # A+right until TOUCHDOWN — two consecutive reads at the platform rest.
    # A single y == 168 read is the ASCENT passing through that height (the
    # arc crosses it mid-air); only at rest does the value hold. Ride on past
    # touchdown and the box walks off the far edge, so the drive is bounded
    # in EMULATED ticks and cut at the rest signature.
    m.advance(1, pad1={"a": True, "right": True})
    got = []
    for _ in range(60):
        m.advance(1, pad1={"a": True, "right": True})
        got.append(_oam_xy(m))
        if len(got) >= 2 and got[-1][1] == got[-2][1] == REST_PLAT1:
            break
    n = len(got)
    want = _sim([(1, 0, 1)] + [(1, 0, 0)] * (n - 1), x0=x0, y0=y0)
    assert got == want, (
        "the platform-landing drive diverges from the integrator oracle")
    xf, yf = got[-1]
    assert yf == REST_PLAT1, f"touchdown y {yf}, want {REST_PLAT1}"
    assert PLAT1_X0 - 7 <= xf <= PLAT1_X1, f"x {xf} not over platform 1"
    m.advance(5)
    x5, y5 = _oam_xy(m)
    assert y5 == REST_PLAT1, "platform rest did not hold released"


def test_walk_off_the_ledge_falls_clamped_and_lands_below(boot):
    """From platform 1, walk left off the edge: the fall must stay under the
    terminal clamp ON THE DRAWN SURFACE (no per-frame drop over 4 px), land
    at the ground rest EXACTLY, hold it — and the horizontal axis must keep
    running THROUGH the fall (the separated-axes teaching: x steps 2 px left
    every frame of the drop, until the border stop)."""
    m = boot()
    m.advance(60, pad1={"left": True})
    m.advance(12, pad1={"right": True})
    m.advance(1, pad1={"a": True, "right": True})
    prev = None
    for _ in range(60):                          # ride until TOUCHDOWN (two
        m.advance(1, pad1={"a": True, "right": True})
        cur = _oam_xy(m)[1]                      #  consecutive rest reads —
        if prev == cur == REST_PLAT1:            #  one alone is the ascent
            break                                #  crossing this height)
        prev = cur
    m.advance(3)                                 # settle, released
    x0, y0 = _oam_xy(m)
    assert y0 == REST_PLAT1, "precondition: not resting on platform 1"
    n = 70
    got = _trace(m, n, {"left": True})
    want = _sim([(0, 1, 0)] * n, x0=x0, y0=REST_PLAT1)
    assert got == want, (
        "the walk-off drive diverges from the integrator oracle")
    ys = [y for _, y in got]
    assert REST_PLAT1 in ys[:3], "did not start from the platform rest"
    deltas = [b - a for a, b in zip(ys, ys[1:])]
    assert max(deltas) <= 4, (
        f"fall step {max(deltas)} px — past the 4 px/frame terminal clamp")
    assert ys[-1] == REST_GROUND, f"ended at {ys[-1]}, want {REST_GROUND}"
    assert all(y == REST_GROUND for y in ys[-5:]), "ground rest not stable"
    # separated axes, as a statement ABOUT the oracle-verified trace: x kept
    # stepping left through every airborne frame (until the border stop)
    xs = [x for x, _ in got]
    fall = [i for i, y in enumerate(ys) if y not in (REST_PLAT1, REST_GROUND)]
    assert fall, "the trace never left a rest height — no fall happened"
    assert all(xs[i] == max(xs[i - 1] - SPEED, 8) for i in fall if i > 0), (
        "x froze during the fall — the axes are not separated")


# =============================================================================
# 5. THE OVERHANG — the bump kills the ascent, exactly one row below the tile
# =============================================================================

def test_overhang_bonks_the_head_and_the_arc_dies_early(boot):
    """Stand under the overhang (right border stop, x=240) and jump: the
    whole trace must match the oracle; min y must be EXACTLY 184 (the snap to
    the first clear row below the tile at 176..183 — never a pixel inside
    it); the arc must resettle at the ground rest; and the airtime must be
    SHORTER than the free jump's (the ascent died early — the done-condition
    verbatim)."""
    m = boot()
    m.advance(150, pad1={"right": True})
    assert _oam_xy(m) == (240, REST_GROUND), "precondition: right border stop"
    n = 40
    got = _trace(m, n, {"a": True})
    want = _sim([(0, 0, 1)] + [(0, 0, 0)] * (n - 1), x0=240, y0=REST_GROUND)
    assert got == want, "the bonk arc diverges from the integrator oracle"
    ys = [y for _, y in got]
    assert min(ys) == BONK_Y, (
        f"bonk min y {min(ys)}, want exactly {BONK_Y} (snap below the tile)")
    assert all(y >= BONK_Y for y in ys), "y entered the overhang's rows"
    assert ys[-1] == REST_GROUND and all(y == REST_GROUND for y in ys[-5:]), (
        "did not resettle at rest after the bonk")
    air = sum(1 for y in ys if y != REST_GROUND)
    assert air < 30, f"airtime {air} frames — the bump did not cut the arc"


# =============================================================================
# 6. THE HORIZONTAL AXIS — borders both ways, cancellation, idle
# =============================================================================

@pytest.mark.parametrize("name,pad,rest_x", [
    ("left", {"left": True}, 8),
    ("right", {"right": True}, 240),
])
def test_the_side_borders_stop_the_run(boot, name, pad, rest_x):
    """Both directions to their border stop: the box's far corner meets the
    border column and x rests exactly one tile in — while y never leaves the
    ground rest (the horizontal probe runs at the current pixel y)."""
    m = boot()
    got = _trace(m, 130, pad)
    assert got[-1] == (rest_x, REST_GROUND), (
        f"{name} drive rests at {got[-1]}, want ({rest_x}, {REST_GROUND})")
    assert all(y == REST_GROUND for _, y in got), (
        f"{name}: y left the ground during a pure horizontal drive")
    xs = [x for x, _ in got]
    assert all(b == a or b == a + (SPEED if name == "right" else -SPEED)
               for a, b in zip(xs, xs[1:])), (
        f"{name}: x moved by something other than 0 or the run step")


def test_opposite_directions_cancel(boot):
    """Left+Right held together: both deltas apply before the one probe, so
    the net is zero by arithmetic (both deltas are applied, never branched) — the
    player must not move on either surface."""
    m = boot()
    before = _oam_xy(m)
    a = _pixels(m, "cancel_a")
    m.advance(30, pad1={"left": True, "right": True})
    after = _oam_xy(m)
    b = _pixels(m, "cancel_b")
    assert after == before == (SPAWN_X, REST_GROUND)
    assert a == b, (
        f"holding Left+Right moved the picture — "
        f"{sum(x != y for x, y in zip(a, b))} pixels differ")


def test_idle_holds_the_whole_picture_still(boot):
    """The rest state, held: 60 idle frames must change NOTHING — OAM first
    (the read order), then the frame, byte for byte. A drifting integrator
    (grounded flicker, a snap that oscillates, subpixel creep) moves here
    while every driven case still passes."""
    m = boot()
    oam_a = _oam_xy(m)
    a = _pixels(m, "idle_a")
    m.advance(60)
    oam_b = _oam_xy(m)
    b = _pixels(m, "idle_b")
    assert oam_a == oam_b == (SPAWN_X, REST_GROUND), "OAM drifted at rest"
    assert a == b, (
        f"the picture moved over 60 idle frames — "
        f"{sum(x != y for x, y in zip(a, b))} pixels differ")


# =============================================================================
# 7. THE STAGING MECHANISM — the shadow, not hardware OAM
# =============================================================================

def test_the_player_is_restaged_every_frame_not_written_once(boot):
    """The OAM SHADOW's write counter — the feature's own output region.
    Hardware OAM is the wrong surface for this claim: oam_nmi_dma commits the
    whole shadow every armed VBlank whether or not jr_obj_draw ran (the
    scroller port's falsification finding). 30 idle frames must keep
    restaging the entry, exactly as the source's per-frame spr_clear + spr."""
    m = boot()
    before = m.writes(W, OAM_SHADOW)
    m.advance(30)
    after = m.writes(W, OAM_SHADOW)
    assert after - before >= 30, (
        f"the OAM shadow's first byte was written {after - before} times "
        f"over 30 frames — the player is staged once, not per frame")
