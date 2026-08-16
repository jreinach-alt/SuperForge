"""scene_mgr's cut transition — the falsification set (docs/46).

A SET OF ITS OWN rather than four more rows in tools/plants/meteor_event.py,
and the reason is what each set is about. That set plants defects in the
METEOR RAIL: its BG->OBJ capture, its baked scale ramp, its glow's plane, its
sprite tumble — things only meteor_event has. These four plant defects in
`scene_mgr` and in the DECLARATION MACHINERY that selects its transition
style, which every rail composes. meteor_event is merely the one rail that
declares `style = "cut"` today, so it is the artifact these build; the next
rail to declare a cut inherits this set unchanged, and would inherit nothing
useful from a row filed under the cutscene's capture.

The four cover the two directions the work item's brief names, plus the two
refusals the design leans on:

  1. THE VISIBLE REGRESSION the cut exists to prevent — a cut edge silently
     running the fade machine.
  2. THE BYPASS the tie leaves open. SM_SWITCH resolves the entry point from
     the declared style, so a rail cannot say "fade" and call the cut THROUGH
     THE MACRO; what it can still do is not use the macro. Plant exactly that
     and require the test to see it.
  3. THE DECLARATION ITSELF, as a one-word edit to game.toml. Nothing else
     changes — no ASM, no test — and the harness's own "the artifact md5 must
     MOVE" step is then the proof that `style` reaches the binary. This is the
     plant that would have been impossible before this work: the word used to
     be consumed by a report string, so flipping it moved nothing.
  4. THE UNDECLARED EDGE, as a build refusal. SM_SWITCH's `.error` is the
     reason a scene cannot request a transition the game.toml never declared,
     and an `.error` that never fires is a comment.

WHAT IS DELIBERATELY NOT HERE:

  * a plant that flips `style` to a NONSENSE value to prove the enum refuses.
    It belongs at the layer it lives in and is already asserted there —
    tests/test_schemas.py::test_edge_with_unknown_style_rejected calls
    load_manifest directly, which is faster, names the SchemaError, and does
    not need a ROM to exist. Routing it through the ROM build would prove the
    same thing twice and more slowly.

  * a plant that removes the `.if SF_SM_CUT` guards so the cut path assembles
    into every ROM. It was considered and it is not a falsification: nothing
    in the cut path RUNS unless an edge declares a cut, so the defect it
    models is "the pinned ROMs' bytes moved", and that is not a test's job to
    catch — `make gates` prints both pin md5s, and this harness's own restore
    step re-checks the artifact byte-for-byte. A plant whose only witness is a
    number a human reads is a plant with no test to go red.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE_MGR = SUPERFORGE / "engine" / "features" / "scene_mgr" / "scene_mgr.asm"
LEVEL = SUPERFORGE / "game" / "meteor_event" / "scenes" / "level.asm"
GAME_TOML = SUPERFORGE / "game" / "meteor_event" / "game.toml"
ROM = SUPERFORGE / "build" / "meteor_event.sfc"

T = "tests/test_scene_mgr_cut.py::"
CUT_FWD = T + "test_a_cut_edge_renders_no_intermediate_brightness[edge0]"
CUT_BACK = T + "test_a_cut_edge_renders_no_intermediate_brightness[edge1]"
DECLARED = T + "test_the_two_meteor_edges_are_declared_cut"

PLANTS = [
    Plant(
        id="cut-path-reenables-fade",
        file=SCENE_MGR,
        old="""    lda #$80
    sta z:ES_SM_NMI+1           ; INIDISP shadow = forced blank (NMI commits)
    lda #4
    sta z:ES_SM_CTL+2           ; phase = CUT switch (after one more VBlank)""",
        new="""    lda #1                      ; PLANT: the cut edge runs the FADE machine
    sta z:ES_SM_CTL+2
    jsr fade_start_out""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[CUT_FWD, CUT_BACK],
        why="the regression this work exists to prevent, in the shape it "
            "would really take: `sm_request_cut` still EXISTS, still gets "
            "called from the declared-cut edges, and quietly does what "
            "`sm_request` does. Everything else about the rail is unchanged — "
            "the scenes swap, the capture holds, the cutscene runs, the cycle "
            "closes — so all twelve of tests/test_meteor_event.py stay green "
            "against it, which is the point: 30 frames of ramp reappear on "
            "both swaps and only a test that reads the PICTURE during the "
            "switch window can tell. The colour-set predicate sees it because "
            "master brightness rescales every channel, so a dimmed frame's "
            "colours are in neither steady-state picture",
    ),
    Plant(
        id="sm_switch-bypassed-at-a-cut-edge",
        file=LEVEL,
        old='    SM_SWITCH "LEVEL", "IMPACT"',
        new="""    lda #1                          ; PLANT: the macro bypassed — a
    jsr ::sm_request                ;   hand-written id + the FADE entry
                                    ;   point, at an edge declared "cut" """,
        artifact=ROM,
        build=["meteor_event"],
        tests=[CUT_FWD],
        why="THE BYPASS ANALYSIS, mechanised. SM_SWITCH ties the declaration "
            "to the path at assembly time, so an edge declared \"fade\" "
            "cannot reach the cut through the macro and an undeclared edge "
            "cannot be requested at all — but a rail that already has one cut "
            "edge can still hand-write `jsr ::sm_request` at a cut edge's "
            "site, and nothing structural stops it. That is the residual hole "
            "the design report names, so it is planted rather than asserted "
            "away. Note what stays green: the ROM builds, no gate objects, "
            "the edge still declares \"cut\" in game.toml and in the emitted "
            "map, and the rail plays through — a declaration that lies, with "
            "the picture as the only witness. The forward-edge case is the "
            "one that fires; the return edge is untouched by this plant, and "
            "its staying green is itself the evidence that the plant is "
            "narrow rather than a rail-wide break",
    ),
    Plant(
        id="declared-style-flipped-to-fade",
        file=GAME_TOML,
        old="""[[edge]]
from = "level"
to = "impact"
style = "cut\"""",
        new="""[[edge]]
from = "level"
to = "impact"
style = "fade"      # PLANT: the declaration alone, nothing else""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[CUT_FWD, DECLARED],
        why="the load-bearing test for `style` itself, and the one plant here "
            "that could not have been written before this work: on the old "
            "tree the word was parsed into EdgeDecl and consumed by a single "
            "report string, so editing it changed no emitted symbol and no "
            "ROM byte. Now the allocator emits ES_E_LEVEL_TO_IMPACT_CUT from "
            "it and SM_SWITCH resolves against that, so this ONE WORD — no "
            "ASM touched, no test touched — moves the artifact md5 and puts "
            "the 30-frame ramp back on the forward swap. (Measured "
            "separately, and it is the sharper statement of the same fact: "
            "flipping BOTH edges rebuilds meteor_event.sfc to "
            "f0568ff3e5ce1a08b25966ef7e3e69ed, the exact pre-work item ROM. This "
            "plant flips one, so its artifact is a third value.) The "
            "harness's own step 3 is therefore half the "
            "assertion: an unchanged md5 here would mean the declaration is "
            "inert again. Two tests fire, and they fire for different "
            "reasons — the rendering case because its parametrisation demands "
            "a cut edge, the declaration case because the rail's intent is "
            "pinned separately from it",
    ),
    Plant(
        id="switch-requests-an-undeclared-edge",
        file=LEVEL,
        old='    SM_SWITCH "LEVEL", "IMPACT"',
        new='    SM_SWITCH "LEVEL", "NOWHERE"    ; PLANT: no such [[edge]]',
        artifact=ROM,
        build=["meteor_event"],
        expect="build-fails",
        build_names="declares no [[edge]] LEVEL -> NOWHERE",
        why="the other half of the tie, and the half that is a REFUSAL rather "
            "than a red test. A scene requesting a transition the game.toml "
            "never declared has no emitted symbol to resolve, and SM_SWITCH's "
            "`.defined` guard turns that into a named build stop instead of "
            "ca65's bare \"Constant expression expected\". An `.error` nobody "
            "has fired is a comment, so it is fired here: the build must fail "
            "AND the message must name the edge, which is what makes it "
            "actionable at 3am rather than a puzzle about macro internals",
    ),
]
