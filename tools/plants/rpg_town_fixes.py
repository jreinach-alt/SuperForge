"""The rpg town's four playability fixes, as falsifiable behaviour plants.

Each of the four changed what the RUNNING GAME does, so each plant is a
`test-red` plant: it reverts one fix to a plausible regression, requires the
built ROM's md5 to MOVE, and requires that fix's own test to go RED. A green
test against a reverted fix would be a hole in the test, which is the whole
point of the harness (docs/46). Paired with the healthy-tree green run the
suite already provides, both arms are covered.

The reverts are realistic defects, not arbitrary breakage:
  - THE EXIT: an off-by-one on the exit row — the shape that would silently
    disable walking onto the exit tile.
  - HOLD-TO-WALK: reading the PRESS edge instead of the held level, so holding
    a direction does nothing past the first tile.
  - THE FLARE: zeroing the flare count — makes "THE TORCH FLARES ONCE" a lie.
  - THE BARRELS: the two plaza props back to torches, the exact state the fix
    undoes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
TOWN = SUPERFORGE / "game" / "rpg" / "scenes" / "town.asm"
GEN = SUPERFORGE / "tools" / "gen_rpg_assets.py"
ROM = SUPERFORGE / "build" / "rpg.sfc"
T = "tests/test_rpg.py"

PLANTS = [
    # THE EXIT — walking onto it
    Plant(
        id="rpg-fix1-walk-onto-exit-neutered",
        file=TOWN,
        old="    cpy #::TOWN_EXIT_TY",
        new="    cpy #::TOWN_EXIT_TY + 1   ; PLANT: off-by-one on the gate row",
        artifact=ROM, build=["rpg"],
        tests=[f"{T}::test_walking_onto_the_south_gate_wipes_out_without_an_a_press"],
        why="an off-by-one on the exit row silently disables the walk-onto "
            "exit — the avatar steps onto the gate and nothing wipes; the test "
            "must catch that stepping onto the gate no longer reaches the "
            "overworld"),

    # HOLD-TO-WALK (the original bug, reverted)
    Plant(
        id="rpg-fix4-hold-to-walk-reverted-to-edge",
        file=TOWN,
        old="    lda z:ES_INP_CUR\n    and #(::JOY_LEFT | ::JOY_RIGHT | ::JOY_UP | ::JOY_DOWN)",
        new="    lda z:ES_INP_PRESS  ; PLANT: edge, not level — the pilot bug\n"
            "    and #(::JOY_LEFT | ::JOY_RIGHT | ::JOY_UP | ::JOY_DOWN)",
        artifact=ROM, build=["rpg"],
        tests=[f"{T}::test_holding_a_direction_walks_tile_by_tile_and_a_tap_moves_one"],
        why="reading the PRESS edge instead of the held level IS the original "
            "pilot bug: a held direction fires one edge and then nothing, so the "
            "walk stalls past tile 1; the held-walk test must go red when the "
            "throttle gate is reverted to edge detection"),

    # THE FLARE — the save torch
    Plant(
        id="rpg-fix3-flare-disabled",
        file=TOWN,
        old="    lda #TOWN_FLARE_FRAMES",
        new="    lda #0   ; PLANT: flare never arms",
        artifact=ROM, build=["rpg"],
        tests=[f"{T}::test_saving_flares_the_save_torch_then_restores_it"],
        why="zeroing the flare count is a plausible regression that makes the "
            "panel's 'THE TORCH FLARES ONCE' a lie again; the flare test must "
            "catch that the save-torch cell never swaps to the lit tile"),

    # THE BARRELS
    Plant(
        id="rpg-fix2-barrel-reverted-to-torch",
        file=GEN,
        old="        m[9][x] = TT_BARREL",
        new="        m[9][x] = TT_TORCH   # PLANT: back to a decorative torch",
        artifact=ROM, build=["rpg"],
        tests=[f"{T}::test_the_plaza_decor_is_barrels_not_torches"],
        why="reverting the two plaza props to torches is the exact regression "
            "the fix undoes; the test must catch that (8,9)/(24,9) are barrels, "
            "not torches, on the town tilemap"),
]
