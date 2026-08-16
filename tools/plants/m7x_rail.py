"""mode7_explore — three defects the rail's tests must be able to see.

Each is a defect a REASONABLE change to this rail would actually produce, which
is the bar `Plant.why` exists to hold. None of them stops the build, and that is
the point: all three are the silent class — the ROM assembles, boots, and shows
a plausible world.

WHY THESE THREE. They are one per mechanism the rail composes, and each aims at
a test whose name claims to cover it:

  bank      the streamer's blob binding — the failure mode where
            `T0_BANK + i` addressing reads someone else's ROM
  vmain     the seed upload's VRAM address increment — the trap m7x_floor.asm's
            header spends a paragraph on
  diagonal  the input dispatch's fall-through, which is the behaviour a port
            "tidies away" precisely because it looks like a missing `bra`

...and four more for the TOWN slice, same bar. Two of them are defects this
rail has actually had:

  town-vram-unpinned  the interior's CHR claim without its `at` — the packer
            first-fits from word 0 and the Mode 7 image the return re-uses goes
            under it. This is the single declaration the whole "no re-stream"
            design rests on
  swap-at-arm  raising the swap request where the wipe is ARMED instead of in
            the callback at PEAK BLACK. THIS RAIL SHIPPED IT for one build
  town-input-level  reading the pad at LEVEL in the interior, which is what the
            overworld does five files away and therefore what a port copies
  town-no-resync  the return leaving the streamer's tracking as the town left
            it — the state-cycle defect that only appears on the FIRST STEP
            after coming back out

NOT PLANTED HERE, and stated rather than omitted: the pivot lift. Setting
`MXL_PIVOT_LIFT = 0` shifts the whole picture sixteen world pixels vertically
and NOTHING in this module's unconditional tests can see it — the window oracle
is built from the camera, which does not move, and the avatar stays pinned. The
one test that catches it is
`test_the_boot_frame_matches_the_reference_render`, which SKIPS unless
`SF_REFERENCE_TREE` names a tree holding the reference render. That is a real,
bounded coverage statement and it belongs in the record: verified by hand where
that render is on disk (the plant turns it red, 3,700-odd pixels), left out of
the automated set because a plant whose only witness can skip reports
TEST-BLIND on a bare runner and would read as a hole that is not one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "mode7_explore" / "scenes" / "overworld.asm"
FLOOR = SUPERFORGE / "engine" / "features" / "m7x_floor" / "m7x_floor.asm"
LOGIC = SUPERFORGE / "engine" / "features" / "m7x_logic" / "m7x_logic.asm"
TOWN = SUPERFORGE / "engine" / "features" / "m7x_town" / "m7x_town.asm"
TOWN_TOML = SUPERFORGE / "engine" / "features" / "m7x_town" / "feature.toml"
ROM = SUPERFORGE / "build" / "mode7_explore.sfc"
T = "tests/test_mode7_explore.py"

PLANTS = [
    # ---- the streamer reads the wrong bank ------------------------------
    Plant(
        id="stream-blob-bank",
        file=SCENE,
        old="M7S_BLOB_BANK = ::ES_R_M7X_MAP_T0_BANK",
        new="M7S_BLOB_BANK = ::ES_R_M7X_MAP_T0_BANK + 1",
        artifact=ROM,
        build=["mode7_explore"],
        tests=[f"{T}::test_walking_streams_the_window_in_every_direction"],
        why="this is the review's finding as an actual defect. mode7_stream's MVN "
            "stub table derives chunk i's source bank as T0_BANK + i, and the "
            "packer does not GUARANTEE consecutive chunks — it merely produces "
            "them today. An off-by-one bank streams a perfectly plausible "
            "world out of the wrong rows with every build gate green, which is "
            "the silent class. The window test claims to prove the streamer "
            "loads THE WORLD; if it cannot see a whole-bank shift, its name is "
            "a lie",
    ),
    # ---- the seed lands in the wrong VRAM words --------------------------
    Plant(
        id="seed-vmain",
        file=FLOOR,
        old="    lda #$80\n"
            "    sta a:$2115                     ; VMAIN: +1 word after the $2119 write",
        new="    lda #$00                        ; PLANT: advance after the LOW byte\n"
            "    sta a:$2115",
        artifact=ROM,
        build=["mode7_explore"],
        tests=[f"{T}::test_the_seed_is_the_world_around_spawn"],
        why="VMAIN $00 advances the VRAM address after the LOW byte instead of "
            "the high one, so the interleaved blob's every high byte "
            "overwrites the wrong word. It is the default value, so it is what "
            "you get by forgetting the register rather than by choosing wrong "
            "— the cheapest possible mistake — and the result is still a "
            "textured Mode 7 plane. The seed test claims the window holds the "
            "world; this is the defect that makes it hold a scramble of it",
    ),
    # ---- the diagonal fall-through, tidied away --------------------------
    Plant(
        id="diagonal-fallthrough",
        file=LOGIC,
        old="    jsr mxl_try_step\n"
            "    lda z:US_STEP_ACTIVE\n"
            "    bne @done\n"
            "@chk_up:",
        new="    jsr mxl_try_step\n"
            "    lda z:US_STEP_ACTIVE\n"
            "    bra @done                       ; PLANT: no fall-through\n"
            "@chk_up:",
        artifact=ROM,
        build=["mode7_explore"],
        tests=[f"{T}::test_a_held_diagonal_keeps_moving_along_the_open_axis"],
        why="`bne @done` after a try that may have been REFUSED is the line a "
            "reader tidies to `bra @done` on the reasonable-sounding grounds "
            "that the axis was already handled. It is the difference between a "
            "held diagonal sliding along a wall and the avatar freezing against "
            "it, and it is invisible in every single-axis test — which is why "
            "the source comment says the fall-through is deliberate and why this "
            "test exists at all",
    ),
    # ---- the interior's VRAM claim, unpinned -----------------------------
    Plant(
        id="town-vram-unpinned",
        file=TOWN_TOML,
        old='kind = "chr"\ntiles = 4\ntile_bytes = 32          # 4bpp\nat = 0x5000',
        new='kind = "chr"\ntiles = 4\ntile_bytes = 32          # 4bpp',
        artifact=ROM,
        build=["mode7_explore"],
        tests=[f"{T}::test_the_mode7_image_survives_the_visit"],
        why="`at = 0x5000` is the one declaration the whole town design rests "
            "on, and dropping it is the most ordinary edit imaginable — a pin "
            "looks like over-specification, the allocator packs everything "
            "else, and the ROM builds and the room renders either way. But the "
            "town scene composes no `mode7` claim, so a PACKED chr claim "
            "first-fits from word 0 and lands squarely on the Mode 7 image the "
            "return re-uses without a re-stream. The survival test claims the "
            "32 KB region comes back byte-identical; if it cannot see the "
            "interior written on top of it, it is not testing anything",
    ),
    # ---- the swap request raised at ARM instead of at peak black ---------
    Plant(
        id="swap-at-arm",
        file=SCENE,
        old="    sep #$20\n"
            "    .a8\n"
            "    lda #TM_BG1                     ; the affected-BG nibble for $2106: BG1 only\n"
            "    ldx #.loword(::mxx_blank_to_town)   ; the swap callback — see its header",
        new="    lda #::SWAP_TO_TOWN             ; PLANT: request it HERE, not at peak black\n"
            "    sta z:US_SWAP_REQ\n"
            "    sep #$20\n"
            "    .a8\n"
            "    lda #TM_BG1                     ; the affected-BG nibble for $2106: BG1 only\n"
            "    ldx #.loword(::mxx_blank_to_town)   ; the swap callback — see its header",
        artifact=ROM,
        build=["mode7_explore"],
        tests=[f"{T}::test_the_avatar_is_hidden_while_the_wipe_runs",
               f"{T}::test_the_return_lands_on_the_same_picture"],
        why="THIS RAIL SHIPPED THIS, for one build, and it is the obvious way "
            "to write it: you know which way you are going at the moment you "
            "arm, so you say so. The consequence is twenty frames away — "
            "mxx_swap_service fires on the very NEXT frame, with a fully-lit "
            "picture on screen, so the 2 KB VRAM rebuild runs without forced "
            "blank and the whole dissolve then plays over an already-swapped "
            "scene. Nothing about the ROM says so: it boots, it wipes, it ends "
            "up in the town. Caught on the emulator by reading the state block "
            "per frame, which is what these two tests do with OAM and pixels",
    ),
    # ---- the interior reading the pad at LEVEL ---------------------------
    Plant(
        id="town-input-level",
        file=TOWN,
        old="    lda z:ES_INP_PRESS\n"
            "    bit #TOWN_JOY_LEFT",
        new="    lda z:ES_INP_CUR                ; PLANT: level, like the overworld\n"
            "    bit #TOWN_JOY_LEFT",
        artifact=ROM,
        build=["mode7_explore"],
        tests=[f"{T}::test_the_town_walk_steps_one_tile_per_press_and_the_room_refuses"],
        why="the overworld reads ES_INP_CUR at LEVEL and it is five files away, "
            "so `PRESS` vs `CUR` is a one-word difference between two routines "
            "that otherwise look the same — exactly what a port copies without "
            "noticing. At level a held direction crosses the 27-tile room in "
            "under half a second and the interior stops reading as a grid. The "
            "walk test's name claims one tile per press; a version that only "
            "pressed once and released would pass on this",
    ),
    # ---- the return not re-seeding the streamer --------------------------
    Plant(
        id="town-no-resync",
        file=SCENE,
        old="    jsr stream_resync               ; tracking re-seeded from the restored camera",
        new="                                    ; PLANT: no re-seed on the way back",
        artifact=ROM,
        build=["mode7_explore"],
        tests=[f"{T}::test_the_streamer_still_works_after_the_return"],
        why="the streamer is not RUNNING while she is indoors, so leaving its "
            "tracking alone across the visit is the natural assumption — and it "
            "is wrong for a reason nothing at the call site shows: that "
            "tracking is SCENE DP, and the interior's own state is allocated on "
            "top of it (town_tx lands on ST_LAST_TY, town_ty on the two pending "
            "counts). What makes it worth planting is that it HEALS: the "
            "streamer walks its stale LAST toward the true camera at eight "
            "tiles a frame and rewrites every column on the way, so the window "
            "is wrong for about thirty frames — 8,054 of 16,384 words at the "
            "worst, measured — and then looks right again. Half a second of "
            "wrong world that any test reading the window ONCE, LATE, calls a "
            "pass. That is what the span of assertions in the named test is "
            "for, and this plant is what proves the span is doing work",
    ),
]
