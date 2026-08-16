"""brawler's four load-bearing mechanisms, each planted and required RED.

The rail is the second OBJ name table,
and the plants are chosen so that the two halves of THAT mechanism are
falsified separately — because they fail in different places and a test that
caught only one of them would ship the other broken:

  1. THE OAM SIDE — the attribute's 9th tile bit. Clearing it leaves an
     OBSEL that is still perfectly programmed and an OAM tile byte that is
     still perfectly correct; the PPU simply reads it out of Arthur's table.
     Mordred keeps his own palette, keeps his position, keeps chasing, and
     keeps dying to three swings — every OAM/HUD/geometry case in the module
     stays green. Only a PIXEL comparison against his own CHR can see it,
     which is what makes this the plant that proves the module's headline
     assertion is not decoration.

  2. THE OBSEL SIDE — the derived gap, actually reaching the register.
     Dropping the `(BR_OBJ_GAP << 3)` term from the OBSEL value leaves the
     hardware pointing the second table at `base + 0x1000`, which the
     allocator packed with the font CHR page and BG1's tilemap — so Mordred
     renders glyph soup while the attribute bit, the tile byte, both CHR
     uploads and both palettes stay exactly right.

     NOTE, and it is the reason this plant is shaped this way: the OBVIOUS
     version of it — `BR_OBJ_GAP = 0`, the gap written down instead of
     derived — BREAKS THE BUILD, because brawler_obj.asm's
     `.assert BR_OBJ_SPAN = ((BR_OBJ_GAP + 1) << 12)` catches exactly that.
     That is a correct refusal and a useless plant: the defect never reaches
     a ROM, so it says nothing about the tests (docs/46's whole point). The
     plant therefore attacks the one step the assertions do NOT cover — the
     assembly of the register VALUE from parts each of which is individually
     checked.

  3. THE ONE-HIT LATCH — the half of "active frames" that a window alone is
     not. Without it a held swing lands a hit on every live frame of its
     window, so a single press takes the foe from 3 to 0 and banks a win.
     A test that only ever tapped A would never see it.

  4. THE ANIM CLOCK RESET — the rail's own stated lesson ("a 4-step table
     gets indexed at step 7 by a stale 8-step counter"). Dropping the reset
     on the idle<->run change leaves both tables cycling and both actors
     animating; only the FIRST tile after a state change is wrong, and only
     against the table's own step 0.

Not planted, deliberately: PARK_Y. The obvious defect there (parking a
32-tall sprite at oam_park_all's 240, so its rows 16..31 wrap onto scanlines
0..15 — the classic silent-quantisation trap) is refused at ASSEMBLE time by
brawler_obj.asm's `BR_PARK_Y + 32 <= 256`, so there is no ROM to test. The
build stopping IS the falsification, and it is checked by the assertion
rather than by this harness.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
INC = SUPERFORGE / "game" / "brawler" / "brawler.inc"
OBJ = SUPERFORGE / "engine" / "features" / "brawler_obj" / "brawler_obj.asm"
SCENE = SUPERFORGE / "game" / "brawler" / "scenes" / "fight.asm"
ROM = SUPERFORGE / "build" / "brawler.sfc"
T = "tests/test_brawler.py::"

PLANTS = [
    Plant(
        id="br-name-bit-cleared",
        file=INC,
        old="BR_ATTR_MORDRED = BR_PRI | (1 << 1) | (1 << 0); palette 1, name table 1",
        new="BR_ATTR_MORDRED = BR_PRI | (1 << 1)             ; PLANT: no name bit",
        artifact=ROM,
        build=["brawler"],
        tests=[
            T + "test_both_knights_draw_from_their_own_name_table_in_one_frame",
        ],
        why="Mordred's tile byte is read out of ARTHUR's name table. The "
            "OBSEL programming is untouched, both CHR uploads still land in "
            "their claimed VRAM words, both palettes are still where their "
            "claims say, his OAM entry still carries his position, his "
            "palette and his priority — so the destination-region tests, the "
            "gap arithmetic, the chase, the swings, the HUD and the freeze "
            "are all GREEN. Exactly one case sees it, and it sees it in "
            "PIXELS: the prediction from br_mor_chr no longer matches the "
            "screen, and the counterfactual prediction from br_art_chr now "
            "does. That inversion is the whole point of the case.",
    ),
    Plant(
        id="br-obsel-gap-dropped",
        file=OBJ,
        old="BR_OBSEL = (BR_OBJ_SIZE_PAIR << 5) | (BR_OBJ_GAP << 3) | ES_V_BR_ART_CHR_OBSEL_BASE",
        new="BR_OBSEL = (BR_OBJ_SIZE_PAIR << 5) | ES_V_BR_ART_CHR_OBSEL_BASE  ; PLANT: gap dropped",
        artifact=ROM,
        build=["brawler"],
        tests=[
            T + "test_both_knights_draw_from_their_own_name_table_in_one_frame",
        ],
        why="the derived gap is computed correctly and then never reaches "
            "the register, so the PPU fetches tiles 256..511 from "
            "base + 0x1000 words — which the allocator packed with the text "
            "CHR page and BG1's tilemap — and Mordred renders font glyphs and "
            "tilemap words as sprite pixels. Nothing else moves: Arthur is "
            "unaffected (he is the FIRST table), the name bit is still set, "
            "both uploads still land in their claimed VRAM words, both "
            "palettes are still where their claims say, and every "
            "assemble-time assertion still passes because each checks a PART "
            "and this drops the assembly. Only the pixel prediction catches "
            "it.",
    ),
    Plant(
        id="br-hit-latch-removed",
        file=SCENE,
        old="""    lda #1
    sta z:US_AHIT
    lda #BR_STUN_T""",
        new="""    lda #BR_STUN_T                  ; PLANT: the one-hit latch is gone""",
        artifact=ROM,
        build=["brawler"],
        tests=[
            T + "test_a_swing_lands_at_most_one_hit_however_long_it_overlaps",
            T + "test_three_hits_bank_a_win_and_respawn_him_at_full_health",
        ],
        why="the hitbox stays live for its whole 4..12 window and now lands a "
            "hit on EVERY frame of it, so one held press takes the foe from 3 "
            "to 0 and banks a win. The window itself still works, the "
            "placement still follows facing, and a single-frame TAP still "
            "looks correct — which is why the module holds A across a whole "
            "swing rather than tapping it, and why the round test walks the "
            "counter down one step at a time instead of only checking the "
            "end state.",
    ),
    Plant(
        id="br-anim-clock-not-reset",
        file=SCENE,
        old="""@set_state:
    .a16
    .i16
    sta z:US_ASTATE
    stz z:US_ATICK
    stz z:US_AFRAME""",
        new="""@set_state:
    .a16
    .i16
    sta z:US_ASTATE                 ; PLANT: the clocks survive the change""",
        artifact=ROM,
        build=["brawler"],
        tests=[
            T + "test_idle_and_run_cycle_their_own_tables_and_reset_on_the_change",
        ],
        why="the rail's stated animation lesson, unlearned: a state change "
            "now carries the old table's step index into the new table. Both "
            "tables still cycle, both still wrap inside their own length "
            "(br_anim_meta bounds that), and every other animation "
            "observable — the run table's step LENGTHS, the idle table's, the "
            "set of tiles each cycles through — is unchanged. Only the FIRST "
            "tile after each transition is wrong, which is why the case "
            "asserts step 0 at both edges rather than just sampling the "
            "cycle.",
    ),
]
