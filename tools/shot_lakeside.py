"""Render the lakeside rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_lakeside.py [outdir]

Boots build/lakeside.sfc and photographs the whole of what the rail is for, on
ABSOLUTE frames: the title with the blender composed OFF, the lake with the
surface half-added over the world, the same lake stilled, the surface half a
pattern-period later, and the title returned to — which is the frame that shows
the blend did NOT outlive the scene that armed it. No assertions; this exists
so a human can LOOK at the ROM the suite just called green.

THE PAIR THAT CARRIES THE POINT is `title` and `lake`. They are the same world,
tile for tile and palette for palette; the only difference is that one scene
designates BG2 to the sub screen and programs the blender. If the lake's lake
bed is not visibly the title's lake bed seen through water, the composition is
not doing what it claims.

AND `title_returned` IS THE HYGIENE HALF. The composed colour-math state is per
scene and nothing carries it across an edge, so this frame is what the title
looks like AFTER the lake armed a blend. It must be indistinguishable from the
first one.

LOCKSTEP, so the renders are a pure function of (rom md5, seed, input script):
two runs photograph the same instants and a visual diff means something. No
wall-clock anywhere. NOTE Machine.screenshot itself costs one emulated frame,
so the frame arithmetic below is the drive's own rather than free-standing
timestamps.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine  # noqa: E402

ROM = SUPERFORGE / "build" / "lakeside.sfc"

TITLE = 60          # well past the 15-frame fade-in
SETTLE = 79         # title -> lake, including both fade ramps
PERIOD = 32         # the ripple's period in px, and at 1 px/frame in frames


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    shots = []

    def shot(m, name, note):
        p = out / f"lakeside_{name}.png"
        m.screenshot(str(p))
        shots.append(p)
        print(f"{name:16s} -> {p}   {note}")

    with Machine(str(ROM)) as m:
        m.advance(TITLE)
        shot(m, "title", "the world, blender composed OFF (CGWSEL $30)")

        m.advance(1, pad1={"start": True})
        m.advance(SETTLE)
        shot(m, "lake", "the surface on the sub screen, half-added")

        m.advance(PERIOD // 2 - 1)
        shot(m, "lake_drifted", "half a pattern period later — the ripple slid")

        m.advance(1, pad1={"b": True})          # latch the drift off
        m.advance(8)
        shot(m, "lake_stilled", "B stills it: the same surface, holding")

        m.advance(1, pad1={"start": True})
        m.advance(SETTLE)
        shot(m, "title_returned",
             "back at the title — the blend did not come with it")

    print(f"\n{len(shots)} renders in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "build/shots"))
