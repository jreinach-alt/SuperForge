; =============================================================================
; melt scene — the lift's other stop, and the table read in BANDS
; =============================================================================
; The same map, seen from its last screen: the machines' feet and the belts
; above the deck, the deck, and under it the whole molten channel. Three bands
; of the picture read three different rows of the offset table, because an
; HDMA channel rewrites BG3VOFS at each band's first line and the PPU fetches
; the row that port names (SnesPpu.cpp GetHorizontalOffsetByte, :257-276):
;
;   A  the hall's running row        the pistons pump, the belts run
;   B  a row with no enable bit      the deck, at both layers' fallback
;   C  a ripple row                  every column a VERTICAL word: the same
;                                    screen columns that carry a HORIZONTAL
;                                    word in band A, now moving on the other
;                                    axis, in the same frame
;
; That third line is what the hall cannot show and this room exists for: mode
; 4 makes the axis a per-column choice, and bands make it per-column PER
; BAND. The channel is `mil_melt`'s [[claims.offset_bands]] — the
; composition's own — armed here through scene_mgr's shadow.
;
; He rides down in the car and stays in it; UP takes him back. Y holds both
; moving bands flat (the hall's control row and the ripple's), which leaves
; band B the control that is always on: a still band between two moving ones,
; from the same table, in the same frame.
.scope melt
.include "engine_state_melt.inc"    ; GENERATED — this scene's map
MIL_OPT_BG1  = ES_OPT_MELT_BG1      ; the walker reads THIS scene's field set
MIL_OPT_BG2  = ES_OPT_MELT_BG2
MIL_OPT_VSEL = ES_OPT_MELT_VSEL
MIL_OPT_MASK = ES_OPT_MELT_MASK
.include "mil_opt.asm"              ; the table walker, scene-scoped
.include "mil_melt.asm"             ; ...and the bands: rows, channel, table

; --- enter: the whole picture, under forced blank --------------------------
; CONTRACT melt::enter
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      both layers uploaded and armed, BG3's three rows in place, the
;             band channel armed in the scene_mgr shadow, the rider aboard,
;             the scroll ports at the melt's camera and the screen composed
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
enter:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "melt::enter"
    stz z:ES_MIL_PHASE
    stz z:ES_MIL_SHOWN
    stz z:ES_MIL_FLATSEL
    stz z:ES_MIL_CAM_SHOWN
    lda #SMIL_MELT_CAM              ; the camera: the map's last screen, and
    sta z:ES_MIL_CAM                ;   it does not move in this room
    stz z:US_TSC
    stz z:US_TSC_ACC
    stz z:ES_MIL_CAR                ; the car is at the bottom of its shaft...
    stz z:ES_MIL_RIDER_Y
    stz z:ES_MIL_STEP
    lda #SMIL_BOARD_ABOARD          ; ...with him in it, behind the glass
    sta z:ES_MIL_BOARD
    lda #SMIL_RIDE_X
    sta z:ES_MIL_PX
    jsr mil_arm_bg                  ; CHR, maps, palettes, BG1SC/BG2SC/BG12NBA
    jsr mil_obj_arm                 ; the rider's CHR, palette and OBSEL
    jsr mil_leaves_park             ; the lobby's leaves, put away (hall's rule)
    jsr mil_rider_stage             ; ...and the man, staged for the arrival
    jsr mil_arm_scroll              ; the four fallback ports, at this camera
    jsr mil_tint_arm                ; the colour window over the shaft
    ; ---- BG3 BECOMES THE TABLE — three rows of it -------------------------
    ; The ports are the composition's and this write is the scene's consent
    ; (hall.asm says why). BG3VOFS here is the SEED: row 0 for the whole
    ; frame, which the band channel overrides from line 0.
    sep #$20
    .a8
    lda #ES_V_MIL_TAB_SC_BASE
    sta a:$2109                     ; BG3SC — the table's page, from the claim
    stz a:$2111                     ; BG3HOFS, low
    stz a:$2111                     ; ...high
    stz a:$2112                     ; BG3VOFS, low — the seed
    stz a:$2112                     ; ...high
    rep #$20
    .a16
    lda #(ES_V_MIL_TAB + 2 * SMIL_COLS)  ; row 2: the zero row, band B's,
    jsr mil_zero_row_at             ;   written once — nothing restages it
    jsr mil_melt_arm_bands          ; the HDMA table, the slot, the enable bit
    ; ---- the composed screen ----------------------------------------------
    sep #$20
    .a8
    lda #ES_VID_MELT_BGMODE
    sta a:$2105                     ; BGMODE
    lda #ES_SCR_MELT_TM
    sta a:$212C
    lda #ES_SCR_MELT_TS
    sta a:$212D
    lda #ES_SCR_MELT_CGWSEL
    sta a:$2130
    lda #ES_SCR_MELT_CGADSUB
    sta a:$2131
    rep #$20
    .a16
    rts

; --- tick: one frame (display active — no VRAM writes here) ----------------
; CONTRACT melt::tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   clobbers: A, X, Y, N, Z, C
;   tail:     rts
tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "melt::tick"
    TS_STEP z:US_TSC_ACC, SMIL_PHASE_BASE
    sta z:US_TSC
    ; ---- Y SELECTS THE FLAT ROWS: a hold, the hall's rule ------------------
    lda z:ES_INP_CUR
    and #JOY_Y
    beq :+
    lda #1
:   .a16
    .i16
    and #1
    sta z:ES_MIL_FLATSEL
    lda z:US_TSC
    jsr mil_advance                 ; the columns and the surface advance,
                                    ;   flat or not — flattening changes which
                                    ;   rows the transfer reads and nothing else
    jsr mil_rider_stage             ; in the car, at this camera
    ; ---- UP: back to the hall, once --------------------------------------
    lda z:ES_MIL_BOARD
    cmp #SMIL_BOARD_ABOARD
    bne @done                       ; already leaving: nothing answers the pad
    lda z:ES_INP_CUR
    and #JOY_UP
    beq @done
    lda #SMIL_BOARD_GONE
    sta z:ES_MIL_BOARD
    sep #$20
    .a8
    SM_SWITCH "MELT", "HALL"
    rep #$20
    .a16
@done:
    .a16
    .i16
    rts

; --- exit -------------------------------------------------------------------
; CONTRACT melt::exit
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   clobbers: none
;   tail:     rts
exit:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "melt::exit"
    rts
.endscope
