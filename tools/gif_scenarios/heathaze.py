"""heathaze — the mirage and its control, cut on the title it returns to.

THE CLIP IS AN ARGUMENT, not a montage. It shows, in one take and one binary:

    the TITLE      the world with BG1VOFS composed flat by `hz_flat`
    the DESERT     the same world with the warp channels armed -- below the
                   horizon every scanline is drawn from a slightly different
                   SOURCE ROW, so the ground compresses and stretches and the
                   road, its dashes and the saguaro trunks boil, with a small
                   horizontal term beside it; the sky and the ridge above the
                   band perfectly still
    the CONTROL    B, and the channels switch to blob 64, the 65th: a complete
                   HDMA table whose every displacement is zero. One variable
                   moves -- the "before distortion / after heat haze" pair,
                   live, from one binary
    and BACK       B again -- the shimmer RESUMES rather than restarting, which
                   is what makes the toggle a control instead of a reset --
                   then Start, and the title returns UNDISPLACED

THAT LAST FRAME IS THE HYGIENE HALF. `desert` left BG1VOFS wherever the last
scanline put it, and the title writes it from `hz_flat`'s own composed symbol
rather than inheriting a warp. It is also what closes the loop: the take
returns to the title so the join a viewer sees is the same instant twice.

THE BEATS ARE IN CAPTURES, three emulated frames each, so they are durations in
the ROM's own time rather than in the host's.
"""
from tools.record_gallery_clip import STEP

ROM = "heathaze"

TITLE_HOLD = 6          # long enough to read the title
SETTLE_B   = 24         # title -> desert, both fade ramps
SHIMMER    = 30         # the shimmer, running
FLAT       = 14         # ...and the same picture with the flat table
SHIMMER_2  = 22         # B again: it RESUMES, it does not restart
RETURN     = 24         # desert -> title, and the undisplaced world

CAPTURES = TITLE_HOLD + SETTLE_B + SHIMMER + FLAT + SHIMMER_2 + RETURN


class Drive:
    """Press the buttons on capture boundaries; idle otherwise."""

    def __init__(self):
        self.n = 0

    def __call__(self, runner, i):
        self.n += 1
        press = None
        if self.n == TITLE_HOLD:
            press = {"start": True}                     # -> desert
        elif self.n == TITLE_HOLD + SETTLE_B + SHIMMER:
            press = {"b": True}                         # -> flat
        elif self.n == TITLE_HOLD + SETTLE_B + SHIMMER + FLAT:
            press = {"b": True}                         # -> shimmer again
        elif self.n == TITLE_HOLD + SETTLE_B + SHIMMER + FLAT + SHIMMER_2:
            press = {"start": True}                     # -> title
        # frame_step, not advance: this is the frame-stepping runner the clip
        # recorder parks.
        if press:
            runner.frame_step(1, **press)
            runner.frame_step(STEP - 1)
        else:
            runner.frame_step(STEP)


def make_drive():
    return Drive()
