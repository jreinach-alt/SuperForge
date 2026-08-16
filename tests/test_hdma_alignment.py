"""The HDMA byte-to-scanline alignment model, re-derived every run.

THE claim: a table unit whose cumulative line index is K is visible at
exactly scanline K. HdmaInit runs at scanline 0 clock 12 and the unit
transferred on the pre-render line covers the first visible line, so no
table needs to close the frame and there is no carried-over line 0.

That one sentence is load-bearing across the tree: gen_gradient's table
emission, split_band.asm's band tables and its corrected note, and ~180
rendered assertions all rest on it. It was established with
`vendor/probes/probe_vb2reg`'s five-way `tab_sel` switch and then left
reproducible-on-demand — the probe's own tests only ever exercise
`tab_sel = 0`, so nothing re-derived it in CI and a change invalidating it
would have failed nowhere. This module is that guard.

How the measurement works: for `tab_sel` 1 and 2 the probe streams a ramp
whose byte k is `$80 | (k & 31)` — a COLDATA B-plane write. The BLUE
INTENSITY of a rendered scanline therefore names WHICH TABLE BYTE that
scanline displays, so reading it back is a direct read of the map.

Deliberately its OWN module. `test_vb2reg_probe` holds a module-scoped
MesenRunner open across its tests; opening a second runner alongside it
makes both read each other's frames, which cost an hour here — the matrix
appeared broken while the probe was fine. One live emulator at a time.
"""
import json
import sys
from contextlib import contextmanager
from importlib import util as _importlib_util
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

WR = MemoryType.SnesWorkRam

RAMP_SELECTORS = {1: "indirect repeat (gen_gradient's exact shape)",
                  2: "direct repeat"}


def _probe_module():
    """The probe's own test module, reused for its `build()` helper."""
    spec = _importlib_util.spec_from_file_location(
        "vb2reg_build", SUPERFORGE / "tests" / "test_vb2reg_probe.py")
    mod = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe_rom(tmp_path_factory):
    """The probe ROM + its symbol map, built once for the matrix."""
    out = tmp_path_factory.mktemp("vb2align")
    rom = _probe_module().build(out)
    jmap = json.loads((out / "map" / "symbol_map.json").read_text())
    return rom, {p["sym"]: p
                 for p in jmap["scenes"]["probe"]["placements"]}


@contextmanager
def _rendered_with_table(rom, syms, sel, shot):
    """Boot the probe FRESH, select a table structure, yield the rendered
    frame and its located scanline-0 row.

    A fresh boot per structure, and the runner is stopped before the next:
    these are measurements of a rendering model, and any shared emulator
    state lets one structure's frame be read as another's."""
    from PIL import Image
    runner = MesenRunner()
    runner.boot_rom(str(rom))
    runner.debug_break()
    runner.frame_step(3)
    addr = syms["US_TAB_SEL"]["start"]
    runner.write_byte(WR, addr, sel)
    runner.frame_step(4)
    got = runner.read_bytes(WR, addr, 1)[0]
    assert got == sel, f"tab_sel write did not land: wrote {sel}, read {got}"
    try:
        # Wait for a STABLE frame before measuring. The first boot in a
        # process settles more slowly than later ones, so whichever test ran
        # first read a pre-switch frame and reported the model broken while
        # the same selector passed when it ran second — an order-dependent
        # result, which is worthless as a measurement.
        #
        # Stability, not expected content: two captures several frames apart
        # must be identical. That cannot launder a wrong answer into a right
        # one, because it never compares against what the test asserts.
        prev = None
        for _ in range(8):
            runner.take_screenshot(str(shot), settle_frames=2)
            cur = Image.open(shot).convert("RGB").tobytes()
            if prev == cur:
                break
            prev = cur
            runner.frame_step(4)
        else:
            raise AssertionError(
                f"tab_sel {sel}: the frame never stabilised — refusing to "
                f"measure an alignment model from a settling render")
        img = Image.open(shot).convert("RGB")
        yield img, D.content_top(img)
    finally:
        runner.debug_resume()
        runner.stop()


def _blue(img, top, scanline):
    """The ramp's 5-bit blue intensity as rendered on one scanline."""
    return img.getpixel((128, top + scanline))[2] >> 3


@pytest.mark.parametrize("sel", sorted(RAMP_SELECTORS))
def test_table_unit_K_is_visible_at_scanline_K(probe_rom, tmp_path, sel):
    """The model itself, for both repeat structures, on all 224 scanlines.

    Table byte k carries intensity (k & 31); if unit K is visible at
    scanline K then scanline S must render (S & 31). A one-line slip shows
    up on 31 of every 32 scanlines."""
    rom, syms = probe_rom
    with _rendered_with_table(rom, syms, sel,
                              tmp_path / f"ramp{sel}.png") as (img, top):
        bad = [(s, _blue(img, top, s)) for s in range(224)
               if _blue(img, top, s) != (s & 31)]
    assert not bad, (
        f"tab_sel {sel} ({RAMP_SELECTORS[sel]}): scanline S does not display "
        f"table byte S. First mismatches (scanline, intensity): {bad[:6]} — "
        f"the alignment model the whole phase rests on has changed.")


def test_the_matrix_can_fail(probe_rom, tmp_path):
    """The guard above must be able to see a different structure, or it
    guards nothing. tab_sel 0 is a two-band table, not the ramp, so the
    per-scanline sequence must NOT match (S & 31)."""
    rom, syms = probe_rom
    with _rendered_with_table(rom, syms, 0,
                              tmp_path / "notramp.png") as (img, top):
        matches = sum(1 for s in range(224) if _blue(img, top, s) == (s & 31))
    assert matches < 224, \
        "the two-band table renders as the ramp — the probe is not switching"


@pytest.mark.parametrize("sel,relatch_visible", [(3, True), (4, False)])
def test_close_experiment_lands_where_the_model_predicts(probe_rom, tmp_path,
                                                         sel, relatch_visible):
    """split_band's failed "close the frame" experiment, pinned.

    Both tables end with a one-line entry re-latching the sky colour, after
    pre-final counts summing to 223 (tab_sel 3) and 224 (tab_sel 4). Under
    "unit K visible at scanline K" the first lands ON visible scanline 223
    and the second falls past the frame. That prediction is what resolved
    a later review's "internal inconsistency", and it is what makes the corrected
    note in split_band.asm true rather than merely plausible."""
    rom, syms = probe_rom
    with _rendered_with_table(rom, syms, sel,
                              tmp_path / f"close{sel}.png") as (img, top):
        last = img.getpixel((128, top + 223))
        mid = img.getpixel((128, top + 200))
    is_sky = last[2] > 200 and last[0] < 50
    assert is_sky == relatch_visible, (
        f"tab_sel {sel}: scanline 223 renders {last}; expected the re-latch "
        f"{'visible there' if relatch_visible else 'past the frame'}")
    assert mid[0] > 200 and mid[2] < 50, \
        f"tab_sel {sel}: the band above the close entry changed: {mid}"
