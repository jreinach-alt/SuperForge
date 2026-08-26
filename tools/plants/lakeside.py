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
WATER_ASM = SUPERFORGE / "engine" / "features" / "water" / "water.asm"
GEN = SUPERFORGE / "tools" / "gen_lakeside_assets.py"
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
    # ---- the surf ---------------------------------------------------------
    # Four plants for the wave, each aimed at ONE of the four claims it makes:
    # that the waterline moves, that what it crosses is wet while covered and
    # dry while bare, that the run-up is faster than the draw-down, and that all
    # of it is measured against the declared tick rather than the frame. They
    # fail differently on purpose — the first leaves a perfectly plausible
    # static picture, the second leaves a wave that still moves, the third
    # leaves one that still wets the sand, and the fourth is invisible on NTSC
    # altogether.

    Plant(id="surf-phase-frozen",
          file=WATER_ASM,
          old="""    lda z:ES_WAT_SCROLL
    .repeat LK_SURF_STEP_SHIFT
    lsr a                           ; ...one phase per LK_SURF_STEP_PX of drift
    .endrepeat
    and #(LK_SURF_PHASES - 1)""",
          new="""    lda #LK_SURF_REF_PHASE          ; PLANT: the wave holds at one phase
    and #(LK_SURF_PHASES - 1)""",
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_the_waterline_advances_up_the_shore_and_draws_back",
              T + "test_the_swash_zone_is_wet_when_covered_and_dry_when_bare",
              T + "test_the_swash_runs_up_faster_than_the_backwash_draws_down",
          ],
          why="the transfer still fires every armed VBlank, the blob is still "
              "resident, the drift still runs and the highlight still walks — "
              "so the lake is a lake and only the WAVE is gone. A test that "
              "read the phase index, or counted the DMA, or asserted that the "
              "slots hold a declared phase, would all pass: the slots hold a "
              "declared phase, just the same one forever. The three cases that "
              "die measure the boundary in the PICTURE across a whole cycle, "
              "which is the only place a frozen wave shows. The stilled case "
              "stays green because a motionless surf is exactly what it "
              "asserts — the matched pair the drift plants already establish"),

    Plant(id="surf-band-never-transparent",
          file=GEN,
          old="""            if y < top:
                line.append(0)""",
          new="""            if y < top:
                line.append(fill[ty][u])    # PLANT: opaque above the waterline""",
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_the_swash_zone_is_wet_when_covered_and_dry_when_bare",
              T + "test_the_waterline_advances_up_the_shore_and_draws_back",
              T + "test_the_surfaces_top_edge_is_a_pixel_boundary_not_a_row_boundary",
              T + "test_the_surface_starts_on_the_row_the_vofs_correction_promises",
              T + "test_no_pixel_under_the_surface_is_explicable_as_unblended_world",
          ],
          why="THE WET/DRY CLAIM'S OTHER HALF, removed. With the band opaque at "
              "every phase the surface covers the whole swash zone all the "
              "time, so the beach is wet even when the wave is out — and "
              "nothing about the picture announces it, because the water still "
              "has an edge (the band's top row) and the fill still changes with "
              "the phase. What dies is every case that needs a pixel to be BARE "
              "somewhere: the swash zone's dry half has no bare pixel to check, "
              "the boundary sweep finds the same waterline at every phase, and "
              "the per-row count of pixels explicable as unblended world goes "
              "to zero where the surface's own VRAM says it should not. Planted "
              "in the GENERATOR because that is where the transparency comes "
              "from — the ROM's DMA is indifferent to what it moves"),

    Plant(id="surf-schedule-symmetric",
          file=GEN,
          old="""SURF_H = [
    6, 13, 20, 26, 30, 32,                                       # the swash
    31, 29, 27, 25, 23, 21, 19, 17, 16, 14, 12, 11, 9, 8,        # the backwash
    8, 7, 7, 6, 6, 6, 7, 7, 6, 6, 6, 6,                          # the lull
]""",
          new="""SURF_H = [                      # PLANT: a symmetric oscillation
    6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 29, 30, 31, 32,
    32, 31, 30, 29, 28, 26, 24, 22, 20, 18, 16, 14, 12, 10, 8, 6,
]""",
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_the_swash_runs_up_faster_than_the_backwash_draws_down",
          ],
          why="surf is not a sine, and this is what it looks like when it is. "
              "The waterline still sweeps its whole 26 px, the wet/dry equality "
              "still holds pixel for pixel, the cycle still closes, the region "
              "arm is untouched — every other case in the module stays green, "
              "which is exactly why the asymmetry needs a case of its OWN "
              "rather than being assumed to fall out of the others. The one "
              "that dies measures the longest monotone run in each direction "
              "off the picture and compares their rates; a symmetric schedule "
              "makes them equal, and a picture that pulses instead of breaking "
              "is the visible result"),

    Plant(id="surf-drift-unscaled",
          file=LAKE,
          old="""    TS_STEP z:US_TSW_ACC, TS_DRIFT_BASE
    sta z:US_TSW""",
          new="""    lda #LK_WATER_SPEED             ; PLANT: a per-frame constant, unscaled
    sta z:US_TSW""",
          artifact=ROM,
          build=["lakeside"],
          tests=[
              T + "test_the_surf_sweeps_the_same_distance_per_real_second_on_both_machines",
          ],
          why="THE PLANT NTSC CANNOT SEE. The published step is still 1 px "
              "every frame, which on NTSC is what TS_STEP publishes anyway, so "
              "the ROM is bit-for-bit indistinguishable in behaviour on the "
              "machine every other case in this module runs on: the surf "
              "sweeps its 26 px, the wet/dry equality holds, the asymmetry "
              "holds, the cycle closes, the picture repeats on all three "
              "periods. On PAL the whole rail — drift, highlight and wave — "
              "runs at five sixths speed in real time. The one case that dies "
              "is the two-machine probe, whose window is REAL SECONDS off the "
              "master clock rather than frames; that is the difference between "
              "measuring a rate and measuring the harness"),
]
