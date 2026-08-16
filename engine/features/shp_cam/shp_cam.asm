; =============================================================================
; shp_cam.asm — TWO PERSPECTIVE cameras over one plane, one frame
; =============================================================================
; Band 1 (scanlines 0..111) streams camera A's band-local per-scanline pose out
; of a 64-HEADING ROM set; band 2 (112..223) streams camera B's out of an
; 8-entry ZOOM set. Both go through INDIRECT HDMA in REPEAT mode, so each band
; is a full per-scanline TRAPEZOID rather than a constant matrix — which is the
; whole difference between this rail and the matrix-band pair.
;
; The per-band world POSITION rides two DIRECT origin channels: camera A on the
; cool stripe at world X `SHP_WORLD_PX/2`, camera B on the warm one a stripe
; further out. Those are stamped ONCE at scene enter and never again — these
; cameras do not drive, and holding them still is what makes the red/cool
; separation a stable per-band assertion rather than a moving target.
;
; PER-FRAME COST: TWO POSE POINTERS. Cam_ptrs turns the two animation indices
; into the two bands' live pointers — FOUR 16-bit stores into the index tables
; (plus four DP scratch stores inside the 448-multiply) — and nothing else
; moves in VBlank. The DASB bytes are static (64 headings is ONE LoROM window,
; so there is no slice index), the origin tables are static (these cameras do
; not move), and the index-table skeletons are built once at enter. That is a
; store COUNT, not a measured cycle figure — no `make measure` run was taken
; for this rail and none is claimed.
;
; TWO PROBLEMS THAT DO NOT ARISE HERE. Precompute camera B into WRAM at boot
; and its splice has to target the freshly flipped half of a DOUBLE-BUFFERED
; matrix table, or the band alternates at ~30 Hz. Both are artefacts of camera
; A being a LIVE per-scanline solve. Here BOTH cameras are precomputed by
; construction — the poses are ROM, emitted by a Python generator at build
; time — so there is no boot-time solve to schedule, no second buffer to flip
; and no apply-hook rule to obey. No machinery in this file mirrors either
; lesson, and that absence is deliberate.

; --- the world --------------------------------------------------------------
; DERIVED from the map claim's own size rather than narrated: the Mode 7 blob
; is 2 bytes per tile (tilemap even, CHR odd) over a square plane, so its size
; fixes the side. `no_literals` refuses a bare 1024 (it lands inside an emitted
; WRAM claim and cannot be told apart from a hand-narrated address), and that
; refusal does real work here — writing the derivation is what makes the two
; camera positions follow the map instead of agreeing with it by coincidence.
SHP_MAP_T    = 128                        ; world side, in tiles
SHP_TILE_PX  = 8
.assert 2 * SHP_MAP_T * SHP_MAP_T = ES_R_SHP_MAP_SIZE, error, "shp_cam world size disagrees with the shp_map claim"
SHP_WORLD_PX = SHP_MAP_T * SHP_TILE_PX    ; 1024 — the plane's period

; The generator's stripe period: 32 world tiles of cool then 32 of warm, phased
; so a COOL stripe centres on the world's middle. The two cameras sit one
; stripe apart, which puts camera A dead-centre in a cool stripe and camera B
; dead-centre in a warm one — the per-band POSITION signal, in the red channel.
SHP_STRIPE_T  = 32
SHP_STRIPE_PX = SHP_STRIPE_T * SHP_TILE_PX
SHP_POS_AX = SHP_WORLD_PX / 2             ; camera A: the cool stripe's centre
SHP_POS_AY = SHP_WORLD_PX / 2
SHP_POS_BX = SHP_POS_AX + SHP_STRIPE_PX   ; camera B: the warm stripe's centre
SHP_POS_BY = SHP_WORLD_PX / 2

; --- the split --------------------------------------------------------------
SHP_LINES    = 224                        ; the active picture
SHP_SEAM     = SHP_LINES / 2              ; 112: band 1 is 0..111, band 2 112..223
SHP_HALF_W   = 128                        ; half the 256-px screen: the pivot's x

; --- the two pose sets ------------------------------------------------------
; A band-local pose is SHP_SEAM scanlines x 4 bytes. Camera A's set is 64
; HEADINGS, camera B's is 8 ZOOM steps, and both live at
;
;  ptr = <that set's claim base> + index * SHP_POSE_BYTES
;
; with NO bank arithmetic: 64 x 448 = 28,672 B is the largest whole number of
; poses that fits one LoROM window, so a set never straddles a bank and its
; DASB is a constant written once. `sh2_cam` pays four window-alignment
; .asserts, a `h >> 6` slice index and four per-frame DASB stamps for its 256
; headings; this rail's step is 5.625 degrees, which is a step every frame
; HELD, and the floor does not visibly stutter at that rate.
;
; The sizes are asserted against the claims rather than trusted: if the
; generator's pose count and the allocator's byte count ever disagree, the
; build stops here instead of streaming a neighbouring pose's bytes.
SHP_POSE_BYTES = SHP_SEAM * 4             ; 448 B per band-local pose
SHP_HEADINGS   = 64                       ; camera A's rotation set
SHP_HEAD_MASK  = SHP_HEADINGS - 1
SHP_ZOOMS      = 8                        ; camera B's zoom set
SHP_ZOOM_MAX   = SHP_ZOOMS - 1

.assert SHP_HEADINGS * SHP_POSE_BYTES = ES_R_SHP_POSEA_AB_SIZE, error, "shp_cam heading count disagrees with the shp_poseA_ab claim"
.assert SHP_HEADINGS * SHP_POSE_BYTES = ES_R_SHP_POSEA_CD_SIZE, error, "shp_cam heading count disagrees with the shp_poseA_cd claim"
.assert SHP_ZOOMS * SHP_POSE_BYTES = ES_R_SHP_POSEB_AB_SIZE, error, "shp_cam zoom count disagrees with the shp_poseB_ab claim"
.assert SHP_ZOOMS * SHP_POSE_BYTES = ES_R_SHP_POSEB_CD_SIZE, error, "shp_cam zoom count disagrees with the shp_poseB_cd claim"

SHP_A_AB_BASE = ES_R_SHP_POSEA_AB_ADDR
SHP_A_CD_BASE = ES_R_SHP_POSEA_CD_ADDR
SHP_B_AB_BASE = ES_R_SHP_POSEB_AB_ADDR
SHP_B_CD_BASE = ES_R_SHP_POSEB_CD_ADDR

; --- the HDMA tables, inside the one 96-byte wram claim ---------------------
; 16 B apart so the offsets read as a table rather than as arithmetic. Band 1's
; index tables are 4 B, band 2's 7 B (the skip prefix), the origin tables 11 B;
; the slack is what the power-on zero in cam_arm covers.
SHP_IDX_AB1      = ES_SHP_TBL + 0
SHP_IDX_CD1      = ES_SHP_TBL + 16
SHP_IDX_AB2      = ES_SHP_TBL + 32
SHP_IDX_CD2      = ES_SHP_TBL + 48
SHP_OTBL_XY      = ES_SHP_TBL + 64
SHP_OTBL_HV      = ES_SHP_TBL + 80
SHP_IDX_AB1_LONG = ES_SHP_TBL_LONG + 0
SHP_IDX_CD1_LONG = ES_SHP_TBL_LONG + 16
SHP_IDX_AB2_LONG = ES_SHP_TBL_LONG + 32
SHP_IDX_CD2_LONG = ES_SHP_TBL_LONG + 48
SHP_OTBL_XY_LONG = ES_SHP_TBL_LONG + 64
SHP_OTBL_HV_LONG = ES_SHP_TBL_LONG + 80

; Band 1's live pose pointer is its table's only one; band 2's is the SECOND
; entry's, because entry 1 is the skip prefix.
SHP_AB1_PTR_LONG = SHP_IDX_AB1_LONG + 1
SHP_CD1_PTR_LONG = SHP_IDX_CD1_LONG + 1
SHP_AB2_PTR_LONG = SHP_IDX_AB2_LONG + 4
SHP_CD2_PTR_LONG = SHP_IDX_CD2_LONG + 4

; --- which channel carries which BAND ---------------------------------------
; ONE indirection, and it is what makes the priority contract checkable in one
; place. A band's table address and its DASB bank must land on the SAME
; channel, so both are derived from these four symbols.
;
; Band 2's index table opens with a NON-REPEAT count-112 SKIP entry, which
; transfers ONE stray 4-byte unit at line 0 before holding silent for 111
; lines. HDMA processes CH0->CH7 within each HBlank and a DMAP-$43 unit
; delivers complete pairs, so the LAST channel to write M7A-M7D in that HBlank
; wins coherently. Band 2's pair therefore sits on LOWER channel numbers than
; band 1's, so band 1's proper line-0 values land last and mask the stray
; write. Declared in feature.toml and ASSERTED here — swapping these four
; symbols is a BUILD REFUSAL, which is why there is no falsify plant for it
; (tools/plants/split_h_persp_demo.py records the ruling, and the reason the
; inversion would be invisible at boot anyway).
SHP_CH_AB1 = ES_H_SHPAB1_CH
SHP_CH_CD1 = ES_H_SHPCD1_CH
SHP_CH_AB2 = ES_H_SHPAB2_CH
SHP_CH_CD2 = ES_H_SHPCD2_CH
.assert SHP_CH_AB2 < SHP_CH_AB1, error, "shp_cam: band 2's AB channel must be BELOW band 1's — the line-0 stray unit would win"
.assert SHP_CH_CD2 < SHP_CH_CD1, error, "shp_cam: band 2's CD channel must be BELOW band 1's — the line-0 stray unit would win"

; The DASB byte ($43x7) of each matrix channel, in the scene_mgr shadow the NMI
; MVNs to $4300 — written there rather than to the register file directly, so
; the stamp rides the same commit path cam_arm's staging does.
SHP_SHDW_CH_SIZE = ES_SM_HDMA_SIZE / 8    ; 16 B of register file per channel
SHP_DASB_AB1     = ES_SM_HDMA_LONG + SHP_CH_AB1 * SHP_SHDW_CH_SIZE + 7
SHP_DASB_CD1     = ES_SM_HDMA_LONG + SHP_CH_CD1 * SHP_SHDW_CH_SIZE + 7
SHP_DASB_AB2     = ES_SM_HDMA_LONG + SHP_CH_AB2 * SHP_SHDW_CH_SIZE + 7
SHP_DASB_CD2     = ES_SM_HDMA_LONG + SHP_CH_CD2 * SHP_SHDW_CH_SIZE + 7

; --- the two animation indices, inside the 6-byte dp claim ------------------
SHP_HEAD = ES_SHP_STATE + 0               ; camera A's heading, 0..63
SHP_ZOOM = ES_SHP_STATE + 2               ; camera B's zoom pose, 0..7
SHP_TMP  = ES_SHP_STATE + 4               ; the pose-pointer multiply's scratch

; --- the boot state ---------------------------------------------------------
; Camera A faces heading 0 and camera B sits MID-SWEEP, so the boot frame shows
; two visibly different trapezoids without a button being touched. Zoom 0 is
; camera A's own pose exactly (the generator asserts it), which is why the boot
; value is not 0: booting there would hide the split behind a collapse.
SHP_HEAD_0 = 0
SHP_ZOOM_0 = SHP_ZOOMS / 2

; =============================================================================
; SHP_POSE_PTR — one animation index -> its two pose pointers
; =============================================================================
; In/out: A16/I16, DB=0. `idx` is the DP word holding the index; `ab`/`cd` are
; the set's claim bases and `abp`/`cdp` the long addresses of the index table
; slots the pointers go into.
;
; SHP_POSE_BYTES is 448, which is not a shift, so the multiply is the
; decomposition 448*m = (m<<9) - (m<<6) — nine shifts and a subtract, no
; hardware multiply and no table.
;
; WIDTH-RISK: A16/I16 on entry AND exit, and the body contains NO sep/rep, so
; the expansion cannot leak a width into the caller on either axis.
.macro SHP_POSE_PTR idx, ab, cd, abp, cdp
    lda z:idx
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                           ; m << 6
    sta z:SHP_TMP
    asl a
    asl a
    asl a                           ; m << 9
    sec
    sbc z:SHP_TMP                   ; (m<<9) - (m<<6) = m * 448
    sta z:SHP_TMP
    clc
    adc #ab
    sta f:abp
    lda z:SHP_TMP
    clc
    adc #cd
    sta f:cdp
.endmacro

; --- cam_ptrs: the two animation indices -> the two live pose pointers ------
; In/out: A16/I16, DB=0. Clobbers A.
;
; THE WHOLE PER-FRAME JOB. Band 1's pointer follows camera A's heading through
; the 64-pose rotation set; band 2's follows camera B's zoom through the 8-pose
; set. Nothing else changes frame to frame: a boot-time solve plus a per-frame
; band-2 splice buys exactly what two pointer stores buy here.
cam_ptrs:
    .a16
    .i16
    SHP_POSE_PTR SHP_HEAD, SHP_A_AB_BASE, SHP_A_CD_BASE, SHP_AB1_PTR_LONG, SHP_CD1_PTR_LONG
    SHP_POSE_PTR SHP_ZOOM, SHP_B_AB_BASE, SHP_B_CD_BASE, SHP_AB2_PTR_LONG, SHP_CD2_PTR_LONG
    rts

; --- cam_origins: the two world positions -> the origin tables --------------
; In/out: A16/I16, DB=0. Clobbers A. Called ONCE, from cam_arm.
;
; THE WHOLE PER-BAND ORIGIN SOLVE, and it is subtraction:
;
;  band N: M7X = posNx M7Y = posNy
;  HOFS = posNx - 128 VOFS = posNy - <band's BOTTOM scanline>
;
; M7X/M7Y is where the camera is in the world; HOFS/VOFS is where the screen's
; origin sits relative to it, so subtracting the band's bottom line is what
; pins each band's viewpoint to its own last scanline rather than to the
; frame's. Band 1's bottom is the seam (112), band 2's is the picture's (224).
;
; NO TRIGONOMETRY, EVEN WITH ROTATION — and that is why camera A's heading is
; free. The subtraction zeroes the matrix term at the band's bottom-centre, so
; the pose rotates ABOUT that point by construction and the heading needs no
; origin math at all. The same holds for camera B's zoom: a scale about a fixed
; point is still a scale about that point.
;
; STAMPED ONCE, unlike `sh2_cam`'s per-frame version, because these cameras do
; not move. The values are the rail's per-band position ORACLE.
cam_origins:
    .a16
    .i16
    lda #SHP_POS_AX
    sta f:SHP_OTBL_XY_LONG + 1      ; M7X, band 1
    sec
    sbc #SHP_HALF_W
    sta f:SHP_OTBL_HV_LONG + 1      ; HOFS = posAx - 128
    lda #SHP_POS_AY
    sta f:SHP_OTBL_XY_LONG + 3      ; M7Y, band 1
    sec
    sbc #SHP_SEAM
    sta f:SHP_OTBL_HV_LONG + 3      ; VOFS = posAy - 112 (band 1's bottom line)
    lda #SHP_POS_BX
    sta f:SHP_OTBL_XY_LONG + 6      ; M7X, band 2
    sec
    sbc #SHP_HALF_W
    sta f:SHP_OTBL_HV_LONG + 6
    lda #SHP_POS_BY
    sta f:SHP_OTBL_XY_LONG + 8      ; M7Y, band 2
    sec
    sbc #SHP_LINES
    sta f:SHP_OTBL_HV_LONG + 8      ; VOFS = posBy - 224 (band 2's bottom line)
    rts

; --- cam_arm: build all six tables + the channel shadow (scene enter) -------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X. The caller
; ORs the six enable bits into the scene_mgr HDMAEN shadow after.
cam_arm:
    .a16
    .i16
    ; ---- the declared init contract: zero the WHOLE claim first ------------
    ; The bytes past each table's terminator are never stamped, but the DMA
    ; controller's terminator processing still fetches indirect-address bytes
    ; after the $00 — real hardware reads them, so they must not be power-on
    ; garbage (uninit-read contract; sh2_cam's and mode7_persp's arms open the
    ; same way for the same reason). The loop follows the claim's own size
    ; rather than a copied constant.
    lda #0
    ldx #(ES_SHP_TBL_SIZE - 2)
:   sta f:ES_SHP_TBL_LONG, x
    dex
    dex
    bpl :-

    ; ---- index-table skeletons: counts + terminators -----------------------
    ; 128 is the HDMA repeat flag; the low 7 bits are the line count. So
    ; 128|112 = "a new 4-byte unit every scanline, 112 times" — which is what
    ; makes a band a per-scanline TRAPEZOID instead of one constant matrix.
    sep #$20
    .a8
    lda #(128 | SHP_SEAM)
    sta f:SHP_IDX_AB1_LONG + 0      ; band 1: lines 0..111, then it ENDS
    sta f:SHP_IDX_CD1_LONG + 0
    sta f:SHP_IDX_AB2_LONG + 3      ; band 2: lines 112..223, after the skip
    sta f:SHP_IDX_CD2_LONG + 3
    lda #SHP_SEAM                   ; band 2's SKIP prefix: NON-repeat, so it
    sta f:SHP_IDX_AB2_LONG + 0      ; fires ONE unit at line 0 and then holds
    sta f:SHP_IDX_CD2_LONG + 0      ; silently for 111 lines
    lda #0
    sta f:SHP_IDX_AB1_LONG + 3      ; terminators
    sta f:SHP_IDX_CD1_LONG + 3
    sta f:SHP_IDX_AB2_LONG + 6
    sta f:SHP_IDX_CD2_LONG + 6

    ; ---- origin-table skeletons -------------------------------------------
    ; NON-repeat counts, which is the opposite reading of the same byte: 112
    ; means "transfer the 4-byte unit once, then idle 111 lines", and 1 means
    ; "transfer once" — after which the terminator ends the channel and the
    ; write-twice latch simply holds band 2's origin to the bottom of the
    ; frame.
    lda #SHP_SEAM
    sta f:SHP_OTBL_XY_LONG + 0
    sta f:SHP_OTBL_HV_LONG + 0
    lda #1
    sta f:SHP_OTBL_XY_LONG + 5
    sta f:SHP_OTBL_HV_LONG + 5
    lda #0
    sta f:SHP_OTBL_XY_LONG + 10
    sta f:SHP_OTBL_HV_LONG + 10

    ; ---- band 2's SKIP pointers: static, never rewritten -------------------
    ; Any valid address in the channel's OWN data bank would do — the unit is
    ; masked at line 0 by band 1's higher-priority write — so this aims at
    ; camera B's set base. If the priority contract ever broke, PPU line 0
    ; would visibly render camera B's zoom-0 matrix in band 1's first scanline.
    ; That inversion is a BUILD REFUSAL rather than a plant — see the
    ; .assert above and tools/plants/split_h_persp_demo.py's header.
    rep #$20
    .a16
    lda #SHP_B_AB_BASE
    sta f:SHP_IDX_AB2_LONG + 1
    lda #SHP_B_CD_BASE
    sta f:SHP_IDX_CD2_LONG + 1

    jsr cam_ptrs                    ; the two live pose pointers, from the indices
    jsr cam_origins                 ; the per-band world positions, once

    ; ---- channel shadow: the two matrix pairs (INDIRECT) ------------------
    ; An indirect channel needs DASB ($43x7) as well: the bank the per-line
    ; pose bytes are fetched from. A1B is the INDEX table's bank ($7E); DASB is
    ; the POSE blob's. Getting those two the wrong way round is the classic
    ; indirect-HDMA bug and is why both come from emitted symbols.
    ;
    ; DASB IS STATIC HERE, and that is the 64-heading set paying off: each pose
    ; set fits one LoROM window, so a band's data bank never changes and these
    ; four bytes are written once instead of every VBlank.
    ;
    ; WHICH TABLE GOES TO WHICH CHANNEL IS THE PRIORITY CONTRACT, carried by
    ; the SHP_CH_* indirection above so a band's table and its DASB bank can
    ; never end up on different channels.
    sep #$20
    .a8
    ldx #(SHP_CH_AB1 * SHP_SHDW_CH_SIZE)
    lda #ES_H_SHPAB1_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: indirect, 2-regs-write-twice
    lda #ES_H_SHPAB1_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7A
    lda #ES_SHP_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the index table's bank ($7E)
    lda #ES_R_SHP_POSEA_AB_BANK
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB: camera A's AB set
    rep #$20
    .a16
    lda #SHP_IDX_AB1
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: band 1's AB index table

    sep #$20
    .a8
    ldx #(SHP_CH_CD1 * SHP_SHDW_CH_SIZE)
    lda #ES_H_SHPCD1_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHPCD1_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7C
    lda #ES_SHP_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    lda #ES_R_SHP_POSEA_CD_BANK
    sta f:ES_SM_HDMA_LONG+7, x
    rep #$20
    .a16
    lda #SHP_IDX_CD1
    sta f:ES_SM_HDMA_LONG+2, x

    sep #$20
    .a8
    ldx #(SHP_CH_AB2 * SHP_SHDW_CH_SIZE)
    lda #ES_H_SHPAB2_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHPAB2_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #ES_SHP_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    lda #ES_R_SHP_POSEB_AB_BANK
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB: camera B's ZOOM set — the whole
    rep #$20                        ;       reason the two bands differ
    .a16
    lda #SHP_IDX_AB2
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: band 2's AB index table

    sep #$20
    .a8
    ldx #(SHP_CH_CD2 * SHP_SHDW_CH_SIZE)
    lda #ES_H_SHPCD2_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHPCD2_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #ES_SHP_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    lda #ES_R_SHP_POSEB_CD_BANK
    sta f:ES_SM_HDMA_LONG+7, x
    rep #$20
    .a16
    lda #SHP_IDX_CD2
    sta f:ES_SM_HDMA_LONG+2, x

    ; ---- channel shadow: the origin pair (DIRECT) -------------------------
    ; No DASB: a direct channel's table IS its data, so A1B/A1T alone locate
    ; every byte the channel will ever read.
    sep #$20
    .a8
    ldx #(ES_H_SHPXY_CH * SHP_SHDW_CH_SIZE)
    lda #ES_H_SHPXY_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: direct, 2-regs-write-twice
    lda #ES_H_SHPXY_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7X
    lda #ES_SHP_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SHP_OTBL_XY
    sta f:ES_SM_HDMA_LONG+2, x

    sep #$20
    .a8
    ldx #(ES_H_SHPHV_CH * SHP_SHDW_CH_SIZE)
    lda #ES_H_SHPHV_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SHPHV_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7HOFS
    lda #ES_SHP_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SHP_OTBL_HV
    sta f:ES_SM_HDMA_LONG+2, x
    rts

; --- the pad, and which bit of a JOY word is which --------------------------
; $4218 delivers one 16-bit word: B Y Select Start Up Down Left Right in the
; HIGH byte, A X L R in the low. Written as SHIFTS rather than as $0200 and
; friends because `no_literals` cannot tell a bare $0200 from a hand-narrated
; WRAM address — it collides with a real claim — and the shift form says which
; bit position is meant, which the hex does not.
SHP_JOY_RIGHT = 1 << 8
SHP_JOY_LEFT  = 1 << 9
SHP_JOY_DOWN  = 1 << 10
SHP_JOY_UP    = 1 << 11

; --- cam_input: one pad, two axes, one per BAND -----------------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; Left/Right steps camera A's heading one pose per frame HELD and WRAPS (a
; heading is cyclic). Up/Down steps camera B's zoom and CLAMPS at both ends (a
; zoom is a segment, and its ends are the rail's two controls).
;
; THE SPLIT ACROSS AXES IS THE TEST SURFACE, not a control preference. Driving
; Right must move band 1 and leave band 2's pixels untouched in the same frame,
; and Up/Down the mirror — which is what "two cameras animating independently"
; means when it is asserted rather than watched. Animate both from free-running
; counters and the only available test is a sample.
;
; THE DOWN CLAMP IS A CONTROL. Zoom 0 is camera A's own heading-0 pose exactly
; (tools/gen_split_h_persp_assets.py asserts it at emit time), so holding Down
; collapses band 2's matrix onto band 1's INSIDE the shipping binary, with no
; separate seam-defeating build needed. It is deliberately PARTIAL: the two
; world positions are untouched by the zoom axis, so the per-band POSITION
; claim survives the collapse and the two claims fail independently.
;
; Right AND Left together is a deliberate no-op (+1 then -1); so is Up AND
; Down. The hardware can report both on a worn pad, and cancelling is the
; honest answer.
;
; WIDTH-RISK: A16/I16 on entry AND exit; the body contains NO sep/rep, so it
; cannot leak a width into the caller on either axis. Every local label below
; is reached A16 by fall-through AND by branch.
cam_input:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #SHP_JOY_RIGHT
    beq @noright
    lda z:SHP_HEAD
    inc a
    and #SHP_HEAD_MASK
    sta z:SHP_HEAD
@noright:
    .a16
    lda z:ES_INP_CUR
    bit #SHP_JOY_LEFT
    beq @noleft
    lda z:SHP_HEAD
    dec a
    and #SHP_HEAD_MASK              ; -1 wraps to 63 under the mask
    sta z:SHP_HEAD
@noleft:
    .a16
    lda z:ES_INP_CUR
    bit #SHP_JOY_UP
    beq @noup
    lda z:SHP_ZOOM
    cmp #SHP_ZOOM_MAX
    bcs @noup                       ; already at the steep end: hold, do not wrap
    inc a
    sta z:SHP_ZOOM
@noup:
    .a16
    lda z:ES_INP_CUR
    bit #SHP_JOY_DOWN
    beq @nodown
    lda z:SHP_ZOOM
    beq @nodown                     ; already collapsed onto camera A: hold
    dec a
    sta z:SHP_ZOOM
@nodown:
    .a16
    rts

; --- cam_tick: re-point both bands, once per VBlank -------------------------
; In/out: A8/I16, DB=0 — the sm_nmi_hook contract. Clobbers A.
;
; WIDTH-RISK: this is a CROSS-FILE contract. It is entered A8 (the NMI hook's
; width), widens for its own 16-bit arithmetic, and MUST restore A8 before
; returning — the hook's next instruction is assembled A8. Width-check cannot
; see across the file boundary in either direction, so this marker carries it.
;
; IN VBLANK, and that is not incidental: the HDMA init fetch for the next frame
; reads these tables at line 0, so a half-written pointer here would be a torn
; frame. The NMI hook is the window where that cannot happen.
;
; BOTH POINTERS EVERY FRAME, deliberately the worst case — it is the cost the
; rail should be judged on, not a best case reached by caching an unchanged
; index.
cam_tick:
    .a8
    .i16
    rep #$20
    .a16
    jsr cam_ptrs
    sep #$20
    .a8
    rts
