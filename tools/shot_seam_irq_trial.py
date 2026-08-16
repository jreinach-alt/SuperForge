#!/usr/bin/env python3
"""Render the seam-IRQ trial's proof frames, from the built ROMs. No asserts.

Every capture lands on an ABSOLUTE emulated frame under the lockstep
`Machine` (`advance` only — no free-run, no wall-clock, no pad: the rail is
autonomous), and each ROM's md5 is printed beside its captures so the renders
 describe the same bytes.

    python3 tools/shot_seam_irq_trial.py docs/img

WHY THESE FRAMES. The scene is FROZEN — motion is not the subject; the seam
is. One settled frame per ROM says everything each build claims:

  seam_irq_trial  frame 120: the subject — band 1's cool perspective above,
                  band 2's warm one below, seam exactly between content
                  lines 111 and 112, delivered by the IRQ + pre-armed pair.
  sit_origin      frame 120: the GOLD control — the same picture through the
                  classic origin HDMA pair. tests/test_seam_irq_trial.py's
                  gold case asserts the two are BYTE-IDENTICAL; this sheet
                  is the human-eye copy of that identity.
  sit_mistime     frame 120: the NON-VACUITY control — VTIME=60, so content
                  lines 60..111 render warm and the mistimed seam is
                  visible five sixths of the way up band 1.

The subject's frame is re-taken from a fresh machine and must digest
byte-identical — a capture that is not reproducible is not evidence.
"""
import hashlib
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from machine import Machine                                    # noqa: E402

SETTLED = 120                   # tests/test_seam_irq_trial.py's settled frame

# (rom stem, shot name)
SHOTS = (
    ("seam_irq_trial", "subject"),
    ("sit_origin", "gold"),
    ("sit_mistime", "mistime"),
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
    for stem, name in SHOTS:
        rom = SUPERFORGE / "build" / f"{stem}.sfc"
        if not rom.exists():
            print(f"{rom} missing — run `make seam_irq_trial sit-origin "
                  f"sit-mistime` first")
            return 1
        digest = hashlib.md5(rom.read_bytes()).hexdigest()
        path = out / f"seam_irq_trial_proof_{name}.png"
        sha = _shot(rom, SETTLED, path)
        print(f"{stem}.sfc  {rom.stat().st_size} B  md5 {digest}")
        print(f"    {path}  frame {SETTLED}  sha1 {sha}")
    # Byte stability: the subject's frame from a fresh machine, again.
    rom = SUPERFORGE / "build" / "seam_irq_trial.sfc"
    recheck = out / ".sit_recheck.png"
    again = _shot(rom, SETTLED, recheck)
    first = hashlib.sha1(
        (out / "seam_irq_trial_proof_subject.png").read_bytes()).hexdigest()
    recheck.unlink()
    ok = again == first
    print(f"subject frame re-taken from a fresh machine: "
          f"{'BYTE-IDENTICAL' if ok else 'DIFFERS — not reproducible'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
