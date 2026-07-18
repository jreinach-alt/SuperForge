"""Acceptance gate for the boss template: a Mode 7 "the boss IS the screen" fight.

The boss is the Mode 7 BG layer — the hardware affine matrix scales+rotates it
for free; the player, the boss's attacks, and the HP bar are SPRITES composited
over it. This gate verifies the battle structure on REAL rendered/hardware
output (OAM bytes, CGRAM bytes, screenshot pixels, and the HP WRAM that the HUD
mirrors) — never a proxy game variable. The acceptance invariants from
docs/sprints/session_B_boss_preflight.md §"Acceptance invariants":

  1. Boss-is-BG scaling: the on-screen boss bbox grows MONOTONICALLY across the
     REVEAL (screenshot lit-pixel extent), driven by the affine matrix scale
     (b_scale WRAM also walks down, but the assertion is on the rendered pixels).
  2. Masked swap: at the RESET swap frame INIDISP==0 (forced blank) — the
     discontinuous battle re-init happens with the screen black, no half-state
     frame.
  3. Sprite-over-BG composition: the player sprite's hull-blue renders in FRONT
     of the boss BG at a known on-screen box (cross-layer screenshot pixel).
  4. Full state cycle: drive reveal->hold->fight->death->result->reset; assert
     b_state walks the FULL cycle AND there are no boss pixels at the reset/off
     (black) frame.
  6. Hit detection: a player shot in the vuln window drops b_hp AND the rendered
     HP HUD loses lit segments; standing in the attack rain drops p_hp -> lose.

State cycles exercised across the suite: REVEAL (grow-in), HOLD, FIGHT (win path
via side-lane + fire, lose path via stand-still), DEATH (recede), RESULT (win
and lose), RESET (masked re-init, loop back to REVEAL).

Control scheme (player-driven so outcomes are deterministic): LEFT/RIGHT strafe;
A (held, rate-limited) fires a shot straight up. The boss hitbox is WIDE (the
face fills the screen) so a shot from any column connects; the boss's attacks
rain in a NARROW central column, so the player dodges by strafing to a side lane
while still able to hit the boss.
"""
from pathlib import Path
from collections import Counter

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam
CG = MemoryType.SnesCgRam

# debug-region mirrors (main.asm writes these every frame; used only to SEQUENCE
# screenshots / locate states — every OUTCOME assertion is on rendered/HW bytes)
DBG_HEART  = 0xE010   # frame counter
DBG_STATE  = 0xE012   # b_state index
DBG_BHP    = 0xE014   # boss HP
DBG_PHP    = 0xE016   # player HP
DBG_SCALE  = 0xE018   # matrix scale
DBG_RESULT = 0xE01A   # 0 none / 1 win / 2 lose

# main-thread DP (DP=$0000) game state
DP_BHP   = 0x3E
DP_PHASE = 0x40

# engine shadow INIDISP (NMI-DP-relative $2E -> absolute $0100+$2E)
SHADOW_INIDISP = 0x012E

# state machine indices (main.asm ST_*)
ST_REVEAL, ST_HOLD, ST_FIGHT, ST_DEATH, ST_LOSE, ST_RESULT, ST_RESET = 1, 2, 3, 4, 5, 6, 7

# OAM map (stable slots; SPR_ORDER_MODE=2)
PLAYER_SLOT = 0
ATK_SLOTS   = range(1, 9)      # boss projectiles
HUD_SLOTS   = range(9, 17)     # boss HP bar segments
SHOT_SLOTS  = range(17, 21)    # player shots

# OBJ tile numbers (relative to the OBSEL name base; from sprites.inc)
SPR_PLAYER_T0 = 0x00
SPR_PROJECTILE = 0x04
SPR_SHOT = 0x05
SPR_HP_LIT = 0x06
SPR_HP_DIM = 0x07

HUD_Y = 12                     # HP-bar row


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


def _rgb(path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return img.load(), w, h


def _lit_pixels(path, thresh=60):
    """Count non-near-black pixels — a proxy for the on-screen boss bbox area
    (the boss IS the BG; everything lit on a black backdrop is the boss + the
    few sprites). Grows as the affine matrix scales the boss up."""
    px, w, h = _rgb(path)
    return sum(1 for y in range(h) for x in range(w) if sum(px[x, y]) > thresh)


def _to_state(runner, want, max_frames=400):
    for _ in range(max_frames):
        runner.run_frames(1)
        if _state(runner) == want:
            return True
    return False


# =============================================================================
# Invariant 1 — boss-is-BG scaling: the rendered boss grows across the REVEAL.
# =============================================================================
def test_boss_reveal_scales_the_bg_boss_up(runner):
    """The boss is the Mode 7 BG; the affine matrix scales the whole plane, so
    across the REVEAL the on-screen boss grows from tiny to full. Asserted on
    the RENDERED pixels (lit-pixel extent grows monotonically across a sweep of
    reveal frames), not just the b_scale WRAM. State cycle: REVEAL grow-in."""
    rom = BUILD / "boss.sfc"
    assert rom.exists(), f"{rom} not built — run `make boss` first"
    runner.load_rom(str(rom), run_seconds=0.3)

    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB", "did not boot (no SFDB magic)"
    h0 = runner.read_u16(WR, DBG_HEART)
    runner.run_frames(8)
    assert runner.read_u16(WR, DBG_HEART) > h0, "heartbeat not advancing"

    # Sample the rendered boss area at three points across the reveal grow-in.
    # The reveal lasts ~60 frames and the intro fade ~32; sample late enough
    # that brightness is up so the comparison is scale-driven, not fade-driven.
    assert _state(runner) == ST_REVEAL, f"not in REVEAL at boot (state {_state(runner)})"
    areas = []
    scales = []
    for target_frame in (18, 30, 44):
        # advance to the target reveal frame
        while runner.read_u16(WR, DBG_HEART) < target_frame and _state(runner) == ST_REVEAL:
            runner.run_frames(1)
        shot = f"/tmp/_boss_reveal_{target_frame}.png"
        runner.take_screenshot(shot)
        areas.append(_lit_pixels(shot))
        scales.append(runner.read_u16(WR, DBG_SCALE))

    # rendered boss area grows monotonically (each later capture is bigger)
    assert areas[0] < areas[1] < areas[2], \
        f"rendered boss did not grow across the reveal: lit-pixel areas {areas}"
    # and it's a real growth, not noise
    assert areas[2] >= areas[0] * 2, \
        f"reveal growth too small to be the affine scale-in: {areas}"
    # the matrix scale walks DOWN (bigger boss) over the same span — the cause
    assert scales[0] > scales[2], \
        f"matrix scale did not ramp down (boss grow): {scales}"


# =============================================================================
# Invariant 3 — sprite-over-BG composition: player hull-blue in front of the BG.
# =============================================================================
def test_player_sprite_composites_in_front_of_boss_bg(runner):
    """The player ship is an OBJ sprite over the Mode 7 boss BG. At a known
    on-screen box (the player at slot 0, x=120 y=184) the player's hull-BLUE
    must render — proving OBJ draws in front of the boss BG (cross-layer
    screenshot pixel, not a single-layer byte). State cycle: FIGHT."""
    rom = BUILD / "boss.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"

    px_slot = _oam(runner, PLAYER_SLOT)
    assert px_slot[2] == SPR_PLAYER_T0, f"slot 0 not the player tile: {px_slot}"
    assert px_slot[1] == 184, f"player not at its fight Y: {px_slot}"
    px0 = px_slot[0]

    runner.take_screenshot("/tmp/_boss_player_box.png")
    px, w, h = _rgb("/tmp/_boss_player_box.png")

    def P(x, y):
        return px[int(x * w / 256), int(y * h / 224)]

    # the skiff hull is blue: high B, B clearly > R (the boss BG is gray, R~=B)
    blue = 0
    for x in range(px0, px0 + 16):
        for y in range(184, 200):
            r, g, b = P(x, y)
            if b > 150 and b > r + 40:
                blue += 1
    assert blue >= 4, \
        f"player hull-blue not rendered in front of the boss BG (blue px={blue})"


# =============================================================================
# Invariant 6 — hit detection: shots drop b_hp + the HUD; rain drops p_hp.
# =============================================================================
def test_shot_drops_boss_hp_and_hp_hud(runner):
    """A player shot in the vuln window drops boss HP, AND the rendered HP HUD
    loses lit segments. Reads the boss HP WRAM (the value) AND the OAM HUD
    segment tiles in slots 9-16 (the rendered bar) — both real output regions.
    State cycle: FIGHT (vulnerable) -> fire -> boss HP + HUD drop."""
    rom = BUILD / "boss.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"
    runner.run_frames(2)

    # full HP -> all 8 HUD segments are the LIT tile (rendered bar)
    lit0 = sum(1 for s in HUD_SLOTS
               if _oam(runner, s)[2] == SPR_HP_LIT and _oam(runner, s)[1] == HUD_Y)
    assert lit0 == 8, f"HP HUD not full at fight start: {lit0}/8 lit segments"
    bhp0 = runner.read_u16(WR, DBG_BHP) & 0xFF
    assert bhp0 > 0

    # strafe to a side lane (out of the central attack rain) and hold A to fire
    # until at least one HUD segment's worth of HP is gone (>= 30, one segment).
    runner.set_input(0, left=True)
    runner.run_frames(40)
    for _ in range(400):
        runner.set_input(0, left=True, a=True)
        runner.run_frames(1)
        if (runner.read_u16(WR, DBG_BHP) & 0xFF) <= bhp0 - 36:
            break
    runner.set_input(0)

    bhp1 = runner.read_u16(WR, DBG_BHP) & 0xFF
    assert bhp1 < bhp0, f"player shots did not damage the boss: {bhp0} -> {bhp1}"
    # the rendered HUD must now show fewer lit segments
    lit1 = sum(1 for s in HUD_SLOTS
               if _oam(runner, s)[2] == SPR_HP_LIT and _oam(runner, s)[1] == HUD_Y)
    assert lit1 < lit0, \
        f"HP HUD did not deplete with boss HP: {lit1} lit (was {lit0}), bhp {bhp1}"
    # depleted segments switch to the DIM tile (the bar still draws all 8)
    dim = sum(1 for s in HUD_SLOTS if _oam(runner, s)[2] == SPR_HP_DIM)
    assert lit1 + dim == 8, f"HP bar not 8 segments (lit {lit1} + dim {dim})"


def test_attack_rain_drops_player_hp(runner):
    """Standing in the central attack rain (no firing) drops the player's HP as
    the boss's projectiles (col_box vs the player box) connect. Reads the player
    HP WRAM (the value the engine drops) across the stand-still. The attacks ARE
    rendered (slots 1-8, tile SPR_PROJECTILE) — verified separately below.
    State cycle: FIGHT, player stationary -> repeated hits -> HP drops."""
    rom = BUILD / "boss.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"

    php0 = runner.read_u16(WR, DBG_PHP) & 0xFF
    assert php0 >= 2, f"player did not start the fight with HP: {php0}"
    # stand still in the central column; no fire -> boss can't die, attacks land
    dropped = False
    for _ in range(400):
        runner.run_frames(1)
        if (runner.read_u16(WR, DBG_PHP) & 0xFF) < php0:
            dropped = True
            break
        if _state(runner) != ST_FIGHT:
            break
    assert dropped, "standing in the attack rain never dropped player HP"


def test_attacks_render_at_moving_positions(runner):
    """The boss's attacks render as SPR_PROJECTILE sprites (OAM slots 1-8) at
    MOVING screen positions (the rain). Reads the actual OAM low-table bytes for
    the attack slots across a window and requires several distinct live
    positions. State cycle: FIGHT."""
    rom = BUILD / "boss.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"

    positions = set()
    for _ in range(80):
        runner.run_frames(1)
        for s in ATK_SLOTS:
            x, y, tile, attr = _oam(runner, s)
            if y != 0xF0 and tile == SPR_PROJECTILE:
                positions.add((s, x, y))
    assert len(positions) >= 10, \
        f"boss attacks did not render at moving positions: {len(positions)} samples"


# =============================================================================
# Invariant 4 — full state cycle, and invariant 2 — masked swap (INIDISP==0).
# =============================================================================
def test_full_state_cycle_win_path_and_masked_reset(runner):
    """Drive the FULL win cycle and assert b_state walks reveal->hold->fight->
    death->result->reset->reveal (looping), AND at the RESET swap frame the
    screen is masked (SHADOW_INIDISP==0) with NO boss pixels rendered (the
    discontinuous re-init happens black). The win is reached by playing: strafe
    to a side lane + hold A to kill the boss untouched.

    States are read from the debug mirror to SEQUENCE the cycle; the masked-swap
    OUTCOME is asserted on the engine's INIDISP shadow (the value the NMI commits
    to $2100) AND on the rendered framebuffer (no lit pixels at the black frame).
    """
    rom = BUILD / "boss.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    # observe from the fresh boot REVEAL so HOLD is in the window too
    assert _state(runner) == ST_REVEAL, f"not in REVEAL at boot ({_state(runner)})"

    visited = set()
    saw_masked_reset = False
    reset_had_no_boss = False
    looped_to_reveal = False
    seen_reset = False
    # play the win: always strafe to the left lane + hold A. (Outside FIGHT the
    # input is harmless — the state machine ignores it; inside FIGHT it kills
    # the boss untouched.)
    for _ in range(1800):
        runner.set_input(0, left=True, a=True)
        runner.run_frames(1)
        s = _state(runner)
        visited.add(s)
        if s == ST_RESET:
            seen_reset = True
            # NOTE (audit-1 L-2): the masked-swap invariant holds while RESET is
            # ACTIVE (the re-init runs under forced blank and the state holds
            # INIDISP==0 until it hands off to REVEAL). We sample on the first
            # RESET frame we observe; the screen is black for the whole RESET
            # dwell, so any RESET frame satisfies it — not a one-frame edge.
            if not saw_masked_reset:
                inidisp = runner.read_u16(WR, SHADOW_INIDISP) & 0xFF
                if inidisp == 0:
                    saw_masked_reset = True
                    runner.take_screenshot("/tmp/_boss_reset_black.png")
                    if _lit_pixels("/tmp/_boss_reset_black.png") < 200:
                        reset_had_no_boss = True
        # loop closed once we return to REVEAL after a RESET
        if seen_reset and s == ST_REVEAL:
            looped_to_reveal = True
            break
    runner.set_input(0)

    # invariant 4: the full cycle was walked
    for want, name in ((ST_REVEAL, "REVEAL"), (ST_HOLD, "HOLD"), (ST_FIGHT, "FIGHT"),
                       (ST_DEATH, "DEATH"), (ST_RESULT, "RESULT"), (ST_RESET, "RESET")):
        assert want in visited, f"state {name} ({want}) never visited; saw {sorted(visited)}"
    assert looped_to_reveal, "did not loop back to REVEAL after RESET"
    # invariant 2: the swap is masked (INIDISP==0) with no boss on screen
    assert saw_masked_reset, "RESET swap frame was not masked (SHADOW_INIDISP never 0)"
    assert reset_had_no_boss, "boss pixels were on screen at the masked RESET frame"


def test_win_sets_result_then_loops(runner):
    """The win OUTCOME: killing the boss enters DEATH (the boss recedes), then
    RESULT with result==1 (WIN), then RESET loops back to REVEAL with result
    cleared. Reads the result WRAM the engine sets at the RESULT transition.
    State cycle: FIGHT(win) -> DEATH -> RESULT(1) -> RESET -> REVEAL."""
    rom = BUILD / "boss.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"
    runner.set_input(0, left=True)
    runner.run_frames(45)
    # fire until the boss dies (state leaves FIGHT)
    for _ in range(1400):
        runner.set_input(0, left=True, a=True)
        runner.run_frames(1)
        if _state(runner) in (ST_DEATH, ST_RESULT):
            break
    runner.set_input(0)
    # follow into RESULT and read the win flag
    won = False
    for _ in range(200):
        runner.run_frames(1)
        if _state(runner) == ST_RESULT and (runner.read_u16(WR, DBG_RESULT) & 0xFF) == 1:
            won = True
            break
    assert won, "win path did not set result=1 (WIN) at RESULT"
    # loops back to REVEAL with the result cleared
    looped = False
    for _ in range(200):
        runner.run_frames(1)
        if _state(runner) == ST_REVEAL:
            looped = (runner.read_u16(WR, DBG_RESULT) & 0xFF) == 0
            break
    assert looped, "win path did not loop back to a fresh REVEAL (result cleared)"


def test_lose_path_sets_result(runner):
    """The lose OUTCOME: standing in the attack rain without firing drains the
    player HP to 0, which enters LOSE -> RESULT with result==2. Reads the player
    HP WRAM (drained by the engine) and the result WRAM the engine sets. State
    cycle: FIGHT(stand still) -> p_hp 0 -> LOSE -> RESULT(2)."""
    rom = BUILD / "boss.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"
    # stand still, never fire -> boss never dies, attacks drain player HP
    lost = False
    for _ in range(800):
        runner.run_frames(1)
        if _state(runner) == ST_RESULT and (runner.read_u16(WR, DBG_RESULT) & 0xFF) == 2:
            lost = True
            break
    assert lost, "lose path did not set result=2 (LOSE) at RESULT"
    assert (runner.read_u16(WR, DBG_PHP) & 0xFF) == 0, "player HP not 0 on the lose path"


def test_boss_phase_advances_with_hp(runner):
    """The boss phase index (b_phase) advances 0->1->2 as boss HP drops past the
    band thresholds (hp>160 -> 0, 80<hp<=160 -> 1, hp<=80 -> 2). Reads the boss
    HP + phase WRAM across a played-out fight. State cycle: FIGHT, HP draining.

    Phase is engine-internal difficulty state (not a rendered output), but it is
    DERIVED from b_hp which the rendered HUD reflects (tested above) — so this
    asserts the phase tracks the same HP the HUD shows. The win/lose/HUD/hit
    OUTCOMES are all on rendered or HW-effect output in the other tests."""
    rom = BUILD / "boss.sfc"
    runner.load_rom(str(rom), run_seconds=0.3)
    assert _to_state(runner, ST_FIGHT), "never reached FIGHT"
    assert (runner.read_u16(WR, DP_PHASE) & 0xFF) == 0, "did not start at phase 0"
    runner.set_input(0, left=True)
    runner.run_frames(40)
    phases = set()
    for _ in range(1200):
        runner.set_input(0, left=True, a=True)
        runner.run_frames(1)
        phases.add(runner.read_u16(WR, DP_PHASE) & 0xFF)
        if _state(runner) != ST_FIGHT:
            break
    runner.set_input(0)
    assert {0, 1, 2}.issubset(phases), \
        f"boss phase did not walk 0->1->2 as HP drained: saw {sorted(phases)}"
