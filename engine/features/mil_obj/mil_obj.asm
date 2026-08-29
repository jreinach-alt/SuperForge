; =============================================================================
; mil_obj.asm — the rider, occluded by the car he is inside
; =============================================================================
; THE OCCLUSION IS THE PRIORITY ORDER AND NOTHING ELSE. Mode 4 renders
; BG2lo(1) OBJ0(2) BG1lo(3) OBJ1(4) BG2hi(5) OBJ2(6) BG1hi(7) OBJ3(8), and a
; sprite is drawn only where the pixel already there scores LOWER:
; `(_mainScreenFlags[x] & 0x0F) < spritePrio` (SnesPpu.cpp:958). At OBJ
; priority 0 the rider scores 2 — under BG1's 3, over BG2's 1 — so the car's
; opaque shell hides him and the hole cut where its glass is shows him. The
; occlusion rides up the shaft with the car because it IS the car.
;
; CPU-WRITTEN REGISTER, DECLARED: OBSEL $2101 (mil_obsel), at scene enter.

MIL_OBJ_REGS = $4300 + ES_D_MIL_OBJ_UP_CH * 16
MIL_RIDER_OAM = ES_OAM_SHADOW + ES_O_MIL_RIDER * 4
MIL_RIDER_HI  = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32 + (ES_O_MIL_RIDER / 4)

; THE SIZE BIT LIVES IN THE HI TABLE, four sprites to a byte, so an entry that
; does not start one would need a read-modify-write against three neighbours
; this feature does not own.
.assert ES_O_MIL_RIDER .MOD 4 = 0, error, "mil_obj: the rider must start a hi-table byte"

; OBSEL: bits 0-2 the OBJ name base in 8K-WORD steps, bits 5-7 the size pair.
; Pair 3 is small 16x16 / large 32x32, and the rider is large.
MIL_OBSEL_PAIR3 = 3 << 5

; The size bit in the hi table: bit0 of a sprite's 2-bit field is X9, bit1 is
; SIZE (Mesen2 SnesPpu.cpp:679 decodes it exactly this way). Pair 3 makes
; `large` 32x32, so one OAM entry draws the whole rider.
MIL_RIDER_SIZE_LARGE = 1 << 1

; OAM attr byte: PRIORITY 0 and OBJ palette 0. Priority 0 is not a default here
; and not a small choice — it is the entire occlusion mechanism. Mode 4 scores
; it 2, BG1's normal tiles 3, and a sprite draws only where what is already
; there scores lower, so the car's shell hides the rider and its glass does not.
; smt_obj's knight uses priority 3 for the opposite reason: he has to be in
; front of everything.
MIL_RIDER_ATTR = (0 << 4)

; ...and the base has to BE expressible in that 8K-word field. That is a
; property of where the allocator put the claim, so it is asserted against the
; emitted symbol rather than assumed — the alternative is an OBJ page silently
; read from somewhere else.
.assert ES_V_MIL_OBJ_CHR = (ES_V_MIL_OBJ_CHR_OBSEL_BASE << 13), error, "mil_obj: the rider's CHR base is not expressible in OBSEL's 8K-word field"

; --- mil_obj_arm: CHR, palette, OBSEL (scene enter) ------------------------
; CONTRACT mil_obj_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the rider's CHR in its OBJ page, OBJ palette 0 written, OBSEL set
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
mil_obj_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_obj_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_MIL_OBJ_CHR
    sta a:$2116
    ldx #.loword(mil_obj_bin)
    sty a:MIL_OBJ_REGS + 5          ; (DAS re-armed below; Y is set first so
    ldy #ES_R_MIL_OBJ_SIZE          ;  the store order reads with the claim)
    stx a:MIL_OBJ_REGS + 2
    sty a:MIL_OBJ_REGS + 5          ; DAS — armed for THIS transfer
    sep #$20
    .a8
    lda #^mil_obj_bin
    sta a:MIL_OBJ_REGS + 4
    lda #ES_D_MIL_OBJ_UP_DMAP
    sta a:MIL_OBJ_REGS + 0
    lda #ES_D_MIL_OBJ_UP_BBAD
    sta a:MIL_OBJ_REGS + 1
    lda #(1 << ES_D_MIL_OBJ_UP_CH)
    sta a:$420B
    ; ---- OBJ palette 0, at the claim's own base ---------------------------
    lda #ES_C_MIL_OBJ_PAL
    sta a:$2121                     ; CGADD = 128
    rep #$20
    .a16
    ldx #0
@pal:
    .a16
    .i16
    lda f:mil_obj_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_MIL_OBJ_PAL_SIZE
    bcc @pal
    ; ---- OBSEL: the 32x32 size pair, and the claim's own base -------------
    sep #$20
    .a8
    lda #(MIL_OBSEL_PAIR3 | ES_V_MIL_OBJ_CHR_OBSEL_BASE)
    sta a:$2101
    rep #$20
    .a16
    rts

; --- mil_rider_stage: put the rider where the car's glass is ---------------
; CONTRACT mil_rider_stage
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       ES_MIL_CAR — the car's displacement up the shaft, in pixels
;             ES_MIL_CAM — the camera, because the car's column carries it
;             ES_MIL_PHASE — which idle cell
;   out:      the rider's shadow-OAM entry written, or PARKED when the glass is
;             off screen, and ES_MIL_RIDER_Y published with the row he was
;             staged at (or SMIL_PARK_Y when parked)
;   clobbers: A, X, Y, N, Z, C
;   assumes:  the main thread; writes the OAM SHADOW, which oam_nmi_dma commits
;   tail:     rts
;
; THE CAR'S SCREEN ROW IS DERIVED, NOT TRACKED. The PPU puts map row R of a
; displaced column at screen row R*8 - word, and the car's word is
; camera + displacement — so the glass is at
;     SMIL_CAR_ROW*8 - (cam + car) + SMIL_WIN_Y
; and there is no second copy of the car's position to drift from the first.
; That is the same join `smt_cam_shown` exists for, made structural instead.
;
; WIDTH-RISK: A16 throughout; the OAM byte writes narrow explicitly. The Y
; comparison is SIGNED — the car climbs off the top of the screen and its glass
; row goes negative, which an unsigned test reads as far below the picture and
; leaves the rider drawn across the bottom of it.
mil_rider_stage:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_rider_stage"
    lda #(SMIL_CAR_ROW * 8 + SMIL_WIN_Y)
    sec
    sbc z:ES_MIL_CAM
    sec
    sbc z:ES_MIL_CAR                ; ...the glass's screen row
    sta z:ES_MIL_RIDER_Y
    ; ---- off the top or off the bottom: park -----------------------------
    ; ONE UNSIGNED COMPARE FOR BOTH ENDS, after biasing by the sprite box. The
    ; car climbs off the TOP, so the glass row goes negative — and a negative
    ; row plus the box either lands inside the band (still partly on screen,
    ; draw it) or wraps enormous (gone, park it). A signed pair of tests would
    ; need negative immediates, which is a hex mask, which is a raw address
    ; operand the moment it is written down.
    clc
    adc #SMIL_RIDER_BOX
    bmi @park                       ; STILL negative after the bias: the car is
                                    ;   fully above the picture. Tested as a
                                    ;   SIGN and not as a magnitude, because a
                                    ;   16-bit add wraps SMALL — glass row -20
                                    ;   biased by 32 is 12, not 65548 — so a
                                    ;   `cmp` alone reads far-above-the-screen
                                    ;   as just-below-the-top
    cmp #SMIL_RIDER_VIS_SPAN
    bcs @park
    ; ---- his X: the car's column, plus the glass, centred on the box -----
    lda #(SMIL_CAR_COL * 8 + SMIL_WIN_X + SMIL_WIN_W / 2 - SMIL_RIDER_BOX / 2 + SMIL_RIDER_DX)
    sep #$20
    .a8
    sta a:MIL_RIDER_OAM + 0         ; X, low 8
    lda z:ES_MIL_RIDER_Y
    sec
    sbc #SMIL_RIDER_RAISE           ; ...the art's own offset inside the glass.
                                    ;   A SUBTRACTION, because the offset is
                                    ;   upward and a negative immediate is a
                                    ;   hex mask the no-literals gate refuses
    sta a:MIL_RIDER_OAM + 1         ; Y
    rep #$20
    .a16
    ; ---- which idle cell, from the PHASE and not from a frame count ------
    lda z:ES_MIL_PHASE
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    and #(SMIL_RIDER_FRAMES - 1)
    .repeat 2
    asl a                           ; ...one 32x32 cell is 4 tiles across
    .endrepeat
    sep #$20
    .a8
    sta a:MIL_RIDER_OAM + 2         ; tile, low 8
    lda #MIL_RIDER_ATTR             ; PRIORITY 0 — the whole point: it scores 2
    sta a:MIL_RIDER_OAM + 3         ;   and loses to BG1's 3 (SnesPpu.cpp:958)
    lda #MIL_RIDER_SIZE_LARGE       ; ...and the size bit for a 32x32 sprite
    sta a:MIL_RIDER_HI              ; whole byte: the three parked neighbours'
                                    ;   fields are zero and stay zero
    rep #$20
    .a16
    rts
@park:
    .a16
    .i16
    lda #SMIL_PARK_Y
    sta z:ES_MIL_RIDER_Y
    sep #$20
    .a8
    sta a:MIL_RIDER_OAM + 1         ; Y off the bottom: the documented park
    rep #$20
    .a16
    rts
