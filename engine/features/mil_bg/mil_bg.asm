; =============================================================================
; mil_bg.asm — BG1 at 8bpp and BG2 at 2bpp, on the same screen
; =============================================================================
; The keystone BG pattern, and the first instance of it in this tree where the
; two layers are at DIFFERENT DEPTHS. Mode 4 renders bg1 8bpp and bg2 2bpp, so
; the CHR arrives as two blobs at 64 and 16 bytes a tile instead of smelter's
; one shared 4bpp claim — and each claim NAMES ITS LAYER, so the allocator's O9
; joins the depth to the mode rather than leaving it to the art.
;
; WHAT IS NOT HERE: BGMODE (a [[claims.video]] claim), TM (composed from this
; feature's two screen designations), and the four scroll ports (mil_opt owns
; them — in an offset mode they are the FALLBACK an ungated column falls back
; to, not the picture's position).
;
; Every byte moves under the enter-time forced blank scene_mgr's switch
; contract guarantees, with NMI masked across it — forced blank does NOT mask
; NMI, $4200 bit 7 does, and an NMI landing mid-upload would re-point VMADD.

MIL_REGS = $4300 + ES_D_MIL_UP_CH * 16

; --- mil_up_dma: one VRAM upload. VMADD must already be set by the caller ---
; CONTRACT mil_up_dma
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the source low 16, Y = the byte count, A = the source bank
;   out:      the block transferred to VRAM from the caller's VMADD
;   clobbers: A, N, Z
;   assumes:  forced blank, and the enter-time window a dma_init claim names
;   tail:     rts
;
; DAS is single-shot — the transfer consumes it — so it is armed HERE, once a
; call, which is the only shape a caller cannot forget.
mil_up_dma:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_up_dma"
    stx a:MIL_REGS + 2              ; A1T
    sty a:MIL_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:MIL_REGS + 4              ; A1B — the bank the caller passed
    lda #ES_D_MIL_UP_DMAP
    sta a:MIL_REGS + 0              ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_MIL_UP_BBAD
    sta a:MIL_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_MIL_UP_CH)
    sta a:$420B
    rep #$20
    .a16
    rts

; --- mil_pal_up: N words of CGRAM from a blob ------------------------------
; CONTRACT mil_pal_up
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the CGRAM word index, X = the blob's low 16, Y = word count
;   out:      Y words written from the blob
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked
;   tail:     rts
;
; CGDATA is a BYTE port written low-then-high, so this is a CPU loop and not a
; transfer — the shape smt_bg, hz_bg and lake_bg all use.
;
; WIDTH-RISK: entry A16. The sep/rep pairs inside the loop are forced
; narrowings and the accumulator is A16 at every arrival of @word.
mil_pal_up:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_pal_up"
    sty z:ES_MIL_NMI_SCRATCH        ; the count. Safe: enter-time, no NMI
    sep #$20
    .a8
    sta a:$2121                     ; CGADD = the claim's word base
    rep #$20
    .a16
    ldy #0
@word:
    .a16
    .i16
    lda f:mil_pal_bin, x            ; ONE blob, two groups — X says which, and
    sep #$20                        ;   SMIL_PAL2_OFF is the generator's
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    iny
    cpy z:ES_MIL_NMI_SCRATCH
    bcc @word
    rts

; --- mil_arm_bg: the whole picture, once, at scene enter --------------------
; CONTRACT mil_arm_bg
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      BG1SC/BG2SC/BG12NBA from the claims, both CHR sets, both maps and
;             both palettes uploaded
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter contract
;   tail:     rts
;
; BG12NBA CARRIES BOTH CHR BASES IN ONE BYTE, three bits each, stepping 4096
; words — which is why the allocator's chr alignment is what makes either base
; expressible at all. The emitted _NBA symbols are those nibbles.
mil_arm_bg:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_arm_bg"
    sep #$20
    .a8
    lda #ES_V_MIL_MAP1_SC_BASE
    sta a:$2107                     ; BG1SC
    lda #ES_V_MIL_MAP2_SC_BASE
    sta a:$2108                     ; BG2SC
    lda #(ES_V_MIL_CHR1_NBA | (ES_V_MIL_CHR2_NBA << 4))
    sta a:$210B                     ; BG12NBA
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- BG1's 8bpp machinery ---------------------------------------------
    lda #ES_V_MIL_CHR1
    sta a:$2116
    ldx #.loword(mil_chr1_bin)
    ldy #ES_R_MIL_CHR1_SIZE
    lda #^mil_chr1_bin
    jsr mil_up_dma
    ; ---- BG2's 2bpp hall ---------------------------------------------------
    lda #ES_V_MIL_CHR2
    sta a:$2116
    ldx #.loword(mil_chr2_bin)
    ldy #ES_R_MIL_CHR2_SIZE
    lda #^mil_chr2_bin
    jsr mil_up_dma
    ; ---- the two maps ------------------------------------------------------
    lda #ES_V_MIL_MAP1
    sta a:$2116
    ldx #.loword(mil_map1_bin)
    ldy #ES_R_MIL_MAP1_SIZE
    lda #^mil_map1_bin
    jsr mil_up_dma
    lda #ES_V_MIL_MAP2
    sta a:$2116
    ldx #.loword(mil_map2_bin)
    ldy #ES_R_MIL_MAP2_SIZE
    lda #^mil_map2_bin
    jsr mil_up_dma
    ; ---- the palettes: BG2's four at 0, BG1's ramp set at 32 --------------
    lda #ES_C_MIL_PAL2
    ldx #SMIL_PAL2_OFF
    ldy #ES_C_MIL_PAL2_WORDS
    jsr mil_pal_up
    lda #ES_C_MIL_PAL1
    ldx #0
    ldy #ES_C_MIL_PAL1_WORDS
    jsr mil_pal_up
    rts

; --- mil_lobby_bases: BG1SC re-pointed at the lobby's map -------------------
; CONTRACT mil_lobby_bases
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      BG1SC at the lobby's tilemap; everything else unchanged
;   clobbers: A, N, Z
;   assumes:  forced blank at scene enter
;   tail:     rts
;
; THIS IS THE WHOLE COST OF A SECOND ROOM. The CHR page, both palettes, BG2's
; map and BG12NBA are identical across the edge — `mil_arm_bg` ran first and
; established all of them — so the two scenes differ by ONE REGISTER. That is
; what cutting both rooms against one shared tile set bought.
mil_lobby_bases:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_lobby_bases"
    sep #$20
    .a8
    lda #ES_V_MIL_LOBBY_SC_BASE
    sta a:$2107                     ; BG1SC
    rep #$20
    .a16
    rts

; --- mil_lobby_up: the lobby's tilemap into VRAM (scene enter) --------------
; CONTRACT mil_lobby_up
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the lobby map in its claimed page
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked
;   tail:     rts
mil_lobby_up:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mil_lobby_up"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_MIL_LOBBY
    sta a:$2116
    ldx #.loword(mil_lobby_bin)
    ldy #ES_R_MIL_LOBBY_SIZE
    lda #^mil_lobby_bin
    jsr mil_up_dma
    rts
