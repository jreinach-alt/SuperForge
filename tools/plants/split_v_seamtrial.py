"""split_v_seamtrial's three load-bearing claims, each planted and required RED.

The rail is the seamless vertical split IN ISOLATION.
Its subject is a picture, so every plant below is chosen to leave a ROM that
still BOOTS, still SWEEPS and still draws a plausible frame — the only surfaces
that can catch any of them are the module's rendered-output assertions. That is
the point: a plant that crashes the ROM proves nothing about the tests.

  1. THE TRIANGLE THAT NEVER TURNS — the sweep pins at SPREAD_MAX and stays
     there. This is defect 5 ("the demo that never demonstrated")
     arriving in the rail whose whole subject is the cycle: every SPLIT frame
     is still correct, the divider is still the right 7px bevel in the right
     tones, and the rail is still self-running. Only the cases that require
     the merge — and the one that walks a whole period — can see it.

  2. THE BAR THAT IS JUST A GREY LINE — the bevel's cross-section flattened to
     one tone. The divider still appears, still ramps 0 -> 3 -> 5 -> 7 px, is
     still full height, still lands in the claimed CGRAM words, and every width
     and presence assertion stays green. Only the case that pins the SHAPE goes
     red. This is defect 6's shape — "the divider still rendered,
     and every 'the divider is present' assertion passed".

  3. THE VIEWPOINT THAT WAS NEVER WRITTEN — enter's one store to ES_SV_MID
     dropped, so the shared viewpoint both cameras straddle is power-on WRAM.
     `tick` never touches that cell (only the DIVERGENCE sweeps), so nothing
     downstream repairs it. The rail still sweeps, the bar still ramps in the
     right tones, the uploads still land; the picture is just of somewhere
     else, and of a DIFFERENT somewhere else per power-on seed. This is the
     plant the two rule-5 seed-invariance cases exist for — a pair a module
     can carry forever without either ever being able to fail.

WHAT WAS TRIED AND IS NOT HERE, because the harness says it cannot fire.
`SVS_TM = $07 -> $17` (OBJ back on the main screen) was plant 3 first: the rail
composes no sprite feature, so its OAM is never written and turning OBJ on
should show power-on garbage. It came back TEST-BLIND, and the reason is a fact
about the harness rather than a hole in the module — **Mesen's power-on OAM is
a FIXED PARKED pattern (`00 f0 00 00` repeating, i.e. every sprite at Y=240,
off-screen), and `SetPowerOnSeed` does not reach it**; measured, both seeds
byte-identical. So an OBJ-on defect draws nothing and no rendered assertion can
see it. Recorded in rather than papered over: the `TM` zero-sprite claim
is real on hardware and unfalsifiable in this harness.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "split_v_seamtrial" / "scenes" / "trial.asm"
GEN = SUPERFORGE / "tools" / "gen_seamtrial_assets.py"
ROM = SUPERFORGE / "build" / "split_v_seamtrial.sfc"
T = "tests/test_split_v_seamtrial.py::"

PLANTS = [
    Plant(
        id="svs-triangle-never-turns",
        file=SCENE,
        old="""    xba                             ; = SVS_SPREAD_MAX in 8.8, exactly
    sta z:US_SPREADF
    lda #1
    sta z:US_SDIR""",
        new="""    xba                             ; PLANT: the phase latch never flips
    sta z:US_SPREADF""",
        artifact=ROM,
        build=["split_v_seamtrial"],
        tests=[
            T + "test_merged_frame_is_one_continuous_picture",
            T + "test_merged_seam_columns_show_terrain_not_a_masked_gap",
            T + "test_merged_frame_carries_no_divider_pixel_anywhere",
            T + "test_frame_to_spread_model_matches_the_picture",
            T + "test_the_sweep_separates_then_merges_then_separates_again",
            T + "test_both_halves_track_their_own_camera_while_closing",
        ],
        why="the sweep opens to SPREAD_MAX and stays. The rail still boots, "
            "still diverges, still draws the full 7px bevel in the right "
            "tones at the right CGRAM words — the SPLIT half of the subject is "
            "untouched and its cases stay green. Six cases go red, and five of "
            "them are about the MERGE: a module that sampled one split frame "
            "and called it proof would ship a rail whose halves never come "
            "back together. defect 5, in the rail that exists to "
            "demonstrate the cycle.",
    ),
    Plant(
        id="svs-bevel-cross-section-flattened",
        file=GEN,
        old="BEVEL_COLS = [2, 2, 1, 1, 3, 3, 3, 2]   # see the docstring's re-indexing",
        new="BEVEL_COLS = [2, 2, 2, 2, 2, 2, 2, 2]   # PLANT: a flat mid bar",
        artifact=ROM,
        build=["split_v_seamtrial"],
        tests=[
            T + "test_divider_cross_section_is_the_source_rails_bar",
        ],
        why="the divider stops being a BEVEL and becomes a grey stripe. It is "
            "still present, still ramps 0/3/5/7 px with the spread, still "
            "reaches every picture row, still reads its palette from the "
            "claimed CGRAM words, and its CHR still matches the blob it was "
            "built from — so the width case, the full-height case, the "
            "presence/absence case and all three upload cases stay GREEN. "
            "Exactly one case names the SHAPE, and this is what proves that "
            "case is load-bearing rather than decorative. Same shape as "
            " defect 6, where a bar in the wrong palette passed "
            "every 'the divider is present' assertion.",
    ),
    Plant(
        id="svs-viewpoint-never-written",
        file=SCENE,
        old="""    lda #SVS_MID_CAM
    sta z:ES_SV_MID                 ; fixed for the whole run: only the""",
        new="""    nop
    nop                             ; PLANT: the viewpoint is power-on WRAM.""",
        artifact=ROM,
        build=["split_v_seamtrial"],
        tests=[
            T + "test_the_picture_is_the_same_under_a_different_power_on_ram",
            T + "test_the_merged_frame_is_the_same_under_a_different_power_on_ram",
        ],
        why="rule 5's write-before-read contract, broken at the one cell `tick` "
            "never repairs: ES_SV_MID is written ONCE, at enter, and the sweep "
            "only ever touches the DIVERGENCE. Remove that store and both "
            "cameras straddle whatever the machine powered on with. Everything "
            "the rail claims about the SPLIT survives — the halves still part "
            "and rejoin on schedule, the bevel is still the right seven "
            "columns in the right tones, all three uploads still land — the "
            "picture is simply of a different place, and of a DIFFERENT "
            "different place per seed. Mesen prints `Uninitialized memory "
            "read: $000011` while it happens. These two cases are the only "
            "ones in the module written for rule 5 and this is what says they "
            "bind.",
    ),
]
