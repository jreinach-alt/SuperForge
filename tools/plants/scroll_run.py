"""scroll_run's three load-bearing mechanisms, each planted and required RED.

The rail is the page-seam world, and its port
has exactly three mechanisms a plausible mistake could silently break:

  1. THE SEAM SPLIT — sr_build_map's page-1 pass reads the blob from world
     column 32. The copy-paste mistake (page 1 rebuilt from page 0's
     columns) leaves a ROM that boots, walks, jumps and WINS — collision
     probes the blob in world space and never notices — while the whole
     right half of the world displays the wrong picture. Only display
     surfaces can catch it, which is what makes it the plant worth running:
     it proves the module's VRAM/pixel assertions are not decoration.

  2. THE ONE-WAY STAND — the pixel-aligned bit-1 probe that keeps the
     runner standing on the goal pillar's top. Deleting it is exactly
     jumper's "the one-way branches are dead code" reading applied to the
     one rail where the condition does NOT hold. The crossing arm still
     re-lands the box each time it slips, so the failure is a subtle
     grounded/subpixel oscillation that only a per-frame trajectory
     comparison sees — the reason the module locksteps the whole rest.

  3. THE CAMERA'S RIGHT CLAMP — the follow's high arm. Without it the
     camera tracks past world 256 into the second page unclamped; every
     left-clamp and mid-world case stays green (they never reach it), which
     is why a one-direction camera test would ship this broken.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
BG = SUPERFORGE / "engine" / "features" / "sr_bg" / "sr_bg.asm"
SCENE = SUPERFORGE / "game" / "scroll_run" / "scenes" / "run.asm"
ROM = SUPERFORGE / "build" / "scroll_run.sfc"
T = "tests/test_scroll_run.py::"

PLANTS = [
    Plant(
        id="sr-page1-from-page0",
        file=BG,
        old="    ldx #SR_PAGE_DIM                ; blob offset: world column 32",
        new="    ldx #0                          ; PLANT: page 1 rebuilt from "
            "page 0's columns",
        artifact=ROM,
        build=["scroll_run"],
        tests=[
            T + "test_tilemap_both_pages_are_the_level_split_at_the_seam",
            T + "test_the_seam_columns_hold_the_platform_on_both_pages",
            T + "test_resting_exactly_on_the_seam_holds_still",
            T + "test_camera_regimes_left_clamp_tracking_right_clamp",
            T + "test_the_goal_ends_the_game_prints_GOAL_and_freezes",
        ],
        why="the copy-paste seam bug: page 1 shows page 0's columns. The "
            "game still boots, walks, jumps and WINS — col_map reads the "
            "blob in world coordinates and never consults the display — so "
            "every oracle-locked OAM case stays green and only the display "
            "surfaces (the 2048-word tilemap check, the named seam columns, "
            "the drawn strip's continuity, the world->screen pixel "
            "predictions, the goal's gold census) go red. Those five are "
            "named; a module without them ships half a world."),
    Plant(
        id="sr-ow-stand-dropped",
        file=SCENE,
        old="""    lda z:US_PYF
    xba
    and #$0007
    beq :+
    jmp @integrate                  ; mid-tile: fall""",
        new="""    lda z:US_PYF
    xba
    and #$0007
    jmp @integrate                  ; PLANT: the ow-stand probe never runs""",
        artifact=ROM,
        build=["scroll_run"],
        tests=[
            T + "test_the_goal_top_is_a_one_way_platform_and_the_win_works_backwards",
        ],
        why="the 'one-way branches are dead code' reading applied to the "
            "rail where its condition is FALSE (the goal tile carries bit "
            "1). The crossing arm still re-lands the slipping box, so the "
            "runner standing on the goal top micro-falls and re-lands in a "
            "subpixel cycle whose pyi drifts within three frames — caught "
            "only because the module locksteps the WHOLE rest against the "
            "oracle rather than sampling the rest y once."),
    Plant(
        id="sr-cam-high-clamp-dropped",
        file=SCENE,
        old="""    bcc @done                       ; <= max -> keep (TRACKING regime)
    lda #SR_CAM_MAX_X               ; > max -> pin at the far edge (CLAMPED)""",
        new="""    bcc @done                       ; PLANT: the high arm is gone""",
        artifact=ROM,
        build=["scroll_run"],
        tests=[
            T + "test_camera_regimes_left_clamp_tracking_right_clamp",
            T + "test_the_goal_ends_the_game_prints_GOAL_and_freezes",
            T + "test_the_goal_top_is_a_one_way_platform_and_the_win_works_backwards",
        ],
        why="the camera follows past world 256 unclamped. Boot, the left "
            "clamp, the tracking cases and every seam case are GREEN (none "
            "reaches world 384), which is precisely the one-direction-"
            "camera smell: only the right-edge cases — the drawn-content "
            "predictions at the won frame, its border pixel, and the "
            "oracle-locked drives past world 384 — go red."),
]
