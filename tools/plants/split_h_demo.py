"""split_h_demo's four load-bearing mechanisms, each planted and required RED.

The rail is the cockpit horizontal raster-band split,
and its port has exactly four mechanisms a plausible mistake could silently
break. Each plant below reaches RENDERED PIXELS on purpose — the B-3 lesson
from this same wave (a plant whose only effect is through OBJ enable/disable
can be TEST-BLIND, because Mesen's power-on OAM is a fixed parked pattern that
`SetPowerOnSeed` does not reach). A band plant has no such escape: BGMODE and
TM decide what the PPU composites, so a wrong band byte is visible or it is
nothing.

  1. THE TOP BAND'S TM BYTE — `SB_TM_TOP = $04` (BG3 alone). Set it to the
     bottom band's $01 and the top 40 scanlines enable BG1 instead: the
     instrument panel disappears and the floor renders edge to edge. The ROM
     still boots, still spins, still toggles, and the whole tilemap upload is
     still byte-perfect — only the picture is wrong, which is exactly why the
     band cases have to read pixels.

  2. THE TWO BAND TABLES AGREEING — split_band drives BGMODE and TM from two
     SEPARATE tables that must switch on the same line. Push the TM table's
     count 8 lines late and the tables drift: scanlines 40..47 run Mode 7
     (BGMODE switched) with TM still enabling BG3 alone (which does not exist
     in Mode 7), so eight lines of backdrop open up between the bands. A drift
     of exactly one line is the same bug at the resolution the seam cases
     assert.

  3. THE TOGGLE ACTUALLY DISARMING — `hdmaen_apply`'s OFF arm. Give it the ON
     mask and the split never collapses: US_SPLIT_ON still flips, the state
     read still says 0, and the picture never changes. The plant that proves
     the lifecycle case asserts on the FRAME and not on the variable.

  4. THE LIVE MATRIX REBUILD — the NMI hook's pose re-point. Delete it and the
     camera's heading still moves, the readout still tracks it, and the panel
     band is still perfectly stable — the whole "split holds under load"
     claim passes VACUOUSLY, because there is no load. This is the plant the
     sweep case's third arm exists for.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
INC = SUPERFORGE / "game" / "split_h_demo" / "split_h_demo.inc"
BAND = SUPERFORGE / "engine" / "features" / "split_band" / "split_band.asm"
SCENE = SUPERFORGE / "game" / "split_h_demo" / "scenes" / "cockpit.asm"
MAIN = SUPERFORGE / "game" / "split_h_demo" / "main.asm"
ROM = SUPERFORGE / "build" / "split_h_demo.sfc"
T = "tests/test_split_h_demo.py::"

PLANTS = [
    Plant(
        id="shd-top-band-shows-bg1",
        file=INC,
        old="SB_TM_TOP   = $04               ; TM above the seam: BG3 only",
        new="SB_TM_TOP   = $01               ; PLANT: the top band enables BG1",
        artifact=ROM,
        build=["split_h_demo"],
        tests=[
            T + "test_the_seam_is_exactly_at_the_declared_scanline",
            T + "test_the_boundary_rows_are_the_two_bands",
            T + "test_every_panel_scanline_is_panel_only_and_the_ink_is_where_the_rows_are",
            T + "test_the_panel_band_changes_only_in_the_readout_across_the_whole_sweep",
            T + "test_the_split_toggles_off_and_on_and_the_picture_follows",
        ],
        why="the top band's TM byte becomes the bottom band's, so BG1 is "
            "enabled above the seam instead of BG3. Every upload case stays "
            "GREEN — the font, both palettes, the Mode 7 seed and all 1,024 "
            "panel tilemap words are still exactly right — and so does the "
            "toggle's VRAM-identity case and the readout's tilemap case. Only "
            "the five picture cases go red, which is the whole argument for "
            "carrying a per-band mode claim on pixels."),
    Plant(
        id="shd-band-tables-drift-apart",
        file=BAND,
        old="""sb_tm_tab:                          ; indirect: [count, ptr] ... [0]
    .byte SB_LINES""",
        new="""sb_tm_tab:                          ; indirect: [count, ptr] ... [0]
    .byte SB_LINES + 8              ; PLANT: the TM table switches 8 lines late""",
        artifact=ROM,
        build=["split_h_demo"],
        tests=[
            T + "test_the_seam_is_exactly_at_the_declared_scanline",
            T + "test_the_boundary_rows_are_the_two_bands",
            T + "test_the_panel_band_changes_only_in_the_readout_across_the_whole_sweep",
            T + "test_the_split_toggles_off_and_on_and_the_picture_follows",
        ],
        why="split_band drives BGMODE and TM from two separate tables and the "
            "whole mechanism is that they switch on the SAME line. Eight lines "
            "of drift opens a backdrop gap between the bands: the mode has "
            "changed to 7 but TM still names BG3, which Mode 7 does not have. "
            "The panel above the gap is untouched and every non-picture case "
            "stays green, so the reds are exactly the four that locate the "
            "seam — including the review's per-sample seam check, which is what "
            "makes a ONE-line drift under a spinning camera detectable."),
    Plant(
        id="shd-toggle-never-disarms",
        file=SCENE,
        old="""    lda #((1 << ES_H_M7AB_CH) | (1 << ES_H_M7CD_CH))
    sta z:ES_SM_NMI+2           ; HDMAEN shadow: the matrix pair alone""",
        new="""    lda #((1 << ES_H_M7AB_CH) | (1 << ES_H_M7CD_CH) | (1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH))
    sta z:ES_SM_NMI+2           ; PLANT: the OFF arm publishes the ON mask""",
        artifact=ROM,
        build=["split_h_demo"],
        tests=[
            T + "test_the_split_toggles_off_and_on_and_the_picture_follows",
            T + "test_the_anchor_agrees_with_itself",
        ],
        why="the lifecycle's OFF state stops existing while every VARIABLE "
            "still says it happened: US_SPLIT_ON flips 1->0->1->0 exactly as "
            "before, and a test that read it would be green through all four "
            "steps. The two reds are the two cases that look at the frame — "
            "the lifecycle's own picture assertions, and the anchor's "
            "cross-check, which needs the OFF frame to actually be 224 "
            "scanlines of floor. The second red is the load-bearing one: it "
            "means the module cannot even ESTABLISH its anchor from a ROM "
            "whose toggle is a no-op."),
    Plant(
        id="shd-matrix-never-repointed",
        file=MAIN,
        old="""    and #HEAD_MASK              ; A8 load left the high byte stale — mask it
    jsr cockpit::persp_set_pose""",
        new="""    and #HEAD_MASK              ; PLANT: the pose re-point never runs""",
        artifact=ROM,
        build=["split_h_demo"],
        tests=[
            T + "test_the_pose_pointers_the_indirect_channels_fetch_move_with_the_heading",
            T + "test_the_panel_band_changes_only_in_the_readout_across_the_whole_sweep",
        ],
        why="THE VACUITY PLANT. The rail's subject is the split holding under "
            "a live matrix rebuild; delete the rebuild and the split holds "
            "trivially. The camera state still advances, the readout still "
            "tracks it, the seam is still at 40 and the panel band is still "
            "pixel-stable — so the sweep case's first two arms pass and only "
            "its THIRD (the floor band must have changed at every sample) goes "
            "red. A module without that arm would report the strongest "
            "possible green on a ROM that never rebuilt anything, which is the "
            "indirect-evidence failure in its purest form."),
]
