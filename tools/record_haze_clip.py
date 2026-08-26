"""Record the heathaze rail to an animated GIF (an owner-validation render).

Usage:  python3 tools/record_haze_clip.py [out.gif]

THE CLIP IS AN ARGUMENT, not a montage. It shows, in one take and one binary:

  the TITLE      the world with BG1HOFS composed flat by `hz_flat`
  the DESERT     the same world with the warp channel armed — the road's
                 edges, its dashes and the saguaro trunks bending, the sky
                 and the ridge above the band perfectly still
  the CONTROL    B, and the channel switches to the 33rd blob: a complete
                 HDMA table whose every displacement is zero. One variable
                 moves. This is the concept sheet's "before distortion /
                 after heat haze" pair, live.
  and BACK       B again — the shimmer RESUMES rather than restarting, which
                 is what makes the toggle a control instead of a reset — then
                 Start, and the title returns UNDISPLACED. That last frame is
                 the hygiene half: `desert` left BG1HOFS wherever the last
                 scanline put it, and the title writes it from `hz_flat`'s
                 own composed symbol rather than inheriting a warp.

The take RETURNS TO THE TITLE so the loop's join is invisible, and it is the
same beat the gallery clip uses for the same reason.

LOCKSTEP, so the clip is a pure function of (rom md5, seed, input script) and
two recordings are byte-identical. No wall-clock anywhere.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "tools"))

from record_gallery_clip import record_clip, STEP    # noqa: E402

ROM = SUPERFORGE / "build" / "heathaze.sfc"

# The beats, in captures. Each capture is EVERY emulated frames, so these are
# durations in the ROM's own time rather than in the host's.
TITLE_HOLD = 6          # long enough to read the title
SETTLE = 24             # title -> desert, both fade ramps
SHIMMER = 30            # the shimmer, running
FLAT = 14               # ...and the same picture with the flat table
SHIMMER_2 = 22          # B again: it RESUMES, it does not restart
RETURN = 24             # desert -> title, and the undisplaced world


class Drive:
    """Press the buttons on capture boundaries; idle otherwise."""

    def __init__(self):
        self.n = 0

    def __call__(self, runner, i):
        self.n += 1
        press = None
        if self.n == TITLE_HOLD:
            press = {"start": True}                     # -> desert
        elif self.n == TITLE_HOLD + SETTLE + SHIMMER:
            press = {"b": True}                         # -> flat
        elif self.n == TITLE_HOLD + SETTLE + SHIMMER + FLAT:
            press = {"b": True}                         # -> shimmer again
        elif self.n == TITLE_HOLD + SETTLE + SHIMMER + FLAT + SHIMMER_2:
            press = {"start": True}                     # -> title
        # frame_step, not advance: this is the frame-stepping runner the clip
        # recorder parks, and `hold()` above is the shape a drive takes.
        if press:
            runner.frame_step(1, **press)
            runner.frame_step(STEP - 1)
        else:
            runner.frame_step(STEP)


def main(out):
    total = TITLE_HOLD + SETTLE + SHIMMER + FLAT + SHIMMER_2 + RETURN
    path, frames, size = record_clip(str(ROM), out, drive=Drive(),
                                     captures=total)
    print(f"{path}  {frames} frames  {size / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "build/shots/heathaze.gif"))
