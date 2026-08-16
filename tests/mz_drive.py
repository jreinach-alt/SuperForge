"""Shared microzero drive/verify helpers (NOT a test module).

Deterministic frame-stepped driving for the race scene: Left/Right steer one
pose step per frame, B accelerates toward the declared max, Down brakes and
then reverses, and releasing everything coasts. The movement oracle is
tools/gen_move_lut.Sim — a bit-exact mirror of race_logic.asm (velocity
clamps, the magnitude-then-sign step, the sub-pixel accumulators and the lap
sector machine), so every position check below is integer-exact.
"""
import importlib.util
import re
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType  # noqa: E402

VR, WR = MemoryType.SnesVideoRam, MemoryType.SnesWorkRam


def load_tool(name):
    """Import a generator from tools/ as the oracle SSoT.

    dont_write_bytecode: these are loaded by path on every test run, and the
    default leaves a __pycache__ beside the generators that tracks nothing
    and shows up in git status."""
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(
            name, SUPERFORGE / "tools" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.dont_write_bytecode = prev


def sky_rgb():
    """The BG2 sky ramp's base colours, as rendered 8-bit RGB triples.

    From tools/gen_sky.RAMP — the generator is the SSoT. These are the
    UNTINTED colours: rgb_gradient's per-scanline COLDATA add lands on top
    of them, so a test that expects tinted sky must add the declared tint
    itself rather than hardcoding the result."""
    g = load_tool("gen_sky")
    return {tuple((v << 3) | (v >> 2) for v in c) for c in g.RAMP}


TITLE, RACE, RESULTS = 0, 1, 2


def scene_now(runner, syms):
    """(current scene id, phase) from the scene_mgr control block."""
    cur, _nxt, phase = runner.read_bytes(WR, syms["ES_SM_CTL"]["start"], 3)
    return cur, phase


def enter_race(runner, syms, limit=600):
    """Press START on the title and WAIT FOR ARRIVAL in the race scene.

    Boots used to be wall-clock: press START, `run_frames(60)`, assume the
    fade edge completed. Under host load the START press or the fade can
    miss those windows, and every race-scoped read afterwards is a read of
    UNINITIALISED WRAM — race-scoped bytes have no owner on the title screen
    and hold random power-on values there. That produced the "unexplained"
    full-suite flake: an impossible heading (`steer_to(40) landed on 210`),
    reproduced by a later review at roughly 1 clean run in 2.

    So this polls the scene manager for (RACE, phase 0) and FAILS LOUDLY if
    it never arrives, instead of proceeding to read whatever was in RAM.
    `test_measure_rebuild`'s `raced` fixture does the same thing, and is the
    one race-entering path that never flaked."""
    runner.frame_step(2, start=True)
    runner.frame_step(2)
    for _ in range(limit):
        if scene_now(runner, syms) == (RACE, 0):
            runner.frame_step(2)          # let the render catch up
            return
        runner.frame_step(1)
    cur, phase = scene_now(runner, syms)
    raise AssertionError(
        f"race scene never settled in {limit} frames — stuck at "
        f"(scene {cur}, phase {phase}). Every race-scoped read from here "
        f"would be uninitialised WRAM, not game state.")


VISIBLE_SCANLINES = 224


def content_top(img):
    """The image row that IS scanline 0 of a MesenRunner screenshot.

    Screenshots are letterboxed with black borders; the content span is the
    224 visible scanlines. LOCATED, never hardcoded — a hardcoded `+ 6`
    offset is exactly how one off-by-one ended up in two test files at once,
    where it cancelled a matching bug in the gradient generator and kept the
    whole suite green while both were wrong. The asserts below
    make the anchor state its own assumptions instead of silently sliding."""
    rows = [{img.getpixel((x, y)) for x in range(img.size[0])}
            for y in range(img.size[1])]
    content = [y for y, r in enumerate(rows) if r != {(0, 0, 0)}]
    assert content, "the frame is entirely black — nothing rendered"
    assert len(content) == VISIBLE_SCANLINES, (
        f"expected {VISIBLE_SCANLINES} visible scanlines between the "
        f"letterbox borders, found {len(content)} — anchor not trustworthy")
    assert content == list(range(content[0], content[0] + len(content))), \
        "the content span has black rows inside it — anchor assumption broken"
    return content[0]


def world_const(name):
    """Read one assemble-time constant out of game/microzero/world.inc.

    world.inc is the SSoT for the game's geometry, so a test that needs
    PIVOT_LINE or HUD_LINES reads it from there. Re-declaring one as a
    literal in a test file is how the test keeps asserting the old geometry
    after the game moved — silently, because the number still looks right."""
    src = (SUPERFORGE / "game" / "microzero" / "world.inc").read_text()
    m = re.search(rf"^\s*{re.escape(name)}\s*=\s*(-?\d+)", src, re.M)
    assert m, f"world.inc has no constant {name!r}"
    return int(m.group(1))


# --- raw state reads (symbol_map addresses only) ----------------------------

def _u8(runner, syms, name, off=0):
    return runner.read_bytes(WR, syms[name]["start"] + off, 1)[0]


def _u16(runner, syms, name, off=0):
    return runner.read_u16(WR, syms[name]["start"] + off)


def heading(runner, syms):
    return _u8(runner, syms, "US_HEADING")


def heading_applied(runner, syms):
    return _u8(runner, syms, "US_HEADING_AP")


def pos_px(runner, syms):
    org = syms["ES_M7ORG"]["start"]
    return (runner.read_u16(WR, org), runner.read_u16(WR, org + 2))


def cam_tiles(runner, syms):
    x, y = pos_px(runner, syms)
    return x >> 3, y >> 3


def vel(runner, syms):
    """Signed 8.8 velocity, from the ROM's two's-complement word."""
    v = _u16(runner, syms, "US_VEL")
    return v - 0x10000 if v & 0x8000 else v


def lap(runner, syms):
    return _u8(runner, syms, "US_LAP")


def race_state(runner, syms):
    """The whole physics + lap state, as the oracle's tuple."""
    return (pos_px(runner, syms), heading(runner, syms), vel(runner, syms),
            _u16(runner, syms, "US_SUB_PX"), _u16(runner, syms, "US_SUB_PX", 2),
            lap(runner, syms), _u8(runner, syms, "US_SECTOR"),
            _u8(runner, syms, "US_CKPT"))


# --- the oracle -------------------------------------------------------------

def sim_from_rom(runner, syms, lut):
    """Seed the oracle from the ROM's live state — every later assertion is
    then a claim about the ROM's ARITHMETIC, not about its starting point."""
    (x, y), h, v, sx, sy, lp, sect, ckpt = race_state(runner, syms)
    return lut.Sim(x, y, h=h, vel=v, sub_x=sx, sub_y=sy,
                   lap=lp, sect=sect, ckpt=ckpt)


def sim_tuple(sim):
    return (sim.pos, sim.h, sim.vel, sim.sub_x, sim.sub_y,
            sim.lap, sim.sector, sim.ckpt)


def assert_matches_sim(runner, syms, sim, tag):
    """Position, heading, velocity, both sub-pixel accumulators and the whole
    lap machine must agree with the oracle EXACTLY."""
    got, want = race_state(runner, syms), sim_tuple(sim)
    fields = ("pos", "h", "vel", "sub_x", "sub_y", "lap", "sector", "ckpt")
    assert got == want, (
        f"{tag}: ROM/oracle divergence\n  " +
        "\n  ".join(f"{f}: got {g!r} want {w!r}"
                    for f, g, w in zip(fields, got, want) if g != w))


# --- driving ----------------------------------------------------------------

def drive(runner, n, **buttons):
    """Hold `buttons` for n frames (ROM only)."""
    for _ in range(n):
        runner.frame_step(1, **buttons)


def drive_sim(runner, sim, n, **buttons):
    """Hold `buttons` for n frames, advancing the ROM and the oracle in
    lockstep. Oracle button names match the ROM's controls."""
    for _ in range(n):
        runner.frame_step(1, **buttons)
        sim.frame(left=buttons.get("left", False),
                  right=buttons.get("right", False),
                  b=buttons.get("b", False),
                  down=buttons.get("down", False))
    return sim


def coast_to_stop(runner, syms, limit=400):
    """Release everything and let friction bring the car to rest."""
    for _ in range(limit):
        if vel(runner, syms) == 0:
            runner.frame_step(1)
            return
        runner.frame_step(1)
    raise AssertionError(f"car never coasted to rest (vel={vel(runner, syms)})")


def brake_to_stop(runner, syms, sim=None, limit=400):
    """Hold Down until the car is at rest, then release — the fast way to a
    known-still camera. Braking clamps AT zero, so releasing on the stop
    frame is what keeps it from rolling backwards. Advances `sim` too when
    given. The full-window streaming invariant is only meaningful at rest:
    while the camera moves, VRAM legitimately trails it by the staging +
    VBlank-drain lag."""
    for _ in range(limit):
        v = vel(runner, syms)
        if v == 0:
            runner.frame_step(1)
            if sim is not None:
                sim.frame()
            return sim
        down = v > 0
        runner.frame_step(1, down=down)
        if sim is not None:
            sim.frame(down=down)
    raise AssertionError(f"car never braked to rest (vel={vel(runner, syms)})")


def steer_to(runner, syms, target):
    """Frame-step Left/Right (1 pose step/frame) to the target heading via
    the shortest arc; assert the ROM lands exactly on it."""
    h = heading(runner, syms)
    d = (target - h) & 63
    if d == 0:
        runner.frame_step(1)
    elif d <= 32:
        for _ in range(d):
            runner.frame_step(1, left=True)
    else:
        for _ in range(64 - d):
            runner.frame_step(1, right=True)
    got = heading(runner, syms)
    assert got == target, f"steer_to({target}) landed on {got}"
    runner.frame_step(2)         # NMI applies the pose; render catches up
    assert heading_applied(runner, syms) == target


# --- driving the track -----------------------------------------------------
# A steering controller run against the ORACLE, so the button sequence is
# deterministic and independent of the ROM: the ROM must then match it.
#
# The course is an octagon (tools/gen_m7_assets.oct_dist), so "distance from
# the centre" is the octagon norm rather than a radius, and the outward
# direction is that norm's gradient: the unit normal of whichever of the
# eight sides the car is currently against. Both come from the GENERATOR —
# the map and the racing line are then the same geometry by construction,
# not two descriptions of it that can drift.

# Tuned against the ORACLE alone (no emulator needed), by sweeping both and
# measuring the octagon-norm distance over a full 3-lap circuit. The road
# band is 1504..1696 px; this pair holds d in 1552..1604, i.e. 48 px (6
# tiles) of clearance at the tightest point, and the result is flat for gain
# 4..8 — so it is a plateau, not a knife-edge fit. Lookahead matters far
# more than gain: with none at all the controller starts its 45-degree
# corner turn only AT the vertex and runs 74 px off the outside of the road.
STEER_GAIN = 6.0                 # centre-line-correction weight
LOOKAHEAD_PX = 200               # how far ahead the controller reads the
                                 # track's shape


def _track():
    return load_tool("gen_m7_assets")


def track_mid_px():
    """The centre-line apothem in pixels — the line the controller holds."""
    return _track().OCT_MID * 8


def oct_dist_px(x, y, lut):
    """The car's octagon-norm distance from the world centre, in pixels."""
    g = _track()
    return g.oct_dist(x - lut.CENTER_PX, y - lut.CENTER_PX)


def oct_normal(x, y, lut):
    """Outward unit normal of the octagon field at (x, y).

    Whichever term of the norm is the maximum names the side the point is
    against: |dx| -> an east/west straight, |dy| -> a north/south straight,
    the diagonal term -> one of the four 45-degree sides. On a circle this
    would just be (cos phi, sin phi); the octagon's is piecewise constant,
    which is exactly why the corners are corners."""
    import math
    dx, dy = x - lut.CENTER_PX, y - lut.CENTER_PX
    ax, ay = abs(dx), abs(dy)
    diag = (ax + ay) / math.sqrt(2)
    sx = 1.0 if dx >= 0 else -1.0
    sy = 1.0 if dy >= 0 else -1.0
    if diag >= ax and diag >= ay:
        r = math.sqrt(2) / 2
        return sx * r, sy * r
    if ax >= ay:
        return sx, 0.0
    return 0.0, sy


def track_heading(sim, lut):
    """The heading that follows the octagon.

    The tangent of the side the car is heading INTO (read LOOKAHEAD_PX along
    the current heading, so the controller starts its 45-degree corner turn
    before the vertex instead of after it — at one pose step per frame a
    45-degree change takes 8 frames, which is 384 px of travel at the
    declared max), biased toward the centre line by however far the car has
    drifted off it."""
    import math
    ux, uy = lut.unit(sim.h)                            # 8.8 unit heading
    ahead_x = sim.x + ux * LOOKAHEAD_PX / 256.0
    ahead_y = sim.y + uy * LOOKAHEAD_PX / 256.0
    nx, ny = oct_normal(ahead_x, ahead_y, lut)
    tx, ty = ny, -nx                                    # counterclockwise
    mid = track_mid_px()
    err = (mid - oct_dist_px(sim.x, sim.y, lut)) / mid  # >0 = drifted inward
    cx, cy = oct_normal(sim.x, sim.y, lut)
    ax = tx + STEER_GAIN * err * cx
    ay = ty + STEER_GAIN * err * cy
    theta = math.atan2(-ax, -ay)                        # invert the LUT's map
    return round(theta * lut.POSES / (2 * math.pi)) % lut.POSES


def track_buttons(sim, lut):
    """One frame of the controller: full throttle, at most one pose step of
    steering toward the track heading (the declared max turn rate)."""
    d = (track_heading(sim, lut) - sim.h) % lut.POSES
    kw = {"b": True}
    if d and d <= lut.POSES // 2:
        kw["left"] = True
    elif d:
        kw["right"] = True
    return kw


def drive_laps(runner, syms, sim, lut, target_lap, limit=900):
    """Lap the ring until the ROM's lap counter reaches target_lap, checking
    it against the oracle every frame. Stops AT the target: the race tick
    requests the results scene on that frame, after which race::tick no
    longer runs and the oracle would diverge."""
    frames = []
    for f in range(limit):
        prev = sim.lap
        drive_sim(runner, sim, 1, **track_buttons(sim, lut))
        if sim.lap != prev:
            frames.append(f)
        assert lap(runner, syms) == sim.lap, (
            f"frame {f}: ROM lap {lap(runner, syms)} vs oracle {sim.lap}")
        if sim.lap >= target_lap:
            return frames
    raise AssertionError(f"only reached lap {sim.lap} in {limit} frames")


def assert_window_exact(runner, syms, world, tag):
    """THE streaming invariant: every tile of the 128x128 VRAM window equals
    the world at the camera's position-wrapped window — full coverage.

    Only meaningful with the camera AT REST: while it moves, VRAM trails it
    by the staging + VBlank-drain lag BY DESIGN (stream_tick stages this
    frame's entering edges; the NMI drains them at the next VBlank)."""
    assert vel(runner, syms) == 0, (
        f"{tag}: window check while moving (vel={vel(runner, syms)}) — "
        f"brake_to_stop() first; a trailing edge there is not a bug")
    runner.frame_step(3)         # drain pending slots + presentation lag
    tx, ty = cam_tiles(runner, syms)
    vram = runner.read_bytes(VR, 0, 128 * 128 * 2)[0::2]
    bad = []
    for wr_ in range(ty - 64, ty + 64):
        row_off = (wr_ & 127) * 128
        wrow = (wr_ & 511) * 512
        for wc in range(tx - 64, tx + 64):
            got = vram[row_off + (wc & 127)]
            want = world[wrow + (wc & 511)]
            if got != want:
                bad.append((wr_ & 511, wc & 511, got, want))
    assert not bad, (f"{tag}: cam=({tx},{ty}) {len(bad)} stale tiles, "
                     f"first: {bad[:5]}")
