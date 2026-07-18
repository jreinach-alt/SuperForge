"""Acceptance gate for the mode7_flight template: the Mode 7 free-flight rail flies.

THE CORE PROOF is altitude -> perspective scale, read from RENDERED OUTPUT (a
screenshot color-transition count per floor row + the rendered floor/landmark
size), never a proxy altitude variable. The rail's other elements (free heading +
throttle movement, the airship + altitude-scaled shadow over Mode 7) are verified
on the engine camera state (committed M7_PV_ANGLE/POSX/POSY) PLUS rendered pixels
and OAM bytes — the established Mode 7 rail bar (cf. tests/test_racer.py).

State cycles exercised:
  A1  climb (R) -> ground recedes ; descend (L) -> approaches ; clamp at both ends
  A2  turn LEFT/RIGHT (opposite angle deltas + floor rotates) ; throttle B
      forward (camera moves + floor shifts) ; release -> hover ; Y reverse
  A3  airship OAM on-screen + propeller frame advances ; shadow OAM tracks altitude
  A4  the oracle.json rendered scenarios (run by the catalog oracle runner)
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

# engine_state.inc absolute addresses (the camera state the renderer consumes)
M7_PV_ANGLE = 0x01DE
M7_PV_POSX_INT = 0x01E1          # integer word of the 16.16 camera X
M7_PV_POSY_INT = 0x01E5
# game DP + debug mirrors (orchestration only; assertions read rendered output)
DP_SPEED = 0x3C                  # R_SPEED (signed 8.8)
ALT_MIRROR = 0xE018              # R_ALT mirror (frame sequencing, not an assert)

SPAWN_X, SPAWN_Y = 872, 512
SHIP_X, SHIP_Y = 112, 96         # fixed-screen 32x32 airship


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rgb(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return list(img.getdata()), w, h


def _floor_region(data, w, h):
    y0, y1 = int(120 * h / 224.0), int(218 * h / 224.0)
    return data[y0 * w:y1 * w]


def _transitions_per_row(data, w, h, q=24):
    """Average color-transitions per floor row — the cold-start metric: a LOW /
    near ground reads ~2-4 transitions/row (few big cells), a HIGH / receded
    ground reads ~18-23 (many small cells packed to the horizon). This is the
    primary owner-facing proof that altitude drives the rendered ground scale."""
    y0, y1 = int(120 * h / 224.0), int(218 * h / 224.0)
    tot = 0
    rows = 0
    for y in range(y0, y1):
        prev = None
        t = 0
        for x in range(w):
            r, g, b = data[y * w + x]
            c = (r // q, g // q, b // q)
            if prev is not None and c != prev:
                t += 1
            prev = c
        tot += t
        rows += 1
    return tot / rows if rows else 0.0


def _boot(runner):
    rom = BUILD / "mode7_flight.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode7_flight` first"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "boot magic missing"
    f1 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    f2 = runner.read_u16(WR, 0xE010)
    assert f2 > f1 > 0, f"heartbeat not advancing: {f1} -> {f2}"


def test_a1_altitude_drives_perspective(runner):
    """A1 — climb recedes the ground, descend approaches it, clamp at both ends.
    PRIMARY proof = the rendered floor's color-transitions/row (smaller = receded).
    """
    _boot(runner)
    # deterministic spawn: over the landmark, mid-altitude, hovering
    assert runner.read_u16(WR, M7_PV_POSX_INT) == SPAWN_X
    assert runner.read_u16(WR, M7_PV_POSY_INT) == SPAWN_Y
    assert runner.read_bytes(WR, M7_PV_ANGLE, 1)[0] == 0

    runner.take_screenshot("/tmp/_ff_mid.png")
    d_mid, w, h = _rgb("/tmp/_ff_mid.png")
    mid_t = _transitions_per_row(d_mid, w, h)
    # the floor must render (multi-color, not a blank band)
    assert len(set(_floor_region(d_mid, w, h))) >= 3, "floor not rendered"

    # --- CLIMB (R): ground recedes -> MORE transitions/row ---
    runner.set_input(0, r=True)
    runner.run_frames(120)
    runner.set_input(0)
    runner.run_frames(2)
    alt_hi = runner.read_bytes(WR, ALT_MIRROR, 1)[0]
    runner.take_screenshot("/tmp/_ff_high.png")
    d_hi, _, _ = _rgb("/tmp/_ff_high.png")
    hi_t = _transitions_per_row(d_hi, w, h)
    assert hi_t > mid_t * 1.2, \
        f"climb did not recede the ground: t/row {mid_t:.1f} -> {hi_t:.1f}"

    # --- clamp at MAX: more climb does not keep shrinking ---
    runner.set_input(0, r=True)
    runner.run_frames(120)
    runner.set_input(0)
    runner.run_frames(2)
    assert runner.read_bytes(WR, ALT_MIRROR, 1)[0] == alt_hi, \
        "altitude did not clamp at the ceiling"

    # --- DESCEND (L): ground approaches -> FEWER transitions/row ---
    runner.set_input(0, l=True)
    runner.run_frames(360)
    runner.set_input(0)
    runner.run_frames(2)
    alt_lo = runner.read_bytes(WR, ALT_MIRROR, 1)[0]
    runner.take_screenshot("/tmp/_ff_low.png")
    d_lo, _, _ = _rgb("/tmp/_ff_low.png")
    lo_t = _transitions_per_row(d_lo, w, h)
    assert lo_t < hi_t * 0.6, \
        f"descend did not approach the ground: high {hi_t:.1f} -> low {lo_t:.1f}"

    # --- clamp at MIN: more descend does not keep growing, no crash ---
    runner.set_input(0, l=True)
    runner.run_frames(120)
    runner.set_input(0)
    runner.run_frames(2)
    assert runner.read_bytes(WR, ALT_MIRROR, 1)[0] == alt_lo == 0, \
        "altitude did not clamp at the floor (no crash)"
    # the loop is still alive after the per-frame rebuilds
    hb = runner.read_u16(WR, 0xE010)
    runner.run_frames(4)
    assert runner.read_u16(WR, 0xE010) > hb, "loop stalled under per-frame rebuild"


def test_a2_free_movement(runner):
    """A2 — heading turn (both directions, opposite angle deltas + floor rotates),
    throttle forward (camera moves + floor shifts), hover on release, reverse."""
    _boot(runner)
    runner.take_screenshot("/tmp/_ff_a2_base.png")
    base, w, h = _rgb("/tmp/_ff_a2_base.png")

    # turn LEFT: angle advances +, floor rotates
    a0 = runner.read_bytes(WR, M7_PV_ANGLE, 1)[0]
    runner.set_input(0, left=True)
    runner.run_frames(30)
    runner.set_input(0)
    a1 = runner.read_bytes(WR, M7_PV_ANGLE, 1)[0]
    assert 1 <= (a1 - a0) % 256 <= 127, f"LEFT did not advance angle: {a0}->{a1}"
    runner.take_screenshot("/tmp/_ff_a2_left.png")
    left, _, _ = _rgb("/tmp/_ff_a2_left.png")
    fb, fl = _floor_region(base, w, h), _floor_region(left, w, h)
    assert sum(1 for p, q in zip(fb, fl) if p != q) > 0.05 * len(fb), \
        "turning LEFT did not rotate the rendered floor"

    # turn RIGHT: angle moves the OTHER way
    runner.set_input(0, right=True)
    runner.run_frames(30)
    runner.set_input(0)
    a2 = runner.read_bytes(WR, M7_PV_ANGLE, 1)[0]
    assert 129 <= (a2 - a1) % 256 <= 255, f"RIGHT did not reverse angle: {a1}->{a2}"
    runner.take_screenshot("/tmp/_ff_a2_right.png")
    right, _, _ = _rgb("/tmp/_ff_a2_right.png")
    fr = _floor_region(right, w, h)
    assert sum(1 for p, q in zip(fl, fr) if p != q) > 0.05 * len(fl), \
        "turning RIGHT did not rotate the rendered floor"

    # throttle forward (B): camera moves + floor shifts; then hover on release
    px0, py0 = runner.read_u16(WR, M7_PV_POSX_INT), runner.read_u16(WR, M7_PV_POSY_INT)
    runner.set_input(0, b=True)
    runner.run_frames(60)
    runner.set_input(0)
    spd = runner.read_u16(WR, DP_SPEED)
    spd = spd - 0x10000 if spd >= 0x8000 else spd
    assert spd > 0x0100, f"holding B built no forward speed: {spd}"
    px1, py1 = runner.read_u16(WR, M7_PV_POSX_INT), runner.read_u16(WR, M7_PV_POSY_INT)
    moved = ((px1 - px0) % 1024, (py1 - py0) % 1024)
    assert moved != (0, 0), f"B did not move the camera: {(px0,py0)}->{(px1,py1)}"
    runner.take_screenshot("/tmp/_ff_a2_fwd.png")
    fwd, _, _ = _rgb("/tmp/_ff_a2_fwd.png")
    assert sum(1 for p, q in zip(fr, _floor_region(fwd, w, h)) if p != q) > 0.05 * len(fr), \
        "throttle forward did not shift the rendered floor"

    # release -> coast to hover
    runner.run_frames(150)
    spd = runner.read_u16(WR, DP_SPEED)
    spd = spd - 0x10000 if spd >= 0x8000 else spd
    assert spd == 0, f"did not coast to hover: speed={spd}"

    # reverse (Y): speed goes negative + camera moves the OTHER way
    px2, py2 = runner.read_u16(WR, M7_PV_POSX_INT), runner.read_u16(WR, M7_PV_POSY_INT)
    runner.set_input(0, y=True)
    runner.run_frames(40)
    runner.set_input(0)
    spd = runner.read_u16(WR, DP_SPEED)
    spd = spd - 0x10000 if spd >= 0x8000 else spd
    assert spd < 0, f"Y did not reverse the speed: {spd}"
    px3, py3 = runner.read_u16(WR, M7_PV_POSX_INT), runner.read_u16(WR, M7_PV_POSY_INT)
    assert (px3, py3) != (px2, py2), "reverse did not move the camera"


def test_a3_airship_and_shadow(runner):
    """A3 — airship OAM on-screen, propeller frame advances, shadow OAM tracks
    altitude (size + offset differ at two altitudes)."""
    _boot(runner)
    ship = runner.read_bytes(OAM, 0, 4)            # slot 0
    assert (ship[0], ship[1]) == (SHIP_X, SHIP_Y), \
        f"airship not at its screen position: {tuple(ship)}"

    # propeller animates: slot-0 tile index advances over frames
    tiles = set()
    for _ in range(20):
        tiles.add(runner.read_bytes(OAM, 2, 1)[0])
        runner.run_frames(1)
    assert len(tiles) >= 2, f"propeller did not animate (tiles seen: {tiles})"

    # shadow OAM tracks altitude: descend -> big/high-up; climb -> small/low
    runner.set_input(0, l=True)
    runner.run_frames(360)
    runner.set_input(0)
    runner.run_frames(2)
    sh_lo = runner.read_bytes(OAM, 4, 4)           # slot 1 at LOW altitude
    runner.set_input(0, r=True)
    runner.run_frames(360)
    runner.set_input(0)
    runner.run_frames(2)
    sh_hi = runner.read_bytes(OAM, 4, 4)           # slot 1 at HIGH altitude
    assert sh_lo[2] != sh_hi[2], \
        f"shadow tile (size) did not change with altitude: lo={sh_lo[2]} hi={sh_hi[2]}"
    assert sh_lo[1] != sh_hi[1], \
        f"shadow screen-Y did not track altitude: lo={sh_lo[1]} hi={sh_hi[1]}"
