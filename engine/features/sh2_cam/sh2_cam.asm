; =============================================================================
; sh2_cam.asm — two ROTATING Mode 7 cameras over one plane, on six HDMA
; channels
; =============================================================================
; THE WHOLE MECHANISM, in one place. Six active channels, 224 lines, seam 112.
; Each band streams its OWN HEADING, which is what turns two positioned
; cameras into two independently ROTATING ones — so a single shared matrix
; pair becomes one pair PER BAND:
;
;  ch ES_H_SH2AB1_CH DMAP $43 (mode 3 + INDIRECT) -> M7A/M7B band 1
;  ch ES_H_SH2CD1_CH DMAP $43 -> M7C/M7D band 1
;  index table, 4 B: [128|112, ptr][0]
;  `128|112` is REPEAT: a NEW 4-byte pose unit EVERY scanline for 112
;  lines. The count-0 terminator at line 112 ENDS the channel for the
;  frame, so band 1's pair is silent through band 2's half.
;
;  ch ES_H_SH2AB2_CH DMAP $43 -> M7A/M7B band 2
;  ch ES_H_SH2CD2_CH DMAP $43 -> M7C/M7D band 2
;  index table, 7 B: [112, skip_ptr][128|112, ptr][0]
;  The FIRST entry is NON-repeat: it transfers its 4-byte unit ONCE at
;  line 0 and then holds silently for 111 lines, which is how band 2's
;  real entry arrives at line 112. That single stray unit at line 0 is
;  masked by CHANNEL PRIORITY — see THE STRAY UNIT below.
;
;  ch ES_H_SH2XY_CH DMAP $03 (mode 3, DIRECT) -> M7X/M7Y
;  ch ES_H_SH2HV_CH DMAP $03 -> M7HOFS/M7VOFS
;  origin table, 11 B: [112, X,Y][1, X,Y][0]
;  NON-repeat counts: transfer the 4-byte unit ONCE, then hold. Band 1's
;  origin lands at line 0 and holds through 111; band 2's lands at 112 and
;  holds to the bottom. Position and rotation are separable: the origin split
;  is a POSITION statement, and a heading is a change of MATRIX.
;
; THE STRAY UNIT, and why it is invisible. HDMA services CH0->CH7 within each
; HBlank, and every DMAP-$43 unit delivers complete low+high pairs to both of
; its registers, so the LAST channel to write M7A-M7D in an HBlank wins
; COHERENTLY (not a torn mixture). Band 2's pair is pinned to LOWER channel
; numbers than band 1's, so at line 0 the skip entry's unit lands first and
; band 1's proper pose overwrites it in the same HBlank. The pin is DECLARED in
; feature.toml (`channel = 0..3`); allocating band 2's pair first achieves the
; same thing invisibly. `-D SH2_BADORDER` inverts the
; binding so the stray unit wins at exactly line 0 — the non-vacuity control
; for this whole argument, and without it "line 0 looks fine" is not evidence.
;
; Mode 3 is write-two-registers-twice: 4 bytes per unit, which is exactly [lo,
; hi] for each of two write-twice 13-bit registers. Every DMAP, BBAD and
; channel number above comes from the allocator's emitted symbols — the
; encoding is derived from the declaration in feature.toml and appears nowhere
; else.
;
; THE PER-FRAME WORK, all of it in the VBlank window (sh2_tick):
;  rotate two increments and two masks (headings step +1 / -1)
;  drive four 8.8 fractional-accumulator steps off the move LUT
;  ptrs two pose-pointer multiplies -> four table slots
;  banks four DASB bytes into the scene_mgr channel shadow
;  stamp eight origin-table stores
; A LIST, not a measured cycle figure: nothing here has been measured on the
; emulator. `make measure`'s label-twin + breakpoint discipline is what a
; budget claim would need, and the first rail whose headroom rule depends on
; the number is the one that owes it.

; --- the world --------------------------------------------------------------
; DERIVED from the map claim's own size rather than narrated: the Mode 7 blob
; is 2 bytes per tile (tilemap even, CHR odd) over a square plane, so its size
; fixes the side. `no_literals` refuses a bare 1024 (it lands inside an emitted
; WRAM claim and cannot be told apart from a hand-narrated address), and that
; refusal does real work here — writing the derivation is what makes the wrap
; follow the map instead of agreeing with it by coincidence.
SH2_MAP_T    = 128                        ; world side, in tiles
SH2_TILE_PX  = 8
.assert 2 * SH2_MAP_T * SH2_MAP_T = ES_R_SH2_MAP_SIZE, error, "sh2_cam world size disagrees with the sh2_map claim"
SH2_WORLD_PX = SH2_MAP_T * SH2_TILE_PX    ; 1024 — the plane's period
SH2_WRAP     = SH2_WORLD_PX - 1           ; the mask M7SEL's wrap makes exact

; --- the split --------------------------------------------------------------
SH2_LINES    = 224                        ; the active picture
SH2_SEAM     = SH2_LINES / 2              ; 112: band 1 is 0..111, band 2 112..223
SH2_HALF_W   = 128                        ; half the 256-px screen: the pivot's x

; --- the pose set -----------------------------------------------------------
; One band-local pose is SH2_SEAM scanlines x 4 bytes; the set is 256 headings
; cut into bank slices of 64. Pose h lives at
;
;  loword = <slice base> + (h & 63) * SH2_POSE_BYTES
;  bank = <slice 0's bank> + (h >> 6)
;
; and BOTH halves of that are asserted against the emitted claims below rather
; than trusted: the loword arithmetic needs every slice to start at its
; window's origin, and the bank arithmetic needs the slices in consecutive
; windows in order. If the allocator ever packs them differently the build
; stops here instead of streaming a neighbouring heading's bytes.
SH2_POSE_BYTES  = SH2_SEAM * 4            ; 448 B per band-local pose
SH2_POSES       = 1 << 8                  ; headings in the set
; The move LUT is a REGION PAIR inside one claim: two arms of identical shape,
; the NTSC one at offset 0 and the PAL one a stride on. The stride is DERIVED
; from the claim rather than restated, so growing or shrinking the pair is one
; edit in sh2_rom's feature.toml and both halves follow.
SH2_MOVE_ARMS      = 2
SH2_MOVE_ARM_BYTES = ES_R_SH2_MOVE256_SIZE / SH2_MOVE_ARMS
SH2_MOVE_ARM_NTSC  = 0
SH2_MOVE_ARM_PAL   = SH2_MOVE_ARM_BYTES
SH2_HEAD_MASK   = SH2_POSES - 1
SH2_SLICE_LOG2  = 6                       ; 64 poses per bank slice
SH2_SLICE_POSES = 1 << SH2_SLICE_LOG2
SH2_SLICE_MASK  = SH2_SLICE_POSES - 1

.assert SH2_SLICE_POSES * SH2_POSE_BYTES = ES_R_SH2_POSE256_AB_S0_SIZE, error, "sh2_cam slice model disagrees with the sh2_pose256_ab_s0 claim"
.assert SH2_SLICE_POSES * SH2_POSE_BYTES = ES_R_SH2_POSE256_CD_S0_SIZE, error, "sh2_cam slice model disagrees with the sh2_pose256_cd_s0 claim"
.assert SH2_POSES * 4 = SH2_MOVE_ARM_BYTES, error, "sh2_cam heading count disagrees with one arm of the sh2_move256 claim"
; The arm is selected by ORing US_MOVE_ARM into the `h * 4` index, which is only
; the same thing as adding it while the index cannot reach the arm's own bit —
; i.e. while one arm is exactly a power of two bytes and the index spans it.
; Both are asserted, so the cheap fold cannot quietly stop being correct.
.assert (SH2_MOVE_ARM_BYTES & (SH2_MOVE_ARM_BYTES - 1)) = 0, error, "sh2_cam: one move arm is not a power of two bytes — the index OR would carry"
; every slice at its window's origin -> ONE loword serves all four
.assert ES_R_SH2_POSE256_AB_S1_ADDR = ES_R_SH2_POSE256_AB_S0_ADDR, error, "sh2_pose256_ab slices are not window-aligned alike"
.assert ES_R_SH2_POSE256_AB_S2_ADDR = ES_R_SH2_POSE256_AB_S0_ADDR, error, "sh2_pose256_ab slices are not window-aligned alike"
.assert ES_R_SH2_POSE256_AB_S3_ADDR = ES_R_SH2_POSE256_AB_S0_ADDR, error, "sh2_pose256_ab slices are not window-aligned alike"
.assert ES_R_SH2_POSE256_CD_S1_ADDR = ES_R_SH2_POSE256_CD_S0_ADDR, error, "sh2_pose256_cd slices are not window-aligned alike"
.assert ES_R_SH2_POSE256_CD_S2_ADDR = ES_R_SH2_POSE256_CD_S0_ADDR, error, "sh2_pose256_cd slices are not window-aligned alike"
.assert ES_R_SH2_POSE256_CD_S3_ADDR = ES_R_SH2_POSE256_CD_S0_ADDR, error, "sh2_pose256_cd slices are not window-aligned alike"
; ...and consecutive banks in order -> `bank = base + (h >> 6)`
.assert ES_R_SH2_POSE256_AB_S1_BANK = ES_R_SH2_POSE256_AB_S0_BANK + 1, error, "sh2_pose256_ab slices are not in consecutive banks"
.assert ES_R_SH2_POSE256_AB_S2_BANK = ES_R_SH2_POSE256_AB_S0_BANK + 2, error, "sh2_pose256_ab slices are not in consecutive banks"
.assert ES_R_SH2_POSE256_AB_S3_BANK = ES_R_SH2_POSE256_AB_S0_BANK + 3, error, "sh2_pose256_ab slices are not in consecutive banks"
.assert ES_R_SH2_POSE256_CD_S1_BANK = ES_R_SH2_POSE256_CD_S0_BANK + 1, error, "sh2_pose256_cd slices are not in consecutive banks"
.assert ES_R_SH2_POSE256_CD_S2_BANK = ES_R_SH2_POSE256_CD_S0_BANK + 2, error, "sh2_pose256_cd slices are not in consecutive banks"
.assert ES_R_SH2_POSE256_CD_S3_BANK = ES_R_SH2_POSE256_CD_S0_BANK + 3, error, "sh2_pose256_cd slices are not in consecutive banks"

SH2_POSE_AB_BASE = ES_R_SH2_POSE256_AB_S0_ADDR
SH2_POSE_CD_BASE = ES_R_SH2_POSE256_CD_S0_ADDR
SH2_MOVE_LONG    = (ES_R_SH2_MOVE256_BANK << 16) | ES_R_SH2_MOVE256_ADDR

; --- the HDMA tables, inside the one 96-byte wram claim ---------------------
; 16 B apart so the offsets read as a table rather than as arithmetic. Band 1's
; index tables are 4 B, band 2's 7 B (the skip prefix), the origin tables 11 B;
; the slack is what the power-on zero in sh2_arm covers.
SH2_IDX_AB1      = ES_SH2_TBL + 0
SH2_IDX_CD1      = ES_SH2_TBL + 16
SH2_IDX_AB2      = ES_SH2_TBL + 32
SH2_IDX_CD2      = ES_SH2_TBL + 48
SH2_OTBL_XY      = ES_SH2_TBL + 64
SH2_OTBL_HV      = ES_SH2_TBL + 80
SH2_IDX_AB1_LONG = ES_SH2_TBL_LONG + 0
SH2_IDX_CD1_LONG = ES_SH2_TBL_LONG + 16
SH2_IDX_AB2_LONG = ES_SH2_TBL_LONG + 32
SH2_IDX_CD2_LONG = ES_SH2_TBL_LONG + 48
SH2_OTBL_XY_LONG = ES_SH2_TBL_LONG + 64
SH2_OTBL_HV_LONG = ES_SH2_TBL_LONG + 80

; Band 1's live pose pointer is its table's only one; band 2's is the SECOND
; entry's, because entry 1 is the skip prefix.
SH2_AB1_PTR_LONG = SH2_IDX_AB1_LONG + 1
SH2_CD1_PTR_LONG = SH2_IDX_CD1_LONG + 1
SH2_AB2_PTR_LONG = SH2_IDX_AB2_LONG + 4
SH2_CD2_PTR_LONG = SH2_IDX_CD2_LONG + 4

; --- which channel carries which BAND ---------------------------------------
; ONE indirection, and it is what makes the -D SH2_BADORDER control a PURE
; priority inversion rather than a second change riding along. A band's table
; address and its DASB bank must land on the SAME channel, so both are derived
; from these four symbols; flipping them swaps the two bands' channels
; completely and changes nothing else. The four channels are two matched pairs
; — same DMAP ($43), same BBAD, same band length — so which pair a band sits on
; is exactly and only its HBlank priority.
;
; In the shipping build these are the identity: band 1 on the HIGH pair (it
; must write M7A-M7D last at line 0), band 2 on the LOW pair.
.ifndef SH2_BADORDER
SH2_CH_AB1 = ES_H_SH2AB1_CH
SH2_CH_CD1 = ES_H_SH2CD1_CH
SH2_CH_AB2 = ES_H_SH2AB2_CH
SH2_CH_CD2 = ES_H_SH2CD2_CH
.else
SH2_CH_AB1 = ES_H_SH2AB2_CH
SH2_CH_CD1 = ES_H_SH2CD2_CH
SH2_CH_AB2 = ES_H_SH2AB1_CH
SH2_CH_CD2 = ES_H_SH2CD1_CH
.endif
.assert SH2_CH_AB2 < SH2_CH_AB1 || .defined(SH2_BADORDER), error, "sh2_cam: band 2's AB channel must be BELOW band 1's — the line-0 stray unit would win"
.assert SH2_CH_CD2 < SH2_CH_CD1 || .defined(SH2_BADORDER), error, "sh2_cam: band 2's CD channel must be BELOW band 1's — the line-0 stray unit would win"

; The DASB byte ($43x7) of each matrix channel, in the scene_mgr shadow the NMI
; MVNs to $4300 — written there rather than to the register file directly, so
; the per-frame stamp rides the same commit path sh2_arm's staging does.
SH2_SHDW_CH_SIZE = ES_SM_HDMA_SIZE / 8    ; 16 B of register file per channel
SH2_DASB_AB1     = ES_SM_HDMA_LONG + SH2_CH_AB1 * SH2_SHDW_CH_SIZE + 7
SH2_DASB_CD1     = ES_SM_HDMA_LONG + SH2_CH_CD1 * SH2_SHDW_CH_SIZE + 7
SH2_DASB_AB2     = ES_SM_HDMA_LONG + SH2_CH_AB2 * SH2_SHDW_CH_SIZE + 7
SH2_DASB_CD2     = ES_SM_HDMA_LONG + SH2_CH_CD2 * SH2_SHDW_CH_SIZE + 7

; --- the two cameras' positions, inside the 8-byte dp claim -----------------
SH2_POS1X = ES_SH2_POS + 0
SH2_POS1Y = ES_SH2_POS + 2
SH2_POS2X = ES_SH2_POS + 4
SH2_POS2Y = ES_SH2_POS + 6

; --- rotation + drive state, inside the 14-byte dp claim --------------------
SH2_H1     = ES_SH2_ROT + 0               ; heading index 0..255, camera 1
SH2_H2     = ES_SH2_ROT + 2               ; ...camera 2
SH2_F1X    = ES_SH2_ROT + 4               ; per-axis 8.8 fraction accumulators
SH2_F1Y    = ES_SH2_ROT + 6
SH2_F2X    = ES_SH2_ROT + 8
SH2_F2Y    = ES_SH2_ROT + 10
SH2_PTRTMP = ES_SH2_ROT + 12              ; pose-pointer multiply scratch

; --- the camera starting headings -------------------------------------------
; Camera 2 boots half a turn from camera 1, so the two floors face opposite
; ways from the first frame and the opposite-sense rotation is visible
; immediately rather than after the headings drift apart.
SH2_H1_0 = 0
SH2_H2_0 = SH2_POSES / 2

; --- the heading rate, and why it is the one thing the LUT pair cannot carry -
; The TRANSLATION is a table: two arms of `sh2_move256`, one per region, and
; picking an arm is the whole compensation. The ROTATION is a step in that
; table's own INDEX — one pose each frame a direction is held, and the same +1
; the autonomous build applies — so no table can hold it and there is nothing
; to bake. Left alone the camera would fly at real-time parity around a circle
; 1.2 times too wide, because its speed scaled and its turn did not.
;
; So it goes through tick_scale, which is what that feature is for: TS_STEP
; publishes 1 on NTSC (today's constant, exactly, with the fraction stuck at 0)
; and 1 or 2 on PAL in the pattern averaging 1.2018. ONE expansion per frame in
; sh2_advance, read by both cameras and by every follower — all three are the
; same base rate, which is the condition the doctrine puts on sharing a pair.
;
; TICK: ok — this block is the region compensator's derivation for this rail,
;   and naming the NTSC frame beside the PAL one is the subject of the comment
;   rather than a coupling in it, exactly as in tick_scale.asm.
SH2_HEAD_BASE = TS_ONE                    ; one pose per NTSC frame held

; =============================================================================
; SH2_DRIVE_AXIS — one axis of one camera's forward step.
; =============================================================================
; In: X = heading * 4, ORed with US_MOVE_ARM (the move LUT's byte index for this
; camera, inside this console's region arm). `voff` is 0 for the x component
; and 2 for the y one; `frac` and `pos` are the DP words this axis owns.
;
; THE ACCUMULATOR IS THE POINT. `move256[h]` is a velocity in 8.8 with a
; CONSTANT magnitude at every heading — 2.0 px per NTSC frame, 2.40361 per PAL
; one, which is the same distance per real second. Adding it to a 16-bit
; fraction word makes the high byte, after the add, the frame's SIGNED integer
; delta (the two's-complement decomposition value = high + frac/256): that
; moves the position, and the low byte is kept as the carry into next frame.
; Rounding the velocity to an integer instead gives a speed that pulses with
; heading and a direction that walks a staircase — the translation jerk this
; shape exists to remove.
;
; WIDTH-RISK: A16/I16 on entry AND exit, and the body contains NO sep/rep — so
; it cannot leak a width into the caller on either axis. It relies on I16 for
; the long-indexed LUT read.
.macro SH2_DRIVE_AXIS voff, frac, pos
    lda f:SH2_MOVE_LONG + voff, x
    clc
    adc z:frac
    sta z:frac                  ; keep the full 16-bit accumulator...
    xba                         ; ...then read its HIGH byte as the delta
    and #$00FF
    cmp #$0080
    bcc :+
    ora #$FF00                  ; sign-extend the s8 delta to s16
:
    clc
    adc z:pos
    and #SH2_WRAP               ; the world's own period (s16 delta wraps exactly)
    sta z:pos
    lda z:frac
    and #$00FF                  ; drop the consumed integer part, keep the fraction
    sta z:frac
.endmacro

; --- sh2_arm: build all six tables + the channel shadow (scene enter) -------
; CONTRACT sh2_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_SH2_POS and ES_SH2_ROT — the caller seeds both before
;             calling, and sh2_arm stamps from both
;   out:      all six HDMA tables built over a zeroed claim, the positions
;             seeded, all six channel shadows staged
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — it writes the whole table
;             claim and the channel shadow, neither of which may be read
;             mid-write. The caller ORs the six enable bits into the
;             scene_mgr HDMAEN shadow AFTERWARDS; this routine does not
;   tail:     rts
sh2_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sh2_arm"
    ; ---- the declared init contract: zero the WHOLE claim first ------------
    ; The bytes past each table's terminator are never stamped, but the DMA
    ; controller's terminator processing still fetches indirect-address bytes
    ; after the $00 — real hardware reads them, so they must not be power-on
    ; garbage (uninit-read contract; mode7_persp's persp_arm opens the same way
    ; for the same reason). The loop follows the claim's OWN emitted size
    ; rather than a copied constant, so widening the claim needs no edit
    ; here.
    lda #0
    ldx #(ES_SH2_TBL_SIZE - 2)
:   sta f:ES_SH2_TBL_LONG, x
    dex
    dex
    bpl :-

    ; ---- index-table skeletons: counts + terminators -----------------------
    ; 128 is the HDMA repeat flag; the low 7 bits are the line count. So
    ; 128|112 = "a new 4-byte unit every scanline, 112 times".
    sep #$20
    .a8
    lda #(128 | SH2_SEAM)
    sta f:SH2_IDX_AB1_LONG + 0      ; band 1: lines 0..111, then it ENDS
    sta f:SH2_IDX_CD1_LONG + 0
    sta f:SH2_IDX_AB2_LONG + 3      ; band 2: lines 112..223, after the skip
    sta f:SH2_IDX_CD2_LONG + 3
    lda #SH2_SEAM                   ; band 2's SKIP prefix: NON-repeat, so it
    sta f:SH2_IDX_AB2_LONG + 0      ; fires ONE unit at line 0 and then holds
    sta f:SH2_IDX_CD2_LONG + 0      ; silently for 111 lines
    lda #0
    sta f:SH2_IDX_AB1_LONG + 3      ; terminators
    sta f:SH2_IDX_CD1_LONG + 3
    sta f:SH2_IDX_AB2_LONG + 6
    sta f:SH2_IDX_CD2_LONG + 6

    ; ---- origin-table skeletons -------------------------------------------
    ; NON-repeat counts, which is the opposite reading of the same byte: 112
    ; means "transfer the unit once, then idle 111 lines", and 1 means
    ; "transfer once" — after which the terminator ends the channel and the
    ; write-twice latch simply holds band 2's value to the bottom of the frame.
    lda #SH2_SEAM
    sta f:SH2_OTBL_XY_LONG + 0
    sta f:SH2_OTBL_HV_LONG + 0
    lda #1
    sta f:SH2_OTBL_XY_LONG + 5
    sta f:SH2_OTBL_HV_LONG + 5
    lda #0
    sta f:SH2_OTBL_XY_LONG + 10
    sta f:SH2_OTBL_HV_LONG + 10

    ; ---- band 2's SKIP pointers: static, never rewritten -------------------
    ; Any valid address in the channel's own data bank would do — the unit is
    ; masked at line 0 — so this aims at the slice BASE. Note what that means
    ; at runtime: band 2's DASB tracks ITS heading's slice, so the bytes this
    ; pointer fetches are heading `64*(h2>>6)`'s first line, which is a
    ; DIFFERENT matrix from band 1's in general. That is deliberate: if the
    ; priority mask ever broke, PPU line 0 would visibly render the wrong
    ; matrix, and -D SH2_BADORDER proves that failure is detectable.
    rep #$20
    .a16
    lda #SH2_POSE_AB_BASE
    sta f:SH2_IDX_AB2_LONG + 1
    lda #SH2_POSE_CD_BASE
    sta f:SH2_IDX_CD2_LONG + 1

    jsr cam_ptrs                    ; the four live pose pointers, from H1/H2
    jsr cam_stamp                   ; the origin values, from the seeded pos

    ; ---- channel shadow: the two matrix pairs (INDIRECT) ------------------
    ; An indirect channel needs DASB ($43x7) as well: the bank the per-line
    ; pose bytes are fetched from. A1B is the INDEX table's bank ($7E); DASB is
    ; the POSE blob's. Getting those two the wrong way round is the classic
    ; indirect-HDMA bug and is why both come from emitted symbols. DASB itself
    ; is left to cam_banks, which derives all four from the live headings.
    ;
    ; WHICH TABLE GOES TO WHICH CHANNEL IS THE PRIORITY CONTRACT, and it is
    ; carried by the SH2_CH_* indirection above so a band's table and its DASB
    ; bank can never end up on different channels.
    sep #$20
    .a8
    rep #$10
    .i16
    ldx #(SH2_CH_AB1 * SH2_SHDW_CH_SIZE)
    lda #ES_H_SH2AB1_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: indirect, 2-regs-write-twice
    lda #ES_H_SH2AB1_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7A
    lda #ES_SH2_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the index table's bank ($7E)
    rep #$20
    .a16
    lda #SH2_IDX_AB1
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: band 1's AB index table

    sep #$20
    .a8
    ldx #(SH2_CH_CD1 * SH2_SHDW_CH_SIZE)
    lda #ES_H_SH2CD1_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SH2CD1_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7C
    lda #ES_SH2_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SH2_IDX_CD1
    sta f:ES_SM_HDMA_LONG+2, x

    sep #$20
    .a8
    ldx #(SH2_CH_AB2 * SH2_SHDW_CH_SIZE)
    lda #ES_H_SH2AB2_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SH2AB2_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #ES_SH2_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SH2_IDX_AB2
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: band 2's AB index table

    sep #$20
    .a8
    ldx #(SH2_CH_CD2 * SH2_SHDW_CH_SIZE)
    lda #ES_H_SH2CD2_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SH2CD2_BBAD
    sta f:ES_SM_HDMA_LONG+1, x
    lda #ES_SH2_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SH2_IDX_CD2
    sta f:ES_SM_HDMA_LONG+2, x

    ; ---- channel shadow: the origin pair (DIRECT) -------------------------
    ; No DASB: a direct channel's table IS its data, so A1B/A1T alone locate
    ; every byte the channel will ever read.
    sep #$20
    .a8
    ldx #(ES_H_SH2XY_CH * SH2_SHDW_CH_SIZE)
    lda #ES_H_SH2XY_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: direct, 2-regs-write-twice
    lda #ES_H_SH2XY_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7X
    lda #ES_SH2_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SH2_OTBL_XY
    sta f:ES_SM_HDMA_LONG+2, x
    sep #$20
    .a8
    ldx #(ES_H_SH2HV_CH * SH2_SHDW_CH_SIZE)
    lda #ES_H_SH2HV_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_SH2HV_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7HOFS
    lda #ES_SH2_TBL_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #SH2_OTBL_HV
    sta f:ES_SM_HDMA_LONG+2, x

    jsr cam_banks                   ; the four DASB bytes, from H1/H2
    rts

; --- cam_ptrs: both headings -> the four live pose pointers -----------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; ptr(h) = slice_base + (h & 63) * SH2_POSE_BYTES, and SH2_POSE_BYTES is 448,
; which is not a shift — so the multiply is the decomposition
; 448*m = (m<<9) - (m<<6). The slice INDEX (h >> 6) selects the
; BANK, which is cam_banks' job; every slice sits at the same loword by the
; .asserts above, so one base serves all four.
cam_ptrs:
    .a16
    .i16
    lda z:SH2_H1
    and #SH2_SLICE_MASK             ; the pose's index WITHIN its bank slice
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a                           ; m << 6
    sta z:SH2_PTRTMP
    asl a
    asl a
    asl a                           ; m << 9
    sec
    sbc z:SH2_PTRTMP                ; (m<<9) - (m<<6) = m * 448
    sta z:SH2_PTRTMP
    clc
    adc #SH2_POSE_AB_BASE
    sta f:SH2_AB1_PTR_LONG          ; band 1 AB
    lda z:SH2_PTRTMP
    clc
    adc #SH2_POSE_CD_BASE
    sta f:SH2_CD1_PTR_LONG          ; band 1 CD
    lda z:SH2_H2
    and #SH2_SLICE_MASK
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta z:SH2_PTRTMP
    asl a
    asl a
    asl a
    sec
    sbc z:SH2_PTRTMP
    sta z:SH2_PTRTMP
    clc
    adc #SH2_POSE_AB_BASE
    sta f:SH2_AB2_PTR_LONG          ; band 2 AB
    lda z:SH2_PTRTMP
    clc
    adc #SH2_POSE_CD_BASE
    sta f:SH2_CD2_PTR_LONG          ; band 2 CD
    rts

; --- cam_banks: both headings -> the four DASB bytes ------------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; bank = slice-0's bank + (h >> 6). Written into the scene_mgr channel shadow,
; which sm_nmi_core MVNs to $4300 immediately AFTER sm_nmi_hook runs — so a
; stamp made here lands in the register file the same VBlank, before the next
; frame's HDMA init fetch reads it. Both bands' AB channels index the SAME four
; ROM banks; it is the per-channel DASB value that makes their headings
; independent.
;
; WIDTH-RISK: enters and exits A16; the four single-byte DASB stores each sit
; in a balanced sep/rep window, and the index registers are never narrowed.
cam_banks:
    .a16
    .i16
    lda z:SH2_H1
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                           ; slice index = h1 >> 6 (0..3)
    sta z:SH2_PTRTMP
    clc
    adc #ES_R_SH2_POSE256_AB_S0_BANK
    sep #$20
    .a8
    sta f:SH2_DASB_AB1
    rep #$20
    .a16
    lda z:SH2_PTRTMP
    clc
    adc #ES_R_SH2_POSE256_CD_S0_BANK
    sep #$20
    .a8
    sta f:SH2_DASB_CD1
    rep #$20
    .a16
    lda z:SH2_H2
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a                           ; slice index = h2 >> 6
    sta z:SH2_PTRTMP
    clc
    adc #ES_R_SH2_POSE256_AB_S0_BANK
    sep #$20
    .a8
    sta f:SH2_DASB_AB2
    rep #$20
    .a16
    lda z:SH2_PTRTMP
    clc
    adc #ES_R_SH2_POSE256_CD_S0_BANK
    sep #$20
    .a8
    sta f:SH2_DASB_CD2
    rep #$20
    .a16
    rts

; --- cam_stamp: both bands' world positions -> the origin tables ------------
; In/out: A16/I16, DB=0. Clobbers A. Caller guarantees VBlank or forced blank.
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
; STILL NO TRIGONOMETRY, EVEN WITH ROTATION — and that is not an oversight, it
; is why the rotation is free. The origin subtraction
; zeroes the matrix term at the band's bottom-centre, so the pose rotates ABOUT
; that point by construction and the heading needs no new origin math at all.
cam_stamp:
    .a16
    .i16
    lda z:SH2_POS1X
    sta f:SH2_OTBL_XY_LONG + 1      ; M7X, band 1
    sec
    sbc #SH2_HALF_W
    sta f:SH2_OTBL_HV_LONG + 1      ; HOFS = pos1x - 128
    lda z:SH2_POS1Y
    sta f:SH2_OTBL_XY_LONG + 3      ; M7Y, band 1
    sec
    sbc #SH2_SEAM
    sta f:SH2_OTBL_HV_LONG + 3      ; VOFS = pos1y - 112 (band 1's bottom line)
    lda z:SH2_POS2X
    sta f:SH2_OTBL_XY_LONG + 6      ; M7X, band 2
    sec
    sbc #SH2_HALF_W
    sta f:SH2_OTBL_HV_LONG + 6
    lda z:SH2_POS2Y
    sta f:SH2_OTBL_XY_LONG + 8      ; M7Y, band 2
    sec
    sbc #SH2_LINES
    sta f:SH2_OTBL_HV_LONG + 8      ; VOFS = pos2y - 224 (band 2's bottom line)
    rts

; --- the two pads, and which bit of a JOY word is which ---------------------
; $4218/$421A deliver one 16-bit word each: B Y Select Start Up Down Left Right
; in the HIGH byte, A X L R in the low. Written as SHIFTS rather than as $0200
; and friends because `no_literals` cannot tell a bare $0200 from a hand-
; narrated WRAM address — it collides with a real claim — and the shift form
; says which bit position is meant, which the hex does not.
SH2_JOY_RIGHT = 1 << 8
SH2_JOY_LEFT  = 1 << 9
SH2_JOY_B     = 1 << 15

; =============================================================================
; SH2_CAM_PAD — one pad drives one camera
; =============================================================================
; In: A16/I16, DB=0. `pad` is the input feature's latched JOY word for this
; player; the rest name the camera's own DP state.
;
; D-pad Right/Left steps the heading by US_TSH HELD — the same step the
; autonomous build applies, so the rotation reads at exactly the rate the
; 256-pose set was chosen for, on either console. B drives forward through the
; SAME SH2_DRIVE_AXIS accumulators against the SAME region arm, so a
; player-driven camera and an autonomous one are the same motion under
; different authority rather than two models.
;
; Right AND Left together is a deliberate no-op (+US_TSH then -US_TSH): the
; hardware can report both on a worn pad, and cancelling is the honest answer.
; It cancels exactly because both arms read the ONE word published for the
; frame, rather than each re-deciding a step.
;
; WIDTH-RISK: A16/I16 on entry AND exit, and the body contains NO sep/rep — the
; expansion cannot leak a width into the caller on either axis. It relies on
; I16 for SH2_DRIVE_AXIS's long-indexed LUT read. NAMED `.local` LABELS, NOT
; ANONYMOUS ONES, and this was a live bug rather than a style note:
; SH2_DRIVE_AXIS contains an anonymous label of its own, so a `beq:+` guarding
; the B branch resolved to the label INSIDE the first expanded drive axis —
; skipping the x accumulator's tail and running the y one on a frame the pad
; never asked to move. Ca65 says so only as "No reference to unnamed label" on
; the trailing `:`, which is easy to read as noise.
.macro SH2_CAM_PAD pad, hh, fx, fy, posx, posy
    .local noright, noleft, nob
    lda z:pad
    bit #SH2_JOY_RIGHT
    beq noright
    lda z:hh
    clc
    adc z:US_TSH                    ; this frame's pose step, region-scaled
    and #SH2_HEAD_MASK
    sta z:hh
noright:
    lda z:pad
    bit #SH2_JOY_LEFT
    beq noleft
    lda z:hh
    sec
    sbc z:US_TSH
    and #SH2_HEAD_MASK              ; a negative step wraps under the mask
    sta z:hh
noleft:
    lda z:pad
    bit #SH2_JOY_B
    beq nob
    lda z:hh
    asl a
    asl a
    ora z:US_MOVE_ARM               ; X = h * 4 inside THIS console's move arm
    tax
    SH2_DRIVE_AXIS 0, fx, posx
    SH2_DRIVE_AXIS 2, fy, posy
nob:
.endmacro

; --- cam_input: the two pads, one per camera --------------------------------
; CONTRACT sh2_cam::cam_input
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the two pads read, one per camera
;   clobbers: A, X, N, Z, C, V
;   assumes:  the pads are already latched — input_read and input2_read
;             run at the top of the main loop, not here
;   tail:     rts
;
; THE SHIPPING BUILD'S ADVANCE. Pad control REPLACES the autonomous step
; rather than adding to it: with nothing held the cameras stand still and only
; the swarm moves. `-D SH2_AUTOCAM` restores the autonomous version below, and
; the two are mutually exclusive on purpose — a build where auto and pad both
; applied would make "Right rotates camera 1" indistinguishable from the auto
; step on the camera whose auto sense is +1, which is half the input surface
; untestable.
;
; The pads are LATCHED by `input_read` / `input2_read` at the top of the main
; loop, not read here: those routines wait out the auto-read busy window, and
; doing that once per frame rather than once per camera is the difference.
cam_input:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "cam_input"
    SH2_CAM_PAD ES_INP_CUR,  SH2_H1, SH2_F1X, SH2_F1Y, SH2_POS1X, SH2_POS1Y
    SH2_CAM_PAD ES_INP2_CUR, SH2_H2, SH2_F2X, SH2_F2Y, SH2_POS2X, SH2_POS2Y
    rts

; --- cam_rotate: step both headings, equal and opposite ---------------------
; In/out: A16/I16, DB=0. Clobbers A.
;
; ONE POSE STEP PER FRAME on each camera. 256 headings is 1.40625 degrees per
; pose, which at this turn rate is a step EVERY frame — that is the whole
; reason the set is 256 and not 64: at 64 the demo had to divide the frame rate
; down (cam 1 every 4 frames, cam 2 every 6) and the floor visibly stepped.
;
; EQUAL AND OPPOSITE (+1 / -1), deliberately. Both cameras turning the same way
; would still prove two headings, but not two INDEPENDENT ones — the two floors
; would stay in lockstep forever and "they rotate separately" would be vacuous.
;
; ONE POSE PER FRAME IS THE NTSC ANSWER, and US_TSH is that answer for whichever
; console this is: sh2_advance publishes it once per frame through TS_STEP, so
; the step is 1 on NTSC (bit-identically to the `inc a` this used to be) and 1
; or 2 on PAL. The two cameras stay equal and opposite because they add and
; subtract the SAME published word.
cam_rotate:
    .a16
    .i16
    lda z:SH2_H1
    clc
    adc z:US_TSH
    and #SH2_HEAD_MASK
    sta z:SH2_H1
.ifndef SH2_SAME_HEADING
    lda z:SH2_H2
    sec
    sbc z:US_TSH
    and #SH2_HEAD_MASK              ; a negative step wraps under the mask
.else
    ; THE INDEPENDENT-ROTATION NON-VACUITY CONTROL (-D SH2_SAME_HEADING).
    ; Camera 2's heading is FOLDED onto camera 1's — same start (split.asm
    ; seeds it) and same sense here — so both bands stream the SAME pose every
    ; frame and the "two headings, opposite senses" signal must DIE. Without
    ; it, "the two floors look different" is a claim about two POSITIONS, which
    ; a rail that rotated ONE camera and pointed both bands at it would pass
    ; every rotation assertion in the module.
    ;
    ; Only the HEADING is folded, so the positions still differ and the
    ; per-band position signal survives — the two claims fail separately.
.endif
    sta z:SH2_H2
    rts

; --- cam_drive: both cameras forward along their own heading ----------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; Four axes, in order: camera 1 X, camera 1 Y, camera 2 X, camera 2 Y. The
; heading indexes the move LUT by h*4 (two s16 words per entry), and each axis
; runs its own 8.8 fraction accumulator — see SH2_DRIVE_AXIS.
cam_drive:
    .a16
    .i16
    lda z:SH2_H1
    asl a
    asl a
    ora z:US_MOVE_ARM               ; X = h1 * 4 inside THIS console's arm
    tax
    SH2_DRIVE_AXIS 0, SH2_F1X, SH2_POS1X
    SH2_DRIVE_AXIS 2, SH2_F1Y, SH2_POS1Y
    lda z:SH2_H2
    asl a
    asl a
    ora z:US_MOVE_ARM               ; X = h2 * 4, same arm
    tax
    SH2_DRIVE_AXIS 0, SH2_F2X, SH2_POS2X
    SH2_DRIVE_AXIS 2, SH2_F2Y, SH2_POS2Y
    rts

; --- sh2_tick: rotate, drive and re-stamp, once per VBlank ------------------
; In/out: A8/I16, DB=0 — the sm_nmi_hook contract. Clobbers A, X.
;
; WIDTH-RISK: this is a CROSS-FILE contract. It is entered A8 (the NMI hook's
; width), widens for its own 16-bit arithmetic, and MUST restore A8 before
; returning — the hook's next instruction is assembled A8. Width-check cannot
; see across the file boundary in either direction, so this marker carries it.
;
; EVERYTHING IS RECOMPUTED EVERY FRAME, deliberately the worst case: both
; headings step, both cameras drive, all four pose pointers and all four DASB
; bytes are re-derived, and both origin tables are re-stamped. That is the cost
; the rail should be judged on, not a best case reached by caching.
;
; IN VBLANK, and that is not incidental: the HDMA init fetch for the next frame
; reads these tables at line 0, so a half-written entry here would be a torn
; frame. The NMI hook is the window where that cannot happen — and the DASB
; stamps go into the scene_mgr shadow, which sm_nmi_core copies to $4300 right
; after this returns, so they reach the register file in the same VBlank.
;
; STAMP FIRST, ADVANCE SECOND — and the reason was MEASURED. It is a shared
; snapshot: ONE VBlank commits the OAM shadow AND the pose pointers/banks AND
; the origins from the SAME heading/position values, and the state advances
; only afterwards, so the next frame's projection can run during ACTIVE
; DISPLAY against a state that is already fully committed.
;
; The other order (advance, then stamp) is correct while nothing but the
; camera moves. It stops being correct the moment a CPU-side per-frame job
; depends on the same state: with advance-first, the only place a projection
; can read the frame's state is inside this VBlank — and putting it there
; OVERRUNS. Measured, not reasoned: with the whole 24-marker cast projected
; from the NMI hook, sm_nmi_core's post-hook MVN of the 128-byte channel
; shadow into $4300 lands during ACTIVE DISPLAY and rewrites every channel's
; running HDMA state mid-frame — the picture speckles from the row the MVN
; reaches downward, while VRAM, the index tables and the shadow all read back
; correct. Only a four-marker cast fitted. The work belongs outside VBlank,
; and this order is what lets it go there without the sprites lagging the
; floor by a frame.
;
; The visible consequence is a one-frame PHASE shift, not a behaviour change:
; frame 1 now renders the seeded state rather than one step past it. Nothing
; recovers state from a frame NUMBER (every test in the module reads it out of
; the pixels), but a test that reads the DP state directly must step it back
; once to get the state the parked frame is showing — see _state in
; tests/test_split_h_2p_demo.py.
; CONTRACT sh2_tick
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       SH2_H1/SH2_H2 and the four position words — the state THIS
;             frame's picture is to be stamped from
;   out:      the four live pose pointers, the four DASB bytes, and both
;             bands' origin words, all committed from the same state
;   clobbers: A, N, Z, C. The index registers are untouched, and are never
;             narrowed — the A8 window this runs inside is A-only
;   assumes:  VBlank (the sm_nmi_hook contract). It stamps only; the state
;             step is sh2_advance's, a few hundred cycles later in the tick
;   tail:     rts
;
; THE A8 ENTRY IS THE HOOK'S, NOT A PREFERENCE: sm_nmi_hook runs in A8/I16 and
; this routine widens to A16 for its own work and narrows back before
; returning, so the hook's contract is what the caller sees on both sides.
sh2_tick:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "sh2_tick"
    rep #$20
    .a16
    jsr cam_ptrs
    jsr cam_banks
    jsr cam_stamp
    sep #$20
    .a8
    rts

; --- sh2_advance: the frame's state step, in the scene TICK -----------------
; CONTRACT sh2_advance
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       US_TSH_ACC (the carried rotation fraction) and, on the input
;             build, the latched pads
;   out:      US_TSH published for this frame; both headings and all four
;             position words stepped unless SH2_FREEZE is defined
;   clobbers: A, X, N, Z, C
;   assumes:  the pads are already LATCHED — input_read / input2_read run at
;             the top of the main loop, not here. And it runs FIRST in the
;             tick, before the swarm and the projection, so what those
;             project is this frame's state rather than last frame's
;   tail:     rts
;
; THE STATE STEP IS OUT OF THE VBLANK HOOK, and the phase is unchanged by that.
; Stamping and then advancing inside one VBlank works too; here sh2_tick stamps
; only, and the tick advances a few hundred cycles later — still before
; the next VBlank, so the state each frame is stamped from is exactly the state
; the same frame's OAM shadow was projected against. What changes is only that
; VBlank does less, which is the direction this rail's budget cares about.
;
; It runs FIRST in the tick, before the swarm and the projection: the tick's
; whole job is "advance S -> S', then project S'", and a projection taken
; before the advance would be a frame behind the floor.
;
; INPUT OR AUTONOMOUS, never both — see cam_input's header for why that is a
; test-surface decision rather than a preference.
;
; THE FRAME'S POSE STEP IS PUBLISHED HERE, first and unconditionally. TS_STEP
; carries the fraction between frames, so it must run every frame whether or not
; anything is turning — a step computed only on the frames a pad is held would
; carry a fraction sampled from the player rather than from the clock. It is
; also outside the `SH2_FREEZE` guard for the same reason: freezing the cameras
; freezes what READS the step, not the clock that produces it.
;
; ONE EXPANSION PER FRAME, for both cameras and all 22 followers: swm_ai reads
; the same word. That is the whole per-frame cost of this rail's rotation
; compensation, and the translation's is a dp OR inside an index it already
; computes.
sh2_advance:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sh2_advance"
    TS_STEP z:US_TSH_ACC, SH2_HEAD_BASE
    sta z:US_TSH
.ifndef SH2_FREEZE
.ifdef SH2_AUTOCAM
    jsr cam_rotate
    jsr cam_drive
.else
    jsr cam_input
.endif
.endif
    rts

; --- sh2_region: pick this console's move arm (scene enter) -----------------
; CONTRACT sh2_region
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_RGN_PAL — the region flag, latched once at boot by
;             region_init
;   out:      US_MOVE_ARM selected on BOTH arms of the branch; US_TSH_ACC
;             zeroed and US_TSH seeded with the NTSC step
;   clobbers: A, N, Z
;   assumes:  region_init has already run in MAIN. Power-on DP is random
;             (rule 5), so every word this writes is a write-before-read
;             obligation this routine discharges at enter
;   tail:     rts
;
; ONCE, AT ENTER. The console cannot change region, so this is the only place
; the flag is read on the motion path — everything after it is an OR against a
; word. `region_init` has already run in MAIN by the time a scene enters, and
; US_MOVE_ARM is written on BOTH arms of the branch, which is the
; write-before-read contract for it (power-on DP is random — rule 5).
;
; It also seeds the heading scaler's two words, and US_TSH_ACC is the one that
; MUST be here: TS_STEP adds the carried fraction, so an unseeded accumulator is
; a first frame that turns by whatever the console powered on holding. US_TSH is
; written by every tick before anything reads it, and is seeded anyway so the
; whole claim is written at enter rather than by an ordering.
sh2_region:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sh2_region"
    lda z:ES_RGN_PAL
    bne @pal
    lda #SH2_MOVE_ARM_NTSC
    bra @arm
@pal:
    .a16
    .i16
    lda #SH2_MOVE_ARM_PAL
@arm:
    .a16
    .i16
    sta z:US_MOVE_ARM
    stz z:US_TSH_ACC
    lda #SH2_HEAD_BASE / TS_ONE     ; the NTSC step, until the first tick
    sta z:US_TSH
    rts
