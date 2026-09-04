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
; THE RATE IS A CURVE AND NOTHING EVER HOLDS STILL. A phase is AUR_HUE_TILES
; updates however they are paced, so a slow cycle means a low AVERAGE rate and
; the shape is only free to redistribute it: the generated curve is a raised
; sine to the fourth, summing to exactly one phase, so the aurora drifts at a
; tile or two a frame and moves at six through the middle of a pass.
;
; The tinted tiles hold a CONTIGUOUS run of BG1 tile indices, so a frame's run
; of them is one VMADD and one transfer; the run is assigned in a SCATTERED
; order, so what changes is spread over the screen rather than sweeping down
; it.
;
; That leaves the picture permanently straddling two phases. Measured on the
; real quantised art, a 50/50 scattered mix of two adjacent phases is
; indistinguishable from either — which is what makes a continuous curve
; preferable to burst-and-hold here, and would not be true at a coarser phase
; step.

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
;   out:      the phase, the cursor, both carried pointers, the rate index,
;             the pending count and the freeze all seeded — the source at the
;             top of the blob, the destination at the aurora's first BG1 tile
;   clobbers: A, N, Z
;   assumes:  enter-time, and that `aur_arm_bg` has already uploaded phase 0
;             as part of the base CHR page. Power-on dp is RANDOM (rule 5), so
;             this is the write-before-read contract for all seven words
;   tail:     rts
aur_hue_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_hue_init"
    stz z:ES_AUR_PHASE
    stz z:ES_AUR_SLOT
    stz z:ES_AUR_HOLD
    stz z:ES_AUR_SRC                ; tile 0 of phase 0
    stz z:ES_AUR_RATEI
    stz z:ES_AUR_PEND
    lda #(ES_V_AUR_CHR1 + AUR_HUE_BASE * 32)
    sta z:ES_AUR_DST                ; ...lands on the aurora's first tile
    rts

; --- aur_hue_tick: read the curve, at the region-correct rate --------------
; CONTRACT aur_hue_tick
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       A = whole ticks this frame (TS_STEP's output, so the fraction is
;             carried by the scaler); ES_AUR_HOLD nonzero freezes the cycle
;   out:      ES_AUR_PEND raised by this frame's share of the curve, and
;             ES_AUR_RATEI advanced past the entries it read
;   clobbers: A, X, Y, N, Z, C
;   assumes:  called once a frame from the main loop
;   tail:     rts
;
; IT ACCUMULATES RATHER THAN ASSIGNS, and that is what keeps the pace
; region-correct: a PAL frame scales to two ticks, reads two entries of the
; curve, and the VBlank after it moves both entries' worth. Assigning would
; silently drop one and run the cycle slow.
aur_hue_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_hue_tick"
    ldy z:ES_AUR_HOLD
    bne @done
    tay                             ; Y = whole ticks this frame
    beq @done
    ; THE CURVE IS INDEXED WITH X, not Y, and that is the machine's choice
    ; rather than a style one: the 65816 has `long,X` and no `long,Y`, and the
    ; table lives in its own bank so the read has to be long.
    ldx z:ES_AUR_RATEI
@step:
    .a16
    .i16
    sep #$20
    .a8
    lda f:aur_rate_bin, x           ; LONG: the curve is in its own bank, and
                                    ;   `a:` with DB=0 reads bank 0 at the same
                                    ;   offset — which is linker FILL, so the
                                    ;   rate read as zero and the cycle stood
                                    ;   still with every other symbol correct
    rep #$20
    .a16
    and #$00FF
    clc
    adc z:ES_AUR_PEND
    sta z:ES_AUR_PEND
    inx
    cpx #AUR_RATE_LEN
    bcc :+
    ldx #0                          ; the curve closes
:   dey
    bne @step
    stx z:ES_AUR_RATEI
@done:
    .a16
    .i16
    rts

; --- aur_hue_nmi: this frame's run of tiles, whatever the curve asked for ---
; CONTRACT aur_hue_nmi
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_AUR_PEND, ES_AUR_HOLD, ES_AUR_SRC, ES_AUR_DST, ES_AUR_SLOT,
;             ES_AUR_PHASE
;   out:      up to ES_AUR_PEND tiles replaced in BG1's CHR, the pointers
;             advanced, and the phase stepped where the cursor wrapped. A run
;             that would cross the end of a phase is CLAMPED and the remainder
;             left in ES_AUR_PEND for the next frame, so the wrap costs one
;             frame of slightly fewer tiles rather than a second destination
;   clobbers: A, X, Y, N, Z, C, VMAIN, VMADD, DMA channel ES_D_AUR_HUE_UP_CH
;   assumes:  called from the NMI hook, inside VBlank
;   tail:     rts
aur_hue_nmi:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "aur_hue_nmi"
    rep #$20
    .a16
    ; Frozen by B, or the curve asked for nothing this frame. The early-out
    ; returns HERE rather than branching to the tail: a `bne` over the whole
    ; body is out of range, and the assembler says so.
    lda z:ES_AUR_HOLD
    bne @none
    lda z:ES_AUR_PEND
    bne @run
@none:
    .a16
    .i16
    sep #$20
    .a8
    rts
@run:
    .a16
    .i16
    ; ---- clamp the run to what is left of this phase ---------------------
    ; THE RUN'S LENGTH IS KEPT, not recomputed. `AUR_HUE_TILES - SLOT - PEND`
    ; only equals it on a frame the clamp fired; on every other frame PEND is
    ; zero and that expression is the room left in the phase, which is far
    ; more. Believing it walked the cursor past tiles that were never
    ; uploaded, and they stayed behind at whatever hue they last held — one
    ; bright square in the middle curtain, in a picture that otherwise looked
    ; completely right.
    sta z:ES_AUR_TMP + 6            ; the run, in tiles
    ldx #0                          ; X = the remainder to carry, if any
    lda #AUR_HUE_TILES
    sec
    sbc z:ES_AUR_SLOT               ; tiles left in the phase
    cmp z:ES_AUR_TMP + 6
    bcs @fits
    sta z:ES_AUR_TMP + 6            ; ...take only those
    lda z:ES_AUR_PEND
    sec
    sbc z:ES_AUR_TMP + 6
    tax                             ; ...and carry the rest to the next frame
@fits:
    .a16
    .i16
    stx z:ES_AUR_PEND
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda z:ES_AUR_DST
    sta a:$2116                     ; VMADD: this frame's contiguous run
    ; ---- where it starts: a chunk, and a tile offset inside it -----------
    lda z:ES_AUR_SRC
    and #(AUR_HUE_PER_CHUNK - 1)
    sta z:ES_AUR_TMP + 0            ; the tile offset within the chunk
    lda z:ES_AUR_SRC
    .repeat ::AUR_HUE_CHUNK_SH
    lsr a
    .endrepeat
    sta z:ES_AUR_TMP + 2            ; ...and which chunk that is
    ; ---- how much of it fits before the boundary -------------------------
    lda #AUR_HUE_PER_CHUNK
    sec
    sbc z:ES_AUR_TMP + 0            ; tiles left in this chunk
    cmp z:ES_AUR_TMP + 6
    bcc :+
    lda z:ES_AUR_TMP + 6            ; ...the whole run fits
:   sta z:ES_AUR_TMP + 4
    lda z:ES_AUR_TMP + 0
    .repeat 6
    asl a
    .endrepeat                      ; the offset, in bytes
    ldx z:ES_AUR_TMP + 2
    jsr aur_hue_xfer
    ; ---- and the remainder, from the top of the NEXT chunk ----------------
    lda z:ES_AUR_TMP + 6
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
    ; ---- advance, by the run this frame actually moved --------------------
    lda z:ES_AUR_SLOT
    clc
    adc z:ES_AUR_TMP + 6
    sta z:ES_AUR_SLOT
    lda z:ES_AUR_SRC
    clc
    adc z:ES_AUR_TMP + 6
    sta z:ES_AUR_SRC
    lda z:ES_AUR_TMP + 6
    .repeat 5
    asl a
    .endrepeat                      ; tiles -> WORDS: 32 a tile at 8bpp
    clc
    adc z:ES_AUR_DST
    sta z:ES_AUR_DST
    ; ---- a whole phase has landed: wrap ----------------------------------
    lda z:ES_AUR_SLOT
    cmp #AUR_HUE_TILES
    bcc @out
    stz z:ES_AUR_SLOT
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
@out:
    .a16
    .i16
    sep #$20
    .a8
    rts
