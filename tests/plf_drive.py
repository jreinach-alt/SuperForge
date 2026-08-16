"""Shared platformer drive helpers (NOT a test module).

Deterministic frame-stepped driving. Every primitive here is CLOSED-LOOP: it
reads the hero's world position out of WRAM each frame and decides the next
input, rather than replaying a fixed button script. That is not a convenience
— an open-loop script is a measurement of the host's timing as much as of the
ROM, and the moment a physics constant moves it silently drives somewhere
else and the assertions downstream test nothing.

The state words below are NAVIGATION: they get the machine into the state
under test. The assertions in tests/test_platformer.py read the rendered
output (VRAM / OAM / CGRAM / screenshot pixels), never these.
"""
import json
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MemoryType  # noqa: E402

W, V, O, C = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
              MemoryType.SnesSpriteRam, MemoryType.SnesCgRam)

ROM = SUPERFORGE / "build" / "platformer.sfc"
_JMAP = json.loads((SUPERFORGE / "build" / "pl" / "symbol_map.json").read_text())

SCENE_TITLE, SCENE_PLAY, SCENE_OVER, SCENE_WIN = 0, 1, 2, 3


def sym(name, scene=None):
    """A placement from the emitted map — addresses are ASKED FOR, never
    hardcoded, so a re-pack moves the tests with the code."""
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — the allocator moved it?")


SM_CTL = sym("ES_SM_CTL")["start"]
FADE_CTL = sym("ES_FADE_CTL")["start"]
PLF_MAP = sym("ES_V_PLF_MAP", "play")["start"]           # VRAM WORD addresses
PLF_SKY = sym("ES_V_PLF_SKY", "play")["start"]
OBJ_CHR = sym("ES_V_OBJ_CHR", "play")["start"]
TXT_MAP = {s: sym("ES_V_TEXT_MAP", s)["start"]
           for s in ("title", "play", "over", "win")}
PLX_TAB = sym("ES_PLX_TAB", "play")["start"]             # WRAM ($7E) offset
TAKEN = sym("ES_PLF_TAKEN", "play")["start"]
CAM = sym("ES_PLF_CAM", "play")["start"]                 # DP, mirrored in WRAM
C_PLF_PAL = sym("ES_C_PLF_PAL", "play")["start"]
C_HERO_PAL = sym("ES_C_HERO_PAL", "play")["start"]
C_GHOST_PAL = sym("ES_C_GHOST_PAL", "play")["start"]
C_DUSK = sym("ES_C_DUSK", "play")["start"]
O_HERO = sym("ES_O_HERO", "play")["start"]
O_GHOSTS = sym("ES_O_GHOSTS", "play")["start"]
O_HI_PAD = sym("ES_O_HI_PAD", "play")["start"]
OAM_SHADOW = sym("ES_OAM_SHADOW")["start"]

DP = {k: sym("US_" + k.upper(), "play")["start"]
      for k in ("px", "pyf", "pixy", "vy", "grounded", "facing", "hurt",
                "lives", "coins", "gover", "paused", "dirty",
                "e1x", "e1d", "e2x", "e2d", "e1alive", "e2alive",
                "atick", "aframe", "msg", "msgpos")}
G_RUNS = sym("US_RUNS")["start"]
G_BANK = sym("US_BANK")["start"]
G_CONTOK = sym("US_CONTOK")["start"]
G_CONTPEND = sym("US_CONTPEND")["start"]


# --- the rail's declared shape (game/platformer/platformer.inc), restated
# here as an ORACLE deliberately independent of the ROM ----------------------
MAP_W, MAP_H = 64, 32
WORLD_W, SCREEN_W = 512, 256
CAM_MAX = WORLD_W - SCREEN_W
BOX = 8
SPAWN_X, SPAWN_Y = 24, 184
PIT_Y = 216
LIVES = 3
COINS_ALL = 6
WALK = 2
PLX_SPLIT, PLX_LINES, PLX_SHIFT = 96, 224, 3
G1_Y, G2_Y = 184, 120
BLINK = 4
ANIM_RATE, ANIM_STEPS = 8, 4
PLF_PLAY_SKY = 0x0000       # CGRAM 0 in `play`: black, the surface the ramp
                            #   is ADDed to (backdrop colour math)
PLF_DUSK = 0x1C8D           # CGRAM 0 in the three gradient-less menu scenes:
                            #   the ramp's own midpoint, (13,4,7)

# The COLDATA table entry k lands on PPU scanline k+1: the HDMA transfer for a
# line happens during the PREVIOUS line's HBlank. MEASURED, not assumed --
# tools/compare_ref_dusk.py finds this offset by search in BOTH ROMs and
# they agree, and rgb_gradient.asm's header note says the same from the other
# end. Scanline 0 therefore shows no table entry at all.
GRAD_LAG = 1

# The imported actors' OBJ pages. Multiples of 16 and 32 apart, which is the
# vendored blobs' load contract: a 16x16 OBJ reads {N, N+1, N+16, N+17}, so a
# four-frame sheet spans TWO 16-wide tile rows.
HERO_TILE, GHOST_TILE = 0, 32

# content_bottom PER FRAME -- the lowest drawn row + 1 inside each frame's
# 16-px box. Four numbers per actor, not one: the hero's frames do not share a
# sole (an artefact of the importer's centring, see gen_platformer_assets.py
# `content_bottoms`), and a single anchor is therefore wrong for at least one
# of them. Restated here as an ORACLE independent of the ROM; the generator
# recomputes them from the vendored PNGs and the test cross-checks both.
HERO_BOTTOMS = (16, 15, 15, 15)
GHOST_BOTTOMS = (15, 15, 15, 15)

# An OBJ renders one scanline BELOW its OAM y: the PPU evaluates a line's
# sprites during the previous line (Mesen2 SnesPpu::EvaluateNextLineSprites).
# MEASURED in both ROMs. This is the term whose absence put the actors on the
# surface line instead of above it.
OBJ_Y_LAG = 1


def plx_expect(cam):
    """The band table the camera implies: (top hofs, bottom hofs).

    The ORACLE for the parallax, derived from the declared ratios rather than
    from the ROM: 1/8 for the far clouds, 3/8 for the near hills.
    """
    return (cam >> PLX_SHIFT, (cam * 3) >> PLX_SHIFT)


def u16(r, addr):
    return r.read_u16(W, addr)


def scene_now(r):
    """(current scene id, phase) from the scene_mgr control block."""
    cur, _nxt, phase = r.read_bytes(W, SM_CTL, 3)
    return cur, phase


def oam_entry(r, slot):
    """One OAM entry as (x_low, y, tile, attr) plus its hi-table 2 bits.

    Read from HARDWARE OAM, not from the WRAM shadow: the shadow is what the
    game wrote, and hardware OAM is what the PPU renders. The DMA between
    them is the thing a test of sprite placement is entitled to doubt.
    """
    lo = r.read_bytes(O, slot * 4, 4)
    hi_byte = r.read_bytes(O, 512 + slot // 4, 1)[0]
    bits = (hi_byte >> ((slot % 4) * 2)) & 3
    x = lo[0] | ((bits & 1) << 8)
    return dict(x=x, y=lo[1], tile=lo[2], attr=lo[3], large=bool(bits & 2))


def to_title(r):
    """Boot and park on the title, frame-stepping."""
    r.boot_rom(str(ROM), frames=90)
    r.debug_break()
    r.frame_step(2)


def press(r, frames=2, **buttons):
    """A button press and its release, both frame-exact."""
    r.frame_step(frames, **buttons)
    r.frame_step(2)


def settle(r, max_frames=180):
    """Step until the scene's fade-in has finished.

    Every screenshot assertion needs this: `fade` ramps INIDISP's brightness
    over a run of frames, so a pixel sampled mid-fade is the right colour
    scaled by an arbitrary factor, and a test that compared it to a declared
    colour would be measuring the fade's progress.
    """
    for _ in range(max_frames):
        level, direction = r.read_bytes(W, FADE_CTL, 2)
        if direction == 0 and level == 15:
            r.frame_step(2)             # ...and let the NMI commit the last
            return                      #   step: the level word reaches 15 a
                                        #   frame before INIDISP does, and a
                                        #   capture in between renders every
                                        #   colour scaled by 14/15
        r.frame_step(1)
    raise AssertionError("the fade never reached full brightness")


def enter_play(r):
    """START on a menu -> the play scene, settled and at full brightness."""
    press(r, start=True)
    r.frame_step(20)
    assert scene_now(r)[0] == SCENE_PLAY, "START did not reach the play scene"
    settle(r)


def wait_scene(r, want, max_frames=240):
    for _ in range(max_frames):
        if scene_now(r)[0] == want:
            r.frame_step(4)
            settle(r)                   # ...so a screenshot is the scene, not
            return True                 #   the fade's progress through it
        r.frame_step(1)
    return False


def wait_grace(r, max_frames=200):
    """Step past the spawn i-frames.

    A round starts with PLF_GRACE frames of invulnerability, and the hero
    BLINKS through them — which means its OAM slot is parked on half the
    frames. Any assertion about where the hero is on screen has to wait for
    that to end, or it reads a parked entry and calls it a position.
    """
    for _ in range(max_frames):
        if u16(r, DP["hurt"]) == 0:
            r.frame_step(1)
            return
        r.frame_step(1)
    raise AssertionError("the spawn grace never expired")


def clear_save(r):
    """Invalidate slot 0, so the next title entry is a virgin cart.

    Mesen persists SRAM to its home directory between loads, so a module that
    banks a run leaves the cart written for every later test. Zeroing the
    magic is the smallest thing that makes `sv_exists` answer 0 — the CRC gate
    is the save feature's own to prove, not this rail's.
    """
    r.write_bytes(MemoryType.SnesSaveRam, 0, bytes(64))


def hold(r, frames, **buttons):
    """Hold a button combination for N frames, one step each so the closed
    loop above can watch the machine while it happens."""
    for _ in range(frames):
        r.frame_step(1, **buttons)


def walk_to(r, target, max_frames=400, **extra):
    """Walk until the hero's world x reaches `target` (either direction).

    Returns the frames it took. Raises if the hero never gets there — which is
    the right failure: a silent give-up turns every later assertion into a
    test of the wrong game state.
    """
    for n in range(max_frames):
        if scene_now(r)[0] != SCENE_PLAY:
            return n                    # the round ended under us -- the sixth
                                        # coin lands mid-walk, and a walk that
                                        # kept pushing would spin on a frozen px
        px = u16(r, DP["px"])
        if abs(px - target) < WALK:
            return n
        direction = {"right": True} if px < target else {"left": True}
        r.frame_step(1, **direction, **extra)
    raise AssertionError(
        f"walk_to({target}) never arrived — stuck at {u16(r, DP['px'])}")


def jump_arc(r, launch_x, release_x=None, hold_frames=24, direction="right",
             max_frames=400):
    """Walk to `launch_x`, jump, and optionally stop pushing at `release_x`.

    `hold_frames` is how long A stays down — with a variable-height jump that
    IS the height control, not a timing hack. `release_x` is what makes a
    landing aimable: keep pushing until the hero is over the target, then let
    the arc fall straight down onto it. Returns when the hero is grounded.
    """
    walk_to(r, launch_x)
    push = {direction: True}
    for n in range(max_frames):
        if release_x is not None:
            px = u16(r, DP["px"])
            over = px >= release_x if direction == "right" else px <= release_x
            if over:
                push = {}
        r.frame_step(1, a=(n < hold_frames), **push)
        if n > 2 and u16(r, DP["grounded"]):
            return
        if scene_now(r)[0] != SCENE_PLAY:
            return
    raise AssertionError("jump_arc never landed")


def die_into_the_pit(r):
    """Walk right off the ground into the first pit (world cols 22-25).

    The cheapest deterministic way to spend a life: no ghost timing, no
    stomp window, just a hole in the floor that is in the level blob.
    """
    start = u16(r, DP["lives"])
    walk_to(r, 190)
    for _ in range(240):
        r.frame_step(1, right=True)
        if u16(r, DP["lives"]) != start or scene_now(r)[0] != SCENE_PLAY:
            r.frame_step(4)
            return
    raise AssertionError("the pit did not cost a life")


def fall_to_ground(r, direction="right", max_frames=200):
    """Walk off whatever the hero is standing on and land on the ground.

    Two phases, and the first is what makes it reliable: WAIT until the hero
    is actually airborne, then wait until it is grounded again. A single
    "walk until grounded" test is satisfied on its first frame by the surface
    the hero has not left yet, and walks the length of the level instead.
    """
    for _ in range(max_frames):
        r.frame_step(1, **{direction: True})
        if not u16(r, DP["grounded"]):
            break
    else:
        raise AssertionError("never left the ledge")
    for _ in range(max_frames):
        r.frame_step(1, **{direction: True})
        if u16(r, DP["grounded"]):
            return
        if scene_now(r)[0] != SCENE_PLAY:
            return
    raise AssertionError("fell without landing")


def avoid_walk_to(r, target, ghost="e2x", alive="e2alive", near=14,
                  max_frames=400):
    """walk_to, but jump when a patrol crowds the hero.

    A jump lifts the 8x8 box clear of the ghost's, so the patrol passes
    underneath and the walk continues — the hero moves 2 px/frame against the
    ghost's 1, so it always wins the race it is allowed to run.
    """
    for _ in range(max_frames):
        if scene_now(r)[0] != SCENE_PLAY:
            return
        px = u16(r, DP["px"])
        if abs(px - target) < WALK:
            return
        crowded = (u16(r, DP[alive])
                   and abs(px - u16(r, DP[ghost])) < near
                   and u16(r, DP["grounded"]))
        push = {"right": True} if px < target else {"left": True}
        r.frame_step(1, a=crowded, **push)
    raise AssertionError(f"avoid_walk_to({target}) never arrived")


def win_route(r):
    """Play the level to the WIN card: all six coins, no lives lost.

    The route is the level's own design read back out of it — the two ground
    coins, the two one-way platforms, the step platform that makes the seam
    ledge reachable, the seam coin above the world's page boundary at column
    32, and both pits. It is closed-loop throughout, so it is a statement
    about the ROM's physics rather than about the host's timing.
    """
    jump_arc(r, 76, release_x=100, hold_frames=24)      # coin (12,19), mid-arc
    jump_arc(r, 120, release_x=162, hold_frames=24)     # -> the step platform
    jump_arc(r, 172, release_x=232, hold_frames=24)     # -> the seam ledge
    avoid_walk_to(r, 248)                               # coin (31,15)
    for _ in range(240):                                # ...standing, so the
        if u16(r, DP["coins"]) >= 3:                    #   box centre is in
            break                                       #   the coin's row
        r.frame_step(1, a=_crowded(r))
    walk_to(r, 300)
    fall_to_ground(r)
    walk_to(r, 272)                                     # coin (34,23)
    jump_arc(r, 320, release_x=344, hold_frames=24)     # coin (43,19)
    jump_arc(r, 366, hold_frames=30)                    # over the second pit
    walk_to(r, 480)                                     # coin (60,23) -> WIN


def _crowded(r):
    return bool(u16(r, DP["e2alive"])
                and abs(u16(r, DP["px"]) - u16(r, DP["e2x"])) < 14
                and u16(r, DP["grounded"]))
