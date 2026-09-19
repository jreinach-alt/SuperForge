"""scene_mgr's CUT transition style, and the declaration that selects it.

A `[[edge]]` in game.toml declares `style = "fade" | "cut" | "mosaic"`; the
allocator emits `ES_E_<SRC>_TO_<DST>_CUT` from it and `SM_SWITCH` picks the
entry point from that symbol at assembly time. So there are two claims to
prove, and they are different claims:

  1. THE CUT RENDERS AS A CUT — NO RAMP, AND NO BLANK FRAME EITHER. Across a
     cut switch the picture goes straight from the outgoing scene to the
     incoming one: no frame shows a dimmed version of either, and no frame is
     blank. That is the user-visible invariant, so it is asserted on
     SCREENSHOT PIXELS. A fade at brightness 7/15 renders colours that appear
     in NEITHER steady frame, which is what the dimmed half refuses; a frame
     of forced blank is all (0,0,0), which is what the blank half refuses.
     (The INIDISP shadow trace is read too, but as a SECOND, sharper statement
     of the same thing — never as the primary evidence. The shadow is engine
     state; the pixels are what a player sees.)

     THE BLANK HALF IS NEW, AND IT IS A REAL DEFECT THIS ONCE SHIPPED. The cut
     used to arm forced blank a frame AHEAD, through the INIDISP shadow, so
     the switch could run under it — and it needed the whole frame, because
     meteor_event's enters re-uploaded 32 KB of Mode-7 plane one way and
     repainted a 2 KB tilemap the other. MEASURED, that was exactly one
     all-black frame on each swap, between two pictures that are pixel-
     identical to each other: a blink, and the project owner reported it as
     one. The uploads are boot work now and @switch holds the blank itself,
     around the body, inside the VBlank the tick starts in.

  1b. AND IT HOLDS THAT BLANK INSIDE VBLANK. The picture case above says no
     displayed frame is blank; case 1b says WHY, at the mechanism, by reading
     the PPU scanline at both ends of the switch's own two $2100 writes. It is
     the gate that fires when a future `enter` grows past the VBlank it has:
     the picture case only goes red once the overrun is a visible black band,
     while this one goes red on the scanline before it.

  2. THE FADE IS UNCHANGED FOR EVERYONE ELSE. A rail whose edges all declare
     "fade" still ramps — the same picture-level assertion, inverted: the
     window MUST contain frames whose colours are in neither steady set,
     because that is what a brightness ramp is. microzero's title -> race is
     the control, and it is a real control rather than a mirror: it is a
     different rail, a different composition, and its call site still uses the
     raw `jsr sm_request` every pre-the spec rail uses.

  3. THE DECLARATION IS WHAT THE ROM DOES. The style is read from the emitted
     map, not typed into the test, and the rendering assertion is chosen BY
     it. A rail that declares "cut" and runs the fade machine — by bypassing
     SM_SWITCH and hand-writing `jsr sm_request`, the one bypass the macro
     leaves open — fails here. tools/plants/scene_mgr_cut.py plants exactly
     that, and the ramp-reinstating half too.

Lockstep Machine for every PICTURE claim: a pure function of (rom md5,
power-on seed, input script), every read from a parked exact frame, no wall
clock anywhere. Note that `Machine.screenshot` itself costs one emulated frame,
so photographing a window IS the frame-by-frame walk of it — the loops below
rely on that rather than interleaving advances. Case 1b is the one exception
and it is a different question, not a different discipline: "which SCANLINE was
the beam on" is not a thing a frame-parked capture can answer, so it reads the
PPU counter at a breakpoint on the store itself, the way
tests/test_scene_mgr_shadow.py measures the transition's cost. Still bounded in
emulated frames, still no wall clock.

runtime: ~1:30 warm — case 1b breaks on every $2100 write for ~460 frames to
reach both swaps, and each break is a debugger round trip.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

BLACK = (0, 0, 0)

# How many frames after the request the switch window can possibly span. The
# cut's own bound is asserted separately and is much tighter; this is only the
# walk length, wide enough to contain a 15-out/1-blank/15-in fade so the fade
# control photographs its whole ramp.
WINDOW = 34


# =============================================================================
# fixtures
# =============================================================================
def _make(target):
    r = subprocess.run(["make", target], cwd=SUPERFORGE, capture_output=True,
                       text=True)
    assert r.returncode == 0, f"make {target} failed:\n{r.stdout}\n{r.stderr}"


def _map(subdir):
    return json.loads((SUPERFORGE / "build" / subdir / "symbol_map.json").read_text())


@pytest.fixture(scope="module")
def met():
    _make("meteor_event")
    return _map("met")


@pytest.fixture(scope="module")
def mz():
    _make("microzero")
    return _map("mz")


# =============================================================================
# helpers — every one reads an OUTPUT region or sequences the drive
# =============================================================================
def _sym(jmap, name):
    for p in jmap["globals"]:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


def _style(jmap, src, dst):
    """The DECLARED style of one edge, from the emitted map. The test never
    types the style: the whole point is that the declaration selects."""
    for e in jmap["edges"]:
        if e["src"] == src and e["dst"] == dst:
            return e["style"]
    raise KeyError(f"no declared edge {src}->{dst} in the emitted map")


def _u8(m, addr):
    return m.read_bytes(MemoryType.SnesWorkRam, addr, 1)[0]


def _u16(m, addr):
    b = m.read_bytes(MemoryType.SnesWorkRam, addr, 2)
    return b[0] | (b[1] << 8)


def _colours(m, tmp_path, name):
    """The distinct RGB triples of one RENDERED frame. Costs one emulated
    frame (Machine.screenshot's own advance)."""
    from PIL import Image
    p = tmp_path / name
    m.screenshot(str(p))
    with Image.open(p) as img:
        return set(img.convert("RGB").getdata())


def _walk_switch(m, tmp_path, tag, inidisp_addr, cur_addr, n=WINDOW):
    """Photograph n consecutive frames from a parked start, recording per
    frame the distinct colours ON SCREEN, the INIDISP shadow the NMI commits,
    and the running scene id. Returns [(colours, inidisp, cur)].

    THE TWO READS COME FIRST, then the capture — `Machine.take_screenshot`
    says so in its own docstring, because the capture SPENDS a frame. Taken
    the other way round (as this did until the cut stopped blanking) every
    read reports the state of the frame AFTER the one photographed, which is
    invisible while the values are steady and wrong exactly at the switch: the
    scene id read beside the outgoing picture is the incoming scene's."""
    out = []
    for k in range(n):
        level = _u8(m, inidisp_addr)
        cur = _u8(m, cur_addr)
        out.append((_colours(m, tmp_path, f"{tag}_{k:02d}.png"), level, cur))
    return out


def _run_to_transition(m, phase_addr, limit=900):
    """Advance until the phase machine leaves 'run'. SEQUENCING only — the
    assertions below are all on rendered frames."""
    for _ in range(limit):
        if _u8(m, phase_addr) != 0:
            return
        m.advance(1)
    raise AssertionError("the phase machine never left phase 0")


def _classify(window, before, after):
    """Split a photographed switch window into the three populations the two
    styles differ on: frames that are entirely black, frames drawn only from
    colours the steady-state frames use, and frames showing anything else —
    which, on this hardware, means a brightness level between 0 and 15."""
    steady = before | after
    blank = [k for k, (c, _, _) in enumerate(window) if c == {BLACK}]
    clean = [k for k, (c, _, _) in enumerate(window)
             if c != {BLACK} and c <= steady]
    dimmed = [k for k, (c, _, _) in enumerate(window)
              if c != {BLACK} and not c <= steady]
    return blank, clean, dimmed


# =============================================================================
# 1. the cut renders as a cut — on the picture
# =============================================================================
@pytest.mark.parametrize("edge", [("level", "impact"), ("impact", "level")])
def test_a_cut_edge_renders_neither_a_ramp_nor_a_blank_frame(met, tmp_path,
                                                             edge):
    """THE HEADLINE. Across each of meteor_event's two declared-cut swaps the
    picture goes straight from the outgoing scene to the incoming one: no
    rendered frame shows a dimmed picture, and no rendered frame is blank.

    The ramp half is a colour-SET containment on screenshot pixels, which is
    what makes it able to see a fade at all. A luminance threshold would let
    brightness 14/15 through; a colour set cannot, because the PPU's master
    brightness rescales every channel, so a dimmed green is simply not the
    authored green (Mesen expands BGR555 as (v << 3) | (v >> 2), and 14/15 of
    an authored value does not land back on it).

    The blank half is the owner-reported defect, stated as the absence it is.
    Its non-vacuity guard is the SCENE ID changing inside the window, not the
    presence of a blank frame as it used to be: on this rail the two pictures
    either side of a swap are pixel-identical by design — that is exactly why
    a single black frame read as a blink — so "the picture never changed" and
    "the swap never happened" are indistinguishable from the pixels alone."""
    src, dst = edge
    assert _style(met, src, dst) == "cut", (
        f"this case exists to test a CUT edge; {src}->{dst} declares "
        f"{_style(met, src, dst)!r}")
    phase = _sym(met, "ES_SM_CTL")["start"] + 2
    cur = _sym(met, "ES_SM_CTL")["start"]
    inidisp = _sym(met, "ES_SM_NMI")["start"] + 1
    st = _sym(met, "US_G_STATE")["start"]

    with Machine(str(SUPERFORGE / "build" / "meteor_event.sfc")) as m:
        m.advance(30)
        for _ in range(400):                    # SEQUENCING: reach the event
            m.advance(1, pad1={"right": True})
            if _u16(m, st) != 0:
                break
        else:
            raise AssertionError("the meteor event never fired")
        if (src, dst) == ("impact", "level"):
            _run_to_transition(m, phase)        # step over the forward swap
            for _ in range(900):                # ...and through the cutscene
                m.advance(1)
                if _u8(m, phase) == 0:
                    break
        before = _colours(m, tmp_path, f"{src}_{dst}_before.png")
        _run_to_transition(m, phase)
        window = _walk_switch(m, tmp_path, f"{src}_{dst}", inidisp, cur)
    after = window[-1][0]

    # NON-VACUITY FIRST, because everything below is an absence: the swap has
    # to have happened inside the frames photographed, or "no dimmed frame,
    # no blank frame" is a statement about a window where nothing occurred.
    scenes = [c for _, _, c in window]
    assert len(set(scenes)) == 2, (
        f"{src}->{dst}: the window never changed scene (ids {scenes}) — the "
        f"assertions below would hold vacuously")

    blank, clean, dimmed = _classify(window, before, after)
    assert dimmed == [], (
        f"{src}->{dst} declares 'cut' but {len(dimmed)} frame(s) render "
        f"colours in neither steady-state picture — a brightness ramp. "
        f"Frames: {dimmed}")
    # THE OWNER-REPORTED DEFECT. A cut switch holds forced blank only while
    # its body runs, and the body runs inside the VBlank the tick starts in —
    # so no DISPLAYED scanline is blanked at all, let alone a whole frame.
    assert blank == [], (
        f"{src}->{dst} rendered {len(blank)} blank frame(s) {blank}: the "
        f"switch's forced blank reached the screen. Either the cut armed it "
        f"ahead of the frame again, or the switch body outgrew the VBlank it "
        f"starts in — test_the_cut_holds_its_forced_blank_inside_vblank "
        f"distinguishes those two.")
    assert clean, "the incoming scene never rendered"

    # The shadow, second and SHARPER than it used to be. The cut no longer
    # stages a blank in the shadow at ALL: @switch writes $80 straight to
    # $2100 and @cut_done writes $0F back, both inside one VBlank, so the
    # value the NMI commits is 15 on every frame of the window. Anything else
    # here is either a ramp (an intermediate level) or the old pre-armed blank
    # ($80) coming back. The fade control's copy of this line samples
    # identically and DOES see its ramp, which is what makes the pair
    # meaningful.
    levels = [d for _, d, _ in window]
    assert set(levels) == {15}, (
        f"INIDISP shadow is not a flat 15 across the cut window: {levels}. "
        f"$80 means the blank was armed a frame ahead again; anything between "
        f"1 and 14 means a brightness ramp.")


def test_the_two_meteor_edges_are_declared_cut(met):
    """The rail's INTENT, pinned separately from the rendering test above.

    That test reads the declared style and asserts the matching rendering, so
    it follows a deliberate style change — correct for an engine-level test,
    and exactly why the rail also needs a case that says what meteor_event
    declares. Flipping either edge back to 'fade' fails HERE, not silently."""
    assert _style(met, "level", "impact") == "cut"
    assert _style(met, "impact", "level") == "cut"


# =============================================================================
# 2. the fade is unchanged for everyone else — the non-vacuity control
# =============================================================================
def test_a_fade_edge_still_ramps(mz, tmp_path):
    """microzero's title -> race declares 'fade' and still fades.

    This is the control that makes the test above mean something: the SAME
    picture-level predicate, over a rail that did not opt in, must find the
    dimmed frames the cut refuses. If this ever goes green with an empty
    `dimmed`, the cut test is passing because the predicate cannot see a ramp,
    not because the cut has no ramp."""
    assert _style(mz, "title", "race") == "fade"
    phase = _sym(mz, "ES_SM_CTL")["start"] + 2
    cur = _sym(mz, "ES_SM_CTL")["start"]
    inidisp = _sym(mz, "ES_SM_NMI")["start"] + 1

    with Machine(str(SUPERFORGE / "build" / "microzero.sfc")) as m:
        m.advance(90)                           # the title's own boot fade-in
        before = _colours(m, tmp_path, "mz_before.png")
        m.advance(1, pad1={"start": True})      # title.asm: START -> race
        _run_to_transition(m, phase)
        window = _walk_switch(m, tmp_path, "mz_fade", inidisp, cur)
    after = window[-1][0]

    blank, clean, dimmed = _classify(window, before, after)
    assert len(dimmed) >= 10, (
        f"a 'fade' edge rendered only {len(dimmed)} dimmed frame(s) — the "
        f"brightness ramp is gone from a rail that declares it")
    # ...and the fade DOES blank, which is the other half of the pair: the cut
    # case asserts an empty `blank` list, so a predicate that could never find
    # a blank frame would pass it for the wrong reason.
    assert blank, (
        "a 'fade' edge rendered no blank frame — the forced-blank switch the "
        "ramp brackets never reached the screen, so the cut case's "
        "`blank == []` is not evidence of anything")
    levels = [d for _, d, _ in window]
    assert len(set(levels) - {0x80, 15}) >= 10, (
        f"the INIDISP shadow shows no ramp on a declared-fade edge: {levels}")


# =============================================================================
# 1b. the cut holds its blank INSIDE VBlank — the mechanism behind case 1
# =============================================================================
# Placed last in the module deliberately: it is the one case that drives the
# legacy free-running runner rather than the lockstep Machine, and the core is
# a process-global singleton — running it after every Machine-based case means
# no `with Machine(...)` block is ever waiting on a core this fixture parked.
#
# NTSC geometry, and it is the whole arithmetic: 262 scanlines of 1,364 master
# cycles each. Lines 1..224 are rendered; 225..261 are VBlank, and line 0 is
# not rendered either. So a forced blank that opens AND closes at a scanline
# >= 225 within ONE PPU frame darkens nothing a player can see.
NTSC_LINES = 262
NTSC_LINE_MC = 1364
VBLANK_FIRST = 225
# The walk has to reach both swaps, and the NMI commits INIDISP every frame, so
# the breakpoint fires about once per frame. The return swap lands near frame
# 400; the budget is that plus headroom, and it is an EMULATED-frame bound, not
# a wall-clock one.
BREAK_BUDGET = 470
# One scanline of grace. The property asserted is "no displayed line is
# blanked", which is what `close < NTSC_LINES` says; this floor makes the gate
# fire a scanline BEFORE the artefact instead of on the frame it appears.
MIN_MARGIN_LINES = 1


@pytest.fixture(scope="module")
def blank_windows(met):
    """Every forced-blank window the two cut switches hold.

    `@switch` opens with `sta a:$2100` (#$80) and `@cut_done` closes with
    `sta a:$2100` (#$0F), so a write breakpoint on the CPU-bus address $2100
    lands on both ends of the bracket — and on the NMI's own INIDISP commit
    every frame, which is how the two are told apart: the NMI's store is the
    one PC that fires hundreds of times, the switch's two fire twice each.

    Each hit carries the master clock, the PPU frame index (public) and the
    PPU scanline (`_ppu_scanline`, the same thin GetPpuState reader
    `ppu_frame_count` is, one field along).
    """
    from mesen_runner import MemoryType as MT, MesenRunner  # noqa: E402

    runner = MesenRunner()
    runner.boot_rom(str(SUPERFORGE / "build" / "meteor_event.sfc"))
    hits = []
    try:
        runner.debug_break()
        runner.set_input(0, right=True)      # walk the player into the event
        with runner.breakpoints([(MT.SnesMemory, 0x2100, "write")]):
            for _ in range(BREAK_BUDGET):
                if not runner.run_to_break(max_frames=1500):
                    break
                st = runner.snes_state_snapshot()
                hits.append({"mc": st.master_clock, "pc": st.cpu_pc,
                             "frame": runner.ppu_frame_count(),
                             "scanline": runner._ppu_scanline()})
    finally:
        runner.stop()

    assert hits, "nothing ever wrote $2100 — the ROM never committed INIDISP"
    counts = {}
    for h in hits:
        counts[h["pc"]] = counts.get(h["pc"], 0) + 1
    nmi_pc = max(counts, key=counts.get)
    rare = [h for h in hits if h["pc"] != nmi_pc]
    assert len(rare) == 4, (
        f"expected two $2100 writes per cut switch over two switches, saw "
        f"{len(rare)} (PC counts {counts}). The bracket is `sta a:$2100` in "
        f"@switch and `sta a:$2100` in @cut_done.")
    return [(rare[i], rare[i + 1]) for i in (0, 2)]


def test_the_cut_holds_its_forced_blank_inside_vblank(blank_windows):
    """THE MECHANISM, measured: the switch's forced blank never reaches a
    rendered scanline.

    Case 1 says no DISPLAYED frame is blank. This says why, and it is the
    gate that has to stay green for case 1 to keep being true for a reason
    rather than by luck: the blank opens inside VBlank, closes inside the
    SAME PPU frame's VBlank, and the margin left is reported so a future
    `enter` eating into it is visible before it becomes a black band.

    Both ends are read at the store itself, so this is not an estimate of how
    long the switch takes — it is where the beam was when the blank went on
    and where it was when the blank came off."""
    report = []
    for opened, closed in blank_windows:
        dur = closed["mc"] - opened["mc"]
        margin = (NTSC_LINES - closed["scanline"]) * NTSC_LINE_MC
        report.append(
            f"open scan {opened['scanline']} -> close scan "
            f"{closed['scanline']}: {dur} mc ({dur / NTSC_LINE_MC:.2f} lines), "
            f"margin {margin} mc ({margin / NTSC_LINE_MC:.2f} lines)")
    print("\n  cut blank windows: " + "\n                     ".join(report))

    for opened, closed in blank_windows:
        assert opened["scanline"] >= VBLANK_FIRST, (
            f"the switch asserted forced blank on RENDERED scanline "
            f"{opened['scanline']} — it is supposed to open inside the VBlank "
            f"`sm_frame_sync` released the tick into ({report})")
        assert closed["frame"] == opened["frame"], (
            f"the forced-blank window crossed a PPU frame boundary (opened in "
            f"frame {opened['frame']} at scanline {opened['scanline']}, closed "
            f"in frame {closed['frame']} at scanline {closed['scanline']}): "
            f"the switch body outgrew the VBlank it starts in, so the top of "
            f"a displayed frame is blanked ({report})")
        assert closed["scanline"] >= VBLANK_FIRST, (
            f"the blank was lifted on scanline {closed['scanline']} of the "
            f"same frame it opened in — that is not reachable without the "
            f"counter wrapping, so read it as a geometry change ({report})")
        margin_lines = NTSC_LINES - closed["scanline"]
        assert margin_lines >= MIN_MARGIN_LINES, (
            f"the switch closes its blank on scanline {closed['scanline']} "
            f"with {margin_lines} scanline(s) of VBlank left. It still fits, "
            f"but the next thing added to a cut `enter` will not: move it to "
            f"boot or put the edge behind a fade ({report})")
