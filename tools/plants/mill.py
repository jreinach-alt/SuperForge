"""mill — what mode 4's per-column AXIS can get wrong without looking wrong.

Eight plants. Six are silent-corruption defects that still produce a plausible
picture of a forge, one is the allocator refusing a declaration that lies, and
one is the control's own failure mode. THREE ARE DEFECTS THE RAIL SHIPPED and a
person caught by looking, put here so the next one is caught by the harness
instead.

THE SET IS BUILT AROUND THE THING THIS RAIL ADDS TO `smelter`. Mode 2 fetches a
word for each axis, so a column's axis is not a choice anybody can make wrong.
Mode 4 fetches ONE word and bit 15 picks — so the failures available here are
about WHICH AXIS a column moved on, WHICH column a word reached, and whether a
sprite and the column that should hide it are on the right sides of each other.
Each plant is chosen to fail DIFFERENTLY: a set where everything kills
everything proves only that the ROM boots.

  * `table-column-lead-removed` is the defect the rail SHIPPED. Every bay's
    leftmost column stood still while its neighbours pumped — 30 of 32 columns
    displaced by their neighbour's word — and it read as an animation bug
    rather than a fetch-order one, which is exactly why it survived a look.
  * `axis-bit-forced-vertical` makes every belt word a vertical one. The
    picture still moves and still moves per column; the conveyors simply run
    UP instead of along. Nothing about the frame announces it, and a rail that
    only asserted "the columns move" would ship it.
  * `axis-bit-dropped-from-shafts` is the other direction, and it is the
    subtler of the two: a horizontal word on a row of one repeated tile is
    INVISIBLE, so the machines just stop. A case that read "did this column
    change" would see the stop; only one that reads the AXIS sees why.
  * `the-camera-is-not-folded-in` leaves the blob's own value in every
    vertical word. `vScroll = word & $3FF` REPLACES a column's scroll, so the
    machines stay nailed to the screen while the hall slides past them — a
    defect that is invisible on the first screen and needs the ride to see.
  * `flat-row-clears-the-enable-bits` is the control's failure mode, and the
    same one smelter's set proved out: a flat row built by CLEARING the enable
    bits still levels the picture, because falling back to BGnVOFS lands on
    the same base — while what made it a control is gone, since two things now
    differ between running and flat instead of one.
  * `the-car-override-ignores-the-lead` is the second SHIPPED defect: the
    override in `mil_stage_row` walks TABLE indices and has to carry the lead
    as well. Without it the car's leftmost column stays behind on the shaft
    while the rest of it climbs — a lift with one edge left in the wall.
  * `the-rider-outranks-the-car` is the third, in reverse. Priority 0 is the
    entire occlusion mechanism; raising it puts the whole rider in front of
    the shell instead of only through its glass, and the picture still shows a
    man in a lift.
  * `hall-declares-mode-1` is the allocator half. The scene's video claim is
    what the offset claim is checked against, so moving it to a mode with no
    offset path must stop the BUILD, not the picture.

WHAT IS DELIBERATELY NOT HERE: a plant on the lobby's OAM ordering. The
arrangement is asserted directly by
`test_the_leaves_cover_him_and_he_covers_them`, which reads the OAM indices and
would fail for a trivially locatable reason — a plant would add a second copy
of the same statement without adding a way for it to be wrong.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
GEN = SUPERFORGE / "tools" / "gen_mill_assets.py"
OPT_ASM = SUPERFORGE / "engine" / "features" / "mil_opt" / "mil_opt.asm"
OBJ_ASM = SUPERFORGE / "engine" / "features" / "mil_obj" / "mil_obj.asm"
OPT_TOML = SUPERFORGE / "engine" / "features" / "mil_opt" / "feature.toml"
ROM = SUPERFORGE / "build" / "mill.sfc"
T = "tests/test_mill.py::"

PLANTS = [
    Plant(id="table-column-lead-removed",
          file=GEN,
          old="""        w = column_word(j + LEAD, phase) if j + LEAD < COLS else 0""",
          new="""        w = column_word(j, phase)         # PLANT: the lead undone""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_the_moving_columns_are_the_ones_the_lead_predicts",
              T + "test_a_column_moves_on_the_axis_its_own_word_names",
          ],
          why="THE DEFECT THIS RAIL SHIPPED. The offset words are fetched "
              "after a column's tilemap data, so the word at map index j "
              "displaces SCREEN column j + 1; undoing the compensation moves "
              "every column's displacement one column left. The picture still "
              "pumps and still runs — every bay's LEFTMOST column simply "
              "stands still, and the owner reported it as 'identical sprites "
              "that do not move while the ones to the left are animated', "
              "which is what a fetch-order bug looks like when you are "
              "looking for an animation bug. The lead case is written to "
              "predict the moving set BOTH ways and require the two to "
              "disagree, so it is a test of the fetch order and not of the "
              "picture."),

    Plant(id="axis-bit-forced-vertical",
          file=GEN,
          old="""    return BIT_BG2 | (belt_h(col, phase) & H_MASK)""",
          new="""    return BIT_BG2 | BIT_VSEL | (belt_h(col, phase) & H_MASK)  # PLANT""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_a_column_moves_on_the_axis_its_own_word_names",
              T + "test_the_two_axes_are_honoured_in_the_same_frame",
          ],
          why="every belt word becomes a VERTICAL one. Mode 4 reads bit 15 to "
              "decide which of vScroll and hScroll the single fetched word "
              "lands on (SnesPpu.cpp:156-161), so the conveyors now run UP "
              "instead of along. The picture is still a per-column table "
              "driving thirty-two columns and still moves every frame; only "
              "the AXIS is wrong, and only a case that asserts the axis can "
              "see it. This is the plant that would catch a rail quietly "
              "reverting to smelter-with-a-richer-BG1."),

    Plant(id="axis-bit-dropped-from-shafts",
          file=GEN,
          old="""        return BIT_BG1 | BIT_VSEL | (piston_v(col, phase) & V_MASK)""",
          new="""        return BIT_BG1 | (piston_v(col, phase) & V_MASK)   # PLANT""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_a_column_moves_on_the_axis_its_own_word_names",
              T + "test_the_table_mixes_both_axes_in_one_row",
          ],
          why="the other direction, and the subtler one. A horizontal word on "
              "a row that is one tile repeated across its whole width is "
              "INVISIBLE — which is the invariance the art already obeys — so "
              "the machines simply stop. A case that only asked 'did this "
              "column change' would see a stop and call it an animation "
              "problem; the axis case sees that the word stopped naming the "
              "axis its column's art is built for. The premise case catches "
              "it from the other side, off the ROM alone."),

    Plant(id="the-camera-is-not-folded-in",
          file=OPT_ASM,
          old="""    and #ES_OPT_HALL_MASK
    clc
    adc z:ES_MIL_CAM
    and #ES_OPT_HALL_MASK           ; ...back inside the ten value bits""",
          new="""    and #ES_OPT_HALL_MASK           ; PLANT: the camera is not folded in""",
          artifact=ROM,
          build=["mill"],
          tests=[T + "test_a_vertical_word_carries_the_camera"],
          why="`vScroll = word & $3FF` (SnesPpu.cpp:160) REPLACES a column's "
              "scroll rather than adding to it, so a scrolling world has to "
              "put the camera inside every vertical word. Without the fold "
              "the machines stay nailed to the SCREEN while the hall slides "
              "past them — and the defect is invisible until the camera "
              "moves, which on this rail means until the lift is ridden. Any "
              "case that read a settled frame would survive it."),

    Plant(id="flat-row-clears-the-enable-bits",
          file=GEN,
          old="""def flat_word(col):""",
          new="""def flat_word(col):
    return 0                          # PLANT: a disarm, not a row""",
          artifact=ROM,
          build=["mill"],
          tests=[T + "test_the_flat_control_is_a_row_and_not_a_disarm"],
          why="the control's own failure mode, and the one smelter's set "
              "already paid for. A flat row built by CLEARING the enable bits "
              "still levels the picture — every column falls back to "
              "BGnVOFS, which is where the flat values put them anyway — so "
              "the flat FRAME is identical either way. What is gone is what "
              "made it a control: two things now differ between running and "
              "flat instead of one, and a defect in the transfer would look "
              "the same as a working one."),

    Plant(id="the-car-override-ignores-the-lead",
          file=OPT_ASM,
          old="""    cpx #((SMIL_CAR_COL - SMIL_LEAD) * 2)""",
          new="""    cpx #(SMIL_CAR_COL * 2)         ; PLANT: the override drops the lead""",
          artifact=ROM,
          build=["mill"],
          tests=[T + "test_the_car_moves_as_one_piece"],
          why="THE SECOND DEFECT THIS RAIL SHIPPED, and it is the lead again "
              "in the one place that does not get it from the blob: the car "
              "override walks TABLE indices, so it has to carry the lead like "
              "the table does. Without it the car's leftmost column keeps the "
              "shaft's word and stays behind while the rest of the car "
              "climbs — a lift with one edge left in the wall. The owner "
              "found it by looking; this is so the next one does not have to."),

    Plant(id="the-rider-outranks-the-car",
          file=OBJ_ASM,
          old="""MIL_RIDER_ATTR = (0 << 4)""",
          new="""MIL_RIDER_ATTR = (3 << 4)       ; PLANT: over BG1 instead of under""",
          artifact=ROM,
          build=["mill"],
          tests=[T + "test_the_rider_is_only_visible_through_the_car_s_glass"],
          why="priority 0 is the ENTIRE occlusion mechanism. Mode 4 scores it "
              "2 against BG1's normal 3, so the car's opaque shell hides the "
              "rider and the hole cut for its glass does not "
              "(SnesPpu.cpp:824, :958). At priority 3 he is drawn over "
              "everything: the picture still shows a man in a lift climbing a "
              "shaft, and what is gone is the reason it looked like he was "
              "INSIDE it. No window register was ever involved, so there is "
              "nothing else for a reader to suspect."),

    Plant(id="hall-declares-mode-1",
          file=OPT_TOML,
          old="""name = "mil_mode"
mode = 4""",
          new="""name = "mil_mode"
mode = 1""",
          artifact=ROM,
          build=["mill"],
          expect="build-fails",
          build_names="mode",
          tests=[],
          why="the allocator half. A scene's video claim is what its offset "
              "claim is checked against — mode 1 has no offset-per-tile path "
              "at all — so this must stop the BUILD by name (refusal O2 of "
              "docs/100) rather than produce a picture for a test to "
              "disbelieve. A rail whose mode and whose table disagreed would "
              "otherwise ship a BG3 full of scroll words being drawn as a "
              "text layer."),
]
