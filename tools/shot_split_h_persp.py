#!/usr/bin/env python3
"""Render the split_h_persp_demo proof frames under the lockstep Machine.

Three ABSOLUTE frames, each after a fixed input script, so the renders are a
pure function of the replay triple — and the ROM's md5 is printed at render
time, so the PNGs and the spec provably describe the same bytes.

    boot      frame 90                    the shipping two-camera picture
    zoom      frame 90 + 5 held Up        camera B mid-sweep, camera A still
    collapse  frame 90 + 40 held Down     camera B folded onto camera A's pose

Run:  make split_h_persp_demo && python3 tools/shot_split_h_persp.py docs/img
"""
import argparse
import hashlib
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from machine import Machine                                    # noqa: E402
import shp_predict as P                                        # noqa: E402

ROM = SUPERFORGE / "build" / "split_h_persp_demo.sfc"
BOOT = 90

SHOTS = (
    ("split_h_persp_proof_boot", ()),
    ("split_h_persp_proof_zoom", ((5, {"up": True}),)),
    ("split_h_persp_proof_collapse", ((40, {"down": True}),)),
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"rom  {ROM.name}  md5 {hashlib.md5(ROM.read_bytes()).hexdigest()}")
    from PIL import Image
    for name, drives in SHOTS:
        m = Machine(str(ROM)).advance(BOOT)
        try:
            for n, pad in drives:
                m.advance(n, pad1=pad)
            out = m.screenshot(str(args.outdir / f"{name}.png"))
        finally:
            m.close()
        im = Image.open(out)
        prof = [P.transitions(im, r) for r in range(P.PICTURE_LINES)]
        band1 = (prof[0], prof[111])
        band2 = (prof[112], prof[223])
        red = (round(P.mean_red(im, 0, 112), 1), round(P.mean_red(im, 112, 224), 1))
        print(f"  {name}.png  frame {BOOT}"
              f"{''.join(f' +{n} {list(p)[0]}' for n, p in drives)}"
              f"  band1 transitions {band1[0]}->{band1[1]}"
              f"  band2 {band2[0]}->{band2[1]}  mean red {red}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
