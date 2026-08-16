#!/usr/bin/env python3
"""Render the `mode7_chamber` proof frames under the lockstep Machine.

Four ABSOLUTE frames, each after a fixed input script, so the renders are a
pure function of the replay triple — and the ROM's md5 is printed at render
time, so the PNGs provably describe the same bytes. The drive
scripts live HERE rather than in the spec's prose: a proof whose drive
is only described is not reproducible (batch-5 audit L-1).

    boot     frame  120                the shipping picture: the FULL bow
    flat     frame  120 + Down held    the bow clamped to step 0 — no barrel
                                       at all, the runtime non-vacuity control
                                       INSIDE the shipping binary
    hold     frame 1610                the dead stop between legs (the roll's
                                       IDLE arm; ten frames later is
                                       bit-identical)
    reverse  frame 2000                mid-way through the REVERSE leg, whose
                                       surge peaks come from the second LFSR

`flat` holds Down from BOOT rather than from frame 120, so both it and `boot`
land on the same absolute frame with the roll at the same world row: the only
difference between the two pictures is the M7A column. That is the whole
comparison, and taking it any other way would fold the roll into it.

The per-shot line reports the PEAK number of colour changes across a rendered
row in each third of the floor band — the horizontal period, which IS the bow
(a row spans exactly A world pixels and the ashlar period is 16, so a row shows
A/8 changes; see tests/test_mode7_chamber.py). A reader can check the bow claim
off the printed numbers without opening the PNGs: the shipping picture bulges
in the middle third, the control is flat at 31-32 everywhere.

Run:  make mode7_chamber && python3 tools/shot_mode7_chamber.py docs/img
"""
import argparse
import hashlib
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from frame_geometry import png_row                             # noqa: E402
from machine import Machine                                    # noqa: E402

ROM = SUPERFORGE / "build" / "mode7_chamber.sfc"
SEAM = 32                       # game/mode7_chamber/world.inc MB_SEAM
THIRDS = ((32, 96), (96, 160), (160, 224))   # the floor band, in three

SHOTS = (
    ("chamber_proof_boot",     120, None),
    ("chamber_proof_flat",     120, {"down": True}),
    ("chamber_proof_hold",    1610, None),
    ("chamber_proof_reverse", 2000, None),
)


def _transitions(px, picture_row):
    y = png_row(picture_row)
    return sum(1 for x in range(1, 256) if px[x, y] != px[x - 1, y])


def _band_lum(px, a, b):
    return sum(sum(px[x, png_row(p)]) for p in range(a, b)
               for x in range(0, 256, 4)) / ((b - a) * 64)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"rom  {ROM.name}  md5 {hashlib.md5(ROM.read_bytes()).hexdigest()}")
    from PIL import Image
    for name, frame, pad in SHOTS:
        with Machine(str(ROM)) as m:
            m.advance(frame, pad1=pad) if pad else m.advance(frame)
            out = m.screenshot(str(args.outdir / f"{name}.png"))
        px = Image.open(out).convert("RGB").load()
        per = [max((_transitions(px, r) for r in range(a, b)), default=0)
               for a, b in THIRDS]
        drive = f" +{''.join(sorted(pad))} held" if pad else ""
        print(f"  {name}.png  frame {frame}{drive}"
              f"  peak period per third {per}"
              f"  band lum: mode1 {_band_lum(px, 0, SEAM):.0f}"
              f"  floor-mid {_band_lum(px, 96, 144):.0f}"
              f"  floor-bottom {_band_lum(px, 176, 224):.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
