; =============================================================================
; lobby scene — the room the ride leaves from, in the SAME mode as the hall
; =============================================================================
; A flat interior with two lift bays. It is a mode-4 scene like `hall` and it
; shares the CHR page, both palettes and the OBJ sheet with it — what changes
; across the edge is which map BG1SC points at, and what BG3's offset row says.
;
; BG3 IS STILL AN OFFSET TABLE HERE, because the mode says so. The PPU reads
; BG3's map as per-column scroll words in mode 4 whether or not a scene means
; to use them, so this one writes a row of ZEROS at enter: no enable bit set
; anywhere, no column displaced, and both layers scroll from BGnHOFS/BGnVOFS
; like an ordinary screen. That is the same hygiene obligation `smelter`'s
; title discharges by re-pointing BG3SC — the difference is that this rail
; stays in one mode, so the table is disarmed by its CONTENT rather than by
; being pointed elsewhere.
;
; THE DOORS ARE SPRITES AND THAT IS NOT A SHORTCUT. A leaf sliding open is a
; PARTIAL reveal — the wall above it and the floor below it hold still — and
; the one fact this whole rail is built on is that A DISPLACED COLUMN MOVES
; WHOLE. There is no offset word that opens a door. The hall's machines work
; because a ram fills its column; a door does not fill anything.
.scope lobby
.include "engine_state_lobby.inc"   ; GENERATED — this scene's map

; --- enter: the room, under forced blank ------------------------------------
; CONTRACT lobby::enter
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      BG1 pointing at the lobby map, BG3's offset row zeroed, the
;             player on the floor, both bays shut, and the screen composed
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
enter:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lobby::enter"
    ; ---- state. Power-on DP is RANDOM (rule 5), so these stores ARE the
    ; write-before-read contract and not defensive initialisation.
    stz z:ES_MIL_PHASE
    stz z:ES_MIL_SHOWN
    stz z:ES_MIL_FLATSEL
    stz z:ES_MIL_CAM
    stz z:ES_MIL_CAM_SHOWN
    stz z:ES_MIL_CAR
    stz z:ES_MIL_STEP
    stz z:ES_MIL_FACE
    stz z:ES_MIL_DOOR
    stz z:ES_MIL_DOOR + 2
    stz z:US_TSC
    stz z:US_TSC_ACC
    ; ---- WHICH ROOM HE IS WALKING INTO --------------------------------------
    ; This scene is entered twice and means something different each time, and
    ; the difference is one word the ride carried across the edge. At boot he
    ; is on the deck with both bays shut; coming back off the lift he is INSIDE
    ; the other bay with its doors shut in front of him, and they part to reveal
    ; him — which needs no code at all, because the leaves are ahead of him in
    ; OAM and simply cover him until they are not there.
    lda z:ES_MIL_ARRIVE
    bne @arrived
    lda #SMIL_SPAWN_X               ; ...boot: on the deck, both bays shut
    sta z:ES_MIL_PX
    stz z:ES_MIL_BAY
    stz z:ES_MIL_BOARD
    bra @placed
@arrived:
    .a16
    .i16
    stz z:ES_MIL_ARRIVE             ; consumed: the next boot is a boot again
    ldx z:ES_MIL_BAY                ; ...the bay the hall handed back
    lda f:mil_bay_x, x
    clc
    adc #SMIL_BOARD_DEST            ; centred in it, behind its shut doors
    sta z:ES_MIL_PX
    lda #SMIL_BOARD_OUT
    sta z:ES_MIL_BOARD
@placed:
    .a16
    .i16
    jsr mil_arm_bg                  ; CHR, both maps, palettes, the layer bases
    jsr mil_obj_arm                 ; the OBJ sheet, its two palettes, OBSEL
    jsr mil_lobby_up                ; the lobby map into its own page...
    jsr mil_lobby_bases             ; ...and BG1SC re-pointed at it
    jsr lobby_flat                  ; BG3 zeroed, and the four ports at rest
    jsr mil_tint_arm                ; the colour window (its bay is off-screen
                                    ;   here; the claim is global and the
                                    ;   registers are established either way —
                                    ;   a port nobody writes holds what the
                                    ;   last scene left in it)
    sep #$20
    .a8
    lda #ES_VID_LOBBY_BGMODE
    sta a:$2105                     ; BGMODE
    lda #ES_SCR_LOBBY_TM
    sta a:$212C
    lda #ES_SCR_LOBBY_TS
    sta a:$212D
    lda #ES_SCR_LOBBY_CGWSEL
    sta a:$2130
    lda #ES_SCR_LOBBY_CGADSUB
    sta a:$2131
    rep #$20
    .a16
    jsr mil_lobby_stage             ; the player and the leaves, before the
    rts                             ;   first frame is drawn

; --- tick: one frame --------------------------------------------------------
; CONTRACT lobby::tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   clobbers: A, X, Y, N, Z, C
;   tail:     rts
tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lobby::tick"
    TS_STEP z:US_TSC_ACC, SMIL_PHASE_BASE
    sta z:US_TSC
    lda z:US_TSC                    ; the idle cell rides the phase. Advanced
    clc                             ;   here rather than through the hall's
    adc z:ES_MIL_PHASE              ;   `mil_advance`, whose file is scoped to
    cmp #SMIL_PHASES                ;   that scene — six lines against a
    bcc :+                          ;   cross-scope call into a walker this
    sec                             ;   room does not otherwise use
    sbc #SMIL_PHASES
:   .a16
    .i16
    sta z:ES_MIL_PHASE
    jsr mil_lobby_walk
    jsr mil_lobby_doors
    jsr mil_lobby_stage
    rts

; --- lobby_flat: BG3 disarmed, and the four scroll ports at rest ------------
; CONTRACT lobby::lobby_flat
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      SMIL_COLS zero words at BG3's offset row, and BG1/BG2 H and V
;             scroll at zero
;   clobbers: A, X, N, Z
;   assumes:  forced blank AND the NMI masked
;   tail:     rts
;
; A MODE-4 SCENE THAT WANTS NO OFFSETS STILL HAS AN OFFSET TABLE. The PPU reads
; BG3's map as per-column scroll words whenever the mode says so and does not
; ask whether the scene meant it — so this room disarms the table by its
; CONTENT: no enable bit set anywhere, therefore no column displaced, therefore
; both layers scroll from BGnHOFS/BGnVOFS like an ordinary screen.
;
; That is the obligation `smelter`'s title discharges by re-pointing BG3SC at a
; text map. This rail stays in ONE MODE across its edge, so it cannot point the
; table away — it has to make it mean nothing instead.
;
; The four scroll ports are `mil_opt`'s claim and this scene is named in its
; `scene_writes`, which is the declared way a scene establishes a port its
; owner also drives.
lobby_flat:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lobby::lobby_flat"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_MIL_TAB
    sta a:$2116
    ldx #0
@word:
    .a16
    .i16
    stz a:$2118                     ; the word port, low
    stz a:$2119                     ; ...and high
    inx
    cpx #SMIL_COLS
    bcc @word
    sep #$20
    .a8
    stz a:$210E                     ; BG1VOFS, low
    stz a:$210E                     ; ...high
    stz a:$2110                     ; BG2VOFS
    stz a:$2110
    stz a:$210D                     ; BG1HOFS
    stz a:$210D
    stz a:$210F                     ; BG2HOFS
    stz a:$210F
    rep #$20
    .a16
    rts

; --- mil_lobby_doors: the call, and the two leaves that answer it -----------
; CONTRACT lobby::mil_lobby_doors
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      every bay's travel advanced one step toward where its owner
;             wants it; ES_MIL_BOARD advanced at the ends of the ride
;   clobbers: A, X, Y, N, Z, C
;   tail:     rts
;
; ONE RULE, AND THE PHASE ONLY SAYS WHO IS ASKING. A bay opens while somebody
; wants it open and shuts otherwise; the travel is the state, and it is a
; position rather than a phase — so a door caught half-open reverses from where
; it is instead of restarting, and there is nothing to keep in step with
; anything. While he is free the asker is his own proximity; once he has
; committed to a ride the asker is the ride, and the only thing that changes
; is which bay gets which answer.
mil_lobby_doors:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lobby::mil_lobby_doors"
    lda z:ES_MIL_BOARD
    beq @proximity
    cmp #SMIL_BOARD_ABOARD
    beq @aboard
    cmp #SMIL_BOARD_OUT
    beq @alight
    ; ---- BOARD_IN: hold his bay open while he walks in, shut the other -----
    ldx z:ES_MIL_BAY
    jsr mil_door_open
    jsr mil_other_shut
    rts
    ; ---- ABOARD: the doors close over him, and the ride begins when shut ---
@aboard:
    .a16
    .i16
    ldx z:ES_MIL_BAY
    jsr mil_door_shut
    bne @done                       ; still closing
    sep #$20
    .a8
    SM_SWITCH "LOBBY", "HALL"       ; ...and the edge the game.toml declares
    rep #$20
    .a16
    rts
    ; ---- OUT: the doors part to reveal him, and he has the controls back ---
    ; NOT UNTIL THE PICTURE IS UP. A scene's tick runs through the fade-in, and
    ; the doors take fifteen frames to part — so left ungated they finish while
    ; the screen is still ramping and the reveal happens in the dark, which is
    ; the same as no reveal. The condition is scene_mgr's own published phase
    ; (ES_SM_CTL+2, 0 = run) and not a count of frames: a count would have to be
    ; tuned against the ramp, would be wrong the moment the ramp changed, and
    ; would be a frame assumption in a rail that scales its time.
@alight:
    .a16
    .i16
    sep #$20
    .a8
    lda z:ES_SM_CTL + 2             ; the transition phase, a BYTE
    rep #$20                        ; REP touches only M here, so the Z the
    .a16                            ;   load set survives the width change
    bne @done                       ; still fading: the doors hold shut
    ldx z:ES_MIL_BAY
    jsr mil_door_open
    cmp #SMIL_DOOR_TRAVEL
    bcc @done
    stz z:ES_MIL_BOARD              ; open: he is free, and the proximity rule
    rts                             ;   takes the bay back over from here
    ; ---- FREE: the proximity rule -----------------------------------------
@proximity:
    .a16
    .i16
    ldx #0
@bay:
    .a16
    .i16
    lda z:ES_MIL_PX
    clc
    adc #(SMIL_RIDER_BOX / 2)       ; ...his centre, not his left edge
    sec
    sbc f:mil_bay_mid, x
    bpl :+
    eor #$FFFF                      ; |distance|, without a signed compare
    inc a
:   .a16
    .i16
    cmp #SMIL_DOOR_REACH
    bcs @far
    jsr mil_door_open
    bra @next
@far:
    .a16
    .i16
    jsr mil_door_shut
@next:
    .a16
    .i16
    inx
    inx
    cpx #(SMIL_DOOR_BAYS * 2)
    bcc @bay
@done:
    .a16
    .i16
    rts

; --- mil_door_open / mil_door_shut: one bay, one step -----------------------
; CONTRACT lobby::mil_door_open
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the bay's WORD OFFSET into ES_MIL_DOOR
;   out:      that bay's travel one step nearer its limit; A = the new travel,
;             Z set when it has REACHED the limit
;   clobbers: A, N, Z, C
;   tail:     rts
;
; The limit is clamped rather than counted to, because DOOR_STEP need not
; divide DOOR_TRAVEL and a door that overshoots its own opening by one step
; would reverse a pixel on the next frame forever.
mil_door_open:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lobby::mil_door_open"
    lda z:ES_MIL_DOOR, x
    cmp #SMIL_DOOR_TRAVEL
    bcs @at_open
    clc
    adc #SMIL_DOOR_STEP
    cmp #SMIL_DOOR_TRAVEL
    bcc :+
    lda #SMIL_DOOR_TRAVEL
:   .a16
    .i16
    sta z:ES_MIL_DOOR, x
@at_open:
    .a16
    .i16
    cmp #SMIL_DOOR_TRAVEL           ; Z when it is standing open
    rts

; CONTRACT lobby::mil_door_shut
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the bay's WORD OFFSET into ES_MIL_DOOR
;   out:      that bay's travel one step nearer zero; A = the new travel, Z set
;             when it is SHUT
;   clobbers: A, N, Z, C
;   tail:     rts
mil_door_shut:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lobby::mil_door_shut"
    lda z:ES_MIL_DOOR, x
    beq @at_shut
    sec
    sbc #SMIL_DOOR_STEP
    bpl :+
    lda #0
:   .a16
    .i16
    sta z:ES_MIL_DOOR, x
@at_shut:
    .a16
    .i16
    cmp #0                          ; Z when it is shut
    rts

; --- mil_other_shut: the bay he did NOT call --------------------------------
; CONTRACT lobby::mil_other_shut
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the bay he DID call, as a word offset
;   out:      every other bay one step nearer shut; X restored
;   clobbers: A, Y, N, Z, C
;   tail:     rts
mil_other_shut:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lobby::mil_other_shut"
    txy                             ; ...his bay, kept
    ldx #0
@bay:
    .a16
    .i16
    stx z:ES_MIL_NMI_SCRATCH + 4    ; main-thread scratch: the hall's row walker
    tya                             ;   is the only other user and it does not
    cmp z:ES_MIL_NMI_SCRATCH + 4    ;   run in this room
    beq @next
    jsr mil_door_shut
    ldx z:ES_MIL_NMI_SCRATCH + 4
@next:
    .a16
    .i16
    inx
    inx
    cpx #(SMIL_DOOR_BAYS * 2)
    bcc @bay
    tyx
    rts

; --- exit -------------------------------------------------------------------
; CONTRACT lobby::exit
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   clobbers: none
;   tail:     rts
exit:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "lobby::exit"
    rts

.segment "RODATA"
; Each bay's CENTRE, in screen X — what the reach test measures against.
; The reach has to cover the whole doorway and the two must not overlap, or a
; step taken in front of one bay opens the other. Both are arithmetic on
; constants, so both are the assembler's to check rather than a playtest's.
.assert SMIL_DOOR_REACH >= SMIL_DOOR_W * 4, error, "lobby: the reach is narrower than the doorway"
.assert SMIL_DOOR_B * 8 - SMIL_DOOR_A * 8 > SMIL_DOOR_REACH * 2, error, "lobby: the two bays' reaches overlap"
mil_bay_mid:
    .word SMIL_DOOR_A * 8 + SMIL_DOOR_W * 4
    .word SMIL_DOOR_B * 8 + SMIL_DOOR_W * 4
.segment "CODE"
.endscope
