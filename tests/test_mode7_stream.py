"""Mode 7 2-axis tilemap-streaming proof test (Streaming rail v2 / Sprint S1).

Drives a camera WALKING a large authored Mode 7 overworld (256x256 tiles =
2048x2048 px, several windows wide AND tall vs the 128x128 Mode 7 VRAM window)
forward in X, forward in Y, BACK in both, and idle, and asserts on the RENDERED
DESTINATION — the Mode 7 VRAM tilemap low bytes — that the streamed window
matches the AUTHORED WORLD GROUND-TRUTH at the camera's world position, with no
stale/garbage strips and no black band.

Test-surface declaration (CLAUDE.md "Indirect-Evidence Tests"):
  - Feature under test: Mode 7 2-axis tilemap streaming (engine/mode7_stream.asm
    + engine/mode7_stream_nmi.inc, driven by lib/macros/sf_mode7_stream.inc).
  - OUTPUT region read: the Mode 7 VRAM tilemap LOW bytes (VRAM words 0..16383,
    even bytes) — the actual rendered tile ids — compared cell-by-cell to the
    authored world tilemap (gen_stream_world.build_tilemap()). NOT a proxy
    engine/WRAM variable. Also reads the screenshot for the no-black-band check.
  - State cycles exercised: forward-X (east), forward-Y (south), reverse-X
    (west), reverse-Y (north), and idle — the FULL state cycle (CLAUDE.md
    "State-cycle coverage"), not a single monotonic direction.

The VRAM 128x128 tilemap is a WRAPPED window onto the world centred on the
camera tile: world tile (wx,wy) lands at VRAM word (wy & 127)*128 + (wx & 127).
The window covers world tiles [cam-64 .. cam+63] each axis. After streaming
settles (camera stationary or steady single-axis motion), every VRAM cell must
equal the authored world tile at that wrapped position.
"""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "infrastructure", "test_harness"))
sys.path.insert(0, os.path.join(HERE, "fixtures", "mode7_stream"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402
import gen_stream_world as world  # noqa: E402

ROM = os.path.join(HERE, "..", "build", "mode7_stream_test.sfc")

W = world.WORLD_T            # 256
VW = 128                     # Mode 7 VRAM window
N_TILES = world.N_TILES

# debug-region offsets ($7E:E000 base)
DBG_HEARTBEAT = 0xE010
DBG_CAM_TX = 0xE012
DBG_CAM_TY = 0xE014
DBG_PHASE = 0xE016
DBG_LAST_TX = 0xE018
DBG_LAST_TY = 0xE01A

# Walk phases (must match the ROM script): 160 frames each.
PHASE_LEN = 160


@pytest.fixture(scope="module")
def tilemap():
    """Authored world ground-truth tile-id grid (row-major, 256x256)."""
    return world.build_tilemap()


def _world_tile(tm, tx, ty):
    return tm[(ty % W) * W + (tx % W)]


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    r.load_rom(ROM, run_seconds=0.5)
    yield r
    r.stop()


def _run_to_frame(r, target):
    cur = r.read_u16(MemoryType.SnesWorkRam, DBG_HEARTBEAT)
    if target > cur:
        r.run_frames(target - cur)


def _vram_lows(r):
    vram = bytes(r.read_bytes(MemoryType.SnesVideoRam, 0x0000, 0x8000))
    return vram[0::2]  # 16384 tile-id low bytes (128x128)


def _sample_window(r, tm):
    """One sample: (cam_tx, cam_ty, mismatches, garbage) for the current frame."""
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
    mid-flight. Streaming stages a row/column on the main thread on frame N and
    the NMI DMAs it into VRAM on VBlank N+1, so a sample taken on the exact
    frame the camera crossed a tile boundary sees a 1-frame-old leading edge
    (correct streaming behaviour, NOT a bug). The window is 0-mismatch on every
    frame except the one the camera tile changes; it self-heals on the next
    VBlank. Returning the best (lowest-mismatch) sample removes the sampling
    race while still failing loudly on a REAL stale/garbage strip (which would
    persist across all `tries` frames). Garbage is always reported from the
    last sample (a real garbage tile never heals)."""
    best = None
    for _ in range(tries):
        s = _sample_window(r, tm)
        if best is None or s[2] < best[2]:
            best = s
        if s[2] == 0:
            return s
        r.run_frames(1)
    return best


# ---------------------------------------------------------------------------
# MS-001 — boots and the heartbeat advances.
# ---------------------------------------------------------------------------
def test_ms001_boot_and_heartbeat(runner):
    magic = bytes(runner.read_bytes(MemoryType.SnesWorkRam, 0xE000, 4))
    assert magic == b"SFDB", f"debug magic missing (got {magic!r}) — ROM didn't boot"
    hb0 = runner.read_u16(MemoryType.SnesWorkRam, DBG_HEARTBEAT)
    runner.run_frames(10)
    hb1 = runner.read_u16(MemoryType.SnesWorkRam, DBG_HEARTBEAT)
    assert hb1 > hb0, f"heartbeat did not advance ({hb0} -> {hb1})"


# ---------------------------------------------------------------------------
# MS-002 — at spawn (initial seed window), the VRAM tilemap matches the world.
# Reads the OUTPUT region (VRAM low bytes) and compares to the authored world.
# ---------------------------------------------------------------------------
def test_ms002_seed_window_matches_world(runner, tilemap):
    _run_to_frame(runner, 5)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert garbage == 0, f"garbage tile-ids in VRAM at spawn: {garbage}"
    assert mism == 0, f"seed window mismatches world at spawn cam=({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MS-003 — walk EAST (forward X): NEW columns stream in; VRAM matches world.
# Mid-phase single-axis motion settles each frame, so the window must be exact.
# ---------------------------------------------------------------------------
def test_ms003_walk_east_streams_columns(runner, tilemap):
    _run_to_frame(runner, 120)  # well into the east phase (phase 0)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert cam_tx > world.SPAWN_TX + 8, \
        f"camera did not walk east far enough (cam_tx={cam_tx})"
    assert garbage == 0, f"garbage tile-ids after east walk: {garbage}"
    assert mism == 0, \
        f"east-streamed window mismatches world at cam=({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MS-004 — walk SOUTH (forward Y): NEW rows stream in; VRAM matches world.
# ---------------------------------------------------------------------------
def test_ms004_walk_south_streams_rows(runner, tilemap):
    _run_to_frame(runner, 280)  # into the south phase (phase 1)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert cam_ty > world.SPAWN_TY + 8, \
        f"camera did not walk south far enough (cam_ty={cam_ty})"
    assert garbage == 0, f"garbage tile-ids after south walk: {garbage}"
    assert mism == 0, \
        f"south-streamed window mismatches world at cam=({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MS-005 — walk WEST (reverse X): columns re-stream in reverse; VRAM matches.
# Reverse motion is a distinct state transition (CLAUDE.md state-cycle rule).
# ---------------------------------------------------------------------------
def test_ms005_walk_west_reverse(runner, tilemap):
    _run_to_frame(runner, 440)  # into the west phase (phase 2)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert garbage == 0, f"garbage tile-ids after west walk: {garbage}"
    assert mism == 0, \
        f"west-reverse window mismatches world at cam=({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MS-006 — walk NORTH (reverse Y): rows re-stream in reverse; VRAM matches.
# ---------------------------------------------------------------------------
def test_ms006_walk_north_reverse(runner, tilemap):
    _run_to_frame(runner, 600)  # into the north phase (phase 3)
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert garbage == 0, f"garbage tile-ids after north walk: {garbage}"
    assert mism == 0, \
        f"north-reverse window mismatches world at cam=({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MS-007 — IDLE: after returning to spawn and going idle, the window is exact
# and the camera has come to rest (the full state cycle closes cleanly).
# ---------------------------------------------------------------------------
def test_ms007_idle_after_full_cycle(runner, tilemap):
    _run_to_frame(runner, 720)  # idle phase (phase 4)
    phase = runner.read_u16(MemoryType.SnesWorkRam, DBG_PHASE)
    assert phase == 4, f"expected idle phase 4, got {phase}"
    cam_tx, cam_ty, mism, garbage = _window_mismatches(runner, tilemap)
    assert garbage == 0, f"garbage tile-ids at idle: {garbage}"
    assert mism == 0, \
        f"idle window mismatches world at cam=({cam_tx},{cam_ty}): {mism}"


# ---------------------------------------------------------------------------
# MS-008 — landmark ground-truth: the hidden 32-tile TOWN-tile lattice renders
# at its world position. This is position-identifiable proof the STREAMED
# content is the AUTHORED world (not a coincidental grass fill). Find every
# TOWN landmark lattice point inside the current window and confirm EACH renders
# TILE_TOWN at its wrapped VRAM cell. Robust to wherever the camera has walked.
# ---------------------------------------------------------------------------
def test_ms008_landmarks_render_at_world_positions(runner, tilemap):
    _run_to_frame(runner, 720)  # idle, window centred & settled
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
            # this world tile is a TOWN landmark by construction
            assert _world_tile(tilemap, wx, wy) == world.TILE_TOWN
            vx = wx & (VW - 1)
            vy = wy & (VW - 1)
            got = lows[vy * VW + vx]
            assert got == world.TILE_TOWN, \
                f"landmark at world({wx % W},{wy % W}) should render TILE_TOWN " \
                f"({world.TILE_TOWN}); VRAM cell ({vx},{vy}) = {got}"
            checked += 1
    assert checked >= 4, \
        f"expected >= 4 landmark lattice points in the window, found {checked}"


# ---------------------------------------------------------------------------
# MS-009 — NO BLACK BAND: the rendered screen shows authored content, not a
# scanline-wide black strip (the Phase-17 streaming-black-band regression
# class). Reads the SCREENSHOT pixels and rejects any all-black scanline in
# the active Mode 7 area.
# ---------------------------------------------------------------------------
def test_ms009_no_black_band(runner):
    from PIL import Image
    _run_to_frame(runner, 300)  # mid-walk (active streaming)
    shot = "/tmp/s1_shots/ms009_blackband.png"
    os.makedirs("/tmp/s1_shots", exist_ok=True)
    runner.take_screenshot(shot)
    img = Image.open(shot).convert("RGB")
    w, h = img.size
    px = img.load()
    # The Mode 7 plane fills the centre; the top/bottom few rows can be the
    # screen's natural black border. Scan the central band only.
    black_rows = 0
    for y in range(16, h - 16):
        row_black = all(px[x, y] == (0, 0, 0) for x in range(0, w, 4))
        if row_black:
            black_rows += 1
    assert black_rows == 0, \
        f"found {black_rows} all-black scanline(s) in the Mode 7 area " \
        f"(streaming black-band regression)"
