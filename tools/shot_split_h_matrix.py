#!/usr/bin/env python3
"""Render the matrix-band pair's committed proof frames, from the built ROMs.

Every capture lands on an ABSOLUTE emulated frame under the lockstep `Machine`
(`advance` only — no free-run, no wall-clock), and the ROM's md5 is printed
beside each one so the renders describe the same bytes.

    python3 tools/shot_split_h_matrix.py docs/img

Frames, per rail:
  boot       frame 90                      — the shipping band list
  zoom       frame 90 + 16 held Right      — the live band MID-SWEEP.
                                             SIXTEEN, measured: at 40 the
                                             three-band rail has already
                                             reached its ceiling ($0080 + 39*4
                                             > $0100), so its "zoom" and
                                             "collapse" frames were identical
                                             and the pair proved one thing
                                             twice. 15 applied steps puts the
                                             two-band rail at $007C and the
                                             three-band one at $00BC — both
                                             visibly between their endpoints.
  collapse   frame 90 + 80 held Right      — the live band clamped at camera
                                             A's scale: the one-camera
                                             control, reached by input inside
                                             the SAME binary
"""
import hashlib
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from machine import Machine                                    # noqa: E402

BOOT = 90
RIGHT = {"right": True}
SHOTS = (("boot", 0), ("zoom", 16), ("collapse", 80))
RAILS = (("split_h_matrix_demo", "split_h_matrix"),
         ("split_h_persp3_demo", "split_h_persp3"))


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img")
    out.mkdir(parents=True, exist_ok=True)
    for rom_name, tag in RAILS:
        rom = SUPERFORGE / "build" / f"{rom_name}.sfc"
        digest = hashlib.md5(rom.read_bytes()).hexdigest()
        print(f"{rom_name}.sfc  {rom.stat().st_size} B  md5 {digest}")
        for name, held in SHOTS:
            m = Machine(str(rom)).advance(BOOT)
            if held:
                m.advance(held, pad1=RIGHT)
            path = out / f"{tag}_proof_{name}.png"
            m.screenshot(str(path))
            m.close()
            print(f"    {path}  frame {BOOT}"
                  + (f" + {held} held Right" if held else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
