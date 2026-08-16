"""scene_mgr's CUT transition style, and the declaration that selects it.

A `[[edge]]` in game.toml declares `style = "fade" | "cut" | "mosaic"`; the
allocator emits `ES_E_<SRC>_TO_<DST>_CUT` from it and `SM_SWITCH` picks the
entry point from that symbol at assembly time. So there are two claims to
prove, and they are different claims:

  1. THE CUT RENDERS AS A CUT. Across a cut switch the picture goes from the
     outgoing scene, to blank, to the incoming scene — and NO frame in between
     shows a dimmed version of either. That is the user-visible invariant, so
     it is asserted on SCREENSHOT PIXELS: every frame in the switch window is
     either black or drawn from a palette the steady-state frames actually
     use. A fade at brightness 7/15 renders colours that appear in NEITHER
     steady frame, which is exactly what this refuses. (The INIDISP shadow
     trace is read too, but as a SECOND, sharper statement of the same thing —
     never as the primary evidence. The shadow is engine state; the pixels are
     what a player sees.)

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

Lockstep Machine throughout: a pure function of (rom md5, power-on seed, input
script), every read from a parked exact frame, no wall clock anywhere. Note
that `Machine.screenshot` itself costs one emulated frame, so photographing a
window IS the frame-by-frame walk of it — the loops below rely on that rather
than interleaving advances.
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


def _walk_switch(m, tmp_path, tag, inidisp_addr, n=WINDOW):
    """Photograph n consecutive frames from a parked start, recording per
    frame the distinct colours ON SCREEN and the INIDISP shadow the NMI
    commits. Returns [(colours, inidisp)]."""
    return [(_colours(m, tmp_path, f"{tag}_{k:02d}.png"), _u8(m, inidisp_addr))
            for k in range(n)]


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
    blank = [k for k, (c, _) in enumerate(window) if c == {BLACK}]
    clean = [k for k, (c, _) in enumerate(window)
             if c != {BLACK} and c <= steady]
    dimmed = [k for k, (c, _) in enumerate(window)
              if c != {BLACK} and not c <= steady]
    return blank, clean, dimmed


# =============================================================================
# 1. the cut renders as a cut — on the picture
# =============================================================================
@pytest.mark.parametrize("edge", [("level", "impact"), ("impact", "level")])
def test_a_cut_edge_renders_no_intermediate_brightness(met, tmp_path, edge):
    """THE HEADLINE. Across each of meteor_event's two declared-cut swaps, no
    rendered frame shows a dimmed picture: the window holds the outgoing
    frame, blank frames, and the incoming frame, and nothing else.

    The assertion is a colour-SET containment on screenshot pixels, which is
    what makes it able to see a fade at all. A luminance threshold would let
    brightness 14/15 through; a colour set cannot, because the PPU's master
    brightness rescales every channel, so a dimmed green is simply not the
    authored green (Mesen expands BGR555 as (v << 3) | (v >> 2), and 14/15 of
    an authored value does not land back on it)."""
    src, dst = edge
    assert _style(met, src, dst) == "cut", (
        f"this case exists to test a CUT edge; {src}->{dst} declares "
        f"{_style(met, src, dst)!r}")
    phase = _sym(met, "ES_SM_CTL")["start"] + 2
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
        window = _walk_switch(m, tmp_path, f"{src}_{dst}", inidisp)
    after = window[-1][0]

    blank, clean, dimmed = _classify(window, before, after)
    assert dimmed == [], (
        f"{src}->{dst} declares 'cut' but {len(dimmed)} frame(s) render "
        f"colours in neither steady-state picture — a brightness ramp. "
        f"Frames: {dimmed}")
    # ...and it really did blank: a "cut" that never blanked would pass the
    # line above vacuously, since every frame would then be a steady frame.
    assert blank, ("no frame blanked across the switch — the forced blank the "
                   "exit/enter run under never reached the screen")
    # The blank window is as long as the SWITCH needs and no longer. The
    # forward swap reloads 32 KB of Mode-7 plane under it; measured, that is
    # one frame. Bound it loosely enough that a slower enter is not a red, and
    # tightly enough that the 15-frame ramp this change removed cannot return.
    assert len(blank) <= 4, (
        f"{len(blank)} blank frames — a cut blanks for as long as the switch "
        f"needs, not on a fixed schedule (frames {blank})")
    assert clean, "the incoming scene never rendered"

    # The shadow, second and ONE-SIDED — say so, because a green here does not
    # witness the blank. `Machine.screenshot`
    # costs its own frame, and `sm_request_cut` writes $80 in the request's
    # phase-0 tick while `@cut_done` re-seats it one frame later in the
    # phase-4 tick (the shadow holds $80 for exactly one frame
    # a review corrected this comment's original "same sm_tick"), so a
    # per-frame read taken
    # after a screenshot's advance reads 15 on every frame of a cut window,
    # including the blank one. What this still catches is any INTERMEDIATE
    # level, which is the ramp — and the blank itself is proven above, on the
    # pixels. The fade control's copy of this line samples identically and DOES
    # see its ramp, which is what makes the pair meaningful.
    levels = [d for _, d in window]
    assert set(levels) <= {0x80, 15}, (
        f"INIDISP shadow passed through intermediate brightness: {levels}")


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
    inidisp = _sym(mz, "ES_SM_NMI")["start"] + 1

    with Machine(str(SUPERFORGE / "build" / "microzero.sfc")) as m:
        m.advance(90)                           # the title's own boot fade-in
        before = _colours(m, tmp_path, "mz_before.png")
        m.advance(1, pad1={"start": True})      # title.asm: START -> race
        _run_to_transition(m, phase)
        window = _walk_switch(m, tmp_path, "mz_fade", inidisp)
    after = window[-1][0]

    blank, clean, dimmed = _classify(window, before, after)
    assert len(dimmed) >= 10, (
        f"a 'fade' edge rendered only {len(dimmed)} dimmed frame(s) — the "
        f"brightness ramp is gone from a rail that declares it")
    levels = [d for _, d in window]
    assert len(set(levels) - {0x80, 15}) >= 10, (
        f"the INIDISP shadow shows no ramp on a declared-fade edge: {levels}")
