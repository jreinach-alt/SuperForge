"""split_h_irq_grad_demo — a freed channel, SPENT, asserted as pictures.

THE CLAIM UNDER TEST: moving band 2's Mode 7 origin to a seam-scanline V-IRQ
frees the origin HDMA pair, and one of the freed channels can then carry a real
per-scanline raster payload — WITHOUT disturbing anything the origin mechanism
was doing, and with both cameras genuinely in motion. Three ROMs carry it:

    build/split_h_irq_grad_demo.sfc  the subject (IRQ origin + the gradient)
    build/shg_nograd.sfc             -DSHG_NO_GRAD: the gradient FLIP control,
                                     and the subject side of the gold pair
    build/shg_origin.sfc             -DSHG_HDMA_ORIGIN: the GOLD control — the
                                     classic origin channel pair. It implies
                                     NO_GRAD (no freed channel to spend), which
                                     is why its partner is shg_nograd

LOCKSTEP-NATIVE for every picture and counter:
`Machine(ROM).advance(N)` lands on the absolute frame N by construction. Unlike
`seam_irq_trial`, this rail is NOT frozen — and the cross-ROM equality is still
well-defined, because both builds run the same tick the same number of times.
That makes the gold assertion here strictly STRONGER than the debut's: a
stamper that dropped a live camera value is invisible to a still.

THE GEOMETRY (tests/frame_geometry.py, measured there): content line L — drawn
during internal scanline L+1 — is PNG row L + PICTURE_TOP. Band 1 is content
lines 0..111, band 2 is 112..223. Each band's pose table is BAND-LOCAL, so a
band's FAR field is its first line and its NEAR field its last: band 1's near
field is 100..111 and band 2's is 160..223.

THE TWO ORACLES, and why each is the one it is:

  RED, for geometry. This rail's palette (shg_floor.asm) puts red 0 in both
  COOL words and red 31 in both WARM ones, so the rendered red byte over the
  whole frame takes exactly TWO values — 0 and 255 — and "red == 255" is a
  total per-pixel stripe test rather than a threshold. Note it is NOT a
  dominance test: the warm-LIGHT word is G=31 R=31, so `red > green` would
  score only half the warm pixels (measured 128/256 at content 200). Counting
  the population the feature controls is the rule; here the feature
  controls "which stripe", and red==255 is exactly that question.

  BLUE, for the gradient. Every world colour keeps blue 0 and CGADSUB's halve
  bit is clear, so Mesen2's blend reduces to `blue = min(0 + fixed_blue, 31)`
  (SnesPpu.cpp:1372-1378) and the rendered blue channel IS the COLDATA byte,
  whatever the checker is doing. That makes the gradient assertion EXACT and
  checker-immune rather than a monotonic trend: line L must read
  `expand(L >> 3)` on all 256 pixels, where expand is Mesen's BGR555 widening
  `(v << 3) | (v >> 2)`.

WHAT THE GRADIENT DOES TO RED, measured and stated because it shapes the
surface: the plane-select write sets R=G=B, so the ADD lifts red too and
saturates it in the lower band. The red==255 CENSUS per row turns out to be
bit-identical between the subject and the flip control at every one of the 224
lines — which is itself an assertion here (the wash must not move the
geometry), and is why the seam and band cases can run on both builds.
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
ROM = BUILD / "split_h_irq_grad_demo.sfc"
ROM_NOGRAD = BUILD / "shg_nograd.sfc"
ROM_ORIGIN = BUILD / "shg_origin.sfc"
MAP = json.loads((BUILD / "shg" / "symbol_map.json").read_text())

WR = MemoryType.SnesWorkRam

SEAM = 112                       # the band seam, in content lines
LINES = 224
SETTLED = 120                    # absolute frame: fade done, cadence steady
WINDOW = 120                     # the second sample, one window later
GRAD_SHIFT = 3                   # shg_grad's SHG_GR_STEER: value = line >> 3

# The two bands' measured checker-repeat periods, in frames. Camera 1 pans
# 1 px/frame and camera 2 2 px/frame over a world whose checker repeats every
# 64 px vertically, so band 1 returns to its own picture every 64 frames and
# band 2 every 32 — the 2:1 ratio IS the different-speeds claim, and the test
# below asserts BOTH halves (band 2 repeats at 32, band 1 provably does not).
BAND2_PERIOD = 32
BAND1_PERIOD = 64

# Content line 112's warm-pixel population, both arms MEASURED on built ROMs:
# a healthy render puts 171 there; the `stage-byte-interleave` plant (band 2's
# origin through a violated write-twice latch) puts exactly 128. The bound sits
# between them with margin on each side rather than one pixel above the tear.
SEAM_WARM_HEALTHY = 171
SEAM_WARM_TORN = 128
SEAM_WARM_MIN = 160


def _sym(name, scene="split"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


CNT = _sym("ES_SHG_CNT")["start"]
FRAME_CTR = _sym("ES_SM_FRAME", scene=None)["start"]

# The five channels' emitted encodings — what the live register file must hold.
CH = {c["name"]: c for c in MAP["scenes"]["split"]["channels"]}


def _expand(v):
    """Mesen's BGR555 -> RGB8 widening at full brightness, per channel."""
    return ((v << 3) | (v >> 2)) & 0xFF


_FRAMES = {}


def _frame(rom, frame, tmp_path):
    """The RGB image of `rom` at ABSOLUTE frame `frame`, cached.

    Caching is sound precisely because Machine is a pure function of (ROM md5,
    power-on seed, input script) — the same triple cannot produce two pictures.
    """
    key = (str(rom), frame)
    if key not in _FRAMES:
        with Machine(str(rom)) as m:
            m.advance(frame)
            p = tmp_path / f"{Path(rom).stem}_{frame}.png"
            m.screenshot(str(p))
            _FRAMES[key] = Image.open(p).convert("RGB")
    return _FRAMES[key]


def _row_channel(im, content_line, ch):
    px = im.load()
    r = PICTURE_TOP + content_line
    return [px[x, r][ch] for x in range(FRAME_W)]


def _warm_census(im):
    """Per content line, how many of the 256 pixels are WARM (red saturated)."""
    return [sum(1 for v in _row_channel(im, l, 0) if v == 255)
            for l in range(LINES)]


def _band_bytes(im, lo, hi):
    b = im.tobytes()
    stride = FRAME_W * 3
    return b[(PICTURE_TOP + lo) * stride:(PICTURE_TOP + hi) * stride]


def _counters(m):
    """(frame, irq_fires, raw_wakes) — the rail's cadence instruments."""
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


@pytest.fixture(scope="module")
def built():
    for rom in (ROM, ROM_NOGRAD, ROM_ORIGIN):
        if not rom.exists():
            pytest.fail(f"{rom} missing — run `make split_h_irq_grad_demo "
                        f"shg-nograd shg-origin` first")


# =========================================================================
# THE PAYLOAD — what the freed channel actually bought
# =========================================================================

def test_the_gradient_writes_one_exact_coldata_byte_to_every_scanline(
        built, tmp_path):
    """The whole 224-line ramp, EXACT, on all 256 pixels of every line.

    Not a monotonic trend and not a sample: content line L must read blue
    `expand(L >> 3)` at every x, for all 224 lines. Two independent things have
    to be right for that to hold — the boot-built table (one NEW byte per
    scanline through two 112-line repeat entries) and the blue-zero palette
    that makes the rendered channel equal the COLDATA byte — so an off-by-one
    in either header, a dropped terminator, or a stray blue in the world moves
    it. The uniformity across x is what makes it checker-immune: the stripes
    are doing something completely different in red and green on these lines.
    """
    im = _frame(ROM, SETTLED, tmp_path)
    for line in range(LINES):
        blues = set(_row_channel(im, line, 2))
        want = _expand(line >> GRAD_SHIFT)
        assert blues == {want}, (
            f"content line {line}: blue is {sorted(blues)[:4]}, expected a "
            f"uniform {want} (= expand({line} >> {GRAD_SHIFT})) — the COLDATA "
            f"channel is not delivering this line's table byte")


def test_the_nograd_control_leaves_the_blue_channel_flat_at_zero(
        built, tmp_path):
    """The flip control: -DSHG_NO_GRAD builds no table, sets no HDMAEN bit and
    turns colour math off, so NOT ONE pixel of the frame carries blue. Without
    this arm the ramp above could be a property of the plane (its perspective
    really does darken with depth) rather than of the channel under test."""
    im = _frame(ROM_NOGRAD, SETTLED, tmp_path)
    hot = [(l, x) for l in range(LINES)
           for x, v in enumerate(_row_channel(im, l, 2)) if v != 0]
    assert not hot, (
        f"{len(hot)} pixel(s) carry blue with the gradient compiled out "
        f"(first at content line {hot[0][0]}, x={hot[0][1]}) — the flip "
        f"control is not flipping, so the gradient case proves nothing")


def test_across_60_fire_cycles_the_wash_holds_and_only_the_checker_moves(
        built, tmp_path):
    """The state-cycle drive for a MOVING rail, split per channel — which is
    possible here only because each channel means one thing, and each clause
    was measured before it was asserted (frames 120 vs 180):

      BLUE identical (0 px differ).  The wash is scanline-locked, not
        world-locked. A consumed DAS never re-armed, a table byte rewritten in
        place, a channel that drifted off its A1T — all land here.
      RED identical (0 px differ).  The warm/cool stripes are a world-X
        property and both cameras pan only in Y, so the stripe map physically
        cannot move. This is the invariant that makes the seam and band cases
        above frame-independent, and it is also the guard on the design: X is
        held fixed precisely so each band stays on its own stripe, and a camera
        that started drifting in X would break the position oracle silently.
      GREEN differs (measured 4,096 px).  The checker's own dark/light axis is
        what a Y pan moves — so this is the clause that refuses "the rail
        quietly stopped moving", which would otherwise make both invariants
        above true and meaningless.
    """
    a = _frame(ROM, SETTLED, tmp_path)
    b = _frame(ROM, SETTLED + 60, tmp_path)
    for line in range(LINES):
        assert _row_channel(a, line, 2) == _row_channel(b, line, 2), (
            f"content line {line}: the gradient moved across 60 frames — some "
            f"per-frame state is rewriting the COLDATA table or its channel")
        assert _row_channel(a, line, 0) == _row_channel(b, line, 0), (
            f"content line {line}: the stripe map moved across 60 frames — a "
            f"camera is panning in X, which walks its band off its own stripe")
    moved = sum(1 for l in range(LINES)
                for u, v in zip(_row_channel(a, l, 1), _row_channel(b, l, 1))
                if u != v)
    assert moved > 0, (
        "the checker is identical 60 frames apart — the cameras are not "
        "panning, so the two invariants above are claims about a still picture")


# =========================================================================
# THE GOLD ASSERTION — the freed mechanism still renders the classic picture
# =========================================================================

def test_gold_the_irq_origin_renders_byte_identical_to_the_hdma_origin_control(
        built, tmp_path):
    """-DSHG_NO_GRAD (IRQ origin) vs -DSHG_HDMA_ORIGIN (classic origin channel
    pair), byte-equal on TWO absolute frames one window apart — WITH BOTH
    CAMERAS MOVING. `seam_irq_trial` proved this frozen; motion is what makes
    it bite, because the two builds now have to agree about a value that
    changes every frame and travels by completely different routes (a staged
    GP-DMA block fired from an IRQ vs an HDMA table walked from line 0). Two
    frames, because the fire and the VBlank re-stamp run every frame and a
    single capture cannot distinguish "the mechanism holds" from "frame 120
    happened to match". Each ROM boots its own random power-on RAM, so equality
    also proves both builds initialise everything they display (rule 5)."""
    for frame in (SETTLED, SETTLED + WINDOW):
        a = _frame(ROM_NOGRAD, frame, tmp_path)
        b = _frame(ROM_ORIGIN, frame, tmp_path)
        assert a.tobytes() == b.tobytes(), (
            f"frame {frame}: the seam-IRQ picture diverged from the "
            f"HDMA-origin control — the freed mechanism is not delivering the "
            f"classic pair's bytes with the cameras in motion")


# =========================================================================
# THE SEAM AND THE BANDS — geometry, and that the wash did not move it
# =========================================================================

@pytest.mark.parametrize("rom,label", [(ROM, "subject"), (ROM_NOGRAD, "nograd")])
def test_the_seam_row_is_exact_line_111_cool_line_112_warm(
        built, tmp_path, rom, label):
    """The four origin bytes land between content lines 111 and 112. Band 1's
    last line must carry NO warm pixel and band 2's first must be mostly warm.
    Run on BOTH builds deliberately: one line early is the reference's measured
    corruption and the `vtime-off-by-one` plant arms it, and the seam has to
    survive on the build where a third channel is also running.

    THE BOUND IS MEASURED ON BOTH SIDES, not chosen: a healthy render puts 171
    warm pixels on content 112, and the `stage-byte-interleave` plant — band
    2's origin delivered through a violated write-twice latch — puts exactly
    128 there. `> 128` would therefore have caught that tear by ONE pixel,
    which is a threshold that reads as an assertion and behaves as a coin
    toss. SEAM_WARM_MIN sits between the two populations with real margin on
    each side (43 below healthy, 32 above torn)."""
    im = _frame(rom, SETTLED, tmp_path)
    warm_111 = sum(1 for v in _row_channel(im, SEAM - 1, 0) if v == 255)
    warm_112 = sum(1 for v in _row_channel(im, SEAM, 0) if v == 255)
    assert warm_111 == 0, (
        f"[{label}] content line 111 shows {warm_111} warm pixels — band 2's "
        f"origin arrived one line early (the VTIME = SEAM-1 defect)")
    assert warm_112 >= SEAM_WARM_MIN, (
        f"[{label}] content line 112 shows only {warm_112} warm pixels "
        f"(healthy is {SEAM_WARM_HEALTHY}, a latch-interleave tear is "
        f"{SEAM_WARM_TORN}) — band 2's origin did not land at the seam")


def test_the_gradient_does_not_move_the_band_geometry(built, tmp_path):
    """The composited check (test-authoring rule 5): colour math on BG1 must
    change what the frame LOOKS like without changing where anything IS. The
    per-row warm-pixel census over all 224 lines must be bit-identical between
    the subject and the flip control — so the wash is provably a colour
    operation and not, say, a channel that stole a line from the matrix pair or
    shifted the seam. A single-layer byte read cannot make this claim; it needs
    both pictures."""
    subject = _warm_census(_frame(ROM, SETTLED, tmp_path))
    control = _warm_census(_frame(ROM_NOGRAD, SETTLED, tmp_path))
    bad = [(l, subject[l], control[l]) for l in range(LINES)
           if subject[l] != control[l]]
    assert not bad, (
        f"{len(bad)} content line(s) changed stripe population when the "
        f"gradient was composed — first {bad[0]} (line, subject, control). "
        f"The wash is doing more than colour math")


def test_the_band_near_fields_carry_their_own_stripes(built, tmp_path):
    """Camera 1 sits on a COOL stripe and camera 2 one 256-px stripe east on a
    WARM one, so the two bands' near fields are total opposites: every pixel of
    content 100..111 is cool and every pixel of 160..223 is warm. Restricted to
    the NEAR fields deliberately — a perspective view's far field compresses
    distant stripes of BOTH colours (measured: content 0 carries 85 warm pixels
    on a correct render), so a whole-band count would assert the wrong
    population (the population rule). Read on the flip control, where red is the
    unwashed stripe signal."""
    im = _frame(ROM_NOGRAD, SETTLED, tmp_path)
    for line in range(100, SEAM):
        warm = sum(1 for v in _row_channel(im, line, 0) if v == 255)
        assert warm == 0, f"band-1 near field, content {line}: {warm} warm px"
    for line in range(160, LINES):
        warm = sum(1 for v in _row_channel(im, line, 0) if v == 255)
        assert warm == FRAME_W, (
            f"band-2 near field, content {line}: {warm}/{FRAME_W} warm px")


# =========================================================================
# THE INDEPENDENT DRIVERS — two cameras, two speeds, from the picture alone
# =========================================================================

def test_the_two_bands_pan_at_different_speeds(built, tmp_path):
    """The independent-driver signal, asserted as the RATIO of the two bands'
    own repeat periods rather than as "something moved". The world's checker
    repeats every 64 px vertically; camera 1 pans 1 px/frame and camera 2
    2 px/frame, so band 2 returns to its exact picture in 32 frames and band 1
    needs 64. FOUR clauses, and each refuses a different way of being wrong:
    band 2 repeating at 32 fixes its speed; band 2 NOT repeating at 16 refuses
    a band that has STOPPED (a frozen band trivially "repeats" at every offset,
    so a periodicity test without this clause passes on a rail whose per-frame
    re-stage was deleted — which is the `stage-not-restamped` plant); band 1
    NOT repeating at 32 refuses "one camera drives both bands", the failure
    this split exists to make visible; and band 1 repeating at 64 fixes its
    speed at exactly half. Only the picture is read — the camera positions are
    WRAM state and would be a proxy."""
    base = _frame(ROM, SETTLED, tmp_path)
    b1_0 = _band_bytes(base, 0, SEAM)
    b2_0 = _band_bytes(base, SEAM, LINES)
    quarter = _frame(ROM, SETTLED + BAND2_PERIOD // 2, tmp_path)
    half = _frame(ROM, SETTLED + BAND2_PERIOD, tmp_path)
    full = _frame(ROM, SETTLED + BAND1_PERIOD, tmp_path)

    assert _band_bytes(quarter, SEAM, LINES) != b2_0, (
        f"band 2 is unchanged after {BAND2_PERIOD // 2} frames — camera 2 has "
        f"stopped, and a stopped band satisfies every periodicity clause below "
        f"vacuously")
    assert _band_bytes(half, SEAM, LINES) == b2_0, (
        f"band 2 did not return to its own picture after {BAND2_PERIOD} "
        f"frames — camera 2 is not panning at 2 px/frame")
    assert _band_bytes(half, 0, SEAM) != b1_0, (
        f"band 1 ALSO repeated after {BAND2_PERIOD} frames — the two bands are "
        f"moving at the same rate, so nothing here shows two independent "
        f"drivers")
    assert _band_bytes(full, 0, SEAM) == b1_0, (
        f"band 1 did not return to its own picture after {BAND1_PERIOD} "
        f"frames — camera 1 is not panning at 1 px/frame")


# =========================================================================
# H1 — the wai double-wake, measured on THIS loop
# =========================================================================

def test_h1_the_armed_wai_wakes_exactly_twice_per_frame(built):
    """Two samples one window apart, deltas EXACT in steady state: the frame
    counter, the fire counter and the wake counter advance +N, +N, +2N. The
    fire counter marching in lockstep with scene_mgr's frame counter is the
    once-per-frame cadence; the wake counter at exactly 2/frame is H1 — wai
    returns at the seam IRQ as well as at NMI (SnesCpu.Shared.h:336-341), and
    the handshake gate sends the seam wake back to sleep so the tick's camera
    advance never runs mid-frame."""
    with Machine(str(ROM)) as m:
        m.advance(SETTLED)
        f0, irq0, wake0 = _counters(m)
        m.advance(WINDOW)
        f1, irq1, wake1 = _counters(m)
    assert f1 - f0 == WINDOW, "the frame counter is not one per frame"
    assert irq1 - irq0 == WINDOW, (
        f"seam-IRQ fires {irq1 - irq0} over {WINDOW} frames — the fire cadence "
        f"is not once per frame")
    assert wake1 - wake0 == 2 * WINDOW, (
        f"raw wai wakes {wake1 - wake0} over {WINDOW} frames — expected "
        f"exactly 2 per frame (the seam wake + the NMI wake)")


def test_h1_control_the_unarmed_build_wakes_once_per_frame(built):
    """The other arm: -DSHG_HDMA_ORIGIN never arms the IRQ, so its wai wakes
    once per frame and its fire counter stays zero. Without this control the 2x
    measurement above could be a property of the counter rather than of the
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
# H2 — the fire window, RE-MEASURED for this rail
# =========================================================================

def test_h2_the_fire_lands_in_the_seam_hblank_window(built):
    """The handler's own OPHCT/OPVCT mirrors, read from the PPU latch: entry on
    internal scanline 112 BEFORE the HBlank flag (dot < 274 — the spin gate is
    what carries it across), fire completion early in internal scanline 113
    before content line 112's first flush trigger at dot 22
    (SnesPpu.cpp:883-884). Measured on THIS rail: entry dot 47, completion dot
    16 — the spec's trial completed at dot 10, and the difference is the point
    of re-measuring rather than inheriting. The assertions are the WINDOW
    bounds, not the exact dots, so a legitimate cycle-level shift cannot flap
    them."""
    with Machine(str(ROM)) as m:
        m.advance(SETTLED)
        (eh, ev), (fh, fv) = _latches(m)
    assert ev == SEAM, (
        f"handler entry at internal scanline {ev}, expected {SEAM} — VTIME is "
        f"not arming the seam line")
    assert eh < 274, (
        f"handler entry at dot {eh} — past the HBlank flag; the entry readout "
        f"would have eaten the spin gate's margin")
    assert fv == SEAM + 1, (
        f"fire completed on internal scanline {fv}, expected {SEAM + 1} (the "
        f"trailing-HBlank fire spills its completion into the next line's "
        f"left edge)")
    assert fh < 22, (
        f"fire completed at dot {fh} of scanline {fv} — past content line 112's "
        f"first flush trigger (dot 22): the seam write missed its window")


# =========================================================================
# THE STRUCTURAL CHANNEL BUDGET — the live silicon, not a shadow
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


def test_the_freed_channels_pay_for_the_gradient_on_the_silicon(built):
    """THE RAIL'S HEADLINE, on the silicon: the live $420C mask holds exactly
    THREE bits — the two matrix channels and the gradient — while the seam pair
    is fully CONFIGURED (DMAP/BBAD matching its claims' emitted encodings, byte
    for byte) and NOT HDMA-enabled, because it fires by MDMAEN from the IRQ
    handler. That is the whole trade in one read: two channels left the mask,
    one came back carrying a payload. This is the SuperForge form of the reference's
    G_MSK2 == 0 assert, and the plant that ORs the seam bits into the scene's
    mask must turn exactly this case red (the picture cannot see that defect —
    an enabled seam channel's stage block reads as a count-0 table and
    terminates at line 0 doing nothing)."""
    dma, _regs = _live_state(ROM)
    want = ((1 << CH["shgab"]["ch"]) | (1 << CH["shgcd"]["ch"])
            | (1 << CH["shggr"]["ch"]))
    assert dma.hdmaen == want, (
        f"live HDMAEN ${dma.hdmaen:02X}, expected ${want:02X} (matrix pair + "
        f"gradient) — a seam channel leaked into the HDMA mask, or the "
        f"gradient fell out of it")
    for claim in ("shgab", "shgcd", "shggr", "shgxy", "shghv"):
        ch = CH[claim]
        live = dma.channels[ch["ch"]]
        assert live.dmap == ch["dmap"], (
            f"{claim}: live DMAP ${live.dmap:02X} != declared ${ch['dmap']:02X}")
        assert live.bbad == ch["bbad"], (
            f"{claim}: live BBAD ${live.bbad:02X} != declared ${ch['bbad']:02X}")


def test_the_gold_control_spends_the_pair_on_the_origin_instead(built):
    """The same silicon read on -DSHG_HDMA_ORIGIN, and it is the budget
    argument's other half: FOUR bits in $420C — the matrix pair plus the origin
    pair — and NO gradient bit, because that build has no freed channel to
    spend. Its reconstructed NMITIMEN also carries no IRQ enable, while the
    subject's carries the V-IRQ bit. The two builds differ at the silicon
    exactly where the mechanism says they should and nowhere else."""
    dma, regs = _live_state(ROM_ORIGIN)
    want = ((1 << CH["shgab"]["ch"]) | (1 << CH["shgcd"]["ch"])
            | (1 << CH["shgxy"]["ch"]) | (1 << CH["shghv"]["ch"]))
    assert dma.hdmaen == want, (
        f"control HDMAEN ${dma.hdmaen:02X}, expected ${want:02X} — the classic "
        f"build should enable the origin pair as real HDMA")
    assert not dma.hdmaen & (1 << CH["shggr"]["ch"]), (
        "the control enabled the gradient channel — it has no freed channel to "
        "spend, so that bit must be absent")
    assert not regs.nmitimen & 0x30, (
        f"control NMITIMEN ${regs.nmitimen:02X} has an IRQ enable bit set — "
        f"the control must not arm the timer")
    _dma_irq, regs_irq = _live_state(ROM)
    assert regs_irq.nmitimen & 0x20, (
        f"subject NMITIMEN ${regs_irq.nmitimen:02X} lacks the V-IRQ enable — "
        f"the subject build is not armed")
