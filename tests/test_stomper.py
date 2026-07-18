"""Done-condition for the stomper template: stomp the patrollers.

Closed-loop bots (read OAM each frame, decide input — set_input is wall-clock)
drive the player onto the ground enemy from above and verify the full stomp
outcome on real outputs: enemy sprite culled + magenta pixels drop, the player
BOUNCES (y trace dips then rises), FOES VRAM digit ticks down. Side contact is
verified to knock back without killing. CLEAR text appears only when both die.
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam
OAM = MemoryType.SnesSpriteRam

SPAWN = (200, 200)
_MAGENTA = lambda p: p[0] > 150 and p[1] < 90 and p[2] > 150
_WHITE = lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200


def _tile(ch):
    return 0x3C00 | (160 + ord(ch) - 0x20)


def _slot(r, n):
    b = r.read_bytes(OAM, n * 4, 2)
    return b[0], b[1]


def _foes(r):
    return r.read_u16(WR, 0xE010)


def _hurts(r):
    return r.read_u16(WR, 0xE012)


def _magenta_count(r, path):
    r.take_screenshot(path)
    img = Image.open(path).convert("RGB")
    return sum(1 for p in img.getdata() if _MAGENTA(p))


def _mount_wall(r, max_frames=600):
    """Closed-loop: stand on top of the col-20 low wall (y=184, x 153..167).
    From the right: walk left until blocked at x=168, hop with a 6-frame
    left tap (lands on the wall top). From inside the beat: symmetric from
    the left face (blocked at 152, right tap)."""
    for _ in range(max_frames):
        x, y = _slot(r, 0)
        if y == 184 and 153 <= x <= 167:
            r.set_input(0)
            r.run_frames(2)
            return True
        if y == 200 and x > 168:
            r.set_input(0, left=True)
            r.run_frames(1)
        elif y == 200 and x == 168:         # blocked at the right face
            r.set_input(0, a=True, left=True)
            r.run_frames(6)
            r.set_input(0)
            for _ in range(40):             # coast to a landing
                r.run_frames(1)
                if _slot(r, 0)[1] in (184, 200):
                    break
        elif y == 200 and x < 152:          # overshot into the beat
            r.set_input(0, right=True)
            r.run_frames(1)
        elif y == 200 and x == 152:         # blocked at the left face
            r.set_input(0, a=True, right=True)
            r.run_frames(6)
            r.set_input(0)
            for _ in range(40):
                r.run_frames(1)
                if _slot(r, 0)[1] in (184, 200):
                    break
        else:
            r.set_input(0)
            r.run_frames(1)
    return False


def _enemy_x(r):
    return _slot(r, 1)[0]


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    rom = BUILD / "stomper.sfc"
    assert rom.exists(), f"{rom} not built — run `make stomper` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


def test_boots_with_two_foes(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    runner.run_frames(10)
    assert _foes(runner) == 2
    assert runner.read_u16(VR, 0xC000 + (1 * 32 + 10) * 2) == _tile('2'), \
        "FOES counter not 00002 at boot"
    assert _magenta_count(runner, "/tmp/_stomper0.png") > 40, \
        "two enemies not rendered"


def test_side_contact_knocks_back_without_killing(runner):
    # drop into the beat while the enemy is FAR, then just stand grounded —
    # the patroller walks into us laterally (vy=0 -> guaranteed HURT, a
    # standing player cannot stomp)
    r = runner
    hurts0 = _hurts(r)
    assert _mount_wall(r), "could not mount the low wall"
    while not (_enemy_x(r) < 110):          # wait until the beat is clear
        r.run_frames(1)
    r.set_input(0, left=True)               # walk off until actually falling
    for _ in range(20):
        r.run_frames(1)
        if _slot(r, 0)[1] > 184:
            break
    r.set_input(0)
    for _ in range(40):                     # land
        r.run_frames(1)
        if _slot(r, 0)[1] == 200:
            break
    assert _slot(r, 0)[1] == 200, f"did not land in the beat: {_slot(r, 0)}"
    for _ in range(300):                    # stand still; the enemy comes
        if _hurts(r) > hurts0:
            break
        r.run_frames(1)
    r.run_frames(3)
    assert _hurts(r) == hurts0 + 1, "side contact not registered"
    assert _foes(r) == 2, "side contact killed an enemy"
    x, y = _slot(r, 0)
    assert abs(x - SPAWN[0]) <= 8 and y == SPAWN[1], f"no knockback: {(x, y)}"


def test_stomp_kills_bounces_and_counts(runner):
    r = runner
    mag0 = _magenta_count(r, "/tmp/_stomper1.png")
    foes0 = _foes(r)
    stomped = False
    for _attempt in range(8):
        assert _mount_wall(r), "could not mount the low wall"
        # wait on the wall top for the enemy to approach the wall, then
        # step off onto its head (8px drop -> falling contact in depth)
        for _ in range(700):
            ex = _enemy_x(r)
            if 134 <= ex <= 146:
                break
            r.run_frames(1)
        r.set_input(0, left=True)
        r.run_frames(3)
        r.set_input(0)
        for _ in range(40):
            r.run_frames(1)
            if _foes(r) < foes0:
                stomped = True
                break
            if _slot(r, 0)[1] == 200 and _slot(r, 0)[0] > 168:
                break                       # got hurt instead — retry
            if _slot(r, 0)[1] == 200:
                break                       # missed — landed in the beat
        if stomped:
            break
    assert stomped, "never landed a stomp (8 attempts)"
    # bounce: right after the kill the player rises — the hop must climb
    # at least 10px above the kill point (audit-1 F1: a bare min<=ys[0]
    # is a tautology; the real bounce apex is ~17px up)
    ys = []
    for _ in range(20):
        r.run_frames(1)
        ys.append(_slot(r, 0)[1])
    assert min(ys) <= ys[0] - 10, f"no bounce after the stomp: {ys}"
    r.run_frames(30)
    assert _foes(r) == 1, "FOES mirror did not tick down"
    assert r.read_u16(VR, 0xC000 + (1 * 32 + 10) * 2) == _tile('1'), \
        "FOES text not reprinted"
    mag1 = _magenta_count(r, "/tmp/_stomper2.png")
    assert mag1 < mag0 - 15, f"enemy still rendered ({mag0} -> {mag1})"
    # the dead enemy's OAM slot is gone: slot 1 now holds the platform enemy
    # (y=152) or a culled entry — no sprite at ground level but the player
    others = [_slot(r, n) for n in (1, 2)]
    assert all(y != 200 or x == 0 for x, y in others), \
        f"a ground-level enemy sprite survived: {others}"


def test_clear_only_after_both(runner):
    # one foe left: CLEAR must not be on screen yet
    assert _foes(runner) == 1
    cells = [runner.read_u16(VR, 0xC000 + (13 * 32 + 13 + i) * 2)
             for i in range(5)]
    assert all(c == 0 for c in cells), "CLEAR printed with a foe alive"


def _hop(r, max_land=40, **direction):
    """Tap A + a direction for 6 frames, then coast to a landing."""
    r.set_input(0, a=True, **direction)
    r.run_frames(6)
    r.set_input(0)
    for _ in range(max_land):
        r.run_frames(1)
        if _slot(r, 0)[1] in (184, 200):
            break


def _mount_left_wall(r, max_frames=800):
    """Stand on the col-10 low wall top (y=184, x 73..87), journeying from
    anywhere on the ground (crosses the col-20 wall if needed; only safe
    once the ground enemy is dead)."""
    for _ in range(max_frames):
        x, y = _slot(r, 0)
        if y == 184 and 73 <= x <= 87:
            r.set_input(0)
            r.run_frames(2)
            return True
        if y == 184:                        # on the col-20 wall: drop left
            r.set_input(0, left=True)
            r.run_frames(1)
        elif y == 200 and x in (88, 168):   # blocked at a wall face -> hop
            _hop(r, left=True)
        elif y == 200 and x == 72:          # left of the wall, blocked
            _hop(r, right=True)
        elif y == 200 and x < 72:
            r.set_input(0, right=True)
            r.run_frames(1)
        elif y == 200:
            r.set_input(0, left=True)
            r.run_frames(1)
        else:
            r.set_input(0)
            r.run_frames(1)
    return False


def test_clear_appears_after_both(runner):
    # stomp the platform enemy (audit-1 F2 recipe: from the col-10 wall top,
    # jump straight up through the wall/platform gap when E2 turns at its
    # left bound, steer left only after the apex). E2 draws in slot 1 now
    # that E1 is dead.
    r = runner

    def e2x():
        for n in (1, 2):
            x, y = _slot(r, n)
            if y == 152:
                return x
        return None

    assert _foes(r) == 1
    stomped = False
    for _attempt in range(10):
        assert _mount_left_wall(r), "could not mount the left wall"
        prev = None
        for _ in range(400):                # wait for E2's left-bound TURN:
            ex = e2x()                      # moving right again, near 32
            if (ex is not None and prev is not None
                    and ex > prev and ex <= 36):
                break
            prev = ex
            r.run_frames(1)
        r.set_input(0, a=True)              # vertical jump through the gap
        r.run_frames(12)
        r.set_input(0, left=True)           # steer in after the apex
        outcome = None
        for _ in range(50):
            r.run_frames(1)
            if _foes(r) == 0:
                outcome = "stomp"
                break
            x, y = _slot(r, 0)
            if y == 200 and x > 160:        # hurt -> knocked back to spawn
                outcome = "hurt"
                break
            if y in (184, 200) and x <= 160:
                outcome = "landed"          # missed
                break
        r.set_input(0)
        if outcome == "stomp":
            stomped = True
            break
    assert stomped, "never stomped the platform enemy (10 attempts)"
    r.run_frames(10)
    assert r.read_u16(VR, 0xC000 + (1 * 32 + 10) * 2) == _tile('0'), \
        "FOES text not 00000"
    word = "".join(chr((runner.read_u16(VR, 0xC000 + (13 * 32 + 13 + i) * 2)
                        & 0xFF) - 160 + 0x20) if
                   runner.read_u16(VR, 0xC000 + (13 * 32 + 13 + i) * 2) else "."
                   for i in range(5))
    assert word == "CLEAR", f"win text reads {word!r}"
    runner.take_screenshot("/tmp/_stomper_clear.png")
    img = Image.open("/tmp/_stomper_clear.png").convert("RGB")
    assert sum(1 for p in img.getdata() if _MAGENTA(p)) == 0, \
        "an enemy is still rendered after CLEAR"
