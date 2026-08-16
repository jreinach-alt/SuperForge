"""The two contracts that make `m7_oshoot` a rail rather than a picture.

 row 20 names exactly two things this rail is FOR beyond `m7_dungeon`:
the sprite-on-M7 projection through the matrix's TRANSPOSE, and a pivot re-pinned
to the player EVERY FRAME. Both are places where the ROM builds, links, renders
something plausible, and is wrong — which is the whole reason they get plants
rather than trust.

    the TRANSPOSE   swap M7P_DOT's pairing to the forward matrix. The sprites
                    still move, still stay on screen, and still look right for a
                    second; they simply slide off the world tile they stand on.
                    This is the classic wrong-pairing edit, and it is worth a
                    plant BECAUSE it is the failure that survives a casual
                    look.

    the PIVOT       drop the per-frame m7a_set_center from the tick, leaving the
                    enter-time pin. The floor still rotates, the hero still sits
                    at screen centre, the cast is still projected — the camera
                    simply stops following the player, so walking slides him off
                    his own world position while the picture insists he is
                    centred. Nothing in the ASM is obviously missing: the call is
                    still there, one scope up, at enter.

BOTH ARE TEST-BLIND AT THE LAYER MOST TESTS WOULD READ. Under either plant the
hero's OAM entry is still (120,104), every pool slot is still emitted, the
alive[] arrays are still right, and both census words still agree with them. A
test suite built on those would be entirely green. The cases named below are the
ones that read the composed picture, and naming them is the point: each plant
asserts WHICH case is doing the work.

    the BULLET HIT  drop `jsr do_bullet_hit` from the tick, so bolts fly through
                    chasers. Gating that one call site is the whole edit.

    the CONTACT     drop `jsr do_contact` from the tick, so a chaser can stand
                    on the hero forever. Same shape, other call site.

THE LAST TWO WERE ADDED AFTER A REVIEW FOUND THE HOLE: deleting either collision
routine would have left all 23 cases green — neither box collision had a case
that asserted it nor a plant that broke it, while every other claim the rail
makes had at least one. These two
plants are the other half of closing that: each names ONLY the new case, because
naming a case that stays green is exactly what `expect="test-red"` is for
catching.

NOT PLANTED, deliberately:

  * `pool`'s own binding contract. That is `tools/plants/railshooter.py`'s set,
    planted against the feature's own file, and re-planting it here
    would prove the same thing twice — this rail's job is to show the contract
    SERVES a second consumer, which this rail's existence is the evidence for.
  * the arena's wall predicate. The generator already refuses a paint/block
    disagreement at build time (assert_flags_equivalent), so a plant there is
    caught before a ROM exists, which is a different and better gate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
PROJ = SUPERFORGE / "engine" / "features" / "m7_project" / "m7_project.asm"
SCENE = SUPERFORGE / "game" / "m7_oshoot" / "scenes" / "arena.asm"
ROM = SUPERFORGE / "build" / "m7_oshoot.sfc"
T = "tests/test_m7_oshoot.py::"

PLANTS = [
    # ---- the transpose ------------------------------------------------------
    Plant(
        id="projection-uses-the-forward-matrix",
        file=PROJ,
        old="    M7P_DOT M7P_AFF_A, M7P_AFF_C\n"
            "    clc\n"
            "    adc #M7P_SCREEN_CX\n"
            "    sta z:ES_M7P + M7P_SX\n"
            "    M7P_DOT M7P_AFF_B, M7P_AFF_D",
        new="    ; PLANT: the FORWARD pairing (A,B / C,D) instead of the\n"
            "    ;        transpose (A,C / B,D). Still a rotation — by +theta\n"
            "    ;        instead of -theta — so the cast counter-rotates and\n"
            "    ;        slides off the floor it is supposed to stand on.\n"
            "    M7P_DOT M7P_AFF_A, M7P_AFF_B\n"
            "    clc\n"
            "    adc #M7P_SCREEN_CX\n"
            "    sta z:ES_M7P + M7P_SX\n"
            "    M7P_DOT M7P_AFF_C, M7P_AFF_D",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_the_cast_matches_an_independent_transpose_projection_oracle",
            T + "test_a_bolt_travels_up_the_screen_whatever_the_heading",
        ],
        why="the wrong-pairing edit is worth planting precisely because "
            "it is the failure that survives a casual look: at scale 1.0 the "
            "matrix is a pure rotation, so feeding the forward pairing rotates "
            "the cast by 2*theta instead of holding it still against the floor. "
            "Every actor stays on screen, moves smoothly, and is wrong.",
    ),

    # ---- the moving pivot ---------------------------------------------------
    Plant(
        id="pivot-not-re-pinned-per-frame",
        file=SCENE,
        old="    ldx z:US_POSX + 2\n"
            "    ldy z:US_POSY + 2\n"
            "    jsr ::m7a_set_center            ; THE MOVING PIVOT",
        new="    ; PLANT: the per-frame re-pin is dropped. The enter-time\n"
            "    ;        m7a_set_center still ran, so the matrix shadow holds a\n"
            "    ;        VALID pivot and every register still commits — the\n"
            "    ;        camera simply stops following the player.\n"
            "    ldx z:US_POSX + 2\n"
            "    ldy z:US_POSY + 2\n"
            "    nop                             ; THE MOVING PIVOT",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_the_hero_stays_pinned_while_the_floor_moves_under_him",
        ],
        why="This is the difference between this rail and m7_dungeon, and it is "
            "invisible everywhere a test would normally look: the hero's OAM "
            "entry is a constant either way (mo_obj never projects him), the "
            "pools are untouched, the floor still rotates to the held heading. "
            "What breaks is only that the floor stops SLIDING under a walking "
            "hero — a claim only the rendered floor can answer.",
    ),

    # ---- the bolt x chaser box ----------------------------------------------
    Plant(
        id="bolts-fly-through-chasers",
        file=SCENE,
        old="    jsr do_bullet_hit               ; bolt x chaser, in WORLD space",
        new="    ; PLANT: the bolt x chaser box is never run. Both pools still\n"
            "    ;        allocate, fly, expire and free on TTL; the census still\n"
            "    ;        agrees with both arrays; every slot still projects\n"
            "    ;        through the transpose. Bolts simply pass through.\n"
            "    nop                             ; bolt x chaser, in WORLD space",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_a_bolt_that_reaches_a_chaser_takes_it_off_the_floor_with_it",
        ],
        why="Gating this one call site is the whole defect, and it earns a "
            "plant because a rail whose "
            "bullets pass through enemies still builds, still renders, and still "
            "reads correct everywhere a pool test looks. arena.asm:758 is the "
            "only pool_kill on MO_ENE_ALIVE in the rail, so with this call gone "
            "NOTHING can take a chaser off the floor, and the only case that "
            "notices is one that watches a specific target's OAM slot go dark "
            "while a bystander's does not.",
    ),

    # ---- the chaser x hero box ----------------------------------------------
    Plant(
        id="contact-never-knocks-the-hero-back",
        file=SCENE,
        old="    jsr do_contact                  ; chaser x hero -> knockback",
        new="    ; PLANT: the chaser x hero box is never run. Chasers still\n"
            "    ;        spawn on the ring and still close in — they simply\n"
            "    ;        walk onto the hero and stand there. No knockback, no\n"
            "    ;        grace, no cue.\n"
            "    nop                             ; chaser x hero -> knockback",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_a_chaser_reaching_the_hero_knocks_the_world_out_from_under_him",
        ],
        why="This is the failure a suite is MOST likely to ship green, because "
            "the rail's own tests used to steer around it: the two pillar cases "
            "pick windows a chaser cannot reach precisely so a knockback cannot "
            "land inside them (the teleport is invisible in the hero's OAM "
            "entry — he is pinned at screen centre either way). With the call "
            "gone the hero's entry is unchanged, both pools are unchanged, the "
            "floor still rotates and still slides. What disappears is the world "
            "being yanked 80 px out from under him, and the hit cue that goes "
            "with it — neither of which any per-actor byte read can see.",
    ),

    # ---- the contact strobe, reinstated (2026-08-08) ------------------------
    Plant(
        id="contact-strobes-the-whole-screen",
        file=SCENE,
        old="    lda #MO_GRACE_FRAMES\n"
            "    sta z:US_GRACE                  ; ...which is ALSO the blink phase the cue",
        new="    lda #MO_GRACE_FRAMES\n"
            "    sta z:US_GRACE\n"
            "    ; PLANT: the full-screen contact strobe, reinstated exactly as\n"
            "    ;        it shipped — snap INIDISP brightness to 1 and pace it\n"
            "    ;        back up. The rail still plays, the cast is untouched,\n"
            "    ;        every pool and every projection is unchanged.\n"
            "    sep #$20\n"
            "    .a8\n"
            "    lda #1\n"
            "    sta z:ES_FADE_CTL\n"
            "    jsr ::fade_start_in\n"
            "    rep #$20\n"
            "    .a16\n"
            "    lda #MO_GRACE_FRAMES            ; ...which is ALSO the blink phase the cue",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_the_screen_never_strobes_to_black_during_a_sustained_walk",
            T + "test_the_hit_cue_is_the_hero_blinking_not_the_whole_screen",
        ],
        why="THE DEFECT THE OWNER REPORTED, put back. It shipped, and it shipped "
            "with a green suite — the contact case of the day REQUIRED the flash "
            "(`dark < 0.5 * bright_before`), so the rail's own tests were "
            "asserting it. Nothing a per-actor byte read can see changes under "
            "this plant: the hero's OAM entry, both pools, the census, the "
            "projection and the floor are all identical. What changes is that "
            "the whole picture snaps to near-black on every contact — mean frame "
            "luminance 4.3 against 61.8 — which is why the two cases named here "
            "read the FRAME's luminance rather than any register or variable. "
            "The second case is named as well as the first because it is the one "
            "that proves the cue is LOCAL: under this plant the hero's pixels "
            "still vanish, so a blink-only assertion would stay green.",
    ),

    # ---- the hit cue, neutered (2026-08-08) --------------------------------
    Plant(
        id="a-contact-gives-no-feedback-at-all",
        file=SCENE,
        old="    jsr do_hit_blink                ;   RE-TINT what obj_draw just placed: a",
        new="    ; PLANT: the hit cue is never drawn. The knockback still happens\n"
            "    ;        — the world is still yanked 80 px out from under the\n"
            "    ;        hero — and the grace still runs. There is simply no\n"
            "    ;        longer anything on screen that says he was hit.\n"
            "    nop                             ;   RE-TINT what obj_draw just placed: a",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_the_hit_cue_is_the_hero_blinking_not_the_whole_screen",
            T + "test_the_screen_never_strobes_to_black_during_a_sustained_walk",
        ],
        why="The other way to 'fix' a strobe is to delete it and ship a rail "
            "that gives no damage feedback at all — which reads as the world "
            "randomly glitching, since the hero is screen-fixed and the teleport "
            "never moves him. This plant is what stops that from passing. It "
            "also proves the strobe case is NOT VACUOUS: that case asserts a cue "
            "fired inside its window precisely so it cannot go green on a build "
            "where nothing ever flashes because nothing ever happens.",
    ),

    # ---- the chase, back to full rate (2026-08-08) -------------------------
    Plant(
        id="chasers-step-every-frame-again",
        file=SCENE,
        old="    lsr                             ; bit 0 -> C, and A is dead after this\n"
            "    bcc @step",
        new="    ; PLANT: the half-rate gate is defeated — the chasers step on\n"
            "    ;        EVERY frame again, which makes a\n"
            "    ;        chaser faster than the hero on every heading but a\n"
            "    ;        cardinal. The counter still runs; the branch is simply\n"
            "    ;        always taken.\n"
            "    lsr                             ; bit 0 -> C, and A is dead after this\n"
            "    bra @step",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_grace_gates_repeat_contact_and_the_chase_leaves_room_to_play",
        ],
        why="The half of the complaint that deleting the flash would have "
            "HIDDEN rather than fixed. With the chasers back at full rate the "
            "hero gains 0.25 px/frame at best and loses 0.12 on a diagonal, so "
            "the 40-frame grace can never clear the 12 px contact box and "
            "contact re-fires the frame it expires — the player never gets to "
            "act. Every per-actor read stays correct under this plant: chasers "
            "chase, bolts kill, the census agrees, the hero is pinned. Only the "
            "RATE changes, which is why the case named here counts rendered "
            "cohort translations over a 900-frame drive (measured 20 under this "
            "plant against 3 without it) instead of asserting on any one frame.",
    ),

    # ---- THE EIGHT-WAY SNAP, REINSTATED --------------------------
    # The one plant this work exists for. It puts the deleted quantiser back —
    # not by restoring the table, which is gone, but by re-imposing its EFFECT on
    # the restored control path: the heading is rounded to the nearest multiple
    # of 32 after every turn, which is exactly the eight compass values
    # `dir8_angle` could produce.
    Plant(
        id="heading-snapped-to-eight-compass-points",
        file=SCENE,
        old="    jsr do_turn                     ; LEFT/RIGHT -> US_HEADING, continuously",
        new="    ; PLANT: the 8-way snap, reinstated. do_turn still runs and the\n"
            "    ;        heading still advances 3 units per held frame — it is\n"
            "    ;        then ROUNDED to the nearest multiple of 32, which is\n"
            "    ;        the set of values the deleted dir8_angle table could\n"
            "    ;        produce. UP still drives along the facing, so the\n"
            "    ;        rail still plays; the picture jolts 45 degrees at a\n"
            "    ;        time and UP goes up to 22.5 degrees off screen-up.\n"
            "    jsr do_turn                     ; LEFT/RIGHT -> US_HEADING, continuously\n"
            "    lda z:US_HEADING\n"
            "    clc\n"
            "    adc #16                         ; round-to-nearest, not truncate\n"
            "    and #$00E0                      ; ...to a multiple of 32\n"
            "    sta z:US_HEADING",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_a_full_turn_rotates_the_floor_smoothly_with_no_forty_five_degree_jump",
            T + "test_up_moves_the_player_toward_screen_up_at_every_heading",
        ],
        why="This is the defect that was played and rejected, and it is the "
            "one a green suite must not survive. It is deliberately planted on "
            "the RESTORED path rather than by reverting the work item, because the "
            "danger being guarded against is a snap creeping back IN somewhere, "
            "not the old table returning by name. Note it is test-blind at every "
            "layer below the picture: the heading is still a valid 0..255 word, "
            "m7a_set_heading still indexes a real LUT entry, the matrix is still "
            "a correct rotation for the heading it holds, every actor still "
            "projects through the transpose, the pools and the census are "
            "untouched, and the hero's OAM entry is a constant either way. Only "
            "two things change and both are pictures: the floor turns in 45 "
            "degree steps, and UP stops meaning screen-up.",
    ),

    # ---- the strafe's lateral sign ----------------------------------------
    Plant(
        id="strafe-terms-added-instead-of-crossed",
        file=SCENE,
        old="    lda z:ES_M7AFF + 0              ; cos(heading) * strafe, SUBTRACTED from x",
        new="    ; PLANT: the strafe's x term takes SIN where it should take COS.\n"
            "    ;        The shoulders still move the world, still oppose each\n"
            "    ;        other, and still leave the heading alone — they simply\n"
            "    ;        push along the FACING instead of across it, so a\n"
            "    ;        strafe becomes a second throttle.\n"
            "    lda z:ES_M7AFF + 2              ; cos(heading) * strafe, SUBTRACTED from x",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_the_shoulders_strafe_sideways_with_the_heading_unchanged",
        ],
        why="A strafe that is really a throttle passes every check that asks "
            "'did the world move' and 'did the heading hold' — both remain true. "
            "The case named here is the only one that asks which WAY it moved, "
            "and it asks it as a lateral floor displacement.",
    ),

    # ---- the death flash ---------------------------------------------------
    Plant(
        id="a-kill-despawns-instead-of-dying",
        file=SCENE,
        old="    lda #MO_DEATH_FRAMES\n"
            "    sta f:ES_MO_ACTORS_LONG + MO_ENE_DYING, x",
        new="    ; PLANT: the hit frees the chaser's slot on the spot, the way it\n"
            "    ;        did before the flash existed. The kill still happens,\n"
            "    ;        the score still increments, the pool still cycles — the\n"
            "    ;        target simply vanishes between two frames, which is what\n"
            "    ;        a despawn looks like and is unreadable in play.\n"
            "    POOL_BIND ES_MO_ACTORS_LONG + MO_ENE_ALIVE\n"
            "    ldx z:US_IDX2\n"
            "    jsr pool_kill",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_a_kill_visibly_dies_and_the_score_increments",
            T + "test_a_kill_is_distinguishable_from_a_despawn",
        ],
        why="The score still moves under this plant, so a case that only "
            "asserted 'the readout incremented' would stay green while the "
            "thing that matters — a kill you can SEE — was gone. The two "
            "cases named here assert the FLASH, and the second one asserts it "
            "against a despawn driven in the same ROM.",
    ),

    # ---- the score's cost on contact ---------------------------------------
    Plant(
        id="a-contact-costs-nothing",
        file=SCENE,
        old="    stz z:US_SCORE                  ; ...AND THE SCORE GOES. That is the stake",
        new="    ; PLANT: a contact no longer costs the score. Everything else\n"
            "    ;        about the hit is intact — the knockback, the grace, the\n"
            "    ;        blink — so the rail looks and plays the same and there\n"
            "    ;        is simply no reason to avoid being hit.\n"
            "    nop                             ; ...AND THE SCORE GOES",
        artifact=ROM,
        build=["m7_oshoot"],
        tests=[
            T + "test_a_contact_costs_the_score_that_was_earned",
        ],
        why="'s fifth acceptance item is 'be hurt and know it, AND "
            "have a reason to avoid it'. The blink covers the first half and "
            "already has its own case; this plant removes only the second half, "
            "which nothing else in the module would notice.",
    ),
]
