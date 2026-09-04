; =============================================================================
; aur_hue — the aurora's colour, cycling through blues and violets
; =============================================================================
; ON A DIRECT-COLOUR LAYER, COLOUR ANIMATION IS CHR TRAFFIC. A colour cycle is
; the classic indexed trick — rewrite one CGRAM word and every pixel using it
; changes at once, for two bytes. Direct colour gives that up: the pixel IS
; the colour, so there is no palette to cycle and the colour lives in the
; tiles. Twelve copies of every tile the aurora tints, 230,400 B, for what an
; indexed layer buys with two.
;
; THE PALETTE FIELD CANNOT DO IT. One low bit a channel — 2 of 31 in red and
; green, 4 in blue — will not carry a teal curtain to violet, and being per
; TILE anything driven by it moves in 8x8 blocks.
;
; A PHASE IS FIVE VBLANKS. The tinted tiles hold a CONTIGUOUS run of BG1 tile
; indices, so a fifth of them is one VMADD and one 3,840 B transfer; the run
; is assigned in a SCATTERED order, so that fifth is spread over the screen
; rather than sweeping down it. Then the picture holds, and the hold is
; counted down by the SCALED tick so a PAL console spends the same wall-clock
; time on the cycle.

AUR_HUE_REGS = $4300 + ES_D_AUR_HUE_UP_CH * 16
AUR_HUE_SPAN = AUR_HUE_PHASES * AUR_HUE_TILES   ; the source's wrap, in tiles

; The blob is bank_tiled at the LoROM window, so reaching a tile is a chunk
; and an offset inside it. AUR_HUE_PER_CHUNK (generated) is how many WHOLE
; 8bpp tiles a window holds, so a chunk boundary never splits a TILE.
;
; IT SPLITS TRANSFERS, THOUGH, and assuming otherwise was a real defect here.
; A chunk is 512 tiles and a slice is 50, so 7 of the cycle's 72 slices cross
; a boundary — and A1B is CONSTANT, so an uncut transfer wraps inside its own
; bank to $0000 and reads the WRAM mirror instead of the next chunk. Mesen's
; uninitialised-read detector named it immediately (a run of reads at
; $05:09F3), which a screenshot never would have: the picture was still
; recognisably an aurora, just with a few tiles of garbage in it.
;
; So a slice that crosses is armed as TWO transfers. The destination needs no
; second VMADD — the port auto-increments, so the second transfer continues
; exactly where the first stopped.

aur_hue_bank:
.repeat ::ES_R_AUR_HUE_CHUNKS, CI
    .byte .ident(.sprintf("ES_R_AUR_HUE_T%d_BANK", CI))
.endrepeat
aur_hue_addr:
.repeat ::ES_R_AUR_HUE_CHUNKS, CI
    .word .ident(.sprintf("ES_R_AUR_HUE_T%d_ADDR", CI))
.endrepeat

; --- aur_hue_xfer: one transfer out of one chunk ---------------------------
; CONTRACT aur_hue_xfer
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = byte offset inside the chunk, X = chunk index,
;             ES_AUR_TMP+4 = how many TILES to move
;   out:      the transfer has run; VMADD is left where the port advanced it,
;             which is what lets a split slice continue without a second VMADD
;   clobbers: A, X, Y, N, Z, C, DMA channel ES_D_AUR_HUE_UP_CH
;   assumes:  VMAIN and VMADD already set, and inside VBlank. DAS is re-armed
;             HERE, per transfer, because the channel consumes it
;   tail:     rts
aur_hue_xfer:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_hue_xfer"
    pha                             ; the byte offset, which A carries in
    txa
    asl a
    tay                             ; Y = chunk * 2, for the WORD table
    pla                             ; ...and the offset back. X is untouched
    clc                             ;   by `tay`, so it still names the chunk
    adc a:aur_hue_addr, y
    sta a:AUR_HUE_REGS + 2          ; A1T
    lda z:ES_AUR_TMP + 4
    .repeat 6
    asl a
    .endrepeat                      ; tiles -> bytes
    sta a:AUR_HUE_REGS + 5          ; DAS — re-armed for THIS transfer
    sep #$20
    .a8
    lda a:aur_hue_bank, x
    sta a:AUR_HUE_REGS + 4          ; A1B, the chunk's own bank
    lda #ES_D_AUR_HUE_UP_DMAP
    sta a:AUR_HUE_REGS + 0          ; DMAP: A->B, 2 regs write-once
    lda #ES_D_AUR_HUE_UP_BBAD
    sta a:AUR_HUE_REGS + 1          ; BBAD: VMDATAL
    lda #(1 << ES_D_AUR_HUE_UP_CH)
    sta a:$420B
    rep #$20
    .a16
    rts

; --- aur_hue_init ----------------------------------------------------------
; CONTRACT aur_hue_init
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       nothing
;   out:      the phase, the slice, both carried pointers, the hold and the
;             freeze all seeded — the source at the top of the blob, the
;             destination at the aurora's first BG1 tile
;   clobbers: A, N, Z
;   assumes:  enter-time, and that `aur_arm_bg` has already uploaded phase 0
;             as part of the base CHR page. Power-on dp is RANDOM (rule 5), so
;             this is the write-before-read contract for all six words
;   tail:     rts
aur_hue_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_hue_init"
    stz z:ES_AUR_PHASE
    stz z:ES_AUR_SLICE
    stz z:ES_AUR_HOLD
    stz z:ES_AUR_SRC                ; tile 0 of phase 0
    lda #(ES_V_AUR_CHR1 + AUR_HUE_BASE * 32)
    sta z:ES_AUR_DST                ; ...lands on the aurora's first tile
    lda #AUR_HUE_HOLD
    sta z:ES_AUR_WAIT               ; ...after one hold, so the boot picture
    rts                             ;   settles before the colour starts moving

; --- aur_hue_tick: count the hold down, at the region-correct rate ----------
; CONTRACT aur_hue_tick
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       A = whole ticks this frame (TS_STEP's output, so the fraction is
;             carried by the scaler); ES_AUR_HOLD nonzero freezes the cycle
;   out:      ES_AUR_WAIT reduced, floored at zero — and zero is what lets the
;             NMI hook move the next slice
;   clobbers: A, N, Z, C
;   assumes:  called once a frame from the main loop
;   tail:     rts
aur_hue_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_hue_tick"
    ldx z:ES_AUR_HOLD
    bne @done
    ldx z:ES_AUR_WAIT
    beq @done                       ; already armed; the NMI is doing the work
    sta z:ES_AUR_TMP + 0
    txa
    sec
    sbc z:ES_AUR_TMP + 0
    bcs :+
    lda #0                          ; the scaled step overshot the remainder
:   sta z:ES_AUR_WAIT
@done:
    .a16
    .i16
    rts

; --- aur_hue_nmi: ONE slice, or nothing ------------------------------------
; CONTRACT aur_hue_nmi
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_AUR_WAIT (zero = armed), ES_AUR_HOLD, ES_AUR_SRC, ES_AUR_DST,
;             ES_AUR_SLICE, ES_AUR_PHASE
;   out:      AUR_HUE_SLICE tiles replaced in BG1's CHR; the pointers advanced,
;             and on the last slice of a phase the hold re-armed
;   clobbers: A, X, Y, N, Z, C, VMAIN, VMADD, DMA channel ES_D_AUR_HUE_UP_CH
;   assumes:  called from the NMI hook, inside VBlank
;   tail:     rts
aur_hue_nmi:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "aur_hue_nmi"
    rep #$20
    .a16
    ; THE EARLY-OUT RETURNS HERE rather than branching to the tail: a `bne`
    ; over the whole body is 155 bytes and out of range, and the assembler
    ; says so. Frozen by B, or still holding between phases — either way
    ; there is nothing to move this frame.
    lda z:ES_AUR_HOLD
    ora z:ES_AUR_WAIT
    beq @run
    sep #$20
    .a8
    rts
@run:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda z:ES_AUR_DST
    sta a:$2116                     ; VMADD: this slice's contiguous run
    ; ---- where the slice starts: a chunk, and a tile offset inside it -----
    lda z:ES_AUR_SRC
    and #(AUR_HUE_PER_CHUNK - 1)
    sta z:ES_AUR_TMP + 0            ; the tile offset within the chunk
    lda z:ES_AUR_SRC
    .repeat ::AUR_HUE_CHUNK_SH
    lsr a
    .endrepeat
    sta z:ES_AUR_TMP + 2            ; ...and which chunk that is
    ; ---- how much of the slice fits before the boundary ------------------
    lda #AUR_HUE_PER_CHUNK
    sec
    sbc z:ES_AUR_TMP + 0            ; tiles left in this chunk
    cmp #AUR_HUE_SLICE
    bcc :+
    lda #AUR_HUE_SLICE              ; ...the whole slice fits
:   sta z:ES_AUR_TMP + 4
    lda z:ES_AUR_TMP + 0
    .repeat 6
    asl a
    .endrepeat                      ; the offset, in bytes
    ldx z:ES_AUR_TMP + 2
    jsr aur_hue_xfer
    ; ---- and the remainder, from the top of the NEXT chunk ----------------
    lda #AUR_HUE_SLICE
    sec
    sbc z:ES_AUR_TMP + 4
    beq @adv
    sta z:ES_AUR_TMP + 4
    ldx z:ES_AUR_TMP + 2
    inx
    lda #0
    jsr aur_hue_xfer
@adv:
    .a16
    .i16
    ; ---- advance ---------------------------------------------------------
    lda z:ES_AUR_SRC
    clc
    adc #AUR_HUE_SLICE
    sta z:ES_AUR_SRC
    lda z:ES_AUR_DST
    clc
    adc #(AUR_HUE_SLICE * 32)       ; 32 WORDS a tile at 8bpp
    sta z:ES_AUR_DST
    lda z:ES_AUR_SLICE
    inc a
    cmp #AUR_HUE_SLICES
    bcc @keep
    ; ---- a whole phase has landed: hold, and wrap --------------------------
    lda #0
    sta z:ES_AUR_SLICE
    lda #(ES_V_AUR_CHR1 + AUR_HUE_BASE * 32)
    sta z:ES_AUR_DST                ; back to the aurora's first tile
    lda z:ES_AUR_SRC
    cmp #AUR_HUE_SPAN
    bcc :+
    lda #0
    sta z:ES_AUR_SRC                ; ...and the cycle closes
:   lda z:ES_AUR_PHASE
    inc a
    cmp #AUR_HUE_PHASES
    bcc :+
    lda #0
:   sta z:ES_AUR_PHASE
    lda #AUR_HUE_HOLD
    sta z:ES_AUR_WAIT
    bra @out
@keep:
    .a16
    .i16
    sta z:ES_AUR_SLICE
@out:
    .a16
    .i16
    sep #$20
    .a8
    rts
