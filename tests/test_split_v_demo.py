"""split_v_demo — the vertical window dual-view, asserted against what was drawn.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(90)`, which
lands on the ABSOLUTE frame 90 by construction.

WHAT THIS RAIL IS, and therefore what these cases have to prove. Its source
states four teachings, and `build_split_v_variants.sh` — not the README — says
where each one lives:

    1. a vertical split from the PPU window system   (default build)
    2. ONE VRAM copy, TWO cameras                    (default build)
    3. a DIAGONAL seam, WH0/WH2/WH3 per scanline     (-DDIAGONAL only)
    4. per-half OBJ CLIPPING                         (-DOBJ_CLIP only)

and its `-DNO_WINDOW` build is the non-vacuity control for (1). In the SuperForge
port 3 and 4 are runtime MODES over one composition and the control stays a
compile-out, so this module drives all four teachings through one
binary and reads the fifth — the collapse — from `build/svd_nowin.sfc`.

EVERY CLAIM HERE IS A PICTURE CLAIM, and that is forced rather than chosen.
The window system lives entirely downstream of VRAM, OAM and CGRAM: a
correct-looking OAM entry is byte-identical whether or not the seam cuts it
(test_the_obj_clip_is_invisible_to_oam asserts exactly that), and the two
cameras read ONE tilemap, so no VRAM read can tell a split screen from an
unsplit one. So the cases below predict the FRAME — every pixel of it, from
the two cameras, the seam, the mode and the level — and compare against the
screenshot.

THE ORACLE. `expect_frame()` rebuilds the picture from the scene's stated
facts: the 32-entry height map, the four-branch cell rule, the five BGR15
colours, the band half-width and the diagonal's base/slope, all written out
here rather than imported out of `tools/gen_svd_assets.py`. Generator and
oracle therefore share no code
and cannot agree with each other about a wrong landscape.

MEASURED HARNESS CONVENTIONS (this ROM, this core — the spec's note that Mesen
captures the 239-line overscan frame rather than the 224-line active area):

    frame               256 x 239
    active scanlines    screen y 7..230; world y = screen y - 7
    BGR15 -> RGB        v << 3 | v >> 2
    marker rows         screen y 183..190 for the ROM's PLY_Y = 176

Frame accounting: `advance` latches both pads and polls them at every frame
boundary, so state after advance(N, pad) reflects N ticks. Nothing here reads
hardware OAM against a per-frame oracle — the rail's state is the picture —
except the one case whose subject IS that OAM does not change.
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
ROM = BUILD / "split_v_demo.sfc"
NOWIN_ROM = BUILD / "svd_nowin.sfc"
MAP = json.loads((BUILD / "svd" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam

BOOT = 90                               # the module's absolute capture frame


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="demo"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_STAGE_CHR = _sym("ES_V_STAGE_CHR")["start"]     # VRAM words
V_STAGE_MAP = _sym("ES_V_STAGE_MAP")["start"]
V_OBJ_CHR = _sym("ES_V_OBJ_CHR")["start"]
C_STAGE_PAL = _sym("ES_C_STAGE_PAL")["start"]     # CGRAM word index
C_MARKER_PAL = _sym("ES_C_MARKER_PAL")["start"]
OAM_SHADOW = _sym("ES_OAM_SHADOW", scene=None)["start"]

# --- the scene's numbers, written out here (NOT imported out of the generator)
HMAP = (18, 18, 17, 16, 15, 13, 11, 9, 8, 8, 9, 11, 13, 15, 16, 17,
        17, 16, 15, 14, 14, 15, 16, 17, 17, 16, 15, 15, 16, 17, 18, 18)
GND_DIRT = 24
MTN_LO, MTN_HI = 6, 13
TILE_SKY, TILE_GRASS, TILE_MTN, TILE_DIRT = 1, 2, 3, 4

CAM_A0, CAM_B0 = 0, 192
SEAM0, SEAM_LO, SEAM_HI = 128, 64, 192
BAND_HW = 6
CAM_SPD = 2
DIAG_BASE, DIAG_SLOPE = 72, 0x0080
PLY_Y, P1_DX, P2_DX = 176, 4, 40

STAGE_BGR15 = (0x7FFF, 0x7F54, 0x02E0, 0x4A52, 0x1194)  # backdrop, sky, grass,
MARKER_BGR15 = 0x001F                                   # mountain, dirt / red

MODE_STRAIGHT, MODE_OBJCLIP, MODE_DIAG = 0, 1, 2

# --- measured harness geometry (see the module docstring) --------------------
FRAME_W, FRAME_H = 256, 239
ACTIVE_Y0, ACTIVE_LINES = 7, 224
MARK_Y0, MARK_Y1 = 183, 190             # the marker rows, inclusive


def rgb(bgr15):
    """BGR15 -> the core's 8-bit RGB. `v << 3 | v >> 2`, per the spec's tones."""
    r, g, b = bgr15 & 31, (bgr15 >> 5) & 31, (bgr15 >> 10) & 31
    return tuple(v << 3 | v >> 2 for v in (r, g, b))


WHITE = rgb(STAGE_BGR15[0])
RED = rgb(MARKER_BGR15)
STAGE_RGB = {i: rgb(STAGE_BGR15[i]) for i in range(1, 5)}


# --- the level oracle: the four-branch cell rule, in its own order ----------
def cell(col, row):
    if row < HMAP[col]:
        return TILE_SKY
    if row >= GND_DIRT:
        return TILE_DIRT
    if MTN_LO <= col < MTN_HI:
        return TILE_MTN
    return TILE_GRASS


def stage_rgb_at(cam, x, world_y):
    """What a BG layer scrolled to `cam` shows at screen column x, world row y.

    The map is 32 cells (256 px) wide and the cameras are masked to a byte, so
    the world is 256-px periodic — which is exactly why the two halves can show
    genuinely different vistas of ONE stage without running out of world.
    """
    col = ((cam + x) >> 3) & 31
    return STAGE_RGB[cell(col, world_y >> 3)]


def diag_seam_x(line):
    return DIAG_BASE + ((line * DIAG_SLOPE) >> 8)


def seam_at(line, seam, mode):
    return diag_seam_x(line) if mode == MODE_DIAG else seam


def expect_frame(cam_a=CAM_A0, cam_b=CAM_B0, seam=SEAM0, mode=MODE_STRAIGHT,
                 markers=True, window=True):
    """The whole 256x239 frame, predicted from the rail's state.

    Window 1 is [seam, 255]: BG1 is hidden INSIDE it, so it shows LEFT of the
    seam; BG2 is hidden OUTSIDE it, so it shows RIGHT. Window 2 is the band
    [seam-hw, seam+hw] and masks BOTH, so the BACKDROP shows there as the bar.
    OBJ is above every BG layer, and in the clip mode it is itself hidden
    inside window 1 — the whole of teaching 4, in one branch.

    `window=False` is the -DSVD_NOWIN control's picture: nothing is masked, so
    BG1 (the higher-priority opaque layer in Mode 1) fills the screen.
    """
    out = []
    for sy in range(FRAME_H):
        if not (ACTIVE_Y0 <= sy < ACTIVE_Y0 + ACTIVE_LINES):
            out.append([(0, 0, 0)] * FRAME_W)
            continue
        line = sy - ACTIVE_Y0
        s = seam_at(line, seam, mode)
        row = []
        for x in range(FRAME_W):
            if not window:
                row.append(stage_rgb_at(cam_a, x, line))
            elif s - BAND_HW <= x <= s + BAND_HW:
                row.append(WHITE)                       # the backdrop bar
            elif x < s:
                row.append(stage_rgb_at(cam_a, x, line))
            else:
                row.append(stage_rgb_at(cam_b, x, line))
        out.append(row)
    if markers and window:
        for mx in marker_columns(seam, mode):
            for sy in range(MARK_Y0, MARK_Y1 + 1):
                out[sy][mx] = RED
    elif markers and not window:
        for mx in marker_columns(seam, MODE_STRAIGHT):
            for sy in range(MARK_Y0, MARK_Y1 + 1):
                out[sy][mx] = RED
    return out


def marker_columns(seam, mode):
    """The marker pixels that survive the mode, as screen columns.

    P1 stands at seam - 4 and therefore STRADDLES the seam; P2 at seam + 40.
    In the clip mode OBJ is hidden inside window 1 = [seam, 255], so P1 keeps
    only its columns left of the seam and P2 disappears entirely.
    """
    cols = list(range(seam - P1_DX, seam - P1_DX + 8))
    cols += list(range(seam + P2_DX, seam + P2_DX + 8))
    if mode == MODE_OBJCLIP:
        cols = [c for c in cols if c < seam]
    return [c for c in cols if 0 <= c < FRAME_W]


# --- machine plumbing --------------------------------------------------------
@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle."""
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make split_v_demo` first")

    def _boot(rom=ROM, frames=BOOT):
        return Machine(str(rom)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


def frame_of(machine, name):
    path = machine.take_screenshot(str(BUILD / "shots" / f"svd_{name}.png"))
    with Image.open(path) as im:
        assert im.size == (FRAME_W, FRAME_H), f"frame size moved: {im.size}"
        raw = im.convert("RGB").tobytes()
    return [[tuple(raw[(y * FRAME_W + x) * 3:(y * FRAME_W + x) * 3 + 3])
             for x in range(FRAME_W)] for y in range(FRAME_H)]


def diff_pixels(got, want, y0=ACTIVE_Y0, y1=ACTIVE_Y0 + ACTIVE_LINES):
    return [(x, y) for y in range(y0, y1) for x in range(FRAME_W)
            if tuple(got[y][x]) != tuple(want[y][x])]


def drive(machine, frames, pad1=None, pad2=None):
    """Drive `frames` ticks, then ONE released settle frame.

    MEASURED on this ROM: the picture lags the tick by exactly one frame. The
    scene tick writes the cameras and the seam; svd_nmi_commit publishes them
    in the NEXT VBlank, so a screenshot taken at the park after advance(N, pad)
    shows N-1 ticks' worth of motion. One released frame closes the gap (5
    R-presses put the bar at 132, +1 idle at 133 = 128 + 5), and it adds no
    motion of its own because every driver here is gated on a held button.
    """
    machine.advance(frames, pad1=pad1, pad2=pad2)
    return machine.advance(1)


def press(machine, button, settle=3):
    """One fresh press (input publishes cur AND NOT prev), then release."""
    machine.advance(1, pad1={button: True})
    machine.advance(settle)
    return machine


def cycle_to(machine, mode):
    for _ in range(mode):
        press(machine, "a")
    return machine


def white_span(row_pixels):
    cols = [x for x, p in enumerate(row_pixels) if tuple(p) == WHITE]
    return (cols[0], cols[-1]) if cols else None


# =============================================================================
# uploads — the destination regions, against the numbers above
# =============================================================================
def test_the_stage_chr_is_four_solid_tiles_at_its_claimed_vram_base(fresh):
    """VRAM CHR: five 4bpp tiles, 0 empty and 1..4 solid colour indices 1..4.

    Decoded from the bitplanes here rather than compared to the blob: the blob
    is what the generator wrote, so a byte-match against it would only prove
    the DMA ran. What the rail needs is that a tilemap cell holding id N draws
    palette entry N, and that is a statement about the plane bits.
    """
    chr_bytes = fresh.read_bytes(V, V_STAGE_CHR * 2, 5 * 32)
    assert chr_bytes[:32] == b"\x00" * 32, "tile 0 must be empty (the pad)"
    for tile in range(1, 5):
        t = chr_bytes[tile * 32:(tile + 1) * 32]
        for row in range(8):
            planes = [t[row * 2], t[row * 2 + 1], t[16 + row * 2], t[16 + row * 2 + 1]]
            got = sum((1 << p) for p, v in enumerate(planes) if v == 0xFF)
            assert [v for v in planes if v not in (0x00, 0xFF)] == [], \
                f"tile {tile} row {row} is not solid: {planes}"
            assert got == tile, f"tile {tile} row {row} decodes to index {got}"


def test_the_shared_tilemap_is_the_declared_landscape_at_ONE_claimed_base(fresh):
    """All 1,024 tilemap words vs the rebuilt level — and nothing beside it.

    The second half is teaching 2: the split costs ONE copy of the stage, so
    the 32x32 map must appear in VRAM EXACTLY ONCE. BG1SC and BG2SC both name
    this base (a register nothing can read back), and this is the readable
    consequence — a rail that duplicated the stage per layer would have a
    second identical page somewhere in VRAM, and this case would find it.
    """
    words = fresh.read_bytes(V, V_STAGE_MAP * 2, 0x400 * 2)
    for row in range(32):
        for col in range(32):
            i = (row * 32 + col) * 2
            got = words[i] | (words[i + 1] << 8)
            assert got == cell(col, row), \
                f"tilemap cell ({col},{row}) = {got}, level says {cell(col, row)}"

    # THE WHOLE 2 KB is the probe, deliberately. A short prefix is degenerate
    # here: rows 0..7 are uniform sky (min hmap = 8), so the map's first 64
    # cells are 64 copies of the word 1 and match at every even offset in the
    # sky region — the periodic-BG trap in a new costume, and it read as 201
    # spurious "copies" the first time this case ran.
    whole = fresh.read_region(V)
    hits = [i for i in range(0, len(whole) - len(words), 2)
            if whole[i:i + len(words)] == words]
    assert hits == [V_STAGE_MAP * 2], \
        f"the stage tilemap appears at {hits}, expected exactly one copy"


def test_the_obj_chr_is_the_solid_marker_at_its_claimed_vram_base(fresh):
    obj = fresh.read_bytes(V, V_OBJ_CHR * 2, 32)
    for row in range(8):
        planes = [obj[row * 2], obj[row * 2 + 1], obj[16 + row * 2], obj[16 + row * 2 + 1]]
        assert planes == [0xFF, 0x00, 0x00, 0x00], \
            f"marker row {row} is not solid colour index 1: {planes}"


def test_both_palettes_reach_their_claimed_cgram_words(fresh):
    """Including WORD 0, which on this rail is the seam bar's colour.

    Read as literal BGR15 values, not as the palette blob: word 0
    being white is a claim about the RAIL (the bar is the backdrop showing
    through window 2), so it is asserted against the number the scene declares
    and not against whatever the generator emitted.
    """
    bg = fresh.read_bytes(C, C_STAGE_PAL * 2, 16 * 2)
    for i, want in enumerate(STAGE_BGR15):
        got = bg[i * 2] | (bg[i * 2 + 1] << 8)
        assert got == want, f"BG palette word {i} = ${got:04X}, want ${want:04X}"
    assert bg[0] | (bg[1] << 8) == 0x7FFF, "CGRAM word 0 must be white — it IS the seam bar"

    obj = fresh.read_bytes(C, C_MARKER_PAL * 2, 16 * 2)
    assert obj[2] | (obj[3] << 8) == MARKER_BGR15, "OBJ palette word 1 must be the marker red"


# =============================================================================
# the picture — the split itself, and its non-vacuity control
# =============================================================================
def test_the_boot_frame_is_the_predicted_two_camera_picture(fresh):
    """Every pixel of frame 90, predicted from (cam A 0, cam B 192, seam 128).

    This is the rail's first teaching in its strongest available form. The two
    halves are NOT merely different: each is the landscape at its OWN camera,
    pixel for pixel, with the backdrop band between them — so the case fails if
    either camera is wrong, if the split lands on the wrong column, if the
    window polarity is inverted (the halves would swap), or if the band is the
    wrong width.
    """
    got = frame_of(fresh, "boot")
    bad = diff_pixels(got, expect_frame())
    assert bad == [], f"{len(bad)} pixel(s) differ from the prediction, first {bad[:8]}"


def test_the_seam_bar_is_the_backdrop_on_every_active_scanline(fresh):
    """13 px of white — 2*hw+1 — at the seam, on all 224 lines, and nowhere else.

    Read per scanline rather than sampled: the bar is written by ONE HDMA
    channel whose two non-repeat entries cover 127 and 97 lines, so a wrong
    entry count would leave a correct-looking bar over part of the screen and
    none over the rest. A sample at midscreen cannot see that.
    """
    got = frame_of(fresh, "bar")
    for sy in range(ACTIVE_Y0, ACTIVE_Y0 + ACTIVE_LINES):
        if MARK_Y0 <= sy <= MARK_Y1:
            continue                    # the markers draw over the band here
        assert white_span(got[sy]) == (SEAM0 - BAND_HW, SEAM0 + BAND_HW), \
            f"scanline {sy}: bar span {white_span(got[sy])}"
        span = [x for x, p in enumerate(got[sy]) if tuple(p) == WHITE]
        assert span == list(range(SEAM0 - BAND_HW, SEAM0 + BAND_HW + 1)), \
            f"scanline {sy}: white is not one contiguous band: {span}"


def test_the_split_collapses_on_the_nowin_control(boot):
    """The non-vacuity control: -DSVD_NOWIN, and the two-region signature dies.

    Without this, "the halves differ" is satisfiable by any picture with detail
    on both sides of x = 128. Here the SAME source, with the window recipe
    compiled out, must render ONE camera across the whole screen and NO white
    bar anywhere — and the case asserts the positive form too, so it cannot
    pass on a black screen.
    """
    if not NOWIN_ROM.exists():
        pytest.fail(f"{NOWIN_ROM} missing — run `bash tools/build_svd_nowin.sh`")
    m = boot(rom=NOWIN_ROM)
    got = frame_of(m, "nowin")
    bad = diff_pixels(got, expect_frame(window=False))
    assert bad == [], f"the control is not the one-camera picture: {bad[:8]}"

    white = [(x, y) for y in range(ACTIVE_Y0, ACTIVE_Y0 + ACTIVE_LINES)
             for x in range(FRAME_W) if tuple(got[y][x]) == WHITE]
    assert white == [], f"the control still draws a seam bar at {white[:8]}"

    split = frame_of(boot(), "nowin_ref")
    assert diff_pixels(split, got), "the split ROM and the control render the same frame"


def test_converged_cameras_compose_ONE_continuous_picture(fresh):
    """Teaching 2, at the shape that proves it: fold camera B onto camera A.

    Both layers read one tilemap and one CHR page, so at cam B == cam A the two
    halves are literally the same bytes at the same offset — and the screen
    outside the band becomes indistinguishable from the no-window control's
    single-camera picture. A rail that had duplicated the stage per layer could
    still pass every other case here and fail this one the moment the copies
    diverged by a pixel.
    """
    drive(fresh, 96, pad2={"left": True})       # cam B 192 -> 0, at 2 px/frame
    got = frame_of(fresh, "converged")
    want = expect_frame(cam_a=CAM_A0, cam_b=CAM_A0)
    assert diff_pixels(got, want) == [], "the converged frame is not the prediction"

    one_cam = expect_frame(window=False)
    outside = [(x, y) for y in range(ACTIVE_Y0, ACTIVE_Y0 + ACTIVE_LINES)
               for x in range(FRAME_W)
               if not (SEAM0 - BAND_HW <= x <= SEAM0 + BAND_HW)
               and not (MARK_Y0 <= y <= MARK_Y1)
               and tuple(got[y][x]) != tuple(one_cam[y][x])]
    assert outside == [], \
        f"outside the band the halves do not compose one picture: {outside[:8]}"


# =============================================================================
# the two cameras and the seam — every transition, in both directions
# =============================================================================
def test_camera_a_pans_both_ways_and_moves_only_the_left_half(fresh):
    """P1's D-pad drives the LEFT camera and nothing else.

    Both directions, and the return leg asserts BYTE-IDENTITY with the boot
    frame — a camera that wrapped, clamped or stepped unevenly on the way back
    would land somewhere else. The right half is checked for identity at every
    stage, which is what makes this a statement about the SPLIT rather than
    about scrolling.
    """
    base = frame_of(fresh, "camA_base")
    drive(fresh, 20, pad1={"right": True})
    right = frame_of(fresh, "camA_right")
    assert diff_pixels(right, expect_frame(cam_a=20 * CAM_SPD)) == []
    assert [p for p in diff_pixels(right, base) if p[0] > SEAM0 + BAND_HW] == [], \
        "driving camera A changed the RIGHT half"

    drive(fresh, 20, pad1={"left": True})
    back = frame_of(fresh, "camA_back")
    assert diff_pixels(back, base) == [], "camera A did not return to its start"


def test_camera_b_pans_both_ways_and_moves_only_the_right_half(fresh):
    """P2's D-pad drives the RIGHT camera — the second pad, and the second
    camera, which is why `input2` is composed at all."""
    base = frame_of(fresh, "camB_base")
    drive(fresh, 20, pad2={"right": True})
    right = frame_of(fresh, "camB_right")
    assert diff_pixels(right, expect_frame(cam_b=CAM_B0 + 20 * CAM_SPD)) == []
    assert [p for p in diff_pixels(right, base) if p[0] < SEAM0 - BAND_HW] == [], \
        "driving camera B changed the LEFT half"

    drive(fresh, 20, pad2={"left": True})
    back = frame_of(fresh, "camB_back")
    assert diff_pixels(back, base) == [], "camera B did not return to its start"


def test_the_seam_sweeps_both_ways_and_clamps_at_both_bounds(fresh):
    """The bar's position read FROM THE PICTURE at four states, both directions.

    The clamp is the part a one-direction test ships broken: holding a shoulder
    into a bound must STOP the seam, and an unsigned underflow past the low
    bound would put it at 255 and collapse the right half in a single frame.
    Both bounds are driven past and then held.
    """
    got = frame_of(fresh, "seam0")
    assert white_span(got[ACTIVE_Y0 + 10]) == (SEAM0 - BAND_HW, SEAM0 + BAND_HW)

    drive(fresh, 40, pad1={"r": True})         # +1 px/frame -> 168
    got = frame_of(fresh, "seam_mid")
    assert white_span(got[ACTIVE_Y0 + 10]) == (168 - BAND_HW, 168 + BAND_HW)
    assert diff_pixels(got, expect_frame(seam=168)) == []

    drive(fresh, 60, pad1={"r": True})         # past SEAM_HI, then held
    got = frame_of(fresh, "seam_hi")
    assert white_span(got[ACTIVE_Y0 + 10]) == (SEAM_HI - BAND_HW, SEAM_HI + BAND_HW)
    assert diff_pixels(got, expect_frame(seam=SEAM_HI)) == []

    drive(fresh, 200, pad1={"l": True})        # past SEAM_LO, then held
    got = frame_of(fresh, "seam_lo")
    assert white_span(got[ACTIVE_Y0 + 10]) == (SEAM_LO - BAND_HW, SEAM_LO + BAND_HW)
    assert diff_pixels(got, expect_frame(seam=SEAM_LO)) == []

    drive(fresh, 64, pad1={"r": True})         # and back to the centre
    got = frame_of(fresh, "seam_home")
    assert white_span(got[ACTIVE_Y0 + 10]) == (SEAM0 - BAND_HW, SEAM0 + BAND_HW)


# =============================================================================
# the two teachings a -D build would otherwise hide
# =============================================================================
def test_the_obj_clip_cuts_the_straddling_marker_and_hides_the_far_one(fresh):
    """Teaching 4 (-DOBJ_CLIP), both directions of the transition.

    P1 stands at seam - 4 and so straddles the seam; P2 at seam + 40. With OBJ
    windowed inside window 1 = [seam, 255], P1 must keep exactly its four
    columns left of the seam and P2 must vanish. Measured on THIS ROM: 128 red
    pixels straight, 32 clipped.
    """
    straight = frame_of(fresh, "clip_off")
    reds = [(x, y) for y in range(FRAME_H) for x in range(FRAME_W)
            if tuple(straight[y][x]) == RED]
    assert len(reds) == 128, f"straight mode should show two whole markers, got {len(reds)}"

    press(fresh, "a")                           # -> MODE_OBJCLIP
    clipped = frame_of(fresh, "clip_on")
    assert diff_pixels(clipped, expect_frame(mode=MODE_OBJCLIP)) == []
    reds = sorted({x for y in range(FRAME_H) for x in range(FRAME_W)
                   if tuple(clipped[y][x]) == RED})
    assert reds == list(range(SEAM0 - P1_DX, SEAM0)), \
        f"the clip should leave only P1's columns left of the seam, got {reds}"

    press(fresh, "b")                           # -> back to MODE_STRAIGHT
    assert diff_pixels(frame_of(fresh, "clip_back"), straight) == [], \
        "leaving the clip mode did not restore both markers"


def test_the_obj_clip_is_invisible_to_oam(fresh):
    """The reason every case in this module reads the picture.

    The clip happens in the PPU's window logic, downstream of OAM, so the OAM
    table is BYTE-IDENTICAL in both modes — a marker that vanishes from the
    screen is still fully present in the sprite table, at the same coordinates,
    with the same tile and attributes. An OAM assertion would report the clip
    working and the clip broken with the same bytes; this case pins that as a
    fact rather than leaving it as a caveat.
    """
    before = fresh.read_bytes(O, 0, 544)
    press(fresh, "a")                           # -> MODE_OBJCLIP
    after = fresh.read_bytes(O, 0, 544)
    assert before == after, \
        "OAM changed across the clip transition — then an OAM test could see it"

    frame = frame_of(fresh, "clip_oam")
    reds = len([1 for y in range(FRAME_H) for x in range(FRAME_W)
                if tuple(frame[y][x]) == RED])
    assert reds == 32, f"the picture must still show the clip: {reds} red px"


def test_the_diagonal_slants_the_seam_per_scanline(fresh):
    """Teaching 3 (-DDIAGONAL): WH0/WH1/WH2/WH3 driven per line from ROM.

    The claim is per-SCANLINE, so it is asserted per scanline: the bar's centre
    on line s must be DIAG_BASE + (s * DIAG_SLOPE >> 8) for all 224 of them.
    A two-entry table (the straight seam's shape) would satisfy a midscreen
    sample and fail here on 222 lines.
    """
    cycle_to(fresh, MODE_DIAG)
    got = frame_of(fresh, "diagonal")
    assert diff_pixels(got, expect_frame(mode=MODE_DIAG)) == [], "the slant is not the prediction"

    for line in range(ACTIVE_LINES):
        sy = ACTIVE_Y0 + line
        if MARK_Y0 <= sy <= MARK_Y1:
            continue                            # markers draw over the band
        want = diag_seam_x(line)
        assert white_span(got[sy]) == (want - BAND_HW, want + BAND_HW), \
            f"line {line}: bar at {white_span(got[sy])}, want centre {want}"

    top, bot = white_span(got[ACTIVE_Y0]), white_span(got[ACTIVE_Y0 + ACTIVE_LINES - 1])
    assert bot[0] - top[0] == diag_seam_x(ACTIVE_LINES - 1) - DIAG_BASE > 100, \
        "the seam did not actually slant across the screen"


def test_the_mode_cycle_runs_in_both_directions(fresh):
    """straight -> clip -> diagonal -> straight forwards, and the reverse back.

    Identified from the PICTURE at every step, never from the mode word: a
    cycle that advanced the variable without re-applying the window recipe
    would pass a state read and show the wrong screen. Both directions, because
    a one-way cycle locks one order and ships the other untested.
    """
    def shape():
        f = frame_of(fresh, "cycle")
        span = white_span(f[ACTIVE_Y0 + 10])
        slanted = white_span(f[ACTIVE_Y0 + 200]) != span
        reds = len([1 for y in range(FRAME_H) for x in range(FRAME_W)
                    if tuple(f[y][x]) == RED])
        return ("diag" if slanted else "clip" if reds == 32 else "straight")

    assert shape() == "straight"
    press(fresh, "a"); assert shape() == "clip"
    press(fresh, "a"); assert shape() == "diag"
    press(fresh, "a"); assert shape() == "straight"
    press(fresh, "b"); assert shape() == "diag"
    press(fresh, "b"); assert shape() == "clip"
    press(fresh, "b"); assert shape() == "straight"


# =============================================================================
# rest
# =============================================================================
def test_sixty_idle_frames_are_byte_identical(fresh):
    """Nothing moves without input — including the seam channel's table, which
    is rebuilt in every VBlank whether or not the seam changed."""
    first = frame_of(fresh, "idle_a")
    fresh.advance(60)
    assert diff_pixels(frame_of(fresh, "idle_b"), first, 0, FRAME_H) == []


def test_the_markers_are_staged_into_the_shadow_not_hardware_oam(fresh):
    """The feature's own output region: the OAM shadow the tick writes.

    Both markers sit at their claimed slots with the tile, attribute and Y the
    arm wrote once, and the X the tick derives from the live seam. Read from
    the SHADOW rather than from hardware OAM, which the
    engine's blanket VBlank DMA would make true for any staging at all.
    """
    W = MemoryType.SnesWorkRam
    p1 = _sym("ES_O_MARKER_P1")["start"]
    p2 = _sym("ES_O_MARKER_P2")["start"]
    shadow = fresh.read_bytes(W, OAM_SHADOW + p1 * 4, 8)
    assert shadow[0] == (SEAM0 - P1_DX) & 0xFF and shadow[1] == PLY_Y
    assert shadow[4] == (SEAM0 + P2_DX) & 0xFF and shadow[5] == PLY_Y
    assert shadow[2] == 0 and shadow[3] == 48, "tile/attr: tile 0, priority 3, palette 0"
    assert p2 == p1 + 1
    hi = fresh.read_bytes(W, OAM_SHADOW + 512 + p1 // 4, 1)[0]
    assert hi == 0, "both markers are on screen and 8x8, so every hi-table bit is clear"
