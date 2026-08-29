"""smelter — offset-per-tile's failure modes, planted.

Fourteen plants, and one RETIRED at the bottom of the file. Twelve are
silent-corruption defects that still produce a plausible picture and two are the
allocator refusing a declaration that lies. One of them found a hole in the test
module on its first run, which is the whole reason this file exists rather than
a list of defects somebody was already confident about; FOUR more are defects
the rail SHIPPED and a person caught, put here so the next one is caught by the
harness instead. The retired one is the other direction entirely — a feature
landing removed the RANGE its defect needed, so the harness reported it blind
and the honest response was to write down why rather than invent a new anchor.

THE LAST THREE ARE THE SCROLLING WORLD'S, added when the rail grew from one
screen to four. `the-read-head-ignores-the-camera` stops the DMA moving along
the world-space row, which is a no-op on the first screen and therefore
invisible to every case that starts from the settled frame.
`the-fallback-carries-column-zeros-melt` is the fourth shipped defect and the
second one a person found by LOOKING: BGnVOFS is not screen column 0's
register, it is every column whose word drives the OTHER layer, so paying off
column 0 with it gave sixteen plate columns one shared melt height belonging to
the left edge. `the-fall-teleports-instead-of-dissolving` puts the respawn back
in the frame the kill fires — the state cycle is unchanged and stays green,
which is the point: the event is a different claim from its endpoints.

THE SET IS BUILT AROUND WHAT A PER-COLUMN TABLE CAN GET WRONG WITHOUT
LOOKING WRONG. A picture where every column has moved to *some* height is the
easiest thing in the world to ship: the melt still erupts, the plates still
bob, and nothing about the frame announces that the columns are one place to
the left, or that half of them are driving the wrong layer. Each plant below
is chosen to fail DIFFERENTLY, because a set where everything kills everything
proves only that the ROM boots.

  * `table-column-lead-removed` undoes the one-column shift the generator
    applies. The picture still moves and still looks like a foundry; every
    column is simply displaced by its NEIGHBOUR's word. It is the defect the
    rail actually shipped once, and the reason the lead is asserted as a
    measurement (a shift of 0 explains the picture and +-1 does not) rather
    than as a comment.
  * `bg1-enable-bit-dropped` clears bit 13 in every plate word, so the plates
    fall back to BG1VOFS and stop moving while the melt carries on. The melt
    cases survive it and should: they are about the OTHER enable bit, out of
    the same 32 words, and a set that killed them too would mean the two
    layers were never independently asserted.
  * `flat-row-clears-the-enable-bits` is the control's own failure mode, and
    it is the one that PAID FOR ITSELF. A flat row built by CLEARING the
    enable bits instead of by lowering the values still levels the picture —
    falling back to BG1VOFS/BG2VOFS lands on exactly the two base values the
    flat row carries — so the flat frame is identical either way, while what
    makes it a control is gone: two things now differ between running and flat
    instead of one. On its first run this plant came back **TEST-BLIND**
    against a module that already read the destination VRAM row, because that
    case reads a RUNNING row. `test_the_flat_row_is_a_row_and_not_a_disarm`
    is what the finding bought.
  * `works-declares-mode-1` is the allocator half. The scene's video claim is
    the thing the offset claim is checked against, so moving it to a mode with
    no offset path must stop the BUILD, not the picture.
  * `bg-text-back-in-globals` is the composition the rail's shape exists to
    make impossible: BG3 as a text layer in a scene where BG3 is the table.
    Also a build refusal, and by a different rule.

THE LAST THREE ARE THE KNIGHT'S, and they are about the claim he is there to
make: that the offset is a position in the world rather than a trick of the
display. Each breaks the link between his feet and the table somewhere
different, and each leaves a picture with a knight on a platform in it.

  * `ride-reads-a-fixed-height` gives him the plate's BASE instead of the
    plate's current height. He stands still, the plate moves under him, and in
    perhaps a fifth of frames he is on it by coincidence. This is the plant
    that says the ride equality is an equality.
  * `the-lava-is-64-rows-lower-than-it-looks` moves the surface the COLLISION
    reads away from the surface the PPU draws, which is the failure mode
    `smt_melt_top` exists to close. He still dies, dissolves and comes back, so
    the state cycle stays green; what he does on the way is sink 64 rows into
    molten metal in full view — and a knight visibly descending into lava reads
    as an animation somebody chose, which is why only a case that joins his
    drawn pixels to the melt's drawn surface in the same frame can see it.
    (`the-knights-y-is-8-8-again` used to sit here. It is RETIRED at the foot of
    this file, because the same sprint that made the lava a collision deleted
    the range that made 9.7 necessary. The reasoning is kept there in full.)
  * `the-32x32-size-bit-dropped` clears one bit of the OAM hi table. The PPU
    draws the top-left quarter of him — a small, complete-looking sprite, in
    the right palette, at the right place — which is exactly the shape of
    failure a "there is a sprite on screen" assertion cannot see.

AND ONE THAT IS ABOUT THE ART RATHER THAN THE MECHANISM.
`the-wall-alternates-per-ROW-again` is the third shipped defect, and the only
one in this file a person found by LOOKING at the clip rather than by running
anything. Every case in the module measured where the crust IS; none measured
what the rest of the column did while it got there, so a wall that slid its
own texture sideways under displacement passed everything. The plant restores
it and the case that now catches it reads a band strictly above the crust.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
GEN = SUPERFORGE / "tools" / "gen_smelter_assets.py"
OPT = SUPERFORGE / "engine" / "features" / "smt_opt" / "feature.toml"
OPT_ASM = SUPERFORGE / "engine" / "features" / "smt_opt" / "smt_opt.asm"
GAME = SUPERFORGE / "game" / "smelter" / "game.toml"
OBJ = SUPERFORGE / "engine" / "features" / "smt_obj" / "smt_obj.asm"
INC = SUPERFORGE / "game" / "smelter" / "smelter.inc"
ROM = SUPERFORGE / "build" / "smelter.sfc"
T = "tests/test_smelter.py::"

PLANTS = [
    Plant(id="table-column-lead-removed",
          file=OPT_ASM,
          old="""    inc a                           ; ...+1: the fetch lead, paid here at the
    asl a                           ;   read head rather than baked in the blob""",
          new="""    asl a                           ; PLANT: the lead undone""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_world_column_under_a_screen_column_is_the_one_that_moves_it",
              T + "test_every_melt_column_stands_where_its_word_says",
              T + "test_every_plate_column_stands_where_its_word_says",
          ],
          why="the defect this rail actually shipped. Undoing the lead moves "
              "every column's displacement one column right, which on a "
              "picture of arches and bobbing plates is invisible: the melt "
              "still erupts, the plates still move, and the only thing wrong "
              "is WHICH column each word drives. The plate cases catch it "
              "because a plate's four columns then include one at the layer's "
              "fallback — the ghost that made the first plate render three "
              "columns wide. THE PLANT MOVED WITH THE MECHANISM: the lead used "
              "to be baked into the generator's table and was planted there; "
              "the world-space table pays it at the DMA'S READ HEAD instead, "
              "so that is where the edit a future author makes now lives. The "
              "rename that came with the move also left this plant pointing at "
              "a test that no longer existed — which the harness reported as "
              "FIRED, because pytest exits non-zero for an unresolvable node "
              "id. tools/falsify.py grew PLANT-NAMES-NO-TEST for it."),

    Plant(id="bg1-enable-bit-dropped",
          file=GEN,
          old="""    return BIT_BG1 | (int(round(v)) & 0x3FF)""",
          new="""    return int(round(v)) & 0x3FF      # PLANT: bit 13 never set""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_every_plate_column_stands_where_its_word_says",
              T + "test_the_plates_are_at_different_heights",
          ],
          why="one enable bit of two, cleared. The plates fall back to "
              "BG1VOFS and stand still; the melt is untouched, because its "
              "columns carry bit 14 out of the same 32 words. MEASURED, NOT "
              "REASONED: every melt case survives this, and that is the "
              "point — it is what says the two layers are asserted "
              "independently rather than through one shared observation."),

    Plant(id="flat-row-clears-the-enable-bits",
          file=GEN,
          old="""    return (BIT_BG1 | PLAT_BASE) if p is not None else (BIT_BG2 | MELT_BASE)""",
          new="""    return 0            # PLANT: a flat row that DISARMS instead""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_flat_row_is_a_row_and_not_a_disarm",
          ],
          why="the CONTROL'S own failure mode, and the one a picture cannot "
              "show. A flat row of zeros still levels every column — falling "
              "back to BG1VOFS/BG2VOFS lands on exactly the two base values "
              "the flat row carries — so what is lost is not the picture but "
              "the ATTRIBUTION: running and flat would then differ in the "
              "values AND in whether the mechanism runs at all, and a "
              "two-variable comparison cannot say which produced the "
              "difference. THE HARNESS FOUND THIS HOLE: on its first run "
              "this plant came back TEST-BLIND against a module that already "
              "read the destination VRAM row, because that case reads a "
              "RUNNING row and the plant only moves the flat one. The "
              "assertion it names now drives the toggle first and checks "
              "every word's ENABLE BIT as well as its value — which is the "
              "assertion a picture-only test set would not have had, and the "
              "one a test set written without a plant did not have either."),

    Plant(id="the-wall-pattern-flows-the-other-way",
          file=GEN,
          old="""        t = (1 - math.cos(2 * math.pi * ((i - k) % WALL_SHADES) / WALL_SHADES)) / 2""",
          new="""        t = (1 - math.cos(2 * math.pi * ((i + k) % WALL_SHADES) / WALL_SHADES)) / 2  # PLANT""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_wall_pattern_flows_one_way_across_the_screen",
          ],
          why="THE DIRECTION, AND NOTHING ELSE. One sign in the rotation, and "
              "the band travels right to left instead of left to right. The "
              "wall still animates; the cycle still closes; the colours are "
              "the same eight, in the same order, at the same rate; every "
              "other case in the module is untouched, INCLUDING the invariance "
              "case, because the pair it compares is matched on the art bytes "
              "and a reversed cycle still produces matching pairs. A viewer "
              "asked for a flow gets one. It is simply the wrong one, and "
              "'the wall changes' cannot tell the difference — which is why "
              "the case this names measures the bright band's COLUMN and "
              "requires every advance to be +1."),

    Plant(id="melt-anim-frame-index-ignores-the-phase",
          file=OPT_ASM,
          old="""    lda z:ES_SMT_PHASE
    .repeat ::SMT_MELT_ANIM_SHIFT""",
          new="""    lda #0                          ; PLANT: frame 0, every frame
    .repeat ::SMT_MELT_ANIM_SHIFT""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_melt_chr_in_vram_is_the_frame_the_rom_holds",
              T + "test_the_melt_churns_while_every_column_stands_still",
          ],
          why="the CHR swap, still firing and still moving the right number "
              "of bytes into the right place — at the same frame every time. "
              "THE PICTURE IS ENTIRELY PLAUSIBLE: the lava simply stops "
              "churning, and a running frame still moves for the other reason, "
              "because every column is being displaced by the table exactly as "
              "before. That is why the case this names drives the FLAT control "
              "first: with the columns standing still, the melt is either "
              "changing or it is not, and there is nothing else it could be. "
              "A transfer that fires, lands, and carries a constant is the "
              "shape a `vblank_bytes_per_frame` budget cannot see either."),

    Plant(id="the-wall-stops-being-vertically-uniform",
          file=GEN,
          old="""    row = [WALL_IX0 + ((k * 8 + x) // WALL_PX_PER_SHADE) % WALL_SHADES
           for x in range(8)]
    return [list(row) for _ in range(8)]""",
          new="""    return [[WALL_IX0 + ((k * 8 + x + y) // WALL_PX_PER_SHADE) % WALL_SHADES
             for x in range(8)] for y in range(8)]   # PLANT: tilted""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_wall_does_not_move_when_its_column_does",
          ],
          why="THE DEFECT CLASS A HUMAN CAUGHT, expressed against the art "
              "that replaced it. The original was a map alternating two streak "
              "phases per MAP ROW under a vertically uniform tile — a "
              "horizontal seam every 8 pixels, so a displaced column slid it "
              "past the screen and the streaks jumped sideways as the melt "
              "rose. That exact edit is no longer possible: the wall's pattern "
              "moved into its PALETTE and there is only one wall tile left, so "
              "there is no alternation to reintroduce. The class survives the "
              "redesign though — anything that puts a horizontal feature in "
              "the wall does it — so the plant now tilts the TILE itself, "
              "which is the same defect through the one door still open. "
              "EVERY OTHER CASE IN THE MODULE STAYS GREEN under it, including "
              "the flow case: the band still travels, one column per step, "
              "left to right. Every case measures where the crust IS, and only "
              "the one this names measures what the rest of the column does "
              "while it gets there."),

    Plant(id="ride-reads-a-fixed-height",
          file=OBJ,
          old="""    jsr smt_plate_top               ; A = the plate's top edge, screen px
    sec""",
          new="""    jsr smt_plate_top               ; A = the plate's top edge, screen px
    lda #(SMT_PLAT_TOP_PX - SMT_PLAT_BASE - SMT_ROW_BIAS)  ; PLANT: the base
    sec""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_knight_stands_on_the_word_the_rom_holds",
              T + "test_the_knight_rides_the_plate_rather_than_hovering_over_it",
          ],
          why="THE SPRITE'S WHOLE CLAIM, cut at the one line that carries it. "
              "The knight's height stops coming from the table and becomes the "
              "plate's resting level, so he stands at a fixed row while the "
              "plate rises and falls through him — and roughly a fifth of the "
              "time he is standing on it correctly, because the plate passes "
              "its own base twice a cycle. A case that sampled one frame would "
              "pass this. The ride case samples six across the harmonic and "
              "requires the equality at every one, which is what makes it a "
              "ride rather than a coincidence. It leaves the FLAT control "
              "green on purpose: flat is the one state where the base IS the "
              "right answer."),

    Plant(id="the-32x32-size-bit-dropped",
          file=OBJ,
          old="""    ora #SMT_KN_SIZE_LARGE""",
          new="""    ; PLANT: no size bit — the PPU draws his top-left quarter""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_knight_is_the_sprite_the_oam_entry_describes",
          ],
          why="one bit of the OAM hi table, and the picture keeps a sprite in "
              "it: the PPU draws the 16x16 top-left quarter of him, in the "
              "right palette, at the right coordinates, standing at the right "
              "height. 'A sprite is on screen' cannot see this and neither can "
              "'his palette appears in the frame'. The entry says 32x32 and the "
              "pixels have to fill it, which is why that case reads OAM AND the "
              "picture and joins the two."),

    Plant(id="works-declares-mode-1",
          file=OPT,
          old="""[[claims.video]]
name = "smt_mode"
mode = 2""",
          new="""[[claims.video]]
name = "smt_mode"
mode = 1                 # PLANT: a mode with no offset path""",
          artifact=ROM,
          build=["smelter"],
          expect="build-fails",
          build_names="Offset-per-tile exists in modes [2, 4, 6] ONLY",
          why="the mode constraint, which is one of the two things the "
              "capability map said could not be expressed at all. The picture "
              "under mode 1 would be a perfectly ordinary flat foundry — the "
              "table would sit in VRAM, uploaded every frame, and the PPU "
              "would never read a word of it — so nothing downstream could "
              "tell this from a table that happened to be flat. It has to "
              "stop the BUILD, and the message has to name the mode."),

    Plant(id="bg-text-back-in-globals",
          file=GAME,
          old="""globals = ["scene_mgr", "fade", "input", "text_dp", "font_rom",
           "smt_bg", "smt_rom", "oam_sprites", "region", "tick_scale",
           "mosaic"]""",
          new="""globals = ["scene_mgr", "fade", "input", "text_dp", "font_rom",
           "bg_text",                    # PLANT: BG3 drawn where it is data
           "smt_bg", "smt_rom", "oam_sprites", "region", "tick_scale",
           "mosaic"]""",
          artifact=ROM,
          build=["smelter"],
          expect="build-fails",
          build_names="BG3 IS THIS SCENE'S OFFSET TABLE, not a drawable layer",
          why="the OTHER thing the capability map said could not be "
              "expressed: a text feature and an offset-per-tile feature both "
              "believing they own BG3. Before the vocabulary this composed "
              "green. It is planted at the one line that makes it happen — "
              "moving `bg_text` from the title scene into the globals — "
              "because that is the edit a future author makes without "
              "thinking, and the refusal is what has to catch it."),

    Plant(id="the-read-head-ignores-the-camera",
          file=OPT_ASM,
          old="""    sta z:ES_SMT_NMI_SCRATCH + 2    ; the camera's own column, for below
    inc a""",
          new="""    sta z:ES_SMT_NMI_SCRATCH + 2    ; the camera's own column, for below
    lda #0                          ; PLANT: the read head never leaves home
    inc a""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_same_agreement_holds_with_the_camera_off_zero",
          ],
          why="SCROLLING, REMOVED, AND THE FIRST SCREEN IS UNTOUCHED. The "
              "layers still scroll — the H ports carry the camera four "
              "instructions later — and the transfer still fires the same 64 B "
              "into the same place. Only the READ HEAD stops moving, so every "
              "frame past the first screen displaces its columns by the words "
              "belonging to world columns 1..32. The picture is a foundry with "
              "plates and jets in it, and the plates are simply not where the "
              "platforms are. EVERY OTHER CASE IN THIS MODULE SURVIVES IT, "
              "because every other case starts from the settled frame where "
              "the camera is zero and the plant is a no-op — which is the "
              "whole reason the case it names exists."),

    Plant(id="the-fallback-carries-column-zeros-melt",
          file=OPT_ASM,
          old="""    lda #SMT_VOFS_BG2               ; the melt's own base, for every column""",
          new="""    lda z:ES_SMT_NMI_SCRATCH        ; PLANT: column 0's word, for everyone
    and #ES_OPT_WORKS_MASK
    ; the melt's own base, for every column""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_melt_behind_every_plate_is_one_calm_level",
          ],
          why="THE DEFECT THIS RAIL SHIPPED AND A PERSON SAW, restored. A word "
              "carries one enable bit, so a plate column displaces BG1 and "
              "leaves BG2 at BG2VOFS — and BG2VOFS is not column 0's register, "
              "it is EVERY plate column's. Loading it with column 0's own word "
              "to pay off the column the hardware cannot displace paid for one "
              "column with sixteen: the lava behind all four platforms rose "
              "and fell together in the left edge's rhythm, at a different "
              "rate from the jets beside it, and snapped to the base whenever "
              "the camera put a plate under column 0. THE PICTURE IS ENTIRELY "
              "PLAUSIBLE — it is lava, and it moves — which is why it shipped "
              "and why every other case here stays green under it: all of them "
              "measure where the crust is in the columns the TABLE drives, and "
              "not one measured the columns it does not."),

    Plant(id="the-fall-teleports-instead-of-dissolving",
          file=OBJ,
          old="""    ldx #.loword(smt_kn_respawn)
    jsr mosaic_arm""",
          new="""    jsr smt_kn_respawn              ; PLANT: the one-frame cut, again""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_fall_dissolves_the_picture_before_it_gives_him_back",
          ],
          why="the respawn back in the frame the kill fires, which is where it "
              "was. He still dies, he still comes back, he still comes back ON "
              "THE SPAWN PLATE at the ride equality — so the state cycle case "
              "stays green and should, because the state cycle is not what "
              "broke. What breaks is that the player cannot SEE it happen: he "
              "blinks from the bottom of the world to the start with nothing "
              "in between. The case this names is the only one that reads the "
              "event rather than its endpoints, and it reads it as the "
              "picture ceasing to be explicable by the table while the mosaic "
              "smears it, then becoming explicable again."),

    Plant(id="the-lava-is-64-rows-lower-than-it-looks",
          file=OPT_ASM,
          old="""    lda #(SMT_CRUST_TOP_PX - SMT_ROW_BIAS)""",
          new="""    lda #(SMT_CRUST_TOP_PX - SMT_ROW_BIAS + 64)  ; PLANT: too low by 64""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_he_sinks_into_the_lava_and_leaves_only_once_he_is_under",
          ],
          why="THE SURFACE THE COLLISION READS, moved away from the surface "
              "the PPU draws — which is the whole failure mode `smt_melt_top` "
              "exists to close, expressed as the bias error that would "
              "reintroduce it. The knight still dies, still dissolves, still "
              "comes back on the spawn plate, so the state cycle case stays "
              "green; what he does on the way is sink 64 rows into the molten "
              "metal in full view, which is exactly what the rail shipped "
              "before the lava was a collision at all. A PLAUSIBLE PICTURE: "
              "lava is not opaque in most games, and a knight visibly "
              "descending into it reads as an animation somebody chose. The "
              "case this names is the only one that joins his drawn pixels to "
              "the melt's drawn surface in the same frame, which is the only "
              "place the two can be shown to be the same number."),

    Plant(id="the-melt-takes-him-on-contact",
          file=OBJ,
          old="""    sbc #SMT_KN_TOP                 ; ...the lowest top edge still showing him""",
          new="""    sbc #SMT_KN_BOTTOM              ; PLANT: his FEET — contact, not under""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_he_sinks_into_the_lava_and_leaves_only_once_he_is_under",
          ],
          why="THE FIRST VERSION OF THIS FEATURE, restored, and it is a "
              "PLAUSIBLE picture — he touches the lava and dies, which is what "
              "most games do. What it costs is the whole point of the melt "
              "having an animation: the death becomes one frame long, he never "
              "descends into anything, and the three-second hold has nothing "
              "to show. One constant apart from the shipped version, and the "
              "case that separates them is the one asserting he had pixels "
              "BELOW the surface before he left."),

    Plant(id="the-hold-is-counted-in-frames",
          file=OBJ,
          old="""    sbc z:US_TSC""",
          new="""    dec a                           ; PLANT: one per FRAME, not per tick""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_melt_holds_him_under_before_it_wipes",
          ],
          why="the frame-assumption class the `tick-check` lint exists for "
              "(docs/96), planted where the lint cannot see it: a decrement is "
              "not a frame COUNT and reads as ordinary arithmetic. Counting the "
              "hold in frames instead of in the scaled phase step makes it "
              "67 frames rather than 179 — a bit over one second instead of "
              "three, which looks like a design choice and not a defect — and "
              "on PAL it would be a different duration again, which is exactly "
              "what expressing it in the scaled unit buys. The case this names "
              "derives the expected length from the rail's own constants, so "
              "it fails on the RATIO rather than on a number typed twice."),

    Plant(id="the-wall-band-is-one-pixel-a-shade-again",
          file=GEN,
          old="""    row = [WALL_IX0 + ((k * 8 + x) // WALL_PX_PER_SHADE) % WALL_SHADES
           for x in range(8)]""",
          new="""    row = [WALL_IX0 + ((k * 8 + x) // 1) % WALL_SHADES   # PLANT
           for x in range(8)]""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_wall_band_is_as_wide_as_the_rail_declares",
          ],
          why="THE ART AND ITS DECLARATION, pulled apart. The tiles go back to "
              "one pixel a shade while the emitted SMT_WALL_PX_PER_SHADE still "
              "says four — which matters beyond the look, because the FLOW case "
              "divides the brightest pixel by that constant to name the shade "
              "it belongs to. Diverge them and that case is measuring in a unit "
              "the picture does not use, and its pass says nothing. The picture "
              "under this plant is the wall the rail actually shipped: a "
              "travelling band with an 8-px period, which is a legitimate "
              "animation and reads as shimmer rather than as flow — a LOOK "
              "defect that no correctness assertion in this module could have "
              "seen, which is why the case it names measures the run widths "
              "against the number the .inc emits rather than against taste."),
]


# ==========================================================================
# RETIRED — kept as the trail, not run
# ==========================================================================
# A plant that stops landing is a finding about the TREE, not litter, and the
# right response depends on which half of it died. When the defect CLASS
# survives an edit that deleted its anchor, the plant is re-expressed against
# whatever door is still open — `the-wall-stops-being-vertically-uniform` is
# that case. When the class's PRECONDITION is gone, re-expressing it would be
# inventing a defect, and the honest move is to retire it with the reason
# written down.
#
# `the-knights-y-is-8-8-again` is the second kind, and what retired it is a
# feature landing rather than a fix.
#
#   It restored the vertical unit the rail shipped first. At 8.8 the knight's Y
#   could not span both ends of his movement: a jump's apex is genuinely above
#   the screen while a miss carried him past row 232, and in 8.8 row 232 and row
#   -24 are the same bit pattern — the kill test read a fall as "above the
#   screen", skipped the kill, and wrapped him to the top. 9.7 settled it, and
#   this plant existed so it was not found by hand twice.
#
#   THE LAVA BEING A COLLISION DELETED THE RANGE. He no longer falls to a fixed
#   row near the bottom of the picture; `smt_melt_top` takes him at the melt's
#   own surface, and the LOWEST that surface can sit is the melt's base — row
#   129 — so the deepest his top edge ever reaches is 129 - SMT_KN_BOTTOM = 101.
#   With -50 at the apex, his whole range is about -50..+101, which 8.8 (-128..
#   +127) represents exactly. Every constant scales off SMT_KN_ONE_PX, so the
#   two units now produce identical behaviour, and the harness said so: the
#   plant reached the artifact and the case stayed green. TEST-BLIND, correctly.
#
#   The unit STAYS 9.7. It costs nothing and it is headroom. What would make it
#   load-bearing again is anything that lets him past row 127 — a taller world,
#   a lower melt base, a death that is a fall out of the picture again — and at
#   that point this plant is the one to bring back rather than rewrite.
RETIRED = """
    Plant(id="the-knights-y-is-8-8-again",
          file=INC,
          old='''SMT_KN_FRAC  = 7''',
          new='''SMT_KN_FRAC  = 8         ; PLANT: the unit the rail shipped first''',
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_walking_off_the_span_drops_him_and_the_world_gives_him_back",
          ],
          why="A DEFECT THIS RAIL SHIPPED, restored. At 8.8 the knight's Y "
              "cannot hold both ends of his own movement: the highest plate "
              "puts a jump's apex genuinely above the screen, so the kill test "
              "has to read the sign — and screen row 232 has the same sign bit "
              "as row -24. He falls past the bottom of the world, the kill is "
              "skipped, and he WRAPS ROUND to the top of the screen instead of "
              "respawning. Every other case stays green, including the ride and "
              "the jump, because nothing else in the rail ever reaches a row "
              "that big. It took a person walking him off the edge to find it "
              "the first time; this is the plant that means it is not found "
              "that way twice."),

"""
