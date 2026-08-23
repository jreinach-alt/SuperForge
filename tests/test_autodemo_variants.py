"""The two controller-free PILOT ROMs, asserted against what they draw.

`build/shd_autodemo.sfc` and `build/shp_autodemo.sfc` exist so the
owner can watch `split_h_demo` and `split_h_persp_demo` run with no controller
attached. That makes the claim under test a claim about MOTION WITHOUT INPUT,
and it has two halves that must both be asserted or neither means anything:

  the POSITIVE   the pilot ROM's picture advances on its own, at the RATE the
                 the pilot script sets — not merely "the frames differ".
  the CONTROL    the BASE rail, driven identically (i.e. not at all), does NOT
                 advance. Without it "the picture changed" is satisfiable by a
                 fade still ramping, a counter bleeding into a tilemap, or any
                 other frame-varying accident.

THE BASE RAILS ARE THE CONTROLS, and that is the one structural difference from
`test_split_v_demo`'s shape. There the shipping ROM is the subject and
`svd_nowin` is the control built to make an assertion fail; here the -D ROM is
the subject and the SHIPPING ROM is the thing that must stay still, because
what these builds add is exactly autonomy. Same discipline, mirrored.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner import, no
wall-clock surface. Every capture lands on an ABSOLUTE frame — either
`advance(N)` from reset, or a run of single `advance(1)` steps from one, which
is the same determinism.

EVERY CLAIM HERE IS A PICTURE CLAIM, and that is forced rather than chosen.
"the demo runs by itself" is a statement about successive rendered frames; a
state word that says the heading advanced does not prove the floor redrew, and
this module reads no map, no WRAM and no VRAM for exactly that reason. It is
also why the module needs no `conftest.MAPS` / `_SUBDIR_MAP` / freshness-guard
entry: it names no symbol map at all.

WHAT THE RATES ARE AND WHERE THEY COME FROM — the pilot scripts themselves:

  shd_autodemo   ONE ROT_SPD heading step every 4 frames, a full turn in 256.
                 `templates/split_h_demo/main.asm:398-404` advances `G_ANGLE`
                 by 1 of 256 angle units per frame under `-DAUTODEMO` (NOT
                 `ROT_SPD`, which is the 2-unit HELD-shoulder step at :186);
                 `pose_rom` here is indexed by 64 headings, so one step of this
                 rail's base is four of those units.
  shp_autodemo   heading +1 EVERY frame and zoom = heading >> 3, so the top
                 band moves every frame, the bottom every 8, and the whole
                 picture repeats every 64. `templates/split_h_persp_demo/
                 main.asm:421-429` is "auto-rotate (4 units/frame) -> full turn
                 every 64 frames" and :445-453 is "zoom-loop (advance every 8
                 frames)" — both off that template's FRAME_COUNTER, in its
                 DEFAULT build, which is why it ships no `-DAUTODEMO` of its
                 own and this one restores rather than adds.

The two periods (256 and 64) are the sharpest form those rates take: a ROM that
stepped at any other rate, or whose two axes were not locked in that 8:1 ratio,
could still satisfy "the picture moved" and cannot satisfy these.
"""
import hashlib
import re
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine  # noqa: E402

BUILD = SUPERFORGE / "build"

SHD_PILOT = BUILD / "shd_autodemo.sfc"
SHD_BASE = BUILD / "split_h_demo.sfc"
SHP_PILOT = BUILD / "shp_autodemo.sfc"
SHP_BASE = BUILD / "split_h_persp_demo.sfc"

BOOT = 90                       # the two rails' own absolute boot frame, past
                                # the fade — test_split_h_demo.py:128 and
                                # test_split_h_persp_demo.py:154

# --- the frame geometry, DERIVED per image rather than pinned ---------------
# Mesen captures the 239-line overscan frame, so the picture sits at some
# offset inside it. Both rails' modules agree the offset is 7, and both DERIVE
# it rather than trusting that: test_split_h_demo.py's `_anchor` anchors from
# the BOTTOM, because the last non-black row IS scanline 223 on a rail whose
# Mode-7 floor reaches the frame's last line — which is true of both rails
# here, in every state either pilot script visits. The top-side "content spans
# 224 rows" anchor would be wrong on split_h_demo, whose panel band is mostly
# backdrop.
#
# It matters more here than in either source module: every claim below is a
# statement about ONE BAND, so an anchor off by a few rows leaks the other
# band's pixels into the digest and "camera B moves every 8 frames" quietly
# becomes "camera B, plus a slice of camera A, moves every frame".
PIC_LINES = 224
FRAME_W = 256

# --- the two seams, read from the rails rather than re-declared -------------
# A re-declared 40 keeps asserting the old seam after the game moves, silently,
# because the number still looks right (test_split_h_demo.py's `_inc_const`
# reasoning). shd's seam is a decimal constant in its .inc; shp's is not — it
# is `SEAM = 112` in its own test module and PICTURE_LINES // 2 by
# construction, so it is derived here the same way that module derives it.
def _shd_inc_const(name):
    src = (SUPERFORGE / "game" / "split_h_demo" / "split_h_demo.inc").read_text()
    m = re.search(rf"^\s*{re.escape(name)}\s*=\s*(-?\d+)\b", src, re.M)
    assert m, f"split_h_demo.inc has no decimal constant {name!r}"
    return int(m.group(1))


SHD_SEAM = _shd_inc_const("HUD_LINES")          # 40 — panel above, floor below
SHP_SEAM = PIC_LINES // 2                       # 112 — camera A above, B below

# The live readout's rendered window on split_h_demo, MEASURED on that ROM and
# restated from test_split_h_demo.py:137-138 (the only part of the panel
# band allowed to change). PICTURE rows and absolute columns — that module
# indexes them as `img.getpixel((x, top + y))` at its :666, so the rows are
# relative to the derived anchor and the columns are not. Used here to assert
# the SAME containment from the other side: under the pilot script the readout
# must move AND the rest of the panel must not.
SHD_HUD_LINES = range(14, 24)
SHD_HUD_COLS = range(184, 208)

# The reference's rates, as periods in frames (see the module docstring).
SHD_STEP_FRAMES = 4             # one heading step every N frames
SHD_TURN_FRAMES = 256           # ...therefore a full 64-heading turn in this
SHP_ZOOM_FRAMES = 8             # camera B advances one zoom every N frames
SHP_CYCLE_FRAMES = 64           # ...and the whole picture repeats in this


# =============================================================================
# capture — one machine, absolute frames, no input anywhere
# =============================================================================
@pytest.fixture(scope="module")
def run():
    """Hand back a capture FUNCTION, not a shared driving handle.

    `Machine` owns the process-global core as a singleton, so a module-scope
    machine and a fresh one inside a case cannot coexist (test_split_h_demo's
    `boot` fixture reasoning). The teardown closes whichever machine currently
    owns the core.
    """
    for rom in (SHD_PILOT, SHD_BASE, SHP_PILOT, SHP_BASE):
        if not rom.exists():
            pytest.fail(
                f"{rom} missing — run `make split_h_demo shd-autodemo "
                f"split_h_persp_demo shp-autodemo`")

    def _run(rom, frames, tmp_path, extra_steps=0):
        """Digest the picture at absolute frame `frames`, then at each of the
        next `extra_steps` frames. NO pad is ever latched — that is the whole
        subject, so it is not a default that could be overridden by accident.

        THE CAPTURE ITSELF COSTS ONE FRAME, and consecutive samples therefore
        come from calling `screenshot()` again with NO advance between them.
        `Machine.take_screenshot` (vendor/machine.py:602) writes the frame that
        was current at call time and then `advance(1)`s the core, so a loop
        that advanced as well would step TWO frames per sample. That is not a
        cosmetic error here: it silently HALVES every observed rate, and the
        two rate cases below duly reported camera B advancing "every 4 frames"
        and the shd heading "every 2" — both self-consistent, both wrong, and
        both matching what a real ROM stepping at twice the rate would produce.
        Caught by disagreeing with the same measurement taken from fresh boots.
        """
        out = []
        m = Machine(str(rom)).advance(frames)
        try:
            for i in range(extra_steps + 1):
                path = tmp_path / f"{rom.stem}_{frames + i}.png"
                out.append(_digests(Image.open(m.screenshot(str(path)))
                                    .convert("RGB")))
        finally:
            m.close()
        return out

    yield _run
    Machine.close_current()


# The captures are digested through the RAW RGB buffer rather than getpixel(),
# and that is a runtime decision rather than a style one: this module takes ~47
# captures and each needs six digests over the frame, which at Python-level
# per-pixel tuple indexing is ~25 M operations and pushed the module past ten
# minutes on its own. `Image.tobytes()` is row-major RGB, so a picture row is a
# slice and a band is a join of slices — the same bytes, three orders of
# magnitude cheaper. Nothing about the ASSERTIONS changes.
_ROW = FRAME_W * 3


def _rows(img):
    """The frame as a list of row byte-strings (row-major RGB)."""
    raw = img.tobytes()
    return [raw[y * _ROW:(y + 1) * _ROW] for y in range(img.size[1])]


def _anchor(rows):
    """The PNG row that IS picture scanline 0, derived from the BOTTOM.

    test_split_h_demo.py:233's rule, and its reasoning carries to both rails:
    the last non-black row is scanline 223 because a Mode-7 floor reaches the
    frame's last line, while rows INSIDE the picture are legitimately all
    black on a rail whose top band is mostly backdrop.
    """
    lit = [y for y, r in enumerate(rows) if any(r)]
    assert lit, "the frame is entirely black — nothing rendered"
    top = lit[-1] - (PIC_LINES - 1)
    assert 0 <= top and top + PIC_LINES <= len(rows), (
        f"the derived anchor {top} does not fit a {PIC_LINES}-row picture in "
        f"a {len(rows)}-row frame")
    return top


def _band(rows, top, r0, r1):
    """One horizontal PICTURE-row band's pixels, as bytes."""
    return b"".join(rows[top + r0:top + r1])


_HUD_X0 = SHD_HUD_COLS.start * 3
_HUD_X1 = SHD_HUD_COLS.stop * 3


def _digests(img):
    """The picture, split the ways every case here needs.

    `whole` is the active picture; `shd_*` and `shp_*` are the two rails'
    bands. Both rails' bands are digested for every capture because a digest is
    cheap and a second boot is not — no case reads a band belonging to the
    other rail.
    """
    rows = _rows(img)
    top = _anchor(rows)
    hud = b"".join(rows[top + y][_HUD_X0:_HUD_X1] for y in SHD_HUD_LINES)
    panel_rest = b"".join(
        (rows[top + y][:_HUD_X0] + rows[top + y][_HUD_X1:])
        if y in SHD_HUD_LINES else rows[top + y]
        for y in range(SHD_SEAM))
    return {
        "whole": _md5(_band(rows, top, 0, PIC_LINES)),
        "shd_floor": _md5(_band(rows, top, SHD_SEAM, PIC_LINES)),
        "shd_hud": _md5(hud),
        "shd_panel_rest": _md5(panel_rest),
        "shp_top": _md5(_band(rows, top, 0, SHP_SEAM)),
        "shp_bot": _md5(_band(rows, top, SHP_SEAM, PIC_LINES)),
    }


def _md5(b):
    return hashlib.md5(b).hexdigest()


def _change_frames(caps, key, first):
    """The absolute frames at which `key` differs from the frame before it."""
    return [first + i for i in range(1, len(caps))
            if caps[i][key] != caps[i - 1][key]]


def _gaps(changes):
    """Frame counts between successive changes in a fully-observed window."""
    return [b - a for a, b in zip(changes, changes[1:])]


# =============================================================================
# split_h_demo — this `-DAUTODEMO`
# =============================================================================
def test_the_shd_pilot_advances_the_floor_and_the_readout_with_no_input(
        run, tmp_path):
    """The headline: one boot, no pad, and BOTH bands move.

    This rail's pilot animates ONE axis where its sibling animates two,
    because its instrument is a READOUT of the heading rather than an
    independent fill bar. So the claim that has to hold is that
    the single heading step reaches BOTH bands — the Mode-7 floor's matrix
    below the seam and the 4-cell readout above it — from one script.

    The negative arm is what locates the readout claim: the rest of the panel
    band must be untouched. Without it, "the panel changed" would also be
    satisfied by a panel that was being redrawn wholesale every frame, which
    is the opposite of what the rail claims about its band.
    """
    a, b = run(SHD_PILOT, BOOT, tmp_path), run(SHD_PILOT, BOOT + 64, tmp_path)
    a, b = a[0], b[0]
    assert a["shd_floor"] != b["shd_floor"], (
        "the Mode-7 floor band is identical 64 frames apart — the pilot ROM's "
        "camera is not spinning")
    assert a["shd_hud"] != b["shd_hud"], (
        "the panel readout is identical 64 frames apart — the heading reached "
        "the floor but not the instrument")
    assert a["shd_panel_rest"] == b["shd_panel_rest"], (
        "the panel band changed OUTSIDE the readout window — the pilot script "
        "is redrawing more of the band than the readout")


def test_the_shd_base_rail_is_still_under_the_same_no_input_drive(
        run, tmp_path):
    """The NON-VACUITY CONTROL, and the reason the case above means anything.

    Same source, same seam, same absolute frames, same absent input — with the
    autonomous step compiled out. Every band must be byte-identical. If the
    base rail moved here too, the positive case would be measuring a fade, a
    counter or a power-on transient rather than the pilot script.
    """
    a, b = run(SHD_BASE, BOOT, tmp_path), run(SHD_BASE, BOOT + 64, tmp_path)
    a, b = a[0], b[0]
    assert a["whole"] == b["whole"], (
        "the SHIPPING split_h_demo moved on its own across 64 frames with no "
        "input — the pilot ROM's motion cannot be attributed to its script")


def test_the_shd_pilot_steps_once_every_four_frames(run, tmp_path):
    """The RATE, which is the part "the picture moved" cannot reach.

    The reference's autodemo advances one angle unit per frame and this rail's
    heading base is four of those units, so the picture must hold STILL for
    runs of exactly four frames and change on the fourth. A ROM stepping every
    frame, or every eight, moves just as visibly and fails here.

    The window is scanned rather than phase-anchored: nothing asserts WHICH
    frames are the boundaries, only that the gaps between them are all
    SHD_STEP_FRAMES. A test that hardcoded the phase would have to be edited
    every time the boot frame moved, and would then be asserting the edit.
    """
    span = SHD_STEP_FRAMES * 3
    caps = run(SHD_PILOT, BOOT, tmp_path, extra_steps=span)
    changes = _change_frames(caps, "whole", BOOT)
    assert len(changes) >= 3, (
        f"only {len(changes)} change(s) in {span + 1} frames — expected one "
        f"every {SHD_STEP_FRAMES}: changes at {changes}")
    gaps = _gaps(changes)
    assert set(gaps) == {SHD_STEP_FRAMES}, (
        f"the heading does not step every {SHD_STEP_FRAMES} frames: changes "
        f"at {changes}, gaps {gaps}")


def test_the_shd_pilot_turn_closes_after_exactly_256_frames(run, tmp_path):
    """The rate's sharpest form: 64 headings x 4 frames = one full turn.

    A picture that returns to itself after exactly SHD_TURN_FRAMES pins the
    step size AND the heading count AND the wrap together, from the outside.
    The paired inequality at the half-turn is what stops it passing on a ROM
    that never moved at all.
    """
    start = run(SHD_PILOT, BOOT, tmp_path)[0]["whole"]
    half = run(SHD_PILOT, BOOT + SHD_TURN_FRAMES // 2, tmp_path)[0]["whole"]
    full = run(SHD_PILOT, BOOT + SHD_TURN_FRAMES, tmp_path)[0]["whole"]
    assert half != start, (
        f"the picture at the half-turn is the boot picture — nothing is "
        f"turning over {SHD_TURN_FRAMES // 2} frames")
    assert full == start, (
        f"the picture has not closed its turn after {SHD_TURN_FRAMES} frames "
        f"— the heading step is not one per {SHD_STEP_FRAMES} frames over 64 "
        f"headings")


# =============================================================================
# split_h_persp_demo — both cameras back on the frame counter
# =============================================================================
def test_the_shp_pilot_runs_both_cameras_with_no_input(run, tmp_path):
    """The headline: two bands, two cameras, both moving, no pad.

    The shipping build puts both axes on pad 1; this one hands them back to
    the frame counter. So both bands must move — a build that restored only
    camera A would leave the bottom band frozen and still look like it was
    "running by itself".
    """
    a = run(SHP_PILOT, BOOT, tmp_path)[0]
    b = run(SHP_PILOT, BOOT + SHP_CYCLE_FRAMES // 2, tmp_path)[0]
    assert a["shp_top"] != b["shp_top"], (
        "camera A's band is identical across half a cycle — the heading is "
        "not rotating")
    assert a["shp_bot"] != b["shp_bot"], (
        "camera B's band is identical across half a cycle — the zoom is not "
        "looping")


def test_the_shp_base_rail_is_still_under_the_same_no_input_drive(
        run, tmp_path):
    """The NON-VACUITY CONTROL for the pair above."""
    a = run(SHP_BASE, BOOT, tmp_path)[0]
    b = run(SHP_BASE, BOOT + SHP_CYCLE_FRAMES // 2, tmp_path)[0]
    assert a["whole"] == b["whole"], (
        "the SHIPPING split_h_persp_demo moved on its own with no input — the "
        "pilot ROM's motion cannot be attributed to its script")


def test_the_shp_pilot_moves_camera_a_every_frame_and_camera_b_every_eight(
        run, tmp_path):
    """The two rates, and the 8:1 lock between them.

    The reference drives both cameras off ONE counter at rates that differ by
    exactly eight, and this build reproduces that by making the zoom a function
    of the heading (`zoom = head >> 3`) rather than a second accumulator. That
    coupling is invisible to any "the picture moved" assertion and is the whole
    of what this case reads: the TOP band must differ across every single
    frame boundary in the window, and the BOTTOM band across exactly the
    boundaries spaced SHP_ZOOM_FRAMES apart.

    Both arms are needed. Top-only would pass on a ROM whose zoom never moved;
    bottom-only would pass on one whose heading only moved every eighth frame.
    """
    span = SHP_ZOOM_FRAMES * 2
    caps = run(SHP_PILOT, BOOT, tmp_path, extra_steps=span)

    top_static = [BOOT + i for i in range(1, len(caps))
                  if caps[i]["shp_top"] == caps[i - 1]["shp_top"]]
    assert top_static == [], (
        f"camera A's band did not change at frame(s) {top_static} — the "
        f"heading is not stepping once per frame")

    bot_changes = _change_frames(caps, "shp_bot", BOOT)
    assert len(bot_changes) >= 2, (
        f"only {len(bot_changes)} zoom change(s) in {span + 1} frames — "
        f"expected one every {SHP_ZOOM_FRAMES}: {bot_changes}")
    gaps = _gaps(bot_changes)
    assert set(gaps) == {SHP_ZOOM_FRAMES}, (
        f"camera B does not advance every {SHP_ZOOM_FRAMES} frames: changes "
        f"at {bot_changes}, gaps {gaps}")


def test_the_shp_pilot_cycle_closes_after_exactly_64_frames(run, tmp_path):
    """Both axes wrap together, which is what makes it a loop at all.

    64 headings at one per frame and 8 zooms at one per eight frames land on
    the same period, so the entire picture — both bands — must return to
    itself after SHP_CYCLE_FRAMES. That is a single assertion covering the
    step size, both set sizes and both wraps.
    """
    start = run(SHP_PILOT, BOOT, tmp_path)[0]
    full = run(SHP_PILOT, BOOT + SHP_CYCLE_FRAMES, tmp_path)[0]
    assert full["shp_top"] == start["shp_top"], (
        f"camera A's band has not closed its turn after {SHP_CYCLE_FRAMES} "
        f"frames")
    assert full["shp_bot"] == start["shp_bot"], (
        f"camera B's band has not closed its loop after {SHP_CYCLE_FRAMES} "
        f"frames")


# =============================================================================
# the pair, against each other
# =============================================================================
def test_each_pilot_rom_differs_from_the_rail_it_was_built_from(run, tmp_path):
    """A variant that silently built the base source would pass everything else.

    Every case above reads the pilot ROM against ITSELF at another frame, and
    the control cases read the base against itself. Neither notices if the two
    binaries are the same file — which is exactly what a dropped `-D`, a
    mistyped define name or a build script writing over the wrong output would
    produce. The `.ifdef` is a compile-time switch with no runtime witness, so
    this is the case that reads it.
    """
    assert SHD_PILOT.read_bytes() != SHD_BASE.read_bytes(), (
        "shd_autodemo.sfc is byte-identical to split_h_demo.sfc — the "
        "SHD_AUTODEMO define did not reach the assembler")
    assert SHP_PILOT.read_bytes() != SHP_BASE.read_bytes(), (
        "shp_autodemo.sfc is byte-identical to split_h_persp_demo.sfc — the "
        "SHP_AUTODEMO define did not reach the assembler")

    # And the same thing on the SCREEN, at a frame where the pilot's script has
    # certainly diverged from the base's frozen state — a half turn for shd, a
    # half cycle for shp. Compared at the SAME absolute frame, so the only
    # difference between the two captures is the define.
    late = run(SHD_PILOT, BOOT + SHD_TURN_FRAMES // 2, tmp_path)[0]["whole"]
    late_base = run(SHD_BASE, BOOT + SHD_TURN_FRAMES // 2, tmp_path)[0]["whole"]
    assert late != late_base, (
        f"at frame {BOOT + SHD_TURN_FRAMES // 2} the pilot and the shipping "
        f"split_h_demo render the same picture — the pilot's camera never "
        f"left the base's heading")

    shp = run(SHP_PILOT, BOOT + SHP_CYCLE_FRAMES // 2, tmp_path)[0]["shp_top"]
    shp_base = run(SHP_BASE, BOOT + SHP_CYCLE_FRAMES // 2,
                   tmp_path)[0]["shp_top"]
    assert shp != shp_base, (
        f"at frame {BOOT + SHP_CYCLE_FRAMES // 2} the pilot and the shipping "
        f"split_h_persp_demo render the same top band — camera A is not "
        f"rotating in the pilot build")
