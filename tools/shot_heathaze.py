"""Render the heathaze rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_heathaze.py [outdir]

Boots build/heathaze.sfc and photographs the whole of what the rail is for, on
ABSOLUTE frames: the desert with the warp flat, the same desert boiling, the
boil half a phase-cycle later, the shimmer toggled back off inside the scene,
and the title returned to -- which is the frame that shows the warp did NOT
outlive the scene that armed it.  No assertions; this exists so a human can
LOOK at the ROM the suite just called green.

THE PAIR THAT CARRIES THE POINT is `title` and `desert`.  They are the same
world, tile for tile and palette for palette; the only difference is that one
scene hands BG1VOFS to a per-scanline transfer.  If the desert is not visibly
the title's desert seen through moving air, the composition is not doing what
it claims.

WHY THE PAIR IS PHOTOGRAPHED ON THE VERTICAL AXIS.  A per-scanline BG1HOFS
shears each row sideways and every source row still appears exactly once; a
per-scanline BG1VOFS makes scanline N draw source row N+d(N), so rows are
duplicated and skipped.  The squashing IS the effect, and it is what these
frames have to show.

AND `title_returned` IS THE HYGIENE HALF.  BG1VOFS is left wherever the last
scanline of the last armed frame put it, so this frame is what the title looks
like AFTER the desert drove that port.  It must be indistinguishable from the
first one -- `title` composes `hz_flat` for exactly that reason.

LOCKSTEP, so the renders are a pure function of (rom md5, seed, input script):
two runs photograph the same instants and a visual diff means something.  No
wall-clock anywhere.  NOTE Machine.screenshot itself costs one emulated frame,
so the frame arithmetic below is the drive's own rather than free-standing
timestamps.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine  # noqa: E402

ROM = SUPERFORGE / "build" / "heathaze.sfc"

# The beats, in ABSOLUTE emulated frames -- the same ones tests/test_heathaze.py
# drives, so a render and an assertion are talking about the same instant.
TITLE = 60              # past the fade-in
SETTLE = 79             # title -> desert, both ramps
SHOW = 12               # long enough for a toggle to reach the PPU
HALF_CYCLE = 32         # far enough for the boil to be a different picture


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(m, name, note):
        p = out / f"heathaze_{name}.png"
        m.screenshot(str(p))
        shots.append(p)
        print(f"{name:16s} -> {p}   {note}")

    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        shot(m, "title", "the world, BG1VOFS carrying its flat base (hz_flat)")

        m.advance(1, pad1={"start": True})
        m.advance(SETTLE)
        shot(m, "desert", "the same world boiling -- BG1VOFS per scanline")

        m.advance(HALF_CYCLE)
        shot(m, "desert_phase", "further round the phase loop -- a different "
                                "displacement over the same art")

        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        shot(m, "desert_flat", "B: the shimmer off, inside the scene -- the "
                               "control every per-row measurement is taken "
                               "against")

        m.advance(1, pad1={"b": True})
        m.advance(SHOW)
        m.advance(1, pad1={"start": True})
        m.advance(SETTLE)
        shot(m, "title_returned", "the title after the desert drove BG1VOFS "
                                  "-- indistinguishable from the first frame")

    print(f"\n{len(shots)} render(s) in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "build/shots/heathaze"))
