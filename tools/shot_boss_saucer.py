"""Render the boss_saucer rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_boss_saucer.py [outdir]

Boots build/boss_saucer.sfc and photographs the WHOLE state cycle on ABSOLUTE
frames: the far pre-reveal pose over the star field, the mid-ramp grow-in with
the boot title, the rest-size hold, the lunge at rest and at its apex, the
beam's sight line and its firing lance, the death recede, the VICTORY card
over a still-lit arena, and the DEFEAT card the no-input path reaches. No assertions — this exists so a human can LOOK at the
ROM the suite just called green, beat by beat.

THE LUNGE PAIR IS THE POINT. The subject is a scale axis m7_affine
does not have, and this rail runs it four times per cycle; `lunge_far` and
`lunge_apex` are the two ends of one dive, rendered from two baked blobs. The
beam pair after them is the attack that scale buys: the lance leaves the
saucer's own emitter and lands on the column latched onto the player's lane,
so the telegraph frame is a sight line already aimed at the dodge window and
the fire frame is what ignoring it costs.

LOCKSTEP, so the renders are a pure function of (rom md5, seed, input script):
two runs photograph the same instants and a visual diff means something. No
wall-clock anywhere. NOTE Machine.screenshot itself costs one emulated frame,
so the frame numbers below are the drive's own arithmetic, not free-standing
timestamps.
"""
import json
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "boss_saucer.sfc"
WRAM = MemoryType.SnesWorkRam

# the DP offsets, read from the emitted map (never a literal)
_MAP = json.loads((SUPERFORGE / "build" / "sau" / "symbol_map.json").read_text())


def _dp(name):
    return next(p for p in _MAP["scenes"]["arena"]["placements"]
                if p["sym"] == name)["start"]


_ST, _LG, _BM, _HP = (_dp(n) for n in ("US_B_STATE", "US_LUNGE_STATE",
                                       "US_BEAM_STATE", "US_B_HP"))
_PX, _BX = (_dp(n) for n in ("US_P_X", "US_BEAM_X"))
_SPAWN = 120                       # saucer.inc's SAU_PLAYER_X0
REVEAL, HOLD, FIGHT, DEATH, RESULT = 1, 2, 3, 4, 6
LG_FAR, LG_APPR, LG_NEAR = 0, 1, 2
BM_TELE, BM_FIRE = 1, 2


def _rd(m, off):
    b = m.read_bytes(WRAM, off, 2)
    return b[0] | (b[1] << 8)


def _until(m, off, want, pad=None, limit=4000):
    for _ in range(limit):
        m.advance(1, pad1=pad or {})
        if _rd(m, off) == want:
            return
    raise SystemExit(f"{off:#x} never reached {want}")


class _Fight:
    """The drive that actually WINS: hold A, dodge each latched column once,
    then come back under the saucer.

    Standing on the spawn lane and holding A is no longer a kill — measured on
    this binary it ends at boss hp 35 with the gunship dead, because the
    saucer's hitbox is its rendered disc now and every beam that lands costs a
    heart. So the drive strafes clear while the beam is up and steers back to
    the lane when it is down, which is also how a player has to hold this
    fight.

    THE DIRECTION IS LATCHED ON THE BEAM'S RISING EDGE, not recomputed per
    frame: a per-frame "move away from the column" rule oscillates about it at
    3 px/frame and never leaves (measured — the ship jittered 120..123 through
    three whole beams and died with the saucer on 35 hp).
    """

    def __init__(self):
        self.dodge = None
        self.prev = 0

    def pad(self, m):
        bm, px, bx = _rd(m, _BM), _rd(m, _PX), _rd(m, _BX)
        if bm and not self.prev:
            self.dodge = "right" if bx < 128 else "left"
        self.prev = bm
        if bm:
            if abs(px + 4 - bx) < 28:            # still in the column's reach
                return {"a": True, self.dodge: True}
            return {"a": True}
        self.dodge = None
        if px < _SPAWN - 2:
            return {"a": True, "right": True}
        if px > _SPAWN + 2:
            return {"a": True, "left": True}
        return {"a": True}


def _fight_until(m, off, want, limit=6000):
    f = _Fight()
    for _ in range(limit):
        m.advance(1, pad1=f.pad(m))
        if _rd(m, off) == want:
            return
    raise SystemExit(f"{off:#x} never reached {want} under the fight drive")


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(m, name):
        p = out / f"boss_saucer_{name}.png"
        m.screenshot(str(p))
        shots.append(p)
        print(f"{name:14s} -> {p}")

    # ---- the win half of the cycle ----------------------------------------
    with Machine(str(ROM)) as m:
        m.advance(22)                    # 3 parks past the fade-in's finish
        shot(m, "reveal_far")
        m.advance(20)                    # mid-ramp, the title card up
        shot(m, "reveal_mid")
        m.advance(46)                    # rest size, holding, the ring spin
        shot(m, "hold_rest")

        _until(m, _ST, FIGHT)
        _until(m, _LG, LG_FAR)
        m.advance(2)
        shot(m, "lunge_far")             # the dive's rest end
        # ...and its near end, photographed on the last frame BEFORE the
        # telegraph arms: from there on the beam is on screen, so this is the
        # last instant that shows the scale axis alone.
        _until(m, _LG, LG_APPR)
        m.advance(19)
        shot(m, "lunge_apex")

        # the beam, from the apex: sparse telegraph, then the solid column
        _until(m, _BM, BM_TELE)
        m.advance(6)
        shot(m, "beam_telegraph")
        _until(m, _BM, BM_FIRE)
        m.advance(4)
        shot(m, "beam_fire")

        # drive the kill: hold A under the saucer, dodging each beam
        _fight_until(m, _ST, DEATH)
        m.advance(6)
        shot(m, "recede_early")
        m.advance(38)
        shot(m, "recede_late")
        _until(m, _ST, RESULT)
        m.advance(4)
        shot(m, "win_card")

        _until(m, _ST, REVEAL)
        m.advance(22)                    # the loop closed; fade back up
        shot(m, "loop_reveal")
        print(f"win cycle complete: hp re-armed to {_rd(m, _HP)}")

    # ---- the lose half: no input at all, so the path is deterministic
    with Machine(str(ROM)) as m:
        _until(m, _ST, RESULT)
        m.advance(4)
        shot(m, "defeat_card")

    print(f"\n{len(shots)} renders in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "build/shots"))
