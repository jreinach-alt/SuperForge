; =============================================================================
; met_bg.asm — the Mode-1 platformer scene: CHR, palette, the painted level
; =============================================================================
; Everything here runs at scene ENTER, under forced blank with NMI masked (the
; scene_mgr enter contract). Room_bg's shape with this rail's blobs and one
; addition that carries the rail's crux: the level is painted into a WRAM
; TILEMAP SHADOW and the shadow is DMA'd to VRAM, so the scene's capture can
; READ what the PPU is displaying. VRAM is not CPU-readable during display, so
; the capture has to read a WRAM mirror; this is that mirror, owned by the one
; feature that writes it.
;
; The blob labels (`met_bg_chr_bin`, `met_bg_pal_bin`) are the game's .incbin
; claim sites in main.asm — the feature names them, the game backs them, and
; `make rom-unbacked` proves the bytes exist.

; The enter-time GP-DMA register file, addressed through the channel the
; met_bg_up dma_init claim names — a declared resource, not a hard-coded 0.
MET_BG_REGS = $4300 + ES_D_MET_BG_UP_CH * 16

; --- bg_arm: the whole Mode-1 layer (scene enter) --------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
;
; TWO transfers on the one declared channel, and DAS is armed inside EACH — it
; is single-shot, consumed by the transfer, so there is one arming site per
; transfer and it cannot be forgotten (room_bg.asm records the same
; reasoning).
;
; WIDTH-RISK: A16/I16 entry AND exit. Toggles A8 for byte-wide channel
; registers and PPU ports, `sep #$20` only — I-width never moves.
bg_arm:
    .a16
    .i16
    jsr bg_paint                    ; the shadow first: the DMA below reads it

    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    lda #ES_D_MET_BG_UP_DMAP
    sta a:MET_BG_REGS + 0           ; DMAP: A->B, 2 regs (mode 1)
    lda #ES_D_MET_BG_UP_BBAD
    sta a:MET_BG_REGS + 1           ; BBAD: VMDATAL, so B+1 = VMDATAH
    lda #^met_bg_chr_bin
    sta a:MET_BG_REGS + 4           ; A1B = source bank (ROM)
    rep #$20
    .a16
    lda #ES_V_BG_CHR
    sta a:$2116                     ; VMADD = the CHR base
    ldx #.loword(met_bg_chr_bin)
    stx a:MET_BG_REGS + 2           ; A1T
    ldy #ES_R_MET_BG_CHR_SIZE
    sty a:MET_BG_REGS + 5           ; DAS, armed for THIS transfer
    sep #$20
    .a8
    lda #(1 << ES_D_MET_BG_UP_CH)
    sta a:$420B                     ; fire

    ; ---- the tilemap: the shadow, straight out of WRAM --------------------
    lda #ES_BG_SHADOW_BANK
    sta a:MET_BG_REGS + 4           ; A1B = the shadow's WRAM bank
    rep #$20
    .a16
    lda #ES_V_BG_MAP
    sta a:$2116                     ; VMADD = the tilemap base
    ldx #ES_BG_SHADOW
    stx a:MET_BG_REGS + 2           ; A1T
    ldy #ES_BG_SHADOW_SIZE
    sty a:MET_BG_REGS + 5           ; DAS, re-armed for THIS transfer
    sep #$20
    .a8
    lda #(1 << ES_D_MET_BG_UP_CH)
    sta a:$420B                     ; fire

    ; ---- the palette: sixteen words at BG palette 0 -----------------------
    ; Word 0 is the backdrop as well as BG colour 0, which is why this
    ; feature claims it: there is no second owner to hand it to.
    lda #ES_C_BG_PAL
    sta a:$2121                     ; CGADD = 0, the claim's contract
    rep #$20
    .a16
    ldx #0
@pal:
    .a16
    .i16
    lda f:met_bg_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_MET_BG_PAL_SIZE
    bcc @pal

    ; ---- the two layout registers this feature owns -----------------------
    ; Both encodings are the ALLOCATOR's, emitted from the vram claims: BG1SC
    ; is (base >> 8) & $7C with the low two bits the 32x32 size code (0), and
    ; BG12NBA's low nibble is base >> 12. Narrating either from the address
    ; would be the second copy of the allocator's arithmetic docs/09 §4.4
    ; refuses.
    sep #$20
    .a8
    lda #ES_V_BG_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: tilemap base, 32x32
    lda #ES_V_BG_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 CHR base in the low nibble
    rep #$20
    .a16
    rts

; --- bg_paint: the level, into the tilemap shadow --------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; A tilemap word is tile id in bits 0-9, palette in 10-12, priority 13, flips
; 14-15 — palette 0 and priority 0 here, so the word IS the tile id and the
; blank fill is a zero fill of the shadow rather than a pattern.
;
; The geometry is meteor.inc's, with the platforms TWO rows tall so a 16x16
; captured block covers exactly its own cells.
bg_paint:
    .a16
    .i16
    ; ---- blank ------------------------------------------------------------
    ldx #0
@clear:
    .a16
    .i16
    stz a:ES_BG_SHADOW, x
    inx
    inx
    cpx #ES_BG_SHADOW_SIZE
    bcc @clear

    ; ---- the flat ground: rows 24..27, all 32 columns ---------------------
    ldy #MET_GND_ROW0
@grow:
    .a16
    .i16
    ldx #0
@gcol:
    .a16
    .i16
    jsr bg_set                      ; (col X, row Y) = MET_BG_PLAT
    inx
    cpx #MET_MAP_COLS
    bcc @gcol
    iny
    cpy #(MET_GND_ROW1 + 1)
    bcc @grow

    ; ---- platform A: rows 18..19, cols 6..9 -------------------------------
    ldy #MET_PLAT_A_R0
@pa_row:
    .a16
    .i16
    ldx #MET_PLAT_A_C0
@pa_col:
    .a16
    .i16
    jsr bg_set
    inx
    cpx #(MET_PLAT_A_C1 + 1)
    bcc @pa_col
    iny
    cpy #(MET_PLAT_A_R1 + 1)
    bcc @pa_row

    ; ---- platform B: rows 14..15, cols 20..23 -----------------------------
    ldy #MET_PLAT_B_R0
@pb_row:
    .a16
    .i16
    ldx #MET_PLAT_B_C0
@pb_col:
    .a16
    .i16
    jsr bg_set
    inx
    cpx #(MET_PLAT_B_C1 + 1)
    bcc @pb_col
    iny
    cpy #(MET_PLAT_B_R1 + 1)
    bcc @pb_row
    rts

; --- bg_set: shadow[row Y][col X] = the platform tile ----------------------
; In: A16/I16, DB=0. X = column, Y = row. Out: X and Y preserved; clobbers A.
; The word index is row*32 + col; the byte offset is twice that.
bg_set:
    .a16
    .i16
    phy
    phx
    tya
    .repeat 6
        asl                         ; row * 32 words * 2 bytes = row * 64
    .endrepeat
    sta z:ES_MET_DRAW + MET_D_TILE  ; borrow the draw scratch: nothing is
                                    ;  drawing while the level is painted
    txa
    asl                             ; col * 2 bytes
    clc
    adc z:ES_MET_DRAW + MET_D_TILE
    tax
    lda #MET_BG_PLAT
    sta a:ES_BG_SHADOW, x
    plx
    ply
    rts
