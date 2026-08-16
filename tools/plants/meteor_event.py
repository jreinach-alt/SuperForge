"""meteor_event — the cutscene rail's falsification set (docs/46).

Eight plants across everything this rail brings that the debut did not: the
BG->OBJ capture (emitted at all / aligned / bounded / sequenced), the rail's
own baked scale ramp's cursor, the glow's PLANE, the sprite phase's flip
cycle, and the parked 32x32 sprite's size bit. `m7_track` itself is NOT
re-planted here — the uniform-scale negate already has a plant in
tools/plants/boss.py, on the feature that owns it, and a second copy would
test the debut's code from a second rail rather than test anything of this
one's.

Five of the eight are the shapes the reference ships non-vacuity controls for:
-DNO_CAPTURE (plant 1), -DNO_SCALE (plant 5), -DNO_GRADIENT's sibling
(plant 6), -DNO_TUMBLE's reachable half (plant 7), and the alignment its
capture test exists to prove (plant 2). Two more are defects this rail
actually hit and fixed, replanted so the tests that caught them stay honest
(plants 4 and 8). One is the declared OAM bound (plant 3), which is the thing
 row 24 says nothing declares.

WHAT IS DELIBERATELY NOT HERE, and both are measured rather than assumed:

  * a plant that WIDENS the capture's slot bound (deleting the
    `cmp #ES_O_CAPTURE_SPRITES` guard). The shipping level emits 36 blocks
    against a claim of 40, so removing the guard changes no rendered byte —
    the harness would report the TESTS as blind rather than the plant as
    caught, which is a true statement about an unreachable path and not a
    finding (docs/46's plant-vs-test distinction). The guard is planted in the
    direction that IS reachable instead: narrowed, so it truncates.

  * a plant that SETS CGADSUB BIT 4 to pull OBJ into the colour math. It was
    written, it was run, and the harness returned TEST-BLIND — correctly, and
    the reason is hardware. Mesen2's `Core/SNES/SnesPpu.cpp:962` gates an OBJ
    pixel's colour math on BOTH the bit and the palette:

        _mainScreenFlags[x] = spritePrio |
            (((_state.ColorMathEnabled & 0x10) && _spritePalette[x] > 3)
             ? PixelFlags::AllowColorMath : 0);

    Colour math reaches an OBJ pixel only from palettes 4..7, and this rail's
    entire cast is OBJ palette 0 (met_obj claims exactly sixteen CGRAM words
    at 128). So bit 4 is unreachable here: the exclusion normally written as
    one bit is enforced TWICE on this composition, and no assertion of any
    kind can distinguish the bit's two values. The reachable half of the same
    mechanism — the plane the wash actually writes — is plant 6 instead.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
LEVEL = SUPERFORGE / "game" / "meteor_event" / "scenes" / "level.asm"
IMPACT = SUPERFORGE / "game" / "meteor_event" / "scenes" / "impact.asm"
GLOW = SUPERFORGE / "engine" / "features" / "met_glow" / "met_glow.asm"
ROM = SUPERFORGE / "build" / "meteor_event.sfc"

T = "tests/test_meteor_event.py::"

PLANTS = [
    Plant(
        id="capture-emits-nothing",
        file=LEVEL,
        old="""    lda a:ES_BG_SHADOW, x           ; what the PPU is displaying, read back
    and #((1 << 10) - 1)            ; the CHR index (low 10 bits of the word)
    cmp #MET_BG_PLAT""",
        new="""    lda a:ES_BG_SHADOW, x
    and #((1 << 10) - 1)
    cmp #MET_BG_BLANK               ; PLANT: matches the SKY, never a platform""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[T + "test_the_capture_hands_the_ground_from_bg_to_obj_pixel_exactly",
               T + "test_the_capture_fills_exactly_the_declared_oam_claim"],
        why="disabling the capture is the obvious control here, and it says what "
            "it must break: 'when ST_CAPTURE blacks the Mode-1 BG the ground "
            "band VANISHES to black'. Comparing the tilemap word against the "
            "wrong tile id is how it happens for real — the level's sky IS "
            "tile 0 and its ground IS tile 1, one digit apart. The pixel "
            "equality test sees the whole level's green disappear the frame "
            "the BG drops; the OAM test sees zero live blocks instead of 36",
    ),
    Plant(
        id="capture-stride-halved",
        file=LEVEL,
        old="""    lda z:US_CAP_SC
    .repeat 3
        asl                         ; sc * 8
    .endrepeat
    sec
    sbc z:US_CAP_SUBX""",
        new="""    lda z:US_CAP_SC
    .repeat 2
        asl                         ; PLANT: sc * 4 — the tile stride, halved
    .endrepeat
    sec
    sbc z:US_CAP_SUBX""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[T + "test_the_capture_hands_the_ground_from_bg_to_obj_pixel_exactly"],
        why="the alignment half, and the reason a capture test "
            "exists at all: the blocks are still emitted, still the right "
            "count, still the right tile — they just land on the wrong "
            "pixels. A narrated tile stride (a shift count) is exactly how "
            "that slips, and no OAM-count or tile-id assertion can see it. "
            "The whole-frame pixel equality across the handover is the only "
            "surface that can, which is why that test compares 61,184 pixels "
            "rather than a region",
    ),
    Plant(
        id="capture-bound-narrowed",
        file=LEVEL,
        old="""    lda z:US_CAP_N
    cmp #ES_O_CAPTURE_SPRITES
    bcs @rows_done                  ; the claim is full: stop, never overrun""",
        new="""    lda z:US_CAP_N
    cmp #20                         ; PLANT: a NARRATED bound, not the claim's
    bcs @rows_done""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[T + "test_the_capture_fills_exactly_the_declared_oam_claim",
               T + "test_the_capture_hands_the_ground_from_bg_to_obj_pixel_exactly"],
        why=" row 24 files this rail as 'medium' because the capture's "
            "OAM cost is 'bounded by nothing declared', and the usual "
            "bound is a COMMENT that is off by a column ('4 rows x 16 "
            "block-cols = 64 max', against a loop that walks "
            "17). Replacing the emitted claim symbol with a hand-written "
            "number is that defect exactly. Both named tests fire: the OAM "
            "test counts 20 live blocks where 36 are expected, and the pixel "
            "equality test sees the untruncated part of the ground go black",
    ),
    Plant(
        id="black-and-capture-same-tick",
        file=LEVEL,
        old="""    lda z:US_G_TIMER
    bne @maybe_black
    jsr capture_emit                ; ONE pass; the blocks then stand
    bra @hold
@maybe_black:""",
        new="""    lda z:US_G_TIMER
    bne @maybe_black
    jsr capture_emit
    jsr bg_black                    ; PLANT: both in ONE tick
    bra @hold
@maybe_black:""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[T + "test_the_capture_hands_the_ground_from_bg_to_obj_pixel_exactly"],
        why="the defect this rail actually shipped for one commit, replanted "
            "so the test that caught it stays honest. The OAM shadow a tick "
            "writes is DMA'd by that frame's VBlank and lands in the NEXT "
            "frame's picture, while the TM write takes effect in the tick's "
            "own — so doing both together leaves exactly one frame with the "
            "BG gone and the blocks not yet committed. Measured planted: a "
            "9,216-pixel black hole, precisely the area of the level's green. "
            "One frame is invisible to any state read and to any OAM read; "
            "only a frame-by-frame picture comparison across the handover "
            "sees it",
    ),
    Plant(
        id="grow-cursor-frozen",
        file=IMPACT,
        old="""    M7T_BIND ::met_grow_bin
    lda z:US_G_SCR
    jsr ::m7t_apply""",
        new="""    M7T_BIND ::met_grow_bin
    lda #0                          ; PLANT: the cursor never advances
    jsr ::m7t_apply""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[T + "test_the_matrix_track_matches_the_generator_at_every_frame",
               T + "test_the_mode7_meteor_grows_in_place_and_slides_off_the_bottom_right"],
        why="this rail's own half of the track contract: m7_track holds "
            "NO cursor, so a consumer that stops indexing renders a frozen "
            "matrix under a counting clock — 'the ramp is wired but nothing "
            "grows'. It is also the obvious no-scale control ('the "
            "meteor holds the crossover scale and never gets bigger'), and "
            "and a grow test needs the pre-glow window for a "
            "clean separation, which is where this rail's samples sit. Both "
            "named tests fire: the whole-shadow oracle mismatches from the "
            "first Mode-7 frame, and the rendered meteor's pixel count stops "
            "increasing",
    ),
    Plant(
        id="glow-writes-the-blue-plane",
        file=GLOW,
        old="""    ora #MET_COLDATA_R              ; the R plane-select bit, every byte""",
        new="""    ora #(1 << 7)                   ; PLANT: the BLUE plane-select bit""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[T + "test_the_glow_rises_and_recedes_over_the_sky_band"],
        why="$2132 is ONE port for three planes and bits 5/6/7 choose which "
            "of R/G/B the low five bits land on, which is why met_glow's "
            "claim names COLDATA_R rather than COLDATA. Nothing checks the "
            "DATA bytes against that claim — the allocator derives the BBAD "
            "from the declaration and the plane bit rides inside the payload "
            "— so a wrong plane-select bit builds clean, arms clean, ramps on "
            "exactly the declared schedule, and paints the impact glow BLUE. "
            "Every timing assertion stays green against it; only a test that "
            "reads the COLOUR of the wash can tell, which is why this one "
            "counts pixels whose RED channel exceeds both others rather than "
            "counting 'pixels that changed'",
    ),
    Plant(
        id="sprite-flip-cycle-pinned",
        file=IMPACT,
        old="""    lda z:US_G_SCR
    and #3
    stz z:US_G_SCR                  ; rebuild it as the attribute bits""",
        new="""    lda #0                          ; PLANT: the flip index pinned at 0
    and #3
    stz z:US_G_SCR""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[T + "test_the_sprite_phase_speck_sweeps_in_and_grows_then_hands_over"],
        why="the no-tumble control, on the half it can reach. OBJ "
            "cannot rotate, so the sprite phase's ENTIRE rotation is the "
            "flip cycle — {normal, H, V, H+V} every 7 frames, 'so the "
            "off-centre craters reorient frame-to-frame (an illusion of "
            "spin)' — and it lives in two OAM attribute "
            "bits that no position, tile, size or pixel-count assertion "
            "touches. Pinned, the speck still sweeps, still grows through the "
            "six frames, still hands over: every other assertion in the named "
            "test stays green and the meteor simply stops turning. The four "
            "attribute samples are what see it. The AFFINE half of the same "
            "control is already covered elsewhere and deliberately not "
            "duplicated here: the tumble rides the baked track's angle, so a "
            "dropped affine ramp fires the whole-shadow matrix oracle at the "
            "first Mode-7 frame",
    ),
    Plant(
        id="meteor-park-keeps-size",
        file=IMPACT,
        old="""    jsr meteor_hi_clear
    ldx #(ES_O_METEOR * 4)
    jsr ::met_park_slot""",
        new="""    ldx #(ES_O_METEOR * 4)          ; PLANT: park WITHOUT clearing the size
    jsr ::met_park_slot""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[T + "test_the_sprite_phase_speck_sweeps_in_and_grows_then_hands_over"],
        why="the second defect this rail actually hit. MET_PARK_Y is 240, "
            "which is off the 224-line screen for a 16x16 sprite and NOT for "
            "a 32x32 one: rows 240..271 wrap, and the bottom sixteen render "
            "at screen y 0..15. So a crossover that parks the rocky frame "
            "without clearing its hi-table size bit leaves a slice of meteor "
            "in the top-left corner for the whole Mode-7 phase — visible, "
            "and invisible to every OAM y assertion, because the y really is "
            "the park value. The test asserts both the size bit AND that no "
            "meteor colour is on the rows the wrap would use",
    ),
]
