"""microzero — rotation/turning: the previously-untested half of the
perspective + streaming composition. Steering retargets the pose LUTs at
runtime (desired -> applied committed by the NMI hook in VBlank, spec §2),
movement follows the heading through the generated LUT, and the tests pin:
the steer rate and wrap, pose-distinguishing RENDERED structure at rotated
headings (plus the heading-independent invariants: HUD, seam, gradient),
LUT-exact positions driving at off-axis headings forward AND reverse with
the full-window VRAM-vs-world invariant after every leg, a two-revolution
pirouette WHILE driving (a pose retarget every single frame) held in exact
lockstep, and a clean uninit detector over the whole turning history.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

WR = MemoryType.SnesWorkRam


@pytest.fixture(scope="module")
def booted():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((SUPERFORGE / "build" / "mz" / "symbol_map.json").read_text())
    syms = {p["sym"]: p for p in
            jmap["scenes"]["race"]["placements"] + jmap["globals"]}
    world = (SUPERFORGE / "build" / "assets" / "world_map.bin").read_bytes()
    lut = D.load_tool("gen_move_lut")
    runner = MesenRunner()
    # An EXACT absolute boot frame, not `>= 120`. The race is a moving
    # picture, and a free-run budget lands anywhere in a ~100-frame
    # spread under load (measured: 6 reps of `run_seconds=4.0` on the
    # autodemo landed on 6 different frames, 218..337, and produced 5
    # different PNGs; `boot_to_frame` produced 1 and 1). docs/45 §5.
    runner.boot_to_frame(str(SUPERFORGE / "build" / "microzero.sfc"), 140,
                         uninit_detection=True)
    D.enter_race(runner, syms)
    runner.debug_break()
    runner.frame_step(2)
    yield runner, syms, world, lut
    runner.debug_resume()
    runner.stop()


def test_steer_rate_and_wrap(booted):
    """One pose step per frame (the declared max turn), wrapping at
    64, and the NMI hook keeps applied == desired within a frame."""
    runner, syms, world, lut = booted
    assert D.heading(runner, syms) == 0
    D.drive(runner, 70, left=True)               # 70 steps: wraps past 63
    assert D.heading(runner, syms) == 70 % 64
    D.drive(runner, 12, right=True)
    assert D.heading(runner, syms) == (70 - 12) % 64
    runner.frame_step(1)
    assert D.heading_applied(runner, syms) == D.heading(runner, syms)
    D.steer_to(runner, syms, 0)


def test_rotated_views_render_declared_structure(booted, tmp_path):
    """Pose-distinguishing rendered structure. h0 (north, along the ring
    road): ONE narrow yellow center line converging toward the horizon.
    h16 (west, along the start spoke): the road now CROSSES the view — its
    yellow line renders as WIDE horizontal bands (impossible at h0). h32
    (south): a converging center line again (the road's mirror view). At
    every heading the composition invariants hold: HUD text white intact
    and the seam line backdrop."""
    from PIL import Image
    runner, syms, world, lut = booted
    grad, m7 = D.load_tool("gen_gradient"), D.load_tool("gen_m7_assets")

    def shot(name):
        p = tmp_path / name
        runner.frame_step(2)
        runner.take_screenshot(str(p))
        return Image.open(p).convert("RGB")

    def rgb(c):
        return tuple(((c >> s) & 31) << 3 | ((c >> s) & 31) >> 2
                     for s in (0, 5, 10))

    yellow, white = rgb(0x03FF), rgb(0x7FFF)

    def yellow_rows(img):
        """map: y -> yellow pixel xs (gradient-tinted yellows count too:
        yellow saturates R/G under ADD, so match (255, 255, *))."""
        w, h = img.size
        out = {}
        for y in range(50, h):
            xs = [x for x in range(w)
                  if img.getpixel((x, y))[:2] == (255, 255)
                  and img.getpixel((x, y)) != white]
            if xs:
                out[y] = xs
        return out

    def invariants(img, tag):
        assert any(img.getpixel((x, 2 * 8 + 3 + D.content_top(img))) == white
                   for x in range(img.size[0])), f"{tag}: HUD text gone"
        # Scanline HUD_LINES is the FIRST FLOOR LINE. The TM table's unit
        # 44 is $11 (BG1+OBJ) and a unit with cumulative line index K is
        # visible at exactly scanline K — so the band boundary
        # falls precisely where the table says. The heading-independent
        # invariant is that this line carries declared FLOOR colours under
        # the declared tint for scanline 44, whatever the camera faces.
        # (Two earlier versions of this claim were wrong: "the seam renders
        # backdrop", and then "the seam carries the sky".)
        seam_tint = tuple(grad.scanline_tint(p)[D.world_const('HUD_LINES')] for p in range(3))
        pal = [(c & 31, (c >> 5) & 31, (c >> 10) & 31)
               for c in m7.palette()]
        want = {tuple(min(31, b + t) << 3 | min(31, b + t) >> 2
                      for b, t in zip(c, seam_tint))
                for c in pal}
        seam = {img.getpixel((x, D.world_const('HUD_LINES') + D.content_top(img))) for x in range(img.size[0])}
        assert seam <= want, f"{tag}: seam is not the sky band: {seam - want}"

    def max_span(rows):
        return max((max(xs) - min(xs) for xs in rows.values()), default=0)

    # h0 — narrow converging line: yellow present, every row's span narrow
    D.steer_to(runner, syms, 0)
    img = shot("h00.png")
    invariants(img, "h0")
    r0 = yellow_rows(img)
    assert r0, "h0: center line missing"
    assert max_span(r0) < 100, f"h0: line too wide ({max_span(r0)})"

    # h16 — the road crosses the view: some yellow row spans nearly full width
    D.steer_to(runner, syms, 16)
    img = shot("h16.png")
    invariants(img, "h16")
    r16 = yellow_rows(img)
    assert r16, "h16: crossing road's line missing"
    assert max_span(r16) > 180, \
        f"h16: no wide crossing band ({max_span(r16)}) — pose not applied?"

    # h32 — converging line again, and the view is NOT h0's frame
    D.steer_to(runner, syms, 32)
    img = shot("h32.png")
    invariants(img, "h32")
    r32 = yellow_rows(img)
    assert r32, "h32: center line missing"
    assert max_span(r32) < 100, f"h32: line too wide ({max_span(r32)})"
    D.steer_to(runner, syms, 0)


def test_forward_and_reverse_track_the_oracle_at_off_axis_headings(booted):
    """Accelerate 12 frames at eight off-axis headings (and reverse at one):
    position, velocity and BOTH sub-pixel accumulators match the physics
    oracle exactly — the off-axis headings are where the magnitude-then-sign
    scaling and the fractional carry actually bite — and the streamed window
    stays byte-exact after every leg."""
    runner, syms, world, lut = booted
    for h in (4, 12, 20, 28, 36, 44, 52, 60):
        D.steer_to(runner, syms, h)
        sim = D.sim_from_rom(runner, syms, lut)
        D.drive_sim(runner, sim, 12, b=True)
        D.assert_matches_sim(runner, syms, sim, f"forward @h{h}")
        D.brake_to_stop(runner, syms)
        D.assert_window_exact(runner, syms, world, f"after fwd @h{h}")
    D.steer_to(runner, syms, 12)
    sim = D.sim_from_rom(runner, syms, lut)
    D.drive_sim(runner, sim, 12, down=True)
    assert D.vel(runner, syms) < 0, "Down from rest never reversed"
    D.assert_matches_sim(runner, syms, sim, "reverse @h12")
    D.coast_to_stop(runner, syms)
    D.assert_window_exact(runner, syms, world, "after reverse @h12")


def test_pirouette_while_driving_stays_lockstep(booted):
    """The everything-at-once frame: steer 1 step AND accelerate every frame
    for 128 frames (two full revolutions) — a pose retarget in every VBlank
    on top of live streaming. The oracle simulates the tick's exact rule
    (steer, then integrate with the NEW heading): position, heading, velocity
    and both accumulators must match INTEGER-EXACTLY (any dropped tick,
    missed retarget, or staging overrun breaks the equality), and the window
    is byte-exact once the camera stops."""
    runner, syms, world, lut = booted
    D.steer_to(runner, syms, 0)
    D.coast_to_stop(runner, syms)
    sim = D.sim_from_rom(runner, syms, lut)
    D.drive_sim(runner, sim, 128, b=True, left=True)
    D.assert_matches_sim(runner, syms, sim, "pirouette")
    runner.frame_step(1)
    assert D.heading_applied(runner, syms) == sim.h
    D.brake_to_stop(runner, syms)
    D.assert_window_exact(runner, syms, world, "after pirouette")


def test_no_uninitialized_reads_across_the_turning_path(booted):
    """Power-on contract over the whole steering/driving history — the pose
    retarget path (index tables, DASB shadows) reads only written state."""
    runner, syms, world, lut = booted
    runner.frame_step(10)
    runner.assert_no_uninitialized_reads()
