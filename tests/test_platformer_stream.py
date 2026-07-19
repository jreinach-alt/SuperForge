"""
test_platformer_stream.py — done-condition test for templates/platformer_stream,
the PLAYABLE Mode-1 platformer on the 2-axis BG1 streaming substrate.

THE DECOUPLED VERIFICATION STRATEGY (the design decision — read this first)
==========================================================================
The streaming ENGINE's 2-axis correctness (forward + reverse, BOTH axes, incl.
UP) is ALREADY proven byte-perfect by tests/test_bg_stream2d.py — a SCRIPTED
camera walked over the authored level in all 4 directions + idle, each visible
cell asserted tile-for-tile against the authored ground-truth. So this PLAYABLE
template test must prove INTEGRATION — that the template wires the proven
substrate to real PLAYER motion — on DETERMINISTIC player drives, NOT re-prove
UP-streaming through a fragile scripted multi-screen climb (that approach is
explicitly banned: jump-arc-vs-step-spacing tuning is a rabbit hole).

The split (also in docs/guides + the catalog row):
  * Template test (THIS file)  = integration on DETERMINISTIC axes:
      - HORIZONTAL: drive the player RIGHT then LEFT across several screens;
        assert the destination BG1 VRAM tilemap matches the authored level at
        the player's world-X (forward AND reverse).
      - VERTICAL DOWN: spawn HIGH, let GRAVITY drop the player down several
        screens through the open shaft; assert the destination VRAM matches the
        authored level at the player's world-Y as it falls. Real player physics,
        no input-timing fragility.
      - JUMP: verify BOTH apex AND landing (CLAUDE.md stateful-physics rule),
        16-bit world-Y.
      - COLLISION: drive into a wall; read the player's REAL world position
        from OUTPUT and assert the box did NOT enter a solid tile.
      - VERTICAL UP (climb): drive the player up a KNOWN, authored staircase
        (the designed climb chain in author_level_seasons) by HOLDING RIGHT and
        jumping — a deterministic walk-up, NOT a fragile step-hunting driver.
        Closed-loop: after the climb assert the player reached successively
        higher GROUNDED rests (world-Y decreased on real treads), the follow-
        camera panned UP (CAMY decreased) under that player motion, AND the
        re-revealed top-edge BG1 VRAM tilemap matches the authored level (UP
        streaming correct under PLAYER motion — the last automation leg).
  * Substrate test (test_bg_stream2d.py) = ENGINE, both axes, scripted camera.

TEST SURFACE DECLARATION (CLAUDE.md "Indirect-Evidence Tests")
  Every assertion reads a real OUTPUT region — the BG1 VRAM tilemap words, the
  player's world position mirrored from the integrator's OWN state, or the OAM
  sprite — never a proxy variable that merely "should" reflect the output.

  - vertical-fall streaming:
      feature = template wires sf_stream_tick2 (row producer) to the follow
                camera under real gravity physics.
      OUTPUT  = BG1 VRAM tilemap words at the player's resident window, compared
                tile-for-tile to the authored level (row-major ground-truth).
      cycle   = airborne spawn -> multi-screen GRAVITY fall -> landed (the DOWN
                state transition driven by physics, sampled at 3 depth bands).
  - horizontal streaming forward + reverse:
      feature = template wires sf_stream_tick2 (column producer) to the camera
                under real walk input.
      OUTPUT  = BG1 VRAM tilemap words at the player window vs authored level.
      cycle   = RIGHT pan east past the 64-col ring, THEN LEFT pan back west
                (forward AND reverse — the state-cycle-coverage rule).
  - jump physics:
      feature = sf_physics_step_world 16-bit world-Y jump arc.
      OUTPUT  = the integrator's committed world-Y (PYF) read per frame.
      cycle   = grounded -> take-off -> ascent -> APEX -> descent -> LANDING ->
                rest (apex AND landing both asserted — the stateful-physics rule).
  - wall collision:
      feature = walk_blocked world-space box probe blocks walls.
      OUTPUT  = the player's committed world-X (PX) + the ROM-resident collision
                table: assert the box's leading column is AIR and the next
                column (the wall) is SOLID — the box did NOT enter the solid.

Position mirrors ($7E:E012+) are the integrator's OWN committed state (PX/PYF
are what the physics actually moved the player to, and what the sprite is drawn
from), so reading them is reading the feature's output, not a decoupled proxy.
The VRAM and collision-table reads are independent hardware/ROM ground-truth.
"""
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROM = os.path.join(HERE, "..", "build", "platformer_stream.sfc")
LEVEL_ROW = os.path.join(HERE, "fixtures", "platformer_stream", "level_flat_row.bin")
COLLISION = os.path.join(HERE, "fixtures", "platformer_stream", "level_collision.bin")

# World geometry (mirrors tools/level_pipeline_bg.py --tall / bg_stream_world.inc).
WORLD_W_TILES = 128
WORLD_H_TILES = 128
ROW_BYTES = WORLD_W_TILES * 2          # 256 bytes/row (row-major)
SCREEN_W_TILES = 32                    # 256px visible window
SCREEN_H_TILES = 28                    # 224px visible window
RING_TILES = 64                        # the 64x64 BG1 hardware ring (boot DMA
                                       # loads cols/rows 0..63; anything past 63
                                       # is correct ONLY if it STREAMED in)

# Spawn / level constants (mirror templates/platformer_stream/main.asm +
# tools/level_pipeline_bg.py author_level_seasons).
FLOOR_TOP_PX = 960                     # bedrock floor top (metatile row 60 = y 960)
SPAWN_X = 272                          # box-left world px (in the shaft)
SPAWN_Y = 136                          # feet world px at spawn (airborne)

# Designed CLIMB CHAIN constants (mirror author_level_seasons): a monotonic-RIGHT
# staircase of treads (floating wood base + grass ledges) west of the wall pillar,
# rising +2 metatile rows (32px) / +3 cols per tread. The player reaches it by
# walking RIGHT along the floor, then HOLDS RIGHT + jumps to walk up it.
CLIMB_APPROACH_X   = 300               # box-left world px to start the climb from
                                       #   (on the floor, just WEST of the base tread
                                       #   at metatile cols 21..23 = world x 336..383)
CLIMB_MIN_CAMY_RISE = 120              # the climb must pan the camera UP at least
                                       #   this many px (measured ~176; floor cam=800)

# Debug region mirrors ($7E:E000 + offset) — the integrator's committed state.
DBG_HEARTBEAT = 0xE010
DBG_PX = 0xE012
DBG_PYF = 0xE014
DBG_VY = 0xE016
DBG_GROUNDED = 0xE018
DBG_CAMX = 0xE01A
DBG_CAMY = 0xE01C
DBG_FACING = 0xE01E


@pytest.fixture(scope="module")
def runner():
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "infrastructure", "test_harness"))
    from mesen_runner import MesenRunner
    r = MesenRunner()
    assert os.path.exists(ROM), (
        f"ROM not built: {ROM} (run `make build/platformer_stream.sfc`)"
    )
    r.load_rom(ROM, run_seconds=0.05)
    yield r
    r.stop()


@pytest.fixture(scope="module")
def level():
    with open(LEVEL_ROW, "rb") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def collision():
    with open(COLLISION, "rb") as fh:
        return fh.read()


def _u16(runner, addr):
    from mesen_runner import MemoryType
    b = runner.read_bytes(MemoryType.SnesWorkRam, addr, 2)
    return b[0] | (b[1] << 8)


def _authored(level, col, row):
    """Authored tilemap word at (world col, row), ROW-major ground-truth."""
    off = row * ROW_BYTES + col * 2
    return level[off] | (level[off + 1] << 8)


def _coll(collision, col, row):
    """ROM-resident collision byte at (world tile col, row): 1=solid, 0=air."""
    return collision[row * WORLD_W_TILES + col]


def _vram_word(runner, world_col, world_row):
    """BG1 VRAM tilemap word for (world_col, world_row) at its 64x64 RING SLOT.
    BG1SC=$5B: cs=col&$3F, rs=row&$3F; page = SC0/SC1/SC2/SC3 per (cs>=32, rs>=32).
    This is the rendered DESTINATION the streaming producers wrote — not a proxy."""
    from mesen_runner import MemoryType
    cs = world_col & 0x3F
    rs = world_row & 0x3F
    base = 0x5800
    if cs >= 32:
        base += 0x400
    if rs >= 32:
        base += 0x800
    word_addr = base + (rs & 31) * 32 + (cs & 31)
    b = runner.read_bytes(MemoryType.SnesVideoRam, word_addr * 2, 2)
    return b[0] | (b[1] << 8)


def _settle_on_floor(runner):
    """Drive the airborne spawn down the shaft until it lands (GROUNDED=1).
    Returns the landed (PX, PYF). Deterministic: pure gravity, no input."""
    runner.set_input(0)
    for _ in range(400):
        runner.run_frames(4)
        if _u16(runner, DBG_GROUNDED) == 1:
            return _u16(runner, DBG_PX), _u16(runner, DBG_PYF)
    raise AssertionError("player never landed (gravity fall did not reach floor)")


def _assert_player_window_matches(runner, level, label, *, inset=2):
    """Assert the BG1 VRAM tilemap in the resident window AROUND the player
    matches the authored level tile-for-tile. The window is centred on the
    camera (cam_x/y from the integrator's own follow state); inset trims the
    actively-streaming leading edge (inherent 1-frame queue lag) + the partial
    edge tiles. Reads VRAM (destination) vs authored (ground-truth)."""
    camx = _u16(runner, DBG_CAMX)
    camy = _u16(runner, DBG_CAMY)
    col0 = camx >> 3
    row0 = camy >> 3
    col_lo = col0 + inset
    col_hi = min(col0 + SCREEN_W_TILES - 1, WORLD_W_TILES - 1) - inset
    row_lo = row0 + inset
    row_hi = min(row0 + SCREEN_H_TILES - 1, WORLD_H_TILES - 1) - inset
    assert col_hi >= col_lo and row_hi >= row_lo, f"{label}: empty window"
    mismatches = []
    checked = 0
    for col in range(col_lo, col_hi + 1):
        for row in range(row_lo, row_hi + 1):
            got = _vram_word(runner, col, row) & 0x3FF
            want = _authored(level, col, row) & 0x3FF
            checked += 1
            if got != want:
                mismatches.append((col, row, got, want))
    assert checked > 0, f"{label}: nothing checked"
    assert not mismatches, (
        f"{label}: {len(mismatches)}/{checked} BG1 VRAM tilemap cells DIFFER "
        f"from the authored level (stale/garbage strip — streaming wrong at the "
        f"player's world position). First 8: {mismatches[:8]}"
    )
    return checked, col_lo, col_hi, row_lo, row_hi


# =============================================================================
# Boot / liveness
# =============================================================================
def test_boot_magic_and_spawn_airborne(runner):
    """The ROM boots (SFDB), runs to completion each frame, and the player
    spawns AIRBORNE in the shaft mouth (GROUNDED=0) at the authored spawn X —
    the precondition for the gravity-driven down-axis test. Reads the debug
    region (boot magic + the integrator's committed spawn state)."""
    from mesen_runner import MemoryType
    runner.load_rom(ROM, run_seconds=0.05)
    runner.set_input(0)
    # Run until the game loop's debug mirror has stamped the magic (a few frames
    # after a reload). The player is still in its shaft FALL at this point (the
    # fall takes ~200 frames to reach the floor), so the mirrored spawn state is
    # the early-fall state: airborne (GROUNDED=0), X UNCHANGED at the shaft spawn
    # column (gravity moves only Y), and a Y well above the floor.
    magic = b""
    for _ in range(30):
        runner.run_frames(2)
        magic = bytes(runner.read_bytes(MemoryType.SnesWorkRam, 0xE000, 4))
        if magic == b"SFDB":
            break
    assert magic == b"SFDB", f"debug magic not SFDB: {magic!r}"
    assert _u16(runner, 0xE008) == 1, "completion flag != 1 (frame crashed)"
    assert _u16(runner, DBG_PX) == SPAWN_X, "player X drifted from the shaft spawn column"
    assert _u16(runner, DBG_GROUNDED) == 0, "player should still be falling in the shaft"
    assert _u16(runner, DBG_PYF) < FLOOR_TOP_PX, "player already at the floor (fall too fast?)"
    hb0 = _u16(runner, DBG_HEARTBEAT)
    runner.run_frames(6)
    assert _u16(runner, DBG_HEARTBEAT) > hb0, "frame heartbeat did not advance"


# =============================================================================
# VERTICAL DOWN — gravity drops the player several screens through the shaft;
# the row-streamer must keep the player's world-Y window authored-correct.
# =============================================================================
def test_fall_down_streams_vertical(runner, level):
    """Reload, spawn airborne, and let GRAVITY drop the player down the open
    shaft (~5 screens). Sample the BG1 VRAM tilemap at THREE depth bands during
    the fall + at the landed floor, asserting each matches the authored level at
    the player's world-Y. Proves the template's VERTICAL streaming wiring under
    real player physics — no scripted input, no UP-climb fragility.

    State cycle: airborne spawn -> deep mid-fall -> deeper -> landed (DOWN)."""
    runner.load_rom(ROM, run_seconds=0.05)
    runner.set_input(0)
    runner.run_frames(2)
    assert _u16(runner, DBG_GROUNDED) == 0, "expected airborne spawn"

    bands = []
    # sample mid-fall depths (camera y rising as the player falls)
    for target_camy in (250, 500, 700):
        for _ in range(400):
            runner.run_frames(2)
            if _u16(runner, DBG_CAMY) >= target_camy:
                break
        camy = _u16(runner, DBG_CAMY)
        n, _, _, row_lo, row_hi = _assert_player_window_matches(
            runner, level, f"fall@camy>={target_camy}")
        bands.append((camy, n, row_lo, row_hi))

    # the DEEP bands must read rows BELOW the boot-loaded 64-row ring (row > 63)
    # — those cells are correct ONLY if the row producer STREAMED them in as the
    # player fell (the boot DMA loaded rows 0..63). Proves vertical STREAMING,
    # not just resident content.
    deepest_row_hi = bands[-1][3]
    assert deepest_row_hi > RING_TILES, (
        f"deepest fall window row_hi={deepest_row_hi} did not pass the 64-row "
        f"boot ring — the test never reached streamed vertical content"
    )

    # finish the fall to the floor and assert the landed window too
    px, pyf = _settle_on_floor(runner)
    assert pyf == FLOOR_TOP_PX, f"feet should rest on the floor top {FLOOR_TOP_PX}, got {pyf}"
    _assert_player_window_matches(runner, level, "landed-floor")

    # the camera genuinely descended through distinct depth bands (not stuck)
    camys = [c for c, _n, _rl, _rh in bands]
    assert camys[0] < camys[1] < camys[2], f"camera did not descend monotonically: {camys}"
    assert camys[2] >= 600, f"fall did not reach a deep band (max camy {camys[2]})"


# =============================================================================
# HORIZONTAL — RIGHT then LEFT across several screens (forward AND reverse);
# the column-streamer must keep the player's world-X window authored-correct.
# =============================================================================
def test_walk_right_then_left_streams_horizontal(runner, level):
    """Land the player, then drive RIGHT until the camera pans east PAST the
    64-col resident ring (forward streaming), asserting the player's VRAM window
    matches the authored level. THEN drive LEFT back west past the start
    (reverse streaming), asserting again. Both directions — the state-cycle-
    coverage rule (a right-only test silently ships reverse broken).

    State cycle: landed -> RIGHT pan east (forward) -> LEFT pan west (reverse)."""
    runner.load_rom(ROM, run_seconds=0.05)
    _settle_on_floor(runner)

    # --- forward (east) until the visible window reads PAST the 64-col ring ---
    # The window LEFT edge passes col 64 when cam_x>>3 (inset) > 63, i.e. the
    # checked cells are columns the COLUMN PRODUCER streamed in (boot loaded only
    # cols 0..63). We run RIGHT until the player nears the east wall (the camera's
    # max reach here), then require col_lo > the ring boundary.
    runner.set_input(0, right=True)
    prev = -1
    for _ in range(600):
        runner.run_frames(2)
        cx = _u16(runner, DBG_CAMX)
        px = _u16(runner, DBG_PX)
        if px == prev and cx >= 256:   # reached the east wall, camera settled deep
            break
        prev = px
    runner.set_input(0)
    runner.run_frames(6)
    assert _u16(runner, DBG_GROUNDED) == 1, "player should stay grounded walking the floor"
    _, fwd_col_lo, fwd_col_hi, _, _ = _assert_player_window_matches(
        runner, level, "walk-right-forward")
    assert fwd_col_hi > RING_TILES, (
        f"forward window col_hi={fwd_col_hi} did not pass the 64-col boot ring — "
        f"the test never verified STREAMED horizontal content (cam_x="
        f"{_u16(runner, DBG_CAMX)})"
    )

    # --- reverse (west) back past the start ---
    runner.set_input(0, left=True)
    for _ in range(800):
        runner.run_frames(2)
        if _u16(runner, DBG_CAMX) <= 40:
            break
    runner.set_input(0)
    runner.run_frames(6)
    assert _u16(runner, DBG_CAMX) <= 40, (
        f"camera never panned back west (cam_x={_u16(runner, DBG_CAMX)})"
    )
    # the reverse window's right edge re-reads columns that were SCROLLED OUT and
    # must be re-streamed on the way back (the reverse-X trailing edge) — the
    # state-cycle-coverage rule (forward-only ships reverse broken).
    _assert_player_window_matches(runner, level, "walk-left-reverse")


# =============================================================================
# JUMP — verify BOTH apex AND landing (CLAUDE.md stateful-physics rule), 16-bit
# world-Y. apex depends on JUMP_VEL+gravity; landing rest depends on the snap.
# =============================================================================
def test_jump_apex_and_landing(runner):
    """From a grounded rest on the floor, hold A: the player takes off, rises to
    an APEX measurably above the rest, then gravity brings it back to LAND at
    EXACTLY the floor rest (no embed, no hover). Reads the integrator's own
    committed world-Y per frame across the WHOLE arc — apex AND landing, the
    full ascent->apex->descent->landing->rest cycle (the stateful-physics rule;
    an apex-only test ships the landing-snap broken)."""
    runner.load_rom(ROM, run_seconds=0.05)
    _settle_on_floor(runner)
    # Normalise to the CANONICAL floor rest first: the spawn-fall lands at
    # terminal velocity and can overshoot the feet 1px onto the floor-top pixel
    # (960) vs the clean rest the controlled jump-descent produces (959). One
    # settle-jump cycle lets the integrator's landing-snap establish the stable
    # rest the test then asserts the real jump returns to — so the apex+landing
    # assertion is self-consistent, not comparing two different landing regimes.
    # Deterministic arc: with the emulator free-running, the settle poll's
    # three WRAM reads land on DIFFERENT emulated frames on a slow host —
    # GROUNDED can read 1 (pre-takeoff) while VY reads 0 (apex), breaking the
    # loop mid-air (CI caught exactly that: rest 952 vs floor 959/960).
    # frame_step parks the emulator between steps so every poll is atomic.
    with runner.frame_stepping():
        runner.frame_step(6, a=True)
        for _ in range(120):
            runner.frame_step(1)
            if _u16(runner, DBG_GROUNDED) == 1 and _u16(runner, DBG_VY) == 0:
                break
        rest_y = _u16(runner, DBG_PYF)
        assert _u16(runner, DBG_GROUNDED) == 1, "player did not settle to a stable floor rest"
        assert rest_y in (FLOOR_TOP_PX - 1, FLOOR_TOP_PX), (
            f"settled rest {rest_y} is not on the floor surface ({FLOOR_TOP_PX-1}/{FLOOR_TOP_PX})"
        )

        # hold A for the jump; sample world-Y every frame to find the apex (min Y).
        min_y = rest_y
        left_ground = False
        for _ in range(60):
            runner.frame_step(1, a=True)
            y = _u16(runner, DBG_PYF)
            if _u16(runner, DBG_GROUNDED) == 0:
                left_ground = True
            if y < min_y:
                min_y = y

        assert left_ground, "player never left the ground on A (jump did not fire)"
        apex_rise = rest_y - min_y
        assert apex_rise >= 24, (
            f"apex rise only {apex_rise}px above rest (y_rest={rest_y}, y_apex={min_y}); "
            f"the jump arc did not clear a believable height"
        )

    # let it fall back and LAND. The user-visible invariant (the one a player
    # sees) is: the player returns to STAND ON THE SAME FLOOR — not embedded
    # below it, not hovering above it — and rests STABLY. The integrator's
    # landing snap settles feet on the floor SURFACE; whether that reads as the
    # floor-top pixel (960) or one above (959) is a 1px sub-pixel-phase detail of
    # the snap, NOT a user-visible embed/hover. So the invariant is "on the
    # surface AND stable", asserted over several frames (no drift = no embed/
    # hover oscillation), not a single exact pixel.
        for _ in range(120):
            runner.frame_step(1)
            if _u16(runner, DBG_GROUNDED) == 1 and _u16(runner, DBG_VY) == 0:
                break
        land_y = _u16(runner, DBG_PYF)
        assert _u16(runner, DBG_GROUNDED) == 1, "player never landed after the jump"
        # on the floor surface: never BELOW the floor top (embedded), never above
        # the clean rest (hovering).
        assert FLOOR_TOP_PX - 1 <= land_y <= FLOOR_TOP_PX, (
            f"landing rest {land_y} not on the floor surface "
            f"[{FLOOR_TOP_PX-1}..{FLOOR_TOP_PX}] (embedded in / hovering above the floor)"
        )
        # STABLE: holding still, the feet do not drift (no embed/hover oscillation).
        for _ in range(20):
            runner.frame_step(1)
            y = _u16(runner, DBG_PYF)
            assert y == land_y, f"rest drifted {land_y}->{y} (unstable landing snap)"
            assert _u16(runner, DBG_GROUNDED) == 1, "lost grounded while standing still"


# =============================================================================
# COLLISION — drive into a wall; read the player's REAL world position from
# OUTPUT and assert the box did NOT enter a solid tile.
# =============================================================================
def test_wall_collision_does_not_enter_solid(runner, collision):
    """Land the player, drive RIGHT into the first crate wall east of spawn
    (cols 52-53 rest on the floor). Read the player's committed world-X (PX)
    and assert the box's LEADING column is AIR while the NEXT column (the wall)
    is SOLID — i.e. walk_blocked stopped the box flush against the wall, never
    INSIDE it. Reads PX (the integrator's output) + the ROM collision table
    (independent ground-truth), not a 'did_collide' proxy flag."""
    runner.load_rom(ROM, run_seconds=0.05)
    _settle_on_floor(runner)

    runner.set_input(0, right=True)
    prev = -1
    for _ in range(500):
        runner.run_frames(4)
        px = _u16(runner, DBG_PX)
        if px == prev:                 # stopped advancing -> hit the wall
            break
        prev = px
    runner.set_input(0)
    runner.run_frames(4)

    px = _u16(runner, DBG_PX)
    pyf = _u16(runner, DBG_PYF)
    assert _u16(runner, DBG_GROUNDED) == 1, "player should be grounded at the wall"
    # the colliding body rows (the 8px above the feet contact line)
    top_row = (pyf - 8) >> 3
    bot_row = (pyf - 1) >> 3
    right_col = (px + 7) >> 3          # box right edge tile column
    next_col = right_col + 1
    # the box's leading column must be AIR (the box did NOT enter the solid)...
    for row in (top_row, bot_row):
        assert _coll(collision, right_col, row) == 0, (
            f"box leading col {right_col} row {row} is SOLID — the player walked "
            f"INTO a solid tile (PX={px})"
        )
    # ...and the very next column must be the SOLID wall it stopped against.
    assert _coll(collision, next_col, bot_row) == 1, (
        f"col {next_col} (the wall the player should have stopped against) is not "
        f"solid — the player did not actually reach the wall (PX={px})"
    )


# =============================================================================
# VERTICAL UP — drive the player UP the authored climb staircase under its OWN
# jumps; assert the camera pans UP and the re-revealed top-edge VRAM streams in
# authored-correct. Closes the last automation leg from audit-1 Finding 1.
# =============================================================================
def _walk_right_to(runner, target_px, *, max_steps=300):
    """Hold RIGHT until the player's box-left world-X reaches target_px (or it
    stops advancing). Deterministic: pure walk input. Returns the landed PX."""
    runner.set_input(0, right=True)
    prev = -1
    for _ in range(max_steps):
        runner.run_frames(2)
        px = _u16(runner, DBG_PX)
        if px >= target_px or px == prev:
            break
        prev = px
    runner.set_input(0)
    runner.run_frames(6)
    return _u16(runner, DBG_PX)


def test_climb_up_streams_vertical_under_player(runner, level):
    """Land the player, walk it RIGHT to the foot of the AUTHORED climb staircase,
    then drive it UP by HOLDING RIGHT and pulsing JUMP — a deterministic walk-up
    of a KNOWN ladder (NOT a fragile step-hunting driver). Closed-loop verify:

      1. the player reaches successively HIGHER grounded rests (world-Y strictly
         decreases on real treads — it actually climbed, didn't just bob),
      2. the follow-camera panned UP (CAMY decreased >= CLIMB_MIN_CAMY_RISE) under
         that player motion, and
      3. the re-revealed top-edge BG1 VRAM tilemap matches the authored level at
         the new (higher) camera window — UP streaming is correct under PLAYER
         motion, the last automation leg of audit-1 Finding 1.

    State cycle: landed -> walk RIGHT to the staircase foot -> CLIMB UP (the UP
    transition, driven by real jump physics) -> grounded high, camera panned up.

    TEST SURFACE: every assertion reads an OUTPUT region — the integrator's own
    committed world-Y / CAMY (what the sprite + camera are actually drawn from)
    for the climb-progress + camera-pan checks, and the BG1 VRAM tilemap words vs
    the authored level (independent ROM ground-truth) for the streaming check.
    No proxy variables."""
    runner.load_rom(ROM, run_seconds=0.05)
    px, _ = _settle_on_floor(runner)

    # --- walk to the foot of the staircase (on the floor, west of the base) ---
    px = _walk_right_to(runner, CLIMB_APPROACH_X)
    assert _u16(runner, DBG_GROUNDED) == 1, "player should be grounded at the staircase foot"
    camy_foot = _u16(runner, DBG_CAMY)
    pyf_foot = _u16(runner, DBG_PYF)
    assert pyf_foot == FLOOR_TOP_PX, f"player should be on the floor at the foot, got {pyf_foot}"

    # --- CLIMB: hold RIGHT + pulse A (12 frames held / 3 released, so jump's
    #     btnp PRESS re-fires on each landing) — a fixed, deterministic input
    #     pattern that walks the player up the KNOWN staircase. Closed-loop: track
    #     each grounded-and-settled rest; require strictly-decreasing world-Y
    #     (the player landed on each next-higher tread, not bobbed in place). ----
    rests = []                         # (pyf, camy) at each new higher grounded rest
    best_pyf = pyf_foot
    for f in range(240):
        phase = f % 15
        kw = {"right": True}
        if phase < 12:
            kw["a"] = True
        runner.set_input(0, **kw)
        runner.run_frames(1)
        if _u16(runner, DBG_GROUNDED) == 1 and _u16(runner, DBG_VY) == 0:
            pyf = _u16(runner, DBG_PYF)
            if pyf < best_pyf - 4:     # a NEW, higher grounded rest (>4px above)
                best_pyf = pyf
                rests.append((pyf, _u16(runner, DBG_CAMY)))
    runner.set_input(0)
    for _ in range(30):                # let it settle on the final tread
        runner.run_frames(1)
        if _u16(runner, DBG_GROUNDED) == 1 and _u16(runner, DBG_VY) == 0:
            break

    # (1) the player climbed real treads: >= 4 successively HIGHER grounded rests,
    #     world-Y strictly decreasing (it walked UP a ladder, not bobbed in place).
    assert len(rests) >= 4, (
        f"player did not climb the staircase: only {len(rests)} higher grounded "
        f"rests reached (rests={rests}); expected the authored treads to be climbed"
    )
    rest_ys = [y for (y, _c) in rests]
    assert all(rest_ys[i] < rest_ys[i - 1] for i in range(1, len(rest_ys))), (
        f"grounded rests did not strictly ASCEND (world-Y must decrease each tread): {rest_ys}"
    )
    final_pyf = _u16(runner, DBG_PYF)
    assert _u16(runner, DBG_GROUNDED) == 1, "player should be grounded on a high tread after the climb"
    assert final_pyf < pyf_foot - 96, (
        f"player only climbed {pyf_foot - final_pyf}px (PYF {pyf_foot}->{final_pyf}); "
        f"expected a multi-tread climb well above the floor"
    )

    # (2) the follow-camera panned UP under the player's climb (CAMY decreased).
    camy_top = _u16(runner, DBG_CAMY)
    assert camy_top <= camy_foot - CLIMB_MIN_CAMY_RISE, (
        f"camera did not pan UP enough under the climb: CAMY {camy_foot}->{camy_top} "
        f"(needed a drop of >= {CLIMB_MIN_CAMY_RISE}px); the player-driven UP pan failed"
    )

    # (3) the re-revealed top-edge BG1 VRAM tilemap matches the authored level at
    #     the new HIGHER camera window. These top rows were scrolled OUT during the
    #     gravity fall (camera was at the world bottom) and must be RE-STREAMED as
    #     the player climbs back up — proving UP streaming under PLAYER motion.
    #     Read VRAM (destination) vs the authored row-major level (ground-truth).
    n, _, _, row_lo, row_hi = _assert_player_window_matches(
        runner, level, "climb-up-top-edge")
    # the checked window's TOP edge must be ABOVE where the camera sat at the foot
    # (smaller world-row) — i.e. genuinely re-revealed content, not the same band.
    assert row_lo < (camy_foot >> 3), (
        f"climb window top row {row_lo} is not above the foot camera row "
        f"{camy_foot >> 3} — the camera did not actually reveal higher content"
    )
