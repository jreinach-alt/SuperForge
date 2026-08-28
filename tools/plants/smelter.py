"""smelter — offset-per-tile's failure modes, planted.

Five plants. Three are silent-corruption defects that still produce a
plausible picture and two are the allocator refusing a declaration that lies.
One of the five found a hole in the test module on its first run, which is the
whole reason this file exists rather than a list of defects somebody was
already confident about.

THE SET IS BUILT AROUND WHAT A PER-COLUMN TABLE CAN GET WRONG WITHOUT
LOOKING WRONG. A picture where every column has moved to *some* height is the
easiest thing in the world to ship: the melt still erupts, the plates still
bob, and nothing about the frame announces that the columns are one place to
the left, or that half of them are driving the wrong layer. Each plant below
is chosen to fail DIFFERENTLY, because a set where everything kills everything
proves only that the ROM boots.

  * `table-column-lead-removed` undoes the one-column shift the generator
    applies. The picture still moves and still looks like a foundry; every
    column is simply displaced by its NEIGHBOUR's word. It is the defect the
    rail actually shipped once, and the reason the lead is asserted as a
    measurement (a shift of 0 explains the picture and +-1 does not) rather
    than as a comment.
  * `bg1-enable-bit-dropped` clears bit 13 in every plate word, so the plates
    fall back to BG1VOFS and stop moving while the melt carries on. The melt
    cases survive it and should: they are about the OTHER enable bit, out of
    the same 32 words, and a set that killed them too would mean the two
    layers were never independently asserted.
  * `flat-row-clears-the-enable-bits` is the control's own failure mode, and
    it is the one that PAID FOR ITSELF. A flat row built by CLEARING the
    enable bits instead of by lowering the values still levels the picture —
    falling back to BG1VOFS/BG2VOFS lands on exactly the two base values the
    flat row carries — so the flat frame is identical either way, while what
    makes it a control is gone: two things now differ between running and flat
    instead of one. On its first run this plant came back **TEST-BLIND**
    against a module that already read the destination VRAM row, because that
    case reads a RUNNING row. `test_the_flat_row_is_a_row_and_not_a_disarm`
    is what the finding bought.
  * `works-declares-mode-1` is the allocator half. The scene's video claim is
    the thing the offset claim is checked against, so moving it to a mode with
    no offset path must stop the BUILD, not the picture.
  * `bg-text-back-in-globals` is the composition the rail's shape exists to
    make impossible: BG3 as a text layer in a scene where BG3 is the table.
    Also a build refusal, and by a different rule.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
GEN = SUPERFORGE / "tools" / "gen_smelter_assets.py"
OPT = SUPERFORGE / "engine" / "features" / "smt_opt" / "feature.toml"
GAME = SUPERFORGE / "game" / "smelter" / "game.toml"
ROM = SUPERFORGE / "build" / "smelter.sfc"
T = "tests/test_smelter.py::"

PLANTS = [
    Plant(id="table-column-lead-removed",
          file=GEN,
          old="""            w = column_word((col + 1) % COLS, phase)""",
          new="""            w = column_word(col, phase)   # PLANT: the lead undone""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_offset_leads_its_column_by_one",
              T + "test_every_melt_column_stands_where_its_word_says",
              T + "test_every_plate_column_stands_where_its_word_says",
          ],
          why="the defect this rail actually shipped. Undoing the shift moves "
              "every column's displacement one column right, which on a "
              "picture of arches and bobbing plates is invisible: the melt "
              "still erupts, the plates still move, and the only thing wrong "
              "is WHICH column each word drives. The plate cases catch it "
              "because a plate's four columns then include one at the layer's "
              "fallback — the ghost that made the first plate render three "
              "columns wide. Planted in the GENERATOR rather than at a write "
              "site because the shift is a property of the table, and the "
              "table is where a future author would undo it."),

    Plant(id="bg1-enable-bit-dropped",
          file=GEN,
          old="""    return BIT_BG1 | (int(round(v)) & 0x3FF)""",
          new="""    return int(round(v)) & 0x3FF      # PLANT: bit 13 never set""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_every_plate_column_stands_where_its_word_says",
              T + "test_the_plates_are_at_different_heights",
          ],
          why="one enable bit of two, cleared. The plates fall back to "
              "BG1VOFS and stand still; the melt is untouched, because its "
              "columns carry bit 14 out of the same 32 words. MEASURED, NOT "
              "REASONED: every melt case survives this, and that is the "
              "point — it is what says the two layers are asserted "
              "independently rather than through one shared observation."),

    Plant(id="flat-row-clears-the-enable-bits",
          file=GEN,
          old="""    return (BIT_BG1 | PLAT_BASE) if p is not None else (BIT_BG2 | MELT_BASE)""",
          new="""    return 0            # PLANT: a flat row that DISARMS instead""",
          artifact=ROM,
          build=["smelter"],
          tests=[
              T + "test_the_flat_row_is_a_row_and_not_a_disarm",
          ],
          why="the CONTROL'S own failure mode, and the one a picture cannot "
              "show. A flat row of zeros still levels every column — falling "
              "back to BG1VOFS/BG2VOFS lands on exactly the two base values "
              "the flat row carries — so what is lost is not the picture but "
              "the ATTRIBUTION: running and flat would then differ in the "
              "values AND in whether the mechanism runs at all, and a "
              "two-variable comparison cannot say which produced the "
              "difference. THE HARNESS FOUND THIS HOLE: on its first run "
              "this plant came back TEST-BLIND against a module that already "
              "read the destination VRAM row, because that case reads a "
              "RUNNING row and the plant only moves the flat one. The "
              "assertion it names now drives the toggle first and checks "
              "every word's ENABLE BIT as well as its value — which is the "
              "assertion a picture-only test set would not have had, and the "
              "one a test set written without a plant did not have either."),

    Plant(id="works-declares-mode-1",
          file=OPT,
          old="""[[claims.video]]
name = "smt_mode"
mode = 2""",
          new="""[[claims.video]]
name = "smt_mode"
mode = 1                 # PLANT: a mode with no offset path""",
          artifact=ROM,
          build=["smelter"],
          expect="build-fails",
          build_names="Offset-per-tile exists in modes [2, 4, 6] ONLY",
          why="the mode constraint, which is one of the two things the "
              "capability map said could not be expressed at all. The picture "
              "under mode 1 would be a perfectly ordinary flat foundry — the "
              "table would sit in VRAM, uploaded every frame, and the PPU "
              "would never read a word of it — so nothing downstream could "
              "tell this from a table that happened to be flat. It has to "
              "stop the BUILD, and the message has to name the mode."),

    Plant(id="bg-text-back-in-globals",
          file=GAME,
          old="""globals = ["scene_mgr", "fade", "input", "text_dp", "font_rom",
           "smt_bg", "smt_rom", "region", "tick_scale"]""",
          new="""globals = ["scene_mgr", "fade", "input", "text_dp", "font_rom",
           "bg_text",                    # PLANT: BG3 drawn where it is data
           "smt_bg", "smt_rom", "region", "tick_scale"]""",
          artifact=ROM,
          build=["smelter"],
          expect="build-fails",
          build_names="BG3 IS THIS SCENE'S OFFSET TABLE, not a drawable layer",
          why="the OTHER thing the capability map said could not be "
              "expressed: a text feature and an offset-per-tile feature both "
              "believing they own BG3. Before the vocabulary this composed "
              "green. It is planted at the one line that makes it happen — "
              "moving `bg_text` from the title scene into the globals — "
              "because that is the edit a future author makes without "
              "thinking, and the refusal is what has to catch it."),
]
