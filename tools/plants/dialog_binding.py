"""`dialog`'s binding contract and its REACH assert, as falsifiable gates.

Two different kinds of claim, so two kinds of plant:

  THE SEVEN BINDING SYMBOLS — col_map's argument, one feature over: the
  schema has no vocabulary for "same feature, different scene geometry", so
  the geometry arrives as includer-supplied symbols with NO DEFAULTS and each
  missing one is a hard `.error`. "The undefined-symbol error is the design
  review" is worth nothing unless the errors arrive, and arrive NAMING the
  symbol. These plants are that evidence.

  THE REACH ASSERT — the interesting one, and the reason this file exists at
  all. docs/09 §5.1 registers "my claim must be reachable from the same BG
  base as that claim" as a MISSING mechanism, and records its own worked
  failure: a claim landing exactly ONE TILE past a layer's reach, with
  nothing noticing. `dialog` has no `reach =` field to declare, so it asserts
  the property from the emitted symbols instead. An assert nobody has tried
  to break is a comment. Here the includer's DLG_BG3_CHR binding is moved so
  the panel's page falls out of reach, and the build must REFUSE naming the
  claim rather than render whatever tiles happen to live there.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "rpg" / "scenes" / "town.asm"
ROM = SUPERFORGE / "build" / "rpg.sfc"

# (the exact binding line in town.asm, the words the .error must carry)
BINDINGS = [
    ("DLG_COL = 2", "must bind the panel's left cell column"),
    ("DLG_ROW = 18", "must bind the panel's top cell row"),
    ("DLG_W = 28", "must bind the panel width in cells"),
    ("DLG_H = 9", "must bind the panel height in cells"),
    ("DLG_BG3_CHR = ES_V_TEXT_CHR", "must bind the BG3 CHR base"),
    ("DLG_MAP = ES_V_TEXT_MAP", "must bind the BG3 tilemap word base"),
    ("DLG_TEXT_ATTR = ((ES_C_TEXT_PAL / 4) << 10) | (1 << 13)",
     "must bind the attr word printed glyphs carry"),
]

PLANTS = [
    Plant(id=f"dlg-binding-{line.split(' ')[0]}",
          file=SCENE,
          old=line,
          new="; PLANT: binding omitted  " + line,
          artifact=ROM,
          build=["rpg"],
          tests=[],
          expect="build-fails",
          build_names=needle,
          why="a scene that forgets this symbol is the exact mistake the "
              "no-defaults design bets on catching at assembly time")
    for line, needle in BINDINGS
]

# --- the reach assert, docs/09 §5.1's gap, tested by breaking it ------------
# Moving the bound BG3 base DOWN by one chr page puts the panel's own page two
# pages above it: 0x2000 words = tile 1024, exactly ONE past the 10-bit index's
# reach — §5.1's own worked failure, reproduced deliberately.
PLANTS.append(Plant(
    id="dlg-reach-one-tile-past",
    file=SCENE,
    old="DLG_BG3_CHR = ES_V_TEXT_CHR",
    # DERIVED, not a literal: `no_literals` refuses a raw address operand even
    # inside a plant, and the first version of this plant failed for exactly
    # that — the build broke on the gate instead of on the assert, which the
    # harness correctly reported as a PLANT failure rather than a fired one.
    # ES_V_TEXT_MAP_WORDS is 0x400, so x4 is one chr page.
    new="DLG_BG3_CHR = ES_V_TEXT_CHR - (ES_V_TEXT_MAP_WORDS * 4)  ; PLANT",
    artifact=ROM,
    build=["rpg"],
    tests=[],
    expect="build-fails",
    build_names="past BG3's 1024-tile reach",
    why="docs/09 §5.1's complaint is that packing order decides the reach and "
        "NOTHING CHECKS THE RESULT. dialog.asm's assert is the check; this "
        "proves it fires on the exact shape §5.1 records — a page landing one "
        "tile past reach — instead of rendering the wrong tiles"))

PLANTS.append(Plant(
    id="dlg-reach-misaligned",
    file=SCENE,
    old="DLG_BG3_CHR = ES_V_TEXT_CHR",
    new="DLG_BG3_CHR = ES_V_TEXT_CHR + 4   ; PLANT: half a 2bpp tile off",
    artifact=ROM,
    build=["rpg"],
    tests=[],
    expect="build-fails",
    build_names="not 8-word aligned",
    why="the third arm of the same guard: a 2bpp tile is 8 words, so a base "
        "that is not a multiple of 8 away from the panel page has NO tile "
        "index that addresses it. Reachable in a real composition — a `raw` "
        "claim between the two pages would do it — unlike the below-the-base "
        "arm, whose plant ca65 refuses on a negative tile index before the "
        "assert can speak (the assert is still there and still correct; it is "
        "simply not falsifiable through the includer's binding)"))
