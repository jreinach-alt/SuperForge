"""mtap + four_pads — the defects docs/102's tests claim to close, planted.

Each plant is ONE realistic slip in the feature or the demo, and names the
tests that must go red for it:

  * the D7 guard skipped — mtap_read clocks the port before the automatic
    read has started. Only a caller that arrives at the very top of VBlank
    can see it, which is exactly what tests/fixtures/mtap_probe does; every
    per-button case on players 2-4 must go red (the manual clocks corrupt
    the latch the automatic read then takes).
  * WRIO.7 left LOW after the manual read — the select line never released.
    The next frame's automatic read then delivers slots 3/4 where players 2/3
    should be; the restore case drives player 4 alone and reads players 2/3.
  * player 3's edge taken from the LEVEL (press = cur, the `eor` dropped) — a
    held button re-"presses" every frame. The edge case for player 3 must go
    red, and the other three players' cases must stay green (a discriminating
    red).
  * the absent path falls through into the read — with no adapter, P4 then
    clocks a plain pad's post-16-bit ones and reads every button held. Both
    the absent-path behaviour case and the absent-path COST case must go red.
  * pad_btn's out-of-range answer dropped — X = 4/5 returns the caller's mask
    instead of 0.
  * the demo's lamp ignores its pad — always lit.

PER-PAD PRESENCE (docs/102 D10, audit-1 F1 remediation):

  * the boot census drops player 4's 17th bit — a pad in slot 3 reads
    absent until the first periodic census. Only a read taken right after
    boot sees it, which is what the presence case's first read is.
  * the periodic census never runs (the countdown's branch lands on the
    plain path) — presence is the boot census forever. The re-read case
    pokes the word and waits for the census; the cost case requires census
    calls in its sample.
  * the census's first half writes the whole low byte (the masked merge's
    AND dropped) — player 4's bit, the other half's, is overwritten with
    the port's junk bits for a call, and bits 4-7 stay junk.
  * the boot census's closing re-latch dropped — the rail's first
    mtap_read, made before any automatic read, shifts padding 1s out of
    slot 3: player 4 holds every button for one frame, and its token flips
    at boot.
  * the demo draws every player whatever pad_here says.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
MTAP = SUPERFORGE / "engine" / "features" / "mtap" / "mtap.asm"
PLAY = SUPERFORGE / "game" / "four_pads" / "scenes" / "play.asm"
PROBE = SUPERFORGE / "build" / "mtap_probe.sfc"
FP = SUPERFORGE / "build" / "four_pads.sfc"
T = "tests/test_mtap.py::"

PLANTS = [
    Plant(id="d7-guard-skipped",
          file=MTAP,
          old="""    bpl @read_over                  ; active display: this frame's read is over""",
          new="""    bra @read_over                  ; PLANT: guard skipped — clock at once""",
          artifact=PROBE,
          build=["mtap-probe"],
          tests=[T + "test_every_button_lands_in_its_own_players_word_only[3]",
                 T + "test_a_held_button_is_pressed_on_its_first_frame_only[3]",
                 "tests/test_mtap_cost.py::test_a_caller_at_the_top_of_vblank_pays_the_auto_read_wait"],
          why="a caller at the top of VBlank (the probe's loop, or any rail "
              "whose NMI work is short) would clock slot 3 before the "
              "automatic read latches it; the guard is the only thing "
              "between that caller and a corrupt P4"),
    Plant(id="wrio-left-low",
          file=MTAP,
          old="""    lda #$FF
    sta a:$4201                     ; WRIO.7 = 1: slots 1/2 for the next frame's""",
          new="""    lda #$FF
    nop                             ; PLANT: select line never released""",
          artifact=PROBE,
          build=["mtap-probe"],
          tests=[T + "test_the_select_line_is_released_so_the_next_auto_read_sees_slots_1_and_2"],
          why="forgetting the second WRIO write is the one-line slip the "
              "protocol invites (fullsnes lists it last, 'prepare here for "
              "next frame'); the defect is visible only on the NEXT frame's "
              "automatic read, never in the frame that made it"),
    Plant(id="p3-edge-from-level",
          file=MTAP,
          old="""    lda z:ES_INP3_PREV
    eor #$FFFF
    and z:ES_INP3_CUR
    sta z:ES_INP3_PRESS""",
          new="""    lda z:ES_INP3_CUR               ; PLANT: press = level, not edge
    sta z:ES_INP3_PRESS""",
          artifact=PROBE,
          build=["mtap-probe"],
          tests=[T + "test_a_held_button_is_pressed_on_its_first_frame_only[2]"],
          why="the edge is the difference between btn and btnp; a level "
              "copied into the press word re-fires A every held frame"),
    Plant(id="absent-path-falls-through",
          file=MTAP,
          old="""    bne @present
    rts                             ; no adapter: the whole per-frame cost""",
          new="""    bra @present                    ; PLANT: read whether or not detected
    rts                             ; no adapter: the whole per-frame cost""",
          artifact=PROBE,
          build=["mtap-probe", "fp-labels"],
          tests=[T + "test_without_an_adapter_players_3_and_4_read_nothing",
                 "tests/test_mtap_cost.py::test_the_absent_path_is_a_flag_test"],
          why="detection that is computed but not consulted: with a plain pad "
              "in port 2 the manual clocks read its post-16-bit ones, so P4 "
              "holds every button — and every rail without an adapter pays "
              "the full read"),
    Plant(id="pad-btn-range-answer-dropped",
          file=MTAP,
          old="""    lda #0                          ; out of range: nothing is held
    rts""",
          new="""    rts                             ; PLANT: out of range returns the mask""",
          artifact=PROBE,
          build=["mtap-probe"],
          tests=[T + "test_out_of_range_players_answer_zero_with_every_pad_holding_everything"],
          why="the range check is the whole of 'out-of-range players return "
              "0'; without the load the caller's mask comes back as if every "
              "asked-for button were held"),
    Plant(id="lamp-ignores-its-pad",
          file=PLAY,
          old="""    beq @ring
    lda #FP_TILE_LIT""",
          new="""    lda #FP_TILE_LIT                ; PLANT: always lit""",
          artifact=FP,
          build=["four_pads"],
          tests=["tests/test_four_pads.py::test_a_lamp_lights_for_every_button_of_its_own_pad_only[0]",
                 "tests/test_four_pads.py::test_the_screen_shows_four_tokens_and_four_lamps_in_their_colours"],
          why="a lamp that is lit whatever its pad does still passes every "
              "'is the lamp drawn' check; only the idle-vs-held contrast, in "
              "OAM and on screen, catches it"),
    Plant(id="boot-census-p4-dropped",
          file=MTAP,
          old="""    bcc @p4_gone
    lda #MTAP_PAD_P4""",
          new="""    bra @p4_gone                    ; PLANT: P4's 17th bit never counted
    lda #MTAP_PAD_P4""",
          artifact=PROBE,
          build=["mtap-probe"],
          tests=[T + "test_presence_names_exactly_the_connected_pads_at_boot_and_after[pad-multitap-1111]"],
          why="the boot census is the only presence a rail has for its "
              "first CENSUS_EVERY frames — and, without an adapter, for good"),
    Plant(id="census-never-reruns",
          file=MTAP,
          old="""    beq @census                     ;   cost of presence, one dec + one branch""",
          new="""    beq @slot3                      ; PLANT: the census never runs""",
          artifact=PROBE,
          build=["mtap-probe", "fp-labels"],
          tests=[T + "test_the_census_re_reads_presence_once_a_period_in_two_halves",
                 "tests/test_mtap_cost.py::test_a_call_after_the_auto_read_stays_under_two_scanlines_census_included"],
          why="a census computed at boot and never again looks exactly right "
              "until somebody plugs a pad in; only a word that is wrong "
              "BEFORE the census and right after it shows the census ran"),
    Plant(id="census-half-clobbers-p4",
          file=MTAP,
          old="""    and #(MTAP_PAD_P1 | MTAP_PAD_P2 | MTAP_PAD_P3) ; census, the rest (player""",
          new="""                                    ; PLANT: the mask dropped (player""",
          artifact=PROBE,
          build=["mtap-probe"],
          tests=[T + "test_the_census_re_reads_presence_once_a_period_in_two_halves",
                 T + "test_presence_names_exactly_the_connected_pads_at_boot_and_after[pad-multitap-1110]"],
          why="two halves writing one byte must each write only their own "
              "bits; a plain store of the first half's byte carries the "
              "port's always-1 bits into player 4's and the unused ones"),
    Plant(id="boot-relatch-dropped",
          file=MTAP,
          old="""    lda #$01
    sta a:$4016                     ; strobe ON
    stz a:$4016                     ; strobe OFF (the auto-read needs it low)
    rep #$20""",
          new="""    lda #$01                        ; PLANT: no re-latch after the census
    rep #$20""",
          artifact=FP,
          build=["four_pads"],
          tests=["tests/test_four_pads.py::test_with_the_adapter_all_four_players_have_a_token_and_a_lamp",
                 "tests/test_four_pads.py::test_a_flips_the_token_once_per_press_not_per_frame[3]"],
          why="the first mtap_read of a rail that arms the automatic read and "
              "goes straight into its loop runs before any automatic read: "
              "whatever state the boot left the pads in is what it reads"),
    Plant(id="demo-ignores-presence",
          file=PLAY,
          old="""    jsr pad_here                ; Z clear = this player's pad is connected
    bne @shown""",
          new="""    jsr pad_here                ; Z clear = this player's pad is connected
    bra @shown                  ; PLANT: everyone drawn, pad or none""",
          artifact=FP,
          build=["four_pads"],
          tests=["tests/test_four_pads.py::test_a_player_is_drawn_only_while_its_own_pad_is_connected[p2-empty]",
                 "tests/test_four_pads.py::test_the_screen_shows_only_the_connected_pads_lamps",
                 "tests/test_four_pads.py::test_without_the_adapter_players_3_and_4_are_absent"],
          why="'which pads are connected' is the demo's half of the owner's "
              "ask; a lamp drawn for an empty port says connected where "
              "nothing is"),
]
