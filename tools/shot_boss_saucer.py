"""Render the boss_saucer rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_boss_saucer.py [outdir]

Boots build/boss_saucer.sfc and photographs the WHOLE state cycle on ABSOLUTE
frames: the far pre-reveal pose over the star field, the mid-ramp grow-in with
the boot title, the rest-size hold, the lunge at rest and at its screen-filling
apex, the beam's sparse telegraph and its solid firing column, the death
recede, the VICTORY card over a still-lit arena, and the DEFEAT card the
no-input path reaches. No assertions — this exists so a human can LOOK at the
ROM the suite just called green, beat by beat.

THE LUNGE PAIR IS THE POINT. The subject is a scale axis m7_affine
does not have, and this rail runs it four times per cycle; `lunge_far` and
`lunge_apex` are the two ends of one dive, rendered from two baked blobs. The
beam pair after them is the attack that scale buys: the column is latched onto
the player's lane at the apex, so the telegraph frame is the dodge window and
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
        # ...and its screen-filling end, photographed on the dive's LAST frame
        # rather than at NEAR: the apex and the telegraph's first frame are the
        # same instant by construction, so a shot at NEAR would duplicate the
        # beam frame below instead of showing the scale axis alone.
        _until(m, _LG, LG_APPR)
        m.advance(42)
        shot(m, "lunge_apex")

        # the beam, from the apex: sparse telegraph, then the solid column
        _until(m, _BM, BM_TELE)
        m.advance(6)
        shot(m, "beam_telegraph")
        _until(m, _BM, BM_FIRE)
        m.advance(4)
        shot(m, "beam_fire")

        # drive the kill: hold A in the left lane until the saucer breaks off
        pad = {"a": True, "left": True}
        _until(m, _ST, DEATH, pad=pad)
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
