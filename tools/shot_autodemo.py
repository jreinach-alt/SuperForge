#!/usr/bin/env python3
"""Render the two pilot ROMs' committed proof frames, from the built ROMs.

Every capture lands on an ABSOLUTE emulated frame under the lockstep `Machine`
(`advance` only — no free-run, no wall-clock), and the ROM's md5 is printed
beside each one so the renders describe the same bytes.

    python3 tools/shot_autodemo.py docs/img

NO PAD IS EVER LATCHED, and that is the subject rather than a detail: these
builds exist so the rails can be watched with no controller attached, so a
render taken with a button held would be a picture of something else. The
frames are reached by advancing alone.

WHY THESE FRAMES. A pilot ROM's proof has to show MOTION, and a still cannot —
so each rail gets two captures separated by a known number of frames, chosen
from its own script so the difference is legible rather than incidental:

  shd  frame 90 and frame 218, a HALF TURN apart (256 / 2 — the heading steps
       once every 4 frames over 64 headings). The floor's horizon has swung
       through 180 degrees and the panel's 4-cell readout has walked 32
       headings, which is this variant's headline: ONE autonomous axis reaching
       BOTH bands, because the instrument is a readout of the camera rather
       than an independent fill bar.
  shp  frame 90 and frame 122, a HALF CYCLE apart (64 / 2). Camera A's band has
       rotated 32 of its 64 headings and camera B's has advanced 4 of its 8
       zooms — the two rates, 8:1, in one pair of pictures.

Both rails also get a `still` capture repeated: the SAME absolute frame taken
twice from two fresh machines, which is the byte-stability check
cites. It is printed as a digest rather than written twice.
"""
import hashlib
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from machine import Machine                                    # noqa: E402

BOOT = 90

# (rom stem, output tag, {shot name: absolute frame})
RAILS = (
    ("shd_autodemo", "shd_autodemo",
     (("boot", BOOT), ("halfturn", BOOT + 128))),
    ("shp_autodemo", "shp_autodemo",
     (("boot", BOOT), ("halfcycle", BOOT + 32))),
)


def _shot(rom: Path, frame: int, path: Path) -> str:
    """One capture at an absolute frame, no pad. Returns the PNG's sha1."""
    m = Machine(str(rom)).advance(frame)
    try:
        m.screenshot(str(path))
    finally:
        m.close()
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img")
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for stem, tag, shots in RAILS:
        rom = SUPERFORGE / "build" / f"{stem}.sfc"
        if not rom.exists():
            print(f"{rom} missing — run `make shd-autodemo shp-autodemo`")
            return 1
        digest = hashlib.md5(rom.read_bytes()).hexdigest()
        print(f"{stem}.sfc  {rom.stat().st_size} B  md5 {digest}")
        for name, frame in shots:
            path = out / f"{tag}_proof_{name}.png"
            first = _shot(rom, frame, path)
            print(f"    {path}  frame {frame}  sha1 {first}")
        # Byte stability: re-take the boot frame from a fresh machine and
        # require the identical PNG. A capture that is not reproducible is not
        # evidence, and the two rate-sensitive frames above are only worth
        # citing if the harness lands on the frame it names.
        again = _shot(rom, BOOT, out / f".{tag}_recheck.png")
        first = hashlib.sha1((out / f"{tag}_proof_boot.png").read_bytes()
                             ).hexdigest()
        (out / f".{tag}_recheck.png").unlink()
        ok = again == first
        bad += not ok
        print(f"    boot frame re-taken from a fresh machine: "
              f"{'BYTE-IDENTICAL' if ok else 'DIFFERS — not reproducible'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
