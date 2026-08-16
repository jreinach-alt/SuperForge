"""m7_oshoot — the rotating Mode 7 arena shooter.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)` — an
absolute frame by construction — and every drive is a fixed per-frame input
list, so the whole trajectory is a pure function of the replay triple.

WHAT THIS RAIL IS — its four teaching claims and its control table:

    M1  static-affine rotating Mode 7 with a MOVING PIVOT — the pivot is
        re-pinned to the player's world position EVERY FRAME, so he stays
        centred while the world spins and slides beneath him
    M2  sprites PROJECTED onto the spinning floor through the render matrix's
        INVERSE, which at this rail's fixed scale is its TRANSPOSE
    M3  rotation-independent WORLD-SPACE gameplay — movement, wall collision
        and both box collisions never read the matrix
    M4  TWO POOLS — bullets fired along the facing, and timed wave chasers

Every one is a named case below, and the state claims are driven in every
direction the rail has (the test-authoring discipline: "forward *and* reverse
*and* idle"): the floor turned LEFT and RIGHT and left ALONE; a bolt allocated
and flown and expired and its slot REUSED; a wall met head-on AND diagonally.

BOTH WORLD-SPACE BOX COLLISIONS ARE DRIVEN INTO, NOT AROUND. M3's other two
halves — `do_bullet_hit` and `do_contact` — are the rail's fifth and sixth
done-conditions ("enemy waves chase AND ARE KILLED BY BULLETS"; "a
hero-enemy contact knocks the hero back"), and each has a case that puts the
collision inside its window on purpose rather than picking a window it cannot
reach: `…a_bolt_that_reaches_a_chaser_takes_it_off_the_floor_with_it` and
`…a_chaser_reaching_the_hero_knocks_the_world_out_from_under_him`. Both are
plant-backed (`tools/plants/m7_oshoot.py`), so neither is a green nobody has
tried to break.

WHAT IS DELIBERATELY NOT READ AS THE ANSWER. `US_HEADING`, `US_POSX/Y` and both
`alive[]` arrays all sit one call away, and reading them as the verdict is the
proxy-variable move CLAUDE.md rule 2 forbids — on every claim here the question
is whether the value REACHES THE PICTURE. So the rotation is read as floor
PIXELS, the pivot as the hero's OAM entry against a floor that moves, the
projection as OAM ENTRIES against an independent oracle, and the pools as OAM
plus the published census. The `alive[]` arrays appear in exactly one place —
`test_the_bolt_pool_fills_swallows_frees_and_reuses_a_slot` — where the claim
IS about which slot the mechanism handed back, and even there the OAM entry is
asserted beside it.

THE FLOOR IS COMPARED BY COLOUR, NOT BY COORDINATES (`_floor`). A whole-frame
diff would answer "did anything move", and the chasers move every frame whatever
the floor does — so an "the floor holds still" case would pass on a broken floor
and a "the floor turned" case would pass on a chaser walking. A pixel is floor
iff its colour is one of the ten the generator emitted, and
`assert_floor_and_obj_palettes_are_disjoint` proves at BUILD time that no OBJ
colour collides with one. That is the population rule — attribute the population you
counted — discharged exactly rather than approximately.

Power-on fidelity comes free rather than as a case: `Machine` seeds power-on
RAM, so every assertion below is made against a ROM booted from random memory,
and none of this rail's WRAM claims are `[init] zero`.
"""
import json
import math
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType                        # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "m7_oshoot.sfc"
ASSETS = BUILD / "assets"
MAP = json.loads((BUILD / "mo" / "symbol_map.json").read_text())

W = MemoryType.SnesWorkRam
O = MemoryType.SnesSpriteRam
C = MemoryType.SnesCgRam

# --- the rail's declared geometry (game/m7_oshoot/m7_oshoot.inc) -----------
# Named here so a wrong constant is a mismatch against the picture rather than
# a silent re-spelling of the source.
HERO_SLOT = 0
ENE_SLOT0, ENE_N = 1, 6
BUL_SLOT0, BUL_N = 7, 8

SCREEN_CX, SCREEN_CY = 128, 112           # m7_project's pinned origin
OBJ_HALF = 8                              # a 16x16 sprite's OAM (x,y) = c - 8
HERO_X, HERO_Y = SCREEN_CX - OBJ_HALF, SCREEN_CY - OBJ_HALF   # 120, 104

T_HERO, T_ENEMY, T_BULLET = 0, 32, 32     # the bolt REUSES the chaser's CHR
ATTR_HERO, ATTR_ENEMY, ATTR_BULLET = 0x30, 0x32, 0x34

# The score readout: three 8x8 digits at their own pinned slots,
# in a fourth OBJ palette band. ATTR_SCORE is also what a DYING chaser's entry
# carries while it flashes, which is what makes a kill legible as a kill.
SCORE_SLOT0, SCORE_N = 16, 3
T_DIGIT0 = 2                              # digit d draws with tile T_DIGIT0 + d
ATTR_SCORE = 0x36                         # priority 3 | OBJ palette 3
MO_DEATH_FRAMES = 24                      # the death flash's length
TURN_STEP = 3                             # heading units per held LEFT/RIGHT

MO_GRACE_FRAMES = 40                      # post-contact frames with the hit
                                          #   suppressed AND the hero blinking —
                                          #   one counter serves both
MO_PARK_Y = 0xF0                          # where a slot that is not drawn goes

# The hero's OAM entry in each of his two states. The blink alternates between
# them, and `mo_park_slot` leaves the hi-table bits mo_put already OR'd in — so
# the parked form keeps size = 1 rather than clearing it. It cannot show: y=240
# with a 16 px sprite is entirely below the 224-line screen.
HERO_DRAWN = (HERO_X, HERO_Y, T_HERO, ATTR_HERO, 0, 1)
HERO_BLINKED = (0, MO_PARK_Y, 0, 0, 0, 1)


# The two colour predicates this module classifies actors with, and which
# tools/gen_m7_oshoot_assets.py's assert_colour_bands() proves nothing else in
# the palette satisfies. That build-time proof is what makes a pixel COUNT here
# attributable to the actor it names.
def _yellow(px):
    r, g, b = px[:3]
    return r > 150 and g > 150 and b < 90


def _red(px):
    r, g, b = px[:3]
    return r > 150 and g < 90 and b < 90


def _cyan(px):
    """The HERO band — the predicate the blink cue is counted with.

    Same contract as the two above, and proved the same way: the generator's
    `assert_colour_bands()` refuses to emit assets if any floor, chaser or bolt
    colour satisfies this, so "how many pixels of this frame are cyan" IS "how
    much of the hero is on screen" with no coordinate arithmetic at all. It is
    checked there against the RENDERED value (5-bit truncation and back), not
    the authored one, because the margin here is 13 rather than the ~100 the
    yellow and red bands enjoy."""
    r, g, b = px[:3]
    return b >= g > r and b >= 120


def _green(px):
    """The SCORE band — the HUD digits and the death flash.

    Fourth and last of this module's exact colour predicates, and proved the same
    way: `assert_colour_bands()` refuses to emit assets if any floor, hero,
    chaser or bolt colour satisfies it, or if any score colour satisfies one of
    the other three. So "how many green pixels" IS "how much score readout and
    death flash is on screen", with no coordinate arithmetic."""
    r, g, b = px[:3]
    return g > 150 and r < 130 and b < 130


def _green_px(img):
    return sum(1 for p in img.get_flattened_data() if _green(p))


# The luminance floor the playtest complaint becomes a gate at.
#
# The scene's normal mean pixel luminance is 62-64. The strobe drove it to 4.1 —
# a full-screen snap to near-black on every contact, ~28% of frames dimmed,
# cycling near 1.5 Hz, which is a photosensitivity hazard as much as a bad read.
# 45 sits an order of magnitude above what the defect produced and ~17 below
# what the fixed rail actually holds (measured min 61.8 across every drive in
# this module), so it catches a reinstated flash without tracking art changes.
LUMA_FLOOR = 45


def _hero_px(img):
    """Pixels of the WHOLE frame that are the hero, this frame.

    Whole-frame rather than a hero-shaped rectangle on purpose: the hero's
    screen position is a constant, so a rect would work, but a count over the
    frame cannot be fooled by an off-by-one in a screen origin this repo does
    not declare (Mesen renders 256x239 here, not 256x224)."""
    return sum(1 for p in img.get_flattened_data() if _cyan(p))


def _luma(img):
    d = list(img.get_flattened_data())
    return sum(0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] for p in d) / len(d)


# --- absolute frames -------------------------------------------------------
CLEAN = 40      # past the fade-in, BEFORE the first wave beat (MO_SPAWN_PERIOD
                #   is 50, counted from enter) — the only window with no chaser
BOOT = 120      # settled, with chasers in the field

PAD_L = {"left": True}
PAD_R = {"right": True}
PAD_U = {"up": True}
PAD_D = {"down": True}


# --- helpers ---------------------------------------------------------------
def _sym(name, scene="arena"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} is not in the emitted map — did the allocator move it?")


DP_M7AFF = _sym("ES_M7AFF", scene=None)["start"]
WR_ACTORS = _sym("ES_MO_ACTORS")["start"]
WR_SHOTS = _sym("US_SHOTS_LIVE")["start"]
WR_CHASERS = _sym("US_CHASERS_LIVE")["start"]

# Byte offsets inside the mo_actors claim (game/m7_oshoot/m7_oshoot.inc).
STRIDE = 16
ENE_ALIVE, ENE_WX, ENE_WY = 0, STRIDE, 2 * STRIDE
BUL_ALIVE, BUL_WX, BUL_WY = 3 * STRIDE, 4 * STRIDE, 5 * STRIDE


def _entry(oam, slot):
    """One OAM entry as (x, y, tile, attr, x9, size) — x9 and size out of the
    HI TABLE, which is where the ninth x bit and the size select actually live.
    Reading the low table alone would miss both, and a stale X9 renders a
    sprite 256 px from where it belongs."""
    x, y, tile, attr = oam[slot * 4:slot * 4 + 4]
    pair = (oam[512 + (slot >> 2)] >> ((slot & 3) * 2)) & 3
    return x, y, tile, attr, pair & 1, (pair >> 1) & 1


def _oam(m):
    return m.read_bytes(O, 0, 544)


def _emitted(oam, slot0, n, tile):
    """The slots of a pool's OAM window that are RENDERING this frame.

    A free or culled slot is parked with tile 0 at y = $F0 by mo_park_slot, so
    a matching TILE is the emitted test — and it is the tile rather than the
    y because a live actor can legitimately be at y = $F0."""
    return [s for s in range(slot0, slot0 + n) if _entry(oam, s)[2] == tile]


def _matrix(m):
    """(A, B, C, D, pivot_x, pivot_y) out of m7_affine's DP shadow.

    M7A-M7D are WRITE-ONLY PPU ports, so the shadow is the only readable copy —
    and it is the exact sixteen bytes m7a_nmi_commit latches, so reading it is
    reading what the floor rendered with, not a parallel guess."""
    v = [m.read_u16(W, DP_M7AFF + 2 * i) for i in range(6)]
    return tuple(x - 0x10000 if x >= 0x8000 else x for x in v[:4]) + (v[4], v[5])


def _shr8(v):
    """The engine's `>> 8` of a signed 32-bit accumulator, which it performs by
    LOADING the word straddling bytes 1 and 2. That is an arithmetic shift
    including the sign, so Python's own >> matches it exactly."""
    return v >> 8


def _project(wx, wy, mat, forward=False):
    """The world -> screen map, computed independently of the ROM.

    `forward=False` is the TRANSPOSE — A,C for x and B,D for y — which is what
    m7_project.asm's M7P_DOT pairs and what the rail is FOR. `forward=True` is
    the pairing a mechanical port reaches for (A,B / C,D): still a rotation,
    still plausible on screen, and wrong by 2*theta. The tests use both: one as
    the oracle, one to prove the oracle is not vacuous at the heading tested."""
    a, b, c, d, px, py = mat
    dx = wx - px
    dy = wy - py
    if dx >= 0x8000:
        dx -= 0x10000
    if dy >= 0x8000:
        dy -= 0x10000
    if forward:
        sx = _shr8(dx * a + dy * b) + SCREEN_CX
        sy = _shr8(dx * c + dy * d) + SCREEN_CY
    else:
        sx = _shr8(dx * a + dy * c) + SCREEN_CX
        sy = _shr8(dx * b + dy * d) + SCREEN_CY
    return sx, sy


def _actors(m, alive_off, wx_off, wy_off, n):
    """[(slot, world_x, world_y)] for the LIVE slots of one pool.

    This is the projection's INPUT, not its output: the output is the OAM entry,
    and that is what the oracle case asserts on."""
    out = []
    for i in range(n):
        if m.read_u16(W, WR_ACTORS + alive_off + 2 * i):
            out.append((i,
                        m.read_u16(W, WR_ACTORS + wx_off + 2 * i),
                        m.read_u16(W, WR_ACTORS + wy_off + 2 * i)))
    return out


def _shot(m, tmp_path, name):
    p = tmp_path / name
    m.screenshot(str(p))
    return Image.open(p).convert("RGB")


def _chaser_centres(oam):
    """Every RENDERING chaser's screen centre, by OAM slot."""
    out = {}
    for s in range(ENE_SLOT0, ENE_SLOT0 + ENE_N):
        x, y, tile, attr, x9, size = _entry(oam, s)
        if tile == T_ENEMY:
            out[s] = ((x - 256 if x9 else x) + OBJ_HALF, y + OBJ_HALF)
    return out


def _knockbacks(seq, thresh=40, spread=6):
    """The indices in a per-frame sequence of chaser centres where the whole
    visible cohort slid together BY THE SAME VECTOR.

    That is the rendered form of a contact, and it is the only one available:
    the hero is screen-fixed, so a knockback moves the pivot and therefore the
    WORLD. A shared vector is a translation — the hero was picked up and put
    down somewhere else. Different vectors would be a rotation and a single odd
    one out would be one chaser walking.

    THE SHARED-VECTOR TEST IS LOAD-BEARING, not decoration. A magnitude-only
    detector counts every heading change as a knockback, because turning rotates
    the floor and moves every chaser a long way — measured on the kiting drive
    below: 26 'knockbacks' at gaps of exactly the turn cadence, against 3 real
    ones."""
    out = []
    for i in range(1, len(seq)):
        prev, cur = seq[i - 1], seq[i]
        both = [s for s in cur if s in prev]
        if len(both) < 2:                     # "they all moved together" is not
            continue                          #   answerable with one chaser
        d = [(cur[s][0] - prev[s][0], cur[s][1] - prev[s][1]) for s in both]
        if max(abs(dx) + abs(dy) for dx, dy in d) < thresh:
            continue
        dxs, dys = [q[0] for q in d], [q[1] for q in d]
        if max(dxs) - min(dxs) <= spread and max(dys) - min(dys) <= spread:
            out.append(i)
    return out


# A kiting drive, REBUILT for turn-and-throttle. It used to be eight
# d-pad combinations, one per compass point, because a combination WAS a heading;
# under the restored scheme a direction is something you turn to and then drive
# along, so the drive is a cycle of "run 30 frames, turn for 15, run again".
#
# IT COVERS MORE THAN ITS PREDECESSOR, not less. Each turn phase sweeps 45 units
# of heading CONTINUOUSLY (15 frames x TURN_STEP), so a full cycle of the pattern
# below visits every heading in the 256 rather than eight of them — which is the
# form the generalised escape check needs. The reverse and idle phases keep the
# "forward and reverse and idle" discipline the module already applied.
# THE HERO KEEPS MOVING WHILE HE TURNS, and getting there took two wrong
# versions that are worth recording because each failed in the opposite
# direction.
#
# What `_knockbacks` can see is the chaser cohort translating, and a knockback
# teleports the hero TO SPAWN — so the translation it renders is the hero's
# DISTANCE FROM SPAWN at that moment, and its 40 px threshold means a drive that
# stays near spawn produces contacts it cannot detect. Version 1 turned in place
# between short runs; the hero pottered around the spawn cell, the translations
# came in under the threshold, and `make falsify`'s `chasers-step-every-frame-
# again` plant reported TEST-BLIND — the case that exists to prove the chase is
# playable had quietly stopped being able to see an unplayable one. Version 2
# lengthened the straight runs to 60 frames, which cleared the threshold and
# then failed the other way: running in a straight line out of a converging
# swarm is the losing pattern on this rail (10 knockbacks against the 3 the
# original drive measured), so the case went red on a perfectly good ROM.
#
# Holding UP *together with* a turn is the answer, and it is not a trick — it is
# how the restored scheme is meant to be played, and it is the closest analogue
# of the old drive's "hold a diagonal": the hero runs a CURVE, so he is moving
# on 121 of these 151 frames (well clear of spawn) while his heading sweeps
# continuously (so he is evading rather than bolting). Reverse and idle keep
# their phases, so the "forward and reverse and idle" discipline still holds.
_KITE_PHASES = [
    (40, PAD_U),                            # run straight
    (25, {"up": True, "left": True}),       # ...curve left, still running
    (40, PAD_U),
    (25, {"up": True, "right": True}),      # ...and curve back the other way
    (15, PAD_D),                            # reverse
    (6, {}),                                # idle: the third state
]
_KITE_LEN = sum(n for n, _ in _KITE_PHASES)


def _kite(f):
    f %= _KITE_LEN
    for n, pad in _KITE_PHASES:
        if f < n:
            return pad
        f -= n
    return {}


FLOOR_WORDS = None          # filled by _floor_colours(), once


def _floor_colours():
    """The RGB triples the floor is allowed to be, from the emitted blob.

    Read out of `mo_pal.bin` rather than restated: the ten words the generator
    emitted ARE the floor, so a re-theme moves this set with the art. Each is
    expanded from BGR555 the way the PPU does — the low three bits of each
    channel are replicated from the high five, which is what makes a rendered
    pixel comparable to a palette word at all."""
    global FLOOR_WORDS
    if FLOOR_WORDS is None:
        blob = (ASSETS / "mo_pal.bin").read_bytes()
        out = set()
        for i in range(0, len(blob), 2):
            w = blob[i] | (blob[i + 1] << 8)
            r5, g5, b5 = w & 31, (w >> 5) & 31, (w >> 10) & 31
            out.add(((r5 << 3) | (r5 >> 2),
                     (g5 << 3) | (g5 >> 2),
                     (b5 << 3) | (b5 >> 2)))
        FLOOR_WORDS = out
    return FLOOR_WORDS


def _floor(img):
    """The frame's pixels with everything that is not floor blanked to None.

    A pixel belongs to the floor iff its colour is one of the floor palette's.
    `tools/gen_m7_oshoot_assets.py::assert_floor_and_obj_palettes_are_disjoint`
    proves at BUILD time that no OBJ colour collides with one, so this
    separation is exact rather than approximate.

    IT IS DELIBERATELY NOT AN OAM-BOX MASK. Projecting OAM entries into the
    framebuffer needs a screen-origin offset that is Mesen's overscan convention
    rather than anything this repo declares — measured here as somewhere between
    +7 and +10 rows depending on which sprite you calibrate against, because the
    art does not fill its 16x16 cell. A wrong offset silently UNDER-masks, and
    the residue looks exactly like a floor that moved: the first version of this
    module reported "92/60417 floor px moved with the pad released" on a floor
    that was perfectly still, and every one of those 92 pixels was a chaser.

    Without any mask these cases would be answering "did any pixel change",
    which the chasers answer yes to every frame whatever the floor does."""
    allowed = _floor_colours()
    return [p if p in allowed else None for p in img.get_flattened_data()]


def _floor_shift(a_img, b_img, radius=14):
    """THE FLOOR'S TRANSLATION between two frames, in screen pixels.

    Returns (dx, dy, score): the displacement the floor CONTENT underwent from A
    to B, and the fraction of compared samples that agreed at it.

    This is how "the player moved toward screen-up" is read off the RENDER. The
    hero is screen-fixed by the moving pivot — his OAM entry is a constant — so
    the only thing his motion can show up in is the floor sliding the other way.
    A floor that moved DOWN (+dy) is a player who moved UP.

    Masked to floor colours for the reason `_floor` states, and the pinned hero's
    own box is dropped as well: he never moves, so leaving him in would pull
    every correlation toward zero.

    A DISPLACEMENT, NOT A DIFFERENCE. `_floor_diff` answers "did the floor
    change", which a rotation, a walk and a knockback all answer yes to. The
    direction question needs the vector, and no variable in the ROM carries it."""
    wa, ha = a_img.size
    pa = _floor(a_img)
    pb = _floor(b_img)
    best = (-1.0, 0, 0)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            hit = tot = 0
            for y in range(20, ha - 20, 3):
                yy = y - dy
                if not (0 <= yy < ha):
                    continue
                row, brow = y * wa, yy * wa
                for x in range(20, wa - 20, 3):
                    xx = x - dx
                    if not (0 <= xx < wa):
                        continue
                    if abs(x - SCREEN_CX) < 24 and abs(y - SCREEN_CY) < 28:
                        continue                  # the pinned hero
                    ca, cb = pa[row + x], pb[brow + xx]
                    if ca is None or cb is None:
                        continue
                    tot += 1
                    if ca == cb:
                        hit += 1
            if tot < 400:
                continue
            sc = hit / tot
            if sc > best[0]:
                best = (sc, -dx, -dy)
    # `best` was found by matching A(x,y) against B(x-dx, y-dy), so the CONTENT
    # moved by (-dx, -dy) — negated above so the returned pair is the motion.
    return best[1], best[2], best[0]


# --- the rendered rotation, measured on the picture ------------------------
# Sample the frame on rings about the screen centre at N_ANG angular positions;
# the circular shift that best correlates two rings IS the rotation the floor
# underwent, in the LUT's own units (360/256 = 1.4 degrees per unit).
#
# WHY NOT READ ES_M7AFF. The matrix shadow is what the NMI latches, so it is
# closer to the truth than most variables — but it is still a variable, and the
# claim under test is about what the player SEES turning. This measures that.
#
# THE SEARCH IS BOUNDED to +-ROT_SEARCH for a specific reason: the arena is a
# square pillar lattice over a square checker, so it correlates with itself at
# multiples of 64 units (90 degrees). A window narrower than that cannot alias a
# 3-unit step onto a 64-unit one, and is still four times wider than the 32-unit
# jolt this change exists to remove.
N_ANG = 256
ROT_RADII = (40, 56, 72, 88)
ROT_SEARCH = 48


def _ring(img):
    px = img.load()
    w, h = img.size
    out = []
    for r in ROT_RADII:
        for a in range(N_ANG):
            th = 2 * math.pi * a / N_ANG
            x = min(max(int(round(SCREEN_CX + r * math.sin(th))), 0), w - 1)
            y = min(max(int(round(SCREEN_CY - r * math.cos(th))), 0), h - 1)
            p = px[x, y]
            out.append(0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2])
    return out


def _rot_delta(ra, rb):
    """The rendered rotation from ring A to ring B, in units of 1.4 degrees.

    Positive = the floor turned clockwise on screen, which is what holding LEFT
    does to it (and what turning left looks like from inside the cockpit)."""
    best = None
    for sh in range(-ROT_SEARCH, ROT_SEARCH + 1):
        err = 0.0
        for ri in range(len(ROT_RADII)):
            base = ri * N_ANG
            for a in range(0, N_ANG, 2):
                d = ra[base + a] - rb[base + ((a + sh) % N_ANG)]
                err += d * d
        if best is None or err < best[0]:
            best = (err, sh)
    return best[1]


def _turn_to(m, heading, pad_frames=None):
    """Hold LEFT until the heading reaches `heading`, then release and settle.

    The frame count comes from the CURRENT heading so the drive is honest about
    where it started; the ASSERTIONS in every case that uses this are on pixels,
    never on this variable. Reachable headings are multiples of TURN_STEP — a
    target that is not one lands on the step below it, which the caller sees in
    the returned value."""
    cur = m.read_u16(W, _sym("US_HEADING")["start"])
    need = (heading - cur) % 256
    n = need // TURN_STEP if pad_frames is None else pad_frames
    if n:
        m.advance(n, pad1=PAD_L)
    m.advance(2)
    return m.read_u16(W, _sym("US_HEADING")["start"])


def _score_tiles(oam):
    """The three HUD digit tiles as rendered — the readout itself, from OAM."""
    return tuple(_entry(oam, s)[2] for s in range(SCORE_SLOT0,
                                                  SCORE_SLOT0 + SCORE_N))


def _score_shown(oam):
    """The number the HUD is DISPLAYING, decoded from its rendered tiles."""
    t = _score_tiles(oam)
    return sum((v - T_DIGIT0) * p for v, p in zip(t, (100, 10, 1)))


def _floor_diff(a_img, b_img):
    """(changed, compared) over the pixels that are floor in BOTH frames."""
    a = _floor(a_img)
    b = _floor(b_img)
    changed = compared = 0
    for pa, pb in zip(a, b):
        if pa is None or pb is None:
            continue
        compared += 1
        if pa != pb:
            changed += 1
    return changed, compared


@pytest.fixture(scope="module", autouse=True)
def _rom_exists():
    if not ROM.exists():
        pytest.skip(f"{ROM} not built — run `make m7_oshoot`")


# =============================================================================
# M1 — the plane, and the pivot pinned to a walking hero
# =============================================================================
def test_the_arena_renders_a_textured_mode7_floor(tmp_path):
    """A REAL textured plane, not a flat fill or a black band.

    The reference oracle's own scenario-1 assertion ("a screenshot blob (>=4
    distinct colours) proves a REAL TEXTURED floor rendered"), read off the
    framebuffer. Paired with a byte-for-byte CGRAM check so "four colours" is
    four colours the generator authored rather than four the PPU invented out of
    an upload that never landed."""
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        img = _shot(m, tmp_path, "floor.png")
        cg = m.read_bytes(C, 0, 512)
    assert len(set(img.get_flattened_data())) >= 4

    want = (ASSETS / "mo_pal.bin").read_bytes()
    assert bytes(cg[:len(want)]) == want, (
        "the floor palette in CGRAM is not the blob the generator emitted — "
        "the upload is the feature under test, so this reads the DESTINATION "
        "region rather than something downstream of it")


def test_the_hero_renders_screen_centred_and_upright():
    """M1's other half: the hero's screen position is a CONSTANT.

    (120, 104) is a 16x16 sprite centred on (128, 112). It is reached without
    projecting the hero at all:
    m7a_set_center pins the pivot there every frame, so the hero's screen
    position falls out of the camera model.

    The size bit must be SET (16x16, the OBSEL pair's large half) and X9 CLEAR.
    The alternative is a real shipped bug, not a hypothetical: a 32x32 hero
    reads a 4x4 tile block whose lower-left quadrant is the chaser CHR, and a
    phantom diamond bleeds into him (main.asm:106-123)."""
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        x, y, tile, attr, x9, size = _entry(_oam(m), HERO_SLOT)
    assert (x, y, tile, attr) == (HERO_X, HERO_Y, T_HERO, ATTR_HERO)
    assert (x9, size) == (0, 1)


@pytest.mark.parametrize("pad,name", [(PAD_L, "left"), (PAD_R, "right"),
                                      (PAD_U, "up"), (PAD_D, "down")])
def test_the_hero_stays_pinned_while_the_floor_moves_under_him(pad, name, tmp_path):
    """THE MOVING PIVOT (M1), in every direction the pad has.

    Walking must move the WORLD and not the hero. Both halves are asserted from
    the render: the hero's OAM entry is identical before and after, and the
    floor pixels are not — so "he is pinned" cannot pass by the floor being
    frozen too, and "the floor moved" cannot pass by the hero having moved."""
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        before_img = _shot(m, tmp_path, f"pin_{name}_a.png")
        before_oam = _oam(m)
        m.advance(24, pad1=pad)
        after_img = _shot(m, tmp_path, f"pin_{name}_b.png")
        after_oam = _oam(m)

    assert _entry(after_oam, HERO_SLOT) == _entry(before_oam, HERO_SLOT), (
        f"the hero moved on screen while walking {name}; the pivot is supposed "
        f"to follow him so that he does not")

    changed, compared = _floor_diff(before_img, after_img)
    assert changed > compared * 0.20, (
        f"the floor barely moved walking {name}: {changed}/{compared} px")


# =============================================================================
# M1 — the floor turns to the held heading, both ways, and holds when idle
# =============================================================================
# The headings are picked OFF-AXIS on purpose. At a quarter turn this arena maps
# almost onto itself — a square pillar lattice over a square checker — so a
# 90-degree probe reads as a false negative and would have shipped a test that
# passed on a floor that never rotated. UP+LEFT and UP+RIGHT are 45 degrees
# either side of the boot heading and have no such symmetry.
@pytest.mark.parametrize("pad,name", [
    ({"up": True, "left": True}, "up-left"),
    ({"up": True, "right": True}, "up-right"),
])
def test_the_floor_turns_to_the_held_heading_in_both_directions(pad, name, tmp_path):
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        a_img = _shot(m, tmp_path, f"turn_{name}_a.png")
        m.advance(8, pad1=pad)
        b_img = _shot(m, tmp_path, f"turn_{name}_b.png")
    changed, compared = _floor_diff(a_img, b_img)
    assert changed > compared * 0.30, (
        f"the floor did not turn {name}: {changed}/{compared} px changed")


def test_the_facing_persists_and_the_floor_holds_still_when_the_pad_is_released(tmp_path):
    """THE IDLE STATE, which is the third direction the discipline demands.

    Release the pad and the world stops: no walk, and no drift back to the boot
    heading. The user-visible invariant is that the FLOOR PIXELS do not move —
    stated that way rather than as "US_HEADING is unchanged", because a heading
    that persists in DP and is not committed looks identical in a variable and
    wrong on screen.

    Sprites are masked out of both frames: the chasers keep walking while the
    floor holds, and a whole-frame diff would call that a moving floor."""
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        m.advance(16, pad1={"up": True, "left": True})   # turn to 45 degrees
        m.advance(4)                                     # release, settle
        a_img = _shot(m, tmp_path, "idle_a.png")
        m.advance(20)                                    # ...and stay released
        b_img = _shot(m, tmp_path, "idle_b.png")
    changed, compared = _floor_diff(a_img, b_img)
    assert compared > 20000, f"too little floor left to judge ({compared} px)"
    assert changed == 0, (
        f"{changed}/{compared} floor px moved with the pad released — the "
        f"facing did not persist, or the world walked without input")


# =============================================================================
# M2 — the transpose: sprites glued to the spinning floor
# =============================================================================
def test_the_cast_matches_an_independent_transpose_projection_oracle():
    """THE MECHANISM UNDER TEST, asserted on OAM against arithmetic done here.

    For every live chaser and bolt: take its WORLD position and the matrix the
    NMI committed, compute the screen point in Python through the TRANSPOSE
    (A,C for x; B,D for y), and require the OAM entry to be that point minus the
    sprite half-extent.

    NON-VACUITY IS PROVEN IN THE SAME CASE. The forward pairing (A,B / C,D) is a
    rotation too — the sprites still move, still stay on screen, and still look
    plausible for a second — so an oracle that happened to agree with it would
    assert nothing. The case therefore computes BOTH and asserts they DISAGREE
    at the heading tested before comparing against the transpose. The forward
    pairing ships as a deliberate negative control for exactly this reason
    (main.asm:125-134, -DBULLET_PROJ_FORWARD).
    """
    with Machine(str(ROM)) as m:
        m.advance(180)                       # a populated field
        _turn_to(m, 192)                     # ...and WALKED clear of (PAD_R
        m.advance(20, pad1=PAD_U)            #   turns now), so a bolt
                                             #   survives long enough to check:
                                             #   a chaser standing ON the hero
                                             #   kills a new bolt in its own
                                             #   spawn tick, which is the rail
                                             #   working and leaves nothing to
                                             #   assert. Measured: 4 chasers and
                                             #   1 bolt on screen here.
        UL = {"up": True, "left": True}
        m.advance(24, pad1=UL)               # turn 45 degrees off-axis, so the
        m.advance(2, pad1=dict(UL, a=True))  #   two pairings differ
        m.advance(3, pad1=UL)
        # THE PRESENTATION LAG, and why the reads are on either side of it.
        # A tick builds the OAM SHADOW; the NMI DMAs that shadow into the PPU at
        # the START of the next frame. So WRAM read here is tick N's answer and
        # OAM read here is tick N-1's. Capturing the world state and the matrix
        # first, then advancing ONE frame, lines the two up on the same tick.
        # Skipped, the oracle is off by one frame of chaser motion: measured at
        # 2 px of screen x for a chaser walking one world px per axis per frame,
        # which reads exactly like a projection that is slightly wrong.
        mat = _matrix(m)
        chasers = _actors(m, ENE_ALIVE, ENE_WX, ENE_WY, ENE_N)
        bolts = _actors(m, BUL_ALIVE, BUL_WX, BUL_WY, BUL_N)
        m.advance(1)
        oam = _oam(m)

    checked = 0
    for pool, slot0 in ((chasers, ENE_SLOT0), (bolts, BUL_SLOT0)):
        for idx, wx, wy in pool:
            sx, sy = _project(wx, wy, mat)
            ox, oy = sx - OBJ_HALF, sy - OBJ_HALF
            if not (0 <= oy <= 2 * SCREEN_CY - 1):
                continue                     # culled by the y test; not emitted
            if not (-(16 - 1) <= ox <= 2 * SCREEN_CX - 1):
                continue                     # ...or by the x test
            fx, fy = _project(wx, wy, mat, forward=True)
            assert (fx, fy) != (sx, sy), (
                "at this heading the forward pairing gives the same answer as "
                "the transpose, so this case would assert nothing — pick a "
                "heading further off-axis")

            x, y, tile, attr, x9, size = _entry(oam, slot0 + idx)
            got_x = x - 256 if x9 else x
            assert (got_x, y) == (ox, oy), (
                f"slot {slot0 + idx} at world ({wx},{wy}) renders at "
                f"({got_x},{y}); the transpose says ({ox},{oy}) and the "
                f"forward pairing would say ({fx - OBJ_HALF},{fy - OBJ_HALF})")
            assert size == 1 and tile in (T_ENEMY, T_BULLET)
            checked += 1

    assert checked >= 2, (
        f"only {checked} actor(s) were on screen to check — the oracle needs "
        f"a populated field to mean anything")


# HEADINGS, NOT PAD COMBINATIONS. A d-pad combination used to BE a heading;
# under turn-and-throttle it is something you turn to and then stop turning. Two
# of these five are off-axis and were unreachable under the deleted table, so
# the case now covers more of the claim than it could before.
@pytest.mark.parametrize("heading,name", [
    (0, "boot"), (45, "45"), (69, "69"), (128, "about-face"), (210, "210"),
])
def test_a_bolt_travels_up_the_screen_whatever_the_heading(heading, name):
    """THE TRANSPOSE'S USER-VISIBLE CONSEQUENCE, and the sharpest form of M2.

    A bolt is fired FORWARD along the facing, and the floor is rotated so the
    facing reads "up". So on SCREEN the bolt must climb straight up from the
    hero at EVERY heading, even though its world velocity is a different vector
    each time. That is exactly what the inverse buys: the world-space direction
    changes with the heading and the screen-space track does not.

    Under the forward pairing the bolt's screen track rotates by 2*theta instead
    of staying put, so this case is red at every heading but zero.

    It is read off OAM — the bolt's own slot, over successive frames — not off
    its world velocity.

    THE PAD IS RELEASED FOR THE WHOLE OBSERVATION, which is new and is the point
    of the restored scheme: turning is now something you STOP doing. Holding a
    turn while the bolt flies rotates the floor under it, so the screen track
    curves — correctly, and uselessly for this claim (measured under the old
    drive: 13 px of sideways for 14 px of climb, purely from the turn still
    being held). Releasing pins the facing — stand-and-shoot survived this change
    — and leaves the bolt's own track as the only thing moving."""
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        _turn_to(m, heading)                 # ...and RELEASE: the facing persists
        m.advance(2, pad1={"a": True})
        m.advance(2)
        first = _entry(_oam(m), BUL_SLOT0)
        m.advance(6)
        later = _entry(_oam(m), BUL_SLOT0)

    assert first[2] == T_BULLET and later[2] == T_BULLET, (
        f"the bolt is not rendering at heading {name}: {first} -> {later}")
    fx = first[0] - 256 if first[4] else first[0]
    lx = later[0] - 256 if later[4] else later[0]
    climb = first[1] - later[1]
    drift = abs(lx - fx)
    assert climb >= 8, (
        f"the bolt did not climb the screen at heading {name}: "
        f"y {first[1]} -> {later[1]}")
    assert climb >= 2 * drift, (
        f"the bolt's track at heading {name} is {drift} px sideways for "
        f"{climb} px of climb — it is not going where it was aimed. The "
        f"forward matrix pairing rotates this track by 2*theta, which at a "
        f"45-degree heading lays it flat.")


# WHY THE DRIFT BOUND IS A RATIO AND NOT ZERO. A bolt's world velocity is the
# INTEGER word of a 16.16 product (`m7p_mul` -> ACC+2), which is the scene's
# own arithmetic (main.asm:1006, `lda a:math_p + 2`) and truncates toward minus
# infinity. At a 45-degree heading the exact velocity is (+2.12, -2.12) and the
# stored one is (+3, -2) — an 11-degree error that no projection can undo, so
# the bolt really does leave slightly off its facing. Measured over the six
# frames this case drives: cardinal headings give drift 0 / climb 10-18, and
# up-right gives drift 4 / climb 14. The ratio bound holds all five with margin
# and still fails hard on a track laid flat by the wrong pairing.


# =============================================================================
# THE CONTROL SCHEME — the playtest complaint, as gates
# =============================================================================
# The rail shipped an EIGHT-WAY COMPASS SNAP: the d-pad chose one of eight world
# headings and US_HEADING jumped to it. The owner piloted it and rejected it —
# *"the sharp world rotation at 45 degree angles does NOT read well, at all. I
# can't tell what's going on... When it rotates, it's resetting how the d-pad
# functions and I'm not sure what direction to press."* Two defects from one
# substitution, and this section is one case for each.
#
# EVERY CASE HERE READS THE PICTURE. The heading is a DP word and the matrix is a
# DP shadow; neither is what the player looked at and rejected. What follows
# measures the floor's translation and the floor's rotation off rendered frames.

# Headings spanning the full 256 and DELIBERATELY NOT multiples of 32 — the eight
# values the deleted table could produce were 0, 32, 64 ... 224, so a probe at
# those alone would pass on the very scheme this change removed. Every value
# below is a multiple of TURN_STEP (they are the ones a turn can actually stop
# on) and none is a multiple of 32.
OFF_AXIS_HEADINGS = [6, 45, 69, 108, 150, 174, 210, 249]


@pytest.mark.parametrize("heading", OFF_AXIS_HEADINGS)
def test_up_moves_the_player_toward_screen_up_at_every_heading(heading, tmp_path):
    """THE INVARIANT THE OWNER'S COMPLAINT IS ABOUT — required by the spec

    Press UP and the player must go toward SCREEN-UP. Not toward a world
    direction that used to be up, not toward whatever the d-pad meant before the
    view rotated: up the screen, at every heading, forever. That is the whole of
    what "turn and throttle" buys and it is the property the eight-way snap could
    not have, because a button chose a WORLD heading while the view rotated
    underneath it.

    READ OFF THE FLOOR, because there is nowhere else to read it. The hero is
    pinned at screen centre by the moving pivot — his OAM entry is a constant, by
    construction — so his motion is visible ONLY as the floor sliding the other
    way. A floor that translates DOWN is a player who moved UP.

    The lateral bound is half the forward one and it is the second half of the
    claim: UP must go STRAIGHT up, not up-and-drifting. A sign error in either
    strafe term of do_integrate, or a swapped sin/cos, shows up here as dx
    growing with the heading while dy stays healthy."""
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        reached = _turn_to(m, heading)
        before = _shot(m, tmp_path, f"up_{heading}_a.png")
        m.advance(8, pad1=PAD_U)
        after = _shot(m, tmp_path, f"up_{heading}_b.png")

    dx, dy, score = _floor_shift(before, after)
    assert score > 0.80, (
        f"the floor correlation is only {score:.2f} at heading {reached} — the "
        f"shift is not trustworthy, so neither is the direction read off it")
    assert dy >= 6, (
        f"held UP for 8 frames at heading {reached} and the floor moved "
        f"{dy:+d} px vertically. Forward is 1.25 px/frame, so the floor owes "
        f"~10 px DOWNWARD (a player moving up). This is the playtest complaint: "
        f"UP did not go up.")
    assert abs(dx) <= 3, (
        f"held UP at heading {reached} and the floor slid {dx:+d} px sideways. "
        f"UP must go STRAIGHT up the screen; a lateral component means the step "
        f"is not along the facing")


def test_a_full_turn_rotates_the_floor_smoothly_with_no_forty_five_degree_jump(tmp_path):
    """THE OTHER HALF OF THE COMPLAINT — *"the sharp world rotation at 45 degree
    angles does NOT read well"* — required by the spec

    Hold LEFT through a whole revolution and measure how far the floor turned
    between one sample and the next, ON THE PICTURE: rings sampled about screen
    centre, correlated circularly, answer in the LUT's own 1.4-degree units.

    THREE CLAIMS, and the third is what stops the first two being vacuous:

      * no jump anywhere near the 32 units (45 degrees) the snap produced. The
        bound is 8 per sample — four times the design rate and four times below
        the jolt, so it separates the two schemes with margin either way.
      * the turn actually goes somewhere: a full revolution's worth of rotation
        accumulates, so this cannot pass on a floor that never turned.
      * MANY DISTINCT ORIENTATIONS are visited. The snap would show a handful of
        big steps and long flat stretches; continuous turning shows a steady
        small step. Counting the samples that moved AT ALL is what tells those
        apart even if a future bug made the steps small but sparse.

    Two emulated frames per sample because `Machine.screenshot()` costs a frame
    AND releases both pads — so the pad is re-asserted every sample and the
    per-sample rate is twice the per-frame one."""
    SAMPLES, PER = 44, 2
    deltas = []
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        prev = _ring(_shot(m, tmp_path, "rot_0.png"))
        for i in range(SAMPLES):
            m.advance(PER, pad1=PAD_L)
            cur = _ring(_shot(m, tmp_path, f"rot_{i + 1}.png"))
            deltas.append(_rot_delta(prev, cur))
            prev = cur

    mags = [abs(d) for d in deltas]
    worst = max(mags)
    assert worst <= 8, (
        f"the floor jumped {worst} units (={worst * 360 / 256:.0f} degrees) in "
        f"one sample. The eight-way snap this change removed produced 32 units "
        f"(45 degrees) per direction change, and that jolt is exactly what the "
        f"playtesting reported as unreadable. Profile: {deltas}")
    assert sum(mags) >= 200, (
        f"only {sum(mags)} units of rotation across {SAMPLES} samples of held "
        f"LEFT — a full turn is 256, so the floor barely moved and the bound "
        f"above would pass on a rail that does not turn at all")
    assert sum(1 for d in mags if d > 0) >= SAMPLES - 2, (
        f"only {sum(1 for d in mags if d > 0)}/{SAMPLES} samples rotated at "
        f"all. A snap is 'a few big steps and long flat stretches'; continuous "
        f"turning moves on essentially every frame, and that is the shape being "
        f"asserted rather than just the size of the biggest step")


def test_forward_and_back_move_opposite_ways_at_a_non_cardinal_heading(tmp_path):
    """UP and DOWN are one axis, and they must be OPPOSITE ends of it.

    Driven at a heading the deleted table could never produce, so this cannot
    pass on a residue of the compass scheme. Both directions are measured as
    floor translations from the same starting frame, and the assertion is on
    their RELATIONSHIP: reverse must undo forward, not merely be non-zero. A
    sign error that made DOWN a second forward would pass a two-sided
    "did the floor move" check and fails here."""
    HEAD = 69
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        _turn_to(m, HEAD)
        a = _shot(m, tmp_path, "fb_a.png")
        m.advance(8, pad1=PAD_U)
        b = _shot(m, tmp_path, "fb_b.png")
        m.advance(8, pad1=PAD_D)          # ...straight back where it came from
        c = _shot(m, tmp_path, "fb_c.png")

    fx, fy, fs = _floor_shift(a, b)
    rx, ry, rs = _floor_shift(b, c)
    assert fs > 0.80 and rs > 0.80, f"weak correlation ({fs:.2f}, {rs:.2f})"
    assert fy >= 6, f"UP moved the floor {fy:+d} px at heading {HEAD}"
    assert ry <= -6, (
        f"DOWN moved the floor {ry:+d} px at heading {HEAD} — reverse must be "
        f"the opposite of forward, not a second forward")
    assert abs(fy + ry) <= 4, (
        f"forward {fy:+d} and reverse {ry:+d} do not cancel; they are supposed "
        f"to be the same axis driven both ways")


# THREE HEADINGS, and the set is chosen against the failure rather than for
# tidiness. The `strafe-terms-added-instead-of-crossed` plant feeds sin where cos
# belongs, which makes the strafe's rendered motion s*sin(t)*(cos t + sin t)
# across and s*sin(t)*(cos t - sin t) along the facing. At heading 45 that is a
# 3:1 lateral:forward split — still mostly sideways, still opposing itself on L
# vs R, still not turning — so a single-heading case reported TEST-BLIND. At
# heading 0 the same expression is ZERO in both axes (the strafe simply stops
# working), and at 210 it is mostly FORWARD. Two independent detectors, from
# arithmetic rather than from luck.
@pytest.mark.parametrize("HEAD", [0, 45, 210])
def test_the_shoulders_strafe_sideways_with_the_heading_unchanged(HEAD, tmp_path):
    """L/R SLIDE, THEY DO NOT TURN.

    The whole justification for adding the shoulders is that they are ADDITIVE:
    they give a sideways dodge without changing what the d-pad means. So the
    claim has two halves and BOTH are measured on the picture — the floor must
    translate laterally, and it must NOT rotate. "The heading is unchanged" is
    asserted as zero rendered rotation rather than as a DP word holding still,
    because a heading that persists in DP and is committed anyway looks
    identical in a variable and wrong on screen.

    Driven at three headings — see the note above the decorator for why those
    three — so 'sideways' is a genuine composition of both world axes at two of
    them rather than a single axis at one."""
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        _turn_to(m, HEAD)
        a = _shot(m, tmp_path, f"str_{HEAD}_a.png")
        ring_a = _ring(a)
        m.advance(10, pad1={"r": True})
        b = _shot(m, tmp_path, f"str_{HEAD}_b.png")
        ring_b = _ring(b)
        m.advance(10, pad1={"l": True})
        c = _shot(m, tmp_path, f"str_{HEAD}_c.png")

    rx, ry, rscore = _floor_shift(a, b)
    lx, ly, lscore = _floor_shift(b, c)
    assert rscore > 0.80 and lscore > 0.80, "weak correlation"
    assert abs(rx) >= 4, (
        f"at heading {HEAD} the R strafe moved the floor only {rx:+d} px "
        f"sideways — 0.75 px/frame over 10 frames owes ~7. A strafe that does "
        f"nothing at some headings is not a strafe")
    assert rx * lx < 0, (
        f"R moved the floor {rx:+d} and L moved it {lx:+d}; the two shoulders "
        f"must slide OPPOSITE ways")
    # SIDEWAYS, AND ONLY SIDEWAYS. The hero always faces screen-up, so a lateral
    # world step must render as a lateral FLOOR step with no forward component.
    # Without this the case is blind to a strafe that is really a second
    # throttle: `make falsify`'s `strafe-terms-added-instead-of-crossed` plant
    # feeds sin where cos belongs, which still moves the world, still opposes
    # itself on L vs R, and still leaves the heading alone — every assertion
    # above stays true — and it reported TEST-BLIND until this line existed.
    # A ratio rather than a constant, on the same reasoning as the bolt-drift
    # bound below: the step is the integer word of a 16.16 product, so a couple
    # of px of truncation error is real and is not the defect.
    assert abs(rx) >= 2 * abs(ry), (
        f"the R strafe moved the floor {rx:+d} across and {ry:+d} along the "
        f"facing. A strafe is a SIDESTEP — a forward component that large means "
        f"the lateral terms are not crossed and the shoulders are a second "
        f"throttle rather than a dodge")
    # THE BOUND IS 3, NOT 0, AND THE RESIDUAL IS THE ESTIMATOR RATHER THAN THE
    # ROM. `_rot_delta` recovers rotation by correlating a ring about the screen
    # centre, and the floor is TRANSLATING ~7 px underneath that ring while the
    # strafe runs — at heading 0 the lattice is axis-aligned, so a pure slide
    # correlates best at a small non-zero shift (measured: -2). What the case
    # has to separate is that residual from an actual turn, and the margin is
    # enormous: a strafe that moved the heading would move it at MO_TURN_STEP,
    # i.e. 30 units across these ten frames, ten times the bound.
    turned = _rot_delta(ring_a, ring_b)
    assert abs(turned) <= 3, (
        f"the floor rotated {turned} units while strafing at heading {HEAD}. A "
        f"strafe that turns the heading is not additive — it is a third thing "
        f"changing what the d-pad means, which is the defect this change "
        f"removed. Ten frames of turning would be {10 * TURN_STEP} units")


# =============================================================================
# M3 — world-space collision, on a floor that is turning
# =============================================================================
def test_a_pillar_blocks_the_walk_and_the_floor_stops_moving(tmp_path):
    """WALKING INTO A WALL, read as the picture.

    The hero never leaves screen centre, so "blocked" has exactly one visible
    form: the floor stops sliding. Held RIGHT from the spawn cell, the lattice's
    nearest pillar face is 80 world px away at 1.25 px/frame; by frame 96 the
    walk is against it and the two comparison frames — still with RIGHT held —
    must be floor-identical.

    The heading is constant across both frames (RIGHT is held throughout), so
    the only thing that could move the floor is translation, which is the claim.
    """
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        # TURN, THEN WALK. This drive used to hold RIGHT, which WAS the east
        # heading under the deleted table; RIGHT now TURNS, so holding it walks
        # nowhere and rotates forever. 192 is that table's own value for RIGHT,
        # reached continuously and then RELEASED — so the heading is constant
        # across every comparison frame below and translation is the only thing
        # that can move the floor, which is what the case claims.
        _turn_to(m, 192)
        m.advance(40, pad1=PAD_U)
        moving_a = _shot(m, tmp_path, "wall_moving_a.png")
        m.advance(4, pad1=PAD_U)
        moving_b = _shot(m, tmp_path, "wall_moving_b.png")
        m.advance(60, pad1=PAD_U)            # ...on into the pillar face
        stuck_a = _shot(m, tmp_path, "wall_stuck_a.png")
        m.advance(4, pad1=PAD_U)
        stuck_b = _shot(m, tmp_path, "wall_stuck_b.png")

    moved, _ = _floor_diff(moving_a, moving_b)
    assert moved > 0, "the floor was not moving before the wall — no control"

    stuck, compared = _floor_diff(stuck_a, stuck_b)
    assert compared > 20000, f"too little floor left to judge ({compared} px)"
    assert stuck == 0, (
        f"{stuck}/{compared} floor px still moving with RIGHT held against a "
        f"pillar — the wall does not block")


def test_a_diagonal_push_into_a_pillar_slides_along_the_free_axis(tmp_path):
    """PER-AXIS CANDIDATE-TEST-COMMIT, which is what makes the lattice weavable.

    The same pillar face, pushed diagonally. The blocked axis stops and the free
    one keeps advancing, so the floor keeps moving — where the head-on case
    above freezes it. Both cases hold their pad for both comparison frames, so
    the heading is constant within each and the difference between them is the
    slide and nothing else."""
    with Machine(str(ROM)) as m:
        m.advance(20)                             # early: the wave beat has not
        # TURN, THEN WALK. This drive used to hold RIGHT, which WAS the east
        # heading under the deleted table; RIGHT now TURNS, so holding it walks
        # nowhere and rotates forever. 192 is that table's own value for RIGHT,
        # reached continuously and then RELEASED — so the heading is constant
        # across every comparison frame below and translation is the only thing
        # that can move the floor, which is what the case claims.
        # ...and the DIAGONAL is now a heading rather than two buttons. 160 is
        # the table's own down-right value; forward there is (+0.707, +0.707) in
        # world, so both axes advance and one can be blocked while the other is
        # not — which is what makes this a per-axis claim and not a second
        # head-on one.
        _turn_to(m, 192)
        m.advance(70, pad1=PAD_U)                 #   fired, so nothing can
                                                  #   reach the hero and knock
                                                  #   him off the wall mid-case
        m.advance(8, pad1={"right": True, "up": True})   # settle on the diagonal
        a_img = _shot(m, tmp_path, "slide_a.png")
        m.advance(4, pad1={"right": True, "up": True})
        b_img = _shot(m, tmp_path, "slide_b.png")
    changed, compared = _floor_diff(a_img, b_img)
    assert compared > 20000, (
        f"only {compared} floor px to judge — the screen is not at full "
        f"brightness, which means a knockback's flash landed inside the case "
        f"and NOTHING here was measured")
    assert changed > 0, (
        "a diagonal push into the pillar dead-stopped; each axis is supposed "
        "to be judged against the world the other one has already resolved")


# =============================================================================
# M4 — the pools: allocate, active, free, REUSE
# =============================================================================
def test_the_bolt_pool_fills_swallows_frees_and_reuses_a_slot():
    """THE WHOLE CYCLE, and the only case that reads `alive[]` — because the
    claim IS which slot the mechanism handed back. The OAM entry for that slot
    is asserted beside it, so "the array says alive" cannot pass alone.

    Four transitions, in order:
      allocate  eight presses fill the pool and eight OAM slots render
      full      a ninth press is SWALLOWED — pool_spawn answers POOL_FULL
      free      the oldest bolt's TTL expires and its slot goes back
      REUSE     the next press claims THAT slot, mid-array, not the next one up

    The reuse arm is the point. pool_spawn scans for the FIRST free slot, so a
    slot freed in the middle must be the one re-claimed — a mechanism that only
    ever appended would pass a fill-drain-refill test and fail this."""
    # TURN EAST ONCE, THEN WALK IT. The hold used to be RIGHT — the east heading
    # under the deleted table — and RIGHT now TURNS, so holding it would leave
    # every bolt on a different facing and put the reuse arm's "the new bolt
    # renders on the hero's own column" off by the accumulated turn (measured:
    # x 118 against the pinned 120). Setting the heading once and holding UP
    # reproduces the original drive exactly: the hero walks away from the ring
    # so a chaser cannot close and eat a bolt, and the facing is constant so the
    # track stays straight. Idling instead was tried and is wrong for a second
    # reason — the first beat's chaser sits straight ahead at the boot heading,
    # so bolt 0 killed it and its slot came back before the pool could fill
    # (measured: alive[] = [0, 1, 1, 1, 1, 1, 1, 1]).
    hold = PAD_U
    fire = {"up": True, "a": True}
    with Machine(str(ROM)) as m:
        m.advance(60)
        _turn_to(m, 192)                      # east, as the old RIGHT meant
        for _ in range(BUL_N):
            m.advance(2, pad1=fire)
            m.advance(2, pad1=hold)
        oam = _oam(m)
        alive = [m.read_u16(W, WR_ACTORS + BUL_ALIVE + 2 * i) for i in range(BUL_N)]
        assert all(alive), f"the pool did not fill: {alive}"
        assert _emitted(oam, BUL_SLOT0, BUL_N, T_BULLET) == \
            list(range(BUL_SLOT0, BUL_SLOT0 + BUL_N)), \
            "eight live bolts, but not eight rendering"

        m.advance(2, pad1=fire)               # the ninth press
        m.advance(2, pad1=hold)
        assert m.read_u16(W, WR_SHOTS) == BUL_N, \
            "a full pool must swallow the press, not grow"

        freed = None
        for _ in range(90):                   # ...until the oldest expires
            m.advance(1, pad1=hold)
            live = [m.read_u16(W, WR_ACTORS + BUL_ALIVE + 2 * i)
                    for i in range(BUL_N)]
            if not all(live):
                freed = live.index(0)
                break
        assert freed is not None, "no bolt expired within its TTL"

        m.advance(2, pad1=fire)               # ...and the next shot takes it
        m.advance(1, pad1=hold)
        alive = [m.read_u16(W, WR_ACTORS + BUL_ALIVE + 2 * i) for i in range(BUL_N)]
        oam = _oam(m)

    assert alive[freed] == 1, (
        f"slot {freed} was freed and the next shot did not reuse it: {alive}")
    x, y, tile, attr, x9, size = _entry(oam, BUL_SLOT0 + freed)
    assert (tile, attr, size) == (T_BULLET, ATTR_BULLET, 1), (
        f"OAM slot {BUL_SLOT0 + freed} is not rendering the reused bolt")
    assert (x - 256 if x9 else x) == HERO_X and HERO_Y - 12 <= y <= HERO_Y, (
        f"the reused bolt renders at ({x},{y}); a bolt is born at the hero's "
        f"world position — which IS the pivot — so it must project onto the "
        f"hero's own column and have climbed at most the two frames of travel "
        f"this drive gives it")


def test_the_published_pool_counts_track_both_pools_through_the_cycle():
    """THE CENSUS, checked against the arrays it counts
    and against the picture at the one moment all of them are visible.

    Nothing in the rail branches on either word, which is what makes them safe
    to assert on: a test reading them cannot be reading something the game
    reacted to."""
    hold = PAD_R
    fire = {"right": True, "a": True}
    with Machine(str(ROM)) as m:
        m.advance(60)
        assert m.read_u16(W, WR_SHOTS) == 0, "bolts before any press"

        for n in range(1, 4):
            m.advance(2, pad1=fire)
            m.advance(2, pad1=hold)
            assert m.read_u16(W, WR_SHOTS) == n, \
                f"after {n} press(es) the census says " \
                f"{m.read_u16(W, WR_SHOTS)}"
        oam = _oam(m)
        rendered = len(_emitted(oam, BUL_SLOT0, BUL_N, T_BULLET))
        assert rendered == 3, f"census 3, but {rendered} bolts on screen"

        chasers = m.read_u16(W, WR_CHASERS)
        alive = sum(1 for i in range(ENE_N)
                    if m.read_u16(W, WR_ACTORS + ENE_ALIVE + 2 * i))
        assert chasers == alive, (
            f"the chaser census says {chasers}, the pool holds {alive}")

        m.advance(120, pad1=hold)             # every bolt outlives its TTL
        assert m.read_u16(W, WR_SHOTS) == 0, \
            "the bolt census did not fall back to zero"


def test_a_bolt_that_reaches_a_chaser_takes_it_off_the_floor_with_it():
    """THE FIRST OF THE TWO WORLD-SPACE BOX COLLISIONS (`do_bullet_hit`), and the
    otherwise-unasserted half of the rail's fifth done-condition — *"enemy
    waves chase AND ARE KILLED BY BULLETS"*. The chase half is
    `…the_wave_beat_puts_chasers_on_the_floor…`; this is the kill.

    THE DRIVE PUTS A BOLT THROUGH A CHASER, IT DOES NOT SHOOT AT NOTHING. The
    first wave beat places its chaser on the hero's own screen column (x = 128,
    measured) and walks it down at 1 px/frame, so the boot heading already aims
    at it: fire ONE bolt at frame 118 and it climbs 3 px/frame into an actor
    coming the other way. Measured, the bolt is emitted at screen y = 109 and is
    still emitted at y = 85 — 24 px of visible travel — before the box closes.

    THE VERDICT IS THE OAM WINDOW, and specifically that TWO slots go dark
    TOGETHER: the chaser's stops emitting T_ENEMY on the same frame the bolt's
    stops emitting T_BULLET. That pairing is what makes this `do_bullet_hit` and
    not something else — it is the only path in the rail that frees a chaser at
    all (`arena.asm:758`, the sole `pool_kill` on MO_ENE_ALIVE), while a bolt
    alone goes back on TTL every 90 frames (`:546`). The published census is read
    beside it as corroboration, never as the verdict.

    IT CANNOT PASS ON A CULL, which is the one other way a slot stops emitting
    (`mo_obj.asm:341-393` parks a culled actor exactly as it parks a free one).
    The case pins the target inside the screen on its last emitted frame, and
    requires the OTHER chaser — off to the right, culled by nothing — to keep
    rendering across the same frame. A cull sweep, an OAM DMA that stopped, or a
    scene-wide fault all move both; only a hit moves one.
    """
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        m.advance(142)                         # the first chaser is 54 px up the
                                               #   hero's own column. It was 76
                                               #   until the chase went to half
                                               #   rate (MO_CHASE_HALF): the
                                               #   chaser closes the same 120 px
                                               #   ring at 0.5 px/frame now, so
                                               #   reaching the SAME geometry
                                               #   this case is calibrated on
                                               #   takes twice as long. Measured
                                               #   on the emulator, not scaled
                                               #   on paper: dy = 77 at CLEAN+96
                                               #   and falls 1 px per 2 frames
        target = _emitted(_oam(m), ENE_SLOT0, ENE_N, T_ENEMY)
        assert target, "no chaser on screen to shoot at"
        tgt = target[0]

        m.advance(2, pad1={"a": True})         # ONE bolt, on A's rising edge
        travel = []
        before = after = None
        for _ in range(18):
            # 18 rather than 12 for the same reason the wait above doubled: the
            # bolt closes at 3 px/frame and the chaser now contributes 0.5 of
            # its own instead of 1, so the 38 px to MO_BULHIT_W takes ~11 frames
            # rather than ~9. The window is a bound on patience, not part of the
            # claim — the verdict below is still that BOTH slots go dark on one
            # frame while the other chaser keeps rendering.
            #
            # THE PRESENTATION LAG, handled the way the oracle case handles it:
            # a WRAM read describes the tick just run, an OAM read describes the
            # one before it. Reading the census FIRST and the OAM after a single
            # advance puts both on the same tick, so "the census fell" and "the
            # slot went dark" are statements about one frame and not two.
            census = (m.read_u16(W, WR_CHASERS), m.read_u16(W, WR_SHOTS))
            m.advance(1)
            oam = _oam(m)
            ene = _emitted(oam, ENE_SLOT0, ENE_N, T_ENEMY)
            bul = _emitted(oam, BUL_SLOT0, BUL_N, T_BULLET)
            # THE BOLT IS THE HIT SIGNAL, NOT THE TARGET. The target does
            # not stop emitting on the hit frame — it starts DYING,
            # so its slot stays on screen (flashing) for MO_DEATH_FRAMES.
            # Watching the target here kept the loop running past the kill and
            # appended PARKED bolt y values to `travel`, which is exactly what
            # it did: [98, 95 ... 74, 240, 240, 240, 240], and the climb check
            # then read 98 -> 240 as the bolt falling.
            if bul:
                before = (oam, ene, bul) + census
                travel.append(_entry(oam, BUL_SLOT0)[1])
                continue
            after = (oam, ene, bul) + census
            break

    assert before is not None, "the target never rendered"
    assert after is not None, (
        f"the bolt was still flying at the end of the window — it went through "
        f"chaser slot {tgt} instead of hitting it")

    b_oam, b_ene, b_bul, b_ch, b_sh = before
    a_oam, a_ene, a_bul, a_ch, a_sh = after

    # The bolt was a TRAVELLING bolt, seen climbing on its way in.
    assert len(travel) >= 4 and travel[0] - travel[-1] >= 12, (
        f"the bolt did not visibly travel before the hit: OAM y {travel}")

    # THE KILL: the target's slot goes dark, and the bolt's goes dark with it.
    assert b_bul and not a_bul, (
        f"the chaser stopped rendering but the bolt did not: bolts {b_bul} -> "
        f"{a_bul}. A hit frees BOTH slots; a bolt going back alone is a TTL "
        f"expiry and would leave the chaser on the floor")

    # NOT A CULL: the target was well inside the screen on its last frame, and
    # the bystander chaser is unaffected across the very same frame.
    x, y, tile, attr, x9, size = _entry(b_oam, tgt)
    cx, cy = (x - 256 if x9 else x) + OBJ_HALF, y + OBJ_HALF
    assert 0 <= cx <= 2 * SCREEN_CX and 0 <= cy <= 2 * SCREEN_CY, (
        f"the target was already leaving the screen at ({cx},{cy}); a slot that "
        f"stops emitting there is a cull, not a kill")
    bystanders = [s for s in b_ene if s != tgt]
    assert bystanders and all(s in a_ene for s in bystanders), (
        f"chasers {bystanders} stopped rendering alongside the target — that is "
        f"a sweep of the whole window, not one bolt hitting one chaser")

    # Corroboration, read after the verdict rather than instead of it.
    #
    # THE CHASER CENSUS DOES NOT FALL ON THE HIT FRAME, and that is the death
    # animation rather than a weakening: a hit no longer frees the chaser's
    # slot on the spot, it marks the slot DYING so the thing visibly dies where it stood
    # for MO_DEATH_FRAMES and only then goes back. The bolt is still spent
    # immediately. `…kill_visibly_dies…` and `…distinguishable_from_a_despawn…`
    # assert the flash itself; what is checked here is that the allocate ->
    # active -> free -> REUSE cycle still completes, just later.
    assert a_sh == b_sh - 1, (
        f"the bolt was not spent by the hit: bolts {b_sh} -> {a_sh}")
    assert a_ch == b_ch, (
        f"the chaser's slot was freed on the hit frame ({b_ch} -> {a_ch}). "
        f"it should be marked DYING and freed when the flash ends — a "
        f"slot that vanishes immediately is the despawn-shaped kill playtesting "
        f"could not read")

    # ...and the death is BOUNDED. Without this the case would pass on a chaser
    # that was marked dying and then flashed forever — a leaked slot that never
    # returns to the pool looks, frame by frame, exactly like a working kill.
    # Asserted on the render: the target must STOP carrying the score band.
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        m.advance(76)                          # the same geometry as above
        m.advance(2, pad1={"a": True})
        band = []
        for _ in range(18 + MO_DEATH_FRAMES + 20):
            m.advance(1)
            band.append(_entry(_oam(m), tgt)[3] == ATTR_SCORE)
    assert any(band), "the target never flashed — the shot did not connect"
    first = band.index(True)
    last = len(band) - 1 - band[::-1].index(True)
    assert last - first <= MO_DEATH_FRAMES + 2, (
        f"the target carried the score band across {last - first} frames, more "
        f"than the {MO_DEATH_FRAMES}-frame death window allows — the slot is "
        f"flashing without ever being freed, which is a leak rather than a kill")


def test_a_chaser_reaching_the_hero_knocks_the_world_out_from_under_him(tmp_path):
    """THE SECOND WORLD-SPACE BOX COLLISION (`do_contact`), and the rail's
    sixth done-condition — *"a hero-enemy contact knocks the hero back"* —
    which nothing else in this module asserts.

    THE CASE DRIVES INTO THE CONTACT INSTEAD OF AROUND IT. The two pillar cases
    deliberately pick windows a chaser cannot reach (`:579-582`, `:588-591`);
    this one holds RIGHT from the spawn cell all the way in, parks against the
    same pillar face 80 world px from spawn, and keeps pushing while the wave
    closes on a hero who cannot retreat.

    THE KNOCKBACK IS INVISIBLE IN THE AVATAR'S OWN POSITION, by construction —
    `arena.asm`'s do_contact says so — because the pivot follows him. So the
    user-visible form of "he was knocked back" is that THE WORLD MOVES, and it
    moves in the one way walking never produces: every rendering chaser jumps by
    the SAME screen vector in a single frame. That is a pivot TRANSLATION — the
    hero was picked up and put down 80 px away. A rotation moves each actor by a
    different vector, and a chaser walking moves itself and nothing else.
    Measured: 79-81 px in one frame against 4-6 px on every other frame.

    WHAT CHANGED, AND WHY THIS CASE DID. Until 2026-08-08 the second half of this
    assertion was that the SCREEN snapped dark and paced back up: do_contact
    wrote INIDISP brightness 1 and re-armed `fade_start_in`. That shipped, and
    playtesting reported the scene "constantly flipping to black with a fade in" —
    a full-screen strobe near 1.5 Hz, which is a photosensitivity hazard on top
    of being a bad read. This case was ASSERTING THE DEFECT: it required the
    flash, so it would have gone red on the fix. The cue is now local to the
    hero's own sprite, and the three cases above own it
    (`…the_screen_never_strobes…`, `…the_hit_cue_is_the_hero_blinking…`,
    `…does_not_blink_when_he_has_not_been_hit`).

    What this case keeps is the MECHANIC — a contact still knocks the hero back —
    plus the hero's own two states across the window: he is either drawn at the
    pin or blinked out by the cue, and never anywhere else on screen. The state
    cycle is still whole: walk, contact, teleport + blink, recover, walk on.
    """
    # No screenshot inside the loop, so the pad is genuinely held on EVERY frame
    # (a capture costs an emulated frame with both pads released). Measured on
    # this drive: knockbacks at CLEAN+207, +248, +289, ... — the hero is pinned
    # against the pillar and cannot retreat, so they come one grace window apart.
    # The 40-frame sample from CLEAN+180 brackets the first and only the first.
    frames = []
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        # TURN, THEN WALK. This drive used to hold RIGHT, which WAS the east
        # heading under the deleted table; RIGHT now TURNS, so holding it walks
        # nowhere and rotates forever. 192 is that table's own value for RIGHT,
        # reached continuously and then RELEASED — so the heading is constant
        # across every comparison frame below and translation is the only thing
        # that can move the floor, which is what the case claims.
        _turn_to(m, 192)
        m.advance(180, pad1=PAD_U)        # hard against the pillar face
        for i in range(40):               # ...one contact falls inside this window
            oam = _oam(m)
            frames.append((_entry(oam, HERO_SLOT), _chaser_centres(oam)))
            m.advance(1, pad1=PAD_U)

    # THE HERO NEVER MOVES ON SCREEN — not while walking, not while knocked back.
    # Two entries are legal now and only two: drawn at the pin, or parked by the
    # blink. Anything else means he was placed somewhere, which the pivot is
    # supposed to make impossible.
    heroes = {f[0] for f in frames}
    assert heroes <= {HERO_DRAWN, HERO_BLINKED}, (
        f"the hero's OAM entry took a value that is neither 'drawn at the pin' "
        f"nor 'blinked out': {heroes - {HERO_DRAWN, HERO_BLINKED}}. He is pinned "
        f"by the pivot, so the knockback must show up in the WORLD, not in him")
    assert HERO_DRAWN in heroes, "the hero was never drawn at all in this window"

    # THE COHORT JUMP: exactly one frame where the whole cast slides together.
    jumps = _knockbacks([f[1] for f in frames])
    assert len(jumps) == 1, (
        f"expected exactly one knockback in the window, saw {len(jumps)} at "
        f"{jumps}. Per-frame chase motion measured under 6 px, so a >=40 px "
        f"cohort move is the teleport and nothing else")

    # ...and it really was a shared vector over more than one chaser, which is
    # what makes it a translation rather than a rotation or one chaser walking.
    i = jumps[0]
    prev, cur = frames[i - 1][1], frames[i][1]
    both = [s for s in cur if s in prev]
    deltas = [(cur[s][0] - prev[s][0], cur[s][1] - prev[s][1]) for s in both]
    assert len(deltas) >= 2, (
        "only one chaser was on screen at the knockback, so 'they all moved "
        "together' cannot be told apart from 'one of them moved'")
    assert max(abs(dx) + abs(dy) for dx, dy in deltas) >= 40, (
        f"the cohort move was too small to be the 80 px teleport: {deltas}")

    # THE BLINK IS THE CUE THAT ACCOMPANIES IT: the hero is parked on at least
    # one frame after the knockback, and drawn again before the window ends.
    after = [f[0] for f in frames[i:]]
    assert HERO_BLINKED in after, (
        "the hero never blinked after the knockback — the contact produced no "
        "cue at all, which is the state the flash was added to avoid")
    assert after[-1] == HERO_DRAWN or HERO_DRAWN in after[1:], (
        "the hero never came back after the knockback blink")


def test_the_screen_never_strobes_to_black_during_a_sustained_walk(tmp_path):
    """THE OWNER'S COMPLAINT, AS A GATE: *"the scene is constantly flipping to
    black with a fade in"*.

    `do_contact` used to snap ES_FADE_CTL (INIDISP brightness) to 1 and re-arm
    the fade on every hero-chaser contact, and contact re-fired on the frame the
    grace expired — so the whole screen strobed to near-black about every 40
    frames for as long as the rail was played. Measured on the shipped ROM by
    this exact drive: mean luminance 4.3 at its floor, 13 of 60 samples under
    45. A full-screen flash at ~1.5 Hz is a photosensitivity hazard, so there is
    no tuning of it that would have been acceptable — the cue had to stop being
    full-screen, which is what `do_hit_blink` does.

    Read as the RENDERED FRAME's mean luminance, which is the quantity playtesting
    actually reported, rather than as "is ES_FADE_CTL untouched" — the latter
    would pass the day something else dims the screen.

    NON-VACUITY IS ASSERTED, NOT ASSUMED. A window with no contact in it would
    hold any luminance floor trivially, so the case also requires that the hit
    cue FIRED inside the window (some sample with the hero blinked out). Without
    that this test would go green on a build where contact never happens at all.
    """
    lum, hero = [], []
    with Machine(str(ROM)) as m:
        m.advance(BOOT)                       # past the enter fade, chasers up
        _turn_to(m, 192)                      # east, then WALK it. PAD_R turns
                                              #   now, so holding it here would
                                              #   spin in place and the case's
                                              #   own name ("a sustained walk")
                                              #   would stop being true
        for i in range(60):
            m.advance(3, pad1=PAD_U)
            img = _shot(m, tmp_path, f"strobe_{i:02d}.png")
            lum.append(_luma(img))
            hero.append(_hero_px(img))

    assert min(lum) >= LUMA_FLOOR, (
        f"the screen dropped to mean luminance {min(lum):.1f} during an ordinary "
        f"walk (floor {LUMA_FLOOR}, the scene's normal level is 62-64). "
        f"{sum(1 for x in lum if x < LUMA_FLOOR)}/{len(lum)} samples were under "
        f"it. That is the full-screen contact strobe playtesting reported; the hit "
        f"cue is supposed to be the hero blinking, not the picture going out")

    assert 0 in hero, (
        "the hit cue never fired in this window, so the luminance floor above "
        "proved nothing — no contact happened at all. Non-vacuity: this drive is "
        "supposed to walk into the pillar and be caught")


def test_the_hit_cue_is_the_hero_blinking_not_the_whole_screen(tmp_path):
    """THE REPLACEMENT CUE, and the property that makes it a replacement:
    it is LOCALISED.

    The hero is screen-fixed — m7a_set_center re-pins the pivot to his world
    position every frame — so a knockback that teleports him to spawn moves the
    FLOOR and not him. Something has to say "that was damage". The rail now says
    it with an invulnerability blink on his own 16x16 sprite for the grace
    window (`do_hit_blink`, arena.asm), which is the genre's standard vocabulary
    and touches no PPU brightness register.

    THE ASSERTION IS A CONJUNCTION, AND IT HAS TO BE. "The hero's pixels vanish"
    is NOT enough on its own: on the shipped ROM they vanish too, because the
    full-screen fade takes the hero down with everything else — measured, 9 such
    frames in this very window at luminance 4.2. What separates a blink from a
    blackout is that the rest of the picture is UNAFFECTED. So:

      * the hero's own pixel count goes to zero on some frame  (the cue fires)
      * ...and comes BACK                                      (it blinks)
      * ...and on every frame of the window, including the dark ones, the
        frame's mean luminance is above the floor                (it is LOCAL)

    Read entirely from rendered pixels: the cue's own output region is counted
    by the hero's colour band, and the "not the whole screen" half is the same
    frames' mean luminance."""
    rows = []
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        _turn_to(m, 192)                      # east — the deleted table's own
        m.advance(110, pad1=PAD_U)            #   value for RIGHT — then walk it
                                              #   hard against the pillar face,
                                              #   which is what puts the hero
                                              #   somewhere a chaser can reach
                                              #   him. Holding PAD_R now turns.
        for i in range(60):
            img = _shot(m, tmp_path, f"cue_{i:02d}.png")
            rows.append((_hero_px(img), _luma(img)))
            m.advance(1, pad1=PAD_U)

    hp = [r[0] for r in rows]
    lm = [r[1] for r in rows]

    dark = [i for i, h in enumerate(hp) if h == 0]
    assert dark, (
        f"the hero never blinked out across {len(rows)} frames of being ground "
        f"against the pillar — the hit cue never fired. Hero pixel counts: "
        f"min {min(hp)}, max {max(hp)}")

    assert max(hp) >= 60, (
        f"the hero is barely on screen even at his brightest ({max(hp)} px). "
        f"The blink is supposed to alternate a WHOLE 16x16 sprite")

    lit_after = [i for i in range(dark[0], len(hp)) if hp[i] > 0]
    assert lit_after, (
        f"the hero blinked out at frame {dark[0]} and never came back. That is "
        f"a disappearance, not an invulnerability blink")

    assert min(lm) >= LUMA_FLOOR, (
        f"the frame's mean luminance fell to {min(lm):.1f} (floor {LUMA_FLOOR}) "
        f"during the hit cue. The cue is supposed to be LOCAL to the hero's own "
        f"sprite — a full-screen dim is the defect this replaced")

    # ...and the dark frames specifically are the ones that must stay bright:
    # that is precisely where the old flash put its near-black frames.
    assert min(lm[i] for i in dark) >= LUMA_FLOOR, (
        f"on the frames where the hero is blinked out, mean luminance fell to "
        f"{min(lm[i] for i in dark):.1f}. The hero's pixels going away IS the "
        f"cue; the rest of the picture going with them is the strobe")


def test_the_hero_does_not_blink_when_he_has_not_been_hit(tmp_path):
    """The control arm for the case above: the blink means SOMETHING.

    A cue that fired all the time would satisfy every assertion in
    `…the_hit_cue_is_the_hero_blinking…` and carry no information. The blink is
    gated on US_GRACE, so before the first wave beat can possibly reach the hero
    he must be solid on every single frame."""
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        counts = []
        for i in range(24):                   # no chaser is near him yet
            counts.append(_hero_px(_shot(m, tmp_path, f"solid_{i:02d}.png")))

    assert min(counts) >= 60, (
        f"the hero blinked with no contact behind it: pixel counts {counts}. "
        f"The cue is gated on the grace window, so an un-hit hero is solid")


def test_grace_gates_repeat_contact_and_the_chase_leaves_room_to_play(tmp_path):
    """THE SECOND HALF OF THE OWNER'S REPORT — being knocked back constantly.

    Deleting the flash would have hidden this rather than fixed it: contact was
    re-firing on the exact frame the grace expired, forever, so the player never
    got to act. The cause is a SPEED RELATIONSHIP, not a stray constant. The hero
    moves 1.25 px/frame along his heading (0.88 per axis on a diagonal); a chaser
    moved 1 px per axis EVERY frame, i.e. 1.0 cardinal and 1.41 diagonal. A
    fleeing hero therefore gained 0.25 px/frame at best and LOST 0.12 on a
    diagonal, while clearing the 12 px contact box inside the 40-frame grace
    needs more than 0.30 sustained. So the grace could never create separation —
    it suppressed the hit and handed him back inside the box. No value of
    MO_GRACE_FRAMES fixes a pursuer faster than the pursued; the chasers now step
    every other frame (MO_CHASE_HALF).

    BOTH HALVES ARE ASSERTED FROM THE RENDER, via the cohort translation that IS
    a knockback on screen (`_knockbacks`) — not from US_HITS, which is one call
    away and is the proxy CLAUDE.md rule 2 forbids:

      * the grace still gates a repeat — no two knockbacks closer than the
        window. This must not regress; it held on the shipped ROM too (measured
        min gap 41) and it is the mechanism's contract.
      * the RATE is now playable. Measured over this drive: 20 knockbacks on the
        shipped ROM against 3 after the fix, so the bound at 8 separates them
        with better than 2x margin either way.
    """
    seq = []
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        for f in range(900):                  # 15 s of kiting, pad held EVERY
            m.advance(1, pad1=_kite(f))       #   frame — no screenshot in here,
            seq.append(_chaser_centres(       #   so nothing releases the pad
                m.read_bytes(O, 0, 544)))

    hits = _knockbacks(seq)
    gaps = [b - a for a, b in zip(hits, hits[1:])]

    assert len(hits) <= 8, (
        f"{len(hits)} knockbacks in {len(seq)} frames of ordinary kiting. The "
        f"shipped ROM managed 20 and playtesting reported being unable to play; "
        f"after halving the chase rate this drive measures 3. Gaps: {gaps}")

    assert all(g >= MO_GRACE_FRAMES for g in gaps), (
        f"two contacts landed {min(gaps)} frames apart, inside the "
        f"{MO_GRACE_FRAMES}-frame grace window that is supposed to gate them: "
        f"{gaps}. The grace suppresses the HIT, so a repeat inside it is the "
        f"suppression failing")


# =============================================================================
# THE PLAYABILITY LAYER — a reason to engage
# =============================================================================
# The owner's broader critique of this rail was *"we built targeting a feature
# but forgot how to make it fun"*. Three things answer it and each gets a case:
# a score that moves, a kill you can SEE, and a cost for being hit.

def _first_chaser_ahead(m):
    """Advance to the first wave beat and return the chaser's OAM slot.

    The first beat places its chaser at ring offset 0 — straight up the world,
    which at the boot heading is straight up the SCREEN, i.e. already in the
    hero's line of fire. That is the rail's own ring order, not a contrivance,
    and it is what lets a kill be driven without steering."""
    m.advance(CLEAN)
    m.advance(60)
    live = _emitted(_oam(m), ENE_SLOT0, ENE_N, T_ENEMY)
    assert live, "no chaser on screen at the first wave beat"
    return live[0]


def test_a_kill_visibly_dies_and_the_score_increments(tmp_path):
    """*"kill something and KNOW you did"* — the spec acceptance item 4.

    Before this change a killed chaser vanished between two frames and nothing
    else on screen changed. Now two things happen, and both are asserted on the
    render rather than on US_KILLS or US_SCORE:

      * THE SCORE READOUT MOVES. The three HUD digit tiles are read out of OAM
        and DECODED — this asserts the number the player can actually read, not
        the word it came from. A HUD that stopped being drawn, or drew the wrong
        digit, or drew it at the wrong slot, fails here.
      * THE TARGET VISIBLY DIES. Its OAM entry stays on screen for the death
        flash carrying the SCORE palette band rather than the chaser's, and
        green pixels appear where there were only the HUD's before. A slot that
        merely disappeared would show neither.
    """
    with Machine(str(ROM)) as m:
        tgt = _first_chaser_ahead(m)
        before_oam = _oam(m)
        base_green = _green_px(_shot(m, tmp_path, "kill_a.png"))
        assert _score_shown(before_oam) == 0, (
            f"the HUD reads {_score_shown(before_oam)} before any kill")

        m.advance(2, pad1={"a": True})              # one bolt, on A's edge
        flash_frames, peak_green, hit_at = 0, 0, None
        for i in range(60):
            m.advance(1)
            oam = _oam(m)
            attr = _entry(oam, tgt)[3]
            if attr == ATTR_SCORE:
                flash_frames += 1
                if hit_at is None:
                    hit_at = i
                    img = _shot(m, tmp_path, "kill_flash.png")
                    peak_green = _green_px(img)
            if _score_shown(oam) > 0 and hit_at is not None and i > hit_at + 30:
                break
        final = _oam(m)

    assert hit_at is not None, (
        "the target never carried the score palette — nothing on screen said a "
        "kill happened")
    assert flash_frames >= 8, (
        f"the death flash was visible on only {flash_frames} frames; it is a "
        f"{MO_DEATH_FRAMES}-frame window blinking half the time, so ~12 are "
        f"owed. A flash this short is not a kill you can see")
    assert peak_green > base_green + 20, (
        f"green pixels went {base_green} -> {peak_green} on the kill frame. The "
        f"dying chaser draws in the score band, so a 16x16 corpse owes far more "
        f"than the three HUD digits alone")
    assert _score_shown(final) == 1, (
        f"the HUD reads {_score_shown(final)} after one kill, not 1. Tiles: "
        f"{_score_tiles(final)}")


def test_a_kill_is_distinguishable_from_a_despawn(tmp_path):
    """the spec — *"a kill is distinguishable from an enemy leaving/despawning"*.

    THE CONTRAST IS THE CLAIM, so both events are driven in the same ROM and
    compared. A BOLT despawns: its TTL expires and its slot parks between two
    frames, with no flash and no score. A CHASER dies: its slot stays on screen
    for the death window in the score band and the readout moves.

    Without this pairing "the kill flashes" would be a claim about one event
    with nothing to be distinguishable FROM — and the rail's original defect was
    exactly that the two looked identical."""
    # ---- the despawn: fire into empty space, away from the first chaser ----
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        _turn_to(m, 128)                    # about-face: nothing to hit behind us
        m.advance(2, pad1={"a": True})
        bolt = _emitted(_oam(m), BUL_SLOT0, BUL_N, T_BULLET)
        assert bolt, "no bolt was spawned"
        b = bolt[0]
        despawn_flash = 0
        parked_at = None
        for i in range(140):
            m.advance(1)
            x, y, tile, attr, _, _ = _entry(_oam(m), b)
            if attr == ATTR_SCORE:
                despawn_flash += 1
            if tile == 0 and y == MO_PARK_Y:
                parked_at = i
                break

    assert parked_at is not None, (
        "the bolt never expired — the despawn half of this comparison never "
        "happened, so there is nothing to distinguish a kill from")
    assert despawn_flash == 0, (
        f"the despawning bolt carried the score palette on {despawn_flash} "
        f"frames. A despawn must NOT flash, or it looks exactly like a kill "
        f"and the distinction this case exists for is gone")

    # ---- the kill: the same rail, the other event -------------------------
    with Machine(str(ROM)) as m:
        tgt = _first_chaser_ahead(m)
        m.advance(2, pad1={"a": True})
        kill_flash = 0
        for _ in range(60):
            m.advance(1)
            if _entry(_oam(m), tgt)[3] == ATTR_SCORE:
                kill_flash += 1
        killed_score = _score_shown(_oam(m))

    assert kill_flash >= 8, (
        f"a kill flashed on {kill_flash} frames — it has to be visibly "
        f"different from the despawn above, which flashed on 0")
    assert killed_score >= 1, "a kill did not move the readout"


def test_a_contact_costs_the_score_that_was_earned(tmp_path):
    """THE STAKE — *"be hurt and know it, and have a reason to avoid it"*.

    The knockback and the blink already said "you were hit". Neither cost the
    player anything they were accumulating, so there was no reason beyond mild
    annoyance to avoid contact. Now a contact takes the score.

    Asserted on the RENDERED READOUT at both ends: it must reach a non-zero
    value the player could see, and it must be back at 000 after a contact. The
    contact itself is detected the way this module already detects one — the
    cohort of chasers sliding together, which is what a knockback looks like on
    a screen where the hero cannot move."""
    with Machine(str(ROM)) as m:
        tgt = _first_chaser_ahead(m)
        m.advance(2, pad1={"a": True})
        for _ in range(60):
            m.advance(1)
            if _score_shown(_oam(m)) > 0:
                break
        earned = _score_shown(_oam(m))

        # ...then WALK AWAY FROM SPAWN and let one catch us there.
        #
        # NOT "stand still", which is what this drive did first and which cannot
        # be detected: a knockback teleports the hero TO SPAWN, so a hero who
        # never left spawn is knocked back to where he already is, the world
        # does not move, and `_knockbacks` — which reads the cohort translation
        # — correctly reports nothing. Measured: 0 contacts found in 700 frames
        # of standing, while US_HITS was climbing. The rendered event only
        # exists if there is a teleport to render, so the drive has to create
        # one. Held RIGHT is the same approach `…knocks_the_world_out_from_
        # under_him…` uses, and it parks against a pillar face 80 px out.
        seq, shown = [], []
        for _ in range(700):
            m.advance(1, pad1=PAD_U)
            oam = m.read_bytes(O, 0, 544)
            seq.append(_chaser_centres(oam))
            shown.append(_score_shown(oam))

    assert earned >= 1, "never scored, so there is nothing for a contact to cost"
    hits = _knockbacks(seq)
    assert hits, ("no contact in 700 frames of standing still — the stake "
                  "cannot be asserted if the hazard never lands")
    after = shown[hits[0] + 2]
    assert after == 0, (
        f"the HUD still reads {after} two frames after a knockback. A contact "
        f"is supposed to cost the score — that is the reason to avoid one")


MO_CONTACT_W = 12                         # the hero-chaser overlap box, world px


@pytest.mark.parametrize("heading", OFF_AXIS_HEADINGS)
def test_the_hero_outruns_a_chaser_at_headings_across_the_whole_turn(heading):
    """THE GENERALISED SPEED CHECK.

    The chasers' rate is half what it first was, because the original chase was
    unwinnable by construction: the hero gained 0.25 px/frame at best and LOST 0.12 on a
    diagonal, against the 0.30 px/frame needed to clear the 12 px contact box
    inside the 40-frame grace. So the grace suppressed the hit without ever
    creating separation, and contact re-fired the frame it expired, forever.

    THAT PROOF COVERED EIGHT HEADINGS — the only ones the deleted table could
    produce. With continuous headings it has to hold across all 256, so this
    re-derives it at eight the old scheme could not reach, from MEASUREMENTS
    rather than from the arithmetic:

      * the CHASER's rate is read from OAM while the hero stands still. Standing
        pins the pivot, so a chaser's screen motion IS its world motion — and
        this is the term that varies with geometry, because a chaser steps one
        px per AXIS and is therefore 1.41x faster on a diagonal than on a
        cardinal. Measuring it beats assuming it.
      * the HERO's rate is read from the floor, because he cannot move on screen
        — `_floor_shift` over a held-UP run is his travel.

    Then the original inequality, restated: what he gains per frame, over the
    grace window, must clear the contact box.

    WHY NOT "flee for 600 frames and count contacts". That was tried and it is
    the wrong claim: a knockback returns the hero TO SPAWN,
    which is where every chaser is converging, so running in a straight line
    from a swarm is not survivable at any heading and never was. The rate at
    which ordinary play gets knocked back is a real claim and it has a case —
    `…grace_gates_repeat_contact…`, over a kiting drive that turns. This case is
    the SPEED relationship, which is the thing that has to hold at every
    heading rather than at the eight a table happened to list."""
    MEASURE = 12
    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        _turn_to(m, heading)
        # ---- the chaser term: pure world motion, the pivot held still -------
        first = _chaser_centres(_oam(m))
        m.advance(20)
        second = _chaser_centres(_oam(m))
        both = [s for s in first if s in second]
        assert both, "no chaser rendered across the standing window"
        chaser_rate = max(
            math.hypot(second[s][0] - first[s][0], second[s][1] - first[s][1])
            for s in both) / 20.0

    with Machine(str(ROM)) as m:
        m.advance(BOOT)
        _turn_to(m, heading)
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            a = _shot(m, Path(td), "esc_a.png")
            m.advance(MEASURE, pad1=PAD_U)
            b = _shot(m, Path(td), "esc_b.png")
            dx, dy, score = _floor_shift(a, b, radius=20)
    assert score > 0.80, f"weak floor correlation ({score:.2f})"
    hero_rate = math.hypot(dx, dy) / MEASURE

    gain = (hero_rate - chaser_rate) * MO_GRACE_FRAMES
    assert gain >= MO_CONTACT_W, (
        f"at heading {heading} the hero makes {hero_rate:.2f} px/frame against "
        f"a chaser closing at {chaser_rate:.2f}, so over the {MO_GRACE_FRAMES}-"
        f"frame grace he gains {gain:.1f} px — less than the {MO_CONTACT_W} px "
        f"contact box. That is the unwinnable relationship: the grace would "
        f"suppress the hit without ever creating separation, and contact would "
        f"re-fire the frame it expired")


def test_the_wave_beat_puts_chasers_on_the_floor_and_they_close_in():
    """M4's other pool: a timed beat CLAIMS a slot, places the chaser on a world
    ring around the player, and the chase closes the distance.

    Read as the rendered distance from screen centre — which under a rotation is
    the world distance, because a rotation preserves it. So "they close in" is
    asserted on the projection's output rather than on the world array the chase
    updates."""
    def radius(oam, slots):
        out = []
        for s in slots:
            x, y, tile, attr, x9, size = _entry(oam, s)
            if tile != T_ENEMY:
                continue
            cx = (x - 256 if x9 else x) + OBJ_HALF
            cy = y + OBJ_HALF
            out.append(((cx - SCREEN_CX) ** 2 + (cy - SCREEN_CY) ** 2) ** 0.5)
        return out

    slots = range(ENE_SLOT0, ENE_SLOT0 + ENE_N)
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        assert not radius(_oam(m), slots), \
            "a chaser is on screen before the first wave beat"
        m.advance(70)                          # past MO_SPAWN_PERIOD
        near0 = min(radius(_oam(m), slots), default=None)
        assert near0 is not None, "the wave beat spawned nothing"
        m.advance(60)
        near1 = min(radius(_oam(m), slots), default=None)
    assert near1 is not None and near1 < near0 - 20, (
        f"the nearest chaser did not close: {near0:.0f} -> "
        f"{near1 if near1 is None else round(near1)} px from centre")


# =============================================================================
# The uploads, and the colours the other cases count
# =============================================================================
@pytest.mark.parametrize("blob,at", [
    ("mo_hero_pal.bin", 128),
    ("mo_enemy_pal.bin", 144),
    ("mo_bullet_pal.bin", 160),
])
def test_an_obj_palette_blob_lands_in_cgram_byte_for_byte(blob, at):
    """The DESTINATION region, read directly.

    An upload that silently no-ops leaves a downstream case passing on whatever
    power-on left in CGRAM, which is why this reads the sixteen words at the
    claim's own base rather than inferring them from a rendered colour."""
    want = (ASSETS / blob).read_bytes()
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)
        got = m.read_bytes(C, at * 2, len(want))
    assert bytes(got) == want


def test_bolts_read_yellow_and_chasers_read_red_and_neither_shows_without_them(tmp_path):
    """THE COLOUR PREDICATES the other cases lean on, tied to the render.

    tools/gen_m7_oshoot_assets.py's assert_colour_bands() proves at BUILD time
    that no floor, wall or hero colour satisfies either predicate, and that the
    chaser and the bolt each satisfy exactly one. This case is the other half:
    that the ROM actually renders them, and renders neither when the pool is
    empty.

    Both are needed. The build assert alone would hold on a ROM that never drew
    a bolt; a pixel count alone would hold on a palette where the floor was
    yellow too."""
    with Machine(str(ROM)) as m:
        m.advance(CLEAN)                       # before the first wave beat
        empty = _shot(m, tmp_path, "colours_empty.png")
        assert not _emitted(_oam(m), BUL_SLOT0, BUL_N, T_BULLET)
        assert not _emitted(_oam(m), ENE_SLOT0, ENE_N, T_ENEMY)

        m.advance(2, pad1={"a": True})
        m.advance(4)
        firing = _shot(m, tmp_path, "colours_bolt.png")
        m.advance(140)                         # let the waves arrive
        crowded = _shot(m, tmp_path, "colours_crowd.png")

    e = list(empty.get_flattened_data())
    assert sum(1 for p in e if _yellow(p)) == 0, "yellow with no bolt on screen"
    assert sum(1 for p in e if _red(p)) == 0, "red with no chaser on screen"

    f = list(firing.get_flattened_data())
    assert sum(1 for p in f if _yellow(p)) >= 10, "a fired bolt renders no yellow"

    c = list(crowded.get_flattened_data())
    assert sum(1 for p in c if _red(p)) >= 20, "the wave renders no red"
