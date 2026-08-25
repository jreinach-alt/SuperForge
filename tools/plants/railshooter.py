"""`pool`'s binding contract and the rail's two headline mechanisms, planted.

THE DEBUT THIS SET EXISTS FOR. `pool` supplies a
mechanism and claims one thing: `ES_POOL_PTR`, a 24-bit base the caller stamps
before every call. Three templates build against that contract next
(`m7_oshoot`, `boss`, `boss_saucer`), so "the tests would catch it" is not good
enough — the contract's arms are planted here and required RED:

    the BIND       drop a POOL_BIND and the routine walks the WRONG pool
    the CLAIM      drop pool_spawn's store and a slot is handed out twice
    the FREE       drop pool_kill's store and a slot leaks forever
    the COUNT      drop the count's bind and it answers about another pool;
                   drop its accumulate and it answers zero forever

The COUNT arm is planted TWICE on purpose. `pool_count` is the one routine that
mutates nothing, so both of its failure modes are invisible in the picture and
they fail in opposite directions — a mis-bound count reports somebody else's
population, a broken scan reports none. One plant would leave half of the case
that guards it unfalsified.

Plus the two mechanisms the rail's README headlines, which are independent of
the pool and of each other: the DEPTH-SORTED emit and the SIGNED lateral
projection.

EVERY PLANT REACHES RENDERED OUTPUT, which is not a slogan here. The sign plant
is the defect this rail actually shipped and it is TEST-BLIND at
the OAM layer by construction: the slot is still emitted, the tile is still
right, the order is still right, the size bit is still right — the sprite is
simply at screen x ~24,900, i.e. off the left edge. The only case that sees it
is the one that counts pixels, which is why that case exists and why this plant
names it alone.

THE REDESIGN ADDS SIX MORE, and three of those are planted in PAIRS
for the same reason the COUNT arm is — the two ways a mechanism can be wrong
fail in opposite directions, and one plant leaves half the case that guards it
unfalsified:

    the CURVE      a camera that never leaves centre / a camera that swings
                   only to ONE side (a rectified sine still looks like a curve)
    the DRAG       an aim point re-anchored to the camera: it still renders,
                   still answers the d-pad, and is no longer dragged
    the FEEDBACK   a kill with no flash — the shipped rail's actual defect,
                   with the hit test, the pool and the score all still working
    the DAMAGE     an arrival that never costs a segment / one that costs TWO

The DRAG plant is the one worth reading. asks for the drag to be
an EMERGENT CONSEQUENCE of the projection rather than a faked screen-space
nudge, and this plant is the faked version's mirror image — the shape an
implementer produces by accident. Under it every per-axis control case stays
green, because the reticle still moves the right way under every direction of
the pad. Only the case that measures the drag WITH NO INPUT AT ALL sees it.

NOT PLANTED, deliberately: the four-channel arming mask in `rail.asm`'s enter.
Dropping a channel is a real defect and the pixel cases would catch it, but the
same edit would break every case at once, so it would prove nothing about which
case is doing work. The set below breaks one mechanism at a time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
POOL = SUPERFORGE / "engine" / "features" / "pool" / "pool.asm"
OBJ = SUPERFORGE / "engine" / "features" / "rs_obj" / "rs_obj.asm"
LOGIC = SUPERFORGE / "engine" / "features" / "rs_logic" / "rs_logic.asm"
GEN = SUPERFORGE / "tools" / "gen_railshooter_assets.py"
RAIL = SUPERFORGE / "game" / "railshooter" / "scenes" / "rail.asm"
ROM = SUPERFORGE / "build" / "railshooter.sfc"
T = "tests/test_railshooter.py::"

PLANTS = [
    # ---- the binding contract, arm 1: the BIND ------------------------------
    Plant(
        id="pool-bind-dropped-before-spawn",
        file=LOGIC,
        old="    POOL_BIND ES_RS_ACTORS_LONG + RS_BUL_ALIVE\n"
            "    ldx #RS_BUL_N\n"
            "    jsr pool_spawn\n"
            "    bmi @done                       ; full: the press is swallowed",
        new="    ; PLANT: the bind is dropped — pool_spawn walks whatever pool\n"
            "    ;        the LAST caller bound, which is the hazard pool\n"
            "    ldx #RS_BUL_N\n"
            "    jsr pool_spawn\n"
            "    bmi @done                       ; full: the press is swallowed",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_pool_allocates_flies_frees_and_reuses_the_slot",
            T + "test_a_full_tracer_pool_swallows_the_extra_press",
        ],
        why="THE CONTRACT `pool` IS BUILT ON. Its one claim is a base pointer "
            "the caller stamps per call, and a consumer that forgets the stamp "
            "gets a routine operating on somebody else's pool — silently, "
            "because the pointer still holds a valid WRAM address. Three "
            "templates bind against this contract next — `m7_oshoot` and "
            "`boss` with two pools each, `boss_saucer` with one — so it has "
            "to be the thing that goes red, not a build error"),

    # ---- the binding contract, arm 2: the CLAIM -----------------------------
    Plant(
        id="pool-spawn-does-not-claim-the-slot",
        file=POOL,
        old="    lda #1\n"
            "    sta [ES_POOL_PTR], y                ; claim it before anyone can rescan",
        new="    lda #1\n"
            "    ; PLANT: the claim store is dropped — every spawn hands out\n"
            "    ;        slot 0 and no actor is ever alive",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_pool_allocates_flies_frees_and_reuses_the_slot",
            T + "test_a_full_tracer_pool_swallows_the_extra_press",
        ],
        why="pool_spawn marks the slot live BEFORE returning precisely so a "
            "caller that forgets to fill the parallel arrays leaks a slot "
            "rather than double-claiming it. Without the store every spawn "
            "answers slot 0, and the four-shot pool becomes a zero-shot pool"),

    # ---- the binding contract, arm 3: the FREE ------------------------------
    Plant(
        id="pool-kill-leaks-the-slot",
        file=POOL,
        old="    txy                                 ; the cursor moves to the only index\n"
            "    lda #0                              ;   register [dp],y can use\n"
            "    sta [ES_POOL_PTR], y",
        new="    txy                                 ; the cursor moves to the only index\n"
            "    lda #0                              ;   register [dp],y can use\n"
            "    ; PLANT: the free store is dropped — the slot never returns",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_pool_allocates_flies_frees_and_reuses_the_slot",
        ],
        why="a pool that allocates and never frees passes any test that only "
            "fires once — which is exactly why the REUSE case exists. This is "
            "the plant that proves the reuse case is doing work rather than "
            "re-proving the spawn"),

    # ---- the binding contract, arm 4: the COUNT ------------------------------
    Plant(
        id="pool-count-bind-dropped-for-the-hazards",
        file=LOGIC,
        old="    POOL_BIND ES_RS_ACTORS_LONG + RS_OBS_ALIVE\n"
            "    ldx #RS_OBS_N\n"
            "    jsr pool_count\n"
            "    sta f:US_HAZARDS_LIVE_LONG",
        new="    ; PLANT: the second bind is dropped — the hazard census is taken\n"
            "    ;        over the BULLET pool the first call left bound\n"
            "    ldx #RS_OBS_N\n"
            "    jsr pool_count\n"
            "    sta f:US_HAZARDS_LIVE_LONG",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_published_pool_count_matches_the_actors_on_screen",
        ],
        why="THE BIND ARM AGAIN, on the routine that answers a QUESTION rather "
            "than mutating a pool — and the one where a dropped stamp is "
            "hardest to notice. The other three arms change what is on screen; "
            "a mis-bound count changes only a number, so if nothing asserted "
            "the number against the actors it describes, this defect would "
            "ship. `m7_oshoot` gates a spawn on that number and reads it for a "
            "wave-clear, so a count taken over the "
            "wrong pool there means enemies that never respawn or a wave that "
            "never ends. The plant leaves both counts being TAKEN and STORED — "
            "only the base is stale, which is exactly the shape a mechanical "
            "port produces when it copies a call and forgets the stamp"),

    Plant(
        id="pool-count-misses-the-live-slots",
        file=POOL,
        old="    lda [ES_POOL_PTR], y\n"
            "    beq @skip\n"
            "    inx\n",
        new="    lda [ES_POOL_PTR], y\n"
            "    beq @skip\n"
            "    ; PLANT: the accumulate is dropped — every pool reads empty\n",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_published_pool_count_matches_the_actors_on_screen",
        ],
        why="the arithmetic half, planted separately from the binding half "
            "because they fail in opposite directions and one plant cannot "
            "prove both. With the accumulate gone `pool_count` still scans "
            "every slot, still returns in A and still answers a number in "
            "range — it answers ZERO, forever. That is the reading a HUD would "
            "render without complaint and the value a `beq wave_cleared` would "
            "act on immediately. It goes red here only because the case "
            "compares the count against the tracers ON SCREEN across a cycle "
            "that includes a non-empty pool; a case that sampled the count at "
            "idle alone would stay green"),

    # ---- the rail's headline: the depth-sorted emit --------------------------
    Plant(
        id="rail-emit-in-pool-slot-order",
        file=OBJ,
        old="    lda f:ES_RS_CACHE_LONG + RSC::tier, x\n"
            "    cmp RSD_PASS\n"
            "    bne @next",
        new="    ; PLANT: the tier filter is dropped — every visible actor is\n"
            "    ;        emitted on the tier-0 pass, i.e. in POOL SLOT order\n"
            "    lda RSD_PASS\n"
            "    bne @next",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_hazard_window_is_depth_ordered_on_every_frame",
            T + "test_all_four_pre_drawn_tiers_render_at_their_hardware_size",
        ],
        why="the defect the two-pass emit exists to prevent, and the rail "
            "rail's own rail_draw.asm names it: a fixed pool-slot -> OAM-slot "
            "map layers by pool identity rather than by depth, so a recycled "
            "hazard keeps its old slot's order and pops in front of something "
            "nearer. The plant leaves the projection, the cache and the pool "
            "untouched — only the ORDER changes"),

    # ---- the rail's other headline: the SIGNED lateral projection -----------
    Plant(
        id="rail-projection-loses-the-sign",
        file=OBJ,
        old="    ldx #0                          ; assume positive\n"
            "    cmp #(1 << 15)                  ; carry set = the sign bit is set\n"
            "    bcc @dx_abs",
        new="    ldx #0                          ; PLANT: the flags now come from\n"
            "    bpl @dx_abs                     ;   the LDX, so every leftward dx\n"
            "    nop                             ;   takes the positive path",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_hazard_window_matches_an_independent_projection_oracle",
        ],
        why="THE DEFECT THIS RAIL ACTUALLY SHIPPED, restored verbatim "
            ". It is TEST-BLIND at the OAM layer by construction — "
            "the slot is emitted, the tile, order and size bit are all correct, "
            "and the sprite simply lands somewhere else. MEASURED: the "
            "screen-side count of hazard rim pixels left of the ship column "
            "only falls from 812 to 682 under it, because a garbage product "
            "still lands on screen about half the time — so that case is NOT "
            "sufficient and this plant is what proved it. What sees it is the "
            "independent projection ORACLE, which compares the whole window "
            "against a second implementation of the pinhole"),
    # =========================================================================
    # THE REDESIGN'S FOUR NEW MECHANISMS. One plant each, chosen so
    # the set can say WHICH case is doing work rather than "something broke".
    # =========================================================================

    # ---- the CURVE DRIVER: translation, and both bends ----------------------
    Plant(
        id="rail-curve-never-leaves-the-centre",
        file=LOGIC,
        old="    jsr rs_path_at\n"
            "    clc\n"
            "    adc #RS_CENTRE\n"
            "    and #RS_WORLD_MASK\n"
            "    sta z:US_CAM_X",
        new="    ; PLANT: the path's offset is discarded — the camera sits on the\n"
            "    ;        rail's centre column forever and the S-curve is flat\n"
            "    jsr rs_path_at\n"
            "    lda #RS_CENTRE\n"
            "    and #RS_WORLD_MASK\n"
            "    sta z:US_CAM_X",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_camera_translates_across_a_full_s_period_and_the_floor_returns",
            T + "test_the_swing_drags_the_reticle_and_the_d_pad_corrects_it_back",
        ],
        why=" is the whole redesign, and this is the shape a "
            "half-finished implementation takes: the table is still read, the "
            "odometer still advances, the ship still banks (the bank comes "
            "from a different read of the same table), and the camera never "
            "moves. Everything a proxy-variable test would look at is still "
            "alive. What dies is the PICTURE — the plane stops translating and "
            "the world-anchored reticle stops being dragged, which is exactly "
            "the pair the two named cases measure"),

    # ---- the CURVE'S SECOND BEND: the S must cross over ---------------------
    Plant(
        id="rail-curve-rectified-into-one-bend",
        file=LOGIC,
        old="    jsr rs_path_at\n"
            "    clc\n"
            "    adc #RS_CENTRE\n"
            "    and #RS_WORLD_MASK\n"
            "    sta z:US_CAM_X",
        new="    ; PLANT: the path is RECTIFIED — |offset| instead of offset, so\n"
            "    ;        the camera swings out and back on ONE side only and\n"
            "    ;        the S becomes a repeated single bend\n"
            "    jsr rs_path_at\n"
            "    jsr rs_abs16\n"
            "    clc\n"
            "    adc #RS_CENTRE\n"
            "    and #RS_WORLD_MASK\n"
            "    sta z:US_CAM_X",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_camera_translates_across_a_full_s_period_and_the_floor_returns",
        ],
        why="PLANTED SEPARATELY FROM THE ONE ABOVE, because the two fail in "
            "different directions and the first plant cannot prove the second "
            "half of the case. A camera that never moves is obvious; a camera "
            "that moves a lot but only ever to ONE SIDE looks like a working "
            "curve in every still and in any test that only measures a span. "
            " asks for a REPEATING S and §3 makes both bends "
            "mandatory, so the half-period mirror assertion has to be the "
            "thing that goes red — and under this plant it is the ONLY one "
            "that does"),

    # ---- the DRAG: the reticle is anchored in WORLD space -------------------
    Plant(
        id="rail-reticle-pinned-to-the-camera",
        file=OBJ,
        old="    lda f:US_RET_X_LONG\n"
            "    sta RSD_OBJX\n"
            "    lda f:US_RET_Z_LONG\n"
            "    sta RSD_Z\n"
            "    lda z:US_CAM_X\n"
            "    sta RSD_CAMX",
        new="    ; PLANT: the aim point is re-anchored to the CAMERA — it still\n"
            "    ;        projects, still moves with the d-pad relative to the\n"
            "    ;        ship, and is no longer dragged by the swing at all\n"
            "    lda f:US_RET_X_LONG\n"
            "    sec\n"
            "    sbc #RS_CENTRE\n"
            "    clc\n"
            "    adc z:US_CAM_X\n"
            "    sta RSD_OBJX\n"
            "    lda f:US_RET_Z_LONG\n"
            "    sta RSD_Z\n"
            "    lda z:US_CAM_X\n"
            "    sta RSD_CAMX",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_swing_drags_the_reticle_and_the_d_pad_corrects_it_back",
            T + "test_the_camera_translates_across_a_full_s_period_and_the_floor_returns",
        ],
        why=" says the reticle is anchored in WORLD space so the "
            "swing drags it AS AN EMERGENT CONSEQUENCE of the projection, and "
            "explicitly not as a faked screen-space nudge. This plant is the "
            "faked version's mirror image and it is the one a reasonable "
            "implementer might write by accident: the reticle still renders, "
            "still moves under every d-pad direction, still sits on the ground "
            "plane, still projects through the same pinhole. It simply travels "
            "WITH the ship, so there is nothing to compensate for and the "
            "skill demand is gone. Every per-axis control case stays green "
            "under it — the drag case is what sees it"),

    # ---- the HIT FEEDBACK: a kill must not resemble a miss ------------------
    Plant(
        id="rail-kill-leaves-no-flash",
        file=LOGIC,
        old="    lda #RS_BURST_FRAMES\n"
            "    sta f:US_BURST_T_LONG",
        new="    ; PLANT: the flash is never armed — the hazard still dies, the\n"
            "    ;        score still moves, and the kill looks like a hazard\n"
            "    ;        that simply flew past. THE SHIPPED RAIL'S DEFECT.\n"
            "    lda #0\n"
            "    sta f:US_BURST_T_LONG",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_a_kill_and_a_miss_are_distinguishable_in_the_rendered_output",
            T + "test_firing_on_target_destroys_it_flashes_and_moves_the_score",
        ],
        why="THIS IS THE DEFECT WAS WRITTEN ABOUT, in its purest form. "
            "The shipped rail's hit test WORKED — audit-verified — and the "
            "owner still could not tell it was checking, because a killed "
            "hazard left the same way one that flew past did. Under this plant "
            "the hit test still works, the pool still frees the slot, the "
            "score still increments: every mechanism is intact and the "
            "FEEDBACK is gone. A test suite that asserted only on the pool and "
            "the score would be entirely green on the exact bug the redesign "
            "exists to fix"),

    # ---- the DAMAGE PATH: exactly one segment, five hits, the fail state ----
    Plant(
        id="rail-arrival-never-costs-a-life",
        file=LOGIC,
        old="    jsr rs_abs16\n"
            "    cmp #RS_SHIP_HIT_X\n"
            "    bcs @free                       ; it passed wide — no harm\n"
            "    jsr rs_hurt",
        new="    ; PLANT: every arrival is treated as a wide pass — nothing can\n"
            "    ;        hurt the player and the life bar never moves\n"
            "    jsr rs_abs16\n"
            "    cmp #RS_SHIP_HIT_X\n"
            "    bcs @free\n"
            "    nop",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_a_hazard_reaching_the_ship_costs_exactly_one_life_segment",
            T + "test_five_hits_empty_the_bar_and_the_rail_restarts_itself",
            T + "test_the_fail_state_clears_the_field_and_the_rail_returns",
        ],
        why="'s whole point is that NOTHING COULD CURRENTLY HURT "
            "THE PLAYER — the damage path is new, so it is the one mechanism "
            "here with no prior art to lean on. Under this plant the bar still "
            "renders five segments, the hazards still arrive and are still "
            "freed on arrival, and the rail simply never ends. It is also the "
            "plant that proves the EXACTLY-ONE assertion is doing work: a bar "
            "that never moves and a bar that drops two at a time are the two "
            "ways that case can be wrong, and this is the first of them"),

    # ---- the DAMAGE PATH, second arm: exactly ONE ---------------------------
    Plant(
        id="rail-arrival-costs-two-life-segments",
        file=LOGIC,
        old="    lda f:US_LIVES_LONG\n"
            "    beq @done                       ; already out; nothing left to take\n"
            "    dec a\n"
            "    sta f:US_LIVES_LONG",
        new="    ; PLANT: an arrival costs TWO segments — the bar still empties\n"
            "    ;        and the rail still fails, just not one hit at a time\n"
            "    lda f:US_LIVES_LONG\n"
            "    beq @done\n"
            "    dec a\n"
            "    dec a\n"
            "    sta f:US_LIVES_LONG",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_a_hazard_reaching_the_ship_costs_exactly_one_life_segment",
        ],
        why="the other direction, planted separately for the reason the COUNT "
            "arm is: a bar that never moves and a bar that moves too far are "
            "opposite failures and one plant cannot falsify both halves of "
            "'EXACTLY one'. This one is the sneakier of the two — the bar "
            "still empties, five hits still reach the fail state (in three), "
            "the demo still loops. Only a case that samples EVERY frame and "
            "checks the step size sees it, which is why that case does"),

    # ---- the CURVE'S TEMPORAL RESOLUTION -----------------------------------
    Plant(
        id="rail-curve-quantised-to-every-fourth-frame",
        file=LOGIC,
        old="rs_path_at:\n"
            "    .a16\n"
            "    .i16\n"
            "    .repeat ::RS_PATH_SHIFT",
        new="rs_path_at:\n"
            "    .a16\n"
            "    .i16\n"
            "    ; PLANT: the odometer is quantised to every fourth frame before\n"
            "    ;        the lookup — bit-for-bit the sampling the shipped\n"
            "    ;        64-entry table had, without touching the baked curve\n"
            "    and #$FFFC\n"
            "    .repeat ::RS_PATH_SHIFT",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_curve_moves_the_picture_every_frame_and_never_in_lurches",
        ],
        why="THE DEFECT THIS RAIL ACTUALLY SHIPPED, and a review rated it HIGH: "
            "the S-curve was delivered at 15 Hz, so the whole Mode 7 plane held "
            "perfectly still for three frames and then jumped up to 21 screen "
            "px sideways, forever, on the redesign's headline mechanic. It is "
            "planted here rather than by shrinking the table because THAT is "
            "the shape a regression takes: the data stays right and the "
            "sampling goes coarse. Note what stays GREEN under it — the camera "
            "still translates, both bends still happen, a full period still "
            "returns the floor byte-identically, the drag is still real and "
            "still correctable, the pose still never moves. Every acceptance "
            "criterion as literally worded passes, which is exactly why the "
            "smoothness case had to exist and why nothing caught this before "
            "the audit measured the picture frame by frame"),

    # ---- power-on fidelity: the read-before-write ordering ------------------
    Plant(
        id="rail-reads-the-pool-before-checking-alive",
        file=OBJ,
        old="rs_cache_one:\n"
            "    .a16\n"
            "    .i16\n"
            "    lda f:ES_RS_ACTORS_LONG + RS_F_ALIVE, x\n"
            "    beq @dead",
        new="rs_cache_one:\n"
            "    .a16\n"
            "    .i16\n"
            "    ; PLANT: the shipped read-before-check ordering, restored. The\n"
            "    ;        alive test still gates the DRAW, so the picture is\n"
            "    ;        unchanged — only the detector sees it.\n"
            "    lda f:ES_RS_ACTORS_LONG + RS_F_WX, x\n"
            "    lda f:ES_RS_ACTORS_LONG + RS_F_Z, x\n"
            "    lda f:ES_RS_ACTORS_LONG + RS_F_TIER, x\n"
            "    lda f:ES_RS_ACTORS_LONG + RS_F_ALIVE, x\n"
            "    beq @dead",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_rail_reads_no_uninitialised_wram",
        ],
        why="This is the one plant in the set whose defect CANNOT "
            "reach the picture by construction — RSC::vis is stamped 0 for a "
            "dead slot and both consumers gate on it — so no rendered-output "
            "case can falsify it and the uninit detector is the only "
            "instrument that can. It is planted precisely to prove that case "
            "is armed, because a power-on-fidelity assertion that nothing can "
            "turn red is decoration. On real hardware the fields it reads are "
            "DRAM garbage, and the garbage tier indexes a 24-byte table "
            "unmasked"),

    # -- THE LOAD-BEARING constraint: TRANSLATION, not ROTATION --
    Plant(
        id="rail-curve-rotates-the-plane-again",
        file=RAIL,
        old="    jsr rs_path_step            ; the S-curve: the odometer -> the camera's x\n"
            "    jsr rs_advance              ; the rail walks forward, always",
        new="    jsr rs_path_step            ; the S-curve: the odometer -> the camera's x\n"
            "    ; PLANT: the pose retarget is RE-ARMED, on the S period, so the\n"
            "    ;        plane rotates with the curve — the quantised mechanism\n"
            "; forbids and the redesign DELETED\n"
            "    lda f:US_DIST_LONG\n"
            "    lsr a\n"
            "    lsr a\n"
            "    and #$003F\n"
            "    jsr persp_set_pose\n"
            "    jsr rs_advance              ; the rail walks forward, always",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_pose_transport_is_untouched_for_a_whole_s_period",
        ],
        why="The redesign's HEADLINE guarantee — 'the plane never "
            "rotates' — had no falsification evidence at all. The structural "
            "argument is strong (both heading words are gone from state.toml "
            "and persp_set_pose is called once, from enter, with 0), but a "
            "structural argument is not a test, and the case that would catch "
            "a regression was unproven. The heading here is driven on the S "
            "period ON PURPOSE, so it returns after 256 frames and the curve's "
            "own cases stay GREEN: rs_project never reads the heading, so the "
            "reticle sweeps identically and the floor still comes back "
            "byte-identical at a full period. Only the transport read sees "
            "it — which is the whole reason that case reads ES_PERSP_IDX and, "
            "since F7, ES_SM_HDMA as well"),

    # ---- the bank RAMP, arm 1: the rate limiter ----------------------------
    Plant(
        id="rail-bank-snaps-instead-of-rolling",
        file=LOGIC,
        old="    lda f:US_LEAN_LONG\n"
            "    cmp RSL_T1\n"
            "    beq @done                       ; already there\n"
            "    bcs @ease_down\n"
            "    inc a\n"
            "    bra @ease",
        new="    ; PLANT: the pose jumps straight to the target — the ship\n"
            "    ;        flips from level to hard over in ONE frame\n"
            "    lda RSL_T1\n"
            "    bra @ease\n"
            "    nop\n"
            "    nop",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_ship_rolls_in_from_level_at_scene_enter_rather_"
                "than_snapping",
        ],
        why="THE DEFECT THIS RAIL SHIPPED, in its residual form. Grading the "
            "slope into four steps is most of the ramp, but it is NOT all of "
            "it, and the difference is measurable: with the limiter gone and "
            "the ladder kept, a whole S period still shows no skipped pose, "
            "because the sine's own slope moves slowly inside a bend. Scene "
            "enter is the transition that bites — the odometer resets to 0 "
            "where the slope is at its maximum, so the ship's first bank is "
            "its last. That is why the roll-in case exists separately from "
            "the period case, and this plant is what makes the separation "
            "evidence rather than an assertion"),

    # ---- the bank RAMP, arm 2: the ROLL, in the art ------------------------
    Plant(
        id="rail-bank-is-a-shear-not-a-roll",
        file=GEN,
        old="    phi = math.radians(-BANK_DEG * bank)",
        new="    phi = math.radians(-BANK_DEG * bank)\n"
            "    phi = 0.0  # PLANT: every pose renders the LEVEL hull",
        artifact=ROM,
        build=["railshooter"],
        tests=[
            T + "test_the_ship_is_form_shaded_and_the_shading_ROLLS_WITH_"
                "THE_HULL",
        ],
        why="THE OTHER HALF OF THE SHIPPED DEFECT, and the one every "
            "tile-index case in the module is blind to. The shipped bank was "
            "a per-row SHEAR of the level frame: the silhouette slid and not "
            "one pixel changed tone. Under this plant the five poses still "
            "occupy five CHR lanes, the OAM tile still advances one step a "
            "frame and the H-flip still fires — so the ramp cases stay GREEN "
            "— and only the case that reads the hull's tone either side of "
            "the ship's centre line sees that the hull is not rolling. It "
            "patches the GENERATOR rather than ASM because the roll lives in "
            "the art, which is exactly where a review would forget to look"),
]
