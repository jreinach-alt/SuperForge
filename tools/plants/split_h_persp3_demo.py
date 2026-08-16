"""split_h_persp3_demo's three band-count mechanisms, planted and required RED.

The sibling rail's plant set attacks `shm_cam` — the feature both rails share.
This one attacks the only thing that distinguishes THIS rail from that one:
its band list. rules row 12 "a band-count parameter" of row 11,
and if that ruling is right then the three plants below are the complete set
of ways to get a three-band rail wrong that a two-band rail cannot suffer.

  1. THE THIRD BAND ITSELF — deleted, which is the rail reduced to its
     sibling. It must not pass as one.
  2. A SEAM MOVED — the band list still has three entries summing to 224, so
     the build's own `.assert` is satisfied and the table is well-formed. Only
     the picture knows where the seams belong.
  3. THE LIVE SLOT — `SHM_LIVE_SLOT`, this rail's ONE differing line of scene
     code (2 rather than the sibling's 1). Set it to the sibling's value and
     the pad drives the middle band.

Each is a change a careless "port the sibling" would make, and each has a
different signature in the picture.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "split_h_persp3_demo" / "scenes" / "bands.asm"
ROM = SUPERFORGE / "build" / "split_h_persp3_demo.sfc"
T = "tests/test_split_h_persp3_demo.py::"

PLANTS = [
    Plant(
        id="shp3-third-band-dropped",
        file=SCENE,
        old="    SHM_BAND 2, SHM_B3_LINES, SHM_SCALE_C\n"
            "    SHM_END  SHM_BANDS_N\n",
        new="    ; PLANT: the third camera is gone\n"
            "    SHM_END  SHM_BANDS_N - 1\n",
        artifact=ROM,
        build=["split_h_persp3_demo"],
        tests=[
            T + "test_both_hdma_tables_are_the_declared_three_band_list",
            T + "test_every_count_byte_is_non_repeat",
            T + "test_the_whole_picture_is_one_world_through_three_matrices",
            T + "test_three_bands_render_three_distinct_periods_in_the_declared_order",
            T + "test_both_seams_are_single_scanlines_where_the_declaration_puts_them",
        ],
        why="the rail reduced to its two-band sibling. The table terminates "
            "after entry 1, so the channel ENDS at scanline 150 and the "
            "write-twice latch holds band 2's matrix to the bottom of the "
            "frame — the picture is 8 / 32 / 32 with ONE seam. It is a "
            "perfectly coherent two-camera frame, which is the point: the "
            "third band's absence is not a crash, it is a rail that looks "
            "like the one next door, and only the period ORDER and the "
            "second seam tell them apart."),
    Plant(
        id="shp3-second-seam-moved",
        file=SCENE,
        old="SHM_SEAM2    = 150\n",
        new="SHM_SEAM2    = 160              ; PLANT: the seam slid 10 lines\n",
        artifact=ROM,
        build=["split_h_persp3_demo"],
        tests=[
            T + "test_both_hdma_tables_are_the_declared_three_band_list",
            T + "test_the_whole_picture_is_one_world_through_three_matrices",
            T + "test_three_bands_render_three_distinct_periods_in_the_declared_order",
            T + "test_both_seams_are_single_scanlines_where_the_declaration_puts_them",
        ],
        why="the band list still has THREE entries whose heights still sum "
            "to 224, so the scene's own build-time `.assert` is satisfied and "
            "the tables are well-formed — the counts are simply 75 / 85 / 64. "
            "Nothing about the mechanism is broken; the geometry is just "
            "wrong. Only a test that knows WHERE the seams are declared can "
            "see it, which is why the module re-derives 75 and 150 from the "
            "reference header instead of reading them back out of the ROM."),
    Plant(
        id="shp3-live-slot-is-the-siblings",
        file=SCENE,
        old="SHM_LIVE_SLOT = 2\n",
        new="SHM_LIVE_SLOT = 1               ; PLANT: the sibling's slot\n",
        artifact=ROM,
        build=["split_h_persp3_demo"],
        tests=[
            T + "test_the_whole_picture_is_one_world_through_three_matrices",
            T + "test_three_bands_render_three_distinct_periods_in_the_declared_order",
            T + "test_holding_right_zooms_the_bottom_band_out_pixel_for_pixel",
            T + "test_the_bottom_band_zooms_out_and_all_the_way_back_in",
        ],
        why="THE ONE LINE OF SCENE CODE THIS RAIL DOES NOT SHARE with its "
            "sibling, set to the sibling's value — the copy-paste this rail's "
            "whole structure invites. Every VBlank stamps band 3's scale into "
            "band 2's entry, so the middle band boots at 0.5 (16 px, band 3's "
            "period) and the pad drives it instead. Three distinct periods "
            "become two, from frame one, and the zoom cases' static-band arms "
            "name the band that moved."),
]
