"""Render the meteor_event rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_meteor_event.py [outdir]

Boots build/meteor_event.sfc and photographs the WHOLE event on ABSOLUTE
frames: the Mode-1 level as it boots, the walk mid-stride, the frozen frame,
the captured ground standing on black with the BG dropped, the far-approach
speck, the crossover pose, the Mode-7 meteor growing in place, the red glow at
its peak, the receded tail, and the restored level with control back. No
assertions — this exists so a human can LOOK at the ROM the suite just called
green, beat by beat.

THE CAPTURE PAIR IS THE POINT OF THE THIRD AND FOURTH. `freeze` still has the
BG; `captured` has TM = OBJ only and is the same picture. If those two frames
look different, the capture's whole claim is wrong — and the test asserts them
pixel-identical, so this is the human-readable half of that assertion.

LOCKSTEP, so the renders are a pure function of (rom md5, seed, input script):
two runs photograph the same instants and a visual diff means something. No
wall-clock anywhere. NOTE Machine.screenshot itself costs one emulated frame
(machine.py:590), so the frame numbers below are the drive's own arithmetic,
not free-standing timestamps.
"""
import json
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "meteor_event.sfc"
WRAM = MemoryType.SnesWorkRam

# the state machine's DP offsets, read from the emitted map (never a literal)
_MAP = json.loads((SUPERFORGE / "build" / "met" / "symbol_map.json").read_text())


def _sym(name):
    return next(p for p in _MAP["globals"] if p["sym"] == name)["start"]


_ST, _TIMER, _WX = _sym("US_G_STATE"), _sym("US_G_TIMER"), _sym("US_G_WORLDX")
PLAY, FREEZE, CAPTURE, SCENE, RESTORE = 0, 1, 2, 3, 4
SPRITE_END = 72                         # meteor.inc's, mirrored for sequencing


def _u16(m, addr):
    b = m.read_bytes(WRAM, addr, 2)
    return b[0] | (b[1] << 8)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(m, name):
        p = out / f"meteor_{name}.png"
        m.screenshot(str(p))
        shots.append(p)
        print(f"{name:12s} -> {p}")

    def park(m, state, timer, limit=800):
        for _ in range(limit):
            if _u16(m, _ST) == state and _u16(m, _TIMER) == timer:
                return
            m.advance(1)
        raise SystemExit(f"never reached state={state} timer={timer}")

    def reach(m, state, limit=800):
        for _ in range(limit):
            if _u16(m, _ST) == state:
                return
            m.advance(1)
        raise SystemExit(f"never reached state={state}")

    with Machine(str(ROM)) as m:
        m.advance(40)                    # past the boot fade-in
        shot(m, "level")                 # the Mode-1 slice as it boots

        m.advance(70, pad1={"right": True})
        shot(m, "walk")                  # mid-stride, the world scrolling

        for _ in range(400):             # on to the trigger
            m.advance(1, pad1={"right": True})
            if _u16(m, _ST) != PLAY:
                break
        park(m, FREEZE, 20)
        shot(m, "freeze")                # input gated, the BG still up

        park(m, CAPTURE, 12)
        shot(m, "captured")              # TM = OBJ only: the SAME picture,
                                         #   now made of sprites

        reach(m, SCENE)
        park(m, SCENE, 40)
        shot(m, "approach")              # the far speck over the frozen ground

        park(m, SCENE, SPRITE_END + 2)
        shot(m, "crossover")             # the plane, revealed at the sprite's
                                         #   own apparent size

        park(m, SCENE, SPRITE_END + 18)
        shot(m, "grow")                  # growing IN PLACE about the pivot

        park(m, SCENE, SPRITE_END + 48)
        shot(m, "glow_peak")             # the red impact wash at full, the
                                         #   captured sprites untinted

        park(m, SCENE, SPRITE_END + 100)
        shot(m, "recede")                # the meteor gone, the glow receding

        reach(m, RESTORE)
        reach(m, PLAY)
        m.advance(40)                    # settle after the swap back. Both
                                         #   edges declare `style = "cut"`
                                         #: one blank frame, no
                                         #   ramp. The boot fade-in above is
                                         #   still a fade — it comes from
                                         #   level::enter, outside the phase
                                         #   machine.
        m.advance(40, pad1={"right": True})
        shot(m, "restored")              # a walkable level again
        print(f"cycle complete: world x back under the pad at {_u16(m, _WX)}")

    print(f"\n{len(shots)} renders in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "build/shots"))
