"""split_h_irq_grad_demo's falsification set — one plant per NEW behaviour.

This rail inherits a proven mechanism and adds four things to it: a boot-built
COLDATA table, a colour-math mode, a channel BUDGET in which the freed pair
pays for the gradient, and — the one `seam_irq_trial` structurally could not
have — a LIVE per-frame origin, because the cameras move. Each gets the
realistic defect it exists to prevent. Two more plants cover the inherited
mechanism's own discipline (the seam line and the handler's HBlank gate),
because this handler is not that handler: its critical section was re-measured
here and both defects would land differently in this composition.

THE CONTROLS STAY HEALTHY through every plant — the harness rebuilds only
`split_h_irq_grad_demo`, so `shg_nograd` / `shg_origin` keep their pre-plant
bytes. That has a consequence worth stating, because it shaped the `tests=`
lists: a plant in shared feature ASM cannot be caught by the GOLD case (which
compares two control ROMs and never reads the subject), so every plant below
names a test that actually reads the subject binary.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
CAM = SUPERFORGE / "engine" / "features" / "shg_cam" / "shg_cam.asm"
GRAD = SUPERFORGE / "engine" / "features" / "shg_grad" / "shg_grad.asm"
SCENE = SUPERFORGE / "game" / "split_h_irq_grad_demo" / "scenes" / "split.asm"
ROM = SUPERFORGE / "build" / "split_h_irq_grad_demo.sfc"
T = "tests/test_split_h_irq_grad_demo.py"

PLANTS = [
    # ---- 1. the gradient table's own byte layout ---------------------------
    Plant(
        id="grad-entry2-payload-offset",
        file=GRAD,
        old="    sta f:ES_SHG_GTBL_LONG + 2, x           ; entry 2 payload (skip its header)",
        new="    sta f:ES_SHG_GTBL_LONG + 1, x           ; PLANT: entry 2 payload, header not skipped",
        artifact=ROM,
        build=["split_h_irq_grad_demo"],
        tests=[f"{T}::test_the_gradient_writes_one_exact_coldata_byte_to_every_scanline"],
        why="a two-entry HDMA table has a header byte between its payloads, "
            "and forgetting to step over it is THE off-by-one of this loop — "
            "the +1 form is what you write if you think of the table as one "
            "flat array of 224 values. It shifts every band-2 byte one line "
            "early AND overwrites entry 2's own header with a payload value, "
            "so the second half of the ramp is wrong in two independent ways. "
            "The exact per-line oracle must see it; a monotonic-trend "
            "assertion would not, which is the reason that case is exact"),

    # ---- 2. the colour-math mode: the gradient silently vanishes -----------
    # HISTORY, kept because it is the finding and not the anecdote: this slot
    # first planted CGWSEL bit 1 ("take the subscreen, not the fixed colour")
    # and the harness reported it TEST-BLIND — md5 moved, assertion green. The
    # test was not blind; the PLANT was inert, and Mesen2's own branch says so
    # (SnesPpu.cpp:1353-1362): with bit 1 set and nothing on the subscreen,
    # `_subScreenPriority[x] == 0` and `otherPixel = _state.FixedColor` ANYWAY.
    # This rail never writes TS, so both arms deliver the same pixel and the
    # bit is genuinely inert here. The lesson is CLAUDE.md's "two kinds of
    # question": the effect of a bit on OUR composition is answered by reading
    # the branch, not by knowing what the bit is called — and shg_grad.asm's
    # own header had already quoted the correct reading ("bit1 clear =>
    # unconditionally"), which is exactly the word that gives it away.
    Plant(
        id="cgadsub-wrong-layer-bit",
        file=GRAD,
        old="SHG_CGADSUB_ADD_BG1 = 1 << 0",
        new="SHG_CGADSUB_ADD_BG1 = 1 << 1    ; PLANT: BG2's bit, not BG1's",
        artifact=ROM,
        build=["split_h_irq_grad_demo"],
        tests=[f"{T}::test_the_gradient_writes_one_exact_coldata_byte_to_every_scanline"],
        why="CGADSUB's low six bits are a per-LAYER enable mask and the layer "
            "this rail draws is BG1 = bit 0 (SnesPpu.cpp:2209 + :855/:1190, "
            "where Mode 7 renders as layerIndex 0). Setting bit 1 enables "
            "colour math on a layer nothing draws: the channel is armed, the "
            "227-byte table is correct, every structural check still passes — "
            "and the picture loses its gradient entirely. That is the WORST "
            "shape this feature's defects take, and 'which bit is BG1' is a "
            "genuine one-off in a register whose field order nobody "
            "remembers"),

    # ---- 3. the channel budget: the freed pair leaks back into HDMAEN ------
    Plant(
        id="seam-in-hdmaen-mask",
        file=SCENE,
        old="""    lda #((1 << ES_H_SHGAB_CH) | (1 << ES_H_SHGCD_CH))
.ifndef SHG_NO_GRAD
    ora #(1 << ES_H_SHGGR_CH)
.endif
.ifdef SHG_HDMA_ORIGIN
    ora #((1 << ES_H_SHGXY_CH) | (1 << ES_H_SHGHV_CH))
.endif""",
        new="""    lda #((1 << ES_H_SHGAB_CH) | (1 << ES_H_SHGCD_CH))
.ifndef SHG_NO_GRAD
    ora #(1 << ES_H_SHGGR_CH)
.endif
    ora #((1 << ES_H_SHGXY_CH) | (1 << ES_H_SHGHV_CH)) ; PLANT: seam bits leaked""",
        artifact=ROM,
        build=["split_h_irq_grad_demo"],
        tests=[f"{T}::test_the_freed_channels_pay_for_the_gradient_on_the_silicon"],
        why="out-of-HDMAEN is a CONVENTION rather than a schema field "
            "in any schema field, so a plant is its only enforcement — and on THIS rail "
            "the convention carries more than it did on the trial, because "
            "the two channels staying out of the mask is the entire argument "
            "for the gradient's channel being affordable. A scene author "
            "extending the mask with 'all my channels' is one ora away. The "
            "declared detector is the live-$420C read, and the picture cannot "
            "substitute: an enabled seam channel's stage block misparses as a "
            "count-0 table and terminates at line 0 doing nothing visible"),

    # ---- 4. the seam line ---------------------------------------------------
    Plant(
        id="vtime-off-by-one",
        file=CAM,
        old="SHG_VTIME = SHG_SEAM",
        new="SHG_VTIME = SHG_SEAM - 1        ; PLANT: one internal scanline early",
        artifact=ROM,
        build=["split_h_irq_grad_demo"],
        tests=[f"{T}::test_the_seam_row_is_exact_line_111_cool_line_112_warm",
               f"{T}::test_h2_the_fire_lands_in_the_seam_hblank_window"],
        why="VTIME counts INTERNAL scanlines and content line L draws during "
            "scanline L+1, so arming SEAM-1 is the natural reading for anyone "
            "thinking in content lines — and it turns band 1's last row warm. "
            "Both the picture case and the timing case must fire: the seam "
            "row sees content 111 pick up band 2's origin, and the entry-V "
            "mirror moves off the seam. Parametrised over both builds, so "
            "the subject arm proves the third channel did not mask it"),

    # ---- 5. the LIVE per-frame origin — this rail's own new behaviour ------
    Plant(
        id="stage-not-restamped",
        file=CAM,
        old="""    jsr cam_stamp_band1
    jsr cam_stamp_stage""",
        new="""    jsr cam_stamp_band1
    ; PLANT: band 2's staged bytes never re-computed from the live position""",
        artifact=ROM,
        build=["split_h_irq_grad_demo"],
        tests=[f"{T}::test_the_two_bands_pan_at_different_speeds"],
        why="THE defect `seam_irq_trial` structurally could not have: its "
            "staged bytes were constants, so a missing re-stage was invisible "
            "there and its own suite would stay green. Here camera 2 moves, "
            "so dropping the re-stage freezes band 2 at its boot pose while "
            "band 1 keeps panning — a half-dead split that still renders a "
            "clean seam, correct colours and a perfect gradient. Realistic "
            "because the VBlank hook has two calls and only one of them is "
            "obviously about 'the registers'. It is also why the "
            "different-speeds case asserts band 2 CHANGES at a half-period "
            "offset: a frozen band satisfies every periodicity clause"),

    # ---- 6. the write-twice ValueLatch discipline --------------------------
    # THE INTERLEAVE TEAR, as a plant rather than as a control ROM.
    # The interesting build is the one where the handler
    # writes the same eight bytes as CPU stores whose byte order interleaves
    # each pair across the two registers, so every write latches
    # `value<<8 | prev` through the ONE shared Mode-7 ValueLatch and both
    # registers end up corrupt. A plant is the stronger form of the same
    # statement — it costs no registration sites and it requires a named test
    # to go RED — but it has to reach the defect by a route a real author
    # would take, which is why this is an OFFSET typo rather than a rewrite of
    # the fire: staging the second word of each pair one byte early puts
    # [Xlo, Ylo, Yhi, 0] in the block, and mode 3's B,B,B+1,B+1 send then
    # hands $211F both Xlo AND Ylo. Same corruption, realistic cause.
    Plant(
        id="stage-byte-interleave",
        file=CAM,
        old="""    lda f:SHG_POS2Y_LONG
    sta f:SHG_STAGE_XY_LONG + 2     ; M7Y
    sec
    sbc #SHG_LINES
    sta f:SHG_STAGE_HV_LONG + 2     ; VOFS = posy - 224 (band 2's bottom line)""",
        new="""    lda f:SHG_POS2Y_LONG
    sta f:SHG_STAGE_XY_LONG + 1     ; PLANT: staged one byte early -> the two
    sec                             ; registers' bytes interleave through the
    sbc #SHG_LINES                  ; ONE shared Mode-7 write-twice ValueLatch
    sta f:SHG_STAGE_HV_LONG + 1     ; PLANT: same, on the HOFS/VOFS pair""",
        artifact=ROM,
        build=["split_h_irq_grad_demo"],
        tests=[f"{T}::test_the_seam_row_is_exact_line_111_cool_line_112_warm"],
        why="the staged block's byte order IS the latch contract: mode 3 sends "
            "B,B,B+1,B+1, so [M7X word][M7Y word] is what keeps each "
            "register's lo and hi adjacent through the shared ValueLatch "
            "(SnesPpu.cpp:1992/2008/2082-2097 — one latch for ALL Mode-7 "
            "pairs). Stage the second word one byte early and $211F receives "
            "Xlo then Ylo: M7X becomes (Ylo<<8)|Xlo and band 2 renders from a "
            "garbage origin. An offset typo in a four-store routine is a "
            "realistic way to arrive there, and this is the ONE defect class "
            "is worth a whole control ROM elsewhere — so the rail owes "
            "it a red test, which is exactly what a plant buys and what "
            "the cold read found missing"),

    # ---- 7. the handler's HBlank spin gate ---------------------------------
    Plant(
        id="spin-gate-removed",
        file=CAM,
        old="""    bit a:$4212                     ; stalls the CPU, so the fire below always
    bvc @spin                       ; lands strictly after that line's HDMA""",
        new="""    bit a:$4212                     ; PLANT: spin gate removed — the fire
    ; bvc @spin                     ; lands mid-render of content line 111""",
        artifact=ROM,
        build=["split_h_irq_grad_demo"],
        tests=[f"{T}::test_the_seam_row_is_exact_line_111_cool_line_112_warm",
               f"{T}::test_h2_the_fire_lands_in_the_seam_hblank_window"],
        why="without the gate the MDMAEN lands at handler entry (measured dot "
            "47 of scanline 112 on this rail), mid-render of content line "
            "111 — the lazy flush renders that line's right side with band "
            "2's origin, and the fire-completion mirror leaves the window. "
            "Re-planted here rather than inherited because this handler's "
            "critical section was re-measured for this composition ( "
            "§4: completion dot 16, not the trial's 10), and a future "
            "'optimisation' deleting the spin is exactly this edit"),
]
