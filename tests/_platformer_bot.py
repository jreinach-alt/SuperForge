"""Closed-loop navigation bot for the platformer flagship (shared by the
orchestrator playthrough and the test_platformer*.py modules), plus the
battery-SRAM (.srm) hygiene helpers every platformer test module uses to
start from its documented save-state baseline (v3 save/continue)."""
import time

from infrastructure.test_harness.mesen_runner import MemoryType

WR = MemoryType.SnesWorkRam
PX, PIXY, GROUNDED = 0x32, 0x5C, 0x3A
SCENE, LIVES, COINS, E2ALIVE = 0x1804, 0x1800, 0x1802, 0x180A
E2X, E2D = 0x46, 0x48

# .srm hygiene now lives in the shared, ROM-name-parameterized tests/_srm.py
# (promoted there after acceptance run #16 re-implemented these for a second
# SRAM game). These flagship-flavored wrappers keep the original module API.
from tests import _srm

SRM_PATH = _srm.srm_path("platformer")


def flush_srm(runner, neutral_rom):
    """Force the LIVE platformer SRAM out to platformer.srm (see _srm.py)."""
    _srm.flush_srm(runner, neutral_rom)


def virgin_srm(runner, neutral_rom):
    """Guarantee the NEXT platformer boot sees VIRGIN SRAM (see _srm.py for
    why the neutral-ROM-first ordering is load-bearing)."""
    _srm.virgin_srm(runner, "platformer", neutral_rom)

def st(r):
    return dict(sc=r.read_u16(WR, SCENE), lv=r.read_u16(WR, LIVES),
                co=r.read_u16(WR, COINS), px=r.read_u16(WR, PX),
                py=r.read_u16(WR, PIXY), g=r.read_u16(WR, GROUNDED),
                e2=r.read_u16(WR, E2ALIVE))

def walk_to(r, x, tmo=20):
    """Walk straight toward x on the current support (no pits in between)."""
    key = "right" if r.read_u16(WR, PX) < x else "left"
    r.set_input(0, **{key: True})
    t0 = time.time()
    while time.time() - t0 < tmo:
        px = r.read_u16(WR, PX)
        if (key == "right" and px >= x) or (key == "left" and px <= x):
            break
        r.run_frames(2)
    r.set_input(0)
    r.run_frames(3)

def settle(r, want_y, tmo=5):
    t0 = time.time()
    while time.time() - t0 < tmo:
        if r.read_u16(WR, GROUNDED) == 1 and r.read_u16(WR, PIXY) == want_y:
            return True
        r.run_frames(2)
    return False

def jump_in_place(r, hold=28):
    r.set_input(0, a=True)
    r.run_frames(hold)
    r.set_input(0)

def running_jump(r, key, hold_a, carry):
    """Tuned arc: direction+A for hold_a frames, direction-only for carry
    frames, release, settle. (Open-loop holds until landing overshoot — the
    arc must end with no input so the landing spot is deterministic.)"""
    r.set_input(0, **{key: True, "a": True})
    r.run_frames(hold_a)
    r.set_input(0, **{key: True})
    r.run_frames(carry)
    r.set_input(0)
    t0 = time.time()
    while time.time() - t0 < 4:
        if r.read_u16(WR, GROUNDED) == 1:
            break
        r.run_frames(2)
    r.run_frames(3)

def mount_platform(r, under_x, rest_y, tries=3):
    """Stand at under_x, full-jump THROUGH the one-way platform, settle."""
    for _ in range(tries):
        walk_to(r, under_x)
        jump_in_place(r)
        if settle(r, rest_y):
            return True
    return False

def stomp_ledge_ghost(r, tmo=30):
    """On the ledge with ghost2: hop when it comes near; falling contact = stomp."""
    t0 = time.time()
    while r.read_u16(WR, E2ALIVE) == 1 and time.time() - t0 < tmo:
        d = r.read_u16(WR, E2X) - r.read_u16(WR, PX)
        if abs(d) < 28:
            r.set_input(0, a=True)
            r.run_frames(8)        # short hop: come down fast onto its head
            r.set_input(0)
            r.run_frames(30)
        else:
            r.run_frames(4)
    return r.read_u16(WR, E2ALIVE) == 0

def win_route(r, log=print):
    """The full 6-coin route. Returns the final state dict."""
    log("start:", st(r))
    walk_to(r, 54);  log("coin A:", st(r))                      # ground col 7
    assert mount_platform(r, 96, 152), "plat1 mount failed"
    walk_to(r, 98);  log("coin B:", st(r))                      # plat1 col 12
    walk_to(r, 118)                                             # plat1 east edge
    running_jump(r, "right", 16, 6)                             # -> stone (tuned)
    assert st(r)["py"] == 136, f"stone missed: {st(r)}"
    log("stone:", st(r))
    walk_to(r, 166)
    # wait until ghost2 is far right and moving AWAY before landing at ~224
    t0 = time.time()
    while time.time() - t0 < 30:
        if r.read_u16(WR, E2X) >= 272 and r.read_u16(WR, E2D) == 1:
            break
        r.run_frames(4)
    running_jump(r, "right", 20, 8)                             # -> ledge (tuned)
    assert st(r)["py"] == 120, f"ledge missed: {st(r)}"
    log("ledge:", st(r))
    assert stomp_ledge_ghost(r), "ghost2 stomp failed"
    log("stomped:", st(r))
    walk_to(r, 250); log("coin C (seam):", st(r))               # ledge col 31
    walk_to(r, 300)
    r.set_input(0, right=True); r.run_frames(30); r.set_input(0)  # off east end
    # the drift lands on plat2 (rest 152), crossing coin F's column on the way
    assert settle(r, 152), f"ledge dismount onto plat2: {st(r)}"
    walk_to(r, 346); log("coin F:", st(r))                      # plat2 col 43
    walk_to(r, 332)                                             # plat2 west edge
    r.set_input(0, left=True); r.run_frames(16); r.set_input(0)  # step off west
    assert settle(r, 184), f"plat2 west dismount: {st(r)}"
    walk_to(r, 274); log("coin D:", st(r))                      # ground col 34
    walk_to(r, 356)                                             # pit2 west lip
    running_jump(r, "right", 26, 14)                            # over pit2
    assert settle(r, 184), f"pit2 crossing: {st(r)}"
    assert st(r)["px"] > 400, f"did not clear pit2: {st(r)}"
    walk_to(r, 478); log("coin E:", st(r))                      # ground col 60
    r.run_frames(10)
    return st(r)
