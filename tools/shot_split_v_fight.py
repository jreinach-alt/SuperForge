"""Render the split_v_fight rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_split_v_fight.py [outdir]

Boots build/split_v_fight.sfc and photographs the seven instants that make
this rail's claim checkable BY LOOKING, along one continuous two-player
sequence:

    01 merged       both fighters together, spread 0. The seam is PRESENT and
                    INVISIBLE: the two half-cameras are equal, so the halves
                    are pixel-identical and there is no divider. If this frame
                    shows a seam, the whole "not a toggle" claim is wrong
    02 opening      mid-part, spread ~13 of 40: the halves have begun to
                    diverge and the beveled BG3 bar has grown off zero width
    03 open         both fighters against their walls, spread at its 40 cap —
                    the widest divider and the largest camera disagreement
    04 re-merged    walked back together: spread 0 again, divider gone. The
                    pair 03/04 is the reversibility claim, and 04 should be
                    hard to tell from 01 apart from the stage position
    05 crossing     the fighters have walked THROUGH each other — fighter 1 is
                    now to the RIGHT of fighter 2 — photographed at the merge,
                    where the crossover happens
    06 swapped      ...and the split re-opened from the crossed state: the
                    same picture as 03 with the fighters' sides exchanged,
                    which is what "the split follows the crossover" means
    07 closed       back to merged from the crossed side

There are no assertions here. This exists so a human (or the maintainer) can
LOOK at the ROM the suite just called green — CLAUDE.md rule 3's "attach a
fresh render from the verified binary", produced from the binary rather than
relayed.

STATE-DRIVEN WHERE THE ROM OWNS THE BEAT. The spread is an EASE chasing a
target (0.75 px/frame against a target moving at 2), so "how many frames to
fully open" is a tuning constant, not a fact — these walk until the ROM's own
ES_SV_SPREAD word says it has arrived. Everything else is absolute frames, and
the whole trajectory is a pure function of (rom md5, seed, input script), so
two runs of this tool photograph the same instants and a visual diff between
them means something. No wall-clock anywhere.
"""
import json
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "split_v_fight.sfc"
WRAM = MemoryType.SnesWorkRam

_MAP = json.loads((SUPERFORGE / "build" / "sv" / "symbol_map.json").read_text())


def _dp(name):
    return next(p for p in _MAP["scenes"]["fight"]["placements"]
                if p["sym"] == name)["start"]


SPREAD, FX1, FX2 = (_dp(n) for n in ("ES_SV_SPREAD", "US_FX1", "US_FX2"))
SPREAD_CAP = 40                 # measured on this binary: the ease's fixed
                                #   point with both fighters on the walls
SETTLE = 60                     # past the fade-in, fighters at 108 / 148

APART = dict(pad1={"left": True}, pad2={"right": True})
TOGETHER = dict(pad1={"right": True}, pad2={"left": True})
BACK = dict(pad1={"left": True}, pad2={"right": True})


def _u16(m, addr):
    b = m.read_bytes(WRAM, addr, 2)
    return b[0] | (b[1] << 8)


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(m, name):
        p = out / f"split_v_fight_{name}.png"
        m.screenshot(str(p))
        shots.append(p)
        print(f"{name:12s} -> {p}  spread={_u16(m, SPREAD)} "
              f"fx1={_u16(m, FX1)} fx2={_u16(m, FX2)}")

    def walk_until(m, pred, pads, limit=400):
        for _ in range(limit):
            if pred(m):
                return
            m.advance(1, **pads)
        raise SystemExit(f"the fighters never reached {pred.__name__}")

    with Machine(str(ROM)) as m:
        m.advance(SETTLE)
        shot(m, "01_merged")

        walk_until(m, lambda mm: _u16(mm, SPREAD) >= 12, APART)
        shot(m, "02_opening")

        walk_until(m, lambda mm: _u16(mm, SPREAD) >= SPREAD_CAP, APART)
        m.advance(20, **APART)                  # hold on the walls
        shot(m, "03_open")

        # ...and back together. The merge is the interesting instant: the
        # divider goes to zero width and the halves become identical again.
        walk_until(m, lambda mm: _u16(mm, SPREAD) == 0, TOGETHER)
        shot(m, "04_re_merged")

        # Keep walking THROUGH each other. fx1 passing fx2 is the crossover;
        # it happens inside the merged window, which is what makes it seamless.
        walk_until(m, lambda mm: _u16(mm, FX1) > _u16(mm, FX2) + 24, TOGETHER)
        shot(m, "05_crossing")

        walk_until(m, lambda mm: _u16(mm, SPREAD) >= SPREAD_CAP, TOGETHER)
        m.advance(20, **TOGETHER)
        shot(m, "06_swapped")

        walk_until(m, lambda mm: _u16(mm, SPREAD) == 0, BACK)
        shot(m, "07_closed")

    print(f"\n{len(shots)} renders in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else SUPERFORGE / "docs" / "img"))
