"""mill_direct — what "the pixel IS the colour" can get wrong while still
producing a picture of a forge.

Four plants, and they are chosen against the ONE structural weakness of the
case set they aim at. `tests/test_mill_direct.py` takes its expected colour
from the CHR byte and the tilemap word THE PPU READ, which is what makes it a
test of the MECHANISM rather than of the converter — and it is also why a
quantiser defect is invisible to it: whatever bytes the quantiser wrote, the
PPU renders exactly what the expression predicts from them. So the set has to
attack from two directions, and it does:

  * `cgwsel-bit-0-not-composed` breaks the DECLARATION's path to the register.
    The claim is declared, the map records it, and the composed byte drops the
    bit — so the PPU reads BG1's pixels as CGRAM indices again and the picture
    becomes whatever the 96-entry palette happens to hold at those indices. It
    is still a picture; it is not this one.
  * `the-palette-field-is-never-fitted` is the half a 3-3-2-only test cannot
    see, and the reason two of the cases exist. Every tile takes field 0, so
    the low bit of each channel is lost and the map words carry nothing. THE
    HEADLINE CASE STAYS GREEN under this plant, by construction — its oracle is
    VRAM, and VRAM now says field 0 everywhere, which is exactly what the
    picture shows. Only the two cases that ask whether the field is DOING
    anything can fail, which is the whole argument for their existence.
  * `the-quantiser-truncates` and `the-fit-takes-the-worst-field` are the
    converter's own failure modes, and the only thing that can see them is the
    other ROM's picture. They are two DIFFERENT shapes of the same class: one
    is a systematic per-channel bias (every colour one step dark), the other is
    a per-tile choice inverted (the field that fits worst instead of best), and
    a set where both killed the same single case would prove less than it
    looks.

WHAT IS DELIBERATELY NOT HERE: a plant that removes O11's warning. O11 warns
rather than refusing (docs/100 §5), so removing it moves no artifact md5 and
the harness would report a plant that never reached the binary — correctly.
That check is a pure-Python case in `tests/test_video_offset.py`
(`test_o11_direct_color_under_a_mode_with_no_8bpp_layer_warns`), where the rest
of the refusal set is tested and where a warning IS the observable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
ALLOC = SUPERFORGE / "allocator" / "allocate.py"
GEN = SUPERFORGE / "tools" / "gen_mill_direct.py"
ROM = SUPERFORGE / "build" / "mill_direct.sfc"
T = "tests/test_mill_direct.py::"

PLANTS = [
    Plant(id="cgwsel-bit-0-not-composed",
          file=ALLOC,
          old="""                  | (0x02 if g.source == "sub" else 0)
                  | (0x01 if direct else 0))""",
          new="""                  | (0x02 if g.source == "sub" else 0))
                                          # PLANT: the declaration is dropped""",
          artifact=ROM,
          build=["mill-direct"],
          tests=[
              T + "test_bg1_renders_the_direct_colour_expression",
              T + "test_the_two_builds_allocate_one_map",
          ],
          why="the DECLARATION'S PATH TO THE REGISTER, cut where the two "
              "vocabularies meet. `direct_color` is declared on the video "
              "claim and composed into CGWSEL by the screen/blend half "
              "(docs/99 §4), which is the only surprising thing about it — so "
              "the plant is the join failing quietly. The build still "
              "succeeds, the variant's map still records `direct_color: "
              "true`, the scene still writes the CGWSEL it was handed, and "
              "the PPU reads BG1's bytes as CGRAM indices again. The picture "
              "is still a hall, drawn from the 96-entry palette at whatever "
              "indices the direct-colour bytes happen to land on."),

    Plant(id="the-palette-field-is-never-fitted",
          file=GEN,
          old="""PALETTE_BITS = True""",
          new="""PALETTE_BITS = False              # PLANT: field 0 everywhere""",
          artifact=ROM,
          build=["mill-direct"],
          tests=[
              T + "test_the_tilemap_palette_field_is_load_bearing",
              T + "test_the_two_builds_draw_the_same_tiles",
          ],
          why="THE HALF A 3-3-2-ONLY TEST CANNOT SEE, and the reason two "
              "cases exist for it. Every tile is fitted under field 0 and "
              "every map word carries 0, so the three bits the indexed build "
              "ignores (SnesPpu.cpp:1077) stay ignored here too and each "
              "channel loses its low bit. The hall still reads as the hall. "
              "`test_bg1_renders_the_direct_colour_expression` STAYS GREEN "
              "under this plant and must: its oracle is VRAM, VRAM says field "
              "0, and field 0 is what the picture shows. What goes red is the "
              "pair of cases that ask whether the field is doing any work — "
              "which is what tells a mechanism that is present from one that "
              "is merely consistent."),

    Plant(id="the-quantiser-truncates",
          file=GEN,
          old="""    r = min(7, max(0, round((t[0] - ((pal & 1) << 1)) / 4)))
    g = min(7, max(0, round((t[1] - (pal & 2)) / 4)))
    b = min(3, max(0, round((t[2] - (pal & 4)) / 8)))""",
          new="""    r = min(7, max(0, int((t[0] - ((pal & 1) << 1)) / 4)))
    g = min(7, max(0, int((t[1] - (pal & 2)) / 4)))
    b = min(3, max(0, int((t[2] - (pal & 4)) / 8)))   # PLANT: truncate""",
          artifact=ROM,
          build=["mill-direct"],
          tests=[T + "test_the_direct_build_is_the_same_picture"],
          why="the converter's own failure mode, and the one nothing else in "
              "the module can see. Every colour is chosen by TRUNCATION "
              "instead of by nearest step, so the whole hall comes out up to "
              "one grid step dark in every channel — a systematic bias, not a "
              "wrong picture. Every case that computes its expectation from "
              "the CHR byte stays green BY CONSTRUCTION, because the PPU "
              "renders exactly what the quantiser wrote; the only oracle that "
              "can refuse it is the other ROM's picture, which is why "
              "`test_the_direct_build_is_the_same_picture` exists at all. "
              "Measured over the CHR page: mean weighted error 8.8 -> 18.4."),

    Plant(id="the-fit-takes-the-worst-field",
          file=GEN,
          old="""        if best_cost is None or cost < best_cost:""",
          new="""        if best_cost is None or cost > best_cost:     # PLANT: worst fit""",
          artifact=ROM,
          build=["mill-direct"],
          tests=[T + "test_the_direct_build_is_the_same_picture"],
          why="the same class as the plant above and a DIFFERENT SHAPE of it, "
              "which is the point of having both: this one is per TILE and "
              "signed either way, not a uniform bias. Each tile is given the "
              "palette field that fits it WORST, so the three low bits are "
              "spent making the colour further from the art rather than "
              "nearer — and the map words still carry a field, so the "
              "load-bearing case above still passes. A quantiser can be wrong "
              "in a direction no per-pixel invariant notices. Measured over "
              "the CHR page: mean weighted error 8.8 -> 24.8."),
]
