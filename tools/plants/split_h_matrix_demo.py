"""split_h_matrix_demo's four load-bearing mechanisms, planted and required RED.

The rail is the two-camera matrix band, and the shape
of a plausible mistake here is narrow: the whole feature is two HDMA tables and
the six values in them. So the plants attack the four properties that make
those values reach M7A-M7D correctly, and each one has a DIFFERENT blast
radius — which is the evidence that the module's cases are separable rather
than one assertion wearing eleven names.

  1. THE NON-REPEAT COUNT — the pair's headline teaching. Bit 7 set makes the
     controller fetch a NEW unit every scanline, walk off an 11-byte table and
     stream whatever follows into the matrix. Both the table case and every
     picture case must see it; if only the table case did, the module would be
     asserting bytes it wrote rather than pixels the PPU drew.

  2. THE LIVE-BAND OFFSET — `SHM_OFF`, the one parameter by which one feature
     serves two rails. Forcing it to 0 aims every zoom stamp at band 0.

  3. THE TWO TABLES ON THE TWO CHANNELS — AB and CD differ only in WHICH two
     words of their 4-byte unit are zero, so pointing both channels at the AB
     table is a one-symbol slip that leaves a plausible-looking picture right
     up until you look at it (M7D = 0 collapses the vertical step).

  4. THE INIT CONTRACT — `shm_zero`. The DMA controller fetches the bytes AFTER
     a table's terminator on real hardware, and power-on WRAM is random here by
     design (rule 5), so dropping the zero leaves the controller reading RNG.
     The plant is the one that proves the slack assertion is not decoration.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
CAM = SUPERFORGE / "engine" / "features" / "shm_cam" / "shm_cam.asm"
SCENE = SUPERFORGE / "game" / "split_h_matrix_demo" / "scenes" / "bands.asm"
ROM = SUPERFORGE / "build" / "split_h_matrix_demo.sfc"
T = "tests/test_split_h_matrix_demo.py::"

PLANTS = [
    Plant(
        id="shm-repeat-bit",
        file=CAM,
        old="    lda #(lines)\n",
        new="    lda #(128 | (lines))            ; PLANT: bit 7 = REPEAT\n",
        artifact=ROM,
        build=["split_h_matrix_demo"],
        tests=[
            T + "test_every_count_byte_is_non_repeat",
            T + "test_the_whole_picture_is_one_world_through_two_matrices",
            T + "test_the_two_bands_render_two_distinct_checker_periods",
            T + "test_the_seam_is_a_single_scanline_where_the_declaration_puts_it",
        ],
        why="THE NON-REPEAT TRAP, armed. Each entry now re-fetches a 4-byte "
            "unit every scanline, so the channel walks off its own 11-byte "
            "table within four lines and streams the neighbouring table (and "
            "then the WRAM past it) straight into M7A-M7D. The count-byte "
            "case names the bit; the three picture cases prove the bit "
            "reaches the PPU — which is the half that would still be missing "
            "if the module only read back the bytes it wrote."),
    Plant(
        id="shm-live-offset-ignored",
        file=CAM,
        old="    ldx z:SHM_OFF\n",
        new="    ldx #0                          ; PLANT: always band 0\n",
        artifact=ROM,
        build=["split_h_matrix_demo"],
        tests=[
            T + "test_the_whole_picture_is_one_world_through_two_matrices",
            T + "test_the_two_bands_render_two_distinct_checker_periods",
            T + "test_holding_right_zooms_the_live_band_out_pixel_for_pixel",
            T + "test_the_live_band_zooms_out_and_all_the_way_back_in",
        ],
        why="`SHM_OFF` is the ONE parameter that lets `shm_cam` serve a "
            "two-band rail and a three-band one without knowing N, so a stamp "
            "that ignores it is the design's central failure. Every zoom "
            "moves band 0 instead of band 1, and because the seeded scale is "
            "band 2's the damage is visible from the FIRST frame: the top "
            "band boots at 0.25 and the two-period signal is 32/32. The "
            "static-band arm of each zoom case is what names it."),
    Plant(
        id="shm-both-channels-on-the-ab-table",
        file=CAM,
        old="    lda #SHM_TBL_CD\n",
        new="    lda #SHM_TBL_AB                 ; PLANT: CD reads AB's table\n",
        artifact=ROM,
        build=["split_h_matrix_demo"],
        tests=[
            T + "test_shm_arm_stages_both_channels_from_the_emitted_declaration",
            T + "test_the_whole_picture_is_one_world_through_two_matrices",
            T + "test_the_two_bands_render_two_distinct_checker_periods",
        ],
        why="the AB and CD tables differ only in WHICH two words of their "
            "4-byte unit are zero, so aiming both channels at AB is a "
            "one-symbol slip that no amount of reading the tables can catch — "
            "both are correctly built. It puts scale into M7C and 0 into "
            "M7D, which zeroes the vertical step: every scanline of the frame "
            "samples the SAME world row. The staging case names the wrong "
            "A1T; the picture cases prove the register file is what the "
            "picture is made of."),
    Plant(
        id="shm-init-contract-dropped",
        file=SCENE,
        old="    jsr shm_zero\n",
        new="    ; PLANT: the wram claim keeps its power-on garbage\n",
        artifact=ROM,
        build=["split_h_matrix_demo"],
        tests=[
            T + "test_the_table_slack_past_the_terminator_is_zeroed",
        ],
        why="the DMA controller's terminator processing FETCHES the bytes "
            "after the $00 on real hardware, so a table's slack may not be "
            "power-on RNG — and Mesen's power-on RAM is random by design "
            "(rule 5), which is what lets this fail at all. NARROW ON "
            "PURPOSE: the entries themselves are still stamped, so the "
            "picture is unchanged and every other case stays green. That is "
            "the finding — an init-contract violation is invisible to the "
            "rendered frame, which is exactly why it needs a case of its own "
            "rather than being folded into a picture assertion."),
]
