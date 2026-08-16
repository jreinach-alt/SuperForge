"""jumper — the physics traps this rail's tests claim to close, planted.

Three plants, each the DOCUMENTED failure mode its test names:

  * the landing snap off by the box height — the repo's apex-only trap
    (CLAUDE.md: "a snap that is off by the box height embeds the sprite in
    the floor while every apex assertion still passes"). The whole-trajectory
    oracle must go red AT THE LANDING INDEX while the boot case (which never
    lands from a fall) stays green — a discriminating red, not a everything-
    breaks red.
  * the terminal clamp dropped — only the LONG fall (the free jump's 39 px
    descent) ever reaches the clamp, so this is exactly the defect a
    threshold assertion (`max(delta) <= 4`) cannot see on a short fall and
    the frame-for-frame oracle can: the walk-off's 32 px drop never engages
    the clamp and stays green, the full arc diverges in its last ticks.
  * the jump gate read level instead of edge (ES_INP_CUR for ES_INP_PRESS) —
    hud_game's plant 2, on this rail's surface: held A must not auto-rejump
    on landing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "jumper" / "scenes" / "sky.asm"
ROM = SUPERFORGE / "build" / "jumper.sfc"

PLANTS = [
    Plant(id="landing-snap-minus-8-dropped",
          file=SCENE,
          old="""    sec
    sbc #8                          ; box top = tile top - box height""",
          new="""    ; PLANT: snap -8 dropped — box top lands AT the tile top (embedded)""",
          artifact=ROM,
          build=["jumper"],
          tests=[
              "tests/test_jumper.py::test_jump_full_cycle_matches_the_oracle_every_frame",
              "tests/test_jumper.py::test_walk_off_the_ledge_falls_clamped_and_lands_below",
          ],
          why="the landing frame is where the bugs live, not the apex: this "
              "embeds the sprite one box-height into the floor on every FAST "
              "landing while the apex stays exactly right. Scoped to the two "
              "cases whose landings execute the SNAP branch — measured, not "
              "assumed (the first cut of this plant named four tests and two "
              "stayed green): the integrator has TWO landing paths, and a "
              "slow arc-top approach (the platform touchdown, the bonk "
              "resettle) is caught by the 1px-below STAND probe before the "
              "snap arm ever runs, so this plant cannot reach those "
              "landings. Only a fall arriving faster than 1 px/frame at "
              "pixel-adjacency (the free jump's terminal-velocity ground "
              "landing, the ledge drop) goes through the snap"),
    Plant(id="terminal-clamp-dropped",
          file=SCENE,
          old="""    cmp #JR_MAX_FALL
    bcc @noclamp
    lda #JR_MAX_FALL""",
          new="""    ; PLANT: terminal clamp dropped — vy grows without bound""",
          artifact=ROM,
          build=["jumper"],
          tests=[
              "tests/test_jumper.py::test_jump_full_cycle_matches_the_oracle_every_frame",
              "tests/test_jumper.py::test_jump_is_edge_and_grounded_gated",
          ],
          why="only the free jump's 39 px descent ever reaches the 4 px/f "
              "clamp (a platform drop lands first), so a threshold check on "
              "the short fall passes forever — the frame-for-frame oracle "
              "reds on the arc's last ticks where the unclamped fall pulls "
              "ahead"),
    Plant(id="jump-gate-level-not-edge",
          file=SCENE,
          old="""    lda z:ES_INP_PRESS
    and #JOY_A""",
          new="""    lda z:ES_INP_CUR            ; PLANT: level, not edge
    and #JOY_A""",
          artifact=ROM,
          build=["jumper"],
          tests=[
              "tests/test_jumper.py::test_jump_full_cycle_matches_the_oracle_every_frame",
              "tests/test_jumper.py::test_jump_onto_platform_lands_on_its_top_exactly",
          ],
          why="held A auto-rejumps the instant the box lands — the rest "
              "tail after the landing frame is the surface that sees it, "
              "and the platform ride's touchdown signature (two consecutive "
              "rest reads) never arrives"),
]
