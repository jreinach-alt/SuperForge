"""sprite_game — the two defects `` §4 ran ad-hoc, made re-runnable.

WHY THIS FILE EXISTS AT ALL. The port ran both plants during the work item and
wrote the outcome into `` §4 — then left nothing behind, so the claim
"this rail's teeth are real" was true and **unverifiable by re-running the
tree**. The a spot check (a spot audit, LOW)
had to reconstruct both from prose and drive them through `tools/falsify.py`
as a library from a scratchpad to check the record. Both FIRED, at exactly
the recorded counts. This file is that reconstruction, committed and
registered, so `make falsify SET=sprite_game` carries the teeth forward.

THE TWO DEFECTS, and the shape each one is a witness for:

  1. THE CLOSED RANGE — the catch test's in-range compare widened by one
     (`cmp #(2*SPRG_SIZE - 1)` -> `cmp #(2*SPRG_SIZE)`), on the X AXIS ONLY.
     Its history is the reason it is worth keeping: planted during the build
     it **DID NOT FIRE** — 18/18 stayed green — because the boundary walk
     only approached from the left (d = -8), the end the *negative* bound
     enforces, while the widened bound is the *positive* end. The test grew
     leg B (park at d = +8 against the relocated dot, then step in) and the
     plant then reddened exactly one case. So re-running this plant does
     not merely confirm a sensitivity: it re-proves that the right-hand leg
     really landed and really discriminates. If a future edit narrows that
     walk back to one side, this plant goes TEST-BLIND and says so.

     The general shape: an in-range compare has TWO
     ends, and a boundary test that walks one of them is half a test. It
     will pass with the other end widened arbitrarily.

  2. THE TICK'S STAGING CALL — `tick`'s tail `jmp sprg_obj_place` dropped to
     a bare `rts`. The ROM boots and the picture is plausible, because
     `enter` calls `sprg_obj_place` once, so frame 1 draws both actors where
     they belong and they simply never move again. Every consumer of the
     per-frame restaging goes red at once and the ten cases that are
     structurally blind to it stay green BY DESIGN — the uploads (VRAM CHR,
     CGRAM), the backdrop, the boot rest position, the whole-screen census
     at boot, the composition map, the uninit-read walk, and the idle case
     (nothing moves either way). That 8-vs-10 split is what makes the module
     discriminating rather than uniformly load-bearing.

RED COUNTS — measured on this tree at 402f371, and equal to the counts
`` §4 and the spot check §4.2 both record:

    sg-collision-closed-range   1 failed              (whole module: 1 failed, 17 passed)
    sg-tick-staging-dropped     8 failed              (whole module: 8 failed, 10 passed)

The `tests=` lists below name the reds themselves rather than the module, so
the printed tail's count IS the claim: "8 failed" means all eight named cases
went red, not "eight of eighteen did".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "sprite_game" / "scenes" / "play.asm"
ROM = SUPERFORGE / "build" / "sprite_game.sfc"
T = "tests/test_sprite_game.py::"

PLANTS = [
    # ---- the in-range compare's positive end, widened by one --------------
    Plant(
        id="sg-collision-closed-range",
        file=SCENE,
        # X AXIS ONLY — the Y block below it is byte-identical, so the anchor
        # carries the three lines that make this one the X test. `replace(…,
        # 1)` would take the first occurrence anyway; naming the axis in the
        # anchor means a future reorder cannot silently move the plant.
        old="    lda z:US_PX\n"
            "    sec\n"
            "    sbc z:US_DOT_X\n"
            "    clc\n"
            "    adc #(SPRG_SIZE - 1)\n"
            "    cmp #(2 * SPRG_SIZE - 1)\n",
        new="    lda z:US_PX\n"
            "    sec\n"
            "    sbc z:US_DOT_X\n"
            "    clc\n"
            "    adc #(SPRG_SIZE - 1)\n"
            "    cmp #(2 * SPRG_SIZE)        ; PLANT: strict -> closed range\n",
        artifact=ROM,
        build=["sprite_game"],
        tests=[T + "test_touching_edge_to_edge_is_not_a_catch_on_either_side"],
        why="off-by-one in the overlap predicate, the single most ordinary "
            "mistake in a hand-written collision test: `d + 7 in [0, 14]` "
            "becomes `in [0, 15]`, so boxes that merely TOUCH edge-to-edge on "
            "the +X side now count as a catch. The col_box contract is "
            "strict half-open, so this is a real contract violation and not a "
            "taste question. It reds exactly one case — the edge-to-edge "
            "boundary walk — and that is the point: this plant STAYED GREEN "
            "during the build until the walk grew its right-hand leg, so it is "
            "the standing witness that the leg is still there. A one-sided "
            "walk cannot see a widened opposite bound",
    ),
    # ---- the per-frame restaging, dropped ---------------------------------
    Plant(
        id="sg-tick-staging-dropped",
        file=SCENE,
        old="    jsr move_player\n"
            "    jsr catch_dot\n"
            "    jmp sprg_obj_place\n",
        new="    jsr move_player\n"
            "    jsr catch_dot\n"
            "    rts                         ; PLANT: tick staging dropped\n",
        artifact=ROM,
        build=["sprite_game"],
        tests=[
            T + "test_both_actors_are_restaged_every_frame_not_written_once",
            T + "test_the_dpad_moves_the_player_right_and_back",
            T + "test_the_dpad_moves_the_player_down_and_back",
            T + "test_the_player_crosses_the_screen_edge_and_x9_tracks_bit_8",
            T + "test_the_first_catch_scores_and_relocates_the_dot",
            T + "test_touching_edge_to_edge_is_not_a_catch_on_either_side",
            T + "test_four_catches_walk_the_preset_cycle_and_wrap",
            T + "test_the_catch_repaints_the_dot_at_its_new_spot",
        ],
        why="the tail-call tidy-up: `tick` ends in `jmp sprg_obj_place`, which "
            "reads like a jump to the next thing rather than the frame's "
            "actual output stage, and a port trimming a 'redundant' jump "
            "leaves `rts`. Nothing about the ROM looks wrong — `enter` already "
            "staged both actors, so it boots to a correct picture and holds "
            "it. The game state still moves underneath (US_PX advances, the "
            "score ticks, the dot cycles); only the OAM shadow stops being "
            "written, which is precisely the case the shadow-counter test was "
            "written for. Eight cases red, and the other ten green BY DESIGN "
            "(uploads, backdrop, boot rest, boot census, composition map, "
            "uninit walk, idle) — a defect that only the per-frame surfaces "
            "can see, proven seen",
    ),
]
