; =============================================================================
; aur_bg — the two layers, uploaded once and then left alone
; =============================================================================
; BG1 is the sky and the aurora at 8bpp, read as DIRECT COLOUR; BG2 is the
; hills, the cliff, the stars and the writing at 4bpp in one palette. Nothing
; here runs per frame: after `aur_arm_bg` the only VRAM this rail touches is
; the roll's thirteen map rows and the pen's tiles, and both are somebody
; else's feature.
;
; BG1 UPLOADS NO PALETTE, and that is not an omission. A direct-colour layer
; consults no CGRAM word at all (SnesPpu.cpp:1071), so the only palette blob
; here is BG2's sixteen and the figures' sixteen.

AUR_REGS = $4300 + ES_D_AUR_UP_CH * 16

; --- aur_up_dma: one VRAM transfer on the feature's own channel ------------
; CONTRACT aur_up_dma
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       X = source address, Y = byte count, A = source BANK
;   out:      the transfer has run
;   clobbers: A, X, Y, N, Z, and DMA channel ES_D_AUR_UP_CH
;   assumes:  the caller has already set VMAIN and VMADD, and is under forced
;             blank or inside VBlank. DAS is re-armed HERE, per transfer,
;             because the channel consumes it
;   tail:     rts
aur_up_dma:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_up_dma"
    stx a:AUR_REGS + 2              ; A1T
    sty a:AUR_REGS + 5              ; DAS — re-armed for THIS transfer
    sep #$20
    .a8
    sta a:AUR_REGS + 4              ; A1B, the bank the caller passed
    lda #ES_D_AUR_UP_DMAP
    sta a:AUR_REGS + 0              ; DMAP: A->B, 2 regs write-once
    lda #ES_D_AUR_UP_BBAD
    sta a:AUR_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_AUR_UP_CH)
    sta a:$420B
    rep #$20
    .a16
    rts

; --- aur_pal_up: one CGRAM group, straight out of the blob -----------------
; CONTRACT aur_pal_up
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       A = the group's CGRAM word base, X = its byte offset into
;             aur_pal_bin, Y = how many words
;   out:      those words are in CGRAM
;   clobbers: A, X, Y, N, Z, C, CGADD
;   assumes:  enter-time, so no NMI can be part-way through its own CGRAM work
;   tail:     rts
aur_pal_up:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_pal_up"
    sep #$20
    .a8
    sta a:$2121                     ; CGADD
    rep #$20
    .a16
@word:
    .a16
    .i16
    lda f:aur_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; CGDATA, low
    xba
    sta a:$2122                     ; ...then high
    rep #$20
    .a16
    inx
    inx
    dey
    bne @word
    rts

; --- aur_arm_bg: the whole picture into VRAM and CGRAM ---------------------
; CONTRACT aur_arm_bg
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       nothing — every address is an allocator symbol
;   out:      BG1/BG2 CHR and tilemaps uploaded, BG2's and the figures'
;             palettes uploaded, BG1SC/BG2SC/BG12NBA set
;   clobbers: A, X, Y, N, Z, C, VMAIN, VMADD, CGADD, DMA channel
;             ES_D_AUR_UP_CH
;   assumes:  FORCED BLANK. Four transfers totalling 31,744 B is far more
;             than a VBlank holds
;   tail:     rts
aur_arm_bg:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "aur_arm_bg"
    sep #$20
    .a8
    lda #ES_V_AUR_MAP1_SC_BASE
    sta a:$2107                     ; BG1SC
    lda #ES_V_AUR_MAP2_SC_BASE
    sta a:$2108                     ; BG2SC
    lda #(ES_V_AUR_CHR1_NBA | (ES_V_AUR_CHR2_NBA << 4))
    sta a:$210B                     ; BG12NBA
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    ; BOTH LAYERS ARE PINNED AT THE ORIGIN AND STAY THERE. This rail's whole
    ; argument is that the aurora does not move: the ordered dither that makes
    ; an 8bpp gradient readable is destroyed by sliding neighbouring scanlines
    ; across it. The scroll ports are written HERE, by the feature that claims
    ; them, rather than from the scene — ownership is not permission, and the
    ; scene has no business in a port whose whole job is to stay put.
    stz a:$210D                     ; BG1HOFS, low
    stz a:$210D                     ; ...and high — the port is write-twice
    stz a:$210E                     ; BG1VOFS
    stz a:$210E
    stz a:$210F                     ; BG2HOFS
    stz a:$210F
    stz a:$2110                     ; BG2VOFS
    stz a:$2110
    rep #$20
    .a16

    lda #ES_V_AUR_CHR1
    sta a:$2116
    ldx #.loword(aur_chr1_bin)
    ldy #ES_R_AUR_CHR1_SIZE
    lda #^aur_chr1_bin
    jsr aur_up_dma

    lda #ES_V_AUR_CHR2
    sta a:$2116
    ldx #.loword(aur_chr2_bin)
    ldy #ES_R_AUR_CHR2_SIZE
    lda #^aur_chr2_bin
    jsr aur_up_dma

    lda #ES_V_AUR_MAP1
    sta a:$2116
    ldx #.loword(aur_map1_bin)
    ldy #ES_R_AUR_MAP1_SIZE
    lda #^aur_map1_bin
    jsr aur_up_dma

    lda #ES_V_AUR_MAP2
    sta a:$2116
    ldx #.loword(aur_map2_bin)
    ldy #ES_R_AUR_MAP2_SIZE
    lda #^aur_map2_bin
    jsr aur_up_dma

    lda #ES_C_AUR_PAL2              ; BG2's sixteen, at CGRAM 0
    ldx #0
    ldy #ES_C_AUR_PAL2_WORDS
    jsr aur_pal_up
    lda #ES_C_AUR_OBJ_PAL           ; ...and the figures', at 128
    ldx #(ES_C_AUR_PAL2_WORDS * 2)
    ldy #ES_C_AUR_OBJ_PAL_WORDS
    jsr aur_pal_up
    rts
