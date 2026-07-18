"""Acceptance gate for the m7_oshoot rail — Mode 7 overhead run-and-gun rail.

m7_oshoot is a top-down run-and-gun on a ROTATING Mode 7 ground plane. It forks
m7_dungeon (static-affine rotating floor + the world->screen TRANSPOSE-matrix
sprite projection + world-space gameplay) and adds: 8-WAY aim/move (model A),
sf_pool BULLETS projected onto the spinning floor, timed enemy WAVES (chasers),
and world-space bullet<->enemy collision.

CARRY-FORWARD LESSON (HIGHEST priority): a Mode 7 projection test that reads OAM
coordinates or a SAME-FORMULA oracle PROVES NOTHING. EVERY projection/affine-
sprite assertion here reads the RENDERED FRAMEBUFFER (samples pixels around the
drawn sprite, classifies FLOOR vs WALL by colour, or counts enemy/bullet pixels),
across MULTIPLE rotation angles, each with a `-D` non-vacuity control build that
FAILS the same check.

DoD items (all rendered-output reads):
 1. Boot: textured rotating floor; hero centred + upright; 8-way input rotates the
    rendered floor (before/after diff); stand-and-shoot (facing persists).
 2. Bullets render ON the floor at multiple headings (rendered ring read);
    -DBULLET_PROJ_FORWARD FAILS.
 3. A bullet held at a fixed world pos stays glued to the SAME rendered floor spot
    across an angle sweep (does not swim onto walls); non-vacuity control FAILS.
 4. A bullet KILLS its target enemy at MULTIPLE plane angles (enemy OAM parked at
    Y=$F0 AND enemy-red pixels vanish); -DNO_BULLET_COLLISION -> enemy survives.
 5. Enemy waves spawn/project-red/advance/cull/pop-in; contact knocks the hero
    back + ticks HITS (visible respawn).
 6. Film-strip montage of the full loop (committed DoD artifact).
"""
import math
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
from infrastructure.test_harness.film_strip import film_strip

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

# --- debug-region mirrors (main.asm writes these every frame) ---
DBG_HEART = 0xE010
DBG_POSX = 0xE012
DBG_POSY = 0xE014
DBG_ANGLE = 0xE016
DBG_HITS = 0xE01C
DBG_ENE_BASE = 0xE020          # ENEMY_COUNT * 8 bytes: +0 wx +2 wy +4 sx +6 sy
DBG_ENE_STRIDE = 8
ENEMY_COUNT = 6
DBG_BUL_COUNT = 0xE050
DBG_BUL_BASE = 0xE052          # BULLET_N * 8 bytes: +0 wx +2 wy +4 sx +6 sy
DBG_BUL_STRIDE = 8
BULLET_N = 8
DBG_KILLS = 0xE092

# --- OAM slot map (main.asm; engine_spr assigns by call order) ---
HERO_SLOT = 0
ENEMY_OAM0 = 1                  # enemies slots 1..ENEMY_COUNT
BULLET_OAM0 = 1 + ENEMY_COUNT   # bullets slots 7..7+BULLET_N-1
HERO_X = 120                   # 128 - 8 (16x16 centred at screen 128,112)
HERO_Y = 104                   # 112 - 8
HERO_ATTR = 0x20               # priority 2, no flips -> upright
CULL_Y = 0xF0
OBJ_HALF = 8

# Frozen-glue swim thresholds (DoD 2/3 non-vacuity). A "swim" = the BACKGROUND
# under a world-floor bullet's drawn centre is wall-dominated (the bullet was
# mis-projected onto a pillar). Measured on rendered output (_bg_wall_frac_disc):
# a mis-projected FORWARD bullet reads wall_frac ~0.42..0.71 with ~44..60 wall px;
# a correctly-projected (transpose) bullet on open floor reads 0 wall px / 0.0.
# Gates sit well below the FORWARD signal and well above the FIXED floor (0), so
# both builds clear/miss them with wide margin and no flake.
GLUE_SWIM_MIN_W = 12           # min background wall px in the disc
GLUE_SWIM_MIN_WF = 0.30        # min wall fraction of the background under the sprite

# --- world arena mirror (verbatim of make_arena.py is_wall) for cross-checks.
#     The arena is an open floor field bounded by a wall ring with a regular
#     LATTICE of obstacle pillars (cover). Keep these constants in lockstep with
#     make_arena.py. ---
ARENA_LO = 4
ARENA_HI = 124
WALL_RING = 3
PILLAR_PITCH = 6
PILLAR_HALF = 1
PILLAR_PHASE = 4
SPAWN_TX_C = 64
SPAWN_TY_C = 64
PILLAR_CLEAR = 8
SPAWN_PX = (64 * 8 + 4, 64 * 8 + 4)   # main.asm SPAWN_TX/TY = 64 (arena centre)


def _on_pillar(tx, ty):
    if abs(tx - SPAWN_TX_C) <= PILLAR_CLEAR and abs(ty - SPAWN_TY_C) <= PILLAR_CLEAR:
        return False
    mx = (tx - PILLAR_PHASE) % PILLAR_PITCH
    my = (ty - PILLAR_PHASE) % PILLAR_PITCH
    near_x = mx <= PILLAR_HALF or mx >= PILLAR_PITCH - PILLAR_HALF
    near_y = my <= PILLAR_HALF or my >= PILLAR_PITCH - PILLAR_HALF
    return near_x and near_y


def _is_wall_tile(tx, ty):
    if _on_pillar(tx, ty):
        return True
    if tx < ARENA_LO or ty < ARENA_LO or tx >= ARENA_HI or ty >= ARENA_HI:
        return True
    if (tx < ARENA_LO + WALL_RING or ty < ARENA_LO + WALL_RING
            or tx >= ARENA_HI - WALL_RING or ty >= ARENA_HI - WALL_RING):
        return True
    return False


def _is_wall_px(px, py):
    return _is_wall_tile((px & 1023) >> 3, (py & 1023) >> 3)


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module")
def variants():
    """Build the -D variant ROMs (the generic make rule can't pass -D). Returns
    {name: rom_path}. Skips if the toolchain is unavailable."""
    import subprocess
    script = ROOT / "templates" / "m7_oshoot" / "build_m7_oshoot_variants.sh"
    assert script.exists(), f"{script} missing"
    res = subprocess.run(["bash", str(script)], cwd=str(ROOT),
                         capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"variant build failed (toolchain?):\n{res.stderr}")
    return {
        "projfwd": BUILD / "m7_oshoot_projfwd.sfc",      # S3 non-vacuity
        "nobulcol": BUILD / "m7_oshoot_nobulcol.sfc",    # S5 non-vacuity
        "nocol": BUILD / "m7_oshoot_nocol.sfc",          # wall-collision control
        "freeze": BUILD / "m7_oshoot_freeze.sfc",        # frozen-bullet glue test
        "freeze_fwd": BUILD / "m7_oshoot_freeze_fwd.sfc",  # glue non-vacuity
    }


# =============================================================================
# Memory + render helpers
# =============================================================================
def _angle(r):
    return r.read_u16(WR, DBG_ANGLE) & 0xFF


def _posx(r):
    return r.read_u16(WR, DBG_POSX) & 0xFFFF


def _posy(r):
    return r.read_u16(WR, DBG_POSY) & 0xFFFF


def _hits(r):
    return r.read_u16(WR, DBG_HITS) & 0xFFFF


def _kills(r):
    return r.read_u16(WR, DBG_KILLS) & 0xFFFF


def _bul_count(r):
    return r.read_u16(WR, DBG_BUL_COUNT) & 0xFFFF


def _bul_world(r, i):
    base = DBG_BUL_BASE + i * DBG_BUL_STRIDE
    return (r.read_u16(WR, base + 0) & 0xFFFF, r.read_u16(WR, base + 2) & 0xFFFF)


def _ene_world(r, i):
    base = DBG_ENE_BASE + i * DBG_ENE_STRIDE
    return (r.read_u16(WR, base + 0) & 0xFFFF, r.read_u16(WR, base + 2) & 0xFFFF)


def _oam(r, slot):
    b = r.read_bytes(OAM, slot * 4, 4)
    hi = r.read_bytes(OAM, 512 + (slot >> 2), 1)[0]
    x9 = b[0] | (((hi >> ((slot & 3) * 2)) & 1) << 8)
    return x9, b[1], b[2], b[3]


def _bullet_oam(r, i):
    return _oam(r, BULLET_OAM0 + i)


def _enemy_oam(r, i):
    return _oam(r, ENEMY_OAM0 + i)


# --- RENDERED floor/wall classification (oracle-FREE; reads the framebuffer).
#     Bands measured on the arena: wall = terracotta (180,90,60 / 220,140,100);
#     floor = blue checker (40,44,60 / 70,78,104). Same classifier family as
#     test_m7_dungeon.py (the proven rendered-floor binding guard). ---
def _is_wall_px_rgb(rgb):
    r, g, b = rgb
    return r > 130 and g < 120 and b < 95 and r > b + 40


def _is_floor_px_rgb(rgb):
    r, g, b = rgb
    return (b >= r - 10) and not _is_wall_px_rgb(rgb)


def _distinct_floor_colours(path, step=4):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    seen = set()
    for y in range(0, h, step):
        for x in range(0, w, step):
            sx, sy = x * 256 // w, y * 224 // h
            if 112 <= sx <= 144 and 96 <= sy <= 128:
                continue
            r, g, b = px[x, y]
            seen.add((r >> 3, g >> 3, b >> 3))
    return len(seen)


def _grid_samples(path, step=8):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    out = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            sx, sy = x * 256 // w, y * 224 // h
            if 112 <= sx <= 144 and 96 <= sy <= 128:
                continue
            out.append(px[x, y])
    return out


def _frac_changed(a, b, thresh=24):
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(1 for i in range(n)
              if sum(abs(a[i][c] - b[i][c]) for c in range(3)) > thresh) / n


def _floor_wall_ring(path, cx, cy, rmin=7, rmax=11):
    """Ring around a drawn sprite centre (256x224 logical) -> (n_floor, n_wall).
    Reads the framebuffer with NO reference to the projection formula."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    nf = nw = 0
    for adeg in range(0, 360, 12):
        for rad in range(rmin, rmax + 1):
            sx = cx + rad * math.cos(math.radians(adeg))
            sy = cy + rad * math.sin(math.radians(adeg))
            ix, iy = int(sx * w / 256), int(sy * h / 224)
            if 0 <= ix < w and 0 <= iy < h:
                rgb = px[ix, iy]
                if _is_wall_px_rgb(rgb):
                    nw += 1
                elif _is_floor_px_rgb(rgb):
                    nf += 1
    return nf, nw


def _bg_wall_frac_disc(path, cx, cy, radius=10):
    """Wall fraction of the BACKGROUND under/around a drawn sprite centre.

    Reads a FILLED disc (radius px, 256x224 logical) around (cx,cy) and tallies
    only the BACKGROUND floor-vs-wall pixels — the sprite's OWN colours (yellow
    bullet bolt + transparent) are EXCLUDED, so the count reflects the floor/wall
    UNDER the sprite, not the sprite itself. Returns (n_floor, n_wall, wall_frac)
    where wall_frac = n_wall / (n_wall + n_floor) (0.0 if no background sampled).

    Why a disc of background (not the fixed-radius ring of _floor_wall_ring): the
    ROUND bullet's larger pixel footprint partly fills a small fixed ring with its
    own yellow, deflating the wall tally; and the ring's wall count swings wildly
    (~17..47) with a 1-2px centre jitter when it grazes a pillar EDGE. A filled
    disc of *background only* is robust to both — the wall FRACTION of the floor/
    wall behind the sprite is stable (a mis-projected bullet sitting on a pillar
    reads ~0.4..0.7; a correctly-projected bullet on open floor reads 0.0). Reads
    the framebuffer with NO reference to the projection formula (oracle-free)."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    nf = nw = 0
    r2 = radius * radius
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > r2:
                continue
            ix = int((cx + dx) * w / 256)
            iy = int((cy + dy) * h / 224)
            if 0 <= ix < w and 0 <= iy < h:
                rgb = px[ix, iy]
                if _is_bullet_yellow(rgb):       # sprite's own pixels -> not background
                    continue
                if _is_wall_px_rgb(rgb):
                    nw += 1
                elif _is_floor_px_rgb(rgb):
                    nf += 1
    frac = nw / (nw + nf) if (nw + nf) else 0.0
    return nf, nw, frac


# enemy red body (enemy_pal[1] = (200,30,30)); bullet bright-yellow bolt
# (bullet_pal[1] = (255,230,40)). Both read the framebuffer.
def _is_enemy_red(rgb):
    r, g, b = rgb
    return r >= 150 and g <= 60 and b <= 70 and (r - max(g, b)) >= 90


def _is_bullet_yellow(rgb):
    r, g, b = rgb
    return r >= 180 and g >= 150 and b <= 120 and min(r, g) - b >= 50


def _count_color_near(path, cx, cy, pred, radius=12):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    n = 0
    for y in range(h):
        sy = y * 224 // h
        if abs(sy - cy) > radius:
            continue
        for x in range(w):
            sx = x * 256 // w
            if abs(sx - cx) > radius:
                continue
            if pred(px[x, y]):
                n += 1
    return n


def _count_color_total(path, pred):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    return sum(1 for y in range(h) for x in range(w) if pred(px[x, y]))


def _hold(r, frames, **buttons):
    r.set_input(0, **buttons)
    r.run_frames(frames)
    r.set_input(0)


# =============================================================================
# DoD 1 — boot: textured rotating floor; hero centred + upright; 8-way rotation;
#          stand-and-shoot (facing persists).
# =============================================================================
def test_boots_textured_floor_hero_centred(runner):
    """Boots (SFDB magic) into a TEXTURED Mode 7 arena floor (>=4 distinct
    rendered colours) with the hero OBJ screen-centred (OAM slot 0 at 120,104)
    and UPRIGHT (attr 0x20). Heartbeat advances (the 60fps loop is live)."""
    rom = BUILD / "m7_oshoot.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_oshoot` first"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot (no SFDB)"
    h0 = runner.read_u16(WR, DBG_HEART)
    runner.run_frames(8)
    assert runner.read_u16(WR, DBG_HEART) > h0, "heartbeat not advancing"

    x, y, tile, attr = _oam(runner, HERO_SLOT)
    assert tile == 0 and (x, y) == (HERO_X, HERO_Y), \
        f"hero not centred at boot: {(x, y, tile)}"
    assert attr == HERO_ATTR, f"hero not upright: attr={attr:#04x}"

    shot = str(BUILD / "_oshoot_boot.png")
    runner.take_screenshot(shot)
    n = _distinct_floor_colours(shot)
    assert n >= 4, f"floor not textured ({n} distinct colours; expected >= 4)"


def test_8way_input_rotates_rendered_floor(runner):
    """Each of the 8 D-pad directions snaps R_ANGLE to its compass heading AND
    rotates the rendered floor (a before/after framebuffer diff). The hero stays
    centred + upright throughout. The static-affine plane only moves under input,
    so a diff is a TRUE rotation signal."""
    rom = BUILD / "m7_oshoot.sfc"
    expect = {"up": 0, "right": 192, "down": 128, "left": 64}
    for d, ang in expect.items():
        runner.load_rom(str(rom), run_seconds=0.3)
        base = str(BUILD / f"_oshoot_rot_base_{d}.png")
        runner.take_screenshot(base)
        s_base = _grid_samples(base)
        _hold(runner, 20, **{d: True})
        assert _angle(runner) == ang, \
            f"{d}: R_ANGLE={_angle(runner)} != expected {ang}"
        after = str(BUILD / f"_oshoot_rot_after_{d}.png")
        runner.take_screenshot(after)
        frac = _frac_changed(s_base, _grid_samples(after))
        # 'up' is heading 0 == boot heading -> the floor barely rotates; the other
        # three are large rotations. Assert a real rotation on the non-zero ones.
        if ang != 0:
            assert frac > 0.20, \
                f"{d}: rendered floor did not rotate ({frac:.2%} changed)"
        # hero stays centred + upright
        x, y, _, attr = _oam(runner, HERO_SLOT)
        assert (x, y) == (HERO_X, HERO_Y) and attr == HERO_ATTR, \
            f"{d}: hero drifted/flipped: {(x, y)} attr={attr:#04x}"


def test_facing_persists_when_idle_stand_and_shoot(runner):
    """Model A: the last facing PERSISTS when no direction is held (R_ANGLE does
    not reset to 0 on release) — so stand-and-shoot works. Turn to a heading,
    release, idle, and assert R_ANGLE holds + the player world pos stops moving."""
    rom = BUILD / "m7_oshoot.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    _hold(runner, 10, left=True)              # face left (heading 64)
    a_held = _angle(runner)
    assert a_held == 64, f"left did not snap to heading 64: {a_held}"
    # SETTLE the joypad-latency move before sampling the idle baseline. The
    # harness frees the emulator on its own thread (run_frames == wall-clock
    # sleep) and set_input(0) lands asynchronously, so after _hold releases the
    # D-pad the ROM can still read "left held" in JOY1_CURRENT for ~1 more frame
    # and commit one final move step. Run 2 idle frames here so that latency move
    # is fully absorbed BEFORE px0/py0 is captured — then the assertion below
    # tests the REAL invariant ("once truly idle, the world pos is FROZEN"),
    # not a racy pre-/post-latency sample. (Without this, ~1 seed in 15 sampled
    # px0 one sub-pixel before the last move landed -> a spurious 1px delta.)
    runner.run_frames(2)                      # absorb joypad-latency move
    px0, py0 = _posx(runner), _posy(runner)
    runner.run_frames(40)                     # idle (no input)
    assert _angle(runner) == a_held, \
        f"facing did not persist when idle: {a_held} -> {_angle(runner)}"
    assert (_posx(runner), _posy(runner)) == (px0, py0), \
        "world pos advanced while idle (the player should hover)"


# =============================================================================
# DoD 2 — bullets render ON the floor at multiple headings (rendered ring read);
#          -DBULLET_PROJ_FORWARD FAILS.
# =============================================================================
def _fire_one_and_settle(r, face=None, travel=6):
    """Boot, optionally face a direction, fire one bullet, let it travel `travel`
    frames. Returns the screenshot path."""
    r.load_rom(str(BUILD / "m7_oshoot.sfc"), run_seconds=0.3)
    if face:
        _hold(r, 8, **{face: True})
    r.set_input(0, a=True)
    r.run_frames(1)
    r.set_input(0)
    r.run_frames(travel)
    shot = str(BUILD / f"_oshoot_bullet_{face or 'up'}.png")
    r.take_screenshot(shot)
    return shot


def test_bullets_render_on_floor_multiple_headings(runner):
    """Fire a bullet from MULTIPLE headings (up/right/down/left); each fired
    bullet renders ON the floor — the ring around its DRAWN sprite centre is
    FLOOR-dominated (not WALL). Reads the rendered framebuffer (oracle-free),
    AND the bullet draws in its own yellow palette (>0 bullet-yellow pixels)."""
    rom = BUILD / "m7_oshoot.sfc"
    assert rom.exists(), f"{rom} not built"
    checked = 0
    for face in ("up", "right", "down", "left"):
        shot = _fire_one_and_settle(runner, face)
        assert _distinct_floor_colours(shot) >= 4, \
            f"{face}: floor not textured — capture is not a real render"
        # bullet renders in its yellow palette somewhere on screen
        assert _count_color_total(shot, _is_bullet_yellow) > 0, \
            f"{face}: no bullet-yellow pixels rendered (bullet invisible)"
        on_floor = 0
        for i in range(BULLET_N):
            bx, by, t, a = _bullet_oam(runner, i)
            if by == CULL_Y:
                continue
            nf, nw = _floor_wall_ring(shot, bx + OBJ_HALF, by + OBJ_HALF)
            assert nf > nw, \
                f"{face}: bullet slot {i} centre ({bx + 8},{by + 8}) is ON A WALL " \
                f"(ring floor={nf} wall={nw}) — not rendering on the floor"
            on_floor += 1
        assert on_floor >= 1, f"{face}: no on-screen bullet to check (vacuous)"
        checked += 1
    assert checked == 4


def test_bullet_on_floor_fails_on_forward_build(variants):
    """NON-VACUITY (DoD 2): the -DBULLET_PROJ_FORWARD build (the forward-matrix
    projection) must put a frozen bullet over WORLD-floor onto WALL pixels at a
    rotated angle. We use the FROZEN builds so the bullet stays at a fixed world
    spot while the plane rotates: the FIXED (transpose) build keeps it on FLOOR at
    every angle; the FORWARD build SWIMS it onto a WALL. Proves the floor check is
    a real guard, not a tautology."""
    fixed_swims, fixed_sum = _frozen_glue_swim_count(variants["freeze"])
    fwd_swims, fwd_sum = _frozen_glue_swim_count(variants["freeze_fwd"])
    # FIXED (correct transpose): the world-floor bullet stays on open floor at every
    # heading — its background is never wall-dominated, so the summed wall-fraction
    # over the sweep is ~0.0.
    assert fixed_sum <= 0.30 and fixed_swims == 0, \
        f"FIXED (transpose) frozen bullet swam onto a wall (summed wall-frac " \
        f"{fixed_sum}, swims {fixed_swims}) — the projection is wrong"
    # NON-VACUITY: the FORWARD mis-projection drifts the same world-floor bullet
    # across pillars, accumulating wall coverage over the sweep (summed wall-frac
    # ~2.9..4.0). Gate on the SUM (FORWARD ~3 vs FIXED 0.0 — a jitter-stable margin
    # of ~3, threshold 1.5 ≈ 1.9x the worst FORWARD run), NOT the per-sample peak or
    # the discrete swim count (both have a soft lower tail as cold-boot jitter
    # changes how deeply any single heading overlaps the sparse lattice).
    assert fwd_sum >= 1.5, \
        f"non-vacuity FAILED: the -DBULLET_PROJ_FORWARD build did NOT accumulate " \
        f"wall coverage across the sweep (summed wall-frac {fwd_sum} < 1.5) — the " \
        f"floor test would not reliably catch the defect. The forward build reliably " \
        f"sums ~2.9..4.0; a drop toward marginal is itself the regression this guards."


# =============================================================================
# DoD 3 — a bullet held at a fixed world pos stays glued to the SAME rendered
#          floor spot across an angle sweep (does not swim); control FAILS.
# =============================================================================
def _frozen_glue_swim_count(rom):
    """Boot the FROZEN-bullet ROM, fire one bullet, drive the player ~50px away so
    the frozen bullet sits at a world offset (a screen orbit ~50px radius), then
    sweep the plane through all 8 headings (three passes, 24 samples), and at each
    sample measure the BACKGROUND under the drawn sprite centre (a filled disc of
    background-only pixels, the sprite's own yellow excluded; see _bg_wall_frac_disc).
    Returns (swims, sum_wall_frac): `swims` = samples where the background is
    wall-dominated (a swim onto a lattice pillar); `sum_wall_frac` = the SUM of the
    background wall-fraction over all 24 samples. Reads the rendered framebuffer
    (oracle-free). Deterministic: the FROZEN-bullet build disables enemy waves, so
    nothing perturbs the player/bullet positions.

    `sum_wall_frac` is the ROBUST discriminator (the assertions gate on it): the
    correct TRANSPOSE build keeps the bullet on open floor at EVERY heading → every
    sample reads 0 wall background → sum is EXACTLY 0.0, every run. The FORWARD
    (-DBULLET_PROJ_FORWARD) build's mis-projection drifts the world-floor bullet
    across pillars → sum reliably ~2.9..4.0. Summing over the sweep is jitter-stable
    where the per-sample PEAK and the discrete `swims` COUNT have a soft lower tail
    (cold-boot sub-pixel jitter changes how deeply any single heading overlaps a
    sparse lattice pillar); the TOTAL coverage stays well-separated (0.0 vs ~3).
    (Measured: FWD sum 2.88..4.01 over 15 runs; FIX 0.0 over 10. `swims` is still
    reported for diagnostics but not gated tightly.)"""
    r = MesenRunner()
    swims = 0
    sum_wf = 0.0                             # TOTAL background wall-fraction over the sweep
    sweep_btns = {"up": dict(up=True), "right": dict(right=True),
                  "down": dict(down=True), "left": dict(left=True),
                  "ur": dict(up=True, right=True), "dr": dict(down=True, right=True),
                  "dl": dict(down=True, left=True), "ul": dict(up=True, left=True)}
    # Sweep all 8 headings THREE times (24 samples). The frozen bullet's screen
    # orbit drifts the FORWARD-mis-projected bullet across the lattice pillars while
    # the correct TRANSPOSE bullet stays on open floor at every heading. Driven with
    # DETERMINISTIC frame_step (exactly-n PPU frames, latched input), NOT wall-clock
    # run_frames: run_frames is a time.sleep while the emulator free-runs, so under
    # CPU contention it under-advances and the orbit/heading drifts run-to-run (a
    # flake source for this 24-sample sweep). frame_step advances an exact frame
    # count regardless of host load, so the sweep is load-independent.
    order = ["up", "ur", "right", "dr", "down", "dl", "left", "ul"] * 3
    try:
        r.load_rom(str(rom), run_seconds=0.3)
        with r.frame_stepping():
            r.frame_step(1, a=True)         # fire one (frozen) bullet
            r.frame_step(1)
            r.frame_step(40, left=True)     # drive away -> ~50px orbit radius
            r.frame_step(1)                 # release + settle one frame
            for k in order:
                r.frame_step(2, **sweep_btns[k])   # snap heading (held 2 frames)
                r.frame_step(2)             # release + let OAM presentation catch up
                shot = str(BUILD / f"_oshoot_glue_{Path(rom).stem}.png")
                r.take_screenshot(shot)
                for i in range(BULLET_N):
                    bx, by, t, a = _bullet_oam(r, i)
                    if by == CULL_Y:
                        continue
                    wx, wy = _bul_world(r, i)
                    if _is_wall_px(wx, wy):
                        continue              # bullet genuinely over a world wall
                    # Robust swim metric: the BACKGROUND under the drawn sprite
                    # centre being WALL-dominated — a filled disc of background-only
                    # pixels (the bullet's own yellow excluded) so the round sprite's
                    # footprint does NOT deflate the wall tally. `sum_wf` accumulates
                    # the wall-fraction over all samples (the robust, jitter-stable
                    # signal); `swims` counts samples past the per-sample gate (a soft
                    # diagnostic). See _bg_wall_frac_disc.
                    nf, nw, wfrac = _bg_wall_frac_disc(shot, bx + OBJ_HALF, by + OBJ_HALF)
                    sum_wf += wfrac           # accumulate wall-fraction (robust signal)
                    if nw >= GLUE_SWIM_MIN_W and wfrac >= GLUE_SWIM_MIN_WF:
                        swims += 1            # world-floor bullet rendered on wall
    finally:
        r.stop()
    return swims, round(sum_wf, 2)


def test_bullet_glued_to_floor_through_rotation(variants):
    """DoD 3: a frozen bullet at a fixed WORLD-floor position stays glued to the
    SAME rendered FLOOR spot as the player sweeps the plane through all 8 headings
    — it never swims onto a wall (0 swims). Reads the rendered floor at each
    angle. Non-vacuity is its companion test_bullet_on_floor_fails_on_forward_build
    (the FORWARD build swims). Uses the -DDBG_FROZEN_BULLET build."""
    swims, sum_wf = _frozen_glue_swim_count(variants["freeze"])
    # The robust guard: the background under the correctly-projected bullet is NEVER
    # wall-dominated at ANY heading, so the summed wall-fraction over the whole sweep
    # is ~0.0 (measured exactly 0.0 / 10 runs). swims==0 is the same claim in
    # discrete form; both must hold.
    assert sum_wf <= 0.30, \
        f"SWIM: a world-floor frozen bullet's background went wall-dominated " \
        f"(summed wall-frac {sum_wf} > 0.30) across the rotation sweep — it is not " \
        f"glued to its floor spot"
    assert swims == 0, \
        f"SWIM: a world-floor frozen bullet rendered on a WALL {swims}x across " \
        f"the rotation sweep — it is not glued to its floor spot"


# =============================================================================
# DoD 4 — a bullet KILLS its target enemy at MULTIPLE plane angles (enemy OAM
#          parked AND enemy-red vanishes); -DNO_BULLET_COLLISION -> survives.
# =============================================================================
_HIT_ANGLES = [("up", 0), ("right", 192), ("down", 128), ("left", 64)]


def _kill_at_angle(r, rom, face):
    """Boot, face `face`, let chasers approach, rapid-fire; return (kills_delta,
    enemy_red_total_after). Reads KILLS (a real game counter) + the framebuffer."""
    r.load_rom(str(rom), run_seconds=0.3)
    _hold(r, 8, **{face: True})
    k0 = _kills(r)
    r.run_frames(120)                         # chasers approach
    red_before = _count_color_total(str(_shot(r, "before")), _is_enemy_red)
    for _ in range(40):
        r.set_input(0, a=True)
        r.run_frames(1)
        r.set_input(0, a=False)
        r.run_frames(2)
    return _kills(r) - k0, red_before


def _shot(r, tag):
    p = BUILD / f"_oshoot_kill_{tag}.png"
    r.take_screenshot(str(p))
    return p


def test_bullet_kills_enemy_at_multiple_angles(runner):
    """DoD 4: a fired bullet KILLS its target chaser at MULTIPLE plane rotation
    angles (facing up/right/down/left). KILLS (the world-space-collision counter)
    increments at every angle — proving the hit detection is rotation-invariant.
    Also confirms enemy-red pixels exist before the burst (there WAS a target)."""
    rom = BUILD / "m7_oshoot.sfc"
    assert rom.exists(), f"{rom} not built"
    for face, ang in _HIT_ANGLES:
        dk, red_before = _kill_at_angle(runner, rom, face)
        assert _angle(runner) == ang, \
            f"{face}: did not reach heading {ang} ({_angle(runner)})"
        assert red_before > 0, \
            f"{face}: no enemy-red on screen before firing — no target (vacuous)"
        assert dk >= 1, \
            f"{face} (angle {ang}): bullet did not kill any enemy (KILLS +{dk}) " \
            f"— world-space hit detection failed at this rotation"


def test_no_kills_with_collision_disabled(runner, variants):
    """NON-VACUITY (DoD 4): the -DNO_BULLET_COLLISION build compiles out the
    bullet<->enemy overlap, so bullets pass THROUGH enemies — KILLS stays 0 at
    EVERY angle. Proves the kill test is a real guard, not a tautology."""
    rom = variants["nobulcol"]
    assert rom.exists(), f"{rom} not built"
    for face, ang in _HIT_ANGLES:
        runner.load_rom(str(rom), run_seconds=0.3)
        _hold(runner, 8, **{face: True})
        runner.run_frames(120)
        for _ in range(40):
            runner.set_input(0, a=True)
            runner.run_frames(1)
            runner.set_input(0, a=False)
            runner.run_frames(2)
        assert _kills(runner) == 0, \
            f"non-vacuity FAILED: -DNO_BULLET_COLLISION killed {_kills(runner)} " \
            f"enemies at facing {face} (angle {ang}) — bullets should pass through"


def test_killed_enemy_despawns_oam_and_red_vanishes(runner):
    """DoD 4 (rendered): after a kill burst, the killed enemies' OAM slots are
    PARKED at Y=$F0 and the enemy-red pixel total DROPS (the diamonds vanish from
    the floor). Reads OAM + the framebuffer. KILLS confirms a real kill happened."""
    rom = BUILD / "m7_oshoot.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    runner.run_frames(150)                    # let several chasers crowd in
    before = str(BUILD / "_oshoot_kill_red_before.png")
    runner.take_screenshot(before)
    red0 = _count_color_total(before, _is_enemy_red)
    k0 = _kills(runner)
    assert red0 > 0, "no enemy-red before the burst (nothing to kill)"
    for _ in range(50):
        runner.set_input(0, a=True)
        runner.run_frames(1)
        runner.set_input(0, a=False)
        runner.run_frames(2)
    after = str(BUILD / "_oshoot_kill_red_after.png")
    runner.take_screenshot(after)
    red1 = _count_color_total(after, _is_enemy_red)
    assert _kills(runner) > k0, \
        f"no kills registered during the burst ({k0} -> {_kills(runner)})"
    # at least one enemy slot is parked (a kill freed it) — read OAM directly
    parked = sum(1 for i in range(ENEMY_COUNT)
                 if _enemy_oam(runner, i)[1] == CULL_Y)
    assert parked >= 1, "no enemy OAM slot parked after kills (none despawned)"


# =============================================================================
# DoD 5 — enemy waves: spawn, project red, advance, cull off-screen + pop in;
#          contact knocks the hero back + ticks HITS (visible respawn).
# =============================================================================
def test_enemy_waves_spawn_and_render_red(runner):
    """Over time the wave spawner populates the pool (live enemy count grows) and
    the chasers render in their RED palette on the floor (>0 enemy-red px). Reads
    OAM (live slot count) + the framebuffer (red pixels)."""
    rom = BUILD / "m7_oshoot.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)

    def live_oam():
        return sum(1 for i in range(ENEMY_COUNT)
                   if _enemy_oam(runner, i)[1] != CULL_Y)

    n0 = live_oam()
    runner.run_frames(180)                    # ~3 wave periods (SPAWN_PERIOD=50)
    n1 = live_oam()
    assert n1 > n0, f"waves did not spawn (live enemies {n0} -> {n1})"
    shot = str(BUILD / "_oshoot_waves.png")
    runner.take_screenshot(shot)
    assert _count_color_total(shot, _is_enemy_red) > 0, \
        "no enemy-red pixels rendered (the chasers are invisible)"


def test_enemy_chases_and_projects_on_floor(runner):
    """A chaser CLOSES on the player (its world distance shrinks) and renders on
    the FLOOR at its projected centre (ring floor-dominated). Reads the live world
    mirror (distance) + the framebuffer (on-floor ring)."""
    rom = BUILD / "m7_oshoot.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    runner.run_frames(55)                     # first spawn
    p = (_posx(runner), _posy(runner))

    def nearest():
        best = None
        for i in range(ENEMY_COUNT):
            if _enemy_oam(runner, i)[1] == CULL_Y:
                continue
            ex, ey = _ene_world(runner, i)
            d = math.hypot(ex - p[0], ey - p[1])
            if best is None or d < best[1]:
                best = (i, d)
        return best

    n0 = nearest()
    assert n0 is not None, "no live enemy after the first spawn"
    runner.run_frames(50)
    n1 = nearest()
    assert n1 is not None
    assert n1[1] < n0[1], \
        f"chaser did not close on the player (dist {n0[1]:.0f} -> {n1[1]:.0f})"
    # the chaser renders on the floor at its projected centre
    shot = str(BUILD / "_oshoot_chase_floor.png")
    runner.take_screenshot(shot)
    ex, ey, t, a = _enemy_oam(runner, n1[0])
    if ey != CULL_Y:
        nf, nw = _floor_wall_ring(shot, ex + OBJ_HALF, ey + OBJ_HALF)
        assert nf > nw or nw <= 12, \
            f"chaser sprite centre ({ex + 8},{ey + 8}) is ON A WALL " \
            f"(ring floor={nf} wall={nw}) — not glued to the floor"


def test_contact_knocks_hero_back_and_ticks_hits(runner):
    """A stationary hero gets reached by the chasers: HITS (DBG_HITS) increments
    and the hero world pos RESETS to the spawn cell (visible respawn — the hero
    sprite renders back at screen-centre). Reads the WRAM counter + OAM."""
    rom = BUILD / "m7_oshoot.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _hits(runner) == 0, "HITS not zero at boot"
    runner.run_frames(220)                    # chasers reach the idle hero
    assert _hits(runner) > 0, \
        f"HITS did not increment while chasers closed in ({_hits(runner)})"
    px, py = _posx(runner), _posy(runner)
    assert abs(px - SPAWN_PX[0]) <= 2 and abs(py - SPAWN_PX[1]) <= 2, \
        f"hero not knocked back to spawn {SPAWN_PX}: at {(px, py)}"
    x, y, tile, attr = _oam(runner, HERO_SLOT)
    assert (x, y) == (HERO_X, HERO_Y) and tile == 0 and attr == HERO_ATTR, \
        f"hero sprite not re-centred upright after knockback: {(x, y, tile, attr)}"


# =============================================================================
# DoD 6 — FILM-STRIP: a multi-frame montage of the full loop, committed.
# =============================================================================
def test_film_strip_full_loop(runner):
    """Drive the full loop on the VERIFIED binary — 8-way move (plane rotating),
    bullets streaming across the rotating floor, an enemy hit — capturing frames
    and asserting on the underlying per-frame RENDERED reads, then stitch them
    into ONE montage PNG (the DoD artifact, committed at build/m7_oshoot_filmstrip.png).
    The per-frame asserts: each captured frame is a real textured render; the
    plane orientation changes across the move frames; bullet-yellow appears while
    firing; a kill registers (KILLS rises) by the end."""
    rom = BUILD / "m7_oshoot.sfc"
    assert rom.exists(), f"{rom} not built"

    frames = []
    labels = []
    runner.load_rom(str(rom), run_seconds=0.3)

    def grab(tag):
        p = str(BUILD / f"_oshoot_film_{len(frames):02d}.png")
        runner.take_screenshot(p)
        frames.append(p)
        labels.append(tag)
        return p

    # 0: boot
    g0 = grab("boot")
    assert _distinct_floor_colours(g0) >= 4, "boot frame not a textured render"
    base_samples = _grid_samples(g0)

    # 1-2: 8-way move (the plane rotates as the player turns + drives)
    _hold(runner, 18, right=True)
    g1 = grab("move-right")
    assert _frac_changed(base_samples, _grid_samples(g1)) > 0.20, \
        "plane did not rotate/scroll on the move frame"
    _hold(runner, 18, down=True)
    grab("move-down")

    # 3: bullets streaming across the rotating floor
    for _ in range(5):
        runner.set_input(0, a=True)
        runner.run_frames(1)
        runner.set_input(0, a=False)
        runner.run_frames(2)
    g3 = grab("bullets")
    assert _count_color_total(g3, _is_bullet_yellow) > 0, \
        "no bullet-yellow on the bullets frame"

    # 4: an enemy hit (let chasers approach + rapid-fire until a kill registers)
    k0 = _kills(runner)
    runner.run_frames(120)
    for _ in range(60):
        runner.set_input(0, a=True)
        runner.run_frames(1)
        runner.set_input(0, a=False)
        runner.run_frames(2)
    g4 = grab("enemy-hit")
    assert _kills(runner) > k0, \
        f"no kill registered for the film-strip hit frame ({k0} -> {_kills(runner)})"

    dest = str(BUILD / "m7_oshoot_filmstrip.png")
    out = film_strip(frames, dest, labels=labels, cols=len(frames))
    assert Path(out).exists(), "film strip montage not written"
    # Also refresh the COMMITTED DoD artifact (build/ is gitignored in the kit;
    # the tracked copy lives under docs/ so it ships with the branch).
    tracked = ROOT / "docs" / "audit" / "m7_oshoot_coldstart" / "m7_oshoot_filmstrip.png"
    if tracked.parent.exists():
        import shutil
        shutil.copyfile(out, tracked)
    print(f"\nDoD #6 film strip: {out} (+ committed copy {tracked}) "
          f"({len(frames)} frames: {labels})")
