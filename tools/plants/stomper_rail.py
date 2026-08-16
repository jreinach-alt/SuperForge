"""stomper — three stomp-resolution defects the rail's tests must see.

None stops the build: all three are the silent class — the ROM assembles,
boots, paces its enemies, and the picture is plausible. Each is a defect a
REASONABLE change to the resolution would produce (`why` holds that bar).

THE TWO-LANDING-PATHS OBLIGATION, from the rail's own
measured fact): the integrator lands via a <=1 px/f STAND probe (arc-top
approaches) or the fast-fall SNAP, and the stomp classifier reads the
approach velocity — so the module keeps one stomp scenario in each speed
class (E1 at the $400 MAX_FALL clamp; E2 at $C0, two ticks past apex). How
the three plants discharge the obligation:

  bounce-dropped / kill-dropped fire in BOTH classes' tests: the E1
    fast-fall case directly, and the win case at its own E1 phase — the win
    script's arc-top contact sits DOWNSTREAM of the E1 kill (the journey to
    the platform crosses E1's beat, which is only safe dead), so its red
    arrives before the arc-top contact is reached. That ordering is a fact
    of the level, not a coverage hole, because:
  slow-falls-hurt exists to be the arc-top class's OWN witness: a velocity
    floor on the stomp ("must be falling >= 1 px/f to count") kills ONLY
    the arc-top contact — the E1 test stays green BY DESIGN (its contact
    passes the floor at $400), and the win test goes red at the E2 contact
    itself, reclassified hurt. A defect only one speed class can see,
    proven seen.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "stomper" / "scenes" / "play.asm"
ROM = SUPERFORGE / "build" / "stomper.sfc"
T = "tests/test_stomper.py"

PLANTS = [
    # ---- the stomp kills but the player does not bounce -------------------
    Plant(
        id="stomp-bounce-dropped",
        file=SCENE,
        old="    stz z:ealive                ; STOMP: kill + bounce\n"
            "    lda #ST_BOUNCE_NEG\n"
            "    sta z:US_VY\n",
        new="    stz z:ealive                ; STOMP: kill + bounce\n"
            "    lda #ST_BOUNCE_NEG\n"
            "    ; PLANT: bounce write dropped\n",
        artifact=ROM,
        build=["stomper"],
        tests=[f"{T}::test_stomp_kills_culls_bounces_and_counts",
               f"{T}::test_arc_top_stomp_wins_and_clear_prints"],
        why="the macro loads the bounce velocity and a tidy-up drops the "
            "store (the load stays, so it reads as intent). The kill still "
            "lands, FOES still counts down, the sprite still culls — the "
            "player just falls through the corpse to the floor. Both stomp "
            "tests' per-frame oracles diverge on the first post-contact "
            "frame (the oracle rises, the ROM keeps falling): the fast-fall "
            "case at its own contact, the win case at its E1 phase",
    ),
    # ---- the stomp bounces but the enemy survives -------------------------
    Plant(
        id="stomp-kill-dropped",
        file=SCENE,
        old="    stz z:ealive                ; STOMP: kill + bounce\n",
        new="    ; PLANT: kill write dropped\n",
        artifact=ROM,
        build=["stomper"],
        tests=[f"{T}::test_stomp_kills_culls_bounces_and_counts",
               f"{T}::test_arc_top_stomp_wins_and_clear_prints",
               f"{T}::test_dead_enemy_is_transparent_and_walls_still_stand"],
        why="the other half of the same tidy-up: the player bounces and the "
            "counter... does not move, because FOES is decremented by the "
            "caller on the return code, which still says 1 — but the enemy "
            "keeps pacing and keeps drawing. Every consumer of the kill is "
            "wrong at once: the cull (magenta persists), the park (slot "
            "stays live), the transparency walk (the 'dead' beat still "
            "hurts), the win (FOES never reaches 0, CLEAR never prints). "
            "The per-frame oracles catch it on the contact frame's commit",
    ),
    # ---- a velocity floor: slow falls no longer stomp ---------------------
    Plant(
        id="slow-falls-hurt",
        file=SCENE,
        old="    bmi hurt                    ; rising -> hit from below\n",
        new="    bmi hurt                    ; rising -> hit from below\n"
            "    cmp #(1 << 8)\n"
            "    bcc hurt                    ; PLANT: slow falls no longer stomp\n",
        artifact=ROM,
        build=["stomper"],
        tests=[f"{T}::test_arc_top_stomp_wins_and_clear_prints"],
        why="THE ARC-TOP CLASS'S OWN WITNESS. A port feel-tuning mushy "
            "stomps adds a floor — 'must actually be falling, say a pixel a "
            "frame' — and every fast-fall stomp still works, every demo "
            "still looks right. What dies is exactly the apex landing: the "
            "win script's E2 contact arrives at $C0 = 0.75 px/f, gets "
            "reclassified HURT, and the player is knocked back with the "
            "second foe alive — the win never comes. The fast-fall test "
            "stays GREEN by design ($400 passes any plausible floor), which "
            "is the point: only a test pinned to the slow class can see "
            "this defect, and the module keeps one",
    ),
]
