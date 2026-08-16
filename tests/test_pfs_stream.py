"""pfs_stream — 2-axis leading-edge streaming for a normal-BG 64x64 ring.

THE OUTPUT REGION IS BG1 VRAM, AND EVERY ASSERTION HERE READS IT. A tilemap
streamer's product is tilemap words in VRAM; nothing in this file asks a
camera variable whether streaming happened. That distinction is not academic —
the predecessor project shipped exactly that proxy twice (its),
where `cam_x > 1024` "proved" a streaming update while two independent bugs
sailed through, and playtesting found both by looking at the screen.

The oracle is the AUTHORED LEVEL, reached through the PPU's own four-page
addressing, which is the one piece of arithmetic the feature and the test do
NOT share:

    VRAM(col,row) = base + (col>=32 ? $400 : 0) + (row>=32 ? $800 : 0)
                         + (row & 31)*32 + (col & 31)

`_vram_word` below is that formula written straight out of the hardware
reference. `pfs_stream.asm` never computes it that way: it derives a pair of
page-aligned VMADD bases and lets the DMA's VMAIN stride walk between them. So
a page-addressing mistake in the feature cannot be mirrored by a matching
mistake here.

The level itself comes from `tools/gen_platformer_stream_assets.py`, whose own
layout is byte-checked against the reference's committed blobs in
`tests/test_platformer_stream_assets.py`. This file shares the level's
DEFINITION with the feature and shares none of its ADDRESSING — the same split
`tests/test_col_map.py` draws between its T1 and T2 halves, and for the same
reason.

WHAT IS DRIVEN, and it is the whole state cycle:

  T1  the arm — all 4096 ring slots, from one forced-blank fill
  T2  DOWN and UP     (the fall shaft and the climb back)
  T3  RIGHT and LEFT  (the runway east, then the reverse west)
  T4  IDLE            (a stopped camera holds the window)
  T5  DIAGONAL        (both axes staging in the same frame)
  T6  the ring wrap   (driven far enough that every slot recycles)
  T7  the deferred drain — the tick/drain guard, forced
  T8  the [init] zero contract, read back out of the declared claims
  T10 the WORD PORT — a staged line with non-zero tilemap high bytes
  T9  the per-line staging cost, MEASURED

T10 exists because the ORACLE HAS A BLIND SPOT the level cannot close: the
authored level authors palette group 0, so every tilemap word's high byte is
zero and no assertion against it can distinguish a correct word-port stream
from one that gets the high byte wrong. a later review planted exactly that (clear
VMAIN bit 7, so the address advances on the low-byte write) and all nine tests
passed. T10 closes it by streaming a line
whose source has non-zero high bytes — a synthetic 128-word ROM line the probe
binds as a third blob, staged and drained entirely by the shipped kernel. It
covers BOTH carriers of a tilemap word: the staging MVN out of ROM and the
drain's word port. Its first version poisoned the staged buffer AFTER the
kernel returned and so covered only the drain; a plant making the staging
discard every high byte passed 11/11 against it. It runs after T8
and before T9 because it, too, perturbs the ring.

T2/T3 exist as pairs on purpose. A streaming test that only walks one way
locks that direction and ships the other broken. That is a recorded defect
here, not a hypothetical: a wall-collision bug survived a long time because no
test ever walked left off the right-edge clamp.

THE FULL-WINDOW INVARIANT IS A STOPPED-CAMERA CLAIM. While the camera moves,
VRAM trails it by the staging + VBlank-drain lag BY DESIGN — the tick stages
this frame's entering edges and the NMI drains them at the next VBlank. Every
window assertion below therefore comes to rest first, exactly as
`mz_drive.assert_window_exact` does for the Mode 7 ring.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam

# The geometry, from engine/features/pfs_stream/pfs_stream.asm's own constants.
# Written here rather than parsed so a change to either side has to be a
# deliberate change to BOTH.
RING = 64            # ring dimension, tiles (both axes)
TILES = 128          # world dimension, tiles (both axes)
HALF = 32            # one hardware page dimension
BACK = 16            # tiles of window kept behind the camera

# The camera clamps the rail applies: a 256x224 screen inside a 1024x1024 px
# world. The probe does not clamp — the streamer is a torus and does not need
# to — so the driver below clamps, which is what keeps the drive legs inside
# the coordinates a player could actually produce.
CAM_X_MAX = TILES * 8 - 256
CAM_Y_MAX = TILES * 8 - 224

SPAWN_X, SPAWN_Y = 272, 136        # the shaft mouth (pfs_world.inc's spawn)

CMD_INIT, CMD_ARM, CMD_FRAME, CMD_BENCH, CMD_CONTROL = 1, 2, 3, 4, 5
CMD_HOLD = 6            # tick, then hold PFS_BUSY up so the drain must defer
CMD_SYNTH = 7           # stage a line out of a SYNTHETIC source with high bytes
# probe_pfs_stream.asm's `pfs_synth_line`: word k of that 128-word ROM line is
# (SYNTH_HI + k) << 8 | (SYNTH_LO + k). All 128 high bytes differ, all 128 low
# bytes differ, and no word's two bytes are equal — so a line staged or drained
# one word out is a mismatch in EVERY word, and a byte-swapped word is one too.
SYNTH_HI = 0x40
SYNTH_LO = 0x01


def _synth_word(k):
    """The synthetic source line's word at world index k (0..127).

    Written here rather than read out of the ROM on purpose: the fixture and
    the oracle have to be two independent statements of the pattern, or the
    assertion is the ROM compared against itself.
    """
    return ((SYNTH_HI + k) << 8) | (SYNTH_LO + k)

# One NTSC frame in master clocks — the denominator for the measured cost.
FRAME_MC = 357368
# FastROM master clocks per CPU cycle.
MC_PER_CYCLE = 8


def _load_tool(name):
    spec = importlib.util.spec_from_file_location(
        name, SUPERFORGE / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    """The isolated kernel: probe_pfs.sfc, which .includes the SHIPPED
    engine/features/pfs_stream/pfs_stream.asm rather than a copy of it.

    Driving the streamer here rather than through the rail is deliberate and
    it is what let the two be built in parallel — but it is also the better
    test surface. The rail's camera is a consequence of physics, so probing a
    coordinate through it means teleporting the player; the probe takes the
    camera as a parameter, which is the whole of the streamer's interface. The
    identical argument is written out in tests/test_col_map.py's fixture,
    where probing shared game state cost 60 stale coordinates out of 512.
    """
    r = subprocess.run(["make", "probe-pfs"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make probe-pfs failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads(
        (SUPERFORGE / "build" / "pfs_map" / "symbol_map.json").read_text())
    syms = {p["sym"]: p["start"]
            for p in jmap["scenes"]["probe"]["placements"] + jmap["globals"]}
    gen = _load_tool("gen_platformer_stream_assets")
    # tile_words[row][col] — the authored level, row-major, exactly what the
    # two blobs are two orderings OF.
    tile_words, _solid = gen.expand_to_bg_tiles(gen.author_level_seasons())
    runner = MesenRunner()
    runner.boot_rom(str(SUPERFORGE / "build" / "probe_pfs.sfc"), frames=30)
    runner.debug_break()
    yield runner, syms, tile_words
    runner.stop()


# --- driving the probe ------------------------------------------------------

def _cmd(probe, n, p=0, p2=0, frames=4):
    """Issue one probe command and wait, in EMULATED frames, for it to report.

    `seq` is the completion counter, not the assertion — every assertion in
    this file is on VRAM. It is here so a command that silently failed to run
    is reported as itself rather than as a stale window ten lines later.
    """
    runner, syms, _ = probe
    s0 = runner.read_u16(WR, syms["US_SEQ"])
    runner.write_bytes(WR, syms["US_PARAM"], int(p).to_bytes(2, "little"))
    runner.write_bytes(WR, syms["US_PARAM2"], int(p2).to_bytes(2, "little"))
    runner.write_bytes(WR, syms["US_CMD"], bytes([n]))
    runner.frame_step(frames)
    assert runner.read_u16(WR, syms["US_SEQ"]) != s0, (
        f"the probe never completed command {n} ({p},{p2})")


def _arm(probe, px, py):
    """Scene enter: init, camera, and the whole ring filled under forced
    blank. 40 frames because the fill is 64 columns x 2 DMAs, all of it in one
    command."""
    _cmd(probe, CMD_ARM, px, py, frames=40)


def _vram_word(base, sc, sr):
    """The PPU's 64x64 addressing, straight from the hardware reference.

    This is the arithmetic the feature does NOT do — pfs_stream derives two
    page-aligned VMADD bases and lets VMAIN stride between them — which is
    what keeps this from being a tautology.
    """
    return (base
            + (0x400 if sc >= HALF else 0)      # SC1/SC3, horizontally
            + (0x800 if sr >= HALF else 0)      # SC2/SC3, vertically
            + (sr & (HALF - 1)) * HALF
            + (sc & (HALF - 1)))


def _window_mismatches(probe, px, py):
    """Every one of the 4096 ring slots against the authored level.

    Reads the whole tilemap region out of VRAM once and walks the 64x64 window
    the camera at (px, py) implies. A slot is addressed by `world & 63`, which
    is what the PPU does with the scroll registers — so this covers the ring
    exactly, with no slot visited twice and none missed.
    """
    runner, syms, tile_words = probe
    base = syms["ES_V_PFS_MAP"]
    vram = runner.read_bytes(VR, base * 2, RING * RING * 2 * 4)
    tx, ty = px >> 3, py >> 3
    bad = []
    for wr_ in range(ty - BACK, ty - BACK + RING):
        for wc in range(tx - BACK, tx - BACK + RING):
            off = (_vram_word(base, wc & (RING - 1), wr_ & (RING - 1))
                   - base) * 2
            got = vram[off] | (vram[off + 1] << 8)
            want = tile_words[wr_ & (TILES - 1)][wc & (TILES - 1)]
            if got != want:
                bad.append((wc & (TILES - 1), wr_ & (TILES - 1), got, want))
    return bad


def _assert_window_exact(probe, px, py, tag):
    """THE streaming invariant — and it is a STOPPED-camera claim.

    Only meaningful at rest: while the camera moves, VRAM trails it by the
    staging + VBlank-drain lag by design. Every caller below has finished its
    leg before asking. The three-frame settle is the same drain grace
    mz_drive.assert_window_exact takes for the Mode 7 ring.
    """
    runner, _syms, _ = probe
    runner.frame_step(3)
    bad = _window_mismatches(probe, px, py)
    assert not bad, (
        f"{tag}: cam=({px >> 3},{py >> 3}) — {len(bad)}/{RING * RING} ring "
        f"slots disagree with the authored level; first 5 "
        f"(world_col, world_row, got, want): {bad[:5]}")


def _slot_world(start, slot):
    """The world line in the resident window [start, start+RING) that lands in
    ring slot `slot`. The ring is addressed `world & 63`, so exactly one world
    line per window occupies each slot."""
    return start + ((slot - start) % RING)


def _drive(probe, px, py, dx, dy, steps):
    """Walk the camera one frame at a time, clamped to the rail's world.

    One `_cmd(CMD_FRAME)` is one game frame: set_cam, tick, and a `wai` for the
    VBlank that drains what the tick staged. So this really is N frames of
    play, not a teleport — which is the only way the leading-edge clamp and the
    per-frame slot budget get exercised at all.
    """
    for _ in range(steps):
        px = max(0, min(CAM_X_MAX, px + dx))
        py = max(0, min(CAM_Y_MAX, py + dy))
        _cmd(probe, CMD_FRAME, px, py, frames=2)
    return px, py


# =============================================================================
# T1 — THE ARM. One forced-blank fill, all 4096 slots.
# =============================================================================

def test_t1_arm_fills_every_ring_slot_from_the_authored_level(probe):
    """The boot picture, tile for tile.

    It matters that this passes for the same reason it matters that T2-T6 do:
    the arm runs the PER-FRAME staging kernel 64 times rather than a separate
    bulk-upload path, so a bug in the addressing cannot hide behind a correct
    boot frame — and a correct boot frame cannot hide one either.
    """
    _arm(probe, SPAWN_X, SPAWN_Y)
    _assert_window_exact(probe, SPAWN_X, SPAWN_Y, "armed at the spawn")


# =============================================================================
# T2/T3 — MOTION, BOTH DIRECTIONS ON BOTH AXES.
# =============================================================================

def test_t2_the_vertical_axis_streams_down_and_back_up(probe):
    """Fall, then climb. BOTH directions, in one test, so neither can be
    green by accident of the other having run first.

    4 px/frame is the rail's terminal fall (SF_MAX_FALL) — the fastest the
    vertical axis ever moves, and 0.5 tile/frame against a clamp of 2.
    """
    px, py = SPAWN_X, SPAWN_Y
    _arm(probe, px, py)
    px, py = _drive(probe, px, py, 0, 4, 60)          # down the shaft
    _assert_window_exact(probe, px, py, "after falling 240 px")
    px, py = _drive(probe, px, py, 0, -4, 45)         # and back up
    _assert_window_exact(probe, px, py, "after climbing 180 px back")


def test_t3_the_horizontal_axis_streams_east_and_back_west(probe):
    """The runway, then the reverse.

    The westbound leg is the one that matters most and it is the one a
    single-direction test omits: the recorded bug was a stale ring
    left edge that only a leftward walk off the right-hand clamp could reach,
    and it survived a long time because nothing ever walked back.
    """
    px, py = SPAWN_X, SPAWN_Y
    _arm(probe, px, py)
    px, py = _drive(probe, px, py, 4, 0, 90)          # east, past the ring
    _assert_window_exact(probe, px, py, "after running 360 px east")
    px, py = _drive(probe, px, py, -4, 0, 120)        # west, back through it
    _assert_window_exact(probe, px, py, "after running 480 px west")


# =============================================================================
# T4 — IDLE. The third state, and the one nothing forces you to think about.
# =============================================================================

def test_t4_a_stopped_camera_holds_the_window(probe):
    """Frames in which the camera does not move must stage nothing and must
    change nothing.

    A streamer that re-stages on a still camera would pass every moving test
    in this file while burning VBlank bytes forever; one that corrupts the
    ring on a zero delta would fail here and nowhere else. The assertion is
    still the full window, read twice with 20 idle frames between.
    """
    px, py = SPAWN_X, SPAWN_Y
    _arm(probe, px, py)
    px, py = _drive(probe, px, py, 3, 2, 30)
    _assert_window_exact(probe, px, py, "before the idle hold")
    before = probe[0].read_bytes(VR, probe[1]["ES_V_PFS_MAP"] * 2,
                                 RING * RING * 2 * 4)
    px, py = _drive(probe, px, py, 0, 0, 20)          # 20 frames, no movement
    _assert_window_exact(probe, px, py, "after 20 idle frames")
    after = probe[0].read_bytes(VR, probe[1]["ES_V_PFS_MAP"] * 2,
                                RING * RING * 2 * 4)
    assert before == after, (
        "the ring's VRAM changed across 20 frames with a stationary camera")


# =============================================================================
# T5 — BOTH AXES IN THE SAME FRAME.
# =============================================================================

def test_t5_diagonal_motion_stages_both_axes_in_one_frame(probe):
    """The worst per-frame load, and the one place the two producers'
    interleaving is exercised.

    A diagonal frame stages a row AND a column, out of two DIFFERENT blobs,
    into one shared slot pool, in the same frame. That interleaving is what
    this test covers, and it covers it at every one of 4096 slots.

    WHAT IT DOES **NOT** SEE, corrected from an earlier version of this
    docstring which claimed the opposite ("the row must use the horizontal
    window the ring actually holds rather than the camera's … this test reads
    every slot, so it sees it"): it does not. a later review planted both
    halves of that claim — swapping the two walks, and making pfs_stage_row
    span CAM_TX's window instead of LAST_TX's — and this test passed both
    times. The reason is that every leg here moves both axes, so both walks
    complete, and whichever runs second overwrites exactly the line the first
    got wrong. The two orders are mutually self-correcting; the divergence only
    exists when the OTHER axis is clamped or deferred and performs no
    correction. **T11 reaches that state** and the CAM_TX plant fails there. A
    docstring that overstates its reach is the same defect class as a proxy
    assertion, one layer up.
    """
    px, py = SPAWN_X, SPAWN_Y
    _arm(probe, px, py)
    px, py = _drive(probe, px, py, 4, 4, 80)
    _assert_window_exact(probe, px, py, "after 80 diagonal frames")
    px, py = _drive(probe, px, py, -4, -4, 80)
    _assert_window_exact(probe, px, py, "after 80 reverse-diagonal frames")


# =============================================================================
# T6 — THE RING WRAP. Where position-wrapping bugs live.
# =============================================================================

def test_t6_the_ring_wraps_on_both_axes(probe):
    """Drive far enough that every ring slot is recycled, on each axis.

    A staged line lands at `world & 63`, never at a sequential buffer index —
    which looks identical for as long as the window happens to start at slot
    0 and diverges the moment it does not. So this walks a full 64 tiles
    (512 px) on each axis from a slot-aligned start, which retires every slot
    exactly once and puts the window start at all 64 phases along the way.

    The intermediate rests are the point: a wrap bug that only shows for part
    of a lap would be invisible if the only assertion were at the end.
    """
    # 512 px = tile 64: a slot-aligned camera, so the walk below starts at
    # window phase 48 and sweeps through every one of them.
    px, py = 512, 512
    _arm(probe, px, py)
    _assert_window_exact(probe, px, py, "armed slot-aligned")
    for leg in range(4):
        px, py = _drive(probe, px, py, -4, 0, 32)     # 128 px = 16 tiles
        _assert_window_exact(probe, px, py, f"x-wrap leg {leg}")
    px, py = 512, 512
    _arm(probe, px, py)
    for leg in range(4):
        px, py = _drive(probe, px, py, 0, 4, 32)
        _assert_window_exact(probe, px, py, f"y-wrap leg {leg}")


# =============================================================================
# T7 — THE DEFERRED DRAIN. The guard that only matters on a timing edge.
# =============================================================================

def test_t7_a_drain_deferred_by_the_busy_guard_loses_nothing(probe):
    """The tick runs on the main thread and the drain runs in the NMI, so they
    interleave for real — and a slot is only well-defined once its meta, its
    buffer AND its count have all landed. `pfs_stream` raises PFS_BUSY across
    the staging window and the drain defers on it.

    A host cannot schedule that edge, so the probe manufactures it: cmd 6 ticks
    normally, re-raises the flag the tick just lowered, and lets a VBlank pass.
    Both halves are then assertable ON VRAM:

      1. while the flag is up, the drain writes NOTHING — the ring still holds
         the PREVIOUS window, entering line and all;
      2. when the host clears it, the pending slots go out and the window is
         exact. The staged line is not lost, because the tick never resets the
         counters — only the drain does.

    The check is aimed at ONE ring slot rather than the whole window, and the
    oracle is asserted to be non-vacuous first: if the entering column and the
    column it displaces ever became identical (both all-air, say), the test
    would pass while proving nothing, so it fails loudly instead.
    """
    runner, syms, tile_words = probe
    base = syms["ES_V_PFS_MAP"]
    # A start position whose entering column has structure: the bedrock floor
    # runway is at world rows 120..127 and the terraces above it are not empty.
    px, py = 480, 800
    _arm(probe, px, py)
    _assert_window_exact(probe, px, py, "armed before the hold")

    new_px = px + 8                       # exactly one tile east
    new_tx = new_px >> 3
    entering = (new_tx + RING - 1 - BACK) & (TILES - 1)   # the new window's last
    displaced = (entering - RING) & (TILES - 1)           # what its slot holds now
    slot = entering & (RING - 1)
    ty = py >> 3
    rows = [(wr_ & (TILES - 1))
            for wr_ in range(ty - BACK, ty - BACK + RING)]
    want_old = [tile_words[r][displaced] for r in rows]
    want_new = [tile_words[r][entering] for r in rows]
    assert want_old != want_new, (
        f"the oracle says world columns {displaced} and {entering} are "
        f"identical over this window, so this test would pass without the "
        f"drain doing anything — move the probe position")

    def read_slot_column():
        vram = runner.read_bytes(VR, base * 2, RING * RING * 2 * 4)
        out = []
        for wr_ in range(ty - BACK, ty - BACK + RING):
            off = (_vram_word(base, slot, wr_ & (RING - 1)) - base) * 2
            out.append(vram[off] | (vram[off + 1] << 8))
        return out

    _cmd(probe, CMD_HOLD, new_px, py, frames=4)
    runner.frame_step(3)                  # more VBlanks, all of them deferring
    assert read_slot_column() == want_old, (
        "the drain ran while PFS_BUSY was raised — it must defer, because the "
        "slot table it would be reading may be half-published")

    runner.write_bytes(WR, syms["ES_PFS_NMI"], bytes([0]))   # PFS_BUSY down
    runner.frame_step(3)
    assert read_slot_column() == want_new, (
        "the deferred slot never reached VRAM — a deferral must cost a frame "
        "of lag, not a staged line")
    _assert_window_exact(probe, new_px, py, "after the deferred drain caught up")


# =============================================================================
# T8 — THE [init] zero CONTRACT, read back rather than declared.
# =============================================================================

def test_t8_init_really_zeroes_the_claims_it_declares(probe):
    """`[init] zero` HAS NO GATE — so this is the gate.

    The allocator emits the contract as a comment and nothing checks anybody
    honoured it. `mosaic` shipped declaring it with no code behind it, and only
    Mesen's random power-on RAM caught the JSR through a swap pointer made of
    DRAM noise. So the probe deliberately does NOT pre-zero these claims in its
    boot block: whatever is in them when cmd 1 runs is either what
    `pfs_stream_init` put there or power-on garbage.

    Reading the DECLARED bytes is reading the feature's output region — the
    same re-pointing of CLAUDE.md rule 2 that tests/test_col_map.py's header
    sets out for a feature whose product is a value rather than a picture.
    """
    runner, syms, _ = probe
    # Scribble first, so a passing read cannot be power-on luck: the routine
    # has to actually clear something.
    runner.write_bytes(WR, syms["ES_PFS_HOT"], b"\xA5" * 24)
    runner.write_bytes(WR, syms["ES_PFS_NMI"], b"\xA5" * 2)
    _cmd(probe, CMD_INIT, frames=3)
    hot = runner.read_bytes(WR, syms["ES_PFS_HOT"], 24)
    nmi = runner.read_bytes(WR, syms["ES_PFS_NMI"], 2)
    assert hot == b"\x00" * 24, (
        f"pfs_hot is declared `[init] zero` and pfs_stream_init left it "
        f"{hot.hex()}")
    assert nmi == b"\x00" * 2, (
        f"pfs_nmi is declared `[init] zero` and pfs_stream_init left it "
        f"{nmi.hex()}")


# =============================================================================
# T11 — THE DECLARED WORST FRAME, and the state where LAST is not CAM.
# =============================================================================

def test_t11_a_three_tile_jump_fills_four_slots_and_the_clamp_does_not_snap(
        probe):
    """Four slots in one frame, the clamp branch taken on both axes, and the
    only state in which the row producer's LAST_TX-not-CAM_TX choice is
    observable. a later review and half of its F2.

    EVERY OTHER TEST IN THIS FILE MOVES AT MOST 4 px/frame — half a tile — so
    col_cnt and row_cnt never exceed 1, at most two of the four slots are ever
    used, and the clamp branches are never taken. Clamping `_pfs_slot_base`'s
    n to {0,1}, which makes slots 2-3 and meta records 2-3 unreachable, passed
    9/9. `vblank_bytes_per_frame = 512`
    described a frame nothing produced.

    A 3-tile jump on both axes in ONE frame produces it: the row walk stages 2
    and stops at the clamp, the column walk stages 2 and stops, so n reaches 3
    — four slots, eight sub-transfers, 512 B, which is the declared worst
    frame exactly. It is deliberately super-physical (the rail's worst real
    displacement is 1 tile/frame/axis); the point is to reach a DECLARED bound,
    not a reachable one.

    AND IT IS THE STATE F2 NEEDS. `pfs_stage_row` spans the ring's 64 columns
    and takes its horizontal window from LAST_TX rather than CAM_TX. With both
    walks completing, that choice is invisible — whichever axis runs second
    overwrites exactly the line the first got wrong, so CAM and LAST are
    mutually self-correcting and a later review plants passed 9/9. Here the
    column walk STOPS AT THE CLAMP one tile short of the camera, so it performs
    no correction, and a row staged over CAM_TX's window leaves ring slot
    (LAST_TX - BACK) & 63 holding a world column that is not in the window at
    all.

    Three assertions, all on VRAM:
      1. the ring holds LAST's window (camera - 1 tile per axis) — the clamp
         held, all four staged lines landed, and the row used LAST_TX;
      2. it does NOT hold CAM's window — a guard on THIS TEST'S OWN
         PARAMETERS, corrected from an earlier docstring which claimed it
         caught "a streamer that had simply reached the camera". It does not,
         and a later review measured both halves. A streamer that reached the
         camera is `PFS_CLAMP 2 -> 4`, and that fails assertion **1** (212/4096
         mismatches) without ever reaching assertion 2. What assertion 2 does
         catch is `jump` here shrinking to <= PFS_CLAMP tiles: then LAST
         reaches CAM in the one frame, the two windows COINCIDE, and assertion
         1 becomes true of a frame in which the clamp never bit — so it would
         pass while proving nothing. Planting `jump` 24 -> 16 fires it. That is
         a real and live guard; it is just a guard on the fixture rather than
         on the engine, and a docstring that overstates its reach is the same
         defect class as a proxy assertion, one layer up (the same correction
         T5 above carries);
      3. one more frame and the third tile arrives: a clamp defers, it does not
         SKIP. (Snapping LAST to CAM instead would leave the skipped line stale
         forever — a recorded anti-pattern, not a hypothetical one.)
    """
    px, py = 512, 512                      # slot-aligned, mid-world
    _arm(probe, px, py)
    jump = 24                              # 3 tiles, against a clamp of 2
    _cmd(probe, CMD_FRAME, px + jump, py + jump, frames=4)

    _assert_window_exact(probe, px + 16, py + 16,
                         "after a 3-tile jump, clamped at 2 per axis")
    assert _window_mismatches(probe, px + jump, py + jump), (
        f"LAST's window and CAM's window are the same window after a "
        f"{jump // 8}-tile jump, so assertion 1 above passed on a frame in "
        f"which the clamp never bit and it proves nothing — this test's jump "
        f"is no longer larger than PFS_CLAMP. (A streamer that merely REACHED "
        f"the camera fails assertion 1, not this one.)")

    _cmd(probe, CMD_FRAME, px + jump, py + jump, frames=4)
    _assert_window_exact(probe, px + jump, py + jump,
                         "one frame later, the clamped tile caught up")


# =============================================================================
# T10 — THE WORD PORT. The half of every tilemap word the level cannot reach.
# =============================================================================

def test_t10_the_word_port_carries_the_tilemap_high_byte(probe):
    """A normal-BG tilemap entry is a WORD, and this is the only test that can
    see its top half — across BOTH carriers, the staging and the drain.

    The change's headline correction was `pfss` mode 0 -> mode 1 and
    `["VMDATAL"]` -> `["VMDATAL","VMDATAH"]`, on the grounds that a normal-BG
    entry is a word where Mode 7's is a byte. Nothing could observe it. The
    authored level authors palette group 0, so all 16,384 of its tilemap words
    have a HIGH BYTE OF ZERO — and against a zero oracle a stream that writes
    only low bytes, or writes high bytes one word out, produces a ring
    byte-identical to a correct one. a later review proved that by planting: clearing
    PFS_VMAIN_ROW's bit 7 — so the VRAM address advances on the $2118 (low)
    write instead of the $2119 (high) one, shifting every high byte one word
    forward and writing one word past the transfer — passed 9 of 9 tests.

    A WORD REACHES VRAM THROUGH TWO STAGES AND THIS TEST DRIVES BOTH. The
    STAGING copies it out of a ROM blob into the slot buffer (two spans, MVN,
    position-wrapped); the DRAIN pushes that buffer through the word port (two
    page DMAs, VMAIN, VMDATAH). The first version of this test poisoned the
    staged buffer's high bytes AFTER the kernel had staged it, which proved the
    drain and — precisely because the poison came after — proved nothing about
    the staging. a later review measured that rather than arguing it: a plant
    making `_pfs_copy_line` mask every staged word to & $00FF, i.e. a streamer
    that throws away palette group, priority and flip on every tile it stages,
    passed 11/11 here and 23/23 on the rail. Nothing in this test now writes
    the slot buffer. cmd 7 stages normally and then re-runs the SHIPPED
    `_pfs_copy_line` over the same slot with a synthetic 128-word ROM source
    whose every high byte is non-zero, so the high bytes that reach VRAM were
    put in the buffer by the kernel.

    The level is NOT changed to make this possible: its byte-identity against
    the reference's committed blobs is the strongest independent oracle in this change.
    And the synthetic source is a genuinely necessary third BINDING rather than
    a shortcut — the staging path's source pointer covers exactly the bound
    32 KB window, masked, so no input to it can reach a non-zero high byte.
    `probe_pfs_stream.asm`'s @arm_synth writes that argument out in full,
    including what it leaves uncovered.

    BOTH AXES, because the two VMAIN bytes are two different constants
    ($81 stride-32 for a column, $80 stride-1 for a row) and a defect in one
    says nothing about the other.

    The oracle is `_synth_word`, this file's own statement of the pattern, and
    the assertion surface is unchanged: BG1 VRAM, read back word for word.
    """
    runner, syms, _tile_words = probe
    base = syms["ES_V_PFS_MAP"]
    px, py = SPAWN_X, SPAWN_Y
    _arm(probe, px, py)
    tx, ty = px >> 3, py >> 3

    def streamed(line, axis):
        """cmd 7 on `axis` (0 = column, 1 = row), then the line read back."""
        _cmd(probe, CMD_SYNTH, line, axis, frames=4)
        runner.frame_step(2)
        vram = runner.read_bytes(VR, base * 2, RING * RING * 2 * 4)
        out = []
        for slot in range(RING):
            sc, sr = ((line & (RING - 1)), slot) if axis == 0 else (
                slot, (line & (RING - 1)))
            off = (_vram_word(base, sc, sr) - base) * 2
            out.append(vram[off] | (vram[off + 1] << 8))
        return out

    # --- the COLUMN axis: 64 world ROWS of one column, VMAIN +32 ------------
    # A column's varying axis is the ROWS, so the span the kernel copies starts
    # at LAST_TY - BACK and ring row slot i holds world row _slot_world(...).
    col = (tx + 5) & (TILES - 1)
    want_col = [_synth_word(_slot_world(ty - BACK, i) & (TILES - 1))
                for i in range(RING)]
    got_col = streamed(col, 0)
    bad = [(i, hex(g), hex(w))
           for i, (g, w) in enumerate(zip(got_col, want_col)) if g != w]
    assert not bad, (
        f"the staged COLUMN {col} came back wrong in {len(bad)}/{RING} ring "
        f"slots (slot, got, want): {bad[:5]} — a high byte that never left the "
        f"blob (the staging MVN), or that lands in the wrong word (VMAIN bit 7, "
        f"DMAP mode, or VMDATAH), is a broken word port")

    # --- the ROW axis: 64 world COLUMNS of one row, VMAIN +1 ----------------
    row = (ty + 5) & (TILES - 1)
    want_row = [_synth_word(_slot_world(tx - BACK, i) & (TILES - 1))
                for i in range(RING)]
    got_row = streamed(row, 1)
    bad = [(i, hex(g), hex(w))
           for i, (g, w) in enumerate(zip(got_row, want_row)) if g != w]
    assert not bad, (
        f"the staged ROW {row} came back wrong in {len(bad)}/{RING} ring "
        f"slots (slot, got, want): {bad[:5]} — see the column arm above")


# =============================================================================
# T9 — THE COST, MEASURED. Runs last: the bench walks state the others read.
# =============================================================================

def test_t9_the_per_line_staging_cost_is_measured(probe):
    """Two arms, K iterations each, differenced — never estimated.

    The control arm shares the counter, both strides, the masks and the
    branch, so everything except `jsr pfs_stage_col` cancels. The strides are
    coprime with the world and with the ring, so successive stages take
    DIFFERENT two-span splits; a bench that stayed slot-aligned would measure
    the cheap case only.

    Timed by frame-anchoring rather than by breakpoint: `run_to_break`'s own
    docstring records that a break can be reported with nothing having matched,
    and a repeated write to ONE address gives it two chances to do so — which
    is what it did here (the mark=2 write landed at frame ~39 and the break was
    reported at frame 334). Frame-stepping is deterministic and host-load
    independent; the price is that each arm's endpoints are quantised to a
    frame boundary, which is why K is large and the bound is stated with its
    quantisation rather than as a bare number.

    NOTE: this test runs LAST in the module on purpose. The bench walks
    LAST_TY to vary the span split (restoring it afterwards) and stages into
    the slot buffers, so it perturbs streamer state the earlier tests read.
    It writes no VRAM.
    """
    runner, syms, _ = probe
    K = 6000

    def run_arm(cmd, budget=2000):
        runner.write_bytes(WR, syms["US_PARAM"], K.to_bytes(2, "little"))
        runner.write_bytes(WR, syms["US_CMD"], bytes([cmd]))
        opened = None
        for _ in range(budget):
            runner.frame_step(1)
            mark = runner.read_byte(WR, syms["US_MARK"])
            if opened is None:
                if mark == 1:
                    opened = runner.snes_state_snapshot().master_clock
            elif mark == 2:
                return runner.snes_state_snapshot().master_clock - opened
        raise AssertionError(f"bench arm {cmd} never closed its timed region")

    staged = run_arm(CMD_BENCH)
    control = run_arm(CMD_CONTROL)
    per_mc = (staged - control) / K
    per_cy = per_mc / MC_PER_CYCLE
    quant_mc = 4 * FRAME_MC / K          # <= 2 frame boundaries per arm
    worst_frame_mc = 4 * per_mc          # the declared 4-slot worst frame

    print(f"\npfs_stream staged line: {per_mc:.0f} mc = {per_cy:.0f} CPU "
          f"cycles (+/-{quant_mc / MC_PER_CYCLE:.0f} cycles quantisation)"
          f"\n  K={K}  staged arm {staged} mc  control arm {control} mc"
          f"\n  worst declared frame (4 slots): {worst_frame_mc:.0f} mc = "
          f"{worst_frame_mc / MC_PER_CYCLE:.0f} cycles = "
          f"{100.0 * worst_frame_mc / FRAME_MC:.1f}% of a 357,368 mc frame")

    assert per_mc > 0, (
        "the staged arm was not slower than the control arm — the bench is "
        "measuring nothing")
    # A 128-byte MVN alone is 7 CPU cycles/byte = 896, so a staged line cannot
    # honestly come in under that; and the declared 4-slot worst frame has to
    # leave the frame usable. Both bounds are about the SHAPE of the number,
    # not a pinned value — a pin belongs in substrate.toml, and this moves no
    # substrate pin.
    assert per_cy > 896, (
        f"a staged line measured {per_cy:.0f} cycles, below the 896 cycles "
        f"its 128-byte MVN alone costs — the bench is not measuring the copy")
    assert worst_frame_mc < FRAME_MC / 4, (
        f"the declared 4-slot worst frame is {worst_frame_mc:.0f} mc, over a "
        f"quarter of a {FRAME_MC} mc frame — the clamp or the kernel needs "
        f"revisiting before the rail composes it")
