"""split_h_persp3_demo — THREE Mode 7 cameras over one world, proven in pixels.

LOCKSTEP-NATIVE, and deliberately the sibling module of
`tests/test_split_h_matrix_demo.py`: same cases, same shared predictor
(`tests/shm_predict.py`), its OWN map, its own band list. The spec rules
this rail "a band-count parameter" of row 11 and says the two ship together or
not at all; keeping the two modules parallel is what makes that claim
checkable by reading them side by side rather than by trusting it.

WHAT THIS RAIL IS:

    C1  THREE distinct on-screen checker periods — 8 / 32 / 16 px
        (and the -DONE_CAM control collapses them)
    C2  two clean single-scanline seams
    C3  temporal stability — the scene is HDMA-static, with no double buffer
        to desync
    M3  one shared world in VRAM

THE MIDDLE BAND IS THE SMALLEST SCALE, NOT A MONOTONIC RAMP (the reference's own
choice: SCALE_A $0100, SCALE_B $0040, SCALE_C $0080). A monotonic 8/16/32
ladder could be mistaken for a single perspective camera; 8/32/16 cannot. The
period cases assert the ORDER, not just the set, for exactly that reason.

WHAT IT SHARES WITH ITS SIBLING, MEASURED RATHER THAN ASSERTED IN PROSE: the
same two HDMA channels, the same 32 KB blob, the same three palette words, the
same origin, the same `shm_cam`/`shm_floor`/`shm_rom` features, the same
feature-for-feature game.toml. The THIRD band costs one more table entry, one
more HBlank write per channel per frame, and one line of scene code. The
channel-count case below asserts the first half of that from the emitted map.

FRAME ACCOUNTING and the no-proxy rule: identical to the sibling module's —
see its header. The live band here is slot 2 rather than slot 1, which is the
entire mechanism by which one feature serves both band counts.
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
import shm_predict as P                                        # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "split_h_persp3_demo.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "shp3" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
W = MemoryType.SnesWorkRam


def _sym(name, scene="bands"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


def _chan(name):
    for c in MAP["scenes"]["bands"]["channels"]:
        if c["name"] == name:
            return c
    raise KeyError(f"{name} is not an emitted channel")


V_M7 = _sym("ES_V_M7")["start"]
C_PAL = _sym("ES_C_SHM_PAL")["start"]
PAL_WORDS = _sym("ES_C_SHM_PAL")["size"]
TBL = _sym("ES_SHM_TBL")["start"]
TBL_SIZE = _sym("ES_SHM_TBL")["size"]
SHDW = _sym("ES_SM_HDMA", scene=None)["start"]
SHDW_SIZE = _sym("ES_SM_HDMA", scene=None)["size"]

CH_AB, CH_CD = _chan("shmab"), _chan("shmcd")

TBL_SPAN = TBL_SIZE // 2
ENTRY = 5
SHDW_CH = SHDW_SIZE // 8

# --- the rail's geometry, restated here rather than imported ------------------
# templates/split_h_persp3_demo/main.asm:85-94.
SEAM1, SEAM2 = 75, 150
B1, B2, B3 = SEAM1, SEAM2 - SEAM1, P.PICTURE_LINES - SEAM2
SCALE_A, SCALE_B, SCALE_C = 0x0100, 0x0040, 0x0080
BANDS = ((B1, SCALE_A), (B2, SCALE_B), (B3, SCALE_C))
PERIODS = (8, 32, 16)

LIVE_SLOT = 2
ZOOM_LO, ZOOM_HI, ZOOM_STEP = 0x0020, SCALE_A, 4

BOOT = 90
ZOOM_LAG = 1

RIGHT, LEFT = {"right": True}, {"left": True}

BLOB = (ASSETS / "shm_map.bin").read_bytes()
PAL = (ASSETS / "shm_pal.bin").read_bytes()
CGRAM_RGB = P.load_palette(PAL)


def _boot(frames=BOOT, drives=()):
    m = Machine(str(ROM)).advance(frames)
    for n, pad in drives:
        m.advance(n, pad1=pad)
    return m


def _shot(m, path):
    m.screenshot(str(path))
    return Image.open(path).convert("RGB")


def _band_rows(slot):
    top = sum(lines for lines, _ in BANDS[:slot])
    return range(top, top + BANDS[slot][0])


def _scale_after(start, steps, sign):
    return max(ZOOM_LO, min(ZOOM_HI, start + sign * ZOOM_STEP * steps))


# =============================================================================
# uploads — the DESTINATION regions, byte for byte
# =============================================================================
def test_the_mode7_plane_reaches_vram_byte_for_byte():
    """The SAME blob the sibling uploads, read out of THIS ROM's VRAM.

    Both rails share one `shm_rom` feature and one generator, so this is not a
    duplicate of the sibling's case: it is the assertion that the second ROM
    also carries and uploads the bytes (`make rom-unbacked` proves a claim is
    backed per COMPOSITION, and this proves the DMA runs per ROM).
    """
    m = _boot()
    try:
        got = m.read_bytes(V, V_M7 * 2, len(BLOB))
    finally:
        m.close()
    assert got == BLOB


def test_all_three_claimed_palette_words_reach_cgram():
    """Including word 0, the backdrop slot the plane never lets render."""
    m = _boot()
    try:
        got = m.read_bytes(C, C_PAL * 2, PAL_WORDS * 2)
    finally:
        m.close()
    assert got == PAL, f"CGRAM[{C_PAL}..] = {got.hex()} != {PAL.hex()}"


# =============================================================================
# the HDMA tables — the feature's own output region
# =============================================================================
def test_both_hdma_tables_are_the_declared_three_band_list():
    """Three entries per table, the third being this rail's whole difference."""
    m = _boot()
    try:
        ab = m.read_bytes(W, TBL, TBL_SPAN)
        cd = m.read_bytes(W, TBL + TBL_SPAN, TBL_SPAN)
    finally:
        m.close()
    assert len(BANDS) == 3
    for slot, (lines, scale) in enumerate(BANDS):
        want_ab, want_cd = P.band_entry(lines, scale)
        at = slot * ENTRY
        assert ab[at:at + ENTRY] == want_ab, f"AB entry {slot}"
        assert cd[at:at + ENTRY] == want_cd, f"CD entry {slot}"
    term = len(BANDS) * ENTRY
    assert ab[term] == 0 and cd[term] == 0, "the terminator is missing"


def test_every_count_byte_is_non_repeat():
    """The NON-REPEAT trap on all three entries, and their declared heights."""
    m = _boot()
    try:
        ab = m.read_bytes(W, TBL, TBL_SPAN)
        cd = m.read_bytes(W, TBL + TBL_SPAN, TBL_SPAN)
    finally:
        m.close()
    for slot, (lines, _) in enumerate(BANDS):
        at = slot * ENTRY
        for tag, tbl in (("AB", ab), ("CD", cd)):
            assert tbl[at] & 0x80 == 0, f"{tag} entry {slot} has the REPEAT bit set"
            assert tbl[at] == lines, f"{tag} entry {slot} count {tbl[at]} != {lines}"
    assert sum(lines for lines, _ in BANDS) == P.PICTURE_LINES


def test_the_table_slack_past_the_terminator_is_zeroed():
    """shm_zero's init contract, with one entry less slack than the sibling."""
    m = _boot()
    try:
        whole = m.read_bytes(W, TBL, TBL_SIZE)
    finally:
        m.close()
    term = len(BANDS) * ENTRY
    for base in (0, TBL_SPAN):
        slack = whole[base + term + 1:base + TBL_SPAN]
        assert set(slack) <= {0}, f"table at +{base}: slack holds {slack.hex()}"


def test_the_third_band_costs_no_extra_channel():
    """The pair's scheduling claim, read off the emitted map and the shadow.

    `sh2_cam` needs a channel PAIR per band because DASB is per channel; a
    DIRECT table needs no DASB, so N bands ride two channels. This asserts
    BOTH halves: the allocator emitted exactly two, and both are staged.
    """
    assert len(MAP["scenes"]["bands"]["channels"]) == 2, (
        "a three-band rail took more than the two channels the pair claims")
    m = _boot()
    try:
        shadow = m.read_bytes(W, SHDW, SHDW_SIZE)
    finally:
        m.close()
    for chan, a1t in ((CH_AB, TBL), (CH_CD, TBL + TBL_SPAN)):
        at = chan["ch"] * SHDW_CH
        assert shadow[at] == chan["dmap"]
        assert shadow[at + 1] == chan["bbad"]
        assert shadow[at + 2] | (shadow[at + 3] << 8) == a1t
        assert shadow[at + 4] == 0x7E


# =============================================================================
# the picture
# =============================================================================
def test_the_whole_picture_is_one_world_through_three_matrices(tmp_path):
    """C1 + C2 + M3 at once: 224 rows x 256 px, predicted from ONE blob."""
    m = _boot()
    try:
        im = _shot(m, tmp_path / "boot.png")
    finally:
        m.close()
    assert im.size == (P.FRAME_W, P.FRAME_H)
    bad = []
    for slot, (_, scale) in enumerate(BANDS):
        for row in _band_rows(slot):
            if P.actual_row(im, row) != P.predict_row(BLOB, CGRAM_RGB, scale, row):
                bad.append((row, slot))
    assert not bad, f"{len(bad)} predicted row(s) differ, first {bad[:4]}"


def test_three_bands_render_three_distinct_periods_in_the_declared_order(tmp_path):
    """C1: 8 / 32 / 16, IN THAT ORDER — not merely three distinct values.

    The order is the argument that this is three cameras rather than
    one perspective ramp: a monotonic ladder would be indistinguishable from a
    single trapezoid, and this one is not monotonic.
    """
    m = _boot()
    try:
        im = _shot(m, tmp_path / "boot.png")
    finally:
        m.close()
    for slot, want in enumerate(PERIODS):
        rows = list(_band_rows(slot))
        got = {P.first_run(im, r) for r in rows}
        assert got == {want}, (
            f"band {slot} rows {rows[0]}..{rows[-1]} show {sorted(got)}, "
            f"expected {want}")
    assert len(set(PERIODS)) == 3
    assert not (PERIODS[0] < PERIODS[1] < PERIODS[2]), "the ladder must not be monotonic"


def test_both_seams_are_single_scanlines_where_the_declaration_puts_them(tmp_path):
    """C2: exactly TWO transitions, at the two declared rows, one row each."""
    m = _boot()
    try:
        im = _shot(m, tmp_path / "boot.png")
    finally:
        m.close()
    prof = P.run_profile(im)
    changes = [r for r in range(1, len(prof)) if prof[r] != prof[r - 1]]
    assert changes == [SEAM1, SEAM2], (
        f"transitions at rows {changes}, expected [{SEAM1}, {SEAM2}]")
    assert (prof[SEAM1 - 1], prof[SEAM1]) == (8, 32)
    assert (prof[SEAM2 - 1], prof[SEAM2]) == (32, 16)


def test_the_scene_is_temporally_stable(tmp_path):
    """C3: HDMA-static, no double buffer to desync — 90 idle frames identical.

    The reference names this as its own test because a three-band split built on
    a flipped buffer would tear at ~30 Hz. Ninety frames rather than the
    sibling's sixty, because that is what a 30 Hz beat would need to be caught
    at every phase.
    """
    m = _boot()
    try:
        a, b = tmp_path / "a.png", tmp_path / "b.png"
        m.screenshot(str(a))
        m.advance(90)
        m.screenshot(str(b))
    finally:
        m.close()
    assert a.read_bytes() == b.read_bytes(), "the picture drifted while idle"


# =============================================================================
# the live band — the state cycle, driven in BOTH directions
# =============================================================================
@pytest.mark.parametrize("held", [3, 12, 25])
def test_holding_right_zooms_the_bottom_band_out_pixel_for_pixel(tmp_path, held):
    """Slot 2 moves; slots 0 AND 1 must not.

    Two static bands rather than the sibling's one, which is what makes this
    the real test of `shm_cam`'s SHM_OFF indirection: a stamp that ignored the
    offset would land on slot 0, and one that used the sibling's offset would
    land on slot 1 — two distinct wrong answers, each caught here by name.
    """
    m = _boot(drives=((held, RIGHT),))
    try:
        im = _shot(m, tmp_path / f"r{held}.png")
    finally:
        m.close()
    scale = _scale_after(SCALE_C, held - ZOOM_LAG, +1)
    assert scale > SCALE_C
    for row in _band_rows(LIVE_SLOT):
        assert P.actual_row(im, row) == P.predict_row(
            BLOB, CGRAM_RGB, scale, row), f"live band row {row}"
    for slot in (0, 1):
        for row in _band_rows(slot):
            assert P.actual_row(im, row) == P.predict_row(
                BLOB, CGRAM_RGB, BANDS[slot][1], row), (
                f"static band {slot} moved at row {row}")


def test_the_bottom_band_zooms_out_and_all_the_way_back_in(tmp_path):
    """Out, back, on down to the floor, and held there — both directions."""
    out_n, back_n = 20, 20
    m = _boot()
    try:
        legs = []
        m.advance(out_n, pad1=RIGHT)
        legs.append(("out", _scale_after(SCALE_C, out_n - ZOOM_LAG, +1),
                     _shot(m, tmp_path / "out.png")))
        m.advance(back_n, pad1=LEFT)
        legs.append(("back", _scale_after(
            _scale_after(SCALE_C, out_n, +1), back_n - ZOOM_LAG, -1),
            _shot(m, tmp_path / "back.png")))
        m.advance(60, pad1=LEFT)
        legs.append(("floor", ZOOM_LO, _shot(m, tmp_path / "floor.png")))
        m.advance(20, pad1=LEFT)
        legs.append(("held", ZOOM_LO, _shot(m, tmp_path / "held.png")))
    finally:
        m.close()
    assert legs[0][1] != legs[1][1] != legs[2][1]
    for tag, scale, im in legs:
        for row in _band_rows(LIVE_SLOT):
            assert P.actual_row(im, row) == P.predict_row(
                BLOB, CGRAM_RGB, scale, row), f"leg {tag}: row {row}"
        for slot in (0, 1):
            for row in _band_rows(slot):
                assert P.actual_row(im, row) == P.predict_row(
                    BLOB, CGRAM_RGB, BANDS[slot][1], row), (
                    f"leg {tag}: static band {slot} moved at row {row}")


def test_driving_the_bottom_band_to_the_ceiling_kills_the_third_camera(tmp_path):
    """The reference's -DONE_CAM control, reached by INPUT — and PARTIAL by design.

    Held to the ceiling band 3 takes camera A's scale, so the THREE-period
    signal dies while the two-period one survives (band 2 is still 0.25). That
    partiality is the point: it kills C1 without also killing C2, so the two
    claims fail independently rather than as a pair — the same separation
    `sh2_cam`'s -D SH2_SAME_HEADING control was built for.
    """
    m = _boot()
    try:
        m.advance(80, pad1=RIGHT)
        im = _shot(m, tmp_path / "ceiling.png")
    finally:
        m.close()
    prof = P.run_profile(im)
    assert set(prof) == {8, 32}, (
        f"the third camera survived: periods {sorted(set(prof))}")
    changes = [r for r in range(1, len(prof)) if prof[r] != prof[r - 1]]
    assert changes == [SEAM1, SEAM2], f"seams moved: {changes}"
    assert prof[SEAM2] == 8, "band 3 did not collapse onto camera A"
    for slot, scale in ((0, SCALE_A), (1, SCALE_B), (2, SCALE_A)):
        for row in _band_rows(slot):
            assert P.actual_row(im, row) == P.predict_row(
                BLOB, CGRAM_RGB, scale, row), f"band {slot} row {row}"
