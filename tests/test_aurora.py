"""aurora — a night sky drawn WITHOUT A PALETTE, and a card that plays itself.

WHAT IS UNDER TEST. Two claims, and they are asserted on the picture rather
than on the state that produced it.

The first is DIRECT COLOUR. On an 8bpp layer with CGWSEL bit 0 set the pixel
byte IS the colour — r3 g3 b2, each channel extended one bit by the tilemap
entry's palette field (Mesen2 SnesPpu.cpp GetRgbColor, the
`bpp == 8 && directColorMode` arm) — so BG1 consults NO CGRAM WORD AT ALL. The
way to prove that from outside is not to read $2130 back; it is to show the
sky is painted in colours CGRAM DOES NOT CONTAIN. An indexed BG1 could not
put a single one of them on screen.

The second is that the rail is a PIECE THAT PLAYS: black, a bare sky, the pen
and the rise together, the held card, black, and round again in a new colour.
Every beat here is observed as a rendered difference, and the loop's return is
asserted on the frame it should land on rather than "eventually".

THE ORACLE IS THE ROM, NOT THE GENERATOR. Where a case needs to know what the
base CHR page holds, it reads those bytes out of build/aurora.sfc — located by
the allocator's own emitted ROM claim — never out of tools/gen_aurora_assets.py.
Importing the generator would compare the ROM against the Python that authored
it, which agrees with itself by construction.

EVERY ADDRESS IS DERIVED. Direct-page words, the VRAM CHR base and the ROM
claim all come out of build/aur/symbol_map.json, so a repack moves this module
with the ROM instead of against it (`make map-check`).

WHAT IS DELIBERATELY NOT ASSERTED: that successive passes are pixel-identical.
They are not, and that is the design — the hue cursor is left running across
the loop so each pass rises in the colour the cycle has reached. The rail
loops in SHAPE, not in pixels, and `test_each_pass_rises_in_a_colour_the_last
_one_did_not` is the case that pins the difference as intended rather than
letting it read as drift.

LOCKSTEP-NATIVE: `Machine` only, absolute frames, no wall-clock surface.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
BUILD = SUPERFORGE / "build"
ROM = BUILD / "aurora.sfc"
MAP = json.loads((BUILD / "aur" / "symbol_map.json").read_text())

sys.path.insert(0, str(SUPERFORGE / "vendor"))                   # noqa: E402
from machine import Machine, MemoryType                          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))         # noqa: E402
from frame_geometry import PICTURE_TOP                           # noqa: E402

W, V, C = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
           MemoryType.SnesCgRam)


# --------------------------------------------------------------------------
# the map, and the generator's geometry — both DERIVED, neither retyped
# --------------------------------------------------------------------------
_POOL = list(MAP["globals"])
for _sc in MAP["scenes"].values():
    _POOL += _sc["placements"]


def _sym(name):
    """The placement the allocator emitted under this name."""
    return next(p for p in _POOL if p["sym"] == name)


def _dp(name):
    p = _sym(name)
    assert p["class"] == "dp", (name, p["class"])
    return p["start"]


def _art():
    """The generated geometry, read out of the .inc BOTH sides compile against.

    Not retyped here and not imported from the generator: this is the same
    file `aur_hue.asm` and `aur_pres.asm` assemble against, so a constant that
    moved moves in the ROM and in the test together.
    """
    out = {}
    for line in (BUILD / "assets" / "aur_art.inc").read_text().splitlines():
        if "=" not in line or not line.startswith("AUR_"):
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = int(v.split(";")[0].strip())
    return out


ART = _art()
PST, PTIM = _dp("ES_AUR_PST"), _dp("ES_AUR_PTIM")
WRESET = _dp("ES_AUR_WRESET")
PHASE, SLOT, HOLD = _dp("ES_AUR_PHASE"), _dp("ES_AUR_SLOT"), _dp("ES_AUR_HOLD")
FADE = _dp("ES_FADE_CTL")
WFRAME = _dp("ES_AUR_WFRAME")

# The beats, in the jump table's order — aur_pres.asm and game/aurora/aurora.inc
P_UP, P_PLAY, P_HOLD, P_DOWN, P_RESET = range(5)

# BG1's CHR base, as a WORD address, and the tinted run inside it.
CHR1_WORD = _sym("ES_V_AUR_CHR1")["start"]
HUE_BASE, HUE_TILES = ART["AUR_HUE_BASE"], ART["AUR_HUE_TILES"]
CLIFF = ART["AUR_CLIFF"]

# The sky band the aurora hangs in: above the hills, below the top edge. Used
# as the observation window everywhere a case reads "the aurora".
SKY_TOP, SKY_BOT = 16, 120


def _pixels(m, path):
    m.screenshot(str(path))
    return Image.open(path).convert("RGB")


def _sky(im):
    """Every pixel of the sky band, as (r, g, b)."""
    px = im.load()
    return [px[x, PICTURE_TOP + y]
            for y in range(SKY_TOP, SKY_BOT) for x in range(im.size[0])]


def _cgram_colours(m):
    """CGRAM as the ROM left it, as 8-bit RGB triples.

    Mesen hands back a 24-bit PNG, so a 5-bit CGRAM channel has to be brought
    into the same space to be compared with one. The PPU's own expansion is
    (v << 3) | (v >> 2) — the top three bits repeated into the low ones — and
    that is what SnesPpu's RGB555-to-RGB888 does.
    """
    raw = m.read_bytes(C, 0, 512)
    out = set()
    for i in range(0, 512, 2):
        w = raw[i] | (raw[i + 1] << 8)
        r, g, b = w & 31, (w >> 5) & 31, (w >> 10) & 31
        out.add(((r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)))
    return out


def _run_to_beat(m, beat, limit=900):
    """Advance until the presentation reaches `beat`, and say where it landed."""
    for f in range(limit):
        if m.read_u16(W, PST) == beat:
            return f
        m.advance(1)
    raise AssertionError(f"beat {beat} never arrived within {limit} frames")


# =============================================================================
# The headline: BG1 is painted in colours CGRAM does not hold
# =============================================================================
def test_the_sky_is_drawn_from_colours_cgram_does_not_hold(tmp_path):
    """DIRECT COLOUR, asserted the only way it can be from outside the PPU.

    Reading CGWSEL back would prove a register was written, not that the layer
    obeys it. What proves it is the PICTURE: on an indexed BG1 every pixel on
    screen is some CGRAM word, because that is the only place a colour could
    have come from. So if the sky is full of colours CGRAM does not contain,
    BG1 did not read CGRAM to draw them.

    The window is the sky band, which is BG1 plus BG2's stars. The stars ARE
    indexed and do land in CGRAM — they are the built-in control here, and
    their presence is why this asserts a large majority rather than all.
    """
    with Machine(str(ROM)) as m:
        _run_to_beat(m, P_HOLD)
        m.advance(30)
        im = _pixels(m, tmp_path / "card.png")
        cg = _cgram_colours(m)
        sky = set(_sky(im))
    foreign = {c for c in sky if c not in cg}
    # MEASURED on this ROM: 166 distinct colours in the band, 161 of them
    # outside CGRAM's 242 — 97.0%. The five that coincide are black plus four
    # near-misses, which is what a 2048-colour lattice overlapping a 256-word
    # palette looks like. The thresholds sit well under that with room for the
    # art to move; the number they must stay clear of is ZERO.
    #
    # DISTINCT colours, not pixels: 47% of the band's PIXELS are black, and
    # black is in every palette, so a pixel-weighted ratio would measure how
    # much night sky there is rather than where the colours came from.
    assert len(sky) > 120, f"the sky band holds only {len(sky)} distinct colours"
    assert len(foreign) / len(sky) > 0.9, (
        f"{len(foreign)}/{len(sky)} of the sky's colours are outside CGRAM. "
        f"On an INDEXED BG1 this ratio is 0 by construction — every pixel "
        f"would have to be a CGRAM word. A low ratio means direct colour is "
        f"not actually in force, whatever $2130 was written with")
    # ...and the converse, so the case cannot pass on a black screen: the
    # colours CGRAM does hold are still on screen, drawn by BG2 and the OBJs.
    assert sky & cg, "nothing indexed is being drawn at all — check the window"


# =============================================================================
# The beats, each observed as a rendered difference
# =============================================================================
def test_the_scene_fades_up_on_the_whole_picture(tmp_path):
    """The first beat reveals the card COMPLETE — sky, hills, figures and the
    aurora already hanging in it — and only the word is missing.

    That is a deliberate reversal. An earlier cut shipped the tinted run UNLIT
    in the base CHR page so the cycle's first pass over it was the aurora
    ARRIVING, which cost nothing and made a pretty beat; the owner watched
    both and kept this one, because the arrival forced a screen-coherent slot
    order and that order reads as a wipe. The aurora being present from the
    first frame is now a property worth holding, not an absence of one.
    """
    with Machine(str(ROM)) as m:
        _run_to_beat(m, P_UP)
        m.advance(8)                          # mid-ramp: lit enough to read
        assert m.read_u16(W, PST) == P_UP, "the beat ended before it was read"
        up = _pixels(m, tmp_path / "up.png")
        _run_to_beat(m, P_HOLD)
        m.advance(30)
        card = _pixels(m, tmp_path / "card.png")

    # THE PREDICATE HAD TO BE MEASURED AGAINST ITS OWN COUNTER-CASE, and the
    # first cut of it was not. `max(g, b) > 40 and b > r + 12` sounds like "an
    # aurora colour" and is really "a blue-ish pixel" — the night sky gradient
    # is blue, so a sky with NO aurora in it scored 661 against a threshold of
    # 500 and the case passed on the defect it exists to catch
    # (`base-page-ships-the-run-unlit`, TEST-BLIND). Measured on both ROMs at
    # this tighter predicate: 3,091 shipped against 39 with the run unlit.
    def _lit(im):
        return sum(1 for r, g, b in _sky(im) if max(g, b) > 60 and b > r + 16)
    assert _lit(up) > 1500, (
        f"only {_lit(up)} aurora-coloured pixels while the scene fades up — "
        f"the base CHR page is supposed to ship the tinted run LIT. Measured: "
        f"3,091 when it does, 39 when it does not")
    # ...and the WORD is the thing that is missing, which is what the pen beat
    # is for. Read in the black band, not the sky.
    def _ink(im):
        px = im.load()
        return sum(1 for y in range(CLIFF + 8, 222) for x in range(im.size[0])
                   if sum(px[x, PICTURE_TOP + y]) > 90)
    assert _ink(up) < 40, f"{_ink(up)} ink pixels before the pen has started"
    assert _ink(card) > 400, "the word never arrived"


def test_the_loop_closes_on_the_frame_it_should_and_keeps_closing(tmp_path):
    """The whole piece, as a beat sequence — and the return is asserted on an
    EXACT frame count rather than "eventually".

    A loop that merely comes back round would pass a test that waited for UP
    to reappear; this one pins the period, so a beat that started overrunning
    (a ramp that stopped going idle, a pen that stopped finishing) is a red
    even though the loop still works.
    """
    seen = []
    with Machine(str(ROM)) as m:
        last = None
        for f in range(1300):
            st = m.read_u16(W, PST)
            if st != last:
                seen.append((f, st))
                last = st
            m.advance(1)
    order = [st for _, st in seen]
    # The first entry is the power-on frame, before `enter` has run: dp is
    # RANDOM at boot (rule 5) and the beat word has no meaning yet.
    assert order[1:6] == [P_UP, P_PLAY, P_HOLD, P_DOWN, P_RESET], order[:6]
    ups = [f for f, st in seen[1:] if st == P_UP]
    assert len(ups) >= 3, f"only {len(ups)} passes in 1300 frames: {seen}"
    periods = [b - a for a, b in zip(ups, ups[1:])]
    assert len(set(periods)) == 1, (
        f"the loop period wanders: {periods}. Every beat waits on something "
        f"that finishes in a fixed number of frames, so it must not")
    assert periods[0] == 390, (
        f"the loop closes in {periods[0]} frames, not the 390 measured when "
        f"the beats landed. A changed ramp, hold or pen moves this — update "
        f"the number WITH the measurement, do not widen the assertion")


def test_the_colour_travels_and_the_loop_never_puts_it_back(tmp_path):
    """THE LOOP IS NOT A RESTART, and this is the case that says so.

    The cycle runs underneath every beat and nothing resets it, so a pass
    opens on whatever hue the drift has reached. That is the rail's whole
    claim — a fifty-one-second journey from cyan-teal to violet — and it is
    exactly what a tidy-looking loop destroys: an earlier cut restored the CHR
    page at each lap, every pass opened on the same teal, and fifteen of the
    sixteen phases became unreachable. Every other case in this module passed
    against that. This one would not.
    """
    shots, phases = [], []
    with Machine(str(ROM)) as m:
        for k in range(3):
            _run_to_beat(m, P_HOLD)
            phases.append(m.read_u16(W, PHASE))
            m.advance(30)
            shots.append(set(_sky(_pixels(m, tmp_path / f"pass{k}.png"))))
            _run_to_beat(m, P_UP)             # ...on into the next pass
    assert len(set(phases)) == 3, (
        f"three passes stood at phases {phases} — the cursor is being reset")
    for a, b in ((0, 1), (1, 2), (0, 2)):
        shared = len(shots[a] & shots[b]) / len(shots[a] | shots[b])
        assert shared < 0.9, (
            f"passes {a} and {b} share {shared:.0%} of their colours: the "
            f"cycle is not travelling between them")


def _diff(a, b):
    pa, pb = a.load(), b.load()
    return sum(1 for y in range(a.size[1]) for x in range(a.size[0])
               if pa[x, y] != pb[x, y])


def test_b_stops_the_whole_piece_and_not_merely_the_roll(tmp_path):
    """B freezes the cycle, the pen AND the beats.

    The last of those is the one worth a case: a still of a presentation that
    is still advancing is not a still, and an earlier cut of this rail held
    only the colour cycle while the pen wrote on underneath it.

    WHY THIS IS COMPARATIVE RATHER THAN PIXEL-IDENTICAL. `Machine.screenshot`
    spends one emulated frame WITH BOTH PADS RELEASED — its documented
    contract, the stated-state discipline — so a capture taken while B is held
    is nevertheless preceded by one unheld frame, and the ROM correctly
    advances one tick for it. A bit-identical assertion across two captures is
    therefore not available to any test of a held input, and writing one would
    be testing the harness rather than the rail. So the held span is measured
    against a FREE-RUNNING span of the same length from the same point, and
    the claim is the ratio.

    MEASURED, from the beat PLAY + 10 frames over a 60-frame span: 36 pixels
    move while B is held against 1,057 free — 29x. The 36 are the two capture
    frames' own ticks and nothing else, which is why the cursor and the beat
    below are asserted UNCHANGED and exactly: those reads cost no frame, so
    they see the held stretch with no tax on it.

    THE CONTROL'S MOTION IS THE PEN, and that is worth naming because it used
    to be something else. While the rail shipped an aurora that ROSE, the same
    span moved 10,135 pixels and the ratio was 260x. The rise is gone — the
    base page ships the tinted run lit — so what remains to move in sixty
    frames is the word being written, plus a colour drift so slow that four
    8x8 cells change in a hundred and twenty frames. A control this much
    smaller is not a weaker test; it is an honest one, and the number it must
    stay clear of is still the held reading.

    THE SPAN MUST NOT APPROACH THE LOOP PERIOD, which is 390 frames. A
    free-running control of about that length returns the picture to where it
    started and the control collapses — measured on the earlier 398-frame loop
    at a span of 400, it reported 133 px and would have "passed" against a
    rail that was not frozen at all.
    """
    span = 60
    with Machine(str(ROM)) as m:
        _run_to_beat(m, P_PLAY)
        m.advance(10)                          # ...mid-word
        before = _pixels(m, tmp_path / "b0.png")
        beat, slot = m.read_u16(W, PST), m.read_u16(W, SLOT)
        m.advance(span, pad1={"b": True})
        after = _pixels(m, tmp_path / "b1.png")
        assert m.read_u16(W, PST) == beat, "the beats advanced under B"
        assert m.read_u16(W, SLOT) == slot, "the cycle advanced under B"
        held = _diff(before, after)
        m.advance(60)                          # released
        assert _diff(after, _pixels(m, tmp_path / "b2.png")) > 0, (
            "released, the piece did not resume")
    with Machine(str(ROM)) as m:               # the control, same start
        _run_to_beat(m, P_PLAY)
        m.advance(10)
        c0 = _pixels(m, tmp_path / "c0.png")
        m.advance(span)
        free = _diff(c0, _pixels(m, tmp_path / "c1.png"))
    assert free > 500, (
        f"the free-running control only moved {free} pixels in {span} frames, "
        f"so it cannot tell a frozen picture from a running one. Check the "
        f"span is not near the 390-frame loop period")
    assert held * 8 < free, (
        f"B held: {held} pixels moved against {free} free over the same span. "
        f"Measured when the rise was removed: 36 against 1,057")


def test_the_pen_writes_the_word_and_then_holds_it(tmp_path):
    """The word arrives, and then STOPS arriving.

    Both halves matter. The stream's cursor only moves forward and the frame
    count is what ends it, so a pen that kept playing past AUR_WRITE_FRAMES
    would read whatever follows the stream in ROM as tile data — and the
    picture would still contain a written word while it did.
    """
    def _ink(im):
        px = im.load()
        return sum(1 for y in range(CLIFF + 8, 222) for x in range(im.size[0])
                   if sum(px[x, PICTURE_TOP + y]) > 90)
    with Machine(str(ROM)) as m:
        _run_to_beat(m, P_PLAY)
        m.advance(6)
        early = _ink(_pixels(m, tmp_path / "w0.png"))
        m.advance(40)
        mid = _ink(_pixels(m, tmp_path / "w1.png"))
        _run_to_beat(m, P_HOLD)
        m.advance(20)
        done = _ink(_pixels(m, tmp_path / "w2.png"))
        m.advance(80)
        still = _ink(_pixels(m, tmp_path / "w3.png"))
    assert early < mid < done, (
        f"the word is not being written: {early} -> {mid} -> {done} ink pixels")
    assert done > 400, f"only {done} ink pixels in the finished word"
    assert still == done, (
        f"the word kept changing after the stream was spent ({done} -> "
        f"{still}): the cursor is running past AUR_WRITE_FRAMES and reading "
        f"whatever follows the stream in ROM")


def test_nothing_reads_a_byte_the_rom_never_wrote(tmp_path):
    """Rule 5, and the regression for a defect a screenshot could not see.

    The hue blob is `bank_tiled`, and a chunk boundary never splits a TILE —
    which is true and was not the invariant that mattered. A1B is CONSTANT, so
    an uncut TRANSFER that crosses one wraps inside its own bank to $0000 and
    reads the WRAM mirror. Seven of the cycle's slices cross. The picture
    stayed recognisably an aurora with a few tiles of garbage in it; the
    uninitialised-read detector named it in one run, at $05:09F3.

    Driven across two whole presentation loops, so the un-rise and the pen's
    erase are both covered as well as the cycle.
    """
    from mesen_runner import MesenRunner       # noqa: E402 -- vendor is on the
                                               #   path from the module header
    r = MesenRunner()
    try:
        # EMULATED FRAMES THROUGHOUT, and PARKED before the read. The detector
        # reads a free-running core, so a wall-clock wait would make what it
        # sees a function of host load rather than of the ROM (`make
        # time-check`, docs/45).
        r.load_rom_with_uninit_detection(str(ROM), frames=60)
        r.wait_frames(850)                     # two loops and a margin
        r.debug_break()
        reads = r.get_uninitialized_reads()
        r.debug_resume()
    finally:
        r.stop()
    named = {mt: sorted(a) for mt, a in reads.items() if a}
    assert not named, (
        "reads of bytes never written since power-on: "
        + "; ".join(f"{mt}: " + " ".join(f"${a:04X}" for a in v[:16])
                    for mt, v in named.items()))
