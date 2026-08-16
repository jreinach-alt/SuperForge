"""split_h_persp_demo — TWO PERSPECTIVE cameras over one world, proven in pixels.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)` — an
absolute frame by construction — and every drive is a fixed per-frame input
list, so the whole trajectory is a pure function of the replay triple.

WHAT THIS RAIL IS:

    P1  the two bands are DISTINCT cameras (and collapse under the control)
    P2  each band animates on its OWN driver
    P3  the seam is a clean single scanline
    P4  band 2 samples a different-coloured world region — an independent
        world POSITION, not merely a different zoom of the same spot
        (folded under the control)
    P5  the scene is temporally stable across consecutive frames

All five are named cases below. **P5 is here as an assertion and NOT as
machinery**: the reference needs a double-buffer apply-hook rule and a
`-DFIXED_BUFFER_SPLICE` control to earn it, because there camera A is a LIVE
per-scanline solve that flips a buffer every rebuild. In SuperForge both cameras
are precomputed by construction — their poses are ROM — so there is nothing to
flip and stability is a property of the design rather than a bug that was
fixed. The spec records that delta; the case stays because "the picture does
not flicker" is still a claim a reader wants asserted.

THE HEADLINE PROOF IS A WHOLE-PICTURE PREDICTION. `test_the_whole_picture_is
_one_world_through_two_perspective_cameras` predicts all 224 rows x 256 pixels
from ONE blob through Mesen's own Mode 7 transform (tests/shp_predict.py, read
out of SnesPpu.cpp), switching pose SET and origin at the declared seam. That
single assertion carries P1, P3 and "one shared world" at once and is strictly
stronger than any period measurement:

  * "one shared world" is not a claim a period can make — two bands would look
    identical whether they sampled one map or two copies. The prediction feeds
    both bands from the SAME 32 KB blob, so a second copy, a wrong tilemap
    row, a wrong CHR byte or a wrong palette index would each fail it;
  * the seam is exact rather than approximate: the prediction switches at the
    declared scanline, so a seam one line early or late mismatches two rows;
  * P1 is over 57,344 pixels rather than over the length of a row's first run.

AND ON A PERSPECTIVE RAIL THE PREDICTION IS NOT OPTIONAL. The matrix-band pair
could fall back on run lengths because a flat band's period is one integer for
the whole band. Here the scale ramps every scanline: a 32-px world checker
SQUARE is 32*256/S(k) px wide on screen, so camera A's walks 25.6 px at the top
of its band to 85.3 px at the bottom, and is an integer on almost no row in
between. A run-length assertion could only be taken at the two ends and only
approximately.

THE ANIMATION INDICES ARE NEVER READ AS VARIABLES. `shp_cam` keeps both in DP
and a test could read them in one call — which is exactly the proxy-variable
move rule 2 forbids, because the whole question is whether an index reaches
M7A-M7D through a ROM pose and an HDMA index table. Every drive case here
reads PIXELS; the table cases read the WRAM the DMA controller fetches.

FRAME ACCOUNTING (measured here, not inherited). A pad held through
`advance(N)` reaches the picture N - 1 times: the main loop's tick steps the
index, the NEXT VBlank's hook points the band's index table at the new pose,
and the frame after that renders it — the constant one-commit presentation lag
of the park point. Calibrated by driving held = 1, 3 and 6 and solving for the
heading the picture shows: 0, 2, 5. `DRIVE_LAG` below.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from machine import Machine, MemoryType                        # noqa: E402
import shp_predict as P                                        # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "split_h_persp_demo.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "shp" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="persp"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


def _chan(name):
    for c in MAP["scenes"]["persp"]["channels"]:
        if c["name"] == name:
            return c
    raise KeyError(f"{name} is not an emitted channel")


def _rom(name):
    """A ROM claim's RUNTIME address, not its file offset.

    The map's `start` is the offset into the .sfc; the emitted `_ADDR`/`_BANK`
    symbols the ASM actually uses are the LoROM decoding of it — bank
    `off >> 15`, address `$8000 | (off & $7FFF)`. Re-derived here from the
    claim rather than copied out of the generated .inc, so a claim that
    moved shows up as a wrong address instead of as a stale constant."""
    p = _sym(name, scene=None)
    return {"addr": 0x8000 | (p["start"] & 0x7FFF),
            "bank": p["start"] >> 15, "size": p["size"]}


def _wram_bank(placement):
    """A WRAM claim's bank byte — the low 64 KB of WRAM is $7E."""
    return 0x7E + (placement["start"] >> 16)


V_M7 = _sym("ES_V_M7")["start"]                  # the pinned Mode 7 region
C_PAL = _sym("ES_C_SHP_PAL")["start"]            # CGRAM words
PAL_WORDS = _sym("ES_C_SHP_PAL")["size"]
TBL = _sym("ES_SHP_TBL")["start"]                # WRAM: all six HDMA tables
TBL_SIZE = _sym("ES_SHP_TBL")["size"]
SHDW = _sym("ES_SM_HDMA", scene=None)["start"]   # scene_mgr's channel shadow
SHDW_SIZE = _sym("ES_SM_HDMA", scene=None)["size"]
SHDW_CH = SHDW_SIZE // 8

CH_AB1, CH_CD1 = _chan("shpab1"), _chan("shpcd1")
CH_AB2, CH_CD2 = _chan("shpab2"), _chan("shpcd2")
CH_XY, CH_HV = _chan("shpxy"), _chan("shphv")

# shp_cam.asm's own table layout: six slots, 16 B apart.
SLOT = 16
IDX_AB1, IDX_CD1, IDX_AB2, IDX_CD2, OTBL_XY, OTBL_HV = (TBL + i * SLOT
                                                        for i in range(6))

# --- the rail's geometry, restated here rather than imported ------------------
# templates/split_h_persp_demo/main.asm:108/109/115 (SEAM, PV_L0, PV_L1),
# :140-141 (camera A's scales), :169 (camera B's far scale), :187 (KPOSES).
SEAM = 112
LINES = P.PICTURE_LINES
HALF_W = 128
POS_AX = POS_AY = P.WORLD_PX // 2                # the COOL stripe's centre
STRIPE_PX = 32 * P.TILE_PX                       # the generator's STRIPE
POS_BX, POS_BY = POS_AX + STRIPE_PX, POS_AY      # the WARM stripe's centre

HEADINGS, ZOOMS = 64, 8
HEAD_0, ZOOM_0 = 0, ZOOMS // 2                   # scenes/persp.asm's seeds
ZOOM_FLOOR, ZOOM_CEIL = 0, ZOOMS - 1

BOOT = 90                       # the module's absolute boot frame
DRIVE_LAG = 1                   # held N frames -> N - 1 steps in the picture

RIGHT, LEFT = {"right": True}, {"left": True}
UP, DOWN = {"up": True}, {"down": True}

# --- the blobs ---------------------------------------------------------------
BLOB = (ASSETS / "shp_map.bin").read_bytes()
PAL = (ASSETS / "shp_pal.bin").read_bytes()
CGRAM_RGB = P.load_palette(PAL)
POSE_A_AB = P.read_poses(ASSETS / "shp_poseA_ab.bin")
POSE_A_CD = P.read_poses(ASSETS / "shp_poseA_cd.bin")
POSE_B_AB = P.read_poses(ASSETS / "shp_poseB_ab.bin")
POSE_B_CD = P.read_poses(ASSETS / "shp_poseB_cd.bin")


def _matrix_of_row(head, zoom):
    """(A,B,C,D) per picture row — band 1 from camera A's heading set, band 2
    from camera B's zoom set, each BAND-LOCAL (index 0 is the band's own first
    scanline, which is what restarts the ramp at the seam)."""
    def f(r):
        if r < SEAM:
            ab, cd = POSE_A_AB[head][r], POSE_A_CD[head][r]
        else:
            ab, cd = POSE_B_AB[zoom][r - SEAM], POSE_B_CD[zoom][r - SEAM]
        return (ab[0], ab[1], cd[0], cd[1])
    return f


def _origin_of_row(r):
    """(centre_x, centre_y, hofs, vofs) — the per-band world position, pinned
    to that band's OWN bottom scanline (shp_cam.asm's cam_origins)."""
    if r < SEAM:
        return (POS_AX, POS_AY, POS_AX - HALF_W, POS_AY - SEAM)
    return (POS_BX, POS_BY, POS_BX - HALF_W, POS_BY - LINES)


def _boot(frames=BOOT, drives=()):
    """A Machine parked on an ABSOLUTE frame, after a fixed input script."""
    m = Machine(str(ROM)).advance(frames)
    for n, pad in drives:
        m.advance(n, pad1=pad)
    return m


def _shot(tmp_path, name, frames=BOOT, drives=()):
    m = _boot(frames, drives)
    try:
        return Image.open(m.screenshot(str(tmp_path / f"{name}.png")))
    finally:
        m.close()


def _mismatched_rows(image, head, zoom, real_y_bias=P.REAL_Y_BIAS):
    mat = _matrix_of_row(head, zoom)
    return [r for r in range(LINES)
            if P.predict_row(BLOB, CGRAM_RGB, r, *mat(r), *_origin_of_row(r),
                             real_y_bias=real_y_bias) != P.actual_row(image, r)]


# =============================================================================
# the uploads — the destination regions, byte for byte
# =============================================================================
def test_the_plane_in_vram_is_the_blob_byte_for_byte():
    """The DESTINATION region, not a downstream consumer of it. shp_floor's one
    mode-1 DMA claims to stream 32,768 interleaved bytes into the pinned Mode 7
    region; this reads them back out of VRAM."""
    m = _boot()
    try:
        got = m.read_bytes(V, V_M7 * 2, len(BLOB))
    finally:
        m.close()
    assert got == BLOB, (
        f"{sum(a != b for a, b in zip(got, BLOB))} of {len(BLOB)} VRAM bytes "
        f"differ from the blob the ROM .incbins")


def test_the_five_claimed_cgram_words_are_the_palette():
    """All FIVE claimed words, including word 0 — the Mode 7 BACKDROP slot the
    plane never lets render, so no pixel assertion in this module can reach it.
    That is the whole reason this case is separate from the picture cases."""
    m = _boot()
    try:
        got = m.read_bytes(C, C_PAL * 2, PAL_WORDS * 2)
    finally:
        m.close()
    assert got == PAL
    reds = [w & 31 for w in
            (PAL[i] | (PAL[i + 1] << 8) for i in range(0, len(PAL), 2))]
    assert reds[1] == reds[2] == 0, "the COOL pair must carry no red"
    assert reds[3] > 0 and reds[4] > 0, "the WARM pair must carry red"


def test_the_map_is_the_reference_world():
    """A THIRD derivation of the world's stated rule, sharing no code with
    tools/gen_split_h_persp_assets.py — so a generator bug and a test bug
    cannot agree with each other. The vendored the reference blob the generator gates
    against is the fourth independent statement of the same bytes.

    `templates/split_h_persp_demo/assets/gen_map.py`: tile (row, col) is
    `((row//4) ^ (col//4)) & 1` plus 2 when `((col+16)//32) & 1`; CHR is four
    solid 8bpp tiles, tile k of palette index k+1; the halves are
    byte-interleaved."""
    t = P.MAP_T
    tilemap = bytearray(t * t)
    for row in range(t):
        for col in range(t):
            parity = ((row // 4) ^ (col // 4)) & 1
            warm = ((col + 16) // 32) & 1
            tilemap[row * t + col] = parity + (2 if warm else 0)
    chrb = bytearray(t * t)
    for k in range(4):
        chrb[k * 64:(k + 1) * 64] = bytes([k + 1]) * 64
    want = bytearray(2 * t * t)
    want[0::2] = tilemap
    want[1::2] = chrb
    assert BLOB == bytes(want)


# =============================================================================
# the HDMA tables — the WRAM the DMA controller fetches
# =============================================================================
def test_the_index_tables_are_the_declared_band_shape():
    """Band 1's table ENDS at the seam; band 2's opens with a NON-repeat skip
    entry and starts streaming there. That asymmetry IS the split, and the
    REPEAT bit is what makes each band a per-scanline trapezoid — a cleared
    bit 7 would hold one matrix for the whole band."""
    m = _boot()
    try:
        tbl = m.read_bytes(W, TBL, TBL_SIZE)
    finally:
        m.close()

    def at(addr, n):
        return tbl[addr - TBL: addr - TBL + n]

    a_ab = _rom("ES_R_SHP_POSEA_AB")["addr"]
    a_cd = _rom("ES_R_SHP_POSEA_CD")["addr"]
    b_ab = _rom("ES_R_SHP_POSEB_AB")["addr"]
    b_cd = _rom("ES_R_SHP_POSEB_CD")["addr"]
    stride = SEAM * 4

    for tab, base in ((IDX_AB1, a_ab), (IDX_CD1, a_cd)):
        e = at(tab, 4)
        assert e[0] == 0x80 | SEAM, f"band 1 count byte {e[0]:#04x}: repeat|112"
        ptr = base + HEAD_0 * stride
        assert e[1] | (e[2] << 8) == ptr
        assert e[3] == 0, "band 1's channel must END at the seam"

    for tab, base in ((IDX_AB2, b_ab), (IDX_CD2, b_cd)):
        e = at(tab, 7)
        assert e[0] == SEAM, "band 2's skip prefix must be NON-repeat"
        assert e[1] | (e[2] << 8) == base, "the skip aims at the set base"
        assert e[3] == 0x80 | SEAM
        assert e[4] | (e[5] << 8) == base + ZOOM_0 * stride
        assert e[6] == 0


def test_the_origin_tables_carry_two_world_positions():
    """The per-band origin, which is the rail's POSITION claim expressed in the
    bytes the controller reads. NON-repeat counts: 112 then 1 then terminate,
    so band 2's values are latched at the seam and held to the bottom."""
    m = _boot()
    try:
        tbl = m.read_bytes(W, TBL, TBL_SIZE)
    finally:
        m.close()

    def at(addr, n):
        return tbl[addr - TBL: addr - TBL + n]

    def words(b):
        return [b[i] | (b[i + 1] << 8) for i in range(0, len(b), 2)]

    xy, hv = at(OTBL_XY, 11), at(OTBL_HV, 11)
    for t in (xy, hv):
        assert (t[0], t[5], t[10]) == (SEAM, 1, 0), "non-repeat, then terminate"
    assert words(xy[1:5]) == [POS_AX, POS_AY]
    assert words(xy[6:10]) == [POS_BX, POS_BY]
    assert words(hv[1:5]) == [POS_AX - HALF_W, POS_AY - SEAM]
    assert words(hv[6:10]) == [POS_BX - HALF_W, POS_BY - LINES]


def test_the_channel_shadow_matches_the_allocators_answers():
    """DMAP / BBAD / A1B / A1T / DASB per channel, against the values the
    ALLOCATOR emitted — the register file the NMI MVNs to $4300."""
    m = _boot()
    try:
        shdw = m.read_bytes(W, SHDW, SHDW_SIZE)
    finally:
        m.close()
    tbl_bank = _wram_bank(_sym("ES_SHP_TBL"))

    def check(ch, table, dasb=None):
        o = ch["ch"] * SHDW_CH
        assert shdw[o] == ch["dmap"], f"{ch['name']} DMAP"
        assert shdw[o + 1] == ch["bbad"], f"{ch['name']} BBAD"
        assert shdw[o + 2] | (shdw[o + 3] << 8) == table, f"{ch['name']} A1T"
        assert shdw[o + 4] == tbl_bank, f"{ch['name']} A1B"
        if dasb is not None:
            assert shdw[o + 7] == dasb, f"{ch['name']} DASB"

    check(CH_AB1, IDX_AB1, _rom("ES_R_SHP_POSEA_AB")["bank"])
    check(CH_CD1, IDX_CD1, _rom("ES_R_SHP_POSEA_CD")["bank"])
    check(CH_AB2, IDX_AB2, _rom("ES_R_SHP_POSEB_AB")["bank"])
    check(CH_CD2, IDX_CD2, _rom("ES_R_SHP_POSEB_CD")["bank"])
    check(CH_XY, OTBL_XY)
    check(CH_HV, OTBL_HV)
    # the PRIORITY contract, in the emitted numbers: band 2 BELOW band 1, so
    # its line-0 stray unit is masked by band 1's proper write in the same
    # HBlank (shp_cam.asm's .assert, re-read here from the map).
    assert CH_AB2["ch"] < CH_AB1["ch"]
    assert CH_CD2["ch"] < CH_CD1["ch"]


def test_the_table_slack_past_the_terminator_is_written():
    """cam_arm's declared init contract. The controller's terminator processing
    still fetches indirect-address bytes AFTER the $00, and power-on WRAM is
    random — so every byte of the claim must have been written. This is
    invisible to any rendered frame, which is why it needs a case of its own."""
    m = _boot()
    try:
        tbl = m.read_bytes(W, TBL, TBL_SIZE)
    finally:
        m.close()
    # the four index tables' slack and the two origin tables' tails
    for base, used in ((IDX_AB1, 4), (IDX_CD1, 4), (IDX_AB2, 7), (IDX_CD2, 7),
                       (OTBL_XY, 11), (OTBL_HV, 11)):
        off = base - TBL
        assert tbl[off + used: off + SLOT] == bytes(SLOT - used), (
            f"slack past the table at {base:#06x} is not the zero cam_arm wrote")


# =============================================================================
# the picture
# =============================================================================
def test_the_frame_geometry_is_the_one_this_predictor_assumes(tmp_path):
    """MEASURED, not inherited. Sweep the realY bias against the boot frame and
    require EXACTLY ONE candidate to describe every row — which is what makes
    `REAL_Y_BIAS` a fact about the machine rather than a fitted constant."""
    im = _shot(tmp_path, "geom")
    counts = {b: len(_mismatched_rows(im, HEAD_0, ZOOM_0, real_y_bias=b))
              for b in range(-2, 4)}
    zeros = [b for b, n in counts.items() if n == 0]
    assert zeros == [P.REAL_Y_BIAS], f"bias sweep: {counts}"


def test_the_whole_picture_is_one_world_through_two_perspective_cameras(tmp_path):
    """THE headline. All 224 rows x 256 px predicted from ONE blob, switching
    pose SET and origin at the declared seam. Carries P1, P3 and the shared
    world at once."""
    im = _shot(tmp_path, "boot")
    bad = _mismatched_rows(im, HEAD_0, ZOOM_0)
    assert bad == [], f"{len(bad)} rows mismatch the prediction: {bad[:8]}"


def test_the_two_bands_are_different_trapezoids(tmp_path):
    """P1, in the rail's own vocabulary. A per-scanline camera's signal is the
    RAMP, so this compares the two bands' transition-count profiles rather than
    one period: each band's count must FALL down the band (a floor receding is
    finer at the top), and the two bands must ramp at measurably different
    RATES — which is what "different perspective parameters" means on screen.

    THE MEASURE IS THE TOP/BOTTOM RATIO, NOT THE SPAN, and the difference was
    MEASURED rather than chosen. `s_far/s_near` is a scale property and a
    rotation does not change it, but a rotation DOES change how many checker
    edges a row crosses — so the span `b[0] - b[-1]` moves under rotation and
    the ratio does not. The `shp-band2-streams-camera-as-set` plant proved it:
    with band 2 streaming camera A's set at heading 4, the spans read 6 and 8
    (a span assertion PASSES) while the ratios read 3.00 and 3.00 (a ratio
    assertion fails). A test name is a contract, and "different trapezoids"
    has to mean different ramps rather than different edge counts."""
    im = _shot(tmp_path, "bands")
    b1 = [P.transitions(im, r) for r in range(SEAM)]
    b2 = [P.transitions(im, r) for r in range(SEAM, LINES)]
    assert b1[0] > b1[-1] * 2, f"band 1 does not recede: {b1[0]} -> {b1[-1]}"
    assert b2[0] > b2[-1] * 2, f"band 2 does not recede: {b2[0]} -> {b2[-1]}"
    r1, r2 = b1[0] / b1[-1], b2[0] / b2[-1]
    assert r2 > r1 * 2, (
        f"the two bands ramp alike: A {b1[0]}->{b1[-1]} (x{r1:.2f}), "
        f"B {b2[0]}->{b2[-1]} (x{r2:.2f})")
    differing = sum(1 for a, b in zip(b1, b2) if a != b)
    assert differing > SEAM // 4, (
        f"only {differing} of {SEAM} band-local rows differ between the bands")


def test_the_seam_is_a_single_scanline_where_the_declaration_puts_it(tmp_path):
    """P3. The transition profile falls monotonically inside each band and
    JUMPS once — at the declared seam and nowhere else. One row wide."""
    im = _shot(tmp_path, "seam")
    prof = [P.transitions(im, r) for r in range(LINES)]
    jumps = [r for r in range(1, LINES) if prof[r] > prof[r - 1]]
    assert jumps == [SEAM], f"profile rises at {jumps}, expected only {SEAM}"


def test_each_band_looks_at_its_own_world_stripe(tmp_path):
    """P4, and it is ORTHOGONAL to P1 by construction: the warm checker pair is
    the cool pair plus red, so the two stripes are identical in the period
    signal and differ only in the red channel. Band 1's camera sits on a cool
    stripe (red 0) and band 2's one full stripe east on a warm one."""
    im = _shot(tmp_path, "stripe")
    a = P.mean_red(im, 0, SEAM)
    b = P.mean_red(im, SEAM, LINES)
    assert a < 16, f"band 1 carries red ({a:.1f}) — it is off the cool stripe"
    assert b > 96, f"band 2 carries no red ({b:.1f}) — it is off the warm stripe"


def test_the_picture_is_byte_identical_across_idle_frames(tmp_path):
    """P5. With no button held nothing in this ROM moves: both pose pointers
    are re-stamped every VBlank from unchanged indices, so consecutive frames
    must be the SAME bytes. There is no double buffer here to desync — see the
    module docstring for why that lesson does not port as machinery."""
    m = _boot()
    try:
        a = Path(m.screenshot(str(tmp_path / "idle_a.png"))).read_bytes()
        m.advance(90)
        b = Path(m.screenshot(str(tmp_path / "idle_b.png"))).read_bytes()
    finally:
        m.close()
    assert a == b, "the picture changed across 90 idle frames"


# =============================================================================
# the two live axes — P2, driven in BOTH directions
# =============================================================================
@pytest.mark.parametrize("held", [3, 6, 11])
def test_holding_right_rotates_camera_a_only(tmp_path, held):
    """P2, half one. The picture is predicted at the EXACT heading the drive
    reaches — never read out of DP — and band 2's rows are asserted UNCHANGED
    in the same frame, which is what makes this "camera A's own driver" rather
    than "something moved"."""
    boot = _shot(tmp_path, f"r{held}_boot")
    im = _shot(tmp_path, f"r{held}", drives=((held, RIGHT),))
    head = (HEAD_0 + held - DRIVE_LAG) % HEADINGS
    assert _mismatched_rows(im, head, ZOOM_0) == [], (
        f"held right {held} does not render heading {head}")
    assert head != HEAD_0, "the drive must actually move camera A"
    for r in range(SEAM):
        if P.actual_row(im, r) != P.actual_row(boot, r):
            break
    else:
        pytest.fail("band 1 did not change at all")
    for r in range(SEAM, LINES):
        assert P.actual_row(im, r) == P.actual_row(boot, r), (
            f"band 2 row {r} moved while only camera A was driven")


@pytest.mark.parametrize("held,want", [(2, ZOOM_0 + 1), (4, ZOOM_0 + 3)])
def test_holding_up_zooms_camera_b_only(tmp_path, held, want):
    """P2, half two — the mirror, on the OTHER axis. Band 1's rows must not
    move while camera B's zoom is driven."""
    boot = _shot(tmp_path, f"u{held}_boot")
    im = _shot(tmp_path, f"u{held}", drives=((held, UP),))
    assert _mismatched_rows(im, HEAD_0, want) == [], (
        f"held up {held} does not render zoom {want}")
    for r in range(SEAM):
        assert P.actual_row(im, r) == P.actual_row(boot, r), (
            f"band 1 row {r} moved while only camera B was driven")
    for r in range(SEAM, LINES):
        if P.actual_row(im, r) != P.actual_row(boot, r):
            break
    else:
        pytest.fail("band 2 did not change at all")


def test_the_heading_walks_forward_and_back_to_where_it_started(tmp_path):
    """The state cycle on camera A's axis, driven in BOTH directions and
    returned to its start — the rule-1 sub-rule the recorded streaming bug
    codified. A rail that only ever stepped one way could have a broken
    decrement and pass every case above."""
    boot = _shot(tmp_path, "cyc_boot")
    out = _shot(tmp_path, "cyc_out", drives=((9, RIGHT),))
    assert _mismatched_rows(out, (HEAD_0 + 9 - DRIVE_LAG) % HEADINGS,
                            ZOOM_0) == []
    # 9 right then 9 left returns the STATE to 0; the trailing idle frame is
    # what lets that state reach the PICTURE (DRIVE_LAG, measured above).
    back = _shot(tmp_path, "cyc_back",
                 drives=((9, RIGHT), (9, LEFT), (1, None)))
    assert _mismatched_rows(back, HEAD_0, ZOOM_0) == [], (
        "walking the heading back does not restore the boot picture")
    assert P.actual_frame(back) == P.actual_frame(boot)


def test_the_heading_wraps_rather_than_running_off_its_set(tmp_path):
    """A heading is CYCLIC: driving Left from 0 must land on the set's last
    pose, not on a pointer below the blob's base. Predicted at that pose."""
    im = _shot(tmp_path, "wrap", drives=((3, LEFT),))
    assert _mismatched_rows(im, (HEAD_0 - 3 + DRIVE_LAG) % HEADINGS,
                            ZOOM_0) == []


def test_the_zoom_clamps_at_both_ends_and_does_not_wrap(tmp_path):
    """A zoom is a SEGMENT, not a cycle. Held past either end the picture must
    STOP at that end's pose and stay there — a clamp that wrapped would put
    band 2 at the opposite extreme, and a 16-bit `dec` past zero would point
    the index table 448 * 65535 bytes below the set."""
    hi = _shot(tmp_path, "z_hi", drives=((40, UP),))
    assert _mismatched_rows(hi, HEAD_0, ZOOM_CEIL) == []
    hi2 = _shot(tmp_path, "z_hi2", drives=((40, UP), (30, UP)))
    assert P.actual_frame(hi2) == P.actual_frame(hi), "the ceiling drifted"

    lo = _shot(tmp_path, "z_lo", drives=((40, DOWN),))
    assert _mismatched_rows(lo, HEAD_0, ZOOM_FLOOR) == []
    lo2 = _shot(tmp_path, "z_lo2", drives=((40, DOWN), (30, DOWN)))
    assert P.actual_frame(lo2) == P.actual_frame(lo), "the floor wrapped"


def test_the_zoom_floor_collapses_the_matrix_but_not_the_world_position(tmp_path):
    """THE MODULE'S NON-VACUITY CONTROL, reachable inside the SHIPPING binary.

    Zoom 0 is camera A's heading-0 pose EXACTLY (the generator asserts it at
    emit time), so holding Down drives band 2's matrix onto band 1's: the
    two-distinct-trapezoids signal must DIE. The reference needs a `-DNO_SEAM`
    build for that.

    And it is deliberately PARTIAL. The zoom axis does not touch either
    camera's world position, so band 2 stays on the WARM stripe and P4 survives
    the collapse — the two claims fail INDEPENDENTLY rather than as a pair. A
    rail that faked the split with one camera and a hardcoded second colour
    would pass P4 and fail here; a rail with two matrices and one position
    would pass here and fail P4."""
    im = _shot(tmp_path, "collapse", drives=((40, DOWN),))
    assert _mismatched_rows(im, HEAD_0, ZOOM_FLOOR) == []

    # P1 is dead, and the strongest available form of "dead": the two bands'
    # transition profiles are IDENTICAL row for band-local row, all 112 of
    # them. Not a span, not a ratio — the same numbers.
    b1 = [P.transitions(im, r) for r in range(SEAM)]
    b2 = [P.transitions(im, r) for r in range(SEAM, LINES)]
    assert b1 == b2, (
        f"the collapse did not fold the ramps: "
        f"{sum(1 for a, b in zip(b1, b2) if a != b)} of {SEAM} rows still differ")

    # P4 is alive: band 2 is still looking at the warm stripe.
    assert P.mean_red(im, 0, SEAM) < 16
    assert P.mean_red(im, SEAM, LINES) > 96
