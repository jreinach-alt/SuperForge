"""Render the lakeside rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_lakeside.py [outdir]

Boots build/lakeside.sfc and photographs the whole of what the rail is for, on
ABSOLUTE frames: the title with the blender composed OFF, the lake with the
surface half-added over the world, the surface half a pattern-period later, the
surf DRAWN BACK and the surf RUN UP, the lake stilled, and the title returned to
— which is the frame that shows the blend did NOT outlive the scene that armed
it. No assertions; this exists so a human can LOOK at the ROM the suite just
called green.

THE SURF PAIR IS THE OTHER CLAIM. `lake_surf_out` and `lake_surf_in` are the
same beach: in one the wave has drawn back and every pixel of it is the world's
own colour at full intensity, in the other the wave has run up and every one of
those pixels is exactly the half-add of that colour with the water over it. The
animation and the colour math are the same event, and this is what that looks
like.

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
import json
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "lakeside.sfc"
ASSETS = SUPERFORGE / "build" / "assets"

TITLE = 60          # well past the 15-frame fade-in
SETTLE = 79         # title -> lake, including both fade ramps
PERIOD = 32         # the ripple's period in px, and at 1 px/frame in frames

# --- the surf's phases, so this tool can stop ON one -------------------------
# The waterline sweeps 26 px of shore on a 128-frame cycle, so "a picture of the
# lake" is not one picture any more: the two that carry the point are the wave
# RUN UP and the wave DRAWN BACK, and they have to be photographed at those
# instants rather than wherever a fixed frame count happens to land. Which phase
# is on screen is recovered from the band's display slots in VRAM against the
# blob the ROM DMAs from — the same recovery tests/test_lakeside.py makes, and
# for the same reason: an assumed offset from the scene switch would go stale
# the moment a fade ramp moved.
ART = {}
for _line in (ASSETS / "lk_art.inc").read_text().splitlines():
    if "=" in _line and not _line.lstrip().startswith(";"):
        _k, _v = _line.split("=", 1)
        ART[_k.strip()] = int(_v.strip())
_MAP = json.loads((SUPERFORGE / "build" / "lks" / "symbol_map.json").read_text())
V_WAT_CHR = next(p for p in _MAP["scenes"]["lake"]["placements"]
                 if p["sym"] == "ES_V_WAT_CHR")["start"]
BLK = ART["LK_SURF_BLOCK_BYTES"]
_BLOB = (ASSETS / "surf_chr.bin").read_bytes()
BLOCKS = [_BLOB[i * BLK:(i + 1) * BLK] for i in range(ART["LK_SURF_PHASES"])]

# Measured from the pictures this tool renders (see the module test's own
# sweep): the phase whose waterline sits highest up the shore, and the one
# where it has drawn furthest back.
SURF_IN, SURF_OUT = 5, 0


def surf_phase(m):
    live = bytes(m.read_bytes(MemoryType.SnesVideoRam,
                              (V_WAT_CHR + ART["LK_SURF_SLOT_WORDS"]) * 2, BLK))
    which = [i for i, b in enumerate(BLOCKS) if b == live]
    assert len(which) == 1, f"the band's slots match {which} declared phase(s)"
    return which[0]


def to_surf(m, want):
    m.advance(((want - surf_phase(m)) % ART["LK_SURF_PHASES"])
              * (ART["LK_SURF_STEP_PX"]))
    assert surf_phase(m) == want, f"wanted surf phase {want}, got {surf_phase(m)}"
    return m


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

        to_surf(m, SURF_OUT)
        shot(m, "lake_surf_out", "the wave drawn back — the beach is DRY, "
                                 "every pixel the world's own colour")
        to_surf(m, SURF_IN)
        shot(m, "lake_surf_in", "the wave run up — the same sand is now "
                                "(sand + water) >> 1. WET.")

        m.advance(1, pad1={"b": True})          # latch the drift off
        m.advance(8)
        shot(m, "lake_stilled", "B stills it: the surface AND the surf, holding")

        m.advance(1, pad1={"start": True})
        m.advance(SETTLE)
        shot(m, "title_returned",
             "back at the title — the blend did not come with it")

    print(f"\n{len(shots)} renders in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "build/shots"))
