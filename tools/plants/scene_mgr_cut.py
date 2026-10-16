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

The first four cover the two directions the original work item's brief names,
plus the two refusals the design leans on; the fifth and sixth cover the
BLANK FRAME the cut used to render, which is a different defect from the ramp
and needs its own plants because a ramp assertion cannot see it:

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
  5. THE BLANK FRAME COMING BACK, as the deletion of @cut_done's one-line
     lift — the NMI then commits the blank's end a frame late and a whole
     displayed frame is black, which is the shape the owner-reported flicker
     actually had.
  6. THE BLANK FRAME COMING BACK THE OTHER WAY, as an `enter` that outgrows
     its VBlank. The blank is a bracket now, so the way to make it reach the
     screen is not to arm it early but to hold it too long — and the two
     failures look nothing alike from the mechanism end even though the
     player sees the same black frame. Moving one upload back inside
     `impact::enter` does it: 262,144 master cycles against a VBlank that has
     about 36,000 left when the switch starts.

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

MET_FLOOR = SUPERFORGE / "engine" / "features" / "met_floor" / "met_floor.asm"
MET_MAIN = SUPERFORGE / "game" / "meteor_event" / "main.asm"

T = "tests/test_scene_mgr_cut.py::"
CUT_FWD = T + "test_a_cut_edge_renders_neither_a_ramp_nor_a_blank_frame[edge0]"
CUT_BACK = T + "test_a_cut_edge_renders_neither_a_ramp_nor_a_blank_frame[edge1]"
DECLARED = T + "test_the_two_meteor_edges_are_declared_cut"
VBLANK = T + "test_the_cut_holds_its_forced_blank_inside_vblank"
MET = "tests/test_meteor_event.py::"
MET_FWD = MET + "test_the_swap_into_mode7_blanks_no_frame_the_picture_is_continuous"

PLANTS = [
    Plant(
        id="cut-path-reenables-fade",
        file=SCENE_MGR,
        old="""    lda #4
    sta z:ES_SM_CTL+2           ; phase = CUT switch (on the next tick, which
                                ;   begins at the top of VBlank)""",
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
    Plant(
        id="cut-lets-the-nmi-lift-the-blank-a-frame-later",
        file=SCENE_MGR,
        old="""    sta a:$2100                 ; INIDISP: full brightness, NOW""",
        new="""                                ; PLANT: the lift removed. The NMI
                                ;   commits the shadow at the NEXT VBlank,
                                ;   so the blank @switch asserted stands
                                ;   through a whole DISPLAYED frame""",
        artifact=ROM,
        build=["meteor_event"],
        tests=[CUT_FWD, CUT_BACK, MET_FWD],
        why="THE OWNER-REPORTED DEFECT, as the one line whose absence caused "
            "it. @switch asserts forced blank on the port; deleting @cut_done's "
            "matching lift leaves the NMI to commit the shadow at the next "
            "VBlank instead, which is one whole displayed frame of black per "
            "swap — the shape the flicker actually had. Note how much stays "
            "green against it: the rail plays through, both scenes render, the "
            "capture holds, and every RAMP assertion in this module passes, "
            "because there is no ramp — a cut that blanks a frame is still a "
            "cut. Only an assertion that reads the PICTURE on the switch "
            "frames sees it, which is why the blank half of case 1 is written "
            "as its own claim rather than folded into the ramp half. "
            "MEASURED WHILE WRITING THIS SET, and worth recording: restoring "
            "the OTHER half of the old mechanism — `sm_request_cut` arming "
            "$80 into the INIDISP shadow a frame ahead — is now INERT at the "
            "picture, because @switch re-asserts and @cut_done lifts the same "
            "blank inside one VBlank. That plant fires only the shadow "
            "assertion. The bracket is what makes the blank safe, so the "
            "bracket is what this plant takes away",
    ),
    Plant(
        id="a-cut-enter-outgrows-its-vblank",
        file=MET_MAIN,
        old="    jsr impact::floor_upload    ; the 32 KB interleaved Mode-7 plane",
        new="                                ; PLANT: the boot upload removed",
        also=((MET_FLOOR,
               """floor_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, \"floor_arm\"
""",
               """floor_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, \"floor_arm\"
    jsr floor_upload                ; PLANT: the 32 KB plane, back inside the
                                    ;   scene switch where it used to be
"""),),
        artifact=ROM,
        build=["meteor_event"],
        tests=[VBLANK, MET_FWD],
        why="THE SAME BLACK FRAME BY THE OTHER MECHANISM, and the reason this "
            "set needs two plants for one symptom. With the blank held as a "
            "bracket rather than armed ahead, the way to put it back on "
            "screen is to make the switch body too long for the VBlank it "
            "starts in — and a 32,768-byte DMA is 262,144 master cycles "
            "against roughly 36,000 available. The defect is realistic "
            "because it is a REVERT: uploading the plane at scene enter is "
            "what every other scene-scoped image on this rail used to do, "
            "and it is the obvious place to put one. It fires the mechanism "
            "case FIRST, which is the point of having that case: the "
            "scanline gate names the cause (the body outgrew VBlank) where "
            "the picture cases only report the symptom. "
            "CASE 1 IS DELIBERATELY NOT IN THIS LIST, and the reason is a "
            "MEASURED limit of its predicate rather than an oversight: an "
            "overrun blanks the TOP of a frame, not the whole of it, so the "
            "frame's colour set is black plus the scene's — `blank` wants "
            "{BLACK} exactly and `dimmed` wants a colour in neither steady "
            "picture, and a band is neither. Verified by planting this and "
            "running that case: it stays green. A partial blank is case 1b's "
            "and the rail module's, which compare geometry and pixels "
            "respectively; naming case 1 here would have been a plant with a "
            "test that cannot fire",
    ),
]
