"""Acceptance gate for the racer template: the Mode 7 racing rail plays.

THIN-VERIFICATION scope: the Mode 7 renderer, the macro group, and the
matrix-table internals are already proven by tests/test_mode7.py — this gate
verifies the TEMPLATE's composition on its real outputs: the rendered pixels
(perspective floor, the kart sprite, rotation under both steer directions),
the OAM bytes (kart slot + sprite speed bar), the engine camera state
(M7_PV_POSX/POSY/ANGLE at $7E:01DF/$01E3/$01DE), and the game's DP speed.

State cycles exercised: standstill -> accelerate (B) -> coast, and steering
in BOTH directions (LEFT then RIGHT — the all-axes discipline).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

HORIZON = 56                    # PV_L0_RACING — the floor starts here (arcade-racer high horizon)
M7_PV_ANGLE = 0x01DE            # engine_state.inc absolute addresses
M7_PV_POSX_INT = 0x01E1         # integer word of the 16.16 camera X
M7_PV_POSY_INT = 0x01E5
DP_SPEED = 0x3C                 # R_SPEED (game DP, 8.8)

START_X, START_Y = 872, 512     # the template's spawn (on the start line)
VEHICLE_X, VEHICLE_Y = 112, 168  # fixed-screen kart (32x32)
TICK_LIT, TICK_DIM = 0x08, 0x0A  # vehicle.inc HUD tick tiles


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _rgb(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return list(img.getdata()), w, h


def _px(data, w, h, x, y):
    """Pixel at SNES coordinates (x, y) (screenshot may be scaled/overscan)."""
    return data[int(y * h / 224.0) * w + int(x * w / 256.0)]


def _floor_region(data, w, h):
    y0, y1 = int(100 * h / 224.0), int(220 * h / 224.0)
    return data[y0 * w:y1 * w]


def _sky_row_uniformity(data, w, h, q=32):
    """Average per-row dominant-color fraction in the sky band (scanlines
    ~20-47, above the horizon, below the HUD). ~1.0 = each row is a flat color
    (a real sky / backdrop); low = rows are horizontally fragmented (a Mode 7
    ground smear with vanishing-point structure). Color-blind to the sky hue and
    immune to a uniform per-scanline tint (the day-night gradient shifts a whole
    row together). This is what distinguishes a genuine sky from the original
    template's tinted ground smear — see CLAUDE.md "Indirect-Evidence Tests".
    """
    from collections import Counter
    y0, y1 = int(0.09 * h), int(0.21 * h)
    fracs = []
    for y in range(y0, y1):
        rc = Counter()
        for x in range(w):
            r, g, b = data[y * w + x]
            rc[(r // q, g // q, b // q)] += 1
        fracs.append(max(rc.values()) / w)
    return sum(fracs) / len(fracs) if fracs else 0.0


def test_racer_drives_and_steers(runner):
    rom = BUILD / "racer.sfc"
    assert rom.exists(), f"{rom} not built — run `make racer` first"
    runner.load_rom(str(rom), run_seconds=2.0)

    # --- boots + heartbeat advances ---
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    f1 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    f2 = runner.read_u16(WR, 0xE010)
    assert f2 > f1 > 0, f"frame heartbeat not advancing: {f1} -> {f2}"

    # --- deterministic spawn: on the start line, standstill ---
    assert runner.read_u16(WR, M7_PV_POSX_INT) == START_X
    assert runner.read_u16(WR, M7_PV_POSY_INT) == START_Y
    assert runner.read_bytes(WR, M7_PV_ANGLE, 1)[0] == 0
    assert runner.read_u16(WR, DP_SPEED) == 0

    # --- the perspective floor renders: the region below the horizon is a
    # real track image (several distinct colors — road grays, start-line
    # black/white — not a blank or single-color band).
    shot0 = "/tmp/_racer_0.png"
    runner.take_screenshot(shot0)
    d0, w, h = _rgb(shot0)
    floor = _floor_region(d0, w, h)
    assert len(set(floor)) >= 3, \
        f"floor below the horizon shows {len(set(floor))} color(s) — track not rendered"

    # --- a DISTINCT sky above the horizon, not the ground smeared upward
    # (the original racer defect). The TM-split (arm_sky_split) turns BG1 off
    # above the horizon so the reserved sky backdrop shows; a real sky is
    # horizontally uniform per scanline, a Mode 7 smear is fragmented. Asserting
    # on rendered pixels (not a proxy) and on STRUCTURE (uniformity), because a
    # color-only check is fooled by the day-night tint darkening the smear.
    sky_uni = _sky_row_uniformity(d0, w, h)
    assert sky_uni >= 0.70, \
        f"no distinct sky above the horizon: sky-band row uniformity {sky_uni:.3f} " \
        f"(< 0.70 => ground smear with horizontal structure, not a sky)"
    # and the sky must not be a color-copy of the floor (a real sky is its own color)
    from collections import Counter
    q = 32
    def _hist(region):
        c = Counter()
        for r, g, b in region:
            c[(r // q, g // q, b // q)] += 1
        tot = sum(c.values()) or 1
        return {k: v / tot for k, v in c.items()}
    sky_band = [d0[y * w + x] for y in range(int(0.09 * h), int(0.21 * h)) for x in range(w)]
    sh, fh = _hist(sky_band), _hist(floor)
    overlap = sum(min(sh.get(k, 0), fh.get(k, 0)) for k in set(sh) | set(fh))
    assert overlap <= 0.30, \
        f"sky band color-overlaps the floor {overlap:.3f} (> 0.30 => not a distinct sky)"

    # --- the kart sprite is visible: OAM slot 0 holds it, and the rendered
    # pixels inside its 32x32 box show the kart's red body AND white helmet
    # (colors the start-line floor at the spawn doesn't provide together).
    kart = runner.read_bytes(OAM, 0, 4)              # slot 0: x, y, tile, attr
    assert (kart[0], kart[1], kart[2]) == (VEHICLE_X, VEHICLE_Y, 0), \
        f"OAM slot 0 is not the kart: {tuple(kart)}"
    box = [_px(d0, w, h, x, y)
           for x in range(VEHICLE_X + 4, VEHICLE_X + 28, 2)
           for y in range(VEHICLE_Y + 2, VEHICLE_Y + 30, 2)]
    assert any(r > 160 and g < 130 and b < 130 for r, g, b in box), \
        "kart body (red) not visible in its screen box"
    assert any(r > 200 and g > 200 and b > 200 for r, g, b in box), \
        "kart helmet (white) not visible in its screen box"

    # --- speed bar at standstill: slots 1-6 all DIM ticks ---
    bar = runner.read_bytes(OAM, 4, 24)
    assert all(bar[i * 4 + 2] == TICK_DIM for i in range(6)), \
        f"speed bar not all-dim at standstill: {[bar[i*4+2] for i in range(6)]}"

    # --- accelerate: hold B ~60 frames -> speed builds, the camera position
    # actually moves through the world, and the speed bar lights up.
    runner.set_input(0, b=True)
    runner.run_frames(60)
    runner.set_input(0)
    speed = runner.read_u16(WR, DP_SPEED)
    assert speed > 0x0100, f"holding B built no speed: {speed:#06x}"
    posy = runner.read_u16(WR, M7_PV_POSY_INT)
    moved = (START_Y - posy) % 1024
    assert 30 < moved < 512, \
        f"holding B did not move the camera forward: posy {START_Y} -> {posy}"
    bar = runner.read_bytes(OAM, 4, 24)
    assert bar[2] == TICK_LIT, \
        f"speed bar did not light under acceleration: {[bar[i*4+2] for i in range(6)]}"

    runner.take_screenshot("/tmp/_racer_1.png")
    d1, w1, h1 = _rgb("/tmp/_racer_1.png")
    assert (w1, h1) == (w, h)

    # --- steer LEFT: the angle byte advances (+ direction) and the rendered
    # floor visibly rotates.
    a0 = runner.read_bytes(WR, M7_PV_ANGLE, 1)[0]
    runner.set_input(0, left=True)
    runner.run_frames(30)
    runner.set_input(0)
    a1 = runner.read_bytes(WR, M7_PV_ANGLE, 1)[0]
    d_left = (a1 - a0) % 256
    assert 1 <= d_left <= 127, f"LEFT did not advance the angle: {a0} -> {a1}"

    runner.take_screenshot("/tmp/_racer_2.png")
    d2, _, _ = _rgb("/tmp/_racer_2.png")
    f1px, f2px = _floor_region(d1, w, h), _floor_region(d2, w, h)
    diff = sum(1 for p, q in zip(f1px, f2px) if p != q)
    assert diff > 0.05 * len(f1px), \
        f"steering LEFT did not rotate the rendered floor ({diff}/{len(f1px)} px changed)"

    # --- steer RIGHT: the angle moves the OTHER way and the view rotates
    # again (all-axes: both steer directions are exercised).
    runner.set_input(0, right=True)
    runner.run_frames(30)
    runner.set_input(0)
    a2 = runner.read_bytes(WR, M7_PV_ANGLE, 1)[0]
    d_right = (a2 - a1) % 256
    assert 129 <= d_right <= 255, f"RIGHT did not turn the angle back: {a1} -> {a2}"

    runner.take_screenshot("/tmp/_racer_3.png")
    d3, _, _ = _rgb("/tmp/_racer_3.png")
    f3px = _floor_region(d3, w, h)
    diff = sum(1 for p, q in zip(f2px, f3px) if p != q)
    assert diff > 0.05 * len(f2px), \
        f"steering RIGHT did not rotate the rendered floor ({diff}/{len(f2px)} px changed)"

    # --- coast: with no input the kart decays back toward standstill ---
    runner.run_frames(120)
    assert runner.read_u16(WR, DP_SPEED) == 0, "coasting never decays to a stop"
