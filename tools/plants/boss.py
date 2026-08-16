"""boss — the scale-axis debut's falsification set (docs/46).

Six plants across the rail's three load-bearing mechanisms: the baked-track
ramps (reversed, frozen), the state machine's death choreography (recede
skipped, wrong blob bound), the shared m7_track player (the uniform-scale
negate), and the pool lifecycle the win depends on (kills dropped). Every
plant names the test that must SEE it on a rendered surface.

WHAT IS DELIBERATELY NOT HERE: a "pool exhaustion mishandled" plant on the
spawn guards (`bmi @no_fire` / `bmi @reload`). Measured against the shipping
cadence, neither pool can fill: a bolt lives ~27 frames against a 9-frame
fire cadence (max 3 of 4 slots), an orb ~61 frames against an 18-frame
second-phase cadence (max ~4 of 8), so the guarded path is unreachable and a
plant on it cannot turn any honest test red — the harness would report the
TESTS as blind rather than the plant as caught (the docs/46 distinction).
The guards stay because pool.asm's contract demands them; the reachable
half of the lifecycle — recycling — is plant 6.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "boss" / "scenes" / "arena.asm"
TRACK = SUPERFORGE / "engine" / "features" / "m7_track" / "m7_track.asm"
ROM = SUPERFORGE / "build" / "boss.sfc"

REVEAL_IDX = """    lda #BS_REVEAL_FRAMES + 1
    sec
    sbc z:US_B_TIMER
    sta z:US_SCR                    ; idx, 1..60
    M7T_BIND ::bs_reveal_bin"""

PLANTS = [
    Plant(
        id="reveal-track-reversed",
        file=SCENE,
        old=REVEAL_IDX,
        new="""    lda z:US_B_TIMER
    sta z:US_SCR                    ; PLANT: idx = timer — the ramp BACKWARDS
    M7T_BIND ::bs_reveal_bin""",
        artifact=ROM,
        build=["boss"],
        tests=["tests/test_boss.py::test_the_reveal_grows_the_boss_on_screen",
               "tests/test_boss.py::"
               "test_the_reveal_matrix_matches_the_baked_track_every_frame"],
        why="a sign slip in the cursor arithmetic plays the grow-in as a "
            "shrink-away — the classic off-by-direction a countdown-timer "
            "complement invites. Both named tests fire (2 failed), measured "
            "planted: the screenshot chain's three in-REVEAL parks INVERT "
            "(early 20859 > mid 9874 > rest 5556 face pixels — the boss "
            "visibly shrinks), and the per-frame oracle names the frame. "
            "(Earlier captures landed mid-fade and in HOLD and were blind to "
            "this plant; the re-timed parks are measured in the test's own "
            "docstring)",
    ),
    Plant(
        id="reveal-cursor-frozen",
        file=SCENE,
        old=REVEAL_IDX,
        new="""    lda #0
    sta z:US_SCR                    ; PLANT: the cursor never advances
    M7T_BIND ::bs_reveal_bin""",
        artifact=ROM,
        build=["boss"],
        tests=["tests/test_boss.py::test_the_reveal_grows_the_boss_on_screen",
               "tests/test_boss.py::"
               "test_the_reveal_matrix_matches_the_baked_track_every_frame"],
        why="a track player whose consumer stops indexing renders a frozen "
            "matrix while every timer keeps counting — the silent shape of "
            "'the ramp is wired but nothing moves'. Both named tests fire "
            "(2 failed), measured planted: the three in-REVEAL captures "
            "count 5154 face pixels EACH (entry 0 rendered statically at "
            "full brightness), flattening the strict-growth chain, and the "
            "oracle mismatches every frame past entry 0. (Same capture-timing "
            "history as the reversed plant: the old captures could not see "
            "a frozen matrix — fade completion grew the count 1763 -> 5154 "
            "with the matrix CONSTANT, and the HOLD park rendered the ring "
            "full size regardless)",
    ),
    Plant(
        id="death-recede-skipped",
        file=SCENE,
        old="""    lda #BS_ST_DEATH
    sta z:US_B_STATE
    lda #BS_REVEAL_FRAMES
    sta z:US_B_TIMER""",
        new="""    lda #BS_ST_RESULT
    sta z:US_B_STATE
    lda #BS_RESULT_FRAMES
    sta z:US_B_TIMER                ; PLANT: the recede never plays""",
        artifact=ROM,
        build=["boss"],
        tests=["tests/test_boss.py::test_the_win_cycle_recede_and_loop"],
        why="the capture beat hands straight to the result card and the "
            "death animation — the half of the scale axis that runs "
            "scale UP — silently never renders. The whole-cycle test must "
            "refuse to reach DEATH",
    ),
    Plant(
        id="death-binds-the-ring",
        file=SCENE,
        old="""    M7T_BIND ::bs_death_bin
    lda z:US_SCR
    jsr ::m7t_apply""",
        new="""    M7T_BIND ::bs_ring_bin          ; PLANT: the wrong blob
    lda z:US_SCR
    jsr ::m7t_apply""",
        artifact=ROM,
        build=["boss"],
        tests=["tests/test_boss.py::test_the_win_cycle_recede_and_loop"],
        why="bind-before-every-call means one pasted line binds the wrong "
            "track and the recede spins at rest scale forever — exactly the "
            "defect class the per-call contract invites. The recede's "
            "shrink chain (n_start > n_mid > n_end, and halved) goes red",
    ),
    Plant(
        id="track-negate-dropped",
        file=TRACK,
        old="""    eor #$FFFF
    inc a
    sta z:ES_M7AFF + 4                  ; M7C = -M7B (negated AFTER the baked
                                        ;  floor shift — negating first would
                                        ;  round differently)""",
        new="""    sta z:ES_M7AFF + 4                  ; PLANT: C = +B, the shear""",
        artifact=ROM,
        build=["boss"],
        tests=["tests/test_boss.py::"
               "test_the_reveal_matrix_matches_the_baked_track_every_frame",
               "tests/test_boss.py::test_the_fight_matrix_tracks_the_ring_oracle"],
        why="the uniform-scale identity is half derived at apply time; drop "
            "the negate and every frame renders a shear that still looks "
            "like 'a turning floor' at many headings — m7_affine's own "
            "header calls out exactly this bug class for the commit order. "
            "Both matrix oracles assert c == -b and must name it",
    ),
    Plant(
        id="shot-pool-never-recycled",
        file=SCENE,
        old="""@kill:
    .a16
    POOL_BIND ES_BS_ACTORS_LONG + BS_SHOT_ALIVE
    ldx z:US_UI
    jsr ::pool_kill                 ; X preserved""",
        new="""@kill:
    .a16
    POOL_BIND ES_BS_ACTORS_LONG + BS_SHOT_ALIVE
    ldx z:US_UI
    ; PLANT: the kill is dropped — the pool leaks every fired slot""",
        artifact=ROM,
        build=["boss"],
        tests=["tests/test_boss.py::test_shot_slots_recycle_between_flights"],
        why="a pool that never frees is the lifecycle half the shipping "
            "cadence actually exercises (the spawn guards are unreachable "
            "at these tunings — see the module docstring). MEASURED, not "
            "the first guess: the leak does NOT stall the win — an unfreed "
            "shot re-deals its 5 HP every frame it crosses the boss box, so "
            "the kill accelerates and the whole-cycle test stays green (the "
            "harness said TEST-BLIND and it was right). What no healthy "
            "frame can show is the leaked slot's OAM y wrapping the 16-bit "
            "space through the 177..239 band, and a pool that never parks "
            "a slot — both halves of the recycle test's assertion",
    ),
]
