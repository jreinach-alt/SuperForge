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


def _stamp_deltas(runner, frames, **buttons):
    """Frame-deterministic loop-rate probe: step exactly one PPU frame at a
    time (input latched) and read the game loop's per-iteration heartbeat
    ($7E:E010 = FRAME_COUNTER written once per loop pass). A loop holding
    60 fps advances the stamp by exactly 1 every hardware frame; an
    iteration that overruns its frame shows up as a 2 (then 0) delta."""
    vals = []
    for _ in range(frames):
        runner.frame_step(1, **buttons)
        vals.append(runner.read_u16(WR, 0xE010))
    return [(b - a) & 0xFFFF for a, b in zip(vals, vals[1:])]


def test_racer_loop_holds_60fps_under_steer(runner):
    """LOOP-RATE GATE (the S1 public finding, fixed): any angle change forces
    a Mode 7 perspective rebuild, and a full rebuild at the racer's trapezoid
    measures 245,779 master clocks (69% of a frame) — one frame cannot hold
    it beside the rail's HDMA + game work, which used to halve the loop to
    30 fps under ANY steering (frame-stamp deltas 2,0,2,0...). The template
    now spreads the rebuild across two frames (pv_rebuild_pass1/_pass2, the
    engine's split entry points) — this gate holds it to 60.

    Also pins the day-night blend cadence: every 8th blend frame rebuilds
    three 225-entry gradient COLDATA tables, a whole-frame cost that predates
    this gate and overruns REGARDLESS of steering (measured at idle: one 2,0
    pair per step). Steering must not stack on it — max stall stays 2 frames
    and the miss count stays near the step rate, never a 30 fps lock."""
    rom = BUILD / "racer.sfc"
    assert rom.exists(), f"{rom} not built — run `make racer` first"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.debug_break()

    # --- sustained steer inside the DAY hold: 60 fps, every single frame ---
    for name, buttons in (("LEFT+B", dict(b=True, left=True)),
                          ("RIGHT+B", dict(b=True, right=True)),
                          ("LEFT only", dict(left=True))):
        n = 310 if name == "LEFT+B" else 80
        deltas = _stamp_deltas(runner, n, **buttons)
        assert set(deltas) == {1}, (
            f"loop dropped under sustained {name} steer: stamp deltas "
            f"{sorted(set(deltas))} (a 2 means an iteration overran its frame; "
            f"the rebuild pacing is broken)")

    # --- steer straight through the DAY->NIGHT blend window (stamp 900+):
    # the gradient-step frames may each cost one extra frame (pre-existing,
    # steering-independent), but never more, and never a sustained drop.
    while runner.read_u16(WR, 0xE010) < 895:
        runner.frame_step(1, b=True)
    deltas = _stamp_deltas(runner, 300, b=True, left=True)
    assert max(deltas) <= 2, (
        f"a loop iteration spanned {max(deltas)} frames during a steered "
        f"blend — the perspective pacing is colliding with the gradient step")
    misses = deltas.count(2)
    # 300 frames cover ~37 8-frame gradient steps; allow pacing interplay
    # up to ~2x that, far below the 150 misses of a 30 fps lock.
    assert misses <= 80, (
        f"{misses} overrun frames in a 300-frame steered blend (expected "
        f"~37-50 from the gradient steps alone) — steering is stacking "
        f"drops onto the blend")
    runner.debug_resume()


def test_racer_offroad_grass_drags(runner):
    """OFF-ROAD GATE: the track is collision ground truth, not paint. The
    template probes the Mode 7 map tile under the kart every frame (ROM copy
    of the interleaved blob + the generated track_surface class table) and
    bleeds speed on grass down to a crawl (GRASS_CAP = 0x00C0).

    Drive: hold B straight from the spawn. The heading leaves the circular
    road at posy ~311 and stays on grass for hundreds of pixels, so the two
    sample points are unambiguous. Evidence: the OAM speed bar (rendered
    HUD: lit tick count collapses 6 -> 1), the engine camera's actual
    travel rate (posy px per 30 frames), and the DP speed hitting the
    documented crawl floor."""
    rom = BUILD / "racer.sfc"
    assert rom.exists(), f"{rom} not built — run `make racer` first"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.debug_break()

    def lit_ticks():
        bar = runner.read_bytes(OAM, 4, 24)
        return sum(1 for i in range(6) if bar[i * 4 + 2] == TICK_LIT)

    # --- on the road: full speed, full bar (non-vacuity for the drag) ---
    for _ in range(70):
        runner.frame_step(1, b=True)
    speed_road = runner.read_u16(WR, DP_SPEED)
    posy = runner.read_u16(WR, M7_PV_POSY_INT)
    assert posy > 320, f"already off the road at posy {posy} — retime the probe"
    assert speed_road == 0x0300, \
        f"not at the speed cap on the road: {speed_road:#06x}"
    assert lit_ticks() == 6, f"speed bar not full at cap: {lit_ticks()} lit"
    y0 = posy
    for _ in range(30):
        runner.frame_step(1, b=True)
    road_rate = (y0 - runner.read_u16(WR, M7_PV_POSY_INT)) % 1024

    # --- straight on, across the kerb into the infield grass ---
    for _ in range(130):
        runner.frame_step(1, b=True)
    speed_grass = runner.read_u16(WR, DP_SPEED)
    assert speed_grass == 0x00C0, (
        f"grass did not bleed the kart to the crawl floor: "
        f"{speed_grass:#06x} (expected GRASS_CAP 0x00c0)")
    assert lit_ticks() <= 1, \
        f"speed bar still lit on grass: {lit_ticks()} ticks"
    y1 = runner.read_u16(WR, M7_PV_POSY_INT)
    for _ in range(30):
        runner.frame_step(1, b=True)
    grass_rate = (y1 - runner.read_u16(WR, M7_PV_POSY_INT)) % 1024
    assert grass_rate * 2 < road_rate, (
        f"grass travel rate {grass_rate}px/30f is not well below the road "
        f"rate {road_rate}px/30f — the drag is not acting on real motion")
    runner.debug_resume()


def test_racer_pause_freezes_world(runner):
    """PAUSE GATE: START toggles a true freeze-frame. While paused, held
    inputs are ignored and the RENDERED FRAME is pixel-identical across
    frames (world, effects, and camera all hold), yet the loop stays alive
    (heartbeat advances — it is a pause, not a hang). START again resumes."""
    from PIL import ImageChops

    rom = BUILD / "racer.sfc"
    assert rom.exists(), f"{rom} not built — run `make racer` first"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.debug_break()
    for _ in range(60):
        runner.frame_step(1, b=True)
    runner.frame_step(1, b=True, start=True)     # pause (rising edge)
    runner.frame_step(2)
    posy0 = runner.read_u16(WR, M7_PV_POSY_INT)
    hb0 = runner.read_u16(WR, 0xE010)
    runner.take_screenshot("/tmp/_racer_pause_a.png")
    for _ in range(40):
        runner.frame_step(1, b=True, left=True)  # must all be ignored
    runner.take_screenshot("/tmp/_racer_pause_b.png")
    a = Image.open("/tmp/_racer_pause_a.png").convert("RGB")
    b = Image.open("/tmp/_racer_pause_b.png").convert("RGB")
    diff_px = sum(1 for p in ImageChops.difference(a, b).convert("L").tobytes()
                  if p)
    assert runner.read_u16(WR, M7_PV_POSY_INT) == posy0, \
        "camera moved while paused"
    assert diff_px == 0, \
        f"{diff_px} pixels changed across 40 paused frames — not a freeze"
    assert runner.read_u16(WR, 0xE010) > hb0, \
        "heartbeat stopped while paused — the loop is hung, not paused"
    runner.frame_step(1, start=True)             # unpause
    runner.frame_step(2)
    for _ in range(30):
        runner.frame_step(1, b=True)
    assert runner.read_u16(WR, M7_PV_POSY_INT) != posy0, \
        "the race did not resume after unpausing"
    runner.debug_resume()


def test_racer_music_plays(runner):
    """AUDIO GATE: the race music actually sounds. The rail links the TAD
    driver + song set (lorom_tad_m7.cfg), boots the S-SMP (sf_audio_init),
    pumps the queue every frame (sf_audio_tick), and starts Song::gimo_297.
    Evidence is the emulator's RENDERED AUDIO: a ~4 s recording must carry
    real signal (measured healthy peak is ~22,400 of 32,767 full scale;
    the gate floor of 4,000 is far above silence/noise yet tolerant of mix
    changes). The TAD_STATUS mirror ($7E:016A) must report PLAYING — that
    alone is a proxy, so it only supplements the waveform evidence."""
    import struct as _struct
    import wave as _wave

    rom = BUILD / "racer.sfc"
    assert rom.exists(), f"{rom} not built — run `make racer` first"
    runner.load_rom(str(rom), run_seconds=2.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert runner.read_bytes(WR, 0x016A, 1)[0] == 1, (
        f"TAD status {runner.read_bytes(WR, 0x016A, 1)[0]} != 1 (playing) "
        f"2 s after boot — the song never started loading/playing")

    wav_path = "/tmp/_racer_song.wav"
    runner.start_audio_recording(wav_path)
    runner.run_frames(240)
    runner.stop_audio_recording()
    with _wave.open(wav_path, "rb") as w:
        n, ch = w.getnframes(), w.getnchannels()
        samples = _struct.unpack(f"<{n * ch}h", w.readframes(n))
    peak = max(abs(s) for s in samples)
    assert n > 0 and peak > 4000, (
        f"recorded audio is (near-)silent: peak {peak} over {n} frames — "
        f"the DSP is producing no music")
