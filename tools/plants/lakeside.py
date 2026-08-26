"""lakeside — the sub-screen half-add's failure modes, planted.

Seven plants. Six are silent-corruption defects that still produce a plausible
picture, and one is the allocator refusing a declaration that lies — which is
the other half of what this rail exists to demonstrate.

THE PAIR THE SET IS BUILT AROUND. `cgadsub-halve-cleared` and
`lake-drops-the-ts-write` are chosen to fail DIFFERENTLY, because a plant set
where everything kills everything proves only that the ROM boots:

  * clearing CGADSUB's halve bit leaves a blend that still composites — the
    water simply washes out. Every composited value moves, so membership, the
    oracle, the spot checks and the full-add absence all die.
  * dropping the scene's TS write removes the sub screen entirely, so the
    blend vanishes and the whole picture is the main screen at full intensity.
    The oracle and the spots die again, and this time so does the count of
    pixels that are explicable as UNBLENDED world — which the first plant
    leaves untouched, because a full add is not a bed colour either.

MEASURED, NOT REASONED: `test_above_the_waterline_the_world_is_at_full_intensity`
survives BOTH, and it should. It is the case that says what the hardware does
where there is nothing to blend with — above the surface's coverage — and
neither plant changes that. A plant set that killed it too would mean the
fallback case was really just another blend assertion wearing a different name.

WHAT MOVED WHEN THE ART DID. These plants were written against flat colour
bands, where "the band equals one value" was the assertion each of them broke.
Tile art put thirty-five composited values on screen at once and that handle
went away; the cases they kill now are the three that replaced it — region-wide
membership, the unblended count against the surface's own transparency, and the
pixel-for-pixel oracle — plus the named spot checks. Every list below was
re-measured against the new module rather than carried across: the counts in
the run output are 7, 8, a build refusal, 2, 3, 1 and 3.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
WATER = SUPERFORGE / "engine" / "features" / "water" / "feature.toml"
LAKE = SUPERFORGE / "game" / "lakeside" / "scenes" / "lake.asm"
TITLE = SUPERFORGE / "game" / "lakeside" / "scenes" / "title.asm"
ROM = SUPERFORGE / "build" / "lakeside.sfc"
T = "tests/test_lakeside.py::"

PLANTS = [
    Plant(id="cgadsub-halve-cleared",
          file=WATER,
          old='''op = "add"
half = true
source = "sub"''',
          new='''op = "add"
half = false                    # PLANT: a full add, not a half add
source = "sub"''',
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_every_pixel_of_the_water_is_a_legal_composited_value",
              T + "test_the_composited_picture_matches_the_two_layers_pixel_for_pixel",
              T + "test_named_coordinates_composite_exactly_what_their_two_layers_hold",
              T + "test_the_half_add_is_not_a_full_add",
              T + "test_the_gaps_inside_the_surface_show_the_bed_at_full_intensity",
              T + "test_text_over_the_water_is_not_blended",
              T + "test_every_bit_the_composition_declares_has_its_consequence_on_screen",
          ],
          why="the defect this rail is most likely to ship: the water still "
              "composites, it is simply twice as bright, and nothing about "
              "the picture announces which of the two it is. This is why the "
              "blend cases assert EQUALITIES rather than a tolerance — a "
              "tolerance wide enough to be comfortable would admit the full "
              "add, and with thirty-five composited values on screen the "
              "temptation to widen one is exactly what has to be refused. "
              "The generator's P4 is what makes the absence assertion real: "
              "no full add lands on a legal value, so a full-add pixel is "
              "outside the legal set rather than merely near its edge. "
              "Planted in the DECLARATION rather than at a write site "
              "because that is where the value comes from: the allocator "
              "recomposes CGADSUB and the emitted byte moves"),

    Plant(id="lake-drops-the-ts-write",
          file=LAKE,
          old='''    lda #ES_SCR_LAKE_TS
    sta a:$212D
''',
          new='''    ; PLANT: the composed TS never reaches the hardware
''',
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_no_pixel_under_the_surface_is_explicable_as_unblended_world",
              T + "test_the_composited_picture_matches_the_two_layers_pixel_for_pixel",
              T + "test_named_coordinates_composite_exactly_what_their_two_layers_hold",
              T + "test_the_gaps_inside_the_surface_show_the_bed_at_full_intensity",
              T + "test_the_surfaces_top_edge_is_a_pixel_boundary_not_a_row_boundary",
              T + "test_the_surface_starts_on_the_row_the_vofs_correction_promises",
              T + "test_text_over_the_water_is_not_blended",
              T + "test_each_scene_enter_writes_every_port_its_composition_owns",
          ],
          why="the composition is right and the write is missing — a scene "
              "that computed the correct byte and never sent it still "
              "renders, on whatever the previous scene left in the port, so "
              "presence has to be asserted separately from effect. With no "
              "sub-designated layer the hardware substitutes the fixed "
              "colour and disables halving at EVERY pixel, so the blend "
              "vanishes rather than degrading. The case that catches it most "
              "directly is the unblended COUNT: every pixel of the water then "
              "wears a bed colour, while the surface's own transparency — read "
              "out of VRAM, where the upload still landed — says only a "
              "fraction of them should. The fallback case above the waterline "
              "stays green, because that state is exactly what it was already "
              "asserting"),

    Plant(id="water-screen-claim-removed",
          file=WATER,
          old='''[[claims.screen]]
layer = "bg2"
on = "sub"
''',
          new='''# PLANT: the designation removed, leaving a blend that names no source
''',
          artifact=ROM,
          build=["lakeside"],
          expect="build-fails",
          build_names="BLEND source contention",
          why="the other half of what this rail demonstrates: a blend "
              "declaring a sub source in a scene with no sub-designated "
              "layer is a declaration that LIES — the hardware would "
              "substitute the fixed colour and the blend would never see its "
              "declared source — so the allocator refuses it (docs/99 R4) "
              "rather than shipping a picture that looks almost right. This "
              "plant is `expect=build-fails` for that reason: the finding is "
              "a refusal, not a red test, and a plant set that only ever "
              "checks tests cannot tell the difference"),

    Plant(id="text-gated-into-the-math",
          file=WATER,
          old='math = ["bg1", "backdrop"]',
          new='math = ["bg1", "bg3", "backdrop"]   # PLANT: blend the text too',
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_text_over_the_water_is_not_blended",
              T + "test_every_bit_the_composition_declares_has_its_consequence_on_screen",
          ],
          why="the per-layer enable is the whole reason CGADSUB has six of "
              "them, and this is the shape of getting one wrong: the picture "
              "is still a plausible lake, the text is simply dimmer over the "
              "water than over the sky. It composes legally — bg3 IS "
              "main-designated, so R5 has nothing to say about it — which is "
              "exactly why a test rather than a gate has to catch it"),

    Plant(id="drift-step-never-applied",
          file=LAKE,
          old='''    lda z:US_TSW
    jsr wat_advance
''',
          new='''    ; PLANT: this frame's step is published and never applied
''',
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_the_surface_drifts_one_pixel_per_emulated_frame",
              T + "test_the_drift_resumes_after_a_second_press",
              T + "test_the_highlight_walks_its_phases_with_the_surface",
          ],
          why="the timebase still runs and still publishes the right step "
              "every frame, so any test that read the accumulator or the "
              "published step would pass — the surface simply never moves. "
              "The two cases that die recover the displacement from the "
              "PIXELS, and the stilled case stays green because a motionless "
              "surface is precisely what it asserts, which is what makes the "
              "two a matched pair rather than one test run twice. The third "
              "is the highlight: its phase is a function of the accumulated "
              "position, so a drift that never accumulates freezes the "
              "twinkle as well — one defect, two visible consequences, and "
              "the case that walks the phases sees the second"),

    Plant(id="title-drops-the-blend-off-write",
          file=TITLE,
          old='''    lda #ES_SCR_TITLE_CGWSEL
    sta a:$2130
    lda #ES_SCR_TITLE_CGADSUB
    sta a:$2131
''',
          new='''    ; PLANT: the composed off state never reaches the hardware
''',
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_each_scene_enter_writes_every_port_its_composition_owns",
          ],
          why="transition hygiene at the PORT. Nothing carries the composed "
              "state across an edge and the boot PPU reset runs only at "
              "power-on, so with this write gone the blender the lake armed "
              "is still programmed while the title is on screen. THE "
              "PICTURE CASE IS DELIBERATELY NOT LISTED, and the reason is "
              "measured rather than assumed: it was listed first, it stayed "
              "GREEN, and the run is what said so. The title also writes "
              "TS = $00, so the sub screen is empty, so the inherited "
              "source = sub blend adds the fixed colour — black, from the "
              "boot reset — with halving disabled, which leaves every main "
              "pixel exactly as it was. The inheritance is real and "
              "invisible. `title-drops-both-halves` is the plant that makes "
              "it visible, and this one is scoped to the assertion that can "
              "actually see it"),

    Plant(id="title-drops-both-halves",
          file=TITLE,
          old='''    lda #ES_SCR_TITLE_TS
    sta a:$212D
    lda #ES_SCR_TITLE_CGWSEL
    sta a:$2130
    lda #ES_SCR_TITLE_CGADSUB
    sta a:$2131
''',
          new='''    ; PLANT: neither half of the composed state reaches the hardware
''',
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_the_title_scene_does_not_inherit_the_lake_blend",
              T + "test_the_title_shows_the_whole_bed_unblended",
              T + "test_each_scene_enter_writes_every_port_its_composition_owns",
          ],
          why="the inheritance made visible, and the pair that makes it so. "
              "With the designation AND the blender both left where the lake "
              "put them, the title screen returned to from the lake renders "
              "its sky, hills, sand and bed through the water\'s ripple — "
              "captured under this plant before it was written. That is what "
              "the per-edge hygiene warning in the allocation report is "
              "about, and it is why every scene in this rail composes the "
              "vocabulary rather than only the one that blends. The two "
              "halves are independently load-bearing at an edge: neither "
              "write alone is sufficient to expose the hazard, which is a "
              "fact about this rail\'s picture rather than about the "
              "vocabulary, and stating it is cheaper than rediscovering it. "
              "The third case it kills names the colours: the returned "
              "title\'s bed holds composited values it has no blender of its "
              "own to make"),
]
