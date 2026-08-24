; =============================================================================
; sky_band.asm — the BG2 sky behind the Mode-1 HUD band
; =============================================================================
; CHR, tilemap and palette come from the sky_* claims (tools/gen_sky.py);
; the BG2 register bases come from the allocator's emitted encodings, never
; from mask arithmetic in ASM. Everything is written once, at scene enter,
; under forced blank — no channel, no WRAM, no per-frame cost.
;
; What makes it visible is split_band's TM table naming BG2 in the top band;
; what colours it is rgb_gradient's per-scanline COLDATA add. This file only
; puts the layer on screen.
;
; BG12NBA ($210B) holds BG1's CHR base in bits 0-3 and BG2's in bits 4-7.
; BG1 is the Mode-7 floor, whose CHR base register is ignored by the Mode-7
; address generator, and BG1 is not in the top band's TM anyway — so this
; feature owns the whole register and writes BG2's nibble with BG1's left 0.

; --- sky_arm: CHR + map + palette + BG2 registers (scene enter) -------------
; The enter-time GP-DMA register file, addressed through the channel the
; sky_up dma_init claim names — the channel number is a declared resource,
; not a hard-coded 0.
SKY_REGS = $4300 + ES_D_SKY_UP_CH * 16

; CONTRACT sky_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       the sky_chr / sky_map / sky_pal claims, and the allocator's
;             emitted BG2 register encodings — never mask arithmetic in
;             ASM
;   out:      CHR, tilemap and palette uploaded, and BG12NBA / BG2SC
;             written. This feature owns the whole of BG12NBA: BG1 is the
;             Mode-7 floor, whose CHR base the Mode-7 address generator
;             ignores, and BG1 is not in the top band's TM anyway
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter; there
;             is no channel, no WRAM and no per-frame cost
;   tail:     rts
sky_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sky_arm"
    ; ---- CHR -> the sky_chr claim (word port, DMA mode 1) -----------------
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after high byte
    rep #$20
    .a16
    lda #ES_V_SKY_CHR
    sta a:$2116                     ; VMADD = claim base
    lda #.loword(sky_chr_bin)
    sta a:SKY_REGS + 2                     ; A1T
    lda #ES_R_SKY_CHR_ROM_SIZE
    sta a:SKY_REGS + 5                     ; DAS
    sep #$20
    .a8
    lda #^sky_chr_bin
    sta a:SKY_REGS + 4                     ; A1B
    lda #ES_D_SKY_UP_DMAP
    sta a:SKY_REGS + 0                     ; DMAP: A->B, 2 regs write-once
    lda #ES_D_SKY_UP_BBAD
    sta a:SKY_REGS + 1                     ; BBAD: VMDATAL
    lda #(1 << ES_D_SKY_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs free)
    ; ---- tilemap -> the sky_map claim ------------------------------------
    ; DAS is single-shot: it was consumed by the transfer above, so re-arm
    ; it here (lessons_learned "DAS Is Single-Shot").
    rep #$20
    .a16
    lda #ES_V_SKY_MAP
    sta a:$2116                     ; VMADD = claim base
    lda #.loword(sky_map_bin)
    sta a:SKY_REGS + 2
    lda #ES_R_SKY_MAP_ROM_SIZE
    sta a:SKY_REGS + 5                     ; DAS re-armed
    sep #$20
    .a8
    lda #^sky_map_bin
    sta a:SKY_REGS + 4
    lda #ES_D_SKY_UP_DMAP
    sta a:SKY_REGS + 0
    lda #ES_D_SKY_UP_BBAD
    sta a:SKY_REGS + 1
    lda #(1 << ES_D_SKY_UP_CH)
    sta a:$420B
    ; ---- palette: the 4 ramp colours at the claimed CGRAM base ------------
    lda #ES_C_SKY_PAL
    sta a:$2121                     ; CGADD = claim base
    rep #$20
    .a16
    ldx #0
:   lda f:sky_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SKY_PAL_ROM_SIZE
    bcc :-
    ; ---- BG2 registers ----------------------------------------------------
    sep #$20
    .a8
    lda #ES_V_SKY_MAP_SC_BASE
    sta a:$2108                     ; BG2SC: 32x32 map at the claimed base
    lda #(ES_V_SKY_CHR_NBA << 4)
    sta a:$210B                     ; BG12NBA: BG2 chr base in bits 4-7
    ; scroll pinned at 0 — the band is a fixed vertical ramp, and a scene
    ; must not inherit whatever the previous one left latched here
    stz a:$210F                     ; BG2HOFS (write-twice)
    stz a:$210F
    stz a:$2110                     ; BG2VOFS (write-twice)
    stz a:$2110
    rep #$20
    .a16
    rts
