"""
test_bg_stream.py — proof test for the Mode-1 normal-BG horizontal column-
                    streaming rail (Streaming rail Mode 1 / Sprint S1).

TEST SURFACE DECLARATION (CLAUDE.md "Indirect-Evidence Tests"):
  - Feature under test: horizontal BG1 column streaming (engine/bg_stream.asm
    producer + the engine/nmi_handler.asm STREAM_PENDING DMA consumer), driven
    by a scripted camera over a WIDE authored Four Seasons level (256 tiles =
    8 screens wide), wired via lib/macros/sf_stream.inc.
  - OUTPUT region read: the BG1 VRAM TILEMAP low+high words in the resident
    64x32 window (VRAM word $5800-$5FFF). For each visible world column we
    read the ring-slot VRAM word and compare it tile-for-tile to the authored
    level ground-truth (tests/fixtures/bg_stream/level_flat.bin, column-major).
    This is the rendered destination, NOT a proxy variable.
  - State cycles exercised: FORWARD (pan east into new content past the resident
    window), REVERSE (pan back west — the ring's trailing edge must repopulate),
    and IDLE (no streaming — window stays correct). All three.

The position-identifiability used to map the test (cam_x, STREAM_CAM_COL,
STREAM_FIRST_COL) is a HIDDEN/DEBUG surface mirrored to $7E:E010+. The VISIBLE
level is the authored Four Seasons art.
"""
import os
import struct

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROM = os.path.join(HERE, "..", "build", "bg_stream_test.sfc")
LEVEL_FLAT = os.path.join(HERE, "fixtures", "bg_stream", "level_flat.bin")

# World geometry (mirrors tools/level_pipeline_bg.py / bg_stream_world.inc).
WORLD_W_TILES = 256
WORLD_H_TILES = 32
COL_BYTES = WORLD_H_TILES * 2          # 64 bytes/column (column-major)
SCREEN_TILES = 32                      # 256px visible window in 8px tiles

# VRAM ring layout (BG1SC=$59, 64x32, two 32x32 pages).
BG1_PAGE0_WORD = 0x5800
BG1_PAGE1_WORD = 0x5C00

# Debug region mirrors ($7E:E000 + offset).
DBG_HEARTBEAT = 0xE010
DBG_CAMX = 0xE012
DBG_PHASE = 0xE014
DBG_CAM_COL = 0xE016
DBG_LAST_COL = 0xE018
DBG_FIRST_COL = 0xE01A
DBG_ACTIVE = 0xE01C

PHASE0_END = 224
PHASE1_END = 448


@pytest.fixture(scope="module")
def runner():
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "infrastructure", "test_harness"))
    from mesen_runner import MesenRunner
    r = MesenRunner()
    assert os.path.exists(ROM), f"ROM not built: {ROM} (run `make build/bg_stream_test.sfc`)"
    r.load_rom(ROM, run_seconds=0.05)
    yield r
    r.stop()


@pytest.fixture(scope="module")
def level():
    with open(LEVEL_FLAT, "rb") as fh:
        return fh.read()


def _u16(runner, addr):
    from mesen_runner import MemoryType
    b = runner.read_bytes(MemoryType.SnesWorkRam, addr, 2)
    return b[0] | (b[1] << 8)


def _authored_word(level, col, row):
    """Authored tilemap word at (world col, row), column-major."""
    off = col * COL_BYTES + row * 2
    return level[off] | (level[off + 1] << 8)


def _vram_word(runner, world_col, row):
    """Read the BG1 VRAM tilemap word for `world_col` at its RING SLOT.
    Ring slot = world_col & $3F; page 0 if slot<32 else page 1."""
    from mesen_runner import MemoryType
    slot = world_col & 0x3F
    if slot < 32:
        word_addr = BG1_PAGE0_WORD + row * 32 + slot
    else:
        word_addr = BG1_PAGE1_WORD + row * 32 + (slot - 32)
    b = runner.read_bytes(MemoryType.SnesVideoRam, word_addr * 2, 2)
    return b[0] | (b[1] << 8)


def _advance_to_phase_pos(runner, target_phase, min_cam_col=None, max_cam_col=None, timeout_frames=900):
    """Run frames until the ROM reports the target phase (and an optional
    cam_col window). Returns (cam_col, first_col, last_col)."""
    for _ in range(timeout_frames):
        runner.run_frames(2)
        phase = _u16(runner, DBG_PHASE)
        cam_col = _u16(runner, DBG_CAM_COL)
        if phase == target_phase:
            if min_cam_col is not None and cam_col < min_cam_col:
                continue
            if max_cam_col is not None and cam_col > max_cam_col:
                continue
            return cam_col, _u16(runner, DBG_FIRST_COL), _u16(runner, DBG_LAST_COL)
    raise AssertionError(
        f"never reached phase {target_phase} "
        f"(cam_col window {min_cam_col}..{max_cam_col})"
    )


def _assert_window_matches(runner, level, cam_col, first_col, last_col, label):
    """The resident ring window [first_col, last_col] is the authored level.
    For every world column currently HELD in the ring (whose slot is uniquely
    owned), the VRAM tilemap column must equal the authored column — no stale
    strips, no garbage. We check the FULLY-VISIBLE interior columns, all 32 rows
    each.

    Inset by 1 column on each edge: under continuous camera motion the single
    column at the ACTIVELY-STREAMING edge has an inherent 1-frame lag (the
    producer queues it, the NMI drains it next VBlank), and the leftmost
    visible column is partially scrolled off by BG1HOFS sub-tile scroll. The
    fully-visible interior is the rendered-destination invariant a user sees;
    the at-rest IDLE test verifies the edge columns too (no inset there)."""
    lo = max(cam_col, first_col) + 1
    hi = min(cam_col + SCREEN_TILES - 1, last_col, WORLD_W_TILES - 1) - 1
    assert hi >= lo, f"{label}: empty visible window (cam_col={cam_col} ring=[{first_col},{last_col}])"
    mismatches = []
    checked = 0
    for col in range(lo, hi + 1):
        for row in range(WORLD_H_TILES):
            got = _vram_word(runner, col, row) & 0x3FF      # tile-id bits
            want = _authored_word(level, col, row) & 0x3FF
            checked += 1
            if got != want:
                mismatches.append((col, row, got, want))
    assert checked > 0
    assert not mismatches, (
        f"{label}: {len(mismatches)}/{checked} VRAM tilemap cells DIFFER from the "
        f"authored level (stale/garbage strip). First 8: {mismatches[:8]} "
        f"(cam_col={cam_col} ring=[{first_col},{last_col}])"
    )


# =============================================================================
# Boot / liveness
# =============================================================================
def test_boot_magic_and_heartbeat(runner):
    """ROM boots (SFDB) and the frame heartbeat advances."""
    from mesen_runner import MemoryType
    runner.run_frames(10)
    magic = bytes(runner.read_bytes(MemoryType.SnesWorkRam, 0xE000, 4))
    assert magic == b"SFDB", f"debug magic not SFDB: {magic!r}"
    hb0 = _u16(runner, DBG_HEARTBEAT)
    runner.run_frames(10)
    hb1 = _u16(runner, DBG_HEARTBEAT)
    assert hb1 > hb0, f"heartbeat did not advance ({hb0} -> {hb1})"


def test_streaming_channel_allocated(runner):
    """bg_stream_init allocated a DMA channel (STREAM_ACTIVE=1) — without it
    no column ever DMAs (graceful-degrade path would silently render nothing)."""
    active = _u16(runner, DBG_ACTIVE)
    assert active == 1, f"STREAM_ACTIVE != 1 (={active}); hdma_request found no free channel"


# =============================================================================
# FORWARD streaming — pan east into new authored content past the window
# =============================================================================
def test_forward_window_matches_authored_near_start(runner, level):
    """Early east pan: the resident window must match the authored level at
    the camera's world column (boot-loaded + early forward streaming)."""
    cam_col, first_col, last_col = _advance_to_phase_pos(
        runner, 0, min_cam_col=20, max_cam_col=40
    )
    _assert_window_matches(runner, level, cam_col, first_col, last_col, "forward-near-start")


def test_forward_window_matches_authored_past_resident_window(runner, level):
    """Deep east pan PAST the 64-column resident window — the only way these
    columns are correct is if they STREAMED in (boot only loaded cols 0..63).
    This is the core forward-streaming proof."""
    cam_col, first_col, last_col = _advance_to_phase_pos(
        runner, 0, min_cam_col=150, max_cam_col=200
    )
    assert cam_col > 64, f"camera never panned past the resident window (cam_col={cam_col})"
    _assert_window_matches(runner, level, cam_col, first_col, last_col, "forward-deep")


def test_forward_window_matches_at_right_edge(runner, level):
    """At the level's right edge the window must still be the authored content
    (the producer caps last_col at width-1; no read past the level boundary)."""
    cam_col, first_col, last_col = _advance_to_phase_pos(
        runner, 0, min_cam_col=210
    )
    _assert_window_matches(runner, level, cam_col, first_col, last_col, "forward-right-edge")


# =============================================================================
# REVERSE streaming — pan back west; trailing-edge ring slots must repopulate
# =============================================================================
def test_reverse_window_matches_authored(runner, level):
    """Pan WEST after reaching the right edge. The ring's trailing (left) edge
    must repopulate with the authored columns it streamed away from — the
    classic 'walk back left' bug class (CLAUDE.md state-cycle coverage)."""
    cam_col, first_col, last_col = _advance_to_phase_pos(
        runner, 1, min_cam_col=80, max_cam_col=160
    )
    _assert_window_matches(runner, level, cam_col, first_col, last_col, "reverse-mid")


def test_reverse_window_matches_back_near_start(runner, level):
    """Continue west back toward col 0 — the window must again be the authored
    level-start content (proves reverse streaming all the way back)."""
    cam_col, first_col, last_col = _advance_to_phase_pos(
        runner, 1, max_cam_col=40
    )
    _assert_window_matches(runner, level, cam_col, first_col, last_col, "reverse-near-start")


# =============================================================================
# IDLE — no streaming; the resident window must stay correct (no drift/decay)
# =============================================================================
def test_idle_window_matches_authored_full(runner, level):
    """In the idle phase the camera holds still and nothing streams; the FULL
    visible window — INCLUDING the edge columns (no inset) — must be the
    authored content. This is the at-rest invariant: every column the user
    sees, all 32 rows, no stale overwrite, no black band. Settles first so all
    pending columns have drained."""
    cam_col, first_col, last_col = _advance_to_phase_pos(runner, 2)
    runner.run_frames(30)
    cam_col2 = _u16(runner, DBG_CAM_COL)
    assert cam_col2 == cam_col, f"camera moved during idle ({cam_col} -> {cam_col2})"
    first_col = _u16(runner, DBG_FIRST_COL)
    last_col = _u16(runner, DBG_LAST_COL)
    lo = max(cam_col, first_col)
    hi = min(cam_col + SCREEN_TILES - 1, last_col, WORLD_W_TILES - 1)
    mismatches = []
    for col in range(lo, hi + 1):
        for row in range(WORLD_H_TILES):
            got = _vram_word(runner, col, row) & 0x3FF
            want = _authored_word(level, col, row) & 0x3FF
            if got != want:
                mismatches.append((col, row, got, want))
    assert not mismatches, (
        f"idle-full: {len(mismatches)} VRAM cells differ from authored "
        f"(first 8: {mismatches[:8]}; cam_col={cam_col} ring=[{first_col},{last_col}])"
    )


def test_no_black_band_in_resident_window(runner, level):
    """Structural anti-black-band check: across the CURRENT visible window there
    must be a healthy population of NON-AIR (ground/platform) tiles — a black
    band or a wiped tilemap would read as all-AIR rows. (Issue #126 class:
    streaming that lands bytes but blanks a scanline.) Phase-agnostic: reads the
    window wherever the camera currently is (the level has a ground baseline in
    every 32-col span)."""
    cam_col = _u16(runner, DBG_CAM_COL)
    first_col = _u16(runner, DBG_FIRST_COL)
    last_col = _u16(runner, DBG_LAST_COL)
    lo = max(cam_col, first_col)
    hi = min(cam_col + SCREEN_TILES - 1, last_col, WORLD_W_TILES - 1)
    nonzero = 0
    for col in range(lo, hi + 1):
        for row in range(WORLD_H_TILES):
            if (_vram_word(runner, col, row) & 0x3FF) != 0:
                nonzero += 1
    # The level has a multi-row ground baseline; expect well over one full row
    # of non-AIR tiles in any 32-col window.
    assert nonzero >= 40, (
        f"resident window has only {nonzero} non-AIR tiles — likely a wiped "
        f"tilemap / black band (cam_col={cam_col})"
    )
