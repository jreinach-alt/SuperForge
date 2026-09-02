; =============================================================================
; hall scene — mode 4, and the axis bit is the whole subject
; =============================================================================
; One 32-word row a frame drives every column on screen, and each column's own
; word says which AXIS it moves on. Four bays: pistons pumping vertically on
; BG1 in the left half of each, tread belts running horizontally on BG2 in the
; right half. Nothing else reaches the hardware per frame.
;
; Y HOLDS THE FLAT CONTROL. It selects the blob's last row — every column at
; rest, every enable bit and every axis bit still set, the same channel moving
; the same 64 B into the same place. Exactly one variable moves between running
; and flat, which is what makes the flat frame a control rather than a second
; unexplained state.
;
; B HOLDS THE RIDE, which is a different control on a different subject: it
; stops the car climbing so a still can be taken anywhere in the sequence. The
; two were the same button between the lift landing and 2026-08-30, which meant
; the flat control had no way to be selected at all — see mill.inc.
.scope hall
.include "engine_state_hall.inc"    ; GENERATED — this scene's map
MIL_OPT_BG1  = ES_OPT_HALL_BG1      ; the walker reads THIS scene's field set
MIL_OPT_BG2  = ES_OPT_HALL_BG2      ;   through these four names — the offset
MIL_OPT_VSEL = ES_OPT_HALL_VSEL     ;   composition emits one set per scene,
MIL_OPT_MASK = ES_OPT_HALL_MASK     ;   and the melt aliases its own
.include "mil_opt.asm"              ; the table walker. SCENE-SCOPED

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
    stz z:ES_MIL_CAM_SHOWN
    lda #SMIL_CAM_MAX               ; the camera opens at the FORGE FLOOR, the
    sta z:ES_MIL_CAM                ;   bottom of a two-screen world
    stz z:US_TSC
    stz z:US_TSC_ACC
    stz z:ES_MIL_CAR
    stz z:ES_MIL_RIDER_Y
    stz z:ES_MIL_STEP
    stz z:ES_MIL_FACE
    stz z:ES_MIL_BOARD              ; HE ARRIVES STANDING ON THE CAR, not shut
    lda #SMIL_RIDE_X                ;   in it, at the X the ride staged him. The car is on the deck — its
    sta z:ES_MIL_PX                 ;   bottom IS the deck's top, which the
                                    ;   generator asserts — so its four columns
                                    ;   are ground, and he can walk straight off
                                    ;   them or press UP to go back. Arriving
                                    ;   ABOARD instead started the climb on the
                                    ;   first frame and he never had the pad
    jsr mil_arm_bg                  ; CHR, maps, palettes, BG1SC/BG2SC/BG12NBA
    jsr mil_obj_arm                 ; the rider's CHR, palette and OBSEL
    jsr mil_leaves_park             ; ...and the lobby's lift leaves put away.
                                    ;   OAM is not scene state: the shadow
                                    ;   carries across the edge, and a bay left
                                    ;   open would hang four doors in the mill
    jsr mil_rider_stage             ; ...AND THE MAN HIMSELF, for exactly the
                                    ;   same reason the leaves are parked here
                                    ;   — which this line was missing while the
                                    ;   line above it stated the principle. His
                                    ;   entry held the LOBBY's coordinates for
                                    ;   the whole handover, so the mill floor
                                    ;   faded up with him standing where the
                                    ;   bay had been, 18 frames measured, and
                                    ;   he snapped onto the car when the tick
                                    ;   finally ran. Everything this reads —
                                    ;   CAM, CAR, PHASE, PX, BOARD — is set
                                    ;   above, so it stages the arrival pose.
    jsr mil_arm_scroll              ; the four fallback ports, at rest
    jsr mil_tint_arm                ; the colour window over the shaft
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
    ; ---- Y SELECTS THE FLAT ROW, and it is a HOLD rather than a toggle ----
    ; A hold is the honest shape for a control: the two states are the two
    ; positions of one finger, so a still of either is reproducible without
    ; knowing how many times the button has been pressed before.
    lda z:ES_INP_CUR
    and #JOY_Y
    beq :+
    lda #1
:   .a16
    .i16
    and #1
    sta z:ES_MIL_FLATSEL
    ; ---- the columns advance every frame, flat or not ---------------------
    ; UNCONDITIONALLY, and that is what makes the toggle a control: flattening
    ; changes ONE thing — which row the transfer reads — and leaves the
    ; animation's position alone, so un-flattening resumes rather than restarts.
    lda z:US_TSC
    jsr mil_advance
    ; ---- HE HAS THE CONTROLS UNTIL HE GIVES THEM UP ----------------------
    ; The hall used to be a cutscene that started itself after a beat. It is a
    ; place now: he steps out of the car onto the deck, walks it as far as the
    ; floor goes, and the ride begins when he stands back on the lift and
    ; presses UP. `mil_walk_hall` returns immediately once the car is moving,
    ; so the performance below is unchanged from the frame it starts.
    jsr mil_walk_hall
    lda z:ES_MIL_BOARD              ; ...and the lift answers where he stands,
    bne :+                          ;   which is what makes the hole in the
    jsr mil_lift_call               ;   floor open and shut
:   .a16
    .i16
    ; ---- THE RIDE, and it is one number --------------------------------
    ; The car climbs; the camera follows it until the world runs out, and then
    ; the car keeps going and leaves through the top. Both fall out of the same
    ; quantity, so nothing has to be kept in step with anything:
    ;     cam = CAM_MAX - car, clamped at 0
    ;     the car's screen row = CAR_ROW*8 - cam - car
    ; While the camera can follow, those cancel and the car HOLDS STILL with the
    ; shaft sliding past it — which is what riding a lift looks like, and it is
    ; the one column on screen whose word is not changing while every other
    ; column's is.
    ; ---- DOWN ON THE CAR: the other stop -----------------------------------
    ; He pressed DOWN standing on the lift (mil_try_descend). One request, and
    ; then the room stops answering him: the melt's enter takes over.
    lda z:ES_MIL_BOARD
    cmp #SMIL_BOARD_DOWN
    bne @not_down
    lda #SMIL_BOARD_GONE
    sta z:ES_MIL_BOARD
    sep #$20
    .a8
    SM_SWITCH "HALL", "MELT"
    rep #$20
    .a16
    bra @hold
@not_down:
    .a16
    .i16
    lda z:ES_MIL_BOARD              ; ...and only once he is aboard. The beat
    cmp #SMIL_BOARD_ABOARD          ;   before it moves is his to take now
    bne @hold
    lda z:ES_INP_CUR
    and #JOY_B
    bne @hold
    lda z:ES_MIL_CAR
    cmp #SMIL_CAR_TOP
    bcs @arrived
    clc
    adc #SMIL_CAR_STEP
    sta z:ES_MIL_CAR
    bra @hold
    ; ---- THE FAR END OF THE RIDE ------------------------------------------
    ; The car left the top of the screen a long way back — CAR_TOP is well past
    ; the row where its last pixel goes — so what this is really waiting for is
    ; a beat of empty shaft, and then the lift lets him out somewhere else.
    ; THE OTHER BAY, which is the one thing the whole sequence is for: the bay
    ; is a word the lobby handed up, and flipping it is what makes arriving
    ; different from leaving.
@arrived:
    .a16
    .i16
    lda z:ES_MIL_BAY
    eor #2                          ; ...the other bay, as a word offset
    sta z:ES_MIL_BAY
    lda #1
    sta z:ES_MIL_ARRIVE
    sep #$20
    .a8
    SM_SWITCH "HALL", "LOBBY"
    rep #$20
    .a16
@hold:
    .a16
    .i16
    ; THE CAMERA FOLLOWS THE RIDE, NOT THE CAR. They were the same thing while
    ; the car only ever moved with him in it; once the lift comes and goes on
    ; its own, a camera tied to the car pans away from the man standing on the
    ; deck every time the lift is called elsewhere — which is what it did, and
    ; it took the player off the bottom of the picture.
    lda z:ES_MIL_BOARD
    cmp #SMIL_BOARD_ABOARD
    beq :+
    lda #SMIL_CAM_MAX               ; on foot: the deck, and it does not move
    sta z:ES_MIL_CAM
    jsr mil_rider_stage
    rts
:   .a16
    .i16
    lda #SMIL_CAM_MAX               ; ...aboard: the camera follows him up
    sec
    sbc z:ES_MIL_CAR
    bpl :+
    lda #0
:   .a16
    .i16
    sta z:ES_MIL_CAM
    jsr mil_rider_stage
    ; ---- the camera climbs the shaft ---------------------------------------
    ; UP and DOWN move it; the clamps are the world's own ends. This is the
    ; whole reason the staging routine exists: an offset word REPLACES its
    ; column's scroll, so the camera has to be inside every vertical word or
    ; the machines stay nailed to the screen while the hall slides past them.
    ; ---- B holds the ride, so a still can be taken anywhere in it ---------
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
