"""The two pilot ROMs' autonomy, planted — and, above all, their RATES.

`shd_autodemo` and `shp_autodemo` exist to run with no controller,
so the obvious plant is "stop the script and watch the self-advance case go
red". That plant is here, and it is the LESS interesting half of this set.

WHAT THIS SET IS REALLY FOR. A pilot ROM is trivially easy to test badly: any
two frames, any digest, "they differ", green. Such a test passes on a demo
running at four times its intended speed, or on one whose two cameras have
come uncoupled — the picture still moves, and moving was the whole assertion.
So each variant gets a FROZEN plant and a WRONG-RATE plant, and the wrong-rate
plants are chosen so the self-advance case stays GREEN under them:

  shd-autodemo-frozen        the heading step is zeroed. Nothing moves.
  shd-autodemo-half-rate     the frame mask is widened 3 -> 7, so the heading
                             steps every 8 frames instead of 4 and the turn
                             takes 512 frames instead of 256. THE PICTURE
                             STILL MOVES, and the self-advance case still
                             passes — only the two rate cases fall.
  shp-autodemo-frozen        the heading never advances, so both bands stand
                             still (the zoom is a function of the heading).
  shp-autodemo-zoom-decoupled  one extra `lsr`, so zoom = head >> 4 rather
                             than head >> 3: camera B advances every 16 frames
                             instead of 8 while camera A is untouched. The
                             8:1 lock between the two reference rates is the one
                             thing this breaks, and it is invisible to every
                             assertion except the one written for it.

That pairing is the point of the set. If only the frozen plants existed, this
suite would have shown that the tests notice a DEAD demo and nothing more.

WHY head >> 4 AND NOT head >> 2. Decoupling the other way (zoom = head >> 2)
would index 0..15 into an 8-entry pose set and stream 448-byte poses from past
its end — a memory-safety defect whose rendered effect is whatever happens to
follow the blob, not a rate defect. A plant has to be a mistake someone could
actually make and whose blast radius is the mechanism under test; >> 4 stays
inside the set and changes exactly one thing.

NOT PLANTED, deliberately: the `.ifdef` guards themselves. Removing one does
not produce a wrong ROM, it produces a DIFFERENT ROM — the base rail's
behaviour under the variant's name — and `test_each_pilot_rom_differs_from_
the_rail_it_was_built_from` already reads the two binaries against each other
for exactly that case. The harness measures artifact md5 movement, and a plant
whose whole effect is "this artifact is now byte-identical to another one"
is checked better by comparing them than by digesting frames.

ALSO NOT PLANTED: anything in the base rails' own paths. Every line these
plants touch is inside an `.ifdef`, so `make split_h_demo` and `make
split_h_persp_demo` are byte-identical throughout the run — which is the
property pins and the reason `build` names only the variant target.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
COCKPIT = SUPERFORGE / "game" / "split_h_demo" / "scenes" / "cockpit.asm"
PERSP = SUPERFORGE / "game" / "split_h_persp_demo" / "scenes" / "persp.asm"
SHD_ROM = SUPERFORGE / "build" / "shd_autodemo.sfc"
SHP_ROM = SUPERFORGE / "build" / "shp_autodemo.sfc"

T = "tests/test_autodemo_variants.py::"

SHD_ADVANCE = T + "test_the_shd_pilot_advances_the_floor_and_the_readout_with_no_input"
SHD_RATE = T + "test_the_shd_pilot_steps_once_every_four_frames"
SHD_TURN = T + "test_the_shd_pilot_turn_closes_after_exactly_256_frames"
SHP_ADVANCE = T + "test_the_shp_pilot_runs_both_cameras_with_no_input"
SHP_RATE = T + "test_the_shp_pilot_moves_camera_a_every_frame_and_camera_b_every_eight"

PLANTS = [
    Plant(
        id="shd-autodemo-frozen",
        file=COCKPIT,
        old="""    bne @auto_done
    sep #$20
    .a8
    lda a:US_HEADING
    clc
    adc #ROT_SPD
""",
        new="""    bne @auto_done
    sep #$20
    .a8
    lda a:US_HEADING
    clc
    adc #0                          ; PLANT: the step is zero -> no motion
""",
        artifact=SHD_ROM,
        build=["shd-autodemo"],
        tests=[SHD_ADVANCE, SHD_RATE, SHD_TURN],
        why="A pilot ROM whose script does nothing is the failure a viewer "
            "would hit first and the one a screenshot cannot report, because "
            "a frozen picture of a correct scene looks exactly like a correct "
            "picture. Everything else here still works — the split holds, the "
            "floor renders, the readout shows a heading — so the ONLY witness "
            "is that successive frames stop differing. The step is zeroed "
            "rather than the branch removed so the plant is a value mistake "
            "in the script, not a structural one.",
    ),
    Plant(
        id="shd-autodemo-half-rate",
        file=COCKPIT,
        old="SHD_AUTO_MASK = 3",
        new="SHD_AUTO_MASK = 7               ; PLANT: every 8th frame, not 4th",
        artifact=SHD_ROM,
        build=["shd-autodemo"],
        tests=[SHD_RATE, SHD_TURN],
        why="THE PLANT THIS SET EXISTS FOR. The demo still runs, both bands "
            "still animate, and a human watching it would see a slightly "
            "statelier spin — so the self-advance case is expected to stay "
            "GREEN and is deliberately not listed. What is wrong is the RATE, "
            "and the rate is the whole of the variant's claim: the "
            "reference advances one of 256 angle units per frame, which is one "
            "step of this rail's 64-heading base every four frames. Widening "
            "the mask by one bit is the exact off-by-one an author re-basing "
            "that arithmetic would make, and only the two rate cases can see "
            "it.",
    ),
    Plant(
        id="shp-autodemo-frozen",
        file=PERSP,
        old="""    lda z:SHP_HEAD
    inc a
    and #SHP_HEAD_MASK              ; +1 heading/frame, wrapping: frame mod 64
""",
        new="""    lda z:SHP_HEAD
    and #SHP_HEAD_MASK              ; PLANT: no `inc` -> the heading is stuck
""",
        artifact=SHP_ROM,
        build=["shp-autodemo"],
        tests=[SHP_ADVANCE, SHP_RATE],
        why="On this rail the two cameras are ONE state word — the zoom is "
            "`head >> 3` rather than a second accumulator — so a heading that "
            "stops takes BOTH bands with it. That coupling is what makes the "
            "plant worth running: it proves the two-band assertion is reading "
            "two bands and not one band twice, and it is the shape a dropped "
            "`inc` actually has (the store still happens, the mask still "
            "applies, the picture is still a valid two-camera frame).",
    ),
    Plant(
        id="shp-autodemo-zoom-decoupled",
        file=PERSP,
        old="""    lsr a
    lsr a
    lsr a                           ; head >> 3 == (frame >> 3) & 7
""",
        new="""    lsr a
    lsr a
    lsr a
    lsr a                           ; PLANT: head >> 4 -> every 16, not 8
""",
        artifact=SHP_ROM,
        build=["shp-autodemo"],
        tests=[SHP_RATE],
        why="The 8:1 lock between the two rates, broken and nothing "
            "else. Camera A is untouched and still steps every frame; camera "
            "B still sweeps, still stays inside its 8-pose set, still renders "
            "a correct trapezoid — it simply advances every sixteenth frame "
            "instead of every eighth. The self-advance case cannot see it "
            "(both bands still move), the cycle case cannot see it (>> 4 of a "
            "64-frame heading still closes in 64), and that is precisely why "
            "the rate case asserts the GAP between camera B's changes rather "
            "than the fact of them.",
    ),
]
