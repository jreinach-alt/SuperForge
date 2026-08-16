"""camera_follow — the camera/world-space split, asserted against what was drawn.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)`, which
lands on the ABSOLUTE frame N by construction.

WHAT THIS RAIL IS, and therefore what these cases have to prove. Its source
states its own done-conditions:

    - boots; BG + red sprite visible
    - mid-world: as the player moves, the camera TRACKS (BG scrolls) and the
      sprite stays centred on screen (~128)
    - at the world edge: the camera CLAMPS (stops scrolling) and the sprite
      moves toward the screen edge

Those are the test surface, plus the spec row 4's reason the rail is in
the sweep at all: the CAMERA/WORLD-SPACE SPLIT — the player lives in world
coordinates, the sprite is drawn at world - camera, and which of the two
regimes (track / clamp) is on screen falls out of that subtraction alone.

THE PERIODIC-BACKGROUND TRAP, handled by construction. Every displacement below is
recovered as a PHASE in a window narrower than half the period (span 7), and
every frame count is chosen so the expected TRUE displacement either sits
inside +-7 (the tracking cases) or is claimed as a phase with the absolute
value carried by frame arithmetic and the sprite surface (the transit case,
which states its use of the alias explicitly). "Unchanged" claims bound the
frames so any real motion would be < 16 px and therefore cannot alias to 0.

FRAME ACCOUNTING (scroller's measured convention, re-verified here by the
tracking cases at N = 4): the picture is one commit behind the tick — from a
STANDING start, N held frames put (N - 1) * SPEED px of motion on screen; two
captures inside one CONTINUOUS hold differ by exactly (frames between) *
SPEED. Hardware OAM carries the same one-commit lag, so both surfaces read at
one park describe the same committed frame — and mid-tracking the subtraction
cancels the lag entirely (scrx = pwx - cam is 128 regardless of which tick
was committed), which is why the sprite-centre assertions are exact.

STATE CYCLES, BOTH DIRECTIONS AND IDLE (the repo's own documented smell is a
camera driven one way only): all four axes track AND clamp; an out-and-back
that must restore the frame byte-for-byte; 60 idle frames; opposite
directions held together; and the rail-specific reverse — driving BACK from a
clamped corner, through the boundary where the camera unpins, asserting the
regime handoff lands exactly where the arithmetic says.
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
ROM = BUILD / "camera_follow.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "cf" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="world"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_CHR = _sym("ES_V_CF_CHR")["start"]            # BG CHR page, VRAM words
V_MAP = _sym("ES_V_CF_MAP")["start"]            # BG tilemap base, VRAM words
V_OBJ = _sym("ES_V_CF_OBJ_CHR")["start"]        # OBJ CHR page, VRAM words
C_PAL = _sym("ES_C_CF_PAL")["start"]            # BG palette group 0, CGRAM
C_OBJ = _sym("ES_C_CF_OBJ_PAL")["start"]        # OBJ palette 0, CGRAM words

# --- the rail's geometry (game/camera_follow/cf.inc, re-derived) -------------
MAP_DIM = 32                            # the tilemap: 32x32 cells = 256 px
PERIOD = 16                             # the checkerboard repeats every 16 px
SPEED = 2                               # player px/frame
WORLD_W, WORLD_H = 512, 448             # four screens
CAM_MAX_X, CAM_MAX_Y = WORLD_W - 256, WORLD_H - 224      # 256, 224
PLAYER_MAX_X, PLAYER_MAX_Y = WORLD_W - 8, WORLD_H - 8    # 504, 440
BOOT_WX, BOOT_WY = WORLD_W // 2, WORLD_H // 2            # 256, 224
CENTRE_X, CENTRE_Y = 128, 112           # the follow's half-screen anchor

# --- the picture -------------------------------------------------------------
# Mesen hands back a 256x239 frame; the active 224 scanlines start at PNG row
# 7 (measured for the sibling rails’ two independent ways that agree —
# the spec — and re-verified here by test_boot_frame..., whose sprite with
# OAM Y = 112 must occupy PNG rows 119..126: the OBJ +1 scanline rule plus
# the +6 PNG offset).
PIC_Y0, PIC_H, PIC_W = 7, 224, 256

GREEN = (0, 255, 0)                     # CGRAM word 1 = $03E0
RED = (255, 0, 0)                       # OBJ CGRAM word 129 = $001F
BLACK = (0, 0, 0)                       # word 0: the backdrop

BOOT = 90                               # an absolute frame, well past the fade

# The BG sampling window, PNG coords. Chosen once for the whole module: the
# sprite is pinned to x 128..135 whenever it moves vertically and to PNG rows
# 119..126 whenever it moves horizontally, and the window's cross product
# touches neither band — so no case below ever samples a sprite pixel.
BG_XS = range(20, 100)
BG_YS = range(30, 100)


@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle."""
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make camera_follow` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


# --- helpers -----------------------------------------------------------------

def _pixels(machine, name):
    path = machine.take_screenshot(str(BUILD / "shots" / f"cf_{name}.png"))
    with Image.open(path) as im:
        return list(im.convert("RGB").getdata())


def _at(px, x, y):
    return px[y * PIC_W + x]


def _window(px, xs=BG_XS, ys=BG_YS):
    """The sampled BG window as a tuple — the 'did the world move' surface."""
    return tuple(_at(px, x, y) for y in ys for x in xs)


def _recover_shift(ref, moved, axis, ys=BG_YS, xs=BG_XS, span=7):
    """Every displacement s for which `moved` IS `ref` shifted by s.

    THE SPAN IS 7 BECAUSE THE PATTERN HAS A PERIOD — this is the phase
    recovery the review's scroller lesson demands. An 8 px checkerboard
    repeats every 16 px, so s is only recoverable modulo 16, and +-7 is the
    widest window that can hold at most one member of an alias class. Callers
    keep the expected displacement inside +-7 (or state, as the transit case
    does, that they are asserting the PHASE and carrying the absolute value on
    another surface).

    Positive s means the pattern moved LEFT/UP on screen (the camera advanced
    right/down), because moved(x) == ref(x + s).
    """
    out = []
    for s in range(-span, span + 1):
        if axis == "x":
            ok = all(_at(ref, (x + s) % PIC_W, y) == _at(moved, x, y)
                     for y in ys for x in xs)
        else:
            ok = all(_at(ref, x, (y - PIC_Y0 + s) % PIC_H + PIC_Y0)
                     == _at(moved, x, y)
                     for y in ys for x in xs)
        if ok:
            out.append(s)
    return out


def _red_bbox(px):
    """The sprite as the picture shows it: bbox of every pure-red pixel."""
    pts = [(x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W) if _at(px, x, y) == RED]
    assert pts, "no red pixels — the sprite is not on screen"
    xs_, ys_ = [p[0] for p in pts], [p[1] for p in pts]
    return len(pts), min(xs_), max(xs_), min(ys_), max(ys_)


def _oam_xy(m):
    b = m.read_bytes(O, 0, 2)
    return b[0], b[1]


def _expected_cell(col, row):
    return (col ^ row) & 1


# =============================================================================
# 1. THE UPLOADS — the destination regions, byte for byte
# =============================================================================

def test_bg_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claimed CHR base, against cf_bg_chr.bin — both tiles,
    including the EMPTY one (rule 5: uploaded explicitly, so read the whole
    claim rather than the tile that shows a colour)."""
    want = (ASSETS / "cf_bg_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_CHR * 2, len(want)))
    assert got == want, (
        f"the BG character block at VRAM word ${V_CHR:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_obj_character_block_is_the_destination_of_the_blob(fresh):
    want = (ASSETS / "cf_obj_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_OBJ * 2, len(want)))
    assert got == want, (
        f"the OBJ character block at VRAM word ${V_OBJ:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} bytes differ")


def test_both_palettes_are_the_destinations_of_their_blobs(fresh):
    """CGRAM at both claimed bases — the whole 16 words each, including the
    backdrop word the checkerboard's empty cell renders as."""
    for label, base, blob in (("bg", C_PAL, "cf_bg_pal.bin"),
                              ("obj", C_OBJ, "cf_obj_pal.bin")):
        want = (ASSETS / blob).read_bytes()
        got = bytes(fresh.read_bytes(C, base * 2, len(want)))
        assert got == want, (
            f"{label} palette at CGRAM word {base} is not {blob} — "
            f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")


def test_tilemap_is_the_checkerboard_the_enter_loop_built(fresh):
    """All 1,024 tilemap words in VRAM, each against (col ^ row) & 1. Every
    cell rather than a corner sample: the build loop's whole subtlety is the
    row-boundary `eor`, and an off-by-one there leaves 31 of 32 rows right."""
    raw = bytes(fresh.read_bytes(V, V_MAP * 2, MAP_DIM * MAP_DIM * 2))
    bad = []
    for row in range(MAP_DIM):
        for col in range(MAP_DIM):
            i = (row * MAP_DIM + col) * 2
            word = raw[i] | (raw[i + 1] << 8)
            if word != _expected_cell(col, row):
                bad.append((col, row, word))
    assert not bad, (
        f"{len(bad)} of {MAP_DIM * MAP_DIM} tilemap cells are not "
        f"(col ^ row) & 1; first 8: {bad[:8]}")


# =============================================================================
# 2. THE PICTURE — the composited boot frame
# =============================================================================

def test_boot_frame_is_the_centred_player_over_the_checkerboard(fresh):
    """The boot done-condition on BOTH surfaces at once.

    The player boots at the world centre (256, 224), so the follow puts the
    camera at (128, 112) and the sprite at screen-centre (128, 112) — the
    composited frame must show a green checkerboard, EXACTLY 64 red pixels in
    a solid 8x8 block at (128..135, PNG 119..126), and nothing else. Hardware
    OAM entry 0 must agree. The sprite row check is also what pins PIC_Y0:
    OAM Y = 112 renders at scanline 113 (the OBJ +1 rule), PNG row 119.
    """
    assert _oam_xy(fresh) == (CENTRE_X, CENTRE_Y), (
        "OAM entry 0 is not at the follow's screen centre")
    px = _pixels(fresh, "boot")
    pic = [_at(px, x, y) for y in range(PIC_Y0, PIC_Y0 + PIC_H)
           for x in range(PIC_W)]
    greens = pic.count(GREEN)
    assert greens > PIC_W * PIC_H // 4, (
        f"only {greens} green pixels — the checkerboard is not on screen")
    n, x0, x1, y0, y1 = _red_bbox(px)
    assert n == 64, f"expected a solid 8x8 red sprite, got {n} red pixels"
    assert (x0, x1) == (128, 135), f"sprite x is {x0}..{x1}, not 128..135"
    assert (y0, y1) == (119, 126), f"sprite y is {y0}..{y1}, not 119..126"
    assert greens + n + pic.count(BLACK) == PIC_W * PIC_H, (
        "the picture holds colours other than backdrop, checkerboard, sprite")


def test_world_origin_lands_at_the_top_left_of_the_picture(fresh):
    """Screen (0, 0) shows world (cam_x, cam_y) exactly — the VOFS `dec` buys
    the y half of this and is asserted here rather than trusted from pfs_bg.

    At boot the camera is (128, 112): both congruent 0 mod 16, so the visible
    phase equals the world-origin picture — screen x 0..7 is world cell
    (16, 14), parity 0, BACKDROP; x 8..15 is cell (17, 14), parity 1, GREEN;
    and down column 0 the first cell row is black with green below it. Drop
    the `dec` in cf_bg_nmi_commit and every horizontal boundary moves up one
    pixel; apply the same "fix" to x and the vertical boundaries move too.
    """
    px = _pixels(fresh, "origin")
    for x in range(0, 8):
        assert _at(px, x, PIC_Y0) == BLACK, f"screen (x={x}, y=0) not backdrop"
    for x in range(8, 16):
        assert _at(px, x, PIC_Y0) == GREEN, f"screen (x={x}, y=0) not green"
    for y in range(0, 8):
        assert _at(px, 0, PIC_Y0 + y) == BLACK, f"screen (x=0, y={y}) not backdrop"
    for y in range(8, 16):
        assert _at(px, 0, PIC_Y0 + y) == GREEN, f"screen (x=0, y={y}) not green"


# =============================================================================
# 3. TRACKING — mid-world, the camera moves and the sprite does not
# =============================================================================
# The first done-condition regime, all four axes. From a standing start at
# boot, N = 4 held frames put (N - 1) * SPEED = 6 px of world motion on
# screen — inside the +-7 phase window, so the recovery is single-valued and
# the SIGN is a real claim. The sprite must not move on either surface: the
# subtraction pins scrx/scry at the centre while the camera absorbs the walk.

DIRS = [
    ("right", {"right": True}, "x", +1),
    ("left", {"left": True}, "x", -1),
    ("down", {"down": True}, "y", +1),
    ("up", {"up": True}, "y", -1),
]


@pytest.mark.parametrize("name,pad,axis,sign", DIRS)
def test_midworld_the_camera_tracks_and_the_sprite_holds_centre(boot, name,
                                                                pad, axis,
                                                                sign):
    n = 4
    want = sign * (n - 1) * SPEED
    m = boot()
    ref = _pixels(m, f"trk_ref_{name}")
    oam0 = _oam_xy(m)
    m.advance(n, pad1=pad)
    moved = _pixels(m, f"trk_moved_{name}")
    got = _recover_shift(ref, moved, axis)
    detail = got or "NO displacement reproduces it — the BG did not scroll"
    assert got == [want], (
        f"holding {name} for {n} frames mid-world should displace the drawn "
        f"world by {want} px on {axis}; the picture says {detail}")
    assert _oam_xy(m) == oam0 == (CENTRE_X, CENTRE_Y), (
        f"{name}: the sprite left screen-centre while the camera was tracking")
    n_red, x0, x1, y0, y1 = _red_bbox(moved)
    assert (n_red, x0, x1, y0, y1) == (64, 128, 135, 119, 126), (
        f"{name}: the drawn sprite moved while tracking "
        f"(bbox {x0}..{x1}, {y0}..{y1})")


# =============================================================================
# 4. THE CLAMP — at each world edge the camera stops and the sprite walks out
# =============================================================================
# The second done-condition regime. 160 held frames from boot put 318 px of
# player motion on screen — past every edge, so each drive comes to REST at
# the world boundary with the lag irrelevant: player pinned by the world
# clamp, camera pinned by the follow clamp, sprite at world - camera exactly.

EDGES = [
    # name, pad, resting OAM (x, y), resting red bbox (x0, x1, y0PNG, y1PNG)
    ("right", {"right": True}, (PLAYER_MAX_X - CAM_MAX_X, CENTRE_Y),
     (248, 255, 119, 126)),
    ("left", {"left": True}, (0, CENTRE_Y), (0, 7, 119, 126)),
    ("down", {"down": True}, (CENTRE_X, PLAYER_MAX_Y - CAM_MAX_Y),
     (128, 135, 223, 230)),
    ("up", {"up": True}, (CENTRE_X, 0), (128, 135, 7, 14)),
]


@pytest.mark.parametrize("name,pad,rest_oam,rest_box", EDGES)
def test_at_the_world_edge_the_sprite_rests_at_the_screen_edge(boot, name,
                                                               pad, rest_oam,
                                                               rest_box):
    """Drive to each edge: the sprite must come to rest AT the screen edge
    (right: x 248..255; down: the bbox's last row IS the last active
    scanline) and still show all 64 pixels — 'the sprite moves toward the
    screen edge and stays on screen', both surfaces agreeing."""
    m = boot()
    m.advance(160, pad1=pad)
    assert _oam_xy(m) == rest_oam, (
        f"{name}: OAM rest is {_oam_xy(m)}, expected {rest_oam}")
    px = _pixels(m, f"edge_{name}")
    n_red, x0, x1, y0, y1 = _red_bbox(px)
    assert n_red == 64, f"{name}: {n_red} red px at the edge — sprite clipped?"
    assert (x0, x1, y0, y1) == rest_box, (
        f"{name}: resting bbox ({x0}..{x1}, {y0}..{y1}) != {rest_box}")


@pytest.mark.parametrize("name,pad,axis,sign", DIRS)
def test_in_the_clamped_window_the_world_holds_and_the_sprite_walks(boot,
                                                                    name, pad,
                                                                    axis,
                                                                    sign):
    """THE TEACHING MOMENT: between camera-clamp and player-clamp the BG is
    pixel-frozen while the sprite still walks.

    80 held frames from boot put 158 px of motion on screen — past the
    camera's clamp boundary (+-16 px of margin) on every axis, with the
    player still 80+ px short of the world edge. The second capture then sits
    4 committed steps later (the ref screenshot's own released frame commits
    one, the 4 new held frames commit three more), so the sprite must have
    moved exactly 4 * SPEED = 8 px while the sampled BG window is IDENTICAL —
    and 8 px < the 16 px period, so "identical" cannot be a whole-period
    alias: a camera still tracking would show as a real shift, not equality.

    READ ORDER IS LOAD-BEARING: OAM is read at the park BEFORE each shot,
    because a parked OAM read and the NEXT screenshot describe the same
    committed frame, while an OAM read AFTER a shot is one commit ahead of
    that shot's picture (measured on this ROM: 158/158 vs 160 — the module's
    one surface-lag gotcha, worth this sentence).
    """
    m = boot()
    m.advance(80, pad1=pad)
    ax_ref = _oam_xy(m)[0 if axis == "x" else 1]
    ref = _pixels(m, f"clw_ref_{name}")
    m.advance(4, pad1=pad)
    ax_now = _oam_xy(m)[0 if axis == "x" else 1]
    moved = _pixels(m, f"clw_moved_{name}")
    assert _window(moved) == _window(ref), (
        f"{name}: the BG moved inside the clamped window — the camera is not "
        f"clamped (or 'unchanged' aliased, which these frame counts forbid)")
    assert ax_now - ax_ref == sign * 4 * SPEED, (
        f"{name}: the sprite moved {ax_now - ax_ref} px against the held "
        f"world, expected {sign * 4 * SPEED}")
    # And the drawn sprite agrees with OAM about where it is.
    n_red, x0, _, y0, _ = _red_bbox(moved)
    assert n_red == 64
    assert (x0 if axis == "x" else y0 - PIC_Y0) == ax_now, (
        f"{name}: the drawn sprite disagrees with hardware OAM")


# =============================================================================
# 5. STATE CYCLES — reverse, idle, cancellation, and BACK THROUGH THE CLAMP
# =============================================================================

@pytest.mark.parametrize("name,pad,axis,sign",
                         [DIRS[0], DIRS[2]])       # one per axis: the return
def test_out_and_back_restores_the_frame_exactly(boot, name, pad, axis, sign):
    """20 frames out, 20 back, one released settle frame: the whole frame —
    BG phase AND sprite — must be byte-identical. Phase-proof: both legs
    carry the same commit lag and it cancels."""
    back = {"right": "left", "down": "up"}[name]
    m = boot()
    before = _pixels(m, f"rt_before_{name}")
    m.advance(20, pad1=pad)
    m.advance(20, pad1={back: True})
    m.advance(1)
    after = _pixels(m, f"rt_after_{name}")
    assert after == before, (
        f"20 frames {name} then 20 frames {back} did not restore the frame — "
        f"{sum(a != b for a, b in zip(before, after))} pixels differ")


def test_idle_holds_the_picture_still(boot):
    """The THIRD state: nothing held. 60 frames must change nothing — a
    drifting follow (or an NMI republishing a stale shadow) moves here while
    every driven case still passes."""
    m = boot()
    a = _pixels(m, "idle_a")
    m.advance(60)
    b = _pixels(m, "idle_b")
    assert a == b, (
        f"the picture moved over 60 idle frames — "
        f"{sum(x != y for x, y in zip(a, b))} pixels differ")


def test_opposite_directions_cancel(boot):
    """All four directions held together net to zero: the deltas cancel in
    the PLAYER, so the derived camera and sprite cannot move either."""
    m = boot()
    a = _pixels(m, "cancel_a")
    m.advance(30, pad1={"left": True, "right": True, "up": True, "down": True})
    b = _pixels(m, "cancel_b")
    assert a == b, (
        f"holding all four directions moved the world — "
        f"{sum(x != y for x, y in zip(a, b))} pixels differ")


def test_walking_back_from_the_corner_crosses_the_regime_boundary(boot):
    """THE RAIL-SPECIFIC REVERSE CYCLE: drive to the right edge, then walk
    back — through the exact boundary where the camera unpins.

    Leg 1 (160 R): rest at the corner — OAM (248, 112).
    Leg 2 (61 L, standing start): 120 px of leftward player motion lands the
      player at world x 384 — the boundary where cam_x = pwx - 128 exactly
      re-reaches the clamp value 256. The camera must not have moved (BG
      window identical to the corner) while the sprite walked 248 -> 128.
    Leg 3 (3 more L): the camera is live again — the BG must move by exactly
      -6 px (inside the phase window) while the sprite HOLDS 128. The -6 is
      three committed steps: the boundary screenshot's released frame commits
      the 61st left step (player 382, camera 254 — one px PAST the pin), and
      the new hold contributes two more visible steps.

    A camera whose clamp is sticky (never unpins) fails leg 3; a camera that
    re-tracks too early fails leg 2; no clamp at all already failed leg 1.
    The regime handoff lands on the pixel the arithmetic names, in the
    direction every earlier drive did not exercise.
    """
    m = boot()
    m.advance(160, pad1={"right": True})
    assert _oam_xy(m) == (248, CENTRE_Y), "did not come to rest at the corner"
    corner = _pixels(m, "rev_corner")

    m.advance(61, pad1={"left": True})
    assert _oam_xy(m) == (CENTRE_X, CENTRE_Y), (
        f"after 61 frames back the sprite is at {_oam_xy(m)}, expected the "
        f"regime boundary (128, 112)")
    at_boundary = _pixels(m, "rev_boundary")
    assert _window(at_boundary) == _window(corner), (
        "the BG moved while the sprite was walking home across the clamped "
        "window — the camera unpinned too early")

    m.advance(3, pad1={"left": True})
    past = _pixels(m, "rev_past")
    got = _recover_shift(at_boundary, past, "x")
    assert got == [-6], (
        f"3 more frames left past the boundary should scroll the world -6 px "
        f"(the camera re-tracking); the picture says "
        f"{got or 'NO displacement reproduces it — the clamp is sticky'}")
    assert _oam_xy(m) == (CENTRE_X, CENTRE_Y), (
        "the sprite left centre after the camera resumed tracking")


# =============================================================================
# 6. THE STAGING MECHANISM — the shadow, not hardware OAM
# =============================================================================

def test_the_sprite_is_restaged_every_frame_not_written_once(boot):
    """The OAM SHADOW's write counter — the feature's own output region.

    Hardware OAM is the WRONG surface for this claim: oam_nmi_dma commits the
    whole shadow every armed VBlank whether or not cf_obj_place ran, so its
    write counter climbs identically in both worlds (the scroller port's
    falsification finding, the spec). The shadow byte distinguishes them:
    an idle run must still restage every frame, because the tick calls
    cf_obj_place unconditionally, exactly as the source's per-frame
    spr_clear + spr does.
    """
    shadow = _sym("ES_OAM_SHADOW", scene=None)["start"]
    m = boot()
    before = m.writes(W, shadow)
    m.advance(30)
    after = m.writes(W, shadow)
    assert after - before >= 30, (
        f"the OAM shadow's first byte was written {after - before} times over "
        f"30 frames — the sprite is staged once, not re-staged per frame")


# =============================================================================
# 7. WHY THIS RAIL IS IN THE SWEEP — the spec row 4: the world/screen split
# =============================================================================

def test_the_full_transit_shows_both_spaces_and_both_regimes(boot):
    """One west-to-east walk across the whole world, all three phases of the
    camera/world-space split asserted at exact waypoints on both surfaces.

    From the LEFT REST (player world 0, camera 0, sprite screen 0):

      a) walk-out (30 R): 58 px on screen — the player is still left of the
         follow's centre range, so the camera stays pinned at 0: the BG
         window is IDENTICAL to the rest frame (a camera wrongly tracking
         here would show as phase 10, not as equality), and the sprite
         alone carries the motion: OAM x = 58.
      b) tracking (70 more R, continuous): 99 steps total = 198 px: the
         camera is live at 70. The sprite snaps to EXACTLY screen-centre 128
         (world - camera cancels the lag by construction), and the BG's
         phase against the rest frame is 70 mod 16 = +6 — A PHASE CLAIM,
         stated as such: the absolute 70 rides on the frame arithmetic and
         on the sprite surface, the picture contributes the congruence.
      c) east rest (200 more R): player 504, camera 256, sprite 248 — and
         the BG window returns to BYTE-IDENTITY with the west-rest frame,
         because 256 is a whole number of periods: THE ALIAS the review
         warns about, used deliberately as the closing modular check, with
         the two OAM readings (0 vs 248) proving the two ends are different
         places in the world.

    The player crossed 504 px of world; the sprite crossed 248 px of screen;
    the camera crossed the other 256. That bookkeeping — world = screen +
    camera at every waypoint — is the whole lesson.
    """
    m = boot()
    m.advance(160, pad1={"left": True})          # to the west rest
    assert _oam_xy(m) == (0, CENTRE_Y), "did not come to rest at world x 0"
    west = _pixels(m, "transit_west")

    m.advance(30, pad1={"right": True})          # (a) walk-out
    assert _oam_xy(m) == (58, CENTRE_Y), (
        f"walk-out: OAM {_oam_xy(m)}, expected (58, 112) — 29 committed "
        f"steps at 2 px")
    out = _pixels(m, "transit_out")
    assert _window(out) == _window(west), (
        "the BG moved while the player was still left of the centre range — "
        "the camera unpinned before world x 128")

    m.advance(70, pad1={"right": True})          # (b) tracking
    assert _oam_xy(m) == (CENTRE_X, CENTRE_Y), (
        f"tracking: OAM {_oam_xy(m)}, expected screen-centre (128, 112)")
    track = _pixels(m, "transit_track")
    got = _recover_shift(west, track, "x")
    assert got == [6], (
        f"at player world 198 the camera is 70, phase +6 against the rest "
        f"frame; the picture says {got or 'NO phase matches'}")

    m.advance(200, pad1={"right": True})         # (c) east rest
    assert _oam_xy(m) == (248, CENTRE_Y), (
        f"east rest: OAM {_oam_xy(m)}, expected (248, 112)")
    east = _pixels(m, "transit_east")
    assert _window(east) == _window(west), (
        "after a full 256 px camera transit (16 whole periods) the BG window "
        "should return to byte-identity with the west rest — it did not, so "
        "the camera did not travel a whole number of periods (or moved off "
        "its clamp)")
    n_red, x0, x1, _, _ = _red_bbox(east)
    assert (n_red, x0, x1) == (64, 248, 255)
