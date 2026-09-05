"""aurora — what a sky with no palette can get wrong while still looking right.

Nine plants. Eight are silent-corruption defects that still produce a plausible
night sky, and one is the allocator refusing a declaration that lies. TWO ARE
DEFECTS THIS RAIL SHIPPED and a person caught by looking, put here so the next
one is caught by the harness instead.

THE SET IS BUILT AROUND WHAT IS UNOBSERVABLE IN A FINISHED FRAME. The card at
the end of a pass is the same picture whether the aurora rose or was simply
there, whether it climbed or appeared in scattered blocks, whether the loop
resets the colour or carries it. Every one of those is a real decision this
rail made and none of them is visible in a still, which is exactly the shape a
falsification harness exists for.

  * `base-page-ships-the-aurora-lit` is the rise, deleted. The generator
    paints the tinted run at phase 0 instead of unlit, so the aurora is
    already there when the fade comes up and the cycle's first pass is an
    ordinary recolour. THE FINISHED CARD IS BYTE-IDENTICAL. Only the first
    beat differs, and only for the two seconds the fade takes.

  * `slot-order-scattered-again` is the order the rail SHIPPED before it was
    measured, and it is the subtler of the pair: the finished card is again
    identical, the rise still takes exactly as long, and the aurora still
    arrives — in 8x8 blocks all over the sky instead of climbing out of the
    horizon. A case that only asked "is more of it lit than before" passes.

  * `unrise-loses-its-last-slice` is an off-by-one in the drain, and it is
    the plant that says why the restore is asserted as a BYTE EQUALITY. The
    sky still looks empty at the next fade-in: what is left behind is a dozen
    tiles of aurora at a hue two phases old, on a night gradient, which is a
    few units of difference. Only the shipped bytes tell them apart.

  * `unrise-does-not-snap-the-cursor` is the second SHIPPED defect. Without
    the snap a pass resumes mid-phase, so the tiles between the cursor and the
    end of the run light FIRST, high in the sky, and sit there disconnected
    while the curtains climb underneath them. Thirteen tiles, at the top, once
    a loop.

WHAT THIS SET DOES NOT HOLD, and why it is stated rather than quietly absent.
A tenth plant was written and withdrawn: removing `@freeze` from the RESET
beat, on the stated grounds that the restore and the cycle share a channel and
would contend. **They do not.** `aur_hue_nmi` tests `ES_AUR_RST` first and
returns, so no hue slice can reach the channel while a drain is running — the
freeze's only consequence is that `ES_AUR_PEND` stops accumulating, worth
about thirteen tiles of burst at the top of the next pass. That is a
difference of DEGREE from the three to five tiles the rate cursor's own
one-entry offset already produces, and no assertion separates them without
being brittle about a number that has no reason to be stable. The plant was
measured, found not to fail DIFFERENTLY from the tree's own behaviour, and
dropped; `aur_hue_unrise`'s contract was corrected to say what the freeze
actually buys instead of repeating the contention claim.

  * `the-hold-does-not-reach-the-pen` restores the rail's original gate, where
    B held the colour cycle and the pen went on writing underneath it. A still
    taken with B down still shows a sky that is not moving.

  * `play-waits-a-round-number` replaces the beat's exact wait with 200 frames
    — close enough to AUR_RATE_LEN that the rise still finishes and the card
    still stands, and wrong enough that the loop no longer closes on the frame
    it should. It is the plant for asserting a PERIOD rather than "it comes
    back round".

  * `the-straddle-is-one-transfer` reintroduces the defect the uninitialised
    read detector named. A1B is constant, so a slice crossing a chunk boundary
    wraps to $0000 and reads the WRAM mirror. Seven of the cycle's slices
    cross. The picture stays recognisably an aurora with a few tiles of
    garbage in it, which is why a screenshot never found it.

  * `direct-colour-cleared` is the allocator half and the rail's headline in
    reverse: CGWSEL bit 0 comes from the video claim, so clearing it there is
    the one-line change that turns BG1 back into an indexed layer. The sky
    then draws from CGRAM like anything else — and the picture is still a
    picture, which is why the case that catches it counts colours against
    CGRAM rather than looking at the screen.
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
    Plant(id="base-page-ships-the-aurora-lit",
          file=GEN,
          old="        _, by, _ = fit_tile(_block(0, c[0], c[1], lit=False), force=best)",
          new="        _, by, _ = fit_tile(_block(0, c[0], c[1]), force=best)"
              "  # PLANT",
          artifact=ROM,
          build=["aurora"],
          # NOT the un-rise case, which stays green here and SHOULD: it asserts
          # VRAM equals the base page the ROM ships, and that holds whatever
          # the base page holds. It is an equality against the artifact, not
          # against a picture, so it is blind to this defect by construction
          # rather than by omission.
          tests=[T + "test_the_scene_fades_up_on_a_sky_with_no_aurora_in_it",
                 T + "test_the_rise_climbs_from_the_horizon_rather_than_"
                     "appearing_all_over"],
          why="the rise is the one thing this rail gets for free, and free "
              "things are the easiest to delete by accident. The finished "
              "card is byte-identical with the aurora shipped lit; what goes "
              "is the first beat"),

    Plant(id="slot-order-scattered-again",
          file=GEN,
          old="    order = sorted(tint_cells, key=lambda c: (-c[1], (c[0] * 97) % TW))\n"
              "    slot_of = {c: k for k, c in enumerate(order)}",
          new="    slot_of = {c: (k * 97) % len(tint_cells)      # PLANT\n"
              "               for k, c in enumerate(tint_cells)}",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_the_rise_climbs_from_the_horizon_rather_than_"
                     "appearing_all_over"],
          why="the order the rail shipped before it was measured. Nothing "
              "about a finished frame distinguishes the two, and the rise "
              "still takes exactly as long — it simply arrives in blocks "
              "instead of climbing. One case stands between this and the tree"),

    Plant(id="unrise-loses-its-last-slice",
          file=HUE,
          old="    lda #AUR_HUE_TILES\n    sta z:ES_AUR_RST\n    ; AND THE CURSOR",
          new="    lda #(AUR_HUE_TILES - AUR_RST_SLICE)   ; PLANT\n"
              "    sta z:ES_AUR_RST\n    ; AND THE CURSOR",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_the_unrise_restores_the_page_the_rom_actually_ships"],
          why="why the restore is a byte equality and not a look. What this "
              "leaves behind is a dozen tiles of two-phase-old aurora on a "
              "night gradient — a few units of difference, on a sky that "
              "still reads as empty"),

    Plant(id="unrise-does-not-snap-the-cursor",
          file=HUE,
          # The snap is everything AFTER the RST store, so returning there is
          # exactly "no snap" and leaves the arm itself intact. The first cut
          # of this plant branched to a label it did not define and the BUILD
          # broke — which the harness reports as a plant fault, correctly:
          # a defect that cannot be assembled proves nothing about the tests.
          old="    sta z:ES_AUR_RST\n    ; AND THE CURSOR SNAPS",
          new="    sta z:ES_AUR_RST\n    rts                             ; PLANT\n"
              "    ; AND THE CURSOR SNAPS",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_the_rise_climbs_from_the_horizon_rather_than_"
                     "appearing_all_over"],
          why="a defect this rail shipped and a contact sheet caught. A pass "
              "resuming mid-phase lights the tiles between the cursor and the "
              "end of the run first, at the TOP, and they sit there while the "
              "curtains climb underneath"),

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

    Plant(id="play-waits-a-round-number",
          file=PRES,
          old="    lda #AUR_RATE_LEN               ; one whole pass of the tinted run",
          new="    lda #200                        ; PLANT",
          artifact=ROM,
          build=["aurora"],
          tests=[T + "test_the_loop_closes_on_the_frame_it_should_and_keeps_"
                     "closing"],
          why="close enough that the rise still finishes and the card still "
              "stands. This is the plant that makes asserting a PERIOD worth "
              "more than asserting the loop comes back round — it does"),

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
