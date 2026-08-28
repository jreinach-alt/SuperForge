"""lakeside — a state cycle, cut on the title it returns to.

THE CLAIM IS THE BLEND, and it is a claim a single frame cannot make: the lake
bed has to be seen dry, then seen THROUGH the surface, and be recognisably the
same bed both times. So the take is choreographed rather than held:

    title       the world with the blender composed OFF
    the lake    the same world with a sub-screen layer half-added over it
    drifting    a WHOLE surf cycle -- the swash runs up the shore and the
                backwash draws down, and the sand it covers goes wet and dry
                with it, which is the colour math and the animation being the
                same event
    stilled     B latches the drift: the same surface, holding
    drifting    B again, and another whole cycle
    title       and the world with the blender off, again

IT RETURNS TO THE TITLE ON PURPOSE, and that serves two ends at once. A gallery
clip loops forever, so its last frame is glued back onto its first and the join
is invisible only when both land on the same instant of the ROM
(`record_gallery_clip`'s own rule). Here the instant that satisfies that is also
the transition-hygiene claim: the composed colour-math state is per scene, so
the title returned to is the title departed from -- the same picture, because
nothing carried the blend across the edge.

WHY THE DRIFT BEATS ARE 45 AND NOT 27. The surf's cycle is 128 px of drift =
128 frames at 1 px/frame, and a beat of 27 captures is 81 -- so the old
schedule showed two thirds of a wave and cut it off mid-backwash. 45 captures
is 135 frames, one whole cycle and a little over, so a viewer sees the swash
run up, the backwash draw down and the lull before the next one. The still beat
is unchanged: 36 frames is a quarter of a cycle, which is exactly the span over
which a running surf would visibly move and a stilled one does not.
"""
from tools.record_gallery_clip import STEP

ROM = "lakeside"

# NOT `SETTLE`: the scenario interface reserves that name for EMULATED boot
# frames before recording starts (gif_scenarios/__init__.py), so a beat
# constant called SETTLE would be read by the dispatcher as one and would
# silently change the take. This is a BEAT, in captures.
TITLE_HOLD = 6      # the opening title, blender composed OFF
SCENE_SWITCH   = 27     # a scene switch + both fade ramps (~81 frames)
DRIFT_A    = 45     # the surface drifting, and a WHOLE SURF CYCLE
STILL      = 12     # B latched: the same surface, holding -- surf included
DRIFT_B    = 45     # B again: the drift resumes, and another whole cycle


class Drive:
    """One capture per call, each advancing STEP frames; a press is one capture.

    A press lasts exactly one capture because stilling is a LATCHED TOGGLE --
    `take_screenshot` releases both pads for its own frame, so a held control
    would re-trigger on every capture and could not be photographed at all.
    """

    def __init__(self):
        self.marks, i = {}, TITLE_HOLD
        self.marks[i] = {"start": True}; i += 1 + SCENE_SWITCH + DRIFT_A
        self.marks[i] = {"b": True};     i += 1 + STILL
        self.marks[i] = {"b": True};     i += 1 + DRIFT_B
        self.marks[i] = {"start": True}; i += 1 + SCENE_SWITCH
        self.total = i

    def __call__(self, runner, i):
        runner.frame_step(STEP, **self.marks.get(i, {}))
        self.done = i >= self.total - 1


CAPTURES = Drive().total + 2


def make_drive():
    return Drive()
