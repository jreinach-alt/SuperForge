"""split_h_matrix_demo — TWO Mode 7 cameras over one world, proven in pixels.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)` — an
absolute frame by construction — and every drive is a fixed per-frame input
list, so the whole trajectory is a pure function of the replay triple.

WHAT THIS RAIL IS:

    M1  two distinct on-screen checker periods with the expected ~4x ratio
        (and the -DNO_MATRIX_SPLIT control collapses them to one)
    M2  one clean single-scanline seam
    M3  one shared world in VRAM
    +   the -DAUTODEMO teaching: the band is LIVE — its matrix can be patched
        in the WRAM HDMA table while the picture is running

All four ship, and each is a named case below.

THE HEADLINE PROOF IS A WHOLE-PICTURE PREDICTION, not a period measurement.
`test_the_whole_picture_is_one_world_through_two_matrices` predicts all 224
rows x 256 pixels from ONE blob through Mesen's own Mode 7 transform
(tests/shm_predict.py, read out of SnesPpu.cpp) and compares them to the
screenshot. That single assertion carries M1, M2 and M3 at once and is
strictly stronger than any of them:

  * M3 ("one shared world") is not a claim a period can make — two periods
    would look identical whether the bands sampled one map or two copies. The
    prediction feeds BOTH bands from the SAME 32 KB blob, so a second copy, a
    wrong tilemap row, a wrong CHR byte or a wrong palette index would each
    fail it;
  * M2 ("one clean seam") is exact rather than approximate: the prediction
    switches matrices at the declared scanline, so a seam one line early or
    late mismatches two rows;
  * M1 ("two distinct cameras") is over 57,344 pixels rather than over the
    length of a row's first run.

The period cases stay anyway, because they are the rail's own vocabulary and
because a prediction that agreed with a broken frame for a subtle reason would
still have to produce 8 and 32.

FRAME ACCOUNTING (measured here). A pad held through `advance(N)` reaches the
picture N - 1 times: the main loop's tick computes the new scale, the NEXT
VBlank's hook stamps it into the HDMA table, and the frame after that renders
it — the constant one-commit presentation lag of the park point, shared by
every rail here (`ZOOM_LAG` below). Calibrated by driving held = 1, 5 and 10 and
solving for the number of steps the picture shows: 0, 4, 9.

THE ZOOM STATE IS NEVER READ AS A VARIABLE. `shm_cam` keeps the live band's
scale in DP and a test could read it in one call — and that is exactly the
proxy-variable move rule 2 forbids, because the whole question is whether the
word reaches M7A/M7D through the HDMA table. Every zoom case here reads
PIXELS, and the two table cases read the WRAM the DMA controller fetches.
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
ROM = BUILD / "split_h_matrix_demo.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "shm" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
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


V_M7 = _sym("ES_V_M7")["start"]                  # the pinned Mode 7 region
C_PAL = _sym("ES_C_SHM_PAL")["start"]            # CGRAM words
PAL_WORDS = _sym("ES_C_SHM_PAL")["size"]
TBL = _sym("ES_SHM_TBL")["start"]                # WRAM: both HDMA tables
TBL_SIZE = _sym("ES_SHM_TBL")["size"]
SHDW = _sym("ES_SM_HDMA", scene=None)["start"]   # scene_mgr's channel shadow
SHDW_SIZE = _sym("ES_SM_HDMA", scene=None)["size"]

CH_AB, CH_CD = _chan("shmab"), _chan("shmcd")

TBL_SPAN = TBL_SIZE // 2                         # shm_cam.asm's own split
ENTRY = 5
SHDW_CH = SHDW_SIZE // 8

# --- the rail's geometry, restated here rather than imported ----------------
# The numbers below are the scene's own; the one point worth flagging is that
# band 1's entry carries its
# FULL height (112, not SEAM - 1 = 111), which is `sh2_cam`'s origin-table
# shape — see game/split_h_matrix_demo/scenes/bands.asm's header.
SEAM = 112
B1_LINES, B2_LINES = SEAM, P.PICTURE_LINES - SEAM
SCALE_A, SCALE_B = 0x0100, 0x0040
BANDS = ((B1_LINES, SCALE_A), (B2_LINES, SCALE_B))

# The live band and its clamp range (scenes/bands.asm).
LIVE_SLOT = 1
ZOOM_LO, ZOOM_HI, ZOOM_STEP = 0x0020, SCALE_A, 4

BOOT = 90                       # the module's absolute boot frame
ZOOM_LAG = 1                    # held N frames -> N - 1 steps in the picture

RIGHT, LEFT = {"right": True}, {"left": True}


# --- the blobs ---------------------------------------------------------------
BLOB = (ASSETS / "shm_map.bin").read_bytes()
PAL = (ASSETS / "shm_pal.bin").read_bytes()
CGRAM_RGB = P.load_palette(PAL)


def _boot(frames=BOOT, drives=()):
    """A Machine parked on an ABSOLUTE frame, after a fixed input script."""
    m = Machine(str(ROM)).advance(frames)
    for n, pad in drives:
        m.advance(n, pad1=pad)
    return m


def _shot(m, path):
    m.screenshot(str(path))
    return Image.open(path).convert("RGB")


def _band_rows(slot):
    """The picture rows a band owns, from the declared band list."""
    top = sum(lines for lines, _ in BANDS[:slot])
    return range(top, top + BANDS[slot][0])


def _scale_after(start, steps, sign):
    """The clamped scale the live band reaches after `steps` held frames."""
    v = start + sign * ZOOM_STEP * steps
    return max(ZOOM_LO, min(ZOOM_HI, v))


# =============================================================================
# uploads — the DESTINATION regions, byte for byte
# =============================================================================
def test_the_mode7_plane_reaches_vram_byte_for_byte(tmp_path):
    """shm_floor's one DMA, read back out of the region it targets.

    The interleave is the whole mechanism (mode 1 alternating $2118/$2119),
    and a converter that is right beside an upload that silently no-ops looks
    identical from the source side — the sprite_game `[sprites]` scar. So this
    reads VRAM, not the blob.
    """
    m = _boot()
    try:
        got = m.read_bytes(V, V_M7 * 2, len(BLOB))
    finally:
        m.close()
    assert got == BLOB, (
        f"the Mode 7 region differs from shm_map.bin at byte "
        f"{next(i for i, (a, b) in enumerate(zip(got, BLOB)) if a != b)}")


def test_all_three_claimed_palette_words_reach_cgram():
    """Every word the cgram claim reserves, INCLUDING the invisible one.

    Word 0 is both palette index 0 and the Mode 7 backdrop slot, and on this
    rail it NEVER renders: the plane covers all 224 lines and its CHR only
    ever emits indices 1 and 2. A pixel test therefore cannot see it, and a
    ROM that skipped it would leave power-on RNG in a slot the hardware reads
    — the scroll_run green-GOAL scar, one claim earlier. Reading CGRAM
    directly is the only way to assert it at all.
    """
    m = _boot()
    try:
        got = m.read_bytes(C, C_PAL * 2, PAL_WORDS * 2)
    finally:
        m.close()
    assert got == PAL, f"CGRAM[{C_PAL}..] = {got.hex()} != {PAL.hex()}"


def test_the_generated_world_is_the_declared_checker():
    """The blob against a THIRD derivation, with no shared code.

    tools/gen_split_h_matrix_assets.py already refuses to emit anything the
    vendored oracle disagrees with. This rebuilds the same bytes from the
    checker's stated rule inside the test, so a generator bug and a test bug
    would have to agree independently to pass.
    """
    assert BLOB == P.derive_checker_blob()
    assert len(BLOB) == 0x8000


# =============================================================================
# the HDMA tables — the feature's own output region
# =============================================================================
def test_both_hdma_tables_are_the_declared_bandlist():
    """The bytes the DMA controller fetches, entry by entry.

    NOT a proxy: this WRAM IS what the two channels read, byte for byte, at
    line 0 of every frame. It is still not SUFFICIENT — the picture cases
    below are what prove the bytes reach M7A-M7D — but a table that is right
    and a picture that is right is a much narrower coincidence than either
    alone, and this case names WHICH entry is wrong when one is.
    """
    m = _boot()
    try:
        ab = m.read_bytes(W, TBL, TBL_SPAN)
        cd = m.read_bytes(W, TBL + TBL_SPAN, TBL_SPAN)
    finally:
        m.close()
    for slot, (lines, scale) in enumerate(BANDS):
        want_ab, want_cd = P.band_entry(lines, scale)
        at = slot * ENTRY
        assert ab[at:at + ENTRY] == want_ab, (
            f"AB entry {slot}: {ab[at:at + ENTRY].hex()} != {want_ab.hex()}")
        assert cd[at:at + ENTRY] == want_cd, (
            f"CD entry {slot}: {cd[at:at + ENTRY].hex()} != {want_cd.hex()}")
    term = len(BANDS) * ENTRY
    assert ab[term] == 0 and cd[term] == 0, "the terminator is missing"


def test_every_count_byte_is_non_repeat():
    """THE NON-REPEAT TRAP, asserted on the byte that carries it.

    Bit 7 set would make the controller fetch a NEW 4-byte unit every scanline,
    walk off an 11-byte table within four lines and stream whatever follows it
    into M7A-M7D. The rail's own header calls this its headline trap; the
    `shm-repeat-bit` plant sets the bit and requires this case AND the picture
    cases to go red, so "we cleared it" is not the whole of the evidence.
    """
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


def test_the_table_slack_past_the_terminator_is_zeroed():
    """shm_zero's declared init contract, on the bytes nothing else writes.

    The DMA controller's terminator processing still FETCHES the bytes after
    the $00 on real hardware, so they may not be power-on garbage. Mesen's
    power-on RAM is random by design (rule 5), which is what makes this
    assertion able to fail at all.
    """
    m = _boot()
    try:
        whole = m.read_bytes(W, TBL, TBL_SIZE)
    finally:
        m.close()
    term = len(BANDS) * ENTRY
    for base in (0, TBL_SPAN):
        slack = whole[base + term + 1:base + TBL_SPAN]
        assert set(slack) <= {0}, (
            f"table at +{base}: slack past the terminator holds {slack.hex()}")


def test_shm_arm_stages_both_channels_from_the_emitted_declaration():
    """The scene_mgr channel shadow — shm_arm's own output region.

    DMAP, BBAD, A1B and A1T for both channels, compared against the values the
    ALLOCATOR emitted rather than against transcribed hex. The NMI MVNs this
    block to $4300 every armed frame, so a wrong byte here is a wrong byte in
    the register file; and A1T pointing at the wrong table is the classic
    swap this pair of channels can suffer (the AB and CD tables differ only in
    which two words are zero).
    """
    m = _boot()
    try:
        shadow = m.read_bytes(W, SHDW, SHDW_SIZE)
    finally:
        m.close()
    for chan, a1t in ((CH_AB, TBL), (CH_CD, TBL + TBL_SPAN)):
        at = chan["ch"] * SHDW_CH
        assert shadow[at] == chan["dmap"], (
            f"ch{chan['ch']} DMAP {shadow[at]:#04x} != {chan['dmap']:#04x}")
        assert shadow[at + 1] == chan["bbad"], (
            f"ch{chan['ch']} BBAD {shadow[at + 1]:#04x} != {chan['bbad']:#04x}")
        assert shadow[at + 2] | (shadow[at + 3] << 8) == a1t, (
            f"ch{chan['ch']} A1T points at the wrong table")
        assert shadow[at + 4] == 0x7E, f"ch{chan['ch']} A1B is not the WRAM bank"


# =============================================================================
# the picture
# =============================================================================
def test_the_whole_picture_is_one_world_through_two_matrices(tmp_path):
    """M1 + M2 + M3 at once: 224 rows x 256 px, predicted from ONE blob.

    Every pixel of the frame is derived from the same 32 KB image through
    Mesen's own Mode 7 transform, switching matrices at the declared seam. A
    second copy of the world, a wrong tilemap row, a wrong CHR byte, a wrong
    palette index, a seam one line out or either band's scale being wrong all
    fail it — which is why the three claims collapse into one case here
    and the narrower ones below are kept as vocabulary rather than as cover.
    """
    m = _boot()
    try:
        im = _shot(m, tmp_path / "boot.png")
    finally:
        m.close()
    assert im.size == (P.FRAME_W, P.FRAME_H)
    bad = []
    for slot, (lines, scale) in enumerate(BANDS):
        for row in _band_rows(slot):
            want = P.predict_row(BLOB, CGRAM_RGB, scale, row)
            if P.actual_row(im, row) != want:
                bad.append((row, slot))
    assert not bad, f"{len(bad)} predicted row(s) differ, first {bad[:4]}"


def test_the_two_bands_render_two_distinct_checker_periods(tmp_path):
    """M1 in the rail's own vocabulary: 8 px on top, 32 below, a 4x ratio."""
    m = _boot()
    try:
        im = _shot(m, tmp_path / "boot.png")
    finally:
        m.close()
    want = {0: 8, 1: 32}
    for slot in (0, 1):
        rows = list(_band_rows(slot))
        got = {P.first_run(im, r) for r in rows}
        assert got == {want[slot]}, (
            f"band {slot} rows {rows[0]}..{rows[-1]} show periods {sorted(got)},"
            f" expected {want[slot]}")
    assert want[1] == 4 * want[0]
    # ...and the world only ever has two colours, in equal measure per row.
    for row in (10, 150):
        counts = {}
        for px in P.actual_row(im, row):
            counts[px] = counts.get(px, 0) + 1
        assert sorted(counts.values()) == [128, 128], (
            f"row {row} is not an even two-colour checker: {counts}")


def test_the_seam_is_a_single_scanline_where_the_declaration_puts_it(tmp_path):
    """M2: ONE transition in the whole picture, at the declared row.

    The profile of per-row run lengths must change exactly once, from 8 to 32,
    between rows SEAM-1 and SEAM. A two-row transition would mean the second
    entry's unit landed mid-band; a transition anywhere else would mean the
    first entry's count was wrong.
    """
    m = _boot()
    try:
        im = _shot(m, tmp_path / "boot.png")
    finally:
        m.close()
    prof = P.run_profile(im)
    changes = [r for r in range(1, len(prof)) if prof[r] != prof[r - 1]]
    assert changes == [SEAM], f"transitions at rows {changes}, expected [{SEAM}]"
    assert prof[SEAM - 1] == 8 and prof[SEAM] == 32


# =============================================================================
# the live band — the state cycle, driven in BOTH directions
# =============================================================================
def test_nothing_moves_when_nothing_is_held(tmp_path):
    """The picture is stationary: 60 idle frames, byte-identical.

    The rail's claim is that N cameras cost ~nil CPU, and the visible half of
    that is that the frame does not drift when nobody asks it to. Compared as
    whole PNG bytes rather than as a period, so a one-pixel wobble anywhere
    fails it.
    """
    m = _boot()
    try:
        a = (tmp_path / "a.png")
        m.screenshot(str(a))
        m.advance(60)
        b = (tmp_path / "b.png")
        m.screenshot(str(b))
    finally:
        m.close()
    assert a.read_bytes() == b.read_bytes(), "the picture drifted while idle"


@pytest.mark.parametrize("held", [3, 12, 25])
def test_holding_right_zooms_the_live_band_out_pixel_for_pixel(tmp_path, held):
    """Right steps the live band's matrix, through the WRAM HDMA table.

    Predicted at the exact clamped scale the drive reaches, so the assertion
    holds at intermediate scales whose on-screen period is not an integer —
    which is most of them. THE OTHER BAND IS ASSERTED UNCHANGED in the same
    frame: the live-band offset is what makes one feature serve both rails,
    and a stamp that walked into the wrong entry would move the top band too.
    """
    m = _boot(drives=((held, RIGHT),))
    try:
        im = _shot(m, tmp_path / f"r{held}.png")
    finally:
        m.close()
    scale = _scale_after(SCALE_B, held - ZOOM_LAG, +1)
    assert scale > SCALE_B, "the drive must actually move the band"
    for row in _band_rows(LIVE_SLOT):
        assert P.actual_row(im, row) == P.predict_row(
            BLOB, CGRAM_RGB, scale, row), (
            f"live band row {row} is not scale {scale:#06x} after {held} held")
    for row in _band_rows(0):
        assert P.actual_row(im, row) == P.predict_row(
            BLOB, CGRAM_RGB, SCALE_A, row), (
            f"the static band moved at row {row} — the stamp hit the wrong entry")


def test_the_live_band_zooms_out_and_all_the_way_back_in(tmp_path):
    """The whole cycle: out, back to the start, on down to the floor, idle.

    A test that only drove Right would lock that direction and ship the other
    broken (the rule-1 state-cycle discipline). Each leg is asserted against
    its own predicted scale, and the last leg holds the floor for 20 more
    frames to prove the clamp does not wrap — a 16-bit `sbc` that borrows
    leaves a value that compares ABOVE the floor, which is the bug shm_cam's
    carry test exists for.
    """
    out_n, back_n = 20, 20
    m = _boot()
    try:
        legs = []
        m.advance(out_n, pad1=RIGHT)
        legs.append(("out", _scale_after(SCALE_B, out_n - ZOOM_LAG, +1),
                     _shot(m, tmp_path / "out.png")))
        m.advance(back_n, pad1=LEFT)
        legs.append(("back", _scale_after(
            _scale_after(SCALE_B, out_n, +1), back_n - ZOOM_LAG, -1),
            _shot(m, tmp_path / "back.png")))
        m.advance(60, pad1=LEFT)                 # ...on down to the floor
        legs.append(("floor", ZOOM_LO, _shot(m, tmp_path / "floor.png")))
        m.advance(20, pad1=LEFT)                 # ...and it stays there
        legs.append(("held", ZOOM_LO, _shot(m, tmp_path / "held.png")))
    finally:
        m.close()
    assert legs[0][1] != legs[1][1] != legs[2][1], "the legs must differ"
    for tag, scale, im in legs:
        for row in _band_rows(LIVE_SLOT):
            assert P.actual_row(im, row) == P.predict_row(
                BLOB, CGRAM_RGB, scale, row), (
                f"leg {tag}: row {row} is not scale {scale:#06x}")
        for row in _band_rows(0):
            assert P.actual_row(im, row) == P.predict_row(
                BLOB, CGRAM_RGB, SCALE_A, row), (
                f"leg {tag}: the static band moved at row {row}")


def test_driving_the_live_band_to_the_ceiling_collapses_the_split(tmp_path):
    """The reference's -DNO_MATRIX_SPLIT control, reached by INPUT.

    Held to the ceiling both bands run camera A's scale, so the two-period
    signal DIES and the whole picture becomes one 8-px checker with no seam.
    That is the non-vacuity control for every case above: without it, "two
    distinct periods" is a claim about a ROM that could equally have hardcoded
    a coarse bottom half. Reaching it by input rather than by a `-D` build
    means the SAME binary carries the control and its refutation.
    """
    m = _boot()
    try:
        m.advance(80, pad1=RIGHT)               # 79 steps x 4 > 0x0100 - 0x0040
        im = _shot(m, tmp_path / "ceiling.png")
    finally:
        m.close()
    prof = P.run_profile(im)
    assert set(prof) == {8}, (
        f"the split did not collapse: the picture still shows periods "
        f"{sorted(set(prof))}")
    changes = [r for r in range(1, len(prof)) if prof[r] != prof[r - 1]]
    assert changes == [], f"a seam survives the collapse at rows {changes}"
    for row in range(P.PICTURE_LINES):
        assert P.actual_row(im, row) == P.predict_row(
            BLOB, CGRAM_RGB, SCALE_A, row), f"row {row} is not camera A"
