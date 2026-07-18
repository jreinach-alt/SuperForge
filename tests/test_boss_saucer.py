"""Acceptance gate for the boss_saucer template: a Mode 7 SCALING boss fight.

The saucer is the Mode 7 BG layer — the hardware affine matrix scales it for
free. Its SIGNATURE is SCALING: it LUNGES toward the camera (the matrix zooms it
from a far speck to a screen-filling disc) and fires a vertical BEAM at the lunge
apex. The player, the beam, the player's shots, and the HP bar are SPRITES
composited over it. This gate verifies the battle on REAL rendered/hardware
output (screenshot lit-pixel area, OAM bytes, HP WRAM) — never a proxy game
variable.

The HEADLINE invariant is the LUNGE scaling: during the fight the on-screen
saucer SIZE oscillates as the affine matrix ramps scale down (approach, grows)
and back up (retreat). The near-apex frame is substantially LARGER than the
far-apex frame — asserted on the rendered lit-pixel area, the same screenshot
proxy the boss template uses for its reveal scaling.

OAM slot map (stable; SPR_ORDER_MODE=2):
    0       player gunship
    1-16    beam column segments (SPR_BEAM = 8)
    17-24   saucer HP HUD pips (SPR_HP_LIT / SPR_HP_DIM)
    25-28   player shots (SPR_SHOT)

Control scheme (player-driven so outcomes are deterministic): LEFT/RIGHT strafe;
A (held, rate-limited) fires a shot straight up. The saucer hitbox is WIDE (the
disc fills the screen) so a shot from any column connects; the BEAM is a NARROW
locked column, so the player dodges by strafing out of the column during the
telegraph.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam

# debug-region mirrors (main.asm writes these every frame; used only to SEQUENCE
# screenshots / locate states — every OUTCOME assertion is on rendered/HW bytes)
DBG_HEART  = 0xE010   # frame counter
DBG_STATE  = 0xE012   # b_state index
DBG_BHP    = 0xE014   # saucer HP
DBG_PHP    = 0xE016   # player HP
DBG_SCALE  = 0xE018   # matrix scale (the LUNGE drives this)
DBG_RESULT = 0xE01A   # 0 none / 1 win / 2 lose
DBG_BEAM   = 0xE01C   # beam sub-state (0 off / 1 telegraph / 2 active)
DBG_LUNGE  = 0xE01E   # lunge sub-state (0 far / 1 appr / 2 near / 3 retreat)

# engine shadow INIDISP (NMI-DP-relative $2E -> absolute $0100+$2E)
SHADOW_INIDISP = 0x012E

# state machine indices (main.asm ST_*)
ST_REVEAL, ST_HOLD, ST_FIGHT, ST_DEATH, ST_LOSE, ST_RESULT, ST_RESET = 1, 2, 3, 4, 5, 6, 7

# beam sub-states (main.asm BEAM_*)
BEAM_OFF, BEAM_TELE, BEAM_FIRE = 0, 1, 2

# OAM map (stable slots; SPR_ORDER_MODE=2)
PLAYER_SLOT = 0
BEAM_SLOTS  = range(1, 17)      # beam column segments
HUD_SLOTS   = range(17, 25)     # saucer HP bar segments
SHOT_SLOTS  = range(25, 29)     # player shots

# OBJ tile numbers (relative to the OBSEL name base; from sprites.inc)
SPR_PLAYER_T0 = 0x00
SPR_SHOT = 0x05
SPR_HP_LIT = 0x06
SPR_HP_DIM = 0x07
SPR_BEAM = 0x08

HUD_Y = 12                      # HP-bar row

# scale landmarks (main.asm): INIT_SCALE (rest/far) vs LUNGE_NEAR_SCALE (near)
INIT_SCALE = 0x0180
LUNGE_NEAR_SCALE = 0x00A0


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _oam(runner, slot):
    b = runner.read_bytes(OAM, slot * 4, 4)
    return b[0], b[1], b[2], b[3]   # x, y, tile, attr


def _state(runner):
    return runner.read_u16(WR, DBG_STATE) & 0xFF


def _beam(runner):
    return runner.read_u16(WR, DBG_BEAM) & 0xFF


def _rgb(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return img.load(), w, h


def _lit_pixels(path, thresh=60):
    """Count non-near-black pixels — a proxy for the on-screen saucer bbox area
    (the saucer IS the BG; everything lit on the dark sky is the saucer + the
    few sprites). Grows as the affine matrix scales the saucer up."""
    px, w, h = _rgb(path)
    return sum(1 for y in range(h) for x in range(w) if sum(px[x, y]) > thresh)


def _to_state(runner, want, max_frames=400):
    for _ in range(max_frames):
        runner.run_frames(1)
        if _state(runner) == want:
            return True
    return False


# =============================================================================
# (a) reveal scaling — the saucer grows as it descends (boss-is-BG scaling).
# =============================================================================
def test_reveal_scales_the_bg_saucer_up(runner):
    """The saucer is the Mode 7 BG; the affine matrix scales the whole plane, so
    across the REVEAL the on-screen saucer grows from a tiny speck to full.
    Asserted on the RENDERED pixels (lit-pixel extent grows monotonically across
    a sweep of reveal frames), not just the b_scale WRAM. State cycle: REVEAL.

    TEST SURFACE: feature = reveal affine scale-in; output region = the rendered
    framebuffer (lit-pixel area, screenshot bytes); state cycle = REVEAL
    grow-in. Cross-checked against the DBG_SCALE matrix value (the cause)."""
    rom = BUILD / "boss_saucer.sfc"
    assert rom.exists(), f"{rom} not built — run `make boss_saucer` first"
    runner.load_rom(str(rom), run_seconds=0.3)

    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot (no SFDB magic)"
    h0 = runner.read_u16(WR, DBG_HEART)
    runner.run_frames(8)
    assert runner.read_u16(WR, DBG_HEART) > h0, "heartbeat not advancing"

    assert _state(runner) == ST_REVEAL, f"not in REVEAL at boot (state {_state(runner)})"
    areas = []
    scales = []
    # threshold 120 excludes the dim night-sky backdrop (CGRAM idx 0 ~= a dark
    # blue) + star field so the lit-pixel count isolates the SAUCER disc, not a
    # constant sky floor; sample across a wide reveal span so the scale ramp
    # (REVEAL_SCALE $0500 -> INIT_SCALE $0180) covers a big range.
    for target_frame in (14, 32, 52):
        while runner.read_u16(WR, DBG_HEART) < target_frame and _state(runner) == ST_REVEAL:
            runner.run_frames(1)
        shot = f"/tmp/_saucer_reveal_{target_frame}.png"
        runner.take_screenshot(shot)
        areas.append(_lit_pixels(shot, thresh=120))
        scales.append(runner.read_u16(WR, DBG_SCALE))

    assert areas[0] < areas[1] < areas[2], \
        f"rendered saucer did not grow across the reveal: lit-pixel areas {areas}"
    assert areas[2] >= areas[0] * 1.5, \
        f"reveal growth too small to be the affine scale-in: {areas}"
    assert scales[0] > scales[2], \
        f"matrix scale did not ramp down (saucer grow): {scales}"


# =============================================================================
# (b) LUNGE scaling — THE HEADLINE: the saucer's on-screen size oscillates as it
#     lunges toward / retreats from the camera during the fight.
# =============================================================================
def test_lunge_oscillates_saucer_size_near_vs_far(runner):
    """THE HEADLINE TEST. During the FIGHT the saucer LUNGES: the affine matrix
    ramps scale DOWN (approach, the saucer grows to fill the screen) then back UP
    (retreat). Capture the rendered framebuffer at a FAR apex (scale near
    INIT_SCALE) and at a NEAR apex (scale near LUNGE_NEAR_SCALE) and assert the
    NEAR frame's lit-pixel area is SUBSTANTIALLY LARGER — the scaling axis, on
    rendered pixels. Also assert the lunge sub-state walks the full FAR->APPROACH
    ->NEAR->RETREAT cycle. State cycle: FIGHT lunge (all 4 sub-states).

    TEST SURFACE: feature = the lunge scale oscillation; output region = the
    rendered framebuffer (lit-pixel area at near vs far apex) + the DBG_SCALE
    matrix value; state cycle = the full lunge sub-state cycle."""
    rom = BUILD / "boss_saucer.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"

    far_area = None
    near_area = None
    far_scale = None
    near_scale = None
    lunge_states = set()
    # iterate a full window long enough for at least one complete lunge cycle
    # (FAR dwell 40 + approach 40 + telegraph 24 + active 30 + retreat 40 ~ 174f);
    # collect every lunge sub-state AND capture the far/near apex frames. Do NOT
    # break early on the captures — keep going so the full sub-state cycle is
    # observed (state-cycle coverage, not a single transition).
    for _ in range(360):
        runner.run_frames(1)
        if _state(runner) != ST_FIGHT:
            break
        lunge_states.add(runner.read_u16(WR, DBG_LUNGE) & 0xFF)
        s = runner.read_u16(WR, DBG_SCALE)
        # FAR apex: scale at/above rest (the small, far saucer)
        if s >= INIT_SCALE - 0x08 and far_area is None:
            runner.take_screenshot("/tmp/_saucer_far.png")
            far_area = _lit_pixels("/tmp/_saucer_far.png")
            far_scale = s
        # NEAR apex: scale at/below the lunge near value (the huge saucer)
        if s <= LUNGE_NEAR_SCALE + 0x08 and near_area is None:
            runner.take_screenshot("/tmp/_saucer_near.png")
            near_area = _lit_pixels("/tmp/_saucer_near.png")
            near_scale = s

    assert far_area is not None, "never captured a FAR apex frame in the lunge"
    assert near_area is not None, "never captured a NEAR apex frame in the lunge"
    # the matrix scale really swung between the two landmarks (the cause)
    assert far_scale > near_scale, \
        f"lunge scale did not swing (far {far_scale:#x} <= near {near_scale:#x})"
    # THE assertion: the near-apex rendered saucer is substantially bigger
    assert near_area >= far_area * 1.5, \
        f"lunge did not visibly grow the saucer: far {far_area} -> near {near_area} px"
    # the full lunge cycle was walked
    assert {0, 1, 2, 3}.issubset(lunge_states), \
        f"lunge sub-state did not walk far->approach->near->retreat: {sorted(lunge_states)}"


# =============================================================================
# (c) beam fires + damages — the beam renders in OAM 1-16 and drops p_hp while
#     the player stands in the locked column during the ACTIVE window.
# =============================================================================
def test_beam_renders_in_oam_and_damages_player_in_column(runner):
    """The saucer's BEAM is a vertical column of SPR_BEAM (tile 8) segments in
    OAM slots 1-16, fired at the lunge apex down a column LOCKED to the player's
    X. A player standing in the locked column during the ACTIVE window takes
    damage (p_hp drops). Reads the OAM beam-segment bytes (the rendered beam) AND
    the player HP WRAM (the value the engine drops) — both real output regions.
    State cycle: FIGHT -> lunge near -> beam telegraph -> beam ACTIVE -> hit.

    The player stands still (no strafe), so when the beam locks to the player's
    column and goes active, the col_box overlap fires. TEST SURFACE: feature =
    the beam attack (render + damage); output regions = OAM slots 1-16 (beam
    tiles) + player HP WRAM; state cycle = beam OFF->TELEGRAPH->ACTIVE."""
    rom = BUILD / "boss_saucer.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"

    php0 = runner.read_u16(WR, DBG_PHP) & 0xFF
    assert php0 >= 2, f"player did not start the fight with HP: {php0}"

    saw_beam_oam = False
    saw_telegraph = False
    saw_active = False
    damaged = False
    # stand still in the central column; do not strafe out (so the locked beam
    # column overlaps the player and the active window damages).
    for _ in range(600):
        runner.run_frames(1)
        if _state(runner) != ST_FIGHT:
            break
        bs = _beam(runner)
        if bs == BEAM_TELE:
            saw_telegraph = True
        if bs == BEAM_FIRE:
            saw_active = True
            # the beam must be RENDERED: SPR_BEAM tiles live in slots 1-16
            live = [s for s in BEAM_SLOTS
                    if _oam(runner, s)[2] == SPR_BEAM and _oam(runner, s)[1] != 0xF0]
            if len(live) >= 8:
                saw_beam_oam = True
        if (runner.read_u16(WR, DBG_PHP) & 0xFF) < php0:
            damaged = True
            break

    assert saw_telegraph, "beam never entered the telegraph window"
    assert saw_active, "beam never went active"
    assert saw_beam_oam, "beam segments never rendered in OAM slots 1-16 (tile 8)"
    assert damaged, "standing in the locked beam column never dropped player HP"


def test_beam_segments_stack_at_locked_column(runner):
    """When the beam is ACTIVE the 16 segments render as a CONTIGUOUS vertical
    column at a single locked X (a continuous descending beam), with 8px Y pitch.
    Reads the actual OAM low-table bytes for the beam slots. State cycle: FIGHT,
    beam ACTIVE.

    TEST SURFACE: feature = the stacked-column beam render; output region = OAM
    slots 1-16 (x, y bytes); state cycle = beam ACTIVE."""
    rom = BUILD / "boss_saucer.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"

    found = False
    for _ in range(600):
        runner.run_frames(1)
        if _state(runner) != ST_FIGHT:
            break
        if _beam(runner) == BEAM_FIRE:
            runner.run_frames(2)            # let the OAM DMA catch up to the draw
            rows = [_oam(runner, s) for s in BEAM_SLOTS]
            live = [(x, y) for (x, y, t, a) in rows if t == SPR_BEAM and y != 0xF0]
            if len(live) >= 16:
                xs = {x for (x, y) in live}
                ys = sorted(y for (x, y) in live)
                # all segments share one column X
                assert len(xs) == 1, f"beam segments not a single column: xs={xs}"
                # contiguous 8px stack from the emitter down
                pitches = {ys[i + 1] - ys[i] for i in range(len(ys) - 1)}
                assert pitches == {8}, f"beam not a contiguous 8px stack: ys={ys}"
                found = True
                break
    assert found, "never observed a full 16-segment beam column while active"


# =============================================================================
# (d) shot drops boss HP — and the rendered HP HUD loses lit segments.
# =============================================================================
def test_shot_drops_saucer_hp_and_hp_hud(runner):
    """A player shot in the vuln window drops saucer HP, AND the rendered HP HUD
    loses lit segments. Reads the saucer HP WRAM (the value) AND the OAM HUD
    segment tiles in slots 17-24 (the rendered bar). State cycle: FIGHT
    (vulnerable) -> fire -> saucer HP + HUD drop.

    TEST SURFACE: feature = shot-vs-saucer hit; output regions = saucer HP WRAM
    + OAM slots 17-24 (HUD pip tiles); state cycle = FIGHT vulnerable."""
    rom = BUILD / "boss_saucer.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"
    runner.run_frames(2)

    lit0 = sum(1 for s in HUD_SLOTS
               if _oam(runner, s)[2] == SPR_HP_LIT and _oam(runner, s)[1] == HUD_Y)
    assert lit0 == 8, f"HP HUD not full at fight start: {lit0}/8 lit segments"
    bhp0 = runner.read_u16(WR, DBG_BHP) & 0xFF
    assert bhp0 > 0

    # hold A to fire until at least one HUD segment's worth of HP is gone (>=36).
    for _ in range(500):
        runner.set_input(0, a=True)
        runner.run_frames(1)
        if (runner.read_u16(WR, DBG_BHP) & 0xFF) <= bhp0 - 36:
            break
        if _state(runner) != ST_FIGHT:
            break
    runner.set_input(0)

    bhp1 = runner.read_u16(WR, DBG_BHP) & 0xFF
    assert bhp1 < bhp0, f"player shots did not damage the saucer: {bhp0} -> {bhp1}"
    lit1 = sum(1 for s in HUD_SLOTS
               if _oam(runner, s)[2] == SPR_HP_LIT and _oam(runner, s)[1] == HUD_Y)
    assert lit1 < lit0, \
        f"HP HUD did not deplete with saucer HP: {lit1} lit (was {lit0}), bhp {bhp1}"
    dim = sum(1 for s in HUD_SLOTS if _oam(runner, s)[2] == SPR_HP_DIM)
    assert lit1 + dim == 8, f"HP bar not 8 segments (lit {lit1} + dim {dim})"


# =============================================================================
# (e) sprite-over-BG composition — player hull-blue in front of the saucer BG.
# =============================================================================
def test_player_sprite_composites_in_front_of_saucer_bg(runner):
    """The player ship is an OBJ sprite over the Mode 7 saucer BG. At a known
    on-screen box (the player at slot 0, y=184) the player's hull-BLUE must
    render — proving OBJ draws in front of the saucer BG (cross-layer screenshot
    pixel, not a single-layer byte). State cycle: FIGHT.

    TEST SURFACE: feature = OBJ-over-Mode7 layer composition; output region = the
    rendered framebuffer (screenshot pixels at the player box) + OAM slot 0
    (identity); state cycle = FIGHT."""
    rom = BUILD / "boss_saucer.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"

    # strafe to a side lane (out of any locked beam column) so the player box is
    # clear of the white-hot beam pixels for the hull-color read.
    runner.set_input(0, left=True)
    runner.run_frames(40)
    runner.set_input(0)

    px_slot = _oam(runner, PLAYER_SLOT)
    assert px_slot[2] == SPR_PLAYER_T0, f"slot 0 not the player tile: {px_slot}"
    assert px_slot[1] == 184, f"player not at its fight Y: {px_slot}"
    px0 = px_slot[0]

    runner.take_screenshot("/tmp/_saucer_player_box.png")
    px, w, h = _rgb("/tmp/_saucer_player_box.png")

    def P(x, y):
        return px[int(x * w / 256), int(y * h / 224)]

    blue = 0
    for x in range(px0, px0 + 16):
        for y in range(184, 200):
            r, g, b = P(x, y)
            if b > 150 and b > r + 40:
                blue += 1
    assert blue >= 4, \
        f"player hull-blue not rendered in front of the saucer BG (blue px={blue})"


# =============================================================================
# (f) full state cycle + masked reset — drive the win cycle, assert it loops and
#     the RESET swap is masked (INIDISP==0) with no saucer on screen.
# =============================================================================
def test_full_state_cycle_win_path_and_masked_reset(runner):
    """Drive the FULL win cycle and assert b_state walks reveal->hold->fight->
    death->result->reset->reveal (looping), AND at the RESET swap frame the
    screen is masked (SHADOW_INIDISP==0) with NO saucer pixels rendered (the
    discontinuous re-init happens black). The win is reached by playing: hold A
    to kill the saucer (dodge the beam by strafing).

    States are read from the debug mirror to SEQUENCE the cycle; the masked-swap
    OUTCOME is asserted on the engine's INIDISP shadow (the value the NMI commits
    to $2100) AND on the rendered framebuffer (no lit pixels at the black frame).

    TEST SURFACE: feature = full battle lifecycle + masked reset; output regions
    = b_state mirror (sequencing), SHADOW_INIDISP (the masked-swap value the NMI
    commits), and the rendered framebuffer (black at reset); state cycle = the
    full REVEAL->...->RESET->REVEAL loop."""
    rom = BUILD / "boss_saucer.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _state(runner) == ST_REVEAL, f"not in REVEAL at boot ({_state(runner)})"

    visited = set()
    saw_masked_reset = False
    reset_had_no_saucer = False
    looped_to_reveal = False
    seen_reset = False
    # play the win: strafe to a side lane (dodge the beam) + hold A to kill it.
    for _ in range(2400):
        runner.set_input(0, left=True, a=True)
        runner.run_frames(1)
        s = _state(runner)
        visited.add(s)
        if s == ST_RESET:
            seen_reset = True
            if not saw_masked_reset:
                inidisp = runner.read_u16(WR, SHADOW_INIDISP) & 0xFF
                if inidisp == 0:
                    saw_masked_reset = True
                    runner.take_screenshot("/tmp/_saucer_reset_black.png")
                    if _lit_pixels("/tmp/_saucer_reset_black.png") < 200:
                        reset_had_no_saucer = True
        if seen_reset and s == ST_REVEAL:
            looped_to_reveal = True
            break
    runner.set_input(0)

    for want, name in ((ST_REVEAL, "REVEAL"), (ST_HOLD, "HOLD"), (ST_FIGHT, "FIGHT"),
                       (ST_DEATH, "DEATH"), (ST_RESULT, "RESULT"), (ST_RESET, "RESET")):
        assert want in visited, f"state {name} ({want}) never visited; saw {sorted(visited)}"
    assert looped_to_reveal, "did not loop back to REVEAL after RESET"
    assert saw_masked_reset, "RESET swap frame was not masked (SHADOW_INIDISP never 0)"
    assert reset_had_no_saucer, "saucer pixels were on screen at the masked RESET frame"


def test_lose_path_sets_result(runner):
    """The lose OUTCOME: standing in the locked beam column without dodging
    drains player HP to 0, entering LOSE -> RESULT with result==2. Reads the
    player HP WRAM (drained by the beam) and the result WRAM the engine sets.
    State cycle: FIGHT (stand still in column) -> p_hp 0 -> LOSE -> RESULT(2).

    TEST SURFACE: feature = the lose outcome; output regions = player HP WRAM +
    result WRAM; state cycle = FIGHT(stand still)->LOSE->RESULT(2)."""
    rom = BUILD / "boss_saucer.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"
    # stand still in the central column, never fire -> the locked beam drains HP
    lost = False
    for _ in range(1600):
        runner.run_frames(1)
        if _state(runner) == ST_RESULT and (runner.read_u16(WR, DBG_RESULT) & 0xFF) == 2:
            lost = True
            break
    assert lost, "lose path did not set result=2 (LOSE) at RESULT"
    assert (runner.read_u16(WR, DBG_PHP) & 0xFF) == 0, "player HP not 0 on the lose path"
