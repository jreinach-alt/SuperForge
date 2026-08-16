"""split_h_2p_demo — two ROTATING Mode 7 cameras over one plane, seam at 112.

The rail's claim is that two INDEPENDENT perspective floors share
one frame at a handful of VBlank stores each: SIX HDMA channels — an INDIRECT
matrix pair PER BAND streaming that band's own heading's pose through M7A-M7D,
and a DIRECT pair landing each band's own M7X/M7Y + M7HOFS/M7VOFS. Each frame
both headings step one pose (+1 and -1), both cameras drive forward 2.0 px
along their heading through per-axis 8.8 fractional accumulators, and four pose
pointers and four DASB banks are re-derived. Nothing solves a matrix at
runtime.

NONE OF THAT IS ASSERTABLE FROM REGISTERS. There is no PPU-register readback in
this harness (vendor/mesen_runner.py:147 — those ports read back as zeros), so
every claim below is proven by what is DRAWN, off VRAM, CGRAM or the
framebuffer. That is what CLAUDE.md rule 2 asks for anyway.

THE ORACLE IS THE HARDWARE'S OWN ARITHMETIC, and it is exact. `_predict`
re-derives the Mode 7 screen->texel transform from fullsnes' formula — the
`& ~63` truncation of each product's low six fractional bits, applied to each
term SEPARATELY, and the scanline counted from 1 (visible line 0 IS raster line
1) — using the pose the band's HEADING selects. Measured against the shipping
ROM at headings 90 and 38: **57,344 of 57,344 pixels, exactly**, every row.

**A STATED LIMIT CLOSED HERE.** At heading 0 the pose is A = D = ramp[k],
B = C = 0, so the two cross terms vanish **from the VX expression** — the axis
the original argument reasoned about, and on it the per-TERM truncation and
truncating the SUM are arithmetically identical. VY is NOT identical even
there (`(D * -bot) & ~63` and `(D * row) & ~63` stay two separately truncated
terms), so heading 0 discriminates too — 256 pixels of it, measured, which
corrects the original premise. Non-zero headings simply
discriminate on both axes: at the state above the two forms disagree at 272 of
57,344 pixels, and the hardware matches the per-term form at all of them. That
is asserted, not narrated — `test_the_truncation_is_per_term_not_per_sum` fails
if the two forms ever stop disagreeing, so the claim cannot quietly become
vacuous again.

WHAT THE FRAMEBUFFER IS ASKED FOR, and what merely seeds it.

  `_recover`      reads a band's (HEADING, x, y) OUT OF THE PIXELS, jointly:
                  all 256 poses of the set against a +/-3 px position window,
                  returning the ONE candidate that reproduces every sampled
                  pixel exactly. The heading search is exhaustive, so "the two
                  cameras rotate in opposite senses" is measured rather than
                  read from a ROM variable. The position window is bounded
                  because a global search is 32,768 candidates (the world's x
                  period is 512 px, its y period 64) and the motion under
                  measurement is 2.0 px/frame; it is seeded ONCE from the
                  game's decided start, and everything after comes off the
                  framebuffer.

                  JOINTLY, and that is not a refinement — recovering the two in
                  sequence is WRONG, because scoring a heading needs the camera
                  position of the frame being scored. The sequential version
                  passed on the first sample (where the seed is exact) and
                  measured the PREVIOUS frame's camera on every one after it;
                  it failed at 389 of 448 grid points, which is how it was
                  found rather than shipped.

  `_shadow_dasb`  is NOT a recovery — it reads the scene_mgr channel shadow,
                  which is the DESTINATION cam_banks writes and the exact bytes
                  sm_nmi_core MVNs into $4307, not a debug mirror written
                  alongside them.

WRAM IS READ IN THREE PLACES, and in none is it the thing being asserted. In
`test_render_matches_the_hardware_oracle` the DP camera positions and headings
are the oracle's INPUT — the game's DECISION — and the pixels are the
assertion, so every step between the two is under test. (Feeding it the ORIGIN
TABLES instead put the mechanism on both sides of the comparison and let a real
sabotage through; a falsification pass on the earlier, world-fixed form of this
rail found exactly that.) In the motion tests scene_mgr's VBlank counter is the
CLOCK, the denominator only. And the DASB test reads the channel shadow, which
is the output region of the thing it names.

THE CONTROLS. Three -D builds, one per claim, because each headline assertion
is weak alone:

  `sh2_same_heading`  camera 2's heading folded onto camera 1's -> both bands
                      stream one pose -> the opposite-sense rotation signal
                      must die, while the positions still differ.
  `sh2_same_cam`      heading AND start position folded -> one camera in two
                      bands -> the two bands' recovered states must be equal.
  `sh2_badorder`      band 2's matrix pair moved ABOVE band 1's, so its
                      skip-prefix entry's stray line-0 unit wins the HBlank ->
                      PPU line 0 must render the skip pose instead of band 1's.
"""
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tools"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

# The asset generator, imported for its ALGEBRA, not its bytes. It refuses to
# emit anything that disagrees with the vendored blobs
# (vendor/art/split_h_2p/), so importing it here is importing a gated oracle
# rather than importing the thing under test: the ROM's copy went through
# ca65's .incbin, six HDMA channels and the PPU to become pixels.
from gen_split_h_2p_assets import (MOVE_SCALE, PAL_FALLBACK,  # noqa: E402
                                   POSE_BYTES, POSES, SLICE_BYTES, SLICES,
                                   move_lut, pose_blobs, tilemap, world_blob)

BUILD = SUPERFORGE / "build"
ROM = BUILD / "split_h_2p_demo.sfc"
# THE AUTONOMOUS BUILD. The SHIPPING ROM is the SP_INPUT one: the two pads
# REPLACE the autonomous rotate+drive, so with
# nothing held the cameras stand still and only the swarm moves. Every test
# below whose subject IS the autonomous camera model — the counter-rotation,
# the 8.8 drive, the DASB slice crossing — therefore reads `-D SH2_AUTOCAM`,
# and so do the two folding controls, which have to fold something that is
# still moving. Everything else (the uploads, the oracle, the channel
# priority, the seam, power-on fidelity) reads the SHIPPING ROM, because those
# claims are about what a user pulling this branch actually gets.
AUTOCAM = BUILD / "sh2_autocam.sfc"
SAME_HEADING = BUILD / "sh2_same_heading.sfc"
SAME_CAM = BUILD / "sh2_same_cam.sfc"
BADORDER = BUILD / "sh2_badorder.sfc"
ASSETS = BUILD / "assets"
# One expression on purpose: conftest resolves the map a module reads at
# COLLECTION time from exactly this shape, and refuses a module whose map it
# cannot see.
_JMAP = json.loads((SUPERFORGE / "build" / "sh2" / "symbol_map.json").read_text())

W, V, C = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
           MemoryType.SnesCgRam)


def _sym(name, scene=None):
    """Addresses are ASKED FOR, never hardcoded — this reads the same map the
    ROM was assembled against, so an allocator move breaks the test loudly
    instead of silently reading the wrong bytes."""
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


def _chan(name):
    """A channel assignment out of the emitted map, by claim name."""
    for c in _JMAP["scenes"]["split"]["channels"]:
        if c["name"] == name:
            return c["ch"]
    raise KeyError(f"{name} is not an emitted channel claim")


V_M7 = _sym("ES_V_M7", "split")["start"]          # word address (0, pinned)
C_PAL = _sym("ES_C_SH2_PAL", "split")["start"]    # word index (0, by contract)
WRAM_TBL = _sym("ES_SH2_TBL", "split")["start"]   # the six HDMA tables
WRAM_HDMA = _sym("ES_SM_HDMA")["start"]           # the 128 B channel shadow
WRAM_FRAME = _sym("ES_SM_FRAME")["start"]         # scene_mgr's own VBlank count
DP_POS = _sym("ES_SH2_POS", "split")["start"]     # the two cameras' positions
DP_ROT = _sym("ES_SH2_ROT", "split")["start"]     # h1, h2, then the fractions
SWM_CTL = _sym("ES_SWM_CTL", "split")["start"]    # +0 the live count, +2 the beat
# The table's CAPACITY, from the claim's own size — the number the sweep can
# poke the live count up to, and therefore the number of records rule 5 is on
# the hook for. Not SWM_N_SHIP, and not a transcribed 64.
SWM_ENTS = _sym("ES_SWM_ENTS", "split")["start"]      # the 64-record table
SWM_ENTS_BYTES = _sym("ES_SWM_ENTS", "split")["size"]
SWM_MAX = SWM_ENTS_BYTES // 8

# --- the geometry, from the rail's own declaration --------------------------
LINES, SEAM, HALF_W = 224, 112, 128
BANDS = ((0, SEAM), (SEAM, LINES))                # (top, bottom) per band
WORLD_PX = 1024
SHADOW_CH_BYTES = 16                              # $43x0..$43xF per channel
DASB_OFF = 7                                      # $43x7 within that block

# The screenshot is 256x239; the ACTIVE PICTURE is rows 7..230 (224 lines).
# Measured, not assumed — the surrounding rows are blanking and are not part of
# the rendered plane, so a geometric oracle over the whole raster is off by the
# asymmetric margin (7 above, 8 below) and reads as a rendering bug.
ACTIVE_TOP, ACTIVE_H = 7, LINES

TILEMAP = tilemap()
MOVE = move_lut(POSES)


def _rgb5(word):
    return (word & 31, (word >> 5) & 31, (word >> 10) & 31)


# Palette index 0 is the BACKDROP and is never drawn by the plane; tile id n
# draws CGRAM n+1, because the generator's CHR skips index 0 deliberately
# (a Mode 7 8bpp zero IS the transparent backdrop, not a floor colour).
COLORS = [_rgb5(w) for w in PAL_FALLBACK]

# The whole 256-heading pose set, unpacked once: POSE[h][k] = (A, B, C, D) for
# band-local scanline k. From the GATED generator — the same arithmetic the
# vendored blobs were checked against — so nothing here is fitted to the ROM,
# whose side of the comparison is eight .incbin'd bank slices, four index
# tables, four DASB stamps, six HDMA channels and the PPU.
def _unpack_all_poses():
    out = []
    for h in range(POSES):
        ab, cd = pose_blobs(2.0 * math.pi * h / POSES)
        rows = []
        for k in range(SEAM):
            a, b = struct.unpack("<hh", ab[k * 4:k * 4 + 4])
            c, d = struct.unpack("<hh", cd[k * 4:k * 4 + 4])
            rows.append((a, b, c, d))
        out.append(rows)
    return out


POSE = _unpack_all_poses()

# The same set as ONE flat sequence of 256*112 scanline rows, which is what the
# blob physically is. Indexing past a pose's 112th row therefore reads the NEXT
# heading's first row — exactly what the HDMA controller would stream if a
# band's repeat count were larger than 112, and the only way to express a
# candidate seam other than 112 (see the seam test).
POSE_FLAT = [row for rows in POSE for row in rows]


def _pose_at(h, k):
    return POSE_FLAT[(h * SEAM + k) % len(POSE_FLAT)]


# =============================================================================
# THE ORACLE — the PPU's own screen->texel arithmetic
# =============================================================================
def _texel(sx, sy, top, bot, cx, cy, h):
    """The world texel (tx, ty) the PPU samples at screen (sx, sy).

    fullsnes' Mode 7 transform, with this rail's origin substituted in:

        VX = ((A*(HOFS-M7X)) & ~63) + ((B*(VOFS-M7Y)) & ~63)
                                    + ((B*row) & ~63) + (M7X << 8) + A*sx
        VY = ((C*(HOFS-M7X)) & ~63) + ((D*(VOFS-M7Y)) & ~63)
                                    + ((D*row) & ~63) + (M7Y << 8) + C*sx

    with HOFS - M7X = -128 and VOFS - M7Y = -<the band's bottom line>, which is
    the rail's whole per-band origin solve, and `row = sy + 1` because visible
    line 0 is raster line 1. The `& ~63` truncations are the hardware's,
    applied per TERM and not to the sum — which heading-0 data alone cannot
    distinguish and rotated data does
    (`test_the_truncation_is_per_term_not_per_sum`).

    The two cross terms (B and C) are what rotation adds; at heading 0 they are
    zero and this collapses to the unrotated form exactly.
    """
    a, b, c, d = POSE[h][sy - top]
    row = sy + 1
    vx = ((a * -HALF_W) & ~63) + ((b * -bot) & ~63) + ((b * row) & ~63) \
        + (cx << 8) + a * sx
    vy = ((c * -HALF_W) & ~63) + ((d * -bot) & ~63) + ((d * row) & ~63) \
        + (cy << 8) + c * sx
    return vx >> 8, vy >> 8


def _tile_at(tx, ty):
    return TILEMAP[((ty >> 3) & 127) * 128 + ((tx >> 3) & 127)]


def _predict(sx, sy, cam, heads):
    """The 5-bit colour the PPU must draw at screen (sx, sy).

    `cam` is ((p1x, p1y), (p2x, p2y)) and `heads` is (h1, h2): the game's
    DECISIONS. Everything between them and the pixel is under test.
    """
    band = 0 if sy < SEAM else 1
    top, bot = BANDS[band]
    cx, cy = cam[band]
    return COLORS[_tile_at(*_texel(sx, sy, top, bot, cx, cy, heads[band])) + 1]


# 5-bit colour -> the tile id that draws it. Index 0 (the backdrop) is absent
# deliberately: the plane never draws it, so a backdrop pixel inside the picture
# is a defect and must not silently score as "some tile".
_TILE_OF = {c: i for i, c in enumerate(COLORS[1:])}

# The cast stands ON the floor, so some pixels of the picture are no
# longer the plane. These two are the marker colours sh2_obj.asm writes into the
# two OBJ palettes — white for band 1, magenta for band 2. The floor oracle
# SKIPS them (a sprite pixel is not a wrong floor pixel) and the sprite tests own
# them; `test_the_obj_palettes_are_the_two_band_signatures` in
# tests/test_split_h_2p_sprites.py asserts CGRAM really holds these, so the
# constants here are the spec rather than a transcription of the ROM.
MARKER_COLORS = {_rgb5(0x7FFF), _rgb5(0x7C1F)}

# The recovery grid. Every 4th row of the band and every 16th column: 448
# points, which is enough that the correct candidate scores 100% and the
# runner-up does not — asserted on every recovery, so a grid that stopped
# discriminating fails loudly instead of returning a fit.
_ROWS = {b: list(range(t, bo, 4)) for b, (t, bo) in enumerate(BANDS)}
_COLS = list(range(8, 250, 16))


def _observed(px, band, rows=None):
    """The band's drawn tile ids at the recovery grid, from the FRAMEBUFFER.

    A grid point covered by a MARKER comes back as None and is skipped by every
    caller. That is not a softening of the assertion: a pixel that is neither a
    floor colour nor a marker colour still fails here, and the callers assert
    that enough points survived to discriminate. The cast is small and the grid
    is 448 points, so the loss is a handful.
    """
    out = []
    for sy in (rows if rows is not None else _ROWS[band]):
        for sx in _COLS:
            c = tuple(v >> 3 for v in px[sx, sy])
            if c in MARKER_COLORS:
                out.append(None)
                continue
            assert c in _TILE_OF, (
                f"screen ({sx},{sy}) is {c}, which is neither a floor colour "
                f"nor a marker colour — the plane drew the backdrop, or the "
                f"palette is wrong")
            out.append(_TILE_OF[c])
    return out


def _predicted(band, cx, cy, h, rows=None):
    top, bot = BANDS[band]
    return [_tile_at(*_texel(sx, sy, top, bot, cx, cy, h))
            for sy in (rows if rows is not None else _ROWS[band])
            for sx in _COLS]


# The recovery's engine: the texel each grid point samples for a given heading
# with the CAMERA AT THE ORIGIN. The camera enters `_texel` only as `+ (cx << 8)`
# and `+ (cy << 8)`, and a value shifted left 8 has no low bits, so
#
#     tx(cx) = tx0 + cx        ty(cy) = ty0 + cy
#
# exactly. Pulling the camera out this way turns a candidate from a full
# re-derivation into one add and one tilemap index, which is what makes
# scoring all 256 headings against a position window affordable at all.
_BASE: dict = {}


def _base(band, h):
    key = (band, h)
    if key not in _BASE:
        top, bot = BANDS[band]
        _BASE[key] = [_texel(sx, sy, top, bot, 0, 0, h)
                      for sy in _ROWS[band] for sx in _COLS]
    return _BASE[key]


def _recover(px, band, near, span=8):
    """The band's (heading, x, y), read out of the pixels — JOINTLY.

    Returns the ONE candidate that reproduces every sampled pixel of the band
    exactly, and fails if there is not exactly one.

    JOINT, because the two cannot be recovered in sequence: scoring a heading
    needs the camera position of the frame being scored, and recovering that
    position needs the heading. Doing them in order works on the first sample
    (where the position seed is the game's own decided state) and silently
    measures the PREVIOUS frame's camera on every sample after it — which is
    how this test first failed, at 389 of 448 grid points.

    THE HEADING SEARCH IS EXHAUSTIVE — all 256 poses of the set, no window and
    no seed — so "camera 1 advanced one pose and camera 2 retreated one" is a
    measurement of what the band's matrix channels streamed. The POSITION
    search is a window around the previous RECOVERED position, because a global
    one is 32,768 candidates (the world's x period is 512 px and its y period
    64).

    THE WINDOW IS SIZED FROM THE HARNESS, not from the per-frame motion. The
    drive is 2.0 px/frame, but one `frame_step` here advances the emulated
    frame more than once — `take_screenshot` is frame-synchronous and absorbs
    the presentation lag — so consecutive samples are 2-3 ROM frames apart and
    +/-3 px is NOT enough. It measurably was not: at span 3 the recovery found
    no candidate at all on the second sample. +/-8 covers four ROM frames of
    drive with margin, and a displacement that still escaped it fails the
    no-candidate assert rather than quietly returning the window's edge.

    The window is seeded ONCE, from the game's decided start; everything after
    comes off the framebuffer.

    EXACTLY ONE, not "the best". A near-miss means the oracle and the ROM have
    diverged (a finding, not a tolerance to widen) and a tie means this cannot
    measure the thing it is being used to measure. Scoring aborts a candidate
    at its first mismatched grid point, so the search costs about as much as
    the handful of candidates that survive.
    """
    obs = _observed(px, band)
    usable = [(b, w) for b, w in zip(_base(band, 0), obs) if w is not None]
    assert len(usable) >= len(obs) * 3 // 4, (
        f"band {band}: {len(obs) - len(usable)} of {len(obs)} grid points are "
        f"under a marker — too few floor samples left to recover a state")
    keep = [i for i, w in enumerate(obs) if w is not None]
    want_at = [obs[i] for i in keep]
    hits, best_n, best_k = [], -1, None
    for h in range(POSES):
        base = _base(band, h)
        pts = [base[i] for i in keep]
        for dx in range(-span, span + 1):
            cx = near[0] + dx
            for dy in range(-span, span + 1):
                cy = near[1] + dy
                n = 0
                for (tx0, ty0), want in zip(pts, want_at):
                    if TILEMAP[(((ty0 + cy) >> 3) & 127) * 128
                               + (((tx0 + cx) >> 3) & 127)] != want:
                        break
                    n += 1
                else:
                    hits.append((h, (cx, cy)))
                if n > best_n:
                    best_n, best_k = n, (h, (cx, cy))
    assert hits, (
        f"band {band}: no (heading, position) within +/-{span} of {near} "
        f"reproduces the frame — best {best_n}/{len(want_at)} grid points at "
        f"{best_k}. The oracle and the ROM have diverged")
    assert len(hits) == 1, (
        f"band {band}: the frame is ambiguous — {hits} all reproduce it, so "
        f"this recovery cannot measure rotation or motion")
    return hits[0]


# =============================================================================
# FIXTURES
# =============================================================================
@pytest.fixture(scope="module")
def runner():
    """ONE MesenRunner for the module. The Mesen2 core is a process-global
    singleton, so a second live runner does not give a second machine — it
    takes this one over, and the first test to touch the old handle afterwards
    dies parked at a scanline with a diagnostic that names the wrong module.
    """
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make split_h_2p_demo` first")
    r = MesenRunner()
    r.boot_rom(str(ROM), frames=60)
    yield r
    r.stop()


@pytest.fixture(scope="module", autouse=True)
def controls_built():
    """Build the three -D controls here, the way test_split_v_fight.py does.

    Built rather than skipped-if-absent: a control that quietly does not exist
    turns the claim it disproves back into the vacuous one it is there to
    disprove, and a skip reports as not-failing.
    """
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make split_h_2p_demo` first")
    subprocess.run(["bash", "tools/build_split_h_2p_variants.sh"],
                   cwd=SUPERFORGE, check=True, capture_output=True)
    for p in (AUTOCAM, SAME_HEADING, SAME_CAM, BADORDER):
        assert p.exists(), f"the variant build produced no {p.name}"


@pytest.fixture
def autocam(runner):
    """The AUTONOMOUS build, from power-on — the self-driving camera model.

    The shipping ROM's cameras are on the two pads, so a test
    whose subject IS the autonomous rotation or drive has to read the build
    that still has it. Everything else stays on the shipping ROM.
    """
    runner.boot_rom(str(AUTOCAM), frames=60)
    return runner


@pytest.fixture
def fresh(runner):
    """The shipping ROM, from power-on, for every test that reads it.

    The rail is stateful — both cameras rotate and drive every frame, and the
    control tests load DIFFERENT ROMs into the shared core — so a module-scoped
    boot would make each test depend on the order pytest happened to pick.
    """
    runner.boot_rom(str(ROM), frames=60)
    return runner


def _shot(runner, tmp_path, tag):
    p = tmp_path / f"{tag}.png"
    runner.take_screenshot(str(p))
    img = Image.open(p).convert("RGB")
    return img.crop((0, ACTIVE_TOP, 256, ACTIVE_TOP + ACTIVE_H)).load()


def _u16(runner, addr):
    b = runner.read_bytes(W, addr, 2)
    return b[0] | (b[1] << 8)


def _step_axis(pos, frac, vel):
    """One SH2_DRIVE_AXIS step: the 8.8 accumulator, exactly as the ROM does it."""
    acc = (frac + vel) & 0xFFFF
    hi = acc >> 8
    return ((pos + (hi - 256 if hi >= 128 else hi)) & (WORLD_PX - 1), acc & 0xFF)


def _rewind_axis(pos, frac, vel):
    """...and its inverse. Exact, and it has to be.

    The step is `acc = frac_before + vel`, `pos += s8(acc >> 8)`,
    `frac_after = acc & $FF`. Only the low byte of `vel` reaches `frac_after`,
    so `frac_before = (frac_after - vel) & $FF` recovers it uniquely; the rest
    then replays forward and the integer delta comes back out.
    """
    before = (frac - vel) & 0xFF
    acc = (before + vel) & 0xFFFF
    hi = acc >> 8
    return ((pos - (hi - 256 if hi >= 128 else hi)) & (WORLD_PX - 1), before)


def _dp_snapshot(runner, advanced=True):
    """The state the PARKED FRAME IS RENDERING — DP, stepped BACK once.

    WHY THE REWIND. `cam_tick` stamps the current state's tables and only then
    advances (sh2_cam.asm's header says why — the cast is projected
    during active display and must read a state that is already committed). So
    while a frame is on screen, DP holds the state the NEXT commit will stamp,
    one step past the one the pixels show. Reading DP raw and feeding it to the
    oracle would compare the frame against its successor.

    The inverse is the forward model run backwards through the SAME gated move
    LUT, and it is CHECKED here rather than trusted: re-applying the forward
    step to the result must reproduce the DP words exactly, or this raises.
    """
    raw = runner.read_bytes(W, DP_POS, 8)
    rot = runner.read_bytes(W, DP_ROT, 12)
    if not advanced:
        # On the SHIPPING ROM with no pad held, cam_advance is
        # cam_input and it steps nothing, so DP already holds the state the
        # parked frame is showing and the rewind below would walk it BACKWARDS
        # off the truth. `advanced` is the caller's statement about what it
        # drove, not a guess — every caller either held a pad or is reading the
        # autonomous build.
        return ([(raw[0] | (raw[1] << 8), raw[2] | (raw[3] << 8)),
                 (raw[4] | (raw[5] << 8), raw[6] | (raw[7] << 8))],
                [rot[0] | (rot[1] << 8), rot[2] | (rot[3] << 8)],
                [(rot[4] & 0xFF, rot[6] & 0xFF), (rot[8] & 0xFF, rot[10] & 0xFF)])
    heads = [rot[0] | (rot[1] << 8), rot[2] | (rot[3] << 8)]
    cam = [[raw[0] | (raw[1] << 8), raw[2] | (raw[3] << 8)],
           [raw[4] | (raw[5] << 8), raw[6] | (raw[7] << 8)]]
    frac = [[rot[4] | (rot[5] << 8), rot[6] | (rot[7] << 8)],
            [rot[8] | (rot[9] << 8), rot[10] | (rot[11] << 8)]]
    out_cam, out_frac, out_heads = [], [], []
    for b in (0, 1):
        vel = struct.unpack_from("<hh", MOVE, heads[b] * 4)
        axes = [_rewind_axis(cam[b][i], frac[b][i], vel[i]) for i in (0, 1)]
        # ...and forward again, which is the self-check.
        fwd = [_step_axis(axes[i][0], axes[i][1], vel[i]) for i in (0, 1)]
        assert [f[0] for f in fwd] == cam[b] and [f[1] for f in fwd] == \
            [frac[b][i] & 0xFF for i in (0, 1)], (
            f"the one-step rewind does not invert the drive for band {b}: "
            f"DP {cam[b]}/{frac[b]} -> {axes} -> {fwd}")
        out_cam.append((axes[0][0], axes[1][0]))
        out_frac.append((axes[0][1], axes[1][1]))
        # camera 1 steps +1 per frame and camera 2 steps -1, so the rewind is
        # the opposite sense per band.
        out_heads.append((heads[b] - 1) % POSES if b == 0
                         else (heads[b] + 1) % POSES)
    return out_cam, out_heads, out_frac


def _state(runner, advanced=True):
    """The game's DECISIONS for the frame on screen: positions and headings."""
    cam, heads, _frac = _dp_snapshot(runner, advanced)
    return cam, heads


def _fracs(runner, advanced=True):
    """The four 8.8 fraction accumulators of the frame on screen."""
    return _dp_snapshot(runner, advanced)[2]


def _shadow_dasb(runner, claim):
    """The DASB byte in the scene_mgr channel shadow for an emitted claim.

    THE DESTINATION, not a mirror. sm_nmi_core MVNs this 128-byte block into
    $4300 immediately after sm_nmi_hook returns, so these ARE the bytes the
    HDMA controller fetches indirect pose data through. A debug mirror
    elsewhere in WRAM would prove only that the stamper can write twice.
    """
    ch = _chan(claim)
    return runner.read_bytes(W, WRAM_HDMA + ch * SHADOW_CH_BYTES + DASB_OFF, 1)[0]


# =============================================================================
# 1. THE WORLD — what the enter-time DMA and the .incbin sites actually put down
# =============================================================================
def test_mode7_vram_is_the_map_blob(fresh):
    """The DESTINATION region, byte for byte, against the source.

    A mode-1 DMA with BBAD = VMDATAL is what makes the interleave land: even
    source byte to $2118 (tilemap), odd to $2119 (8bpp CHR). Reading the
    consumer's pixels instead would pass while a whole half of this transfer
    was wrong — the CHR is only four solid tiles, so a tilemap that landed in
    the high bytes would still draw *something*.
    """
    want = (ASSETS / "sh2_map.bin").read_bytes()
    assert len(want) == 32768
    got = bytes(fresh.read_bytes(V, V_M7 * 2, len(want)))
    assert got == want, (
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} VRAM bytes "
        f"differ from sh2_map.bin")


def test_map_blob_is_the_generator():
    """The bytes ca65 embedded ARE what the generator computes.

    Not a tautology: `world_blob()` recomputes the checker from its algebra,
    so this ties the shipped blob to the authored world rather than to itself.
    The gate against the vendored blobs is a separate claim with its own
    module, `tests/test_split_h_2p_assets.py`.
    """
    assert (ASSETS / "sh2_map.bin").read_bytes() == world_blob()


def test_every_pose_slice_landed_where_its_claim_says(fresh):
    """The eight 28,672 B slices, byte for byte, at their claimed ROM offsets.

    The DESTINATION-region check for the ROM layout the runtime pointer
    arithmetic stands on. ca65's `.assert ^label = ES_R_*_BANK` refuses a claim
    that DRIFTED, but a claim site can pass that and still hold the wrong
    bytes — an .incbin of the wrong slice file asserts identically. So the
    image is opened and compared: slice k of channel c must be exactly the file
    the generator cut, at exactly the byte offset the allocator emitted.

    This is what makes `bank = base + (h >> 6)` a fact rather than a comment:
    if two slices were swapped, every heading in two of the four 64-pose
    quarters would stream the wrong pose and only this test names WHICH.
    """
    image = ROM.read_bytes()
    for chan in ("ab", "cd"):
        for k in range(SLICES):
            claim = f"sh2_pose256_{chan}_s{k}"
            at = _sym(f"ES_R_{claim.upper()}", None)["start"]
            want = (ASSETS / f"{claim}.bin").read_bytes()
            assert len(want) == SLICE_BYTES
            got = image[at:at + SLICE_BYTES]
            assert got == want, (
                f"{claim} at ROM ${at:05X} is not the generator's slice — "
                f"{sum(a != b for a, b in zip(got, want))} of {SLICE_BYTES} "
                f"bytes differ")
    at = _sym("ES_R_SH2_MOVE256", None)["start"]
    assert image[at:at + len(MOVE)] == MOVE, "sh2_move256 is not the move LUT"


def test_cgram_is_the_palette_and_word_0_is_the_backdrop(fresh):
    """Five absolute CGRAM indices — Mode 7 8bpp pixels ARE CGRAM indices.

    Word 0 is asserted separately because it is TWO things: palette index 0 and
    the Mode 7 backdrop slot. That double duty is why `backdrop` cannot compose
    with this scene, and a test that only checked 1..4 would let the backdrop
    slot drift to whatever the PPU powered on holding.
    """
    want = (ASSETS / "sh2_pal.bin").read_bytes()
    assert len(want) == 10
    got = bytes(fresh.read_bytes(C, C_PAL * 2, len(want)))
    assert got == want
    assert got[0] | (got[1] << 8) == PAL_FALLBACK[0], "CGRAM 0 is not the backdrop"


def test_palette_holds_the_position_oracle_at_full_separation(fresh):
    """The COOL pair carries no red and the WARM pair carries all of it.

    The colours the recoveries above resolve tiles by. A re-theme that softened
    the split would make `_TILE_OF` ambiguous and every recovery in this module
    quietly weaker rather than red, which is the failure mode this repo calls
    indirect evidence.
    """
    raw = fresh.read_bytes(C, C_PAL * 2, 10)
    words = [raw[i] | (raw[i + 1] << 8) for i in range(0, 10, 2)]
    assert [w & 31 for w in words[1:3]] == [0, 0], "a cool colour carries red"
    assert [w & 31 for w in words[3:5]] == [31, 31], "a warm colour is not saturated"


# =============================================================================
# 2. THE PICTURE — every pixel, against the PPU's own arithmetic
# =============================================================================
def test_render_matches_the_hardware_oracle(fresh, tmp_path):
    """All 256x224 pixels, exactly, from two positions and two HEADINGS.

    The strongest statement this module makes. The two camera positions and the
    two headings are the oracle's INPUT and the FRAMEBUFFER is the assertion,
    so what is checked is the whole chain BETWEEN them — four index tables,
    each band's pose POINTER and its DASB BANK, the repeat counts, band 2's
    skip prefix, both origin tables' non-repeat counts, the channel priority
    that hides the stray line-0 unit, the subtraction that turns a position
    into M7X/M7Y + HOFS/VOFS, the seam, the palette and the interleave. Any one
    of them wrong moves pixels.

    THE INPUT IS THE GAME'S DECISION, NOT THE MECHANISM'S OUTPUT — the DP
    positions and headings, NOT the origin tables cam_stamp writes or the
    pointers cam_ptrs writes. Reading those instead would put the thing under
    test on both sides of the comparison: measured with band 2's M7X
    sabotaged, a table-fed oracle PASSED while four other tests failed.

    Exact, not thresholded, and the pixel count is asserted so the assertion
    cannot quietly narrow to a stride again — it did once, and nothing caught
    it until the pixel count was asserted alongside.
    """
    with fresh.frame_stepping():
        cam, heads = _state(fresh, advanced=False)
        px = _shot(fresh, tmp_path, "oracle")
    assert heads[0] != heads[1], (
        f"both bands are at heading {heads[0]} — this frame cannot distinguish "
        f"two matrix pairs from one")
    checked = [(sx, sy) for sy in range(LINES) for sx in range(256)]
    assert len(checked) == 57344, "the oracle is no longer checking every pixel"
    seen = {(sx, sy): tuple(c >> 3 for c in px[sx, sy]) for sx, sy in checked}
    marks = [k for k, c in seen.items() if c in MARKER_COLORS]
    bad = [(sx, sy) for sx, sy in checked
           if seen[(sx, sy)] not in MARKER_COLORS
           and seen[(sx, sy)] != _predict(sx, sy, cam, heads)]
    assert not bad, (
        f"{len(bad)} of {len(checked)} non-marker pixels disagree with the "
        f"Mode 7 oracle at cam {cam} headings {heads}; first at {bad[:5]}")
    # The cast is ALLOWED to cover the plane and nothing else. Bounding it both
    # ways is what stops "everything is a marker" from reading as a clean floor:
    # the markers must be there (the cast renders) and must be a small
    # part of the picture (they are tokens on a floor, not a wash over it).
    assert marks, "no marker pixel in the frame — the cast did not render"
    assert len(marks) < len(checked) // 20, (
        f"{len(marks)} of {len(checked)} pixels are marker colours — the cast "
        f"is covering the plane rather than standing on it")


def test_the_truncation_is_per_term_not_per_sum(fresh, tmp_path):
    """the hardware truncates each PRODUCT, not the sum.

    The unrotated form of this rail could not ask this question, and the reason
    usually given was HALF right. At heading 0 the pose is A = D = ramp[k] and
    B = C = 0, so two of VX's three truncated terms vanish and the per-term and
    per-sum forms are arithmetically identical **on the vx axis**. VY is not:
    `(D * -bot)` and `(D * row)` remain two separately truncated terms at every
    heading, and they discriminate — measured at 256 pixels of the seeded
    headings (0, 128). So heading 0 could have settled it after all; the limit
    as originally stated was narrower than it read. Nothing here depends on
    which is true, because the first assertion below refuses a frame on which
    the forms agree.

    Both halves are asserted, because either alone is worthless:

      * the two forms must DISAGREE on this frame (otherwise the test is
        vacuous and would stay green if the rail lost its rotation), and
      * the hardware must match the PER-TERM form and NOT the per-sum one.
    """
    with fresh.frame_stepping():
        cam, heads = _state(fresh, advanced=False)
        px = _shot(fresh, tmp_path, "trunc")

    def per_sum(sx, sy):
        band = 0 if sy < SEAM else 1
        top, bot = BANDS[band]
        cx, cy = cam[band]
        a, b, c, d = POSE[heads[band]][sy - top]
        row = sy + 1
        vx = ((a * -HALF_W + b * -bot + b * row) & ~63) + (cx << 8) + a * sx
        vy = ((c * -HALF_W + d * -bot + d * row) & ~63) + (cy << 8) + c * sx
        return COLORS[_tile_at(vx >> 8, vy >> 8) + 1]

    forms_differ = [(sx, sy) for sy in range(LINES) for sx in range(256)
                    if _predict(sx, sy, cam, heads) != per_sum(sx, sy)]
    assert forms_differ, (
        f"the per-term and per-sum forms agree everywhere at headings {heads} "
        f"— this frame cannot settle the question, so the claim is vacuous")
    wrong = [(sx, sy) for sx, sy in forms_differ
             if tuple(c >> 3 for c in px[sx, sy]) not in MARKER_COLORS
             and tuple(c >> 3 for c in px[sx, sy]) == per_sum(sx, sy)]
    assert not wrong, (
        f"the hardware matched the PER-SUM form at {len(wrong)} of "
        f"{len(forms_differ)} discriminating pixels — the oracle's truncation "
        f"model is wrong, which is a finding about the PPU, not about the ROM")


# =============================================================================
# 3. THE CHANNEL-PRIORITY CONTRACT — the slice's one structural risk
# =============================================================================
def test_band_2s_matrix_pair_is_pinned_below_band_1s():
    """The DECLARATION half: the emitted channel numbers, in the right order.

    Band 2's index tables open with a non-repeat count-112 SKIP entry that
    fires one stray 4-byte unit at line 0. HDMA services CH0->CH7 within an
    HBlank, so the mask is band 1's pair writing M7A-M7D LAST — which is only
    true if band 2's channels are numerically lower. Asserted against the
    emitted map rather than copied out of the .toml's comment, and the
    framebuffer half is the next two tests.

    The four are also asserted DISTINCT: the bands are disjoint, which makes a
    channel reusable, so an unpinned allocation packs both bands' AB claims
    onto one channel — one table and one DASB for two headings.
    """
    chans = {n: _chan(n) for n in ("sh2ab1", "sh2cd1", "sh2ab2", "sh2cd2")}
    assert len(set(chans.values())) == 4, (
        f"the four matrix channels are not distinct: {chans} — a shared "
        f"channel is one index table and one DASB for two headings")
    assert chans["sh2ab2"] < chans["sh2ab1"], (
        f"band 2's AB channel {chans['sh2ab2']} is not below band 1's "
        f"{chans['sh2ab1']} — its stray line-0 unit would win the HBlank")
    assert chans["sh2cd2"] < chans["sh2cd1"], (
        f"band 2's CD channel {chans['sh2cd2']} is not below band 1's "
        f"{chans['sh2cd1']}")


L0_TURN_FRAMES = 20
# The two candidate poses must disagree on at least this many of line 0's plane
# pixels, or the comparison below is decided by rounding. MEASURED, not picked:
# after the drive, band 1 is at heading 20 and the skip pose at 64, and they
# paint line 0 differently at 199 of 256 — so the shipping ROM scores 256/256
# against its own pose and 57/256 against the stray one. The PARKED seeded state
# that this test once sat on gives FOUR. The floor is set an octave below the
# measured separation, not just under it.
L0_MIN_SEPARATION = 64


def _line0_scores(runner, tmp_path, tag, advanced=False, drive=L0_TURN_FRAMES):
    """PPU line 0 scored against band 1's pose and against the skip pose.

    Both are computed at BAND 1's origin, because the origin channels are
    untouched by the priority question: at line 0 the origin HDMA has already
    landed band 1's M7X/M7Y and HOFS/VOFS whichever matrix pair won. The skip
    pointer aims at the slice BASE, so the pose it fetches is heading
    64*(h2 >> 6) — band 2's current bank slice, first heading.

    THE PADS ARE DRIVEN FIRST, and here is why. On the SP_INPUT shipping
    build a released controller leaves both cameras on the seeded state forever
    — band 1 at heading 0, the skip pose at heading 128 — and on a four-fold
    symmetric checker those two poses render line 0 the SAME at 252 of 256
    pixels. The claim below then turned on FOUR pixels, and it got that thin
    silently when the pads replaced the autonomous camera. Twenty
    frames of the sprite module's own drive (`_unstick`'s remedy for the same
    degeneracy) puts band 1 near heading 20 and the skip pose two bank slices
    away, and the last frame is RELEASED so DP still holds what the picture
    shows.

    THE SEPARATION IS THEN ASSERTED, not hoped for: the two candidate poses must
    differ on at least `L0_MIN_SEPARATION` of the plane pixels being scored.
    That is the same non-vacuity self-guard
    `test_the_truncation_is_per_term_not_per_sum` uses, and it is what keeps
    "line 0 renders MY pose, not the stray one" from quietly degenerating into
    "the two poses look alike here" a third time.
    """
    with runner.frame_stepping():
        for _ in range(drive):
            runner.set_input(1, left=True, b=True)
            runner.frame_step(1, controller_index=0, right=True, b=True)
        if drive:
            runner.set_input(1)
            runner.frame_step(1)                # released: DP == the picture
        cam, heads = _state(runner, advanced=advanced)
        px = _shot(runner, tmp_path, tag)
    row = [tuple(v >> 3 for v in px[sx, 0]) for sx in range(256)]
    (cx, cy) = cam[0]
    # A near marker's box can reach row 0, and a sprite pixel is not
    # a wrong floor pixel. The columns it covers are dropped from BOTH scores
    # and the denominator is returned with them, so the caller compares like
    # with like instead of against a constant that stopped being true.
    cols = [sx for sx in range(256) if row[sx] not in MARKER_COLORS]
    assert len(cols) >= 256 * 3 // 4, (
        f"{256 - len(cols)} of 256 pixels of line 0 are marker colours — too "
        f"few plane pixels left to tell the two poses apart")

    def render(h):
        return [COLORS[_tile_at(*_texel(sx, 0, 0, SEAM, cx, cy, h)) + 1]
                for sx in cols]

    def score(h):
        return sum(1 for got, want in zip(row_cols, render(h)) if got == want)

    row_cols = [row[sx] for sx in cols]
    skip_h = (heads[1] >> 6) * (POSES // SLICES)
    assert skip_h != heads[0], (
        f"the skip pose and band 1's pose are both heading {skip_h} on this "
        f"frame — line 0 cannot distinguish them, so the test is vacuous")
    # ...and the INDEX inequality above is not enough: it was all this guarded
    # this for a long time, and two DIFFERENT headings can still paint line 0
    # identically on a symmetric world. Compare what they DRAW.
    sep = sum(1 for a, b in zip(render(heads[0]), render(skip_h)) if a != b)
    assert sep >= L0_MIN_SEPARATION, (
        f"band 1's pose (heading {heads[0]}) and the skip pose (heading "
        f"{skip_h}) paint line 0 the same at {len(cols) - sep} of {len(cols)} "
        f"plane pixels — only {sep} pixels separate them, under the "
        f"{L0_MIN_SEPARATION} this comparison needs to mean anything")
    return score(heads[0]), score(skip_h), heads, skip_h, len(cols)


def test_line_0_renders_band_1s_matrix_not_the_stray_skip_unit(fresh, tmp_path):
    """THE PIXELS half. Every one of the 256 pixels of PPU line 0.

    The stray unit is REAL — band 2's channel does transfer it, every frame —
    and this asserts that the priority pin makes it invisible: line 0 must
    reproduce band 1's pose exactly and must NOT reproduce the skip pose.
    `test_the_badorder_control_lets_the_stray_unit_win` shows that both halves
    can fail, which is what makes "line 0 looks fine" evidence.
    """
    mine, stray, heads, skip_h, n = _line0_scores(fresh, tmp_path, "line0")
    assert mine == n, (
        f"PPU line 0 does not render band 1's pose (heading {heads[0]}): "
        f"{mine}/{n} plane pixels match. Band 2's stray line-0 unit is not "
        f"masked")
    assert stray < n, (
        f"PPU line 0 also reproduces the skip pose (heading {skip_h}) exactly "
        f"— the two poses are indistinguishable here and this proves nothing")


def test_the_badorder_control_lets_the_stray_unit_win(runner, tmp_path):
    """THE CONTROL. Band 2's pair moved ABOVE band 1's -> line 0 flips.

    The only change is which channel each band's index table AND its DASB bank
    are bound to (sh2_cam.asm's SH2_CH_* indirection); both pairs are DMAP $43
    to the same BBAD with the same band length, so the swap is exactly the
    priority inversion and nothing else. Line 0 must then render the SKIP pose
    exactly, and band 1's pose must fail — the mirror image of the test above.

    Without this the claim above is untestable: a rail whose skip entry never
    fired at all would pass it just as well.
    """
    runner.boot_rom(str(BADORDER), frames=60)
    mine, stray, heads, skip_h, n = _line0_scores(runner, tmp_path, "badorder")
    assert stray == n, (
        f"the BADORDER control's line 0 does not render the skip pose "
        f"(heading {skip_h}): {stray}/{n}. The control is not inverting the "
        f"priority, so the shipping ROM's line-0 assertion proves nothing")
    assert mine < n, (
        f"the BADORDER control's line 0 still renders band 1's pose "
        f"({mine}/{n}) — the inversion did not take effect")


# =============================================================================
# 4. THE HEADLINE — two cameras, ROTATING in opposite senses
# =============================================================================
def _walk(runner, tmp_path, tag, steps):
    """Step `steps` frames, recovering both bands' heading AND position from
    the pixels at each one.

    The ROM's own VBlank counter is the CLOCK — the denominator only, exactly
    A `frame_step` here measurably advances the emulated frame
    more than once (`take_screenshot` is frame-synchronous and absorbs the
    presentation lag), so asserting "one pose step per STEP" would assert a
    property of the harness instead of the rail.

    The position seed is the game's decided start, read ONCE; every later
    position is recovered from the framebuffer within +/-3 px of the previous
    RECOVERED one.
    """
    out, seed_frac = [], None
    with runner.frame_stepping():
        seed, _ = _state(runner)
        near = list(seed)
        for i in range(steps + 1):
            if i == 0:
                seed_frac = _fracs(runner)
            # THE COUNTER AND THE PIXELS MUST BE THE SAME FRAME'S, and taking
            # the picture can advance the emulated frame (take_screenshot is
            # frame-synchronous even on a parked core). An earlier form read the
            # counter before the shot and got away with it; here it slipped
            # twice in seven samples and the per-step rotation delta read
            # [2,1,3,...] against a flat [2,2,2,...] — a HARNESS race, not a
            # rail defect, and it presents as one. So the counter is read on
            # BOTH sides and the sample is retaken until they agree.
            # THE PICTURE'S FRAME IS BRACKETED, NOT PAIRED. Taking the shot
            # advances the emulated frame even on a parked core
            # (take_screenshot is frame-synchronous), and by a VARYING amount —
            # measured here as 2 or 3. It once read the counter once, before
            # the shot, and treated it as the picture's frame; that held on its
            # run and slipped twice in seven samples on this one, presenting as
            # a rotation rate of [2,1,3,2,2,2] against a flat [2,2,2,...] — a
            # HARNESS race wearing a rail defect's clothes. Reading the counter
            # on BOTH sides brackets the frame the picture came from, and the
            # rate assertions below use the bracket instead of a point.
            frame = _u16(runner, WRAM_FRAME)
            dasb = tuple(_shadow_dasb(runner, n)
                         for n in ("sh2ab1", "sh2cd1", "sh2ab2", "sh2cd2"))
            px = _shot(runner, tmp_path, f"{tag}{i}")
            frame_hi = _u16(runner, WRAM_FRAME)
            hs, ps = [], []
            for b in (0, 1):
                h, p = _recover(px, b, near[b])
                hs.append(h)
                ps.append(p)
                near[b] = p
            out.append((frame, tuple(hs), tuple(ps), dasb, frame_hi))
            if i < steps:
                runner.frame_step()
    return out, seed_frac


def test_both_cameras_rotate_in_opposite_senses(autocam, tmp_path):
    """Each band's HEADING, recovered from its own pixels, over a driven run.

    All 256 candidate poses are scored against the frame, so this measures what
    the band's matrix channels STREAMED — the pose pointer, the DASB bank and
    the HDMA fetch together. An engine that advanced its heading words
    correctly while the pointers never reached the tables would fail here, and
    a test on those words would not.

    THE SENSES ARE ASSERTED, not merely "something changed". Camera 1 steps +1
    pose per frame and camera 2 steps -1: equal senses would still prove two
    headings, but not two INDEPENDENT ones — the two floors would stay in
    lockstep forever and any "they rotate apart" claim would be vacuous. The
    control `test_the_same_heading_control_folds_both_bands_onto_one_pose`
    makes exactly that failure and shows this test catches it.

    A FULL STATE CYCLE, not a snapshot: every stepped frame is measured, so the
    per-frame step is checked N times rather than once across an interval.
    """
    seen, _ = _walk(autocam, tmp_path, "rot", 6)
    d1 = [(b[1][0] - a[1][0]) % POSES for a, b in zip(seen, seen[1:])]
    d2 = [(a[1][1] - b[1][1]) % POSES for a, b in zip(seen, seen[1:])]
    assert all(n > 0 for n in d1), (
        f"camera 1's heading did not advance at every step: {d1}")
    # EQUAL AND OPPOSITE, PER STEP, and this half needs no clock at all: both
    # headings come out of the SAME picture, so whichever frame that picture
    # is, camera 1's advance and camera 2's retreat are measured against each
    # other. A rail that rotated ONE camera and pointed both bands at it would
    # give d2 = -d1 rather than d2 = d1 and fail here.
    assert d1 == d2, (
        f"the two cameras are not counter-rotating in step: camera 1 advanced "
        f"{d1} while camera 2 retreated {d2} (from {[s[1] for s in seen]})")
    # ONE POSE PER FRAME, against the ROM's own counter — and the counter's
    # bracket is what makes this exact rather than flaky. Sample i's picture
    # came from a frame in [lo_i, hi_i], so the pose delta from sample 0 must
    # lie in [lo_i - hi_0, hi_i - lo_0].
    for i, sm in enumerate(seen[1:], 1):
        poses = (sm[1][0] - seen[0][1][0]) % POSES
        lo = (sm[0] - seen[0][4]) & 0xFFFF
        hi = (sm[4] - seen[0][0]) & 0xFFFF
        assert lo <= poses <= hi, (
            f"sample {i}: the pose advanced {poses} while the ROM's frame "
            f"counter advanced between {lo} and {hi} — camera 1 is not "
            f"stepping one pose per frame")
    # THE TWO HEADINGS MUST DIFFER SOMEWHERE, NOT EVERYWHERE — and that
    # correction came later. Equal-and-opposite counters MEET twice per turn
    # by construction (h1 = t, h2 = 128 - t coincide at t = 64 and t = 192), so
    # "never equal over a run" was never a property of the rail; an earlier run
    # simply started far from a crossing, and 2b's one-frame phase shift walked
    # into one. What matters is the SENSES above, which are asserted per step,
    # plus the fact that the run does resolve two DISTINCT headings at all — a
    # rail with one heading in both bands would have every sample equal, and
    # the sh2_same_heading control below is exactly that.
    differ = [s[1] for s in seen if s[1][0] != s[1][1]]
    assert len(differ) >= len(seen) - 1, (
        f"the two bands share a heading on {len(seen) - len(differ)} of "
        f"{len(seen)} samples — more than the single crossing frame the "
        f"counter-rotation passes through: {[s[1] for s in seen]}")


def test_the_same_heading_control_folds_both_bands_onto_one_pose(runner, tmp_path):
    """THE CONTROL for independent rotation. Camera 2's heading := camera 1's.

    Only the heading is folded — the two cameras still start in different
    places, so the position signal survives and the two claims fail separately.
    Recovered from the pixels by the same 256-candidate scoring the test above
    uses, so this is that test's exact negation.
    """
    runner.boot_rom(str(SAME_HEADING), frames=60)
    seen, _ = _walk(runner, tmp_path, "sameh", 3)
    assert all(s[1][0] == s[1][1] for s in seen), (
        f"the SAME_HEADING control still shows two different headings "
        f"{[s[1] for s in seen]} — the opposite-sense assertion is not "
        f"measuring the two bands' poses separately")
    assert all(s[2][0] != s[2][1] for s in seen), (
        f"the control also folded the POSITIONS {[s[2] for s in seen]} — it is "
        f"meant to kill the rotation signal alone")


# =============================================================================
# 5. THE OTHER HALF — both cameras DRIVE, at a constant 2 px/frame
# =============================================================================
def _integrate(pos, frac, h, sense, frames):
    """The rail's own drive model, re-implemented from the gated move LUT.

    Per frame, in cam_tick's order: the heading STEPS first (+1 for camera 1,
    -1 for camera 2), then each axis does `frac += move256[h]` and takes the
    HIGH byte of the 16-bit result as that frame's SIGNED integer delta; the
    position moves by it, masked to the world's period, and the low byte is
    kept as the carry into the next frame.

    An INDEPENDENT model — it shares no code with the ROM, which does the same
    arithmetic in 65816 across four macro expansions — so the comparison below
    is a real check of both.
    """
    x, y = pos
    fx, fy = frac
    out = []
    for _ in range(frames):
        h = (h + sense) % POSES
        vx, vy = struct.unpack("<hh", MOVE[h * 4:h * 4 + 4])
        fx = (fx + (vx & 0xFFFF)) & 0xFFFF
        dx = fx >> 8
        x = (x + (dx - 256 if dx >= 128 else dx)) & (WORLD_PX - 1)
        fx &= 0xFF
        fy = (fy + (vy & 0xFFFF)) & 0xFFFF
        dy = fy >> 8
        y = (y + (dy - 256 if dy >= 128 else dy)) & (WORLD_PX - 1)
        fy &= 0xFF
        out.append((x, y))
    return out


def test_both_cameras_drive_forward_along_their_heading(autocam, tmp_path):
    """Each band's POSITION, recovered from its pixels, against the drive model.

    THE MODEL IS INDEPENDENT. Python re-runs the 8.8 fractional accumulator
    from the gated `move256` LUT — `frac += vel`, high byte is the signed
    integer delta, keep the fraction — seeded once from the ROM's decided state
    at the first sample. Every position it is compared against comes off the
    FRAMEBUFFER, so this asserts that the camera the PPU is actually rendering
    from moved the way the design says, not that a DP word incremented.

    WHY THE FRACTION MATTERS, asserted rather than described: 2.0 px/frame does
    not decompose into equal integer steps at most headings, so the per-frame
    displacements are a MIXTURE of 1s, 2s and 3s whose running total tracks the
    real velocity. The test asserts the exact sequence — an implementation that
    rounded the velocity to an integer would produce a different, smoother-
    looking sequence and fail here, which is the translation jerk the
    accumulator exists to remove.

    BOTH CAMERAS, in both senses, because they rotate oppositely and therefore
    drive along diverging arcs; a model that only matched camera 1 would mean
    the second band's move-LUT index is wrong.
    """
    steps = 6
    seen, frac = _walk(autocam, tmp_path, "drive", steps)
    # THE CLOCK IS THE RECOVERED POSE, not the ROM's frame counter. Camera 1
    # steps exactly one pose per frame, so the pose delta between two samples
    # IS the number of ROM frames between them — and it comes out of the same
    # picture the positions do, which is what makes the two exactly aligned.
    # (The counter cannot do that here: taking a screenshot advances the
    # emulated frame by a varying amount, so the counter read beside a picture
    # brackets it rather than naming it — see _walk.)
    frames = (seen[-1][1][0] - seen[0][1][0]) % POSES
    assert frames >= steps, f"the run advanced only {frames} ROM frames"
    lo = (seen[-1][0] - seen[0][4]) & 0xFFFF
    hi = (seen[-1][4] - seen[0][0]) & 0xFFFF
    assert lo <= frames <= hi, (
        f"the pose clock says {frames} frames but the ROM's counter brackets "
        f"the run at [{lo}, {hi}] — the two clocks disagree")

    for band, sense in ((0, 1), (1, -1)):
        model = _integrate(seen[0][2][band], frac[band], seen[0][1][band],
                           sense, frames)
        for sm in seen[1:]:
            n = ((sm[1][0] - seen[0][1][0]) % POSES) - 1
            ps = sm[2]
            assert ps[band] == model[n], (
                f"band {band} is at {ps[band]} after {n + 1} ROM frames; the "
                f"8.8 accumulator model says {model[n]} (from {seen[0][2][band]}"
                f" at heading {seen[0][1][band]})")
        # Non-vacuity: the run must actually MOVE, and by ~2 px per frame.
        dist = [math.dist(a, b) for a, b in zip(model, model[1:])]
        assert all(d > 0 for d in dist), f"band {band} did not move: {model}"
        travelled = sum(dist)
        assert travelled > frames * (MOVE_SCALE / 256) * 0.8, (
            f"band {band} travelled {travelled:.1f} px over {frames} frames, "
            f"far short of the {MOVE_SCALE / 256} px/frame the LUT encodes")


def test_the_same_cam_control_folds_the_two_cameras_into_one(runner, tmp_path):
    """THE CONTROL for "two cameras". Both start position AND heading folded.

    With the same start and the same heading every frame, the two cameras take
    the same move-LUT entry every frame, so they are ONE camera rendered in two
    bands — and the states recovered from the two halves of the framebuffer
    must be identical at every sample. The shipping ROM's must not be.

    SH2_SAME_ORIGIN ALONE IS NOT THIS CONTROL any more, and that is a
    consequence of the cameras now driving rather than an omission: the earlier
    cameras never changed x, so folding the starts held; these drive along their
    headings, so
    folding the starts alone lets two different velocities pull them apart
    again within a few frames. Folding the heading is what makes the fold
    stick.
    """
    runner.boot_rom(str(SAME_CAM), frames=60)
    seen, _ = _walk(runner, tmp_path, "samecam", 3)
    assert all(s[1][0] == s[1][1] and s[2][0] == s[2][1] for s in seen), (
        f"the SAME_CAM control still shows two distinct cameras: "
        f"headings {[s[1] for s in seen]} positions {[s[2] for s in seen]}")


# =============================================================================
# 6. THE BANK STAMP — the four DASB bytes the VBlank stamper wrote
# =============================================================================
def test_the_dasb_banks_track_both_headings(autocam, tmp_path):
    """The four $43x7 bytes, read from the shadow sm_nmi_core MVNs to $4300.

    THE DESTINATION, not a mirror. cam_banks' only output is these four bytes;
    a debug copy elsewhere in WRAM would prove only that the stamper can write
    the same value twice.

    The heading each byte is checked against is the one RECOVERED FROM THE
    PIXELS, so the chain closes: the bank the stamper chose must be the bank
    whose slice contains the pose the PPU actually streamed.

    A SLICE CROSSING IS REQUIRED, not hoped for. Every heading in a 64-pose
    quarter shares a bank, so a stamper that emitted a constant would pass a
    short run inside one quarter. The run is driven until both bands' bytes
    have taken at least two distinct values — h1 rises and h2 falls, so they
    cross in opposite directions — and the test fails if it does not happen.
    """
    ab0 = _sym("ES_R_SH2_POSE256_AB_S0", None)["start"] >> 15
    cd0 = _sym("ES_R_SH2_POSE256_CD_S0", None)["start"] >> 15
    steps, seen = 0, []
    with autocam.frame_stepping():
        seed, _ = _state(autocam)
        near = list(seed)
        while steps < 200:
            dasb = tuple(_shadow_dasb(autocam, n)
                         for n in ("sh2ab1", "sh2cd1", "sh2ab2", "sh2cd2"))
            px = _shot(autocam, tmp_path, f"dasb{steps}")
            hs = []
            for b in (0, 1):
                h, near[b] = _recover(px, b, near[b])
                hs.append(h)
            seen.append((tuple(hs), dasb))
            assert dasb == (ab0 + (hs[0] >> 6), cd0 + (hs[0] >> 6),
                            ab0 + (hs[1] >> 6), cd0 + (hs[1] >> 6)), (
                f"the stamped DASB banks {dasb} do not match the headings "
                f"{hs} rendered on this frame (slice bases {ab0}, {cd0})")
            if (len({s[1][0] for s in seen}) > 1
                    and len({s[1][2] for s in seen}) > 1):
                break
            autocam.frame_step()
            steps += 1
    assert len({s[1][0] for s in seen}) > 1, (
        f"band 1's AB bank never changed across {len(seen)} samples "
        f"({[s[1][0] for s in seen]}) — a constant would pass this test")
    assert len({s[1][2] for s in seen}) > 1, (
        f"band 2's AB bank never changed across {len(seen)} samples")


# =============================================================================
# 7. THE SEAM — found from the picture, not from the declaration
# =============================================================================
def test_the_seam_is_where_the_declaration_says(fresh, tmp_path):
    """The scanline the handover happens on, SEARCHED FOR in the picture.

    A candidate seam S is a complete alternative rail: band 1 is rows [0, S)
    with its origin subtracted against bottom line S, band 2 is rows [S, 224)
    with pose index sy - S and bottom line 224. Scoring S against the frame
    therefore asks "which split does this picture actually show", and exactly
    one S may reproduce it.

    A CANDIDATE MUST BE EXPRESSIBLE OR THE SEARCH IS THEATRE. A pose is 112
    scanlines, so S != 112 needs rows a pose does not have — and the naive
    model, which simply refuses those, leaves 112 as the only candidate and
    "the seam is at 112" as a restatement of the pose length. The blob is
    contiguous, so a band whose repeat count ran past its pose would stream the
    NEXT heading's rows, and `_pose_at` models exactly that. Every S in the
    scanned range is then a real, renderable rail, and only the true one fits.

    Not computed from the screenshot's height: the active picture's top margin
    is asymmetric (7 above, 8 below), so anything derived from the raster is
    off by it. And not read off the colours the way the unrotated form did —
    those cameras sat still on their own stripes forever, while these drive across
    them, so the red channel is no longer a band marker.
    """
    with fresh.frame_stepping():
        cam, heads = _state(fresh, advanced=False)
        px = _shot(fresh, tmp_path, "seam")

    def explains(s):
        """Every 4th row, every 8th column, under the split-at-s model."""
        for sy in range(0, LINES, 4):
            band = 0 if sy < s else 1
            top, bot = (0, s) if band == 0 else (s, LINES)
            cx, cy = cam[band]
            a, b, c, d = _pose_at(heads[band], sy - top)
            row = sy + 1
            vx = ((a * -HALF_W) & ~63) + ((b * -bot) & ~63) + ((b * row) & ~63) \
                + (cx << 8) + a * 0
            vy = ((c * -HALF_W) & ~63) + ((d * -bot) & ~63) + ((d * row) & ~63) \
                + (cy << 8) + c * 0
            for sx in range(0, 256, 8):
                gx = vx + a * sx
                gy = vy + c * sx
                got = tuple(v >> 3 for v in px[sx, sy])
                if got in MARKER_COLORS:
                    continue            # a marker stands here, not the plane
                if got != COLORS[_tile_at(gx >> 8, gy >> 8) + 1]:
                    return False
        return True

    span = range(SEAM - 16, SEAM + 17)
    fits = [s for s in span if explains(s)]
    assert len(list(span)) > 1, "the candidate range collapsed to one value"
    assert fits == [SEAM], (
        f"the picture's band split is {fits}, not [{SEAM}] — every candidate "
        f"seam in {span.start}..{span.stop - 1} was scored against the frame")


# =============================================================================
# 8. POWER-ON FIDELITY — CLAUDE.md rule 5, asserted rather than commented
# =============================================================================
def test_the_rail_reads_nothing_it_never_wrote(runner):
    """No CPU-side read-before-write anywhere in volatile RAM, from power-on.

    THE MITIGATION THIS ASSERTS IS INVISIBLE TO EVERY OTHER TEST HERE.
    `cam_arm` zeroes its whole HDMA-table claim before stamping, because the
    DMA controller keeps fetching indirect-address bytes past each table's
    `$00` terminator — the slack is real hardware traffic. Deleting that loop
    left every other test in this module GREEN while the detector reported
    three uninitialised reads inside `sh2_cam`'s own claim.

    THE SURFACE WIDENED ONCE: the claim grew from 64 B to 96 B
    (six tables, two of them with band 2's skip prefix) and a second DP claim
    appeared — two headings and four fraction accumulators, all of which the
    first frame's `cam_ptrs`, `cam_banks` and `cam_drive` read. The scene's
    enter writes every one of them before cam_arm runs; this is what asserts
    that it really does.

    AND AGAIN, and the detector is whole-machine so it followed
    without a line of test code: two more DP claims (`mpp`'s 36-byte call frame
    and `sho`'s 18 bytes of bookkeeping), the 544-byte OAM shadow, and both OBJ
    palette claims. Two of those are exactly where a rule-5 slip would hide —
    `sho`'s watermark is the one byte that must survive between frames (obj_arm
    writes it before the first projection reads it), and the palettes are
    claimed sixteen words each while only one word of each is ever drawn, so
    obj_arm writes all thirty-two rather than leaving fifteen to power-on.

    The detector is Mesen's per-address access counters, armed from the reset
    vector by `load_rom_with_uninit_detection` (a plain load races the boot and
    reports false positives).
    """
    runner.load_rom_with_uninit_detection(str(ROM), frames=180)
    runner.assert_no_uninitialized_reads()


def test_the_whole_entity_table_is_seeded_and_not_just_the_live_count(runner):
    """The 40 records the SHIPPING build never ticks.

    `swm_arm` copies all SWM_MAX records out of ROM, not the SWM_N_SHIP the
    build ticks, and both `sh2_swarm.asm` and its `feature.toml` argue why: the
    cadence sweep and `make sh2-measure` poke the count UPWARD, so a record the
    shipping build never reads is one the sweep does, and power-on WRAM is
    random. Correct reasoning, and for a long time NOTHING asserted it:
    shortening the copy to the 24 live records left the whole suite green
    (19/19 across both split_h_2p modules), because the test above never pokes
    the count and the cadence gate's poked-to-64 test asserts only that the
    lockstep BREAKS, which garbage entities do just as well.

    That is the same failure shape as rule-5 compliance resting on a comment,
    recurring on the same rail, which is why it gets its own named test rather
    than a line inside the one above.

    THE ASSERTION IS THE WRITE COUNTER, and that is deliberate. The obvious
    remedy — poke the count to the capacity, run,
    `assert_no_uninitialized_reads()` — DOES NOT GO RED on the plant it was
    written for. Measured here on that identical plant (artifact md5
    `03f26866…`): Mesen LOGS seventeen
    `[CPU] Uninitialized memory read: $7E06xx` lines, and the assertion passes,
    because `get_uninitialized_reads` classifies from the per-address counters
    (`WriteCounter == 0 and ReadCounter > 0`) and `swm_ai` WRITES BACK every
    field of every record it steers on the same frame it reads them. A byte
    read from power-on garbage and then written is invisible to that
    classification for the rest of the run.

    So this reads the counter directly and asserts the seeding: after boot,
    EVERY byte of the entity-table claim must have been WRITTEN at least once.
    That is `swm_arm`'s contract stated in the output region it writes, it does
    not depend on the record ever being read, and on the plant it reports 320
    never-written bytes (the 40 records the shipping count leaves alone) rather
    than nothing.

    The poked run below stays because it asserts a different thing — that the
    whole machine is rule-5 clean while the SWEEP'S count is live, which is the
    regime `make sh2-measure` and the cadence gate actually drive and which no
    other test enters. It is not what catches a short seed.
    """
    runner.load_rom_with_uninit_detection(str(ROM), frames=60)
    counts = runner.get_access_counts(W)
    never = [SWM_ENTS + i for i in range(SWM_ENTS_BYTES)
             if counts[SWM_ENTS + i].WriteCounter == 0]
    assert not never, (
        f"{len(never)} of {SWM_ENTS_BYTES} bytes of the entity table were "
        f"never written since power-on — records "
        f"{sorted({(a - SWM_ENTS) // 8 for a in never})} hold power-on garbage "
        f"and the sweep reads them. First: "
        f"{', '.join(f'${a:04X}' for a in never[:8])}")
    runner.write_bytes(W, SWM_CTL, bytes([SWM_MAX & 0xFF, SWM_MAX >> 8]))
    runner.wait_frames(60)
    assert _u16(runner, SWM_CTL) == SWM_MAX, (
        "the live count did not stay poked — the sweep handle this test drives "
        "through is not the one the ROM reads")
    runner.assert_no_uninitialized_reads()
