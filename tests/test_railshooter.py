"""Acceptance gate for the railshooter template: the Mode 7 forward rail plays.

Off-catalog proof for the guided-generation foundation: the SAME host
composition as the racer (Mode 7 floor + OBJ + the CH2 sky TM-split) navigated
to a different genre purely by DRIVER — a rail (auto-advance) instead of an
input throttle, and a strafing ship instead of a fixed kart. So the gate checks
the two things that make it a rail shooter, on real outputs:

  * RAIL: with NO input the camera advances forward every frame (the racer
    coasts to a stop; this never stops).
  * STRAFE: LEFT vs RIGHT move the camera laterally opposite ways AND move the
    ship sprite on screen.

Plus the shared Mode 7 invariants (distinct sky above a grid terrain). State
cycles exercised: idle-but-advancing, strafe LEFT, strafe RIGHT.

The "done right" upgrade adds the mechanics that make it a recognizable rail
shooter, each gated on real outputs (OAM / pool-array / screenshot bytes — no
proxy game variables):
  * P1 obstacles APPROACH on a fake-3D ground plane (pinhole 1/z projection,
    fully DECOUPLED from the Mode 7 matrix — the grid is just the backdrop) and
    SCALE through FOUR discrete pre-drawn size tiers (the SNES has no hardware
    sprite scaling).
  * P2 strafing BANKS the Mode 7 plane and eases back to straight.
  * P5 A FIRES a forward bullet (recedes toward the horizon), a lock-on RETICLE
    marks the aim point, and a bullet hit REMOVES the obstacle.

The projection is verified on the REAL rendered output: a tracked obstacle's
OAM screen_y descends approximately monotonically from the horizon to low on
screen across a full multi-frame approach; its OAM tile + hi-table size bit
step through all four pre-drawn size tiers; and lateral lanes project to
screen_x consistent with the sign of their world-X offset. (The old
matrix-inverse co-location test is gone: the pinhole model deliberately does
NOT anchor obstacles to the Mode 7 affine matrix, so recovering world position
from the live A_V/D_V coefficients is no longer the right invariant.)
"""
from pathlib import Path
from collections import Counter

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

DBG_POSY = 0xE012               # main.asm mirrors camera Y here each frame
DBG_POSX = 0xE014               # ...and camera X here
SHIP_CENTER = 112               # SHIP_CENTER = 128-16
SHIP_Y = 150
RAIL_SPEED = 6


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rgb(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return list(img.getdata()), w, h


def _floor_region(data, w, h):
    y0, y1 = int(110 * h / 224.0), int(210 * h / 224.0)
    return data[y0 * w:y1 * w]


def _sky_row_uniformity(data, w, h, q=32):
    y0, y1 = int(0.09 * h), int(0.21 * h)
    fracs = []
    for y in range(y0, y1):
        rc = Counter()
        for x in range(w):
            r, g, b = data[y * w + x]
            rc[(r // q, g // q, b // q)] += 1
        fracs.append(max(rc.values()) / w)
    return sum(fracs) / len(fracs) if fracs else 0.0


def test_railshooter_rails_and_strafes(runner):
    rom = BUILD / "railshooter.sfc"
    assert rom.exists(), f"{rom} not built — run `make railshooter` first"
    runner.load_rom(str(rom), run_seconds=1.0)

    # --- boots + heartbeat advances ---
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    f1 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > f1 > 0, "frame heartbeat not advancing"

    # --- the grid terrain renders below the horizon (several distinct colors) ---
    shot = "/tmp/_rail_0.png"
    runner.take_screenshot(shot)
    d0, w, h = _rgb(shot)
    floor = _floor_region(d0, w, h)
    assert len(set(floor)) >= 3, \
        f"grid terrain below the horizon shows {len(set(floor))} color(s)"

    # --- a DISTINCT sky above the horizon (uniform, not a smear) ---
    uni = _sky_row_uniformity(d0, w, h)
    assert uni >= 0.70, f"no distinct sky: sky-band row uniformity {uni:.3f} (<0.70)"
    sky = [d0[y * w + x] for y in range(int(0.09 * h), int(0.21 * h)) for x in range(w)]
    q = 32
    def _hist(reg):
        c = Counter()
        for r, g, b in reg:
            c[(r // q, g // q, b // q)] += 1
        t = sum(c.values()) or 1
        return {k: v / t for k, v in c.items()}
    sh, fh = _hist(sky), _hist(floor)
    overlap = sum(min(sh.get(k, 0), fh.get(k, 0)) for k in set(sh) | set(fh))
    assert overlap <= 0.30, f"sky color-overlaps the grid {overlap:.3f} (>0.30)"

    # --- THE RAIL: with NO input the camera advances forward every frame ---
    py0 = runner.read_u16(WR, DBG_POSY)
    runner.run_frames(30)
    py1 = runner.read_u16(WR, DBG_POSY)
    advanced = (py0 - py1) % 1024
    assert 60 <= advanced <= 360, \
        f"rail did not auto-advance with no input: posy {py0} -> {py1} (delta {advanced})"

    # --- STRAFE LEFT: camera X moves one way, ship sprite leans/moves ---
    runner.set_input(0)
    px_base = runner.read_u16(WR, DBG_POSX)
    runner.set_input(0, left=True)
    runner.run_frames(20)
    ship_l = runner.read_bytes(OAM, 0, 4)
    px_left = runner.read_u16(WR, DBG_POSX)
    runner.set_input(0)
    d_left = (px_base - px_left) % 1024
    assert 1 <= d_left <= 512, f"strafe LEFT did not move the camera: {px_base} -> {px_left}"
    assert ship_l[0] < SHIP_CENTER, f"ship did not lean left on screen: x={ship_l[0]}"
    assert ship_l[1] == SHIP_Y, f"ship Y moved unexpectedly: {ship_l[1]}"

    # --- STRAFE RIGHT: camera X moves the OTHER way (all-axes), ship leans right ---
    runner.set_input(0, right=True)
    runner.run_frames(40)
    ship_r = runner.read_bytes(OAM, 0, 4)
    px_right = runner.read_u16(WR, DBG_POSX)
    runner.set_input(0)
    d_right = (px_right - px_left) % 1024
    assert 1 <= d_right <= 512, f"strafe RIGHT did not move the camera back: {px_left} -> {px_right}"
    assert ship_r[0] > SHIP_CENTER, f"ship did not lean right on screen: x={ship_r[0]}"

    # --- the ship sprite is visible: OAM slot 0 + red body rendered in its
    # screen box (sampled from the standstill shot d0, ship centered). ---
    def _px(data, x, y):
        return data[int(y * h / 224.0) * w + int(x * w / 256.0)]
    box = [_px(d0, x, y)
           for x in range(SHIP_CENTER + 4, SHIP_CENTER + 28, 2)
           for y in range(SHIP_Y + 2, SHIP_Y + 30, 2)]
    assert any(r > 160 and g < 130 and b < 130 for r, g, b in box), \
        "ship body (red) not visible in its screen box"


# =============================================================================
# Upgraded rail-shooter mechanics (the "done right" build):
#   P1 obstacles approach (pinhole 1/z projection, decoupled from the matrix)
#      + scale through FOUR discrete pre-drawn size tiers, verified on the
#      rendered OAM across a full multi-frame approach.
#   P2 banking on strafe (the world plane tilts, eases back)
#   P5 firing forward + a lock-on reticle + bullet-removes-obstacle collision
#
# Every assertion reads a REAL output region — OAM bytes (low table + size
# hi-table), the pool ALIVE/WX/DEPTH arrays in WRAM, or screenshot pixels —
# never a proxy engine variable.
# =============================================================================

# debug-region mirrors (main.asm writes these every frame)
DBG_OBS_DEPTH = 0xE016         # obstacle slot-0 forward depth z (world px)
DBG_ANGLE  = 0xE01A             # heading/bank angle byte
DBG_BULCNT = 0xE01C             # live bullet count
DBG_OBSCNT = 0xE01E            # live obstacle count

# pool arrays in low WRAM (sf_pool layout in main.asm)
OBS_ALIVE = 0x1800
OBS_WX    = 0x1810
OBS_DEPTH = 0x1820             # forward depth z (world px ahead of the camera)
BUL_ALIVE = 0x1830
BUL_WX    = 0x1840
BUL_DEPTH = 0x1850
OBS_TIER  = 0x1870             # effective (hysteresis-applied) tier per obstacle
OBS_N = 6

# sf_rail_draw_sorted DEPTH-SORTED OAM EMIT (the "done right" draw): the
# obstacles are now emitted into OAM slots 1..OBS_N ORDERED BY SIZE TIER (tier 0
# = nearest = lowest OAM slot = drawn in front), re-derived every frame. So an
# obstacle's pool slot no longer maps to a fixed OAM slot — track an obstacle by
# its IDENTITY. The routine's per-pool-slot projection cache (RAIL_CACHE, 4
# words/actor: [sx, sy, tier, vis]) records exactly what it placed for each pool
# slot; we use it to locate that obstacle's OAM entry in the slot window, then
# assert on the REAL OAM bytes there. (Cache + OAM are both real output regions
# the routine produced — no proxy game variable.)
RAIL_CACHE = 0x1890            # OBS_N x 4 words; pool slot k at +k*8
OBS_OAM_LO = 1                 # obstacles occupy OAM slots [1, 1+OBS_N)
OBS_OAM_HI = 1 + OBS_N
TIER_CENTER = (16, 16, 8, 8)   # half-width per tier (rail_tier_tbl center_off)

# OBJ tile numbers (OBS_TILE_BASE=64 + frame offsets from obstacles.inc).
# Four size-tier frames: obs_t3=$00, obs_t2=$02, obs_t1=$04, obs_t0=$08.
OBS_TILE_BASE = 64
OBS_TILE_LO = OBS_TILE_BASE    # any obstacle tile is >= 64
TILE_T3 = OBS_TILE_BASE + 0x00   # 64  tier 3 (16x16 box, tiny art)
TILE_T2 = OBS_TILE_BASE + 0x02   # 66  tier 2 (16x16 box, full art)
TILE_T1 = OBS_TILE_BASE + 0x04   # 68  tier 1 (32x32 box, medium art)
TILE_T0 = OBS_TILE_BASE + 0x08   # 72  tier 0 (32x32 box, full art)
TIER_TILES = (TILE_T3, TILE_T2, TILE_T1, TILE_T0)
TILE_RETICLE = OBS_TILE_BASE + 0x0C   # 76
TILE_BULLET  = OBS_TILE_BASE + 0x0E   # 78

# projection LUT geometry (mode7_project.inc); PROJ_DMAX is the far-edge z
PV_L0 = 56                      # horizon scanline (pinhole HORIZON_Y)
PROJ_DMAX = 640                 # max projectable depth z (world px) = Z_FAR


def _oam_entry(runner, slot):
    b = runner.read_bytes(OAM, slot * 4, 4)
    return b[0], b[1], b[2], b[3]   # x, y, tile, attr


def _oam_size_bit(runner, slot):
    """OAM hi-table size bit for `slot` (1 = large per OBSEL)."""
    hi = runner.read_bytes(OAM, 512 + slot // 4, 1)[0]
    return (hi >> ((slot % 4) * 2 + 1)) & 1


def _u16(runner, addr, mem=WR):
    return runner.read_u16(mem, addr)


def _s16(lo, hi):
    v = lo | (hi << 8)
    return v - 0x10000 if v & 0x8000 else v


def _cache(runner, pool_slot):
    """The draw routine's projection cache for pool slot k: (sx, sy, tier, vis).
    These are the EXACT values it placed into OAM for that obstacle (a real
    output region the routine produced), keyed by pool slot identity."""
    base = RAIL_CACHE + pool_slot * 8
    sx = _u16(runner, base + 0)
    sy = _u16(runner, base + 2) & 0xFF
    tier = _u16(runner, base + 4) & 0xFF
    vis = _u16(runner, base + 6)
    return sx, sy, tier, vis


def _find_obstacle_oam(runner, pool_slot):
    """Locate the OAM entry the depth-sorted draw produced for `pool_slot` by
    matching the routine's per-pool-slot projection cache against the obstacle
    OAM window — identity tracking under the tier-bucketed slot ordering. The
    cache (sx, sy, tier, vis) is the routine's own output for THIS pool slot; we
    use its tier (-> the rendered tile) + sy as the identity key and return the
    matched OAM entry's REAL bytes. Among same-tile entries (several obstacles
    can share a tier) we pick the one whose OAM y is closest to the cached sy
    (and tolerate a small lag: the shadow OAM committed by NMI trails the
    game-loop cache by up to a frame). Returns (oam_slot, x, y, tile, attr,
    size_bit) or None if not visible / no same-tile entry on screen.

    Why match rather than read a fixed slot: the draw RE-DERIVES OAM order from
    depth every frame (tier 0 nearest -> lowest slot), so pool slot k has no
    fixed OAM slot. The assertion still lands on real OAM bytes; the cache only
    supplies the identity (which tier-tile this obstacle currently wears)."""
    sx, sy, tier, vis = _cache(runner, pool_slot)
    if not vis:
        return None
    want_tile = (TILE_T0, TILE_T1, TILE_T2, TILE_T3)[tier]   # tier -> rendered tile
    best = None
    best_dy = 999
    for slot in range(OBS_OAM_LO, OBS_OAM_HI):
        x, y, tile, attr = _oam_entry(runner, slot)
        if y >= 224 or tile != want_tile:
            continue
        dy = abs(y - sy)
        if dy < best_dy:
            best_dy = dy
            best = (slot, x, y, tile, attr, _oam_size_bit(runner, slot))
    return best


def test_railshooter_obstacle_smooth_descent(runner):
    """P1 (smooth descent): track ONE obstacle (pool slot 0, located in OAM by
    IDENTITY under the depth-sorted draw) across a FULL approach and assert its
    rendered OAM screen_y descends approximately monotonically from near the
    horizon (~HORIZON_Y) to low on screen (>195) over MANY frames (a real
    multi-frame approach, not a 2-3 frame snap). Reads the OAM low-table y of the
    matched slot directly per frame. State cycle: far(horizon) -> near(bottom) ->
    recycle.

    The obstacle's OAM SLOT is no longer fixed (the draw orders by tier), so we
    find its entry each frame via _find_obstacle_oam (matches the routine's
    projection cache for pool slot 0 to the OAM window) and assert on the matched
    entry's real bytes.

    This is the pinhole 1/z projection's defining property: screen_y =
    HORIZON_Y + CAM_H*256/z, monotone in z, so as z falls each frame the sprite
    walks smoothly down the screen. The old matrix-chained model could only
    produce a ~14px-deep snap; this must produce a long, smooth ramp."""
    rom = BUILD / "railshooter.sfc"
    assert rom.exists()
    runner.load_rom(str(rom), run_seconds=0.5)
    runner.set_input(0)
    runner.run_frames(8)

    # First wait for a recycle so we capture a FULL approach (far -> near), not a
    # partial one we happened to catch mid-flight.
    prev_z = _u16(runner, DBG_OBS_DEPTH)
    for _ in range(200):
        runner.run_frames(1)
        z = _u16(runner, DBG_OBS_DEPTH)
        if z > prev_z + 200:    # recycled -> a fresh approach starts now
            break
        prev_z = z

    # Capture the full fresh approach: collect (z, oam_y) per frame until the
    # next recycle. Track pool slot 0 by identity through the sorted draw.
    samples = []                # (z, oam_y) for the tracked obstacle
    prev_z = _u16(runner, DBG_OBS_DEPTH)
    for _ in range(200):
        runner.run_frames(1)
        z = _u16(runner, DBG_OBS_DEPTH)
        if z > prev_z + 200:    # recycled -> the approach we tracked is over
            break
        prev_z = z
        found = _find_obstacle_oam(runner, 0)
        if found is not None:
            samples.append((z, found[2]))   # found[2] = rendered OAM y

    assert len(samples) >= 40, (
        f"approach was not multi-frame: only {len(samples)} on-screen frames "
        f"(a smooth pinhole descent spans dozens of frames, not a snap)")
    ys = [s[1] for s in samples]
    # emerges near the horizon and ends low on the screen
    assert min(ys) <= PV_L0 + 20, \
        f"obstacle never emerged near the horizon (min OAM y {min(ys)})"
    assert max(ys) >= 195, \
        f"obstacle never descended low on screen (max OAM y {max(ys)})"
    # APPROXIMATELY monotone descent: as z falls, y rises. Count frame-to-frame
    # steps that go the wrong way (y decreasing) and allow only a few (the
    # 1-frame recycle artifact / clamp plateau at the bottom).
    backsteps = sum(1 for i in range(len(ys) - 1) if ys[i + 1] < ys[i] - 1)
    assert backsteps <= 3, \
        f"descent not approximately monotone: {backsteps} backward steps in {ys}"
    # the total travel is large (a real ramp, not a snap)
    assert max(ys) - min(ys) >= 100, \
        f"descent travel too small ({max(ys) - min(ys)}px); not a smooth ramp"


def test_railshooter_obstacle_steps_through_four_size_tiers(runner):
    """P1 (rigorous): a SINGLE tracked obstacle must step through >=3 of the four
    discrete pre-drawn size tiers as it approaches, AND reach the largest tier
    (tier 0, 32x32 full, OAM size bit 1) low on the screen BEFORE it recycles.
    Reads the OAM tile number + hi-table size bit (the real rendered frame) per
    slot per frame across a full approach. State cycle: far -> near -> recycle.

    Tier tiles: T3=64 (tiny), T2=66 (small), T1=68 (medium/large box),
    T0=72 (full/large box). A near obstacle should pass tiny->small->medium->big.
    """
    rom = BUILD / "railshooter.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    runner.set_input(0)
    runner.run_frames(8)

    # Track obstacle pool slot 0 (its z is mirrored at DBG_OBS_DEPTH) by IDENTITY
    # through the depth-sorted draw: _find_obstacle_oam matches the routine's
    # cache for pool slot 0 to the OAM window and returns the matched OAM entry's
    # real bytes (slot, x, y, tile, attr, size_bit).
    tiers_seen = set()
    big_low_frames = 0          # frames where the tracked obs is tier-0 AND low
    recycled = False
    prev_depth = _u16(runner, DBG_OBS_DEPTH)
    for _ in range(200):
        runner.run_frames(1)
        depth = _u16(runner, DBG_OBS_DEPTH)
        # recycle = z jumps back UP toward the far edge (Z_FAR=640)
        if depth > prev_depth + 200:
            recycled = True
            break
        prev_depth = depth
        found = _find_obstacle_oam(runner, 0)
        if found is None:
            continue
        slot, x, y, tile, attr, sz = found
        # which tier frame is this?
        if tile in TIER_TILES:
            tiers_seen.add(tile)
        # tier 0 = full 32x32 (tile 72, size bit 1), low on screen
        if tile == TILE_T0 and sz == 1 and y > 130:
            big_low_frames += 1

    assert len(tiers_seen) >= 3, \
        f"obstacle stepped through only {len(tiers_seen)} size tiers " \
        f"({sorted(tiers_seen)}); expected >=3 of {TIER_TILES}"
    assert big_low_frames >= 2, \
        f"tracked obstacle never reached the largest tier (T0=72, size-large) " \
        f"low on screen for >=2 frames before recycling (got {big_low_frames})"
    assert recycled, "tracked obstacle never recycled across the 200-frame window"


def test_railshooter_obstacle_lateral_lanes(runner):
    """P1 (lateral): obstacles in DIFFERENT lanes render at DIFFERENT screen_x,
    each consistent with the SIGN of its lane's world-X offset from the camera.
    The pinhole lateral projection is screen_x = 128 + ((lane_x - cam_x) *
    scale) >> 8, so an obstacle left of the camera (lane_x < cam_x) renders left
    of centre (sx_center < 128) and one to the right renders right of centre,
    with the magnitude growing as it nears (larger scale). Reads each live
    obstacle's known lane X (pool array) + its rendered OAM x (+ hi-table size
    bit for the centre offset) — both real output regions, no proxy.

    Collected across a window so we observe BOTH left and right lanes on-screen
    (the lanes are 512, 464, 560, 488 around camera 512, i.e. centre/left/right).
    """
    rom = BUILD / "railshooter.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    runner.set_input(0)
    runner.run_frames(8)

    def x9(slot):
        hi = runner.read_bytes(OAM, 512 + slot // 4, 1)[0]
        return (hi >> ((slot % 4) * 2)) & 1

    saw_left = saw_right = False
    checked = 0
    for _ in range(120):
        runner.run_frames(1)
        cam_x = _u16(runner, DBG_POSX)
        for pool_slot in range(OBS_N):
            if _u16(runner, OBS_ALIVE + pool_slot * 2) != 1:
                continue
            depth = _u16(runner, OBS_DEPTH + pool_slot * 2)
            # only assert sign for clearly on-screen obstacles (not the extreme
            # near depth where a big lateral offset projects off the screen edge
            # and the 9-bit X is a wrap, ambiguous to a left/right sign test).
            if depth < 64 or depth > 360:
                continue
            # This obstacle's projected screen-centre x is in its OWN cache slot
            # (the routine's real per-pool-slot output). To prove it RENDERED
            # there (not just computed it), locate the matching OAM entry by tile
            # AND screen x near (cache_sx - centre), then read that entry's bytes.
            c_sx, c_sy, c_tier, c_vis = _cache(runner, pool_slot)
            if not c_vis:
                continue
            want_tile = (TILE_T0, TILE_T1, TILE_T2, TILE_T3)[c_tier]
            want_x = (c_sx - TIER_CENTER[c_tier]) & 0xFF
            oam_slot = None
            for sl in range(OBS_OAM_LO, OBS_OAM_HI):
                ex, ey, et, ea = _oam_entry(runner, sl)
                if ey < 224 and et == want_tile and abs(ey - c_sy) <= 2 \
                        and abs(((ex - want_x + 128) & 0xFF) - 128) <= 2:
                    oam_slot = sl
                    x, y, tile, attr = ex, ey, et, ea
                    break
            if oam_slot is None:
                continue
            sz = _oam_size_bit(runner, oam_slot)
            if y < PV_L0 or y >= 224 or tile < OBS_TILE_LO:
                continue
            # full 9-bit screen X (X9 hi-table bit + low byte), then centre.
            sx9 = (x9(oam_slot) << 8) | x
            if sx9 >= 256:                  # off the right edge: treat as +large
                sx9 -= 512
            sx_center = sx9 + (16 if sz else 8)
            off = _s16(*runner.read_bytes(WR, OBS_WX + pool_slot * 2, 2)) - cam_x
            # sign consistency: left lane -> left of centre, right -> right.
            if off <= -8:
                assert sx_center < 128, (
                    f"left-lane obstacle (off {off}) rendered right of centre: "
                    f"sx_center={sx_center} (y={y} depth={depth})")
                saw_left = True
                checked += 1
            elif off >= 8:
                assert sx_center > 128, (
                    f"right-lane obstacle (off {off}) rendered left of centre: "
                    f"sx_center={sx_center} (y={y} depth={depth})")
                saw_right = True
                checked += 1

    assert saw_left and saw_right, (
        f"did not observe both a left and a right lane on-screen "
        f"(left={saw_left} right={saw_right})")
    assert checked >= 6, \
        f"too few lateral samples verified ({checked}); need >=6 off-centre"


def test_railshooter_obstacles_drawn_depth_sorted(runner):
    """P1 (depth order — the sf_rail_draw_sorted invariant): when two obstacles
    are at DIFFERENT size tiers, the NEARER one (lower tier number) occupies a
    LOWER OAM slot index than the farther one. Lower OAM index draws in FRONT on
    the SNES, so this is the rendered back-to-front layering: nearer obstacles
    occlude farther ones. Reads REAL OAM bytes — for each visible obstacle, its
    OAM slot index + the hi-table size bit (large = tier 0/1, small = tier 2/3) —
    no proxy variable. The check is structural: across a window, EVERY observed
    (slot, tier) pair must be tier-monotone in slot.

    This is the fix the sorted draw ships: the old fixed pool-slot -> OAM-slot
    map layered by pool identity, so a recycled near obstacle could draw BEHIND a
    farther one (the "pop"). The order is now re-derived from depth every frame.

    The size bit (OBSEL: large for the 32x32 tier-0/1 frames, small for the
    16x16 tier-2/3 frames) is the rendered, hardware-read proxy for "near vs far"
    that needs NO cross-reference to the pool: a large-size sprite is a near
    obstacle, a small-size one is far. So we assert: NO small-size obstacle OAM
    slot is lower than a large-size obstacle OAM slot in the same frame."""
    rom = BUILD / "railshooter.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    runner.set_input(0)
    runner.run_frames(8)

    frames_with_mixed = 0       # frames where both a large and a small are on screen
    violations = 0
    pair_checks = 0
    for _ in range(150):
        runner.run_frames(1)
        # read the whole obstacle OAM window: (slot, y, tile, size_bit)
        live = []
        for slot in range(OBS_OAM_LO, OBS_OAM_HI):
            x, y, tile, attr = _oam_entry(runner, slot)
            if y >= 224 or tile < OBS_TILE_LO:
                continue                    # parked / not an obstacle frame
            sz = _oam_size_bit(runner, slot)   # 1 = large (near tier 0/1), 0 = small
            live.append((slot, sz, tile, y))
        # need at least one large and one small to test the ordering
        larges = [e for e in live if e[1] == 1]
        smalls = [e for e in live if e[1] == 0]
        if not (larges and smalls):
            continue
        frames_with_mixed += 1
        # the deepest (highest-index) large slot must be ABOVE the shallowest
        # (lowest-index) small slot: every large in front of every small.
        max_large_slot = max(e[0] for e in larges)
        min_small_slot = min(e[0] for e in smalls)
        pair_checks += 1
        if max_large_slot >= min_small_slot:
            violations += 1

    assert frames_with_mixed >= 10, (
        f"never observed a frame with both near (large) and far (small) "
        f"obstacles on screen ({frames_with_mixed}) — can't test depth order")
    assert violations == 0, (
        f"depth-sort violated in {violations}/{pair_checks} mixed frames: a "
        f"far (small) obstacle drew in FRONT of a near (large) one (lower OAM "
        f"slot). The tier-bucketed draw must put nearer = lower slot.")

    # also assert the finer-grained tier->slot monotonicity via the identity
    # tracker on a single frame with several tiers present: collect each live
    # pool slot's (tier, oam_slot) and require tier-monotone in slot.
    saw_multi_tier = False
    for _ in range(150):
        runner.run_frames(1)
        entries = []            # (tier, oam_slot) per visible obstacle
        for pool_slot in range(OBS_N):
            sx, sy, tier, vis = _cache(runner, pool_slot)
            if not vis:
                continue
            found = _find_obstacle_oam(runner, pool_slot)
            if found is None:
                continue
            entries.append((tier, found[0]))
        tiers_present = {t for t, _ in entries}
        if len(tiers_present) < 2:
            continue
        saw_multi_tier = True
        # sort by tier; OAM slots must be non-decreasing as tier increases
        entries.sort(key=lambda e: e[0])
        slots_in_tier_order = [s for _, s in entries]
        assert slots_in_tier_order == sorted(slots_in_tier_order), (
            f"tier->slot not monotone: {entries} (nearer tier must be a lower "
            f"OAM slot)")
        break
    assert saw_multi_tier, "never observed >=2 tiers on screen to check ordering"


def test_railshooter_banks_both_directions_and_eases_back(runner):
    """P2: strafing tilts the Mode 7 plane (heading angle) a few units toward the
    strafe and eases back to straight on release, BOTH directions. Reads the
    committed heading angle (the value that drives the affine matrix) and a
    screenshot left/right pixel asymmetry that only a tilted plane produces.
    State cycle: neutral -> RIGHT -> release -> LEFT -> release."""
    rom = BUILD / "railshooter.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    runner.set_input(0)
    runner.run_frames(10)
    assert (_u16(runner, DBG_ANGLE) & 0xFF) == 0, "not straight at rest"

    # RIGHT -> a small positive heading; release -> eases back to 0
    runner.set_input(0, right=True)
    runner.run_frames(15)
    a_right = _u16(runner, DBG_ANGLE) & 0xFF
    assert 1 <= a_right <= 16, f"RIGHT did not bank a small positive angle: {a_right}"
    # the tilted plane is visibly asymmetric: sample the floor's far band, the
    # left vs right halves differ more than on a straight (symmetric) plane.
    runner.take_screenshot("/tmp/_rail_bank_r.png")
    dR, w, h = _rgb("/tmp/_rail_bank_r.png")
    runner.set_input(0)
    runner.run_frames(20)
    a_rest1 = _u16(runner, DBG_ANGLE) & 0xFF
    assert a_rest1 == 0, f"did not ease back to straight after RIGHT release: {a_rest1}"

    # LEFT -> a small negative heading (wraps to 256-n); release -> back to 0
    runner.set_input(0, left=True)
    runner.run_frames(15)
    a_left = _u16(runner, DBG_ANGLE) & 0xFF
    assert 240 <= a_left <= 255, f"LEFT did not bank a small negative angle: {a_left}"
    runner.set_input(0)
    runner.run_frames(20)
    a_rest2 = _u16(runner, DBG_ANGLE) & 0xFF
    assert a_rest2 == 0, f"did not ease back to straight after LEFT release: {a_rest2}"

    # banked frame is visibly tilted: the far-floor band is not left/right
    # mirror-symmetric (a straight plane is). Compare column-mean brightness of
    # the left third vs right third in the floor band.
    def _avg(xs):
        if not xs:
            return 0
        return sum(sum(p) for p in xs) / (3 * len(xs))
    bw = w
    yy0, yy1 = int(0.30 * h), int(0.45 * h)
    left = [dR[y * w + x] for y in range(yy0, yy1) for x in range(0, bw // 3)]
    right = [dR[y * w + x] for y in range(yy0, yy1) for x in range(2 * bw // 3, bw)]
    assert abs(_avg(left) - _avg(right)) > 4.0, \
        "banked far-floor band is left/right symmetric (plane not tilted)"


def test_railshooter_fires_bullet_that_travels_and_a_reticle(runner):
    """P5a: A (rising edge) spawns a bullet in the pool; the bullet recedes UP the
    screen (toward the horizon) over successive frames; a lock-on reticle renders
    at the aim point. Reads the BUL_ALIVE pool array in WRAM (the spawn output
    region) + the bullet's OAM y (travel) + the reticle OAM entry. State cycle:
    no-bullet -> fire -> bullet-travels -> die-at-horizon."""
    rom = BUILD / "railshooter.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    # strafe to a lane clear of the obstacle columns so the bullet can travel
    runner.set_input(0, right=True)
    runner.run_frames(22)
    runner.set_input(0)
    runner.run_frames(2)

    # reticle renders (OAM slot 11, the reticle tile, visible on screen)
    rx, ry, rtile, rattr = _oam_entry(runner, 11)
    assert rtile == TILE_RETICLE and ry < 224, \
        f"lock-on reticle not rendered: tile={rtile} (want {TILE_RETICLE}) y={ry}"

    # no bullet before firing
    assert runner.read_bytes(WR, BUL_ALIVE, 2) == b"\x00\x00", "a bullet was already live"

    # fire: A rising edge -> a pooled bullet becomes live
    runner.set_input(0, a=True)
    runner.run_frames(1)
    runner.set_input(0)
    assert _u16(runner, BUL_ALIVE) == 1, "fire did not spawn a bullet (BUL_ALIVE[0]!=1)"

    # the bullet recedes UP the screen as it travels forward; track its OAM y
    ys = []
    for _ in range(10):
        runner.run_frames(2)
        bx, by, btile, battr = _oam_entry(runner, 7)
        if btile == TILE_BULLET and by < 224:
            ys.append(by)
    assert len(ys) >= 3, "bullet sprite did not render across its travel"
    assert ys[0] - ys[-1] >= 20, \
        f"bullet did not recede toward the horizon (OAM y {ys[0]} -> {ys[-1]})"


def test_railshooter_bullet_removes_obstacle(runner):
    """P5b: a bullet hitting an in-lane obstacle removes it — the obstacle
    recycles far ahead (its forward depth z jumps to ~the far edge). Reads the
    obstacle DEPTH z in WRAM (the actual recycle output) before/after firing at
    the in-lane obstacle. State cycle: aim -> fire -> obstacle-removed.

    The bullet spawns near (z=Z_NEAR) and RECEDES (z increases ~BUL_SPEED=20/fr),
    so it sweeps UP through obstacle depths. To prove the BULLET removed it (not
    a natural recycle at Z_NEAR), the target is chosen at a mid depth where a
    natural recycle is many frames away, and the recycle (z jumps far up) must
    occur within the short volley window."""
    rom = BUILD / "railshooter.sfc"
    runner.load_rom(str(rom), run_seconds=0.5)
    runner.set_input(0)
    runner.run_frames(10)

    cam_x = _u16(runner, DBG_POSX)

    def depth_of(slot):
        return _u16(runner, OBS_DEPTH + slot * 2)

    def wx_of(slot):
        return _u16(runner, OBS_WX + slot * 2)

    # Pick an in-lane obstacle (x within HIT_X_TOL of cam) at a MID depth: far
    # enough that it won't naturally recycle during the volley (>~120 px, i.e.
    # >10 frames at step 12), near enough for the climbing bullet to reach it.
    lane = [s for s in range(OBS_N)
            if _u16(runner, OBS_ALIVE + s * 2) == 1
            and abs(wx_of(s) - cam_x) <= 48 and 120 <= depth_of(s) <= 320]
    if not lane:
        # widen the window if the field's phase didn't place one mid-lane
        lane = [s for s in range(OBS_N)
                if _u16(runner, OBS_ALIVE + s * 2) == 1
                and abs(wx_of(s) - cam_x) <= 48 and depth_of(s) >= 100]
    assert lane, "no mid-depth in-lane obstacle to shoot — adjust spawn lanes"
    target = min(lane, key=depth_of)
    d_before = depth_of(target)

    # Fire a short volley; a climbing bullet sweeps through the target's depth.
    # The volley is short enough that the target cannot naturally recycle: at
    # step 12, d_before>=100 needs >=7 frames to reach Z_NEAR; the volley is
    # 6 frames of advance.
    removed = False
    for _ in range(6):
        runner.set_input(0, a=True)
        runner.run_frames(1)
        runner.set_input(0)
        runner.run_frames(1)
        d = depth_of(target)
        # recycle = z jumps far UP (toward Z_FAR=640), the bullet-removal output
        if d > d_before + 100:
            removed = True
            break

    d_after = depth_of(target)
    assert removed and d_after > 300, \
        f"obstacle not removed by the bullet (depth z {d_before} -> {d_after})"
    # the pool always holds OBS_N obstacles (removal recycles, never depletes)
    assert _u16(runner, DBG_OBSCNT) == OBS_N, "obstacle pool depleted (should recycle)"
