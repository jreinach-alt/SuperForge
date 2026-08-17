"""split_v_fight's fighting game, planted defect by defect.

The rail HAD NO PLANT SET. Its camera split was covered by
`tools/plants/split_v_demo.py` one rail over, and everything this sprint added
— the round, the swing, the jump, the bars — arrived guarded only by tests
nobody had tried to break. A green test you have not tried to break is not
evidence (AGENTS.md), so each guarded behaviour gets a plant that switches it
off in the most PLAUSIBLE way available, and every one of them leaves a ROM
that still boots, still splits and still looks like a fighting game.

The four, and what each one is chosen to survive:

  1. THE ONE-HIT LATCH — `svf-swing-latch-never-armed`. A new swing forgets to
     clear the latch... no: it forgets to SET it on a landing, which is the
     same line written the plausible way round. The active window is eight
     frames and the bar is four segments, so one swing now empties the whole
     bar. Everything else is untouched: the swing plays, the blade sweeps, the
     defender reacts, the KO fires. Only the case that counts SEGMENTS per
     swing can see it.

  2. THE VERTICAL GATE — `svf-jump-gate-ignored`. The swing stops asking how
     high the defender is. A fighter in the air takes the hit anyway, which is
     the whole reason the jump is a COMMAND and not an animation. The jump
     still arcs, still lands, still draws its own frame; the arc test stays
     green and must.

  3. THE COUNT'S ORDER — `svf-count-digit-not-derived`. The countdown draws
     "3" on every beat instead of deriving the glyph from the round timer. The
     count still runs, still lasts the same time, still hands over to a live
     round, and the banner still appears at the end — a still of the opening
     frame is IDENTICAL to a healthy one, which is why the case that catches
     it walks every frame of the count and demands the four beats in order.

  4. THE LANDING — `svf-jump-never-reaches-zero`. The integration clamps the
     height at a floor of one pixel instead of zeroing it, and leaves the
     velocity alone. The apex is untouched, the ascent is untouched, the
     descent is untouched: only the last frame is wrong, and only a case that
     asserts the fighter comes to REST on the line it left can see it. That
     is the house's own recorded trap — an apex-only jump test ships a broken
     landing — planted deliberately.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "split_v_fight" / "scenes" / "fight.asm"
OBJ = SUPERFORGE / "engine" / "features" / "split_v_obj" / "split_v_obj.asm"
ROM = SUPERFORGE / "build" / "split_v_fight.sfc"
T = "tests/test_split_v_fight.py::"

PLANTS = [
    Plant(
        id="svf-swing-latch-never-armed",
        file=SCENE,
        old="""    lda #1
    sta z:US_SWH, x                 ; ...and this swing is spent
    jmp swing_land""",
        new="""    jmp swing_land                  ; PLANT: the swing is never marked spent""",
        artifact=ROM,
        build=["split_v_fight"],
        tests=[
            T + "test_a_swing_runs_startup_active_recovery_and_lands_exactly_one_hit",
            T + "test_the_life_bar_empties_a_segment_at_a_time_and_the_round_resets",
        ],
        why="the active window is eight frames and the bar is four segments, "
            "so one swing now empties it. Every OTHER thing about the attack "
            "is untouched — the pose plays, the blade sweeps through its four "
            "frames, the defender plays the pack's hit row, the KO fires and "
            "the round resets — so a test that asserted 'a swing damages the "
            "defender' stays green. Only counting SEGMENTS per swing sees it."),
    Plant(
        id="svf-jump-gate-ignored",
        file=SCENE,
        old="""    cmp #SV_SWING_VGATE
    bcs @bail                       ; the defender is over (or under) the blade""",
        new="""    nop                             ; PLANT: the height difference is
    nop                             ;   computed and then ignored""",
        artifact=ROM,
        build=["split_v_fight"],
        tests=[T + "test_jumping_over_a_swing_takes_no_damage"],
        why="the jump stops being a defence. A fighter at the top of a 40px "
            "arc takes a ground swing full in the face, which is the one "
            "thing that makes the jump a COMMAND rather than an animation. "
            "The arc itself is untouched, so the ascent/apex/descent/landing "
            "case stays green and must — it is about the jump, not about what "
            "the jump is FOR."),
    Plant(
        id="svf-count-digit-not-derived",
        file=OBJ,
        old="""    eor #$FFFF
    inc a
    clc
    adc #3                          ; beat 3 -> 0, beat 1 -> 2
    asl a                           ; ...one HUD slot is two tiles
    clc
    adc #SV_H_D3
    sta z:US_TILE""",
        new="""    lda #SV_H_D3                    ; PLANT: every beat draws "3"
    sta z:US_TILE""",
        artifact=ROM,
        build=["split_v_fight"],
        tests=[T + "test_the_round_counts_3_2_1_FIGHT_and_only_then_goes_live"],
        why="the count stops counting. It still runs for exactly as long, "
            "still gates input for exactly as long, still ends on FIGHT and "
            "still hands over to a live round — and the OPENING frame is "
            "pixel-identical to a healthy one, which is what a still would "
            "photograph. Only walking every frame of the count and demanding "
            "3, 2, 1, FIGHT IN ORDER can tell the two ROMs apart."),
    Plant(
        id="svf-jump-never-reaches-zero",
        file=SCENE,
        old="""@landed:
    .a16
    .i16
    lda #0
    sta z:US_JMP, x
    sta z:US_JVEL, x""",
        new="""@landed:
    .a16
    .i16
    lda #$0100                      ; PLANT: the landing clamps to one pixel
    sta z:US_JMP, x                 ;   above the floor instead of zeroing,
                                    ;   and leaves the velocity behind""",
        artifact=ROM,
        build=["split_v_fight"],
        tests=[T + "test_a_jump_rises_peaks_falls_lands_and_comes_to_REST"],
        why="the apex, the ascent and the descent are all exactly right and "
            "only the last frame is wrong — the fighter comes to rest one "
            "pixel off the ground with a live velocity under it. This is the "
            "house's own recorded trap planted deliberately: an apex-only "
            "jump test passes on this ROM, and the case only catches it "
            "because it asserts REST on the floor line the fighter left."),
]
