#!/usr/bin/env python3
"""Render the freed-channel rail's proof frames, from the built ROMs. No asserts.

Every capture lands on an ABSOLUTE emulated frame under the lockstep `Machine`
(`advance` only — no free-run, no wall-clock, no pad: the rail is autonomous
and takes no input at all), and each ROM's md5 is
printed beside its captures so the renders describe the same bytes.

    python3 tools/shot_split_h_irq_grad_demo.py docs/img

WHY THESE FRAMES. Unlike `seam_irq_trial`, this rail MOVES, so the sheet has
to show two things a single still cannot: what the composed picture looks like,
and that the two bands are driven independently.

  subject      frame 120 — the whole claim in one picture: band 1's cool
               perspective above, band 2's warm one below, the seam exactly
               between content lines 111 and 112 delivered by the seam IRQ,
               and the COLDATA ramp washing the frame from top to bottom on
               the channel that seam freed.
  subject_t32  frame 152 — the SAME ROM 32 frames later. Camera 2 has moved a
               whole checker period and is pixel-for-pixel back where it
               started; camera 1 has moved half of one and is visibly not.
               Put the two side by side and the lower band is identical while
               the upper band has shifted: that is the independent-driver
               claim, for the eye. The gradient is bit-identical in both, which
               is the other half — the wash is scanline-locked, not
               world-locked.
  nograd       frame 120 — the flip control (-DSHG_NO_GRAD). The same geometry
               with the gradient compiled out, so the sheet shows what the
               freed channel actually bought by showing the frame without it.
  gold         frame 120 — the gold control (-DSHG_HDMA_ORIGIN): band 2's
               origin through the classic origin HDMA pair instead of the IRQ.
               tests/test_split_h_irq_grad_demo.py's gold case asserts this is
               BYTE-IDENTICAL to `nograd`; the sheet prints both sha1s so a
               reader can check that by eye rather than take it on trust.

The subject's frame is re-taken from a fresh machine and must digest
byte-identical — a capture that is not reproducible is not evidence.
"""
import hashlib
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
from machine import Machine                                    # noqa: E402

SETTLED = 120            # tests/test_split_h_irq_grad_demo.py's settled frame
BAND2_PERIOD = 32        # camera 2's measured checker-repeat period, in frames

# (rom stem, shot name, absolute frame)
SHOTS = (
    ("split_h_irq_grad_demo", "subject", SETTLED),
    ("split_h_irq_grad_demo", "subject_t32", SETTLED + BAND2_PERIOD),
    ("shg_nograd", "nograd", SETTLED),
    ("shg_origin", "gold", SETTLED),
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
    shas = {}
    for stem, name, frame in SHOTS:
        rom = SUPERFORGE / "build" / f"{stem}.sfc"
        if not rom.exists():
            print(f"{rom} missing — run `make split_h_irq_grad_demo "
                  f"shg-nograd shg-origin` first")
            return 1
        digest = hashlib.md5(rom.read_bytes()).hexdigest()
        path = out / f"split_h_irq_grad_demo_proof_{name}.png"
        shas[name] = _shot(rom, frame, path)
        print(f"{stem}.sfc  {rom.stat().st_size} B  md5 {digest}")
        print(f"    {path}  frame {frame}  sha1 {shas[name]}")
    # The gold identity, as a digest the reader can compare without running
    # the suite. The test is the assertion; this is the human-legible copy.
    same = shas["nograd"] == shas["gold"]
    print(f"nograd vs gold frame {SETTLED}: "
          f"{'SHA1-IDENTICAL' if same else 'DIFFER'}  "
          f"({shas['nograd']} / {shas['gold']})")
    # Byte stability: the subject's frame from a fresh machine, again.
    rom = SUPERFORGE / "build" / "split_h_irq_grad_demo.sfc"
    recheck = out / ".shg_recheck.png"
    again = _shot(rom, SETTLED, recheck)
    recheck.unlink()
    ok = again == shas["subject"]
    print(f"subject frame re-taken from a fresh machine: "
          f"{'BYTE-IDENTICAL' if ok else 'DIFFERS — not reproducible'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
