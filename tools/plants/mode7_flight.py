"""The five contracts that make `mode7_flight` the altitude axis rather than a
picture of one.

This rail's whole subject is a design that was RULED rather than derived
THE SEPARATED FACTORS: the pose factors, both factors are baked, and
the join multiplies them back together 160 times a frame. Every plant below
attacks one joint of that, and every one of them leaves a ROM that builds,
links, and renders a plausible Mode 7 floor with a sky over it and an airship
in the middle. That is the reason they exist rather than trust.

    a FACTOR's BYTES   corrupt one altitude level of the baked scale profile.
                       The blob is still the right size, the claim is still
                       backed, every `.assert` on stride and level count still
                       holds, and 80 of the 81 altitudes are still exact — so
                       nothing about the DECLARATION is wrong. Only the picture
                       at one altitude is.

    the CD IDENTITY    write M7D from B instead of from A. C = -B and D = A is
                       the per-scanline form of the identity the design review
                       verified byte-for-byte, and it is what buys this rail two
                       multiplies a line instead of four. Break the D half and
                       the plane SHEARS — every entry is still written, every
                       count byte is still right, the table is still exactly
                       640 data bytes per channel.

    the OPERAND ORDER  swap which magnitude the join stages first, so every
                       scanline gets A = S*sin and B = S*cos. The floor still
                       has perspective, still turns with the heading, still
                       recedes when you climb — it is simply rotated a quarter
                       turn away from where the ship is pointing, which is a
                       fact about a picture and not about any variable.

    the BUFFER SWAP    stop flipping `back` in the NMI hook. The join keeps
                       composing, every entry stays exact, and the channels
                       keep streaming a valid table — the SAME one, forever,
                       while the CPU rewrites it underneath them. Nothing is
                       missing anywhere: the flip is one `eor #1`.

    the DIRTY GATE     pin the change-gate's countdown clear, so the join
                       never runs after scene enter. The rail still renders a
                       perspective floor with a sky over it and an airship in
                       the middle — it is simply the SPAWN pose's floor, for
                       the whole flight, while the ship's shadow and the
                       altitude state move correctly underneath it.

    the BUFFER COUNT   arm the gate for ONE buffer instead of two. This is the
                       double-buffer-specific failure and the reason the gate
                       is a countdown rather than a flag: only one of the two
                       tables is refreshed, so the swap alternates between
                       this frame's pose and one from two frames ago. The
                       picture is RIGHT on alternate frames — a 30 Hz judder
                       that reads as a cadence problem rather than a logic one.

    the BAND BOUNDS    shorten the second segment by four lines. The picture
                       keeps a horizon, keeps a sky, keeps a floor; four
                       scanlines at the bottom of the band simply hold the
                       previous line's matrix. This is the plant for the four
                       CONTROL bytes the join has to step over and does not own.

WHY THESE FIVE AND NOT THE OBVIOUS ONES. "Delete the compose call" and "clamp
the altitude to a constant" are both loud: the first renders a frozen floor and
the second stops the axis dead, and a cold read catches either. The five above
are the ones that survive a look — the class this harness exists for, and the
class both of this work's own real defects belonged to (a stack-balance slip
that JSR'd through a garbage vector, and a segment that wrote 80 lines one byte
off; the picture had a floor in it through both).

NOT PLANTED, deliberately:

  * the generator's own identity and monotonicity checks. `gen_m7f_factors.py`
    asserts them at BAKE time, so a plant there is refused before a ROM exists
    — a different and better gate than a red test.
  * the sky split's TM values. `m7f_floor`'s two-band table is four bytes and
    the picture answers immediately; the pixel case already reads the boundary
    to the scanline, and a plant would only prove the assertion is not vacuous
    in a place where vacuity is not the risk.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
CAM = SUPERFORGE / "engine" / "features" / "m7f_cam" / "m7f_cam.asm"
FLOOR = SUPERFORGE / "engine" / "features" / "m7f_floor" / "m7f_floor.asm"
GEN = SUPERFORGE / "tools" / "gen_m7f_factors.py"
GEN_JOIN = SUPERFORGE / "tools" / "gen_m7f_join.py"
ROM = SUPERFORGE / "build" / "mode7_flight.sfc"
T = "tests/test_mode7_flight.py::"

CYCLES = T + "test_the_band_tracks_both_axes_through_every_state_cycle"

PLANTS = [
    # ---- a factor blob's bytes ---------------------------------------------
    Plant(
        id="one-altitude-level-of-the-scale-profile-is-corrupt",
        file=GEN,
        old="        row = [quantise(s) for s in raw]\n",
        new="        row = [quantise(s) for s in raw]\n"
            "        # PLANT: one altitude level's profile is flattened toward\n"
            "        #        its own near end. The blob is still 25,920 B, the\n"
            "        #        stride is still 320, all 81 levels are still\n"
            "        #        present and every .assert in m7f_cam still holds —\n"
            "        #        so the DECLARATION is untouched and the claim is\n"
            "        #        still backed. Only the picture at this one\n"
            "        #        altitude is wrong.\n"
            "        if alt == ALTS[ALT_SPAWN_IDX + 6]:\n"
            "            row = [min(row[-1] + 3, p) for p in row]\n",
        artifact=ROM,
        build=["m7f-assets", "mode7_flight"],
        tests=[
            CYCLES + "[climb-pad0-40]",
            T + "test_the_altitude_axis_returns_to_its_start_and_the_band_with_it",
        ],
        why="A baked factor is only as good as its bytes, and nothing in the "
            "build asks whether they are RIGHT — `rom-unbacked` asks whether "
            "they EXIST and the size .asserts ask whether the shape matches. "
            "The whole-table oracle is the only thing between a corrupt level "
            "and a shipped one, and this plant is what proves it is looking.",
    ),

    # ---- the CD identity ----------------------------------------------
    # RE-HOMED to the GENERATOR when the join body became emitted asm. The
    # emitted file lands in build/ and is rewritten on every build, so a plant
    # against it would be reverted by the next `make` rather than by the
    # harness — the plant has to attack the thing that PRODUCES the asm. That
    # is the maintenance path the generator's header states, applied to
    # sabotage as well as to fixes.
    Plant(
        id="m7d-written-from-b-instead-of-a",
        file=GEN_JOIN,
        old='    a += [f"    sta a:M7F_AB + {to} + 0, y",\n'
            '          f"    sta a:M7F_CD + {to} + 2, y  ; M7D = A (the identity, as a store)"]\n',
        new='    # PLANT: M7D is left holding whatever the PREVIOUS line put\n'
            '    #        there. D = A is half of the identity that buys this\n'
            '    #        rail two multiplies a line instead of four; drop it\n'
            '    #        and the plane shears, while every count byte, every\n'
            '    #        terminator and all 640 data bytes per channel stay\n'
            '    #        exactly as they were.\n'
            '    a += [f"    sta a:M7F_AB + {to} + 0, y"]\n',
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            T + "test_the_composed_band_matches_the_generator_at_the_spawn_pose",
            CYCLES + "[turn left while climbing-pad3-40]",
        ],
        why="C = -B and D = A is the per-scanline form of the identity the "
            "design review verified byte-for-byte across the baked sets, and it is "
            "the reason the join is two products a line rather than four. It is "
            "asserted NOWHERE except in the composed table, because the M7 "
            "ports are write-only — so if the whole-table oracle does not catch "
            "this, nothing does.",
    ),

    # ---- the multiply operand order ----------------------------------------
    Plant(
        id="the-join-swaps-its-cos-and-sin-operands",
        file=CAM,
        old="    lda f:M7F_TRIG_LONG + 0, x\n"
            "    sta z:M7F_CMAG              ; cmag, in the low byte\n"
            "    eor f:M7F_TRIG_LONG + 2, x  ; ...XOR smag: the inner loop's operand switch",
        new="    ; PLANT: the two magnitudes are staged the other way round, so\n"
            "    ;        every scanline gets A = S*sin and B = S*cos. Still a\n"
            "    ;        perspective floor, still turning with the heading,\n"
            "    ;        still receding on a climb — a quarter turn away from\n"
            "    ;        where the ship points, and only a picture can say so.\n"
            "    lda f:M7F_TRIG_LONG + 2, x\n"
            "    sta z:M7F_CMAG              ; cmag, in the low byte\n"
            "    eor f:M7F_TRIG_LONG + 0, x  ; ...XOR smag: the inner loop's operand switch",
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            T + "test_the_composed_band_matches_the_generator_at_the_spawn_pose",
            T + "test_the_streamed_buffer_is_exactly_one_frame_behind",
        ],
        why="The sign masks are read separately from the magnitudes, so a swap "
            "here is not a sign error and not a range error — every coefficient "
            "stays in band, the table stays well-formed, and the rail keeps all "
            "four of its teaching points. It is exactly the kind of wrongness "
            "that reads as a design choice until it is compared to an oracle.",
    ),

    # ---- the double buffer's swap ------------------------------------------
    Plant(
        id="the-band-table-is-never-swapped",
        file=CAM,
        old="    lda z:M7F_BACK\n"
            "    eor #1\n"
            "    sta z:M7F_BACK\n"
            "    jsr m7f_point_channels",
        new="    ; PLANT: the flip is dropped, so the tick composes the same\n"
            "    ;        buffer the channels are streaming and the PPU reads a\n"
            "    ;        table the CPU is rewriting underneath it. Every entry\n"
            "    ;        the join writes is still exact; the second buffer is\n"
            "    ;        still allocated, still composed at enter, still valid.\n"
            "    lda z:M7F_BACK\n"
            "    nop\n"
            "    sta z:M7F_BACK\n"
            "    jsr m7f_point_channels",
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            T + "test_the_double_buffer_swaps_and_the_streamed_table_is_never_the_live_one",
            T + "test_the_streamed_buffer_is_exactly_one_frame_behind",
        ],
        why="The double buffer is the cost the separated factors accepted "
            "records the tear discipline as a lesson SuperForge had RETIRED, and "
            "the separable join brings it back. A plant on it is the check that "
            "the 2.5 KB is doing work rather than sitting there: without the "
            "flip the picture still has a floor, because most of the table is "
            "unchanged frame to frame.",
    ),

    # ---- the band bounds ----------------------------------------------------
    Plant(
        id="the-second-segment-stops-four-lines-early",
        file=CAM,
        old="    clc\n"
            "    adc z:M7F_NLINES\n"
            "    sta z:M7F_XEND              ; ...and runs the remaining N/2 lines\n",
        new="    ; PLANT: segment 1 stops four lines short. The HDMA count byte\n"
            "    ;        still says N/2, so the channel still streams N/2\n"
            "    ;        lines — the last four just carry whatever the\n"
            "    ;        previous frame left there. A horizon, a sky and a\n"
            "    ;        floor all survive.\n"
            "    clc\n"
            "    adc z:M7F_NLINES\n"
            "    sec\n"
            "    sbc #8\n"
            "    sta z:M7F_XEND              ; ...and runs the remaining N/2 lines\n",
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            T + "test_the_composed_band_matches_the_generator_at_the_spawn_pose",
            CYCLES + "[dive-pad1-40]",
        ],
        why="The band is two 80-line runs because an HDMA repeat count is seven "
            "bits, and the join has to walk over four control bytes it does not "
            "own. This work item's OWN second defect was exactly this joint — "
            "segment 1 began at table offset 7 instead of 327 and spent eighty "
            "lines overwriting segment 0 one byte off, with a floor still on "
            "screen. A bounds plant is the regression guard for the class.",
    ),
    # ---- the change gate: pinned clear (stale pose under input) ----------
    Plant(
        id="the-change-gate-never-arms",
        file=CAM,
        old="    lda z:M7F_DIRTY\n"
            "    beq @skip\n",
        new="    ; PLANT: the gate never opens, so the join runs only in m7f_arm\n"
            "    ;        and the rail flies the whole flight on the SPAWN\n"
            "    ;        pose's floor. The altitude state still moves, the\n"
            "    ;        shadow still reports it, the sky is still there —\n"
            "    ;        only the ground stops answering the stick.\n"
            "    lda z:M7F_DIRTY\n"
            "    and #0\n"
            "    beq @skip\n",
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            CYCLES + "[climb-pad0-40]",
            T + "test_the_skip_transitions_in_and_out_with_no_stale_frame",
        ],
        why="The skip is the rail's headroom lever and it gates the ONE thing "
            "the rail is for. Pinned clear it is not a performance change, it "
            "is a rail that no longer has an altitude axis — and it costs "
            "nothing visible on a still frame, which is exactly why the state "
            "cycles have to drive it rather than photograph it.",
    ),

    # ---- the change gate: armed for one buffer instead of two -------------
    Plant(
        id="the-change-gate-refreshes-only-one-buffer",
        file=CAM,
        old="    sta z:M7F_GEOOWED           ; both buffers owe a re-anchor\n"
            "    sta z:M7F_DIRTY             ; ...and their data\n",
        new="    ; PLANT: ONE buffer instead of two — the failure the countdown\n"
            "    ;        exists to prevent. The tick refreshes the back buffer\n"
            "    ;        once and then skips, so the swap alternates between\n"
            "    ;        this pose's table and the one from two frames ago:\n"
            "    ;        correct on every other frame, a frame stale between.\n"
            "    sta z:M7F_GEOOWED           ; both buffers owe a re-anchor\n"
            "    lsr a\n"
            "    sta z:M7F_DIRTY             ; ...and their data\n",
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            T + "test_the_streamed_buffer_is_exactly_one_frame_behind",
            T + "test_a_skipped_frame_renders_the_identical_picture",
        ],
        why="This is the plant the double buffer earns. A one-bit flag or a "
            "count of one both look right in a static screenshot and in any "
            "single-buffer assertion; what breaks is the RELATIONSHIP between "
            "the two tables across a swap, which only a case that reads both "
            "buffers against their own poses can see.",
    ),
    # ---- the moving horizon: pinned to the deck --------------------------
    Plant(
        id="the-horizon-never-moves-with-altitude",
        file=CAM,
        old="    lda z:M7F_ALTIDX\n"
            "    lsr a\n"
            "    lsr a                       ; a >> 2\n"
            "    asl a                       ; ...times M7F_BAND_STEP (2)\n",
        new="    ; PLANT: the band's shrink is pinned to zero, so the horizon\n"
            "    ;        sits at the deck's scanline 64 for the whole flight.\n"
            "    ;        Everything else still works — the ground still\n"
            "    ;        recedes with altitude, the shadow still reports it,\n"
            "    ;        the skip still gates — and the sky's share of the\n"
            "    ;        screen never changes, which is the ORIGINAL owner\n"
            "    ;        observation this piece exists to fix.\n"
            "    lda z:M7F_ALTIDX\n"
            "    and #0\n"
            "    lsr a                       ; a >> 2\n"
            "    asl a                       ; ...times M7F_BAND_STEP (2)\n",
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            T + "test_the_horizon_tracks_the_altitude_across_a_full_climb_and_dive",
            T + "test_the_skip_holds_byte_identity_across_a_re_anchor",
        ],
        why="A regression here is INVISIBLE in every assertion the rail had "
            "before this milestone: the band is still internally consistent, "
            "the oracle still matches (it reads the live geometry), the skip "
            "still works, the picture still has a horizon. What is lost is "
            "only that the horizon MOVES — a fact about the rendered split, "
            "which is why the case reads it off a screenshot.",
    ),

    # ---- the far-row curve: the clamp put back ---------------------------
    Plant(
        id="the-profile-clamps-and-the-far-field-goes-planar",
        file=GEN,
        old="S0_SPAN = 853",
        new="S0_SPAN = 960   # PLANT: the uncapped constant, which pushes s0 to\n"
            "                #        1120 and re-engages the min(255, S/4)\n"
            "                #        clamp. Four rows at the top of the band\n"
            "                #        collapse to ONE coefficient at max\n"
            "                #        altitude: a flat face-on horizon. The\n"
            "                #        band is still monotonic, still exact\n"
            "                #        against the oracle, still the right\n"
            "                #        length — only the far field stops\n"
            "                #        receding.",
        artifact=ROM,
        build=["m7f-assets", "mode7_flight"],
        tests=[
            T + "test_the_far_rows_keep_receding_at_the_top_of_the_climb",
        ],
        why="This is the defect that is visible by eye, and that an earlier "
            "reading of the clamp shipped. The whole-table oracle "
            "CANNOT catch it — the oracle asks whether the ROM matches the "
            "generator, and under this plant it does; both are wrong together. "
            "Only a case asserting the CURVE's shape sees it, which is why "
            "that case replaced the one that asserted the clamp.",
    ),
    # ---- the geometry gate: pinned stale ---------------------------------
    Plant(
        id="the-geometry-gate-never-re-arms",
        file=CAM,
        old="    sta z:M7F_GEOOWED           ; both buffers owe a re-anchor\n",
        new="    ; PLANT: the geometry gate never re-arms, so the band keeps the\n"
            "    ;        shape it was armed with at scene enter while the\n"
            "    ;        altitude moves under it. The DATA is still recomposed\n"
            "    ;        every frame and still matches the oracle for the\n"
            "    ;        standing geometry, the skip still works, the ground\n"
            "    ;        still recedes — only the HORIZON stops following the\n"
            "    ;        airship, and the fog band that anchors to it with it.\n"
            "    bit z:M7F_GEOOWED           ; both buffers owe a re-anchor\n",
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            T + "test_the_horizon_tracks_the_altitude_across_a_full_climb_and_dive",
            T + "test_the_skip_holds_byte_identity_across_a_re_anchor",
        ],
        why="THE CLAW-BACK'S OWN FAILURE MODE, and it is the one that would "
            "not show up in a cost measurement: gating the re-anchor is free "
            "headroom right up until the gate stops re-arming, at which point "
            "the rail silently reverts to milestone 0's fixed horizon while "
            "every band assertion still passes. The horizon-position case is "
            "what sees it — which is why that case reads the split off a "
            "SCREENSHOT rather than off the DP word the plant leaves correct.",
    ),

    # ---- the fog's anchor: nailed to the deck horizon --------------------
    Plant(
        id="the-fog-is-anchored-to-a-fixed-scanline",
        file=FLOOR,
        old="    lda z:M7F_HORIZON\n"
            "    sec\n"
            "    sbc #M7F_GRAD_RAMP\n",
        new="    ; PLANT: the COLDATA cursor is anchored to the DECK horizon\n"
            "    ;        instead of the live one — which is what every other\n"
            "    ;        consumer of rgb_gradient legitimately does, because\n"
            "    ;        their camera height never changes. Every declaration\n"
            "    ;        is still true, all three header tables are still\n"
            "    ;        well-formed, the split still moves, the band table\n"
            "    ;        still matches the oracle and M7F_HORIZON is still\n"
            "    ;        correct in DP. Only the haze stops following the\n"
            "    ;        horizon: it floats in open sky above the deck line\n"
            "    ;        and the real seam goes un-hazed.\n"
            "    lda #(M7F_BAND_BOT - M7F_LINES)\n"
            "    sec\n"
            "    sbc #M7F_GRAD_RAMP\n",
        artifact=ROM,
        build=["mode7_flight"],
        tests=[
            T + "test_the_fog_rides_the_moving_horizon_rather_than_a_fixed_scanline",
            T + "test_the_sky_is_the_generators_ramp_at_every_scanline[the ceiling-pad2-100]",
        ],
        why="THE TEAR THIS PIECE EXISTS TO PREVENT, and the only one on this "
            "rail whose whole evidence is the picture: under it every DP word "
            "is still right — the horizon, the band table, the split's count "
            "byte — because the stale thing is a WRAM header table nothing "
            "else reads. A state assertion cannot see it, so the plant proves "
            "the two cases that can are looking at the screen and at the LIVE "
            "horizon rather than at a constant.",
    ),
]
