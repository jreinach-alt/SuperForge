"""mode7_chamber's load-bearing mechanisms, each planted and required RED.

The rail is FOUR COOPERATING PER-SCANLINE EFFECTS over one Mode 7 plane
, and it debuts `m7_barrel`. The set is chosen so
each mechanism falls on its OWN — a set that only ever broke the whole picture
at once could not tell whether any individual case was doing work.

ALL FOUR EFFECTS ARE COVERED, which took a remediation pass to become true.
The set shipped with the binding contract, the bow (twice), the split and the
roll — leaving the other two per-scanline columns unplanted while the
docstring above already claimed the coverage. `m7c-persp-is-a-linear-ramp`
and `m7c-vignette-on-one-plane` close them, one per channel:

    m7_barrel   M7A  the bow          m7c-bow-step-ignored, m7c-tail-span-…
    m7_barrel   M7D  the perspective  m7c-persp-is-a-linear-ramp
    split_band       the mode split   m7c-split-lands-late
    rgb_gradient     the vignette     m7c-vignette-on-one-plane
    m7c_roll         the motion       m7c-roll-never-reverses

EVERY PLANT REACHES RENDERED PIXELS, or refuses the build and says which
symbol. This rail draws no sprites at all, so nothing here can be blind the
way an OBJ-only plant is (the seam-in-isolation rail's finding: Mesen's power-on OAM is a
fixed parked pattern `SetPowerOnSeed` does not reach).

THE BINDING PLANT IS THE FEATURE-DEBUT ONE. `m7_barrel` carries NO defaults —
the includer supplies `MB_SEAM` and a missing one is a named `.error` — which
is the standing rule ("the undefined-symbol error is the design review")
applied to a new feature. That argument is worth nothing unless the error
arrives, and arrives NAMING the symbol. `m7c-seam-unbound` is the evidence,
and `expect="build-fails"` is what makes the harness require ca65 to name it
rather than accept any failure.

NOT PLANTED, deliberately:
  * the size .asserts in m7_barrel.asm (`MB_BOWS * MB_POSE_BYTES =
    ES_R_BOW_A_SIZE`). Breaking the geometry is refused at ASSEMBLE time, so
    the defect never reaches a ROM and the plant would say nothing about the
    tests — docs/46's whole point, and the ruling
    tools/plants/split_h_persp_demo.py took on the band-priority contract.
  * the oracle gate in tools/gen_chamber_assets.py. It refuses at GENERATE
    time and its own falsification is that it has two arms (a map that
    disagrees is a refusal; an absent oracle is a refusal) — a plant here
    would only re-prove `sys.exit`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
BARREL = SUPERFORGE / "engine" / "features" / "m7_barrel" / "m7_barrel.asm"
ROLL = SUPERFORGE / "engine" / "features" / "m7c_roll" / "m7c_roll.asm"
WORLD = SUPERFORGE / "game" / "mode7_chamber" / "world.inc"
GEN = SUPERFORGE / "tools" / "gen_chamber_assets.py"
ROM = SUPERFORGE / "build" / "mode7_chamber.sfc"
T = "tests/test_mode7_chamber.py::"

# A GENERATOR-SIDE PLANT MUST NOT MOVE WHAT THE TEST READS AS THE DECLARATION.
# tests/test_mode7_chamber.py imports this generator as its oracle, so planting
# inside `persp_column()` or `vignette_intensity()` would move the prediction
# and the ROM together and the case would stay green by tautology — the
# self-referential shape CLAUDE.md rule 2 is about. Both generator plants below
# therefore sit on the EMIT path (`main`'s blob, `build_vignette`'s plane
# bytes) and leave the declared table the test reads untouched.

PLANTS = [
    # --- the feature debut's binding contract ------------------------------
    Plant(
        id="m7c-seam-unbound",
        file=WORLD,
        old="MB_SEAM     = 32",
        new="; PLANT: binding omitted  MB_SEAM = 32",
        artifact=ROM,
        build=["mode7_chamber"],
        tests=[],
        expect="build-fails",
        build_names="m7_barrel: MB_SEAM undefined",
        why="a rail that forgets the seam is the exact mistake a no-defaults "
            "binding contract bets on catching at assembly time. The bet is "
            "only good if ca65 names MB_SEAM rather than failing later inside "
            "an index-table count with a range error — and `mode7_persp` "
            "reaches for a bare `HUD_LINES` instead, which would bind by "
            "accident on a rail that happens to define it",
    ),

    # --- the bow axis: the pointer that IS the runtime parameter ------------
    Plant(
        id="m7c-bow-step-ignored",
        file=BARREL,
        old="""mb_point:
    .a16
    .i16
    lda z:MB_BOW""",
        new="""mb_point:
    .a16
    .i16
    lda #0                          ; PLANT: the step is ignored""",
        artifact=ROM,
        build=["mode7_chamber"],
        tests=[T + "test_the_floor_bows_row_by_row_as_the_declared_m7a_column_says",
               T + "test_the_bow_is_a_bulge_and_not_a_ramp",
               T + "test_holding_down_flattens_the_bow_and_holding_up_restores_it",
               T + "test_the_bow_step_reaches_the_hdma_index_table_the_dma_"
                   "controller_fetches"],
        why="the whole of m7_barrel's parameter space is one multiply into "
            "three pointers. Freezing it at step 0 leaves a build that runs, a "
            "floor that renders, a perspective that recedes and a roll that "
            "rolls — and NO barrel. It is the shape warns about "
            "(a table-driven feature whose domain is smaller than the demand) "
            "arriving as a silent regression rather than as a schedule error",
    ),

    Plant(
        id="m7c-tail-span-reads-the-head",
        file=BARREL,
        old="""    clc
    adc #(MB_HEAD * 2)
    sta f:MB_IDX_A_LONG + 7         ; floor rows 127..end""",
        new="""    clc
    adc #0                          ; PLANT: the tail span re-reads the head
    sta f:MB_IDX_A_LONG + 7         ; floor rows 127..end""",
        artifact=ROM,
        build=["mode7_chamber"],
        tests=[T + "test_the_floor_bows_row_by_row_as_the_declared_m7a_column_says",
               T + "test_the_bow_step_reaches_the_hdma_index_table_the_dma_"
                   "controller_fetches"],
        why="an HDMA index table's second span has to be offset by the units "
            "the first one consumed. Getting it wrong replays the top of the "
            "bow across the bottom third of the floor — a defect that leaves "
            "the picture PLAUSIBLE (still bowed, still receding) and is exactly "
            "why the bow case predicts every row rather than sampling three",
    ),

    # --- the perspective column: the OTHER matrix channel -------------------
    Plant(
        id="m7c-persp-is-a-linear-ramp",
        file=GEN,
        old="    persp = persp_column()",
        new="""    persp = persp_column()          # PLANT: the EMITTED column is a
    _last = len(persp) - 1          # linear ramp between the same two
    persp = [round(MB_SCALE_FAR + (MB_SCALE_NEAR - MB_SCALE_FAR) * k / _last)
             for k in range(len(persp))]""",
        artifact=ROM,
        build=["mode7_chamber"],
        tests=[T + "test_the_rendered_recession_follows_the_declared_"
                   "perspective_column"],
        why="the D channel had no falsification at all, and the case that "
            "looked like its proof could not have one: "
            "`test_the_perspective_column_recedes_monotonically` asserts the "
            "endpoints and monotonicity of a PYTHON list, and this plant "
            "satisfies both — same first row, same last row, still monotone — "
            "so that case stays GREEN while every scanline of the floor "
            "recedes wrongly. What is planted is a WRONGLY-SHAPED D "
            "column, not a dead one, which is the half no indirect argument "
            "covered. The rendered case sees it because it predicts all 192 "
            "floor rows from the declared hyperbola and this ramp misses "
            "well over half",
    ),

    # --- the mode split -----------------------------------------------------
    Plant(
        id="m7c-split-lands-late",
        file=WORLD,
        old="SB_LINES    = MB_SEAM                   ; the seam: Mode 1 rows 0..31",
        new="SB_LINES    = MB_SEAM + 8               ; PLANT: the split lands late",
        artifact=ROM,
        build=["mode7_chamber"],
        tests=[T + "test_a_clean_mode_1_band_sits_above_the_mode_7_floor"],
        why="split_band's seam and m7_barrel's are the same number for a "
            "reason — the horizon IS the mode split. Moving one and not the "
            "other leaves eight scanlines of Mode 7 floor inside the band the "
            "rail calls clean, which is the reference rail's own 'no smear' "
            "criterion failing by the smallest amount that could ship",
    ),

    # --- the vignette: three COLDATA planes that must be THREE --------------
    Plant(
        id="m7c-vignette-on-one-plane",
        file=GEN,
        old='PLANE = (0x20, 0x40, 0x80)  # COLDATA plane-select bits (R, G, B)',
        new='PLANE = (0x20, 0x20, 0x20)  # PLANT: all three tables select RED',
        artifact=ROM,
        build=["mode7_chamber"],
        tests=[T + "test_the_vignette_matches_the_declared_intensity_line_"
                   "for_line"],
        why="this rail spends THREE channels where one COLDATA byte would do, "
            "on the reading that $2132's plane bits gate three "
            "disjoint fields — so the decision is exactly a binding that can "
            "be wrong silently, and it was the fourth effect with no plant "
            "at all. Selecting one plane on all three tables leaves the "
            "vignette's SHAPE intact: the middle of the picture is still "
            "brighter than the top and the bottom, so "
            "`test_the_middle_of_the_frame_is_brighter_than_the_top_and_the_"
            "bottom` stays GREEN. What breaks is that the ramp is no longer "
            "NEUTRAL — the floor's grey mortar rows come back tinted, and only "
            "the line-for-line case, which reads each uniform row's actual "
            "colour against the declared intensity, can say so. docs/46's "
            "argument in one plant: an unfalsified assertion is unproven, and "
            "the shape-only case is not a substitute for it",
    ),

    # --- the roll's reverse arm ---------------------------------------------
    Plant(
        id="m7c-roll-never-reverses",
        file=ROLL,
        old="""    lda z:US_DIR
    eor #1
    sta z:US_DIR                        ; flip direction""",
        new="""    lda z:US_DIR
    eor #0                              ; PLANT: the direction never flips
    sta z:US_DIR                        ; flip direction""",
        artifact=ROM,
        build=["mode7_chamber"],
        tests=[T + "test_the_floor_rolls_both_ways"],
        why="a rail whose motion only ever goes one way is the state-cycle "
            "rule's canonical failure, and it is INVISIBLE to any single-frame "
            "picture: the floor still rolls, the hold still holds, and only a "
            "test that drives the reverse arm can see it. The reference rail's "
            "two LFSR streams exist precisely because the two directions are "
            "meant to be different",
    ),
]
