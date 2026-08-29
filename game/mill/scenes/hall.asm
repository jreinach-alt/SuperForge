; =============================================================================
; hall scene — mode 4, and the axis bit is the whole subject
; =============================================================================
; One 32-word row a frame drives every column on screen, and each column's own
; word says which AXIS it moves on. Four bays: pistons pumping vertically on
; BG1 in the left half of each, tread belts running horizontally on BG2 in the
; right half. Nothing else reaches the hardware per frame.
;
; B HOLDS THE FLAT CONTROL. It selects the blob's last row — every column at
; rest, every enable bit and every axis bit still set, the same channel moving
; the same 64 B into the same place. Exactly one variable moves between running
; and flat, which is what makes the flat frame a control rather than a second
; unexplained state.
.scope hall
.include "engine_state_hall.inc"    ; GENERATED — this scene's map
.include "mil_opt.asm"              ; the row transfer, the phase, the ports

; --- enter: the whole picture, under forced blank --------------------------
; CONTRACT hall::enter
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      both layers uploaded and armed, BG3 pointing at the offset table,
;             the scroll ports at rest, the phase at zero and the screen
;             composed
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
enter:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hall::enter"
    ; ---- state. Power-on DP is RANDOM (rule 5), so these stores ARE the
    ; write-before-read contract and not defensive initialisation.
    stz z:ES_MIL_PHASE
    stz z:ES_MIL_SHOWN
    stz z:ES_MIL_FLATSEL
    stz z:US_TSC
    stz z:US_TSC_ACC
    jsr mil_arm_bg                  ; CHR, maps, palettes, BG1SC/BG2SC/BG12NBA
    jsr mil_arm_scroll              ; the four fallback ports, at rest
    ; ---- BG3 BECOMES THE TABLE, and this write is the SCENE'S -------------
    ; BG3SC/BG3HOFS/BG3VOFS are not mil_opt's to claim: the offset composition
    ; synthesizes ownership of them and grants the scene's enter code the
    ; consent to write the emitted values. A raw claim on them beside the
    ; composition is O5's register arm and stops the build by name.
    ;
    ; BG3HOFS INDEXES THE COLUMN and BG3VOFS names WHICH ROW mode 4 reads
    ; (SnesPpu.cpp GetHorizontalOffsetByte, :257-276). Both are zero: the table
    ; is row 0 of its page and its column 0 is screen column 0's.
    sep #$20
    .a8
    lda #ES_V_MIL_TAB_SC_BASE
    sta a:$2109                     ; BG3SC — the table's page, from the claim
    stz a:$2111                     ; BG3HOFS, low
    stz a:$2111                     ; ...high
    stz a:$2112                     ; BG3VOFS, low
    stz a:$2112                     ; ...high
    rep #$20
    .a16
    ; ---- the composed screen ----------------------------------------------
    ; BGMODE and TM/TS come from the vocabulary, not from a narrated byte: the
    ; mode is [[claims.video]] mode 4 and the two layers are this rail's screen
    ; designations. A literal here would be a second, uncheckable copy.
    sep #$20
    .a8
    lda #ES_VID_HALL_BGMODE
    sta a:$2105                     ; BGMODE
    lda #ES_SCR_HALL_TM
    sta a:$212C
    lda #ES_SCR_HALL_TS
    sta a:$212D
    lda #ES_SCR_HALL_CGWSEL
    sta a:$2130
    lda #ES_SCR_HALL_CGADSUB
    sta a:$2131
    rep #$20
    .a16
    rts

; --- tick: one frame (display active — no VRAM writes here) ----------------
; CONTRACT hall::tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   clobbers: A, X, Y, N, Z, C
;   tail:     rts
;
; TS_STEP is expanded once and its output read by the one add that consumes
; it. The step is in WHOLE phases; the fraction it could not publish this frame
; is carried to the next, which is what makes a PAL run walk the same 65 rows
; in the same wall-clock time as an NTSC one.
tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hall::tick"
    TS_STEP z:US_TSC_ACC, SMIL_PHASE_BASE
    sta z:US_TSC
    ; ---- the columns advance every frame, flat or not ---------------------
    ; UNCONDITIONALLY, and that is what makes the toggle a control: flattening
    ; changes ONE thing — which row the transfer reads — and leaves the
    ; animation's position alone, so un-flattening resumes rather than restarts.
    lda z:US_TSC
    jsr mil_advance
    ; ---- B: the flat control ----------------------------------------------
    lda z:ES_INP_PRESS
    and #JOY_B
    beq @no_toggle
    lda z:ES_MIL_FLATSEL
    eor #1
    sta z:ES_MIL_FLATSEL
@no_toggle:
    .a16
    .i16
    rts

; --- exit -------------------------------------------------------------------
; CONTRACT hall::exit
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   clobbers: none
;   tail:     rts
exit:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hall::exit"
    rts
.endscope
