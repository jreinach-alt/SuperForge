"""racer's seven load-bearing mechanisms, each planted and required RED.

The rail is THE CHANNEL-PRESSURE CASE, and what
makes it worth a plant set is that its claims are independent by construction:
the day-night wash, the off-road drag, the rumble strips, the pause gate and
the kart's lean frame each ride a different mechanism, so a set that only ever
broke one thing could not tell whether the others' tests were doing any work.

EVERY PLANT REACHES RENDERED PIXELS, which is not a slogan: the seam-in-isolation rail
measured that Mesen's power-on OAM is a fixed parked pattern `SetPowerOnSeed`
does not reach, so a plant whose only effect is via an OAM byte that happens
to match the park is TEST-BLIND by construction. The two OAM-facing plants
here (`racer-lean-suppressed`, and the bar half of `racer-pause-ignored`)
change a TILE NUMBER inside a slot the scene actively writes every frame, not
a Y coordinate against the park.

NOT PLANTED, deliberately: the seven-channel arming mask in `race.asm`'s
`enter`. Dropping a channel from it is a real defect and the tests would
catch it — but the CHANNEL LEDGER is asserted from the
ALLOCATOR'S MAP, which the plant does not touch, so the ledger cases would
stay green while the picture broke. That asymmetry is worth naming rather
than papering over: the ledger cases prove what was DECLARED, the picture
cases prove what was DELIVERED, and it takes both. The delivery half is
covered by `racer-blue-plane-unarmed` below, which is exactly that defect
narrowed to one channel.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
GRAD = SUPERFORGE / "engine" / "features" / "rc_grad" / "rc_grad.asm"
LOGIC = SUPERFORGE / "engine" / "features" / "rc_logic" / "rc_logic.asm"
SCENE = SUPERFORGE / "game" / "racer" / "scenes" / "race.asm"
MAIN = SUPERFORGE / "game" / "racer" / "main.asm"
ROM = SUPERFORGE / "build" / "racer.sfc"
T = "tests/test_racer.py::"

PLANTS = [
    Plant(
        id="racer-daynight-frozen",
        file=GRAD,
        old="    and #(RCG_MAX_KEY)\n    asl\n    tax",
        new="    and #0                          ; PLANT: every key -> keyframe 0\n"
            "    asl\n    tax",
        artifact=ROM,
        build=["racer"],
        tests=[
            T + "test_the_sky_changes_between_the_day_and_night_holds",
            T + "test_all_three_coldata_planes_reach_the_sky",
            T + "test_night_is_darker_than_day_and_the_cycle_comes_back",
        ],
        why="THE FEATURE rc_grad EXISTS FOR. rgb_gradient cannot serve this "
            "rail because its wash has no time axis; this "
            "plant removes the time axis from rc_grad and leaves everything "
            "else perfect — the three channels are still armed, the WRAM "
            "header tables are still built, the pointers are still valid, the "
            "phase machine still runs, and US_GRAD_K still counts 0..7. Only "
            "the DATA the pointers reach stops moving. A test that read "
            "US_GRAD_K would pass; the two that read sky-band PIXELS cannot.",
    ),
    Plant(
        id="racer-offroad-ignored",
        file=LOGIC,
        old="    and #RC_FLAG_DRIVABLE\n    rep #$20\n    .a16\n    bne @on_track",
        new="    and #RC_FLAG_DRIVABLE\n    rep #$20\n    .a16\n"
            "    bra @on_track                   ; PLANT: the map never reaches speed",
        artifact=ROM,
        build=["racer"],
        tests=[T + "test_grass_slows_the_kart_to_a_crawl_without_stopping_it"],
        why="\"THE MAP IS COLLISION GROUND TRUTH\" — the reference rail's first "
            "sentence. col_map is still composed, still queried every frame "
            "with the live camera coordinate, and still writes CM_FLAG; only "
            "the branch that lets the answer reach velocity is gone. This is "
            "the shape the test was written against: an assertion on "
            "US_SPEED, or on CM_FLAG, would survive this plant unchanged, "
            "because both are still correct. Only the picture moves.",
    ),
    Plant(
        id="racer-kerb-palette-truncated",
        file=SCENE,
        old="    ldy #ES_R_FLOOR_PAL_ROM_SIZE\n    jsr m7_upload_pal",
        new="    ldy #10                     ; PLANT: stop before the kerb pair\n"
            "    jsr m7_upload_pal",
        artifact=ROM,
        build=["racer"],
        tests=[T + "test_the_rumble_strips_show_both_red_and_white"],
        why="THE RUMBLE STRIPS THEMSELVES. With the kerb cycle gone the kerbs "
            "have no code of their own to break — they are "
            "two fixed entries of a palette uploaded once — so the plant "
            "attacks the upload: five words instead of seventeen, which "
            "leaves CGRAM 5 and 6 holding power-on RAM. Everything else is "
            "untouched; the tilemap still names the kerb tiles, the tileset "
            "still paints them, and the anti-regression case correctly "
            "SURVIVES, because garbage that never changes is still static. "
            "That split is the point: one case says the pattern is THERE and "
            "the other says it does not MOVE, and they fail on different "
            "defects.",
    ),
    Plant(
        id="racer-kerb-cycle-reintroduced",
        file=MAIN,
        old="    jsr race::stream_nmi_dispatch\n",
        new="""    jsr race::stream_nmi_dispatch
    ; PLANT: the defect playtest found, put back — a per-frame
    ; CGRAM write that repaints the kerb red slot on a frame bit. It must
    ; ALTERNATE, not corrupt: a one-way write settles after the first firing
    ; and two samples then read the same byte, which is how the first version
    ; of this plant came back TEST-BLIND against a working assertion.
    lda a:ES_SM_FRAME
    and #16
    beq @plant_dark
    lda #5
    sta a:$2121                 ; REG-LINT: ok $2121 — deliberate plant (docs/46)
    lda #$FF
    sta a:$2122                 ; REG-LINT: ok $2122 — deliberate plant (docs/46)
    lda #$7F
    sta a:$2122                 ; REG-LINT: ok $2122 — deliberate plant (docs/46)
    bra @plant_done
@plant_dark:
    .a8
    .i16
    lda #5
    sta a:$2121                 ; REG-LINT: ok $2121 — deliberate plant (docs/46)
    lda #$1F
    sta a:$2122                 ; REG-LINT: ok $2122 — deliberate plant (docs/46)
    lda #$00
    sta a:$2122                 ; REG-LINT: ok $2122 — deliberate plant (docs/46)
@plant_done:
    .a8
    .i16
""",
        artifact=ROM,
        build=["racer"],
        tests=[T + "test_cgram_never_changes_after_the_scene_is_up"],
        why="THE DEFECT CLASS ITSELF, reintroduced. This is the plant the "
            "anti-regression case exists for: a per-frame palette writer "
            "added to the VBlank hook, which is exactly the shape the "
            "shipped-then-reverted kerb cycle had. It reaches rendered "
            "pixels (the strips blink) AND it makes CGRAM move, and the "
            "PATTERN case correctly SURVIVES it — both colours are still on "
            "screen at both phases, which is precisely why 'red and white "
            "are both present' was not a sufficient test on its own.",
    ),
    Plant(
        id="racer-pause-ignored",
        file=SCENE,
        old="    jsr rc_pause\n    beq @racing\n    rts",
        new="    jsr rc_pause\n    bra @racing                 ; PLANT: the freeze gate is gone\n"
            "    rts",
        artifact=ROM,
        build=["racer"],
        tests=[T + "test_start_freezes_the_whole_picture_and_start_again_resumes"],
        why="THE FREEZE-FRAME, and the invariant is the USER-VISIBLE one "
            "(CLAUDE.md's parallax lesson: 'freeze' means pixels do not move, "
            "not that a variable reads 1). US_PAUSED still toggles on the "
            "rising edge and still reads 1 while frozen — a test asserting "
            "the flag would pass on this ROM. The picture keeps moving: the "
            "camera advances, the kerb lights keep flashing and the day-night "
            "clock keeps stepping, which is why the case compares two frames "
            "of the freeze for BYTE IDENTITY rather than sampling one.",
    ),
    Plant(
        id="racer-lean-suppressed",
        file=LOGIC,
        old="    ldy #1                          ; lean left",
        new="    ldy #0                          ; PLANT: no lean frame on LEFT",
        artifact=ROM,
        build=["racer"],
        tests=[T + "test_the_kart_frame_follows_the_steer_direction"],
        why="THE LEAN FRAME — 'the kart leans into the turn', and the reason "
            "the CHR carries a second 16x16 frame at all. Steering still "
            "works: the heading still steps, the pose still retargets, the "
            "floor still rotates, so every camera case stays green and only "
            "the OAM TILE NUMBER is wrong. The plant is one-sided (LEFT only) "
            "so the parametrised case must fail on exactly the arm whose "
            "mechanism moved, which is a sharper signal than breaking both.",
    ),
    Plant(
        id="racer-blue-plane-unarmed",
        file=SCENE,
        old="    ora #((1 << ES_H_RCGR_CH) | (1 << ES_H_RCGG_CH) | (1 << ES_H_RCGB_CH))",
        new="    ora #((1 << ES_H_RCGR_CH) | (1 << ES_H_RCGG_CH))  ; PLANT: B plane off",
        artifact=ROM,
        build=["racer"],
        tests=[T + "test_all_three_coldata_planes_reach_the_sky"],
        why="THE DELIVERY HALF OF THE LEDGER. counts seven armed "
            "channels; this drops one of them at the HDMAEN shadow while "
            "leaving the claim, the channel assignment, the header table and "
            "the blob completely intact — so every ledger case (which reads "
            "the ALLOCATOR'S MAP) stays green by design, and the picture "
            "cases have to carry it. That split is the point: a declaration "
            "is not a delivery, and this set exists partly to prove the "
            "module knows the difference. IT FOUND ONE: on its first run the "
            "named cases were the two day-vs-night ones and both stayed "
            "GREEN, because R and G still moved and 'the sky changes' does "
            "not ask which plane changed it. The per-plane case exists "
            "because of this plant.",
    ),
]
