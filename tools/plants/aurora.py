"""aurora — what a sky with no palette can get wrong while still looking right.

Seven plants. Six are silent-corruption defects that still produce a plausible
night sky, and one is the allocator refusing a declaration that lies.

THE SET IS BUILT AROUND WHAT IS UNOBSERVABLE IN A FINISHED FRAME. The card at
the end of a pass is the same picture whether the aurora was there from the
first frame or arrived, whether the loop carries the colour forward or puts it
back, whether the pen finished before the beat ended. Every one of those is a
real decision this rail made and none of them is visible in a still, which is
the shape a falsification harness exists for.

  * `the-loop-puts-the-colour-back` is the defect this rail SHIPPED for a
    while, and it is the tidy-looking one: restore the CHR page at each lap
    and every pass opens on exactly the same picture, which is what a loop is
    supposed to do. What it throws away is the headline — fifteen of the
    sixteen phases become unreachable and the fifty-one-second journey from
    cyan-teal to violet never happens. Every other case in the module passes
    against it.

  * `base-page-ships-the-run-unlit` is the reverse of a beat the rail shipped
    and the owner rejected. Unlit, the cycle's first pass IS the aurora
    arriving — free, and pretty — and it forces a screen-coherent slot order
    to stop the half-risen picture reading as a corrupted upload. That order
    reads as a wipe. The finished card is byte-identical either way.

  * `play-ends-before-the-pen-does` stops watching the pen twelve frames
    early, so the card begins standing while the exit swash is still being
    drawn. The word finishes anyway; only the PERIOD moves.

  * `the-hold-does-not-reach-the-pen` restores the rail's original gate, where
    B held the colour cycle and the pen went on writing underneath it. A still
    taken with B down still shows a sky that is not moving.

  * `the-straddle-is-one-transfer` reintroduces the defect the uninitialised
    read detector named. A1B is constant, so a slice crossing a chunk boundary
    wraps to $0000 and reads the WRAM mirror. Seven of the cycle's slices
    cross. The picture stays recognisably an aurora with a few tiles of
    garbage in it, which is why a screenshot never found it.

  * `direct-colour-cleared` is the allocator half and the rail's headline in
    reverse. It is expected to REFUSE the build: CGWSEL bit 0 comes from the
    video claim, so clearing it means the composition no longer owns the port,
    `ES_SCR_CREDITS_CGWSEL` stops being emitted, and the scene's write to
    $2130 becomes undeclared. `-and-the-write-with-it` carries the same defect
    through into a ROM that assembles, which is what someone would do next.

WHAT THIS SET DOES NOT HOLD, and why it is stated rather than quietly absent.

Two plants were written and withdrawn after measurement.

`the-reset-does-not-hold-the-cycle` removed `@freeze` from the RESET beat on
the stated grounds that the restore and the cycle would contend for a channel.
They never did. When the un-rise existed, `aur_hue_nmi` tested its counter
first and returned; now there is no un-rise at all. The freeze is worth a few
tiles of accumulated burst, which is a difference of degree from what the rate
cursor's own offset already produces, and no assertion separates them without
being brittle about a number that has no reason to be stable.

`slot-order-scattered-again` — or rather its inverse, now that the tree ships
the scattered order — CANNOT BE HELD AT ALL, and that is worth stating plainly
because the order is a deliberate choice the owner made. While the aurora
ROSE, the order was strongly observable: the two states of a rising tile are
"nothing" and "a curtain", so a scattered first pass read as 8x8 blocks all
over the sky. With the rise gone, the only difference the order makes is HOW a
mix of two adjacent phases is distributed — and those phases are five degrees
of hue apart, under the dither's own noise. MEASURED on the shipped ROM: four
8x8 cells of the sky change in a hundred and twenty frames. A test asserting
the scatter would be asserting something with almost no observable
consequence, which is the indirect-evidence trap in a different costume. The
order is recorded in `cut_bg1`'s docstring and in `aur_hue`'s header as a
judgement, and it is not defended by a plant.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
GEN = SUPERFORGE / "tools" / "gen_aurora_assets.py"
HUE = SUPERFORGE / "engine" / "features" / "aur_hue" / "aur_hue.asm"
WRITE = SUPERFORGE / "engine" / "features" / "aur_write" / "aur_write.asm"
PRES = SUPERFORGE / "engine" / "features" / "aur_pres" / "aur_pres.asm"
MODE = SUPERFORGE / "engine" / "features" / "aur_mode" / "feature.toml"
ROM = SUPERFORGE / "build" / "aurora.sfc"
T = "tests/test_aurora.py::"

PLANTS = [
    Plant(id="the-hold-does-not-reach-the-pen",
          file=WRITE,
          old="    lda z:ES_AUR_HOLD\n    beq :+\n    sep #$20\n    .a8\n    rts\n"
              ":   .a16\n    .i16\n    lda z:ES_AUR_WFRAME",
          new="    ; PLANT: the pen writes on under the hold\n    lda z:ES_AUR_WFRAME",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_b_stops_the_whole_piece_and_not_merely_the_roll"],
          why="the rail's original gate, where B held the roll and nothing "
              "else. A still taken with B down still shows a sky that is not "
              "moving, so the defect is only visible in the black band"),

    Plant(id="play-ends-before-the-pen-does",
          file=PRES,
          old="    cmp #AUR_WRITE_FRAMES\n    bcs :+",
          new="    cmp #(AUR_WRITE_FRAMES - 12)    ; PLANT\n    bcs :+",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_the_loop_closes_on_the_frame_it_should_and_keeps_"
                     "closing",
                 T + "test_the_pen_writes_the_word_and_then_holds_it"],
          why="the beat stops watching the pen twelve frames early, so the "
              "card begins standing while the exit swash is still being "
              "drawn. Nothing about a still announces it — the word finishes "
              "anyway, a fifth of a second into a beat that lasts five "
              "seconds — and only the PERIOD moves. This is why the loop case "
              "asserts a frame count rather than that the loop comes round"),

    Plant(id="the-loop-puts-the-colour-back",
          file=PRES,
          old="@reset:\n    .a16\n    .i16\n    jsr @freeze",
          new="@reset:\n    .a16\n    .i16\n"
              "    stz z:ES_AUR_SRC                ; PLANT\n"
              "    stz z:ES_AUR_PHASE              ; PLANT\n    jsr @freeze",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_the_colour_travels_and_the_loop_never_puts_it_back"],
          why="THE DEFECT THIS RAIL ACTUALLY SHIPPED FOR A WHILE, in the cut "
              "where the loop restored the CHR page. It is the tidy-looking "
              "change — every pass then opens on exactly the same picture, "
              "which is what a loop is supposed to do — and it silently "
              "throws away the rail's headline: fifteen of the sixteen phases "
              "become unreachable, and the fifty-one-second journey from "
              "cyan-teal to violet never happens. EVERY OTHER CASE IN THE "
              "MODULE PASSES AGAINST IT. A single frame cannot show it and "
              "neither can a single pass"),

    Plant(id="base-page-ships-the-run-unlit",
          file=GEN,
          old="        _, by, _ = fit_tile(_block(0, c[0], c[1]), force=best)",
          new="        _, by, _ = fit_tile(                                # PLANT\n"
              "            [tuple(to5(v) for v in sky(c[1] * 8 + j))\n"
              "             for j in range(8) for _i in range(8)], force=best)",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_the_scene_fades_up_on_the_whole_picture"],
          why="the reverse of a beat this rail once shipped and the owner "
              "rejected. With the tinted run unlit in the base page the "
              "cycle's first pass over it becomes the aurora ARRIVING, which "
              "costs nothing and makes a pretty rise — and forces a "
              "screen-coherent slot order to keep the half-risen picture from "
              "reading as a corrupted upload, which reads as a wipe. THE "
              "FINISHED CARD IS BYTE-IDENTICAL either way; what changes is "
              "only the first two seconds, which is exactly why the beat "
              "needs a case of its own"),

    Plant(id="the-straddle-is-one-transfer",
          file=HUE,
          # PLANTED AT THE CLAMP, NOT AT THE SECOND TRANSFER, and the
          # difference is the whole defect. Skipping the remainder transfer
          # moves FEWER bytes — tiles go missing and nothing reads out of
          # bounds, which is a different bug that the detector cannot see and
          # is what the first cut of this plant did. Arming ONE transfer for
          # the WHOLE run is the original: it runs off the end of the chunk,
          # A1B does not follow, and the read wraps to $0000 in that bank.
          old="    lda #AUR_HUE_PER_CHUNK\n    sec\n"
              "    sbc z:ES_AUR_TMP + 0            ; tiles left in this chunk\n"
              "    cmp z:ES_AUR_TMP + 6\n    bcc :+\n"
              "    lda z:ES_AUR_TMP + 6            ; ...the whole run fits\n"
              ":   sta z:ES_AUR_TMP + 4",
          new="    lda z:ES_AUR_TMP + 6            ; PLANT: uncut, whatever it crosses\n"
              "    sta z:ES_AUR_TMP + 4",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_nothing_reads_a_byte_the_rom_never_wrote"],
          why="the defect the uninitialised-read detector named and a "
              "screenshot could not. A1B is constant, so a slice crossing a "
              "chunk boundary wraps to $0000 and reads the WRAM mirror. The "
              "picture stays recognisably an aurora with a few tiles of "
              "garbage in it"),

    Plant(id="direct-colour-cleared",
          file=MODE,
          old="direct_color = true",
          new="direct_color = false            # PLANT",
          artifact=ROM,
          build=["aurora"],
          expect="build-fails",
          build_names="CGWSEL",
          why="YOU CANNOT TURN THE HEADLINE OFF QUIETLY, and this plant is "
              "here to prove that rather than to prove a picture. Clearing "
              "the field means the composition no longer OWNS CGWSEL, so "
              "`ES_SCR_CREDITS_CGWSEL` stops being emitted and the scene's "
              "write to $2130 becomes an undeclared one — the reg-ownership "
              "gate stops the build naming the port. The declaration and the "
              "permission to write the register are the same fact, which is "
              "the whole argument for declaring CGWSEL bit 0 beside the mode "
              "instead of writing it by hand. Expected to REFUSE, so a ROM "
              "that builds is the failure"),

    Plant(id="direct-colour-cleared-and-the-write-with-it",
          file=MODE,
          old="direct_color = true",
          new="direct_color = false            # PLANT",
          also=((SUPERFORGE / "game" / "aurora" / "scenes" / "credits.asm",
                 "    lda #ES_SCR_CREDITS_CGWSEL      ; ...and CGWSEL b0 with it: DIRECT COLOUR\n"
                 "    sta a:$2130                     ;   arrives through the composition, not\n",
                 "    ; PLANT: no owner, so no write\n"),),
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_the_sky_is_drawn_from_colours_cgram_does_not_hold"],
          why="the same defect CARRIED THROUGH, which is what someone would "
              "do next after the plant above stopped their build: drop the "
              "write the symbol no longer backs. Now it assembles, and BG1 is "
              "an indexed 8bpp layer reading a palette nothing fitted for it. "
              "TWO FILES FOR ONE DEFECT is what `also` is for — the "
              "declaration and its consequence stopped being one file the "
              "moment ownership decided the emission. The picture is still a "
              "picture — the sky just comes out of CGRAM now, from a palette "
              "nothing fitted for it — which is why the case that catches it "
              "COUNTS COLOURS AGAINST CGRAM rather than looking at the "
              "screen. That is the only observation that separates the two"),
]
