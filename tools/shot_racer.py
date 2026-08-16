#!/usr/bin/env python3
"""Render the `racer` proof frames under the lockstep Machine.

Four ABSOLUTE frames, each after a fixed input script, so the renders are a
pure function of the replay triple — and the ROM's md5 is printed at render
time, so the PNGs provably describe the same bytes. The drive
scripts live HERE rather than in the spec's prose: a proof whose drive
is only described is not reproducible (batch-5 audit L-1).

    day     frame 100                      the shipping picture, DAY hold
    speed   frame 100 + 30 held B          the speed bar lit, the kart moving
    steer   frame 100 + 10 held Left       the floor rotated, the kart leaning
    night   frame 300                      the NIGHT hold, same camera

The drives are SHORT on purpose, and `steer` carries no throttle at all:
steering from the standstill rotates the world under a camera that stays on
the start line, which is the picture the claim is about — under way, the
same frames of turn also translate the camera, and the rotation photographs
as a curve through the world instead of as the floor turning.

Run:  make racer && python3 tools/shot_racer.py docs/img
"""
import argparse
import hashlib
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine                                    # noqa: E402

ROM = SUPERFORGE / "build" / "racer.sfc"
SEAM = 44                       # game/racer/world.inc HUD_LINES

SHOTS = (
    ("racer_proof_day",   100, ()),
    ("racer_proof_speed", 100, ((30, {"b": True}),)),
    ("racer_proof_steer", 100, ((10, {"left": True}),)),
    ("racer_proof_night", 300, ()),
)


def _bands(im):
    """Colour counts per band — the number a reader can check against the
    picture: the sky band and the Mode-7 floor are different compositions."""
    px = im.convert("RGB").load()
    sky = {px[x, y] for y in range(0, SEAM) for x in range(im.width)}
    floor = {px[x, y] for y in range(SEAM, 224) for x in range(im.width)}
    lum = sum(sum(px[x, y]) for y in range(0, SEAM)
              for x in range(0, im.width, 4))
    return len(sky), len(floor), lum


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir", type=Path)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"rom  {ROM.name}  md5 {hashlib.md5(ROM.read_bytes()).hexdigest()}")
    from PIL import Image
    for name, frame, drives in SHOTS:
        m = Machine(str(ROM)).advance(frame)
        try:
            for n, pad in drives:
                m.advance(n, pad1=pad)
            out = m.screenshot(str(args.outdir / f"{name}.png"))
            bar = [m.read_bytes(18, 4 + i * 4 + 2, 1)[0] for i in range(6)]
            kart = tuple(m.read_bytes(18, 0, 4))
        finally:
            m.close()
        sky, floor, lum = _bands(Image.open(out))
        drive = "".join(f" +{n}{''.join(sorted(p))}" for n, p in drives)
        print(f"  {name}.png  frame {frame}{drive}"
              f"  sky {sky} colours (lum {lum})  floor {floor} colours"
              f"  bar {bar}  kart {kart}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
