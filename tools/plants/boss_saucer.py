"""boss_saucer — the SCALING rail's falsification set (docs/46).

Six plants across the six mechanisms this rail ADDS on top of the boss
debut it inherits: the lunge's two baked ramps (the dive's cursor, the
climb's blob), the beam's column lock and its telegraph-vs-active split,
the break-off, and the audio the rail is the one composer of.
Every plant names the test that must SEE it on a rendered surface.

WHAT IS DELIBERATELY NOT HERE, and why each is a plant that could only
report the TESTS blind (the docs/46 distinction) rather than a defect
caught:

  * a plant on `pool_spawn`'s POOL_FULL guard (`bmi @no_fire`). Measured
    against the shipping cadence: a bolt lives (176 - 16) / 6 = 27 frames
    against an 8-frame fire cadence, so at most 4 of 4 slots are live and
    the pool's own spawn scan finds a free one before the fifth shot is
    ever requested. The guarded path is unreachable; the guard stays
    because pool.asm's contract demands it. The reachable half of the
    lifecycle — recycling — is covered by the boss rail's plant shape and
    by this rail's own recycle test.
  * a plant on the RING blob. Only HOLD indexes it here (the fight holds
    angle 0), and the boss rail's own set already falsifies the shared
    player through it — a second copy would prove nothing new about THIS
    rail. The seams that DO bind the ring to this rail's ramps are
    asserted at build time in the generator and again in
    `test_the_track_blobs_hold_their_format_and_their_seams`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "boss_saucer" / "scenes" / "arena.asm"
ROM = SUPERFORGE / "build" / "boss_saucer.sfc"

T = "tests/test_boss_saucer.py::"

PLANTS = [
    Plant(
        id="lunge-dive-cursor-frozen",
        file=SCENE,
        old="""    lda #SAU_LUNGE_FRAMES + 1
    sec
    sbc z:US_LUNGE_TIMER
    sta z:US_SCR                    ; idx, 1..45
    M7T_BIND ::sau_appr_bin""",
        new="""    lda #0
    sta z:US_SCR                    ; PLANT: the dive's cursor never advances
    M7T_BIND ::sau_appr_bin""",
        artifact=ROM,
        build=["boss_saucer"],
        tests=[T + "test_the_lunge_grows_then_shrinks_the_saucer",
               T + "test_the_lunge_matrix_matches_the_baked_ramps_every_frame"],
        why="the rail's HEADLINE, silently disarmed: every timer keeps "
            "counting and the state machine still walks FAR -> APPROACH -> "
            "NEAR -> RETREAT, but the plane holds the rest pose through the "
            "whole dive — 'the lunge is wired and nothing zooms'. This is "
            "the shape a frozen track cursor takes, and it is why the pixel "
            "test measures the EMITTER rather than the whole face: the "
            "emitter's area is monotone in 1/scale, so a frozen dive "
            "flattens `far < mid_in < apex` instead of merely bending it",
    ),
    Plant(
        id="lunge-climb-binds-the-dive",
        file=SCENE,
        old="""    M7T_BIND ::sau_retr_bin
    lda z:US_SCR
    jsr ::m7t_apply""",
        new="""    M7T_BIND ::sau_appr_bin         ; PLANT: the wrong blob
    lda z:US_SCR
    jsr ::m7t_apply""",
        artifact=ROM,
        build=["boss_saucer"],
        tests=[T + "test_the_lunge_grows_then_shrinks_the_saucer",
               T + "test_the_lunge_matrix_matches_the_baked_ramps_every_frame"],
        why="bind-before-every-call means ONE pasted line binds the wrong "
            "track — exactly the defect class the per-call contract invites, "
            "and the reason this rail ships the climb as its own blob rather "
            "than walking the dive backwards. Planted, the climb "
            "re-plays the DIVE. MEASURED, and it corrected this entry: the "
            "first run fired `1 failed, 1 passed`, because a replayed dive is "
            "just as monotone as a real climb — `apex > mid_out > far` held, "
            "and `home` is sampled after the FAR transition re-applies the "
            "rest pose either way, so the pixel cycle test was blind and only "
            "the per-frame oracle named it. The cycle test now also samples "
            "the climb's LAST frame, which is the one place a climb and a "
            "second dive differ (rest pose vs apex pose); re-measured after "
            "that change, BOTH named tests fire — 2 failed",
    ),
    Plant(
        id="beam-column-not-locked",
        file=SCENE,
        old="""    lda z:US_P_X
    clc
    adc #4                          ; centre the 8 px column on the 16 px hull
    sta z:US_BEAM_X""",
        new="""    lda #SAU_PLAYER_X0 + 4          ; PLANT: a FIXED column, never latched
    sta z:US_BEAM_X""",
        artifact=ROM,
        build=["boss_saucer"],
        tests=[T + "test_the_beam_renders_a_seamless_column_locked_to_the_player",
               T + "test_strafing_out_of_the_telegraph_dodges_the_beam"],
        why="the beam's whole design is that the apex LATCHES the column onto "
            "wherever the player is standing, so the telegraph is a real "
            "dodge window. A fixed column looks identical on a stationary "
            "player — the autonomous LOSE path still works, the beam still "
            "renders, the ship still flashes — and is completely wrong for a "
            "player who moved. THIS PLANT'S FIRST RUN SAID TEST-BLIND AND THE "
            "HARNESS WAS RIGHT: both named tests drove to the telegraph with "
            "no input, so the ship sat on the spawn lane the plant pins the "
            "column to, and a constant column was the same picture as a "
            "latched one (2 passed against a defect that reached the "
            "artifact). The remediation drives LEFT to the clamp BEFORE the "
            "latch in both tests, so the lock test's `bx == p_x + 4` is a "
            "claim about a column that followed and the dodge test's arms "
            "both depend on the latch; measured planted, 2 failed",
    ),
    Plant(
        id="telegraph-damages",
        file=SCENE,
        old="""    lda z:US_BEAM_STATE
    beq @done                       ; SAU_BM_OFF -> nothing
    cmp #SAU_BM_TELE
    beq @tele""",
        new="""    lda z:US_BEAM_STATE
    beq @done                       ; SAU_BM_OFF -> nothing
                                    ; PLANT: the telegraph is skipped, so the
                                    ;   beam damages from its first frame""",
        artifact=ROM,
        build=["boss_saucer"],
        tests=[T + "test_the_beam_renders_a_seamless_column_locked_to_the_player",
               T + "test_strafing_out_of_the_telegraph_dodges_the_beam"],
        why="collapsing the two beam phases removes the dodge window without "
            "removing the beam: it still renders, still costs hearts, still "
            "drives the LOSE path — the fight is merely unfair. The telegraph "
            "is the stated design (24 frames of dim, every-other "
            "segment) and its render is the sparse column the lock test "
            "asserts slot by slot; the dodge test's strafe arm goes red "
            "because the damage lands before the player can leave",
    ),
    Plant(
        id="kill-skips-the-break-off",
        file=SCENE,
        old="""    stz z:US_BEAM_STATE             ;   and the beam dies with it
    jsr break_off                   ; climb home, then hand to DEATH""",
        new="""    stz z:US_BEAM_STATE             ;   and the beam dies with it
    lda #SAU_ST_DEATH               ; PLANT: hand straight over, mid-dive
    sta z:US_B_STATE
    lda #SAU_REVEAL_FRAMES
    sta z:US_B_TIMER""",
        artifact=ROM,
        build=["boss_saucer"],
        tests=[T + "test_the_kill_climbs_the_lunge_home_before_the_recede"],
        why="The break-off's entire subject. The baked death track is ABSOLUTE, so "
            "handing to it from wherever the lunge happened to be teleports "
            "the saucer to rest size on one frame — the pop the break-off "
            "exists to remove, and the one thing that separates this rail's "
            "kill from a naive port. The plant is invisible to every other "
            "test (the recede still plays, the card still shows, the loop "
            "still closes); what fires is the monotone-climb assertion on the "
            "matrix shadow and the seam's rendered-area bound",
    ),
    Plant(
        id="beam-queues-no-sfx",
        file=SCENE,
        old="""    sep #$20
    .a8
    lda #SFX::room_b_ambience       ; the beam ignites: the arena rings
    jsr Tad_QueueSoundEffect
    rep #$20
    .a16""",
        new="""                                    ; PLANT: the ignition SFX is never
                                    ;   queued — the beam burns silently""",
        artifact=ROM,
        build=["boss_saucer"],
        tests=[T + "test_the_theme_plays_and_the_beam_swells_the_arena_echo"],
        why="this is the tail's ONE audio-composing rail, and the whole of "
            "what 'composing' means here is that game code ASKS through the "
            "Tad_* API and claims nothing. A dropped queue call leaves the "
            "driver playing, the song ticking and every visual surface "
            "identical — the only witness is SPC-side hardware state. The "
            "test walks the echo registers through rest -> beam -> rest, so "
            "the plant fires on the middle leg; a snapshot test of 'is audio "
            "running' would not have seen it",
    ),
]
