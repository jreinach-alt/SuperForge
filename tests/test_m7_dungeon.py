"""Acceptance gate for the m7_dungeon rail.

m7_dungeon is a Mode 7 rotating-floor top-down dungeon: the floor is the Mode 7
BG, scaled+rotated by a single uniform affine matrix; the hero is an OBJ pinned
at screen centre while the world spins + scrolls underneath (TANK CONTROLS).

What these checks cover, all on REAL rendered/hardware output (framebuffer pixels,
OAM/CGRAM bytes, recorded WAV — never a proxy game variable):

  TANK CONTROLS
  - Boots (SFDB magic) into a TEXTURED Mode 7 floor (>= 4 distinct colours).
  - The hero OBJ stays screen-centred + upright across turning and driving.
  - LEFT vs RIGHT give OPPOSITE heading deltas AND the rendered floor rotates the
    matching way; B/UP drive advances the world pos + scrolls the floor, Y/DOWN
    reverses, release coasts to a stop.

  WORLD-SPACE WALL COLLISION
  - dungeon_terrain.bin (128x128 byte LUT, 1=solid/0=floor) is emitted from the
    SAME is_wall() predicate that paints the wall art (make_dungeon.py), so it is
    the GROUND-TRUTH oracle (mirrored in Python below). The hero footprint NEVER
    occupies a solid cell: driving into a wall stops adjacent; a diagonal push
    slides along the unblocked axis; at the speed cap no frame tunnels.
  - Negative control: a -DNO_COLLISION variant WALKS THROUGH walls — proving the
    collision assertion is not vacuous.

  ENEMIES (project + cull + patrol + contact)
  - Enemies live in world space and project onto the rotating floor, staying glued
    to their tile under rotation + translation and culling when off-screen; they
    patrol their corridors (wall-turn) and knock the hero back on contact with a
    screen flash. Rendered-floor checks confirm each enemy sits on FLOOR pixels
    (the forward-matrix control build FAILS them).

The debug-region mirrors (the WRAM the ROM writes each frame: R_POSX/R_POSY world
px, R_ANGLE heading, DBG_ENE_* live enemy pos, DBG_HITS) are read to SEQUENCE
captures and to know where things are; the rotation / scroll / sprite is always
confirmed on the framebuffer.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

# debug-region mirrors (main.asm writes these every frame; SEQUENCE + direction)
DBG_HEART = 0xE010   # frame counter
DBG_POSX  = 0xE012   # world x integer px
DBG_POSY  = 0xE014   # world y integer px
DBG_ANGLE = 0xE016   # heading (low byte 0..255)

# S4 per-enemy debug mirrors (main.asm DBG_ENE_BASE; 8 bytes each):
#   +0 world_x  +2 world_y  +4 projected screen_x  +6 projected screen_y
# the world (x,y) at +0/+2 is now the LIVE patrol position (enemies MOVE);
# tests read it per frame via _enemy_mirror, NOT the static seed table below.
DBG_ENE_BASE = 0xE020
DBG_ENE_STRIDE = 8
ENEMY_COUNT = 3
# S5 enemy SPAWN-SEED positions (verbatim mirror of main.asm enemy_world ROM
# table) — the boot seed only. After boot the enemies PATROL, so the live pos
# (read via _enemy_mirror) drifts from these seeds. SPREAD along the START->GOAL
# route so culling-by-visibility is exercised. E2 was RELOCATED off the old
# goal-adjacent cell (356,316) to the pre-exit row (316,276) so the GOAL is safe.
ENEMY_SEED = [(156, 116), (276, 196), (316, 276)]
# S5 per-enemy patrol axis (main.asm dispatch): 'x' = row corridor, 'y' = column.
ENEMY_AXIS = ['x', 'y', 'x']
# S5 contact/HITS mirrors + persistent patrol state (main.asm).
DBG_HITS = 0xE01C    # hero-enemy contact (knockback) counter
DBG_GRACE = 0xE01E   # post-respawn grace countdown (frames left)
ENE_DIR_BASE = 0xE040  # ENEMY_COUNT*2: signed patrol step direction per enemy
PATROL_SPEED = 1     # main.asm PATROL_SPEED (world px/frame per enemy)
CONTACT_HALF = 4     # main.asm CONTACT_HALF (8x8 world contact box)
GRACE_FRAMES = 40    # main.asm GRACE_FRAMES (post-respawn contact suppression)
DBG_BLOCK = 0xE018   # count of blocked axis-steps (collision proof)
DBG_PAUSED = 0xE048  # main.asm: 0 = running, 1 = paused (START toggles)

# --- S3 collision ground-truth oracle. MIRRORS make_dungeon.py's is_wall() (the
#     SINGLE source of truth for both the wall art and dungeon_terrain.bin), so a
#     mismatch here means the ROM's LUT diverged from the art. The maze layout +
#     parameters below are a VERBATIM mirror of make_dungeon.py's MAZE/CELL/WALL_T/
#     ORIGIN_* — keep them in lockstep. ---
HERO_HALF = 4        # main.asm HERO_HALF: footprint is an 8px box (near-4 .. far+3)

# verbatim mirror of make_dungeon.MAZE (the authored maze)
_MAZE = [
    "#########",
    "#S....#D#",
    "#####.#.#",
    "#D..#.#.#",
    "###.#.#.#",
    "#...#...#",
    "#.#####.#",
    "#.....#G#",
    "#########",
]
_CELL = 3            # floor tiles per cell edge   (== make_dungeon.CELL)
_WALL_T = 2          # wall thickness in tiles      (== make_dungeon.WALL_T)
_PITCH = _CELL + _WALL_T
_ORIGIN_TX = 6       # == make_dungeon.ORIGIN_TX
_ORIGIN_TY = 6       # == make_dungeon.ORIGIN_TY
_ROWS = len(_MAZE)
_COLS = len(_MAZE[0])


def _mcell(cx, cy):
    """Logical cell char normalised to '#' (wall) / '.' (any walkable)."""
    if 0 <= cy < _ROWS and 0 <= cx < _COLS:
        return '#' if _MAZE[cy][cx] == '#' else '.'
    return '#'


def _is_wall_tile(tx, ty):
    """Ground-truth wall predicate — a verbatim mirror of make_dungeon.is_wall."""
    rx, ry = tx - _ORIGIN_TX, ty - _ORIGIN_TY
    if rx < 0 or ry < 0:
        return True
    cx, sx = divmod(rx, _PITCH)
    cy, sy = divmod(ry, _PITCH)
    if cx >= _COLS or cy >= _ROWS:
        return True
    if _mcell(cx, cy) == '#':
        return True
    in_bx = sx < _WALL_T
    in_by = sy < _WALL_T
    if not in_bx and not in_by:
        return False
    if in_bx and not in_by:
        return _mcell(cx - 1, cy) == '#'
    if in_by and not in_bx:
        return _mcell(cx, cy - 1) == '#'
    return not (_mcell(cx - 1, cy) != '#' and _mcell(cx, cy - 1) != '#'
                and _mcell(cx - 1, cy - 1) != '#')


def _cell_center_tile(ch):
    """World tile centre of the floor body of the cell tagged `ch`."""
    for cy in range(_ROWS):
        for cx in range(_COLS):
            if _MAZE[cy][cx] == ch:
                return (_ORIGIN_TX + cx * _PITCH + _WALL_T + _CELL // 2,
                        _ORIGIN_TY + cy * _PITCH + _WALL_T + _CELL // 2)
    return None


# maze START / GOAL world pixel centres (for the route test)
_S_TILE = _cell_center_tile('S')
_G_TILE = _cell_center_tile('G')
GOAL_PX = (_G_TILE[0] * 8 + 4, _G_TILE[1] * 8 + 4)
SPAWN_PX = (_S_TILE[0] * 8 + 4, _S_TILE[1] * 8 + 4)


def _is_wall_px(px, py):
    """Is the world PIXEL (px,py) inside a solid wall cell? (world wraps 0..1023)."""
    return _is_wall_tile((px & 1023) >> 3, (py & 1023) >> 3)


def _footprint_solid(px, py):
    """Does the hero's 8px-box footprint at world centre (px,py) touch ANY solid
    cell? Samples the four corners (centre +/- HERO_HALF, far edge -1) the SAME way
    main.asm's footprint_solid does — this is the 'hero is in a wall' check."""
    for dx in (-HERO_HALF, HERO_HALF - 1):
        for dy in (-HERO_HALF, HERO_HALF - 1):
            if _is_wall_px(px + dx, py + dy):
                return True
    return False

# OAM slot 0 = hero (SPR_ORDER_MODE=2 stable). main.asm HERO_X/Y = 120,104
HERO_SLOT = 0
HERO_X = 120         # 128 - 8 (16x16 centred at screen 128,112)
HERO_Y = 104         # 112 - 8
HERO_ATTR = 0x20     # priority 2 (no flips) -> hero stays upright


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


@pytest.fixture(scope="module")
def variants():
    """Build the S3 -D variant ROMs (the generic make rule can't pass -D):
      build/m7_dungeon_nocol.sfc  (-DNO_COLLISION=1) — the negative control.
      build/m7_dungeon_far.sfc    (-DSPAWN_TX=72 -DSPAWN_TY=40) — a far room.
    Returns the dict of {name: rom_path}. Skips if the toolchain is unavailable."""
    import subprocess
    script = ROOT / "templates" / "m7_dungeon" / "build_m7_dungeon_variants.sh"
    assert script.exists(), f"{script} missing"
    res = subprocess.run(["bash", str(script)], cwd=str(ROOT),
                         capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"variant build failed (toolchain?):\n{res.stderr}")
    return {
        "nocol": BUILD / "m7_dungeon_nocol.sfc",
        "far": BUILD / "m7_dungeon_far.sfc",
        "goalspawn": BUILD / "m7_dungeon_goalspawn.sfc",
        # non-vacuity control: OLD forward-matrix projection (enemies drift
        # onto the WALLS under rotation) — the rendered-floor test must FAIL on it.
        "projfwd": BUILD / "m7_dungeon_projfwd.sfc",
        # sprite-size non-vacuity control: OLD 32x32 size bit (bit7 SET) on the hero
        # + enemies. The 32x32 hero reads tile 32 (enemy CHR) into its lower-left
        # quadrant -> a phantom diamond (the demon CHR rendered in the KNIGHT hero
        # palette = grey/bone pixels below the hero). The sprite-size regression test
        # must FAIL on it (size bit SET + hero-palette pixels below the hero).
        "bigspr": BUILD / "m7_dungeon_bigspr.sfc",
        # enemy-colour non-vacuity control: -DENEMY_MISCOLOR renders the demon in a
        # COOL (floor-blue) OBJ palette, so the enemy-warm band reads 0 -> proves the
        # enemy colour tests are not vacuous (see test_enemy_colour_regression_*).
        "miscolor": BUILD / "m7_dungeon_miscolor.sfc",
    }


def _oam(runner, slot):
    b = runner.read_bytes(OAM, slot * 4, 4)
    return b[0], b[1], b[2], b[3]   # x, y, tile, attr


def _angle(runner):
    return runner.read_u16(WR, DBG_ANGLE) & 0xFF


def _posx(runner):
    return runner.read_u16(WR, DBG_POSX) & 0xFFFF


def _posy(runner):
    return runner.read_u16(WR, DBG_POSY) & 0xFFFF


def _blocked(runner):
    return runner.read_u16(WR, DBG_BLOCK) & 0xFFFF


def _live_world(runner, i):
    """Enemy i's LIVE world (x,y) — the patrol position the ROM updates each frame
    (DBG_ENE_BASE +0/+2). S5 enemies MOVE, so every projection/cull oracle reads
    THIS per frame instead of the static seed table."""
    base = DBG_ENE_BASE + i * DBG_ENE_STRIDE
    return (runner.read_u16(WR, base + 0) & 0xFFFF,
            runner.read_u16(WR, base + 2) & 0xFFFF)


def _hits(runner):
    return runner.read_u16(WR, DBG_HITS) & 0xFFFF


def _grace(runner):
    return runner.read_u16(WR, DBG_GRACE) & 0xFFFF


def _paused(runner):
    return runner.read_u16(WR, DBG_PAUSED) & 0xFFFF


def _hold(runner, frames, **buttons):
    """Latch the given buttons and advance `frames` frames, then release."""
    runner.set_input(0, **buttons)
    runner.run_frames(frames)
    runner.set_input(0)


# The boot music streams to the SPC over the first ~25 frames; while it does, the
# heavy Mode 7 frame can skip a frame (a sub-perceptible boot-second stutter, the
# cost of booting straight into gameplay instead of a title screen). A drive that
# counts exact frames must start AFTER that settles: from a mid-frame wall-clock
# boot the transient desyncs it (a held button latched N vs N+1 times, or a few
# skipped drive frames). Frame-stepping past the load — with NO input, so the
# hero just hovers at spawn — makes the start state deterministic (spawn, angle 0)
# on a clean 60fps budget, independent of the wall-clock boot phase. This is a
# determinism fix, not a tolerance change: the drive assertions are unchanged.
_AUDIO_SETTLE_FRAMES = 45


def _boot_settled(runner, rom):
    """load_rom + frame-step past the song-load transient (see _AUDIO_SETTLE_FRAMES)
    so a following exact frame-count drive is deterministic. No input during the
    settle, so the world stays at the spawn state."""
    runner.load_rom(str(rom), run_seconds=0.3)
    runner.run_frames(_AUDIO_SETTLE_FRAMES)


def _grid_samples(path, step=8):
    """Return the RGB of a coarse grid of framebuffer points, EXCLUDING the
    central hero box, so comparisons reflect the FLOOR, not the (static) hero."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    out = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            sx, sy = x * 256 // w, y * 224 // h     # to 256x224 logical space
            if 112 <= sx <= 144 and 96 <= sy <= 128:
                continue                            # skip the centred hero box
            out.append(px[x, y])
    return out


def _distinct_floor_colours(path, step=4):
    """Count distinct quantised colours in the framebuffer (hero box excluded) —
    the textured-plane check. Quantise to 5 bits/channel (SNES native)."""
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


def _frac_changed(a, b, thresh=24):
    """Fraction of grid samples whose colour changed by > thresh (sum-of-abs) —
    a render-output diff between two floor captures."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    diff = sum(1 for i in range(n)
               if sum(abs(a[i][c] - b[i][c]) for c in range(3)) > thresh)
    return diff / n


def _frame_brightness(path, step=8):
    """Mean per-channel brightness of a coarse framebuffer grid. The get-hit flash
    dims the WHOLE screen (INIDISP brightness), so a dark frame here is the rendered
    proof the hit fired — a non-vacuous, whole-view change (unlike the hero OAM,
    which is pinned at centre and never moves)."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    tot = n = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = px[x, y]
            tot += r + g + b
            n += 1
    return tot / (3 * n) if n else 0.0


# The enemy body colour rendered on screen: the dungeonSprites DEMON's orange-red
# body (CC0 pack sprite; enemy.inc palette body ~ (224,104,72), rendered ~
# (231,107,74)). We match a WARM/BRIGHT cluster (Wave-D dressing retune) whose
# key separator is BRIGHTNESS: the demon body is r>=205, brighter than any brick
# wall tone (WALL_LT rendered ~ (189,123,82)), so the band accepts the demon and
# REJECTS the warm brick walls, the cool flagstone floor, the grey/white knight
# hero, and the green goal. This reads the rendered FRAMEBUFFER (pixels), not OAM
# — so an invisible / wrong-palette sprite cannot pass (see the -DENEMY_MISCOLOR
# non-vacuity control, which renders the enemy cool and reads 0 here).
_ENEMY_RED = (224, 104, 72)


def _is_enemy_red(rgb):
    """True iff rgb is the enemy DEMON's bright warm body (rendered ~ (231,107,74)).
    Retuned on the emulator (measured rendered values) to separate the demon from
    the WARM brick wall by BRIGHTNESS: r>=205 clears the demon (231) but rejects
    every wall tone (WALL_LT 189, WALL 148, WALL_MO 107); g<=130 rejects the bone
    highlight; b<=110 + r-b>=120 reject the cool floor + the grey knight hero. Only
    a real demon-body pixel passes. Non-vacuity: -DENEMY_MISCOLOR reads 0 (see
    test_enemy_colour_regression_fails_on_miscolor)."""
    r, g, b = rgb
    return r >= 205 and g <= 130 and b <= 110 and (r - b) >= 120


def _count_enemy_red_near(path, cx, cy, radius=12):
    """Count enemy-red framebuffer pixels within `radius` (in 256x224 logical
    space) of screen centre (cx,cy). Reads the rendered image — the OUTPUT."""
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
            if _is_enemy_red(px[x, y]):
                n += 1
    return n


def _count_enemy_red_total(path):
    """Total enemy-red pixels in the whole rendered frame (non-vacuity probe:
    0 on the broken build, >0 once the enemy actually renders)."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    return sum(1 for y in range(h) for x in range(w) if _is_enemy_red(px[x, y]))


# --- RENDERED-FLOOR classification (the forward-matrix-projection binding guard). These read the
#     ACTUAL rendered Mode 7 plane and tell FLOOR from WALL so we can assert each
#     enemy sits on the FLOOR under rotation — an oracle-FREE check (it does not
#     reuse the projection formula, so it catches a wrong-direction projection
#     that the OAM-vs-_project oracle and the distance-only orbit check both miss).
#     Wave-D dressing retune — bands MEASURED on the emulator across angles
#     0/40/96/160/220 for the camelot-themed stone palette:
#       wall  = warm brick, rendered WALL_LT (189,123,82) / WALL (148,90,57) /
#               WALL_MO mortar (107,66,41): warm (r>b+40), r in (100,210), g<130, b<95
#       floor = cool flagstone, rendered FLOOR_B (74,90,132) / FLOOR_A (33,41,66) /
#               FLOOR_M seam (49,66,99): bluish/dark, b >= r, NOT wall
#     The r<210 ceiling keeps the BRIGHT demon enemy (r~231) out of the wall band.
def _is_wall_px_rgb(rgb):
    """Rendered WALL (warm brick) pixel test — accepts every brick tone (body,
    highlight, mortar) and rejects the cool floor, the bright demon, the grey hero."""
    r, g, b = rgb
    return 100 < r < 210 and g < 130 and b < 95 and r > b + 40


def _is_floor_px_rgb(rgb):
    """Rendered FLOOR (cool flagstone) pixel test — bluish/dark, and NOT wall."""
    r, g, b = rgb
    return (b >= r - 10) and not _is_wall_px_rgb(rgb)


def _floor_wall_ring(path, cx, cy, rmin=7, rmax=11):
    """Sample a ring (radius rmin..rmax px, 256x224 logical) around the enemy's
    drawn sprite CENTRE (cx,cy) and count FLOOR vs WALL rendered pixels. Returns
    (n_floor, n_wall, n_total). Reads the framebuffer — the actual OUTPUT, with NO
    reference to the projection formula."""
    import math as _m
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    nf = nw = nt = 0
    for adeg in range(0, 360, 12):
        for rad in range(rmin, rmax + 1):
            sx = cx + rad * _m.cos(_m.radians(adeg))
            sy = cy + rad * _m.sin(_m.radians(adeg))
            ix = int(sx * w / 256)
            iy = int(sy * h / 224)
            if 0 <= ix < w and 0 <= iy < h:
                nt += 1
                rgb = px[ix, iy]
                if _is_wall_px_rgb(rgb):
                    nw += 1
                elif _is_floor_px_rgb(rgb):
                    nf += 1
    return nf, nw, nt


# =============================================================================
# Done-condition 1 — boots into a TEXTURED Mode 7 floor.
# =============================================================================
def test_boots_into_textured_mode7_floor(runner):
    """The ROM boots (SFDB magic) and renders a TEXTURED Mode 7 floor: the
    framebuffer (hero box excluded) shows >= 4 distinct colours — a real textured
    plane (floor checker + wall bands), not a flat fill or a black band. With NO
    input the hero hovers, so the heartbeat still advances (the game loop runs)."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    runner.load_rom(str(rom), run_seconds=0.3)

    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot (no SFDB magic)"
    h0 = runner.read_u16(WR, DBG_HEART)
    runner.run_frames(8)
    assert runner.read_u16(WR, DBG_HEART) > h0, "heartbeat not advancing"

    shot = "/tmp/m7dungeon_boot.png"
    runner.take_screenshot(shot)
    n = _distinct_floor_colours(shot)
    assert n >= 4, f"floor not textured (only {n} distinct colours; expected >= 4)"


# =============================================================================
# Done-condition 2 — hero OBJ is screen-centred + upright and STAYS so under input.
# =============================================================================
def test_hero_is_screen_centred_and_stays_centred(runner):
    """OAM slot 0 (the hero) sits at the centred box (120,104) — a 16x16 sprite
    centred on screen (128,112), UPRIGHT (no H/V flip) — and STAYS there while the
    player TURNS and DRIVES the floor under it. Read from the OAM bytes (the
    hardware sprite table)."""
    rom = BUILD / "m7_dungeon.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)

    x, y, tile, attr = _oam(runner, HERO_SLOT)
    assert tile == 0, f"slot 0 is not the hero tile 0: {(x, y, tile, attr)}"
    assert (x, y) == (HERO_X, HERO_Y), f"hero not centred at boot: {(x, y)}"
    assert attr == HERO_ATTR, f"hero not upright (flip bits set): attr={attr:#04x}"

    # stays centred + upright across a mix of driving inputs (turn, fwd, reverse)
    for buttons in ({"left": True}, {"right": True}, {"b": True}, {"y": True},
                    {"up": True}, {"down": True}):
        runner.set_input(0, **buttons)
        runner.run_frames(20)
        x, y, tile, attr = _oam(runner, HERO_SLOT)
        assert (x, y) == (HERO_X, HERO_Y), \
            f"hero drifted off centre under input {buttons}: {(x, y)}"
        assert attr == HERO_ATTR, \
            f"hero not upright under input {buttons}: attr={attr:#04x}"
    runner.set_input(0)


# =============================================================================
# Done-condition 3 — TURN: LEFT vs RIGHT give OPPOSITE angle deltas + the floor
# rotates the corresponding way (rendered).
# =============================================================================
def test_turn_left_right_opposite_and_floor_rotates(runner):
    """Holding LEFT vs RIGHT from the same start produces OPPOSITE heading deltas
    (the angle mirror) AND the rendered floor orientation rotates each way. The
    floor diff is read from the framebuffer (hero box excluded); the angle mirror
    only proves the heading moved + the directions are opposite."""
    rom = BUILD / "m7_dungeon.sfc"

    # --- baseline orientation at angle 0 (no input) ---
    _boot_settled(runner, rom)      # frame-step past the song load -> deterministic drive
    assert _angle(runner) == 0, "spawn heading should be 0"
    base = "/tmp/m7dungeon_turn_base.png"
    runner.take_screenshot(base)
    s_base = _grid_samples(base)

    # --- LEFT: angle increases ---
    _hold(runner, 40, left=True)
    a_left = _angle(runner)
    left = "/tmp/m7dungeon_turn_left.png"
    runner.take_screenshot(left)
    s_left = _grid_samples(left)
    frac_left = _frac_changed(s_base, s_left)

    # --- RIGHT from a fresh spawn: angle decreases (opposite sign) ---
    _boot_settled(runner, rom)      # same deterministic settle as the LEFT drive
    _hold(runner, 40, right=True)
    a_right = _angle(runner)

    # opposite deltas about 0: LEFT -> +d, RIGHT -> -d (== 256-d). Same magnitude.
    d_left = a_left % 256
    d_right = (-a_right) % 256
    assert d_left > 0, f"LEFT did not turn the heading: angle={a_left}"
    assert d_right > 0, f"RIGHT did not turn the heading: angle={a_right}"
    assert d_left == d_right, \
        f"LEFT/RIGHT not opposite-equal: +{d_left} vs -{d_right}"

    # the rendered floor visibly rotated under the LEFT turn (orientation change)
    assert frac_left > 0.30, \
        f"floor did not visibly rotate under LEFT turn: only {frac_left:.2%} changed"


# =============================================================================
# Done-condition 4 — FORWARD/REVERSE: B/UP advances world pos along the facing
# vector + the floor scrolls; Y/DOWN reverses; release -> hover.
# =============================================================================
def test_forward_reverse_drive_and_release_hovers(runner):
    """From the spawn heading (0), B advances the world position and the floor
    scrolls (rendered); Y moves it the OPPOSITE way. Release -> the speed decays
    and the world position STOPS advancing (coast to hover). World direction is
    read from the world-pos mirror; the scroll itself is confirmed on the
    framebuffer."""
    rom = BUILD / "m7_dungeon.sfc"

    # --- B forward from angle 0 (facing vector is the Y axis here) ---
    runner.load_rom(str(rom), run_seconds=0.3)
    py0 = _posy(runner)
    base = "/tmp/m7dungeon_drive_base.png"
    runner.take_screenshot(base)
    s_base = _grid_samples(base)

    _hold(runner, 40, b=True)
    py_fwd = _posy(runner)
    fwd = "/tmp/m7dungeon_drive_fwd.png"
    runner.take_screenshot(fwd)
    s_fwd = _grid_samples(fwd)

    # signed delta on the 1024px wrap plane: forward steps it one way
    d_fwd = (py_fwd - py0)
    if d_fwd > 512:
        d_fwd -= 1024
    if d_fwd < -512:
        d_fwd += 1024
    assert d_fwd != 0, "B did not advance the world position"
    # the floor scrolled (rendered content changed) because the pivot moved
    frac_fwd = _frac_changed(s_base, s_fwd)
    assert frac_fwd > 0.20, \
        f"floor did not scroll under forward drive: only {frac_fwd:.2%} changed"

    # --- Y reverse from a fresh spawn: world pos moves the OPPOSITE way ---
    runner.load_rom(str(rom), run_seconds=0.3)
    py0r = _posy(runner)
    _hold(runner, 40, y=True)
    py_rev = _posy(runner)
    d_rev = (py_rev - py0r)
    if d_rev > 512:
        d_rev -= 1024
    if d_rev < -512:
        d_rev += 1024
    assert d_rev != 0, "Y did not move the world position"
    assert (d_fwd > 0) != (d_rev > 0), \
        f"B and Y moved the same way: fwd={d_fwd}, rev={d_rev}"

    # --- release -> coast to hover: world pos stops advancing ---
    runner.load_rom(str(rom), run_seconds=0.3)
    runner.set_input(0, b=True)
    runner.run_frames(40)
    runner.set_input(0)           # release throttle
    runner.run_frames(60)         # let speed bleed fully to 0
    p_a = _posy(runner)
    runner.run_frames(30)
    p_b = _posy(runner)
    assert p_a == p_b, \
        f"world pos still advancing after release (no hover): {p_a} -> {p_b}"


# =============================================================================
# UP/DOWN alias B/Y (the dungeon throttle accepts the D-pad too).
# =============================================================================
def test_up_down_alias_forward_reverse(runner):
    """UP throttles forward (same world direction as B); DOWN reverses (same as
    Y). World direction read from the world-pos mirror."""
    rom = BUILD / "m7_dungeon.sfc"

    def drive_dy(**buttons):
        runner.load_rom(str(rom), run_seconds=0.3)
        py0 = _posy(runner)
        _hold(runner, 40, **buttons)
        dy = _posy(runner) - py0
        if dy > 512:
            dy -= 1024
        if dy < -512:
            dy += 1024
        return dy

    dy_b = drive_dy(b=True)
    dy_up = drive_dy(up=True)
    dy_y = drive_dy(y=True)
    dy_down = drive_dy(down=True)

    assert (dy_b > 0) == (dy_up > 0) and dy_up != 0, \
        f"UP did not match B forward: B={dy_b}, UP={dy_up}"
    assert (dy_y > 0) == (dy_down > 0) and dy_down != 0, \
        f"DOWN did not match Y reverse: Y={dy_y}, DOWN={dy_down}"
    assert (dy_up > 0) != (dy_down > 0), \
        f"UP and DOWN moved the same way: UP={dy_up}, DOWN={dy_down}"


# =============================================================================
# S3 helpers — drive into walls and verify the footprint never enters a solid
# cell, reading the WORLD-POS mirror against the ground-truth LUT oracle.
# =============================================================================
def _turn_to(runner, frames, direction):
    """Hold a turn `frames` frames to reach a heading, then release."""
    if frames:
        runner.set_input(0, **{direction: True})
        runner.run_frames(frames)
        runner.set_input(0)


def _drive_scan_frames(runner, frames, step=2, **buttons):
    """Hold `buttons`, advancing `frames` frames in small chunks; after EACH chunk
    read the world pos and assert the hero footprint is NOT inside a solid cell.
    Returns the count of frame-chunks where the footprint was solid (== 0 means
    the hero never tunneled into a wall). Releases input at the end."""
    bad = 0
    runner.set_input(0, **buttons)
    done = 0
    while done < frames:
        n = min(step, frames - done)
        runner.run_frames(n)
        done += n
        if _footprint_solid(_posx(runner), _posy(runner)):
            bad += 1
    runner.set_input(0)
    return bad


# =============================================================================
# blocked from MULTIPLE FACINGS at MULTIPLE LOCATIONS:
# drive forward into a wall; the hero stops adjacent and the footprint NEVER
# enters a solid cell (frames_in_wall == 0), checked against the LUT oracle.
# =============================================================================
def test_collision_blocks_from_all_facings(runner):
    """From the spawn room, rotate to several headings (cardinals + diagonals) and
    drive FORWARD into a wall. At every sampled frame the hero's 8px footprint must
    be CLEAR of solid cells (ground-truth LUT), it must end adjacent to a wall, and
    the ROM's blocked-count must register the collision. The terrain LUT is the
    oracle (a Python mirror of make_dungeon.is_wall)."""
    rom = BUILD / "m7_dungeon.sfc"
    # 8 facings: cardinals + diagonals (heading units 0..255, ~32 = 45deg).
    for turn in (0, 32, 64, 96, 128, 160, 192, 224):
        runner.load_rom(str(rom), run_seconds=0.3)
        # spawn footprint must itself be clear (sanity: the oracle agrees w/ spawn)
        assert not _footprint_solid(_posx(runner), _posy(runner)), \
            f"spawn footprint is solid per oracle — bad spawn/oracle"
        _turn_to(runner, turn, "left")
        bad = _drive_scan_frames(runner, 260, b=True)
        px, py = _posx(runner), _posy(runner)
        assert bad == 0, \
            f"facing turn={turn}: hero footprint entered a wall on {bad} frames " \
            f"(final pos {(px, py)})"
        assert not _footprint_solid(px, py), \
            f"facing turn={turn}: final footprint solid at {(px, py)}"
        assert _blocked(runner) > 0, \
            f"facing turn={turn}: drove into a wall but blocked-count stayed 0"
        # ended FLUSH against a wall: a solid cell lies just beyond the footprint.
        # The hero halts within one step (<=1.25px) of the wall, so a solid cell
        # must lie within HERO_HALF + 2 px of the centre (footprint near-edge to the
        # wall plus a step's worth of slop). Without collision it would be deep
        # inside — this confirms it stopped AT the wall, not short of it.
        margin = HERO_HALF + 2
        adj = any(_is_wall_px(px + dx, py + dy)
                  for dx in range(-margin, margin + 1)
                  for dy in range(-margin, margin + 1))
        assert adj, f"facing turn={turn}: hero not flush against a wall at {(px, py)}"


# =============================================================================
# collision holds in a FAR room (not just at spawn).
# =============================================================================
def test_collision_blocks_in_far_room(runner, variants):
    """The far-room variant (-DSPAWN_TX=43 -DSPAWN_TY=20) spawns far from the
    origin; collision must hold there too — the footprint never enters a solid cell
    and the blocked-count registers. Proves collision is world-position-general."""
    rom = variants["far"]
    assert rom.exists(), f"{rom} not built"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert not _footprint_solid(_posx(runner), _posy(runner)), "far spawn is solid"
    for turn in (0, 64, 128, 192):
        _boot_settled(runner, rom)  # frame-step past the song load -> deterministic drive
        _turn_to(runner, turn, "left")
        bad = _drive_scan_frames(runner, 260, b=True)
        px, py = _posx(runner), _posy(runner)
        assert bad == 0, f"far room turn={turn}: footprint in wall {bad} frames"
        assert _blocked(runner) > 0, f"far room turn={turn}: no collision registered"


# =============================================================================
# SLIDE: push diagonally into an axis-aligned wall; the
# UNBLOCKED axis still advances (the hero slides along, doesn't dead-stop).
# =============================================================================
def test_diagonal_push_slides_along_wall(runner):
    """Drive forward at a SHALLOW heading into the top (axis-aligned) wall: the Y
    component blocks (hero pins against the wall) but the X component keeps
    advancing — the hero SLIDES along the wall instead of dead-stopping at the
    corner. Read from world-pos deltas: once Y is pinned, X still changes."""
    rom = BUILD / "m7_dungeon.sfc"
    # The maze START corridor runs EAST along the top row with a long axis-aligned
    # wall above it — the clean slide case. Setup: drive EAST into the corridor,
    # then face heading 240 (North tilted toward East) so forward = mostly -Y (into
    # the top wall) with a steady +X component. The Y component pins on the wall;
    # the +X component must keep advancing along the open corridor (slide).
    runner.load_rom(str(rom), run_seconds=0.3)
    _turn_to(runner, 64, "right")          # angle 192 = East (corridor heading)
    runner.set_input(0, b=True)
    runner.run_frames(35)                  # drive a bit into the East corridor
    runner.set_input(0)
    _turn_to(runner, 64, "left")           # back to angle 0 = North
    _turn_to(runner, 16, "right")          # -> angle 240 (North tilted East)
    # phase 1: drive until pinned against the top wall (Y stops decreasing)
    runner.set_input(0, b=True)
    runner.run_frames(60)
    x_mid, y_mid = _posx(runner), _posy(runner)
    # phase 2: keep driving — Y stays pinned, X must still advance (slide)
    runner.run_frames(80)
    x_end, y_end = _posx(runner), _posy(runner)
    runner.set_input(0)
    assert y_end == y_mid, \
        f"slide: Y not pinned against the wall ({y_mid} -> {y_end}); not a clean " \
        f"axis-aligned-wall slide case"
    assert x_end != x_mid, \
        f"slide FAILED: X dead-stopped at the wall ({x_mid} -> {x_end}); the " \
        f"unblocked axis must keep advancing (per-axis slide)"
    # and the footprint stayed clear throughout the slide
    assert not _footprint_solid(x_end, y_end), \
        f"slide ended inside a wall at {(x_end, y_end)}"


# =============================================================================
# NO TUNNELING at the speed cap: drive at max speed straight
# into a wall; assert NO sampled frame lands the footprint inside a solid cell.
# =============================================================================
def test_no_tunneling_at_speed_cap(runner):
    """Hold B long enough to reach the +1.25 px/frame speed cap, then keep driving
    straight into a wall. Sampling EVERY frame, the footprint must never be inside a
    solid cell — the <=1.25px/f cap must hold even at a 2-tile (16px) wall band.
    (per-frame scan, step=1, so a single tunneling frame is caught.)"""
    rom = BUILD / "m7_dungeon.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    # ramp to cap first (ACCEL=$10 over $0140 cap -> ~20 frames to saturate), then
    # the per-frame scan covers the approach + impact at full speed.
    runner.set_input(0, b=True)
    runner.run_frames(25)          # saturate speed before the wall
    runner.set_input(0)
    bad = _drive_scan_frames(runner, 200, step=1, b=True)
    assert bad == 0, \
        f"tunneling: footprint entered a solid cell on {bad} frames at speed cap"


# =============================================================================
# NEGATIVE CONTROL: prove the test is NOT vacuous. The
# -DNO_COLLISION variant has the wall reject compiled out, so the hero WALKS
# THROUGH walls — the same scan that passes on the real ROM must FAIL here.
# =============================================================================
def test_negative_control_walks_through_walls(runner, variants):
    """The -DNO_COLLISION ROM disables the wall reject. Driving forward into a wall,
    the hero's footprint MUST enter solid cells (frames_in_wall > 0) — proving the
    collision assertion in the real tests can fail, i.e. it is not vacuous. The
    blocked-count must also stay 0 (no reject path compiled in)."""
    rom = variants["nocol"]
    assert rom.exists(), f"{rom} not built"
    runner.load_rom(str(rom), run_seconds=0.3)
    bad = _drive_scan_frames(runner, 260, b=True)
    px, py = _posx(runner), _posy(runner)
    assert bad > 0, \
        "NEGATIVE CONTROL FAILED: -DNO_COLLISION hero never entered a wall — the " \
        "collision test would be vacuous (it can't tell pass from fail)"
    assert _blocked(runner) == 0, \
        f"-DNO_COLLISION still registered {_blocked(runner)} blocks (reject not " \
        f"compiled out)"
    # and the no-collision hero ended up INSIDE a wall (walked clean through)
    assert _footprint_solid(px, py), \
        f"-DNO_COLLISION hero did not end inside a wall at {(px, py)}"


# =============================================================================
# MAZE ROUTE — the committed scripted route (assets/maze_route.json) drives the
# hero from spawn to the GOAL through the authored maze WITH COLLISION LIVE. CI
# protects it: replayed from boot it must reach the goal AND the footprint must
# never enter a solid cell on ANY frame (per-frame scan vs the LUT oracle).
# =============================================================================
import json

ROUTE_PATH = (ROOT / "templates" / "m7_dungeon" / "assets" / "maze_route.json")


def test_maze_route_reaches_goal(runner):
    """Replay the committed maze_route.json from boot: every frame the hero's 8px
    footprint must be CLEAR of solid cells (ground-truth LUT mirror), and the hero
    must end within 8px of the GOAL cell centre. This is the authored-maze solve,
    deterministic + CI-protected so the route stays replayable."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    assert ROUTE_PATH.exists(), f"{ROUTE_PATH} missing"
    route = json.loads(ROUTE_PATH.read_text())
    assert route and all("buttons" in s and "frames" in s for s in route), \
        "maze_route.json malformed"

    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"
    # spawn footprint must be clear (sanity: oracle agrees with the maze spawn)
    assert not _footprint_solid(_posx(runner), _posy(runner)), \
        f"spawn footprint solid per oracle at {(_posx(runner), _posy(runner))}"

    gx, gy = GOAL_PX
    bad_frames = []
    goal_frame = None
    frame = 0
    for st in route:
        btns = {b: True for b in st["buttons"]}
        for _ in range(int(st["frames"])):
            runner.set_input(0, **btns)
            runner.run_frames(1)
            frame += 1
            px, py = _posx(runner), _posy(runner)
            if _footprint_solid(px, py):
                bad_frames.append((frame, px, py))
            if goal_frame is None and abs(px - gx) <= 8 and abs(py - gy) <= 8:
                goal_frame = frame
    runner.set_input(0)

    assert not bad_frames, \
        f"route put the footprint in a wall on {len(bad_frames)} frames: " \
        f"{bad_frames[:5]}"
    px, py = _posx(runner), _posy(runner)
    assert abs(px - gx) <= 8 and abs(py - gy) <= 8, \
        f"route did not reach the goal: final {(px, py)} vs goal {(gx, gy)}"
    assert goal_frame is not None, "route never entered the goal region"


# =============================================================================
# ENEMY SPRITE PROJECTION onto the rotating Mode 7 floor.
# =============================================================================
# Static enemies live at fixed WORLD positions and are projected each frame onto
# the rotating + scrolling Mode 7 plane so they stay GLUED to their world tile.
# world->screen is the INVERSE of the forward (screen->texel) Mode 7 matrix
# M=[[A,B],[C,D]]; at the fixed scale 1.0 the inverse is the TRANSPOSE, so
# (sx,sy) = ( (dx*A+dy*C)>>8, (dx*B+dy*D)>>8 ) + (128,112), where (dx,dy)
# = enemy_world - player_world (the pivot = screen centre) and A=cos*scale>>8,
# B=sin*scale>>8, C=-B, D=A with scale=$0100 (1.0). This Python mirror is a CHEAP
# OAM SANITY oracle: it replicates the ROM's sincos LUT + 8.8 arithmetic, so it
# verifies the OAM bytes match the SAME formula — but because it IS that formula
# it CANNOT catch a wrong-rotation-direction projection (the forward-matrix-projection defect: a
# forward-matrix projection drifted enemies onto the WALLS yet passed this oracle
# AND the distance-only orbit check). The BINDING correctness guard is the
# rendered-FLOOR regression test below (test_enemies_on_rendered_floor), which
# reads the actual framebuffer and asserts each enemy sits on FLOOR, not WALL,
# pixels at multiple rotation angles. Every assertion reads the OAM bytes / the
# rendered frame (the hardware output) — never a proxy variable.
import math as _math

# main.asm screen anchor + sprite convention
_SCREEN_CX = 128
_SCREEN_CY = 112
_OBJ_HALF = 8        # 16x16 enemy: OAM (x,y) = projected centre - 8
_CULL_MARGIN = 16    # main.asm CULL_MARGIN: 16px slack for the 16px sprite
_CULL_Y = 0xF0       # main.asm CULL_Y: parked-offscreen Y


def _sincos_8_8(angle):
    """Mirror engine sincos: sin_lut[i] = round(sin(i*pi/256)*256), 512 entries.
    sina = sin_lut[(angle*2)&0x1FF]; cosa = sin_lut[(angle*2+128)&0x1FE]. Returns
    (cosa, sina) as signed 8.8 ints — exactly what sf_boss_matrix reads."""
    a = angle & 0xFF

    def lut(i):
        return int(round(_math.sin((i & 0x1FF) * _math.pi / 256.0) * 256))
    sin_i = (a * 2) & 0x1FF
    cos_i = (a * 2 + 128) & 0x1FE
    return lut(cos_i), lut(sin_i)


def _project(enemy_world, pivot, angle, scale=0x0100):
    """Ground-truth (sx,sy) for an enemy at enemy_world with the player at pivot
    and heading `angle`. Mirrors main.asm's projection EXACTLY (8.8 matrix,
    floor >>8). Returns signed screen coords (may be off-screen / negative)."""
    cosa, sina = _sincos_8_8(angle)
    A = (cosa * scale) >> 8
    B = (sina * scale) >> 8
    C = -B
    D = A
    dx = enemy_world[0] - pivot[0]
    dy = enemy_world[1] - pivot[1]
    # world->screen is the INVERSE of the forward (screen->texel) matrix
    # M=[[A,B],[C,D]]. At the fixed scale 1.0 M is a pure rotation, so its inverse
    # is the TRANSPOSE [[A,C],[B,D]] (swap B<->C vs the forward form). This MUST
    # match main.asm's fixed proj_dot calls (M7A,M7C then M7B,M7D). NOTE: this is a
    # cheap OAM sanity oracle, NOT the real guard — it is the same formula as the
    # ASM, so it can't catch a wrong-direction projection. The rendered-FLOOR
    # regression test (test_enemies_on_rendered_floor) is the binding check.
    sx = ((dx * A + dy * C) >> 8) + _SCREEN_CX
    sy = ((dx * B + dy * D) >> 8) + _SCREEN_CY
    return sx, sy


def _expected_oam(enemy_world, pivot, angle):
    """The OAM (x,y) the ROM should write, OR the parked sentinel if off-screen.
    Returns ('park', y=$F0) when culled, else ('on', oam_x9bit, oam_y)."""
    sx, sy = _project(enemy_world, pivot, angle)
    # cull rule == main.asm enemy_culled (window +/- margin, signed)
    off = (sx + _CULL_MARGIN < 0 or sx + _CULL_MARGIN >= 256 + 2 * _CULL_MARGIN or
           sy + _CULL_MARGIN < 0 or sy + _CULL_MARGIN >= 224 + 2 * _CULL_MARGIN)
    if off:
        return ("park", None, _CULL_Y)
    ox = (sx - _OBJ_HALF) & 0x1FF
    oy = (sy - _OBJ_HALF) & 0xFF
    return ("on", ox, oy)


def _enemy_mirror(runner, i):
    """Read enemy i's debug mirror: (world_x, world_y, screen_x, screen_y)."""
    base = DBG_ENE_BASE + i * DBG_ENE_STRIDE
    wx = runner.read_u16(WR, base + 0) & 0xFFFF
    wy = runner.read_u16(WR, base + 2) & 0xFFFF

    def s16(v):
        return v - 0x10000 if v >= 0x8000 else v
    sx = s16(runner.read_u16(WR, base + 4) & 0xFFFF)
    sy = s16(runner.read_u16(WR, base + 6) & 0xFFFF)
    return wx, wy, sx, sy


def _enemy_oam(runner, i):
    """OAM x (with bit8 from the high table), y, tile, attr for enemy slot i+1."""
    slot = i + 1
    x, y, tile, attr = _oam(runner, slot)
    # bit8 of X lives in the OAM high table: byte slot>>2, bit (slot&3)*2
    hi = runner.read_bytes(OAM, 512 + (slot >> 2), 1)[0]
    x9 = x | (((hi >> ((slot & 3) * 2)) & 1) << 8)
    return x9, y, tile, attr


def _pivot(runner):
    return (_posx(runner), _posy(runner))


# =============================================================================
# BOOT PLACEMENT: an enemy near the player projects
# on-screen; its OAM x/y matches the Python projection within a tight tolerance.
# =============================================================================
def test_boot_placement_matches_projection(runner):
    """At boot (angle 0, pivot = spawn 116,116) the enemies are SPREAD along the
    route: E0 (near-start) projects on-screen east of centre, while E1 (mid-path)
    and E2 (near-exit) are far enough to project OFF-screen (culled). Read each
    enemy's OAM and assert: its world mirror matches the authored table; an
    on-screen enemy's OAM (x,y) equals the Python projection within <=2 px; a
    culled enemy is parked at Y=$F0. At least E0 must be on-screen (so the per-
    enemy on-screen assertion is exercised)."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"

    pivot = _pivot(runner)
    ang = _angle(runner)
    on_count = 0
    for i in range(ENEMY_COUNT):
        wx, wy, sx, sy = _enemy_mirror(runner, i)
        # enemies patrol, so the live world pos has drifted from the seed by
        # boot; assert it stayed ON the seed's pace AXIS (the perpendicular coord
        # is unchanged) — i.e. it is moving along its corridor, not teleporting.
        seed = ENEMY_SEED[i]
        if ENEMY_AXIS[i] == 'x':
            assert wy == seed[1], f"E{i} drifted off its X-pace row: {(wx, wy)}"
        else:
            assert wx == seed[0], f"E{i} drifted off its Y-pace column: {(wx, wy)}"
        world = (wx, wy)
        state, exp_x, exp_y = _expected_oam(world, pivot, ang)
        ox, oy, tile, attr = _enemy_oam(runner, i)
        if state == "park":
            assert oy == _CULL_Y, \
                f"E{i} culled per oracle at boot but OAM y={oy} != parked {_CULL_Y}"
            continue
        on_count += 1
        assert abs(ox - exp_x) <= 2 and abs(oy - exp_y) <= 2, \
            f"E{i} OAM {(ox, oy)} != projection {(exp_x, exp_y)} (pivot {pivot}, " \
            f"angle {ang}); ROM screen mirror={(sx, sy)}"
        # enemy uses its own tile (32) + OBJ palette 1. OAM attr byte is VH00_PPPn:
        # bits 3:1 = OBJ palette (PPP), bit 0 = name/tile-high (n). Palette 1 means
        # bits3:1 == %001 AND the name bit MUST be 0 (else the OAM tile is bumped to
        # 256+32 = empty VRAM -> invisible; the original-defect signature). So the
        # whole low nibble must be %0010 == 2, NOT 1.
        assert tile == 32, f"E{i} not the enemy tile 32: tile={tile}"
        assert (attr & 0x01) == 0, \
            f"E{i} OAM name/tile-high bit set (attr={attr:#04x}) -> points at empty " \
            f"VRAM tile 288 -> invisible enemy"
        assert ((attr >> 1) & 0x07) == 1, \
            f"E{i} not OBJ palette 1 (PPP): attr={attr:#04x}"
    assert on_count >= 1, \
        "no enemy on-screen at boot — expected E0 (near-start) to project on-screen"


# =============================================================================
# ENEMIES ACTUALLY RENDER (pixel-level): correct OAM is
# NOT enough — the enemy CHR must be visible on the framebuffer in its OWN warm
# palette, at each projected centre. This reads RENDERED PIXELS, closing the gap
# where the original build had perfect OAM coords but 0 enemy pixels on screen
# (name/tile-high bit set -> empty VRAM tile 288; palette 0 -> hero colours). This
# test FAILS on that broken build (warm count == 0); see the inline non-vacuity
# note. It complements (does NOT replace) the OAM-coordinate oracle checks.
# =============================================================================
def test_enemies_render_red_at_projected_centres(runner):
    """Boot, screenshot the frame, and assert the enemy DEMON's warm body colour is
    actually PRESENT at each on-screen enemy's projected sprite centre (OAM x+8,
    y+8). Sampling a patch around the centre tolerates the sprite shape. The
    whole-frame warm count must be > 0 (it is 0 on the invisible-enemy defect and on
    the -DENEMY_MISCOLOR control), and the grey/bone KNIGHT hero (slot 0) must NOT be
    counted — proving the match band is enemy-specific, not "any bright sprite"."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"

    shot = str(BUILD / "_s4_enemy_render_h0.png")
    runner.take_screenshot(shot)

    # Whole-frame enemy-red must EXIST (the invisible-enemy defect => 0).
    total = _count_enemy_red_total(shot)
    assert total > 0, \
        "NO enemy-red pixels in the rendered frame — the enemies are invisible " \
        "(the OAM coords can be perfect yet the sprite never renders)"

    # Per on-screen enemy: red must cluster at its projected sprite centre.
    pivot = _pivot(runner)
    ang = _angle(runner)
    centres_checked = 0
    for i in range(ENEMY_COUNT):
        world = _live_world(runner, i)               # live patrol pos
        state, exp_x, exp_y = _expected_oam(world, pivot, ang)
        if state != "on":
            continue
        ox, oy, tile, attr = _enemy_oam(runner, i)
        cx, cy = ox + _OBJ_HALF, oy + _OBJ_HALF      # sprite centre
        red = _count_enemy_red_near(shot, cx, cy, radius=12)
        assert red >= 8, \
            f"E{i}: only {red} enemy-red px at projected centre ({cx},{cy}) — the " \
            f"enemy is not rendering in its red palette there (tile={tile} " \
            f"attr={attr:#04x})"
        centres_checked += 1
    assert centres_checked >= 1, \
        f"expected >=1 on-screen enemy at boot (E0 near-start), checked " \
        f"{centres_checked}"

    # Negative control: the hero box (centre ~128,112) is the grey/bone KNIGHT,
    # must read ~0 enemy-warm px, proving the band does not just match any sprite.
    hero_red = _count_enemy_red_near(shot, 128, 112, radius=8)
    assert hero_red == 0, \
        f"hero box matched {hero_red} 'enemy-warm' px — the colour band is not " \
        f"enemy-specific (would let the grey knight hero pass as the demon)"


# =============================================================================
# ENEMY-COLOUR NON-VACUITY: the -DENEMY_MISCOLOR control ROM renders the demon in
# a COOL palette, so the enemy-warm band must read ZERO — proving the enemy colour
# tests are a real guard (they CAN fail), not a tautology.
# =============================================================================
def test_enemy_colour_regression_fails_on_miscolor(runner, variants):
    """NON-VACUITY for the retuned enemy colour band: -DENEMY_MISCOLOR loads a COOL
    (floor-blue) OBJ palette for the enemy, so the demon renders BLUE and the whole
    frame reads 0 enemy-warm pixels. The real demon build reads >0 (see
    test_enemies_render_red_at_projected_centres) — so the enemy colour tests are
    not vacuous. Reads the rendered framebuffer."""
    rom = variants["miscolor"]
    assert rom.exists(), f"{rom} not built (variant build did not run)"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"
    shot = str(BUILD / "_enemy_miscolor.png")
    runner.take_screenshot(shot)
    total = _count_enemy_red_total(shot)
    assert total == 0, \
        f"non-vacuity FAILED: -DENEMY_MISCOLOR rendered {total} enemy-warm px — the " \
        f"enemy colour band would match a COOL (non-demon) sprite, making the enemy " \
        f"colour tests vacuous. shot={shot}"
    print(f"\nenemy-colour non-vacuity OK: miscolor build = {total} enemy-warm px "
          f"(real demon build > 0). shot={shot}")


# =============================================================================
# RENDERED ENEMIES ORBIT WITH ROTATION (pixels, not OAM):
# after rotating the heading, the red clusters must MOVE and still sit at the new
# projected centres — the enemy diamonds visibly orbit with the floor.
# =============================================================================
def test_rendered_enemies_orbit_under_rotation(runner):
    """Screenshot at heading 0, rotate LEFT, screenshot again. The enemy-red must
    still render (>0) and follow the OAM centres at the new heading, and at least
    one enemy's rendered centre must have MOVED (proving the pixels orbit with the
    floor, not pinned on screen)."""
    rom = BUILD / "m7_dungeon.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)

    shot0 = str(BUILD / "_s4_orbit_h0.png")
    runner.take_screenshot(shot0)
    oam0 = [_enemy_oam(runner, i) for i in range(ENEMY_COUNT)]

    runner.set_input(0, left=True)
    runner.run_frames(40)
    runner.set_input(0)
    runner.run_frames(2)
    shot1 = str(BUILD / "_s4_orbit_h1.png")
    runner.take_screenshot(shot1)
    oam1 = [_enemy_oam(runner, i) for i in range(ENEMY_COUNT)]

    assert _count_enemy_red_total(shot1) > 0, \
        "enemies vanished after rotation (no enemy-red pixels)"

    moved = 0
    pivot = _pivot(runner)
    ang = _angle(runner)
    for i in range(ENEMY_COUNT):
        world = _live_world(runner, i)               # live patrol pos
        state, _, _ = _expected_oam(world, pivot, ang)
        if state != "on":
            continue
        ox1, oy1 = oam1[i][0], oam1[i][1]
        cx1, cy1 = ox1 + _OBJ_HALF, oy1 + _OBJ_HALF
        red = _count_enemy_red_near(shot1, cx1, cy1, radius=12)
        assert red >= 8, \
            f"E{i}: only {red} enemy-red px at rotated centre ({cx1},{cy1})"
        if (oam1[i][0], oam1[i][1]) != (oam0[i][0], oam0[i][1]):
            moved += 1
    assert moved >= 1, \
        "no enemy's rendered position changed under rotation (not orbiting)"


# =============================================================================
# GLUED UNDER ROTATION (the anti-"swim" test): rotate the
# heading; the enemy's OAM must track the projection at every heading — it ORBITS
# screen centre (constant radius) consistent with the floor, never swims off its
# world tile. STRICT: OAM == oracle within <=2 px across many headings.
# =============================================================================
def test_glued_under_rotation_does_not_swim(runner):
    """Hold LEFT/RIGHT to sweep the heading through many values. At EACH heading,
    every on-screen enemy's OAM (x,y) must equal the Python projection (<=2 px) AND
    its screen distance from centre (128,112) must equal the LIVE world distance
    |live_world - pivot| (the orbit radius) — proving it stays glued to its world
    spot as the floor rotates, not fixed on screen and not swimming. The pivot does
    NOT move here (no throttle), so any OAM motion is rotation + the enemy's own
    patrol. S5: the orbit radius is read LIVE per frame (the enemy paces along its
    corridor, so its world distance from the pivot changes) — the swim guard is
    'screen radius == live world radius', not a fixed boot radius."""
    rom = BUILD / "m7_dungeon.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    pivot = _pivot(runner)

    headings_checked = 0
    # sweep ~ a full turn in steps by holding LEFT; sample every few frames.
    for _ in range(20):
        runner.set_input(0, left=True)
        runner.run_frames(6)
        runner.set_input(0)
        runner.run_frames(1)
        # pivot must NOT have drifted (no throttle) — rotation-only invariant
        assert _pivot(runner) == pivot, \
            f"pivot drifted under pure rotation: {_pivot(runner)} != {pivot}"
        ang = _angle(runner)
        for i in range(ENEMY_COUNT):
            world = _live_world(runner, i)           # live patrol pos
            state, exp_x, exp_y = _expected_oam(world, pivot, ang)
            if state != "on":
                continue
            ox, oy, tile, attr = _enemy_oam(runner, i)
            # Cull-boundary fuzz: when the enemy is right at the visible edge, the
            # ROM's integer cull and the Python oracle can disagree by ~1px on
            # whether to park it. If the ROM PARKED it (OAM y == CULL_Y), it is being
            # culled (not swimming) — skip this borderline sample.
            if oy == _CULL_Y:
                continue
            assert abs(ox - exp_x) <= 2 and abs(oy - exp_y) <= 2, \
                f"SWIM: E{i} OAM {(ox, oy)} != projection {(exp_x, exp_y)} at " \
                f"angle {ang} (pivot {pivot}, live world {world})"
            # orbit-radius invariant: the DRAWN sprite's screen distance from centre
            # (128,112) must equal the LIVE world distance from the pivot (the orbit
            # radius) — proving it is glued to its world spot, not pinned on screen.
            # Use the (signed, un-wrapped) PROJECTION centre exp_x/exp_y, validated
            # == OAM (<=2px) above; the raw 9-bit OAM X wraps for a sprite near the
            # left edge and would corrupt the radius. Skip the (rare) edge-wrap
            # sample where exp_x falls in the off-left cull band.
            if -_CULL_MARGIN <= exp_x <= 256 + _CULL_MARGIN:
                cx, cy = exp_x + _OBJ_HALF, exp_y + _OBJ_HALF
                r = _math.hypot(cx - 128, cy - 112)
                world_r = _math.hypot(world[0] - pivot[0], world[1] - pivot[1])
                assert abs(r - world_r) <= 4, \
                    f"SWIM: E{i} screen orbit radius {r:.1f} != live world radius " \
                    f"{world_r:.1f} at angle {ang} (must stay glued to its world spot)"
            headings_checked += 1
    runner.set_input(0)
    assert headings_checked >= 10, \
        f"too few on-screen rotation samples checked ({headings_checked})"


# =============================================================================
# GLUED UNDER TRANSLATION: drive forward/back; the enemy's
# OAM shifts per the projection (it stays on its world spot as the floor scrolls).
# =============================================================================
def test_glued_under_translation(runner):
    """Drive FORWARD (the pivot/world pos moves), then the enemies — fixed in the
    world — must shift on screen exactly per the projection (the floor scrolls
    under them). At several points along the drive, every on-screen enemy's OAM
    equals the Python projection from the CURRENT pivot (<=2 px). As the player
    drives toward the eastern enemies, they move toward + past screen centre."""
    rom = BUILD / "m7_dungeon.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)

    samples = 0
    for _ in range(8):
        runner.set_input(0, b=True)      # throttle forward (heading 0 = north/+? )
        runner.run_frames(10)
        runner.set_input(0)
        runner.run_frames(2)
        pivot = _pivot(runner)
        ang = _angle(runner)
        for i in range(ENEMY_COUNT):
            world = _live_world(runner, i)           # live patrol pos
            state, exp_x, exp_y = _expected_oam(world, pivot, ang)
            if state != "on":
                continue
            ox, oy, tile, attr = _enemy_oam(runner, i)
            assert abs(ox - exp_x) <= 2 and abs(oy - exp_y) <= 2, \
                f"E{i} OAM {(ox, oy)} != projection {(exp_x, exp_y)} after drive " \
                f"(pivot {pivot}, angle {ang}, live world {world}) — not glued"
            samples += 1
    runner.set_input(0)
    assert samples >= 5, f"too few on-screen translation samples ({samples})"


# =============================================================================
# CULLING: drive far enough that an enemy leaves the visible
# window; its OAM entry must be PARKED off-screen (Y=$F0), not wrapped on-screen.
# =============================================================================
def test_offscreen_enemy_is_culled(runner, variants):
    """The goal-spawn variant places the player in the GOAL cell (px 356,356). The
    enemies are SPREAD along the route, so from the goal the FAR ones cull: E0
    (near-start px 156,116, ~312px away) and E1 (mid-path px 276,196, ~179px away)
    both project OFF the visible window, while E2 (near-exit px 356,316, only ~40px
    away) is ON-screen here. Each enemy whose projection is off-screen (per the
    oracle) must have its OAM PARKED at Y=$F0 (kit cull convention), NOT wrapped to a
    bogus on-screen position; each on-screen enemy must NOT be parked. Deterministic
    at boot. Also drive a little to confirm the cull holds dynamically, not just at
    boot."""
    rom = variants["goalspawn"]
    assert rom.exists(), f"{rom} not built"
    runner.load_rom(str(rom), run_seconds=0.3)

    def check_all_culled(tag):
        pivot = _pivot(runner)
        ang = _angle(runner)
        culled_any = False
        for i in range(ENEMY_COUNT):
            world = _live_world(runner, i)           # live patrol pos
            state, exp_x, exp_y = _expected_oam(world, pivot, ang)
            ox, oy, tile, attr = _enemy_oam(runner, i)
            if state == "park":
                culled_any = True
                assert oy == _CULL_Y, \
                    f"{tag}: E{i} culled per oracle but OAM y={oy} != parked " \
                    f"{_CULL_Y} (pivot {pivot}, angle {ang})"
            else:
                assert oy != _CULL_Y, \
                    f"{tag}: E{i} parked but oracle says on-screen {(exp_x, exp_y)}"
        return culled_any

    # at boot: all enemies far away -> all parked, none wrapped on-screen
    assert check_all_culled("boot"), \
        "goal-spawn: no enemy off-screen — the cull test would be vacuous"
    # and after a short drive (pivot moves) the cull still tracks the oracle
    runner.set_input(0, b=True)
    runner.run_frames(20)
    runner.set_input(0)
    check_all_culled("after-drive")


# =============================================================================
# CULLING BY VISIBILITY (rendered-output drop-then-pop):
# the enemies are SPREAD along the route, so the NEAR-EXIT enemy (E2, px 356,316,
# ~312px from spawn) is OFF the visible window at spawn and only pops in when the
# player approaches the GOAL. This reads the RENDERED FRAMEBUFFER + OAM (never a
# proxy): at boot E2 is genuinely NOT DRAWN (OAM parked at CULL_Y + zero enemy-red
# pixels where it would project) while the near-start enemy (E0) IS drawn (red
# pixels on screen); then the committed maze_route is replayed to the goal, after
# which E2 is DRAWN (OAM un-parked + enemy-red pixels at its projected centre).
# This proves culling drops far enemies and visibility pops them back in.
# =============================================================================
def test_culling_by_visibility_drop_then_pop(runner):
    """At spawn the near-exit enemy E2 is CULLED (OAM y==CULL_Y AND no enemy-red
    pixels where it would project — it is genuinely not rendered) while the
    near-start enemy E0 is ON-screen (rendered red). Then drive the committed
    maze_route.json to the goal: E2 must POP IN — OAM un-parked AND enemy-red
    pixels appear at its projected sprite centre. Reads the rendered output +
    OAM, never a proxy variable."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    assert ROUTE_PATH.exists(), f"{ROUTE_PATH} missing"

    E0_IDX, E2_IDX = 0, 2          # near-start, near-exit (per ENEMY_SEED spread)

    # ---- PHASE 1: at spawn, E2 is DROPPED (culled) and E0 is DRAWN -------------
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"
    pivot, ang = _pivot(runner), _angle(runner)

    # the oracle must agree the spread is non-vacuous: E2 off, E0 on at spawn.
    # read the LIVE world pos (enemies patrol; at spawn-boot they have barely
    # drifted, but use live so the oracle matches the ROM's actual position).
    w2_spawn = _live_world(runner, E2_IDX)
    w0_spawn = _live_world(runner, E0_IDX)
    st2, _, _ = _expected_oam(w2_spawn, pivot, ang)
    st0, _, _ = _expected_oam(w0_spawn, pivot, ang)
    assert st2 == "park", \
        f"E2 (near-exit) not off-screen at spawn (oracle says {st2}) — culling " \
        f"would be vacuous; pivot {pivot} angle {ang}"
    assert st0 == "on", \
        f"E0 (near-start) not on-screen at spawn (oracle says {st0})"

    spawn_shot = "/tmp/m7dungeon_cull_spawn.png"
    runner.take_screenshot(spawn_shot)

    # E2 OAM is PARKED at the cull Y (the ROM dropped it).
    e2x, e2y, e2tile, e2attr = _enemy_oam(runner, E2_IDX)
    assert e2y == _CULL_Y, \
        f"E2 not parked off-screen at spawn: OAM y={e2y} != {_CULL_Y}"
    # and it is GENUINELY not drawn: where E2 WOULD project (its true screen spot,
    # had it not been culled), there are NO enemy-red pixels on the framebuffer.
    proj2 = _project(w2_spawn, pivot, ang)
    red_e2_spawn = _count_enemy_red_near(spawn_shot, proj2[0], proj2[1], radius=14)
    assert red_e2_spawn == 0, \
        f"E2 culled in OAM but {red_e2_spawn} enemy-red px rendered at its would-be " \
        f"projection {proj2} — it is still drawn (cull did not drop the sprite)"

    # E0 IS drawn at spawn: OAM on-screen + enemy-red pixels at its centre.
    e0x, e0y, _, _ = _enemy_oam(runner, E0_IDX)
    assert e0y != _CULL_Y, f"E0 (near-start) parked at spawn (should be on-screen)"
    red_e0_spawn = _count_enemy_red_near(
        spawn_shot, e0x + _OBJ_HALF, e0y + _OBJ_HALF, radius=12)
    assert red_e0_spawn >= 8, \
        f"E0 (near-start) only {red_e0_spawn} enemy-red px at spawn — it should be " \
        f"clearly drawn on-screen while E2 is dropped"

    # ---- PHASE 2: replay the route to the goal; E2 POPS IN (drawn) -------------
    # Replay FRAME-BY-FRAME (re-latch input each frame), the same way the route was
    # recorded and the way test_maze_route_reaches_goal drives it. A chunked replay
    # (set_input once, run_frames(N)) latches on a different sub-frame phase and
    # drifts the enemy-dodge timing off the recorded path.
    route = json.loads(ROUTE_PATH.read_text())
    for st in route:
        btns = {b: True for b in st["buttons"]}
        for _ in range(int(st["frames"])):
            runner.set_input(0, **btns)
            runner.run_frames(1)
    runner.set_input(0)
    runner.run_frames(2)

    pivot, ang = _pivot(runner), _angle(runner)
    gx, gy = GOAL_PX
    assert abs(pivot[0] - gx) <= 8 and abs(pivot[1] - gy) <= 8, \
        f"route did not reach the goal: pivot {pivot} vs goal {(gx, gy)}"

    near_shot = "/tmp/m7dungeon_cull_nearexit.png"
    runner.take_screenshot(near_shot)

    # E2 is now ON-screen per the oracle (sanity: the pop-in is real, not luck).
    st2n, _, _ = _expected_oam(_live_world(runner, E2_IDX), pivot, ang)
    assert st2n == "on", \
        f"E2 not on-screen at goal (oracle {st2n}); pivot {pivot} angle {ang}"
    # OAM un-parked AND enemy-red pixels render at E2's projected sprite centre.
    e2x2, e2y2, _, _ = _enemy_oam(runner, E2_IDX)
    assert e2y2 != _CULL_Y, \
        f"E2 still parked (y={e2y2}) at the goal — it did not pop back in"
    red_e2_near = _count_enemy_red_near(
        near_shot, e2x2 + _OBJ_HALF, e2y2 + _OBJ_HALF, radius=12)
    assert red_e2_near >= 8, \
        f"E2 OAM un-parked at goal but only {red_e2_near} enemy-red px at its " \
        f"projected centre ({e2x2 + _OBJ_HALF},{e2y2 + _OBJ_HALF}) — it did not " \
        f"render (visibility pop-in not on the framebuffer)"

    print(f"\nS4 culling-by-visibility: E2 enemy-red px at spawn={red_e2_spawn} "
          f"(dropped) -> at goal={red_e2_near} (popped in); "
          f"E0 at spawn={red_e0_spawn}. shots: {spawn_shot} {near_shot}")


# =============================================================================
# VISUAL: the enemy sprite sits ON the floor at its world
# tile at TWO different player headings (proving it rotates around with the floor).
# Saves screenshots for owner inspection; asserts the rendered frame is textured.
# =============================================================================
def test_visual_enemy_on_floor_two_headings(runner):
    """Capture the rendered frame at two headings. Each shows the red enemy
    sprite(s) sitting on the rotating floor at their world tile (the orbit moves
    them between the two shots). Saved to /tmp for owner inspection; the floor is
    asserted textured (>=4 colours) so the captures are real renders. Also confirms
    via OAM that >=1 enemy is on-screen and glued to the projection in each shot."""
    rom = BUILD / "m7_dungeon.sfc"

    def capture(turn_frames, tag):
        runner.load_rom(str(rom), run_seconds=0.3)
        if turn_frames:
            runner.set_input(0, left=True)
            runner.run_frames(turn_frames)
            runner.set_input(0)
            runner.run_frames(2)
        shot = f"/tmp/m7dungeon_s4_{tag}.png"
        runner.take_screenshot(shot)
        n = _distinct_floor_colours(shot)
        assert n >= 4, f"{tag}: floor not textured ({n} colours)"
        pivot, ang = _pivot(runner), _angle(runner)
        on = 0
        for i in range(ENEMY_COUNT):
            world = _live_world(runner, i)           # live patrol pos
            state, exp_x, exp_y = _expected_oam(world, pivot, ang)
            if state != "on":
                continue
            ox, oy, tile, attr = _enemy_oam(runner, i)
            assert abs(ox - exp_x) <= 2 and abs(oy - exp_y) <= 2, \
                f"{tag}: E{i} OAM {(ox, oy)} != projection {(exp_x, exp_y)}"
            # VISUAL truth: the enemy's RED body must actually render at its
            # projected centre — not just have correct OAM coords (the defect was
            # correct OAM + 0 rendered pixels). Reads the framebuffer.
            cx, cy = ox + _OBJ_HALF, oy + _OBJ_HALF
            red = _count_enemy_red_near(shot, cx, cy, radius=12)
            assert red >= 8, \
                f"{tag}: E{i} OAM correct but only {red} red px rendered at " \
                f"({cx},{cy}) — invisible/wrong-palette enemy (tile={tile} " \
                f"attr={attr:#04x})"
            on += 1
        assert on >= 1, f"{tag}: no enemy on-screen to show on the floor"
        return shot, ang

    shot0, ang0 = capture(0, "heading0")
    shot1, ang1 = capture(40, "heading40")
    assert ang0 != ang1, "the two captures must be at different headings"
    print(f"\nS4 visual captures: {shot0} (angle {ang0}), {shot1} (angle {ang1})")


# =============================================================================
# done-condition — RENDERED-FLOOR REGRESSION (the BINDING correctness
# guard). The S4 defect (2nd): the enemy projection used the FORWARD (screen->
# texel) matrix instead of its INVERSE, so under floor ROTATION the enemies
# drifted onto the WALLS. The OAM-vs-_project oracle missed it (it is the SAME
# formula as the ASM — self-referential) and the orbit-RADIUS check missed it (it
# is blind to rotation DIRECTION). This test is oracle-FREE: it reads the actual
# rendered framebuffer and, for several rotation angles, samples a ring around
# each on-screen enemy's DRAWN sprite centre and asserts that ring sits on FLOOR-
# coloured pixels, NOT WALL pixels — proving the enemy is glued to the floor it
# is standing on at EVERY angle (angle 0 is the on-floor calibration).
#   Non-vacuity is proven by test_floor_regression_fails_on_forward_build
#   below: the -DENEMY_PROJ_FORWARD build (old buggy projection) FAILS this same
#   floor check (enemies land on WALLS at rotated angles).
# =============================================================================
# Headings to sample. 0 = on-floor calibration; the rest exercise rotation. Driven
# by holding LEFT from boot (angle increases), pivot stays at spawn (no throttle).
_FLOOR_ANGLES = [0, 40, 96, 160, 220]
# A ring passes iff it is NOT WALL-DOMINATED: floor pixels exceed wall pixels, OR
# the wall count is negligibly low (<= _WALL_NOISE). S5: a PATROLLING enemy can
# pace to a spot whose ring straddles the dark checker (floor=0, wall=0 — neither
# band), which the old "floor >= 60" rule wrongly failed; the real bug signal is
# the enemy CENTRE sitting ON a wall (wall pixels DOMINATE the ring). Measured:
# FIXED build wall <= 19 at every sample (floor>>wall or both ~0); BUGGY (forward-
# matrix) build wall = 17..57 with floor = 0 on the drifted-onto-wall enemies.
_WALL_NOISE = 12         # wall pixels this low = corridor edge clipping, not "on a wall"
                         # (FIXED max wall when floor is dim is ~0; BUGGY >= 17)


def _drive_left_to(runner, target, max_steps=240):
    """Boot already loaded: hold LEFT until R_ANGLE reaches ~target (it increases
    by a few per frame). Pivot does NOT move (no throttle). Returns the reached
    angle. target==0 means leave it at boot heading 0."""
    if target == 0:
        return _angle(runner)
    prev = _angle(runner)
    for _ in range(max_steps):
        runner.set_input(0, left=True)
        runner.run_frames(2)
        runner.set_input(0)
        a = _angle(runner)
        # angle is mod 256 and increasing; stop once we've reached/passed target
        if a >= target or (a < prev and target - prev > 0):
            break
        prev = a
    runner.run_frames(2)
    return _angle(runner)


def _assert_enemies_on_floor(runner, rom, tag, require_on_floor=True):
    """For each sampled rotation angle, screenshot the rendered frame and check
    every ON-SCREEN enemy's drawn-sprite-centre ring against FLOOR vs WALL pixels.
    Returns a list of (angle, enemy_idx, n_floor, n_wall) for every checked enemy.
    If require_on_floor, ASSERTS each is on floor; else just measures (for the
    non-vacuity proof)."""
    results = []
    checked_angles = set()
    for target in _FLOOR_ANGLES:
        runner.load_rom(str(rom), run_seconds=0.3)
        ang = _drive_left_to(runner, target)
        pivot = _pivot(runner)
        shot = str(BUILD / f"_s4_floor_{tag}_a{target}.png")
        runner.take_screenshot(shot)
        # floor must be a real textured render (guards a black/flat capture)
        assert _distinct_floor_colours(shot) >= 4, \
            f"{tag} a{target}: floor not textured — capture is not a real render"
        any_on = False
        for i in range(ENEMY_COUNT):           # drawn-sprite-centre is read
            ox, oy, tile, attr = _enemy_oam(runner, i)  # straight from live OAM
            if oy == _CULL_Y:
                continue                       # parked off-screen this angle
            cx, cy = ox + _OBJ_HALF, oy + _OBJ_HALF
            nf, nw, nt = _floor_wall_ring(shot, cx, cy)
            results.append((ang, i, nf, nw))
            any_on = True
            if require_on_floor:
                # NOT wall-dominated: floor exceeds wall, OR wall is negligibly low
                # (corridor-edge clipping, not the enemy standing on a wall).
                assert nf > nw or nw <= _WALL_NOISE, \
                    f"{tag} angle {ang} E{i}: enemy sprite centre ({cx},{cy}) is " \
                    f"ON A WALL — ring has floor={nf} wall={nw} (wall dominates; " \
                    f"need floor>wall or wall<={_WALL_NOISE}). This is the forward-" \
                    f"vs-inverse projection drift onto the walls."
        assert any_on, f"{tag} a{target}: no enemy on-screen to check (vacuous)"
        checked_angles.add(target)
    # the whole point: floor-correctness validated across MULTIPLE rotation angles
    assert len(checked_angles) >= 4, \
        f"{tag}: only {len(checked_angles)} angles checked; need >=4 rotations"
    return results


def test_enemies_on_rendered_floor(runner):
    """ORACLE-FREE binding guard: at angles 0/40/96/160/220 (LEFT-driven from
    boot, player at spawn), every on-screen enemy's DRAWN sprite centre sits on
    FLOOR pixels (cool flagstone), NOT WALL pixels (warm brick). Reads the rendered
    framebuffer — never the projection formula or a proxy var. This is what the
    self-referential OAM oracle + distance-only orbit check could not catch."""
    rom = BUILD / "m7_dungeon.sfc"
    results = _assert_enemies_on_floor(runner, rom, "fixed", require_on_floor=True)
    # report the measured floor/wall counts (owner-visible proof on the render)
    print("\nS4 rendered-floor (FIXED) — floor/wall pixels per on-screen enemy:")
    for ang, i, nf, nw in results:
        print(f"  angle {ang:3d}  E{i}  floor={nf:3d}  wall={nw:3d}")


def test_floor_regression_fails_on_forward_build(variants):
    """NON-VACUITY: the -DENEMY_PROJ_FORWARD build (the OLD buggy forward-matrix
    projection) must FAIL the rendered-floor check — its enemies drift onto the
    WALLS at rotated angles. Proves test_enemies_on_rendered_floor is a real
    guard, not a tautology. Same harness, require_on_floor=False to MEASURE, then
    assert at least one rotated angle shows an enemy on a WALL (floor<wall)."""
    rom = variants["projfwd"]
    assert Path(rom).exists(), f"{rom} missing (variant build did not run)"
    r = MesenRunner()
    try:
        # measure without asserting on-floor, then prove the buggy build is on WALLS
        results = _assert_enemies_on_floor(r, rom, "buggy_fwd",
                                           require_on_floor=False)
    finally:
        r.stop()
    print("\nS4 rendered-floor (BUGGY -DENEMY_PROJ_FORWARD) — floor/wall per enemy:")
    on_wall = 0
    rotated_on_wall = 0
    for ang, i, nf, nw in results:
        print(f"  angle {ang:3d}  E{i}  floor={nf:3d}  wall={nw:3d}")
        # an enemy whose ring is WALL-dominated and would FAIL the floor assertion
        # (the same rule the binding test uses: pass iff floor>wall OR wall<=noise)
        if not (nf > nw or nw <= _WALL_NOISE):
            on_wall += 1
            if ang != 0:
                rotated_on_wall += 1
    # the buggy build must put >=1 enemy on a WALL at a ROTATED angle (angle 0 is
    # the shared calibration where BOTH builds are correct, so it doesn't count).
    assert rotated_on_wall >= 1, \
        "non-vacuity FAILED: the forward-matrix (buggy) build did NOT land any " \
        f"enemy on a wall at a rotated angle (on_wall={on_wall}) — the floor test " \
        "would not actually catch the defect"
    print(f"  => non-vacuity OK: {rotated_on_wall} enemy/angle samples on WALL "
          f"(would FAIL the floor test) on the buggy build")


# =============================================================================
# SPRITE-SIZE REGRESSION — the hero is a 16x16 sprite with NO tile bleed (no
# phantom diamond below it).
#
# THE BUG: OBSEL ($2101)=$62 selects size pair 3 = 16x16 small / 32x32 LARGE.
# The hero spr flags ($0080) + ENEMY_ATTR ($0082) SET the OAM size bit, picking
# the 32x32 LARGE size. A 32x32 hero at tile 0 reads a 4x4 tile block (tiles
# 0..3, 16..19, 32..35, 48..51); tile 32 is the ENEMY CHR (added in S4), so the
# enemy (demon) shape renders in the hero's lower-LEFT quadrant in the HERO's
# palette -> a phantom grey/bone diamond below the hero. Latent since S1 (tile 32
# was blank until S4 added the enemy art). FIX: clear the size bit (16x16 small).
#
# These read the rendered OUTPUT (OAM high table + framebuffer pixels), never a
# proxy. Non-vacuity is proven by test_sprite_size_regression_fails_on_big_build
# below: the -DBUGGY_SPRITE_SIZE build (size bit SET = 32x32) FAILS both checks.
# =============================================================================
# The hero sprite's own palette (Wave-D dressing: the hero is now the dungeonSprites
# KNIGHT, a CC0 pack sprite): steel-grey body rendered ~ (148,140,140) and a bone
# highlight ~ (239,231,222). When a 32x32 hero pulls in tile 32 (the enemy CHR)
# rendered in the HERO palette, that phantom diamond fills the lower quadrant with
# these SAME grey/bone hero-palette pixels — which must NOT appear in the floor
# region directly below a correct 16x16 hero. A KNIGHT-palette pixel is BRIGHT and
# DESATURATED (grey/white): r,g,b all >= ~110 and near-equal. That REJECTS the cool
# flagstone floor (too dark, blue-biased) and the warm brick wall (b too low).
def _is_hero_sprite_px(rgb):
    """True iff rgb is a KNIGHT-hero-palette sprite pixel: the bright, low-saturation
    steel-grey / bone-white body. Retuned on measured rendered values to REJECT the
    floor (dark/blue) and the brick wall (low blue), so only a real hero-palette
    pixel (or its 32x32 phantom-diamond bleed) passes."""
    r, g, b = rgb
    return (r >= 120 and g >= 115 and b >= 110
            and (max(r, g, b) - min(r, g, b)) <= 40)


def _count_hero_px_below(path, x0=120, x1=136, y0=120, y1=134):
    """Count HERO-palette sprite pixels in the floor region BELOW the hero
    (logical 256x224 box x0..x1, y0..y1 — the lower-left quadrant of where a
    32x32 hero would draw, == where the phantom diamond appeared). On a 16x16
    hero this region is pure floor -> 0; on the buggy 32x32 hero the diamond
    fills it. Reads the rendered framebuffer."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    n = 0
    for sy in range(y0, y1):
        iy = sy * h // 224
        for sx in range(x0, x1):
            ix = sx * w // 256
            if _is_hero_sprite_px(px[ix, iy]):
                n += 1
    return n


def _oam_size_bit(runner, slot):
    """The OAM size-select bit for `slot`, read from the OAM HIGH table (the
    hardware bytes at OAM offset 512). With OBSEL pair $62, bit CLEAR = 16x16
    (small), bit SET = 32x32 (large). High table: byte 512 + (slot>>2), the
    size bit is bit ((slot&3)*2 + 1)."""
    hi = runner.read_bytes(OAM, 512 + (slot >> 2), 1)[0]
    return (hi >> ((slot & 3) * 2 + 1)) & 1


def _active_slots(runner, max_slots=8):
    """Slots whose OAM Y is on-screen (not the parked CULL_Y) — the active
    sprites. The hero (0) + any un-culled enemies."""
    out = []
    for s in range(max_slots):
        _, y, _, _ = _oam(runner, s)
        if y != _CULL_Y:
            out.append(s)
    return out


def test_sprite_size_hero_is_16x16_no_diamond(runner):
    """REGRESSION (phantom diamond): the hero is a 16x16 sprite and there
    is NO hero-palette tile bleed below it. Two rendered-output checks:
      (1) OAM size: every ACTIVE sprite's size bit (OAM high table) is CLEAR
          (16x16 small — with OBSEL pair $62). A SET bit = 32x32, the bug.
      (2) Framebuffer: the region just BELOW the hero (logical ~122..134 x,
          120..134 y — where the phantom diamond appeared) has ZERO hero-palette
          sprite pixels (it must be floor, not a grey/bone knight-palette diamond).
    Reads OAM + the rendered frame; the buggy 32x32 build FAILS both (see
    test_sprite_size_regression_fails_on_big_build)."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"

    # (1) OAM size bit CLEAR on every active sprite (hero + on-screen enemies).
    actives = _active_slots(runner)
    assert HERO_SLOT in actives, "hero slot 0 is not active (parked?)"
    for s in actives:
        assert _oam_size_bit(runner, s) == 0, \
            f"slot {s} OAM size bit SET -> 32x32 (with OBSEL $62); expected 16x16 " \
            f"(size bit CLEAR). A 32x32 hero pulls tile 32 (enemy CHR) into its " \
            f"lower quadrant -> the phantom grey/bone diamond."

    # (2) No hero-palette sprite pixels in the floor region below the hero.
    shot = str(BUILD / "_sprsize_hero.png")
    runner.take_screenshot(shot)
    n_below = _count_hero_px_below(shot)
    assert n_below == 0, \
        f"{n_below} hero-palette sprite pixels below the hero — a phantom diamond " \
        f"(tile 32 enemy CHR bleeding into a 32x32 hero) is rendering there; the " \
        f"region should be clean floor. shot={shot}"


def test_sprite_size_regression_fails_on_big_build(runner, variants):
    """NON-VACUITY: the -DBUGGY_SPRITE_SIZE build restores the OLD 32x32 size bit
    on the hero + enemies. It MUST FAIL the two checks the fixed build passes:
    the hero's OAM size bit is SET (32x32) AND hero-palette pixels (the phantom
    diamond) render below the hero. Proves the regression test is a real guard,
    not a tautology."""
    rom = variants["bigspr"]
    assert rom.exists(), f"{rom} not built (variant build did not run)"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"

    # the buggy build has the hero size bit SET (32x32) — the exact regression
    size = _oam_size_bit(runner, HERO_SLOT)
    assert size == 1, \
        "non-vacuity FAILED: -DBUGGY_SPRITE_SIZE hero size bit is CLEAR — the OAM " \
        "size check would not distinguish the 32x32 bug from the 16x16 fix"

    # and the phantom diamond actually RENDERS below the hero (hero-palette px > 0)
    shot = str(BUILD / "_sprsize_hero_buggy.png")
    runner.take_screenshot(shot)
    n_below = _count_hero_px_below(shot)
    assert n_below > 0, \
        "non-vacuity FAILED: the 32x32 (buggy) build rendered NO hero-palette " \
        f"pixels below the hero — the framebuffer diamond check would not catch " \
        f"the defect (n_below={n_below})"
    print(f"\nsprite-size non-vacuity OK: buggy 32x32 build has hero size_bit=1 "
          f"and {n_below} phantom-diamond px below the hero (both FAIL the fixed "
          f"test). shot={shot}")


# =============================================================================
# ENEMY PATROL (world-space wall-turn) + hero-enemy CONTACT.
# =============================================================================
# The enemies now PACE their corridor in world space at PATROL_SPEED px/frame,
# reversing when the next-step footprint would enter a wall (the SAME S3
# footprint_solid LUT). Hero-enemy CONTACT (world-box overlap) knocks the hero
# back to spawn (R_POSX/Y reset, speed 0) and ticks a HITS counter, with a
# post-respawn GRACE window so an enemy beat crossing the spawn cannot re-hit.
# Every assertion reads the LIVE world mirror / rendered framebuffer / WRAM
# counters (DBG_HITS), never a same-formula proxy. The visible proof of a hit is
# the hero teleporting back to spawn (Mode 7 has no spare BG text layer for a
# HITS HUD — deferred to S6; the debug mirror + the visible respawn are the S5
# outputs).
def _turn_to_heading(runner, target):
    """Hold LEFT/RIGHT to reach R_ANGLE == target (shortest direction)."""
    for _ in range(300):
        a = _angle(runner)
        if a == target:
            return
        d = (target - a) % 256
        runner.set_input(0, **({"left": True} if d <= 128 else {"right": True}))
        runner.run_frames(1)
    runner.set_input(0)


# =============================================================================
# PATROL MOVES + WALL-TURNS: each enemy's LIVE world pos
# paces along its beat and REVERSES, never entering a solid cell; the rendered
# red diamond visibly moves on the floor.
# =============================================================================
def test_patrol_moves_and_wall_turns(runner):
    """Over many frames read each enemy's LIVE world pos (DBG_ENE_BASE): it must
    MOVE along its pace AXIS (E0/E2 X, E1 Y), REVERSE direction at least once
    (wall-turn), and its footprint must NEVER occupy a solid cell (ground-truth
    LUT). Reads the live WRAM mirror per frame — the enemies move, so this tracks
    the live position, not a fixed table."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"

    seeds = [_live_world(runner, i) for i in range(ENEMY_COUNT)]
    prev_dir = [runner.read_u16(WR, ENE_DIR_BASE + i * 2) & 0xFFFF
                for i in range(ENEMY_COUNT)]
    moved = [False] * ENEMY_COUNT
    reversed_ = [False] * ENEMY_COUNT
    axis_violation = [0] * ENEMY_COUNT
    footprint_bad = [0] * ENEMY_COUNT

    for _ in range(400):
        runner.run_frames(1)
        for i in range(ENEMY_COUNT):
            wx, wy = _live_world(runner, i)
            # footprint never in a wall (the patrol wall-turn must hold)
            if _footprint_solid(wx, wy):
                footprint_bad[i] += 1
            # stays on its pace axis (perpendicular coord fixed)
            if ENEMY_AXIS[i] == 'x':
                if wy != seeds[i][1]:
                    axis_violation[i] += 1
                if wx != seeds[i][0]:
                    moved[i] = True
            else:
                if wx != seeds[i][0]:
                    axis_violation[i] += 1
                if wy != seeds[i][1]:
                    moved[i] = True
            d = runner.read_u16(WR, ENE_DIR_BASE + i * 2) & 0xFFFF
            if d != prev_dir[i]:
                reversed_[i] = True
            prev_dir[i] = d

    for i in range(ENEMY_COUNT):
        assert footprint_bad[i] == 0, \
            f"E{i} footprint entered a solid cell on {footprint_bad[i]} frames " \
            f"(patrol walked through a wall)"
        assert axis_violation[i] == 0, \
            f"E{i} left its pace axis on {axis_violation[i]} frames"
        assert moved[i], f"E{i} never moved (no patrol)"
        assert reversed_[i], f"E{i} never reversed (no wall-turn)"


def test_rendered_red_diamond_moves(runner):
    """The rendered enemy-red diamond visibly MOVES on the floor between two time
    points — reads the FRAMEBUFFER (the OUTPUT), not OAM/WRAM. Tracks the enemy's
    drawn sprite centre via OAM (live) and asserts enemy-red pixels are present at
    the (moved) centre at the later time, and that the centre actually changed."""
    rom = BUILD / "m7_dungeon.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    # pick an enemy that is ON-screen at boot (E0 near-start)
    i = 0
    ox0, oy0, _, _ = _enemy_oam(runner, i)
    shot0 = "/tmp/m7dungeon_s5_patrol_t0.png"
    runner.take_screenshot(shot0)
    red0 = _count_enemy_red_near(shot0, ox0 + _OBJ_HALF, oy0 + _OBJ_HALF, radius=12)

    runner.run_frames(40)                       # let it pace
    ox1, oy1, _, _ = _enemy_oam(runner, i)
    shot1 = "/tmp/m7dungeon_s5_patrol_t1.png"
    runner.take_screenshot(shot1)
    red1 = _count_enemy_red_near(shot1, ox1 + _OBJ_HALF, oy1 + _OBJ_HALF, radius=12)

    assert red0 >= 8, f"E{i} not rendered red at t0 ({red0} px)"
    assert red1 >= 8, f"E{i} not rendered red at its t1 centre ({red1} px)"
    assert (ox1, oy1) != (ox0, oy0), \
        f"E{i} drawn centre did not move ({(ox0, oy0)} -> {(ox1, oy1)}) — the red " \
        f"diamond is not pacing on the floor"
    print(f"\nS5 patrol render: E{i} centre {(ox0, oy0)}->{(ox1, oy1)} "
          f"(red {red0}->{red1}). shots: {shot0} {shot1}")


# =============================================================================
# CONTACT -> KNOCKBACK + HITS: drive the hero into a
# patrolling enemy; HITS increments and the hero world pos RESETS to spawn AND
# the hero sprite renders back at screen-centre on the spawn tile. Then hold the
# hero clear of all beats and assert HITS does NOT increment.
# =============================================================================
def test_contact_knockback_and_hits(runner):
    """Drive the hero HEAD-ON (no wall-hug) east into E0's pace line: HITS (WRAM
    mirror DBG_HITS) must INCREMENT and the hero world pos must RESET to the spawn
    cell (SPAWN_PX). The hero sprite must render at screen-centre (OAM slot 0 at
    HERO_X/Y) on the spawn tile. Reads the rendered OAM + the WRAM counter — the
    visible proof of the hit is the hero teleporting back to spawn."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"

    # baseline brightness at full display (no hit yet) — the flash is measured
    # against this so the assertion cannot pass on an always-dark capture.
    base_shot = "/tmp/m7dungeon_contact_base.png"
    runner.take_screenshot(base_shot)
    base_bright = _frame_brightness(base_shot)

    h0 = _hits(runner)
    # face pure EAST (heading 192) and drive straight into E0 on the centreline,
    # one frame at a time, stopping the FRAME the hit registers — so we read the
    # knockback pos before the (still-held) throttle drives the hero off spawn.
    _turn_to_heading(runner, 192)
    hit_pos = None
    for _ in range(160):
        runner.set_input(0, b=True)
        runner.run_frames(1)
        if _hits(runner) > h0:
            hit_pos = (_posx(runner), _posy(runner))
            break
    runner.set_input(0)

    assert _hits(runner) > h0, \
        f"HITS did not increment after driving into E0 ({h0} -> {_hits(runner)}) " \
        f"— hero pos {(_posx(runner), _posy(runner))}"
    # the hero world pos was reset to the spawn cell ON the hit frame (knockback)
    px, py = hit_pos
    assert abs(px - SPAWN_PX[0]) <= 2 and abs(py - SPAWN_PX[1]) <= 2, \
        f"hero not knocked back to spawn {SPAWN_PX} on the hit frame: at {(px, py)}"
    # the hero sprite renders at screen-centre (slot 0) on the spawn tile
    x, y, tile, attr = _oam(runner, HERO_SLOT)
    assert (x, y) == (HERO_X, HERO_Y), \
        f"hero sprite not re-centred after knockback: OAM {(x, y)}"
    assert tile == 0 and attr == HERO_ATTR, \
        f"hero sprite wrong after knockback: tile={tile} attr={attr:#04x}"

    # RENDERED get-hit FLASH (the non-vacuous rendered proof). The knockback-to-
    # spawn is invisible when the hero was already near spawn (its OAM is pinned at
    # centre — the old assert was vacuous). The visible cue is the whole screen
    # flashing DARK on contact (INIDISP dip), then fading back. Read the frame right
    # after the hit: it must be far darker than the pre-hit baseline; a build
    # without the flash stays at full brightness and fails this.
    runner.run_frames(1)              # let the NMI commit the flash brightness
    flash_shot = "/tmp/m7dungeon_contact_flash.png"
    runner.take_screenshot(flash_shot)
    flash_bright = _frame_brightness(flash_shot)
    assert flash_bright < base_bright * 0.4, \
        f"no get-hit flash: post-hit brightness {flash_bright:.1f} not << baseline " \
        f"{base_bright:.1f} (the screen must flash dark on contact)"
    # ...and it recovers to (near) full brightness as the fade completes.
    runner.run_frames(30)
    rec_shot = "/tmp/m7dungeon_contact_recovered.png"
    runner.take_screenshot(rec_shot)
    rec_bright = _frame_brightness(rec_shot)
    assert rec_bright > base_bright * 0.8, \
        f"flash did not recover: brightness {rec_bright:.1f} still low vs baseline " \
        f"{base_bright:.1f}"
    print(f"\ncontact: HITS {h0}->{_hits(runner)}, hero knocked back to {(px, py)} "
          f"== spawn {SPAWN_PX}; flash brightness {base_bright:.0f}->{flash_bright:.0f}"
          f"->{rec_bright:.0f}. shots: {flash_shot} {rec_shot}")


def test_standing_clear_no_hit(runner):
    """Drive the hero to a SAFE cell clear of every enemy beat (the GOAL cell via
    the committed route) and idle there: HITS must NOT increment. Proves contact
    only fires on a real overlap, not spuriously. Reads the WRAM HITS counter."""
    rom = BUILD / "m7_dungeon.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    route = json.loads(ROUTE_PATH.read_text())
    for st in route:
        btns = {b: True for b in st["buttons"]}
        runner.set_input(0, **btns)
        runner.run_frames(int(st["frames"]))
    runner.set_input(0)
    # at the goal (safe), hold clear for several seconds
    h_at_goal = _hits(runner)
    runner.run_frames(240)                       # 4s idle at the goal
    assert _hits(runner) == h_at_goal, \
        f"HITS incremented while standing clear at the goal " \
        f"({h_at_goal} -> {_hits(runner)}) — spurious contact"
    px, py = _posx(runner), _posy(runner)
    gx, gy = GOAL_PX
    assert abs(px - gx) <= 10 and abs(py - gy) <= 10, \
        f"hero not at the goal cell while idling clear: {(px, py)} vs {(gx, gy)}"


# =============================================================================
# GOAL IS SAFE: drive the committed maze_route.json to the
# goal; reaching the goal triggers NO hit (E2 relocated off the goal-adjacent
# cell). The route dodges the patrolling enemies by wall-hugging (S3 slide).
# =============================================================================
def test_goal_route_is_safe(runner):
    """Replay the committed maze_route.json: the hero reaches the GOAL cell with
    ZERO hits the whole way (the route wall-hugs past each patrolling enemy) AND
    every frame the hero footprint stays clear of solid cells. Asserts HITS == 0
    at the goal — reaching the exit is safe (E2 was relocated off the goal cell)."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    assert ROUTE_PATH.exists(), f"{ROUTE_PATH} missing"
    route = json.loads(ROUTE_PATH.read_text())

    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"
    assert _hits(runner) == 0, "HITS not zero at boot"

    gx, gy = GOAL_PX
    bad_frames = []
    frame = 0
    for st in route:
        btns = {b: True for b in st["buttons"]}
        for _ in range(int(st["frames"])):
            runner.set_input(0, **btns)
            runner.run_frames(1)
            frame += 1
            px, py = _posx(runner), _posy(runner)
            if _footprint_solid(px, py):
                bad_frames.append((frame, px, py))
    runner.set_input(0)

    assert not bad_frames, \
        f"route put the footprint in a wall on {len(bad_frames)} frames: " \
        f"{bad_frames[:5]}"
    px, py = _posx(runner), _posy(runner)
    assert abs(px - gx) <= 10 and abs(py - gy) <= 10, \
        f"route did not reach the goal: final {(px, py)} vs goal {(gx, gy)}"
    assert _hits(runner) == 0, \
        f"reaching the goal triggered {_hits(runner)} hit(s) — the route was " \
        f"supposed to dodge every enemy and the goal cell is supposed to be safe"
    print(f"\nS5 goal-safe: route reached goal {(px, py)} with HITS={_hits(runner)} "
          f"(0 hits, footprint clear on all {frame} frames)")


# =============================================================================
# GOAL WIN-CARD — reaching the GOAL cell draws a 3-star banner overlay (OAM slots
# 4-6) at screen top. NON-VACUOUS rendered check: absent at spawn, present at goal.
# =============================================================================
def _is_win_gold(rgb):
    """The win-card's gold sparkle-star body (rendered ~ (248,200,64)): bright +
    warm-YELLOW (high green), so it never collides with the enemy-warm band (g>130)
    or the grey knight hero. Measured on the emulator."""
    r, g, b = rgb
    return r >= 200 and g >= 150 and b <= 150 and (r - b) >= 70


def _count_win_gold_top(path, y_max=60):
    """Count win-card gold pixels in the top banner region (logical y < y_max)."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    n = 0
    for y in range(h):
        if y * 224 // h > y_max:
            continue
        for x in range(w):
            if _is_win_gold(px[x, y]):
                n += 1
    return n


def test_goal_win_card_overlay(runner):
    """Reaching the GOAL draws a 3-star win-card banner (OAM slots 4-6) at screen
    top. NON-VACUOUS rendered check: at spawn the banner is ABSENT (slots 4-6 parked
    at CULL_Y AND 0 gold pixels in the top region); after replaying the committed
    route to the goal it is PRESENT (slots un-parked AND gold star pixels render at
    the top). An OVERLAY only — no state/input change — so the route/collision/pause
    suites are undisturbed. Reads OAM + the rendered framebuffer."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    assert ROUTE_PATH.exists(), f"{ROUTE_PATH} missing"

    # PHASE 1: at spawn the win-card is ABSENT (parked slots + no gold pixels).
    runner.load_rom(str(rom), run_seconds=0.3)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot"
    runner.run_frames(4)
    spawn_shot = "/tmp/m7dungeon_win_spawn.png"
    runner.take_screenshot(spawn_shot)
    for s in (4, 5, 6):
        _, y, _, _ = _oam(runner, s)
        assert y == _CULL_Y, f"win slot {s} not parked at spawn (y={y}) — the card " \
            f"should only show on the goal"
    assert _count_win_gold_top(spawn_shot) == 0, \
        "win-card gold rendered at spawn — the card should appear only at the goal"

    # PHASE 2: replay the committed route to the goal; the win-card APPEARS.
    route = json.loads(ROUTE_PATH.read_text())
    for st in route:
        btns = {b: True for b in st["buttons"]}
        for _ in range(int(st["frames"])):
            runner.set_input(0, **btns)
            runner.run_frames(1)
    runner.set_input(0)
    runner.run_frames(2)
    gx, gy = GOAL_PX
    px, py = _posx(runner), _posy(runner)
    assert abs(px - gx) <= 10 and abs(py - gy) <= 10, \
        f"route did not reach the goal: {(px, py)} vs {(gx, gy)}"
    goal_shot = "/tmp/m7dungeon_win_goal.png"
    runner.take_screenshot(goal_shot)
    active = [s for s in (4, 5, 6) if _oam(runner, s)[1] != _CULL_Y]
    assert len(active) == 3, \
        f"win-card banner not drawn at the goal (un-parked win slots: {active})"
    gold = _count_win_gold_top(goal_shot)
    assert gold >= 20, \
        f"win-card gold not rendered at the goal (only {gold} gold px in the banner)"
    print(f"\nwin-card: absent at spawn (0 gold) -> present at goal ({gold} gold px, "
          f"slots {active}). shots: {spawn_shot} {goal_shot}")


# =============================================================================
# PAUSE — START freezes the world + enemies (the frame still renders); a second
# START resumes. The enemies patrol continuously, so their live world pos is the
# motion witness: it advances while running, holds while paused.
# =============================================================================
def test_start_pauses_and_resumes(runner):
    """START toggles pause. While RUNNING the enemies pace (live world pos moves)
    and a held throttle drives the hero; while PAUSED both freeze and the rendered
    frame does not change; a second START resumes. Reads the WRAM pause flag +
    live enemy/hero mirrors + the framebuffer."""
    rom = BUILD / "m7_dungeon.sfc"
    assert rom.exists(), f"{rom} not built — run `make m7_dungeon` first"
    _boot_settled(runner, rom)
    assert _paused(runner) == 0, "should boot unpaused"

    # RUNNING: the enemy paces over 40 frames (motion witness).
    e_run0 = _live_world(runner, 0)
    runner.run_frames(40)
    assert _live_world(runner, 0) != e_run0, "enemy did not pace while running"

    # tap START -> PAUSED
    _hold(runner, 2, start=True)
    runner.run_frames(2)
    assert _paused(runner) == 1, "START did not pause"

    p_pause = (_posx(runner), _posy(runner))
    e_pause = _live_world(runner, 0)
    shot_a = "/tmp/m7dungeon_pause_a.png"
    runner.take_screenshot(shot_a)
    sa = _grid_samples(shot_a)

    # while paused: hold the throttle AND let time pass — nothing moves, frame holds
    runner.set_input(0, b=True)
    runner.run_frames(50)
    runner.set_input(0)
    assert (_posx(runner), _posy(runner)) == p_pause, \
        f"hero moved while paused: {p_pause} -> {(_posx(runner), _posy(runner))}"
    assert _live_world(runner, 0) == e_pause, \
        f"enemy moved while paused: {e_pause} -> {_live_world(runner, 0)}"
    shot_b = "/tmp/m7dungeon_pause_b.png"
    runner.take_screenshot(shot_b)
    frac = _frac_changed(sa, _grid_samples(shot_b))
    assert frac < 0.03, f"rendered frame changed while paused ({frac:.1%} of samples)"

    # tap START -> RESUME; the enemy paces again
    _hold(runner, 2, start=True)
    runner.run_frames(2)
    assert _paused(runner) == 0, "second START did not resume"
    e_res0 = _live_world(runner, 0)
    runner.run_frames(40)
    assert _live_world(runner, 0) != e_res0, "world did not resume after unpause"
    print(f"\npause: enemy paced running, froze at {e_pause} while paused "
          f"(frame delta {frac:.1%}), paced again on resume. shots: {shot_a} {shot_b}")
