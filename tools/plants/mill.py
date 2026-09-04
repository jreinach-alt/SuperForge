"""mill — what mode 4's per-column AXIS can get wrong without looking wrong.

Twenty-three plants. Twenty are silent-corruption defects that still produce a
plausible picture of a forge (one of them the control's own failure mode), and
THREE are the allocator refusing a declaration that lies. THREE ARE DEFECTS THE
RAIL SHIPPED and a person caught by looking, put here so the next one is caught
by the harness instead.

(The count in this paragraph had gone stale at "eight" while the set grew; it
is a number nothing checks, so treat it as a description of the SHAPE and the
list below as the roll.)

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
  * `table-declares-both-under-mode-4` is the second allocator half, and it is
    the one no picture could ever carry: `both` and `per_column` EMIT THE SAME
    THREE CONSTANTS under mode 4, so the ROM is byte-identical and every
    frame agrees. Only the declaration is wrong — a column displaced on both
    axes at once, which mode 4 has no state for — and only the allocator can
    say so.
  * `tiles16-on-the-layer-the-belts-drive` is the third, and it is a JOIN:
    16x16 tiles on a layer the table drives HORIZONTALLY. One plant carries
    both declarations because neither refuses alone.

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
HALL_ASM = SUPERFORGE / "game" / "mill" / "scenes" / "hall.asm"
BAND_ASM = SUPERFORGE / "engine" / "features" / "mil_band" / "mil_band.asm"
ROM = SUPERFORGE / "build" / "mill.sfc"
T = "tests/test_mill.py::"

PLANTS = [
    Plant(id="table-column-lead-removed",
          file=GEN,
          old="""        w = word_of(j + LEAD) if j + LEAD < COLS else 0""",
          new="""        w = word_of(j)                    # PLANT: the lead undone""",
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
          old="""    and #MIL_OPT_MASK
    clc
    adc z:ES_MIL_CAM
    and #MIL_OPT_MASK           ; ...back inside the ten value bits""",
          new="""    and #MIL_OPT_MASK               ; PLANT: the camera is not folded in""",
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
          old="""    cpy #((SMIL_CAR_COL - SMIL_LEAD) * 2)""",
          new="""    cpy #(SMIL_CAR_COL * 2)         ; PLANT: the override drops the lead""",
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

    Plant(id="collision-tests-one-edge-not-the-box",
          file=OBJ_ASM,
          old="""    .repeat 3
    lsr a                           ; ...his left edge, as a column
    .endrepeat
    tax
    jsr mil_solid
    beq @no""",
          new="""    .repeat 3
    lsr a                           ; PLANT: the left edge is not tested
    .endrepeat
    tax""",
          artifact=ROM,
          build=["mill"],
          tests=[T + "test_he_cannot_walk_into_the_hammer_s_shaft"],
          why="one edge instead of the box. He still stops at a hole and the "
              "picture still looks like collision — he simply stops THIRTY-TWO "
              "PIXELS LATE walking left, standing over the CHANNEL with all but "
              "his right edge past the floor. This is the defect a case that "
              "asserted 'he stops somewhere' would ship; the case asserts the "
              "stop to the pixel against the floor map, which is the only "
              "thing that can tell the two apart. Planted in `mil_can_stand` "
              "rather than in a direction's own branch, because the first cut "
              "of this plant edited the RIGHTWARD branch and the case that "
              "names it walks LEFT — the harness reported TEST-BLIND for a "
              "defect the test never reached."),

    Plant(id="the-lift-is-always-floor",
          file=OBJ_ASM,
          old="""    lda z:ES_MIL_CAR                ; the lift's own columns: ground iff the
    bne @no                         ;   car is at the bottom of its travel""",
          new="""    nop                             ; PLANT: ground whatever the car is doing
    nop""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_he_waits_at_the_shaft_s_edge_for_the_lift",
              T + "test_the_lift_s_columns_are_floor_only_while_the_car_is_down",
          ],
          why="THE DYNAMIC HALF, REMOVED. The lift's columns become permanent "
              "floor, so he walks out over the shaft while the car is at the "
              "top of it. Nothing in a still frame distinguishes the two "
              "cases, because the TILES ARE THE SAME EITHER WAY; what changed "
              "is that the answer no longer comes from the ride's own number. "
              "This plant is also the one that found the mechanism was not "
              "reachable at all: on its first run every named case stayed "
              "green, because the car only ever moved while he was aboard and "
              "could not walk. A lift that never leaves is a bridge, and the "
              "call rule (mil_lift_call) is what the finding bought."),

    Plant(id="the-floor-map-is-not-the-painter-s",
          file=GEN,
          old="""    DECK_COLS.update(range(cx // 8, (cx + w) // 8))""",
          new="""    DECK_COLS.update(range(COLS))     # PLANT: a floor everywhere""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_the_shafts_have_no_floor_and_that_is_the_mechanism_s_price",
              T + "test_he_cannot_walk_into_the_hammer_s_shaft",
          ],
          why="the map stops being the painter's record and becomes a claim "
              "about the art that the art cannot contradict. He walks over "
              "both shafts, on nothing — and the picture does not object, "
              "because a figure over a hole looks exactly like a figure over "
              "a floor when the floor is what you were going to check. The "
              "geometry case catches it off the ROM alone, without a frame."),

    Plant(id="the-doors-open-in-front-of-the-building",
          file=GEN,
          old="""                if r in hi_r and c in hi_c:
                    t |= TILE_HI            # ...the pocket a leaf retracts into""",
          new="""                if False:                # PLANT: no pocket is high
                    t |= TILE_HI""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_a_retracted_leaf_is_hidden_by_the_pier_it_slides_into",
          ],
          why="the defect this rail actually shipped, and the reason it needs "
              "a plant rather than a comment: for six commits the leaves slid "
              "ACROSS the piers instead of into them, and twenty-two cases "
              "passed the whole time because every one of them asked about "
              "the BAY and none about the wall beside it. A lift whose doors "
              "open in front of the building is not subtle once seen, and it "
              "was seen by a person, not by the suite. Without the pocket bit "
              "a leaf at OBJ priority 1 (score 4) beats BG1's normal 3 "
              "everywhere, so the wall stops occluding it and the pixels the "
              "case samples move.",),

    Plant(id="the-new-room-shows-the-old-room-s-pose",
          file=HALL_ASM,
          old="""    jsr mil_rider_stage             ; ...AND THE MAN HIMSELF, for exactly the""",
          new="""    nop                             ; PLANT: the arrival is not staged --
    nop                             ;   three bytes, the width of the jsr, and
    nop                             ;   NOT `.byte 0`: $00 is BRK, which plants
                                    ;   a crash instead of a missing stage""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_the_handover_does_not_show_him_where_the_last_room_left_him",
          ],
          why="OAM is not scene state, and this is the line that says so for "
              "the man rather than for the doors. Without it his entry keeps "
              "the LOBBY's coordinates across the edge: the mill floor fades "
              "up with him standing where the bay was, 18 lit frames measured, "
              "then he snaps onto the car when the tick first runs. The rail "
              "shipped exactly that, under a comment two lines above stating "
              "the principle for the leaves.",),

    Plant(id="the-boarding-snap-and-the-ride-disagree",
          file=OBJ_ASM,
          old="""    lda #SMIL_RIDE_X                ; ...the SAME X the boarding snap uses, or""",
          new="""    lda #(SMIL_RIDE_X + 2)          ; PLANT: the ride stages him 2 px from where he stood""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_he_does_not_shift_when_the_lift_starts_under_him",
          ],
          why="the defect as shipped: two sites each stating where he stands "
              "to ride, three pixels apart, and the picture switching from one "
              "to the other the frame the car moves. A case that reads only "
              "his Y passes on it -- that reading is the one this rail spent a "
              "whole abandoned fix on -- so the case reads both coordinates.",),

    Plant(id="he-breathes-in-the-glass",
          file=OBJ_ASM,
          old="""    lda #0                          ; the standing cell, tile 0""",
          new="""    lda z:ES_MIL_PHASE              ; PLANT: the idle bob, back
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #(SMIL_RIDER_FRAMES - 1)
    asl a
    asl a""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_he_holds_one_pose_for_the_whole_ride",
          ],
          why="the ride as shipped: the pack's two idle frames cycled from "
              "the phase, and they differ by a two-row breath at the head. "
              "With his boots behind the sill, that breath is the only thing "
              "moving in the glass, and it reads as him shifting up a line. "
              "The case reads the rows of his ink that reach the screen, so "
              "a cell whose head sits elsewhere is a moved span.",),

    Plant(id="he-stands-in-front-of-the-car",
          file=OBJ_ASM,
          old="""    lda #MIL_RIDER_ATTR             ; priority 0: behind the car, as riding""",
          new="""    lda #MIL_LOBBY_ATTR             ; PLANT: in front of it, as on the deck""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_standing_on_the_car_is_the_same_picture_as_riding_it",
          ],
          why="the deck staging as shipped, applied on the lift: priority 3 "
              "over BG1, so at rest his cape and boots draw over the sill and "
              "the left wall, and the frame the car moves they drop behind it. "
              "The case counts his ink outside the glass on each sample and "
              "holds his whole OAM entry to one value from rest to riding.",),

    # ---- THE BANDS: the table read three rows at once ----------------------
    Plant(id="the-deck-band-reads-the-ripple-row",
          file=BAND_ASM,
          old="""    ldy #MIL_BAND_ROW_ZERO
    lda z:ES_MIL_NMI_SCRATCH + 14   ; ...the deck: the channel's top less the""",
          new="""    ldy #MIL_BAND_ROW_RIPPLE        ; PLANT: the deck reads the ripple
    lda z:ES_MIL_NMI_SCRATCH + 14   ; ...the deck: the channel's top less the""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_the_hall_reads_three_rows_and_the_deck_band_stands_still",
          ],
          why="band B's entry names the wrong row: the deck ripples with the "
              "channel. The picture still has three bands and a moving "
              "surface, so only a case that asserts the deck band holds "
              "STILL between two frames on which both restaged rows moved "
              "can tell it from the intended picture.",),

    Plant(id="the-channel-band-reads-the-machine-row",
          file=BAND_ASM,
          old="""    ldy #MIL_BAND_ROW_RIPPLE
    lda #SMIL_SCREEN_H              ; ...and the channel: what is left""",
          new="""    ldy #MIL_BAND_ROW_ROOM          ; PLANT: the channel reads the room
    lda #SMIL_SCREEN_H              ; ...and the channel: what is left""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_a_column_carries_an_h_word_in_one_band_and_a_v_word_in_another",
          ],
          why="band C's entry names row 0: the channel shows the machine "
              "row's words, so a belt column's channel art holds still "
              "while the ripple row in VRAM — which the case reads — says "
              "it should slide. The case joins the picture to the words of "
              "the row the band DECLARES, and only that join fails here.",),

    Plant(id="the-ripple-is-staged-from-the-room-s-row",
          file=OPT_ASM,
          old="""    jsr mil_ripple_source           ; ...and the surface's row for it""",
          new="""    jsr mil_row_source              ; PLANT: the room's row, twice""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_a_column_carries_an_h_word_in_one_band_and_a_v_word_in_another",
          ],
          why="the second staged row is a copy of the first, so table row 1 "
              "carries the machine words and no belt column carries a "
              "vertical word in band C — the axis is no longer per band. "
              "The case selects its columns by exactly that property and "
              "refuses to run without them, which is the honest failure.",),

    Plant(id="the-band-channel-is-never-armed",
          file=BAND_ASM,
          old="""    ora #(1 << ES_H_MIL_BANDS_ROWSEL_CH)""",
          new="""    ora #0                          ; PLANT: the bit never reaches HDMAEN""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_the_band_channel_is_the_composition_s_own_and_its_table_is_the_camera_s",
              T + "test_a_column_carries_an_h_word_in_one_band_and_a_v_word_in_another",
          ],
          why="the slot is filled and the table built but the enable bit "
              "never reaches the shadow scene_mgr commits, so the whole frame "
              "reads the seed row — no bands at all. Two cases see it from "
              "two sides: the shadow byte lacks the declared channel's bit, "
              "and the channel band does not follow the ripple words the ROM "
              "restages every frame.",),

    # THE DEFECT THIS RAIL ACTUALLY SHIPPED, planted so it cannot ship twice.
    # The split cap is 96 rather than the hardware's 127 so that every table
    # is at least three entries; at 127 the hall's collapses to two the moment
    # the deck's band and the channel's close, and there the channel drove
    # BG3VOFS not once in the whole picture (docs/100 §14).
    Plant(id="the-split-cap-goes-back-to-the-hardware-s-127",
          file=GEN,
          old="""BAND_MAX = 96
""",
          new="""BAND_MAX = 127                # PLANT: two entries once the lower bands close
""",
          artifact=ROM,
          build=["mill"],
          tests=[
              T + "test_the_band_channel_is_the_composition_s_own_and_its_table_is_the_camera_s",
              T + "test_he_holds_one_pose_for_the_whole_ride",
          ],
          why="the table the ROM builds a third of the way up the shaft is "
              "127 + 97 and no longer at least three entries. The declaration "
              "case derives the entries from the camera and refuses the "
              "two-entry split by name; the ride case sees what it costs, "
              "which is the car and its rider gone off the screen for the "
              "rest of the climb.",),

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

    Plant(id="table-declares-both-under-mode-4",
          file=OPT_TOML,
          # ANCHORED ON THE CLAIM'S OWN `name` LINE, not on `axis` alone: the
          # feature's header PROSE quotes `axis = "per_column"` inside
          # backticks, six lines above the claim, so the bare anchor replaced
          # the COMMENT and left the declaration untouched. The build then
          # accepted the plant and the harness said so — TEST-BLIND, "the
          # build ACCEPTED the plant" — which is the harness reporting a
          # PLANT failure correctly and not a hole in any test.
          old='name = "mil_table"\naxis = "per_column"',
          new='name = "mil_table"\naxis = "both"',
          artifact=ROM,
          build=["mill"],
          expect="build-fails",
          build_names="axis",
          tests=[],
          why="the MIGRATION hazard, and the whole reason `both` and "
              "`per_column` are two names. `both` is a column displaced on "
              "BOTH axes at once and mode 4 has no such state -- one word is "
              "fetched and bit 15 picks -- so this declares something the "
              "hardware cannot do while rendering EXACTLY THE SAME PICTURE, "
              "because the emission is identical under both values (MASK, "
              "HMASK, VSEL). That is what makes it worth planting: no frame "
              "could ever disagree with it, so only the allocator can. It "
              "was a warning until 2026-09-04, and a warning cannot stop a "
              "table moved from mode 2 to mode 4 keeping its declaration and "
              "changing its meaning (refusal O7 of docs/100)."),

    Plant(id="tiles16-on-the-layer-the-belts-drive",
          file=OPT_TOML,
          old='''axis = "per_column"
layers = ["bg1", "bg2"]

# Mode 4: bg1 8bpp + bg2 2bpp. The depths are the reason the art is split into
# two CHR claims at 64 and 16 bytes a tile (mil_bg), and O9 checks each of them
# against this number.
[[claims.video]]
name = "mil_mode"
mode = 4''',
          new='''axis = "h"                       # PLANT: the whole table horizontal...
layers = ["bg1", "bg2"]

# Mode 4: bg1 8bpp + bg2 2bpp. The depths are the reason the art is split into
# two CHR claims at 64 and 16 bytes a tile (mil_bg), and O9 checks each of them
# against this number.
[[claims.video]]
name = "mil_mode"
mode = 4
tiles16 = ["bg2"]                # PLANT: ...and the belts' layer 16x16''',
          artifact=ROM,
          build=["mill"],
          expect="build-fails",
          build_names="16x16 tiles for bg2",
          tests=[],
          why="O11, and it is a JOIN -- 16x16 tiles on a layer the offset "
              "table drives HORIZONTALLY -- so no single-sided plant reaches "
              "it. THIS PLANT CARRIES BOTH SIDES: the table committed to the "
              "horizontal axis, and `tiles16 = [\"bg2\"]` on the video claim "
              "it is joined against. Neither half refuses alone -- mill's own "
              "`per_column` leaves the axis in the WORDS, where the "
              "composition cannot read it, so a bare `tiles16` there only "
              "warns. What the join protects: a 16x16 layer picks its "
              "tilemap ENTRY from the DISPLACED scroll and WHICH HALF of the "
              "16-wide tile from the LAYER's own BGnHOFS (SnesPpu.cpp:195 / "
              ":199 against :235), so a horizontal word of 8 moves an EVEN "
              "screen column by 0 and an ODD one by 16 and the two halves of "
              "every large tile come apart. Measured on a probe build at "
              "30/31 columns; no picture case can carry it on the shipping "
              "tree, because no rail can afford 16x16 on this art "
              "(docs/100 O11)."),
]
