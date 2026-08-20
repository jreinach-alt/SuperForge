"""Render the railshooter rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_railshooter.py [outdir]

Boots build/railshooter.sfc and photographs the six instants asks a
pilot to be able to read without being told:

    rail        the settled rail, mid-bend — the S-curve carrying the ship
    pylon       the obstacle the curve bends around, at close range
    drag        the reticle dragged well off centre by the swing, hands off
    kill        the frame after a hit: the flash over the wreck, score moved
    hurt        the life bar part-spent
    fail        zero lives: an empty rail, an empty bar, the ship blinking

No assertions — this exists so a human (or the maintainer) can LOOK at the
ROM the suite just called green.

Every capture lands on an absolute frame (`boot_to_frame` + `frame_step`), so
two runs of this tool photograph the same instants and a visual diff between
them means something.

THE KILL SHOT IS DRIVEN, NOT WAITED FOR. It steers the reticle onto whatever
hazard is nearest using only what is ON SCREEN — the same closed loop the test
module uses — because a fixed input script that happened to hit today would
photograph a miss tomorrow.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner  # noqa: E402

ROM = SUPERFORGE / "build" / "railshooter.sfc"
SETTLE = 150            # the fade-in is done and the field has spread in depth

# game/railshooter/railshooter.inc — the OAM window, front to back
RET_SLOT, BURST_SLOT, SHIP_SLOT = 0, 1, 2
HAZ_SLOT0, HAZ_N = 3, 4
SCORE_SLOT0, SCORE_DIGITS = 10, 4
LIFE_SLOT0, LIFE_N = 14, 5
PYL_SLOT0, PYL_SLOTS = 22, 6 # behind the HUD, after the OAM reorder
T_LIFE_FULL, T_LIFE_EMPTY = 204, 206
T_HAZ = (192, 196, 164, 166)
T_PYL_NEAR = (64, 68)
LARGE = (192, 196)              # the two hazard tiers the PPU draws at 32x32


def hold(runner, frames, **buttons):
    """Step `frames` emulated frames with `buttons` held on pad 1."""
    for _ in range(frames):
        runner.frame_step(1, **buttons)


def oam(runner):
    from mesen_runner import MemoryType
    return runner.read_bytes(MemoryType.SnesSpriteRam, 0, 544)


def entry(o, s):
    x, y, tile, attr = o[s * 4:s * 4 + 4]
    x9 = (o[512 + (s >> 2)] >> ((s & 3) * 2)) & 1
    v = x + 256 * x9
    return (v - 512 if v >= 256 else v), y, tile


def nearest_hazard(o):
    live = [entry(o, s) for s in range(HAZ_SLOT0, HAZ_SLOT0 + HAZ_N)
            if o[s * 4 + 2] != 0]
    return min(live, key=lambda h: T_HAZ.index(h[2])) if live else None


def steer_onto_target(runner, budget=120):
    """The pilot's loop: fly the reticle onto the nearest hazard from what is
    rendered. Returns True once the crosshair is on it."""
    for _ in range(budget):
        o = oam(runner)
        tgt = nearest_hazard(o)
        if tgt is None:
            hold(runner, 1)
            continue
        tx, ty, tile = tgt
        half = 16 if tile in LARGE else 8
        rx, ry, _ = entry(o, RET_SLOT)
        rcx, rcy = rx + 8, ry + 8
        pad = {}
        if tx + half - rcx > 4:
            pad["right"] = True
        elif rcx - (tx + half) > 4:
            pad["left"] = True
        if ty + half - rcy > 4:
            pad["down"] = True
        elif rcy - (ty + half) > 4:
            pad["up"] = True
        if not pad:
            return True
        hold(runner, 1, **pad)
    return False


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    runner = MesenRunner()
    runner.boot_to_frame(str(ROM), SETTLE)
    runner.debug_break()

    def shot(name):
        runner.take_screenshot(str(out / f"railshooter_{name}.png"))
        print(f"{name:6s} ->", out / f"railshooter_{name}.png")

    shot("rail")

    # --- the pylon at its nearest: hold until the column is on a near tier --
    for _ in range(320):
        o = oam(runner)
        near = [s for s in range(PYL_SLOT0, PYL_SLOT0 + PYL_SLOTS)
                if o[s * 4 + 2] in T_PYL_NEAR]
        if len(near) >= 3:
            break
        hold(runner, 1)
    shot("pylon")

    # --- the drag: hands off through a bend, so the aim slides off centre ---
    hold(runner, 64)
    shot("drag")

    # --- the kill: steer on, fire, photograph the flash ---------------------
    if steer_onto_target(runner):
        hold(runner, 1, a=True)
        hold(runner, 2)
        shot("kill")
    else:
        print("kill   -> SKIPPED: never acquired a target")

    # --- damage, then the fail state ----------------------------------------
    # MID, not "any damage": the first hit empties one segment and lands a frame
    # that is hard to tell from the kill shot above. The set wants the bar at
    # 5, MID and 0, so this waits for exactly two left.
    # The life slots are NAMED, not spelled `20 + i` inline. They were, twice,
    # and an OAM reorder walked straight into it: the loops silently
    # began reading the HUD's pad slots and the pylons, the break conditions
    # stopped matching, and both captures landed on whatever frame the loop ran
    # out on — two committed renders quietly showing the wrong moment, with no
    # error anywhere. Same drift class the .assert block in rs_obj.asm now
    # refuses on the ASM side.
    for _ in range(1200):
        o = oam(runner)
        if sum(1 for i in range(LIFE_N)
               if o[(LIFE_SLOT0 + i) * 4 + 2] == T_LIFE_FULL) == 2:
            break
        hold(runner, 1)
    shot("hurt")

    for _ in range(900):
        o = oam(runner)
        if all(o[(LIFE_SLOT0 + i) * 4 + 2] == T_LIFE_EMPTY for i in range(LIFE_N)):
            break
        hold(runner, 1)
    hold(runner, 8)
    shot("fail")

    runner.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rs_shots"))
