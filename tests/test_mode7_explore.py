"""Mode 7 streaming EXPLORATION rail done-condition (Streaming rail v2 / S2 +
F1 remediation: world grown to 512x512 so "several windows" is LITERAL).

Drives the AVATAR with REAL D-pad input (not a scripted camera) walking a large
authored Mode 7 overworld (512x512 tiles = 4096x4096 px, SEVERAL windows wide AND
tall vs the 128x128 Mode 7 VRAM window) forward-X, forward-Y, reverse, and idle,
and asserts on the RENDERED DESTINATION — the Mode 7 VRAM tilemap low bytes —
that the streamed window matches the AUTHORED WORLD GROUND-TRUTH at the avatar's
world position, with no stale/garbage strips and no black band. Also drives the
avatar INTO a wall (mountain) and confirms it is BLOCKED (the camera does not
enter the blocked tile), reading the camera world position from WRAM after the
collision.

Test-surface declaration (CLAUDE.md "Indirect-Evidence Tests"):
  - Feature under test: the mode7_explore streaming exploration rail — an avatar
    walking a streaming Mode 7 world (engine/mode7_stream.asm + _nmi.inc via
    lib/macros/sf_mode7_stream.inc) with WORLD-SPACE tile collision.
  - OUTPUT region read:
      * the Mode 7 VRAM tilemap LOW bytes (VRAM words 0..16383, even bytes) — the
        actual rendered tile ids — compared cell-by-cell to the authored world
        tilemap (make_explore_world.build_tilemap()). NOT a proxy variable.
      * the rendered SCREENSHOT pixels (no-black-band check).
      * the avatar OAM low-table bytes (it stays screen-centred).
      * the camera world TILE position in WRAM ($7E:E014) AFTER walking into a
        wall — confirming the avatar did NOT enter the blocked tile (collision is
        proven by where the camera CAME TO REST against the wall, plus the
        blocked-step counter which only the rejected-step path increments).
  - State cycles exercised: forward-X (east), forward-Y (south), reverse-X
    (west), reverse-Y (north), idle, AND a collision (walk into a mountain) —
    the full state cycle (CLAUDE.md "State-cycle coverage"), driven by real
    input, not a scripted frame counter.

The VRAM 128x128 tilemap is a WRAPPED window onto the world centred on the
camera tile: world tile (wx,wy) lands at VRAM word (wy & 127)*128 + (wx & 127).
The window covers world tiles [cam-64 .. cam+63] each axis.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "infrastructure", "test_harness"))
sys.path.insert(0, os.path.join(HERE, "..", "templates", "mode7_explore", "assets"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402
import make_explore_world as world  # noqa: E402

ROM = os.path.join(HERE, "..", "build", "mode7_explore.sfc")

W = world.WORLD_T            # 512 (F1 remediation)
VW = 128                     # Mode 7 VRAM window
N_TILES = world.N_TILES

# debug-region offsets ($7E:E000 base)
DBG_HEARTBEAT = 0xE010
DBG_CAM_TX = 0xE012
DBG_CAM_TY = 0xE014
DBG_LAST_TX = 0xE018
DBG_LAST_TY = 0xE01A
DBG_BLOCK_CT = 0xE01C

# Avatar screen centre (kept fixed; the camera carries world position).
AV_X0 = 120
AV_Y0 = 104


@pytest.fixture(scope="module")
def tilemap():
    """Authored world ground-truth tile-id grid (row-major, 512x512)."""
    return world.build_tilemap()


def _world_tile(tm, tx, ty):
    return tm[(ty % W) * W + (tx % W)]


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    r.load_rom(ROM, run_seconds=0.5)
    yield r
    r.stop()


def _vram_lows(r):
    vram = bytes(r.read_bytes(MemoryType.SnesVideoRam, 0x0000, 0x8000))
    return vram[0::2]  # 16384 tile-id low bytes (128x128)


def _sample_window(r, tm):
    cam_tx = r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TX)
    cam_ty = r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
    lows = _vram_lows(r)
    mism = 0
    for wy in range(cam_ty - 64, cam_ty + 64):
        vy = wy & (VW - 1)
        for wx in range(cam_tx - 64, cam_tx + 64):
            vx = wx & (VW - 1)
            if _world_tile(tm, wx, wy) != lows[vy * VW + vx]:
                mism += 1
    garbage = sum(1 for b in lows if b >= N_TILES)
    return cam_tx, cam_ty, mism, garbage


def _window_mismatches(r, tm, tries=4):
    """Sample the window, retrying up to `tries` frames if a leading edge is
    mid-flight (the tick stages on frame N; the NMI DMAs on VBlank N+1, so a
    sample taken on the exact tile-crossing frame sees a 1-frame-old edge — this
    self-heals next VBlank). A REAL stale/garbage strip persists across all
    tries and fails loudly."""
    best = None
    for _ in range(tries):
        s = _sample_window(r, tm)
        if best is None or s[2] < best[2]:
            best = s
        if s[2] == 0:
            return s
        r.run_frames(1)
    return best


def _walk(r, frames, **buttons):
    """Hold a direction for `frames` frames, then release + settle."""
    r.set_input(0, **buttons)
    r.run_frames(frames)
    r.set_input(0)
    r.run_frames(6)


# ---------------------------------------------------------------------------
# MX-001 — boots and the heartbeat advances.
# ---------------------------------------------------------------------------
def test_mx001_boot_and_heartbeat(runner):
    magic = bytes(runner.read_bytes(MemoryType.SnesWorkRam, 0xE000, 4))
    assert magic == b"SFDB", f"debug magic missing (got {magic!r}) — ROM didn't boot"
    hb0 = runner.read_u16(MemoryType.SnesWorkRam, DBG_HEARTBEAT)
    runner.run_frames(10)
    hb1 = runner.read_u16(MemoryType.SnesWorkRam, DBG_HEARTBEAT)
    assert hb1 > hb0, f"heartbeat did not advance ({hb0} -> {hb1})"


# ---------------------------------------------------------------------------
# MX-002 — the avatar is screen-centred at OAM slot 0 (the camera moves, the
# avatar stays put). Reads the OAM low-table bytes directly.
# ---------------------------------------------------------------------------
def test_mx002_avatar_centred_oam(runner):
    runner.run_frames(4)
    oam = bytes(runner.read_bytes(MemoryType.SnesSpriteRam, 0, 4))
    assert oam[0] == AV_X0, f"avatar X = {oam[0]}, expected {AV_X0}"
    assert oam[1] == AV_Y0, f"avatar Y = {oam[1]}, expected {AV_Y0}"
    assert oam[2] == world.AVATAR_BASE_TILE, \
        f"avatar tile = {oam[2]}, expected {world.AVATAR_BASE_TILE}"


# ---------------------------------------------------------------------------
# MX-003 — at spawn (initial seed window), the VRAM tilemap matches the world.
# ---------------------------------------------------------------------------
def test_mx003_seed_window_matches_world(runner, tilemap):
    runner.run_frames(6)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert cam_tx == world.SPAWN_TX and cam_ty == world.SPAWN_TY, \
        f"camera not at spawn: ({cam_tx},{cam_ty})"
    assert garbage == 0, f"garbage tile-ids in VRAM at spawn: {garbage}"
    assert mism == 0, f"seed window mismatches world at spawn: {mism}"


# ---------------------------------------------------------------------------
# MX-004 — walk EAST (forward X) with real input: NEW columns stream in; the
# rendered VRAM window matches the world at the new camera position.
# ---------------------------------------------------------------------------
def test_mx004_walk_east_streams_columns(runner, tilemap):
    start_tx = runner.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TX)
    _walk(runner, 80, right=True)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert cam_tx > start_tx + 4, f"camera did not walk east (cam_tx={cam_tx})"
    assert garbage == 0, f"garbage after east walk: {garbage}"
    assert mism == 0, f"east window mismatches world at ({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MX-005 — walk SOUTH (forward Y): NEW rows stream in; VRAM matches.
# ---------------------------------------------------------------------------
def test_mx005_walk_south_streams_rows(runner, tilemap):
    start_ty = runner.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
    _walk(runner, 80, down=True)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert cam_ty > start_ty + 4, f"camera did not walk south (cam_ty={cam_ty})"
    assert garbage == 0, f"garbage after south walk: {garbage}"
    assert mism == 0, f"south window mismatches world at ({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MX-006 — walk WEST (reverse X): columns re-stream in reverse; VRAM matches.
# Reverse motion is a distinct state transition (CLAUDE.md state-cycle rule).
# ---------------------------------------------------------------------------
def test_mx006_walk_west_reverse(runner, tilemap):
    start_tx = runner.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TX)
    _walk(runner, 80, left=True)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert cam_tx < start_tx - 4, f"camera did not walk west (cam_tx={cam_tx})"
    assert garbage == 0, f"garbage after west walk: {garbage}"
    assert mism == 0, f"west window mismatches world at ({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MX-007 — walk NORTH (reverse Y): rows re-stream in reverse; VRAM matches.
# ---------------------------------------------------------------------------
def test_mx007_walk_north_reverse(runner, tilemap):
    start_ty = runner.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
    _walk(runner, 40, up=True)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert cam_ty < start_ty, f"camera did not walk north (cam_ty={cam_ty})"
    assert garbage == 0, f"garbage after north walk: {garbage}"
    assert mism == 0, f"north window mismatches world at ({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MX-008 — IDLE: release input; the window stays exact and the camera at rest.
# Closes the full state cycle cleanly.
# ---------------------------------------------------------------------------
def test_mx008_idle_window_exact(runner, tilemap):
    runner.set_input(0)
    runner.run_frames(30)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert garbage == 0, f"garbage at idle: {garbage}"
    assert mism == 0, f"idle window mismatches world at ({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MX-009 — landmark ground-truth: the hidden 32-tile TOWN-tile lattice renders
# at its world position. Position-identifiable proof the STREAMED content is the
# AUTHORED world (not a coincidental grass fill). Robust to wherever the camera
# walked: find every TOWN landmark inside the current window, confirm each
# renders TILE_TOWN at its wrapped VRAM cell.
# ---------------------------------------------------------------------------
def test_mx009_landmarks_render_at_world_positions(runner, tilemap):
    runner.set_input(0)
    runner.run_frames(8)
    cam_tx = runner.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TX)
    cam_ty = runner.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
    lows = _vram_lows(runner)
    step = world.LANDMARK_STEP
    checked = 0
    for wy in range(cam_ty - 64, cam_ty + 64):
        if (wy % W) % step != 0:
            continue
        for wx in range(cam_tx - 64, cam_tx + 64):
            if (wx % W) % step != 0:
                continue
            # only assert landmarks the authored world actually placed (the spawn
            # clearing carves a couple lattice cells back to grass — skip those).
            if _world_tile(tilemap, wx, wy) != world.TILE_TOWN:
                continue
            vx = wx & (VW - 1)
            vy = wy & (VW - 1)
            got = lows[vy * VW + vx]
            assert got == world.TILE_TOWN, \
                f"landmark at world({wx % W},{wy % W}) should render TILE_TOWN " \
                f"({world.TILE_TOWN}); VRAM cell ({vx},{vy}) = {got}"
            checked += 1
    assert checked >= 2, \
        f"expected >= 2 TOWN landmark lattice points in the window, found {checked}"


# ---------------------------------------------------------------------------
# MX-010 — COLLISION: walk the avatar NORTH into the mountain wall at world row
# 126 (4 tiles above spawn). The camera must STOP at ty=127 (adjacent to the
# blocked tile) — it must NOT enter the blocked tile (ty<=126). The blocked-step
# counter (only the rejected-step path increments it) must rise as the avatar
# keeps pressing into the wall. Reads the camera world position + block counter
# from WRAM (the OUTPUT of the collision logic), a FRESH boot so spawn is known.
# ---------------------------------------------------------------------------
def _blocked_terrains():
    return (world.TILE_MTN_DK, world.TILE_MTN_LT,
            world.TILE_WATER_DK, world.TILE_WATER_LT)


def _step_once(r, **buttons):
    """Drive exactly ONE discrete grid step (8-frame slide) then release+settle,
    so the camera advances by exactly one tile (the grid machine ignores new
    input mid-slide; pressing 8 frames then releasing lands one tile exactly)."""
    r.set_input(0, **buttons)
    r.run_frames(8)
    r.set_input(0)
    r.run_frames(4)


def _nearest_wall_north_in_col(tilemap, cx, ty0):
    """First BLOCKED world row going north from ty0 in column cx (or None)."""
    for k in range(1, 40):
        cy = ty0 - k
        if tilemap[cy * W + cx] in _blocked_terrains():
            return cy
    return None


def test_mx010_collision_blocks_avatar_at_wall(tilemap):
    # The two spawn axes are open road corridors; reach a wall by stepping a few
    # tiles EAST off the spawn column, then walking NORTH into the geography. The
    # wall row is derived from the ground-truth tilemap IN THE COLUMN THE AVATAR
    # ACTUALLY REACHED (collision is LUT-derived from this SAME flat tilemap byte
    # via tile_terrain_lut), so the test tracks the asset exactly.
    r = MesenRunner()
    try:
        r.load_rom(ROM, run_seconds=0.5)
        r.run_frames(8)
        assert r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY) == world.SPAWN_TY
        # --- step EAST one tile at a time until the current column has a BLOCKED
        #     tile to the north within reach (so holding UP exercises collision).
        cx = world.SPAWN_TX
        wall_ty = None
        for _ in range(40):
            _step_once(r, right=True)
            cx = r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TX)
            ty_now = r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
            wall_ty = _nearest_wall_north_in_col(tilemap, cx, ty_now)
            if wall_ty is not None and wall_ty < ty_now - 1:
                break
        assert wall_ty is not None, "no reachable north wall found stepping east from spawn"
        stop_ty = wall_ty + 1                  # camera rests one tile SOUTH of the wall
        ty_now = r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
        assert tilemap[wall_ty * W + cx] in _blocked_terrains(), \
            f"expected a blocked tile at world ({cx},{wall_ty})"
        bc0 = r.read_u16(MemoryType.SnesWorkRam, DBG_BLOCK_CT)
        # --- now hold UP into the wall; the avatar walks to stop_ty then blocks. ---
        r.set_input(0, up=True)
        r.run_frames(200)
        r.set_input(0)
        r.run_frames(6)
        cam_ty = r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
        bc1 = r.read_u16(MemoryType.SnesWorkRam, DBG_BLOCK_CT)
        # the camera STOPPED adjacent to the wall (stop_ty); it did NOT enter the
        # blocked tile (ty would be <= wall_ty if collision were broken).
        assert cam_ty == stop_ty, \
            f"avatar should stop at ty={stop_ty} (adjacent to the blocked tile at " \
            f"ty={wall_ty}) in column {cx}; got cam_ty={cam_ty} (entered the wall if <={wall_ty})"
        # the rejected-step path fired (the blocked counter rose).
        assert bc1 > bc0, \
            f"blocked-step counter did not rise ({bc0} -> {bc1}) — the wall did " \
            f"not reject any step (collision not exercised)"
    finally:
        r.stop()


# ---------------------------------------------------------------------------
# MX-011 — NO BLACK BAND: the rendered screen shows authored content, not a
# scanline-wide black strip (the Phase-17 streaming-black-band regression
# class). Reads the SCREENSHOT pixels and rejects any all-black scanline in the
# active Mode 7 area, mid-walk (active streaming).
# ---------------------------------------------------------------------------
def test_mx011_no_black_band(tilemap):
    from PIL import Image
    r = MesenRunner()
    try:
        r.load_rom(ROM, run_seconds=0.5)
        r.run_frames(8)
        r.set_input(0, right=True)
        r.run_frames(40)        # mid-walk, active column streaming
        shot = "/tmp/s2_shots/mx011_blackband.png"
        os.makedirs("/tmp/s2_shots", exist_ok=True)
        r.take_screenshot(shot)
        img = Image.open(shot).convert("RGB")
        w, h = img.size
        px = img.load()
        black_rows = 0
        for y in range(16, h - 16):
            if all(px[x, y] == (0, 0, 0) for x in range(0, w, 4)):
                black_rows += 1
        assert black_rows == 0, \
            f"found {black_rows} all-black scanline(s) in the Mode 7 area " \
            f"(streaming black-band regression)"
    finally:
        r.stop()


# ---------------------------------------------------------------------------
# MX-012 — SEVERAL-WINDOWS TRAVERSAL (F1 remediation core). Walk the avatar from
# the spawn ACROSS the full camera-clamp box each axis (>= 3 streaming windows of
# distinct authored content) and confirm NEW authored content streams the whole
# way — the rendered VRAM window matches the AUTHORED WORLD GROUND-TRUTH at every
# sampled camera position, with NO wrap-repeat (a 128-tile wrap-repeat of the
# seed window would FAIL the cell-by-cell compare once the camera passes the seed
# window boundary). Reads the VRAM tilemap low bytes (the rendered DESTINATION)
# vs make_explore_world.build_tilemap(), not a proxy variable.
#
# The camera clamp is [64..447] (WORLD_HALF .. WORLD_T-1-WORLD_HALF for a 512
# world); spawn is at (258,258). Walking WEST to the clamp min then EAST to the
# clamp max sweeps the full 383-tile camera range each axis = ~3.0 windows of
# camera travel (~4.0 windows of distinct content seen). Each axis is sampled at
# multiple distinct camera positions to prove continuous NEW content.
# ---------------------------------------------------------------------------
def _drive_until_tile(r, axis_addr, target, **buttons):
    """Hold a direction until the camera reaches (or passes) `target` tile on the
    given debug axis, or it comes to rest (clamp/wall) across TWO consecutive
    sample windows, or a frame budget expires. Returns the final tile value.

    Robustness: a single sample can land between grid steps (step just completed,
    next not yet started) so the camera reads unchanged for one window even while
    walking — declare "stopped" only after TWO consecutive unchanged windows."""
    last = r.read_u16(MemoryType.SnesWorkRam, axis_addr)
    stalls = 0
    r.set_input(0, **buttons)
    for i in range(1200):          # budget: plenty for a ~200-tile sweep
        r.run_frames(8)            # one grid step (8 frames @ 1px/frame)
        cur = r.read_u16(MemoryType.SnesWorkRam, axis_addr)
        if cur == last:
            stalls += 1
            if stalls >= 3 and i > 3:   # 3 unchanged windows -> truly at rest
                break
        else:
            stalls = 0
        last = cur
        if (buttons.get("right") or buttons.get("down")) and cur >= target:
            break
        if (buttons.get("left") or buttons.get("up")) and cur <= target:
            break
    r.set_input(0)
    r.run_frames(6)
    return r.read_u16(MemoryType.SnesWorkRam, axis_addr)


def test_mx012_three_windows_of_travel_each_axis(tilemap):
    HALF = 64
    CLAMP_MIN = HALF                      # 64
    CLAMP_MAX = W - 1 - HALF              # 447
    r = MesenRunner()
    try:
        r.load_rom(ROM, run_seconds=0.5)
        r.run_frames(8)
        spawn_tx = r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TX)
        spawn_ty = r.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
        assert spawn_tx == world.SPAWN_TX and spawn_ty == world.SPAWN_TY

        # collect distinct camera-X positions across a full WEST->EAST sweep,
        # asserting the window is byte-exact at each, and recording the span.
        x_positions = [spawn_tx]

        def sample_here(axis):
            cam_tx, cam_ty, mism, garbage = _window_mismatches(r, tilemap)
            assert garbage == 0, f"garbage during {axis} sweep at ({cam_tx},{cam_ty}): {garbage}"
            assert mism == 0, \
                f"{axis} window mismatches world at ({cam_tx},{cam_ty}): {mism} " \
                f"(streamed content drifted from the authored world — wrap-repeat?)"
            return cam_tx, cam_ty

        # --- WEST to the clamp minimum (sampling partway + at the edge) ---
        _drive_until_tile(r, DBG_CAM_TX, (spawn_tx + CLAMP_MIN) // 2, left=True)
        x_positions.append(sample_here("west-mid")[0])
        west_tx = _drive_until_tile(r, DBG_CAM_TX, CLAMP_MIN, left=True)
        x_positions.append(sample_here("west-edge")[0])

        # --- EAST all the way to the clamp maximum (full-range sweep) ---
        _drive_until_tile(r, DBG_CAM_TX, (CLAMP_MIN + CLAMP_MAX) // 2, right=True)
        x_positions.append(sample_here("east-mid")[0])
        east_tx = _drive_until_tile(r, DBG_CAM_TX, CLAMP_MAX, right=True)
        x_positions.append(sample_here("east-edge")[0])

        # Travel bar: the full camera-clamp span = CLAMP_MAX - CLAMP_MIN = 383
        # tiles ≈ 3.0 windows of camera travel (the window shows cam±64, so the
        # distinct CONTENT seen is 383+128 = 511 tiles ≈ 4.0 windows). Assert the
        # camera reached the full clamp span each axis.
        TRAVEL_BAR = CLAMP_MAX - CLAMP_MIN          # 383 tiles ≈ 3.0 windows
        x_span = max(x_positions) - min(x_positions)
        assert x_span >= TRAVEL_BAR, \
            f"X camera travel {x_span} tiles < clamp span {TRAVEL_BAR} (~3 windows); " \
            f"positions {sorted(set(x_positions))}"
        # the avatar reached (within a tile) the clamp extremes -> the world is
        # genuinely several windows wide and the clamp doesn't pin it short.
        assert west_tx <= CLAMP_MIN + 1, f"did not reach the west clamp edge (got {west_tx})"
        assert east_tx >= CLAMP_MAX - 1, f"did not reach the east clamp edge (got {east_tx})"

        # --- now sweep the Y axis the same way (NORTH then SOUTH). Reset by
        #     re-booting so the wall north of spawn doesn't gate the Y sweep:
        #     walk SOUTH (away from the north wall) to the clamp max, then NORTH. -
    finally:
        r.stop()

    r2 = MesenRunner()
    try:
        r2.load_rom(ROM, run_seconds=0.5)
        r2.run_frames(8)
        spawn_ty = r2.read_u16(MemoryType.SnesWorkRam, DBG_CAM_TY)
        y_positions = [spawn_ty]

        def sample_y(axis):
            cam_tx, cam_ty, mism, garbage = _window_mismatches(r2, tilemap)
            assert garbage == 0, f"garbage during {axis} at ({cam_tx},{cam_ty}): {garbage}"
            assert mism == 0, \
                f"{axis} window mismatches world at ({cam_tx},{cam_ty}): {mism}"
            return cam_ty

        CLAMP_MIN = HALF
        CLAMP_MAX = W - 1 - HALF
        TRAVEL_BAR = CLAMP_MAX - CLAMP_MIN           # 383 tiles ≈ 3.0 windows
        # The spawn COLUMN is an open authored road corridor (full clamp range),
        # so the avatar walks the whole 383-tile span: SOUTH to the clamp max,
        # then NORTH all the way to the clamp min.
        _drive_until_tile(r2, DBG_CAM_TY, (spawn_ty + CLAMP_MAX) // 2, down=True)
        y_positions.append(sample_y("south-mid"))
        south_ty = _drive_until_tile(r2, DBG_CAM_TY, CLAMP_MAX, down=True)
        y_positions.append(sample_y("south-edge"))
        _drive_until_tile(r2, DBG_CAM_TY, (CLAMP_MIN + CLAMP_MAX) // 2, up=True)
        y_positions.append(sample_y("north-mid"))
        north_ty = _drive_until_tile(r2, DBG_CAM_TY, CLAMP_MIN, up=True)
        y_positions.append(sample_y("north-edge"))

        y_span = max(y_positions) - min(y_positions)
        assert y_span >= TRAVEL_BAR, \
            f"Y camera travel {y_span} tiles < clamp span {TRAVEL_BAR} (~3 windows); " \
            f"positions {sorted(set(y_positions))}"
        assert south_ty >= CLAMP_MAX - 1, f"did not reach the south clamp edge (got {south_ty})"
        assert north_ty <= CLAMP_MIN + 1, f"did not reach the north clamp edge (got {north_ty})"
    finally:
        r2.stop()
