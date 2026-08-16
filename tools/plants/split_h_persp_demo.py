"""split_h_persp_demo's five load-bearing mechanisms, each planted and required RED.

The rail is TWO PERSPECTIVE CAMERAS over one world,
and its claims are deliberately independent: what makes the two bands
different TRAPEZOIDS (the matrix, per scanline) and what makes them look at
different WORLD REGIONS (the origin, per band) are separate mechanisms with
separate tests. The plant set is chosen so that each falls on its own — a set
that only ever broke both at once could not tell whether either test was doing
any work.

EVERY PLANT REACHES RENDERED PIXELS, which is not a slogan here: the seam-in-isolation rail
measured that Mesen's power-on OAM is a fixed parked pattern `SetPowerOnSeed`
does not reach, so a plant whose only effect is via OBJ enable/disable is
TEST-BLIND by construction. This rail draws no sprites at all, so every plant
below lands in M7A-M7D or in the Mode 7 origin and shows up in the predicted
frame.

WHAT THE SET FOUND, and it is why the set exists.
`shp-band2-streams-camera-as-set` took
`test_the_two_bands_are_different_trapezoids` GREEN on its first run: that case
compared the two bands' transition-count SPANS, and a span moves under ROTATION
as well as under scale — with band 2 streaming camera A's set at heading 4 the
spans read 6 and 8 and the assertion passed while the picture was wrong. The
case now compares the top/bottom RATIO, a scale property a rotation does not
touch (3.00 vs 3.00 planted, 3.00 vs 13.00 shipped), and the plant takes it
red. A test name is a contract, and "different trapezoids" cannot be checked by
counting checker edges.

NOT PLANTED, deliberately: the BAND-PRIORITY contract (band 2's matrix pair
must sit on LOWER channel numbers than band 1's, so its line-0 stray unit is
masked). Swapping the four `SHP_CH_*` symbols is refused at ASSEMBLE time by
shp_cam.asm's own `.assert SHP_CH_AB2 < SHP_CH_AB1`, so the defect never
reaches a ROM and the plant would say nothing about the tests — docs/46's
whole point, and the same ruling `tools/plants/brawler.py` took on `PARK_Y`.
The build stopping IS the falsification there, and it is checked by the
assertion rather than by this harness. (Worth recording for a future reader:
at BOOT the priority inversion would be invisible anyway, because band 2's
skip pointer aims at zoom index 0 and that pose is camera A's heading-0 pose
by construction — the stray unit writes the matrix that was already there.
It only becomes visible once the heading is driven, which is where
`test_holding_right_rotates_camera_a_only` would catch it.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
CAM = SUPERFORGE / "engine" / "features" / "shp_cam" / "shp_cam.asm"
ROM = SUPERFORGE / "build" / "split_h_persp_demo.sfc"
T = "tests/test_split_h_persp_demo.py::"

PLANTS = [
    Plant(
        id="shp-repeat-bit-cleared",
        file=CAM,
        old="""    lda #(128 | SHP_SEAM)
    sta f:SHP_IDX_AB1_LONG + 0      ; band 1: lines 0..111, then it ENDS
    sta f:SHP_IDX_CD1_LONG + 0
""",
        new="""    lda #SHP_SEAM                   ; PLANT: NON-repeat -> band 1 goes FLAT
    sta f:SHP_IDX_AB1_LONG + 0
    sta f:SHP_IDX_CD1_LONG + 0
    lda #(128 | SHP_SEAM)
""",
        artifact=ROM,
        build=["split_h_persp_demo"],
        tests=[
            T + "test_the_index_tables_are_the_declared_band_shape",
            T + "test_the_whole_picture_is_one_world_through_two_perspective_cameras",
            T + "test_the_two_bands_are_different_trapezoids",
        ],
        why="THE PERSPECTIVE ITSELF. Bit 7 of the count byte is the whole "
            "difference between a per-scanline trapezoid and one constant "
            "matrix held for 112 lines: cleared, band 1's channel transfers "
            "ONE 4-byte unit at line 0 and then idles, so camera A's floor "
            "stops receding and becomes a flat top-down view at its horizon "
            "scale. Everything else stays perfectly correct — the pointer is "
            "right, the pose set is right, the origin is right, the seam is "
            "still one scanline — which is why the count-byte case names the "
            "bit and TWO PICTURE cases prove it reaches the PPU. Without "
            "those two the module would be asserting bytes it wrote itself.",
    ),
    Plant(
        id="shp-band2-streams-camera-as-set",
        file=CAM,
        old="    SHP_POSE_PTR SHP_ZOOM, SHP_B_AB_BASE, SHP_B_CD_BASE, "
            "SHP_AB2_PTR_LONG, SHP_CD2_PTR_LONG",
        new="    SHP_POSE_PTR SHP_ZOOM, SHP_A_AB_BASE, SHP_A_CD_BASE, "
            "SHP_AB2_PTR_LONG, SHP_CD2_PTR_LONG  ; PLANT: band 2 -> camera A's set",
        artifact=ROM,
        build=["split_h_persp_demo"],
        tests=[
            T + "test_the_index_tables_are_the_declared_band_shape",
            T + "test_the_whole_picture_is_one_world_through_two_perspective_cameras",
            T + "test_the_two_bands_are_different_trapezoids",
            T + "test_holding_up_zooms_camera_b_only",
            T + "test_the_zoom_clamps_at_both_ends_and_does_not_wrap",
            # NOT `test_the_zoom_floor_collapses_...`: at zoom 0 the two sets
            # COINCIDE by construction (zoom 0 is pinned onto camera A's
            # heading-0 pose), so the planted ROM renders that state exactly
            # like the baseline and the case survives CORRECTLY. Naming it
            # here would demand a red the design guarantees cannot happen.
        ],
        why="THE SECOND POSE SET — the claim says `sh2_cam` "
            "cannot make. Band 2 keeps its own index, its own channel pair, "
            "its own DASB and its own origin; only the SET it indexes moves "
            "to camera A's. The result is still a coherent perspective band "
            "that still animates when Up is held and still carries red — it "
            "is simply camera A's trapezoid at a different heading, which is "
            "`split_h_2p_demo`. Widest blast radius of the five, and that "
            "breadth is the point: every zoom case in the module is really a "
            "claim about the second set.",
    ),
    Plant(
        id="shp-origin-band2-folded",
        file=CAM,
        old="""    lda #SHP_POS_BX
    sta f:SHP_OTBL_XY_LONG + 6      ; M7X, band 2
""",
        new="""    lda #SHP_POS_AX                 ; PLANT: camera B folded onto camera A
    sta f:SHP_OTBL_XY_LONG + 6
""",
        artifact=ROM,
        build=["split_h_persp_demo"],
        tests=[
            T + "test_the_origin_tables_carry_two_world_positions",
            T + "test_the_whole_picture_is_one_world_through_two_perspective_cameras",
            T + "test_each_band_looks_at_its_own_world_stripe",
            T + "test_the_zoom_floor_collapses_the_matrix_but_not_the_world_position",
        ],
        why="the same-centre control, as a plant rather than a ROM. Camera B's "
            "world X folds onto camera A's — and because the HOFS value is "
            "derived from it two instructions later, BOTH halves of the "
            "origin fold, which is what a genuine "
            "world pan needs (splicing only the centre shifts the sampled "
            "texel by ~0 in the near band). Band 2 leaves the WARM stripe, "
            "so the red position signal must die WHILE the two trapezoids "
            "stay different — the exact complement of the collapse control, "
            "and the pair is why P1 and P4 are two claims rather than one.",
    ),
    Plant(
        id="shp-band2-origin-pinned-to-band1s-bottom",
        file=CAM,
        old="""    sbc #SHP_LINES
    sta f:SHP_OTBL_HV_LONG + 8      ; VOFS = posBy - 224 (band 2's bottom line)
""",
        new="""    sbc #SHP_SEAM                   ; PLANT: band 2 pinned to band 1's bottom
    sta f:SHP_OTBL_HV_LONG + 8
""",
        artifact=ROM,
        build=["split_h_persp_demo"],
        tests=[
            T + "test_the_origin_tables_carry_two_world_positions",
            T + "test_the_whole_picture_is_one_world_through_two_perspective_cameras",
        ],
        why="THE PER-BAND ANCHOR, and the narrowest plant here on purpose. "
            "Each band's VOFS subtracts that band's OWN bottom scanline, "
            "which is what pins its viewpoint to its own last row rather "
            "than to the frame's. Pinning band 2 to 112 slides its whole "
            "view 112 world rows north: the picture stays perfectly "
            "coherent — same periods, same ramp, same stripe, same seam — "
            "and is simply looking somewhere else. NOTHING but a whole-frame "
            "prediction can see it, which is the case for predicting pixels "
            "rather than measuring runs.",
    ),
    Plant(
        id="shp-zoom-floor-clamp-dropped",
        file=CAM,
        old="""    lda z:SHP_ZOOM
    beq @nodown                     ; already collapsed onto camera A: hold
    dec a
""",
        new="""    lda z:SHP_ZOOM
    dec a                           ; PLANT: no floor — 0 wraps to $FFFF
""",
        artifact=ROM,
        build=["split_h_persp_demo"],
        tests=[
            T + "test_the_zoom_clamps_at_both_ends_and_does_not_wrap",
            T + "test_the_zoom_floor_collapses_the_matrix_but_not_the_world_position",
        ],
        why="A zoom is a SEGMENT, not a cycle, and its floor is the rail's "
            "runtime collapse CONTROL — so the clamp is load-bearing twice "
            "over. Without it a 16-bit `dec` walks below zero, the pointer "
            "multiply turns $FFFF into base + 448*65535 mod 65536, and band "
            "2 streams whatever ROM bytes live there as a matrix. The plant "
            "is deliberately on the DOWN arm alone: the ceiling clamp is a "
            "`cmp`/`bcs` and survives, so the two ends fail independently "
            "and the module cannot pass the pair by testing only one.",
    ),
]
