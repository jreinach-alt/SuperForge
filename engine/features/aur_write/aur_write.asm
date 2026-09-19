; =============================================================================
; aur_write — "The End", delivered as a CHR delta stream
; =============================================================================
; The pen crosses tiles DIAGONALLY, so at any moment a tile is partly inked.
; Revealing by tilemap swap would climb the word in eight-pixel stairs, and
; generating CHR on the 65816 per frame is out of the question — so the tiles
; that change in each frame were computed at build time and this plays them
; back. Measured on this word: 168 uploads over 70 frames, never more than
; AUR_WRITE_PEAK in one of them.
;
; The stream is [count][ (tile u16, 32 B) x count ] per frame, in order, and
; the cursor only ever moves forward.

AUR_W_REGS = $4300 + ES_D_AUR_WRITE_UP_CH * 16

; --- aur_write_init --------------------------------------------------------
; CONTRACT aur_write_init
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       nothing
;   out:      the cursor, the frame count and the reset flag all zeroed
;   clobbers: N, Z
;   assumes:  enter-time. Power-on dp is RANDOM (rule 5)
;   tail:     rts
aur_write_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_write_init"
    stz z:ES_AUR_WPTR
    stz z:ES_AUR_WFRAME
    stz z:ES_AUR_WRESET
    rts

; --- aur_write_restart: ask VBlank to blank the word and start again --------
; CONTRACT aur_write_restart
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       nothing
;   out:      ES_AUR_WRESET set to the whole tile run; the next VBlanks erase
;             it a slice at a time and then rewind the stream
;   clobbers: A, N, Z
;   assumes:  main-loop. The blanking is 2,464 B and belongs in VBlank, so
;             this only raises the flag
;   tail:     rts
aur_write_restart:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_write_restart"
    lda #AUR_INK_TILES
    sta z:ES_AUR_WRESET
    rts

; --- aur_w_dma: one transfer on the feature's own channel -------------------
; CONTRACT aur_w_dma
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       X = source address, Y = byte count, A = source BANK
;   out:      the transfer has run
;   clobbers: A, X, Y, N, Z, DMA channel ES_D_AUR_WRITE_UP_CH
;   assumes:  VMAIN and VMADD already set, and inside VBlank
;   tail:     rts
aur_w_dma:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_w_dma"
    stx a:AUR_W_REGS + 2            ; A1T
    sty a:AUR_W_REGS + 5            ; DAS — re-armed for THIS transfer
    sep #$20
    .a8
    sta a:AUR_W_REGS + 4            ; A1B
    lda #ES_D_AUR_WRITE_UP_DMAP
    sta a:AUR_W_REGS + 0
    lda #ES_D_AUR_WRITE_UP_BBAD
    sta a:AUR_W_REGS + 1
    lda #(1 << ES_D_AUR_WRITE_UP_CH)
    sta a:$420B
    rep #$20
    .a16
    rts

; --- aur_write_nmi: this frame's tiles, or the replay's blanking ------------
; CONTRACT aur_write_nmi
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_AUR_WRESET, ES_AUR_WFRAME, ES_AUR_WPTR
;   out:      up to AUR_WRITE_PEAK CHR tiles uploaded and the cursor advanced;
;             or, on a reset frame, the pen's whole tile run restored to the
;             ground under the word and the cursor rewound
;   clobbers: A, X, Y, N, Z, C, VMAIN, VMADD, DMA channel
;             ES_D_AUR_WRITE_UP_CH
;   assumes:  called from the NMI hook, inside VBlank
;   tail:     rts
aur_write_nmi:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "aur_write_nmi"
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda z:ES_AUR_WRESET
    beq @play
    ; ---- the replay, A SLICE AT A TIME. The pen's tiles are the LAST run of
    ; the CHR page and they are emitted holding the GROUND under the word, so
    ; erasing is a DMA out of that same blob — no second copy of the picture
    ; in ROM. It is sliced because all 77 at once is 2,464 B in a VBlank that
    ; already carries a hue slice, and because a word that un-writes over five
    ; frames reads better than one that blinks out.
    ;
    ; ES_AUR_WRESET counts tiles REMAINING, so the run starts at
    ; AUR_INK_TILES - WRESET and the arithmetic needs no second cursor.
    sec
    lda #AUR_INK_TILES
    sbc z:ES_AUR_WRESET              ; the first tile of this slice
    pha
    asl a
    asl a
    asl a
    asl a                            ; x16 WORDS: a 4bpp tile is 32 B
    clc
    adc #(ES_V_AUR_CHR2 + AUR_INK_BASE * 16)
    sta a:$2116                      ; VMADD
    pla
    asl a
    asl a
    asl a
    asl a
    asl a                            ; x32 BYTES, into the blob
    clc
    adc #(.loword(aur_chr2_bin) + AUR_INK_OFF)
    tax
    ldy #(AUR_INK_SLICE * 32)
    lda z:ES_AUR_WRESET
    cmp #AUR_INK_SLICE
    bcs :+
    asl a
    asl a
    asl a
    asl a
    asl a                            ; ...the last slice is the remainder
    tay
:   lda #^aur_chr2_bin
    jsr aur_w_dma
    lda z:ES_AUR_WRESET
    sec
    sbc #AUR_INK_SLICE
    bcs :+
    lda #0
:   sta z:ES_AUR_WRESET
    bne :+
    stz z:ES_AUR_WPTR                ; erased: the pen starts again
    stz z:ES_AUR_WFRAME
:   sep #$20
    .a8
    rts
@play:
    .a16
    .i16
    ; HELD — by B, or by a beat that has not released the pen yet. Only the
    ; PLAY arm is gated: the erase above is a reset action, not the pen
    ; moving, and the beat that runs it holds everything by definition.
    lda z:ES_AUR_HOLD
    beq :+
    sep #$20
    .a8
    rts
:   .a16
    .i16
    lda z:ES_AUR_WFRAME
    cmp #AUR_WRITE_FRAMES
    bcs @spent                      ; the word is written; it just stands
    inc a
    sta z:ES_AUR_WFRAME
    ; THE CURSOR LIVES IN DP, NOT IN X. `aur_w_dma` declares X clobbered, and
    ; a loop that carried the cursor through the call would be relying on the
    ; body of a routine instead of on its contract — the exact shape rule 6
    ; exists for, one register wide.
    ldx z:ES_AUR_WPTR
    sep #$20
    .a8
    lda f:aur_write_bin, x          ; this frame's tile count
    rep #$20
    .a16
    and #$00FF
    inx
    stx z:ES_AUR_WPTR
    tay                             ; Y = count
    beq @spent
@tile:
    .a16
    .i16
    phy
    ldx z:ES_AUR_WPTR
    lda f:aur_write_bin, x          ; the tile index
    inx
    inx
    stx z:ES_AUR_WPTR
    asl a
    asl a
    asl a
    asl a                           ; x16 WORDS: a 4bpp tile is 32 B
    clc
    adc #ES_V_AUR_CHR2
    sta a:$2116                     ; VMADD: that tile's CHR
    lda z:ES_AUR_WPTR
    clc
    adc #.loword(aur_write_bin)
    tax                             ; A1T = the 32 bytes that follow
    ldy #32
    lda #^aur_write_bin
    jsr aur_w_dma
    lda z:ES_AUR_WPTR
    clc
    adc #32
    sta z:ES_AUR_WPTR               ; past the payload
    ply
    dey
    bne @tile
@spent:
    .a16
    .i16
    sep #$20
    .a8
    rts
