"""
test_bg_stream2d.py — proof test for the Mode-1 normal-BG 2-AXIS (horizontal
                      column + vertical row) streaming substrate (Sprint S2a).

TEST SURFACE DECLARATION (CLAUDE.md "Indirect-Evidence Tests"):
  - Feature under test: 2-axis BG1 tilemap streaming on a 64x64 hardware tilemap
    (BG1SC=$5B). HORIZONTAL = engine/bg_stream.asm column producer (2-axis mode:
    a column spans 64 rows, emitting a rows-0..31 sub-slot + a rows-32..63 sub-
    slot). VERTICAL = engine/bg_stream_row.asm row producer (stages the 64
    visible cols into a WRAM buffer, queues 2 page-aligned sub-slots). Both
    drain via the engine/nmi_handler.asm STREAM_PENDING (column, stride-32) and
    STREAM_ROW_PENDING (row, stride-1) VBlank DMAs. Driven by a scripted camera
    over a WIDE AND TALL authored Four Seasons level (128x128 tiles), wired via
    lib/macros/sf_stream.inc (sf_stream_init / sf_stream_row_init /
    sf_stream_set_cam2 / sf_stream_tick2).
  - OUTPUT region read: the BG1 VRAM TILEMAP words in the resident 64x64 ring
    (VRAM word $5800-$67FF, 4 sub-pages). For each visible world (col,row) we
    read the ring-slot VRAM word and compare it tile-for-tile to the authored
    level ground-truth (tests/fixtures/bg_stream2d/level_flat_row.bin, row-major).
    This is the rendered destination, NOT a proxy variable.
  - State cycles exercised: RIGHT (pan east into new horizontal content past the
    64-col ring), DOWN (pan south into new vertical content past the 64-row
    ring), LEFT (reverse-X: horizontal trailing edge must repopulate), UP
    (reverse-Y: vertical trailing edge must repopulate), and IDLE (no streaming;
    the FULL window — both axes — must be the authored content at rest). All 5.

Position-identifiability (cam_x/y, STREAM_CAM_COL/ROW, FIRST/LAST) is mirrored to
$7E:E010+ as a HIDDEN/DEBUG surface to map the test. The VISIBLE level is the
authored Four Seasons art.
"""
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROM = os.path.join(HERE, "..", "build", "bg_stream2d_test.sfc")
LEVEL_ROW = os.path.join(HERE, "fixtures", "bg_stream2d", "level_flat_row.bin")

# World geometry (mirrors tools/level_pipeline_bg.py --tall / bg_stream_world.inc).
WORLD_W_TILES = 128
WORLD_H_TILES = 128
ROW_BYTES = WORLD_W_TILES * 2          # 256 bytes/row (row-major)
SCREEN_W_TILES = 32                    # 256px visible window
SCREEN_H_TILES = 28                    # 224px visible window

# Debug region mirrors ($7E:E000 + offset).
DBG_HEARTBEAT = 0xE010
DBG_CAMX = 0xE012
DBG_CAMY = 0xE014
DBG_PHASE = 0xE016
DBG_CAM_COL = 0xE018
DBG_CAM_ROW = 0xE01A
DBG_FIRST_COL = 0xE01C
DBG_FIRST_ROW = 0xE01E
DBG_LAST_COL = 0xE020
DBG_LAST_ROW = 0xE022
DBG_ACTIVE = 0xE024
DBG_ROW_ACT = 0xE026

PHASE_RIGHT, PHASE_DOWN, PHASE_LEFT, PHASE_UP, PHASE_IDLE = 0, 1, 2, 3, 4


@pytest.fixture(scope="module")
def runner():
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "infrastructure", "test_harness"))
    from mesen_runner import MesenRunner
    r = MesenRunner()
    assert os.path.exists(ROM), f"ROM not built: {ROM} (run `make build/bg_stream2d_test.sfc`)"
    r.load_rom(ROM, run_seconds=0.05)
    yield r
    r.stop()


@pytest.fixture(scope="module")
def level():
    with open(LEVEL_ROW, "rb") as fh:
        return fh.read()


def _u16(runner, addr):
    from mesen_runner import MemoryType
    b = runner.read_bytes(MemoryType.SnesWorkRam, addr, 2)
    return b[0] | (b[1] << 8)


def _authored(level, col, row):
    """Authored tilemap word at (world col, row), ROW-major."""
    off = row * ROW_BYTES + col * 2
    return level[off] | (level[off + 1] << 8)


def _vram_word(runner, world_col, world_row):
    """BG1 VRAM tilemap word for (world_col, world_row) at its 64x64 RING SLOT.
    cs = col & $3F, rs = row & $3F; page = SC0/SC1/SC2/SC3 per (cs>=32, rs>=32)."""
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


def _advance_to(runner, target_phase, *, min_col=None, max_col=None,
                min_row=None, max_row=None, timeout=1400):
    """Run frames until the ROM reports target_phase (+ optional cam window)."""
    for _ in range(timeout):
        runner.run_frames(2)
        if _u16(runner, DBG_PHASE) != target_phase:
            continue
        cc = _u16(runner, DBG_CAM_COL)
        cr = _u16(runner, DBG_CAM_ROW)
        if min_col is not None and cc < min_col:
            continue
        if max_col is not None and cc > max_col:
            continue
        if min_row is not None and cr < min_row:
            continue
        if max_row is not None and cr > max_row:
            continue
        return cc, cr
    raise AssertionError(f"never reached phase {target_phase} in window")


def _window_bounds(runner, inset_col=1, inset_row=1):
    """Resident-visible window [col_lo,col_hi] x [row_lo,row_hi], inset by N on
    each moving edge (the actively-streaming edge has an inherent 1-frame queue
    lag; the IDLE test verifies edges with no inset)."""
    cc = _u16(runner, DBG_CAM_COL)
    cr = _u16(runner, DBG_CAM_ROW)
    fc = _u16(runner, DBG_FIRST_COL)
    fr = _u16(runner, DBG_FIRST_ROW)
    lc = _u16(runner, DBG_LAST_COL)
    lr = _u16(runner, DBG_LAST_ROW)
    col_lo = max(cc, fc) + inset_col
    col_hi = min(cc + SCREEN_W_TILES - 1, lc, WORLD_W_TILES - 1) - inset_col
    row_lo = max(cr, fr) + inset_row
    row_hi = min(cr + SCREEN_H_TILES - 1, lr, WORLD_H_TILES - 1) - inset_row
    return col_lo, col_hi, row_lo, row_hi


def _assert_window(runner, level, label, inset_col=1, inset_row=1):
    col_lo, col_hi, row_lo, row_hi = _window_bounds(runner, inset_col, inset_row)
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
    assert checked > 0
    assert not mismatches, (
        f"{label}: {len(mismatches)}/{checked} VRAM tilemap cells DIFFER from "
        f"authored (stale/garbage strip). First 8: {mismatches[:8]}"
    )


# =============================================================================
# Boot / liveness
# =============================================================================
def test_boot_magic_and_heartbeat(runner):
    from mesen_runner import MemoryType
    runner.run_frames(10)
    magic = bytes(runner.read_bytes(MemoryType.SnesWorkRam, 0xE000, 4))
    assert magic == b"SFDB", f"debug magic not SFDB: {magic!r}"
    hb0 = _u16(runner, DBG_HEARTBEAT)
    runner.run_frames(10)
    assert _u16(runner, DBG_HEARTBEAT) > hb0, "heartbeat did not advance"


def test_both_axes_channel_active(runner):
    """Column producer allocated a DMA channel (STREAM_ACTIVE=1) and the row
    producer mirrored it (STREAM_ROW_ACTIVE=1) — without it nothing streams."""
    assert _u16(runner, DBG_ACTIVE) == 1, "STREAM_ACTIVE != 1 (no channel)"
    assert _u16(runner, DBG_ROW_ACT) == 1, "STREAM_ROW_ACTIVE != 1"


# =============================================================================
# HORIZONTAL — RIGHT pan into new authored content past the 64-col ring
# =============================================================================
def test_right_window_matches_past_ring(runner, level):
    """Deep east pan PAST the 64-column resident ring — these columns are only
    correct if they STREAMED in (boot loaded cols 0..63). Core forward-X proof,
    AND it proves the 2-axis column path fills the full 64 rows (rows 0..31 +
    the rows-32..63 sub-slot)."""
    cc, cr = _advance_to(runner, PHASE_RIGHT, min_col=58, max_col=90)
    assert cc > 32, f"camera never panned past the ring (cam_col={cc})"
    _assert_window(runner, level, "right-deep")


# =============================================================================
# VERTICAL — DOWN pan into new authored content past the 64-row ring
# =============================================================================
def test_down_window_matches_past_ring(runner, level):
    """Deep south pan PAST the 64-row resident ring — these rows are only
    correct if the VERTICAL producer streamed them in. Core forward-Y proof.
    Larger row inset (4): the vertical leading edge has a multi-row queue lag
    under continuous 1-row/frame motion (the staging copy + 2-sub-slot DMA per
    row); the IDLE test verifies the whole window with no inset once settled."""
    cc, cr = _advance_to(runner, PHASE_DOWN, min_row=40)
    assert cr > 32, f"camera never panned past the row ring (cam_row={cr})"
    _assert_window(runner, level, "down-deep", inset_col=1, inset_row=4)


# =============================================================================
# REVERSE-X / REVERSE-Y — deep-region traversal (S2a-fix: now byte-perfect)
# =============================================================================
# The S2a substrate's reverse-traversal deep-region corruption is FIXED (sprint
# claude/streaming-rail-mode1-s2a-fix). Four root causes were isolated with
# MesenRunner + synthetic unique-per-cell level data (decoding the world row
# stored in each VRAM ring slot):
#   1. engine/bg_stream_row.asm _bsr_slot_x: `and #$00FF` ran in A8, so it
#      assembled as a 1-byte immediate (`29 FF`) that did NOT clear the
#      accumulator high byte; the subsequent I16 `tax` transferred stale-B<<8 |
#      pending*5, scattering queue-slot stores to garbage addresses.
#   2. engine/bg_stream_row.asm _bsr_row_vaddr_a: cached scratch in $A9/$AB,
#      which alias the live 16-bit stage-base pointer $AA-$AB (an A16 `sta $A9`
#      spills into $AA); the queued DMA source pointer was corrupted so the row
#      DMA read engine state, not the staging buffer.
#   3. The fix above stashes the stage base in alias-immune $B6 for both
#      sub-slots' SRC.
#   4. engine_state.inc: STREAM_ROW_STAGE_IDX ($0840) sat INSIDE the
#      double-buffer span ($0760-$085F); staging an odd (idx=1) row's col-slot
#      48 word landed on $0840 and corrupted the index mid-stage. Relocated to
#      $0860.
#   5. engine/bg_stream.asm (column producer): the 2-axis column stream wrote
#      world rows 0..63 regardless of vertical scroll, so reverse-X (LEFT) at a
#      deep cam_y overwrote the deep page (the reverse-Y / UP failure). Source
#      base now += STREAM_FIRST_ROW*2 so a column fills the resident vertical
#      window [first_row..first_row+63].
# These assert the RENDERED OUTPUT (BG1 VRAM tilemap words) vs the authored
# ground-truth at the reverse-traversed world position — not a proxy variable.
def test_left_reverse_window_matches(runner, level):
    """Pan WEST after the right edge. The ring's trailing (left) edge must
    repopulate with the authored columns — the 'walk back left' bug class."""
    cc, cr = _advance_to(runner, PHASE_LEFT, max_col=70)
    _assert_window(runner, level, "left-reverse")


# =============================================================================
# REVERSE-Y — UP pan; vertical trailing edge must repopulate
# =============================================================================
def test_up_reverse_window_matches(runner, level):
    """Pan NORTH after the bottom edge. The ring's trailing (top) edge must
    repopulate with the authored rows — the vertical 'walk back up' bug class."""
    cc, cr = _advance_to(runner, PHASE_UP, max_row=70)
    _assert_window(runner, level, "up-reverse", inset_col=1, inset_row=4)


# =============================================================================
# IDLE — full window (BOTH axes, NO inset) must be the authored level at rest
# =============================================================================
def test_idle_full_window_matches(runner, level):
    """In the idle phase the camera holds still and nothing streams; the FULL
    visible window — INCLUDING the edge columns AND rows (no inset) — must be
    the authored content. This is the at-rest 2-axis invariant: every cell the
    user sees, no stale overwrite, no black band. Settles first so all pending
    columns AND rows have drained."""
    cc, cr = _advance_to(runner, PHASE_IDLE)
    runner.run_frames(40)
    assert _u16(runner, DBG_CAM_COL) == cc, "camera moved during idle"
    assert _u16(runner, DBG_CAM_ROW) == cr, "camera moved during idle"
    _assert_window(runner, level, "idle-full", inset_col=0, inset_row=0)


def test_no_black_band_in_resident_window(runner, level):
    """Structural anti-black-band check (issue #126 class): across the current
    visible window there must be a healthy population of NON-AIR tiles. A wiped
    tilemap / black band reads as all-AIR. Phase-agnostic."""
    col_lo, col_hi, row_lo, row_hi = _window_bounds(runner, 0, 0)
    nonzero = 0
    for col in range(col_lo, col_hi + 1):
        for row in range(row_lo, row_hi + 1):
            if (_vram_word(runner, col, row) & 0x3FF) != 0:
                nonzero += 1
    assert nonzero >= 40, (
        f"resident window has only {nonzero} non-AIR tiles — likely a wiped "
        f"tilemap / black band"
    )
