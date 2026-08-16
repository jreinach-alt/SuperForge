"""seam_irq_trial's falsification set — one plant per new behaviour.

The debut's four load-bearing behaviours, each planted as the realistic
defect the mechanism exists to prevent. The controls stay HEALTHY through
every plant (the harness rebuilds only `seam_irq_trial`; `sit_origin` /
`sit_mistime` keep their pre-plant bytes), so a cross-ROM case that goes red
is red about the SUBJECT — which is the direction the trial's comparisons
are built to point.

What each plant proved when this set first ran is recorded in —
including the one whose failure surface is structural rather than visual
(hdmaen-mask: an enabled seam channel's count-0/repeat-count-0 table bytes
are what the picture shows, but the DECLARED detector is the live-$420C
assert, and the plant proves that assert is load-bearing rather than
decorative).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
CAM = SUPERFORGE / "engine" / "features" / "sit_cam" / "sit_cam.asm"
SCENE = SUPERFORGE / "game" / "seam_irq_trial" / "scenes" / "seam.asm"
ROM = SUPERFORGE / "build" / "seam_irq_trial.sfc"
T = "tests/test_seam_irq_trial.py"

PLANTS = [
    # ---- 1. VTIME off by one: the internal-scanline model ------------------
    Plant(
        id="vtime-off-by-one",
        file=CAM,
        old="SIT_VTIME = SIT_SEAM            ; content line 111 draws during internal",
        new="SIT_VTIME = SIT_SEAM - 1        ; PLANT: content line 111 draws during internal",
        artifact=ROM,
        build=["seam_irq_trial"],
        tests=[f"{T}::test_the_seam_row_is_exact_line_111_cool_line_112_warm",
               f"{T}::test_gold_the_irq_build_renders_byte_identical_to_the_hdma_origin_control"],
        why="VTIME counts INTERNAL scanlines and content line L draws during "
            "scanline L+1 — arming SEAM-1 is the natural reading for anyone "
            "who thinks in content lines, and the measurement is exactly "
            "this defect (one full row wrong). The seam-row case must SEE "
            "content line 111 turn warm, and the gold identity must break"),

    # ---- 2. the HBlank spin gate removed -----------------------------------
    Plant(
        id="spin-gate-removed",
        file=CAM,
        old="    bit a:$4212                     ; stalls the CPU, so the fire below always\n"
            "    bvc @spin                       ; lands strictly after that line's HDMA",
        new="    bit a:$4212                     ; PLANT: spin gate removed — the fire\n"
            "    ; bvc @spin                     ; lands mid-render of content line 111",
        artifact=ROM,
        build=["seam_irq_trial"],
        tests=[f"{T}::test_the_seam_row_is_exact_line_111_cool_line_112_warm",
               f"{T}::test_h2_the_fire_lands_in_the_seam_hblank_window"],
        why="without the gate the MDMAEN lands at handler entry (~dot 47 of "
            "scanline 112), mid-render of content line 111 — the lazy flush "
            "renders that line's right side with band 2's origin, and the "
            "fire-completion mirror moves out of the HBlank window. Both "
            "the picture case and the timing case must fire, because a "
            "future 'optimisation' deleting the spin is exactly this edit"),

    # ---- 3. the seam channels wrongly included in the HDMAEN mask ----------
    Plant(
        id="seam-in-hdmaen-mask",
        file=SCENE,
        old="    lda #((1 << ES_H_SITAB_CH) | (1 << ES_H_SITCD_CH))\n"
            ".ifdef SIT_HDMA_ORIGIN\n"
            "    ora #((1 << ES_H_SITXY_CH) | (1 << ES_H_SITHV_CH))\n"
            ".endif",
        new="    lda #((1 << ES_H_SITAB_CH) | (1 << ES_H_SITCD_CH))\n"
            "    ora #((1 << ES_H_SITXY_CH) | (1 << ES_H_SITHV_CH)) ; PLANT: seam bits leaked",
        artifact=ROM,
        build=["seam_irq_trial"],
        tests=[f"{T}::test_the_seam_channels_are_armed_but_not_hdma_enabled"],
        why="the out-of-HDMAEN convention is the schema-field-free "
            "choice, so a falsify plant is its ONLY enforcement: a scene "
            "author extending the mask with 'all my channels' is one ora "
            "away, and the declared detector is the live-$420C structural "
            "assert. (The enabled stage blocks also misparse as HDMA "
            "tables — whatever that does to the picture, the STRUCTURAL "
            "case must fire on the mask alone.)"),

    # ---- 4. the VBlank A1T/DAS re-arm removed (DAS is single-shot) ---------
    Plant(
        id="das-rearm-removed",
        file=CAM,
        old="    lda #SIT_STAGE_XY\n"
            "    sta f:ES_SM_HDMA_LONG+2, x      ; A1T\n"
            "    lda #4\n"
            "    sta f:ES_SM_HDMA_LONG+5, x      ; DAS = 4 (lo+hi)",
        new="    lda #SIT_STAGE_XY\n"
            "    sta f:ES_SM_HDMA_LONG+2, x      ; A1T\n"
            "    ; PLANT: DAS staging removed — the shadow MVN re-arms 0",
        artifact=ROM,
        build=["seam_irq_trial"],
        tests=[f"{T}::test_gold_the_irq_build_renders_byte_identical_to_the_hdma_origin_control",
               f"{T}::test_h2_the_fire_lands_in_the_seam_hblank_window"],
        why="a GP-DMA fire CONSUMES A1T/DAS, and the re-arm here is the "
            "sm_hdma shadow MVN — so a shadow slot with no DAS staged means "
            "the FIRST fire works (sit_rearm_live armed the live register at "
            "boot) and every later frame fires DAS=0 = a 65,536-byte "
            "transfer. The classic DAS-is-single-shot arc: first transfer "
            "moves bytes, the rest silently wreck — the gold identity and "
            "the fire-window mirror must both fire from frame 2 on"),
]
