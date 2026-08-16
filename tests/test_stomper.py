"""stomper — stomp-vs-hurt resolution on top of jumper physics, vs an oracle.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner import, no wall-clock surface.
Every boot is `Machine(rom).advance(N)` — an absolute frame by construction —
and every scripted drive is a fixed per-frame input list, so the whole
trajectory is a pure function of the replay triple. The reference test uses
closed-loop retry bots because its input path is wall-clock; under the Machine
the same recipes become exact scripts with no retries, found in the oracle and
asserted frame for frame.

WHAT THIS RAIL IS (its done-condition list, templates/stomper/main.asm:22-27):

    - boots; both enemies pace their exact beats; FOES 00002
    - landing on an enemy: it disappears (sprite culled, magenta drops),
      the player BOUNCES (y dips then rises ~17px), FOES ticks down (text)
    - side contact: knockback to spawn (enemy survives)
    - both stomped -> "CLEAR" printed; the game keeps running

THE ORACLE is an independent Python re-implementation of the whole game tick
(move -> jump -> integrator -> patrols -> one-contact resolution), seeded
from nothing and compared against hardware OAM EVERY FRAME of every drive —
the jumper module's discipline extended to the enemy layer. The world it
probes is rebuilt in-module from the level's four mset loops (shared
code with the generator: none), and the tilemap test closes the loop by
requiring VRAM == blob == this derivation.

THE TWO LANDING PATHS, and why both stomp tests exist: the integrator lands via a <=1
px/frame STAND probe (arc-top approaches) or via the fast-fall SNAP, and the
stomp classifier reads the approach velocity — so this build's two stomp
scripts pin one contact in each speed class:
    E1: a full-jump descent contacting at vy = 4.00 px/f (the MAX_FALL
        clamp — the snap class);
    E2: the reference's own wall-gap recipe contacting at vy = 0.75 px/f
        two ticks past apex (the arc-top class).
A stomp-resolution plant must turn BOTH red or say why one is out of reach.

FRAME ACCOUNTING (measured here, the shared convention): hardware OAM and
the committed text cells after advance(N) reflect the state after tick
N - 1 — the constant one-commit presentation lag of the park point. The
oracle is indexed accordingly (OAM_LAG). OAM is read BEFORE each screenshot:
a parked OAM read and the NEXT shot describe the same committed frame, while
a read AFTER a shot is one commit ahead.

NO PERIODIC-BG TRAP: this arena never scrolls (the scroll pin is the
feature's enter-time write), so no displacement is recovered anywhere and
the phase-alias discipline does not arise — motion claims ride on OAM and
pixel bboxes at absolute positions.
"""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "stomper.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "st" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam
W = MemoryType.SnesWorkRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="play"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_CHR = _sym("ES_V_ST_CHR")["start"]           # BG CHR page, VRAM words
V_MAP = _sym("ES_V_ST_MAP")["start"]           # BG tilemap base, VRAM words
V_OBJ = _sym("ES_V_ST_OBJ_CHR")["start"]       # OBJ CHR page, VRAM words
V_TEXT = _sym("ES_V_TEXT_MAP")["start"]        # BG3 text map base, VRAM words
C_PAL = _sym("ES_C_ST_PAL")["start"]           # BG palette group 0, CGRAM
C_OBJ = _sym("ES_C_ST_OBJ_PAL")["start"]       # OBJ palettes 0+1, CGRAM words
O_ACTORS = _sym("ES_O_ACTORS")["start"]        # player, e1, e2, pad
OAM_SHADOW = _sym("ES_OAM_SHADOW", scene=None)["start"]

# --- the rail's geometry (game/stomper/stomper.inc, re-derived) --------------
GRAVITY, MAX_FALL, JUMP_VEL, BOUNCE = 0x40, 0x400, 0x480, 0x300
SPEED, PATROL_SPEED, STOMP_DEPTH = 2, 1, 5
E1_Y, E2_Y = 200, 152
SPAWN = (200, 200)
PARK_Y = 240                            # oam_park_all's off-screen row
A, RIGHT, LEFT = 1 << 7, 1 << 8, 1 << 9

TXT_ATTR = (7 << 10) | (1 << 13)
HUD_ROW, DIGITS_C = 1, 6
CLEAR_ROW, CLEAR_C = 13, 13
UNITS_CELL = V_TEXT + HUD_ROW * 32 + DIGITS_C + 4       # the live FOES digit
CLEAR_CELLS = [V_TEXT + CLEAR_ROW * 32 + CLEAR_C + i for i in range(5)]


def _glyph(ch):
    return (ord(ch) - 0x20) | TXT_ATTR


# --- the world, rebuilt from the level's four mset loops -----------------
# (templates/stomper/main.asm:113-151 — ground row 26, border columns 0/31
# rows 0..25, low walls columns 10/20 rows 24..25, platform row 20 cols 4..8;
# tile 2 everywhere, flags[2] = SOLID. Shared code with the generator: none.)
def _derive_world():
    w = [[0] * 32 for _ in range(32)]
    for x in range(32):
        w[26][x] = 2
    for y in range(26):
        w[y][0] = 2
        w[y][31] = 2
    for y in range(24, 26):
        w[y][10] = 2
        w[y][20] = 2
    for x in range(4, 9):
        w[20][x] = 2
    return w


WORLD = _derive_world()
SOLID_CELLS = sum(v == 2 for row in WORLD for v in row)          # 93


# =============================================================================
# THE ORACLE — the whole game tick, independently re-implemented
# =============================================================================
def _solid(x, y):
    return WORLD[(y >> 3) & 31][(x >> 3) & 31] == 2


def _solid_box(x, y):
    return any(_solid((x + dx) & 0xFFFF, (y + dy) & 0xFFFF)
               for dy in (0, 7) for dx in (0, 7))


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _xba(v):
    return ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)


class Oracle:
    def __init__(s):
        s.px, s.pyf, s.vy, s.grounded = SPAWN[0], SPAWN[1] << 8, 0, 0
        s.pyi = SPAWN[1]
        s.e = [[120, 1, 1], [48, 1, 1]]          # x, dir, alive per enemy
        s.foes, s.hurts = 2, 0
        s.events = []                            # (tick, kind, enemy, ...)

    def snap(s):
        return (s.px, s.pyi, s.vy, s.grounded,
                tuple(s.e[0]), tuple(s.e[1]), s.foes, s.hurts)

    def tick(s, t, cur, press):
        # --- move_player (held state; one box test at the tentative x) ---
        s.pyi = (s.pyf >> 8) & 0xFF
        newx = s.px
        if cur & RIGHT:
            newx = (newx + SPEED) & 0xFFFF
        if cur & LEFT:
            newx = (newx - SPEED) & 0xFFFF
        if not _solid_box(newx, s.pyi):
            s.px = newx
        # --- do_jump (edge, grounded-gated) ---
        if (press & A) and s.grounded:
            s.vy = (-JUMP_VEL) & 0xFFFF
            s.grounded = 0
        # --- phys_step: the reference integrator, both landing paths ---
        if _s16(s.vy) >= 0:                      # falling arm
            py = (s.pyf >> 8) & 0xFF
            if _solid_box(s.px, (py + 1) & 0xFFFF):
                s.vy, s.grounded = 0, 1          # STAND: pixel-exact rest
                s.pyf &= 0xFF00
            else:
                vy = _s16(s.vy) + GRAVITY
                if vy >= MAX_FALL:
                    vy = MAX_FALL
                s.vy = vy & 0xFFFF
                tent = (s.pyf + s.vy) & 0xFFFF
                newy = (tent >> 8) & 0xFF
                if _solid_box(s.px, newy):       # SNAP: bottom -> tile top
                    top = (((newy + 7) >> 3) << 3) - 8
                    s.pyf = _xba(top & 0xFFFF)
                    s.vy, s.grounded = 0, 1
                else:
                    s.pyf, s.grounded = tent, 0
        else:                                    # rising arm
            s.grounded = 0
            s.vy = (s.vy + GRAVITY) & 0xFFFF
            tent = (s.pyf + s.vy) & 0xFFFF
            newy = (tent >> 8) & 0xFF
            if _solid_box(s.px, newy):           # head bump
                row = ((newy >> 3) << 3) + 8
                s.pyf = _xba(row & 0xFFFF)
                s.vy = 0
            else:
                s.pyf = tent
        s.pyi = (s.pyf >> 8) & 0xFF
        # --- patrols (alive-gated; wall OR ledge turns, no move) ---
        for i, ey in ((0, E1_Y), (1, E2_Y)):
            ex, edir, alive = s.e[i]
            if not alive:
                continue
            nx = (ex + PATROL_SPEED) & 0xFFFF if edir \
                else (ex - PATROL_SPEED) & 0xFFFF
            leadx = (nx + 7) & 0xFFFF if edir else nx
            if _solid_box(nx, ey) or not _solid(leadx, ey + 8):
                s.e[i][1] ^= 1
            else:
                s.e[i][0] = nx
        # --- contact resolution: at most ONE per frame, enemy 1 first ---
        for i, ey in ((0, E1_Y), (1, E2_Y)):
            ex, edir, alive = s.e[i]
            if not alive:
                continue
            if abs(s.px - ex) >= 8 or abs(s.pyi - ey) >= 8:
                continue
            v = _s16(s.vy)
            if v > 0 and (s.pyi + 8 - ey) <= STOMP_DEPTH:
                s.e[i][2] = 0                    # STOMP: kill + bounce
                s.vy = (-BOUNCE) & 0xFFFF
                s.foes -= 1
                s.events.append((t, "stomp", i, s.pyi, v))
            else:
                s.px, s.pyf = SPAWN[0], SPAWN[1] << 8
                s.vy, s.grounded = 0, 0
                s.hurts += 1
                s.pyi = SPAWN[1]
                s.events.append((t, "hurt", i))
            break


def run_oracle(script):
    """script: [(frames, buttons), ...]. Returns (oracle, [snap after tick
    1..N]) — press is derived per frame exactly as input_read does."""
    g = Oracle()
    snaps, prev, t = [], 0, 0
    for frames, cur in script:
        for _ in range(frames):
            t += 1
            g.tick(t, cur, cur & ~prev)
            prev = cur
            snaps.append(g.snap())
    return g, snaps


# =============================================================================
# THE SCRIPTS — found in the oracle, asserted on the emulator
# =============================================================================
# Every S_* script INCLUDES the boot segment; the emulator side boots with
# the fixture's advance(BOOT) and then drives script[1:].
BOOT = 90                                # the absolute boot frame

# Mount the col-20 low wall from spawn: 16 left to the wall face (px 168),
# hop (A+left 6), coast to the wall top (px 164, y 184).
_MOUNT = [(16, LEFT), (6, A | LEFT), (40, 0)]

# ...then drop into E1's beat: wait, walk off the wall's left edge, land at
# px 150, y 200 (E1 far left, no contact on the way down).
_ENTER_BEAT = _MOUNT + [(30, 0), (7, LEFT), (60, 0)]

# E1 STOMP (the fast-fall class): from px 150 in the beat, a full jump in
# place; E1 walks under during the arc and the descent lands on its head at
# terminal velocity. Oracle: stomp at tick 285, pyi 195, vy $400 = 4.00 px/f.
S_E1_STOMP = [(BOOT, 0)] + _ENTER_BEAT + [(2, 0), (1, A), (50, 0)]

# SIDE CONTACT (enemy alive): drop into the beat while E1 is walking back
# toward it and STAND — a grounded player cannot stomp (vy = 0), so the
# patroller walking into us is a guaranteed HURT. Oracle: hurt at tick 283.
S_HURT = [(BOOT, 0)] + _MOUNT + [(90, 0), (7, LEFT), (60, 0)]

# THE FULL WIN: E1 stomp, walk left across the dead enemy's beat, hop onto
# the col-10 wall, then the reference's own E2 recipe — jump straight up
# through the wall/platform gap as E2 comes off its left turn, steer left
# only after the apex (12 frames). Oracle: E2 stomp at tick 411, pyi 147,
# vy $C0 = 0.75 px/f (two ticks past apex — the arc-top class).
S_WIN = S_E1_STOMP + [(40, LEFT), (6, A | LEFT), (40, 0),
                      (2, 0), (1, A), (12, 0), (30, LEFT), (30, 0)]

# After the E1 kill: walk left THROUGH the old beat (the hurt script's
# ground, now transparent) to the col-10 wall face.
S_THROUGH = S_E1_STOMP + [(40, LEFT), (20, 0)]

# The commit lag: hardware OAM / committed text after advance(N) show the
# state after tick N - OAM_LAG. Measured by the beats test below over 140
# frames of both enemies' cycles (and re-measured by every trajectory case).
OAM_LAG = 1

# --- the picture -------------------------------------------------------------
# Mesen hands back 256x239; the active 224 scanlines start at PNG row 7
# (the sibling rails' measured constant, re-verified here by the boot test:
# the sprite with OAM y 200 must occupy PNG rows 207..214 — the OBJ +1
# scanline rule plus the +6 offset — and the ground row 26 must start at
# PNG row 215 = 7 + 208, which is the VOFS -1 identity world row = OAM row).
PIC_Y0, PIC_W, PIC_H = 7, 256, 239

BLACK = (0, 0, 0)
GREY = (115, 115, 115)                   # BG_GREY $39CE through Mesen's 5->8
RED = (255, 0, 0)                        # OBJ_RED $001F
MAGENTA = (255, 0, 255)                  # OBJ_MAGEN $7C1F
WHITE = (255, 255, 255)                  # text colour 3 $7FFF


@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle."""
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make stomper` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


# --- helpers -----------------------------------------------------------------
def _pad(cur):
    d = {}
    if cur & A:
        d["a"] = True
    if cur & RIGHT:
        d["right"] = True
    if cur & LEFT:
        d["left"] = True
    return d


def _actors(m):
    """Hardware OAM for the three actor slots: ((px,py),(e1x,e1y),(e2x,e2y))."""
    b = m.read_bytes(O, O_ACTORS * 4, 12)
    return (b[0], b[1]), (b[4], b[5]), (b[8], b[9])


def _assert_frame(m, frame, snaps, where):
    """One frame's whole actor set against the oracle (lag applied)."""
    w = snaps[frame - 1 - OAM_LAG]
    p, e1, e2 = _actors(m)
    exp_p = (w[0] & 0xFF, w[1])
    assert p == exp_p, (
        f"{where} frame {frame}: player OAM {p}, oracle {exp_p}")
    if w[4][2]:
        assert e1 == (w[4][0] & 0xFF, E1_Y), (
            f"{where} frame {frame}: enemy1 OAM {e1}, oracle x {w[4][0]}")
    else:
        assert e1[1] == PARK_Y, (
            f"{where} frame {frame}: enemy1 dead but not parked ({e1})")
    if w[5][2]:
        assert e2 == (w[5][0] & 0xFF, E2_Y), (
            f"{where} frame {frame}: enemy2 OAM {e2}, oracle x {w[5][0]}")
    else:
        assert e2[1] == PARK_Y, (
            f"{where} frame {frame}: enemy2 dead but not parked ({e2})")


def _drive(m, script, snaps, where, start=BOOT):
    """Advance through `script` (which INCLUDES the boot segment), asserting
    every frame's actor OAM against the oracle. Returns the final frame."""
    frame = start
    for frames, cur in script:
        pad = _pad(cur)
        for _ in range(frames):
            m.advance(1, pad1=pad)
            frame += 1
            _assert_frame(m, frame, snaps, where)
    return frame


def _pixels(m, name):
    path = m.take_screenshot(str(BUILD / "shots" / f"st_{name}.png"))
    with Image.open(path) as im:
        return list(im.convert("RGB").getdata())


def _census(px):
    counts = {}
    for p in px:
        counts[p] = counts.get(p, 0) + 1
    return counts


def _bbox(px, colour):
    pts = [(i % PIC_W, i // PIC_W) for i, p in enumerate(px) if p == colour]
    assert pts, f"no {colour} pixels on screen"
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return len(pts), min(xs), max(xs), min(ys), max(ys)


def _vword(m, word_addr):
    b = m.read_bytes(V, word_addr * 2, 2)
    return b[0] | (b[1] << 8)


# =============================================================================
# 1. THE UPLOADS — destination regions, byte for byte
# =============================================================================

def test_bg_character_block_is_the_destination_of_the_blob(fresh):
    """VRAM at the claimed CHR base vs st_bg_chr.bin — all three tiles,
    including the two EMPTY ones (rule 5: uploaded explicitly, so the whole
    claim is read, not just the tile that shows a colour)."""
    want = (ASSETS / "st_bg_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_CHR * 2, len(want)))
    assert got == want, (
        f"BG CHR at VRAM word ${V_CHR:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")


def test_obj_character_block_is_the_destination_of_the_blob(fresh):
    want = (ASSETS / "st_obj_chr.bin").read_bytes()
    got = bytes(fresh.read_bytes(V, V_OBJ * 2, len(want)))
    assert got == want, (
        f"OBJ CHR at VRAM word ${V_OBJ:04X} is not the blob — "
        f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")


def test_palettes_are_the_destinations_of_their_blobs(fresh):
    """CGRAM at both claimed bases — BG group 0 (word 0 IS the backdrop) and
    the two OBJ palettes in one 32-word claim (player red at 128+1, enemy
    magenta at 144+1)."""
    for label, base, blob in (("bg", C_PAL, "st_bg_pal.bin"),
                              ("obj", C_OBJ, "st_obj_pal.bin")):
        want = (ASSETS / blob).read_bytes()
        got = bytes(fresh.read_bytes(C, base * 2, len(want)))
        assert got == want, (
            f"{label} palette at CGRAM word {base} is not {blob} — "
            f"{sum(a != b for a, b in zip(got, want))} of {len(want)} differ")
    # the two discriminating entries, named: red vs magenta
    obj = bytes(fresh.read_bytes(C, C_OBJ * 2, 64))
    assert obj[2] | (obj[3] << 8) == 0x001F, "OBJ pal 0 colour 1 is not red"
    assert obj[34] | (obj[35] << 8) == 0x7C1F, "OBJ pal 1 colour 1 is not magenta"


def test_tilemap_is_the_arena_from_the_world_blob(fresh):
    """THE SINGLE-SOURCE PROPERTY, closed in both directions: all 1,024 VRAM
    tilemap words == the st_world blob's bytes == this module's own rebuild of
    the level's four mset loops. The same blob is what col_map probes, so the
    display the player sees and the walls the physics enforces cannot
    disagree — and neither can drift from the declared level without this
    failing."""
    blob = (ASSETS / "st_world.bin").read_bytes()
    assert len(blob) == 1024
    derived = bytes(v for row in WORLD for v in row)
    assert blob == derived, "st_world.bin is not the reference level"
    raw = bytes(fresh.read_bytes(V, V_MAP * 2, 1024 * 2))
    bad = []
    for i in range(1024):
        word = raw[2 * i] | (raw[2 * i + 1] << 8)
        if word != blob[i]:
            bad.append((i % 32, i // 32, word, blob[i]))
    assert not bad, (
        f"{len(bad)} of 1024 tilemap cells differ from the world blob; "
        f"first 8 (col,row,got,want): {bad[:8]}")


# =============================================================================
# 2. THE BOOT PICTURE — the composited frame, census-exact
# =============================================================================

def test_boot_frame_shows_the_arena_actors_and_hud(fresh):
    """The whole boot frame accounted for, pixel by pixel: 93 solid cells x
    64 grey px, exactly 64 red (the player at spawn), exactly 128 magenta
    (two live patrollers at their oracle positions), white HUD glyphs, black
    elsewhere — and NOTHING else. OAM is read BEFORE the shot and
    must agree with both the oracle and the drawn bboxes. The player bbox at
    PNG rows 207..214 with the ground starting at row 215 is the VOFS -1
    identity (world row = screen row = OAM row) rendered visible."""
    _, snaps = run_oracle([(BOOT, 0)])
    w = snaps[BOOT - 1 - OAM_LAG]
    p, e1, e2 = _actors(fresh)               # read BEFORE the screenshot
    assert p == (SPAWN[0], SPAWN[1])
    assert e1 == (w[4][0], E1_Y)
    assert e2 == (w[5][0], E2_Y)
    px = _pixels(fresh, "boot")
    counts = _census(px)
    assert counts[GREY] == SOLID_CELLS * 64, (
        f"terrain: {counts.get(GREY)} grey px, want {SOLID_CELLS * 64}")
    assert counts[RED] == 64, f"player: {counts.get(RED)} red px, want 64"
    assert counts[MAGENTA] == 128, (
        f"enemies: {counts.get(MAGENTA)} magenta px, want 128")
    assert counts.get(WHITE, 0) > 100, "the FOES HUD is not on screen"
    known = (counts[GREY] + counts[RED] + counts[MAGENTA]
             + counts.get(WHITE, 0) + counts.get(BLACK, 0))
    assert known == PIC_W * PIC_H, "the picture holds unexpected colours"
    n, x0, x1, y0, y1 = _bbox(px, RED)
    assert (n, x0, x1) == (64, SPAWN[0], SPAWN[0] + 7)
    assert (y0, y1) == (PIC_Y0 + SPAWN[1], PIC_Y0 + SPAWN[1] + 7), (
        "the player's drawn rows disagree with OAM y — the OBJ row identity")
    ground_row = PIC_Y0 + 208
    assert px[ground_row * PIC_W + 128] == GREY, (
        "world row 208 (ground top) is not at PNG row 215 — the VOFS -1 "
        "identity broke")
    assert px[(ground_row - 1) * PIC_W + 128] == BLACK, (
        "the pixel above the ground top is not backdrop")
    # the FOES counter's five cells in VRAM: 0 0 0 0 2
    cells = [_vword(fresh, V_TEXT + HUD_ROW * 32 + DIGITS_C + i)
             for i in range(5)]
    assert cells == [_glyph(c) for c in "00002"], (
        f"the boot counter does not read 00002: {[hex(c) for c in cells]}")


# =============================================================================
# 3. THE BEATS — both enemies pace exactly, the whole cycle, vs the oracle
# =============================================================================

def test_both_enemies_pace_their_exact_beats(boot):
    """140 idle frames, hardware OAM for BOTH enemies asserted against the
    patrol oracle EVERY frame — covering, for each enemy, a right sweep, the
    turn at the wall/ledge, a left sweep and the other turn. The observed
    extremes must be the reference's documented beats (E1 88..152 between the
    low walls; E2 32..64 on the platform). This is also the module's
    frame<->tick calibration: OAM_LAG is proven over every sampled frame,
    and any drift between the oracle's patrol model (wall probe + leading-
    corner ledge probe) and the shipped ASM fails on the exact frame it
    diverges."""
    _, snaps = run_oracle([(BOOT + 140, 0)])
    m = boot()
    seen1, seen2 = set(), set()
    frame = BOOT
    for _ in range(140):
        m.advance(1)
        frame += 1
        _assert_frame(m, frame, snaps, "beats")
        _, e1, e2 = _actors(m)
        seen1.add(e1[0])
        seen2.add(e2[0])
    assert (min(seen1), max(seen1)) == (88, 152), (
        f"enemy 1's observed beat is {min(seen1)}..{max(seen1)}, not 88..152")
    assert (min(seen2), max(seen2)) == (32, 64), (
        f"enemy 2's observed beat is {min(seen2)}..{max(seen2)}, not 32..64")


# =============================================================================
# 4. THE JUMP — the integrator's full cycle on open ground (both paths' base)
# =============================================================================

def test_jump_full_cycle_lands_snap_exact_and_rests_stable(boot):
    """A single A press at spawn: the WHOLE trajectory equals the oracle —
    take-off, every ascent step, the 38 px apex, every descent step, THE
    LANDING FRAME (the fast-fall SNAP: the descent ends at the MAX_FALL
    clamp and the box bottom snaps to the ground row exactly), then ten rest
    frames at exactly (200, 200) each (the STAND probe holding rest stable —
    the other landing path, exercised every rest frame). Apex and landing
    are both asserted (the reference's apex-only lesson)."""
    script = [(BOOT, 0), (1, A), (55, 0)]
    _, snaps = run_oracle(script)
    m = boot()
    _drive(m, script[1:], snaps, "jump")
    ys = [s[1] for s in snaps[BOOT:]]
    assert min(ys) == SPAWN[1] - 39, (
        f"apex {min(ys)} is not 39 px above rest — the arc the jumper port "
        f"measured")
    # the oracle's own landing: find the first return to rest...
    land = next(i for i, s in enumerate(snaps[BOOT + 1:], BOOT + 1)
                if s[1] == SPAWN[1] and s[3] == 1)
    assert snaps[land - 1][1] != SPAWN[1], "no snap frame — trajectory wrong"
    # ...and the tail is at rest EVERY frame (grounded, pixel-exact)
    for s in snaps[land:]:
        assert (s[0], s[1], s[3]) == (SPAWN[0], SPAWN[1], 1), (
            "the rest tail is not stable — the stand probe flickered")


# =============================================================================
# 5. THE STOMP, fast-fall class — kill, cull, bounce, count (enemy 1)
# =============================================================================

def test_stomp_kills_culls_bounces_and_counts(boot):
    """The rail's headline, at the SNAP-class approach speed: a full-jump
    descent contacts enemy 1's head at vy = $400 = 4.00 px/f (the MAX_FALL
    clamp — the oracle's event pins both the contact tick and the speed
    class). Asserted across the whole cycle, every frame on hardware OAM:
    approach -> the exact contact frame -> the enemy PARKED on the next
    commit (the fixed-slot cull) -> the bounce (y dips to the kill pixel
    then rises; apex >= 10 px above it, oracle-exact) -> re-landing -> rest.
    The FOES units cell reprints '1' (destination VRAM + its write counter);
    enemy 2 is untouched all the while; the magenta census halves."""
    g, snaps = run_oracle(S_E1_STOMP)
    stomps = [e for e in g.events if e[1] == "stomp"]
    assert stomps and not [e for e in g.events if e[1] == "hurt"]
    tick_k, _, enemy, kill_pyi, kill_vy = stomps[0]
    assert enemy == 0 and kill_vy == MAX_FALL, (
        "the script no longer contacts at the terminal clamp — the fast-fall "
        "class claim would be vacuous")
    m = boot()
    w0 = m.writes(V, UNITS_CELL * 2)         # low byte of the live cell
    frame = _drive(m, S_E1_STOMP[1:], snaps, "stomp1")
    # bounce shape from the oracle: dip to kill_pyi, rise to the bounce apex
    ys = [s[1] for s in snaps[tick_k - 1:tick_k + 20]]
    assert ys[0] == kill_pyi and min(ys) <= kill_pyi - 10, (
        f"no bounce after the stomp: {ys}")
    # the cull + the count, on the final committed state
    p, e1, e2 = _actors(m)
    assert e1[1] == PARK_Y, "enemy 1 not parked after the stomp"
    assert e2 == (snaps[frame - 1 - OAM_LAG][5][0], E2_Y), (
        "enemy 2 was perturbed by enemy 1's death")
    assert _vword(m, UNITS_CELL) == _glyph("1"), "FOES did not reprint to 1"
    assert m.writes(V, UNITS_CELL * 2) == w0 + 1, (
        "the FOES cell was rewritten more (or less) than the one reprint")
    px1 = _pixels(m, "poststomp")
    assert _census(px1)[MAGENTA] == 64, "the dead enemy still draws"
    assert _census(px1)[RED] == 64, "the player vanished"


# =============================================================================
# 6. SIDE CONTACT, enemy alive — knockback to spawn, no kill
# =============================================================================

def test_side_contact_knocks_back_without_killing(boot):
    """The other contact class: standing in the beat (vy = 0 — a grounded
    player cannot stomp), the patroller walks into us. The oracle pins the
    contact tick; on its commit the player's OAM snaps to spawn (200, 200)
    — the knockback teleport — and enemy 1 SURVIVES: alive at its oracle
    position on every subsequent frame, magenta census still 128, and the
    FOES cell not rewritten (its write counter holds). The drive continues
    past the contact so 'the enemy keeps pacing' is asserted rather than
    assumed."""
    script = S_HURT
    g, snaps = run_oracle(script)
    hurts = [e for e in g.events if e[1] == "hurt"]
    assert hurts and not [e for e in g.events if e[1] == "stomp"]
    m = boot()
    w0 = m.writes(V, UNITS_CELL * 2)
    frame = _drive(m, script[1:], snaps, "hurt")
    assert snaps[frame - 1][7] == 1, "oracle says the hurt never happened"
    p, e1, e2 = _actors(m)
    assert p == SPAWN, f"no knockback: player OAM {p}"
    assert e1 == (snaps[frame - 1 - OAM_LAG][4][0], E1_Y), (
        "enemy 1 did not survive the side contact")
    assert _vword(m, UNITS_CELL) == _glyph("2"), "FOES changed on a hurt"
    assert m.writes(V, UNITS_CELL * 2) == w0, (
        "the FOES cell was rewritten by a hurt")
    px = _pixels(m, "posthurt")
    assert _census(px)[MAGENTA] == 128, "an enemy died on a side contact"


# =============================================================================
# 7. THE DEAD ENEMY IS TRANSPARENT — the enemy-gone regime of the same ground
# =============================================================================

def test_dead_enemy_is_transparent_and_walls_still_stand(boot):
    """After the enemy-1 kill, the SAME ground that hurt the standing player
    in the test above is walked straight through: 40 frames of left crossing
    the whole old beat with the oracle confirming no respawn (the player's x
    marches monotonically to the col-10 wall face at 88 and STOPS there —
    the wall still works; dead enemies don't). The per-frame oracle equality
    plus the endpoint make the claim: contact resolution is gated on the
    alive flag, not on position history."""
    script = S_THROUGH
    g, snaps = run_oracle(script)
    assert len([e for e in g.events if e[1] == "stomp"]) == 1
    assert not [e for e in g.events if e[1] == "hurt"], (
        "the walk-through got hurt in the oracle — the script rotted")
    m = boot()
    frame = _drive(m, script[1:], snaps, "through")
    p, e1, _ = _actors(m)
    assert p == (88, 200), (
        f"the walk through the dead enemy's beat ended at {p}, not at the "
        f"col-10 wall face (88, 200)")
    assert e1[1] == PARK_Y


# =============================================================================
# 8. THE WIN — the arc-top stomp on enemy 2, and CLEAR
# =============================================================================

def test_arc_top_stomp_wins_and_clear_prints(boot):
    """The reference's own platform-enemy recipe (jump straight up through the
    wall/platform gap as E2 comes off its left turn, steer left after the
    apex), contacting at vy = $C0 = 0.75 px/f two ticks past apex — THE
    ARC-TOP CLASS, the second landing-path speed regime the module header
    names. Whole-script per-frame OAM equality, then the win surface:

      BEFORE the closing stomp: the five CLEAR cells hold the space word
      (the enter-time clear) and their write counters are the enter-time
      baseline — CLEAR is not on screen with a foe alive (the reference's own
      negative assertion).
      AFTER: FOES reads '0', the five cells spell C L E A R (one write
      each — the one-cell-per-frame pump, landing over the five frames
      after the stomp), the magenta census is ZERO, both enemy slots are
      parked, and the game KEEPS RUNNING (the player still answers the
      oracle for 30 more frames)."""
    tail = 40                                # keeps-running frames past S_WIN
    script = S_WIN + [(tail, 0)]
    g, snaps = run_oracle(script)
    stomps = [e for e in g.events if e[1] == "stomp"]
    assert [e[2] for e in stomps] == [0, 1] and not [
        e for e in g.events if e[1] == "hurt"]
    t2, _, _, pyi2, vy2 = stomps[1]
    assert vy2 <= 0x180, (
        f"E2 contact at vy={vy2:#x} is not the arc-top class — the script "
        f"rotted and the two-landing-paths coverage claim would be vacuous")
    m = boot()
    base_w = [m.writes(V, c * 2) for c in CLEAR_CELLS]
    # drive, checking the negative just BEFORE the closing stomp commits
    pre = []
    frame = BOOT
    for frames, cur in script[1:]:
        pad = _pad(cur)
        for _ in range(frames):
            if frame + 1 == t2:              # the stomp tick's frame
                pre = [_vword(m, c) for c in CLEAR_CELLS]
                pre_w = [m.writes(V, c * 2) for c in CLEAR_CELLS]
                assert pre == [TXT_ATTR] * 5, (
                    f"CLEAR cells not blank with a foe alive: {pre}")
                assert pre_w == base_w, "CLEAR cells written before the win"
            m.advance(1, pad1=pad)
            frame += 1
            _assert_frame(m, frame, snaps, "win")
    assert pre, "the drive never reached the closing stomp's frame"
    # the win surface (the tail above already proved the game keeps running:
    # the player answered the oracle for 40 post-win frames)
    assert _vword(m, UNITS_CELL) == _glyph("0"), "FOES did not reach 0"
    got = [_vword(m, c) for c in CLEAR_CELLS]
    assert got == [_glyph(c) for c in "CLEAR"], (
        f"the win text does not spell CLEAR: {[hex(c) for c in got]}")
    assert [m.writes(V, c * 2) for c in CLEAR_CELLS] == \
        [w + 1 for w in base_w], "a CLEAR cell was written other than once"
    p, e1, e2 = _actors(m)
    assert e1[1] == PARK_Y and e2[1] == PARK_Y, "a dead enemy is not parked"
    px = _pixels(m, "clear")
    assert _census(px).get(MAGENTA, 0) == 0, "an enemy survived the win"
    assert _census(px)[RED] == 64, "the player vanished after the win"


# =============================================================================
# 9. IDLE — reprint-on-change and the staging mechanism
# =============================================================================

def test_idle_stages_actors_every_frame_and_never_reprints_text(boot):
    """60 idle frames: the OAM SHADOW's player byte is written every frame
    (the feature's own output region — hardware OAM is the wrong surface,
    its DMA commits unconditionally; the scroller falsification's lesson),
    while the FOES cell's VRAM write counter does not move at all (the
    counter reprints on change, and nothing changed)."""
    m = boot()
    shadow_player = OAM_SHADOW + O_ACTORS * 4
    s0 = m.writes(W, shadow_player)
    t0 = m.writes(V, UNITS_CELL * 2)
    m.advance(60)
    assert m.writes(W, shadow_player) - s0 >= 60, (
        "the player is not re-staged every frame")
    assert m.writes(V, UNITS_CELL * 2) == t0, (
        "the FOES cell was rewritten on idle frames")
