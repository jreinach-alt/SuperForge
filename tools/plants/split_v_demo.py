"""split_v_demo's four teachings, each planted and required RED.

The rail is the vertical window dual-view, and its
reference source names exactly four things it teaches — with three of them
reachable only from `-D` variant builds. The SuperForge port makes two of those
runtime modes, so all four live in ONE binary, and each one gets a plant that
switches it off in the most plausible way available:

  1. THE SPLIT AND ITS BAR — `svd-w12sel-band-dropped`. The win2 term on BOTH
     W12SEL nibbles is what cuts the backdrop channel between the halves, and
     it is the single easiest thing to leave out of this recipe (split_v_bg's
     own file says so in as many words). Drop it and the split still works
     perfectly: two cameras, two halves, the right seam column — and no bar,
     because BG1 and BG2 now cover the band between them.

  2. TWO CAMERAS — `svd-camb-folded-onto-cama`. BG2HOFS published from camera
     A. One stage, one camera, drawn twice. Note WHICH case survives this:
     `test_converged_cameras_compose_ONE_continuous_picture` stays GREEN, and
     must — a folded camera IS a converged camera. That is the whole reason
     the boot frame is predicted from BOTH cameras separately.

  3. THE DIAGONAL SEAM — `svd-diag-table-not-repointed`. The mode's arm sets
     its window state and forgets to repoint A1T/A1B at the ROM table, so the
     channel keeps reading the straight seam's 11-byte WRAM table. The exact
     copy-paste mistake the two-table design invites, and the failure is
     silent: a perfectly good vertical seam in the mode whose subject is that
     it slants.

  4. PER-HALF OBJ CLIPPING — `svd-objclip-tmw-obj-bit-dropped`. WOBJSEL set,
     TMW's OBJ bit not. This is a HARDWARE-semantics plant rather than a
     clerical one: a BG/OBJ layer's window is gated by TMW (Mesen2
     SnesPpu.cpp:980-981) — only the colour-math window bypasses it — so
     WOBJSEL alone is inert and the clip mode renders identically to the
     straight one. Everything about the sprite is right; nothing cuts it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
BG = SUPERFORGE / "engine" / "features" / "svd_bg" / "svd_bg.asm"
ROM = SUPERFORGE / "build" / "split_v_demo.sfc"
T = "tests/test_split_v_demo.py::"

PLANTS = [
    Plant(
        id="svd-w12sel-band-dropped",
        file=BG,
        old="""SVD_W12SEL_BG1 = SVD_W1_INSIDE | SVD_W2_INSIDE
SVD_W12SEL_BG2 = SVD_W1_OUTSIDE | SVD_W2_INSIDE""",
        new="""SVD_W12SEL_BG1 = SVD_W1_INSIDE
SVD_W12SEL_BG2 = SVD_W1_OUTSIDE""",
        artifact=ROM,
        build=["split_v_demo"],
        tests=[
            T + "test_the_seam_bar_is_the_backdrop_on_every_active_scanline",
            T + "test_the_boot_frame_is_the_predicted_two_camera_picture",
            T + "test_the_seam_sweeps_both_ways_and_clamps_at_both_bounds",
            T + "test_the_diagonal_slants_the_seam_per_scanline",
        ],
        why="the win2 term dropped from both W12SEL nibbles: BG1 and BG2 "
            "cover the band, so the CGRAM-0 backdrop never shows and the "
            "seam bar disappears. The SPLIT is untouched — two cameras, two "
            "halves, the seam in the right column — which is what makes this "
            "the plant worth running: every upload case, the OAM case and "
            "the nowin control stay green, and only the cases that read the "
            "bar's pixels go red."),
    Plant(
        id="svd-camb-folded-onto-cama",
        file=BG,
        old="""    lda z:ES_SVD_CAM + 2
    sta a:$210F                     ; BG2HOFS, low  (camera B — the right half)
    lda z:ES_SVD_CAM + 3
    sta a:$210F                     ; BG2HOFS, high""",
        new="""    lda z:ES_SVD_CAM + 0
    sta a:$210F                     ; PLANT: BG2HOFS published from camera A
    lda z:ES_SVD_CAM + 1
    sta a:$210F""",
        artifact=ROM,
        build=["split_v_demo"],
        tests=[
            T + "test_the_boot_frame_is_the_predicted_two_camera_picture",
            T + "test_camera_b_pans_both_ways_and_moves_only_the_right_half",
        ],
        why="one camera drawn twice. The screen still splits, the bar is "
            "still there, P2's pad still moves a variable — the picture just "
            "stops depending on it. test_converged_cameras stays GREEN and "
            "MUST: a folded camera is a converged camera, and a module that "
            "only ever asserted the merged property would ship this. The two "
            "cases named are the ones that predict the halves from the two "
            "cameras SEPARATELY."),
    Plant(
        id="svd-diag-table-not-repointed",
        file=BG,
        old="""    ldx #SVD_CH
    lda #^svd_diag_tab_bin
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B — the blob's linker bank
    rep #$20
    .a16
    lda #.loword(svd_diag_tab_bin)
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T""",
        new="""    ldx #SVD_CH
    lda #ES_SVD_TAB_BANK
    sta f:ES_SM_HDMA_LONG + 4, x    ; PLANT: the arm forgot to repoint A1B
    rep #$20
    .a16
    lda #ES_SVD_TAB
    sta f:ES_SM_HDMA_LONG + 2, x    ; PLANT: ...and A1T""",
        artifact=ROM,
        build=["split_v_demo"],
        tests=[
            T + "test_the_diagonal_slants_the_seam_per_scanline",
            T + "test_the_mode_cycle_runs_in_both_directions",
        ],
        why="the diagonal mode reads the STRAIGHT seam's table. The channel "
            "is armed, the mode word advances, the window state is applied — "
            "the seam is simply vertical in the mode whose whole subject is "
            "that it is not. The failure is silent by construction (a "
            "straight seam is a valid picture), so only a per-scanline "
            "assertion on the bar's centre can see it: a midscreen sample "
            "passes on both tables."),
    Plant(
        id="svd-objclip-tmw-obj-bit-dropped",
        file=BG,
        old="""    lda #SVD_TMW_BG_OBJ
    sta a:$212E                     ; TMW: BG1|BG2|OBJ — WOBJSEL is inert""",
        new="""    lda #SVD_TMW_BG
    sta a:$212E                     ; PLANT: WOBJSEL armed, TMW's OBJ bit not""",
        artifact=ROM,
        build=["split_v_demo"],
        tests=[
            T + "test_the_obj_clip_cuts_the_straddling_marker_and_hides_the_far_one",
            T + "test_the_obj_clip_is_invisible_to_oam",
            T + "test_the_mode_cycle_runs_in_both_directions",
        ],
        why="the hardware trap this rail's fourth teaching sits on: a BG/OBJ "
            "layer's window is gated by TMW (SnesPpu.cpp:980-981), so "
            "WOBJSEL without TMW's OBJ bit is inert and the clip mode renders "
            "exactly like the straight one. OAM is byte-identical in both "
            "(that is the point of test_the_obj_clip_is_invisible_to_oam), so "
            "nothing but the drawn pixels can tell the two apart — a sprite "
            "test would report this working."),
]
