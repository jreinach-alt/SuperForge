; =============================================================================
; mil_band — the bands: which row of the offset table each part of the picture
;            reads, and the channel that says so
; =============================================================================
; SCENE-SCOPED, like mil_opt.asm, and included after it: it reads this scene's
; ES_OPT_<ID>_* field set and the channel the composition synthesized for this
; scene (ES_H_MIL_BANDS_ROWSEL_*).
;
; The rows live in BG3's map at a stride of SMIL_COLS words:
;   row 0  the ROOM's own row — the hall's machine row, restaged every VBlank;
;          the lobby never selects it
;   row 1  the RIPPLE row for this phase, restaged every VBlank in both rooms
;   row 2  a row of ZEROS, written once at enter — no enable bit, so every
;          column it covers shows both layers at their own scroll
;
; A band is one HDMA entry: a line count, then BG3VOFS written twice. A
; non-repeat entry transfers on its first line and holds for the rest, and the
; BGnVOFS write-twice latch keeps the value through the hold — so a band of N
; lines costs three bytes and one transfer, whatever N is.

MIL_BAND_ROW_ZERO = 2 * MIL_OPT_ROW_VOFS     ; ...as BG3VOFS values, which is
MIL_BAND_ROW_RIPPLE = 1 * MIL_OPT_ROW_VOFS   ;   what the table holds
MIL_BAND_ROW_ROOM = 0

; --- mil_band_one: one entry — `lines` scanlines reading the row in Y -------
; CONTRACT mil_band_one
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       A — the entry's line count, 1..SMIL_BAND_MAX
;             Y — the BG3VOFS value naming the row those lines read
;             X — the byte cursor into the table
;   out:      three bytes written at the cursor
;   clobbers: A, X, N, Z
;   tail:     rts
mil_band_one:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mil_band_one"
    sta f:ES_MIL_BANDTAB_LONG, x        ; the line count
    tya                                 ; WIDTH-RISK: A8/I16, so this takes
                                        ;   Y's low byte. Y is a row's
                                        ;   BG3VOFS, 0..16 by construction
                                        ;   (three rows, stride 8), so the
                                        ;   high byte it drops is zero and the
                                        ;   store below writes that zero
    sta f:ES_MIL_BANDTAB_LONG + 1, x    ; BG3VOFS, low
    lda #0                              ; ...and high: a row index times the
    sta f:ES_MIL_BANDTAB_LONG + 2, x    ;   stride never reaches 256. `lda #0`
    inx                                 ;   and not `stz`, which has no long
    inx                                 ;   indexed form on this CPU
    inx                                 ; THREE bytes an entry, and the cursor
                                        ;   steps once for all of them: an
                                        ;   `inx` between the count and the
                                        ;   row wrote every selector into the
                                        ;   NEXT entry's byte, and the table
                                        ;   read rows 20 and 13 of a page that
                                        ;   holds three. The lobby still looked
                                        ;   right, because an unwritten row is
                                        ;   zeros and zeros displace nothing
    rts

; --- mil_band_emit: one band, however deep --------------------------------
; CONTRACT mil_band_emit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       A — the band's depth in scanlines, 0..SMIL_SCREEN_H
;             Y — the BG3VOFS value naming the row it reads
;             X — the byte cursor into the table
;   out:      the entries for that band, X advanced past them
;   clobbers: A, X, N, Z, C
;   tail:     rts
;
; A DEPTH OF ZERO WRITES NOTHING, which is what an empty band is: the hall's
; channel band closes as the lift rises and its deck band after it, and a band
; that has gone off the bottom of the picture must leave no entry rather than a
; zero-count one — a zero count byte is the TERMINATOR, and an entry carrying
; it would end the table early and leave every band below it unwritten.
mil_band_emit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mil_band_emit"
    cmp #0
    beq @done
@chunk:
    .a8
    .i16
    cmp #(SMIL_BAND_MAX + 1)
    bcc @tail
    pha                             ; deeper than one entry can hold: fill one
    lda #SMIL_BAND_MAX              ;   and carry the rest
    jsr mil_band_one
    pla
    sec
    sbc #SMIL_BAND_MAX
    bne @chunk
    bra @done
@tail:
    .a8
    .i16
    jsr mil_band_one
@done:
    .a8
    .i16
    rts

; --- mil_band_arm: the channel's slot, its seed, and its enable bit ---------
; CONTRACT mil_band_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the row-selecting channel's shadow slot filled and its bit ORed
;             into the scene_mgr HDMAEN shadow, which the NMI commits to $420C
;   clobbers: A, X, N, Z
;   assumes:  forced blank, at scene enter, AFTER scene_mgr's transition
;             shadow clear (the switch runs it before enter)
;   tail:     rts
mil_band_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_band_arm"
    sep #$20
    .a8
    ldx #(ES_H_MIL_BANDS_ROWSEL_CH * 16)
    lda #ES_H_MIL_BANDS_ROWSEL_DMAP
    sta f:ES_SM_HDMA_LONG + 0, x    ; DMAP: direct, mode 2 (write twice)
    lda #ES_H_MIL_BANDS_ROWSEL_BBAD
    sta f:ES_SM_HDMA_LONG + 1, x    ; BBAD -> BG3VOFS
    lda #<ES_MIL_BANDTAB
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T low
    lda #>ES_MIL_BANDTAB
    sta f:ES_SM_HDMA_LONG + 3, x    ; A1T high
    lda #ES_MIL_BANDTAB_BANK
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B: the WRAM bank the claim landed in
    ; ---- THE SHADOW MUST HOLD A STATE THE CHANNEL CAN RUN FROM, because it
    ; DOES run from it. The NMI copies this slot to $43x0-$43xA and sets
    ; HDMAEN in the same VBlank, and what the channel starts the next frame
    ; with is these bytes -- $4308/9, the current table address, and $430A,
    ; the line counter -- rather than only what the frame-start init derives
    ; from the table (SnesDmaController.cpp InitHdmaChannels, at scanline 0,
    ; reloads the counter from the table's first byte). MEASURED on this rail,
    ; three seeds, three pictures:
    ;
    ;   $430A = 0     "repeat, 127 lines": the counter decrements to $FF, bit
    ;                 7 is the repeat flag, so the channel transfers on EVERY
    ;                 line and walks the table pointer through WRAM. 433 reads
    ;                 of never-written memory on the lobby's first frame
    ;                 (rule 5's class), from past the table's end.
    ;   $430A = $7F   "hold 127 lines": no walk and no reads -- and the hold
    ;                 landed on EVERY frame, not just the arming one, so the
    ;                 first band's write reached BG3VOFS at line 128 and the
    ;                 top 128 lines of the picture read whichever row the port
    ;                 already held. The hall's machines stood still while its
    ;                 table advanced under them, which is the defect this
    ;                 comment's first draft shipped.
    ;   $430A = 1     one line, then the first entry loads from the table:
    ;                 no walk, no hold, zero uninitialised reads, and every
    ;                 band from the top of the picture.
    ;
    ; Why the $7F hold survived the frame-start init is not established by
    ; reading the emulator; the RULE this follows is the measurement, and it
    ; is the honest one either way -- seed the slot to something correct to
    ; run from rather than to something that merely stays quiet.
    lda #<ES_MIL_BANDTAB
    sta f:ES_SM_HDMA_LONG + 8, x    ; A2A = A1T, for the same reason
    lda #>ES_MIL_BANDTAB
    sta f:ES_SM_HDMA_LONG + 9, x
    lda #1
    sta f:ES_SM_HDMA_LONG + 10, x   ; NLTR: one line, then the first entry
    ; ---- ...and the enable bit, in the shadow the NMI writes to $420C ----
    lda z:ES_SM_NMI + 2
    ora #(1 << ES_H_MIL_BANDS_ROWSEL_CH)
    sta z:ES_SM_NMI + 2
    rep #$20
    .a16
    rts

; --- mil_band_lobby: the lobby's table, once at enter -----------------------
; CONTRACT mil_band_lobby
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      two bands: the room down to the floor reads the ZERO row, the
;             channel under it reads the RIPPLE row
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank, at scene enter
;   tail:     rts
;
; CONSTANT, because this room does not scroll: its floor is at SMIL_CHANNEL_Y
; on every frame it will ever draw, so the table is built once and the channel
; re-reads it at line 0 for free.
mil_band_lobby:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_band_lobby"
    sep #$20
    .a8
    ldx #0
    ldy #MIL_BAND_ROW_ZERO
    lda #SMIL_CHANNEL_Y             ; the wall, the bays and the floor plate
    jsr mil_band_emit
    ldy #MIL_BAND_ROW_RIPPLE
    lda #(SMIL_SCREEN_H - SMIL_CHANNEL_Y)
    jsr mil_band_emit               ; ...and the channel
    lda #0
    sta f:ES_MIL_BANDTAB_LONG, x    ; the terminator
    rep #$20
    .a16
    rts

; --- mil_band_hall: the hall's table, every armed VBlank --------------------
; CONTRACT mil_band_hall
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_MIL_CAM — the camera, in world pixels
;   out:      three bands, their depths taken from the camera: the machines
;             read the room's row, the deck the zero row, the channel the
;             ripple row
;   clobbers: A, X, Y, N, Z, C, ES_MIL_NMI_SCRATCH+12..15
;   assumes:  VBlank, from the rail's sm_nmi_hook
;   tail:     rts
;
; THE EDGES MOVE, and that is the half of the claim a fixed split cannot show.
; The deck and the channel are at fixed WORLD rows and the camera climbs, so
; their screen rows are DECK_ROW*8 - cam and MELT_ROW*8 - cam: at rest the
; channel is the bottom 56 lines, and by the time the car is a third of the way
; up it has closed and the hall reads one row again. Both are clamped to the
; picture's depth, which is what makes the closing bands write no entry.
mil_band_hall:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mil_band_hall"
    rep #$20
    .a16
    lda #(SMIL_DECK_ROW * 8)        ; ...where the deck is, on screen. The
    sec                             ;   camera never exceeds SMIL_CAM_MAX, so
    sbc z:ES_MIL_CAM                ;   this cannot go negative
    cmp #(SMIL_SCREEN_H + 1)
    bcc :+
    lda #SMIL_SCREEN_H              ; ...off the bottom: the machines fill it
:   .a16
    .i16
    sta z:ES_MIL_NMI_SCRATCH + 12
    lda #(SMIL_MELT_ROW * 8)        ; ...and the channel
    sec
    sbc z:ES_MIL_CAM
    cmp #(SMIL_SCREEN_H + 1)
    bcc :+
    lda #SMIL_SCREEN_H
:   .a16
    .i16
    sta z:ES_MIL_NMI_SCRATCH + 14
    sep #$20
    .a8
    ldx #0
    ldy #MIL_BAND_ROW_ROOM
    lda z:ES_MIL_NMI_SCRATCH + 12   ; the machines, the uprights and the car
    jsr mil_band_emit
    ldy #MIL_BAND_ROW_ZERO
    lda z:ES_MIL_NMI_SCRATCH + 14   ; ...the deck: the channel's top less the
    sec                             ;   deck's, which is the plate's depth
    sbc z:ES_MIL_NMI_SCRATCH + 12   ;   until the deck itself goes off screen
    jsr mil_band_emit
    ldy #MIL_BAND_ROW_RIPPLE
    lda #SMIL_SCREEN_H              ; ...and the channel: what is left
    sec
    sbc z:ES_MIL_NMI_SCRATCH + 14
    jsr mil_band_emit
    lda #0
    sta f:ES_MIL_BANDTAB_LONG, x    ; the terminator
    rts
