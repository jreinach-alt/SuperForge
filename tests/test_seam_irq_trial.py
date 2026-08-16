"""seam_irq_trial — the scanline-IRQ debut, asserted as pictures and timing.

THE CLAIM UNDER TEST: band 2's Mode 7 origin can arrive by a seam-scanline
V-IRQ firing two pre-armed GP-DMA channels in the HBlank gap — and render
EXACTLY what the classic origin HDMA pair renders. Three ROMs carry it:

    build/seam_irq_trial.sfc  the subject (IRQ + pre-armed pair)
    build/sit_origin.sfc      -DSIT_HDMA_ORIGIN: the GOLD control (classic
                              origin channels through the same claims)
    build/sit_mistime.sfc     -DSIT_MISTIME: VTIME=60 — the NON-VACUITY
                              control; the same metric must FLIP

LOCKSTEP-NATIVE for every picture and counter:
`Machine(ROM).advance(N)` lands on the absolute frame N by construction, and
the scene is FROZEN precisely so cross-ROM equality is well-defined. The two
live-silicon cases at the bottom use MesenRunner's console-state API instead
— the `$420C` mask and the `$43xx` channel files are unreachable through the
debugger peek path (test_decl_impl_channels' v1 lesson), and the whole point
of the freed-channel assertion is to read the mask the silicon acts on, not
a WRAM shadow of it.

THE GEOMETRY (tests/frame_geometry.py, measured there): content line L —
drawn during internal scanline L+1 — is PNG row L + PICTURE_TOP. Band 1 is
content lines 0..111, band 2 is 112..223; the trial's whole delta is the four
origin bytes that change between content lines 111 and 112.

THE COLOUR ORACLE (the rail's own, sit_rom's palette contract): the cool pair
carries red 0 and the warm pair red 31, so "red-dominant pixels per row" is a
per-band position signal. Band 1's FAR FIELD legitimately shows warm rows
(the perspective compresses distant stripes — measured 85/256 red-dominant at
content 0), so every per-row claim here is restricted to rows the seam
mechanism determines: the near-field band and the two rows astride the seam
(the population rule — count the population the feature controls, not the screen).

H1/H2 ARE MEASURED, NOT ASSUMED: the reference's numbers are
hypotheses until re-measured on THIS engine loop, and the counters the rail
exports are the instruments — sit_cnt's wake counter sits inside scene_mgr's
own gated-wai handshake, and the latch mirrors are OPHCT/OPVCT read at
handler entry and one instruction after the MDMAEN fire returns.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402
from frame_geometry import PICTURE_TOP, FRAME_W  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "seam_irq_trial.sfc"
ROM_ORIGIN = BUILD / "sit_origin.sfc"
ROM_MISTIME = BUILD / "sit_mistime.sfc"
MAP = json.loads((BUILD / "sit" / "symbol_map.json").read_text())

WR = MemoryType.SnesWorkRam

SEAM = 112                       # the rail's band seam (content lines)
MISTIME_LINE = 60                # the -DSIT_MISTIME fire line
SETTLED = 120                    # absolute frame: fade done, cycle steady
WINDOW = 120                     # the second sample, one window later


def _sym(name, scene="seam"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


CNT = _sym("ES_SIT_CNT")["start"]
FRAME_CTR = _sym("ES_SM_FRAME", scene=None)["start"]

# The four channels' emitted encodings — what the live register file must hold.
CH = {c["name"]: c for c in MAP["scenes"]["seam"]["channels"]}


def _counters(m):
    """(frame, irq_fires, raw_wakes) — the trial's cadence instruments."""
    c = m.read_bytes(WR, CNT, 4)
    frame = int.from_bytes(m.read_bytes(WR, FRAME_CTR, 2), "little")
    return (frame,
            int.from_bytes(c[0:2], "little"),
            int.from_bytes(c[2:4], "little"))


def _latches(m):
    """Entry and post-fire OPHCT/OPVCT mirrors: ((eh, ev), (fh, fv))."""
    c = m.read_bytes(WR, CNT + 4, 8)
    return ((c[0] | (c[1] << 8), c[2] | (c[3] << 8)),
            (c[4] | (c[5] << 8), c[6] | (c[7] << 8)))


def _frame_png(rom, frame, tmp_path, name):
    with Machine(str(rom)) as m:
        m.advance(frame)
        p = tmp_path / name
        m.screenshot(str(p))
        return Image.open(p).convert("RGB")


def _row_red_green(im, content_line):
    """(red-dominant, green-dominant) pixel counts of one content line."""
    px = im.load()
    r = PICTURE_TOP + content_line
    reds = greens = 0
    for x in range(FRAME_W):
        p = px[x, r]
        if p[0] > 100 and p[0] > p[1]:
            reds += 1
        elif p[1] > 100 and p[1] > p[0]:
            greens += 1
    return reds, greens


@pytest.fixture(scope="module")
def built():
    for rom in (ROM, ROM_ORIGIN, ROM_MISTIME):
        if not rom.exists():
            pytest.fail(f"{rom} missing — run `make seam_irq_trial "
                        f"sit-origin sit-mistime` first")


# =========================================================================
# THE GOLD ASSERTION — the trial's headline
# =========================================================================

def test_gold_the_irq_build_renders_byte_identical_to_the_hdma_origin_control(
        built, tmp_path):
    """Default vs -DSIT_HDMA_ORIGIN framebuffers, byte-equal on TWO absolute
    frames one window apart. Two frames, because the seam fire and the VBlank
    re-stamp run every frame — a single capture could not distinguish "the
    mechanism holds" from "frame 120 happened to match". Each ROM boots its
    own random power-on RAM, so equality also proves both builds initialise
    everything they display (rule 5 — nothing rendered is inherited)."""
    for frame in (SETTLED, SETTLED + WINDOW):
        a = _frame_png(ROM, frame, tmp_path, f"irq_{frame}.png")
        b = _frame_png(ROM_ORIGIN, frame, tmp_path, f"gold_{frame}.png")
        assert a.tobytes() == b.tobytes(), (
            f"frame {frame}: the seam-IRQ picture diverged from the "
            f"HDMA-origin control — the mechanism under trial is not "
            f"delivering the classic pair's bytes")


def test_the_picture_is_stable_across_the_fire_cycle(built, tmp_path):
    """The frozen scene through N fire->re-stamp->re-arm cycles is the SAME
    picture: frame 120 vs 180 byte-equal on the subject ROM. This is the
    state-cycle drive for a static rail — any per-frame leak (a consumed DAS
    that never re-armed, a drifting staged byte, a band-1 register the VBlank
    stamp missed) accumulates into a visible divergence here."""
    a = _frame_png(ROM, SETTLED, tmp_path, "cyc_a.png")
    b = _frame_png(ROM, SETTLED + 60, tmp_path, "cyc_b.png")
    assert a.tobytes() == b.tobytes(), (
        "the picture drifted across 60 fire cycles — some per-frame state "
        "is not re-established (DAS? A1T? the band-1 re-stamp?)")


# =========================================================================
# THE NON-VACUITY CONTROL — the same metric must flip
# =========================================================================

def test_mistime_flips_the_gold_metric_in_exactly_the_mistimed_band(
        built, tmp_path):
    """-DSIT_MISTIME (VTIME=60) against the default, SAME comparison as the
    gold case: rows outside content [60, 112) byte-identical, EVERY row
    inside different. The fire mechanism is identical — only the line moved —
    so the flip localised to exactly content 60..111 is what proves the gold
    equality is sharp enough to see a mistimed seam (and not a comparison
    too dull to fail)."""
    a = _frame_png(ROM, SETTLED, tmp_path, "def.png").tobytes()
    c = _frame_png(ROM_MISTIME, SETTLED, tmp_path, "mis.png").tobytes()
    assert a != c, "the mistimed build rendered identically — vacuous gold"
    stride = FRAME_W * 3
    diff_rows = []
    h = len(a) // stride
    for row in range(h):
        if a[row * stride:(row + 1) * stride] != c[row * stride:(row + 1) * stride]:
            diff_rows.append(row - PICTURE_TOP)     # content-line numbering
    assert diff_rows, "no differing rows found"
    assert min(diff_rows) == MISTIME_LINE, (
        f"the mistimed origin first lands at content {min(diff_rows)}, "
        f"expected {MISTIME_LINE} — the VTIME->content-line model is wrong")
    assert max(diff_rows) == SEAM - 1, (
        f"the mistimed region ends at content {max(diff_rows)}, expected "
        f"{SEAM - 1} — band 2 proper should render identically in both")
    assert len(diff_rows) == SEAM - MISTIME_LINE, (
        f"{len(diff_rows)} rows differ; expected every row in "
        f"[{MISTIME_LINE}, {SEAM}) and no other")


# =========================================================================
# THE SEAM ROW, EXACT
# =========================================================================

def test_the_seam_row_is_exact_line_111_cool_line_112_warm(built, tmp_path):
    """The four origin bytes land between content lines 111 and 112 — one
    line early is the reference's measured corruption, and the falsify plant
    that arms VTIME=SEAM-1 must turn THIS case red. Line 111 (band 1's last,
    near field: measured 0 red-dominant / 256 green) carries no red; line 112
    (band 2's first) is red-dominant."""
    im = _frame_png(ROM, SETTLED, tmp_path, "seam.png")
    reds_111, greens_111 = _row_red_green(im, SEAM - 1)
    reds_112, _ = _row_red_green(im, SEAM)
    assert reds_111 == 0, (
        f"content line 111 shows {reds_111} red-dominant pixels — band 2's "
        f"origin arrived one line early (the VTIME=SEAM-1 defect)")
    assert greens_111 > 200, (
        f"content line 111 is not the cool near-field ({greens_111} green)")
    assert reds_112 > 128, (
        f"content line 112 shows only {reds_112} red-dominant pixels — "
        f"band 2's origin did not land at the seam")


def test_band_geometry_near_fields_carry_their_own_stripes(built, tmp_path):
    """Band 1's near field (content 100..111) is pure cool; band 2's near
    field (content 200..223) is pure warm. Restricted to the near fields
    deliberately — the far field of a perspective view compresses distant
    stripes of BOTH colours (measured: content 0 has 85 red-dominant pixels
    on a correct render), so a whole-band count would assert the wrong
    population (the population rule)."""
    im = _frame_png(ROM, SETTLED, tmp_path, "bands.png")
    for line in range(100, SEAM):
        reds, _ = _row_red_green(im, line)
        assert reds == 0, f"band-1 near-field content {line}: {reds} red"
    for line in range(200, 224):
        reds, _ = _row_red_green(im, line)
        assert reds > 250, f"band-2 near-field content {line}: {reds} red"


# =========================================================================
# H1 — the wai double-wake, measured on THIS loop
# =========================================================================

def test_h1_the_armed_wai_wakes_exactly_twice_per_frame(built):
    """Two samples one window apart, deltas EXACT in steady state: the frame
    counter, the fire counter and the wake counter advance +N, +N, +2N. The
    fire counter marching in lockstep with scene_mgr's frame counter is the
    once-per-frame cadence; the wake counter at exactly 2/frame is H1 — wai
    returns at the seam IRQ as well as at NMI (SnesCpu.Shared.h:336-341),
    and the handshake gate sends the seam wake back to sleep."""
    with Machine(str(ROM)) as m:
        m.advance(SETTLED)
        f0, irq0, wake0 = _counters(m)
        m.advance(WINDOW)
        f1, irq1, wake1 = _counters(m)
    assert f1 - f0 == WINDOW, "the frame counter is not one per frame"
    assert irq1 - irq0 == WINDOW, (
        f"seam-IRQ fires {irq1 - irq0} over {WINDOW} frames — the fire "
        f"cadence is not once per frame")
    assert wake1 - wake0 == 2 * WINDOW, (
        f"raw wai wakes {wake1 - wake0} over {WINDOW} frames — expected "
        f"exactly 2 per frame (the seam wake + the NMI wake)")


def test_h1_control_the_unarmed_build_wakes_once_per_frame(built):
    """The other arm: -DSIT_HDMA_ORIGIN never arms the IRQ, so its wai wakes
    once per frame and its fire counter stays zero. Without this control the
    2x measurement above could be a property of the counter, not of the
    armed line."""
    with Machine(str(ROM_ORIGIN)) as m:
        m.advance(SETTLED)
        f0, irq0, wake0 = _counters(m)
        m.advance(WINDOW)
        f1, irq1, wake1 = _counters(m)
    assert irq0 == 0 and irq1 == 0, "the control build fired the seam IRQ"
    assert f1 - f0 == WINDOW
    assert wake1 - wake0 == WINDOW, (
        f"unarmed wakes {wake1 - wake0} over {WINDOW} frames — expected "
        f"exactly 1 per frame (NMI only)")


# =========================================================================
# H2 — the fire window, measured on THIS loop
# =========================================================================

def test_h2_the_fire_lands_in_the_seam_hblank_window(built):
    """The handler's own OPHCT/OPVCT mirrors, read from the PPU latch: entry
    on internal scanline 112 BEFORE the HBlank flag (dot < 274 — the spin
    gate is what carries it across), fire completion early in internal
    scanline 113 before content line 112's first flush trigger at dot 22
    (SnesPpu.cpp:883-884). Measured on this loop: entry dot 47, completion
    dot 10 — recorded in the spec; the assertions are the WINDOW bounds, not
    the exact dots, so a legitimate cycle-level shift cannot flap this."""
    with Machine(str(ROM)) as m:
        m.advance(SETTLED)
        (eh, ev), (fh, fv) = _latches(m)
    assert ev == SEAM, (
        f"handler entry at internal scanline {ev}, expected {SEAM} — VTIME "
        f"is not arming the seam line")
    assert eh < 274, (
        f"handler entry at dot {eh} — past the HBlank flag; the entry "
        f"readout would have eaten the spin gate's margin")
    assert fv == SEAM + 1, (
        f"fire completed on internal scanline {fv}, expected {SEAM + 1} "
        f"(the trailing-HBlank fire spills its completion into the next "
        f"line's left edge)")
    assert fh < 22, (
        f"fire completed at dot {fh} of scanline {fv} — past content line "
        f"112's first flush trigger (dot 22): the seam write missed its "
        f"window")


def test_h2_mistime_the_same_window_at_the_mistimed_line(built):
    """The mistimed build's mirrors show the SAME mechanism at line 60:
    entry scanline 60, completion early in 61. The window is a property of
    the fire, not of the seam — which is exactly why VTIME alone decides
    where the corruption lands."""
    with Machine(str(ROM_MISTIME)) as m:
        m.advance(SETTLED)
        (eh, ev), (fh, fv) = _latches(m)
    assert ev == MISTIME_LINE and fv == MISTIME_LINE + 1, (
        f"mistimed fire at {ev}/{fv}, expected "
        f"{MISTIME_LINE}/{MISTIME_LINE + 1}")
    assert fh < 22


# =========================================================================
# THE STRUCTURAL FREED-CHANNEL ASSERTS — the live silicon, not a shadow
# =========================================================================

def _live_state(rom):
    """Boot under MesenRunner and return (dma_state, internal_regs) at a
    settled parked frame. MesenRunner because the $420C mask and the $43xx
    register file are unreachable through the debugger peek path — the
    console-state API is the one honest surface (test_decl_impl_channels)."""
    from mesen_runner import MesenRunner  # noqa: E402  (lockstep default
    # everywhere else in this module; the live-silicon cases need the
    # console-state API, which Machine deliberately does not carry)
    runner = MesenRunner()
    try:
        runner.boot_to_frame(str(rom), SETTLED)
        snap = runner.snes_state_snapshot()
        return snap.dma, snap.internal_regs
    finally:
        runner.stop()


def test_the_seam_channels_are_armed_but_not_hdma_enabled(built):
    """THE FREED-CHANNEL SIGNAL, on the silicon: the live $420C mask holds
    exactly the two matrix bits — the seam pair is configured (DMAP/BBAD
    match its claims' emitted encodings, byte for byte) yet NOT HDMA-enabled,
    because it fires by MDMAEN from the IRQ handler. This is the SuperForge form
    of the reference's G_MSK2==0 assert, and the falsify plant that ORs the
    seam bits into the scene's mask must turn exactly this case red (the
    picture cannot see that defect: an enabled seam channel's stage block
    reads as a count-0 table and terminates at line 0 doing nothing)."""
    dma, _regs = _live_state(ROM)
    want = (1 << CH["sitab"]["ch"]) | (1 << CH["sitcd"]["ch"])
    assert dma.hdmaen == want, (
        f"live HDMAEN ${dma.hdmaen:02X}, expected ${want:02X} (matrix pair "
        f"only) — a seam channel leaked into the HDMA mask, or a matrix "
        f"channel fell out")
    for claim in ("sitab", "sitcd", "sitxy", "sithv"):
        ch = CH[claim]
        live = dma.channels[ch["ch"]]
        assert live.dmap == ch["dmap"], (
            f"{claim}: live DMAP ${live.dmap:02X} != declared ${ch['dmap']:02X}")
        assert live.bbad == ch["bbad"], (
            f"{claim}: live BBAD ${live.bbad:02X} != declared ${ch['bbad']:02X}")


def test_the_control_enables_all_four_and_arms_no_irq(built):
    """The same silicon read on -DSIT_HDMA_ORIGIN: all four channel bits in
    $420C (the classic composition), and the reconstructed NMITIMEN carries
    NO V-IRQ enable — the two builds differ at the silicon exactly where the
    mechanism says they should, and nowhere else."""
    dma, regs = _live_state(ROM_ORIGIN)
    want = ((1 << CH["sitab"]["ch"]) | (1 << CH["sitcd"]["ch"])
            | (1 << CH["sitxy"]["ch"]) | (1 << CH["sithv"]["ch"]))
    assert dma.hdmaen == want, (
        f"control HDMAEN ${dma.hdmaen:02X}, expected ${want:02X} — the "
        f"classic build should enable the origin pair as real HDMA")
    assert not regs.nmitimen & 0x30, (
        f"control NMITIMEN ${regs.nmitimen:02X} has an IRQ enable bit set — "
        f"the control must not arm the timer")
    dma_irq, regs_irq = _live_state(ROM)
    assert regs_irq.nmitimen & 0x20, (
        f"subject NMITIMEN ${regs_irq.nmitimen:02X} lacks the V-IRQ enable "
        f"— the trial build is not armed")
