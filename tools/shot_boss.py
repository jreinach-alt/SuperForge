"""Render the boss rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_boss.py [outdir]

Boots build/boss.sfc and photographs the WHOLE state cycle on ABSOLUTE
frames: the far pre-reveal pose, the mid-ramp grow-in, the rest-size hold,
the fight (rain + bolts + the strafing ship), the death recede in two poses,
the bright win card, and the re-armed reveal after the loop closes. No
assertions — this exists so a human can LOOK at the ROM the suite just
called green, beat by beat.

THE REVEAL TRIPLE IS THE POINT OF THE FIRST THREE. This rail's whole
subject is a scale axis m7_affine does not have; frames far/mid/rest are the
baked track rendering it. The two recede frames are the same axis run the
other way with the spin composed in — and the win card after them shows the
eight HP pips all dim, which is what "the boss is dead" looks like in OAM.

LOCKSTEP, so the renders are a pure function of (rom md5, seed, input
script): two runs photograph the same instants and a visual diff means
something. No wall-clock anywhere. NOTE Machine.screenshot itself costs one
emulated frame (machine.py:600), so the frame numbers below are the drive's
own arithmetic, not free-standing timestamps.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "boss.sfc"
WRAM = MemoryType.SnesWorkRam

# US_B_STATE's DP offset, read from the emitted map (never a literal)
import json  # noqa: E402

_MAP = json.loads((SUPERFORGE / "build" / "bs" / "symbol_map.json").read_text())
_ST = next(p for p in _MAP["scenes"]["arena"]["placements"]
           if p["sym"] == "US_B_STATE")["start"]
_HP = next(p for p in _MAP["scenes"]["arena"]["placements"]
           if p["sym"] == "US_B_HP")["start"]
FIGHT, DEATH, RESULT, REVEAL = 3, 4, 6, 1


def _st(m):
    b = m.read_bytes(WRAM, _ST, 2)
    return b[0] | (b[1] << 8)


def _hp(m):
    b = m.read_bytes(WRAM, _HP, 2)
    return b[0] | (b[1] << 8)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(m, name):
        p = out / f"boss_{name}.png"
        m.screenshot(str(p))
        shots.append(p)
        print(f"{name:12s} -> {p}")

    with Machine(str(ROM)) as m:
        m.advance(12)                    # mid fade-in (measured (12,1) here);
                                         # the boss still far either way
        shot(m, "reveal_far")
        m.advance(20)                    # mid-ramp
        shot(m, "reveal_mid")
        m.advance(42)                    # rest size, holding, gentle spin
        shot(m, "hold_rest")

        # into the fight; strafe to the dodge lane and fire a while so the
        # frame holds rain, bolts and a lit-but-chipped HUD at once
        pad = {"a": True, "left": True}
        while _st(m) != FIGHT:
            m.advance(2)
        m.advance(90, pad1=pad)
        shot(m, "fight")

        # drive the kill through DYING into the recede
        while _st(m) != DEATH:
            m.advance(4, pad1=pad)
        m.advance(6)
        shot(m, "recede_early")
        m.advance(40)
        shot(m, "recede_late")

        while _st(m) != RESULT:
            m.advance(4)
        m.advance(4)
        shot(m, "win_card")

        # the loop closes: RESULT -> fade -> RESET -> a fresh reveal
        while _st(m) != REVEAL:
            m.advance(4)
        m.advance(22)                    # fade back up, ramp under way
        shot(m, "loop_reveal")
        print(f"cycle complete: hp re-armed to {_hp(m)}")

    print(f"\n{len(shots)} renders in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "build/shots"))
